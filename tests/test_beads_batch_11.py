"""Batch 11: two screens that told the user something untrue.

One congratulated them for deployments that never happened. The other
recommended a credential and then offered nowhere to enter it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"
SETUP_HTML = ROOT / "app" / "templates" / "setup.html"


def without_comments(text: str) -> str:
    """JS source with comments stripped, so prose cannot satisfy a code check."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in text.splitlines())


class TestTheWizardSaysWhatActuallyHappened:
    """CashPilot-4og: the final screen was unconditional markup.

    "You're all set! Your services are being deployed." — shown whether five
    deployed, none did, or every deploy returned 403. `wizardState.deployed`
    was written twice and read nowhere, so a user whose deploys all failed was
    congratulated and sent to an empty dashboard with no idea anything had gone
    wrong.
    """

    def test_the_success_copy_is_no_longer_hardcoded(self):
        html = SETUP_HTML.read_text(encoding="utf-8")
        assert "Your services are being deployed." not in html

    def test_the_copy_is_addressable(self):
        html = SETUP_HTML.read_text(encoding="utf-8")
        assert 'id="wizard-done-title"' in html
        assert 'id="wizard-done-text"' in html

    def test_the_outcome_is_rendered_from_what_deployed(self):
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        assert "function renderWizardOutcome()" in source
        assert "wizardState.deployed" in source[source.index("function renderWizardOutcome()") :][:1400]

    def test_it_runs_when_the_wizard_reaches_the_last_step(self):
        """A renderer nothing calls is the same as no renderer."""
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        idx = source.index("if (wizardState.step === 4)")
        assert "renderWizardOutcome()" in source[idx : idx + 300]

    def test_a_skipped_setup_is_not_reported_as_a_failure(self):
        """From CodeRabbit on this PR, and a real gap in the first fix.

        Step 3 offers "Skip to Summary", so a user can select services and reach
        step 4 having deployed nothing. My first version keyed only on
        `deployed.length === 0`, so it told them "None of the selected services
        could be deployed" — sending them to hunt a failure that never happened.

        The distinction is whether a deploy was ATTEMPTED, which is why
        deployService now records it.
        """
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        assert "deployAttempted" in source, "the attempt is not tracked at all"
        block = source[source.index("function renderWizardOutcome()") :][:1600]
        assert "!wizardState.deployAttempted" in block, "the skip case is not distinguished"

    def test_the_attempt_is_recorded_where_deploying_happens(self):
        """A flag nothing sets is worse than no flag — it is always false."""
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        block = source[source.index("async function deployService(") :][:400]
        assert "wizardState.deployAttempted = true" in block

    def test_the_flag_starts_false_on_a_fresh_wizard(self):
        """Otherwise a second run of the wizard inherits the first run's state."""
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        assert source.count("deployAttempted: false") >= 2, (
            "deployAttempted must be initialised in both the declaration and the reset"
        )

    def test_deployed_is_now_read_not_just_written(self):
        """The bead's core evidence: the field had no reader at all."""
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        reads = [
            line
            for line in source.splitlines()
            if "wizardState.deployed" in line and ".push(" not in line and "= [" not in line
        ]
        assert reads, "wizardState.deployed is still write-only"


class TestTheCredentialModalShowsWhatItRecommends:
    """CashPilot-zr9: the modal filtered to required fields only.

    Bytelixir's session cookie expires in about two hours. Its remember_web and
    xsrf_token cookies last a year and are what stop collection dying the same
    afternoon — and both are OPTIONAL, so the credential-health panel said "a
    longer-lived credential exists for this service" while the modal it links to
    offered nowhere to put it.

    Storj was worse: its only field is optional, so the modal rendered no inputs
    at all.
    """

    def _modal(self) -> str:
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        start = source.index("function openCredentialModal")
        return source[start : start + 3000]

    def test_every_field_is_rendered(self):
        assert "col.fields.filter(f => f.required).map" not in self._modal()
        assert "col.fields.map(f =>" in self._modal()

    def test_optional_fields_are_labelled(self):
        """Rendering them without saying so would imply they are required."""
        assert "optionalSuffix" in self._modal()
        assert "(optional)" in self._modal()

    @pytest.mark.parametrize("slug,expected", [("storj", 1), ("bytelixir", 3)])
    def test_the_affected_services_now_have_fields(self, slug, expected):
        """storj showed ZERO inputs before this change."""
        from app.collectors import _COLLECTOR_ARGS

        assert len(_COLLECTOR_ARGS[slug]) == expected

    def test_bytelixirs_durable_cookies_are_the_optional_ones(self):
        """If these ever became required, the bug would have fixed itself.

        Pinned so this test cannot pass for the wrong reason later.
        """
        from app.collectors import _COLLECTOR_ARGS

        optional = {a.lstrip("?") for a in _COLLECTOR_ARGS["bytelixir"] if a.startswith("?")}
        assert optional == {"remember_web", "xsrf_token"}

    def test_the_health_panel_still_recommends_them(self):
        """The recommendation is what made hiding the field a dead end."""
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        assert "A longer-lived credential exists for this service" in source
