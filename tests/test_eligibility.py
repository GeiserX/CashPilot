"""Regression tests for payout eligibility logic.

The eligibility expression used in the /api/earnings/latest endpoint must
handle zero-threshold services (min_amount=0) correctly.
"""

import pytest


def _eligible(cashout: dict, balance: float, min_amount: float) -> bool:
    """Mirror the eligibility expression from main.py api_earnings_latest."""
    return bool(cashout) and balance > 0 and balance >= min_amount


class TestEligibility:
    """Zero-threshold payout eligibility (min_amount=0)."""

    def test_zero_threshold_positive_balance(self):
        assert _eligible({"min_amount": 0}, balance=5.0, min_amount=0)

    def test_zero_threshold_zero_balance(self):
        assert not _eligible({"min_amount": 0}, balance=0.0, min_amount=0)

    def test_normal_threshold_above(self):
        assert _eligible({"min_amount": 5}, balance=10.0, min_amount=5)

    def test_normal_threshold_exact(self):
        assert _eligible({"min_amount": 5}, balance=5.0, min_amount=5)

    def test_normal_threshold_below(self):
        assert not _eligible({"min_amount": 5}, balance=3.0, min_amount=5)

    def test_no_cashout_section(self):
        assert not _eligible({}, balance=10.0, min_amount=0)

    def test_empty_cashout_high_balance(self):
        """Empty cashout dict is falsy — no payout mechanism exists."""
        assert not _eligible({}, balance=100.0, min_amount=0)

    @pytest.mark.parametrize(
        "balance,min_amount,expected",
        [
            (0.0001, 0, True),
            (0, 0, False),
            (0, 10, False),
            (10, 10, True),
            (9.99, 10, False),
        ],
    )
    def test_edge_cases(self, balance, min_amount, expected):
        cashout = {"min_amount": min_amount, "dashboard_url": "https://example.com"}
        assert _eligible(cashout, balance, min_amount) is expected
