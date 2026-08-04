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

import re
from pathlib import Path

import pytest

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
