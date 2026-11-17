"""CashPilot-9fg: the compose-pin check was a tripwire, not a guard.

``tests/test_compose_image_pins.py`` compares the example compose files' pinned
``major.minor`` against the newest RELEASED series, and it is right to: a stale
pin is what gave issue #188 a version with a first-run bug that had been fixed
for months.

But nothing moved the pin. So every minor release left both compose files a
series behind and that test went red on **every open branch** until someone
bumped them by hand — it blocked two unrelated PRs within hours of v1.15.0. The
check was punishing whoever opened the next pull request for something the
release had done.

The release now moves the pin itself, straight after pushing the tag it is
pinning to.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / ".github" / "workflows" / "release.yml"


def publish_steps() -> list[dict]:
    doc = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))
    return [s for s in doc["jobs"]["publish"]["steps"] if isinstance(s, dict)]


def release_push_paths() -> list[str]:
    """The files a release is built from. Once the push trigger's path filter;
    since releases are batched, the list the daily run compares with the last tag."""
    doc = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))
    return doc["jobs"]["pending"]["env"]["RELEASE_PATHS"].split()


def _filter_regex(pattern: str) -> re.Pattern[str]:
    """GitHub's filter-pattern syntax, enough of it to be honest.

    `*` stops at a slash, `**` does not, and `?`/`+` are quantifiers on what
    precedes them. Substring matching was the previous version of this check and
    it would have waved through `'*.yml'`, which matches both compose files.
    """
    out: list[str] = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "*":
            if pattern[i + 1 : i + 2] == "*":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif char in "?+":
            out.append(char)
        elif char == "[":
            close = pattern.index("]", i)
            out.append(pattern[i : close + 1])
            i = close + 1
            continue
        else:
            out.append(re.escape(char))
        i += 1
    return re.compile("^" + "".join(out) + "$")


def path_filter_matches(paths: list[str], filename: str) -> bool:
    """Last matching pattern wins, and a leading `!` negates."""
    matched = False
    for pattern in paths:
        negated = pattern.startswith("!")
        if _filter_regex(pattern[1:] if negated else pattern).match(filename):
            matched = not negated
    return matched


def push_step() -> dict:
    for step in publish_steps():
        if step.get("name") == "Push the changelog and the pins to main":
            return step
    raise AssertionError(f"no push step: {[s.get('name') for s in publish_steps()]}")


def bump_step() -> dict:
    for step in publish_steps():
        if "compose pins" in (step.get("name") or ""):
            return step
    raise AssertionError(f"no compose-pin step: {[s.get('name') for s in publish_steps()]}")


class TestTheReleaseMovesThePin:
    def test_the_step_exists(self):
        assert bump_step()["run"]

    def test_it_runs_after_the_tag_is_pushed(self):
        """Order matters and is not cosmetic. The pin test compares against the
        newest RELEASED series, so bumping before the tag exists would leave the
        files pinned to a version no release has published."""
        names = [s.get("name") or s.get("uses") or "" for s in publish_steps()]
        tag_at = next(i for i, n in enumerate(names) if "push tag" in n.lower())
        bump_at = next(i for i, n in enumerate(names) if "compose pins" in n)
        assert tag_at < bump_at, names

    def test_it_derives_the_series_from_the_tag(self):
        """Not from anything that could agree with itself."""
        run = bump_step()["run"]
        assert "needs.release.outputs.new_tag" in run
        assert 'SERIES="${SERIES%.*}"' in run, "the patch component is not stripped"

    def test_a_patch_release_changes_nothing(self):
        """v1.16.2 is the same 1.16 series. Without this the release pushes an
        empty commit to main on every patch."""
        run = bump_step()["run"]
        assert '[ "$CURRENT" = "$SERIES" ]' in run, run

    def test_the_edit_is_verified_before_it_is_committed(self):
        """A sed that matched nothing would commit nothing and report success,
        leaving the drift in place with no red build to reveal it."""
        run = bump_step()["run"]
        assert "STRAY=" in run
        assert "::error::" in run
        assert "exit 1" in run

    def test_the_guard_uses_no_perl_regex(self):
        """GNU grep REFUSES -E and -P together ("conflicting matchers
        specified", exit 2). The first version of this step used both and looked
        fine locally only because that shell's `grep` is a ugrep shim, which
        accepts it — so it would have failed on ubuntu-latest, in the release,
        after the tag was already published.
        """
        run = bump_step()["run"]
        offenders = [ln.strip() for ln in run.splitlines() if re.search(r"\bgrep\b.*-\w*P\b", ln)]
        assert not offenders, offenders

    def test_the_step_names_the_compose_files_it_edits(self):
        """Derived, not restated, so a rename cannot slip past the next test."""
        assert self._edited_files() == [
            "docker-compose.fleet.yml",
            "docker-compose.worker.yml",
            "docker-compose.yml",
        ], self._edited_files()

    def _edited_files(self):
        adds = [ln for ln in bump_step()["run"].splitlines() if ln.strip().startswith("git add")]
        assert adds, "the step no longer stages anything"
        return sorted({word for line in adds for word in line.split()[2:] if word.endswith(".yml")})

    @pytest.mark.parametrize("compose", ["docker-compose.yml", "docker-compose.fleet.yml"])
    def test_the_commit_cannot_start_another_release(self, compose):
        """release.yml triggers on pushes to main, so a pin bump must not be one.

        The guarantee used to be a skip-CI marker on the commit. It is now the
        paths filter, which does not match the compose files, so the workflow
        never fires for this push at all. Asserted where the guarantee actually
        lives rather than on a marker that only backs it up.

        Matched as GitHub matches, not by substring: `'*.yml'` names neither
        file and matches both. (CodeRabbit, PR #351.)
        """
        paths = release_push_paths()
        assert not path_filter_matches(paths, compose), (
            f"release.yml fires on {compose} (paths: {paths}), so every release would trigger another one"
        )

    def test_it_edits_the_newest_main(self):
        """main may have moved while the images were building. Editing the
        tagged commit and pushing it would be refused, or undo those merges."""
        names = [s.get("name") or s.get("uses") or "" for s in publish_steps()]
        assert names.index("Start from the newest main") < names.index("Bump the example compose pins to this series")
        assert names.index("Bump the example compose pins to this series") < names.index(push_step()["name"])

    def test_the_bump_step_itself_never_pushes(self):
        """One commit, one push: the pins go out with the changelog."""
        assert "git push" not in bump_step()["run"]
        assert "git commit" not in bump_step()["run"]

    def test_the_commit_carries_no_skip_marker(self):
        """A skipped run never reports. `test` must still run on this commit on
        main, and the docs must rebuild for the new compose pins."""
        commits = [ln for ln in push_step()["run"].splitlines() if ln.strip().startswith("git commit")]
        assert commits, "the step no longer commits anything"
        offenders = [ln.strip() for ln in commits if "[skip ci]" in ln or "[ci skip]" in ln]
        assert not offenders, offenders

    def test_the_commit_subject_is_one_the_changelog_skips(self):
        """`chore(release):` is skipped by cliff.toml, so the changelog never
        lists its own commit."""
        commit = next(ln for ln in push_step()["run"].splitlines() if ln.strip().startswith("git commit"))
        assert '-m "chore(release): ' in commit, commit

    def test_every_push_goes_to_main(self):
        """Asserted POSITIVELY: a push anywhere else is the old PR branch coming
        back, which is what needed a person to merge it."""
        pushes = [ln.strip() for ln in push_step()["run"].splitlines() if "git push" in ln]
        assert pushes, "the step no longer pushes anything"
        offenders = [ln for ln in pushes if "HEAD:main" not in ln]
        assert not offenders, offenders

    def test_every_delivery_failure_warns_rather_than_failing_the_release(self):
        """The tag, the images and the GitHub Release are published by this point.
        Failing here would turn a cosmetic miss into a red release.

        Scoped to the DELIVERY half (key, host keys, push). A truncated render
        above it is a real defect and stays an ::error::, without failing.
        """
        run = push_step()["run"]
        delivery = run[run.index('if [ -z "$DEPLOY_KEY" ]') :]
        assert "::warning::" in delivery
        assert "::error::" not in delivery, "a delivery failure is escalated to an error"
        assert "exit 1" not in run
        # A missing key, unreadable host keys, and every push refused.
        assert delivery.count("exit 0") >= 3, delivery

    def test_a_refused_push_is_replayed_on_the_newest_main(self):
        """A merge between the fetch and the push must not cost the commit."""
        run = push_step()["run"]
        loop = run[run.index("for attempt in") :]
        assert "git fetch origin main" in loop and "git rebase FETCH_HEAD" in loop, loop
        assert "git rebase --abort" in loop, "a conflicted replay is left half-applied"

    def test_the_delivery_waits_for_the_newest_main_and_the_newest_tag(self):
        """A late "Re-run failed jobs" on an older release must not push its
        shorter changelog and older pins over a newer release's: the push passes
        no check. Both steps that write main are gated on the guard."""
        start = next(s for s in publish_steps() if s.get("name") == "Start from the newest main")
        assert start.get("id") == "main"
        run = start["run"]
        assert "--sort=-v:refname" in run and '[ "$NEWEST" != "$TAG" ]' in run, run
        assert run.count("deliver=false") == 2 and "deliver=true" in run, run
        for step in (bump_step(), push_step()):
            assert step.get("if") == "steps.main.outputs.deliver == 'true'", step.get("name")

    def test_a_failed_fetch_warns_rather_than_failing_the_release(self):
        start = next(s for s in publish_steps() if s.get("name") == "Start from the newest main")
        assert "if ! git fetch" in start["run"]
        assert "git fetch origin main || break" in push_step()["run"]

    def test_the_host_key_call_is_authenticated(self):
        """Unauthenticated, /meta shares the runner IP's limit of 60 an hour."""
        step = push_step()
        assert step["env"]["GH_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}"
        assert '-H "Authorization: Bearer $GH_TOKEN" https://api.github.com/meta' in step["run"]

    def test_only_main_can_read_the_deploy_key(self):
        """The key bypasses the PR and check rules on main. It sits in the
        `release` environment, which admits main only, so a workflow pushed on
        another branch by a write collaborator cannot read it."""
        doc = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))
        assert doc["jobs"]["publish"].get("environment") == "release"
        users = [name for name, job in doc["jobs"].items() if "RELEASE_DEPLOY_KEY" in yaml.safe_dump(job)]
        assert users == ["publish"], users
        for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
            if wf.name != "release.yml":
                assert "RELEASE_DEPLOY_KEY" not in wf.read_text(encoding="utf-8"), wf.name

    def test_the_series_is_read_from_both_files(self):
        """Reading only docker-compose.yml made partial drift invisible.

        If one file had drifted and the other had not, the "already on $SERIES"
        check would fire on the first and leave the second stale forever — a
        silent no-op that looks exactly like success. Verified on a Linux host:
        with the two files on 1.14 and 1.16, the step now reports
        `bump [1.14 1.16] -> 1.16` instead of `NOOP`.
        """
        run = bump_step()["run"]
        read = run[run.index("CURRENT=") : run.index("if [ -z")]
        assert "docker-compose.yml" in read and "docker-compose.fleet.yml" in read, read

    def test_finding_no_pin_warns_instead_of_failing_the_release(self):
        """`set -o pipefail` turns a grep that matches nothing into a failed
        pipeline, and `set -e` then kills the step — which runs AFTER the tag is
        pushed. So a compose file without a pin would turn a successful release
        red over a cosmetic edit: the exact failure the retry logic below exists
        to prevent, reappearing a few lines earlier.
        """
        run = bump_step()["run"]
        read = run[run.index("CURRENT=") : run.index("if [ -z")]
        assert "|| true" in read, "a grep miss still fails the step:\n" + read
        guard = run[run.index("if [ -z") : run.index('if [ "$CURRENT" = "$SERIES" ]')]
        assert "::warning::" in guard and "exit 0" in guard, guard

    def test_both_compose_files_are_covered(self):
        run = bump_step()["run"]
        assert "docker-compose.yml" in run
        assert "docker-compose.fleet.yml" in run


class TestTheSeriesArithmetic:
    """The shell's series extraction, exercised directly.

    Verified end to end against the real compose files on a Linux host with GNU
    grep 3.12 before this was written; these pin the arithmetic so a later edit
    cannot quietly change it.
    """

    @staticmethod
    def _series(tag: str) -> str:
        version = tag.removeprefix("v")
        return version.rsplit(".", 1)[0]

    def test_a_minor_release(self):
        assert self._series("v1.16.0") == "1.16"

    def test_a_patch_release_keeps_the_series(self):
        assert self._series("v1.16.3") == "1.16"

    def test_a_major_release(self):
        assert self._series("v2.0.0") == "2.0"

    def test_a_two_digit_minor(self):
        """A naive cut on the first dot would give "1"."""
        assert self._series("v1.100.2") == "1.100"
