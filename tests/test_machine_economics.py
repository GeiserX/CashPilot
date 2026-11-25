"""Machine-level break-even (CashPilot-l01).

The interesting tests here are the REFUSALS.

Adding a bandwidth container to a machine that is already on costs 1-3 W, which
is below what a consumer smart plug can measure. A per-service "net profit"
there would look authoritative and be noise, so the module declines to produce
one. That refusal is the feature.

What it will answer is the machine-level question, because that one has a real
answer: a dedicated 65 W node at EUR 0.20/kWh costs about EUR 9.50 a month
against a typical USD 3-6 gross from a single node.
"""

from __future__ import annotations

import pytest

from app import machine_economics as me


class TestItRefusesFabricatedPrecision:
    @pytest.mark.parametrize("watts", [0.5, 1.0, 2.0, 3.0, 4.9])
    def test_a_bandwidth_container_is_too_small_to_cost_out(self, watts):
        """1-3 W is below a consumer smart plug's own measurement error."""
        assert me.per_service_is_meaningful(watts) is False

    @pytest.mark.parametrize("watts", [5.0, 40.0, 250.0])
    def test_a_large_marginal_draw_is_worth_costing_out(self, watts):
        assert me.per_service_is_meaningful(watts) is True

    def test_an_unknown_marginal_draw_is_not_meaningful(self):
        assert me.per_service_is_meaningful(None) is False


class TestTheHonestUnknowns:
    def test_no_tariff_means_no_verdict(self):
        out = me.assess_machine(name="box", monthly_gross=4.0, watts=65.0, price_per_kwh=None)
        assert out["verdict"] == me.UNKNOWN
        assert out["monthly_net"] is None
        assert "electricity price" in out["summary"]

    def test_no_wattage_means_no_verdict(self):
        out = me.assess_machine(name="box", monthly_gross=4.0, watts=None, price_per_kwh=0.20)
        assert out["verdict"] == me.UNKNOWN
        assert out["monthly_cost"] is None
        assert "power draw" in out["summary"]

    def test_it_says_guessing_would_be_worse_than_silence(self):
        out = me.assess_machine(name="box", monthly_gross=4.0, watts=None, price_per_kwh=None)
        assert "guessing would be worse" in out["summary"]

    def test_a_vps_is_not_judged_on_electricity(self):
        """The bill does not move with CPU, so estimated watts invent a cost."""
        out = me.assess_machine(name="vps", monthly_gross=4.0, watts=65.0, price_per_kwh=0.20, metered=False)
        assert out["verdict"] == me.NOT_METERED
        assert out["monthly_cost"] is None

    def test_every_figure_is_labelled_an_estimate(self):
        out = me.assess_machine(name="box", monthly_gross=4.0, watts=65.0, price_per_kwh=0.20)
        assert out["quality"] == "estimated"


class TestTheAnswerThatMatters:
    def test_a_dedicated_node_that_loses_money_says_so_plainly(self):
        """The bead's own worked example: ~65 W at 0.20/kWh is ~9.50 a month."""
        out = me.assess_machine(name="node", monthly_gross=4.0, watts=65.0, price_per_kwh=0.20, dedicated=True)
        assert out["verdict"] == me.LOSING_MONEY
        assert out["monthly_cost"] == pytest.approx(9.49, abs=0.05)
        assert out["monthly_net"] < 0
        assert "turning it off would save that" in out["summary"]

    def test_a_shared_machine_is_not_blamed_for_being_on(self):
        """A NAS would be on anyway; the services did not cause its draw."""
        out = me.assess_machine(name="nas", monthly_gross=4.0, watts=65.0, price_per_kwh=0.20, dedicated=False)
        assert out["verdict"] == me.LOSING_MONEY
        assert "would be on anyway" in out["summary"]
        assert "turning it off" not in out["summary"]

    def test_a_clearly_profitable_machine_is_reported_as_such(self):
        out = me.assess_machine(name="box", monthly_gross=50.0, watts=10.0, price_per_kwh=0.10)
        assert out["verdict"] == me.PROFITABLE

    def test_near_break_even_is_admitted_to_be_indistinguishable(self):
        out = me.assess_machine(name="box", monthly_gross=9.6, watts=65.0, price_per_kwh=0.20)
        assert out["verdict"] == me.MARGINAL
        assert "cannot really tell them apart" in out["summary"]


class TestBreakEven:
    def test_break_even_watts_is_the_draw_that_exactly_pays_for_itself(self):
        watts = me.break_even_watts(monthly_gross=9.49, price_per_kwh=0.20)
        assert watts == pytest.approx(65.0, abs=0.5)

    def test_break_even_price_is_the_tariff_where_it_stops_being_worth_it(self):
        price = me.break_even_price(monthly_gross=9.49, watts=65.0)
        assert price == pytest.approx(0.20, abs=0.005)

    def test_without_a_tariff_there_is_no_break_even_wattage(self):
        assert me.break_even_watts(10.0, 0.0) is None

    def test_without_a_draw_there_is_no_break_even_price(self):
        assert me.break_even_price(10.0, 0.0) is None

    def test_cost_is_zero_for_nonsense_inputs_rather_than_negative(self):
        assert me.monthly_cost(-5, 0.2) == 0.0
        assert me.monthly_cost(65, -1) == 0.0

    def test_break_even_is_reported_before_a_tariff_is_entered(self):
        """It needs only gross and watts: the price this machine could stand.

        An 18 W miner earning 0.99 a month uses 13.14 kWh, so it pays for itself
        below 0.99 / 13.14 = 0.0753 a kWh, whatever the user pays.
        """
        out = me.assess_machine(name="bitaxe", monthly_gross=0.99, watts=18.0, price_per_kwh=None)
        assert out["verdict"] == me.UNKNOWN
        assert out["break_even_price_per_kwh"] == pytest.approx(0.0753, abs=0.0001)
        assert out["quality"] == "estimated"

    def test_a_machine_that_earned_nothing_breaks_even_at_zero(self):
        out = me.assess_machine(name="box", monthly_gross=0.0, watts=65.0, price_per_kwh=None)
        assert out["break_even_price_per_kwh"] == 0.0
        assert "loses money at any electricity price" in out["summary"]

    def test_an_unreported_machine_has_no_break_even(self):
        """None gross is a machine we cannot see, not one that earned nothing."""
        out = me.assess_machine(name="box", monthly_gross=None, watts=65.0, price_per_kwh=None)
        assert "break_even_price_per_kwh" not in out

    def test_an_unread_gross_has_no_break_even(self):
        out = me.assess_machine(name="box", monthly_gross=0.0, watts=65.0, price_per_kwh=None, gross_measured=False)
        assert "break_even_price_per_kwh" not in out
        assert "guessing would be worse" in out["summary"]

    def test_without_watts_there_is_no_break_even_tariff(self):
        out = me.assess_machine(name="box", monthly_gross=4.0, watts=None, price_per_kwh=None)
        assert "break_even_price_per_kwh" not in out
        assert "guessing would be worse" in out["summary"]


class TestFleetRollUp:
    def _machine(self, name, gross, cost, verdict=me.PROFITABLE):
        return {"machine": name, "monthly_gross": gross, "monthly_cost": cost, "verdict": verdict}

    def test_machines_with_unknown_cost_are_counted_not_folded_in_as_zero(self):
        """Otherwise the fleet total quietly understates what it costs."""
        out = me.fleet_summary([self._machine("a", 10.0, 5.0), self._machine("b", 10.0, None)])
        assert out["cost_known_for"] == 1
        assert out["cost_unknown_for"] == 1
        assert out["monthly_cost"] == 5.0
        assert "known for 1 of 2" in out["summary"]

    def test_it_names_the_machines_losing_money(self):
        out = me.fleet_summary([self._machine("good", 20.0, 2.0), self._machine("bad", 1.0, 9.0, me.LOSING_MONEY)])
        assert out["losing_money"] == ["bad"]

    def test_an_all_known_fleet_reports_a_net(self):
        out = me.fleet_summary([self._machine("a", 10.0, 4.0), self._machine("b", 5.0, 1.0)])
        assert out["monthly_gross"] == 15.0
        assert out["monthly_net"] == 10.0

    def test_a_fleet_with_no_cost_data_reports_no_net(self):
        out = me.fleet_summary([self._machine("a", 10.0, None)])
        assert out["monthly_net"] is None

    def test_an_empty_fleet_does_not_explode(self):
        out = me.fleet_summary([])
        assert out["monthly_gross"] == 0.0


class TestItNeverActsOnTheNumber:
    def test_the_module_cannot_stop_or_change_anything(self):
        """No auto-stop, no throttle. The electricity is the operator's."""
        import ast
        import pathlib

        tree = ast.parse(pathlib.Path(me.__file__).read_text(encoding="utf-8"))
        called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        for forbidden in ("stop", "remove", "restart", "kill", "pause", "post", "delete"):
            assert forbidden not in called, f"machine_economics calls {forbidden!r} — it must only report"


class TestEndpoint:
    def _call(self, config=None, workers=None, earned=None, containers=None, measured=None, deployments=None):
        import asyncio
        import json
        from unittest.mock import AsyncMock, MagicMock, patch

        from app import main

        rows = [
            {
                "id": w["id"],
                "client_id": f"c{w['id']}",
                "name": w["name"],
                "status": "online",
                "containers": json.dumps([]),
                "system_info": json.dumps(w.get("system_info", {})),
                "apps": json.dumps([]),
            }
            for w in (workers or [])
        ]

        async def run():
            with (
                patch.object(main, "_require_auth_api", lambda r: None),
                patch.object(main.database, "get_config", AsyncMock(return_value=config or {})),
                patch.object(main.database, "list_workers", AsyncMock(return_value=rows)),
                patch.object(main.database, "get_deployments", AsyncMock(return_value=deployments or [])),
                patch.object(main.database, "get_earned_by_platform", fake_earned),
                patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=containers or [])),
            ):
                return await main.api_fleet_economics(MagicMock())

        # Every platform in `earned` counts as read unless `measured` says
        # otherwise, the way the real reader marks a priced delta.
        async def fake_earned(days=30, measured=None, _read=measured):
            if measured is not None:
                measured.update((earned or {}) if _read is None else _read)
            return earned or {}

        return asyncio.run(run())

    WORKERS = [{"id": 1, "name": "charlie"}, {"id": 2, "name": "alpha"}]

    def test_without_a_tariff_every_machine_reports_unknown(self):
        out = self._call(workers=self.WORKERS)
        assert out["monthly_cost"] is None
        assert all(m["verdict"] == me.UNKNOWN for m in out["machines"])

    def test_earnings_are_attributed_to_the_machine_running_the_service(self):
        out = self._call(
            config={"electricity_price_per_kwh": "0.20", "worker_1_watts": "65"},
            workers=self.WORKERS,
            earned={"honeygain": 4.0},
            containers=[{"slug": "honeygain", "status": "running", "_worker_id": 1}],
        )
        by_name = {m["machine"]: m for m in out["machines"]}
        assert by_name["charlie"]["monthly_gross"] == 4.0
        assert by_name["alpha"]["monthly_gross"] == 0.0
        assert by_name["charlie"]["verdict"] == me.LOSING_MONEY

    def test_a_service_on_two_machines_splits_its_gross(self):
        """Without per-node earnings there is no better answer than an even split."""
        out = self._call(
            config={"electricity_price_per_kwh": "0.20"},
            workers=self.WORKERS,
            earned={"honeygain": 10.0},
            containers=[
                {"slug": "honeygain", "status": "running", "_worker_id": 1},
                {"slug": "honeygain", "status": "running", "_worker_id": 2},
            ],
        )
        assert all(m["monthly_gross"] == 5.0 for m in out["machines"])

    def test_a_malformed_tariff_is_treated_as_absent_not_as_zero_cost(self):
        out = self._call(config={"electricity_price_per_kwh": "cheap"}, workers=self.WORKERS)
        assert all(m["verdict"] == me.UNKNOWN for m in out["machines"])

    def test_an_empty_fleet_returns_an_empty_summary(self):
        out = self._call()
        assert out["machines"] == []

    @pytest.mark.parametrize("watts", [None, "0", "-10", "nan", "inf", "5e-324"])
    def test_a_tracked_pool_with_no_valid_watts_has_unknown_cost(self, watts):
        out = self._call(
            config={"power_currency": "USD", "power_price_per_kwh": "0.20", "power_device_ocean_watts": watts},
            earned={"ocean": 8.0},
            deployments=[{"slug": "ocean", "status": "external"}],
        )
        (device,) = out["machines"]
        assert device["kind"] == "device"
        assert device["slug"] == "ocean"
        assert device["gross_basis"] == "accrued"
        assert device["monthly_gross"] == 8.0
        assert device["monthly_cost"] is None
        assert device["break_even_tariff"] is None
        assert out["cost_unknown_for"] == 1

    def test_a_tracked_pool_uses_entered_wall_watts_in_fleet_totals(self):
        out = self._call(
            config={"power_currency": "USD", "power_price_per_kwh": "0.20", "power_device_ocean_watts": "10"},
            earned={"ocean": 8.0},
            deployments=[{"slug": "ocean", "status": "external"}, {"slug": "grass", "status": "external"}],
        )
        (device,) = out["machines"]
        assert device["watts"] == 10.0
        assert device["break_even_tariff"] == {"currency": "USD", "price_per_kwh": pytest.approx(8 / 7.3, abs=0.0001)}
        assert device["monthly_cost"] == pytest.approx(1.46)
        assert out["monthly_net"] == pytest.approx(6.54)

    def test_pool_gross_is_a_period_accrual_not_the_unpaid_balance(self):
        out = self._call(
            earned={"ocean": 8.0},
            deployments=[{"slug": "ocean", "status": "external"}],
        )
        (device,) = out["machines"]
        assert device["gross_basis"] == "accrued"
        assert "Earnings accrued at the pool during this period." in device["summary"]

    def test_a_pool_without_a_priced_reading_does_not_get_a_zero_break_even(self):
        out = self._call(
            config={"power_currency": "USD", "power_device_ocean_watts": "10"},
            earned={"ocean": 0.0},
            measured=set(),
            deployments=[{"slug": "ocean", "status": "external"}],
        )
        (device,) = out["machines"]
        assert device["watts"] == 10.0
        assert device["monthly_gross"] is None
        assert device["break_even_tariff"] is None

    @pytest.mark.parametrize(
        ("slug", "service"),
        [
            ("xmrig", {"name": "XMRig", "category": "mining"}),
            ("render-gpu", {"name": "Render host", "category": "compute", "requirements": {"gpu": True}}),
        ],
    )
    def test_a_service_running_on_a_worker_is_counted_once(self, slug, service):
        from unittest.mock import patch

        from app import catalog

        with patch.object(catalog, "get_service", return_value=service):
            out = self._call(
                config={"power_currency": "USD", "power_price_per_kwh": "0.20", "worker_c1_watts": "100"},
                workers=self.WORKERS[:1],
                earned={slug: 8.0},
                containers=[{"slug": slug, "status": "running", "_worker_id": 1}],
                deployments=[{"slug": slug, "status": "external"}],
            )
        (machine,) = out["machines"]
        assert machine["kind"] == "machine"
        assert out["monthly_gross"] == 8.0
        assert out["monthly_cost"] == 14.6

    def _fx(self, from_usd, to_usd):
        from unittest.mock import patch

        from app import main

        return (
            patch.object(main.exchange_rates, "from_usd", from_usd),
            patch.object(main.exchange_rates, "to_usd", to_usd),
        )

    def test_break_even_is_in_the_tariff_currency(self):
        """A price per kWh is read against a bill, so it is in the bill's currency."""
        a, b = self._fx(lambda v, cur: v * 0.9, lambda v, cur: v / 0.9)
        with a, b:
            out = self._call(
                config={"power_currency": "EUR", "worker_c1_watts": "18"},
                workers=self.WORKERS,
                earned={"miner": 0.99},
                containers=[{"slug": "miner", "status": "running", "_worker_id": 1}],
            )
        by_name = {m["machine"]: m for m in out["machines"]}
        be = by_name["charlie"]["break_even_tariff"]
        assert be["currency"] == "EUR"
        assert be["price_per_kwh"] == pytest.approx(0.0753 * 0.9, abs=0.0001)
        assert by_name["alpha"]["break_even_tariff"] is None, "no watts typed, so no break-even"
        assert out["tariff_currency"] == "EUR"
        assert out["tariff_price_per_kwh"] is None, "no tariff typed"

    def test_break_even_without_fx_is_labelled_usd(self):
        """No rate: the USD figure labelled USD, never USD labelled EUR."""
        a, b = self._fx(lambda v, cur: None, lambda v, cur: None)
        with a, b:
            out = self._call(
                config={"power_currency": "EUR", "power_price_per_kwh": "0.25", "worker_c1_watts": "18"},
                workers=self.WORKERS,
                earned={"miner": 0.99},
                containers=[{"slug": "miner", "status": "running", "_worker_id": 1}],
            )
        be = {m["machine"]: m for m in out["machines"]}["charlie"]["break_even_tariff"]
        assert be == {"price_per_kwh": pytest.approx(0.0753, abs=0.0001), "currency": "USD"}
        assert out["tariff_currency"] == "EUR"
        assert out["tariff_price_per_kwh"] == 0.25

    def test_a_gross_nobody_read_gets_no_break_even(self):
        """No collector, no credentials or no rate: 0.0 is missing data, not zero.

        Telling that user "loses money at any electricity price" with a 0.000
        break-even would be a claim built on nothing.
        """
        out = self._call(
            config={"power_currency": "USD", "worker_c1_watts": "18"},
            workers=self.WORKERS,
            earned={},
            containers=[{"slug": "mysterium", "status": "running", "_worker_id": 1}],
        )
        charlie = {m["machine"]: m for m in out["machines"]}["charlie"]
        assert charlie["break_even_tariff"] is None
        assert "loses money at any electricity price" not in charlie["summary"]
        assert "guessing would be worse" in charlie["summary"]

    def test_an_unread_gross_with_a_tariff_gets_no_break_even_either(self):
        out = self._call(
            config={"power_currency": "USD", "power_price_per_kwh": "0.25", "worker_c1_watts": "18"},
            workers=self.WORKERS,
            earned={"mysterium": 0.0},
            measured=(),
            containers=[{"slug": "mysterium", "status": "running", "_worker_id": 1}],
        )
        charlie = {m["machine"]: m for m in out["machines"]}["charlie"]
        assert charlie["break_even_price_per_kwh"] is None
        assert charlie["break_even_tariff"] is None

    @pytest.mark.parametrize(
        "system_info",
        [
            {"docker_available": False},
            {"docker_available": True, "containers_listed": False},
            {"docker_available": True, "proxied": None},
            {"docker_available": True, "routes_read": False},
        ],
        ids=["docker-unavailable", "containers-unread", "proxies-unread", "routes-unread"],
    )
    def test_an_empty_list_from_an_unread_inventory_has_no_break_even(self, system_info):
        out = self._call(
            config={"power_currency": "USD", "worker_c1_watts": "18"},
            workers=[{"id": 1, "name": "charlie", "system_info": system_info}],
            earned={},
        )
        charlie = out["machines"][0]
        assert charlie["break_even_tariff"] is None
        assert "loses money at any electricity price" not in charlie["summary"]

    def test_an_empty_list_from_a_worker_that_sees_docker_is_a_measured_zero(self):
        """The mirror: a host that can read its socket and runs nothing earns 0."""
        out = self._call(
            config={"power_currency": "USD", "worker_c1_watts": "18"},
            workers=[{"id": 1, "name": "charlie", "system_info": {"docker_available": True}}],
            earned={},
        )
        charlie = out["machines"][0]
        assert charlie["break_even_tariff"] == {"price_per_kwh": 0.0, "currency": "USD"}
        assert "loses money at any electricity price" in charlie["summary"]

    def test_a_read_zero_still_breaks_even_at_zero(self):
        """The mirror: a gross that WAS read and is 0.0 keeps the strong claim."""
        out = self._call(
            config={"power_currency": "USD", "worker_c1_watts": "18"},
            workers=self.WORKERS,
            earned={"mysterium": 0.0},
            containers=[{"slug": "mysterium", "status": "running", "_worker_id": 1}],
        )
        charlie = {m["machine"]: m for m in out["machines"]}["charlie"]
        assert charlie["break_even_tariff"] == {"price_per_kwh": 0.0, "currency": "USD"}
        assert "loses money at any electricity price" in charlie["summary"]

    def test_the_tariff_is_echoed_as_typed_not_converted(self):
        """The page prints "you pay" next to a local price, so it must be local."""
        a, b = self._fx(lambda v, cur: v * 0.9, lambda v, cur: v / 0.9)
        with a, b:
            out = self._call(
                config={"power_currency": "EUR", "power_price_per_kwh": "0.25", "worker_c1_watts": "18"},
                workers=self.WORKERS,
                earned={"miner": 0.99},
                containers=[{"slug": "miner", "status": "running", "_worker_id": 1}],
            )
        assert out["tariff_price_per_kwh"] == 0.25
        charlie = {m["machine"]: m for m in out["machines"]}["charlie"]
        assert charlie["verdict"] == me.LOSING_MONEY
        assert charlie["break_even_tariff"]["currency"] == "EUR"


class TestWorkerWatts:
    """One reader of the typed machine watts, for every consumer."""

    def test_client_id_wins_over_the_row_id(self):
        from app import main

        cfg = {"worker_abc_watts": "18", "worker_7_watts": "65"}
        assert main._worker_watts(cfg, {"id": 7, "client_id": "abc"}) == 18.0

    def test_the_row_id_key_is_still_read(self):
        from app import main

        assert main._worker_watts({"worker_7_watts": "65"}, {"id": 7, "client_id": "abc"}) == 65.0

    @pytest.mark.parametrize("raw", [None, "", "lots", "nan", "inf", "-inf"])
    def test_absent_or_unreadable_is_none(self, raw):
        from app import main

        cfg = {} if raw is None else {"worker_abc_watts": raw}
        assert main._worker_watts(cfg, {"id": 7, "client_id": "abc"}) is None
