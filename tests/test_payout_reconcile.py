"""The reconciliation module must be incapable of the accusation it exists to avoid.

CashPilot-l09j. The tempting feature -- "your balance is lower than your
recorded earnings, so this service is not paying you" -- is wrong, because
withdrawing money produces exactly that picture. These tests pin the refusal
rather than the happy path, because the refusal is the whole point.
"""

from decimal import Decimal

import pytest

from app import payout_reconcile as pr


def obs(*pairs):
    return [pr.Observation(day=d, amount=Decimal(str(a))) for d, a in pairs]


RISING_LONG = obs(("2026-07-01", 0), ("2026-07-10", 5), ("2026-07-20", 12))


class TestItCannotSeeABalanceAtAll:
    def test_reconcile_takes_no_balance_parameter(self):
        """The wrong inference must not be expressible through the interface.

        This is a structural guarantee, not a stylistic one: if a balance can
        never be passed in, no caller can ask this module to compare against
        one, however much they want to.
        """
        import inspect

        params = set(inspect.signature(pr.reconcile).parameters)
        assert params == {"address", "observations", "receipts"}
        assert not any("balance" in p or "amount" in p for p in params)


class TestAbsentIsNotEmpty:
    """receipts=None (could not look) and receipts=[] (looked, nothing) differ."""

    def test_none_receipts_is_never_a_finding(self):
        v = pr.reconcile(address="0xabc", observations=RISING_LONG, receipts=None)
        assert v["state"] == pr.NO_KEY
        assert v["is_finding"] is False

    def test_empty_receipts_with_the_same_inputs_IS_a_finding(self):
        """The control that gives the test above its meaning.

        Identical address and identical earnings history; only the receipts
        argument changes from None to []. If these two ever returned the same
        verdict, the module would be treating "we did not look" as "nothing
        arrived" -- the exact confusion it is built to prevent.
        """
        v = pr.reconcile(address="0xabc", observations=RISING_LONG, receipts=[])
        assert v["state"] == pr.NOTHING_EVER_ARRIVED
        assert v["is_finding"] is True

    def test_the_two_differ(self):
        a = pr.reconcile(address="0xabc", observations=RISING_LONG, receipts=None)
        b = pr.reconcile(address="0xabc", observations=RISING_LONG, receipts=[])
        assert a["state"] != b["state"]
        assert a["is_finding"] != b["is_finding"]


class TestWithdrawalIsNotEvidenceOfNonPayment:
    def test_receipts_present_is_never_a_finding_however_small(self):
        """A user who withdrew everything still has receipts.

        This is the scenario the tempting feature gets wrong: the address holds
        nothing now, yet the service paid correctly. Because this module reads
        receipts and not balances, the case cannot even arise -- but it is
        asserted so that a future change reintroducing a balance is caught.
        """
        v = pr.reconcile(
            address="0xabc",
            observations=RISING_LONG,
            receipts=[{"hash": "0x1", "value": "1"}],
        )
        assert v["state"] == pr.RECEIPTS_SEEN
        assert v["is_finding"] is False

    def test_one_ancient_receipt_still_suppresses_the_finding(self):
        """ "Has it EVER arrived" is the question, so any receipt answers yes."""
        v = pr.reconcile(
            address="0xabc",
            observations=RISING_LONG,
            receipts=[{"hash": "0x1", "day": "2020-01-01"}],
        )
        assert v["is_finding"] is False


class TestItRefusesToSpeakTooSoon:
    def test_too_few_observations(self):
        v = pr.reconcile(
            address="0xabc",
            observations=obs(("2026-07-01", 0), ("2026-07-20", 9)),
            receipts=[],
        )
        assert v["state"] == pr.INSUFFICIENT_HISTORY
        assert v["is_finding"] is False

    def test_rose_but_over_too_short_a_span(self):
        """A service that started earning yesterday has not had a chance to pay."""
        v = pr.reconcile(
            address="0xabc",
            observations=obs(("2026-07-01", 0), ("2026-07-02", 3), ("2026-07-03", 6)),
            receipts=[],
        )
        assert v["state"] == pr.INSUFFICIENT_HISTORY
        assert v["is_finding"] is False

    def test_flat_earnings_are_nothing_to_reconcile(self):
        v = pr.reconcile(
            address="0xabc",
            observations=obs(("2026-07-01", 4), ("2026-07-10", 4), ("2026-07-20", 4)),
            receipts=[],
        )
        assert v["state"] == pr.NO_EARNINGS_CLAIMED
        assert v["is_finding"] is False

    def test_a_blip_that_reverted_is_not_a_sustained_claim(self):
        """Ends where it started: no accrual was actually claimed."""
        v = pr.reconcile(
            address="0xabc",
            observations=obs(("2026-07-01", 5), ("2026-07-10", 9), ("2026-07-20", 5)),
            receipts=[],
        )
        assert v["state"] == pr.NO_EARNINGS_CLAIMED
        assert v["is_finding"] is False

    def test_unparseable_days_refuse_rather_than_assume(self):
        """A bad date must not be treated as a wide enough window."""
        v = pr.reconcile(
            address="0xabc",
            observations=obs(("not-a-date", 0), ("also-bad", 5), ("still-bad", 12)),
            receipts=[],
        )
        assert v["is_finding"] is False


class TestNoAddress:
    @pytest.mark.parametrize("addr", [None, ""])
    def test_no_address_is_not_applicable(self, addr):
        v = pr.reconcile(address=addr, observations=RISING_LONG, receipts=[])
        assert v["state"] == pr.NOT_APPLICABLE
        assert v["is_finding"] is False


class TestExactlyOneVerdictAccuses:
    def test_only_nothing_ever_arrived_is_a_finding(self):
        """A verdict added later must default to not being an accusation.

        Enumerated from the module rather than a hand-kept list, so a new
        constant is covered the day it is added.
        """
        states = {
            v
            for k, v in vars(pr).items()
            if k.isupper() and isinstance(v, str) and not k.startswith("_") and not k.startswith("MIN_")
        }
        accusing = {s for s in states if pr._verdict(s, "x")["is_finding"]}
        assert accusing == {pr.NOTHING_EVER_ARRIVED}, f"exactly one verdict may be a finding; got {accusing}"
