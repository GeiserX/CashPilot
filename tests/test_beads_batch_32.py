"""CashPilot-de1: CI and local development tested different code.

``pyproject.toml`` + ``uv.lock`` are the source of truth, and the Dockerfile
installs with ``uv sync --frozen`` — so what SHIPS is pinned. But the test
workflow installed from ``requirements.txt``, which listed unpinned lower bounds
(``fastapi>=0.136.1``, ...), and then pip-installed pytest and friends by hand
on top.

The consequence is not theoretical. Local development sat on fastapi 0.136.1 /
starlette 1.0.1; CI resolved 0.141.1 / 1.3.1. On the newer pair
``include_router`` stops adding its routes to ``app.routes``, so a route sweep
silently covered 65 of 76 — a real behaviour difference that appeared only on
CI, and only because one test happened to assert something that noticed.

A green local suite was not evidence about what CI would do, nor about what a
user installing today would get.

Now every workflow that runs the suite resolves from the same lockfile the image
ships, and there is no second list at all.

The export outlived its usefulness and then did damage. requirements.txt was
kept as a pinned copy of the lock, but nothing installed from it: not the image
(`uv sync --frozen`), not CI, not the dependency graph. Dependabot's `pip`
ecosystem found it, though, and #350 bumped six pins in it — a change that
could not reach a built image, left uv.lock behind, and asked for
pydantic-core 2.48.0 next to pydantic 2.13.4, which pins pydantic-core==2.46.4
exactly. pip answers that pair with ResolutionImpossible, so the one instruction
that used the file could no longer be followed.

One lockfile, one resolution, and the bot points at it.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _workflow(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _run_steps(doc):
    for job in (doc.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            run = step.get("run")
            if run:
                yield run


class TestEveryWorkflowResolvesFromTheLockfile:
    SUITE_WORKFLOWS = ["test.yml", "collector-live-check.yml", "release.yml"]

    @pytest.mark.parametrize("name", SUITE_WORKFLOWS)
    def test_it_does_not_pip_install_requirements(self, name):
        commands = " ".join(_run_steps(_workflow(name)))
        assert "pip install -r requirements.txt" not in commands, (
            f"{name} installs from requirements.txt instead of the lockfile the image ships"
        )

    @pytest.mark.parametrize("name", SUITE_WORKFLOWS)
    def test_it_syncs_from_the_lock(self, name):
        commands = " ".join(_run_steps(_workflow(name)))
        assert "uv sync --frozen" in commands, f"{name} does not resolve from uv.lock"

    @pytest.mark.parametrize("name", ["test.yml", "collector-live-check.yml"])
    def test_it_runs_pytest_inside_that_environment(self, name):
        """`uv sync` then a bare `pytest` would run whatever pip left on PATH."""
        commands = [c for c in _run_steps(_workflow(name)) if "pytest" in c]
        assert commands, f"{name} does not run pytest at all"
        for command in commands:
            assert "uv run pytest" in command, f"{name} runs pytest outside the synced environment: {command.strip()}"

    def test_nothing_installs_test_deps_by_hand(self):
        """Hand-assembling the test environment is how it diverged.

        Checked per STEP. Joining every run block into one string let the
        pattern span two unrelated commands — "pip install uv" in one step and
        "uv run pytest" three steps later — and reported a violation that did
        not exist.
        """
        offenders = [
            command.strip()
            for command in _run_steps(_workflow("test.yml"))
            for line in command.splitlines()
            if re.search(r"pip install\b.*\bpytest\b", line)
            for command in [line]
        ]
        assert not offenders, f"test.yml still pip-installs pytest directly; put it in the dev extra: {offenders}"


class TestTheDevExtraCoversWhatTheSuiteNeeds:
    def _dev(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        return {re.split(r"[><=\[]", d)[0].strip().lower() for d in data["project"]["optional-dependencies"]["dev"]}

    @pytest.mark.parametrize("package", ["pytest", "pytest-asyncio", "pytest-cov", "docker", "tzdata"])
    def test_it_is_declared(self, package):
        assert package in self._dev(), f"{package} is imported by the suite but not in the dev extra"

    def test_pyyaml_comes_from_the_runtime_deps(self):
        """It is a real runtime dependency, not a test-only one."""
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        runtime = {re.split(r"[><=\[]", d)[0].strip().lower() for d in data["project"]["dependencies"]}
        assert "pyyaml" in runtime


class TestThereIsOneDependencySourceOfTruth:
    """A second list of the app's dependencies is a second resolution.

    ``docs/requirements-docs.txt`` is deliberately exempt. It is genuinely
    installed — docs.yml pip-installs it to run MkDocs — and it must stay OUT of
    uv.lock, because release.yml treats uv.lock as a release trigger and a
    mkdocs-material bump would otherwise cut an app release that changes nothing
    in the app.
    """

    #: Install surfaces that are real, separate toolchains rather than a copy of
    #: what uv.lock already pins.
    EXEMPT = {"docs/requirements-docs.txt"}

    def _tracked(self):
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            # No git here — measure the working tree instead, so the check still
            # measures something rather than passing by default.
            return [str(path.relative_to(ROOT)) for path in ROOT.rglob("requirements*.txt")]
        return result.stdout.splitlines()

    def test_no_requirements_export_is_committed(self):
        exports = [
            path for path in self._tracked() if Path(path).name.startswith("requirements") and path not in self.EXEMPT
        ]
        assert not exports, (
            "a requirements export is back. Nothing installs from one here — the image and CI "
            f"both `uv sync --frozen` — so it can only drift from uv.lock or ship a pair pip "
            f"cannot resolve: {exports}"
        )

    def test_the_dev_instructions_install_from_the_lock(self):
        """CLAUDE.md is the only place that ever told a human how to install."""
        text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        assert "pip install -r requirements" not in text, "CLAUDE.md sends developers to a requirements export again"
        assert "uv sync --frozen" in text, "CLAUDE.md no longer tells developers to install from the lock"


class TestDependabotUpdatesWhatShips:
    """A dependency PR that cannot reach a built image is worse than none."""

    def _release_paths(self):
        """Everything release.yml treats as a reason to cut a release."""
        doc = _workflow("release.yml")
        # PyYAML parses a bare `on:` key as the boolean True.
        triggers = doc.get("on", doc.get(True))
        return set(triggers["push"]["paths"])

    def _python_update(self):
        config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
        python = [u for u in config["updates"] if u["package-ecosystem"] in {"uv", "pip", "poetry", "pipenv"}]
        assert len(python) == 1, f"expected exactly one Python update config, found {len(python)}"
        return python[0]

    def test_the_python_ecosystem_is_uv(self):
        ecosystem = self._python_update()["package-ecosystem"]
        assert ecosystem == "uv", (
            f"Dependabot is set to '{ecosystem}', which edits requirements files. "
            "uv.lock is what the image builds from; anything else bumps a file nobody installs."
        )

    @pytest.mark.parametrize("manifest", ["uv.lock", "pyproject.toml"])
    def test_the_files_it_edits_can_trigger_a_release(self, manifest):
        """uv edits pyproject.toml and uv.lock. Both must be release triggers.

        #350 bumped requirements.txt, which release.yml does not watch, so even
        a correct bump there would have sat on main without ever being built.
        """
        assert manifest in self._release_paths(), (
            f"Dependabot updates {manifest} but release.yml does not treat it as a release trigger, "
            "so a dependency bump would never reach Docker Hub"
        )

    def test_major_bumps_stay_ignored(self):
        """Kept from the pip config on purpose: majors land by hand, reviewed."""
        ignored = self._python_update()["ignore"]
        assert any(
            entry.get("dependency-name") == "*" and "version-update:semver-major" in entry.get("update-types", [])
            for entry in ignored
        ), "major updates are no longer ignored"
