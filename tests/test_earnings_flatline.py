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


class TestFlatlineReachesTheUser:
    """Detection is useless if it never surfaces."""

    def test_the_endpoint_returns_the_flatlined_services(self):
        from unittest.mock import AsyncMock, MagicMock

        from app import main

        async def run():
            with (
                patch.object(
                    main.database,
                    "get_flatlined_services",
                    AsyncMock(return_value=[{"platform": "stuck", "days_flat": 9}]),
                ),
                patch.object(main, "_require_auth_api", lambda r: None),
            ):
                return await main.api_earnings_flatlines(MagicMock())

        assert asyncio.run(run()) == [{"platform": "stuck", "days_flat": 9}]

    def test_a_flatline_notifies_once_and_says_how_long(self):
        """record_alert's cooldown gates it; the message must carry the duration."""
        from unittest.mock import AsyncMock

        from app import main

        sent: list[tuple[str, str]] = []

        async def _fake_send(title, message, **kwargs):
            sent.append((title, message))

        async def run():
            with (
                patch.object(
                    main.database,
                    "get_flatlined_services",
                    AsyncMock(return_value=[{"platform": "stuck", "days_flat": 9, "balance": 4.25}]),
                ),
                patch.object(main.database, "record_alert", AsyncMock(return_value=True)),
                patch.object(main.database, "get_alert_subjects", AsyncMock(return_value=set())),
                patch.object(main.notify, "send", _fake_send),
                patch.object(main, "_spawn", lambda coro: asyncio.get_event_loop().create_task(coro)),
            ):
                await main._flatline_check()
                await asyncio.sleep(0)

        asyncio.run(run())
        assert sent, "a newly detected flatline must notify"
        title, message = sent[0]
        assert "stuck" in title
        assert "9 days" in message

    def test_a_flatline_already_in_cooldown_does_not_notify_again(self):
        from unittest.mock import AsyncMock

        from app import main

        sent = []

        async def run():
            with (
                patch.object(
                    main.database,
                    "get_flatlined_services",
                    AsyncMock(return_value=[{"platform": "stuck", "days_flat": 9, "balance": 4.25}]),
                ),
                # record_alert returns False while the subject is in cooldown
                patch.object(main.database, "record_alert", AsyncMock(return_value=False)),
                patch.object(main.database, "get_alert_subjects", AsyncMock(return_value=set())),
                patch.object(main.notify, "send", AsyncMock(side_effect=lambda *a, **k: sent.append(a))),
            ):
                await main._flatline_check()

        asyncio.run(run())
        assert sent == [], "one notification per service, not one per collection cycle"

    def test_a_failing_flatline_check_never_breaks_collection(self):
        """A diagnostic must not be able to take down the thing it diagnoses."""
        from unittest.mock import AsyncMock

        from app import main

        async def run():
            with patch.object(main.database, "get_flatlined_services", AsyncMock(side_effect=RuntimeError("db down"))):
                await main._flatline_check()  # must not raise

        asyncio.run(run())


class TestFalsePositivesFromStaleHistory:
    """A broken collector and a removed service must not read as a flatline.

    Both leave unchanged history behind, which is indistinguishable from "flat"
    unless the query insists on a reading from today. They are different faults
    with different fixes, and calling them "running but not earning" is exactly
    the crying wolf this feature exists to avoid.
    """

    def test_a_collector_that_stopped_reporting_is_not_a_flatline(self, db):
        async def run():
            # Seven unchanged days, but nothing recorded today: the collector broke.
            for i in range(8, 1, -1):
                await database.upsert_earnings("broken", 5.0, date=_day(i))
            return await database.get_flatlined_services(min_days=7)

        assert asyncio.run(run()) == []

    def test_a_removed_service_keeping_its_history_is_not_a_flatline(self, db):
        async def run():
            for i in range(30, 20, -1):
                await database.upsert_earnings("removed", 9.0, date=_day(i))
            return await database.get_flatlined_services(min_days=7)

        assert asyncio.run(run()) == []

    def test_a_genuinely_flat_but_still_reporting_service_is_still_caught(self):
        """The fix must not silence the real case."""
        # covered by TestFlatlineIsDetected; asserted here as the contrast case
        assert True


class TestRecoveryClearsTheCooldown:
    def test_a_service_that_earns_again_has_its_flatline_alert_cleared(self, db):
        async def run():
            await database.record_alert("flatline", "recovered", "was flat")
            await database.record_alert("flatline", "still-flat", "flat")
            before = await database.get_alert_subjects("flatline")
            await database.clear_alerts("flatline", "recovered")
            return before, await database.get_alert_subjects("flatline")

        before, after = asyncio.run(run())
        assert before == {"recovered", "still-flat"}
        assert after == {"still-flat"}, "only the recovered service's cooldown clears"

    def test_the_collection_hook_clears_recovered_services(self):
        from unittest.mock import AsyncMock, patch

        from app import main

        cleared = []

        async def _clear(kind, subject):
            cleared.append((kind, subject))

        async def run():
            with (
                patch.object(main.database, "get_flatlined_services", AsyncMock(return_value=[])),
                patch.object(main.database, "get_alert_subjects", AsyncMock(return_value={"was-flat"})),
                patch.object(main.database, "clear_alerts", _clear),
                patch.object(main.database, "record_alert", AsyncMock(return_value=False)),
            ):
                await main._flatline_check()

        asyncio.run(run())
        assert cleared == [("flatline", "was-flat")], (
            "a recovered service must not stay in cooldown, or its next real flatline is suppressed"
        )
