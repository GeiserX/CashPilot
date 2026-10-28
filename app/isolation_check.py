"""What can an earner reach on this host's networks? (issue #451)

The fence that keeps earners off the LAN, the host and any overlay network is a
firewall rule the operator writes by hand, and it fails silently: Tailscale puts
its own chain ahead of DOCKER-USER, a script flushes another script's rules, a
service lands on Docker's default bridge. This module tells the truth about the
result, in the same stance as ``app.lan_isolation``: it changes no firewall rule
and leaves nothing behind. It only starts two short-lived probe containers from
the worker's own image, and removes them on every path.

1. **Control.** A probe on host networking lists targets the worker could not
   guess (default gateway, the host's addresses with ports it listens on,
   private resolvers, Tailscale's 100.100.100.100 and one tailnet peer, cloud
   metadata) and keeps only the ones that answer from the host. A closed port
   therefore never counts as "blocked", which is what lets this check fail.
2. **Earner side.** A second probe joins a running earner's network namespace
   (or CASHPILOT_CONTAINER_NETWORK when none runs) and tries the kept targets,
   plus one internet address as the positive check.

No kept targets, or no internet from the earner side, is "could not test",
never "isolated".
"""

from __future__ import annotations

import contextlib
import json
import threading
from typing import Any

from app import orchestrator
from app.constants import LABEL_MANAGED, LABEL_SERVICE

DOCS = "https://geiserx.github.io/CashPilot/"
FIX_PAGE = DOCS + "isolation-check/#2-fix-it-by-platform"
OVERLAY_PAGE = DOCS + "isolation-check/#with-tailscale-or-another-overlay-network-on-the-host"
MYSTERIUM_PAGE = DOCS + "isolation-check/#mysterium-which-uses-host-networking"
BRIDGE_PAGE = DOCS + "home-network-security/#put-the-containers-on-their-own-bridge"
DNS_PAGE = DOCS + "home-network-security/#name-lookups-need-a-resolver-the-rules-allow"

GROUPS = {
    "lan": ("Your LAN", FIX_PAGE),
    "host": ("This host", FIX_PAGE),
    "overlay": ("Overlay network", OVERLAY_PAGE),
    "metadata": ("Cloud metadata", FIX_PAGE),
}

INTERNET = {"group": "internet", "host": "1.1.1.1", "port": 443, "label": "public address"}
TAILSCALE_DNS = "100.100.100.100"

#: A Mysterium node's own blackhole list. The node reads it from this flag on
#: its command line, and its NAT chain sends those ranges to this address.
PROTECTED_FLAG = "--firewall.protected.networks="
MYST_BLACKHOLE = "240.0.0.1"

PROBE_LABEL = "cashpilot.probe"
HOST_PROBE = "cashpilot-isolation-probe-host"
EARNER_PROBE = "cashpilot-isolation-probe-earner"
#: Seconds one probe container may run. Each connect gives up after 2 s and
#: they run in parallel, so a healthy probe finishes in a few seconds.
PROBE_TIMEOUT = 30

_lock = threading.Lock()


class CheckBusy(RuntimeError):
    """Another check is running on this worker (the probe names are fixed)."""


# Runs inside the probe containers: stdlib only, no file writes, prints JSON.
# "discover" (host network) lists candidates and tries each; "test" tries the
# targets given in PROBE_TARGETS and prints one boolean per target.
PROBE_SCRIPT = r"""
import fcntl, ipaddress, json, os, socket, struct, sys
from concurrent.futures import ThreadPoolExecutor

def reach(t):
    try:
        with socket.create_connection((t["host"], int(t["port"])), timeout=2):
            return True
    except OSError:
        return False

def ip(hexval):
    return socket.inet_ntoa(struct.pack("=I", int(hexval, 16)))

def tcp(state):
    found = []
    with open("/proc/net/tcp") as f:
        next(f)
        for line in f:
            p = line.split()
            if p[3] == state:
                la, lp = p[1].split(":")
                ra, rp = p[2].split(":")
                found.append((ip(la), int(lp, 16), ip(ra), int(rp, 16)))
    return found

def discover():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ifaces = {}
    for _i, name in socket.if_nameindex():
        try:
            raw = fcntl.ioctl(s.fileno(), 0x8915, struct.pack("256s", name[:15].encode()))
            ifaces[name] = socket.inet_ntoa(raw[20:24])
        except OSError:
            pass
    own = sorted({a for a in ifaces.values() if not a.startswith("127.")})[:24]
    cgnat = ipaddress.ip_network("100.64.0.0/10")
    out, seen = [], set()
    def add(group, host, port, label):
        if (host, port) not in seen:
            seen.add((host, port))
            out.append({"group": group, "host": host, "port": port, "label": label})
    with open("/proc/net/route") as f:
        next(f)
        for line in f:
            p = line.split()
            if p[1] == "00000000" and p[2] != "00000000":
                for port in (80, 443, 53, 22):
                    add("lan", ip(p[2]), port, "default gateway")
    # Tailscale names its interface tailscale0, or tailscale1 on Unraid's
    # plugin; any address of ours in 100.64.0.0/10 says the same.
    if any(n.startswith("tailscale") for n in ifaces) or any(ipaddress.ip_address(a) in cgnat for a in own):
        add("overlay", "100.100.100.100", 53, "Tailscale DNS")
        add("overlay", "100.100.100.100", 80, "Tailscale status page")
        # A connection this host opened, so the peer's port is a service port.
        mine = {lp for _l, lp, _r, _q in tcp("0A")}
        for _l, lp, ra, rp in tcp("01"):
            if lp not in mine and ipaddress.ip_address(ra) in cgnat and ra != "100.100.100.100" and ra not in own:
                add("overlay", ra, rp, "tailnet peer")
                break
    resolvers = []
    try:
        with open("/etc/resolv.conf") as f:
            for line in f:
                p = line.split()
                if len(p) > 1 and p[0] == "nameserver":
                    resolvers.append(p[1])
    except OSError:
        pass
    for r in resolvers:
        try:
            a = ipaddress.ip_address(r)
        except ValueError:
            continue
        if a.version != 4 or a.is_loopback or r in own:
            continue
        if a in cgnat:
            add("overlay", r, 53, "DNS resolver")
        elif a.is_private:
            add("lan", r, 53, "DNS resolver")
    add("metadata", "169.254.169.254", 80, "cloud metadata")
    listen = tcp("0A")
    wild = sorted({lp for la, lp, _r, _q in listen if la == "0.0.0.0"}, key=lambda p: (p != 22, p))[:3]
    for a in own:
        for port in wild:
            add("host", a, port, "this host, port %d" % port)
    for la, lp, _r, _q in listen:
        if la != "0.0.0.0" and not la.startswith("127."):
            add("host", la, lp, "this host, port %d" % lp)
    return {"candidates": out, "resolvers": resolvers}

def run(targets):
    with ThreadPoolExecutor(32) as pool:
        return list(pool.map(reach, targets))

if sys.argv[1] == "discover":
    found = discover()
    for t, ok in zip(found["candidates"], run(found["candidates"])):
        t["ok"] = ok
    print(json.dumps(found))
else:
    print(json.dumps({"results": run(json.loads(os.environ["PROBE_TARGETS"]))}))
"""


def _remove_probe(client: Any, name: str) -> None:
    with contextlib.suppress(Exception):
        client.containers.get(name).remove(force=True)


def run_probe(
    client: Any,
    image: str,
    name: str,
    mode: str,
    *,
    network_mode: str | None = None,
    network: str | None = None,
    targets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run one probe container to completion and return what it printed.

    The container is removed on every path: success, a non-zero exit, a wait
    that times out, or Docker refusing halfway through. Removal goes by name,
    so a container created by a ``run`` that then failed to start goes too.
    """
    _remove_probe(client, name)
    try:
        container = client.containers.run(
            image=image,
            name=name,
            entrypoint=["python", "-c", PROBE_SCRIPT],
            command=[mode],
            environment={"PROBE_TARGETS": json.dumps(targets or [])},
            network_mode=network_mode,
            network=network,
            # The same floor as every earner, and lower: no capabilities, no
            # root, nothing writable. A TCP connect needs none of them.
            user="65534:65534",
            read_only=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            privileged=False,
            pids_limit=64,
            mem_limit="64m",
            healthcheck={"test": ["NONE"]},
            labels={PROBE_LABEL: "isolation-check"},
            detach=True,
        )
        status = container.wait(timeout=PROBE_TIMEOUT)
        if (status or {}).get("StatusCode") != 0:
            raise RuntimeError(f"the probe exited with status {(status or {}).get('StatusCode')}")
        return json.loads(container.logs(stdout=True, stderr=False))
    finally:
        _remove_probe(client, name)


def _network_mode(container: Any) -> str:
    return str(((container.attrs or {}).get("HostConfig") or {}).get("NetworkMode") or "bridge")


def _networks(container: Any) -> set[str]:
    return set((((container.attrs or {}).get("NetworkSettings") or {}).get("Networks") or {}).keys())


def _is_bridge(container: Any) -> bool:
    mode = _network_mode(container)
    return mode not in ("host", "none") and not mode.startswith("container:")


def _name(container: Any) -> str:
    return str(getattr(container, "name", "") or "")


def placement_findings(earners: list[Any], network: str) -> list[dict[str, Any]]:
    """Bridge earners that no rule on the isolated bridge can cover."""
    bridge = [c for c in earners if _is_bridge(c)]
    if not bridge:
        return []
    if not network:
        names = ", ".join(sorted(_name(c) for c in bridge))
        return [
            {
                "kind": "no_isolated_network",
                "exposure": True,
                "detail": (
                    "CASHPILOT_CONTAINER_NETWORK is not set, so these earners sit on Docker's default bridge "
                    f"next to your other containers and no rule can single them out: {names}."
                ),
                "docs": BRIDGE_PAGE,
            }
        ]
    outside = sorted(_name(c) for c in bridge if network not in _networks(c))
    if not outside:
        return []
    return [
        {
            "kind": "not_on_isolated_network",
            "exposure": True,
            "detail": (
                f"These earners are not on {network}, so the rules on its bridge do not cover them: "
                f"{', '.join(outside)}. Redeploy them from the dashboard."
            ),
            "docs": BRIDGE_PAGE,
        }
    ]


def dns_findings(earners: list[Any], network: str, resolvers: list[str], blocked: set[str]) -> list[dict[str, Any]]:
    """Earners on the isolated bridge whose first resolver the fence blocks.

    A container with no resolvers of its own uses the daemon's list, which is
    the host's. Each lookup then waits about 4 s before Docker tries the next
    one. They were deployed before CASHPILOT_CONTAINER_DNS and need a redeploy.
    """
    host_first = next((r for r in resolvers if not r.startswith("127.")), None)
    slow = []
    for c in earners:
        if not network or network not in _networks(c):
            continue
        own = ((c.attrs or {}).get("HostConfig") or {}).get("Dns") or []
        first = own[0] if own else host_first
        if first and first in blocked:
            slow.append((_name(c), first))
    if not slow:
        return []
    listed = ", ".join(f"{n} ({r})" for n, r in sorted(slow))
    return [
        {
            "kind": "dns_blocked_resolver",
            "exposure": False,
            "detail": (
                "These earners ask a resolver the fence blocks, so every name lookup waits about 4 s: "
                f"{listed}. Redeploy them so they get CASHPILOT_CONTAINER_DNS."
            ),
            "docs": DNS_PAGE,
        }
    ]


def protected_networks() -> dict[str, list[str]]:
    """Services whose catalog command sets the node's blackhole list, and the list.

    The catalog is the source of truth: a service opts in by passing the flag,
    and the ranges it passes are what its chain must blackhole.
    """
    found = {}
    for svc in orchestrator.get_services() if orchestrator.get_services else []:
        for word in str((svc.get("docker") or {}).get("command") or "").split():
            if word.startswith(PROTECTED_FLAG):
                found[svc["slug"]] = [n for n in word.removeprefix(PROTECTED_FLAG).split(",") if n]
    return found


def read_myst_chain(client: Any) -> dict[str, Any] | None:
    """What a running Mysterium node blackholes for its customers, or None.

    Read from inside the node's own container with the iptables it ships, so
    the answer comes from the backend that wrote the rules. On Unraid the host's
    ``iptables -t nat -S MYST`` shows nothing because the node writes through
    nf_tables, so every backend is asked and the lines are merged.
    """
    nodes, required = [], []
    for slug, networks in protected_networks().items():
        running = client.containers.list(filters={"label": f"{LABEL_SERVICE}={slug}"})
        if running:
            nodes, required = running, networks
            break
    if not nodes:
        return None
    node = nodes[0]
    cmd = "for b in iptables-nft iptables-legacy iptables; do $b -t nat -S MYST 2>/dev/null; done"
    try:
        code, output = node.exec_run(["sh", "-c", cmd])
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        return {"container": _name(node), "readable": False, "detail": f"Could not read the MYST chain: {exc}"}
    lines = sorted({ln.strip() for ln in (output or b"").decode(errors="replace").splitlines() if ln.strip()})
    blackholed = sorted(
        {
            parts[parts.index("-d") + 1]
            for parts in (ln.split() for ln in lines)
            if "-d" in parts and MYST_BLACKHOLE in " ".join(parts)
        }
    )
    if not lines:
        return {
            "container": _name(node),
            "readable": False,
            "blackholed": [],
            "missing": [],
            "detail": (
                "The node's MYST chain is empty or missing. The node builds it when a session starts, so run "
                "the check again after it has carried a session."
            ),
        }
    missing = [net for net in required if net not in blackholed]
    return {"container": _name(node), "readable": True, "blackholed": blackholed, "missing": missing}


def _keep(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The candidates that answered from the host, one port per address.

    A fence drops by destination address, so one open port per address is
    enough to test it. Tailscale's 100.100.100.100 keeps both its ports: port 80
    is how the report tells the DNS rewrite on port 53 from a missing fence.
    """
    kept, hosts = [], set()
    for t in candidates:
        if not t.get("ok") or (t["host"] in hosts and t["host"] != TAILSCALE_DNS):
            continue
        hosts.add(t["host"])
        kept.append({k: t[k] for k in ("group", "host", "port", "label")})
    return kept


def _pick_earner(earners: list[Any], network: str) -> Any | None:
    bridge = [c for c in earners if _is_bridge(c)]
    on_network = [c for c in bridge if network and network in _networks(c)]
    return (on_network or bridge or [None])[0]


def _self_image(client: Any) -> str | None:
    me = orchestrator._self_container(client)
    return ((me.attrs or {}).get("Image") or None) if me is not None else None


def run() -> dict[str, Any]:
    """Run the whole check. Raises CheckBusy when one is already running."""
    if not _lock.acquire(blocking=False):
        raise CheckBusy("An isolation check is already running on this worker.")
    try:
        return _run(orchestrator._get_client())
    finally:
        _lock.release()


def _run(client: Any) -> dict[str, Any]:
    network = orchestrator._CONTAINER_NETWORK
    earners = client.containers.list(filters={"label": f"{LABEL_MANAGED}=true"})
    report: dict[str, Any] = {
        "status": "could_not_test",
        "tested_from": None,
        "groups": [],
        "internet": None,
        "not_answering_from_host": [],
        "findings": placement_findings(earners, network),
        "node_firewall": None,
        "reason": "",
    }

    myst = read_myst_chain(client)
    report["node_firewall"] = myst
    if myst and myst.get("missing"):
        report["findings"].append(
            {
                "kind": "mysterium_unprotected",
                "exposure": True,
                "detail": (
                    f"Mysterium ({myst['container']}) does not blackhole {', '.join(myst['missing'])} for its "
                    "customers. Redeploy it from the dashboard to pick up the catalog's list."
                ),
                "docs": MYSTERIUM_PAGE,
            }
        )

    report["reason"] = _probe(client, report, earners, network)
    exposed = any(f.get("exposure") for f in report["findings"])
    if exposed:
        report["status"] = "exposed"
    elif not report["reason"]:
        report["status"] = "isolated"
    return report


def _probe(client: Any, report: dict[str, Any], earners: list[Any], network: str) -> str:
    """Fill the probe part of ``report``. Returns why it could not test, or ""."""
    image = _self_image(client)
    if not image:
        return "The worker cannot find its own container, so it has no image to run the probes from."

    try:
        found = run_probe(client, image, HOST_PROBE, "discover", network_mode="host")
    except Exception as exc:  # noqa: BLE001 - the report says what went wrong
        return f"The control probe on the host network failed: {exc}"
    candidates = found.get("candidates") or []
    kept = _keep(candidates)
    report["not_answering_from_host"] = [f"{t['host']}:{t['port']}" for t in candidates if not t.get("ok")]
    if not kept:
        return (
            "Nothing answered from the host itself, so there is nothing to compare against. "
            "A blocked result here would prove nothing."
        )

    earner = _pick_earner(earners, network)
    kwargs: dict[str, Any]
    if earner is not None:
        kwargs = {"network_mode": f"container:{earner.id}"}
        report["tested_from"] = {"earner": _name(earner), "network": sorted(_networks(earner))}
    elif network:
        try:
            orchestrator.container_network("bridge")
        except orchestrator.ContainerNetworkError as exc:
            return str(exc)
        kwargs = {"network": network}
        report["tested_from"] = {"earner": None, "network": [network]}
    else:
        return "No earner is running on a bridge and CASHPILOT_CONTAINER_NETWORK is not set, so there is no earner side to test."

    targets = kept + [INTERNET]
    try:
        results = run_probe(client, image, EARNER_PROBE, "test", targets=targets, **kwargs).get("results") or []
    except Exception as exc:  # noqa: BLE001
        return f"The probe on the earner side failed: {exc}"
    if len(results) != len(targets):
        return "The probe on the earner side returned an incomplete answer."

    outcome = [
        dict(t, reachable=bool(r), address=f"{t['host']}:{t['port']}") for t, r in zip(targets, results, strict=True)
    ]
    internet = outcome.pop()
    report["internet"] = {"address": internet["address"], "reachable": internet["reachable"]}
    _tailscale_dns_note(outcome)

    for group, (label, docs) in GROUPS.items():
        rows = [
            {k: t[k] for k in ("address", "label", "reachable", "note") if k in t}
            for t in outcome
            if t["group"] == group
        ]
        if not rows:
            continue
        report["groups"].append({"group": group, "label": label, "targets": rows})
        exposed = [t for t in outcome if t["group"] == group and t["reachable"] and not t.get("expected")]
        if exposed:
            report["findings"].append(
                {
                    "kind": f"reachable_{group}",
                    "exposure": True,
                    "detail": f"{label}: an earner reaches {', '.join(t['address'] for t in exposed)}.",
                    "docs": docs,
                }
            )

    blocked = {t["host"] for t in outcome if t["port"] == 53 and not t["reachable"]}
    report["findings"].extend(dns_findings(earners, network, found.get("resolvers") or [], blocked))

    if not internet["reachable"]:
        return (
            "The earner side cannot reach the internet either, so a blocked result proves nothing. "
            "The earner may be down, or run under gVisor, whose network namespace a probe cannot join."
        )
    return ""


def _tailscale_dns_note(outcome: list[dict[str, Any]]) -> None:
    """Tell the DNS rewrite apart from a missing fence (docs/isolation-check.md).

    With the documented rewrite, port 53 on 100.100.100.100 is sent on to a
    public resolver before the fence sees it, so it reads reachable on a fenced
    host. Port 80 on the same address (tailscaled's status page) is not
    rewritten: blocked there means the fence works and port 53 is the rewrite.
    """
    by_port = {t["port"]: t for t in outcome if t["host"] == TAILSCALE_DNS}
    dns, page = by_port.get(53), by_port.get(80)
    if not dns or not dns["reachable"]:
        return
    if page and not page["reachable"]:
        dns["expected"] = True
        dns["note"] = (
            "Expected with the DNS rewrite: port 80 on the same address is blocked, so the fence works and "
            "this lookup went to a public resolver."
        )
    else:
        dns["note"] = (
            "Can also mean the DNS rewrite is in place. Check the rewrite rule's packet counter as the docs show."
        )
