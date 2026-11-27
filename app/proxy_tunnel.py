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

A service routed through a proxy from its first deploy (app/route_gate.py) is
the one exception: it gets a tunnel of its own (``cashpilot-tunnel-p<id>-<slug>``,
``own_tunnel``). Earners in one namespace share its loopback and its /proc/net,
so one provider's client could reach another's local ports, take a port first
or read its connections. Direct earners are kept apart on the bridge
(enable_icc off), and a routed service, which runs in place of a direct one,
keeps that separation. Its tunnel works exactly as a shared one with one copy.

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
import errno
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
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, unquote

from docker.errors import APIError, DockerException, NotFound
from docker.types import Mount

from app import egress, gpu, lan_fence, orchestrator, route_gate, version
from app.constants import (
    CONTAINER_PREFIX,
    DEPLOY_DEADLINE_SECONDS,
    LABEL_CATEGORY,
    LABEL_DEPLOYED_BY,
    LABEL_MANAGED,
    LABEL_PROXY,
    LABEL_ROLE,
    LABEL_SERVICE,
    LABEL_VERSION,
    PROXIED_FORBIDDEN_CAPS,
    ROLE_TUNNEL,
    TUNNEL_PREFIX,
)
from app.i18n import t

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
#: A deploy that takes a new tunnel image for its only copy keeps the old tunnel
#: under its name plus this suffix, with the old earner still inside, until the
#: new earner runs (see _ensure_tunnel's ``keep``). A failed deploy gives it the
#: name back; the heartbeat removes one left empty. A dot, which no slug holds
#: (only ``[a-z0-9-]``), so the retired name of one tunnel is never the name of
#: another service's own tunnel (``...-p<id>-<slug>``), whatever its slug ends in.
RETIRED_SUFFIX = ".old"
# deploy() swapping the old pair for the staged one, and status(), take turns: a
# heartbeat must not start an earner that is being removed, or read a half swap.
_swap_lock = threading.Lock()
# One operation per proxy at a time: the copies through a proxy share its
# tunnel (the route mark is guarded by route_gate.deploying, taken first), so a second deploy would take the first one's staged tunnel for a
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
#: A routed service's own tunnel carries the same, plus LABEL_TUNNEL_FOR naming it.
SHARED_SLUG = "proxy-tunnel"
LABEL_TUNNEL_FOR = "cashpilot.tunnel-for"

#: Earners the owner or the cap stopped, one container name per line. Their
#: tunnel may keep running for the other copies, so without this the heartbeat
#: would take a stopped earner beside a ready tunnel for one a reboot stopped,
#: and start it again.
HELD_MARKER = os.path.join(os.getenv("CASHPILOT_DATA_DIR", "/data"), ".proxied_held")
_held_lock = threading.Lock()
#: Replacements a failed redeploy left that Docker would not remove, one
#: container id per line. While one holds the copy's name, the old earner
#: deploy_raw kept aside (``<name>-replaced``) is the copy, whatever state the
#: failed one is in: one that started and exited is no proof the deploy went
#: through, and taking it for the copy would remove the old earner.
FAILED_MARKER = os.path.join(os.getenv("CASHPILOT_DATA_DIR", "/data"), ".proxied_failed")
#: Ids of previous copies a redeploy moves aside until it records the outcome.
KEPT_MARKER = os.path.join(os.getenv("CASHPILOT_DATA_DIR", "/data"), ".proxied_kept")
#: Names of unfinished first deploys, or the specific holders a legacy marker
#: was bound to. These intent markers cannot authorize removal on their own.
NEW_MARKER = os.path.join(os.getenv("CASHPILOT_DATA_DIR", "/data"), ".proxied_new")
# Only successful deploys and checked moves write these full Docker IDs.
# An inventory read never gives a container permission to be replaced.
CONTAINER_MARKER = os.path.join(os.getenv("CASHPILOT_DATA_DIR", "/data"), ".proxied_containers")

# Full IDs from Docker's create response. The older intent markers alone
# cannot prove that the container currently under a name belongs to a deploy.
CREATED_MARKER = os.path.join(os.getenv("CASHPILOT_DATA_DIR", "/data"), ".proxied_created")
MOVE_MARKER = os.path.join(os.getenv("CASHPILOT_DATA_DIR", "/data"), ".proxied_moves")


def _read_names(path: str) -> set[str]:
    """The names in the marker at ``path``; none when it does not exist. Raises OSError when it cannot be read."""
    try:
        with open(path, encoding="utf-8") as fh:
            return {line.strip() for line in fh if line.strip()}
    except FileNotFoundError:
        return set()
    except UnicodeDecodeError as exc:
        # A garbled marker is one that cannot be read: every caller handles OSError.
        raise OSError(t("err.proxy_tunnel.not_text", path=os.path.basename(path), reason=exc.reason)) from None


def _write_names(path: str, names: set[str]) -> None:
    """Replace the marker at ``path`` with ``names``, on disk before it returns. Raises OSError."""
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("".join(f"{n}\n" for n in sorted(names)))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    # And the rename itself, or a power cut can bring the old list back. A
    # failure raises (_sync_folder): a stop or a deploy is acknowledged only
    # once its record is on disk. The marker already holds the new list, so a
    # retry that finds it there flushes the folder again (_flush_unchanged).
    _sync_folder(path)


#: What a folder flush answers on a filesystem that cannot flush a folder at
#: all (some network and VM shared folders). It always will, and nothing more
#: can be done there, so the rename stands as written and is logged once, as
#: PostgreSQL's fsync_fname does. Any other error (EIO) means the rename may be
#: lost, and raises.
_NO_FOLDER_FLUSH = frozenset({errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EBADF})
_no_folder_flush_logged: set[str] = set()


class _NotFlushed(OSError):
    """The marker holds the new list, but its folder could not be flushed: the rename may not survive a power cut."""


def _sync_folder(path: str) -> None:
    """Flush the folder of the marker at ``path``, so its last rename survives a power cut. Raises _NotFlushed."""
    folder_path = os.path.dirname(path) or "."
    folder = None
    try:
        # Opened inside the mapping too: the rename is already done, so a folder
        # that cannot be opened (EMFILE) is one that was not flushed, never a
        # write that failed (a stop goes ahead on _NotFlushed, see _stop).
        folder = os.open(folder_path, os.O_RDONLY)
        os.fsync(folder)
    except OSError as exc:
        if exc.errno not in _NO_FOLDER_FLUSH:
            raise _NotFlushed(exc.errno, f"the data folder could not be flushed: {exc.strerror or exc}") from None
        if folder_path not in _no_folder_flush_logged:
            _no_folder_flush_logged.add(folder_path)
            logger.warning(
                "The filesystem of %s cannot flush a folder (%s); markers are written without it", folder_path, exc
            )
    finally:
        if folder is not None:
            os.close(folder)


def _recorded_containers() -> dict[str, str]:
    try:
        return dict(line.split("@", 1) for line in _read_names(CONTAINER_MARKER) if "@" in line)
    except OSError as exc:
        logger.warning("Could not read the saved proxied container IDs: %s", exc)
        return {}


def _record_container(name: str, container_id: str | None) -> None:
    """Save the container ID of ``name``, or with None drop it (the copy was removed)."""
    try:
        with _held_lock:
            records = _read_names(CONTAINER_MARKER)
            kept = {entry for entry in records if not entry.startswith(f"{name}@")}
            if container_id is not None:
                _write_names(CONTAINER_MARKER, kept | {f"{name}@{container_id}"})
            elif kept != records:
                _write_names(CONTAINER_MARKER, kept)
    except OSError as exc:
        # The deploy, move or removal has committed. A lost or stale record makes
        # later moves ask for approval (or skip), so it is safe to report success.
        logger.warning("Could not save the container ID of %s: %s", name, exc)


def _forget_container(name: str) -> None:
    _record_container(name, None)


def _flush_unchanged(path: str) -> None:
    """For a write that finds the marker already says so: flush its folder anyway.

    The write that said so may not have flushed it, in this process or in one
    before a restart, so the retry is acknowledged only once it is on disk. No
    marker means no rename to flush."""
    if os.path.exists(path):
        _sync_folder(path)


def held() -> set[str]:
    """The earners recorded as stopped. Raises OSError when the marker exists
    but cannot be read: an empty answer then would restart every stopped copy."""
    return _read_names(HELD_MARKER)


def _created_key(name: str, previous: str, container_id: str) -> str:
    return f"{name}@{previous}@{container_id}"


def _record_pair(path: str, name: str, previous: str, container_id: str) -> None:
    with _held_lock:
        try:
            records = _read_names(path)
            records = {line for line in records if not line.startswith(f"{name}@")}
            _write_names(path, records | {_created_key(name, previous, container_id)})
        except OSError as exc:
            raise ProxyTunnelError(t("err.proxy_tunnel.could_not_record_created_container", name=name)) from exc


def _record_created(name: str, previous: str, container_id: str) -> None:
    _record_pair(CREATED_MARKER, name, previous, container_id)


def _forget_created(name: str, previous: str, container_id: str) -> None:
    _set_id(CREATED_MARKER, _created_key(name, previous, container_id), False)


def _created_by_deploy(holder: Any, previous: str = "none") -> bool:
    return _created_key(str(holder.name), previous, str(holder.id)) in _read_names(CREATED_MARKER)


def _aside_is_copy(holder: Any, aside: Any) -> bool:
    """An unfinished redeploy can restore its old copy only over the replacement it created."""
    return (
        not _going(aside)
        and _created_by_deploy(holder, str(aside.id))
        and (str(aside.id) in _read_names(KEPT_MARKER) or _recorded_failed(holder))
    )


def _require_resolved_deploy(holder: Any, aside: Any | None) -> None:
    """Refuse to touch a name holder that an interrupted deploy cannot identify."""
    name = str(holder.name)
    previous = str(aside.id) if aside is not None else "none"
    if (aside is not None or _recorded_failed(holder)) and not _created_by_deploy(holder, previous):
        raise RecoveryConflict(t("err.proxy_tunnel.recovery_skipped_deploy_record_cannot", name=name))


def _going(container: Any | None) -> bool:
    """Gone, or past return: Docker never starts or renames a container it is removing or left dead."""
    return container is None or getattr(container, "status", "") in ("removing", "dead")


def _new_key(name: str, container_id: str) -> str:
    """The NEW_MARKER record of the container ``container_id`` under ``name``: Docker names never hold an ``@``."""
    return f"{name}@{container_id}"


def _recorded_failed(container: Any) -> bool:
    """Whether ``container`` is a deploy's that failed or never said it went through.

    One a failed deploy recorded (FAILED_MARKER), one under a name whose first
    deploy is still recorded (NEW_MARKER), or the container such a record was
    bound to. Raises OSError when a marker cannot be read."""
    cid, name = str(getattr(container, "id", "")), str(getattr(container, "name", ""))
    new = _read_names(NEW_MARKER)
    return cid in _read_names(FAILED_MARKER) or name in new or _new_key(name, cid) in new


def _set_failed(container_id: str, on: bool) -> bool:
    """Record, or forget, a failed deploy's replacement. A failure is logged only. Whether it was done."""
    return _set_id(FAILED_MARKER, container_id, on)


def _set_kept(container_id: str, on: bool, *, strict: bool = False) -> bool:
    """Record, or forget, an old earner a redeploy moves aside. ``strict`` raises ProxyTunnelError on a failure."""
    return _set_id(KEPT_MARKER, container_id, on, strict=strict)


def _set_new(name: str, on: bool, *, strict: bool = False) -> bool:
    """Record, or forget, a first deploy of the copy ``name``. ``strict`` raises ProxyTunnelError on a failure."""
    return _set_id(NEW_MARKER, name, on, strict=strict)


def _bind_new(name: str, container_id: str) -> None:
    """Bind the record of a dead first deploy of ``name`` to ``container_id``, what it left. ProxyTunnelError when it cannot.

    The record still says that container is not the copy, but no longer
    whatever holds the name: a replacement whose deploy then fails to clear it
    is never taken for a failed first deploy and removed."""
    with _held_lock:
        try:
            keys = _read_names(NEW_MARKER)
            _write_names(NEW_MARKER, (keys - {name}) | {_new_key(name, container_id)})
        except OSError as exc:
            raise ProxyTunnelError(t("err.proxy_tunnel.could_not_record_deploy_disk", exc=exc)) from None


def _set_id(path: str, key: str, on: bool, *, strict: bool = False) -> bool:
    with _held_lock:
        try:
            keys = _read_names(path)
            if (key in keys) == on:
                _flush_unchanged(path)
                return True
            _write_names(path, keys | {key} if on else keys - {key})
            return True
        except OSError as exc:
            if strict:
                raise ProxyTunnelError(t("err.proxy_tunnel.could_not_record_deploy_disk", exc=exc)) from None
            logger.warning("Could not update %s for %s: %s", os.path.basename(path), key[:40], exc)
            return False


def _set_held(name: str, on: bool, *, strict: bool = False, rewrite: bool = False) -> None:
    """Record or clear a stop. ``strict`` raises when it cannot be done.

    A stop that is not recorded is undone by the next heartbeat, and a copy
    started while still recorded is never restarted after a reboot, so a stop
    and a start are both strict. A removal is not: its container is gone.
    ``rewrite`` writes the marker even when it already says so: the proof a
    deploy takes that it can clear the stop once its earner runs.
    """
    with _held_lock:
        try:
            names = held()
            if (name in names) == on and not rewrite:
                _flush_unchanged(HELD_MARKER)
                return
            _write_names(HELD_MARKER, names | {name} if on else names - {name})
        except OSError as exc:
            if strict:
                what = "was stopped" if on else "is no longer stopped"
                if isinstance(exc, _NotFlushed):
                    raise _RecordNotFlushed(
                        t("err.proxy_tunnel.could_not_record_good", name=name, what=what, exc=exc)
                    ) from None
                raise ProxyTunnelError(
                    t("err.proxy_tunnel.could_not_record_left", name=name, what=what, exc=exc)
                ) from None
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


class _RecordNotFlushed(ProxyTunnelError):
    """A stop or start is in the marker, but its folder could not be flushed (_NotFlushed)."""


class RecoveryConflict(ProxyTunnelError):
    """Docker's name holder cannot be tied to the unfinished operation."""


class CopyNotRunning(ProxyTunnelError):
    """In-place Restart refused a stopped copy before taking any action."""


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
            raise ProxyTunnelError(t("err.proxy_tunnel.cashpilot_tunnel_image_give_exact", override=repr(override)))
        return override
    current = version.current()
    # An unversioned build reports "dev", or "latest" when it was dispatched
    # without a version; neither names a tunnel image anyone published.
    if current == version.UNKNOWN or current.lower().removeprefix("v") in _FLOATING_TAGS:
        raise ProxyTunnelError(t("err.proxy_tunnel.worker_development_build_has_no"))
    return f"{TUNNEL_REPOSITORY}:{current.removeprefix('v')}"


def tunnel_name(slug: str, proxy_id: int) -> str:
    """A legacy tunnel: one per copy, from workers older than the shared tunnel."""
    return f"{TUNNEL_PREFIX}{slug}-p{proxy_id}"


def shared_tunnel_name(proxy_id: int, slug: str | None = None) -> str:
    """The one tunnel every copy through ``proxy_id`` on this worker joins, or with
    ``slug`` the routed service's own tunnel through it."""
    return f"{TUNNEL_PREFIX}p{proxy_id}" + (f"-{slug}" if slug else "")


def shared_label(proxy_id: int, slug: str | None = None) -> str:
    """What names the tunnel inside the tunnel (its tailnet host name)."""
    return f"{slug}-p{proxy_id}" if slug else f"p{proxy_id}"


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
        raise ProxyTunnelError(
            t("err.proxy_tunnel.cannot_resolve_proxy_host_worker", host=repr(host), exc=exc)
        ) from None
    for info in infos:
        return str(info[4][0])
    raise ProxyTunnelError(t("err.proxy_tunnel.proxy_host_has_no_ipv4", host=repr(host)))


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
        raise ProxyTunnelError(t("err.proxy_tunnel.unknown_proxy_type", kind=repr(kind)), status_code=400)
    files = {"kind": kind, "own_ip": own_ip or ""}
    if kind == "tailscale":
        if not proxy.get("auth_key") or not proxy.get("exit_node"):
            raise ProxyTunnelError(t("err.proxy_tunnel.tailscale_proxy_needs_auth_key"), status_code=400)
        files["auth_key"] = str(proxy["auth_key"])
        files["exit_node"] = str(proxy["exit_node"])
        files["hostname"] = _ts_hostname(label)
        if proxy.get("login_server"):
            files["login_server"] = str(proxy["login_server"])
        return files
    host = str(proxy.get("host") or "").strip()
    port = int(proxy.get("port") or 0)
    if not host or not 1 <= port <= 65535:
        raise ProxyTunnelError(t("err.proxy_tunnel.proxy_needs_host_port_between"), status_code=400)
    files["proxy_host"] = host
    files["proxy_ip"] = resolve_proxy_ip(host)
    files["proxy_port"] = str(port)
    # tun2proxy dials the address resolved above, so the sidecar never needs DNS
    # outside the tunnel. The URL is put together in cp-tunnel from these parts,
    # so a start can swap in a fresh address without the credentials.
    files["proxy_scheme"] = "socks5" if kind == "socks5" else "http"
    files["proxy_auth"] = proxy_auth(str(proxy.get("username") or ""), str(proxy.get("password") or ""))
    return files


def _auth_secrets(auth: str) -> list[str]:
    """What a proxy_auth value (``user:password@``, URL-encoded) gives away."""
    password = auth.rstrip("@").partition(":")[2]
    return [v for v in (auth, password, unquote(password)) if v]


def proxy_auth(username: str, password: str) -> str:
    """The ``user:password@`` part of the proxy URL, percent-encoded, or empty."""
    if not (username or password):
        return ""
    return f"{quote(username, safe='')}:{quote(password, safe='')}@"


def _read_secret_file(container: Any, name: str) -> str | None:
    """One file of a sidecar's secret volume; works on a stopped container."""
    try:
        return _read_secret_file_or_raise(container, name)
    except Exception:  # noqa: BLE001 - unreadable: nothing to refresh
        return None


def _read_secret_file_or_raise(container: Any, name: str) -> str | None:
    """As _read_secret_file, but None only for a file that is not there; any
    other failure raises. A SOCKS tunnel, for one, has no Tailscale files."""
    try:
        stream, _ = container.get_archive(f"{SECRET_DIR}/{name}")
    except NotFound:
        return None
    with tarfile.open(fileobj=io.BytesIO(b"".join(stream))) as tar:
        member = tar.next()
        handle = tar.extractfile(member) if member is not None else None
        return handle.read().decode().strip() if handle is not None else None


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


def sidecar_kwargs(
    name: str, slug: str, proxy_id: int | None, network: str | None, hostname: str, tunnel_for: str | None = None
) -> dict[str, Any]:
    """Everything the sidecar is created with. No secret appears here.

    ``tunnel_for`` names the service whose copy the tunnel carries.

    No tunnel gets a restart policy. Docker would start one again on its own
    (after a crash, a reboot or a daemon restart), and a new run's namespace
    has its interface and default route before cp-tunnel's first command
    loads the drop-all table: an earner starting into it in that moment
    sends from the box's own address. Without one, only the worker starts a
    tunnel, under the proxy's lock, which every earner start also holds, and
    an earner starts only after reading that the run is ready
    (_start_in_ready_run). So no earner ever starts into a run nobody proved.
    The heartbeat starts a tunnel that is down while a copy in it should run
    (_start_down_tunnel), and its copies once it is ready.

    Older workers gave every tunnel ``unless-stopped``, and the worker cannot
    take it away: the socket proxy refuses a container update on purpose
    (docs/security-defaults.md). A shared tunnel that still has it is replaced
    instead, by the first deploy, start or heartbeat that can
    (_restarts_by_itself), and no earner starts in it until then. Nor in a
    legacy pair's tunnel, which keeps it: the pair moves into the shared
    tunnel when its copy must start (_start_legacy, _replace_restarting_tunnels).

    A Test tunnel left behind by a worker that died during the test does not
    come back either: sweep_test_tunnels removes it.
    """
    labels = {
        LABEL_MANAGED: "true",
        LABEL_ROLE: ROLE_TUNNEL,
        LABEL_SERVICE: slug,
        LABEL_DEPLOYED_BY: "worker",
    }
    if proxy_id is not None:
        labels[LABEL_PROXY] = str(proxy_id)
    if tunnel_for:
        labels[LABEL_TUNNEL_FOR] = tunnel_for
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
        "restart_policy": {"Name": "no"},
        # tun2proxy runs at warn, so this log holds errors, never the sites the
        # earner reaches; the bound keeps even a noisy failure off the box disk.
        "log_config": {"type": "json-file", "config": {"max-size": "1m", "max-file": "2"}},
        "detach": True,
    }


def _wait_ready(container: Any, timeout: float = READY_TIMEOUT) -> dict[str, Any]:
    """Wait for /run/ready; returns the probe result {"ip", "country"}."""
    deadline = time.monotonic() + timeout
    fenced = False
    while time.monotonic() < deadline:
        container.reload()
        if container.status not in ("running", "created", "restarting"):
            break
        if container.status == "running":
            if not fenced:
                # Its bridge address exists only now: the fence lets it reach a
                # proxy or exit node on one of the owner's own exits (lan_fence.tunnel_allows).
                fenced = True
                lan_fence.tunnel_started()
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
        t("err.proxy_tunnel.tunnel_did_not_reach_internet", timeout=int(timeout))
        + (f" Tunnel log: {reason}" if reason else "")
    )


def _is_ip(value: Any) -> bool:
    """cp-probe keeps only IP characters of what an echo site answered, so an
    error page can still come through as "e"; only a real address counts."""
    try:
        ipaddress.ip_address(str(value or ""))
    except ValueError:
        return False
    return True


# A tunnel on a tailnet logs out when it is stopped, which deletes its
# ephemeral device; killed sooner, that device stays behind offline. The stop
# returns as soon as the logout is done, so this is a ceiling, not a wait.
SIDECAR_STOP_SECONDS = 10


def _remove_quietly(container: Any, stop_timeout: int = SIDECAR_STOP_SECONDS, *, volumes: bool = True) -> None:
    # A failed stop is no reason to keep the container; the removal is what matters.
    with contextlib.suppress(Exception):
        container.stop(timeout=stop_timeout)
    with contextlib.suppress(NotFound):
        container.remove(force=True, v=volumes)


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
    proxy: dict[str, Any] | None,
    own_ip: str | None,
    hostname: str | None = None,
    *,
    label: str | None = None,
    files: dict[str, str] | None = None,
    tunnel_for: str | None = None,
    deadline: float | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Create, provision and start a tunnel, then wait for its exit. Removed on any failure.

    ``label`` names the tunnel on the tailnet (``cashpilot-<label>``).
    ``files`` hands over settings already read from another tunnel (the
    migration of a legacy pair), instead of building them from ``proxy``.
    ``deadline`` (a deploy's, time.monotonic()) bounds the image pull, which
    has no overall timeout of its own (orchestrator._pull_until).
    """
    network = orchestrator.container_network("bridge")
    if files is None:
        if label is None:
            label = f"{slug}-p{proxy_id}" if proxy_id is not None else slug
        files = secret_files(proxy or {}, own_ip, label)
    # Files read from another tunnel (a migration) carry the password only
    # inside proxy_auth, so its decoded form is redacted too.
    secrets = [*_secret_values(proxy or {}), files.get("auth_key", ""), *_auth_secrets(files.get("proxy_auth", ""))]
    image = tunnel_image()
    if deadline is not None:
        if (refused := orchestrator._pull_until(client, image, deadline)) is not None:
            logger.warning("Could not pull %s: %s (trying the local copy)", image, refused)
    else:
        try:
            client.images.pull(image)
        except APIError as exc:
            logger.warning("Could not pull %s: %s (trying the local copy)", image, exc)
    kwargs = sidecar_kwargs(name, slug, proxy_id, network, hostname=hostname or _hostname(name), tunnel_for=tunnel_for)
    kwargs.pop("detach")
    container = client.containers.create(**kwargs)
    try:
        if not container.put_archive(SECRET_DIR, _secret_tar(files)):
            raise ProxyTunnelError(t("err.proxy_tunnel.could_not_hand_proxy_settings"))
        container.start()
        exit_info = _wait_ready(container)
    except Exception as exc:
        _remove_quietly(container, SIDECAR_STOP_SECONDS)
        if isinstance(exc, ProxyTunnelError):
            raise ProxyTunnelError(redact(str(exc), secrets), exc.status_code) from None
        detail = orchestrator.proxy_refusal(exc) or str(exc)
        raise ProxyTunnelError(redact(f"The tunnel could not start: {detail}", secrets)) from None
    return container, exit_info


def _routed_here(slug: str, proxy_id: int) -> bool:
    """Whether ``slug`` is routed through ``proxy_id`` on this worker (app/route_gate.py).

    Raises when the marker cannot be read: "not routed" would put a routed
    earner in the proxy's shared tunnel, beside the other services' earners.
    """
    try:
        return route_gate.routed().get(slug) == int(proxy_id)
    except (OSError, ValueError) as exc:
        raise ProxyTunnelError(t("err.proxy_tunnel.could_not_read_which_services", exc=exc, slug=slug), 503) from None


def copy_name(slug: str, proxy_id: int) -> str | None:
    """The name of the copy of ``slug`` through ``proxy_id`` on this worker, or None. Raises when Docker cannot answer."""
    earner = _get(orchestrator._get_client(), earner_name(slug, proxy_id))
    return earner.name if _is_ours(earner, slug, proxy_id) else None


def routed_copies(slug: str, marked: int | None) -> list[tuple[int, str]]:
    """(proxy id, name) of every routed copy of ``slug`` on this worker, through any proxy.

    A routed copy is an earner in a tunnel of its own. One whose tunnel is gone
    counts only when ``marked`` (the proxy the route mark names) is its proxy:
    _start brings it back in a tunnel of its own then, and in the proxy's
    shared tunnel otherwise. Raises when Docker cannot answer.
    """
    client = orchestrator._get_client()
    found = client.containers.list(
        all=True, filters={"label": [f"{LABEL_SERVICE}={slug}", f"{LABEL_MANAGED}=true", LABEL_PROXY]}
    )
    copies: list[tuple[int, str]] = []
    for earner in found:
        pid = _labels(earner).get(LABEL_PROXY, "")
        if not (_is_earner(earner) and _labels(earner).get(LABEL_SERVICE) == slug and pid.isdigit()):
            continue
        tunnel_id = _tunnel_id_of(earner)
        tunnel = _get(client, tunnel_id) if tunnel_id else None
        if (tunnel is None and marked is not None and int(pid) == int(marked)) or (
            tunnel is not None and _own_key(tunnel) == slug
        ):
            copies.append((int(pid), str(earner.name)))
    return sorted(copies)


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
    """A proxy's tunnel. Never one deploy_raw made: it sets LABEL_VERSION on every
    container, and a direct deploy once kept any other label it was given (see
    orchestrator.is_tunnel_sidecar)."""
    labels = _labels(container)
    return (
        labels.get(LABEL_MANAGED) == "true"
        and labels.get(LABEL_ROLE) == ROLE_TUNNEL
        and LABEL_VERSION not in labels
        and LABEL_PROXY in labels
        and (proxy_id is None or labels.get(LABEL_PROXY) == str(proxy_id))
    )


def _is_shared(container: Any | None, proxy_id: int | None = None) -> bool:
    """A tunnel the shared-tunnel code made: a proxy's shared one or a routed service's own."""
    return _is_tunnel(container, proxy_id) and _labels(container).get(LABEL_SERVICE) == SHARED_SLUG


def _is_tunnel_for(container: Any | None, proxy_id: int, slug: str | None) -> bool:
    """The proxy's shared tunnel (``slug`` None), or the routed service ``slug``'s own."""
    return _is_shared(container, proxy_id) and _labels(container).get(LABEL_TUNNEL_FOR) == slug


def _own_key(tunnel: Any | None) -> str | None:
    """Whose own tunnel this is: the routed service's slug, or None for a shared one."""
    return _labels(tunnel).get(LABEL_TUNNEL_FOR) or None


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


@dataclass(frozen=True)
class _StartApproval:
    selected: str
    expected: dict[str, str]
    grouped: bool = False


class StartTargetsChanged(ProxyTunnelError):
    def __init__(self, targets: dict[str, str]):
        super().__init__("Starting this copy requires replacing the listed containers in its shared tunnel.")
        self.targets = targets


def _require_settled_move(client: Any, name: str) -> None:
    """A staged or aside container is never a target the owner can approve."""
    canonical = name.removesuffix(STAGED_SUFFIX).removesuffix(MOVING_SUFFIX).removesuffix(orchestrator.REPLACED_SUFFIX)
    if canonical != name:
        raise RecoveryConflict(
            t("err.proxy_tunnel.recovery_skipped_container_still_holds", canonical=canonical, name=name)
        )
    for suffix in (STAGED_SUFFIX, MOVING_SUFFIX):
        if _get(client, name + suffix) is not None:
            raise RecoveryConflict(
                t("err.proxy_tunnel.recovery_skipped_container_still_holds_2", name=name, value=name + suffix)
            )


def _move_expected(client: Any, member: Any, target: _StartApproval | None) -> str:
    name = str(member.name)
    _require_settled_move(client, name)
    saved = _recorded_containers().get(name, "none") if target is None or not target.grouped else "none"
    expected = target.expected.get(name, saved) if target is not None else saved
    current = orchestrator.deploy_target(client, name)
    orchestrator.require_deploy_target(expected, current)
    orchestrator.require_deploy_target(expected, member)
    _require_settled_deploy(client, member)
    return expected


def _require_settled_deploy(client: Any, member: Any) -> None:
    """A copy whose redeploy is not settled is never moved, nor offered for approval.

    Its old earner aside (KEPT_MARKER may make it the copy) and the recorded
    pair are what the heartbeat settles it by (_settle_replaced). A clone of
    the replacement would match neither."""
    name = str(member.name)
    aside = _get(client, name + orchestrator.REPLACED_SUFFIX)
    _require_resolved_deploy(member, aside)
    if aside is not None or _recorded_failed(member):
        raise RecoveryConflict(t("err.proxy_tunnel.recovery_skipped_previous_deploy_has", name=name))


def _check_move_targets(client: Any, members: list[Any], target: _StartApproval | None) -> None:
    try:
        for member in members:
            _move_expected(client, member, target)
    except orchestrator.DeployTargetChanged:
        if target is None or not members:
            raise
        affected = {str(member.name): member for member in members}
        if target.selected not in affected:
            selected = orchestrator.deploy_target(client, target.selected)
            if selected is None:
                raise
            affected[target.selected] = selected
        if len(affected) == 1:
            raise
        approvals = {}
        for name, member in sorted(affected.items()):
            _require_settled_move(client, name)
            current = orchestrator.deploy_target(client, name)
            orchestrator.require_deploy_target(member.id, current)
            _require_settled_deploy(client, member)
            approvals[_labels(member)[LABEL_SERVICE]] = str(member.id)
        raise StartTargetsChanged(approvals) from None


def _clone_into(
    client: Any, member: Any, tunnel: Any, *, start: bool | None = None, target: _StartApproval | None = None
) -> Any:
    """Recreate ``member`` inside ``tunnel``'s namespace, from what Docker recorded.

    A container's network namespace is fixed when it is created, so moving an
    earner to another tunnel means a new container. The worker rebuilds it from
    ``inspect`` without contacting the UI. ``start``
    defaults to whether the member was running.

    Nothing is removed before its replacement holds the name: the clone is
    created under a staged name, the member stops and is renamed aside
    (MOVING_SUFFIX), the clone takes the name and starts, and only then is the
    member removed. The member stops first, so the one aside never runs: no
    Stop, Remove or deploy has to look for a second running copy of it. A
    failure on the way puts the member back under its name, started again in
    a ready run of its own tunnel when it ran (_put_back). In a tunnel an older
    worker made no earner starts, so there it stays stopped until the next try
    moves it, STAGED_STALE_SECONDS later (_replace_restarting_tunnels), and the
    heartbeat starts it in the new tunnel. A worker that dies on the way
    leaves both, and recover_moves() finishes or undoes the move.

    A member with host devices or a capability that reaches its tunnel's
    firewall (PROXIED_FORBIDDEN_CAPS) is never moved (_refuse_unmovable):
    the worker API gives a proxied copy neither. The clone gets what every
    proxied copy gets, whatever the member recorded: every capability dropped
    but its own CapAdd, and no-new-privileges.

    The clone starts only in a run of ``tunnel`` that is ready, as every
    earner does (_start_in_ready_run); in one that is not, it stays stopped
    and the heartbeat starts it once the run is ready.
    """
    member.reload()
    attrs = member.attrs or {}
    cfg = attrs.get("Config") or {}
    hc = attrs.get("HostConfig") or {}
    name = str(member.name)
    expected = _move_expected(client, member, target)
    service = _labels(member).get(LABEL_SERVICE)
    was_running = getattr(member, "status", "") in _LIVE
    _refuse_unmovable(member)
    staged = name + STAGED_SUFFIX
    aside = name + MOVING_SUFFIX
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
        # Volumes the image declares (an earner may keep its device id in
        # one) go with the copy: a fresh one would make it a new device.
        "volumes": {
            m["Name"]: {"bind": m["Destination"], "mode": "rw" if m.get("RW", True) else "ro"}
            for m in attrs.get("Mounts") or []
            if m.get("Type") == "volume" and m.get("Name") and m.get("Destination")
        }
        or None,
    }
    # Older copies may have inherited NVIDIA settings from their image. A
    # replacement must explicitly hide NVIDIA devices like a fresh deploy.
    environment = [entry for entry in cfg.get("Env") or [] if not entry.upper().startswith(gpu.ENV_PREFIX)]
    environment.extend(f"{key}={value}" for key, value in gpu.VOID_ENV.items())
    run_kwargs = dict(
        image=cfg.get("Image") or _image_of(member),
        name=staged,
        environment=environment,
        labels=dict(cfg.get("Labels") or _labels(member)),
        network_mode=f"container:{tunnel.id}",
        # As orchestrator.deploy_raw does for every proxied copy: every
        # capability dropped, then the member's own CapAdd, which
        # _refuse_unmovable checked against PROXIED_FORBIDDEN_CAPS only (the
        # catalog allowlist gated it when the copy was deployed; a move never
        # adds a capability the copy did not hold). A recorded partial CapDrop is never
        # carried: it would keep Docker's default NET_RAW, which can send
        # frames past the tunnel's firewall. Nor is a recorded
        # seccomp=unconfined or apparmor=unconfined.
        cap_drop=["ALL"],
        cap_add=hc.get("CapAdd") or None,
        security_opt=["no-new-privileges:true"],
        privileged=False,
        # Never started by Docker on its own: see orchestrator.deploy_raw.
        restart_policy={"Name": "no"},
        **{k: v for k, v in optional.items() if v is not None},
    )
    # The ID from Docker's create answer, recorded before the SDK's inspect:
    # one that times out leaves a clone recover_moves can identify.
    clone_id = orchestrator._create_container_id(client, run_kwargs)
    move = _created_key(name, str(member.id), clone_id)
    try:
        _record_pair(MOVE_MARKER, name, str(member.id), clone_id)
        clone = client.containers.get(clone_id)
        orchestrator.require_deploy_target(expected, orchestrator.deploy_target(client, name))
    except Exception:
        # By its ID, never its name. One Docker keeps is settled by the move record.
        with contextlib.suppress(Exception):
            client.api.remove_container(clone_id, force=True, v=False)
        raise
    try:
        with contextlib.suppress(Exception):
            member.stop(timeout=orchestrator._get_stop_timeout(service or ""))
        member.reload()
        if getattr(member, "status", "") in _LIVE:
            # Never two of one copy at once: the provider would see one device twice.
            raise ProxyTunnelError(t("err.proxy_tunnel.did_not_stop_not_moved", name=name))
        member.rename(aside)
    except Exception:
        _remove_quietly(clone, 2, volumes=False)
        _put_back(client, member, name, was_running)
        raise
    try:
        clone.rename(name)
        if start if start is not None else was_running:
            _start_in_ready_run(clone, tunnel, service or "")
    except Exception:
        _remove_quietly(clone, 2, volumes=False)
        _put_back(client, member, name, was_running)
        raise
    # Saved before the original goes: once it is gone, recover_moves no longer
    # sees this move, so a worker that stopped here would keep the old ID.
    _record_container(name, str(clone.id))
    try:
        member.remove(force=True, v=False)  # its volumes are the clone's now
    except NotFound:
        _set_id(MOVE_MARKER, move, False)
    except Exception as exc:  # noqa: BLE001 - a leftover only: recover_moves removes it
        logger.warning("Could not remove %s after it moved: %s", aside, exc)
    else:
        _set_id(MOVE_MARKER, move, False)
    clone.reload()
    return clone


def _refuse_unmovable(member: Any) -> None:
    """Refuse to move ``member`` into a tunnel when it holds what a proxied copy never gets.

    The worker API gives a proxied copy no host devices and none of
    PROXIED_FORBIDDEN_CAPS (_validate_proxied in app/worker_api.py), so one
    that has any was not made through it. In a tunnel's namespace they could
    change or bypass its firewall, for every copy that shares it. The move is
    refused before anything changed, and the copy stays as it is. So do the
    other copies in its tunnel, which move only with it: the owner removes
    that copy, and deploys it again if they want it."""
    hc = (getattr(member, "attrs", None) or {}).get("HostConfig") or {}
    name = str(member.name)
    what = ""
    if hc.get("Devices"):
        what = "host devices"
    elif hc.get("DeviceRequests"):
        what = "device requests"
    elif gpu.grant(_labels(member).get(LABEL_SERVICE)):
        what = "a catalog GPU grant"
    elif risky := sorted(
        {str(c).upper().removeprefix("CAP_") for c in hc.get("CapAdd") or []} & PROXIED_FORBIDDEN_CAPS
    ):
        what = ", ".join(risky)
    if what:
        raise ProxyTunnelError(t("err.proxy_tunnel.holds_which_proxied_copy_never", name=name, what=what))


def _put_back(client: Any, member: Any, name: str, was_running: bool) -> None:
    """Give a member whose move failed its name back, running if it ran, in a ready run of its own tunnel."""
    with contextlib.suppress(Exception):
        member.reload()
        if str(member.name) != name:
            member.rename(name)
        if was_running and getattr(member, "status", "") not in _LIVE:
            home = _get(client, tid) if (tid := _tunnel_id_of(member)) else None
            if _is_tunnel(home):
                _start_in_ready_run(member, home, _labels(member).get(LABEL_SERVICE, ""))


def _move_members(client: Any, old: Any, new: Any, *, target: _StartApproval | None = None) -> None:
    """Every earner of ``old`` into ``new``. On a failure the ones moved go back, unless no earner starts in ``old``.

    No earner starts in a tunnel Docker restarts on its own (_start_in_ready_run),
    so moving them back into one would recreate each a second time only to
    leave it stopped. They stay in ``new`` then, running if they ran, and
    ``new`` stays with them (the caller keeps a tunnel copies live in): the
    heartbeat finishes the change later (_finish_staged), and the copies left
    in ``old`` move then."""
    members = _members(client, old)
    _check_move_targets(client, members, target)
    moved: list[Any] = []
    try:
        for member in members:
            moved.append(_clone_into(client, member, new, target=target))
    except Exception:
        with contextlib.suppress(Exception):
            old.reload()
        if moved and _restarts_by_itself(old):
            logger.warning(
                "%d cop%s stay in the new tunnel of %s", len(moved), "y" if len(moved) == 1 else "ies", old.name
            )
            raise
        back_up = getattr(old, "status", "") == "running"
        for clone in moved:
            # Started again only where they can run: a tunnel Docker could not
            # start keeps them stopped, under their own names, for the next start.
            with contextlib.suppress(Exception):
                _clone_into(client, clone, old, start=back_up and getattr(clone, "status", "") in _LIVE)
        raise


def _shared_ready(client: Any, proxy_id: int, key: str | None = None) -> tuple[Any, dict[str, Any]] | None:
    """The proxy's shared tunnel (with ``key``, that routed service's own) when it runs and has written /run/ready."""
    current = _get(client, shared_tunnel_name(proxy_id, key))
    if not _is_tunnel_for(current, proxy_id, key) or getattr(current, "status", "") != "running":
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
    slug: str | None = None,
    deadline: float | None = None,
    keep: str | None = None,
    expected_container: str | None = None,
    move_target: _StartApproval | None = None,
) -> tuple[Any, dict[str, Any]]:
    """The proxy's shared tunnel, running on the given settings and ready; with
    ``slug``, the routed service's own tunnel through the proxy instead.

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
    is the way only when there is none yet, for an upgrade, when Docker
    cannot start this one at all (its container is broken), or when an older
    worker made it, so Docker would restart it on its own (_restarts_by_itself).

    ``keep`` names the earner the caller replaces itself (a deploy). When it
    is the only one in the tunnel being replaced, it is not recreated: that
    would lose its writable layer before the deploy can fail. The old tunnel
    keeps running with it inside, under RETIRED_SUFFIX, until the caller
    removes it once the new earner runs, or gives it its name back
    (_restore_retired).
    """
    label = shared_label(proxy_id, slug)
    files, secrets = _tunnel_settings(proxy, own_ip, label, files)
    image = tunnel_image()
    final = shared_tunnel_name(proxy_id, slug)
    staged = final + STAGED_SUFFIX
    _reclaim_retired(client, proxy_id, slug, final)
    current = _get(client, final)
    if current is not None and not _is_tunnel_for(current, proxy_id, slug):
        raise ProxyTunnelError(t("err.proxy_tunnel.container_named_cashpilot_did_not", final=final))
    leftover = _get(client, staged)
    if (
        _is_tunnel_for(leftover, proxy_id, slug)
        and _age_seconds(leftover) >= STAGED_STALE_SECONDS
        and _members(client, leftover)
    ):
        if expected_container is not None:
            raise ProxyTunnelError(t("err.proxy_tunnel.wait_worker_recover_previous_tunnel"))
        # A change that died after it began moving copies: finish it first.
        with _swap_lock:
            current = _finish_staged(client, leftover, current, final, target=move_target)
    broken = False
    # An older worker's tunnel, which Docker restarts on its own, is never used
    # as it is: replaced before any earner starts in it (_restarts_by_itself).
    if current is not None and not _restarts_by_itself(current) and (_image_of(current) == image or not upgrade):
        try:
            return _in_place(client, current, proxy, own_ip, files, secrets, deadline=deadline)
        except _Broken as exc:
            # Not refused for a retired name in the way, as below: the tunnel is
            # down now and Docker cannot start it, so its earners run again only
            # recreated in a new tunnel (a start would recreate them too).
            logger.warning("The tunnel of proxy %s cannot start in place (%s); replacing it", proxy_id, exc)
            broken = True
    elif current is not None:
        _refuse_foreign_retired_name(client, current, final, keep, proxy_id, slug)
    if current is not None:
        members = _members(client, current)
        if keep is None or any(str(m.name) != keep for m in members):
            # Refused before a new tunnel is pulled, started and logged in: a
            # copy that can never move (_refuse_unmovable) would only have it
            # thrown away, on every try.
            for member in members:
                _refuse_unmovable(member)
            if expected_container is None:
                _check_move_targets(client, members, move_target)
        # Before anything changes: the replacement must carry the recorded address.
        files = _carry_own_ip(current, files, replacing=True, broken=broken)
    # Left by a deploy that died midway, on this name only if it is ours. A young
    # one can belong to a deploy another worker on this daemon is running.
    if (leftover := _get(client, staged)) is not None:
        if not _is_tunnel_for(leftover, proxy_id, slug):
            raise ProxyTunnelError(t("err.proxy_tunnel.container_named_cashpilot_did_not_3", staged=staged))
        if _age_seconds(leftover) < STAGED_STALE_SECONDS:
            raise ProxyTunnelError(
                t("err.proxy_tunnel.another_change_proxy_s_tunnel", leftover=int(_age_seconds(leftover)))
            )
        _remove_quietly(leftover, SIDECAR_STOP_SECONDS)
    new, exit_info = start_sidecar(
        client,
        staged,
        SHARED_SLUG,
        proxy_id,
        proxy,
        own_ip,
        hostname=_hostname(final),
        label=label,
        files=files,
        tunnel_for=slug,
        deadline=deadline,
    )
    retired = False
    try:
        with _swap_lock:
            if current is not None:
                members = _members(client, current)
                if expected_container is not None and any(m.id != expected_container for m in members):
                    raise ProxyTunnelError(t("err.proxy_tunnel.deploy_cannot_replace_other_containers"))
                if _keep_aside(client, current, final, keep, proxy_id, slug):
                    current.rename(final + RETIRED_SUFFIX)
                    retired = True
                else:
                    if expected_container is not None and members:
                        raise ProxyTunnelError(t("err.proxy_tunnel.could_not_keep_approved_container"))
                    _move_members(client, current, new, target=move_target)
                    _remove_quietly(current, SIDECAR_STOP_SECONDS)
            new.rename(final)
    except Exception:
        if not _members(client, new):
            _remove_quietly(new, SIDECAR_STOP_SECONDS)
        if retired:
            with contextlib.suppress(Exception):
                current.rename(final)
        raise
    return new, exit_info


def _tunnel_settings(
    proxy: dict[str, Any] | None, own_ip: str | None, label: str, files: dict[str, str] | None = None
) -> tuple[dict[str, str], list[str]]:
    """The files a tunnel gets for ``proxy`` (or ``files``, already read), and every secret value to redact."""
    if files is None:
        try:
            files = secret_files(proxy or {}, own_ip, label)
        except ProxyTunnelError as exc:
            raise ProxyTunnelError(redact(str(exc), _secret_values(proxy or {})), exc.status_code) from None
    secrets = [*_secret_values(proxy or {}), files.get("auth_key", ""), *_auth_secrets(files.get("proxy_auth", ""))]
    return files, secrets


def _refuse_foreign_retired_name(
    client: Any, current: Any, final: str, keep: str | None, proxy_id: int, slug: str | None
) -> None:
    """Refuse, before anything changes, a replacement whose only earner ``keep`` cannot be kept aside.

    That happens when a container CashPilot did not make holds the retired
    name: _keep_aside could not rename the tunnel there, so the earner the
    caller replaces would be recreated in the new tunnel and lose its
    writable layer before the deploy can fail."""
    members = _members(client, current)
    if keep is None or not members or any(str(m.name) != keep for m in members):
        return
    in_way = _get(client, final + RETIRED_SUFFIX)
    if in_way is not None and not _is_tunnel_for(in_way, proxy_id, slug):
        raise ProxyTunnelError(t("err.proxy_tunnel.container_named_cashpilot_did_not_2", name=in_way.name, keep=keep))


def _keep_aside(client: Any, current: Any, final: str, keep: str | None, proxy_id: int, slug: str | None) -> bool:
    """Whether ``current`` stays, under RETIRED_SUFFIX, with ``keep`` inside: its only earner, which the caller replaces.

    A leftover of this same tunnel under that name with no earner left in it
    goes first; one that still holds an earner (a worker died in a deploy), or
    any other container there, is left, and this tunnel is replaced the old way."""
    members = _members(client, current)
    if keep is None or not members or any(str(m.name) != keep for m in members):
        return False
    if (leftover := _get(client, final + RETIRED_SUFFIX)) is not None:
        if not _is_tunnel_for(leftover, proxy_id, slug) or _members(client, leftover):
            return False
        _remove_quietly(leftover, SIDECAR_STOP_SECONDS)
    return True


def _reclaim_retired(client: Any, proxy_id: int, slug: str | None, final: str) -> None:
    """A tunnel left under RETIRED_SUFFIX with a copy still inside gets its name back, when that name is free or empty.

    A deploy that failed while Docker kept its failed earner, or a worker that
    died between the retirement and the new earner, leaves the old earner in
    its old tunnel under the other name. Without this, the next start or
    deploy would make a new tunnel and recreate that earner inside it, losing
    its writable layer. The caller holds the proxy's lock.
    """
    retired = _get(client, final + RETIRED_SUFFIX)
    if not _is_tunnel_for(retired, proxy_id, slug) or not _members(client, retired):
        return
    current = _get(client, final)
    if current is not None and (not _is_tunnel_for(current, proxy_id, slug) or _members(client, current)):
        return
    with _swap_lock:
        if current is not None:
            _remove_quietly(current, SIDECAR_STOP_SECONDS)
        retired.rename(final)
    logger.info("%s, kept aside by a redeploy that did not finish, has its name back", final)


def _restore_retired(client: Any, retired: Any, tunnel: Any) -> None:
    """After a failed deploy, the old tunnel _ensure_tunnel kept (``keep``) gets its name back, the new one goes.

    The old earner is back inside the old tunnel (deploy_raw puts it back), so
    the new tunnel is empty unless Docker refused to remove the failed earner;
    then both stay as they are, the old one still working under its other
    name, and the heartbeat removes the new one once it is empty."""
    final = str(retired.name).removesuffix(RETIRED_SUFFIX)
    try:
        with _swap_lock:
            _drop_if_empty(client, tunnel)
            if final != str(retired.name) and _get(client, final) is None:
                retired.rename(final)
    except Exception as exc:  # noqa: BLE001 - the deploy's own error is the one reported
        logger.warning("Could not give %s its name back after a failed deploy: %s", final, redact(str(exc)))


class _Broken(Exception):
    """Docker cannot write to or start this tunnel container at all."""


def _in_place(
    client: Any,
    current: Any,
    proxy: dict[str, Any] | None,
    own_ip: str | None,
    files: dict[str, str],
    secrets: list[str],
    *,
    deadline: float | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Bring ``current`` up on ``files`` without replacing the container. See _ensure_tunnel.

    Raises _Broken when Docker refuses the container itself (a daemon restart
    can leave one that cannot start), so the caller replaces it.
    """
    current.reload()
    running = current.status == "running"
    files = _carry_own_ip(current, files)
    # The container's log spans every setting it ever ran on (it is restarted
    # in place), so the old credentials are redacted from errors too.
    if old := _read_secret_file(current, "auth_key"):
        secrets = [*secrets, old]
    if old := _read_secret_file(current, "proxy_auth"):
        secrets = [*secrets, *_auth_secrets(old)]
    # The digest leaves own_ip out, but the leak guard reads it when the tunnel
    # starts: a new address restarts the tunnel as a settings change does. An
    # empty one (the worker could not tell its address) is no news:
    # _carry_own_ip put the recorded one in the files written below, or left
    # it out when it could not be read, so its file stays as it is.
    same = _read_secret_file(current, "settings") == files["settings"] and (
        not files.get("own_ip") or _read_secret_file(current, "own_ip") == files["own_ip"]
    )
    if running and same:
        with contextlib.suppress(ProxyTunnelError):
            return current, _wait_ready(current)
        logger.warning("The tunnel %s runs but has no exit; restarting it", current.name)
        previous = None
    elif running:
        _prove(client, proxy, own_ip, files, deadline=deadline)
        try:
            previous = {key: _read_secret_file_or_raise(current, key) or "" for key in SECRET_KEYS}
            # A first read above may have failed where this one worked.
            secrets = [*secrets, previous["auth_key"], *_auth_secrets(previous["proxy_auth"])]
        except Exception as exc:  # noqa: BLE001 - without them the old settings could not be put back
            raise ProxyTunnelError(
                t("err.proxy_tunnel.could_not_read_tunnel_s", exc=redact(str(exc), secrets))
            ) from None
    else:
        previous = None
    if running:
        with contextlib.suppress(APIError):
            current.stop(timeout=SIDECAR_STOP_SECONDS)
        current.reload()
        if current.status == "running":
            # Files written under a running tunnel would be recorded as its
            # settings while it still runs on the old ones.
            raise ProxyTunnelError(t("err.proxy_tunnel.docker_did_not_stop_settings", name=current.name))
    # Replacing the tunnel recreates every copy in it (a new device to each
    # provider), so a Docker error gets a second try first: only a container
    # Docker refuses twice is taken for broken.
    for attempt in (1, 2):
        try:
            # An own_ip _carry_own_ip left out could not be read: its file stays as it is.
            written = {key: files.get(key, "") for key in SECRET_KEYS if key != "own_ip" or "own_ip" in files}
            if not current.put_archive(SECRET_DIR, _secret_tar(written)):
                raise _Broken(t("err.proxy_tunnel.docker_did_not_take_settings"))
            current.start()
            break
        except (APIError, _Broken) as exc:
            if attempt == 2:
                raise _Broken(redact(str(exc), secrets)) from None
            logger.warning(
                "Docker refused the tunnel %s once (%s); trying again", current.name, redact(str(exc), secrets)
            )
            time.sleep(2)
    try:
        exit_info = _wait_ready(current)
    except ProxyTunnelError as exc:
        try:
            if previous is not None:
                # Proven a moment ago, failed here: back to what ran before,
                # and its copies back inside it.
                current.stop(timeout=SIDECAR_STOP_SECONDS)
                current.put_archive(SECRET_DIR, _secret_tar(previous))
                current.start()
                _wait_ready(current)
                _restart_members(client, current)
            elif not running:
                # Down, not leaking: its earners have no way out. Stopped so it
                # does not hold a tailnet device or a proxy session for nothing.
                current.stop(timeout=SIDECAR_STOP_SECONDS)
        except Exception as undo:  # noqa: BLE001 - the tunnel stays down, failing closed
            logger.warning("Could not put the old settings back into %s: %s", current.name, redact(str(undo), secrets))
        raise ProxyTunnelError(redact(str(exc), secrets), exc.status_code) from None
    _restart_members(client, current)
    return current, exit_info


def _carry_own_ip(
    current: Any, files: dict[str, str], *, replacing: bool = False, broken: bool = False
) -> dict[str, str]:
    """``files``, with the own_ip ``current`` has when they carry none.

    An empty own_ip means the worker could not tell its address this time. It
    must never replace a known one: cp-tunnel's leak guard lets any exit
    through when own_ip is empty, the box's own address too.

    A recorded address that cannot be read:

    * written into ``current`` itself (_in_place), is left out of the files,
      so its own_ip file stays as it is, never empty;
    * for a new tunnel ``replacing`` it, refuses the change before anything
      is changed: the old tunnel holds the address, and a later try (the
      read again, or a start that knows the address) carries it;
    * except when ``current`` is ``broken`` (Docker can neither start nor read
      it) and the worker never knows its address (CASHPILOT_EGRESS_DETECT=off).
      No try would ever carry it then, and refusing would keep its copies down
      for good. The new tunnel starts with no address to compare, as a first
      deploy with the address unknown does (docs/proxies.md).
    """
    if files.get("own_ip"):
        return files
    try:
        stored = _read_secret_file_or_raise(current, "own_ip")
    except Exception as exc:  # noqa: BLE001 - any failure but "not there" is unknown
        why = redact(str(exc))
        if replacing and not (broken and egress.detection_off()):
            raise ProxyTunnelError(
                t("err.proxy_tunnel.could_not_read_address_recorded", name=current.name, why=why)
            ) from None
        logger.warning(
            "Could not read the address %s recorded for this box (%s), and the worker cannot tell its own address "
            "now; %s",
            current.name,
            why,
            "its replacement starts with none to compare" if replacing else "keeping the recorded one where it is",
        )
        return {key: value for key, value in files.items() if key != "own_ip"}
    return {**files, "own_ip": stored} if stored else files


def _prove(
    client: Any,
    proxy: dict[str, Any] | None,
    own_ip: str | None,
    files: dict[str, str],
    *,
    deadline: float | None = None,
) -> None:
    """Start a throwaway Test tunnel on ``files`` and wait for its exit; it never stays."""
    trial = dict(files)
    if trial.get("kind") == "tailscale":
        trial["hostname"] = _ts_hostname(TEST_SLUG)
    name = f"{TUNNEL_PREFIX}test-{uuid.uuid4().hex[:10]}"
    sidecar, _ = start_sidecar(client, name, TEST_SLUG, None, proxy, own_ip, files=trial, deadline=deadline)
    _remove_quietly(sidecar, SIDECAR_STOP_SECONDS)


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
            _start_in_ready_run(member, tunnel, _labels(member).get(LABEL_SERVICE, ""), restart=True)
        except Exception as exc:  # noqa: BLE001 - the heartbeat tries again
            logger.warning("Could not restart %s into its tunnel: %s", member.name, exc)


def _start_in_ready_run(earner: Any, tunnel: Any, slug: str, *, restart: bool = False) -> bool:
    """Start (or restart) ``earner`` in ``tunnel``'s current run, only when that run is ready. Returns whether it did.

    Every earner start goes through here, under the proxy's lock, but a
    deploy's new earner, which deploy_raw starts under that lock right after
    _ensure_tunnel proved the run. Ready is read again here, never taken from
    the caller: an earner that joins a new run before its firewall is loaded
    could send from the box's own address. A shared tunnel this worker made
    has no restart policy (sidecar_kwargs) and the worker starts one only
    under that lock, so the run read here is the run the earner joins. A
    tunnel an older worker made (a shared one, or a legacy pair's) still has
    one, which the worker cannot take away, so nothing is started in it: a
    shared one is replaced first (_replace_restarting) and a legacy pair moves
    into the shared tunnel (_migrate_proxy), and the earner starts there. The
    run is still read again after every start (a person may start a tunnel by
    hand), and when it changed, or that read fails, the earner is stopped
    again, and the heartbeat starts it once the run it is in is ready.
    """
    timeout = orchestrator._get_stop_timeout(slug)
    tunnel.reload()
    run = _started_at(tunnel)
    if _restarts_by_itself(tunnel):
        logger.warning("The tunnel of %s restarts by itself (an older worker made it); not starting it", earner.name)
        return False
    if tunnel.status != "running" or _read_exit(tunnel) is None:
        logger.warning("The tunnel of %s is not ready; not starting it", earner.name)
        return False
    same = False
    try:
        if restart:
            earner.restart(timeout=timeout)
        else:
            earner.start()
    finally:
        try:
            tunnel.reload()
            same = tunnel.status == "running" and _started_at(tunnel) == run
        except Exception:  # noqa: BLE001 - a run that cannot be told is not proven
            same = False
        if not same:
            logger.warning(
                "The tunnel of %s restarted while it started, or could not be read; stopping it", earner.name
            )
            earner.stop(timeout=timeout)
    return same


def _moving(client: Any, proxy_id: str) -> list[str]:
    """Copies of a proxy that are half moved: aside or staged (see _clone_into)."""
    found = client.containers.list(all=True, filters={"label": [f"{LABEL_MANAGED}=true", f"{LABEL_PROXY}={proxy_id}"]})
    return [str(c.name) for c in found if _is_earner(c) and str(c.name).endswith((STAGED_SUFFIX, MOVING_SUFFIX))]


def _finish_staged(
    client: Any, staged: Any, current: Any | None, final: str, *, target: _StartApproval | None = None
) -> Any:
    """Finish a tunnel change a worker died in: the staged tunnel had proved its
    exit before any copy moved into it, so the copies left in ``current`` move
    across and it takes the final name. Returns the tunnel under ``final``.
    A staged tunnel that cannot prove its exit while ``current`` runs is undone
    instead (see _undo_staged).

    Refused while a copy of the proxy is still half moved: recover_moves must
    settle it first, or its container aside would be taken for a copy."""
    if half := _moving(client, _labels(staged).get(LABEL_PROXY, "")):
        raise RecoveryConflict(
            t(
                "err.proxy_tunnel.recovery_skipped_still_being_moved",
                half=", ".join(sorted(half)),
                value="is" if len(half) == 1 else "are",
            )
        )
    members = _members(client, current) if current is not None else []
    _check_move_targets(client, members, target)
    run = getattr(staged, "status", "") == "running"
    if current is not None and (
        getattr(current, "status", "") in _LIVE or any(getattr(m, "status", "") in _LIVE for m in members)
    ):
        # The current tunnel runs (after a reboot with every copy still down,
        # too): its copies never move into one that has not proved its exit
        # now. Running is no proof, and a tunnel Docker just restarted needs
        # its probe time to write /run/ready again.
        try:
            if not run:
                staged.start()
            _wait_ready(staged)
        except Exception:  # noqa: BLE001 - the detail may hold the proxy's secrets
            # Stopped, so it holds no proxy login while nothing can use it.
            with contextlib.suppress(Exception):
                staged.stop(timeout=SIDECAR_STOP_SECONDS)
            why = "runs but has no exit" if run else "could not start"
            return _undo_staged(client, staged, current, f"The new tunnel of {final} {why}")
        run = True
    if current is not None:
        members = _members(client, current)
        _check_move_targets(client, members, target)
        for member in members:
            _clone_into(client, member, staged, start=run and getattr(member, "status", "") in _LIVE, target=target)
        _remove_quietly(current, SIDECAR_STOP_SECONDS)
    staged.rename(final)
    logger.info("Finished moving the copies of %s into its new tunnel", final)
    return staged


def _undo_staged(client: Any, staged: Any, current: Any, why: str) -> Any:
    """Undo a tunnel change whose staged tunnel never proved its exit, while
    ``current`` runs: the copies already in the staged tunnel go
    back into ``current`` and the staged tunnel goes. Returns ``current``.

    Retrying the staged tunnel on its own settings can fail for good (a login
    that no longer works), and a deploy's new settings are written only into
    ``current``. Moved back, every copy has an exit and a deploy can fix it."""
    try:
        _move_members(client, staged, current)
    except Exception as exc:  # noqa: BLE001 - the detail may hold the proxy's secrets
        raise ProxyTunnelError(
            t("err.proxy_tunnel.copies_could_not_move_back", why=why, name=current.name, exc=redact(str(exc)))
        ) from None
    _remove_quietly(staged, SIDECAR_STOP_SECONDS)
    logger.warning("%s; its copies moved back into %s", why, current.name)
    return current


def _drop_if_empty(client: Any, tunnel: Any | None) -> list[str]:
    """Remove a shared tunnel, and its secret volume, once no earner lives in it."""
    if tunnel is None or not _is_shared(tunnel) or _members(client, tunnel):
        return []
    _remove_quietly(tunnel, SIDECAR_STOP_SECONDS)
    return [str(tunnel.name)]


# ---------------------------------------------------------------------------
# Deploy, stop, start, remove
# ---------------------------------------------------------------------------


def deploy(
    slug: str,
    proxy_id: int,
    earner: dict[str, Any],
    proxy: dict[str, Any],
    own_ip: str | None,
    *,
    only_if_running: bool = False,
    expected_container: str | None = None,
    deadline: float | None = None,
) -> dict:
    """Deploy (or replace) the proxied copy of ``slug`` through proxy ``proxy_id``.

    The proxy's shared tunnel is made ready first (see _ensure_tunnel): a
    second copy through a proxy that already has a ready tunnel on these
    settings creates only its earner and touches no other copy. Then the old
    earner of this copy goes (with its tunnel, when it is a legacy pair), and
    the new one is created inside the shared tunnel's namespace. A tunnel that
    cannot start therefore costs nothing.

    A routed service (the route mark names this proxy) gets a tunnel of its
    own instead; a tunnel it leaves goes once no copy is left in it. The mark
    is read under the lock that chooses the tunnel, so a routed deploy that
    finished while this one waited is seen, and its copy never lands in the
    proxy's shared tunnel beside other services.

    ``only_if_running`` replaces only a copy that runs and that the owner or
    the cap did not stop, and changes nothing otherwise (409). It is checked
    under the lock a stop takes, so a stop that came first always wins.

    The service's lock (route_gate.deploying) is held from the mark read to
    the earner, as every route change holds it: a route can never move while
    a copy built by the old one is still being made.

    ``deadline`` (time.monotonic(); by default DEPLOY_DEADLINE_SECONDS from
    now) is counted by the worker API from the request's arrival, as a direct
    deploy's is: past it, no earner is created and the running copy is not
    touched, however long the locks above or the tunnel's pull took. The UI
    holds the copy's ids for an unanswered deploy only that long and a few
    hours more (database.PENDING_IDENTITY_SECONDS).
    """
    if deadline is None:
        deadline = time.monotonic() + DEPLOY_DEADLINE_SECONDS
    with route_gate.deploying(slug), _deploy_lock(proxy_id):
        # The waits for both locks have no bound of their own.
        orchestrator._refuse_past(deadline, str(earner.get("image") or slug))
        if only_if_running:
            _require_running(slug, proxy_id)
        return _deploy(
            slug,
            proxy_id,
            earner,
            proxy,
            own_ip,
            own_tunnel=_routed_here(slug, proxy_id),
            deadline=deadline,
            expected_container=expected_container,
        )


def _require_running(slug: str, proxy_id: int) -> None:
    name = earner_name(slug, proxy_id)
    earner = _get(orchestrator._get_client(), name)
    try:
        stopped = name in held()
    except OSError as exc:
        raise ProxyTunnelError(t("err.proxy_tunnel.could_not_read_which_copies", exc=exc, name=name)) from None
    if not _is_ours(earner, slug, proxy_id) or stopped or getattr(earner, "status", "") not in _LIVE:
        raise ProxyTunnelError(t("err.proxy_tunnel.not_running_left", name=name))


def _deploy(
    slug: str,
    proxy_id: int,
    earner: dict[str, Any],
    proxy: dict[str, Any],
    own_ip: str | None,
    *,
    own_tunnel: bool = False,
    expected_container: str | None = None,
    deadline: float,
) -> dict:
    client = orchestrator._get_client()
    key = slug if own_tunnel else None
    # Checked first: settings that cannot work (a host that does not resolve,
    # no tunnel image) fail fast, before a tunnel is created.
    secret_files(proxy, own_ip, shared_label(proxy_id, key))
    tunnel_image()
    name = earner_name(slug, proxy_id)
    if expected_container is not None:
        orchestrator.require_deploy_target(expected_container, orchestrator.deploy_target(client, name))
    _settle_before_deploy(client, name, slug, proxy_id)
    # A new tunnel image is taken only when no other copy would be recreated
    # for it (see _ensure_tunnel): this copy's own earner is replaced anyway.
    # Including a staged tunnel's copies, which _ensure_tunnel may finish first.
    others = [
        m
        for tunnel_item in (
            _get(client, shared_tunnel_name(proxy_id, key)),
            _get(client, shared_tunnel_name(proxy_id, key) + STAGED_SUFFIX),
            # And one a failed redeploy left retired: _ensure_tunnel gives it its name back first.
            _get(client, shared_tunnel_name(proxy_id, key) + RETIRED_SUFFIX),
        )
        if _is_tunnel_for(tunnel_item, proxy_id, key)
        for m in _members(client, tunnel_item)
        if str(m.name) != name
    ]
    old = _get(client, name)
    old_tunnel = _tunnel_of(client, old if _is_ours(old, slug, proxy_id) else None, slug, proxy_id)
    # The earner's image is pulled before anything changes, as a direct deploy
    # pulls before it touches the old container, and before the tunnel: a new
    # tunnel image recreates this copy's earner in a new tunnel (_ensure_tunnel),
    # which loses its writable layer. A pull still running at the deadline, or a
    # tag with no image anywhere, leaves the old copy and its tunnel as they were.
    image = str(earner["image"])
    if (refused := orchestrator._pull_until(client, image, deadline)) is not None:
        logger.warning("Failed to pull image %s: %s (trying local)", image, refused)
        try:
            client.images.get(image)
        except DockerException:
            raise orchestrator.ContainerRuntimeError(
                t("err.proxy_tunnel.not_available_worker_running_copy", image=image, refused=refused)
            ) from None
    if expected_container is not None:
        orchestrator.require_deploy_target(expected_container, orchestrator.deploy_target(client, name))
    tunnel, exit_info = _ensure_tunnel(
        client,
        proxy_id,
        proxy,
        own_ip,
        upgrade=not others,
        slug=key,
        deadline=deadline,
        keep=name,
        expected_container=expected_container,
    )
    # The old tunnel a new tunnel image left running with the old earner inside
    # (keep): removed below once the new earner runs, renamed back on a failure.
    retired = _get(client, shared_tunnel_name(proxy_id, key) + RETIRED_SUFFIX)
    if retired is None or old_tunnel is None or retired.id != old_tunnel.id or retired.id == tunnel.id:
        retired = None
    # Past the deadline (a slow tunnel start), the old copy is left as it was.
    try:
        orchestrator._refuse_past(deadline, image)
        try:
            # A stopped copy stays recorded as stopped until its replacement
            # runs: a worker that dies on the way never starts the old earner.
            was_held = name in held()
        except OSError as exc:
            raise ProxyTunnelError(t("err.proxy_tunnel.could_not_read_which_copies", exc=exc, name=name)) from None
        # The old earner is not removed here: deploy_raw replaces it, keeping it
        # aside until the new one runs and putting it back if the deadline passes
        # while it stops or the new one fails. Its legacy tunnel goes only after.
        previous = _get(client, name)
        orchestrator.require_deploy_target(expected_container, previous)
        if was_held:
            # The stop is cleared once the new earner runs; a marker the disk
            # will not take refuses the deploy now, before anything changes.
            _set_held(name, True, strict=True, rewrite=True)
        first = previous is None or not _is_ours(previous, slug, proxy_id)
        if not first:
            # Read now, while a failure changes nothing: a name a dead first
            # deploy left there is bound to the earner it left, before the
            # replacement exists, so it keeps saying that earner is not the
            # copy (a rollback puts it back) and never names the replacement,
            # even when clearing it after the deploy fails.
            try:
                stale_new = name in _read_names(NEW_MARKER)
            except OSError as exc:
                raise ProxyTunnelError(
                    t("err.proxy_tunnel.could_not_read_which_deploys_2", exc=exc, name=name)
                ) from None
            if stale_new:
                _bind_new(name, str(previous.id))
            # On disk before deploy_raw moves it aside: until this deploy says
            # how it ended, the old earner aside is the copy (_aside_is_copy).
            _set_kept(str(previous.id), True, strict=True)
        else:
            # No old earner to keep: until this deploy says how it ended, what
            # it creates is not the copy (_recorded_failed).
            _set_new(name, True, strict=True)
    except Exception:
        if retired is not None:
            _restore_retired(client, retired, tunnel)
        else:
            _drop_if_empty(client, tunnel)
        raise
    previous_id = "none" if first else str(previous.id)
    created_id = None

    def on_created(container_id: str) -> None:
        nonlocal created_id
        created_id = container_id
        _record_created(name, previous_id, container_id)

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
            deadline=deadline,
            pulled=True,
            expected_container=expected_container,
            on_created=on_created,
        )
        # Recorded as done before it is reported, or undone below: a record
        # left saying otherwise would have the heartbeat undo it.
        _commit(client, name, None if first else previous, clear_new=first)
        _record_container(name, str(container_id))
        if first:
            _forget_created(name, previous_id, str(container_id))
    except Exception as exc:
        # docker-py's run leaves the container created when only its start
        # fails; the heartbeat would start it later, outside the owner's view.
        # Never the old earner deploy_raw put back. A removal Docker refuses
        # neither hides the deploy's own error nor skips the put back:
        # _settle_replaced tries it again, and _start_when_ready never starts a
        # failed one while the old earner is aside.
        # The failed one is recorded first, whatever state it is in (one whose
        # start got no answer can be "exited"): while Docker keeps it, the old
        # earner aside stays the copy, here and in every later heartbeat.
        # A read or a record that fails here (the daemon that did not answer the
        # start may not answer this either) skips neither the put back nor the
        # tunnel restore: the old earner aside stays the copy through KEPT_MARKER.
        # On a redeploy the new earner goes only while the old one is still
        # here to be put back: once deploy_raw has removed it (a commit that
        # failed after), or while Docker is removing it, the new one is the
        # only copy left. Not known: kept.
        try:
            left = _get(client, name)
            if (
                not isinstance(exc, orchestrator.DeployTargetChanged)
                and left is not None
                and left.id == created_id
                and (first or not _going(_get(client, str(previous.id))))
            ):
                _set_failed(str(left.id), True)
                with contextlib.suppress(Exception):
                    _remove_quietly(left, 2)
                    _set_failed(str(left.id), False)
                    left = None
            if first and (left is None or isinstance(exc, orchestrator.DeployTargetChanged)):
                _set_new(name, False)
            if created_id and (left is None or left.id != created_id):
                _forget_created(name, previous_id, created_id)
        except Exception as exc:  # noqa: BLE001 - the deploy's own error is the one reported
            logger.warning("Could not check what the failed deploy of %s left: %s", name, redact(str(exc)))
        with contextlib.suppress(Exception):
            _put_old_back(client, name, slug, proxy_id, was_held)
            if previous is not None and _get(client, name + orchestrator.REPLACED_SUFFIX) is None:
                _set_kept(str(previous.id), False)
        if retired is not None:
            _restore_retired(client, retired, tunnel)
        else:
            _drop_if_empty(client, tunnel)
        raise
    # The new earner runs, so the stop is cleared now, never before: a copy
    # left running while recorded as stopped is only not restarted after a
    # reboot, where one started while the owner or the cap stopped it earns
    # past the stop. A failure here is logged; the deploy is done.
    if was_held:
        _set_held(name, False)
    if not first and stale_new:
        # Names the old earner, which is gone: one left behind names nothing.
        _set_new(_new_key(name, str(previous.id)), False)
    # The volumes its image declared went with the old earner when it was
    # removed before its replacement: the new copy starts on fresh ones.
    if previous is not None and previous.id != container_id and _is_ours(previous, slug, proxy_id):
        _remove_anonymous_volumes(client, previous)
    # The old copy's legacy tunnel, now that no earner needs its namespace.
    # The new earner already runs: a Docker error here leaves a tunnel with no
    # copy behind, and never reports the deploy as failed.
    try:
        legacy = _get(client, tunnel_name(slug, proxy_id))
    except Exception as exc:  # noqa: BLE001 - logged; the deploy is done
        logger.warning("Could not look for the legacy tunnel of %s: %s", name, redact(str(exc)))
        legacy = None
    for candidate in {
        tunnel_item.id: tunnel_item
        for tunnel_item in (old_tunnel, legacy)
        if tunnel_item is not None and tunnel_item.id != tunnel.id
    }.values():
        if _is_tunnel(candidate, proxy_id) and not _is_shared(candidate) and _is_ours(candidate, slug, proxy_id):
            try:
                with _swap_lock:
                    _remove_quietly(candidate, SIDECAR_STOP_SECONDS)
            except Exception as exc:  # noqa: BLE001 - logged; the deploy is done
                logger.warning(
                    "Could not remove %s, the legacy tunnel of %s: %s", candidate.name, name, redact(str(exc))
                )
    if old_tunnel is not None and old_tunnel.id != tunnel.id:
        # The shared tunnel this copy left for its own, or the other way round.
        with contextlib.suppress(Exception):
            _drop_if_empty(client, _get(client, old_tunnel.id))
    return {"container_id": container_id, "tunnel_id": tunnel.id, "exit": exit_info}


def _commit(client: Any, name: str, previous: Any | None, *, clear_new: bool) -> None:
    """Record that the deploy of ``name`` went through, before it is reported. ProxyTunnelError when it cannot.

    The heartbeat undoes the earner of a first deploy still recorded
    (NEW_MARKER), and the earner beside an old earner still recorded aside
    (KEPT_MARKER). So the first record is cleared (``clear_new``: this deploy
    wrote it; one a redeploy found is bound to the old earner), and the second is cleared or its
    old earner is gone, before the deploy is reported as done. When that
    cannot be done the caller undoes the deploy: the old earner is never lost,
    and a deploy reported as done is never undone.
    """
    if clear_new and not _set_new(name, False):
        raise ProxyTunnelError(t("err.proxy_tunnel.not_deployed_worker_could_not", name=name))
    if previous is None or _set_kept(str(previous.id), False):
        return
    # deploy_raw removes the old earner once the new one runs, so one gone (by
    # id, whatever its name) leaves a record that names nothing: done. One
    # Docker would not remove then is a leftover now: it goes before the
    # deploy is reported.
    try:
        aside = _get(client, str(previous.id))
    except Exception as exc:  # noqa: BLE001 - reported; the caller keeps the new earner (not known gone)
        raise ProxyTunnelError(
            t("err.proxy_tunnel.may_not_have_been_replaced", name=name, exc=redact(str(exc)))
        ) from None
    if aside is None or str(aside.name) == name:
        return
    try:
        _remove_quietly(aside, 2, volumes=False)
    except Exception as exc:  # noqa: BLE001 - reported, and the deploy undone
        # A removal can take effect and still error (a timed-out DELETE): one
        # gone after all, or one Docker is still removing (it can never run or
        # be put back again), is a success, never a failure reported over the
        # new copy, which is then the only one left.
        with contextlib.suppress(Exception):
            if _going(_get(client, str(previous.id))):
                return
        raise ProxyTunnelError(
            t("err.proxy_tunnel.not_replaced_worker_could_not", name=name, exc=redact(str(exc)))
        ) from None


def _put_old_back(client: Any, name: str, slug: str, proxy_id: int, was_held: bool) -> None:
    """After a failed redeploy, the old earner deploy_raw kept: under its name, held if it was, running if it should.

    deploy_raw leaves it aside when the failed container still held the name
    (removed since), and never starts it itself (see orchestrator._start_again):
    it is started here only once its tunnel says it is ready, as the heartbeat
    would. The caller holds the proxy's lock.
    """
    if was_held:
        # The deploy keeps the stop until its earner runs; recorded again in
        # case it went, first, so no step below that fails can skip it: the
        # heartbeat would then give the old earner its name back and start it.
        _set_held(name, True)
    if (aside := _get(client, name + orchestrator.REPLACED_SUFFIX)) is not None:
        _settle_replaced(client, aside)
    if was_held:
        return
    old = _get(client, name)
    if old is None or not _is_ours(old, slug, proxy_id):
        return
    sidecar = _tunnel_of(client, old, slug, proxy_id)
    if sidecar is not None and _read_exit(sidecar) is not None:
        _start_when_ready(old, sidecar, slug, ready=True)


def _settle_before_deploy(client: Any, name: str, slug: str, proxy_id: int, *, expected: str | None = None) -> None:
    """Settle an old earner a failed redeploy left aside, before a deploy or a start touches anything.

    deploy_raw takes a ``<name>-replaced`` of the same copy for a leftover and
    removes it (orchestrator._move_aside). After a failed redeploy whose
    container Docker would not remove, that aside is the real copy: it is put
    back first, and while the failed container still holds the name the deploy
    (or start, which would run the failed one) is refused. The caller holds the
    proxy's lock.
    """
    aside_name = name + orchestrator.REPLACED_SUFFIX
    aside = _get(client, aside_name)
    if not _is_aside_of(aside, name):
        return  # none, or not this copy's old earner: deploy_raw's to handle, as before
    try:
        _settle_replaced(client, aside, expected=expected)
    except (RecoveryConflict, orchestrator.DeployTargetChanged):
        raise
    except Exception as exc:  # noqa: BLE001 - what is left is checked below
        logger.warning("Could not settle %s before a deploy: %s", aside_name, redact(str(exc)))
    current = _get(client, name)
    if not _is_aside_of(aside := _get(client, aside_name), name):
        return
    if not (_is_ours(current, slug, proxy_id) and _is_earner(current)):
        # The name is free and the aside could not get it back: it is the copy,
        # and a deploy now would be undone by the heartbeat that settles it.
        raise ProxyTunnelError(t("err.proxy_tunnel.left_previous_copy_could_not", name=name, aside_name=aside_name))
    try:
        failed = _aside_is_copy(current, aside)
    except OSError:
        failed = True  # not known: the copy aside is never taken for a leftover
    if failed:
        raise ProxyTunnelError(t("err.proxy_tunnel.left_docker_has_not_yet", name=name, aside_name=aside_name))


def _settle_replaced(client: Any, aside: Any, *, expected: str | None = None) -> str | None:
    """Settle a redeploy using the IDs it recorded, under the proxy's lock."""
    aside_name = str(aside.name)
    name = aside_name.removesuffix(orchestrator.REPLACED_SUFFIX)
    if name == aside_name or not _is_aside_of(aside, name):
        return None
    current = orchestrator.deploy_target(client, name)
    orchestrator.require_deploy_target(expected, current)
    if current is None:
        aside.rename(name)
        _set_kept(str(aside.id), False)
        return f"restored {name}"
    if current.id == aside.id:
        return None  # one container under both names: a stale read of one already restored
    _require_resolved_deploy(current, aside)
    try:
        failed = _aside_is_copy(current, aside)
    except OSError as exc:
        # Not known whether the deploy went through: both stay as they are.
        logger.warning("Could not read which replacements failed (%s); %s is left aside", exc, aside_name)
        return None
    if failed:
        # deploy_raw keeps the old one aside for exactly this: the failed one
        # goes first (a refusal raises, and both stay as they are).
        _remove_quietly(current, 2)
        _set_failed(str(current.id), False)
        aside.rename(name)
        _set_kept(str(aside.id), False)
        _forget_created(name, str(aside.id), str(current.id))
        return f"restored {name}"
    # As deploy_raw would have removed it once its replacement ran.
    _remove_quietly(aside, 2, volumes=False)
    _remove_anonymous_volumes(client, aside)
    _forget_created(name, str(aside.id), str(current.id))
    return f"removed {aside_name}"


def _is_aside_of(aside: Any | None, name: str) -> bool:
    """Whether ``aside`` is the copy ``name``'s own earner (by its labels), so one _settle_replaced handles."""
    labels = _labels(aside)
    pid = labels.get(LABEL_PROXY, "")
    return (
        aside is not None
        and _is_earner(aside)
        and pid.isdigit()
        and name == earner_name(labels.get(LABEL_SERVICE, ""), int(pid))
    )


_LIVE = ("running", "restarting")
_ANONYMOUS_VOLUME = re.compile(r"[0-9a-f]{64}")


def _remove_anonymous_volumes(client: Any, container: Any) -> None:
    """The anonymous volumes a removed ``container`` had, as ``remove(v=True)`` would have taken them."""
    for mount in (getattr(container, "attrs", None) or {}).get("Mounts") or []:
        name = str(mount.get("Name") or "")
        if mount.get("Type") == "volume" and _ANONYMOUS_VOLUME.fullmatch(name):
            # One still in use or already gone is left: a leftover volume only.
            with contextlib.suppress(Exception):
                client.volumes.get(name).remove()


def stop(slug: str, proxy_id: int) -> dict[str, Any]:
    """Stop one copy. The answer says whether it was running (``was_running``).

    Docker answers a stop of a stopped container with success, so the cap asks
    this to tell a copy it stopped from one the owner had already stopped.
    A stop whose record may not survive a power cut still answers, as a start
    does (_started): ``durable`` False and a ``warning``.

    The stop is written down first (HELD_MARKER), so a stop that fails halfway
    is never undone by the heartbeat. The shared tunnel stops too once no copy
    that should run is left in it. A legacy pair stops as before: tunnel first.
    """
    with _deploy_lock(proxy_id):
        return _stop(slug, proxy_id)


def _stop(slug: str, proxy_id: int) -> dict[str, Any]:
    client = orchestrator._get_client()
    name = earner_name(slug, proxy_id)
    earner = _get(client, name)
    earner = earner if _is_ours(earner, slug, proxy_id) else None
    tunnel = _tunnel_of(client, earner, slug, proxy_id)
    # A worker that died mid-move (_clone_into) may leave the copy only as its
    # two halves, aside and staged, with no tunnel of its own to find it by, and
    # a failed redeploy only as its old earner aside (<name>-replaced). The
    # heartbeat gives one of them the name later (recover_moves,
    # _settle_replaced) and would start it: the stop is written down for it all
    # the same, and they stop.
    halves = tuple(
        c
        for c in (
            _get(client, name + MOVING_SUFFIX),
            _get(client, name + STAGED_SUFFIX),
            _get(client, name + orchestrator.REPLACED_SUFFIX),
        )
        if _is_ours(c, slug, proxy_id) and _is_earner(c)
    )
    if earner is None and tunnel is None and not halves:
        raise ValueError(t("err.proxy_tunnel.no_proxied_copy_through_proxy", slug=slug, proxy_id=proxy_id))
    try:
        was_held = name in held()
    except OSError as exc:
        raise ProxyTunnelError(t("err.proxy_tunnel.could_not_read_which_copies", exc=exc, name=name)) from None
    tunnel_live = tunnel is not None and getattr(tunnel, "status", "") in _LIVE
    # was_running is "the owner wanted this copy running", for the cap to mark
    # it for its reset. A copy the owner never stopped is wanted in any form
    # and state: down for its tunnel, after a reboot, or left as a half or an
    # aside, the heartbeat would start it. A held one is not, unless it still
    # runs: a stop that failed halfway (an error, so the cap did not mark it)
    # and is tried again must still be marked. A named earner outside a
    # shared tunnel (in its own legacy tunnel, or one that is gone) is the
    # exception: an older worker's stop left no marker, the heartbeat never
    # starts it, and Docker restarts a legacy tunnel unless its owner stopped
    # it (_status), so down and unheld means stopped by its owner. So is a
    # legacy tunnel left with no earner. They count only live, or the tunnel
    # live and the copy not held. A copy with halves or an aside keeps the
    # rule, named earner or not: migrate_legacy moves only a pair that was
    # wanted running.
    live = any(getattr(c, "status", "") in _LIVE for c in (earner, *halves) if c is not None)
    if not halves and not _is_shared(tunnel):  # a named earner or a legacy tunnel: _stop raised on neither
        was_running = live or (tunnel_live and not was_held)
    else:
        was_running = not was_held or live
    try:
        _set_held(name, True, strict=True)
    except _RecordNotFlushed as exc:
        # The marker says stopped, but a power cut may lose it: the copy is
        # stopped all the same, the safe way, and the answer says so. Never an
        # error: the cap would read it as "could not stop" and never mark the
        # copy, and a second stop finds it held (was_running False), so its
        # reset would never start it again.
        ran, half_failure = _halt(client, slug, earner, tunnel, tunnel_live, was_running, halves)
        warning = (
            f"{name} was stopped, but the stop may not survive a power cut. {exc}. Stop it again once the disk "
            "is healthy."
        )
        return _stopped(name, ran, half_failure, warning, durable=False)
    ran, half_failure = _halt(client, slug, earner, tunnel, tunnel_live, was_running, halves)
    return _stopped(name, ran, half_failure)


def _stopped(
    name: str, was_running: bool, half_failure: Exception | None, warning: str | None = None, *, durable: bool = True
) -> dict[str, Any]:
    """The answer of a stop that stopped the copy: ``was_running``, and ``durable`` False and a ``warning`` when due.

    A half of an interrupted move, or an old earner aside, that could not stop (_halt) is a warning, never
    an error: the copy and its tunnel are down and the stop is in the marker, so
    an error would make the cap read "could not stop" and never mark the copy,
    and a second stop finds it held (was_running False), so its reset would
    never start it again."""
    out: dict[str, Any] = {"was_running": was_running}
    notes = [warning] if warning else []
    if half_failure is not None:
        notes.append(
            f"{name} was stopped, but what an interrupted move or redeploy left of it could not be stopped ({half_failure}). "
            "Stop it again."
        )
    if not durable:
        out["durable"] = False
    if notes:
        out["warning"] = " ".join(notes)
    return out


def _halt(
    client: Any, slug: str, earner: Any, tunnel: Any, tunnel_live: bool, was_running: bool, halves: tuple[Any, ...] = ()
) -> tuple[bool, Exception | None]:
    """_stop's work once the stop is in the marker: the earner down, and its tunnel when no copy in it should run.

    ``halves`` are what a move a worker died in, or a failed redeploy, left of the copy (_stop): down too.
    A half that cannot stop never keeps the earner and its tunnel up. One that
    was down (the usual case: the member stops before its rename, and a clone
    is not started) never makes the stop an error: its first failure is
    returned with ``was_running``, for the answer's warning (_stopped). One
    that still runs is raised once the earner and the tunnel are down, as a
    failure to stop the earner is: the copy still runs, so the cap must retry."""
    half_failure = None
    live_failure = None
    for half in halves:
        was_live = getattr(half, "status", "") in _LIVE
        try:
            half.stop(timeout=orchestrator._get_stop_timeout(slug))
        except NotFound:
            pass
        except Exception as exc:  # noqa: BLE001 - a warning, or raised once the earner and the tunnel are down
            if was_live:
                live_failure = live_failure or exc
            else:
                half_failure = half_failure or exc
    if tunnel is not None and not _is_shared(tunnel):
        tunnel.stop(timeout=SIDECAR_STOP_SECONDS)
        if earner is not None:
            earner.stop(timeout=orchestrator._get_stop_timeout(slug))
        if live_failure is not None:
            raise live_failure
        return was_running, half_failure
    failure = live_failure
    if earner is not None:
        try:
            earner.stop(timeout=orchestrator._get_stop_timeout(slug))
        except Exception as exc:  # noqa: BLE001 - raised below, after the tunnel
            failure = failure or exc
    if tunnel is not None and tunnel_live:
        # Also when the earner did not stop: with no copy that should run left,
        # stopping the tunnel cuts the earner's way out all the same.
        try:
            stopped = held()
        except OSError:
            stopped = None  # the tunnel keeps running: safe, and the next stop tries again
        if stopped is not None and not any(str(m.name) not in stopped for m in _members(client, tunnel)):
            tunnel.stop(timeout=SIDECAR_STOP_SECONDS)
    if failure is not None:
        raise failure
    return was_running, half_failure


def start(
    slug: str,
    proxy_id: int,
    proxy: dict[str, Any] | None = None,
    own_ip: str | None = None,
    *,
    expected_container: str | None = None,
    expected_containers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Start one copy: its tunnel ready first, then the earner.

    ``proxy`` is the proxy as it is stored now, so an edit (a new password,
    port, auth key or exit node) reaches the tunnel on this start; see
    _ensure_tunnel for how a tunnel on other settings is replaced. A legacy
    pair is moved into the shared tunnel on the way. Without ``proxy`` (a UI
    older than this worker) the tunnel is only started, its proxy address
    looked up again.

    The earner is restarted rather than started when it is still running in a
    namespace the tunnel left behind. It holds the service's lock as a
    deploy does: a copy whose tunnel is gone is rebuilt by the route it reads.
    """
    with route_gate.deploying(slug), _deploy_lock(proxy_id):
        try:
            approval = {"expected_containers": expected_containers} if expected_containers is not None else {}
            return _start(slug, proxy_id, proxy, own_ip, expected_container, **approval)
        except orchestrator.PastDeadline:
            # Only a start's tunnel image pull has a deadline here (_pull_deadline):
            # not the deploy limit the error names, nor a setting to fix.
            raise ProxyTunnelError(
                t(
                    "err.proxy_tunnel.not_started_tunnel_image_took",
                    slug=earner_name(slug, proxy_id),
                    replace_pull_seconds=REPLACE_PULL_SECONDS,
                ),
                503,
            ) from None


def _start(
    slug: str,
    proxy_id: int,
    proxy: dict[str, Any] | None,
    own_ip: str | None,
    expected_container: str | None,
    *,
    expected_containers: dict[str, str] | None = None,
) -> dict[str, Any]:
    client = orchestrator._get_client()
    name = earner_name(slug, proxy_id)
    if expected_containers is not None:
        if slug not in expected_containers or any(
            not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", copy_slug) or not re.fullmatch(r"[0-9a-f]{64}", cid)
            for copy_slug, cid in expected_containers.items()
        ):
            raise ProxyTunnelError(t("err.proxy_tunnel.expected_full_docker_ids_all"), 422)
        expected_container = expected_containers[slug]
    elif expected_container == "none":
        # A Start needs its earner, so "none" can never be the container meant.
        # It says only that the caller saw no saved ID: this worker's own record applies.
        expected_container = None
    # The old earner a failed redeploy left aside is the copy, never the
    # failed container under its name.
    earner = orchestrator.deploy_target(client, name)
    _require_settled_move(client, name)
    if expected_container is not None:
        orchestrator.require_deploy_target(expected_container, earner)
    if earner is not None:
        _require_resolved_deploy(earner, _get(client, name + orchestrator.REPLACED_SUFFIX))
    _settle_before_deploy(client, name, slug, proxy_id, expected=expected_container)
    earner = orchestrator.deploy_target(client, name)
    if expected_containers is None:
        saved = expected_container if expected_container is not None else _recorded_containers().get(name, "none")
        target = _StartApproval(name, {name: saved})
    else:
        target = _StartApproval(
            name,
            {earner_name(copy_slug, proxy_id): cid for copy_slug, cid in expected_containers.items()},
            grouped=True,
        )
    if not _is_ours(earner, slug, proxy_id):
        raise ValueError(t("err.proxy_tunnel.no_proxied_copy_through_proxy", slug=slug, proxy_id=proxy_id))
    # One a deploy that failed or never said it went through left is never the
    # copy: never started, as the heartbeat never starts it (it removes it).
    try:
        unfinished = _recorded_failed(earner)
    except OSError as exc:
        raise ProxyTunnelError(t("err.proxy_tunnel.could_not_read_which_deploys", exc=exc, name=name)) from None
    if unfinished:
        raise ProxyTunnelError(t("err.proxy_tunnel.not_started_deploy_did_not", name=name))
    tunnel = _tunnel_of(client, earner, slug, proxy_id)
    if tunnel is not None and not _is_shared(tunnel) and proxy is None:
        return _start_legacy(slug, earner, tunnel, name)
    if proxy is not None:
        # A routed service keeps its own tunnel; anything else is a shared copy.
        key = _own_key(tunnel) if _is_shared(tunnel) else (slug if _routed_here(slug, proxy_id) else None)
        final = shared_tunnel_name(proxy_id, key)
        _reclaim_retired(client, proxy_id, key, final)
        retired = _get(client, final + RETIRED_SUFFIX)
        held_in = _get(client, name)
        if (
            _is_tunnel_for(retired, proxy_id, key)
            and not _restarts_by_itself(retired)
            and held_in is not None
            and _tunnel_id_of(held_in) == retired.id
        ):
            # An earner a failed redeploy left in its old tunnel under the retired
            # name, which could not get its name back (another copy holds it):
            # that tunnel takes the settings and starts in place, and the earner
            # starts there, never recreated, which would lose its writable layer.
            # Not an older worker's tunnel, where no earner starts: its earner
            # is recreated in the tunnel under the name instead, below.
            # In place rewrites every file (own_ip too, which the leak guard
            # reads; an unknown one keeps the recorded address) and redacts the
            # old and new credentials from its errors.
            # The tunnel gets its name back once that name is free; a deploy
            # replaces both.
            files, secrets = _tunnel_settings(proxy, own_ip, shared_label(proxy_id, key))
            try:
                shared, exit_info = _in_place(client, retired, proxy, own_ip, files, secrets, deadline=_pull_deadline())
            except _Broken as exc:
                raise ProxyTunnelError(
                    t("err.proxy_tunnel.docker_could_not_start_not", name=retired.name, exc=exc, name2=name)
                ) from None
        else:
            if _tunnel_id_of(earner) != getattr(_get(client, final), "id", None):
                _move_expected(client, earner, target)
            shared, exit_info = _ensure_tunnel(
                client, proxy_id, proxy, own_ip, slug=key, deadline=_pull_deadline(), move_target=target
            )
    else:
        if tunnel is None:
            raise ProxyTunnelError(t("err.proxy_tunnel.tunnel_gone_start_dashboard_current", name=name))
        tunnel.reload()
        if _is_shared(tunnel) and _restarts_by_itself(tunnel):
            # An older worker's tunnel: replaced on the settings it holds before
            # the earner starts, which is recreated in the replacement.
            tunnel, exit_info = _replace_restarting(client, tunnel, deadline=_pull_deadline(), move_target=target)
            earner = _get(client, name)
            if earner is None:
                raise ProxyTunnelError(t("err.proxy_tunnel.disappeared_while_tunnel_replaced", name=name))
            if _tunnel_id_of(earner) != tunnel.id:
                # The ready run read below must be the one the earner joins.
                raise ProxyTunnelError(t("err.proxy_tunnel.not_started_not_tunnel_proved", name=name))
        else:
            if tunnel.status != "running":
                refresh_proxy_ip(tunnel)
                tunnel.start()
            exit_info = _wait_ready(tunnel)
    current = shared if proxy is not None else tunnel
    try:
        if proxy is not None:
            earner = _get(client, name)
            if earner is not None and _tunnel_id_of(earner) != shared.id:
                # A legacy pair, or a copy whose tunnel is gone: a namespace is
                # fixed at create, so its earner is recreated in the shared
                # tunnel (a routed service's in its own). A legacy tunnel goes
                # with it.
                with _swap_lock:
                    _clone_into(client, earner, shared, start=False, target=target)
                    if tunnel is not None and not _is_shared(tunnel):
                        _remove_quietly(tunnel, SIDECAR_STOP_SECONDS)
                    elif tunnel is not None and tunnel.id != shared.id:
                        with contextlib.suppress(Exception):
                            _drop_if_empty(client, tunnel)
                earner = _get(client, name)
            if earner is None:
                raise ProxyTunnelError(t("err.proxy_tunnel.disappeared_while_tunnel_replaced", name=name))
        not_durable = _clear_held_for_start(name)
    except Exception:
        # The tunnel was started for this copy, which stays stopped: down
        # again unless another copy in it should run.
        _stop_if_unwanted(client, current)
        raise
    earner.reload()
    if earner.status == "running":
        if earner_action(earner, current, True) == "restart":
            _started_or_raise(earner, current, slug, restart=True)
    else:
        _started_or_raise(earner, current, slug)
    return _started(exit_info, name, not_durable)


def _pull_deadline() -> float:
    """The deadline of a start's tunnel image pull. A start holds the proxy's lock,
    so a Stop of any copy through that proxy (the traffic cap's too) waits for it:
    a pull past REPLACE_PULL_SECONDS fails the start, and Docker finishes it for the next."""
    return time.monotonic() + REPLACE_PULL_SECONDS


def _clear_held_for_start(name: str) -> _RecordNotFlushed | None:
    """Clear the stop of ``name`` for a start; the error when the marker says so but may not survive a power cut.

    The marker then already says the copy runs, so the heartbeat would start it
    anyway: the start goes ahead, as a stop does (_stop), and reports it after
    (_started), never a failure for a copy that runs."""
    try:
        _set_held(name, False, strict=True)
    except _RecordNotFlushed as exc:
        return exc
    return None


def _started(exit_info: dict[str, Any], name: str, not_durable: _RecordNotFlushed | None) -> dict[str, Any]:
    """The answer of a start that went ahead. One whose record may not survive a power cut (_RecordNotFlushed)
    still says it started, never a failure: ``durable`` False and a ``warning`` the UI shows. An error would have
    the UI keep it recorded as stopped (by the cap, too) while it runs."""
    if not_durable is None:
        return {"exit": exit_info}
    return {
        "exit": exit_info,
        "durable": False,
        "warning": (
            f"{name} was started, but the start may not survive a power cut. {not_durable}. Start it again once the "
            "disk is healthy."
        ),
    }


def _stop_if_unwanted(client: Any, tunnel: Any) -> None:
    """Stop ``tunnel`` unless a copy in it should run. Errors are ignored: a start that failed reports its own."""
    with contextlib.suppress(Exception):
        stopped = held()
        if not any(str(m.name) not in stopped for m in _members(client, tunnel)):
            tunnel.stop(timeout=SIDECAR_STOP_SECONDS)


def _started_or_raise(earner: Any, tunnel: Any, slug: str, *, restart: bool = False) -> None:
    """_start_in_ready_run for a start the owner asked for: one it did not do is an error, never a success."""
    if not _start_in_ready_run(earner, tunnel, slug, restart=restart):
        raise ProxyTunnelError(t("err.proxy_tunnel.not_started_tunnel_not_ready", name=earner.name))


def _start_legacy(slug: str, earner: Any, sidecar: Any, name: str) -> dict[str, Any]:
    """A pair from an older worker, started by a UI that sends no settings.

    Its tunnel has Docker's restart policy, so no earner starts in it
    (_start_in_ready_run): it is started for its settings, and the pair moves
    into the proxy's shared tunnel first (a routed service's into its own,
    _migrate_proxy), where the earner starts."""
    client = orchestrator._get_client()
    sidecar.reload()
    if sidecar.status != "running":
        refresh_proxy_ip(sidecar)
    sidecar.start()
    legacy = sidecar
    try:
        exit_info = _wait_ready(sidecar)
        moved = _restarts_by_itself(sidecar)
        if moved:
            proxy_id = int(_labels(sidecar).get(LABEL_PROXY, ""))
            _migrate_proxy(client, proxy_id, [sidecar], deadline=_pull_deadline())
            earner = _get(client, name)
            sidecar = _tunnel_of(client, earner, slug, proxy_id)
            if earner is None or not _is_shared(sidecar):
                raise ProxyTunnelError(t("err.proxy_tunnel.not_started_tunnel_made_older", name=name))
            exit_info = _read_exit(sidecar) or exit_info
        not_durable = _clear_held_for_start(name)
    except Exception:
        # Started for this copy, which stays stopped: down again, as _start
        # does, or it holds the proxy's login (or an online node) for nothing.
        # The same for a shared tunnel it moved into.
        for tunnel in {
            id(tunnel_item): tunnel_item for tunnel_item in (legacy, sidecar) if tunnel_item is not None
        }.values():
            _stop_if_unwanted(client, tunnel)
        raise
    earner.reload()
    if earner.status != "running":
        _started_or_raise(earner, sidecar, slug)
    elif not moved or earner_action(earner, sidecar, True) == "restart":
        _started_or_raise(earner, sidecar, slug, restart=True)
    return _started(exit_info, name, not_durable)


def _earner_or_raise(client: Any, slug: str, proxy_id: int) -> Any:
    """The copy's earner. ValueError when there is no such copy."""
    earner = _get(client, earner_name(slug, proxy_id))
    if not _is_ours(earner, slug, proxy_id) or not _is_earner(earner):
        raise ValueError(t("err.proxy_tunnel.no_proxied_copy_through_proxy", slug=slug, proxy_id=proxy_id))
    return earner


def logs(slug: str, proxy_id: int, lines: int = 50) -> str:
    """The last ``lines`` log lines of the copy's earner. ValueError when there is no such copy."""
    earner = _earner_or_raise(orchestrator._get_client(), slug, proxy_id)
    return earner.logs(tail=lines, timestamps=True).decode("utf-8", errors="replace")


def grep_logs(slug: str, proxy_id: int, match: re.Pattern[str], since_hours: float, lines: int = 1000) -> str:
    """The earner's log lines of the past ``since_hours`` that match ``match``, as orchestrator.grep_service_logs
    reads a direct copy's: for the UI's windowed health signals (main._sweep_windowed_signals)."""
    earner = _earner_or_raise(orchestrator._get_client(), slug, proxy_id)
    return orchestrator.grep_container_logs(earner, match, since_hours, lines)


def restart(slug: str, proxy_id: int) -> dict[str, Any]:
    """Restart one running copy where it is, for a health signal a restart clears (main._auto_restart).

    Never a stop and a start: a stop writes the copy down as held, so a start
    that then failed would leave it stopped for good. This writes no marker.
    It refuses a copy its owner or the traffic cap stopped (held), one that is
    not running, and one a deploy that did not finish left. The earner
    restarts only into a tunnel run that is ready, and is stopped again if
    the tunnel restarted meanwhile (_start_in_ready_run); the heartbeat then
    starts it once the tunnel is ready, as after a reboot. Under the proxy's
    lock, as a stop, a start and a deploy are.
    """
    with _deploy_lock(proxy_id):
        client = orchestrator._get_client()
        earner = _earner_or_raise(client, slug, proxy_id)
        name = str(earner.name)
        try:
            stopped = name in held()
            unfinished = _recorded_failed(earner)
        except OSError as exc:
            raise ProxyTunnelError(t("err.proxy_tunnel.could_not_read_which_copies", exc=exc, name=name)) from None
        if unfinished:
            raise ProxyTunnelError(t("err.proxy_tunnel.left_deploy_did_not_finish", name=name))
        if stopped:
            raise CopyNotRunning(t("err.proxy_tunnel.stopped_owner_traffic_cap_left", name=name))
        state = getattr(earner, "status", "")
        if state != "running":
            error = CopyNotRunning if state in ("created", "exited") else ProxyTunnelError
            raise error(t("err.proxy_tunnel.not_running_left", name=name))
        tunnel = _tunnel_of(client, earner, slug, proxy_id)
        if tunnel is None or not _start_in_ready_run(earner, tunnel, slug, restart=True):
            raise ProxyTunnelError(
                t("err.proxy_tunnel.not_restarted_tunnel_gone_not", name=name),
                503,
            )
    return {"restarted": name}


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
    # And the old earner a redeploy left aside (see _settle_replaced), and both
    # halves of a move a worker died in (see recover_moves), each with the
    # tunnel it lives in: left behind, recover_moves would give one of them the
    # name back and the heartbeat would start the removed copy again.
    asides = [
        aside
        for suffix in (orchestrator.REPLACED_SUFFIX, MOVING_SUFFIX, STAGED_SUFFIX)
        if _is_ours(aside := _get(client, name + suffix), slug, proxy_id) and _is_earner(aside)
    ]
    tunnels = [_tunnel_of(client, earner, slug, proxy_id)]
    tunnels += [_tunnel_of(client, aside, slug, proxy_id) for aside in asides]
    for container in (earner, *asides):
        if container is not None:
            _remove_quietly(container, orchestrator._get_stop_timeout(slug))
            removed.append(container.name)
    # A legacy tunnel of this copy, even when the earner was already moved out.
    legacy = _get(client, tunnel_name(slug, proxy_id))
    for candidate in {
        tunnel_item.id: tunnel_item for tunnel_item in (*tunnels, legacy) if tunnel_item is not None
    }.values():
        if _is_tunnel(candidate, proxy_id) and not _is_shared(candidate) and _is_ours(candidate, slug, proxy_id):
            _remove_quietly(candidate, SIDECAR_STOP_SECONDS)
            removed.append(candidate.name)
        elif drop_shared and _is_shared(candidate, proxy_id):
            removed += _drop_if_empty(client, candidate)
    _set_held(name, False)
    _forget_container(name)
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

    def canonical(container: Any) -> str:
        # The saved ID is kept under the copy's own name, never a half-moved one's.
        name = str(container.name)
        for suffix in (orchestrator.REPLACED_SUFFIX, MOVING_SUFFIX, STAGED_SUFFIX):
            name = name.removesuffix(suffix)
        return name

    removed: list[str] = []
    left: list[str] = []
    for pid in sorted({_labels(c).get(LABEL_PROXY, "") for c in listing()}):
        with _deploy_lock(int(pid)) if pid.isdigit() else contextlib.nullcontext():
            found = [c for c in listing() if _labels(c).get(LABEL_PROXY, "") == pid]
            shared_ids = {tid for c in found if _is_earner(c) and (tid := _tunnel_id_of(c))}
            # Earners first, so no tunnel is removed under a running earner.
            found.sort(key=lambda c: _labels(c).get(LABEL_ROLE) == ROLE_TUNNEL)
            gone: set[str] = set()
            kept: set[str] = set()
            for container in found:
                _remove_quietly(container)
                try:
                    container.reload()
                except NotFound:
                    removed.append(container.name)
                    if _is_earner(container):
                        _set_held(str(container.name), False)
                        gone.add(canonical(container))
                else:
                    left.append(container.name)
                    if _is_earner(container):
                        kept.add(canonical(container))
            # Only once no container of that copy is left: a survivor keeps its record.
            for name in sorted(gone - kept):
                _forget_container(name)
            if pid.isdigit():
                for tid in sorted(shared_ids):
                    tunnel = _get(client, tid)
                    if _is_shared(tunnel, int(pid)):
                        removed += _drop_if_empty(client, tunnel)
    if left:
        # Said out loud, so the UI keeps the records of copies that still exist.
        raise ProxyTunnelError(t("err.proxy_tunnel.docker_did_not_remove", left=", ".join(left)), status_code=409)
    return removed


def sweep_test_tunnels(min_age: float = 0.0) -> list[str]:
    """Remove Test tunnels a worker that stopped mid-test left behind, and staged
    tunnels of a deploy it stopped in.

    Run at worker start, when no test of this worker can be in flight. A worker
    that started without Docker runs it once Docker answers, with the API
    already serving: it passes ``min_age``, the seconds since it started, so a
    Test tunnel younger than that (a test of this worker, in flight) is kept.
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
        if min_age and _age_seconds(container) < min_age:
            continue
        _remove_quietly(container, SIDECAR_STOP_SECONDS)
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
            _remove_quietly(container, SIDECAR_STOP_SECONDS)
            swept.append(container.name)
    return swept


def recover_moves(min_age: float | None = None, *, conflicts: dict[str, str] | None = None) -> list[str]:
    """Finish interrupted moves whose original and staged Docker IDs are in the move record."""
    if min_age is None:
        min_age = STAGED_STALE_SECONDS
    client = orchestrator._get_client()
    found = client.containers.list(all=True, filters={"label": [f"{LABEL_MANAGED}=true", LABEL_PROXY]})
    names = {
        str(c.name).removesuffix(MOVING_SUFFIX).removesuffix(STAGED_SUFFIX): _labels(c).get(LABEL_PROXY, "")
        for c in found
        if _is_earner(c) and str(c.name).endswith((MOVING_SUFFIX, STAGED_SUFFIX))
    }
    done = []
    for name, pid in sorted(names.items()):
        if not pid.isdigit():
            continue
        lock = _deploy_lock(int(pid))
        if not lock.acquire(blocking=False):
            continue
        try:
            if result := _settle_move(client, name, min_age):
                done.append(result)
                logger.info("Recovered an interrupted move: %s", result)
        except RecoveryConflict as exc:
            if conflicts is not None:
                conflicts[name] = str(exc)
            logger.warning("%s", exc)
        except Exception as exc:  # noqa: BLE001 - the next pass tries again
            logger.warning("Could not recover the move of %s: %s", name, redact(str(exc)))
        finally:
            lock.release()
    return done


def _settle_move(client: Any, name: str, min_age: float) -> str | None:
    holder = _get(client, name)
    aside = _get(client, name + MOVING_SUFFIX)
    staged = _get(client, name + STAGED_SUFFIX)
    if aside is None and staged is None:
        return None
    if any(c is not None and _age_seconds(c) < min_age for c in (holder, staged)):
        return None
    marker = next((key for key in _read_names(MOVE_MARKER) if key.startswith(f"{name}@")), "")
    _, _, pair = marker.partition("@")
    old_id, _, clone_id = pair.partition("@")
    if (
        not old_id
        or not clone_id
        or (aside is not None and aside.id != old_id)
        or (staged is not None and staged.id != clone_id)
        or (holder is not None and holder.id != (clone_id if aside is not None else old_id))
    ):
        raise RecoveryConflict(t("err.proxy_tunnel.recovery_skipped_move_record_cannot", name=name))

    if holder is not None and aside is not None:
        _remove_quietly(aside, 2, volumes=False)
        _record_container(name, clone_id)
        result = f"removed {aside.name}"
    elif (
        holder is None
        and staged is not None
        and (
            aside is None
            or (_get(client, _tunnel_id_of(aside)) is None and _get(client, _tunnel_id_of(staged)) is not None)
        )
    ):
        staged.rename(name)
        if aside is not None:
            _remove_quietly(aside, 2, volumes=False)
        _record_container(name, clone_id)
        result = f"finished {name}"
    else:
        if staged is not None:
            staged_name = str(staged.name)
            _remove_quietly(staged, 2, volumes=False)
        if aside is not None:
            aside.rename(name)
            result = f"restored {name}"
        else:
            result = f"removed {staged_name}"
    _set_id(MOVE_MARKER, marker, False)
    return result


def _finish_stale_staged(client: Any, staged: Any) -> str | None:
    """A staged shared tunnel copies still live in, past any change's timeout:
    finish that change, unless one of this proxy is running now.

    Returns why the change is not finished, for the heartbeat to report (the
    UI alerts on a change stuck this way), or None when it finished or the
    tunnel is not a shared one."""
    pid = _labels(staged).get(LABEL_PROXY, "")
    if not pid.isdigit() or not _is_shared(staged, int(pid)):
        return None
    if half := _moving(client, pid):
        # recover_moves settles those first, at a later heartbeat
        return (
            f"{', '.join(sorted(half))} {'is' if len(half) == 1 else 'are'} still half moved between tunnels, "
            "and the worker has not settled that yet."
        )
    lock = _deploy_lock(int(pid))
    if not lock.acquire(blocking=False):
        return "Another change to this proxy is running on this worker."
    # The name the staged tunnel was made for: the proxy's shared one, or a
    # routed service's own.
    key = _own_key(staged)
    final = shared_tunnel_name(int(pid), key)
    try:
        current = _get(client, final)
        if current is not None and not _is_tunnel_for(current, int(pid), key):
            return f"A container named {final} that CashPilot did not create holds the name the new tunnel needs."
        _finish_staged(client, staged, current, final)
        return None
    except Exception as exc:  # noqa: BLE001 - the next heartbeat tries again
        logger.warning("Could not finish the tunnel change of proxy %s: %s", pid, exc)
        # A ProxyTunnelError is written to be shown; anything else gets the
        # same redaction as every other Docker error the worker passes on.
        text = str(exc) if isinstance(exc, ProxyTunnelError) else redact(str(exc))
        return text[:300] or type(exc).__name__  # never blank: a blank reason is not reported
    finally:
        lock.release()


def _settle_replaced_unless_busy(client: Any, aside: Any) -> str | None:
    """_settle_replaced under the proxy's lock; skipped while a change to that proxy runs (its own aside)."""
    pid = _labels(aside).get(LABEL_PROXY, "")
    if not pid.isdigit():
        return None
    lock = _deploy_lock(int(pid))
    if not lock.acquire(blocking=False):
        return None
    try:
        # Read again under the lock: the listing is from before it, and a deploy
        # that held it may have given this container its name back since.
        aside.reload()
        if done := _settle_replaced(client, aside):
            logger.info("An old earner a redeploy left aside: %s", done)
    except RecoveryConflict as exc:
        logger.warning("%s", exc)
        return str(exc)
    except NotFound:
        pass
    except Exception as exc:  # noqa: BLE001 - the next heartbeat tries again
        logger.warning("Could not settle %s: %s", aside.name, exc)
    finally:
        lock.release()
    return None


def _drop_empty_shared(client: Any, tunnel: Any) -> None:
    """Remove a shared tunnel with no copy, under its proxy's lock (skipped when held)."""
    pid = _labels(tunnel).get(LABEL_PROXY, "")
    if not pid.isdigit():
        return
    lock = _deploy_lock(int(pid))
    if not lock.acquire(blocking=False):
        return
    try:
        if dropped := _drop_if_empty(client, _get(client, str(tunnel.name))):
            logger.info("Removed %s: no copy lives in it", ", ".join(dropped))
    except Exception as exc:  # noqa: BLE001 - the next heartbeat tries again
        logger.warning("Could not remove the empty tunnel %s: %s", tunnel.name, exc)
    finally:
        lock.release()


def _read_all_files(container: Any) -> dict[str, str]:
    """Every settings file but the digest. A file that is not there reads as
    empty; any other read error raises, so a migration never runs on half of them."""
    return {key: _read_secret_file_or_raise(container, key) or "" for key in SECRET_KEYS if key != "settings"}


def migrate_legacy() -> list[str]:
    """Move the copies of older workers, one tunnel each, into one shared tunnel per proxy.

    Run at worker start. Per proxy, the settings come from its shared tunnel
    when one is ready, else from a running, ready legacy tunnel (its secret
    files, read back; nothing is asked of the UI). A proxy with neither is left
    alone: its legacy pairs keep working and move on their next start. Any
    failure leaves the pairs not moved yet as they are: each one is valid and
    fails closed. A pair whose legacy tunnel is stopped (and did not fail to
    start) is left as it is, and moves on its next start.
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
        if (
            str(c.name).endswith(STAGED_SUFFIX)
            or slug in (SHARED_SLUG, TEST_SLUG)
            or not pid.isdigit()
            or not _is_tunnel(c)
        ):
            continue
        legacy.setdefault(int(pid), []).append(c)
    moved: list[str] = []
    for proxy_id, tunnels in sorted(legacy.items()):
        with _deploy_lock(proxy_id):
            try:
                # Bounded like a start's pull (_pull_deadline): a Stop through
                # this proxy, the traffic cap's too, waits for this lock.
                moved += _migrate_proxy(client, proxy_id, tunnels, deadline=_pull_deadline())
            except Exception as exc:  # noqa: BLE001 - the pairs left are valid; the next start tries again
                logger.warning("Could not move the copies of proxy %s into one tunnel: %s", proxy_id, redact(str(exc)))
    return moved


def _migrate_proxy(client: Any, proxy_id: int, tunnels: list[Any], *, deadline: float | None = None) -> list[str]:
    """Move the legacy pairs ``tunnels`` of the proxy into its shared tunnel. ``deadline`` bounds the image pull.

    A routed service's pair moves into that service's own tunnel through the
    proxy instead, as a start with settings does: a routed earner never joins
    the shared tunnel (_routed_here)."""
    groups: dict[str | None, list[Any]] = {}
    for tunnel in tunnels:
        slug = _labels(tunnel).get(LABEL_SERVICE, "")
        groups.setdefault(slug if _routed_here(slug, proxy_id) else None, []).append(tunnel)
    moved: list[str] = []
    for key, group in groups.items():
        moved += _migrate_into(client, proxy_id, group, key, deadline=deadline)
    return moved


def _migrate_into(
    client: Any, proxy_id: int, tunnels: list[Any], key: str | None, *, deadline: float | None = None
) -> list[str]:
    """Move the legacy pairs ``tunnels`` into the proxy's shared tunnel, or with ``key`` that routed service's own."""
    for tunnel in tunnels:
        for member in _members(client, tunnel):
            _move_expected(client, member, None)
    ready = _shared_ready(client, proxy_id, key)
    if ready is not None and _restarts_by_itself(ready[0]):
        # An older worker's shared tunnel: no copy starts in it, so it is
        # replaced first, once its own copies are settled; else the pairs wait.
        if not _settled_and_wanted(client, ready[0], str(proxy_id)):
            logger.info("Proxy %s's tunnel is replaced first; its other copies move on their next start", proxy_id)
            return []
        ready = _replace_restarting(client, ready[0], deadline=deadline)
    if ready is None:
        sources = [
            tunnel_item
            for tunnel_item in tunnels
            if getattr(tunnel_item, "status", "") == "running" and _read_exit(tunnel_item) is not None
        ]
        if not sources:
            logger.info(
                "Proxy %s has no running tunnel to copy settings from; its copies move on their next start", proxy_id
            )
            return []
        sources.sort(key=_started_at, reverse=True)
        files = _read_all_files(sources[0])
        if files.get("kind") == "tailscale":
            files["hostname"] = _ts_hostname(shared_label(proxy_id, key))
        files = _with_digest(files)
        ready = _ensure_tunnel(
            client, proxy_id, None, files.get("own_ip") or None, files=files, slug=key, deadline=deadline
        )
    shared, _ = ready
    moved: list[str] = []
    for tunnel in tunnels:
        try:
            tunnel.reload()  # read under the proxy's lock, not from the listing
        except NotFound:
            continue
        was_up = getattr(tunnel, "status", "") in _LIVE
        # A pair down because Docker could not start its tunnel (State.Error,
        # e.g. after a daemon restart) moves, unheld, so the heartbeat starts it
        # in the shared tunnel. Any other stopped pair may be one the owner
        # stopped or one Docker has yet to restart: nothing tells them apart, so
        # it stays as it is, valid and closed, and moves on its next start.
        failed = bool(((getattr(tunnel, "attrs", None) or {}).get("State") or {}).get("Error"))
        if not was_up and not failed:
            continue
        with _swap_lock:
            for member in _members(client, tunnel):
                clone = _clone_into(client, member, shared, start=was_up and getattr(member, "status", "") in _LIVE)
                moved.append(str(clone.name))
            _remove_quietly(tunnel, SIDECAR_STOP_SECONDS)
    if moved:
        logger.info(
            "Moved %d cop%s of proxy %s into %s",
            len(moved),
            "y" if len(moved) == 1 else "ies",
            proxy_id,
            shared_tunnel_name(proxy_id, key),
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


def _ready_missing(sidecar: Any) -> bool:
    """Whether the running tunnel answered that /run/ready is not there. An exec that fails is not known: False."""
    if sidecar.status != "running":
        return False
    try:
        code, _ = sidecar.exec_run(["cat", "/run/ready"], demux=False)
    except Exception:  # noqa: BLE001 - not known is not "not there"
        return False
    return code == 1


def _recover(earner: Any, sidecar: Any, slug: str, proxy_id: str, *, ready: bool) -> None:
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
        _start_when_ready(earner, sidecar, slug, ready=ready)
    finally:
        if lock is not None:
            lock.release()


def _start_when_ready(earner: Any, sidecar: Any, slug: str, *, ready: bool) -> None:
    """_recover's work, for a caller that holds the proxy's lock.

    ``ready`` is whether the caller saw ``sidecar`` write /run/ready. A failed
    deploy's earner is removed either way; nothing is started or restarted
    unless it is True, so the earner never enters a tunnel that could leak.
    """
    try:
        try:
            if str(earner.name) in held():
                return
        except OSError as exc:
            logger.warning("Could not read which copies are stopped (%s); starting none", exc)
            return
        listed = str(earner.name)
        earner.reload()
        if str(earner.name) != listed:
            return  # moved aside (or back) since it was listed: the next beat sees it as it is
        aside = _get(orchestrator._get_client(), f"{earner.name}{orchestrator.REPLACED_SUFFIX}")
        try:
            _require_resolved_deploy(earner, aside)
            failed = _aside_is_copy(earner, aside) if aside is not None else _recorded_failed(earner)
        except RecoveryConflict as exc:
            logger.warning("%s", exc)
            return
        except OSError as exc:
            logger.warning("Could not read which replacements failed (%s); not starting %s", exc, earner.name)
            return  # not known: nothing is started, nothing removed
        if failed and aside is not None:
            # A failed replacement Docker would not remove: the old earner
            # aside is the copy, and _settle_replaced gives it the name back.
            logger.warning("Not starting %s: a failed deploy left it, and the copy it replaced is aside", earner.name)
            return
        if failed:
            # A first deploy that failed and that Docker would not remove: it
            # never was the copy (the UI dropped its record), so it goes.
            logger.warning("Not starting %s: a failed deploy left it; removing it", earner.name)
            _remove_quietly(earner, 2)
            _set_failed(str(earner.id), False)
            _set_new(str(earner.name), False)
            _set_new(_new_key(str(earner.name), str(earner.id)), False)
            _forget_created(str(earner.name), "none", str(earner.id))
            return
        if ready:
            # Read again under the lock: what the caller saw may describe a run
            # of the tunnel that has ended since (/run is a tmpfs, so a fresh
            # read is the current run's). False is never read again into True.
            sidecar.reload()
            ready = _read_exit(sidecar) is not None
        action = earner_action(earner, sidecar, ready)
        if action == "stop":
            # ``ready`` False may come from a read that failed, or from a run
            # that has ended since: only the current run answering that it has
            # no /run/ready (written once per run, never removed) stops it.
            sidecar.reload()
            run = _started_at(sidecar)
            missing = _ready_missing(sidecar)
            sidecar.reload()
            if not missing or _started_at(sidecar) != run or earner_action(earner, sidecar, False) != "stop":
                return
            logger.warning("%s runs in a run of its tunnel that has not proved an exit; stopping it", earner.name)
            earner.stop(timeout=orchestrator._get_stop_timeout(slug))
            return
        if action not in ("start", "restart"):
            return
        if _start_in_ready_run(earner, sidecar, slug, restart=action == "restart"):
            earner.reload()
            logger.info("Started %s inside its tunnel, which is ready", earner.name)
    except Exception as exc:  # noqa: BLE001 - the next heartbeat tries again
        logger.warning("Could not start %s inside its tunnel: %s", earner.name, exc)


def earner_action(earner: Any, sidecar: Any, ready: bool) -> str | None:
    """What the heartbeat does to an earner: "restart", "start", "stop" or nothing.

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

    A running earner that started in the tunnel's current run while that run
    has not written /run/ready is stopped: it joined a namespace nobody proved
    (a start that raced a restart of the tunnel), and it starts again once the
    run is ready. Started before the run, it sits in the old namespace and is
    left as it is. A False ``ready`` may be a read that failed, so the caller
    stops it only when the current run answers it has no /run/ready
    (_start_when_ready).
    """
    if getattr(sidecar, "status", "") != "running":
        return None
    status = getattr(earner, "status", "")
    if not ready:
        in_this_run = status == "running" and _started_at(earner) >= _started_at(sidecar)
        return "stop" if in_this_run else None
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
    _replace_soon()
    # A change that holds _swap_lock longer (a replacement stopping copy after
    # copy) costs this reading, never the heartbeat: the worker sends it with
    # its copies not known, which the UI never takes for gone.
    if not _swap_lock.acquire(timeout=STATUS_SWAP_WAIT):
        raise ProxyTunnelError(t("err.proxy_tunnel.change_proxy_s_tunnel_moving"))
    try:
        return _status(collect_stats)
    finally:
        _swap_lock.release()


#: Seconds status() waits for a tunnel change to let go of _swap_lock.
STATUS_SWAP_WAIT = 20


def _status(collect_stats: bool) -> list[dict[str, Any]]:
    try:
        client = orchestrator._get_client()
        found = client.containers.list(all=True, filters={"label": [f"{LABEL_MANAGED}=true", LABEL_PROXY]})
    except Exception as exc:  # noqa: BLE001 - the heartbeat says it could not look
        raise ProxyTunnelError(t("err.proxy_tunnel.could_not_list_proxied_copies", exc=redact(str(exc)))) from None
    conflicts: dict[str, str] = {}
    # Moves a worker died in come first: a copy aside or staged is still a copy.
    if any(str(getattr(c, "name", "")).endswith((STAGED_SUFFIX, MOVING_SUFFIX)) for c in found):
        with contextlib.suppress(Exception):
            recover_moves(conflicts=conflicts)
            found = client.containers.list(all=True, filters={"label": [f"{LABEL_MANAGED}=true", LABEL_PROXY]})
    # An old earner a redeploy left aside, with no deploy of its proxy running:
    # removed beside its replacement, or the copy again when the name is free.
    if any(str(getattr(c, "name", "")).endswith(orchestrator.REPLACED_SUFFIX) and _is_earner(c) for c in found):
        for aside in [c for c in found if str(getattr(c, "name", "")).endswith(orchestrator.REPLACED_SUFFIX)]:
            name = str(aside.name).removesuffix(orchestrator.REPLACED_SUFFIX)
            if conflict := _settle_replaced_unless_busy(client, aside):
                conflicts[name] = conflict
        with contextlib.suppress(Exception):
            found = client.containers.list(all=True, filters={"label": [f"{LABEL_MANAGED}=true", LABEL_PROXY]})
    # A staged tunnel past any change's timeout: one copies live in (staged or
    # aside ones included) is a change to finish; an empty one is a leftover
    # holding the proxy login, removed here, since the startup sweep skips those
    # still young when the worker starts.
    # A change it could not finish is reported on the copies already in the
    # staged tunnel, which the report below cannot pair with any tunnel.
    stuck: dict[str, dict[str, Any]] = {}
    every_earner = [c for c in found if _labels(c).get(LABEL_ROLE) != ROLE_TUNNEL]
    for container in found:
        if (
            str(getattr(container, "name", "")).endswith(STAGED_SUFFIX)
            and _labels(container).get(LABEL_ROLE) == ROLE_TUNNEL
            and _age_seconds(container) >= STAGED_STALE_SECONDS
        ):
            if any(_tunnel_id_of(e) == container.id for e in every_earner):
                if (reason := _finish_stale_staged(client, container)) is not None:
                    stuck[container.id] = {
                        "tunnel": str(container.name),
                        "age_seconds": int(_age_seconds(container)),
                        "reason": reason,
                    }
            else:
                _remove_quietly(container, SIDECAR_STOP_SECONDS)
    with contextlib.suppress(Exception):
        found = client.containers.list(all=True, filters={"label": [f"{LABEL_MANAGED}=true", LABEL_PROXY]})
    tunnels: dict[str, Any] = {}
    earners: list[Any] = []
    asides: dict[tuple[str, str], Any] = {}
    halves: dict[tuple[str, str], Any] = {}
    for container in found:
        if str(getattr(container, "name", "")).endswith((STAGED_SUFFIX, MOVING_SUFFIX)):
            if _is_earner(container):
                # A half of a move recover_moves left alone (still young, or it
                # failed): the aside one first, the copy recover_moves restores.
                labels = _labels(container)
                key = (labels.get(LABEL_SERVICE, ""), labels.get(LABEL_PROXY, ""))
                if key not in halves or str(container.name).endswith(MOVING_SUFFIX):
                    halves[key] = container
            continue
        if _labels(container).get(LABEL_ROLE) == ROLE_TUNNEL:
            tunnels[container.id] = container
        elif not str(getattr(container, "name", "")).endswith(orchestrator.REPLACED_SUFFIX):
            earners.append(container)
        elif _is_earner(container):
            # An old earner kept aside until its replacement runs: by a deploy
            # still running, or one settling could not give its name back.
            labels = _labels(container)
            asides[(labels.get(LABEL_SERVICE, ""), labels.get(LABEL_PROXY, ""))] = container
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
                    tunnel_item
                    for tunnel_item in tunnels.values()
                    if tunnel_item.name == tunnel_name(labels.get(LABEL_SERVICE, ""), labels.get(LABEL_PROXY, ""))
                ),
                None,
            )
        if tunnel is not None:
            used.add(tunnel.id)
        pairs[(labels.get(LABEL_SERVICE, ""), labels.get(LABEL_PROXY, ""))] = (earner, tunnel)
    # While the name is free or held by a failed replacement, the old earner
    # aside is the copy, and may still run its ids: it is listed, never
    # started here, and with no digest, so the UI neither takes the failed
    # one's ids for the copy's nor lets go of a hold because the copy looks gone.
    unproven: set[tuple[str, str]] = set()
    for key, aside in asides.items():
        holder = pairs.get(key, (None, None))[0]
        try:
            # The rule settlement and start recovery use: the copy reported, and
            # its identity proof, are always the one they keep.
            replaced = holder is None or (holder.id != aside.id and _aside_is_copy(holder, aside))
        except OSError:
            replaced = True
        if replaced:
            tunnel = tunnels.get(_tunnel_id_of(aside))
            if tunnel is not None:
                used.add(tunnel.id)
            pairs[key] = (aside, tunnel)
            unproven.add(key)
    # A copy left only as the halves of a move is still the copy, and may run its
    # ids once recovered: listed as an aside is, so the UI keeps its holds.
    for key, half in halves.items():
        if pairs.get(key, (None, None))[0] is None:
            tunnel = tunnels.get(_tunnel_id_of(half))
            if tunnel is not None:
                used.add(tunnel.id)
            pairs[key] = (half, tunnel)
            unproven.add(key)
    for tunnel in list(tunnels.values()):
        # A shared tunnel no copy lives in holds the proxy login (and a tailnet
        # device) for nothing. Not a young one, which a deploy may be filling.
        if tunnel.id not in used and _is_shared(tunnel) and _age_seconds(tunnel) >= STAGED_STALE_SECONDS:
            _drop_empty_shared(client, tunnel)
            continue
        # A legacy tunnel whose earner is gone still reports, so the UI sees it.
        if tunnel.id not in used and not _is_shared(tunnel):
            labels = _labels(tunnel)
            pairs.setdefault((labels.get(LABEL_SERVICE, ""), labels.get(LABEL_PROXY, "")), (None, tunnel))
    # Which copies the owner or the cap stopped, so the UI can tell them from
    # ones that died. Unreadable: not said, and the UI alerts on what is gone only.
    try:
        stopped: set[str] | None = held()
    except OSError:
        stopped = None
    # Docker never starts a shared tunnel this worker made on its own
    # (sidecar_kwargs): one that is down while a copy in it should run is
    # started here, and its copies on a later beat, once it is ready. One an
    # older worker made is replaced (_replace_restarting_tunnels, in the
    # background), and is never started as it is. A copy
    # whose stop marker cannot be read starts no tunnel. A legacy pair is left
    # to Docker as it was: a stop by an older worker left no marker, so only
    # Docker knows whether its owner stopped it, and its next start moves it
    # into a shared tunnel.
    for key, (earner, sidecar) in pairs.items():
        if (
            stopped is not None
            and earner is not None
            and _is_shared(sidecar)
            and not _restarts_by_itself(sidecar)
            and key not in unproven
            and str(earner.name) not in conflicts
            and getattr(sidecar, "status", "") == "exited"
            and str(earner.name) not in stopped
            and not _failed_or_unknown(earner)
        ):
            _start_down_tunnel(sidecar, key[1], str(earner.name))
    live = {tunnel_item.id: tunnel_item for _, tunnel_item in pairs.values() if tunnel_item is not None}
    stats = orchestrator._collect_stats_bulk(list(live.values())) if collect_stats else {}
    exits = {tid: _read_exit(tunnel_item) for tid, tunnel_item in live.items()}
    out: list[dict[str, Any]] = []
    recorded = _recorded_containers()
    for (slug, proxy_id), (earner, sidecar) in sorted(pairs.items()):
        exit_info = exits.get(sidecar.id) if sidecar is not None else None
        aside = (slug, proxy_id) in unproven
        # A deploy that failed or never said it went through left this earner:
        # it is not the copy, so it proves no ids, and recovery removes it.
        failed = False
        if not aside and earner is not None:
            try:
                failed = _recorded_failed(earner)
            except OSError:
                failed = True  # not known; _start_when_ready reads it again and does nothing
        name = str(earner.name) if earner is not None and not aside else earner_name(slug, proxy_id)
        conflict = conflicts.get(name)
        if earner is not None and not aside and conflict is None and failed:
            try:
                _require_resolved_deploy(earner, None)
            except RecoveryConflict as exc:
                conflict = str(exc)
                logger.warning("%s", conflict)
            except OSError:
                pass
        if (
            not conflict
            and not aside
            and earner is not None
            and (failed or earner_action(earner, sidecar, exit_info is not None) is not None)
        ):
            _recover(earner, sidecar, slug, proxy_id, ready=exit_info is not None)
        _, _, rx, tx = stats.get(sidecar.id, (None, None, None, None)) if sidecar is not None else (None,) * 4
        try:
            pid = int(proxy_id)
        except ValueError:
            continue
        out.append(
            {
                "slug": slug,
                "proxy_id": pid,
                "name": earner.name if earner is not None and not aside else earner_name(slug, pid),
                "status": earner.status if earner is not None else "missing",
                "container_id": earner.short_id if earner is not None else "",
                # What a routed service runs, for the UI's outdated-image notice.
                "image": _image_of(earner) if earner is not None else "",
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
        if conflict:
            out[-1]["recovery_skipped"] = conflict
        elif sidecar is not None and sidecar.id in _recovery_skipped:
            out[-1]["recovery_skipped"] = RECOVERY_SKIPPED
        if not aside and earner is not None and (saved := recorded.get(str(earner.name))):
            out[-1]["recorded_container"] = saved
        if stopped is not None and earner is not None:
            out[-1]["held"] = out[-1]["name"] in stopped
        if earner is not None and not aside and not failed and not conflict:
            # The keyed hash of the device ids it runs with, never the ids: the
            # UI's proof before it records this copy in the identity ledger.
            out[-1].update(orchestrator._identity_entry(earner, slug))
        if sidecar is None and earner is not None and (change := stuck.get(_tunnel_id_of(earner))):
            out[-1]["tunnel_change"] = dict(change)
    return out


def _failed_or_unknown(earner: Any) -> bool:
    try:
        return _recorded_failed(earner)
    except OSError:
        return True


def _restarts_by_itself(container: Any) -> bool:
    """Whether Docker starts ``container`` again on its own: the restart policy older workers gave every tunnel.

    The worker cannot take the policy away: the socket proxy refuses a
    container update on purpose (docs/security-defaults.md). So a shared
    tunnel that has it is replaced (_replace_restarting), and no earner starts
    in it meanwhile (_start_in_ready_run)."""
    policy = (((getattr(container, "attrs", None) or {}).get("HostConfig") or {}).get("RestartPolicy") or {}).get(
        "Name"
    )
    return str(policy or "no") != "no"


def _replace_restarting(
    client: Any, tunnel: Any, *, deadline: float | None = None, move_target: _StartApproval | None = None
) -> tuple[Any, dict[str, Any]]:
    """Replace ``tunnel``, a shared tunnel an older worker made, with one Docker never restarts on its own.

    Returns the tunnel its copies live in now, ready. On the settings it holds,
    read back as migrate_legacy reads them, with the proxy's address looked up
    again as a start would. It goes through _ensure_tunnel's staged
    replacement: the new tunnel proves its exit first, then each copy is
    recreated in it under its own name, with its settings and the volumes its
    image declared, and started again only in the new run once that run is
    ready, and only if it ran. The old tunnel goes; the new one runs the
    current tunnel image.

    A failure before the copies move leaves the old tunnel and its copies as
    they were. One while they move leaves the copies already moved running in
    the new tunnel, under its staged name, and the rest in the old one: in the
    old one none of them could start again (_move_members). The copy whose own
    move failed stays stopped in the old one, since it stops before its move
    (_clone_into): the next try, STAGED_STALE_SECONDS later, moves it, and the
    heartbeat starts it in the new tunnel. The heartbeat finishes that change
    once it is STAGED_STALE_SECONDS old (_finish_staged).

    One kept under RETIRED_SUFFIX by a redeploy that did not finish gets its
    name back when that name is free or empty (_reclaim_retired). When
    another copy holds the name, its copies move into the tunnel under that
    name instead, which runs the proxy's current settings, once that tunnel
    is ready (started first when it is down) and is not an older worker's
    too; until then, nothing is done.
    Either way the copies end up in the tunnel this returns.

    ``deadline`` bounds the image pull (start_sidecar). The caller holds the
    proxy's lock, never _swap_lock."""
    _check_move_targets(client, _members(client, tunnel), move_target)
    pid = int(_labels(tunnel).get(LABEL_PROXY, ""))
    key = _own_key(tunnel)
    final = shared_tunnel_name(pid, key)
    if str(tunnel.name) != final:
        _reclaim_retired(client, pid, key, final)
        tunnel.reload()
    if str(tunnel.name) != final:
        target = _get(client, final)
        if not _is_tunnel_for(target, pid, key) or _restarts_by_itself(target):
            raise ProxyTunnelError(t("err.proxy_tunnel.replaced_once_runs_worker_s", name=tunnel.name, final=final))
        for member in _members(client, tunnel):
            _refuse_unmovable(member)  # before the target is started for them
        if target.status != "running":
            # Down, as when every copy in it was stopped: started on the
            # settings it holds, as a start does, since a copy moving in should
            # run. Nothing else starts it, so the move would wait for good.
            refresh_proxy_ip(target)
            target.start()
            try:
                _wait_ready(target)
            except Exception:
                _stop_if_unwanted(client, target)
                raise
        if (exit_info := _read_exit(target)) is None:
            raise ProxyTunnelError(t("err.proxy_tunnel.replaced_once_ready", name=tunnel.name, final=final))
        with _swap_lock:
            _move_members(client, tunnel, target, target=move_target)
            _remove_quietly(tunnel, SIDECAR_STOP_SECONDS)
        logger.info(
            "Moved the copies of %s, which an older worker made to restart by itself, into %s", tunnel.name, final
        )
        return target, exit_info
    try:
        files = _read_all_files(tunnel)
    except Exception as exc:  # noqa: BLE001 - the detail may hold the proxy's secrets
        raise ProxyTunnelError(
            t("err.proxy_tunnel.could_not_read_settings", name=tunnel.name, exc=redact(str(exc)))
        ) from None
    if host := files.get("proxy_host"):
        files["proxy_ip"] = resolve_proxy_ip(host)
    files = _with_digest(files)
    replaced = _ensure_tunnel(
        client,
        pid,
        None,
        files.get("own_ip") or None,
        files=files,
        slug=key,
        deadline=deadline,
        move_target=move_target,
    )
    logger.info("Replaced %s, which an older worker made to restart by itself", tunnel.name)
    return replaced


#: Tunnel id -> time.monotonic() of the heartbeat's last failed try to replace it (_replace_restarting_tunnels).
_replace_failed: dict[str, float] = {}
_recovery_skipped: set[str] = set()
RECOVERY_SKIPPED = (
    "Recovery skipped because a container in this tunnel does not match the worker's saved ID, "
    "or the worker has no saved ID for it yet."
)
#: Seconds an image pull under the proxy's lock waits for the tunnel image: the
#: heartbeat's replacement (_replace_restarting_tunnels) and a start (_pull_deadline).
REPLACE_PULL_SECONDS = 60
#: Held while the heartbeat's replacement runs, so a beat starts no second one (_replace_soon).
_replacing = threading.Lock()


def _in_background(work: Any) -> None:
    """Run ``work`` in a thread of its own. Tests run it in place (tests/conftest.py)."""
    threading.Thread(target=work, name="tunnel-replacement", daemon=True).start()


def _replace_soon() -> None:
    """Start _replace_restarting_tunnels in the background, unless a try is still running.

    One try can take minutes: an image pull, the new tunnel's exit
    (READY_TIMEOUT), then each copy's stop (its stop timeout). Run in the
    heartbeat, it held the heartbeat past the UI's offline threshold."""
    if not _replacing.acquire(blocking=False):
        return

    def work() -> None:
        try:
            _replace_restarting_tunnels()
        finally:
            _replacing.release()

    try:
        _in_background(work)
    except BaseException:
        if _replacing.locked():
            _replacing.release()
        raise


def _replace_restarting_tunnels() -> None:
    """Replace, for the heartbeat, a tunnel an older worker made that a copy in it should run in.

    In the background (_replace_soon), one try per beat; a tunnel whose try
    failed waits STAGED_STALE_SECONDS for the next, so the others get theirs.
    The image pull waits REPLACE_PULL_SECONDS at most, since it holds the
    proxy's lock (a Stop waits for it): a pull past that fails the try before
    anything changed, and Docker finishes it for the next. Under the proxy's
    lock (one someone holds means the next beat), and only once its copies
    are settled: none
    half moved, aside or left by a deploy that did not finish, since
    recreating one would lose the record that tells it apart. A running one
    with no exit is left: a new one on its settings would have none either.
    One whose copies are all stopped is left for the start that brings one
    back, which replaces it (_ensure_tunnel).

    A shared tunnel is replaced (_replace_restarting), also one kept under
    RETIRED_SUFFIX. A legacy pair's tunnel moves its copy into the shared
    tunnel (_migrate_proxy), only once that copy must start or restart, when
    its tunnel is ready: until then it runs where it is, and is not recreated."""
    try:
        client = orchestrator._get_client()
        found = client.containers.list(
            all=True, filters={"label": [f"{LABEL_MANAGED}=true", f"{LABEL_ROLE}={ROLE_TUNNEL}", LABEL_PROXY]}
        )
    except Exception:  # noqa: BLE001 - _status reports a listing that fails
        return
    _recovery_skipped.intersection_update(tunnel_item.id for tunnel_item in found)
    for tunnel in found:
        pid = _labels(tunnel).get(LABEL_PROXY, "")
        if (
            not pid.isdigit()
            or not _is_tunnel(tunnel, int(pid))
            or not _restarts_by_itself(tunnel)
            or str(tunnel.name).endswith(STAGED_SUFFIX)
        ):
            continue
        shared = _is_shared(tunnel, int(pid))
        if shared and str(tunnel.name).removesuffix(RETIRED_SUFFIX) != shared_tunnel_name(int(pid), _own_key(tunnel)):
            continue
        if time.monotonic() - _replace_failed.get(tunnel.id, -STAGED_STALE_SECONDS) < STAGED_STALE_SECONDS:
            continue
        lock = _deploy_lock(int(pid))
        if not lock.acquire(blocking=False):
            continue
        try:
            tunnel.reload()  # read under the lock, not from the listing
            if not (_restarts_by_itself(tunnel) and _settled_and_wanted(client, tunnel, pid)):
                continue
            ready = tunnel.status == "running" and _read_exit(tunnel) is not None
            if tunnel.status == "running" and not ready:
                continue
            if not shared and not (ready and _must_start(client, tunnel)):
                continue
            try:
                deadline = time.monotonic() + REPLACE_PULL_SECONDS
                if shared:
                    _replace_restarting(client, tunnel, deadline=deadline)
                elif not _migrate_proxy(client, int(pid), [tunnel], deadline=deadline):
                    raise ProxyTunnelError(t("err.proxy_tunnel.copy_could_not_move_into"))
                _replace_failed.pop(tunnel.id, None)
                _recovery_skipped.discard(tunnel.id)
            except orchestrator.DeployTargetChanged:
                _replace_failed[tunnel.id] = time.monotonic()
                _recovery_skipped.add(tunnel.id)
                logger.warning("%s Tunnel: %s", RECOVERY_SKIPPED, tunnel.name)
            except Exception as exc:  # noqa: BLE001 - it stays as it is, and no earner starts in it
                _replace_failed[tunnel.id] = time.monotonic()
                text = str(exc) if isinstance(exc, ProxyTunnelError) else redact(str(exc))
                logger.warning("Could not replace %s, which restarts by itself: %s", tunnel.name, text)
            return
        except NotFound:
            pass
        except Exception as exc:  # noqa: BLE001 - the next beat looks again
            logger.warning("Could not look at %s, which restarts by itself: %s", tunnel.name, redact(str(exc)))
        finally:
            lock.release()


def _must_start(client: Any, tunnel: Any) -> bool:
    """Whether a copy in ``tunnel``, which is ready, is one the heartbeat would start or restart. Raises OSError."""
    stopped = held()
    return any(
        str(m.name) not in stopped and earner_action(m, tunnel, True) in ("start", "restart")
        for m in _members(client, tunnel)
    )


def _settled_and_wanted(client: Any, tunnel: Any, proxy_id: str) -> bool:
    """Whether every copy in ``tunnel`` is settled and one of them should run. See _replace_restarting_tunnels."""
    members = _members(client, tunnel)
    if not members or _moving(client, proxy_id):
        return False
    try:
        stopped = held()
        if any(
            str(m.name).endswith((STAGED_SUFFIX, MOVING_SUFFIX, orchestrator.REPLACED_SUFFIX)) or _recorded_failed(m)
            for m in members
        ):
            return False
    except OSError:
        return False
    return any(str(m.name) not in stopped for m in members)


def _start_down_tunnel(tunnel: Any, proxy_id: str, name: str) -> None:
    """Start a tunnel that is down while the copy ``name`` in it should run, for the heartbeat; never waited for.

    Under the proxy's lock, as every tunnel and earner start: a lock someone
    holds means the next beat. The stop marker is read again under that lock,
    since a stop takes it to record itself: a stop that landed after the
    caller read the marker is never undone here. Nothing starts its copies
    here; the heartbeat does once the run says it is ready."""
    lock = _deploy_lock(int(proxy_id)) if str(proxy_id).isdigit() else None
    if lock is None or not lock.acquire(blocking=False):
        return
    started = False
    try:
        try:
            if name in held():
                return
        except OSError as exc:
            logger.warning("Could not read which copies are stopped (%s); not starting %s", exc, tunnel.name)
            return
        tunnel.reload()
        if tunnel.status != "exited" or _restarts_by_itself(tunnel):
            return
        refresh_proxy_ip(tunnel)
        tunnel.start()
        started = True
        logger.info("Started %s, which was down while a copy in it should run", tunnel.name)
    except Exception as exc:  # noqa: BLE001 - the next beat tries again
        logger.warning("Could not start %s: %s", tunnel.name, redact(str(exc)))
    finally:
        lock.release()
    if started:
        # Its bridge address is new: give it its exception to an exit node or
        # proxy on one of the owner's lines now, as _wait_ready does for a deploy.
        lan_fence.tunnel_started()


def test(proxy: dict[str, Any], own_ip: str | None) -> dict[str, Any]:
    """Start a throwaway sidecar, read the exit IP it gets, and remove it on every path."""
    client = orchestrator._get_client()
    name = f"{TUNNEL_PREFIX}test-{uuid.uuid4().hex[:10]}"
    began = time.monotonic()
    sidecar, exit_info = start_sidecar(client, name, TEST_SLUG, None, proxy, own_ip)
    try:
        return {**exit_info, "ms": int((time.monotonic() - began) * 1000)}
    finally:
        _remove_quietly(sidecar, SIDECAR_STOP_SECONDS)
