"""The Add a box block on the fleet page: what a second server needs to join."""

from __future__ import annotations

from pathlib import Path

from app import deps

FLEET = Path(__file__).resolve().parents[1] / "app" / "templates" / "fleet.html"


def _add_box_text() -> str:
    """The first paragraph of Add a box, rendered with the real template globals."""
    html = FLEET.read_text(encoding="utf-8")
    start = html.index('<p class="add-worker-text">', html.index('id="add-worker"'))
    return deps.templates.env.from_string(html[start : html.index("</p>", start)]).render()


def test_the_worker_image_carries_this_uis_series(monkeypatch):
    monkeypatch.setenv("CASHPILOT_VERSION", "3.0.1")
    assert deps.templates.env.globals["worker_image"]() == "drumsergio/cashpilot-worker:3.0"
    assert "Deploy <code>drumsergio/cashpilot-worker:3.0</code> on each server" in _add_box_text()


def test_a_dev_build_names_no_tag_as_if_it_were_published(monkeypatch):
    """No release version means no published tag: the page says to pick one."""
    monkeypatch.delenv("CASHPILOT_VERSION", raising=False)
    assert deps.templates.env.globals["worker_image"]() is None
    text = _add_box_text()
    assert "This build has no" in text and "replaced by a published release" in text
    assert "<code>drumsergio/cashpilot-worker</code>" not in text
    assert ":latest" not in text


def test_the_key_note_says_where_the_key_comes_from():
    """The key is often generated in /fleet, with CASHPILOT_API_KEY empty."""
    html = FLEET.read_text(encoding="utf-8")
    assert "The API key is set via" not in html
    assert "/fleet/.fleet_key" in html


def test_a_loopback_origin_is_not_offered_as_the_ui_url():
    html = FLEET.read_text(encoding="utf-8")
    assert "document.getElementById('env-ui-url').textContent = window.location.origin;" not in html
    assert "<this-server-address>" in html
    assert 'id="env-ui-url-loopback"' in html
    assert "CASHPILOT_BIND_ADDR" in html
