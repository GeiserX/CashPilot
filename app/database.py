"""SQLite database layer for CashPilot.

Stores earnings history, user configuration, and deployment records.
DB file lives at /data/cashpilot.db (Docker volume mount) with a local
fallback to ./data/cashpilot.db for development.
"""

from __future__ import annotations

import os
from datetime import datetime
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

CREATE TABLE IF NOT EXISTS nodes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    token_hash      TEXT    NOT NULL UNIQUE,
    ip              TEXT    NOT NULL DEFAULT '',
    os              TEXT    NOT NULL DEFAULT '',
    arch            TEXT    NOT NULL DEFAULT '',
    docker_version  TEXT    NOT NULL DEFAULT '',
    docker_mode     TEXT    NOT NULL DEFAULT 'unknown',
    role            TEXT    NOT NULL DEFAULT 'child',
    status          TEXT    NOT NULL DEFAULT 'pending',
    last_seen       TEXT,
    registered_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_earnings_platform_date
    ON earnings (platform, date);

CREATE INDEX IF NOT EXISTS idx_nodes_status
    ON nodes (status);
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


# --- Nodes (Federation) ---


async def register_node(
    name: str,
    token_hash: str,
    ip: str = "",
    os_info: str = "",
    arch: str = "",
    docker_version: str = "",
    docker_mode: str = "unknown",
) -> int:
    """Register a new child node. Returns the new node ID."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            INSERT INTO nodes (name, token_hash, ip, os, arch, docker_version, docker_mode, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'online')
            """,
            (name, token_hash, ip, os_info, arch, docker_version, docker_mode),
        )
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def get_node_by_token_hash(token_hash: str) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM nodes WHERE token_hash = ?", (token_hash,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_node(node_id: int) -> dict[str, Any] | None:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def list_nodes() -> list[dict[str, Any]]:
    db = await _get_db()
    try:
        cursor = await db.execute("SELECT * FROM nodes ORDER BY name")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def update_node_heartbeat(
    node_id: int,
    ip: str = "",
    os_info: str = "",
    arch: str = "",
    docker_version: str = "",
    docker_mode: str = "unknown",
) -> None:
    """Update a node's last_seen timestamp and system info."""
    db = await _get_db()
    try:
        await db.execute(
            """
            UPDATE nodes
            SET last_seen = datetime('now'), status = 'online',
                ip = ?, os = ?, arch = ?, docker_version = ?, docker_mode = ?
            WHERE id = ?
            """,
            (ip, os_info, arch, docker_version, docker_mode, node_id),
        )
        await db.commit()
    finally:
        await db.close()


async def set_node_status(node_id: int, status: str) -> None:
    db = await _get_db()
    try:
        await db.execute("UPDATE nodes SET status = ? WHERE id = ?", (status, node_id))
        await db.commit()
    finally:
        await db.close()


async def delete_node(node_id: int) -> None:
    db = await _get_db()
    try:
        await db.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        await db.commit()
    finally:
        await db.close()
