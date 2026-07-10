"""Tests for main.py FastAPI routes using TestClient.

Covers auth routes, page routes, API endpoints for services, earnings,
config, users, fleet workers, and compose export.
"""

import asyncio
import json
import os
import socket
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest
from fastapi.testclient import TestClient

from app.main import app


# Replace the real lifespan with a no-op for tests
@asynccontextmanager
async def _noop_lifespan(a):
    yield


app.router.lifespan_context = _noop_lifespan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _owner_user():
    return {"uid": 1, "u": "admin", "r": "owner"}


def _writer_user():
    return {"uid": 2, "u": "writer", "r": "writer"}


def _viewer_user():
    return {"uid": 3, "u": "viewer", "r": "viewer"}


def _auth_owner():
    return patch("app.main.auth.get_current_user", return_value=_owner_user())


def _auth_writer():
    return patch("app.main.auth.get_current_user", return_value=_writer_user())


def _auth_viewer():
    return patch("app.main.auth.get_current_user", return_value=_viewer_user())


def _no_auth():
    return patch("app.main.auth.get_current_user", return_value=None)


@pytest.fixture
def client():
    """TestClient with no-op lifespan to avoid scheduler/DB issues."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


class TestSafeJson:
    def test_valid_json(self):
        from app.main import _safe_json

        assert _safe_json('{"a": 1}') == {"a": 1}

    def test_invalid_json_fallback(self):
        from app.main import _safe_json

        assert _safe_json("not json") == []

    def test_invalid_json_custom_fallback(self):
        from app.main import _safe_json

        assert _safe_json("bad", {}) == {}

    def test_none_input(self):
        from app.main import _safe_json

        assert _safe_json(None) == []


class TestResolveWorkerId:
    def test_explicit_worker_id(self):
        from app.main import _resolve_worker_id

        result = asyncio.run(_resolve_worker_id(42))
        assert result == 42

    def test_auto_resolve_single_worker(self):
        from app.main import _resolve_worker_id

        with patch(
            "app.main.database.list_workers", new_callable=AsyncMock, return_value=[{"id": 7, "status": "online"}]
        ):
            result = asyncio.run(_resolve_worker_id(None))
            assert result == 7

    def test_no_workers_raises_503(self):
        from app.main import _resolve_worker_id

        with (
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[]),
            pytest.raises(Exception, match="No workers online"),
        ):
            asyncio.run(_resolve_worker_id(None))

    def test_multiple_workers_raises_400(self):
        from app.main import _resolve_worker_id

        workers = [
            {"id": 1, "status": "online"},
            {"id": 2, "status": "online"},
        ]
        with (
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            pytest.raises(Exception, match="worker_id is required"),
        ):
            asyncio.run(_resolve_worker_id(None))


class TestGetAllWorkerContainers:
    def test_docker_containers(self):
        from app.main import _get_all_worker_containers

        workers = [
            {
                "id": 1,
                "name": "w1",
                "status": "online",
                "system_info": json.dumps({"docker_available": True}),
                "containers": json.dumps([{"slug": "honeygain", "name": "hg", "status": "running"}]),
                "apps": "[]",
            }
        ]
        with patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers):
            result = asyncio.run(_get_all_worker_containers())
        assert len(result) == 1
        assert result[0]["slug"] == "honeygain"
        assert result[0]["deployed_by"] == "w1"

    def test_android_apps(self):
        from app.main import _get_all_worker_containers

        workers = [
            {
                "id": 2,
                "name": "phone",
                "status": "online",
                "system_info": json.dumps({"device_type": "android"}),
                "containers": "[]",
                "apps": json.dumps([{"slug": "earnapp", "running": True}]),
            }
        ]
        with patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers):
            result = asyncio.run(_get_all_worker_containers())
        assert len(result) == 1
        assert result[0]["slug"] == "earnapp"
        assert result[0]["_is_android"] is True

    def test_offline_workers_skipped(self):
        from app.main import _get_all_worker_containers

        workers = [{"id": 1, "name": "w1", "status": "offline", "system_info": "{}", "containers": "[]", "apps": "[]"}]
        with patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers):
            result = asyncio.run(_get_all_worker_containers())
        assert result == []


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------


class TestLoginRoute:
    def test_login_page_redirects_to_onboarding_if_no_users(self, client):
        with (
            _no_auth(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
        ):
            resp = client.get("/login", follow_redirects=False)
            assert resp.status_code == 303
            assert "/onboarding" in resp.headers["location"]

    def test_login_page_redirects_to_home_if_logged_in(self, client):
        with (
            _auth_owner(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=True),
        ):
            resp = client.get("/login", follow_redirects=False)
            assert resp.status_code == 303
            assert resp.headers["location"] == "/"

    def test_login_page_renders(self, client):
        with (
            _no_auth(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=True),
        ):
            resp = client.get("/login")
            assert resp.status_code == 200

    def test_login_success(self, client):
        user = {"id": 1, "username": "admin", "password": "hashed", "role": "owner"}
        with (
            patch("app.main.database.get_user_by_username", new_callable=AsyncMock, return_value=user),
            patch("app.main.auth.verify_password", return_value=True),
            patch("app.main.auth.create_session_token", return_value="tok"),
            patch("app.main.auth.set_session_cookie", side_effect=lambda r, t: r),
        ):
            resp = client.post("/login", data={"username": "admin", "password": "pass"}, follow_redirects=False)
            assert resp.status_code == 303

    def test_login_bad_password(self, client):
        user = {"id": 1, "username": "admin", "password": "hashed", "role": "owner"}
        with (
            patch("app.main.database.get_user_by_username", new_callable=AsyncMock, return_value=user),
            patch("app.main.auth.verify_password", return_value=False),
        ):
            resp = client.post("/login", data={"username": "admin", "password": "wrong"})
            assert resp.status_code == 401

    def test_login_unknown_user(self, client):
        with patch("app.main.database.get_user_by_username", new_callable=AsyncMock, return_value=None):
            resp = client.post("/login", data={"username": "nope", "password": "x"})
            assert resp.status_code == 401


class TestRegisterRoute:
    def test_register_page_first_user(self, client):
        with (
            _no_auth(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
        ):
            resp = client.get("/register")
            assert resp.status_code == 200

    def test_register_page_non_owner_redirects(self, client):
        with (
            _auth_viewer(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=True),
        ):
            resp = client.get("/register", follow_redirects=False)
            assert resp.status_code == 303

    def test_register_first_user_success(self, client):
        with (
            _no_auth(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
            patch("app.main.database.get_user_by_username", new_callable=AsyncMock, return_value=None),
            patch("app.main.auth.hash_password", return_value="hashed"),
            patch("app.main.database.create_user", new_callable=AsyncMock, return_value=1),
            patch("app.main.database.delete_config_keys", new_callable=AsyncMock),
            patch("app.main.auth.create_session_token", return_value="tok"),
            patch("app.main.auth.set_session_cookie", side_effect=lambda r, t: r),
        ):
            resp = client.post(
                "/register",
                data={
                    "username": "admin",
                    "password": "password123",
                    "password_confirm": "password123",
                },
                follow_redirects=False,
            )
            assert resp.status_code == 303

    def test_register_first_user_requires_setup_token(self, client):
        # When a first-run setup token is active, registering without it is refused
        # (the proxy-independent gate against a public visitor seizing the owner).
        from app import setup_token

        setup_token.set_active("the-token")
        with (
            _no_auth(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
        ):
            resp = client.post(
                "/register",
                data={
                    "username": "admin",
                    "password": "password123",
                    "password_confirm": "password123",
                },
                follow_redirects=False,
            )
            assert resp.status_code == 403

    def test_register_first_user_with_setup_token_clears_it(self, client):
        from app import setup_token

        setup_token.set_active("the-token")
        with (
            _no_auth(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
            patch("app.main.database.get_user_by_username", new_callable=AsyncMock, return_value=None),
            patch("app.main.auth.hash_password", return_value="hashed"),
            patch("app.main.database.create_user", new_callable=AsyncMock, return_value=1),
            patch("app.main.database.delete_config_keys", new_callable=AsyncMock) as del_keys,
            patch("app.main.auth.create_session_token", return_value="tok"),
            patch("app.main.auth.set_session_cookie", side_effect=lambda r, t: r),
        ):
            resp = client.post(
                "/register",
                data={
                    "username": "admin",
                    "password": "password123",
                    "password_confirm": "password123",
                    "setup_token": "the-token",
                },
                follow_redirects=False,
            )
            assert resp.status_code == 303
            del_keys.assert_awaited_once_with(["_setup_token"])
            assert setup_token.active() is None

    def test_register_password_mismatch(self, client):
        with (
            _no_auth(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
        ):
            resp = client.post(
                "/register",
                data={
                    "username": "admin",
                    "password": "password123",
                    "password_confirm": "different",
                },
            )
            assert resp.status_code == 400

    def test_register_password_too_short(self, client):
        with (
            _no_auth(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
        ):
            resp = client.post(
                "/register",
                data={
                    "username": "admin",
                    "password": "short",
                    "password_confirm": "short",
                },
            )
            assert resp.status_code == 400

    def test_register_bad_username(self, client):
        with (
            _no_auth(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
        ):
            resp = client.post(
                "/register",
                data={
                    "username": "a",
                    "password": "password123",
                    "password_confirm": "password123",
                },
            )
            assert resp.status_code == 400

    def test_register_duplicate_username(self, client):
        with (
            _no_auth(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
            patch("app.main.database.get_user_by_username", new_callable=AsyncMock, return_value={"id": 1}),
        ):
            resp = client.post(
                "/register",
                data={
                    "username": "admin",
                    "password": "password123",
                    "password_confirm": "password123",
                },
            )
            assert resp.status_code == 400

    def test_register_non_first_user_non_owner_forbidden(self, client):
        with (
            _auth_viewer(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=True),
        ):
            resp = client.post(
                "/register",
                data={
                    "username": "new",
                    "password": "password123",
                    "password_confirm": "password123",
                },
            )
            assert resp.status_code == 403


class TestLogout:
    def test_logout_redirects(self, client):
        with patch("app.main.auth.clear_session_cookie", side_effect=lambda r: r):
            resp = client.get("/logout", follow_redirects=False)
            assert resp.status_code == 303


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


class TestPageRoutes:
    def test_dashboard_not_logged_in_no_users(self, client):
        with (
            _no_auth(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
        ):
            resp = client.get("/", follow_redirects=False)
            assert resp.status_code == 303
            assert "/onboarding" in resp.headers["location"]

    def test_dashboard_not_logged_in_has_users(self, client):
        with (
            _no_auth(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=True),
        ):
            resp = client.get("/", follow_redirects=False)
            assert resp.status_code == 303
            assert "/login" in resp.headers["location"]

    def test_dashboard_logged_in(self, client):
        with _auth_owner():
            resp = client.get("/")
            assert resp.status_code == 200

    def test_setup_page(self, client):
        with _auth_owner():
            resp = client.get("/setup")
            assert resp.status_code == 200

    def test_setup_page_no_auth(self, client):
        with _no_auth():
            resp = client.get("/setup", follow_redirects=False)
            assert resp.status_code == 303

    def test_catalog_page(self, client):
        with _auth_owner():
            resp = client.get("/catalog")
            assert resp.status_code == 200

    def test_catalog_no_auth(self, client):
        with _no_auth():
            resp = client.get("/catalog", follow_redirects=False)
            assert resp.status_code == 303

    def test_settings_page_owner(self, client):
        with _auth_owner():
            resp = client.get("/settings")
            assert resp.status_code == 200

    def test_settings_page_non_owner(self, client):
        with _auth_viewer():
            resp = client.get("/settings")
            assert resp.status_code == 403

    def test_settings_no_auth(self, client):
        with _no_auth():
            resp = client.get("/settings", follow_redirects=False)
            assert resp.status_code == 303

    def test_fleet_page(self, client):
        with _auth_owner():
            resp = client.get("/fleet")
            assert resp.status_code == 200

    def test_fleet_no_auth(self, client):
        with _no_auth():
            resp = client.get("/fleet", follow_redirects=False)
            assert resp.status_code == 303

    def test_onboarding_page_no_users(self, client):
        with (
            _no_auth(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
        ):
            resp = client.get("/onboarding")
            assert resp.status_code == 200

    def test_onboarding_redirects_when_users_exist(self, client):
        with (
            _no_auth(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=True),
        ):
            resp = client.get("/onboarding", follow_redirects=False)
            assert resp.status_code == 303
            assert "/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# API: Services
# ---------------------------------------------------------------------------


class TestApiServices:
    def test_api_mode(self, client):
        with _auth_owner():
            resp = client.get("/api/mode")
            assert resp.status_code == 200
            data = resp.json()
            assert data["mode"] == "ui"
            assert data["docker"] is False

    def test_api_mode_no_auth(self, client):
        with _no_auth():
            resp = client.get("/api/mode")
            assert resp.status_code == 401

    def test_api_list_services(self, client):
        with (
            _auth_owner(),
            patch("app.main.catalog.get_services", return_value=[{"slug": "hg", "name": "Honeygain"}]),
        ):
            resp = client.get("/api/services")
            assert resp.status_code == 200
            assert len(resp.json()) == 1

    def test_api_get_service(self, client):
        svc = {"slug": "hg", "name": "Honeygain", "docker": {"image": "test"}}
        with (
            _auth_owner(),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[]),
        ):
            resp = client.get("/api/services/hg")
            assert resp.status_code == 200
            assert resp.json()["slug"] == "hg"

    def test_api_get_service_has_collector_flag(self, client):
        # honeygain has a collector; a service without one reports False.
        hg = {"slug": "honeygain", "name": "Honeygain", "docker": {"image": "test"}}
        with (
            _auth_owner(),
            patch("app.main.catalog.get_service", return_value=hg),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[]),
        ):
            assert client.get("/api/services/honeygain").json()["has_collector"] is True
        nocol = {"slug": "nodle", "name": "Nodle", "docker": {"image": "test"}}
        with (
            _auth_owner(),
            patch("app.main.catalog.get_service", return_value=nocol),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[]),
        ):
            assert client.get("/api/services/nodle").json()["has_collector"] is False

    def test_api_get_service_not_found(self, client):
        with (
            _auth_owner(),
            patch("app.main.catalog.get_service", return_value=None),
        ):
            resp = client.get("/api/services/nope")
            assert resp.status_code == 404

    def test_api_status(self, client):
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[]),
        ):
            resp = client.get("/api/status")
            assert resp.status_code == 200
            assert resp.json() == []

    def test_api_services_available(self, client):
        svcs = [{"slug": "hg", "name": "HG", "status": "active", "docker": {"image": "test"}}]
        with (
            _auth_owner(),
            patch("app.main.catalog.get_services", return_value=svcs),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[]),
        ):
            resp = client.get("/api/services/available")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["deployed"] is False

    def test_api_services_available_skips_broken(self, client):
        svcs = [
            {"slug": "hg", "name": "HG", "status": "active", "docker": {"image": "test"}},
            {"slug": "dead", "name": "Dead", "status": "broken", "docker": {"image": "x"}},
        ]
        with (
            _auth_owner(),
            patch("app.main.catalog.get_services", return_value=svcs),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[]),
        ):
            resp = client.get("/api/services/available")
            assert len(resp.json()) == 1

    def test_api_services_deployed(self, client):
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_health_scores", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
        ):
            resp = client.get("/api/services/deployed")
            assert resp.status_code == 200
            assert resp.json() == []

    def test_api_services_deployed_with_external(self, client):
        deps = [{"slug": "grass", "status": "external"}]
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_health_scores", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=deps),
            patch("app.main.catalog.get_service", return_value={"name": "Grass", "category": "bandwidth"}),
        ):
            resp = client.get("/api/services/deployed")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["container_status"] == "external"

    def test_deployed_collector_needs_setup_when_creds_missing(self, client):
        # Repocket deployed + earning, but its collector email/password are unset
        # → needs_setup True, disconnected False.
        workers = [
            {
                "id": 1,
                "name": "w1",
                "status": "online",
                "system_info": json.dumps({"docker_available": True}),
                "containers": json.dumps([{"slug": "repocket", "name": "rp", "status": "running"}]),
                "apps": "[]",
            }
        ]
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_health_scores", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
            patch("app.main.catalog.get_service", return_value={"name": "Repocket", "category": "bandwidth"}),
        ):
            resp = client.get("/api/services/deployed")
            assert resp.status_code == 200
            row = next(r for r in resp.json() if r["slug"] == "repocket")
            assert row["collector_needs_setup"] is True
            assert row["collector_disconnected"] is False

    def test_deployed_collector_not_needs_setup_when_creds_present(self, client):
        workers = [
            {
                "id": 1,
                "name": "w1",
                "status": "online",
                "system_info": json.dumps({"docker_available": True}),
                "containers": json.dumps([{"slug": "repocket", "name": "rp", "status": "running"}]),
                "apps": "[]",
            }
        ]
        cfg = {"repocket_email": "me@example.com", "repocket_password": "secret"}
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_health_scores", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_config", new_callable=AsyncMock, return_value=cfg),
            patch("app.main.catalog.get_service", return_value={"name": "Repocket", "category": "bandwidth"}),
        ):
            resp = client.get("/api/services/deployed")
            row = next(r for r in resp.json() if r["slug"] == "repocket")
            assert row["collector_needs_setup"] is False

    def test_deployed_row_flags_unstable_on_repeated_crashes(self, client):
        """A service with >=3 crashes in the health window is flagged unstable so the
        dashboard can surface a crash-looping earner at a glance."""
        workers = [
            {
                "id": 1,
                "name": "w1",
                "status": "online",
                "system_info": json.dumps({"docker_available": True}),
                "containers": json.dumps([{"slug": "repocket", "name": "rp", "status": "running"}]),
                "apps": "[]",
            }
        ]
        scores = [{"slug": "repocket", "score": 30, "uptime_pct": 40, "restarts": 5, "crashes": 4}]
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_health_scores", new_callable=AsyncMock, return_value=scores),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
            patch("app.main.catalog.get_service", return_value={"name": "Repocket", "category": "bandwidth"}),
        ):
            resp = client.get("/api/services/deployed")
            assert resp.status_code == 200
            row = next(r for r in resp.json() if r["slug"] == "repocket")
            assert row["unstable"] is True
            assert row["crashes_7d"] == 4

    def test_deployed_row_not_unstable_below_threshold(self, client):
        """Fewer than 3 crashes is not flagged unstable (crashes_7d is still surfaced)."""
        workers = [
            {
                "id": 1,
                "name": "w1",
                "status": "online",
                "system_info": json.dumps({"docker_available": True}),
                "containers": json.dumps([{"slug": "repocket", "name": "rp", "status": "running"}]),
                "apps": "[]",
            }
        ]
        scores = [{"slug": "repocket", "score": 85, "uptime_pct": 98, "restarts": 1, "crashes": 2}]
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_health_scores", new_callable=AsyncMock, return_value=scores),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
            patch("app.main.catalog.get_service", return_value={"name": "Repocket", "category": "bandwidth"}),
        ):
            resp = client.get("/api/services/deployed")
            row = next(r for r in resp.json() if r["slug"] == "repocket")
            assert row["unstable"] is False
            assert row["crashes_7d"] == 2

    def test_deployed_disconnected_takes_precedence_over_needs_setup(self, client):
        # When the collector has actually errored, show the error state, not "needs setup".
        workers = [
            {
                "id": 1,
                "name": "w1",
                "status": "online",
                "system_info": json.dumps({"docker_available": True}),
                "containers": json.dumps([{"slug": "repocket", "name": "rp", "status": "running"}]),
                "apps": "[]",
            }
        ]
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_health_scores", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
            patch("app.main._collector_alerts", [{"platform": "repocket", "error": "auth failed"}]),
            patch("app.main.catalog.get_service", return_value={"name": "Repocket", "category": "bandwidth"}),
        ):
            resp = client.get("/api/services/deployed")
            row = next(r for r in resp.json() if r["slug"] == "repocket")
            assert row["collector_disconnected"] is True
            assert row["collector_needs_setup"] is False

    def test_collector_needs_setup_helper(self):
        # Service with no collector → never needs setup.
        from app.main import _collector_needs_setup

        assert _collector_needs_setup("not-a-service", {}) is False
        # Optional-only collector (storj: ?api_url) → not "needs setup" when blank.
        assert _collector_needs_setup("storj", {}) is False
        # Required creds absent → needs setup; present → not.
        assert _collector_needs_setup("repocket", {}) is True
        assert _collector_needs_setup("repocket", {"repocket_email": "a", "repocket_password": "b"}) is False


# ---------------------------------------------------------------------------
# API: Earnings
# ---------------------------------------------------------------------------


class TestApiEarnings:
    def test_api_earnings(self, client):
        with (
            _auth_owner(),
            patch(
                "app.main.database.get_earnings_summary",
                new_callable=AsyncMock,
                return_value=[{"platform": "hg", "balance": 5.0, "currency": "USD"}],
            ),
        ):
            resp = client.get("/api/earnings")
            assert resp.status_code == 200
            assert len(resp.json()) == 1

    def test_api_earnings_summary(self, client):
        summary = {"total": 10.0, "today": 1.0, "month": 5.0, "today_change": 0.5}
        with (
            _auth_owner(),
            patch("app.main.database.get_earnings_dashboard_summary", new_callable=AsyncMock, return_value=summary),
            patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
            patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[]),
        ):
            resp = client.get("/api/earnings/summary")
            assert resp.status_code == 200
            data = resp.json()
            assert "total" in data
            assert "active_services" in data

    def test_api_earnings_daily(self, client):
        with (
            _auth_owner(),
            patch(
                "app.main.database.get_daily_earnings",
                new_callable=AsyncMock,
                return_value=[{"date": "2026-01-01", "amount": 1.0}],
            ),
        ):
            resp = client.get("/api/earnings/daily?days=7")
            assert resp.status_code == 200

    def test_api_earnings_daily_invalid_days(self, client):
        with _auth_owner():
            resp = client.get("/api/earnings/daily?days=0")
            assert resp.status_code == 400

    def test_api_earnings_breakdown(self, client):
        rows = [{"platform": "hg", "balance": 5.0, "prev_balance": 4.0, "currency": "USD", "date": "2026-01-01"}]
        svc = {"name": "Honeygain", "cashout": {"min_amount": 20, "method": "paypal"}}
        with (
            _auth_owner(),
            patch("app.main.database.get_earnings_per_service", new_callable=AsyncMock, return_value=rows),
            patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
            patch("app.main.catalog.get_service", return_value=svc),
        ):
            resp = client.get("/api/earnings/breakdown")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["delta"] == 1.0

    def test_api_earnings_history(self, client):
        with (
            _auth_owner(),
            patch("app.main.database.get_earnings_history", new_callable=AsyncMock, return_value=[]),
        ):
            resp = client.get("/api/earnings/history?period=week")
            assert resp.status_code == 200

    def test_api_earnings_history_invalid_period(self, client):
        with _auth_owner():
            resp = client.get("/api/earnings/history?period=invalid")
            assert resp.status_code == 400

    def test_api_health_scores(self, client):
        scores = [{"slug": "hg", "score": 95, "uptime_pct": 99, "restarts": 0}]
        svc = {"name": "Honeygain"}
        with (
            _auth_owner(),
            patch("app.main.database.get_health_scores", new_callable=AsyncMock, return_value=scores),
            patch("app.main.catalog.get_service", return_value=svc),
        ):
            resp = client.get("/api/health/scores?days=7")
            assert resp.status_code == 200

    def test_api_health_scores_invalid_days(self, client):
        with _auth_owner():
            resp = client.get("/api/health/scores?days=0")
            assert resp.status_code == 400

    def test_api_collect_trigger(self, client):
        with _auth_writer():
            resp = client.post("/api/collect")
            assert resp.status_code == 200
            assert resp.json()["status"] == "collection_started"

    def test_api_collector_alerts(self, client):
        with _auth_owner():
            resp = client.get("/api/collector-alerts")
            assert resp.status_code == 200

    def test_api_exchange_rates(self, client):
        rates = {"fiat": {"USD": 1.0}, "crypto_usd": {}, "last_updated": None}
        with (
            _auth_owner(),
            patch("app.main.exchange_rates.get_all", return_value=rates),
        ):
            resp = client.get("/api/exchange-rates")
            assert resp.status_code == 200
            assert "fiat" in resp.json()


# ---------------------------------------------------------------------------
# API: Compose
# ---------------------------------------------------------------------------


class TestApiCompose:
    def test_api_compose_single(self, client):
        svc = {"slug": "hg", "name": "Honeygain", "docker": {"image": "test"}}
        with (
            _auth_owner(),
            patch("app.main.catalog.get_service", return_value=svc),
            patch(
                "app.main.compose_generator.generate_compose_single", return_value="services:\n  hg:\n    image: test"
            ),
        ):
            resp = client.get("/api/compose/hg")
            assert resp.status_code == 200
            assert "services" in resp.text

    def test_api_compose_single_not_found(self, client):
        with (
            _auth_owner(),
            patch("app.main.catalog.get_service", return_value=None),
        ):
            resp = client.get("/api/compose/nope")
            assert resp.status_code == 404

    def test_api_compose_multi(self, client):
        with (
            _auth_owner(),
            patch("app.main.compose_generator.generate_compose_multi", return_value="services:\n  multi: {}"),
        ):
            resp = client.post("/api/compose", json={"slugs": ["a", "b"]})
            assert resp.status_code == 200

    def test_api_compose_all(self, client):
        with (
            _auth_owner(),
            patch("app.main.compose_generator.generate_compose_all", return_value="services:\n  all: {}"),
        ):
            resp = client.get("/api/compose")
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# API: Config
# ---------------------------------------------------------------------------


class TestApiConfig:
    def test_api_get_config(self, client):
        masked = {"honeygain_email": "a@b.com", "_secrets": {"honeygain_password": True}}
        with (
            _auth_owner(),
            patch("app.main.database.get_config_masked", new_callable=AsyncMock, return_value=masked),
        ):
            resp = client.get("/api/config")
            assert resp.status_code == 200
            assert resp.json() == masked

    def test_api_get_config_masks_secrets(self, client):
        """Secret keys must be absent at top level and only present (as bool) in _secrets."""
        masked = {
            "honeygain_email": "a@b.com",
            "_secrets": {"honeygain_password": True, "grass_access_token": False},
        }
        with (
            _auth_owner(),
            patch("app.main.database.get_config_masked", new_callable=AsyncMock, return_value=masked),
        ):
            resp = client.get("/api/config")
            assert resp.status_code == 200
            data = resp.json()
            # Non-secret value present at top level
            assert data["honeygain_email"] == "a@b.com"
            # Secret values absent from top level
            assert "honeygain_password" not in data
            assert "grass_access_token" not in data
            # Presence reported as bool under _secrets
            assert data["_secrets"]["honeygain_password"] is True
            assert data["_secrets"]["grass_access_token"] is False

    def test_api_set_config(self, client):
        with (
            _auth_owner(),
            patch("app.main.database.set_config_bulk", new_callable=AsyncMock),
            patch("app.main.catalog.get_service", return_value=None),
        ):
            resp = client.post("/api/config", json={"data": {"key": "value"}})
            assert resp.status_code == 200
            assert resp.json()["status"] == "saved"

    def test_api_set_config_creates_external_deployment(self, client):
        svc = {"slug": "grass", "docker": {}}
        with (
            _auth_owner(),
            patch("app.main.database.set_config_bulk", new_callable=AsyncMock),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.database.get_deployment", new_callable=AsyncMock, return_value=None),
            patch("app.main.database.save_deployment", new_callable=AsyncMock) as mock_save,
        ):
            resp = client.post("/api/config", json={"data": {"grass_access_token": "tok"}})
            assert resp.status_code == 200
            mock_save.assert_called_once()

    def test_api_clear_service_config(self, client):
        svc = {"slug": "grass", "docker": {}}
        with (
            _auth_owner(),
            patch("app.main.database.delete_config_keys", new_callable=AsyncMock),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.database.remove_deployment", new_callable=AsyncMock),
        ):
            resp = client.delete("/api/config/grass")
            assert resp.status_code == 200

    def test_api_clear_config_unknown_service(self, client):
        with _auth_owner():
            resp = client.delete("/api/config/nonexistent")
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API: Users
# ---------------------------------------------------------------------------


class TestApiUsers:
    def test_api_list_users(self, client):
        users = [{"id": 1, "username": "admin", "role": "owner"}]
        with (
            _auth_owner(),
            patch("app.main.database.list_users", new_callable=AsyncMock, return_value=users),
        ):
            resp = client.get("/api/users")
            assert resp.status_code == 200
            assert len(resp.json()) == 1

    def test_api_update_user_role(self, client):
        user = {"id": 2, "username": "bob", "role": "viewer"}
        with (
            _auth_owner(),
            patch("app.main.database.get_user_by_id", new_callable=AsyncMock, return_value=user),
            patch("app.main.database.update_user_role", new_callable=AsyncMock),
        ):
            resp = client.patch("/api/users/2", json={"role": "writer"})
            assert resp.status_code == 200

    def test_api_update_user_invalid_role(self, client):
        with _auth_owner():
            resp = client.patch("/api/users/2", json={"role": "superadmin"})
            assert resp.status_code == 400

    def test_api_update_user_not_found(self, client):
        with (
            _auth_owner(),
            patch("app.main.database.get_user_by_id", new_callable=AsyncMock, return_value=None),
        ):
            resp = client.patch("/api/users/99", json={"role": "writer"})
            assert resp.status_code == 404

    def test_api_update_user_demote_self(self, client):
        user = {"id": 1, "username": "admin", "role": "owner"}
        with (
            _auth_owner(),
            patch("app.main.database.get_user_by_id", new_callable=AsyncMock, return_value=user),
        ):
            resp = client.patch("/api/users/1", json={"role": "viewer"})
            assert resp.status_code == 400

    def test_api_update_user_demote_last_owner(self, client):
        user = {"id": 2, "username": "admin2", "role": "owner"}
        all_users = [{"id": 2, "username": "admin2", "role": "owner"}]
        with (
            _auth_owner(),
            patch("app.main.database.get_user_by_id", new_callable=AsyncMock, return_value=user),
            patch("app.main.database.list_users", new_callable=AsyncMock, return_value=all_users),
        ):
            resp = client.patch("/api/users/2", json={"role": "viewer"})
            assert resp.status_code == 400

    def test_api_delete_user(self, client):
        user = {"id": 2, "username": "bob", "role": "viewer"}
        with (
            _auth_owner(),
            patch("app.main.database.get_user_by_id", new_callable=AsyncMock, return_value=user),
            patch("app.main.database.delete_user", new_callable=AsyncMock),
        ):
            resp = client.delete("/api/users/2")
            assert resp.status_code == 200

    def test_api_delete_user_self(self, client):
        with _auth_owner():
            resp = client.delete("/api/users/1")
            assert resp.status_code == 400

    def test_api_delete_user_not_found(self, client):
        with (
            _auth_owner(),
            patch("app.main.database.get_user_by_id", new_callable=AsyncMock, return_value=None),
        ):
            resp = client.delete("/api/users/99")
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API: Change own password (H4)
# ---------------------------------------------------------------------------


class TestChangeOwnPassword:
    def test_change_own_password_ok(self, client):
        record = {
            "id": 1,
            "username": "admin",
            "password": "x-mock-hash",
            "role": "owner",
            "password_changed_at": 123.0,
        }
        with (
            _auth_owner(),
            patch("app.main.database.get_user_by_id", new_callable=AsyncMock, return_value=record),
            patch("app.main.auth.verify_password", return_value=True),
            patch("app.main.auth.hash_password", return_value="hashed-new"),
            patch("app.main.database.update_user_password", new_callable=AsyncMock) as mock_upd,
            patch("app.main.auth.set_user_pwd_epoch") as mock_epoch,
            patch("app.main.auth.create_session_token", return_value="tok"),
            patch("app.main.auth.set_session_cookie", side_effect=lambda r, t: r),
        ):
            resp = client.post(
                "/api/users/me/password",
                json={"current_password": "oldpassword1", "new_password": "newpassword123"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "password_changed"
            mock_upd.assert_called_once_with(1, "hashed-new")
            mock_epoch.assert_called_once_with(1, 123.0)

    def test_change_own_password_remints_cookie(self, client):
        # The caller must NOT be logged out by their own password change: the
        # route re-mints the session cookie with a fresh token (iat > new epoch).
        record = {
            "id": 1,
            "username": "admin",
            "password": "x-mock-hash",
            "role": "owner",
            "password_changed_at": 123.0,
        }
        with (
            _auth_owner(),
            patch("app.main.database.get_user_by_id", new_callable=AsyncMock, return_value=record),
            patch("app.main.auth.verify_password", return_value=True),
            patch("app.main.auth.hash_password", return_value="hashed-new"),
            patch("app.main.database.update_user_password", new_callable=AsyncMock),
            patch("app.main.auth.set_user_pwd_epoch"),
            patch("app.main.auth.create_session_token", return_value="fresh-tok") as mock_tok,
            patch("app.main.auth.set_session_cookie", side_effect=lambda r, t: r) as mock_cookie,
        ):
            resp = client.post(
                "/api/users/me/password",
                json={"current_password": "oldpassword1", "new_password": "newpassword123"},
            )
            assert resp.status_code == 200
            mock_tok.assert_called_once_with(1, "admin", "owner")
            # set_session_cookie must be called with the freshly-minted token.
            assert mock_cookie.call_args[0][1] == "fresh-tok"

    def test_change_own_password_user_vanished(self, client):
        # Authenticated session but the user row is gone → 404, no crash.
        with (
            _auth_owner(),
            patch("app.main.database.get_user_by_id", new_callable=AsyncMock, return_value=None),
        ):
            resp = client.post(
                "/api/users/me/password",
                json={"current_password": "oldpassword1", "new_password": "newpassword123"},
            )
            assert resp.status_code == 404

    def test_change_own_password_wrong_current(self, client):
        record = {"id": 1, "username": "admin", "password": "x-mock-hash", "role": "owner"}
        with (
            _auth_owner(),
            patch("app.main.database.get_user_by_id", new_callable=AsyncMock, return_value=record),
            patch("app.main.auth.verify_password", return_value=False),
        ):
            resp = client.post(
                "/api/users/me/password",
                json={"current_password": "wrong", "new_password": "newpassword123"},
            )
            assert resp.status_code == 403

    def test_change_own_password_too_short(self, client):
        record = {"id": 1, "username": "admin", "password": "x-mock-hash", "role": "owner"}
        with (
            _auth_owner(),
            patch("app.main.database.get_user_by_id", new_callable=AsyncMock, return_value=record),
            patch("app.main.auth.verify_password", return_value=True),
        ):
            resp = client.post(
                "/api/users/me/password",
                json={"current_password": "oldpassword1", "new_password": "short"},
            )
            assert resp.status_code == 400

    def test_change_own_password_same_as_old(self, client):
        record = {"id": 1, "username": "admin", "password": "x-mock-hash", "role": "owner"}
        with (
            _auth_owner(),
            patch("app.main.database.get_user_by_id", new_callable=AsyncMock, return_value=record),
            patch("app.main.auth.verify_password", return_value=True),
        ):
            resp = client.post(
                "/api/users/me/password",
                json={"current_password": "samepassword1", "new_password": "samepassword1"},
            )
            assert resp.status_code == 400

    def test_change_own_password_uid0_rejected(self, client):
        """API-key sessions (uid=0) cannot change a password."""
        with patch("app.main.auth.get_current_user", return_value={"uid": 0, "u": "api", "r": "owner"}):
            resp = client.post(
                "/api/users/me/password",
                json={"current_password": "x", "new_password": "newpassword123"},
            )
            assert resp.status_code == 400

    def test_change_own_password_unauthenticated(self, client):
        with _no_auth():
            resp = client.post(
                "/api/users/me/password",
                json={"current_password": "x", "new_password": "newpassword123"},
            )
            assert resp.status_code == 401


# ---------------------------------------------------------------------------
# API: Admin reset password (H4)
# ---------------------------------------------------------------------------


class TestAdminResetPassword:
    def test_admin_reset_password_owner_ok(self, client):
        target = {"id": 2, "username": "bob", "password": "hashed", "role": "viewer", "password_changed_at": 456.0}
        with (
            _auth_owner(),
            patch("app.main.database.get_user_by_id", new_callable=AsyncMock, return_value=target),
            patch("app.main.auth.hash_password", return_value="hashed-new"),
            patch("app.main.database.update_user_password", new_callable=AsyncMock) as mock_upd,
            patch("app.main.auth.set_user_pwd_epoch") as mock_epoch,
        ):
            resp = client.post("/api/users/2/password", json={"new_password": "newpassword123"})
            assert resp.status_code == 200
            assert resp.json()["status"] == "password_set"
            mock_upd.assert_called_once_with(2, "hashed-new")
            mock_epoch.assert_called_once_with(2, 456.0)

    def test_admin_reset_password_non_owner_403(self, client):
        with _auth_writer():
            resp = client.post("/api/users/2/password", json={"new_password": "newpassword123"})
            assert resp.status_code == 403

    def test_admin_reset_password_user_not_found_404(self, client):
        with (
            _auth_owner(),
            patch("app.main.database.get_user_by_id", new_callable=AsyncMock, return_value=None),
        ):
            resp = client.post("/api/users/99/password", json={"new_password": "newpassword123"})
            assert resp.status_code == 404

    def test_admin_reset_password_too_short(self, client):
        target = {"id": 2, "username": "bob", "password": "hashed", "role": "viewer"}
        with (
            _auth_owner(),
            patch("app.main.database.get_user_by_id", new_callable=AsyncMock, return_value=target),
        ):
            resp = client.post("/api/users/2/password", json={"new_password": "short"})
            assert resp.status_code == 400


# ---------------------------------------------------------------------------
# API: Preferences
# ---------------------------------------------------------------------------


class TestApiPreferences:
    def test_api_get_preferences(self, client):
        prefs = {"setup_mode": "fresh", "selected_categories": "[]", "timezone": "UTC", "setup_completed": False}
        with (
            _auth_owner(),
            patch("app.main.database.get_user_preferences", new_callable=AsyncMock, return_value=prefs),
        ):
            resp = client.get("/api/preferences")
            assert resp.status_code == 200
            assert resp.json()["setup_mode"] == "fresh"

    def test_api_get_preferences_default(self, client):
        with (
            _auth_owner(),
            patch("app.main.database.get_user_preferences", new_callable=AsyncMock, return_value=None),
        ):
            resp = client.get("/api/preferences")
            assert resp.status_code == 200
            assert resp.json()["setup_mode"] == "fresh"

    def test_api_set_preferences(self, client):
        with (
            _auth_owner(),
            patch("app.main.database.get_user_preferences", new_callable=AsyncMock, return_value=None),
            patch("app.main.database.save_user_preferences", new_callable=AsyncMock),
        ):
            resp = client.post("/api/preferences", json={"setup_mode": "monitoring"})
            assert resp.status_code == 200

    def test_api_set_preferences_invalid_mode(self, client):
        with _auth_owner():
            resp = client.post("/api/preferences", json={"setup_mode": "invalid"})
            assert resp.status_code == 400


# ---------------------------------------------------------------------------
# API: Env Info
# ---------------------------------------------------------------------------


class TestApiEnvInfo:
    def test_api_env_info(self, client):
        with _auth_owner():
            resp = client.get("/api/env-info")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            keys = {e["key"] for e in data}
            assert "CASHPILOT_API_KEY" in keys

    def test_api_env_info_non_owner(self, client):
        with _auth_viewer():
            resp = client.get("/api/env-info")
            assert resp.status_code == 403

    def test_api_env_info_no_secret_value(self, client):
        """Secret rows must drop 'value' and expose 'is_set' instead."""
        with (
            _auth_owner(),
            patch.dict(os.environ, {"CASHPILOT_API_KEY": "test-placeholder-value"}, clear=False),
        ):
            resp = client.get("/api/env-info")
            assert resp.status_code == 200
            rows = {e["key"]: e for e in resp.json()}
            fleet = rows["CASHPILOT_API_KEY"]
            assert fleet["secret"] is True
            assert "value" not in fleet
            assert fleet["is_set"] is True
            # Non-secret rows keep their real value
            prefix = rows["CASHPILOT_HOSTNAME_PREFIX"]
            assert "value" in prefix
            assert "is_set" not in prefix

    def test_env_info_secret_key_never_leaks(self, client):
        """CASHPILOT_SECRET_KEY must never return a value; is_set + read_only true."""
        sentinel = "test-placeholder-value"
        with (
            _auth_owner(),
            patch.dict(os.environ, {"CASHPILOT_SECRET_KEY": sentinel}, clear=False),
        ):
            resp = client.get("/api/env-info")
            assert resp.status_code == 200
            rows = {e["key"]: e for e in resp.json()}
            sk = rows["CASHPILOT_SECRET_KEY"]
            assert "value" not in sk
            assert sk["is_set"] is True
            assert sk["read_only"] is True
            # The plaintext must not appear anywhere in the response body
            assert sentinel not in resp.text


# ---------------------------------------------------------------------------
# API: Fleet / Workers
# ---------------------------------------------------------------------------


class TestApiFleet:
    def test_api_worker_heartbeat_enrollment_issues_key(self, client):
        # A brand-new worker authenticates with the shared key and is issued its own.
        with (
            patch("app.main.FLEET_API_KEY", "test-fleet-key"),
            patch("app.main.database.get_worker_key_hash", new_callable=AsyncMock, return_value=None),
            patch("app.main.database.set_worker_key_hash", new_callable=AsyncMock) as set_kh,
            patch("app.main.database.upsert_worker", new_callable=AsyncMock, return_value=1),
        ):
            resp = client.post(
                "/api/workers/heartbeat",
                json={"name": "worker-1", "client_id": "c1"},
                headers={"Authorization": "Bearer test-fleet-key"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["worker_id"] == 1
            assert body.get("worker_key")  # a per-worker key was issued
            set_kh.assert_awaited_once()  # its hash was persisted

    def test_api_worker_heartbeat_unenrolled_bad_key(self, client):
        with (
            patch("app.main.FLEET_API_KEY", "test-fleet-key"),
            patch("app.main.database.get_worker_key_hash", new_callable=AsyncMock, return_value=None),
        ):
            resp = client.post(
                "/api/workers/heartbeat",
                json={"name": "worker-1"},
                headers={"Authorization": "Bearer wrong-key"},
            )
            assert resp.status_code == 401

    def test_api_worker_heartbeat_no_fleet_key(self, client):
        with patch("app.main.FLEET_API_KEY", ""):
            resp = client.post(
                "/api/workers/heartbeat",
                json={"name": "worker-1"},
            )
            assert resp.status_code == 503

    def test_api_worker_heartbeat_enrolled_rejects_shared_key(self, client):
        # The cutover: an enrolled worker must use its own key; the shared key is
        # rejected, and its own key is accepted (no new key re-issued).
        from app import database as db_mod

        own_key = "the-worker-key"
        with (
            patch("app.main.FLEET_API_KEY", "test-fleet-key"),
            patch(
                "app.main.database.get_worker_key_hash",
                new_callable=AsyncMock,
                return_value=db_mod.hash_worker_key(own_key),
            ),
            patch("app.main.database.upsert_worker", new_callable=AsyncMock, return_value=1),
        ):
            shared = client.post(
                "/api/workers/heartbeat",
                json={"name": "w", "client_id": "c1"},
                headers={"Authorization": "Bearer test-fleet-key"},
            )
            assert shared.status_code == 401  # shared key no longer works once enrolled

            own = client.post(
                "/api/workers/heartbeat",
                json={"name": "w", "client_id": "c1"},
                headers={"Authorization": f"Bearer {own_key}"},
            )
            assert own.status_code == 200
            assert "worker_key" not in own.json()

    def test_api_list_workers(self, client):
        workers = [{"id": 1, "name": "w1", "status": "online", "containers": "[]", "apps": "[]", "system_info": "{}"}]
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
        ):
            resp = client.get("/api/workers")
            assert resp.status_code == 200

    def test_api_get_worker(self, client):
        worker = {"id": 1, "name": "w1", "status": "online", "containers": "[]", "apps": "[]", "system_info": "{}"}
        with (
            _auth_owner(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
        ):
            resp = client.get("/api/workers/1")
            assert resp.status_code == 200

    def test_api_get_worker_not_found(self, client):
        with (
            _auth_owner(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=None),
        ):
            resp = client.get("/api/workers/99")
            assert resp.status_code == 404

    def test_api_delete_worker(self, client):
        worker = {"id": 1, "name": "w1", "status": "online"}
        with (
            _auth_owner(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.delete_worker", new_callable=AsyncMock),
        ):
            resp = client.delete("/api/workers/1")
            assert resp.status_code == 200

    def test_api_delete_worker_not_found(self, client):
        with (
            _auth_owner(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=None),
        ):
            resp = client.delete("/api/workers/99")
            assert resp.status_code == 404

    def test_api_fleet_summary(self, client):
        workers = [
            {"id": 1, "name": "w1", "status": "online", "containers": "[]", "apps": "[]", "system_info": "{}"},
            {"id": 2, "name": "w2", "status": "offline", "containers": "[]", "apps": "[]", "system_info": "{}"},
        ]
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
        ):
            resp = client.get("/api/fleet/summary")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_workers"] == 2
            assert data["online_workers"] == 1

    def test_fleet_api_key_status_only(self, client):
        """GET returns presence only — never the key value."""
        with (
            _auth_owner(),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.get("/api/fleet/api-key")
            assert resp.status_code == 200
            data = resp.json()
            assert data["is_set"] is True
            assert "api_key" not in data
            assert "source" in data

    def test_api_fleet_api_key_non_owner(self, client):
        with _auth_viewer():
            resp = client.get("/api/fleet/api-key")
            assert resp.status_code == 403

    def test_fleet_api_key_reveal_owner(self, client):
        """POST reveal returns the actual key for an owner."""
        with (
            _auth_owner(),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post("/api/fleet/api-key/reveal")
            assert resp.status_code == 200
            assert resp.json()["api_key"] == "test-key"

    def test_fleet_reveal_non_owner_403(self, client):
        with _auth_viewer():
            resp = client.post("/api/fleet/api-key/reveal")
            assert resp.status_code == 403


# ---------------------------------------------------------------------------
# API: Worker URL validation
# ---------------------------------------------------------------------------


class TestValidateWorkerUrl:
    def test_valid_url(self):
        from app.main import _validate_worker_url

        assert _validate_worker_url("http://192.168.1.10:8081") == "http://192.168.1.10:8081"

    def test_trailing_slash_stripped(self):
        from app.main import _validate_worker_url

        assert _validate_worker_url("http://host:8081/") == "http://host:8081"

    def test_invalid_scheme(self):
        from app.main import _validate_worker_url

        with pytest.raises(Exception, match="Invalid worker URL scheme"):
            _validate_worker_url("ftp://host:21")

    def test_no_host(self):
        from app.main import _validate_worker_url

        with pytest.raises(Exception, match="no host"):
            _validate_worker_url("http://")

    def test_loopback_blocked(self):
        from app.main import _validate_worker_url

        with pytest.raises(Exception, match="loopback"):
            _validate_worker_url("http://127.0.0.1:8081")

    def test_localhost_blocked(self):
        from app.main import _validate_worker_url

        with pytest.raises(Exception, match="localhost"):
            _validate_worker_url("http://localhost:8081")

    def test_tailscale_dns_allowed(self):
        from app.main import _validate_worker_url

        # Exact-match (not substring) so CodeQL's url-substring-sanitization rule
        # isn't tripped by a test assertion.
        result = _validate_worker_url("http://worker.mango.ts.net:8081")
        assert result == "http://worker.mango.ts.net:8081"

    def test_tailscale_cgnat_ip_allowed(self):
        # 100.64.0.0/10 is neither private nor public in Python's ipaddress;
        # permissive default must still allow Tailscale literal IPs.
        from app.main import _validate_worker_url

        assert _validate_worker_url("http://100.100.100.100:8081") == "http://100.100.100.100:8081"

    def test_rfc1918_lan_allowed(self):
        from app.main import _validate_worker_url

        assert _validate_worker_url("http://192.168.10.50:8081") == "http://192.168.10.50:8081"

    def test_metadata_ipv4_blocked(self):
        from app.main import _validate_worker_url

        with pytest.raises(Exception, match="metadata"):
            _validate_worker_url("http://169.254.169.254/latest/meta-data/")

    def test_metadata_ipv6_blocked(self):
        from app.main import _validate_worker_url

        with pytest.raises(Exception, match="metadata"):
            _validate_worker_url("http://[fd00:ec2::254]:80/")

    def test_ipv6_loopback_blocked(self):
        from app.main import _validate_worker_url

        with pytest.raises(Exception, match="loopback"):
            _validate_worker_url("http://[::1]:8081")

    def test_ipv4_mapped_loopback_blocked(self):
        from app.main import _validate_worker_url

        with pytest.raises(Exception, match="loopback"):
            _validate_worker_url("http://[::ffff:127.0.0.1]:8081")

    def test_dns_rebind_to_metadata_blocked(self):
        # A hostname that resolves to the metadata IP must be rejected even in
        # permissive mode (DNS-rebinding guard).
        from app.main import _validate_worker_url

        with (
            patch(
                "app.main.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("169.254.169.254", 80))],
            ),
            pytest.raises(Exception, match="metadata"),
        ):
            _validate_worker_url("http://evil.example.com")

    def test_strict_mode_allows_listed_cidr(self):
        import app.main as main

        orig = (main._WORKER_URL_POLICY, main._WORKER_ALLOWED_CIDRS)
        try:
            main._WORKER_URL_POLICY = "strict"
            main._WORKER_ALLOWED_CIDRS = [main.ipaddress.ip_network("192.168.10.0/24")]
            assert main._validate_worker_url("http://192.168.10.50:8081") == "http://192.168.10.50:8081"
        finally:
            main._WORKER_URL_POLICY, main._WORKER_ALLOWED_CIDRS = orig

    def test_strict_mode_blocks_unlisted_ip(self):
        import app.main as main

        orig = (main._WORKER_URL_POLICY, main._WORKER_ALLOWED_CIDRS)
        try:
            main._WORKER_URL_POLICY = "strict"
            main._WORKER_ALLOWED_CIDRS = [main.ipaddress.ip_network("192.168.10.0/24")]
            with pytest.raises(Exception, match="strict mode"):
                main._validate_worker_url("http://10.0.0.5:8081")
        finally:
            main._WORKER_URL_POLICY, main._WORKER_ALLOWED_CIDRS = orig

    def test_metadata_escape_hatch_allows(self):
        # The escape hatch un-blocks the metadata check only. Use the IPv6 IMDS
        # address (ULA fd00::/8, not link-local) so the loopback/link-local guard
        # doesn't independently block it — proving the hatch works in isolation.
        import app.main as main

        orig = main._WORKER_ALLOW_METADATA
        try:
            main._WORKER_ALLOW_METADATA = True
            assert main._validate_worker_url("http://[fd00:ec2::254]:80/") == "http://[fd00:ec2::254]:80"
        finally:
            main._WORKER_ALLOW_METADATA = orig

    def test_strict_mode_hostname_resolves_into_allowed_cidr(self):
        # Strict mode, Case B: hostname resolving to an allowed CIDR is accepted.
        import app.main as main

        orig = (main._WORKER_URL_POLICY, main._WORKER_ALLOWED_CIDRS)
        try:
            main._WORKER_URL_POLICY = "strict"
            main._WORKER_ALLOWED_CIDRS = [main.ipaddress.ip_network("192.168.10.0/24")]
            with patch("app.main.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("192.168.10.50", 8081))]):
                assert main._validate_worker_url("http://wk.local:8081") == "http://wk.local:8081"
        finally:
            main._WORKER_URL_POLICY, main._WORKER_ALLOWED_CIDRS = orig

    def test_strict_mode_hostname_resolves_outside_allowed_cidr_blocked(self):
        import app.main as main

        orig = (main._WORKER_URL_POLICY, main._WORKER_ALLOWED_CIDRS)
        try:
            main._WORKER_URL_POLICY = "strict"
            main._WORKER_ALLOWED_CIDRS = [main.ipaddress.ip_network("192.168.10.0/24")]
            with (
                patch("app.main.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.0.0.5", 8081))]),
                pytest.raises(Exception, match="strict mode"),
            ):
                main._validate_worker_url("http://wk.local:8081")
        finally:
            main._WORKER_URL_POLICY, main._WORKER_ALLOWED_CIDRS = orig

    def test_strict_mode_unresolvable_hostname_blocked(self):
        import app.main as main

        orig = main._WORKER_URL_POLICY
        try:
            main._WORKER_URL_POLICY = "strict"
            with (
                patch("app.main.socket.getaddrinfo", side_effect=socket.gaierror),
                pytest.raises(Exception, match="does not resolve"),
            ):
                main._validate_worker_url("http://nope.invalid:8081")
        finally:
            main._WORKER_URL_POLICY = orig


# ---------------------------------------------------------------------------
# Periodic tasks
# ---------------------------------------------------------------------------


class TestPeriodicTasks:
    def test_run_health_check(self):
        from app.main import _run_health_check

        with (
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            asyncio.run(_run_health_check())

    def test_run_health_check_error(self):
        from app.main import _run_health_check

        with patch("app.main.database.list_workers", new_callable=AsyncMock, side_effect=Exception("db error")):
            asyncio.run(_run_health_check())  # Should not raise

    def test_run_data_retention(self):
        from app.main import _run_data_retention

        with patch("app.main.database.purge_old_data", new_callable=AsyncMock, return_value=5):
            asyncio.run(_run_data_retention())

    def test_run_data_retention_error(self):
        from app.main import _run_data_retention

        with patch("app.main.database.purge_old_data", new_callable=AsyncMock, side_effect=Exception("err")):
            asyncio.run(_run_data_retention())  # Should not raise

    def test_check_stale_workers(self):
        from datetime import UTC, datetime, timedelta

        from app.main import _check_stale_workers

        old_time = (datetime.now(UTC) - timedelta(seconds=300)).isoformat()
        workers = [{"id": 1, "name": "w1", "status": "online", "last_heartbeat": old_time}]
        with (
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.database.set_worker_status", new_callable=AsyncMock) as mock_set,
        ):
            asyncio.run(_check_stale_workers())
            mock_set.assert_called_once_with(1, "offline")

    def test_check_stale_workers_error(self):
        from app.main import _check_stale_workers

        with patch("app.main.database.list_workers", new_callable=AsyncMock, side_effect=Exception("err")):
            asyncio.run(_check_stale_workers())  # Should not raise

    def test_run_collection(self):
        from app.collectors.base import EarningsResult
        from app.main import _run_collection

        mock_collector = AsyncMock()
        mock_collector.collect.return_value = EarningsResult(platform="test", balance=5.0, currency="USD")
        with (
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[{"slug": "test"}]),
            patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
            patch("app.collectors.make_collectors", return_value=[mock_collector]),
            patch("app.main.database.upsert_earnings", new_callable=AsyncMock),
        ):
            asyncio.run(_run_collection())

    def test_run_collection_with_error(self):
        from app.collectors.base import EarningsResult
        from app.main import _run_collection

        mock_collector = AsyncMock()
        mock_collector.collect.return_value = EarningsResult(platform="test", balance=0.0, error="API failed")
        with (
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[{"slug": "test"}]),
            patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
            patch("app.collectors.make_collectors", return_value=[mock_collector]),
        ):
            asyncio.run(_run_collection())


# ---------------------------------------------------------------------------
# Security middleware
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    def test_security_headers_present(self, client):
        with _auth_owner():
            resp = client.get("/api/mode")
            assert resp.headers.get("X-Content-Type-Options") == "nosniff"
            assert resp.headers.get("X-Frame-Options") == "DENY"


# ---------------------------------------------------------------------------
# API: Collectors Meta
# ---------------------------------------------------------------------------


class TestApiCollectorsMeta:
    def test_api_collectors_meta(self, client):
        with (
            _auth_owner(),
            patch("app.main.catalog.get_service", return_value={"name": "Test"}),
        ):
            resp = client.get("/api/collectors/meta")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) > 0
            # Each entry should have slug, name, fields
            assert "slug" in data[0]
            assert "fields" in data[0]

    def test_api_collectors_meta_non_owner(self, client):
        with _auth_viewer():
            resp = client.get("/api/collectors/meta")
            assert resp.status_code == 403


# ---------------------------------------------------------------------------
# API: Per-node earnings
# ---------------------------------------------------------------------------


class TestApiPerNodeEarnings:
    def test_per_node_earnings_unknown_slug(self, client):
        with (
            _auth_owner(),
            patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
        ):
            resp = client.get("/api/services/honeygain/per-node-earnings")
            assert resp.status_code == 200
            assert resp.json() == []


# ---------------------------------------------------------------------------
# Lifespan / scheduler wiring (audit: error listener + job hardening)
# ---------------------------------------------------------------------------


class TestLifespanScheduler:
    """Exercise the real lifespan() so the scheduler wiring is actually covered.

    External I/O (init_db, exchange refresh, collection) is mocked, but the real
    AsyncIOScheduler is started so we can assert every interval job is registered
    with the hardening kwargs and the EVENT_JOB_ERROR/MISSED listener is attached.
    """

    def test_lifespan_registers_jobs_and_error_listener(self):
        import app.main as main_mod

        async def _run():
            with (
                patch("app.main.database.init_db", new_callable=AsyncMock),
                patch("app.main.database.connect_shared", new_callable=AsyncMock),
                patch("app.main.database.close_shared", new_callable=AsyncMock),
                patch("app.main.database.list_users_with_pwd_epoch", new_callable=AsyncMock, return_value=[]),
                patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=True),
                patch("app.main.catalog.load_services"),
                patch("app.main.catalog.register_sighup"),
                patch("app.main.exchange_rates.refresh", new_callable=AsyncMock),
                patch("app.main._run_collection", new_callable=AsyncMock),
                patch("app.main.close_all_collectors", new_callable=AsyncMock, create=True),
            ):
                async with main_mod.lifespan(main_mod.app):
                    sched = main_mod.scheduler
                    jobs = {j.id: j for j in sched.get_jobs()}
                    # All interval jobs registered.
                    assert set(jobs) == {
                        "collect",
                        "health_check",
                        "stale_workers",
                        "data_retention",
                        "db_vacuum",
                        "exchange_rates",
                    }
                    # Every job carries the hardening kwargs (audit fix).
                    for job in jobs.values():
                        assert job.max_instances == 1, f"{job.id} max_instances"
                        assert job.coalesce is True, f"{job.id} coalesce"
                        assert job.misfire_grace_time == 300, f"{job.id} misfire_grace_time"
                    # The error/missed listener is attached.
                    assert len(sched._listeners) >= 1

        asyncio.run(_run())

    def test_on_job_event_logs_without_exception_attr(self):
        """A MISSED event has no .exception attr — the listener must not crash."""
        import app.main as main_mod

        captured = {}

        async def _run():
            with (
                patch("app.main.database.init_db", new_callable=AsyncMock),
                patch("app.main.database.connect_shared", new_callable=AsyncMock),
                patch("app.main.database.close_shared", new_callable=AsyncMock),
                patch("app.main.database.list_users_with_pwd_epoch", new_callable=AsyncMock, return_value=[]),
                patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=True),
                patch("app.main.catalog.load_services"),
                patch("app.main.catalog.register_sighup"),
                patch("app.main.exchange_rates.refresh", new_callable=AsyncMock),
                patch("app.main._run_collection", new_callable=AsyncMock),
                patch("app.main.close_all_collectors", new_callable=AsyncMock, create=True),
                patch("app.main.logger.error") as err,
            ):
                async with main_mod.lifespan(main_mod.app):
                    listener = main_mod.scheduler._listeners[0][0]
                    # Simulate a MISSED event object lacking `.exception`.
                    event = type("Evt", (), {"job_id": "collect"})()
                    listener(event)  # must not raise
                    captured["called"] = err.called

        asyncio.run(_run())
        assert captured["called"] is True

    def test_lifespan_first_run_generates_setup_token(self):
        """With no users, startup generates + persists + activates a setup token."""
        import app.main as main_mod
        from app import setup_token

        async def _run():
            with (
                patch("app.main.database.init_db", new_callable=AsyncMock),
                patch("app.main.database.connect_shared", new_callable=AsyncMock),
                patch("app.main.database.close_shared", new_callable=AsyncMock),
                patch("app.main.database.list_users_with_pwd_epoch", new_callable=AsyncMock, return_value=[]),
                patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
                patch("app.main.database.get_config", new_callable=AsyncMock, return_value=None),
                patch("app.main.database.set_config", new_callable=AsyncMock) as set_cfg,
                patch("app.main.catalog.load_services"),
                patch("app.main.catalog.register_sighup"),
                patch("app.main.exchange_rates.refresh", new_callable=AsyncMock),
                patch("app.main._run_collection", new_callable=AsyncMock),
                patch("app.main.close_all_collectors", new_callable=AsyncMock, create=True),
                patch("app.main.scheduler"),  # isolate from the real module scheduler
            ):
                async with main_mod.lifespan(main_mod.app):
                    assert setup_token.active() is not None
                    set_cfg.assert_awaited_once()  # persisted the freshly generated token

        asyncio.run(_run())


class TestRunVacuum:
    def test_run_vacuum_success(self):
        import app.main as main_mod

        with patch("app.main.database.vacuum_database", new_callable=AsyncMock) as vac:
            asyncio.run(main_mod._run_vacuum())
            vac.assert_awaited_once()

    def test_run_vacuum_swallows_error(self):
        import app.main as main_mod

        with patch(
            "app.main.database.vacuum_database",
            new_callable=AsyncMock,
            side_effect=Exception("boom"),
        ):
            # Must not raise — a failed VACUUM is logged, not fatal.
            asyncio.run(main_mod._run_vacuum())


# ---------------------------------------------------------------------------
# Shared auth deps (app/deps.py) — guard branches
# ---------------------------------------------------------------------------


class TestDepsGuards:
    def test_require_writer_denies_viewer(self, client):
        # A writer-gated route (/api/stop) must 403 for a viewer.
        with _auth_viewer():
            resp = client.post("/api/stop/honeygain")
            assert resp.status_code == 403

    def test_require_private_network_blocks_public_ip(self):
        from fastapi import HTTPException

        from app.deps import _require_private_network

        req = MagicMock()
        req.client.host = "8.8.8.8"
        with pytest.raises(HTTPException) as ei:
            _require_private_network(req)
        assert ei.value.status_code == 403

    def test_require_private_network_allows_private_ip(self):
        from app.deps import _require_private_network

        req = MagicMock()
        req.client.host = "192.168.1.10"
        assert _require_private_network(req) is None

    def test_require_private_network_no_client_is_noop(self):
        from app.deps import _require_private_network

        req = MagicMock()
        req.client = None
        assert _require_private_network(req) is None


class TestWorkerAllowlistParsing:
    def test_parse_allowlist_mixed_entries(self):
        import app.main as main

        with patch.dict(
            os.environ,
            {"CASHPILOT_WORKER_ALLOWED_HOSTS": "192.168.10.0/24, *.ts.net , watchtower.local"},
        ):
            cidrs, suffixes, exact = main._parse_worker_allowlist()
        # Exact-collection asserts (not substring `in`) so CodeQL's
        # url-substring-sanitization heuristic isn't tripped by the test.
        assert cidrs == [main.ipaddress.ip_network("192.168.10.0/24")]
        assert suffixes == ["ts.net"]
        assert exact == {"watchtower.local"}


class TestLoginRateLimitMetric:
    def test_login_rate_limit_records_metric(self, client):
        from fastapi import HTTPException

        def _raise_429(_ip):
            raise HTTPException(status_code=429, detail="Too many login attempts")

        with (
            patch("app.main._check_login_rate", side_effect=_raise_429),
            patch("app.main.metrics.record_rate_limit") as mock_metric,
        ):
            resp = client.post("/login", data={"username": "x", "password": "y"}, follow_redirects=False)
            assert resp.status_code == 429
            mock_metric.assert_called_once()
