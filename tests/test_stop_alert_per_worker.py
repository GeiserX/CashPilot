"""A stop made from the dashboard keeps that box quiet, whatever happens to the service elsewhere.

The "has stopped running" alert looked up the latest start/stop/restart/remove
of the service, not of the service on that worker: starting the same service
on another box re-armed the alert for a copy the user had stopped on purpose,
and a stop only explained an exit within ten minutes of it. The action is now
recorded with its worker and read per worker, and a stop stays quiet for as
long as it is the latest action CashPilot sent there.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

from app import database, main
from tests.test_container_down_alert import _ago, _Alerts, _entry


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.setattr(main, "_container_first_seen_down", {})
    monkeypatch.setattr(main, "_container_down_bell", {})
    monkeypatch.setattr(main, "_collector_alerts", [])


def _when(**kw) -> str:
    return (datetime.now(UTC) - timedelta(**kw)).strftime("%Y-%m-%d %H:%M:%S")


class _PerWorker(_Alerts):
    """Lifecycle events by worker, as the per-worker lookup returns them."""

    def __init__(self, events):
        super().__init__()
        self.events = events
        self.asked: list[tuple[str, object]] = []

    def run(self, statuses):
        async def last(slug, worker_id, instance=1):
            self.asked.append((slug, worker_id))
            return self.events.get((worker_id, instance), self.events.get(worker_id))

        def spawn(coro):
            coro.close()
            self.pushed.append("push")

        with (
            patch.object(main.database, "record_alert", self.record),
            patch.object(main.database, "get_alert_subjects", self.subjects),
            patch.object(main.database, "clear_alerts", self.clear),
            patch.object(main.database, "get_last_lifecycle_event", last),
            patch.object(main, "_spawn", spawn),
        ):
            asyncio.run(main._container_down_check(statuses))


DOWN = {"finished_at": _ago(hours=3), "exit_code": 0}


class TestTheStopIsPerWorker:
    def test_a_start_on_another_box_does_not_rearm_a_stopped_copy(self):
        alerts = _PerWorker({1: ("stop", _when(hours=4)), 2: ("start", _when(minutes=5))})
        alerts.run([_entry(worker_id=1, node="alpha", **DOWN), _entry("running", worker_id=2, node="bravo")])
        assert not alerts.rows
        assert ("urnetwork", 1) in alerts.asked

    def test_a_copy_stopped_outside_cashpilot_still_alerts_beside_one_stopped_here(self):
        alerts = _PerWorker({1: ("stop", _when(hours=4)), 2: ("start", _when(days=1))})
        alerts.run([_entry(worker_id=1, node="alpha", **DOWN), _entry(worker_id=2, node="bravo", **DOWN)])
        message = alerts.rows["urnetwork"]
        assert "bravo" in message and "alpha" not in message

    def test_a_removal_from_cashpilot_is_quiet_too(self):
        alerts = _PerWorker({1: ("remove", _when(hours=4))})
        alerts.run([_entry(worker_id=1, **DOWN)])
        assert not alerts.rows

    def test_control_with_no_action_recorded_a_docker_stop_alerts(self):
        alerts = _PerWorker({})
        alerts.run([_entry(worker_id=1, **DOWN)])
        assert "urnetwork" in alerts.rows


class TestTheStopIsPerCopy:
    def test_a_stop_of_copy_one_does_not_hide_a_crash_of_copy_two_on_the_same_box(self):
        alerts = _PerWorker({(1, 1): ("stop", _when(hours=4))})
        alerts.run(
            [
                _entry(worker_id=1, instance=1, **DOWN),
                {**_entry(worker_id=1, instance=2, node="alpha-2", **DOWN), "name": "cashpilot-urnetwork-2"},
            ]
        )
        assert "alpha-2" in alerts.rows["urnetwork"]

    def test_control_each_copy_stopped_here_is_quiet(self):
        alerts = _PerWorker({(1, 1): ("stop", _when(hours=4)), (1, 2): ("stop", _when(hours=4))})
        alerts.run(
            [
                _entry(worker_id=1, instance=1, **DOWN),
                {**_entry(worker_id=1, instance=2, **DOWN), "name": "cashpilot-urnetwork-2"},
            ]
        )
        assert not alerts.rows


class TestTheAlertClearsByCause:
    def test_stopping_an_alerted_copy_from_the_dashboard_clears_it(self, caplog):
        alerts = _PerWorker({1: ("stop", _when(minutes=1))})
        alerts.rows["urnetwork"] = "raised for a docker stop"
        with caplog.at_level(logging.INFO, logger="app.main"):
            alerts.run([_entry(worker_id=1, **DOWN)])
        assert not alerts.rows
        assert "urnetwork was stopped or removed from CashPilot; cleared" in caplog.text

    def test_running_again_says_so(self, caplog):
        alerts = _PerWorker({})
        alerts.rows["urnetwork"] = "raised"
        with caplog.at_level(logging.INFO, logger="app.main"):
            alerts.run([_entry("running")])
        assert "urnetwork is running again" in caplog.text

    def test_a_removed_service_is_not_called_running_again(self, caplog):
        alerts = _PerWorker({})
        alerts.rows["urnetwork"] = "raised"
        with caplog.at_level(logging.INFO, logger="app.main"):
            alerts.run([])
        assert not alerts.rows
        assert "running again" not in caplog.text
        assert "urnetwork is no longer listed on any worker" in caplog.text

    def test_control_a_copy_not_stopped_here_keeps_the_alert(self):
        alerts = _PerWorker({1: ("stop", _when(hours=4))})
        alerts.rows["urnetwork"] = "raised"
        alerts.run([_entry(worker_id=1, **DOWN), _entry(worker_id=2, node="bravo", finished_at=_ago(minutes=5))])
        assert "urnetwork" in alerts.rows


def test_the_alert_says_a_dashboard_stop_keeps_it_quiet():
    alerts = _PerWorker({})
    alerts.run([_entry(**DOWN)])
    message = alerts.rows["urnetwork"]
    assert message.endswith("stop it from the dashboard too: a stop made there keeps this alert quiet.")
    assert "remove it if you stopped it on purpose" not in message


def test_a_fenced_node_says_the_same():
    with patch.object(main.catalog, "fence_gated", return_value=True):
        message = main._container_down_message("mysterium", [_entry(slug="mysterium", _down_since=datetime.now(UTC))])
    assert "stop it from the dashboard, which keeps this alert quiet" in message


# --- Recording and reading the worker ------------------------------------------


@pytest.fixture
def db(tmp_path):
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
        asyncio.run(database.init_db())
        yield tmp_path / "cashpilot.db"


def test_the_latest_action_is_read_per_worker(db):
    async def go():
        await database.record_health_event("urnetwork", "stop", worker_id=1)
        await database.record_health_event("urnetwork", "start", worker_id=2)
        await database.record_health_event("urnetwork", "check_ok")
        return (
            await database.get_last_lifecycle_event("urnetwork", 1),
            await database.get_last_lifecycle_event("urnetwork", 2),
            await database.get_last_lifecycle_event("urnetwork", 3),
        )

    one, two, three = asyncio.run(go())
    assert one[0] == "stop" and two[0] == "start" and three is None


def test_the_latest_action_is_read_per_copy_and_a_deploy_counts_for_each(db):
    async def go():
        await database.record_health_event("urnetwork", "stop", worker_id=1, instance=1)
        await database.record_health_event("urnetwork", "start", worker_id=1, instance=2)
        first = await database.get_last_lifecycle_event("urnetwork", 1, 1)
        second = await database.get_last_lifecycle_event("urnetwork", 1, 2)
        await database.record_health_event("urnetwork", "start", "deployed", worker_id=1)
        return first, second, await database.get_last_lifecycle_event("urnetwork", 1, 1)

    first, second, after_deploy = asyncio.run(go())
    assert first[0] == "stop" and second[0] == "start" and after_deploy[0] == "start"


def test_a_deploy_records_each_copys_start_before_deploying_it():
    # An extra copy that fails must not leave an older stop as its latest action,
    # and a copy the deploy never reaches must keep its own.
    source = (Path(main.__file__)).read_text(encoding="utf-8")
    body = source[source.index("async def api_deploy(") :]
    body = body[: body.index("\n@app.")]
    loop = body[body.index("for n in range(2, instances + 1):") :]
    assert loop.index("instance=n") < loop.index("await _proxy_worker_deploy(worker_id, slug, _instance_spec(")
    starts = re.findall(r'record_health_event\(\s*slug, "start"[^)]*\)', body)
    assert len(starts) == 2 and all("instance=" in call for call in starts), "a deploy records a start per copy"


def test_a_row_from_before_the_worker_was_recorded_counts_for_every_worker(db):
    async def go():
        await database.record_health_event("urnetwork", "stop")
        return await database.get_last_lifecycle_event("urnetwork", 7)

    assert asyncio.run(go())[0] == "stop"


def test_an_existing_database_gets_the_columns(tmp_path):
    path = tmp_path / "cashpilot.db"

    async def go():
        # The table as an earlier version created it, with a stop already recorded.
        async with aiosqlite.connect(path) as conn:
            await conn.execute(
                "CREATE TABLE health_events (id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT NULL, "
                "event TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', "
                "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
            )
            await conn.execute("INSERT INTO health_events (slug, event) VALUES ('urnetwork', 'stop')")
            await conn.commit()
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", path):
            await database.init_db()
            async with aiosqlite.connect(path) as conn:
                cursor = await conn.execute("PRAGMA table_info(health_events)")
                cols = {row[1] for row in await cursor.fetchall()}
            return cols, await database.get_last_lifecycle_event("urnetwork", 1)

    cols, last = asyncio.run(go())
    assert {"worker_id", "instance"} <= cols and last[0] == "stop"


@pytest.mark.parametrize(
    ("call", "event"),
    [
        (lambda r: main._svc_stop(r, "urnetwork", 4), "stop"),
        (lambda r: main._svc_restart(r, "urnetwork", 4), "restart"),
        (lambda r: main.api_service_start(r, "urnetwork", 4), "start"),
    ],
)
def test_each_dashboard_action_records_its_worker(call, event):
    record = AsyncMock()
    with (
        patch.object(main, "_require_writer", lambda r: None),
        patch.object(main, "_resolve_worker_id", AsyncMock(return_value=4)),
        patch.object(main, "_proxy_worker_command", AsyncMock(return_value={})),
        patch.object(main.database, "record_health_event", record),
    ):
        asyncio.run(call(MagicMock()))
    record.assert_awaited_once_with("urnetwork", event, worker_id=4, instance=1)


def test_a_removal_records_its_worker():
    record = AsyncMock()
    with (
        patch.object(main, "_require_writer", lambda r: None),
        patch.object(main, "_resolve_worker_id", AsyncMock(return_value=4)),
        patch.object(main, "_proxy_worker_command", AsyncMock(return_value={})),
        patch.object(main.database, "remove_deployment", AsyncMock()),
        patch.object(main.database, "delete_proxied_copies_of", AsyncMock()),
        patch.object(main.database, "record_health_event", record),
    ):
        asyncio.run(main._svc_remove(MagicMock(), "urnetwork", 4, False))
    record.assert_awaited_once_with("urnetwork", "remove", worker_id=4)


@pytest.mark.parametrize("event", ["stop", "restart", "start"])
def test_the_raw_worker_command_records_the_first_copy(event):
    # The worker's plain container route acts on copy 1, so the action names it.
    record = AsyncMock()
    with (
        patch.object(main, "_require_writer", lambda r: None),
        patch.object(main, "_proxy_to_worker", AsyncMock(return_value={})),
        patch.object(main.database, "record_health_event", record),
    ):
        asyncio.run(main.api_worker_command(MagicMock(), 4, main.WorkerCommand(command=event, slug="urnetwork")))
    record.assert_awaited_once_with("urnetwork", event, worker_id=4, instance=1)


def test_an_unreadable_copy_number_still_alerts():
    # Copy 1 was stopped; an entry whose copy cannot be read must not hide behind that.
    alerts = _PerWorker({(1, 1): ("stop", _when(hours=4))})
    alerts.run([_entry(worker_id=1, instance="junk", **DOWN)])
    assert len(alerts.rows) == 1


@pytest.mark.parametrize(("spec", "copy"), [({"image": "x", "instance": 2}, 2), ({"image": "x"}, 1)])
def test_the_raw_deploy_records_the_copy_it_deployed(spec, copy):
    record = AsyncMock()
    with (
        patch.object(main, "_require_owner", lambda r: None),
        patch.object(main, "_proxy_to_worker", AsyncMock(return_value={"container_id": "c"})),
        patch.object(main.database, "save_deployment", AsyncMock()),
        patch.object(main.database, "record_health_event", record),
        patch.object(main, "_spawn", lambda coro: coro.close()),
    ):
        asyncio.run(
            main.api_worker_command(MagicMock(), 4, main.WorkerCommand(command="deploy", slug="urnetwork", spec=spec))
        )
    record.assert_awaited_once_with("urnetwork", "start", "deployed to worker 4", worker_id=4, instance=copy)


def test_a_fractional_copy_number_still_alerts():
    alerts = _PerWorker({(1, 1): ("stop", _when(hours=4))})
    alerts.run([_entry(worker_id=1, instance=1.5, **DOWN)])
    assert len(alerts.rows) == 1


@pytest.mark.parametrize("command", ["start", "restart"])
@pytest.mark.parametrize(("status", "recorded"), [(504, True), (503, False), (409, False)])
def test_a_start_the_worker_may_have_done_unanswered_is_recorded(command, status, recorded):
    # 504: the worker got it and may have done it. 503 never reached it; 409 refused.
    record = AsyncMock()
    with (
        patch.object(main, "_proxy_worker_command", AsyncMock(side_effect=main.HTTPException(status_code=status))),
        patch.object(main.database, "record_health_event", record),
        pytest.raises(main.HTTPException),
    ):
        asyncio.run(main._command_and_record(4, command, "urnetwork", 2))
    if recorded:
        record.assert_awaited_once_with("urnetwork", command, worker_id=4, instance=2)
    else:
        record.assert_not_awaited()


@pytest.mark.parametrize("command", ["stop", "restart", "remove"])
def test_a_stop_waits_as_long_as_the_service_takes_to_stop(command):
    # storj stops in up to 300 s; cut off at 30 s, a stop that went through
    # answers 504, is never recorded, and the stopped copy raises an alert.
    call = AsyncMock(return_value={})
    with (
        patch.object(main.catalog, "get_service", lambda slug: {"docker": {"stop_timeout": 300}}),
        patch.object(main, "_proxy_to_worker", call),
    ):
        asyncio.run(main._proxy_worker_command(4, command, "storj"))
    assert call.call_args.kwargs["timeout"] > 300


@pytest.mark.parametrize(("raw", "seconds"), [(300, 300), (0, 30), (-5, 30), (None, 30), ("junk", 30)])
def test_the_stop_timeout_is_read_as_the_worker_reads_it(raw, seconds):
    from app import orchestrator

    with patch.object(main.catalog, "get_service", lambda slug: {"docker": {"stop_timeout": raw}}):
        assert main._catalog_stop_timeout("x") == seconds == orchestrator._parse_stop_timeout(raw)
