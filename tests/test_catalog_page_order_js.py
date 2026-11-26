"""The Catalog page leads each group with the services that pay the project.

#435 gave the catalog a `priority` (1 first) so every list opens with the
services whose referral programme pays the project best. A later redesign of the
Catalog page sorted both groups by name again, so Anyone Protocol and Bitping,
which pay nothing, sat above Honeygain. The page has to keep the same order as
the API, the setup wizard and the README: priority first, then by name.

filterCatalog runs in node against a stub DOM, with the real catalog as input.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app import catalog
from app.constants import UNDEPLOYABLE_STATUSES

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "app/static/js/app.js"

_HARNESS = r"""
const src = require('fs').readFileSync(process.argv[process.argv.length - 2], 'utf8');
const from = src.indexOf('  function filterCatalog() {');
const to = src.indexOf('  function renderCatalogCard(svc) {');
if (from < 0 || to <= from) { console.log(JSON.stringify({ error: 'block moved' })); process.exit(0); }
const { services, category } = JSON.parse(process.argv[process.argv.length - 1]);
const grid = { innerHTML: '' };
const document = {
  querySelector: sel => (sel === '.filter-tab.active' ? { dataset: { category } } : null),
  getElementById: id => (id === 'catalog-grid' ? grid : id === 'catalog-search' ? { value: '' } : null),
};
const renderCatalogCard = svc => `<tr data-slug="${svc.slug}"></tr>`;
const filterCatalog = new Function('document', 'catalogServices', 'renderCatalogCard',
  `${src.slice(from, to)}; return filterCatalog;`)(document, services, renderCatalogCard);
filterCatalog();
console.log(JSON.stringify({ html: grid.innerHTML }));
"""


def _groups(services: list[dict], category: str = "all") -> dict[str, list[str]]:
    """Run filterCatalog and return the slugs of each group, in page order."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    out = subprocess.run(
        [node, "-e", _HARNESS, str(APP_JS), json.dumps({"services": services, "category": category})],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    result = json.loads(out.stdout)
    assert "error" not in result, result
    groups = {}
    for body in re.findall(r'<tbody class="cat-group">(.*?)</tbody>', result["html"], re.S):
        label = re.search(r'scope="colgroup">([^<]+?) <span', body).group(1)
        groups[label] = re.findall(r'data-slug="([^"]+)"', body)
    return groups


def _page_services() -> list[dict]:
    """The services the Catalog page gets: /api/services/available hides these statuses."""
    return [
        {"slug": s["slug"], "name": s["name"], "category": s["category"], "priority": s.get("priority")}
        for s in catalog.get_services()
        if s.get("status") not in UNDEPLOYABLE_STATUSES
    ]


def _expected(services: list[dict]) -> list[str]:
    key = lambda s: (*catalog.priority_key(s), str(s["name"]).lower())  # noqa: E731
    return [s["slug"] for s in sorted(services, key=key)]


class TestTheRealCatalog:
    def test_honeygain_is_the_first_bandwidth_row(self):
        assert _groups(_page_services(), "bandwidth")["Not running"][0] == "honeygain"

    def test_every_tab_lists_by_priority_then_name(self):
        services = _page_services()
        for category in ["all", *sorted({s["category"] for s in services})]:
            shown = [s for s in services if category == "all" or s["category"] == category]
            assert _groups(services, category)["Not running"] == _expected(shown), category


class TestBothGroups:
    ROWS = [
        {"slug": "alpha", "name": "Alpha", "category": "bandwidth"},
        {"slug": "zeta", "name": "Zeta", "category": "bandwidth", "priority": 2},
        {"slug": "beta", "name": "beta", "category": "bandwidth"},
        {"slug": "mu", "name": "Mu", "category": "bandwidth", "priority": 1},
        {"slug": "omega", "name": "Omega", "category": "bandwidth", "priority": 3},
    ]

    def test_running_and_not_running_each_lead_with_priority(self):
        rows = [dict(r, deployed=r["slug"] in {"alpha", "zeta", "mu"}) for r in self.ROWS]
        groups = _groups(rows)
        assert groups["Running in your fleet"] == ["mu", "zeta", "alpha"]
        assert groups["Not running"] == ["omega", "beta"]

    def test_entries_without_a_priority_follow_by_name_whatever_the_case(self):
        assert _groups(self.ROWS)["Not running"] == ["mu", "zeta", "omega", "alpha", "beta"]
