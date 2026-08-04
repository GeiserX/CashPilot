"""Regression tests for bead batch 2: the duplicate groups.

Three audit areas filed the same two defects between them, so eight beads
collapse into two fixes. Both are the same mistake — code with no value
supplying a confident one.

Independently re-verified against this branch before being touched.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"


class TestANeverReadServiceIsNotAServiceEarningZero:
    """CashPilot-vp6 / -ikh / -7qk — one defect, filed from three audit areas.

    `balance_map.get(slug, 0.0)` turned "no reading" into a confident $0.00.
    Neither existing suppressor fires in that state: collector_disconnected
    needs an alert (none was raised, because no collector ran) and
    collector_needs_setup only checks whether config keys are filled. The
    flatline detector cannot catch it either — it skips rows whose max balance
    is 0. So the user saw a service marked Running with a balance of $0.00 and
    a bell reporting "All collectors healthy".
    """

    def test_the_api_reports_an_unknown_balance_as_null(self):
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert "balance_map.get(slug, 0.0)" not in source
        assert '"balance_known": slug in balance_map,' in source

    def test_both_entry_paths_were_fixed(self):
        """Container-backed and external services build separate dicts."""
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert source.count('"balance_known": slug in balance_map,') == 2

    def test_the_renderer_does_not_coerce_null_back_to_zero(self):
        """`|| 0` would silently undo the whole fix."""
        source = APP_JS.read_text(encoding="utf-8")
        assert "const balance = (bk && bk.balance) || svc.balance || 0;" not in source
        assert "balanceKnown" in source

    def test_an_unknown_balance_renders_as_a_dash(self):
        source = APP_JS.read_text(encoding="utf-8")
        assert "if (!balanceKnown)" in source
        assert "&mdash;" in source


class TestThePayoutCardDoesNotInventProgress:
    """CashPilot-3oa / -jkd / -s2b — one card, three filed symptoms.

    It asserted a definite 0.00 lifetime and a 0%-of-minimum bar for a service
    CashPilot had never read. It already got "Balance now" right via
    balance_known, which made the fabricated figures beside it look
    corroborated.
    """

    def test_the_card_hides_when_there_is_nothing_to_show(self):
        source = APP_JS.read_text(encoding="utf-8")
        assert "if (!data.balance_known && !paid)" in source

    def test_confirmed_payouts_alone_still_show_the_card(self):
        """A confirmed payout is a real lower bound even with no live balance."""
        source = APP_JS.read_text(encoding="utf-8")
        block = source[source.index("if (!data.balance_known && !paid)") :][:200]
        assert "&& !paid" in block

    def test_the_lifetime_figure_is_gated_too(self):
        source = APP_JS.read_text(encoding="utf-8")
        assert "${escapeHtml(money(data.lifetime_earned || 0))}</div>" not in source

    def test_the_endpoint_does_not_fold_unknown_into_zero(self):
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert "if (known or confirmed) else None" in source

    def test_the_projection_is_kept(self):
        """NOT_ENOUGH_DATA says WHY there is no estimate; null does not.

        Nulling it broke an existing test that was right to object.
        """
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        # Matched on the CALL, not its full argument list. Pinning the arguments
        # made this fail when project() gained the balance's currency — a change
        # that has nothing to do with what this test is protecting, which is
        # that the field is populated rather than nulled.
        assert '"projection": payouts.project(current, service, history' in source
        assert '"projection": None' not in source

    @pytest.mark.asyncio
    async def test_a_never_read_service_reports_null_lifetime(self):
        from app import main

        with (
            patch.object(main, "_require_auth_api", lambda r: None),
            patch.object(main.database, "get_latest_balance", AsyncMock(return_value=None)),
            patch.object(main.database, "get_balance_history", AsyncMock(return_value=[])),
            patch.object(main.database, "get_payouts", AsyncMock(return_value=[])),
            patch.object(main.catalog, "get_service", MagicMock(return_value={"slug": "honeygain"})),
        ):
            out = await main.api_payout_progress(MagicMock(), "honeygain")
        assert out["balance_known"] is False
        assert out["lifetime_earned"] is None, "a service never read reported a definite lifetime total"
        assert out["current_balance"] is None
