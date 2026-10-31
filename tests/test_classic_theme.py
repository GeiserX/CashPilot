"""Classic night: a third theme, chosen in Settings > Appearance.

The choice is saved per user on the server, so it follows the user to a new
browser, and mirrored into localStorage 'cp-theme' for the pre-paint script.
The browser-side behaviour (pre-paint key, the sun/moon rule, the server
winning on a new device) runs in scripts/theme_check.mjs; this file covers the
server and the markup.
"""

from __future__ import annotations

import asyncio
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import app

ROOT = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def _noop_lifespan(a):
    yield


app.router.lifespan_context = _noop_lifespan


@pytest.fixture
def real_db(tmp_path):
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"),
    ):
        asyncio.run(database.init_db())
        uid = asyncio.run(database.create_user("classic_user", "pw", "viewer"))
        yield uid


@pytest.fixture
def client(real_db):
    user = {"uid": real_db, "u": "classic_user", "r": "viewer"}
    with (
        patch("app.main.auth.get_current_user", return_value=user),
        TestClient(app, raise_server_exceptions=False) as c,
    ):
        yield c


class TestPreferenceRoundTrip:
    def test_unset_theme_is_null(self, client):
        assert client.get("/api/preferences").json()["theme"] is None

    def test_saved_theme_comes_back(self, client):
        assert client.post("/api/preferences", json={"theme": "classic"}).status_code == 200
        assert client.get("/api/preferences").json()["theme"] == "classic"

    def test_other_fields_keep_the_theme(self, client):
        client.post("/api/preferences", json={"theme": "classic"})
        client.post("/api/preferences", json={"timezone": "Europe/Madrid"})
        prefs = client.get("/api/preferences").json()
        assert prefs["theme"] == "classic"
        assert prefs["timezone"] == "Europe/Madrid"

    def test_theme_keeps_the_other_fields(self, client):
        client.post("/api/preferences", json={"setup_mode": "monitoring", "setup_completed": True})
        client.post("/api/preferences", json={"theme": "light"})
        prefs = client.get("/api/preferences").json()
        assert (prefs["setup_mode"], prefs["setup_completed"], prefs["theme"]) == ("monitoring", 1, "light")

    def test_unknown_theme_is_refused(self, client):
        assert client.post("/api/preferences", json={"theme": "sepia"}).status_code == 400
        assert client.get("/api/preferences").json()["theme"] is None


def _pref_columns(path):
    conn = sqlite3.connect(path)
    try:
        return {r[1]: (r[2], r[3], r[4]) for r in conn.execute("PRAGMA table_info(user_preferences)")}
    finally:
        conn.close()


def test_fresh_and_upgraded_installs_get_the_same_column(tmp_path):
    fresh = tmp_path / "fresh.db"
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.execute(
        "CREATE TABLE user_preferences (user_id INTEGER PRIMARY KEY, setup_mode TEXT NOT NULL DEFAULT 'fresh', "
        "selected_categories TEXT NOT NULL DEFAULT '[]', timezone TEXT NOT NULL DEFAULT 'UTC', "
        "setup_completed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (datetime('now')), "
        "updated_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.commit()
    conn.close()
    for path in (fresh, old):
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", path):
            asyncio.run(database.init_db())
    assert _pref_columns(fresh)["theme"] == ("TEXT", 0, None)
    assert _pref_columns(old)["theme"] == _pref_columns(fresh)["theme"]


def test_settings_offers_the_three_themes(real_db):
    # Settings is owner-only; the preference API itself is open to every user.
    owner = {"uid": real_db, "u": "classic_user", "r": "owner"}
    with patch("app.main.auth.get_current_user", return_value=owner), TestClient(app) as c:
        html = c.get("/settings").text
    values = re.findall(r'<input type="radio" name="cp-theme" value="(\w+)"', html)
    assert values == ["dark", "light", "classic"]


def test_classic_hides_the_sun_moon_item():
    css = (ROOT / "app/static/css/style.css").read_text()
    rule = re.search(r':root\[data-theme="classic"\] #theme-toggle[^{]*\{([^}]*)\}', css)
    assert rule and "display: none" in rule.group(1)
