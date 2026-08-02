"""Producer state: is it actually earning? (CashPilot-b4e)

Container health answers "is the process up". It is computed from restarts,
crashes and check results, so a container that has produced nothing for a month
still scores 100/100. "It runs but earns nothing" is the most common complaint
in this whole product category, and container health is structurally incapable
of seeing it.

This is a SEPARATE state, deliberately. A service can be perfectly healthy as a
container and dead as a producer, and collapsing the two would hide exactly the
case a user cares about.

Three signals feed it. Two are implemented here:

* **Earnings movement** — only meaningful for a service that HAS a collector.
* **Log signals** — per-service regexes declared in the service YAML. This is
  the only signal available for the 30+ catalogued services with no collector,
  and keeping the patterns in YAML follows the rule that service-specific
  knowledge never lives in ``app/``.

The third, container network counters, needs the rx/tx figures wired through the
Docker worker heartbeat and is tracked separately.
"""

from __future__ import annotations

import re
from typing import Any

# States, best to worst. FAILING beats IDLE: a log line saying "login failed" is
# a concrete, actionable diagnosis, whereas idleness is only an observation.
PRODUCING = "producing"
IDLE = "idle"
FAILING = "failing"
UNKNOWN = "unknown"

_RANK = {PRODUCING: 0, UNKNOWN: 1, IDLE: 2, FAILING: 3}

# A regex from YAML is applied to container logs. Cap the work so a hostile or
# accidentally catastrophic pattern cannot hang the worker.
_MAX_LOG_CHARS = 200_000


def _compile(pattern: str) -> re.Pattern[str] | None:
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return None


def match_log_signals(logs: str, signals: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Return the declared signals whose pattern appears in ``logs``.

    Each signal is ``{pattern, means, state}`` from the service YAML. An invalid
    regex is skipped rather than raised: a typo in one service's catalog entry
    must not break health reporting for every other service.
    """
    if not logs or not signals:
        return []
    haystack = logs[-_MAX_LOG_CHARS:]
    hits: list[dict[str, str]] = []
    for signal in signals:
        if not isinstance(signal, dict):
            continue
        compiled = _compile(str(signal.get("pattern") or ""))
        if compiled is None or not compiled.search(haystack):
            continue
        hits.append(
            {
                "pattern": str(signal.get("pattern")),
                "means": str(signal.get("means") or "").strip() or "Matched a declared failure signal.",
                "state": str(signal.get("state") or FAILING).lower(),
            }
        )
    return hits


def assess(
    *,
    slug: str,
    has_collector: bool,
    earned_recently: bool | None,
    log_hits: list[dict[str, str]] | None = None,
    container_running: bool = True,
) -> dict[str, Any]:
    """Combine the available signals into one producer state.

    ``earned_recently`` is None when it cannot be determined — no collector, or
    not enough history. That is reported as UNKNOWN rather than guessed, because
    telling a user their service is idle when we simply cannot see its earnings
    is the same false confidence this module exists to remove.
    """
    log_hits = log_hits or []
    reasons: list[str] = []
    candidates: list[str] = []

    if not container_running:
        return {
            "slug": slug,
            "state": UNKNOWN,
            "reasons": ["The container is not running, so there is nothing to judge."],
            "log_hits": [],
        }

    for hit in log_hits:
        state = hit["state"] if hit["state"] in _RANK else FAILING
        candidates.append(state)
        reasons.append(hit["means"])

    if earned_recently is True:
        candidates.append(PRODUCING)
        reasons.append("Recorded earnings have moved recently.")
    elif earned_recently is False:
        candidates.append(IDLE)
        reasons.append("Recorded earnings have not moved recently.")
    elif has_collector:
        candidates.append(UNKNOWN)
        reasons.append("Not enough earnings history yet to judge.")
    else:
        candidates.append(UNKNOWN)
        reasons.append(
            "This service has no collector, so CashPilot cannot see its earnings. "
            "Only declared log signals can say anything about it."
        )

    state = max(candidates, key=lambda s: _RANK[s]) if candidates else UNKNOWN
    return {"slug": slug, "state": state, "reasons": reasons, "log_hits": log_hits}


def signals_for(service: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The ``health_signals`` block a service declares, or an empty list."""
    if not service:
        return []
    raw = (service.get("docker") or {}).get("health_signals") or service.get("health_signals") or []
    return [s for s in raw if isinstance(s, dict)]
