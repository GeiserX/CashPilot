"""``python -m app.users rotate-session-key``: end forged sessions after a compromise.

A stolen ``.secret_key`` lets anyone mint an owner cookie with a fresh issue
time, which a password reset does not stop. Replacing the key does, once the UI
restarts. The command must refuse when the key comes from the environment, must
never write a partial key or touch ``.fernet_key``, and must not create a key
file next to a missing database.
"""

from __future__ import annotations

import ast
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OLD_KEY = "old-session-key-from-a-stolen-backup-000000000000000000000"


def _make_db(data_dir: Path) -> Path:
    from app import database

    db = data_dir / "cashpilot.db"
    conn = sqlite3.connect(db)
    conn.executescript(database._SCHEMA)
    conn.execute("INSERT INTO users (username, password, role, password_changed_at) VALUES ('alice', 'x', 'owner', 0)")
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("CASHPILOT_SECRET_KEY", raising=False)
    return tmp_path


def _run(argv):
    from app import users

    return users.main(argv)


class TestRotate:
    def test_writes_a_new_0600_key_that_differs(self, data_dir, capsys):
        _make_db(data_dir)
        key_file = data_dir / ".secret_key"
        key_file.write_text(OLD_KEY)
        assert _run(["rotate-session-key"]) == 0
        new = key_file.read_text()
        assert new and new != OLD_KEY
        assert len(new) >= 64  # token_urlsafe(48), the strength the app generates
        assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
        # Same owner as the database; no temp file left behind.
        db_st = (data_dir / "cashpilot.db").stat()
        assert (key_file.stat().st_uid, key_file.stat().st_gid) == (db_st.st_uid, db_st.st_gid)
        assert sorted(p.name for p in data_dir.iterdir() if p.name.startswith(".secret_key")) == [".secret_key"]

    def test_two_runs_give_two_different_keys(self, data_dir, capsys):
        _make_db(data_dir)
        assert _run(["rotate-session-key"]) == 0
        first = (data_dir / ".secret_key").read_text()
        assert _run(["rotate-session-key"]) == 0
        assert (data_dir / ".secret_key").read_text() != first

    def test_the_app_resolves_the_new_key(self, data_dir, capsys):
        from app import auth

        _make_db(data_dir)
        (data_dir / ".secret_key").write_text(OLD_KEY)
        assert auth._resolve_secret_key() == OLD_KEY
        assert _run(["rotate-session-key"]) == 0
        assert auth._resolve_secret_key() == (data_dir / ".secret_key").read_text()
        assert auth._resolve_secret_key() != OLD_KEY

    def test_a_cookie_signed_with_the_old_key_fails_under_the_new_one(self, data_dir, capsys):
        from itsdangerous import BadSignature, URLSafeTimedSerializer

        from app import auth

        _make_db(data_dir)
        (data_dir / ".secret_key").write_text(OLD_KEY)
        forged = URLSafeTimedSerializer(OLD_KEY).dumps({"uid": 1, "u": "alice", "r": "owner", "iat": 9e12})
        assert _run(["rotate-session-key"]) == 0
        with pytest.raises(BadSignature):
            URLSafeTimedSerializer(auth._resolve_secret_key()).loads(forged)

    def test_prints_the_restart_step_and_never_the_key(self, data_dir, capsys):
        _make_db(data_dir)
        assert _run(["rotate-session-key"]) == 0
        out = capsys.readouterr().out
        assert "Restart the UI container to sign out every browser" in out
        assert "docker restart <container> (cashpilot-ui in the stock compose file)." in out
        assert (data_dir / ".secret_key").read_text() not in out

    def test_never_touches_the_fernet_key(self, data_dir, capsys):
        _make_db(data_dir)
        fernet = data_dir / ".fernet_key"
        fernet.write_text("fernet-key-value")
        before = fernet.stat()
        assert _run(["rotate-session-key"]) == 0
        after = fernet.stat()
        assert fernet.read_text() == "fernet-key-value"
        assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)

    def test_a_failed_write_keeps_the_old_key_and_leaves_no_temp_file(self, data_dir, monkeypatch, capsys):
        from app import users

        _make_db(data_dir)
        key_file = data_dir / ".secret_key"
        key_file.write_text(OLD_KEY)

        def boom(fd):
            raise OSError("disk full")

        monkeypatch.setattr(users.os, "fsync", boom)
        assert _run(["rotate-session-key"]) == 1
        assert key_file.read_text() == OLD_KEY
        assert "disk full" in capsys.readouterr().err
        assert [p.name for p in data_dir.iterdir() if p.name.startswith(".secret_key")] == [".secret_key"]


class TestRefusals:
    def test_an_env_key_in_use_refuses_and_writes_nothing(self, data_dir, monkeypatch, capsys):
        _make_db(data_dir)
        key_file = data_dir / ".secret_key"
        key_file.write_text(OLD_KEY)
        mtime = key_file.stat().st_mtime_ns
        monkeypatch.setenv("CASHPILOT_SECRET_KEY", "a-real-key-set-in-the-environment")
        assert _run(["rotate-session-key"]) == 1
        err = capsys.readouterr().err
        assert "CASHPILOT_SECRET_KEY" in err and "environment" in err
        assert key_file.read_text() == OLD_KEY and key_file.stat().st_mtime_ns == mtime

    def test_an_env_key_with_no_key_file_refuses_and_creates_none(self, data_dir, monkeypatch, capsys):
        _make_db(data_dir)
        monkeypatch.setenv("CASHPILOT_SECRET_KEY", "a-real-key-set-in-the-environment")
        assert _run(["rotate-session-key"]) == 1
        assert not (data_dir / ".secret_key").exists()

    @pytest.mark.parametrize("placeholder", ["changeme", "changeme-generate-a-random-secret", ""])
    def test_an_env_placeholder_does_not_block(self, data_dir, monkeypatch, capsys, placeholder):
        from app import auth

        _make_db(data_dir)
        (data_dir / ".secret_key").write_text(OLD_KEY)
        monkeypatch.setenv("CASHPILOT_SECRET_KEY", placeholder)
        assert _run(["rotate-session-key"]) == 0
        new = (data_dir / ".secret_key").read_text()
        assert new != OLD_KEY
        # The app ignores the placeholder too, so it reads the rotated file.
        assert auth._resolve_secret_key() == new

    def test_a_missing_database_refuses_and_creates_nothing(self, data_dir, capsys):
        assert _run(["rotate-session-key"]) == 1
        assert "cashpilot.db" in capsys.readouterr().err
        assert list(data_dir.iterdir()) == []


class TestStandsAlone:
    def test_users_imports_no_app_module(self):
        tree = ast.parse((ROOT / "app" / "users.py").read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add(node.module or "")
        assert not {n for n in names if n == "app" or n.startswith("app.")}, names

    def test_a_run_loads_no_app_module_and_creates_no_fernet_key(self, tmp_path):
        _make_db(tmp_path)
        probe = (
            "import runpy, sys\n"
            "sys.argv = ['app.users', 'rotate-session-key']\n"
            "try:\n"
            "    runpy.run_module('app.users', run_name='__main__')\n"
            "except SystemExit as e:\n"
            "    assert not e.code, e.code\n"
            "print('LOADED', sorted(m for m in sys.modules if m.startswith('app.') and m != 'app.users'))\n"
        )
        env = {k: v for k, v in os.environ.items() if k != "CASHPILOT_SECRET_KEY"}
        env["CASHPILOT_DATA_DIR"] = str(tmp_path)
        res = subprocess.run(
            [sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60
        )
        assert res.returncode == 0, res.stderr
        assert "LOADED []" in res.stdout, res.stdout
        assert (tmp_path / ".secret_key").is_file()
        assert not (tmp_path / ".fernet_key").exists()


class TestNoDrift:
    def test_auth_uses_the_known_defaults_from_users(self):
        from app import auth, users

        assert auth._KNOWN_DEFAULTS is users.KNOWN_DEFAULT_SECRET_KEYS
        src = (ROOT / "app" / "auth.py").read_text(encoding="utf-8")
        assert '"changeme"' not in src, "app/auth.py restates the known-default keys"

    def test_the_placeholder_the_ui_shows_is_a_known_default(self):
        from app import users

        src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert '"changeme-generate-a-random-secret"' in src
        assert "changeme-generate-a-random-secret" in users.KNOWN_DEFAULT_SECRET_KEYS

    def test_auth_generates_keys_with_the_same_function(self):
        src = (ROOT / "app" / "auth.py").read_text(encoding="utf-8")
        assert "token_urlsafe" not in src, "app/auth.py generates its own session key"
        assert "_new_secret_key()" in src
