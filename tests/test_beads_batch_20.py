"""CashPilot-4fy: an upgraded install kept its credentials in plaintext forever.

Reads are backward compatible — ``decrypt_value`` returns an unprefixed value
as-is — which is what makes an upgrade work at all, and also what left the
plaintext sitting in cashpilot.db indefinitely. Two users on identical code end
up with different at-rest protection for the same secret, and nothing tells the
upgraded one. A copied backup, a Duplicacy/Garage snapshot or a shared /data
directory hands over the live provider password.

Reproduced in the audit with the real key name: a volume written by v0.2.49
still held ``honeygain_password = SECRET-PASSWORD`` at rest after upgrading,
while a fresh install of the same credential stored ``enc:gAAAAAB...``.

The same applies to keys that only BECAME secret later: the suffix list was
widened after an audit found the at-rest boundary was a naming convention with
nothing enforcing it, and anything written before that widening is plaintext
under a key now recognised as a credential.
"""

from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest


@pytest.fixture
def db(tmp_path):
    """A real database module pointed at a throwaway file."""
    from app import database as _database

    database = importlib.reload(_database)
    database.DB_DIR = tmp_path
    database.DB_PATH = tmp_path / "cashpilot.db"
    return database


async def _raw(database, key):
    """What is actually on disk, bypassing every decrypt path."""
    conn = await database._get_db()
    try:
        cursor = await conn.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row["value"] if row else None
    finally:
        await conn.close()


async def _write_plaintext(database, key, value):
    """Exactly what an old version left behind: no enc: prefix."""
    conn = await database._get_db()
    try:
        await conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
        await conn.commit()
    finally:
        await conn.close()


class TestLegacyPlaintextIsEncryptedOnUpgrade:
    @pytest.mark.asyncio
    async def test_a_legacy_password_stops_being_readable_at_rest(self, db):
        await db.init_db()
        await _write_plaintext(db, "honeygain_password", "SECRET-PASSWORD")
        assert await _raw(db, "honeygain_password") == "SECRET-PASSWORD"

        await db.init_db()  # the upgrade restart

        at_rest = await _raw(db, "honeygain_password")
        assert at_rest.startswith("enc:"), "the provider password is still plaintext on disk"
        assert "SECRET-PASSWORD" not in at_rest

    @pytest.mark.asyncio
    async def test_the_value_still_reads_back_correctly(self, db):
        """Encrypting is only a fix if the credential still works afterwards."""
        await db.init_db()
        await _write_plaintext(db, "honeygain_password", "SECRET-PASSWORD")
        await db.init_db()
        assert (await db.get_config())["honeygain_password"] == "SECRET-PASSWORD"

    @pytest.mark.asyncio
    async def test_a_key_that_only_became_secret_later_is_covered(self, db):
        """The suffix list was widened; earlier writes are plaintext under it."""
        await db.init_db()
        await _write_plaintext(db, "bytelixir_session_cookie", "COOKIE-VALUE")
        await db.init_db()
        assert (await _raw(db, "bytelixir_session_cookie")).startswith("enc:")

    @pytest.mark.asyncio
    async def test_non_secret_config_is_left_exactly_alone(self, db):
        """The control. Encrypting everything would be a different bug.

        Non-secret values are read WITHOUT decryption, so encrypting one here
        would hand the caller an 'enc:...' string as though it were the setting.
        """
        await db.init_db()
        await _write_plaintext(db, "power_price_per_kwh", "0.30")
        await db.init_db()
        assert await _raw(db, "power_price_per_kwh") == "0.30"
        assert (await db.get_config())["power_price_per_kwh"] == "0.30"

    @pytest.mark.asyncio
    async def test_an_already_encrypted_value_is_not_double_encrypted(self, db):
        """Idempotent: this runs on EVERY startup, not once."""
        await db.init_db()
        await db.set_config("honeygain_password", "SECRET-PASSWORD")
        first = await _raw(db, "honeygain_password")
        await db.init_db()
        await db.init_db()
        assert await _raw(db, "honeygain_password") == first
        assert (await db.get_config())["honeygain_password"] == "SECRET-PASSWORD"

    @pytest.mark.asyncio
    async def test_an_empty_value_is_not_encrypted(self, db):
        """An empty string is not a credential; encrypting it invents one."""
        await db.init_db()
        await _write_plaintext(db, "honeygain_password", "")
        await db.init_db()
        assert await _raw(db, "honeygain_password") == ""


class TestItRefusesToRunUnderAnEphemeralKey:
    """The guard that keeps this from being worse than the problem.

    Encrypting with a key that vanishes on restart turns a readable credential
    into a permanently unrecoverable one. Plaintext is bad; silently destroying
    the user's provider passwords is worse.
    """

    @pytest.mark.asyncio
    async def test_nothing_is_encrypted_with_a_throwaway_key(self, db):
        await db.init_db()
        await _write_plaintext(db, "honeygain_password", "SECRET-PASSWORD")
        with patch.object(db, "_fernet_key_is_ephemeral", True):
            await db.init_db()
        assert await _raw(db, "honeygain_password") == "SECRET-PASSWORD", (
            "credentials were encrypted with a key that will not survive a restart"
        )

    @pytest.mark.asyncio
    async def test_it_says_why_it_skipped(self, db, caplog):
        import logging

        await db.init_db()
        await _write_plaintext(db, "honeygain_password", "SECRET-PASSWORD")
        with caplog.at_level(logging.WARNING), patch.object(db, "_fernet_key_is_ephemeral", True):
            caplog.clear()
            await db.init_db()
        assert any("ephemeral" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_it_does_run_with_a_persistent_key(self, db):
        """The control: the guard must not disable the fix everywhere."""
        await db.init_db()
        await _write_plaintext(db, "honeygain_password", "SECRET-PASSWORD")
        with patch.object(db, "_fernet_key_is_ephemeral", False):
            await db.init_db()
        assert (await _raw(db, "honeygain_password")).startswith("enc:")


class TestItDoesNotLogTheSecretsItMoves:
    @pytest.mark.asyncio
    async def test_the_value_never_reaches_the_log(self, db, caplog):
        """A migration that prints what it encrypted defeats itself."""
        import logging

        await db.init_db()
        await _write_plaintext(db, "honeygain_password", "SECRET-PASSWORD")
        with caplog.at_level(logging.DEBUG):
            caplog.clear()
            await db.init_db()
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert "SECRET-PASSWORD" not in joined

    @pytest.mark.asyncio
    async def test_the_key_name_does_reach_the_log(self, db, caplog):
        """The operator needs to know which credentials were touched."""
        import logging

        await db.init_db()
        await _write_plaintext(db, "honeygain_password", "SECRET-PASSWORD")
        with caplog.at_level(logging.INFO):
            caplog.clear()
            await db.init_db()
        assert any("honeygain_password" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_a_clean_install_logs_nothing_about_it(self, db, caplog):
        """The control: this must not announce itself on every ordinary boot."""
        import logging

        await db.init_db()
        with caplog.at_level(logging.INFO):
            caplog.clear()
            await db.init_db()
        assert not any("predated at-rest encryption" in r.getMessage() for r in caplog.records)
