"""The dashboard's own script and stylesheet carry the release in their URL.

app.js is served with an ETag and no Cache-Control, so a browser applies
heuristic freshness: a file last modified a day ago is reused for hours without
asking the server. After the v1.36.8 upgrade a tab that had loaded the dashboard
the day before kept running the old app.js, and the bug that release fixed
looked unfixed. A `?v=<release>` on the reference is a new URL per release, so
the old cache entry is never consulted.
"""

import gzip
import re
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.deps import templates
from app.main import app
from tests.test_main_routes import _auth_owner  # importing it also installs the no-op lifespan

_OWN_ASSETS = ("/static/css/style.css", "/static/js/app.js", "/static/js/delegate.js")


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _rendered_references(html: str) -> dict[str, str]:
    """Map each of our asset paths to the exact URL the page references it by."""
    found = {}
    for path in _OWN_ASSETS:
        m = re.search(r'(?:src|href)="(' + re.escape(path) + r'[^"]*)"', html)
        assert m, f"the dashboard no longer references {path}"
        found[path] = m.group(1)
    return found


class TestTheDashboardReferencesVersionedAssets:
    def test_each_own_asset_carries_the_running_release(self, client):
        with _auth_owner(), patch.dict(templates.env.globals, {"app_version": lambda: "v9.8.7"}):
            resp = client.get("/")
        assert resp.status_code == 200
        for path, url in _rendered_references(resp.text).items():
            assert url == f"{path}?v=v9.8.7", f"{path} is referenced as {url}"

    def test_a_new_release_is_a_new_url(self, client):
        """The whole point: the URL changes when the release does."""
        urls = {}
        for release in ("v1.0.0", "v1.0.1"):
            with _auth_owner(), patch.dict(templates.env.globals, {"app_version": lambda release=release: release}):
                urls[release] = _rendered_references(client.get("/").text)["/static/js/app.js"]
        assert urls["v1.0.0"] != urls["v1.0.1"]

    def test_the_template_has_no_bare_reference_left(self):
        """Guards the template itself, so a later edit cannot drop the query on one tag."""
        from pathlib import Path

        html = Path(__file__).resolve().parents[1].joinpath("app", "templates", "base.html").read_text(encoding="utf-8")
        for path in _OWN_ASSETS:
            bare = re.findall(r'(?:src|href)="' + re.escape(path) + r'"', html)
            assert not bare, f"{path} is referenced without ?v= in base.html"


class TestStaticAssetsAreCheapToLoad:
    """app.js and style.css are about 366 KB raw, and were sent uncompressed and
    revalidated on every navigation."""

    def test_a_versioned_asset_is_cached_for_good(self, client, monkeypatch):
        monkeypatch.setenv("CASHPILOT_VERSION", "9.8.7")
        r = client.get("/static/js/app.js?v=v9.8.7")
        assert r.status_code == 200
        assert r.headers.get("cache-control") == "public, max-age=31536000, immutable"

    @pytest.mark.parametrize(
        ("running", "asked"),
        [
            # A source build renders ?v=dev on every rebuild: the URL never changes.
            ("", "dev"),
            ("dev", "dev"),
            # Another release's URL is not this build's file.
            ("9.8.7", "v9.8.6"),
        ],
    )
    def test_only_the_running_release_is_cached_for_good(self, client, monkeypatch, running, asked):
        monkeypatch.setenv("CASHPILOT_VERSION", running)
        r = client.get(f"/static/js/app.js?v={asked}")
        assert r.status_code == 200
        assert "immutable" not in (r.headers.get("cache-control") or "")

    def test_an_unversioned_reference_still_revalidates(self, client):
        # auth.html and onboarding.html reference style.css without ?v=.
        r = client.get("/static/css/style.css")
        assert r.status_code == 200
        assert "immutable" not in (r.headers.get("cache-control") or "")

    def test_assets_are_gzipped_for_a_client_that_accepts_it(self, client):
        raw = client.get("/static/js/app.js", headers={"Accept-Encoding": "identity"})
        assert raw.headers.get("content-encoding") is None
        with client.stream("GET", "/static/js/app.js", headers={"Accept-Encoding": "gzip"}) as gz:
            assert gz.headers.get("content-encoding") == "gzip"
            sent = b"".join(gz.iter_raw())
        assert len(sent) < len(raw.content) / 2
        assert gzip.decompress(sent) == raw.content

    def test_pages_are_not_gzipped(self, client):
        # Compression stays on /static: a page holds a CSRF token beside reflected input.
        r = client.get("/login", headers={"Accept-Encoding": "gzip"})
        assert r.headers.get("content-encoding") is None
