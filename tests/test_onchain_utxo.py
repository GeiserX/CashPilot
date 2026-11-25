"""Bitcoin and Kaspa balances through the real HTTP request and parser."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import httpx
import pytest

from app import catalog, onchain

BTC = "bc1q0pp74ghs25vpn2ah6auz4vkehvzy8z8ddyzts7"
KAS = "kaspa:qz0efmwpt789garsw290g47865tz73pwdm3fufqxymchvun9u8tjxlc3ue4s5"


@pytest.fixture(autouse=True)
def _clear_state():
    onchain.reset_state()
    yield
    onchain.reset_state()


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    ("chain", "address"),
    [
        ("bitcoin", BTC),
        ("bitcoin", BTC.upper()),
        ("bitcoin", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"),
        ("bitcoin", "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"),
        ("bitcoin", "bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0"),
        ("kaspa", KAS),
    ],
)
def test_valid_addresses(chain, address):
    assert onchain.address_looks_valid(chain, address)


@pytest.mark.parametrize(
    ("chain", "address"),
    [
        ("bitcoin", BTC[:-1] + "x"),
        ("bitcoin", BTC[:4].upper() + BTC[4:]),
        ("bitcoin", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb"),
        ("bitcoin", "tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q0sl5k7"),
        ("bitcoin", "bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqh2y7hd"),
        ("kaspa", KAS[:-1] + "q"),
        ("kaspa", KAS.split(":")[1]),
        ("kaspa", BTC),
        ("bitcoin", KAS),
    ],
)
@pytest.mark.anyio
async def test_invalid_addresses_never_reach_the_explorer(chain, address):
    calls = []

    def record(request):
        calls.append(request)
        return httpx.Response(500)

    async with _client(record) as client:
        result = await onchain.balance(chain, address, client=client)

    assert result["state"] == onchain.INVALID
    assert result["amount"] is None
    assert calls == []


def _stats(funded=0, spent=0):
    return {
        "funded_txo_count": int(funded != 0),
        "funded_txo_sum": funded,
        "spent_txo_count": int(spent != 0),
        "spent_txo_sum": spent,
    }


def _esplora(confirmed=None, pending=None):
    return {"chain_stats": confirmed if confirmed is not None else _stats(), "mempool_stats": pending or _stats()}


@pytest.mark.anyio
async def test_esplora_confirmed_and_negative_pending_are_separate():
    def handler(request):
        assert request.method == "GET"
        assert str(request.url) == f"https://mempool.space/api/address/{BTC}"
        return httpx.Response(200, json=_esplora(_stats(313825056, 1), _stats(100, 1100)))

    async with _client(handler) as client:
        result = await onchain.balance("bitcoin", BTC.upper(), client=client)

    assert result["state"] == onchain.KNOWN
    assert result["amount"] == Decimal("3.13825055")
    assert result["pending"] == Decimal("-0.00001")
    assert result["source"] == "mempool.space"
    assert result["private"] is False


@pytest.mark.anyio
async def test_esplora_confirms_a_zero_balance():
    async with _client(lambda _: httpx.Response(200, json=_esplora())) as client:
        result = await onchain.balance("bitcoin", BTC, client=client)

    assert result["state"] == onchain.KNOWN
    assert result["amount"] == result["pending"] == Decimal(0)


@pytest.mark.parametrize(
    "malformed",
    [
        _esplora({**_stats(), "spent_txo_count": True}),
        _esplora(pending={**_stats(), "funded_txo_count": 1.0}),
        _esplora({**_stats(), "spent_txo_sum": -1}),
        _esplora(pending={**_stats(), "funded_txo_sum": "0"}),
        _esplora(_stats(50, 100)),
        _esplora({**_stats(50), "funded_txo_count": 0}),
        {"chain_stats": _stats()},
    ],
)
@pytest.mark.anyio
async def test_esplora_refuses_inconsistent_or_incomplete_stats(malformed):
    async with _client(lambda _: httpx.Response(200, json=malformed)) as client:
        result = await onchain.balance("bitcoin", BTC, client=client)

    assert result["state"] == onchain.UNREACHABLE
    assert result["amount"] is result["pending"] is None


@pytest.mark.parametrize("status", [200, 201, 400, 429])
@pytest.mark.anyio
async def test_esplora_refuses_empty_bodies_and_unexpected_statuses(status):
    response = httpx.Response(status) if status == 200 else httpx.Response(status, json=_esplora())
    async with _client(lambda _: response) as client:
        result = await onchain.balance("bitcoin", BTC, client=client)
    assert result["state"] == onchain.UNREACHABLE


@pytest.mark.parametrize(("retry_after", "delay"), [("600", 600), ("9999", 900), ("bad", 120), ("-1", 120)])
@pytest.mark.anyio
async def test_rate_limit_uses_retry_after_on_the_effective_endpoint(monkeypatch, retry_after, delay):
    url = "http://umbrel.local:3006/api"
    clock = 100.0
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        assert str(request.url) == f"{url}/address/{BTC}"
        return httpx.Response(429, headers={"Retry-After": retry_after})

    monkeypatch.setenv("CASHPILOT_ONCHAIN_URL_BITCOIN", url + "/")
    monkeypatch.setattr(onchain, "_now", lambda: clock)
    async with _client(handler) as client:
        await onchain.balance("bitcoin", BTC, client=client)
        clock += delay - 1
        await onchain.balance("bitcoin", BTC, client=client)
        assert calls == 1
        clock += 1
        await onchain.balance("bitcoin", BTC, client=client)
        assert calls == 2


@pytest.mark.anyio
async def test_override_change_bypasses_cached_default_and_empty_disables(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request.url.host)
        return httpx.Response(200, json=_esplora())

    async with _client(handler) as client:
        await onchain.balance("bitcoin", BTC, client=client)
        monkeypatch.setenv("CASHPILOT_ONCHAIN_URL_BITCOIN", "http://umbrel.local:3006/api")
        changed = await onchain.balance("bitcoin", BTC, client=client)
        monkeypatch.setenv("CASHPILOT_ONCHAIN_URL_BITCOIN", "")
        disabled = await onchain.balance("bitcoin", BTC, client=client)
        monkeypatch.setenv("CASHPILOT_ONCHAIN_URL_BITCOIN", "file:///tmp/api")
        malformed = await onchain.balance("bitcoin", BTC, client=client)

    assert calls == ["mempool.space", "umbrel.local"]
    assert changed["source"] == "umbrel.local"
    assert disabled["state"] == malformed["state"] == onchain.UNSUPPORTED
    assert "CASHPILOT_ONCHAIN_URL_BITCOIN" in disabled["detail"]


@pytest.mark.anyio
async def test_kaspa_confirms_sompi_without_inventing_pending():
    def handler(request):
        assert request.method == "GET"
        assert str(request.url) == f"https://api.kaspa.org/addresses/{KAS}/balance"
        return httpx.Response(200, json={"address": KAS, "balance": 2588155946484})

    async with _client(handler) as client:
        result = await onchain.balance("kaspa", KAS, client=client)
    assert result["state"] == onchain.KNOWN
    assert result["amount"] == Decimal("25881.55946484")
    assert result["pending"] is None
    assert result["source"] == "api.kaspa.org"


@pytest.mark.parametrize(
    "payload",
    [
        {"address": KAS, "balance": "0"},
        {"address": KAS, "balance": False},
        {"address": KAS, "balance": -1},
        {"address": KAS[:-1] + "q", "balance": 0},
    ],
)
@pytest.mark.anyio
async def test_kaspa_refuses_a_wrong_address_or_noninteger_balance(payload):
    async with _client(lambda _: httpx.Response(200, json=payload)) as client:
        result = await onchain.balance("kaspa", KAS, client=client)
    assert result["state"] == onchain.UNREACHABLE
    assert result["amount"] is None


@pytest.mark.anyio
async def test_private_monero_names_the_view_key_without_contacting_anyone():
    calls = []
    async with _client(lambda request: calls.append(request) or httpx.Response(500)) as client:
        result = await onchain.balance("monero", "public-payout-address", client=client)
    assert result["state"] == onchain.UNSUPPORTED
    assert result["symbol"] == "XMR"
    assert result["private"] is True
    assert result["amount"] is result["pending"] is result["source"] is None
    assert "private view key" in result["detail"]
    assert calls == []


@pytest.mark.anyio
async def test_same_host_has_two_slots_across_chains_and_paths(monkeypatch):
    monkeypatch.setenv("CASHPILOT_ONCHAIN_URL_BITCOIN", "https://node.example/btc")
    monkeypatch.setenv("CASHPILOT_ONCHAIN_URL_KASPA", "https://node.example/kas")
    active = peak = 0

    async def handler(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        if request.url.path.startswith("/kas/"):
            return httpx.Response(200, json={"address": KAS, "balance": 0})
        return httpx.Response(200, json=_esplora())

    async with _client(handler) as client:
        results = await asyncio.gather(
            onchain.balance("bitcoin", BTC, client=client),
            onchain.balance("bitcoin", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", client=client),
            onchain.balance("kaspa", KAS, client=client),
        )
    assert {result["state"] for result in results} == {onchain.KNOWN}
    assert peak == 2


def test_catalog_payout_chains_match_the_readers():
    services = catalog.load_services()
    declared = {service["payout"]["chain"] for service in services if (service.get("payout") or {}).get("chain")}
    assert declared <= onchain.KNOWN_SLUGS
    assert onchain.CHAINS.keys() <= declared
