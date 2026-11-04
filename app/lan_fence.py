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
means the earners are offline, not exposed: with no NAT a packet from the
bridge reaches no internet host and no LAN machine that can answer. A reboot,
``nft flush ruleset`` or a firewalld reload therefore fails closed until the
worker writes the table again (at startup, before every deploy, every 300 s).

Modes (the state lives in Docker, so a lost /data changes nothing):

* ``operator``: CASHPILOT_CONTAINER_NETWORK is set. That network is used as
  before and nothing on the host is touched.
* ``off``: CASHPILOT_ISOLATION=off. Docker's default bridge, as before. If our
  network still exists, the table keeps only its masquerade, so earners still
  on it keep their internet until they are redeployed.
* ``on``: CASHPILOT_ISOLATION=on, or our labeled network exists, or no managed
  earner sits on the default bridge (a fresh install).
* ``legacy``: an upgraded install whose earners are on the default bridge.
  Nothing changes until the owner turns isolation on from the fleet page.

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

#: Seconds between checks that the table is still in place.
RECHECK_SECONDS = 300

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
FWD_EST_RULE = "forward-established"
IN_EST_RULE = "input-established"

#: Interfaces whose subnets are Docker's, ours or an overlay's, never the LAN.
_VIRTUAL_PREFIXES = ("docker", "br-", "veth", "cp-", "lo", "tailscale", "myst", "wg", "tun", "virbr")

#: The helper container's name and the label every probe of ours carries.
HELPER_NAME = "cashpilot-fence"
PROBE_LABEL = "cashpilot.probe"
HELPER_TIMEOUT = 20

_SETTING = os.getenv("CASHPILOT_ISOLATION", "auto").strip().lower() or "auto"
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


def rule_names(extra_subnets: list[str] | tuple[str, ...] = (), filtered: bool = True) -> set[str]:
    """The comment of every rule the table should hold. Each rule has its own."""
    names = {MASQ_RULE}
    if filtered:
        names |= {FWD_EST_RULE, IN_EST_RULE, HOST_RULE}
        names |= {name for name, _c, _s in BLOCKED}
        names |= {_connected_rule(c) for c in extra_subnets}
    return names


def render_nft(iface: str, subnet: str, extra_subnets: list[str] | tuple[str, ...] = (), filtered: bool = True) -> str:
    """The whole table, replaced atomically by one ``nft -f -``.

    Priority -150 runs before Docker's and Tailscale's filter chains, so the
    drops hold whatever order those are in. An ``accept`` here ends only this
    chain; a ``drop`` is final. ``filtered=False`` keeps only the masquerade:
    the way back out, where earners still on the bridge keep their internet.
    """
    ipaddress.ip_network(subnet)
    q = json.dumps(iface)
    lines = [
        f"table ip {TABLE}",
        f"delete table ip {TABLE}",
        f"table ip {TABLE} {{",
        "  chain postrouting {",
        "    type nat hook postrouting priority srcnat; policy accept;",
        f'    ip saddr {subnet} oifname != {q} counter masquerade comment "{MASQ_RULE}"',
        "  }",
    ]
    if filtered:
        lines += [
            "  chain forward {",
            "    type filter hook forward priority -150; policy accept;",
            f'    iifname {q} ct state established,related counter accept comment "{FWD_EST_RULE}"',
        ]
        for name, cidr, _s in BLOCKED:
            lines.append(f'    iifname {q} ip daddr {cidr} counter drop comment "{name}"')
        for cidr in extra_subnets:
            ipaddress.ip_network(cidr)
            lines.append(f'    iifname {q} ip daddr {cidr} counter drop comment "{_connected_rule(cidr)}"')
        lines += [
            "  }",
            "  chain input {",
            "    type filter hook input priority -150; policy accept;",
            f'    iifname {q} ct state established,related counter accept comment "{IN_EST_RULE}"',
            f'    iifname {q} counter drop comment "{HOST_RULE}"',
            "  }",
        ]
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_iptables(
    iface: str, subnet: str, extra_subnets: list[str] | tuple[str, ...] = (), filtered: bool = True
) -> str:
    """The same fence for kernels without nf_tables, as an idempotent sh script.

    Mangle chains (the slot that holds against Tailscale's ts-forward, see
    docs/isolation-check.md) and a nat chain for the masquerade. Each chain is
    flushed and rebuilt, and each jump is added only if missing.
    """
    ipaddress.ip_network(subnet)
    ipt = "iptables-legacy -w"
    out = ["set -e"]

    def chain(table: str, name: str, hook: str, match: str) -> None:
        out.append(f"{ipt} -t {table} -N {name} 2>/dev/null || true")
        out.append(f"{ipt} -t {table} -F {name}")
        out.append(
            f"{ipt} -t {table} -C {hook} {match} -j {name} 2>/dev/null || {ipt} -t {table} -I {hook} 1 {match} -j {name}"
        )

    def comment(name: str) -> str:
        return f"-m comment --comment {name}"

    chain("nat", "CP-POST", "POSTROUTING", f"-s {subnet}")
    out.append(f"{ipt} -t nat -A CP-POST ! -o {iface} {comment(MASQ_RULE)} -j MASQUERADE")
    chain("mangle", "CP-FWD", "FORWARD", f"-i {iface}")
    chain("mangle", "CP-IN", "INPUT", f"-i {iface}")
    if filtered:
        est = "-m conntrack --ctstate ESTABLISHED,RELATED"
        out.append(f"{ipt} -t mangle -A CP-FWD {est} {comment(FWD_EST_RULE)} -j RETURN")
        for name, cidr, _s in BLOCKED:
            out.append(f"{ipt} -t mangle -A CP-FWD -d {cidr} {comment(name)} -j DROP")
        for cidr in extra_subnets:
            ipaddress.ip_network(cidr)
            out.append(f"{ipt} -t mangle -A CP-FWD -d {cidr} {comment(_connected_rule(cidr))} -j DROP")
        out.append(f"{ipt} -t mangle -A CP-IN {est} {comment(IN_EST_RULE)} -j RETURN")
        out.append(f"{ipt} -t mangle -A CP-IN {comment(HOST_RULE)} -j DROP")
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
import json, os, subprocess, sys
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

def read(b):
    if b == "nft":
        rc, out, _ = sh(["nft", "list", "table", "ip", f.TABLE])
        return (f.parse_nft_counters(out) if rc == 0 else {}), rc == 0
    counters, present = {}, False
    for table, chain in (("nat", "CP-POST"), ("mangle", "CP-FWD"), ("mangle", "CP-IN")):
        rc, out, _ = sh(["iptables-legacy", "-w", "-t", table, "-L", chain, "-v", "-x", "-n"])
        if rc == 0:
            present = True
            counters.update(f.parse_iptables_counters(out))
    return counters, present

action = sys.argv[1]
iface = os.environ["FENCE_IFACE"]
subnet = os.environ["FENCE_SUBNET"]
filtered = os.environ.get("FENCE_FILTER", "1") == "1"
try:
    with open("/proc/net/route") as fh:
        extras = f.connected_subnets(fh.read())
except OSError:
    extras = []
b = backend(os.environ.get("FENCE_BACKEND", "auto"))
expected = f.rule_names(extras, filtered)
counters, present = read(b)
out = {"backend": b, "ok": True, "changed": False, "error": "", "extra_subnets": extras}
if action == "apply" and set(counters) != expected:
    if b == "nft":
        rc, _o, err = sh(["nft", "-f", "-"], f.render_nft(iface, subnet, extras, filtered))
    else:
        rc, _o, err = sh(["sh", "-c", f.render_iptables(iface, subnet, extras, filtered)])
    out["changed"] = True
    if rc != 0:
        out["ok"] = False
        out["error"] = (err or "exit status %d" % rc)[:400]
    counters, present = read(b)
out["present"] = present
out["counters"] = counters
out["matches"] = set(counters) == expected
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
}


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


def resolve_mode(client: Any) -> str:
    if _orchestrator()._CONTAINER_NETWORK:
        return MODE_OPERATOR
    chosen = setting()
    if chosen == "off":
        return MODE_OFF
    if chosen == "on" or managed_network(client) is not None:
        return MODE_ON
    return MODE_LEGACY if default_bridge_earners(client) else MODE_ON


def ensure_network(client: Any) -> Any:
    """Our network, created when missing. Raises IsolationConflict."""
    from docker.errors import NotFound

    net = managed_network(client)
    if net is not None:
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


def _remove_helper(client: Any) -> None:
    from docker.errors import NotFound

    try:
        client.containers.get(HELPER_NAME).remove(force=True, v=True)
    except NotFound:
        pass
    except Exception as exc:  # noqa: BLE001 - logged; the next run removes it by name first
        logger.warning("Could not remove %s: %s", HELPER_NAME, exc)


def run_helper(client: Any, action: str, subnet: str, filtered: bool = True) -> dict[str, Any]:
    """Run the helper to completion and return what it printed. Removed on every path."""
    with _lock:
        _remove_helper(client)
        try:
            container = client.containers.run(
                image=_helper_image(client),
                name=HELPER_NAME,
                entrypoint=["python", "-c", HELPER_SCRIPT],
                command=[action],
                environment={
                    "FENCE_IFACE": BRIDGE_INTERFACE,
                    "FENCE_SUBNET": subnet,
                    "FENCE_FILTER": "1" if filtered else "0",
                    "FENCE_BACKEND": _BACKEND,
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
                detach=True,
            )
            status = container.wait(timeout=HELPER_TIMEOUT)
            text = container.logs(stdout=True, stderr=False).decode(errors="replace").strip()
            if (status or {}).get("StatusCode") != 0:
                err = container.logs(stdout=False, stderr=True).decode(errors="replace").strip()
                raise RuntimeError(
                    f"the fence helper exited with status {(status or {}).get('StatusCode')}: {err[-300:]}"
                )
            return json.loads(text.splitlines()[-1])
        finally:
            _remove_helper(client)


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
    return result


def read_fence(client: Any) -> dict[str, Any] | None:
    """The table's per-rule counters, or None when our network does not exist."""
    net = managed_network(client)
    if net is None:
        return None
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
    mode = resolve_mode(client)
    _state["mode"] = mode
    if mode != MODE_ON:
        return None
    try:
        apply_fence(client)
    except (RuntimeError, IsolationConflict) as exc:
        raise orch.ContainerNetworkError(f"{exc} The running container was not touched. {_off_hint()}") from None
    _state["network"] = NETWORK_NAME
    return NETWORK_NAME


def effective_network(client: Any) -> tuple[str, str]:
    """(mode, the network earners should be on, or "" for the default bridge)."""
    mode = resolve_mode(client)
    if mode == MODE_OPERATOR:
        return mode, _orchestrator()._CONTAINER_NETWORK
    if mode == MODE_ON:
        return mode, NETWORK_NAME
    return mode, ""


def _outside(client: Any, network: str) -> list[str]:
    from app.constants import LABEL_SERVICE

    found = []
    for c in _managed(client):
        attrs = c.attrs or {}
        mode = str((attrs.get("HostConfig") or {}).get("NetworkMode") or "bridge")
        if mode in ("host", "none") or mode.startswith("container:"):
            continue
        nets = set(((attrs.get("NetworkSettings") or {}).get("Networks") or {}).keys())
        if network not in nets:
            found.append(str((c.labels or {}).get(LABEL_SERVICE) or c.name))
    return sorted(set(found))


def reconcile() -> dict[str, Any]:
    """Startup and every RECHECK_SECONDS: put the fence back if it went, refresh the status.

    Never raises: a failure is recorded in the status, which the heartbeat
    carries to the fleet page.
    """
    orch = _orchestrator()
    if not orch.docker_available():
        _state.update(mode=None, network=None, earners_outside=[])
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
        elif mode == MODE_OFF and managed_network(client) is not None:
            try:
                reduce_fence(client)
            except Exception as exc:  # noqa: BLE001 - recorded in the status
                _set_fence("failed", error=str(exc))
        else:
            _set_fence("n/a")
        if mode == MODE_LEGACY:
            _state["earners_outside"] = _labels_or_names(default_bridge_earners(client))
        elif mode in (MODE_ON, MODE_OPERATOR):
            _state["earners_outside"] = _outside(client, _state["network"])
        else:
            _state["earners_outside"] = []
    except Exception as exc:  # noqa: BLE001 - recorded, never raised
        logger.warning("LAN fence check failed: %s", exc)
        _set_fence("failed", error=str(exc))
    return status()


def refresh_outside() -> None:
    """Recount the earners outside the fence after a deploy or a removal. Never raises.

    Without it the fleet page kept naming a moved earner as exposed until the
    next five-minute check.
    """
    with contextlib.suppress(Exception):
        client = _orchestrator()._get_client()
        mode = _state["mode"]
        if mode == MODE_LEGACY:
            _state["earners_outside"] = _labels_or_names(default_bridge_earners(client))
        elif mode in (MODE_ON, MODE_OPERATOR) and _state["network"]:
            _state["earners_outside"] = _outside(client, _state["network"])


def _labels_or_names(containers: list[Any]) -> list[str]:
    from app.constants import LABEL_SERVICE

    return sorted({str((c.labels or {}).get(LABEL_SERVICE) or c.name) for c in containers})


def enable() -> dict[str, Any]:
    """Turn isolation on for an upgraded worker. Returns the status and the earners to move.

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
    apply_fence(client)
    _state["mode"] = MODE_ON
    _state["network"] = NETWORK_NAME
    _state["earners_outside"] = _outside(client, NETWORK_NAME)
    return status()


def status() -> dict[str, Any]:
    """What the heartbeat reports. A copy of the cached state; no Docker call."""
    return {
        "mode": _state["mode"],
        "network": _state["network"],
        "fence": dict(_state["fence"]),
        "earners_outside": list(_state["earners_outside"]),
    }


def gateway(client: Any) -> str | None:
    """Our bridge's gateway address: the host as an earner sees it."""
    net = managed_network(client)
    return _gateway(net) if net is not None else None
