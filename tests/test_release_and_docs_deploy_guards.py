"""Guards on the release and docs-deploy workflows.

* On 2026-11-11 an Auto Release run pushed cashpilot:2.3.0 and :latest and was
  cancelled before its publish job pushed the v2.3.0 git tag. The next run read
  v2.2.9 as the last tag, computed v2.3.0 again and overwrote the images from
  another commit. The version step must skip a version whose images exist, and
  the workflow must queue its runs (per ref) so two never bump at once.
* Only the "pending" job filtered pre-release tags. With a v3.0.0-rc.1 tag the
  version step would read "0-rc" as the patch number. Every lookup of the last
  release tag must skip pre-release tags.
* A single "status: 500" from GitHub Pages failed the docs deploy, nothing
  re-ran it, and the public site stayed stale. The deploy must retry.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
DOCS = ROOT / ".github" / "workflows" / "docs.yml"

# The lines in release.yml that read the last release tag into a variable.
_TAG_LOOKUP = re.compile(r"^\s*(?:LAST_TAG|LATEST)=\$\(git tag -l .*\)\s*$", re.M)


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class TestReleaseRunsNeverOverlap:
    def test_the_workflow_queues_its_runs(self):
        concurrency = _load(RELEASE).get("concurrency")
        assert isinstance(concurrency, dict), "release.yml has no workflow-level concurrency"
        # Per ref: a dispatch from a branch must not replace a pending main run.
        assert "github.ref" in str(concurrency.get("group")), concurrency
        # A cancelled run can leave images pushed with no tag; never cancel.
        assert concurrency.get("cancel-in-progress") is False, concurrency


def _version_step() -> str:
    steps = _load(RELEASE)["jobs"]["release"]["steps"]
    (step,) = [s for s in steps if s.get("id") == "version"]
    return step["run"]


class TestAPublishedVersionIsNeverReused:
    """Run the real "Get latest version tag" step against a repo whose last
    tag is v2.2.9 plus a feat commit, with a fake Docker Hub on which 2.3.0
    (and optionally 2.3.1) is already published."""

    def _run(self, tmp_path: Path, attempt: str, published: tuple[str, ...]) -> str:
        repo = tmp_path / "repo"
        repo.mkdir()

        def git(*args: str) -> None:
            subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

        ident = ("-c", "user.name=t", "-c", "user.email=t@t")
        git("init", "-q")
        git(*ident, "commit", "-q", "--allow-empty", "-m", "fix: a")
        git("tag", "v2.2.9")
        git(*ident, "commit", "-q", "--allow-empty", "-m", "feat: b")

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        curl = bin_dir / "curl"
        cases = " ".join(f"*/tags/{v})" + " printf 200 ;;" for v in published)
        curl.write_text(f'#!/bin/sh\nfor a; do url="$a"; done\ncase "$url" in {cases} *) printf 404 ;; esac\n')
        curl.chmod(0o755)

        out = tmp_path / "out"
        script = _version_step().replace("${{ github.run_attempt }}", attempt)
        subprocess.run(
            ["bash", "-eo", "pipefail", "-c", script],
            cwd=repo,
            env={"PATH": f"{bin_dir}:/usr/bin:/bin", "GITHUB_OUTPUT": str(out)},
            capture_output=True,
            text=True,
            check=True,
        )
        lines = dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)
        return lines["new_tag"]

    def test_a_first_attempt_skips_published_versions(self, tmp_path):
        assert self._run(tmp_path, "1", ("2.3.0", "2.3.1")) == "v2.3.2"

    def test_a_free_version_is_taken_as_computed(self, tmp_path):
        assert self._run(tmp_path, "1", ()) == "v2.3.0"

    def test_a_rerun_of_the_same_run_keeps_its_version(self, tmp_path):
        assert self._run(tmp_path, "2", ("2.3.0",)) == "v2.3.0"


class TestTheLastReleaseTagSkipsPreReleases:
    def _repo(self, tmp_path: Path) -> Path:
        def git(*args: str) -> None:
            subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

        git("init", "-q")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "c")
        for tag in ("v2.2.9", "v2.3.0", "v3.0.0-rc.1"):
            git("tag", tag)
        return tmp_path

    def test_every_lookup_returns_the_last_release(self, tmp_path):
        lookups = _TAG_LOOKUP.findall(RELEASE.read_text(encoding="utf-8"))
        assert len(lookups) == 3, lookups  # pending, Detect what changed, Get latest version tag
        repo = self._repo(tmp_path)
        for line in lookups:
            var = line.strip().split("=", 1)[0]
            out = subprocess.run(
                ["bash", "-c", f'{line.strip()}\necho "${var}"'],
                cwd=repo,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            assert out == "v2.3.0", f"{line.strip()!r} returned {out!r}"


class TestThePagesDeployRetries:
    def test_a_failed_deploy_gets_two_more_tries(self):
        steps = _load(DOCS)["jobs"]["deploy"]["steps"]
        deploys = [s for s in steps if str(s.get("uses", "")).startswith("actions/deploy-pages@")]
        assert len(deploys) == 3, deploys
        # The first two may fail; the last one fails the job.
        assert [s.get("continue-on-error", False) for s in deploys] == [True, True, False]
        assert deploys[1]["if"] == f"steps.{deploys[0]['id']}.outcome == 'failure'"
        assert deploys[2]["if"] == f"steps.{deploys[1]['id']}.outcome == 'failure'"


class TestTheSiteRedeploysDaily:
    def test_docs_runs_on_a_schedule(self):
        # The release bot's pin and changelog merges start no Docs run.
        # PyYAML reads the bare `on:` key as True.
        triggers = _load(DOCS).get(True) or _load(DOCS).get("on")
        assert triggers.get("schedule"), triggers
