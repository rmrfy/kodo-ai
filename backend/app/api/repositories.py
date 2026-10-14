"""GitHub installation, repository, and maintainer-context endpoints."""
import logging
import os
import requests
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, or_, select

from .. import config
from ..db import SessionLocal
from ..integrations import github_request
from ..maintainer_context import MAX_CONTEXT_CHARS
from ..models import (
    BookDocument, ContextFile, Installation, OrganizationMembership, PullRequest,
    RepoBookSection, Repository, WorkSession,
)
from ..services.auth import _github_user_installations, _session
from ..services.access import (
    _authorized_repo, _member_can_access_repo, _organization_admin, _require_github,
    _require_repo_admin, _sync_installation_repositories, _sync_organization_repositories,
)
from ..services.context import _save_context_file

router = APIRouter()
log = logging.getLogger("kodo.repositories")

@router.get("/api/installations")
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

@router.get("/api/installations/available")
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

@router.post("/api/installations/{installation_id}/connect")
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

@router.get("/api/app-install-url")
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

@router.get("/api/repos")
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

@router.get("/api/repos/{repo_id}/summary")
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

@router.get("/api/context-files")
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

@router.put("/api/installations/{installation_id}/context")
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

@router.put("/api/repos/{repo_id}/context")
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

@router.patch("/api/repos/{repo_id}")
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
