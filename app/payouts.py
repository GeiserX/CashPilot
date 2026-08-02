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
    days = len(points) - 1
    return gained / days if days > 0 else None


def project(
    current_balance: float,
    service: dict[str, Any] | None,
    history: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """How long until this can be cashed out?

    Every branch that cannot answer says so specifically. "Not enough data yet"
    and "this is not earning" are different problems with different fixes, and
    collapsing them into one shrug helps nobody.
    """
    threshold = min_payout(service)
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
