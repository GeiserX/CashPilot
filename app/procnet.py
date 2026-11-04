"""What an earner's network namespace shows in /proc/net: socket tables and counters.

Pure stdlib with no app imports, for two reasons. The worker runs this file's
source inside a short-lived probe container that joins one earner's network
namespace (``python -c``, app/activity.py), and the tests import it directly to
feed it fixture text. Nothing here reads traffic contents: only the kernel's
socket tables (who is connected to which address and port) and the protocol
counters in /proc/net/snmp.

``classify`` runs on the worker, not in the probe, so the probe needs no network
context; it lives here so its ranges sit next to the parser and both can be
tested together.
"""

import ipaddress
import json
import os
import socket
import struct
import time

#: TCP states from include/net/tcp_states.h that this page tells apart. The
#: closing states (FIN_WAIT1/2, TIME_WAIT, CLOSE_WAIT, LAST_ACK, CLOSING) are
#: one "closed": the connection happened, which is what the mail alert needs,
#: because a short SMTP session spends most of its life in TIME_WAIT.
STATES = {
    "01": "est",
    "02": "syn_sent",
    "03": "syn_recv",
    "04": "closed",
    "05": "closed",
    "06": "closed",
    "08": "closed",
    "09": "closed",
    "0A": "listen",
    "0B": "closed",
}
#: The SNMP counters read, by protocol line. A connection opened is
#: ActiveOpens (we dialled) or PassiveOpens (someone dialled us).
SNMP_TCP = ("ActiveOpens", "PassiveOpens", "AttemptFails", "EstabResets", "CurrEstab")
SNMP_UDP = ("InDatagrams", "OutDatagrams")
#: /proc/net/snmp counts IPv4 UDP only; IPv6 UDP is in /proc/net/snmp6.
SNMP6_UDP = {"Udp6InDatagrams": "InDatagrams", "Udp6OutDatagrams": "OutDatagrams"}
#: DNS and DNS over TLS: to a local address this is the earner's resolver.
DNS_PORTS = (53, 853)
SOCKET_FILES = (
    ("tcp", "/proc/net/tcp"),
    ("tcp6", "/proc/net/tcp6"),
    ("udp", "/proc/net/udp"),
    ("udp6", "/proc/net/udp6"),
)

#: Copied from app/lan_isolation.py (not in the worker image); a test pins them equal.
RFC1918 = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
LINK_LOCAL = ("169.254.0.0/16",)
ULA = ("fc00::/7",)
LINK_LOCAL6 = ("fe80::/10",)
CGNAT = ("100.64.0.0/10",)
METADATA = ("169.254.169.254", "fd00:ec2::254")
DOCKER_DNS = "127.0.0.11"
TAILSCALE_DNS = "100.100.100.100"
#: Network drivers whose subnet is the operator's real LAN, not a Docker bridge.
LAN_DRIVERS = ("macvlan", "ipvlan")

_RFC1918 = [ipaddress.ip_network(n) for n in RFC1918]
_ULA = [ipaddress.ip_network(n) for n in ULA]
_LINK_LOCAL = [ipaddress.ip_network(n) for n in LINK_LOCAL + LINK_LOCAL6]
_CGNAT = [ipaddress.ip_network(n) for n in CGNAT]


def hex_ip(hexval):
    """An address as /proc/net prints it, as text. IPv4-mapped IPv6 folds to IPv4.

    /proc/net/tcp prints the 32-bit address in host byte order, and tcp6 prints
    four such words, so both are unpacked with the native order.
    """
    if len(hexval) == 8:
        return socket.inet_ntoa(struct.pack("=I", int(hexval, 16)))
    if len(hexval) == 32:
        raw = b"".join(struct.pack("=I", int(hexval[i : i + 8], 16)) for i in range(0, 32, 8))
        addr = ipaddress.IPv6Address(raw)
        return str(addr.ipv4_mapped) if addr.ipv4_mapped else str(addr)
    raise ValueError("not a /proc/net address")


def parse_sockets(text, proto):
    """(sockets, malformed lines) from one /proc/net/{tcp,tcp6,udp,udp6} file.

    Each socket is a dict with proto ("tcp" or "udp"), local and remote address
    and port, and state: est, syn_sent, syn_recv, listen or other. A UDP socket
    is "est" when connected to a peer and "other" when only bound.
    """
    family = "udp" if proto.startswith("udp") else "tcp"
    found, malformed = [], 0
    for line in (text or "").splitlines():
        parts = line.split()
        if not parts or parts[0] == "sl":
            continue
        try:
            la, lp = parts[1].split(":")
            ra, rp = parts[2].split(":")
            state = parts[3].upper()
            if len(state) != 2:
                raise ValueError("state")
            int(state, 16)
            sock = {
                "proto": family,
                "lip": hex_ip(la),
                "lport": int(lp, 16),
                "rip": hex_ip(ra),
                "rport": int(rp, 16),
            }
        except (ValueError, IndexError, struct.error):
            malformed += 1
            continue
        if family == "udp":
            connected = sock["rport"] != 0 and not ipaddress.ip_address(sock["rip"]).is_unspecified
            sock["state"] = "est" if connected else "other"
        else:
            sock["state"] = STATES.get(state, "other")
        found.append(sock)
    return found, malformed


def _parse_snmp6_udp(text):
    """Udp6 in/out datagrams from /proc/net/snmp6 (one "name value" per line), or None."""
    found = {}
    for raw in (text or "").splitlines():
        parts = raw.split()
        if len(parts) == 2 and parts[0] in SNMP6_UDP:
            try:
                found[SNMP6_UDP[parts[0]]] = int(parts[1])
            except ValueError:
                return None
    return found if len(found) == len(SNMP6_UDP) else None


def parse_snmp(text, text6=None):
    """The TCP and UDP counters of /proc/net/snmp, or None when the file says nothing.

    The file holds pairs of lines per protocol: names, then values. UDP over
    IPv6 is counted in /proc/net/snmp6 (``text6``) and added when present.
    """
    rows = {}
    lines = (text or "").splitlines()
    for names, values in zip(lines, lines[1:], strict=False):
        n, v = names.split(), values.split()
        if len(n) > 1 and n[0] == v[0] and n[0] in ("Tcp:", "Udp:") and len(n) == len(v):
            try:
                rows[n[0][:-1].lower()] = {k: int(x) for k, x in zip(n[1:], v[1:], strict=True)}
            except ValueError:
                continue
    tcp, udp = rows.get("tcp"), rows.get("udp")
    if not tcp or any(k not in tcp for k in SNMP_TCP):
        return None
    out = {"tcp": {k: tcp[k] for k in SNMP_TCP}, "udp": None}
    if udp and all(k in udp for k in SNMP_UDP):
        out["udp"] = {k: udp[k] for k in SNMP_UDP}
        udp6 = _parse_snmp6_udp(text6)
        if udp6:
            out["udp"] = {k: out["udp"][k] + udp6[k] for k in SNMP_UDP}
    return out


def _loopback(ip):
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return True


def summarise(snapshots, cap_out=40, cap_in=20):
    """Fold several socket snapshots of one namespace into one bounded summary.

    A connected socket whose local port is one this namespace listens on is
    inbound, keyed (local port, remote address); every other connected socket
    is outbound, keyed (proto, remote address, remote port). ``seen`` is the
    number of snapshots a key appeared in. Loopback is dropped: it never leaves
    the namespace. ``remotes_total`` counts every key before the caps.
    """
    out, inbound = {}, {}
    listen, est_max, syn_max, udp_bound = set(), 0, 0, 0
    for snap in snapshots:
        listeners = [s for s in snap if s["proto"] == "tcp" and s["state"] == "listen"]
        listening = {s["lport"] for s in listeners}
        # Reported ports are the ones reachable from outside the namespace.
        listen |= {s["lport"] for s in listeners if not _loopback(s["lip"])}
        est = syn = bound = 0
        seen_out, seen_in = set(), set()
        for s in snap:
            if s["state"] == "listen":
                continue
            if s["proto"] == "udp" and s["state"] == "other":
                if not _loopback(s["lip"]):
                    bound += 1
                continue
            if _loopback(s["rip"]):
                continue
            if s["proto"] == "tcp" and s["state"] == "est":
                est += 1
            elif s["state"] == "syn_sent":
                syn += 1
            if s["proto"] == "tcp" and s["lport"] in listening:
                key = (s["lport"], s["rip"])
                entry = inbound.setdefault(key, {"seen": 0})
                if key not in seen_in:
                    seen_in.add(key)
                    entry["seen"] += 1
            else:
                key = (s["proto"], s["rip"], s["rport"])
                entry = out.setdefault(key, {"seen": 0, "states": {}})
                entry["states"][s["state"]] = entry["states"].get(s["state"], 0) + 1
                if key not in seen_out:
                    seen_out.add(key)
                    entry["seen"] += 1
        est_max, syn_max, udp_bound = max(est_max, est), max(syn_max, syn), max(udp_bound, bound)

    out_rows = sorted(out.items(), key=lambda kv: (-kv[1]["seen"], kv[0]))
    in_rows = sorted(inbound.items(), key=lambda kv: (-kv[1]["seen"], kv[0]))
    total = len(out_rows) + len(in_rows)
    return {
        "est_max": est_max,
        "syn_sent_max": syn_max,
        "udp_bound": udp_bound,
        "listen_ports": sorted(listen)[:20],
        "remotes_total": total,
        "truncated": len(out_rows) > cap_out or len(in_rows) > cap_in,
        "out": [[k[0], k[1], k[2], v["seen"], v["states"]] for k, v in out_rows[:cap_out]],
        "in": [[k[1], k[0], v["seen"]] for k, v in in_rows[:cap_in]],
    }


def _in_any(addr, nets):
    return any(addr.version == n.version and addr in n for n in nets)


def classify(ip, port, ctx=None):
    """Where a remote address sits, from the earner's point of view.

    ``ctx`` carries the earner's network context: ``gateways`` (bridge
    gateways), ``dns`` (resolvers it was given), ``subnets``, a list of
    (cidr, driver) for the networks it is attached to, and ``peers``, the
    addresses on those networks that belong to earners (absent: unknown, every
    address on a bridge subnet is a peer). The order is the rule:

    infra (Docker's DNS, DNS to the gateway or a configured resolver or
    Tailscale's) before metadata before DNS to any local address (the
    resolver Docker copied from the host, usually the router) before
    docker_host (the gateway on any other port) before peer (an earner on its
    own bridge) or docker_peer (any other container there) before lan before
    tailnet before link_local before multicast; everything else is public.
    """
    ctx = ctx or {}
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "public"
    text = str(addr)
    gateways = set(ctx.get("gateways") or ())
    dns = set(ctx.get("dns") or ())
    if text == DOCKER_DNS or (port == 53 and (text in gateways or text in dns or text == TAILSCALE_DNS)):
        return "infra"
    if text in METADATA:
        return "metadata"
    if port in DNS_PORTS and (
        _in_any(addr, _RFC1918) or _in_any(addr, _ULA) or _in_any(addr, _CGNAT) or _in_any(addr, _LINK_LOCAL)
    ):
        return "infra"
    if text in gateways:
        return "docker_host"
    peers = ctx.get("peers")
    peers = None if peers is None else set(peers)
    for cidr, driver in ctx.get("subnets") or ():
        try:
            net = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            continue
        if addr.version == net.version and addr in net:
            if driver in LAN_DRIVERS:
                return "lan"
            return "peer" if peers is None or text in peers else "docker_peer"
    if _in_any(addr, _RFC1918) or _in_any(addr, _ULA):
        return "lan"
    if _in_any(addr, _CGNAT):
        return "tailnet"
    if _in_any(addr, _LINK_LOCAL):
        return "link_local"
    if addr.is_multicast:
        return "multicast"
    if addr.is_loopback:
        return "infra"
    return "public"


def _read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def _env_int(name, default, low, high):
    try:
        return max(low, min(high, int(os.environ.get(name, default))))
    except ValueError:
        return default


def main():
    snapshots_n = _env_int("PROBE_SNAPSHOTS", 5, 1, 10)
    gap = _env_int("PROBE_GAP", 2, 0, 5)
    try:
        netns = os.readlink("/proc/self/ns/net")
    except OSError:
        netns = None
    snmp_start = parse_snmp(_read("/proc/net/snmp"), _read("/proc/net/snmp6"))
    files = {}
    snapshots, malformed = [], 0
    for i in range(snapshots_n):
        if i:
            time.sleep(gap)
        snap = []
        for name, path in SOCKET_FILES:
            text = _read(path)
            files[name] = text is not None
            sockets, bad = parse_sockets(text, name)
            snap.extend(sockets)
            malformed += bad
        snapshots.append(snap)
    snmp_end = parse_snmp(_read("/proc/net/snmp"), _read("/proc/net/snmp6"))
    print(
        json.dumps(
            {
                "v": 1,
                "netns": netns,
                "snmp_start": snmp_start,
                "snmp_end": snmp_end,
                "summary": summarise(snapshots),
                "files": files,
                "malformed": malformed,
                "snapshots": snapshots_n,
            }
        )
    )


if __name__ == "__main__":
    main()
