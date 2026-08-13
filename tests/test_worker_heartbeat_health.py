"""The worker must be able to report that it cannot report.

A worker whose heartbeats stopped landing kept passing its container
healthcheck, because that check was a TCP connect to its own port -- true of a
process that is listening and completely disconnected. Two hosts ran like that
for 42 hours: `docker ps` said healthy, the fleet page said offline, and nothing
reconciled the two.

These tests pin the two behaviours that close that gap: /api/health degrades
after a sustained run of missed heartbeats, and a name-resolution failure is
explained once with the cause that actually produces it.
"""

from __future__ import annotations

import logging
import os
import socket
from contextlib import asynccontextmanager
from unittest.mock import patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

try:
    from fastapi.testclient import TestClient  # noqa: E402
except ImportError:  # pragma: no cover - exercised only without fastapi
    pytest.skip("fastapi not installed", allow_module_level=True)

from app import worker_api  # noqa: E402


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


def _client():
    worker_api.app.router.lifespan_context = _noop_lifespan
    return TestClient(worker_api.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _reset_heartbeat_state():
    """Module-level counters leak between tests otherwise."""
    before = (
        worker_api._consecutive_heartbeat_failures,
        worker_api._link_hint_logged,
        worker_api._last_heartbeat,
        worker_api._last_error,
    )
    yield
    (
        worker_api._consecutive_heartbeat_failures,
        worker_api._link_hint_logged,
        worker_api._last_heartbeat,
        worker_api._last_error,
    ) = before


class TestHealthReflectsHeartbeat:
    def test_healthy_shape_is_unchanged(self):
        """The healthy response must stay byte-identical to the old one.

        Anything already parsing this endpoint keeps working; only the degraded
        path adds fields.
        """
        worker_api._consecutive_heartbeat_failures = 0
        resp = _client().get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "worker": worker_api.WORKER_NAME}

    def test_still_ok_below_the_threshold(self):
        """A UI restart or a blip must not flap the container to unhealthy."""
        worker_api._consecutive_heartbeat_failures = worker_api._HEARTBEAT_FAILURES_UNHEALTHY_AFTER - 1
        with patch.object(worker_api, "UI_URL", "http://cashpilot-ui:8080"):
            resp = _client().get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_degrades_after_sustained_failures(self):
        worker_api._consecutive_heartbeat_failures = worker_api._HEARTBEAT_FAILURES_UNHEALTHY_AFTER
        worker_api._last_heartbeat = "never"
        worker_api._last_error = "connection failed"
        with patch.object(worker_api, "UI_URL", "http://cashpilot-ui:8080"):
            resp = _client().get("/api/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["last_heartbeat"] == "never"
        assert body["error"] == "connection failed"
        assert body["consecutive_failures"] == str(worker_api._HEARTBEAT_FAILURES_UNHEALTHY_AFTER)

    def test_no_ui_configured_is_not_degraded(self):
        """A worker with nowhere to report is doing what it was told.

        Without this guard every standalone worker would report unhealthy
        forever, which trains operators to ignore the signal.
        """
        worker_api._consecutive_heartbeat_failures = 99
        with patch.object(worker_api, "UI_URL", ""):
            resp = _client().get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestLinkFailureHint:
    def test_explains_a_resolution_failure_once(self, caplog):
        worker_api._link_hint_logged = False
        wrapped = ConnectionError("connect failed")
        wrapped.__cause__ = socket.gaierror(-3, "Try again")

        with (
            patch.object(worker_api, "UI_URL", "http://cashpilot-ui:8080"),
            caplog.at_level(logging.ERROR, logger=worker_api.logger.name),
        ):
            worker_api._log_link_failure_hint(wrapped)
            first = len([r for r in caplog.records if "Cannot resolve" in r.getMessage()])
            # A second failure in the same outage must stay quiet: this used to
            # be logged every 60s for 42 hours, which is how it was ignored.
            worker_api._log_link_failure_hint(wrapped)
            second = len([r for r in caplog.records if "Cannot resolve" in r.getMessage()])

        assert first == 1
        assert second == 1
        msg = next(r.getMessage() for r in caplog.records if "Cannot resolve" in r.getMessage())
        assert "cashpilot-ui" in msg
        assert "NetworkSettings.Networks" in msg

    def test_silent_for_failures_that_are_not_resolution(self, caplog):
        """A refused connection or a timeout has a different cause and fix."""
        worker_api._link_hint_logged = False
        with (
            patch.object(worker_api, "UI_URL", "http://cashpilot-ui:8080"),
            caplog.at_level(logging.ERROR, logger=worker_api.logger.name),
        ):
            worker_api._log_link_failure_hint(TimeoutError("timed out"))

        assert not [r for r in caplog.records if "Cannot resolve" in r.getMessage()]
        assert worker_api._link_hint_logged is False

    def test_finds_the_gaierror_deep_in_the_chain(self, caplog):
        """httpx wraps the resolution error, so the surface type is not gaierror."""
        worker_api._link_hint_logged = False
        inner = socket.gaierror(-3, "Try again")
        middle = OSError("transport failed")
        middle.__cause__ = inner
        outer = ConnectionError("all connection attempts failed")
        outer.__cause__ = middle

        with (
            patch.object(worker_api, "UI_URL", "http://cashpilot-ui:8080"),
            caplog.at_level(logging.ERROR, logger=worker_api.logger.name),
        ):
            worker_api._log_link_failure_hint(outer)

        assert [r for r in caplog.records if "Cannot resolve" in r.getMessage()]

    def test_survives_a_self_referential_exception_chain(self):
        """A cycle in __cause__/__context__ must not hang the heartbeat loop."""
        worker_api._link_hint_logged = False
        a = ConnectionError("a")
        b = ConnectionError("b")
        a.__cause__ = b
        b.__cause__ = a

        with patch.object(worker_api, "UI_URL", "http://cashpilot-ui:8080"):
            worker_api._log_link_failure_hint(a)  # must return, not spin

        assert worker_api._link_hint_logged is False
