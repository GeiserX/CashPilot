"""Integration tests for payout eligibility in /api/earnings/breakdown.

These tests call the actual route handler with mocked DB/catalog/auth
dependencies, so they exercise real route wiring and response assembly.

Requires fastapi + httpx (installed in CI via requirements.txt).
Skipped automatically in minimal local environments.
"""

import os

# Fleet key env must be set before app.main import triggers resolve_fleet_key()
os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

try:
    from app.main import api_earnings_breakdown  # noqa: E402
except ImportError:
    pytest.skip("Requires full app dependencies (fastapi, httpx, etc.) — runs in CI", allow_module_level=True)

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402


def _earnings_row(platform, balance, prev_balance=0, currency="USD"):
    return {
        "platform": platform,
        "balance": balance,
        "prev_balance": prev_balance,
        "currency": currency,
        "date": "2026-01-01T00:00:00",
    }


def _service(slug, cashout=None):
    svc = {"name": slug.replace("-", " ").title(), "slug": slug}
    if cashout is not None:
        svc["cashout"] = cashout
    return svc


async def _call_breakdown(rows, services_by_slug):
    """Call the real handler with mocked dependencies."""
    request = MagicMock()
    with (
        patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "test", "r": "owner"}),
        patch("app.main.database.get_earnings_per_service", new_callable=AsyncMock, return_value=rows),
        patch("app.main.catalog.get_service", side_effect=lambda slug: services_by_slug.get(slug)),
    ):
        return await api_earnings_breakdown(request)


@pytest.mark.asyncio
class TestBreakdownEligibility:
    """Zero-threshold payout eligibility via the real route handler."""

    async def test_zero_threshold_positive_balance_eligible(self):
        rows = [_earnings_row("svc-a", balance=5.0)]
        svcs = {"svc-a": _service("svc-a", cashout={"min_amount": 0, "dashboard_url": "https://x.com"})}
        result = await _call_breakdown(rows, svcs)
        assert result[0]["cashout"]["eligible"] is True

    async def test_zero_threshold_zero_balance_not_eligible(self):
        rows = [_earnings_row("svc-a", balance=0.0)]
        svcs = {"svc-a": _service("svc-a", cashout={"min_amount": 0})}
        result = await _call_breakdown(rows, svcs)
        assert result[0]["cashout"]["eligible"] is False

    async def test_normal_threshold_above(self):
        rows = [_earnings_row("svc-a", balance=10.0)]
        svcs = {"svc-a": _service("svc-a", cashout={"min_amount": 5})}
        result = await _call_breakdown(rows, svcs)
        assert result[0]["cashout"]["eligible"] is True

    async def test_normal_threshold_exact(self):
        rows = [_earnings_row("svc-a", balance=5.0)]
        svcs = {"svc-a": _service("svc-a", cashout={"min_amount": 5})}
        result = await _call_breakdown(rows, svcs)
        assert result[0]["cashout"]["eligible"] is True

    async def test_normal_threshold_below(self):
        rows = [_earnings_row("svc-a", balance=3.0)]
        svcs = {"svc-a": _service("svc-a", cashout={"min_amount": 5})}
        result = await _call_breakdown(rows, svcs)
        assert result[0]["cashout"]["eligible"] is False

    async def test_no_cashout_section_not_eligible(self):
        """Service with no cashout in catalog should never be eligible."""
        rows = [_earnings_row("svc-a", balance=100.0)]
        svcs = {"svc-a": _service("svc-a", cashout=None)}
        result = await _call_breakdown(rows, svcs)
        assert result[0]["cashout"]["eligible"] is False

    async def test_unknown_service_not_eligible(self):
        """Service not in catalog (svc returns None) should not be eligible."""
        rows = [_earnings_row("unknown", balance=50.0)]
        result = await _call_breakdown(rows, {})
        assert result[0]["cashout"]["eligible"] is False
        assert result[0]["name"] == "unknown"  # falls back to slug

    async def test_response_includes_cashout_fields(self):
        """Verify full cashout response structure from the real handler."""
        rows = [_earnings_row("svc-a", balance=10.0)]
        svcs = {
            "svc-a": _service(
                "svc-a",
                cashout={
                    "min_amount": 5,
                    "method": "api",
                    "dashboard_url": "https://dash.example.com",
                    "notes": "Payout every Monday",
                },
            )
        }
        result = await _call_breakdown(rows, svcs)
        co = result[0]["cashout"]
        assert co["eligible"] is True
        assert co["min_amount"] == 5.0
        assert co["method"] == "api"
        assert co["dashboard_url"] == "https://dash.example.com"
        assert co["notes"] == "Payout every Monday"

    async def test_delta_computation(self):
        """Verify delta is computed from real handler, not just eligibility."""
        rows = [_earnings_row("svc-a", balance=10.0, prev_balance=7.5)]
        svcs = {"svc-a": _service("svc-a", cashout={"min_amount": 0})}
        result = await _call_breakdown(rows, svcs)
        assert result[0]["delta"] == 2.5

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
    async def test_edge_cases(self, balance, min_amount, expected):
        rows = [_earnings_row("svc-a", balance=balance)]
        svcs = {"svc-a": _service("svc-a", cashout={"min_amount": min_amount, "dashboard_url": "https://x.com"})}
        result = await _call_breakdown(rows, svcs)
        assert result[0]["cashout"]["eligible"] is expected
