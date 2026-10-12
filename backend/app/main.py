"""kodai GitHub App API."""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import requests
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import quote
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from itsdangerous import URLSafeTimedSerializer, BadSignature
from . import config
from . import ai
from .db import SessionLocal
from .integrations import github_request, installation_token
from .jobs import run_background_job
from .models import AgentTask, BackgroundJob, BookDocument, ContextFile, Installation, PullRequest, RepoBookSection, RepoChatMessage, Repository, UsageRecord, UserSession, WebhookDelivery, WorkSession, WorkSessionPullRequest
from .maintainer_context import MAX_CONTEXT_CHARS, format_context, load_context
from .repo_chat import retrieve_book_context

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("kodo")
app = FastAPI(title="kodai", version="0.1.0")
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
        log.info("Resuming persisted background job: job_id=%s", job_id)
        asyncio.create_task(asyncio.to_thread(run_background_job, job_id))

def _queue_job(db, tasks: BackgroundTasks, kind: str, dedupe_key: str, payload: dict):
    row = db.scalar(select(BackgroundJob).where(BackgroundJob.kind == kind, BackgroundJob.dedupe_key == dedupe_key))
    requeueable = {"failed", "complete"} if kind == "coding_session" else {"failed"}
    if row and kind == "coding_session" and row.state == "running":
        data = json.loads(row.payload or "{}")
        data["rerun_requested"] = True
        row.payload = json.dumps(data)
        row.updated_at = datetime.utcnow()
        log.info("Coding session job has another queued task: job_id=%s", row.id)
        return row
    if row and row.state not in requeueable:
        log.info("Background job already exists: kind=%s job_id=%s state=%s dedupe_key=%s", kind, row.id, row.state, dedupe_key)
        return row
    if row:
        row.payload, row.state, row.attempts, row.last_error = json.dumps(payload), "queued", 0, ""
        row.updated_at = datetime.utcnow()
    else:
        row = BackgroundJob(kind=kind, dedupe_key=dedupe_key, payload=json.dumps(payload), state="queued")
        db.add(row)
    db.flush()
    tasks.add_task(run_background_job, row.id)
    log.info("Background job queued: kind=%s job_id=%s dedupe_key=%s", kind, row.id, dedupe_key)
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
        return {
            "id": record.github_user_id, "login": record.login,
            "token": _decrypt_token(record.access_token), "session_id": record.id,
        }
    finally:
        db.close()

def _user_installations(session: dict) -> set[int]:
    data = _user_github_request(session, "GET", "/user/installations", params={"per_page": 100})
    return {x["id"] for x in data.get("installations", [])}

def _refresh_user_access_token(session: dict, rejected_token: str) -> str:
    """Rotate an expired GitHub App user token once, serializing concurrent requests."""
    client_id, client_secret = os.getenv("GITHUB_CLIENT_ID"), os.getenv("GITHUB_CLIENT_SECRET")
    db = SessionLocal()
    try:
        record = db.scalar(select(UserSession).where(UserSession.id == session["session_id"]).with_for_update())
        if not record:
            raise HTTPException(401, "Your GitHub session expired. Sign in again.")
        current_token = _decrypt_token(record.access_token)
        if current_token != rejected_token:
            return current_token  # Another request already refreshed the token.
        if not record.refresh_token or not client_id or not client_secret:
            raise HTTPException(401, "GitHub authorization expired. Sign in again to reconnect your account.")
        try:
            response = requests.post(
                "https://github.com/login/oauth/access_token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": _decrypt_token(record.refresh_token),
                },
                headers={"Accept": "application/json"}, timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            raise HTTPException(401, "GitHub authorization could not be renewed. Sign in again to reconnect your account.")
        new_access_token = payload.get("access_token")
        new_refresh_token = payload.get("refresh_token")
        if not new_access_token or not new_refresh_token:
            raise HTTPException(401, "GitHub authorization expired. Sign in again to reconnect your account.")
        now = datetime.utcnow()
        record.access_token = _encrypt_token(new_access_token)
        record.refresh_token = _encrypt_token(new_refresh_token)
        record.github_token_expires_at = now + timedelta(seconds=int(payload.get("expires_in", 28800)))
        record.refresh_token_expires_at = now + timedelta(seconds=int(payload.get("refresh_token_expires_in", 15897600)))
        db.commit()
        session["token"] = new_access_token
        return new_access_token
    except HTTPException:
        db.rollback()
        raise
    finally:
        db.close()

def _user_github_request(session: dict, method: str, path: str, **kwargs):
    token = session["token"]
    try:
        return github_request(method, path, token, **kwargs)
    except requests.HTTPError as error:
        if not error.response or error.response.status_code != 401:
            raise
    token = _refresh_user_access_token(session, token)
    try:
        return github_request(method, path, token, **kwargs)
    except requests.HTTPError as error:
        if error.response and error.response.status_code == 401:
            raise HTTPException(401, "GitHub authorization was rejected. Sign in again to reconnect your account.")
        raise

def _sync_user_repositories(db, session: dict) -> set[int]:
    """Refresh the local repo list so existing installations don't depend on webhook history."""
    data = _user_github_request(session, "GET", "/user/installations", params={"per_page": 100})
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
                db.query(WorkSession).filter(WorkSession.repository_id == repo.id).delete()
                db.query(UsageRecord).filter(UsageRecord.repository_id == repo.id).delete()
                db.delete(repo)
    return ids

def _authorized_repo(db, repo_id: int, session: dict) -> Repository:
    repo = db.get(Repository, repo_id)
    if not repo or repo.installation_id not in _user_installations(session):
        raise HTTPException(404, "Repository not found")
    return repo

@app.get("/api/auth/github")
async def auth_start(request: Request):
    client_id = os.getenv("GITHUB_CLIENT_ID")
    if not client_id:
        raise HTTPException(503, "Set GITHUB_CLIENT_ID to enable dashboard sign-in")
    state = secrets.token_urlsafe(24)
    authorize_url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={quote(client_id, safe='')}"
        f"&redirect_uri={quote(config.GITHUB_OAUTH_REDIRECT_URI, safe='')}"
        f"&state={quote(state, safe='')}&scope=offline_access"
    )
    response = RedirectResponse(authorize_url, status_code=302)
    # The callback may be registered at /auth/callback, outside the default
    # /api/auth cookie path inferred from this start URL.
    response.set_cookie("kodo_oauth_state", state, httponly=True, secure=_cookie_secure(), samesite="lax", max_age=600, path="/")
    log.info("Starting GitHub OAuth: host=%s secure_cookie=%s", request.headers.get("host", ""), _cookie_secure())
    return response

@app.get("/auth/callback")  # retain the callback path already configured in the GitHub App
@app.get("/api/auth/callback")
async def auth_callback(code: str, state: str, request: Request):
    saved_state = request.cookies.get("kodo_oauth_state", "")
    state_matches = bool(saved_state) and hmac.compare_digest(saved_state, state)
    if not state_matches:
        log.warning(
            "GitHub OAuth state validation failed: host=%s cookie_present=%s",
            request.headers.get("host", ""),
            bool(saved_state),
        )
        raise HTTPException(400, "Invalid OAuth state")
    client_id, secret = os.getenv("GITHUB_CLIENT_ID"), os.getenv("GITHUB_CLIENT_SECRET")
    if not client_id or not secret:
        raise HTTPException(503, "GitHub OAuth is not configured")
    response = requests.post(
        "https://github.com/login/oauth/access_token",
        json={
            "client_id": client_id,
            "client_secret": secret,
            "code": code,
            "state": state,
            "redirect_uri": config.GITHUB_OAUTH_REDIRECT_URI,
        },
        headers={"Accept": "application/json"},
        timeout=20,
    )
    response.raise_for_status()
    token_data = response.json()
    token = token_data.get("access_token")
    if not token:
        raise HTTPException(401, "GitHub sign-in failed")
    user = github_request("GET", "/user", token)
    session_id = secrets.token_urlsafe(32)
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        db.add(UserSession(
            id=session_id, github_user_id=user["id"], login=user["login"],
            access_token=_encrypt_token(token),
            refresh_token=_encrypt_token(token_data["refresh_token"]) if token_data.get("refresh_token") else "",
            github_token_expires_at=now + timedelta(seconds=int(token_data["expires_in"])) if token_data.get("expires_in") else None,
            refresh_token_expires_at=now + timedelta(seconds=int(token_data["refresh_token_expires_in"])) if token_data.get("refresh_token_expires_in") else None,
            expires_at=now + timedelta(days=7),
        ))
        db.commit()
    finally:
        db.close()
    result = RedirectResponse(config.FRONTEND_ORIGIN, status_code=302)
    result.delete_cookie("kodo_oauth_state", path="/")
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

@app.get("/api/context-files")
async def context_files(request: Request):
    session = _session(request)
    installation_ids = _user_installations(session)
    db = SessionLocal()
    try:
        repos = db.scalars(select(Repository).where(Repository.installation_id.in_(installation_ids))).all() if installation_ids else []
        repo_ids = [repo.id for repo in repos]
        filters = []
        if installation_ids:
            filters.append((ContextFile.scope == "installation") & ContextFile.scope_id.in_(installation_ids))
        if repo_ids:
            filters.append((ContextFile.scope == "repository") & ContextFile.scope_id.in_(repo_ids))
        rows = db.scalars(select(ContextFile).where(or_(*filters))).all() if filters else []
        return {
            "workspace": {str(row.scope_id): row.markdown for row in rows if row.scope == "installation"},
            "repository": {str(row.scope_id): row.markdown for row in rows if row.scope == "repository"},
        }
    finally:
        db.close()

def _save_context_file(db, scope: str, scope_id: int, markdown: str):
    row = db.scalar(select(ContextFile).where(ContextFile.scope == scope, ContextFile.scope_id == scope_id))
    if row:
        row.markdown = markdown
        row.updated_at = datetime.utcnow()
    else:
        db.add(ContextFile(scope=scope, scope_id=scope_id, markdown=markdown, updated_at=datetime.utcnow()))

@app.put("/api/installations/{installation_id}/context")
async def update_workspace_context(installation_id: int, request: Request):
    session = _session(request)
    if installation_id not in _user_installations(session):
        raise HTTPException(404, "Workspace not found")
    body = await request.json()
    markdown = body.get("markdown") if isinstance(body, dict) else None
    if not isinstance(markdown, str) or len(markdown) > MAX_CONTEXT_CHARS:
        raise HTTPException(422, f"Workspace Markdown must be {MAX_CONTEXT_CHARS:,} characters or fewer")
    db = SessionLocal()
    try:
        _save_context_file(db, "installation", installation_id, markdown)
        repo_ids = db.scalars(select(Repository.id).where(Repository.installation_id == installation_id)).all()
        if repo_ids:
            db.query(RepoBookSection).filter(RepoBookSection.repository_id.in_(repo_ids)).update({"stale": True}, synchronize_session=False)
            db.query(BookDocument).filter(BookDocument.repository_id.in_(repo_ids), BookDocument.kind.in_(["overview", "chapter"])).update({"stale": True}, synchronize_session=False)
        db.commit()
        return {"scope_id": installation_id, "markdown": markdown, "updated_at": datetime.utcnow().isoformat()}
    finally:
        db.close()

@app.put("/api/repos/{repo_id}/context")
async def update_repository_context(repo_id: int, request: Request):
    session = _session(request)
    body = await request.json()
    markdown = body.get("markdown") if isinstance(body, dict) else None
    if not isinstance(markdown, str) or len(markdown) > MAX_CONTEXT_CHARS:
        raise HTTPException(422, f"Repository Markdown must be {MAX_CONTEXT_CHARS:,} characters or fewer")
    db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, session)
        _save_context_file(db, "repository", repo_id, markdown)
        db.query(RepoBookSection).filter(RepoBookSection.repository_id == repo_id).update({"stale": True}, synchronize_session=False)
        db.query(BookDocument).filter(BookDocument.repository_id == repo_id, BookDocument.kind.in_(["overview", "chapter"])).update({"stale": True}, synchronize_session=False)
        db.commit()
        return {"scope_id": repo_id, "markdown": markdown, "updated_at": datetime.utcnow().isoformat()}
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
        "source_pull_request_number": task.source_pull_request_number,
        "source_finding_key": task.source_finding_key,
        "work_session_id": task.work_session_id,
        "work_session_pull_request_id": task.work_session_pull_request_id,
        "commit_sha": task.commit_sha, "summary": task.summary, "error": task.error,
        "created_at": task.created_at.isoformat(), "updated_at": task.updated_at.isoformat(),
    }

def _work_session_response(row, db, eligibility=None):
    tasks = db.scalars(select(AgentTask).where(AgentTask.work_session_id == row.id).order_by(AgentTask.created_at)).all()
    destinations = db.scalars(select(WorkSessionPullRequest).where(WorkSessionPullRequest.work_session_id == row.id).order_by(WorkSessionPullRequest.sequence)).all()
    eligibility = eligibility or {"can_continue": row.status != "paused", "can_retry": row.status == "paused", "reason": row.error, "pull_requests": {}}
    task_groups = {}
    for task in tasks:
        task_groups.setdefault(task.work_session_pull_request_id, []).append(task)
    return {
        "id": row.id, "title": row.title or "New work session", "status": row.status,
        "updated_at": row.updated_at.isoformat(),
        "error": row.error, "task_count": len(tasks), "queued_count": sum(item.state == "queued" for item in tasks),
        "pull_requests": [{
            "id": destination.id, "sequence": destination.sequence,
            "status": destination.status, "branch": destination.branch,
            "pull_request_number": destination.pull_request_number,
            "pull_request_url": destination.pull_request_url, "error": destination.error,
            "task_count": len(task_groups.get(destination.id, [])),
            "tasks": [_agent_task_response(item) for item in task_groups.get(destination.id, [])],
            "can_continue": eligibility.get("pull_requests", {}).get(destination.id, {}).get("can_continue", destination.status in {"planned", "open"}),
            "reason": eligibility.get("pull_requests", {}).get(destination.id, {}).get("reason", destination.error),
        } for destination in destinations],
        "can_continue": eligibility["can_continue"], "can_retry": eligibility["can_retry"],
        "can_start_new_pr": eligibility.get("can_start_new_pr", True),
        "reason": eligibility["reason"],
    }

def _verify_session_pull_request(repo, destination):
    """Return whether a destination still points at the same writable open PR."""
    if not destination.pull_request_number:
        return destination.status == "planned"
    try:
        token = installation_token(repo.installation_id)
        pull = github_request("GET", f"/repos/{repo.full_name}/pulls/{destination.pull_request_number}", token)
    except requests.HTTPError as error:
        status = error.response.status_code if error.response is not None else 0
        if status == 404:
            destination.status = "unavailable"
            destination.error = "This pull request is no longer available. The next task can start a new PR."
            return False
        raise HTTPException(503, "kodai could not verify the pull request. Try again shortly.")
    if pull.get("state") != "open":
        destination.status = "closed"
        destination.error = "This pull request is closed or merged. The next task can start a new PR."
        return False
    head = pull.get("head") or {}
    head_repo = (head.get("repo") or {}).get("full_name", "")
    if head_repo.casefold() != repo.full_name.casefold():
        destination.status = "ineligible"
        destination.error = "This PR uses a fork branch kodai cannot update. The next task can start a new PR."
        return False
    if destination.branch and head.get("ref") != destination.branch:
        destination.status = "ineligible"
        destination.error = "The PR branch changed. The next task can start a new PR."
        return False
    destination.status, destination.error = "open", ""
    return True


def _session_eligibility(repo, sessions, destinations):
    """Check PR destinations in one GitHub request; sessions may start another PR."""
    result = {row.id: {"can_continue": row.status != "paused", "can_retry": row.status == "paused", "can_start_new_pr": True, "reason": row.error, "pull_requests": {}} for row in sessions}
    active_destinations = [row for row in destinations if row.pull_request_number]
    open_prs = None
    lookup_error = ""
    if active_destinations:
        try:
            token = installation_token(repo.installation_id)
            open_prs = github_request("GET", f"/repos/{repo.full_name}/pulls", token, params={"state": "open", "per_page": 100}) or []
        except Exception:
            lookup_error = "kodai could not verify this pull request. Try refreshing in a moment."
    open_by_number = {pull.get("number"): pull for pull in (open_prs or [])}
    for destination in destinations:
        reason = ""
        target_valid = not destination.pull_request_number and destination.status == "planned"
        if destination.pull_request_number:
            pull = open_by_number.get(destination.pull_request_number)
            if lookup_error:
                target_valid, reason = False, lookup_error
            elif not pull:
                target_valid = False
                reason = "This PR is closed or unavailable. Start a new PR in this session."
                destination.status, destination.error, destination.updated_at = "closed", reason, datetime.utcnow()
            else:
                head = pull.get("head") or {}
                head_repo = (head.get("repo") or {}).get("full_name", "")
                if head_repo.casefold() != repo.full_name.casefold():
                    target_valid = False
                    reason = "This PR uses a fork branch kodai cannot update. Start a new PR in this session."
                    destination.status, destination.error = "ineligible", reason
                elif destination.branch and head.get("ref") != destination.branch:
                    target_valid = False
                    reason = "The PR branch changed. Start a new PR in this session."
                    destination.status, destination.error = "ineligible", reason
                else:
                    target_valid = True
                    destination.status, destination.error = "open", ""
        result[destination.work_session_id]["pull_requests"][destination.id] = {"can_continue": target_valid, "reason": reason}
    return result


def _new_session_pull_request(db, work_session):
    sequence = db.scalar(select(func.max(WorkSessionPullRequest.sequence)).where(
        WorkSessionPullRequest.work_session_id == work_session.id,
    )) or 0
    sequence += 1
    slug = re.sub(r"[^a-z0-9-]+", "-", work_session.title.lower()).strip("-")[:40] or "work"
    destination = WorkSessionPullRequest(
        work_session_id=work_session.id, repository_id=work_session.repository_id,
        sequence=sequence,
        branch=f"kodo/{slug}-{work_session.id}" + (f"-{sequence}" if sequence > 1 else ""),
        status="planned",
    )
    db.add(destination)
    db.flush()
    return destination

def _finding_key(finding: dict) -> str:
    canonical = {key: finding.get(key) for key in ("title", "path", "line", "severity", "body")}
    return hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

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

@app.get("/api/repos/{repo_id}/work-sessions")
async def list_work_sessions(repo_id: int, request: Request):
    session = _session(request)
    db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, session)
        rows = db.scalars(select(WorkSession).where(WorkSession.repository_id == repo_id).order_by(WorkSession.updated_at.desc()).limit(50)).all()
        destinations = db.scalars(select(WorkSessionPullRequest).where(WorkSessionPullRequest.work_session_id.in_([row.id for row in rows]))).all() if rows else []
        eligibility = _session_eligibility(db.get(Repository, repo_id), rows, destinations)
        db.commit()
        return [_work_session_response(row, db, eligibility[row.id]) for row in rows]
    finally:
        db.close()

@app.post("/api/repos/{repo_id}/work-sessions/{work_session_id}/retry", status_code=202)
async def retry_work_session(repo_id: int, work_session_id: int, request: Request, background_tasks: BackgroundTasks):
    session = _session(request)
    db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, session)
        work_session = db.scalar(select(WorkSession).where(WorkSession.id == work_session_id, WorkSession.repository_id == repo_id))
        if not work_session:
            raise HTTPException(404, "Work session not found")
        failed = db.scalar(select(AgentTask).where(AgentTask.work_session_id == work_session_id, AgentTask.state == "failed").order_by(AgentTask.created_at.desc()).limit(1))
        if not failed:
            raise HTTPException(409, "This session has no failed task to retry")
        failed.state, failed.error, failed.updated_at = "queued", "", datetime.utcnow()
        work_session.status, work_session.error, work_session.updated_at = "active", "", datetime.utcnow()
        _queue_job(db, background_tasks, "coding_session", f"agent-session:{work_session.id}", {"session_id": work_session.id})
        db.commit()
        return _work_session_response(work_session, db)
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
    source_pr_number = body.get("source_pull_request_number") if isinstance(body, dict) else None
    source_finding = body.get("source_finding") if isinstance(body, dict) else None
    work_session_id = body.get("work_session_id") if isinstance(body, dict) else None
    target_session_pr_id = body.get("work_session_pull_request_id") if isinstance(body, dict) else None
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
        raise HTTPException(422, "Enter a task title up to 200 characters")
    if not isinstance(instructions, str) or len(instructions.strip()) < 10 or len(instructions) > 8000:
        raise HTTPException(422, "Describe the task in 10 to 8,000 characters")
    if source_pr_number is None and source_finding is not None:
        raise HTTPException(422, "A source pull request is required for a finding task")
    if source_pr_number is not None and (not isinstance(source_pr_number, int) or isinstance(source_pr_number, bool) or source_pr_number <= 0 or not isinstance(source_finding, dict)):
        raise HTTPException(422, "Invalid source finding")
    if target_session_pr_id is not None and work_session_id is None:
        raise HTTPException(422, "Choose a session before selecting one of its pull requests")
    db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, session)
        source_key = ""
        if source_pr_number is not None:
            source_pr = db.scalar(select(PullRequest).where(PullRequest.repository_id == repo_id, PullRequest.number == source_pr_number))
            valid_findings = json.loads(source_pr.findings_json) if source_pr else []
            source_key = _finding_key(source_finding)
            if not any(_finding_key(item) == source_key for item in valid_findings if isinstance(item, dict)):
                raise HTTPException(422, "That finding is no longer available on the pull request. Refresh and try again.")
            existing = db.scalar(select(AgentTask).where(
                AgentTask.repository_id == repo_id,
                AgentTask.source_pull_request_number == source_pr_number,
                AgentTask.source_finding_key == source_key,
            ).order_by(AgentTask.created_at.desc()))
            if existing:
                return _agent_task_response(existing)
        work_session = None
        repo = db.get(Repository, repo_id)
        if target_session_pr_id is not None and (not isinstance(target_session_pr_id, int) or isinstance(target_session_pr_id, bool)):
            raise HTTPException(422, "Invalid session pull request")
        if work_session_id is not None:
            if not isinstance(work_session_id, int) or isinstance(work_session_id, bool):
                raise HTTPException(422, "Invalid work session")
            work_session = db.scalar(select(WorkSession).where(WorkSession.id == work_session_id, WorkSession.repository_id == repo_id).with_for_update())
            if not work_session:
                raise HTTPException(404, "Work session not found")
            if work_session.status == "paused" and target_session_pr_id is not None:
                raise HTTPException(409, "This session is paused after a failed task. Retry the failed task before continuing.")
        if not work_session:
            work_session = WorkSession(
                repository_id=repo_id, github_user_id=session["id"], title=title.strip(),
                status="active",
            )
            db.add(work_session)
            db.flush()
        elif not work_session.title:
            work_session.title = title.strip()
        destination = None
        if target_session_pr_id is not None:
            destination = db.scalar(select(WorkSessionPullRequest).where(
                WorkSessionPullRequest.id == target_session_pr_id,
                WorkSessionPullRequest.work_session_id == work_session.id,
            ))
            if not destination:
                raise HTTPException(404, "Session pull request not found")
            if not _verify_session_pull_request(repo, destination):
                log.info("Session PR is no longer eligible; routing task to a new PR: session_id=%s destination_id=%s", work_session.id, destination.id)
                destination = None
        if destination is None:
            destination = _new_session_pull_request(db, work_session)
        work_session.status, work_session.error = "active", ""
        work_session.updated_at = datetime.utcnow()
        task = AgentTask(
            repository_id=repo_id, github_user_id=session["id"], github_login=session["login"],
            title=title.strip(), instructions=instructions.strip(), state="queued",
            source_pull_request_number=source_pr_number, source_finding_key=source_key,
            work_session_id=work_session.id,
            work_session_pull_request_id=destination.id,
        )
        try:
            db.add(task)
            db.flush()
            _queue_job(db, background_tasks, "coding_session", f"agent-session:{work_session.id}", {"session_id": work_session.id})
            db.commit()
            log.info("Session task accepted: task_id=%s session_id=%s repo_id=%s title=%r requested_by=%s", task.id, work_session.id, repo_id, task.title, session["login"])
        except IntegrityError:
            db.rollback()
            if source_pr_number is not None:
                existing = db.scalar(select(AgentTask).where(
                    AgentTask.repository_id == repo_id,
                    AgentTask.source_pull_request_number == source_pr_number,
                    AgentTask.source_finding_key == source_key,
                ).order_by(AgentTask.created_at.desc()))
                if existing:
                    return _agent_task_response(existing)
            raise HTTPException(409, "This task was created at the same time by another request")
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
        linked_tasks = db.scalars(select(AgentTask).where(
            AgentTask.repository_id == repo_id, AgentTask.source_pull_request_number.is_not(None),
        ).order_by(AgentTask.created_at.desc())).all()
        task_by_finding = {(task.source_pull_request_number, task.source_finding_key): task for task in linked_tasks}
        session_pull_requests = {item.id: item for item in db.scalars(select(WorkSessionPullRequest).where(WorkSessionPullRequest.repository_id == repo_id)).all()}
        result = []
        for row in rows:
            findings = json.loads(row.findings_json)
            for finding in findings:
                if isinstance(finding, dict):
                    task = task_by_finding.get((row.number, _finding_key(finding)))
                    if task:
                        target_pr = session_pull_requests.get(task.work_session_pull_request_id)
                        finding["task"] = {
                            "id": task.id, "title": task.title, "state": task.state,
                            "created_at": task.created_at.isoformat(),
                            "pull_request_url": target_pr.pull_request_url if target_pr else "",
                        }
            result.append({"number": row.number, "title": row.title, "author": row.author, "state": row.state, "head_sha": row.head_sha, "url": row.url, "summary": row.summary, "findings": findings, "status": row.status, "updated_at": row.updated_at.isoformat()})
        return result
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
        maintainer_context = format_context(*load_context(db, repo.installation_id, repo_id))
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
        result = await asyncio.to_thread(ai.answer_repo_question, repo.full_name, question, history, selected_sources, maintainer_context)
    except Exception as error:
        log.exception("Repository chat failed (%s)", type(error).__name__)
        raise HTTPException(502, "kodai could not answer this question. Check the backend logs and try again.")

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
    log.info("GitHub webhook received: event=%s delivery=%s action=%s", event, delivery, payload.get("action", ""))
    db = SessionLocal()
    try:
        if db.get(WebhookDelivery, delivery):
            log.info("Duplicate GitHub webhook ignored: event=%s delivery=%s", event, delivery)
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
                    db.query(WorkSession).filter(WorkSession.repository_id.in_(install_repos)).delete(synchronize_session=False)
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
                db.query(WorkSession).filter(WorkSession.repository_id == r["id"]).delete()
                db.query(UsageRecord).filter(UsageRecord.repository_id == r["id"]).delete()
        elif event == "pull_request":
            pr = payload.get("pull_request", {})
            log.info("Pull request webhook: action=%s repo_id=%s pr=%s draft=%s", payload.get("action"), (payload.get("repository") or {}).get("id"), pr.get("number"), bool(pr.get("draft", False)))
            if payload.get("action") == "closed":
                repo = db.get(Repository, payload.get("repository", {}).get("id"))
                if repo:
                    saved = db.scalar(select(PullRequest).where(PullRequest.repository_id == repo.id, PullRequest.number == pr.get("number")))
                    if saved: saved.state = "closed"
                    destinations = db.scalars(select(WorkSessionPullRequest).where(WorkSessionPullRequest.repository_id == repo.id, WorkSessionPullRequest.pull_request_number == pr.get("number"))).all()
                    for destination in destinations:
                        destination.status = "closed"
                        destination.error = "The pull request is closed or merged. Start a new PR in this session to continue."
                        destination.updated_at = datetime.utcnow()
                    log.info("Pull request closed: repo=%s pr=%s", repo.full_name, pr.get("number"))
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
                elif repo:
                    log.info("PR review not queued: repo=%s pr=%s reason=repository_disabled", repo.full_name, pr.get("number"))
            else:
                reason = "draft_pull_request" if pr.get("draft", False) else "unsupported_action"
                log.info("PR review not queued: repo_id=%s pr=%s action=%s reason=%s", (payload.get("repository") or {}).get("id"), pr.get("number"), payload.get("action"), reason)
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
