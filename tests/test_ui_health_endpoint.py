"""The UI must be able to report that it cannot do its job.

The container healthcheck was a TCP connect — completed by the kernel's listen
backlog while uvicorn is wedged, the scheduler is dead or the database is
unreadable. Meanwhile the bell's "All collectors healthy" is rendered from a
latch that can never go false once set, so a dead scheduler left every signal
affirmatively green with week-old numbers underneath.

/api/health (unauthenticated — the Docker healthcheck asks it) answers three
concrete questions: scheduler running, collection machinery recently completed
a run, database readable. The bell additionally goes "status unknown" when the
collection stamp goes stale.
"""

import asyncio
import os
import time

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

try:
    from fastapi.testclient import TestClient  # noqa: E402

    from app import main  # noqa: E402
except ImportError:
    pytest.skip(
        "Requires full app dependencies — runs in CI",
        allow_module_level=True,
    )

from contextlib import asynccontextmanager  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


def _client():
    main.app.router.lifespan_context = _noop_lifespan
    return TestClient(main.app, raise_server_exceptions=False)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _fresh_stamp():
    before = main._last_collection_finished
    main._last_collection_finished = time.monotonic()
    yield
    main._last_collection_finished = before


def _stale_age():
    return main._COLLECTION_STALE_FACTOR * main.COLLECT_INTERVAL_MIN * 60 + 1


class TestUiHealth:
    def _get(self):
        with patch.object(main.database, "get_config", AsyncMock(return_value={})):
            return _client().get("/api/health")

    def test_healthy_and_unauthenticated(self):
        # No Authorization header, no session — the Docker healthcheck has
        # neither. Scheduler "running" is patched because tests never start it.
        with patch.object(type(main.scheduler), "running", property(lambda self: True)):
            resp = self._get()
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_a_dead_scheduler_degrades(self):
        with patch.object(type(main.scheduler), "running", property(lambda self: False)):
            resp = self._get()
        assert resp.status_code == 503
        assert "scheduler stopped" in resp.json()["problems"]

    def test_a_stale_collection_stamp_degrades(self):
        """A wedged collection lock freezes the stamp: every subsequent run
        skip-returns before the finally, and the age grows through exactly
        the failure the skip line used to disguise as routine."""
        main._last_collection_finished = time.monotonic() - _stale_age()
        with patch.object(type(main.scheduler), "running", property(lambda self: True)):
            resp = self._get()
        assert resp.status_code == 503
        assert any("no collection completed" in p for p in resp.json()["problems"])

    def test_an_unreadable_database_degrades(self):
        with (
            patch.object(type(main.scheduler), "running", property(lambda self: True)),
            patch.object(main.database, "get_config", AsyncMock(side_effect=RuntimeError("locked"))),
        ):
            resp = _client().get("/api/health")
        assert resp.status_code == 503
        assert "database unreadable" in resp.json()["problems"]

    def test_problems_never_carry_exception_text(self):
        # The endpoint is unauthenticated; the reason strings are fixed
        # operational states, never str(exc).
        secret = "password-in-a-connection-error"
        with (
            patch.object(type(main.scheduler), "running", property(lambda self: True)),
            patch.object(main.database, "get_config", AsyncMock(side_effect=RuntimeError(secret))),
        ):
            resp = _client().get("/api/health")
        assert secret not in resp.text


class TestCollectionStampAdvances:
    @pytest.mark.asyncio
    async def test_a_completed_run_advances_the_stamp(self):
        main._last_collection_finished = 1.0  # ancient
        with (
            patch.object(main.database, "get_deployments", AsyncMock(return_value=[])),
            patch.object(main.database, "get_config", AsyncMock(return_value={})),
            patch.object(main, "_detect_payout", AsyncMock(return_value=None)),
            patch.object(main, "_flatline_check", AsyncMock(return_value=[])),
            patch.object(main, "_pending_payout_alerts", AsyncMock(return_value=[])),
            patch.object(main, "_collector_alerts", []),
            patch("app.collectors.make_collectors", lambda deployments, config: []),
            patch("app.collectors._close_stale", AsyncMock()),
        ):
            await main._run_collection()
        assert time.monotonic() - main._last_collection_finished < 60

    @pytest.mark.asyncio
    async def test_a_lock_skip_does_not_advance_the_stamp(self):
        # Negative control: a skipped run is not a completed run — the stamp
        # freezing during a wedge is the entire detection mechanism.
        main._last_collection_finished = 1.0
        async with main._collection_lock:
            await main._run_collection()  # lock held -> skip path
        assert main._last_collection_finished == 1.0


class TestBellStalenessContract:
    def _payload(self):
        with (
            patch.object(main, "_require_auth_api", lambda request: None),
            patch.object(main, "_collector_alerts", []),
            patch.object(main, "_collection_has_run", True),
        ):
            return _client().get("/api/collector-alerts").json()

    def test_fresh_collection_is_not_stale(self):
        main._last_collection_finished = time.monotonic()
        payload = self._payload()
        assert payload["collection_stale"] is False
        assert payload["last_run_age_seconds"] < 60

    def test_a_frozen_stamp_reads_stale(self):
        main._last_collection_finished = time.monotonic() - _stale_age()
        payload = self._payload()
        assert payload["collection_stale"] is True
