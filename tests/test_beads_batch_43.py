"""CashPilot-9mw: one ERROR per request when /fleet is not writable.

``app/auth.py`` calls ``resolve_fleet_key()`` on EVERY request carrying an
Authorization header — every worker heartbeat, every Home Assistant poll. On an
install whose ``/fleet`` volume is missing or not writable by uid 1000 (an
Unraid run with an explicit ``--user``, where entrypoint.sh skips the chown),
each of those calls re-ran ``mkdir`` + ``open`` and logged a fresh ERROR.

The log filled with the same line, burying the single one that explains it, and
every request paid two extra filesystem syscalls. Measured in the audit: five
curls took the "Cannot write fleet key" count from 1 to 6.

A successful resolution is now remembered. A FAILURE is not — the volume may be
fixed while the process runs, and a cached failure would keep rejecting workers
long after the cause was gone. Only the log is suppressed.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _clean_module_state(monkeypatch):
    """Each test starts with no cached resolution and no reported failure."""
    from app import fleet_key

    monkeypatch.setattr(fleet_key, "_resolved", None)
    monkeypatch.setattr(fleet_key, "_reported_failure", None)
    monkeypatch.delenv("CASHPILOT_API_KEY", raising=False)
    return fleet_key


class TestAnUnwritableVolumeIsReportedOnce:
    def _resolve_n(self, fleet_key, monkeypatch, tmp_path, caplog, times):
        unwritable = tmp_path / "fleet"
        monkeypatch.setattr(fleet_key, "_FLEET_KEY_DIR", unwritable)
        monkeypatch.setattr(fleet_key, "_FLEET_KEY_FILE", unwritable / ".fleet_key")

        def deny(*a, **k):
            raise OSError(30, "Read-only file system")

        monkeypatch.setattr(fleet_key.os, "open", deny)
        monkeypatch.setattr(Path, "mkdir", lambda *a, **k: None)
        with caplog.at_level(logging.ERROR, logger="app.fleet_key"):
            caplog.clear()
            for _ in range(times):
                fleet_key.resolve_fleet_key()
        return [r for r in caplog.records if "Cannot write fleet key" in r.getMessage()]

    def test_five_calls_log_once(self, _clean_module_state, monkeypatch, tmp_path, caplog):
        errors = self._resolve_n(_clean_module_state, monkeypatch, tmp_path, caplog, times=5)
        assert len(errors) == 1, f"the log still fills with one error per request: {len(errors)}"

    def test_it_is_still_reported_at_all(self, _clean_module_state, monkeypatch, tmp_path, caplog):
        """The control: suppressing it entirely would be worse than repeating."""
        errors = self._resolve_n(_clean_module_state, monkeypatch, tmp_path, caplog, times=1)
        assert len(errors) == 1

    def test_it_says_the_message_will_not_repeat(self, _clean_module_state, monkeypatch, tmp_path, caplog):
        """Otherwise the absence of further lines reads as the problem clearing."""
        errors = self._resolve_n(_clean_module_state, monkeypatch, tmp_path, caplog, times=1)
        assert "logged once" in errors[0].getMessage()

    def test_it_still_names_the_fix(self, _clean_module_state, monkeypatch, tmp_path, caplog):
        message = self._resolve_n(_clean_module_state, monkeypatch, tmp_path, caplog, times=1)[0].getMessage()
        assert "CASHPILOT_API_KEY" in message
        assert "chown 1000:0" in message

    def test_a_failure_is_never_cached_as_an_answer(self, _clean_module_state, monkeypatch, tmp_path, caplog):
        """The volume may be fixed while the process runs.

        Caching the empty string would keep rejecting every worker long after
        the cause was gone, which is worse than the noisy log this replaces.
        """
        fleet_key = _clean_module_state
        self._resolve_n(fleet_key, monkeypatch, tmp_path, caplog, times=3)
        assert fleet_key._resolved is None


class TestASuccessfulResolutionIsRemembered:
    def test_the_file_is_read_once(self, _clean_module_state, monkeypatch, tmp_path):
        fleet_key = _clean_module_state
        key_file = tmp_path / ".fleet_key"
        key_file.write_text("a-real-fleet-key")
        monkeypatch.setattr(fleet_key, "_FLEET_KEY_DIR", tmp_path)
        monkeypatch.setattr(fleet_key, "_FLEET_KEY_FILE", key_file)

        assert fleet_key.resolve_fleet_key() == "a-real-fleet-key"
        # Remove the file: a cached answer survives, a re-read would not.
        key_file.unlink()
        assert fleet_key.resolve_fleet_key() == "a-real-fleet-key"

    def test_the_cache_is_keyed_on_the_path(self, _clean_module_state, monkeypatch, tmp_path):
        """Two different files must not share one cached answer."""
        fleet_key = _clean_module_state
        first, second = tmp_path / "a", tmp_path / "b"
        first.mkdir()
        second.mkdir()
        (first / ".fleet_key").write_text("key-one")
        (second / ".fleet_key").write_text("key-two")

        monkeypatch.setattr(fleet_key, "_FLEET_KEY_DIR", first)
        monkeypatch.setattr(fleet_key, "_FLEET_KEY_FILE", first / ".fleet_key")
        assert fleet_key.resolve_fleet_key() == "key-one"

        monkeypatch.setattr(fleet_key, "_FLEET_KEY_DIR", second)
        monkeypatch.setattr(fleet_key, "_FLEET_KEY_FILE", second / ".fleet_key")
        assert fleet_key.resolve_fleet_key() == "key-two"

    def test_the_env_var_still_wins(self, _clean_module_state, monkeypatch, tmp_path):
        """The documented priority must survive the cache."""
        fleet_key = _clean_module_state
        key_file = tmp_path / ".fleet_key"
        key_file.write_text("from-file")
        monkeypatch.setattr(fleet_key, "_FLEET_KEY_FILE", key_file)
        monkeypatch.setenv("CASHPILOT_API_KEY", "from-env")
        assert fleet_key.resolve_fleet_key() == "from-env"

    def test_a_generated_key_is_remembered_too(self, _clean_module_state, monkeypatch, tmp_path):
        fleet_key = _clean_module_state
        monkeypatch.setattr(fleet_key, "_FLEET_KEY_DIR", tmp_path)
        monkeypatch.setattr(fleet_key, "_FLEET_KEY_FILE", tmp_path / ".fleet_key")
        generated = fleet_key.resolve_fleet_key()
        assert generated
        assert fleet_key._resolved == (tmp_path / ".fleet_key", generated)


def test_auth_still_calls_it_per_request():
    """The premise. If auth stopped calling it, the cache would be pointless —
    but so would the bug, so this records why the cache is where it is."""
    source = (Path(__file__).resolve().parents[1] / "app" / "auth.py").read_text(encoding="utf-8")
    assert "_fleet_key_mod.resolve_fleet_key()" in source
