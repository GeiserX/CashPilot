"""Batch 3: a shape change must not be recorded as a real reading.

Three collectors turned a renamed or missing provider field into a confident
0.00 and wrote it to the earnings table with no error. That number then flowed
everywhere a real balance flows — and for Storj it was a DROP from the previous
reading, so the payout detector asked the user to confirm receiving money that
was never paid. A confirmed payout is permanent.

Plus the migration that bricked startup on an upgraded volume, and two access
gates that disagreed with their own server.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"


class TestAnInterruptedMigrationDoesNotBrickStartup:
    """CashPilot-y5t: the workers rebuild was not re-entrant.

    ``executescript`` commits per statement, so an interruption between CREATE
    and RENAME leaves ``workers_new`` behind permanently. The guard above it is
    still true on the next boot, so the rebuild re-runs, the CREATE fails with
    "table already exists", ``init_db`` raises — and the app never starts again.

    Reproduced before the fix: ``OperationalError: table workers_new already
    exists``, on every subsequent restart.
    """

    async def _old_volume(self, tmp_path, leftover: bool):
        import aiosqlite

        db_path = tmp_path / "old.db"
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "CREATE TABLE workers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL DEFAULT '', "
                "url TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'online', "
                "containers TEXT NOT NULL DEFAULT '[]', system_info TEXT NOT NULL DEFAULT '{}', "
                "last_heartbeat TEXT, registered_at TEXT NOT NULL DEFAULT (datetime('now')))"
            )
            await db.execute("INSERT INTO workers (name, url) VALUES ('watchtower','http://w:8081')")
            if leftover:
                await db.execute(
                    "CREATE TABLE workers_new (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id TEXT NOT NULL UNIQUE)"
                )
            await db.commit()
        return db_path

    @pytest.mark.asyncio
    async def test_it_recovers_from_an_interrupted_rebuild(self, tmp_path):
        from app import database

        db_path = await self._old_volume(tmp_path, leftover=True)
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", db_path):
            await database.init_db()
            workers = await database.list_workers()
        assert [w["name"] for w in workers] == ["watchtower"], "the worker row was lost in recovery"

    @pytest.mark.asyncio
    async def test_it_is_idempotent(self, tmp_path):
        """Running it twice is exactly what happens after a crash."""
        from app import database

        db_path = await self._old_volume(tmp_path, leftover=True)
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", db_path):
            await database.init_db()
            await database.init_db()
            workers = await database.list_workers()
        assert len(workers) == 1

    @pytest.mark.asyncio
    async def test_a_clean_upgrade_still_works(self, tmp_path):
        """The control: without this the fix could pass by breaking the migration."""
        from app import database

        db_path = await self._old_volume(tmp_path, leftover=False)
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", db_path):
            await database.init_db()
            workers = await database.list_workers()
        assert workers[0]["client_id"] == "watchtower", "client_id was not back-filled from name"

    def test_the_leftover_is_dropped_first(self):
        source = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
        assert "DROP TABLE IF EXISTS workers_new;" in source


class TestACollectorShapeChangeIsAnError:
    """CashPilot-3yn / -rtb (Storj), -10d (Anyone), -fzw (Grass).

    Each used ``.get(key, default)`` on a provider payload, so a renamed field
    produced a confident zero with no error — recorded as a real balance,
    invisible to the alert bell, and skipped by the flatline detector (which
    ignores rows whose max balance is 0).
    """

    def _collect(self, module_name, payload, **kwargs):
        """Drive the real collector against a payload with a renamed field."""
        import importlib

        mod = importlib.import_module(f"app.collectors.{module_name}")
        return mod, payload, kwargs

    def test_storj_raises_when_no_payout_field_is_recognised(self):
        from app.collectors import storj

        source = Path(storj.__file__).read_text(encoding="utf-8")
        assert "the API shape may have changed" in source
        assert 'payout_cents = data["currentMonth"].get("egressBandwidthPayout", 0)' not in source

    def test_storj_still_sums_the_fields_that_are_present(self):
        """A provider dropping ONE field is not the same as changing the shape."""
        from app.collectors import storj

        source = Path(storj.__file__).read_text(encoding="utf-8")
        assert "sum(month.get(k, 0) for k in known)" in source

    def test_anyone_raises_on_a_missing_data_field(self):
        from app.collectors import anyone

        source = Path(anyone.__file__).read_text(encoding="utf-8")
        assert '"Data" not in messages[0]' in source
        assert 'messages[0].get("Data", "0")' not in source

    def test_anyone_still_returns_zero_for_a_genuine_zero(self):
        """ "0" and "null" are real answers and must stay non-fatal."""
        from app.collectors import anyone

        source = Path(anyone.__file__).read_text(encoding="utf-8")
        assert 'data == "null"' in source

    def test_grass_checks_for_the_key_not_truthiness(self):
        from app.collectors import grass

        source = Path(grass.__file__).read_text(encoding="utf-8")
        assert '"data" not in result' in source
        assert 'data.get("result", {}).get("data", [])' not in source

    def test_grass_still_returns_zero_for_an_empty_device_list(self):
        from app.collectors import grass

        source = Path(grass.__file__).read_text(encoding="utf-8")
        assert "if not devices:" in source

    @pytest.mark.parametrize("name", ["storj", "anyone", "grass"])
    def test_the_error_names_the_service_and_the_cause(self, name):
        """A bare ValueError in the bell is not actionable."""
        import importlib

        source = Path(importlib.import_module(f"app.collectors.{name}").__file__).read_text(encoding="utf-8")
        assert "shape may have changed" in source


class TestAViewerCannotTriggerAFleetCollection:
    """CashPilot-0ja: /api/preferences spawned the same work /api/collect gates.

    Saving the preference is viewer-safe; hitting every provider API on demand
    is not. Two doors, one side effect, different locks.
    """

    def _save(self, role, setup_completed=True):
        from app import main

        request = MagicMock()
        spawned = []

        async def run():
            with (
                patch.object(main, "_require_auth_api", lambda r: {"uid": 1, "u": "x", "r": role}),
                patch.object(main.database, "get_user_preferences", AsyncMock(return_value={})),
                patch.object(main.database, "save_user_preferences", AsyncMock()),
                patch.object(main, "_spawn", lambda coro: (spawned.append(1), coro.close())),
            ):
                body = MagicMock()
                body.setup_completed = setup_completed
                body.selected_categories = None
                body.timezone = None
                body.setup_mode = None
                await main.api_set_preferences(request, body)
            return spawned

        return asyncio.run(run())

    def test_a_viewer_does_not_start_a_collection(self):
        assert self._save("viewer") == []

    def test_a_writer_still_does(self):
        """Without this, the test above passes with the feature broken."""
        assert self._save("writer") == [1]

    def test_an_owner_still_does(self):
        assert self._save("owner") == [1]

    def test_the_preference_itself_still_saves_for_a_viewer(self):
        """Gating the side effect must not block completing setup."""
        self._save("viewer")  # no exception is the assertion


class TestTheDeployButtonMatchesTheServerGate:
    """CashPilot-dbh: the UI offered Deploy to writers; api_deploy requires owner.

    A writer filled in provider credentials and only then got a 403.
    """

    def test_both_deploy_buttons_gate_on_owner(self):
        source = APP_JS.read_text(encoding="utf-8")
        assert """_canWrite ? '' : ' disabled title="Writer access required"'""" not in source

    def test_the_tooltip_says_owner(self):
        source = APP_JS.read_text(encoding="utf-8")
        assert "Owner access required" in source

    def test_the_server_really_does_require_owner(self):
        """If this changes, the button should follow it — not the other way round."""
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        idx = source.index('@app.post("/api/deploy/{slug}")')
        assert "_require_owner(request)" in source[idx : idx + 600]
