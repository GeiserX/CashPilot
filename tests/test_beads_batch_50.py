"""CashPilot-2dh, -0p4, -wij: three ways the fleet page misled its reader.

**2dh** — worker timestamps were rendered raw. The database writes
``datetime('now')``, which SQLite produces in **UTC** with no zone designator,
and the frontend had no date formatting of any kind: ``toLocaleString``,
``toLocaleDateString`` and ``new Date(`` each returned zero hits across
``app.js`` and ``fleet.html``. A viewer in CEST read a worker that heartbeated
five minutes ago as two hours stale — directly beside the words "This host is
not reachable", and one click from Remove.

**0p4** — the Copy button claimed success in two situations where it had none.
``navigator.clipboard`` is gated on a secure context, and ``docs/fleet.md``
documents the normal setup as plain ``http://`` on the LAN, where the object is
``undefined``; the property access threw inside an async function that
``delegate.js`` calls without awaiting, so the button was silently dead. And when
the key reveal failed, ``_apiKey`` was the literal ``(error)`` — copied, with a
success toast, into a compose file that could never enrol a worker.

**wij** — of four stat cards in one row, "Workers" and "Online" were fleet-wide
while "Services" and "Running" counted only online workers, with nothing saying
so. A rebooting host made "Services" drop, and it read as containers lost. The
dashboard already ships the correct explanation and a button that sends the user
to this very page to be misled by it.

Behaviour lives in ``scripts/fleet_staleness_check.mjs``, which now runs the real
``fmtTimestamp`` extracted from ``app.js`` rather than a stub — a stub would let
the formatter break while the harness stayed green, which is the failure mode
these scripts exist to catch.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FLEET = ROOT / "app" / "templates" / "fleet.html"
APP_JS = ROOT / "app" / "static" / "js" / "app.js"
HARNESS = ROOT / "scripts" / "fleet_staleness_check.mjs"


class TestThereIsOneSharedTimestampFormatter:
    def test_it_exists(self):
        assert "function fmtTimestamp(" in APP_JS.read_text(encoding="utf-8")

    def test_it_is_exported_for_the_templates(self):
        """fleet.html reaches it through the CP namespace."""
        js = APP_JS.read_text(encoding="utf-8")
        export = js[js.rindex("  return {") :]
        assert "fmtTimestamp," in export

    def test_it_is_defined_outside_the_export_object(self):
        """A function declaration inside the returned literal is a syntax error.

        The first attempt at this landed there; `node --check` caught it.
        """
        js = APP_JS.read_text(encoding="utf-8")
        assert js.index("function fmtTimestamp(") < js.rindex("  return {")

    def test_no_raw_heartbeat_reaches_the_page(self):
        html = FLEET.read_text(encoding="utf-8")
        assert "${w.last_heartbeat || 'never'}" not in html, "the stored UTC value is rendered verbatim again"
        assert "${lastSeen || 'never'}" not in html

    def test_both_render_sites_use_the_formatter(self):
        html = FLEET.read_text(encoding="utf-8")
        assert html.count("CP.fmtTimestamp(") >= 3, "a timestamp site was left on the raw value"

    def test_the_original_utc_is_still_recoverable(self):
        """Converting without keeping the source would lose the audit trail."""
        js = APP_JS.read_text(encoding="utf-8")
        body = js[js.index("function fmtTimestamp(") :][:1200]
        assert "UTC" in body


class TestTheCopyButtonCannotClaimAnUnearnedSuccess:
    def _body(self):
        html = FLEET.read_text(encoding="utf-8")
        start = html.index("window.copyWorkerEnv")
        return html[start : start + 1800]

    def test_it_refuses_the_sentinel_values(self):
        """`(error)` and `(not configured)` are not keys."""
        assert "_apiKey.startsWith('(')" in self._body()

    def test_the_success_toast_is_no_longer_unconditional(self):
        body = self._body()
        assert "navigator.clipboard.writeText(text).then(() => CP.toast('Copied', 'success'));" not in body

    def test_the_clipboard_write_is_awaited_and_caught(self):
        """Unawaited, the rejection is invisible: delegate.js does not catch it."""
        body = self._body()
        assert "await navigator.clipboard.writeText(text)" in body
        assert "catch" in body

    def test_a_missing_clipboard_api_is_handled(self):
        """It is undefined on the plain-http LAN origin the docs recommend."""
        assert "!navigator.clipboard" in self._body()

    def test_there_is_something_to_fall_back_to(self):
        html = FLEET.read_text(encoding="utf-8")
        assert 'id="worker-env-fallback"' in html, "the handler targets an element that does not exist"
        assert "<textarea" in html[html.index('id="worker-env-fallback"') :][:400]


class TestTheFleetCardsSayWhatTheyCount:
    def test_the_online_only_cards_are_labelled(self):
        html = FLEET.read_text(encoding="utf-8")
        for card in ("fleet-total-containers", "fleet-running-containers"):
            block = html[max(0, html.index(card) - 600) : html.index(card)]
            assert "(online)" in block, f"{card} still reads as a fleet-wide total"

    def test_the_fleet_wide_cards_are_not_mislabelled(self):
        """Over-labelling would be its own inaccuracy.

        Scoped to each fleet-wide card's own <div>, not to "everything before
        the first online-only card" -- that slice necessarily contains the
        Services label, so the first version of this test failed on correct
        markup.
        """
        html = FLEET.read_text(encoding="utf-8")
        for card in ("fleet-total-workers", "fleet-online-workers"):
            start = html.rindex('<div class="stat-card">', 0, html.index(card))
            block = html[start : html.index(card)]
            assert "(online)" not in block, f"{card} is fleet-wide but labelled as online-only"

    def test_the_endpoint_reports_what_the_cards_leave_out(self):
        main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        start = main.index("async def api_fleet_summary")
        body = main[start : start + 2200]
        assert '"unreachable_containers"' in body
        assert '"unreachable_workers"' in body

    def test_offline_workers_are_still_excluded_from_the_online_totals(self):
        """The counts themselves must not change — only what is said about them."""
        main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        start = main.index("async def api_fleet_summary")
        body = main[start : start + 2200]
        assert 'if w["status"] != "online":' in body
        assert 'total_services += w["container_count"]' in body

    def test_the_page_renders_the_note(self):
        html = FLEET.read_text(encoding="utf-8")
        assert 'id="fleet-unreachable-note"' in html
        assert "summary.unreachable_containers" in html

    def test_the_note_denies_the_wrong_conclusion_explicitly(self):
        """ "N not counted" alone still reads as "N lost"."""
        html = FLEET.read_text(encoding="utf-8")
        idx = html.index("summary.unreachable_containers")
        block = html[idx : idx + 900]
        assert "keep running and earning" in block


class TestTheHarnessRunsTheRealFormatter:
    def test_it_extracts_fmttimestamp_from_app_js(self):
        text = HARNESS.read_text(encoding="utf-8")
        assert "app/static/js/app.js" in text
        assert "fmtTimestamp" in text

    def test_it_does_not_stub_it(self):
        """A stub would let the formatter break while this stayed green."""
        text = HARNESS.read_text(encoding="utf-8")
        assert "const fmtTimestamp = new Function(" in text

    def test_it_fails_loudly_if_the_function_is_renamed(self):
        text = HARNESS.read_text(encoding="utf-8")
        assert "throw new Error('fmtTimestamp is gone" in text

    def test_the_assertion_count_is_counted_not_hardcoded(self):
        """The summary line used to interpolate a literal and always say twenty.

        Checks the console.log LINE, not the whole file: the comment recording
        why necessarily quotes the old literal, and the first version of this
        test matched its own explanation.
        """
        line = next(
            line
            for line in HARNESS.read_text(encoding="utf-8").splitlines()
            if "assertions)" in line and "console" in line
        )
        assert not re.search(r"\$\{\d+\}", line), f"still interpolating a constant: {line.strip()}"
        assert "checksRun" in line

    @pytest.mark.parametrize("script", ["fleet_staleness_check.mjs", "settings_failure_check.mjs"])
    def test_the_browser_free_harnesses_stay_browser_free(self, script):
        text = (ROOT / "scripts" / script).read_text(encoding="utf-8")
        assert "9222" not in text

    def test_the_harness_reports_more_assertions_than_before(self):
        """Guards against the count silently shrinking as checks are removed."""
        import subprocess

        result = subprocess.run(
            ["node", "scripts/fleet_staleness_check.mjs"], cwd=ROOT, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stdout + result.stderr
        count = int(re.search(r"\((\d+) assertions\)", result.stdout).group(1))
        assert count >= 26, f"the harness now runs only {count} assertions"
