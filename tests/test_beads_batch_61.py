"""CashPilot-ein: three releases shipped one worker image, reporting the wrong version.

``cashpilot-worker:1.13.0``, ``:1.14.0`` and ``:1.14.1`` all resolved to a single
digest whose baked ``CASHPILOT_VERSION`` was ``1.13.0``. Every worker on the
fleet page therefore reported a version it was not running — and a *wrong*
version reads as a **match**, hiding exactly the staleness that version
reporting exists to reveal.

The cause was an optimisation, not an accident. When change detection said the
worker source had not changed, ``build.yml`` re-pointed the new release tags at
the previous image with ``docker buildx imagetools create``, which copies a
manifest. But the version is baked into the image (``ARG`` → ``ENV``), so the
two releases' images are *not* equivalent and the copy asserted something false.

Two things had to change:

* build both images on every release — the saving was small, the correctness
  cost was not;
* verify the **artifact** rather than the label. The existing guard checks that a
  published tag *resolves*, and a tag pointing at a stale image resolves
  perfectly, which is why it passed three times.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / ".github" / "workflows" / "build.yml"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"


def build_doc() -> dict:
    return yaml.safe_load(BUILD.read_text(encoding="utf-8"))


def release_doc() -> dict:
    return yaml.safe_load(RELEASE.read_text(encoding="utf-8"))


class TestNoImageIsEverRetagged:
    """Copying a manifest asserts an equivalence the baked version breaks."""

    def test_the_retag_jobs_are_gone(self):
        jobs = set(build_doc()["jobs"])
        assert "retag-ui" not in jobs, "retag-ui copies a manifest whose baked version is stale"
        assert "retag-worker" not in jobs

    def test_nothing_copies_a_manifest_any_more(self):
        """`imagetools create` is the specific mechanism that did this."""
        text = BUILD.read_text(encoding="utf-8")
        offenders = [
            line.strip()
            for line in text.splitlines()
            if "imagetools create" in line and not line.lstrip().startswith("#")
        ]
        assert not offenders, offenders

    def test_no_job_depends_on_a_removed_one(self):
        """A dangling `needs` makes the whole workflow invalid, not just skipped."""
        doc = build_doc()
        names = set(doc["jobs"])
        for job, spec in doc["jobs"].items():
            needs = spec.get("needs") or []
            needs = [needs] if isinstance(needs, str) else needs
            missing = set(needs) - names
            assert not missing, f"{job} needs jobs that no longer exist: {missing}"

    def test_nothing_READS_from_the_floating_latest_tag(self):
        """The retag sourced its manifest from `:latest`.

        Narrow on purpose. PUBLISHING `:latest` alongside the semver tags is
        normal and still happens; my first version of this test forbade every
        mention and failed on those publish targets — the test was wrong, not
        the workflow. What must never happen is READING an image from a floating
        tag to derive a release artifact, because whatever `latest` happens to
        point at is then what the release inherits.

        Executable lines only: the comment explaining the fix has to name
        `:latest` to be understood.
        """
        code = [ln for ln in BUILD.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#")]
        reads = re.compile(r"(imagetools create|docker pull|^FROM)\b.*cashpilot(-worker)?:latest")
        offenders = [ln.strip() for ln in code if reads.search(ln.strip())]
        assert not offenders, offenders


class TestBothImagesAreBuiltOnEveryRelease:
    def test_the_release_forces_both_builds(self):
        """Change detection still decides whether to RELEASE, not whether to BUILD."""
        with_ = release_doc()["jobs"]["build"]["with"]
        assert with_["build_ui"] is True, f"build_ui = {with_['build_ui']!r}"
        assert with_["build_worker"] is True, f"build_worker = {with_['build_worker']!r}"

    def test_both_build_jobs_still_exist(self):
        jobs = set(build_doc()["jobs"])
        assert {"build-ui", "build-worker"} <= jobs

    def test_both_still_receive_the_version_as_a_build_arg(self):
        """If the arg stops flowing, every image silently reports `dev`."""
        doc = build_doc()
        for job in ("build-ui", "build-worker"):
            args = [
                str(step.get("with", {}).get("build-args", ""))
                for step in doc["jobs"][job]["steps"]
                if isinstance(step.get("with"), dict)
            ]
            assert any("CASHPILOT_VERSION=" in a for a in args), f"{job} no longer passes the version"


class TestTheGuardChecksTheArtifactNotTheLabel:
    def _verify_steps(self) -> list[dict]:
        return build_doc()["jobs"]["verify-tags"]["steps"]

    def test_the_resolve_check_is_still_there(self):
        """The new check complements it; it does not replace it."""
        names = [s.get("name", "") for s in self._verify_steps()]
        assert any("resolve" in n.lower() for n in names), names

    def test_a_version_assertion_exists(self):
        names = [s.get("name", "") for s in self._verify_steps()]
        assert any("version" in n.lower() for n in names), names

    def test_it_compares_against_the_release_input(self):
        """Comparing against anything else could agree with itself."""
        step = next(s for s in self._verify_steps() if "version" in s.get("name", "").lower())
        assert "inputs.version" in str(step.get("env", {}))

    def test_it_strips_the_tag_prefix(self):
        """The input is `v1.2.3`; the image bakes the bare number."""
        step = next(s for s in self._verify_steps() if "version" in s.get("name", "").lower())
        assert "${VERSION#v}" in step["run"]

    def test_it_reads_the_env_from_the_pulled_image(self):
        """A manifest does not carry the config, so inspecting --raw would not see it."""
        step = next(s for s in self._verify_steps() if "version" in s.get("name", "").lower())
        assert "docker image inspect" in step["run"]
        assert "CASHPILOT_VERSION=" in step["run"]

    def test_it_fails_the_run_rather_than_warning(self):
        step = next(s for s in self._verify_steps() if "version" in s.get("name", "").lower())
        assert "exit 1" in step["run"]
        assert "::error::" in step["run"]

    def test_it_checks_the_worker_tags_too(self):
        """The worker is the image that was actually wrong."""
        step = next(s for s in self._verify_steps() if "version" in s.get("name", "").lower())
        env = str(step.get("env", {}))
        assert "worker_tags" in env, env

    def test_a_failed_pull_fails_the_run_rather_than_skipping(self):
        """A check that can silently opt out is worse than no check.

        My first version `continue`d on a pull failure, reasoning that the
        resolve step above owned it. It does not: that step uses `docker
        manifest inspect`, which can succeed while a pull fails, so a registry
        hiccup left the version unverified with `bad` still 0 — and the release
        published looking verified. (CodeRabbit, PR #254.)
        """
        step = next(s for s in self._verify_steps() if "version" in s.get("name", "").lower())
        run = step["run"]

        # Scoped to the pull branch ALONE. Two earlier versions of this
        # assertion passed against a deliberately broken workflow:
        #   * `"PULL FAILED" in run` also matched the ::error:: text, which
        #     mentions it -- the test matching its own prose;
        #   * a `bad=1 in pull_block` slice that ran to `done <<<` swallowed the
        #     legitimate `bad=1` in the version-mismatch branch below it.
        start = run.index("if ! err=$(docker pull")
        branch = run[start : run.index("fi", start)]
        assert "bad=1" in branch, f"a failed pull does not mark the run failed:\n{branch}"
        assert "owns that failure" not in run, "the silent-skip rationale is back"

    def test_it_keeps_no_runtime_state_in_tmp(self):
        """Replaced by a here-string, which also avoids the subshell that made
        the neighbouring step use a file in the first place."""
        step = next(s for s in self._verify_steps() if "version" in s.get("name", "").lower())
        assert "/tmp" not in step["run"]

    def test_the_loop_does_not_run_in_a_subshell(self):
        """`while` on the right of a pipe loses `bad`, which is how this class of
        check silently passes."""
        step = next(s for s in self._verify_steps() if "version" in s.get("name", "").lower())
        run = step["run"]
        assert "done <<<" in run, "the loop no longer reads from a here-string"
        assert "| while" not in run and "|while" not in run

    def test_it_tells_the_reader_not_to_re_tag(self):
        """Re-tagging is the obvious 'fix' and it reproduces the defect."""
        step = next(s for s in self._verify_steps() if "version" in s.get("name", "").lower())
        assert "rebuild" in step["run"].lower()


class TestTheComparisonItselfIsCorrect:
    """The shell logic, exercised directly against the real-world values.

    Validated against the registry as it stood: the worker tagged 1.14.1 reports
    1.13.0 (must fail), and the UI tagged 1.14.1 reports 1.14.1 (must pass). A
    guard that flags everything is as useless as one that flags nothing.
    """

    @staticmethod
    def _matches(reported: str, released: str) -> bool:
        return reported == released.removeprefix("v")

    def test_the_real_defect_is_caught(self):
        assert not self._matches("1.13.0", "v1.14.1")

    def test_a_correct_image_is_not_flagged(self):
        assert self._matches("1.14.1", "v1.14.1")

    def test_an_unstamped_image_is_caught(self):
        """`dev` is the Dockerfile default when the arg never arrives."""
        assert not self._matches("dev", "v1.14.1")

    def test_an_empty_version_is_caught(self):
        assert not self._matches("", "v1.14.1")
