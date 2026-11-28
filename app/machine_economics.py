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

import math
from collections.abc import Collection, Mapping
from datetime import date, timedelta
from typing import Any

from app.i18n import t

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

# Heat sources a device's heat can replace, by the per-machine setting.
HEAT_SOURCES = ("resistive", "heat_pump", "fuel")
HEAT_COP_RANGE = (1.0, 10.0)
# The English of t("machine_economics.heat_assumption"), kept for the code that tests for it.
HEAT_ASSUMPTION = "Assumes all its heat replaces heating you would otherwise pay for during those months."


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
    gross_measured: bool = True,
    heat: Mapping[str, Any] | None = None,
    heating_share: float = 0.0,
) -> dict[str, Any]:
    """Should this machine stay powered on for what it earns?

    ``gross_measured`` is False when none of the machine's services had an
    earnings reading in the window, so its 0.0 gross is an absence of data,
    not a measured zero. No break-even tariff is built on that.

    ``dedicated`` means the machine exists only to run these services, so its
    WHOLE draw is attributable. On a machine that would be on anyway — a NAS, a
    home server — only the marginal draw counts, and that is too small to
    measure, so the honest output is the cost of the box rather than a verdict
    pretending the services caused it.

    ``heat`` is a parsed heat setting (``parse_heat``) and ``heating_share``
    the fraction of the window that falls in its heating months. The credit
    is its own figure next to the cost, never folded into it.
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
            "summary": (t("machine_economics.not_reporting_cashpilot_cannot_see", name=name)),
        }

    gross = float(monthly_gross or 0.0)

    if not metered:
        # A VPS bill does not move with CPU, so estimated watts would invent a
        # cost the user is not paying.
        out = {
            "machine": name,
            "verdict": NOT_METERED,
            "monthly_gross": round(gross, 4),
            "monthly_cost": None,
            "monthly_net": None,
            "summary": (t("machine_economics.not_billed_kilowatt_hour_electricity", name=name)),
        }
        if heat is not None:
            # The credit is capped at the electricity cost, and a fixed-price
            # bill has no per-kWh cost for the heat to offset.
            out.update(heat=dict(heat), heat_credit=0.0)
        return out

    if price_per_kwh is None or price_per_kwh <= 0 or watts is None or watts <= 0:
        # A select, not a pasted phrase, so a language with cases can inflect it.
        missing = "price" if not price_per_kwh else "power_draw"
        out: dict[str, Any] = {
            "machine": name,
            "verdict": UNKNOWN,
            "monthly_gross": round(gross, 4),
            "monthly_cost": None,
            "monthly_net": None,
            "break_even_watts": None,
            "summary": (
                t(
                    "machine_economics.earned_last_month_without_cashpilot",
                    name=name,
                    gross=format(gross, ".2f"),
                    missing=missing,
                )
            ),
        }
        # The break-even TARIFF needs only the gross and the draw, not a price:
        # it is the price this machine could stand. Withholding it until a
        # tariff is typed hid the one number a user can check against a bill
        # without telling CashPilot what that bill is.
        if gross_measured and watts is not None and watts > 0:
            out["break_even_price_per_kwh"] = round(break_even_price(gross, watts) or 0.0, 4)
            out["quality"] = "estimated"
            if gross <= 0:
                out["summary"] = t("machine_economics.earned_nothing_measurable", name=name)
            if heat is not None:
                out.update(_heat_break_even(gross, watts, heat))
        if heat is not None:
            # No cost is known here, so there is nothing for the heat to offset.
            out["heat"] = dict(heat)
            out["heat_credit"] = None
        return out

    cost = monthly_cost(watts, price_per_kwh)
    credit = heat_credit(watts, price_per_kwh, heat, heating_share)
    net = gross - cost + credit
    verdict = LOSING_MONEY if net < 0 else (MARGINAL if cost > 0 and net < cost * 0.25 else PROFITABLE)

    result = {
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
        "break_even_price_per_kwh": (round(break_even_price(gross, watts) or 0.0, 4) if gross_measured else None),
        "summary": _summary(name, gross, cost, net, verdict, dedicated, credit),
    }
    if heat is not None:
        result["heat"] = dict(heat)
        result["heat_credit"] = round(credit, 4)
        if gross_measured:
            result.update(_heat_break_even(gross, watts, heat))
        result["summary"] += " " + t("machine_economics.heat_assumption")
    return result


def _heat_break_even(gross: float, watts: float, heat: Mapping[str, Any]) -> dict[str, Any]:
    """The heating-months break-even fields for an assessed row."""
    price = break_even_price_with_heat(gross, watts, heat)
    return {
        "break_even_price_per_kwh_heating": None if price is None else round(price, 4),
        "heat_covers_all_in_season": price is None and _heat_covers_all(heat),
    }


def _summary(
    name: str, gross: float, cost: float, net: float, verdict: str, dedicated: bool, credit: float = 0.0
) -> str:
    # With a heat credit, gross minus cost is no longer the net, so the
    # sentence names the credit rather than leave its figures not adding up.
    # "none" picks the select branch without the heat clause.
    amounts = {
        "name": name,
        "gross": format(gross, ".2f"),
        "cost": format(cost, ".2f"),
        "heat": format(credit, ".2f") if credit > 0 else "none",
    }
    if verdict == LOSING_MONEY:
        return t(
            "machine_economics.losing_money",
            net=format(abs(net), ".2f"),
            dedicated="yes" if dedicated else "no",
            **amounts,
        )
    if verdict == MARGINAL:
        return t("machine_economics.marginal", **amounts)
    return t("machine_economics.earns_against", **amounts)


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
    unmetered = [m for m in machines if m.get("verdict") == NOT_METERED]
    unknown = [m for m in machines if m.get("monthly_cost") is None and m.get("verdict") != NOT_METERED]
    # A machine that is not reporting has monthly_gross None, and summing that
    # as 0.0 makes the fleet total silently exclude whatever it earns. That is
    # the same "absent read as measured" mistake this function already guards
    # against for cost, so it is counted and reported the same way rather than
    # left for the reader to notice a number quietly getting smaller.
    gross_unknown = [m for m in machines if m.get("monthly_gross") is None]
    gross = sum(float(m.get("monthly_gross") or 0.0) for m in machines)
    # Net must compare LIKE WITH LIKE. Subtracting the cost of the machines
    # whose cost is known from the gross of ALL machines flatters the result by
    # exactly the gross of every machine whose cost is unknown — the more
    # machines you cannot price, the healthier the fleet appears. The docstring
    # promises this total "never quietly understates what the fleet costs".
    known_gross = sum(float(m.get("monthly_gross") or 0.0) for m in known)
    cost = sum(float(m.get("monthly_cost") or 0.0) for m in known)
    # A heat credit exists only where a cost does, so it is summed over the
    # same machines and added to the same like-with-like net.
    credit = sum(float(m.get("heat_credit") or 0.0) for m in known)

    if not (unknown or gross_unknown or unmetered):
        summary = t(
            "machine_economics.fleet_total",
            n=len(machines),
            gross=format(gross, ".2f"),
            cost=format(cost, ".2f"),
            heat=format(credit, ".2f") if credit > 0 else "none",
        )
    else:
        notes = []
        if known or unknown:
            notes.append(t("machine_economics.fleet_costs_known", known=len(known), n=len(known) + len(unknown)))
        if unmetered:
            notes.append(t("machine_economics.fleet_not_metered", n=len(unmetered)))
        if gross_unknown:
            notes.append(t("machine_economics.fleet_not_reporting", n=len(gross_unknown)))
        summary = " ".join(notes)

    return {
        "machines": machines,
        "monthly_gross": round(gross, 4),
        "monthly_cost": round(cost, 4) if known else None,
        "monthly_heat_credit": round(credit, 4) if known else None,
        "monthly_net": round(known_gross - cost + credit, 4) if known else None,
        "cost_known_for": len(known),
        "cost_unknown_for": len(unknown),
        "gross_unknown_for": len(gross_unknown),
        "losing_money": [m["machine"] for m in machines if m.get("verdict") == LOSING_MONEY],
        "quality": "estimated",
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Heat credit
#
# A miner turns every watt it draws into heat. In a month you heat the room
# anyway, that heat replaces some of what you would have paid for. The one rule:
# you can always heat with a resistive heater at your own tariff, so a kWh of
# the device's heat is worth at most the tariff. The credit therefore can never
# exceed the electricity cost, and it is shown beside the cost, never inside it.
# ---------------------------------------------------------------------------


def _finite(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def parse_heat_months(raw: Any) -> frozenset[int] | None:
    """``"11,12,1"`` as a set of calendar months, or None if empty or invalid."""
    tokens = [part.strip() for part in str(raw or "").split(",")]
    if not any(tokens):
        return None
    months: set[int] = set()
    for token in tokens:
        if not (token.isascii() and token.isdigit()) or not 1 <= int(token) <= 12:
            return None
        months.add(int(token))
    return frozenset(months)


def parse_heat(config: Mapping[str, Any], prefix: str) -> dict[str, Any] | None:
    """The heat setting stored under ``prefix``, or None for no credit.

    Every part must be present and valid. A missing month list, a COP outside
    1-10 or a fuel price that is not positive gives None, never a guess.
    Months are never filled in for the user: half the world heats in June.
    """
    source = str(config.get(f"{prefix}_heat") or "").strip().lower()
    if source not in HEAT_SOURCES:
        return None
    months = parse_heat_months(config.get(f"{prefix}_heat_months"))
    if months is None:
        return None
    heat: dict[str, Any] = {"source": source, "months": sorted(months)}
    if source == "heat_pump":
        cop = _finite(config.get(f"{prefix}_heat_cop"))
        if cop is None or not HEAT_COP_RANGE[0] <= cop <= HEAT_COP_RANGE[1]:
            return None
        heat["cop"] = cop
    elif source == "fuel":
        price = _finite(config.get(f"{prefix}_heat_price"))
        if price is None or price <= 0:
            return None
        heat["price"] = price
    return heat


def heating_share(months: Collection[int], today: date, days: int = 30) -> float:
    """The fraction of the trailing ``days`` (today included) in ``months``."""
    if days <= 0:
        return 0.0
    wanted = set(months)
    hits = sum(1 for back in range(days) if (today - timedelta(days=back)).month in wanted)
    return hits / days


def heat_value_per_kwh(heat: Mapping[str, Any], price_per_kwh: float) -> float:
    """What one kWh of the device's heat is worth: never more than the tariff."""
    if price_per_kwh <= 0:
        return 0.0
    source = heat.get("source")
    if source == "resistive":
        value = price_per_kwh
    elif source == "heat_pump":
        value = price_per_kwh / float(heat["cop"])
    elif source == "fuel":
        value = float(heat["price"])
    else:
        return 0.0
    return max(0.0, min(price_per_kwh, value))


def heat_credit(watts: float, price_per_kwh: float, heat: Mapping[str, Any] | None, share: float) -> float:
    """The monthly heat credit, never more than the monthly electricity cost."""
    if heat is None or watts <= 0 or price_per_kwh <= 0:
        return 0.0
    share = max(0.0, min(1.0, share))
    kwh = (watts / 1000.0) * HOURS_PER_MONTH
    return min(kwh * share * heat_value_per_kwh(heat, price_per_kwh), monthly_cost(watts, price_per_kwh))


def _heat_covers_all(heat: Mapping[str, Any]) -> bool:
    return heat.get("source") == "resistive" or (heat.get("source") == "heat_pump" and float(heat["cop"]) <= 1.0)


def break_even_price_with_heat(monthly_gross: float, watts: float, heat: Mapping[str, Any]) -> float | None:
    """The tariff below which it pays for itself in a heating month (share 1).

    With ``g`` the gross per kWh drawn:

    * resistive (or a heat pump with COP 1): the heat is worth the whole
      electricity cost, so it never loses money in season. None.
    * heat pump: the net ``g - p(1 - 1/COP)`` is zero at ``g / (1 - 1/COP)``.
    * fuel at ``f`` per kWh of heat: below ``f`` the heat is worth the tariff
      and it cannot lose money; above it, the net ``g - p + f`` is zero at
      ``g + f``.
    """
    if watts <= 0 or _heat_covers_all(heat):
        return None
    g = monthly_gross / ((watts / 1000.0) * HOURS_PER_MONTH)
    if heat.get("source") == "heat_pump":
        return g / (1.0 - 1.0 / float(heat["cop"]))
    if heat.get("source") == "fuel":
        return g + float(heat["price"])
    return None
