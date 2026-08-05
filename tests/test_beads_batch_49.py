"""CashPilot-pmi and CashPilot-cn3: two places the UI spoke without evidence.

**pmi** — the dashboard's "Active Services" card was initialised to a literal
``0`` in the template while its three siblings used an em-dash. ``app.js``
already renders the em-dash when the count comes back null, commenting that
``|| 0`` "would render 'could not be counted' as 'nothing is running'"; and its
catch deliberately PRESERVES whatever is displayed, so a transient failure
cannot look like earnings dropping to zero. Compose the three and a **first**
load that fails preserves the hardcoded ``0``. The one card fixed for this in JS
was the one where a template character undid the fix.

**cn3** — the Settings panels showed "Loading..." forever. Two of the three calls
in ``loadSettings``' ``Promise.all`` carry their own ``.catch``; ``/api/config``
did not, so its rejection aborted the whole thing before either render function
ran, and the outer catch body was empty. An expired session or a restarting
server was indistinguishable from a page that never finished loading.

The behaviour of the Settings fix is proven by ``scripts/settings_failure_check.mjs``,
which runs the real functions against a stub DOM — a string assertion could show
the catch is non-empty but never that both panels get written, nor that what
lands in them is useful. What is pinned here is the wiring that harness cannot
see: that the catch calls it, and that the harness runs in CI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "app" / "templates" / "dashboard.html"
APP_JS = ROOT / "app" / "static" / "js" / "app.js"


class TestNoStatCardClaimsAMeasurementItDoesNotHave:
    """The template's initial text is what a failed first load leaves on screen."""

    def _cards(self):
        html = DASHBOARD.read_text(encoding="utf-8")
        # (id, initial text) for every stat-value element.
        return re.findall(r'<div class="stat-value[^"]*" id="([^"]+)">([^<]*)</div>', html)

    def test_the_dashboard_has_stat_cards_to_check(self):
        """A regex that silently matches nothing would make every test below vacuous."""
        assert len(self._cards()) >= 4, f"only found {self._cards()} — the sweep is not seeing the template"

    def test_active_services_no_longer_starts_at_zero(self):
        """The bead, stated directly."""
        cards = dict(self._cards())
        assert "active-services" in cards
        assert cards["active-services"].strip() != "0", (
            "a failed first load leaves this on screen, and it reads as a measured zero"
        )

    @pytest.mark.parametrize("card_id", ["total-earnings", "today-earnings", "month-earnings", "active-services"])
    def test_it_initialises_to_the_unknown_marker(self, card_id):
        cards = dict(self._cards())
        assert cards[card_id].strip() in ("&mdash;", "—"), (
            f"{card_id} starts as {cards[card_id]!r}, which asserts a value nothing measured"
        )

    def test_no_stat_card_anywhere_starts_as_a_number(self):
        """Catches the next card added, not just the four that exist today."""
        numeric = [
            (cid, text)
            for cid, text in self._cards()
            if re.fullmatch(r"[\s$€£]*-?[\d.,]+%?\s*", text or "") and text.strip()
        ]
        assert not numeric, f"these assert a measurement before one is taken: {numeric}"

    def test_the_js_still_renders_the_marker_for_a_null_count(self):
        """The template fix is worthless if the render path regresses."""
        js = APP_JS.read_text(encoding="utf-8")
        assert "data.active_services == null ? '\\u2014' : data.active_services" in js


class TestTheSettingsPanelsSayWhyTheyAreEmpty:
    def _load_settings_body(self):
        js = APP_JS.read_text(encoding="utf-8")
        start = js.index("async function loadSettings(")
        rest = js[start:]
        end = re.search(r"\n  (?:async )?function [A-Za-z_]", rest)
        return rest[: end.start()] if end else rest[:3000]

    def test_the_catch_is_no_longer_empty(self):
        body = self._load_settings_body()
        catch = body[body.index("} catch (err) {") :]
        assert "settingsPanelsFailed(err)" in catch, (
            "the failure is swallowed again, so both panels keep saying Loading forever"
        )

    def test_the_handler_exists(self):
        js = APP_JS.read_text(encoding="utf-8")
        assert "function settingsPanelsFailed(" in js
        assert "function settingsLoadFailureMessage(" in js

    def test_both_containers_are_targeted(self):
        """One panel fixed and one still spinning would be worse than neither."""
        js = APP_JS.read_text(encoding="utf-8")
        start = js.index("function settingsPanelsFailed(")
        body = js[start : start + 700]
        assert "env-vars-container" in body
        assert "collectors-container" in body

    def test_the_message_is_escaped_before_it_reaches_innerhtml(self):
        """The detail comes from a server response, so it is untrusted."""
        js = APP_JS.read_text(encoding="utf-8")
        start = js.index("function settingsPanelsFailed(")
        body = js[start : start + 700]
        assert "escapeHtml(message)" in body

    def test_the_templates_still_ship_a_loading_placeholder(self):
        """The premise: without it there would be nothing to get stuck on."""
        settings = (ROOT / "app" / "templates" / "settings.html").read_text(encoding="utf-8")
        assert settings.count("Loading...") >= 2


class TestTheHarnessActuallyRunsInCI:
    """A behavioural harness nobody runs proves nothing."""

    def test_the_script_exists(self):
        assert (ROOT / "scripts" / "settings_failure_check.mjs").is_file()

    def test_the_workflow_runs_it(self):
        doc = yaml.safe_load((ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8"))
        commands = " ".join(
            str(step.get("run", "")) for job in doc["jobs"].values() for step in (job.get("steps") or [])
        )
        assert "node scripts/settings_failure_check.mjs" in commands

    def test_it_is_browser_free_like_its_siblings(self):
        """The Chrome-dependent harnesses cannot run in CI; this one must not need one."""
        text = (ROOT / "scripts" / "settings_failure_check.mjs").read_text(encoding="utf-8")
        assert "9222" not in text
        assert "puppeteer" not in text.lower()
