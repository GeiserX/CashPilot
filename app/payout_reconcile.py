"""Reconcile recorded earnings against payout RECEIPTS, never against a balance.

CashPilot-l09j. This module exists mainly to make one specific wrong feature
hard to build, so the reasoning is here rather than in a commit message.

THE TEMPTING VERSION: compare recorded earnings against the on-chain balance
and flag a shortfall as "this service is reporting money it is not sending".
**That inference does not hold.** A low or zero balance is equally consistent
with the user having withdrawn or moved the funds, which is the normal thing to
do with money. Shipping it would produce confident accusations against services
that paid correctly.

So this module never looks at a balance at all. The only question it can answer
is "did anything ever ARRIVE at this address, and when", and the only claim it
will make is the one receipts actually support.

The distinction the whole module turns on:

    receipts is None  -> we could not look. Says NOTHING about the service.
    receipts == []    -> we looked, and nothing has ever arrived.

Those are different claims and only the second can support a finding. This is
the same three-valued rule the rest of the codebase runs on -- absent is not
zero, and it is not true either -- applied to receipts rather than to money.

Reconciliation needs a real explorer API (incoming transfer history), which
needs a key the user supplies themselves; keyless public JSON-RPC cannot answer
it. Until then `receipts` is None everywhere and this reports NO_KEY, which is
an honest "not checked", not a clean bill of health.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# --- verdicts -------------------------------------------------------------
# Only ONE of these is a finding about the service. The rest describe the state
# of our own knowledge, and must never be rendered as if they described theirs.

NO_KEY = "no_key"
"""No explorer key, so no receipts could be fetched. Not a finding."""

NOT_APPLICABLE = "not_applicable"
"""No payout address is known for this service. Not a finding."""

INSUFFICIENT_HISTORY = "insufficient_history"
"""Too few earnings observations to say anything. Not a finding."""

NO_EARNINGS_CLAIMED = "no_earnings_claimed"
"""Recorded earnings never rose, so there is nothing to reconcile."""

RECEIPTS_SEEN = "receipts_seen"
"""Money has arrived at the address. The service is paying."""

NOTHING_EVER_ARRIVED = "nothing_ever_arrived"
"""THE ONLY FINDING. Earnings rose over a sustained window and the address has
received nothing, ever. Never emitted from a balance, and never from a
shortfall."""

#: Minimum number of earnings observations before any verdict beyond
#: INSUFFICIENT_HISTORY. A single snapshot cannot support a claim about time.
MIN_OBSERVATIONS = 3

#: Minimum span, in days, over which earnings must have risen before silence at
#: the address means anything. A service that started earning yesterday has not
#: had a chance to pay.
MIN_SPAN_DAYS = 7


@dataclass(frozen=True)
class Observation:
    """One recorded earnings reading: a cumulative balance at a point in time."""

    day: str
    amount: Decimal


def _rose_over_window(observations: list[Observation]) -> bool:
    """True when recorded earnings genuinely increased across the window.

    Uses first vs last rather than any-increase: a single blip that reverted
    is not a sustained claim of accrual, and reconciling against it would
    manufacture findings out of noise.
    """
    if len(observations) < MIN_OBSERVATIONS:
        return False
    ordered = sorted(observations, key=lambda o: o.day)
    return ordered[-1].amount > ordered[0].amount


def _span_days(observations: list[Observation]) -> int:
    """Calendar span between the first and last observation, in whole days."""
    if len(observations) < 2:
        return 0
    ordered = sorted(observations, key=lambda o: o.day)
    from datetime import date

    try:
        first = date.fromisoformat(ordered[0].day)
        last = date.fromisoformat(ordered[-1].day)
    except ValueError:
        # An unparseable day is a reason to say nothing, never a reason to
        # assume the window is wide enough.
        return 0
    return (last - first).days


def reconcile(
    *,
    address: str | None,
    observations: list[Observation] | None,
    receipts: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Return a verdict about whether a service has ever actually paid.

    `receipts` is the load-bearing argument and its three states are distinct:

    * ``None``  -- not checked (no key, lookup failed, chain unsupported).
    * ``[]``    -- checked, and nothing has ever arrived.
    * non-empty -- money has arrived.

    A balance is deliberately not a parameter. There is no way to pass one in,
    which is the point: the wrong inference cannot be expressed through this
    interface.
    """
    if not address:
        return _verdict(NOT_APPLICABLE, "No payout address is known for this service.")

    # Not checked. This must never collapse into "nothing arrived" -- that is
    # the single most damaging confusion available here, because it turns our
    # own missing key into an accusation against the service.
    if receipts is None:
        return _verdict(
            NO_KEY,
            "Not checked. Reading incoming transfers needs an explorer API key, "
            "which you supply yourself; free public endpoints cannot answer it.",
        )

    if receipts:
        return _verdict(
            RECEIPTS_SEEN,
            f"{len(receipts)} incoming transfer(s) recorded at this address.",
        )

    # From here on, receipts is a CONFIRMED empty list.
    obs = observations or []
    if len(obs) < MIN_OBSERVATIONS:
        return _verdict(
            INSUFFICIENT_HISTORY,
            f"Only {len(obs)} earnings observation(s); at least {MIN_OBSERVATIONS} "
            "are needed before silence at the address means anything.",
        )

    if not _rose_over_window(obs):
        return _verdict(
            NO_EARNINGS_CLAIMED,
            "Recorded earnings did not rise over this window, so there is nothing to reconcile.",
        )

    span = _span_days(obs)
    if span < MIN_SPAN_DAYS:
        return _verdict(
            INSUFFICIENT_HISTORY,
            f"Earnings rose, but only over {span} day(s); a service needs longer "
            f"than {MIN_SPAN_DAYS} days before silence is meaningful.",
        )

    return _verdict(
        NOTHING_EVER_ARRIVED,
        f"Recorded earnings rose over {span} days, but nothing has ever arrived at this payout address.",
    )


def _verdict(state: str, detail: str) -> dict[str, Any]:
    """Shape every result identically, and mark which one is a finding.

    `is_finding` is computed here rather than by each caller so that a new
    verdict added later defaults to NOT being an accusation.
    """
    return {
        "state": state,
        "detail": detail,
        "is_finding": state == NOTHING_EVER_ARRIVED,
    }
