"""The referral registry audit (CashPilot-4jtc).

Referral links are revenue. Two real incidents shaped these rules: ProxyBase
migrated domains and the deployed link stopped attributing, and Bytebenefit sat
wrongly dead with a bare URL for ~5 months of unattributed signups. The audit
must catch the regression shape (a recorded code missing from the URL) hard,
surface known-program-no-code as an action item, and treat "nobody checked"
as a research list -- never as false, and never as a failure.
"""

import importlib.util
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("referral_check", ROOT / "scripts" / "referral_check.py")
referral_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(referral_check)


def _svc(**over):
    base = {
        "slug": "example",
        "status": "active",
        "referral": {"signup_url": "https://example.com/?ref=MYCODE", "code": "MYCODE"},
    }
    base.update(over)
    return base


class TestTheRegressionShape:
    def test_a_clean_coded_service_has_no_findings(self):
        """Control: if this fixture produced findings, every test below could
        be failing for fixture reasons rather than rule reasons."""
        f = referral_check.audit([_svc()])
        assert f == {"errors": [], "actions": [], "unknowns": []}

    def test_a_code_missing_from_the_url_is_an_error(self):
        """The negative control for the whole audit: strip the code from the
        URL (the ProxyBase domain-migration shape) and the audit must go red."""
        svc = _svc(referral={"signup_url": "https://example.com/", "code": "MYCODE"})
        f = referral_check.audit([svc])
        assert len(f["errors"]) == 1
        assert "not anchored" in f["errors"][0]

    def test_a_hostname_coincidence_is_not_attribution(self):
        """`"grass" in "https://app.grass.io/register"` is True for the wrong
        reason. Anchoring is what makes the check mean what it claims."""
        svc = _svc(referral={"signup_url": "https://app.grass.io/register", "code": "grass"})
        f = referral_check.audit([svc])
        assert len(f["errors"]) == 1
        assert "not anchored" in f["errors"][0]

    def test_every_real_anchor_shape_is_accepted(self):
        """The three shapes the live catalog actually uses."""
        for url in (
            "https://dashboard.honeygain.com/ref/SERGIB4014",  # path segment
            "https://example.com/?ref=SERGIB4014",  # query value
            "https://spide.network/register.html?SERGIB4014",  # bare query key
        ):
            assert referral_check.code_attributes_url("SERGIB4014", url), url

    def test_a_code_with_no_signup_url_is_an_error(self):
        svc = _svc(referral={"code": "MYCODE"})
        f = referral_check.audit([svc])
        assert len(f["errors"]) == 1
        assert "no referral.signup_url" in f["errors"][0]

    def test_the_error_fires_for_dead_services_too(self):
        """A dead service keeps its code, so a resurrection comes back
        attributed. Bytebenefit is why."""
        svc = _svc(
            status="dead",
            referral={"signup_url": "https://example.com/", "code": "MYCODE"},
        )
        assert len(referral_check.audit([svc])["errors"]) == 1

    def test_an_empty_code_is_an_error_not_a_pass(self):
        svc = _svc(referral={"signup_url": "https://example.com/", "code": ""})
        f = referral_check.audit([svc])
        assert len(f["errors"]) == 1
        assert "empty" in f["errors"][0]

    def test_code_with_program_false_is_a_contradiction(self):
        svc = _svc(
            referral={
                "signup_url": "https://example.com/?ref=MYCODE",
                "code": "MYCODE",
                "program": False,
            }
        )
        f = referral_check.audit([svc])
        assert len(f["errors"]) == 1
        assert "program: false" in f["errors"][0]


class TestThreeValuedProgram:
    """Absent is not "no", and unknown is not a failure."""

    def test_known_program_without_code_is_an_action_item(self):
        svc = _svc(referral={"signup_url": "https://example.com", "program": True})
        f = referral_check.audit([svc])
        assert f["errors"] == []
        assert len(f["actions"]) == 1

    def test_verified_no_program_bare_url_is_fully_clean(self):
        svc = _svc(referral={"signup_url": "https://example.com", "program": False})
        f = referral_check.audit([svc])
        assert f == {"errors": [], "actions": [], "unknowns": []}

    def test_absent_program_is_unknown_not_false_and_not_an_action(self):
        svc = _svc(referral={"signup_url": "https://example.com"})
        f = referral_check.audit([svc])
        assert f["errors"] == []
        assert f["actions"] == []
        assert len(f["unknowns"]) == 1

    def test_a_dead_bare_service_is_not_even_unknown(self):
        """Research effort belongs on services users can see."""
        svc = _svc(status="dead", referral={"signup_url": "https://example.com"})
        assert referral_check.audit([svc]) == {
            "errors": [],
            "actions": [],
            "unknowns": [],
        }

    def test_garbage_program_values_are_errors_not_silence(self):
        """The vanishing bucket: `program: "no"` satisfies neither the True arm
        nor the None arm, so without a type gate the service produces NO
        finding at all and drops off the research backlog while the tool exits
        0. app/catalog.py learned this same lesson with `disclosure: TODO`."""
        for garbage in ("false", "true", "no", "yes", "TODO", 1, 0):
            svc = _svc(referral={"signup_url": "https://example.com", "program": garbage})
            f = referral_check.audit([svc])
            assert len(f["errors"]) == 1, f"program={garbage!r} vanished silently"
            assert "must be true, false, or absent" in f["errors"][0]

    def test_an_active_service_with_no_signup_url_at_all_is_an_action(self):
        """A vanished signup link is a gap users hit, not a research topic."""
        svc = _svc(referral={})
        f = referral_check.audit([svc])
        assert f["errors"] == []
        assert len(f["actions"]) == 1
        assert "nowhere to sign up" in f["actions"][0]

    def test_a_non_mapping_referral_block_is_an_error_not_a_crash(self):
        svc = _svc(referral="TODO")
        f = referral_check.audit([svc])
        assert len(f["errors"]) == 1
        assert "must be a mapping" in f["errors"][0]


class TestTheLoaderRefusesToSkip:
    """An audit that silently drops a broken file reports it as fine."""

    def test_an_empty_yaml_file_names_itself(self, tmp_path):
        (tmp_path / "bandwidth").mkdir()
        bad = tmp_path / "bandwidth" / "empty.yml"
        bad.write_text("")
        try:
            referral_check.load_services(tmp_path)
        except SystemExit as exc:
            assert "empty.yml" in str(exc)
        else:
            raise AssertionError("an empty file loaded as a service")

    def test_unparseable_yaml_names_itself(self, tmp_path):
        (tmp_path / "bandwidth").mkdir()
        bad = tmp_path / "bandwidth" / "broken.yml"
        bad.write_text("referral: [unclosed")
        try:
            referral_check.load_services(tmp_path)
        except SystemExit as exc:
            assert "broken.yml" in str(exc)
        else:
            raise AssertionError("unparseable YAML loaded as a service")


class TestTheRealCatalog:
    """The audit runs against the shipped catalog in CI; pin both modes."""

    def test_the_shipped_catalog_has_no_errors(self):
        result = subprocess.run(
            [sys.executable, "scripts/referral_check.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_strict_mode_currently_fails_on_the_repocket_gap(self):
        """Control for --strict: it must be a genuinely harder gate. If this
        starts passing, the repocket code was added -- move this assertion to
        expect success rather than deleting it."""
        result = subprocess.run(
            [sys.executable, "scripts/referral_check.py", "--strict"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1, result.stdout
        assert "repocket" in result.stdout

    def test_strict_mode_passes_on_a_clean_catalog(self, tmp_path):
        """The control for the control: if --strict always exited 1, the test
        above would keep passing while the gate meant nothing."""
        (tmp_path / "bandwidth").mkdir()
        (tmp_path / "bandwidth" / "clean.yml").write_text(
            'slug: clean\nstatus: active\nreferral:\n  signup_url: "https://example.com/?ref=OK"\n  code: "OK"\n'
        )
        result = subprocess.run(
            [
                sys.executable,
                "scripts/referral_check.py",
                "--strict",
                "--services-dir",
                str(tmp_path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
