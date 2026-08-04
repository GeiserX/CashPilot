"""CashPilot-l6c: neither image knew what version it was.

Both apps hardcoded ``version="0.1.0"`` while releases are tag-driven and had
reached 1.11.x. The heartbeat carried no version, the workers table had no
column for one, and nothing in the fleet page, the logs or any payload said what
either half was running.

That makes UI/worker skew undetectable. On Unraid the UI and the worker are two
separate Community Applications entries, each on ``:latest``, so updating one
and not the other is a single click — and the result is a 1.11 UI against a 1.4
worker with no indication anywhere. The symptoms are unexplained missing data: a
worker that never reports an egress IP, a button that 404s.

The version is baked in at build time from the release tag and travels in the
heartbeat, which needs no migration because ``system_info`` is already a stored
JSON blob.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


class TestTheVersionIsHonestAboutWhatItKnows:
    def test_outside_a_release_build_it_says_dev(self, monkeypatch):
        from app import version

        monkeypatch.delenv("CASHPILOT_VERSION", raising=False)
        assert version.current() == "dev"

    def test_a_release_build_reports_its_tag(self, monkeypatch):
        from app import version

        monkeypatch.setenv("CASHPILOT_VERSION", "1.11.15")
        assert version.current() == "1.11.15"

    def test_an_empty_value_is_not_a_version(self, monkeypatch):
        """An unset build arg must not read as a release called ''."""
        from app import version

        monkeypatch.setenv("CASHPILOT_VERSION", "   ")
        assert version.current() == "dev"

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("1.11.15", "1.11"), ("v1.4.4", "1.4"), ("dev", None), ("latest", None), ("", None), (None, None)],
    )
    def test_the_series_is_what_skew_is_judged_on(self, value, expected):
        from app import version

        assert version.series(value) == expected


class TestSkewIsOnlyClaimedWhenItIsKnown:
    @pytest.mark.parametrize(
        ("ui", "worker", "skewed"),
        [
            ("1.11.15", "1.4.4", True),  # the bead's exact case
            ("1.11.15", "1.11.2", False),  # same series: patches interoperate
            ("1.11.15", None, False),  # an older worker sends nothing
            ("1.11.15", "dev", False),  # a locally built worker
            ("dev", "1.11.15", False),  # a locally built UI
            (None, None, False),
        ],
    )
    def test_it(self, ui, worker, skewed):
        from app import version

        assert version.skewed(ui, worker) is skewed

    def test_an_unknown_worker_is_not_a_mismatch(self):
        """The upgrade that introduces this must not light up every fleet.

        Every worker predating this change sends no version at all. Reporting
        that as skew would put a warning on every card in the fleet on the day
        the UI is updated, which is exactly the false alarm that teaches people
        to ignore warnings.
        """
        from app import version

        assert version.skewed("1.11.15", None) is False


class TestBothImagesLearnTheirVersion:
    @pytest.mark.parametrize("dockerfile", ["Dockerfile", "Dockerfile.worker"])
    def test_it_takes_a_build_arg(self, dockerfile):
        text = (ROOT / dockerfile).read_text(encoding="utf-8")
        assert "ARG CASHPILOT_VERSION" in text
        assert "ENV CASHPILOT_VERSION=$CASHPILOT_VERSION" in text

    @pytest.mark.parametrize("dockerfile", ["Dockerfile", "Dockerfile.worker"])
    def test_it_defaults_to_dev(self, dockerfile):
        """A local `docker build` must not claim to be a release."""
        text = (ROOT / dockerfile).read_text(encoding="utf-8")
        assert "ARG CASHPILOT_VERSION=dev" in text

    def test_the_build_passes_the_resolved_version_to_both(self):
        import yaml

        doc = yaml.safe_load((ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8"))
        builds = [
            step
            for job in doc["jobs"].values()
            for step in job.get("steps") or []
            if str(step.get("uses", "")).startswith("docker/build-push-action")
        ]
        assert len(builds) >= 2, f"expected a build step per image, found {len(builds)}"
        for step in builds:
            args = (step.get("with") or {}).get("build-args") or ""
            assert "CASHPILOT_VERSION=" in args, (
                f"a build step passes no version: {(step.get('with') or {}).get('file')}"
            )

    def test_the_worker_image_ships_the_module(self):
        """It is imported at worker startup; omitting it crashes the worker.

        Two existing tests caught this when the module was first added — the
        assertion is repeated here because it is what makes the rest reachable.
        """
        text = (ROOT / "Dockerfile.worker").read_text(encoding="utf-8")
        assert re.search(r"^COPY .*app/version\.py \./app/", text, re.M)

    @pytest.mark.parametrize("module", ["app/main.py", "app/worker_api.py"])
    def test_neither_app_hardcodes_a_placeholder(self, module):
        text = (ROOT / module).read_text(encoding="utf-8")
        assert 'version="0.1.0"' not in text, f"{module} still reports the 0.1.0 placeholder"
        assert "version.current()" in text


class TestTheWorkerReportsItAndTheUISurfacesIt:
    def test_the_heartbeat_carries_the_version(self):
        text = (ROOT / "app" / "worker_api.py").read_text(encoding="utf-8")
        i = text.index('"docker_available"')
        assert '"version": version.current()' in text[i : i + 600], "the heartbeat payload has no version"

    def test_the_workers_endpoint_reports_skew(self):
        text = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert 'w["version_skew"] = version.skewed(' in text
        assert 'w["ui_version"] = ui_version' in text

    def test_the_fleet_card_shows_it(self):
        text = (ROOT / "app" / "templates" / "fleet.html").read_text(encoding="utf-8")
        assert "sysInfo.version" in text
        assert "version_skew" in text

    def test_an_unknown_version_says_so_rather_than_nothing(self):
        """Blank space would read as "no problem" for a worker too old to say."""
        text = (ROOT / "app" / "templates" / "fleet.html").read_text(encoding="utf-8")
        assert "version unknown" in text

    def test_the_warning_says_what_to_do(self):
        """ "Different versions" without the Unraid detail is not actionable."""
        text = (ROOT / "app" / "templates" / "fleet.html").read_text(encoding="utf-8")
        assert "two separate apps" in text
