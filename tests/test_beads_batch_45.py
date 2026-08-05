"""CashPilot-dfw: staleness was computed, published, and read by nobody.

``app/exchange_rates.py`` keeps a SEPARATE clock per source, each advanced only
on that source's own HTTP 200 — deliberately, so a failure on one never marks
the other stale — and publishes ``stale``, ``crypto_stale`` and ``fiat_stale``
on ``/api/exchange-rates``.

No caller ever asked. So if CoinGecko stopped responding after one successful
fetch, the cached rates never expired and nothing on screen changed: a MYST
balance kept being converted and displayed at a price that could be hours or
days old, with no indication at all.

The behaviour itself is exercised by scripts/currency_check.mjs, which runs the
real function against controlled state — this is conditional logic about which
source matters to which viewer, and a string assertion cannot see it. These
tests pin the wiring and the invariants that harness cannot reach.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"


def js() -> str:
    text = APP_JS.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in text.splitlines())


class TestThePublishedStalenessIsRead:
    @pytest.mark.parametrize("field", ["crypto_stale", "fiat_stale"])
    def test_the_ui_reads_it(self, field):
        assert f"_exchangeRates.{field}" in js(), f"{field} is published and still ignored"

    def test_the_backend_still_publishes_it(self):
        """The premise. If get_all stops sending these, the UI reads nothing."""
        from app import exchange_rates

        published = exchange_rates.get_all()
        assert "crypto_stale" in published
        assert "fiat_stale" in published

    def test_the_two_clocks_are_still_separate(self):
        """A failure on one source must not mark the other stale.

        That separation is the reason the UI can name which source is behind,
        so it is worth pinning here rather than only in the module.
        """
        source = (ROOT / "app" / "exchange_rates.py").read_text(encoding="utf-8")
        assert "def crypto_rates_stale" in source
        assert "def fiat_rates_stale" in source

    def test_the_notice_is_rendered_somewhere(self):
        assert "rates-stale-note" in js()
        assert "rates-stale-note" in (ROOT / "app" / "templates" / "dashboard.html").read_text(encoding="utf-8")

    def test_it_is_refreshed_when_rates_are(self):
        source = js()
        i = source.index("async function loadExchangeRates")
        assert "renderStaleRateNotice()" in source[i : i + 500]

    def test_it_is_refreshed_when_the_display_currency_changes(self):
        """The fiat half depends on which currency is being read."""
        source = js()
        changes = [m.start() for m in re.finditer(r"_displayCurrency = select\.value;", source)]
        assert changes, "the display-currency handlers moved"
        for i in changes:
            assert "renderStaleRateNotice()" in source[i : i + 400], (
                "a currency change leaves the staleness notice showing the previous answer"
            )


class TestTheHarnessCoversTheBehaviour:
    """The conditional logic is run, not read — and CI runs it."""

    def test_the_harness_exercises_the_function(self):
        source = (ROOT / "scripts" / "currency_check.mjs").read_text(encoding="utf-8")
        assert "staleRateNotice" in source

    def test_ci_runs_that_harness(self):
        workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        assert "currency_check.mjs" in workflow

    def test_the_harness_passes(self):
        import shutil

        node = shutil.which("node")
        if node is None:
            pytest.skip("node is not installed; CI runs this as its own step")
        result = subprocess.run([node, "scripts/currency_check.mjs"], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_it_covers_the_case_that_must_stay_quiet(self):
        """A USD viewer is unaffected by a stale USD->X table.

        Warning them would be the noise that teaches people to ignore warnings,
        so the harness has to assert the silence as well as the alarm.
        """
        source = (ROOT / "scripts" / "currency_check.mjs").read_text(encoding="utf-8")
        assert "fiat stale, USD viewer" in source

    def test_it_covers_an_absent_field(self):
        """Absent is not stale: an older payload must not raise a false alarm."""
        source = (ROOT / "scripts" / "currency_check.mjs").read_text(encoding="utf-8")
        assert "field absent entirely" in source
