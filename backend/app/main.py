"""Kodo AI GitHub App API."""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timedelta
from types import SimpleNamespace
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from itsdangerous import URLSafeTimedSerializer, BadSignature
from . import config
from . import ai
from .db import SessionLocal
from .integrations import github_request, installation_token
from .jobs import run_background_job
from .models import AgentTask, BackgroundJob, BookDocument, Installation, PullRequest, RepoBookSection, RepoChatMessage, Repository, UsageRecord, UserSession, WebhookDelivery
from .repo_chat import retrieve_book_context

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("kodo")
app = FastAPI(title="Kodo AI", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[config.FRONTEND_ORIGIN], allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type"])
SESSION_SECRET = os.getenv("KODO_SESSION_SECRET", "local-only-change-this-secret")
if os.getenv("ENVIRONMENT", "development").lower() == "production" and SESSION_SECRET == "local-only-change-this-secret":
    raise RuntimeError("KODO_SESSION_SECRET must be set in production")
serializer = URLSafeTimedSerializer(SESSION_SECRET)

def _cookie_secure() -> bool:
    configured = os.getenv("KODO_COOKIE_SECURE")
    return configured.lower() == "true" if configured is not None else os.getenv("ENVIRONMENT", "development").lower() == "production"

@app.on_event("startup")
async def resume_background_jobs():
    db = SessionLocal()
    try:
        rows = db.scalars(select(BackgroundJob).where(BackgroundJob.state.in_(["queued", "running"]))).all()
        job_ids = [row.id for row in rows]
        for row in rows:
            row.state = "queued"
        db.commit()
    finally:
        db.close()
    for job_id in job_ids:
        asyncio.create_task(asyncio.to_thread(run_background_job, job_id))

def _queue_job(db, tasks: BackgroundTasks, kind: str, dedupe_key: str, payload: dict):
    row = db.scalar(select(BackgroundJob).where(BackgroundJob.kind == kind, BackgroundJob.dedupe_key == dedupe_key))
    if row and row.state != "failed":
        return row
    if row:
        row.payload, row.state, row.attempts, row.last_error = json.dumps(payload), "queued", 0, ""
        row.updated_at = datetime.utcnow()
    else:
        row = BackgroundJob(kind=kind, dedupe_key=dedupe_key, payload=json.dumps(payload), state="queued")
        db.add(row)
    db.flush()
    tasks.add_task(run_background_job, row.id)
    return row

def _session(request: Request) -> dict:
    signed = request.cookies.get("kodo_session")
    if not signed:
        raise HTTPException(401, "Sign in with GitHub to continue")
    try:
        session_id = serializer.loads(signed, max_age=60 * 60 * 24 * 7)
    except BadSignature:
        raise HTTPException(401, "Session expired")
    db = SessionLocal()
    try:
        record = db.get(UserSession, session_id)
        if not record or record.expires_at < datetime.utcnow():
            raise HTTPException(401, "Session expired")
        return {"id": record.github_user_id, "login": record.login, "token": _decrypt_token(record.access_token)}
    finally:
        db.close()

def _user_installations(session: dict) -> set[int]:
    data = github_request("GET", "/user/installations", session["token"], params={"per_page": 100})
    return {x["id"] for x in data.get("installations", [])}

def _sync_user_repositories(db, session: dict) -> set[int]:
    """Refresh the local repo list so existing installations don't depend on webhook history."""
    data = github_request("GET", "/user/installations", session["token"], params={"per_page": 100})
    installations = data.get("installations", [])
    ids = {item["id"] for item in installations}
    for item in installations:
        account = item.get("account") or {}
        db.merge(Installation(
            id=item["id"], account=account.get("login", ""),
            account_type=account.get("type", "User"), suspended=bool(item.get("suspended_at")),
        ))
        if item.get("suspended_at"):
            continue
        token = installation_token(item["id"])
        visible = set()
        for page in range(1, 11):
            result = github_request("GET", "/installation/repositories", token,
                                    params={"per_page": 100, "page": page}) or {}
            batch = result.get("repositories", [])
            for repo in batch:
                visible.add(repo["id"])
                saved = db.get(Repository, repo["id"])
                if saved:
                    saved.installation_id = item["id"]
                    saved.full_name = repo["full_name"]
                    saved.private = repo.get("private", True)
                else:
                    db.add(Repository(
                        id=repo["id"], installation_id=item["id"],
                        full_name=repo["full_name"], private=repo.get("private", True),
                    ))
            if len(batch) < 100:
                break
        stale = db.scalars(select(Repository).where(
            Repository.installation_id == item["id"],
        )).all()
        for repo in stale:
            if repo.id not in visible:
                db.query(PullRequest).filter(PullRequest.repository_id == repo.id).delete()
                db.query(BookDocument).filter(BookDocument.repository_id == repo.id).delete()
                db.query(RepoBookSection).filter(RepoBookSection.repository_id == repo.id).delete()
                db.query(RepoChatMessage).filter(RepoChatMessage.repository_id == repo.id).delete()
                db.query(AgentTask).filter(AgentTask.repository_id == repo.id).delete()
                db.query(UsageRecord).filter(UsageRecord.repository_id == repo.id).delete()
                db.delete(repo)
    return ids

def _authorized_repo(db, repo_id: int, session: dict) -> Repository:
    repo = db.get(Repository, repo_id)
    if not repo or repo.installation_id not in _user_installations(session):
        raise HTTPException(404, "Repository not found")
    return repo

@app.get("/api/auth/github")
async def auth_start():
    client_id = os.getenv("GITHUB_CLIENT_ID")
    if not client_id:
        raise HTTPException(503, "Set GITHUB_CLIENT_ID to enable dashboard sign-in")
    state = secrets.token_urlsafe(24)
    response = RedirectResponse(f"https://github.com/login/oauth/authorize?client_id={client_id}&state={state}&scope=read:user", status_code=302)
    response.set_cookie("kodo_oauth_state", state, httponly=True, secure=_cookie_secure(), samesite="lax", max_age=600)
    return response

@app.get("/auth/callback")  # retain the callback path already configured in the GitHub App
@app.get("/api/auth/callback")
async def auth_callback(code: str, state: str, request: Request):
    if not hmac.compare_digest(request.cookies.get("kodo_oauth_state", ""), state):
        raise HTTPException(400, "Invalid OAuth state")
    client_id, secret = os.getenv("GITHUB_CLIENT_ID"), os.getenv("GITHUB_CLIENT_SECRET")
    if not client_id or not secret:
        raise HTTPException(503, "GitHub OAuth is not configured")
    import requests
    response = requests.post("https://github.com/login/oauth/access_token", json={"client_id": client_id, "client_secret": secret, "code": code, "state": state}, headers={"Accept": "application/json"}, timeout=20)
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise HTTPException(401, "GitHub sign-in failed")
    user = github_request("GET", "/user", token)
    session_id = secrets.token_urlsafe(32)
    db = SessionLocal()
    try:
        db.add(UserSession(id=session_id, github_user_id=user["id"], login=user["login"], access_token=_encrypt_token(token), expires_at=datetime.utcnow() + timedelta(days=7)))
        db.commit()
    finally:
        db.close()
    result = RedirectResponse(config.FRONTEND_ORIGIN, status_code=302)
    result.delete_cookie("kodo_oauth_state")
    result.set_cookie("kodo_session", serializer.dumps(session_id), httponly=True, secure=_cookie_secure(), samesite="lax", max_age=604800)
    return result

@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    try:
        session = _session(request)
        db = SessionLocal()
        db.query(UserSession).filter(UserSession.github_user_id == session["id"]).delete()
        db.commit(); db.close()
    except HTTPException:
        pass
    response.delete_cookie("kodo_session")
    return {"ok": True}

@app.get("/api/me")
async def me(request: Request):
    session = _session(request)
    return {"login": session["login"]}

@app.get("/api/installations")
async def installations(request: Request):
    session = _session(request)
    ids = _user_installations(session)
    db = SessionLocal()
    try:
        rows = db.scalars(select(Installation).where(Installation.id.in_(ids))).all() if ids else []
        return [{"id": x.id, "account": x.account, "account_type": x.account_type, "suspended": x.suspended} for x in rows]
    finally:
        db.close()

@app.get("/api/app-install-url")
async def app_install_url(request: Request):
    _session(request)
    slug = os.getenv("GITHUB_APP_SLUG", "")
    return {"url": f"https://github.com/apps/{slug}/installations/new" if slug else None}

@app.get("/api/repos")
async def repositories(request: Request):
    session = _session(request)
    db = SessionLocal()
    try:
        ids = _sync_user_repositories(db, session)
        db.commit()
        rows = db.scalars(select(Repository).where(Repository.installation_id.in_(ids))).all() if ids else []
        return [{"id": r.id, "installation_id": r.installation_id, "full_name": r.full_name, "private": r.private, "enabled": r.enabled, "review_mode": r.review_mode} for r in rows]
    finally:
        db.close()

@app.patch("/api/repos/{repo_id}")
async def update_repository(repo_id: int, request: Request):
    session = _session(request)
    body = await request.json()
    db = SessionLocal()
    try:
        repo = _authorized_repo(db, repo_id, session)
        if "enabled" in body: repo.enabled = bool(body["enabled"])
        if "review_mode" in body:
            if body["review_mode"] not in {"quick", "standard", "deep", "security"}:
                raise HTTPException(422, "Invalid review mode")
            repo.review_mode = body["review_mode"]
        db.commit()
        return {"id": repo.id, "enabled": repo.enabled, "review_mode": repo.review_mode}
    finally:
        db.close()

def _agent_task_response(task: AgentTask):
    return {
        "id": task.id, "repository_id": task.repository_id, "github_login": task.github_login,
        "title": task.title, "instructions": task.instructions, "state": task.state,
        "branch": task.branch, "commit_sha": task.commit_sha,
        "pull_request_number": task.pull_request_number, "pull_request_url": task.pull_request_url,
        "summary": task.summary, "error": task.error,
        "created_at": task.created_at.isoformat(), "updated_at": task.updated_at.isoformat(),
    }

@app.get("/api/repos/{repo_id}/tasks")
async def list_agent_tasks(repo_id: int, request: Request):
    session = _session(request)
    db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, session)
        rows = db.scalars(select(AgentTask).where(AgentTask.repository_id == repo_id).order_by(AgentTask.created_at.desc()).limit(50)).all()
        return [_agent_task_response(row) for row in rows]
    finally:
        db.close()

@app.post("/api/repos/{repo_id}/tasks", status_code=202)
async def create_agent_task(repo_id: int, request: Request, background_tasks: BackgroundTasks):
    if not config.CODING_TASKS_ENABLED:
        raise HTTPException(503, "Coding tasks are disabled by backend configuration")
    session = _session(request)
    body = await request.json()
    title = body.get("title", "") if isinstance(body, dict) else ""
    instructions = body.get("instructions", "") if isinstance(body, dict) else ""
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
        raise HTTPException(422, "Enter a task title up to 200 characters")
    if not isinstance(instructions, str) or len(instructions.strip()) < 10 or len(instructions) > 8000:
        raise HTTPException(422, "Describe the task in 10 to 8,000 characters")
    db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, session)
        active_count = db.scalar(select(func.count(AgentTask.id)).where(
            AgentTask.repository_id == repo_id, AgentTask.state.in_(["queued", "running"]),
        )) or 0
        if active_count:
            raise HTTPException(409, "This repository already has a coding task in progress")
        task = AgentTask(
            repository_id=repo_id, github_user_id=session["id"], github_login=session["login"],
            title=title.strip(), instructions=instructions.strip(), state="queued",
        )
        db.add(task)
        db.flush()
        job = _queue_job(db, background_tasks, "coding_task", f"agent-task:{task.id}", {"task_id": task.id})
        db.commit()
        db.refresh(task)
        return _agent_task_response(task)
    finally:
        db.close()

@app.get("/api/repos/{repo_id}/pulls")
async def pull_requests(repo_id: int, request: Request):
    session = _session(request); db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, session)
        rows = db.scalars(select(PullRequest).where(PullRequest.repository_id == repo_id).order_by(PullRequest.updated_at.desc()).limit(50)).all()
        return [{"number": x.number, "title": x.title, "author": x.author, "state": x.state, "head_sha": x.head_sha, "url": x.url, "summary": x.summary, "findings": json.loads(x.findings_json), "status": x.status, "updated_at": x.updated_at.isoformat()} for x in rows]
    finally: db.close()

@app.get("/api/repos/{repo_id}/book")
async def repo_book(repo_id: int, request: Request):
    session = _session(request); db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, session)
        docs = db.scalars(select(BookDocument).where(BookDocument.repository_id == repo_id).order_by(BookDocument.kind, BookDocument.path)).all()
        manifest = next((doc for doc in docs if doc.kind == "manifest"), None)
        try:
            build_summary = json.loads(manifest.content) if manifest else None
            if build_summary is not None:
                build_summary["stale"] = manifest.stale
        except json.JSONDecodeError:
            build_summary = None
        sections = db.scalars(select(RepoBookSection).where(RepoBookSection.repository_id == repo_id).order_by(RepoBookSection.category, RepoBookSection.slug)).all()
        return {
            "sections": [{"id": s.id, "slug": s.slug, "title": s.title, "category": s.category,
                "audiences": _json_list(s.audiences_json), "summary": s.summary, "blocks": _json_list(s.blocks_json),
                "source_paths": _json_list(s.source_paths_json), "stale": s.stale, "updated_at": s.updated_at.isoformat()} for s in sections],
            "documents": [{"id": d.id, "kind": d.kind, "path": d.path, "title": d.title, "content": d.content, "stale": d.stale, "updated_at": d.updated_at.isoformat()} for d in docs if d.kind != "manifest"],
            "build_summary": build_summary,
        }
    finally: db.close()

def _chat_message_json(message: RepoChatMessage) -> dict:
    try:
        sources = json.loads(message.sources_json or "[]")
    except json.JSONDecodeError:
        sources = []
    return {"id": message.id, "role": message.role, "content": message.content, "sources": sources, "created_at": message.created_at.isoformat()}

def _json_list(value: str) -> list:
    try:
        data = json.loads(value or "[]")
        return data if isinstance(data, list) else []
    except (TypeError, json.JSONDecodeError):
        return []

def _section_for_retrieval(section: RepoBookSection):
    blocks = _json_list(section.blocks_json)
    parts = [section.summary]
    for block in blocks:
        if not isinstance(block, dict): continue
        if block.get("type") in {"paragraph", "callout"}:
            parts.append(f"{block.get('label', '')}: {block.get('text', '')}".strip(": "))
        elif block.get("type") in {"bullets", "steps"}:
            parts.extend(str(value) for value in block.get("items", []))
        elif block.get("type") == "table":
            parts.extend(" | ".join(str(value) for value in [*block.get("columns", []), *row]) for row in block.get("rows", []))
    return SimpleNamespace(
        id=f"section-{section.id}", kind="section", title=section.title, path="",
        content="\n".join(parts), stale=section.stale, source_paths_json=section.source_paths_json,
    )

@app.get("/api/repos/{repo_id}/chat")
async def repo_chat_history(repo_id: int, request: Request):
    session = _session(request); db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, session)
        docs = db.scalars(select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind != "manifest")).all()
        sections = db.scalars(select(RepoBookSection).where(RepoBookSection.repository_id == repo_id)).all()
        rows = db.scalars(select(RepoChatMessage).where(
            RepoChatMessage.repository_id == repo_id,
            RepoChatMessage.github_user_id == session["id"],
        ).order_by(RepoChatMessage.created_at.desc(), RepoChatMessage.id.desc()).limit(60)).all()
        rows.reverse()
        book_is_mock = any("Mock Handbook" in doc.content or "mock mode" in doc.content.lower() for doc in docs) or any("AI is disabled" in section.summary for section in sections)
        return {"book_ready": bool(docs or sections), "book_is_mock": book_is_mock, "messages": [_chat_message_json(row) for row in rows]}
    finally:
        db.close()

@app.post("/api/repos/{repo_id}/chat")
async def ask_repo_chat(repo_id: int, request: Request):
    session = _session(request)
    body = await request.json()
    question = str(body.get("question", "")).strip()
    if not question:
        raise HTTPException(422, "Enter a question about this repository")
    if len(question) > 4000:
        raise HTTPException(422, "Questions must be 4,000 characters or fewer")

    db = SessionLocal()
    try:
        repo = _authorized_repo(db, repo_id, session)
        documents = db.scalars(select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind != "manifest").order_by(BookDocument.kind, BookDocument.path)).all()
        sections = db.scalars(select(RepoBookSection).where(RepoBookSection.repository_id == repo_id).order_by(RepoBookSection.slug)).all()
        if not documents and not sections:
            raise HTTPException(409, "Generate the Handbook before asking questions about this repository")
        if any("Mock Handbook" in doc.content or "mock mode" in doc.content.lower() for doc in documents) or any("AI is disabled" in section.summary for section in sections):
            raise HTTPException(409, "This Handbook contains mock summaries. Regenerate it with live AI before asking repository questions.")
        recent = db.scalars(select(RepoChatMessage).where(
            RepoChatMessage.repository_id == repo_id,
            RepoChatMessage.github_user_id == session["id"],
        ).order_by(RepoChatMessage.created_at.desc(), RepoChatMessage.id.desc()).limit(10)).all()
        recent.reverse()
        history = [{"role": row.role, "content": row.content} for row in recent]
        section_docs = [_section_for_retrieval(section) for section in sections]
        selected_sources = retrieve_book_context(question, [*section_docs, *documents])
        if not selected_sources:
            raise HTTPException(409, "The Handbook has no readable notes yet. Regenerate it, then try again.")
        user_message = RepoChatMessage(repository_id=repo_id, github_user_id=session["id"], role="user", content=question)
        db.add(user_message)
        db.commit()
        db.refresh(user_message)
        user_message_json = _chat_message_json(user_message)
    finally:
        db.close()

    source_refs = [{
        "title": item["doc"].title, "path": item["doc"].path,
        "kind": item["doc"].kind, "stale": item["doc"].stale,
        "source_paths": _json_list(getattr(item["doc"], "source_paths_json", "[]")),
    } for item in selected_sources]
    try:
        result = await asyncio.to_thread(ai.answer_repo_question, repo.full_name, question, history, selected_sources)
    except Exception as error:
        log.exception("Repository chat failed (%s)", type(error).__name__)
        raise HTTPException(502, "Kodo could not answer this question. Check the backend logs and try again.")

    db = SessionLocal()
    try:
        assistant_message = RepoChatMessage(
            repository_id=repo_id, github_user_id=session["id"], role="assistant",
            content=result["answer"], sources_json=json.dumps(source_refs),
        )
        db.add(assistant_message)
        db.add(UsageRecord(
            repository_id=repo_id, task="repo_chat", model=result["model"],
            input_tokens=result["input_tokens"], output_tokens=result["output_tokens"],
            estimated_cost_usd=result["cost"],
        ))
        db.commit()
        db.refresh(assistant_message)
        return {"user_message": user_message_json, "assistant_message": _chat_message_json(assistant_message)}
    finally:
        db.close()

@app.delete("/api/repos/{repo_id}/chat")
async def clear_repo_chat(repo_id: int, request: Request):
    session = _session(request); db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, session)
        db.query(RepoChatMessage).filter(
            RepoChatMessage.repository_id == repo_id,
            RepoChatMessage.github_user_id == session["id"],
        ).delete(synchronize_session=False)
        db.commit()
        return {"ok": True}
    finally:
        db.close()

@app.post("/api/repos/{repo_id}/book/rebuild")
async def rebuild_book(repo_id: int, request: Request, tasks: BackgroundTasks):
    session = _session(request); db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, session)
        queued_jobs = db.scalars(select(BackgroundJob).where(
            BackgroundJob.kind == "repo_book", BackgroundJob.state == "queued",
        )).all()
        for queued in queued_jobs:
            try:
                belongs_to_repo = json.loads(queued.payload).get("repository_id") == repo_id
            except (TypeError, ValueError):
                belongs_to_repo = False
            if belongs_to_repo:
                queued.state = "failed"
                queued.last_error = "Superseded by a manual Handbook regeneration"
                queued.updated_at = datetime.utcnow()
        # Regeneration replaces generated Handbook material while retaining usage history.
        db.query(BookDocument).filter(BookDocument.repository_id == repo_id).delete(synchronize_session=False)
        db.query(RepoBookSection).filter(RepoBookSection.repository_id == repo_id).delete(synchronize_session=False)
        db.query(RepoChatMessage).filter(
            RepoChatMessage.repository_id == repo_id,
            RepoChatMessage.github_user_id == session["id"],
        ).delete(synchronize_session=False)
        job = _queue_job(db, tasks, "repo_book", f"manual:{repo_id}:{secrets.token_urlsafe(8)}", {"repository_id": repo_id})
        db.commit()
        return {"status": job.state, "job_id": job.id}
    finally:
        db.close()

@app.get("/api/repos/{repo_id}/book/rebuild/{job_id}")
async def book_rebuild_status(repo_id: int, job_id: int, request: Request):
    session = _session(request); db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, session)
        job = db.get(BackgroundJob, job_id)
        if not job or job.kind != "repo_book" or json.loads(job.payload).get("repository_id") != repo_id:
            raise HTTPException(404, "Handbook job not found")
        payload = json.loads(job.payload or "{}")
        return {"state": job.state, "attempts": job.attempts, "error": job.last_error if job.state == "failed" else "", "progress": payload.get("progress")}
    finally:
        db.close()

@app.get("/api/usage")
async def usage(request: Request):
    session = _session(request); db = SessionLocal()
    try:
        ids = _user_installations(session)
        repo_ids = select(Repository.id).where(Repository.installation_id.in_(ids))
        rows = db.execute(select(UsageRecord.task, UsageRecord.model, func.sum(UsageRecord.input_tokens), func.sum(UsageRecord.output_tokens), func.sum(UsageRecord.estimated_cost_usd)).where(UsageRecord.repository_id.in_(repo_ids)).group_by(UsageRecord.task, UsageRecord.model)).all()
        return [{"task": x[0], "model": x[1], "input_tokens": x[2] or 0, "output_tokens": x[3] or 0, "estimated_cost_usd": round(x[4] or 0, 6)} for x in rows]
    finally: db.close()

@app.post("/github-webhook")
async def github_webhook(request: Request, tasks: BackgroundTasks):
    raw = await request.body()
    signature = request.headers.get("x-hub-signature-256", "")
    if not config.GITHUB_WEBHOOK_SECRET:
        raise HTTPException(503, "Webhook secret is not configured")
    expected = "sha256=" + hmac.new(config.GITHUB_WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(401, "Invalid webhook signature")
    delivery = request.headers.get("x-github-delivery")
    event = request.headers.get("x-github-event", "")
    if not delivery:
        raise HTTPException(400, "Missing delivery ID")
    payload = json.loads(raw or b"{}")
    db = SessionLocal()
    try:
        if db.get(WebhookDelivery, delivery):
            return {"success": True, "duplicate": True}
        db.add(WebhookDelivery(delivery_id=delivery))
        if event == "installation":
            install = payload.get("installation", {})
            action = payload.get("action")
            if action == "suspend":
                db.query(Installation).filter(Installation.id == install.get("id")).update({"suspended": True})
                db.query(Repository).filter(Repository.installation_id == install.get("id")).update({"enabled": False})
            elif action == "deleted":
                install_repos = db.scalars(select(Repository.id).where(Repository.installation_id == install.get("id"))).all()
                if install_repos:
                    db.query(PullRequest).filter(PullRequest.repository_id.in_(install_repos)).delete(synchronize_session=False)
                    db.query(BookDocument).filter(BookDocument.repository_id.in_(install_repos)).delete(synchronize_session=False)
                    db.query(RepoBookSection).filter(RepoBookSection.repository_id.in_(install_repos)).delete(synchronize_session=False)
                    db.query(RepoChatMessage).filter(RepoChatMessage.repository_id.in_(install_repos)).delete(synchronize_session=False)
                    db.query(AgentTask).filter(AgentTask.repository_id.in_(install_repos)).delete(synchronize_session=False)
                    db.query(UsageRecord).filter(UsageRecord.repository_id.in_(install_repos)).delete(synchronize_session=False)
                db.query(Repository).filter(Repository.installation_id == install.get("id")).delete()
                db.query(Installation).filter(Installation.id == install.get("id")).delete()
            elif action in {"created", "unsuspend", "new_permissions_accepted"}:
                account = install.get("account") or {}
                db.merge(Installation(id=install["id"], account=account.get("login", ""), account_type=account.get("type", "User"), suspended=False))
        elif event == "installation_repositories":
            install_id = payload.get("installation", {}).get("id")
            for r in payload.get("repositories_added", []):
                db.merge(Repository(id=r["id"], installation_id=install_id, full_name=r["full_name"], private=r.get("private", True), enabled=True))
            for r in payload.get("repositories_removed", []):
                db.query(Repository).filter(Repository.id == r["id"]).delete()
                db.query(PullRequest).filter(PullRequest.repository_id == r["id"]).delete()
                db.query(BookDocument).filter(BookDocument.repository_id == r["id"]).delete()
                db.query(RepoBookSection).filter(RepoBookSection.repository_id == r["id"]).delete()
                db.query(RepoChatMessage).filter(RepoChatMessage.repository_id == r["id"]).delete()
                db.query(AgentTask).filter(AgentTask.repository_id == r["id"]).delete()
                db.query(UsageRecord).filter(UsageRecord.repository_id == r["id"]).delete()
        elif event == "pull_request":
            pr = payload.get("pull_request", {})
            if payload.get("action") == "closed":
                repo = db.get(Repository, payload.get("repository", {}).get("id"))
                if repo:
                    saved = db.scalar(select(PullRequest).where(PullRequest.repository_id == repo.id, PullRequest.number == pr.get("number")))
                    if saved: saved.state = "closed"
            elif payload.get("action") in {"opened", "reopened", "synchronize", "ready_for_review"} and not pr.get("draft", False):
                repo = db.get(Repository, payload.get("repository", {}).get("id"))
                if repo and repo.enabled:
                    head_sha = (pr.get("head") or {}).get("sha", "unknown")
                    action = payload.get("action", "unknown")
                    saved = db.scalar(select(PullRequest).where(PullRequest.repository_id == repo.id, PullRequest.number == pr["number"]))
                    if not saved:
                        saved = PullRequest(repository_id=repo.id, number=pr["number"])
                        db.add(saved)
                    saved.title = pr.get("title", "")
                    saved.author = (pr.get("user") or {}).get("login", "")
                    saved.state = pr.get("state", "open")
                    saved.head_sha = head_sha
                    saved.url = pr.get("html_url", "")
                    saved.status = "pending"
                    saved.updated_at = datetime.utcnow()
                    _queue_job(db, tasks, "pull_request", f"{repo.id}:{pr['number']}:{head_sha}:{action}", {"repository_id": repo.id, "number": pr["number"], "event": payload})
        elif event == "push":
            repo_data = payload.get("repository", {})
            repo = db.get(Repository, repo_data.get("id"))
            if repo:
                db.query(BookDocument).filter(BookDocument.repository_id == repo.id).update({"stale": True})
                db.query(RepoBookSection).filter(RepoBookSection.repository_id == repo.id).update({"stale": True})
                if repo.enabled:
                    after = payload.get("after", "unknown")
                    _queue_job(db, tasks, "repo_book", f"push:{repo.id}:{after}", {"repository_id": repo.id})
        db.commit()
        return {"success": True}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

@app.get("/health")
async def health():
    return {"ok": True}

def _cipher():
    from cryptography.fernet import Fernet
    import base64
    secret = os.getenv("KODO_SESSION_SECRET", "local-only-change-this-secret").encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret).digest()))

def _encrypt_token(token: str) -> str:
    return _cipher().encrypt(token.encode()).decode()

def _decrypt_token(token: str) -> str:
    return _cipher().decrypt(token.encode()).decode()
