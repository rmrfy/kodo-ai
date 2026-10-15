"""GitHub installation, repository, and maintainer-context endpoints."""
import logging
import os
import requests
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, or_, select

from .. import config
from ..db import SessionLocal
from ..integrations import github_request, installation_token
from ..maintainer_context import MAX_CONTEXT_CHARS
from ..models import (
    BookDocument, ContextFile, Installation, OrganizationMembership, PullRequest,
    RepoBookSection, Repository, WorkSession, Workspace, Organization,
)
from ..services.auth import _github_user_installations, _session
from ..services.access import (
    _authorized_repo, _member_can_access_repo, _organization_admin, _require_github,
    _require_repo_admin, _sync_installation_repositories, _sync_organization_repositories, _sync_workspace_repositories,
)
from ..services.context import _save_context_file
from ..services.workspaces import user_can_manage_workspace

router = APIRouter()
log = logging.getLogger("kodo.repositories")

@router.get("/api/installations")
async def installations(request: Request):
    session = _session(request)
    db = SessionLocal()
    try:
        workspace = db.get(Workspace, session["workspace_id"])
        if not workspace or not ((workspace.kind == "personal" and workspace.owner_user_id == session["user_id"]) or (workspace.kind == "organization" and session.get("role") in {"owner", "admin"})):
            raise HTTPException(403, "Workspace owner or admin access is required")
        rows = db.scalars(select(Installation).where(
            Installation.workspace_id == session["workspace_id"],
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
        workspace = db.get(Workspace, session["workspace_id"])
        if not workspace:
            raise HTTPException(404, "Workspace not found")
        if workspace.kind == "organization":
            _organization_admin(db, session)
            expected_type = "organization"
        elif workspace.kind == "personal" and workspace.owner_user_id == session["user_id"]:
            expected_type = "user"
        else:
            raise HTTPException(404, "Workspace not found")
        linked = _github_user_installations(session)
        available = []
        for item in linked:
            account = item.get("account") or {}
            if (account.get("type") or "").casefold() != expected_type:
                continue
            saved = db.get(Installation, item["id"])
            if saved and saved.workspace_id and saved.workspace_id != workspace.id:
                continue
            if saved and saved.workspace_id == workspace.id and not saved.suspended:
                still_connected = db.scalar(select(Repository.id).where(
                    Repository.installation_id == saved.id, Repository.connected.is_(True),
                ).limit(1))
                if still_connected:
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
        workspace = db.get(Workspace, session["workspace_id"])
        if not workspace:
            raise HTTPException(404, "Workspace not found")
        if workspace.kind == "organization":
            owner = _organization_admin(db, session)
            expected_type = "organization"
        elif workspace.kind == "personal" and workspace.owner_user_id == session["user_id"]:
            owner = None
            expected_type = "user"
        else:
            raise HTTPException(404, "Workspace not found")
        item = next((row for row in _github_user_installations(session) if row.get("id") == installation_id), None)
        if not item:
            raise HTTPException(404, "This GitHub App installation is not accessible to your connected GitHub account.")
        account = item.get("account") or {}
        if (account.get("type") or "").casefold() != expected_type:
            label = "GitHub Organization" if expected_type == "organization" else "personal GitHub account"
            raise HTTPException(422, f"Only {label} installations can be connected to this Kodai workspace.")
        saved = db.get(Installation, installation_id)
        if saved and saved.workspace_id and saved.workspace_id != workspace.id:
            raise HTTPException(409, "This GitHub installation is already connected to another Kodai workspace.")

        if not saved:
            saved = Installation(id=installation_id)
            db.add(saved)
        saved.account = account.get("login", "")
        saved.account_type = account.get("type", "Organization")
        saved.suspended = bool(item.get("suspended_at"))
        saved.workspace_id = workspace.id
        saved.organization_id = owner.organization_id if owner else None
        db.flush()

        repo_count = _sync_installation_repositories(db, saved)
        db.commit()
        log.info(
            "GitHub installation connected to Kodai workspace: installation_id=%s account=%s workspace=%s repos=%s",
            installation_id, saved.account, workspace.id, repo_count,
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
        workspace = db.get(Workspace, session["workspace_id"])
        if not workspace or not ((workspace.kind == "personal" and workspace.owner_user_id == session["user_id"]) or (workspace.kind == "organization" and session.get("role") in {"owner", "admin"})):
            raise HTTPException(403, "Workspace owner or admin access is required")
    finally:
        db.close()
    slug = os.getenv("GITHUB_APP_SLUG", "")
    return {"url": f"https://github.com/apps/{slug}/installations/new" if slug else None}

@router.get("/api/repos")
async def repositories(request: Request):
    session = _session(request)
    db = SessionLocal()
    try:
        if session.get("workspace_id") and (session.get("workspace_kind") == "personal" or session.get("role") in {"owner", "admin"}):
            _sync_workspace_repositories(db, session["workspace_id"])
            db.commit()
        if session.get("workspace_kind") == "personal":
            workspace = db.get(Workspace, session["workspace_id"])
            if not workspace or workspace.owner_user_id != session["user_id"]:
                raise HTTPException(404, "Workspace not found")
            rows = db.scalars(select(Repository).join(
                Installation, Installation.id == Repository.installation_id,
            ).where(
                Repository.workspace_id == workspace.id,
                Repository.connected.is_(True),
                Installation.workspace_id == workspace.id,
                Installation.suspended.is_(False),
                Installation.account_type.ilike("user"),
                Repository.organization_id.is_(None),
            )).all()
            return [{"id": r.id, "installation_id": r.installation_id, "full_name": r.full_name, "private": r.private, "enabled": r.enabled, "review_mode": r.review_mode,
                     "workspace_id": r.workspace_id, "role": "owner", "audience": "all"} for r in rows]
        members = db.scalars(select(OrganizationMembership).where(
            OrganizationMembership.user_id == session["user_id"], OrganizationMembership.organization_id == session.get("organization_id"),
        )).all()
        member_by_organization = {member.organization_id: member for member in members}
        rows = db.scalars(select(Repository).join(
            Installation, Installation.id == Repository.installation_id,
        ).where(
            Repository.workspace_id == session.get("workspace_id"),
            Repository.connected.is_(True),
            Repository.organization_id.in_(member_by_organization),
            Installation.workspace_id == session.get("workspace_id"),
            Installation.suspended.is_(False),
            Installation.organization_id == Repository.organization_id,
            Installation.account_type.ilike("organization"),
        )).all() if member_by_organization else []
        rows = [repo for repo in rows if _member_can_access_repo(member_by_organization[repo.organization_id], repo.id)]
        return [{"id": r.id, "installation_id": r.installation_id, "full_name": r.full_name, "private": r.private, "enabled": r.enabled, "review_mode": r.review_mode, "organization_id": r.organization_id, "workspace_id": r.workspace_id,
                 "role": member_by_organization[r.organization_id].role, "audience": member_by_organization[r.organization_id].audience} for r in rows]
    finally:
        db.close()


@router.get("/api/workspaces/{workspace_id}/repositories")
async def workspace_repositories_for_transfer(workspace_id: str, request: Request):
    session = _session(request)
    try:
        workspace_id = str(UUID(workspace_id))
    except ValueError:
        raise HTTPException(404, "Workspace not found")
    db = SessionLocal()
    try:
        workspace = db.get(Workspace, workspace_id)
        if not workspace or not user_can_manage_workspace(db, session["user_id"], workspace):
            raise HTTPException(404, "Workspace not found")
        rows = db.scalars(select(Repository).where(
            Repository.workspace_id == workspace.id,
            Repository.connected.is_(True),
        ).order_by(Repository.full_name)).all()
        return [{"id": repo.id, "full_name": repo.full_name, "private": repo.private,
                 "workspace_id": workspace.id, "installation_id": repo.installation_id} for repo in rows]
    finally:
        db.close()


@router.post("/api/repos/{repo_id}/transfer")
async def transfer_repository(repo_id: int, request: Request):
    """Move a repository and its Kodai history between workspaces explicitly."""
    session = _session(request)
    _require_github(session)
    body = await request.json()
    raw_source_id = body.get("source_workspace_id") if isinstance(body, dict) else None
    installation_id = body.get("installation_id") if isinstance(body, dict) else None
    if not isinstance(raw_source_id, str):
        raise HTTPException(422, "Choose the repository's current workspace")
    try:
        source_workspace_id = str(UUID(raw_source_id))
    except ValueError:
        raise HTTPException(422, "Choose a valid source workspace")
    if not isinstance(installation_id, int) or isinstance(installation_id, bool):
        raise HTTPException(422, "Choose a GitHub installation connected to the destination workspace")

    db = SessionLocal()
    try:
        destination = db.get(Workspace, session.get("workspace_id"))
        source = db.get(Workspace, source_workspace_id)
        repo = db.get(Repository, repo_id)
        if not destination or not source or not repo or repo.workspace_id != source.id or not repo.connected:
            raise HTTPException(404, "Repository or workspace not found")
        if destination.id == source.id:
            raise HTTPException(409, "The repository is already in this workspace")
        if not user_can_manage_workspace(db, session["user_id"], source) or not user_can_manage_workspace(db, session["user_id"], destination):
            raise HTTPException(403, "Workspace owner or admin access is required in both workspaces")
        installation = db.get(Installation, installation_id)
        if not installation or installation.workspace_id != destination.id or installation.suspended:
            raise HTTPException(404, "Destination GitHub installation not found")
        destination_org = db.scalar(select(Organization).where(Organization.workspace_id == destination.id)) if destination.kind == "organization" else None
        expected_type = "organization" if destination.kind == "organization" else "user"
        if (installation.account_type or "").casefold() != expected_type or (destination.kind == "organization" and not destination_org):
            raise HTTPException(409, "The installation does not match the destination workspace type")

        try:
            token = installation_token(installation.id)
            is_installed = False
            for page in range(1, 101):
                result = github_request("GET", "/installation/repositories", token, params={"per_page": 100, "page": page}) or {}
                repositories = result.get("repositories", [])
                if any(int(item.get("id", 0)) == repo_id for item in repositories):
                    is_installed = True
                    break
                if len(repositories) < 100:
                    break
        except requests.RequestException as error:
            log.exception("Could not verify destination GitHub access for repository transfer: repo_id=%s", repo_id)
            raise HTTPException(502, "Could not verify repository access in the destination GitHub installation") from error
        if not is_installed:
            raise HTTPException(403, "The destination GitHub installation does not have access to this repository")

        repo.installation_id = installation.id
        repo.workspace_id = destination.id
        repo.organization_id = destination_org.id if destination_org else None
        repo.connected = True
        db.commit()
        return {"repository_id": repo.id, "workspace_id": destination.id, "workspace_name": destination.name}
    except HTTPException:
        db.rollback()
        raise
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
