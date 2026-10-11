"""Background work for pull requests and incremental repository knowledge."""
import json
import hashlib
from datetime import datetime
from sqlalchemy import select, update
from . import ai, config
from .db import SessionLocal
from .integrations import github_request, installation_token, pull_files
from .models import BackgroundJob, BookDocument, PullRequest, Repository, UsageRecord

BOT_MARKER = "<!-- kodo-ai-summary -->"
TEXT_SUFFIXES = {".py", ".js", ".ts", ".vue", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".sql", ".md", ".toml", ".yaml", ".yml", ".json", ".tsx", ".jsx", ".css", ".html", ".sh"}

def _usage(db, repository_id, task, result):
    db.add(UsageRecord(repository_id=repository_id, task=task, model=result.get("model", "mock"), input_tokens=result.get("input_tokens", 0), output_tokens=result.get("output_tokens", 0), estimated_cost_usd=result.get("cost", 0)))

def _book_context(db, repo_id):
    docs = db.scalars(select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.stale.is_(False)).order_by(BookDocument.kind)).all()
    return [f"{d.kind}: {d.title} ({d.path}) — {d.content}" for d in docs[:100]]

def process_pull_request(repo_id: int, number: int, payload: dict):
    db = SessionLocal()
    try:
        repo = db.get(Repository, repo_id)
        if not repo or not repo.enabled:
            return True
        pr_data = payload["pull_request"]
        event_sha = (pr_data.get("head") or {}).get("sha", "")
        pr = db.scalar(select(PullRequest).where(PullRequest.repository_id == repo_id, PullRequest.number == number))
        if pr and pr.head_sha and event_sha and pr.head_sha != event_sha:
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
        context = ai.pr_prompt(pr.title, pr_data.get("body") or "", files, _book_context(db, repo_id))
        did_analyze = pr.analysis_sha != pr.head_sha or not pr.summary
        if did_analyze:
            result = ai.analyze("pr", ai.PR_INSTRUCTIONS, context, repo.review_mode)
            pr.summary = result.get("summary", "")
            pr.findings_json = json.dumps(result.get("findings", []))
            pr.analysis_sha = pr.head_sha
        else:
            result = ai.AIResult(summary=pr.summary, findings=json.loads(pr.findings_json or "[]"), model="cached", input_tokens=0, output_tokens=0, cost=0)
        latest = github_request("GET", f"/repos/{repo.full_name}/pulls/{number}", token)
        if latest["head"]["sha"] != pr.head_sha:
            pr.status = "outdated"
            db.commit()
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
        body = f"{BOT_MARKER}\n## Kodo AI summary\n\n{summary}\n\n_Review mode: {repo.review_mode} · Model: {result.get('model', 'mock')}_"
        bot_comment = next((c for c in comments if BOT_MARKER in c.get("body", "")), None)
        if bot_comment:
            github_request("PATCH", f"/repos/{repo.full_name}/issues/comments/{bot_comment['id']}", token, json={"body": body})
        else:
            github_request("POST", f"/repos/{repo.full_name}/issues/{number}/comments", token, json={"body": body})

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
                    github_request("POST", f"/repos/{repo.full_name}/pulls/{number}/reviews", token, json={"commit_id": pr.head_sha, "event": "COMMENT", "body": "Kodo found actionable issues on changed lines.", "comments": inline[:20]})
        return True
    except Exception as error:
        db.rollback()
        existing = db.scalar(select(PullRequest).where(PullRequest.repository_id == repo_id, PullRequest.number == number))
        if existing:
            existing.status = "failed"
            db.commit()
        # Let server logging capture exception type without credentials or response payloads.
        import logging
        logging.getLogger("kodo.jobs").exception("Pull request job failed (%s)", type(error).__name__)
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

def build_repo_book(repo_id: int):
    db = SessionLocal()
    try:
        repo = db.get(Repository, repo_id)
        if not repo or not repo.enabled:
            return True
        token = installation_token(repo.installation_id)
        meta = github_request("GET", f"/repos/{repo.full_name}", token)
        branch = meta.get("default_branch", "main")
        tree = github_request("GET", f"/repos/{repo.full_name}/git/trees/{branch}?recursive=1", token)
        entries = [x for x in tree.get("tree", []) if x.get("type") == "blob" and any(x["path"].endswith(s) for s in TEXT_SUFFIXES) and x.get("size", 0) < 50000][:config.MAX_REPO_FILES]
        files_summary = []
        for item in entries:
            previous = db.scalar(select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind == "file", BookDocument.path == item["path"]))
            if previous and previous.source_sha == item["sha"]:
                previous.stale = False
                files_summary.append((item["path"], previous.content))
                continue
            content_data = github_request("GET", f"/repos/{repo.full_name}/contents/{item['path']}?ref={branch}", token)
            import base64
            code = base64.b64decode(content_data.get("content", "")).decode("utf-8", errors="replace")[:12000]
            result = ai.analyze("book_file", "Return ONLY JSON {\"summary\": string}. Describe purpose, important logic, dependencies, and key symbols from this file. Be concise and factual.", f"Path: {item['path']}\n\n{code}")
            summary = result.get("summary", "")
            if previous:
                previous.content, previous.source_sha, previous.stale, previous.updated_at = summary, item["sha"], False, datetime.utcnow()
            else:
                db.add(BookDocument(repository_id=repo_id, kind="file", path=item["path"], title=item["path"].split("/")[-1], content=summary, source_sha=item["sha"]))
            _usage(db, repo_id, "repo_book_file", result)
            db.commit()
            files_summary.append((item["path"], summary))

        current_paths = {p for p, _ in files_summary}
        for doc in db.scalars(select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind == "file")).all():
            if doc.path not in current_paths:
                doc.stale = True
        modules: dict[str, list] = {}
        for path, summary in files_summary:
            module = path.split("/")[0] if "/" in path else "Repository root"
            modules.setdefault(module, []).append((path, summary))
        module_summaries = {}
        for module, entries_for_module in modules.items():
            context = "\n".join(f"{p}: {s}" for p, s in entries_for_module)
            digest = hashlib.sha256(context.encode()).hexdigest()
            prior = db.scalar(select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind == "module", BookDocument.path == module))
            if not prior or prior.source_sha != digest or prior.stale:
                result = ai.analyze("book_module", "Return ONLY JSON {\"summary\": string}. Explain module responsibilities, component relationships, and important flows based only on supplied file summaries.", context)
                _upsert_book(db, repo_id, "module", module, module, result.get("summary", ""), digest)
                _usage(db, repo_id, "repo_book_module", result)
                module_summaries[module] = result.get("summary", "")
            else:
                module_summaries[module] = prior.content
        overview_context = "\n".join(f"{module}: {summary}" for module, summary in module_summaries.items())
        overview_digest = hashlib.sha256(overview_context.encode()).hexdigest()
        prior = db.scalar(select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind == "overview", BookDocument.path == ""))
        if not prior or prior.source_sha != overview_digest or prior.stale:
            result = ai.analyze("book_overview", "Return ONLY JSON {\"summary\": string}. Write a navigable repository architecture overview: main modules, likely data flow and integrations, noting evidence limits.", overview_context)
            _upsert_book(db, repo_id, "overview", "", repo.full_name, result.get("summary", ""), overview_digest)
            _usage(db, repo_id, "repo_book_overview", result)
        chapters = db.scalars(select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind == "chapter")).all()
        if not chapters or any(d.source_sha != overview_digest or d.stale for d in chapters):
            chapter_result = ai.analyze("book_chapters", "Return ONLY JSON {\"chapters\":[{\"topic\":\"architecture|data_flow|integrations|business_logic\",\"title\":string,\"summary\":string}]}. Produce exactly four concise chapters: architecture, data flow, integrations, and key business logic. Base each only on the repository module summaries supplied; describe uncertainty instead of guessing.", overview_context)
            for chapter in chapter_result.get("chapters", []):
                topic = chapter.get("topic", "")
                if topic in {"architecture", "data_flow", "integrations", "business_logic"}:
                    _upsert_book(db, repo_id, "chapter", topic, chapter.get("title", topic.replace("_", " ").title()), chapter.get("summary", ""), overview_digest)
            _usage(db, repo_id, "repo_book_chapters", chapter_result)
        db.commit()
        return True
    except Exception as error:
        db.rollback()
        import logging
        logging.getLogger("kodo.jobs").exception("Repo Book job failed (%s)", type(error).__name__)
        return False
    finally:
        db.close()

def _upsert_book(db, repo_id, kind, path, title, content, sha):
    doc = db.scalar(select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind == kind, BookDocument.path == path))
    if doc:
        doc.title, doc.content, doc.source_sha, doc.stale, doc.updated_at = title, content, sha, False, datetime.utcnow()
    else:
        db.add(BookDocument(repository_id=repo_id, kind=kind, path=path, title=title, content=content, source_sha=sha))

def run_background_job(job_id: int):
    """Claim a persisted job and retry transient failures, surviving process restarts."""
    db = SessionLocal()
    try:
        claimed = db.execute(update(BackgroundJob).where(BackgroundJob.id == job_id, BackgroundJob.state == "queued").values(state="running", updated_at=datetime.utcnow()))
        db.commit()
        if not claimed.rowcount:
            return
        job = db.get(BackgroundJob, job_id)
        kind, payload = job.kind, json.loads(job.payload)
    finally:
        db.close()
    succeeded, last_error = False, ""
    for attempt in range(1, 4):
        db = SessionLocal()
        try:
            row = db.get(BackgroundJob, job_id)
            if not row:
                return
            row.attempts = attempt
            row.updated_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()
        try:
            if kind == "pull_request":
                succeeded = process_pull_request(payload["repository_id"], payload["number"], payload["event"])
            elif kind == "repo_book":
                succeeded = build_repo_book(payload["repository_id"])
            else:
                last_error = "Unknown background job kind"
                break
            if succeeded:
                break
            last_error = "Job failed; retrying"
        except Exception as error:
            last_error = type(error).__name__
        if attempt < 3:
            import time
            time.sleep(attempt * 2)
    db = SessionLocal()
    try:
        row = db.get(BackgroundJob, job_id)
        if row:
            row.state = "complete" if succeeded else "failed"
            row.last_error = "" if succeeded else last_error
            row.updated_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()
