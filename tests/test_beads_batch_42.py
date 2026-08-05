"""CashPilot-65s: the lockout alarm skipped the lockout it was most needed for.

The alarm was gated on ``if status == 401 and _worker_key:``. A worker that LOST
``/data/.worker_key`` — a partial restore, an appdata copy that skips dotfiles —
holds no key. It sends the shared ``CASHPILOT_API_KEY``, the UI refuses it
because its row for that client_id is enrolled and confirmed, and the worker
falls into the ``else`` branch that RESETS the counter. So it 401'd forever and
logged nothing but a generic "Heartbeat failed" every 60 seconds, while its
service containers kept earning and nothing else surfaced the problem.

The alarm that did fire named the wrong fix. It told the operator to write a
client_id into ``/data/.worker_id``, which is the fix for neither lockout that
actually happens — the row was removed, or the stored key can no longer be
decrypted, and in both the id is fine and it is the KEY that has to change. It
also named an id the dashboard has never displayed.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    import httpx

    import app.worker_api as w
except ImportError:  # pragma: no cover - CI always has these
    pytest.skip("requires the app dependencies", allow_module_level=True)


def _alarms(*, holds_key, count, caplog, tmp_path):
    """Drive N consecutive 401 heartbeats and return the ERROR records."""
    key_file = tmp_path / ".worker_key"
    if holds_key:
        key_file.write_text("own")
    saved = w._worker_key
    w._worker_key = "own" if holds_key else None
    w._consecutive_auth_failures = 0
    try:
        with caplog.at_level(logging.ERROR, logger="app.worker_api"):
            caplog.clear()
            for _ in range(count):
                request = httpx.Request("POST", "http://ui:8080/api/workers/heartbeat")
                response = httpx.Response(401, request=request, json={})
                client = MagicMock()
                client.__aenter__ = AsyncMock(return_value=client)
                client.__aexit__ = AsyncMock(return_value=False)
                client.post = AsyncMock(return_value=response)
                with (
                    patch.object(w, "_WORKER_KEY_FILE", key_file),
                    patch.object(w, "UI_URL", "http://ui:8080"),
                    patch("app.worker_api.orchestrator.get_status", return_value=[]),
                    patch("app.worker_api.orchestrator.docker_available", return_value=True),
                    patch("app.worker_api.httpx.AsyncClient", return_value=client),
                ):
                    asyncio.run(w._send_heartbeat())
        return [r.getMessage() for r in caplog.records]
    finally:
        w._worker_key = saved
        w._consecutive_auth_failures = 0


class TestAWorkerWithNoKeyIsAlsoTold:
    def test_it_alarms(self, caplog, tmp_path):
        messages = _alarms(holds_key=False, count=w._AUTH_FAILURE_ALARM_AFTER, caplog=caplog, tmp_path=tmp_path)
        assert any("Rejected" in m for m in messages), (
            "a worker that lost its key file still 401s in silence — the case the alarm exists for"
        )

    def test_it_names_the_missing_file(self, caplog, tmp_path):
        messages = _alarms(holds_key=False, count=w._AUTH_FAILURE_ALARM_AFTER, caplog=caplog, tmp_path=tmp_path)
        joined = " ".join(messages)
        assert str(w._WORKER_KEY_FILE) in joined or ".worker_key" in joined

    def test_it_gives_the_recovery(self, caplog, tmp_path):
        """Restore the file, or remove the worker so it enrols again."""
        joined = " ".join(_alarms(holds_key=False, count=w._AUTH_FAILURE_ALARM_AFTER, caplog=caplog, tmp_path=tmp_path))
        assert "remove this worker in the fleet dashboard" in joined

    def test_it_says_which_key_was_refused(self, caplog, tmp_path):
        joined = " ".join(_alarms(holds_key=False, count=w._AUTH_FAILURE_ALARM_AFTER, caplog=caplog, tmp_path=tmp_path))
        assert "CASHPILOT_API_KEY" in joined

    def test_it_stays_quiet_below_the_threshold(self, caplog, tmp_path):
        """The control: two 401s across a restart are ordinary."""
        messages = _alarms(holds_key=False, count=w._AUTH_FAILURE_ALARM_AFTER - 1, caplog=caplog, tmp_path=tmp_path)
        assert not [m for m in messages if "Rejected" in m]


class TestTheAdviceMatchesTheLockout:
    def test_a_worker_holding_a_key_is_told_to_discard_it(self, caplog, tmp_path):
        joined = " ".join(_alarms(holds_key=True, count=w._AUTH_FAILURE_ALARM_AFTER, caplog=caplog, tmp_path=tmp_path))
        assert "re-enrol" in joined
        # The harness patches _WORKER_KEY_FILE to a tmp path, so the message
        # carries THAT path — comparing against the module constant would be
        # comparing against a value the code under test never saw.
        assert ".worker_key" in joined

    def test_neither_message_tells_anyone_to_edit_the_id_file(self, caplog, tmp_path):
        """The id is fine in both real lockouts; editing it fixes neither."""
        for holds in (True, False):
            joined = " ".join(
                _alarms(holds_key=holds, count=w._AUTH_FAILURE_ALARM_AFTER, caplog=caplog, tmp_path=tmp_path)
            )
            assert str(w._WORKER_ID_FILE) not in joined, f"the id file is still named (holds_key={holds})"

    def test_the_two_messages_are_different(self, caplog, tmp_path):
        """One fix for two different situations is how the old one went wrong."""
        with_key = " ".join(
            _alarms(holds_key=True, count=w._AUTH_FAILURE_ALARM_AFTER, caplog=caplog, tmp_path=tmp_path)
        )
        without = " ".join(
            _alarms(holds_key=False, count=w._AUTH_FAILURE_ALARM_AFTER, caplog=caplog, tmp_path=tmp_path)
        )
        assert with_key != without

    def test_the_self_heal_still_only_applies_when_there_is_a_key_to_discard(self):
        """A keyless worker has nothing to discard; discarding must not fire."""
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "app" / "worker_api.py").read_text(encoding="utf-8")
        assert "elif _worker_key and _consecutive_auth_failures >= _AUTH_FAILURE_DISCARD_AFTER:" in source
