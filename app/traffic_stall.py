"""A running copy that carries almost no traffic while its service's other copies are busy.

Some clients stay connected after a dropped session and then get no work. The
container is up, its log says it runs, and the account balance still grows from
the service's other copies, so neither the health check nor the "gone quiet"
heads-up sees it. Only the traffic shows it: that one copy sends next to
nothing, hour after hour, while the copies on the other machines keep sending
their usual amount.

A service opts in with ``docker.traffic_stall`` in its catalog entry
(services/_schema.yml). The check reads the bytes each copy SENT per hour
(usage_hourly ``tx_bytes`` over ``net_seconds``). Received bytes also count
traffic the copy never asked for, such as broadcasts on the network it sits
on, and on some hosts that alone is a few MB an hour, enough to hide a stall.

It only alerts. It never restarts a copy: a restart has not yet been shown to
clear a stall. Free of app-level imports, because catalog.py validates the
declaration with it and the worker image copies catalog.py.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any

DEFAULT_SHARE = 0.05
DEFAULT_PEER_MIN_MB_PER_HOUR = 10.0
DEFAULT_HOURS = 12
# usage_hourly keeps 35 days; a week is already far longer than a stall worth waiting for.
MAX_HOURS = 168
MB = 1_000_000

Copy = tuple[int, str]  # (worker id, container name), the key of a usage_hourly line


@dataclass(frozen=True)
class Spec:
    """A service's declared check, with its defaults filled in."""

    share: float
    peer_min_bytes: float  # bytes sent per hour
    hours: int


@dataclass(frozen=True)
class Stall:
    """A copy judged stalled: what it sent and what its peers sent, in bytes per hour."""

    sent: float  # its mean over the window
    peers: float  # the median, over the window, of the other copies' hourly median


def _real(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value)


def spec_errors(spec: Any) -> list[str]:
    """What is wrong with a ``docker.traffic_stall`` declaration; empty when it is usable."""
    if not isinstance(spec, dict):
        return ["must be a mapping"]
    errors: list[str] = []
    unknown = sorted(str(k) for k in set(spec) - {"share", "peer_min_mb_per_hour", "hours"})
    if unknown:
        errors.append(f"unknown key {', '.join(unknown)}")
    share = _real(spec.get("share", DEFAULT_SHARE))
    if share is None or not 0 < share < 1:
        errors.append("share must be a number between 0 and 1")
    floor = _real(spec.get("peer_min_mb_per_hour", DEFAULT_PEER_MIN_MB_PER_HOUR))
    if floor is None or floor <= 0:
        errors.append("peer_min_mb_per_hour must be a positive number")
    hours = spec.get("hours", DEFAULT_HOURS)
    if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= MAX_HOURS:
        errors.append(f"hours must be a whole number from 1 to {MAX_HOURS}")
    return errors


def spec_of(service: dict[str, Any] | None) -> Spec | None:
    """A catalog entry's declared check, or None when it declares none or one the loader refuses."""
    raw = ((service or {}).get("docker") or {}).get("traffic_stall")
    if raw is None or spec_errors(raw):
        return None
    return Spec(
        share=float(raw.get("share", DEFAULT_SHARE)),
        peer_min_bytes=float(raw.get("peer_min_mb_per_hour", DEFAULT_PEER_MIN_MB_PER_HOUR)) * MB,
        hours=int(raw.get("hours", DEFAULT_HOURS)),
    )


def last_whole_hour(now: float) -> int:
    """The start, in epoch seconds, of the last UTC hour that has ended."""
    return int(now // 3600) * 3600 - 3600


def sent_per_hour(rows: list[dict[str, Any]]) -> dict[Copy, dict[int, float]]:
    """Each copy's bytes sent per hour, by hour, from usage_hourly rows.

    An hour with no counter or no measured interval is left out, never read as zero.
    """
    out: dict[Copy, dict[int, float]] = {}
    for r in rows:
        sent, seconds = r.get("tx_bytes"), r.get("net_seconds")
        if sent is None or not seconds or seconds <= 0:
            continue
        out.setdefault((r["worker_id"], r["container"]), {})[r["hour"]] = sent * 3600 / seconds
    return out


def judge(rows: list[dict[str, Any]], spec: Spec, now: float) -> tuple[dict[Copy, Stall], set[Copy]]:
    """The stalled copies of one service, and the copies that carried traffic in the last whole hour.

    ``rows`` are the service's usage_hourly rows over the window. A copy is
    stalled when, in each of the last ``spec.hours`` whole hours, it has a
    reading, at least one other copy has one, the median of the others is at
    least ``spec.peer_min_bytes``, and the copy sent less than ``spec.share``
    of that median. A copy carries traffic when, in the last whole hour, it
    sent at least the floor itself, or at least that share of a median that
    reached the floor. Any other copy is undecided: an hour without a reading
    says nothing, and neither does an hour in which the other copies are
    quiet too.
    """
    last = last_whole_hour(now)
    window = [last - 3600 * i for i in range(spec.hours)]
    sent = sent_per_hour(rows)
    stalled: dict[Copy, Stall] = {}
    carrying: set[Copy] = set()
    for copy, mine in sent.items():

        def peer_median(hour: int, copy: Copy = copy) -> float | None:
            others = [s[hour] for k, s in sent.items() if k != copy and hour in s]
            return statistics.median(others) if others else None

        if last in mine:
            median = peer_median(last)
            if mine[last] >= spec.peer_min_bytes or (
                median is not None and median >= spec.peer_min_bytes and mine[last] >= spec.share * median
            ):
                carrying.add(copy)
                continue
        medians: list[float] = []
        for hour in window:
            median = peer_median(hour)
            if hour not in mine or median is None or median < spec.peer_min_bytes or mine[hour] >= spec.share * median:
                break
            medians.append(median)
        else:
            stalled[copy] = Stall(
                sent=statistics.fmean(mine[h] for h in window),
                peers=statistics.median(medians),
            )
    return stalled, carrying
