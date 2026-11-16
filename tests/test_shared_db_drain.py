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
import sys
import threading

import aiosqlite
import pytest

from tests.conftest import close_shared_conns, connect_closable_from_any_thread


@contextlib.contextmanager
def _connection_whose_thread_died_on_a_closed_loop(
    path,
    *,
    uncommitted_write: bool = False,
    on_death=None,
    in_flight: int = 1,
    connect=connect_closable_from_any_thread,
):
    """Yield an aiosqlite connection whose worker thread died on a closed loop.

    The held query ends only when ``release`` is set, never on a timer: a timer
    could fire while the loop is still open on a slow runner, and then the
    thread would live. On any way out, the query is released and the
    connection is drained, so a failed setup or assertion never leaves a
    non-daemon worker thread that keeps pytest from exiting.

    The thread's death is the point, so its exception is expected and kept out
    of pytest's report: ``on_death`` gets it instead, and by default drops it.
    Opened as the suite opens its shared connections, unless ``connect`` says
    otherwise.
    """
    release = threading.Event()
    opened: list[aiosqlite.Connection] = []
    pytest_hook = threading.excepthook

    def drop_the_worker_death(args) -> None:
        if not any(args.thread is conn._thread for conn in opened):
            pytest_hook(args)
        elif on_death is not None:
            on_death(args)

    async def leave_a_query_in_flight() -> aiosqlite.Connection:
        conn = await connect(str(path))
        opened.append(conn)
        await conn.create_function("hold", 0, release.wait)
        if uncommitted_write:
            await conn.execute("CREATE TABLE IF NOT EXISTS t (x)")
            await conn.commit()
            # Cancelled before its commit, as a collection run can be.
            await conn.execute("INSERT INTO t VALUES (1)")
        # Fire and forget, as _deploy does with _run_collection: asyncio.run
        # cancels this task, but the query keeps running on the thread.
        # More than one: the rest wait in the dead thread's queue.
        for _ in range(in_flight):
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
        try:
            close_shared_conns(opened)
        finally:
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
        _assert_the_next_writer_writes_at_once(path)


def test_queries_left_queued_behind_the_dead_one_do_not_keep_the_lock(tmp_path):
    """Two tasks on one loop share the connection, as a gather of collectors does.

    The thread dies answering the first; the second stays in its queue, bound to
    the sqlite handle, so freeing the handle by dropping references never works.
    """
    path = tmp_path / "queued.db"
    with _connection_whose_thread_died_on_a_closed_loop(path, uncommitted_write=True, in_flight=2) as conn:
        assert not conn._thread.is_alive()
        assert conn._tx.qsize() >= 1, "nothing was left queued; this test proves nothing"

        close_shared_conns([conn])

        _assert_the_next_writer_writes_at_once(path)


def _assert_the_next_writer_writes_at_once(path) -> None:
    # The next test's connection: it must write at once, not wait on a lock
    # held by a handle nobody can reach any more.
    nxt = sqlite3.connect(path, timeout=0.5)
    try:
        nxt.execute("INSERT INTO t VALUES (2)")
        nxt.commit()
        # The cancelled write was rolled back, never committed.
        assert nxt.execute("SELECT x FROM t").fetchall() == [(2,)]
    finally:
        nxt.close()


# The worker's death is the point of the setup, so its traceback is expected.
@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_shared_connection_held_by_a_logged_traceback_does_not_keep_the_lock(tmp_path, monkeypatch, caplog):
    """The path CI takes: a fire-and-forget task through ``_get_db`` dies at shutdown.

    The task raises while ``asyncio.run`` cancels it, asyncio logs that with its
    traceback, and pytest keeps the record until the test ends. The traceback
    reaches the borrowed ``execute`` frame, whose ``raw`` is the sqlite handle.
    """
    from app import database

    path = tmp_path / "logged.db"
    monkeypatch.setattr(database, "DB_PATH", path)
    release = threading.Event()

    async def collect(db) -> None:
        try:
            await db.execute("SELECT hold()")
        finally:
            raise RuntimeError("a collection run that fails while it is cancelled")

    async def deploy() -> aiosqlite.Connection:
        db = await database._get_db()
        await db.create_function("hold", 0, release.wait)
        await db.execute("CREATE TABLE t (x)")
        await db.commit()
        await db.execute("INSERT INTO t VALUES (1)")  # cancelled before its commit
        asyncio.get_running_loop().create_task(collect(db))
        await asyncio.sleep(0.05)
        return object.__getattribute__(db, "_conn")

    try:
        conn = asyncio.run(deploy())
    finally:
        release.set()
    conn._thread.join(timeout=5)
    assert not conn._thread.is_alive()
    assert any(r.exc_info for r in caplog.records), "asyncio logged no traceback; this test proves nothing"
    assert conn._connection.in_transaction

    conns = list(database._shared_conns.values())
    database._shared_conns.clear()
    close_shared_conns(conns)

    _assert_the_next_writer_writes_at_once(path)


def test_control_a_healthy_connection_is_closed_for_real(tmp_path):
    async def open_one() -> aiosqlite.Connection:
        return await aiosqlite.connect(str(tmp_path / "healthy.db"))

    conn = asyncio.run(open_one())
    assert conn._thread.is_alive()

    close_shared_conns([conn])

    assert not conn._thread.is_alive()
    assert conn._connection is None, "the sqlite connection was left open"


def test_a_death_pytest_keeps_on_record_does_not_keep_the_lock(tmp_path):
    """The thread can die in teardown, after pytest last emptied its record.

    pytest keeps every thread's exception until the end of the test phase, and
    the traceback reaches the dead worker's frame, which still holds the query
    it ran and its cursor, so the handle is still alive at the drain.
    """
    kept: list[BaseException] = []
    path = tmp_path / "kept.db"
    with _connection_whose_thread_died_on_a_closed_loop(
        path, uncommitted_write=True, on_death=lambda a: kept.append(a.exc_value)
    ) as conn:
        assert kept, "the death never reached the hook; this test proves nothing"

        close_shared_conns([conn])

        _assert_the_next_writer_writes_at_once(path)


def test_control_a_handle_with_pythons_thread_check_still_drains(tmp_path):
    """A test that reloads ``app.database`` opens one the plain way; it must not fail the drain."""
    with _connection_whose_thread_died_on_a_closed_loop(tmp_path / "plain.db", connect=aiosqlite.connect) as conn:
        assert not conn._thread.is_alive()
        close_shared_conns([conn])
        assert conn._connection is None


def test_a_drain_that_fails_still_gives_pytest_its_thread_hook_back(tmp_path, monkeypatch):
    pytest_hook = threading.excepthook
    real_drain = close_shared_conns

    def failing_drain(conns) -> None:
        real_drain(conns)
        raise RuntimeError("the drain failed")

    monkeypatch.setattr(sys.modules[__name__], "close_shared_conns", failing_drain)
    with (
        pytest.raises(RuntimeError, match="the drain failed"),
        _connection_whose_thread_died_on_a_closed_loop(tmp_path / "hook.db"),
    ):
        pass

    assert threading.excepthook is pytest_hook
