"""Pull-request analysis, summaries, and inline findings."""
import json
import logging
from datetime import datetime
from sqlalchemy import select

from .. import ai
from ..db import SessionLocal
from ..integrations import github_request, installation_token, pull_files
from ..models import BookDocument, Installation, PullRequest, Repository
from .common import _usage

log = logging.getLogger("kodo.jobs")

BOT_MARKER = "<!-- kodo-ai-summary -->"

def _book_context(db, repo_id):
    docs = db.scalars(select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind.in_(["file", "module", "overview", "chapter"]), BookDocument.stale.is_(False)).order_by(BookDocument.kind)).all()
    return [f"{d.kind}: {d.title} ({d.path}) — {d.content}" for d in docs[:100]]

def process_pull_request(repo_id: int, number: int, payload: dict):
    db = SessionLocal()
    try:
        repo = db.get(Repository, repo_id)
        installation = db.get(Installation, repo.installation_id) if repo else None
        if not repo or not repo.enabled or not repo.connected or not installation or installation.suspended or installation.workspace_id != repo.workspace_id:
            log.info("PR review skipped because repository access is inactive: repository_id=%s pr=%s", repo_id, number)
            return True
        pr_data = payload["pull_request"]
        event_sha = (pr_data.get("head") or {}).get("sha", "")
        log.info("PR review started: repo=%s pr=%s title=%r head=%s", repo.full_name, number, pr_data.get("title", ""), event_sha[:12])
        pr = db.scalar(select(PullRequest).where(PullRequest.repository_id == repo_id, PullRequest.number == number))
        if pr and pr.head_sha and event_sha and pr.head_sha != event_sha:
            log.info("PR review superseded: repo=%s pr=%s queued_head=%s latest_head=%s", repo.full_name, number, event_sha[:12], pr.head_sha[:12])
            return True  # a newer webhook already superseded this queued analysis
        if not pr:
            pr = PullRequest(repository_id=repo_id, number=number)
            db.add(pr)
        pr.title = pr_data.get("title", "")
        pr.author = (pr_data.get("user") or {}).get("login", "")
        pr.state = pr_data.get("state", "open")
        pr.head_sha = event_sha
        pr.url = pr_data.get("html_url", "")
        pr.status = "processing"
        db.commit()

        token = installation_token(repo.installation_id)
        files = pull_files(repo.full_name, number, token)
        log.info("PR review fetched files: repo=%s pr=%s files=%s", repo.full_name, number, len(files))
        context = ai.pr_prompt(pr.title, pr_data.get("body") or "", files, _book_context(db, repo_id))
        did_analyze = pr.analysis_sha != pr.head_sha or not pr.summary
        if did_analyze:
            log.info("PR analysis started: repo=%s pr=%s mode=%s", repo.full_name, number, repo.review_mode)
            result = ai.analyze("pr", ai.PR_INSTRUCTIONS, context, repo.review_mode)
            log.info("PR analysis finished: repo=%s pr=%s model=%s findings=%s", repo.full_name, number, result.get("model", "unknown"), len(result.get("findings", [])))
            pr.summary = result.get("summary", "")
            pr.findings_json = json.dumps(result.get("findings", []))
            pr.analysis_sha = pr.head_sha
        else:
            result = ai.AIResult(summary=pr.summary, findings=json.loads(pr.findings_json or "[]"), model="cached", input_tokens=0, output_tokens=0, cost=0)
        latest = github_request("GET", f"/repos/{repo.full_name}/pulls/{number}", token)
        if latest["head"]["sha"] != pr.head_sha:
            pr.status = "outdated"
            db.commit()
            log.info("PR review discarded as outdated: repo=%s pr=%s analyzed_head=%s current_head=%s", repo.full_name, number, pr.head_sha[:12], latest["head"]["sha"][:12])
            return True
        summary = result.get("summary", "")
        findings = result.get("findings", [])
        pr.summary = summary
        pr.findings_json = json.dumps(findings)
        pr.status = "complete"
        pr.updated_at = datetime.utcnow()
        if did_analyze:
            _usage(db, repo_id, "pull_request", result)
        db.commit()

        # Upsert the bot's single summary comment for this PR.
        comments = github_request("GET", f"/repos/{repo.full_name}/issues/{number}/comments", token, params={"per_page": 100}) or []
        body = f"{BOT_MARKER}\n## kodai summary\n\n{summary}\n\n_Review mode: {repo.review_mode} · Model: {result.get('model', 'mock')}_"
        bot_comment = next((c for c in comments if BOT_MARKER in c.get("body", "")), None)
        if bot_comment:
            github_request("PATCH", f"/repos/{repo.full_name}/issues/comments/{bot_comment['id']}", token, json={"body": body})
            log.info("PR summary comment updated: repo=%s pr=%s", repo.full_name, number)
        else:
            github_request("POST", f"/repos/{repo.full_name}/issues/{number}/comments", token, json={"body": body})
            log.info("PR summary comment created: repo=%s pr=%s", repo.full_name, number)

        by_path = {f["filename"]: f for f in files}
        inline = []
        for finding in findings:
            path = finding.get("path", "")
            line = finding.get("line")
            file = by_path.get(path)
            if not file or not file.get("patch") or not isinstance(line, int):
                continue
            if line not in _added_line_numbers(file["patch"]):
                continue
            inline.append({"path": path, "line": line, "side": "RIGHT", "body": f"**{finding.get('severity','medium').upper()}: {finding.get('title','Review finding')}**\n\n{finding.get('body','')}"})
        if inline:
            latest = github_request("GET", f"/repos/{repo.full_name}/pulls/{number}", token)
            if latest["head"]["sha"] == pr.head_sha:
                existing_comments = github_request("GET", f"/repos/{repo.full_name}/pulls/{number}/comments", token, params={"per_page": 100}) or []
                seen = {(c.get("commit_id"), c.get("path"), c.get("line"), c.get("body")) for c in existing_comments}
                inline = [c for c in inline if (pr.head_sha, c["path"], c["line"], c["body"]) not in seen]
                if inline:
                    github_request("POST", f"/repos/{repo.full_name}/pulls/{number}/reviews", token, json={"commit_id": pr.head_sha, "event": "COMMENT", "body": "kodai found actionable issues on changed lines.", "comments": inline[:20]})
                    log.info("PR inline findings posted: repo=%s pr=%s count=%s", repo.full_name, number, min(len(inline), 20))
                else:
                    log.info("PR inline findings skipped: repo=%s pr=%s reason=already_posted", repo.full_name, number)
        else:
            log.info("PR inline findings skipped: repo=%s pr=%s reason=no_findings_on_added_lines findings=%s", repo.full_name, number, len(findings))
        log.info("PR review completed: repo=%s pr=%s findings=%s analyzed=%s", repo.full_name, number, len(findings), did_analyze)
        return True
    except Exception as error:
        db.rollback()
        existing = db.scalar(select(PullRequest).where(PullRequest.repository_id == repo_id, PullRequest.number == number))
        if existing:
            existing.status = "failed"
            db.commit()
        # Let server logging capture exception type without credentials or response payloads.
        log.exception("Pull request processing failed: repo_id=%s pr=%s error=%s", repo_id, number, error)
        return False
    finally:
        db.close()

def _added_line_numbers(patch: str) -> set[int]:
    result, line = set(), 0
    for text in patch.splitlines():
        if text.startswith("@@"):
            try:
                line = int(text.split("+")[1].split(",")[0].split(" ")[0])
            except (IndexError, ValueError):
                continue
        elif text.startswith("+") and not text.startswith("+++"):
            result.add(line); line += 1
        elif text.startswith("-") and not text.startswith("---"):
            continue
        else:
            line += 1
    return result
