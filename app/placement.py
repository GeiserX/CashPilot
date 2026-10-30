"""Where each service runs, read from the workers' own heartbeats.

The ``deployments`` table says what CashPilot once deployed. It does not say
where that service runs today: a container removed by hand, a box rebuilt, or a
deploy that never finished all leave the row behind, and every screen that
reads the row then reports a service that runs nowhere as deployed. The
workers' heartbeats are the only record of what is running now, so this module
answers "where does it run" from them, and "what was CashPilot told is
deployed but no box runs" by comparing the two.

Pure functions over rows the caller already read, so the rules can be tested
without a database or a fleet.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any


def _json(raw: Any, fallback: Any) -> Any:
    if isinstance(raw, list | dict):
        return raw
    try:
        value = json.loads(raw or "")
    except (TypeError, ValueError):
        return fallback
    return value if isinstance(value, type(fallback)) else fallback


def system_info(worker: dict[str, Any]) -> dict[str, Any]:
    return _json(worker.get("system_info"), {})


def is_android(info: dict[str, Any]) -> bool:
    """A phone, by either field the Android client has sent.

    The client is meant to send ``device_type: android``, but CashPilot-android
    0.3.0 sends only ``os: Android``. Reading ``device_type`` alone made every
    phone look like a Docker host that cannot read its socket, which switched
    the missing-container check off for the whole fleet.
    """
    return info.get("device_type") == "android" or str(info.get("os") or "").strip().lower() == "android"


def can_see_docker(worker: dict[str, Any]) -> bool:
    """Whether a missing container on this worker is evidence of anything."""
    info = system_info(worker)
    return not is_android(info) and bool(info.get("docker_available", False))


def _android_status(running: Any) -> str:
    if running is None:
        return "unknown"
    return "running" if running else "stopped"


def reported(workers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per service copy a worker last reported, online or not.

    An offline worker's last report is kept and marked: its containers may well
    still be running, and leaving them out would say the service runs nowhere.
    """
    out: list[dict[str, Any]] = []
    for w in workers:
        android = is_android(system_info(w))
        online = w.get("status") == "online"
        if android:
            for app in _json(w.get("apps"), []):
                if isinstance(app, dict) and app.get("slug"):
                    out.append(
                        {
                            "slug": app["slug"],
                            "worker_id": w.get("id"),
                            "worker": w.get("name") or str(w.get("id")),
                            "online": online,
                            "android": True,
                            "status": _android_status(app.get("running")),
                        }
                    )
            continue
        for c in _json(w.get("containers"), []):
            if isinstance(c, dict) and c.get("slug"):
                out.append(
                    {
                        "slug": c["slug"],
                        "worker_id": w.get("id"),
                        "worker": w.get("name") or str(w.get("id")),
                        "online": online,
                        "android": False,
                        "status": str(c.get("status") or "unknown"),
                    }
                )
    return out


def runs_on(workers: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """slug -> the workers that report it, one entry per worker, sorted by name.

    Several copies on one worker collapse to that worker, with the best status
    (running wins), because the question is which machines, not how many copies.
    """
    by_slug: dict[str, dict[Any, dict[str, Any]]] = {}
    for row in reported(workers):
        seen = by_slug.setdefault(row["slug"], {})
        current = seen.get(row["worker_id"])
        if current is None or (current["status"] != "running" and row["status"] == "running"):
            seen[row["worker_id"]] = {
                "worker_id": row["worker_id"],
                "name": row["worker"],
                "online": row["online"],
                "android": row["android"],
                "status": row["status"],
            }
    return {slug: sorted(rows.values(), key=lambda r: str(r["name"]).lower()) for slug, rows in by_slug.items()}


#: How long a deployment may be missing from every heartbeat before it is an
#: alert. A deploy, a redeploy or an update removes and recreates the container,
#: and a worker reports every minute; half an hour covers that with room left.
MISSING_GRACE = timedelta(minutes=30)


def _sqlite_time(value: Any) -> datetime | None:
    """SQLite's ``datetime('now')`` text (UTC, no zone) as a datetime."""
    if not isinstance(value, str) or len(value) < 19:
        return None
    try:
        return datetime.fromisoformat(value[:19].replace(" ", "T")).replace(tzinfo=UTC)
    except ValueError:
        return None


def missing(
    deployments: list[dict[str, Any]],
    specs: list[dict[str, Any]],
    workers: list[dict[str, Any]],
    *,
    now: datetime,
    first_missing: dict[tuple[str, Any], datetime],
    grace: timedelta = MISSING_GRACE,
    alerted: set[str] | frozenset[str] = frozenset(),
) -> dict[str, dict[str, Any]] | None:
    """Deployments CashPilot records that no worker runs, past the grace period.

    Two cases, one answer per service:

    * a container deployment (status other than ``external``) that no worker
      reports at all, online or offline: CashPilot says it is deployed and it
      runs nowhere;
    * a deployment recorded for one worker (``specs``: slug, worker_id,
      deployed_at) that the worker, online and able to read Docker, no longer
      reports.

    ``external`` rows are credentials-only tracking: the service runs on a phone,
    a desktop app or a browser extension CashPilot never deployed, so a worker
    not listing it says nothing.

    Returns None when the fleet cannot tell: no worker online, or an online
    Docker host that cannot read its socket (it may be the one running it). The
    caller then neither raises nor clears anything.

    ``first_missing`` remembers when each (slug, worker_id or None) was first
    seen missing and is updated in place. After the call its keys are exactly
    what is still missing or cannot be judged right now (its box went offline
    or blind): the caller keeps an alert while any key of that service remains,
    and clears it only once none does. ``alerted`` are services that already
    have a stored alert: they skip the grace period, so a restart, which empties
    ``first_missing``, neither clears nor re-pushes them.
    """
    online = [w for w in workers if w.get("status") == "online"]
    if not online:
        return None
    if any(not is_android(system_info(w)) and not can_see_docker(w) for w in online):
        return None

    where = runs_on(workers)
    by_id = {w.get("id"): w for w in workers}
    candidates: dict[tuple[str, Any], datetime | None] = {}
    held: set[tuple[str, Any]] = set()

    # Offline Docker hosts whose last report is older than a deploy cannot have
    # listed it yet: that deployment may be running there.
    offline_since = [
        _sqlite_time(w.get("last_heartbeat"))
        for w in workers
        if w.get("status") != "online" and not is_android(system_info(w))
    ]

    for d in deployments:
        slug = d.get("slug")
        if not slug or (d.get("status") or "") == "external" or slug in where:
            continue
        deployed_at = _sqlite_time(d.get("deployed_at"))
        if deployed_at is not None and any(seen is not None and seen < deployed_at for seen in offline_since):
            held.add((slug, None))
            continue
        candidates[(slug, None)] = deployed_at

    for s in specs:
        slug, wid = s.get("slug"), s.get("worker_id")
        w = by_id.get(wid)
        if not slug or w is None:
            continue
        if w.get("status") != "online" or not can_see_docker(w):
            # Cannot look right now. A verdict already reached stands until it can.
            held.add((slug, wid))
            continue
        if any(r["worker_id"] == wid for r in where.get(slug, [])):
            continue
        candidates[(slug, wid)] = _sqlite_time(s.get("deployed_at"))

    for key in set(first_missing) - set(candidates) - held:
        first_missing.pop(key, None)

    out: dict[str, dict[str, Any]] = {}
    for (slug, wid), deployed_at in sorted(candidates.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        since = first_missing.setdefault((slug, wid), now)
        # A fresh deploy gets the full grace period from the deploy itself, so
        # a slow first pull is not reported while it is still downloading.
        start = max(since, deployed_at) if deployed_at else since
        if slug not in alerted and now - start < grace:
            continue
        item = out.setdefault(
            slug,
            {
                "everywhere": False,
                "boxes": [],
                "still_on": [r["name"] for r in where.get(slug, [])],
            },
        )
        if wid is None:
            item["everywhere"] = True
        else:
            item["boxes"].append({"worker_id": wid, "name": by_id[wid].get("name") or str(wid)})
    return out
