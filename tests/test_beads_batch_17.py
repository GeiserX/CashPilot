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
from unittest.mock import patch

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
        """A USD minimum against a token balance is the mirror case."""
        from app import payouts

        with patch("app.exchange_rates.from_usd", lambda amount, currency: amount * 4.0):
            got = payouts.min_payout_in({"cashout": {"min_amount": 5.0, "currency": "USD"}}, "GRASS")
            assert got == pytest.approx(20.0)


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
        assert "balance >= minAmount" in source, "the comparison itself should still exist"


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
