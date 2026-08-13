"""A worker going offline must be an alert, not a log line.

The 42-hour incident, UI side: two workers stopped heartbeating, the UI marked
them offline in its own database within 3 minutes — and told nobody. The fleet
page was the only witness, and nobody was looking at it. These tests pin the
full lifecycle: transition -> alert row + push + bell, dedupe inside the
cooldown, persistence across a UI restart, and recovery clearing all of it.
"""

import asyncio
import os

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

try:
    from app.main import (  # noqa: E402
        _check_stale_workers,
        _offline_worker_alerts,
        _warm_collector_alerts,
        api_worker_heartbeat,
    )
except ImportError:
    pytest.skip(
        "Requires full app dependencies (fastapi, httpx, etc.) — runs in CI",
        allow_module_level=True,
    )

from types import SimpleNamespace  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

from app import main  # noqa: E402


def _request():
    req = MagicMock()
    req.headers = {"Authorization": "Bearer test-fleet-key"}
    return req


def _worker_row(**over):
    row = {
        "id": 1,
        "client_id": "srv-1",
        "name": "watchtower",
        "url": "",
        "status": "online",
        "containers": "[]",
        "apps": "[]",
        "system_info": '{"docker_available": true}',
        "last_heartbeat": "2026-04-04T12:00:00",
        "registered_at": "2026-04-01T00:00:00",
        "api_key_enc": None,
    }
    row.update(over)
    return row


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolate_bell():
    before = main._collector_alerts
    main._collector_alerts = []
    yield
    main._collector_alerts = before


class TestOfflineTransition:
    def _sweep(self, *, record_returns, rows=None):
        """Run _check_stale_workers over one stale online worker."""
        sends = []

        async def _capture_send(title, message, **kw):
            sends.append((title, kw.get("kind"), kw.get("subject")))
            return 1

        record = AsyncMock(return_value=record_returns)
        with (
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=rows or [_worker_row()]),
            patch("app.main.database.set_worker_status", new_callable=AsyncMock) as set_status,
            patch("app.main.database.record_alert", record),
            patch("app.main.notify.send", _capture_send),
        ):
            _run(_check_stale_workers())
        return record, set_status, sends

    def test_going_offline_records_pushes_and_bells(self):
        record, set_status, sends = self._sweep(record_returns=True)
        set_status.assert_awaited_once_with(1, "offline")
        assert record.await_args.args[0] == "worker"
        assert record.await_args.args[1] == "watchtower"
        assert len(sends) == 1
        assert sends[0][1] == "worker" and sends[0][2] == "watchtower"
        assert any(a["kind"] == "worker" and a["platform"] == "watchtower" for a in main._collector_alerts)

    def test_cooldown_dedupes_the_push_but_not_the_bell(self):
        # record_alert False = still inside the cooldown window: no second
        # push, and no duplicate bell entry either.
        main._collector_alerts = [{"kind": "worker", "platform": "watchtower", "error": "x"}]
        record, _, sends = self._sweep(record_returns=False)
        assert record.await_count == 1
        assert sends == []
        assert len([a for a in main._collector_alerts if a["kind"] == "worker"]) == 1

    def test_a_fresh_worker_is_left_alone(self):
        # Negative control: recent heartbeat -> no transition, no alert.
        from datetime import UTC, datetime

        fresh = _worker_row(last_heartbeat=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"))
        record, set_status, sends = self._sweep(record_returns=True, rows=[fresh])
        set_status.assert_not_awaited()
        record.assert_not_awaited()
        assert sends == []
        assert main._collector_alerts == []


class TestBellRebuildDerivesOfflineWorkers:
    def test_offline_workers_are_derived_each_rebuild(self):
        rows = [
            _worker_row(status="offline"),
            _worker_row(id=2, client_id="srv-2", name="geiserback", status="online"),
        ]
        with patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=rows):
            entries = _run(_offline_worker_alerts())
        assert [e["platform"] for e in entries] == ["watchtower"]
        assert entries[0]["kind"] == "worker"

    def test_no_offline_workers_is_empty(self):
        # Negative control — an all-online fleet derives nothing.
        with patch(
            "app.main.database.list_workers",
            new_callable=AsyncMock,
            return_value=[_worker_row(status="online")],
        ):
            assert _run(_offline_worker_alerts()) == []

    def test_a_db_error_degrades_to_empty_not_a_crash(self):
        with patch("app.main.database.list_workers", new_callable=AsyncMock, side_effect=RuntimeError("db gone")):
            assert _run(_offline_worker_alerts()) == []


class TestWarmRestoresWorkerAlerts:
    def test_worker_and_notice_kinds_survive_a_restart(self):
        stored = [
            {"kind": "worker", "subject": "watchtower", "message": "offline", "category": None},
            # A notice dropped here used to skip clear_alerts on recovery
            # inside the warm gap, so its stale row swallowed the next warning.
            {"kind": "notice", "subject": "storj", "message": "unreachable", "category": None},
            {"kind": "bogus", "subject": "x", "message": "y", "category": None},
        ]
        with patch("app.main.database.list_alerts", new_callable=AsyncMock, return_value=stored):
            _run(_warm_collector_alerts())
        kinds = [a["kind"] for a in main._collector_alerts]
        assert "worker" in kinds
        assert "notice" in kinds
        assert "bogus" not in kinds  # negative control: unknown kinds still dropped


class TestRecoveryClears:
    def _heartbeat(self, previous):
        cleared = []

        async def _capture_clear(kind, subject):
            cleared.append((kind, subject))

        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value=False),
            patch("app.main.database.get_worker_status_and_name", new_callable=AsyncMock, return_value=previous),
            patch("app.main.database.upsert_worker", new_callable=AsyncMock, return_value=1),
            patch("app.main.database.clear_alerts", _capture_clear),
            patch("app.main._earnings_for_worker", new_callable=AsyncMock, return_value=None),
        ):
            _run(
                api_worker_heartbeat(
                    _request(),
                    SimpleNamespace(
                        name="watchtower",
                        url="",
                        client_id="srv-1",
                        containers=[],
                        apps=[],
                        system_info={},
                    ),
                )
            )
        return cleared

    def test_recovery_clears_the_alert_and_the_bell(self):
        main._collector_alerts = [
            {"kind": "worker", "platform": "watchtower", "error": "offline"},
            {"kind": "collector", "platform": "honeygain", "error": "kept"},
        ]
        cleared = self._heartbeat(previous=("offline", "watchtower"))
        assert cleared == [("worker", "watchtower")]
        kinds = [(a["kind"], a["platform"]) for a in main._collector_alerts]
        assert ("worker", "watchtower") not in kinds
        assert ("collector", "honeygain") in kinds  # untouched

    def test_an_online_worker_heartbeat_clears_nothing(self):
        # Negative control: no transition, no clearing.
        main._collector_alerts = [{"kind": "worker", "platform": "watchtower", "error": "offline"}]
        cleared = self._heartbeat(previous=("online", "watchtower"))
        assert cleared == []
        assert len(main._collector_alerts) == 1

    def test_a_new_worker_heartbeat_clears_nothing(self):
        assert self._heartbeat(previous=None) == []
