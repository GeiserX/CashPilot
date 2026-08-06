"""CashPilot-sfbh: migrations ran and reported nothing.

Every schema change in ``init_db`` is guarded by its own ``PRAGMA table_info``
check, and they are careful. But **nothing said what happened.** An operator
watching ``docker logs`` through an upgrade could not tell a clean start from one
that had just rewritten the earnings table, and a bug report could not say either.

Two things are now reported at startup: the schema version, and which migrations
actually ran on this boot.

THE DESIGN DECISION THAT MATTERS: the version is REPORTED, NEVER USED AS A GATE.
If ``user_version`` decided whether migrations ran, a database whose version said
10 but was missing a column -- an interrupted upgrade, a restored backup, a
hand-edited file -- could never be repaired, because the gate would say there was
nothing to do. The ``PRAGMA table_info`` guards stay the source of truth; they are
idempotent and cheap. The version is for the human.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import patch

import pytest

from app import database


@pytest.fixture
def db_dir(tmp_path):
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
        yield tmp_path


def _user_version() -> int:
    async def run():
        conn = await database._get_db()
        cur = await conn.execute("PRAGMA user_version")
        row = await cur.fetchone()
        return int(row[0]) if row else 0

    return asyncio.run(run())


class TestTheVersionIsRecorded:
    def test_a_fresh_database_ends_at_the_current_version(self, db_dir):
        asyncio.run(database.init_db())
        assert _user_version() == database.SCHEMA_VERSION

    def test_the_constant_is_a_positive_int(self):
        """A float or a string would be interpolated into the PRAGMA."""
        assert isinstance(database.SCHEMA_VERSION, int)
        assert database.SCHEMA_VERSION > 0

    def test_a_second_boot_does_not_change_it(self, db_dir):
        asyncio.run(database.init_db())
        first = _user_version()
        asyncio.run(database.init_db())
        assert _user_version() == first


class TestTheStartupLogSaysWhatHappened:
    def test_a_fresh_database_reports_no_migration(self, db_dir, caplog):
        """A brand-new file creates its tables from _SCHEMA; no guarded
        migration fires, so saying one did would be false."""
        with caplog.at_level(logging.INFO, logger="app.database"):
            asyncio.run(database.init_db())
        assert any("no migration needed" in r.getMessage() for r in caplog.records), [
            r.getMessage() for r in caplog.records
        ]

    def test_it_always_says_something(self, db_dir, caplog):
        """Silence is the defect being fixed. Whatever happened, one line."""
        with caplog.at_level(logging.INFO, logger="app.database"):
            asyncio.run(database.init_db())
        assert any("Schema" in (r.getMessage()) for r in caplog.records)

    def test_an_upgraded_database_names_the_migrations_that_ran(self, db_dir, caplog):
        """The case that matters. An OLD database -- one missing a column this
        build adds -- must report exactly what was done to it."""

        async def make_old():
            conn = await database._get_db()
            # A minimal pre-`source` earnings table, as a database written by an
            # older build actually looks.
            await conn.executescript(
                """
                CREATE TABLE earnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    balance REAL NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    date TEXT NOT NULL,
                    created_at TEXT
                );
                """
            )
            await conn.commit()

        asyncio.run(make_old())
        with caplog.at_level(logging.INFO, logger="app.database"):
            asyncio.run(database.init_db())

        messages = [r.getMessage() for r in caplog.records]
        summary = next((m for m in messages if "Migrations applied this boot" in m), None)
        assert summary, messages
        assert "earnings.source" in summary, summary
        assert "earnings.fx_rate_usd" in summary, summary

    def test_the_upgrade_reports_the_version_it_came_from(self, db_dir, caplog):
        """ "was 0" on anything written before this existed, including a database
        that was otherwise fully up to date. Honest rather than alarming."""

        async def make_old():
            conn = await database._get_db()
            await conn.executescript("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT NOT NULL);")
            await conn.commit()

        asyncio.run(make_old())
        with caplog.at_level(logging.INFO, logger="app.database"):
            asyncio.run(database.init_db())
        messages = [r.getMessage() for r in caplog.records]
        assert any("(was 0)" in m for m in messages), messages


class TestTheVersionNeverGatesTheMigrations:
    """The design decision, enforced.

    A database claiming the current version but MISSING a column must still be
    repaired. Gating on the version would make that database unfixable, and the
    shapes that produce it -- an interrupted upgrade, a restored backup -- are
    exactly when repair matters most.
    """

    def test_a_column_is_added_even_when_the_version_already_says_current(self, db_dir):
        async def make_lying_db():
            conn = await database._get_db()
            await conn.executescript(
                """
                CREATE TABLE earnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    balance REAL NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    date TEXT NOT NULL,
                    created_at TEXT
                );
                """
            )
            await conn.execute(f"PRAGMA user_version = {database.SCHEMA_VERSION}")
            await conn.commit()

        asyncio.run(make_lying_db())
        asyncio.run(database.init_db())

        async def columns():
            conn = await database._get_db()
            cur = await conn.execute("PRAGMA table_info(earnings)")
            return {row["name"] for row in await cur.fetchall()}

        cols = asyncio.run(columns())
        assert "source" in cols, "the version gated the migration; a damaged database is unrepairable"
        assert "fx_rate_usd" in cols
