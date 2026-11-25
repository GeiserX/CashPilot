"""Test the public HeroMiners Kaspa stats contract with controlled replies."""

import json
from pathlib import Path

import httpx
import pytest

from app import catalog, credential_test, exchange_rates, payouts
from app.collectors import base, build_one, fully_configured_slugs, herominers

SLUG = "herominers-kas"
ADDRESS = "kaspa:qp5y3dq23g8nts03peqhvlq9xx4asd2mr84r22zqxqglkle7jf5qvrjsw5lkd"
CONTRACT = json.loads((Path(__file__).parent / "fixtures/collectors/herominers-kas.json").read_text())


@pytest.fixture
def read(monkeypatch):
    now = int(CONTRACT["sample"]["stats"]["lastShare"]) + 60
    monkeypatch.setattr(herominers.time, "time", lambda: now)

    async def collect(handler, address=ADDRESS):
        collector, missing = build_one(SLUG, {f"{SLUG}_address": address})
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
async def test_reads_only_the_unpaid_sompi_balance(read):
    result, requests = await read(lambda _: httpx.Response(200, json=CONTRACT["sample"]), f" {ADDRESS} ")

    assert result.error is None
    assert result.platform == SLUG
    assert result.currency == CONTRACT["currency"]
    assert result.balance == CONTRACT["parsed"]
    assert result.warning is None
    [request] = requests
    assert request.method == "GET"
    assert request.url.host == "kaspa.herominers.com" and request.url.path == "/api/stats_address"
    assert dict(request.url.params) == {"address": ADDRESS, "recentBlocksAmount": "0", "longpoll": "false"}


@pytest.mark.asyncio
@pytest.mark.parametrize(("raw", "amount"), [("0", 0.0), ("1", 0.00000001)])
async def test_reads_zero_and_single_sompi_for_a_known_address(read, raw, amount):
    result, _ = await read(lambda _: httpx.Response(200, json={"stats": {"balance": raw}}))

    assert result.error is None and result.balance == amount


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_error", "message", "kind"),
    [("Not found", "no record of this address", None), ("Invalid address", "full KAS payout address", base.KIND_AUTH)],
)
async def test_pool_errors_on_http_200_are_not_readings(read, provider_error, message, kind):
    result, requests = await read(lambda _: httpx.Response(200, json={"error": provider_error}))

    assert len(requests) == 1
    assert result.error and message in result.error
    assert result.error_kind == kind
    assert credential_test.classify(result.error, result.error_kind) == credential_test.BAD_CREDENTIALS


@pytest.mark.asyncio
@pytest.mark.parametrize("address", [ADDRESS + ".rig", ADDRESS[6:], ADDRESS[:-1], ADDRESS + "&longpoll=true"])
async def test_malformed_address_is_never_sent(read, address):
    result, requests = await read(lambda _: httpx.Response(200, json=CONTRACT["sample"]), address)

    assert requests == []
    assert result.error and result.error_kind == base.KIND_AUTH


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        [],
        {"stats": None},
        {"stats": {}},
        {"stats": {"balance": True}},
        {"stats": {"balance": "-1"}},
        {"stats": {"balance": "1.4"}},
        {"stats": {"balance": "1e8"}},
        {"stats": {"balance": "1" * 21}},
        {"error": "pool busy", "stats": {"balance": "0"}},
    ],
)
async def test_malformed_reply_does_not_produce_a_reading(read, body):
    result, _ = await read(lambda _: httpx.Response(200, json=body))

    assert result.error and result.error_kind == base.KIND_SHAPE


@pytest.mark.asyncio
async def test_non_json_reply_is_a_shape_error(read):
    result, _ = await read(lambda _: httpx.Response(200, text="<html>"))

    assert result.error and result.error_kind == base.KIND_SHAPE


@pytest.mark.asyncio
async def test_old_share_warns_and_keeps_the_balance(read):
    body = {"stats": {"balance": "184000000", "lastShare": "1795630000"}}
    result, _ = await read(lambda _: httpx.Response(200, json=body))

    assert result.error is None and result.balance == 1.84
    assert result.warning and "no shares from this address for 3 h" in result.warning


@pytest.mark.asyncio
async def test_503_is_transient_and_omits_the_address(read):
    result, _ = await read(lambda _: httpx.Response(503))

    assert result.error and "503" in result.error and ADDRESS not in result.error
    assert result.error_kind == base.KIND_TRANSIENT


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_refused_public_request_does_not_reject_the_payout_address(read, status):
    result, _ = await read(lambda _: httpx.Response(status))

    assert result.error_kind == base.KIND_TRANSIENT
    assert credential_test.classify(result.error, result.error_kind) == credential_test.UNREACHABLE


@pytest.mark.asyncio
async def test_timeout_is_transient_after_retries(read, monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(base.asyncio, "sleep", no_sleep)

    def timeout(request):
        raise httpx.ReadTimeout("", request=request)

    result, requests = await read(timeout)

    assert len(requests) == 3
    assert result.error and result.error_kind == base.KIND_TRANSIENT


def test_registered_as_a_kaspa_pool_with_a_one_kas_minimum():
    assert SLUG in fully_configured_slugs({f"{SLUG}_address": ADDRESS})
    service = catalog.get_service(SLUG)
    assert service["category"] == "mining" and service["docker"]["image"] == ""
    assert service["collector"]["accrual"] == "pool"
    assert service["payout"]["chain"] == "kaspa" and service["payout"]["address_source"] == "collector"
    assert exchange_rates.CRYPTO_IDS["KAS"] == "kaspa"
    drop = payouts.detect(2.01, 1.01, service, "KAS")
    assert drop and drop["amount"] == 1.0 and drop["confirmed"] is False
    assert payouts.detect(2.00999999, 1.01, service, "KAS") is None
