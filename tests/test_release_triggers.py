"""CashPilot-gn6 / CashPilot-l7t: a release that publishes nothing, silently.

`release.yml` decided what to build from two hand-maintained regexes. Both had
drifted from the Dockerfiles they were meant to mirror:

* The UI regex named 13 of 27 modules, but the UI image does
  ``COPY app/ ./app/`` — the whole directory. A change to any of the other 14
  (payouts, preflight, power, egress, lan_isolation, notify, ...) set
  ``BUILD_UI=false``, which skipped the version step, which left ``new_tag``
  empty, which skipped the tag, the GitHub Release and the whole build job.
  Skipped steps do not fail a run, so the release went GREEN having published
  nothing at all.

* The worker regex omitted ``egress.py`` and ``state_backup.py``, both COPY'd
  into the worker image and imported by ``worker_api`` at runtime. With
  ``build_worker=false`` the pipeline RETAGS the previous image, so the worker
  could be published under a new version tag containing the previous release's
  code — and ``verify-tags`` only runs ``docker manifest inspect``, which a
  retag satisfies.

The fix is to stop restating the Dockerfiles in a regex. These tests assert the
two stay in agreement, so the next module added to either image is covered
without anyone remembering.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
DOCKERFILE = ROOT / "Dockerfile"
DOCKERFILE_WORKER = ROOT / "Dockerfile.worker"

APP_MODULES = sorted(p.name for p in (ROOT / "app").glob("*.py"))


def worker_copied_modules() -> list[str]:
    """The app modules Dockerfile.worker actually COPYs, as the workflow reads them."""
    text = DOCKERFILE_WORKER.read_text(encoding="utf-8")
    return sorted(set(re.findall(r"^COPY[^#\n]*?app/([a-z_]+\.py)", text, re.M)))


class TestTheUiBuildCoversEveryModule:
    """The UI image copies app/ wholesale, so the trigger must too."""

    def test_the_ui_image_still_copies_the_whole_directory(self):
        """If this ever narrows, the blanket trigger below stops being right."""
        text = DOCKERFILE.read_text(encoding="utf-8")
        assert re.search(r"^COPY[^#\n]*\bapp/ ", text, re.M), "Dockerfile no longer copies app/ wholesale"

    def test_the_trigger_is_not_a_module_allowlist(self):
        text = RELEASE.read_text(encoding="utf-8")
        assert "app/(main|database|catalog|auth|compose_generator" not in text, (
            "the hand-maintained UI module allowlist is back"
        )

    def test_any_app_change_builds_the_ui(self):
        text = RELEASE.read_text(encoding="utf-8")
        assert "|app/)'" in text, "the UI trigger no longer matches all of app/"


class TestTheWorkerBuildMatchesItsDockerfile:
    def test_the_worker_list_is_derived_not_restated(self):
        text = RELEASE.read_text(encoding="utf-8")
        assert "Dockerfile.worker" in text
        assert "WORKER_MODULES=$(grep" in text, "the worker list is not derived from the Dockerfile"

    def test_no_hardcoded_worker_module_regex_remains(self):
        text = RELEASE.read_text(encoding="utf-8")
        assert "app/(worker_api|orchestrator|constants|catalog|fleet_key)" not in text

    @pytest.mark.parametrize("module", ["egress.py", "state_backup.py"])
    def test_the_previously_missed_modules_are_covered(self, module):
        """Both ship in the worker image and were absent from the old regex."""
        assert module in worker_copied_modules()

    def test_every_copied_module_exists(self):
        """A COPY of a deleted file would build a worker that cannot import."""
        for module in worker_copied_modules():
            assert (ROOT / "app" / module).exists(), f"Dockerfile.worker copies a missing {module}"

    def test_worker_api_imports_are_all_copied(self):
        """The real contract: what worker_api imports must be in the image.

        This is what makes a stale or missing module a crash on the user's
        machine rather than a build failure here.
        """
        source = (ROOT / "app" / "worker_api.py").read_text(encoding="utf-8")
        imported = set()
        for line in source.splitlines():
            m = re.match(r"\s*from app import (.+)", line)
            if m:
                imported |= {n.strip().split(" as ")[0] for n in m.group(1).split(",")}
        copied = {m[:-3] for m in worker_copied_modules()}
        missing = {n for n in imported if n and not n.startswith("_")} - copied
        assert not missing, f"worker_api imports modules the worker image does not contain: {sorted(missing)}"


class TestNoModuleFallsThroughBothTriggers:
    def test_every_app_module_triggers_at_least_one_build(self):
        """The defect in one line: 14 of 27 modules triggered neither.

        A change to any of them produced a green run that published nothing.
        """
        text = RELEASE.read_text(encoding="utf-8")
        ui_matches_all = "|app/)'" in text
        assert ui_matches_all, "some app modules would still trigger no build at all"

    def test_there_are_modules_to_check(self):
        """Guards against this whole file passing vacuously on an empty glob."""
        assert len(APP_MODULES) > 20, APP_MODULES


class TestTheDocsNameTheRightEncryptionKey:
    """CashPilot-dxi: six places told users the wrong variable protects credentials.

    `CASHPILOT_SECRET_KEY` signs login sessions. `CASHPILOT_ENCRYPTION_KEY` is
    the Fernet key that encrypts stored credentials, persisted at
    `/data/.fernet_key`.

    The advice was not merely wrong, it was harmful: a user who set
    `CASHPILOT_SECRET_KEY` believing their credentials were now portable would
    never back up the key file, and would lose every stored credential the
    first time the volume was recreated. README.md already had the correct
    wording; the other six places contradicted it.
    """

    DOCS = ["docs/fleet.md", "docs/getting-started.md", "docs/index.md", "unraid/cashpilot.xml", "README.md"]

    @pytest.mark.parametrize("rel", DOCS)
    def test_no_doc_claims_the_session_key_encrypts_credentials(self, rel):
        text = (ROOT / rel).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "CASHPILOT_SECRET_KEY" not in line:
                continue
            lowered = line.lower()
            if "encrypt" not in lowered:
                continue
            # A line may mention both, but only to DENY that the session key encrypts.
            assert any(
                marker in lowered
                for marker in ("does not encrypt", "not encrypt", "not `cashpilot_secret_key`", "only signs")
            ), f"{rel}: {line.strip()[:140]}"

    def test_the_real_key_is_documented_where_it_matters(self):
        for rel in ("docs/getting-started.md", "docs/fleet.md", "docs/index.md", "unraid/cashpilot.xml"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            assert "CASHPILOT_ENCRYPTION_KEY" in text, f"{rel} never mentions the key that actually encrypts"

    def test_the_key_file_is_named_so_it_can_be_backed_up(self):
        """Knowing the variable is useless without knowing what to back up."""
        text = (ROOT / "docs" / "getting-started.md").read_text(encoding="utf-8")
        assert "/data/.fernet_key" in text
        assert "back that file up" in text.lower()

    def test_the_unraid_template_exposes_it(self):
        """Unraid users configure entirely through the template."""
        text = (ROOT / "unraid" / "cashpilot.xml").read_text(encoding="utf-8")
        assert 'Target="CASHPILOT_ENCRYPTION_KEY"' in text
        assert text.count('Mask="true"') >= 2, "the encryption key must be masked like the session key"

    @pytest.mark.parametrize("rel", ["docs/index.md", "docs/fleet.md", "docs/getting-started.md"])
    def test_the_env_var_is_not_described_as_an_override(self, rel):
        """From CodeRabbit on this PR, and right.

        The key FILE always wins — app/database.py logs a warning and keeps the
        stored key when CASHPILOT_ENCRYPTION_KEY differs, because switching keys
        would make every existing credential unreadable. Calling the variable an
        "override" is wrong exactly where it matters most: someone restoring a
        backup onto an instance that still has a stale key file would expect
        their value to take effect, and it would be ignored.
        """
        text = (ROOT / rel).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "CASHPILOT_ENCRYPTION_KEY" not in line:
                continue
            assert "overridable" not in line.lower(), f"{rel}: {line.strip()[:120]}"

    def test_at_least_one_doc_states_the_precedence(self):
        """Knowing the variable exists is not enough to restore a backup with it."""
        found = [
            rel
            for rel in ("docs/index.md", "docs/fleet.md", "docs/getting-started.md")
            if "only when that file is absent" in (ROOT / rel).read_text(encoding="utf-8")
        ]
        assert len(found) >= 3, f"precedence stated in only {found}"


class TestOnlyARealDependencyChangeBuilds:
    """CashPilot-#354: a dev-tool bump cut a full release.

    ``uv.lock`` carries the dev group, both images build with
    ``uv sync --frozen --no-dev``, and the trigger matched on the filename. So
    v1.36.4 shipped for a pytest/pytest-asyncio/ruff bump: 78 entries in
    site-packages, not one different from v1.36.3, and three containers
    restarted on the fleet for a version label. Dependency PRs land weekly, so
    this was the most frequent release the project cut.

    The question that decides a release is whether the no-dev resolution moved,
    which is what ``scripts/runtime_deps_changed.py`` answers.
    """

    SCRIPT = ROOT / "scripts" / "runtime_deps_changed.py"

    def _detect_step(self) -> str:
        doc = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))
        for step in doc["jobs"]["release"]["steps"]:
            if step.get("name") == "Detect what changed":
                return step["run"]
        raise AssertionError("release.yml no longer detects what changed")

    def _answer(self, base: str, head: str) -> str:
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT), base, head, "--repo", str(ROOT)],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    @pytest.mark.parametrize("manifest", [r"pyproject\.toml", r"uv\.lock"])
    def test_the_manifests_no_longer_trigger_by_name(self, manifest):
        """Naming a manifest may gate the resolution check, never a build.

        Checked as a BLOCK, not a line. The condition that decides whether to
        run the check names both manifests too, so a line-level "does this
        mention uv.lock" flags the fix itself.
        """
        lines = self._detect_step().splitlines()
        offenders = []
        for index, line in enumerate(lines):
            if "grep -qE" not in line or manifest not in line:
                continue
            body = []
            for follower in lines[index + 1 :]:
                if follower.strip() == "fi":
                    break
                body.append(follower)
            if any("BUILD_UI" in b or "BUILD_WORKER" in b for b in body):
                offenders.append(line.strip())
        assert not offenders, (
            f"{manifest} still sets a build flag by filename, so the resolution check cannot matter: {offenders}"
        )

    def test_the_resolution_check_decides_instead(self):
        step = self._detect_step()
        assert "scripts/runtime_deps_changed.py" in step, "nothing asks whether the shipped dependencies changed"
        assert "RUNTIME_CHANGED" in step
        assert 'if [ "$RUNTIME_CHANGED" = true ]; then' in step, "the answer is computed but never acted on"

    def test_uv_is_installed_before_anything_reads_the_answer(self):
        """Without uv the script is fail-safe but useless: everything builds."""
        doc = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))
        names = [s.get("name") or s.get("uses") or "" for s in doc["jobs"]["release"]["steps"]]
        assert "Install uv" in names, f"the release job never installs uv: {names}"
        assert names.index("Install uv") < names.index("Detect what changed"), names

    def _script_module(self):
        """The script is not a package; load it from its path."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("runtime_deps_changed", self.SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_detector_uses_the_uv_the_images_build_with(self):
        """A different uv could read the lock differently from the one that
        installs it, and then the check judges a resolution nobody ships.
        Derived from the Dockerfile, so there is no second copy to drift.
        (CodeRabbit, PR #354.)
        """
        import yaml

        doc = yaml.safe_load(RELEASE.read_text(encoding="utf-8"))
        step = next(s for s in doc["jobs"]["release"]["steps"] if s.get("name") == "Install uv")
        assert "astral-sh/uv:" in step["run"], "the release job installs some uv, not the images' uv"
        assert 'pip install "uv==$UV_VERSION"' in step["run"], "the derived version is read but not installed"

    def test_the_dockerfile_still_states_a_uv_version_to_derive(self):
        """The derivation above degrades to a warning, so this is what notices."""
        found = re.findall(r"astral-sh/uv:(\d+\.\d+\.\d+)", (ROOT / "Dockerfile").read_text(encoding="utf-8"))
        assert found, "Dockerfile no longer pins a uv version, so the release job cannot match it"
        worker = re.findall(r"astral-sh/uv:(\d+\.\d+\.\d+)", (ROOT / "Dockerfile.worker").read_text(encoding="utf-8"))
        assert set(found) == set(worker), f"the two images build with different uv versions: {found} vs {worker}"

    def test_a_hash_only_change_is_a_change(self):
        """`uv sync --frozen` consumes the artifacts, not just the versions.

        A lock can gain or change an artifact for a version that already
        exists, and every `name==version` pin still reads the same. Exporting
        without hashes returned "unchanged" for something the build installs
        differently. (CodeRabbit, PR #354.)
        """
        import re as _re
        import shutil
        import tempfile

        module = self._script_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plain, tampered = root / "plain", root / "tampered"
            for target in (plain, tampered):
                target.mkdir()
                for name in module.MANIFESTS:
                    shutil.copy(ROOT / name, target / name)

            before = module._runtime_requirements(plain)
            assert before, "the baseline export produced nothing, so this test proves nothing"

            hashes = _re.findall(r"--hash=sha256:([0-9a-f]{64})", "\n".join(before))
            assert hashes, "the export carries no hashes, so a hash-only change could never be seen"

            lock = (tampered / "uv.lock").read_text(encoding="utf-8")
            flipped = ("0" if hashes[0][0] != "0" else "1") + hashes[0][1:]
            assert hashes[0] in lock
            (tampered / "uv.lock").write_text(lock.replace(hashes[0], flipped), encoding="utf-8")

            after = module._runtime_requirements(tampered)
            assert after is not None, "uv refused the tampered lock, so the comparison never happened"
            assert before != after, "a changed artifact hash reads as no change, so the release would be skipped"

    def test_no_tag_to_compare_against_still_builds(self):
        """The first release, or a checkout without tags, must not skip.

        There is nothing to diff against, so the honest answer is "changed".
        Reaching the script with an empty ref would make it compare HEAD with
        nothing and say "unchanged", which publishes no image at all.
        """
        step = self._detect_step()
        block = step[step.index("RUNTIME_CHANGED=false") :]
        block = block[: block.index("BUILD_UI")]
        assert 'if [ -n "$LAST_TAG" ]; then' in block, (
            "the detector calls the script even with no tag to compare against"
        )
        assert "RUNTIME_CHANGED=true" in block, "the no-tag branch does not force a build"

    def test_a_dev_only_bump_does_not_build(self):
        """v1.36.4 over v1.36.3: pytest, pytest-asyncio and ruff, nothing shipped."""
        assert self._answer("v1.36.3", "v1.36.4") == "false"

    def test_a_runtime_bump_does_build(self):
        """v1.36.3 over v1.36.2: starlette, uvicorn, idna and friends."""
        assert self._answer("v1.36.2", "v1.36.3") == "true"

    def test_a_ref_it_cannot_read_builds(self):
        """Not knowing must never read as "nothing to do"."""
        assert self._answer("v99.99.99", "HEAD") == "true"

    def test_a_missing_uv_builds(self, tmp_path):
        """The one failure that would otherwise silently disable every release."""
        stripped = dict(os.environ, PATH=str(tmp_path))
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT), "v1.36.3", "v1.36.4", "--repo", str(ROOT)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env=stripped,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "true", result.stdout
        assert "uv is not on PATH" in result.stderr

    def test_the_tags_it_measures_against_exist(self):
        """Guards the two tests above from passing on a repo with no tags."""
        for tag in ("v1.36.2", "v1.36.3", "v1.36.4"):
            result = subprocess.run(
                ["git", "-C", str(ROOT), "rev-parse", "--verify", f"{tag}^{{commit}}"],
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, f"{tag} is missing, so the behaviour tests measure nothing"
