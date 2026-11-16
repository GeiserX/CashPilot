"""A cancelled collection run must end with CancelledError, not UnboundLocalError.

A run can be cancelled before its first database query returns (shutdown, or
asyncio.run tearing down in tests). CancelledError is not an Exception, so the
run's ``except Exception`` branch does not run, and the ``finally`` block used
to read ``platforms_ok`` before anything had set it. That raised
UnboundLocalError, which replaced the cancel and logged a misleading error.

A cancelled run also never completed, so it must be recorded as unsuccessful:
recording it as a success would refresh collection_last_success_timestamp and
hold off the staleness alerts.
"""

import asyncio
import os

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

try:
    from app import main  # noqa: E402
except ImportError:
    pytest.skip(
        "Requires full app dependencies (fastapi, httpx, etc.) — runs in CI",
        allow_module_level=True,
    )

from unittest.mock import AsyncMock, patch  # noqa: E402


@pytest.mark.asyncio
async def test_a_run_cancelled_during_get_deployments_ends_cleanly():
    ends = []

    def _capture_end(start, success, platforms_ok=0, collectors_configured=0):
        ends.append((success, platforms_ok, collectors_configured))

    started = asyncio.Event()

    async def _hang():
        started.set()
        await asyncio.Event().wait()

    with (
        patch.object(main.database, "get_deployments", _hang),
        patch.object(main.database, "get_config", AsyncMock(return_value={})),
        patch.object(main.metrics, "record_collection_end", _capture_end),
        patch.object(main, "_collection_has_run", False),
        patch.object(main, "_last_collection_finished", None),
    ):
        task = asyncio.create_task(main._run_collection())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # The finally block still ran to the end.
        assert main._collection_has_run is True
        assert main._last_collection_finished is not None

    # Recorded as a failed run, never as a success.
    assert ends == [(False, 0, 0)]
    # The lock is released, so the next run is not skipped.
    assert not main._collection_lock.locked()
