"""A changelog entry must say what changed, not only which PR changed it.

5a9b0a7 (#838) was squash-merged with the subject " (#838)" and no title, so
git-cliff rendered it as a bare "- (#838)" under "Other". main has moved on, so
the title is restored by cliff.toml's commit_preprocessors, not by rewriting
history, and this keeps it there.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BARE_ENTRY = re.compile(r"^\s*[-*]?\s*\(#\d+\)\s*$")

# The message of 5a9b0a7 as git-cliff sees it: the empty title, then a body.
# The body matters: without (?m) a pattern anchored with a trailing $ never
# matches a multi-line message.
MESSAGE_838 = (
    " (#838)\n"
    "\n"
    "The full test suite and ruff ran on the fork on this exact head and passed.\n"
    "Two independent reviews found four issues, all fixed with regression checks.\n"
)


def _preprocess(message: str) -> str:
    config = tomllib.loads((ROOT / "cliff.toml").read_text(encoding="utf-8"))
    for rule in config["git"].get("commit_preprocessors", []):
        message = re.sub(rule["pattern"], rule["replace"], message)
    return message


def test_the_changelog_has_no_bare_pr_entry():
    hits = [line for line in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if BARE_ENTRY.match(line)]
    assert not hits, f"CHANGELOG.md has an entry with no title: {hits}"


def test_cliff_restores_the_838_title():
    """Without the preprocessor the next regeneration renders "- (#838)"."""
    subject = _preprocess(MESSAGE_838).splitlines()[0]
    assert not BARE_ENTRY.match(subject), f"cliff.toml leaves #838 with no title: {subject!r}"
    assert subject == "fix(economics): stop charging fixed-price workers for electricity (#838)"


def test_the_838_rule_leaves_other_subjects_alone():
    for subject in (
        "fix(economics): stop counting pool-tracked miners as free electricity (#836)",
        "feat: mention (#838) in passing",
        " (#8380)",
    ):
        assert _preprocess(subject) == subject
