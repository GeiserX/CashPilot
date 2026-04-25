"""Tests for main.py FastAPI routes using TestClient.

Covers auth routes, page routes, API endpoints for services, earnings,
config, users, fleet workers, and compose export.
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

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
        with patch("app.main.database.list_workers", new_callable=AsyncMock,
                    return_value=[{"id": 7, "status": "online"}]):
            result = asyncio.run(_resolve_worker_id(None))
            assert result == 7

    def test_no_workers_raises_503(self):
        from app.main import _resolve_worker_id
        with patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[]), pytest.raises(Exception, match="No workers online"):
            asyncio.run(_resolve_worker_id(None))

    def test_multiple_workers_raises_400(self):
        from app.main import _resolve_worker_id
        workers = [
            {"id": 1, "status": "online"},
            {"id": 2, "status": "online"},
        ]
        with patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers), pytest.raises(Exception, match="worker_id is required"):
            asyncio.run(_resolve_worker_id(None))


class TestGetAllWorkerContainers:
    def test_docker_containers(self):
        from app.main import _get_all_worker_containers
        workers = [{
            "id": 1, "name": "w1", "status": "online",
            "system_info": json.dumps({"docker_available": True}),
            "containers": json.dumps([{"slug": "honeygain", "name": "hg", "status": "running"}]),
            "apps": "[]",
        }]
        with patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers):
            result = asyncio.run(_get_all_worker_containers())
        assert len(result) == 1
        assert result[0]["slug"] == "honeygain"
        assert result[0]["deployed_by"] == "w1"

    def test_android_apps(self):
        from app.main import _get_all_worker_containers
        workers = [{
            "id": 2, "name": "phone", "status": "online",
            "system_info": json.dumps({"device_type": "android"}),
            "containers": "[]",
            "apps": json.dumps([{"slug": "earnapp", "running": True}]),
        }]
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
    def test_login_page_redirects_to_register_if_no_users(self, client):
        with (
            _no_auth(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
        ):
            resp = client.get("/login", follow_redirects=False)
            assert resp.status_code == 303
            assert "/register" in resp.headers["location"]

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
            patch("app.main.auth.create_session_token", return_value="tok"),
            patch("app.main.auth.set_session_cookie", side_effect=lambda r, t: r),
        ):
            resp = client.post("/register", data={
                "username": "admin",
                "password": "password123",
                "password_confirm": "password123",
            }, follow_redirects=False)
            assert resp.status_code == 303

    def test_register_password_mismatch(self, client):
        with (
            _no_auth(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
        ):
            resp = client.post("/register", data={
                "username": "admin",
                "password": "password123",
                "password_confirm": "different",
            })
            assert resp.status_code == 400

    def test_register_password_too_short(self, client):
        with (
            _no_auth(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
        ):
            resp = client.post("/register", data={
                "username": "admin",
                "password": "short",
                "password_confirm": "short",
            })
            assert resp.status_code == 400

    def test_register_bad_username(self, client):
        with (
            _no_auth(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
        ):
            resp = client.post("/register", data={
                "username": "a",
                "password": "password123",
                "password_confirm": "password123",
            })
            assert resp.status_code == 400

    def test_register_duplicate_username(self, client):
        with (
            _no_auth(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
            patch("app.main.database.get_user_by_username", new_callable=AsyncMock, return_value={"id": 1}),
        ):
            resp = client.post("/register", data={
                "username": "admin",
                "password": "password123",
                "password_confirm": "password123",
            })
            assert resp.status_code == 400

    def test_register_non_first_user_non_owner_forbidden(self, client):
        with (
            _auth_viewer(),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=True),
        ):
            resp = client.post("/register", data={
                "username": "new",
                "password": "password123",
                "password_confirm": "password123",
            })
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
            assert "/register" in resp.headers["location"]

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

    def test_onboarding_page(self, client):
        with _auth_owner():
            resp = client.get("/onboarding")
            assert resp.status_code == 200

    def test_onboarding_no_auth(self, client):
        with _no_auth():
            resp = client.get("/onboarding", follow_redirects=False)
            assert resp.status_code == 303


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


# ---------------------------------------------------------------------------
# API: Earnings
# ---------------------------------------------------------------------------


class TestApiEarnings:
    def test_api_earnings(self, client):
        with (
            _auth_owner(),
            patch("app.main.database.get_earnings_summary", new_callable=AsyncMock,
                  return_value=[{"platform": "hg", "balance": 5.0, "currency": "USD"}]),
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
            patch("app.main.database.get_daily_earnings", new_callable=AsyncMock,
                  return_value=[{"date": "2026-01-01", "amount": 1.0}]),
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
            patch("app.main.compose_generator.generate_compose_single", return_value="services:\n  hg:\n    image: test"),
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
        with (
            _auth_owner(),
            patch("app.main.database.get_config", new_callable=AsyncMock, return_value={"k": "v"}),
        ):
            resp = client.get("/api/config")
            assert resp.status_code == 200
            assert resp.json() == {"k": "v"}

    def test_api_get_config_non_dict(self, client):
        with (
            _auth_owner(),
            patch("app.main.database.get_config", new_callable=AsyncMock, return_value=None),
        ):
            resp = client.get("/api/config")
            assert resp.json() == {}

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


# ---------------------------------------------------------------------------
# API: Fleet / Workers
# ---------------------------------------------------------------------------


class TestApiFleet:
    def test_api_worker_heartbeat(self, client):
        with (
            patch("app.main.FLEET_API_KEY", "test-fleet-key"),
            patch("app.main.database.upsert_worker", new_callable=AsyncMock, return_value=1),
        ):
            resp = client.post(
                "/api/workers/heartbeat",
                json={"name": "worker-1", "client_id": "c1"},
                headers={"Authorization": "Bearer test-fleet-key"},
            )
            assert resp.status_code == 200
            assert resp.json()["worker_id"] == 1

    def test_api_worker_heartbeat_bad_key(self, client):
        with patch("app.main.FLEET_API_KEY", "test-fleet-key"):
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

    def test_api_fleet_api_key(self, client):
        with (
            _auth_owner(),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.get("/api/fleet/api-key")
            assert resp.status_code == 200
            assert resp.json()["api_key"] == "test-key"

    def test_api_fleet_api_key_non_owner(self, client):
        with _auth_viewer():
            resp = client.get("/api/fleet/api-key")
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
        result = _validate_worker_url("http://worker.mango.ts.net:8081")
        assert "worker.mango.ts.net" in result


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
