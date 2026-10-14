"""Request-session validation and user-scoped GitHub authentication."""
import os
import requests
from datetime import datetime, timedelta
from urllib.parse import quote

from fastapi import HTTPException, Request
from itsdangerous import BadSignature
from sqlalchemy import select

from ..db import SessionLocal
from ..integrations import github_request
from ..models import AuthIdentity, Organization, OrganizationMembership, User, UserSession
from .security import _decrypt_token, _encrypt_token, serializer
from .serialization import _json_list

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
