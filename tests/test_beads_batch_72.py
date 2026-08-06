"""CashPilot-yhkl: the sidebar never highlighted the page you were on.

Every link in base.html renders `{% if active_page == 'x' %}active{% endif %}`
and `.sidebar-link.active` is styled (style.css). But nothing ever SET
`active_page` -- not the routes, which pass only {"user": user}, not a Jinja
global, and no JS added the class at runtime. So the comparison was always
false and the highlight was dead on every page, for every user.

Fixed by deriving it in base.html from the `page` block each child already
declares for <body data-page>, rather than making every route pass a second
copy of the same string.

These assertions read the RENDERED OUTPUT. A test that the template contains
"active_page" would have passed happily for as long as this bug existed.
"""

from __future__ import annotations

import re
from unittest.mock import patch

import pytest


def _client():
    """Not a context manager: entering it runs the lifespan, which installs a
    SIGHUP handler, and signal() raises "only works in main thread" under
    pytest. These tests only need routing and template rendering."""
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


def _active_links(body: str) -> list[str]:
    return [
        href
        for href, cls in re.findall(r'<a href="([^"]+)" class="sidebar-link ([^"]*)"', body)
        if "active" in cls.split()
    ]


OWNER = {"u": "sergio", "r": "owner"}


@pytest.mark.parametrize(
    ("path", "expected"),
    [("/", "/"), ("/catalog", "/catalog"), ("/settings", "/settings"), ("/fleet", "/fleet")],
)
def test_the_current_page_is_the_one_highlighted(path, expected):
    client = _client()
    with patch("app.main.auth.get_current_user", return_value=OWNER):
        body = client.get(path).text
    assert _active_links(body) == [expected]


def test_exactly_one_link_is_ever_active():
    """Two highlighted links would be as useless as none."""
    client = _client()
    for path in ("/", "/catalog", "/settings", "/fleet"):
        with patch("app.main.auth.get_current_user", return_value=OWNER):
            body = client.get(path).text
        assert len(_active_links(body)) == 1, f"{path} highlighted {_active_links(body)}"


def test_control_a_page_does_not_highlight_a_different_one():
    """The negative control. If /catalog also marked /fleet active, the tests
    above could still pass on a template that highlights everything."""
    client = _client()
    with patch("app.main.auth.get_current_user", return_value=OWNER):
        body = client.get("/catalog").text
    assert "/fleet" not in _active_links(body)
    assert "/settings" not in _active_links(body)
