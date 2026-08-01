"""Running is not earning (CashPilot-kbs).

A container can be up, its collector can authenticate happily, and the balance
can simply never move. Every other view of the system looks healthy, so nothing
surfaces it — the user finds out when they eventually notice they stopped being
paid.

These tests pin the detection AND its restraint. The bead is explicit that a
report which cries wolf is a report nobody reads, so most of what follows checks
the cases that must NOT be reported.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app import database


@pytest.fixture
def db_dir(tmp_path):
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"),
    ):
        yield tmp_path


@pytest.fixture
def db(db_dir):
    asyncio.run(database.init_db())
    return db_dir


def _day(offset: int) -> str:
    return (datetime.now(UTC) - timedelta(days=offset)).strftime("%Y-%m-%d")


async def _seed(platform: str, balances: list[float]) -> None:
    """Record one balance per day, oldest first, ending today."""
    for i, balance in enumerate(balances):
        await database.upsert_earnings(platform, balance, date=_day(len(balances) - 1 - i))


class TestFlatlineIsDetected:
    def test_a_stuck_balance_is_reported(self, db):
        async def run():
            await _seed("stuck", [12.5] * 8)
            return await database.get_flatlined_services(min_days=7)

        flat = asyncio.run(run())
        assert len(flat) == 1
        assert flat[0]["platform"] == "stuck"
        assert flat[0]["balance"] == 12.5
        assert flat[0]["days_flat"] >= 7


class TestFlatlineRestraint:
    """Everything here must NOT be reported."""

    def test_a_moving_balance_is_not_reported(self, db):
        async def run():
            await _seed("earning", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
            return await database.get_flatlined_services(min_days=7)

        assert asyncio.run(run()) == []

    def test_a_balance_that_moved_only_once_is_not_reported(self, db):
        """Slow earners still count as earning."""

        async def run():
            await _seed("slow", [5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.01])
            return await database.get_flatlined_services(min_days=7)

        assert asyncio.run(run()) == []

    def test_a_new_deployment_is_not_reported(self, db):
        """Too little history to call anything: it has not had time to earn."""

        async def run():
            await _seed("fresh", [3.0, 3.0, 3.0])
            return await database.get_flatlined_services(min_days=7)

        assert asyncio.run(run()) == []

    def test_a_permanently_zero_balance_is_not_reported(self, db):
        """Never earned is a setup problem, not a service that stopped paying."""

        async def run():
            await _seed("zero", [0.0] * 8)
            return await database.get_flatlined_services(min_days=7)

        assert asyncio.run(run()) == []

    def test_a_collection_outage_cannot_look_like_a_flatline(self, db):
        """Gaps record nothing, so distinct recorded days stay below the window."""

        async def run():
            # Same balance, but only 3 days were ever recorded across a long span.
            for offset in (30, 20, 10):
                await database.upsert_earnings("gappy", 9.0, date=_day(offset))
            return await database.get_flatlined_services(min_days=7)

        assert asyncio.run(run()) == []

    def test_only_the_flat_service_is_reported_among_many(self, db):
        async def run():
            await _seed("good", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
            await _seed("bad", [4.25] * 8)
            await _seed("young", [1.0, 1.0])
            return await database.get_flatlined_services(min_days=7)

        flat = asyncio.run(run())
        assert [f["platform"] for f in flat] == ["bad"]
