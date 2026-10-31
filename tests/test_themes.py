"""The built-in themes: one list (app/themes.json) for the server, the
validation, the picker and the browser checks.

The browser-side behaviour (pre-paint fallback, the picker's clicks) runs in
scripts/theme_check.mjs; this file covers the server, the markup and the rule
that a theme is one list entry plus one CSS block and swatch.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest
from fastapi.testclient import TestClient

from app import database, themes
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "app/themes.json").read_text())
IDS = [t["id"] for t in SPEC["themes"]]
CSS = (ROOT / "app/static/css/style.css").read_text()


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
        yield asyncio.run(database.create_user("theme_user", "pw", "viewer"))


def _client(uid, role="viewer"):
    user = {"uid": uid, "u": "theme_user", "r": role}
    return patch("app.main.auth.get_current_user", return_value=user), TestClient(app, raise_server_exceptions=False)


def _html_theme(html):
    m = re.search(r'<html[^>]*\bdata-theme="([^"]*)"', html)
    return m and m.group(1)


def test_the_five_built_in_themes_with_classic_night_the_default():
    assert [(t["id"], t["label"]) for t in SPEC["themes"]] == [
        ("classic", "Classic night"),
        ("dark", "Dark"),
        ("light", "Light"),
        ("sunrise", "Sunrise"),
        ("warm", "Warm"),
    ]
    assert SPEC["default"] == "classic"


def test_server_and_validation_read_the_one_list():
    assert list(themes.THEMES) == IDS
    assert database.THEMES is themes.THEMES
    assert database.DEFAULT_THEME == themes.DEFAULT_THEME
    assert SPEC["default"] == themes.DEFAULT_THEME


@pytest.mark.parametrize("theme", IDS)
def test_each_theme_round_trips_and_paints(real_db, theme):
    p, c = _client(real_db)
    with p, c:
        assert c.post("/api/preferences", json={"theme": theme}).status_code == 200
        assert c.get("/api/preferences").json()["theme"] == theme
        for page in ("/", "/fleet", "/catalog", "/setup"):
            assert _html_theme(c.get(page).text) == theme, page


@pytest.mark.parametrize("bad", ["sepia", "Sunrise", "WARM", "", "dark ", "<script>"])
def test_an_unknown_theme_is_refused(real_db, bad):
    p, c = _client(real_db)
    with p, c:
        c.post("/api/preferences", json={"theme": "warm"})
        r = c.post("/api/preferences", json={"theme": bad})
        assert r.status_code == 400
        assert c.get("/api/preferences").json()["theme"] == "warm"


def test_an_old_or_unknown_stored_value_paints_the_default(real_db):
    """A value written before a theme was removed, or by hand, is not a theme."""
    asyncio.run(database.save_user_preferences(real_db, theme="neon"))
    p, c = _client(real_db)
    with p, c:
        assert _html_theme(c.get("/").text) == SPEC["default"]


def test_never_chosen_paints_the_default(real_db):
    p, c = _client(real_db)
    with p, c:
        assert _html_theme(c.get("/").text) == SPEC["default"]


@pytest.mark.parametrize("role", ["owner", "writer", "viewer"])
def test_every_role_gets_the_picker_with_every_theme_and_a_swatch(real_db, role):
    p, c = _client(real_db, role)
    with p, c:
        html = c.get("/").text
    picker = html[html.index('class="avatar-theme-options"') :]
    picker = picker[: picker.index("</div>")]
    buttons = re.findall(r'<button[^>]*data-theme-choice="(\w+)"[^>]*>(.*?)</button>', picker, re.S)
    assert [b[0] for b in buttons] == IDS
    for tid, inner in buttons:
        assert f'class="theme-swatch" data-swatch="{tid}"' in inner, tid
    labels = {tid: re.sub(r"<[^>]+>", "", inner).strip() for tid, inner in buttons}
    assert labels == {
        t["id"]: t["label"] + (" (default)" if t["id"] == SPEC["default"] else "") for t in SPEC["themes"]
    }


@pytest.mark.parametrize("theme", IDS)
def test_every_theme_in_the_list_has_a_css_block_and_a_swatch(theme):
    """One entry in app/themes.json, one CSS block, one swatch: nothing else.

    Dark is the stylesheet's base (:root), so it needs no block of its own.
    """
    if theme != "dark":
        assert f':root[data-theme="{theme}"] {{' in CSS, f"{theme} has no CSS block"
    assert re.search(rf'\.theme-swatch\[data-swatch="{theme}"\]\s*\{{[^}}]*background', CSS), f"{theme} has no swatch"


def test_no_css_block_or_swatch_for_a_theme_that_is_not_in_the_list():
    blocks = set(re.findall(r':root\[data-theme="(\w+)"\]\s*\{', CSS))
    swatches = set(re.findall(r'\.theme-swatch\[data-swatch="(\w+)"\]', CSS))
    assert blocks <= set(IDS), blocks - set(IDS)
    assert swatches == set(IDS)


def test_no_template_or_script_keeps_its_own_theme_list():
    """The ids live in app/themes.json only; a second copy is how lists drift."""
    pattern = re.compile(r"""\[\s*['"](?:dark|light|classic)['"]\s*,\s*['"](?:dark|light|classic)['"]""")
    pattern_py = re.compile(r"""\(\s*['"](?:dark|light|classic)['"]\s*,\s*['"](?:dark|light|classic)['"]""")
    paths = [*ROOT.glob("app/**/*.py"), *ROOT.glob("app/templates/*.html"), ROOT / "app/static/js/app.js"]
    paths += [
        ROOT / f"scripts/{n}.mjs" for n in ("theme_check", "legibility_check", "fleet_overflow_check", "ui_screenshots")
    ]
    hits = [
        str(p.relative_to(ROOT)) for p in paths if pattern.search(p.read_text()) or pattern_py.search(p.read_text())
    ]
    assert hits == []


def _top_level_split(selector):
    """Split a selector list on the commas outside :is()/:where()/:not()."""
    parts, depth, cur = [], 0, ""
    for ch in selector:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return [*parts, cur.strip()]


def test_sunrise_and_warm_scope_their_rules_to_their_own_theme():
    """No new rule may leak into another theme (the doc's draft used :root:not(light))."""
    for theme in ("sunrise", "warm"):
        start = CSS.index(f"/* ----- {theme.capitalize()} -----")
        end = CSS.find("/* ----- ", start + 10)
        block = CSS[start : end if end > 0 else len(CSS)]
        for sel in re.findall(r"^([^\s/*}][^{]*)\{", block, re.M):
            for part in _top_level_split(sel):
                assert part.startswith(
                    (f':root[data-theme="{theme}"]', f':where(:root[data-theme="{theme}"])', ".theme-swatch")
                ), part
