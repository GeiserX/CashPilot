"""Agent working files were live on the public documentation site.

MkDocs builds **every** file in ``docs_dir``, whether or not it appears in
``nav``. Three agent scratch files sat there and were therefore published:

    https://geiserx.github.io/CashPilot/GOAL/               -> HTTP 200
    https://geiserx.github.io/CashPilot/AUTOPILOT-WORKLOG/  -> HTTP 200

Between them they published this project's internal planning verbatim, quoted
the maintainer directly, and printed a real Mysterium node identity address —
which links this public repository to a specific earning node.

``mkdocs build --strict`` does **not** catch this. ``validation.nav.omitted_files``
defaults to ``info`` and ``--strict`` only promotes ``warn`` to an error, so the
orphans are reported and the build stays green. Exclusion has to be explicit.

This test is the guard: any file matching the agent-artifact patterns must be
excluded from the built site, and the exclusion is asserted against the parsed
config rather than a substring, so reformatting cannot silently defeat it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MKDOCS = ROOT / "mkdocs.yml"

#: Files that are agent working artifacts, never documentation.
AGENT_ARTIFACTS = ("GOAL.md", "AUTOPILOT-WORKLOG.md", "DEFERRED-QUESTIONS.md")


def _exclude_docs_entries():
    """The exclude_docs block, parsed without a full YAML load.

    mkdocs.yml carries Material's ``!!python/name:`` tags, which safe_load
    rejects, so this reads the block structurally instead of guessing.
    """
    text = MKDOCS.read_text(encoding="utf-8")
    match = re.search(r"^exclude_docs:\s*\|\s*$", text, re.MULTILINE)
    if not match:
        return []
    entries = []
    for line in text[match.end() :].splitlines()[1:]:
        if not line.startswith("  ") or not line.strip():
            break
        entries.append(line.strip())
    return entries


class TestNoAgentArtifactIsPublished:
    def test_the_exclude_block_exists(self):
        assert _exclude_docs_entries(), "mkdocs.yml has no exclude_docs block; every file in docs/ is published"

    @pytest.mark.parametrize("name", AGENT_ARTIFACTS)
    def test_it_is_excluded(self, name):
        assert name in _exclude_docs_entries(), f"{name} would be published to the public site"

    @pytest.mark.parametrize("name", AGENT_ARTIFACTS)
    def test_if_it_exists_at_all_it_is_under_docs(self, name):
        """Guards the other direction: a NEW agent file added to docs/.

        If one of these is ever moved out of docs_dir the exclusion is harmless,
        but while it lives there the exclusion is the only thing stopping it.
        """
        if (ROOT / "docs" / name).exists():
            assert name in _exclude_docs_entries()

    def test_no_unlisted_agent_artifact_is_sitting_in_docs(self):
        """Catches the next one, not just the three we know about."""
        suspects = [
            p.name
            for p in (ROOT / "docs").glob("*.md")
            if re.match(r"^(GOAL|.*WORKLOG|DEFERRED-QUESTIONS|.*-STATE|NOTES)", p.name, re.IGNORECASE)
        ]
        excluded = set(_exclude_docs_entries())
        leaked = [s for s in suspects if s not in excluded]
        assert not leaked, f"agent-looking files in docs/ that would be published: {leaked}"


class TestNoAgentArtifactIsCommitted:
    """Excluding from the SITE is not enough — they must not be in the repo.

    Both were tracked, so their content is in this public repository's history
    from the commit that added them onwards. Untracking stops it growing; it does
    not remove what is already there.
    """

    @pytest.mark.parametrize("name", AGENT_ARTIFACTS)
    def test_it_is_gitignored(self, name):
        import subprocess

        if not (ROOT / ".git").exists():
            pytest.skip("not a git checkout")
        result = subprocess.run(
            ["git", "check-ignore", "-q", f"docs/{name}"], cwd=ROOT, capture_output=True, check=False
        )
        assert result.returncode == 0, f"docs/{name} is not ignored, so it can be committed again"

    @pytest.mark.parametrize("name", AGENT_ARTIFACTS)
    def test_it_is_not_tracked(self, name):
        import subprocess

        if not (ROOT / ".git").exists():
            pytest.skip("not a git checkout")
        tracked = subprocess.run(
            ["git", "ls-files", f"docs/{name}"], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()
        assert not tracked, f"docs/{name} is still tracked: {tracked}"


class TestTheReasonIsRecorded:
    def test_the_reason_is_recorded_beside_the_rule(self):
        """Without it, a later tidy-up deletes the block as unexplained."""
        text = MKDOCS.read_text(encoding="utf-8")
        head = text[: text.index("exclude_docs:")]
        assert "nav" in head.split("# Files that live under")[-1] or "published" in text[: text.index("exclude_docs:")]
