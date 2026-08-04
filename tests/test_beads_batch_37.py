"""CashPilot-p6s: the wizard's expected end state was a dashboard reading zero.

Step 3 of the setup wizard says "Already have an account? Enter your credentials
below." A reasonable user concludes that entering them is what makes earnings
appear. It is not: those values only configure the CONTAINER. The dashboard
shows no balance until the same credentials are entered again under
Settings → Collectors.

The service-detail view says exactly that. The wizard — the one screen a new
user actually sees — said nothing, so completing onboarding correctly still left
the dashboard at zero with no explanation.

``/api/services/available``, which is what the wizard reads, did not even report
``has_collector``, so the wizard could not have known.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"


def js() -> str:
    text = APP_JS.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in text.splitlines())


class TestTheWizardSaysIt:
    def test_the_setup_form_renders_the_notice(self):
        source = js()
        i = source.index("function renderServiceSetupForm")
        j = source.index("function ", i + 10)
        assert "collectorCredentialsNotice" in source[i:j], "the wizard still says nothing about collectors"

    def test_it_is_gated_on_the_service_having_one(self):
        """A service with no collector has no second step to warn about."""
        source = js()
        assert "svc.has_collector ? collectorCredentialsNotice" in source

    def test_the_endpoint_the_wizard_reads_reports_it(self):
        """The wizard could not have known: the field was not in the payload."""
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        i = source.index("async def api_services_available")
        j = source.index("\n@app.", i)
        assert 'svc["has_collector"]' in source[i:j]

    def test_the_notice_names_where_to_go(self):
        assert "Settings → Collectors" in js()

    def test_it_says_the_service_still_earns(self):
        """Without this it reads as "your deployment is broken", which it is not."""
        assert "the service earns either way" in js()


class TestThereIsOnlyOneWording:
    """Two copies of a notice drift, and the wizard's is the one that matters."""

    def test_the_helper_exists(self):
        assert "function collectorCredentialsNotice(slug)" in js()

    def test_both_screens_use_it(self):
        source = js()
        assert source.count("collectorCredentialsNotice(") >= 3, (
            "expected the definition plus a call from the wizard and the detail view"
        )

    def test_the_detail_view_no_longer_inlines_its_own(self):
        source = js()
        i = source.index("function collectorCredentialsNotice")
        after = source[source.index("}", source.index("return `", i)) :]
        assert "The credentials above run the service" not in after, "a second copy of the notice is back"

    def test_the_slug_is_escaped(self):
        """It goes into a data attribute reached through innerHTML."""
        source = js()
        i = source.index("function collectorCredentialsNotice")
        assert "escapeHtml(slug)" in source[i : i + 900]


class TestTheDistinctionIsRealNotCosmetic:
    """The premise: container credentials and collector credentials differ."""

    def test_a_service_with_a_collector_is_flagged(self):
        from app.collectors import COLLECTOR_MAP

        assert "honeygain" in COLLECTOR_MAP

    def test_a_service_without_one_is_not(self):
        from app.collectors import COLLECTOR_MAP

        assert "proxybase-xyz" not in COLLECTOR_MAP

    @pytest.mark.parametrize("slug", ["honeygain", "iproyal"])
    def test_the_collector_takes_its_own_arguments(self, slug):
        """If they were the same values, re-entering them would be pointless."""
        from app.collectors import _COLLECTOR_ARGS

        assert _COLLECTOR_ARGS.get(slug), f"{slug} has a collector but declares no arguments"
