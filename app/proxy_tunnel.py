"""Proxied copies of a service: one earner that can only leave through a proxy.

Runs inside the worker. A proxied copy is two containers:

* a **tunnel sidecar** from our own pinned image (Dockerfile.tunnel). Its
  entrypoint drops every packet that is not tunnel traffic before it starts the
  tunnel, so the proxy is the only way out of its network namespace;
* the **earner**, created with ``network_mode=container:<sidecar>``. It has no
  interface of its own. If the proxy, the tunnel process or the sidecar dies,
  it has nowhere to send a packet.

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
from typing import Any
from urllib.parse import quote

from docker.errors import APIError, NotFound

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
# deploy() swapping the old pair for the staged one, and status(), take turns: a
# heartbeat must not start an earner that is being removed, or read a half swap.
_swap_lock = threading.Lock()


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
    return f"{CONTAINER_PREFIX}tunnel-{slug}-p{proxy_id}"


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
    files = _secret_files(proxy, own_ip, label)
    digest_of = {k: v for k, v in files.items() if k not in ("own_ip", "proxy_ip")}
    files["settings"] = hashlib.sha256(json.dumps(digest_of, sort_keys=True).encode()).hexdigest()
    return files


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
        files["hostname"] = re.sub(r"[^a-z0-9-]", "-", f"cashpilot-{label}".lower())[:63]
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
        "hostname": hostname,
        "cap_drop": ["ALL"],
        "cap_add": ["NET_ADMIN"],
        "devices": ["/dev/net/tun"],
        "privileged": False,
        "security_opt": ["no-new-privileges:true"],
        "pids_limit": 64,
        "read_only": True,
        "tmpfs": {"/run": "size=8m,mode=0755"},
        "volumes": [SECRET_DIR],
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


def start_sidecar(
    client: Any,
    name: str,
    slug: str,
    proxy_id: int | None,
    proxy: dict[str, Any],
    own_ip: str | None,
    hostname: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Create, provision and start a sidecar, then wait for its exit. Removed on any failure."""
    network = orchestrator.container_network("bridge")
    files = secret_files(proxy, own_ip, f"{slug}-p{proxy_id}" if proxy_id is not None else slug)
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
            raise ProxyTunnelError(redact(str(exc), _secret_values(proxy)), exc.status_code) from None
        detail = orchestrator.proxy_refusal(exc) or str(exc)
        raise ProxyTunnelError(redact(f"The tunnel could not start: {detail}", _secret_values(proxy))) from None
    return container, exit_info


def _hostname(name: str) -> str:
    return name.removeprefix(CONTAINER_PREFIX)[:63]


def deploy(slug: str, proxy_id: int, earner: dict[str, Any], proxy: dict[str, Any], own_ip: str | None) -> dict:
    """Deploy (or replace) the proxied copy of ``slug`` through proxy ``proxy_id``.

    Order: the new sidecar starts under a staged name and proves an exit while
    the old pair keeps running; then the old pair goes (earner first), the
    sidecar takes the final name, and only then is the earner created inside
    its namespace. A sidecar that cannot start therefore costs nothing.
    """
    client = orchestrator._get_client()
    # Checked first: settings that cannot work (a host that does not resolve,
    # no tunnel image) fail fast, before a sidecar is created.
    secret_files(proxy, own_ip, f"{slug}-p{proxy_id}")
    tunnel_image()
    final = tunnel_name(slug, proxy_id)
    staged = final + STAGED_SUFFIX
    # Left by a deploy that died midway, on this name only if it is ours.
    if (leftover := _get(client, staged)) is not None:
        if not _is_ours(leftover, slug, proxy_id):
            raise ProxyTunnelError(f"A container named {staged} that CashPilot did not create is in the way")
        _remove_quietly(leftover, 2)
    sidecar, exit_info = start_sidecar(client, staged, slug, proxy_id, proxy, own_ip, hostname=_hostname(final))
    try:
        with _swap_lock:
            remove(slug, proxy_id)
            sidecar.rename(final)
    except Exception:
        _remove_quietly(sidecar, 2)
        raise
    try:
        container_id = orchestrator.deploy_raw(
            slug=slug,
            image=earner["image"],
            env=earner.get("env") or {},
            network_mode=f"container:{sidecar.id}",
            cap_add=earner.get("cap_add"),
            devices=earner.get("devices"),
            command=earner.get("command"),
            labels={**(earner.get("labels") or {}), LABEL_PROXY: str(proxy_id)},
            resources=earner.get("resources"),
            category=(earner.get("labels") or {}).get(LABEL_CATEGORY, "bandwidth"),
            name=earner_name(slug, proxy_id),
        )
    except Exception:
        _remove_quietly(sidecar, 2)
        raise
    return {"container_id": container_id, "tunnel_id": sidecar.id, "exit": exit_info}


def _pair(slug: str, proxy_id: int) -> tuple[Any | None, Any | None]:
    client = orchestrator._get_client()
    return _get(client, earner_name(slug, proxy_id)), _get(client, tunnel_name(slug, proxy_id))


def _is_ours(container: Any | None, slug: str, proxy_id: int) -> bool:
    labels = (getattr(container, "labels", None) or {}) if container is not None else {}
    return (
        labels.get(LABEL_MANAGED) == "true"
        and labels.get(LABEL_SERVICE) == slug
        and labels.get(LABEL_PROXY) == str(proxy_id)
    )


_LIVE = ("running", "restarting")


def stop(slug: str, proxy_id: int) -> bool:
    """Stop the earner, then its tunnel. Returns whether either was running.

    Docker answers a stop of a stopped container with success, so the cap asks
    this to tell a copy it stopped from one the owner had already stopped.
    """
    earner, sidecar = _pair(slug, proxy_id)
    if not _is_ours(earner, slug, proxy_id) and not _is_ours(sidecar, slug, proxy_id):
        raise ValueError(f"No proxied copy of {slug} through proxy {proxy_id} on this worker")
    was_running = any(_is_ours(c, slug, proxy_id) and getattr(c, "status", "") in _LIVE for c in (earner, sidecar))
    if _is_ours(earner, slug, proxy_id):
        earner.stop(timeout=orchestrator._get_stop_timeout(slug))
    if _is_ours(sidecar, slug, proxy_id):
        sidecar.stop(timeout=10)
    return was_running


def start(slug: str, proxy_id: int, proxy: dict[str, Any] | None = None, own_ip: str | None = None) -> dict[str, Any]:
    """Start the tunnel, wait for its exit, then the earner.

    ``proxy`` is the proxy as it is stored now. Its settings are written over
    the ones the tunnel was deployed with, so a new password, port, auth key or
    exit node reaches the copy on its next start. A tunnel still running on
    other settings is stopped first, with its earner, and comes back on the new
    ones. Without ``proxy`` (a UI older than this worker) only the address is
    resolved again.

    The earner is restarted rather than started when it is still running in a
    namespace the old tunnel left behind.
    """
    earner, sidecar = _pair(slug, proxy_id)
    if not _is_ours(earner, slug, proxy_id) or not _is_ours(sidecar, slug, proxy_id):
        raise ValueError(f"No proxied copy of {slug} through proxy {proxy_id} on this worker")
    sidecar.reload()
    if proxy is not None:
        try:
            files = secret_files(proxy, own_ip, f"{slug}-p{proxy_id}")
        except ProxyTunnelError as exc:
            raise ProxyTunnelError(redact(str(exc), _secret_values(proxy)), exc.status_code) from None
        if sidecar.status == "running" and _read_secret_file(sidecar, "settings") != files["settings"]:
            earner.stop(timeout=orchestrator._get_stop_timeout(slug))
            sidecar.stop(timeout=10)
            sidecar.reload()
        if sidecar.status != "running":
            full = {key: files.get(key, "") for key in SECRET_KEYS}
            if not sidecar.put_archive(SECRET_DIR, _secret_tar(full)):
                raise ProxyTunnelError("Could not hand the proxy settings to the tunnel container")
    elif sidecar.status != "running":
        refresh_proxy_ip(sidecar)
    sidecar.start()
    exit_info = _wait_ready(sidecar)
    earner.reload()
    if earner.status == "running":
        earner.restart(timeout=orchestrator._get_stop_timeout(slug))
    else:
        earner.start()
    return {"exit": exit_info}


def remove(slug: str, proxy_id: int) -> list[str]:
    """Remove the earner, then its tunnel and the tunnel's secret volume."""
    removed: list[str] = []
    earner, sidecar = _pair(slug, proxy_id)
    for container, timeout in ((earner, orchestrator._get_stop_timeout(slug)), (sidecar, 10)):
        if _is_ours(container, slug, proxy_id):
            _remove_quietly(container, timeout)
            removed.append(container.name)
    return removed


def remove_all(slug: str) -> list[str]:
    """Every proxied copy of ``slug`` and its tunnel, when the service is removed."""
    client = orchestrator._get_client()
    found = client.containers.list(
        all=True, filters={"label": [f"{LABEL_SERVICE}={slug}", f"{LABEL_MANAGED}=true", LABEL_PROXY]}
    )
    # Earners first, so no tunnel is removed under a running earner.
    found.sort(key=lambda c: (c.labels or {}).get(LABEL_ROLE) == ROLE_TUNNEL)
    removed: list[str] = []
    left: list[str] = []
    for container in found:
        _remove_quietly(container)
        try:
            container.reload()
        except NotFound:
            removed.append(container.name)
        else:
            left.append(container.name)
    if left:
        # Said out loud, so the UI keeps the records of copies that still exist.
        raise ProxyTunnelError(f"Docker did not remove {', '.join(left)}", status_code=409)
    return removed


def sweep_test_tunnels() -> list[str]:
    """Remove Test tunnels a worker that stopped mid-test left behind, and staged
    sidecars of a deploy it stopped in.

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
    # And staged sidecars of a deploy the worker died in: they hold the proxy
    # login, and the heartbeat never reports them.
    staged = client.containers.list(
        all=True, filters={"label": [f"{LABEL_MANAGED}=true", f"{LABEL_ROLE}={ROLE_TUNNEL}", LABEL_PROXY]}
    )
    for container in staged:
        if str(container.name).endswith(STAGED_SUFFIX):
            _remove_quietly(container, 2)
            swept.append(container.name)
    return swept


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
    tunnel is up was stopped by a reboot or by its own crash, never by the
    owner or the cap, which stop the tunnel too; it is started.
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

    Traffic is the sidecar's: the earner has no interface of its own, so its
    stats carry no network counters, and every byte it moves crosses the
    sidecar's eth0.
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
    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    for container in found:
        if str(getattr(container, "name", "")).endswith(STAGED_SUFFIX):
            continue  # a redeploy's sidecar, not promoted yet
        labels = container.labels or {}
        key = (labels.get(LABEL_SERVICE, ""), labels.get(LABEL_PROXY, ""))
        role = "tunnel" if labels.get(LABEL_ROLE) == ROLE_TUNNEL else "earner"
        pairs.setdefault(key, {})[role] = container
    stats = (
        orchestrator._collect_stats_bulk([p["tunnel"] for p in pairs.values() if "tunnel" in p])
        if collect_stats
        else {}
    )
    out: list[dict[str, Any]] = []
    for (slug, proxy_id), pair in sorted(pairs.items()):
        earner, sidecar = pair.get("earner"), pair.get("tunnel")
        exit_info = _read_exit(sidecar) if sidecar is not None else None
        action = earner_action(earner, sidecar, exit_info is not None) if earner is not None else None
        if action is not None:
            try:
                if action == "restart":
                    earner.restart(timeout=orchestrator._get_stop_timeout(slug))
                else:
                    earner.start()
                earner.reload()
                logger.info("Started %s inside its tunnel, which is ready", earner.name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not start %s inside its tunnel: %s", earner.name, exc)
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
