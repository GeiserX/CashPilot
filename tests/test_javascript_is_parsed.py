"""The JavaScript is never parsed by anything in CI. It is now.

Demonstrated, not theorised: appending `function broken( {` to app/static/js/app.js
leaves the entire suite green — 2306 passed. CI would be green too, because
nothing in .github/workflows/test.yml so much as looks at a .js file.

What ships in that state is a completely dead dashboard. `app.js` is one IIFE
assigned to `CP`; a syntax error anywhere in its 2900 lines means `CP` is never
defined, `delegate.js` falls through to `typeof CP !== 'undefined' ? CP : {}`,
and every single data-action button logs "No handler named X" and does nothing.
No page errors, no failed request, no alert — just a dashboard where nothing
works.

That is a bigger risk after this release than before it: 1.11.0 moved the payout
queue, payout progress, credential health, running costs and the deploy-risk
gate into that file. All of them are reachable only through `CP`.

These tests skip rather than fail when node is unavailable, because a missing
toolchain is not a code defect — but CI has node, and the workflow step added
alongside this makes it a hard gate there.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS_FILES = sorted((ROOT / "app" / "static" / "js").glob("*.js"))
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed; CI installs it")


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
def test_the_file_parses(path: Path):
    """A syntax error here is invisible to every other test in the suite."""
    result = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, f"{path.name} does not parse:\n{result.stderr}"


def test_there_is_javascript_to_check():
    """A glob that matches nothing would make the parametrised test vacuous."""
    names = {p.name for p in JS_FILES}
    assert {"app.js", "delegate.js"} <= names, names


def test_the_check_actually_rejects_broken_syntax(tmp_path):
    """Prove the checker fails on something, rather than trusting it."""
    broken = tmp_path / "broken.js"
    broken.write_text("function broken( {\n", encoding="utf-8")
    result = subprocess.run([NODE, "--check", str(broken)], capture_output=True, text=True, timeout=60)
    assert result.returncode != 0, "node --check accepted invalid JavaScript"


def test_ci_also_parses_the_javascript():
    """Local-only enforcement drifts. The workflow must gate it too.

    Asserted against the workflow file because a developer without node gets a
    skip above, and a skip is not a check.
    """
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert "--check" in workflow, "CI does not parse the JavaScript"


class TestTheCommittedBrowserHarnessesStillRun:
    """Three harnesses exist because pytest cannot see browser behaviour.

    Each was written after a defect that no string test could have caught, so
    they are only worth having if something notices when they rot.
    """

    @pytest.mark.parametrize("name", ["currency_check.mjs", "hint_sanitizer_check.mjs", "first_boot_check.mjs"])
    def test_the_harness_exists_and_can_fail(self, name):
        path = ROOT / "scripts" / name
        assert path.exists(), f"{name} was deleted; the behaviour it pinned is unguarded again"
        source = path.read_text(encoding="utf-8")
        assert "process.exit" in source, f"{name} cannot fail, so it gates nothing"

    def test_the_currency_harness_runs_headlessly_and_passes(self):
        """This one needs no browser, so it can run here."""
        result = subprocess.run(
            [NODE, "scripts/currency_check.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, f"currency harness failed:\n{result.stdout}\n{result.stderr}"
        assert "RESULT: PASS" in result.stdout


class TestTheBrowserHarnessesActuallyRun:
    """The .mjs checks are only worth having if something runs them.

    CI runs them as separate steps, which is right — but a harness that only
    ever runs on CI is one a local `pytest` run will not catch before a push.
    Shelling out here keeps them in the same gate as everything else.
    """

    @pytest.mark.parametrize("script", ["currency_check.mjs", "fleet_staleness_check.mjs"])
    def test_the_harness_passes(self, script):
        node = shutil.which("node")
        if node is None:
            pytest.skip("node is not installed; CI runs these as their own step")
        result = subprocess.run(
            [node, f"scripts/{script}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, f"{script} failed:\n{result.stdout}\n{result.stderr}"

    def test_ci_runs_every_browser_free_harness(self):
        """A new harness that CI never invokes is decoration."""
        workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        for script in ("currency_check.mjs", "fleet_staleness_check.mjs"):
            assert script in workflow, f"scripts/{script} is never run by CI"
