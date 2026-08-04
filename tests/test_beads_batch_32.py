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
ships, and requirements.txt is a pinned export of it rather than a second,
looser opinion.
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


class TestRequirementsTxtIsAPinnedExport:
    def _text(self):
        return (ROOT / "requirements.txt").read_text(encoding="utf-8")

    def test_every_requirement_is_pinned(self):
        loose = [
            line.strip()
            for line in self._text().splitlines()
            if line.strip() and not line.startswith((" ", "#")) and "==" not in line
        ]
        assert not loose, f"these are not pinned, so they can resolve differently from the lock: {loose}"

    def test_it_says_it_is_generated(self):
        """A hand-edit is how it drifts back apart."""
        assert "GENERATED" in self._text()
        assert "uv export" in self._text()

    def test_it_matches_the_lockfile(self):
        """The whole point: one resolution, not two.

        Regenerate with:
            uv export --no-dev --no-hashes --format requirements-txt > requirements.txt
        """
        result = subprocess.run(
            ["uv", "export", "--no-dev", "--no-hashes", "--format", "requirements-txt"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip("uv is not available here; CI resolves from the lock directly")
        exported = {
            line.strip() for line in result.stdout.splitlines() if line.strip() and not line.startswith(("#", " "))
        }
        committed = {
            line.strip() for line in self._text().splitlines() if line.strip() and not line.startswith(("#", " "))
        }
        assert committed == exported, (
            "requirements.txt has drifted from uv.lock. Regenerate it with "
            "`uv export --no-dev --no-hashes --format requirements-txt > requirements.txt` "
            f"(only in committed: {sorted(committed - exported)}; only in lock: {sorted(exported - committed)})"
        )

    def test_it_still_lists_the_real_dependencies(self):
        """Guards against this passing because the file was emptied."""
        text = self._text().lower()
        for package in ("fastapi", "uvicorn", "cryptography", "httpx"):
            assert package in text, f"{package} disappeared from requirements.txt"
