"""Background work for pull requests and incremental repository knowledge."""
import json
import hashlib
import re
import logging
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
from sqlalchemy import select, update
from . import ai, config
from .db import SessionLocal
from .coding_tasks import process_coding_task, process_coding_session
from .integrations import github_request, installation_token, pull_files
from .maintainer_context import format_context, load_context
from .models import BackgroundJob, BookDocument, RepoBookSection, PullRequest, Repository, UsageRecord

log = logging.getLogger("kodo.jobs")

BOT_MARKER = "<!-- kodo-ai-summary -->"
TEXT_SUFFIXES = {".py", ".js", ".ts", ".vue", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".sql", ".md", ".toml", ".yaml", ".yml", ".json", ".tsx", ".jsx", ".css", ".html", ".sh"}
BOOK_FILE_BATCH_SIZE = 10
BOOK_MODULE_BATCH_SIZE = 12
BOOK_GUIDE_SOURCE_LIMIT = 24
BOOK_GUIDE_SOURCE_CHARS = 22000
BOOK_FILE_CONTENT_CHARS = 5000
BOOK_IGNORED_DIRS = {".git", ".hg", ".svn", "node_modules", "vendor", "dist", "build", "coverage", ".venv", "venv", "__pycache__", "target", "bin", "obj", ".next", ".nuxt", "storybook-static", "site-packages", "Pods", "DerivedData"}
BOOK_IGNORED_FILES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "poetry.lock", "uv.lock", "cargo.lock", "go.sum", "composer.lock", "gemfile.lock", "pipfile.lock", "flake.lock"}

def _usage(db, repository_id, task, result):
    db.add(UsageRecord(repository_id=repository_id, task=task, model=result.get("model", "mock"), input_tokens=result.get("input_tokens", 0), output_tokens=result.get("output_tokens", 0), estimated_cost_usd=result.get("cost", 0)))

def _book_context(db, repo_id):
    docs = db.scalars(select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind.in_(["file", "module", "overview", "chapter"]), BookDocument.stale.is_(False)).order_by(BookDocument.kind)).all()
    return [f"{d.kind}: {d.title} ({d.path}) — {d.content}" for d in docs[:100]]

def process_pull_request(repo_id: int, number: int, payload: dict):
    db = SessionLocal()
    try:
        repo = db.get(Repository, repo_id)
        if not repo or not repo.enabled:
            log.info("PR review skipped: repository_id=%s enabled=%s pr=%s", repo_id, bool(repo and repo.enabled), number)
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

def _repository_text_entries(repo_name: str, branch: str, token: str) -> tuple[list[dict], bool]:
    """Use GitHub's recursive tree normally and walk subtrees if its 100k cap truncates."""
    ref = quote(branch, safe="")
    tree = github_request("GET", f"/repos/{repo_name}/git/trees/{ref}?recursive=1", token) or {}
    if not tree.get("truncated"):
        return tree.get("tree", []), False

    root = github_request("GET", f"/repos/{repo_name}/git/trees/{ref}", token) or {}
    if root.get("truncated"):
        raise RuntimeError("A repository directory contains more entries than GitHub can enumerate")
    found: list[dict] = []
    stack = [item for item in root.get("tree", []) if item.get("type") == "tree"]
    found.extend(item for item in root.get("tree", []) if item.get("type") == "blob")
    visited = 0
    while stack:
        directory = stack.pop()
        visited += 1
        if visited > 20000:
            raise RuntimeError("Repository has too many directories to safely enumerate")
        subtree = github_request("GET", f"/repos/{repo_name}/git/trees/{directory['sha']}", token) or {}
        if subtree.get("truncated"):
            raise RuntimeError("A repository directory contains more entries than GitHub can enumerate")
        for item in subtree.get("tree", []):
            path = f"{directory.get('path', '')}/{item.get('path', '')}".strip("/")
            entry = {**item, "path": path}
            if item.get("type") == "tree":
                stack.append(entry)
            elif item.get("type") == "blob":
                found.append(entry)
    return found, True

def _book_file_priority(path: str) -> tuple[int, str]:
    lower = path.lower()
    name = lower.rsplit("/", 1)[-1]
    if name.startswith("readme"):
        return (0, lower)
    if name.endswith(".md") and (lower.startswith("docs/") or "/docs/" in lower):
        return (1, lower)
    if _is_guide_source(path):
        return (2, lower)
    return (3, lower)

def _is_ignored_book_path(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    lower_parts = {part.lower() for part in parts[:-1]}
    name = parts[-1].lower()
    return bool(lower_parts & {item.lower() for item in BOOK_IGNORED_DIRS}) or name in BOOK_IGNORED_FILES or name.endswith((".min.js", ".min.css", ".map")) or ".generated." in name

def _fetch_repo_file_text(repo_name: str, branch: str, token: str, path: str) -> str:
    import base64
    content_data = github_request("GET", f"/repos/{repo_name}/contents/{quote(path, safe='/')}?ref={quote(branch, safe='')}", token)
    return base64.b64decode(content_data.get("content", "")).decode("utf-8", errors="replace")[:BOOK_FILE_CONTENT_CHARS]

def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]

def _report_book_progress(callback, phase: str, current: int, total: int, message: str):
    if callback:
        callback({"phase": phase, "current": current, "total": total, "message": message, "updated_at": datetime.utcnow().isoformat()})

def build_repo_book(repo_id: int, progress_callback=None):
    db = SessionLocal()
    try:
        repo = db.get(Repository, repo_id)
        if not repo or not repo.enabled:
            return True
        workspace_markdown, repository_markdown = load_context(db, repo.installation_id, repo_id)
        maintainer_context = format_context(workspace_markdown, repository_markdown)
        token = installation_token(repo.installation_id)
        meta = github_request("GET", f"/repos/{repo.full_name}", token)
        branch = meta.get("default_branch", "main")
        _report_book_progress(progress_callback, "discover", 0, 0, "Finding repository files")
        tree_entries, tree_was_truncated = _repository_text_entries(repo.full_name, branch, token)
        eligible = [
            item for item in tree_entries
            if item.get("type") == "blob" and item.get("path")
            and any(item["path"].lower().endswith(s) for s in TEXT_SUFFIXES)
            and item.get("size", 0) < 50000 and not _is_ignored_book_path(item["path"])
        ]
        eligible.sort(key=lambda item: _book_file_priority(item["path"]))
        entries = eligible[:max(1, config.MAX_REPO_FILES)]
        _report_book_progress(progress_callback, "index", 0, len(entries), f"Indexing 0 of {len(entries)} selected files")

        files_summary: list[tuple[str, str]] = []
        guide_material = []
        guide_chars = 0
        pending_files: list[dict] = []
        for offset in range(0, len(entries), BOOK_FILE_BATCH_SIZE):
            batch = entries[offset:offset + BOOK_FILE_BATCH_SIZE]
            files_to_fetch = []
            for item in batch:
                path = item["path"]
                is_guide_source = _is_guide_source(path) and len(guide_material) < BOOK_GUIDE_SOURCE_LIMIT and guide_chars < BOOK_GUIDE_SOURCE_CHARS
                previous = db.scalar(select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind == "file", BookDocument.path == path))
                unchanged = previous and previous.source_sha == item["sha"]
                code = None
                if unchanged:
                    previous.stale = False
                    files_summary.append((path, previous.content))
                    if not is_guide_source:
                        continue
                files_to_fetch.append((item, previous, bool(unchanged), is_guide_source))
            with ThreadPoolExecutor(max_workers=4) as pool:
                codes = list(pool.map(lambda work: _fetch_repo_file_text(repo.full_name, branch, token, work[0]["path"]), files_to_fetch))
            for (item, previous, unchanged, is_guide_source), code in zip(files_to_fetch, codes):
                path = item["path"]
                if is_guide_source and code and guide_chars < BOOK_GUIDE_SOURCE_CHARS:
                    extract = code[:min(6000, BOOK_GUIDE_SOURCE_CHARS - guide_chars)]
                    guide_material.append(f"SOURCE FILE: {path}\n{extract}")
                    guide_chars += len(extract)
                if not unchanged:
                    pending_files.append({"path": path, "sha": item["sha"], "content": code})

            for pending_batch in _chunks(pending_files, BOOK_FILE_BATCH_SIZE):
                context = "\n\n".join(f"FILE: {item['path']}\n{item['content']}" for item in pending_batch)
                try:
                    result = ai.analyze(
                        "repo_book_files_batch",
                        "Return ONLY JSON {\"files\":[{\"path\":string,\"summary\":string}]}. For every supplied file return one concise, concrete summary of its purpose and important logic. Describe only what that file shows. Do not add generic filler. Include each path exactly once.",
                        context,
                    )
                except ValueError:  # A structured batch response may be truncated; retry only its files individually.
                    result = ai.AIResult(files=[], input_tokens=0, output_tokens=0, model="batch_parse_fallback", cost=0)
                summaries = {row.get("path"): row.get("summary", "") for row in result.get("files", []) if isinstance(row, dict) and row.get("path")}
                missing = [item["path"] for item in pending_batch if not str(summaries.get(item["path"], "")).strip()]
                fallback_instructions = "Return ONLY JSON {\"summary\": string}. Explain this file's purpose and important logic from the supplied source. Be specific and concise; do not infer beyond the source."
                for path in missing:
                    item = next(value for value in pending_batch if value["path"] == path)
                    single = ai.analyze("book_file", fallback_instructions, f"Path: {path}\n\n{item['content']}")
                    summaries[path] = single.get("summary", "")
                    _usage(db, repo_id, "repo_book_file_fallback", single)
                    if not str(summaries[path]).strip():
                        raise ValueError("AI could not summarize a repository file")
                for item in pending_batch:
                    path = item["path"]
                    summary = str(summaries[path]).strip()
                    previous = db.scalar(select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind == "file", BookDocument.path == path))
                    if previous:
                        previous.title, previous.content, previous.source_sha = path.split("/")[-1], summary, item["sha"]
                        previous.stale, previous.updated_at = False, datetime.utcnow()
                    else:
                        db.add(BookDocument(repository_id=repo_id, kind="file", path=path, title=path.split("/")[-1], content=summary, source_sha=item["sha"]))
                    files_summary.append((path, summary))
                _usage(db, repo_id, "repo_book_files_batch", result)
                db.commit()
            pending_files.clear()
            processed = min(offset + len(batch), len(entries))
            _report_book_progress(progress_callback, "index", processed, len(entries), f"Indexed {processed} of {len(entries)} selected files")

        current_paths = {p for p, _ in files_summary}
        for doc in db.scalars(select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind == "file")).all():
            if doc.path not in current_paths:
                doc.stale = True
        files_summary.sort(key=lambda row: row[0])
        modules: dict[str, list] = {}
        for path, summary in files_summary:
            module = path.split("/")[0] if "/" in path else "Repository root"
            modules.setdefault(module, []).append((path, summary))
        _report_book_progress(progress_callback, "modules", 0, len(modules), f"Mapping {len(modules)} repository areas")
        module_summaries: dict[str, str] = {}
        pending_modules: list[tuple[str, list[tuple[str, str]], str]] = []
        for module, entries_for_module in modules.items():
            context = "\n".join(f"{p}: {s}" for p, s in entries_for_module)
            digest = hashlib.sha256(context.encode()).hexdigest()
            prior = db.scalar(select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind == "module", BookDocument.path == module))
            if not prior or prior.source_sha != digest or prior.stale:
                pending_modules.append((module, entries_for_module, digest))
            else:
                module_summaries[module] = prior.content
        for offset in range(0, len(pending_modules), BOOK_MODULE_BATCH_SIZE):
            batch = pending_modules[offset:offset + BOOK_MODULE_BATCH_SIZE]
            context = "\n\n".join(f"AREA: {module}\n" + "\n".join(f"{path}: {summary[:350]}" for path, summary in entries_for_module[:40]) for module, entries_for_module, _ in batch)
            result = ai.analyze(
                "repo_book_modules_batch",
                "Return ONLY JSON {\"modules\":[{\"path\":string,\"summary\":string}]}. For every supplied area, summarize the responsibilities and relationships visible in its file summaries. Include each area path exactly once. Do not guess what the product does.",
                context,
            )
            summaries = {row.get("path"): row.get("summary", "") for row in result.get("modules", []) if isinstance(row, dict) and row.get("path")}
            for module, entries_for_module, digest in batch:
                summary = str(summaries.get(module, "")).strip()
                if not summary:
                    summary = "\n".join(f"{path}: {text}" for path, text in entries_for_module[:20])[:5000]
                _upsert_book(db, repo_id, "module", module, module, summary, digest)
                module_summaries[module] = summary
            _usage(db, repo_id, "repo_book_modules_batch", result)
            db.commit()
            complete = min(offset + len(batch), len(pending_modules))
            _report_book_progress(progress_callback, "modules", complete, len(pending_modules), f"Mapped {complete} of {len(pending_modules)} changed areas")
        active_modules = set(modules)
        for doc in db.scalars(select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind == "module")).all():
            if doc.path not in active_modules:
                doc.stale = True

        module_context = "\n".join(f"{module}: {summary}" for module, summary in module_summaries.items())
        inventory = "\n".join(f"- {path}" for path, _ in files_summary)
        maintainer_sources = []
        if workspace_markdown.strip():
            maintainer_sources.append("SOURCE: Workspace context (maintainer-maintained Markdown)\n" + workspace_markdown)
        if repository_markdown.strip():
            maintainer_sources.append("SOURCE: Repository context (maintainer-maintained Markdown)\n" + repository_markdown)
        guide_context = (
            (("MAINTAINER-PROVIDED CONTEXT (use for product and operational understanding; repository-specific context overrides workspace context):\n"
             + "\n\n".join(maintainer_sources)[:18000] + "\n\n") if maintainer_context else "")
            + "REPOSITORY FILE INVENTORY (only these paths may be cited):\n" + inventory[:12000]
            + "\n\nMODULE SUMMARIES:\n" + module_context[:16000]
            + "\n\nDIRECT PRODUCT / OPERATIONS DOCUMENTATION:\n" + "\n\n".join(guide_material)
        )[:config.MAX_DIFF_CHARS]
        guide_digest = hashlib.sha256(guide_context.encode()).hexdigest()
        current_sections = db.scalars(select(RepoBookSection).where(RepoBookSection.repository_id == repo_id)).all()
        legacy_slugs = {"product-overview", "user-journeys", "business-context", "system-architecture", "data-and-integrations", "operate-and-deploy", "support-and-troubleshooting", "code-map", "glossary"}
        is_legacy_fixed_layout = len(current_sections) == 9 and {section.slug for section in current_sections} == legacy_slugs
        if not current_sections or is_legacy_fixed_layout or any(section.source_hash != guide_digest or section.stale for section in current_sections):
            _report_book_progress(progress_callback, "handbook", 0, 1, "Writing repository-specific handbook chapters")
            for section in current_sections:
                section.stale = True
            instructions = _repo_book_guide_instructions()
            result = ai.analyze("repo_book_guide", instructions, guide_context)
            allowed_paths = {path for path, _ in files_summary}
            if workspace_markdown.strip():
                allowed_paths.add("Workspace context")
            if repository_markdown.strip():
                allowed_paths.add("Repository context")
            generated = result.get("sections", [])
            replacement_sections = []
            seen_slugs = set()
            for row in (generated[:12] if isinstance(generated, list) else []):
                if not isinstance(row, dict):
                    continue
                title = str(row.get("title", "")).strip()[:255]
                if not title:
                    continue
                sources = [path for path in _clean_string_list(row.get("source_paths", []), 20) if path in allowed_paths]
                # Chapters without exact, current repository references are omitted;
                # this keeps unsupported taxonomy topics out of the book entirely.
                if not sources:
                    continue
                blocks = _clean_guide_blocks(row.get("blocks", []))
                summary = str(row.get("summary", "")).strip()[:3000]
                body_text = " ".join([summary, *_guide_block_text(blocks)])
                if len(body_text) < 100 or _is_empty_chapter_text(body_text):
                    continue
                slug_base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:70] or "chapter"
                slug = slug_base
                suffix = 2
                while slug in seen_slugs:
                    slug = f"{slug_base[:70-len(str(suffix))-1]}-{suffix}"
                    suffix += 1
                seen_slugs.add(slug)
                replacement_sections.append(RepoBookSection(
                    repository_id=repo_id, slug=slug,
                    title=title,
                    category=str(row.get("category", "Guide"))[:80],
                    audiences_json=json.dumps(_clean_string_list(row.get("audiences", []), 8)),
                    summary=summary, blocks_json=json.dumps(blocks),
                    source_paths_json=json.dumps(sources), source_hash=guide_digest,
                    stale=False, updated_at=datetime.utcnow(),
                ))
            db.query(RepoBookSection).filter(RepoBookSection.repository_id == repo_id).delete(synchronize_session=False)
            db.add_all(replacement_sections)
            _usage(db, repo_id, "repo_book_guide", result)
            # Remove obsolete short-form chapters after the structured handbook exists.
            db.query(BookDocument).filter(BookDocument.repository_id == repo_id, BookDocument.kind.in_(["overview", "chapter"])).delete(synchronize_session=False)
        index_manifest = {
            "branch": branch,
            "eligible_files": len(eligible),
            "indexed_files": len(entries),
            "omitted_files": max(0, len(eligible) - len(entries)),
            "file_limit": max(1, config.MAX_REPO_FILES),
            "tree_was_truncated": tree_was_truncated,
            "updated_at": datetime.utcnow().isoformat(),
        }
        _upsert_book(db, repo_id, "manifest", "", "Repository index", json.dumps(index_manifest), hashlib.sha256(json.dumps(index_manifest, sort_keys=True).encode()).hexdigest())
        db.commit()
        _report_book_progress(progress_callback, "complete", len(entries), len(entries), f"Indexed {len(entries)} of {len(eligible)} eligible files")
        return True
    except Exception as error:
        db.rollback()
        import logging
        logging.getLogger("kodo.jobs").exception("Handbook job failed (%s)", type(error).__name__)
        raise
    finally:
        db.close()

def _upsert_book(db, repo_id, kind, path, title, content, sha):
    doc = db.scalar(select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind == kind, BookDocument.path == path))
    if doc:
        doc.title, doc.content, doc.source_sha, doc.stale, doc.updated_at = title, content, sha, False, datetime.utcnow()
    else:
        db.add(BookDocument(repository_id=repo_id, kind=kind, path=path, title=title, content=content, source_sha=sha))

def _is_guide_source(path: str) -> bool:
    lower = path.lower()
    name = lower.rsplit("/", 1)[-1]
    return ("/docs/" in f"/{lower}/" or lower.startswith("docs/") or name.startswith(("readme", "contributing", "support", "operations", "runbook", "architecture", "security"))
            or name in {"makefile", "dockerfile", "docker-compose.yml", "docker-compose.yaml", "pyproject.toml", "package.json", "requirements.txt", "procfile"}
            or lower.startswith(".github/workflows/"))

def _clean_string_list(value, limit):
    if not isinstance(value, list): return []
    return [str(item)[:160] for item in value if isinstance(item, (str, int, float))][:limit]

def _clean_guide_blocks(value):
    if not isinstance(value, list): return []
    cleaned = []
    for block in value[:24]:
        if not isinstance(block, dict): continue
        kind = block.get("type")
        if kind in {"paragraph", "callout"}:
            text = str(block.get("text", "")).strip()[:2500]
            if _is_empty_chapter_text(text):
                continue
            if text: cleaned.append({"type": kind, **({"label": str(block.get("label", "Note"))[:80]} if kind == "callout" else {}), "text": text})
        elif kind in {"bullets", "steps"}:
            items = _clean_string_list(block.get("items", []), 16)
            if items: cleaned.append({"type": kind, "items": items})
        elif kind == "table":
            columns = _clean_string_list(block.get("columns", []), 6)
            rows = block.get("rows", [])
            if columns and isinstance(rows, list):
                cleaned_rows = [[str(cell)[:500] for cell in row[:len(columns)]] for row in rows[:20] if isinstance(row, list)]
                if cleaned_rows: cleaned.append({"type": "table", "columns": columns, "rows": cleaned_rows})
    return cleaned

def _repo_book_guide_instructions():
    return '''Return ONLY JSON with {"sections":[{"title":"...","category":"...","audiences":[...],"summary":"...","blocks":[...],"source_paths":[...]}]}. Create a repository-specific table of contents. Do not use a fixed set of chapter names or force standard product, business, operations, support, or architecture chapters. Infer useful chapters from the actual subsystems, product concepts, workflows, documentation, and boundaries visible in the supplied repository. Use natural titles that describe this repository's own features and concepts. Merge overlapping topics. Include a chapter only when the sources support a useful explanation. Return fewer chapters when evidence is limited; return [] rather than empty/template chapters when nothing meaningful can be written.

This is a practical guide for new hires and engineering, operations, support, and sales. Write plainly and explain local terms. Use maintainer context for product, users, business rules, and operational knowledge; use repository inventory, module summaries, and direct documentation for code behavior and implementation. Repository context takes precedence over workspace context when they conflict. Do not infer customers, market, business value, policies, deployment steps, commands, user journeys, or operational procedures unless those sources support them. Omit unsupported topics entirely; do not write “no information was provided”, “not documented”, generic placeholders, or evidence-gap chapters. Avoid generic introductions, repeated summaries, filler, and claims like “robust/scalable/seamless”.

Each chapter must teach a concrete repository-specific idea and include a short summary plus 2-6 useful blocks. Group related components; do not create one chapter per file or directory. Return at most 12 chapters so each one can be detailed and reviewed. Block formats: {"type":"paragraph","text":"..."}, {"type":"bullets","items":[...]}, {"type":"steps","items":[...]}, {"type":"table","columns":[...],"rows":[...]}, {"type":"callout","label":"...","text":"..."}. Prefer tables for mappings when useful. Use steps only for an evidenced sequence. Include relative paths inline in factual explanations. source_paths must cite exact supporting inventory paths and may cite the exact labels "Workspace context" or "Repository context" when maintainer Markdown supports a claim. Chapters without supporting sources must be omitted. Aim for 80-200 words per chapter, using more only where the repository has real detail. Audience values: everyone, developers, operations, support, sales.'''

def _guide_block_text(blocks):
    values = []
    for block in blocks:
        if "text" in block: values.append(block["text"])
        values.extend(block.get("items", []))
        for row in block.get("rows", []): values.extend(row)
    return values

def _is_empty_chapter_text(value: str) -> bool:
    return bool(re.search(r"(?:no\b[^.]{0,100}\b(?:was|were)\s+provided\b|no\b[^.]{0,80}\b(?:information|details|documentation|evidence|context)\s+(?:is|are)\s+(?:provided|available|documented)\b|not (?:documented|provided|available)|nothing (?:was )?provided)", value, re.IGNORECASE))

def run_background_job(job_id: int):
    """Claim a persisted job and retry transient failures, surviving process restarts."""
    rerun_requested = False
    db = SessionLocal()
    try:
        claimed = db.execute(update(BackgroundJob).where(BackgroundJob.id == job_id, BackgroundJob.state == "queued").values(state="running", updated_at=datetime.utcnow()))
        db.commit()
        if not claimed.rowcount:
            return
        job = db.get(BackgroundJob, job_id)
        kind, payload = job.kind, json.loads(job.payload)
        log.info("Background job claimed: job_id=%s kind=%s", job_id, kind)
    finally:
        db.close()
    succeeded, last_error = False, ""

    def save_progress(progress):
        progress_db = SessionLocal()
        try:
            row = progress_db.get(BackgroundJob, job_id)
            if row:
                data = json.loads(row.payload or "{}")
                data["progress"] = progress
                row.payload = json.dumps(data)
                row.updated_at = datetime.utcnow()
                progress_db.commit()
                payload["progress"] = progress
        finally:
            progress_db.close()

    max_attempts = 1 if kind in {"coding_task", "coding_session"} else 3
    for attempt in range(1, max_attempts + 1):
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
            log.info("Background job attempt started: job_id=%s kind=%s attempt=%s/%s", job_id, kind, attempt, max_attempts)
            if kind == "pull_request":
                succeeded = process_pull_request(payload["repository_id"], payload["number"], payload["event"])
            elif kind == "repo_book":
                succeeded = build_repo_book(payload["repository_id"], progress_callback=save_progress)
            elif kind == "coding_task":
                succeeded = process_coding_task(payload["task_id"])
            elif kind == "coding_session":
                succeeded = process_coding_session(payload["session_id"])
            else:
                last_error = "Unknown background job kind"
                break
            if succeeded:
                log.info("Background job attempt succeeded: job_id=%s kind=%s attempt=%s", job_id, kind, attempt)
                break
            last_error = "Job failed; retrying"
            log.warning("Background job attempt failed: job_id=%s kind=%s attempt=%s", job_id, kind, attempt)
        except Exception as error:
            last_error = type(error).__name__
            log.exception("Background job raised an exception: job_id=%s kind=%s attempt=%s error=%s", job_id, kind, attempt, error)
            if kind == "repo_book":
                progress = payload.get("progress", {})
                progress.update({"phase": "retrying", "message": f"Temporary failure ({last_error}); resuming saved batches", "updated_at": datetime.utcnow().isoformat()})
                save_progress(progress)
                payload["progress"] = progress
        if attempt < max_attempts:
            import time
            time.sleep(attempt * 2)
    db = SessionLocal()
    try:
        row = db.get(BackgroundJob, job_id)
        if row:
            final_payload = json.loads(row.payload or "{}")
            rerun_requested = kind == "coding_session" and bool(final_payload.pop("rerun_requested", False))
            row.payload = json.dumps(final_payload)
            row.state = "queued" if rerun_requested else "complete" if succeeded else "failed"
            row.last_error = "" if succeeded else last_error
            if not succeeded and kind == "repo_book":
                progress = json.loads(row.payload or "{}").get("progress", {})
                progress.update({"phase": "failed", "message": f"Failed after retries ({last_error})", "updated_at": datetime.utcnow().isoformat()})
                data = json.loads(row.payload or "{}")
                data["progress"] = progress
                row.payload = json.dumps(data)
            row.updated_at = datetime.utcnow()
            db.commit()
            log.info("Background job finished: job_id=%s kind=%s state=%s attempts=%s", job_id, kind, row.state, row.attempts)
    finally:
        db.close()
    if rerun_requested:
        threading.Thread(target=run_background_job, args=(job_id,), daemon=True).start()
