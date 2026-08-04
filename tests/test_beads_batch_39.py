"""CashPilot-85s: the release was announced before the images existed.

release.yml pushed the annotated tag and published the GitHub Release with
``draft: false``, and only THEN ran the build. Any failure in it — a Docker Hub
outage, a rate limit, or the arm64 QEMU emulation, which is the slowest and most
failure-prone step — left an announced version with no images.

A user sees the release notification, edits their compose to the new series,
runs ``docker compose pull``, and gets ``manifest unknown``.

Recovery was manual, and the repo's own CLAUDE.md flags the trap: re-running
release.yml fails at ``git tag -a`` with ``already_exists``, so someone had to
hand-dispatch build.yml with the version.

Publishing last removes the failure mode entirely, and the tag step is idempotent
so a re-run after a partial failure works rather than dying on a tag it created
itself.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / ".github" / "workflows" / "release.yml"


def workflow():
    return yaml.safe_load(RELEASE.read_text(encoding="utf-8"))


def job(name):
    return workflow()["jobs"][name]


def steps_of(name):
    return job(name).get("steps") or []


def _uses(steps, prefix):
    return [s for s in steps if str(s.get("uses", "")).startswith(prefix)]


class TestNothingIsAnnouncedBeforeTheImagesExist:
    def test_the_publish_job_waits_for_the_build(self):
        needs = job("publish").get("needs") or []
        assert "build" in needs, "the release can still be announced without images"

    def test_the_github_release_is_created_there(self):
        assert _uses(steps_of("publish"), "softprops/action-gh-release"), (
            "the GitHub Release is not created by the job that waits for the build"
        )

    def test_the_tag_is_pushed_there_too(self):
        commands = " ".join(s.get("run", "") for s in steps_of("publish"))
        assert "git push origin" in commands

    def test_exactly_one_job_publishes_and_it_is_publish(self):
        """Written as a whole-file check, not per job.

        The first version parametrised over ["release", "build"] and passed an
        empty list for "build" — which is a reusable-workflow call with no steps
        — so that half asserted nothing at all. Counting across every job is
        both simpler and actually says what it means.
        """
        publishers = [
            name
            for name, spec in workflow()["jobs"].items()
            if _uses(spec.get("steps") or [], "softprops/action-gh-release")
        ]
        assert publishers == ["publish"], f"the GitHub Release is created by {publishers}, expected only 'publish'"

    def test_the_release_job_no_longer_pushes_a_tag(self):
        commands = " ".join(s.get("run", "") for s in steps_of("release"))
        assert "git push origin" not in commands, "the tag is still pushed before the build"

    def test_the_build_still_runs_after_the_version_is_decided(self):
        assert "release" in (job("build").get("needs") or [])


class TestARerunAfterAFailedBuildWorks:
    """The trap CLAUDE.md names: `git tag -a` with already_exists."""

    def test_the_tag_step_checks_before_creating(self):
        commands = " ".join(s.get("run", "") for s in steps_of("publish"))
        assert "git rev-parse -q --verify" in commands, "a re-run would die on the tag it created itself"

    def test_it_checks_the_remote_before_pushing(self):
        commands = " ".join(s.get("run", "") for s in steps_of("publish"))
        assert "git ls-remote --exit-code --tags origin" in commands

    def test_it_still_creates_the_tag_when_absent(self):
        """The control: idempotence must not mean never tagging."""
        commands = " ".join(s.get("run", "") for s in steps_of("publish"))
        assert "git tag -a" in commands


class TestThePublishJobCanDoItsWork:
    def test_it_can_write_to_the_repository(self):
        """Pushing a tag and creating a release both need contents: write."""
        assert (job("publish").get("permissions") or {}).get("contents") == "write"

    def test_it_checks_out_with_tags(self):
        checkout = _uses(steps_of("publish"), "actions/checkout")
        assert checkout, "the job cannot tag without a checkout"
        assert (checkout[0].get("with") or {}).get("fetch-tags") is True

    def test_it_only_runs_when_there_is_a_version(self):
        assert "new_tag" in str(job("publish").get("if", ""))

    def test_it_uses_the_version_the_release_job_decided(self):
        """Recomputing it here could pick a different number."""
        text = RELEASE.read_text(encoding="utf-8")
        i = text.index("  publish:")
        assert "needs.release.outputs.new_tag" in text[i:]


class TestTheWorkflowIsStillValid:
    def test_it_parses(self):
        assert workflow()["jobs"]

    def test_every_job_dependency_exists(self):
        jobs = workflow()["jobs"]
        for name, spec in jobs.items():
            needs = spec.get("needs") or []
            needs = [needs] if isinstance(needs, str) else needs
            for dep in needs:
                assert dep in jobs, f"{name} depends on missing job {dep}"

    def test_the_build_is_still_reached(self):
        """A publish job that waits on a build nobody runs would never fire."""
        assert workflow()["jobs"]["build"].get("uses", "").endswith("build.yml")
