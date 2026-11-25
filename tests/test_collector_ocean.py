"""The OCEAN collector: an unpaid BTC balance read by payout address.

Live answers recorded on 2026-11-25 (specs/critique.md §3): a known address
gives ``result.unpaid`` as a decimal string, and an address OCEAN has never
seen answers HTTP 200 with ``{"error":"No such user/worker"}``. That second
answer must be an error, never a balance of 0.
"""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import httpx
import pytest

from app import credential_test
from app.collectors import _COLLECTOR_ARGS, COLLECTOR_MAP, base, fully_configured_slugs
from app.collectors import ocean as ocean_mod
from app.collectors.ocean import OceanCollector

LIVE = "bc1q4efd2vns8qwawg3nt4xxzs9053shh0q3x0tuu9"
NOW = 1795626484.0

KNOWN = {
    "result": {
        "snap_type": "user",
        "hashrate_300s": "20206150328135624",
        "lastest_share_ts": str(int(NOW)),
        "estimated_payout_next_block": "0.00000000",
        "unpaid": "0.00571777",
    }
}


def _run(collector: OceanCollector, handler) -> tuple[base.EarningsResult, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def _record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    collector._client = httpx.AsyncClient(transport=httpx.MockTransport(_record))

    async def _go():
        try:
            return await collector.collect()
        finally:
            await collector.close()

    return asyncio.run(_go()), seen


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    monkeypatch.setattr(ocean_mod.time, "time", lambda: NOW + 60)


class TestReading:
    def test_unpaid_is_the_balance_in_btc(self):
        result, seen = _run(OceanCollector(LIVE), lambda r: httpx.Response(200, json=KNOWN))
        assert result.error is None
        assert result.balance == pytest.approx(0.00571777, abs=1e-12)
        assert result.currency == "BTC"
        assert result.warning is None
        assert [str(r.url) for r in seen] == [f"https://api.ocean.xyz/v1/statsnap/{LIVE}"]

    def test_an_address_ocean_has_never_seen_is_an_error_never_zero(self):
        result, _ = _run(OceanCollector(LIVE), lambda r: httpx.Response(200, json={"error": "No such user/worker"}))
        # The collection loop stores a balance only when error is unset.
        assert result.error and "no record of this address" in result.error
        assert result.error_kind is None
        # The test button names it as a wrong value, not as an API change.
        assert credential_test.classify(result.error, result.error_kind) == credential_test.BAD_CREDENTIALS

    def test_an_unexpected_error_body_is_a_shape_problem(self):
        result, _ = _run(OceanCollector(LIVE), lambda r: httpx.Response(200, json={"error": "maintenance"}))
        assert result.error and result.error_kind == base.KIND_SHAPE

    @pytest.mark.parametrize("body", [{"result": {}}, {"result": {"unpaid": "abc"}}, {"result": {"unpaid": "-1"}}, []])
    def test_a_missing_or_bad_unpaid_is_a_shape_problem(self, body):
        result, _ = _run(OceanCollector(LIVE), lambda r: httpx.Response(200, json=body))
        assert result.error and result.error_kind == base.KIND_SHAPE

    @pytest.mark.parametrize(
        "address",
        [
            "not-an-address",
            f"{LIVE}.bitaxe",
            "0x00109777bdc6d6a658097ed6b6167569ee1f4ec1",
            "bc1q../../v1/blocks",
            "",
        ],
    )
    def test_a_malformed_address_is_never_sent(self, address):
        result, seen = _run(OceanCollector(address), lambda r: httpx.Response(200, json=KNOWN))
        assert seen == []
        assert result.error and "not a Bitcoin address" in result.error
        assert result.error_kind == base.KIND_AUTH

    @pytest.mark.parametrize(
        "address",
        [
            LIVE,
            f"  {LIVE.upper()}  ",
            "bc1p5d7rjq7g6rdk2yhzks9smlaqtedr4dekq08ge8ztwac72sfr9rusxg3297",
            "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy",
        ],
    )
    def test_every_address_type_ocean_accepts_is_sent_in_its_canonical_form(self, address):
        result, seen = _run(OceanCollector(address), lambda r: httpx.Response(200, json=KNOWN))
        assert result.error is None
        assert len(seen) == 1
        assert str(seen[0].url).endswith("/statsnap/" + ocean_mod.normalise_address(address))
        assert ocean_mod.normalise_address(f" {LIVE.upper()} ") == LIVE


class TestWarnings:
    def test_no_shares_for_over_an_hour_warns_and_keeps_the_balance(self):
        body = {"result": dict(KNOWN["result"], lastest_share_ts=str(int(NOW - 5 * 3600)))}
        result, _ = _run(OceanCollector(LIVE), lambda r: httpx.Response(200, json=body))
        assert result.error is None and result.balance == pytest.approx(0.00571777)
        assert result.warning and "no shares from this address for 5 h" in result.warning

    def test_paid_every_block_warns(self):
        body = {"result": dict(KNOWN["result"], unpaid="0.00000000", estimated_payout_next_block="0.01500000")}
        result, _ = _run(OceanCollector(LIVE), lambda r: httpx.Response(200, json=body))
        assert result.error is None and result.balance == 0.0
        assert result.warning and "every block" in result.warning

    def test_a_real_zero_with_nothing_due_has_no_warning(self):
        body = {"result": dict(KNOWN["result"], unpaid="0.00000000")}
        result, _ = _run(OceanCollector(LIVE), lambda r: httpx.Response(200, json=body))
        assert result.error is None and result.balance == 0.0 and result.warning is None


class TestFailures:
    def test_a_503_is_transient(self):
        result, _ = _run(OceanCollector(LIVE), lambda r: httpx.Response(503, text="busy"))
        assert result.error and result.error_kind == base.KIND_TRANSIENT

    def test_a_timeout_is_transient_never_a_balance(self, monkeypatch):
        async def _no_sleep(_seconds):
            return None

        monkeypatch.setattr(base.asyncio, "sleep", _no_sleep)

        def _timeout(request):
            raise httpx.ReadTimeout("timed out", request=request)

        result, seen = _run(OceanCollector(LIVE), _timeout)
        assert result.error and result.error_kind == base.KIND_TRANSIENT
        assert len(seen) == 3  # the base retry: one try and two retries


class TestRegistration:
    def test_registered_with_one_public_address_field(self):
        assert COLLECTOR_MAP["ocean"] is OceanCollector
        assert _COLLECTOR_ARGS["ocean"] == ["address"]

    def test_saving_the_address_starts_tracking(self):
        assert "ocean" in fully_configured_slugs({"ocean_address": LIVE})
        assert "ocean" not in fully_configured_slugs({})
