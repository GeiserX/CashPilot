"""Tests for main.py deploy/stop/restart/remove routes and worker proxy commands.

These routes proxy commands to workers via httpx, so we mock the httpx calls
and the database layer.
"""

import json
import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app


# No-op lifespan
@asynccontextmanager
async def _noop_lifespan(a):
    yield


app.router.lifespan_context = _noop_lifespan


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
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def deploy_capture():
    """Capture the spec forwarded to ``_proxy_worker_deploy``.

    Returns ``(captured, side_effect)``: patch ``app.main._proxy_worker_deploy``
    with ``side_effect``, then read the forwarded spec from ``captured["spec"]``.
    """
    captured: dict = {}

    async def _capture_deploy(worker_id, slug, spec):
        captured["spec"] = spec
        return {"container_id": "abc123"}

    return captured, _capture_deploy


def _online_worker(wid=1, url="http://192.168.1.10:8081"):
    return {"id": wid, "name": "w1", "status": "online", "url": url}


def _mock_httpx_resp(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = json.dumps(json_data or {})
    resp.headers = {"content-type": "application/json"}
    return resp


# ---------------------------------------------------------------------------
# Deploy route
# ---------------------------------------------------------------------------


class TestApiDeploy:
    def test_deploy_success(self, client):
        svc = {
            "slug": "honeygain",
            "name": "Honeygain",
            "docker": {
                "image": "honeygain/honeygain:latest",
                "env": [{"key": "EMAIL", "default": "user@test.com"}],
                "ports": ["8080:80/tcp"],
                "volumes": ["/data:/app/data"],
            },
        }
        worker = _online_worker()
        httpx_resp = _mock_httpx_resp(200, {"container_id": "abc123"})

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.return_value = httpx_resp

        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post("/api/deploy/honeygain", json={"env": {}, "hostname": "myhost"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "deployed"

    def test_deploy_service_not_found(self, client):
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[_online_worker()]),
            patch("app.main.catalog.get_service", return_value=None),
        ):
            resp = client.post("/api/deploy/nope", json={})
            assert resp.status_code == 404

    def test_deploy_no_image(self, client):
        svc = {"slug": "grass", "name": "Grass", "docker": {}}
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[_online_worker()]),
            patch("app.main.catalog.get_service", return_value=svc),
        ):
            resp = client.post("/api/deploy/grass", json={})
            assert resp.status_code == 400

    def test_deploy_dead_service(self, client):
        svc = {"slug": "peer2profit", "name": "Peer2Profit", "status": "dead", "docker": {"image": "x"}}
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[_online_worker()]),
            patch("app.main.catalog.get_service", return_value=svc),
        ):
            resp = client.post("/api/deploy/peer2profit", json={})
            assert resp.status_code == 410
            assert "no longer available" in resp.json()["detail"]

    def test_deploy_no_auth(self, client):
        with _no_auth():
            resp = client.post("/api/deploy/honeygain", json={})
            assert resp.status_code == 401

    def test_deploy_repocket_emits_rp_env_keys(self, client, deploy_capture):
        """#82 guard at the deploy layer: the real repocket catalog entry must
        produce RP_EMAIL/RP_API_KEY in the container spec sent to the worker.

        Uses the real catalog (no get_service mock), so a future regression that
        renames the YAML keys OR a refactor of api_deploy that mangles env names
        is caught independently of the catalog-level test.
        """
        captured, capture = deploy_capture

        # Reload the real catalog from disk so this test is independent of any
        # earlier test that swapped SERVICES_DIR and left the cache polluted.
        from app import catalog

        catalog.load_services()

        with (
            _auth_owner(),
            patch("app.main._resolve_worker_id", new_callable=AsyncMock, return_value=1),
            patch("app.main._proxy_worker_deploy", side_effect=capture),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.post(
                "/api/deploy/repocket",
                json={"env": {"RP_EMAIL": "me@example.com", "RP_API_KEY": "key123"}},
            )
            assert resp.status_code == 200, resp.text
            spec_env = captured["spec"]["env"]
            assert set(spec_env) == {"RP_EMAIL", "RP_API_KEY"}, (
                f"repocket container spec must carry exactly RP_EMAIL + RP_API_KEY, got {set(spec_env)}"
            )
            assert spec_env["RP_API_KEY"] == "key123"
            assert spec_env["RP_EMAIL"] == "me@example.com"

    def test_deploy_forwards_resources_from_yaml(self, client, deploy_capture):
        """A resources block in the service YAML must reach the worker spec."""
        captured, capture = deploy_capture

        svc = {
            "slug": "storj",
            "name": "Storj",
            "docker": {
                "image": "storjlabs/storagenode",
                "env": [],
                "ports": [],
                "volumes": [],
                "resources": {"mem_limit": "2g", "oom_score_adj": -100},
            },
        }
        with (
            _auth_owner(),
            patch("app.main._resolve_worker_id", new_callable=AsyncMock, return_value=1),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main._proxy_worker_deploy", side_effect=capture),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.post("/api/deploy/storj", json={})
            assert resp.status_code == 200, resp.text
            assert captured["spec"]["resources"] == {"mem_limit": "2g", "oom_score_adj": -100}

    def test_deploy_omits_resources_when_absent(self, client, deploy_capture):
        """A service YAML without a resources block must not add one to the spec."""
        captured, capture = deploy_capture

        svc = {
            "slug": "nores",
            "name": "NoRes",
            "docker": {"image": "x", "env": [], "ports": [], "volumes": []},
        }
        with (
            _auth_owner(),
            patch("app.main._resolve_worker_id", new_callable=AsyncMock, return_value=1),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main._proxy_worker_deploy", side_effect=capture),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.post("/api/deploy/nores", json={})
            assert resp.status_code == 200, resp.text
            assert "resources" not in captured["spec"]

    def test_deploy_storj_real_catalog_carries_resources(self, client, deploy_capture):
        """Guard: the real storj YAML resources must reach the container spec.

        Uses the real catalog (no get_service mock) so a rename of the YAML
        `resources` keys is caught independently of the schema-level test.
        """
        captured, capture = deploy_capture

        from app import catalog

        catalog.load_services()

        with (
            _auth_owner(),
            patch("app.main._resolve_worker_id", new_callable=AsyncMock, return_value=1),
            patch("app.main._proxy_worker_deploy", side_effect=capture),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.post(
                "/api/deploy/storj",
                json={
                    "env": {
                        "WALLET": "0xabc",
                        "EMAIL": "a@b.com",
                        "ADDRESS": "1.2.3.4:28967",
                        "STORAGE": "2TB",
                        "IDENTITY_DIR": "/mnt/id",
                        "STORAGE_DIR": "/mnt/data",
                    }
                },
            )
            assert resp.status_code == 200, resp.text
            assert captured["spec"]["resources"] == {"mem_limit": "2g", "oom_score_adj": -100}


# ---------------------------------------------------------------------------
# Stop / Restart / Start / Remove (service management routes)
# ---------------------------------------------------------------------------


class TestServiceManagement:
    def _setup_proxy(self):
        """Common setup for proxy tests: single online worker, mock httpx."""
        worker = _online_worker()
        httpx_resp = _mock_httpx_resp(200, {"status": "ok"})

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.return_value = httpx_resp
        mock_client.delete.return_value = httpx_resp

        return worker, mock_client

    def test_restart_service(self, client):
        worker, mock_client = self._setup_proxy()
        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post("/api/services/honeygain/restart")
            assert resp.status_code == 200

    def test_stop_service(self, client):
        worker, mock_client = self._setup_proxy()
        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post("/api/services/honeygain/stop")
            assert resp.status_code == 200

    def test_start_service(self, client):
        worker, mock_client = self._setup_proxy()
        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post("/api/services/honeygain/start")
            assert resp.status_code == 200

    def test_remove_service(self, client):
        worker, mock_client = self._setup_proxy()
        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.remove_deployment", new_callable=AsyncMock),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.delete("/api/services/honeygain")
            assert resp.status_code == 200

    def test_service_logs(self, client):
        worker = _online_worker()
        httpx_resp = _mock_httpx_resp(200, {"logs": "log content"})
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get.return_value = httpx_resp

        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.get("/api/services/honeygain/logs?lines=50")
            assert resp.status_code == 200

    def test_old_stop_route(self, client):
        """Test the legacy /api/stop/{slug} route."""
        worker, mock_client = self._setup_proxy()
        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.post("/api/stop/honeygain")
            assert resp.status_code == 200

    def test_old_restart_route(self, client):
        worker, mock_client = self._setup_proxy()
        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.post("/api/restart/honeygain")
            assert resp.status_code == 200

    def test_old_remove_route(self, client):
        worker, mock_client = self._setup_proxy()
        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.remove_deployment", new_callable=AsyncMock),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.delete("/api/remove/honeygain")
            assert resp.status_code == 200

    def test_remove_with_delete_volumes(self, client):
        worker, mock_client = self._setup_proxy()
        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.remove_deployment", new_callable=AsyncMock),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.delete("/api/services/honeygain?delete_volumes=true")
            assert resp.status_code == 200
            assert mock_client.delete.call_args.kwargs["params"] == {"delete_volumes": "true"}


# ---------------------------------------------------------------------------
# Worker proxy error handling
# ---------------------------------------------------------------------------


class TestProxyErrors:
    def test_proxy_worker_error_response(self, client):
        worker = _online_worker()
        error_resp = _mock_httpx_resp(500, {"detail": "Docker error"})

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.return_value = error_resp

        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post("/api/services/honeygain/restart")
            assert resp.status_code == 500

    def test_proxy_worker_httpx_error(self, client):
        worker = _online_worker()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")

        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post("/api/services/honeygain/restart")
            assert resp.status_code == 503

    def test_proxy_worker_offline(self, client):
        worker = {"id": 1, "name": "w1", "status": "offline", "url": "http://192.168.1.10:8081"}
        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
        ):
            resp = client.post("/api/services/honeygain/restart?worker_id=1")
            assert resp.status_code == 503

    def test_proxy_worker_not_found(self, client):
        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=None),
        ):
            resp = client.post("/api/services/honeygain/restart?worker_id=99")
            assert resp.status_code == 404

    def test_proxy_worker_no_url(self, client):
        worker = {"id": 1, "name": "w1", "status": "online", "url": ""}
        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
        ):
            resp = client.post("/api/services/honeygain/restart?worker_id=1")
            assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Worker command proxy route
# ---------------------------------------------------------------------------


class TestWorkerCommand:
    def _setup(self):
        worker = _online_worker()
        httpx_resp = _mock_httpx_resp(200, {"status": "ok"})
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.return_value = httpx_resp
        mock_client.delete.return_value = httpx_resp
        return worker, mock_client

    def test_command_deploy(self, client):
        # Deploy via the command route is OWNER-gated (matching /api/deploy/{slug}),
        # so it must not be reachable with a mere writer role — use owner here.
        worker, mock_client = self._setup()
        with (
            _auth_owner(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.save_deployment", new_callable=AsyncMock) as save_dep,
            patch("app.main.database.record_health_event", new_callable=AsyncMock) as health_evt,
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
            assert resp.status_code == 200
            # The bug fix: a deploy via the command route must record the deployment
            # (so it starts earning) and a "start" health event — not silently skip both.
            save_dep.assert_awaited_once()
            health_evt.assert_awaited()

    def test_command_deploy_writer_denied(self, client):
        """A writer must NOT be able to deploy via /api/workers/{id}/command — deploy is
        owner-only, so this route must not become an owner-gate bypass (writer stays
        allowed for stop/restart/remove, tested separately)."""
        worker, mock_client = self._setup()
        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post(
                "/api/workers/1/command",
                json={"command": "deploy", "slug": "honeygain", "spec": {"image": "test"}},
            )
            assert resp.status_code == 403

    def test_command_stop(self, client):
        worker, mock_client = self._setup()
        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.record_health_event", new_callable=AsyncMock) as health_evt,
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post(
                "/api/workers/1/command",
                json={
                    "command": "stop",
                    "slug": "honeygain",
                },
            )
            assert resp.status_code == 200
            health_evt.assert_awaited_once()

    def test_command_remove(self, client):
        worker, mock_client = self._setup()
        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.remove_deployment", new_callable=AsyncMock) as rm_dep,
            patch("app.main.database.record_health_event", new_callable=AsyncMock) as health_evt,
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post(
                "/api/workers/1/command",
                json={
                    "command": "remove",
                    "slug": "honeygain",
                },
            )
            assert resp.status_code == 200
            # A remove via the command route must clean up the deployments row.
            rm_dep.assert_awaited_once()
            health_evt.assert_awaited()

    def test_command_unknown(self, client):
        worker, mock_client = self._setup()
        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post(
                "/api/workers/1/command",
                json={
                    "command": "nuke",
                    "slug": "honeygain",
                },
            )
            assert resp.status_code == 400

    def test_command_worker_offline(self, client):
        worker = {"id": 1, "name": "w1", "status": "offline", "url": "http://192.168.1.10:8081"}
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

    def test_command_worker_not_found(self, client):
        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=None),
        ):
            resp = client.post(
                "/api/workers/99/command",
                json={
                    "command": "stop",
                    "slug": "honeygain",
                },
            )
            assert resp.status_code == 404

    def test_command_httpx_error(self, client):
        worker = _online_worker()
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("refused")

        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post(
                "/api/workers/1/command",
                json={
                    "command": "restart",
                    "slug": "honeygain",
                },
            )
            assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Deployed services aggregation (multi-node)
# ---------------------------------------------------------------------------


class TestDeployedServicesAggregation:
    def test_aggregation_with_workers_and_earnings(self, client):
        workers = [
            {
                "id": 1,
                "name": "w1",
                "status": "online",
                "system_info": json.dumps({"docker_available": True}),
                "containers": json.dumps(
                    [
                        {
                            "slug": "honeygain",
                            "name": "hg",
                            "status": "running",
                            "image": "hg:latest",
                            "cpu_percent": 1.5,
                            "memory_mb": 50,
                        },
                    ]
                ),
                "apps": "[]",
            }
        ]
        earnings = [{"platform": "honeygain", "balance": 5.0, "currency": "USD"}]
        health = [{"slug": "honeygain", "score": 95, "uptime_pct": 99, "restarts": 0}]
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
            patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=earnings),
            patch("app.main.database.get_health_scores", new_callable=AsyncMock, return_value=health),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
            patch("app.main.catalog.get_service", return_value=svc),
        ):
            resp = client.get("/api/services/deployed")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["slug"] == "honeygain"
            assert data[0]["balance"] == 5.0
            assert data[0]["instances"] == 1
            assert len(data[0]["instance_details"]) == 1

    def test_multi_node_aggregation(self, client):
        workers = [
            {
                "id": 1,
                "name": "w1",
                "status": "online",
                "system_info": json.dumps({"docker_available": True}),
                "containers": json.dumps(
                    [
                        {
                            "slug": "honeygain",
                            "name": "hg-1",
                            "status": "running",
                            "image": "hg:latest",
                            "cpu_percent": 1.0,
                            "memory_mb": 30,
                        },
                    ]
                ),
                "apps": "[]",
            },
            {
                "id": 2,
                "name": "w2",
                "status": "online",
                "system_info": json.dumps({"docker_available": True}),
                "containers": json.dumps(
                    [
                        {
                            "slug": "honeygain",
                            "name": "hg-2",
                            "status": "running",
                            "image": "hg:latest",
                            "cpu_percent": 2.0,
                            "memory_mb": 40,
                        },
                    ]
                ),
                "apps": "[]",
            },
        ]
        svc = {"name": "Honeygain", "category": "bandwidth"}

        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_health_scores", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
            patch("app.main.catalog.get_service", return_value=svc),
        ):
            resp = client.get("/api/services/deployed")
            data = resp.json()
            assert len(data) == 1
            assert data[0]["instances"] == 2
            assert float(data[0]["cpu"].rstrip("%")) == 3.0


# ---------------------------------------------------------------------------
# Earnings summary with non-USD and bonuses
# ---------------------------------------------------------------------------


class TestEarningsSummaryAdvanced:
    def test_earnings_summary_with_non_usd(self, client):
        summary = {"total": 0.0, "today": 0.0, "month": 0.0, "today_change": 0.0}
        earnings = [
            {"platform": "grass", "balance": 100.0, "currency": "GRASS"},
        ]
        with (
            _auth_owner(),
            patch("app.main.database.get_earnings_dashboard_summary", new_callable=AsyncMock, return_value=summary),
            patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
            patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=earnings),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[]),
            patch("app.main.exchange_rates.to_usd", return_value=0.50),
        ):
            resp = client.get("/api/earnings/summary")
            assert resp.status_code == 200

    def test_earnings_summary_with_bonus(self, client):
        summary = {"total": 10.0, "today": 1.0, "month": 5.0, "today_change": 0.5}
        earnings = [
            {"platform": "honeygain", "balance": 15.0, "currency": "USD"},
        ]
        config = {"honeygain_signup_bonus": "5.0"}
        with (
            _auth_owner(),
            patch("app.main.database.get_earnings_dashboard_summary", new_callable=AsyncMock, return_value=summary),
            patch("app.main.database.get_config", new_callable=AsyncMock, return_value=config),
            patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=earnings),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[]),
        ):
            resp = client.get("/api/earnings/summary")
            data = resp.json()
            assert data["total_bonus"] == 5.0
            assert data["total_adjusted"] == 10.0
