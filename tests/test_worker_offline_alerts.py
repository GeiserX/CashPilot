"""A worker going offline must be an alert, not a log line.

The 42-hour incident, UI side: two workers stopped heartbeating, the UI marked
them offline in its own database within 3 minutes — and told nobody. The fleet
page was the only witness, and nobody was looking at it. These tests pin the
full lifecycle: transition -> alert row + push + bell, dedupe inside the
cooldown, persistence across a UI restart, and recovery clearing all of it.

Identity is client_id throughout: workers.name is the container hostname —
cosmetic, mutable across recreates, shareable by two hosts — so keying alerts
on it would let one worker suppress or clear another's. The transition write is
conditional on the heartbeat it was decided from, so a recovery landing in the
sweep's read-write gap wins instead of being alerted offline at its exact
moment of coming back.
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
    # The key comes from the environment (set or defaulted above) — never a
    # second copy of the literal, so a CI-provided key keeps these green.
    req = MagicMock()
    req.headers = {"Authorization": f"Bearer {os.environ['CASHPILOT_API_KEY']}"}
    return req


def _worker_row(**over):
    row = {
        "id": 1,
        "client_id": "cid-watchtower",
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
    def _sweep(self, *, record_returns=True, rows=None, transition_wins=True):
        """Run _check_stale_workers over the given worker rows."""
        sends = []

        async def _capture_send(title, message, **kw):
            sends.append((title, kw.get("kind"), kw.get("subject")))
            return 1

        record = AsyncMock(return_value=record_returns)
        mark = AsyncMock(return_value=transition_wins)
        clear = AsyncMock()
        with (
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=rows or [_worker_row()]),
            patch("app.main.database.mark_worker_offline_if_unchanged", mark),
            patch("app.main.database.delete_worker", new_callable=AsyncMock) as delete,
            patch("app.main.database.record_alert", record),
            patch("app.main.database.clear_alerts", clear),
            patch("app.main.notify.send", _capture_send),
        ):
            _run(_check_stale_workers())
        return SimpleNamespace(record=record, mark=mark, clear=clear, delete=delete, sends=sends)

    def test_going_offline_records_pushes_and_bells(self):
        r = self._sweep()
        r.mark.assert_awaited_once_with(1, "2026-04-04T12:00:00")
        assert r.record.await_args.args[0] == "worker"
        assert r.record.await_args.args[1] == "cid-watchtower"  # identity, not the name
        assert "watchtower" in r.record.await_args.args[2]  # the name travels in the message
        assert r.sends == [("CashPilot: worker 'watchtower' went offline", "worker", "cid-watchtower")]
        entry = next(a for a in main._collector_alerts if a["kind"] == "worker")
        assert entry["platform"] == "watchtower"
        assert entry["client_id"] == "cid-watchtower"

    def test_a_recovery_racing_the_sweep_wins(self):
        """The conditional write loses when a heartbeat landed in the gap —
        and then NOTHING may fire: no alert, no push, no bell entry."""
        r = self._sweep(transition_wins=False)
        r.record.assert_not_awaited()
        assert r.sends == []
        assert main._collector_alerts == []

    def test_cooldown_dedupes_the_push_but_not_the_bell(self):
        main._collector_alerts = [
            {"kind": "worker", "platform": "watchtower", "client_id": "cid-watchtower", "error": "x"}
        ]
        r = self._sweep(record_returns=False)
        assert r.sends == []
        assert len([a for a in main._collector_alerts if a["kind"] == "worker"]) == 1

    def test_a_fresh_worker_is_left_alone(self):
        # Negative control: recent heartbeat -> no transition, no alert.
        from datetime import UTC, datetime

        fresh = _worker_row(last_heartbeat=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"))
        r = self._sweep(rows=[fresh])
        r.mark.assert_not_awaited()
        r.record.assert_not_awaited()
        assert main._collector_alerts == []

    def test_a_still_offline_worker_retries_the_durable_alert(self):
        """A record_alert or push that failed at transition time must not be
        lost to the already-offline state — the sweep re-attempts, and the
        record_alert cooldown makes the successful case a cheap no-op."""
        # Enrolled (api_key_enc set): never purge-eligible, however long offline.
        offline = _worker_row(status="offline", api_key_enc="enc")
        r = self._sweep(rows=[offline])
        assert r.record.await_args.args[:2] == ("worker", "cid-watchtower")
        r.delete.assert_not_awaited()

    def test_an_online_worker_with_a_lingering_alert_is_reconciled(self):
        """A recovery clear the heartbeat route missed (it is best-effort so a
        DB hiccup can never fail a heartbeat) is finished by the sweep."""
        from datetime import UTC, datetime

        fresh = _worker_row(last_heartbeat=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"))
        main._collector_alerts = [
            {"kind": "worker", "platform": "watchtower", "client_id": "cid-watchtower", "error": "x"}
        ]
        r = self._sweep(rows=[fresh])
        r.clear.assert_awaited_once_with("worker", "cid-watchtower")
        assert main._collector_alerts == []


class TestBellRebuildDerivesOfflineWorkers:
    def test_offline_workers_are_derived_each_rebuild(self):
        rows = [
            _worker_row(status="offline"),
            _worker_row(id=2, client_id="cid-geiserback", name="geiserback", status="online"),
        ]
        with patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=rows):
            entries = _run(_offline_worker_alerts())
        assert [(e["platform"], e["client_id"]) for e in entries] == [("watchtower", "cid-watchtower")]
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
            # Worker alerts are stored under client_id; the warm pass resolves
            # the display name and keeps the id beside it.
            {"kind": "worker", "subject": "cid-watchtower", "message": "offline", "category": None},
            {"kind": "notice", "subject": "storj", "message": "unreachable", "category": None},
            {"kind": "bogus", "subject": "x", "message": "y", "category": None},
        ]
        with (
            patch("app.main.database.list_alerts", new_callable=AsyncMock, return_value=stored),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[_worker_row()]),
            patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=[]),
        ):
            _run(_warm_collector_alerts())
        by_kind = {a["kind"]: a for a in main._collector_alerts}
        assert by_kind["worker"]["platform"] == "watchtower"  # resolved for display
        assert by_kind["worker"]["client_id"] == "cid-watchtower"  # identity kept
        assert "notice" in by_kind
        assert "bogus" not in by_kind  # negative control: unknown kinds still dropped

    def test_a_deleted_workers_alert_keeps_the_raw_id(self):
        stored = [{"kind": "worker", "subject": "cid-gone", "message": "offline", "category": None}]
        with (
            patch("app.main.database.list_alerts", new_callable=AsyncMock, return_value=stored),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=[]),
        ):
            _run(_warm_collector_alerts())
        entry = next(a for a in main._collector_alerts if a["kind"] == "worker")
        assert entry["platform"] == "cid-gone"  # still actionable, never wrong


class TestRecoveryClears:
    def _heartbeat(self, previous, *, clear_raises=False):
        cleared = []

        async def _capture_clear(kind, subject):
            if clear_raises:
                raise RuntimeError("db locked")
            cleared.append((kind, subject))

        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value=False),
            patch("app.main.database.get_worker_status_and_name", new_callable=AsyncMock, return_value=previous),
            patch("app.main.database.upsert_worker", new_callable=AsyncMock, return_value=1),
            patch("app.main.database.clear_alerts", _capture_clear),
            patch("app.main._earnings_for_worker", new_callable=AsyncMock, return_value=None),
        ):
            result = _run(
                api_worker_heartbeat(
                    _request(),
                    SimpleNamespace(
                        name="watchtower",
                        url="",
                        client_id="cid-watchtower",
                        containers=[],
                        apps=[],
                        system_info={},
                    ),
                )
            )
        return cleared, result

    def test_recovery_clears_the_alert_and_the_bell_by_identity(self):
        main._collector_alerts = [
            {"kind": "worker", "platform": "watchtower", "client_id": "cid-watchtower", "error": "offline"},
            {"kind": "collector", "platform": "honeygain", "error": "kept"},
        ]
        cleared, _ = self._heartbeat(previous=("offline", "watchtower"))
        assert cleared == [("worker", "cid-watchtower")]
        kinds = [(a["kind"], a.get("client_id")) for a in main._collector_alerts]
        assert ("worker", "cid-watchtower") not in kinds
        assert ("collector", None) in kinds  # untouched

    def test_a_failed_clear_never_fails_the_heartbeat(self):
        """Heartbeats are the fleet's lifeline: the clear is best-effort, the
        bell entry stays (memory and disk must not diverge), and the sweep's
        reconciliation finishes the job."""
        main._collector_alerts = [
            {"kind": "worker", "platform": "watchtower", "client_id": "cid-watchtower", "error": "offline"}
        ]
        cleared, result = self._heartbeat(previous=("offline", "watchtower"), clear_raises=True)
        assert result["status"] == "ok"  # the heartbeat itself succeeded
        assert cleared == []
        assert len(main._collector_alerts) == 1  # NOT pruned while the row survives

    def test_an_online_worker_heartbeat_clears_nothing(self):
        # Negative control: no transition, no clearing.
        main._collector_alerts = [
            {"kind": "worker", "platform": "watchtower", "client_id": "cid-watchtower", "error": "offline"}
        ]
        cleared, _ = self._heartbeat(previous=("online", "watchtower"))
        assert cleared == []
        assert len(main._collector_alerts) == 1

    def test_a_new_worker_heartbeat_clears_nothing(self):
        cleared, _ = self._heartbeat(previous=None)
        assert cleared == []
