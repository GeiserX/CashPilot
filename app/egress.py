"""Egress-IP awareness across the fleet (CashPilot-5qc).

Providers cap per **IP address**, not per device. Honeygain treats more than one
active device on a network as "network overused"; EarnApp documents that extra
devices behind one IP share the same daily cap without increasing earnings.

CashPilot's whole fleet model encourages deploying one service to several
machines — and until now it warned about none of this. Two workers in the same
house are two machines to us and one customer to the provider, so the second
one earns nothing and can get the account flagged.

This is the one check a single-host tool structurally cannot perform, because
seeing it requires knowing about the *other* machines.

Three rules hold this together, and each exists because the opposite is worse
than saying nothing:

* **An undetected egress IP is not a shared one, and not a distinct one.** Two
  workers whose IP we could not determine must never be grouped as if they
  matched, nor reported as separate as if we had checked. They go to a bucket
  that says exactly that.
* **An absent ``devices_per_ip`` means nobody documented it — not "unlimited".**
  The schema uses ``0`` for unlimited, which is a real, deliberate answer. A
  missing key is not. Only ~4 of 50 services declare it today, so reading
  absence as permission would silently bless the exact mistake this module was
  written to catch.
* **A private address is a detection failure.** A worker reporting 192.168.x,
  or a tailnet 100.64/10 address, has told us about its LAN, not its egress.
  Grouping on it would invent a shared IP that does not exist — and on a
  tailnet, would group the *entire* fleet into one false conflict.
"""

from __future__ import annotations

import ipaddress
from typing import Any

# What kind of connection the worker sits on. UNKNOWN is the default and is
# never upgraded by guesswork: "we could not tell" and "we checked, it is
# residential" lead to different advice and must not be confused.
RESIDENTIAL = "residential"
HOSTING = "hosting"
UNKNOWN = "unknown"

_NETWORK_TYPES = {RESIDENTIAL, HOSTING, UNKNOWN}

# Vendor strings that appear in DMI/product identifiers on hosted machines.
# Deliberately a *local* signal: no third party is asked to profile the user's
# address, and nothing breaks when the machine is offline.
HOSTING_VENDOR_HINTS = (
    "amazon ec2",
    "digitalocean",
    "google compute engine",
    "hetzner",
    "linode",
    "microsoft corporation",  # Azure reports this as the chassis vendor
    "openstack",
    "oracle",
    "ovh",
    "scaleway",
    "vultr",
)


def classify_vendor(vendor: str | None) -> str:
    """Map a DMI vendor/product string to a network type.

    Returns UNKNOWN for anything unrecognised, including bare hypervisors like
    QEMU or VMware: a VM on a home server is a residential connection, and a
    home lab is this project's most common deployment. Calling that "hosting"
    would fire a ban warning at precisely the users who are fine.
    """
    text = (vendor or "").strip().lower()
    if not text:
        return UNKNOWN
    return HOSTING if any(hint in text for hint in HOSTING_VENDOR_HINTS) else UNKNOWN


def normalise_network_type(value: Any) -> str:
    """Accept only the three known values; anything else is UNKNOWN."""
    text = str(value or "").strip().lower()
    return text if text in _NETWORK_TYPES else UNKNOWN


def public_ip(value: Any) -> str | None:
    """Return ``value`` only if it is a usable public egress address.

    Private, loopback, link-local, multicast, reserved and shared-CGNAT
    (100.64/10 — which is also the tailnet range) addresses all mean the
    detection failed and we are looking at an interface, not an exit.
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return None
    if not addr.is_global or addr.is_multicast:
        return None
    return str(addr)


def egress_of(worker: dict[str, Any] | None) -> str | None:
    """The worker's public egress IP, or None when it is not known."""
    if not worker:
        return None
    info = worker.get("system_info") or {}
    if not isinstance(info, dict):
        return None
    return public_ip(info.get("egress_ip"))


def network_type_of(worker: dict[str, Any] | None) -> str:
    """The worker's connection type, defaulting to UNKNOWN."""
    if not worker:
        return UNKNOWN
    info = worker.get("system_info") or {}
    if not isinstance(info, dict):
        return UNKNOWN
    return normalise_network_type(info.get("egress_network_type"))


def devices_per_ip_limit(service: dict[str, Any] | None) -> int | None:
    """How many devices this service allows per IP.

    ``None`` means *not documented*, which is different from ``0`` (documented
    as unlimited). Callers must keep them apart; collapsing them is how a
    warning becomes wrong.
    """
    if not service:
        return None
    raw = (service.get("requirements") or {}).get("devices_per_ip")
    if raw is None:
        return None
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        return None
    return limit if limit >= 0 else None


def group_by_egress(workers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group workers by the IP the provider actually sees.

    The fleet view is by machine; providers count by exit. A group of two is the
    thing worth showing, so groups are returned largest first.

    Workers with no detected egress IP are collected into a single group flagged
    ``known: False``. That group is NOT a claim that they share an address — it
    is the list of machines whose exit we could not determine, and every caller
    has to treat it as unchecked rather than as a conflict.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    unknown: list[dict[str, Any]] = []

    for worker in workers or []:
        ip = egress_of(worker)
        if ip is None:
            unknown.append(worker)
        else:
            groups.setdefault(ip, []).append(worker)

    out = [
        {
            "egress_ip": ip,
            "known": True,
            "network_type": _group_network_type(members),
            "workers": members,
            "worker_count": len(members),
            "shared": len(members) > 1,
        }
        for ip, members in groups.items()
    ]
    out.sort(key=lambda g: (-g["worker_count"], g["egress_ip"]))

    if unknown:
        out.append(
            {
                "egress_ip": None,
                "known": False,
                "network_type": UNKNOWN,
                "workers": unknown,
                "worker_count": len(unknown),
                # Not "shared": we have no idea whether these share anything.
                "shared": False,
            }
        )
    return out


def _group_network_type(members: list[dict[str, Any]]) -> str:
    """One address has one connection type; disagreement means we trust none."""
    seen = {network_type_of(m) for m in members} - {UNKNOWN}
    return seen.pop() if len(seen) == 1 else UNKNOWN


def peers_sharing_egress(worker: dict[str, Any], workers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Other workers behind the same public IP as ``worker``.

    Empty when the IP is unknown — an unchecked worker has no *known* peers, and
    reporting one would be a fabrication.
    """
    ip = egress_of(worker)
    if ip is None:
        return []
    own_id = worker.get("client_id")
    return [w for w in workers or [] if w.get("client_id") != own_id and egress_of(w) == ip]


def container_slug(container: dict[str, Any] | None) -> str:
    """The service slug of one heartbeat container entry.

    Worth a named function: ``orchestrator.get_status`` emits ``slug`` and so
    does the UI's aggregation, but hand-written fixtures kept using ``service``
    — and code that read ``service`` therefore matched nothing in production
    while its tests passed. Both keys are accepted so neither shape can silently
    match zero containers again.
    """
    if not isinstance(container, dict):
        return ""
    return str(container.get("slug") or container.get("service") or "")


def running_slugs(worker: dict[str, Any] | None) -> set[str]:
    """Slugs of the containers a worker reports as running."""
    if not worker:
        return set()
    containers = worker.get("containers")
    if not isinstance(containers, list):
        return set()
    found = {
        container_slug(c) for c in containers if isinstance(c, dict) and str(c.get("status", "")).lower() == "running"
    }
    return found - {""}
