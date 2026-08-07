"""CashPilot-93t: the dashboard asserted $0.00 before anything had ever looked.

A brand-new user's first view of CashPilot was "Total Balance $0.00 / Today
$0.00 / This Month $0.00" — stated as measurements, in the same typeface those
cards will later carry real money in. The three cards rendered identically when
collection had silently STOPPED: an expired cookie, deleted credentials, a
wedged scheduler. Nothing in the payload let the page tell "nothing measured
yet" from "measured, and it was zero".

Verified against a live empty install: /api/earnings/summary returned
{"total":0,"today":0.0,"month":0,...} with no field separating the two, while
/api/earnings and /api/earnings/history?period=week both returned [].

This is the same rule the rest of the codebase already follows for balances,
costs and payout minimums — absent is not zero — applied to the first screen a
new user ever sees.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"
DASHBOARD = ROOT / "app" / "templates" / "dashboard.html"


def without_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in text.splitlines())


async def _summary(earnings_rows):
    from app import main

    with (
        patch.object(main, "_require_auth_api", lambda r: None),
        patch.object(main, "_require_reader", lambda r: None),
        patch.object(
            main.database,
            "get_earnings_dashboard_summary",
            AsyncMock(return_value={"total": 0, "today": 0.0, "month": 0}),
        ),
        patch.object(main.database, "get_config", AsyncMock(return_value={})),
        patch.object(main.database, "get_earnings_summary", AsyncMock(return_value=earnings_rows)),
        patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=[])),
    ):
        return await main.api_earnings_summary(MagicMock())


class TestThePayloadSaysWhetherAnythingHasBeenRead:
    @pytest.mark.asyncio
    async def test_a_fresh_install_reports_no_readings(self):
        assert (await _summary([]))["has_readings"] is False

    @pytest.mark.asyncio
    async def test_a_collected_install_reports_readings(self):
        """The control: this must not claim "nothing yet" once data exists."""
        rows = [{"platform": "honeygain", "balance": 3.5, "currency": "USD"}]
        assert (await _summary(rows))["has_readings"] is True

    @pytest.mark.asyncio
    async def test_a_genuine_measured_zero_still_counts_as_read(self):
        """The distinction that makes this worth having.

        A service read at exactly 0.00 HAS been measured. Folding it back into
        "nothing yet" would replace one wrong answer with another.
        """
        rows = [{"platform": "honeygain", "balance": 0.0, "currency": "USD"}]
        out = await _summary(rows)
        assert out["has_readings"] is True
        assert out["total"] == 0

    @pytest.mark.asyncio
    async def test_the_existing_fields_are_untouched(self):
        """Nothing else about the payload changes."""
        out = await _summary([])
        for key in ("total", "today", "month", "active_services", "total_bonus", "total_adjusted"):
            assert key in out, f"{key} disappeared from the summary payload"


class TestTheCardsDoNotStateMoneyTheyDoNotHave:
    def test_the_static_page_no_longer_ships_hardcoded_zeroes(self):
        """These render before any request is made, so they are an assertion."""
        html = DASHBOARD.read_text(encoding="utf-8")
        for element in ("total-earnings", "today-earnings", "month-earnings"):
            assert f'id="{element}">$0.00<' not in html, f"{element} still ships a hardcoded balance"

    def test_the_static_page_uses_a_neutral_placeholder(self):
        html = DASHBOARD.read_text(encoding="utf-8")
        assert html.count('">—<') >= 3

    def test_the_renderer_checks_has_readings(self):
        """Pinned to the MONEY path, not just the string.

        The first version asserted `data.has_readings === false` appeared
        anywhere in the file — which the note-toggling line satisfies on its own.
        Removing the conditional from the figures left this passing, so it was
        testing nothing about the three cards it names.
        """
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        assert "const money = value => (data.has_readings === false" in source, (
            "the stat cards render currency unconditionally again"
        )

    @pytest.mark.parametrize("element", ["total-earnings", "today-earnings", "month-earnings"])
    def test_each_card_goes_through_the_conditional_formatter(self, element):
        """All three, not just whichever one was checked."""
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        assert f"setTextContent('{element}', money(" in source, f"{element} bypasses the has_readings check"

    def test_the_topbar_total_gets_the_same_treatment(self):
        """It sits beside the cards; one of them saying $0.00 undoes the other."""
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        assert "setTextContent('topbar-total', money(displayTotal));" in source

    def test_there_is_a_note_saying_which_case_it_is(self):
        """An em dash alone is ambiguous — it needs a word."""
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        html = DASHBOARD.read_text(encoding="utf-8")
        assert "no-readings-note" in source
        assert "Nothing collected yet" in html

    def test_real_figures_still_render_as_currency(self):
        """The control: this must not em-dash a working dashboard."""
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        assert "formatCurrency(value)" in source, "the money path was removed rather than made conditional"
