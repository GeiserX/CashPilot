"""The dashboard cards and the trend chart must count non-USD platforms.

Three separate SQL aggregates and the chart query each carried their own copy
of the earnings arithmetic, and every one of them filtered ``currency = 'USD'``.
An installation earning MYST, GRASS or ANYONE — which is most of this catalog —
saw "$0.00 today", "$0.00 this month" and a flat-zero chart while its balances
climbed all week. Nothing looked broken; the numbers were simply wrong.

The existing tests could not catch it: `tests/test_database.py` only ever
inserts USD rows, and `tests/test_summary_bonus.py` / `tests/test_main_routes.py`
mock the summary function entirely. Every one of them passes against the bug.
So these tests are all mixed-currency by construction.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app import database


def day(n: int) -> str:
    return (datetime.now(UTC) - timedelta(days=n)).strftime("%Y-%m-%d")


class Fixture:
    """A real SQLite database, because the bug lived in the SQL."""

    def __init__(self, tmp_path, name):
        self.tmp_path = tmp_path
        self.name = name
        self.rows: list[tuple] = []

    def earning(self, platform, balance, days_ago, currency="USD", rate=None):
        self.rows.append((platform, balance, days_ago, currency, rate))
        return self

    def _run(self, coro_factory):
        async def go():
            with (
                patch.object(database, "DB_DIR", self.tmp_path),
                patch.object(database, "DB_PATH", self.tmp_path / f"{self.name}.db"),
            ):
                await database.init_db()
                for platform, balance, days_ago, currency, rate in self.rows:
                    await database.upsert_earnings(
                        platform, balance, currency=currency, date=day(days_ago), fx_rate_usd=rate
                    )
                return await coro_factory()

        return asyncio.run(go())

    def summary(self):
        return self._run(database.get_earnings_dashboard_summary)

    def chart(self, days=7):
        return self._run(lambda: database.get_daily_earnings(days=days))


class TestTheCardsCountEveryCurrency:
    def test_a_token_only_fleet_does_not_read_as_zero(self, tmp_path):
        """The reported symptom: MystNodes-only, balance climbing, cards at $0.00."""
        summary = (
            Fixture(tmp_path, "myst")
            .earning("mysterium", 100.0, 1, "MYST", 0.10)
            .earning("mysterium", 102.0, 0, "MYST", 0.10)
            .summary()
        )
        assert summary["today"] == pytest.approx(0.20)

    def test_usd_and_token_platforms_add_up_together(self, tmp_path):
        summary = (
            Fixture(tmp_path, "mix")
            .earning("mysterium", 100.0, 1, "MYST", 0.10)
            .earning("mysterium", 102.0, 0, "MYST", 0.10)
            .earning("honeygain", 5.0, 1)
            .earning("honeygain", 5.5, 0)
            .summary()
        )
        assert summary["today"] == pytest.approx(0.70), "0.20 from MYST + 0.50 from USD"

    def test_the_month_includes_token_earnings(self, tmp_path):
        summary = (
            Fixture(tmp_path, "month")
            .earning("grass", 1000.0, 2, "GRASS", 0.002)
            .earning("grass", 1500.0, 0, "GRASS", 0.002)
            .summary()
        )
        assert summary["month"] == pytest.approx(1.0)

    def test_the_delta_is_priced_not_the_balance(self, tmp_path):
        """A rate move alone must not move the card.

        Converting the running total and subtracting afterwards would report
        the rate change itself as income.
        """
        summary = (
            Fixture(tmp_path, "ratemove")
            .earning("mysterium", 100.0, 1, "MYST", 0.50)
            .earning("mysterium", 100.0, 0, "MYST", 0.90)
            .summary()
        )
        assert summary["today"] == pytest.approx(0.0), "the balance never moved"

    def test_an_unpriced_platform_is_excluded_rather_than_counted_at_parity(self, tmp_path):
        """1 GRASS is not $1."""
        summary = (
            Fixture(tmp_path, "unpriced")
            .earning("grass", 1000.0, 1, "GRASS")
            .earning("grass", 2000.0, 0, "GRASS")
            .summary()
        )
        assert summary["today"] == pytest.approx(0.0)


class TestTheChartCountsEveryCurrency:
    def test_a_token_only_fleet_does_not_draw_a_flat_zero_line(self, tmp_path):
        chart = (
            Fixture(tmp_path, "chart")
            .earning("mysterium", 100.0, 1, "MYST", 0.10)
            .earning("mysterium", 102.0, 0, "MYST", 0.10)
            .chart(days=3)
        )
        assert chart[-1]["amount"] == pytest.approx(0.20)
        assert any(point["amount"] > 0 for point in chart), "every bar was zero"

    def test_a_new_platform_does_not_spike_its_whole_opening_balance(self, tmp_path):
        """A first-ever reading is not a day's earnings.

        Differencing against an implicit zero drew a newly added service as one
        enormous bar the size of its entire existing balance.
        """
        chart = Fixture(tmp_path, "spike").earning("honeygain", 250.0, 0).chart(days=3)
        assert all(point["amount"] == 0 for point in chart), f"opening balance counted as earnings: {chart}"

    def test_the_chart_and_the_today_card_agree(self, tmp_path):
        """They were computed by two separate queries and could disagree."""
        fixture = (
            Fixture(tmp_path, "agree")
            .earning("mysterium", 100.0, 1, "MYST", 0.10)
            .earning("mysterium", 102.0, 0, "MYST", 0.10)
            .earning("honeygain", 5.0, 1)
            .earning("honeygain", 5.5, 0)
        )
        assert fixture.chart(days=2)[-1]["amount"] == pytest.approx(fixture.summary()["today"])


class TestThePayoutClampSurvivedTheRewrite:
    def test_a_payout_on_one_platform_does_not_eat_another_platforms_earnings(self, tmp_path):
        """The reason the original clamped per platform before summing."""
        summary = (
            Fixture(tmp_path, "clamp")
            .earning("honeygain", 20.0, 1)
            .earning("honeygain", 0.10, 0)  # paid out
            .earning("iproyal", 5.0, 1)
            .earning("iproyal", 6.0, 0)  # genuinely earned 1.00
            .summary()
        )
        assert summary["today"] == pytest.approx(1.0), "the payout drop cancelled real earnings"
