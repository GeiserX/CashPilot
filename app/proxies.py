"""Proxies an owner runs copies of services through (UI side; docs/proxies.md).

A proxy is a first-class object: the owner adds it once, its credentials are
encrypted at rest with everything else, and copies of services on any worker
can be sent through it. The worker does the Docker side (app/proxy_tunnel.py).

This module holds the rules that do not need a request or a database: what a
proxy definition may contain, what the API may show of it (never a secret),
the spec a proxied copy is built from, the traffic cap, and grouping copies by
the exit IP a provider sees.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

from app import egress
from app.constants import PROXIED_FORBIDDEN_CAPS

KINDS = ("socks5", "http", "tailscale")
SECRET_FIELDS = ("username", "password", "auth_key")
DEFAULT_THRESHOLD_PCT = 90
#: GB here is the decimal gigabyte providers sell (10^9 bytes).
GB = 1_000_000_000

_HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
_EXIT_NODE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,253}$")


class ProxyInputError(ValueError):
    """A proxy definition the owner has to fix; the message names the field."""


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def clean_definition(body: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate what the owner sent and return the definition to store.

    On an edit (``existing`` given) a secret field left blank keeps the stored
    value, because the form never shows secrets back. Sending ``clear_<field>``
    removes it.
    """
    base = dict(existing or {})
    out: dict[str, Any] = {}
    out["name"] = _text(body.get("name", base.get("name")))[:80]
    if not out["name"]:
        raise ProxyInputError("Give the proxy a name")
    kind = _text(body.get("kind", base.get("kind"))).lower()
    if kind not in KINDS:
        raise ProxyInputError("The type must be socks5, http or tailscale")
    out["kind"] = kind

    for field in SECRET_FIELDS:
        sent = body.get(field)
        if body.get(f"clear_{field}"):
            out[field] = ""
        elif sent is not None and str(sent) != "":
            out[field] = str(sent)
        else:
            out[field] = str(base.get(field) or "")

    if kind == "tailscale":
        out["exit_node"] = _text(body.get("exit_node", base.get("exit_node")))
        out["login_server"] = _text(body.get("login_server", base.get("login_server")))
        if not out["auth_key"]:
            raise ProxyInputError("A Tailscale proxy needs an auth key")
        if not _EXIT_NODE_RE.match(out["exit_node"]):
            raise ProxyInputError("Name the exit node by its Tailscale name or IP")
        if out["login_server"] and not out["login_server"].startswith("https://"):
            raise ProxyInputError("The login server must be an https:// URL")
        out["host"], out["port"] = "", 0
        out["username"] = out["password"] = ""
    else:
        out["host"] = _text(body.get("host", base.get("host")))
        try:
            out["port"] = int(body.get("port", base.get("port")) or 0)
        except (TypeError, ValueError):
            out["port"] = 0
        if not _HOST_RE.match(out["host"]):
            raise ProxyInputError("The host must be a host name or an IPv4 address")
        if not 1 <= out["port"] <= 65535:
            raise ProxyInputError("The port must be between 1 and 65535")
        out["exit_node"] = out["login_server"] = ""
        out["auth_key"] = ""

    out["rotating"] = bool(body.get("rotating", base.get("rotating", False)))

    cap = body.get("cap_gb", base.get("cap_gb"))
    if cap in (None, "", 0, "0"):
        out["cap_gb"] = None
    else:
        try:
            out["cap_gb"] = float(cap)
        except (TypeError, ValueError):
            raise ProxyInputError("The traffic cap is a number of GB, or empty for none") from None
        if not 0 < out["cap_gb"] <= 1_000_000:
            raise ProxyInputError("The traffic cap must be more than 0 GB")
    try:
        pct = int(body.get("cap_threshold_pct", base.get("cap_threshold_pct")) or DEFAULT_THRESHOLD_PCT)
    except (TypeError, ValueError):
        raise ProxyInputError("The stop threshold is a percentage") from None
    if not 10 <= pct <= 100:
        raise ProxyInputError("The stop threshold must be between 10 and 100 percent")
    out["cap_threshold_pct"] = pct
    reset = body.get("reset_day", base.get("reset_day"))
    if reset in (None, "", 0, "0"):
        out["reset_day"] = None
    else:
        try:
            out["reset_day"] = int(reset)
        except (TypeError, ValueError):
            raise ProxyInputError("The reset day is a day of the month") from None
        if not 1 <= out["reset_day"] <= 28:
            raise ProxyInputError("The reset day must be between 1 and 28, so every month has it")
    return out


def public_view(proxy: dict[str, Any], copies: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """What the API returns for a proxy. Secrets appear only as "set: true"."""
    d = proxy.get("definition") or {}
    state = proxy.get("state") or {}
    view = {
        "id": proxy.get("id"),
        "name": d.get("name", ""),
        "kind": d.get("kind", ""),
        "host": d.get("host", ""),
        "port": d.get("port", 0),
        "exit_node": d.get("exit_node", ""),
        "login_server": d.get("login_server", ""),
        "rotating": bool(d.get("rotating")),
        "secrets": {field: bool(d.get(field)) for field in SECRET_FIELDS},
        "cap": cap_view(d, state),
        "last_exit_ip": state.get("last_exit_ip"),
        "last_country": state.get("last_country"),
        "last_checked_at": state.get("last_checked_at"),
        "last_test": state.get("last_test"),
        "copies": [
            {"worker_id": c["worker_id"], "slug": c["slug"], "stopped_by_cap": bool(c.get("stopped_by_cap"))}
            for c in copies or []
        ],
    }
    return view


def worker_proxy_spec(definition: dict[str, Any]) -> dict[str, Any]:
    """The proxy part of a request to a worker."""
    return {
        "kind": definition.get("kind"),
        "host": definition.get("host") or "",
        "port": int(definition.get("port") or 0),
        "username": definition.get("username") or None,
        "password": definition.get("password") or None,
        "auth_key": definition.get("auth_key") or None,
        "exit_node": definition.get("exit_node") or "",
        "login_server": definition.get("login_server") or "",
    }


def secret_values(definition: dict[str, Any]) -> list[str]:
    return [str(definition.get(f) or "") for f in SECRET_FIELDS if definition.get(f)]


# ---------------------------------------------------------------------------
# Which services can run through a proxy, and the spec they run with
# ---------------------------------------------------------------------------


def _caps(values: Any) -> list[str]:
    return [str(c).upper().removeprefix("CAP_") for c in (values or []) if isinstance(c, str)]


def refusal(svc: dict[str, Any]) -> str | None:
    """Why ``svc`` cannot run through a proxy, or None.

    A proxied copy lives inside its tunnel's network namespace. Host
    networking, published ports and devices need the host's own network or
    hardware, and a volume would be shared with the copy on the box.
    """
    docker_conf = svc.get("docker") or {}
    name = svc.get("name") or svc.get("slug") or "This service"
    if docker_conf.get("network_mode") == "host":
        return f"{name} uses the host's network, so it cannot be moved behind a proxy."
    if docker_conf.get("ports"):
        return f"{name} publishes a port on the host, which a proxied copy cannot do."
    if docker_conf.get("volumes"):
        return f"{name} keeps data in a volume or host directory, which a proxied copy would share."
    if docker_conf.get("devices"):
        return f"{name} needs a device on the host, which a proxied copy does not get."
    if risky := sorted(set(_caps(docker_conf.get("cap_add"))) & PROXIED_FORBIDDEN_CAPS):
        return (
            f"{name} asks for {', '.join(risky)}, which would let it change or bypass the tunnel's firewall, "
            "so it cannot run behind a proxy."
        )
    prohibited = (svc.get("requirements") or {}).get("proxy_prohibited")
    if prohibited:
        source = prohibited.get("source") if isinstance(prohibited, dict) else None
        return f"{name}'s terms forbid running it through a proxy or VPN" + (f" ({source})." if source else ".")
    return None


def earner_spec(recorded: dict[str, Any], docker_conf: dict[str, Any], proxy_id: int) -> dict[str, Any]:
    """The spec of a proxied copy: the deployed copy's, under its own device names.

    Built from what the service was actually deployed with on that worker (the
    record api_deploy writes after its own validation), the same way
    main._instance_spec makes extra copies, so the two paths cannot drift.
    """
    suffix = f"p{proxy_id}"
    named = {var["key"] for var in docker_conf.get("env", []) if "{hostname}" in str(var.get("default", ""))}
    env = {
        key: (f"{value}-{suffix}" if key in named and value else value)
        for key, value in (recorded.get("env") or {}).items()
    }
    spec: dict[str, Any] = {
        "image": recorded.get("custom_image") or recorded.get("image"),
        "env": env,
        "cap_add": recorded.get("cap_add") or None,
        "labels": dict(recorded.get("labels") or {}),
    }
    if recorded.get("resources"):
        spec["resources"] = recorded["resources"]
    if recorded.get("command") and docker_conf.get("command"):
        spec["command"] = re.sub(r"\$\{(\w+)\}", lambda m: env.get(m.group(1), m.group(0)), docker_conf["command"])
    elif recorded.get("command"):
        spec["command"] = recorded["command"]
    return spec


# ---------------------------------------------------------------------------
# Traffic cap
# ---------------------------------------------------------------------------


def cap_bytes(definition: dict[str, Any]) -> int | None:
    cap = definition.get("cap_gb")
    return int(float(cap) * GB) if cap else None


def threshold_bytes(definition: dict[str, Any]) -> int | None:
    cap = cap_bytes(definition)
    if cap is None:
        return None
    return int(cap * int(definition.get("cap_threshold_pct") or DEFAULT_THRESHOLD_PCT) / 100)


def cap_view(definition: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": cap_bytes(definition) is not None,
        "cap_bytes": cap_bytes(definition),
        "threshold_pct": int(definition.get("cap_threshold_pct") or DEFAULT_THRESHOLD_PCT),
        "reset_day": definition.get("reset_day"),
        "used_bytes": int(state.get("used_bytes") or 0),
        "period_start": state.get("period_start"),
        "capped_at": state.get("capped_at"),
        "cap_reason": state.get("cap_reason"),
    }


#: How long a tunnel's counter baseline is kept after its last reading. Long
#: enough that a UI outage of weeks still finds the baseline, so the traffic of
#: a tunnel that kept running is counted once, not again from zero.
BASELINE_KEEP_SECONDS = 31 * 86400


def _cap_delta(previous: int | None, prev_started: str, current: int, started_at: str) -> int:
    """Bytes a tunnel moved since the last counted reading, for the cap.

    Unlike usage.counter_delta, the age of the baseline does not matter: the
    tunnel's counters run for the container's whole life, so the difference on
    the same container and the same start is exact after any gap. A first
    sighting counts everything, since the counter began at zero when the
    tunnel started. A counter that went back, or a new start time, is a
    restart: the new counter counts from zero.
    """
    if previous is None:
        return current
    if started_at and prev_started and started_at != prev_started:
        return current
    if current < previous:
        return current
    return current - previous


def account(
    state: dict[str, Any], definition: dict[str, Any], worker_id: int, entries: list[dict[str, Any]], now: float
) -> tuple[dict[str, Any], bool]:
    """Fold one heartbeat's tunnel counters into a proxy's state.

    Returns the new state and whether this reading crossed the cap threshold.
    A missing counter is unknown, not zero; see _cap_delta for the rest.
    """
    state = dict(state)
    counters = dict(state.get("counters") or {})
    used = int(state.get("used_bytes") or 0)
    for entry in entries:
        tid = str(entry.get("tunnel_container_id") or "")
        rx, tx = entry.get("net_rx_bytes"), entry.get("net_tx_bytes")
        if not tid or not isinstance(rx, int) or not isinstance(tx, int) or rx < 0 or tx < 0:
            continue
        started = str(entry.get("tunnel_started_at") or "")
        key = f"{worker_id}:{tid}"
        prev = counters.get(key)
        prev_started = str(prev[3]) if prev and len(prev) > 3 and prev[3] else ""
        used += _cap_delta(int(prev[0]) if prev else None, prev_started, rx, started)
        used += _cap_delta(int(prev[1]) if prev else None, prev_started, tx, started)
        counters[key] = [rx, tx, now, started]
        exit_ip = egress.public_ip(entry.get("exit_ip"))
        if exit_ip:
            state["last_exit_ip"] = exit_ip
            state["last_country"] = str(entry.get("exit_country") or "") or None
            state["last_checked_at"] = datetime.fromtimestamp(now, UTC).isoformat(timespec="seconds")
    # Baselines of tunnels gone for a month are dropped, so the state cannot grow forever.
    state["counters"] = {k: v for k, v in counters.items() if now - float(v[2]) < BASELINE_KEEP_SECONDS}
    state["used_bytes"] = used
    limit = threshold_bytes(definition)
    crossed = limit is not None and not state.get("capped_at") and used >= limit
    if crossed:
        state["capped_at"] = datetime.fromtimestamp(now, UTC).isoformat(timespec="seconds")
        state["cap_reason"] = cap_reason(definition, datetime.fromtimestamp(now, UTC).date())
    return state, crossed


def cap_reason(definition: dict[str, Any], when: date) -> str:
    cap = cap_bytes(definition) or 0
    pct = int(definition.get("cap_threshold_pct") or DEFAULT_THRESHOLD_PCT)
    reset = definition.get("reset_day")
    return (
        f"{definition.get('name') or 'This proxy'} reached {pct}% of its {cap / GB:g} GB cap on {when.isoformat()}"
        + (f"; it resets on day {reset} of the month" if reset else "; reset it by hand to start the copies again")
    )


def cap_change(
    old: dict[str, Any], new: dict[str, Any], state: dict[str, Any], today: date
) -> tuple[dict[str, Any], bool]:
    """Bring the cap state in line with an edited definition.

    Returns the new state and whether the copies the cap stopped should start
    again. A cap turned on starts a fresh period, so traffic from before it
    existed never counts against it. A cap turned off, or moved above what
    this period has used, lifts the stop.
    """
    if cap_bytes(new) is not None and cap_bytes(old) is None:
        return reset_state(state, today), bool(state.get("capped_at"))
    if not state.get("capped_at"):
        return dict(state), False
    limit = threshold_bytes(new)
    if limit is None or int(state.get("used_bytes") or 0) < limit:
        out = dict(state)
        out.pop("capped_at", None)
        out.pop("cap_reason", None)
        return out, True
    if (new.get("cap_gb"), new.get("cap_threshold_pct"), new.get("reset_day"), new.get("name")) != (
        old.get("cap_gb"),
        old.get("cap_threshold_pct"),
        old.get("reset_day"),
        old.get("name"),
    ):
        # Still over: keep the stop, but say it with the new numbers.
        out = dict(state)
        out["cap_reason"] = cap_reason(new, today)
        return out, False
    return dict(state), False


def reset_state(state: dict[str, Any], today: date) -> dict[str, Any]:
    """A new period: nothing used, no cap hit. Counter baselines are kept."""
    out = dict(state)
    out["used_bytes"] = 0
    out["period_start"] = today.isoformat()
    out.pop("capped_at", None)
    out.pop("cap_reason", None)
    return out


def reset_due(definition: dict[str, Any], state: dict[str, Any], today: date) -> bool:
    """True when the period that began on the last reset day has not been started yet."""
    day = definition.get("reset_day")
    if not day:
        return False
    if today.day >= day:
        boundary = today.replace(day=day)
    else:
        prev_month = today.month - 1 or 12
        prev_year = today.year - (1 if today.month == 1 else 0)
        boundary = date(prev_year, prev_month, day)
    start = state.get("period_start")
    if not start:
        return True
    try:
        return date.fromisoformat(str(start)) < boundary
    except ValueError:
        return True


# ---------------------------------------------------------------------------
# Egress: proxied copies are grouped by the proxy's exit IP, not the box's
# ---------------------------------------------------------------------------


def proxied_entries(worker: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The proxied copies a worker's last heartbeat reported."""
    info = (worker or {}).get("system_info") or {}
    entries = info.get("proxied") if isinstance(info, dict) else None
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def proxy_exits(workers: list[dict[str, Any]], rotating_ids: set[int] | None = None) -> list[dict[str, Any]]:
    """Running proxied copies grouped by the exit IP the provider sees.

    Same invariants as egress.group_by_egress: an undetected or private exit
    is never grouped (it goes in one ``known: False`` bucket that claims
    nothing), and a proxy the owner marked as rotating is listed apart, since
    its exit changes per connection and grouping on one sample would be made up.
    """
    rotating_ids = rotating_ids or set()
    groups: dict[str, list[dict[str, Any]]] = {}
    unknown: list[dict[str, Any]] = []
    rotating: list[dict[str, Any]] = []
    for worker in workers or []:
        for entry in proxied_entries(worker):
            if str(entry.get("status")) != "running":
                continue
            member = {
                "worker_id": worker.get("id"),
                "worker_name": worker.get("name"),
                "slug": egress.container_slug(entry),
                "proxy_id": entry.get("proxy_id"),
            }
            if entry.get("proxy_id") in rotating_ids:
                rotating.append(member)
                continue
            ip = egress.public_ip(entry.get("exit_ip"))
            if ip is None:
                unknown.append(member)
            else:
                groups.setdefault(ip, []).append(member)
    out = [{"exit_ip": ip, "known": True, "members": m, "shared": len(m) > 1} for ip, m in groups.items()]
    out.sort(key=lambda g: (-len(g["members"]), g["exit_ip"]))
    if rotating:
        out.append({"exit_ip": None, "known": False, "rotating": True, "members": rotating, "shared": False})
    if unknown:
        out.append({"exit_ip": None, "known": False, "members": unknown, "shared": False})
    return out


def same_exit_copies(
    workers: list[dict[str, Any]], slug: str, exit_ip: str | None, itself: tuple[Any, Any] | None = None
) -> list[str]:
    """Where ``slug`` already leaves from ``exit_ip``: proxied copies and boxes alike.

    Empty when the exit is unknown: undetected is not shared. ``itself`` is the
    (worker_id, proxy_id) of the copy being checked, whose own entry from the
    last heartbeat is not another copy.
    """
    ip = egress.public_ip(exit_ip)
    if ip is None:
        return []
    found: list[str] = []
    for worker in workers or []:
        name = str(worker.get("name") or worker.get("id"))
        if egress.egress_of(worker) == ip and slug in egress.running_slugs(worker):
            found.append(f"{name} (its own connection)")
        for entry in proxied_entries(worker):
            if itself is not None and (worker.get("id"), entry.get("proxy_id")) == itself:
                continue
            if (
                egress.container_slug(entry) == slug
                and str(entry.get("status")) == "running"
                and egress.public_ip(entry.get("exit_ip")) == ip
            ):
                found.append(f"{name} (through proxy {entry.get('proxy_id')})")
    return found
