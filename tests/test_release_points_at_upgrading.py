"""Every GitHub Release points at UPGRADING.md.

``generate_release_notes`` lists PR titles only. A release that needs a manual
step (a major, a new compose policy) would not tell anyone to read the upgrade
notes. The publish step now sets a ``body`` that links to UPGRADING.md.

softprops/action-gh-release (pinned v3.0.3) puts ``body`` first and the
generated notes after it, so the PR titles still appear. ``append_body`` only
matters when the release already exists, which is a re-run of the publish job.
Then it keeps the old body and adds the line and the generated notes again, so
it must stay unset.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
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


def test_the_release_body_links_to_the_upgrade_notes():
    body = str(release_step().get("body") or "")
    assert UPGRADING_URL in body, f"the release body does not link to {UPGRADING_URL}: {body!r}"


def test_the_link_names_a_file_that_exists_on_main():
    """The URL is absolute, so a renamed file would leave a dead link."""
    match = re.fullmatch(r"https://github\.com/GeiserX/CashPilot/blob/main/(.+)", UPGRADING_URL)
    assert match and (ROOT / match.group(1)).is_file(), f"{UPGRADING_URL} names no file in the repo"


def test_the_pr_titles_still_appear():
    assert release_step().get("generate_release_notes") is True, "the generated PR list is gone"


def test_a_rerun_does_not_repeat_the_body():
    assert release_step().get("append_body") in (None, False), (
        "append_body keeps the existing release body on a re-run and adds the line and the notes again"
    )
