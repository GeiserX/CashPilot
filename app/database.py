"""SQLite database layer for CashPilot.

Stores earnings history, user configuration, and deployment records.
DB file lives at /data/cashpilot.db (Docker volume mount) with a local
fallback to ./data/cashpilot.db for development.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

DB_DIR = Path(os.getenv("CASHPILOT_DATA_DIR", "/data"))
DB_PATH = DB_DIR / "cashpilot.db"

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
    name            TEXT    NOT NULL UNIQUE,
    url             TEXT    NOT NULL DEFAULT '',
    status          TEXT    NOT NULL DEFAULT 'online',
    containers      TEXT    NOT NULL DEFAULT '[]',
    system_info     TEXT    NOT NULL DEFAULT '{}',
    last_heartbeat  TEXT,
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

CREATE UNIQUE INDEX IF NOT EXISTS idx_earnings_platform_date
    ON earnings (platform, date);

CREATE INDEX IF NOT EXISTS idx_workers_status
    ON workers (status);

CREATE INDEX IF NOT EXISTS idx_health_events_slug
    ON health_events (slug, created_at);
"""


async def _get_db() -> aiosqlite.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    return db


async def init_db() -> None:
    """Create tables if they don't exist."""
    db = await _get_db()
    try:
        await db.executescript(_SCHEMA)
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
    date = date or datetime.utcnow().strftime("%Y-%m-%d")
    db = await _get_db()
    try:
        await db.execute(
            """
            INSERT INTO earnings (platform, balance, currency, date)
            VALUES (?, ?, ?, ?)
            ON CONFLICT DO NOTHING
            """,
            (platform, balance, currency, date),
        )
        # Update if there is already a record for this platform+date with a
        # different balance (we always want the latest reading).
        await db.execute(
            """
            UPDATE earnings SET balance = ?, currency = ?, created_at = datetime('now')
            WHERE platform = ? AND date = ? AND balance != ?
            """,
            (balance, currency, platform, date, balance),
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
        today = datetime.utcnow().strftime("%Y-%m-%d")
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        first_of_month = datetime.utcnow().replace(day=1).strftime("%Y-%m-%d")

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
        day_before = (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%d")
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
        now = datetime.utcnow()
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
    """Get a single config value (if key given) or all config as a dict."""
    db = await _get_db()
    try:
        if key:
            cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
            row = await cursor.fetchone()
            return row["value"] if row else None
        cursor = await db.execute("SELECT key, value FROM config")
        rows = await cursor.fetchall()
        return {r["key"]: r["value"] for r in rows}
    finally:
        await db.close()


async def set_config(key: str, value: str) -> None:
    """Upsert a config key-value pair."""
    db = await _get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (key, value),
        )
        await db.commit()
    finally:
        await db.close()


async def set_config_bulk(data: dict[str, str]) -> None:
    """Upsert multiple config entries at once."""
    db = await _get_db()
    try:
        await db.executemany(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            list(data.items()),
        )
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
    name: str,
    url: str = "",
    containers: str = "[]",
    system_info: str = "{}",
) -> int:
    """Register or update a worker by name. Returns the worker ID."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            INSERT INTO workers (name, url, containers, system_info, status, last_heartbeat)
            VALUES (?, ?, ?, ?, 'online', datetime('now'))
            ON CONFLICT(name) DO UPDATE SET
                url = excluded.url,
                containers = excluded.containers,
                system_info = excluded.system_info,
                status = 'online',
                last_heartbeat = datetime('now')
            """,
            (name, url, containers, system_info),
        )
        await db.commit()
        # Return the worker ID (either new or existing)
        cursor = await db.execute("SELECT id FROM workers WHERE name = ?", (name,))
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


async def get_worker_by_name(name: str) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM workers WHERE name = ?", (name,))
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
