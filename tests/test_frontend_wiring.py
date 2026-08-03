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
        """A USD payout on a USD dashboard must not read '24.90 USD (≈ $24.90)'."""
        assert "converted !== native" in self._queue_source()


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
