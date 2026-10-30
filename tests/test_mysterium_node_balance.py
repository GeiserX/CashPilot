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
    # Their settlement histories keep a fifth back as fees.
    nodes = [
        {"node": "a", "balance": 1.32, "lifetime": 166.7, "settled_net": 8.0, "settled_fees": 2.0},
        {"node": "b", "balance": 2.54, "lifetime": 245.8, "settled_net": 4.0, "settled_fees": 1.0},
    ]
    _collect_once(EarningsResult(platform="mysterium", balance=3.86, currency="MYST", nodes=nodes))

    with (
        patch("app.main._require_reader", lambda request: None),
        patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=[])),
        patch.object(main.exchange_rates, "to_usd", lambda amount, currency: amount * 0.1),
    ):
        summary = asyncio.run(main.api_earnings_summary(MagicMock()))
    assert summary["paid_out"] == pytest.approx(round((412.5 - 3.86) * 0.8 * 0.1, 2))

    with patch("app.main._require_auth_api", lambda request: None):
        progress = asyncio.run(main.api_payout_progress(MagicMock(), "mysterium"))
    assert progress["current_balance"] == pytest.approx(3.86)
    assert progress["lifetime_earned"] == pytest.approx(412.5)


# --- Review of #526: fees, unread nodes, guards -------------------------------

# Two items of a real GET /transactor/settle/history answer (watchtower, 2026-10-27).
HISTORY = (
    '{"items":[{"tx_hash":"0xd8de","provider_id":"0x55fd4a497237be0591b6c2423cde0e325398b6a8",'
    '"beneficiary":"0x9b3fEa36391651C2621283F6c0269790e15562C4","amount":3943301172065558488,'
    '"settled_at":"2026-10-27T19:55:55Z","fees":1060451925050989623,"is_withdrawal":false,"error":""},'
    '{"tx_hash":"0x1df8","amount":3941398055988733688,"settled_at":"2026-10-22T01:50:02Z",'
    '"fees":1060134234074383422,"is_withdrawal":false,"error":""}],"withdrawal_total":"0","page":1}'
)


def test_the_reader_sums_the_settlement_history_after_the_identity():
    figures = node_read.extract(IDENTITY + "\n" + HISTORY, _reader())
    assert figures["settled_net"] == pytest.approx(3943301172065558488 + 3941398055988733688)
    assert figures["settled_fees"] == pytest.approx(1060451925050989623 + 1060134234074383422)
    # No history (the read failed) is "fee unknown", not "no fee".
    assert "settled_net" not in node_read.extract(IDENTITY, _reader())


def _node(node, balance, lifetime, net=None, fees=None):
    row = {"node": node, "balance": balance, "lifetime": lifetime}
    if net is not None:
        row.update(settled_net=net, settled_fees=fees)
    return row


def test_cashed_out_is_net_of_the_settlement_fee(db):
    # 100 settled gross on each node; their histories keep 20% and 25% back,
    # weighted by how much each settled (300 and 100 in their history).
    nodes = [_node("a", 1.0, 101.0, net=240.0, fees=60.0), _node("b", 2.0, 102.0, net=75.0, fees=25.0)]
    asyncio.run(database.record_node_figures("mysterium", nodes, "MYST"))
    totals = asyncio.run(database.get_node_totals())["mysterium"]
    assert totals["settled_gross"] == pytest.approx(200.0)
    assert totals["settled"] == pytest.approx(200.0 * (1 - 85.0 / 400.0))
    # A later read whose history failed keeps the last one.
    asyncio.run(database.record_node_figures("mysterium", [_node("a", 1.0, 101.0)], "MYST"))
    assert asyncio.run(database.get_node_totals())["mysterium"]["settled"] == pytest.approx(157.5)


def _summary():
    with (
        patch("app.main._require_reader", lambda request: None),
        patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=[])),
        patch.object(main.exchange_rates, "to_usd", lambda amount, currency: amount * 0.1),
    ):
        return asyncio.run(main.api_earnings_summary(MagicMock()))


def test_the_summary_counts_only_what_reached_the_wallet(db):
    nodes = [_node("a", 1.0, 101.0, net=80.0, fees=20.0)]
    _collect_once(EarningsResult(platform="mysterium", balance=1.0, currency="MYST", nodes=nodes))
    summary = _summary()
    assert summary["paid_out"] == pytest.approx(round(100.0 * 0.8 * 0.1, 2))
    assert summary["unpriced_payouts"] == 0


def test_with_no_fee_known_the_gross_settled_is_left_out_and_flagged(db):
    _collect_once(EarningsResult(platform="mysterium", balance=1.0, currency="MYST", nodes=[_node("a", 1.0, 101.0)]))
    summary = _summary()
    assert summary["paid_out"] == 0.0
    assert summary["unpriced_payouts"] == 1


def test_a_payout_confirmed_before_the_node_read_is_not_counted_twice(db):
    asyncio.run(database.record_probable_payout("mysterium", 50.0, "MYST", 0.1))
    pending = asyncio.run(database.get_payouts("mysterium"))
    asyncio.run(database.confirm_payout(pending[0]["id"]))
    nodes = [_node("a", 1.0, 101.0, net=80.0, fees=20.0)]
    _collect_once(EarningsResult(platform="mysterium", balance=1.0, currency="MYST", nodes=nodes))
    # The node's settled total already includes that payout.
    assert _summary()["paid_out"] == pytest.approx(8.0)


def test_a_same_balance_reading_still_moves_the_running_total(db):
    # A settlement that lands exactly on what was earned since the last read.
    asyncio.run(database.upsert_earnings("mysterium", 2.0, "MYST", _day(0), 0.1, earned=1.0))
    asyncio.run(database.upsert_earnings("mysterium", 2.0, "MYST", _day(0), 0.1, earned=3.0))
    assert asyncio.run(database.get_balance_history("mysterium", days=1))[-1]["earned"] == pytest.approx(3.0)


def test_a_node_last_read_long_ago_still_counts(db):
    two = [_node("a", 1.0, 100.0), _node("b", 2.0, 200.0)]
    asyncio.run(database.record_node_figures("mysterium", two, "MYST"))

    async def age_b():
        conn = await database._get_db()
        try:
            await conn.execute("UPDATE node_earnings SET updated_at = datetime('now', '-90 days') WHERE node = 'b'")
            await conn.commit()
        finally:
            await conn.close()

    asyncio.run(age_b())
    totals = asyncio.run(database.record_node_figures("mysterium", [_node("a", 1.0, 100.0)], "MYST"))
    assert totals["balance"] == 3.0 and totals["lifetime"] == 300.0


def _collector(cloud_nodes):
    from app.collectors.mystnodes import MystNodesCollector

    login = MagicMock(status_code=200)
    login.json.return_value = {"accessToken": "at", "refreshToken": "rt"}
    listing = MagicMock(status_code=200)
    listing.json.return_value = {"nodes": cloud_nodes}
    client = MagicMock()
    client.post = AsyncMock(return_value=login)
    client.get = AsyncMock(return_value=listing)
    client.is_closed = False
    client.aclose = AsyncMock()
    return client, MystNodesCollector(email="a@b.c", password="p")


CLOUD = [
    {"identity": "0xAA", "nodeStatus": {"online": True}},
    {"identity": "0xbb", "nodeStatus": {"online": True}},
    {"identity": "0xcc", "nodeStatus": {"online": False}},
]


def test_an_online_node_no_worker_read_is_named_in_a_warning():
    client, c = _collector(CLOUD)
    with patch("app.collectors.mystnodes.httpx.AsyncClient", return_value=client):
        c.node_readings = [_node("0xaa", 1.0, 10.0)]
        result = asyncio.run(c.collect())
    assert result.error is None and result.balance == 1.0
    # 0xbb is online and unread; 0xcc is offline, so it earns nothing to miss.
    assert "0xbb" in result.warning and "0xcc" not in result.warning and "0xaa" not in result.warning


def test_every_node_unread_names_them_and_is_not_a_credential_or_api_problem():
    from app import credential_test

    client, c = _collector(CLOUD)
    with patch("app.collectors.mystnodes.httpx.AsyncClient", return_value=client):
        c.node_readings = []
        result = asyncio.run(c.collect())
    assert result.error and "0xaa" in result.error and "0xbb" in result.error
    assert credential_test.classify(result.error, result.error_kind) == credential_test.OK


def test_the_ui_keeps_the_settlement_sums_and_drops_bad_ones():
    where = {"mysterium": [{"worker_id": 1, "online": True, "android": False, "status": "running"}]}
    answer = {
        "nodes": [
            {"slug": "mysterium", "node": "0xa", "balance": 1.0, "lifetime": 10.0, "settled_net": 8, "settled_fees": 2},
            {
                "slug": "mysterium",
                "node": "0xb",
                "balance": 1.0,
                "lifetime": 10.0,
                "settled_net": -1,
                "settled_fees": 2,
            },
        ]
    }
    with (
        patch.object(main.database, "list_workers", AsyncMock(return_value=[])),
        patch.object(main.placement, "runs_on", return_value=where),
        patch.object(main, "_proxy_to_worker", AsyncMock(return_value=answer)),
    ):
        rows = asyncio.run(main._read_node_figures("mysterium"))
    assert rows == [
        {"node": "0xa", "balance": 1.0, "lifetime": 10.0, "settled_net": 8.0, "settled_fees": 2.0},
        {"node": "0xb", "balance": 1.0, "lifetime": 10.0},
    ]
