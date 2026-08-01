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


_TRUTHY = {"1", "true", "yes", "on"}

# Set when CASHPILOT_ENCRYPTION_KEY is present but not a usable Fernet key.
_fernet_key_error: str | None = None
# Set when the key could not be written to disk, i.e. it dies with this process.
_fernet_key_persist_error: str | None = None
_fernet_key_is_ephemeral = False


def _load_or_create_fernet() -> Fernet:
    """Resolve the key used to encrypt stored credentials.

    Precedence is deliberate, and file-first:

      1. ``<data>/.fernet_key`` always wins when it exists.
      2. Otherwise ``CASHPILOT_ENCRYPTION_KEY``, which is then persisted.
      3. Otherwise a fresh key is generated and persisted.

    Reading the file first is what makes the environment variable safe to
    introduce. Env-first would mean anyone who sets it on a running instance
    instantly loses every credential already encrypted under the file key. The
    restore case is unaffected, because a wiped volume has no file for the
    environment value to lose to.

    Note this is NOT ``CASHPILOT_SECRET_KEY``, which signs sessions and lives at
    ``<data>/.secret_key``. They are separate keys with separate jobs.
    """
    global _fernet_key_error, _fernet_key_persist_error, _fernet_key_is_ephemeral

    env_raw = os.getenv("CASHPILOT_ENCRYPTION_KEY", "").strip()
    env_key: bytes | None = None
    if env_raw:
        try:
            Fernet(env_raw.encode())
            env_key = env_raw.encode()
        except (ValueError, TypeError) as exc:
            # Do not quietly generate a replacement: that is the same silent
            # failure this function exists to remove. Record it and let startup
            # refuse.
            _fernet_key_error = (
                f"CASHPILOT_ENCRYPTION_KEY is set but is not a valid Fernet key "
                f"({exc or 'malformed'}). It must be a urlsafe-base64 32-byte key, as "
                'produced by `python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"`.'
            )
            _logger.error("%s", _fernet_key_error)

    # 1. An existing key file always wins.
    unusable: str | None = None
    try:
        if _FERNET_KEY_FILE.is_file():
            raw = _FERNET_KEY_FILE.read_text().strip()
            if raw:
                try:
                    fernet = Fernet(raw.encode())
                except (ValueError, TypeError) as exc:
                    unusable = f"it is not a valid Fernet key ({exc})"
                else:
                    if env_key and env_key != raw.encode():
                        _logger.warning(
                            "CASHPILOT_ENCRYPTION_KEY differs from the key already stored "
                            "at %s. The stored key wins, because switching keys would make "
                            "every existing credential unreadable. To adopt the environment "
                            "key instead, remove the file and re-enter your credentials.",
                            _FERNET_KEY_FILE,
                        )
                    return fernet
            # An empty file means no key was ever stored, so replacing it loses
            # nothing. Fall through and mint one.
    except OSError as exc:
        unusable = f"it could not be read ({exc})"

    if unusable:
        # Refuse rather than overwrite. Credentials already in the database were
        # encrypted under the key this file was meant to hold, so replacing it
        # destroys the only artifact that could still decrypt them.
        _fernet_key_error = (
            f"the key file {_FERNET_KEY_FILE} exists but {unusable}. Refusing to "
            "overwrite it: any credential already stored was encrypted under that "
            "key, and replacing the file would make them permanently unreadable. "
            "Restore the file from backup, or move it aside and re-enter your "
            "credentials."
        )
        _logger.error("%s", _fernet_key_error)
        # Return a working cipher so importing this module stays side-effect free;
        # startup refuses via verify_encryption_key_persisted().
        return Fernet(Fernet.generate_key())

    # 2/3. Adopt the supplied key, or mint one.
    key = env_key if env_key else Fernet.generate_key()
    try:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        # Create with 0o600 up front rather than chmod-ing afterwards: writing
        # first would leave the key briefly readable to anyone, depending on umask.
        fd = os.open(_FERNET_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, key)
        finally:
            os.close(fd)
        # An existing file keeps its old mode, so tighten it regardless.
        _FERNET_KEY_FILE.chmod(0o600)
        _logger.info(
            "%s credential-encryption key at %s",
            "Adopted the supplied" if env_key else "Generated a new",
            _FERNET_KEY_FILE,
        )
    except OSError as exc:
        _fernet_key_persist_error = str(exc)
        _fernet_key_is_ephemeral = True
        _logger.error(
            "Could not persist the credential-encryption key to %s: %s. "
            "Credentials encrypted now will be unreadable after a restart.",
            _FERNET_KEY_FILE,
            exc,
        )
    return Fernet(key)


_fernet = _load_or_create_fernet()


def verify_encryption_key_persisted() -> None:
    """Raise unless the credential-encryption key will survive a restart.

    Call this from application startup, never at import time: ``app.database``
    is imported by the test suite with the default ``/data``, which does not
    exist on a development machine, so importing must stay side-effect free.

    Continuing with a key that cannot be persisted is not a kindness. Every
    credential stored during this run becomes undecryptable the moment the
    process restarts, and the symptom the user eventually sees is a provider
    auth failure, which points nowhere near the real cause.
    """
    if _fernet_key_error:
        raise RuntimeError(
            f"{_fernet_key_error} Refusing to start rather than encrypting credentials under a throwaway key."
        )

    if not _fernet_key_is_ephemeral:
        return

    if os.getenv("CASHPILOT_ALLOW_EPHEMERAL_KEY", "").strip().lower() in _TRUTHY:
        _logger.warning(
            "Running with an EPHEMERAL credential-encryption key because "
            "CASHPILOT_ALLOW_EPHEMERAL_KEY is set. Every stored credential will "
            "become unreadable when this process restarts."
        )
        return

    raise RuntimeError(
        f"Cannot persist the credential-encryption key to {_FERNET_KEY_FILE}: "
        f"{_fernet_key_persist_error}. Credentials encrypted now would be "
        "permanently unreadable after a restart, so CashPilot is refusing to "
        "start. Fix the permissions or the volume mount for the data directory "
        "(CASHPILOT_DATA_DIR), supply a key via CASHPILOT_ENCRYPTION_KEY on a "
        "writable volume, or set CASHPILOT_ALLOW_EPHEMERAL_KEY=true if you "
        "genuinely want a throwaway instance."
    )


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
        # Deliberately ERROR, not WARNING: this is unattended software, and the
        # downstream symptom is a provider auth failure that points nowhere near
        # the real cause.
        _logger.error(
            "Failed to decrypt a stored credential: the credential-encryption key "
            "(CASHPILOT_ENCRYPTION_KEY / %s) does not match the key this value was "
            "encrypted with. This is NOT a bad credential and NOT CASHPILOT_SECRET_KEY, "
            "which only signs sessions. Restore the original encryption key to recover, "
            "or re-enter the affected credentials.",
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
    -- USD per 1 unit of `currency` when this reading was taken (so USD rows store
    -- 1.0). Rates are only cached live, so without storing it here the historical
    -- value of a non-USD balance (MYST, GRASS, ...) cannot be reconstructed later at
    -- any accuracy — which is what a net-profit or tax export needs. NULL only when
    -- the rate was genuinely unavailable, never a guess.
    fx_rate_usd REAL,
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

-- Alerts worth a human's attention (collector failures today; container crashes and
-- earnings flatlines later). Persisted rather than kept in memory so they survive a
-- restart: passive income is unattended, and an alert that only exists in a running
-- process is an alert nobody ever sees.
CREATE TABLE IF NOT EXISTS alerts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT    NOT NULL,
    subject    TEXT    NOT NULL,
    message    TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
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

CREATE INDEX IF NOT EXISTS idx_earnings_date
    ON earnings (date);

CREATE INDEX IF NOT EXISTS idx_workers_status
    ON workers (status);

CREATE INDEX IF NOT EXISTS idx_health_events_slug
    ON health_events (slug, created_at);

CREATE INDEX IF NOT EXISTS idx_health_events_created
    ON health_events (created_at);

CREATE INDEX IF NOT EXISTS idx_alerts_created
    ON alerts (created_at);
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
        # In WAL mode NORMAL is durable across app crashes (only a power loss can lose
        # the last transactions) and skips an fsync on every commit — a large win on the
        # write-heavy health-check path that commits per service each cycle.
        await conn.execute("PRAGMA synchronous=NORMAL")
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

        # Migrate earnings table: add fx_rate_usd so a non-USD balance's value at the
        # time it was recorded stays reconstructable (rates are only cached live).
        cursor = await db.execute("PRAGMA table_info(earnings)")
        earnings_cols = {row["name"] for row in await cursor.fetchall()}
        if "fx_rate_usd" not in earnings_cols:
            await db.execute("ALTER TABLE earnings ADD COLUMN fx_rate_usd REAL")

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
    fx_rate_usd: float | None = None,
) -> None:
    """Insert or update an earnings record for a platform + date.

    ``fx_rate_usd`` is the currency -> USD rate at collection time. It is stored
    alongside the balance because exchange rates are only cached live: without it,
    the USD value of a historical non-USD reading cannot be reconstructed later.
    """
    date = date or datetime.now(UTC).strftime("%Y-%m-%d")
    db = await _get_db()
    try:
        # Insert a new reading, or update the existing platform+date row only
        # when the balance changed (we always want the latest reading). The
        # WHERE guard preserves created_at when the balance is unchanged.
        await db.execute(
            """
            INSERT INTO earnings (platform, balance, currency, date, fx_rate_usd)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(platform, date) DO UPDATE SET
                balance = excluded.balance,
                currency = excluded.currency,
                -- COALESCE, not a plain assignment: if the rate lookup failed this
                -- cycle (provider outage after a restart cleared the cache) the new
                -- value is NULL, and overwriting a known-good rate with it would
                -- destroy the very data this column exists to preserve.
                fx_rate_usd = COALESCE(excluded.fx_rate_usd, earnings.fx_rate_usd),
                created_at = datetime('now')
            -- The balance guard preserves created_at when nothing changed, but it also
            -- meant a row already stored with a NULL rate (written pre-upgrade, or when
            -- the rate was briefly unavailable) could never be back-filled: for a
            -- service whose balance moves once a day, every later run in that day was
            -- skipped entirely. Allow the update through in that one case.
            WHERE earnings.balance != excluded.balance
               OR earnings.fx_rate_usd IS NULL
            """,
            (platform, balance, currency, date, fx_rate_usd),
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
            # period="all": defensively cap the result so a very long-lived DB can't
            # return an unbounded row set into a single response/chart. Most-recent
            # first; 50k rows spans years of daily per-service earnings.
            cursor = await db.execute(
                "SELECT platform, balance, currency, date FROM earnings ORDER BY date DESC, platform LIMIT 50000"
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


async def record_health_events(events: list[tuple[str, str, str]]) -> None:
    """Record many health events in ONE transaction/commit.

    The health-check cycle writes one event per deployed service; committing each
    separately fsync'd the WAL up to ~49 times per cycle. One executemany + one commit
    collapses that to a single write — the dominant fix for that path's I/O.
    """
    if not events:
        return
    db = await _get_db()
    try:
        await db.executemany(
            "INSERT INTO health_events (slug, event, detail) VALUES (?, ?, ?)",
            events,
        )
        await db.commit()
    finally:
        await db.close()


# How long a subject stays quiet after alerting. A collector broken for a week must
# not notify every hour: the first failure is news, the 168th is noise.
ALERT_COOLDOWN_HOURS = 24


async def record_alert(
    kind: str,
    subject: str,
    message: str,
    *,
    cooldown_hours: int = ALERT_COOLDOWN_HOURS,
) -> bool:
    """Persist an alert, returning True only when the caller should notify.

    Suppression is by TIME WINDOW per kind+subject, not by message equality. Message
    equality alone is not enough: several collectors alternate between two error
    strings for the same underlying fault (grass flips between an expired-token error
    and a Cloudflare rate-limit depending on which request tripped first), so a
    "changed message means new" rule would notify every single hour and grow the
    table without bound — exactly what this is meant to prevent.

    Nothing is stored while a subject is in cooldown, which keeps the table bounded.
    Call ``clear_alerts`` when a subject recovers so the next failure alerts again
    immediately instead of waiting out the window.
    """
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT id FROM alerts WHERE kind = ? AND subject = ? AND created_at > datetime('now', ?) LIMIT 1",
            (kind, subject, f"-{int(cooldown_hours)} hours"),
        )
        if await cursor.fetchone() is not None:
            return False
        await db.execute(
            "INSERT INTO alerts (kind, subject, message) VALUES (?, ?, ?)",
            (kind, subject, message),
        )
        await db.commit()
        return True
    finally:
        await db.close()


async def list_alerts(limit: int = 50) -> list[dict[str, Any]]:
    """Return the most recent alerts, newest first."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT kind, subject, message, created_at FROM alerts ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in await cursor.fetchall()]
    finally:
        await db.close()


async def clear_alerts(kind: str | None = None, subject: str | None = None) -> None:
    """Drop stored alerts (all, one kind, or one subject within a kind).

    Called when a subject recovers, so that if it breaks again later the failure
    counts as new and notifies again instead of being deduped into silence.
    """
    clauses, params = [], []
    if kind is not None:
        clauses.append("kind = ?")
        params.append(kind)
    if subject is not None:
        clauses.append("subject = ?")
        params.append(subject)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    db = await _get_db()
    try:
        await db.execute(f"DELETE FROM alerts{where}", tuple(params))  # noqa: S608 - clauses are literals
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
        # Alerts are deduped on write so the table stays small, but a service that
        # was removed long ago should not leave its last failure sitting there forever.
        c4 = await db.execute(
            "DELETE FROM alerts WHERE created_at < datetime('now', ?)",
            (cutoff,),
        )
        await db.commit()
        return (c1.rowcount or 0) + (c2.rowcount or 0) + (c3.rowcount or 0) + (c4.rowcount or 0)
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
