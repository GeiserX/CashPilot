"""Adding a service is a button in the top bar, not the last tab.

The setup wizard is how a service gets added, and it sat at the end of the tab
row after Settings, shrunk to "Add" on a phone. It is now a primary button on
the right of the bar, on every page, and the dashboard no longer repeats it.
Only the owner can deploy (/api/deploy is owner-only), so only the owner gets
the button; writers and viewers keep a plain Setup tab to the same wizard.
"""

from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest
from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
PAGES = ["/", "/catalog", "/fleet", "/setup"]


@asynccontextmanager
async def _noop_lifespan(a):
    yield


app.router.lifespan_context = _noop_lifespan


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _as(role: str):
    return patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": role, "r": role})


def _section(html: str, start: str, end: str) -> str:
    i = html.index(start)
    return html[i : html.index(end, i)]


def _bar(client, role: str, page: str) -> tuple[str, str]:
    with _as(role):
        resp = client.get(page)
    assert resp.status_code == 200
    html = resp.text
    nav = _section(html, '<nav class="topnav"', "</nav>")
    right = _section(html, '<div class="topbar-right">', '<div class="topbar-earnings"')
    return nav, right


@pytest.mark.parametrize("page", PAGES)
def test_the_owner_gets_the_add_button_not_a_tab(client, page):
    nav, right = _bar(client, "owner", page)
    assert 'href="/setup"' not in nav, "Add services is still a tab"
    button = re.search(r'<a href="/setup" class="([^"]*)"[^>]*>', right)
    assert button, "no Add service button next to the balance"
    assert {"btn", "btn-primary", "topbar-add"} <= set(button.group(1).split())
    assert 'data-key="a"' in button.group(0)
    assert 'aria-label="Add service"' in button.group(0)


@pytest.mark.parametrize("role", ["writer", "viewer"])
@pytest.mark.parametrize("page", PAGES)
def test_others_get_no_add_button_but_still_reach_setup(client, role, page):
    nav, right = _bar(client, role, page)
    assert "/setup" not in right, f"{role} sees an Add button for a deploy they cannot do"
    assert "topbar-add" not in right
    tab = re.search(r'<a href="/setup" class="sidebar-link[^"]*" data-key="a">Setup</a>', nav)
    assert tab, f"{role} lost the way to /setup"


def test_the_button_is_marked_current_on_setup(client):
    with _as("owner"):
        setup = client.get("/setup").text
        catalog = client.get("/catalog").text
    assert re.search(r'class="[^"]*topbar-add active"[^>]*aria-current="page"', setup)
    assert "aria-current" not in _section(catalog, '<div class="topbar-right">', '<div class="topbar-earnings"')


def test_the_dashboard_does_not_repeat_it(client):
    with _as("owner"):
        html = client.get("/").text
    assert html.count('href="/setup"') == 1


def test_the_g_a_shortcut_still_finds_it():
    # The shortcut looked only inside .topnav; the button now lives outside it.
    app_js = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert '.topbar a[data-key="${CSS.escape(e.key)}"]' in app_js
