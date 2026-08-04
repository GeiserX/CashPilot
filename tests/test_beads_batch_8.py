"""Batch 8: a machine we cannot see is not a machine earning nothing.

Two findings, one mistake. Both endpoints are built only from ONLINE workers,
and both then presented the resulting absence as a measured fact — one as a
financial recommendation, the other as "you have no services".
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"


def without_comments(text: str) -> str:
    """JS source with comments stripped, for guards that scan raw text."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in text.splitlines())


class TestAnUnreadableMachineGetsNoVerdict:
    """CashPilot-daq: an offline worker was told to switch itself off.

    per_worker_gross is built only from online workers, and the endpoint
    defaulted a missing entry to 0.0. So a host that had merely stopped
    heartbeating produced: "geiserback earns about 0.00 a month and costs about
    9.49 in electricity — roughly 9.49 out of pocket. Since this machine runs
    only these services, turning it off would save that."

    A confident financial recommendation about a machine CashPilot cannot see —
    and its earnings were silently reattributed to the workers still reporting.
    """

    def _assess(self, gross):
        from app import machine_economics

        return machine_economics.assess_machine(
            name="geiserback", monthly_gross=gross, watts=65.0, price_per_kwh=0.20, dedicated=True
        )

    def test_unknown_earnings_produce_an_unknown_verdict(self):
        from app import machine_economics

        assert self._assess(None)["verdict"] == machine_economics.UNKNOWN

    def test_no_cost_or_net_is_asserted_for_it(self):
        out = self._assess(None)
        assert out["monthly_cost"] is None
        assert out["monthly_net"] is None
        assert out["monthly_gross"] is None, "0.0 here is the fabrication being removed"

    def test_the_summary_says_it_is_not_reporting(self):
        assert "not reporting" in self._assess(None)["summary"]

    def test_it_does_not_recommend_switching_anything_off(self):
        summary = self._assess(None)["summary"].lower()
        assert "turning it off would save" not in summary

    def test_a_genuine_zero_is_still_judged(self):
        """The control. Without it this fix could pass by never judging anything."""
        from app import machine_economics

        out = self._assess(0.0)
        assert out["verdict"] == machine_economics.LOSING_MONEY
        assert out["monthly_cost"] is not None

    def test_a_profitable_machine_is_unaffected(self):
        from app import machine_economics

        assert self._assess(50.0)["verdict"] == machine_economics.PROFITABLE

    def test_the_endpoint_passes_none_for_an_offline_worker(self):
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert 'monthly_gross=per_worker_gross.get(worker.get("id"), 0.0),' not in source
        assert 'if str(worker.get("status") or "") == "online"' in source


class TestTheEmptyDashboardSaysWhichEmptyItIs:
    """CashPilot-1qy: an unreachable worker read as "you have no services".

    /api/services/deployed is built only from online workers, so three minutes
    after a host stopped heartbeating — a reboot, a network blip, a worker
    container restart — the table emptied and the dashboard stated as fact that
    the user had nothing and should start over. The containers were still
    running and still earning.
    """

    def _empty_state(self) -> str:
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        start = source.index("if (!services || services.length === 0)")
        return source[start : start + 2000]

    def test_it_checks_for_unreachable_workers_first(self):
        assert "/api/workers" in self._empty_state()

    def test_it_does_not_claim_nothing_is_deployed_when_a_worker_is_offline(self):
        block = self._empty_state()
        assert "unreachable === 0" in block, "the two cases are not distinguished"

    def test_it_says_the_containers_are_still_running(self):
        """The user's real question is whether their earnings stopped."""
        block = self._empty_state()
        assert "keep running and earning" in block

    def test_a_genuinely_empty_install_still_gets_the_wizard(self):
        """The control: the onboarding path must survive this change."""
        block = self._empty_state()
        assert "No services deployed yet" in block
        assert "/setup" in block

    def test_a_failed_worker_lookup_does_not_assert_either_case(self):
        """If we cannot tell which it is, saying nothing beats guessing."""
        block = self._empty_state()
        assert "unreachable = -1" in block

    def test_the_worker_count_is_escaped(self):
        """It reaches the DOM through innerHTML."""
        block = self._empty_state()
        assert "escapeHtml(String(unreachable))" in block


class TestTheFleetTotalSaysWhatItCouldNotSee:
    """Found in my own fresh review of this PR, not by an audit agent.

    Making an unreachable machine report ``monthly_gross: None`` fixed the
    per-machine verdict but pushed the same mistake up one level: the fleet
    total summed that None as 0.0, so the headline gross silently shrank by
    whatever the unreachable machine earns, with nothing saying so.

    The function already guards exactly this for cost — "so the total never
    quietly understates what the fleet costs" — and the guard simply had not
    been extended to gross, because until this PR gross was never unknown.
    """

    def _summary(self, machines):
        from app import machine_economics

        return machine_economics.fleet_summary(machines)

    def test_an_unreadable_machine_is_counted(self):
        out = self._summary(
            [
                {"machine": "watchtower", "monthly_gross": 40.0, "monthly_cost": 9.0},
                {"machine": "geiserback", "monthly_gross": None, "monthly_cost": None},
            ]
        )
        assert out["gross_unknown_for"] == 1

    def test_the_summary_says_the_total_is_incomplete(self):
        out = self._summary(
            [
                {"machine": "watchtower", "monthly_gross": 40.0, "monthly_cost": 9.0},
                {"machine": "geiserback", "monthly_gross": None, "monthly_cost": None},
            ]
        )
        assert "not reporting" in out["summary"]
        assert "not in this total" in out["summary"]

    def test_a_fully_readable_fleet_says_nothing_extra(self):
        """The control: this must not nag when everything is known."""
        out = self._summary(
            [
                {"machine": "watchtower", "monthly_gross": 40.0, "monthly_cost": 9.0},
                {"machine": "nuc", "monthly_gross": 10.0, "monthly_cost": 3.0},
            ]
        )
        assert out["gross_unknown_for"] == 0
        assert "not reporting" not in out["summary"]

    def test_the_template_can_render_a_null_gross(self):
        """monthly_gross became nullable; something has to draw it.

        fleet.html's money() already returns an em dash for null — asserted so a
        later simplification of that helper cannot turn a null into "0.00" or a
        NaN.
        """
        text = (ROOT / "app" / "templates" / "fleet.html").read_text(encoding="utf-8")
        assert "v == null ? '—'" in text
