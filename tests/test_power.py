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
