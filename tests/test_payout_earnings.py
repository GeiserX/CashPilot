"""A payout on one platform must not erase earnings on another (CashPilot-glc).

The earnings table stores balance snapshots. When a payout lands, that platform's
balance falls. Earnings were computed by summing the per-platform deltas and only
then clamping the total at zero - so a large payout drop on one platform cancelled
real earnings on another before the clamp ever ran, understating what was earned.

The fix clamps each platform's delta at zero *before* summing, so a payout is
treated as "zero earned on that platform today", never as a negative that eats
into the rest.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app import database


@pytest.fixture
def db_dir(tmp_path):
    db_path = tmp_path / "cashpilot.db"
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", db_path),
    ):
        yield tmp_path


@pytest.fixture
def db(db_dir):
    asyncio.run(database.init_db())
    return db_dir


def _day(offset: int) -> str:
    return (datetime.now(UTC) - timedelta(days=offset)).strftime("%Y-%m-%d")


class TestPayoutDoesNotMaskEarnings:
    def test_today_summary_counts_the_earning_platform_through_a_payout(self, db):
        """Platform A pays out 20 the same day platform B earns 2."""

        async def run():
            # Yesterday's balances.
            await database.upsert_earnings("platform_a", 20.0, date=_day(1))
            await database.upsert_earnings("platform_b", 5.0, date=_day(1))
            # Today: A paid out (20 -> 0.10), B earned (5 -> 7).
            await database.upsert_earnings("platform_a", 0.10, date=_day(0))
            await database.upsert_earnings("platform_b", 7.0, date=_day(0))
            return await database.get_earnings_dashboard_summary()

        summary = asyncio.run(run())
        # B genuinely earned 2.00. The old code summed (-19.90 + 2.00) = -17.90,
        # clamped to 0.00, and reported nothing earned at all.
        assert summary["today"] == pytest.approx(2.0), (
            f"expected B's 2.00 to survive A's payout, got {summary['today']}"
        )

    def test_daily_chart_counts_the_earning_platform_through_a_payout(self, db):
        async def run():
            await database.upsert_earnings("platform_a", 20.0, date=_day(1))
            await database.upsert_earnings("platform_b", 5.0, date=_day(1))
            await database.upsert_earnings("platform_a", 0.10, date=_day(0))
            await database.upsert_earnings("platform_b", 7.0, date=_day(0))
            return await database.get_daily_earnings(days=2)

        chart = asyncio.run(run())
        today = chart[-1]["amount"]
        assert today == pytest.approx(2.0), f"chart should show B's 2.00, got {today}"

    def test_a_pure_payout_day_reads_as_zero_not_negative(self, db):
        """One platform, balance falls: the day reads 0 earned, never negative."""

        async def run():
            await database.upsert_earnings("solo", 20.0, date=_day(1))
            await database.upsert_earnings("solo", 0.0, date=_day(0))
            return await database.get_daily_earnings(days=2)

        chart = asyncio.run(run())
        assert chart[-1]["amount"] == 0.0
        assert all(point["amount"] >= 0 for point in chart)

    def test_ordinary_earnings_are_unchanged(self, db):
        """The fix must not disturb the normal all-platforms-earning case."""

        async def run():
            await database.upsert_earnings("platform_a", 10.0, date=_day(1))
            await database.upsert_earnings("platform_b", 5.0, date=_day(1))
            await database.upsert_earnings("platform_a", 12.0, date=_day(0))
            await database.upsert_earnings("platform_b", 6.5, date=_day(0))
            return await database.get_earnings_dashboard_summary()

        summary = asyncio.run(run())
        assert summary["today"] == pytest.approx(3.5)  # 2.0 + 1.5
