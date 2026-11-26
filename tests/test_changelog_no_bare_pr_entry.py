"""A changelog entry must say what changed, not only which PR changed it.

5a9b0a7 (#838) was squash-merged with the subject " (#838)" and no title, so
git-cliff rendered it as a bare "- (#838)" under "Other". main has moved on, so
the title is restored by cliff.toml's commit_preprocessors, not by rewriting
history, and this keeps it there.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

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


def _rules() -> list[dict[str, str]]:
    config = tomllib.loads((ROOT / "cliff.toml").read_text(encoding="utf-8"))
    return config["git"].get("commit_preprocessors", [])


def _preprocess(message: str, rules: list[dict[str, str]] | None = None) -> str:
    for rule in _rules() if rules is None else rules:
        message = re.sub(rule["pattern"], rule["replace"], message)
    return message


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def test_the_changelog_has_no_bare_pr_entry():
    hits = [line for line in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if BARE_ENTRY.match(line)]
    assert not hits, f"CHANGELOG.md has an entry with no title: {hits}"


def test_no_commit_in_history_renders_as_a_bare_pr_entry():
    """Catch an empty-title squash on main's own push run, before a release renders it.

    CHANGELOG.md changes only when a release renders it, so the test above sees
    a new empty title late. This one reads every commit message the next render
    will read.
    """
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    if _git("rev-parse", "--is-shallow-repository").strip() != "false":
        pytest.skip("shallow checkout: the history is incomplete")
    rules = _rules()
    hits = []
    for record in _git("log", "--format=%H%x1f%B%x1e").split("\x1e"):
        if "\x1f" not in record:
            continue
        sha, message = record.strip("\n").split("\x1f", 1)
        subject = (_preprocess(message, rules).splitlines() or [""])[0]
        if BARE_ENTRY.match(subject):
            hits.append(f"{sha[:7]} {subject!r}")
    assert not hits, f"add a cliff.toml commit_preprocessors rule that restores the title of: {hits}"


def test_preprocessor_replacements_are_plain_text():
    """git-cliff expands $1 and $name in a replacement; Python expands backslashes.

    The tests here run the rules through Python, so they only predict the real
    render while every replacement is plain text.
    """
    bad = [rule["replace"] for rule in _rules() if "$" in rule["replace"] or "\\" in rule["replace"]]
    assert not bad, f"a replacement uses group syntax, so these tests no longer match git-cliff: {bad}"


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
