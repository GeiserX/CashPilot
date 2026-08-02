"""Network counters as a producer-state signal (CashPilot-t6y).

Docker's counters are CUMULATIVE, so every test here is really about the ways a
raw total lies: a counter that reset, a counter that was never reported, and an
idle threshold that "obviously" ought to be zero and is not.

The measurements behind the threshold are in docs/research/idle-network-traffic.md
— taken from a live fleet, because the bead was explicit that assuming zero is
how this signal goes wrong.
"""

from __future__ import annotations

import pytest

from app import net_activity as na
from app import producer_state as ps


class TestACounterThatWentBackwardsIsARestart:
    def test_a_reset_yields_unknown_not_a_negative_rate(self):
        """The container restarted; the old baseline means nothing now."""
        assert na.rate(1_000_000, 500, 60) is None

    def test_a_reset_is_not_silently_clamped_to_zero(self):
        """Clamping would report a busy service as silent — the worst outcome."""
        assert na.classify(na.rate(1_000_000, 500, 60)) == na.UNKNOWN

    def test_an_unchanged_counter_is_a_real_zero_rate(self):
        assert na.rate(1000, 1000, 60) == 0.0
        assert na.classify(na.rate(1000, 1000, 60)) == na.SILENT


class TestMissingCountersAreNotZero:
    def test_a_container_reporting_no_interfaces_is_unknown(self):
        """Host-network containers have NO networks key at all in Docker stats.

        Verified on a live fleet, where the busiest service by far — a dVPN exit
        moving ~15 MB/s — is host-networked and reports nothing.
        """
        assert na.totals({"slug": "mysterium"}) is None
        assert na.totals({"net_rx_bytes": None, "net_tx_bytes": None}) is None

    def test_a_partially_reported_container_still_counts(self):
        assert na.totals({"net_rx_bytes": 10, "net_tx_bytes": None}) == 10

    def test_malformed_counters_are_unknown_rather_than_guessed(self):
        assert na.totals({"net_rx_bytes": "lots", "net_tx_bytes": 1}) is None
        assert na.totals({"net_rx_bytes": -5, "net_tx_bytes": -5}) is None
        assert na.totals(None) is None
        assert na.totals("not-a-container") is None

    def test_both_counters_are_summed(self):
        assert na.totals({"net_rx_bytes": 100, "net_tx_bytes": 23}) == 123


class TestIntervalsWeCannotTrust:
    def test_no_baseline_means_no_rate(self):
        assert na.rate(None, 500, 60) is None
        assert na.rate(500, None, 60) is None

    def test_too_short_an_interval_is_dominated_by_jitter(self):
        assert na.rate(0, 1000, 0.5) is None

    def test_too_old_a_baseline_may_hide_a_restart_inside_it(self):
        assert na.rate(0, 1000, na.MAX_BASELINE_AGE_SECONDS + 1) is None

    def test_a_sane_interval_produces_a_rate(self):
        assert na.rate(0, 6000, 60) == 100.0


class TestTheThresholdIsMeasuredNotAssumed:
    def test_it_is_not_zero(self):
        """Idle-but-connected containers are not silent.

        On the measured fleet the quietest still-connected service sat at
        ~5.5 B/s of keepalive chatter, so a zero threshold would call almost
        every healthy idle container "moving".
        """
        assert na.SILENT_BYTES_PER_SEC > 0

    def test_the_quietest_measured_live_container_reads_as_moving(self):
        """5.5 B/s was a real reading from a connected, working service."""
        assert na.classify(5.5) == na.MOVING

    def test_a_genuinely_dead_container_reads_as_silent(self):
        """Two services measured at exactly 0.0 B/s over two minutes."""
        assert na.classify(0.0) == na.SILENT

    @pytest.mark.parametrize("rate_bps", [545.5, 6708.6, 815589.1, 15275715.3])
    def test_every_busy_measured_container_reads_as_moving(self, rate_bps):
        assert na.classify(rate_bps) == na.MOVING

    def test_a_human_description_is_always_available(self):
        for state in (na.MOVING, na.SILENT, na.UNKNOWN):
            assert na.describe(state, 1234.0)


class TestItNeverCondemns:
    """Silence is not proof of breakage when demand drives the traffic."""

    def test_silence_supports_idle_but_never_failing(self):
        out = ps.assess(slug="x", has_collector=False, earned_recently=None, traffic=na.SILENT)
        assert out["state"] == ps.IDLE

    def test_silence_does_not_override_observed_earnings(self):
        """Money moved. A quiet minute does not undo that."""
        out = ps.assess(slug="x", has_collector=True, earned_recently=True, traffic=na.SILENT)
        assert out["state"] == ps.PRODUCING

    def test_traffic_never_outranks_a_failure_log(self):
        out = ps.assess(
            slug="x",
            has_collector=True,
            earned_recently=None,
            traffic=na.MOVING,
            log_hits=[{"pattern": "banned", "means": "The provider has banned this node.", "state": "failing"}],
        )
        assert out["state"] == ps.FAILING

    def test_moving_data_is_not_reported_as_earning(self):
        """Bytes on the wire are not money."""
        out = ps.assess(slug="x", has_collector=False, earned_recently=None, traffic=na.MOVING)
        assert out["state"] == ps.UNKNOWN
        assert any("does not prove it is earning" in r for r in out["reasons"])

    def test_unknown_traffic_changes_nothing(self):
        with_unknown = ps.assess(slug="x", has_collector=True, earned_recently=False, traffic=na.UNKNOWN)
        without = ps.assess(slug="x", has_collector=True, earned_recently=False)
        assert with_unknown["state"] == without["state"]

    def test_the_traffic_state_is_reported_back(self):
        assert ps.assess(slug="x", has_collector=True, earned_recently=True, traffic=na.MOVING)["traffic"] == na.MOVING
        assert ps.assess(slug="x", has_collector=True, earned_recently=True)["traffic"] == na.UNKNOWN


class TestTheBaselineCache:
    def _state(self, slug, containers):
        from app import main

        return main._traffic_state(slug, containers)

    def setup_method(self):
        from app import main

        main._net_baselines.clear()

    def test_the_first_sighting_cannot_produce_a_rate(self):
        assert self._state("x", [{"_worker_id": 1, "net_rx_bytes": 100, "net_tx_bytes": 100}]) == na.UNKNOWN

    def test_a_service_with_no_containers_says_nothing_at_all(self):
        assert self._state("x", []) is None

    def test_containers_without_counters_say_nothing_at_all(self):
        assert self._state("x", [{"_worker_id": 1, "slug": "x"}]) is None

    def test_a_second_reading_produces_a_verdict(self, monkeypatch):
        import time

        from app import main

        clock = [1000.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])
        assert self._state("x", [{"_worker_id": 1, "net_rx_bytes": 0, "net_tx_bytes": 0}]) == na.UNKNOWN
        clock[0] += 60
        out = main._traffic_state("x", [{"_worker_id": 1, "net_rx_bytes": 60_000, "net_tx_bytes": 0}])
        assert out == na.MOVING

    def test_a_restart_between_readings_reports_unknown(self, monkeypatch):
        import time

        from app import main

        clock = [1000.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])
        self._state("x", [{"_worker_id": 1, "net_rx_bytes": 10_000_000, "net_tx_bytes": 0}])
        clock[0] += 60
        assert main._traffic_state("x", [{"_worker_id": 1, "net_rx_bytes": 42, "net_tx_bytes": 0}]) == na.UNKNOWN

    def test_instances_are_tracked_per_worker(self, monkeypatch):
        import time

        from app import main

        clock = [1000.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])
        both = [
            {"_worker_id": 1, "net_rx_bytes": 0, "net_tx_bytes": 0},
            {"_worker_id": 2, "net_rx_bytes": 0, "net_tx_bytes": 0},
        ]
        self._state("x", both)
        clock[0] += 60
        # Worker 1 idle, worker 2 busy: the service is not silent.
        out = main._traffic_state(
            "x",
            [
                {"_worker_id": 1, "net_rx_bytes": 0, "net_tx_bytes": 0},
                {"_worker_id": 2, "net_rx_bytes": 600_000, "net_tx_bytes": 0},
            ],
        )
        assert out == na.MOVING


class TestTheWorkerReportsTheCounters:
    def test_host_networked_containers_report_none(self):
        from app import orchestrator

        assert orchestrator._network_totals({"memory_stats": {}}) == (None, None)
        assert orchestrator._network_totals({"networks": {}}) == (None, None)
        assert orchestrator._network_totals({"networks": "eth0"}) == (None, None)

    def test_every_interface_is_summed(self):
        from app import orchestrator

        stats = {"networks": {"eth0": {"rx_bytes": 10, "tx_bytes": 20}, "eth1": {"rx_bytes": 1, "tx_bytes": 2}}}
        assert orchestrator._network_totals(stats) == (11, 22)

    def test_a_malformed_interface_entry_is_skipped(self):
        from app import orchestrator

        stats = {"networks": {"eth0": "bad", "eth1": {"rx_bytes": 5, "tx_bytes": 5}}}
        assert orchestrator._network_totals(stats) == (5, 5)


class TestProducerStateEndpointCarriesTraffic:
    def _call(self, containers, earned=None):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from app import main

        main._net_baselines.clear()
        svc = {"slug": "demo", "docker": {}}

        async def run():
            with (
                patch.object(main, "_require_auth_api", lambda r: None),
                patch.object(main.catalog, "get_service", return_value=svc),
                patch.dict("app.collectors.COLLECTOR_MAP", {}, clear=True),
                patch.object(main.database, "get_earned_by_platform", AsyncMock(return_value=earned or {})),
                patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=containers)),
            ):
                return await main.api_producer_state(MagicMock(), "demo")

        return asyncio.run(run())

    RUNNING = [{"slug": "demo", "status": "running", "_worker_id": 1, "net_rx_bytes": 5, "net_tx_bytes": 5}]

    def test_the_first_call_reports_unknown_traffic(self):
        assert self._call(self.RUNNING)["traffic"] == na.UNKNOWN

    def test_a_host_networked_container_does_not_claim_silence(self):
        out = self._call([{"slug": "demo", "status": "running", "_worker_id": 1}])
        assert out["traffic"] == na.UNKNOWN
        assert not any("no data" in r for r in out["reasons"])
