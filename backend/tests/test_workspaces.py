import unittest
import os
import hashlib
import hmac
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import config
from app.db import Base
from app.main import app
from app.coding_tasks import _verify_task_requester_github_write
from app.models import (
    AuthIdentity, Installation, Organization, OrganizationInvite, OrganizationMembership,
    Repository, User, UserSession, Workspace,
)
from app.api.auth import _accept_verified_invites
from app.services.security import serializer
from app.services.access import _authorized_repo
from app.services.email_delivery import send_verification_email
from app.services.workspaces import (
    create_organization_workspace, ensure_personal_workspace,
    user_can_access_workspace, user_can_manage_workspace,
)


class WorkspaceIsolationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def make_user(self, name):
        user = User(name=name)
        self.db.add(user)
        self.db.flush()
        return user

    def test_account_provisioning_has_one_stable_private_workspace(self):
        user = self.make_user("Ashish")

        first = ensure_personal_workspace(self.db, user)
        second = ensure_personal_workspace(self.db, user)

        self.assertEqual(first.id, second.id)
        self.assertEqual(first.kind, "personal")
        self.assertEqual(first.owner_user_id, user.id)

    def test_personal_and_organization_access_are_distinct(self):
        owner = self.make_user("Owner")
        outsider = self.make_user("Outsider")
        personal = ensure_personal_workspace(self.db, owner)
        organization_workspace, organization = create_organization_workspace(self.db, owner, "Kodai team")
        self.db.add(OrganizationMembership(organization_id=organization.id, user_id=owner.id, role="owner"))
        self.db.flush()

        self.assertTrue(user_can_access_workspace(self.db, owner.id, personal))
        self.assertFalse(user_can_access_workspace(self.db, outsider.id, personal))
        self.assertTrue(user_can_access_workspace(self.db, owner.id, organization_workspace))
        self.assertFalse(user_can_access_workspace(self.db, outsider.id, organization_workspace))
        self.assertTrue(user_can_manage_workspace(self.db, owner.id, organization_workspace))
        self.assertFalse(user_can_manage_workspace(self.db, outsider.id, organization_workspace))

    def test_unverified_email_cannot_accept_an_invitation_and_acceptance_is_single_use(self):
        owner = self.make_user("Owner")
        invited = self.make_user("Invited")
        invited.email = "invited@example.com"
        workspace, organization = create_organization_workspace(self.db, owner, "Kodai team")
        self.db.add(OrganizationMembership(organization_id=organization.id, user_id=owner.id, role="owner"))
        invite = OrganizationInvite(
            organization_id=organization.id, email=invited.email, role="knowledge",
            audience="support", repository_scope="selected", repository_ids_json="[33]",
            invited_by_user_id=owner.id, expires_at=datetime.utcnow() + timedelta(days=7),
        )
        self.db.add(invite)
        self.db.flush()

        self.assertEqual(_accept_verified_invites(self.db, invited, datetime.utcnow()), [])
        self.assertIsNone(invite.accepted_at)
        self.assertEqual(self.db.query(OrganizationMembership).filter_by(user_id=invited.id).count(), 0)

        invited.email_verified_at = datetime.utcnow()
        accepted = _accept_verified_invites(self.db, invited, datetime.utcnow())
        self.db.flush()
        self.assertEqual([row.id for row in accepted], [invite.id])
        self.assertEqual(_accept_verified_invites(self.db, invited, datetime.utcnow()), [])
        member = self.db.query(OrganizationMembership).filter_by(user_id=invited.id).one()
        self.assertEqual((member.role, member.audience, member.repository_scope, member.repository_ids_json),
                         ("knowledge", "support", "selected", "[33]"))
        self.assertEqual(ensure_personal_workspace(self.db, invited).kind, "personal")

    def test_repository_access_checks_workspace_owner_role_and_installation(self):
        owner = self.make_user("Owner")
        outsider = self.make_user("Outsider")
        personal = ensure_personal_workspace(self.db, owner)
        installation = Installation(
            id=101, account="owner", account_type="User", workspace_id=personal.id,
        )
        repo = Repository(
            id=1001, installation_id=installation.id, full_name="owner/private",
            workspace_id=personal.id, organization_id=None, connected=True,
        )
        self.db.add_all([installation, repo])
        self.db.flush()

        self.assertIs(_authorized_repo(self.db, repo.id, {
            "user_id": owner.id, "workspace_id": personal.id,
        }), repo)
        with self.assertRaises(HTTPException) as denied:
            _authorized_repo(self.db, repo.id, {"user_id": outsider.id, "workspace_id": personal.id})
        self.assertEqual(denied.exception.status_code, 404)

        installation.suspended = True
        with self.assertRaises(HTTPException) as suspended:
            _authorized_repo(self.db, repo.id, {"user_id": owner.id, "workspace_id": personal.id})
        self.assertEqual(suspended.exception.status_code, 404)

    def test_knowledge_role_keeps_repository_and_feature_restrictions(self):
        owner = self.make_user("Owner")
        knowledge = self.make_user("Knowledge")
        workspace, organization = create_organization_workspace(self.db, owner, "Kodai team")
        self.db.add(OrganizationMembership(
            organization_id=organization.id, user_id=knowledge.id, role="knowledge",
            repository_scope="selected", repository_ids_json="[2001]", audience="support",
        ))
        installation = Installation(
            id=202, account="kodai-team", account_type="Organization",
            organization_id=organization.id, workspace_id=workspace.id,
        )
        allowed = Repository(
            id=2001, installation_id=installation.id, full_name="team/allowed",
            organization_id=organization.id, workspace_id=workspace.id, connected=True,
        )
        excluded = Repository(
            id=2002, installation_id=installation.id, full_name="team/excluded",
            organization_id=organization.id, workspace_id=workspace.id, connected=True,
        )
        self.db.add_all([installation, allowed, excluded])
        self.db.flush()
        session = {"user_id": knowledge.id, "workspace_id": workspace.id}

        self.assertIs(_authorized_repo(self.db, allowed.id, session, access="knowledge"), allowed)
        with self.assertRaises(HTTPException) as feature_denied:
            _authorized_repo(self.db, allowed.id, session, access="developer")
        self.assertEqual(feature_denied.exception.status_code, 403)
        with self.assertRaises(HTTPException) as repo_denied:
            _authorized_repo(self.db, excluded.id, session, access="knowledge")
        self.assertEqual(repo_denied.exception.status_code, 404)


class VerificationLinkTest(unittest.TestCase):
    def test_email_verification_token_is_put_in_fragment_not_request_path(self):
        with patch("app.services.email_delivery.config.FRONTEND_ORIGIN", "https://thekodai.com"), \
             patch("app.services.email_delivery.send_email", return_value=True) as send:
            self.assertTrue(send_verification_email("user@example.com", "one-time-token"))

        body = send.call_args.args[2]
        self.assertIn("https://thekodai.com/verify-email#token=one-time-token", body)
        self.assertNotIn("/verify-email?token=", body)


class CodingTaskGithubAuthorizationTest(unittest.TestCase):
    def test_worker_rechecks_the_requesting_users_current_github_write_access(self):
        database = MagicMock()
        database.scalar.return_value = AuthIdentity(
            user_id="user-id", provider="github", provider_user_id="123",
            provider_username="current-login", access_token="encrypted-token",
        )
        task = {
            "task_id": 10, "requester_id": "user-id", "github_user_id": 123,
            "github_login": "old-login", "full_name": "team/project",
        }
        with patch("app.coding_tasks.SessionLocal", return_value=database), \
             patch("app.coding_tasks._decrypt_token", return_value="access-token"), \
             patch("app.coding_tasks._user_github_request", return_value={"permission": "write"}) as github_request:
            _verify_task_requester_github_write(task)

        self.assertEqual(github_request.call_args.args[2], "/repos/team/project/collaborators/current-login/permission")
        database.close.assert_called_once()

    def test_worker_blocks_when_github_write_access_was_removed(self):
        database = MagicMock()
        database.scalar.return_value = AuthIdentity(
            user_id="user-id", provider="github", provider_user_id="123",
            provider_username="current-login", access_token="encrypted-token",
        )
        task = {
            "task_id": 10, "requester_id": "user-id", "github_user_id": 123,
            "github_login": "current-login", "full_name": "team/project",
        }
        with patch("app.coding_tasks.SessionLocal", return_value=database), \
             patch("app.coding_tasks._decrypt_token", return_value="access-token"), \
             patch("app.coding_tasks._user_github_request", return_value={"permission": "read"}):
            with self.assertRaisesRegex(RuntimeError, "no longer has GitHub write access"):
                _verify_task_requester_github_write(task)


class AccountProvisioningApiTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self):
        self.engine.dispose()

    def test_email_signup_verifies_before_creating_signin_and_provisions_personal_workspace(self):
        captured = {}

        def capture_verification(email, token):
            captured.update(email=email, token=token)
            return True

        with patch("app.main.SessionLocal", self.session_factory), \
             patch("app.api.auth.SessionLocal", self.session_factory), \
             patch("app.api.organizations.SessionLocal", self.session_factory), \
             patch("app.services.auth.SessionLocal", self.session_factory), \
             patch("app.api.auth.send_verification_email", side_effect=capture_verification), \
             patch.object(config, "DISABLE_APP_ROUTES", False), \
             TestClient(app) as client:
            signup = client.post("/api/auth/email", json={
                "mode": "signup", "name": "Test User", "email": "test@example.com",
                "password": "long-password-for-test",
            })
            self.assertEqual(signup.status_code, 200, signup.text)
            self.assertTrue(signup.json()["verification_required"])
            self.assertTrue(signup.json()["email_sent"])

            db = self.session_factory()
            try:
                user = db.query(User).filter_by(email="test@example.com").one()
                workspace = ensure_personal_workspace(db, user)
                owner = User(name="Workspace owner")
                db.add(owner)
                db.flush()
                organization_workspace, organization = create_organization_workspace(db, owner, "Invited team")
                db.add(OrganizationMembership(organization_id=organization.id, user_id=owner.id, role="owner"))
                db.add(OrganizationInvite(
                    organization_id=organization.id, email="test@example.com", role="developer",
                    invited_by_user_id=owner.id, expires_at=datetime.utcnow() + timedelta(days=7),
                ))
                db.commit()
                self.assertIsNone(user.email_verified_at)
                self.assertEqual(workspace.kind, "personal")
                self.assertEqual(db.query(OrganizationMembership).filter_by(user_id=user.id).count(), 0)
            finally:
                db.close()

            verified = client.post("/api/auth/email/verify", json={"token": captured["token"]})
            self.assertEqual(verified.status_code, 200, verified.text)
            me = client.get("/api/me")
            self.assertEqual(me.status_code, 200, me.text)
            self.assertTrue(me.json()["email_verified"])
            self.assertEqual(me.json()["workspace_kind"], "organization")
            self.assertEqual(me.json()["workspace_name"], "Invited team")
            workspaces = client.get("/api/workspaces").json()
            self.assertEqual({row["kind"] for row in workspaces}, {"personal", "organization"})
            self.assertEqual(sum(row["kind"] == "personal" for row in workspaces), 1)
            user_id = me.json()["id"]
            client.post("/api/auth/logout")
            signed_in = client.post("/api/auth/email", json={
                "mode": "signin", "email": "test@example.com", "password": "long-password-for-test",
            })
            self.assertEqual(signed_in.status_code, 200, signed_in.text)
            returning_me = client.get("/api/me")
            self.assertEqual(returning_me.status_code, 200, returning_me.text)
            self.assertEqual(returning_me.json()["id"], user_id)
            self.assertEqual(returning_me.json()["workspace_kind"], "personal")

    def test_workspace_switch_rejects_a_workspace_without_membership(self):
        owner = User(name="Owner")
        outsider = User(name="Outsider")
        with self.session_factory() as db:
            db.add_all([owner, outsider])
            db.flush()
            personal = ensure_personal_workspace(db, owner)
            foreign_workspace, foreign_organization = create_organization_workspace(db, outsider, "Private team")
            db.add(OrganizationMembership(organization_id=foreign_organization.id, user_id=outsider.id, role="owner"))
            session_record = UserSession(
                id="test-session", user_id=owner.id, expires_at=datetime.utcnow() + timedelta(days=1),
                active_workspace_id=personal.id,
            )
            db.add(session_record)
            db.commit()
            personal_id, foreign_id = personal.id, foreign_workspace.id

        with patch("app.main.SessionLocal", self.session_factory), \
             patch("app.api.organizations.SessionLocal", self.session_factory), \
             patch("app.services.auth.SessionLocal", self.session_factory), \
             patch.object(config, "DISABLE_APP_ROUTES", False), \
             TestClient(app) as client:
            client.cookies.set("kodo_session", serializer.dumps("test-session"))
            denied = client.post("/api/workspaces/activate", json={"workspace_id": foreign_id})
            self.assertEqual(denied.status_code, 404)
            current = client.get("/api/me")
            self.assertEqual(current.status_code, 200, current.text)
            self.assertEqual(current.json()["workspace_id"], personal_id)

    def test_organization_owner_transfer_keeps_one_owner_and_revokes_old_owner_transfer_power(self):
        owner, next_owner, other_member = User(name="Owner"), User(name="Next owner"), User(name="Other member")
        with self.session_factory() as db:
            db.add_all([owner, next_owner, other_member])
            db.flush()
            workspace, organization = create_organization_workspace(db, owner, "Team")
            db.add_all([
                OrganizationMembership(organization_id=organization.id, user_id=owner.id, role="owner"),
                OrganizationMembership(organization_id=organization.id, user_id=next_owner.id, role="developer"),
                OrganizationMembership(organization_id=organization.id, user_id=other_member.id, role="developer"),
            ])
            db.add(UserSession(
                id="owner-transfer-session", user_id=owner.id,
                expires_at=datetime.utcnow() + timedelta(days=1), active_workspace_id=workspace.id,
                active_organization_id=organization.id,
            ))
            db.commit()
            next_owner_id, other_member_id = next_owner.id, other_member.id

        with patch("app.main.SessionLocal", self.session_factory), \
             patch("app.api.organizations.SessionLocal", self.session_factory), \
             patch("app.services.auth.SessionLocal", self.session_factory), \
             patch.object(config, "DISABLE_APP_ROUTES", False), \
             TestClient(app) as client:
            client.cookies.set("kodo_session", serializer.dumps("owner-transfer-session"))
            transferred = client.post("/api/organization/transfer-owner", json={
                "new_owner_user_id": next_owner_id,
            })
            self.assertEqual(transferred.status_code, 200, transferred.text)
            rejected = client.post("/api/organization/transfer-owner", json={
                "new_owner_user_id": other_member_id,
            })
            self.assertEqual(rejected.status_code, 403, rejected.text)

        with self.session_factory() as db:
            memberships = db.query(OrganizationMembership).filter(
                OrganizationMembership.organization_id == organization.id,
            ).all()
            roles = {member.user_id: member.role for member in memberships}
            self.assertEqual(roles[owner.id], "admin")
            self.assertEqual(roles[next_owner_id], "owner")
            self.assertEqual(sum(role == "owner" for role in roles.values()), 1)

    def test_linking_verified_email_keeps_the_existing_github_account_and_workspace(self):
        user = User(name="Existing account")
        captured = {}

        def capture_verification(email, token):
            captured.update(email=email, token=token)
            return True

        with self.session_factory() as db:
            db.add(user)
            db.flush()
            personal = ensure_personal_workspace(db, user)
            db.add(AuthIdentity(
                user_id=user.id, provider="github", provider_user_id="777",
                provider_username="existing-login", access_token="",
            ))
            db.add(UserSession(
                id="link-session", user_id=user.id, expires_at=datetime.utcnow() + timedelta(days=1),
                active_workspace_id=personal.id,
            ))
            db.commit()
            user_id, workspace_id = user.id, personal.id

        with patch("app.main.SessionLocal", self.session_factory), \
             patch("app.api.auth.SessionLocal", self.session_factory), \
             patch("app.api.organizations.SessionLocal", self.session_factory), \
             patch("app.services.auth.SessionLocal", self.session_factory), \
             patch("app.api.auth.send_verification_email", side_effect=capture_verification), \
             patch.object(config, "DISABLE_APP_ROUTES", False), \
             TestClient(app) as client:
            client.cookies.set("kodo_session", serializer.dumps("link-session"))
            linked = client.post("/api/auth/email/link", json={
                "email": "existing@example.com", "password": "safe-password-123",
            })
            self.assertEqual(linked.status_code, 200, linked.text)
            self.assertTrue(linked.json()["verification_required"])
            verified = client.post("/api/auth/email/verify", json={"token": captured["token"]})
            self.assertEqual(verified.status_code, 200, verified.text)
            me = client.get("/api/me")
            self.assertEqual(me.status_code, 200, me.text)

        self.assertEqual(me.json()["id"], user_id)
        self.assertEqual(me.json()["workspace_id"], workspace_id)
        self.assertEqual(set(me.json()["auth_providers"]), {"github", "email_password"})
        with self.session_factory() as db:
            self.assertEqual(db.query(User).filter_by(email="existing@example.com").count(), 1)
            self.assertEqual(db.query(Workspace).filter_by(owner_user_id=user_id, kind="personal").count(), 1)

    def test_webhook_from_unlinked_installation_cannot_change_a_connected_repository(self):
        owner = User(name="Owner")
        with self.session_factory() as db:
            db.add(owner)
            db.flush()
            personal = ensure_personal_workspace(db, owner)
            db.add_all([
                Installation(id=222, account="owner", account_type="User", workspace_id=personal.id),
                Installation(id=333, account="other", account_type="User", workspace_id=None),
            ])
            db.add(Repository(
                id=123, installation_id=222, workspace_id=personal.id,
                full_name="owner/original", organization_id=None, connected=True,
            ))
            db.commit()

        payload = {
            "action": "added",
            "installation": {"id": 333, "account": {"login": "other", "type": "User"}},
            "repositories_added": [{"id": 123, "full_name": "other/renamed", "private": True}],
            "repositories_removed": [],
        }
        raw = json.dumps(payload).encode()
        secret = "webhook-test-secret"
        signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        with patch("app.main.SessionLocal", self.session_factory), \
             patch("app.api.webhooks.SessionLocal", self.session_factory), \
             patch.object(config, "GITHUB_WEBHOOK_SECRET", secret), \
             patch.object(config, "DISABLE_APP_ROUTES", False), \
             TestClient(app) as client:
            response = client.post("/github-webhook", content=raw, headers={
                "content-type": "application/json", "x-hub-signature-256": signature,
                "x-github-delivery": "test-unlinked-installation", "x-github-event": "installation_repositories",
            })
            self.assertEqual(response.status_code, 200, response.text)

        with self.session_factory() as db:
            repo = db.get(Repository, 123)
            self.assertEqual((repo.installation_id, repo.full_name, repo.connected), (222, "owner/original", True))

    def test_github_first_login_provisions_personal_workspace_without_organization(self):
        github_user = {"id": 12345, "login": "test-user", "name": "Test User", "avatar_url": ""}

        class TokenResponse:
            def raise_for_status(self):
                return None

            @staticmethod
            def json():
                return {"access_token": "github-test-token"}

        def github_request(method, path, token):
            if path == "/user":
                return github_user
            if path == "/user/emails":
                return []
            raise AssertionError(path)

        env = {"GITHUB_CLIENT_ID": "test-client", "GITHUB_CLIENT_SECRET": "test-secret"}
        with patch.dict(os.environ, env), \
             patch("app.main.SessionLocal", self.session_factory), \
             patch("app.api.auth.SessionLocal", self.session_factory), \
             patch("app.services.auth.SessionLocal", self.session_factory), \
             patch("app.api.auth.requests.post", return_value=TokenResponse()), \
             patch("app.api.auth.github_request", side_effect=github_request), \
             patch.object(config, "DISABLE_APP_ROUTES", False), \
             TestClient(app, follow_redirects=False) as client:
            started = client.get("/api/auth/github", follow_redirects=False)
            self.assertEqual(started.status_code, 302)
            state = client.cookies.get("kodo_oauth_state")
            callback = client.get(f"/auth/callback?code=test-code&state={state}", follow_redirects=False)
            self.assertEqual(callback.status_code, 302, callback.text)

        db = self.session_factory()
        try:
            user = db.query(User).filter_by(name="Test User").one()
            workspaces = db.query(Workspace).filter_by(kind="personal", owner_user_id=user.id).all()
            self.assertEqual(len(workspaces), 1)
            self.assertEqual(db.query(Organization).count(), 0)
        finally:
            db.close()

    def test_linking_github_with_a_verified_matching_email_preserves_existing_account(self):
        user = User(name="Existing email user", email="existing@example.com", email_verified_at=datetime.utcnow())
        with self.session_factory() as db:
            db.add(user)
            db.flush()
            personal = ensure_personal_workspace(db, user)
            db.add(AuthIdentity(
                user_id=user.id, provider="email_password", provider_user_id=user.email,
                password_hash="existing-hash",
            ))
            db.add(UserSession(
                id="github-link-session", user_id=user.id,
                expires_at=datetime.utcnow() + timedelta(days=1), active_workspace_id=personal.id,
            ))
            db.commit()
            user_id, workspace_id = user.id, personal.id

        class TokenResponse:
            def raise_for_status(self):
                return None

            @staticmethod
            def json():
                return {"access_token": "github-link-token"}

        def github_request(method, path, token):
            if path == "/user":
                return {"id": 9876, "login": "linked-github", "name": "Existing email user", "avatar_url": ""}
            if path == "/user/emails":
                return [{"email": "existing@example.com", "verified": True, "primary": True}]
            raise AssertionError(path)

        with patch.dict(os.environ, {"GITHUB_CLIENT_ID": "client", "GITHUB_CLIENT_SECRET": "secret"}), \
             patch("app.main.SessionLocal", self.session_factory), \
             patch("app.api.auth.SessionLocal", self.session_factory), \
             patch("app.api.organizations.SessionLocal", self.session_factory), \
             patch("app.services.auth.SessionLocal", self.session_factory), \
             patch("app.api.auth.requests.post", return_value=TokenResponse()), \
             patch("app.api.auth.github_request", side_effect=github_request), \
             patch("app.api.auth._encrypt_token", return_value="encrypted-token"), \
             patch("app.services.auth._decrypt_token", return_value="github-link-token"), \
             patch.object(config, "DISABLE_APP_ROUTES", False), \
             TestClient(app, follow_redirects=False) as client:
            client.cookies.set("kodo_session", serializer.dumps("github-link-session"))
            started = client.get("/api/auth/github?next=/app/settings", follow_redirects=False)
            self.assertEqual(started.status_code, 302)
            state = client.cookies.get("kodo_oauth_state")
            callback = client.get(
                f"/auth/callback?code=link-code&state={state}", follow_redirects=False,
            )
            self.assertEqual(callback.status_code, 302, callback.text)
            me = client.get("/api/me")
            self.assertEqual(me.status_code, 200, me.text)

        self.assertEqual(me.json()["id"], user_id)
        self.assertEqual(me.json()["workspace_id"], workspace_id)
        self.assertEqual(set(me.json()["auth_providers"]), {"github", "email_password"})
        with self.session_factory() as db:
            self.assertEqual(db.query(User).count(), 1)
            self.assertEqual(db.query(Workspace).filter_by(owner_user_id=user_id, kind="personal").count(), 1)


if __name__ == "__main__":
    unittest.main()
