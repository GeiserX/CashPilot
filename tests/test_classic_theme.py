"""Classic night: the default theme, next to dark and light in the avatar menu.

Anyone who never chose a theme (user_preferences.theme NULL, a new install, a
browser with nothing saved on the sign-in pages) gets Classic. An explicit dark
or light stays.

The choice is saved per user on the server and rendered into <html data-theme>
on every signed-in page, then mirrored into localStorage 'cp-theme' for the
sign-in pages. The browser-side behaviour (pre-paint, the picker) runs in
scripts/theme_check.mjs; this file covers the server and the markup.
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


def _html_theme(html):
    m = re.search(r"<html[^>]*>", html)
    t = re.search(r'data-theme="([^"]*)"', m.group(0))
    return t and t.group(1)


@pytest.mark.parametrize("role", ["owner", "writer", "viewer"])
def test_every_role_gets_the_three_way_picker(real_db, role):
    user = {"uid": real_db, "u": "classic_user", "r": role}
    with patch("app.main.auth.get_current_user", return_value=user), TestClient(app) as c:
        html = c.get("/").text
    assert re.findall(r'data-theme-choice="(\w+)"', html) == ["classic", "dark", "light"]
    assert re.search(r'data-theme-choice="classic"[^>]*>Classic \(default\)<', html)


def test_signed_in_page_paints_the_saved_theme(real_db):
    user = {"uid": real_db, "u": "classic_user", "r": "viewer"}
    with patch("app.main.auth.get_current_user", return_value=user), TestClient(app) as c:
        assert c.get("/api/preferences").json()["theme"] is None
        for page in ("/", "/fleet", "/catalog", "/setup"):
            assert _html_theme(c.get(page).text) == "classic", page  # never chosen: the default


@pytest.mark.parametrize("choice", ["dark", "light", "classic"])
def test_an_explicit_choice_stays(real_db, choice):
    """A user who picked dark or light keeps it; only NULL gets the default."""
    user = {"uid": real_db, "u": "classic_user", "r": "owner"}  # owner: every page renders
    with patch("app.main.auth.get_current_user", return_value=user), TestClient(app) as c:
        assert c.post("/api/preferences", json={"theme": choice}).status_code == 200
        for page in ("/", "/fleet", "/catalog", "/payouts", "/settings", "/setup"):
            assert _html_theme(c.get(page).text) == choice, page


def test_an_unknown_stored_theme_falls_back_to_classic(real_db):
    """A value outside THEMES (hand-edited row) paints the default, not nothing."""
    asyncio.run(database.save_user_preferences(real_db, theme="sepia"))
    user = {"uid": real_db, "u": "classic_user", "r": "viewer"}
    with patch("app.main.auth.get_current_user", return_value=user), TestClient(app) as c:
        assert _html_theme(c.get("/").text) == "classic"


def test_next_user_on_the_same_browser_gets_their_own_theme(real_db):
    """An owner picks Light; a viewer who never chose signs in on that browser.

    The browser still holds 'cp-theme' = light. The viewer's pages must say
    classic on <html>, which the pre-paint script prefers over the stored key
    (scripts/theme_check.mjs proves that half), so the viewer is never left in
    someone else's theme.
    """
    owner_id = asyncio.run(database.create_user("the_owner", "pw", "owner"))
    asyncio.run(database.save_user_preferences(owner_id, theme="light"))
    viewer = {"uid": real_db, "u": "classic_user", "r": "viewer"}
    with patch("app.main.auth.get_current_user", return_value=viewer), TestClient(app) as c:
        assert _html_theme(c.get("/").text) == "classic"


def test_partial_update_writes_only_the_fields_sent(real_db):
    """A theme save must not rewrite the wizard's fields, and the reverse.

    The old save read every field and wrote them all back, so a theme click
    racing the wizard's step-4 POST could put setup_completed back to 0. Here
    the "stale" writer is simulated directly: a theme-only save after another
    writer set setup_completed must leave it set.
    """
    asyncio.run(database.save_user_preferences(real_db, setup_mode="mixed", timezone="Europe/Madrid"))
    asyncio.run(database.save_user_preferences(real_db, setup_completed=True))
    asyncio.run(database.save_user_preferences(real_db, theme="classic"))
    prefs = asyncio.run(database.get_user_preferences(real_db))
    assert (prefs["setup_mode"], prefs["timezone"], prefs["setup_completed"], prefs["theme"]) == (
        "mixed",
        "Europe/Madrid",
        1,
        "classic",
    )


def test_theme_click_does_not_reset_setup_completed(client):
    """The API path of the same race: it must not read and write back."""
    real_get = database.get_user_preferences

    async def stale_read(uid):
        # What a read taken before the wizard's POST landed would see.
        prefs = await real_get(uid)
        return {**(prefs or {}), "setup_completed": 0}

    client.post("/api/preferences", json={"setup_completed": True})
    with patch.object(database, "get_user_preferences", stale_read):
        client.post("/api/preferences", json={"theme": "light"})
    prefs = client.get("/api/preferences").json()
    assert (prefs["setup_completed"], prefs["theme"]) == (1, "light")


def test_schema_version_counts_the_theme_column():
    assert database.SCHEMA_VERSION == 14


def test_classic_success_hover_stays_white_but_not_on_claim_icons():
    css = (ROOT / "app/static/css/style.css").read_text()
    block = css[css.index(':root[data-theme="classic"] {') :]
    rule = re.search(r"\.btn-success([^{]*):hover:not\(:disabled\)\s*\{([^}]*)\}", block)
    assert rule, "Classic has no .btn-success hover, so it takes the rose --accent-hover"
    assert ":not(.btn-icon)" in rule.group(1), "the claim $ icon buttons would turn white too"
    assert "accent" not in rule.group(2)
