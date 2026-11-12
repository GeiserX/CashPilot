"""A reading stored before rates were recorded gets its own day's price.

Readings taken before the fx_rate_usd column existed have no rate, so every
total left them out: on one install 128 MYST readings, about 225 MYST of
earnings. The backfill fills each from CoinGecko's daily history at the price
of that reading's own day, and never at today's.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app import database, exchange_rates, main

DAY_MS = 86_400_000


def _day(offset: int) -> str:
    """A date ``offset`` days before today, inside CoinGecko's free 365-day window."""
    return (datetime.now(UTC) - timedelta(days=offset)).strftime("%Y-%m-%d")


def _midnight_ms(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC).timestamp() * 1000)


def _history(prices: dict[str, float], now_price: float | None = 99.0) -> dict:
    """CoinGecko's market_chart shape: one 00:00 UTC point per day, then "now"."""
    points = [[_midnight_ms(day), price] for day, price in sorted(prices.items())]
    if now_price is not None:
        points.append([int(datetime.now(UTC).timestamp() * 1000) // DAY_MS * DAY_MS + 12_345_678, now_price])
    return {"prices": points}


def _client(status: int = 200, body: dict | None = None, error: Exception | None = None) -> AsyncMock:
    resp = MagicMock(status_code=status)
    resp.json.return_value = body if body is not None else {}
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(side_effect=error) if error else AsyncMock(return_value=resp)
    return client


@pytest.fixture
def db(tmp_path):
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
        asyncio.run(database.init_db())
        yield


def _rate(platform: str, date: str, source: str = "server") -> float | None:
    async def read():
        conn = await database._get_db()
        cursor = await conn.execute(
            "SELECT fx_rate_usd FROM earnings WHERE platform = ? AND date = ? AND source = ?",
            (platform, date, source),
        )
        return (await cursor.fetchone())[0]

    return asyncio.run(read())


def _backfill(client: AsyncMock) -> None:
    with patch("app.exchange_rates.httpx.AsyncClient", return_value=client):
        asyncio.run(main._run_rate_backfill())


def test_a_null_myst_reading_gets_the_price_of_its_own_day(db, caplog):
    d1, d2 = _day(30), _day(29)
    asyncio.run(database.upsert_earnings("mysterium", 10.0, "MYST", date=d1))
    client = _client(body=_history({_day(31): 0.10, d1: 0.20, d2: 0.30}))
    with caplog.at_level(logging.INFO, logger="app.main"):
        _backfill(client)
    assert _rate("mysterium", d1) == pytest.approx(0.20)
    url = client.get.await_args.args[0]
    assert url.endswith("/coins/mysterium/market_chart")
    assert client.get.await_args.kwargs["params"]["days"] == 365
    assert "1 readings" in caplog.text and "MYST" in caplog.text


def test_the_trailing_now_point_never_prices_a_day(db):
    today = _day(0)
    asyncio.run(database.upsert_earnings("mysterium", 10.0, "MYST", date=today))
    _backfill(_client(body=_history({_day(1): 0.20}, now_price=0.50)))
    assert _rate("mysterium", today) is None


def test_a_rate_a_collector_stored_is_left_alone(db):
    d = _day(10)
    asyncio.run(database.upsert_earnings("mysterium", 10.0, "MYST", date=d, fx_rate_usd=0.15))
    # A second MYST series on the same day with no rate, so MYST is looked up
    # and the same day's price is written beside the stored one.
    asyncio.run(database.upsert_earnings("mysterium", 9.0, "MYST", date=d, source="laptop"))
    _backfill(_client(body=_history({d: 0.40})))
    assert _rate("mysterium", d, "server") == pytest.approx(0.15)
    assert _rate("mysterium", d, "laptop") == pytest.approx(0.40)


def test_grass_and_usd_are_never_looked_up(db):
    d = _day(5)
    asyncio.run(database.upsert_earnings("grass", 500.0, "GRASS", date=d))
    asyncio.run(database.upsert_earnings("earnapp", 4.0, "USD", date=d))
    client = _client(body=_history({d: 0.40}))
    _backfill(client)
    client.get.assert_not_awaited()
    assert _rate("grass", d) is None
    assert _rate("earnapp", d) is None


def test_no_request_when_nothing_is_missing(db):
    asyncio.run(database.upsert_earnings("mysterium", 10.0, "MYST", date=_day(3), fx_rate_usd=0.2))
    client = _client(body=_history({}))
    with patch("app.exchange_rates.httpx.AsyncClient", return_value=client) as made:
        asyncio.run(main._run_rate_backfill())
    made.assert_not_called()


def test_a_day_without_a_price_stays_null(db):
    priced, unpriced = _day(20), _day(19)
    asyncio.run(database.upsert_earnings("mysterium", 10.0, "MYST", date=priced))
    asyncio.run(database.upsert_earnings("mysterium", 11.0, "MYST", date=unpriced))
    _backfill(_client(body=_history({priced: 0.20, _day(18): 0.25})))
    assert _rate("mysterium", priced) == pytest.approx(0.20)
    assert _rate("mysterium", unpriced) is None


@pytest.mark.parametrize(
    "client",
    [
        _client(status=429),
        _client(status=500),
        _client(error=httpx.ConnectTimeout("")),
        _client(body={"error": "no prices key"}),
        _client(body={"prices": [["not a number", 1.0]]}),
    ],
    ids=["429", "500", "timeout", "no-prices", "garbage-point"],
)
def test_a_failed_fetch_leaves_everything_null_and_does_not_raise(db, client, caplog):
    d = _day(7)
    asyncio.run(database.upsert_earnings("mysterium", 10.0, "MYST", date=d))
    with caplog.at_level(logging.WARNING, logger="app.exchange_rates"):
        _backfill(client)
    assert _rate("mysterium", d) is None
    assert "rate history for MYST" in caplog.text


@pytest.mark.parametrize("bad", [0.0, -0.2, math.nan, math.inf])
def test_a_price_that_is_not_a_price_is_not_written(db, bad):
    d = _day(7)
    asyncio.run(database.upsert_earnings("mysterium", 10.0, "MYST", date=d))
    _backfill(_client(body=_history({d: bad})))
    assert _rate("mysterium", d) is None


def test_a_payout_is_priced_by_the_day_it_landed(db):
    landed, other = _day(40), _day(41)
    asyncio.run(database.add_manual_payout("mysterium", 50.0, "MYST", None, "wallet", landed))
    assert asyncio.run(database.count_unpriced_confirmed_payouts()) == 1
    _backfill(_client(body=_history({other: 0.10, landed: 0.30})))
    assert asyncio.run(database.count_unpriced_confirmed_payouts()) == 0
    assert asyncio.run(database.get_confirmed_payout_totals()) == {"mysterium": pytest.approx(15.0)}


def test_a_total_that_left_the_readings_out_now_includes_them(db):
    d1, d2 = _day(60), _day(59)
    asyncio.run(database.upsert_earnings("mysterium", 100.0, "MYST", date=d1))
    asyncio.run(database.upsert_earnings("mysterium", 110.0, "MYST", date=d2))
    before = asyncio.run(database.get_earned_by_platform(days=365))
    assert before["mysterium"] == 0.0
    _backfill(_client(body=_history({d1: 0.20, d2: 0.30})))
    after = asyncio.run(database.get_earned_by_platform(days=365))
    # 10 MYST earned on d2, priced at d2's own rate.
    assert after["mysterium"] == pytest.approx(3.0)


def test_a_database_failure_is_logged_not_raised(caplog):
    with (
        patch.object(database, "currencies_missing_rates", AsyncMock(side_effect=RuntimeError("locked"))),
        caplog.at_level(logging.WARNING, logger="app.main"),
    ):
        asyncio.run(main._run_rate_backfill())
    assert "Rate backfill error: locked" in caplog.text


def test_an_unknown_currency_asks_nothing():
    with patch("app.exchange_rates.httpx.AsyncClient") as made:
        assert asyncio.run(exchange_rates.fetch_daily_usd_prices("GRASS")) == {}
    made.assert_not_called()


def test_the_backfill_runs_at_startup_and_daily():
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(main.lifespan.__wrapped__)))
    spawned = {
        node.args[0].func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "_spawn"
        and isinstance(node.args[0], ast.Call)
        and isinstance(node.args[0].func, ast.Name)
    }
    assert "_run_rate_backfill" in spawned
    jobs = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", None) == "add_job"
        and getattr(node.args[0], "id", None) == "_run_rate_backfill"
    ]
    assert len(jobs) == 1


def test_no_currency_asked_means_no_query(db):
    assert asyncio.run(database.currencies_missing_rates([])) == set()


def test_a_failed_write_rolls_back_and_frees_the_lock(db):
    d = _day(7)
    asyncio.run(database.upsert_earnings("mysterium", 10.0, "MYST", date=d))

    async def break_payouts():
        conn = await database._get_db()
        await conn.execute("ALTER TABLE payouts RENAME TO payouts_gone")
        await conn.commit()

    asyncio.run(break_payouts())
    with pytest.raises(Exception, match="payouts"):
        asyncio.run(database.fill_missing_rates("MYST", {d: 0.2}))
    # The earnings half of the write was undone, and the next write is not blocked.
    assert _rate("mysterium", d) is None
    asyncio.run(database.upsert_earnings("mysterium", 11.0, "MYST", date=_day(6)))
