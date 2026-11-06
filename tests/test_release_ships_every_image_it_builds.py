"""release.yml must release for every image build.yml publishes, and must not
gate a release on the compose pins the release itself moves.

build.yml builds the tunnel sidecar from Dockerfile.tunnel on every release,
but a change to that file or to tunnel/ matched neither the path filter nor
the change detector, so it merged with no release and no image carried it.

The ci job ran the pin-drift test while the release's own pin PR was still
open, so an app/ merge in that window failed and shipped nothing (#574 waited
for v1.70.0).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.test_beads_batch_65 import path_filter_matches, release_push_paths

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
DRIFT = (
    "tests/test_compose_image_pins.py::TestTheComposePinTracksReleases::test_the_pin_matches_the_newest_released_series"
)


def _release() -> dict:
    return yaml.safe_load((WORKFLOWS / "release.yml").read_text(encoding="utf-8"))


def _built_dockerfiles() -> list[str]:
    doc = yaml.safe_load((WORKFLOWS / "build.yml").read_text(encoding="utf-8"))
    files = []
    for job in doc["jobs"].values():
        for step in job.get("steps") or []:
            f = (step.get("with") or {}).get("file")
            if f:
                files.append(f)
    return files


def test_build_yml_builds_the_tunnel_image():
    """Guards the check below against passing on an empty list."""
    assert "Dockerfile.tunnel" in _built_dockerfiles()


@pytest.mark.parametrize("path", [*_built_dockerfiles(), "tunnel/cp-tunnel", "tunnel/cp-probe"])
def test_the_path_filter_covers_every_built_image(path):
    assert path_filter_matches(release_push_paths(), path), f"a change to {path} starts no release"


def _detector(tmp_path: Path, changed: str) -> dict[str, str]:
    """Run the 'Detect what changed' step in a scratch repo where `changed`
    is the only file touched since the last tag."""
    steps = _release()["jobs"]["release"]["steps"]
    script = next(s for s in steps if s.get("id") == "changes")["run"]
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]
    (tmp_path / "Dockerfile.worker").write_text((ROOT / "Dockerfile.worker").read_text(encoding="utf-8"))
    target = tmp_path / changed
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("v1\n")
    # Run inside a git hook, GIT_DIR and friends point at the real repository;
    # drop them so every command here stays in the scratch one.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for cmd in (["git", "init", "-q"], [*git, "add", "-A"], [*git, "commit", "-qm", "base"], [*git, "tag", "v1.0.0"]):
        subprocess.run(cmd, cwd=tmp_path, env=env, check=True)
    target.write_text("v2\n")
    subprocess.run([*git, "commit", "-qam", "fix: change it"], cwd=tmp_path, env=env, check=True)
    out = tmp_path / "out"
    env["GITHUB_OUTPUT"] = str(out)
    subprocess.run(["bash", "-e", "-c", script], cwd=tmp_path, env=env, check=True, capture_output=True)
    return dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)


@pytest.mark.parametrize("changed", ["Dockerfile.tunnel", "tunnel/cp-probe"])
def test_a_tunnel_only_change_cuts_a_release(tmp_path, changed):
    outputs = _detector(tmp_path, changed)
    version = next(s for s in _release()["jobs"]["release"]["steps"] if s.get("id") == "version")
    fired = [
        k
        for k in ("ui", "worker", "tunnel")
        if outputs.get(k) == "true" and f"steps.changes.outputs.{k} == 'true'" in version["if"]
    ]
    assert fired, f"{changed} changed alone: detector said {outputs}, version step runs on {version['if']!r}"


def test_a_docs_only_change_still_cuts_no_release(tmp_path):
    """The control: the detector must still be able to say no."""
    outputs = _detector(tmp_path, "docs/x.md")
    assert {outputs.get(k) for k in ("ui", "worker", "tunnel")} == {"false"}, outputs


def test_the_release_gate_skips_only_the_pin_drift_test():
    steps = _release()["jobs"]["ci"]["steps"]
    run = next(s["run"] for s in steps if "pytest" in str(s.get("run", "")))
    assert f"--deselect {DRIFT}" in run, "the release gate runs the pin-drift test its own pin PR fixes"
    assert run.count("--deselect") == 1 and " -k " not in run and " -m " not in run, run


def test_pull_requests_still_run_the_pin_drift_test():
    text = (WORKFLOWS / "test.yml").read_text(encoding="utf-8")
    assert "uv run pytest" in text and "--deselect" not in text
