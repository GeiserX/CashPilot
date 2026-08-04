"""CashPilot-bgj: the catalog stated a service's payout minimum in two units.

``services/_schema.yml`` defines ``cashout.min_amount`` as "numeric, derived
from ``payment.minimum_payout``". So ``cashout.currency`` describes the unit
``min_amount`` is in — not the token the provider pays in, which is what
``payment.currency`` already records.

Three entries disagreed with themselves. Each documented the minimum in dollars
and then labelled the derived number with something else:

===============  =========================  ==================
slug             payment.minimum_payout     cashout.currency
===============  =========================  ==================
storj            ``"$4"``                   ``STORJ``
ebesucher        ``"$2"``                   ``EUR``
proxybase-xyz    ``"$1"``                   ``USDC``
===============  =========================  ==================

The bead named only storj; the other two were found by checking the same rule
across the whole catalog.

For storj that is a real distortion: 4 STORJ is around a dollar, so a user was
told they needed roughly four times what the provider actually asks. CashPilot-c50
fixed the arithmetic — the comparison now reconciles units before comparing —
but it reconciles against whatever the catalog DECLARES, so a wrong declaration
still produces a wrong threshold. This fixes the declaration.

``payment.currency`` is untouched in all three: STORJ, EUR and USDC are what the
provider actually pays in, and that is worth keeping.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "services"


def catalog():
    out = {}
    for path in sorted(SERVICES.rglob("*.yml")):
        if path.name.startswith("_"):
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        out[data.get("slug", path.stem)] = data
    return out


def _documented_in_dollars(text: str) -> bool:
    text = str(text or "").strip()
    return text.startswith("$") or "USD" in text.upper()


class TestTheMinimumIsLabelledWithTheUnitItWasDerivedFrom:
    def test_no_entry_documents_dollars_and_labels_something_else(self):
        offenders = []
        for slug, data in catalog().items():
            payment = data.get("payment") or {}
            cashout = data.get("cashout") or {}
            declared = str(cashout.get("currency") or "").strip().upper()
            if not declared or cashout.get("min_amount") is None:
                continue
            if _documented_in_dollars(payment.get("minimum_payout")) and declared != "USD":
                offenders.append((slug, payment.get("minimum_payout"), declared))
        assert not offenders, (
            f"these state the minimum in dollars but label the derived number differently: {offenders}. "
            "cashout.currency is the unit of min_amount (see services/_schema.yml); the token the "
            "provider pays in belongs in payment.currency."
        )

    @pytest.mark.parametrize("slug", ["storj", "ebesucher", "proxybase-xyz"])
    def test_the_three_named_entries_are_consistent(self, slug):
        data = catalog()[slug]
        assert str(data["cashout"]["currency"]).upper() == "USD"

    @pytest.mark.parametrize(
        ("slug", "token"),
        [("storj", "STORJ"), ("ebesucher", "EUR"), ("proxybase-xyz", "USDC")],
    )
    def test_the_payout_token_is_still_recorded(self, slug, token):
        """The control: this must not erase what the provider pays in."""
        assert catalog()[slug]["payment"]["currency"] == token

    def test_the_catalog_still_declares_non_usd_minimums_somewhere(self):
        """Guards against this passing because every currency was set to USD.

        A provider genuinely quoting its minimum in a token is legitimate; the
        rule is only that the LABEL must match what min_amount was derived from.

        The predicate reads cashout.currency, which is what this class is about.
        It first read payment.currency — a different field that this change does
        not touch, so the guard would have held even if every cashout minimum HAD
        been flattened to USD, which is precisely what it exists to catch.
        (CodeRabbit, PR #207.)
        """
        non_usd_cashout = {
            slug: (data.get("cashout") or {}).get("currency")
            for slug, data in catalog().items()
            if (data.get("cashout") or {}).get("currency")
            and str((data.get("cashout") or {}).get("currency")).upper() != "USD"
        }
        assert non_usd_cashout, "no service declares a non-USD cashout minimum — cashout.currency was flattened"
        # Twenty-one do today (mysterium MYST, grass GRASS, helium HNT, ...), so
        # a single stray edit cannot satisfy this by accident either.
        assert len(non_usd_cashout) >= 10, f"only {sorted(non_usd_cashout)} still declare a token minimum"


class TestTheReconciledThresholdIsNowRight:
    """c50 fixed the arithmetic; it reconciles against what the catalog declares.

    With STORJ declared, a $3.50 balance was measured against 4 STORJ converted
    into dollars — about $1 — so the user was told they were eligible far too
    early. With the declaration corrected there is nothing to convert and the
    threshold is the $4 the provider documents.
    """

    def test_storj_needs_no_conversion_now(self):
        from app import payouts

        service = catalog()["storj"]
        assert payouts.min_payout_in(service, "USD") == 4.0

    def test_it_no_longer_depends_on_a_token_rate(self):
        """Before this, a missing STORJ rate made the threshold unknown."""
        from unittest.mock import patch

        from app import payouts

        service = catalog()["storj"]
        with patch("app.exchange_rates.to_usd", lambda amount, currency: None):
            assert payouts.min_payout_in(service, "USD") == 4.0

    def test_the_collector_still_reports_usd(self):
        """The premise: the balance side of the comparison is dollars."""
        source = (ROOT / "app" / "collectors" / "storj.py").read_text(encoding="utf-8")
        assert 'currency="USD"' in source

    def test_a_service_declaring_a_token_minimum_still_converts(self):
        """The control: the reconciliation machinery must stay exercised."""
        from unittest.mock import patch

        from app import payouts

        token_service = {"cashout": {"min_amount": 4.0, "currency": "STORJ"}}
        with patch("app.exchange_rates.to_usd", lambda amount, currency: amount * 0.25):
            assert payouts.min_payout_in(token_service, "USD") == pytest.approx(1.0)
