"""``python -m app.users``: recover a CashPilot account from the server console.

CashPilot has no e-mail reset. Whoever runs the server resets a password from
the console of the UI container::

    python -m app.users list
    python -m app.users reset-password [USERNAME]
    python -m app.users rename OLD NEW

Three rules keep this command safe:

* It imports no ``app.*`` module. ``app.auth`` and ``app.database`` create key
  files in the data folder when they are missing. Against the wrong volume
  that would leave a new, useless key behind. Plain ``sqlite3`` and ``bcrypt``
  do the work instead.
* Run as root, it first drops to the uid and gid that own the database file.
  Otherwise a ``docker exec`` as root leaves root-owned ``-wal`` and ``-shm``
  files that the app cannot write.
* It refuses an empty users table. First-run setup goes through the setup
  token, never through this command.

The app keeps the session epoch in the memory of the web process. This command
cannot reach it, so cookies issued before a reset stay valid until the UI
restarts. At startup the app reads ``password_changed_at`` and rejects them.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import sqlite3
import sys
import time
from pathlib import Path

import bcrypt

# The registration rule for usernames. app/routers/auth.py imports it from here,
# so the form and this command cannot drift apart.
USERNAME_PATTERN = r"^[a-zA-Z0-9_-]{3,32}$"
USERNAME_RULE = "3-32 characters: letters, digits, _ and -"

# The app resolves its database the same way: app/database.py reads
# CASHPILOT_DATA_DIR with this default. A test checks that the two agree.
DEFAULT_DATA_DIR = "/data"

EMPTY_TABLE = "No users exist. Restart the container and use the setup token from its log."


class CommandError(Exception):
    """A failure to report on stderr with exit status 1."""


def valid_username(name: str) -> bool:
    return re.fullmatch(USERNAME_PATTERN, name) is not None


def db_path() -> Path:
    return Path(os.getenv("CASHPILOT_DATA_DIR", DEFAULT_DATA_DIR)) / "cashpilot.db"


def _drop_privileges(path: Path) -> None:
    """As root, become the user and group that own the database file."""
    if os.geteuid() != 0:
        return
    st = os.stat(path)
    if st.st_uid == 0:
        return
    os.setgroups([])
    os.setgid(st.st_gid)
    os.setuid(st.st_uid)


def _connect(path: Path) -> sqlite3.Connection:
    # mode=rw never creates the file: a wrong path is an error, not a new database.
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=rw", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _users(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT id, username, role FROM users ORDER BY id").fetchall()


def _print_users(rows: list[sqlite3.Row]) -> None:
    print(f"{'ID':>4}  {'USERNAME':<32}  ROLE")
    for r in rows:
        print(f"{r['id']:>4}  {r['username']:<32}  {r['role']}")


def _cmd_list(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    _print_users(_users(conn))
    return 0


def _cmd_reset_password(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    rows = _users(conn)
    if args.username is None:
        owners = [r for r in rows if r["role"] == "owner"]
        if len(owners) != 1:
            _print_users(rows)
            raise CommandError("Name the user to reset: python -m app.users reset-password USERNAME")
        target = owners[0]
    else:
        matches = [r for r in rows if r["username"] == args.username]
        if not matches:
            _print_users(rows)
            raise CommandError(f"No user named {args.username!r}. Usernames are case-sensitive.")
        target = matches[0]

    password = secrets.token_urlsafe(18)
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    with conn:
        conn.execute(
            "UPDATE users SET password = ?, password_changed_at = ? WHERE id = ?",
            (hashed, time.time(), target["id"]),
        )
    name = target["username"]
    print(f"New password for {name}: {password}")
    print("Sign in, then change it from the avatar menu. This password is not shown again.")
    print(
        f"Restart the UI container to sign out browsers that were logged in as {name}: "
        "docker restart <container> (cashpilot-ui in the stock compose file)."
    )
    return 0


def _cmd_rename(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    if not valid_username(args.new):
        raise CommandError(f"{args.new!r} is not a valid username ({USERNAME_RULE}).")
    try:
        with conn:
            cur = conn.execute("UPDATE users SET username = ? WHERE username = ?", (args.new, args.old))
    except sqlite3.IntegrityError:
        raise CommandError(f"The username {args.new!r} is already taken.") from None
    if cur.rowcount == 0:
        raise CommandError(f"No user named {args.old!r}. Usernames are case-sensitive.")
    print(f"Renamed {args.old} to {args.new}. Sign out and back in to see the new name.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.users",
        description="Recover a CashPilot account. Run it in the console of the CashPilot UI container.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="show every user: id, username and role")
    reset = sub.add_parser("reset-password", help="set a new random password and print it once")
    reset.add_argument("username", nargs="?", help="the user to reset; optional when there is one owner")
    rename = sub.add_parser("rename", help="change a username")
    rename.add_argument("old")
    rename.add_argument("new")
    args = parser.parse_args(argv)

    path = db_path()
    if not path.is_file():
        print(
            f"error: no database at {path}. Run this in the CashPilot UI container, "
            "or set CASHPILOT_DATA_DIR to the folder that holds cashpilot.db.",
            file=sys.stderr,
        )
        return 1
    _drop_privileges(path)
    try:
        conn = _connect(path)
    except sqlite3.Error as exc:
        print(f"error: cannot open {path}: {exc}", file=sys.stderr)
        return 1
    try:
        if not _users(conn):
            raise CommandError(EMPTY_TABLE)
        handler = {"list": _cmd_list, "reset-password": _cmd_reset_password, "rename": _cmd_rename}
        return handler[args.command](conn, args)
    except CommandError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except sqlite3.Error as exc:
        print(f"error: {path}: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
