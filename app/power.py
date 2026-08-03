"""Net profit rather than gross earnings (CashPilot-f5u).

Every dashboard in this space reports what a service PAID. None report what it
COST to run. For a large share of users the honest number is negative — a
service earning EUR 2/month on hardware drawing 15W in a country at EUR 0.30/kWh
is losing money, and reporting that as income is the thing this space is worst at.

Two rules run through everything here:

* **Never present an estimate as a measurement.** A CPU-share model is crude. It
  is directionally right and far better than pretending cost is zero, but every
  figure it produces carries its quality, and the caller is expected to show it.
* **Never show net as gross.** Net is reported alongside gross, never instead of
  it, so the user can always see both numbers and the difference between them.
"""

from __future__ import annotations

from typing import Any

# Quality of a cost figure, worst to best. The UI must not render an ESTIMATED
# cost with the same confidence as a MEASURED one.
ESTIMATED = "estimated"
MEASURED = "measured"

# Fallback host draw when a worker has not declared its hardware. A small
# always-on server (NUC, Pi 5, mini PC) sits around here. It is a guess, and any
# figure derived from it is marked ESTIMATED for exactly that reason.
DEFAULT_HOST_TDP_WATTS = 65.0

# What the machine draws doing nothing. A container using 0% CPU is not free —
# it holds a share of a machine that is already powered on — but attributing the
# whole idle draw to one container would overstate its cost wildly. Idle draw is
# apportioned across containers by the caller; this is only the active part.
IDLE_FRACTION = 0.4


def estimate_watts(
    cpu_percent: float,
    *,
    host_tdp_watts: float = DEFAULT_HOST_TDP_WATTS,
    container_count: int = 1,
) -> float:
    """Estimate a container's draw from its CPU share of the host.

    ``cpu_percent`` is the container's share of the whole host, as Docker
    reports it (100.0 means one core fully saturated on a single-core host).

    The model: a host's draw splits into an idle floor it pays merely by being
    on, and an active part that scales with utilisation. A container is charged
    its CPU share of the active part, plus an equal share of the idle floor —
    because a machine kept running for ten containers costs its idle draw once,
    not ten times.
    """
    host_tdp_watts = max(0.0, float(host_tdp_watts))
    container_count = max(1, int(container_count))
    cpu_share = max(0.0, float(cpu_percent)) / 100.0

    idle_watts = host_tdp_watts * IDLE_FRACTION
    active_watts = host_tdp_watts * (1.0 - IDLE_FRACTION)

    return (idle_watts / container_count) + (active_watts * cpu_share)


def energy_cost(watts: float, hours: float, price_per_kwh: float) -> float:
    """Cost of running at ``watts`` for ``hours`` at ``price_per_kwh``."""
    if watts <= 0 or hours <= 0 or price_per_kwh <= 0:
        return 0.0
    return (watts / 1000.0) * hours * price_per_kwh


def net_for_service(
    gross: float,
    cost: float | None,
    *,
    quality: str = ESTIMATED,
) -> dict[str, Any]:
    """Gross, cost and net for one service, with the cost's quality attached.

    ``negative`` is the number worth acting on: a service whose trailing net is
    below zero is costing more in electricity than it pays, and the honest thing
    is to say so rather than let it sit in a dashboard looking like income.
    """
    gross = float(gross)
    if cost is None:
        # No tariff, so the cost is genuinely unknown. Reporting cost 0 here
        # would make net equal gross and present earnings as profit - the exact
        # dishonesty this module exists to prevent, and it must not creep back in
        # at the per-service level just because the totals get it right.
        return {
            "gross": round(gross, 4),
            "cost": None,
            "net": None,
            "cost_quality": "unknown",
            "negative": False,
        }
    cost = max(0.0, float(cost))
    net = gross - cost
    return {
        "gross": round(gross, 4),
        "cost": round(cost, 4),
        "net": round(net, 4),
        "cost_quality": quality,
        "negative": net < 0,
    }


def is_metered(worker_meta: dict[str, Any] | None) -> bool:
    """Whether the user actually pays for this machine's electricity.

    A VPS has no marginal power cost to its owner: the bill is the monthly fee,
    which does not move with CPU. Charging estimated watts against it would
    invent a cost the user is not paying, which is the same dishonesty as
    ignoring the cost on a home server.
    """
    if not worker_meta:
        return True
    if worker_meta.get("metered") is not None:
        return bool(worker_meta["metered"])
    return True


def summarise(
    services: list[dict[str, Any]],
    *,
    price_per_kwh: float,
    currency: str = "EUR",
) -> dict[str, Any]:
    """Roll per-service figures into a fleet total.

    Each entry needs ``platform``, ``gross``, ``watts`` and ``hours``; anything
    on an unmetered host should arrive with ``watts`` already zeroed.

    With no tariff configured this reports gross only and says so, rather than
    silently charging zero and presenting gross as if it were net.
    """
    configured = price_per_kwh > 0
    rows: list[dict[str, Any]] = []
    total_gross = 0.0
    total_cost = 0.0

    for svc in services:
        gross = float(svc.get("gross") or 0.0)
        cost = (
            energy_cost(float(svc.get("watts") or 0.0), float(svc.get("hours") or 0.0), price_per_kwh)
            if configured
            else None
        )
        row = net_for_service(gross, cost, quality=str(svc.get("cost_quality") or ESTIMATED))
        row["platform"] = svc.get("platform")
        # Carried through rather than recomputed. Whether a per-service cost can
        # be ATTRIBUTED is a different question from whether it is known: the
        # host really does draw the power, so the figure stays in the total, but
        # the share-out is below smart-plug resolution and a consumer should not
        # render it as if it were measured. Defaults to True so a caller that
        # does not care is unaffected.
        row["cost_attributable"] = bool(svc.get("cost_attributable", True))
        rows.append(row)
        total_gross += gross
        total_cost += cost or 0.0

    return {
        "currency": currency,
        "price_per_kwh": price_per_kwh if configured else None,
        # Without a tariff there is no net to report. Saying so is the point:
        # a zero cost would render gross as net and quietly overstate earnings.
        "cost_known": configured,
        "services": rows,
        "total_gross": round(total_gross, 4),
        "total_cost": round(total_cost, 4) if configured else None,
        "total_net": round(total_gross - total_cost, 4) if configured else None,
        "negative_services": [r["platform"] for r in rows if r["negative"]],
    }
