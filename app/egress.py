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

Known limitation, stated rather than hidden: grouping is exact-address equality,
so on a **native-IPv6** connection every machine has its own global /128 and two
hosts on one physical line never match. Detecting that properly means grouping
on the delegated prefix, which is a separate design decision. The consequence is
a missed conflict, never a fabricated one — which is the right way round for
this to fail, and the reason it ships as-is.
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
# Deliberately NOT here: "microsoft corporation". Azure guests do report it,
# but so do Surface hardware and Hyper-V guests — including Hyper-V on a home
# Windows desktop. A false "hosting" verdict escalates a residential-IP note
# into a ban warning, fired at a user who is fine, which is the exact failure
# classify_vendor exists to avoid. A missed VPS costs far less than that.
HOSTING_VENDOR_HINTS = (
    "amazon ec2",
    "digitalocean",
    "google compute engine",
    "hetzner",
    "linode",
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


# Address families that Python reports as global but that carry, or translate,
# an address belonging to someone else. NAT64 (64:ff9b::/96) embeds an arbitrary
# IPv4 address in its low bits — including a private one — and 6to4 (2002::/16)
# embeds one likewise, so both can smuggle a LAN address past an is_global check.
_TRANSLATION_PREFIXES = tuple(
    ipaddress.ip_network(n)
    for n in (
        "64:ff9b::/96",  # NAT64
        "64:ff9b:1::/48",  # NAT64, local-use prefix
        "2002::/16",  # 6to4
        "fec0::/10",  # deprecated site-local — a LAN address Python calls global
    )
)


def public_ip(value: Any) -> str | None:
    """Return ``value`` only if it is a usable public egress address.

    Private, loopback, link-local, multicast, reserved and shared-CGNAT
    (100.64/10 — which is also the tailnet range) addresses all mean the
    detection failed and we are looking at an interface, not an exit.

    An IPv6 address carrying an IPv4 one — mapped ``::ffff:a.b.c.d`` or the
    deprecated compatible ``::a.b.c.d`` — is unwrapped to that IPv4 form rather
    than returned verbatim. Two things depend on that: grouping is string equality,
    so the same host reported as ``81.61.1.9`` and ``::ffff:81.61.1.9`` would
    never match itself; and older 3.12 patch releases — which this project's
    ``requires-python`` still permits for a source install — got ``is_global``
    wrong for the mapped form, so unwrapping first makes the check correct
    independently of the interpreter version.
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return None
    addr = _unwrap_v4(addr)
    if any(addr in net for net in _TRANSLATION_PREFIXES if net.version == addr.version):
        return None
    if not addr.is_global or addr.is_multicast:
        return None
    return str(addr)


def _unwrap_v4(addr: Any) -> Any:
    """Reduce an IPv6 form that carries an IPv4 address to that IPv4 address.

    Covers BOTH ``::ffff:a.b.c.d`` (mapped) and the deprecated ``::a.b.c.d``
    (compatible). Python exposes a helper only for the first, and the second is
    just as dangerous: ``::192.168.1.5`` is reported global, so an unwrapped LAN
    address would become a grouping key. It also breaks self-matching, since a
    host seen once as 81.61.1.9 and once as ::81.61.1.9 would never match.
    """
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        return mapped
    if getattr(addr, "version", None) == 6 and int(addr) >> 32 == 0 and int(addr) > 1:
        return ipaddress.ip_address(int(addr) & 0xFFFFFFFF)
    return addr


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
    out.sort(key=lambda g: (-g["worker_count"], g["egress_ip"] or ""))

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
    # Identity on the primary key. client_id is a secondary key (NOT NULL in the
    # schema, but backfilled from the display name by an old migration, so it is
    # the weaker identity of the two); `id` is what the row actually is.
    own = (worker.get("id"), worker.get("client_id"))

    def _same(w: dict[str, Any]) -> bool:
        if own == (None, None):
            # No identity to compare on; only object identity can exclude it,
            # and without this a caller's worker becomes its own peer.
            return w is worker
        if own[0] is not None and w.get("id") is not None:
            return w.get("id") == own[0]
        return own[1] is not None and w.get("client_id") == own[1]

    return [w for w in workers or [] if not _same(w) and egress_of(w) == ip]


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
    """Slugs a worker reports as running, from Docker containers AND Android apps."""
    if not worker:
        return set()
    containers = worker.get("containers")
    if not isinstance(containers, list):
        containers = []
    found = {
        container_slug(c) for c in containers if isinstance(c, dict) and str(c.get("status", "")).lower() == "running"
    }
    # Android workers report `apps` with a boolean `running` instead of Docker
    # containers. A phone on the home WiFi plus a server is two devices on ONE
    # public IP — the canonical case for this whole feature — so leaving them
    # out would blind it to the very conflict it exists to catch.
    apps = worker.get("apps")
    if isinstance(apps, list):
        found |= {container_slug(a) for a in apps if isinstance(a, dict) and a.get("running")}
    return found - {""}


def advertised_host(value: Any) -> str | None:
    """The host part of an advertised dial-back address ("host:port" or "host").

    Returns None when there is nothing usable — empty, whitespace, or a bare
    port. A ``[v6]:port`` bracket form yields the address inside the brackets.
    None is "no claim", never "checked and fine".
    """
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("["):
        host = text[1:].split("]", 1)[0].strip()
        return host or None
    head, sep, tail = text.rpartition(":")
    if sep and head and tail.isdigit() and ":" not in head:
        # Exactly one colon with digits after it is host:port. A digit tail
        # after MORE colons is a bare IPv6 address, which stays whole.
        return head
    return text


def advertised_address_verdict(
    advertised: Any,
    egress_ip: str | None,
    resolved_ips: set[str] | None,
) -> str | None:
    """Reason string when the network appears to be dialling an address this
    machine does not have. None is NO CLAIM — undetected egress, unparseable
    input, or resolution unavailable — never a verdict of "fine".

    ``resolved_ips`` follows the three-valued rule for a HOSTNAME:
      - None       resolution was not attempted or failed transiently: no claim;
      - empty set  the name definitively does not resolve: that IS a finding;
      - non-empty  the addresses the name currently points at.
    For an IP-literal host the verdict needs no resolution at all.

    The comparison assumes the service's inbound port rides the same WAN as
    the machine's default egress — true for every single-WAN host. An operator
    who deliberately forwards through a second WAN gets a warning they can
    read and dismiss; the message says which assumption produced it.
    """
    host = advertised_host(advertised)
    if not host or egress_ip is None:
        return None

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if literal is not None:
        if public_ip(host) is None:
            return (
                f"This service advertises {host}, a private address the network cannot dial back. "
                "Set the advertised address to your public DDNS hostname (preferred) or public IP."
            )
        if public_ip(host) != egress_ip:
            return (
                f"This service advertises {host}, but this machine's current public IP is {egress_ip} — "
                "the network is dialling an address this machine no longer has (a silent ISP re-provision "
                "does exactly this). Update the advertised address, and prefer a DDNS hostname so the next "
                "IP change heals itself. If you deliberately forward this service through a different WAN "
                "than this machine's default egress, this comparison does not apply."
            )
        return None

    if resolved_ips is None:
        return None
    if not resolved_ips:
        return (
            f"This service advertises the hostname {host}, which does not resolve at all — "
            "the network cannot even look it up. Check the DNS record (did the DDNS updater stop?)."
        )
    if egress_ip not in resolved_ips:
        shown = ", ".join(sorted(resolved_ips)[:3])
        return (
            f"This service advertises {host}, which resolves to {shown}, but this machine's current "
            f"public IP is {egress_ip} — the network is dialling an address this machine does not have. "
            "If the IP just changed, a DDNS updater may simply be lagging; if this persists, fix the "
            "record. If you deliberately forward this service through a different WAN than this "
            "machine's default egress, this comparison does not apply."
        )
    return None
