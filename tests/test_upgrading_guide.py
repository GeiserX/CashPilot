"""CashPilot-su5: nothing told a user how to upgrade.

The changelog documents 8 of 198 releases and its newest entry is
``[Unreleased]``. A user on 1.10.1 — which the reference fleet was actually
running, 33 releases behind — had no way to learn what changed or whether
anything needed doing.

``UPGRADING.md`` is the short document: only releases that require an action,
each with who is affected, what breaks if they do nothing, and the command.

Its entries were **harvested** from three hand-written ``**Upgrade note:**``
bullets that were buried in the changelog's ``[Unreleased]`` block, plus the
enrollment-window change which had no note anywhere. Every version heading was
established by finding the commit that introduced the behaviour and asking git
which tag contains it — not by guessing.

These tests keep the file honest and keep it from rotting the way the changelog
did.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UPGRADING = ROOT / "UPGRADING.md"


def _sections():
    """Each ``## vX.Y.Z`` section and its body."""
    text = UPGRADING.read_text(encoding="utf-8")
    parts = re.split(r"^## (v\d+\.\d+\.\d+)", text, flags=re.MULTILINE)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


class TestTheGuideExists:
    def test_it_is_at_the_repo_root_not_in_the_docs_site(self):
        """Deliberate: this must be readable from a checkout without building docs."""
        assert UPGRADING.is_file()

    def test_it_documents_at_least_the_known_action_requiring_releases(self):
        assert len(_sections()) >= 5

    def test_it_tells_the_reader_what_the_default_is(self):
        """Most releases need nothing; saying so is what makes the rest credible."""
        text = UPGRADING.read_text(encoding="utf-8")
        assert "docker compose pull" in text
        assert "no action" in text.lower()


class TestEveryEntryAnswersTheThreeQuestions:
    """Who is affected, what breaks, what to type — the shape the research found."""

    @pytest.mark.parametrize("version", sorted(_sections()))
    def test_it_says_who_is_affected(self, version):
        body = _sections()[version]
        assert re.search(r"\*\*Affects you if\*\*|Affects you if", body) or "own page" in body, (
            f"{version} does not scope who needs to act"
        )

    @pytest.mark.parametrize("version", sorted(_sections()))
    def test_it_offers_an_explicit_no_action_clause(self, version):
        """The clause that stops most readers reading further."""
        # Normalised: markdown wraps, so the clause is split across lines.
        body = re.sub(r"\s+", " ", _sections()[version].lower())
        assert "no action is required" in body or "nothing, unless" in body or "own page" in body, (
            f"{version} never tells an unaffected reader they can stop"
        )


class TestTheVersionsAreReal:
    """A guide with invented version numbers is worse than no guide."""

    def _tags(self):
        out = subprocess.run(["git", "tag"], cwd=ROOT, capture_output=True, text=True, check=False).stdout
        return set(out.split())

    @pytest.mark.parametrize("version", sorted(_sections()))
    def test_the_release_exists(self, version):
        if not (ROOT / ".git").exists():
            pytest.skip("not a git checkout")
        tags = self._tags()
        if not tags:
            pytest.skip("no tags fetched")
        assert version in tags, f"{version} is documented but was never released"

    def test_the_enrollment_window_entry_names_the_release_that_shipped_it(self):
        """Pinned because this is the entry most likely to disconnect somebody."""
        assert "v1.11.30" in _sections()


class TestItIsDiscoverable:
    def test_the_readme_points_at_it(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "UPGRADING.md" in readme, "a user upgrading will never find this file"

    def test_the_changelog_points_at_it(self):
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "UPGRADING.md" in changelog


class TestTheHarvestedNotesSurvived:
    """These three were buried in [Unreleased] and would be lost on regeneration."""

    @pytest.mark.parametrize(
        ("marker", "why"),
        [
            ("CASHPILOT_ALLOW_EPHEMERAL_KEY", "the refuse-to-start-on-unwritable-/data escape hatch"),
            ("CASHPILOT_BIND_ADDR", "the loopback-by-default change"),
            ("latest", "the compose files pinning a series instead of :latest"),
        ],
    )
    def test_it_is_in_the_guide(self, marker, why):
        assert marker in UPGRADING.read_text(encoding="utf-8"), f"lost the note about {why}"

    def test_the_fernet_key_backup_warning_survived(self):
        """Losing that key makes every stored credential unrecoverable."""
        text = UPGRADING.read_text(encoding="utf-8")
        assert ".fernet_key" in text
        assert "back up" in text.lower()
