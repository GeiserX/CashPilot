"""CashPilot-dpe: the recovery message named the wrong variable.

Restore /data without .fernet_key, or set a different CASHPILOT_ENCRYPTION_KEY,
and every enrolled worker's per-worker key becomes undecryptable. The UI logged
two contradictory lines back to back:

    ... the credential-encryption key (CASHPILOT_ENCRYPTION_KEY / .../.fernet_key)
    ... This is NOT ... CASHPILOT_SECRET_KEY

    Worker 'abc123' per-worker key is undecryptable (CASHPILOT_SECRET_KEY
    changed?) -- treating as unenrolled so it can re-enroll via the shared key

The second names the variable the first has just ruled out. CASHPILOT_SECRET_KEY
signs sessions and has nothing to do with decrypting a stored key, so an
operator whose whole fleet had gone offline was sent after the wrong setting.

The re-enrolment claim was also untrue when written: the worker keeps sending
the key it persisted. CashPilot-u10 has since made it self-heal after a bounded
run of rejections, so it is now true — but only eventually, and the message said
nothing about the wait or about the one-step manual fix.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest


async def _log_for_undecryptable_key(caplog):
    """Drive get_worker_key_state with a value decrypt_value cannot read."""
    from app import database

    class _Row(dict):
        def __getitem__(self, key):
            return dict.__getitem__(self, key)

    row = _Row({"api_key_enc": "enc:not-a-real-token", "key_confirmed": 1})

    class _Cursor:
        async def fetchone(self):
            return row

    class _DB:
        async def execute(self, *a, **k):
            return _Cursor()

        async def close(self):
            return None

    with (
        patch.object(database, "_get_db", AsyncMock(return_value=_DB())),
        patch.object(database, "decrypt_value", lambda v: ""),
        caplog.at_level(logging.ERROR, logger="app.database"),
    ):
        caplog.clear()
        result = await database.get_worker_key_state("abc123")
    return result, [r.getMessage() for r in caplog.records]


class TestTheMessageNamesTheKeyThatActuallyMatters:
    @pytest.mark.asyncio
    async def test_it_no_longer_blames_the_session_key(self, caplog):
        _, messages = await _log_for_undecryptable_key(caplog)
        joined = " ".join(messages)
        assert "CASHPILOT_SECRET_KEY changed" not in joined, "still pointing at the session-signing key"

    @pytest.mark.asyncio
    async def test_it_names_the_encryption_key(self, caplog):
        _, messages = await _log_for_undecryptable_key(caplog)
        assert any("CASHPILOT_ENCRYPTION_KEY" in m for m in messages)

    @pytest.mark.asyncio
    async def test_it_says_which_key_it_is_not(self, caplog):
        """The two are confused often enough that the codebase says so elsewhere."""
        _, messages = await _log_for_undecryptable_key(caplog)
        assert any("NOT CASHPILOT_SECRET_KEY" in m for m in messages)

    @pytest.mark.asyncio
    async def test_it_names_the_key_file(self, caplog):
        _, messages = await _log_for_undecryptable_key(caplog)
        assert any(".fernet_key" in m for m in messages)


class TestItDescribesWhatWillActuallyHappen:
    @pytest.mark.asyncio
    async def test_it_does_not_promise_immediate_re_enrolment(self, caplog):
        _, messages = await _log_for_undecryptable_key(caplog)
        joined = " ".join(messages)
        assert "so it can re-enroll via the shared key" not in joined

    @pytest.mark.asyncio
    async def test_it_warns_that_401s_come_first(self, caplog):
        """The operator watches a fleet go offline; silence about it reads as a bug."""
        _, messages = await _log_for_undecryptable_key(caplog)
        assert any("401" in m for m in messages)

    @pytest.mark.asyncio
    async def test_it_gives_the_one_step_manual_fix(self, caplog):
        _, messages = await _log_for_undecryptable_key(caplog)
        joined = " ".join(messages)
        assert "/data/.worker_key" in joined

    @pytest.mark.asyncio
    async def test_it_says_how_to_recover_the_credentials_themselves(self, caplog):
        """Deleting the worker key fixes the fleet, not the stored credentials."""
        _, messages = await _log_for_undecryptable_key(caplog)
        assert any("Restore the original key" in m for m in messages)

    @pytest.mark.asyncio
    async def test_the_behaviour_itself_is_unchanged(self, caplog):
        """Still reported as unenrolled — only the words changed."""
        result, _ = await _log_for_undecryptable_key(caplog)
        assert result == (None, False)


class TestTheNumberInTheMessageCannotDrift:
    """A message quoting "roughly N heartbeats" must track the real threshold."""

    def test_the_two_constants_agree(self):
        from app import database, worker_api

        assert database._WORKER_KEY_DISCARD_AFTER == worker_api._AUTH_FAILURE_DISCARD_AFTER

    def test_the_worker_really_discards_after_that_many(self):
        """The claim in the message is about worker behaviour, so check it there."""
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "app" / "worker_api.py").read_text(encoding="utf-8")
        assert "_consecutive_auth_failures >= _AUTH_FAILURE_DISCARD_AFTER" in source
        assert "_discard_worker_key(" in source
