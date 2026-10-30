"""VACUUM must run on an instance that restarts more than once a week.

The weekly VACUUM was an APScheduler interval, which counts from process start
and does not fire on start. Every release recreates the UI container, so an
auto-updating install never reached the first tick and kept every page that
retention freed. The last run is now stored in config: startup and the weekly
timer both run it only when the last one is more than 7 days old.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from app import main


def _vacuum(stamp, vacuum=None):
    """Run the gated VACUUM with the stored stamp; return (vacuum mock, set_config mock)."""
    vacuum = vacuum or AsyncMock()
    set_config = AsyncMock()

    async def get_config(key=None):
        assert key == main._LAST_VACUUM_KEY
        return stamp

    with (
        patch.object(main.database, "get_config", get_config),
        patch.object(main.database, "set_config", set_config),
        patch.object(main.database, "vacuum_database", vacuum),
    ):
        asyncio.run(main._run_vacuum())
    return vacuum, set_config


def _ago(days):
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


class TestItRunsOnlyWhenTheLastOneIsOld:
    def test_a_fresh_install_vacuums_and_records_it(self):
        vacuum, set_config = _vacuum(None)
        vacuum.assert_awaited_once()
        key, value = set_config.await_args.args
        assert key == main._LAST_VACUUM_KEY
        assert datetime.now(UTC) - datetime.fromisoformat(value) < timedelta(minutes=1)

    def test_a_vacuum_two_days_ago_is_not_repeated(self):
        """The control: a restart soon after a VACUUM must not rewrite the database again."""
        vacuum, set_config = _vacuum(_ago(2))
        vacuum.assert_not_awaited()
        set_config.assert_not_awaited()

    def test_a_vacuum_eight_days_ago_runs_again(self):
        vacuum, _ = _vacuum(_ago(8))
        vacuum.assert_awaited_once()

    def test_an_unreadable_stamp_does_not_block_it_forever(self):
        vacuum, _ = _vacuum("not a date")
        vacuum.assert_awaited_once()

    def test_a_failed_vacuum_is_not_recorded_as_done(self):
        vacuum, set_config = _vacuum(None, AsyncMock(side_effect=RuntimeError("disk full")))
        vacuum.assert_awaited_once()
        set_config.assert_not_awaited()


def test_it_runs_at_startup():
    """Runs the real lifespan: the call must happen before it yields, not merely exist."""
    vacuum = AsyncMock()

    async def run():
        with (
            patch("app.main.database.init_db", new_callable=AsyncMock),
            patch("app.main.database.connect_shared", new_callable=AsyncMock),
            patch("app.main.database.close_shared", new_callable=AsyncMock),
            patch("app.main.database.list_users_with_pwd_epoch", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.list_session_revocations", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=True),
            patch("app.main.catalog.load_services"),
            patch("app.main.catalog.register_sighup"),
            patch("app.main.exchange_rates.refresh", new_callable=AsyncMock),
            patch("app.main.update_check.refresh", new_callable=AsyncMock),
            patch("app.main.update_check.refresh_android", new_callable=AsyncMock),
            patch("app.main._run_collection", new_callable=AsyncMock),
            patch("app.main._run_data_retention", new_callable=AsyncMock),
            patch("app.main._run_vacuum", vacuum),
            patch("app.main._check_windowed_signals", new_callable=AsyncMock),
        ):
            async with main.lifespan(main.app):
                await asyncio.sleep(0)
                assert vacuum.await_count == 1, (
                    "VACUUM only ran a week after start, which a restarting install never reaches"
                )

    asyncio.run(run())
