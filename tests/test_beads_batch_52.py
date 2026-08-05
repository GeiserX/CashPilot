"""The sidebar printed a hardcoded version, ~150 releases stale.

``app/templates/base.html`` read::

    <span class="sidebar-footer-version">CashPilot v0.2.49</span>

while the running release was v1.11.34. Everything needed to do it properly was
already in place and already correct — ``Dockerfile`` sets ``CASHPILOT_VERSION``
from the build arg, ``build.yml`` passes the resolved release, and
``version.current()`` reads it. Verified on the live container: the environment
said ``1.11.34`` and ``version.current()`` returned ``1.11.34``. The template
simply ignored all of it.

That is worse than cosmetic. It is the only place a user can see which version
they are running, so every bug report from this UI carried a version 150
releases wrong — and the fleet page, which computes skew from
``version.current()``, disagreed with the sidebar about what the UI even was.

The fix renders ``version.display()`` through a Jinja **global**, so no handler
has to thread it and a new template cannot reintroduce a literal by copy-paste.

The sweep below is the part that matters long-term: it fails for *any* template
that hardcodes a version-looking literal, not just the one line that was wrong.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = sorted((ROOT / "app" / "templates").rglob("*.html"))

#: A literal that looks like a version being shown to a person.
VERSION_LITERAL = re.compile(r"v\d+\.\d+(\.\d+)?\b")


class TestNoTemplateHardcodesAVersion:
    def test_there_are_templates_to_check(self):
        """An empty glob would make the sweep below vacuously green."""
        assert len(TEMPLATES) >= 5, f"only found {len(TEMPLATES)} templates"

    @pytest.mark.parametrize("path", TEMPLATES, ids=[p.name for p in TEMPLATES])
    def test_it_does_not_print_a_version_literal(self, path):
        """Catches the next template, not just the one that was wrong.

        Comment lines are excluded: a template may legitimately *explain* that
        v0.2.49 was once hardcoded here without reintroducing it.
        """
        offenders = [
            (n, line.strip())
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if VERSION_LITERAL.search(line) and "{#" not in line and "<!--" not in line
        ]
        assert not offenders, f"{path.name} hardcodes a version a human will read: {offenders}"


class TestTheSidebarUsesTheRuntimeVersion:
    def _footer_line(self):
        text = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
        return next(line for line in text.splitlines() if "sidebar-footer-version" in line)

    def test_the_footer_still_exists(self):
        """The premise. If the element is gone, the tests below prove nothing."""
        assert "sidebar-footer-version" in self._footer_line()

    def test_it_calls_the_global(self):
        assert "app_version()" in self._footer_line()

    def test_the_global_is_registered_on_the_shared_environment(self):
        from app import deps

        assert "app_version" in deps.templates.env.globals

    def test_it_renders_the_running_version(self, monkeypatch):
        """Drives the real Jinja environment, not a string match."""
        from app import deps, version

        monkeypatch.setenv("CASHPILOT_VERSION", "9.9.9")
        # Re-register: the global holds a reference to the callable, which reads
        # the environment each call, so this proves it is not captured at import.
        rendered = deps.templates.env.from_string(self._footer_line()).render()
        assert "9.9.9" in rendered, rendered
        assert version.display() == "v9.9.9"


class TestItNeverInventsAVersion:
    """ "absent is not zero, and not true" — a build that does not know says so."""

    def test_a_release_build_reads_as_a_version(self, monkeypatch):
        from app import version

        monkeypatch.setenv("CASHPILOT_VERSION", "1.11.34")
        assert version.display() == "v1.11.34"

    @pytest.mark.parametrize(("value", "expected"), [("", "dev"), ("dev", "dev"), ("latest", "latest")])
    def test_a_non_release_build_never_reads_as_a_version(self, monkeypatch, value, expected):
        """`latest` passes through deliberately, and that is the honest answer.

        A container built from the floating :latest tag is NOT a dev build, so
        calling it "dev" would be its own small lie — and "latest" tells the user
        something actionable (you are on a moving tag; pin a version). The
        invariant that matters is only that none of these render as a number.
        """
        from app import version

        monkeypatch.setenv("CASHPILOT_VERSION", value)
        shown = version.display()
        assert shown == expected
        assert not VERSION_LITERAL.match(shown), f"{value!r} rendered as a version: {shown!r}"

    def test_a_dev_build_is_not_rendered_as_vdev(self, monkeypatch):
        """The `v` is added by display(), so it must not be added to `dev`."""
        from app import version

        monkeypatch.setenv("CASHPILOT_VERSION", "dev")
        assert not version.display().startswith("v")

    def test_the_unset_case_matches_what_the_dockerfile_defaults_to(self):
        """Dockerfile: ARG CASHPILOT_VERSION=dev. The two must agree."""
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        assert "ARG CASHPILOT_VERSION=dev" in dockerfile

        from app import version

        assert version.UNKNOWN == "dev"


class TestTheBuildStillSuppliesTheVersion:
    """The template fix is worthless if the value stops arriving."""

    def test_the_dockerfile_promotes_the_arg_to_an_env_var(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        assert "ENV CASHPILOT_VERSION=$CASHPILOT_VERSION" in dockerfile

    def test_the_build_workflow_passes_the_resolved_release(self):
        import yaml

        doc = yaml.safe_load((ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8"))
        build_args = [
            str(step.get("with", {}).get("build-args", ""))
            for job in doc["jobs"].values()
            for step in (job.get("steps") or [])
            if isinstance(step.get("with"), dict)
        ]
        assert any("CASHPILOT_VERSION=" in a for a in build_args), (
            "nothing passes the version into the image, so it would always read dev"
        )
