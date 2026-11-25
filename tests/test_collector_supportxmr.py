"""The SupportXMR collector: a Monero pool balance read by payout address.

Live answers recorded on 2026-11-25: a known address gives ``amtDue`` in
piconero, and an address the pool has never seen answers HTTP 200 with every
field zero. That second answer must be an error, never a balance of 0.
"""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import httpx
import pytest

from app import credential_test
from app.collectors import _COLLECTOR_ARGS, COLLECTOR_MAP, base, fully_configured_slugs
from app.collectors import supportxmr as sxmr
from app.collectors.supportxmr import SupportXMRCollector

# The Monero General Fund's donation address, which mines on SupportXMR.
FUND = "44AFFq5kSiGBoZ4NMDwYtN18obc8AemS33DBLWs3H7otXft3XjrpDtQGv7SqSsaBYBb98uNbr2VBBEt7f2wfn3RVGQBEP3A"
NOW = 1795629323

KNOWN = {
    "hash": 1500,
    "identifier": "global",
    "lastHash": NOW,
    "totalHashes": 86313450020,
    "validShares": 757428,
    "invalidShares": 754,
    "expiry": 1795629368100,
    "amtPaid": 934095340542,
    "amtDue": 2633849853,
    "txnCount": 0,
}
NEVER_SEEN = {
    "hash": 0,
    "identifier": "global",
    "lastHash": 0,
    "totalHashes": 0,
    "validShares": 0,
    "invalidShares": 0,
    "expiry": 1795629370264,
    "amtPaid": 0,
    "amtDue": 0,
    "txnCount": 0,
}


def _run(collector, handler):
    seen: list[httpx.Request] = []

    def _record(request):
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
    monkeypatch.setattr(sxmr.time, "time", lambda: NOW + 60)


class TestReading:
    def test_amt_due_is_the_balance_in_xmr(self):
        result, seen = _run(SupportXMRCollector(FUND), lambda r: httpx.Response(200, json=KNOWN))
        assert result.error is None
        assert result.balance == pytest.approx(0.002633849853, abs=1e-15)
        assert result.currency == "XMR"
        assert result.warning is None
        assert [str(r.url) for r in seen] == [f"https://www.supportxmr.com/api/miner/{FUND}/stats"]

    def test_one_piconero_is_kept(self):
        result, _ = _run(SupportXMRCollector(FUND), lambda r: httpx.Response(200, json=dict(KNOWN, amtDue=1)))
        assert result.balance == pytest.approx(1e-12, abs=1e-18)

    @pytest.mark.parametrize("txn_count", [0, 9])
    def test_an_address_the_pool_has_never_seen_is_an_error_never_zero(self, txn_count):
        body = dict(NEVER_SEEN, txnCount=txn_count)
        result, _ = _run(SupportXMRCollector(FUND), lambda r: httpx.Response(200, json=body))
        assert result.error and "no record of this address" in result.error
        assert result.error_kind is None
        assert credential_test.classify(result.error, result.error_kind) == credential_test.BAD_CREDENTIALS

    @pytest.mark.parametrize("field", ["lastHash", "totalHashes", "amtPaid"])
    @pytest.mark.parametrize("invalid", [None, True, "0", -1])
    def test_a_zero_balance_with_incomplete_history_is_a_shape_problem(self, field, invalid):
        body = dict(NEVER_SEEN, **{field: invalid})
        result, _ = _run(SupportXMRCollector(FUND), lambda r: httpx.Response(200, json=body))
        assert result.error and result.error_kind == base.KIND_SHAPE

    def test_a_miner_with_history_and_nothing_due_is_a_real_zero(self):
        # Paid out to the last piconero: it has hashes on record, so 0 is a fact.
        body = dict(KNOWN, amtDue=0)
        result, _ = _run(SupportXMRCollector(FUND), lambda r: httpx.Response(200, json=body))
        assert result.error is None and result.balance == 0.0

    def test_txn_count_is_never_used(self):
        # A live address had amtPaid above 0 with txnCount 0; any value must change nothing.
        a, _ = _run(SupportXMRCollector(FUND), lambda r: httpx.Response(200, json=dict(KNOWN, txnCount=0)))
        b, _ = _run(SupportXMRCollector(FUND), lambda r: httpx.Response(200, json=dict(KNOWN, txnCount=9)))
        assert (a.balance, a.error, a.warning) == (b.balance, b.error, b.warning)

    @pytest.mark.parametrize("due", [None, "2633849853", -1, 1.5, True])
    def test_a_missing_or_bad_amount_is_a_shape_problem(self, due):
        body = {k: v for k, v in KNOWN.items() if k != "amtDue"} if due is None else dict(KNOWN, amtDue=due)
        result, _ = _run(SupportXMRCollector(FUND), lambda r: httpx.Response(200, json=body))
        assert result.error and result.error_kind == base.KIND_SHAPE

    def test_a_body_that_is_not_an_object_is_a_shape_problem(self):
        result, _ = _run(SupportXMRCollector(FUND), lambda r: httpx.Response(200, json=[]))
        assert result.error and result.error_kind == base.KIND_SHAPE

    @pytest.mark.parametrize(
        "address",
        [
            "not-an-address",
            FUND + ".rig1",
            FUND + "+50000",
            FUND[:-1],
            "bc1q4efd2vns8qwawg3nt4xxzs9053shh0q3x0tuu9",
            "44AFFq5k/../../api/pool/stats" + "1" * 66,
            "",
        ],
    )
    def test_a_malformed_address_is_never_sent(self, address):
        result, seen = _run(SupportXMRCollector(address), lambda r: httpx.Response(200, json=KNOWN))
        assert seen == []
        assert result.error and "not a Monero address" in result.error
        assert result.error_kind == base.KIND_AUTH

    @pytest.mark.parametrize("address", [FUND, f"  {FUND}  ", "8" + FUND[1:], "4" + "A" * 105])
    def test_standard_sub_and_integrated_addresses_are_sent(self, address):
        result, seen = _run(SupportXMRCollector(address), lambda r: httpx.Response(200, json=KNOWN))
        assert result.error is None and len(seen) == 1
        assert str(seen[0].url).endswith(f"/miner/{address.strip()}/stats")


class TestWarnings:
    def test_no_shares_for_over_an_hour_warns_and_keeps_the_balance(self):
        body = dict(KNOWN, lastHash=NOW - 3 * 3600)
        result, _ = _run(SupportXMRCollector(FUND), lambda r: httpx.Response(200, json=body))
        assert result.error is None and result.balance > 0
        assert result.warning and "no shares from this address for 3 h" in result.warning


class TestFailures:
    def test_a_503_is_transient(self):
        result, _ = _run(SupportXMRCollector(FUND), lambda r: httpx.Response(503, text="busy"))
        assert result.error and result.error_kind == base.KIND_TRANSIENT

    def test_a_timeout_is_transient_never_a_balance(self, monkeypatch):
        async def _no_sleep(_seconds):
            return None

        monkeypatch.setattr(base.asyncio, "sleep", _no_sleep)

        def _timeout(request):
            raise httpx.ReadTimeout("timed out", request=request)

        result, seen = _run(SupportXMRCollector(FUND), _timeout)
        assert result.error and result.error_kind == base.KIND_TRANSIENT
        assert len(seen) == 3


class TestRegistration:
    def test_registered_with_one_public_address_field(self):
        assert COLLECTOR_MAP["supportxmr"] is SupportXMRCollector
        assert _COLLECTOR_ARGS["supportxmr"] == ["address"]

    def test_saving_the_address_starts_tracking(self):
        assert "supportxmr" in fully_configured_slugs({"supportxmr_address": FUND})

    def test_the_catalog_entry_is_a_pool(self):
        from app import catalog, exchange_rates, payouts

        svc = catalog.get_service("supportxmr")
        assert svc["category"] == "mining" and svc["collector"]["accrual"] == "pool"
        assert svc["payout"]["chain"] == "monero" and svc["payout"]["address_source"] == "collector"
        assert exchange_rates.CRYPTO_IDS["XMR"] == "monero"
        # A 0.05 XMR instant payout is seen; a block credit going up is not.
        out = payouts.detect(0.052633849853, 0.002633849853, svc, "XMR")
        assert out is not None and out["amount"] == 0.05
        assert payouts.detect(0.002, 0.0026, svc, "XMR") is None

    def test_a_drop_at_the_manual_minimum_counts_to_the_piconero(self):
        from app import catalog, payouts

        svc = catalog.get_service("supportxmr")
        out = payouts.detect(0.011, 0.001, svc, "XMR")
        assert out is not None and out["amount"] == 0.01 and out["confirmed"] is False
        assert payouts.detect(0.010999999999, 0.001, svc, "XMR") is None

    @pytest.mark.parametrize("address", [FUND, f"{FUND}.rig"])
    def test_credential_check_gives_payout_address_advice(self, monkeypatch, address):
        from unittest.mock import AsyncMock

        from fastapi.testclient import TestClient

        from app import main

        async def fetch_stats(_client, url):
            return httpx.Response(200, json=NEVER_SEEN, request=httpx.Request("GET", url))

        monkeypatch.setattr(main.auth, "get_current_user", lambda request: {"uid": 1, "u": "admin", "r": "owner"})
        monkeypatch.setattr(main.database, "get_config", AsyncMock(return_value={"supportxmr_address": address}))
        monkeypatch.setattr(httpx.AsyncClient, "get", fetch_stats)
        monkeypatch.setattr(credential_test, "_last_attempt", {})
        response = TestClient(main.app).post("/api/services/supportxmr/test-credentials")

        assert response.status_code == 200
        result = response.json()
        assert result["outcome"] == credential_test.BAD_CREDENTIALS
        assert "payout address" in result["message"] and "shares" in result["message"]
        assert "balance" not in result and address not in result["message"]
