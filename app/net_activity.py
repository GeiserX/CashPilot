"""Is anything actually crossing the wire? (CashPilot-t6y)

The third producer-state signal. Earnings movement needs a collector, which 30+
catalogued services do not have, and log signals need a pattern somebody wrote
down. Network counters need neither: every Docker container has them.

What makes this hard is that Docker's counters are CUMULATIVE totals since the
container started, so a single reading says nothing. Two readings give a rate —
and only if nothing reset in between.

Three rules, each from a way this signal lies if taken at face value:

* **A counter that went BACKWARDS is a restart, not negative traffic.** The
  totals reset to zero when the container is recreated, so subtracting the old
  reading yields a large negative number; treating that as a rate would report
  a wild figure or, worse, silently clamp to zero and call a busy service idle.
  A backwards step means "we lost the baseline", which is UNKNOWN.

* **Missing counters are not zero counters.** A container on the host network
  has NO `networks` key in Docker's stats at all — verified on a real fleet,
  where the single busiest service (a dVPN exit moving ~15 MB/s) reported
  nothing. Reading that absence as no-traffic would mark the best earner dead.
  Decided at runtime from what Docker reports, not from the catalog: an override
  can host-network a container the catalog says nothing about.

* **The idle threshold is measured, not assumed.** Idle-but-connected containers
  are not silent: on a real fleet they sit anywhere from ~5 B/s to ~600 B/s of
  keepalive chatter, so a threshold of "zero" would be wrong for almost all of
  them. See docs/research/idle-network-traffic.md for the measurements.

And one rule about what the signal can CONCLUDE. Bandwidth resale is
buyer-driven and bursty: a perfectly healthy node earns nothing while nobody is
buying. Silence therefore supports IDLE at most, and never FAILING — no amount
of quiet proves a service is broken.
"""

from __future__ import annotations

from typing import Any

MOVING = "moving"
SILENT = "silent"
UNKNOWN = "unknown"

# Below this, a container is transferring essentially nothing. Derived from
# measuring every managed container on a live fleet over two minutes: the
# quietest still-connected service sat at ~5.5 B/s, while two genuinely inactive
# ones sat at exactly 0.0 B/s. So the only distinction this data supports is
# "no measurable traffic at all" versus "some". Deliberately conservative: the
# cost of calling a working service silent is far higher than missing an idle
# one, because the first is a false alarm the user has to chase.
SILENT_BYTES_PER_SEC = 2.0

# A sample older than this is not a useful baseline: the longer the gap, the more
# likely a restart happened inside it and reset the counters without us seeing
# the step backwards.
MAX_BASELINE_AGE_SECONDS = 900.0

# Two samples closer together than this produce a rate dominated by timing jitter.
MIN_INTERVAL_SECONDS = 5.0


def totals(container: dict[str, Any] | None) -> int | None:
    """Combined rx+tx byte counter for one container, or None if unavailable.

    None is returned whenever the worker could not read the counters — most
    often a host-network container, where Docker reports no interfaces at all.
    """
    if not isinstance(container, dict):
        return None
    rx = container.get("net_rx_bytes")
    tx = container.get("net_tx_bytes")
    if rx is None and tx is None:
        return None
    try:
        total = int(rx or 0) + int(tx or 0)
    except (TypeError, ValueError):
        return None
    return total if total >= 0 else None


def rate(previous: int | None, current: int | None, seconds: float) -> float | None:
    """Bytes per second between two cumulative readings, or None.

    None means "we cannot tell", and every branch that returns it is a case
    where a number would be a fabrication:
    a missing reading, an interval too short or too long to trust, or a counter
    that went backwards because the container restarted.
    """
    if previous is None or current is None:
        return None
    if seconds < MIN_INTERVAL_SECONDS or seconds > MAX_BASELINE_AGE_SECONDS:
        return None
    if current < previous:
        # Counters reset on restart. The old baseline is meaningless now.
        return None
    return (current - previous) / seconds


def classify(bytes_per_second: float | None) -> str:
    """MOVING / SILENT / UNKNOWN for a rate."""
    if bytes_per_second is None:
        return UNKNOWN
    return SILENT if bytes_per_second < SILENT_BYTES_PER_SEC else MOVING


def describe(state: str, bytes_per_second: float | None) -> str:
    """One plain sentence a user can act on."""
    if state == MOVING:
        return f"The container is moving data ({_human(bytes_per_second)})."
    if state == SILENT:
        return (
            "The container has moved essentially no data since the last check. "
            "For a bandwidth service that can simply mean nobody is buying right now."
        )
    return "CashPilot could not measure this container's network traffic."


def _human(bytes_per_second: float | None) -> str:
    """A rate in the largest unit that keeps it readable.

    MB/s is the last unit, so the loop always returns from inside it — there is
    no trailing fallback, because a line that cannot execute is not a safety
    net, it is just a line nobody can ever check.
    """
    value = float(bytes_per_second or 0.0)
    for unit in ("B/s", "KB/s"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} MB/s"
