"""The Add a box block on the fleet page: what a second server needs to join."""

from __future__ import annotations

from pathlib import Path

from app import deps

FLEET = Path(__file__).resolve().parents[1] / "app" / "templates" / "fleet.html"


def test_the_worker_image_carries_this_uis_series(monkeypatch):
    monkeypatch.setenv("CASHPILOT_VERSION", "3.0.1")
    assert deps.templates.env.globals["worker_image"]() == "drumsergio/cashpilot-worker:3.0"


def test_a_dev_build_never_names_an_unpinned_image(monkeypatch):
    monkeypatch.delenv("CASHPILOT_VERSION", raising=False)
    image = deps.templates.env.globals["worker_image"]()
    assert ":" in image and not image.endswith(":latest")


def test_the_page_names_the_pinned_image():
    html = FLEET.read_text(encoding="utf-8")
    assert "<code>{{ worker_image() }}</code>" in html
    assert "<code>drumsergio/cashpilot-worker</code>" not in html


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
