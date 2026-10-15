"""`priority` leads the catalog with the services that pay the project best.

The README lists and the web catalog used to be alphabetical, so Anyone Protocol
and Bitping (no referral programme at all) came first and Honeygain (30% to the
referrer) sat in the middle. A reorder is now a number in the YAML, and
everything that lists the catalog follows it; the entries without one keep the
order they always had.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app import catalog

ROOT = Path(__file__).resolve().parents[1]


class TestPriorityKey:
    def test_prioritised_entries_come_first_lowest_number_first(self):
        rows = [{"slug": "c"}, {"slug": "b", "priority": 2}, {"slug": "a", "priority": 1}, {"slug": "d"}]
        assert [r["slug"] for r in sorted(rows, key=catalog.priority_key)] == ["a", "b", "c", "d"]

    def test_entries_without_a_priority_keep_their_order(self):
        rows = [{"slug": "z"}, {"slug": "m"}, {"slug": "a"}]
        assert [r["slug"] for r in sorted(rows, key=catalog.priority_key)] == ["z", "m", "a"]


class TestValidation:
    def _errors(self, tmp_path, priority) -> list[str]:
        data = {"name": "X", "slug": "x", "category": "bandwidth", "status": "active", "priority": priority}
        return [e for e in catalog._validate(data, tmp_path / "x.yml") if "priority" in e]

    def test_a_positive_integer_is_accepted(self, tmp_path):
        assert self._errors(tmp_path, 3) == []

    def test_text_zero_negative_and_booleans_are_refused(self, tmp_path):
        for bad in ("high", 0, -1, True):
            assert self._errors(tmp_path, bad), bad


class TestTheRealCatalog:
    def test_honeygain_leads_the_catalog(self):
        """Honeygain pays the referrer 30% and is the biggest earner in the fleet."""
        services = catalog.get_services()
        assert services[0]["slug"] == "honeygain"

    def test_every_prioritised_entry_is_live(self):
        for svc in catalog.get_services():
            if svc.get("priority") is not None:
                assert svc.get("status") in {"active", "beta"}, svc["slug"]

    def test_priorities_are_unique(self):
        numbers = [s["priority"] for s in catalog.get_services() if s.get("priority") is not None]
        assert len(numbers) == len(set(numbers))

    def test_the_readme_docker_line_starts_with_honeygain(self):
        out = subprocess.run(
            [sys.executable, "-c", "import scripts.generate_readme_tables as g; print(g._line(g.DOCKER))"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert out.split("** ", 1)[1].startswith("[Honeygain]"), out[:200]
