"""Regression tests for durable session revocation (CashPilot-rqw).

Deleting or demoting a user must invalidate their outstanding session cookies in a
way that SURVIVES a UI restart. The bug: the revocation lived only in the in-memory
`auth._USER_PWD_EPOCH` cache, which resets to empty on restart, and startup warm-up
only restored password-change epochs — so after any restart a deleted/demoted user's
still-valid 30-day cookie was honored again with its old role.
"""

import asyncio
import os
from unittest.mock import patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest

from app import auth, database


@pytest.fixture
def db_dir(tmp_path):
    db_path = tmp_path / "cashpilot.db"
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", db_path),
    ):
        yield tmp_path


@pytest.fixture
def db(db_dir):
    asyncio.run(database.init_db())
    return db_dir


@pytest.fixture(autouse=True)
def _reset_epoch_cache():
    """The auth epoch cache is a module global; keep tests isolated."""
    auth._USER_PWD_EPOCH.clear()
    yield
    auth._USER_PWD_EPOCH.clear()


class TestSessionRevocationStore:
    def test_table_created(self, db):
        async def run():
            conn = await database._get_db()
            try:
                cur = await conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='session_revocations'"
                )
                assert await cur.fetchone() is not None
            finally:
                await conn.close()

        asyncio.run(run())

    def test_revoke_and_list(self, db):
        async def run():
            await database.revoke_user_sessions(7, 1000.0)
            rows = {r["user_id"]: r["revoked_before"] for r in await database.list_session_revocations()}
            assert rows[7] == 1000.0

        asyncio.run(run())

    def test_monotonic_never_lowers(self, db):
        async def run():
            await database.revoke_user_sessions(7, 5000.0)
            await database.revoke_user_sessions(7, 1000.0)  # older — must NOT lower
            rows = {r["user_id"]: r["revoked_before"] for r in await database.list_session_revocations()}
            assert rows[7] == 5000.0
            await database.revoke_user_sessions(7, 9000.0)  # newer — must raise
            rows = {r["user_id"]: r["revoked_before"] for r in await database.list_session_revocations()}
            assert rows[7] == 9000.0

        asyncio.run(run())

    def test_survives_user_deletion(self, db):
        """No FK to users: deleting the user row must not drop the revocation."""

        async def run():
            await database.revoke_user_sessions(42, 1234.0)
            await database.delete_user(42)  # DELETE FROM users — must not cascade
            uids = {r["user_id"] for r in await database.list_session_revocations()}
            assert 42 in uids

        asyncio.run(run())

    def test_prune_expired(self, db):
        """A revocation whose whole window has elapsed is pruned on the next write."""

        async def run():
            await database.revoke_user_sessions(1, 100.0)
            newer = 100.0 + database._SESSION_MAX_AGE_SECONDS + 10.0
            await database.revoke_user_sessions(2, newer)
            uids = {r["user_id"] for r in await database.list_session_revocations()}
            assert 1 not in uids  # fully elapsed -> pruned (its tokens already expired)
            assert 2 in uids

        asyncio.run(run())


class TestWarmRestore:
    """The core fix: revocations are restored into the epoch cache at startup."""

    def test_revocation_restored_after_restart(self, db):
        import time as _time

        from app import main

        async def run():
            uid = 7
            # Use real-wall-clock-relative timestamps: patching auth.time.time also
            # moves itsdangerous's own signature clock, so a token stamped far from
            # real "now" would read as expired at decode time regardless of the epoch.
            now = _time.time()
            revoke_at = now - 1000.0  # a delete/demote happened 1000s ago
            await database.revoke_user_sessions(uid, revoke_at)

            # Simulate a UI restart: the in-memory cache starts empty.
            auth._USER_PWD_EPOCH.clear()
            assert auth._user_pwd_epoch(uid) == 0.0

            # Startup warm-up must restore it from the durable table.
            await main._warm_session_epochs()
            assert auth._user_pwd_epoch(uid) == revoke_at

            # A cookie issued BEFORE the revocation is rejected across the restart
            # (by the epoch, not by expiry — its signature age is only ~2000s)...
            with patch.object(auth.time, "time", return_value=now - 2000.0):
                stale = auth.create_session_token(uid, "bob", "owner")
            assert auth.decode_session_token(stale) is None

            # ...while a fresh cookie (re-login after demotion) is accepted with its new role.
            fresh = auth.create_session_token(uid, "bob", "viewer")
            decoded = auth.decode_session_token(fresh)
            assert decoded is not None
            assert decoded["r"] == "viewer"

        asyncio.run(run())

    def test_warm_restore_merges_password_and_revocation(self, db):
        """Warm-up takes the later of password_changed_at and revoked_before per user."""
        from app import main

        async def run():
            uid = await database.create_user("alice", auth.hash_password("pw-000000"), "owner")
            # Password changed at t=2000 (persisted on the users row)...
            await database.update_user_password(uid, auth.hash_password("pw-111111"))
            # ...then a later revocation at a much higher timestamp.
            await database.revoke_user_sessions(uid, 9_000_000_000.0)

            auth._USER_PWD_EPOCH.clear()
            await main._warm_session_epochs()
            # The revocation is later, so it wins.
            assert auth._user_pwd_epoch(uid) == 9_000_000_000.0

        asyncio.run(run())
