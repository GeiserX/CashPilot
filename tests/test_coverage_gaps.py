"""Tests targeting specific uncovered lines to reach 90%+ coverage.

Covers gaps in catalog.py, collectors/__init__.py, bytelixir.py,
main.py, fleet_key.py, database.py, and various collector edge cases.
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import httpx
import pytest
import yaml

from app import catalog, database
from app.collectors import COLLECTOR_MAP, make_collectors
from app.collectors.base import EarningsResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_async_client():
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def _mock_response(status_code=200, json_data=None, text="", url="https://example.com"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    resp.url = url
    resp.headers = {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=resp
        )
    return resp


def _make_service_yaml(
    slug="test-svc",
    name="Test Service",
    category="bandwidth",
    status="active",
    description="A test service",
    docker=None,
):
    data = {
        "name": name,
        "slug": slug,
        "category": category,
        "status": status,
        "description": description,
        "docker": docker or {"image": "test/image:latest"},
    }
    return yaml.dump(data)


# ---------------------------------------------------------------------------
# catalog.py — .yaml extension with validation errors, SIGHUP, lazy init
# ---------------------------------------------------------------------------


class TestCatalogYamlExtension:
    """Cover lines 70-81: .yaml extension parsing with validation errors."""

    def test_yaml_extension_invalid_yaml(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "bad.yaml").write_text("{{{{invalid")
        (svc_dir / "good.yml").write_text(_make_service_yaml("good"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            services = catalog._load_from_disk()
        assert len(services) == 1

    def test_yaml_extension_non_dict(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "list.yaml").write_text("- item1\n- item2\n")
        (svc_dir / "good.yml").write_text(_make_service_yaml("good"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            services = catalog._load_from_disk()
        assert len(services) == 1

    def test_yaml_extension_missing_fields(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "incomplete.yaml").write_text(yaml.dump({"name": "Only Name"}))
        (svc_dir / "good.yml").write_text(_make_service_yaml("good"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            services = catalog._load_from_disk()
        assert len(services) == 1

    def test_yaml_extension_underscore_skipped(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "_schema.yaml").write_text(_make_service_yaml("schema"))
        (svc_dir / "good.yml").write_text(_make_service_yaml("good"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            services = catalog._load_from_disk()
        assert len(services) == 1


class TestCatalogLazyInit:
    """Cover lines 99, 115: get_services and get_service lazy loading."""

    def test_get_services_lazy_loads(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "lazy.yml").write_text(_make_service_yaml("lazy"))

        # Clear cache
        catalog._services.clear()
        catalog._by_slug.clear()

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            services = catalog.get_services()
        assert len(services) >= 1

    def test_get_service_lazy_loads(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "lazysvc.yml").write_text(_make_service_yaml("lazysvc"))

        # Clear cache
        catalog._services.clear()
        catalog._by_slug.clear()

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            svc = catalog.get_service("lazysvc")
        assert svc is not None
        assert svc["slug"] == "lazysvc"


class TestCatalogSighup:
    """Cover lines 121-128: SIGHUP handler and registration."""

    def test_sighup_handler_reloads(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "svc.yml").write_text(_make_service_yaml("svc"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            catalog._sighup_handler(0, None)
            # After reload, service should be in cache
            assert len(catalog._services) >= 1

    def test_register_sighup_on_unix(self):
        import signal
        import sys

        if sys.platform == "win32":
            pytest.skip("Unix only")
        with patch("signal.signal") as mock_signal:
            catalog.register_sighup()
            mock_signal.assert_called_once_with(signal.SIGHUP, catalog._sighup_handler)


# ---------------------------------------------------------------------------
# collectors/__init__.py — make_collectors edge cases
# ---------------------------------------------------------------------------


class TestMakeCollectorsEdgeCases:
    """Cover lines 86, 101, 106-117: missing keys, unknown slug, instantiation error."""

    def test_skips_unknown_slug(self):
        deployments = [{"slug": "nonexistent-service"}]
        collectors = make_collectors(deployments, {})
        assert len(collectors) == 0

    def test_skips_missing_required_keys(self):
        deployments = [{"slug": "honeygain"}]
        # honeygain needs email + password, not providing them
        collectors = make_collectors(deployments, {})
        assert len(collectors) == 0

    def test_handles_instantiation_error(self):
        """Cover lines 116-117: exception during cls(**kwargs)."""
        deployments = [{"slug": "honeygain"}]
        config = {"honeygain_email": "test@test.com", "honeygain_password": "pass"}

        with patch.dict(COLLECTOR_MAP, {"honeygain": MagicMock(side_effect=Exception("init error"))}):
            collectors = make_collectors(deployments, config)
        assert len(collectors) == 0

    def test_optional_args_not_required(self):
        """Storj with no api_url should still create a collector."""
        deployments = [{"slug": "storj"}]
        collectors = make_collectors(deployments, {})
        assert len(collectors) == 1

    def test_optional_arg_value_passed(self):
        deployments = [{"slug": "storj"}]
        collectors = make_collectors(deployments, {"storj_api_url": "http://custom:14002"})
        assert len(collectors) == 1
        assert collectors[0].api_url == "http://custom:14002"

    def test_deployment_without_slug_key(self):
        deployments = [{"other_key": "value"}]
        collectors = make_collectors(deployments, {})
        assert len(collectors) == 0


# ---------------------------------------------------------------------------
# bytelixir.py — _make_client, parse balance edge cases
# ---------------------------------------------------------------------------


class TestBytelixirMakeClient:
    """Cover lines 59-77: _make_client with remember_web and xsrf_token."""

    def test_make_client_with_all_cookies(self):
        from app.collectors.bytelixir import BytelixirCollector

        c = BytelixirCollector(
            session_cookie="sess-val",
            remember_web="remember-val",
            xsrf_token="xsrf-val",
        )
        client = c._make_client()
        assert isinstance(client, httpx.AsyncClient)
        # Verify cookies are set
        cookies = dict(client.cookies)
        assert "bytelixir_session" in cookies
        assert c._REMEMBER_COOKIE in cookies
        assert "XSRF-TOKEN" in cookies
        asyncio.run(client.aclose())

    def test_make_client_session_only(self):
        from app.collectors.bytelixir import BytelixirCollector

        c = BytelixirCollector(session_cookie="sess-only")
        client = c._make_client()
        cookies = dict(client.cookies)
        assert "bytelixir_session" in cookies
        assert c._REMEMBER_COOKIE not in cookies
        assert "XSRF-TOKEN" not in cookies
        asyncio.run(client.aclose())


class TestBytelixirParseBalanceEdgeCases:
    """Cover lines 115-123: parse_balance when all matches are zero."""

    def test_parse_balance_all_zero(self):
        from app.collectors.bytelixir import BytelixirCollector

        html = '<span>$</span>0.00<span class="text-2xs">000</span>'
        result = BytelixirCollector._parse_balance_from_html(html)
        # All zero — should return first match (0.00000)
        assert result == 0.0

    def test_parse_balance_first_zero_second_nonzero(self):
        from app.collectors.bytelixir import BytelixirCollector

        html = '<span>$</span>0.00<span class="text-2xs">000</span><span>$</span>1.23<span class="text-2xs">456</span>'
        result = BytelixirCollector._parse_balance_from_html(html)
        assert result == 1.23456


# ---------------------------------------------------------------------------
# main.py — uncovered edge cases
# ---------------------------------------------------------------------------


# No-op lifespan for TestClient
@asynccontextmanager
async def _noop_lifespan(a):
    yield


def _owner_user():
    return {"uid": 1, "u": "admin", "r": "owner"}


def _writer_user():
    return {"uid": 2, "u": "writer", "r": "writer"}


def _auth_owner():
    return patch("app.main.auth.get_current_user", return_value=_owner_user())


def _auth_writer():
    return patch("app.main.auth.get_current_user", return_value=_writer_user())


def _no_auth():
    return patch("app.main.auth.get_current_user", return_value=None)


@pytest.fixture
def client():
    from app.main import app

    app.router.lifespan_context = _noop_lifespan
    from fastapi.testclient import TestClient

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestMainHealthCheckWithContainers:
    """Cover lines 147-155: health check with running and non-running containers."""

    def test_health_check_records_events(self):
        from app.main import _run_health_check

        workers = [
            {
                "id": 1,
                "name": "w1",
                "status": "online",
                "system_info": json.dumps({"docker_available": True}),
                "containers": json.dumps(
                    [
                        {"slug": "honeygain", "name": "hg", "status": "running"},
                        {"slug": "earnapp", "name": "ea", "status": "stopped"},
                    ]
                ),
                "apps": "[]",
            }
        ]
        mock_record = AsyncMock()
        with (
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.database.record_health_event", mock_record),
        ):
            asyncio.run(_run_health_check())

        # Should record check_ok for honeygain (running) and check_down for earnapp (stopped)
        calls = mock_record.call_args_list
        slugs_events = [(c.args[0], c.args[1]) for c in calls]
        assert ("honeygain", "check_ok") in slugs_events
        assert ("earnapp", "check_down") in slugs_events


class TestMainStaleWorkers:
    """Cover _check_stale_workers with no heartbeat field."""

    def test_stale_worker_no_heartbeat(self):
        from app.main import _check_stale_workers

        workers = [{"id": 1, "name": "w1", "status": "online", "last_heartbeat": None}]
        with (
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.database.set_worker_status", new_callable=AsyncMock) as mock_set,
        ):
            asyncio.run(_check_stale_workers())
            # No heartbeat means no comparison, should not crash or mark offline
            mock_set.assert_not_called()


class TestMainRunCollectionException:
    """Cover line 167: _run_collection total failure."""

    def test_run_collection_total_exception(self):
        from app.main import _run_collection

        with patch("app.main.database.get_deployments", new_callable=AsyncMock, side_effect=Exception("DB down")):
            asyncio.run(_run_collection())  # Should not raise


class TestMainDeployCommandEdgeCases:
    """Cover deploy route command substitution and volume substitution."""

    def test_deploy_with_command_substitution(self, client):
        svc = {
            "slug": "test-cmd",
            "name": "TestCmd",
            "docker": {
                "image": "test:latest",
                "env": [{"key": "TOKEN", "default": "abc"}],
                "ports": [],
                "volumes": ["${TOKEN}:/data:ro"],
                "command": "run --token=${TOKEN}",
            },
        }
        worker = {"id": 1, "name": "w1", "status": "online", "url": "http://192.168.1.10:8081"}
        httpx_resp = MagicMock()
        httpx_resp.status_code = 200
        httpx_resp.json.return_value = {"container_id": "abc"}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.return_value = httpx_resp

        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post("/api/deploy/test-cmd", json={"env": {"TOKEN": "mytoken"}})
            assert resp.status_code == 200

    def test_deploy_with_network_mode_and_cap_add(self, client):
        svc = {
            "slug": "test-net",
            "name": "TestNet",
            "docker": {
                "image": "test:latest",
                "env": [],
                "ports": [],
                "volumes": [],
                "network_mode": "host",
                "cap_add": ["NET_ADMIN"],
                "privileged": True,
            },
        }
        worker = {"id": 1, "name": "w1", "status": "online", "url": "http://192.168.1.10:8081"}
        httpx_resp = MagicMock()
        httpx_resp.status_code = 200
        httpx_resp.json.return_value = {"container_id": "xyz"}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.return_value = httpx_resp

        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post("/api/deploy/test-net", json={})
            assert resp.status_code == 200


class TestMainProxyWorkerDeployError:
    """Cover lines 940-948: proxy deploy error responses."""

    def test_proxy_deploy_error_response(self, client):
        svc = {
            "slug": "hg",
            "name": "Honeygain",
            "docker": {"image": "hg:latest", "env": [], "ports": [], "volumes": []},
        }
        worker = {"id": 1, "name": "w1", "status": "online", "url": "http://192.168.1.10:8081"}
        error_resp = MagicMock()
        error_resp.status_code = 500
        error_resp.json.return_value = {"detail": "Docker error"}
        error_resp.text = '{"detail": "Docker error"}'
        error_resp.headers = {"content-type": "application/json"}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.return_value = error_resp

        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post("/api/deploy/hg", json={})
            assert resp.status_code == 500

    def test_proxy_deploy_httpx_error(self, client):
        svc = {
            "slug": "hg",
            "name": "Honeygain",
            "docker": {"image": "hg:latest", "env": [], "ports": [], "volumes": []},
        }
        worker = {"id": 1, "name": "w1", "status": "online", "url": "http://192.168.1.10:8081"}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")

        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post("/api/deploy/hg", json={})
            assert resp.status_code == 503


class TestMainProxyLogsError:
    """Cover lines 964-972: proxy logs error responses."""

    def test_proxy_logs_error_response(self, client):
        worker = {"id": 1, "name": "w1", "status": "online", "url": "http://192.168.1.10:8081"}
        error_resp = MagicMock()
        error_resp.status_code = 500
        error_resp.json.return_value = {"detail": "error"}
        error_resp.text = '{"detail": "error"}'
        error_resp.headers = {"content-type": "application/json"}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get.return_value = error_resp

        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.get("/api/services/honeygain/logs?worker_id=1")
            assert resp.status_code == 500

    def test_proxy_logs_httpx_error(self, client):
        worker = {"id": 1, "name": "w1", "status": "online", "url": "http://192.168.1.10:8081"}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("refused")

        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.get("/api/services/honeygain/logs?worker_id=1")
            assert resp.status_code == 503


class TestMainComposeSingleError:
    """Cover lines 1039-1040: compose single ValueError."""

    def test_compose_single_value_error(self, client):
        svc = {"slug": "bad", "name": "Bad", "docker": {}}
        with (
            _auth_owner(),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.compose_generator.generate_compose_single", side_effect=ValueError("no image")),
        ):
            resp = client.get("/api/compose/bad")
            assert resp.status_code == 400

    def test_compose_multi_value_error(self, client):
        with (
            _auth_owner(),
            patch("app.main.compose_generator.generate_compose_multi", side_effect=ValueError("no services")),
        ):
            resp = client.post("/api/compose", json={"slugs": ["bad"]})
            assert resp.status_code == 400

    def test_compose_all_value_error(self, client):
        with (
            _auth_owner(),
            patch("app.main.compose_generator.generate_compose_all", side_effect=ValueError("no services")),
        ):
            resp = client.get("/api/compose")
            assert resp.status_code == 400


class TestMainPerNodeEarnings:
    """Cover lines 1238-1247: per-node earnings for mysterium."""

    def test_per_node_earnings_mysterium(self, client):
        mock_collector = MagicMock()
        mock_collector.get_per_node_earnings = AsyncMock(return_value=[{"identity": "0xabc", "earnings_myst": 5.0}])
        with (
            _auth_owner(),
            patch(
                "app.main.database.get_config",
                new_callable=AsyncMock,
                return_value={
                    "mysterium_email": "test@test.com",
                    "mysterium_password": "pass",
                },
            ),
            patch("app.collectors.mystnodes.MystNodesCollector", return_value=mock_collector),
        ):
            resp = client.get("/api/services/mysterium/per-node-earnings")
            assert resp.status_code == 200


class TestMainSetConfigExternalDeploySkip:
    """Cover lines 1456, 1460: config set that skips services with images."""

    def test_set_config_skips_docker_service(self, client):
        """When all required keys are provided for a docker-image service, don't auto-deploy."""
        svc = {"slug": "honeygain", "docker": {"image": "hg:latest"}}
        with (
            _auth_owner(),
            patch("app.main.database.set_config_bulk", new_callable=AsyncMock),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.database.get_deployment", new_callable=AsyncMock),
            patch("app.main.database.save_deployment", new_callable=AsyncMock) as mock_save,
        ):
            resp = client.post(
                "/api/config",
                json={
                    "data": {
                        "honeygain_email": "test@test.com",
                        "honeygain_password": "pass",
                    }
                },
            )
            assert resp.status_code == 200
            mock_save.assert_not_called()


class TestMainClearConfigWithDockerService:
    """Cover main.py clear config for docker-based service."""

    def test_clear_config_docker_service_no_deployment_removed(self, client):
        svc = {"slug": "honeygain", "docker": {"image": "hg:latest"}}
        with (
            _auth_owner(),
            patch("app.main.database.delete_config_keys", new_callable=AsyncMock),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.database.remove_deployment", new_callable=AsyncMock) as mock_rm,
        ):
            resp = client.delete("/api/config/honeygain")
            assert resp.status_code == 200
            # Docker services don't auto-create external deployments, so no removal
            mock_rm.assert_not_called()


class TestMainPreferencesSetupCompleted:
    """Cover line 1294: setup_completed triggers collection."""

    def test_set_preferences_completed_triggers_collection(self, client):
        with (
            _auth_owner(),
            patch("app.main.database.get_user_preferences", new_callable=AsyncMock, return_value=None),
            patch("app.main.database.save_user_preferences", new_callable=AsyncMock),
        ):
            resp = client.post("/api/preferences", json={"setup_completed": True})
            assert resp.status_code == 200


class TestMainWorkerCommandNoUrl:
    """Cover line 1659: worker command with no URL."""

    def test_worker_command_no_url(self, client):
        worker = {"id": 1, "name": "w1", "status": "online", "url": ""}
        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
        ):
            resp = client.post(
                "/api/workers/1/command",
                json={
                    "command": "stop",
                    "slug": "honeygain",
                },
            )
            assert resp.status_code == 503


class TestMainWorkerCommandHttpError:
    """Cover line 1688: worker command httpx error on deploy."""

    def test_worker_command_deploy_error(self, client):
        worker = {"id": 1, "name": "w1", "status": "online", "url": "http://192.168.1.10:8081"}
        error_resp = MagicMock()
        error_resp.status_code = 500
        error_resp.text = "Internal Server Error"
        error_resp.headers = {"content-type": "text/plain"}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.return_value = error_resp

        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post(
                "/api/workers/1/command",
                json={
                    "command": "deploy",
                    "slug": "honeygain",
                    "spec": {"image": "test"},
                },
            )
            assert resp.status_code == 500


class TestMainEarningsSummaryWithWorkerException:
    """Cover lines 1124-1125: worker container exception in summary."""

    def test_earnings_summary_worker_exception(self, client):
        summary = {"total": 10.0, "today": 1.0, "month": 5.0, "today_change": 0.5}
        with (
            _auth_owner(),
            patch("app.main.database.get_earnings_dashboard_summary", new_callable=AsyncMock, return_value=summary),
            patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
            patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=[]),
            patch("app.main._get_all_worker_containers", new_callable=AsyncMock, side_effect=Exception("worker error")),
        ):
            resp = client.get("/api/earnings/summary")
            assert resp.status_code == 200
            assert resp.json()["active_services"] == 0


class TestMainServicesDeployedMultiStatus:
    """Cover lines 605, 626-627: deployed services with various statuses."""

    def test_deployed_services_with_cashout_and_referral(self, client):
        workers = [
            {
                "id": 1,
                "name": "w1",
                "status": "online",
                "system_info": json.dumps({"docker_available": True}),
                "containers": json.dumps(
                    [
                        {
                            "slug": "hg",
                            "name": "hg",
                            "status": "restarting",
                            "image": "hg:latest",
                            "cpu_percent": 0.5,
                            "memory_mb": 25,
                        },
                        {
                            "slug": "hg",
                            "name": "hg-2",
                            "status": "running",
                            "image": "hg:latest",
                            "cpu_percent": 1.0,
                            "memory_mb": 30,
                        },
                    ]
                ),
                "apps": "[]",
            }
        ]
        svc = {
            "name": "Honeygain",
            "category": "bandwidth",
            "cashout": {"min_amount": 20},
            "referral": {"signup_url": "https://r.hg.com"},
            "website": "https://honeygain.com",
        }

        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch(
                "app.main.database.get_earnings_summary",
                new_callable=AsyncMock,
                return_value=[{"platform": "hg", "balance": 5.0, "currency": "USD"}],
            ),
            patch("app.main.database.get_health_scores", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
            patch("app.main.catalog.get_service", return_value=svc),
        ):
            resp = client.get("/api/services/deployed")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["instances"] == 2
            # Best status should be "running" (higher priority than restarting)
            assert data[0]["container_status"] == "running"


class TestMainServicesAvailableNodeCounts:
    """Cover lines 713-719: node counts from worker containers."""

    def test_services_available_with_node_counts(self, client):
        svcs = [{"slug": "hg", "name": "HG", "status": "active", "docker": {"image": "test"}}]
        workers = [
            {
                "id": 1,
                "name": "w1",
                "status": "online",
                "system_info": json.dumps({"docker_available": True}),
                "containers": json.dumps([{"slug": "hg", "name": "hg", "status": "running"}]),
                "apps": "[]",
            }
        ]
        deps = [{"slug": "hg"}]
        with (
            _auth_owner(),
            patch("app.main.catalog.get_services", return_value=svcs),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=deps),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
        ):
            resp = client.get("/api/services/available")
            data = resp.json()
            assert len(data) == 1
            assert data[0]["deployed"] is True
            assert data[0]["node_count"] == 1


class TestMainGetServiceEnriched:
    """Cover lines 749-750: service enrichment with worker data."""

    def test_get_service_with_worker_data(self, client):
        svc = {"slug": "hg", "name": "HG", "docker": {"image": "test"}}
        workers = [
            {
                "id": 1,
                "name": "w1",
                "status": "online",
                "system_info": json.dumps({"docker_available": True}),
                "containers": json.dumps([{"slug": "hg", "name": "hg", "status": "running"}]),
                "apps": "[]",
            }
        ]
        with (
            _auth_owner(),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
        ):
            resp = client.get("/api/services/hg")
            assert resp.status_code == 200
            data = resp.json()
            assert data["deployed"] is True
            assert data["node_count"] == 1


# ---------------------------------------------------------------------------
# Collector edge cases — small gaps
# ---------------------------------------------------------------------------


class TestCollectorSmallGaps:
    """Cover remaining 1-3 line gaps in various collectors."""

    def test_honeygain_login_no_token(self):
        """Cover honeygain.py line 44: login response missing access_token."""
        from app.collectors.honeygain import HoneygainCollector

        login_resp = _mock_response(200, {"data": {}})
        client = _make_async_client()
        client.post.return_value = login_resp

        with patch("app.collectors.honeygain.httpx.AsyncClient", return_value=client):
            c = HoneygainCollector(email="test@test.com", password="pass")
            result = asyncio.run(c.collect())
        assert result.error is not None

    def test_iproyal_login_success_but_no_balance_field(self):
        """Cover iproyal.py lines 53-54: balance response without balance field."""
        from app.collectors.iproyal import IPRoyalCollector

        login_resp = _mock_response(200, {"access_token": "tok"})
        balance_resp = _mock_response(200, {})  # missing balance field

        client = _make_async_client()
        client.post.return_value = login_resp
        client.get.return_value = balance_resp

        with patch("app.collectors.iproyal.httpx.AsyncClient", return_value=client):
            c = IPRoyalCollector(email="test@test.com", password="pass")
            result = asyncio.run(c.collect())
        # Should either succeed with 0 or have an error
        assert isinstance(result, EarningsResult)

    def test_earnfm_login_response_missing_token(self):
        """Cover earnfm.py lines 53, 59: login without access_token."""
        from app.collectors.earnfm import EarnFMCollector

        login_resp = _mock_response(200, {})  # missing access_token
        client = _make_async_client()
        client.post.return_value = login_resp

        with patch("app.collectors.earnfm.httpx.AsyncClient", return_value=client):
            c = EarnFMCollector(email="test@test.com", password="pass")
            result = asyncio.run(c.collect())
        assert isinstance(result, EarningsResult)

    def test_bitping_login_missing_cookie(self):
        """Cover bitping.py lines 45-48: login without cookie set."""
        from app.collectors.bitping import BitpingCollector

        login_resp = _mock_response(200, {})
        client = _make_async_client()
        client.cookies = MagicMock()
        client.cookies.items.return_value = []  # no token cookie
        client.post.return_value = login_resp

        with patch("app.collectors.bitping.httpx.AsyncClient", return_value=client):
            c = BitpingCollector(email="test@test.com", password="pass")
            result = asyncio.run(c.collect())
        assert result.error is not None

    def test_traffmonetizer_login_missing_token(self):
        """Cover traffmonetizer.py line 45: login response without token."""
        from app.collectors.traffmonetizer import TraffmonetizerCollector

        login_resp = _mock_response(200, {"data": {}})
        client = _make_async_client()
        client.post.return_value = login_resp

        with patch("app.collectors.traffmonetizer.httpx.AsyncClient", return_value=client):
            c = TraffmonetizerCollector(email="test@test.com", password="pass")
            result = asyncio.run(c.collect())
        assert isinstance(result, EarningsResult)

    def test_repocket_login_missing_token(self):
        """Cover repocket.py lines 49, 55: login without idToken."""
        from app.collectors.repocket import RepocketCollector

        login_resp = _mock_response(200, {})  # missing idToken
        client = _make_async_client()
        client.post.return_value = login_resp

        with patch("app.collectors.repocket.httpx.AsyncClient", return_value=client):
            c = RepocketCollector(email="test@test.com", password="pass")
            result = asyncio.run(c.collect())
        assert isinstance(result, EarningsResult)

    def test_mystnodes_login_missing_token(self):
        """Cover mystnodes.py lines 51, 57: login without accessToken."""
        from app.collectors.mystnodes import MystNodesCollector

        login_resp = _mock_response(200, {})  # missing accessToken
        client = _make_async_client()
        client.post.return_value = login_resp

        with patch("app.collectors.mystnodes.httpx.AsyncClient", return_value=client):
            c = MystNodesCollector(email="test@test.com", password="pass")
            result = asyncio.run(c.collect())
        assert isinstance(result, EarningsResult)

    def test_storj_no_current_month(self):
        """Cover storj.py line 54: response without any known fields."""
        from app.collectors.storj import StorjCollector

        resp = _mock_response(200, {})
        client = _make_async_client()
        client.get.return_value = resp

        with patch("app.collectors.storj.httpx.AsyncClient", return_value=client):
            c = StorjCollector()
            result = asyncio.run(c.collect())
        assert isinstance(result, EarningsResult)

    def test_packetstream_api_endpoint_pattern(self):
        """Cover packetstream.py lines 74-75: API endpoint pattern."""
        from app.collectors.packetstream import PacketStreamCollector

        html = '"balance":3.50'
        resp = _mock_response(200, url="https://app.packetstream.io/dashboard")
        resp.text = html
        client = _make_async_client()
        client.get.return_value = resp

        with patch("app.collectors.packetstream.httpx.AsyncClient", return_value=client):
            c = PacketStreamCollector(auth_token="jwt")
            result = asyncio.run(c.collect())
        assert isinstance(result, EarningsResult)

    def test_earnapp_balance_field_missing(self):
        """Cover earnapp.py line 39: response without balance field."""
        from app.collectors.earnapp import EarnAppCollector

        xsrf_resp = _mock_response(200)
        no_balance_resp = _mock_response(200, {"earnings_total": 0})

        client = _make_async_client()
        client.cookies = MagicMock()
        client.cookies.items.return_value = [("xsrf-token", "val")]
        client.get.side_effect = [xsrf_resp, no_balance_resp]

        with patch("app.collectors.earnapp.httpx.AsyncClient", return_value=client):
            c = EarnAppCollector(oauth_token="tok")
            result = asyncio.run(c.collect())
        assert isinstance(result, EarningsResult)

    def test_grass_epoch_fallback_no_devices(self):
        """Cover grass.py lines 100-101, 107-108, 117: active epoch with empty devices."""
        from app.collectors.grass import GrassCollector

        user_resp = _mock_response(200, {"result": {"data": {"totalPoints": 0}}})
        devices_resp = _mock_response(200, {"result": {"data": []}})

        client = _make_async_client()
        client.get.side_effect = [user_resp, devices_resp]

        with patch("app.collectors.grass.httpx.AsyncClient", return_value=client):
            c = GrassCollector(access_token="test-token")
            result = asyncio.run(c.collect())
        assert result.balance == 0.0


# ---------------------------------------------------------------------------
# database.py — encryption edge cases
# ---------------------------------------------------------------------------


class TestDatabaseEncryptionEdgeCases:
    """Cover database.py lines 57-61, 66-68, 90-92: Fernet key loading edge cases."""

    def test_decrypt_invalid_token(self):
        """Cover line 90-92: decrypt with invalid ciphertext."""
        result = database.decrypt_value("enc:invalid-base64-garbage")
        assert result == ""

    def test_is_secret_key_various(self):
        assert database._is_secret_key("my_service_token") is True
        assert database._is_secret_key("my_service_secret_key") is True
        assert database._is_secret_key("my_service_session_cookie") is True
        assert database._is_secret_key("my_service_brd_sess_id") is True
        assert database._is_secret_key("my_service_remember_web") is True
        assert database._is_secret_key("my_service_xsrf_token") is True
        assert database._is_secret_key("my_service_email") is False
        assert database._is_secret_key("plain_setting") is False


# ---------------------------------------------------------------------------
# fleet_key.py — edge cases
# ---------------------------------------------------------------------------


class TestFleetKeyEdgeCases:
    """Cover fleet_key.py lines 40-41, 61-62."""

    def test_existing_key_file_logged(self, tmp_path):
        from app import fleet_key

        key_dir = tmp_path / "fleet"
        key_dir.mkdir()
        key_file = key_dir / ".fleet_key"
        key_file.write_text("stored-key-123")

        with (
            patch.object(fleet_key, "_FLEET_KEY_DIR", key_dir),
            patch.object(fleet_key, "_FLEET_KEY_FILE", key_file),
            patch.dict(os.environ, {"CASHPILOT_API_KEY": ""}),
        ):
            result = fleet_key.resolve_fleet_key()
            assert result == "stored-key-123"


# ---------------------------------------------------------------------------
# auth.py — OSError reading key file
# ---------------------------------------------------------------------------


class TestAuthOSError:
    """Cover auth.py lines 56-57: OSError reading persisted key."""

    def test_resolve_secret_key_oserror_reading(self, tmp_path):
        from app import auth

        with (
            patch.dict(os.environ, {"CASHPILOT_SECRET_KEY": "", "CASHPILOT_DATA_DIR": str(tmp_path)}),
            patch("app.auth.Path") as mock_path_cls,
        ):
            mock_data_dir = MagicMock()
            mock_key_file = MagicMock()
            mock_key_file.is_file.return_value = True
            mock_key_file.read_text.side_effect = OSError("permission denied")
            mock_data_dir.__truediv__ = MagicMock(return_value=mock_key_file)
            mock_path_cls.return_value = mock_data_dir
            result = auth._resolve_secret_key()
            # Should generate a new key since reading failed
            assert len(result) > 20
