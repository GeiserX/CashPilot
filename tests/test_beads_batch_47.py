"""CashPilot-cvr: the enrollment window never actually closed.

Per-worker fleet keys exist so that `CASHPILOT_API_KEY` — one shared secret
every worker is given — stops being enough to speak as any particular worker.
The cutover finalizes when a worker first heartbeats with its OWN key.

Until then the shared key is still honoured for that worker, so a dropped
enrollment response cannot lock it out. The docstring called that "a bounded
window that closes on the worker's first own-key heartbeat" — and for a worker
that CANNOT persist its key, that heartbeat never arrives. A pre-1.0.0 image, a
read-only /data, an ephemeral container: the window stayed open forever, the UI
re-sent the key to a shared-key holder every 60 seconds, and the only trace was
one log line a minute that nobody reads.

Measured before the fix: four consecutive heartbeats sending nothing but a name
and the shared key returned 200 each time, each with the same worker_key in the
body.

So the window is now bounded by TIME as well — a wall clock the worker cannot
influence, rather than an attempt count that just re-expresses the heartbeat
interval and breaks when that interval is configured differently.

Two things matter as much as the bound itself:

* **Absent is not expired.** A missing or unparseable issue time reads as still
  enrolling, and the migration backfills existing unconfirmed workers to NOW.
  Otherwise a patch release would lock out every mid-enrollment worker the
  moment it landed.
* **It is visible.** The fleet page marks such a worker "enrollment incomplete",
  and docs/upgrade-v1.md no longer claims an old worker "can no longer
  heartbeat" — that claim is exactly why nobody went looking.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest


def _stamp(**delta) -> str:
    """A key-issue timestamp in the format SQLite's datetime('now') writes."""
    return (datetime.now(UTC) - timedelta(**delta)).strftime("%Y-%m-%d %H:%M:%S")


class TestTheWindowIsBounded:
    def _state(self, issued_at, confirmed=False):
        from app.main import enrollment_state

        return enrollment_state(issued_at, confirmed)

    def test_a_freshly_issued_key_is_still_enrolling(self):
        assert self._state(_stamp(minutes=1)) == "pending"

    def test_a_key_issued_just_inside_the_window_is_still_enrolling(self):
        from app.main import WORKER_KEY_CONFIRM_WINDOW

        assert self._state(_stamp(seconds=WORKER_KEY_CONFIRM_WINDOW.total_seconds() - 60)) == "pending"

    def test_a_key_never_confirmed_past_the_window_is_incomplete(self):
        """The bead: this state used to be indistinguishable from enrolling."""
        from app.main import WORKER_KEY_CONFIRM_WINDOW

        assert self._state(_stamp(seconds=WORKER_KEY_CONFIRM_WINDOW.total_seconds() + 60)) == "incomplete"

    def test_a_confirmed_worker_is_confirmed_however_old_the_key_is(self):
        """Confirmation is permanent; a long-lived key is the normal case."""
        assert self._state(_stamp(days=400), confirmed=True) == "confirmed"

    def test_the_window_is_long_enough_to_survive_an_outage(self):
        """Minutes would cut off a worker that was merely rebooting."""
        from app.main import WORKER_KEY_CONFIRM_WINDOW

        assert timedelta(hours=1) <= WORKER_KEY_CONFIRM_WINDOW

    def test_the_window_is_not_effectively_unbounded(self):
        """The whole bead is that the shared key stayed valid forever."""
        from app.main import WORKER_KEY_CONFIRM_WINDOW

        assert timedelta(days=7) >= WORKER_KEY_CONFIRM_WINDOW


class TestUnknownIsNotExpired:
    """Reading absence as expiry would lock workers out on an upgrade."""

    def _state(self, issued_at):
        from app.main import enrollment_state

        return enrollment_state(issued_at, False)

    @pytest.mark.parametrize("value", [None, "", "not-a-timestamp", "2026-13-45 99:99:99"])
    def test_a_missing_or_unusable_timestamp_reads_as_still_enrolling(self, value):
        assert self._state(value) == "pending", f"{value!r} was treated as expired — nobody wrote that value"


class TestTheHeartbeatGuardEnforcesIt:
    """The state function is only useful if the auth path consults it."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from app.main import app

        # Built directly, NOT entered as a context manager: that would run the
        # app's lifespan, which calls catalog.register_sighup(), and signal
        # handlers cannot be installed off the main thread. The guards under
        # test are per-request, so no startup work is needed.
        return TestClient(app, raise_server_exceptions=False)

    @contextlib.contextmanager
    def _unconfirmed_worker(self, issued_at):
        """An enrolled-but-never-confirmed worker whose key was minted then."""
        with contextlib.ExitStack() as stack:
            for patcher in (
                patch("app.main.FLEET_API_KEY", "test-fleet-key"),
                patch(
                    "app.main.database.get_worker_key_state",
                    new_callable=AsyncMock,
                    return_value=("existing-key", False),
                ),
                patch("app.main.database.get_worker_key", new_callable=AsyncMock, return_value="existing-key"),
                patch(
                    "app.main.database.get_worker_key_issued_at",
                    new_callable=AsyncMock,
                    return_value=issued_at,
                ),
                patch("app.main.database.upsert_worker", new_callable=AsyncMock, return_value=1),
            ):
                stack.enter_context(patcher)
            yield

    @staticmethod
    def _heartbeat(client, token="test-fleet-key"):
        return client.post(
            "/api/workers/heartbeat",
            json={"name": "w", "client_id": "c1"},
            headers={"Authorization": f"Bearer {token}"},
        )

    def test_inside_the_window_the_shared_key_still_reissues(self, client):
        """A dropped enrollment response must not lock a worker out."""
        with self._unconfirmed_worker(_stamp(minutes=5)):
            resp = self._heartbeat(client)
        assert resp.status_code == 200
        assert resp.json().get("worker_key") == "existing-key"

    def test_past_the_window_the_shared_key_is_refused(self, client):
        """The measured symptom: 200 with the key in the body, forever."""
        with self._unconfirmed_worker(_stamp(days=30)):
            resp = self._heartbeat(client)
        assert resp.status_code == 401, "a shared-key holder can still speak as this worker indefinitely"

    def test_the_refusal_does_not_leak_the_key(self, client):
        """Refusing while still handing over the credential would fix nothing."""
        with self._unconfirmed_worker(_stamp(days=30)):
            resp = self._heartbeat(client)
        assert "existing-key" not in resp.text

    def test_the_refusal_says_how_to_recover(self, client):
        """A worker that goes offline with no explanation reads as a bug."""
        with self._unconfirmed_worker(_stamp(days=30)):
            resp = self._heartbeat(client)
        detail = resp.json()["detail"].lower()
        assert "/data" in detail and "remove" in detail

    def test_a_confirmed_worker_with_its_own_key_is_unaffected(self, client):
        """The steady state must not reach the window check at all."""
        with (
            patch("app.main.FLEET_API_KEY", "test-fleet-key"),
            patch(
                "app.main.database.get_worker_key_state",
                new_callable=AsyncMock,
                return_value=("own-key", True),
            ),
            patch("app.main.database.confirm_worker_key", new_callable=AsyncMock),
            patch("app.main.database.upsert_worker", new_callable=AsyncMock, return_value=1),
            patch(
                "app.main.database.get_worker_key_issued_at",
                new_callable=AsyncMock,
                side_effect=AssertionError("the steady-state path must not read the issue time"),
            ),
        ):
            resp = self._heartbeat(client, token="own-key")
        assert resp.status_code == 200

    def test_an_unenrolled_worker_can_still_enroll(self, client):
        """Nothing about this may block a genuinely new worker."""
        with (
            patch("app.main.FLEET_API_KEY", "test-fleet-key"),
            patch("app.main.database.get_worker_key_state", new_callable=AsyncMock, return_value=(None, False)),
            patch("app.main.database.set_worker_key", new_callable=AsyncMock),
            patch("app.main.database.upsert_worker", new_callable=AsyncMock, return_value=1),
        ):
            resp = self._heartbeat(client)
        assert resp.status_code == 200
        assert resp.json().get("worker_key")


class TestTheDatabaseRecordsWhenTheKeyWasIssued:
    @pytest.fixture
    def db(self, tmp_path, monkeypatch):
        import asyncio

        from app import database

        monkeypatch.setattr(database, "DB_DIR", tmp_path)
        monkeypatch.setattr(database, "DB_PATH", tmp_path / "cvr.db")
        asyncio.run(database.init_db())
        return database

    @pytest.mark.asyncio
    async def test_minting_a_key_stamps_the_time(self, db):
        await db.upsert_worker(client_id="c1", name="w", url="", containers="[]", apps="[]", system_info="{}")
        await db.set_worker_key("c1", "a-key")

        issued = await db.get_worker_key_issued_at("c1")
        assert issued, "nothing records when the key was minted, so no window can be bounded"
        parsed = datetime.fromisoformat(issued).replace(tzinfo=UTC)
        assert abs((datetime.now(UTC) - parsed).total_seconds()) < 120

    @pytest.mark.asyncio
    async def test_re_minting_restarts_the_window(self, db):
        """A worker removed and re-enrolled gets a fresh window, not an expired one."""
        from app.main import enrollment_state

        await db.upsert_worker(client_id="c1", name="w", url="", containers="[]", apps="[]", system_info="{}")
        await db.set_worker_key("c1", "first")
        await db.confirm_worker_key("c1")
        await db.set_worker_key("c1", "second")

        _key, confirmed = await db.get_worker_key_state("c1")
        assert confirmed is False, "re-minting must un-confirm, or the new key is trusted before it is used"
        assert enrollment_state(await db.get_worker_key_issued_at("c1"), confirmed) == "pending"

    @pytest.mark.asyncio
    async def test_an_unknown_worker_has_no_issue_time(self, db):
        assert await db.get_worker_key_issued_at("never-seen") is None

    @pytest.mark.asyncio
    async def test_the_existing_key_state_contract_is_unchanged(self, db):
        """Several callers and tests depend on the 2-tuple."""
        await db.upsert_worker(client_id="c1", name="w", url="", containers="[]", apps="[]", system_info="{}")
        await db.set_worker_key("c1", "a-key")
        assert await db.get_worker_key_state("c1") == ("a-key", False)


class TestTheMigrationDoesNotLockOutAFleet:
    """An upgrade must not cut off every worker that is mid-enrollment."""

    @pytest.mark.asyncio
    async def test_an_existing_unconfirmed_worker_is_backfilled_to_now(self, tmp_path, monkeypatch):
        import aiosqlite

        from app import database
        from app.main import enrollment_state

        monkeypatch.setattr(database, "DB_DIR", tmp_path)
        monkeypatch.setattr(database, "DB_PATH", tmp_path / "old.db")

        # A pre-migration database: the workers table without key_issued_at.
        async with aiosqlite.connect(tmp_path / "old.db") as conn:
            await conn.execute(
                "CREATE TABLE workers ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " client_id TEXT NOT NULL UNIQUE,"
                " name TEXT NOT NULL DEFAULT '',"
                " url TEXT NOT NULL DEFAULT '',"
                " status TEXT NOT NULL DEFAULT 'online',"
                " containers TEXT NOT NULL DEFAULT '[]',"
                " apps TEXT NOT NULL DEFAULT '[]',"
                " system_info TEXT NOT NULL DEFAULT '{}',"
                " last_heartbeat TEXT,"
                " api_key_enc TEXT,"
                " key_confirmed INTEGER NOT NULL DEFAULT 0,"
                " registered_at TEXT NOT NULL DEFAULT (datetime('now')))"
            )
            await conn.execute(
                "INSERT INTO workers (client_id, name, api_key_enc, key_confirmed) VALUES ('c1', 'w', 'enc:x', 0)"
            )
            await conn.commit()

        await database.init_db()

        issued = await database.get_worker_key_issued_at("c1")
        assert issued, "the migration left the issue time unset for an enrolled worker"
        assert enrollment_state(issued, False) == "pending", (
            "an upgrade would immediately refuse a worker that was mid-enrollment"
        )


class TestItIsVisibleAndDocumented:
    def test_the_api_publishes_the_enrollment_state(self):
        """A log line once a minute is not a way to tell anyone anything."""
        import ast
        import inspect
        import textwrap

        from app import main

        source = textwrap.dedent(inspect.getsource(main.api_list_workers))
        tree = ast.parse(source)
        assigned = {
            node.slice.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
        }
        assert "enrollment" in assigned
        calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert "enrollment_state" in calls, "the fleet page and the auth guard would judge this separately"

    def test_the_fleet_page_shows_it(self):
        from pathlib import Path

        html = (Path(__file__).resolve().parents[1] / "app" / "templates" / "fleet.html").read_text(encoding="utf-8")
        assert "w.enrollment === 'incomplete'" in html
        assert "enrollment incomplete" in html

    def test_the_badge_explains_the_cause_and_the_cure(self):
        """ "enrollment incomplete" alone tells an operator nothing to do."""
        from pathlib import Path

        html = (Path(__file__).resolve().parents[1] / "app" / "templates" / "fleet.html").read_text(encoding="utf-8")
        marker = html.index("enrollment incomplete")
        tooltip = html[max(0, marker - 900) : marker]
        assert "/data/.worker_key" in tooltip
        assert "shared" in tooltip.lower()

    def test_the_upgrade_doc_no_longer_claims_old_workers_cannot_heartbeat(self):
        """That claim is why nobody went looking for the worker still on the shared key."""
        from pathlib import Path

        doc = (Path(__file__).resolve().parents[1] / "docs" / "upgrade-v1.md").read_text(encoding="utf-8")
        assert "can no\n   longer heartbeat" not in doc
        assert "no longer heartbeat" not in doc

    def test_the_upgrade_doc_describes_what_really_happens(self):
        from pathlib import Path

        doc = (Path(__file__).resolve().parents[1] / "docs" / "upgrade-v1.md").read_text(encoding="utf-8")
        assert "enrollment incomplete" in doc
        assert "read-only" in doc
