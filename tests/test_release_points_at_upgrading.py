"""Every GitHub Release points at UPGRADING.md.

``generate_release_notes`` lists PR titles only. A release that needs a manual
step (a major, a new compose policy) would not tell anyone to read the upgrade
notes. The publish step now sets a ``body`` that links to UPGRADING.md. A
major (X.0.0) links its own section there, so its notes open on what changed
and how to upgrade; ``scripts/release_upgrade_link.py`` writes the line.

softprops/action-gh-release (pinned v3.0.3) puts ``body`` first and the
generated notes after it, so the PR titles still appear. ``append_body`` only
matters when the release already exists, which is a re-run of the publish job.
Then it keeps the old body and adds the line and the generated notes again, so
it must stay unset.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("release_upgrade_link", ROOT / "scripts" / "release_upgrade_link.py")
link = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(link)
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
UPGRADING_URL = "https://github.com/GeiserX/CashPilot/blob/main/UPGRADING.md"


def release_step() -> dict:
    jobs = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))["jobs"]
    steps = [
        step
        for spec in jobs.values()
        for step in spec.get("steps") or []
        if str(step.get("uses", "")).startswith("softprops/action-gh-release")
    ]
    assert len(steps) == 1, f"expected one GitHub Release step, found {len(steps)}"
    return steps[0]["with"]


def _publish_steps() -> list[dict]:
    jobs = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))["jobs"]
    return jobs["publish"]["steps"]


def test_the_release_body_is_the_line_the_script_writes():
    step = release_step()
    assert str(step.get("body") or "") == "${{ steps.notes.outputs.body }}", step.get("body")
    # The action reads body_path before body, so it would silently drop the line.
    assert "body_path" not in step, "body_path takes priority over body and would drop the UPGRADING.md line"
    steps = _publish_steps()
    names = [s.get("id") for s in steps]
    notes = steps[names.index("notes")]
    release = next(i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("softprops/action-gh-release"))
    assert names.index("notes") < release, "the notes step must run before the release step"
    assert "scripts/release_upgrade_link.py" in notes["run"]
    assert notes["env"]["TAG"] == "${{ needs.release.outputs.new_tag }}"


@pytest.mark.parametrize("tag", ["v3.0.1", "v3.1.0", "v2.10.2", "v1.73.0"])
def test_a_release_that_is_not_a_major_links_the_top_of_the_file(tag):
    text = (ROOT / "UPGRADING.md").read_text(encoding="utf-8")
    assert link.body(tag, text) == f"Upgrading? Read {UPGRADING_URL} first."


@pytest.mark.parametrize(
    ("tag", "fragment"),
    [
        ("v3.0.0", "30-upgrade-the-ui-first-then-change-the-image-tags"),
        ("v2.0.0", "20-change-the-image-tags"),
        ("v1.0.0", "v100-per-worker-fleet-keys"),
    ],
)
def test_a_major_links_its_own_section(tag, fragment):
    text = (ROOT / "UPGRADING.md").read_text(encoding="utf-8")
    assert link.body(tag, text) == f"Upgrading? Read {UPGRADING_URL}#{fragment} first."


def test_the_anchor_is_the_one_github_writes():
    """Lower case, punctuation and backticks gone, spaces to hyphens."""
    assert link.anchor("3.0: upgrade the UI first, then change the image tags") == (
        "30-upgrade-the-ui-first-then-change-the-image-tags"
    )
    assert link.anchor("4.0: the `/data` folder moves") == "40-the-data-folder-moves"


def test_a_major_with_no_section_still_gets_a_link(capsys):
    """A missing section must not stop the release, but it must not pass quietly."""
    assert link.body("v9.0.0", "# Upgrading\n\n## 8.0: old\n") == f"Upgrading? Read {UPGRADING_URL} first."
    assert "no '## 9.0:' section" in capsys.readouterr().err


def test_the_script_runs_from_the_command_line():
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "release_upgrade_link.py"), "v3.0.0"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out.strip() == f"Upgrading? Read {UPGRADING_URL}#30-upgrade-the-ui-first-then-change-the-image-tags first."


def test_the_link_names_a_file_in_the_repo():
    """The URL is absolute, so a renamed file would leave a dead link."""
    match = re.fullmatch(r"https://github\.com/GeiserX/CashPilot/blob/main/(.+)", UPGRADING_URL)
    assert match and (ROOT / match.group(1)).is_file(), f"{UPGRADING_URL} names no file in the repo"


def test_the_pr_titles_still_appear():
    assert release_step().get("generate_release_notes") is True, "the generated PR list is gone"


def test_a_rerun_does_not_repeat_the_body():
    assert release_step().get("append_body") in (None, False), (
        "append_body keeps the existing release body on a re-run and adds the line and the notes again"
    )
