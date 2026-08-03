"""Endpoints that exist but that nothing in the UI ever calls.

v1.10.x shipped 35 `/api/**` routes with no frontend consumer. Each one is a
feature that was designed, implemented, tested and then made invisible — the
backend computes the answer and no page ever asks for it. Nothing failed, so
nothing reported it.

The payout queue is the sharpest case and the reason this file exists: a balance
drop was recorded as a PROBABLE payout, and until someone answers "yes, I was
paid" it never counts toward lifetime earnings. There was nowhere to answer. So
a real payout looked exactly like a loss, permanently, which is the opposite of
what the feature was built for.

This guards the endpoints that are wired today. It is deliberately NOT a
list of every route — a test asserting "all 35 are wired" would just be a
failing TODO. It locks in what has been done so it cannot silently rot.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = sorted((ROOT / "app" / "static" / "js").glob("*.js"))
TEMPLATES = sorted((ROOT / "app" / "templates").glob("*.html"))


def js_function(name: str) -> str:
    """The source of exactly one function in app.js, and no more.

    Slicing a fixed number of characters reads into whatever comes next, which
    is how the first version of these tests reported that `confirmPayout` asks
    for confirmation — it had run on into `rejectPayout`, which does. Bounded
    on the next top-level function instead.
    """
    app_js = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    start = app_js.index(f"function {name}(")
    rest = app_js[start:]
    following = [
        match.start() for match in re.finditer(r"\n  (?:async )?function [A-Za-z_]", rest) if match.start() > 0
    ]
    body = rest[: following[0]] if following else rest
    assert len(body) > 100, f"{name} extracted as {len(body)} chars — the bound is wrong"
    return body


def frontend_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in [*JS, *TEMPLATES])


#: (route segment that must appear in a fetch, why it matters to a user)
WIRED = [
    ("/api/earnings/payouts", "the queue where a detected payout is confirmed or rejected"),
    ("payouts/${", "the confirm/reject call, built as a template literal"),
]


class TestTheseEndpointsHaveAConsumer:
    @pytest.mark.parametrize(("needle", "why"), WIRED, ids=lambda v: v if v.startswith("/") or "$" in v else "")
    def test_the_frontend_actually_calls_it(self, needle, why):
        assert needle in frontend_text(), f"nothing in the UI calls {needle} — {why}"


class TestThePayoutQueueIsReachable:
    """Wiring it up means all four pieces, and each fails silently on its own."""

    def test_the_dashboard_has_somewhere_to_render_it(self):
        dashboard = (ROOT / "app" / "templates" / "dashboard.html").read_text(encoding="utf-8")
        assert 'id="payout-queue-card"' in dashboard
        assert 'id="payout-queue-list"' in dashboard

    def test_the_card_starts_hidden(self):
        """An empty card every day trains people to ignore the one day it matters."""
        dashboard = (ROOT / "app" / "templates" / "dashboard.html").read_text(encoding="utf-8")
        card = dashboard[dashboard.index('id="payout-queue-card"') :][:200]
        assert "display:none" in card.replace(" ", "")

    @pytest.mark.parametrize("handler", ["loadPayoutQueue", "confirmPayout", "rejectPayout"])
    def test_the_handler_is_exported_from_cp(self, handler):
        """delegate.js resolves data-action against CP; unexported means a dead button."""
        app_js = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
        exported = set(re.findall(r"^\s{4}([A-Za-z_][A-Za-z0-9_]*),\s*$", app_js, re.M))
        assert handler in exported, f"{handler} is not in the CP return block, so its button does nothing"

    def test_the_queue_loads_with_the_rest_of_the_dashboard(self):
        """Defined but never called is the same as not built."""
        app_js = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
        load_dashboard = app_js[app_js.index("async function loadDashboard()") :][:900]
        assert "loadPayoutQueue()" in load_dashboard

    def test_the_buttons_use_delegated_actions_not_inline_handlers(self):
        queue = js_function("loadPayoutQueue")
        assert 'data-action="confirmPayout"' in queue
        assert 'data-action="rejectPayout"' in queue
        assert "onclick=" not in queue, "CSP has no unsafe-inline; an inline handler would never fire"


class TestTheAmountShownIsTheOneTheProviderPaid:
    """Caught in a real browser, not by a string test.

    A 24.90 USD payout rendered as "£18.55" because the dashboard's display
    currency was applied to it. Everywhere else that is right; here it is a
    converted approximation of one specific real transaction, and the user is
    about to go and check it against the provider's own page.
    """

    def _queue_source(self) -> str:
        return js_function("loadPayoutQueue")

    def test_the_native_amount_leads(self):
        source = self._queue_source()
        assert "nativeCurrency" in source
        assert "Balance dropped by ${escapeHtml(native)}" in source

    def test_the_converted_value_is_marked_approximate(self):
        assert "≈" in self._queue_source(), "a converted figure presented as exact invites a false mismatch"

    def test_it_does_not_repeat_itself_when_both_are_the_same(self):
        """A USD payout on a USD dashboard must not read '24.90 USD (≈ $24.90)'.

        The first version of this test asserted the literal source text
        `converted !== native` — the implementation, not the behaviour — and so
        passed while that very comparison produced the duplication it claims to
        prevent: `formatCurrency` returns "$24.90" through Intl, `native` is
        "24.90 USD", the two strings differ, and the approximation rendered
        anyway. Asserting on the currency CODES is asserting the thing that
        actually decides whether a conversion happened.
        """
        source = self._queue_source()
        # Superseded once more: comparing against _displayCurrency was still
        # wrong when that currency has NO rate, because the amount then stays
        # in USD while the preference says GBP. The effective currency is the
        # one the formatter will actually use.
        assert "effectiveDisplayCurrency(nativeCurrency) !== nativeCurrency" in source
        assert "converted !== native" not in source, "comparing formatted strings re-introduces the duplicate amount"


class TestPayoutActionsRespectTheRoleLadder:
    """The backend requires writer for confirm and reject.

    Showing a viewer buttons that can only ever return 403 teaches them the app
    is broken. The repo already has the idiom for this — `_canWrite` gates the
    deploy button — so the queue follows it.
    """

    def test_the_buttons_are_gated_on_write_access(self):
        assert "_canWrite ?" in js_function("loadPayoutQueue")

    def test_a_viewer_is_told_why_rather_than_shown_nothing(self):
        """A row with no explanation reads as a rendering bug."""
        assert "Writer access required" in js_function("loadPayoutQueue")


class TestRejectionAsksFirst:
    def test_rejecting_requires_a_confirmation(self):
        """Reject is a hard DELETE with no undo."""
        reject = js_function("rejectPayout")
        assert "window.confirm" in reject
        assert "cannot be undone" in reject

    def test_confirming_does_not_ask(self):
        """Confirming is reversible in effect and is the common case."""
        confirm = js_function("confirmPayout")
        assert "window.confirm" not in confirm


class TestAFailedLookupDoesNotHideThePrompt:
    def test_an_api_error_leaves_the_card_alone(self):
        """Unknown is not "nothing pending".

        Hiding the card on a failed fetch would silently drop a question the
        user still owes an answer to.
        """
        queue = js_function("loadPayoutQueue")
        # Only the fetch's own catch, which is the first one in the function.
        catch_block = queue[queue.index("} catch (err) {") : queue.index("if (!pending.length)")]
        assert "return" in catch_block, "a failed fetch must bail out, not fall through"
        assert "display = 'none'" not in catch_block, "hiding the card on an error drops a pending question"


class TestPayoutProgressIsShownWhereTheUserLooks:
    """The "how far off is my payout" number, previously computed for nobody.

    It nearly went into `app/templates/service_detail.html`, which turns out to
    be a DEAD template: no route renders it and nothing references it. The real
    detail view is a modal built by `renderServiceDetail`. A card added to that
    template would have passed every string test in this file and never once
    appeared on screen.
    """

    def test_the_dead_template_is_still_dead(self):
        """If someone wires it up later, this test should fail and be deleted."""
        py = "\n".join(p.read_text(encoding="utf-8") for p in [*(ROOT / "app").rglob("*.py")] if "test" not in p.name)
        assert "service_detail.html" not in py, (
            "service_detail.html is now rendered by something — the payout progress card "
            "should probably live there too, and this test has served its purpose"
        )

    def test_the_card_is_built_by_the_modal_renderer(self):
        render = js_function("renderServiceDetail")
        assert 'id="payout-progress-card"' in render
        assert 'id="payout-progress-body"' in render

    def test_the_modal_asks_for_the_data_after_building_the_container(self):
        """Called before the innerHTML assignment, it would find nothing to fill."""
        detail = js_function("openServiceDetail")
        assert "loadPayoutProgress()" in detail
        assert detail.index("renderServiceDetail") < detail.index("loadPayoutProgress()")

    def test_it_is_exported_so_the_modal_can_reach_it(self):
        app_js = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
        exported = set(re.findall(r"^\s{4}([A-Za-z_][A-Za-z0-9_]*),\s*$", app_js, re.M))
        assert "loadPayoutProgress" in exported


class TestTheProgressCardKeepsItsUnitsStraight:
    """Caught in a browser: "£3.73" rendered directly above "to the 20 minimum".

    Two halves of one comparison in different units, with a progress bar that
    agreed with neither. Everything in this card is stated in the cashout
    currency the provider's own minimum is declared in.
    """

    def test_it_uses_the_cashout_currency_rather_than_the_display_currency(self):
        source = js_function("loadPayoutProgress")
        assert "card.dataset.currency" in source
        assert "const money =" in source

    def test_the_renderer_passes_that_currency_through(self):
        assert "data-currency=" in js_function("renderServiceDetail")

    def test_it_falls_back_when_a_service_declares_no_cashout_currency(self):
        """Not every catalogued service declares one; the card must still render."""
        assert "unit ?" in js_function("loadPayoutProgress")

    def test_the_bar_is_derived_from_remaining_not_from_a_threshold_key(self):
        """`project()` returns `remaining`, never `threshold` — verified against it."""
        source = js_function("loadPayoutProgress")
        assert "projection.remaining" in source
        assert "projection.threshold" not in source, "that key does not exist in the API response"

    def test_no_bar_is_drawn_when_there_is_no_minimum_to_reach(self):
        """A bar stuck at zero says the wrong thing more loudly than no bar."""
        source = js_function("loadPayoutProgress")
        assert "typeof remaining === 'number'" in source


class TestAConvertedFigureIsNeverFabricated:
    """formatCurrency labelled unconverted USD with the display currency's sign.

    With no rate for the display currency the amount was left in USD and then
    formatted AS that currency, so $24.90 rendered as "£24.90" — not a
    conversion, the same number wearing a different sign. Rates are fetched
    asynchronously, so this hit every figure on the dashboard on every page load
    until they arrived, and hit permanently for any currency with no rate.

    Found by driving a freshly restarted server in a browser. The behavioural
    proof lives in scripts/currency_check.mjs, which exercises the real function
    against controlled rate state; these assert the shape that makes it hold.
    """

    def _format_currency(self) -> str:
        return js_function("formatCurrency")

    def test_the_label_follows_the_conversion_rather_than_the_preference(self):
        source = self._format_currency()
        assert "let currency = 'USD'" in source, "the label must be derived, not assumed"
        assert "currency: _displayCurrency" not in source, (
            "labelling with the preferred currency regardless of whether a rate was applied "
            "is exactly the bug: it prints a USD amount as if it were converted"
        )

    def test_the_currency_is_only_upgraded_when_a_rate_was_actually_applied(self):
        source = self._format_currency()
        applied = source.index("displayAmount = usdAmount * _exchangeRates.fiat[_displayCurrency]")
        assigned = source.index("currency = _displayCurrency")
        assert applied < assigned, "the label is set before the conversion it claims to describe"

    def test_there_is_a_committed_harness_that_proves_the_behaviour(self):
        harness = ROOT / "scripts" / "currency_check.mjs"
        assert harness.exists()
        text = harness.read_text(encoding="utf-8")
        assert "NO rate" in text, "the no-rate case is the one that regressed"
        assert "process.exit" in text, "a harness that cannot fail gates nothing"


class TestTheApproximationIsSuppressedWhenNothingWasConverted:
    def test_the_decision_uses_the_effective_currency(self):
        assert "effectiveDisplayCurrency(nativeCurrency) !== nativeCurrency" in js_function("loadPayoutQueue")

    def test_the_effective_currency_accounts_for_a_missing_fiat_rate(self):
        """A GBP preference with no GBP rate resolves to USD, not GBP."""
        source = js_function("effectiveDisplayCurrency")
        assert "_exchangeRates.fiat[_displayCurrency]" in source
        assert "return 'USD'" in source

    def test_an_unpriced_token_is_left_in_its_own_units(self):
        source = js_function("effectiveDisplayCurrency")
        assert "crypto_usd" in source
        assert "if (!priced) return nativeCurrency" in source


class TestTheChartLabelsAndItsBarsAgree:
    """Reported as a bug; it is not one, and the reason is worth pinning down.

    The dataset holds raw USD, which looks wrong on a euro dashboard until you
    notice the y-axis ticks are formatted through the SAME converter as the
    tooltip. Bars and ticks therefore live in one space and the reading is
    consistent: a bar at raw 24.90 sits against a tick labelled in the display
    currency.

    That consistency is entirely accidental-looking and one line from breaking.
    Converting the data without the ticks — or the ticks without the data —
    would silently misplace every bar against its own axis, which is far harder
    to notice than an obviously wrong number.
    """

    def _chart(self) -> str:
        return js_function("loadEarningsChart")

    def test_the_tooltip_formats_through_the_shared_converter(self):
        assert "formatCurrency(ctx.parsed.y)" in self._chart()

    def test_the_axis_ticks_format_through_the_same_one(self):
        assert "callback: (v) => formatCurrency(v)" in self._chart()

    def test_the_data_is_not_pre_converted_behind_the_labels_back(self):
        """Converting the values while the ticks also convert would double it."""
        chart = self._chart()
        assert "values = data.map(d => d.amount)" in chart, (
            "if the data is converted here, the axis callback must stop converting too, "
            "or every figure is converted twice"
        )


class TestCredentialHealthWarnsBeforeCollectionStops:
    """Several providers issue session cookies measured in hours.

    When one dies, collection stops and nothing says so — the dashboard keeps
    showing the last balance it managed to read, which is indistinguishable
    from a service that simply is not earning. The endpoint computing this
    shipped in 1.10.x with no consumer, so the warning existed and nobody ever
    saw it.
    """

    def _source(self) -> str:
        return js_function("loadCredentialHealth")

    def test_settings_has_somewhere_to_show_it(self):
        settings = (ROOT / "app" / "templates" / "settings.html").read_text(encoding="utf-8")
        assert 'id="credential-health-card"' in settings
        assert 'id="credential-health-body"' in settings

    def test_it_loads_with_the_rest_of_settings(self):
        assert "loadCredentialHealth()" in js_function("loadSettings")

    def test_it_is_exported(self):
        app_js = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
        exported = set(re.findall(r"^\s{4}([A-Za-z_][A-Za-z0-9_]*),\s*$", app_js, re.M))
        assert "loadCredentialHealth" in exported

    def test_the_worst_rows_come_first(self):
        """The only rows worth acting on are the bad ones."""
        source = self._source()
        assert "rows.sort(" in source
        assert "likely_expired" in source

    def test_a_failed_fetch_leaves_the_card_hidden_rather_than_empty(self):
        """An empty "Credential health" heading reads as "nothing configured"."""
        source = self._source()
        catch = source[source.index("} catch (err) {") : source.index("if (!Array.isArray(rows)")]
        assert "return" in catch
        assert "display = ''" not in catch

    def test_it_offers_the_durable_alternative_as_the_actual_fix(self):
        """Re-pasting a 2-hour cookie restarts the cycle; the alternative ends it."""
        assert "durable_alternative_missing" in self._source()

    def test_the_update_button_is_owner_only(self):
        """Credentials are owner-gated everywhere else."""
        assert "_isOwner ?" in self._source()

    def test_it_renders_no_credential_value(self):
        """Verified in a browser too: the seeded placeholder never reached the DOM.

        The endpoint is documented as never returning values; this asserts the
        renderer does not start printing one if that ever changes.
        """
        source = self._source()
        for forbidden in ("row.value", "row.secret", "row.password", "row.token"):
            assert forbidden not in source, f"the renderer reads {forbidden}"


class TestRunningCostsAreShownWithoutBeingInvented:
    """fleet/economics and earnings/net, both orphaned since 1.10.x.

    The whole point of these endpoints is that the answer is often "this
    machine is not worth leaving on" or "we cannot tell". Rendering them at all
    is only useful if the uncertainty survives the trip to the screen — a zero
    where the cost is unknown would turn gross into apparent profit, which is
    the exact dishonesty app/power.py exists to prevent.
    """

    def _fleet(self) -> str:
        return (ROOT / "app" / "templates" / "fleet.html").read_text(encoding="utf-8")

    def test_the_fleet_page_has_somewhere_to_show_it(self):
        page = self._fleet()
        assert 'id="fleet-economics-card"' in page
        assert 'id="fleet-economics-body"' in page

    def test_it_starts_hidden(self):
        """With no tariff the answer is "unknown", and saying so daily is noise."""
        page = self._fleet()
        card = page[page.index('id="fleet-economics-card"') - 120 :][:260]
        assert "display:none" in card.replace(" ", "")

    def test_it_loads_with_the_rest_of_the_fleet_page(self):
        assert "loadFleetEconomics()" in self._fleet()

    def test_an_unknown_cost_renders_as_unknown_not_as_zero(self):
        """A zero cost makes gross look like profit."""
        page = self._fleet()
        assert "v == null ? '—'" in page.replace('"', "'"), "money() must distinguish null from 0"

    def test_the_backend_sentence_is_rendered_rather_than_reworded(self):
        """Every branch already states its own uncertainty precisely."""
        assert "esc(m.summary)" in self._fleet()

    def test_only_attributable_service_costs_are_listed(self):
        assert "s.cost_attributable" in self._fleet()

    def test_what_was_withheld_is_counted_out_loud(self):
        """Dropping rows silently would read as "these services cost nothing"."""
        page = self._fleet()
        assert "withheld" in page
        assert "still counted in the machine totals" in page

    def test_a_failed_fetch_leaves_the_card_hidden(self):
        page = self._fleet()
        block = page[page.index("async function loadFleetEconomics()") :][:1400]
        assert "Leave hidden" in block or "return;   // Leave hidden" in block
