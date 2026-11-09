"""A node missed because its worker did not answer is not a node that runs nowhere.

Seconds after an upgrade restarted the UI and a worker, the worker answered the
node read with a 503 while it was still starting, and the collector told the
user the node "ran on no CashPilot worker". It had run on that worker all along.
A node a worker has read before is now named as missed, with the worker that
could not be reached; the old notice is kept for nodes no worker ever reported,
and is held back in the first collection after a start while workers settle.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app import credential_test, database, main
from app.collectors.base import KIND_UNREAD
from tests.test_mysterium_node_balance import CLOUD, _collector, _node

NOWHERE = "ran on no CashPilot worker"


def _collect(readings, *, known=(), unreached=(), readers=None, settling=False):
    client, c = _collector(CLOUD)
    with patch("app.collectors.mystnodes.httpx.AsyncClient", return_value=client):
        c.node_readings = readings
        c.known_nodes = set(known)
        c.unreached_workers = list(unreached)
        c.node_readers = dict(readers or {})
        c.workers_settling = settling
        return asyncio.run(c.collect())


# 0xaa is read each time; 0xbb is online and unread; 0xcc is offline.
READ = [_node("0xaa", 1.0, 10.0)]


class TestANodeReadBefore:
    def test_its_unreachable_worker_is_named_not_its_placement(self):
        result = _collect(READ, known={"0xaa", "0xbb"}, unreached=["box-a"], readers={"0xbb": "box-a"})
        assert result.error is None and result.balance == 1.0
        assert "couldn't reach worker box-a to read node 0xbb" in result.warning
        assert "uses its last reading" in result.warning
        assert NOWHERE not in result.warning

    def test_after_a_restart_with_no_reader_known_the_unreached_worker_is_named(self):
        result = _collect(READ, known={"0xbb"}, unreached=["box-a"])
        assert "couldn't reach worker box-a to read node 0xbb" in result.warning

    def test_several_unreached_workers_are_all_named(self):
        result = _collect(READ, known={"0xbb"}, unreached=["box-a", "box-b", "box-a"])
        assert "couldn't reach workers box-a, box-b to read node 0xbb" in result.warning

    def test_its_worker_answered_without_it(self):
        # box-b failed, but 0xbb was last read on box-a, which answered.
        result = _collect(READ, known={"0xbb"}, unreached=["box-b"], readers={"0xbb": "box-a"})
        assert "No worker reported node 0xbb this time, last read on box-a" in result.warning
        assert "couldn't reach" not in result.warning and NOWHERE not in result.warning

    def test_with_every_worker_answering_it_is_only_not_reported(self):
        result = _collect(READ, known={"0xbb"})
        assert result.warning.startswith("No worker reported node 0xbb this time;")

    def test_when_it_was_the_only_node_the_error_names_the_worker_too(self):
        result = _collect([], known={"0xaa", "0xbb"}, unreached=["box-a"])
        assert result.error.startswith("CashPilot couldn't reach worker box-a to read node 0xaa;")
        assert "node 0xbb" in result.error and "No CashPilot worker could read" not in result.error
        assert result.error_kind == KIND_UNREAD
        assert credential_test.classify(result.error, result.error_kind) == credential_test.OK


class TestANodeNoWorkerEverReported:
    def test_keeps_the_notice(self):
        result = _collect(READ, unreached=["box-a"])
        assert NOWHERE in result.warning and "0xbb" in result.warning
        assert "couldn't reach" not in result.warning

    def test_is_held_back_while_workers_settle_after_a_start(self):
        assert _collect(READ, settling=True).warning is None

    def test_a_missed_node_is_still_named_while_they_settle(self):
        result = _collect(READ, known={"0xbb"}, unreached=["box-a"], settling=True)
        assert "couldn't reach worker box-a" in result.warning

    def test_with_nothing_read_a_missed_node_keeps_its_unreached_worker(self):
        # 0xaa was read before on box-a, 0xbb never: the error still names box-a.
        result = _collect([], known={"0xaa"}, unreached=["box-a"])
        assert result.error.startswith("CashPilot couldn't reach worker box-a to read node 0xaa;")
        assert "No CashPilot worker could read" in result.error and "0xbb" in result.error

    def test_with_nothing_read_and_no_node_list_the_unreached_workers_are_named(self):
        client, c = _collector(None)
        with patch("app.collectors.mystnodes.httpx.AsyncClient", return_value=client):
            c.node_readings, c.unreached_workers = [], ["box-a", "box-b"]
            result = asyncio.run(c.collect())
        assert result.error.startswith("CashPilot couldn't reach workers box-a, box-b. No CashPilot worker could read")

    def test_control_with_nothing_read_it_is_still_the_error(self):
        result = _collect([])
        assert result.error.startswith("No CashPilot worker could read")


# --- The UI side --------------------------------------------------------------

WHERE = {
    "mysterium": [
        {"worker_id": 1, "name": "box-a", "online": True, "android": False, "status": "running"},
        {"worker_id": 2, "name": "box-b", "online": True, "android": False, "status": "running"},
    ]
}


def _read(proxy):
    unreached: list[str] = []
    with (
        patch.object(main.database, "list_workers", AsyncMock(return_value=[])),
        patch.object(main.placement, "runs_on", return_value=WHERE),
        patch.object(main, "_proxy_to_worker", proxy),
        patch.dict(main._node_reader, clear=True),
    ):
        rows = asyncio.run(main._read_node_figures("mysterium", unreached))
        readers = dict(main._node_reader)
    return rows, unreached, readers


def test_the_read_names_the_worker_that_did_not_answer_and_who_read_each_node():
    async def proxy(worker_id, *args, **kwargs):
        if worker_id == 2:
            raise main.HTTPException(status_code=503, detail="Worker communication failed")
        return {"nodes": [{"slug": "mysterium", "node": "0xAA", "balance": 1.0, "lifetime": 2.0}]}

    rows, unreached, readers = _read(proxy)
    assert [r["node"] for r in rows] == ["0xAA"]
    assert unreached == ["box-b"]
    assert readers == {"0xaa": "box-a"}


def test_control_every_worker_answering_leaves_none_unreached():
    rows, unreached, _ = _read(AsyncMock(return_value={"nodes": []}))
    assert rows == [] and unreached == []


def _attach(workers, *, collected):
    from app.collectors.mystnodes import MystNodesCollector

    c = MystNodesCollector(email="a@b.c", password="p")
    with (
        patch.object(main, "_read_node_figures", AsyncMock(return_value=[])),
        patch.object(main.database, "get_node_ids", AsyncMock(return_value={"0xbb"})),
        patch.object(main.database, "list_workers", AsyncMock(return_value=workers)),
        patch.object(main, "_collected_since_start", collected),
        patch.object(main, "_PROCESS_STARTED", "2026-11-08 18:50:43"),
    ):
        asyncio.run(main._attach_node_readings(c))
    return c


STALE = {"status": "online", "last_heartbeat": "2026-11-08 18:49:58"}
FRESH = {"status": "online", "last_heartbeat": "2026-11-08 18:51:02"}


class TestTheFirstCollectionAfterAStart:
    def test_a_worker_not_heard_from_since_the_start_holds_the_notice_back(self):
        c = _attach([FRESH, STALE], collected=False)
        assert c.workers_settling is True and c.known_nodes == {"0xbb"}

    def test_once_every_online_worker_has_heartbeated_it_does_not(self):
        assert _attach([FRESH], collected=False).workers_settling is False

    def test_an_offline_worker_does_not_hold_it_back(self):
        assert _attach([FRESH, {**STALE, "status": "offline"}], collected=False).workers_settling is False

    def test_only_the_first_collection(self):
        assert _attach([FRESH, STALE], collected=True).workers_settling is False


@pytest.fixture
def db(tmp_path):
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
        asyncio.run(database.init_db())
        yield


def test_a_failed_history_read_holds_the_never_read_notice_back():
    from app.collectors.mystnodes import MystNodesCollector

    c = MystNodesCollector(email="a@b.c", password="p")
    with (
        patch.object(main, "_read_node_figures", AsyncMock(return_value=[])),
        patch.object(main.database, "get_node_ids", AsyncMock(side_effect=RuntimeError("database is locked"))),
    ):
        asyncio.run(main._attach_node_readings(c))
    assert c.workers_settling is True


def test_a_collection_marks_the_process_as_collected(db):
    with patch.object(main, "_collected_since_start", False):
        asyncio.run(main._run_collection())
        assert main._collected_since_start is True


def test_a_collection_that_aborts_before_its_collectors_keeps_the_settling_hold(db):
    # The retry still runs as the first collection, so a node whose worker has
    # not heartbeated yet is not reported as running on no worker.
    with (
        patch.object(main, "_collected_since_start", False),
        patch.object(main.database, "get_deployments", AsyncMock(side_effect=RuntimeError("database is locked"))),
    ):
        asyncio.run(main._run_collection())
        assert main._collected_since_start is False
        assert main._collection_has_run is True


def test_the_known_nodes_are_every_node_ever_read_for_that_platform(db):
    asyncio.run(database.record_node_figures("mysterium", [_node("0xAA", 1.0, 2.0)], "MYST"))
    asyncio.run(database.record_node_figures("other", [_node("0xdd", 1.0, 2.0)], "X"))
    assert asyncio.run(database.get_node_ids("mysterium")) == {"0xaa"}
