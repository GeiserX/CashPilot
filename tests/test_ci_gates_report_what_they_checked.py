"""refine-loop segment 1: guards that did not guard what they claimed.

Five independent places where a check looked like it was protecting something
and was not. None of them changes what the application does; all of them change
what the project can conclude from a green run.

1. The nightly collector-live-check collects **zero** tests — no test carries the
   ``live`` marker — masks pytest's exit 5, and is therefore green every morning.
   "Green" meant both "every provider still matches its collector" and "nothing
   was checked at all", and it was always the second. The masking stays (a job
   that fails every night trains people to ignore it); the empty case now says so
   in the step summary.

2. ``verify-tags`` was the only job in build.yml that talked to Docker Hub
   without logging in, and it discarded stderr. An anonymous rate limit — shared
   per egress IP with every other project on GitHub-hosted runners — printed
   ``MISSING`` for images that had published perfectly, and the ``::error::``
   then asserted a partial release that had not happened. Because verify-tags
   failing fails release.yml's ``build``, which ``publish`` needs, the run then
   withheld the git tag and the GitHub Release for a complete release.

3. release.yml's ``ci`` job — the one the release is actually gated on, since
   test.yml gates nothing — ran the suite on Python 3.12 while both images ship
   3.14. ``uv sync --frozen`` resolves markers per interpreter, so the two gates
   really did install different wheels. This is the shape of CashPilot-de1,
   where a different resolution silently covered 65 of 76 routes.

4. build.yml and lint.yml installed ruff unpinned while release.yml used the
   lockfile's. A ruff release that adds a default rule turned the **release** red
   on a commit that changed nothing, in the same run whose ``ci`` job had just
   passed lint on the pinned version. They also disagreed on scope (``app/`` vs
   ``.``).

5. ``.beads/`` was kept out of git only by ``.git/info/exclude``, which is local
   to one clone and is not itself tracked. The backlog holds real wallet
   addresses and this repository is public, so the protection had to travel with
   the repo.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

SHIPPED_PYTHON = "3.14"
"""The interpreter both Dockerfiles use. Derived below, never assumed."""


def _wf(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _steps(job):
    return job.get("steps") or []


class TestTheNightlyLiveCheckAdmitsWhenItCheckedNothing:
    """It may stay green on an empty run; it may not stay silent about it."""

    def _text(self):
        return (WORKFLOWS / "collector-live-check.yml").read_text(encoding="utf-8")

    def test_no_test_currently_carries_the_live_marker(self):
        """The premise. If this ever fails, the job started doing real work."""
        # Excludes THIS file, which necessarily names the marker in order to
        # talk about it — the first version of this test matched its own prose
        # and reported live tests that do not exist.
        marked = [
            p
            for p in (ROOT / "tests").rglob("*.py")
            if p != Path(__file__).resolve() and "@pytest.mark.live" in p.read_text(encoding="utf-8")
        ]
        assert not marked, (
            f"live tests now exist ({[p.name for p in marked]}) — the 'nothing was checked' "
            "summary is no longer the normal case and this file should be revisited"
        )

    def test_it_still_masks_the_empty_run(self):
        """Failing every night is what trains people to ignore the alert.

        Behaviour is proven by the executing test below; this only pins that the
        exit status is CAPTURED rather than re-read later, which is the mistake
        that made the summary unreachable.
        """
        text = self._text()
        assert "rc=${PIPESTATUS[0]}" in text
        assert '[ "$rc" = "5" ]' in text

    def test_it_writes_the_empty_case_to_the_step_summary(self):
        text = self._text()
        assert "GITHUB_STEP_SUMMARY" in text, "an empty run is still indistinguishable from a clean one"

    def test_the_summary_says_nothing_was_checked(self):
        """A neutral note would be read as success. It has to be explicit."""
        text = self._text()
        assert "NOT active" in text
        assert "no collector was checked against a real API" in text

    @pytest.mark.parametrize(
        ("pytest_exit", "expect_rc", "expect_summary"),
        [(5, 0, True), (0, 0, False), (1, 1, False)],
        ids=["empty-run-is-masked-and-announced", "clean-run-stays-quiet", "real-failure-still-reddens"],
    )
    def test_the_step_behaves_correctly_when_actually_run(self, pytest_exit, expect_rc, expect_summary):
        """Executes the step's shell against a stubbed pytest, rather than reading it.

        The first version of this class asserted only that one string appeared
        before another in the file. That passed against a step which could never
        emit the summary at all: ``PIPESTATUS`` is overwritten by every
        subsequent command, including the ``[ ... ]`` test that was on the right
        of the ``||``, so the later read always saw that test's own status
        instead of pytest's. A string test cannot see a bug like that; only
        running it can.
        """
        import os
        import subprocess
        import tempfile

        script = next(
            step["run"]
            for job in _wf("collector-live-check.yml")["jobs"].values()
            for step in _steps(job)
            if "pytest" in str(step.get("run", ""))
        )
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "uv"
            stub.write_text(f"#!/bin/sh\nexit {pytest_exit}\n")
            stub.chmod(0o755)
            summary = Path(tmp) / "summary.md"
            summary.write_text("")
            env = {**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}", "GITHUB_STEP_SUMMARY": str(summary)}
            result = subprocess.run(["bash", "-e", "-c", script], cwd=tmp, env=env, capture_output=True, text=True)
            # Read INSIDE the context manager: the directory is gone after it.
            written = summary.read_text()

        assert result.returncode == expect_rc, (
            f"pytest exiting {pytest_exit} should leave the step at rc={expect_rc}; got {result.returncode}"
        )
        assert ("NOT active" in written) is expect_summary

    def test_a_real_failure_can_still_reach_the_issue_filing_step(self):
        """Masking everything would turn a masking bug into a silencing bug."""
        doc = _wf("collector-live-check.yml")
        job = next(j for j in doc["jobs"].values() if any("pytest" in str(s.get("run", "")) for s in _steps(j)))
        assert any(str(s.get("if", "")).strip() == "failure()" for s in _steps(job)), (
            "nothing reacts to a genuine live-test failure any more"
        )


class TestTheTagVerifierCanTellApartMissingAndUnreachable:
    def _job(self):
        return _wf("build.yml")["jobs"]["verify-tags"]

    def test_it_authenticates_to_the_registry(self):
        """It was the only Docker Hub caller here that did not."""
        assert any("docker/login-action" in str(s.get("uses", "")) for s in _steps(self._job())), (
            "anonymous manifest inspects share a per-IP rate limit and fail this gate for images that published fine"
        )

    def test_it_pins_the_same_action_version_as_its_siblings(self):
        """A second pin for one action is drift, and a guessed SHA is worse."""
        doc = _wf("build.yml")
        pins = {
            str(s.get("uses"))
            for job in doc["jobs"].values()
            for s in _steps(job)
            if "docker/login-action" in str(s.get("uses", ""))
        }
        assert len(pins) == 1, f"docker/login-action is pinned to more than one version: {sorted(pins)}"

    def test_it_keeps_the_registry_response(self):
        runs = " ".join(str(s.get("run", "")) for s in _steps(self._job()))
        assert "err=$(docker manifest inspect" in runs

    def test_it_no_longer_discards_stderr(self):
        runs = " ".join(str(s.get("run", "")) for s in _steps(self._job()))
        assert 'inspect "$tag" >/dev/null 2>&1' not in runs, "the registry's actual answer is thrown away again"

    def test_it_prints_that_response_on_failure(self):
        """Captured but unprinted would be exactly as useless."""
        runs = " ".join(str(s.get("run", "")) for s in _steps(self._job()))
        assert "${err}" in runs

    def test_the_error_no_longer_asserts_a_single_cause(self):
        runs = " ".join(str(s.get("run", "")) for s in _steps(self._job()))
        assert "::error::A release tag is missing." not in runs, (
            "it states a partial release as fact when an auth or rate-limit failure looks identical"
        )


class TestTheReleaseGateRunsWhatShips:
    def _dockerfile_python(self, name):
        line = next(
            line for line in (ROOT / name).read_text(encoding="utf-8").splitlines() if line.startswith("FROM python:")
        )
        return line.split("FROM python:")[1].split("-")[0]

    @pytest.mark.parametrize("dockerfile", ["Dockerfile", "Dockerfile.worker"])
    def test_the_images_ship_the_python_this_file_pins(self, dockerfile):
        """Derives the expectation instead of hardcoding it twice."""
        assert self._dockerfile_python(dockerfile) == SHIPPED_PYTHON

    def _python_versions(self, workflow, job):
        return {
            str(s["with"]["python-version"])
            for s in _steps(_wf(workflow)["jobs"][job])
            if isinstance(s.get("with"), dict) and "python-version" in s["with"]
        }

    def test_the_release_gate_uses_it(self):
        """release.yml's `ci` is what gates the release; test.yml gates nothing."""
        assert self._python_versions("release.yml", "ci") == {SHIPPED_PYTHON}

    def test_the_standalone_suite_uses_it_too(self):
        assert self._python_versions("test.yml", "test") == {SHIPPED_PYTHON}

    def test_the_release_job_really_does_depend_on_that_gate(self):
        """If `release` stopped needing `ci`, none of the above would matter."""
        assert "ci" in _wf("release.yml")["jobs"]["release"]["needs"]


class TestEveryLintGateReachesTheSameVerdict:
    """Three gates, one commit — they must not be able to disagree."""

    LINT_JOBS = [("build.yml", "lint"), ("lint.yml", "ruff")]

    @pytest.mark.parametrize(("workflow", "job"), LINT_JOBS)
    def test_it_does_not_install_a_floating_ruff(self, workflow, job):
        for step in _steps(_wf(workflow)["jobs"][job]):
            run = str(step.get("run", "")).strip()
            # Matched as a PATTERN: `run != "pip install ruff"` was satisfied by
            # `pip install ruff -U`, `pip install ruff --quiet`, or any two-line
            # run block.
            assert not re.search(r"pip install\b[^\n]*\bruff\b", run), (
                f"{workflow}:{job} lints with whatever ruff released today: {run}"
            )

    @pytest.mark.parametrize(("workflow", "job"), LINT_JOBS)
    def test_it_resolves_ruff_from_the_lockfile(self, workflow, job):
        runs = " ".join(str(s.get("run", "")) for s in _steps(_wf(workflow)["jobs"][job]))
        assert "uv sync --frozen" in runs
        assert "uv run ruff check ." in runs, f"{workflow}:{job} does not lint the whole tree with the pinned ruff"

    @pytest.mark.parametrize(("workflow", "job"), LINT_JOBS)
    def test_every_ruff_invocation_goes_through_uv(self, workflow, job):
        """`uv sync` puts ruff in .venv, NOT on PATH.

        Deleting `pip install ruff` while leaving a bare `ruff format --check .`
        does not fall back to a pinned ruff -- it exits 127. The earlier version
        of this class asserted only the *check* command and was blind to a format
        step that could no longer run at all.
        """
        for step in _steps(_wf(workflow)["jobs"][job]):
            run = str(step.get("run", "")).strip()
            if not run or "ruff" not in run:
                continue
            assert run.startswith("uv run ruff"), f"{workflow}:{job} invokes ruff outside the synced environment: {run}"

    def test_the_lint_job_still_gates_the_builds(self):
        """The point of pinning it is that it can fail a release."""
        doc = _wf("build.yml")
        for job in ("build-ui", "build-worker"):
            assert "lint" in doc["jobs"][job]["needs"]

    def test_the_build_lint_checks_formatting_too(self):
        runs = " ".join(str(s.get("run", "")) for s in _steps(_wf("build.yml")["jobs"]["lint"]))
        assert "ruff format --check ." in runs


class TestTheBacklogCannotBeCommitted:
    """It holds real wallet addresses and this repository is public."""

    def test_the_committed_gitignore_excludes_it(self):
        """.git/info/exclude is local to one clone and is not tracked."""
        entries = {
            line.strip() for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines() if line.strip()
        }
        assert ".beads/" in entries

    def test_git_agrees_that_it_is_ignored_by_that_file(self):
        """Proves the rule is effective, not merely present."""
        import subprocess

        if not (ROOT / ".git").exists():
            pytest.skip("not a git checkout (sdist/export); the .gitignore assertion above still holds")
        # Checks a path INSIDE the directory, not the directory itself.
        # `.beads/` is a directory-only pattern, and git can only tell that a
        # path is a directory if it exists on disk -- so `check-ignore .beads`
        # answers "not ignored" on any fresh checkout where the tracker has not
        # been initialised, which is every CI run. This test passed locally and
        # failed on CI for exactly that reason.
        result = subprocess.run(
            ["git", "check-ignore", "-v", ".beads/config.yaml"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, ".beads contents are not ignored at all"
        assert result.stdout.startswith(".gitignore:"), (
            f"still relying on a non-portable exclude: {result.stdout.strip()}"
        )

    def test_the_reason_is_recorded_next_to_the_rule(self):
        """Without it, a later 'fix' restores the usual commit-the-beads convention."""
        # Anchored on the RULE line, not the first occurrence of the string:
        # the explanation itself mentions .beads/, so `text.index` landed inside
        # the comment it was meant to be reading.
        lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        rule = next(i for i, line in enumerate(lines) if line.strip() == ".beads/")
        preceding = "\n".join(lines[max(0, rule - 12) : rule])
        assert "PUBLIC" in preceding and "wallet addresses" in preceding

    def test_no_beads_file_is_tracked(self):
        """The rule only prevents new adds; this catches one already in the index."""
        import subprocess

        tracked = subprocess.run(
            ["git", "ls-files", ".beads"], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()
        assert not tracked, f"wallet addresses are committed to a public repo: {tracked}"
