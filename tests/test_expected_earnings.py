"""Expected earnings next to what the pool credited (Fleet device rows).

The expected figure is an ESTIMATE from the network's difficulty and recent
block rewards, before the pool's fee and luck. It must never read as money
owed, never replace the credited figure, and never be 0 because a read failed.

Live answers recorded on 2026-11-25 (specs/economics.md (d)):
``/api/v1/mining/hashrate/3d`` gave ``currentDifficulty`` 134823837323272.7 and
``/api/v1/mining/reward-stats/144`` gave ``totalReward`` "45263587901" over
blocks 977385-977528: 46.9 sats per TH/s per day.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import httpx  # noqa: E402
import pytest  # noqa: E402

from app import network_stats, onchain  # noqa: E402
from app.collectors.base import EarningsResult  # noqa: E402
from app.collectors.ocean import OceanCollector  # noqa: E402

DIFFICULTY = 134823837323272.7
HASHRATE_ANSWER = {"currentHashrate": 1.039e21, "currentDifficulty": DIFFICULTY}
REWARD_ANSWER = {"startBlock": 977385, "endBlock": 977528, "totalReward": "45263587901", "totalFee": "263587901"}
REWARD_BTC = 45263587901 / 144 / 1e8


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.delenv(onchain.CHAINS["bitcoin"].endpoint_variable, raising=False)
    network_stats.reset_state()
    yield
    network_stats.reset_state()


def _read(handler):
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(record)) as client:
            return await network_stats.bitcoin(client=client)

    return asyncio.run(go()), seen


def _mempool(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/v1/mining/hashrate/3d"):
        return httpx.Response(200, json=HASHRATE_ANSWER)
    if request.url.path.endswith("/v1/mining/reward-stats/144"):
        return httpx.Response(200, json=REWARD_ANSWER)
    return httpx.Response(404)


class TestFormula:
    def test_the_worked_example_is_46_9_sats_per_th_per_day(self):
        sats = network_stats.expected_btc_per_day(1e12, DIFFICULTY, REWARD_BTC) * 1e8
        assert sats == pytest.approx(46.9, abs=0.05)

    def test_it_scales_with_hashrate(self):
        one = network_stats.expected_btc_per_day(1e12, DIFFICULTY, REWARD_BTC)
        assert network_stats.expected_btc_per_day(1.2e12, DIFFICULTY, REWARD_BTC) == pytest.approx(1.2 * one)


class TestNetworkRead:
    def test_reads_difficulty_and_the_average_block_reward_from_mempool_space(self):
        stats, seen = _read(_mempool)
        assert stats["state"] == network_stats.KNOWN
        assert stats["difficulty"] == DIFFICULTY
        assert stats["reward_btc_per_block"] == pytest.approx(REWARD_BTC)
        assert stats["source"] == "mempool.space"
        assert [str(r.url) for r in seen] == [
            "https://mempool.space/api/v1/mining/hashrate/3d",
            "https://mempool.space/api/v1/mining/reward-stats/144",
        ]

    def test_a_second_read_within_the_hour_is_served_from_cache(self):
        _read(_mempool)
        stats, seen = _read(_mempool)
        assert stats["state"] == network_stats.KNOWN
        assert seen == []

    def test_the_bitcoin_endpoint_override_is_used(self, monkeypatch):
        monkeypatch.setenv("CASHPILOT_ONCHAIN_URL_BITCOIN", "https://node.example/mempool/api/")
        stats, seen = _read(_mempool)
        assert stats["source"] == "node.example"
        assert str(seen[0].url) == "https://node.example/mempool/api/v1/mining/hashrate/3d"

    def test_an_empty_override_turns_it_off_without_a_request(self, monkeypatch):
        monkeypatch.setenv("CASHPILOT_ONCHAIN_URL_BITCOIN", "")
        stats, seen = _read(_mempool)
        assert stats["state"] == network_stats.UNSUPPORTED
        assert "CASHPILOT_ONCHAIN_URL_BITCOIN" in stats["detail"]
        assert seen == []

    def test_a_failed_read_is_unreachable_and_backs_off(self):
        stats, seen = _read(lambda request: httpx.Response(503))
        assert stats["state"] == network_stats.UNREACHABLE
        assert "difficulty" not in stats
        again, seen_again = _read(_mempool)
        assert again["state"] == network_stats.UNREACHABLE
        assert seen_again == []

    @pytest.mark.parametrize(
        ("hashrate", "rewards"),
        [
            ({"currentDifficulty": 0}, REWARD_ANSWER),
            ({"currentDifficulty": "nan"}, REWARD_ANSWER),
            ({}, REWARD_ANSWER),
            (HASHRATE_ANSWER, {**REWARD_ANSWER, "totalReward": "abc"}),
            (HASHRATE_ANSWER, {**REWARD_ANSWER, "endBlock": 977000}),
            (HASHRATE_ANSWER, {**REWARD_ANSWER, "startBlock": True}),
            (HASHRATE_ANSWER, []),
        ],
    )
    def test_an_answer_without_usable_figures_is_unreachable_never_zero(self, hashrate, rewards):
        def answer(request):
            return httpx.Response(200, json=hashrate if "hashrate" in request.url.path else rewards)

        stats, _ = _read(answer)
        assert stats["state"] == network_stats.UNREACHABLE


class TestEndpoint:
    """The device row on /api/fleet/economics."""

    def _device(self, *, hashrate=(1.2e12, "2026-11-26T10:00:00+00:00"), stats=None, slug="ocean", btc_usd=90000.0):
        from tests.test_machine_economics import TestEndpoint as Base

        known = {
            "state": network_stats.KNOWN,
            "difficulty": DIFFICULTY,
            "reward_btc_per_block": REWARD_BTC,
            "reward_blocks": 144,
            "source": "mempool.space",
        }
        bitcoin = AsyncMock(return_value=stats or known)
        readings = {} if hashrate is None else {slug: hashrate}
        to_usd = (lambda amount, currency: amount * btc_usd if currency == "BTC" else None) if btc_usd else None
        with (
            patch("app.main._pool_hashrate", readings),
            patch("app.main.network_stats.bitcoin", bitcoin),
            patch("app.main.exchange_rates.to_usd", to_usd or (lambda amount, currency: None)),
        ):
            out = Base()._call(
                config={"power_currency": "USD", "power_price_per_kwh": "0.20", "power_device_ocean_watts": "18"},
                earned={slug: 0.85},
                deployments=[{"slug": slug, "status": "external"}],
            )
        (device,) = out["machines"]
        return device, bitcoin

    def test_a_bitcoin_pool_with_a_hashrate_gets_an_estimate_next_to_its_credit(self):
        device, _ = self._device()
        expected = device["expected"]
        coin = network_stats.expected_btc_per_day(1.2e12, DIFFICULTY, REWARD_BTC) * 30
        assert expected["estimate"] is True
        assert expected["state"] == network_stats.KNOWN
        assert expected["currency"] == "BTC"
        assert expected["hashrate_hs"] == 1.2e12
        assert expected["monthly_coin"] == pytest.approx(coin, abs=1e-8)
        assert expected["monthly_usd"] == pytest.approx(coin * 90000.0, abs=0.0001)
        assert expected["source"] == "mempool.space"
        # What the pool credited is still the gross, untouched.
        assert device["monthly_gross"] == 0.85

    def test_the_estimate_never_changes_gross_cost_or_net(self):
        with_estimate, _ = self._device()
        without, _ = self._device(hashrate=None)
        assert without["expected"] is None
        for key in ("monthly_gross", "monthly_cost", "monthly_net", "verdict", "break_even_tariff"):
            assert with_estimate[key] == without[key]

    def test_no_reported_hashrate_means_no_estimate_and_no_network_read(self):
        device, bitcoin = self._device(hashrate=None)
        assert device["expected"] is None
        bitcoin.assert_not_awaited()

    def test_a_failed_network_read_says_so_and_estimates_nothing(self):
        device, _ = self._device(stats={"state": network_stats.UNREACHABLE, "detail": "ReadTimeout while reading"})
        expected = device["expected"]
        assert expected["state"] == network_stats.UNREACHABLE
        assert expected["detail"] == "ReadTimeout while reading"
        assert "monthly_coin" not in expected and "monthly_usd" not in expected

    def test_without_a_bitcoin_price_the_estimate_stays_in_bitcoin(self):
        device, _ = self._device(btc_usd=None)
        assert device["expected"]["monthly_coin"] > 0
        assert device["expected"]["monthly_usd"] is None

    def test_a_pool_paying_another_coin_gets_no_bitcoin_estimate(self):
        device, bitcoin = self._device(slug="2miners-etc")
        assert device["expected"] is None
        bitcoin.assert_not_awaited()


class TestOceanHashrate:
    def _collect(self, result):
        collector = OceanCollector("bc1q4efd2vns8qwawg3nt4xxzs9053shh0q3x0tuu9")
        collector._client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"result": result}))
        )

        async def go():
            try:
                return await collector.collect()
            finally:
                await collector.close()

        return asyncio.run(go())

    def test_the_5_minute_hashrate_comes_with_the_balance(self):
        out = self._collect({"unpaid": "0.001", "hashrate_300s": "1200000000000"})
        assert out.error is None
        assert out.hashrate == 1.2e12

    @pytest.mark.parametrize("value", [None, "abc", "-5", "inf"])
    def test_a_missing_or_bad_hashrate_is_none_never_zero(self, value):
        out = self._collect({"unpaid": "0.001", "hashrate_300s": value})
        assert out.error is None
        assert out.balance == 0.001
        assert out.hashrate is None


class TestCollectionLoop:
    def _run(self, result, previous=None):
        from app import main

        collector = OceanCollector("bc1q4efd2vns8qwawg3nt4xxzs9053shh0q3x0tuu9")
        collector.collect = AsyncMock(return_value=result)
        readings = dict(previous or {})
        with (
            patch("app.main._pool_hashrate", readings),
            patch("app.main._collector_alerts", []),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[{"slug": "ocean"}]),
            patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
            patch("app.collectors.make_collectors", return_value=[collector]),
            patch("app.collectors._close_stale", new_callable=AsyncMock),
            patch("app.main.database.record_alert", new_callable=AsyncMock, return_value=None),
            patch("app.main.database.clear_alerts", new_callable=AsyncMock),
            patch("app.main.database.upsert_earnings", new_callable=AsyncMock),
            patch("app.main._detect_payout", new_callable=AsyncMock, return_value=None),
            patch("app.main._pending_payout_alerts", new_callable=AsyncMock, return_value=[]),
            patch("app.main._flatline_check", new_callable=AsyncMock, return_value=[]),
            patch("app.main._offline_worker_alerts", new_callable=AsyncMock, return_value=[]),
        ):
            asyncio.run(main._run_collection())
        return readings

    def test_a_good_read_keeps_the_pool_hashrate(self):
        readings = self._run(EarningsResult(platform="ocean", balance=0.001, currency="BTC", hashrate=1.2e12))
        assert readings["ocean"][0] == 1.2e12

    def test_a_good_read_without_a_hashrate_drops_the_old_one(self):
        old = {"ocean": (1.2e12, "2026-11-25T00:00:00+00:00")}
        readings = self._run(EarningsResult(platform="ocean", balance=0.001, currency="BTC"), previous=old)
        assert "ocean" not in readings

    def test_a_failed_read_stores_no_hashrate(self):
        readings = self._run(EarningsResult(platform="ocean", balance=0.0, currency="BTC", error="timeout"))
        assert readings == {}
