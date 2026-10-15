"""Repository, organization, and role-based access checks."""
import json
import logging
import shutil
from urllib.parse import quote

import requests
from fastapi import HTTPException
from sqlalchemy import select

from .. import config
from ..integrations import github_request, installation_token
from ..models import (
    AgentTask, BookDocument, Installation, OrganizationMembership, PullRequest,
    RepoBookSection, RepoChatMessage, Repository, UsageRecord, WorkSession, Workspace, Organization,
)
from .auth import _user_github_request
from .serialization import _json_list

log = logging.getLogger("kodo.access")

def _sync_installation_repositories(db, installation: Installation) -> int:
    """Refresh repositories only from an installation explicitly linked to a Kodai workspace."""
    workspace = db.get(Workspace, installation.workspace_id) if installation.workspace_id else None
    if not workspace or installation.suspended:
        return 0
    if workspace.kind == "personal":
        if (installation.account_type or "").casefold() != "user" or not workspace.owner_user_id:
            return 0
        organization_id = None
    elif workspace.kind == "organization":
        organization = db.scalar(select(Organization).where(Organization.workspace_id == workspace.id))
        if (installation.account_type or "").casefold() != "organization" or not organization or installation.organization_id != organization.id:
            return 0
        organization_id = organization.id
    else:
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
            if saved and saved.workspace_id and saved.workspace_id != workspace.id:
                # A GitHub repository may be installed in more than one account.
                # Its Kodai history stays with its one explicitly selected workspace.
                log.info("Skipping repository already connected to another Kodai workspace: repo_id=%s", repo["id"])
                continue
            if saved:
                saved.installation_id = installation.id
                saved.full_name = repo["full_name"]
                saved.private = repo.get("private", True)
                saved.organization_id = organization_id
                saved.workspace_id = workspace.id
                saved.connected = True
            else:
                db.add(Repository(
                    id=repo["id"], installation_id=installation.id,
                    full_name=repo["full_name"], private=repo.get("private", True),
                    organization_id=organization_id, workspace_id=workspace.id,
                    connected=True,
                ))
        if len(batch) < 100:
            break

    stale = db.scalars(select(Repository).where(Repository.installation_id == installation.id)).all()
    for repo in stale:
        if repo.id not in visible and repo.workspace_id == workspace.id:
            # Unlinking GitHub access must not erase Kodai task, Handbook, or chat history.
            repo.connected = False
    return len(visible)

def _sync_organization_repositories(db, organization_id: str) -> None:
    installations = db.scalars(select(Installation).where(
        Installation.organization_id == organization_id,
        Installation.account_type.ilike("organization"),
    )).all()
    for installation in installations:
        _sync_installation_repositories(db, installation)


def _sync_workspace_repositories(db, workspace_id: str) -> None:
    installations = db.scalars(select(Installation).where(Installation.workspace_id == workspace_id)).all()
    for installation in installations:
        _sync_installation_repositories(db, installation)

def _authorized_repo(db, repo_id: int, session: dict, access: str = "developer") -> Repository:
    repo = db.get(Repository, repo_id)
    if not repo or not repo.connected or not repo.workspace_id or repo.workspace_id != session.get("workspace_id"):
        raise HTTPException(404, "Repository not found")
    workspace = db.get(Workspace, repo.workspace_id)
    installation = db.get(Installation, repo.installation_id)
    if not workspace or not installation or installation.suspended or installation.workspace_id != workspace.id:
        raise HTTPException(404, "Repository not found")
    if workspace.kind == "personal":
        if workspace.owner_user_id != session["user_id"] or (installation.account_type or "").casefold() != "user" or repo.organization_id:
            raise HTTPException(404, "Repository not found")
        return repo
    if workspace.kind != "organization" or not repo.organization_id:
        raise HTTPException(404, "Repository not found")
    organization = db.get(Organization, repo.organization_id)
    if not organization or organization.workspace_id != workspace.id or installation.organization_id != organization.id or (installation.account_type or "").casefold() != "organization":
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
    workspace = db.get(Workspace, repo.workspace_id) if repo.workspace_id else None
    if workspace and workspace.kind == "personal" and workspace.owner_user_id == user_id:
        return None
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
    workspace = db.get(Workspace, repo.workspace_id) if repo.workspace_id else None
    if workspace and workspace.kind == "personal" and workspace.owner_user_id == user_id:
        return type("PersonalWorkspaceAccess", (), {"role": "owner", "audience": "all", "repository_scope": "all"})()
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
