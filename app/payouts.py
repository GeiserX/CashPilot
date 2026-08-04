"""Payouts, and the two numbers people actually want (CashPilot-1og).

The earnings table stores balance SNAPSHOTS, so a payout is invisible: the
balance simply drops. Two consequences, and both of them mislead.

First, one number is doing two jobs. "Earned" goes DOWN when you get paid, which
is the opposite of what the word means. Lifetime earned and current balance are
different questions — *how much has this ever made me* and *how much is sitting
there waiting* — and neither is answerable while they are conflated.

Second, and more demotivating: nobody can see how far away the payout is. A USD
20 minimum can be two or three months on a single device, and not knowing that
is what makes people quit before they ever cash out. Telling them "43 days at
your current rate" is a small feature that answers the biggest open question in
this category.

Two rules run through everything below:

* **Never auto-confirm a payout.** A balance falls for reasons that are not a
  payout: a provider correction, a reversed fraud check, a lost session that
  resets a counter. Recording an unconfirmed guess as income permanently
  corrupts lifetime-earned, and the user cannot tell it happened. So a drop is
  reported as PROBABLE and waits for a human.
* **Refuse to project rather than project badly.** A confident wrong date is
  worse than "not enough data yet", because the user plans around it. Zero rate,
  falling rate, and too little history are three different honest answers, not
  three ways of saying zero.
"""

from __future__ import annotations

from datetime import date
from typing import Any

# Minimum history before a trailing rate means anything. Below this a single
# good day sets the projection, and the number swings wildly day to day.
MIN_DAYS_FOR_PROJECTION = 3

# Beyond this a projection stops being information. "Four years" is not a plan,
# and rendering a precise date that far out invites belief it does not deserve.
MAX_PROJECTION_DAYS = 365

# Verdicts for a projection.
REACHED = "reached"
PROJECTED = "projected"
NOT_ENOUGH_DATA = "not_enough_data"
NOT_EARNING = "not_earning"
TOO_FAR = "too_far"
NO_THRESHOLD = "no_threshold"
NO_MINIMUM_REQUIRED = "no_minimum_required"


def min_payout(service: dict[str, Any] | None) -> float | None:
    """The provider's minimum cashout.

    Three-valued, for the same reason as every other threshold in this project:

    * a positive number is a real minimum;
    * ``0.0`` is a documented "no minimum, cash out any amount" — a real answer,
      which at least one catalogued service actually declares;
    * ``None`` means undocumented, or a value that does not parse.

    Collapsing 0 into None would tell a user with no minimum that there is
    nothing to count down to, when the truth is the opposite: they can cash out
    right now.
    """
    if not service:
        return None
    raw = (service.get("cashout") or {}).get("min_amount")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return value


def min_payout_currency(service: dict[str, Any] | None) -> str | None:
    """The unit ``min_payout`` is expressed in, straight from the catalog."""
    if not service:
        return None
    raw = (service.get("cashout") or {}).get("currency")
    text = str(raw or "").strip().upper()
    return text or None


def min_payout_in(service: dict[str, Any] | None, currency: str | None) -> float | None:
    """The provider's minimum, expressed in ``currency``.

    The minimum is declared in whatever unit the provider cashes out in, and the
    balance is recorded in whatever unit the collector reports. For thirteen of
    the fifteen collectors those agree, which is why nothing noticed. For Storj
    the collector reports USD (its API gives cents) while the catalog declares
    ``currency: STORJ, min_amount: 4.0``, and for anyone-protocol it is USD
    against ANYONE — so a $3.50 balance was compared against 4 STORJ as though
    the two were the same number, and the card told the user they had "0.50 to
    go" toward a threshold in a different unit entirely.

    ``None`` when the minimum is undocumented, when either unit is unknown, or
    when no rate is available. Unknown is not zero and not "eligible": a guess
    here sends someone to a withdrawal page that refuses them.
    """
    minimum = min_payout(service)
    if minimum is None:
        return None
    declared = min_payout_currency(service)
    target = str(currency or "").strip().upper()
    # No declared unit is the common case — most catalog entries omit it because
    # the provider pays in the same unit the collector reports. Taking the
    # minimum at face value is what the code already did, and is right whenever
    # the two agree; there is nothing better available when one is unstated.
    if not declared or not target or declared == target:
        return minimum
    if minimum == 0:
        # A documented "no minimum" is unit-free: zero of anything is zero.
        return 0.0

    # Imported here, not at module scope: this module is otherwise pure and is
    # imported by tests that must not reach for a rate table.
    from app import exchange_rates

    in_usd = minimum if declared == "USD" else exchange_rates.to_usd(minimum, declared)
    if in_usd is None:
        return None
    if target == "USD":
        return in_usd
    # The inverse is DERIVED from to_usd rather than taken from from_usd, for
    # two reasons. from_usd is deliberately fiat-only ("a USD figure has no
    # meaningful expression in a provider's token"), which is right for
    # displaying earnings but wrong here: expressing a threshold in the token
    # the balance is counted in is exactly the comparison the card needs. And
    # deriving it means the direction cannot be inverted by mistake — one unit
    # of the target is worth `unit_in_usd`, so a USD figure is that many units.
    unit_in_usd = exchange_rates.to_usd(1.0, target)
    if not unit_in_usd:
        return None
    return in_usd / unit_in_usd


def looks_like_payout(previous: float, current: float, threshold: float | None) -> bool:
    """Did this balance fall far enough to look like a cashout?

    Requires a documented threshold. Guessing one — say, "any drop over 20%" —
    would fire on every provider correction and train the user to dismiss the
    prompt, which is worse than never asking.
    """
    # A zero minimum cannot drive detection: every drop of any size would
    # qualify, so the prompt would fire on ordinary provider noise and train the
    # user to dismiss it.
    if not threshold:
        return False
    return (previous - current) >= threshold


def detect(previous: float, current: float, service: dict[str, Any] | None) -> dict[str, Any] | None:
    """A PROBABLE payout, or None. Never a confirmed one.

    The amount recorded is the size of the drop, which is what a payout of this
    balance would have been. If the user rejects it, nothing is recorded at all.
    """
    threshold = min_payout(service)
    if not looks_like_payout(previous, current, threshold):
        return None
    return {
        "platform": service.get("slug") if service else None,
        "amount": round(previous - current, 6),
        "confirmed": False,
        "reason": (
            f"The balance fell by {previous - current:.2f}, which is at least this service's "
            f"{threshold:.2f} minimum cashout. That usually means you were paid — but a provider "
            "correction can look identical, so CashPilot will not record it as income until you say so."
        ),
    }


def lifetime_earned(current_balance: float, confirmed_payouts: list[dict[str, Any]] | None) -> float:
    """Everything this platform has ever produced.

    Only CONFIRMED payouts count. Including probable ones would let a single
    misread drop inflate lifetime earnings forever, silently.
    """
    total = float(current_balance or 0.0)
    for payout in confirmed_payouts or []:
        if payout.get("confirmed"):
            total += float(payout.get("amount") or 0.0)
    return round(total, 6)


def daily_rate(history: list[dict[str, Any]] | None) -> float | None:
    """Average gain per day from a balance series, or None if unknowable.

    Each entry needs ``balance``. Negative steps are treated as payouts and
    skipped rather than subtracted — otherwise a cashout would read as a month
    of negative earnings and drag the projection into nonsense.
    """
    points = [p for p in (history or []) if p.get("balance") is not None]
    if len(points) < MIN_DAYS_FOR_PROJECTION:
        return None

    gained = 0.0
    for older, newer in zip(points, points[1:], strict=False):
        step = float(newer["balance"]) - float(older["balance"])
        if step > 0:
            gained += step

    # Divide by ELAPSED CALENDAR DAYS, not by the number of readings. A day the
    # collector failed produces no row at all, so counting intervals treats a
    # ten-day gap as one day and inflates the rate by that factor — which then
    # tells the user their payout is ten times nearer than it is.
    days = _elapsed_days(points)
    return gained / days if days and days > 0 else None


def _elapsed_days(points: list[dict[str, Any]]) -> float | None:
    """Calendar days between the first and last reading, when datable."""
    first, last = points[0].get("date"), points[-1].get("date")
    if first and last:
        try:
            span = (date.fromisoformat(str(last)) - date.fromisoformat(str(first))).days
        except ValueError:
            span = None
        if span:
            # Callers pass date-ordered history, but the distance between two
            # dates does not depend on which end you start from, and a negative
            # divisor here would invert the rate and project the payout into
            # the past rather than the future.
            return float(abs(span))
    # No usable dates: fall back to the interval count, which is correct when
    # readings really are daily and is the best available otherwise.
    return float(len(points) - 1) or None


def project(
    current_balance: float,
    service: dict[str, Any] | None,
    history: list[dict[str, Any]] | None,
    balance_currency: str | None = None,
) -> dict[str, Any]:
    """How long until this can be cashed out?

    Every branch that cannot answer says so specifically. "Not enough data yet"
    and "this is not earning" are different problems with different fixes, and
    collapsing them into one shrug helps nobody.
    """
    # The threshold has to be in the BALANCE's unit, not the provider's. For
    # Storj the collector records USD and the catalog declares the minimum in
    # STORJ, so `remaining = 4.0 - 3.50` produced "0.50 to go" where the two
    # numbers were dollars and tokens. min_payout_in returns None when they
    # cannot be reconciled, which every branch below already treats as "no
    # documented minimum" — no estimate rather than a wrong one.
    threshold = min_payout_in(service, balance_currency)
    balance = float(current_balance or 0.0)

    if threshold is None:
        return {
            "state": NO_THRESHOLD,
            "days": None,
            "summary": "This service does not publish a minimum cashout, so there is nothing to count down to.",
        }
    if threshold == 0:
        return {
            "state": NO_MINIMUM_REQUIRED,
            "days": 0,
            "remaining": 0.0,
            "summary": "This service has no minimum — whatever has accrued can be cashed out at any time.",
        }
    if balance >= threshold:
        return {
            "state": REACHED,
            "days": 0,
            "remaining": 0.0,
            "summary": f"You have reached the {threshold:g} minimum — this can be cashed out now.",
        }

    remaining = threshold - balance
    rate = daily_rate(history)
    if rate is None:
        return {
            "state": NOT_ENOUGH_DATA,
            "days": None,
            "remaining": round(remaining, 4),
            "summary": (
                f"{remaining:.2f} to go. There is not enough history yet to say how long that will take — "
                f"come back after a few more days of collection."
            ),
        }
    if rate <= 0:
        return {
            "state": NOT_EARNING,
            "days": None,
            "remaining": round(remaining, 4),
            "summary": (
                f"{remaining:.2f} to go, but this has earned nothing recently, so at the current rate it "
                "will not get there at all."
            ),
        }

    days = remaining / rate
    if days > MAX_PROJECTION_DAYS:
        return {
            "state": TOO_FAR,
            "days": None,
            "remaining": round(remaining, 4),
            "rate_per_day": round(rate, 6),
            "summary": (
                f"At {rate:.4f} a day it would take over a year to reach the {threshold:g} minimum. "
                "That is worth knowing before you leave it running."
            ),
        }
    return {
        "state": PROJECTED,
        "days": round(days, 1),
        "remaining": round(remaining, 4),
        "rate_per_day": round(rate, 6),
        "summary": f"About {days:.0f} day(s) to the {threshold:g} minimum, at {rate:.4f} a day.",
    }
