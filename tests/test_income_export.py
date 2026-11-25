"""Exercise the owner download and its source data on real SQLite."""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import Request
from fastapi.responses import StreamingResponse

from app import auth, catalog, database, exchange_rates, income_export, main

pytestmark = pytest.mark.asyncio
EXPORT = "/api/earnings/income.csv"
EARLIER = "2025-11-13"
SATURDAY = "2025-11-15"
MONDAY = "2025-11-17"


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    # The URI must work even when a local data directory contains URI punctuation.
    data = tmp_path / "data #1"
    monkeypatch.setattr(database, "DB_DIR", data)
    monkeypatch.setattr(database, "DB_PATH", data / "cashpilot.db")
    await database.init_db()
    yield database
    await database.close_shared()


@pytest_asyncio.fixture
async def client(db):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app),
        base_url="http://test",
        cookies={auth.SESSION_COOKIE: auth.create_session_token(1, "owner", "owner")},
    ) as client:
        yield client


def csv_rows(response: httpx.Response) -> list[dict[str, str]]:
    assert response.status_code == 200, response.text
    return list(csv.DictReader(StringIO(response.text)))


async def test_owner_download_headers_and_audit(client, db):
    response = await client.get(EXPORT, params={"start": EARLIER, "end": MONDAY})
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert (
        response.headers["content-disposition"] == f'attachment; filename="cashpilot-income-{EARLIER}_{MONDAY}-USD.csv"'
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.content == (",".join(income_export.HEADER) + "\r\n").encode()
    assert response.text.splitlines()[0] == (
        "date,period_start,kind,service,coin,amount,usd_rate,usd_value,local_currency,local_rate,local_value,method"
    )
    (event,) = await db.get_audit_events()
    assert (event["action"], event["target"], event["outcome"], event["actor"], event["detail"]) == (
        "income_export",
        f"{EARLIER}..{MONDAY}",
        "exported",
        "owner",
        "USD",
    )


@pytest.mark.parametrize(
    ("credential", "status"),
    [("anonymous", 401), ("viewer", 403), ("writer", 403), ("reader", 403), ("fleet", 403), ("admin", 200)],
)
async def test_export_auth(db, monkeypatch, credential, status):
    monkeypatch.setenv("CASHPILOT_READONLY_API_KEY", "test-reader")
    monkeypatch.setenv("CASHPILOT_ADMIN_API_KEY", "test-admin")
    monkeypatch.setattr(auth._fleet_key_mod, "resolve_fleet_key", lambda: "test-fleet")
    headers, cookies = {}, {}
    if credential in {"reader", "fleet", "admin"}:
        headers["Authorization"] = f"Bearer test-{credential}"
    if credential in {"viewer", "writer"}:
        cookies[auth.SESSION_COOKIE] = auth.create_session_token(2, credential, credential)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://test", headers=headers, cookies=cookies
    ) as client:
        response = await client.get(EXPORT, params={"start": EARLIER, "end": MONDAY})
    assert response.status_code == status


async def test_blank_dates_use_oldest_income_and_today(client, db):
    assert await db.oldest_income_date() is None
    await db.upsert_earnings("honeygain", 10, date=SATURDAY)
    await db.add_manual_payout("mysterium", 1, paid_on=EARLIER)
    response = await client.get(EXPORT, params={"start": "", "end": ""})
    assert csv_rows(response)[0]["kind"] == "payout"
    today = datetime.now(UTC).date().isoformat()
    assert response.headers["content-disposition"].endswith(f'{EARLIER}_{today}-USD.csv"')


async def test_export_explains_history_limits(client):
    response = await client.get("/payouts")
    assert response.status_code == 200
    assert "Older earnings readings may have been deleted. A past year can be incomplete." in response.text

    guide = (Path(__file__).resolve().parents[1] / "docs" / "income-export.md").read_text()
    assert f"{database.RETENTION_DAYS} days after recording them" in guide
    assert "If more than one source reads the same account, the CSV can count that income more than once." in guide


async def test_baseline_clamp_and_start_filter(client, db):
    dates = [EARLIER, SATURDAY, "2025-11-16", MONDAY]
    for value, day in zip([10, 15, 3, 4], dates, strict=True):
        await db.upsert_earnings("honeygain", value, date=day)
    await db.upsert_earnings("honeygain", 99, date="2025-11-18")
    rows = csv_rows(await client.get(EXPORT, params={"start": SATURDAY, "end": MONDAY}))
    assert [(r["period_start"], r["date"], r["amount"]) for r in rows] == [
        (EARLIER, SATURDAY, "5"),
        ("2025-11-16", MONDAY, "1"),
    ]
    assert csv_rows(await client.get(EXPORT, params={"end": EARLIER})) == []


async def test_running_total_and_two_sources(client, db):
    await db.upsert_earnings("mysterium", 10, "MYST", EARLIER, 0.5, source="desktop", earned=20)
    await db.upsert_earnings("mysterium", 4, "MYST", EARLIER, 0.5, earned=40)
    await db.upsert_earnings("mysterium", 2, "MYST", MONDAY, 0.5, source="desktop", earned=25)
    await db.upsert_earnings("mysterium", 7, "MYST", SATURDAY, 0.5, earned=43)
    rows = csv_rows(await client.get(EXPORT))
    assert [(r["service"], r["date"], r["coin"], r["amount"], r["usd_value"]) for r in rows] == [
        ("mysterium", SATURDAY, "MYST", "3", "1.5"),
        ("mysterium", MONDAY, "MYST", "5", "2.5"),
    ]


async def test_unpriced_steps_and_accrual(client, db):
    assert catalog.get_service("ocean")["collector"]["accrual"] == "pool"
    await db.upsert_earnings("ocean", 0.001, "BTC", EARLIER)
    await db.upsert_earnings("ocean", 0.00112345, "BTC", SATURDAY, 100_000)
    for slug, currency in [("unpriced-pool", "KAS"), ("grass", "GRASS")]:
        for day, amount, rate in [(EARLIER, 10, None), (SATURDAY, 12.5, None), (MONDAY, 13, 0.5)]:
            await db.upsert_earnings(slug, amount, currency, day, rate)

    accrued, unpriced, priced = csv_rows(await client.get(EXPORT))
    assert (accrued["kind"], accrued["amount"], accrued["usd_value"]) == ("accrued", "0.00012345", "12.345")
    assert (unpriced["kind"], unpriced["amount"], unpriced["coin"]) == ("earned", "2.5", "KAS")
    assert (unpriced["usd_rate"], unpriced["usd_value"], unpriced["local_rate"], unpriced["local_value"]) == (
        "",
        "",
        "1",
        "",
    )
    assert (priced["period_start"], priced["amount"], priced["usd_value"]) == (SATURDAY, "0.5", "0.25")


async def test_only_confirmed_payouts_with_recorded_dates_and_rates(client, db):
    await db.add_manual_payout("mysterium", 8, "MYST", 0.25, "crypto", MONDAY)
    await db.add_manual_payout("ocean", 0.00012345, "BTC", None, "wallet", EARLIER)
    await db.add_manual_payout("honeygain", 12.5, "USD", 9, "card", SATURDAY)
    await db.record_probable_payout("earnapp", 99)
    rows = csv_rows(await client.get(EXPORT))
    assert [r["date"] for r in rows] == [EARLIER, SATURDAY, MONDAY]
    assert all(r["period_start"] == "" and r["kind"] == "payout" for r in rows)
    assert [(r["coin"], r["amount"], r["usd_rate"], r["usd_value"], r["method"]) for r in rows] == [
        ("BTC", "0.00012345", "", "", "wallet"),
        ("USD", "12.5", "1", "12.5", "card"),
        ("MYST", "8", "0.25", "2", "crypto"),
    ]


async def test_earnings_and_payouts_share_one_date_order(client, db):
    await db.upsert_earnings("earnapp", 10, date=EARLIER)
    await db.upsert_earnings("earnapp", 12, date=MONDAY)
    await db.upsert_earnings("honeygain", 20, date=EARLIER)
    await db.upsert_earnings("honeygain", 23, date=SATURDAY)
    sunday = "2025-11-16"
    await db.add_manual_payout("earnapp", 4, paid_on=sunday)
    await db.add_manual_payout("honeygain", 5, paid_on=EARLIER)

    rows = csv_rows(await client.get(EXPORT, params={"start": EARLIER, "end": MONDAY}))
    assert [(r["date"], r["kind"], r["service"]) for r in rows] == [
        (EARLIER, "payout", "honeygain"),
        (SATURDAY, "earned", "honeygain"),
        (sunday, "payout", "earnapp"),
        (MONDAY, "earned", "earnapp"),
    ]


async def test_cointracking_example_maps_a_payout(client, db):
    await db.add_manual_payout("mysterium", 8, "MYST", 0.25, "crypto", MONDAY)
    (payout,) = csv_rows(await client.get(EXPORT))

    guide = (Path(__file__).resolve().parents[1] / "docs" / "income-export.md").read_text()
    cointracking = guide.split("### CoinTracking", 1)[1]
    example = cointracking.split("```csv\n", 1)[1].split("\n```", 1)[0]
    (row,) = csv.DictReader(StringIO(example))
    assert row == {
        "Type": "Income",
        "Buy Amount": payout["amount"],
        "Buy Currency": payout["coin"],
        "Sell Amount": "",
        "Sell Currency": "",
        "Fee": "",
        "Fee Currency": "",
        "Exchange": "",
        "Trade-Group": "",
        "Comment": payout["service"],
        "Date": datetime.fromisoformat(payout["date"]).strftime("%d.%m.%Y %H:%M:%S"),
    }


async def test_weekend_uses_previous_business_day(client, db, monkeypatch):
    fetch = AsyncMock(return_value={EARLIER: 0.9, MONDAY: 0.91})
    monkeypatch.setattr(exchange_rates, "fetch_daily_fiat_rates", fetch)
    await db.upsert_earnings("honeygain", 7, date=EARLIER)
    await db.upsert_earnings("honeygain", 9, date=SATURDAY)
    await db.add_manual_payout("mysterium", 8, "MYST", 0.25, "crypto", MONDAY)
    earned, payout = csv_rows(await client.get(EXPORT, params={"start": SATURDAY, "end": MONDAY, "currency": "EUR"}))
    assert [(r["usd_value"], r["local_currency"], r["local_rate"], r["local_value"]) for r in [earned, payout]] == [
        ("2", "EUR", "0.9", "1.8"),
        ("2", "EUR", "0.91", "1.82"),
    ]
    fetch.assert_awaited_once_with("EUR", SATURDAY, MONDAY)


async def test_fiat_rates_only_need_to_cover_saved_history(client, db, monkeypatch):
    await db.upsert_earnings("honeygain", 7, date=EARLIER)
    await db.upsert_earnings("honeygain", 9, date=MONDAY)
    fetch = AsyncMock(return_value={EARLIER: 0.9, MONDAY: 0.91})
    monkeypatch.setattr(exchange_rates, "fetch_daily_fiat_rates", fetch)

    response = await client.get(EXPORT, params={"start": "1998-12-30", "end": MONDAY, "currency": "EUR"})
    (earned,) = csv_rows(response)
    assert earned["local_value"] == "1.82"
    assert response.headers["content-disposition"].endswith(f'1998-12-30_{MONDAY}-EUR.csv"')
    fetch.assert_awaited_once_with("EUR", EARLIER, MONDAY)


@pytest.mark.parametrize(
    "params",
    [
        {"start": MONDAY, "end": EARLIER},
        {"start": "2026-13-01"},
        {"start": "2025-11-15\n"},
        {"end": "2025-02-30"},
        {"end": "9999-12-31"},
        {"currency": "eur1"},
    ],
)
async def test_bad_query_does_not_request_rates_or_export(client, db, monkeypatch, params):
    fetch = AsyncMock()
    monkeypatch.setattr(exchange_rates, "fetch_daily_fiat_rates", fetch)
    response = await client.get(EXPORT, params=params)
    assert response.status_code == 400
    assert response.json()["detail"]
    assert await db.get_audit_events() == []
    fetch.assert_not_called()


@pytest.mark.parametrize(("unknown", "status"), [(False, 502), (True, 400)])
async def test_rate_failure_precedes_audit_and_stream(client, db, monkeypatch, unknown, status):
    fetch = AsyncMock(return_value=None, side_effect=exchange_rates.UnknownFiat("EUR") if unknown else None)
    monkeypatch.setattr(exchange_rates, "fetch_daily_fiat_rates", fetch)
    response = await client.get(EXPORT, params={"currency": "EUR"})
    assert response.status_code == status
    assert "content-disposition" not in response.headers
    assert await db.get_audit_events() == []


async def test_failed_audit_does_not_start_download(db, monkeypatch):
    monkeypatch.setattr(db, "add_audit_event", AsyncMock(side_effect=RuntimeError("audit unavailable")))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app, raise_app_exceptions=False),
        base_url="http://test",
        cookies={auth.SESSION_COOKIE: auth.create_session_token(1, "owner", "owner")},
    ) as client:
        response = await client.get(EXPORT)
    assert response.status_code == 500
    assert "content-disposition" not in response.headers


async def test_dangerous_fields_stay_text(client, db):
    response = await client.post(
        "/api/earnings/payouts",
        json={"platform": "honeygain", "amount": 1, "currency": "=1+1", "method": "@SUM(A1)", "date": EARLIER},
    )
    assert response.status_code == 200, response.text
    await db.add_manual_payout("mysterium", 1, "-MYST", None, "+word", SATURDAY)
    await db.add_manual_payout("ocean", 1, "\tBTC", None, "\rlabel", MONDAY)
    await db.add_manual_payout("earnapp", 1, "\nGBP", None, "  ＝word", "2025-11-18")
    rows = csv_rows(await client.get(EXPORT))
    assert [(r["coin"], r["method"]) for r in rows] == [
        ("'=1+1", "'@SUM(A1)"),
        ("'-MYST", "'+word"),
        ("'\tBTC", "'\rlabel"),
        ("'\nGBP", "'  ＝word"),
    ]


async def test_priced_export_agrees_with_dashboard(client, db):
    for day, balance, coin, rate in [
        (EARLIER, 10, "USD", 10),
        ("2025-11-14", 12, "USD", 10),
        (SATURDAY, 8, "MYST", 0.25),
        ("2025-11-16", 4, "MYST", 0.25),
        (MONDAY, 5, "MYST", 0.5),
    ]:
        await db.upsert_earnings("mysterium", balance, coin, day, rate)
    async with await db._get_db() as conn:
        per_day, unpriced = await db._usd_earned_per_date(conn)
    rows = csv_rows(await client.get(EXPORT))
    assert not unpriced
    assert {r["date"]: float(r["usd_value"]) for r in rows} == pytest.approx(
        {day: amount for day, amount in per_day.items() if amount}
    )
    assert per_day == {"2025-11-14": 2.0, "2025-11-16": 0.0, MONDAY: 0.5}


async def test_large_download_streams_chunks(db):
    start = date(2025, 1, 1)
    await db.upsert_earnings_many(
        [
            {
                "platform": "honeygain",
                "source": f"client-{source}",
                "balance": day,
                "currency": "USD",
                "date": (start + timedelta(days=day)).isoformat(),
            }
            for source in range(25)
            for day in range(200)
        ]
    )
    session = auth.create_session_token(1, "owner", "owner")
    request = Request({"type": "http", "headers": [(b"cookie", f"{auth.SESSION_COOKIE}={session}".encode())]})
    response = await main.api_income_csv(request)
    assert isinstance(response, StreamingResponse)
    chunks = [chunk async for chunk in response.body_iterator]
    assert len(chunks) == 10
    assert sum(chunk.count("\r\n") for chunk in chunks) == 1 + 25 * 199


async def test_usd_does_not_open_http_client(monkeypatch):
    def fail(**kwargs):
        pytest.fail("USD parity should not need network access")

    monkeypatch.setattr(exchange_rates.httpx, "AsyncClient", fail)
    assert await exchange_rates.fetch_daily_fiat_rates("USD", EARLIER, MONDAY) == {EARLIER: 1.0}


async def test_frankfurter_requests_one_series(monkeypatch):
    def reply(request):
        assert request.url.host == "api.frankfurter.dev"
        assert request.url.path == f"/v1/{SATURDAY}..{MONDAY}"
        assert dict(request.url.params) == {"from": "USD", "to": "EUR"}
        return httpx.Response(200, json={"base": "USD", "rates": {EARLIER: {"EUR": 0.9}, MONDAY: {"EUR": 0.91}}})

    http_client = httpx.AsyncClient

    def factory(**kwargs):
        return http_client(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(exchange_rates.httpx, "AsyncClient", factory)
    assert await exchange_rates.fetch_daily_fiat_rates("EUR", SATURDAY, MONDAY) == {EARLIER: 0.9, MONDAY: 0.91}


@pytest.mark.parametrize(
    ("status", "rates"),
    [
        (404, {}),
        (503, {}),
        (200, {}),
        (200, {EARLIER: {"EUR": -1}}),
        (200, {MONDAY: {"EUR": 0.91}}),
    ],
)
async def test_frankfurter_refuses_unusable_responses(monkeypatch, status, rates):
    def reply(request):
        return httpx.Response(status, json={"base": "USD", "rates": rates})

    http_client = httpx.AsyncClient

    def factory(**kwargs):
        return http_client(transport=httpx.MockTransport(reply), **kwargs)

    monkeypatch.setattr(exchange_rates.httpx, "AsyncClient", factory)
    if status == 404:
        with pytest.raises(exchange_rates.UnknownFiat):
            await exchange_rates.fetch_daily_fiat_rates("EUR", SATURDAY, MONDAY)
    else:
        assert await exchange_rates.fetch_daily_fiat_rates("EUR", SATURDAY, MONDAY) is None
