"""Earners fenced off the LAN by default.

Docker's default bridge lets every container reach the LAN, the host, a
tailnet and cloud metadata. Until now the fix was a recipe the operator ran by
hand (docs/home-network-security.md), so a new install was exposed until
someone read it. This module makes the fence the default.

The mechanism, in full:

* The worker creates its own bridge network, ``cashpilot-isolated`` (interface
  ``cp-isolated``), with Docker's masquerade OFF and inter-container traffic
  off, and labels it ``cashpilot.isolation=managed``.
* It writes one nftables table of its own, ``table ip cashpilot``, into the
  host's network namespace, through a one-shot helper container started from
  its own image (host networking, NET_ADMIN). The table holds the masquerade
  that gives the earners their internet, plus drops for private ranges and for
  the host itself.

Because the masquerade lives in the same table as the drops, a missing table
means the earners are offline rather than on the LAN: with no NAT a TCP
connection from the bridge gets no answer from the internet or the LAN. A
reboot, ``nft flush ruleset`` or a firewalld reload therefore fails closed
until the worker writes the table again (at startup, before every deploy,
every 300 s), with three conditions docs/isolation.md spells out: the host
itself stays reachable while the table is missing, a masquerade of the host's
own that covers the subnet NATs the earners anyway, and one-way UDP still
leaves.

Modes (the state lives in Docker and in the worker's /data, so losing either
one alone changes nothing):

* ``operator``: CASHPILOT_CONTAINER_NETWORK is set. That network is used as
  before and nothing on the host is touched, except the masquerade alone
  while earners are still on our network, as in ``off``.
* ``off``: CASHPILOT_ISOLATION=off. Docker's default bridge, as before. If our
  network still exists, the table keeps only its masquerade, so earners still
  on it keep their internet until they are redeployed.
* ``on``: CASHPILOT_ISOLATION=on, or /data/.isolation_on exists (written the
  first time the worker resolves to ``on``), or our labeled network exists, or
  a managed earner is still bound to it after it was removed (Unraid's
  reboot), or no managed earner sits on the default bridge (a fresh install).
  ``off`` deletes the file.
* ``legacy``: an upgraded install whose earners are on the default bridge.
  Nothing changes until the owner turns isolation on from the fleet page.
* ``unsupported``: a Podman engine, with the setting not ``off``. Podman's
  Docker-compatible API keeps the interface name out of the network's options
  and drops the masquerade and inter-container options, and netavark adds its
  own masquerade, so none of what the fence relies on can be set or checked
  there. Earners deploy on the default network and the fleet page says they
  are not fenced; with CASHPILOT_ISOLATION=on, deploys are refused, since on
  was asked for and cannot be given.

The top of this module is stdlib only: the helper container imports it to
render the rules, and the UI image imports its constants.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

NETWORK_NAME = "cashpilot-isolated"
#: Linux caps interface names at 15 characters, so the network's own name
#: cannot double as the interface name.
BRIDGE_INTERFACE = "cp-isolated"
TABLE = "cashpilot"
#: Marks the network as ours. Its presence is what keeps a worker in ``on``
#: mode across restarts and reinstalls.
NETWORK_LABEL = "cashpilot.isolation"
NETWORK_LABEL_VALUE = "managed"

MODE_OPERATOR = "operator"
MODE_OFF = "off"
MODE_ON = "on"
MODE_LEGACY = "legacy"
MODE_UNSUPPORTED = "unsupported"

PODMAN_UNSUPPORTED = (
    "CashPilot cannot fence earners off the LAN on Podman yet: its Docker-compatible API does not keep "
    "the network settings the fence relies on"
)

#: Seconds between checks that the table is still in place.
RECHECK_SECONDS = 300
#: Seconds between the guard's checks while a fence-gated service (one that
#: holds NET_ADMIN in its own namespace, Mysterium) is deployed on this worker.
GUARD_SECONDS = 30

#: (rule name, destination, sentinel address the isolation check connects to).
#: A sentinel is an address nobody uses, so the only evidence a connect to it
#: was blocked by this fence is the rule's own packet counter.
BLOCKED = (
    ("rfc1918-10", "10.0.0.0/8", "10.255.255.254"),
    ("rfc1918-172", "172.16.0.0/12", "172.31.255.254"),
    ("rfc1918-192", "192.168.0.0/16", "192.168.255.254"),
    # CGNAT, which is also where Tailscale puts every tailnet address.
    ("cgnat", "100.64.0.0/10", "100.127.255.254"),
    # Cloud metadata lives here; on a VPS it can mint credentials.
    ("link-local", "169.254.0.0/16", "169.254.169.254"),
)
#: The rule that drops everything from the bridge to the host itself.
HOST_RULE = "host"
MASQ_RULE = "masquerade"
#: The home's own public IP, so NAT loopback on the router cannot bring an
#: earner back into the LAN.
EGRESS_PREFIX = "egress-"
#: Every IPv6 packet from the bridge, forwarded or to the host.
IPV6_FWD_RULE = "ipv6-forward"
IPV6_HOST_RULE = "ipv6-host"
#: Replies to connections that started outside the bridge (a published port,
#: the host talking to an earner). Matched by conntrack direction, so a
#: connection an earner opened while the table was missing gets no pass when
#: the table comes back: its next packet meets the drops like any other.
FWD_EST_RULE = "forward-reply"
IN_EST_RULE = "input-reply"

#: Interfaces whose subnets are Docker's, ours or an overlay's, never the LAN.
_VIRTUAL_PREFIXES = ("docker", "br-", "veth", "cp-", "lo", "tailscale", "myst", "wg", "tun", "virbr")

#: The helper container's name and the label every probe of ours carries.
HELPER_NAME = "cashpilot-fence"
PROBE_LABEL = "cashpilot.probe"
HELPER_TIMEOUT = 20
#: Read in the host's namespace by the helper. Constants so tests can point them at fixtures.
PROC_IPV6 = "/proc/sys/net/ipv6"
PROC_IF_INET6 = "/proc/net/if_inet6"
PROC_ROUTE = "/proc/net/route"

_SETTING = os.getenv("CASHPILOT_ISOLATION", "auto").strip().lower() or "auto"
#: Written in the worker's /data once it resolves to ``on``. Docker's evidence
#: (our network, an earner bound to it) is gone when every fenced earner was
#: removed and the network went with a reboot or a prune; without this file the
#: stopped default-bridge earners left over would read as an upgraded install.
ON_MARKER = Path(os.getenv("CASHPILOT_DATA_DIR", "/data")) / ".isolation_on"
#: Test-only: force the iptables-legacy backend on a host that has nftables.
_BACKEND = os.getenv("CASHPILOT_FENCE_BACKEND", "auto").strip().lower() or "auto"


# ---------------------------------------------------------------------------
# The rules (pure functions; the helper runs these)
# ---------------------------------------------------------------------------


def connected_subnets(route_text: str) -> list[str]:
    """Subnets directly connected to a real interface, outside the blocked ranges.

    Covers a LAN numbered in public space and a VPS's neighbours on its
    provider's segment. Read from ``/proc/net/route`` of the host namespace.
    """
    found: list[str] = []
    blocked = [ipaddress.ip_network(cidr) for _n, cidr, _s in BLOCKED]
    for line in route_text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 8:
            continue
        iface, dest, gateway, mask = parts[0], parts[1], parts[2], parts[7]
        if iface.startswith(_VIRTUAL_PREFIXES) or gateway != "00000000" or dest == "00000000":
            continue
        try:
            net = ipaddress.ip_network(
                f"{_le_ip(dest)}/{_le_ip(mask)}",
                strict=False,
            )
        except ValueError:
            continue
        if net.prefixlen < 8 or net.is_loopback or any(net.subnet_of(b) for b in blocked):
            continue
        if str(net) not in found:
            found.append(str(net))
    return sorted(found)


def _le_ip(hexval: str) -> str:
    """An address as /proc/net/route prints it (little-endian hex)."""
    value = int(hexval, 16)
    return ".".join(str((value >> shift) & 0xFF) for shift in (0, 8, 16, 24))


def _connected_rule(cidr: str) -> str:
    return f"connected-{cidr}"


def masq_rule(subnet: str) -> str:
    """The masquerade's name carries its subnet.

    The helper rewrites the table only when a name it expects is missing, so a
    network recreated with a new subnet must change a name, or the old
    masquerade stays and the earners lose their internet.
    """
    return f"{MASQ_RULE}-{subnet}"


def egress_rule(ip: str) -> str:
    return f"{EGRESS_PREFIX}{ip}"


def egress_target(value: Any) -> str | None:
    """The home's own public IPv4, or None. Dropped so NAT loopback cannot bring an earner back in.

    A connection to that address leaves as internet traffic and most home
    routers loop it straight back into the LAN, with a LAN source address.
    """
    try:
        addr = ipaddress.ip_address(str(value or "").strip())
    except ValueError:
        return None
    if addr.version != 4 or not addr.is_global or addr.is_multicast:
        return None
    return str(addr)


def rule_names(
    subnet: str,
    extra_subnets: list[str] | tuple[str, ...] = (),
    filtered: bool = True,
    egress: str | None = None,
    ipv6: bool = False,
) -> set[str]:
    """The comment of every rule the tables should hold. Each rule has its own."""
    names = {masq_rule(subnet)}
    if filtered:
        names |= {FWD_EST_RULE, IN_EST_RULE, HOST_RULE}
        names |= {name for name, _c, _s in BLOCKED}
        names |= {_connected_rule(c) for c in extra_subnets}
        if egress:
            names.add(egress_rule(egress))
        if ipv6:
            names |= {IPV6_FWD_RULE, IPV6_HOST_RULE}
    return names


def render_nft(
    iface: str,
    subnet: str,
    extra_subnets: list[str] | tuple[str, ...] = (),
    filtered: bool = True,
    egress: str | None = None,
    ipv6: bool = False,
) -> str:
    """The whole table, replaced atomically by one ``nft -f -``.

    Priority -150 runs before Docker's and Tailscale's filter chains, so the
    drops hold whatever order those are in. An ``accept`` here ends only this
    chain; a ``drop`` is final. ``filtered=False`` keeps only the masquerade:
    the way back out, where earners still on the bridge keep their internet.

    ``ipv6`` adds ``table ip6 cashpilot``, which drops every IPv6 packet that
    enters from the bridge. The network has IPv6 off, but Docker engines before
    26 still give each container an fe80:: address, and over it an earner
    reaches any host service listening on [::].
    """
    ipaddress.ip_network(subnet)
    q = json.dumps(iface)
    lines = [
        f"table ip {TABLE}",
        f"delete table ip {TABLE}",
    ]
    if ipv6:
        lines += [f"table ip6 {TABLE}", f"delete table ip6 {TABLE}"]
    lines += [
        f"table ip {TABLE} {{",
        "  chain postrouting {",
        "    type nat hook postrouting priority srcnat; policy accept;",
        f'    ip saddr {subnet} oifname != {q} counter masquerade comment "{masq_rule(subnet)}"',
        "  }",
    ]
    if filtered:
        lines += [
            "  chain forward {",
            "    type filter hook forward priority -150; policy accept;",
            f'    iifname {q} ct state established,related ct direction reply counter accept comment "{FWD_EST_RULE}"',
        ]
        for name, cidr, _s in BLOCKED:
            lines.append(f'    iifname {q} ip daddr {cidr} counter drop comment "{name}"')
        for cidr in extra_subnets:
            ipaddress.ip_network(cidr)
            lines.append(f'    iifname {q} ip daddr {cidr} counter drop comment "{_connected_rule(cidr)}"')
        if egress:
            ip = str(ipaddress.IPv4Address(egress))
            lines.append(f'    iifname {q} ip daddr {ip} counter drop comment "{egress_rule(ip)}"')
        lines += [
            "  }",
            "  chain input {",
            "    type filter hook input priority -150; policy accept;",
            f'    iifname {q} ct state established,related ct direction reply counter accept comment "{IN_EST_RULE}"',
            f'    iifname {q} counter drop comment "{HOST_RULE}"',
            "  }",
        ]
    lines.append("}")
    if filtered and ipv6:
        lines += [
            f"table ip6 {TABLE} {{",
            "  chain forward {",
            "    type filter hook forward priority -150; policy accept;",
            f'    iifname {q} counter drop comment "{IPV6_FWD_RULE}"',
            "  }",
            "  chain input {",
            "    type filter hook input priority -150; policy accept;",
            f'    iifname {q} counter drop comment "{IPV6_HOST_RULE}"',
            "  }",
            "}",
        ]
    return "\n".join(lines) + "\n"


def render_iptables(
    iface: str,
    subnet: str,
    extra_subnets: list[str] | tuple[str, ...] = (),
    filtered: bool = True,
    egress: str | None = None,
    ipv6: bool = False,
) -> str:
    """The same fence for kernels without nf_tables, as an idempotent sh script.

    Mangle chains (the slot that holds against Tailscale's ts-forward, see
    docs/isolation-check.md) and a nat chain for the masquerade. Each chain is
    flushed and rebuilt, and each jump is added only if missing.
    """
    ipaddress.ip_network(subnet)
    out = ["set -e"]

    def chain(ipt: str, table: str, name: str, hook: str, match: str) -> None:
        out.append(f"{ipt} -t {table} -N {name} 2>/dev/null || true")
        out.append(f"{ipt} -t {table} -F {name}")
        out.append(
            f"{ipt} -t {table} -C {hook} {match} -j {name} 2>/dev/null || {ipt} -t {table} -I {hook} 1 {match} -j {name}"
        )

    def comment(name: str) -> str:
        return f"-m comment --comment {name}"

    ipt = "iptables-legacy -w"
    chain(ipt, "nat", "CP-POST", "POSTROUTING", f"-s {subnet}")
    out.append(f"{ipt} -t nat -A CP-POST ! -o {iface} {comment(masq_rule(subnet))} -j MASQUERADE")
    chain(ipt, "mangle", "CP-FWD", "FORWARD", f"-i {iface}")
    chain(ipt, "mangle", "CP-IN", "INPUT", f"-i {iface}")
    if filtered:
        est = "-m conntrack --ctstate ESTABLISHED,RELATED --ctdir REPLY"
        out.append(f"{ipt} -t mangle -A CP-FWD {est} {comment(FWD_EST_RULE)} -j RETURN")
        for name, cidr, _s in BLOCKED:
            out.append(f"{ipt} -t mangle -A CP-FWD -d {cidr} {comment(name)} -j DROP")
        for cidr in extra_subnets:
            ipaddress.ip_network(cidr)
            out.append(f"{ipt} -t mangle -A CP-FWD -d {cidr} {comment(_connected_rule(cidr))} -j DROP")
        if egress:
            ip = str(ipaddress.IPv4Address(egress))
            out.append(f"{ipt} -t mangle -A CP-FWD -d {ip}/32 {comment(egress_rule(ip))} -j DROP")
        out.append(f"{ipt} -t mangle -A CP-IN {est} {comment(IN_EST_RULE)} -j RETURN")
        out.append(f"{ipt} -t mangle -A CP-IN {comment(HOST_RULE)} -j DROP")
    if ipv6:
        ip6t = "ip6tables-legacy -w"
        chain(ip6t, "mangle", "CP6-FWD", "FORWARD", f"-i {iface}")
        chain(ip6t, "mangle", "CP6-IN", "INPUT", f"-i {iface}")
        if filtered:
            out.append(f"{ip6t} -t mangle -A CP6-FWD {comment(IPV6_FWD_RULE)} -j DROP")
            out.append(f"{ip6t} -t mangle -A CP6-IN {comment(IPV6_HOST_RULE)} -j DROP")
    return "\n".join(out) + "\n"


_NFT_RULE = re.compile(r'counter packets (\d+) bytes \d+ .*?comment "([^"]+)"')
_IPT_RULE = re.compile(r"^\s*(\d+)\s+\d+\s+.*?/\* (\S+) \*/")


def parse_nft_counters(listing: str) -> dict[str, int]:
    """Packets per rule name from ``nft list table ip cashpilot``."""
    return {m.group(2): int(m.group(1)) for m in _NFT_RULE.finditer(listing)}


def parse_iptables_counters(listing: str) -> dict[str, int]:
    """Packets per rule name from ``iptables -L <chain> -v -x -n``."""
    found = {}
    for line in listing.splitlines():
        m = _IPT_RULE.match(line)
        if m:
            found[m.group(2)] = int(m.group(1))
    return found


#: Runs inside the helper container (host networking, NET_ADMIN, root,
#: read-only root filesystem). Prints one JSON object.
HELPER_SCRIPT = r"""
import json, os, socket, subprocess, sys
from app import lan_fence as f

def sh(argv, data=None):
    try:
        r = subprocess.run(argv, input=data, capture_output=True, text=True, timeout=10)
        return r.returncode, r.stdout, r.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)

def backend(want):
    if want in ("nft", "legacy"):
        return want
    return "nft" if sh(["nft", "list", "tables"])[0] == 0 else "legacy"

def local(ip):
    # On a VPS the public IP sits on the host itself: the input drop covers it.
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind((ip, 0))
        return True
    except OSError:
        return False
    finally:
        s.close()

def bridge_ipv6(iface):
    # The bridge's own link-local address, the one an earner would reach the host on.
    try:
        with open(os.environ.get("FENCE_PROC_IF_INET6") or f.PROC_IF_INET6) as fh:
            for line in fh:
                p = line.split()
                if len(p) == 6 and p[5] == iface and p[0].startswith("fe80"):
                    return str(__import__("ipaddress").IPv6Address(bytes.fromhex(p[0])))
    except OSError:
        pass
    return None

def read(b, ipv6):
    if b == "nft":
        rc, out, _ = sh(["nft", "list", "table", "ip", f.TABLE])
        counters = f.parse_nft_counters(out) if rc == 0 else {}
        if ipv6:
            rc6, out6, _ = sh(["nft", "list", "table", "ip6", f.TABLE])
            if rc6 == 0:
                counters.update(f.parse_nft_counters(out6))
        return counters, rc == 0
    counters, present = {}, False
    chains = [
        ("iptables-legacy", "nat", "CP-POST", "POSTROUTING", ["-s", subnet]),
        ("iptables-legacy", "mangle", "CP-FWD", "FORWARD", ["-i", iface]),
        ("iptables-legacy", "mangle", "CP-IN", "INPUT", ["-i", iface]),
    ]
    if ipv6:
        chains += [
            ("ip6tables-legacy", "mangle", "CP6-FWD", "FORWARD", ["-i", iface]),
            ("ip6tables-legacy", "mangle", "CP6-IN", "INPUT", ["-i", iface]),
        ]
    for tool, table, chain, hook, match in chains:
        rc, out, _ = sh([tool, "-w", "-t", table, "-L", chain, "-v", "-x", "-n"])
        if rc != 0:
            continue
        present = present or tool == "iptables-legacy"
        # A firewall script that flushes FORWARD or INPUT keeps our chain but
        # drops the jump into it. Its rules then count for nothing, so they are
        # left out and the apply writes the jump back.
        if sh([tool, "-w", "-t", table, "-C", hook] + match + ["-j", chain])[0] == 0:
            counters.update(f.parse_iptables_counters(out))
    return counters, present

action = sys.argv[1]
iface = os.environ["FENCE_IFACE"]
subnet = os.environ["FENCE_SUBNET"]
filtered = os.environ.get("FENCE_FILTER", "1") == "1"
egress = f.egress_target(os.environ.get("FENCE_EGRESS"))
if egress and local(egress):
    egress = None
# A kernel booted with ipv6.disable=1 has no IPv6 at all, and no ip6 hooks to load.
ipv6 = os.path.isdir(os.environ.get("FENCE_PROC_IPV6") or f.PROC_IPV6)
route_error = ""
try:
    with open(os.environ.get("FENCE_PROC_ROUTE") or f.PROC_ROUTE) as fh:
        extras = f.connected_subnets(fh.read())
except OSError as exc:
    # Without the routes a LAN numbered in public space would lose its drop, so
    # the table is left as it is rather than rewritten without it.
    extras, route_error = [], "could not read the host's routes (%s)" % exc
b = backend(os.environ.get("FENCE_BACKEND", "auto"))
counters, present = read(b, ipv6)
if not egress:
    # The worker does not know its public IP yet (a lookup failed, or it just
    # started): keep the drop the table already has rather than lose it.
    kept = [n[len(f.EGRESS_PREFIX):] for n in counters if n.startswith(f.EGRESS_PREFIX)]
    egress = f.egress_target(kept[0]) if len(kept) == 1 else None
expected = f.rule_names(subnet, extras, filtered, egress, ipv6)
out = {"backend": b, "ok": True, "changed": False, "error": "", "extra_subnets": extras, "egress": egress, "ipv6": ipv6}
if action == "apply" and filtered and route_error:
    out["ok"] = False
    out["error"] = route_error + "; the table was not changed"
elif action == "apply" and set(counters) != expected:
    if b == "nft":
        rc, _o, err = sh(["nft", "-f", "-"], f.render_nft(iface, subnet, extras, filtered, egress, ipv6))
    else:
        rc, _o, err = sh(["sh", "-c", f.render_iptables(iface, subnet, extras, filtered, egress, ipv6)])
    out["changed"] = True
    if rc != 0:
        out["ok"] = False
        out["error"] = (err or "exit status %d" % rc)[:400]
    counters, present = read(b, ipv6)
out["present"] = present
out["counters"] = counters
out["matches"] = set(counters) == expected
out["bridge_ipv6"] = bridge_ipv6(iface) if ipv6 else None
if action == "apply" and out["ok"] and not out["matches"]:
    out["ok"] = False
    out["error"] = out["error"] or "the table was written but does not hold the expected rules"
print(json.dumps(out))
"""


# ---------------------------------------------------------------------------
# Docker side (worker only; Docker is imported lazily)
# ---------------------------------------------------------------------------


class IsolationConflict(RuntimeError):
    """A network named like ours exists that we did not create and that is in use."""


_lock = threading.Lock()
_state: dict[str, Any] = {
    "mode": None,
    "network": None,
    "fence": {"state": "n/a", "backend": None, "error": "", "applied_at": None},
    "earners_outside": [],
    "earners_outside_stopped": [],
    # Fence-gated containers the guard holds stopped, by name, with the reason.
    "guard": {},
    "unfenced": [],
}
#: The worker's public egress IP, set from the heartbeat's detection
#: (app/worker_api.py). The next apply adds its drop.
_egress: dict[str, str | None] = {"ip": None}


def set_egress_ip(value: Any) -> bool:
    """Remember the home's public IP for the next apply.

    A failed lookup (None, or a non-public answer) keeps the last address: not
    knowing the IP is no reason to stop dropping it. Returns True when a new
    public address arrived, so the caller can apply at once.
    """
    new = egress_target(value)
    if new is None or new == _egress["ip"]:
        return False
    _egress["ip"] = new
    return True


def setting() -> str:
    return _SETTING if _SETTING in ("auto", "on", "off") else "auto"


def _orchestrator():
    from app import orchestrator

    return orchestrator


def managed_network(client: Any) -> Any | None:
    """Our labeled network, or None."""
    try:
        nets = client.networks.list(filters={"label": f"{NETWORK_LABEL}={NETWORK_LABEL_VALUE}"})
    except Exception:  # noqa: BLE001 - treated as absent; the deploy path reports Docker errors
        return None
    for net in nets or []:
        if getattr(net, "name", None) == NETWORK_NAME:
            return client.networks.get(net.id)
    return None


def _on_default_bridge(container: Any) -> bool:
    attrs = getattr(container, "attrs", None) or {}
    mode = str((attrs.get("HostConfig") or {}).get("NetworkMode") or "")
    nets = set(((attrs.get("NetworkSettings") or {}).get("Networks") or {}).keys())
    return mode in ("bridge", "default") or "bridge" in nets


def _managed(client: Any) -> list[Any]:
    from app.constants import LABEL_MANAGED

    return client.containers.list(all=True, filters={"label": f"{LABEL_MANAGED}=true"})


def default_bridge_earners(client: Any) -> list[Any]:
    """Managed containers on Docker's default bridge: the exposed ones."""
    return [c for c in _managed(client) if _on_default_bridge(c)]


def _bound_to_removed_network(client: Any) -> bool:
    """A managed container still names our network after it was removed.

    Unraid removes user-defined networks when Docker starts. Each earner keeps
    its endpoint by name with the old ID, so this is the proof isolation was
    on when the network itself is gone. A network by our name that someone
    else created is not removed, so it never counts here.
    """
    from docker.errors import NotFound

    try:
        client.networks.get(NETWORK_NAME)
        return False
    except NotFound:
        pass
    except Exception:  # noqa: BLE001 - treated as absent; the deploy path reports Docker errors
        return False
    try:
        earners = _managed(client)
    except Exception:  # noqa: BLE001 - same
        return False
    return any(NETWORK_NAME in (((c.attrs or {}).get("NetworkSettings") or {}).get("Networks") or {}) for c in earners)


def _remembered_on() -> bool:
    try:
        return ON_MARKER.is_file()
    except OSError:
        return False


def _remember(on: bool) -> None:
    """Record in /data whether isolation is on. Best effort: Docker's own evidence still counts."""
    try:
        if on and not ON_MARKER.is_file():
            ON_MARKER.parent.mkdir(parents=True, exist_ok=True)
            ON_MARKER.write_text("on\n")
        elif not on:
            ON_MARKER.unlink(missing_ok=True)
    except OSError as exc:
        if on:
            logger.warning(
                "Could not record isolation on in %s (%s). Make /data writable: until then, losing the %s network "
                "with only stopped default-bridge earners left would put this worker back in legacy mode.",
                ON_MARKER,
                exc,
                NETWORK_NAME,
            )
        else:
            logger.warning(
                "Could not delete %s (%s). Delete it by hand, or this worker comes back isolated once "
                "CASHPILOT_ISOLATION=off is removed.",
                ON_MARKER,
                exc,
            )


def is_podman(client: Any) -> bool:
    """A Podman engine behind the Docker-compatible API.

    Podman names itself in /version ("Podman Engine"). An engine that does not
    answer cannot be told apart, and a Podman taken for Docker gets a network
    whose bridge is not the one the fence's rules name, so this raises
    RuntimeError instead of guessing: isolation fails closed.
    """
    try:
        version = client.version() or {}
    except Exception as exc:  # noqa: BLE001 - re-raised as the documented RuntimeError
        raise RuntimeError(
            f"Could not read the container engine's /version ({exc}), so it cannot tell Docker from Podman "
            "and the LAN fence was not applied."
        ) from exc
    names = [str((version.get("Platform") or {}).get("Name") or "")]
    names += [str((c or {}).get("Name") or "") for c in version.get("Components") or []]
    return any("podman" in n.lower() for n in names)


def resolve_mode(client: Any) -> str:
    if _orchestrator()._CONTAINER_NETWORK:
        return MODE_OPERATOR
    chosen = setting()
    if chosen == "off":
        _remember(False)
        return MODE_OFF
    if is_podman(client):
        return MODE_UNSUPPORTED
    if (
        chosen == "on"
        or _remembered_on()
        or managed_network(client) is not None
        or _bound_to_removed_network(client)
        or not default_bridge_earners(client)
    ):
        _remember(True)
        return MODE_ON
    return MODE_LEGACY


def ensure_network(client: Any) -> Any:
    """Our network, created when missing. Raises IsolationConflict."""
    from docker.errors import NotFound

    net = managed_network(client)
    if net is not None:
        _check_managed(net)
        return net
    try:
        other = client.networks.get(NETWORK_NAME)
    except NotFound:
        other = None
    if other is not None and getattr(other, "name", NETWORK_NAME) == NETWORK_NAME:
        if (other.attrs or {}).get("Containers"):
            raise IsolationConflict(
                f"A network named {NETWORK_NAME} already exists, CashPilot did not create it, and containers use "
                f"it. Either set CASHPILOT_CONTAINER_NETWORK={NETWORK_NAME} to keep managing it and its firewall "
                "rules yourself, or remove it so CashPilot can create its own."
            )
        other.remove()
    logger.info("Creating the isolated network %s (interface %s)", NETWORK_NAME, BRIDGE_INTERFACE)
    return client.networks.create(
        NETWORK_NAME,
        driver="bridge",
        options={
            "com.docker.network.bridge.name": BRIDGE_INTERFACE,
            # The fence's own table does the NAT, so no table means no internet.
            "com.docker.network.bridge.enable_ip_masquerade": "false",
            "com.docker.network.bridge.enable_icc": "false",
        },
        labels={NETWORK_LABEL: NETWORK_LABEL_VALUE},
        enable_ipv6=False,
    )


#: The options the fence depends on: its rules match the interface by name,
#: and Docker's own masquerade or inter-container traffic would bypass them.
_REQUIRED_OPTIONS = {
    "com.docker.network.bridge.name": BRIDGE_INTERFACE,
    "com.docker.network.bridge.enable_ip_masquerade": "false",
    "com.docker.network.bridge.enable_icc": "false",
}


def _check_managed(net: Any) -> None:
    """Refuse a labeled network whose settings the fence cannot hold. Raises IsolationConflict."""
    attrs = net.attrs or {}
    options = attrs.get("Options") or {}
    wrong = [k for k, v in _REQUIRED_OPTIONS.items() if str(options.get(k, "")).lower() != v]
    if attrs.get("Driver", "bridge") != "bridge" or wrong:
        raise IsolationConflict(
            f"The {NETWORK_NAME} network carries CashPilot's label but not the settings its fence needs "
            f"({', '.join(wrong) or 'driver ' + str(attrs.get('Driver'))}). Remove it, or move its containers "
            "off it, so CashPilot can create it again."
        )


def _stale_endpoint(container: Any, net: Any) -> bool:
    """A stopped earner still bound to an earlier network of ours, by its ID."""
    nets = ((container.attrs or {}).get("NetworkSettings") or {}).get("Networks") or {}
    old = (nets.get(NETWORK_NAME) or {}).get("NetworkID") or ""
    return bool(old) and old != net.id


def reattach(client: Any, net: Any) -> list[str]:
    """Bind earners left on a removed copy of our network to the current one.

    Docker keeps a container's network by ID. Unraid removes every user-defined
    network when its Docker service starts, unless "Preserve user defined
    networks" is on, so after a reboot each earner fails to start with
    "network <id> not found" and stays down even once the worker has created
    the network again. Each such earner is disconnected from the old network
    by name, connected to the new one and, when the missing network is what
    stopped it, started. One an owner stopped is moved and left stopped.
    Never raises; returns the names it moved.
    """
    moved = []
    try:
        earners = _managed(client)
    except Exception:  # noqa: BLE001 - the deploy path reports Docker errors
        return moved
    for c in earners:
        if c.status == "running" or not _stale_endpoint(c, net):
            continue
        error = str(((c.attrs or {}).get("State") or {}).get("Error") or "")
        try:
            net.disconnect(c, force=True)
            net.connect(c)
            # A fence-gated one is started by the guard alone, after all its checks.
            if "network" in error and "not found" in error and not _is_gated(c):
                c.start()
            moved.append(c.name)
        except Exception as exc:  # noqa: BLE001 - logged; the next check tries again
            logger.warning("Could not move %s onto the recreated %s network: %s", c.name, NETWORK_NAME, exc)
    if moved:
        logger.info("Reattached %s to the recreated %s network", ", ".join(moved), NETWORK_NAME)
    return moved


def _is_gated(container: Any) -> bool:
    from app.constants import LABEL_SERVICE

    slug = str((getattr(container, "labels", None) or {}).get(LABEL_SERVICE) or "")
    return _orchestrator()._gated_container(slug, container)


def _subnet(net: Any) -> str:
    for conf in ((net.attrs or {}).get("IPAM") or {}).get("Config") or []:
        subnet = conf.get("Subnet") or ""
        with contextlib.suppress(ValueError):
            if ipaddress.ip_network(subnet).version == 4:
                return subnet
    raise RuntimeError(f"The {NETWORK_NAME} network has no IPv4 subnet.")


def _gateway(net: Any) -> str | None:
    for conf in ((net.attrs or {}).get("IPAM") or {}).get("Config") or []:
        if conf.get("Gateway") and ":" not in conf["Gateway"]:
            return conf["Gateway"]
    return None


def _helper_image(client: Any) -> str:
    me = _orchestrator()._self_container(client)
    image = ((me.attrs or {}).get("Image") or None) if me is not None else None
    if image:
        return image
    from app import version

    return f"drumsergio/cashpilot-worker:{version.current()}"


#: How long a helper that was just created or has just exited still belongs to
#: the process that started it: that process starts it, then reads its logs and
#: removes it, all within moments. HELPER_POLL is how often a busy helper is
#: looked at again.
HELPER_GRACE = 10.0
HELPER_POLL = 0.25


def _stamp_age(stamp: Any, now: float) -> float | None:
    """Seconds since a Docker timestamp, or None when it is unset or unreadable."""
    try:
        when = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    if when.tzinfo is None or when.year < 2000:
        return None
    return now - when.timestamp()


def _helper_busy(attrs: dict[str, Any], now: float) -> bool:
    """A helper another process is still using: running, or created or exited within HELPER_GRACE."""
    state = attrs.get("State") or {}
    if state.get("Running") or state.get("Restarting"):
        return True
    status = state.get("Status")
    if status == "created":
        stamp = attrs.get("Created")
    elif status in ("exited", "dead"):
        stamp = state.get("FinishedAt")
    else:
        return False
    age = _stamp_age(stamp, now)
    return age is not None and age < HELPER_GRACE


def _clear_helper(client: Any) -> None:
    """Make room for this process's helper.

    Only a container that carries the helper's label is touched: a container
    someone else named cashpilot-fence is left alone, and the run that follows
    fails on the name instead of deleting it.

    The Desktop app runs the same helper, by the same name and label, so on a
    host that runs both, a helper of ours can belong to another process that is
    still waiting for its result. That one is waited for, never killed: killing
    it would make the other side record a failed fence and refuse its deploy.
    Only a leftover, one idle past HELPER_GRACE or still there after the helper
    timeout, is removed.
    """
    from docker.errors import NotFound

    # Per helper: one another process created after the last poll gets its own wait.
    waiting_on, deadline = None, 0.0
    while True:
        try:
            found = client.containers.get(HELPER_NAME)
            if (getattr(found, "labels", None) or {}).get(PROBE_LABEL) != "fence":
                return
            if getattr(found, "id", None) != waiting_on:
                waiting_on, deadline = getattr(found, "id", None), time.monotonic() + HELPER_TIMEOUT + HELPER_GRACE
            if not _helper_busy(found.attrs or {}, time.time()) or time.monotonic() > deadline:
                found.remove(force=True, v=True)
                return
        except NotFound:
            return
        except Exception as exc:  # noqa: BLE001 - logged; the run that follows fails on the name
            logger.warning("Could not remove %s: %s", HELPER_NAME, exc)
            return
        time.sleep(HELPER_POLL)


def _remove_own(container: Any) -> None:
    """Remove the helper this process started, by its own ID, never by name."""
    from docker.errors import NotFound

    try:
        container.remove(force=True, v=True)
    except NotFound:
        pass
    except Exception as exc:  # noqa: BLE001 - logged; the next run clears it as a leftover
        logger.warning("Could not remove %s: %s", HELPER_NAME, exc)


def run_helper(client: Any, action: str, subnet: str, filtered: bool = True) -> dict[str, Any]:
    """Run the helper to completion and return what it printed. Removed on every path."""
    from docker.errors import APIError

    with _lock:
        container = None
        try:
            # Twice: another process can create its helper between our clear and our run.
            for attempt in range(2):
                _clear_helper(client)
                try:
                    container = _create_helper(client, action, subnet, filtered)
                    break
                except APIError as exc:
                    if attempt or getattr(exc, "status_code", None) != 409:
                        raise
            # Created and started apart, so a start that fails still leaves an
            # ID to remove: nothing is ever removed by name after the create.
            container.start()
            status = container.wait(timeout=HELPER_TIMEOUT)
            text = container.logs(stdout=True, stderr=False).decode(errors="replace").strip()
            if (status or {}).get("StatusCode") != 0:
                err = container.logs(stdout=False, stderr=True).decode(errors="replace").strip()
                raise RuntimeError(
                    f"the fence helper exited with status {(status or {}).get('StatusCode')}: {err[-300:]}"
                )
            return json.loads(text.splitlines()[-1])
        finally:
            if container is not None:
                _remove_own(container)


def _create_helper(client: Any, action: str, subnet: str, filtered: bool) -> Any:
    """Create the helper container, not started, pulling its image once if it is missing."""
    from docker.errors import ImageNotFound

    image = _helper_image(client)
    try:
        return client.containers.create(image=image, **_helper_spec(action, subnet, filtered))
    except ImageNotFound:
        client.images.pull(image)
        return client.containers.create(image=image, **_helper_spec(action, subnet, filtered))


def _helper_spec(action: str, subnet: str, filtered: bool) -> dict[str, Any]:
    """The helper's container settings: host networking, NET_ADMIN and NET_RAW, every other capability dropped."""
    return dict(
        name=HELPER_NAME,
        entrypoint=["python", "-c", HELPER_SCRIPT],
        command=[action],
        environment={
            "FENCE_IFACE": BRIDGE_INTERFACE,
            "FENCE_SUBNET": subnet,
            "FENCE_FILTER": "1" if filtered else "0",
            "FENCE_BACKEND": _BACKEND,
            "FENCE_EGRESS": _egress["ip"] or "",
        },
        network_mode="host",
        user="0:0",
        read_only=True,
        # iptables-legacy takes its lock in /run.
        tmpfs={"/run": "size=1m"},
        cap_drop=["ALL"],
        # NET_RAW only matters to iptables-legacy, which talks to the
        # kernel over a raw socket. Both run our own script, never an earner.
        cap_add=["NET_ADMIN", "NET_RAW"],
        security_opt=["no-new-privileges:true"],
        privileged=False,
        pids_limit=64,
        mem_limit="64m",
        healthcheck={"test": ["NONE"]},
        labels={PROBE_LABEL: "fence"},
    )


def _set_fence(state: str, result: dict[str, Any] | None = None, error: str = "") -> None:
    _state["fence"] = {
        "state": state,
        "backend": (result or {}).get("backend"),
        "error": error or (result or {}).get("error") or "",
        "applied_at": time.time() if state == "applied" else _state["fence"].get("applied_at"),
    }


def _off_hint() -> str:
    return (
        "Set CASHPILOT_ISOLATION=off on this worker to deploy on Docker's default bridge instead, "
        "without the fence (docs/isolation.md)."
    )


def apply_fence(client: Any) -> dict[str, Any]:
    """Make sure our network and its full table exist. Raises RuntimeError with the reason."""
    try:
        net = ensure_network(client)
        result = run_helper(client, "apply", _subnet(net), filtered=True)
    except IsolationConflict as exc:
        _set_fence("failed", error=str(exc))
        raise
    except Exception as exc:
        _set_fence("failed", error=str(exc))
        raise RuntimeError(f"The LAN fence could not be applied on this host: {exc}") from exc
    if not result.get("ok"):
        _set_fence("failed", result)
        raise RuntimeError(
            f"The LAN fence could not be applied on this host ({result.get('backend')}): {result.get('error')}"
        )
    if result.get("changed"):
        logger.info(
            "LAN fence applied (%s backend, %d rules)", result.get("backend"), len(result.get("counters") or {})
        )
    _set_fence("applied", result)
    # Only now: an earner left on a removed copy of the network is started by
    # the move, and it must not run before the drops are in place.
    reattach(client, net)
    return result


def read_fence(client: Any) -> dict[str, Any] | None:
    """The table's per-rule counters, or None when our network does not exist.

    Raises IsolationConflict when the network no longer has the settings the
    rules depend on: they match its interface by name, so a copy recreated
    under another interface would read complete and cover nothing.
    """
    net = managed_network(client)
    if net is None:
        return None
    _check_managed(net)
    return run_helper(client, "read", _subnet(net), filtered=True)


def reduce_fence(client: Any) -> dict[str, Any] | None:
    """Keep only the masquerade, so earners left on our network keep internet."""
    net = managed_network(client)
    if net is None:
        return None
    result = run_helper(client, "apply", _subnet(net), filtered=False)
    _set_fence("reduced" if result.get("ok") else "failed", result)
    return result


def network_for_deploy() -> str | None:
    """The network a bridge-networked earner joins when the operator named none.

    None means Docker's default bridge (``off`` and ``legacy``). In ``on`` mode
    the fence is checked first; if it cannot be applied the deploy is refused
    here, before the running container is touched.
    """
    orch = _orchestrator()
    client = orch._get_client()
    try:
        mode = resolve_mode(client)
    except RuntimeError as exc:
        raise orch.ContainerNetworkError(f"{exc} The running container was not touched. {_off_hint()}") from None
    _state["mode"] = mode
    if mode == MODE_UNSUPPORTED and setting() == "on":
        raise orch.ContainerNetworkError(
            f"CASHPILOT_ISOLATION=on, but {PODMAN_UNSUPPORTED}. The running container was not touched. "
            "Set CASHPILOT_ISOLATION=auto or off on this worker to deploy on Podman's default network, "
            "without the fence (docs/isolation.md)."
        )
    if mode != MODE_ON:
        return None
    try:
        apply_fence(client)
    except (RuntimeError, IsolationConflict) as exc:
        raise orch.ContainerNetworkError(f"{exc} The running container was not touched. {_off_hint()}") from None
    _state["network"] = NETWORK_NAME
    return NETWORK_NAME


def move_advice(mode: str | None, service: str = "it", it: str = "it") -> str:
    """The one thing to do to move a fence-gated node off the host's network, in this isolation mode.

    ``on`` and ``operator`` take a redeploy alone (switching isolation on is
    refused in ``operator`` mode); ``legacy`` needs isolation on first, ``off``
    the setting changed, and Podman cannot be fenced at all. ``None`` is a
    worker that reports no mode.
    """
    if mode == MODE_ON:
        return f"Redeploy {service} once to move {it} onto the fenced bridge."
    if mode == MODE_OPERATOR:
        return f"Redeploy {service} once to move {it} onto your own network (CASHPILOT_CONTAINER_NETWORK)."
    if mode == MODE_LEGACY:
        return f"Switch isolation on in Fleet first, then redeploy {service} once to move {it} onto the fenced bridge."
    if mode == MODE_OFF:
        return (
            f"Set CASHPILOT_ISOLATION=auto on this worker and restart it, then redeploy {service} once to move "
            f"{it} onto the fenced bridge."
        )
    if mode == MODE_UNSUPPORTED:
        return (
            f"{PODMAN_UNSUPPORTED}, so {service} cannot be fenced on this worker. Run {it} on Docker, or on your "
            "own network (CASHPILOT_CONTAINER_NETWORK)."
        )
    return (
        f"Redeploy {service} once to move {it} onto the fenced bridge; if isolation is not on for this worker, "
        "switch it on in Fleet first."
    )


def mode_problem(mode: str, service: str = "this service") -> str | None:
    """Why a fence-gated service cannot run in this isolation mode at all, or None.

    Only ``on`` (behind our fence) and ``operator`` (on the operator's own
    network, under their rules) qualify. In ``off``, ``legacy`` and
    ``unsupported`` the node would sit on Docker's default bridge, where every
    other earner reaches its WebUI and nothing keeps it off the LAN.
    ``service`` is the catalog name the message gives.
    """
    if mode in (MODE_ON, MODE_OPERATOR):
        return None
    return f"isolation is {mode} on this worker, and {service} runs only behind the LAN fence. {move_advice(mode, service)}"


def fence_problem(client: Any, service: str = "this service") -> str | None:
    """Why a fence-gated container must not start now, or None.

    In ``on`` mode the table is read back by the helper and every rule it
    should hold must be there, IPv6 drops included. On the operator's own
    network there is no fence of ours to wait for: it carries their rules. Any
    other mode does not run the node at all (mode_problem).
    """
    try:
        mode = resolve_mode(client)
    except RuntimeError as exc:
        return f"the isolation mode could not be read ({exc})"
    if mode != MODE_ON:
        return mode_problem(mode, service)
    try:
        result = read_fence(client)
    except Exception as exc:  # noqa: BLE001 - the reason is the answer
        return f"the LAN fence could not be read ({exc})"
    if result is None:
        return f"the {NETWORK_NAME} network does not exist, so the LAN fence is not in place"
    if not result.get("present") or not result.get("matches"):
        return "the LAN fence is not complete on this host, so the node stays stopped until the worker restores it"
    return None


def _gated(client: Any) -> list[Any]:
    orch = _orchestrator()
    from app.constants import LABEL_SERVICE

    return [
        c
        for c in _managed(client)
        if orch.fence_gated(str((c.labels or {}).get(LABEL_SERVICE) or ""))
        and not orch.is_proxied(c)
        # A node from 2.0.6 or earlier, on the host's network, is left exactly
        # as it is until its owner redeploys it (orchestrator.predates_fence).
        and not orch.predates_fence(c)
    ]


def _unfenced(client: Any) -> list[dict[str, str]]:
    """Fence-gated services' containers still on the host's network (2.0.6 or earlier).

    Left running as they are; the Fleet page offers the redeploy that moves them.
    """
    orch = _orchestrator()
    from app.constants import LABEL_SERVICE

    found = []
    for c in _managed(client):
        slug = str((c.labels or {}).get(LABEL_SERVICE) or "")
        if orch.fence_gated(slug) and orch.predates_fence(c):
            found.append({"name": c.name, "slug": slug, "service": orch.service_name(slug)})
    return found


def guard() -> dict[str, str]:
    """Every GUARD_SECONDS: hold each fence-gated container to the fence. Never raises.

    A fence-gated service has no Docker restart policy, so this is what starts
    it: after a deploy that left it created, after a reboot or a daemon
    restart, after a crash. It starts one only when the fence is confirmed and
    the container's shape is the catalog's, and never one the owner stopped.

    It also stops one within GUARD_SECONDS when either goes: a rule deleted
    from the table, the container recreated on the host network, privileged,
    with a capability or an image the catalog does not give it. The fence is
    then applied again; the next pass starts the container once it reads
    complete. Returns the containers held stopped, with the reason.
    """
    orch = _orchestrator()
    held: dict[str, str] = {}
    scanned = False
    try:
        if not orch.docker_available():
            _state["unfenced"] = []
            return {}
        client = orch._get_client()
        _state["unfenced"] = _unfenced(client)
        scanned = True
        gated = _gated(client)
        if not gated:
            _state["guard"] = {}
            return {}
        # A deploy replacing a gated container holds this lock: the pass then
        # only stops (orchestrator.GATED_DEPLOY_LOCK says why).
        deploying = not orch.GATED_DEPLOY_LOCK.acquire(blocking=False)
        try:
            try:
                mode: str | None = resolve_mode(client)
                fence = fence_problem(client)
            except RuntimeError as exc:
                # Not knowing the mode is not knowing the fence is there.
                mode, fence = None, f"the isolation mode could not be read ({exc})"
            # Container.status is read-only in docker-py; what this pass stopped is kept apart.
            stopped_now: set[str] = set()
            if fence and mode in (MODE_ON, None):
                # Stop first, so nothing runs while the table is put back.
                for c in gated:
                    if c.status == "running":
                        _guard_stop(c, fence)
                        stopped_now.add(c.name)
                if mode == MODE_ON:
                    with contextlib.suppress(RuntimeError, IsolationConflict):
                        apply_fence(client)
            stopped = orch.user_stopped()
            failed = orch.deploy_failed()
            for c in gated:
                running = c.status == "running" and c.name not in stopped_now
                problem = (
                    fence
                    or (FAILED_DEPLOY if c.name in failed else None)
                    or orch.gated_spec_problem(c, mode)
                    or (None if deploying else orch.identity_problem(c))
                )
                if problem:
                    held[c.name] = problem
                    if running:
                        _guard_stop(c, problem)
                elif (
                    not deploying
                    and c.status in ("exited", "created")
                    and c.name not in stopped
                    # The old node a deploy moved aside: put back by its roll-back, never by the guard.
                    and not c.name.endswith(orch.REPLACED_SUFFIX)
                ):
                    c.start()
                    if problem := _started_unattached(c, mode):
                        # Up with no address on its network: never started again
                        # by the guard until a deploy succeeds.
                        held[c.name] = problem
                        _guard_stop(c, problem)
                        if not problem.startswith(UNREAD):
                            orch._mark_failed(c.name, True)
                    else:
                        logger.info("Started %s: the LAN fence is confirmed and it is on its network", c.name)
        finally:
            if not deploying:
                orch.GATED_DEPLOY_LOCK.release()
    except Exception as exc:  # noqa: BLE001 - the next pass tries again
        logger.warning("Fence guard pass failed: %s", exc)
        # No Fleet button on a report the scan could not refresh. A later step
        # failing (another node's start) leaves a fresh report as it is.
        if not scanned:
            _state["unfenced"] = []
    _state["guard"] = held
    return held


#: Why the guard holds a container a failed deploy left behind.
FAILED_DEPLOY = "its last deploy failed and left this container behind. Redeploy it from the dashboard"


#: A start the guard could not read back: stopped, but tried again next pass.
UNREAD = "it could not be read back after its start"


def _started_unattached(container: Any, mode: str | None) -> str | None:
    """Why a container just started must stop: not running, or no address on its network.

    Judged in ``on`` and ``operator`` mode, the only ones a fence-gated
    container runs in (mode_problem).
    """
    if mode not in (MODE_ON, MODE_OPERATOR):
        return None
    expected = NETWORK_NAME if mode == MODE_ON else _orchestrator()._CONTAINER_NETWORK
    try:
        container.reload()
    except Exception as exc:  # noqa: BLE001 - not confirmed is not attached
        return f"{UNREAD} ({exc})"
    attrs = container.attrs if isinstance(getattr(container, "attrs", None), dict) else {}
    state = attrs.get("State") if isinstance(attrs.get("State"), dict) else {}
    nets = ((attrs.get("NetworkSettings") or {}).get("Networks") or {}) if isinstance(attrs, dict) else {}
    address = str(((nets.get(expected) or {}) if isinstance(nets, dict) else {}).get("IPAddress") or "")
    if state and not state.get("Running"):
        return "it exited right after its start"
    if not address:
        return f"it started with no address on {expected}, so it has no network"
    return None


def _guard_stop(container: Any, reason: str) -> None:
    from app.constants import LABEL_SERVICE

    slug = str((container.labels or {}).get(LABEL_SERVICE) or "")
    logger.warning("Stopping %s: %s", container.name, reason)
    container.stop(timeout=_orchestrator()._get_stop_timeout(slug))


def effective_network(client: Any) -> tuple[str, str]:
    """(mode, the network earners should be on, or "" for the default bridge)."""
    mode = resolve_mode(client)
    if mode == MODE_OPERATOR:
        return mode, _orchestrator()._CONTAINER_NETWORK
    if mode == MODE_ON:
        return mode, NETWORK_NAME
    return mode, ""


def _outside_containers(client: Any, network: str) -> list[Any]:
    found = []
    for c in _managed(client):
        attrs = c.attrs or {}
        mode = str((attrs.get("HostConfig") or {}).get("NetworkMode") or "bridge")
        if mode in ("host", "none") or mode.startswith("container:"):
            continue
        nets = set(((attrs.get("NetworkSettings") or {}).get("Networks") or {}).keys())
        # On our network and another one: it reaches whatever the other reaches.
        if nets != {network}:
            found.append(c)
    return found


def _set_outside(containers: list[Any]) -> None:
    """Running earners outside the fence, and stopped ones apart.

    The switch redeploys the first list. A redeploy starts the container, so a
    stopped earner is left alone and moves the next time it is deployed.
    """
    running = [c for c in containers if c.status == "running"]
    stopped = [c for c in containers if c.status != "running"]
    _state["earners_outside"] = _labels_or_names(running)
    _state["earners_outside_stopped"] = sorted(set(_labels_or_names(stopped)) - set(_state["earners_outside"]))


def reconcile() -> dict[str, Any]:
    """Startup and every RECHECK_SECONDS: put the fence back if it went, refresh the status.

    Never raises: a failure is recorded in the status, which the heartbeat
    carries to the fleet page.
    """
    orch = _orchestrator()
    if not orch.docker_available():
        _state.update(mode=None, network=None, earners_outside=[], earners_outside_stopped=[])
        _set_fence("n/a")
        return status()
    try:
        client = orch._get_client()
        mode = resolve_mode(client)
        _state["mode"] = mode
        _state["network"] = {MODE_ON: NETWORK_NAME, MODE_OPERATOR: orch._CONTAINER_NETWORK}.get(mode)
        if mode == MODE_ON:
            with contextlib.suppress(RuntimeError, IsolationConflict):
                apply_fence(client)
        elif mode == MODE_UNSUPPORTED:
            _set_fence("unsupported", error=PODMAN_UNSUPPORTED + ".")
        elif _needs_reduced(client, mode, orch._CONTAINER_NETWORK):
            try:
                reduce_fence(client)
            except Exception as exc:  # noqa: BLE001 - recorded in the status
                _set_fence("failed", error=str(exc))
        else:
            _set_fence("n/a")
        if mode == MODE_LEGACY:
            _set_outside(default_bridge_earners(client))
        elif mode in (MODE_ON, MODE_OPERATOR):
            _set_outside(_outside_containers(client, _state["network"]))
        else:
            _set_outside([])
    except Exception as exc:  # noqa: BLE001 - recorded, never raised
        logger.warning("LAN fence check failed: %s", exc)
        _set_fence("failed", error=str(exc))
    return status()


def _needs_reduced(client: Any, mode: str, operator_network: str) -> bool:
    """Whether our network needs its masquerade back without the drops.

    ``off`` always, while the network exists. ``operator`` only while earners are
    still on our network: they keep their internet until they are redeployed
    onto the operator's, and once none is left the host is not touched.
    """
    if mode not in (MODE_OFF, MODE_OPERATOR):
        return False
    net = managed_network(client)
    if net is None:
        return False
    if mode == MODE_OFF:
        return True
    return operator_network != NETWORK_NAME and bool((net.attrs or {}).get("Containers"))


def refresh_outside() -> None:
    """Recount the earners outside the fence after a deploy or a removal. Never raises.

    Without it the fleet page kept naming a moved earner as exposed until the
    next five-minute check.
    """
    with contextlib.suppress(Exception):
        client = _orchestrator()._get_client()
        mode = _state["mode"]
        if mode == MODE_LEGACY:
            _set_outside(default_bridge_earners(client))
        elif mode in (MODE_ON, MODE_OPERATOR) and _state["network"]:
            _set_outside(_outside_containers(client, _state["network"]))


def _labels_or_names(containers: list[Any]) -> list[str]:
    from app.constants import LABEL_SERVICE

    return sorted({str((c.labels or {}).get(LABEL_SERVICE) or c.name) for c in containers})


def enable() -> dict[str, Any]:
    """Turn isolation on for an upgraded worker. Returns the status and the running earners to move.

    Raises IsolationConflict for a setting or a network the owner has to fix
    first, RuntimeError when the fence cannot be applied.
    """
    orch = _orchestrator()
    if orch._CONTAINER_NETWORK:
        raise IsolationConflict(
            f"This worker uses CASHPILOT_CONTAINER_NETWORK={orch._CONTAINER_NETWORK}, so its firewall rules are "
            "yours to manage. Remove that setting to let CashPilot fence the earners."
        )
    if setting() == "off":
        raise IsolationConflict(
            "This worker has CASHPILOT_ISOLATION=off. Remove that setting and restart the worker to turn isolation on."
        )
    client = orch._get_client()
    if is_podman(client):
        raise IsolationConflict(PODMAN_UNSUPPORTED + ".")
    apply_fence(client)
    _remember(True)
    _state["mode"] = MODE_ON
    _state["network"] = NETWORK_NAME
    _set_outside(_outside_containers(client, NETWORK_NAME))
    return status()


def status() -> dict[str, Any]:
    """What the heartbeat reports. A copy of the cached state; no Docker call."""
    return {
        "mode": _state["mode"],
        "network": _state["network"],
        "fence": dict(_state["fence"]),
        "earners_outside": list(_state["earners_outside"]),
        "earners_outside_stopped": list(_state.get("earners_outside_stopped") or []),
        "guard": dict(_state.get("guard") or {}),
        "unfenced": [dict(u) for u in _state.get("unfenced") or []],
    }


def gateway(client: Any) -> str | None:
    """Our bridge's gateway address: the host as an earner sees it."""
    net = managed_network(client)
    return _gateway(net) if net is not None else None
