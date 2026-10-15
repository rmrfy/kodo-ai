"""Organization, membership, and invitation endpoints."""
import json
import logging
import re
import smtplib
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from ..db import SessionLocal
from ..models import (
    AuthIdentity, Installation, Organization, OrganizationInvite, OrganizationMembership,
    RepoChatMessage, Repository, User, UserSession, Workspace,
)
from ..services.auth import _session
from ..services.access import _organization_admin
from ..services.serialization import _json_list
from ..services.email_delivery import send_organization_invite
from ..services.workspaces import create_organization_workspace, user_can_access_workspace, workspace_for_organization

router = APIRouter()
log = logging.getLogger("kodo.organizations")


@router.get("/api/workspaces")
async def list_workspaces(request: Request):
    session = _session(request)
    db = SessionLocal()
    try:
        personal = db.scalars(select(Workspace).where(
            Workspace.kind == "personal", Workspace.owner_user_id == session["user_id"],
        )).all()
        rows = db.execute(select(OrganizationMembership, Organization, Workspace).join(
            Organization, Organization.id == OrganizationMembership.organization_id,
        ).join(Workspace, Workspace.id == Organization.workspace_id).where(
            OrganizationMembership.user_id == session["user_id"], Workspace.kind == "organization",
        ).order_by(OrganizationMembership.created_at, Organization.name)).all()
        result = [{"id": item.id, "kind": item.kind, "name": item.name, "role": "owner", "active": item.id == session["workspace_id"]} for item in personal]
        result.extend({"id": workspace.id, "kind": "organization", "name": organization.name,
                       "role": member.role, "active": workspace.id == session["workspace_id"]}
                      for member, organization, workspace in rows)
        return result
    finally:
        db.close()


@router.post("/api/workspaces/activate")
async def activate_workspace(request: Request):
    session = _session(request)
    body = await request.json()
    workspace_id = body.get("workspace_id") if isinstance(body, dict) else None
    if not isinstance(workspace_id, str):
        raise HTTPException(422, "Choose a workspace")
    try:
        workspace_id = str(UUID(workspace_id))
    except ValueError:
        raise HTTPException(422, "Choose a valid workspace")
    db = SessionLocal()
    try:
        workspace = db.get(Workspace, workspace_id)
        record = db.get(UserSession, session["session_id"])
        if not workspace or not record or not user_can_access_workspace(db, session["user_id"], workspace):
            raise HTTPException(404, "Workspace not found")
        organization = db.scalar(select(Organization).where(Organization.workspace_id == workspace.id)) if workspace.kind == "organization" else None
        if workspace.kind == "organization" and not organization:
            raise HTTPException(404, "Workspace not found")
        record.active_workspace_id = workspace.id
        record.active_organization_id = organization.id if organization else None
        db.commit()
        return {"workspace_id": workspace.id, "workspace_kind": workspace.kind, "workspace_name": workspace.name}
    finally:
        db.close()

@router.get("/api/organizations")
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

@router.post("/api/organizations")
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
        workspace, organization = create_organization_workspace(db, user_record, name)
        db.add(OrganizationMembership(organization_id=organization.id, user_id=user_record.id, role="owner"))
        record.active_workspace_id = workspace.id
        record.active_organization_id = organization.id
        db.commit()
        return {"id": organization.id, "name": organization.name, "role": "owner", "active": True}
    finally:
        db.close()

@router.post("/api/organization/activate")
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
        workspace = workspace_for_organization(db, organization_id)
        if not workspace:
            raise HTTPException(404, "Organization not found")
        record.active_workspace_id = workspace.id
        record.active_organization_id = organization_id
        db.commit()
        return {"organization_id": organization_id}
    finally:
        db.close()

@router.patch("/api/organization")
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
        workspace = workspace_for_organization(db, organization.id)
        if workspace:
            workspace.name = name
            workspace.updated_at = datetime.utcnow()
        db.commit()
        return {"id": organization.id, "name": organization.name}
    finally:
        db.close()


@router.post("/api/organization/transfer-owner")
async def transfer_organization_owner(request: Request):
    session = _session(request)
    body = await request.json()
    raw_user_id = body.get("new_owner_user_id") if isinstance(body, dict) else None
    if not isinstance(raw_user_id, str):
        raise HTTPException(422, "Choose an existing organization member")
    try:
        new_owner_id = str(UUID(raw_user_id))
    except ValueError:
        raise HTTPException(422, "Choose a valid organization member")
    db = SessionLocal()
    try:
        organization_id = session.get("organization_id")
        current_owner = db.scalar(select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == session["user_id"],
        ).with_for_update()) if organization_id else None
        if not current_owner or current_owner.role != "owner":
            raise HTTPException(403, "Only the current owner can transfer ownership")
        if new_owner_id == session["user_id"]:
            raise HTTPException(422, "Choose another member to become the owner")
        target = db.scalar(select(OrganizationMembership).where(
            OrganizationMembership.organization_id == current_owner.organization_id,
            OrganizationMembership.user_id == new_owner_id,
        ).with_for_update())
        if not target:
            raise HTTPException(404, "Organization member not found")
        owners = db.scalars(select(OrganizationMembership).where(
            OrganizationMembership.organization_id == current_owner.organization_id,
            OrganizationMembership.role == "owner",
        ).with_for_update()).all()
        for owner in owners:
            owner.role = "admin"
        target.role = "owner"
        organization = db.get(Organization, current_owner.organization_id)
        organization.created_by_user_id = new_owner_id
        organization.updated_at = datetime.utcnow()
        workspace = workspace_for_organization(db, organization.id)
        if workspace:
            workspace.updated_at = datetime.utcnow()
        db.commit()
        return {"organization_id": organization.id, "owner_user_id": new_owner_id}
    finally:
        db.close()

@router.post("/api/invitations/accept")
async def accept_organization_invitations(request: Request):
    session = _session(request)
    db = SessionLocal()
    try:
        user_record = db.get(User, session["user_id"])
        user_session = db.get(UserSession, session["session_id"])
        if not user_record or not user_session:
            raise HTTPException(401, "Sign in to continue")
        if not user_record.email or not user_record.email_verified_at:
            return {"accepted": 0, "verification_required": bool(user_record.email)}
        now = datetime.utcnow()
        invites = db.scalars(select(OrganizationInvite).where(
            OrganizationInvite.email == user_record.email,
            OrganizationInvite.accepted_at.is_(None), OrganizationInvite.expires_at > now,
        ).order_by(OrganizationInvite.created_at, OrganizationInvite.id).with_for_update()).all()
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
            workspace = workspace_for_organization(db, invites[0].organization_id)
            user_session.active_workspace_id = workspace.id if workspace else None
            user_session.active_organization_id = invites[0].organization_id
            db.commit()
        return {"accepted": accepted}
    finally:
        db.close()

@router.get("/api/organization/members")
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

@router.post("/api/organization/invites")
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
        try:
            email_sent = send_organization_invite(email, organization.name, session.get("name") or session.get("login") or "Your teammate", invite.expires_at, invite.id)
        except (OSError, smtplib.SMTPException):
            log.exception("Organization invitation email delivery failed")
            email_sent = False
        return {"ok": True, "email": email, "role": role, "email_sent": email_sent}
    finally:
        db.close()

@router.patch("/api/organization/members/{user_id}")
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

@router.delete("/api/organization/members/{user_id}")
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

@router.delete("/api/organization/invites/{invite_id}")
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
