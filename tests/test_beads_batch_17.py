"""CashPilot-c50: a dollar balance compared against a token minimum at 1:1.

The balance is recorded in whatever the collector reports; the payout minimum
is declared in whatever the provider cashes out in. For thirteen of the fifteen
registered collectors those agree, which is why nothing noticed. Two disagree:

* Storj — the collector reports USD (its API gives cents), the catalog declares
  ``currency: STORJ, min_amount: 4.0``;
* anyone-protocol — USD against ANYONE.

So a real $3.50 balance rendered as "Balance now: 3.50 STORJ", the card said
"0.50 to go" toward a threshold in a different unit, and the service-row
tooltip printed 4 STORJ as "$4.00". Every number the user was asked to compare
was in a unit it was not in.

Fixed by reconciling once, in payouts.min_payout_in, and using it everywhere the
two are compared: eligibility, the projection, the progress card, the service
row, the claim modal, and the "closest to payout" sort.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"


def without_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in text.splitlines())


STORJ = {"cashout": {"min_amount": 4.0, "currency": "STORJ"}}


class TestTheMinimumIsBroughtIntoTheBalancesUnit:
    def test_a_token_minimum_becomes_dollars(self):
        """4 STORJ at $0.25 is $1.00 — not "4", and not "$4.00"."""
        from app import payouts

        with patch("app.exchange_rates.to_usd", lambda amount, currency: amount * 0.25):
            assert payouts.min_payout_in(STORJ, "USD") == pytest.approx(1.0)

    def test_matching_units_are_left_exactly_alone(self):
        """The thirteen collectors that already agree must not move at all."""
        from app import payouts

        assert payouts.min_payout_in({"cashout": {"min_amount": 20.0, "currency": "USD"}}, "USD") == 20.0

    def test_an_undeclared_cashout_currency_is_taken_at_face_value(self):
        """Most catalog entries omit it because the two agree.

        Refusing to compare here would disable the payout bar for almost every
        service in the catalog — a far worse answer than the existing behaviour,
        which is correct whenever the units match.
        """
        from app import payouts

        assert payouts.min_payout_in({"cashout": {"min_amount": 20.0}}, "USD") == 20.0

    def test_an_unknown_balance_currency_is_taken_at_face_value(self):
        from app import payouts

        assert payouts.min_payout_in(STORJ, None) == 4.0

    def test_no_rate_means_no_comparison_rather_than_a_guess(self):
        """Unknown is not zero and not "eligible"."""
        from app import payouts

        with patch("app.exchange_rates.to_usd", lambda amount, currency: None):
            assert payouts.min_payout_in(STORJ, "USD") is None

    def test_a_documented_no_minimum_needs_no_rate(self):
        """Zero of anything is zero — refusing here would hide a real answer."""
        from app import payouts

        with patch("app.exchange_rates.to_usd", lambda amount, currency: None):
            assert payouts.min_payout_in({"cashout": {"min_amount": 0, "currency": "STORJ"}}, "USD") == 0.0

    def test_an_undocumented_minimum_stays_unknown(self):
        from app import payouts

        assert payouts.min_payout_in({"cashout": {}}, "USD") is None

    def test_it_converts_the_other_way_too(self):
        """A USD minimum against a token balance is the mirror case.

        Driven through the REAL rate table, not a patched helper. The first
        version of this test replaced exchange_rates.from_usd with a lambda and
        passed while production returned None for every token target: from_usd
        is deliberately fiat-only, so nothing here exercised the path it claimed
        to. Seeding the rate is the difference between testing the conversion
        and testing the mock. (CodeRabbit caught this on PR #200.)
        """
        from app import exchange_rates, payouts

        saved = dict(exchange_rates._crypto_usd)
        try:
            exchange_rates._crypto_usd["GRASS"] = 0.25  # 1 GRASS = $0.25
            got = payouts.min_payout_in({"cashout": {"min_amount": 5.0, "currency": "USD"}}, "GRASS")
            assert got == pytest.approx(20.0), "a $5 minimum is 20 GRASS at $0.25"
        finally:
            exchange_rates._crypto_usd.clear()
            exchange_rates._crypto_usd.update(saved)

    def test_an_unpriced_token_target_is_unknown_not_zero(self):
        """No rate for the token means no comparison, not a threshold of 0."""
        from app import exchange_rates, payouts

        saved = dict(exchange_rates._crypto_usd)
        try:
            exchange_rates._crypto_usd.pop("NOSUCHTOKEN", None)
            assert payouts.min_payout_in({"cashout": {"min_amount": 5.0, "currency": "USD"}}, "NOSUCHTOKEN") is None
        finally:
            exchange_rates._crypto_usd.clear()
            exchange_rates._crypto_usd.update(saved)

    def test_a_fiat_target_still_works(self):
        """The conversion is derived from to_usd, which handles both kinds."""
        from app import exchange_rates, payouts

        saved = dict(exchange_rates._fiat_rates)
        try:
            exchange_rates._fiat_rates["EUR"] = 0.80  # USD -> EUR
            got = payouts.min_payout_in({"cashout": {"min_amount": 10.0, "currency": "USD"}}, "EUR")
            assert got == pytest.approx(8.0), "a $10 minimum is EUR 8 at 0.80"
        finally:
            exchange_rates._fiat_rates.clear()
            exchange_rates._fiat_rates.update(saved)


class TestTheProjectionCountsDownInOneUnit:
    def _remaining(self, balance, currency, rate=0.25):
        from app import payouts

        history = [
            {"date": "2026-07-01", "balance": balance - 1.0, "currency": currency},
            {"date": "2026-07-31", "balance": balance, "currency": currency},
        ]
        with patch("app.exchange_rates.to_usd", lambda amount, cur: amount * rate):
            return payouts.project(balance, STORJ, history, currency)

    def test_remaining_is_in_the_balances_unit(self):
        """$3.50 against 4 STORJ at $0.25 is already PAST the $1.00 minimum."""
        out = self._remaining(3.50, "USD")
        assert out.get("remaining") == 0.0, f"still counting down to a token threshold: {out}"

    def test_a_matching_unit_is_unaffected(self):
        """The control: the ordinary case must keep its countdown."""
        from app import payouts

        history = [
            {"date": "2026-07-01", "balance": 1.0, "currency": "USD"},
            {"date": "2026-07-31", "balance": 3.50, "currency": "USD"},
        ]
        out = payouts.project(3.50, {"cashout": {"min_amount": 20.0, "currency": "USD"}}, history, "USD")
        assert out.get("remaining") == pytest.approx(16.50)

    def test_no_rate_gives_no_estimate_rather_than_a_wrong_one(self):
        from app import payouts

        history = [
            {"date": "2026-07-01", "balance": 1.0, "currency": "USD"},
            {"date": "2026-07-31", "balance": 3.50, "currency": "USD"},
        ]
        with patch("app.exchange_rates.to_usd", lambda amount, cur: None):
            out = payouts.project(3.50, STORJ, history, "USD")
        assert out.get("remaining") is None


class TestEligibilityUsesTheReconciledThreshold:
    def _eligible(self, cashout, balance, currency):
        from tests.test_eligibility import _call_breakdown, _earnings_row, _service

        row = _earnings_row("storj", balance=balance)
        row["currency"] = currency
        return _call_breakdown([row], {"storj": _service("storj", cashout=cashout)})[0]["cashout"]

    def test_a_dollar_balance_is_judged_against_the_dollar_minimum(self):
        """$3.50 vs 4 STORJ at $0.25 = $1.00: eligible, and it was not."""
        with patch("app.exchange_rates.to_usd", lambda amount, cur: amount * 0.25):
            out = self._eligible({"min_amount": 4.0, "currency": "STORJ"}, 3.50, "USD")
        assert out["eligible"] is True
        assert out["min_amount_comparable"] == pytest.approx(1.0)

    def test_the_catalogs_own_figure_is_still_reported(self):
        """The provider's wording stays available; only the comparison changed."""
        with patch("app.exchange_rates.to_usd", lambda amount, cur: amount * 0.25):
            out = self._eligible({"min_amount": 4.0, "currency": "STORJ"}, 3.50, "USD")
        assert out["min_amount"] == 4.0
        assert out["min_amount_currency"] == "STORJ"

    def test_no_rate_makes_eligibility_unknown_not_true(self):
        with patch("app.exchange_rates.to_usd", lambda amount, cur: None):
            out = self._eligible({"min_amount": 4.0, "currency": "STORJ"}, 3.50, "USD")
        assert out["eligible"] is None

    def test_the_ordinary_matching_case_is_unchanged(self):
        """The control that would catch this breaking every other service."""
        out = self._eligible({"min_amount": 20.0}, 25.0, "USD")
        assert out["eligible"] is True
        assert self._eligible({"min_amount": 20.0}, 5.0, "USD")["eligible"] is False


class TestTheCardsRenderTheUnitTheyAreIn:
    def test_the_progress_card_labels_with_the_balances_currency(self):
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        assert "data.balance_currency" in source, "the card still assumes the cashout unit"

    @pytest.mark.parametrize("count", [3])
    def test_every_comparison_site_uses_the_reconciled_minimum(self, count):
        """Service row, claim modal, and the closest-to-payout sort."""
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        assert source.count("min_amount_comparable") >= count, (
            "a comparison site still divides a balance by the catalog's declared minimum"
        )

    def test_no_site_still_divides_by_the_raw_declared_minimum(self):
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        assert "/ coA.min_amount)" not in source
        # The row no longer recomputes eligibility at all — it reads the
        # endpoint's three-valued answer, which is the only side that knows
        # whether a rate was available. This assertion used to require the local
        # `balance >= minAmount`; keeping it would have blocked the better fix.
        assert "co.eligible === true" in source, "the row must still state eligibility from somewhere"
        assert "min_amount_comparable" in source, "the reconciled threshold is still what the bar uses"


class TestTheCatalogStillContainsTheCaseThisIsAbout:
    """If Storj's YAML is ever normalised, this fix stops being exercised."""

    def _cashout(self, slug):
        for path in ROOT.joinpath("services").rglob(f"{slug}.yml"):
            return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("cashout") or {}
        return {}

    def test_storj_still_declares_a_token_minimum(self):
        assert self._cashout("storj").get("currency") == "STORJ"

    def test_the_storj_collector_still_reports_usd(self):
        source = (ROOT / "app" / "collectors" / "storj.py").read_text(encoding="utf-8")
        assert 'currency="USD"' in source


class TestTheThresholdAlwaysNamesItsUnit:
    """CodeRabbit, PR #200: min_amount without a currency cannot be attributed.

    With nothing collected there is no balance currency, so min_payout_in hands
    back the catalog figure at face value — and the response labelled it with
    None, leaving a consumer holding a number in no stated unit.
    """

    async def _progress(self, history):
        from app import main

        service = {"name": "Storj", "cashout": {"min_amount": 4.0, "currency": "STORJ"}}
        with (
            patch.object(main, "_require_auth_api", lambda r: None),
            patch.object(main.catalog, "get_service", lambda slug: service),
            patch.object(main.database, "get_latest_balance", AsyncMock(return_value=None if not history else 3.5)),
            patch.object(main.database, "get_balance_history", AsyncMock(return_value=history)),
            patch.object(main.database, "get_payouts", AsyncMock(return_value=[])),
        ):
            return await main.api_payout_progress(MagicMock(), "storj")

    @pytest.mark.asyncio
    async def test_a_never_collected_service_reports_the_declared_unit(self):
        out = await self._progress([])
        assert out["min_amount"] == 4.0
        assert out["min_amount_currency"] == "STORJ", "the threshold has no attributable unit"

    @pytest.mark.asyncio
    async def test_a_collected_service_reports_the_balances_unit(self):
        """The control: once there is a balance, the unit is the balance's."""
        from app import exchange_rates

        saved = dict(exchange_rates._crypto_usd)
        try:
            exchange_rates._crypto_usd["STORJ"] = 0.25
            out = await self._progress([{"date": "2026-08-01", "balance": 3.5, "currency": "USD"}])
            assert out["min_amount_currency"] == "USD"
            assert out["min_amount"] == pytest.approx(1.0)
        finally:
            exchange_rates._crypto_usd.clear()
            exchange_rates._crypto_usd.update(saved)


class TestUnknownEligibilityStaysUnknownInTheUI:
    """CodeRabbit, PR #200: my own fix reintroduced the bug it was removing.

    The endpoint answers three-valued — True, False, or null when no rate makes
    the comparison possible. The service row did `co.min_amount_comparable ?? 0`
    and then `balance >= 0`, rating EVERY positive balance as eligible; the
    claim modal rendered the same null as "Below minimum payout". Two opposite
    wrong answers from one unknown.
    """

    def _js(self):
        return without_comments(APP_JS.read_text(encoding="utf-8"))

    def test_the_row_does_not_coerce_a_null_threshold_to_zero(self):
        assert "co.min_amount_comparable ?? 0" not in self._js()

    def test_the_row_takes_eligibility_from_the_endpoint(self):
        """Recomputing it locally is what let the two sides disagree."""
        assert "co.eligible === true" in self._js()

    def test_the_row_hides_the_bar_when_the_units_cannot_be_reconciled(self):
        assert "comparable && minAmount > 0" in self._js()

    def test_the_modal_has_a_third_state(self):
        js = self._js()
        assert "eligibilityUnknown" in js
        assert "Cannot tell yet" in js

    def test_the_modal_explains_why_rather_than_guessing(self):
        js = self._js()
        assert "cannot be compared" in js
        assert "will not guess" in js

    def test_the_modal_still_says_below_minimum_when_it_knows(self):
        """The control: the ordinary negative answer must survive."""
        assert "Below minimum payout" in self._js()
