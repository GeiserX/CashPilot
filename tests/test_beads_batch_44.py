"""CashPilot-f62: a fresh install and an upgraded one had different schemas.

``CREATE TABLE config`` declared ``updated_at TEXT NOT NULL DEFAULT
(datetime('now'))``. The migration for existing volumes ran ``ALTER TABLE config
ADD COLUMN updated_at TEXT`` — nullable, no default — because SQLite cannot add
a NOT NULL column without one, and adding a default would BACK-FILL. The
migration refuses to back-fill for a good reason, recorded in its own comment:
doing so once stamped every stored credential with the moment of the upgrade, so
a Bytelixir session cookie that expires after two hours and had in fact expired
days earlier was reported as fresh.

So the constraint existed on fresh installs and was permanently absent on
upgraded ones. Nothing broke today — both writers set the value explicitly — but
the next writer to rely on the default would store NULL on upgraded volumes
ONLY, and ``get_config_updated_at`` filters ``WHERE updated_at IS NOT NULL``, so
those keys would quietly disappear from the credential-age report.

A bug that appears only on volumes older than some release is the hardest kind
to reproduce from a report, which is why this is worth closing while it is still
theoretical.

The upgraded shape is the correct one to converge on: NULL means "nobody
recorded when this was set", which is exactly what both consumers assume.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _columns(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return {
            row[1]: {"type": row[2], "notnull": row[3], "default": row[4]}
            for row in conn.execute("PRAGMA table_info(config)")
        }
    finally:
        conn.close()


def _fresh(tmp_path):
    """A database created the way a new install creates one."""
    import importlib

    from app import database as _database

    # The helper owns its directory: one test forgot to mkdir and failed with
    # "unable to open database file", which looks nothing like the schema
    # question being asked.
    tmp_path.mkdir(parents=True, exist_ok=True)
    database = importlib.reload(_database)
    database.DB_DIR = tmp_path
    database.DB_PATH = tmp_path / "fresh.db"
    asyncio.run(database.init_db())
    return tmp_path / "fresh.db"


def _upgraded(tmp_path):
    """A pre-1.4 volume, then migrated by init_db."""
    import importlib

    from app import database as _database

    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "upgraded.db"
    conn = sqlite3.connect(path)
    try:
        # The old shape: no updated_at at all.
        conn.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.commit()
    finally:
        conn.close()

    database = importlib.reload(_database)
    database.DB_DIR = tmp_path
    database.DB_PATH = path
    asyncio.run(database.init_db())
    return path


class TestBothInstallsGetTheSameSchema:
    def test_the_column_exists_on_both(self, tmp_path):
        assert "updated_at" in _columns(_fresh(tmp_path / "a"))
        assert "updated_at" in _columns(_upgraded(tmp_path / "b"))

    def test_the_constraints_match(self, tmp_path):
        fresh = _columns(_fresh(tmp_path / "a"))["updated_at"]
        upgraded = _columns(_upgraded(tmp_path / "b"))["updated_at"]
        assert fresh == upgraded, f"fresh {fresh} != upgraded {upgraded} — the drift is back"

    def test_it_is_nullable_on_both(self, tmp_path):
        """NULL means "nobody recorded when this was set", which both consumers assume."""
        assert _columns(_fresh(tmp_path / "a"))["updated_at"]["notnull"] == 0
        assert _columns(_upgraded(tmp_path / "b"))["updated_at"]["notnull"] == 0

    def test_neither_has_a_default(self, tmp_path):
        """A default is what would back-fill, and back-filling is the bug it
        would reintroduce: an unknown age rendered as the most favourable one."""
        assert _columns(_fresh(tmp_path / "a"))["updated_at"]["default"] is None
        assert _columns(_upgraded(tmp_path / "b"))["updated_at"]["default"] is None


class TestTheWritersStillStampTheValue:
    """The constraint is gone, so the writers are now the only thing setting it."""

    def test_both_writers_set_it_explicitly(self):
        source = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
        assert (
            source.count("INSERT OR REPLACE INTO config (key, value, updated_at) VALUES (?, ?, datetime('now'))") == 2
        )

    @pytest.mark.asyncio
    async def test_a_written_key_carries_a_timestamp(self, tmp_path):
        import importlib

        from app import database as _database

        database = importlib.reload(_database)
        database.DB_DIR = tmp_path
        database.DB_PATH = tmp_path / "w.db"
        await database.init_db()
        await database.set_config("power_currency", "EUR")
        stamps = await database.get_config_updated_at()
        assert stamps.get("power_currency"), "the writer stopped stamping and nothing else does now"

    @pytest.mark.asyncio
    async def test_an_unstamped_row_is_reported_as_unknown(self, tmp_path):
        """The pre-existing contract, which is why nullable is the right shape."""
        import importlib

        from app import database as _database

        database = importlib.reload(_database)
        database.DB_DIR = tmp_path
        database.DB_PATH = tmp_path / "u.db"
        await database.init_db()
        conn = sqlite3.connect(database.DB_PATH)
        try:
            conn.execute("INSERT INTO config (key, value, updated_at) VALUES ('legacy_key', 'v', NULL)")
            conn.commit()
        finally:
            conn.close()
        stamps = await database.get_config_updated_at()
        assert "legacy_key" not in stamps, "an unstamped key must not be reported with an age"


def test_the_migration_still_refuses_to_backfill():
    """The reason the two shapes have to converge on nullable at all."""
    source = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
    assert 'ALTER TABLE config ADD COLUMN updated_at TEXT"' in source
    assert "Deliberately NOT back-filled" in source
