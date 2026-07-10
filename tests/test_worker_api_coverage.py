"""Tests targeting uncovered lines in app/worker_api.py.

Covers _verify_api_key negative paths (missing header, wrong key, no key
configured), _validate_deploy_spec rejections not already exercised by
test_worker_resources.py (privileged, blocked capabilities, disallowed
network_mode, blocked volume roots, named-volume allow-list), and the
container command endpoints (status/list/deploy/restart/stop/start/remove/
logs) success + docker-error paths.

Mocks app.orchestrator entirely — no real Docker socket is used.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

try:
    from fastapi import HTTPException  # noqa: E402
    from fastapi.testclient import TestClient  # noqa: E402

    from app import worker_api  # noqa: E402
    from app.worker_api import DeploySpec, _validate_deploy_spec, _verify_api_key  # noqa: E402
except ImportError:
    pytest.skip(
        "Requires full app dependencies (fastapi, docker, etc.) — runs in CI",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers — match the TestClient harness used in test_worker_resources.py
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _noop_lifespan(a):
    yield


def _client():
    # Disable the heartbeat lifespan so the TestClient stays isolated.
    worker_api.app.router.lifespan_context = _noop_lifespan
    return TestClient(worker_api.app, raise_server_exceptions=False)


def _auth():
    return {"Authorization": f"Bearer {worker_api.API_KEY}"}


# ---------------------------------------------------------------------------
# _verify_api_key — negative paths
# ---------------------------------------------------------------------------


class TestVerifyApiKeyUnit:
    def test_missing_header_rejected(self):
        req = MagicMock()
        req.headers = {}
        with pytest.raises(HTTPException) as ei:
            _verify_api_key(req)
        assert ei.value.status_code == 401

    def test_wrong_key_rejected(self):
        req = MagicMock()
        req.headers = {"Authorization": "Bearer wrong-key"}
        with pytest.raises(HTTPException) as ei:
            _verify_api_key(req)
        assert ei.value.status_code == 401

    def test_no_key_configured_returns_503(self):
        req = MagicMock()
        req.headers = {"Authorization": "Bearer anything"}
        with patch.object(worker_api, "API_KEY", ""), pytest.raises(HTTPException) as ei:
            _verify_api_key(req)
        assert ei.value.status_code == 503

    def test_correct_key_passes(self):
        req = MagicMock()
        req.headers = {"Authorization": f"Bearer {worker_api.API_KEY}"}
        _verify_api_key(req)  # must not raise


class TestEndpointAuthRejection:
    def test_endpoint_rejects_missing_header(self):
        resp = _client().get("/api/status")
        assert resp.status_code == 401

    def test_endpoint_rejects_wrong_key(self):
        resp = _client().get("/api/status", headers={"Authorization": "Bearer nope"})
        assert resp.status_code == 401

    def test_health_endpoint_requires_no_auth(self):
        resp = _client().get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "worker": worker_api.WORKER_NAME}


# ---------------------------------------------------------------------------
# _validate_deploy_spec — rejections not covered by test_worker_resources.py
# ---------------------------------------------------------------------------


class TestValidateDeploySpecRejections:
    def test_privileged_rejected(self):
        spec = DeploySpec(image="x", privileged=True)
        with pytest.raises(HTTPException) as ei:
            _validate_deploy_spec(spec)
        assert ei.value.status_code == 403

    def test_blocked_capability_rejected(self):
        spec = DeploySpec(image="x", cap_add=["SYS_ADMIN"])
        with pytest.raises(HTTPException) as ei:
            _validate_deploy_spec(spec)
        assert ei.value.status_code == 403

    def test_blocked_capability_rejected_case_insensitive(self):
        spec = DeploySpec(image="x", cap_add=["sys_ptrace"])
        with pytest.raises(HTTPException) as ei:
            _validate_deploy_spec(spec)
        assert ei.value.status_code == 403

    def test_allowed_capability_passes(self):
        _validate_deploy_spec(DeploySpec(image="x", cap_add=["NET_ADMIN"]))  # must not raise

    def test_disallowed_network_mode_rejected(self):
        spec = DeploySpec(image="x", network_mode="container:abc123")
        with pytest.raises(HTTPException) as ei:
            _validate_deploy_spec(spec)
        assert ei.value.status_code == 403

    def test_host_network_mode_allowed(self):
        # mysterium legitimately needs host networking.
        _validate_deploy_spec(DeploySpec(image="x", network_mode="host"))  # must not raise

    def test_bridge_network_mode_allowed(self):
        _validate_deploy_spec(DeploySpec(image="x", network_mode="bridge"))  # must not raise

    @pytest.mark.parametrize("root", ["/etc", "/root", "/var/run", "/proc"])
    def test_blocked_volume_root_rejected(self, root):
        # Patch realpath to identity: on macOS dev machines /etc and /var/run
        # are themselves symlinks (-> /private/etc, /private/var/run), which
        # would dodge the block by resolving to a path outside the blocklist.
        # In the worker's actual Linux container this resolution is a no-op.
        spec = DeploySpec(image="x", volumes={root: {"bind": "/data", "mode": "rw"}})
        with (
            patch("app.worker_api.os.path.realpath", side_effect=lambda p: p),
            pytest.raises(HTTPException) as ei,
        ):
            _validate_deploy_spec(spec)
        assert ei.value.status_code == 403

    def test_blocked_volume_subpath_rejected(self):
        spec = DeploySpec(image="x", volumes={"/etc/passwd": {"bind": "/x", "mode": "ro"}})
        with (
            patch("app.worker_api.os.path.realpath", side_effect=lambda p: p),
            pytest.raises(HTTPException) as ei,
        ):
            _validate_deploy_spec(spec)
        assert ei.value.status_code == 403

    def test_named_volume_always_allowed(self):
        # Not an absolute path -> named volume (e.g. mysterium-data), always allowed.
        spec = DeploySpec(image="x", volumes={"mysterium-data": {"bind": "/data", "mode": "rw"}})
        _validate_deploy_spec(spec)  # must not raise

    def test_allowed_bind_mount_passes(self):
        spec = DeploySpec(image="x", volumes={"/data/honeygain": {"bind": "/data", "mode": "rw"}})
        _validate_deploy_spec(spec)  # must not raise


# ---------------------------------------------------------------------------
# Container command endpoints — success + docker-error paths
# ---------------------------------------------------------------------------


class TestStatusAndListEndpoints:
    def test_status_reports_docker_and_counts(self):
        containers = [{"status": "running"}, {"status": "exited"}]
        with (
            patch("app.worker_api.orchestrator.get_status_cached", return_value=containers),
            patch("app.worker_api.orchestrator.docker_available", return_value=True),
        ):
            resp = _client().get("/api/status", headers=_auth())
        assert resp.status_code == 200
        body = resp.json()
        assert body["docker_available"] is True
        assert body["container_count"] == 2
        assert body["running_count"] == 1

    def test_status_handles_status_fetch_exception(self):
        with (
            patch("app.worker_api.orchestrator.get_status_cached", side_effect=Exception("boom")),
            patch("app.worker_api.orchestrator.docker_available", return_value=False),
        ):
            resp = _client().get("/api/status", headers=_auth())
        assert resp.status_code == 200
        assert resp.json()["container_count"] == 0

    def test_list_containers_success(self):
        containers = [{"slug": "honeygain"}]
        with patch("app.worker_api.orchestrator.get_status_cached", return_value=containers):
            resp = _client().get("/api/containers", headers=_auth())
        assert resp.status_code == 200
        assert resp.json() == containers

    def test_list_containers_docker_unavailable_returns_503(self):
        with patch("app.worker_api.orchestrator.get_status_cached", side_effect=RuntimeError("no docker")):
            resp = _client().get("/api/containers", headers=_auth())
        assert resp.status_code == 503


class TestDeployEndpointErrors:
    def test_generic_exception_returns_500(self):
        with patch("app.worker_api.orchestrator.deploy_raw", side_effect=Exception("boom")):
            resp = _client().post(
                "/api/containers/honeygain/deploy",
                json={"image": "img"},
                headers=_auth(),
            )
        assert resp.status_code == 500


class TestStopRestartStartEndpoints:
    def test_stop_success(self):
        with patch("app.worker_api.orchestrator.stop_service") as mock_stop:
            resp = _client().post("/api/containers/honeygain/stop", headers=_auth())
        assert resp.status_code == 200
        assert resp.json() == {"status": "stopped"}
        mock_stop.assert_called_once_with("honeygain")

    def test_stop_not_found_returns_404(self):
        with patch("app.worker_api.orchestrator.stop_service", side_effect=ValueError("not found")):
            resp = _client().post("/api/containers/missing/stop", headers=_auth())
        assert resp.status_code == 404

    def test_stop_docker_unavailable_returns_503(self):
        with patch("app.worker_api.orchestrator.stop_service", side_effect=RuntimeError("no docker")):
            resp = _client().post("/api/containers/honeygain/stop", headers=_auth())
        assert resp.status_code == 503

    def test_restart_success(self):
        with patch("app.worker_api.orchestrator.restart_service") as mock_restart:
            resp = _client().post("/api/containers/honeygain/restart", headers=_auth())
        assert resp.status_code == 200
        assert resp.json() == {"status": "restarted"}
        mock_restart.assert_called_once_with("honeygain")

    def test_restart_not_found_returns_404(self):
        with patch("app.worker_api.orchestrator.restart_service", side_effect=ValueError("gone")):
            resp = _client().post("/api/containers/x/restart", headers=_auth())
        assert resp.status_code == 404

    def test_restart_docker_unavailable_returns_503(self):
        with patch("app.worker_api.orchestrator.restart_service", side_effect=RuntimeError("no docker")):
            resp = _client().post("/api/containers/honeygain/restart", headers=_auth())
        assert resp.status_code == 503

    def test_start_success(self):
        with patch("app.worker_api.orchestrator.start_service") as mock_start:
            resp = _client().post("/api/containers/honeygain/start", headers=_auth())
        assert resp.status_code == 200
        assert resp.json() == {"status": "started"}
        mock_start.assert_called_once_with("honeygain")

    def test_start_not_found_returns_404(self):
        with patch("app.worker_api.orchestrator.start_service", side_effect=ValueError("gone")):
            resp = _client().post("/api/containers/x/start", headers=_auth())
        assert resp.status_code == 404

    def test_start_docker_unavailable_returns_503(self):
        with patch("app.worker_api.orchestrator.start_service", side_effect=RuntimeError("no docker")):
            resp = _client().post("/api/containers/honeygain/start", headers=_auth())
        assert resp.status_code == 503


class TestRemoveEndpoint:
    def test_remove_success(self):
        removal = {"container": "cashpilot-honeygain", "deleted_volumes": [], "failed_volumes": []}
        with patch("app.worker_api.orchestrator.remove_service", return_value=removal) as mock_remove:
            resp = _client().delete("/api/containers/honeygain", headers=_auth())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "removed"
        assert body["container"] == "cashpilot-honeygain"
        mock_remove.assert_called_once_with("honeygain", delete_volumes=False)

    def test_remove_with_delete_volumes_query_param(self):
        removal = {"container": "cashpilot-honeygain", "deleted_volumes": ["v1"], "failed_volumes": []}
        with patch("app.worker_api.orchestrator.remove_service", return_value=removal) as mock_remove:
            resp = _client().delete("/api/containers/honeygain?delete_volumes=true", headers=_auth())
        assert resp.status_code == 200
        mock_remove.assert_called_once_with("honeygain", delete_volumes=True)

    def test_remove_not_found_returns_404(self):
        with patch("app.worker_api.orchestrator.remove_service", side_effect=ValueError("gone")):
            resp = _client().delete("/api/containers/x", headers=_auth())
        assert resp.status_code == 404

    def test_remove_docker_unavailable_returns_503(self):
        with patch("app.worker_api.orchestrator.remove_service", side_effect=RuntimeError("no docker")):
            resp = _client().delete("/api/containers/honeygain", headers=_auth())
        assert resp.status_code == 503


class TestLogsEndpoint:
    def test_logs_success(self):
        with patch("app.worker_api.orchestrator.get_service_logs", return_value="line1\nline2") as mock_logs:
            resp = _client().get("/api/containers/honeygain/logs", headers=_auth())
        assert resp.status_code == 200
        assert resp.json() == {"logs": "line1\nline2"}
        mock_logs.assert_called_once_with("honeygain", lines=50)

    def test_logs_lines_capped_at_1000(self):
        with patch("app.worker_api.orchestrator.get_service_logs", return_value="") as mock_logs:
            resp = _client().get("/api/containers/honeygain/logs?lines=5000", headers=_auth())
        assert resp.status_code == 200
        mock_logs.assert_called_once_with("honeygain", lines=1000)

    def test_logs_not_found_returns_404(self):
        with patch("app.worker_api.orchestrator.get_service_logs", side_effect=ValueError("gone")):
            resp = _client().get("/api/containers/x/logs", headers=_auth())
        assert resp.status_code == 404

    def test_logs_docker_unavailable_returns_503(self):
        with patch("app.worker_api.orchestrator.get_service_logs", side_effect=RuntimeError("no docker")):
            resp = _client().get("/api/containers/honeygain/logs", headers=_auth())
        assert resp.status_code == 503
