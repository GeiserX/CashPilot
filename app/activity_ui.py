"""Activity on the UI side: checking what a worker sent, and the alert rules.

Pure functions, no database and no I/O, so every rule can be tested with
plain data. The worker side is app/activity.py; storage is in app/database.py.

Raw remote addresses only ever reach ``activity_dest_raw`` (24 h). Nothing
built here for an alert, a log line or an aggregate carries an address or a
network name.
"""

from __future__ import annotations

import ipaddress
import json
import statistics
from typing import Any

PAYLOAD_VERSION = 1
MAX_PAYLOAD_BYTES = 256 * 1024
MAX_SAMPLES = 64
MAX_OUT = 40
MAX_IN = 20
MAX_DESTINATIONS = 400
#: How long a remote address is kept (database.ACTIVITY_RAW_SECONDS, pinned by a test).
RAW_HOURS = 24

STATUSES = ("ok", "host_network", "no_network", "sandboxed", "probe_failed", "skipped_budget")
CLASSES = ("infra", "metadata", "docker_host", "peer", "lan", "tailnet", "link_local", "multicast", "public")
STATES = ("est", "syn_sent", "syn_recv", "other")
COUNTERS = ("opens", "passive_opens", "attempt_fails", "resets", "udp_in", "udp_out")
GAUGES = ("est_max", "syn_sent_max", "udp_bound", "remotes_total")

#: Destinations of these classes are an earner reaching into the owner's own networks.
LAN_ALERT_CLASSES = ("lan", "tailnet", "docker_host", "metadata", "link_local")
MAIL_PORTS = (25, 465, 587, 2525)
MAIL_COOLDOWN_HOURS = 24
LAN_COOLDOWN_HOURS = 6
SPIKE_COOLDOWN_HOURS = 12
#: A spike needs this much history, this ratio over the median, and this floor.
SPIKE_MIN_HOURS = 72
SPIKE_RATIO = 10
SPIKE_BYTES_FLOOR = 1024**3
SPIKE_OPENS_FLOOR = 2000

CLASS_LABELS = {
    "lan": "your local network",
    "tailnet": "your tailnet",
    "docker_host": "the Docker host itself",
    "metadata": "a cloud metadata address",
    "link_local": "a link-local address",
}


def _int(value: Any, low: int = 0, high: int = 2**62) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if low <= value <= high else None


def _text(value: Any, limit: int) -> str:
    return str(value if value is not None else "")[:limit]


def _ip(value: Any) -> str | None:
    try:
        addr = ipaddress.ip_address(str(value))
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        return str(addr.ipv4_mapped)
    return str(addr)


def _port(value: Any) -> int | None:
    return _int(value, 0, 65535)


def _states(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    out = {}
    for key, count in value.items():
        n = _int(count, 0, 10_000)
        if key in STATES and n is not None:
            out[key] = n
    return out


def _sample(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    container = _text(raw.get("container"), 128)
    if not container:
        return None
    status = raw.get("status") if raw.get("status") in STATUSES else "probe_failed"
    members = raw.get("members") if isinstance(raw.get("members"), list) else []
    s: dict[str, Any] = {
        "container": container,
        "status": status,
        "reason": _text(raw.get("reason"), 32),
        "members": [_text(m, 128) for m in members[:16] if m],
        "network_mode": _text(raw.get("network_mode"), 160),
        "truncated": bool(raw.get("truncated")),
    }
    for key in COUNTERS + GAUGES:
        s[key] = _int(raw.get(key))
    ports = raw.get("listen_ports") if isinstance(raw.get("listen_ports"), list) else []
    s["listen_ports"] = sorted({p for p in (_port(x) for x in ports[:20]) if p is not None})
    out_rows = []
    for row in (raw.get("out") if isinstance(raw.get("out"), list) else [])[:MAX_OUT]:
        if not isinstance(row, list) or len(row) != 6:
            continue
        proto, ip, port, cls, seen, states = row
        ip, port, seen = _ip(ip), _port(port), _int(seen, 1, 10)
        if proto in ("tcp", "udp") and ip and port is not None and cls in CLASSES and seen:
            out_rows.append(
                {"proto": proto, "ip": ip, "port": port, "class": cls, "seen": seen, "states": _states(states)}
            )
    in_rows = []
    for row in (raw.get("in") if isinstance(raw.get("in"), list) else [])[:MAX_IN]:
        if not isinstance(row, list) or len(row) != 4:
            continue
        ip, lport, cls, seen = row
        ip, lport, seen = _ip(ip), _port(lport), _int(seen, 1, 10)
        if ip and lport is not None and cls in CLASSES and seen:
            in_rows.append({"ip": ip, "port": lport, "class": cls, "seen": seen})
    s["out"], s["in"] = out_rows, in_rows
    return s


def sanitise(payload: Any, now: float) -> dict[str, Any] | None:
    """The worker's window, checked and clipped; None when it is not one we read.

    Every cap the worker applies is applied again here: a worker is trusted to
    run, not to be correct.
    """
    if not isinstance(payload, dict) or payload.get("v") != PAYLOAD_VERSION:
        return None
    end = _int(payload.get("window_end"))
    # A window from the future (past a clock skew allowance) or older than the
    # raw retention is not stored: it would be purged at once or never.
    if end is None or end > now + 600 or end < now - 86400:
        return None
    end -= end % 300
    samples = []
    budget = MAX_DESTINATIONS
    for raw in (payload.get("samples") if isinstance(payload.get("samples"), list) else [])[:MAX_SAMPLES]:
        s = _sample(raw)
        if s is None:
            continue
        keep = len(s["out"]) + len(s["in"])
        if keep > budget:
            s["out"] = s["out"][:budget]
            s["in"] = s["in"][: max(0, budget - len(s["out"]))]
            s["truncated"] = True
        budget -= len(s["out"]) + len(s["in"])
        samples.append(s)
    leftovers = payload.get("leftover_probes") if isinstance(payload.get("leftover_probes"), list) else []
    return {
        "window_end": end,
        "worker_status": _text(payload.get("worker_status"), 32) or "ok",
        "leftover_probes": [_text(x, 128) for x in leftovers[:16]],
        "samples": samples,
    }


def alert_findings(window: dict[str, Any]) -> list[dict[str, Any]]:
    """The mail and LAN alerts one sanitised window raises, without any address.

    Mail: outbound TCP to a public address on a mail port, connected or
    connecting. LAN: any outbound destination in LAN_ALERT_CLASSES; infra and
    peer never count. Each finding is (kind, container, class or port, count).
    """
    found = []
    for s in window.get("samples") or []:
        mail = [
            d
            for d in s["out"]
            if d["proto"] == "tcp"
            and d["class"] == "public"
            and d["port"] in MAIL_PORTS
            and (d["states"].get("est") or d["states"].get("syn_sent"))
        ]
        if mail:
            ports = sorted({d["port"] for d in mail})
            found.append(
                {
                    "kind": "activity_mail",
                    "container": s["container"],
                    "detail": "",
                    "message": (
                        f"{s['container']} opened {len(mail)} mail connection(s) to the internet "
                        f"(port {', '.join(str(p) for p in ports)}). Earners have no reason to send mail; "
                        "this is how an exit node gets your address listed as a spam source."
                    ),
                }
            )
        by_class: dict[str, list[dict[str, Any]]] = {}
        for d in s["out"]:
            if d["class"] in LAN_ALERT_CLASSES:
                by_class.setdefault(d["class"], []).append(d)
        for cls, rows in sorted(by_class.items()):
            pending = any(d["states"].get("syn_sent") for d in rows)
            ports = sorted({d["port"] for d in rows})[:5]
            if cls == "metadata":
                message = (
                    f"{s['container']} tried to reach a cloud metadata address (port {', '.join(map(str, ports))}). "
                    "On a cloud server that address can hand out credentials for the whole account."
                )
            else:
                message = (
                    f"{s['container']} tried to reach {CLASS_LABELS[cls]}: {len(rows)} destination(s), "
                    f"port {', '.join(map(str, ports))}."
                )
            if pending:
                message += " Some were still pending (no answer yet), which usually means a firewall dropped them."
            found.append({"kind": "activity_lan", "container": s["container"], "detail": cls, "message": message})
    return found


def _usable(values: list[float | None]) -> list[float]:
    return [float(v) for v in values if v is not None]


def spike(history: list[float | None], latest: float | None, floor: float) -> bool:
    """True when ``latest`` is a spike against ``history`` (hours before it).

    Null hours (no counters, no reading) are skipped, never read as zero, and no
    verdict is given on fewer than SPIKE_MIN_HOURS usable hours.
    """
    usable = _usable(history)
    if latest is None or len(usable) < SPIKE_MIN_HOURS:
        return False
    return latest > floor and latest > SPIKE_RATIO * statistics.median(usable)


def human_bytes(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TiB"


# ---------------------------------------------------------------------------
# The per-worker switch
# ---------------------------------------------------------------------------

FLAG_SUFFIX = "activity"
TRUTHY = {"1", "true", "yes", "on"}  # database._TRUTHY, pinned equal by a test

#: What the worker said about its last round, by worker id: not stored, a
#: restart forgets it until the next window arrives.
LAST_STATUS: dict[int, dict[str, Any]] = {}


def flag_key(worker: dict[str, Any]) -> str:
    """The config key of a worker's switch: client_id first, as _worker_config_key does."""
    return f"worker_{worker.get('client_id') or worker.get('id') or ''}_{FLAG_SUFFIX}"


def enabled(config: dict[str, Any], worker: dict[str, Any]) -> bool:
    """Is Activity switched on for this worker. Unset means off."""
    for key in (flag_key(worker), f"worker_{worker.get('id')}_{FLAG_SUFFIX}"):
        value = str(config.get(key, "") or "").strip()
        if value:
            return value.lower() in TRUTHY
    return False


# ---------------------------------------------------------------------------
# What the page reads
# ---------------------------------------------------------------------------


def _sum(values: list[Any]) -> int | None:
    usable = [v for v in values if v is not None]
    return sum(usable) if usable else None


def _max(values: list[Any]) -> int | None:
    usable = [v for v in values if v is not None]
    return max(usable) if usable else None


def series(rows: list[dict[str, Any]], days: int) -> list[list[Any]]:
    """[time, opens, attempt_fails, est_max] per 5-minute window (1 day) or per hour."""
    if days <= 1:
        return [[r["window_end"], r["opens"], r["attempt_fails"], r["est_max"]] for r in rows]
    by_hour: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        by_hour.setdefault((r["window_end"] - 1) // 3600 * 3600, []).append(r)
    return [
        [h, _sum([r["opens"] for r in rs]), _sum([r["attempt_fails"] for r in rs]), _max([r["est_max"] for r in rs])]
        for h, rs in sorted(by_hour.items())
    ]


def dims(rows: list[dict[str, Any]], top: int = 5) -> dict[str, list[list[Any]]]:
    """Per dimension, the values with the most sightings, as [value, sightings]."""
    totals: dict[str, dict[str, int]] = {}
    for r in rows:
        bucket = totals.setdefault(r["dim"], {})
        bucket[r["value"]] = bucket.get(r["value"], 0) + int(r["sightings"])
    return {
        dim: [[v, n] for v, n in sorted(values.items(), key=lambda kv: (-kv[1], kv[0]))[:top]]
        for dim, values in totals.items()
    }


def container_rows(
    samples: list[dict[str, Any]], hourly: list[dict[str, Any]], alert_subjects: dict[str, int], cid: str, days: int
) -> list[dict[str, Any]]:
    """One entry per container of one worker, newest status first in each."""
    by_container: dict[str, list[dict[str, Any]]] = {}
    for r in samples:
        by_container.setdefault(r["container"], []).append(r)
    hourly_by: dict[str, list[dict[str, Any]]] = {}
    for r in hourly:
        hourly_by.setdefault(r["container"], []).append(r)
    out = []
    for name, rows in sorted(by_container.items()):
        rows.sort(key=lambda r: r["window_end"])
        last = rows[-1]
        top = dims(hourly_by.get(name, []))
        out.append(
            {
                "container": name,
                "status": last["status"],
                "reason": last["reason"],
                "members": _json_list(last["members"]),
                "network_mode": last["network_mode"],
                "listen_ports": _json_list(last["listen_ports"]),
                "last_window": last["window_end"],
                "est_max": last["est_max"],
                "remotes_total": last["remotes_total"],
                "truncated": bool(last["truncated"]),
                "opens_last": last["opens"],
                "attempt_fails_last": last["attempt_fails"],
                "series": series(rows, days),
                "top_ports": top.get("port", []),
                "top_asn": top.get("asn", []),
                "top_cc": top.get("cc", []),
                "classes": dict(top_all(hourly_by.get(name, []), "class")),
                "dirs": dict(top_all(hourly_by.get(name, []), "dir")),
                "alerts": sum(n for subject, n in alert_subjects.items() if subject.startswith(f"{cid}:{name}")),
            }
        )
    return out


def top_all(rows: list[dict[str, Any]], dim: str) -> list[tuple[str, int]]:
    totals: dict[str, int] = {}
    for r in rows:
        if r["dim"] == dim:
            totals[r["value"]] = totals.get(r["value"], 0) + int(r["sightings"])
    return sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))


def _json_list(text: Any) -> list[Any]:
    try:
        value = json.loads(text or "[]")
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []
