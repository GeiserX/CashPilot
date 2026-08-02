"""Net profit rather than gross (CashPilot-f5u).

Every dashboard in this space reports what a service paid and none report what
it cost to run. For a lot of users the honest number is negative.

The tests that matter most here are the honesty ones: an estimate must never be
dressed up as a measurement, gross must never be rendered as net, and a machine
the user does not pay power for must not be charged an invented cost.
"""

from __future__ import annotations

import pytest

from app import power


class TestWattsEstimate:
    def test_a_busy_container_draws_more_than_an_idle_one(self):
        idle = power.estimate_watts(0.0, host_tdp_watts=100.0)
        busy = power.estimate_watts(100.0, host_tdp_watts=100.0)
        assert busy > idle

    def test_an_idle_container_is_not_free(self):
        """It holds a share of a machine that is already switched on."""
        assert power.estimate_watts(0.0, host_tdp_watts=100.0) > 0

    def test_the_idle_floor_is_shared_not_charged_to_each_container(self):
        """Ten containers on one host must not be billed ten idle floors."""
        alone = power.estimate_watts(0.0, host_tdp_watts=100.0, container_count=1)
        shared = power.estimate_watts(0.0, host_tdp_watts=100.0, container_count=10)
        assert shared == pytest.approx(alone / 10)

    def test_a_saturated_container_approaches_the_host_draw(self):
        w = power.estimate_watts(100.0, host_tdp_watts=100.0, container_count=1)
        assert w == pytest.approx(100.0)

    def test_nonsense_inputs_do_not_produce_nonsense_costs(self):
        assert power.estimate_watts(-50.0, host_tdp_watts=100.0) >= 0
        assert power.estimate_watts(10.0, host_tdp_watts=-1.0) == 0.0
        assert power.estimate_watts(10.0, host_tdp_watts=100.0, container_count=0) > 0


class TestEnergyCost:
    def test_a_known_case_computes_correctly(self):
        # 15 W for 730 h (a month) at 0.30/kWh = 3.285
        assert power.energy_cost(15.0, 730.0, 0.30) == pytest.approx(3.285, abs=1e-6)

    @pytest.mark.parametrize("watts,hours,price", [(0, 730, 0.3), (15, 0, 0.3), (15, 730, 0), (-5, 730, 0.3)])
    def test_missing_or_absurd_inputs_cost_nothing(self, watts, hours, price):
        assert power.energy_cost(watts, hours, price) == 0.0


class TestTheHonestyRules:
    def test_a_service_that_costs_more_than_it_pays_is_flagged(self):
        """The bead's motivating case: EUR 2/month on 15W at EUR 0.30/kWh."""
        cost = power.energy_cost(15.0, 730.0, 0.30)
        row = power.net_for_service(gross=2.0, cost=cost)
        assert row["net"] < 0
        assert row["negative"] is True

    def test_a_genuinely_profitable_service_is_not_flagged(self):
        row = power.net_for_service(gross=20.0, cost=3.285)
        assert row["negative"] is False
        assert row["net"] == pytest.approx(16.715)

    def test_every_cost_carries_its_quality(self):
        """An estimate must never be presented as a measurement."""
        assert power.net_for_service(1.0, 0.5)["cost_quality"] == power.ESTIMATED
        assert power.net_for_service(1.0, 0.5, quality=power.MEASURED)["cost_quality"] == power.MEASURED

    def test_gross_is_always_reported_alongside_net(self):
        row = power.net_for_service(gross=5.0, cost=1.0)
        assert row["gross"] == 5.0 and row["net"] == 4.0

    def test_an_unmetered_host_is_not_charged_an_invented_cost(self):
        """A VPS bill does not move with CPU; charging watts would invent a cost."""
        assert power.is_metered({"metered": False}) is False
        assert power.is_metered({"metered": True}) is True
        assert power.is_metered(None) is True, "default to charging, not to hiding cost"
        assert power.is_metered({}) is True


class TestSummary:
    SERVICES = [
        {"platform": "tiny", "gross": 2.0, "watts": 15.0, "hours": 730.0},
        {"platform": "good", "gross": 20.0, "watts": 15.0, "hours": 730.0},
    ]

    def test_it_reports_totals_and_names_the_loss_makers(self):
        out = power.summarise(self.SERVICES, price_per_kwh=0.30)
        assert out["cost_known"] is True
        assert out["total_gross"] == pytest.approx(22.0)
        assert out["total_net"] == pytest.approx(22.0 - 2 * 3.285)
        assert out["negative_services"] == ["tiny"]

    def test_without_a_tariff_it_says_the_cost_is_unknown(self):
        """A zero cost would render gross as net and overstate earnings."""
        out = power.summarise(self.SERVICES, price_per_kwh=0.0)
        assert out["cost_known"] is False
        assert out["total_net"] is None
        assert out["total_cost"] is None
        assert out["price_per_kwh"] is None
        assert out["total_gross"] == pytest.approx(22.0)
        assert out["negative_services"] == []

    def test_a_service_on_an_unmetered_host_costs_nothing(self):
        out = power.summarise(
            [{"platform": "vps", "gross": 1.0, "watts": 0.0, "hours": 730.0}],
            price_per_kwh=0.30,
        )
        assert out["services"][0]["cost"] == 0.0
        assert out["services"][0]["negative"] is False

    def test_the_currency_is_carried_through(self):
        assert power.summarise([], price_per_kwh=0.3, currency="GBP")["currency"] == "GBP"


class TestUnknownTariffIsNotZero:
    """The honesty rule, at the PER-SERVICE level.

    Regression: the totals correctly reported cost_known false and total_net
    None, while each service row still reported net == gross — presenting
    earnings as profit, which is exactly what this module exists to prevent.
    """

    def test_a_service_row_reports_unknown_not_gross_as_net(self):
        out = power.summarise(
            [{"platform": "x", "gross": 5.0, "watts": 15.0, "hours": 730.0}],
            price_per_kwh=0.0,
        )
        row = out["services"][0]
        assert row["gross"] == 5.0
        assert row["cost"] is None, "an unknown cost must not be reported as zero"
        assert row["net"] is None, "net must not equal gross when the cost is unknown"
        assert row["cost_quality"] == "unknown"
        assert row["negative"] is False

    def test_nothing_is_flagged_negative_when_the_cost_is_unknown(self):
        out = power.summarise(
            [{"platform": "x", "gross": 0.01, "watts": 99.0, "hours": 730.0}],
            price_per_kwh=0.0,
        )
        assert out["negative_services"] == []

    def test_a_configured_tariff_still_reports_real_numbers(self):
        row = power.summarise(
            [{"platform": "x", "gross": 2.0, "watts": 15.0, "hours": 730.0}],
            price_per_kwh=0.30,
        )["services"][0]
        assert row["cost"] is not None and row["net"] is not None
        assert row["negative"] is True


class TestEarnedOverTheWindow:
    """Net must subtract a window's cost from that window's EARNINGS.

    Regression: the endpoint used the latest balance — a running total — so a
    30-day electricity cost was charged against a lifetime of earnings.
    """

    def test_earned_is_the_window_delta_not_the_balance(self, tmp_path):
        import asyncio
        from datetime import UTC, datetime, timedelta
        from unittest.mock import patch

        from app import database

        def day(n):
            return (datetime.now(UTC) - timedelta(days=n)).strftime("%Y-%m-%d")

        async def run():
            with (
                patch.object(database, "DB_DIR", tmp_path),
                patch.object(database, "DB_PATH", tmp_path / "t.db"),
            ):
                await database.init_db()
                # Balance climbs 100 -> 103 over the window: earned 3, not 103.
                for i, bal in ((3, 100.0), (2, 101.0), (1, 103.0)):
                    await database.upsert_earnings("svc", bal, date=day(i))
                return await database.get_earned_by_platform(days=30)

        assert asyncio.run(run())["svc"] == pytest.approx(3.0)

    def test_a_payout_does_not_read_as_negative_earnings(self, tmp_path):
        """Same clamping rule as the dashboard (CashPilot-glc)."""
        import asyncio
        from datetime import UTC, datetime, timedelta
        from unittest.mock import patch

        from app import database

        def day(n):
            return (datetime.now(UTC) - timedelta(days=n)).strftime("%Y-%m-%d")

        async def run():
            with (
                patch.object(database, "DB_DIR", tmp_path),
                patch.object(database, "DB_PATH", tmp_path / "t2.db"),
            ):
                await database.init_db()
                for i, bal in ((3, 20.0), (2, 0.10), (1, 1.10)):  # payout then earning
                    await database.upsert_earnings("svc", bal, date=day(i))
                return await database.get_earned_by_platform(days=30)

        assert asyncio.run(run())["svc"] == pytest.approx(1.0), "payout must not go negative"


class TestNetEndpoint:
    """The endpoint wiring: config parsing, windowing, and the honesty rules end to end."""

    def _call(self, cfg, earned, containers, days=30, workers=None):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from app import main

        async def run():
            with (
                patch.object(main, "_require_auth_api", lambda r: None),
                patch.object(main.database, "get_config", AsyncMock(return_value=cfg)),
                patch.object(main.database, "get_earned_by_platform", AsyncMock(return_value=earned)),
                patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=containers)),
                patch.object(main.database, "list_workers", AsyncMock(return_value=workers or [])),
            ):
                return await main.api_earnings_net(MagicMock(), days=days)

        return asyncio.run(run())

    def test_it_reports_net_when_a_tariff_is_configured(self):
        out = self._call(
            {"power_price_per_kwh": "0.30", "power_currency": "EUR", "power_host_tdp_watts": "65"},
            {"svc": 2.0},
            [{"service": "svc", "status": "running", "cpu_percent": 5.0}],
        )
        assert out["cost_known"] is True
        assert out["currency"] == "EUR"
        assert out["services"][0]["net"] is not None
        assert out["window_days"] == 30

    def test_without_a_tariff_it_reports_unknown_not_gross_as_net(self):
        out = self._call({}, {"svc": 2.0}, [{"service": "svc", "status": "running", "cpu_percent": 5.0}])
        assert out["cost_known"] is False
        assert out["services"][0]["net"] is None
        assert out["total_net"] is None

    def test_a_stopped_container_does_not_dilute_the_idle_floor(self):
        """A stopped container draws nothing and must not be counted."""
        busy = self._call(
            {"power_price_per_kwh": "0.30"},
            {"svc": 2.0},
            [
                {"service": "svc", "status": "running", "cpu_percent": 5.0},
                {"service": "other", "status": "exited", "cpu_percent": 0.0},
            ],
        )
        alone = self._call(
            {"power_price_per_kwh": "0.30"},
            {"svc": 2.0},
            [{"service": "svc", "status": "running", "cpu_percent": 5.0}],
        )
        assert busy["services"][0]["cost"] == pytest.approx(alone["services"][0]["cost"])

    def test_a_worker_status_failure_does_not_break_the_earnings_figures(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from app import main

        async def run():
            with (
                patch.object(main, "_require_auth_api", lambda r: None),
                patch.object(main.database, "get_config", AsyncMock(return_value={"power_price_per_kwh": "0.30"})),
                patch.object(main.database, "get_earned_by_platform", AsyncMock(return_value={"svc": 7.0})),
                patch.object(main, "_get_all_worker_containers", AsyncMock(side_effect=RuntimeError("worker down"))),
                patch.object(main.database, "list_workers", AsyncMock(return_value=[])),
            ):
                return await main.api_earnings_net(MagicMock(), days=30)

        out = asyncio.run(run())
        assert out["total_gross"] == pytest.approx(7.0), "gross comes from the DB and is still reportable"

    def test_a_malformed_tariff_is_treated_as_unset_rather_than_crashing(self):
        out = self._call({"power_price_per_kwh": "not-a-number"}, {"svc": 1.0}, [])
        assert out["cost_known"] is False


class TestPerWorkerAttribution:
    """Each host pays its own idle draw (CashPilot-yh5).

    Collapsing a fleet into one count charged a single idle floor for the whole
    estate, and left no per-worker context for power.is_metered — so a VPS was
    billed like a home server.
    """

    def _call(self, containers, workers, price="0.30"):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from app import main

        async def run():
            with (
                patch.object(main, "_require_auth_api", lambda r: None),
                patch.object(main.database, "get_config", AsyncMock(return_value={"power_price_per_kwh": price})),
                patch.object(
                    main.database,
                    "get_earned_by_platform",
                    AsyncMock(return_value={c["service"]: 10.0 for c in containers}),
                ),
                patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=containers)),
                patch.object(main.database, "list_workers", AsyncMock(return_value=workers)),
            ):
                return await main.api_earnings_net(MagicMock(), days=30)

        return asyncio.run(run())

    def test_two_hosts_are_charged_two_idle_floors(self):
        """One container on each of two hosts costs more than two on one host."""
        two_hosts = self._call(
            [
                {"service": "a", "status": "running", "cpu_percent": 0.0, "_worker_id": 1},
                {"service": "b", "status": "running", "cpu_percent": 0.0, "_worker_id": 2},
            ],
            [{"id": 1, "system_info": "{}"}, {"id": 2, "system_info": "{}"}],
        )
        one_host = self._call(
            [
                {"service": "a", "status": "running", "cpu_percent": 0.0, "_worker_id": 1},
                {"service": "b", "status": "running", "cpu_percent": 0.0, "_worker_id": 1},
            ],
            [{"id": 1, "system_info": "{}"}],
        )
        assert two_hosts["total_cost"] > one_host["total_cost"], (
            "two machines burn two idle floors; collapsing them charged only one"
        )
        assert two_hosts["total_cost"] == pytest.approx(one_host["total_cost"] * 2, rel=0.01)

    def test_an_unmetered_host_contributes_no_cost(self):
        """A VPS bill does not move with CPU."""
        out = self._call(
            [
                {"service": "home", "status": "running", "cpu_percent": 10.0, "_worker_id": 1},
                {"service": "vps", "status": "running", "cpu_percent": 10.0, "_worker_id": 2},
            ],
            [
                {"id": 1, "system_info": "{}"},
                {"id": 2, "system_info": '{"metered": false}'},
            ],
        )
        rows = {r["platform"]: r for r in out["services"]}
        assert rows["vps"]["cost"] == 0.0, "an unmetered host must not be charged"
        assert rows["home"]["cost"] > 0.0

    def test_a_per_worker_tdp_is_honoured(self):
        """A 200W server must not be costed as a 65W mini PC."""
        big = self._call(
            [{"service": "a", "status": "running", "cpu_percent": 50.0, "_worker_id": 1}],
            [{"id": 1, "system_info": '{"host_tdp_watts": 200}'}],
        )
        small = self._call(
            [{"service": "a", "status": "running", "cpu_percent": 50.0, "_worker_id": 1}],
            [{"id": 1, "system_info": '{"host_tdp_watts": 65}'}],
        )
        assert big["total_cost"] > small["total_cost"]

    def test_a_service_spread_over_two_hosts_accumulates_both(self):
        one = self._call(
            [{"service": "a", "status": "running", "cpu_percent": 20.0, "_worker_id": 1}],
            [{"id": 1, "system_info": "{}"}],
        )
        two = self._call(
            [
                {"service": "a", "status": "running", "cpu_percent": 20.0, "_worker_id": 1},
                {"service": "a", "status": "running", "cpu_percent": 20.0, "_worker_id": 2},
            ],
            [{"id": 1, "system_info": "{}"}, {"id": 2, "system_info": "{}"}],
        )
        assert two["services"][0]["cost"] > one["services"][0]["cost"]
