"""Catalog facts that were wrong against the provider's own pages.

Each case names the page it was checked against. The payout reminders read
these fields (the cash-out minimum, the claim deadline, the payout method), so a
stale value turns into a reminder at the wrong time or to the wrong place.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
import yaml

from app.collectors import COLLECTOR_MAP

ROOT = Path(__file__).resolve().parents[1]
ENTRIES = {
    (d := yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("slug", p.stem): d
    for p in sorted(ROOT.glob("services/*/*.yml"))
}


def test_bitping_minimum_is_five_cents():
    # https://bitping.com/help/nodes/troubleshooting-solana-payouts
    # "You can request a withdrawal once your unpaid earnings are more than $0.05 USD."
    bitping = ENTRIES["bitping"]
    assert bitping["payment"]["minimum_payout"] == "$0.05"
    assert bitping["cashout"]["min_amount"] == 0.05


@pytest.mark.parametrize("slug", ["network3", "koii", "gaganode"])
def test_gone_projects_are_dead_and_link_nowhere(slug: str):
    """Their domains now serve a spam, casino or parking page, checked 2026-11-24."""
    entry = ENTRIES[slug]
    assert entry["status"] == "dead"
    assert not (entry.get("referral") or {}).get("signup_url")
    assert not (entry.get("cashout") or {}).get("dashboard_url")


@pytest.mark.parametrize("slug", ["koii", "gaganode"])
def test_gone_projects_on_a_live_domain_are_acknowledged(slug: str):
    """Their old domain answers 200 on itself, which the weekly probe would report
    as a resurrection every week without the hand check."""
    assert ENTRIES[slug].get("resurrection_checked") == "2026-11-24"


def test_gradient_is_not_listed_as_earning():
    # https://docs.gradient.network/user-products/sentry-node-open-beta-concluded/sentry-nodes-user-guide-legacy
    # "Sentry Nodes do not receive rewards at the current moment."
    gradient = ENTRIES["gradient"]
    assert gradient["status"] == "broken"
    assert gradient["earnings"]["monthly_high"] == 0


def test_grass_names_the_stage_2_claim_deadline():
    # https://www.grass.io/learn/how-your-stage-2-rewards-allocation-works/
    # "Claim deadline: January 22nd, 2027. Unclaimed rewards will be retained by Grass."
    assert "22 January 2027" in ENTRIES["grass"]["cashout"]["notes"]


def test_wipter_pays_usdt_on_bep20_only():
    # https://wipter.com/en/terms-and-conditions-of-use, "User Payout"
    wipter = ENTRIES["wipter"]
    assert wipter["payment"]["methods"] == ["crypto"]
    assert wipter["payment"]["crypto_token"] == "USDT"
    assert "BEP20" in wipter["cashout"]["notes"]


def test_proxyrack_pays_through_tremendous_not_crypto():
    # https://help.proxyrack.com/en/articles/6532823-when-will-i-get-my-payout
    assert "crypto" not in ENTRIES["proxyrack"]["payment"]["methods"]


def test_nodle_is_on_zksync():
    # https://docs.nodle.com/nodle-on-zksync-era and
    # https://paragraph.com/@nodle/nodle-bids-farewell-to-polkadot (bridge sunset 31 Dec 2025)
    notes = ENTRIES["nodle"]["cashout"]["notes"]
    assert "ZKsync" in notes and "31 December 2025" in notes


@pytest.mark.parametrize("slug", sorted(s for s in COLLECTOR_MAP if s in ENTRIES))
def test_collector_notes_name_only_endpoints_the_collector_calls(slug: str):
    """A path in collector.notes is a claim about the code; it must be in the code.

    Collectors often keep the version in an API_BASE constant, so the version and
    the rest of the path are looked up separately.
    """
    notes = str((ENTRIES[slug].get("collector") or {}).get("notes") or "")
    source = Path(inspect.getsourcefile(COLLECTOR_MAP[slug])).read_text(encoding="utf-8")
    named = [m.groups() for m in re.finditer(r"(/v\d+)(/[\w/-]+(?:\.[\w-]+)*)", notes)]
    assert [v + p for v, p in named if v not in source or p not in source] == []
