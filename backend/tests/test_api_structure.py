import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app import config
from app.main import app


class ApiRouterTest(unittest.TestCase):
    def test_domain_routers_register_all_existing_api_routes(self):
        routes = {
            (method, route.path)
            for route in app.routes
            if getattr(route, "path", "").startswith("/api/")
            or getattr(route, "path", "") in {"/auth/callback", "/github-webhook", "/health"}
            for method in (route.methods or set())
            if method not in {"HEAD", "OPTIONS"}
        }

        self.assertEqual(len(routes), 51)
        self.assertTrue({
            ("POST", "/api/waitlist"),
            ("GET", "/api/auth/github"),
            ("GET", "/auth/callback"),
            ("GET", "/api/organization/members"),
            ("GET", "/api/repos"),
            ("POST", "/api/repos/{repo_id}/tasks"),
            ("POST", "/api/repos/{repo_id}/work-sessions/{work_session_id}/stage"),
            ("POST", "/api/repos/{repo_id}/work-sessions/{work_session_id}/commit"),
            ("POST", "/api/repos/{repo_id}/work-sessions/{work_session_id}/publish"),
            ("GET", "/api/repos/{repo_id}/book"),
            ("POST", "/api/repos/{repo_id}/chat"),
            ("POST", "/github-webhook"),
            ("GET", "/health"),
        }.issubset(routes))

    def test_application_starts_and_health_endpoint_works(self):
        database = MagicMock()
        database.scalars.return_value.all.return_value = []
        with patch("app.main.SessionLocal", return_value=database), \
             patch.object(config, "DISABLE_APP_ROUTES", False):
            with TestClient(app) as client:
                response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        database.commit.assert_called_once()
        database.close.assert_called_once()

    def test_route_gate_keeps_public_endpoints_and_protects_app_routes(self):
        client = TestClient(app)
        with patch.object(config, "DISABLE_APP_ROUTES", False):
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.get("/api/me").status_code, 401)

        with patch.object(config, "DISABLE_APP_ROUTES", True):
            self.assertEqual(client.get("/api/me").status_code, 404)
            response = client.get("/api/public-config")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["disable_app_routes"])


if __name__ == "__main__":
    unittest.main()
