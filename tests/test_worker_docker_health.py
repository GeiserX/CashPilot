"""A worker that cannot reach Docker must say so on /api/health.

On 2026-11-17 a Docker update on geiserct replaced /var/run/docker.sock. The
socket proxy had bound the old socket file, so for 17 hours every Docker call
the worker made failed, while /api/health answered 200 and the heartbeat kept
landing. The worker logged the outage once and nothing else saw it.

These tests pin the fix: the outage clock in the orchestrator, and
/api/health turning 503 after a sustained outage (never after a blip), without
calling Docker itself.
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

try:
    from fastapi.testclient import TestClient  # noqa: E402
except ImportError:  # pragma: no cover - exercised only without fastapi
    pytest.skip("fastapi not installed", allow_module_level=True)

from app import orchestrator, worker_api  # noqa: E402

PROXY_HOST = f"unix://{orchestrator.PROXY_SOCKET_DIR}/docker.sock"


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


def _client():
    worker_api.app.router.lifespan_context = _noop_lifespan
    return TestClient(worker_api.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _docker_state(monkeypatch):
    monkeypatch.setattr(orchestrator, "_docker_available", None)
    monkeypatch.setattr(orchestrator, "_docker_unreachable_since", None)


def _outage_for(seconds: float) -> None:
    """Docker has failed every call for this long."""
    orchestrator._mark_docker_unavailable("test", RuntimeError("connection refused"))
    orchestrator._docker_unreachable_since = time.monotonic() - seconds


class TestOutageClock:
    def test_starts_on_the_first_failure_also_at_startup(self):
        # None -> False is a worker that starts with Docker unreachable.
        assert orchestrator.docker_unreachable_for() is None
        orchestrator._mark_docker_unavailable("ping failed", RuntimeError("refused"))
        assert orchestrator.docker_unreachable_for() is not None

    def test_a_repeated_failure_does_not_restart_it(self):
        orchestrator._mark_docker_unavailable("ping failed", RuntimeError("refused"))
        orchestrator._docker_unreachable_since = started = time.monotonic() - 3600
        orchestrator._mark_docker_unavailable("container listing failed", RuntimeError("refused"))
        assert orchestrator._docker_unreachable_since == started

    def test_a_success_stops_it(self):
        _outage_for(3600)
        orchestrator._mark_docker_available()
        assert orchestrator.docker_unreachable_for() is None


class TestHealthReportsALostDocker:
    def test_a_short_outage_stays_healthy(self):
        """A daemon restart or a docker-ce upgrade must not flap the container."""
        _outage_for(worker_api._DOCKER_UNHEALTHY_AFTER - 30)
        resp = _client().get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "worker": worker_api.WORKER_NAME}

    def test_a_sustained_outage_degrades_with_the_reason(self, monkeypatch):
        monkeypatch.setenv("DOCKER_HOST", PROXY_HOST)
        _outage_for(worker_api._DOCKER_UNHEALTHY_AFTER + 60)
        resp = _client().get("/api/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["reason"] == "cannot reach Docker"
        assert body["docker_unreachable_for"].endswith("s")
        assert int(body["docker_unreachable_for"][:-1]) >= worker_api._DOCKER_UNHEALTHY_AFTER
        # Fixed text that names the fix, nothing of Docker's own answer.
        assert "docker restart cashpilot-socket-proxy" in body["docker"]
        assert "connection refused" not in resp.text

    def test_degrades_without_a_ui_too(self):
        """Unlike the heartbeat rule: a worker with no UI and no Docker does nothing it was told."""
        _outage_for(worker_api._DOCKER_UNHEALTHY_AFTER + 60)
        with patch.object(worker_api, "UI_URL", ""):
            resp = _client().get("/api/health")
        assert resp.status_code == 503
        assert resp.json()["reason"] == "cannot reach Docker"

    def test_both_faults_are_named(self):
        _outage_for(worker_api._DOCKER_UNHEALTHY_AFTER + 60)
        worker_api._consecutive_heartbeat_failures = worker_api._HEARTBEAT_FAILURES_UNHEALTHY_AFTER
        with patch.object(worker_api, "UI_URL", "http://cashpilot-ui:8080"):
            resp = _client().get("/api/health")
        assert resp.status_code == 503
        assert resp.json()["reason"] == "not reporting to the UI; cannot reach Docker"

    def test_recovery_returns_to_the_healthy_body(self):
        _outage_for(worker_api._DOCKER_UNHEALTHY_AFTER + 60)
        assert _client().get("/api/health").status_code == 503
        orchestrator._mark_docker_available()
        resp = _client().get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "worker": worker_api.WORKER_NAME}

    def test_never_calls_docker(self):
        """A hung socket must not hang the healthcheck: the clock is read from memory."""
        _outage_for(worker_api._DOCKER_UNHEALTHY_AFTER + 60)

        def hang(*_a, **_k):
            raise AssertionError("/api/health called Docker")

        with patch.object(orchestrator.docker, "from_env", hang):
            resp = _client().get("/api/health")
        assert resp.status_code == 503


class TestHeartbeatSaysHowDockerIsReached:
    def test_heartbeat_carries_docker_access(self, monkeypatch):
        """The UI's alert names what to restart: the proxy, or the worker itself."""
        captured: dict = {}

        class _Resp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {}

        class _Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, json=None, headers=None):
                captured.update(json or {})
                return _Resp()

        monkeypatch.setenv("DOCKER_HOST", PROXY_HOST)
        monkeypatch.setattr(worker_api, "UI_URL", "http://cashpilot-ui:8080")
        monkeypatch.setattr(orchestrator, "get_status", lambda: [])
        monkeypatch.setattr(orchestrator, "docker_available", lambda: False)
        with (
            patch.object(worker_api, "_detect_egress_ip", AsyncMock(return_value=None)),
            patch.object(worker_api, "_disk_usage", return_value=None),
            patch.object(worker_api, "_gpu_info", return_value={}),
            patch.object(worker_api.httpx, "AsyncClient", _Client),
        ):
            asyncio.run(worker_api._send_heartbeat())
        assert captured["system_info"]["docker_access"] == "proxy"
        assert captured["system_info"]["docker_available"] is False
