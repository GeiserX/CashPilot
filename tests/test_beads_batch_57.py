"""CashPilot-cle: the services table hid the two resources that decide viability.

CPU and memory were shown; disk and GPU were not. Those are the two that
actually matter for this product:

* **Disk.** Storj is paid for what it *stores*, so free space is earning
  capacity. A node that quietly fills up stops growing, and nothing in CashPilot
  said so anywhere.
* **GPU.** Salad, Nosana, io.net and Vast.ai only earn with one. The table gave
  no way to tell a GPU service that is earning from one that is running and idle
  because the device was never passed through — the Mysterium ``/dev/net/tun``
  failure mode: healthy-looking, earning nothing.

Both are facts about the **host**, so they are read from the worker that
reported them, which is what makes them work for a remote host exactly as for
the local one — the user's explicit requirement, "even if its remote".

Behaviour lives in ``scripts/host_resources_check.mjs``, which runs the real
functions. The tests here cover what that harness structurally cannot: that the
three row shapes agree on how many columns exist. A mismatch shifts every cell
after it, and no JS assertion would notice.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"
HARNESS = ROOT / "scripts" / "host_resources_check.mjs"


def _js() -> str:
    return APP_JS.read_text(encoding="utf-8")


class TestTheTableStillLinesUp:
    """A column added to one row shape and not the others shifts the rest."""

    def _header_columns(self) -> list[str]:
        js = _js()
        start = js.index('<table class="breakdown-table">')
        head = js[start : js.index("</thead>", start)]
        return re.findall(r"sortTh\('([a-z]+)'|<th[^>]*>([A-Za-z]+)</th>", head)

    def _count_cells(self, marker: str) -> int:
        """Cells in one <tr> template, counted from the opening tag."""
        js = _js()
        start = js.index(marker)
        row = js[start : js.index("</tr>", start)]
        return row.count("<td")

    def test_the_header_has_the_expected_columns(self):
        cols = [a or b for a, b in self._header_columns()]
        assert "disk" in cols, "the Host disk column is gone"
        assert "gpu" in cols, "the GPU column is gone"

    def test_the_main_row_matches_the_header(self):
        header = len(self._header_columns())
        assert self._count_cells('<tr class="breakdown-row') == header, (
            "the main row and the header disagree on column count, so every cell after the "
            "mismatch is drawn under the wrong heading"
        )

    def test_the_instance_sub_row_matches_the_header(self):
        header = len(self._header_columns())
        assert self._count_cells('<tr class="instance-row') == header, (
            "the per-instance sub-row has a different column count from the header"
        )

    def test_the_new_columns_sit_together_after_memory(self):
        """Grouping the resource columns is the point; scattered they read worse."""
        cols = [a or b for a, b in self._header_columns()]
        assert cols.index("disk") == cols.index("memory") + 1
        assert cols.index("gpu") == cols.index("disk") + 1


class TestTheColumnsSayWhatTheyMean:
    def test_the_disk_header_says_HOST_disk(self):
        """Host free space and a service's own volume are different numbers.

        Showing one under the other's name would be worse than showing neither,
        and "Disk" alone would be read as the service's usage.
        """
        assert "'Host disk'" in _js()

    def test_the_tooltip_denies_the_wrong_reading_explicitly(self):
        js = _js()
        assert "not this service's own volume" in js

    def test_a_multi_host_service_reports_the_tightest_not_an_average(self):
        """An average hides exactly the host that is about to fill up."""
        js = _js()
        assert "tightest of" in js
        assert "free_bytes <= b.disk.free_bytes" in js


class TestUnknownIsNeverRenderedAsAValue:
    """The rule this codebase keeps having to re-establish."""

    def test_a_missing_disk_reading_is_not_zero(self):
        js = _js()
        block = js[js.index("function diskCellForHosts(") : js.index("function gpuCell(")]
        assert "|| 0" not in block, "a failed disk read collapses to 0, which renders as a full disk"

    def test_gpu_is_three_valued_not_boolean(self):
        """`available: null` is "could not tell", not "has none"."""
        js = _js()
        block = js[js.index("function gpuCellForHosts(") :][:1600]
        assert "=== true" in block
        assert "=== false" in block, "the cell tests truthiness, so unknown reads as absent"

    def test_only_an_explicit_no_from_every_host_renders_as_None(self):
        js = _js()
        assert "hosts.every(h => h.gpu && h.gpu.available === false)" in js

    def test_the_sort_key_does_not_collapse_unknown_into_a_number(self):
        """-Infinity sorts last descending but FIRST ascending.

        A numeric sentinel cannot keep unknown at the bottom both ways, which
        would put every unreadable host at the top of "least free space".
        """
        js = _js()
        assert "Symbol('unknown')" in js
        assert "SORT_UNKNOWN = Number" not in js

    def test_the_comparator_sinks_unknown_in_both_directions(self):
        js = _js()
        assert "aU && bU ? 0 : (aU ? 1 : -1)" in js


class TestItReadsTheInstanceListAndNotTheCount:
    """``instances`` is a COUNT; ``for...of`` over a number throws.

    The first draft did exactly that, which would have blanked the whole
    services table rather than degrading one column. Only running it caught it.
    """

    def test_it_iterates_instance_details(self):
        js = _js()
        block = js[js.index("function hostsFor(") : js.index("const UNKNOWN_CELL")]
        assert "instance_details" in block
        assert "svc.instances ||" not in block, "iterating the instance COUNT throws"

    def test_it_guards_the_type_anyway(self):
        js = _js()
        assert "Array.isArray(svc.instance_details)" in js

    def test_the_server_really_sends_that_key(self):
        """The premise. If the endpoint renamed it, the guard silently wins."""
        main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert '"instance_details": instance_details' in main
        assert '"worker_id": inst.get("_worker_id")' in main


class TestTheHarnessIsRealAndWired:
    def test_it_extracts_the_live_code_rather_than_stubbing_it(self):
        text = HARNESS.read_text(encoding="utf-8")
        assert "app/static/js/app.js" in text
        assert "new Function(" in text

    def test_it_fails_loudly_if_the_block_moves(self):
        """Otherwise a rename leaves it green while testing nothing."""
        text = HARNESS.read_text(encoding="utf-8")
        assert "the host-resource block moved" in text

    def test_ci_runs_it(self):
        import yaml

        doc = yaml.safe_load((ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8"))
        runs = [s.get("run", "") for job in doc["jobs"].values() for s in (job.get("steps") or [])]
        assert any("host_resources_check.mjs" in r for r in runs), "the harness exists but nothing runs it"

    def test_it_passes(self):
        import subprocess

        result = subprocess.run(
            ["node", "scripts/host_resources_check.mjs"], cwd=ROOT, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_the_assertion_count_is_counted_not_hardcoded(self):
        line = next(
            ln for ln in HARNESS.read_text(encoding="utf-8").splitlines() if "assertions)" in ln and "console" in ln
        )
        assert not re.search(r"\$\{\d+\}", line), f"still interpolating a constant: {line.strip()}"
        assert "checksRun" in line

    def test_it_covers_the_remote_host_requirement(self):
        """The user's words were "even if its remote". A local-only test would
        pass while the feature missed its actual point."""
        text = HARNESS.read_text(encoding="utf-8")
        assert "multi-host" in text.lower() or "tightest of" in text

    @pytest.mark.parametrize("needle", ["escapeHtml", "onerror"])
    def test_it_proves_hostile_worker_data_is_escaped(self, needle):
        """Device names and worker names reach innerHTML."""
        assert needle in HARNESS.read_text(encoding="utf-8")
