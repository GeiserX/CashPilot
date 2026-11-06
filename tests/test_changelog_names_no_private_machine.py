"""CHANGELOG.md is public and is regenerated from commit subjects.

One subject (#412) names a maintainer's machine. A hand edit of the changelog
removed it and the next regeneration put it back (#577, then #578), so the
rewrite lives in cliff.toml's commit_preprocessors and this keeps it there.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = re.compile(r"(?i)macbook|mac ?mini")


def test_the_changelog_names_no_private_machine():
    hits = [line for line in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if PRIVATE.search(line)]
    assert not hits, f"CHANGELOG.md names a private machine: {hits}"


def test_cliff_rewrites_the_subject_that_names_one():
    """Without the preprocessor the next regeneration undoes the hand edit."""
    config = tomllib.loads((ROOT / "cliff.toml").read_text(encoding="utf-8"))
    subject = "chore(beads): drop a MacBook-only lefthook path from the committed hook (#412)"
    for rule in config["git"].get("commit_preprocessors", []):
        subject = re.sub(rule["pattern"], rule["replace"], subject)
    assert not PRIVATE.search(subject), f"cliff.toml leaves the subject naming a machine: {subject}"
