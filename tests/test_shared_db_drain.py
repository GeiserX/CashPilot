"""The per-test drain of shared SQLite connections must never hang the run.

On 2026-11-14 ten CI runs hung until GitHub's six-hour limit, right after
test_beads_batch_56's deploy test. That test calls ``api_deploy`` under
``asyncio.run``; the deploy spawns a collection run, ``asyncio.run`` cancels it
with its query still on the aiosqlite thread, and closes the loop. The query's
answer then goes to the closed loop and kills the thread. The drain in
conftest awaited ``conn.close()`` on that connection, and nothing was left to
answer it. This builds that exact state and checks the drain gets through it.
"""

from __future__ import annotations

import asyncio
import threading

import aiosqlite
import pytest

from tests.conftest import close_shared_conns


def _connection_whose_thread_died_on_a_closed_loop(path) -> aiosqlite.Connection:
    release = threading.Event()

    async def leave_a_query_in_flight() -> aiosqlite.Connection:
        conn = await aiosqlite.connect(str(path))
        await conn.create_function("hold", 0, lambda: release.wait(5))
        # Fire and forget, as _deploy does with _run_collection: asyncio.run
        # cancels this task, but the query keeps running on the thread.
        asyncio.get_running_loop().create_task(conn.execute("SELECT hold()"))
        await asyncio.sleep(0.05)
        return conn

    conn = asyncio.run(leave_a_query_in_flight())
    release.set()  # the query ends now, after its loop has closed
    conn._thread.join(timeout=5)
    return conn


# The thread's death is the point of the setup, so its traceback is expected.
@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_connection_whose_thread_died_is_drained_in_seconds(tmp_path):
    conn = _connection_whose_thread_died_on_a_closed_loop(tmp_path / "drain.db")
    # The state CI hung on, or this test proves nothing: the thread is gone and
    # the connection still claims to be open.
    assert not conn._thread.is_alive()
    assert conn._running

    # The warning filter above hides thread exceptions, so the drain's own
    # error is caught here and raised again: a drain that crashes is not one
    # that got through.
    errors: list[BaseException] = []

    def run_drain() -> None:
        try:
            close_shared_conns([conn])
        except BaseException as exc:
            errors.append(exc)

    drain = threading.Thread(target=run_drain, daemon=True)
    drain.start()
    drain.join(timeout=20)
    assert not drain.is_alive(), "the drain waited on a connection whose thread is dead; CI would hang here"
    if errors:
        raise errors[0]


def test_control_a_healthy_connection_is_closed_for_real(tmp_path):
    async def open_one() -> aiosqlite.Connection:
        return await aiosqlite.connect(str(tmp_path / "healthy.db"))

    conn = asyncio.run(open_one())
    assert conn._thread.is_alive()

    close_shared_conns([conn])

    assert not conn._thread.is_alive()
    assert conn._connection is None, "the sqlite connection was left open"
