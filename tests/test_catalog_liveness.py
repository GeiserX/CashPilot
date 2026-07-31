"""Tests for scripts/check_catalog_liveness.py.

Only the pure decision logic is exercised — no network calls and no docker, so
the suite stays deterministic and offline. What matters here is that the script
cannot report a *live* service as dead (which would send someone deleting a
working catalog entry) and cannot report an empty catalog as healthy.
"""

from __future__ import annotations

import importlib.util
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
        slugs = [s["slug"] for s in liveness.load_services(tmp_path)]
        assert slugs == ["alpha", "bravo"]

    def test_unparseable_file_is_skipped_not_fatal(self, tmp_path):
        self._write(tmp_path, "bad.yml", "{{{ not yaml")
        self._write(tmp_path, "good.yml", "slug: good\nname: G\n")
        assert [s["slug"] for s in liveness.load_services(tmp_path)] == ["good"]


class TestCheckService:
    def test_dead_status_service_is_skipped(self):
        client = MagicMock()
        findings = liveness.check_service(
            client, {"slug": "gone", "status": "dead", "website": "https://x.com"}, check_images=False
        )
        assert all(f.status == liveness.SKIPPED for f in findings)
        client.head.assert_not_called()  # no network for a service we already retired

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
