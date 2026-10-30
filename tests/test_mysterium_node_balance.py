"""Mysterium's balance and lifetime come from the nodes, not the cloud's 30-day sum (#488).

MystNodes' ``earningsTotal`` is the sum of the last 30 days. Stored as the
balance it rose and fell as days left the window, settlements were invisible,
and lifetime earnings were wrong. Each node's TequilAPI knows the real figures:
``earnings_tokens`` waits to settle, ``earnings_total_tokens`` is everything it
ever earned. The worker reads them inside the node, and the UI keeps one row
per node so a node it missed once still counts.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import catalog, database, main, node_read, payouts
from app.collectors.base import EarningsResult

# A real answer from GET /identities/<id> on one of our nodes (2026-10-30).
IDENTITY = (
    '{"id":"0x55fd4a497237be0591b6c2423cde0e325398b6a8","registration_status":"Registered",'
    '"balance":0,"earnings":1738650251353643259,"earnings_total":167136351806698648922,'
    '"balance_tokens":{"wei":"0","ether":"0","human":"0"},'
    '"earnings_tokens":{"wei":"1738650251353643259","ether":"1.738650251353643259","human":"1.73865"},'
    '"earnings_total_tokens":{"wei":"167136351806698648922","ether":"167.136351806698648922","human":"167.136351"},'
    '"stake":0,"earnings_per_hermes":{"0x80Ed28d84792d8b153bf2F25F0C4B7a1381dE4ab":{'
    '"earnings":{"wei":"1","ether":"9.9","human":"9.9"},"earnings_total":{"wei":"1","ether":"9.9","human":"9.9"}}}}'
)


def _reader():
    return node_read.readers([catalog.get_service("mysterium")])["mysterium"]


def _day(offset: int) -> str:
    return (datetime.now(UTC) + timedelta(days=offset)).strftime("%Y-%m-%d")


@pytest.fixture
def db(tmp_path):
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
        asyncio.run(database.init_db())
        yield


# --- The worker's read ---------------------------------------------------------


def test_the_catalog_reader_takes_the_top_level_figures_of_a_real_identity():
    assert node_read.extract(IDENTITY, _reader()) == {
        "node": "0x55fd4a497237be0591b6c2423cde0e325398b6a8",
        "balance": pytest.approx(1.738650251353643259),
        "lifetime": pytest.approx(167.136351806698648922),
    }


def test_a_partial_or_impossible_answer_is_no_reading():
    reader = _reader()
    assert node_read.extract('{"id":"0x' + "a" * 40 + '"}', reader) is None
    assert node_read.extract("", reader) is None
    # Less ever earned than is waiting to settle cannot be true.
    swapped = IDENTITY.replace('"ether":"167.136351806698648922"', '"ether":"0.5"')
    assert node_read.extract(swapped, reader) is None


def test_a_malformed_declaration_is_ignored():
    services = [
        {
            "slug": "a",
            "collector": {"node_read": {"command": "sh", "node": "(x)", "balance": "(x)", "lifetime": "(x)"}},
        },
        {"slug": "b", "collector": {"node_read": {"command": ["sh"], "node": "(x)", "balance": "(x"}}},
        {
            "slug": "c",
            "collector": {"node_read": {"command": ["sh"], "node": "x", "balance": "(x)", "lifetime": "(x)"}},
        },
    ]
    assert node_read.readers(services) == {}


def test_the_worker_reads_each_running_copy_and_says_why_one_failed():
    good, bad, stopped = MagicMock(status="running"), MagicMock(status="running"), MagicMock(status="exited")
    good.exec_run.return_value = (0, IDENTITY.encode())
    bad.exec_run.return_value = (1, b"wget: can't connect")
    with (
        patch.object(node_read.orchestrator, "service_instances", return_value=[good, bad, stopped]),
        patch.object(node_read.orchestrator, "_instance_of", side_effect=[1, 2]),
    ):
        rows = node_read.read_all([catalog.get_service("mysterium")])
    assert [r["instance"] for r in rows] == [1, 2]
    assert rows[0]["node"].startswith("0x55fd") and "error" not in rows[0]
    assert rows[1]["error"] and "balance" not in rows[1]
    stopped.exec_run.assert_not_called()


def test_the_ui_asks_only_running_copies_and_drops_bad_rows():
    where = {
        "mysterium": [
            {"worker_id": 1, "online": True, "android": False, "status": "running"},
            {"worker_id": 2, "online": False, "android": False, "status": "running"},
            {"worker_id": 3, "online": True, "android": False, "status": "exited"},
        ]
    }
    answer = {
        "nodes": [
            {"slug": "mysterium", "node": "0xa", "balance": 1.0, "lifetime": 10.0},
            {"slug": "mysterium", "node": "0xb", "balance": 5.0, "lifetime": 1.0},
            {"slug": "mysterium", "error": "timed out"},
            {"slug": "anyone-protocol", "node": "0xc", "balance": 1.0, "lifetime": 2.0},
        ]
    }
    proxy = AsyncMock(return_value=answer)
    with (
        patch.object(main.database, "list_workers", AsyncMock(return_value=[])),
        patch.object(main.placement, "runs_on", return_value=where),
        patch.object(main, "_proxy_to_worker", proxy),
    ):
        rows = asyncio.run(main._read_node_figures("mysterium"))
    assert rows == [{"node": "0xa", "balance": 1.0, "lifetime": 10.0}]
    assert [c.args[0] for c in proxy.await_args_list] == [1]


# --- What the UI keeps ---------------------------------------------------------


def test_a_node_first_read_brings_its_lifetime_but_earns_nothing_that_day(db):
    totals = asyncio.run(
        database.record_node_figures("mysterium", [{"node": "a", "balance": 1.3, "lifetime": 166.7}], "MYST")
    )
    assert totals == {"balance": 1.3, "lifetime": 166.7, "earned": 0.0}


def test_a_node_missed_by_one_collection_keeps_counting(db):
    two = [{"node": "a", "balance": 1.0, "lifetime": 100.0}, {"node": "b", "balance": 2.0, "lifetime": 200.0}]
    asyncio.run(database.record_node_figures("mysterium", two, "MYST"))
    totals = asyncio.run(
        database.record_node_figures("mysterium", [{"node": "a", "balance": 1.5, "lifetime": 100.5}], "MYST")
    )
    assert totals == {"balance": 3.5, "lifetime": 300.5, "earned": 0.5}


def test_a_lifetime_never_moves_backwards(db):
    asyncio.run(database.record_node_figures("mysterium", [{"node": "a", "balance": 1.0, "lifetime": 100.0}], "MYST"))
    totals = asyncio.run(
        database.record_node_figures("mysterium", [{"node": "a", "balance": 1.0, "lifetime": 90.0}], "MYST")
    )
    assert totals["lifetime"] == 100.0 and totals["earned"] == 0.0


def test_a_settlement_is_earnings_not_a_drop(db):
    # A node at 4.9 settles 5 MYST and keeps earning: 0.6 then 0.4 more.
    for offset, balance, earned in ((-2, 4.9, 0.0), (-1, 0.5, 0.6), (0, 0.9, 1.0)):
        asyncio.run(database.upsert_earnings("mysterium", balance, "MYST", _day(offset), 0.1, earned=earned))
    earned = asyncio.run(database.get_earned_by_platform(days=30))
    assert earned["mysterium"] == pytest.approx(0.1)
    chart = asyncio.run(database.get_daily_earnings(days=3))
    assert sum(d["amount"] for d in chart) == pytest.approx(0.1)


def test_the_projection_rate_counts_the_settlement_day():
    history = [
        {"date": _day(-2), "balance": 4.9, "earned": 0.0},
        {"date": _day(-1), "balance": 0.5, "earned": 0.6},
        {"date": _day(0), "balance": 0.9, "earned": 1.0},
    ]
    assert payouts.daily_rate(history) == pytest.approx(0.5)


def _collect_once(result: EarningsResult) -> None:
    collector = MagicMock(platform=result.platform)
    with (
        patch.object(main, "_collect_bounded", AsyncMock(return_value=result)),
        patch.object(main, "_attach_node_readings", AsyncMock()),
        patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=[])),
        patch.object(main, "_flatline_check", AsyncMock(return_value=[])),
        patch.object(main, "_offline_worker_alerts", AsyncMock(return_value=[])),
        patch.object(main, "_collector_alerts", []),
        patch.object(main, "_spawn", lambda coro: coro.close()),
        patch.object(main.exchange_rates, "to_usd", lambda amount, currency: amount * 0.1),
        patch("app.collectors.make_collectors", lambda deployments, config: [collector]),
        patch("app.collectors._close_stale", AsyncMock()),
    ):
        asyncio.run(main._run_collection())


def test_the_first_node_reading_after_the_cloud_sum_is_no_payout_and_no_earnings(db):
    # Yesterday's row is the old 30-day sum; today the nodes say 8.65 waits.
    asyncio.run(database.upsert_earnings("mysterium", 112.75, "MYST", _day(-1), 0.1))
    nodes = [
        {"node": "a", "balance": 1.32, "lifetime": 166.7},
        {"node": "b", "balance": 2.54, "lifetime": 245.8},
        {"node": "c", "balance": 4.79, "lifetime": 300.2},
    ]
    _collect_once(EarningsResult(platform="mysterium", balance=8.65, currency="MYST", nodes=nodes))

    assert asyncio.run(database.get_payouts("mysterium")) == []
    assert asyncio.run(database.get_latest_balance("mysterium")) == pytest.approx(8.65)
    assert asyncio.run(database.get_earned_by_platform(days=30))["mysterium"] == 0.0

    # Tomorrow a and b earned 0.1 each; c reached 5 MYST (0.21 more) and settled.
    nodes = [
        {"node": "a", "balance": 1.42, "lifetime": 166.8},
        {"node": "b", "balance": 2.64, "lifetime": 245.9},
        {"node": "c", "balance": 0.0, "lifetime": 300.41},
    ]
    with patch.object(database, "datetime", wraps=datetime) as fake:
        fake.now.side_effect = lambda tz=None: datetime.now(tz) + timedelta(days=1)
        _collect_once(EarningsResult(platform="mysterium", balance=0.0, currency="MYST", nodes=nodes))
    assert asyncio.run(database.get_payouts("mysterium")) == []
    rows = asyncio.run(database.get_balance_history("mysterium", days=30))
    assert rows[-1]["balance"] == pytest.approx(4.06) and rows[-1]["earned"] == pytest.approx(0.41)
    # The balance fell by 4.59, yet the day counts the 0.41 the nodes earned.
    earned = asyncio.run(database.get_earned_by_platform(days=30))["mysterium"]
    assert earned == pytest.approx(0.041)


def test_settlements_count_as_cashed_out_and_lifetime_is_the_nodes(db):
    nodes = [{"node": "a", "balance": 1.32, "lifetime": 166.7}, {"node": "b", "balance": 2.54, "lifetime": 245.8}]
    _collect_once(EarningsResult(platform="mysterium", balance=3.86, currency="MYST", nodes=nodes))

    with (
        patch("app.main._require_reader", lambda request: None),
        patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=[])),
        patch.object(main.exchange_rates, "to_usd", lambda amount, currency: amount * 0.1),
    ):
        summary = asyncio.run(main.api_earnings_summary(MagicMock()))
    assert summary["paid_out"] == pytest.approx(round((412.5 - 3.86) * 0.1, 2))

    with patch("app.main._require_auth_api", lambda request: None):
        progress = asyncio.run(main.api_payout_progress(MagicMock(), "mysterium"))
    assert progress["current_balance"] == pytest.approx(3.86)
    assert progress["lifetime_earned"] == pytest.approx(412.5)
