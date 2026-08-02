"""Producer state is not container health (CashPilot-b4e).

Container health is computed from restarts and crashes, so a service that has
produced nothing for a month still scores 100/100. "It runs but earns nothing"
is the most common complaint in this category and container health cannot see it.

The tests that matter most are the ones about NOT claiming to know: a service
with no collector must read unknown rather than idle, because saying "idle" when
we simply cannot see the earnings is the false confidence this exists to remove.
"""

from __future__ import annotations

import pytest

from app import producer_state as ps

FAILED_LOGIN = {"pattern": r"login failed", "means": "The service rejected the stored credentials.", "state": "failing"}
BANNED = {"pattern": r"\bbanned\b", "means": "The provider has banned this node.", "state": "failing"}
IDLE_HINT = {"pattern": r"no tasks available", "means": "Connected but nothing to do.", "state": "idle"}


class TestLogSignals:
    def test_a_declared_pattern_is_matched(self):
        hits = ps.match_log_signals("2026-08-02 ERROR login failed for user", [FAILED_LOGIN])
        assert len(hits) == 1
        assert hits[0]["means"].startswith("The service rejected")

    def test_matching_is_case_insensitive(self):
        assert ps.match_log_signals("LOGIN FAILED", [FAILED_LOGIN])

    def test_an_absent_pattern_does_not_match(self):
        assert ps.match_log_signals("everything is fine", [FAILED_LOGIN]) == []

    def test_an_invalid_regex_is_skipped_not_raised(self):
        """A typo in one service's YAML must not break health for all the others."""
        hits = ps.match_log_signals("login failed", [{"pattern": "(unclosed", "means": "x"}, FAILED_LOGIN])
        assert len(hits) == 1

    def test_a_signal_without_a_reason_still_says_something(self):
        hits = ps.match_log_signals("banned", [{"pattern": "banned"}])
        assert hits[0]["means"]

    def test_only_the_tail_of_a_huge_log_is_scanned(self):
        """A pattern must not cost unbounded work on a noisy container."""
        logs = ("x" * 500_000) + "login failed"
        assert ps.match_log_signals(logs, [FAILED_LOGIN])

    def test_no_logs_or_no_signals_is_simply_no_hits(self):
        assert ps.match_log_signals("", [FAILED_LOGIN]) == []
        assert ps.match_log_signals("login failed", None) == []


class TestItDoesNotClaimToKnow:
    def test_a_service_with_no_collector_is_unknown_not_idle(self):
        """We cannot see its earnings, so we must not call it idle."""
        out = ps.assess(slug="grass", has_collector=False, earned_recently=None)
        assert out["state"] == ps.UNKNOWN
        assert any("no collector" in r for r in out["reasons"])

    def test_too_little_history_is_unknown_not_idle(self):
        out = ps.assess(slug="new", has_collector=True, earned_recently=None)
        assert out["state"] == ps.UNKNOWN
        assert any("Not enough" in r for r in out["reasons"])

    def test_a_stopped_container_is_not_judged_at_all(self):
        out = ps.assess(slug="x", has_collector=True, earned_recently=False, container_running=False)
        assert out["state"] == ps.UNKNOWN
        assert "not running" in out["reasons"][0]


class TestStates:
    def test_moving_earnings_read_as_producing(self):
        assert ps.assess(slug="x", has_collector=True, earned_recently=True)["state"] == ps.PRODUCING

    def test_flat_earnings_read_as_idle(self):
        assert ps.assess(slug="x", has_collector=True, earned_recently=False)["state"] == ps.IDLE

    def test_a_failure_log_beats_moving_earnings(self):
        """A concrete diagnosis outranks an observation."""
        out = ps.assess(
            slug="x",
            has_collector=True,
            earned_recently=True,
            log_hits=ps.match_log_signals("login failed", [FAILED_LOGIN]),
        )
        assert out["state"] == ps.FAILING
        assert any("rejected the stored credentials" in r for r in out["reasons"])

    def test_a_log_signal_can_explain_a_collector_less_service(self):
        """The whole point of the YAML signals: 30+ services have no collector."""
        out = ps.assess(
            slug="teneo",
            has_collector=False,
            earned_recently=None,
            log_hits=ps.match_log_signals("account banned", [BANNED]),
        )
        assert out["state"] == ps.FAILING
        assert any("banned" in r for r in out["reasons"])

    def test_an_idle_log_signal_does_not_masquerade_as_failure(self):
        out = ps.assess(
            slug="x",
            has_collector=False,
            earned_recently=None,
            log_hits=ps.match_log_signals("no tasks available", [IDLE_HINT]),
        )
        assert out["state"] == ps.IDLE

    def test_the_worst_signal_wins(self):
        out = ps.assess(
            slug="x",
            has_collector=True,
            earned_recently=True,
            log_hits=ps.match_log_signals("no tasks available and banned", [IDLE_HINT, BANNED]),
        )
        assert out["state"] == ps.FAILING

    def test_every_verdict_carries_its_reasons(self):
        for kwargs in (
            {"has_collector": True, "earned_recently": True},
            {"has_collector": True, "earned_recently": False},
            {"has_collector": False, "earned_recently": None},
        ):
            assert ps.assess(slug="x", **kwargs)["reasons"], "a state with no reason is not actionable"


class TestCatalogIntegration:
    def test_signals_are_read_from_the_service_yaml(self):
        svc = {"slug": "x", "docker": {"health_signals": [FAILED_LOGIN]}}
        assert ps.signals_for(svc) == [FAILED_LOGIN]

    def test_a_service_declaring_none_yields_none(self):
        assert ps.signals_for({"slug": "x", "docker": {}}) == []
        assert ps.signals_for(None) == []

    def test_malformed_entries_are_ignored(self):
        svc = {"slug": "x", "docker": {"health_signals": ["not-a-mapping", FAILED_LOGIN]}}
        assert ps.signals_for(svc) == [FAILED_LOGIN]

    def test_every_declared_signal_in_the_real_catalog_compiles(self):
        """A broken regex shipped in the catalog would be silently useless."""
        import re

        from app import catalog

        for svc in catalog.get_services():
            for sig in ps.signals_for(svc):
                pattern = sig.get("pattern")
                assert pattern, f"{svc['slug']}: health_signals entry has no pattern"
                try:
                    re.compile(str(pattern))
                except re.error as exc:
                    pytest.fail(f"{svc['slug']}: invalid health_signals regex {pattern!r} ({exc})")
                assert str(sig.get("means") or "").strip(), (
                    f"{svc['slug']}: signal {pattern!r} has no 'means' — a match nobody can interpret"
                )


class TestProducerStateEndpoint:
    """The wiring: collector detection, log fetching, and never 500-ing."""

    def _call(self, slug, service, earned=None, containers=None, logs="", collector=True):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from app import main

        cmap = {slug: object()} if collector else {}

        async def run():
            with (
                patch.object(main, "_require_auth_api", lambda r: None),
                patch.object(main.catalog, "get_service", return_value=service),
                patch.dict("app.collectors.COLLECTOR_MAP", cmap, clear=True),
                patch.object(main.database, "get_earned_by_platform", AsyncMock(return_value=earned or {})),
                patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=containers or [])),
                patch.object(main, "_proxy_worker_logs", AsyncMock(return_value={"logs": logs})),
            ):
                return await main.api_producer_state(MagicMock(), slug)

        return asyncio.run(run())

    SVC = {"slug": "demo", "docker": {"health_signals": [FAILED_LOGIN]}}
    RUNNING = [{"service": "demo", "status": "running", "_worker_id": 1}]

    def test_an_unknown_service_is_a_404(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            self._call("nope", None)
        assert exc.value.status_code == 404

    def test_moving_earnings_report_producing(self):
        out = self._call("demo", self.SVC, earned={"demo": 1.5}, containers=self.RUNNING)
        assert out["state"] == ps.PRODUCING

    def test_flat_earnings_report_idle(self):
        out = self._call("demo", self.SVC, earned={"demo": 0.0}, containers=self.RUNNING)
        assert out["state"] == ps.IDLE

    def test_a_log_signal_is_matched_from_worker_logs(self):
        out = self._call("demo", self.SVC, earned={"demo": 1.0}, containers=self.RUNNING, logs="ERROR login failed")
        assert out["state"] == ps.FAILING
        assert out["log_hits"]

    def test_a_service_without_a_collector_is_unknown_not_idle(self):
        out = self._call("demo", self.SVC, containers=self.RUNNING, collector=False)
        assert out["state"] == ps.UNKNOWN

    def test_a_log_fetch_failure_never_500s(self):
        """The earnings signal alone is still worth reporting."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from app import main

        async def run():
            with (
                patch.object(main, "_require_auth_api", lambda r: None),
                patch.object(main.catalog, "get_service", return_value=self.SVC),
                patch.dict("app.collectors.COLLECTOR_MAP", {"demo": object()}, clear=True),
                patch.object(main.database, "get_earned_by_platform", AsyncMock(return_value={"demo": 2.0})),
                patch.object(main, "_get_all_worker_containers", AsyncMock(side_effect=RuntimeError("down"))),
            ):
                return await main.api_producer_state(MagicMock(), "demo")

        out = asyncio.run(run())
        assert out["state"] == ps.PRODUCING


class TestItReadsTheShapeWorkersActuallySend:
    """Regression: this matched on ``service`` while heartbeats emit ``slug``.

    Every service therefore reported "the container is not running" in
    production — the feature was inert — and the tests above passed because they
    hand-fed the key the code was looking for rather than the key it would get.
    """

    def _call(self, containers, logs=""):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from app import main

        svc = {"slug": "demo", "docker": {"health_signals": [FAILED_LOGIN]}}

        async def run():
            with (
                patch.object(main, "_require_auth_api", lambda r: None),
                patch.object(main.catalog, "get_service", return_value=svc),
                patch.dict("app.collectors.COLLECTOR_MAP", {"demo": object()}, clear=True),
                patch.object(main.database, "get_earned_by_platform", AsyncMock(return_value={"demo": 0.0})),
                patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=containers)),
                patch.object(main, "_proxy_worker_logs", AsyncMock(return_value={"logs": logs})),
            ):
                return await main.api_producer_state(MagicMock(), "demo")

        return asyncio.run(run())

    REAL = [{"slug": "demo", "status": "running", "_worker_id": 1, "name": "cashpilot-demo"}]

    def test_a_container_keyed_by_slug_is_found(self):
        assert self._call(self.REAL)["state"] == ps.IDLE

    def test_its_logs_are_actually_fetched_and_matched(self):
        """Not finding the container also meant never reading its logs."""
        out = self._call(self.REAL, logs="ERROR login failed")
        assert out["state"] == ps.FAILING

    def test_the_legacy_service_key_still_matches(self):
        legacy = [{"service": "demo", "status": "running", "_worker_id": 1}]
        assert self._call(legacy)["state"] == ps.IDLE

    def test_an_unrelated_container_is_not_matched(self):
        other = [{"slug": "something-else", "status": "running", "_worker_id": 1}]
        assert self._call(other)["state"] == ps.UNKNOWN
