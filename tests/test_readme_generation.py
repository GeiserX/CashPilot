"""README tables generated from the catalog (CashPilot-9q1).

"YAML is the single source of truth" is the rule this project is built on, and
the README service tables were the one place it was violated. They drifted: the
README kept publishing a per-IP device limit for weeks after the catalog dropped
it for being unsourced — the same wrong number, in the more visible place.

The tests that matter are the ones about what generation must NOT destroy: a
referral link is revenue, and a warning that a provider forbids the way
CashPilot runs it is the most consequential sentence in the file.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_readme_tables as gen  # noqa: E402  (a script, not a package module)

from app import catalog  # noqa: E402

README = ROOT / "README.md"
REFERRAL_HINT = re.compile(r"(ref|psr=|aff=|/i/|\?r=|code=)")
URL = re.compile(r"https://[^\s)\]]+")


def _referral_urls(text: str) -> set[str]:
    return {u for u in URL.findall(text) if REFERRAL_HINT.search(u)}


class TestTheReadmeCannotDriftFromTheCatalog:
    def test_the_checked_in_readme_is_up_to_date(self):
        """The whole point: this fails if someone edits the table by hand."""
        current = README.read_text(encoding="utf-8")
        assert gen.render(current) == current, (
            "README service tables are out of date with the catalog. Run: python scripts/generate_readme_tables.py"
        )

    def test_generation_is_idempotent(self):
        once = gen.render(README.read_text(encoding="utf-8"))
        assert gen.render(once) == once

    def test_it_refuses_to_run_against_a_readme_without_markers(self):
        with pytest.raises(SystemExit, match="markers"):
            gen.render("# CashPilot\n\nNo markers here.\n")

    def test_prose_outside_the_markers_is_untouched(self):
        current = README.read_text(encoding="utf-8")
        rendered = gen.render(current)
        for sentinel in ("## Quick Start", "## License", "## FAQ"):
            assert sentinel in rendered


class TestGenerationNeverDestroysRevenue:
    """A referral link is income. Losing one to a formatting change is silent."""

    def test_every_active_service_referral_url_appears_in_the_readme(self):
        readme = README.read_text(encoding="utf-8")
        missing = []
        for svc in catalog.get_services():
            if str(svc.get("status")) not in {"active", "beta"}:
                continue
            url = (svc.get("referral") or {}).get("signup_url")
            if url and url not in readme:
                missing.append((svc["slug"], url))
        assert not missing, f"referral URLs missing from the README: {missing}"

    def test_no_referral_url_was_lost_relative_to_the_committed_readme(self):
        committed = subprocess.run(["git", "show", "HEAD:README.md"], capture_output=True, text=True, cwd=ROOT).stdout
        if not committed:
            pytest.skip("README not committed yet")
        lost = _referral_urls(committed) - _referral_urls(README.read_text(encoding="utf-8"))
        assert not lost, f"generation dropped referral URLs: {lost}"

    def test_the_generator_prefers_the_referral_url_over_the_bare_website(self):
        """A bare website link in the table is lost revenue on every signup."""
        svc = {
            "slug": "x",
            "name": "X",
            "website": "https://example.com",
            "referral": {"signup_url": "https://example.com/?ref=CODE"},
        }
        assert "ref=CODE" in gen._link(svc)


class TestWarningsSurviveRegeneration:
    def test_a_container_prohibited_service_keeps_its_footnote_marker(self):
        """Hand-placed markers vanish on the first regeneration.

        EarnApp's marker points at the warning that it forbids Docker
        containers, VMs and home servers — which is exactly how CashPilot
        deploys it. Deriving the marker from the catalog is what keeps it.
        """
        svc = {"slug": "earnapp", "requirements": {"container_prohibited": True}}
        assert gen._markers(svc).strip()
        assert gen._markers({"slug": "x", "requirements": {}}) == ""

    def test_the_real_earnapp_row_still_carries_the_marker(self):
        readme = README.read_text(encoding="utf-8")
        row = next(line for line in readme.splitlines() if "docs/guides/earnapp.md" in line)
        assert "\\*\\*\\*\\*" in row


class TestAbsentIsNotFalse:
    """The confusion that has bitten this catalog repeatedly."""

    def test_an_undeclared_flag_renders_as_unknown_not_no(self):
        assert gen._yes_no(None) == "?"
        assert gen._yes_no(True) == "✅"
        assert gen._yes_no(False) == "❌"

    def test_an_undocumented_device_limit_is_not_rendered_as_a_number(self):
        rendered = gen._devices(None)
        assert "?" in rendered
        assert "1" not in rendered

    def test_a_documented_zero_means_unlimited(self):
        assert gen._devices(0) == "Unlimited"

    def test_a_real_limit_is_rendered_plainly(self):
        assert gen._devices(1) == "1"

    def test_vps_uses_the_schemas_documented_default(self):
        """services/_schema.yml: vps_ip defaults to the opposite of residential_ip.

        Using a DOCUMENTED default is not guessing; printing "?" for two thirds
        of the catalog instead would be less true and less useful.
        """
        assert gen._vps_allowed({"residential_ip": True}) is False
        assert gen._vps_allowed({"residential_ip": False}) is True
        assert gen._vps_allowed({"residential_ip": True, "vps_ip": True}) is True
        assert gen._vps_allowed({}) is None


class TestPayoutRendering:
    def test_crypto_names_its_token_when_the_catalog_records_one(self):
        assert gen._payout({"payment": {"methods": ["crypto"], "crypto_token": "SOL"}}) == "Crypto (SOL)"

    def test_crypto_without_a_token_is_just_crypto(self):
        assert gen._payout({"payment": {"methods": ["crypto"]}}) == "Crypto"

    def test_underscored_methods_are_made_readable(self):
        assert gen._payout({"payment": {"methods": ["amazon_giftcard"]}}) == "Amazon Gift Card"

    def test_a_service_with_no_methods_says_so(self):
        assert gen._payout({}) == "--"


class TestEveryServiceHasAGuide:
    def test_no_catalogued_service_is_missing_its_guide(self):
        missing = [
            s["slug"] for s in catalog.get_services() if not (ROOT / "docs" / "guides" / f"{s['slug']}.md").exists()
        ]
        assert not missing, f"no guide for: {missing}. Generate a stub with: python scripts/new_service_stub.py <slug>"


class TestTheGuideStubGenerator:
    def _render(self, slug):
        sys.path.insert(0, str(ROOT / "scripts"))
        import new_service_stub

        return new_service_stub.render(slug)

    def test_it_renders_a_real_service_from_the_catalog(self):
        out = self._render("honeygain")
        assert "# Honeygain" in out
        assert "Devices per IP" in out

    def test_it_uses_the_referral_link_in_the_setup_step(self):
        out = self._render("honeygain")
        signup = (catalog.get_service("honeygain").get("referral") or {}).get("signup_url")
        assert signup and signup in out

    def test_it_says_not_documented_rather_than_inventing_a_value(self):
        import new_service_stub

        assert new_service_stub._fmt(None) == "Not documented"
        assert new_service_stub._fmt(0) == "Unlimited"
        assert new_service_stub._fmt(True) == "Yes"
        assert new_service_stub._fmt(False) == "No"

    def test_an_unknown_slug_fails_loudly(self):
        with pytest.raises(SystemExit, match="No catalog entry"):
            self._render("no-such-service")
