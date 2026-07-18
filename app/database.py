"""SQLite database layer for CashPilot.

Stores earnings history, user configuration, and deployment records.
DB file lives at /data/cashpilot.db (Docker volume mount) with a local
fallback to ./data/cashpilot.db for development.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite
from cryptography.fernet import Fernet, InvalidToken

_logger = logging.getLogger(__name__)

DB_DIR = Path(os.getenv("CASHPILOT_DATA_DIR", "/data"))
DB_PATH = DB_DIR / "cashpilot.db"

# ---------------------------------------------------------------------------
# Credential encryption (Fernet)
# ---------------------------------------------------------------------------

_FERNET_KEY_FILE = DB_DIR / ".fernet_key"

# Keys that contain secrets and must be encrypted at rest
SECRET_CONFIG_KEYS = {
    "password",
    "token",
    "auth_token",
    "access_token",
    "api_key",
    "secret_key",
    "session_cookie",
    "auth_cookie",
    "oauth_token",
    "brd_sess_id",
    "remember_web",
    "xsrf_token",
}


def _is_secret_key(key: str) -> bool:
    """Return True if a config key holds a secret value (by suffix match)."""
    lower = key.lower()
    return any(lower.endswith(s) for s in SECRET_CONFIG_KEYS)


def _load_or_create_fernet() -> Fernet:
    """Load or generate the Fernet encryption key."""
    try:
        if _FERNET_KEY_FILE.is_file():
            raw = _FERNET_KEY_FILE.read_text().strip()
            if raw:
                return Fernet(raw.encode())
    except (OSError, ValueError):
        pass

    key = Fernet.generate_key()
    try:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        _FERNET_KEY_FILE.write_text(key.decode())
        _FERNET_KEY_FILE.chmod(0o600)
        _logger.info("Generated new Fernet key at %s", _FERNET_KEY_FILE)
    except OSError as exc:
        _logger.warning("Could not persist Fernet key: %s", exc)
    return Fernet(key)


_fernet = _load_or_create_fernet()

_ENC_PREFIX = "enc:"


def encrypt_value(value: str) -> str:
    """Encrypt a string value, returning an 'enc:' prefixed token."""
    return _ENC_PREFIX + _fernet.encrypt(value.encode()).decode()


def decrypt_value(value: str) -> str:
    """Decrypt an 'enc:' prefixed token back to plaintext."""
    if not value.startswith(_ENC_PREFIX):
        return value  # Not encrypted (legacy data)
    try:
        return _fernet.decrypt(value[len(_ENC_PREFIX) :].encode()).decode()
    except InvalidToken:
        _logger.warning(
            "Failed to decrypt config value: the Fernet ENCRYPTION KEY (CASHPILOT_SECRET_KEY / "
            "%s) does not match the key this value was encrypted with. This is NOT a bad "
            "credential — re-enter the affected credentials, or restore the original encryption "
            "key, to recover.",
            _FERNET_KEY_FILE,
        )
        return ""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS earnings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    platform   TEXT    NOT NULL,
    balance    REAL    NOT NULL,
    currency   TEXT    NOT NULL DEFAULT 'USD',
    date       TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deployments (
    slug               TEXT PRIMARY KEY,
    container_id       TEXT NOT NULL,
    env_vars_encrypted TEXT NOT NULL DEFAULT '',
    deployed_at        TEXT NOT NULL DEFAULT (datetime('now')),
    status             TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT    NOT NULL UNIQUE,
    password   TEXT    NOT NULL,
    role       TEXT    NOT NULL DEFAULT 'viewer',
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS workers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id       TEXT    NOT NULL UNIQUE,
    name            TEXT    NOT NULL DEFAULT '',
    url             TEXT    NOT NULL DEFAULT '',
    status          TEXT    NOT NULL DEFAULT 'online',
    containers      TEXT    NOT NULL DEFAULT '[]',
    apps            TEXT    NOT NULL DEFAULT '[]',
    system_info     TEXT    NOT NULL DEFAULT '{}',
    last_heartbeat  TEXT,
    api_key_enc     TEXT,
    key_confirmed   INTEGER NOT NULL DEFAULT 0,
    registered_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id             INTEGER PRIMARY KEY,
    setup_mode          TEXT    NOT NULL DEFAULT 'fresh',
    selected_categories TEXT    NOT NULL DEFAULT '[]',
    timezone            TEXT    NOT NULL DEFAULT 'UTC',
    setup_completed     INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS health_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    slug       TEXT    NOT NULL,
    event      TEXT    NOT NULL,
    detail     TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Durable per-user session-revocation epochs. A signed session cookie whose iat
-- predates a user's revoked_before is rejected. DELIBERATELY has no FOREIGN KEY to
-- users: when a user is deleted the revocation MUST outlive the row, so the deleted
-- account's still-valid 30-day cookies keep being rejected across UI restarts
-- (otherwise the in-memory epoch resets on restart and a deleted/demoted user's old
-- cookie regains their old role). Warmed into auth's in-memory epoch cache at startup.
CREATE TABLE IF NOT EXISTS session_revocations (
    user_id        INTEGER PRIMARY KEY,
    revoked_before REAL    NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_earnings_platform_date
    ON earnings (platform, date);

CREATE INDEX IF NOT EXISTS idx_earnings_created
    ON earnings (created_at);

CREATE INDEX IF NOT EXISTS idx_workers_status
    ON workers (status);

CREATE INDEX IF NOT EXISTS idx_health_events_slug
    ON health_events (slug, created_at);

CREATE INDEX IF NOT EXISTS idx_health_events_created
    ON health_events (created_at);
"""


# ---------------------------------------------------------------------------
# Shared connection management
# ---------------------------------------------------------------------------
#
# Each event loop gets a single long-lived aiosqlite connection. In production
# there is one uvicorn loop, so all 36 DB helpers reuse one connection instead
# of opening (and WAL-initialising) a fresh one on every call. Tests use
# ``asyncio.run(...)`` which creates a brand-new loop per call, so each test
# gets its own isolated connection.
#
# The 36 helpers keep their ``db = await _get_db(); try: ... finally:
# await db.close()`` shape unchanged. ``_get_db()`` hands back a
# ``_BorrowedConnection`` proxy whose ``.close()`` is a no-op, so the borrowed
# handle's ``finally`` never actually tears down the shared connection.

_shared_conns: dict[int, aiosqlite.Connection] = {}


class _BorrowedConnection:
    """A borrowed view onto a shared aiosqlite connection.

    Delegates every attribute (execute, commit, fetch*, row_factory, ...) to
    the real connection, but turns ``close()`` into an async no-op and makes
    ``async with`` a pass-through. This lets call sites keep their
    ``finally: await db.close()`` pattern byte-for-byte while the underlying
    connection stays open and shared for the lifetime of the event loop.
    """

    __slots__ = ("_conn",)

    def __init__(self, conn: aiosqlite.Connection) -> None:
        object.__setattr__(self, "_conn", conn)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_conn"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(object.__getattribute__(self, "_conn"), name, value)

    async def close(self) -> None:
        """No-op: the shared connection outlives any individual borrow."""
        return None

    async def __aenter__(self) -> _BorrowedConnection:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _open_connection() -> aiosqlite.Connection:
    """Create an unawaited aiosqlite connection with row factory + PRAGMAs.

    The returned object is the ``aiosqlite.connect(...)`` awaitable/context
    manager; the caller awaits it to obtain the live connection. The row
    factory and PRAGMAs are applied once per connection in ``_get_db()``.
    """
    DB_DIR.mkdir(parents=True, exist_ok=True)
    return aiosqlite.connect(str(DB_PATH))


async def _get_db() -> _BorrowedConnection:
    """Return a borrowed handle on this event loop's shared connection.

    Opens (and caches) a connection the first time it is needed on a given
    loop, or whenever the cached connection has been closed. The returned
    ``_BorrowedConnection`` is safe to ``close()`` — it is a no-op.
    """
    loop = asyncio.get_running_loop()
    key = id(loop)
    conn = _shared_conns.get(key)

    needs_open = conn is None
    if conn is not None:
        try:
            needs_open = not conn._running
        except AttributeError:
            needs_open = False

    if needs_open:
        conn = await _open_connection()
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute("PRAGMA busy_timeout=5000")
        _shared_conns[key] = conn

    return _BorrowedConnection(conn)


async def connect_shared() -> None:
    """Eagerly open the shared connection for the current event loop."""
    await _get_db()


async def close_shared() -> None:
    """Close and forget the current event loop's shared connection."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    conn = _shared_conns.pop(id(loop), None)
    if conn is not None:
        await conn.close()


async def init_db() -> None:
    """Create tables if they don't exist."""
    db = await _get_db()
    try:
        await db.executescript(_SCHEMA)
        # Migrate workers table: add client_id (UNIQUE) and apps columns
        cursor = await db.execute("PRAGMA table_info(workers)")
        cols = {row["name"] for row in await cursor.fetchall()}
        if "client_id" not in cols:
            # Rebuild table: UNIQUE moves from name → client_id, name becomes display-only.
            # Existing rows get client_id = name for backward compat.
            has_apps = "apps" in cols
            apps_select = "apps" if has_apps else "'[]'"
            _logger.info("Migrating workers table: adding client_id column")
            await db.executescript(f"""
                CREATE TABLE workers_new (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id       TEXT    NOT NULL UNIQUE,
                    name            TEXT    NOT NULL DEFAULT '',
                    url             TEXT    NOT NULL DEFAULT '',
                    status          TEXT    NOT NULL DEFAULT 'online',
                    containers      TEXT    NOT NULL DEFAULT '[]',
                    apps            TEXT    NOT NULL DEFAULT '[]',
                    system_info     TEXT    NOT NULL DEFAULT '{{}}',
                    last_heartbeat  TEXT,
                    registered_at   TEXT    NOT NULL DEFAULT (datetime('now'))
                );
                INSERT INTO workers_new
                    (id, client_id, name, url, status, containers, apps, system_info, last_heartbeat, registered_at)
                SELECT id, name, name, url, status, containers, {apps_select}, system_info, last_heartbeat, registered_at
                FROM workers;
                DROP TABLE workers;
                ALTER TABLE workers_new RENAME TO workers;
                CREATE INDEX IF NOT EXISTS idx_workers_status ON workers (status);
            """)
        elif "apps" not in cols:
            await db.execute("ALTER TABLE workers ADD COLUMN apps TEXT NOT NULL DEFAULT '[]'")

        # Migrate workers table: add api_key_enc for per-worker fleet keys.
        # (cols is the pre-rebuild snapshot; on a fresh DB the column comes from
        # _SCHEMA so it is already present here and the ALTER is skipped.)
        if "api_key_enc" not in cols:
            await db.execute("ALTER TABLE workers ADD COLUMN api_key_enc TEXT")
        if "key_confirmed" not in cols:
            await db.execute("ALTER TABLE workers ADD COLUMN key_confirmed INTEGER NOT NULL DEFAULT 0")

        # Migrate users table: add password_changed_at for session invalidation
        cursor = await db.execute("PRAGMA table_info(users)")
        user_cols = {row["name"] for row in await cursor.fetchall()}
        if "password_changed_at" not in user_cols:
            await db.execute("ALTER TABLE users ADD COLUMN password_changed_at REAL DEFAULT 0")

        await db.commit()
    finally:
        await db.close()


# --- Earnings ---


async def upsert_earnings(
    platform: str,
    balance: float,
    currency: str = "USD",
    date: str | None = None,
) -> None:
    """Insert or update an earnings record for a platform + date."""
    date = date or datetime.now(UTC).strftime("%Y-%m-%d")
    db = await _get_db()
    try:
        # Insert a new reading, or update the existing platform+date row only
        # when the balance changed (we always want the latest reading). The
        # WHERE guard preserves created_at when the balance is unchanged.
        await db.execute(
            """
            INSERT INTO earnings (platform, balance, currency, date)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(platform, date) DO UPDATE SET
                balance = excluded.balance,
                currency = excluded.currency,
                created_at = datetime('now')
            WHERE earnings.balance != excluded.balance
            """,
            (platform, balance, currency, date),
        )
        await db.commit()
    finally:
        await db.close()


async def get_earnings_summary() -> list[dict[str, Any]]:
    """Return the latest balance for each platform."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            SELECT platform, balance, currency, date
            FROM earnings
            WHERE (platform, date) IN (
                SELECT platform, MAX(date) FROM earnings GROUP BY platform
            )
            ORDER BY platform
            """
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_earnings_history(
    period: str = "week",
) -> list[dict[str, Any]]:
    """Return earnings history filtered by period (week, month, year, all)."""
    days_map = {"week": 7, "month": 30, "year": 365}
    days = days_map.get(period)

    db = await _get_db()
    try:
        if days:
            cursor = await db.execute(
                """
                SELECT platform, balance, currency, date
                FROM earnings
                WHERE date >= date('now', ?)
                ORDER BY date DESC, platform
                """,
                (f"-{days} days",),
            )
        else:
            cursor = await db.execute(
                "SELECT platform, balance, currency, date FROM earnings ORDER BY date DESC, platform"
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_earnings_dashboard_summary() -> dict[str, Any]:
    """Return aggregated earnings stats for the dashboard."""
    db = await _get_db()
    try:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
        first_of_month = datetime.now(UTC).replace(day=1).strftime("%Y-%m-%d")

        # Total: sum of latest balance per platform (USD only for now)
        cursor = await db.execute(
            """
            SELECT COALESCE(SUM(e.balance), 0) as total
            FROM earnings e
            INNER JOIN (
                SELECT platform, MAX(date) as max_date
                FROM earnings WHERE currency = 'USD'
                GROUP BY platform
            ) latest ON e.platform = latest.platform AND e.date = latest.max_date
            WHERE e.currency = 'USD'
            """
        )
        row = await cursor.fetchone()
        total = row["total"]

        # Today's earnings: delta from yesterday per platform
        cursor = await db.execute(
            """
            SELECT COALESCE(SUM(t.balance - COALESCE(y.balance, 0)), 0) as earned
            FROM (
                SELECT platform, balance FROM earnings
                WHERE date = ? AND currency = 'USD'
            ) t
            LEFT JOIN (
                SELECT platform, balance FROM earnings
                WHERE date = ? AND currency = 'USD'
            ) y ON t.platform = y.platform
            """,
            (today, yesterday),
        )
        row = await cursor.fetchone()
        today_earned = max(0.0, row["earned"])

        # This month's earnings: latest balance minus first-of-month balance
        cursor = await db.execute(
            """
            SELECT COALESCE(SUM(
                latest.balance - COALESCE(month_start.balance, 0)
            ), 0) as earned
            FROM (
                SELECT e.platform, e.balance
                FROM earnings e
                INNER JOIN (
                    SELECT platform, MAX(date) as max_date
                    FROM earnings WHERE currency = 'USD'
                    GROUP BY platform
                ) m ON e.platform = m.platform AND e.date = m.max_date
                WHERE e.currency = 'USD'
            ) latest
            LEFT JOIN (
                SELECT e.platform, e.balance
                FROM earnings e
                INNER JOIN (
                    SELECT platform, MIN(date) as min_date
                    FROM earnings
                    WHERE date >= ? AND currency = 'USD'
                    GROUP BY platform
                ) m ON e.platform = m.platform AND e.date = m.min_date
                WHERE e.currency = 'USD'
            ) month_start ON latest.platform = month_start.platform
            """,
            (first_of_month,),
        )
        row = await cursor.fetchone()
        month_earned = max(0.0, row["earned"])

        # Yesterday's delta for percentage change
        day_before = (datetime.now(UTC) - timedelta(days=2)).strftime("%Y-%m-%d")
        cursor = await db.execute(
            """
            SELECT COALESCE(SUM(y.balance - COALESCE(dy.balance, 0)), 0) as earned
            FROM (
                SELECT platform, balance FROM earnings
                WHERE date = ? AND currency = 'USD'
            ) y
            LEFT JOIN (
                SELECT platform, balance FROM earnings
                WHERE date = ? AND currency = 'USD'
            ) dy ON y.platform = dy.platform
            """,
            (yesterday, day_before),
        )
        row = await cursor.fetchone()
        yesterday_earned = max(0.0, row["earned"])

        today_change = 0.0
        if yesterday_earned > 0:
            today_change = ((today_earned - yesterday_earned) / yesterday_earned) * 100

        return {
            "total": round(total, 2),
            "today": round(today_earned, 2),
            "month": round(month_earned, 2),
            "today_change": round(today_change, 1),
            "month_change": 0.0,
        }
    finally:
        await db.close()


async def get_earnings_per_service() -> list[dict[str, Any]]:
    """Return per-platform earnings breakdown: latest balance, previous balance, trend."""
    db = await _get_db()
    try:
        # Latest balance per platform
        cursor = await db.execute(
            """
            SELECT
                e.platform,
                e.balance,
                e.currency,
                e.date,
                COALESCE(prev.balance, 0) as prev_balance
            FROM earnings e
            INNER JOIN (
                SELECT platform, MAX(date) as max_date
                FROM earnings GROUP BY platform
            ) latest ON e.platform = latest.platform AND e.date = latest.max_date
            LEFT JOIN (
                SELECT e2.platform, e2.balance
                FROM earnings e2
                INNER JOIN (
                    SELECT platform, MAX(date) as max_date
                    FROM earnings
                    WHERE date < (SELECT MAX(date) FROM earnings e3 WHERE e3.platform = earnings.platform)
                    GROUP BY platform
                ) prev_latest ON e2.platform = prev_latest.platform AND e2.date = prev_latest.max_date
            ) prev ON e.platform = prev.platform
            ORDER BY e.balance DESC
            """
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_daily_earnings(days: int = 7) -> list[dict[str, Any]]:
    """Return daily aggregated earnings for charting (delta per day)."""
    db = await _get_db()
    try:
        # Get daily total balance (sum across platforms) for the range
        # Include one extra day before the range so we can compute the first delta
        cursor = await db.execute(
            """
            SELECT date, SUM(balance) as total_balance
            FROM earnings
            WHERE date >= date('now', ?) AND currency = 'USD'
            GROUP BY date
            ORDER BY date
            """,
            (f"-{days + 1} days",),
        )
        rows = await cursor.fetchall()
        data = [dict(r) for r in rows]

        # Build a map of date -> total_balance
        balance_by_date: dict[str, float] = {}
        for row in data:
            balance_by_date[row["date"]] = row["total_balance"]

        # Generate result for exactly `days` days
        now = datetime.now(UTC)
        result = []
        for i in range(days - 1, -1, -1):
            d = now - timedelta(days=i)
            date_str = d.strftime("%Y-%m-%d")
            prev_str = (d - timedelta(days=1)).strftime("%Y-%m-%d")

            current = balance_by_date.get(date_str, 0.0)
            previous = balance_by_date.get(prev_str, 0.0)
            delta = max(0.0, current - previous) if current > 0 else 0.0

            result.append(
                {
                    "date": d.strftime("%b %d"),
                    "amount": round(delta, 2),
                }
            )

        return result
    finally:
        await db.close()


# --- Config ---


async def get_config(key: str | None = None) -> dict[str, str] | str | None:
    """Get a single config value (if key given) or all config as a dict.

    Secret values are decrypted transparently.
    """
    db = await _get_db()
    try:
        if key:
            cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
            row = await cursor.fetchone()
            if not row:
                return None
            val = row["value"]
            return decrypt_value(val) if _is_secret_key(key) else val
        cursor = await db.execute("SELECT key, value FROM config")
        rows = await cursor.fetchall()
        return {r["key"]: (decrypt_value(r["value"]) if _is_secret_key(r["key"]) else r["value"]) for r in rows}
    finally:
        await db.close()


async def get_config_masked() -> dict[str, Any]:
    """Return non-secret config values plus a {secret_key: is_set} map.

    Secret values are NEVER decrypted or returned — only their presence is
    reported under the ``_secrets`` key. This is the read path for the UI so
    stored credentials never cross the wire in plaintext.
    """
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT key, value FROM config")
        rows = await cursor.fetchall()
        values: dict[str, Any] = {}
        secrets_set: dict[str, bool] = {}
        for r in rows:
            if _is_secret_key(r["key"]):
                secrets_set[r["key"]] = bool(r["value"])
            else:
                values[r["key"]] = r["value"]
        values["_secrets"] = secrets_set
        return values
    finally:
        await db.close()


async def set_config(key: str, value: str) -> None:
    """Upsert a config key-value pair. Secrets are encrypted at rest."""
    stored = encrypt_value(value) if _is_secret_key(key) else value
    db = await _get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (key, stored),
        )
        await db.commit()
    finally:
        await db.close()


async def set_config_bulk(data: dict[str, str]) -> None:
    """Upsert multiple config entries at once. Secrets are encrypted at rest."""
    pairs = [(k, encrypt_value(v) if _is_secret_key(k) else v) for k, v in data.items()]
    db = await _get_db()
    try:
        await db.executemany(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            pairs,
        )
        await db.commit()
    finally:
        await db.close()


async def delete_config_keys(keys: list[str]) -> None:
    """Delete one or more config entries by key."""
    if not keys:
        return
    db = await _get_db()
    try:
        placeholders = ",".join("?" for _ in keys)
        await db.execute(f"DELETE FROM config WHERE key IN ({placeholders})", keys)
        await db.commit()
    finally:
        await db.close()


# --- Deployments ---


async def save_deployment(
    slug: str,
    container_id: str,
    env_vars_encrypted: str = "",
    status: str = "running",
) -> None:
    db = await _get_db()
    try:
        await db.execute(
            """
            INSERT OR REPLACE INTO deployments
                (slug, container_id, env_vars_encrypted, deployed_at, status)
            VALUES (?, ?, ?, datetime('now'), ?)
            """,
            (slug, container_id, env_vars_encrypted, status),
        )
        await db.commit()
    finally:
        await db.close()


async def get_deployments() -> list[dict[str, Any]]:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM deployments ORDER BY slug")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_deployment(slug: str) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM deployments WHERE slug = ?", (slug,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def remove_deployment(slug: str) -> None:
    db = await _get_db()
    try:
        await db.execute("DELETE FROM deployments WHERE slug = ?", (slug,))
        await db.commit()
    finally:
        await db.close()


# --- Users ---


async def has_any_users() -> bool:
    """Check if any user accounts exist (for first-run detection)."""
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM users")
        row = await cursor.fetchone()
        return row["cnt"] > 0
    finally:
        await db.close()


async def create_user(username: str, hashed_password: str, role: str = "viewer") -> int:
    db = await _get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            (username, hashed_password, role),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def create_first_owner(username: str, hashed_password: str) -> int | None:
    """Atomically create the first owner account.

    Returns the new id, or ``None`` if any account already exists (lost the
    first-run race). The ``INSERT ... WHERE NOT EXISTS`` makes the "one owner per
    setup token" guarantee safe against two concurrent first-run registrations,
    which a check-then-act (``has_any_users()`` then ``create_user()``) could not.
    """
    db = await _get_db()
    try:
        cursor = await db.execute(
            "INSERT INTO users (username, password, role) SELECT ?, ?, 'owner' WHERE NOT EXISTS (SELECT 1 FROM users)",
            (username, hashed_password),
        )
        await db.commit()
        if cursor.rowcount != 1:
            return None
        return cursor.lastrowid
    finally:
        await db.close()


async def get_user_by_username(username: str) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def list_users() -> list[dict[str, Any]]:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT id, username, role, created_at FROM users ORDER BY id")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def list_users_with_pwd_epoch() -> list[dict[str, Any]]:
    """Return [{id, password_changed_at}, ...] for warming the auth pwd-epoch cache."""
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT id, password_changed_at FROM users")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def update_user_role(user_id: int, role: str) -> None:
    db = await _get_db()
    try:
        await db.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        await db.commit()
    finally:
        await db.close()


async def delete_user(user_id: int) -> None:
    db = await _get_db()
    try:
        await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await db.commit()
    finally:
        await db.close()


# Kept in sync with auth.SESSION_MAX_AGE (30 days); duplicated as a plain constant
# so this module doesn't import auth (which would create a cycle).
_SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30


async def revoke_user_sessions(user_id: int, revoked_before: float) -> None:
    """Durably invalidate a user's outstanding session cookies.

    Records that any session token for ``user_id`` issued before ``revoked_before``
    must be rejected. This table has no FK to ``users``, so the revocation outlives
    a deleted row and is restored into auth's in-memory epoch cache at startup —
    that is what stops a deleted/demoted account's still-valid 30-day cookie from
    regaining access after a UI restart. The write is monotonic (an older timestamp
    can never lower an existing revocation), and rows whose window has fully elapsed
    are pruned since the tokens they guarded have themselves expired.
    """
    db = await _get_db()
    try:
        await db.execute(
            """
            INSERT INTO session_revocations (user_id, revoked_before)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET revoked_before = excluded.revoked_before
            WHERE excluded.revoked_before > session_revocations.revoked_before
            """,
            (user_id, revoked_before),
        )
        await db.execute(
            "DELETE FROM session_revocations WHERE revoked_before < ?",
            (revoked_before - _SESSION_MAX_AGE_SECONDS,),
        )
        await db.commit()
    finally:
        await db.close()


async def list_session_revocations() -> list[dict[str, Any]]:
    """Return [{user_id, revoked_before}, ...] for warming the auth epoch cache."""
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT user_id, revoked_before FROM session_revocations")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def update_user_password(user_id: int, hashed_password: str) -> None:
    """Update a user's password and record the change timestamp."""
    import time

    db = await _get_db()
    try:
        await db.execute(
            "UPDATE users SET password = ?, password_changed_at = ? WHERE id = ?",
            (hashed_password, time.time(), user_id),
        )
        await db.commit()
    finally:
        await db.close()


# --- User Preferences ---


async def get_user_preferences(user_id: int) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM user_preferences WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def save_user_preferences(
    user_id: int,
    setup_mode: str = "fresh",
    selected_categories: str = "[]",
    timezone: str = "UTC",
    setup_completed: bool = False,
) -> None:
    db = await _get_db()
    try:
        await db.execute(
            """
            INSERT INTO user_preferences
                (user_id, setup_mode, selected_categories, timezone, setup_completed, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                setup_mode = excluded.setup_mode,
                selected_categories = excluded.selected_categories,
                timezone = excluded.timezone,
                setup_completed = excluded.setup_completed,
                updated_at = datetime('now')
            """,
            (user_id, setup_mode, selected_categories, timezone, int(setup_completed)),
        )
        await db.commit()
    finally:
        await db.close()


async def mark_setup_completed(user_id: int) -> None:
    db = await _get_db()
    try:
        await db.execute(
            "UPDATE user_preferences SET setup_completed = 1, updated_at = datetime('now') WHERE user_id = ?",
            (user_id,),
        )
        await db.commit()
    finally:
        await db.close()


# --- Workers (Fleet) ---


async def upsert_worker(
    client_id: str,
    name: str = "",
    url: str = "",
    containers: str = "[]",
    apps: str = "[]",
    system_info: str = "{}",
) -> int:
    """Register or update a worker by client_id. Returns the worker ID."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            INSERT INTO workers (client_id, name, url, containers, apps, system_info, status, last_heartbeat)
            VALUES (?, ?, ?, ?, ?, ?, 'online', datetime('now'))
            ON CONFLICT(client_id) DO UPDATE SET
                name = excluded.name,
                url = excluded.url,
                containers = excluded.containers,
                apps = excluded.apps,
                system_info = excluded.system_info,
                status = 'online',
                last_heartbeat = datetime('now')
            """,
            (client_id, name, url, containers, apps, system_info),
        )
        await db.commit()
        cursor = await db.execute("SELECT id FROM workers WHERE client_id = ?", (client_id,))
        row = await cursor.fetchone()
        return row["id"]
    finally:
        await db.close()


async def get_worker(worker_id: int) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM workers WHERE id = ?", (worker_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def list_workers() -> list[dict[str, Any]]:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM workers ORDER BY name")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def set_worker_status(worker_id: int, status: str) -> None:
    db = await _get_db()
    try:
        await db.execute("UPDATE workers SET status = ? WHERE id = ?", (status, worker_id))
        await db.commit()
    finally:
        await db.close()


async def delete_worker(worker_id: int) -> None:
    db = await _get_db()
    try:
        await db.execute("DELETE FROM workers WHERE id = ?", (worker_id,))
        await db.commit()
    finally:
        await db.close()


# --- Per-worker fleet keys ---
#
# The UI must both VERIFY inbound heartbeats from a worker and, for the full
# cutover, AUTHENTICATE outbound calls TO that worker — so it needs the key
# itself, not just a one-way hash. Keys are therefore stored encrypted at rest
# (Fernet, the same at-rest protection as service credentials) and decrypted on
# demand for comparison and for outbound Authorization headers.


async def set_worker_key(client_id: str, key: str) -> None:
    """Store a worker's per-worker key (encrypted), unconfirmed until the worker
    proves it holds the key by using it on a later heartbeat."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "UPDATE workers SET api_key_enc = ?, key_confirmed = 0 WHERE client_id = ?",
            (encrypt_value(key), client_id),
        )
        await db.commit()
        if not cursor.rowcount:
            # The worker row must exist first (upsert runs before this); a missing
            # row would silently drop the key and lock the worker out.
            _logger.warning("set_worker_key: no worker row for client_id=%s", client_id)
    finally:
        await db.close()


async def confirm_worker_key(client_id: str) -> None:
    """Mark a worker's key confirmed — it has authenticated with its own key, so the
    shared bootstrap key is refused from now on (the cutover finalizes)."""
    db = await _get_db()
    try:
        await db.execute(
            "UPDATE workers SET key_confirmed = 1 WHERE client_id = ?",
            (client_id,),
        )
        await db.commit()
    finally:
        await db.close()


async def get_worker_key(client_id: str) -> str | None:
    """Return a worker's per-worker key (decrypted), or None if not yet enrolled."""
    key, _ = await get_worker_key_state(client_id)
    return key


async def get_worker_key_state(client_id: str) -> tuple[str | None, bool]:
    """Return (key, confirmed) for a worker: the decrypted per-worker key (or None
    if unenrolled, or if the stored key can no longer be decrypted) and whether the
    worker has confirmed it by using it."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT api_key_enc, key_confirmed FROM workers WHERE client_id = ?",
            (client_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None, False
        enc = row["api_key_enc"]
        if not enc:
            return None, bool(row["key_confirmed"])
        key = decrypt_value(enc)
        if not key:
            # decrypt_value() returns "" (after logging its own warning) when the
            # Fernet key can't decrypt this value -- e.g. CASHPILOT_SECRET_KEY was
            # rotated or restored from a different value. A real per-worker key is
            # always a secrets.token_urlsafe(32) string and can never legitimately
            # be empty, so "" here unambiguously means "undecryptable", not "empty
            # key". Report it as NOT enrolled (None) rather than as a real key that
            # can never match, so callers fall back to the shared bootstrap key and
            # the worker can re-enroll instead of being permanently bricked.
            _logger.error(
                "Worker '%s' per-worker key is undecryptable (CASHPILOT_SECRET_KEY "
                "changed?) -- treating as unenrolled so it can re-enroll via the "
                "shared key",
                client_id,
            )
            return None, False
        return key, bool(row["key_confirmed"])
    finally:
        await db.close()


# --- Health Events ---


async def record_health_event(slug: str, event: str, detail: str = "") -> None:
    """Record a health event (start, stop, restart, crash, check_ok)."""
    db = await _get_db()
    try:
        await db.execute(
            "INSERT INTO health_events (slug, event, detail) VALUES (?, ?, ?)",
            (slug, event, detail),
        )
        await db.commit()
    finally:
        await db.close()


async def get_health_scores(days: int = 7) -> list[dict[str, Any]]:
    """Compute health score per service over the last N days.

    Score formula (0-100):
    - Start at 100
    - -5 per restart
    - -20 per crash
    - Uptime ratio bonus: (running_checks / total_checks) * weight
    """
    db = await _get_db()
    try:
        cutoff = f"-{days} days"
        cursor = await db.execute(
            """
            SELECT
                slug,
                COUNT(*) as total_events,
                SUM(CASE WHEN event = 'restart' THEN 1 ELSE 0 END) as restarts,
                SUM(CASE WHEN event = 'crash' THEN 1 ELSE 0 END) as crashes,
                SUM(CASE WHEN event = 'stop' THEN 1 ELSE 0 END) as stops,
                SUM(CASE WHEN event = 'check_ok' THEN 1 ELSE 0 END) as ok_checks,
                SUM(CASE WHEN event IN ('check_ok', 'check_down') THEN 1 ELSE 0 END) as total_checks,
                MIN(created_at) as first_event,
                MAX(created_at) as last_event
            FROM health_events
            WHERE created_at >= datetime('now', ?)
            GROUP BY slug
            ORDER BY slug
            """,
            (cutoff,),
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            r = dict(row)
            score = 100.0
            score -= r["restarts"] * 5
            score -= r["crashes"] * 20
            score -= r["stops"] * 2

            # Uptime ratio
            if r["total_checks"] > 0:
                uptime_ratio = r["ok_checks"] / r["total_checks"]
                score = score * 0.4 + uptime_ratio * 100 * 0.6
            score = max(0.0, min(100.0, score))

            results.append(
                {
                    "slug": r["slug"],
                    "score": round(score, 1),
                    "restarts": r["restarts"],
                    "crashes": r["crashes"],
                    "stops": r["stops"],
                    "uptime_checks": r["ok_checks"],
                    "total_checks": r["total_checks"],
                    "uptime_pct": round(r["ok_checks"] / r["total_checks"] * 100, 1) if r["total_checks"] > 0 else None,
                }
            )
        return results
    finally:
        await db.close()


# --- Data Retention ---

RETENTION_DAYS = 400
# High-frequency uptime samples (check_ok / check_down, one per service every 5
# minutes) are the dominant source of health_events growth, yet get_health_scores
# only ever reads a bounded window. /api/health/scores caps that window at 90 days,
# so we keep samples just past that (95d) — enough that no allowed query can
# out-range its own samples, while still cutting the bulk sample rows ~76% versus
# the 400-day lifecycle-event history (start/stop/restart/crash), which we keep in
# full because those rows are rare and worth the long tail.
HEALTH_CHECK_RETENTION_DAYS = 95
_HEALTH_CHECK_EVENTS = ("check_ok", "check_down")


async def purge_old_data() -> int:
    """Delete data past retention. Returns rows deleted.

    Earnings and lifecycle health events are kept RETENTION_DAYS; the far more
    numerous uptime-sample events are trimmed to HEALTH_CHECK_RETENTION_DAYS.
    """
    db = await _get_db()
    try:
        cutoff = f"-{RETENTION_DAYS} days"
        check_cutoff = f"-{HEALTH_CHECK_RETENTION_DAYS} days"
        c1 = await db.execute(
            "DELETE FROM earnings WHERE created_at < datetime('now', ?)",
            (cutoff,),
        )
        c2 = await db.execute(
            "DELETE FROM health_events WHERE created_at < datetime('now', ?)",
            (cutoff,),
        )
        c3 = await db.execute(
            "DELETE FROM health_events WHERE event IN ('check_ok', 'check_down') AND created_at < datetime('now', ?)",
            (check_cutoff,),
        )
        await db.commit()
        return (c1.rowcount or 0) + (c2.rowcount or 0) + (c3.rowcount or 0)
    finally:
        await db.close()


async def vacuum_database() -> None:
    """Reclaim free pages left by retention deletes.

    SQLite never shrinks the file on DELETE alone, so without a periodic VACUUM the
    database keeps its high-water-mark size forever even as old rows are purged.
    Run off-peak (weekly) — VACUUM rewrites the whole file and briefly locks it. We
    commit first because VACUUM cannot run inside an open transaction, and checkpoint
    the WAL afterwards so the freed space is actually returned to the filesystem.
    """
    db = await _get_db()
    try:
        await db.commit()
        await db.execute("VACUUM")
        await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        await db.close()
