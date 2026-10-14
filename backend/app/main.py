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
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from uuid import UUID
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from itsdangerous import URLSafeTimedSerializer, BadSignature
from . import config
from . import ai
from .db import SessionLocal
from .integrations import github_request, installation_token, pull_files
from .jobs import run_background_job
from .coding_tasks import _git, _git_auth_env, _session_workspace_path
from .models import User, AgentTask, BackgroundJob, BookDocument, ContextFile, AuthIdentity, Installation, PullRequest, RepoBookSection, RepoChatMessage, Repository, UsageRecord, UserSession, WebhookDelivery, WorkSession, WorkSessionPullRequest, Organization, OrganizationInvite, OrganizationMembership, WaitlistSignup
from .maintainer_context import MAX_CONTEXT_CHARS, format_context, load_context
from .repo_chat import retrieve_book_context

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("kodo")
app = FastAPI(title="kodai", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[config.FRONTEND_ORIGIN], allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type"])


@app.middleware("http")
async def prelaunch_route_gate(request: Request, call_next):
    """Keep the public API closed during prelaunch except for waitlist signup."""
    if request.method == "OPTIONS" or (request.method == "POST" and request.url.path == "/api/waitlist"):
        return await call_next(request)
    return JSONResponse(status_code=404, content={"detail": "kodai is not open yet"})


SESSION_SECRET = os.getenv("KODO_SESSION_SECRET", "local-only-change-this-secret")
if os.getenv("ENVIRONMENT", "development").lower() == "production" and SESSION_SECRET == "local-only-change-this-secret":
    raise RuntimeError("KODO_SESSION_SECRET must be set in production")
serializer = URLSafeTimedSerializer(SESSION_SECRET)

def _cookie_secure() -> bool:
    configured = os.getenv("KODO_COOKIE_SECURE")
    return configured.lower() == "true" if configured is not None else os.getenv("ENVIRONMENT", "development").lower() == "production"

def _safe_app_return_path(value: str | None) -> str | None:
    if not value or len(value) > 2048 or "\\" in value:
        return None
    try:
        parsed = urlsplit(value)
        decoded_path = unquote(parsed.path)
    except ValueError:
        return None
    segments = decoded_path.split("/")
    if parsed.scheme or parsed.netloc or not (decoded_path == "/app" or decoded_path.startswith("/app/")):
        return None
    if any(segment in {".", ".."} for segment in segments):
        return None
    return urlunsplit(("", "", parsed.path, parsed.query, parsed.fragment))

def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"

def _verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, n, r, p, salt_hex, digest_hex = password_hash.split("$")
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(digest_hex)),
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False

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


@app.post("/api/waitlist")
async def join_waitlist(request: Request):
    """Persist a launch-notification email without requiring an account."""
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(400, "Send a valid JSON body")
    email = str(payload.get("email", "") if isinstance(payload, dict) else "").strip().lower()
    if len(email) > 320 or not re.fullmatch(r"[^@\s]{1,64}@[^@\s.]+(?:\.[^@\s.]+)+", email):
        raise HTTPException(422, "Enter a valid email address")

    db = SessionLocal()
    try:
        existing = db.scalar(select(WaitlistSignup.id).where(WaitlistSignup.email == email))
        if existing is None:
            db.add(WaitlistSignup(email=email))
            try:
                db.commit()
            except IntegrityError:
                # A concurrent duplicate submission is still an idempotent success.
                db.rollback()
                if db.scalar(select(WaitlistSignup.id).where(WaitlistSignup.email == email)) is None:
                    raise
        return {"ok": True}
    finally:
        db.close()

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
        raise HTTPException(401, "Sign in to continue")
    try:
        session_id = serializer.loads(signed, max_age=60 * 60 * 24 * 7)
    except BadSignature:
        raise HTTPException(401, "Session expired")
    db = SessionLocal()
    try:
        record = db.get(UserSession, session_id)
        if not record or record.expires_at < datetime.utcnow() or not record.user_id:
            raise HTTPException(401, "Session expired")
        user = db.get(User, record.user_id)
        if not user:
            raise HTTPException(401, "User not found")
        memberships = db.scalars(select(OrganizationMembership).where(OrganizationMembership.user_id == user.id).order_by(OrganizationMembership.id)).all()
        membership = next((item for item in memberships if item.organization_id == record.active_organization_id), None)
        if not membership and memberships:
            membership = memberships[0]
            record.active_organization_id = membership.organization_id
        identities = db.scalars(select(AuthIdentity).where(AuthIdentity.user_id == user.id)).all()
        identity = next((item for item in identities if item.provider == "github"), None)
        organization = db.get(Organization, membership.organization_id) if membership else None
        return {
            "id": user.id, "user_id": user.id, "email": user.email,
            "login": user.name or (identity.provider_username if identity else "") or user.email or "kodai user",
            "name": user.name, "avatar_url": user.avatar_url, "phone": user.phone, "job_function": user.job_function,
            "email_verified": user.email_verified_at is not None, "is_platform_admin": user.is_platform_admin,
            "created_at": user.created_at, "updated_at": user.updated_at, "last_login_at": user.last_login_at,
            "auth_providers": [item.provider for item in identities],
            "github_login": identity.provider_username if identity else "",
            "github_user_id": int(identity.provider_user_id) if identity and identity.provider_user_id.isdigit() else None,
            "email_password_connected": any(item.provider == "email_password" for item in identities),
            "token": _decrypt_token(identity.access_token) if identity and identity.access_token else "",
            "session_id": record.id, "organization_id": membership.organization_id if membership else None,
            "organization_name": organization.name if organization else "",
            "role": membership.role if membership else "",
            "audience": membership.audience if membership else "all",
            "repository_scope": membership.repository_scope if membership else "all",
            "repository_ids": _json_list(membership.repository_ids_json) if membership else [],
        }
    finally:
        db.close()

def _refresh_user_access_token(session: dict, rejected_token: str) -> str:
    """Rotate an expired GitHub App user token once, serializing concurrent requests."""
    client_id, client_secret = os.getenv("GITHUB_CLIENT_ID"), os.getenv("GITHUB_CLIENT_SECRET")
    db = SessionLocal()
    try:
        record = db.scalar(select(AuthIdentity).where(
            AuthIdentity.user_id == session["user_id"], AuthIdentity.provider == "github",
        ).with_for_update())
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
        record.token_expires_at = now + timedelta(seconds=int(payload.get("expires_in", 28800)))
        record.refresh_expires_at = now + timedelta(seconds=int(payload.get("refresh_token_expires_in", 15897600)))
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

def _github_user_installations(session: dict) -> list[dict]:
    """List installations the linked GitHub identity can manage, including later pages."""
    installations = []
    for page in range(1, 101):
        data = _user_github_request(
            session, "GET", "/user/installations", params={"per_page": 100, "page": page},
        ) or {}
        batch = data.get("installations", [])
        installations.extend(batch)
        if len(batch) < 100:
            break
    return installations


def _sync_installation_repositories(db, installation: Installation) -> int:
    """Refresh repositories only for an installation explicitly linked to a kodai org."""
    if (installation.account_type or "").casefold() != "organization" or not installation.organization_id:
        return 0
    if installation.suspended:
        return 0

    token = installation_token(installation.id)
    visible = set()
    for page in range(1, 101):
        result = github_request(
            "GET", "/installation/repositories", token,
            params={"per_page": 100, "page": page},
        ) or {}
        batch = result.get("repositories", [])
        for repo in batch:
            visible.add(repo["id"])
            saved = db.get(Repository, repo["id"])
            if saved and saved.organization_id and saved.organization_id != installation.organization_id:
                raise HTTPException(
                    409,
                    f"Repository {repo['full_name']} is already linked to another kodai organization.",
                )
            if saved:
                saved.installation_id = installation.id
                saved.full_name = repo["full_name"]
                saved.private = repo.get("private", True)
                saved.organization_id = installation.organization_id
            else:
                db.add(Repository(
                    id=repo["id"], installation_id=installation.id,
                    full_name=repo["full_name"], private=repo.get("private", True),
                    organization_id=installation.organization_id,
                ))
        if len(batch) < 100:
            break

    stale = db.scalars(select(Repository).where(Repository.installation_id == installation.id)).all()
    for repo in stale:
        if repo.id not in visible:
            _remove_coding_workspaces(db, [repo.id])
            db.query(PullRequest).filter(PullRequest.repository_id == repo.id).delete()
            db.query(BookDocument).filter(BookDocument.repository_id == repo.id).delete()
            db.query(RepoBookSection).filter(RepoBookSection.repository_id == repo.id).delete()
            db.query(RepoChatMessage).filter(RepoChatMessage.repository_id == repo.id).delete()
            db.query(AgentTask).filter(AgentTask.repository_id == repo.id).delete()
            db.query(WorkSession).filter(WorkSession.repository_id == repo.id).delete()
            db.query(UsageRecord).filter(UsageRecord.repository_id == repo.id).delete()
            db.delete(repo)
    return len(visible)


def _sync_organization_repositories(db, organization_id: str) -> None:
    installations = db.scalars(select(Installation).where(
        Installation.organization_id == organization_id,
        Installation.account_type.ilike("organization"),
    )).all()
    for installation in installations:
        _sync_installation_repositories(db, installation)

def _authorized_repo(db, repo_id: int, session: dict, access: str = "developer") -> Repository:
    repo = db.get(Repository, repo_id)
    if not repo or not repo.organization_id or repo.organization_id != session.get("organization_id"):
        raise HTTPException(404, "Repository not found")
    installation = db.get(Installation, repo.installation_id)
    if not installation or (installation.account_type or "").casefold() != "organization" or installation.organization_id != repo.organization_id:
        raise HTTPException(404, "Repository not found")
    membership = db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == repo.organization_id,
        OrganizationMembership.user_id == session["user_id"],
    ))
    if not membership:
        raise HTTPException(404, "Repository not found")
    if membership.role == "knowledge" and access != "knowledge":
        raise HTTPException(403, "This organization role has access to Handbook and repository chat only")
    if membership.role not in {"owner", "admin", "developer", "knowledge"}:
        raise HTTPException(403, "This organization role cannot access repositories")
    if not _member_can_access_repo(membership, repo_id):
        raise HTTPException(404, "Repository not found")
    return repo

def _repo_member(db, repo: Repository, user_id: str) -> OrganizationMembership | None:
    return db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == repo.organization_id,
        OrganizationMembership.user_id == user_id,
    ))

def _member_can_access_repo(member: OrganizationMembership, repo_id: int) -> bool:
    if member.role in {"owner", "admin"} or member.repository_scope != "selected":
        return True
    try:
        return int(repo_id) in {int(value) for value in json.loads(member.repository_ids_json or "[]")}
    except (TypeError, ValueError, json.JSONDecodeError):
        return False

def _require_repo_admin(db, repo: Repository, user_id: str):
    member = _repo_member(db, repo, user_id)
    if not member or member.role not in {"owner", "admin"}:
        raise HTTPException(403, "Organization owner or admin access is required")
    return member

def _section_visible_to_audience(section: RepoBookSection, audience: str) -> bool:
    if audience == "all":
        return True
    labels = {str(item).strip().casefold() for item in _json_list(section.audiences_json) if str(item).strip()}
    return not labels or bool(labels & {"all", "general", "everyone", audience.casefold()})

def _require_github(session: dict):
    if not session.get("token") or not session.get("github_user_id"):
        raise HTTPException(403, "Connect a GitHub account to use this feature")

def _require_github_repo_write(session: dict, repo: Repository):
    _require_github(session)
    try:
        details = _user_github_request(
            session, "GET",
            f"/repos/{repo.full_name}/collaborators/{quote(session['github_login'], safe='')}/permission",
        )
    except requests.HTTPError as error:
        if error.response is not None and error.response.status_code in {403, 404}:
            raise HTTPException(403, "Your GitHub account does not have access to this repository")
        raise
    if details.get("permission") not in {"admin", "write", "maintain"}:
        raise HTTPException(403, "Your GitHub account needs write access to create or publish coding changes")

def _organization_admin(db, session: dict):
    if not session.get("organization_id"):
        raise HTTPException(403, "You are not a member of an organization")
    member = db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == session["organization_id"],
        OrganizationMembership.user_id == session["user_id"],
    ))
    if not member or member.role not in {"owner", "admin"}:
        raise HTTPException(403, "Organization owner or admin access is required")
    return member

def _remove_coding_workspaces(db, repository_ids):
    """Remove persisted private checkouts when their repository sessions are deleted."""
    repository_ids = [repo_id for repo_id in repository_ids if repo_id is not None]
    if not repository_ids:
        return
    root = config.CODING_WORKSPACE_DIR.resolve()
    session_ids = db.scalars(select(WorkSession.id).where(WorkSession.repository_id.in_(repository_ids))).all()
    for session_id in session_ids:
        path = root / f"session-{session_id}"
        try:
            if path.is_symlink():
                path.unlink()
            elif path.exists() and path.resolve().parent == root:
                shutil.rmtree(path)
        except OSError:
            log.warning("Could not remove coding workspace after repository disconnect: session_id=%s path=%s", session_id, path, exc_info=True)

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
        f"&state={quote(state, safe='')}&scope={quote('read:user user:email offline_access', safe='')}"
    )
    response = RedirectResponse(authorize_url, status_code=302)
    next_path = _safe_app_return_path(request.query_params.get("next")) or "/app"
    response.set_cookie("kodo_oauth_next", next_path, httponly=True, secure=_cookie_secure(), samesite="lax", max_age=600, path="/")
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
    verified_emails = []
    try:
        email_rows = github_request("GET", "/user/emails", token)
        if isinstance(email_rows, list):
            verified_emails = [row for row in email_rows if row.get("verified") and row.get("email")]
    except (requests.RequestException, HTTPException):
        # GitHub sign-in still works when the user has no accessible email.
        pass
    primary_email = next((row.get("email", "").strip().lower() for row in verified_emails if row.get("primary")), "")
    session_id = secrets.token_urlsafe(32)
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        existing_session = None
        signed = request.cookies.get("kodo_session")
        if signed:
            try:
                existing_session = db.get(UserSession, serializer.loads(signed, max_age=60 * 60 * 24 * 7))
                if existing_session and (existing_session.expires_at < now or not existing_session.user_id):
                    existing_session = None
            except BadSignature:
                existing_session = None
        github_identity = db.scalar(select(AuthIdentity).where(
            AuthIdentity.provider == "github", AuthIdentity.provider_user_id == str(user["id"]),
        ))
        linked_user = db.get(User, existing_session.user_id) if existing_session else None
        user_record = db.get(User, github_identity.user_id) if github_identity else None
        if existing_session:
            if user_record and linked_user and user_record.id != linked_user.id:
                raise HTTPException(409, "That GitHub account is linked to another kodai account")
            user_record = linked_user
        user_record = user_record or linked_user
        if not user_record and primary_email:
            email_owner = db.scalar(select(User).where(User.email == primary_email))
            if email_owner:
                raise HTTPException(409, "This email already has a kodai account. Sign in with that account, then connect GitHub from Settings.")
        if not user_record:
            user_record = User(
                email=primary_email or None, email_verified_at=now if primary_email else None,
                name=user.get("name") or user["login"],
                avatar_url=user.get("avatar_url") or "", last_login_at=now,
            )
            db.add(user_record)
            db.flush()
        else:
            user_record.name = user_record.name or user.get("name") or user["login"]
            user_record.avatar_url = user.get("avatar_url") or user_record.avatar_url
            user_record.last_login_at = now
            if primary_email:
                email_owner = db.scalar(select(User).where(User.email == primary_email))
                if email_owner and email_owner.id != user_record.id and not github_identity:
                    raise HTTPException(409, "That verified email already belongs to another kodai account. Sign in to that account before linking GitHub.")
                if user_record.email == primary_email and not user_record.email_verified_at:
                    user_record.email_verified_at = now
                elif not user_record.email and not email_owner:
                    user_record.email = primary_email
                    user_record.email_verified_at = now

        pending_invites = []
        if user_record.email:
            pending_invites = db.scalars(select(OrganizationInvite).where(
                OrganizationInvite.email == user_record.email,
                OrganizationInvite.accepted_at.is_(None),
                OrganizationInvite.expires_at > now,
            )).all()
            for invite in pending_invites:
                member = db.scalar(select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == invite.organization_id,
                    OrganizationMembership.user_id == user_record.id,
                ))
                if not member:
                    db.add(OrganizationMembership(
                        organization_id=invite.organization_id, user_id=user_record.id, role=invite.role,
                        audience=invite.audience, repository_scope=invite.repository_scope,
                        repository_ids_json=invite.repository_ids_json or "[]",
                    ))
                invite.accepted_at = now

        memberships = db.scalars(select(OrganizationMembership).where(
            OrganizationMembership.user_id == user_record.id,
        ).order_by(OrganizationMembership.id)).all()
        if not memberships and not pending_invites:
            organization = Organization(name=f"{user_record.name or user['login']}'s organization", created_by_user_id=user_record.id)
            db.add(organization)
            db.flush()
            memberships = [OrganizationMembership(organization_id=organization.id, user_id=user_record.id, role="owner")]
            db.add(memberships[0])

        identity = db.scalar(select(AuthIdentity).where(
            AuthIdentity.user_id == user_record.id, AuthIdentity.provider == "github",
        ).with_for_update())
        if identity and identity.provider_user_id != str(user["id"]):
            raise HTTPException(409, "This kodai account already has a different GitHub account connected")
        if not identity:
            identity = AuthIdentity(
                user_id=user_record.id, provider="github", provider_user_id=str(user["id"]),
                provider_username=user["login"],
            )
            db.add(identity)
        identity.provider_user_id = str(user["id"])
        identity.provider_username = user["login"]
        identity.access_token = _encrypt_token(token)
        identity.refresh_token = _encrypt_token(token_data["refresh_token"]) if token_data.get("refresh_token") else ""
        identity.token_expires_at = now + timedelta(seconds=int(token_data["expires_in"])) if token_data.get("expires_in") else None
        identity.refresh_expires_at = now + timedelta(seconds=int(token_data["refresh_token_expires_in"])) if token_data.get("refresh_token_expires_in") else None
        identity.updated_at = now
        target_session = existing_session or UserSession(id=session_id, user_id=user_record.id, expires_at=now + timedelta(days=7))
        target_session.user_id = user_record.id
        target_session.expires_at = now + timedelta(days=7)
        if pending_invites:
            target_session.active_organization_id = pending_invites[0].organization_id
        elif not any(item.organization_id == target_session.active_organization_id for item in memberships):
            target_session.active_organization_id = memberships[0].organization_id if memberships else None
        if not existing_session:
            db.add(target_session)
        db.commit()
        session_id = target_session.id
    finally:
        db.close()
    next_path = _safe_app_return_path(request.cookies.get("kodo_oauth_next")) or "/app"
    result = RedirectResponse(f"{config.FRONTEND_ORIGIN.rstrip('/')}{next_path}", status_code=302)
    result.delete_cookie("kodo_oauth_state", path="/")
    result.delete_cookie("kodo_oauth_next", path="/")
    result.set_cookie("kodo_session", serializer.dumps(session_id), httponly=True, secure=_cookie_secure(), samesite="lax", max_age=604800)
    return result

@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    try:
        session = _session(request)
        db = SessionLocal()
        db.query(UserSession).filter(UserSession.id == session["session_id"]).delete()
        db.commit(); db.close()
    except HTTPException:
        pass
    response.delete_cookie("kodo_session")
    return {"ok": True}

@app.get("/api/me")
async def me(request: Request):
    session = _session(request)
    return {
        "id": session["user_id"], "login": session["login"], "email": session["email"], "name": session["name"],
        "avatar_url": session["avatar_url"], "phone": session["phone"], "job_function": session["job_function"],
        "created_at": session["created_at"], "updated_at": session["updated_at"], "last_login_at": session["last_login_at"],
        "auth_providers": session["auth_providers"],
        "email_verified": session["email_verified"], "is_platform_admin": session["is_platform_admin"],
        "github_login": session["github_login"], "github_connected": bool(session["github_user_id"]),
        "email_password_connected": session["email_password_connected"],
        "role": session["role"], "audience": session["audience"],
        "organization_id": session["organization_id"], "organization_name": session["organization_name"],
    }

@app.get("/api/organizations")
async def list_organizations(request: Request):
    session = _session(request)
    db = SessionLocal()
    try:
        rows = db.execute(select(OrganizationMembership, Organization).join(Organization, Organization.id == OrganizationMembership.organization_id).where(
            OrganizationMembership.user_id == session["user_id"],
        ).order_by(OrganizationMembership.id)).all()
        return [{"id": organization.id, "name": organization.name, "role": member.role,
                 "active": organization.id == session["organization_id"]} for member, organization in rows]
    finally:
        db.close()

@app.post("/api/organizations")
async def create_organization(request: Request):
    session = _session(request)
    body = await request.json()
    raw_name = body.get("name") if isinstance(body, dict) else None
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if not name or len(name) > 120:
        raise HTTPException(422, "Organization name must be between 1 and 120 characters")
    db = SessionLocal()
    try:
        user_record = db.get(User, session["user_id"])
        record = db.get(UserSession, session["session_id"])
        if not user_record or not record:
            raise HTTPException(401, "Sign in to continue")
        organization = Organization(name=name, created_by_user_id=user_record.id)
        db.add(organization)
        db.flush()
        db.add(OrganizationMembership(organization_id=organization.id, user_id=user_record.id, role="owner"))
        record.active_organization_id = organization.id
        db.commit()
        return {"id": organization.id, "name": organization.name, "role": "owner", "active": True}
    finally:
        db.close()

@app.post("/api/organization/activate")
async def activate_organization(request: Request):
    session = _session(request)
    body = await request.json()
    organization_id = body.get("organization_id") if isinstance(body, dict) else None
    if not isinstance(organization_id, str):
        raise HTTPException(422, "Choose an organization")
    try:
        organization_id = str(UUID(organization_id))
    except ValueError:
        raise HTTPException(422, "Choose a valid organization")
    db = SessionLocal()
    try:
        record = db.get(UserSession, session["session_id"])
        membership = db.scalar(select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id, OrganizationMembership.user_id == session["user_id"],
        ))
        if not record or not membership:
            raise HTTPException(404, "Organization not found")
        record.active_organization_id = organization_id
        db.commit()
        return {"organization_id": organization_id}
    finally:
        db.close()

@app.patch("/api/organization")
async def rename_organization(request: Request):
    session = _session(request)
    body = await request.json()
    raw_name = body.get("name") if isinstance(body, dict) else None
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if not name or len(name) > 120:
        raise HTTPException(422, "Organization name must be between 1 and 120 characters")
    db = SessionLocal()
    try:
        member = _organization_admin(db, session)
        if member.role != "owner":
            raise HTTPException(403, "Only the organization owner can rename it")
        organization = db.get(Organization, member.organization_id)
        organization.name = name
        organization.updated_at = datetime.utcnow()
        db.commit()
        return {"id": organization.id, "name": organization.name}
    finally:
        db.close()

@app.post("/api/invitations/accept")
async def accept_organization_invitations(request: Request):
    session = _session(request)
    db = SessionLocal()
    try:
        user_record = db.get(User, session["user_id"])
        user_session = db.get(UserSession, session["session_id"])
        if not user_record or not user_session:
            raise HTTPException(401, "Sign in to continue")
        if not user_record.email:
            return {"accepted": 0}
        now = datetime.utcnow()
        invites = db.scalars(select(OrganizationInvite).where(
            OrganizationInvite.email == user_record.email,
            OrganizationInvite.accepted_at.is_(None), OrganizationInvite.expires_at > now,
        ).order_by(OrganizationInvite.created_at, OrganizationInvite.id)).all()
        accepted = 0
        for invite in invites:
            member = db.scalar(select(OrganizationMembership).where(
                OrganizationMembership.organization_id == invite.organization_id,
                OrganizationMembership.user_id == user_record.id,
            ))
            if not member:
                db.add(OrganizationMembership(
                    organization_id=invite.organization_id, user_id=user_record.id, role=invite.role,
                    audience=invite.audience, repository_scope=invite.repository_scope,
                    repository_ids_json=invite.repository_ids_json or "[]",
                ))
            invite.accepted_at = now
            accepted += 1
        if accepted:
            user_session.active_organization_id = invites[0].organization_id
            db.commit()
        return {"accepted": accepted}
    finally:
        db.close()

@app.post("/api/auth/email")
async def sign_in_with_email(request: Request, response: Response):
    body = await request.json()
    mode = body.get("mode") if isinstance(body, dict) else None
    raw_email = body.get("email") if isinstance(body, dict) else None
    password = body.get("password") if isinstance(body, dict) else None
    raw_name = body.get("name") if isinstance(body, dict) else None
    email = raw_email.strip().lower() if isinstance(raw_email, str) else ""
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if mode not in {"signup", "signin"}:
        raise HTTPException(422, "Choose whether to create an account or sign in")
    if len(email) > 320 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(422, "Enter a valid email address")
    if len(name) > 255:
        raise HTTPException(422, "Name must be 255 characters or fewer")
    if not isinstance(password, str) or len(password) < 12 or len(password) > 1024:
        raise HTTPException(422, "Password must be between 12 and 1024 characters")
    db = SessionLocal()
    try:
        pending_invites = db.scalars(select(OrganizationInvite).where(
            OrganizationInvite.email == email, OrganizationInvite.accepted_at.is_(None), OrganizationInvite.expires_at > datetime.utcnow(),
        )).all()
        user_record = db.scalar(select(User).where(User.email == email))
        identity = db.scalar(select(AuthIdentity).where(
            AuthIdentity.provider == "email_password", AuthIdentity.provider_user_id == email,
        ))
        if mode == "signup" and identity:
            raise HTTPException(409, "An email and password account already exists for this email. Sign in instead.")
        if mode == "signup" and user_record:
            raise HTTPException(409, "A kodai account already uses this email. Sign in with its existing method or connect email sign-in from Settings.")
        if mode == "signin" and (not identity or not user_record or identity.user_id != user_record.id):
            raise HTTPException(401, "No email and password account was found. Create an account or sign in with GitHub.")
        if mode == "signup":
            user_record = User(email=email, name=name or email.split("@", 1)[0], last_login_at=datetime.utcnow())
            db.add(user_record)
            db.flush()
            identity = AuthIdentity(
                user_id=user_record.id, provider="email_password", provider_user_id=email,
                password_hash=_hash_password(password),
            )
            db.add(identity)
        else:
            if not _verify_password(password, identity.password_hash or ""):
                raise HTTPException(401, "Invalid email or password")
        user_record.last_login_at = datetime.utcnow()
        memberships = db.scalars(select(OrganizationMembership).where(
            OrganizationMembership.user_id == user_record.id,
        ).order_by(OrganizationMembership.id)).all()
        if not memberships and not pending_invites:
            organization = Organization(name=f"{user_record.name or email.split('@', 1)[0]}'s organization", created_by_user_id=user_record.id)
            db.add(organization)
            db.flush()
            membership = OrganizationMembership(organization_id=organization.id, user_id=user_record.id, role="owner")
            db.add(membership)
            memberships.append(membership)
        for invite in pending_invites:
            member = db.scalar(select(OrganizationMembership).where(
                OrganizationMembership.organization_id == invite.organization_id, OrganizationMembership.user_id == user_record.id,
            ))
            if not member:
                member = OrganizationMembership(
                    organization_id=invite.organization_id, user_id=user_record.id, role=invite.role, audience=invite.audience,
                    repository_scope=invite.repository_scope,
                    repository_ids_json=invite.repository_ids_json or "[]",
                )
                db.add(member)
                memberships.append(member)
            invite.accepted_at = datetime.utcnow()
        session_id = secrets.token_urlsafe(32)
        active_organization_id = pending_invites[0].organization_id if pending_invites else (memberships[0].organization_id if memberships else None)
        db.add(UserSession(
            id=session_id, user_id=user_record.id, expires_at=datetime.utcnow() + timedelta(days=7),
            active_organization_id=active_organization_id,
        ))
        db.commit()
        response.set_cookie("kodo_session", serializer.dumps(session_id), httponly=True, secure=_cookie_secure(), samesite="lax", max_age=604800)
        return {"ok": True, "email": email}
    finally:
        db.close()

@app.post("/api/auth/email/link")
async def link_email_password(request: Request):
    session = _session(request)
    body = await request.json()
    raw_email = body.get("email") if isinstance(body, dict) else None
    password = body.get("password") if isinstance(body, dict) else None
    email = raw_email.strip().lower() if isinstance(raw_email, str) else ""
    if len(email) > 320 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise HTTPException(422, "Enter a valid email address")
    if not isinstance(password, str) or len(password) < 12 or len(password) > 1024:
        raise HTTPException(422, "Password must be between 12 and 1024 characters")
    db = SessionLocal()
    try:
        user_record = db.get(User, session["user_id"])
        if not user_record:
            raise HTTPException(401, "Sign in to continue")
        github_identity = db.scalar(select(AuthIdentity.id).where(
            AuthIdentity.user_id == user_record.id, AuthIdentity.provider == "github",
        ))
        if not github_identity:
            raise HTTPException(403, "Connect GitHub before adding email sign-in")
        identity = db.scalar(select(AuthIdentity).where(
            AuthIdentity.provider == "email_password", AuthIdentity.provider_user_id == email,
        ))
        if identity and identity.user_id != user_record.id:
            raise HTTPException(409, "This email already belongs to another kodai account")
        if identity:
            raise HTTPException(409, "Email and password sign-in is already connected to this account")
        email_owner = db.scalar(select(User).where(User.email == email))
        if email_owner and email_owner.id != user_record.id:
            raise HTTPException(409, "This email already belongs to another kodai account")
        if user_record.email and user_record.email.lower() != email:
            raise HTTPException(422, "Use the email already on this account")
        user_record.email = email
        db.add(AuthIdentity(
            user_id=user_record.id, provider="email_password", provider_user_id=email,
            password_hash=_hash_password(password),
        ))
        db.commit()
        return {"ok": True, "email": email}
    finally:
        db.close()

@app.get("/api/organization/members")
async def organization_members(request: Request):
    session = _session(request)
    db = SessionLocal()
    try:
        if not session.get("organization_id"):
            raise HTTPException(404, "Organization not found")
        rows = db.execute(select(OrganizationMembership, User).join(User, User.id == OrganizationMembership.user_id).where(
            OrganizationMembership.organization_id == session["organization_id"],
        ).order_by(OrganizationMembership.created_at)).all()
        user_ids = [user_record.id for _, user_record in rows]
        github_identities = db.scalars(select(AuthIdentity).where(
            AuthIdentity.user_id.in_(user_ids), AuthIdentity.provider == "github",
        )).all() if user_ids else []
        github_by_user = {identity.user_id: identity for identity in github_identities}
        me_role = session.get("role", "")
        invites = db.scalars(select(OrganizationInvite).where(
            OrganizationInvite.organization_id == session["organization_id"],
            OrganizationInvite.accepted_at.is_(None), OrganizationInvite.expires_at > datetime.utcnow(),
        ).order_by(OrganizationInvite.created_at.desc())).all() if me_role in {"owner", "admin"} else []
        return {"organization_id": session["organization_id"], "role": me_role, "members": [
            {"user_id": member.user_id, "email": user_record.email or "", "name": user_record.name or user_record.email or "kodai user",
             "github_login": github_by_user[user_record.id].provider_username if user_record.id in github_by_user else "",
             "avatar_url": user_record.avatar_url, "role": member.role, "audience": member.audience,
             "repository_scope": member.repository_scope, "repository_ids": _json_list(member.repository_ids_json)}
            for member, user_record in rows
        ], "invites": [
            {"id": invite.id, "email": invite.email, "role": invite.role, "audience": invite.audience,
             "repository_scope": invite.repository_scope, "repository_ids": _json_list(invite.repository_ids_json),
             "expires_at": invite.expires_at.isoformat()}
            for invite in invites
        ]}
    finally:
        db.close()

@app.post("/api/organization/invites")
async def invite_organization_member(request: Request):
    session = _session(request)
    body = await request.json()
    raw_email = body.get("email") if isinstance(body, dict) else None
    email = raw_email.strip().lower() if isinstance(raw_email, str) else ""
    role = body.get("role", "knowledge") if isinstance(body, dict) else "knowledge"
    audience = body.get("audience", "all") if isinstance(body, dict) else "all"
    repository_scope = body.get("repository_scope", "all") if isinstance(body, dict) else "all"
    requested_repo_ids = body.get("repository_ids", []) if isinstance(body, dict) else []
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 320:
        raise HTTPException(422, "Enter a valid email address")
    if role not in {"admin", "developer", "knowledge"}:
        raise HTTPException(422, "Choose admin, developer, or knowledge access")
    if audience not in {"all", "operations", "support", "sales"}:
        raise HTTPException(422, "Choose a valid Handbook audience")
    if repository_scope not in {"all", "selected"}:
        raise HTTPException(422, "Choose all repositories or selected repositories")
    if not isinstance(requested_repo_ids, list) or any(not isinstance(value, int) or isinstance(value, bool) for value in requested_repo_ids):
        raise HTTPException(422, "Selected repository access is invalid")
    if role in {"admin", "owner"}:
        repository_scope, requested_repo_ids = "all", []
    db = SessionLocal()
    try:
        member = _organization_admin(db, session)
        if role == "admin" and member.role != "owner":
            raise HTTPException(403, "Only the organization owner can appoint another admin")
        organization = db.get(Organization, member.organization_id)
        available_repo_ids = set(db.scalars(select(Repository.id).join(
            Installation, Installation.id == Repository.installation_id,
        ).where(
            Repository.organization_id == organization.id,
            Installation.organization_id == organization.id,
            Installation.account_type.ilike("organization"),
        )).all())
        requested_repo_ids = list(dict.fromkeys(requested_repo_ids))
        if repository_scope == "selected" and (not requested_repo_ids or not set(requested_repo_ids).issubset(available_repo_ids)):
            raise HTTPException(422, "Choose one or more repositories from this organization")
        if repository_scope == "all":
            requested_repo_ids = []
        if email == (session.get("email") or ""):
            raise HTTPException(422, "You are already a member of this organization")
        existing_account = db.scalar(select(User).where(User.email == email))
        if existing_account and db.scalar(select(OrganizationMembership.id).where(
            OrganizationMembership.organization_id == organization.id, OrganizationMembership.user_id == existing_account.id,
        )):
            raise HTTPException(409, "This person is already an organization member. Change their access from the member list.")
        invite = db.scalar(select(OrganizationInvite).where(
            OrganizationInvite.organization_id == organization.id, OrganizationInvite.email == email,
            OrganizationInvite.accepted_at.is_(None), OrganizationInvite.expires_at > datetime.utcnow(),
        ).order_by(OrganizationInvite.created_at.desc()).limit(1))
        if not invite:
            invite = OrganizationInvite(
                organization_id=organization.id, email=email, role=role, audience=audience,
                repository_scope=repository_scope, repository_ids_json=json.dumps(requested_repo_ids),
                invited_by_user_id=session["user_id"], expires_at=datetime.utcnow() + timedelta(days=7),
            )
            db.add(invite)
        else:
            invite.role, invite.audience = role, audience
            invite.repository_scope = repository_scope
            invite.repository_ids_json = json.dumps(requested_repo_ids)
            invite.invited_by_user_id = session["user_id"]
            invite.expires_at = datetime.utcnow() + timedelta(days=7)
        db.commit()
        return {"ok": True, "email": email, "role": role}
    finally:
        db.close()

@app.patch("/api/organization/members/{user_id}")
async def change_organization_member_role(user_id: str, request: Request):
    session = _session(request)
    body = await request.json()
    role = body.get("role") if isinstance(body, dict) else None
    audience = body.get("audience") if isinstance(body, dict) else None
    repository_scope = body.get("repository_scope", "all") if isinstance(body, dict) else "all"
    repository_ids = body.get("repository_ids", []) if isinstance(body, dict) else []
    if role not in {"admin", "developer", "knowledge"}:
        raise HTTPException(422, "Choose admin, developer, or knowledge access")
    if audience is not None and audience not in {"all", "operations", "support", "sales"}:
        raise HTTPException(422, "Choose a valid Handbook audience")
    if repository_scope not in {"all", "selected"}:
        raise HTTPException(422, "Choose all repositories or selected repositories")
    if not isinstance(repository_ids, list) or any(not isinstance(value, int) or isinstance(value, bool) for value in repository_ids):
        raise HTTPException(422, "Selected repository access is invalid")
    db = SessionLocal()
    try:
        owner = _organization_admin(db, session)
        if role == "admin" and owner.role != "owner":
            raise HTTPException(403, "Only the organization owner can appoint another admin")
        member = db.scalar(select(OrganizationMembership).where(OrganizationMembership.organization_id == owner.organization_id, OrganizationMembership.user_id == user_id))
        if not member or member.role == "owner":
            raise HTTPException(404, "Organization member not found")
        available_repo_ids = set(db.scalars(select(Repository.id).join(
            Installation, Installation.id == Repository.installation_id,
        ).where(
            Repository.organization_id == owner.organization_id,
            Installation.organization_id == owner.organization_id,
            Installation.account_type.ilike("organization"),
        )).all())
        repository_ids = list(dict.fromkeys(repository_ids))
        if role == "admin":
            repository_scope, repository_ids = "all", []
        elif repository_scope == "selected" and (not repository_ids or not set(repository_ids).issubset(available_repo_ids)):
            raise HTTPException(422, "Choose one or more repositories from this organization")
        if repository_scope == "all":
            repository_ids = []
        previous_role, previous_audience = member.role, member.audience
        previous_scope, previous_repo_ids = member.repository_scope, member.repository_ids_json
        member.role = role
        member.repository_scope = repository_scope
        member.repository_ids_json = json.dumps(repository_ids)
        if audience is not None:
            member.audience = audience
        access_changed = previous_role != role or previous_audience != member.audience or previous_scope != repository_scope or previous_repo_ids != member.repository_ids_json
        if access_changed:
            repo_ids = select(Repository.id).join(
                Installation, Installation.id == Repository.installation_id,
            ).where(
                Repository.organization_id == owner.organization_id,
                Installation.organization_id == owner.organization_id,
                Installation.account_type.ilike("organization"),
            )
            if repository_scope == "selected":
                repo_ids = select(Repository.id).where(Repository.id.in_(repository_ids))
            db.query(RepoChatMessage).filter(
                RepoChatMessage.repository_id.in_(repo_ids), RepoChatMessage.user_id == user_id,
            ).delete(synchronize_session=False)
        db.commit()
        return {"user_id": user_id, "role": role, "audience": member.audience,
                "repository_scope": member.repository_scope, "repository_ids": _json_list(member.repository_ids_json)}
    finally:
        db.close()

@app.delete("/api/organization/members/{user_id}")
async def remove_organization_member(user_id: str, request: Request):
    session = _session(request)
    db = SessionLocal()
    try:
        owner = _organization_admin(db, session)
        member = db.scalar(select(OrganizationMembership).where(OrganizationMembership.organization_id == owner.organization_id, OrganizationMembership.user_id == user_id))
        if not member or member.role == "owner":
            raise HTTPException(404, "Organization member not found")
        repo_ids = select(Repository.id).join(
            Installation, Installation.id == Repository.installation_id,
        ).where(
            Repository.organization_id == owner.organization_id,
            Installation.organization_id == owner.organization_id,
            Installation.account_type.ilike("organization"),
        )
        db.query(RepoChatMessage).filter(
            RepoChatMessage.repository_id.in_(repo_ids), RepoChatMessage.user_id == user_id,
        ).delete(synchronize_session=False)
        db.delete(member)
        db.commit()
        return {"ok": True}
    finally:
        db.close()

@app.delete("/api/organization/invites/{invite_id}")
async def revoke_organization_invite(invite_id: int, request: Request):
    session = _session(request)
    db = SessionLocal()
    try:
        owner = _organization_admin(db, session)
        invite = db.scalar(select(OrganizationInvite).where(
            OrganizationInvite.id == invite_id, OrganizationInvite.organization_id == owner.organization_id,
            OrganizationInvite.accepted_at.is_(None),
        ))
        if not invite:
            raise HTTPException(404, "Invitation not found")
        db.delete(invite)
        db.commit()
        return {"ok": True}
    finally:
        db.close()

@app.get("/api/installations")
async def installations(request: Request):
    session = _session(request)
    db = SessionLocal()
    try:
        owner = _organization_admin(db, session)
        rows = db.scalars(select(Installation).where(
            Installation.organization_id == owner.organization_id,
            Installation.account_type.ilike("organization"),
        ).order_by(Installation.account)).all()
        return [{"id": x.id, "account": x.account, "account_type": x.account_type, "suspended": x.suspended} for x in rows]
    finally:
        db.close()

@app.get("/api/installations/available")
async def available_installations(request: Request):
    session = _session(request)
    _require_github(session)
    db = SessionLocal()
    try:
        owner = _organization_admin(db, session)
        linked = _github_user_installations(session)
        available = []
        for item in linked:
            account = item.get("account") or {}
            if (account.get("type") or "").casefold() != "organization":
                continue
            saved = db.get(Installation, item["id"])
            if saved and saved.organization_id:
                continue
            available.append({
                "id": item["id"],
                "account": account.get("login", "GitHub organization"),
                "account_type": account.get("type", "Organization"),
                "suspended": bool(item.get("suspended_at")),
            })
        return available
    finally:
        db.close()

@app.post("/api/installations/{installation_id}/connect")
async def connect_installation(installation_id: int, request: Request):
    session = _session(request)
    _require_github(session)
    db = SessionLocal()
    try:
        owner = _organization_admin(db, session)
        item = next((row for row in _github_user_installations(session) if row.get("id") == installation_id), None)
        if not item:
            raise HTTPException(404, "This GitHub App installation is not accessible to your connected GitHub account.")
        account = item.get("account") or {}
        if (account.get("type") or "").casefold() != "organization":
            raise HTTPException(422, "Only GitHub Organization installations can be connected to a kodai organization.")
        saved = db.get(Installation, installation_id)
        if saved and saved.organization_id and saved.organization_id != owner.organization_id:
            raise HTTPException(409, "This GitHub organization is already connected to another kodai organization.")

        if not saved:
            saved = Installation(id=installation_id)
            db.add(saved)
        saved.account = account.get("login", "")
        saved.account_type = account.get("type", "Organization")
        saved.suspended = bool(item.get("suspended_at"))
        saved.organization_id = owner.organization_id
        db.flush()

        repo_count = _sync_installation_repositories(db, saved)
        db.commit()
        log.info(
            "GitHub organization connected to kodai organization: installation_id=%s github_org=%s kodai_org=%s repos=%s",
            installation_id, saved.account, owner.organization_id, repo_count,
        )
        return {"installation_id": installation_id, "account": saved.account, "repository_count": repo_count}
    except HTTPException:
        db.rollback()
        raise
    except requests.RequestException as error:
        db.rollback()
        log.exception("Could not sync GitHub organization installation %s", installation_id)
        raise HTTPException(502, "Could not load repositories from this GitHub organization. Try again.") from error
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

@app.get("/api/app-install-url")
async def app_install_url(request: Request):
    session = _session(request)
    _require_github(session)
    db = SessionLocal()
    try:
        _organization_admin(db, session)
    finally:
        db.close()
    slug = os.getenv("GITHUB_APP_SLUG", "")
    return {"url": f"https://github.com/apps/{slug}/installations/new" if slug else None}

@app.get("/api/repos")
async def repositories(request: Request):
    session = _session(request)
    db = SessionLocal()
    try:
        if session.get("role") in {"owner", "admin"} and session.get("organization_id"):
            _sync_organization_repositories(db, session["organization_id"])
            db.commit()
        members = db.scalars(select(OrganizationMembership).where(
            OrganizationMembership.user_id == session["user_id"], OrganizationMembership.organization_id == session.get("organization_id"),
        )).all()
        member_by_organization = {member.organization_id: member for member in members}
        rows = db.scalars(select(Repository).join(
            Installation, Installation.id == Repository.installation_id,
        ).where(
            Repository.organization_id.in_(member_by_organization),
            Installation.organization_id == Repository.organization_id,
            Installation.account_type.ilike("organization"),
        )).all() if member_by_organization else []
        rows = [repo for repo in rows if _member_can_access_repo(member_by_organization[repo.organization_id], repo.id)]
        return [{"id": r.id, "installation_id": r.installation_id, "full_name": r.full_name, "private": r.private, "enabled": r.enabled, "review_mode": r.review_mode, "organization_id": r.organization_id,
                 "role": member_by_organization[r.organization_id].role, "audience": member_by_organization[r.organization_id].audience} for r in rows]
    finally:
        db.close()

@app.get("/api/repos/{repo_id}/summary")
async def repository_summary(repo_id: int, request: Request):
    """Return lightweight counts for repository navigation badges."""
    session = _session(request)
    db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, session, access="knowledge")
        pull_requests_count = db.scalar(
            select(func.count(PullRequest.id)).where(PullRequest.repository_id == repo_id)
        ) or 0
        sessions_count = db.scalar(
            select(func.count(WorkSession.id)).where(WorkSession.repository_id == repo_id)
        ) or 0
        return {
            "pull_requests_count": pull_requests_count,
            "sessions_count": sessions_count,
        }
    finally:
        db.close()

@app.get("/api/context-files")
async def context_files(request: Request):
    session = _session(request)
    db = SessionLocal()
    try:
        owner = _organization_admin(db, session)
        repos = db.scalars(select(Repository).join(
            Installation, Installation.id == Repository.installation_id,
        ).where(
            Repository.organization_id == owner.organization_id,
            Installation.organization_id == owner.organization_id,
            Installation.account_type.ilike("organization"),
        )).all()
        repo_ids = [repo.id for repo in repos]
        installation_ids = set(db.scalars(select(Installation.id).where(
            Installation.organization_id == owner.organization_id,
            Installation.account_type.ilike("organization"),
        )).all())
        filters = []
        if installation_ids:
            filters.append((ContextFile.scope == "installation") & ContextFile.scope_id.in_(installation_ids))
        if repo_ids:
            filters.append((ContextFile.scope == "repository") & ContextFile.scope_id.in_(repo_ids))
        rows = db.scalars(select(ContextFile).where(or_(*filters))).all() if filters else []
        return {
            "organization": {str(row.scope_id): row.markdown for row in rows if row.scope == "installation"},
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
async def update_organization_context(installation_id: int, request: Request):
    session = _session(request)
    body = await request.json()
    markdown = body.get("markdown") if isinstance(body, dict) else None
    if not isinstance(markdown, str) or len(markdown) > MAX_CONTEXT_CHARS:
        raise HTTPException(422, f"Organization Markdown must be {MAX_CONTEXT_CHARS:,} characters or fewer")
    db = SessionLocal()
    try:
        owner = _organization_admin(db, session)
        installation = db.get(Installation, installation_id)
        if not installation or installation.organization_id != owner.organization_id or (installation.account_type or "").casefold() != "organization":
            raise HTTPException(404, "Organization not found")
        shared = db.scalar(select(Repository.id).join(
            Installation, Installation.id == Repository.installation_id,
        ).where(
            Repository.installation_id == installation_id,
            Repository.organization_id == owner.organization_id,
            Installation.organization_id == owner.organization_id,
            Installation.account_type.ilike("organization"),
        ).limit(1))
        if not shared:
            raise HTTPException(404, "Organization not found")
        _save_context_file(db, "installation", installation_id, markdown)
        repo_ids = db.scalars(select(Repository.id).join(
            Installation, Installation.id == Repository.installation_id,
        ).where(
            Repository.installation_id == installation_id,
            Repository.organization_id == owner.organization_id,
            Installation.organization_id == owner.organization_id,
            Installation.account_type.ilike("organization"),
        )).all()
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
        _require_repo_admin(db, repo, session["user_id"])
        if "enabled" in body: repo.enabled = bool(body["enabled"])
        if "review_mode" in body:
            if body["review_mode"] not in {"quick", "standard", "deep", "security"}:
                raise HTTPException(422, "Invalid review mode")
            repo.review_mode = body["review_mode"]
        db.commit()
        return {"id": repo.id, "enabled": repo.enabled, "review_mode": repo.review_mode}
    finally:
        db.close()

def _agent_task_response(task: AgentTask, commit_published=False):
    return {
        "id": task.id, "repository_id": task.repository_id, "github_login": task.github_login,
        "instructions": task.instructions, "state": task.state,
        "progress_stage": task.progress_stage, "progress_message": task.progress_message,
        "source_pull_request_number": task.source_pull_request_number,
        "source_finding_key": task.source_finding_key,
        "work_session_id": task.work_session_id,
        "work_session_pull_request_id": task.work_session_pull_request_id,
        "commit_sha": task.commit_sha, "summary": task.summary, "error": task.error,
        "changes_available": task.changes_json not in {"", "{}"},
        "commit_published": bool(commit_published and task.commit_sha),
        "created_at": task.created_at.isoformat(), "updated_at": task.updated_at.isoformat(),
    }

def _session_git_status(workspace: Path):
    """Return per-file staging state from Git's NUL-delimited porcelain output."""
    raw = _git(workspace, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = {}
    parts = raw.split("\0") if raw else []
    index = 0
    while index < len(parts):
        record = parts[index]
        index += 1
        if len(record) < 4:
            continue
        code, path = record[:2], record[3:]
        entry = {
            "staged": code[0] not in {" ", "?"},
            "unstaged": code[1] not in {" ", "?"} or code == "??",
            "working_status": code,
        }
        entries[path] = entry
        if code[0] in {"R", "C"} and index < len(parts):
            entries[parts[index]] = entry
            index += 1
    return entries

def _valid_git_paths(paths):
    if not isinstance(paths, list) or not paths or len(paths) > 200:
        raise HTTPException(422, "Select one or more changed files")
    normalized = []
    for path in paths:
        if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path or "\x00" in path or any(part == ".." for part in path.split("/")):
            raise HTTPException(422, "One or more file paths are invalid")
        normalized.append(path)
    return list(dict.fromkeys(normalized))

def _session_workspace(db, repo_id: int, work_session_id: int, user_session: dict, allow_missing=False):
    repo = _authorized_repo(db, repo_id, user_session)
    work_session = db.scalar(select(WorkSession).where(
        WorkSession.id == work_session_id, WorkSession.repository_id == repo_id,
    ))
    if not work_session:
        raise HTTPException(404, "Work session not found")
    destination = db.scalar(select(WorkSessionPullRequest).where(
        WorkSessionPullRequest.work_session_id == work_session_id,
    ).order_by(WorkSessionPullRequest.sequence.desc()).limit(1))
    if not destination:
        raise HTTPException(409, "This session does not have a working branch yet")
    workspace = _session_workspace_path(work_session_id, destination.id)
    if not workspace.is_dir() or not (workspace / ".git").is_dir():
        if allow_missing and destination.status == "planned":
            return repo, work_session, destination, workspace
        raise HTTPException(409, "The saved session workspace is unavailable")
    if _git(workspace, "branch", "--show-current") != destination.branch:
        raise HTTPException(409, "The saved session workspace is on a different branch")
    return repo, work_session, destination, workspace

def _work_session_response(row, db, eligibility=None):
    tasks = db.scalars(select(AgentTask).where(AgentTask.work_session_id == row.id).order_by(AgentTask.created_at)).all()
    destinations = db.scalars(select(WorkSessionPullRequest).where(WorkSessionPullRequest.work_session_id == row.id).order_by(WorkSessionPullRequest.sequence)).all()
    eligibility = eligibility or {"can_continue": row.status != "paused", "can_retry": row.status == "paused", "reason": row.error, "pull_requests": {}}
    task_groups = {}
    for task in tasks:
        task_groups.setdefault(task.work_session_pull_request_id, []).append(task)
    destination_by_id = {destination.id: destination for destination in destinations}

    def task_response(task):
        destination = destination_by_id.get(task.work_session_pull_request_id)
        return _agent_task_response(task, commit_published=bool(destination and destination.pull_request_number))

    # Session order is authoritative: a terminal latest PR starts a new branch generation
    # on the next prompt instead of silently switching back to an older branch.
    active_destination = destinations[-1] if destinations else None
    active_eligibility = eligibility.get("pull_requests", {}).get(active_destination.id, {}) if active_destination else {}
    active_pull_request = None
    if active_destination and active_destination.pull_request_number:
        active_pull_request = {
            "number": active_destination.pull_request_number,
            "url": active_destination.pull_request_url,
            "status": active_destination.status,
        }
    normalized_status = "ready" if row.status == "complete" else row.status
    has_pending_task = any(item.state in {"queued", "running"} for item in tasks)
    return {
        "id": row.id, "title": row.title or "New work session", "status": normalized_status,
        "updated_at": row.updated_at.isoformat(),
        "error": row.error, "task_count": len(tasks), "queued_count": sum(item.state == "queued" for item in tasks),
        "tasks": [task_response(item) for item in tasks],
        "branch": active_destination.branch if active_destination else "",
        "active_destination_id": active_destination.id if active_destination else None,
        "active_destination": ({
            "id": active_destination.id, "sequence": active_destination.sequence,
            "branch": active_destination.branch, "status": active_destination.status,
            "pull_request_number": active_destination.pull_request_number,
            "pull_request_url": active_destination.pull_request_url,
            "error": active_destination.error,
            "can_continue": active_eligibility.get("can_continue", active_destination.status in {"planned", "ready", "open"}),
            "reason": active_eligibility.get("reason", active_destination.error),
        } if active_destination else None),
        "pull_request": active_pull_request,
        "can_publish": bool(active_destination
            and active_destination.status in {"ready", "open"}
            and not has_pending_task and normalized_status != "paused"),
        "pull_requests": [{
            "id": destination.id, "sequence": destination.sequence,
            "status": destination.status, "branch": destination.branch,
            "pull_request_number": destination.pull_request_number,
            "pull_request_url": destination.pull_request_url, "error": destination.error,
            "task_count": len(task_groups.get(destination.id, [])),
            "tasks": [task_response(item) for item in task_groups.get(destination.id, [])],
            "can_continue": eligibility.get("pull_requests", {}).get(destination.id, {}).get("can_continue", destination.status in {"planned", "ready", "open"}),
            "reason": eligibility.get("pull_requests", {}).get(destination.id, {}).get("reason", destination.error),
        } for destination in destinations],
        "can_continue": eligibility["can_continue"], "can_retry": eligibility["can_retry"],
        "can_start_new_pr": eligibility.get("can_start_new_pr", True),
        "reason": eligibility["reason"],
    }

def _verify_session_pull_request(repo, destination):
    """Return whether a destination still points at the same writable open PR."""
    if not destination.pull_request_number:
        return destination.status in {"planned", "ready"}
    try:
        token = installation_token(repo.installation_id)
        pull = github_request("GET", f"/repos/{repo.full_name}/pulls/{destination.pull_request_number}", token)
    except requests.HTTPError as error:
        status = error.response.status_code if error.response is not None else 0
        if status == 404:
            destination.status = "unavailable"
            destination.error = "This pull request is no longer available. The next coding turn will start a new session branch."
            return False
        raise HTTPException(503, "kodai could not verify the pull request. Try again shortly.")
    if pull.get("state") != "open":
        destination.status = "closed"
        destination.error = "This pull request is closed or merged. The next coding turn will start a new session branch."
        return False
    head = pull.get("head") or {}
    head_repo = (head.get("repo") or {}).get("full_name", "")
    if head_repo.casefold() != repo.full_name.casefold():
        destination.status = "ineligible"
        destination.error = "This PR uses a fork branch kodai cannot update. The next coding turn will start a new session branch."
        return False
    if destination.branch and head.get("ref") != destination.branch:
        destination.status = "ineligible"
        destination.error = "The PR branch changed. The next coding turn will start a new session branch."
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
        target_valid = not destination.pull_request_number and destination.status in {"planned", "ready"}
        if destination.pull_request_number:
            pull = open_by_number.get(destination.pull_request_number)
            if lookup_error:
                target_valid, reason = False, lookup_error
            elif not pull:
                target_valid = False
                reason = "This PR is closed or unavailable. The next coding turn starts a new branch in this session."
                destination.status, destination.error, destination.updated_at = "closed", reason, datetime.utcnow()
            else:
                head = pull.get("head") or {}
                head_repo = (head.get("repo") or {}).get("full_name", "")
                if head_repo.casefold() != repo.full_name.casefold():
                    target_valid = False
                    reason = "This PR uses a fork branch kodai cannot update. The next coding turn starts a new branch in this session."
                    destination.status, destination.error = "ineligible", reason
                elif destination.branch and head.get("ref") != destination.branch:
                    target_valid = False
                    reason = "The PR branch changed. The next coding turn starts a new branch in this session."
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

def _session_title_from_instructions(instructions: str) -> str:
    first_line = next((line.strip() for line in instructions.splitlines() if line.strip()), "New work session")
    return re.sub(r"^#+\s*", "", first_line)[:200] or "New work session"

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

@app.get("/api/repos/{repo_id}/work-sessions/{work_session_id}")
async def get_work_session(repo_id: int, work_session_id: int, request: Request):
    session = _session(request)
    db = SessionLocal()
    try:
        repo = _authorized_repo(db, repo_id, session)
        work_session = db.scalar(select(WorkSession).where(
            WorkSession.id == work_session_id,
            WorkSession.repository_id == repo_id,
        ))
        if not work_session:
            raise HTTPException(404, "Work session not found")
        destinations = db.scalars(select(WorkSessionPullRequest).where(
            WorkSessionPullRequest.work_session_id == work_session_id,
        ).order_by(WorkSessionPullRequest.sequence)).all()
        eligibility = _session_eligibility(repo, [work_session], destinations)
        db.commit()
        return _work_session_response(work_session, db, eligibility[work_session.id])
    finally:
        db.close()

@app.get("/api/repos/{repo_id}/work-sessions/{work_session_id}/tasks/{task_id}/changes")
async def get_work_session_task_changes(repo_id: int, work_session_id: int, task_id: int, request: Request):
    """Return the files and patch produced by one coding turn."""
    session = _session(request)
    db = SessionLocal()
    try:
        repo = _authorized_repo(db, repo_id, session)
        work_session = db.scalar(select(WorkSession).where(
            WorkSession.id == work_session_id,
            WorkSession.repository_id == repo_id,
        ))
        task = db.scalar(select(AgentTask).where(
            AgentTask.id == task_id,
            AgentTask.repository_id == repo_id,
            AgentTask.work_session_id == work_session_id,
        ))
        if not work_session or not task:
            raise HTTPException(404, "Session task not found")
        if task.changes_json and task.changes_json != "{}":
            try:
                saved = json.loads(task.changes_json)
                return {"task_id": task.id, "commit_sha": task.commit_sha,
                        "files": saved.get("files", []), "diff": saved.get("diff", ""),
                        "truncated": bool(saved.get("truncated"))}
            except (TypeError, ValueError):
                log.warning("Invalid task change snapshot: task_id=%s", task_id)
        if not task.commit_sha or not re.fullmatch(r"[0-9a-f]{40,64}", task.commit_sha):
            raise HTTPException(409, "This task has no saved commit to review")
        destination = db.get(WorkSessionPullRequest, task.work_session_pull_request_id)
        if not destination or destination.work_session_id != work_session_id:
            raise HTTPException(404, "Session branch not found")

        workspace = _session_workspace_path(work_session_id, destination.id)
        files = []
        diff = ""
        truncated = False
        if workspace.is_dir() and (workspace / ".git").is_dir():
            try:
                _git(workspace, "cat-file", "-e", f"{task.commit_sha}^{{commit}}")
                names = _git(workspace, "show", "--format=", "--name-status", "--no-renames", task.commit_sha, "--")
                remaining = config.MAX_DIFF_CHARS
                for line in names.splitlines():
                    status, separator, path = line.partition("\t")
                    if separator and path:
                        patch = _git(workspace, "show", "--format=", "--no-ext-diff", "--no-color", "--unified=3", task.commit_sha, "--", path)
                        if len(patch) > remaining:
                            patch = patch[:remaining]
                            truncated = True
                        remaining = max(0, remaining - len(patch))
                        diff += ("\n" if diff else "") + patch
                        files.append({"status": status, "path": path, "patch": patch})
            except RuntimeError:
                if not destination.pull_request_number:
                    raise HTTPException(404, "The saved changes are no longer available in this workspace")

        if not files and destination.pull_request_number:
            try:
                token = installation_token(repo.installation_id)
                commit = github_request("GET", f"/repos/{repo.full_name}/commits/{task.commit_sha}", token)
                for item in commit.get("files") or []:
                    status = {"added": "A", "modified": "M", "removed": "D", "renamed": "R", "copied": "C"}.get(item.get("status"), "M")
                    patch = item.get("patch") or ""
                    if len(patch) > config.MAX_DIFF_CHARS - len(diff):
                        patch = patch[:max(0, config.MAX_DIFF_CHARS - len(diff))]
                        truncated = True
                    diff += ("\n" if diff else "") + patch
                    files.append({"status": status, "path": item.get("filename", ""), "patch": patch})
            except Exception as error:
                log.warning("Could not load task diff from GitHub: task_id=%s error=%s", task_id, error)
                if not files:
                    raise HTTPException(502, "Could not load this task’s changes from GitHub")

        return {"task_id": task.id, "commit_sha": task.commit_sha, "files": files,
                "diff": diff, "truncated": truncated}
    finally:
        db.close()

@app.get("/api/repos/{repo_id}/work-sessions/{work_session_id}/tasks/{task_id}/progress")
async def get_work_session_task_progress(repo_id: int, work_session_id: int, task_id: int, request: Request):
    """Return lightweight live execution state without reloading the full session."""
    session = _session(request)
    db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, session)
        task = db.scalar(select(AgentTask).where(
            AgentTask.id == task_id,
            AgentTask.repository_id == repo_id,
            AgentTask.work_session_id == work_session_id,
        ))
        if not task:
            raise HTTPException(404, "Session task not found")
        return {
            "id": task.id,
            "state": task.state,
            "progress_stage": task.progress_stage,
            "progress_message": task.progress_message,
            "summary": task.summary,
            "error": task.error,
            "updated_at": task.updated_at.isoformat(),
        }
    finally:
        db.close()

@app.get("/api/repos/{repo_id}/work-sessions/{work_session_id}/changes")
async def get_work_session_changes(repo_id: int, work_session_id: int, request: Request):
    """Return cumulative branch changes plus staged and unstaged file state."""
    user_session = _session(request)
    db = SessionLocal()
    try:
        repo, work_session, destination, workspace = _session_workspace(db, repo_id, work_session_id, user_session, allow_missing=True)
        if not workspace.is_dir() or not (workspace / ".git").is_dir():
            return {"branch": destination.branch, "pull_request_number": destination.pull_request_number,
                    "files": [], "truncated": False, "staged_count": 0, "unstaged_count": 0,
                    "commits_ahead": 0, "outgoing_files": [], "has_uncommitted_changes": False,
                    "pending_count": 0, "can_commit": False, "can_publish": False}
        base_branch = ""
        pull = None
        token = installation_token(repo.installation_id)
        if destination.pull_request_number:
            pull = github_request("GET", f"/repos/{repo.full_name}/pulls/{destination.pull_request_number}", token)
            base_branch = ((pull.get("base") or {}).get("ref") or "").strip()
        if not base_branch:
            metadata = github_request("GET", f"/repos/{repo.full_name}", token)
            base_branch = metadata.get("default_branch") or "main"
        if not re.fullmatch(r"[A-Za-z0-9._/-]{1,255}", base_branch) or ".." in base_branch.split("/"):
            raise HTTPException(502, "GitHub returned an invalid base branch")

        with tempfile.TemporaryDirectory(prefix=f"kodai-session-diff-{work_session_id}-") as temp:
            askpass = Path(temp) / "git-askpass"
            askpass.write_text(
                "#!/bin/sh\ncase \"$1\" in *sername*) printf '%s\\n' x-access-token;; *) printf '%s\\n' \"$KODO_GIT_TOKEN\";; esac\n",
                encoding="utf-8",
            )
            askpass.chmod(0o700)
            git_env = _git_auth_env(token, askpass)
            _git(workspace, "remote", "set-url", "origin", f"https://github.com/{repo.full_name}.git")
            _git(workspace, "fetch", "origin", f"refs/heads/{base_branch}:refs/remotes/origin/{base_branch}", env=git_env, timeout=180)
            if destination.pull_request_number:
                # Refresh the PR head's remote-tracking ref before calculating pending
                # commits. Otherwise it can keep pointing at the old pre-push SHA.
                _git(workspace, "fetch", "origin", f"refs/heads/{destination.branch}:refs/remotes/origin/{destination.branch}", env=git_env, timeout=180)

        base_ref = f"refs/remotes/origin/{base_branch}"
        status_by_path = _session_git_status(workspace)
        for path, status in status_by_path.items():
            if status["working_status"] == "??":
                _git(workspace, "add", "-N", "--", path)
        status_by_path = _session_git_status(workspace)
        names = _git(workspace, "diff", "--name-status", "--no-renames", base_ref, "--")
        files, combined_size, truncated = [], 0, False
        for line in names.splitlines():
            status, separator, path = line.partition("\t")
            if not separator or not path:
                continue
            patch = _git(workspace, "diff", "--no-ext-diff", "--no-color", "--unified=3", base_ref, "--", path)
            working = status_by_path.get(path, {})
            staged_patch = ""
            unstaged_patch = ""
            if working.get("staged"):
                staged_patch = _git(workspace, "diff", "--cached", "--no-ext-diff", "--no-color", "--unified=3", "HEAD", "--", path)
            if working.get("unstaged"):
                unstaged_patch = _git(workspace, "diff", "--no-ext-diff", "--no-color", "--unified=3", "--", path)
            remaining = max(0, config.MAX_DIFF_CHARS - combined_size)
            if len(patch) > remaining:
                patch, truncated = patch[:remaining], True
            combined_size += len(patch)
            files.append({"status": status, "path": path, "patch": patch,
                          "staged_patch": staged_patch, "unstaged_patch": unstaged_patch,
                          "staged": bool(working.get("staged")), "unstaged": bool(working.get("unstaged"))})
        if destination.pull_request_number:
            ahead_ref = f"refs/remotes/origin/{destination.branch}"
        else:
            try:
                upstream = _git(workspace, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
                ahead_ref = upstream
            except RuntimeError:
                ahead_ref = base_ref
        ahead = int(_git(workspace, "rev-list", "--count", f"{ahead_ref}..HEAD") or "0")
        outgoing_files = []
        if ahead:
            for line in _git(workspace, "diff", "--name-status", "--no-renames", f"{ahead_ref}..HEAD", "--").splitlines():
                status, separator, path = line.partition("\t")
                if separator and path:
                    outgoing_files.append({"status": status, "path": path})
        pending = db.scalar(select(func.count(AgentTask.id)).where(
            AgentTask.work_session_id == work_session_id, AgentTask.state.in_(["queued", "running"]),
        )) or 0
        dirty = bool(_git(workspace, "status", "--porcelain=v1", "--untracked-files=all"))
        return {
            "branch": destination.branch, "pull_request_number": destination.pull_request_number,
            "files": files, "truncated": truncated, "staged_count": sum(item["staged"] for item in status_by_path.values()),
            "unstaged_count": sum(item["unstaged"] for item in status_by_path.values()),
            "outgoing_files": outgoing_files,
            "commits_ahead": ahead, "has_uncommitted_changes": dirty,
            "pending_count": pending,
            "can_commit": not pending and any(item["staged"] for item in status_by_path.values()),
            "can_publish": not pending and not dirty and ahead > 0,
        }
    finally:
        db.close()

@app.post("/api/repos/{repo_id}/work-sessions/{work_session_id}/stage")
async def update_session_staging(repo_id: int, work_session_id: int, request: Request):
    user_session = _session(request)
    body = await request.json()
    action = body.get("action") if isinstance(body, dict) else None
    if action not in {"stage", "unstage"}:
        raise HTTPException(422, "Choose whether to stage or unstage files")
    paths = _valid_git_paths(body.get("paths") if isinstance(body, dict) else None)
    db = SessionLocal()
    try:
        repo, work_session, destination, workspace = _session_workspace(db, repo_id, work_session_id, user_session)
        pending = db.scalar(select(func.count(AgentTask.id)).where(
            AgentTask.work_session_id == work_session_id, AgentTask.state.in_(["queued", "running"]),
        )) or 0
        if pending:
            raise HTTPException(409, "Wait for session tasks to finish before changing staged files")
        changed_paths = set(_session_git_status(workspace))
        if any(path not in changed_paths for path in paths):
            raise HTTPException(422, "One or more selected files are no longer in the session workspace")
        for path in paths:
            if action == "stage":
                _git(workspace, "add", "--", path)
            else:
                _git(workspace, "reset", "-q", "HEAD", "--", path)
        work_session.updated_at = datetime.utcnow()
        db.commit()
        return {"ok": True}
    finally:
        db.close()

@app.post("/api/repos/{repo_id}/work-sessions/{work_session_id}/commit")
async def commit_session_changes(repo_id: int, work_session_id: int, request: Request):
    user_session = _session(request)
    body = await request.json()
    message = body.get("message", "") if isinstance(body, dict) else ""
    if not isinstance(message, str) or not message.strip() or len(message.strip()) > 200:
        raise HTTPException(422, "Enter a commit message up to 200 characters")
    db = SessionLocal()
    try:
        repo, work_session, destination, workspace = _session_workspace(db, repo_id, work_session_id, user_session)
        pending = db.scalar(select(func.count(AgentTask.id)).where(
            AgentTask.work_session_id == work_session_id, AgentTask.state.in_(["queued", "running"]),
        )) or 0
        if pending:
            raise HTTPException(409, "Wait for session tasks to finish before committing")
        status = _session_git_status(workspace)
        if not any(item["staged"] for item in status.values()):
            raise HTTPException(409, "Stage at least one changed file before committing")
        try:
            _git(workspace, "-c", "user.name=kodai", "-c", "user.email=bot@kodo.ai", "commit", "-m", message.strip())
        except RuntimeError as error:
            raise HTTPException(409, str(error))
        commit_sha = _git(workspace, "rev-parse", "HEAD")
        destination.status = "open" if destination.pull_request_number else "ready"
        destination.error = ""
        destination.updated_at = datetime.utcnow()
        work_session.updated_at = datetime.utcnow()
        db.commit()
        log.info("User committed staged session changes: session_id=%s branch=%s commit=%s", work_session_id, destination.branch, commit_sha[:12])
        return {"ok": True, "commit_sha": commit_sha}
    finally:
        db.close()

@app.post("/api/repos/{repo_id}/work-sessions/{work_session_id}/retry", status_code=202)
async def retry_work_session(repo_id: int, work_session_id: int, request: Request, background_tasks: BackgroundTasks):
    session = _session(request)
    db = SessionLocal()
    try:
        repo = _authorized_repo(db, repo_id, session)
        _require_github_repo_write(session, repo)
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
        destinations = db.scalars(select(WorkSessionPullRequest).where(
            WorkSessionPullRequest.work_session_id == work_session.id,
        ).order_by(WorkSessionPullRequest.sequence)).all()
        eligibility = _session_eligibility(db.get(Repository, repo_id), [work_session], destinations)
        db.commit()
        return _work_session_response(work_session, db, eligibility[work_session.id])
    finally:
        db.close()

@app.patch("/api/repos/{repo_id}/work-sessions/{work_session_id}")
async def rename_work_session(repo_id: int, work_session_id: int, request: Request):
    user_session = _session(request)
    body = await request.json()
    title = body.get("title", "") if isinstance(body, dict) else ""
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
        raise HTTPException(422, "Enter a session title up to 200 characters")
    db = SessionLocal()
    try:
        _authorized_repo(db, repo_id, user_session)
        work_session = db.scalar(select(WorkSession).where(
            WorkSession.id == work_session_id,
            WorkSession.repository_id == repo_id,
            WorkSession.user_id == user_session["user_id"],
        ).with_for_update())
        if not work_session:
            raise HTTPException(404, "Work session not found")
        work_session.title = title.strip()
        work_session.updated_at = datetime.utcnow()
        db.commit()
        destinations = db.scalars(select(WorkSessionPullRequest).where(
            WorkSessionPullRequest.work_session_id == work_session.id,
        ).order_by(WorkSessionPullRequest.sequence)).all()
        eligibility = _session_eligibility(db.get(Repository, repo_id), [work_session], destinations)
        return _work_session_response(work_session, db, eligibility[work_session.id])
    finally:
        db.close()

@app.post("/api/repos/{repo_id}/work-sessions/{work_session_id}/publish")
async def publish_work_session(repo_id: int, work_session_id: int, request: Request):
    """Push the session branch and create one draft PR when the user is ready."""
    session = _session(request)
    body_input = await request.json()
    requested_title = body_input.get("title", "") if isinstance(body_input, dict) else ""
    requested_body = body_input.get("body", "") if isinstance(body_input, dict) else ""
    if not isinstance(requested_title, str) or len(requested_title.strip()) > 200:
        raise HTTPException(422, "Pull request title must be 200 characters or fewer")
    if not isinstance(requested_body, str) or len(requested_body.strip()) > 6000:
        raise HTTPException(422, "Pull request description must be 6,000 characters or fewer")
    db = SessionLocal()
    try:
        repo = _authorized_repo(db, repo_id, session)
        _require_github_repo_write(session, repo)
        work_session = db.scalar(select(WorkSession).where(
            WorkSession.id == work_session_id,
            WorkSession.repository_id == repo_id,
        ).with_for_update())
        if not work_session:
            raise HTTPException(404, "Work session not found")
        if work_session.status == "paused":
            raise HTTPException(409, "Retry the failed task before publishing this session")
        pending = db.scalar(select(func.count(AgentTask.id)).where(
            AgentTask.work_session_id == work_session_id,
            AgentTask.state.in_(["queued", "running"]),
        )) or 0
        if pending:
            raise HTTPException(409, "Wait for the current session tasks to finish before publishing")

        destinations = db.scalars(select(WorkSessionPullRequest).where(
            WorkSessionPullRequest.work_session_id == work_session_id,
        ).order_by(WorkSessionPullRequest.sequence.desc())).all()
        destination = destinations[0] if destinations else None
        if not destination:
            raise HTTPException(409, "This session does not have a working branch yet")
        existing_pull = None
        if destination.pull_request_number:
            if not _verify_session_pull_request(repo, destination):
                db.commit()
                raise HTTPException(409, "This session's pull request is closed. Continue in a new session to start another change.")
            existing_pull = github_request("GET", f"/repos/{repo.full_name}/pulls/{destination.pull_request_number}", installation_token(repo.installation_id))
        if destination.status not in {"ready", "open"}:
            raise HTTPException(409, "There are no completed changes to publish yet")

        token = installation_token(repo.installation_id)
        metadata = github_request("GET", f"/repos/{repo.full_name}", token)
        base_branch = (((existing_pull or {}).get("base") or {}).get("ref")
                       or metadata.get("default_branch") or "main")
        workspace = _session_workspace_path(work_session.id, destination.id)
        if not workspace.is_dir() or not (workspace / ".git").is_dir():
            raise HTTPException(409, "The saved session workspace is unavailable, so its unpublished changes cannot be pushed")
        if _git(workspace, "branch", "--show-current") != destination.branch:
            raise HTTPException(409, "The saved session workspace is on a different branch")
        if _git(workspace, "status", "--porcelain=v1", "--untracked-files=all"):
            raise HTTPException(409, "Stage and commit the reviewed session changes before publishing")

        with tempfile.TemporaryDirectory(prefix=f"kodai-publish-{work_session.id}-") as temp:
            askpass = Path(temp) / "git-askpass"
            askpass.write_text(
                "#!/bin/sh\ncase \"$1\" in *sername*) printf '%s\\n' x-access-token;; *) printf '%s\\n' \"$KODO_GIT_TOKEN\";; esac\n",
                encoding="utf-8",
            )
            askpass.chmod(0o700)
            git_env = _git_auth_env(token, askpass)
            _git(workspace, "remote", "set-url", "origin", f"https://github.com/{repo.full_name}.git")
            _git(workspace, "push", "--set-upstream", "origin", destination.branch, env=git_env, timeout=180)

        owner = repo.full_name.split("/", 1)[0]
        existing_prs = github_request("GET", f"/repos/{repo.full_name}/pulls", token, params={
            "state": "open", "head": f"{owner}:{destination.branch}", "base": base_branch, "per_page": 100,
        }) or []
        if existing_prs:
            pull = existing_prs[0]
        else:
            comparison = github_request(
                "GET",
                f"/repos/{repo.full_name}/compare/{quote(base_branch, safe='')}...{quote(destination.branch, safe='')}",
                token,
            )
            if not comparison.get("ahead_by"):
                raise HTTPException(409, "This session branch has no commits ahead of the default branch")
            completed = db.scalars(select(AgentTask).where(
                AgentTask.work_session_id == work_session.id,
                AgentTask.state == "complete",
            ).order_by(AgentTask.created_at)).all()
            task_list = "\n".join(
                f"- {(item.summary or item.instructions).replace(chr(10), ' ')[:300]}"
                for item in completed
            )
            generated_body = (
                f"## kodai session\n\nThis draft pull request gathers the changes from the **{work_session.title}** session.\n\n"
                f"### Session work\n{task_list or '- Session changes'}\n\n"
                "_Opened by kodai. Review the changes and checks before merging._"
            )[:6000]
            pull = github_request("POST", f"/repos/{repo.full_name}/pulls", token, json={
                "title": requested_title.strip() or work_session.title,
                "head": destination.branch,
                "base": base_branch,
                "body": requested_body.strip() or generated_body,
                "draft": True,
            })

        destination.status = "open"
        destination.pull_request_number = pull["number"]
        destination.pull_request_url = pull["html_url"]
        destination.error = ""
        destination.updated_at = datetime.utcnow()
        work_session.status = "ready"
        work_session.updated_at = datetime.utcnow()
        db.commit()
        log.info("Session published as draft PR: session_id=%s repo=%s branch=%s pr=%s", work_session.id, repo.full_name, destination.branch, pull["number"])
        destinations = db.scalars(select(WorkSessionPullRequest).where(
            WorkSessionPullRequest.work_session_id == work_session_id,
        ).order_by(WorkSessionPullRequest.sequence)).all()
        eligibility = _session_eligibility(repo, [work_session], destinations)
        db.commit()
        return _work_session_response(work_session, db, eligibility[work_session.id])
    except HTTPException:
        db.rollback()
        raise
    except Exception as error:
        db.rollback()
        log.exception("Could not publish session: session_id=%s error=%s", work_session_id, error)
        raise HTTPException(502, "Could not publish this session to GitHub. Check repository access and try again.")
    finally:
        db.close()

@app.post("/api/repos/{repo_id}/tasks", status_code=202)
async def create_agent_task(repo_id: int, request: Request, background_tasks: BackgroundTasks):
    if not config.CODING_TASKS_ENABLED:
        raise HTTPException(503, "Coding tasks are disabled by backend configuration")
    session = _session(request)
    body = await request.json()
    session_title = body.get("session_title", "") if isinstance(body, dict) else ""
    instructions = body.get("instructions", "") if isinstance(body, dict) else ""
    source_pr_number = body.get("source_pull_request_number") if isinstance(body, dict) else None
    source_finding = body.get("source_finding") if isinstance(body, dict) else None
    work_session_id = body.get("work_session_id") if isinstance(body, dict) else None
    if not isinstance(session_title, str) or len(session_title.strip()) > 200:
        raise HTTPException(422, "Session title must be up to 200 characters")
    if not isinstance(instructions, str) or len(instructions.strip()) < 10 or len(instructions) > 8000:
        raise HTTPException(422, "Describe the task in 10 to 8,000 characters")
    if source_pr_number is None and source_finding is not None:
        raise HTTPException(422, "A source pull request is required for a finding task")
    if source_pr_number is not None and (not isinstance(source_pr_number, int) or isinstance(source_pr_number, bool) or source_pr_number <= 0 or not isinstance(source_finding, dict)):
        raise HTTPException(422, "Invalid source finding")
    db = SessionLocal()
    try:
        repo = _authorized_repo(db, repo_id, session)
        _require_github_repo_write(session, repo)
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
        if work_session_id is not None:
            if not isinstance(work_session_id, int) or isinstance(work_session_id, bool):
                raise HTTPException(422, "Invalid work session")
            work_session = db.scalar(select(WorkSession).where(WorkSession.id == work_session_id, WorkSession.repository_id == repo_id).with_for_update())
            if not work_session:
                raise HTTPException(404, "Work session not found")
            if work_session.status == "paused":
                raise HTTPException(409, "This session is paused after a failed task. Retry the failed task before continuing.")
        if not work_session:
            work_session = WorkSession(
                repository_id=repo_id, github_user_id=session["github_user_id"], user_id=session["user_id"],
                title=session_title.strip() or _session_title_from_instructions(instructions),
                status="active",
            )
            db.add(work_session)
            db.flush()
        elif not work_session.title:
            work_session.title = session_title.strip() or _session_title_from_instructions(instructions)
        destinations = db.scalars(select(WorkSessionPullRequest).where(
            WorkSessionPullRequest.work_session_id == work_session.id,
        ).order_by(WorkSessionPullRequest.sequence.desc())).all()
        destination = destinations[0] if destinations else None
        if destination and not _verify_session_pull_request(repo, destination):
            log.info("Session branch is no longer eligible; creating a new branch generation: session_id=%s destination_id=%s", work_session.id, destination.id)
            destination = None
        if destination is None:
            destination = _new_session_pull_request(db, work_session)
        work_session.status, work_session.error = "active", ""
        work_session.updated_at = datetime.utcnow()
        task = AgentTask(
            repository_id=repo_id, github_user_id=session["github_user_id"], user_id=session["user_id"], github_login=session["github_login"],
            instructions=instructions.strip(), state="queued",
            source_pull_request_number=source_pr_number, source_finding_key=source_key,
            work_session_id=work_session.id,
            work_session_pull_request_id=destination.id,
        )
        try:
            db.add(task)
            db.flush()
            _queue_job(db, background_tasks, "coding_session", f"agent-session:{work_session.id}", {"session_id": work_session.id})
            db.commit()
            log.info("Session task accepted: task_id=%s session_id=%s repo_id=%s requested_by=%s", task.id, work_session.id, repo_id, session["login"])
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
                            "id": task.id, "state": task.state,
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
        repo = _authorized_repo(db, repo_id, session, access="knowledge")
        member = _repo_member(db, repo, session["user_id"])
        knowledge_only = member.role == "knowledge"
        docs_query = (
            select(BookDocument).where(BookDocument.repository_id == repo_id).order_by(BookDocument.kind, BookDocument.path)
            if not knowledge_only
            else select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind == "manifest")
        )
        docs = db.scalars(docs_query).all()
        manifest = next((doc for doc in docs if doc.kind == "manifest"), None)
        try:
            build_summary = json.loads(manifest.content) if manifest else None
            if build_summary is not None:
                build_summary["stale"] = manifest.stale
        except json.JSONDecodeError:
            build_summary = None
        sections = db.scalars(select(RepoBookSection).where(RepoBookSection.repository_id == repo_id).order_by(RepoBookSection.category, RepoBookSection.slug)).all()
        if knowledge_only:
            sections = [section for section in sections if _section_visible_to_audience(section, member.audience)]
        return {
            "sections": [{"id": s.id, "slug": s.slug, "title": s.title, "category": s.category,
                "audiences": _json_list(s.audiences_json), "summary": s.summary, "blocks": _json_list(s.blocks_json),
                "source_paths": _json_list(s.source_paths_json), "stale": s.stale, "updated_at": s.updated_at.isoformat()} for s in sections],
            "documents": [] if knowledge_only else [{"id": d.id, "kind": d.kind, "path": d.path, "title": d.title, "content": d.content, "stale": d.stale, "updated_at": d.updated_at.isoformat()} for d in docs if d.kind != "manifest"],
            "build_summary": None if knowledge_only else build_summary,
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
        repo = _authorized_repo(db, repo_id, session, access="knowledge")
        member = _repo_member(db, repo, session["user_id"])
        knowledge_only = member.role == "knowledge"
        docs = [] if knowledge_only else db.scalars(select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind != "manifest")).all()
        sections = db.scalars(select(RepoBookSection).where(RepoBookSection.repository_id == repo_id)).all()
        if knowledge_only:
            sections = [section for section in sections if _section_visible_to_audience(section, member.audience)]
        rows = db.scalars(select(RepoChatMessage).where(
            RepoChatMessage.repository_id == repo_id,
            RepoChatMessage.user_id == session["user_id"],
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
        repo = _authorized_repo(db, repo_id, session, access="knowledge")
        member = _repo_member(db, repo, session["user_id"])
        knowledge_only = member.role == "knowledge"
        maintainer_context = "" if knowledge_only else format_context(*load_context(db, repo.installation_id, repo_id))
        documents = [] if knowledge_only else db.scalars(select(BookDocument).where(BookDocument.repository_id == repo_id, BookDocument.kind != "manifest").order_by(BookDocument.kind, BookDocument.path)).all()
        sections = db.scalars(select(RepoBookSection).where(RepoBookSection.repository_id == repo_id).order_by(RepoBookSection.slug)).all()
        if knowledge_only:
            sections = [section for section in sections if _section_visible_to_audience(section, member.audience)]
        if not documents and not sections:
            raise HTTPException(409, "Generate the Handbook before asking questions about this repository")
        if any("Mock Handbook" in doc.content or "mock mode" in doc.content.lower() for doc in documents) or any("AI is disabled" in section.summary for section in sections):
            raise HTTPException(409, "This Handbook contains mock summaries. Regenerate it with live AI before asking repository questions.")
        recent = db.scalars(select(RepoChatMessage).where(
            RepoChatMessage.repository_id == repo_id,
            RepoChatMessage.user_id == session["user_id"],
        ).order_by(RepoChatMessage.created_at.desc(), RepoChatMessage.id.desc()).limit(10)).all()
        recent.reverse()
        history = [{"role": row.role, "content": row.content} for row in recent]
        section_docs = [_section_for_retrieval(section) for section in sections]
        selected_sources = retrieve_book_context(question, [*section_docs, *documents])
        if not selected_sources:
            raise HTTPException(409, "The Handbook has no readable notes yet. Regenerate it, then try again.")
        user_message = RepoChatMessage(repository_id=repo_id, github_user_id=session.get("github_user_id"), user_id=session["user_id"], role="user", content=question)
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
            repository_id=repo_id, github_user_id=session.get("github_user_id"), user_id=session["user_id"], role="assistant",
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
        _authorized_repo(db, repo_id, session, access="knowledge")
        db.query(RepoChatMessage).filter(
            RepoChatMessage.repository_id == repo_id,
            RepoChatMessage.user_id == session["user_id"],
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
            RepoChatMessage.user_id == session["user_id"],
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
        memberships = db.scalars(select(OrganizationMembership).where(
            OrganizationMembership.user_id == session["user_id"], OrganizationMembership.organization_id == session.get("organization_id"),
            OrganizationMembership.role.in_(["owner", "admin", "developer"]),
        )).all()
        repo_ids = [repo_id for membership in memberships for repo_id in db.scalars(
            select(Repository.id).join(Installation, Installation.id == Repository.installation_id).where(
                Repository.organization_id == membership.organization_id,
                Installation.organization_id == membership.organization_id,
                Installation.account_type.ilike("organization"),
            )
        ).all() if _member_can_access_repo(membership, repo_id)]
        if not repo_ids:
            return []
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
                    _remove_coding_workspaces(db, install_repos)
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
                saved_installation = db.get(Installation, install["id"])
                if not saved_installation:
                    saved_installation = Installation(id=install["id"])
                    db.add(saved_installation)
                saved_installation.account = account.get("login", "")
                saved_installation.account_type = account.get("type", "User")
                saved_installation.suspended = False
                if (saved_installation.account_type or "").casefold() != "organization":
                    saved_installation.organization_id = None
                    db.query(Repository).filter(Repository.installation_id == install["id"]).update(
                        {"organization_id": None}, synchronize_session=False,
                    )
        elif event == "installation_repositories":
            install_data = payload.get("installation", {})
            install_id = install_data.get("id")
            account = install_data.get("account") or {}
            installation = db.get(Installation, install_id) if install_id else None
            if install_id and not installation:
                installation = Installation(
                    id=install_id,
                    account=account.get("login", ""),
                    account_type=account.get("type", "User"),
                    suspended=bool(install_data.get("suspended_at")),
                )
                db.add(installation)
                db.flush()
            mapped_org_id = (
                installation.organization_id
                if installation and (installation.account_type or "").casefold() == "organization"
                else None
            )
            for r in payload.get("repositories_added", []):
                saved_repo = db.get(Repository, r["id"])
                if saved_repo and saved_repo.organization_id and mapped_org_id and saved_repo.organization_id != mapped_org_id:
                    log.warning(
                        "GitHub repository addition skipped because it is linked to another kodai organization: repo_id=%s installation_id=%s",
                        r["id"], install_id,
                    )
                    continue
                if not saved_repo:
                    saved_repo = Repository(id=r["id"], installation_id=install_id, full_name=r["full_name"])
                    db.add(saved_repo)
                saved_repo.installation_id = install_id
                saved_repo.full_name = r["full_name"]
                saved_repo.private = r.get("private", True)
                saved_repo.enabled = True
                saved_repo.organization_id = mapped_org_id
            for r in payload.get("repositories_removed", []):
                _remove_coding_workspaces(db, [r["id"]])
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
                        destination.error = "The pull request is closed or merged. The next coding turn starts a new branch in this session."
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
