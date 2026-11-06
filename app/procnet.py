"""What an earner's network namespace shows in /proc/net: socket tables and counters.

Pure stdlib with no app imports, for two reasons. The worker runs this file's
source inside a short-lived probe container that joins one earner's network
namespace (``python -c``, app/activity.py), and the tests import it directly to
feed it fixture text. Nothing here reads traffic contents: only the kernel's
socket tables (who is connected to which address and port) and the protocol
counters in /proc/net/snmp.

``classify`` runs on the worker, not in the probe, so the probe needs no network
context; it lives here so its ranges sit next to the parser and both can be
tested together. CashPilot Desktop runs this same file as its helper and passes
the context in ``PROBE_CTX``; the probe then classifies the rows itself.

An earner on the host network shares the machine's socket table, so for it the
probe runs with ``PROBE_MODE=cgroup``: it asks the kernel for the socket list
over sock_diag, which reports each socket's cgroup, and keeps only the sockets
of the earner's own cgroup (and the cgroups under it). Nothing else leaves the
probe.
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
    # A port is inbound when any snapshot shows a listener on it: a connection
    # outlives a listener that closed mid-sample, and must not turn outbound.
    listening = {s["lport"] for snap in snapshots for s in snap if s["proto"] == "tcp" and s["state"] == "listen"}
    for snap in snapshots:
        listeners = [s for s in snap if s["proto"] == "tcp" and s["state"] == "listen"]
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


#: sock_diag over netlink: the kernel's own socket dump, with each socket's cgroup.
NETLINK_SOCK_DIAG = 4
SOCK_DIAG_BY_FAMILY = 20
NLM_F_REQUEST = 0x1
NLM_F_DUMP = 0x300
#: Set on NLMSG_DONE when the table changed during the dump, so the dump may miss sockets.
NLM_F_DUMP_INTR = 0x10
NLMSG_ERROR = 2
NLMSG_DONE = 3
#: enum in include/uapi/linux/inet_diag.h; emitted for every full socket since Linux 5.8.
INET_DIAG_CGROUP_ID = 21
_NLMSG_HDR = struct.Struct("=IHHII")
#: inet_diag_req_v2: family, protocol, ext, pad, states, then a zeroed 48-byte sockid.
_DIAG_REQ = struct.Struct("=BBBxI48x")
#: inet_diag_msg: family, state, timer, retrans, sport, dport (big endian), src[16], dst[16], if, cookie[2],
#: expires, rqueue, wqueue, uid, inode.
_DIAG_MSG = struct.Struct("=BBBB2H16s16sI8xIIIII")
_RTA_HDR = struct.Struct("=HH")
#: Bound on the sockets one dump reads, so a host with a huge table cannot keep the helper busy.
MAX_DIAG_MESSAGES = 200_000
#: Every TCP state but TIME_WAIT (6) and NEW_SYN_RECV (12): those never carry a cgroup id.
DIAG_STATES = 0xFFFFFFFF & ~((1 << 6) | (1 << 12))
DIAG_DUMPS = (
    ("tcp", socket.AF_INET, 6),
    ("tcp6", socket.AF_INET6, 6),
    ("udp", socket.AF_INET, 17),
    ("udp6", socket.AF_INET6, 17),
)
CGROUP_ROOT = "/sys/fs/cgroup"
CGROUP_MAX_DEPTH = 6
CGROUP_MAX_DIRS = 5000


def _align4(n):
    return (n + 3) & ~3


def _diag_addr(raw, family):
    if family == socket.AF_INET:
        return socket.inet_ntoa(raw[:4])
    addr = ipaddress.IPv6Address(raw)
    return str(addr.ipv4_mapped) if addr.ipv4_mapped else str(addr)


def parse_diag(data, proto):
    """(sockets, done, error, interrupted) from one netlink read of a sock_diag dump.

    Each socket is the dict parse_sockets makes, plus ``cgroup``: the cgroup v2
    id the kernel reported, or None when it reported none (TIME_WAIT and
    request sockets never carry one). ``done`` is True at NLMSG_DONE; ``error``
    is the errno of an NLMSG_ERROR or of a DONE that ends a failed dump, else 0. ``interrupted`` is True when the
    kernel ended the dump with NLM_F_DUMP_INTR: the table changed meanwhile.
    """
    family = "udp" if proto.startswith("udp") else "tcp"
    found, off = [], 0
    while off + _NLMSG_HDR.size <= len(data):
        length, kind, flags, _seq, _pid = _NLMSG_HDR.unpack_from(data, off)
        if length < _NLMSG_HDR.size or off + length > len(data):
            return found, True, -1, False
        body = data[off + _NLMSG_HDR.size : off + length]
        off += _align4(length)
        if kind == NLMSG_DONE:
            # The kernel ends a failed dump with DONE and a negative errno in its body.
            err = struct.unpack_from("=i", body)[0] if len(body) >= 4 else 0
            return found, True, (-err if err < 0 else 0), bool(flags & NLM_F_DUMP_INTR)
        if kind == NLMSG_ERROR:
            err = struct.unpack_from("=i", body)[0] if len(body) >= 4 else -1
            return found, True, (-err if err < 0 else err), False
        if kind != SOCK_DIAG_BY_FAMILY or len(body) < _DIAG_MSG.size:
            continue
        fam, state, _t, _r, sport, dport, src, dst, _if, _exp, _rq, _wq, _uid, _ino = _DIAG_MSG.unpack_from(body)
        try:
            sock = {
                "proto": family,
                "lip": _diag_addr(src, fam),
                "lport": socket.ntohs(sport),
                "rip": _diag_addr(dst, fam),
                "rport": socket.ntohs(dport),
            }
        except (ValueError, OSError):
            continue
        cgroup = None
        a = _DIAG_MSG.size
        while a + _RTA_HDR.size <= len(body):
            alen, atype = _RTA_HDR.unpack_from(body, a)
            if alen < _RTA_HDR.size or a + alen > len(body):
                break
            if atype == INET_DIAG_CGROUP_ID and alen >= _RTA_HDR.size + 8:
                cgroup = struct.unpack_from("=Q", body, a + _RTA_HDR.size)[0] or None
            a += _align4(alen)
        sock["cgroup"] = cgroup
        if family == "udp":
            connected = sock["rport"] != 0 and not ipaddress.ip_address(sock["rip"]).is_unspecified
            sock["state"] = "est" if connected else "other"
        else:
            sock["state"] = STATES.get(f"{state:02X}", "other")
        found.append(sock)
    return found, False, 0, False


def diag_dump(proto, family, ipproto, keep=None, cap=MAX_DIAG_MESSAGES):
    """(sockets, truncated): the sockets of one family and protocol in this network namespace, via sock_diag.

    ``keep`` filters each socket as it is read, so memory follows what is kept,
    not the host's whole table. ``truncated`` is True when ``cap`` sockets were
    read before the dump ended (even in the batch that ends it), or the kernel marked the dump interrupted. Raises OSError when netlink refuses (no socket,
    or an error reply).
    """
    req = _DIAG_REQ.pack(family, ipproto, 0, DIAG_STATES)
    msg = _NLMSG_HDR.pack(_NLMSG_HDR.size + len(req), SOCK_DIAG_BY_FAMILY, NLM_F_REQUEST | NLM_F_DUMP, 1, 0) + req
    family_netlink = getattr(socket, "AF_NETLINK", None)
    if family_netlink is None:
        raise OSError("no netlink on this system")
    found, read = [], 0
    with socket.socket(family_netlink, socket.SOCK_DGRAM, NETLINK_SOCK_DIAG) as s:
        s.settimeout(5)
        s.sendto(msg, (0, 0))
        while True:
            sockets, done, err, interrupted = parse_diag(s.recv(1 << 16), proto)
            if err:
                raise OSError(err, "sock_diag")
            clipped = len(sockets) > cap - read
            sockets = sockets[: cap - read]
            read += len(sockets)
            found.extend(x for x in sockets if keep is None or keep(x))
            if done:
                return found, interrupted or clipped
            if read >= cap:
                return found, True


def cgroup_ids(container_id, root=CGROUP_ROOT, max_depth=CGROUP_MAX_DEPTH, max_dirs=CGROUP_MAX_DIRS):
    """(ids, reason): the cgroup v2 ids of a container's cgroup and every cgroup under it.

    The container's cgroup is the directory whose name holds its full id
    (cgroupfs ``docker/<id>``, systemd ``docker-<id>.scope``, podman
    ``libpod-<id>.scope``); a cgroup's id is its directory's inode number.
    ``reason`` is "" on success, else cgroup_v1 or cgroup_missing, or
    cgroup_partial when the container's cgroup was found but a walk limit
    left part of its subtree unread (the ids are then incomplete).
    """
    if not os.path.exists(os.path.join(root, "cgroup.controllers")):
        return set(), "cgroup_v1"
    cid = str(container_id or "").lower()
    if len(cid) != 64 or any(c not in "0123456789abcdef" for c in cid):
        return set(), "cgroup_missing"
    queue, seen, ids, cut = [(root, 0, False)], 0, set(), False
    while queue and seen < max_dirs:
        path, depth, inside = queue.pop()
        try:
            entries = list(os.scandir(path))
        except OSError:
            # An unreadable directory of the container's subtree leaves its sockets out.
            cut = cut or inside
            continue
        for i, e in enumerate(entries):
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
                ino = e.inode()
            except OSError:
                continue
            seen += 1
            if seen > max_dirs:
                # The rest of this directory is unread: it matters only if it is the container's.
                cut = cut or inside or any(cid in x.name for x in entries[i:])
                break
            mine = inside or cid in e.name
            if mine:
                ids.add(ino)
            if depth + 1 < max_depth:
                queue.append((e.path, depth + 1, mine))
            elif mine and _has_subdir(e.path):
                cut = True
    # A directory of the container's subtree still queued was never read.
    cut = cut or any(mine for _, _, mine in queue)
    if not ids:
        return ids, "cgroup_missing"
    return ids, "cgroup_partial" if cut else ""


def _has_subdir(path):
    try:
        return any(e.is_dir(follow_symlinks=False) for e in os.scandir(path))
    except OSError:
        return False


def cgroup_snapshot(ids, dumps=DIAG_DUMPS, dump=None):
    """(sockets of these cgroups, tagged, dumps that worked, partial).

    ``tagged`` is True when any socket carried a real cgroup id, or when the
    dumps held no socket at all, so there was nothing to judge the kernel by.

    An id of 1 is the root cgroup, which is also what every socket reports when
    the cgroup v1 net_cls or net_prio controller is active: a host where no
    socket carries anything else cannot be told apart. ``partial`` is True when
    a dump was refused (a kernel without udp_diag) or hit its cap, so the
    reading misses sockets.
    """
    dump = dump or diag_dump
    tagged, seen = False, False

    def keep(s):
        nonlocal tagged, seen
        seen = True
        cg = s.get("cgroup")
        if cg is None:
            # Never match a missing id: TIME_WAIT and request sockets carry
            # none, and None == None would hand the host's to the earner.
            return False
        tagged = tagged or cg != 1
        return cg in ids

    mine, worked, partial = [], 0, False
    for proto, family, ipproto in dumps:
        try:
            sockets, truncated = dump(proto, family, ipproto, keep)
        except OSError:
            partial = True
            continue
        worked += 1
        partial = partial or truncated
        for s in sockets:
            s.pop("cgroup", None)
            mine.append(s)
    return mine, tagged or not seen, worked, partial


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


def _classified(summary, ctx):
    """The summary with each row's class added, as the worker's activity._sample does."""
    out = dict(summary)
    out["out"] = [
        [proto, ip, port, classify(ip, port, ctx), seen, states] for proto, ip, port, seen, states in summary["out"]
    ]
    out["in"] = [[ip, lport, classify(ip, None, ctx), seen] for ip, lport, seen in summary["in"]]
    return out


def _ctx_from_env():
    """The network context in PROBE_CTX, or None when absent or unreadable."""
    raw = os.environ.get("PROBE_CTX")
    if not raw:
        return None
    try:
        ctx = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(ctx, dict):
        return None
    subnets = []
    for item in ctx.get("subnets") or []:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            subnets.append((str(item[0]), str(item[1])))
    return {
        "gateways": [str(x) for x in ctx.get("gateways") or []],
        "dns": [str(x) for x in ctx.get("dns") or []],
        "subnets": subnets,
        "peers": None if ctx.get("peers") is None else [str(x) for x in ctx.get("peers") or []],
    }


def _cgroup_reading(container_id, snapshots_n, gap):
    """(snapshots, reason, partial) of the sockets of one container's cgroups in this network namespace."""
    ids, reason = cgroup_ids(container_id)
    cut = reason == "cgroup_partial"
    if reason and not cut:
        return [], reason, False
    snapshots, tagged, worked, partial = [], False, 0, cut
    for i in range(snapshots_n):
        if i:
            time.sleep(gap)
        mine, any_tagged, dumps, missed = cgroup_snapshot(ids)
        tagged = tagged or any_tagged
        worked = max(worked, dumps)
        partial = partial or missed
        snapshots.append(mine)
    if not worked:
        return [], "sock_diag_refused", False
    if not tagged:
        return [], "kernel_no_cgroup_id", False
    return snapshots, "", partial


def main():
    snapshots_n = _env_int("PROBE_SNAPSHOTS", 5, 1, 10)
    gap = _env_int("PROBE_GAP", 2, 0, 5)
    ctx = _ctx_from_env()
    if os.environ.get("PROBE_MODE") == "cgroup":
        # The host's counters and namespace are the machine's, not the earner's.
        snapshots, reason, partial = _cgroup_reading(os.environ.get("PROBE_CONTAINER", ""), snapshots_n, gap)
        summary = summarise(snapshots)
        # A refused or capped dump missed sockets: never present the reading as complete.
        summary["truncated"] = summary["truncated"] or partial
        out = {
            "v": 1,
            "attribution": "cgroup",
            "reason": reason,
            "netns": None,
            "snmp_start": None,
            "snmp_end": None,
            "summary": _classified(summary, ctx) if ctx is not None else summary,
            "snapshots": snapshots_n,
        }
        if ctx is not None:
            out["classified"] = True
        print(json.dumps(out))
        return
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
    summary = summarise(snapshots)
    out = {
        "v": 1,
        "netns": netns,
        "snmp_start": snmp_start,
        "snmp_end": snmp_end,
        "summary": _classified(summary, ctx) if ctx is not None else summary,
        "files": files,
        "malformed": malformed,
        "snapshots": snapshots_n,
    }
    if ctx is not None:
        out["classified"] = True
    print(json.dumps(out))


if __name__ == "__main__":
    main()
