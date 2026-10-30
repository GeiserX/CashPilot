"""What each container costs its server: CPU, memory and traffic over time.

The worker already sends every container's CPU %, memory and Docker's network
counters in its heartbeat. This module turns one heartbeat into per-container
samples; app/database.py folds them into hourly rows that the dashboard draws
as lines, per server and per container.

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
  (``None``), so its line has a gap and a server total without it is marked
  as a floor, never drawn as 0 B/s.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# Heartbeats arrive every 60 s. An hour covers a UI restart or a short worker
# outage; anything longer is a gap we refuse to attribute to one hour.
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
class ContainerSample:
    """One heartbeat's reading of one running container."""

    name: str
    slug: str
    container_id: str = ""
    cpu_percent: float | None = None
    memory_mb: float | None = None
    # Bytes moved since the previous reading, and the seconds that covers. All
    # three are None until there is a baseline to difference against.
    rx_bytes: int | None = None
    tx_bytes: int | None = None
    net_seconds: float | None = None
    # (rx, tx) to store as the next baseline, None without counters.
    counters: tuple[int, int] | None = None
    # No counters at all: a host-network container, or a worker that does not
    # send them. Its traffic is unknown, so a server total without it is a floor.
    no_counters: bool = False
    # Had counters, but the traffic since the last reading is lost (a baseline
    # older than MAX_BASELINE_AGE_SECONDS).
    traffic_lost: bool = False


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    # inf/nan would poison the stored sums and break the JSON response.
    return out if math.isfinite(out) and out >= 0 else None


def samples_from_heartbeat(
    containers: list[dict[str, Any]],
    baselines: dict[str, tuple[int, int, float]],
    now: float,
) -> dict[str, ContainerSample]:
    """Per-container usage from one heartbeat, keyed by container name.

    The name, not the id: a redeploy makes a new container under the same name,
    and its line should carry on. ``baselines`` maps container_id to
    ``(rx, tx, seen_at)`` from the previous heartbeat. Only running containers
    count: a stopped one uses nothing, and draws a gap rather than a zero.
    """
    out: dict[str, ContainerSample] = {}
    for c in containers:
        if not isinstance(c, dict):
            continue
        slug = c.get("slug")
        if not slug or str(c.get("status") or "").lower() != "running":
            continue
        cid = str(c.get("container_id") or "")
        name = str(c.get("name") or cid or "")
        if not name:
            continue
        sample = out.setdefault(name, ContainerSample(name=name, slug=str(slug), container_id=cid))
        sample.cpu_percent = _num(c.get("cpu_percent"))
        sample.memory_mb = _num(c.get("memory_mb"))

        rx_raw, tx_raw = c.get("net_rx_bytes"), c.get("net_tx_bytes")
        try:
            rx, tx = int(rx_raw), int(tx_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            rx = tx = -1
        if not cid or rx < 0 or tx < 0:
            sample.no_counters = True
            continue
        sample.counters = (rx, tx)
        prev = baselines.get(cid)
        if prev is None:
            continue
        age = now - prev[2]
        if age <= 0:
            continue
        if age > MAX_BASELINE_AGE_SECONDS:
            sample.traffic_lost = True
            continue
        sample.rx_bytes = counter_delta(prev[0], rx, age)
        sample.tx_bytes = counter_delta(prev[1], tx, age)
        sample.net_seconds = age
    return out


def rate(byte_count: int | None, seconds: float | None) -> float | None:
    """Bytes per second, or None when there is no measured interval."""
    if byte_count is None or not seconds or seconds <= 0:
        return None
    return byte_count / seconds
