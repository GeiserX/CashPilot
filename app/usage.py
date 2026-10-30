"""What each earning service costs its server: CPU, memory and traffic per day.

The worker already sends every container's CPU %, memory and Docker's network
counters in its heartbeat. This module turns those readings into per-day usage
rows, so the dashboard can set what a service uses against what it earns.

The network counters are CUMULATIVE since the container started, so traffic is
the difference between two readings, with three rules:

* **A counter that went backwards is a restart.** Docker resets the counters
  when the container restarts, so the new reading IS the traffic since the
  restart. Counting it (rather than dropping it, or subtracting into a negative)
  keeps a busy service that restarts often from looking idle.

* **A baseline too old to trust is replaced, not differenced.** When a worker
  was offline for hours the container may have restarted several times; the
  difference would land hours of traffic on whatever day the worker came back.
  Past MAX_BASELINE_AGE_SECONDS we start over and count nothing for that gap.

* **Missing counters are not zero.** A host-network container has no
  per-container counters at all. Its traffic is unknown and stays unknown
  (``None``), so the panel shows a dash, never 0 B.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Heartbeats arrive every 60 s. An hour covers a UI restart or a short worker
# outage; anything longer is a gap we refuse to attribute to one day.
MAX_BASELINE_AGE_SECONDS = 3600.0


def counter_delta(previous: int | None, current: int | None, seconds_since: float | None) -> int | None:
    """Bytes moved between two cumulative readings of one container.

    ``None`` means the reading carries no counter at all. ``0`` means we have a
    counter but nothing to compare it with yet (first sight, or a stale
    baseline), so the reading only becomes the next baseline.
    """
    if current is None or current < 0:
        return None
    if previous is None or seconds_since is None or seconds_since < 0:
        return 0
    if seconds_since > MAX_BASELINE_AGE_SECONDS:
        return 0
    if current < previous:
        # Restarted: the counter began again from zero.
        return current
    return current - previous


@dataclass
class ServiceSample:
    """One heartbeat's usage for one service on one worker (all its instances)."""

    cpu_percent: float | None = None
    memory_mb: float | None = None
    rx_bytes: int | None = None
    tx_bytes: int | None = None
    # (container_id, rx, tx) to store as the next baseline.
    counters: list[tuple[str, int, int]] = field(default_factory=list)
    # A running container of this service had no counters (host network, or a
    # worker that does not send them), so the traffic above is not the whole
    # service and no per-GB figure may be built on it.
    traffic_gap: bool = False


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out >= 0 else None


def _add(total: float | int | None, value: float | int | None) -> float | int | None:
    if value is None:
        return total
    return value if total is None else total + value


def samples_from_heartbeat(
    containers: list[dict[str, Any]],
    baselines: dict[str, tuple[int, int, float]],
    now: float,
) -> dict[str, ServiceSample]:
    """Per-service usage from one heartbeat's container list.

    ``baselines`` maps container_id to ``(rx, tx, seen_at)`` from the previous
    heartbeat. Only running containers count: a stopped one uses nothing, and
    its last counters are kept as they were.
    """
    out: dict[str, ServiceSample] = {}
    for c in containers:
        if not isinstance(c, dict):
            continue
        slug = c.get("slug")
        if not slug or str(c.get("status") or "").lower() != "running":
            continue
        sample = out.setdefault(slug, ServiceSample())
        sample.cpu_percent = _add(sample.cpu_percent, _num(c.get("cpu_percent")))
        sample.memory_mb = _add(sample.memory_mb, _num(c.get("memory_mb")))

        cid = str(c.get("container_id") or "")
        rx_raw, tx_raw = c.get("net_rx_bytes"), c.get("net_tx_bytes")
        if not cid or rx_raw is None or tx_raw is None:
            sample.traffic_gap = True
            continue
        try:
            rx, tx = int(rx_raw), int(tx_raw)
        except (TypeError, ValueError):
            sample.traffic_gap = True
            continue
        prev = baselines.get(cid)
        age = None if prev is None else now - prev[2]
        d_rx = counter_delta(None if prev is None else prev[0], rx, age)
        d_tx = counter_delta(None if prev is None else prev[1], tx, age)
        if d_rx is None or d_tx is None:
            sample.traffic_gap = True
            continue
        sample.rx_bytes = _add(sample.rx_bytes, d_rx)
        sample.tx_bytes = _add(sample.tx_bytes, d_tx)
        sample.counters.append((cid, rx, tx))
    return out


def per_gb(earned: float | None, byte_count: int | None) -> float | None:
    """Earnings per GB, or None when either side is unknown or the traffic is tiny.

    Under 10 MB the ratio is noise: a service that moved 2 MB and earned a cent
    would read as the best earner on the fleet.
    """
    if earned is None or byte_count is None or byte_count < 10 * 1024 * 1024:
        return None
    return earned / (byte_count / 1024**3)
