"""Tests for scripts/check_catalog_liveness.py.

Only the pure decision logic is exercised — no network calls and no docker, so
the suite stays deterministic and offline. What matters here is that the script
cannot report a *live* service as dead (which would send someone deleting a
working catalog entry) and cannot report an empty catalog as healthy.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_catalog_liveness.py"
_spec = importlib.util.spec_from_file_location("check_catalog_liveness", _SCRIPT)
liveness = importlib.util.module_from_spec(_spec)
# Register before exec: the module's @dataclass resolves its string annotations
# (PEP 563) through sys.modules, which fails if the module isn't there yet.
sys.modules["check_catalog_liveness"] = liveness
_spec.loader.exec_module(liveness)


class TestClassifyStatus:
    @pytest.mark.parametrize("code", [200, 201, 204, 301, 302])
    def test_alive_codes(self, code):
        assert liveness.classify_status(code) == liveness.OK

    @pytest.mark.parametrize("code", [401, 403, 405, 429])
    def test_guarded_but_alive(self, code):
        # Cloudflare/bot guards and "HEAD not allowed" prove the host answered.
        assert liveness.classify_status(code) == liveness.OK

    @pytest.mark.parametrize("code", [400, 404, 410])
    def test_client_errors_are_dead(self, code):
        assert liveness.classify_status(code) == liveness.DEAD

    @pytest.mark.parametrize("code", [500, 502, 503])
    def test_server_errors_are_unreachable_not_dead(self, code):
        # A provider having a bad afternoon is not a retired service.
        assert liveness.classify_status(code) == liveness.UNREACHABLE


class TestReferralCodeLost:
    def test_collapse_to_bare_homepage_is_lost(self):
        assert liveness.referral_code_lost("https://p.com/signup?ref=CODE", "https://p.com/")

    def test_landing_on_a_real_page_is_fine(self):
        # Plenty of healthy links drop the query after setting a cookie.
        assert not liveness.referral_code_lost("https://p.com/signup?ref=CODE", "https://p.com/welcome")

    def test_query_preserved_is_fine(self):
        assert not liveness.referral_code_lost("https://p.com/signup?ref=CODE", "https://p.com/signup?ref=CODE")

    def test_bare_to_bare_is_not_a_loss(self):
        # Nothing to lose if the configured URL had no path or query to begin with.
        assert not liveness.referral_code_lost("https://p.com/", "https://p.com/")


class TestCheckImage:
    def test_empty_image_is_skipped(self):
        status, detail = liveness.check_image("")
        assert status == liveness.SKIPPED
        assert "not Docker-deployable" in detail

    def test_manifest_found_is_ok(self):
        with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stderr="")):
            assert liveness.check_image("repo/img:1")[0] == liveness.OK

    @pytest.mark.parametrize("err", ["toomanyrequests: too many requests", "unauthorized: authentication required"])
    def test_rate_limit_is_unreachable_not_dead(self, err):
        # Reporting a rate-limited registry as "dead" would send us deleting live services.
        with patch.object(subprocess, "run", return_value=MagicMock(returncode=1, stderr=err)):
            assert liveness.check_image("repo/img:1")[0] == liveness.UNREACHABLE

    def test_missing_manifest_is_dead(self):
        with patch.object(subprocess, "run", return_value=MagicMock(returncode=1, stderr="manifest unknown")):
            assert liveness.check_image("repo/gone:1")[0] == liveness.DEAD

    def test_docker_missing_is_unreachable(self):
        with patch.object(subprocess, "run", side_effect=OSError("no docker")):
            assert liveness.check_image("repo/img:1")[0] == liveness.UNREACHABLE


class TestLoadServices:
    def _write(self, d: Path, name: str, body: str):
        (d / name).write_text(body)

    def test_loads_and_sorts_skipping_schema(self, tmp_path):
        self._write(tmp_path, "b.yml", "slug: bravo\nname: B\n")
        self._write(tmp_path, "a.yml", "slug: alpha\nname: A\n")
        self._write(tmp_path, "_schema.yml", "slug: schema\nname: S\n")
        services, errors = liveness.load_services(tmp_path)
        assert [s["slug"] for s in services] == ["alpha", "bravo"]
        assert errors == []

    def test_unparseable_file_is_reported_not_silently_skipped(self, tmp_path):
        """A broken YAML must not let the run claim 'All good'.

        Skipping it quietly means fewer services are checked and the report is
        confidently wrong — the worst failure mode for a check like this.
        """
        self._write(tmp_path, "bad.yml", "{{{ not yaml")
        self._write(tmp_path, "good.yml", "slug: good\nname: G\n")
        services, errors = liveness.load_services(tmp_path)
        assert [s["slug"] for s in services] == ["good"]
        assert len(errors) == 1
        assert errors[0].kind == "catalog"
        assert errors[0].is_problem
        assert "bad.yml" in errors[0].target
        # A raw newline in a markdown table cell breaks the rest of the table.
        assert "\n" not in errors[0].detail
        # ...and it must reach the report, which is what the CI gate greps.
        report = liveness.build_report(errors)
        assert not report.startswith("# Catalog liveness report\n\nAll good")
        assert "could not be read" in report

    def test_file_without_slug_is_reported(self, tmp_path):
        self._write(tmp_path, "nope.yml", "name: no slug here\n")
        services, errors = liveness.load_services(tmp_path)
        assert services == []
        assert len(errors) == 1 and errors[0].is_problem


def _resp(status_code: int, url: str):
    return MagicMock(status_code=status_code, url=url)


class TestResurrectionProbe:
    """Dead/dropped services get one probe: are they alive again?

    Liveness used to skip them entirely, so a resurrection was invisible
    forever -- Bytebenefit ran ~5 months at bytebenefit.io while the catalog
    said dead (CashPilot-lv8v).
    """

    def test_alive_on_its_own_domain_is_a_finding(self):
        client = MagicMock()
        client.get.return_value = _resp(200, "https://x.com/home")
        findings = liveness.check_service(
            client, {"slug": "gone", "status": "dead", "website": "https://x.com"}, check_images=False
        )
        assert len(findings) == 1
        f = findings[0]
        assert f.kind == "resurrection"
        assert f.status == liveness.RESURRECTED
        assert f.is_problem, "a resurrection must reach the weekly issue"
        assert "never flipped automatically" in f.detail

    def test_a_dropped_service_is_not_probed_at_all(self):
        """Dropped means rejected on judgment (shady, rebranded), not died.
        gaganode's site answers 200 today -- that is expected, not news, and
        probing it would put the same non-finding in the issue every week."""
        client = MagicMock()
        findings = liveness.check_service(
            client, {"slug": "shady", "status": "dropped", "website": "https://x.com"}, check_images=False
        )
        assert len(findings) == 1
        assert findings[0].status == liveness.SKIPPED
        client.get.assert_not_called()
        client.head.assert_not_called()

    def test_the_parked_domain_control(self):
        """The negative control, straight from the incident: bytebenefit.com
        answers 200 today -- by redirecting to the atom.com marketplace. A 200
        on someone ELSE'S domain must never be claimed as a resurrection."""
        client = MagicMock()
        client.get.return_value = _resp(200, "https://www.atom.com/name/ByteBenefit")
        findings = liveness.check_service(
            client, {"slug": "gone", "status": "dead", "website": "https://bytebenefit.com"}, check_images=False
        )
        assert len(findings) == 1
        f = findings[0]
        assert f.status == liveness.SKIPPED
        assert not f.is_problem
        assert "parked" in f.detail
        assert liveness.build_report(findings).splitlines()[2].startswith("All good")

    def test_a_dead_site_that_is_still_dead_stays_quiet(self):
        client = MagicMock()
        client.get.return_value = _resp(404, "https://x.com")
        findings = liveness.check_service(
            client, {"slug": "gone", "status": "dead", "website": "https://x.com"}, check_images=False
        )
        assert findings[0].status == liveness.SKIPPED
        assert "still dead" in findings[0].detail
        assert not findings[0].is_problem
        assert not findings[0].is_inconclusive, "still-dead must not clutter the weekly inconclusive section"

    def test_an_unreachable_dead_site_stays_quiet_too(self):
        client = MagicMock()
        client.get.side_effect = liveness.httpx.ConnectError("boom")
        findings = liveness.check_service(
            client, {"slug": "gone", "status": "dead", "website": "https://x.com"}, check_images=False
        )
        assert findings[0].status == liveness.SKIPPED
        assert not findings[0].is_problem

    def test_no_website_recorded_is_skipped_without_network(self):
        client = MagicMock()
        findings = liveness.check_service(client, {"slug": "gone", "status": "dead"}, check_images=False)
        assert findings[0].status == liveness.SKIPPED
        client.get.assert_not_called()

    def test_referral_and_image_are_not_checked_for_dead_services(self):
        """The probe is one cheap GET; the rest stays retired noise."""
        client = MagicMock()
        client.get.return_value = _resp(200, "https://x.com/")
        findings = liveness.check_service(
            client,
            {
                "slug": "gone",
                "status": "dead",
                "website": "https://x.com",
                "referral": {"signup_url": "https://x.com/?r=C"},
                "docker": {"image": "x/y:1"},
            },
            check_images=True,
        )
        assert len(findings) == 1
        client.head.assert_not_called()

    def test_the_report_gets_its_own_section(self):
        findings = [liveness.Finding("gone", "resurrection", "https://x.com", liveness.RESURRECTED, "answers HTTP 200")]
        report = liveness.build_report(findings)
        assert "Possibly resurrected" in report
        assert "Verify by hand" in report
        assert not report.splitlines()[2].startswith("All good")


class TestRegistrableDomain:
    def test_www_is_the_same_site(self):
        assert liveness.registrable_domain("www.x.com") == liveness.registrable_domain("x.com")

    def test_a_subdomain_is_the_same_site(self):
        assert liveness.registrable_domain("dashboard.x.com") == liveness.registrable_domain("x.com")

    def test_a_different_domain_is_not(self):
        assert liveness.registrable_domain("atom.com") != liveness.registrable_domain("bytebenefit.com")


class TestCheckService:
    def test_dead_status_service_is_probed_for_resurrection_only(self):
        client = MagicMock()
        client.get.return_value = _resp(404, "https://x.com")
        findings = liveness.check_service(
            client, {"slug": "gone", "status": "dead", "website": "https://x.com"}, check_images=False
        )
        assert all(f.status == liveness.SKIPPED for f in findings)
        client.head.assert_not_called()  # one GET probe; no referral/image checks

    def test_referral_is_checked_separately_from_website(self):
        client = MagicMock()
        client.head.return_value = MagicMock(status_code=200, url="https://p.com/signup?ref=CODE")
        findings = liveness.check_service(
            client,
            {
                "slug": "p",
                "status": "active",
                "website": "https://p.com",
                "referral": {"signup_url": "https://p.com/signup?ref=CODE"},
            },
            check_images=False,
        )
        kinds = {f.kind for f in findings}
        assert kinds == {"website", "referral"}
        assert all(f.status == liveness.OK for f in findings)


class TestBuildReport:
    def test_clean_report_says_all_good(self):
        findings = [liveness.Finding("a", "website", "u", liveness.OK, "HTTP 200")]
        assert build_starts_ok(liveness.build_report(findings))

    def test_referral_problems_get_their_own_revenue_section(self):
        findings = [
            liveness.Finding("a", "website", "u", liveness.OK, "HTTP 200"),
            liveness.Finding("a", "referral", "https://p.com/s?ref=X", liveness.DEAD, "referral code lost"),
        ]
        report = liveness.build_report(findings)
        assert "lost revenue" in report
        assert "referral code lost" in report

    def test_skipped_entries_are_not_problems(self):
        findings = [liveness.Finding("a", "image", "", liveness.SKIPPED, "no image")]
        assert build_starts_ok(liveness.build_report(findings))


def build_starts_ok(report: str) -> bool:
    return "All good" in report


class TestInconclusiveIsNotAProblem:
    """A weekly auto-issue that cries wolf gets ignored — so 'can't tell' != 'broken'."""

    def test_unreachable_does_not_open_an_issue(self):
        findings = [
            liveness.Finding("a", "website", "https://a.com", liveness.UNREACHABLE, "ServerError"),
            liveness.Finding("b", "image", "repo/img", liveness.UNREACHABLE, "registry rate-limited or auth-gated"),
        ]
        report = liveness.build_report(findings)
        # The CI step greps for a leading "All good" to decide whether to file.
        assert report.splitlines()[2].startswith("All good")
        # ...but the detail is still visible to a human reading the run.
        assert "Could not verify" in report
        assert "rate-limited" in report

    def test_dead_still_opens_an_issue(self):
        findings = [
            liveness.Finding("a", "website", "https://a.com", liveness.UNREACHABLE, "ServerError"),
            liveness.Finding("b", "referral", "https://b.com/?r=X", liveness.DEAD, "referral code lost"),
        ]
        report = liveness.build_report(findings)
        assert not report.splitlines()[2].startswith("All good")
        assert "**1 problem(s)**" in report
        # The unreachable one is still shown, just not counted.
        assert "Could not verify" in report

    def test_image_arg_cannot_be_read_as_a_flag(self):
        import subprocess

        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            return MagicMock(returncode=0, stderr="")

        with patch.object(subprocess, "run", side_effect=fake_run):
            liveness.check_image("repo/img:1")
        assert "--" in captured["cmd"]
        assert captured["cmd"].index("--") == captured["cmd"].index("repo/img:1") - 1


class TestReferralCollapseIsInconclusive:
    """A collapsed referral URL must not be reported as a confirmed dead link.

    Regression for a real false positive: ProxyLite's `?r=CODE` returns 302 +
    a session cookie and lands on the bare homepage, which is a WORKING referral
    capture. Calling that "dead" sent us to retire a live, earning service.
    """

    def test_collapse_is_reported_but_not_counted_as_a_problem(self):
        client = MagicMock()
        client.head.return_value = MagicMock(status_code=200, url="https://p.com/")
        findings = liveness.check_service(
            client,
            {
                "slug": "p",
                "status": "active",
                "website": "https://p.com",
                "referral": {"signup_url": "https://p.com/?r=CODE"},
            },
            check_images=False,
        )
        ref = [f for f in findings if f.kind == "referral"][0]
        assert ref.status == liveness.UNREACHABLE
        assert not ref.is_problem, "a session-capture referral must not be called dead"
        assert ref.is_inconclusive
        report = liveness.build_report(findings)
        assert report.splitlines()[2].startswith("All good")
        assert "verify manually" in report

    def test_a_recorded_code_visible_after_redirect_is_conclusively_ok(self):
        """The registry upgrade: with referral.code recorded, the POSITIVE
        direction becomes conclusive -- the code is still where the provider
        reads it. (Absence stays inconclusive; session capture hides working
        codes.)"""
        client = MagicMock()
        client.head.return_value = _resp(200, "https://p.com/welcome?ref=CODE")
        findings = liveness.check_service(
            client,
            {
                "slug": "p",
                "status": "active",
                "website": "https://p.com",
                "referral": {"signup_url": "https://p.com/signup?ref=CODE", "code": "CODE"},
            },
            check_images=False,
        )
        ref = [f for f in findings if f.kind == "referral"][0]
        assert ref.status == liveness.OK
        assert "code visible" in ref.detail

    def test_a_recorded_code_that_vanished_is_still_only_inconclusive(self):
        """The code being INVISIBLE proves nothing -- ProxyLite's working
        session-capture link looks exactly like this. The registry must not
        turn a working link into a weekly 'problem'."""
        client = MagicMock()
        client.head.return_value = _resp(200, "https://p.com/")
        findings = liveness.check_service(
            client,
            {
                "slug": "p",
                "status": "active",
                "website": "https://p.com",
                "referral": {"signup_url": "https://p.com/?r=CODE", "code": "CODE"},
            },
            check_images=False,
        )
        ref = [f for f in findings if f.kind == "referral"][0]
        assert ref.status == liveness.UNREACHABLE
        assert not ref.is_problem

    def test_footer_does_not_call_a_collapse_dead(self):
        """The footer must match the classification, or it teaches the wrong lesson."""
        findings = [liveness.Finding("a", "referral", "https://p.com/?r=X", liveness.UNREACHABLE, "not visible")]
        report = liveness.build_report(findings)
        tail = report.rsplit("_`unreachable`", 1)[-1]
        assert "referral link collapsed" not in tail
        assert "no longer visible" in tail


# ---------------------------------------------------------------------------
# Declared platforms must have a build behind them
# ---------------------------------------------------------------------------


def _manifest(*platforms: str) -> str:
    """What ``docker manifest inspect -v`` prints: a list for multi-arch, one object otherwise."""
    entries = []
    for p in platforms:
        os_, arch, *variant = p.split("/")
        plat = {"os": os_, "architecture": arch}
        if variant:
            plat["variant"] = variant[0]
        entries.append({"Ref": "x", "Descriptor": {"platform": plat}})
    return json.dumps(entries if len(entries) != 1 else entries[0])


class TestPlatformFamily:
    @pytest.mark.parametrize(
        ("platform", "family"),
        [
            ("linux/amd64", "amd64"),
            ("linux/arm64", "arm64"),
            ("linux/arm64/v8", "arm64"),
            ("linux/arm/v7", "arm"),
            ("linux/arm/v5", "arm"),
            ("linux/386", None),
            ("windows/amd64", None),
            ("amd64", None),
        ],
    )
    def test_folds_variants_onto_the_family(self, platform, family):
        assert liveness.platform_family(platform) == family


class TestPublishedPlatforms:
    def test_a_manifest_list_yields_every_family(self):
        out = _manifest("linux/amd64", "linux/arm/v7", "linux/arm64/v8", "unknown/unknown")
        with patch.object(subprocess, "run", return_value=MagicMock(returncode=0, stdout=out, stderr="")):
            status, families, _ = liveness.published_platforms("repo/img")
        assert status == liveness.OK
        assert families == {"amd64", ("arm", 7), "arm64"}

    def test_a_single_arch_image_yields_its_one_family(self):
        with patch.object(
            subprocess, "run", return_value=MagicMock(returncode=0, stdout=_manifest("linux/amd64"), stderr="")
        ):
            assert liveness.published_platforms("traffmonetizer/cli_v2")[1] == {"amd64"}

    def test_a_rate_limit_is_inconclusive_not_dead(self):
        with patch.object(subprocess, "run", return_value=MagicMock(returncode=1, stdout="", stderr="toomanyrequests")):
            assert liveness.published_platforms("repo/img")[0] == liveness.UNREACHABLE

    @pytest.mark.parametrize(
        "stderr", ["manifest unknown: manifest unknown", "no such manifest: repo/gone:1", "repo/gone:1 not found"]
    )
    def test_a_registry_that_says_no_such_manifest_is_dead(self, stderr):
        with patch.object(subprocess, "run", return_value=MagicMock(returncode=1, stdout="", stderr=stderr)):
            assert liveness.published_platforms("repo/gone")[0] == liveness.DEAD

    @pytest.mark.parametrize(
        "stderr", ["dial tcp: lookup registry-1.docker.io: no such host", "Cannot connect to the Docker daemon", ""]
    )
    def test_any_other_failure_is_inconclusive_not_dead(self, stderr):
        """A DNS blip or a daemon hiccup must not raise the weekly problem count."""
        with patch.object(subprocess, "run", return_value=MagicMock(returncode=1, stdout="", stderr=stderr)):
            status, _, detail = liveness.published_platforms("repo/img")
        assert status == liveness.UNREACHABLE
        assert detail

    def test_no_docker_is_inconclusive(self):
        with patch.object(subprocess, "run", side_effect=OSError("no docker")):
            assert liveness.published_platforms("repo/img")[0] == liveness.UNREACHABLE


class TestArmVariantsAreDirectional:
    """A v7 board runs v5 and v6 builds; a Pi Zero (v6) cannot run a v7 build."""

    @pytest.mark.parametrize(
        ("platform", "norm"),
        [
            ("linux/arm/v5", ("arm", 5)),
            ("linux/arm/v7", ("arm", 7)),
            ("linux/arm", ("arm", 7)),
            ("linux/arm64/v8", "arm64"),
            ("linux/amd64", "amd64"),
        ],
    )
    def test_arm_keeps_its_variant(self, platform, norm):
        assert liveness.normalise_platform(platform) == norm

    @pytest.mark.parametrize(
        ("published", "declared", "ok"),
        [
            ({("arm", 5)}, ("arm", 7), True),  # a v5 build runs on a v7 board
            ({("arm", 7)}, ("arm", 5), False),  # a v7 build does not run on a v5 board
            ({("arm", 7)}, ("arm", 6), False),  # nor on a Pi Zero
            ({("arm", 6), ("arm", 7)}, ("arm", 7), True),
            ({"arm64"}, "arm64", True),
            ({"amd64"}, "arm64", False),
        ],
    )
    def test_coverage_follows_the_direction(self, published, declared, ok):
        assert liveness.covers(published, declared) is ok


class TestCheckPlatforms:
    """The catalog's promise versus the registry's manifest, per declared platform."""

    def _svc(self, platforms, image="repo/img", image_by_arch=None):
        docker = {"image": image, "platforms": platforms}
        if image_by_arch:
            docker["image_by_arch"] = image_by_arch
        return {"slug": "svc", "status": "active", "docker": docker}

    def _with_registry(self, answers: dict[str, str]):
        """Map image -> manifest JSON; anything else is 'manifest unknown'."""

        def _run(cmd, **_kw):
            image = cmd[-1]
            if image in answers:
                return MagicMock(returncode=0, stdout=answers[image], stderr="")
            return MagicMock(returncode=1, stdout="", stderr="manifest unknown")

        return patch.object(subprocess, "run", side_effect=_run)

    def test_a_declared_build_that_exists_is_ok(self):
        with self._with_registry({"repo/img": _manifest("linux/amd64", "linux/arm64/v8")}):
            [f] = liveness.check_platforms(self._svc(["linux/amd64", "linux/arm64"]))
        assert f.status == liveness.OK and f.kind == "platforms"

    def test_a_declared_build_that_does_not_exist_is_a_problem(self):
        """ProxyLite declared arm64 for months; the image only ever had amd64."""
        with self._with_registry({"repo/img": _manifest("linux/amd64")}):
            [f] = liveness.check_platforms(self._svc(["linux/amd64", "linux/arm64"]))
        assert f.status == liveness.DEAD and f.is_problem
        assert "arm64" in f.detail and "amd64" in f.detail

    def test_an_image_by_arch_override_covers_its_family(self):
        """Traffmonetizer: the default tag is amd64-only, the ARM tags exist under their own names."""
        svc = self._svc(
            ["linux/amd64", "linux/arm64", "linux/arm/v7"],
            image="traffmonetizer/cli_v2",
            image_by_arch={"arm64": "traffmonetizer/cli_v2:arm64v8", "arm": "traffmonetizer/cli_v2:arm32v7"},
        )
        answers = {
            "traffmonetizer/cli_v2": _manifest("linux/amd64"),
            "traffmonetizer/cli_v2:arm64v8": _manifest("linux/amd64"),  # mislabelled, but it exists
            "traffmonetizer/cli_v2:arm32v7": _manifest("linux/amd64"),
        }
        with self._with_registry(answers):
            [f] = liveness.check_platforms(svc)
        assert f.status == liveness.OK

    def test_a_declared_variant_the_image_does_not_reach_is_a_problem(self):
        """Declaring arm/v6 on a v7-only image promises Pi Zero support that is not there."""
        with self._with_registry({"repo/img": _manifest("linux/amd64", "linux/arm/v7")}):
            [f] = liveness.check_platforms(self._svc(["linux/amd64", "linux/arm/v6"]))
        assert f.status == liveness.DEAD and "arm/v6" in f.detail and "arm/v7" in f.detail

    def test_a_lower_published_variant_covers_a_higher_declared_one(self):
        with self._with_registry({"repo/img": _manifest("linux/amd64", "linux/arm/v5")}):
            [f] = liveness.check_platforms(self._svc(["linux/amd64", "linux/arm/v7"]))
        assert f.status == liveness.OK

    def test_an_unreachable_override_is_reported_but_does_not_condemn_the_entry(self):
        svc = self._svc(["linux/amd64", "linux/arm64"], image_by_arch={"arm64": "repo/img:arm64v8"})

        def _run(cmd, **_kw):
            if cmd[-1] == "repo/img":
                return MagicMock(returncode=0, stdout=_manifest("linux/amd64"), stderr="")
            return MagicMock(returncode=1, stdout="", stderr="toomanyrequests: rate limit")

        with patch.object(subprocess, "run", side_effect=_run):
            findings = liveness.check_platforms(svc)
        assert [f.status for f in findings] == [liveness.UNREACHABLE]
        assert not any(f.is_problem for f in findings)

    def test_an_override_tag_that_vanished_is_a_problem(self):
        svc = self._svc(["linux/amd64", "linux/arm64"], image_by_arch={"arm64": "repo/img:arm64v8"})
        with self._with_registry({"repo/img": _manifest("linux/amd64")}):
            findings = liveness.check_platforms(svc)
        kinds = {(f.status, f.target) for f in findings}
        assert (liveness.DEAD, "repo/img:arm64v8") in kinds  # the override itself
        assert any(f.status == liveness.DEAD and f.target == "repo/img" and "arm64" in f.detail for f in findings)

    def test_a_rate_limited_registry_is_reported_but_not_a_problem(self):
        with patch.object(subprocess, "run", return_value=MagicMock(returncode=1, stdout="", stderr="toomanyrequests")):
            [f] = liveness.check_platforms(self._svc(["linux/amd64"]))
        assert f.status == liveness.UNREACHABLE and not f.is_problem

    def test_nothing_declared_or_no_image_checks_nothing(self):
        assert liveness.check_platforms(self._svc([])) == []
        assert liveness.check_platforms(self._svc(["linux/amd64"], image="")) == []

    def test_check_service_runs_it_only_with_images_and_never_for_dead_entries(self):
        client = MagicMock()
        client.head.return_value = MagicMock(status_code=200, url="https://x.example/")
        svc = self._svc(["linux/amd64", "linux/arm64"])
        svc["website"] = "https://x.example/"
        with self._with_registry({"repo/img": _manifest("linux/amd64")}):
            with_images = liveness.check_service(client, svc, check_images=True)
            without = liveness.check_service(client, svc, check_images=False)
        assert any(f.kind == "platforms" and f.is_problem for f in with_images)
        assert not any(f.kind == "platforms" for f in without)


# ---------------------------------------------------------------------------
# A dead entry whose site stays up: a human can record the hand check
# ---------------------------------------------------------------------------


class TestAnAcknowledgedDeadSiteIsNotReflaggedForAYear:
    """Presearch, SpeedShare and Wipter answered on their own domains every week
    for months after being marked dead, and the report asked every week. The
    hand check is now recorded in the entry and the report stops asking, for a
    year, after which it asks again.
    """

    def _dead(self, **extra):
        return {"slug": "gone", "status": "dead", "website": "https://gone.example/", **extra}

    def _client_alive(self):
        client = MagicMock()
        client.get.return_value = MagicMock(status_code=200, url="https://gone.example/")
        return client

    def test_the_field_counts_for_a_year(self):
        from datetime import date

        svc = self._dead(resurrection_checked="2026-09-21")
        assert liveness.acknowledged_dead(svc, today=date(2026, 9, 21)) == date(2026, 9, 21)
        assert liveness.acknowledged_dead(svc, today=date(2027, 9, 21)) == date(2026, 9, 21)  # day 365 still counts
        assert liveness.acknowledged_dead(svc, today=date(2027, 9, 22)) is None  # day 366 asks again

    @pytest.mark.parametrize("raw", [None, "", "yesterday", "21/09/2026", 20260921])
    def test_a_missing_or_malformed_date_does_not_silence_the_check(self, raw):
        svc = self._dead()
        if raw is not None:
            svc["resurrection_checked"] = raw
        assert liveness.acknowledged_dead(svc) is None

    def test_a_fresh_acknowledgement_moves_the_entry_to_the_skipped_section(self):
        from datetime import date

        svc = self._dead(resurrection_checked=date.today().isoformat())
        [f] = liveness.check_resurrection(self._client_alive(), svc)
        assert f.status == liveness.SKIPPED and not f.is_problem
        assert "hand check" in f.detail and "resurrection_checked" in f.detail

    def test_without_it_the_site_answering_is_still_a_resurrection(self):
        [f] = liveness.check_resurrection(self._client_alive(), self._dead())
        assert f.status == liveness.RESURRECTED and f.is_problem
        assert "resurrection_checked" in f.detail  # the report tells the reader how to acknowledge

    def test_an_expired_acknowledgement_asks_again(self):
        [f] = liveness.check_resurrection(self._client_alive(), self._dead(resurrection_checked="2020-01-01"))
        assert f.status == liveness.RESURRECTED

    def test_the_real_catalog_uses_the_field_correctly(self):
        """Only dead entries carry it, and every value is an ISO date the script can read."""
        from datetime import date

        services, errors = liveness.load_services(Path(__file__).resolve().parents[1] / "services")
        assert not errors
        carriers = [s for s in services if s.get(liveness.ACK_FIELD)]
        assert carriers, "the three entries this was built for no longer carry the field"
        for svc in carriers:
            assert svc.get("status") == "dead", f"{svc['slug']} is {svc.get('status')} but carries {liveness.ACK_FIELD}"
            date.fromisoformat(str(svc[liveness.ACK_FIELD]))
