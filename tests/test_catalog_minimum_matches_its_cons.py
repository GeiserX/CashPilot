"""A minimum quoted in a rating con must be the minimum the catalog uses.

UpRock's payout_terms con quoted its help centre ("a 250 UPT minimum") while
``payment.minimum_payout`` said "$5" and ``cashout.min_amount`` said 5 USD, so
the payout card counted down to a threshold the provider does not have.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
QUOTED = re.compile(r"(?P<usd>\$)?(?P<amount>\d[\d,]*(?:\.\d+)?) ?(?P<unit>[A-Z]{2,6})? minimum")


def quoted_minimums(entry: dict) -> list[tuple[float, str]]:
    found = []
    for con in (entry.get("rating") or {}).get("cons") or []:
        for m in QUOTED.finditer(str(con.get("text") or "")):
            unit = "USD" if m.group("usd") else (m.group("unit") or "")
            if unit:
                found.append((float(m.group("amount").replace(",", "")), unit))
    return found


def _stated(text: object) -> tuple[float, str] | None:
    """payment.minimum_payout as (amount, unit): "$5" is (5.0, "USD"), "250 UPT" is (250.0, "UPT")."""
    m = re.fullmatch(r"(?P<usd>\$)?(?P<amount>\d[\d,]*(?:\.\d+)?) ?(?P<unit>[A-Z]{2,6})?", str(text or "").strip())
    if not m:
        return None
    unit = "USD" if m.group("usd") else (m.group("unit") or "")
    return float(m.group("amount").replace(",", "")), unit


def mismatches(entry: dict) -> list[tuple[float, str]]:
    """Quoted minimums that disagree with cashout.min_amount or payment.minimum_payout."""
    cashout = entry.get("cashout") or {}
    derived = (cashout.get("min_amount"), str(cashout.get("currency") or "").upper())
    stated = _stated((entry.get("payment") or {}).get("minimum_payout"))
    return [q for q in quoted_minimums(entry) if q != derived or q != stated]


ENTRIES = {p.stem: yaml.safe_load(p.read_text(encoding="utf-8")) or {} for p in sorted(ROOT.glob("services/*/*.yml"))}


@pytest.mark.parametrize("slug", [s for s, e in ENTRIES.items() if quoted_minimums(e)])
def test_the_quoted_minimum_is_the_catalog_minimum(slug: str):
    assert mismatches(ENTRIES[slug]) == []


def test_some_entry_quotes_a_minimum():
    """Otherwise the test above has nothing to check."""
    assert "uprock" in [s for s, e in ENTRIES.items() if quoted_minimums(e)]


def test_the_check_catches_the_old_uprock_entry():
    old = {
        "payment": {"minimum_payout": "$5"},
        "cashout": {"min_amount": 5.0, "currency": "USD"},
        "rating": {"cons": [{"text": "withdrawals are UPT tokens to a Solana wallet, with a 250 UPT minimum."}]},
    }
    assert mismatches(old) == [(250.0, "UPT")]


def test_the_check_catches_a_stale_payment_minimum():
    """cashout.min_amount is derived from payment.minimum_payout; a stale source is caught too."""
    entry = {
        "payment": {"minimum_payout": "$5"},
        "cashout": {"min_amount": 250.0, "currency": "UPT"},
        "rating": {"cons": [{"text": "with a 250 UPT minimum."}]},
    }
    assert mismatches(entry) == [(250.0, "UPT")]
