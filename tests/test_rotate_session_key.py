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
import re
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

    def test_the_data_folder_is_fsynced_after_the_replace(self, data_dir, monkeypatch, capsys):
        from app import users

        _make_db(data_dir)
        synced = []
        real_fsync = users.os.fsync

        def record(fd):
            st = os.fstat(fd)
            synced.append((stat.S_ISDIR(st.st_mode), st.st_ino))
            real_fsync(fd)

        monkeypatch.setattr(users.os, "fsync", record)
        assert _run(["rotate-session-key"]) == 0
        # The key file first, then the folder that holds the new directory entry.
        assert synced[-1] == (True, data_dir.stat().st_ino)
        assert any(not is_dir for is_dir, _ in synced[:-1])

    def test_a_failed_folder_fsync_still_reports_the_rotation(self, data_dir, monkeypatch, capsys):
        from app import users

        _make_db(data_dir)
        key_file = data_dir / ".secret_key"
        key_file.write_text(OLD_KEY)
        real_fsync = users.os.fsync

        def reject_dirs(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError(22, "Invalid argument")
            real_fsync(fd)

        monkeypatch.setattr(users.os, "fsync", reject_dirs)
        # The key is already in place once the folder fsync runs, so this is a
        # rotation that worked: say so, and give the restart step.
        assert _run(["rotate-session-key"]) == 0
        assert key_file.read_text() != OLD_KEY
        captured = capsys.readouterr()
        assert "Restart the UI container to sign out every browser" in captured.out
        assert "cannot write" not in captured.err
        assert "Invalid argument" in captured.err

    def test_as_root_the_key_file_is_handed_to_the_database_owner(self, data_dir, monkeypatch, capsys):
        # As non-root the file already has the right owner, so pretend to be
        # root and check the explicit chown names the database's owner.
        from app import users

        db = _make_db(data_dir)
        calls = []
        monkeypatch.setattr(users.os, "geteuid", lambda: 0)
        monkeypatch.setattr(users.os, "fchown", lambda fd, uid, gid: calls.append((uid, gid)))
        assert users._rotate_session_key(db) == 0
        assert calls == [(db.stat().st_uid, db.stat().st_gid)]

    def test_it_drops_to_the_database_owner_before_writing(self, data_dir, monkeypatch, capsys):
        # Run as root, the command must write as the app user, the same way the
        # other subcommands do. _drop_privileges itself is tested in
        # test_users_command.py.
        from app import users

        db = _make_db(data_dir)
        calls = []
        real_rotate = users._rotate_session_key
        monkeypatch.setattr(users, "_drop_privileges", lambda p: calls.append(("drop", p)))
        monkeypatch.setattr(users, "_rotate_session_key", lambda p: calls.append(("rotate", p)) or real_rotate(p))
        assert _run(["rotate-session-key"]) == 0
        assert calls == [("drop", db), ("rotate", db)]


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
        assert "no database at" in capsys.readouterr().err
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

    def test_the_placeholder_the_ui_shows_is_a_known_default(self):
        from app import users

        src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert '"changeme-generate-a-random-secret"' in src
        assert "changeme-generate-a-random-secret" in users.KNOWN_DEFAULT_SECRET_KEYS


def _faq_section(start: str, end: str) -> str:
    faq = (ROOT / "docs" / "faq.md").read_text(encoding="utf-8")
    section = faq[faq.index(start) :]
    return section[: section.index(end)]


class TestDocs:
    def test_the_faq_names_the_command_and_never_deletes_a_key_file(self):
        faq = (ROOT / "docs" / "faq.md").read_text(encoding="utf-8")
        # No -it: the command reads no input, and -it fails without a terminal.
        assert "docker exec cashpilot-ui python -m app.users rotate-session-key" in faq
        assert not re.search(r"\brm\b[^\n]*\.(secret|fernet)_key", faq)

    def test_the_compromise_steps_go_past_the_key(self):
        # A new key ends forged cookies, not an account the attacker added or
        # the credentials a lost /data copy decrypts.
        steps = _faq_section("**After a suspected compromise**", "**If the UI container does not start**")
        assert "python -m app.users list" in steps
        assert "provider accounts" in steps
        assert "docker run" in steps  # the env-key refusal needs docker exec

    def test_the_fallback_stays_about_reset(self):
        fallback = _faq_section("**If the UI container does not start**", "**What about security?**")
        assert "CASHPILOT_SECRET_KEY" not in fallback

    def test_restore_warns_that_an_old_backup_brings_the_old_key_back(self):
        doc = (ROOT / "docs" / "backup-restore.md").read_text(encoding="utf-8")
        restore = doc[doc.index("## Restore") :]
        restore = restore[: restore.index("### What the logs should say")]
        assert "rotate-session-key" in restore
        faq = _faq_section("**After a suspected compromise**", "**If the UI container does not start**")
        assert "restore a backup" in faq
