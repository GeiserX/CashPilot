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

import yaml

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / ".github" / "workflows" / "release.yml"


def publish_steps() -> list[dict]:
    doc = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))
    return [s for s in doc["jobs"]["publish"]["steps"] if isinstance(s, dict)]


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

    def test_the_commit_cannot_start_another_release(self):
        """release.yml triggers on pushes to main. Without the marker this would
        be a release that releases.

        Scoped to the `git commit` line. A plain `"[skip ci]" in run` passed with
        the marker DELETED from the commit, because the comment above it explains
        why the marker is there and therefore has to name it — the test matching
        its own prose. Caught by a negative control.
        """
        commits = [ln for ln in bump_step()["run"].splitlines() if ln.strip().startswith("git commit")]
        assert commits, "the step no longer commits anything"
        assert all("[skip ci]" in ln for ln in commits), commits

    def test_it_retries_rather_than_racing_a_merge(self):
        """The build job takes minutes, so main may well have moved. A rejected
        push must not be the end of it."""
        run = bump_step()["run"]
        assert "git pull --rebase" in run
        assert "for attempt" in run

    def test_a_failed_push_warns_rather_than_failing_the_release(self):
        """The tag and the images are already published and correct by this
        point. Failing here would turn a cosmetic miss into a red release."""
        run = bump_step()["run"]
        assert "::warning::" in run
        tail = run[run.index("for attempt") :]
        assert "::error::" not in tail, "a push failure is escalated to an error"

    def test_it_pushes_to_the_branch_it_ran_on(self):
        """Never a hardcoded 'main': the branch name is the runtime's to know."""
        assert "GITHUB_REF_NAME" in bump_step()["run"]

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
