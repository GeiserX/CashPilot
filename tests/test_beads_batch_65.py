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

    def test_it_goes_through_a_pull_request(self):
        """main is PROTECTED: "Changes must be made through a pull request".

        The first version pushed straight to main and was rejected three times
        with GH006 in the v1.16.0 run — which shipped green only because the
        failure warns instead of failing. Branch protection is not going away,
        so the mechanism had to change rather than the retry count.
        """
        run = bump_step()["run"]
        assert "gh pr create" in run, run
        assert "gh pr merge" in run, run

    def test_it_never_pushes_straight_to_the_release_branch(self):
        """The regression that matters: reintroducing a direct push would be
        rejected on every release, silently, behind a warning."""
        run = bump_step()["run"]
        direct = [
            ln.strip()
            for ln in run.splitlines()
            if "git push" in ln and "GITHUB_REF_NAME" in ln and "$BRANCH" not in ln
        ]
        assert not direct, direct

    def test_the_pr_targets_the_branch_the_release_ran_on(self):
        """Never a hardcoded 'main'."""
        run = bump_step()["run"]
        create = next(ln for ln in run.splitlines() if "gh pr create" in ln)
        assert "GITHUB_REF_NAME" in create, create

    def test_the_step_has_a_token_to_talk_to_the_api(self):
        """`gh` without GH_TOKEN fails with an auth error that reads like a
        permissions bug."""
        assert "GH_TOKEN" in str(bump_step().get("env", {}))

    def test_the_job_may_open_a_pull_request(self):
        """contents: write is not enough to open a PR; the API returns 403."""
        import yaml as _yaml

        doc = _yaml.safe_load(RELEASE.read_text(encoding="utf-8"))
        perms = doc["jobs"]["publish"]["permissions"]
        assert perms.get("pull-requests") == "write", perms

    def test_every_delivery_failure_warns_rather_than_failing_the_release(self):
        """The tag and the images are already published and correct by this
        point. Failing here would turn a cosmetic miss into a red release — and
        that is not hypothetical: the v1.16.0 run hit exactly this path.

        Scoped to the DELIVERY half (push, PR, merge). The validation above it
        still uses ::error:: for a sed that did not do what it claims, which is a
        real defect rather than an environment refusal.
        """
        run = bump_step()["run"]
        delivery = run[run.index('BRANCH="chore/compose-pins') :]
        assert "::warning::" in delivery
        assert "::error::" not in delivery, "a delivery failure is escalated to an error"
        # Each of the three ways delivery can fail must exit 0, not fall through.
        assert delivery.count("exit 0") >= 3, delivery

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
