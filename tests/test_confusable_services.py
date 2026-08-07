"""Two services that are easy to confuse must not hide which one holds money.

CashPilot-cp5g. The catalog ships "ProxyBase" and "ProxyBase Markets" as
separate deployable services. They are genuinely different products --
different domains, different container images, different payout models -- but
only ONE of them generates a wallet whose volume is the sole copy of the key,
and the catalog's own text says deleting that volume "destroys the funds with
it".

I confused the two myself while reading the code, which is what makes this
worth a test rather than a comment: the failure mode on a wrong guess is
permanent loss of funds, and the names differ by a single word.

The invariant is deliberately general, not a proxybase special case: whenever
one service's name is a prefix of another's, and exactly one of the pair holds
irreplaceable state, the one that does must say so where a user choosing
between them will read it.
"""

import pathlib

import pytest
import yaml

SERVICES = pathlib.Path(__file__).resolve().parent.parent / "services"


def _load_all():
    out = []
    for f in sorted(SERVICES.rglob("*.yml")):
        if f.name.startswith("_"):
            continue
        try:
            d = yaml.safe_load(f.read_text())
        except yaml.YAMLError:  # schema tests elsewhere own malformed YAML
            continue
        if isinstance(d, dict) and d.get("slug"):
            out.append((f, d))
    return out


def _holds_irreplaceable_state(entry: dict) -> bool:
    return bool((entry.get("docker") or {}).get("critical_volumes"))


def _confusable_pairs():
    """Pairs whose display names collide at a glance: one is a prefix of the other."""
    services = _load_all()
    pairs = []
    for fa, a in services:
        for fb, b in services:
            if a["slug"] >= b["slug"]:
                continue
            na, nb = (a.get("name") or "").strip(), (b.get("name") or "").strip()
            if not na or not nb:
                continue
            lo, hi = sorted([na, nb], key=len)
            if hi.lower().startswith(lo.lower()):
                pairs.append(((fa, a), (fb, b)))
    return pairs


def test_there_is_at_least_one_confusable_pair():
    """Negative control.

    If the catalog ever contains no confusable pair, the test below passes
    without checking anything. That would be a real change worth noticing
    rather than a silent pass, so it is asserted explicitly.
    """
    pairs = _confusable_pairs()
    assert pairs, (
        "no name-prefix collisions found -- either the catalog changed shape or "
        "the detector is broken; the invariant below would be vacuous"
    )


@pytest.mark.parametrize(
    "pair",
    _confusable_pairs(),
    ids=lambda p: f"{p[0][1]['slug']}|{p[1][1]['slug']}",
)
def test_confusable_pair_says_which_one_holds_money(pair):
    (fa, a), (fb, b) = pair
    holders = [x for x in (a, b) if _holds_irreplaceable_state(x)]

    # Both or neither holding state is not the dangerous shape -- the danger is
    # a pair where one is destructive to get wrong and the other is not.
    if len(holders) != 1:
        pytest.skip("pair does not mix a state-holding service with a stateless one")

    holder = holders[0]
    other = b if holder is a else a
    desc = (holder.get("short_description") or "").lower()

    assert desc, f"{holder['slug']} has no short_description to distinguish it"

    # It must reference the state it holds. A user choosing between two
    # near-identical names has nothing else to go on at that moment.
    assert any(word in desc for word in ("wallet", "key", "seed")), (
        f"{holder['slug']} generates irreplaceable state but its short_description "
        f"does not mention it, while {other['slug']} has a near-identical name "
        f"({holder.get('name')!r} vs {other.get('name')!r}). Deleting the wrong "
        f"one destroys funds permanently."
    )

    # And the two descriptions must not themselves be interchangeable.
    assert (holder.get("short_description") or "") != (other.get("short_description") or ""), (
        f"{holder['slug']} and {other['slug']} share a short_description, so the "
        f"catalog offers no way to tell them apart"
    )
