"""Test the unMineable address stats contract with controlled replies."""

import json
import re
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from app import catalog, credential_test, payouts
from app.collectors import base, build_one, fully_configured_slugs

SLUG = "unmineable"
FUND = "44AFFq5kSiGBoZ4NMDwYtN18obc8AemS33DBLWs3H7otXft3XjrpDtQGv7SqSsaBYBb98uNbr2VBBEt7f2wfn3RVGQBEP3A"
CONTRACT = json.loads((Path(__file__).parent / "fixtures/collectors/unmineable.json").read_text())
CODE = "awk6-j1z0"


def _reply(**data):
    body = deepcopy(CONTRACT["sample"])
    body["data"].update(data)
    return body


@pytest.fixture
def read(monkeypatch):
    async def collect(handler, address=FUND, coin="XMR"):
        collector, missing = build_one(SLUG, {f"{SLUG}_address": address, f"{SLUG}_coin": coin})
        assert collector is not None and not missing
        requests = []

        def record(request):
            requests.append(request)
            return handler(request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(record)) as client:
            monkeypatch.setattr(collector, "_get_client", lambda **kwargs: client)
            result = await collector.collect()
        return result, requests

    return collect


@pytest.mark.asyncio
async def test_reads_the_balance_and_threshold_in_the_chosen_coin(read):
    result, requests = await read(lambda _: httpx.Response(200, json=CONTRACT["sample"]), f" {FUND} ", " xmr ")

    assert result.error is None and result.warning is None
    assert result.platform == SLUG
    assert result.currency == CONTRACT["currency"]
    assert result.balance == CONTRACT["parsed"]
    assert result.payout_threshold == 0.03
    [request] = requests
    assert request.method == "GET"
    assert request.url.host == "api.unminable.com" and request.url.path == f"/v4/address/{FUND}"
    assert dict(request.url.params) == {"coin": "XMR"}


@pytest.mark.asyncio
async def test_a_known_address_with_nothing_owed_reads_zero(read):
    result, _ = await read(
        lambda _: httpx.Response(200, json=_reply(balance="0", payment_threshold="150000")), coin="SHIB"
    )

    assert result.error is None
    assert result.balance == 0.0 and result.currency == "SHIB" and result.payout_threshold == 150000


@pytest.mark.asyncio
async def test_an_address_unmineable_has_never_seen_is_unknown_not_zero(read):
    result, _ = await read(lambda _: httpx.Response(200, json=_reply(balance="0", fresh=True)))

    assert result.error and "no record of this XMR address" in result.error
    assert result.error_kind is None
    assert result.payout_threshold is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [
        {"fresh": None},
        {"balance": None},
        {"balance": 0.5},
        {"balance": "-1"},
        {"balance": "NaN"},
        {"balance": "Infinity"},
        {"balance": "lots"},
        {"payment_threshold": None},
        {"payment_threshold": "0"},
    ],
)
async def test_an_invalid_balance_or_threshold_is_an_error_not_zero(read, data):
    body = _reply()
    for key, value in data.items():
        if value is None:
            del body["data"][key]
        else:
            body["data"][key] = value
    result, _ = await read(lambda _: httpx.Response(200, json=body))

    assert result.error and result.error_kind == base.KIND_SHAPE
    assert result.payout_threshold is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"success": True, "msg": "Ok"},
        {"success": True, "data": []},
        {"success": "yes", "data": CONTRACT["sample"]["data"]},
        [],
    ],
)
async def test_a_reply_without_address_stats_is_an_error(read, body):
    result, _ = await read(lambda _: httpx.Response(200, json=body))

    assert result.error == "unMineable did not return address stats." and result.error_kind == base.KIND_SHAPE


@pytest.mark.asyncio
async def test_a_reply_that_is_not_json_is_an_error(read):
    result, _ = await read(lambda _: httpx.Response(200, text="<html>maintenance</html>"))

    assert result.error and result.error_kind == base.KIND_SHAPE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("msg", "expected"),
    [("Invalid address.", "does not accept this address for XMR"), ("Invalid or missing coin.", "does not list")],
)
async def test_a_rejected_address_or_coin_needs_a_person(read, msg, expected):
    result, _ = await read(lambda _: httpx.Response(404, json={"success": False, "msg": msg}))

    assert result.error and expected in result.error
    assert result.error_kind == base.KIND_AUTH
    assert FUND not in result.error


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "kind"), [(403, base.KIND_TRANSIENT), (503, base.KIND_TRANSIENT), (404, None)])
async def test_a_refused_public_request_does_not_reject_the_address(read, status, kind):
    result, _ = await read(lambda _: httpx.Response(status, text="nope"))

    assert result.error == f"unMineable returned HTTP {status}."
    assert result.error_kind == kind


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("address", "coin"),
    [
        (f"{FUND}.rig", "XMR"),
        (f"{FUND}#{CODE}", "XMR"),
        (f"XMR:{FUND}", "XMR"),
        ("rXRPaddress:12345", "XRP"),
        (f"{FUND}/../../stats", "XMR"),
        (FUND, "X"),
        (FUND, "XMR&coin=BTC"),
        (FUND, "   "),
    ],
)
async def test_a_malformed_address_or_coin_is_refused_before_any_request(read, address, coin):
    result, requests = await read(lambda _: httpx.Response(200, json=CONTRACT["sample"]), address, coin)

    assert requests == []
    assert result.error and result.error_kind == base.KIND_AUTH


@pytest.mark.asyncio
async def test_a_flagged_address_keeps_its_balance_with_a_warning(read):
    flags = dict(CONTRACT["sample"]["data"]["err_flags"], payment_error=True, restricted=True)
    result, _ = await read(lambda _: httpx.Response(200, json=_reply(err_flags=flags)))

    assert result.error is None and result.balance == CONTRACT["parsed"]
    assert result.warning == "unMineable reports a payment error and a restricted address for this address."


@pytest.mark.asyncio
async def test_a_network_failure_is_transient(read):
    def fail(request):
        raise httpx.ConnectError("connection refused", request=request)

    result, _ = await read(fail)

    assert result.error and result.error_kind == base.KIND_TRANSIENT


def test_both_the_address_and_the_coin_are_required():
    assert SLUG not in fully_configured_slugs({f"{SLUG}_address": FUND})
    assert SLUG not in fully_configured_slugs({f"{SLUG}_coin": "XMR"})
    assert SLUG in fully_configured_slugs({f"{SLUG}_address": FUND, f"{SLUG}_coin": "XMR"})


class TestPayoutUsesTheCoinsOwnThreshold:
    """The catalog has one entry for every coin, so the pool's threshold decides."""

    def test_the_catalog_sets_no_single_minimum(self):
        service = catalog.get_service(SLUG)
        assert payouts.min_payout(service) is None
        # Without the pool's threshold a drop is never asked about.
        assert payouts.detect(150_000.0, 10.0, service, "SHIB") is None

    def test_a_drop_of_at_least_the_reported_threshold_is_a_probable_payout(self):
        service = catalog.get_service(SLUG)
        out = payouts.detect(150_010.0, 10.0, service, "SHIB", threshold=150_000.0)
        assert out is not None and out["amount"] == 150_000.0 and out["confirmed"] is False
        assert "150000.00 minimum" in out["reason"]
        assert payouts.detect(150_009.0, 10.0, service, "SHIB", threshold=150_000.0) is None

    def test_the_reported_threshold_overrides_the_catalog_minimum(self):
        service = catalog.get_service("supportxmr")
        # SupportXMR's catalog minimum is 0.01 XMR: the reported 0.03 wins.
        assert payouts.detect(0.03, 0.01, service, "XMR") is not None
        assert payouts.detect(0.03, 0.01, service, "XMR", threshold=0.03) is None

    @pytest.mark.asyncio
    async def test_the_collection_loop_passes_the_threshold_on(self, tmp_path, monkeypatch):
        from app import database, main
        from app.collectors.base import EarningsResult

        monkeypatch.setattr(database, "DB_DIR", tmp_path)
        monkeypatch.setattr(database, "DB_PATH", tmp_path / "cashpilot.db")
        monkeypatch.setattr(main, "_push_alert", AsyncMock())
        await database.init_db()
        await database.upsert_earnings(SLUG, 0.031, "XMR")

        await main._detect_payout(EarningsResult(platform=SLUG, balance=0.0005, currency="XMR", payout_threshold=0.03))

        [payout] = await database.get_payouts(SLUG)
        assert payout["amount"] == pytest.approx(0.0305) and not payout["confirmed"]
        assert payout["currency"] == "XMR"

    @pytest.mark.asyncio
    async def test_switching_coins_is_not_a_payout(self, tmp_path, monkeypatch):
        from app import database, main
        from app.collectors.base import EarningsResult

        monkeypatch.setattr(database, "DB_DIR", tmp_path)
        monkeypatch.setattr(database, "DB_PATH", tmp_path / "cashpilot.db")
        monkeypatch.setattr(main, "_push_alert", AsyncMock())
        await database.init_db()
        await database.upsert_earnings(SLUG, 150_000.0, "SHIB")

        # The same address now mines XMR: 150000 SHIB to 0.001 XMR is no drop.
        await main._detect_payout(EarningsResult(platform=SLUG, balance=0.001, currency="XMR", payout_threshold=0.03))

        assert await database.get_payouts(SLUG) == []
        assert await database.get_latest_balance(SLUG) == 150_000.0
        assert await database.get_latest_balance(SLUG, "shib") == 150_000.0
        assert await database.get_latest_balance(SLUG, "XMR") is None


@pytest.mark.parametrize("address", [FUND, f"{FUND}.rig"])
def test_credential_check_gives_payout_address_advice(monkeypatch, address):
    from fastapi.testclient import TestClient

    from app import main

    async def fetch_stats(_client, url, **kwargs):
        return httpx.Response(200, json=_reply(fresh=True, balance="0"), request=httpx.Request("GET", url))

    monkeypatch.setattr(main.auth, "get_current_user", lambda request: {"uid": 1, "u": "admin", "r": "owner"})
    config = {f"{SLUG}_address": address, f"{SLUG}_coin": "XMR"}
    monkeypatch.setattr(main.database, "get_config", AsyncMock(return_value=config))
    monkeypatch.setattr(httpx.AsyncClient, "get", fetch_stats)
    monkeypatch.setattr(credential_test, "_last_attempt", {})
    response = TestClient(main.app).post(f"/api/services/{SLUG}/test-credentials")

    assert response.status_code == 200
    result = response.json()
    assert result["outcome"] == credential_test.BAD_CREDENTIALS
    assert "payout address" in result["message"] and "shares" in result["message"]
    assert "cookie" not in result["message"] and address not in result["message"]


def test_xmr_is_priced_and_the_listed_coins_are_too():
    from app import exchange_rates

    for coin, coin_id in {"XMR": "monero", "SHIB": "shiba-inu", "DOGE": "dogecoin", "BNB": "binancecoin"}.items():
        assert exchange_rates.CRYPTO_IDS[coin] == coin_id


def test_the_guide_lists_exactly_the_priced_coins():
    from app import exchange_rates

    guide = (Path(__file__).parents[1] / "docs/guides/unmineable.md").read_text()
    line = next(line for line in guide.splitlines() if line.startswith("CashPilot prices "))
    listed = set(re.findall(r"\b[A-Z]{3,4}\b", line))
    assert listed == set(exchange_rates.CRYPTO_IDS) - {"MYST", "ANYONE", "UPT"}
