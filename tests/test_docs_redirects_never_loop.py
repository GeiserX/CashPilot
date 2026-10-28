"""The Service guides page reloaded itself forever (issue #465).

``guides/README.md: guides/index.md`` in the redirects plugin looks like a
rename, but MkDocs publishes a folder's ``README.md`` and ``index.md`` at the
same URL, ``guides/``. The plugin wrote its redirect page there, over the real
index, and the page sent the browser to ``./``: itself. Every link to the guide
list (the README, the docs nav, the app) showed a black page that kept
refreshing.

A redirect whose source and target publish at the same URL can only ever do
that, so none may exist.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from tests.test_docs_never_publish_agent_files import MKDOCS


def _url(page: str) -> str:
    """The URL MkDocs gives a page under use_directory_urls (its default)."""
    path = PurePosixPath(page)
    stem = path.stem
    parent = "" if str(path.parent) == "." else f"{path.parent}/"
    if stem.lower() in ("index", "readme"):
        return parent
    return f"{parent}{stem}/"


def _redirects() -> dict[str, str]:
    text = MKDOCS.read_text()
    block = re.search(r"redirect_maps:\n((?:[ \t]+\S.*\n)+)", text)
    assert block, "mkdocs.yml has no redirect_maps block"
    pairs = re.findall(r"^\s+(\S+\.md):\s*(\S+\.md)\s*$", block.group(1), re.M)
    assert pairs, "redirect_maps parsed to nothing; this test would pass on any config"
    return dict(pairs)


def test_the_url_rule_puts_readme_and_index_at_the_folder():
    assert _url("guides/README.md") == _url("guides/index.md") == "guides/"
    assert _url("contributing.md") == "contributing/"


def test_no_redirect_points_at_its_own_url():
    loops = {src: dst for src, dst in _redirects().items() if _url(src) == _url(dst)}
    assert not loops, f"these redirects publish a page that redirects to itself: {loops}"
