"""CashPilot-3xg: ~200 releases, and no way to see what changed across them.

The hand-written ``CHANGELOG.md`` stopped at **0.2.49** while the project shipped
**1.13.0**. GitHub already renders per-release notes (``release.yml`` sets
``generate_release_notes: true``, and it works), but at roughly two commits per
release, upgrading 1.10.1 → 1.13.0 meant opening thirty release pages that each
held one PR title. The gap was never "no release notes" — it was no **aggregate**.

Generation is by ``git-cliff``, chosen because ``--tag`` only *labels* a section
and never creates a ref, so the existing bump logic in ``release.yml`` is
untouched. release-please and semantic-release both replace that workflow.

Two things here are load-bearing and easy to undo by accident:

* **The hand-written entries are preserved verbatim**, because they explain *why*
  a change was made at a length no generated line reaches. They are archived, not
  deleted.
* **The generated file cannot be trusted to flag breaking changes.** Exactly one
  commit in the entire history carries a ``!`` marker, so an empty "breaking"
  section means nothing. That is why ``UPGRADING.md`` stays hand-written and why
  the generated header says so out loud.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"
ARCHIVE = ROOT / "docs" / "changelog-0.x-handwritten.md"
CONFIG = ROOT / "cliff.toml"
WORKFLOW = ROOT / ".github" / "workflows" / "changelog.yml"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"


class TestTheAggregateExists:
    def test_the_changelog_covers_the_releases_that_were_missing(self):
        """It stopped at 0.2.49 while 1.x shipped ~200 times."""
        text = CHANGELOG.read_text(encoding="utf-8")
        sections = re.findall(r"^## \[([^\]]+)\]", text, re.M)
        assert len(sections) >= 150, f"only {len(sections)} releases; the aggregate is the point"

    def test_it_reaches_the_current_major(self):
        text = CHANGELOG.read_text(encoding="utf-8")
        assert re.search(r"^## \[1\.", text, re.M), "still stops before 1.0.0"

    def test_entries_are_grouped_rather_than_one_flat_list(self):
        text = CHANGELOG.read_text(encoding="utf-8")
        groups = set(re.findall(r"^### (.+)$", text, re.M))
        assert {"Features", "Fixes"} <= groups, groups

    def test_most_commits_are_not_dumped_into_Other(self):
        """ "Other" with 174 entries is not a section, it is a pile.

        Measured against the real history: the pre-convention rules in
        cliff.toml bring it from 40% of entries to under 15%.
        """
        text = CHANGELOG.read_text(encoding="utf-8")
        group, counts = None, {}
        for line in text.splitlines():
            if line.startswith("### "):
                group = line[4:].strip()
            elif line.startswith("- ") and group:
                counts[group] = counts.get(group, 0) + 1
        total = sum(counts.values())
        assert total > 300, f"only {total} entries parsed"
        other = counts.get("Other", 0)
        assert other / total < 0.15, f"Other is {100 * other / total:.0f}% of {total} entries"


class TestTheHandWrittenEntriesSurvived:
    """They explain *why*, at a length no generated line reaches."""

    def test_the_archive_exists(self):
        assert ARCHIVE.exists(), "the hand-written changelog was overwritten, not archived"

    def test_the_generated_file_links_to_it(self):
        assert "changelog-0.x-handwritten.md" in CHANGELOG.read_text(encoding="utf-8")

    @pytest.mark.parametrize("version", ["0.2.49", "0.2.17", "0.1.0"])
    def test_every_old_release_heading_is_still_readable(self, version):
        assert f"## [{version}]" in ARCHIVE.read_text(encoding="utf-8")

    def test_the_detailed_prose_survived_verbatim(self):
        """A spot check on content, not just headings.

        Whitespace-normalised: the source hard-wraps, and a contiguous
        substring check has already failed three times in this project for
        exactly that reason.
        """
        text = re.sub(r"\s+", " ", ARCHIVE.read_text(encoding="utf-8"))
        assert "A redeploy no longer silently replaces a container" in text
        assert "ProxyBase migrated to the current client" in text

    def test_the_archive_is_marked_as_not_regenerable(self):
        assert "Do not regenerate this file" in ARCHIVE.read_text(encoding="utf-8")

    def test_it_has_exactly_one_top_level_heading(self):
        """The original H1 is dropped when nesting it under the archive's own."""
        heads = [ln for ln in ARCHIVE.read_text(encoding="utf-8").splitlines() if ln.startswith("# ")]
        assert len(heads) == 1, heads


class TestItDoesNotOversellWhatItKnows:
    """One commit in ~430 carries a breaking marker."""

    def test_the_header_sends_upgraders_to_the_hand_written_file_first(self):
        text = re.sub(r"\s+", " ", CHANGELOG.read_text(encoding="utf-8")[:2000])
        assert "UPGRADING.md" in text

    def test_it_admits_it_cannot_flag_breaking_changes(self):
        text = re.sub(r"\s+", " ", CHANGELOG.read_text(encoding="utf-8")[:2000])
        assert "cannot be trusted to flag breaking changes" in text

    def test_the_claim_behind_that_warning_is_still_true(self):
        """If the project starts marking breaking changes, soften the wording.

        Asserted against git, so it fails when the premise changes rather than
        leaving a warning that has quietly become false.
        """
        out = subprocess.run(["git", "log", "--pretty=%s"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        marked = [s for s in out.splitlines() if re.match(r"^[a-z]+(\(.+\))?!:", s)]
        assert len(marked) <= 5, (
            f"{len(marked)} commits now carry a breaking marker; the header's warning is too strong"
        )


class TestRegenerationCannotLoopOrLoseTheFile:
    def _release_paths(self) -> list[str]:
        doc = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))
        on = doc[True] if True in doc else doc["on"]
        return list((on.get("push") or {}).get("paths") or [])

    def test_merging_the_changelog_does_not_trigger_a_release(self):
        """Otherwise: release -> regenerate -> merge -> release, forever."""
        paths = self._release_paths()
        assert paths, "release.yml lost its path filter, so ANY merge now releases"
        for never in ("CHANGELOG.md", "cliff.toml"):
            assert never not in paths, f"{never} is in release.yml's path filter — this is a release loop"

    def test_the_docs_path_is_not_in_the_filter_either(self):
        assert not any(p.startswith("docs/") for p in self._release_paths())

    def test_the_workflow_opens_a_pull_request_rather_than_pushing(self):
        """`main` requires a PR, so a push would simply fail."""
        doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        steps = doc["jobs"]["regenerate"]["steps"]
        assert any("create-pull-request" in str(s.get("uses", "")) for s in steps)

    def test_it_reuses_one_branch_instead_of_spamming(self):
        doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        step = next(s for s in doc["jobs"]["regenerate"]["steps"] if "create-pull-request" in str(s.get("uses", "")))
        assert step["with"]["branch"] == "chore/changelog", (
            "without a fixed branch this files one PR per release, and releases are ~2 commits apart"
        )

    def test_it_checks_out_full_history(self):
        """A shallow clone yields a changelog with one release and no error."""
        doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        checkout = next(s for s in doc["jobs"]["regenerate"]["steps"] if "actions/checkout" in str(s.get("uses", "")))
        assert checkout["with"]["fetch-depth"] == 0

    def test_it_refuses_to_commit_a_truncated_changelog(self):
        """Committing an empty render would silently delete the file."""
        text = WORKFLOW.read_text(encoding="utf-8")
        assert "Refusing" in text
        assert "-lt 100" in text

    def test_every_third_party_action_is_pinned_to_a_sha(self):
        """These get write access to the repository."""
        doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        for step in doc["jobs"]["regenerate"]["steps"]:
            uses = str(step.get("uses", ""))
            if not uses:
                continue
            assert re.search(r"@[0-9a-f]{40}$", uses.split()[0]), f"{uses} is not SHA-pinned"

    def test_the_job_asks_for_no_more_permission_than_it_needs(self):
        doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        assert doc["permissions"] == {"contents": "read"}, "the workflow-level default should stay read-only"
        assert set(doc["jobs"]["regenerate"]["permissions"]) == {"contents", "pull-requests"}


class TestTheConfigIsHonestAboutItsLimits:
    def test_unconventional_commits_are_kept_not_dropped(self):
        """~40% of this history predates the convention."""
        assert "filter_unconventional = false" in CONFIG.read_text(encoding="utf-8")

    def test_dependency_bumps_are_grouped_rather_than_skipped(self):
        """A user auditing a CVE needs to see the bump."""
        text = CONFIG.read_text(encoding="utf-8")
        assert 'group = "Dependencies"' in text
        assert not re.search(r'message = "\^deps".*skip = true', text)

    def test_merge_commits_are_skipped(self):
        assert 'message = "^Merge (pull request|branch|remote)", skip = true' in CONFIG.read_text(encoding="utf-8")

    def test_there_is_exactly_one_catch_all_and_it_is_last(self):
        """A catch-all above the specific rules swallows everything below it.

        The first version of this only checked the LAST parser, so inserting a
        second ``.*`` at the top passed — the original was still last while every
        commit landed in Other. Caught by a negative control that did not fire.
        """
        text = CONFIG.read_text(encoding="utf-8")
        parsers = re.findall(r"^\s*\{ message = \"([^\"]+)\"", text, re.M)
        assert parsers.count(".*") == 1, f"{parsers.count('.*')} catch-all rules; the first one wins and hides the rest"
        assert parsers[-1] == ".*", f"the catch-all is not last: {parsers[-3:]}"

    def test_the_ordering_is_load_bearing_in_practice(self):
        """Not just a lint on the file: prove the rules actually classify.

        A structural check on ordering says nothing about whether the parsers
        match real subjects, so this runs them against subjects taken from this
        repository's own history.
        """
        text = CHANGELOG.read_text(encoding="utf-8")
        group, seen = None, {}
        for line in text.splitlines():
            if line.startswith("### "):
                group = line[4:].strip()
            elif line.startswith("- ") and group:
                seen.setdefault(group, []).append(line[2:])
        # A real `feat:` subject from main's history, which must not land in
        # Other. Deliberately one that is MERGED rather than one from the branch
        # under development: the first version named a commit that existed only
        # on a sibling branch, so regenerating anywhere else failed the test for
        # a reason that had nothing to do with the parsers.
        assert any("report disk and GPU" in e for e in seen.get("Features", [])), (
            "a feat: commit is not being grouped as a Feature"
        )
        assert len(seen.get("Fixes", [])) > 50, "fix: is the most common type here; it should dominate"


class TestTheChangelogStaysOutOfTheDocsSite:
    """Asked for explicitly: the changelog and upgrade notes are FILES.

    They belong beside the code, where someone comparing the version they run
    against the one they are about to pull will look. Two independent reasons
    reinforce it: their links are written relative to the REPOSITORY root
    (``../CHANGELOG.md``, ``docs/guides/proxybase.md``), so publishing them makes
    ``mkdocs build --strict`` fail on seven broken links.
    """

    MKDOCS = ROOT / "mkdocs.yml"

    def _excluded(self) -> list[str]:
        text = self.MKDOCS.read_text(encoding="utf-8")
        block = text[text.index("exclude_docs:") :]
        block = block[: block.index("\nnav:")]
        return [ln.strip() for ln in block.splitlines()[1:] if ln.strip() and not ln.strip().startswith("#")]

    def test_the_archive_is_excluded_from_the_site(self):
        assert "changelog-0.x-handwritten.md" in self._excluded()

    def test_the_nav_does_not_link_it(self):
        """exclude_docs plus a nav entry is a build error, not a silent skip."""
        text = self.MKDOCS.read_text(encoding="utf-8")
        nav = text[text.index("\nnav:") :]
        assert "changelog-0.x-handwritten" not in nav

    def test_neither_changelog_file_lives_under_docs_nav(self):
        text = self.MKDOCS.read_text(encoding="utf-8")
        nav = text[text.index("\nnav:") :]
        assert "CHANGELOG" not in nav
        assert "UPGRADING" not in nav

    def test_the_root_files_exist_where_a_reader_expects_them(self):
        """The flip side: excluded from the site must not mean missing."""
        assert (ROOT / "CHANGELOG.md").exists()
        assert (ROOT / "UPGRADING.md").exists()


class TestTheArchiveIsActuallyReadable:
    """Moving the file into ``docs/`` silently broke four of its links.

    The entries were written when this changelog sat at the repository root, so
    ``docs/guides/proxybase.md`` now resolves to ``docs/docs/...`` and 404s, and
    a bare ``UPGRADING.md`` resolves to ``docs/UPGRADING.md``. Excluding the file
    from the MkDocs build made ``--strict`` pass and hid this — but GitHub is
    exactly where the archive is meant to be read, so the links still had to
    work. (CodeRabbit, PR #251.)

    Resolved against the filesystem rather than pattern-matched: a test that
    only checked the links "look relative" would have passed on every broken
    one of them.
    """

    def test_every_link_in_the_archive_resolves(self):
        links = re.findall(r"\]\(([^)#\s]+\.md)\)", ARCHIVE.read_text(encoding="utf-8"))
        assert links, "no links found; this test would be vacuous"
        broken = [link for link in links if not (ARCHIVE.parent / link).resolve().exists()]
        assert not broken, f"these 404 for anyone reading the archive on GitHub: {broken}"

    def test_it_still_points_at_both_current_files(self):
        text = ARCHIVE.read_text(encoding="utf-8")
        assert "](../CHANGELOG.md)" in text
        assert "](../UPGRADING.md)" in text

    def test_the_rewrite_is_disclosed(self):
        """The file claims to be verbatim; a silent edit would make that false."""
        assert "only the links were rebased" in ARCHIVE.read_text(encoding="utf-8")


class TestTheReleaseSkipRuleIsReachable:
    """It sat *below* the generic ``^(chore|style|build)`` rule, which matches
    ``chore(release):`` first — so the skip never fired and the rule was dead.

    No such commit exists yet, so the current output is unchanged; this is about
    the rule working the first time one appears. (CodeRabbit, PR #251.)
    """

    def _parsers(self) -> list[str]:
        return re.findall(r"^\s*\{ message = \"([^\"]+)\"", CONFIG.read_text(encoding="utf-8"), re.M)

    def test_the_release_rule_precedes_the_generic_chore_rule(self):
        parsers = self._parsers()
        release = next(i for i, p in enumerate(parsers) if "release" in p)
        generic = next(i for i, p in enumerate(parsers) if p == "^(chore|style|build)")
        assert release < generic, "the release skip is unreachable behind the generic chore rule"

    def test_no_release_bookkeeping_leaks_into_the_changelog(self):
        """The outcome, not just the ordering."""
        entries = [ln for ln in CHANGELOG.read_text(encoding="utf-8").splitlines() if ln.startswith("- ")]
        leaked = [e for e in entries if re.match(r"- (chore\(release\)|Release v?[0-9])", e)]
        assert not leaked, leaked
