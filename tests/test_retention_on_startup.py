"""Retention must run on an instance that restarts more than once a day.

The purge is a 24-hour APScheduler interval, and an interval trigger counts from
process start and does not fire on start. The UI is recreated on every release,
so an auto-updating install that ships more often than daily never reaches the
first tick: ours restarted eight times in a day and had 3,960 health-check rows
past their 95-day window. The update check hit the same trap and was fixed by
running it once at startup; retention now does the same, and keeps its timer.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import textwrap
from unittest.mock import AsyncMock, patch

from app import main


def _lifespan_calls() -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(main.lifespan.__wrapped__)))
    return {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}


def test_the_purge_runs_once_at_startup():
    """Runs the real lifespan: the call must happen before it yields, not merely exist."""
    retention = AsyncMock()

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
            patch("app.main._run_data_retention", retention),
        ):
            async with main.lifespan(main.app):
                await asyncio.sleep(0)
                assert retention.await_count == 1, (
                    "retention only runs 24 h after start, which an install restarting daily never reaches"
                )

    asyncio.run(run())


def test_the_daily_timer_is_kept():
    source = inspect.getsource(main.lifespan.__wrapped__)
    assert 'id="data_retention"' in source


def test_the_control_finds_a_call_that_is_really_there():
    """Guards the guard: the walker must see the startup collection it already spawns."""
    assert "_run_collection" in _lifespan_calls()
