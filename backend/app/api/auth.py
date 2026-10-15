"""Authentication endpoints and GitHub OAuth callbacks."""
import hmac
import hashlib
import logging
import os
import re
import requests
import secrets
import smtplib
from datetime import datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature
from sqlalchemy import select

from .. import config
from ..db import SessionLocal
from ..integrations import github_request
from ..models import AuthIdentity, EmailVerification, Organization, OrganizationInvite, OrganizationMembership, User, UserSession, Workspace
from ..services.auth import _session
from ..services.security import (
    _cookie_secure, _encrypt_token, _hash_password, _safe_app_return_path,
    _verify_password, serializer,
)
from ..services.email_delivery import send_verification_email
from ..services.workspaces import ensure_personal_workspace, workspace_for_organization

router = APIRouter()
log = logging.getLogger("kodo.auth")


def _accept_verified_invites(db, user_record: User, now: datetime):
    if not user_record.email or not user_record.email_verified_at:
        return []
    invites = db.scalars(select(OrganizationInvite).where(
        OrganizationInvite.email == user_record.email,
        OrganizationInvite.accepted_at.is_(None),
        OrganizationInvite.expires_at > now,
    ).order_by(OrganizationInvite.created_at, OrganizationInvite.id).with_for_update()).all()
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
    return invites


def _create_email_verification(db, user: User, email: str, purpose: str, password_hash: str | None = None):
    db.query(EmailVerification).filter(
        EmailVerification.user_id == user.id,
        EmailVerification.purpose == purpose,
        EmailVerification.consumed_at.is_(None),
    ).delete(synchronize_session=False)
    token = secrets.token_urlsafe(32)
    db.add(EmailVerification(
        user_id=user.id, email=email, purpose=purpose,
        token_hash=hashlib.sha256(token.encode()).hexdigest(), password_hash=password_hash,
        expires_at=datetime.utcnow() + timedelta(minutes=30),
    ))
    return token


@router.get("/api/auth/github")
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

@router.get("/auth/callback")
@router.get("/api/auth/callback")
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

        personal_workspace = ensure_personal_workspace(db, user_record)
        pending_invites = _accept_verified_invites(db, user_record, now)
        memberships = db.scalars(select(OrganizationMembership).where(
            OrganizationMembership.user_id == user_record.id,
        ).order_by(OrganizationMembership.id)).all()

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
            active_workspace = workspace_for_organization(db, pending_invites[0].organization_id)
        else:
            active_workspace = db.get(Workspace, target_session.active_workspace_id) if target_session.active_workspace_id else None
            if active_workspace and active_workspace.kind == "organization":
                member = db.scalar(select(OrganizationMembership.id).where(
                    OrganizationMembership.organization_id == select(Organization.id).where(Organization.workspace_id == active_workspace.id).scalar_subquery(),
                    OrganizationMembership.user_id == user_record.id,
                ))
                if not member:
                    active_workspace = None
            elif active_workspace and active_workspace.kind == "personal" and active_workspace.owner_user_id != user_record.id:
                active_workspace = None
            active_workspace = active_workspace or personal_workspace
        target_session.active_workspace_id = active_workspace.id if active_workspace else personal_workspace.id
        active_org = db.scalar(select(Organization).where(Organization.workspace_id == target_session.active_workspace_id))
        target_session.active_organization_id = active_org.id if active_org else None
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

@router.post("/api/auth/logout")
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

@router.get("/api/me")
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
        "workspace_id": session["workspace_id"], "workspace_kind": session["workspace_kind"],
        "workspace_name": session["workspace_name"],
    }

@router.post("/api/auth/email")
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
        user_record = db.scalar(select(User).where(User.email == email))
        identity = db.scalar(select(AuthIdentity).where(
            AuthIdentity.provider == "email_password", AuthIdentity.provider_user_id == email,
        ))
        now = datetime.utcnow()
        if mode == "signup":
            password_hash = _hash_password(password)
            if identity:
                raise HTTPException(409, "An email and password account already exists for this email. Sign in instead.")
            if user_record and user_record.email_verified_at:
                raise HTTPException(409, "A kodai account already uses this verified email. Sign in with its existing method.")
            if user_record:
                pending = db.scalar(select(EmailVerification).where(
                    EmailVerification.user_id == user_record.id,
                    EmailVerification.purpose == "signup",
                    EmailVerification.consumed_at.is_(None),
                    EmailVerification.expires_at > now,
                ).order_by(EmailVerification.created_at.desc()))
                if pending and pending.password_hash and not _verify_password(password, pending.password_hash):
                    raise HTTPException(409, "An account is already being verified for this email. Use its original password or sign in with the existing account.")
                if not pending:
                    token = _create_email_verification(db, user_record, email, "signup", password_hash)
                else:
                    token = _create_email_verification(db, user_record, email, "signup", pending.password_hash or password_hash)
            else:
                user_record = User(email=email, name=name or email.split("@", 1)[0], last_login_at=now)
                db.add(user_record)
                db.flush()
                ensure_personal_workspace(db, user_record)
                token = _create_email_verification(db, user_record, email, "signup", password_hash)
            db.commit()
            try:
                email_sent = send_verification_email(email, token)
            except (OSError, smtplib.SMTPException):
                log.exception("Email verification delivery failed")
                email_sent = False
            return {"ok": True, "email": email, "verification_required": True, "email_sent": email_sent}

        if not identity or not user_record or identity.user_id != user_record.id:
            raise HTTPException(401, "No email and password account was found. Create an account or sign in with GitHub.")
        if not _verify_password(password, identity.password_hash or ""):
            raise HTTPException(401, "Invalid email or password")
        if not user_record.email_verified_at:
            token = _create_email_verification(db, user_record, email, "signup", identity.password_hash)
            db.commit()
            try:
                email_sent = send_verification_email(email, token)
            except (OSError, smtplib.SMTPException):
                log.exception("Email verification delivery failed")
                email_sent = False
            return {"ok": True, "email": email, "verification_required": True, "email_sent": email_sent}
        user_record.last_login_at = now
        personal = ensure_personal_workspace(db, user_record)
        invites = _accept_verified_invites(db, user_record, now)
        workspace = workspace_for_organization(db, invites[0].organization_id) if invites else personal
        organization = db.scalar(select(Organization).where(Organization.workspace_id == workspace.id)) if workspace else None
        session_id = secrets.token_urlsafe(32)
        db.add(UserSession(
            id=session_id, user_id=user_record.id, expires_at=now + timedelta(days=7),
            active_workspace_id=workspace.id if workspace else personal.id,
            active_organization_id=organization.id if organization else None,
        ))
        db.commit()
        response.set_cookie("kodo_session", serializer.dumps(session_id), httponly=True, secure=_cookie_secure(), samesite="lax", max_age=604800)
        return {"ok": True, "email": email}
    finally:
        db.close()


@router.post("/api/auth/email/verify")
async def verify_email(request: Request, response: Response):
    body = await request.json()
    raw_token = body.get("token") if isinstance(body, dict) else None
    if not isinstance(raw_token, str) or len(raw_token) > 200:
        raise HTTPException(422, "Use the verification link from your email")
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        verification = db.scalar(select(EmailVerification).where(
            EmailVerification.token_hash == token_hash,
            EmailVerification.consumed_at.is_(None),
            EmailVerification.expires_at > now,
        ).with_for_update())
        if not verification:
            raise HTTPException(400, "This verification link is invalid, expired, or already used. Request a new one.")
        user_record = db.get(User, verification.user_id)
        if not user_record:
            raise HTTPException(400, "This verification link is no longer valid")
        email_owner = db.scalar(select(User).where(User.email == verification.email))
        if email_owner and email_owner.id != user_record.id:
            raise HTTPException(409, "This email is already linked to another kodai account")
        identity = db.scalar(select(AuthIdentity).where(
            AuthIdentity.provider == "email_password", AuthIdentity.provider_user_id == verification.email,
        ))
        if identity and identity.user_id != user_record.id:
            raise HTTPException(409, "This email sign-in is already linked to another kodai account")
        if verification.purpose == "link_email" and user_record.email and user_record.email != verification.email:
            raise HTTPException(409, "This account already has a different email address")
        if verification.purpose not in {"signup", "link_email"}:
            raise HTTPException(400, "This verification link is invalid")
        user_record.email = verification.email
        user_record.email_verified_at = now
        user_record.last_login_at = now
        if verification.password_hash:
            if identity:
                identity.password_hash = verification.password_hash
                identity.updated_at = now
            else:
                db.add(AuthIdentity(
                    user_id=user_record.id, provider="email_password", provider_user_id=verification.email,
                    password_hash=verification.password_hash,
                ))
        verification.consumed_at = now
        personal = ensure_personal_workspace(db, user_record)
        invites = _accept_verified_invites(db, user_record, now)
        workspace = workspace_for_organization(db, invites[0].organization_id) if invites else personal
        organization = db.scalar(select(Organization).where(Organization.workspace_id == workspace.id)) if workspace else None
        session_id = secrets.token_urlsafe(32)
        db.add(UserSession(
            id=session_id, user_id=user_record.id, expires_at=now + timedelta(days=7),
            active_workspace_id=workspace.id if workspace else personal.id,
            active_organization_id=organization.id if organization else None,
        ))
        db.commit()
        response.set_cookie("kodo_session", serializer.dumps(session_id), httponly=True,
                            secure=_cookie_secure(), samesite="lax", max_age=604800)
        return {"ok": True, "email": user_record.email}
    finally:
        db.close()

@router.post("/api/auth/email/link")
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
        token = _create_email_verification(db, user_record, email, "link_email", _hash_password(password))
        db.commit()
        try:
            email_sent = send_verification_email(email, token)
        except (OSError, smtplib.SMTPException):
            log.exception("Email verification delivery failed")
            email_sent = False
        return {"ok": True, "email": email, "verification_required": True, "email_sent": email_sent}
    finally:
        db.close()
