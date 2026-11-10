"""The account recovery command: ``python -m app.users`` (issue #721).

A locked-out owner runs it in the UI container's console. It must work on its
own: no ``app.*`` imports (they create key files), the database path resolved
the same way the app resolves it, a privilege drop to the owner of the database
file, and a refusal on an empty users table.
"""

from __future__ import annotations

import ast
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import bcrypt
import pytest

ROOT = Path(__file__).resolve().parents[1]
USERS_PY = ROOT / "app" / "users.py"


def _make_db(data_dir: Path, users: list[tuple[str, str]]) -> Path:
    """Create a database with the app's real schema and the given (name, role) users."""
    from app import database

    db = data_dir / "cashpilot.db"
    conn = sqlite3.connect(db)
    conn.executescript(database._SCHEMA)
    for name, role in users:
        conn.execute(
            "INSERT INTO users (username, password, role, password_changed_at) VALUES (?, ?, ?, 0)",
            (name, "x", role),
        )
    conn.commit()
    conn.close()
    return db


def _row(db: Path, name: str):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM users WHERE username = ?", (name,)).fetchone()
    finally:
        conn.close()


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHPILOT_DATA_DIR", str(tmp_path))
    return tmp_path


def _run(argv):
    from app import users

    return users.main(argv)


class TestList:
    def test_prints_id_name_and_role_never_the_hash(self, data_dir, capsys):
        _make_db(data_dir, [("alice", "owner"), ("bob", "viewer")])
        assert _run(["list"]) == 0
        out = capsys.readouterr().out
        assert "alice" in out and "owner" in out and "bob" in out and "viewer" in out
        assert "$2b$" not in out and " x\n" not in out


class TestResetPassword:
    def test_picks_the_lone_owner(self, data_dir, capsys):
        db = _make_db(data_dir, [("alice", "owner"), ("bob", "viewer")])
        before = time.time()
        assert _run(["reset-password"]) == 0
        out = capsys.readouterr().out
        row = _row(db, "alice")
        new = re.search(r"New password for alice: (\S+)", out).group(1)
        assert bcrypt.checkpw(new.encode(), row["password"].encode())
        assert row["password_changed_at"] >= before
        # The viewer is untouched.
        assert _row(db, "bob")["password"] == "x"

    def test_the_hash_verifies_with_the_apps_own_check(self, data_dir, capsys):
        from app import auth

        db = _make_db(data_dir, [("alice", "owner")])
        assert _run(["reset-password", "alice"]) == 0
        new = re.search(r"New password for alice: (\S+)", capsys.readouterr().out).group(1)
        assert auth.verify_password(new, _row(db, "alice")["password"])

    def test_prints_the_sign_in_and_restart_hints(self, data_dir, capsys):
        _make_db(data_dir, [("alice", "owner")])
        assert _run(["reset-password"]) == 0
        out = capsys.readouterr().out
        assert "Sign in, then change it from the avatar menu" in out
        assert "Restart the UI container to sign out browsers that were logged in as alice" in out
        assert "docker restart" in out

    def test_a_named_user_is_reset(self, data_dir, capsys):
        db = _make_db(data_dir, [("alice", "owner"), ("bob", "viewer")])
        assert _run(["reset-password", "bob"]) == 0
        new = re.search(r"New password for bob: (\S+)", capsys.readouterr().out).group(1)
        assert bcrypt.checkpw(new.encode(), _row(db, "bob")["password"].encode())
        assert _row(db, "alice")["password"] == "x"

    def test_two_owners_and_no_name_prints_the_list_and_fails(self, data_dir, capsys):
        db = _make_db(data_dir, [("alice", "owner"), ("carol", "owner")])
        assert _run(["reset-password"]) != 0
        cap = capsys.readouterr()
        assert "alice" in cap.out + cap.err and "carol" in cap.out + cap.err
        assert _row(db, "alice")["password"] == "x" and _row(db, "carol")["password"] == "x"

    def test_an_unknown_name_prints_the_list_and_fails(self, data_dir, capsys):
        db = _make_db(data_dir, [("alice", "owner")])
        assert _run(["reset-password", "Alice"]) != 0  # names are case-sensitive
        cap = capsys.readouterr()
        assert "alice" in cap.out + cap.err
        assert _row(db, "alice")["password"] == "x"

    def test_refuses_an_empty_users_table(self, data_dir, capsys):
        _make_db(data_dir, [])
        assert _run(["reset-password"]) != 0
        err = capsys.readouterr().err
        assert "No users exist. Restart the container and use the setup token from its log." in err

    def test_a_missing_database_is_an_error_and_is_not_created(self, data_dir, capsys):
        assert _run(["reset-password"]) != 0
        assert not (data_dir / "cashpilot.db").exists()
        assert "cashpilot.db" in capsys.readouterr().err


class TestRename:
    def test_renames(self, data_dir, capsys):
        db = _make_db(data_dir, [("alice", "owner")])
        assert _run(["rename", "alice", "alice_2"]) == 0
        assert _row(db, "alice") is None
        assert _row(db, "alice_2")["role"] == "owner"

    @pytest.mark.parametrize("bad", ["ab", "a" * 33, "has space", "bad!", "abc\n"])
    def test_applies_the_registration_rule(self, data_dir, capsys, bad):
        db = _make_db(data_dir, [("alice", "owner")])
        assert _run(["rename", "alice", bad]) != 0
        assert _row(db, "alice") is not None

    def test_a_clash_is_a_clear_error(self, data_dir, capsys):
        db = _make_db(data_dir, [("alice", "owner"), ("bob", "viewer")])
        assert _run(["rename", "alice", "bob"]) != 0
        assert "bob" in capsys.readouterr().err
        assert _row(db, "alice")["role"] == "owner"

    def test_an_unknown_old_name_is_a_clear_error(self, data_dir, capsys):
        _make_db(data_dir, [("alice", "owner")])
        assert _run(["rename", "nobody", "someone"]) != 0
        assert "nobody" in capsys.readouterr().err

    def test_registration_uses_the_same_constant(self):
        from app import users
        from app.routers import auth as auth_router

        src = (ROOT / "app" / "routers" / "auth.py").read_text(encoding="utf-8")
        assert "USERNAME_PATTERN" in src
        assert "[a-zA-Z0-9_-]{3,32}" not in src, "registration restates the username rule"
        assert auth_router.USERNAME_PATTERN is users.USERNAME_PATTERN


class TestStandsAlone:
    def test_imports_no_app_module(self):
        tree = ast.parse(USERS_PY.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add(node.module or "")
        assert not {n for n in names if n == "app" or n.startswith("app.")}, names

    def test_a_run_creates_no_key_file_and_loads_no_app_module(self, tmp_path):
        _make_db(tmp_path, [("alice", "owner")])
        probe = (
            "import runpy, sys\n"
            "sys.argv = ['app.users', 'reset-password']\n"
            "try:\n"
            "    runpy.run_module('app.users', run_name='__main__')\n"
            "except SystemExit as e:\n"
            "    assert not e.code, e.code\n"
            "print('LOADED', sorted(m for m in sys.modules if m.startswith('app.') and m != 'app.users'))\n"
        )
        env = {**os.environ, "CASHPILOT_DATA_DIR": str(tmp_path)}
        res = subprocess.run(
            [sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60
        )
        assert res.returncode == 0, res.stderr
        assert "LOADED []" in res.stdout, res.stdout
        assert not (tmp_path / ".fernet_key").exists()
        assert not (tmp_path / ".secret_key").exists()

    def test_resolves_the_database_path_as_the_app_does(self, tmp_path):
        """Both modules read CASHPILOT_DATA_DIR, with the same default."""
        probe = "from app import users, database\nprint(users.db_path() == database.DB_PATH, users.db_path())\n"
        env = {**os.environ, "CASHPILOT_DATA_DIR": str(tmp_path)}
        res = subprocess.run(
            [sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60
        )
        assert res.returncode == 0, res.stderr
        assert res.stdout.startswith("True "), res.stdout
        # The default, read from source: importing app.database with /data unset is not safe here.
        db_src = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
        assert 'Path(os.getenv("CASHPILOT_DATA_DIR", "/data"))' in db_src
        from app import users

        assert users.DEFAULT_DATA_DIR == "/data"


def _fake_owner(monkeypatch, users, uid, gid):
    """Make the database file look owned by uid:gid to the command."""
    real_stat = os.stat

    def fake_stat(p, *a, **k):
        st = real_stat(p, *a, **k)
        return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, uid, gid, *tuple(st)[6:10]))

    monkeypatch.setattr(users.os, "stat", fake_stat)


class TestPrivilegeDrop:
    def test_root_drops_to_the_owner_of_the_database_file(self, data_dir, monkeypatch, capsys):
        from app import users

        _make_db(data_dir, [("alice", "owner")])
        calls = []
        monkeypatch.setattr(users.os, "geteuid", lambda: 0)
        _fake_owner(monkeypatch, users, 1000, 0)
        monkeypatch.setattr(users.os, "setgroups", lambda g: calls.append(("setgroups", tuple(g))), raising=False)
        monkeypatch.setattr(users.os, "setgid", lambda g: calls.append(("setgid", g)))
        monkeypatch.setattr(users.os, "setuid", lambda u: calls.append(("setuid", u)))
        assert users.main(["list"]) == 0
        assert calls == [("setgroups", ()), ("setgid", 0), ("setuid", 1000)]

    def test_a_root_owned_database_keeps_root(self, data_dir, monkeypatch, capsys):
        from app import users

        _make_db(data_dir, [("alice", "owner")])
        calls = []
        monkeypatch.setattr(users.os, "geteuid", lambda: 0)
        _fake_owner(monkeypatch, users, 0, 0)
        monkeypatch.setattr(users.os, "setgroups", lambda g: calls.append("setgroups"), raising=False)
        monkeypatch.setattr(users.os, "setgid", lambda g: calls.append("setgid"))
        monkeypatch.setattr(users.os, "setuid", lambda u: calls.append("setuid"))
        assert users.main(["list"]) == 0
        assert calls == []

    def test_a_refused_drop_is_a_clear_error_not_a_traceback(self, data_dir, monkeypatch, capsys):
        from app import users

        _make_db(data_dir, [("alice", "owner")])
        monkeypatch.setattr(users.os, "geteuid", lambda: 0)
        _fake_owner(monkeypatch, users, 1000, 1000)
        monkeypatch.setattr(users.os, "setgroups", lambda g: None, raising=False)

        def refuse(_gid):
            raise PermissionError(1, "Operation not permitted")

        monkeypatch.setattr(users.os, "setgid", refuse)
        assert users.main(["list"]) == 1
        assert "error: cannot open" in capsys.readouterr().err

    def test_non_root_does_not_try(self, data_dir, monkeypatch, capsys):
        from app import users

        _make_db(data_dir, [("alice", "owner")])
        monkeypatch.setattr(users.os, "geteuid", lambda: 1000)
        monkeypatch.setattr(users.os, "setuid", lambda u: pytest.fail("setuid called"))
        assert users.main(["list"]) == 0

    @pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() != 0, reason="needs root")
    def test_as_root_the_command_runs_as_the_database_owner(self):
        """SQLite already hands a new -wal file to the database owner when run as
        root, so the file owner alone cannot show the drop. Check the ids too."""
        import tempfile

        # Under /tmp, so the dropped user can reach it; pytest's tmp_path is 0700.
        tmp_path = Path(tempfile.mkdtemp(dir="/tmp"))
        os.chmod(tmp_path, 0o777)
        db = _make_db(tmp_path, [("alice", "owner")])
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.close()
        os.chown(db, 4321, 4322)
        env = {**os.environ, "CASHPILOT_DATA_DIR": str(tmp_path)}
        probe = (
            "import os\n"
            "from app import users\n"
            "users._drop_privileges(users.db_path())\n"
            "c = users._connect(users.db_path())\n"
            "c.execute('UPDATE users SET role = role')\n"
            "c.commit()\n"
            "print(os.geteuid(), os.getegid(), os.getgroups(), os.stat(str(users.db_path()) + '-wal').st_uid)\n"
            "c.close()\n"
        )
        res = subprocess.run(
            [sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60
        )
        assert res.returncode == 0, res.stderr
        assert res.stdout.split() == ["4321", "4322", "[]", "4321"], res.stdout
