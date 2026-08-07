"""Batch 4: figures that were wrong rather than merely missing.

Three ways a total misled. One dropped holdings it could have priced. One
reported a month-over-month percentage nothing had computed. One subtracted the
cost of SOME machines from the gross of ALL of them.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def without_comments(text: str) -> str:
    """Source with comments stripped, for guards that scan raw text.

    This is the FIFTH time in this effort that a text-matching assertion has
    matched the comment explaining the very thing it checks. Here the comment
    mentions `pct.toFixed` while warning that it would throw — so an
    order-of-operations assertion found the prose before the code and failed on
    correct source.

    Rewording the comment to appease the test makes the code worse to read in
    order to keep a weak check green. Strip the comments instead.
    """
    import re

    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in text.splitlines())


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"


class TestTheTotalUsesTheRateTheReadingWasRecordedAt:
    """CashPilot-47t: a crypto with no LIVE rate vanished from the headline.

    ``exchange_rates.to_usd`` consults only the live caches, so a stale rate
    lookup silently removed the entire holding from the dashboard Total — while
    the Today and Month cards, which already fall back to the stored
    ``fx_rate_usd``, kept counting it. Two cards, one dataset, different answers.
    """

    async def _summary(self, rows, live_rate=None):
        from app import database, exchange_rates, main

        with (
            patch.object(main, "_require_auth_api", lambda r: None),
            patch.object(main, "_require_reader", lambda r: None),
            patch.object(
                database,
                "get_earnings_dashboard_summary",
                AsyncMock(
                    return_value={"total": 0.0, "today": 0.0, "month": 0.0, "today_change": 0.0, "month_change": None}
                ),
            ),
            patch.object(database, "get_earnings_summary", AsyncMock(return_value=rows)),
            patch.object(database, "get_config", AsyncMock(return_value={})),
            patch.object(database, "get_confirmed_payout_totals", AsyncMock(return_value={})),
            patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=[])),
            patch.object(exchange_rates, "to_usd", lambda amt, cur: live_rate),
        ):
            return await main.api_earnings_summary(MagicMock())

    @pytest.mark.asyncio
    async def test_a_stale_rate_no_longer_drops_the_holding(self):
        rows = [{"platform": "mysterium", "balance": 110.0, "currency": "MYST", "date": "d", "fx_rate_usd": 0.12}]
        out = await self._summary(rows, live_rate=None)
        assert out["total"] == pytest.approx(13.2), "110 MYST at the stored 0.12 should be 13.20"

    @pytest.mark.asyncio
    async def test_a_live_rate_still_wins(self):
        """The stored rate is a floor, not a replacement — it is older."""
        rows = [{"platform": "mysterium", "balance": 100.0, "currency": "MYST", "date": "d", "fx_rate_usd": 0.10}]
        out = await self._summary(rows, live_rate=50.0)
        assert out["total"] == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_a_row_with_no_usable_rate_is_reported_not_hidden(self):
        """A total that silently omits holdings looks exactly like a correct one."""
        rows = [{"platform": "grass", "balance": 1200.0, "currency": "GRASS", "date": "d", "fx_rate_usd": None}]
        out = await self._summary(rows, live_rate=None)
        assert out["total"] == 0.0
        assert out["unpriced_platforms"] == ["grass"]

    @pytest.mark.asyncio
    async def test_nothing_unpriced_reports_an_empty_list(self):
        rows = [{"platform": "mysterium", "balance": 10.0, "currency": "MYST", "date": "d", "fx_rate_usd": 0.5}]
        out = await self._summary(rows, live_rate=None)
        assert out["unpriced_platforms"] == []

    def test_a_rejected_rate_is_not_used(self):
        """0, negative, inf and nan are rejected — by the SHARED validator."""
        from app.main import _to_usd_with_stored

        assert _to_usd_with_stored(100.0, "MYST", None) is None

    def test_the_query_actually_selects_the_stored_rate(self):
        """The fallback is unreachable if the column never leaves SQLite."""
        source = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
        assert "SELECT platform, balance, currency, date, fx_rate_usd" in source

    def test_the_helper_is_module_level_not_a_closure(self):
        """Defined in the loop it captured `currency` late (ruff B023).

        Every conversion would then have used the LAST currency seen — which is
        worse than the bug being fixed, and silent.
        """
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert "\ndef _to_usd_with_stored(" in source


class TestAnUncomputedPercentageIsNotZero:
    """CashPilot-7oj: month_change was a literal 0.0 nothing ever computed.

    The dashboard rendered it as "+0.0%" in the positive style, permanently —
    a month-over-month comparison presented with the same confidence as a
    measured one.
    """

    def test_the_backend_reports_it_as_unmeasured(self):
        source = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
        assert '"month_change": 0.0,' not in source

    def test_the_renderer_shows_nothing_rather_than_zero(self):
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        start = source.index("function setChangeIndicator")
        block = source[start : source.index("function debounce", start)]
        assert "pct === null" in block

    def test_the_renderer_does_not_throw_on_null(self):
        """`pct.toFixed` on null is a TypeError that would kill the handler."""
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        start = source.index("function setChangeIndicator")
        block = source[start : source.index("function debounce", start)]
        assert block.index("pct === null") < block.index("pct.toFixed")

    def test_a_real_percentage_still_renders(self):
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        start = source.index("function setChangeIndicator")
        block = source[start : source.index("function debounce", start)]
        assert "toFixed(1)" in block


class TestFleetNetComparesLikeWithLike:
    """CashPilot-he1: net subtracted SOME costs from ALL gross.

    Gross summed every machine; cost summed only machines whose cost was known.
    The difference flatters the fleet by exactly the gross of every machine that
    could not be priced — so the more machines you cannot measure, the healthier
    it looks. The function's own docstring promises it "never quietly
    understates what the fleet costs".
    """

    def _fleet(self, machines):
        from app import machine_economics

        return machine_economics.fleet_summary(machines)

    def test_an_unpriced_machine_does_not_inflate_net(self):
        out = self._fleet(
            [
                {"monthly_gross": 100.0, "monthly_cost": 30.0},
                {"monthly_gross": 500.0, "monthly_cost": None},
            ]
        )
        assert out["monthly_net"] == pytest.approx(70.0), (
            "net counted the unpriced machine's gross with none of its cost"
        )

    def test_gross_still_reports_the_whole_fleet(self):
        """Gross is not wrong — only net was mixing denominators."""
        out = self._fleet(
            [
                {"monthly_gross": 100.0, "monthly_cost": 30.0},
                {"monthly_gross": 500.0, "monthly_cost": None},
            ]
        )
        assert out["monthly_gross"] == pytest.approx(600.0)

    def test_the_caller_is_told_how_many_are_priced(self):
        out = self._fleet(
            [
                {"monthly_gross": 100.0, "monthly_cost": 30.0},
                {"monthly_gross": 500.0, "monthly_cost": None},
            ]
        )
        assert out["cost_known_for"] == 1

    def test_all_known_is_unchanged(self):
        """The control: the fix must not alter the fully-measured case."""
        out = self._fleet(
            [
                {"monthly_gross": 100.0, "monthly_cost": 30.0},
                {"monthly_gross": 200.0, "monthly_cost": 50.0},
            ]
        )
        assert out["monthly_net"] == pytest.approx(220.0)

    def test_none_known_reports_net_as_unknown(self):
        out = self._fleet([{"monthly_gross": 100.0, "monthly_cost": None}])
        assert out["monthly_net"] is None
        assert out["monthly_cost"] is None
