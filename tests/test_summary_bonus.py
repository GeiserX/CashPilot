"""Tests for signup bonus aggregation in /api/earnings/summary.

Verifies that total_adjusted equals the sum of per-service clamped adjusted
balances, with proper USD conversion for non-USD services.
"""

import asyncio
import os

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

try:
    from app.main import api_earnings_summary  # noqa: E402
except ImportError:
    pytest.skip("Requires full app dependencies (fastapi, httpx, etc.) — runs in CI", allow_module_level=True)

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402


def _dashboard_summary(total=0.0):
    return {
        "total": total,
        "today": 0.0,
        "month": 0.0,
        "today_change": 0.0,
        "month_change": 0.0,
    }


def _earnings_entry(platform, balance, currency="USD"):
    return {"platform": platform, "balance": balance, "currency": currency}


def _call_summary(dashboard_total, earnings, config=None, to_usd=None):
    """Call the real handler with mocked dependencies."""
    request = MagicMock()

    def mock_to_usd(amount, currency):
        if to_usd and currency in to_usd:
            return amount * to_usd[currency]
        return None

    with (
        patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "test", "r": "owner"}),
        patch(
            "app.main.database.get_earnings_dashboard_summary",
            new_callable=AsyncMock,
            return_value=_dashboard_summary(dashboard_total),
        ),
        patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=earnings),
        patch("app.main.database.get_config", new_callable=AsyncMock, return_value=config or {}),
        patch("app.main.exchange_rates.to_usd", side_effect=mock_to_usd),
        patch("app.main._get_all_worker_containers", new_callable=AsyncMock, return_value=[]),
    ):
        return asyncio.run(api_earnings_summary(request))


class TestSummaryBonusAggregation:
    """Signup bonus aggregation in the summary endpoint."""

    def test_no_bonuses_total_unchanged(self):
        earnings = [_earnings_entry("svc-a", 10.0), _earnings_entry("svc-b", 5.0)]
        result = _call_summary(15.0, earnings)
        assert result["total"] == 15.0
        assert result["total_adjusted"] == 15.0
        assert result["total_bonus"] == 0.0

    def test_bonus_reduces_adjusted_total(self):
        earnings = [_earnings_entry("svc-a", 20.0), _earnings_entry("svc-b", 8.0)]
        config = {"svc-a_signup_bonus": "5.0", "svc-b_signup_bonus": "3.0"}
        result = _call_summary(28.0, earnings, config=config)
        assert result["total"] == 28.0
        assert result["total_adjusted"] == 20.0  # (20-5) + (8-3)
        assert result["total_bonus"] == 8.0

    def test_adjusted_clamps_at_zero_per_service(self):
        """Bonus exceeding balance should floor at 0, not go negative."""
        earnings = [_earnings_entry("svc-a", 3.0), _earnings_entry("svc-b", 10.0)]
        config = {"svc-a_signup_bonus": "10.0", "svc-b_signup_bonus": "2.0"}
        result = _call_summary(13.0, earnings, config=config)
        # svc-a: max(0, 3-10) = 0, svc-b: max(0, 10-2) = 8
        assert result["total_adjusted"] == 8.0
        assert result["total_bonus"] == 12.0

    def test_adjusted_never_negative(self):
        """Even if all bonuses exceed balances, total_adjusted stays >= 0."""
        earnings = [_earnings_entry("svc-a", 2.0)]
        config = {"svc-a_signup_bonus": "100.0"}
        result = _call_summary(2.0, earnings, config=config)
        assert result["total_adjusted"] == 0.0

    def test_non_usd_bonus_converted(self):
        """Bonus on a MYST service should be converted to USD."""
        earnings = [
            _earnings_entry("honeygain", 10.0, "USD"),
            _earnings_entry("mysterium", 20.0, "MYST"),
        ]
        config = {"mysterium_signup_bonus": "4.0"}
        # MYST -> USD at 0.10 per token
        result = _call_summary(10.0, earnings, config=config, to_usd={"MYST": 0.10})
        # honeygain: 10 USD (no bonus)
        # mysterium: 20 MYST raw = $2.0 total, bonus 4 MYST, adjusted 16 MYST = $1.6
        assert result["total"] == 12.0  # 10 + 2.0
        assert result["total_adjusted"] == 11.6  # 10 + 1.6
        assert result["total_bonus"] == 0.4  # 4 MYST * 0.10

    def test_matches_breakdown_sum(self):
        """total_adjusted should equal sum of per-service adjusted balances."""
        earnings = [
            _earnings_entry("a", 15.0),
            _earnings_entry("b", 3.0),
            _earnings_entry("c", 25.0),
        ]
        config = {"a_signup_bonus": "5.0", "b_signup_bonus": "10.0"}
        result = _call_summary(43.0, earnings, config=config)
        # a: max(0, 15-5) = 10, b: max(0, 3-10) = 0, c: 25
        expected_adjusted = 10.0 + 0.0 + 25.0
        assert result["total_adjusted"] == expected_adjusted
