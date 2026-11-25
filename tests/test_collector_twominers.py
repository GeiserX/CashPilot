"""Exercise the 2Miners pool balance and Ethereum Classic wallet reads."""

import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app import catalog, credential_test, exchange_rates, onchain, payouts
from app.collectors import base, build_one, fully_configured_slugs, twominers

SLUG = "2miners-etc"
ADDRESS = "0x00109777bdc6d6a658097ed6b6167569ee1f4ec1"
CONTRACT = json.loads((Path(__file__).parent / "fixtures/collectors/2miners-etc.json").read_text())


@pytest.fixture
def read(monkeypatch):
    now = CONTRACT["sample"]["stats"]["lastShare"] + 60
    monkeypatch.setattr(twominers.time, "time", lambda: now)

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
async def test_only_the_unpaid_balance_is_read_in_etc(read):
    stats = dict(CONTRACT["sample"]["stats"], pending=123_456)
    result, requests = await read(lambda _: httpx.Response(200, json={"stats": stats}), f" {ADDRESS} ")

    assert result.error is None and result.warning is None
    assert result.platform == SLUG
    assert result.currency == CONTRACT["currency"] and result.balance == CONTRACT["parsed"]
    [request] = requests
    assert request.method == "GET"
    assert str(request.url) == f"https://etc.2miners.com/api/accounts/{ADDRESS}"


@pytest.mark.asyncio
@pytest.mark.parametrize("balance", [0, 1])
async def test_known_address_can_have_zero_or_one_base_unit(read, balance):
    stats = dict(CONTRACT["sample"]["stats"], balance=balance)
    result, _ = await read(lambda _: httpx.Response(200, json={"stats": stats}))
    assert result.error is None and result.balance == balance / 1_000_000_000


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 404])
async def test_unseen_address_is_an_error(read, status):
    stats = {"lastShare": 0, "balance": 0, "paid": 0}
    response = httpx.Response(200, json={"stats": stats}) if status == 200 else httpx.Response(404)
    result, _ = await read(lambda _: response)

    assert result.error and "no record of this address" in result.error
    assert result.error_kind is None
    assert credential_test.classify(result.error, result.error_kind) == credential_test.BAD_CREDENTIALS


@pytest.mark.asyncio
@pytest.mark.parametrize("address", [ADDRESS + ".rig", ADDRESS[2:], ADDRESS[:-1], "bc1qabcd", ADDRESS + "?extra="])
async def test_malformed_address_is_never_sent(read, address):
    result, requests = await read(lambda _: httpx.Response(200, json=CONTRACT["sample"]), address)
    assert requests == [] and result.error and result.error_kind == base.KIND_AUTH


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stats",
    [
        None,
        {},
        {"balance": 0},
        {"balance": "0", "lastShare": 1},
        {"balance": -1, "lastShare": 1},
        {"balance": True, "lastShare": 1},
        {"balance": 0, "lastShare": False},
    ],
)
async def test_malformed_stats_are_shape_errors(read, stats):
    result, _ = await read(lambda _: httpx.Response(200, json={"stats": stats}))
    assert result.error and result.error_kind == base.KIND_SHAPE


@pytest.mark.asyncio
async def test_stale_share_warns_without_losing_the_balance(read):
    stats = dict(CONTRACT["sample"]["stats"], lastShare=CONTRACT["sample"]["stats"]["lastShare"] - 7200)
    result, _ = await read(lambda _: httpx.Response(200, json={"stats": stats}))
    assert result.error is None and result.balance == CONTRACT["parsed"]
    assert result.warning and "no shares from this address for 2 h" in result.warning


@pytest.mark.asyncio
async def test_service_unavailable_has_a_transient_error_without_the_address(read):
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
    assert len(requests) == 3 and result.error and result.error_kind == base.KIND_TRANSIENT


def test_registered_as_an_etc_pool_with_a_point_one_etc_minimum():
    assert SLUG in fully_configured_slugs({f"{SLUG}_address": ADDRESS})
    service = catalog.get_service(SLUG)
    assert service["category"] == "mining" and service["docker"]["image"] == ""
    assert service["collector"]["accrual"] == "pool"
    assert service["payout"]["chain"] == "ethereum-classic" and service["payout"]["address_source"] == "collector"
    assert exchange_rates.CRYPTO_IDS["ETC"] == "ethereum-classic"
    drop = payouts.detect(0.11, 0.01, service, "ETC")
    assert drop and drop["amount"] == 0.1 and drop["confirmed"] is False
    assert payouts.detect(0.109999999, 0.01, service, "ETC") is None


@pytest.mark.asyncio
async def test_ethereum_classic_rpc_uses_wei_not_pool_units():
    onchain.reset_state()

    def respond(request):
        assert str(request.url) == "https://geth-at.etc-network.info"
        rpc = json.loads(request.content)
        assert rpc["method"] == "eth_getBalance" and rpc["params"] == [ADDRESS, "latest"]
        return httpx.Response(200, json={"result": hex(10**18 + 1)})

    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result = await onchain.balance("ethereum-classic", ADDRESS, client=client)
        assert result["state"] == onchain.KNOWN and result["symbol"] == "ETC"
        assert result["amount"] == Decimal("1.000000000000000001")
    finally:
        onchain.reset_state()


@pytest.mark.asyncio
async def test_ethereum_classic_rpc_error_keeps_the_payout_address_out_of_logs(caplog):
    response = httpx.Response(200, json={"error": {"code": -32602, "message": f"Invalid account {ADDRESS}"}})
    onchain.reset_state()
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
            result = await onchain.balance("ethereum-classic", ADDRESS, client=client)
    finally:
        onchain.reset_state()

    assert result["state"] == onchain.UNREACHABLE and result["amount"] is None
    assert "Could not read ethereum-classic balance" in caplog.text
    assert ADDRESS not in caplog.text
