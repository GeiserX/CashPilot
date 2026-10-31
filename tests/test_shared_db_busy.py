"""A write refused as locked must not leave the shared connection stuck.

On 2026-10-31 (v1.58.0) one heartbeat write waited out the busy timeout behind
another connection. The sqlite3 module had already sent BEGIN, and nothing
rolled it back. The next read pinned a snapshot inside that open transaction,
``record_usage`` committed on its own connection, and from then on every write
on the shared connection failed at once with SQLITE_BUSY_SNAPSHOT
("database is locked") until the UI was restarted nine minutes later.
"""

import asyncio
import logging
import os
import sqlite3
from unittest.mock import patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest

from app import database


@pytest.fixture
def db_dir(tmp_path):
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"),
    ):
        asyncio.run(database.init_db())
        yield tmp_path


def _other_connection() -> sqlite3.Connection:
    """A second connection, as record_usage and the payout helpers open."""
    return sqlite3.connect(str(database.DB_PATH), isolation_level=None, timeout=0)


class TestOneLockedWriteDoesNotLockEveryLaterWrite:
    def test_the_incident_sequence_recovers(self, db_dir):
        async def run() -> None:
            shared = await database._get_db()
            # The production timeout is 5 s; the sequence is the same at 50 ms.
            await shared.execute("PRAGMA busy_timeout=50")
            other = _other_connection()
            try:
                # 1. Another connection holds the write lock past the busy timeout.
                other.execute("BEGIN IMMEDIATE")
                other.execute("INSERT INTO config (key, value) VALUES ('held', '1')")
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    await database.set_config("heartbeat", "1")
                other.execute("COMMIT")

                # 2. Any task reads on the shared connection (the next heartbeat's
                #    get_worker_status_and_name, a page load).
                await database.get_config("anything")

                # 3. Another connection commits (record_usage, every heartbeat).
                other.execute("INSERT INTO config (key, value) VALUES ('usage', '1')")

                # 4. Nobody holds a lock now, so writes must work again.
                for i in range(3):
                    await database.set_config(f"after-{i}", str(i))
                assert other.execute("SELECT value FROM config WHERE key = 'after-2'").fetchone() == ("2",)
                assert await database.get_config("usage") == "1", "the shared connection reads a stale snapshot"
            finally:
                other.close()

        asyncio.run(run())

    def test_executemany_recovers_too(self, db_dir):
        async def run() -> None:
            shared = await database._get_db()
            await shared.execute("PRAGMA busy_timeout=50")
            other = _other_connection()
            try:
                other.execute("BEGIN IMMEDIATE")
                other.execute("INSERT INTO config (key, value) VALUES ('held', '1')")
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    await database.set_config_bulk({"a": "1", "b": "2"})
                other.execute("COMMIT")
                await database.get_config("anything")
                other.execute("INSERT INTO config (key, value) VALUES ('usage', '1')")
                await database.set_config_bulk({"a": "1", "b": "2"})
                assert other.execute("SELECT value FROM config WHERE key = 'b'").fetchone() == ("2",)
            finally:
                other.close()

        asyncio.run(run())

    def test_the_rollback_is_logged(self, db_dir, caplog):
        async def run() -> None:
            shared = await database._get_db()
            await shared.execute("PRAGMA busy_timeout=50")
            other = _other_connection()
            try:
                other.execute("BEGIN IMMEDIATE")
                with pytest.raises(sqlite3.OperationalError):
                    await database.set_config("heartbeat", "1")
                other.execute("ROLLBACK")
            finally:
                other.close()

        with caplog.at_level(logging.WARNING, logger="app.database"):
            asyncio.run(run())
        assert any("rolled back" in r.getMessage() for r in caplog.records)


class TestOtherFailuresKeepTheOpenTransaction:
    def test_a_constraint_error_does_not_throw_away_earlier_uncommitted_writes(self, db_dir):
        """Only SQLITE_BUSY rolls back. Any other failed statement can sit in a
        transaction that already holds another task's writes; those must stay."""

        async def run() -> None:
            db = await database._get_db()
            await db.execute("INSERT INTO config (key, value) VALUES ('kept', '1')")
            with pytest.raises(sqlite3.IntegrityError):
                await db.execute("INSERT INTO config (key, value) VALUES ('kept', '2')")
            assert db.in_transaction
            await db.commit()
            assert await database.get_config("kept") == "1"

        asyncio.run(run())


class TestTheBootLogNamesANewTable:
    def test_the_12_to_13_upgrade_is_reported(self, db_dir, caplog):
        """Version 13 only added the state_backups table, and the log said
        "no migration needed" while it was being created."""

        async def make_v12() -> None:
            db = await database._get_db()
            await db.execute("DROP TABLE state_backups")
            await db.execute("PRAGMA user_version = 12")
            await db.commit()

        asyncio.run(make_v12())
        with caplog.at_level(logging.INFO, logger="app.database"):
            asyncio.run(database.init_db())
        messages = [r.getMessage() for r in caplog.records]
        summary = next((m for m in messages if "Migrations applied this boot" in m), None)
        assert summary, messages
        assert "(was 12)" in summary and "table state_backups created" in summary, summary
        assert not any("no migration needed" in m for m in messages), messages


class TestTheWrapperKeepsAiosqlitesInterface:
    def test_execute_works_as_a_context_manager(self, db_dir):
        async def run() -> None:
            db = await database._get_db()
            async with db.execute("SELECT 1") as cur:
                assert (await cur.fetchone())[0] == 1
            async with db.executemany("INSERT INTO config (key, value) VALUES (?, ?)", [("x", "1")]):
                pass
            await db.commit()
            assert await database.get_config("x") == "1"

        asyncio.run(run())
