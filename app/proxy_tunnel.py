"""Proxied copies of a service: earners that can only leave through a proxy.

Runs inside the worker. Every copy through one proxy on this worker shares one
tunnel:

* a **tunnel** container from our own pinned image (Dockerfile.tunnel), one per
  proxy on this worker (``cashpilot-tunnel-p<id>``). Its entrypoint drops every
  packet that is not tunnel traffic before it starts the tunnel, so the proxy
  is the only way out of its network namespace;
* one **earner** per copy, created with ``network_mode=container:<tunnel>``.
  It has no interface of its own. If the proxy, the tunnel process or the
  tunnel container dies, it has nowhere to send a packet.

Copies through one proxy already share its exit IP, so they gain nothing from a
tunnel each, and a tunnel costs more memory than most earners (tailscaled holds
about 20 MB of heap whatever the traffic). Workers older than this ran one
tunnel per copy (``cashpilot-tunnel-<slug>-p<id>``); those "legacy" pairs keep
working, and ``migrate_legacy`` moves them into the shared tunnel. An earner's
tunnel is always the container its NetworkMode names, never a name lookup.

A copy the owner (or the cap) stopped is written down in ``HELD_MARKER``: its
tunnel may stay up for the other copies, so a stopped earner beside a ready
tunnel no longer means "stopped by a reboot or a crash", and the heartbeat
must not start it.

docs/proxies.md explains the model and scripts/proxy_leak_test.sh proves the
fail-closed part against a real daemon.

Secrets: the proxy URL or Tailscale auth key goes into the sidecar as files in
an anonymous volume, written with put_archive between create and start. They
are never in a label, the environment or the command Docker records, so
``docker inspect`` shows only the mount. Nothing here logs a proxy spec, and
errors pass through ``redact`` before they leave this module.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import ipaddress
import json
import logging
import os
import re
import socket
import tarfile
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from docker.errors import APIError, NotFound
from docker.types import Mount

from app import orchestrator, version
from app.constants import (
    CONTAINER_PREFIX,
    LABEL_CATEGORY,
    LABEL_DEPLOYED_BY,
    LABEL_MANAGED,
    LABEL_PROXY,
    LABEL_ROLE,
    LABEL_SERVICE,
    ROLE_TUNNEL,
)

logger = logging.getLogger(__name__)

PROXY_KINDS = ("socks5", "http", "tailscale")

#: The worker's own tunnel image, the same release as the worker. A deploy
#: request can never choose it.
TUNNEL_REPOSITORY = "drumsergio/cashpilot-tunnel"
#: Seconds to wait for the sidecar to prove an exit through the tunnel.
READY_TIMEOUT = 45.0
SECRET_DIR = "/run/cashpilot-secret"
_FLOATING_TAGS = {"", "latest", "stable", "edge", "main", "master"}
#: A redeploy starts the new sidecar under its tunnel name plus this suffix, next
#: to the copy that runs now, and gives it the final name only once the old pair
#: is gone. The heartbeat (status()) never reports a staged sidecar.
STAGED_SUFFIX = "-next"
#: An earner being moved into another tunnel keeps its container under its name
#: plus this suffix until its clone runs (see _clone_into), so a worker that dies
#: midway never leaves a copy with no container at all.
MOVING_SUFFIX = "-moving"
# deploy() swapping the old pair for the staged one, and status(), take turns: a
# heartbeat must not start an earner that is being removed, or read a half swap.
_swap_lock = threading.Lock()
# One operation per proxy at a time: the copies through a proxy share its
# tunnel, so a second deploy would take the first one's staged tunnel for a
# leftover, and a stop, start or removal that ran during a deploy could stop or
# remove the tunnel the deploy is putting a copy into.
_deploy_locks: dict[int, threading.Lock] = {}
_deploy_locks_guard = threading.Lock()
#: A staged sidecar older than this is a leftover: a deploy is past its ready
#: timeout by then. Younger ones may belong to a deploy still running.
STAGED_STALE_SECONDS = 300


def _deploy_lock(proxy_id: int) -> threading.Lock:
    with _deploy_locks_guard:
        return _deploy_locks.setdefault(int(proxy_id), threading.Lock())


#: The service label of a shared tunnel: it belongs to a proxy, not to a service.
SHARED_SLUG = "proxy-tunnel"

#: Earners the owner or the cap stopped, one container name per line. Their
#: tunnel may keep running for the other copies, so without this the heartbeat
#: would take a stopped earner beside a ready tunnel for one a reboot stopped,
#: and start it again.
HELD_MARKER = os.path.join(os.getenv("CASHPILOT_DATA_DIR", "/data"), ".proxied_held")
_held_lock = threading.Lock()


def held() -> set[str]:
    """The earners recorded as stopped. Raises OSError when the marker exists
    but cannot be read: an empty answer then would restart every stopped copy."""
    try:
        with open(HELD_MARKER, encoding="utf-8") as fh:
            return {line.strip() for line in fh if line.strip()}
    except FileNotFoundError:
        return set()


def _set_held(name: str, on: bool, *, strict: bool = False) -> None:
    """Record or clear a stop. ``strict`` raises when it cannot be done.

    A stop that is not recorded is undone by the next heartbeat, and a copy
    started while still recorded is never restarted after a reboot, so a stop
    and a start are both strict. A removal is not: its container is gone.
    """
    with _held_lock:
        try:
            names = held()
            if (name in names) == on:
                return
            names = names | {name} if on else names - {name}
            tmp = f"{HELD_MARKER}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write("".join(f"{n}\n" for n in sorted(names)))
            os.replace(tmp, HELD_MARKER)
        except OSError as exc:
            if strict:
                what = "was stopped" if on else "is no longer stopped"
                raise ProxyTunnelError(f"Could not record that {name} {what} ({exc}); it was left as it was") from None
            logger.warning("Could not clear the stop of %s: %s", name, exc)


def _age_seconds(container: Any) -> float:
    """Seconds since the container was created; 0 when Docker does not say."""
    raw = str((getattr(container, "attrs", None) or {}).get("Created") or "")
    try:
        created = datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", raw).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return (datetime.now(UTC) - created).total_seconds()


class ProxyTunnelError(RuntimeError):
    """A proxied copy could not be set up; the message is safe to show."""

    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


def tunnel_image() -> str:
    """The pinned tunnel image this worker uses.

    ``CASHPILOT_TUNNEL_IMAGE`` lets an operator (or a test rig) point at a
    mirror, but only with an exact tag or a digest: a floating tag would let
    the image change under a running worker.
    """
    override = (os.getenv("CASHPILOT_TUNNEL_IMAGE") or "").strip()
    if override:
        if "@sha256:" in override:
            return override
        tag = override.rsplit(":", 1)[1] if ":" in override.rsplit("/", 1)[-1] else ""
        if tag.lower() in _FLOATING_TAGS:
            raise ProxyTunnelError(
                f"CASHPILOT_TUNNEL_IMAGE is {override!r}; give it an exact version tag or a digest, never a "
                f"floating tag."
            )
        return override
    current = version.current()
    # An unversioned build reports "dev", or "latest" when it was dispatched
    # without a version; neither names a tunnel image anyone published.
    if current == version.UNKNOWN or current.lower().removeprefix("v") in _FLOATING_TAGS:
        raise ProxyTunnelError(
            "This worker is a development build, so it has no released tunnel image to pin. Set "
            "CASHPILOT_TUNNEL_IMAGE to an exact tag or digest."
        )
    return f"{TUNNEL_REPOSITORY}:{current.removeprefix('v')}"


def tunnel_name(slug: str, proxy_id: int) -> str:
    """A legacy tunnel: one per copy, from workers older than the shared tunnel."""
    return f"{CONTAINER_PREFIX}tunnel-{slug}-p{proxy_id}"


def shared_tunnel_name(proxy_id: int) -> str:
    """The one tunnel every copy through ``proxy_id`` on this worker joins."""
    return f"{CONTAINER_PREFIX}tunnel-p{proxy_id}"


def shared_label(proxy_id: int) -> str:
    """What names the shared tunnel inside the tunnel (its tailnet host name)."""
    return f"p{proxy_id}"


def earner_name(slug: str, proxy_id: int) -> str:
    return f"{CONTAINER_PREFIX}{slug}-p{proxy_id}"


_URL_USERINFO = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s'\"]*@")


def redact(text: str, secrets: list[str] | tuple[str, ...] = ()) -> str:
    """Strip URL credentials and any known secret value from a message."""
    out = _URL_USERINFO.sub(r"\1", str(text))
    for secret in secrets:
        if secret:
            out = out.replace(secret, "***")
            out = out.replace(quote(secret, safe=""), "***")
    return out


def resolve_proxy_ip(host: str) -> str:
    """The proxy's IPv4 address, resolved here so the sidecar does no DNS before the tunnel is up."""
    try:
        return str(ipaddress.IPv4Address(host))
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise ProxyTunnelError(f"Cannot resolve the proxy host {host!r} from this worker: {exc}") from None
    for info in infos:
        return str(info[4][0])
    raise ProxyTunnelError(f"The proxy host {host!r} has no IPv4 address")


#: Every file cp-tunnel reads. A rewrite writes them all, the ones the new
#: settings do not use as empty files, so nothing of the old settings (a login
#: server, a host) is left for cp-tunnel to pick up.
SECRET_KEYS = (
    "kind",
    "own_ip",
    "auth_key",
    "exit_node",
    "hostname",
    "login_server",
    "proxy_host",
    "proxy_ip",
    "proxy_port",
    "proxy_scheme",
    "proxy_auth",
    "settings",
)


def secret_files(proxy: dict[str, Any], own_ip: str | None, label: str) -> dict[str, str]:
    """The files written into the sidecar's secret volume, one value per file.

    ``settings`` is a digest of everything but ``own_ip``, so a start can tell
    whether the proxy was edited since the tunnel last read its files.
    """
    return _with_digest(_secret_files(proxy, own_ip, label))


def _with_digest(files: dict[str, str]) -> dict[str, str]:
    files = {k: v for k, v in files.items() if k != "settings"}
    digest_of = {k: v for k, v in files.items() if k not in ("own_ip", "proxy_ip") and v != ""}
    files["settings"] = hashlib.sha256(json.dumps(digest_of, sort_keys=True).encode()).hexdigest()
    return files


def _ts_hostname(label: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", f"cashpilot-{label}".lower())[:63]


def _secret_files(proxy: dict[str, Any], own_ip: str | None, label: str) -> dict[str, str]:
    kind = proxy.get("kind")
    if kind not in PROXY_KINDS:
        raise ProxyTunnelError(f"Unknown proxy type {kind!r}", status_code=400)
    files = {"kind": kind, "own_ip": own_ip or ""}
    if kind == "tailscale":
        if not proxy.get("auth_key") or not proxy.get("exit_node"):
            raise ProxyTunnelError("A Tailscale proxy needs an auth key and an exit node", status_code=400)
        files["auth_key"] = str(proxy["auth_key"])
        files["exit_node"] = str(proxy["exit_node"])
        files["hostname"] = _ts_hostname(label)
        if proxy.get("login_server"):
            files["login_server"] = str(proxy["login_server"])
        return files
    host = str(proxy.get("host") or "").strip()
    port = int(proxy.get("port") or 0)
    if not host or not 1 <= port <= 65535:
        raise ProxyTunnelError("A proxy needs a host and a port between 1 and 65535", status_code=400)
    files["proxy_host"] = host
    files["proxy_ip"] = resolve_proxy_ip(host)
    files["proxy_port"] = str(port)
    # tun2proxy dials the address resolved above, so the sidecar never needs DNS
    # outside the tunnel. The URL is put together in cp-tunnel from these parts,
    # so a start can swap in a fresh address without the credentials.
    files["proxy_scheme"] = "socks5" if kind == "socks5" else "http"
    files["proxy_auth"] = proxy_auth(str(proxy.get("username") or ""), str(proxy.get("password") or ""))
    return files


def proxy_auth(username: str, password: str) -> str:
    """The ``user:password@`` part of the proxy URL, percent-encoded, or empty."""
    if not (username or password):
        return ""
    return f"{quote(username, safe='')}:{quote(password, safe='')}@"


def _read_secret_file(container: Any, name: str) -> str | None:
    """One file of a sidecar's secret volume; works on a stopped container."""
    try:
        stream, _ = container.get_archive(f"{SECRET_DIR}/{name}")
        with tarfile.open(fileobj=io.BytesIO(b"".join(stream))) as tar:
            member = tar.next()
            handle = tar.extractfile(member) if member is not None else None
            return handle.read().decode().strip() if handle is not None else None
    except Exception:  # noqa: BLE001 - absent or unreadable: nothing to refresh
        return None


def refresh_proxy_ip(container: Any) -> None:
    """Resolve the proxy host again before a start, so a provider that moved its
    gateway to a new address does not leave the copy dialing the old one.

    A host that no longer resolves stops the start: the old address may belong
    to someone else by now, and cp-tunnel would hand it the proxy login."""
    host = _read_secret_file(container, "proxy_host")
    if not host:
        return
    fresh = resolve_proxy_ip(host)
    if fresh != _read_secret_file(container, "proxy_ip"):
        container.put_archive(SECRET_DIR, _secret_tar({"proxy_ip": fresh}))
        logger.info("The proxy of %s moved to a new address; the tunnel will use it", container.name)


def _secret_tar(files: dict[str, str]) -> bytes:
    """A tar of the files, owned by root and readable by root only.

    Root in the sidecar has no CAP_DAC_OVERRIDE, so the files must be owned by
    uid 0 to be readable at all.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, value in files.items():
            data = value.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o400
            info.uid = info.gid = 0
            info.mtime = int(time.time())
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _secret_values(proxy: dict[str, Any]) -> list[str]:
    return [str(proxy.get(k) or "") for k in ("password", "auth_key", "username")]


#: The service label of a throwaway Test tunnel.
TEST_SLUG = "proxy-test"


def secret_mount() -> Mount:
    """The tunnel's settings volume: anonymous, removed with the tunnel."""
    return Mount(SECRET_DIR, None, type="volume")


def sidecar_kwargs(name: str, slug: str, proxy_id: int | None, network: str | None, hostname: str) -> dict[str, Any]:
    """Everything the sidecar is created with. No secret appears here.

    A Test tunnel (no proxy id) gets no restart policy: one left behind by a
    worker that died during the test must not come back with every daemon
    restart, holding the proxy login. sweep_test_tunnels removes it.
    """
    labels = {
        LABEL_MANAGED: "true",
        LABEL_ROLE: ROLE_TUNNEL,
        LABEL_SERVICE: slug,
        LABEL_DEPLOYED_BY: "worker",
    }
    if proxy_id is not None:
        labels[LABEL_PROXY] = str(proxy_id)
    return {
        "image": tunnel_image(),
        "name": name,
        "labels": labels,
        "network": network,
        # The isolated bridge's resolvers, as every earner on it gets them: its
        # rules refuse the daemon's LAN resolver. None on the default bridge.
        "dns": orchestrator.container_dns(network),
        "hostname": hostname,
        "cap_drop": ["ALL"],
        "cap_add": ["NET_ADMIN"],
        "devices": ["/dev/net/tun"],
        "privileged": False,
        "security_opt": ["no-new-privileges:true"],
        "pids_limit": 64,
        "read_only": True,
        "tmpfs": {"/run": "size=8m,mode=0755"},
        # An anonymous volume as a Mount, never as volumes=[SECRET_DIR]: docker-py
        # writes that as a Binds entry with no source, and Docker 29 brings such
        # a container back from a daemon restart as "get: no such volume", for
        # good. The Mount form comes back with its files.
        "mounts": [secret_mount()],
        "init": True,
        "sysctls": {
            "net.ipv6.conf.all.disable_ipv6": "1",
            "net.ipv6.conf.default.disable_ipv6": "1",
            # DNS sent to Docker's resolver is redirected into the tunnel and
            # keeps a loopback source until it is rewritten; see cp-tunnel.
            "net.ipv4.conf.all.route_localnet": "1",
        },
        "restart_policy": {"Name": "unless-stopped" if proxy_id is not None else "no"},
        # tun2proxy runs at warn, so this log holds errors, never the sites the
        # earner reaches; the bound keeps even a noisy failure off the box disk.
        "log_config": {"type": "json-file", "config": {"max-size": "1m", "max-file": "2"}},
        "detach": True,
    }


def _wait_ready(container: Any, timeout: float = READY_TIMEOUT) -> dict[str, Any]:
    """Wait for /run/ready; returns the probe result {"ip", "country"}."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        container.reload()
        if container.status not in ("running", "created", "restarting"):
            break
        if container.status == "running":
            code, out = container.exec_run(["cat", "/run/ready"], demux=False)
            if code == 0 and out:
                try:
                    result = json.loads(out.decode().strip().splitlines()[-1])
                except (ValueError, IndexError):
                    result = None
                if isinstance(result, dict) and _is_ip(result.get("ip")):
                    return {"ip": str(result["ip"]), "country": str(result.get("country") or "")}
        time.sleep(1)
    tail = ""
    with contextlib.suppress(Exception):  # the log is only a hint
        raw = container.logs(tail=5)
        tail = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    reason = " ".join(tail.split())[-300:]
    raise ProxyTunnelError(
        "The tunnel did not reach the internet through the proxy within "
        f"{int(timeout)} s, so nothing was started behind it." + (f" Tunnel log: {reason}" if reason else "")
    )


def _is_ip(value: Any) -> bool:
    """cp-probe keeps only IP characters of what an echo site answered, so an
    error page can still come through as "e"; only a real address counts."""
    try:
        ipaddress.ip_address(str(value or ""))
    except ValueError:
        return False
    return True


def _remove_quietly(container: Any, stop_timeout: int = 10) -> None:
    # A failed stop is no reason to keep the container; the removal is what matters.
    with contextlib.suppress(Exception):
        container.stop(timeout=stop_timeout)
    with contextlib.suppress(NotFound):
        container.remove(force=True, v=True)


def _get(client: Any, name: str) -> Any | None:
    try:
        return client.containers.get(name)
    except NotFound:
        return None


#: Seconds a tunnel gets to stop before Docker kills it. The same value and
#: name as the logout-on-stop change, so the two meet without a conflict.
SIDECAR_STOP_SECONDS = 10


def start_sidecar(
    client: Any,
    name: str,
    slug: str,
    proxy_id: int | None,
    proxy: dict[str, Any] | None,
    own_ip: str | None,
    hostname: str | None = None,
    *,
    label: str | None = None,
    files: dict[str, str] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Create, provision and start a tunnel, then wait for its exit. Removed on any failure.

    ``label`` names the tunnel on the tailnet (``cashpilot-<label>``).
    ``files`` hands over settings already read from another tunnel (the
    migration of a legacy pair), instead of building them from ``proxy``.
    """
    network = orchestrator.container_network("bridge")
    if files is None:
        if label is None:
            label = f"{slug}-p{proxy_id}" if proxy_id is not None else slug
        files = secret_files(proxy or {}, own_ip, label)
    secrets = _secret_values(proxy or {}) + [files.get("auth_key", ""), files.get("proxy_auth", "")]
    image = tunnel_image()
    try:
        client.images.pull(image)
    except APIError as exc:
        logger.warning("Could not pull %s: %s (trying the local copy)", image, exc)
    kwargs = sidecar_kwargs(name, slug, proxy_id, network, hostname=hostname or _hostname(name))
    kwargs.pop("detach")
    container = client.containers.create(**kwargs)
    try:
        if not container.put_archive(SECRET_DIR, _secret_tar(files)):
            raise ProxyTunnelError("Could not hand the proxy settings to the tunnel container")
        container.start()
        exit_info = _wait_ready(container)
    except Exception as exc:
        _remove_quietly(container, 2)
        if isinstance(exc, ProxyTunnelError):
            raise ProxyTunnelError(redact(str(exc), secrets), exc.status_code) from None
        detail = orchestrator.proxy_refusal(exc) or str(exc)
        raise ProxyTunnelError(redact(f"The tunnel could not start: {detail}", secrets)) from None
    return container, exit_info


def _hostname(name: str) -> str:
    return name.removeprefix(CONTAINER_PREFIX)[:63]


# ---------------------------------------------------------------------------
# Who is whose: earners, shared tunnels and legacy tunnels
# ---------------------------------------------------------------------------


def _labels(container: Any | None) -> dict[str, str]:
    labels = getattr(container, "labels", None) if container is not None else None
    return labels if isinstance(labels, dict) else {}


def _is_ours(container: Any | None, slug: str, proxy_id: int) -> bool:
    """An earner of ``slug`` through ``proxy_id``, or that copy's legacy tunnel."""
    labels = _labels(container)
    return (
        labels.get(LABEL_MANAGED) == "true"
        and labels.get(LABEL_SERVICE) == slug
        and labels.get(LABEL_PROXY) == str(proxy_id)
    )


def _is_tunnel(container: Any | None, proxy_id: int | None = None) -> bool:
    labels = _labels(container)
    return (
        labels.get(LABEL_MANAGED) == "true"
        and labels.get(LABEL_ROLE) == ROLE_TUNNEL
        and LABEL_PROXY in labels
        and (proxy_id is None or labels.get(LABEL_PROXY) == str(proxy_id))
    )


def _is_shared(container: Any | None, proxy_id: int | None = None) -> bool:
    return _is_tunnel(container, proxy_id) and _labels(container).get(LABEL_SERVICE) == SHARED_SLUG


def _is_earner(container: Any | None) -> bool:
    labels = _labels(container)
    return labels.get(LABEL_MANAGED) == "true" and LABEL_PROXY in labels and labels.get(LABEL_ROLE) != ROLE_TUNNEL


def _tunnel_id_of(earner: Any) -> str:
    """The id of the container whose namespace the earner lives in, or ""."""
    mode = str(((getattr(earner, "attrs", None) or {}).get("HostConfig") or {}).get("NetworkMode") or "")
    return mode.removeprefix("container:") if mode.startswith("container:") else ""


def _image_of(container: Any) -> str:
    return str(((getattr(container, "attrs", None) or {}).get("Config") or {}).get("Image") or "")


def _members(client: Any, tunnel: Any) -> list[Any]:
    """Every earner (running or not) that lives in ``tunnel``'s namespace."""
    proxy_id = _labels(tunnel).get(LABEL_PROXY, "")
    found = client.containers.list(all=True, filters={"label": [f"{LABEL_MANAGED}=true", f"{LABEL_PROXY}={proxy_id}"]})
    return [c for c in found if _is_earner(c) and _tunnel_id_of(c) == tunnel.id]


def _tunnel_of(client: Any, earner: Any | None, slug: str, proxy_id: int) -> Any | None:
    """The earner's tunnel: the container its NetworkMode names, else the copy's legacy tunnel."""
    if earner is not None and (tid := _tunnel_id_of(earner)):
        found = _get(client, tid)
        if found is not None and _is_tunnel(found, proxy_id):
            return found
    legacy = _get(client, tunnel_name(slug, proxy_id))
    return legacy if _is_ours(legacy, slug, proxy_id) and _is_tunnel(legacy, proxy_id) else None


# ---------------------------------------------------------------------------
# The shared tunnel of a proxy, and moving earners into it
# ---------------------------------------------------------------------------


def _clone_into(client: Any, member: Any, tunnel: Any, *, start: bool | None = None) -> Any:
    """Recreate ``member`` inside ``tunnel``'s namespace, from what Docker recorded.

    A container's network namespace is fixed when it is created, so moving an
    earner to another tunnel means a new container. The worker rebuilds it from
    ``inspect``, so it needs neither the UI nor the catalog. ``start``
    defaults to whether the member was running.

    Nothing is removed before its replacement holds the name: the clone is
    created under a staged name, the member is renamed aside (MOVING_SUFFIX),
    the clone takes the name and starts, and only then is the member removed.
    A failure on the way puts the member back as it was. A worker that dies
    on the way leaves both, and recover_moves() finishes or undoes the move.
    """
    member.reload()
    attrs = member.attrs or {}
    cfg = attrs.get("Config") or {}
    hc = attrs.get("HostConfig") or {}
    name = str(member.name)
    service = _labels(member).get(LABEL_SERVICE)
    was_running = getattr(member, "status", "") in _LIVE
    staged = name + STAGED_SUFFIX
    aside = name + MOVING_SUFFIX
    for leftover_name in (staged, aside):
        if (leftover := _get(client, leftover_name)) is not None:
            if not (_is_earner(leftover) and _labels(leftover).get(LABEL_SERVICE) == service):
                raise ProxyTunnelError(f"A container named {leftover_name} that CashPilot did not create is in the way")
            _remove_quietly(leftover, 2)
    optional = {
        "entrypoint": cfg.get("Entrypoint"),
        "command": cfg.get("Cmd"),
        "user": cfg.get("User") or None,
        "working_dir": cfg.get("WorkingDir") or None,
        "stop_signal": cfg.get("StopSignal") or None,
        "stop_timeout": cfg.get("StopTimeout"),
        "runtime": hc.get("Runtime") or None,
        "init": hc.get("Init"),
        "pids_limit": hc.get("PidsLimit") or None,
        "mem_limit": hc.get("Memory") or None,
        "mem_reservation": hc.get("MemoryReservation") or None,
        "oom_score_adj": hc.get("OomScoreAdj") or None,
        "cpu_shares": hc.get("CpuShares") or None,
        "log_config": hc.get("LogConfig") or None,
    }
    clone = client.containers.create(
        image=cfg.get("Image") or _image_of(member),
        name=staged,
        environment=cfg.get("Env") or [],
        labels=dict(cfg.get("Labels") or _labels(member)),
        network_mode=f"container:{tunnel.id}",
        cap_drop=hc.get("CapDrop") or ["ALL"],
        cap_add=hc.get("CapAdd") or None,
        security_opt=hc.get("SecurityOpt") or ["no-new-privileges:true"],
        privileged=False,
        # Never started by Docker on its own: see orchestrator.deploy_raw.
        restart_policy={"Name": "no"},
        **{k: v for k, v in optional.items() if v is not None},
    )
    try:
        with contextlib.suppress(Exception):
            member.stop(timeout=orchestrator._get_stop_timeout(service or ""))
        member.rename(aside)
    except Exception:
        _remove_quietly(clone, 2)
        _put_back(member, name, was_running)
        raise
    try:
        clone.rename(name)
        if start if start is not None else was_running:
            clone.start()
    except Exception:
        _remove_quietly(clone, 2)
        _put_back(member, name, was_running)
        raise
    try:
        member.remove(force=True, v=True)
    except NotFound:
        pass
    except Exception as exc:  # noqa: BLE001 - a leftover only: recover_moves removes it
        logger.warning("Could not remove %s after it moved: %s", aside, exc)
    clone.reload()
    return clone


def _put_back(member: Any, name: str, was_running: bool) -> None:
    """Give a member whose move failed its name back, running if it ran."""
    with contextlib.suppress(Exception):
        member.reload()
        if str(member.name) != name:
            member.rename(name)
        if was_running and getattr(member, "status", "") not in _LIVE:
            member.start()


def _move_members(client: Any, old: Any, new: Any) -> None:
    """Every earner of ``old`` into ``new``. On a failure the ones moved go back."""
    moved: list[Any] = []
    try:
        for member in _members(client, old):
            moved.append(_clone_into(client, member, new))
    except Exception:
        with contextlib.suppress(Exception):
            old.reload()
        back_up = getattr(old, "status", "") == "running"
        for clone in moved:
            # Started again only where they can run: a tunnel Docker could not
            # start keeps them stopped, under their own names, for the next start.
            with contextlib.suppress(Exception):
                _clone_into(client, clone, old, start=back_up and getattr(clone, "status", "") in _LIVE)
        raise


def _shared_ready(client: Any, proxy_id: int) -> tuple[Any, dict[str, Any]] | None:
    """The proxy's shared tunnel when it runs and has written /run/ready."""
    current = _get(client, shared_tunnel_name(proxy_id))
    if not _is_shared(current, proxy_id) or getattr(current, "status", "") != "running":
        return None
    exit_info = _read_exit(current)
    return (current, exit_info) if exit_info is not None else None


def _ensure_tunnel(
    client: Any,
    proxy_id: int,
    proxy: dict[str, Any] | None,
    own_ip: str | None,
    *,
    files: dict[str, str] | None = None,
    upgrade: bool = False,
) -> tuple[Any, dict[str, Any]]:
    """The proxy's shared tunnel, running on the given settings and ready.

    Its earners are never recreated for a settings change. A container's state
    lives in its writable layer (proxied copies have no volumes), and several
    earners keep their device id there, so a recreated copy is a new device to
    its provider. So:

    * running on the same settings: used as it is; restarted in place when it
      has no exit;
    * running on other settings: the new settings first prove an exit in a
      throwaway Test tunnel, which costs the running copies nothing when it
      fails. Then they are written into this tunnel, which restarts in place;
    * stopped: the settings are written over and it starts in place.

    In place means the same container id, so every earner keeps its
    NetworkMode and is restarted into the new namespace (here, by the caller
    or by the heartbeat). A new tunnel image does not replace a tunnel that
    copies live in; ``upgrade`` (a deploy with no other copy in it) does.

    A new tunnel under a staged name, with every earner recreated inside it,
    is the way only when there is none yet, for an upgrade, or when Docker
    cannot start this one at all (its container is broken).
    """
    label = shared_label(proxy_id)
    if files is None:
        try:
            files = secret_files(proxy or {}, own_ip, label)
        except ProxyTunnelError as exc:
            raise ProxyTunnelError(redact(str(exc), _secret_values(proxy or {})), exc.status_code) from None
    secrets = _secret_values(proxy or {}) + [files.get("auth_key", ""), files.get("proxy_auth", "")]
    image = tunnel_image()
    final = shared_tunnel_name(proxy_id)
    staged = final + STAGED_SUFFIX
    current = _get(client, final)
    if current is not None and not _is_shared(current, proxy_id):
        raise ProxyTunnelError(f"A container named {final} that CashPilot did not create is in the way")
    leftover = _get(client, staged)
    if _is_shared(leftover, proxy_id) and _age_seconds(leftover) >= STAGED_STALE_SECONDS and _members(client, leftover):
        # A change that died after it began moving copies: finish it first.
        with _swap_lock:
            current = _finish_staged(client, leftover, current, final)
    if current is not None and (_image_of(current) == image or not upgrade):
        try:
            return _in_place(client, current, proxy, own_ip, files, secrets)
        except _Broken as exc:
            logger.warning("The tunnel of proxy %s cannot start in place (%s); replacing it", proxy_id, exc)
    # Left by a deploy that died midway, on this name only if it is ours. A young
    # one can belong to a deploy another worker on this daemon is running.
    if (leftover := _get(client, staged)) is not None:
        if not _is_shared(leftover, proxy_id):
            raise ProxyTunnelError(f"A container named {staged} that CashPilot did not create is in the way")
        if _age_seconds(leftover) < STAGED_STALE_SECONDS:
            raise ProxyTunnelError(
                f"Another change to this proxy's tunnel started {int(_age_seconds(leftover))} s ago and may still "
                f"be running. Try again in a few minutes."
            )
        _remove_quietly(leftover, SIDECAR_STOP_SECONDS)
    new, exit_info = start_sidecar(
        client, staged, SHARED_SLUG, proxy_id, proxy, own_ip, hostname=_hostname(final), label=label, files=files
    )
    try:
        with _swap_lock:
            if current is not None:
                _move_members(client, current, new)
                _remove_quietly(current, SIDECAR_STOP_SECONDS)
            new.rename(final)
    except Exception:
        if not _members(client, new):
            _remove_quietly(new, SIDECAR_STOP_SECONDS)
        raise
    return new, exit_info


class _Broken(Exception):
    """Docker cannot write to or start this tunnel container at all."""


def _in_place(
    client: Any,
    current: Any,
    proxy: dict[str, Any] | None,
    own_ip: str | None,
    files: dict[str, str],
    secrets: list[str],
) -> tuple[Any, dict[str, Any]]:
    """Bring ``current`` up on ``files`` without replacing the container. See _ensure_tunnel.

    Raises _Broken when Docker refuses the container itself (a daemon restart
    can leave one that cannot start), so the caller replaces it.
    """
    current.reload()
    running = current.status == "running"
    if running and _read_secret_file(current, "settings") == files["settings"]:
        with contextlib.suppress(ProxyTunnelError):
            return current, _wait_ready(current)
        logger.warning("The tunnel %s runs but has no exit; restarting it", current.name)
        previous = None
    elif running:
        _prove(client, proxy, own_ip, files)
        previous = {key: _read_secret_file(current, key) or "" for key in SECRET_KEYS}
    else:
        previous = None
    try:
        if running:
            current.stop(timeout=SIDECAR_STOP_SECONDS)
        if not current.put_archive(SECRET_DIR, _secret_tar({key: files.get(key, "") for key in SECRET_KEYS})):
            raise _Broken("Docker did not take the settings files")
        current.start()
    except (APIError, _Broken) as exc:
        raise _Broken(redact(str(exc), secrets)) from None
    try:
        exit_info = _wait_ready(current)
    except ProxyTunnelError as exc:
        with contextlib.suppress(Exception):
            if previous is not None:
                # Proven a moment ago, failed here: back to what ran before.
                current.stop(timeout=SIDECAR_STOP_SECONDS)
                current.put_archive(SECRET_DIR, _secret_tar(previous))
                current.start()
            elif not running:
                # Down, not leaking: its earners have no way out. Stopped so it
                # does not hold a tailnet device or a proxy session for nothing.
                current.stop(timeout=SIDECAR_STOP_SECONDS)
        raise ProxyTunnelError(redact(str(exc), secrets), exc.status_code) from None
    _restart_members(client, current)
    return current, exit_info


def _prove(client: Any, proxy: dict[str, Any] | None, own_ip: str | None, files: dict[str, str]) -> None:
    """Start a throwaway Test tunnel on ``files`` and wait for its exit; it never stays."""
    trial = dict(files)
    if trial.get("kind") == "tailscale":
        trial["hostname"] = _ts_hostname(TEST_SLUG)
    name = f"{CONTAINER_PREFIX}tunnel-test-{uuid.uuid4().hex[:10]}"
    sidecar, _ = start_sidecar(client, name, TEST_SLUG, None, proxy, own_ip, files=trial)
    _remove_quietly(sidecar, 2)


def _restart_members(client: Any, tunnel: Any) -> None:
    """Restart the running, not held earners of a tunnel that restarted in place,
    so they join its new namespace now rather than at the next heartbeat."""
    try:
        stopped = held()
    except OSError as exc:
        logger.warning("Could not read which copies are stopped (%s); restarting none", exc)
        return
    for member in _members(client, tunnel):
        if str(member.name) in stopped or getattr(member, "status", "") not in _LIVE:
            continue
        try:
            member.restart(timeout=orchestrator._get_stop_timeout(_labels(member).get(LABEL_SERVICE, "")))
        except Exception as exc:  # noqa: BLE001 - the heartbeat tries again
            logger.warning("Could not restart %s into its tunnel: %s", member.name, exc)


def _moving(client: Any, proxy_id: str) -> list[str]:
    """Copies of a proxy that are half moved: aside or staged (see _clone_into)."""
    found = client.containers.list(all=True, filters={"label": [f"{LABEL_MANAGED}=true", f"{LABEL_PROXY}={proxy_id}"]})
    return [str(c.name) for c in found if _is_earner(c) and str(c.name).endswith((STAGED_SUFFIX, MOVING_SUFFIX))]


def _finish_staged(client: Any, staged: Any, current: Any | None, final: str) -> Any:
    """Finish a tunnel change a worker died in: the staged tunnel had proved its
    exit before any copy moved into it, so the copies left in ``current`` move
    across and it takes the final name. Returns the tunnel under ``final``.

    Refused while a copy of the proxy is still half moved: recover_moves must
    settle it first, or its container aside would be taken for a copy."""
    if half := _moving(client, _labels(staged).get(LABEL_PROXY, "")):
        raise ProxyTunnelError(
            f"{', '.join(sorted(half))} {'is' if len(half) == 1 else 'are'} still being moved into a new tunnel; "
            "the worker settles that within a few minutes. Try again then."
        )
    run = getattr(staged, "status", "") == "running"
    if current is not None:
        for member in _members(client, current):
            _clone_into(client, member, staged, start=run and getattr(member, "status", "") in _LIVE)
        _remove_quietly(current, SIDECAR_STOP_SECONDS)
    staged.rename(final)
    logger.info("Finished moving the copies of %s into its new tunnel", final)
    return staged


def _drop_if_empty(client: Any, tunnel: Any | None) -> list[str]:
    """Remove a shared tunnel, and its secret volume, once no earner lives in it."""
    if tunnel is None or not _is_shared(tunnel) or _members(client, tunnel):
        return []
    _remove_quietly(tunnel, SIDECAR_STOP_SECONDS)
    return [str(tunnel.name)]


# ---------------------------------------------------------------------------
# Deploy, stop, start, remove
# ---------------------------------------------------------------------------


def deploy(slug: str, proxy_id: int, earner: dict[str, Any], proxy: dict[str, Any], own_ip: str | None) -> dict:
    """Deploy (or replace) the proxied copy of ``slug`` through proxy ``proxy_id``.

    The proxy's shared tunnel is made ready first (see _ensure_tunnel): a
    second copy through a proxy that already has a ready tunnel on these
    settings creates only its earner and touches no other copy. Then the old
    earner of this copy goes (with its tunnel, when it is a legacy pair), and
    the new one is created inside the shared tunnel's namespace. A tunnel that
    cannot start therefore costs nothing.
    """
    with _deploy_lock(proxy_id):
        return _deploy(slug, proxy_id, earner, proxy, own_ip)


def _deploy(slug: str, proxy_id: int, earner: dict[str, Any], proxy: dict[str, Any], own_ip: str | None) -> dict:
    client = orchestrator._get_client()
    # Checked first: settings that cannot work (a host that does not resolve,
    # no tunnel image) fail fast, before a tunnel is created.
    secret_files(proxy, own_ip, shared_label(proxy_id))
    tunnel_image()
    name = earner_name(slug, proxy_id)
    # A new tunnel image is taken only when no other copy would be recreated
    # for it (see _ensure_tunnel): this copy's own earner is replaced anyway.
    current = _get(client, shared_tunnel_name(proxy_id))
    others = [m for m in _members(client, current) if str(m.name) != name] if _is_shared(current, proxy_id) else []
    tunnel, exit_info = _ensure_tunnel(client, proxy_id, proxy, own_ip, upgrade=not others)
    with _swap_lock:
        _remove(slug, proxy_id, drop_shared=False)
    try:
        container_id = orchestrator.deploy_raw(
            slug=slug,
            image=earner["image"],
            env=earner.get("env") or {},
            network_mode=f"container:{tunnel.id}",
            cap_add=earner.get("cap_add"),
            devices=earner.get("devices"),
            command=earner.get("command"),
            labels={**(earner.get("labels") or {}), LABEL_PROXY: str(proxy_id)},
            resources=earner.get("resources"),
            category=(earner.get("labels") or {}).get(LABEL_CATEGORY, "bandwidth"),
            name=name,
        )
    except Exception:
        _drop_if_empty(client, tunnel)
        raise
    _set_held(name, False, strict=True)
    return {"container_id": container_id, "tunnel_id": tunnel.id, "exit": exit_info}


_LIVE = ("running", "restarting")


def stop(slug: str, proxy_id: int) -> bool:
    """Stop one copy. Returns whether it was running.

    Docker answers a stop of a stopped container with success, so the cap asks
    this to tell a copy it stopped from one the owner had already stopped.

    The stop is written down first (HELD_MARKER), so a stop that fails halfway
    is never undone by the heartbeat. The shared tunnel stops too once no copy
    that should run is left in it. A legacy pair stops as before: tunnel first.
    """
    with _deploy_lock(proxy_id):
        return _stop(slug, proxy_id)


def _stop(slug: str, proxy_id: int) -> bool:
    client = orchestrator._get_client()
    name = earner_name(slug, proxy_id)
    earner = _get(client, name)
    earner = earner if _is_ours(earner, slug, proxy_id) else None
    tunnel = _tunnel_of(client, earner, slug, proxy_id)
    if earner is None and tunnel is None:
        raise ValueError(f"No proxied copy of {slug} through proxy {proxy_id} on this worker")
    try:
        was_held = name in held()
    except OSError as exc:
        raise ProxyTunnelError(f"Could not read which copies are stopped ({exc}); {name} was left as it was") from None
    tunnel_live = tunnel is not None and getattr(tunnel, "status", "") in _LIVE
    was_running = (earner is not None and getattr(earner, "status", "") in _LIVE) or (tunnel_live and not was_held)
    _set_held(name, True, strict=True)
    if tunnel is not None and not _is_shared(tunnel):
        tunnel.stop(timeout=SIDECAR_STOP_SECONDS)
        if earner is not None:
            earner.stop(timeout=orchestrator._get_stop_timeout(slug))
        return was_running
    if earner is not None:
        earner.stop(timeout=orchestrator._get_stop_timeout(slug))
    if tunnel is not None and tunnel_live:
        try:
            stopped = held()
        except OSError:
            return was_running  # the tunnel keeps running: safe, and the next stop tries again
        if not any(str(m.name) not in stopped for m in _members(client, tunnel)):
            tunnel.stop(timeout=SIDECAR_STOP_SECONDS)
    return was_running


def start(slug: str, proxy_id: int, proxy: dict[str, Any] | None = None, own_ip: str | None = None) -> dict[str, Any]:
    """Start one copy: its tunnel ready first, then the earner.

    ``proxy`` is the proxy as it is stored now, so an edit (a new password,
    port, auth key or exit node) reaches the tunnel on this start; see
    _ensure_tunnel for how a tunnel on other settings is replaced. A legacy
    pair is moved into the shared tunnel on the way. Without ``proxy`` (a UI
    older than this worker) the tunnel is only started, its proxy address
    looked up again.

    The earner is restarted rather than started when it is still running in a
    namespace the tunnel left behind.
    """
    with _deploy_lock(proxy_id):
        return _start(slug, proxy_id, proxy, own_ip)


def _start(slug: str, proxy_id: int, proxy: dict[str, Any] | None, own_ip: str | None) -> dict[str, Any]:
    client = orchestrator._get_client()
    name = earner_name(slug, proxy_id)
    earner = _get(client, name)
    if not _is_ours(earner, slug, proxy_id):
        raise ValueError(f"No proxied copy of {slug} through proxy {proxy_id} on this worker")
    tunnel = _tunnel_of(client, earner, slug, proxy_id)
    if tunnel is not None and not _is_shared(tunnel) and proxy is None:
        return _start_legacy(slug, earner, tunnel, name)
    if proxy is not None:
        shared, exit_info = _ensure_tunnel(client, proxy_id, proxy, own_ip)
        earner = _get(client, name)
        if earner is not None and _tunnel_id_of(earner) != shared.id:
            # A legacy pair, or a copy whose tunnel is gone: a namespace is
            # fixed at create, so its earner is recreated in the shared tunnel.
            # A legacy tunnel goes with it.
            with _swap_lock:
                _clone_into(client, earner, shared, start=False)
                if tunnel is not None and not _is_shared(tunnel):
                    _remove_quietly(tunnel, SIDECAR_STOP_SECONDS)
            earner = _get(client, name)
        if earner is None:
            raise ProxyTunnelError(f"{name} disappeared while its tunnel was replaced")
    else:
        if tunnel is None:
            raise ProxyTunnelError(
                f"The tunnel of {name} is gone. Start it from the dashboard of a current UI, or remove the copy "
                f"and add it again."
            )
        tunnel.reload()
        if tunnel.status != "running":
            refresh_proxy_ip(tunnel)
            tunnel.start()
        exit_info = _wait_ready(tunnel)
    _set_held(name, False, strict=True)
    earner.reload()
    if earner.status == "running":
        if earner_action(earner, shared if proxy is not None else tunnel, True) == "restart":
            earner.restart(timeout=orchestrator._get_stop_timeout(slug))
    else:
        earner.start()
    return {"exit": exit_info}


def _start_legacy(slug: str, earner: Any, sidecar: Any, name: str) -> dict[str, Any]:
    """A pair from an older worker, started by a UI that sends no settings."""
    sidecar.reload()
    if sidecar.status != "running":
        refresh_proxy_ip(sidecar)
    sidecar.start()
    exit_info = _wait_ready(sidecar)
    _set_held(name, False, strict=True)
    earner.reload()
    if earner.status == "running":
        earner.restart(timeout=orchestrator._get_stop_timeout(slug))
    else:
        earner.start()
    return {"exit": exit_info}


def remove(slug: str, proxy_id: int) -> list[str]:
    """Remove the earner; then its tunnel and the tunnel's secret volume, once no
    other copy lives in it."""
    with _deploy_lock(proxy_id):
        return _remove(slug, proxy_id)


def _remove(slug: str, proxy_id: int, *, drop_shared: bool = True) -> list[str]:
    client = orchestrator._get_client()
    removed: list[str] = []
    name = earner_name(slug, proxy_id)
    earner = _get(client, name)
    earner = earner if _is_ours(earner, slug, proxy_id) else None
    tunnel = _tunnel_of(client, earner, slug, proxy_id)
    if earner is not None:
        _remove_quietly(earner, orchestrator._get_stop_timeout(slug))
        removed.append(earner.name)
    # A legacy tunnel of this copy, even when the earner was already moved out.
    legacy = _get(client, tunnel_name(slug, proxy_id))
    for candidate in {id(t): t for t in (tunnel, legacy) if t is not None}.values():
        if _is_tunnel(candidate, proxy_id) and not _is_shared(candidate) and _is_ours(candidate, slug, proxy_id):
            _remove_quietly(candidate, SIDECAR_STOP_SECONDS)
            removed.append(candidate.name)
        elif drop_shared and _is_shared(candidate, proxy_id):
            removed += _drop_if_empty(client, candidate)
    _set_held(name, False)
    return removed


def remove_all(slug: str) -> list[str]:
    """Every proxied copy of ``slug``, its legacy tunnels, and each shared tunnel
    left with no copy, when the service is removed.

    One proxy at a time, under its lock, and listed again inside it: a move or
    a migration of that proxy (both under the same lock) cannot then create a
    copy beside the deletion."""
    client = orchestrator._get_client()

    def listing() -> list[Any]:
        return client.containers.list(
            all=True, filters={"label": [f"{LABEL_SERVICE}={slug}", f"{LABEL_MANAGED}=true", LABEL_PROXY]}
        )

    removed: list[str] = []
    left: list[str] = []
    for pid in sorted({_labels(c).get(LABEL_PROXY, "") for c in listing()}):
        with _deploy_lock(int(pid)) if pid.isdigit() else contextlib.nullcontext():
            found = [c for c in listing() if _labels(c).get(LABEL_PROXY, "") == pid]
            shared_ids = {tid for c in found if _is_earner(c) and (tid := _tunnel_id_of(c))}
            # Earners first, so no tunnel is removed under a running earner.
            found.sort(key=lambda c: _labels(c).get(LABEL_ROLE) == ROLE_TUNNEL)
            for container in found:
                _remove_quietly(container)
                try:
                    container.reload()
                except NotFound:
                    removed.append(container.name)
                    if _is_earner(container):
                        _set_held(str(container.name), False)
                else:
                    left.append(container.name)
            if pid.isdigit():
                for tid in sorted(shared_ids):
                    tunnel = _get(client, tid)
                    if _is_shared(tunnel, int(pid)):
                        removed += _drop_if_empty(client, tunnel)
    if left:
        # Said out loud, so the UI keeps the records of copies that still exist.
        raise ProxyTunnelError(f"Docker did not remove {', '.join(left)}", status_code=409)
    return removed


def sweep_test_tunnels() -> list[str]:
    """Remove Test tunnels a worker that stopped mid-test left behind, and staged
    tunnels of a deploy it stopped in.

    Run at worker start, when no test of this worker can be in flight.
    """
    client = orchestrator._get_client()
    found = client.containers.list(
        all=True,
        filters={"label": [f"{LABEL_MANAGED}=true", f"{LABEL_ROLE}={ROLE_TUNNEL}", f"{LABEL_SERVICE}={TEST_SLUG}"]},
    )
    swept: list[str] = []
    for container in found:
        if LABEL_PROXY in (container.labels or {}):
            continue
        _remove_quietly(container, 2)
        swept.append(container.name)
    # And staged tunnels of a deploy that died: they hold the proxy login, and
    # the heartbeat never reports them. Only stale ones, so a deploy another
    # worker on this daemon is running keeps its tunnel, and never one that
    # copies still live in.
    staged = client.containers.list(
        all=True, filters={"label": [f"{LABEL_MANAGED}=true", f"{LABEL_ROLE}={ROLE_TUNNEL}", LABEL_PROXY]}
    )
    for container in staged:
        if (
            str(container.name).endswith(STAGED_SUFFIX)
            and _age_seconds(container) >= STAGED_STALE_SECONDS
            and not _members(client, container)
        ):
            _remove_quietly(container, 2)
            swept.append(container.name)
    return swept


def recover_moves(min_age: float | None = None) -> list[str]:
    """Finish or undo moves a worker died in (see _clone_into). Returns what it did.

    Run at worker start and by the heartbeat. Per copy:

    * its container is aside (``<name>-moving``) and its clone already holds
      the name: the move finished; the aside one is removed;
    * aside, and the name is free: it gets its name back and the half-made
      clone goes, unless the tunnel it lived in is gone while the clone's
      exists, in which case the clone takes the name instead;
    * a clone (``<name>-next``) with no aside one: it takes the name when the
      name is free, or is removed as a leftover when the copy holds it.

    A clone younger than ``min_age`` (default STAGED_STALE_SECONDS) may belong
    to a move another worker on this daemon is making, and is left alone.
    """
    if min_age is None:
        min_age = STAGED_STALE_SECONDS
    client = orchestrator._get_client()
    done: list[str] = []

    def earners() -> dict[str, Any]:
        found = client.containers.list(all=True, filters={"label": [f"{LABEL_MANAGED}=true", LABEL_PROXY]})
        return {str(c.name): c for c in found if _is_earner(c)}

    by_name = earners()
    for aside_name, aside in sorted(by_name.items()):
        if not aside_name.endswith(MOVING_SUFFIX):
            continue
        name = aside_name.removesuffix(MOVING_SUFFIX)
        clone = by_name.get(name + STAGED_SUFFIX)
        if clone is not None and _age_seconds(clone) < min_age:
            continue
        try:
            if name in by_name:
                _remove_quietly(aside, 2)
                done.append(f"removed {aside_name}")
            elif (
                clone is not None and _get(client, _tunnel_id_of(aside)) is None and _get(client, _tunnel_id_of(clone))
            ):
                clone.rename(name)
                _remove_quietly(aside, 2)
                done.append(f"finished {name}")
            else:
                if clone is not None:
                    _remove_quietly(clone, 2)
                aside.rename(name)
                done.append(f"restored {name}")
        except Exception as exc:  # noqa: BLE001 - the next pass tries again
            logger.warning("Could not recover the move of %s: %s", name, exc)
    by_name = earners()
    for staged_name, clone in sorted(by_name.items()):
        if not staged_name.endswith(STAGED_SUFFIX) or _age_seconds(clone) < min_age:
            continue
        name = staged_name.removesuffix(STAGED_SUFFIX)
        if name + MOVING_SUFFIX in by_name:
            continue
        try:
            if name in by_name:
                _remove_quietly(clone, 2)
                done.append(f"removed {staged_name}")
            else:
                clone.rename(name)
                done.append(f"finished {name}")
        except Exception as exc:  # noqa: BLE001 - the next pass tries again
            logger.warning("Could not recover the move of %s: %s", name, exc)
    for line in done:
        logger.info("A move a worker died in: %s", line)
    return done


def _finish_stale_staged(client: Any, staged: Any) -> None:
    """A staged shared tunnel copies still live in, past any change's timeout:
    finish that change, unless one of this proxy is running now."""
    pid = _labels(staged).get(LABEL_PROXY, "")
    if not pid.isdigit() or not _is_shared(staged, int(pid)):
        return
    if _moving(client, pid):
        return  # recover_moves settles those first, at a later heartbeat
    lock = _deploy_lock(int(pid))
    if not lock.acquire(blocking=False):
        return
    try:
        current = _get(client, shared_tunnel_name(int(pid)))
        if current is not None and not _is_shared(current, int(pid)):
            return
        _finish_staged(client, staged, current, shared_tunnel_name(int(pid)))
    except Exception as exc:  # noqa: BLE001 - the next heartbeat tries again
        logger.warning("Could not finish the tunnel change of proxy %s: %s", pid, exc)
    finally:
        lock.release()


def _read_all_files(container: Any) -> dict[str, str]:
    return {key: _read_secret_file(container, key) or "" for key in SECRET_KEYS if key != "settings"}


def migrate_legacy() -> list[str]:
    """Move the copies of older workers, one tunnel each, into one shared tunnel per proxy.

    Run at worker start. Per proxy, the settings come from its shared tunnel
    when one is ready, else from a running, ready legacy tunnel (its secret
    files, read back; nothing is asked of the UI). A proxy with neither is left
    alone: its legacy pairs keep working and move on their next start. Any
    failure leaves the pairs not moved yet as they are: each one is valid and
    fails closed. Copies whose legacy tunnel was stopped stay stopped.
    Running it again does nothing once every pair has moved.
    """
    client = orchestrator._get_client()
    found = client.containers.list(
        all=True, filters={"label": [f"{LABEL_MANAGED}=true", f"{LABEL_ROLE}={ROLE_TUNNEL}", LABEL_PROXY]}
    )
    legacy: dict[int, list[Any]] = {}
    for c in found:
        pid = _labels(c).get(LABEL_PROXY, "")
        slug = _labels(c).get(LABEL_SERVICE, "")
        if str(c.name).endswith(STAGED_SUFFIX) or slug in (SHARED_SLUG, TEST_SLUG) or not pid.isdigit():
            continue
        legacy.setdefault(int(pid), []).append(c)
    moved: list[str] = []
    for proxy_id, tunnels in sorted(legacy.items()):
        with _deploy_lock(proxy_id):
            try:
                moved += _migrate_proxy(client, proxy_id, tunnels)
            except Exception as exc:  # noqa: BLE001 - the pairs left are valid; the next start tries again
                logger.warning("Could not move the copies of proxy %s into one tunnel: %s", proxy_id, redact(str(exc)))
    return moved


def _migrate_proxy(client: Any, proxy_id: int, tunnels: list[Any]) -> list[str]:
    ready = _shared_ready(client, proxy_id)
    if ready is None:
        sources = [t for t in tunnels if getattr(t, "status", "") == "running" and _read_exit(t) is not None]
        if not sources:
            logger.info(
                "Proxy %s has no running tunnel to copy settings from; its copies move on their next start", proxy_id
            )
            return []
        sources.sort(key=_started_at, reverse=True)
        files = _read_all_files(sources[0])
        if files.get("kind") == "tailscale":
            files["hostname"] = _ts_hostname(shared_label(proxy_id))
        files = _with_digest(files)
        ready = _ensure_tunnel(client, proxy_id, None, files.get("own_ip") or None, files=files)
    shared, _ = ready
    moved: list[str] = []
    for tunnel in tunnels:
        was_up = getattr(tunnel, "status", "") in _LIVE
        # Older workers stopped a pair by stopping its tunnel, which Docker
        # (unless-stopped) then leaves down. One Docker tried to start and could
        # not (State.Error, e.g. after a daemon restart) was not stopped by anyone.
        failed = bool(((getattr(tunnel, "attrs", None) or {}).get("State") or {}).get("Error"))
        with _swap_lock:
            for member in _members(client, tunnel):
                if not was_up and not failed:
                    # The owner or the cap stopped this pair: it stays stopped.
                    _set_held(str(member.name), True, strict=True)
                clone = _clone_into(client, member, shared, start=was_up and getattr(member, "status", "") in _LIVE)
                moved.append(str(clone.name))
            _remove_quietly(tunnel, SIDECAR_STOP_SECONDS)
    if moved:
        logger.info(
            "Moved %d cop%s of proxy %s into one shared tunnel", len(moved), "y" if len(moved) == 1 else "ies", proxy_id
        )
    return moved


def _started_at(container: Any) -> str:
    state = (container.attrs or {}).get("State") or {}
    return str(state.get("StartedAt") or "")


def _read_exit(sidecar: Any) -> dict[str, Any] | None:
    if sidecar.status != "running":
        return None
    try:
        code, out = sidecar.exec_run(["cat", "/run/ready"], demux=False)
    except Exception:  # noqa: BLE001 - unknown is the honest answer
        return None
    if code != 0 or not out:
        return None
    try:
        result = json.loads(out.decode().strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    return result if isinstance(result, dict) and _is_ip(result.get("ip")) else None


def _recover(earner: Any, sidecar: Any, slug: str, proxy_id: str) -> None:
    """Start or restart an earner inside its ready tunnel, for the heartbeat.

    Under the proxy's lock, with the stop marker and the earner read again
    inside it: a stop records itself and stops the earner under that lock, so
    a stop that returned is never undone here. A lock someone holds, or a
    marker that cannot be read, means nothing is done until the next beat.
    """
    lock = _deploy_lock(int(proxy_id)) if str(proxy_id).isdigit() else None
    if lock is not None and not lock.acquire(blocking=False):
        return
    try:
        try:
            if str(earner.name) in held():
                return
        except OSError as exc:
            logger.warning("Could not read which copies are stopped (%s); starting none", exc)
            return
        earner.reload()
        action = earner_action(earner, sidecar, True)
        if action == "restart":
            earner.restart(timeout=orchestrator._get_stop_timeout(slug))
        elif action == "start":
            earner.start()
        else:
            return
        earner.reload()
        logger.info("Started %s inside its tunnel, which is ready", earner.name)
    except Exception as exc:  # noqa: BLE001 - the next heartbeat tries again
        logger.warning("Could not start %s inside its tunnel: %s", earner.name, exc)
    finally:
        if lock is not None:
            lock.release()


def earner_action(earner: Any, sidecar: Any, ready: bool) -> str | None:
    """What the heartbeat does to an earner: "restart", "start" or nothing.

    Nothing happens until the tunnel is running and has written /run/ready,
    which it does only after its firewall is loaded and an exit through the
    tunnel was seen. So an earner never enters a namespace that could still
    leak, including after a reboot or a daemon restart (Docker does not start
    a proxied earner on its own; see orchestrator.deploy_raw).

    A running earner whose tunnel started after it sits in the old namespace,
    which has no way out: it does not leak, it just stops earning until it is
    restarted into the new one. An earner that is not running while its
    tunnel is up was stopped by a reboot or by its own crash; one the owner or
    the cap stopped is held (HELD_MARKER), and status() never asks about it.
    """
    if not ready or getattr(sidecar, "status", "") != "running":
        return None
    status = getattr(earner, "status", "")
    if status == "running":
        return "restart" if _started_at(sidecar) > _started_at(earner) else None
    if status in ("exited", "created"):
        return "start"
    return None


def status(collect_stats: bool = True) -> list[dict[str, Any]]:
    """One entry per proxied copy on this worker, for the heartbeat.

    Traffic is the tunnel's: the earner has no interface of its own, so its
    stats carry no network counters, and every byte it moves crosses the
    tunnel's eth0. Copies that share a tunnel report the same counters and the
    same tunnel id; the UI's cap counts one tunnel id once (proxies.account).
    """
    with _swap_lock:
        return _status(collect_stats)


def _status(collect_stats: bool) -> list[dict[str, Any]]:
    try:
        client = orchestrator._get_client()
        found = client.containers.list(all=True, filters={"label": [f"{LABEL_MANAGED}=true", LABEL_PROXY]})
    except Exception as exc:  # noqa: BLE001 - a heartbeat must not fail on this
        logger.debug("Could not list proxied copies: %s", exc)
        return []
    # Moves a worker died in come first: a copy aside or staged is still a copy.
    if any(str(getattr(c, "name", "")).endswith((STAGED_SUFFIX, MOVING_SUFFIX)) for c in found):
        with contextlib.suppress(Exception):
            recover_moves()
            found = client.containers.list(all=True, filters={"label": [f"{LABEL_MANAGED}=true", LABEL_PROXY]})
    # A staged tunnel past any change's timeout: one copies live in (staged or
    # aside ones included) is a change to finish; an empty one is a leftover
    # holding the proxy login, removed here, since the startup sweep skips those
    # still young when the worker starts.
    every_earner = [c for c in found if _labels(c).get(LABEL_ROLE) != ROLE_TUNNEL]
    for container in found:
        if (
            str(getattr(container, "name", "")).endswith(STAGED_SUFFIX)
            and _labels(container).get(LABEL_ROLE) == ROLE_TUNNEL
            and _age_seconds(container) >= STAGED_STALE_SECONDS
        ):
            if any(_tunnel_id_of(e) == container.id for e in every_earner):
                _finish_stale_staged(client, container)
            else:
                _remove_quietly(container, 2)
    with contextlib.suppress(Exception):
        found = client.containers.list(all=True, filters={"label": [f"{LABEL_MANAGED}=true", LABEL_PROXY]})
    tunnels: dict[str, Any] = {}
    earners: list[Any] = []
    for container in found:
        if str(getattr(container, "name", "")).endswith((STAGED_SUFFIX, MOVING_SUFFIX)):
            continue
        if _labels(container).get(LABEL_ROLE) == ROLE_TUNNEL:
            tunnels[container.id] = container
        else:
            earners.append(container)
    pairs: dict[tuple[str, str], tuple[Any | None, Any | None]] = {}
    used: set[str] = set()
    for earner in earners:
        labels = _labels(earner)
        tunnel = tunnels.get(_tunnel_id_of(earner))
        if tunnel is None:
            # An earner whose NetworkMode names no tunnel we know: its legacy
            # tunnel by name, if any (an older worker, or an older docker-py).
            tunnel = next(
                (
                    t
                    for t in tunnels.values()
                    if t.name == tunnel_name(labels.get(LABEL_SERVICE, ""), labels.get(LABEL_PROXY, ""))
                ),
                None,
            )
        if tunnel is not None:
            used.add(tunnel.id)
        pairs[(labels.get(LABEL_SERVICE, ""), labels.get(LABEL_PROXY, ""))] = (earner, tunnel)
    for tunnel in tunnels.values():
        # A legacy tunnel whose earner is gone still reports, so the UI sees it.
        if tunnel.id not in used and not _is_shared(tunnel):
            labels = _labels(tunnel)
            pairs.setdefault((labels.get(LABEL_SERVICE, ""), labels.get(LABEL_PROXY, "")), (None, tunnel))
    live = {t.id: t for _, t in pairs.values() if t is not None}
    stats = orchestrator._collect_stats_bulk(list(live.values())) if collect_stats else {}
    exits = {tid: _read_exit(t) for tid, t in live.items()}
    out: list[dict[str, Any]] = []
    for (slug, proxy_id), (earner, sidecar) in sorted(pairs.items()):
        exit_info = exits.get(sidecar.id) if sidecar is not None else None
        if earner is not None and earner_action(earner, sidecar, exit_info is not None) is not None:
            _recover(earner, sidecar, slug, proxy_id)
        _, _, rx, tx = stats.get(sidecar.id, (None, None, None, None)) if sidecar is not None else (None,) * 4
        try:
            pid = int(proxy_id)
        except ValueError:
            continue
        out.append(
            {
                "slug": slug,
                "proxy_id": pid,
                "name": earner.name if earner is not None else earner_name(slug, pid),
                "status": earner.status if earner is not None else "missing",
                "container_id": earner.short_id if earner is not None else "",
                "tunnel_status": sidecar.status if sidecar is not None else "missing",
                "tunnel_container_id": sidecar.short_id if sidecar is not None else "",
                "tunnel_started_at": _started_at(sidecar) if sidecar is not None else "",
                "tunnel_shared": bool(sidecar is not None and _is_shared(sidecar)),
                "net_rx_bytes": rx,
                "net_tx_bytes": tx,
                "exit_ip": (exit_info or {}).get("ip"),
                "exit_country": (exit_info or {}).get("country"),
            }
        )
    return out


def test(proxy: dict[str, Any], own_ip: str | None) -> dict[str, Any]:
    """Start a throwaway sidecar, read the exit IP it gets, and remove it on every path."""
    client = orchestrator._get_client()
    name = f"{CONTAINER_PREFIX}tunnel-test-{uuid.uuid4().hex[:10]}"
    began = time.monotonic()
    sidecar, exit_info = start_sidecar(client, name, TEST_SLUG, None, proxy, own_ip)
    try:
        return {**exit_info, "ms": int((time.monotonic() - began) * 1000)}
    finally:
        _remove_quietly(sidecar, 2)
