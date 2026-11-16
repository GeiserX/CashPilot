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
import contextlib
import sqlite3
import threading

import aiosqlite

from tests.conftest import close_shared_conns


@contextlib.contextmanager
def _connection_whose_thread_died_on_a_closed_loop(path, *, uncommitted_write: bool = False):
    """Yield an aiosqlite connection whose worker thread died on a closed loop.

    The held query ends only when ``release`` is set, never on a timer: a timer
    could fire while the loop is still open on a slow runner, and then the
    thread would live. On any way out, the query is released and the
    connection is drained, so a failed setup or assertion never leaves a
    non-daemon worker thread that keeps pytest from exiting.

    The thread's death is the point, so its exception is expected and kept out
    of pytest's report. It is also dropped at once: pytest would hold its
    traceback, and with it the sqlite handle, until the test ends. In a real
    run the thread dies in a test's body and that hold is gone by the time
    the drain runs in teardown.
    """
    release = threading.Event()
    opened: list[aiosqlite.Connection] = []
    pytest_hook = threading.excepthook

    def drop_the_worker_death(args) -> None:
        if not any(args.thread is conn._thread for conn in opened):
            pytest_hook(args)

    async def leave_a_query_in_flight() -> aiosqlite.Connection:
        conn = await aiosqlite.connect(str(path))
        opened.append(conn)
        await conn.create_function("hold", 0, release.wait)
        if uncommitted_write:
            await conn.execute("CREATE TABLE IF NOT EXISTS t (x)")
            await conn.commit()
            # Cancelled before its commit, as a collection run can be.
            await conn.execute("INSERT INTO t VALUES (1)")
        # Fire and forget, as _deploy does with _run_collection: asyncio.run
        # cancels this task, but the query keeps running on the thread.
        asyncio.get_running_loop().create_task(conn.execute("SELECT hold()"))
        await asyncio.sleep(0.05)
        return conn

    threading.excepthook = drop_the_worker_death
    try:
        conn = asyncio.run(leave_a_query_in_flight())
        release.set()  # the query ends now, after its loop has closed
        conn._thread.join(timeout=5)
        yield conn
    finally:
        release.set()
        close_shared_conns(opened)
        threading.excepthook = pytest_hook


def test_a_connection_whose_thread_died_is_drained_in_seconds(tmp_path):
    with _connection_whose_thread_died_on_a_closed_loop(tmp_path / "drain.db") as conn:
        _assert_drained_in_seconds(conn)


def _assert_drained_in_seconds(conn: aiosqlite.Connection) -> None:
    # The state CI hung on, or this test proves nothing: the thread is gone and
    # the connection still claims to be open.
    assert not conn._thread.is_alive()
    assert conn._running

    # The drain's own error is caught here and raised again: a drain that
    # crashes is not one that got through.
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


def test_a_dead_connections_open_write_does_not_lock_the_next_writer(tmp_path):
    path = tmp_path / "locked.db"
    with _connection_whose_thread_died_on_a_closed_loop(path, uncommitted_write=True) as conn:
        assert not conn._thread.is_alive()
        assert conn._connection.in_transaction, "setup left no open write; this test proves nothing"

        close_shared_conns([conn])

        assert conn._connection is None, "the dead thread's sqlite handle was left open"
        # The next test's connection: it must write at once, not wait on a
        # lock held by a handle nobody can reach any more.
        nxt = sqlite3.connect(path, timeout=0.5)
        try:
            nxt.execute("INSERT INTO t VALUES (2)")
            nxt.commit()
            # The cancelled write was rolled back, never committed.
            assert nxt.execute("SELECT x FROM t").fetchall() == [(2,)]
        finally:
            nxt.close()


def test_control_a_healthy_connection_is_closed_for_real(tmp_path):
    async def open_one() -> aiosqlite.Connection:
        return await aiosqlite.connect(str(tmp_path / "healthy.db"))

    conn = asyncio.run(open_one())
    assert conn._thread.is_alive()

    close_shared_conns([conn])

    assert not conn._thread.is_alive()
    assert conn._connection is None, "the sqlite connection was left open"
