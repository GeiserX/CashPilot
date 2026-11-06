"""release.yml must start for every image build.yml publishes, and must not
gate a release on the compose pins the release itself moves.

build.yml builds the tunnel sidecar from Dockerfile.tunnel on every release,
but a change to that file or to tunnel/ matched no push path, so it merged
with no release and no image carried it. That the detect step then builds the
worker for such a change is tested in test_release_triggers.py.

The ci job ran the pin-drift test while the release's own pin PR was still
open, so an app/ merge in that window failed and shipped nothing (#574 waited
for v1.70.0).
"""

from __future__ import annotations

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


def test_the_release_gate_skips_only_the_pin_drift_test():
    steps = _release()["jobs"]["ci"]["steps"]
    run = next(s["run"] for s in steps if "pytest" in str(s.get("run", "")))
    assert f"--deselect {DRIFT}" in run, "the release gate runs the pin-drift test its own pin PR fixes"
    assert run.count("--deselect") == 1 and " -k " not in run and " -m " not in run, run


def test_pull_requests_still_run_the_pin_drift_test():
    text = (WORKFLOWS / "test.yml").read_text(encoding="utf-8")
    assert "uv run pytest" in text and "--deselect" not in text
