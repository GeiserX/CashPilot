"""Guards on the release and docs-deploy workflows.

* Two Auto Release runs overlapped on 2026-11-11. Both read v2.2.9 as the last
  tag, both computed v2.3.0, and both pushed cashpilot:2.3.0 and :latest, built
  from different commits. The workflow must queue its runs.
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
        assert concurrency.get("group"), concurrency
        # A cancelled run can leave images pushed with no tag; never cancel.
        assert concurrency.get("cancel-in-progress") is False, concurrency


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
