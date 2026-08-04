"""Is this MACHINE worth keeping powered on? (CashPilot-l01)

The question people ask is "does this service make money", and for a shared box
that question has no honest answer. Adding a bandwidth container to a machine
that is already on costs roughly 1-3 W — about EUR 0.19 a month at EUR
0.105/kWh — which is **below the measurement error of a consumer smart plug**.
A per-service "net profit" figure there would be fabricated precision: it would
look authoritative and be noise.

The question that does have an answer is about the machine. A dedicated ~65 W
node at EUR 0.20/kWh costs about EUR 9.50 a month against a typical USD 3-6
gross from a single node. That is net negative, it is knowable, and nobody is
currently told.

So this module answers per-MACHINE and refuses to answer per-service on a shared
host. That refusal is the feature, not a limitation of it.

Three rules:

* **Refuse fabricated precision.** Below the resolution of the cheapest thing
  that could check the number, there is no number — only a shrug with a decimal
  point on it.
* **Estimates are labelled estimates.** Everything here rests on a user-entered
  wattage and tariff. Both are guesses, the output inherits that, and it says so.
* **Never act on it.** No auto-stop, no throttling, no "helpful" suggestion the
  code carries out. Show the number and let the operator decide; the electricity
  is theirs and so is the call.
"""

from __future__ import annotations

from typing import Any

# DEFAULT_IDLE_WATTS used to live here: 65.0, described as what a small
# always-on server draws. It was never referenced by anything, and
# `power.DEFAULT_HOST_TDP_WATTS` is the SAME number with the same meaning and
# an actual consumer. Two constants for one quantity in two modules is worse
# than an unused one — they can drift apart silently, and the next person to
# need it has to guess which is authoritative. Import it from `power`.

HOURS_PER_MONTH = 730.0

# Below this, the marginal cost of one more container is smaller than a consumer
# smart plug can measure, so a per-service figure would be invented. Chosen from
# the bead's own research: a bandwidth container adds roughly 1-3 W.
SMART_PLUG_RESOLUTION_WATTS = 5.0

# Verdicts, worst first.
LOSING_MONEY = "losing_money"
MARGINAL = "marginal"
PROFITABLE = "profitable"
UNKNOWN = "unknown"
NOT_METERED = "not_metered"


def monthly_cost(watts: float, price_per_kwh: float) -> float:
    """Cost of leaving a machine drawing ``watts`` on for a month."""
    if watts <= 0 or price_per_kwh <= 0:
        return 0.0
    return (watts / 1000.0) * HOURS_PER_MONTH * price_per_kwh


def break_even_watts(monthly_gross: float, price_per_kwh: float) -> float | None:
    """The draw at which this machine exactly pays for its own electricity.

    None when there is no tariff — the honest answer, since without a price
    every wattage breaks even and the question is meaningless.
    """
    if price_per_kwh <= 0:
        return None
    return (monthly_gross * 1000.0) / (HOURS_PER_MONTH * price_per_kwh)


def break_even_price(monthly_gross: float, watts: float) -> float | None:
    """The electricity price at which this machine stops being worth it."""
    if watts <= 0:
        return None
    return monthly_gross / ((watts / 1000.0) * HOURS_PER_MONTH)


def assess_machine(
    *,
    name: str,
    monthly_gross: float | None,
    watts: float | None,
    price_per_kwh: float | None,
    metered: bool = True,
    dedicated: bool = False,
) -> dict[str, Any]:
    """Should this machine stay powered on for what it earns?

    ``dedicated`` means the machine exists only to run these services, so its
    WHOLE draw is attributable. On a machine that would be on anyway — a NAS, a
    home server — only the marginal draw counts, and that is too small to
    measure, so the honest output is the cost of the box rather than a verdict
    pretending the services caused it.
    """
    # None means CashPilot could not READ this machine's earnings — an offline
    # worker, not a machine that earned nothing. The two were indistinguishable,
    # so a host that had merely stopped heartbeating was told:
    # "earns about 0.00 a month and costs about 9.49 in electricity ... turning
    # it off would save that." A confident financial recommendation about a
    # machine we cannot see, and its earnings were being silently reattributed
    # to whatever workers were still reporting.
    if monthly_gross is None:
        return {
            "machine": name,
            "verdict": UNKNOWN,
            "monthly_gross": None,
            "monthly_cost": None,
            "monthly_net": None,
            "break_even_watts": None,
            "summary": (
                f"{name} is not reporting, so CashPilot cannot see what it earns. Nothing here "
                "says whether it is worth running — the last figures it sent are not evidence "
                "about now."
            ),
        }

    gross = float(monthly_gross or 0.0)

    if not metered:
        # A VPS bill does not move with CPU, so estimated watts would invent a
        # cost the user is not paying.
        return {
            "machine": name,
            "verdict": NOT_METERED,
            "monthly_gross": round(gross, 4),
            "monthly_cost": None,
            "monthly_net": None,
            "summary": (
                f"{name} is not billed by the kilowatt-hour, so electricity is not what decides "
                "whether it is worth running."
            ),
        }

    if price_per_kwh is None or price_per_kwh <= 0 or watts is None or watts <= 0:
        missing = "your electricity price" if not price_per_kwh else "this machine's power draw"
        return {
            "machine": name,
            "verdict": UNKNOWN,
            "monthly_gross": round(gross, 4),
            "monthly_cost": None,
            "monthly_net": None,
            "break_even_watts": None,
            "summary": (
                f"{name} earned {gross:.2f} last month. Without {missing} CashPilot cannot say "
                "whether that covers the electricity — and guessing would be worse than not saying."
            ),
        }

    cost = monthly_cost(watts, price_per_kwh)
    net = gross - cost
    verdict = LOSING_MONEY if net < 0 else (MARGINAL if cost > 0 and net < cost * 0.25 else PROFITABLE)

    return {
        "machine": name,
        "verdict": verdict,
        "monthly_gross": round(gross, 4),
        "monthly_cost": round(cost, 4),
        "monthly_net": round(net, 4),
        "watts": round(float(watts), 1),
        "price_per_kwh": price_per_kwh,
        "dedicated": dedicated,
        # Everything here rests on an entered wattage and tariff.
        "quality": "estimated",
        "break_even_watts": round(break_even_watts(gross, price_per_kwh) or 0.0, 1),
        "break_even_price_per_kwh": round(break_even_price(gross, watts) or 0.0, 4),
        "summary": _summary(name, gross, cost, net, verdict, dedicated),
    }


def _summary(name: str, gross: float, cost: float, net: float, verdict: str, dedicated: bool) -> str:
    if verdict == LOSING_MONEY:
        base = (
            f"{name} earns about {gross:.2f} a month and costs about {cost:.2f} in electricity — "
            f"roughly {abs(net):.2f} a month out of pocket."
        )
        return base + (
            " Since this machine runs only these services, turning it off would save that."
            if dedicated
            else " This machine would be on anyway, so treat the cost as the price of the box, not of the services."
        )
    if verdict == MARGINAL:
        return (
            f"{name} earns about {gross:.2f} a month against roughly {cost:.2f} of electricity. "
            "That is close enough to break-even that the estimate cannot really tell them apart."
        )
    return f"{name} earns about {gross:.2f} a month against roughly {cost:.2f} of electricity."


def per_service_is_meaningful(marginal_watts: float | None) -> bool:
    """Whether a per-service cost figure would mean anything at all.

    A container adding 1-3 W to a machine that is already on is below what a
    consumer smart plug can measure, so a per-service net there is invented
    precision. GPU compute is the exception — its marginal draw is large enough
    to matter — but no compute service in this catalog is Docker-deployable
    today, so that path is currently theoretical.
    """
    if marginal_watts is None:
        return False
    return marginal_watts >= SMART_PLUG_RESOLUTION_WATTS


def fleet_summary(machines: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll the per-machine verdicts into a fleet answer.

    Machines whose cost is unknown are counted separately rather than folded in
    as zero, so the total never quietly understates what the fleet costs.
    """
    known = [m for m in machines if m.get("monthly_cost") is not None]
    unknown = [m for m in machines if m.get("monthly_cost") is None]
    gross = sum(float(m.get("monthly_gross") or 0.0) for m in machines)
    # Net must compare LIKE WITH LIKE. Subtracting the cost of the machines
    # whose cost is known from the gross of ALL machines flatters the result by
    # exactly the gross of every machine whose cost is unknown — the more
    # machines you cannot price, the healthier the fleet appears. The docstring
    # promises this total "never quietly understates what the fleet costs".
    known_gross = sum(float(m.get("monthly_gross") or 0.0) for m in known)
    cost = sum(float(m.get("monthly_cost") or 0.0) for m in known)

    return {
        "machines": machines,
        "monthly_gross": round(gross, 4),
        "monthly_cost": round(cost, 4) if known else None,
        "monthly_net": round(known_gross - cost, 4) if known else None,
        "cost_known_for": len(known),
        "cost_unknown_for": len(unknown),
        "losing_money": [m["machine"] for m in machines if m.get("verdict") == LOSING_MONEY],
        "quality": "estimated",
        "summary": (
            f"Costs are known for {len(known)} of {len(machines)} machine(s)."
            if unknown
            else f"Across {len(machines)} machine(s): about {gross:.2f} earned against {cost:.2f} of electricity."
        ),
    }
