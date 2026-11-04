"""Activity: what each earner container does on the network, sampled on the worker.

Every 5 minutes, when the owner has switched it on for this worker, one
short-lived probe container per network namespace joins that namespace
(``network_mode=container:<id>``) and reads /proc/net: the socket tables a few
times over 8 seconds, and the TCP/UDP counters. It never reads traffic
contents. The probe is the worker's own image with the same floor as the
isolation check's probes (app/isolation_check.py): uid 65534, no capabilities,
read-only, no new privileges, removed on every path.

The worker keeps one window of counter state per namespace so the next round
can report how many connections were opened in between. Everything else goes
to the UI in the heartbeat and is forgotten here.
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from docker.errors import NotFound

from app import isolation_check, orchestrator, procnet

logger = logging.getLogger(__name__)

#: The probe runs procnet.py as ``python -c``; its ``__main__`` guard calls main().
ACTIVITY_SCRIPT = Path(procnet.__file__).read_text(encoding="utf-8")

PROBE_LABEL = isolation_check.PROBE_LABEL
PROBE_KIND = "activity"
PROBE_PREFIX = "cashpilot-activity-probe-"
#: Seconds one probe may run: 5 snapshots 2 s apart is about 8 s.
PROBE_TIMEOUT = 30
PROBE_SNAPSHOTS = 5
PROBE_GAP = 2
#: Probes in flight at once, and the wall-clock budget for one round.
MAX_PARALLEL = 4
ROUND_BUDGET = 200
#: Window length; rounds start on these wall-clock boundaries.
WINDOW_SECONDS = 300

#: Payload caps, so a proxy earner holding hundreds of sockets cannot grow the heartbeat.
MAX_SAMPLES = 64
MAX_DESTINATIONS = 400
MAX_BYTES = 128 * 1024

#: Containers that are CashPilot itself, never sampled.
SELF_NAMES = ("cashpilot-ui", "cashpilot-worker")
#: Runtimes whose namespace a probe can join and whose /proc/net is the kernel's.
PLAIN_RUNTIMES = ("", "runc", "io.containerd.runc.v2", "crun")
#: Runtime binaries that share the kernel's network stack: runc, crun, and the
#: runc-compatible ones (NVIDIA's wrapper around runc, youki).
PLAIN_BINARIES = ("runc", "crun", "nvidia-container-runtime", "youki")
#: A counter change over a longer gap than this is not one window's worth: no delta.
MAX_DELTA_SECONDS = 2 * 300

_lock = threading.Lock()
#: owner container id -> (netns id, snmp at the end of the last probe, monotonic time).
_prev: dict[str, tuple[str, dict[str, Any], float]] = {}


def reset() -> None:
    """Forget the counter state, so a re-enabled worker never reports a stale delta."""
    _prev.clear()


def _client() -> Any:
    return isolation_check._client()


def _remove(container: Any) -> bool:
    try:
        container.remove(force=True, v=True)
    except NotFound:
        pass
    except Exception as exc:  # noqa: BLE001 - reported as a leftover, never raised
        logger.warning("Could not remove activity probe %s: %s", getattr(container, "name", "?"), type(exc).__name__)
        return False
    return True


def sweep(client: Any) -> list[str]:
    """Remove every activity probe still on this host. Returns the ones Docker kept."""
    left = []
    try:
        found = client.containers.list(all=True, filters={"label": f"{PROBE_LABEL}={PROBE_KIND}"})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not list activity probes: %s", type(exc).__name__)
        return left
    for c in found:
        if not _remove(c):
            left.append(str(getattr(c, "name", "") or ""))
    return left


def probe_name(owner_id: str) -> str:
    return PROBE_PREFIX + owner_id[:12]


def probe_kwargs(image: str, owner_id: str) -> dict[str, Any]:
    """The containers.run arguments of one probe: the isolation probe's floor, and lower."""
    return {
        "image": image,
        "name": probe_name(owner_id),
        "entrypoint": ["python", "-c", ACTIVITY_SCRIPT],
        "environment": {"PROBE_SNAPSHOTS": str(PROBE_SNAPSHOTS), "PROBE_GAP": str(PROBE_GAP)},
        "network_mode": f"container:{owner_id}",
        "user": "65534:65534",
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "privileged": False,
        "pids_limit": 32,
        "mem_limit": "48m",
        # The image declares VOLUME /data; a tmpfs there means no anonymous
        # volume is created at all, so none can leak.
        "tmpfs": {"/data": "size=64k"},
        "healthcheck": {"test": ["NONE"]},
        "labels": {PROBE_LABEL: PROBE_KIND},
        "detach": True,
    }


class ProbeFailed(RuntimeError):
    """A probe did not produce a reading. ``reason`` is a fixed code, never exception text."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def run_probe(client: Any, image: str, owner_id: str, leftovers: list[str]) -> dict[str, Any]:
    """Run one probe in ``owner_id``'s namespace and return what it printed.

    Removed on every path; a probe Docker would not remove goes in ``leftovers``.
    """
    name = probe_name(owner_id)
    with contextlib.suppress(Exception):
        _remove(client.containers.get(name))
    container = None
    try:
        try:
            container = client.containers.run(**probe_kwargs(image, owner_id))
        except Exception as exc:  # noqa: BLE001
            raise ProbeFailed("run_error") from exc
        try:
            status = container.wait(timeout=PROBE_TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            raise ProbeFailed("timeout" if "timeout" in type(exc).__name__.lower() else "wait_error") from exc
        if (status or {}).get("StatusCode") != 0:
            raise ProbeFailed("exit_nonzero")
        try:
            data = json.loads(container.logs(stdout=True, stderr=False))
        except Exception as exc:  # noqa: BLE001
            raise ProbeFailed("bad_output") from exc
        if not isinstance(data, dict) or data.get("v") != 1 or not isinstance(data.get("summary"), dict):
            raise ProbeFailed("bad_output")
        return data
    finally:
        target = container
        if target is None:
            with contextlib.suppress(Exception):
                target = client.containers.get(name)
        if target is not None and not _remove(target):
            leftovers.append(name)


def _attrs(c: Any) -> dict[str, Any]:
    return getattr(c, "attrs", None) or {}


def _host(c: Any) -> dict[str, Any]:
    return _attrs(c).get("HostConfig") or {}


def _configured_dns() -> list[str]:
    return [s.strip() for s in (orchestrator._CONTAINER_DNS or "").split(",") if s.strip()]


def _network_info(client: Any, net_id: str, earners: set[str]) -> tuple[str, list[str]]:
    """(driver, addresses of the earners on it) of one network, from one inspect."""
    try:
        attrs = _attrs(client.networks.get(net_id))
    except Exception:  # noqa: BLE001 - an unknown driver reads as a bridge with no known earners
        return "", []
    ips = []
    for member in (attrs.get("Containers") or {}).values():
        member = member or {}
        if str(member.get("Name") or "") not in earners:
            continue
        for key in ("IPv4Address", "IPv6Address"):
            if member.get(key):
                ips.append(str(member[key]).split("/", 1)[0])
    return str(attrs.get("Driver") or ""), ips


def network_context(
    client: Any, owner: Any, networks: dict[str, tuple[str, list[str]]], earners: set[str] | None = None
) -> dict[str, Any]:
    """Gateways, resolvers, subnets and earner neighbours of the namespace owner, for procnet.classify.

    ``peers`` holds the owner's own addresses and those of the earners beside
    it. Any other container on the same bridge (on Docker's default bridge,
    every container the user runs) is a docker_peer, which alerts.
    """
    earners = set(_earner_names()) if earners is None else earners
    gateways, subnets, peers = set(), [], set()
    for net in ((_attrs(owner).get("NetworkSettings") or {}).get("Networks") or {}).values():
        net = net or {}
        net_id = str(net.get("NetworkID") or "")
        if net_id and net_id not in networks:
            networks[net_id] = _network_info(client, net_id, earners)
        driver, earner_ips = networks.get(net_id, ("", []))
        peers.update(earner_ips)
        for gw_key, ip_key, len_key in (
            ("Gateway", "IPAddress", "IPPrefixLen"),
            ("IPv6Gateway", "GlobalIPv6Address", "GlobalIPv6PrefixLen"),
        ):
            if net.get(gw_key):
                gateways.add(str(net[gw_key]))
            if net.get(ip_key):
                peers.add(str(net[ip_key]))
            if net.get(ip_key) and net.get(len_key):
                subnets.append((f"{net[ip_key]}/{net[len_key]}", driver))
    dns = list(_host(owner).get("Dns") or []) + _configured_dns()
    return {"gateways": sorted(gateways), "dns": dns, "subnets": subnets, "peers": sorted(peers)}


def _counters(snmp: Any) -> tuple[int, ...] | None:
    if not isinstance(snmp, dict) or not isinstance(snmp.get("tcp"), dict):
        return None
    tcp = snmp["tcp"]
    udp = snmp.get("udp") if isinstance(snmp.get("udp"), dict) else {}
    try:
        return (
            int(tcp["ActiveOpens"]),
            int(tcp["PassiveOpens"]),
            int(tcp["AttemptFails"]),
            int(tcp["EstabResets"]),
            int(udp.get("InDatagrams", -1)),
            int(udp.get("OutDatagrams", -1)),
        )
    except (KeyError, TypeError, ValueError):
        return None


DELTA_KEYS = ("opens", "passive_opens", "attempt_fails", "resets", "udp_in", "udp_out")


def deltas(owner_id: str, data: dict[str, Any], now: float) -> dict[str, Any]:
    """Counter changes since this namespace's last reading, or nulls.

    A delta exists only when the namespace is the same one (a recreated
    container gets a new one and its counters restart), no counter went
    backwards, and the last reading is at most MAX_DELTA_SECONDS old (after a
    skipped round or a switch-off, the change would cover far more than the
    window it is filed under). The state is replaced either way.
    """
    netns, end = data.get("netns"), data.get("snmp_end")
    prev = _prev.get(owner_id)
    out: dict[str, Any] = dict.fromkeys(DELTA_KEYS)
    out["delta_seconds"] = None
    cur = _counters(end)
    if prev and cur and netns and prev[0] == netns and 0 <= now - prev[2] <= MAX_DELTA_SECONDS:
        old = _counters(prev[1])
        if old and all(c >= o for c, o in zip(cur[:4], old[:4], strict=True)):
            for key, c, o in zip(DELTA_KEYS[:4], cur[:4], old[:4], strict=True):
                out[key] = c - o
            for key, c, o in zip(DELTA_KEYS[4:], cur[4:], old[4:], strict=True):
                out[key] = c - o if c >= 0 and o >= 0 and c >= o else None
            out["delta_seconds"] = round(now - prev[2], 1)
    if cur and netns:
        _prev[owner_id] = (str(netns), end, now)
    else:
        _prev.pop(owner_id, None)
    return out


def _sample_base(name: str, members: list[str], mode: str, status: str, reason: str = "") -> dict[str, Any]:
    base: dict[str, Any] = {
        "container": name,
        "members": members,
        "network_mode": mode,
        "status": status,
        "reason": reason,
    }
    base.update(dict.fromkeys(DELTA_KEYS))
    base.update(
        {
            "delta_seconds": None,
            "est_max": None,
            "syn_sent_max": None,
            "udp_bound": None,
            "listen_ports": [],
            "remotes_total": None,
            "truncated": False,
            "out": [],
            "in": [],
        }
    )
    return base


def _earner_names() -> list[str]:
    """Running earners the orchestrator already reports, labelled and external."""
    names = []
    for entry in orchestrator.get_status_cached():
        name = str(entry.get("name") or "")
        if name and entry.get("status") == "running" and name not in SELF_NAMES and name not in names:
            names.append(name)
    return names


def joinable_runtimes(client: Any) -> set[str]:
    """The runtimes whose containers keep their sockets in the kernel's network namespace.

    runc and crun do, under any registered name. gVisor (runsc) does only with
    ``--network=host``, where its sockets live in the container's namespace
    (verified on a gVisor host: the kernel's tables show the earner's
    connections). gVisor's own netstack and anything unknown keep them out of
    reach, and a probe would read an empty table: those are "sandboxed".
    """
    found = set(PLAIN_RUNTIMES)
    try:
        runtimes = (client.info() or {}).get("Runtimes") or {}
    except Exception:  # noqa: BLE001 - fall back to the names every Docker ships
        return found
    for name, spec in runtimes.items():
        spec = spec or {}
        binary = Path(str(spec.get("path") or name)).name
        args = [str(a) for a in spec.get("runtimeArgs") or []]
        if binary in PLAIN_BINARIES or (binary == "runsc" and "--network=host" in args):
            found.add(name)
    return found


def plan(
    client: Any, self_id: str | None, joinable: set[str] | None = None
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Group earners by the namespace they live in.

    Returns ({owner id: {"owner": container, "members": [names], "mode": str,
    "owner_earner": bool}}, [samples for earners that cannot be probed]).
    """
    joinable = set(PLAIN_RUNTIMES) if joinable is None else joinable
    groups: dict[str, dict[str, Any]] = {}
    fixed: list[dict[str, Any]] = []
    earners = _earner_names()
    for name in earners:
        try:
            c = client.containers.get(name)
        except Exception:  # noqa: BLE001 - gone since the status read
            continue
        labels = (_attrs(c).get("Config") or {}).get("Labels") or {}
        if PROBE_LABEL in labels or (self_id and c.id == self_id):
            continue
        host = _host(c)
        mode = str(host.get("NetworkMode") or "bridge")
        runtime = str(host.get("Runtime") or "")
        if mode == "host":
            fixed.append(_sample_base(name, [name], mode, "host_network"))
            continue
        if mode == "none":
            fixed.append(_sample_base(name, [name], mode, "no_network"))
            continue
        if runtime not in joinable:
            fixed.append(_sample_base(name, [name], mode, "sandboxed"))
            continue
        owner = c
        if mode.startswith("container:"):
            try:
                owner = client.containers.get(mode.split(":", 1)[1])
            except Exception:  # noqa: BLE001
                fixed.append(_sample_base(name, [name], mode, "probe_failed", "owner_missing"))
                continue
            if _host(owner).get("NetworkMode") == "host":
                fixed.append(_sample_base(name, [name], mode, "host_network"))
                continue
            if str(_host(owner).get("Runtime") or "") not in joinable:
                fixed.append(_sample_base(name, [name], mode, "sandboxed"))
                continue
        group = groups.setdefault(
            owner.id,
            {"owner": owner, "members": [], "mode": mode, "owner_earner": getattr(owner, "name", None) in earners},
        )
        group["members"].append(name)
        if owner.id == c.id:
            group["mode"] = mode
    return groups, fixed


def _dest_count(samples: list[dict[str, Any]]) -> int:
    return sum(len(s.get("out") or []) + len(s.get("in") or []) for s in samples)


def fit(window: dict[str, Any]) -> dict[str, Any]:
    """Enforce the payload caps: samples, destinations in total, serialised bytes.

    Above a cap the per-sample top-N is halved until the window fits; a sample
    that lost rows says ``truncated``.
    """
    samples = window["samples"]
    if len(samples) > MAX_SAMPLES:
        window["samples_dropped"] = len(samples) - MAX_SAMPLES
        del samples[MAX_SAMPLES:]
    cap_out, cap_in = 40, 20
    while cap_out > 0 and (
        _dest_count(samples) > MAX_DESTINATIONS or len(json.dumps(window, separators=(",", ":"))) > MAX_BYTES
    ):
        cap_out //= 2
        cap_in //= 2
        for s in samples:
            if len(s["out"]) > cap_out or len(s["in"]) > cap_in:
                s["truncated"] = True
                s["out"] = s["out"][:cap_out]
                s["in"] = s["in"][:cap_in]
    return window


def window_end(now: float | None = None) -> int:
    now = time.time() if now is None else now
    return int(now // WINDOW_SECONDS) * WINDOW_SECONDS


def _sample(name: str, group: dict[str, Any], data: dict[str, Any], ctx: dict[str, Any], now: float) -> dict[str, Any]:
    s = _sample_base(name, sorted(group["members"]), group["mode"], "ok")
    s.update(deltas(group["owner"].id, data, now))
    summary = data["summary"]
    for key in ("est_max", "syn_sent_max", "udp_bound", "remotes_total"):
        s[key] = summary.get(key)
    s["truncated"] = bool(summary.get("truncated"))
    s["listen_ports"] = list(summary.get("listen_ports") or [])[:20]
    if not group.get("owner_earner", True):
        # The namespace belongs to a non-earner (a VPN or Tailscale sidecar)
        # that other apps may share: its destinations are not the earner's to
        # report, so only the counters are kept, and no LAN alert can fire on
        # the sidecar's own traffic.
        s["reason"] = "shared_namespace"
        return s
    s["out"] = [
        [proto, ip, port, procnet.classify(ip, port, ctx), seen, states]
        for proto, ip, port, seen, states in summary.get("out") or []
    ]
    s["in"] = [[ip, lport, procnet.classify(ip, None, ctx), seen] for ip, lport, seen in summary.get("in") or []]
    return s


def run_round(now: float | None = None) -> dict[str, Any] | None:
    """One sampling round. None when another round is still running."""
    if not _lock.acquire(blocking=False):
        return None
    try:
        client = _client()
        try:
            return _round(client, time.time() if now is None else now)
        finally:
            with contextlib.suppress(Exception):
                client.close()
    finally:
        _lock.release()


def _round(client: Any, now: float) -> dict[str, Any]:
    leftovers = sweep(client)
    window: dict[str, Any] = {
        "v": 1,
        "window_end": window_end(now),
        "worker_status": "ok",
        "leftover_probes": leftovers,
        "samples": [],
    }
    me = orchestrator._self_container(client)
    image = (_attrs(me).get("Image") or None) if me is not None else None
    if not image:
        window["worker_status"] = "no_image"
        return window
    groups, fixed = plan(client, getattr(me, "id", None), joinable_runtimes(client))
    window["samples"].extend(fixed)

    deadline = time.monotonic() + ROUND_BUDGET
    networks: dict[str, tuple[str, list[str]]] = {}
    earners = set(_earner_names())

    def one(owner_id: str) -> dict[str, Any]:
        group = groups[owner_id]
        name = str(getattr(group["owner"], "name", "") or owner_id[:12])
        if time.monotonic() > deadline:
            return _sample_base(name, sorted(group["members"]), group["mode"], "skipped_budget")
        try:
            data = run_probe(client, image, owner_id, leftovers)
        except ProbeFailed as exc:
            _prev.pop(owner_id, None)
            return _sample_base(name, sorted(group["members"]), group["mode"], "probe_failed", exc.reason)
        ctx = network_context(client, group["owner"], networks, earners)
        return _sample(name, group, data, ctx, time.monotonic())

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        window["samples"].extend(pool.map(one, list(groups)))
    # Forget namespaces that are gone, so the state holds one window at most.
    for owner_id in list(_prev):
        if owner_id not in groups:
            _prev.pop(owner_id, None)
    window["samples"].sort(key=lambda s: s["container"])
    return fit(window)
