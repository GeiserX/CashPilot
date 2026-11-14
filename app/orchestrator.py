"""Docker container orchestrator for CashPilot.

Runs inside the CashPilot Worker, which has the Docker socket mounted.
Manages container lifecycle (deploy, stop, restart, remove) and status
inspection for cashpilot-managed containers via the Docker SDK.
"""

from __future__ import annotations

import collections
import contextlib
import functools
import hashlib
import ipaddress
import logging
import os
import re
import secrets
import shlex
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any

import docker
import requests
from docker.errors import APIError, DockerException, NotFound

# docker-py's run() and create() refuse stop_timeout although the Engine API and
# the low-level create_container() accept it, so a container could only ever
# carry Docker's default of 10 seconds. That default governs every stop that
# does not pass its own timeout: a plain `docker stop`, Docker Desktop quitting,
# a host shutting down. Registering the key lets run() forward it.
if "stop_timeout" not in docker.models.containers.RUN_CREATE_KWARGS:
    docker.models.containers.RUN_CREATE_KWARGS.append("stop_timeout")

try:
    from app.catalog import critical_volume_targets, get_service, get_services, identity_digest, identity_keys
except ImportError:
    # Defensive fallback if the catalog module isn't importable in some context.
    # (The worker image does ship catalog.py + services/, so this normally no-ops.)
    get_service = None  # type: ignore[assignment]
    get_services = None  # type: ignore[assignment]
    critical_volume_targets = None  # type: ignore[assignment]
    identity_digest = None  # type: ignore[assignment]
    identity_keys = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

from app import socket_policy, version  # noqa: E402
from app.constants import (  # noqa: E402
    CASHPILOT_DEPLOYED,
    CONTAINER_PREFIX,
    LABEL_CATEGORY,
    LABEL_DEPLOYED_BY,
    LABEL_INSTANCE,
    LABEL_MANAGED,
    LABEL_PROXY,
    LABEL_RESTORE,
    LABEL_ROLE,
    LABEL_SERVICE,
    LABEL_STATE_CREATED,
    LABEL_VERSION,
    START_SETTLE_SECONDS,
    drift_warnings_enabled,
)

# Cached Docker availability (checked once at startup, refreshed on demand)
_docker_available: bool | None = None

# In-memory status cache — populated by health check, served instantly to UI
_status_cache: list[dict[str, Any]] = []
_status_cache_time: float = 0.0


def _mark_docker_unavailable(reason: str, exc: BaseException) -> None:
    """Flip the availability memo to False, saying so LOUDLY on the transition.

    Docker going away mid-life used to be a logger.debug — invisible at the
    default INFO level — so a worker silently degraded to monitor-only, every
    deploy 503'd, and `docker logs` contained no reason at all. The transition
    is the loud moment; a persisting outage stays quiet (the caller's per-call
    debug covers it) so a dead daemon does not warn once per probe forever.
    Only True -> False warns: None -> False is startup discovering a
    monitor-only worker, which lifespan already announces.
    """
    global _docker_available
    if _docker_available is True:
        logger.warning(
            "Docker became unreachable (%s): %s — degrading to monitor-only until it returns",
            reason,
            exc,
        )
    _docker_available = False


def _mark_docker_available() -> None:
    """Flip the availability memo to True, announcing a recovery."""
    global _docker_available
    if _docker_available is False:
        logger.warning("Docker is reachable again — container management restored")
    _docker_available = True


def docker_available() -> bool:
    """Check whether the Docker socket is accessible.

    Only the positive result is memoized. A negative/unknown result is
    re-probed on every call so a transient daemon blip self-heals. The memo is
    invalidated by any code path that catches a live Docker failure (see
    _mark_docker_unavailable), so a daemon that dies AFTER a successful probe
    is re-discovered rather than reported available forever.
    """
    if _docker_available:
        return True
    client = None
    try:
        client = docker.from_env()
        client.ping()
        _mark_docker_available()
    except Exception as exc:
        logger.debug("Docker ping failed: %s", exc)
        _mark_docker_unavailable("ping failed", exc)
    finally:
        # A ping that RAISED used to leak the half-built client and its pool.
        if client is not None:
            with contextlib.suppress(Exception):
                client.close()
    return bool(_docker_available)


def _get_client() -> docker.DockerClient:
    """Return a Docker client, raising a clear error if the socket is missing."""
    try:
        client = docker.from_env()
        client.ping()
        _mark_docker_available()
        return client
    except DockerException as exc:
        _mark_docker_unavailable("client connect failed", exc)
        if proxied():
            raise RuntimeError(
                "The Docker socket proxy is not answering. Check that the "
                f"{PROXY_SERVICE} container is running (docker compose ps) and "
                f"read its log (docker logs {PROXY_SERVICE})."
            ) from exc
        raise RuntimeError(
            "Docker socket not available. Mount /var/run/docker.sock to "
            "enable container management, or use CashPilot in monitor-only "
            "mode for earnings tracking and compose file export."
        ) from exc


# ---------------------------------------------------------------------------
# Docker socket proxy
#
# The shipped compose files give the worker no Docker socket. A pinned
# sockguard container holds it and serves a filtered copy as a unix socket in
# the named volume below; DOCKER_HOST points every docker.from_env() at it.
# The proxy reads request bodies, so it refuses a privileged container, a bind
# of / or of the socket, an added capability outside the catalog's, and exec
# of anything but the catalog's readers. The policy is in the compose file.
# ---------------------------------------------------------------------------

#: Where the proxy's socket is mounted, in the worker and in the update helper.
PROXY_SOCKET_DIR = "/run/cashpilot-docker"
#: The named volume that carries it. Fixed name (`name:` in compose), so the
#: update helper can mount it whatever the compose project is called. It
#: carries the proxy's owner label, so the helper may mount it; the name moved
#: from cashpilot-docker-api because Compose never relabels a volume.
PROXY_VOLUME = "cashpilot-docker-api-owned"
#: Every name the socket volume has had. A worker on this image whose compose
#: file is older still uses the first one, so neither may go to a container.
PROXY_VOLUMES = (PROXY_VOLUME, "cashpilot-docker-api")
#: The proxy's compose service and container name.
PROXY_SERVICE = "cashpilot-socket-proxy"
#: Host paths the proxy lets the worker bind, as the compose file passes them.
COMPOSE_DIR_ENV = "CASHPILOT_COMPOSE_DIR"
BIND_MOUNTS_ENV = "CASHPILOT_PROXY_BIND_MOUNTS"


def proxied() -> bool:
    """True when the worker reaches Docker through the socket proxy."""
    return os.getenv("DOCKER_HOST", "").strip().startswith(f"unix://{PROXY_SOCKET_DIR}/")


def docker_access() -> str:
    """How the worker reaches Docker, "proxy" or "socket", for the status page."""
    return "proxy" if proxied() else "socket"


_policy_digest: str | None = None


def proxy_policy_current() -> bool | None:
    """Whether the proxy's policy is the one this worker image was built for.

    The policy sits in the operator's compose file, which an image update never
    rewrites, while the catalog in the image can need new exec readers,
    capabilities or Docker calls. The compose file gives the worker the policy's
    fingerprint (CASHPILOT_PROXY_POLICY); a different one means the proxy runs
    an older (or newer) policy than the image expects. None when not proxied.
    """
    global _policy_digest
    if not proxied():
        return None
    if _policy_digest is None:
        _policy_digest = socket_policy.digest()
    return os.getenv("CASHPILOT_PROXY_POLICY", "").strip() == _policy_digest


#: Compose does not recreate a container when only its config's content
#: changes, so the proxy is named: a plain `up -d` can leave it on the old policy.
PROXY_RECREATE = f"docker compose up -d --force-recreate {PROXY_SERVICE} cashpilot-worker"


def proxy_policy_fix() -> dict[str, str] | None:
    """How to bring the proxy's policy up to this image's, or None when it is.

    The worker never rewrites the policy itself: it is what the policy
    restricts (app/socket_policy.py). It names this release and both ways to
    take its policy, so the operator does it in one step.
    """
    if proxy_policy_current() is not False:
        return None
    current = version.current()
    # Only a plain X.Y.Z is a published tag and image; dev, latest or a custom
    # build string links main and the latest image instead.
    release = re.fullmatch(r"\d+\.\d+\.\d+", current) is not None
    tag = current if release else "latest"
    ref = f"v{current}" if release else "main"
    return {
        "release": version.display(),
        "command": (
            f"docker run --rm -i --network none drumsergio/cashpilot-worker:{tag} "
            "python -m app.socket_policy < docker-compose.yml > docker-compose.new.yml"
        ),
        "url": f"https://github.com/GeiserX/CashPilot/blob/{ref}/docker-compose.worker.yml",
        "recreate": PROXY_RECREATE,
    }


def proxy_policy_fix_text(fix: dict[str, str]) -> str:
    """The fix as one sentence for the log and the status page."""
    return (
        f"its policy is not the one this worker image ({fix['release']}) expects, so some calls may be "
        "refused. An image update never changes the policy: it lives in your compose file. Update it with "
        f"`{fix['command']}`, check the diff, use the new file in place of yours, then run "
        f"`{PROXY_RECREATE}` (with your -f if you use one). "
        "Or copy the lines from '# BEGIN socket proxy policy' to '# END socket proxy policy', and the "
        f"CASHPILOT_PROXY_POLICY line, from {fix['url']} (the same in every compose file of the release)."
    )


def proxy_refusal(exc: BaseException) -> str | None:
    """The proxy's reason for refusing a call, as a sentence, or None.

    sockguard answers a refused call with 403 and a JSON body whose ``reason``
    names the rule. docker-py keeps only the body's ``message`` (the generic
    "request denied by sockguard policy") as the explanation, so the reason is
    read from the response. Anything that is not the proxy's 403, Docker's own
    errors included, returns None and keeps its existing handling.
    """
    if getattr(exc, "status_code", None) != 403:
        return None
    response = getattr(exc, "response", None)
    try:
        body = response.json() if response is not None else None
    except Exception:  # noqa: BLE001 - not JSON: not the proxy
        return None
    if not isinstance(body, dict):
        return None
    message = " ".join(str(body.get("message") or "").split())
    if "sockguard" not in message and "policy denied" not in message:
        return None
    reason = " ".join(str(body.get("reason") or message).split())[:300]
    text = f"The Docker socket proxy refused this: {reason}."
    if "bind" in reason.lower() or "mount" in reason.lower():
        text += (
            f" To let containers use a host folder, add it to {BIND_MOUNTS_ENV} in the .env "
            "next to your compose file (comma-separated), then run docker compose up -d."
        )
    return text


def _container_name(slug: str, instance: int = 1) -> str:
    base = f"{CONTAINER_PREFIX}{slug}"
    return base if instance <= 1 else f"{base}-{instance}"


def _instance_of(container: Any) -> int:
    """Which copy of its service a container is; 1 when unlabelled."""
    try:
        return max(1, int((container.labels or {}).get(LABEL_INSTANCE) or 1))
    except (TypeError, ValueError):
        return 1


def _stop_facts(container: Any) -> dict[str, Any]:
    """When a stopped container stopped, how, and whether Docker will start it again.

    Only for an exited or dead container, so a running fleet's heartbeat does
    not grow. The UI uses these to alert on a container that has stayed down:
    the timestamp says for how long, and a restart policy of "no" is why a
    clean exit stayed down for days instead of being restarted.
    """
    if getattr(container, "status", "") not in ("exited", "dead"):
        return {}
    attrs = container.attrs if isinstance(getattr(container, "attrs", None), dict) else {}
    state = attrs.get("State") if isinstance(attrs.get("State"), dict) else {}
    host = attrs.get("HostConfig") if isinstance(attrs.get("HostConfig"), dict) else {}
    policy = host.get("RestartPolicy") if isinstance(host.get("RestartPolicy"), dict) else None
    facts: dict[str, Any] = {}
    finished = state.get("FinishedAt")
    # Docker's zero time means "never finished", which is not a date.
    if isinstance(finished, str) and finished and not finished.startswith("0001-"):
        facts["finished_at"] = finished
    if isinstance(state.get("ExitCode"), int):
        facts["exit_code"] = state["ExitCode"]
    if policy is not None:
        # An empty name is Docker's "no".
        facts["restart_policy"] = str(policy.get("Name") or "no")
    return facts


# The fatal-pattern check reads the last 20 log records of the run and judges
# their last 4 KB. Docker has no byte limit on a log read, so a record can be
# up to 16 KB and the read up to 320 KB; the time window (since/until
# StartedAt) keeps it to one run. The provider's refusal is the last thing the
# client prints before it exits, so it is inside the 4 KB.
_FATAL_LOG_LINES = 20
_FATAL_LOG_CHARS = 4096


def match_fatal(logs: str, signals: Any) -> str | None:
    """``"account_disabled"`` when such a catalog health signal matches ``logs``, else None.

    pawns-cli prints "user is disabled" with no newline on every start, so the
    text is searched as a whole, never line by line. A bad entry is skipped.
    """
    if not logs or not isinstance(signals, list):
        return None
    tail = logs[-_FATAL_LOG_CHARS:]
    for item in signals:
        if not isinstance(item, dict) or item.get("state") != "account_disabled" or not item.get("pattern"):
            continue
        try:
            if re.search(str(item["pattern"]), tail, re.IGNORECASE):
                return "account_disabled"
        except re.error:
            continue
    return None


# A running copy younger than this has not yet shown the provider accepts it:
# a refused pawns-cli lives 0.4 to 1.8 s, and a heartbeat that lands in that
# window must not read as a recovery.
_FATAL_PROVEN_AFTER_S = 120


def _docker_epoch(value: Any) -> float | None:
    """Docker's StartedAt/FinishedAt (RFC 3339, UTC, nanoseconds) as a Unix time; None for its zero time."""
    if not isinstance(value, str) or len(value) < 19 or value.startswith("0001-"):
        return None
    try:
        whole = datetime.fromisoformat(value[:19]).replace(tzinfo=UTC).timestamp()
    except ValueError:
        return None
    frac = value[19:].split("Z")[0].split("+")[0]
    if frac.startswith(".") and frac[1:].isdigit():
        whole += float("0." + frac[1:7])
    return whole


def _fatal_entry(container: Any, slug: str) -> dict[str, Any]:
    """``{"fatal": "account_disabled", "fatal_at": <FinishedAt>}`` when the last finished run was refused.

    Only for a service whose catalog entry declares an account_disabled
    ``docker.health_signals`` entry, so a healthy fleet costs no log read.

    - Restarting, exited or dead: the log of the last run only (since its
      StartedAt), so an earlier run's refusal is not judged as this one.
    - Running for under two minutes: the log before this start, that is the
      previous run. A crash loop is "running" for about a second per minute,
      and that second is not a recovery.
    - Running longer: nothing to say, no log read.

    ``fatal_at`` is when the refused run ended, so the UI can tell a refusal
    that came before a balance read (stale) from one after it. Never raises:
    a log that cannot be read says nothing.
    """
    status = getattr(container, "status", "")
    if status not in ("running", "restarting", "exited", "dead") or not get_service:
        return {}
    signals = ((get_service(slug) or {}).get("docker") or {}).get("health_signals")
    if not isinstance(signals, list) or not any(
        isinstance(s, dict) and s.get("state") == "account_disabled" for s in signals
    ):
        return {}
    attrs = container.attrs if isinstance(getattr(container, "attrs", None), dict) else {}
    state = attrs.get("State") if isinstance(attrs.get("State"), dict) else {}
    started = _docker_epoch(state.get("StartedAt"))
    finished = state.get("FinishedAt")
    if _docker_epoch(finished) is None:
        # Never finished a run: nothing was refused yet.
        return {}
    window: dict[str, float] = {}
    if status == "running":
        if started is None or time.time() - started >= _FATAL_PROVEN_AFTER_S:
            return {}
        window["until"] = started
    elif started is not None:
        window["since"] = started
    try:
        raw = container.logs(tail=_FATAL_LOG_LINES, **window)
    except Exception as exc:  # noqa: BLE001 - an unreadable log is no finding
        logger.debug("Could not read the log of %s for its fatal patterns: %s", getattr(container, "name", "?"), exc)
        return {}
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw or "")
    kind = match_fatal(text, signals)
    return {"fatal": kind, "fatal_at": finished} if kind else {}


def _held_entry(container: Any) -> dict[str, Any]:
    """``{"held": why}`` for a container the fence guard keeps stopped (lan_fence.guard), else nothing.

    The guard's last pass, so the dashboard can say on the service itself why
    the node is down and what brings it back, not only on the Fleet page.
    """
    from app import lan_fence

    why = (lan_fence._state.get("guard") or {}).get(getattr(container, "name", None))
    return {"held": str(why)} if why else {}


def _shape(container: Any) -> dict[str, Any]:
    """What a container was created with, on the settings that decide whether it works.

    The UI compares this with what a redeploy would build from the current
    catalog (app/drift.py), so a container made before a catalog fix is not left
    broken in silence. Bitping ran three months without NET_RAW, added to the
    catalog after its containers were made, with every probe failing.

    Names only, never values: env keys without their values, mount targets
    without their sources. The command is not here at all, since it carries
    credentials; the UI judges it from the deployment record instead.
    """
    attrs = container.attrs if isinstance(getattr(container, "attrs", None), dict) else {}
    config = attrs.get("Config") if isinstance(attrs.get("Config"), dict) else {}
    host = attrs.get("HostConfig") if isinstance(attrs.get("HostConfig"), dict) else {}
    devices = host.get("Devices") if isinstance(host.get("Devices"), list) else []
    mounts = attrs.get("Mounts") if isinstance(attrs.get("Mounts"), list) else []
    entrypoint = config.get("Entrypoint")
    return {
        "image": str(config.get("Image") or ""),
        "cap_add": sorted({str(cap).upper().removeprefix("CAP_") for cap in host.get("CapAdd") or []}),
        "privileged": bool(host.get("Privileged")),
        "network_mode": str(host.get("NetworkMode") or ""),
        "devices": sorted(
            {str(d.get("PathInContainer") or "").rstrip("/") for d in devices if isinstance(d, dict)} - {""}
        ),
        "ports": sorted(str(key) for key in (host.get("PortBindings") or {})),
        "mounts": sorted({str(m.get("Destination") or "").rstrip("/") for m in mounts if isinstance(m, dict)} - {""}),
        "env_keys": sorted({str(item).split("=", 1)[0] for item in config.get("Env") or []}),
        "entrypoint": [str(part) for part in entrypoint] if isinstance(entrypoint, list) else None,
        "restart_policy": str((host.get("RestartPolicy") or {}).get("Name") or "no"),
    }


def _shape_entry(container: Any) -> dict[str, Any]:
    """``{"shape": ...}`` for a container CashPilot's worker made, else nothing.

    The cashpilot labels alone do not make a container CashPilot's: a compose
    file exported from CashPilot carries them too, and the user runs and edits
    that by hand. Only CashPilot's own deploys write the values in
    CASHPILOT_DEPLOYED. A hand-made
    container is never judged against the catalog, and neither is anything
    when CASHPILOT_DRIFT_WARNINGS is off.
    """
    labels = getattr(container, "labels", None) or {}
    if labels.get(LABEL_DEPLOYED_BY) not in CASHPILOT_DEPLOYED or not drift_warnings_enabled():
        return {}
    return {"shape": _shape(container)}


def is_proxied(container: Any) -> bool:
    """A proxied copy or its tunnel sidecar (app/proxy_tunnel.py).

    Neither is "copy N" of its service. A proxied copy carries no instance
    label, so without this check _instance_of() reads it as copy 1, and
    stopping or removing copy 1 could hit it instead.
    """
    try:
        labels = container.labels
        if not isinstance(labels, dict):
            return False
        return bool(labels.get(LABEL_PROXY) or labels.get(LABEL_ROLE))
    except Exception:  # noqa: BLE001 - an unreadable container is handled by the caller's own guard
        return False


def service_instances(slug: str, client: Any = None) -> list[Any]:
    """Every managed container of ``slug`` on this worker, first copy first.

    Proxied copies and tunnels are not copies of the service; see is_proxied.
    ``client`` lets a caller list on its own client, with its own timeout.
    """
    client = client or _get_client()
    found = client.containers.list(all=True, filters={"label": [f"{LABEL_SERVICE}={slug}", f"{LABEL_MANAGED}=true"]})
    return sorted((c for c in found if not is_proxied(c)), key=_instance_of)


def _find_container(slug: str, instance: int = 1):
    """Find a MANAGED container by name, falling back to label-based lookup.

    The name match must verify the cashpilot.managed label, not just the
    prefix: the platform's own containers are named cashpilot-worker and
    cashpilot-ui, so slug "worker" name-matched the worker's OWN container
    and a writer-role command could force-remove it -- the worker deleting
    itself, unrecoverable remotely (CashPilot-o4uw). A name hit without the
    label is treated exactly like NotFound.
    """
    client = _get_client()
    name = _container_name(slug, instance)
    try:
        container = client.containers.get(name)
        if (
            (container.labels or {}).get(LABEL_MANAGED) == "true"
            and not is_proxied(container)
            and _instance_of(container) == instance
        ):
            return container
    except NotFound:
        pass
    # Fallback: find by label (handles renamed containers). Only the copy asked
    # for: with several copies running, "the first match" would stop or remove
    # whichever one Docker happened to list first.
    matches = client.containers.list(
        all=True,
        filters={
            "label": [
                f"{LABEL_SERVICE}={slug}",
                f"{LABEL_MANAGED}=true",
            ]
        },
    )
    for match in matches:
        if not is_proxied(match) and _instance_of(match) == instance:
            return match
    raise ValueError(f"Container for {slug} not found" if instance <= 1 else f"Instance {instance} of {slug} not found")


def _normalize_resources(resources: Any) -> dict[str, Any]:
    """Coerce a resources spec (Pydantic model, dict, or None) into a plain dict.

    Only non-None values are kept, so callers can splat the result into
    ``containers.run`` without clobbering Docker's own defaults.
    """
    if resources is None:
        return {}
    if hasattr(resources, "model_dump"):
        data = resources.model_dump()
    elif isinstance(resources, dict):
        data = dict(resources)
    else:
        return {}
    return {k: v for k, v in data.items() if v is not None}


# A hostile or runaway image must not be able to exhaust the host's PID namespace.
# Generous for a real earner (these run a single process tree); raise it with
# CASHPILOT_PIDS_LIMIT if a service legitimately needs more.
_PIDS_LIMIT_DEFAULT = 512


def _read_pids_limit() -> int:
    """Parse CASHPILOT_PIDS_LIMIT, falling back to the default on bad input.

    This is read at import time, so a bare int() would turn a typo like "512m"
    into a ValueError that stops the worker from starting at all — a container
    limit knob must never be able to take the whole worker down. A non-positive
    value is also rejected: Docker reads 0/-1 as "unlimited", which would
    silently disable the very limit this exists to enforce.
    """
    raw = os.getenv("CASHPILOT_PIDS_LIMIT")
    if not raw:
        return _PIDS_LIMIT_DEFAULT
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid CASHPILOT_PIDS_LIMIT=%r (not an integer); using %d", raw, _PIDS_LIMIT_DEFAULT)
        return _PIDS_LIMIT_DEFAULT
    if value <= 0:
        logger.warning("CASHPILOT_PIDS_LIMIT=%d would disable the PID limit; using %d", value, _PIDS_LIMIT_DEFAULT)
        return _PIDS_LIMIT_DEFAULT
    return value


_PIDS_LIMIT = _read_pids_limit()


def available_runtimes() -> set[str] | None:
    """Runtimes the local Docker daemon actually reports, or None if unaskable.

    The allowlist is derived from the daemon rather than hardcoded, because a
    runtime CashPilot has heard of but the host has not installed would fail at
    container-create time with a Docker error the user cannot act on. Asking the
    daemon means the only runtimes offered are ones that exist here.

    None, not an empty set, when the daemon cannot be asked: "no runtimes
    installed here" is a caller mistake (400), "daemon unreachable" is an
    outage (503), and collapsing them told the operator to fix the wrong
    thing. The probe uses its OWN short-timeout client — the shared client
    keeps the SDK's long default because deploys legitimately take minutes,
    but a validation probe hanging 60s per call could pile onto the executor.
    """
    client = None
    try:
        client = docker.from_env(timeout=5)
        info = client.info()
    except Exception as exc:
        logger.warning("Could not read Docker runtimes (daemon unreachable?): %s", exc)
        return None
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                client.close()
    runtimes = info.get("Runtimes")
    return set(runtimes) if isinstance(runtimes, dict) else set()


#: A user-defined bridge the operator created for the earners, so their host
#: firewall rules can name one interface (docs/home-network-security.md).
#: Empty means Docker's default bridge, as before.
_CONTAINER_NETWORK = os.getenv("CASHPILOT_CONTAINER_NETWORK", "").strip()


class ContainerNetworkError(RuntimeError):
    """CASHPILOT_CONTAINER_NETWORK names a network this worker cannot use."""


def container_network(network_mode: str | None) -> str | None:
    """The network a new container joins, or None for Docker's default bridge.

    Only a container that would otherwise land on the default bridge moves: host
    or none networking is the service's own choice. With CASHPILOT_CONTAINER_NETWORK
    set the worker never creates the network (or any firewall rule); a network
    that is missing, or is not a bridge, is refused here, BEFORE anything is
    removed, so a typo cannot take a running service down.
    """
    # "default" is Docker's other name for the default bridge, so it moves too.
    if (network_mode or "bridge") not in ("bridge", "default"):
        return None
    if not _CONTAINER_NETWORK:
        # No network of the operator's: CashPilot's own fenced bridge, unless
        # isolation is off or this is an upgraded install not switched yet
        # (app/lan_fence.py). Raises ContainerNetworkError when the fence
        # cannot be applied, which is also before anything is touched.
        from app import lan_fence

        return lan_fence.network_for_deploy()
    try:
        network = _get_client().networks.get(_CONTAINER_NETWORK)
    except NotFound:
        raise ContainerNetworkError(
            f"CASHPILOT_CONTAINER_NETWORK is {_CONTAINER_NETWORK!r}, and no network by that name exists on "
            f"this host. Create it first: docker network create --driver bridge "
            f"-o com.docker.network.bridge.name=cp-isolated {_CONTAINER_NETWORK}"
        ) from None
    attrs = network.attrs or {}
    if (attrs.get("Name") or getattr(network, "name", "")) == "bridge" or (attrs.get("Options") or {}).get(
        "com.docker.network.bridge.default_bridge"
    ) == "true":
        raise ContainerNetworkError(
            "CASHPILOT_CONTAINER_NETWORK names Docker's default bridge, which every other container shares, "
            "so no firewall rule can single out the earners. Name the bridge you created for them."
        )
    driver = attrs.get("Driver")
    if driver != "bridge":
        raise ContainerNetworkError(
            f"CASHPILOT_CONTAINER_NETWORK is {_CONTAINER_NETWORK!r}, a {driver!r} network. Only a bridge keeps "
            f"the containers behind this host's firewall rules."
        )
    return _CONTAINER_NETWORK


#: Resolvers for containers on an isolated bridge (CashPilot's own or
#: CASHPILOT_CONTAINER_NETWORK). Docker's embedded
#: resolver forwards their lookups from inside that network, so a daemon whose
#: list starts with a LAN or tailnet resolver gets refused by the very rules
#: that isolate the bridge, and every lookup waits about 4 s before Docker
#: falls through to the next server. Empty keeps the daemon's own list.
_CONTAINER_DNS = os.getenv("CASHPILOT_CONTAINER_DNS", "1.1.1.1,9.9.9.9")


def container_dns(network: str | None) -> list[str] | None:
    """The resolvers a new container gets, or None for the daemon's own.

    Only a container joined to the operator's isolated bridge gets them; every
    other container, and the host, keep Docker's default. A setting that is not
    a list of IP addresses is refused here, before the running container is
    touched, for the same reason as container_network.
    """
    if not network:
        return None
    servers = [entry.strip() for entry in _CONTAINER_DNS.split(",") if entry.strip()]
    for server in servers:
        try:
            ipaddress.ip_address(server)
        except ValueError:
            raise ContainerNetworkError(
                f"CASHPILOT_CONTAINER_DNS has {server!r}; it takes IP addresses separated by commas, "
                f"for example 1.1.1.1,9.9.9.9, or nothing to keep the Docker daemon's resolvers."
            ) from None
    return servers or None


#: The runtime for containers on bridge networking when the deploy request
#: names none, e.g. a gVisor runtime registered in daemon.json. Empty means
#: Docker's default, as before. CashPilot never picks one for the operator.
_CONTAINER_RUNTIME = os.getenv("CASHPILOT_CONTAINER_RUNTIME", "").strip()
#: Per-service exceptions, "slug=runtime,slug=runtime": a service that needs
#: raw sockets gets a runtime registered with --net-raw, and "runc" runs one
#: under the runtime Docker ships with.
_CONTAINER_RUNTIME_OVERRIDES = os.getenv("CASHPILOT_CONTAINER_RUNTIME_OVERRIDES", "").strip()


class ContainerRuntimeError(RuntimeError):
    """The runtime settings name a runtime this worker cannot use.

    ``status_code`` is what the worker API answers: 409 for a setting the
    operator has to fix, 503 when the daemon cannot be asked at all.
    """

    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


def _runtime_overrides() -> dict[str, str]:
    overrides: dict[str, str] = {}
    for entry in _CONTAINER_RUNTIME_OVERRIDES.split(","):
        if not entry.strip():
            continue
        slug, sep, runtime = entry.partition("=")
        if not sep or not slug.strip() or not runtime.strip():
            raise ContainerRuntimeError(
                f"CASHPILOT_CONTAINER_RUNTIME_OVERRIDES has {entry.strip()!r}; each entry is slug=runtime, "
                f"for example bitping=runsc-hostnet-raw."
            )
        overrides[slug.strip()] = runtime.strip()
    return overrides


def _proxy_allows_runtime(slug: str, runtime: str) -> str:
    """Refuse, before anything is touched, a runtime the socket proxy would refuse.

    The daemon may offer more runtimes (io.containerd.runc.v2, nvidia, crun,
    kata) than the proxy policy allows; a create the proxy refuses comes after
    the old container is gone, so it is caught here instead.
    """
    if proxied() and runtime not in socket_policy.ALLOWED_RUNTIMES:
        raise ContainerRuntimeError(
            f"{slug} would run under the {runtime!r} runtime, and the Docker socket proxy allows only "
            f"{', '.join(socket_policy.ALLOWED_RUNTIMES)}. The running container was not touched. Pick one "
            f"of those in CASHPILOT_CONTAINER_RUNTIME or its overrides, or deploy without a runtime."
        )
    return runtime


def container_runtime(slug: str, network_mode: str | None, requested: str | None) -> str | None:
    """The runtime a new container runs under, or None for Docker's default.

    A runtime named in the deploy request wins; the worker API has already
    checked it against the daemon. A runtime the service's catalog entry
    requires wins over both. Otherwise a container on bridge networking takes
    the service's override or the worker's default. Host and none networking
    keep Docker's default: a sandbox gains little on the host's own network
    stack. Mysterium's catalog entry requires runc: a TUN device works under
    gVisor, but iptables-nft and kernel WireGuard do not.

    Like container_network, a runtime the daemon does not provide is refused
    here, BEFORE the running container is stopped, so a typo in the compose
    file cannot take a service down.
    """
    if required := catalog_runtime(slug):
        # The service's own catalog entry names the one runtime it works under
        # (Mysterium: runc, since gVisor has no iptables-nft or kernel WireGuard).
        # Neither the request nor the operator's default can change it.
        return _proxy_allows_runtime(slug, required)
    if requested:
        return _proxy_allows_runtime(slug, requested)
    if (network_mode or "bridge") not in ("bridge", "default"):
        return None
    runtime = _runtime_overrides().get(slug, _CONTAINER_RUNTIME)
    if not runtime:
        return None
    _proxy_allows_runtime(slug, runtime)
    available = available_runtimes()
    if available is None:
        raise ContainerRuntimeError(
            f"Cannot check the {runtime!r} runtime: the Docker daemon is not answering.", status_code=503
        )
    if runtime not in available:
        raise ContainerRuntimeError(
            f"The runtime settings give {slug} the {runtime!r} runtime, which this host's Docker daemon "
            f"does not provide. Available: {sorted(available) or 'none reported'}. Register it in "
            f"/etc/docker/daemon.json and restart Docker, or change CASHPILOT_CONTAINER_RUNTIME."
        )
    return runtime


#: Held while deploy_raw replaces a fence-gated container (Mysterium). The
#: guard (lan_fence.guard) takes it for each pass, and while a deploy holds it
#: the guard only stops: it starts nothing and reads no identity. Otherwise a
#: pass could start the old node between its stop and its removal, or read the
#: old node's identity, match the record deploy_raw just wrote, and delete it,
#: so the new node would never be compared.
GATED_DEPLOY_LOCK = threading.Lock()


#: Slugs a restore (restore_state) is creating now, and how many deploy_raw
#: calls run per slug, both under _SLUG_WORK_LOCK. A deploy replaces the
#: container of its slug and keeps its volumes, so one that met a restore's
#: created container would start a node on a half-written volume. Each refuses
#: while the other runs; restore_state calls deploy_raw.__wrapped__, which
#: skips this.
_SLUG_WORK_LOCK = threading.Lock()
_restoring: set[str] = set()
_deploying: dict[str, int] = {}


def _holds_gated_lock(fn: Any) -> Any:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        slug = str(kwargs.get("slug", args[0] if args else ""))
        with _SLUG_WORK_LOCK:
            if slug in _restoring:
                raise ContainerRuntimeError(
                    f"A restore of {slug} is running on this box, so nothing was deployed. Try again when it ends.",
                    409,
                )
            _deploying[slug] = _deploying.get(slug, 0) + 1
        try:
            if not fence_gated(slug):
                return fn(*args, **kwargs)
            with GATED_DEPLOY_LOCK:
                return fn(*args, **kwargs)
        finally:
            with _SLUG_WORK_LOCK:
                _deploying[slug] -= 1
                if not _deploying[slug]:
                    del _deploying[slug]

    return wrapper


@_holds_gated_lock
def deploy_raw(
    slug: str,
    image: str,
    env: dict[str, str] | None = None,
    ports: dict[str, int | tuple[str, int]] | None = None,
    volumes: dict[str, dict[str, str]] | None = None,
    network_mode: str | None = None,
    cap_add: list[str] | None = None,
    devices: list[str] | None = None,
    command: str | None = None,
    hostname: str | None = None,
    labels: dict[str, str] | None = None,
    resources: Any = None,
    category: str = "bandwidth",
    runtime: str | None = None,
    moved_mounts: list[str] | None = None,
    kept_mounts: list[dict[str, str]] | None = None,
    keep_targets: set[str] | None = None,
    instance: int = 1,
    name: str | None = None,
    start: bool = True,
) -> str:
    """Deploy a container from a raw spec (no catalog lookup).

    ``start=False`` is for a restore (restore_state): the container is created
    and left unstarted, and only where none of that name exists. Nothing is
    replaced, so nothing is moved aside or kept.

    A container being REPLACED keeps the mounts it has now — see
    ``_keep_live_mounts``. ``moved_mounts`` names the targets the operator
    relocated on purpose this deploy; ``keep_targets`` limits keeping to the
    targets the caller vouches for; ``kept_mounts``, when given, is filled with
    what was kept so the caller can report it.

    ``network_mode="container:<id>"`` and ``name`` are for app/proxy_tunnel.py
    only: the worker API refuses a container: network mode from any caller.
    A container that joins another's namespace gets no ports, resolvers or
    hostname of its own, because Docker refuses them there.

    Used by CashPilot Worker when the UI sends a full container spec.
    ``resources`` (mem_limit / mem_reservation / oom_score_adj / cpu_shares)
    makes the container's cgroup limits durable across recreates. Returns the
    container ID.
    """
    client = _get_client()
    name = name or _container_name(slug, instance)
    joined = (network_mode or "").startswith("container:")
    gated = fence_gated(slug)

    # Decided before the old container is touched: a network or runtime that
    # cannot be used must fail the deploy while the running service is still running.
    # The resolvers are checked here for the same reason.
    network = container_network(network_mode)
    runtime = container_runtime(slug, network_mode, runtime)
    dns = container_dns(network)
    # Another service's wallet or identity volume is never this container's,
    # whoever asks (the worker API checks it first; this is the backstop).
    refuse_critical_mounts(slug, volumes, client)
    if gated:
        from app import lan_fence

        # A mode that cannot run it at all (off, legacy) is refused here too,
        # while the running node is still running.
        gated_mode = lan_fence.resolve_mode(client)
        if problem := lan_fence.mode_problem(gated_mode, service_name(slug)):
            raise ContainerNetworkError(f"{slug} was not deployed: {problem} The running container was not touched.")

    # The pull is on this side of the line for the same reason: a registry outage
    # or a typo'd image must not cost the running container. And once the image
    # is here, what it would run as PID 1 is known, so an image that cannot run
    # under this worker's hardening is refused now, not left to loop.
    logger.info("Pulling image %s", image)
    pull_error: APIError | None = None
    try:
        client.images.pull(image)
    except APIError as exc:
        pull_error = exc
        logger.warning("Failed to pull image %s: %s (trying local)", image, exc)
    try:
        image_config = client.images.get(image).attrs.get("Config") or {}
    except DockerException as exc:
        # No local copy after a failed pull, or a daemon that cannot describe
        # the image it just pulled: either way there is nothing to run, and
        # removing the old container first would only make that worse.
        raise ContainerRuntimeError(
            f"{image} is not available on this worker: {pull_error or exc}. The running container was not touched."
        ) from None
    entrypoint = _get_entrypoint(slug)
    _refuse_init_image(image, image_config, entrypoint, command)

    # Replace any existing container with the same name. It is stopped and
    # moved aside, not removed, until its replacement runs: Docker can still
    # refuse the new one (a host port another program holds), and then the old
    # one goes back as it was (_roll_back).
    replaced = None
    replaced_running = False
    identity_before = _identity_snapshot(name)
    held_before = _MISMATCH_HELD.get(name)
    stopped_before = name in user_stopped()
    try:
        old = client.containers.get(name)
        if not start:
            raise ContainerRuntimeError(
                f"{name} already exists, so nothing was restored. A restore only creates a new container.", 409
            )
        # The name alone is not proof the container is this copy of this
        # service: copy 2 of "foo" and copy 1 of a service slugged "foo-2" are
        # both cashpilot-foo-2. Replacing another service's container would
        # stop it and start this one under its name, so that is refused.
        old_labels = old.labels if isinstance(getattr(old, "labels", None), dict) else {}
        old_slug = old_labels.get(LABEL_SERVICE)
        if (old_slug and old_slug != slug) or (old_slug == slug and _instance_of(old) != instance):
            raise ContainerRuntimeError(
                f"{name} already belongs to {old_slug} (copy {_instance_of(old)}), not to copy {instance} of "
                f"{slug}. It was left running; remove it or deploy under another name."
            )
        if problem := _aside_taken(client, old, name, slug):
            raise ContainerRuntimeError(problem)
        volumes, kept = _keep_live_mounts(old, volumes, moved_mounts, keep_targets)
        if kept:
            # A kept mount is the old container's own: one made before this
            # check existed must not carry another service's volume forward.
            refuse_critical_mounts(slug, volumes, client)
        for entry in kept:
            logger.warning(
                "%s keeps %s at %s; the spec asked for %s",
                name,
                entry["kept"],
                entry["target"],
                entry["requested"],
            )
        if kept_mounts is not None:
            kept_mounts.extend(kept)
        # A kept mount is the running container's own, never checked against
        # the proxy's folders by the worker API. One the proxy will not bind
        # would otherwise be found only after the running node is gone.
        refused = _outside_proxy_roots(volumes)
        if refused:
            raise ContainerRuntimeError(
                f"{name} keeps its data in {', '.join(refused)}, and the Docker socket proxy does not let "
                f"containers bind that folder, so the replacement could not be created. The running "
                f"container was not touched. Add the folder to {BIND_MOUNTS_ENV} in the .env next to your "
                "compose file (comma-separated), then run docker compose up -d."
            )
        _ensure_volumes(client, volumes)
        # Stop it the way stop and restart do, with the catalog's timeout, before
        # removing it. remove(force=True) alone is SIGKILL: a storage node gets no
        # chance to flush (storj declares 300 s for that reason) and pays for it
        # with an unclean-shutdown recovery. A stop that fails is not a reason to
        # abandon the deploy - the forced removal below is what ran before.
        if gated:
            # A deploy is the owner's way out of a hold, written down or not.
            _MISMATCH_HELD.pop(name, None)
        if gated and not _pending_identity(name):
            # Read while it still runs; the guard compares the new one with it.
            # A redeploy over a stopped node clears the record instead. A record
            # still pending is kept: the container being replaced is itself a
            # replacement whose identity was never confirmed, so this retry is
            # compared with the node as it was before the first redeploy.
            running = getattr(old, "status", "") == "running"
            identity = read_node_identity(old, slug) if running else None
            if running and identity is None and _reads_identity(slug):
                # Without it the new node could run on another keystore unchecked.
                # Nothing is replaced, so the hold popped above comes back. Only
                # the memory moved: the record on disk is left as it is, and a
                # hold set meanwhile is newer than the one popped, so it stays.
                if held_before is not None:
                    _MISMATCH_HELD.setdefault(name, held_before)
                raise ContainerRuntimeError(
                    f"{name} was not replaced: its identity could not be read from the running node, so the new "
                    "one could not be checked against it. The running container was not touched. Try again in a "
                    "minute. If the node is broken, stop it from the dashboard first: a stopped node is replaced "
                    "without the check."
                )
            _remember_identity(name, identity)
        replaced_running = getattr(old, "status", "") == "running"
        try:
            old.stop(timeout=_get_stop_timeout(slug))
        except NotFound:
            raise
        except Exception as exc:  # noqa: BLE001 - a timeout is no proof it stopped either
            logger.warning("Could not stop %s cleanly before replacing it: %s", name, exc)
            if _still_running(old):
                # Its replacement would run beside it on the same identity volume.
                _restore_identity(name, identity_before, held_before)
                raise ContainerRuntimeError(
                    f"{name} could not be stopped ({exc}), so it was not replaced and is still running. "
                    "Try again in a minute.",
                    409,
                ) from exc
        try:
            replaced = _move_aside(client, old, name, slug)
        except NotFound:
            raise
        except Exception as exc:  # noqa: BLE001 - whatever failed, the old node must run again
            # A rename that timed out may still have happened: give it its name back.
            with contextlib.suppress(Exception):
                old.reload()
                if str((old.attrs or {}).get("Name") or "").lstrip("/") != name:
                    old.rename(name)
            _restore_identity(name, identity_before, held_before)
            restored = "The previous container was not replaced and " + _start_again(
                client, old, replaced_running, gated, name
            )
            raise _deploy_failure(exc, restored, slug) from exc
    except NotFound:
        _ensure_volumes(client, volumes)

    all_labels = {
        LABEL_SERVICE: slug,
        LABEL_MANAGED: "true",
        LABEL_VERSION: "1",
        LABEL_CATEGORY: category,
        LABEL_DEPLOYED_BY: "worker",
    }
    if labels:
        all_labels.update(labels)
        # What the guard, the owner checks and every lookup find a container by:
        # never the caller's to change.
        all_labels[LABEL_SERVICE] = slug
        all_labels[LABEL_MANAGED] = "true"
    if instance > 1:
        all_labels[LABEL_INSTANCE] = str(instance)

    # Durable resource limits (only passed when explicitly set, so Docker
    # defaults are preserved otherwise). memswap is deliberately left unset:
    # at create time mem_limit alone avoids the cgroup-v2 swap validation issue.
    res = _normalize_resources(resources)
    resource_kwargs = {
        key: res[key]
        for key in ("mem_limit", "mem_reservation", "oom_score_adj", "cpu_shares")
        if res.get(key) is not None
    }

    # The resource kwargs are logged because the deploy response only says
    # "deployed" — nothing echoes which limits were applied, and a worker whose
    # ResourceSpec predates a key silently drops it (Pydantic ignores extras).
    # This line makes `docker logs cashpilot-worker` state what THIS worker
    # applied, so an operator comparing against the catalog can see the gap.
    logger.info("Creating container %s from %s (resources: %s)", name, image, resource_kwargs or "docker defaults")
    # A fence-gated container is created, then started only once the fence is
    # confirmed again: containers.run would start it in the same call.
    run_kwargs: dict[str, Any] = dict(
        image=image,
        name=name,
        environment=env or {},
        ports=ports if ports and network_mode != "host" and not joined else None,
        volumes=volumes if volumes else None,
        # docker-py refuses network and network_mode together; a container moved
        # onto the operator's bridge is joined to it and nothing else.
        network_mode=None if network else network_mode,
        network=network,
        # Only set on the isolated bridge; see container_dns.
        dns=dns,
        # These images are third-party and closed-source, so they get the minimum
        # kernel surface: every capability dropped, then only the ones the service's
        # own catalog entry declares added back (docs/fleet.md lists them; most
        # services are plain outbound TCP clients and add nothing). Without this
        # they ran as in-container root with Docker's full default set, which
        # includes NET_RAW (ARP/DNS spoofing on the bridge), MKNOD, SETUID and
        # SYS_CHROOT.
        devices=devices or None,
        cap_drop=["ALL"],
        cap_add=cap_add or None,
        # no-new-privileges blocks privilege escalation via setuid binaries; privileged
        # is hardcoded off so the dangerous state is unrepresentable here rather than
        # merely refused upstream by the worker's spec validation.
        security_opt=["no-new-privileges:true"],
        privileged=False,
        pids_limit=_PIDS_LIMIT,
        # From the worker's own catalog (see _get_entrypoint), like the stop
        # timeout below: neither is something the deploy request can set.
        entrypoint=entrypoint,
        command=command if command else None,
        # The container keeps the catalog's grace for every stop, not only the
        # ones this worker sends with an explicit timeout.
        stop_timeout=_get_stop_timeout(slug),
        labels=all_labels,
        hostname=None if joined else (hostname or name),
        # A container inside another's namespace is never started by Docker on
        # its own: after a reboot or a daemon restart it would join the tunnel's
        # namespace before the tunnel's firewall is loaded. The worker starts it
        # once the tunnel says it is ready (proxy_tunnel.status).
        # A fence-gated one (Mysterium) neither: Docker would start it after a
        # reboot before this worker has put the fence back. The worker's guard
        # starts it once the fence is confirmed (lan_fence.guard).
        restart_policy={"Name": "no"} if joined or gated else {"Name": "unless-stopped"},
        # None means Docker's default runtime. See container_runtime for when
        # the operator's CASHPILOT_CONTAINER_RUNTIME applies instead.
        runtime=runtime or None,
        **resource_kwargs,
    )
    created = None
    began = time.monotonic()
    try:
        try:
            container = (
                client.containers.create(**run_kwargs)
                if gated or not start
                else client.containers.run(detach=True, **run_kwargs)
            )
            created = container
            if not start:
                # Restore: the caller writes the data, checks it, then starts it.
                logger.info("Container %s created, not started: %s", name, container.short_id)
                return container.id
            if gated:
                _mark_stopped(name, False)
                # Left created, not started, when the fence is not confirmed: the guard
                # starts it as soon as it is, and nothing runs before that.
                _require_fence(slug)
                container.start()
        except ContainerNetworkError:
            raise
        except Exception as exc:
            # No answer is not a refusal: Docker may still be starting it. A gated
            # create that got none was never started, so there is nothing to wait for.
            if not _outcome_unknown(exc) or (gated and created is None):
                raise
            container = created = _await_start(client, name, created, began, exc)
        if gated:
            from app import lan_fence

            if problem := lan_fence._started_unattached(container, gated_mode):
                raise ContainerRuntimeError(f"{name} did not come up on its network: {problem}.")
    except ContainerNetworkError:
        # The fence went between the checks above and the start: the new node is
        # created and the guard starts it once the fence reads complete.
        if gated:
            _mark_failed(name, False)
        _remove_replaced(replaced, name, slug)
        raise
    except Exception as exc:
        restored = _roll_back(
            client,
            name,
            slug,
            replaced,
            replaced_running,
            identity_before,
            stopped_before,
            held_before=held_before,
            created=created,
            gated=gated,
        )
        raise _deploy_failure(exc, restored, slug) from exc
    if gated:
        _mark_failed(name, False)
    _remove_replaced(replaced, name, slug)
    logger.info("Container %s started: %s", name, container.short_id)
    return container.id


#: Suffix of a container moved aside while its replacement is created.
REPLACED_SUFFIX = "-replaced"


def _move_aside(client: Any, old: Any, name: str, slug: str) -> Any | None:
    """Rename the stopped ``old`` out of its name; remove it if it cannot be renamed. The renamed one, or None."""
    aside = f"{name}{REPLACED_SUFFIX}"
    with contextlib.suppress(NotFound):
        # One left by a deploy that did not finish is older than ``old``.
        leftover = client.containers.get(aside)
        if leftover is not old and getattr(leftover, "id", None) != getattr(old, "id", None):
            _remove_container(leftover, slug)
    # A rename Docker refuses raises: the old one keeps its name and is never
    # removed before its replacement runs.
    old.rename(aside)
    logger.info("Moved %s aside as %s until its replacement runs", name, aside)
    return old


def _aside_taken(client: Any, old: Any, name: str, slug: str) -> str | None:
    """Why the name ``old`` would be moved aside to belongs to another container, or None."""
    aside = f"{name}{REPLACED_SUFFIX}"
    try:
        leftover = client.containers.get(aside)
    except NotFound:
        return None
    if leftover is old or getattr(leftover, "id", None) == getattr(old, "id", None):
        return None
    labels = leftover.labels if isinstance(getattr(leftover, "labels", None), dict) else {}
    if labels.get(LABEL_SERVICE) == slug and _instance_of(leftover) == _instance_of(old):
        return None
    return (
        f"{name} was not replaced: {aside}, the name it is moved aside to while its replacement starts, belongs to "
        f"{labels.get(LABEL_SERVICE) or 'a container CashPilot did not deploy'}. The running container was not "
        "touched; remove or rename that container, then redeploy."
    )


def _still_running(container: Any) -> bool:
    try:
        container.reload()
    except NotFound:
        return False
    except Exception:  # noqa: BLE001 - not known stopped is treated as running
        return True
    return getattr(container, "status", "") == "running"


def _remove_replaced(replaced: Any | None, name: str, slug: str) -> None:
    """Remove the old container once its replacement is in place; a failure leaves a leftover only."""
    if replaced is None:
        return
    try:
        _remove_container(replaced, slug)
    except Exception as exc:  # noqa: BLE001 - the guard never starts it, and the next deploy removes it
        logger.warning("Could not remove %s%s after its replacement was created: %s", name, REPLACED_SUFFIX, exc)


def _start_again(client: Any, old: Any, was_running: bool, gated: bool, name: str) -> str:
    """Start the previous container again if it ran, a gated one only behind a complete fence. Says how it is."""
    if not was_running:
        return "is stopped as it was."
    if gated and not predates_fence(old):
        from app import lan_fence

        try:
            fence = lan_fence.fence_problem(client)
        except Exception as exc:  # noqa: BLE001 - not confirmed is not complete
            fence = f"the fence could not be checked ({exc})"
        if fence:
            logger.warning("Not starting %s again yet: %s", name, fence)
            return f"is kept stopped until the LAN fence is complete again ({fence}); the worker starts it then."
    try:
        old.start()
    except Exception as exc:  # noqa: BLE001 - reported to the caller
        logger.warning("Could not start %s again: %s", name, exc)
        return f"could not be started again ({exc})."
    return "is running again."


def _roll_back(
    client: Any,
    name: str,
    slug: str,
    replaced: Any | None,
    was_running: bool,
    identity_before: str | None,
    stopped_before: bool,
    *,
    held_before: str | None = None,
    created: Any | None = None,
    gated: bool,
) -> str:
    """Undo a deploy whose new container could not be created or started. Says what was put back.

    The half-made container goes, the old one gets its name back and runs
    again if it ran, and the identity and stop records are as they were. A
    leftover that cannot be removed is marked, so the guard never starts it.
    """
    leftover_gone = True
    taken = False
    try:
        current = client.containers.get(name)
        # Only what this deploy made: its own container, or (when Docker
        # failed inside the create-and-start call) one that is not running.
        # A running one there is another deploy's, and it is left alone.
        if created is not None:
            ours = getattr(current, "id", None) == getattr(created, "id", None)
        else:
            ours = getattr(current, "status", "") != "running"
        if ours:
            _remove_container(current, slug)
        else:
            leftover_gone, taken = False, True
    except NotFound:
        pass
    except Exception as exc:  # noqa: BLE001 - reported below
        leftover_gone = False
        logger.warning("Could not remove the container the failed deploy of %s left: %s", name, exc)
    _restore_identity(name, identity_before, held_before)
    _mark_stopped(name, stopped_before)
    if gated and not leftover_gone and not taken:
        _mark_failed(name, True)
    if replaced is None:
        return "No container ran under that name before, so nothing was put back."
    if taken:
        return (
            f"Another deploy took the name meanwhile, so the previous container is kept, stopped, as "
            f"{name}{REPLACED_SUFFIX}."
        )
    if not leftover_gone:
        return (
            f"The previous container is kept, stopped, as {name}{REPLACED_SUFFIX}: the failed one still holds "
            "the name. Remove it, then redeploy."
        )
    try:
        replaced.rename(name)
    except Exception as exc:  # noqa: BLE001 - reported to the caller
        logger.warning("Could not put %s back: %s", name, exc)
        return f"The previous container could not be put back ({exc}); it is kept as {name}{REPLACED_SUFFIX}."
    logger.info("Put the previous %s back after a failed deploy", name)
    return "The previous container was put back and " + _start_again(client, replaced, was_running, gated, name)


def _deploy_failure(exc: BaseException, restored: str, slug: str = "") -> ContainerRuntimeError:
    """The error a failed create or start answers with, after the roll-back."""
    if isinstance(exc, ContainerRuntimeError):
        return ContainerRuntimeError(f"{exc} {restored}", exc.status_code)
    refusal = proxy_refusal(exc) if isinstance(exc, APIError) else None
    if refusal:
        return ContainerRuntimeError(f"{refusal} {restored}", 403)
    if isinstance(exc, APIError):
        reason = " ".join(str(exc.explanation or exc).split())[:300]
        return ContainerRuntimeError(
            f"Docker refused the container: {reason}{_ephemeral_hint(reason, slug)} {restored}"
        )
    return ContainerRuntimeError(f"The container could not be created: {exc}. {restored}", 500)


#: What the socket proxy answers when it stopped waiting for Docker (sockguard
#: cuts a call whose answer has not begun after 30 s): Docker may still be at it.
_GATEWAY_STATUSES = frozenset({502, 504})
#: Seconds between two looks at a container whose start got no answer.
_START_POLL_SECONDS = 2.0


def _outcome_unknown(exc: BaseException) -> bool:
    """Whether a Docker call that raised may still have done its work: no answer, rather than a refusal.

    docker-py's own read timeout or a dropped connection, or the socket proxy's
    gateway answer. A refusal (a taken port, a proxy rule, a bad spec) is an
    answer, and is not waited on.
    """
    # APIError first: docker-py derives it from requests' HTTPError, and it is Docker's answer.
    if isinstance(exc, APIError):
        return getattr(exc, "status_code", None) in _GATEWAY_STATUSES
    return isinstance(exc, requests.exceptions.RequestException)


def _await_start(client: Any, name: str, created: Any | None, began: float, exc: BaseException) -> Any:
    """The container under ``name`` once Docker has started it; raises when it did not.

    For a create or start whose call ended without Docker's answer: Docker goes
    on starting the container after the proxy or docker-py stopped waiting, and
    each published port slows the start (a node with 1,000 UDP ports took about
    51 s). Removing it then, as a refused start is, took down a node Docker was
    still bringing up. Looks until it runs, Docker reports the start failed, or
    START_SETTLE_SECONDS from the create call have passed.
    """
    logger.warning(
        "Docker did not answer the start of %s (%s); waiting up to %d s for it to come up",
        name,
        exc,
        START_SETTLE_SECONDS,
    )
    deadline = began + START_SETTLE_SECONDS
    while True:
        try:
            current = created if created is not None else client.containers.get(name)
            # Docker answers an inspect only once the start lets go of the container.
            current.reload()
        except NotFound:
            raise ContainerRuntimeError(f"{name} is gone: Docker did not start it ({exc}).", 500) from exc
        except Exception as poll_exc:  # noqa: BLE001 - not known yet; looked at again below
            logger.debug("Could not read %s while it starts: %s", name, poll_exc)
        else:
            attrs = current.attrs if isinstance(getattr(current, "attrs", None), dict) else {}
            state = attrs.get("State") if isinstance(attrs.get("State"), dict) else {}
            status = getattr(current, "status", "")
            if status == "running":
                logger.info("%s came up %.0f s after its create call", name, time.monotonic() - began)
                return current
            if status in ("exited", "dead") or (status == "created" and state.get("Error")):
                why = state.get("Error") or f"it is {status}"
                raise ContainerRuntimeError(f"{name} did not start: {why}.", 500) from exc
        if time.monotonic() >= deadline:
            # 500, not 504: the deploy is rolled back by the time this is answered,
            # and a 504 tells a caller the worker may still be at it (main keeps a
            # proxied copy's record on one).
            raise ContainerRuntimeError(
                f"{name} was not running {START_SETTLE_SECONDS} s after Docker was asked to start it ({exc}).", 500
            ) from exc
        time.sleep(_START_POLL_SECONDS)


from app.constants import EPHEMERAL_PORTS  # noqa: E402 - Linux's default ephemeral range


def _ephemeral_hint(reason: str, slug: str = "") -> str:
    """Why a taken UDP port in Linux's ephemeral range failed the start, and what to do.

    The setting to change and its default come from the service's catalog
    entry (``udp_port_range``); a service without one gets the general advice.
    """
    if "already" not in reason:
        return ""
    for port in re.findall(r":(\d+)/udp", reason):
        if EPHEMERAL_PORTS[0] <= int(port) <= EPHEMERAL_PORTS[1]:
            why = (
                f" UDP port {port} is in Linux's ephemeral range ({EPHEMERAL_PORTS[0]}-{EPHEMERAL_PORTS[1]}), where "
                "any program on the host can hold a port for a moment, and one taken port fails the whole start."
            )
            docker_conf = ((get_service(slug) if get_service and slug else None) or {}).get("docker") or {}
            rng = docker_conf.get("udp_port_range")
            key = str(rng.get("env") or "") if isinstance(rng, dict) else ""
            if not key:
                return why + f" Publish it on a port below {EPHEMERAL_PORTS[0]} instead."
            default = next(
                (str(v.get("default") or "") for v in docker_conf.get("env") or [] if v.get("key") == key), ""
            )
            shown = f" (the default is {default})" if default else ""
            return why + (
                f" Set {key} to a range below {EPHEMERAL_PORTS[0]}{shown} and forward that range on your router "
                "instead."
            )
    return ""


def _named_volumes(volumes: dict[str, Any] | list[str] | None) -> list[str]:
    """The named volumes (not host folders) a deploy mounts."""
    if not volumes:
        return []
    sources = [str(v).split(":", 1)[0] for v in volumes] if isinstance(volumes, list) else [str(v) for v in volumes]
    return [src for src in sources if src and not src.startswith("/")]


def _ensure_volumes(client: Any, volumes: dict[str, Any] | list[str] | None) -> None:
    """Create each named volume the deploy mounts, before any container is touched.

    Behind the proxy's owner isolation a container may only name a volume that
    exists and carries the owner label, and Docker's own create-on-first-use
    makes one without it. A volume made through the proxy gets the label; one
    an older release made without it (its migration has not run) is refused
    here, with the reason, while the running container is still running.
    """
    for vol in _named_volumes(volumes):
        try:
            client.volumes.get(vol)
        except NotFound:
            try:
                client.volumes.create(name=vol)
            except APIError as exc:
                # A proxy from an older compose file refuses the call, and has
                # no owner isolation either: Docker makes the volume with the
                # container, as it always did.
                if proxy_refusal(exc) is None:
                    raise
        except APIError as exc:
            refusal = proxy_refusal(exc)
            if refusal is None:
                raise
            raise ContainerRuntimeError(
                f"The volume {vol} was not made by this worker, so the Docker socket proxy will not let a "
                f"container use it ({refusal}). The running container was not touched. Run docker compose up -d "
                "with the current compose file once: its cashpilot-migrate step moves the volume over, data "
                "included (UPGRADING.md)."
            ) from None


# The main process of an image built to boot like a machine. Almost always
# systemd, which needs a privileged container with the host's cgroup tree;
# under the capability drop every deploy gets here it exits 255 at once, with
# nothing in the logs, and Docker's restart policy starts it again forever.
# /sbin/init is BusyBox init on Alpine, which has no more business as PID 1 of
# an earner, so the path is refused without naming the implementation.
_INIT_SYSTEMS = frozenset(
    {"/sbin/init", "/usr/sbin/init", "/lib/systemd/systemd", "/usr/lib/systemd/systemd", "systemd"}
)


def _boots_init_system(image_config: dict[str, Any], entrypoint: list[str] | None, command: str | None) -> bool:
    """True when the container would start an init system as PID 1.

    The catalog's entrypoint, when it declares one, replaces the image's; the
    request's command replaces the image's CMD but never its ENTRYPOINT. Only
    the first word of what finally runs matters.
    """
    if entrypoint:
        first = entrypoint[0]
    elif image_config.get("Entrypoint"):
        first = str(image_config["Entrypoint"][0])
    elif command:
        first = command.split()[0]
    else:
        cmd = image_config.get("Cmd") or []
        first = str(cmd[0]) if cmd else ""
    return first in _INIT_SYSTEMS


def _refuse_init_image(
    image: str, image_config: dict[str, Any], entrypoint: list[str] | None, command: str | None
) -> None:
    """Fail the deploy of an image that boots an init system, before anything runs.

    Raised as a 409 like the network and runtime settings: the message says
    what to do instead.
    """
    if _boots_init_system(image_config, entrypoint, command):
        raise ContainerRuntimeError(
            f"{image} runs an init system as its main process (/sbin/init, usually systemd), which needs a "
            "privileged container with the host's cgroup tree. CashPilot never grants that, so the "
            "container would exit at once and restart forever. Use the image's non-init tag (often "
            "':lite') or the catalog image."
        )


def _parse_stop_timeout(value: Any) -> int:
    """Parse a stop_timeout value, returning 30 on invalid input."""
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        return 30
    return timeout if timeout > 0 else 30


def _get_entrypoint(slug: str) -> list[str] | None:
    """The entrypoint override the catalog declares for ``slug``, if any.

    Read from the worker's OWN catalog, never from the deploy request: an
    entrypoint decides what runs as root inside the container, so the caller
    must not be able to choose it.
    """
    if not get_service:
        return None
    svc = get_service(slug)
    raw = (svc or {}).get("docker", {}).get("entrypoint")
    if isinstance(raw, list) and raw and all(isinstance(part, str) for part in raw):
        return list(raw)
    return None


def _get_stop_timeout(slug: str) -> int:
    """Return the stop timeout from the catalog, or 30s default."""
    if get_service:
        svc = get_service(slug)
        if svc:
            return _parse_stop_timeout(svc.get("docker", {}).get("stop_timeout"))
    return 30


def fence_gated(slug: str) -> bool:
    """Whether this worker's own catalog starts ``slug`` only behind a confirmed fence."""
    if not get_service:
        return False
    return ((get_service(slug) or {}).get("docker") or {}).get("fence_gated") is True


def catalog_runtime(slug: str) -> str | None:
    """The runtime this worker's own catalog requires for ``slug``, if any."""
    if not get_service:
        return None
    runtime = ((get_service(slug) or {}).get("docker") or {}).get("runtime")
    return runtime.strip() if isinstance(runtime, str) and runtime.strip() else None


#: Names of the fence-gated containers the owner stopped. Docker restarts none
#: of them (restart policy "no"), so the worker's guard starts each one that is
#: not running, except these: a Stop from the dashboard must stay a stop.
STOPPED_MARKER = os.path.join(os.getenv("CASHPILOT_DATA_DIR", "/data"), ".fence_gated_stopped")


def user_stopped() -> set[str]:
    try:
        with open(STOPPED_MARKER, encoding="utf-8") as fh:
            return {line.strip() for line in fh if line.strip()}
    except OSError:
        return set()


def _mark_stopped(name: str, stopped: bool, *, strict: bool = False) -> None:
    """Record or clear an owner's Stop. ``strict`` raises when it cannot be written.

    A Stop that is not recorded is undone by the guard's next pass, so Stop is
    strict. A Start or a deploy that cannot clear the record only leaves the
    node stopped, which is safe, so they log it.
    """
    names = user_stopped()
    if (name in names) == stopped:
        return
    names = names | {name} if stopped else names - {name}
    try:
        with open(STOPPED_MARKER, "w", encoding="utf-8") as fh:
            fh.write("".join(f"{n}\n" for n in sorted(names)))
    except OSError as exc:
        if strict:
            raise ContainerRuntimeError(
                f"{name} was not stopped: the stop could not be recorded ({exc}), and without that record the "
                "worker would start it again within a minute."
            ) from None
        logger.warning("Could not record that %s was %s: %s", name, "stopped" if stopped else "started", exc)


#: Fence-gated containers a failed deploy left that could not be removed. The
#: guard never starts one; the next deploy that succeeds clears it.
FAILED_MARKER = os.path.join(os.getenv("CASHPILOT_DATA_DIR", "/data"), ".fence_gated_failed")


#: The last mark the file could not take, by container name. A deploy that
#: worked must lift the mark even when /data cannot be written, or the guard
#: would keep stopping the node the owner just redeployed.
_FAILED_UNWRITTEN: dict[str, bool] = {}


def _failed_on_disk() -> set[str]:
    try:
        with open(FAILED_MARKER, encoding="utf-8") as fh:
            return {line.strip() for line in fh if line.strip()}
    except OSError:
        return set()


def deploy_failed() -> set[str]:
    names = _failed_on_disk()
    for name, failed in _FAILED_UNWRITTEN.items():
        names = names | {name} if failed else names - {name}
    return names


def _mark_failed(name: str, failed: bool) -> None:
    names = _failed_on_disk()
    if (name in names) == failed:
        _FAILED_UNWRITTEN.pop(name, None)
        return
    names = names | {name} if failed else names - {name}
    try:
        with open(FAILED_MARKER, "w", encoding="utf-8") as fh:
            fh.write("".join(f"{n}\n" for n in sorted(names)))
        _FAILED_UNWRITTEN.pop(name, None)
    except OSError as exc:
        _FAILED_UNWRITTEN[name] = failed
        logger.warning(
            "Could not record that the last deploy of %s %s: %s", name, "failed" if failed else "worked", exc
        )


def predates_fence(container: Any) -> bool:
    """A fence-gated service's container from 2.0.6 or earlier: on the host's network.

    Every Mysterium through 2.0.6 runs this way, and keeps running exactly as
    it is until its owner redeploys it: the guard neither stops nor starts it,
    and Start, Stop and Restart treat it as before. Drift and the isolation
    check flag it, and the redeploy moves it onto the fenced bridge.
    """
    attrs = container.attrs if isinstance(getattr(container, "attrs", None), dict) else {}
    host = attrs.get("HostConfig") if isinstance(attrs.get("HostConfig"), dict) else {}
    return str(host.get("NetworkMode") or "") == "host"


def _gated_container(slug: str, container: Any) -> bool:
    return fence_gated(slug) and not predates_fence(container)


def service_name(slug: str) -> str:
    """The catalog's display name for ``slug``, or the slug itself."""
    return str(((get_service(slug) if get_service else None) or {}).get("name") or slug)


def stop_service(slug: str, instance: int = 1) -> None:
    """Stop the container for a service."""
    # For a fence-gated service the container is looked up under the lock too: a
    # redeploy holds it while the old node sits renamed aside and the new one
    # starts, so a lookup made before would stop the old node, or one the
    # redeploy then removes, and leave the new node running.
    with GATED_DEPLOY_LOCK if fence_gated(slug) else contextlib.nullcontext():
        container = _find_container(slug, instance)
        if _gated_container(slug, container):
            # Recorded before the stop, under the guard's lock: a guard pass that
            # read the records before this Stop would otherwise start it after.
            _mark_stopped(container.name, True, strict=True)
        container.stop(timeout=_get_stop_timeout(slug))
    logger.info("Stopped container %s", container.name)


def restart_service(slug: str, instance: int = 1) -> None:
    """Restart the container for a service."""
    _refuse_mid_restore(slug, "started")
    container = _find_container(slug, instance)
    if _gated_container(slug, container):
        _require_startable(container, slug)
        _mark_stopped(container.name, False)
    container.restart(timeout=_get_stop_timeout(slug))
    logger.info("Restarted container %s", container.name)


#: The node identity a fence-gated container had before a redeploy replaced
#: it, one file per container name. The guard reads the new container's
#: identity until it matches, then deletes the file; a different identity
#: holds the node stopped (lan_fence.guard), since its data volume is not the
#: one it ran on.
IDENTITY_DIR = os.path.join(os.getenv("CASHPILOT_DATA_DIR", "/data"), ".fence_gated_identity")


def read_node_identity(container: Any, slug: str) -> str | None:
    """The node's own identity from inside it (collector.node_read), or None.

    Mysterium answers its TequilAPI identity on the node's loopback; the
    command and the pattern are the catalog's, the same the earnings read uses.
    """
    svc = (get_service(slug) if get_service else None) or {}
    spec = (svc.get("collector") or {}).get("node_read") or {}
    command, pattern = spec.get("command"), spec.get("node")
    if not (isinstance(command, list) and command and isinstance(pattern, str)):
        return None
    try:
        code, output = container.exec_run(command)
        match = re.search(pattern, (output or b"").decode(errors="replace")) if code == 0 else None
    except Exception as exc:  # noqa: BLE001 - unknown, not different
        logger.debug("Could not read the identity of %s: %s", getattr(container, "name", "?"), exc)
        return None
    return match.group(1) if match else None


def _reads_identity(slug: str) -> bool:
    """Whether the catalog says how to read this service's node identity (collector.node_read)."""
    svc = (get_service(slug) if get_service else None) or {}
    spec = (svc.get("collector") or {}).get("node_read") or {}
    return isinstance(spec.get("command"), list) and bool(spec.get("command")) and isinstance(spec.get("node"), str)


def _identity_file(name: str) -> str:
    return os.path.join(IDENTITY_DIR, re.sub(r"[^A-Za-z0-9_.-]", "_", name))


#: Mismatch holds by container name, kept in memory as well as on disk: a hold
#: whose record could not be written must still hold, or the stopped node
#: would read as unchecked and the guard would start it again every pass.
_MISMATCH_HELD: dict[str, str] = {}


def _identity_snapshot(name: str) -> str | None:
    """The identity record exactly as it is, or None when there is none."""
    try:
        with open(_identity_file(name), encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def _restore_identity(name: str, snapshot: str | None, held: str | None = None) -> None:
    """Put the identity record back as _identity_snapshot found it, and a hold kept only in memory."""
    path = _identity_file(name)
    try:
        if snapshot is None:
            if os.path.exists(path):
                os.remove(path)
        else:
            os.makedirs(IDENTITY_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(snapshot)
    except OSError as exc:
        logger.warning("Could not restore the identity record of %s: %s", name, exc)
    word, _, reason = (snapshot or "").strip().partition(" ")
    if held is not None:
        _MISMATCH_HELD[name] = held
    elif word == "MISMATCH":
        _MISMATCH_HELD[name] = reason
    else:
        _MISMATCH_HELD.pop(name, None)


def _pending_identity(name: str) -> str | None:
    """The identity a replacement still has to match, or None (no record, or a held mismatch)."""
    try:
        with open(_identity_file(name), encoding="utf-8") as fh:
            recorded = fh.read().strip()
    except OSError:
        return None
    return None if not recorded or recorded.startswith("MISMATCH ") else recorded


def _remember_identity(name: str, identity: str | None) -> None:
    if not str(identity or "").startswith("MISMATCH "):
        # A deploy rewrites the record: the owner's way out of a hold.
        _MISMATCH_HELD.pop(name, None)
    path = _identity_file(name)
    try:
        if identity:
            os.makedirs(IDENTITY_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(identity)
        elif os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        logger.warning("Could not record the identity of %s: %s", name, exc)


def identity_problem(container: Any) -> str | None:
    """Why a fence-gated node must stop: a different identity than before its redeploy.

    None while there is nothing to compare (no record, or the node not
    answering yet) and once it matches, when the record is deleted.
    """
    if held_reason := _MISMATCH_HELD.get(container.name):
        return held_reason
    path = _identity_file(container.name)
    try:
        with open(path, encoding="utf-8") as fh:
            expected = fh.read().strip()
    except OSError:
        return None
    held, _, rest = expected.partition(" ")
    if held == "MISMATCH":
        # Sticky until the next deploy rewrites the record: a stopped node
        # reads no identity, and must not be started again because of that.
        return rest
    if getattr(container, "status", "") != "running":
        return None
    slug = str((getattr(container, "labels", None) or {}).get(LABEL_SERVICE) or "")
    current = read_node_identity(container, slug)
    if current is None:
        return None
    if current.lower() == expected.lower():
        _remember_identity(container.name, None)
        logger.info("%s kept its identity %s across the redeploy", container.name, current)
        return None
    reason = (
        f"its identity is {current}, not {expected} as before the redeploy, so it is not running on the data "
        "volume that holds its keystore. It stays stopped: restore that volume, then redeploy"
    )
    _MISMATCH_HELD[container.name] = reason
    _remember_identity(container.name, f"MISMATCH {reason}")
    return reason


def _require_fence(slug: str) -> None:
    """Refuse to start a fence-gated service unless the fence is confirmed now.

    Raises ContainerNetworkError with the reason. Outside ``on`` mode there is
    no fence of ours to wait for: the operator's network carries their own
    rules, and ``off`` or ``legacy`` was the owner's choice.
    """
    from app import lan_fence

    problem = lan_fence.fence_problem(_get_client(), service_name(slug))
    if problem:
        raise ContainerNetworkError(f"{slug} was not started: {problem}")


def _require_startable(container: Any, slug: str) -> None:
    """Refuse Start or Restart of an existing fence-gated container the guard would stop.

    The fence first, then what the guard also holds against the container
    itself: its shape (host network, privileged, a capability, an image or a
    restart policy the catalog does not give it) and a different identity
    than before its last redeploy. Without this the dashboard reported it
    started, and it ran until the guard's next pass stopped it again.
    """
    from app import lan_fence

    _require_fence(slug)
    try:
        mode = lan_fence.resolve_mode(_get_client())
    except RuntimeError as exc:
        raise ContainerNetworkError(f"{slug} was not started: the isolation mode could not be read ({exc})") from None
    problem = (
        (lan_fence.FAILED_DEPLOY if getattr(container, "name", None) in deploy_failed() else None)
        or gated_spec_problem(container, mode)
        or identity_problem(container)
    )
    if problem:
        raise ContainerNetworkError(f"{slug} was not started: {problem}")


def gated_spec_problem(container: Any, mode: str | None = None) -> str | None:
    """Why a fence-gated container must not run as it is, or None.

    Read from the live container, so a container someone recreated by hand, or
    a worker of an older release made, is judged on what it is: on the host
    network, privileged, with a capability its catalog entry does not grant,
    started by Docker on its own, or on an image other than the pinned one.
    """
    labels = getattr(container, "labels", None) or {}
    slug = str(labels.get(LABEL_SERVICE) or "")
    svc = (get_service(slug) if get_service else None) or {}
    docker_conf = svc.get("docker") or {}
    attrs = container.attrs if isinstance(getattr(container, "attrs", None), dict) else {}
    host = attrs.get("HostConfig") if isinstance(attrs.get("HostConfig"), dict) else {}
    config = attrs.get("Config") if isinstance(attrs.get("Config"), dict) else {}
    network_mode = str(host.get("NetworkMode") or "")
    if network_mode == "host":
        return "it shares the host's network, where its NET_ADMIN would reach the host's firewall"
    if host.get("Privileged"):
        return "it runs privileged"
    want_caps = {str(c).upper().removeprefix("CAP_") for c in docker_conf.get("cap_add") or []}
    have_caps = {str(c).upper().removeprefix("CAP_") for c in host.get("CapAdd") or []}
    if extra := sorted(have_caps - want_caps):
        return f"it holds {', '.join(extra)}, which its catalog entry does not grant"
    policy = str((host.get("RestartPolicy") or {}).get("Name") or "no")
    if policy != "no":
        return f"Docker would start it on its own (restart policy {policy}), before the fence is confirmed"
    pinned = {docker_conf.get("image")} | set((docker_conf.get("image_by_arch") or {}).values())
    pinned -= {None, ""}
    if pinned and str(config.get("Image") or "") not in pinned:
        return f"it runs {config.get('Image') or 'an unknown image'}, not the image the catalog pins"
    from app import lan_fence

    if mode == lan_fence.MODE_ON and network_mode != lan_fence.NETWORK_NAME:
        return f"it is not on {lan_fence.NETWORK_NAME}, so the fence does not cover it"
    if mode == lan_fence.MODE_OPERATOR and network_mode != _CONTAINER_NETWORK:
        return f"it is not on {_CONTAINER_NETWORK}, the network whose rules this worker runs earners under"
    if mode in (lan_fence.MODE_ON, lan_fence.MODE_OPERATOR):
        settings = attrs.get("NetworkSettings") if isinstance(attrs.get("NetworkSettings"), dict) else {}
        attached = settings.get("Networks") if isinstance(settings.get("Networks"), dict) else {}
        if network_mode not in attached:
            return f"it is not attached to {network_mode}, so it would start with no network"
        if extra := sorted(set(attached) - {network_mode}):
            return f"it is also attached to {', '.join(extra)}, where the fence does not cover it"
        bindings = host.get("PortBindings") if isinstance(host.get("PortBindings"), dict) else {}
        ui = docker_conf.get("ui_port")
        if isinstance(ui, dict) and f"{ui.get('port')}/tcp" not in bindings:
            return f"it does not publish its WebUI port {ui.get('port')}"
        rng = docker_conf.get("udp_port_range")
        if isinstance(rng, dict):
            wanted = _env_port_range(config, str(rng.get("env") or ""))
            if wanted is None and not any(k.endswith("/udp") for k in bindings):
                return "it publishes none of its UDP ports"
            if wanted is not None:
                missing = [p for p in range(wanted[0], wanted[1] + 1) if f"{p}/udp" not in bindings]
                if missing:
                    return (
                        f"it does not publish UDP {missing[0]}"
                        + (f" and {len(missing) - 1} more" if len(missing) > 1 else "")
                        + f" of its range {wanted[0]}:{wanted[1]}"
                    )
    return None


def _env_port_range(config: dict[str, Any], key: str) -> tuple[int, int] | None:
    """The start:end range the container's own env sets in ``key``, or None when it sets none it can read."""
    if not key:
        return None
    for entry in config.get("Env") or []:
        name, _, value = str(entry).partition("=")
        if name == key:
            m = re.fullmatch(r"\s*(\d{1,5}):(\d{1,5})\s*", value)
            if m and int(m[1]) <= int(m[2]) <= 65535:
                return int(m[1]), int(m[2])
            return None
    return None


def _keep_live_mounts(
    old: Any,
    volumes: dict[str, dict[str, str]] | None,
    moved_mounts: list[str] | None = None,
    keep_targets: set[str] | None = None,
) -> tuple[dict[str, dict[str, str]] | list[str] | None, list[dict[str, str]]]:
    """Where a running container keeps its data is a fact; the spec is a guess.

    A deploy that replaces a container mounts, at every target the two have in
    common, what the container has mounted NOW. Otherwise a container whose data
    lives somewhere the spec does not know about — created or edited by hand,
    deployed before specs were recorded, or described by a record that belongs
    to another worker — comes back on the catalog's volume. For mysterium, storj
    and every service that keeps an identity on disk, that is a different node:
    seen live, a redeploy moved a node from its bind-mounted directory onto the
    ``mysterium-data`` volume and it came up with another identity.

    Two limits. A target in ``moved_mounts`` is left to the spec: the operator
    typed a new path for it on this deploy, so the move is what they asked for.
    And when ``keep_targets`` is given, only those targets are kept — the worker
    passes the ones its own catalog declares for the slug, because the kept
    source is not re-checked against the bind-path rules and the spec's targets
    are caller-supplied.

    A target whose host side has no path variable (mysterium's) can never be in
    ``moved_mounts``, so the dashboard cannot move it: that is intended, and the
    way to move such a mount is to recreate the container by hand.

    A mount that was read-only stays read-only. When anything is kept the result
    is a list of ``source:target:mode`` strings rather than a dict keyed by
    source: two targets can share one source (a directory mounted twice, or a
    kept source that equals another requested one), and a dict would silently
    drop one of them — bringing that target up empty, which is the very loss
    this exists to prevent.
    """
    if not volumes:
        return volumes, []
    moved = {_norm_mount(target) for target in moved_mounts or []}
    allowed = None if keep_targets is None else {_norm_mount(target) for target in keep_targets}
    live: dict[str, tuple[str, bool]] = {}
    for mount in (getattr(old, "attrs", None) or {}).get("Mounts") or []:
        source = mount.get("Name") if mount.get("Type") == "volume" else mount.get("Source")
        if source and mount.get("Destination"):
            live[_norm_mount(mount["Destination"])] = (source, mount.get("RW") is False)

    binds: list[str] = []
    kept: list[dict[str, str]] = []
    for host, spec in volumes.items():
        bind = str((spec or {}).get("bind") or "")
        mode = str((spec or {}).get("mode") or "rw")
        target = _norm_mount(bind)
        source, read_only = live.get(target, ("", False))
        keepable = bool(source) and target not in moved and (allowed is None or target in allowed)
        # Same source but read-only now and read-write in the spec is a change
        # too: the replacement could write to data that was protected.
        if keepable and (source != host or (read_only and mode != "ro")):
            binds.append(f"{source}:{bind}:{'ro' if read_only else mode}")
            kept.append(
                {"target": target, "kept": source if source != host else f"{source} (read-only)", "requested": host}
            )
        else:
            binds.append(f"{host}:{bind}:{mode}")
    if not kept:
        return volumes, []
    return binds, kept


def _remove_container(container: Any, slug: str) -> None:
    """Force-remove a container of ``slug``; a custom service's anonymous volumes go with it.

    Only for a custom service (a ``custom-`` slug, which catalog._validate
    refuses for any catalog entry). An image that declares VOLUME and has no
    data path gets a fresh anonymous volume with every container, and nothing
    ever mounts the old one again (_catalog_volume_targets keeps no mount for a
    custom slug), so without ``v`` each redeploy or scale-down leaves one
    behind. Docker's ``v`` removes anonymous volumes only, never a named one,
    so the data path (cashpilot-custom-<name>-data) stays. A catalog service is
    removed exactly as before: its data is never touched here.
    """
    if slug.startswith("custom-"):
        container.remove(force=True, v=True)
    else:
        container.remove(force=True)


def _norm_mount(path: str) -> str:
    """Normalise a container mount path for comparison.

    Only a trailing slash is stripped (root "/" is left alone). Docker reports
    destinations without one, but a hand-written catalog entry might include it,
    and an exact-string mismatch on this comparison fails OPEN on the only
    irreversible operation in the codebase.
    """
    return path.rstrip("/") or "/"


class CriticalVolumeError(Exception):
    """Raised when a delete would destroy state the catalog marks irreplaceable.

    Carries the blocked mounts so the caller can tell the operator exactly what
    would have been lost, rather than just refusing.
    """

    def __init__(self, slug: str, blocked: list[dict[str, str]]) -> None:
        self.slug = slug
        self.blocked = blocked
        targets = ", ".join(b["target"] for b in blocked)
        super().__init__(f"Refusing to delete critical volume(s) for {slug}: {targets}")


def _critical_volume_targets(slug: str) -> dict[str, str] | None:
    """Look up critical mounts, returning None when it cannot be determined.

    The worker image ships the catalog, but a trimmed build might not. Import
    failure is treated as "unknown", which the caller refuses on, so a missing
    catalog can never quietly permit an irreversible delete.
    """
    if critical_volume_targets is None:
        return None
    try:
        return critical_volume_targets(slug)
    except Exception:  # pragma: no cover - defensive
        logger.exception("Could not resolve critical volumes for %s", slug)
        return None


# ---------------------------------------------------------------------------
# Critical volumes stay with their own service
#
# A critical volume (``critical_volumes`` in a service's YAML) holds a wallet or
# a node identity. Any container that mounts it can read it or replace it, so
# the worker lets only that service's own containers mount it, and only on the
# catalog's image unless the owner confirmed another with their password
# (app/step_up.py, checked in app/worker_api.py). Which volumes count comes from
# the YAML, never from a list of names here.
# ---------------------------------------------------------------------------


class CriticalMountError(ContainerRuntimeError):
    """A container would mount another service's critical volume. Always 403."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=403)


def critical_slugs() -> dict[str, set[str]]:
    """slug -> the container paths its YAML marks critical, for every service that marks any."""
    if get_services is None:
        return {}
    found: dict[str, set[str]] = {}
    for svc in get_services():
        entries = (svc.get("docker") or {}).get("critical_volumes") or []
        targets = {_norm_mount(str(e["target"])) for e in entries if isinstance(e, dict) and e.get("target")}
        if targets and svc.get("slug"):
            found[str(svc["slug"])] = targets
    return found


def _catalog_critical_named_volumes(critical: dict[str, set[str]]) -> dict[str, str]:
    """Named volume -> owning slug, from the YAML's own ``volumes`` lines.

    Only literal names count. A ``${VAR}`` source is a host folder the operator
    picks at deploy time; the running container says where it is (see
    critical_sources).
    """
    owners: dict[str, str] = {}
    for svc in get_services() if get_services is not None else []:
        slug = svc.get("slug")
        if slug not in critical:
            continue
        for mapping in (svc.get("docker") or {}).get("volumes") or []:
            parts = str(mapping).split(":")
            if len(parts) < 2 or _norm_mount(parts[1]) not in critical[slug]:
                continue
            source = parts[0]
            if source and not source.startswith(("/", "$", ".", "~")):
                owners[source] = slug
    return owners


def critical_sources(client: Any = None) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Where critical state lives on this host: (named volume -> slugs, host folder -> slugs).

    The catalog's named volumes, plus what each critical service's containers
    have mounted at a critical path right now: a bind-mounted Storj identity, a
    node moved off its catalog volume by hand. A folder or volume is learned
    only while a container of its service exists; one left behind by a removed
    container is no longer known to be critical.

    Every owner of a key is kept: host_path_key folds case, so on a
    case-sensitive host ``/mnt/user/Wallet`` and ``/mnt/user/wallet`` can be two
    services' folders under one key, and keeping only the first would let the
    first service mount the second's.

    Raises DockerException when the containers cannot be listed: the caller
    refuses rather than guess.
    """
    critical = critical_slugs()
    named: dict[str, set[str]] = {name: {slug} for name, slug in _catalog_critical_named_volumes(critical).items()}
    binds: dict[str, set[str]] = {}
    if not critical:
        return named, binds
    client = client or _get_client()
    for container in client.containers.list(all=True, filters={"label": f"{LABEL_MANAGED}=true"}):
        labels = getattr(container, "labels", None)
        slug = labels.get(LABEL_SERVICE) if isinstance(labels, dict) else None
        if slug not in critical:
            continue
        attrs = getattr(container, "attrs", None)
        mounts = attrs.get("Mounts") if isinstance(attrs, dict) else None
        for mount in mounts if isinstance(mounts, list) else []:
            if not isinstance(mount, dict) or _norm_mount(str(mount.get("Destination") or "")) not in critical[slug]:
                continue
            if mount.get("Type") == "volume" and mount.get("Name"):
                named.setdefault(str(mount["Name"]), set()).add(slug)
            elif mount.get("Type") == "bind" and str(mount.get("Source") or "").startswith("/"):
                binds.setdefault(host_path_key(str(mount["Source"])), set()).add(slug)
    return named, binds


def host_path_key(path: str) -> str:
    """One spelling per host folder, for comparing a requested bind with a known folder.

    ``os.path.normpath`` alone keeps exactly two leading slashes on POSIX, so
    ``//mnt/user/node`` would not equal ``/mnt/user/node`` although the kernel
    mounts the same folder. Every leading slash collapses to one, then ``.``,
    ``..`` and trailing slashes go. Case is folded too: a host on a
    case-insensitive filesystem mounts ``/Mnt/User/Node`` as the same folder,
    and on a case-sensitive one the only cost is a refusal of a lookalike name.
    Only for deny checks: folding case would widen an allow list.
    """
    return os.path.normpath("/" + path.lstrip("/")).casefold()


def _mount_sources(volumes: Any) -> list[str]:
    """The host side of each mount, from a spec dict or a ``source:target:mode`` list."""
    if isinstance(volumes, dict):
        return [str(source) for source in volumes]
    if isinstance(volumes, list):
        return [str(entry).split(":", 1)[0] for entry in volumes]
    return []


def critical_mount_conflicts(slug: str, volumes: Any, client: Any = None) -> list[tuple[str, str]]:
    """(source, owning slug) for each mount in ``volumes`` that holds another service's critical state.

    A host folder conflicts when it is a critical folder, lies inside one, or
    contains one: binding a parent hands over everything under it. Folders are
    compared as written, after host_path_key; a symlink to a critical folder is
    not seen here (the worker cannot see the host's filesystem).
    """
    sources = _mount_sources(volumes)
    if not sources:
        return []
    named, binds = critical_sources(client)
    found: list[tuple[str, str]] = []
    for source in sources:
        if not source.startswith("/"):
            others = sorted(named.get(source, set()) - {slug})
            if others:
                found.append((source, others[0]))
            continue
        path = host_path_key(source)
        for folder, owners in binds.items():
            others = sorted(owners - {slug})
            if not others:
                continue
            if path == folder or path.startswith(folder.rstrip("/") + "/") or folder.startswith(path.rstrip("/") + "/"):
                found.append((source, others[0]))
                break
    return found


def refuse_critical_mounts(slug: str, volumes: Any, client: Any = None) -> None:
    """Raise CriticalMountError when ``volumes`` reaches another service's critical state."""
    conflicts = critical_mount_conflicts(slug, volumes, client)
    if conflicts:
        what = ", ".join(f"{source} ({owner})" for source, owner in conflicts)
        raise CriticalMountError(
            f"{slug} cannot mount {what}: it holds another service's wallet or identity, which only that "
            "service may mount. Nothing was deployed; the running container was not touched."
        )


_DEFAULT_REGISTRIES = ("docker.io/", "index.docker.io/", "registry-1.docker.io/")


def _split_image(ref: str) -> tuple[str, str, str]:
    """(repository, tag, digest) of an image reference; tag and digest may be ""."""
    ref = ref.strip()
    digest = ""
    if "@" in ref:
        ref, digest = ref.split("@", 1)
    tag = ""
    slash = ref.rfind("/")
    colon = ref.rfind(":")
    if colon > slash:
        ref, tag = ref[:colon], ref[colon + 1 :]
    repo = ref.lower()
    for prefix in _DEFAULT_REGISTRIES:
        if repo.startswith(prefix):
            repo = repo[len(prefix) :]
            break
    repo = repo.removeprefix("library/")
    return repo, tag, digest.lower()


def catalog_image_matches(slug: str, image: str) -> bool:
    """Whether ``image`` is the image this worker's catalog runs ``slug`` on.

    Same repository, and the same tag and digest wherever the catalog pins one:
    an untagged catalog image (``storjlabs/storagenode``) accepts any tag of that
    repository, a pinned one only itself. Any build in ``image_by_arch`` counts.
    """
    docker_conf = ((get_service(slug) if get_service is not None else None) or {}).get("docker") or {}
    candidates = [docker_conf.get("image")] + list((docker_conf.get("image_by_arch") or {}).values())
    repo, tag, digest = _split_image(str(image or ""))
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        c_repo, c_tag, c_digest = _split_image(candidate)
        if repo == c_repo and (not c_tag or tag == c_tag) and (not c_digest or digest == c_digest):
            return True
    return False


def _catalog_command_tokens(template: str, env: dict[str, Any]) -> list[str]:
    """The arguments the catalog's command becomes once its ``${VAR}`` are filled from ``env``.

    Split first, filled second: a value is one argument whatever it holds, so a
    value with a space in it ("1000:2000 --tequilapi.address=0.0.0.0") cannot
    add arguments of its own. Docker splits the string the UI sends with shlex
    too (docker-py's split_command), so a spec that carries such a value no
    longer splits into these arguments and is refused.
    """
    return [
        re.sub(r"\$\{(\w+)\}", lambda m: str(env.get(m.group(1), m.group(0))), token) for token in shlex.split(template)
    ]


def critical_spec_deviations(
    slug: str, image: str, command: str | None, env: dict[str, Any] | None, volumes: Any
) -> list[str]:
    """How a deploy of ``slug`` differs from what this worker's catalog runs; [] when it does not.

    Only for a service with critical volumes: whatever runs in its container can
    read or replace its wallet or identity. So the image, the command, the env
    keys and the mount targets must be the catalog's, or the owner must have
    confirmed the difference with their password (app/step_up.py). Each of
    these alone is enough to take the wallet with the catalog's own image: a
    shell as the command, ``LD_PRELOAD`` or an import variable in the env, a
    volume of the caller's mounted over the image's binaries. Env values are
    the operator's settings and are not compared, except where they land on the
    command line (see _catalog_command_tokens).
    """
    docker_conf = ((get_service(slug) if get_service is not None else None) or {}).get("docker") or {}
    found: list[str] = []
    if not catalog_image_matches(slug, image):
        pinned = str(docker_conf.get("image") or "")
        if _split_image(pinned)[0] == _split_image(str(image or ""))[0]:
            found.append(
                f"the image {image} is not the {pinned} this worker's catalog pins. If the UI was updated and "
                "this worker was not, update the worker"
            )
        else:
            found.append(f"the image {image} is not the catalog's")
    template = str(docker_conf.get("command") or "")
    try:
        expected = _catalog_command_tokens(template, env or {}) if template else []
        sent = shlex.split(command) if command else []
    except ValueError:
        expected, sent = [], ["<unparseable>"]
    if sent != expected:
        found.append("the command is not the catalog's")
    declared = {str(var.get("key")) for var in docker_conf.get("env") or [] if isinstance(var, dict)}
    if extra := sorted(set(env or {}) - declared):
        found.append(f"the env sets {', '.join(extra)}, which the catalog does not declare")
    targets = {_norm_mount(str(m).split(":")[1]) for m in docker_conf.get("volumes") or [] if ":" in str(m)}
    mounted = (
        [str((m or {}).get("bind") or "") for m in volumes.values()]
        if isinstance(volumes, dict)
        else [str(entry).split(":")[1] if ":" in str(entry) else "" for entry in volumes or []]
    )
    if strange := sorted({_norm_mount(t) for t in mounted} - targets):
        found.append(f"it mounts {', '.join(strange)}, which the catalog does not")
    return found


#: The largest state ``read_critical_state`` will hold in memory. Node identities,
#: keystores and wallets are kilobytes to a few megabytes; anything near this is a
#: storage directory, which is not something to carry in one HTTP response. The
#: bundle is held several times over on its way out (chunks, payload, ciphertext,
#: base64, JSON), so the peak is a multiple of this.
MAX_BACKUP_BYTES = 64 * 1024 * 1024


def state_id(container: Any, targets: dict[str, str] | list[str] | None, client: Any = None) -> str | None:
    """A short fingerprint of WHERE a service's irreplaceable state lives.

    Built from each critical mount's type and source, plus a named volume's
    creation time (the replaced volume's, for one the owner migration moved). It changes when the state can have changed under the user:
    the volume was removed and made again (same name, new creation time), the
    service now points at another volume or host path, or the state sits in the
    container's own layer and the container was replaced. It does NOT change
    when a container is recreated over the same volume, which every image
    update does, so a confirmed backup survives updates.

    Never reads the files: the fingerprint is metadata only, cheap enough for
    every heartbeat and free of key material. A change made inside the same
    volume (a new identity generated in place) is not seen; the UI's time limit
    covers that. None when the service declares nothing critical.
    """
    if not targets:
        return None
    mounts = {
        str(m.get("Destination") or "").rstrip("/"): m
        for m in ((getattr(container, "attrs", None) or {}).get("Mounts") or [])
        if isinstance(m, dict)
    }
    parts: list[str] = []
    for target in sorted(str(t).rstrip("/") for t in targets):
        mount = mounts.get(target)
        if mount is None:
            # Not mounted: the state lives in the container itself and dies
            # with it, so the container IS its identity.
            parts.append(f"{target}|container|{getattr(container, 'id', '')}")
            continue
        kind = str(mount.get("Type") or "")
        if kind == "volume":
            name = str(mount.get("Name") or "")
            created = ""
            try:
                attrs = (client or _get_client()).volumes.get(name).attrs or {}
                # The owner migration copies a volume's data onto a new one of the
                # same name and keeps the old creation time in this label.
                created = str((attrs.get("Labels") or {}).get(LABEL_STATE_CREATED) or attrs.get("CreatedAt") or "")
            except Exception as exc:  # noqa: BLE001 - unknown, not a change
                logger.debug("Could not read volume %s for the state fingerprint: %s", name, exc)
                return None
            parts.append(f"{target}|volume|{name}|{created}")
        else:
            parts.append(f"{target}|{kind}|{mount.get('Source') or ''}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def _state_id_entry(container: Any, slug: str, client: Any) -> dict[str, str]:
    """``{"state_id": ...}`` for a service with critical volumes, else nothing."""
    if critical_volume_targets is None:
        return {}
    try:
        targets = critical_volume_targets(slug)
    except Exception:  # noqa: BLE001 - pragma: no cover - defensive
        return {}
    found = state_id(container, targets, client) if targets else None
    return {"state_id": found} if found else {}


def critical_state_id(slug: str) -> str | None:
    """The state fingerprint of ``slug``'s running copy on this worker."""
    return state_id(_find_container(slug), _critical_volume_targets(slug))


def read_critical_state(slug: str) -> tuple[bytes, list[str]]:
    """Read a service's irreplaceable state as a deterministic tar archive.

    Returns ``(tar_bytes, targets)``. Only the mounts the catalog marks
    ``critical_volumes`` are read — never the whole container. That list is the
    same inventory the delete guard refuses on, so "what is irreplaceable" has
    one definition rather than two that can drift apart.

    The container is PAUSED for the duration when it is running. A keystore or
    sqlite file copied while it is being written produces a backup that opens
    perfectly and restores a corrupt node — the worst possible outcome, because
    it fails only when it is finally needed. Pause is used rather than stop so a
    node does not lose its uptime score for a backup.
    """
    targets = _critical_volume_targets(slug)
    if not targets:
        raise ValueError(
            f"{slug} declares no critical_volumes, so there is no irreplaceable state to export. "
            "Adding a backup for a service whose state is re-downloadable would teach a false habit."
        )

    container = _find_container(slug)
    was_running = container.status == "running"
    chunks: list[bytes] = []
    read: list[str] = []
    size = 0

    if was_running:
        container.pause()
    read_failure: BaseException | None = None
    try:
        for target in sorted(targets):
            stream, _stat = container.get_archive(target)
            try:
                for chunk in stream:
                    size += len(chunk)
                    if size > MAX_BACKUP_BYTES:
                        # Storj and Sia mark their whole storage directory critical.
                        # Reading terabytes into memory, with the node paused, would
                        # take the worker and the node down for nothing.
                        raise ValueError(
                            f"{slug}'s state is larger than {MAX_BACKUP_BYTES // (1024 * 1024)} MB, too big to "
                            f"export here. That is a data folder, not an identity: Storj and Sia keep their "
                            f"whole storage folder there. Back up {target} at the disk level with your own "
                            "tools, then use I have a backup."
                        )
                    chunks.append(chunk)
            finally:
                # Close it before the unpause below. An archive stream left open
                # (the raise above keeps it alive through the traceback) holds the
                # container, so Docker never answers the unpause: the earner stays
                # PAUSED and earns nothing. Proven on Docker 29.5: unpause timed
                # out with the stream open, returned at once once it was closed.
                close = getattr(stream, "close", None)
                if callable(close):
                    close()
            read.append(target)
    except BaseException as exc:
        read_failure = exc
        raise
    finally:
        if was_running:
            # Unpause even if the read failed: leaving a paused earner behind
            # would silently stop the income this feature exists to protect.
            try:
                container.unpause()
            except Exception as exc:
                # Never silent. A paused container renders normally and earns
                # nothing, and nothing else in the system reports that state,
                # so an unlogged failure here is an invisible revenue stop.
                logger.error(
                    "CRITICAL: %s is still PAUSED — unpause failed (%s). It is earning "
                    "NOTHING until it is unpaused by hand: docker unpause %s",
                    slug,
                    exc,
                    container.name,
                )
                # Only swallow this while a read error is already on its way
                # up, where re-raising would replace the real cause with a
                # downstream symptom. When the read SUCCEEDED, staying quiet is
                # worse than losing the archive: the caller would hand back a
                # perfectly good backup, verification would report success, and
                # the container would sit paused indefinitely with nothing
                # anywhere contradicting the green result. The backup can be
                # taken again; an unnoticed paused earner just stops paying.
                if read_failure is None:
                    raise

    return b"".join(chunks), read


# ---------------------------------------------------------------------------
# Restore from the dashboard (issue #741)
#
# Only into nothing: a new container on a new volume, written before the
# container ever runs, read back and compared, then started. Never over a live
# identity, and nothing half-restored is left behind. The bundle is opened and
# its archives checked by the caller (worker_api), outside any lock.
#
# The write goes through a helper container that is created and never
# started: it mounts the fresh volume at the one folder the socket proxy lets
# the worker write into (RESTORE_WRITE_DIR, the tunnel sidecar's folder), so a
# restore needs no wider proxy rule. A compromised worker gains nothing it did
# not have: it could already create a container on any volume it owns.
# ---------------------------------------------------------------------------

#: Where the helper mounts the volume being restored. The socket proxy allows
#: archive writes into this folder only (app/socket_policy.py container_archive).
RESTORE_WRITE_DIR = "/run/cashpilot-secret"
#: Suffix of the helper's name. A dot, so no service's container name can match.
RESTORE_HELPER_SUFFIX = ".restore"
#: One restore at a time on this worker. Held, a helper found under its name
#: was left by a worker that died mid-restore, so it is removed, not refused.
_RESTORE_LOCK = threading.Lock()


class RestoreError(ContainerRuntimeError):
    """A restore that was refused or undone. The message is safe to show and names no secret."""

    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message, status_code=status_code)


def restore_targets(slug: str) -> dict[str, str] | None:
    """critical target -> named volume for ``slug`` from this worker's catalog, or None.

    None when the service keeps its state anywhere a restore cannot create new
    (a host folder: Storj, Sia) or declares nothing critical.
    """
    svc = (get_service(slug) if get_service is not None else None) or {}
    from app import state_backup

    return state_backup.restore_volumes(svc.get("docker") or {})


def _restore_refusal(client: Any, slug: str, name: str, volumes: dict[str, str]) -> str | None:
    """Why ``slug`` cannot be restored on this box now, or None.

    Any container of the service (any copy, any state, a moved-aside one) or
    of its name refuses, and so does any of its critical volumes existing at
    all: a restore never writes over something that is there. A volume the
    proxy will not show counts as there.
    """
    labelled = client.containers.list(all=True, filters={"label": f"{LABEL_SERVICE}={slug}"})
    if labelled:
        return (
            f"{slug} already has a container on this box ({labelled[0].name}). A restore only creates a new one: "
            "back the running one up, remove it with its data from the dashboard, then restore"
        )
    for candidate in (name, name + REPLACED_SUFFIX, name + RESTORE_HELPER_SUFFIX):
        try:
            found = client.containers.get(candidate)
        except NotFound:
            continue
        labels = found.labels if isinstance(getattr(found, "labels", None), dict) else {}
        if candidate.endswith(RESTORE_HELPER_SUFFIX) and labels.get(LABEL_RESTORE) == "helper":
            # Never started, and no restore runs (_RESTORE_LOCK): a dead worker's leftover.
            try:
                found.remove(force=True)
            except NotFound:
                pass
            except Exception as exc:  # noqa: BLE001 - said to the owner
                return f"{candidate}, left by a restore that did not finish, could not be removed ({exc})"
            logger.warning("Removed %s, left by a restore that did not finish", candidate)
            continue
        return f"a container named {candidate} already exists on this box"
    for volume in volumes.values():
        try:
            client.volumes.get(volume)
        except NotFound:
            continue
        except APIError as exc:
            return f"the volume {volume} could not be checked ({proxy_refusal(exc) or exc}), so it counts as there"
        return (
            f"the volume {volume} already exists on this box. A restore never writes into an existing volume: "
            "if it holds nothing you need, remove it, then restore"
        )
    return None


def _restore_helper(slug: str) -> Any | None:
    """The helper container a restore of ``slug`` left behind, or None.

    It exists only while a restore writes, so outside one it means the worker
    died mid-write: the volume may be half-written.
    """
    try:
        found = _get_client().containers.get(_container_name(slug) + RESTORE_HELPER_SUFFIX)
    except NotFound:
        return None
    labels = found.labels if isinstance(getattr(found, "labels", None), dict) else {}
    return found if labels.get(LABEL_RESTORE) == "helper" else None


def _refuse_mid_restore(slug: str, what: str) -> None:
    """Raise unless ``slug`` may start: no restore of it runs, and none left a half-written volume.

    A fence-gated service is also held by its failed mark on disk; this covers
    the others (ProxyBase, Anyone), which nothing else marks.
    """
    with _SLUG_WORK_LOCK:
        running = slug in _restoring
    if running:
        raise ContainerRuntimeError(
            f"A restore of {slug} is running on this box, so it was not {what}. Try again when it ends.", 409
        )
    if _restore_helper(slug) is not None:
        raise ContainerRuntimeError(
            f"A restore of {slug} did not finish, so its data may be half-written and it was not {what}. "
            "Remove the service with its data, then restore the backup again.",
            409,
        )


def _create_restore_volume(client: Any, volume: str) -> None:
    """Create ``volume`` new, or raise RestoreError when Docker handed back one that was there."""
    nonce = secrets.token_hex(16)
    created = client.volumes.create(name=volume, labels={LABEL_RESTORE: nonce})
    labels = (getattr(created, "attrs", None) or {}).get("Labels") or {}
    if labels.get(LABEL_RESTORE) != nonce:
        # Docker returns the existing volume for a name that exists. One the
        # proxy hid from the check above is still somebody's data.
        raise RestoreError(f"the volume {volume} already existed (it was hidden from this worker), so it was not used")


def _restore_cleanup(client: Any, containers: list[Any], created_volumes: list[str]) -> list[str]:
    """Remove the containers and the volumes this restore made. Returns what could not be removed.

    Only ``containers``, the objects this restore created, never a container
    found by name: one under that name it did not make is another deploy's.
    A volume Docker refuses as in use, while every container of ours is
    gone, is that deploy's now and is kept.
    """
    left: list[str] = []
    # The helper first (made last): it holds the volumes too.
    for container in reversed(containers):
        try:
            container.remove(force=True)
        except NotFound:
            pass
        except Exception as exc:  # noqa: BLE001 - keep going: the volumes must go too
            logger.error("Restore cleanup could not remove %s: %s", container.name, exc)
            left.append(container.name)
    for volume in created_volumes:
        try:
            client.volumes.get(volume).remove(force=True)
        except NotFound:
            pass
        except APIError as exc:
            if exc.status_code == 409 and not left:
                logger.warning("Restore cleanup kept the volume %s: another container uses it now", volume)
                continue
            logger.error("Restore cleanup could not remove the volume %s: %s", volume, exc)
            left.append(volume)
        except Exception as exc:  # noqa: BLE001
            logger.error("Restore cleanup could not remove the volume %s: %s", volume, exc)
            left.append(volume)
    return left


def _read_back(container: Any, target: str) -> bytes:
    """Docker's archive of ``target`` in the created container, capped like an export."""
    stream, _stat = container.get_archive(target)
    chunks: list[bytes] = []
    size = 0
    try:
        for chunk in stream:
            size += len(chunk)
            if size > MAX_BACKUP_BYTES:
                raise RestoreError(f"{target} reads back larger than a backup can be, so it is not the backup")
            chunks.append(chunk)
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()
    return b"".join(chunks)


def _write_through_helper(client: Any, container: Any, volume: str, payload: bytes, made: list[Any]) -> None:
    """Write ``payload`` into ``volume`` through a helper that is created and never started.

    The helper runs the restored container's own image (already here, so no
    pull), with no network, no capabilities and nothing to run: Docker writes
    into a created container's mounts without starting it, as the tunnel
    sidecar's settings are written. It is removed as soon as the write returns;
    the volume stays, mounted by the restored container. Until then it is in
    ``made``, so a failed removal is retried by the cleanup.
    """
    from docker.types import Mount

    helper = client.containers.create(
        image=(getattr(container, "attrs", None) or {}).get("Image") or container.image.id,
        name=container.name + RESTORE_HELPER_SUFFIX,
        command=["true"],
        network_mode="none",
        mounts=[Mount(RESTORE_WRITE_DIR, volume, type="volume")],
        labels={LABEL_RESTORE: "helper"},
        cap_drop=["ALL"],
        security_opt=["no-new-privileges:true"],
    )
    made.append(helper)
    try:
        if not helper.put_archive(RESTORE_WRITE_DIR, payload):
            raise RestoreError(f"Docker did not write the volume {volume}")
    finally:
        helper.remove(force=True)
        made.remove(helper)


def restore_state(slug: str, archives: dict[str, bytes], deploy: dict[str, Any]) -> dict[str, Any]:
    """Create ``slug`` from ``deploy`` with ``archives`` in its critical volumes, then start it.

    ``archives`` is split_archives' output, keyed by each critical folder's
    last path component, and must name exactly this worker's catalog targets.
    ``deploy`` is deploy_raw's keyword arguments, already validated by the
    worker API like any deploy. In order: refuse unless nothing of the service
    is here; create its critical volumes new; create the container without
    starting it (deploy_raw, so every deploy check applies); write each archive
    into its volume through a helper that never starts (_write_through_helper);
    read each folder back from the restored container and compare every file,
    link, owner and permission with the backup; start. Any failure removes the container
    and every volume this call made. A fence-gated service holds
    GATED_DEPLOY_LOCK throughout, and is marked failed on disk before it is
    created until its data reads back right, so the guard never starts it
    half-written: not while this runs, nor after a worker that died midway.
    """
    from app import state_backup

    targets = restore_targets(slug)
    if not targets:
        raise RestoreError(
            f"{slug} keeps its state in a host folder, or keeps none, so it cannot be restored from the dashboard. "
            "Use the command line steps in the backup guide."
        )
    by_folder = {target.rstrip("/").rsplit("/", 1)[-1]: target for target in targets}
    if len(by_folder) != len(targets) or set(archives) != set(by_folder):
        want = ", ".join(sorted(by_folder))
        have = ", ".join(sorted(archives)) or "nothing"
        raise RestoreError(f"this backup holds {have}, but {slug} keeps {want}. It is not a backup of {slug}.", 400)
    expected = {by_folder[f]: state_backup.tree_manifest(data) for f, data in archives.items()}
    payloads = {by_folder[f]: state_backup.relative_archive(data) for f, data in archives.items()}

    gated = fence_gated(slug)
    lock = GATED_DEPLOY_LOCK if gated else contextlib.nullcontext()
    client = _get_client()
    name = _container_name(slug)
    if not _RESTORE_LOCK.acquire(blocking=False):
        raise RestoreError("Nothing was restored: another restore is running on this box. Try again when it ends.")
    try:
        with _SLUG_WORK_LOCK:
            if _deploying.get(slug):
                raise RestoreError(
                    f"Nothing was restored: a deploy of {slug} is running on this box. Try again when it ends."
                )
            _restoring.add(slug)
        try:
            with lock:
                return _restore_locked(client, slug, name, gated, targets, expected, payloads, deploy)
        finally:
            with _SLUG_WORK_LOCK:
                _restoring.discard(slug)
    finally:
        _RESTORE_LOCK.release()


def _restore_locked(
    client: Any,
    slug: str,
    name: str,
    gated: bool,
    targets: dict[str, str],
    expected: dict[str, Any],
    payloads: dict[str, bytes],
    deploy: dict[str, Any],
) -> dict[str, Any]:
    """restore_state's steps, under its locks."""
    from app import state_backup

    if why := _restore_refusal(client, slug, name, targets):
        raise RestoreError(f"Nothing was restored: {why}.")
    before = set(_named_volumes(deploy.get("volumes")))
    made: list[str] = []
    containers: list[Any] = []
    failed_before = name in deploy_failed()
    files = 0
    try:
        if gated:
            # On disk before the container exists: a worker that dies before the
            # read-back leaves a node the guard never starts (lan_fence.guard).
            _mark_failed(name, True)
            if name not in _failed_on_disk():
                raise RestoreError(f"the worker could not record that {name} is not ready yet, so nothing was made")
        for volume in targets.values():
            _create_restore_volume(client, volume)
            made.append(volume)
        # The other volumes the service mounts (Anyone's config) are made
        # by deploy_raw if missing; those it makes are removed on failure too.
        existing = {v for v in before - set(made) if _volume_exists(client, v)}
        made.extend(sorted(before - set(made) - existing))
        container = client.containers.get(deploy_raw.__wrapped__(slug=slug, **deploy, start=False))
        containers.append(container)
        if getattr(container, "status", "created") != "created":
            raise RestoreError(f"{name} is {container.status}, not newly created, so it was not written to")
        for target, payload in sorted(payloads.items()):
            _write_through_helper(client, container, targets[target], payload, containers)
        for target in sorted(targets):
            found = state_backup.tree_manifest(_read_back(container, target))
            diff = state_backup.manifest_differences(expected[target], found)
            if diff:
                shown = "; ".join(diff[:5]) + (f"; and {len(diff) - 5} more" if len(diff) > 5 else "")
                raise RestoreError(f"{target} does not read back as the backup: {shown}")
            files += sum(1 for entry in found.values() if entry[0] == "file")
        container.reload()
        if container.status != "created":
            raise RestoreError(f"{name} started before the restore finished, so it was undone")
        started = _start_restored(slug, container)
    except BaseException as exc:
        left = _restore_cleanup(client, containers, made)
        if gated:
            # Any container left under the name stays held (ours that could not
            # be removed, or one deploy_raw's roll-back left): the guard never
            # starts unchecked data. A free name gets its mark back as it was.
            _mark_failed(name, failed_before or _name_taken(client, name))
        note = f" Could not remove {', '.join(left)}: remove it by hand." if left else ""
        if isinstance(exc, RestoreError):
            raise RestoreError(f"{exc}. The container and volumes it made were removed.{note}", exc.status_code)
        if isinstance(exc, ContainerRuntimeError):
            raise RestoreError(f"{exc} The restore was undone.{note}", exc.status_code) from None
        if isinstance(exc, APIError):
            why = proxy_refusal(exc) or " ".join(str(exc.explanation or exc).split())[:300]
            raise RestoreError(f"Docker refused the restore: {why}. It was undone.{note}") from None
        if isinstance(exc, Exception):
            logger.exception("Restore of %s failed", slug)
            raise RestoreError(f"The restore failed and was undone.{note}", 500) from None
        raise
    logger.info("Restored %s from a backup: %d files in %s", slug, files, ", ".join(sorted(targets)))
    return {
        "container_id": container.id,
        "targets": sorted(targets),
        "files": files,
        "started": started,
        # The new volume's fingerprint: the UI links an export from it later to this backup's node.
        "state_id": state_id(container, targets, client),
    }


def _name_taken(client: Any, name: str) -> bool:
    """Whether a container holds ``name``; not known counts as taken."""
    try:
        client.containers.get(name)
    except NotFound:
        return False
    except Exception:  # noqa: BLE001
        return True
    return True


def _volume_exists(client: Any, volume: str) -> bool:
    try:
        client.volumes.get(volume)
    except NotFound:
        return False
    except APIError:
        return True
    return True


def _start_restored(slug: str, container: Any) -> bool:
    """Start the restored container. False when a fence-gated one waits for its fence.

    A fence-gated node starts only behind a confirmed fence, as on a deploy;
    left created, the guard starts it once the fence holds. Its data is already
    checked, so waiting is safe.
    """
    if fence_gated(slug):
        # The data just read back as the backup: an identity record or hold
        # from the node this replaces (a MISMATCH the owner fixed by removing
        # it and restoring) no longer applies, and would stop it at once.
        _remember_identity(container.name, None)
        _mark_stopped(container.name, False)
        # Last: from here the guard may start it once the fence holds.
        _mark_failed(container.name, False)
        try:
            _require_fence(slug)
        except ContainerNetworkError as exc:
            logger.info("Restored %s waits for the LAN fence: %s", slug, exc)
            return False
    container.start()
    return True


def remove_instance(slug: str, instance: int) -> dict[str, Any]:
    """Remove one extra copy of a service (scaling down). Never the first.

    Extra copies are refused for services with volumes (see the deploy route),
    so there is no data to keep or delete here: the container goes, nothing else.
    """
    if instance <= 1:
        raise ValueError("The first instance is removed with the service, not on its own")
    container = _find_container(slug, instance)
    # Read before it goes: the UI keeps the ids this copy ran with (identity ledger).
    identity = _identity_entry(container, slug)
    try:
        container.stop(timeout=_get_stop_timeout(slug))
    except APIError as exc:
        logger.warning("Could not stop %s cleanly before removing it: %s", container.name, exc)
    _remove_container(container, slug)
    logger.info("Removed container %s", container.name)
    return {"container": container.name, **identity}


def remove_extra_instances(slug: str) -> list[str]:
    """Remove every copy of ``slug`` after the first; returns their names.

    Called when a service is removed from a worker, or the extra copies would
    keep running unmanaged once the UI forgets the deployment.
    """
    removed: list[str] = []
    for extra in service_instances(slug):
        if _instance_of(extra) > 1:
            # Not _remove_container: this is whole-service removal, where the
            # operator decides about data, and the first copy keeps its volumes.
            extra.remove(force=True)
            logger.info("Removed container %s", extra.name)
            removed.append(extra.name)
    return removed


def remove_service(slug: str, delete_volumes: bool = False, allow_delete_critical: bool = False) -> dict[str, Any]:
    """Stop and remove the container for a service.

    When delete_volumes is True, also remove named volumes that were
    mounted into the container. Bind mounts and anonymous volumes are skipped.

    Volumes the catalog marks as critical are refused unless
    ``allow_delete_critical`` is set. This is the only irreversible path in the
    codebase: the data behind these mounts — node identities, keystores,
    generated wallets — has no server-side copy and no backup, so a mistake here
    cannot be undone by redeploying.
    """
    with _SLUG_WORK_LOCK:
        if slug in _restoring:
            raise ContainerRuntimeError(
                f"A restore of {slug} is running on this box, so nothing was removed. Try again when it ends.", 409
            )
    container = _find_container(slug)
    name = container.name

    volume_names: list[str] = []
    if delete_volumes:
        raw_critical = _critical_volume_targets(slug)
        # Normalise a trailing slash on both sides: a catalog entry written as
        # "/app/identity/" must still match Docker's "/app/identity", or the
        # guard silently fails open on the only irreversible path there is.
        critical = None if raw_critical is None else {_norm_mount(k): v for k, v in raw_critical.items()}
        blocked: list[dict[str, str]] = []
        for m in container.attrs.get("Mounts", []) or []:
            if m.get("Type") == "volume" and m.get("Name"):
                volume_names.append(m["Name"])
                destination = _norm_mount(m.get("Destination") or "")
                if critical is None:
                    # Criticality could not be determined. Refuse rather than
                    # guess: an unknown slug or a catalog-less build must not
                    # silently unlock an irreversible delete.
                    blocked.append(
                        {
                            "volume": m["Name"],
                            "target": destination,
                            "holds": (
                                f"Cannot determine whether this volume is critical: {slug!r} "
                                "is not in the catalog on this worker. Refusing to delete "
                                "something that might be irreplaceable."
                            ),
                        }
                    )
                elif destination in critical:
                    blocked.append(
                        {
                            "volume": m["Name"],
                            "target": destination,
                            "holds": critical[destination],
                        }
                    )

        # Check BEFORE removing the container: refusing after that point would
        # already have destroyed something.
        if blocked and not allow_delete_critical:
            raise CriticalVolumeError(slug, blocked)

    container.remove(force=True)
    logger.info("Removed container %s", name)
    # A restore that died midway left its helper, which mounts the volume, so
    # the volume could not go and the next restore would refuse it.
    try:
        helper = _restore_helper(slug)
        if helper is not None:
            helper.remove(force=True)
            logger.info("Removed %s, left by a restore that did not finish", helper.name)
    except Exception as exc:  # noqa: BLE001 - its volume then shows as not deleted
        logger.warning("Could not remove the helper a restore of %s left: %s", slug, exc)

    deleted_volumes: list[str] = []
    failed_volumes: list[str] = []
    if volume_names:
        client = _get_client()
        for vol_name in volume_names:
            try:
                client.volumes.get(vol_name).remove(force=True)
                deleted_volumes.append(vol_name)
                logger.info("Removed volume %s", vol_name)
            except NotFound:
                deleted_volumes.append(vol_name)
            except APIError as exc:
                failed_volumes.append(vol_name)
                logger.warning("Failed to remove volume %s: %s", vol_name, exc)

    return {
        "container": name,
        "deleted_volumes": deleted_volumes,
        "failed_volumes": failed_volumes,
    }


def start_service(slug: str, instance: int = 1) -> None:
    """Start a stopped container for a service."""
    _refuse_mid_restore(slug, "started")
    container = _find_container(slug, instance)
    if _gated_container(slug, container):
        _require_startable(container, slug)
        _mark_stopped(container.name, False)
    container.start()
    logger.info("Started container %s", container.name)


# ---------------------------------------------------------------------------
# Self-update (issue #342)
#
# The documented install pins a MAJOR.MINOR image series with pull_policy:
# always, and docker-compose.yml itself names `docker compose pull && docker
# compose up -d` as the update path. The update button runs exactly that — from
# a transient helper container, because the worker cannot recreate itself from
# inside the process being recreated.
#
# Nothing here is caller-controlled: the compose project location comes from
# the labels Compose put on the worker's OWN container, the helper image is
# pinned, and the command is fixed. An install that pins an exact tag (GitOps
# fleets) gets a no-op pull by construction; an install not managed by Compose
# is refused with instructions instead of guessing.
#
# The helper sees the compose files and the project's .env, never the shell the
# operator deployed from. So before anything is pulled, a socketless `docker
# compose config` run resolves the file the way the helper will, and the update
# is refused if that would publish a CashPilot container on different host
# ports than it has now (a CASHPILOT_UI_PORT or CASHPILOT_BIND_ADDR given on the
# command line): recreating it there could move the dashboard off the address
# the operator uses, or onto a port another service already holds.
# ---------------------------------------------------------------------------

#: Pinned helper image (ships the compose plugin — verified v2.33.0). Never :latest.
#: Pinned by digest too: it runs with the host's raw Docker socket, which is
#: root on the host, so it must be the bytes we reviewed and not whatever the
#: tag points to on the day of the update. Bump both parts on purpose.
UPDATER_IMAGE = "docker:27.5.1-cli@sha256:851f91d241214e7c6db86513b270d58776379aacc5eb9c4a87e5b47115e3065c"
#: Fixed helper name: doubles as the only-one-update-at-a-time lock.
UPDATER_NAME = "cashpilot-updater"


def _updater_script(services: list[str]) -> str:
    """The helper's fixed script, scoped to the named compose services.

    Two guards precede the documented pull/up:
    - `docker compose config` must succeed — a file the resolver rejects must
      never drive a recreation.
    - Unset ``${VAR}`` substitutions abort. The helper does not inherit the
      shell environment the operator originally deployed with, so a variable
      that resolved to a bind path then would resolve to EMPTY now — recreating
      onto broken mounts. (The documented compose file only uses ``:-`` defaults
      and is immune; this protects customized files.)

    And the pull/up is scoped to the CashPilot services by name — a user's
    compose project may hold other services, and recreating those is exactly
    the bulk-redeploy the catalog rules forbid.
    """
    import shlex as _shlex

    scoped = " ".join(_shlex.quote(s) for s in services)
    return (
        "if ! w=$(docker compose config 2>&1 >/dev/null); then "
        'echo "refusing to update: docker compose rejected the configuration:"; echo "$w"; exit 1; fi; '
        'if [ -n "$w" ] && echo "$w" | grep -qi "is not set"; then '
        'echo "refusing to update: the compose file references variables that are not set here:"; echo "$w"; exit 1; fi; '
        f"docker compose pull {scoped} && docker compose up -d --no-deps {scoped}"
    )


class SelfUpdateUnavailable(RuntimeError):
    """This install cannot be updated by the helper; the message says what to do."""


#: Seconds the socketless `docker compose config` preflight may take.
_PREFLIGHT_TIMEOUT = 60

_MANUAL_UPDATE = "docker compose pull && docker compose up -d"

# One published port: (host_ip, published, target, protocol). An empty host IP
# and 0.0.0.0 both mean "all interfaces"; an empty published port means Docker
# picks one.
_Binding = tuple[str, str, int, str]


def _norm_host_ip(ip: Any) -> str:
    ip = str(ip or "").strip().strip("[]")
    return ip or "0.0.0.0"


def _norm_published(port: Any) -> str:
    port = str(port or "").strip()
    return "" if port == "0" else port


def _published_from_config(cfg: dict[str, Any], service: str) -> set[_Binding] | None:
    """The bindings `docker compose config --format json` gives a service, or
    None when the service is not in the resolved file at all."""
    svc = (cfg.get("services") or {}).get(service)
    if not isinstance(svc, dict):
        return None
    out: set[_Binding] = set()
    for p in svc.get("ports") or []:
        if not isinstance(p, dict):
            continue
        out.add(
            (
                _norm_host_ip(p.get("host_ip")),
                _norm_published(p.get("published")),
                int(p.get("target") or 0),
                str(p.get("protocol") or "tcp").lower(),
            )
        )
    return out


def _published_from_container(attrs: dict[str, Any]) -> set[_Binding]:
    """The bindings a live container was created with.

    Read from HostConfig.PortBindings (what was asked for), not
    NetworkSettings.Ports, which reports a 0.0.0.0 binding twice (IPv4 and ::).
    """
    bindings = ((attrs.get("HostConfig") or {}).get("PortBindings")) or {}
    out: set[_Binding] = set()
    for key, hosts in bindings.items():
        port, _, proto = str(key).partition("/")
        for h in hosts or [{}]:
            h = h or {}
            out.add(
                (
                    _norm_host_ip(h.get("HostIp")),
                    _norm_published(h.get("HostPort")),
                    int(port),
                    (proto or "tcp").lower(),
                )
            )
    return out


def _describe(bindings: set[_Binding]) -> str:
    if not bindings:
        return "no host port"
    return ", ".join(
        f"{ip if ':' not in ip else f'[{ip}]'}:{pub or '(random)'}->{target}/{proto}"
        for ip, pub, target, proto in sorted(bindings)
    )


def _port_drift(pairs: list[tuple[str, set[_Binding]]], cfg: dict[str, Any]) -> list[str]:
    """One line per service whose resolved ports differ from its live ones."""
    lines: list[str] = []
    for service, live in pairs:
        wanted = _published_from_config(cfg, service)
        if wanted is None:
            lines.append(f"{service} is missing from your compose file as the update reads it")
        elif wanted != live:
            lines.append(
                f"{service} is published on {_describe(live)}, but your compose file as the "
                f"update reads it would publish {_describe(wanted)}"
            )
    return lines


def _self_container(client: docker.DockerClient):
    """The worker's own container, or None outside Docker.

    The container hostname defaults to the short container id (the documented
    compose file sets container_name, not hostname), so gethostname() resolves
    directly; the documented container name is the fallback for installs that
    do set a hostname.
    """
    import socket as _socket

    for candidate in (_socket.gethostname(), "cashpilot-worker"):
        try:
            return client.containers.get(candidate)
        except (NotFound, APIError):
            continue
    return None


def _compose_project(container: Any) -> dict[str, str]:
    labels = (container.attrs.get("Config", {}) or {}).get("Labels") or {}
    return {
        "working_dir": labels.get("com.docker.compose.project.working_dir") or "",
        "config_files": labels.get("com.docker.compose.project.config_files") or "",
        "project": labels.get("com.docker.compose.project") or "",
        # Set only when the install was started with --env-file; comma-separated.
        "env_files": labels.get("com.docker.compose.project.environment_file") or "",
    }


def self_update_info() -> dict[str, Any]:
    """What an update here would actually do — facts, no side effects."""
    client = _get_client()
    me = _self_container(client)
    info: dict[str, Any] = {
        "compose_managed": False,
        "working_dir": "",
        "project": "",
        "worker_image": "",
        "ui_image": "",
        "updater_running": False,
        "docker_access": docker_access(),
        "proxy_policy_current": proxy_policy_current(),
        "proxy_policy_fix": proxy_policy_fix(),
    }
    if me is not None:
        project = _compose_project(me)
        info["compose_managed"] = bool(project["working_dir"])
        info["working_dir"] = project["working_dir"]
        info["project"] = project["project"]
        info["worker_image"] = (me.attrs.get("Config", {}) or {}).get("Image") or ""
    try:
        ui = client.containers.get("cashpilot-ui")
        info["ui_image"] = (ui.attrs.get("Config", {}) or {}).get("Image") or ""
    except NotFound:
        pass
    except APIError as exc:
        # The proxy's owner isolation keeps the worker away from the dashboard's
        # container, so the update below recreates the worker only and the
        # dashboard on this server is updated by hand.
        info["ui_by_hand"] = proxy_refusal(exc) is not None
    with contextlib.suppress(NotFound, APIError):
        updater = client.containers.get(UPDATER_NAME)
        info["updater_running"] = updater.status == "running"
    return info


#: Where the preflight writes the resolved config inside its own container.
_PREFLIGHT_OUT = "/tmp/cashpilot-compose-config.json"
#: Label on preflight containers, so a leftover one can be found and removed.
_PREFLIGHT_LABEL = "cashpilot.updater=check"


def _remove_leftover_checks(client: docker.DockerClient) -> None:
    """Remove preflight containers an interrupted check left behind.

    Their filesystem holds a resolved compose file, secrets included.
    """
    with contextlib.suppress(Exception):
        for old in client.containers.list(all=True, filters={"label": _PREFLIGHT_LABEL}):
            with contextlib.suppress(Exception):
                old.remove(force=True)


def _read_file_from_container(container: Any, path: str) -> bytes:
    """One regular file out of a (possibly exited) container."""
    import io as _io
    import tarfile as _tarfile

    stream, _stat = container.get_archive(path)
    buf = _io.BytesIO(b"".join(stream))
    with _tarfile.open(fileobj=buf) as tar:
        for member in tar:
            if member.isfile():
                fh = tar.extractfile(member)
                if fh is not None:
                    return fh.read()
    raise ValueError(f"{path} is not a file in the archive")


def _ensure_updater_image(client: docker.DockerClient) -> None:
    """Pull the helper image if this host does not have it yet.

    ``containers.run`` pulls a missing image by itself only when the daemon
    answers "No such image". Behind the socket proxy the create is refused
    before it reaches the daemon, with the proxy's own 404 ("owner policy
    could not resolve image"), so ``run`` raised instead of pulling, and the
    first in-app update on a proxied install failed with "Docker refused to
    start the update helper". Pulling first works the same with or without
    the proxy.
    """
    try:
        client.images.get(UPDATER_IMAGE)
        return
    except NotFound:
        pass
    except APIError as exc:
        refusal = proxy_refusal(exc)
        if refusal:
            raise SelfUpdateUnavailable(f"Not updating. {refusal}") from exc
        logger.warning("Could not check for the update helper image: %s", exc)
    except Exception as exc:  # noqa: BLE001 - a read timeout or a dropped socket: the pull below reports it
        logger.warning("Could not check for the update helper image: %s", type(exc).__name__)
    try:
        # The client's read timeout (60 s by default) ends a pull that stalls;
        # a slow pull that keeps sending progress goes on.
        client.images.pull(UPDATER_IMAGE)
    except APIError as exc:
        logger.warning("Could not pull the update helper image %s: %s", UPDATER_IMAGE, exc)
        refusal = proxy_refusal(exc)
        if refusal:
            raise SelfUpdateUnavailable(f"Not updating. {refusal}") from exc
        raise RuntimeError(f"Docker could not pull the update helper image {UPDATER_IMAGE}.") from exc
    except Exception as exc:  # noqa: BLE001 - a read timeout or a dropped socket, not a daemon answer
        logger.warning("Pulling the update helper image %s did not finish: %s", UPDATER_IMAGE, type(exc).__name__)
        raise RuntimeError(f"Docker could not pull the update helper image {UPDATER_IMAGE}.") from exc


def _resolve_compose_config(
    client: docker.DockerClient,
    working_dir: str,
    environment: dict[str, str],
    services: list[str],
    volumes: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """Resolve the compose file exactly as the updater will, without a socket.

    Same image, same project and env-file mounts (read-only here), same
    environment. The resolved file carries every interpolated secret from .env
    (session, encryption and API keys), so it is written to a file inside the
    check container and copied out, never printed: stdout would hand it to the
    daemon's log driver. Raises SelfUpdateUnavailable when Compose rejects the
    file, RuntimeError when the check itself cannot run.
    """
    import json as _json

    _remove_leftover_checks(client)
    try:
        check = client.containers.run(
            UPDATER_IMAGE,
            command=["docker", "compose", "config", "--format", "json", "-o", _PREFLIGHT_OUT, *services],
            working_dir=working_dir,
            volumes={path: {**spec, "mode": "ro"} for path, spec in volumes.items()},
            environment=environment,
            labels={"cashpilot.updater": "check"},
            security_opt=["no-new-privileges:true"],
            detach=True,
        )
    except APIError as exc:
        logger.warning("Self-update preflight failed to start: %s", exc)
        refusal = proxy_refusal(exc)
        if refusal:
            raise SelfUpdateUnavailable(f"Not updating. {refusal}") from exc
        raise RuntimeError("Docker refused to start the update helper.") from exc
    try:
        try:
            status = check.wait(timeout=_PREFLIGHT_TIMEOUT)
            err = check.logs(stdout=False, stderr=True)
        except Exception as exc:  # timeout (requests) or daemon error
            logger.warning("Self-update preflight did not finish: %s", exc)
            raise RuntimeError("The update check did not finish; try again.") from exc
        code = status.get("StatusCode", 1) if isinstance(status, dict) else 1
        err_text = (err or b"").decode("utf-8", "replace").strip()
        if code != 0:
            raise SelfUpdateUnavailable(
                "Not updating: docker compose rejected the configuration: " + (err_text[-600:] or f"exit {code}")
            )
        try:
            out = _read_file_from_container(check, _PREFLIGHT_OUT)
            cfg = _json.loads(out.decode("utf-8", "replace"))
        except Exception as exc:
            raise RuntimeError("The update check returned unreadable output.") from exc
        if not isinstance(cfg, dict):
            raise RuntimeError("The update check returned unreadable output.")
        return cfg
    finally:
        with contextlib.suppress(Exception):
            check.remove(force=True)


def _proxy_bind_roots() -> list[str]:
    """The host folders the proxy lets containers bind, as the worker was told.

    The compose file hands the proxy and the worker the same two variables, so
    the worker can refuse an update the proxy would refuse, with a sentence
    instead of a 403 halfway through.
    """
    roots: list[str] = []
    for raw in (os.getenv("CASHPILOT_COMPOSE_DIR", ""), *os.getenv("CASHPILOT_PROXY_BIND_MOUNTS", "").split(",")):
        # Taken exactly as the proxy reads them: an entry padded with spaces is
        # not a path to it, so it opens nothing here either.
        if raw.startswith("/") and raw == raw.strip():
            roots.append(raw.rstrip("/") or "/")
    return roots


def _within_proxy_roots(path: str, roots: list[str]) -> bool:
    path = os.path.normpath(path)
    return any(root == "/" or path == root or path.startswith(root + "/") for root in roots)


def _outside_proxy_roots(volumes: dict[str, Any] | list[str] | None) -> list[str]:
    """Host folders in a deploy's mounts the socket proxy would refuse; [] when not proxied."""
    if not proxied() or not volumes:
        return []
    sources = [str(v).split(":", 1)[0] for v in volumes] if isinstance(volumes, list) else list(volumes)
    roots = _proxy_bind_roots()
    return [src for src in sources if src.startswith("/") and not _within_proxy_roots(src, roots)]


def _compose_device_path(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("source") or "")
    return str(entry).split(":", 1)[0]


def _proxy_compose_refusals(cfg: dict[str, Any], services: list[str]) -> list[str]:
    """What, in the resolved compose file, the socket proxy would refuse to create.

    The update helper recreates the UI and the worker through the proxy, so a
    service with a GPU, a device or a host folder outside the allowed ones would
    fail after Compose has started. Listed per service, so the operator knows
    which line to change.
    """
    roots = _proxy_bind_roots()
    caps = set(socket_policy.ALLOWED_CAPABILITIES)
    found: list[str] = []
    for name in services:
        svc = (cfg.get("services") or {}).get(name)
        if not isinstance(svc, dict):
            continue
        why: list[str] = []
        for vol in svc.get("volumes") or []:
            if isinstance(vol, dict) and vol.get("type") == "bind":
                source = str(vol.get("source") or "")
                if source.startswith("/") and not _within_proxy_roots(source, roots):
                    why.append(f"the host folder {source}")
        for dev in svc.get("devices") or []:
            if _compose_device_path(dev) not in socket_policy.ALLOWED_DEVICES:
                why.append(f"the device {_compose_device_path(dev)}")
        reservations = ((svc.get("deploy") or {}).get("resources") or {}).get("reservations") or {}
        if svc.get("gpus") or reservations.get("devices"):
            why.append("a GPU request")
        if svc.get("privileged"):
            why.append("privileged mode")
        extra_caps = sorted({str(c).upper().removeprefix("CAP_") for c in svc.get("cap_add") or []} - caps)
        if extra_caps:
            why.append(f"the capabilities {', '.join(extra_caps)}")
        for key, label in (
            ("pid", "the PID"),
            ("ipc", "the IPC"),
            ("userns_mode", "the user"),
            ("cgroup", "the cgroup"),
        ):
            if str(svc.get(key) or "").startswith("host"):
                why.append(f"{label} namespace of the host")
        security_opt = [str(o).replace("=", ":").replace(" ", "") for o in svc.get("security_opt") or []]
        if not any(o in ("no-new-privileges", "no-new-privileges:true") for o in security_opt):
            why.append("no no-new-privileges")
        for opt in security_opt:
            if opt in ("seccomp:unconfined", "apparmor:unconfined", "systempaths:unconfined"):
                why.append(opt)
        runtime = svc.get("runtime")
        if runtime and runtime not in socket_policy.ALLOWED_RUNTIMES:
            why.append(f"the {runtime} runtime")
        if why:
            found.append(f"{name}, which asks for {', '.join(why)}")
    return found


def _proxy_volume(me: Any) -> str:
    """The socket volume this worker mounts, whatever its compose file calls it.

    A worker updated to this image from an older compose file still has the
    proxy's socket in cashpilot-docker-api; mounting the new name there would
    hand the helper an empty volume and no Docker.
    """
    for mount in (getattr(me, "attrs", None) or {}).get("Mounts") or []:
        if mount.get("Type") == "volume" and mount.get("Destination") == PROXY_SOCKET_DIR and mount.get("Name"):
            return str(mount["Name"])
    return PROXY_VOLUME


def _check_proxy_binds(working_dir: str, extra_paths: list[str]) -> None:
    """Refuse, with the line to paste, an update the proxy would not let bind its folders."""
    compose_dir = os.getenv("CASHPILOT_COMPOSE_DIR", "").strip().rstrip("/")
    if compose_dir != working_dir.rstrip("/"):
        # working_dir is the path Compose itself ran in. Under a webhook or a
        # deployer container (Portainer and the like) that path is inside the
        # deployer and may not exist on this host; the helper binds it as is,
        # so no other value would work either: the deployer has to update.
        raise SelfUpdateUnavailable(
            f"The update helper needs your compose folder, which Docker Compose recorded as "
            f"{working_dir}, and the Docker socket proxy lets containers bind only the folders "
            "it was told about. If Compose runs inside another container for you (a webhook, "
            "Portainer or another deployer), that path is inside it, not on this host: update "
            "the stack from your deployer instead. Otherwise either update with docker compose "
            "pull && docker compose up -d, or add this line to the .env next to your compose "
            "file and run docker compose up -d once (it lets containers bind that folder "
            "through the proxy, which weakens it): "
            f"{COMPOSE_DIR_ENV}={working_dir}"
        )
    roots = _proxy_bind_roots()
    outside = [p for p in extra_paths if not _within_proxy_roots(p, roots)]
    if outside:
        raise SelfUpdateUnavailable(
            f"This install reads its settings from {', '.join(outside)}, outside your compose folder, "
            "and the Docker socket proxy will not let the update helper read it. Add the file's "
            f"folder to {BIND_MOUNTS_ENV} in that settings file, then run docker compose up -d once, "
            f"or update by hand: {_MANUAL_UPDATE}"
        )


def spawn_self_update() -> dict[str, Any]:
    """Start the one-shot updater helper and return its identity.

    Raises SelfUpdateUnavailable when this install has no compose project to
    update (not deployed via Compose, or the worker cannot see itself), and
    when an update is already running.
    """
    client = _get_client()
    me = _self_container(client)
    if me is None:
        raise SelfUpdateUnavailable(
            "The worker cannot identify its own container, so it cannot locate "
            "your compose project. Update manually: docker compose pull && docker compose up -d"
        )
    project = _compose_project(me)
    if not project["working_dir"]:
        raise SelfUpdateUnavailable(
            "This install is not managed by Docker Compose (no compose labels on "
            "the worker container). Update manually with the commands you used to "
            "install — for docker run, pull the new image and recreate the "
            "cashpilot-ui and cashpilot-worker containers."
        )

    working_dir = project["working_dir"]
    if not working_dir.startswith("/"):
        # Docker Desktop on Windows labels the project with a C:\... path, which
        # the daemon cannot use as a Linux bind target or working directory.
        raise SelfUpdateUnavailable(
            f"The compose project lives at {working_dir}, a Windows path the update "
            "helper cannot mount (Docker Desktop on Windows). Update from that folder "
            f"instead: {_MANUAL_UPDATE}"
        )

    # The update is scoped to the CashPilot services BY NAME, both derived from
    # container labels — never `up -d` on the whole project, which would
    # recreate any unrelated services the operator keeps in the same file.
    # Each service keeps its live container, for the port check below.
    me_labels = (me.attrs.get("Config", {}) or {}).get("Labels") or {}
    services: list[str] = []
    live: list[tuple[str, set[_Binding]]] = []
    my_service = me_labels.get("com.docker.compose.service")
    if my_service:
        services.append(my_service)
        live.append((my_service, _published_from_container(me.attrs)))
    with contextlib.suppress(NotFound, APIError):
        ui = client.containers.get("cashpilot-ui")
        ui_labels = (ui.attrs.get("Config", {}) or {}).get("Labels") or {}
        if ui_labels.get("com.docker.compose.project") == project["project"]:
            ui_service = ui_labels.get("com.docker.compose.service")
            if ui_service and ui_service not in services:
                services.append(ui_service)
                live.append((ui_service, _published_from_container(ui.attrs)))
    if not services:
        raise SelfUpdateUnavailable(
            "The worker container carries a compose project but no service name "
            "label, so the update cannot be scoped safely. Update manually: "
            f"{_MANUAL_UPDATE}"
        )

    environment: dict[str, str] = {}
    if project["config_files"]:
        # Compose separates label paths with commas; COMPOSE_FILE uses colons.
        environment["COMPOSE_FILE"] = project["config_files"].replace(",", ":")
    if project["project"]:
        # Without it Compose names the project after the folder (or `name:` or
        # .env), so an install started with `-p` lands in a second project
        # and `up` fails on the container_name it already uses.
        environment["COMPOSE_PROJECT_NAME"] = project["project"]

    # The project dir is mounted at its own path. An install started with
    # --env-file read its values from those files instead of .env; without them
    # the update would resolve every variable to its default. Pass the same
    # files (Compose's COMPOSE_ENV_FILES, comma-separated like the label) and
    # mount any that live outside the project dir, read-only, at their paths.
    project_mount = {working_dir: {"bind": working_dir}}
    env_mounts: dict[str, dict[str, str]] = {}
    env_files = [f for f in project["env_files"].split(",") if f]
    if env_files:
        if not all(f.startswith("/") for f in env_files):
            raise SelfUpdateUnavailable(
                f"This install reads its settings from {', '.join(env_files)}, a path the update "
                f"helper cannot mount. Update from your compose folder instead: {_MANUAL_UPDATE}"
            )
        environment["COMPOSE_ENV_FILES"] = ",".join(env_files)
        root = working_dir.rstrip("/") + "/"
        for f in env_files:
            if not f.startswith(root):
                env_mounts[f] = {"bind": f, "mode": "ro"}

    if proxied():
        _check_proxy_binds(working_dir, list(env_mounts))

    # Only one update at a time; checked before the preflight so a second
    # click does not even resolve the config.
    try:
        try:
            existing = client.containers.get(UPDATER_NAME)
            if existing.status == "running":
                raise SelfUpdateUnavailable("An update is already running.")
            # A leftover from an interrupted run — clear it so the fixed name is free.
            existing.remove(force=True)
        except NotFound:
            pass
    except APIError as exc:
        logger.warning("Self-update lock check failed: %s", exc)
        raise RuntimeError("Docker refused to start the update helper.") from exc

    _ensure_updater_image(client)
    cfg = _resolve_compose_config(client, working_dir, environment, services, {**project_mount, **env_mounts})
    if proxied():
        refused = _proxy_compose_refusals(cfg, services)
        if refused:
            raise SelfUpdateUnavailable(
                "Not updating: the Docker socket proxy would refuse to recreate "
                + "; ".join(refused)
                + ". Compose would stop halfway. A host folder can be allowed by adding it to "
                f"{BIND_MOUNTS_ENV} in the .env next to your compose file; anything else has to go from the "
                f"CashPilot services in that file, or update by hand: {_MANUAL_UPDATE}"
            )
    drift = _port_drift(live, cfg)
    if drift:
        source = (
            "the env file" + ("s " if len(env_files) > 1 else " ") + ", ".join(env_files) + " you started it with"
            if env_files
            else "the .env file next to your compose file"
        )
        raise SelfUpdateUnavailable(
            "Not updating: " + "; ".join(drift) + ". This happens when a port or address was set on the command line "
            "(for example CASHPILOT_UI_PORT=8088 docker compose up -d). The update "
            f"cannot see your shell, only {source}. "
            "Put the values there, or update by hand: " + _MANUAL_UPDATE
        )

    if proxied():
        # The helper gets what the worker has: the filtered socket, never the
        # host's. Its compose pull and up then pass the same policy, and
        # --no-deps keeps it from recreating the proxy it is talking through.
        docker_mount = {_proxy_volume(me): {"bind": PROXY_SOCKET_DIR, "mode": "rw"}}
        helper_env = {**environment, "DOCKER_HOST": os.environ["DOCKER_HOST"].strip()}
    else:
        docker_mount = {"/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"}}
        helper_env = environment
    try:
        updater = client.containers.run(
            UPDATER_IMAGE,
            name=UPDATER_NAME,
            command=["sh", "-c", _updater_script(services)],
            working_dir=working_dir,
            volumes={
                **docker_mount,
                working_dir: {"bind": working_dir, "mode": "rw"},
                **env_mounts,
            },
            environment=helper_env,
            labels={"cashpilot.updater": "true"},
            security_opt=["no-new-privileges:true"],
            detach=True,
            remove=True,
        )
    except APIError as exc:
        # Two updates racing: the loser's containers.run hits a 409 name
        # conflict on the fixed helper name — that is the already-running
        # answer, not an outage. Anything else from the daemon is.
        if getattr(exc, "status_code", None) == 409:
            raise SelfUpdateUnavailable("An update is already running (the helper name is in use).") from exc
        logger.warning("Self-update helper failed to start: %s", exc)
        refusal = proxy_refusal(exc)
        if refusal:
            raise SelfUpdateUnavailable(f"Not updating. {refusal}") from exc
        raise RuntimeError("Docker refused to start the update helper.") from exc

    logger.info(
        "Self-update started: helper %s updating %s in %s",
        updater.id[:12],
        ", ".join(services),
        working_dir,
    )
    return {"updater_id": updater.id[:12], "working_dir": working_dir, "services": services}


def _collect_stats(c) -> tuple[float, float, int | None, int | None]:
    """Collect CPU%, memory and cumulative network counters for one container.

    Returns ``(cpu_pct, mem_mb, rx_bytes, tx_bytes)``. The counters are None
    when Docker reports no interfaces — which is what happens for a container on
    the HOST network, where the ``networks`` key is absent entirely. That is not
    zero traffic and must never be reported as such: on a real fleet the single
    busiest service is host-networked.
    """
    try:
        stats = c.stats(stream=False)
        cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        system_delta = stats["cpu_stats"]["system_cpu_usage"] - stats["precpu_stats"]["system_cpu_usage"]
        num_cpus = stats["cpu_stats"].get(
            "online_cpus",
            len(stats["cpu_stats"]["cpu_usage"].get("percpu_usage", [1])),
        )
        cpu_pct = round((cpu_delta / system_delta) * num_cpus * 100, 2) if system_delta > 0 else 0.0
        mem_mb = round(stats["memory_stats"].get("usage", 0) / (1024 * 1024), 1)
        rx, tx = _network_totals(stats)
        return cpu_pct, mem_mb, rx, tx
    except (KeyError, ZeroDivisionError, APIError):
        # None, not 0.0. A stats call that FAILED tells us nothing about the
        # container's CPU or memory, and 0.00% / 0.0 MB is a measurement — one
        # that reads as "idle" for a container that may be working hard. The
        # network counters on the line above were already None for exactly this
        # reason; the same failure was being reported two different ways.
        return None, None, None, None


def _network_totals(stats: dict[str, Any]) -> tuple[int | None, int | None]:
    """Cumulative rx/tx across every interface, or (None, None) if unreported."""
    networks = stats.get("networks")
    if not isinstance(networks, dict) or not networks:
        return None, None
    rx = tx = 0
    for iface in networks.values():
        if not isinstance(iface, dict):
            continue
        rx += int(iface.get("rx_bytes") or 0)
        tx += int(iface.get("tx_bytes") or 0)
    return rx, tx


#: Concurrent `stats` calls. Bounded because the aim is to stop the heartbeat
#: growing with the container count, not to flood the Docker daemon — an
#: unbounded fan-out on a busy host trades one problem for another.
_STATS_CONCURRENCY = 8


def _collect_stats_bulk(containers: list[Any]) -> dict[str, tuple[float, float, int | None, int | None]]:
    """Stats for many containers at once, keyed by container id.

    `stats(stream=False)` costs ~1-2s per container and was called in a serial
    loop, so a heartbeat took time proportional to the number of containers on
    the host. The loop sleeps AFTER sending, so this stretches the real
    heartbeat interval rather than skipping cycles: at 60s nominal and 180s
    before the UI marks a worker offline, a host would start flapping somewhere
    past 60-80 containers. Today's reference fleet runs ~14 on its busiest
    host, so this is a margin that shrinks as people add services, not a fire.

    The calls are read-only GETs issued through the shared client, which is a
    `requests.Session` subclass backed by urllib3's lock-protected connection
    pool. docker-py has never published a thread-safety guarantee — the
    question is open in their tracker — so this is a deliberate, bounded bet on
    widely-relied-upon behaviour rather than a documented contract.
    """
    if not containers:
        return {}
    results: dict[str, tuple[float, float, int | None, int | None]] = {}
    with ThreadPoolExecutor(max_workers=min(_STATS_CONCURRENCY, len(containers))) as pool:
        futures = {pool.submit(_collect_stats, c): c for c in containers}
        for future in as_completed(futures):
            container = futures[future]
            try:
                results[container.id] = future.result()
            except Exception as exc:
                # One unreadable container must not cost us the whole fleet's
                # stats. None, like _collect_stats: a failed read is not 0% CPU.
                logger.warning("Stats unavailable for %s: %s", getattr(container, "short_id", "?"), exc)
                results[container.id] = (None, None, None, None)
    return results


def _advertised_address(container: Any, slug: str) -> str | None:
    """The value of the ONE env var this service declares as its dial-back address.

    Only a service whose catalog entry sets ``docker.advertised_address_env``
    yields anything, and only that single variable is ever read: container env
    holds credentials, and the heartbeat must never widen into carrying them.
    The Docker LIST API omits ``Config.Env``, so this costs one inspect call —
    but only for declaring services (in practice: storj alone), so the status
    paths stay cheap. None is "nothing to report", covering the undeclared,
    unset and inspect-failed cases alike — absence is not a claim.
    """
    if get_service is None:
        return None
    try:
        service = get_service(slug) or {}
    except Exception:
        return None
    docker_conf = service.get("docker") or {}
    var = docker_conf.get("advertised_address_env")
    if not var or not isinstance(var, str):
        return None
    # Runtime backstop for the CI guard: a catalog edit pointing this at a
    # secret-flagged var must not start exporting a credential into every
    # heartbeat just because a test was skipped.
    for declared in docker_conf.get("env") or []:
        if isinstance(declared, dict) and declared.get("key") == var and declared.get("secret"):
            return None
    try:
        env = (container.client.api.inspect_container(container.id).get("Config") or {}).get("Env") or []
    except Exception:
        return None
    prefix = f"{var}="
    for entry in env:
        if isinstance(entry, str) and entry.startswith(prefix):
            return entry[len(prefix) :] or None
    return None


# What keys identity_digest: the worker's active API key, set by worker_api.
# Unset (the UI process, a test) means no digest at all.
identity_digest_key: Any = None

# Container id -> the identity values it runs with. A container's env never
# changes, so each is inspected once; the cap only bounds a long uptime. The
# digest is made per call, so it follows the key when the worker enrols.
_identity_values: dict[str, dict[str, str]] = {}


def _identity_entry(container: Any, slug: str) -> dict[str, str]:
    """``identity_digest``: a keyed hash of the device ids this container runs with.

    The UI writes a copy's ledger row only when this matches what its deploy
    record derives (catalog.identity_digest), so a copy still running an older
    id is never given a newer one. Only for a service with identity keys, and
    never the ids themselves: they let whoever holds them claim the device.
    """
    if get_service is None or identity_digest is None or identity_keys is None or identity_digest_key is None:
        return {}
    try:
        service = get_service(slug)
        key = identity_digest_key()
    except Exception:
        return {}
    cid = str(getattr(container, "id", "") or "")
    if not service or not cid or not key:
        return {}
    if cid not in _identity_values:
        names = identity_keys(service)
        if not names:
            return {}
        try:
            env_list = (container.client.api.inspect_container(cid).get("Config") or {}).get("Env") or []
        except Exception:
            return {}
        env = dict(e.split("=", 1) for e in env_list if isinstance(e, str) and "=" in e)
        if len(_identity_values) > 1024:
            _identity_values.clear()
        _identity_values[cid] = {name: env.get(name, "") for name in names}
    digest = identity_digest(service, _identity_values[cid], key)
    return {"identity_digest": digest} if digest else {}


def copy_identity_digests(slug: str) -> dict[str, str]:
    """The digest of every copy of ``slug`` on this worker, by copy number, before a removal."""
    digests: dict[str, str] = {}
    for container in service_instances(slug):
        if digest := _identity_entry(container, slug).get("identity_digest"):
            digests[str(_instance_of(container))] = digest
    return digests


def get_status() -> list[dict[str, Any]]:
    """Return live status of all known containers (labeled + image-matched).

    Calls the Docker stats API for every container, which is slow per container
    (~1-2s); the calls are issued concurrently, but this is still far heavier
    than a plain list. Use get_status_cached() for page loads; this is for
    background refresh.
    """
    global _status_cache, _status_cache_time

    try:
        client = _get_client()
    except RuntimeError:
        return []

    # Labeled containers (CashPilot-managed)
    try:
        labeled = client.containers.list(
            all=True,
            filters={"label": f"{LABEL_MANAGED}=true"},
        )
    except Exception as exc:
        # "Ping works, list fails" (daemon 500, read timeout, containerd
        # hiccup) used to escape this function entirely: the heartbeat then
        # shipped containers=[] WITH docker_available=true — a worker that
        # looks online and deliberately empty, while the UI writes a durable
        # check_down for every deployment it can no longer see. Flag the
        # outage so the SAME heartbeat reports blind, and the UI's guard
        # skips the false downtime.
        _mark_docker_unavailable("container listing failed", exc)
        return []
    seen_ids: set[str] = set()

    results: list[dict[str, Any]] = []
    # Proxied copies and their tunnels are reported on their own
    # (proxy_tunnel.status): they leave from another IP and are not copies of
    # the service. Marked seen so the image match below cannot adopt them.
    seen_ids.update(c.id for c in labeled if is_proxied(c))
    labeled = [c for c in labeled if not is_proxied(c)]
    labeled_stats = _collect_stats_bulk(list(labeled))
    for c in labeled:
        try:
            seen_ids.add(c.id)
            slug = c.labels.get(LABEL_SERVICE, "unknown")
            cpu_pct, mem_mb, net_rx, net_tx = labeled_stats.get(c.id, (None, None, None, None))
            entry = {
                "slug": slug,
                "name": c.name,
                "status": c.status,
                "image": _image_ref(c.image, (c.attrs.get("Config") or {}).get("Image", "")) or str(c.image.short_id),
                "cpu_percent": cpu_pct,
                "memory_mb": mem_mb,
                # Cumulative since container start; None when unavailable.
                "net_rx_bytes": net_rx,
                "net_tx_bytes": net_tx,
                "created": c.attrs.get("Created", ""),
                "container_id": c.short_id,
                "deployed_by": c.labels.get(LABEL_DEPLOYED_BY, "unknown"),
                "category": c.labels.get(LABEL_CATEGORY, ""),
                "instance": _instance_of(c),
                **_shape_entry(c),
                **_stop_facts(c),
                **_identity_entry(c, slug),
                **_state_id_entry(c, slug, client),
                **_fatal_entry(c, slug),
                **_held_entry(c),
            }
            # Present only when the service declares a dial-back address var;
            # the key's absence is "nothing to say", never "checked and fine".
            if advertised := _advertised_address(c, slug):
                entry["advertised_address"] = advertised
            results.append(entry)
        except Exception as exc:
            logger.warning("Skipping corrupted container %s: %s", getattr(c, "short_id", "?"), exc)

    # Image-matched containers (deployed externally)
    image_map = _build_image_slug_map()
    if image_map:
        try:
            all_containers = _external_candidates(client, image_map)
        except Exception as exc:
            # Same rule as the labeled list: a partial result with the flag
            # still true would show EXTERNAL deployments as down instead of
            # Docker-blind — the exact lie this change removes.
            _mark_docker_unavailable("container listing failed", exc)
            return []
        # Resolve which externally-deployed containers we actually care about
        # BEFORE fetching stats, so nothing is paid for a container we skip.
        matched: list[tuple[Any, str, str]] = []
        for c in all_containers:
            try:
                if c.id in seen_ids:
                    continue
                image_name = _image_ref(c.image, (c.attrs.get("Config") or {}).get("Image", ""))
                slug = image_map.get(image_name, "")
                if not slug and image_name:
                    slug = image_map.get(_image_repository(image_name), "")
                if slug:
                    seen_ids.add(c.id)
                    matched.append((c, slug, image_name))
            except Exception as exc:
                logger.warning("Skipping corrupted container %s: %s", getattr(c, "short_id", "?"), exc)

        matched_stats = _collect_stats_bulk([c for c, _, _ in matched])
        for c, slug, image_name in matched:
            try:
                cpu_pct, mem_mb, net_rx, net_tx = matched_stats.get(c.id, (None, None, None, None))
                entry = {
                    "slug": slug,
                    "name": c.name,
                    "status": c.status,
                    "image": image_name or str(c.image.short_id),
                    "cpu_percent": cpu_pct,
                    "memory_mb": mem_mb,
                    "net_rx_bytes": net_rx,
                    "net_tx_bytes": net_tx,
                    "created": c.attrs.get("Created", ""),
                    "container_id": c.short_id,
                    "deployed_by": "external",
                    "category": "",
                    **_state_id_entry(c, slug, client),
                    **_fatal_entry(c, slug),
                }
                # External nodes are the COMMON storj adoption path (the node
                # predates CashPilot) — leaving them out of the address check
                # would blind it for exactly the users most likely to need it.
                if advertised := _advertised_address(c, slug):
                    entry["advertised_address"] = advertised
                results.append(entry)
            except Exception as exc:
                logger.warning("Skipping corrupted container %s: %s", getattr(c, "short_id", "?"), exc)

    # Update the cache
    _status_cache = results
    _status_cache_time = time.monotonic()

    return results


def get_status_cached(max_age: int = 600) -> list[dict[str, Any]]:
    """Return cached container status, falling back to light query if stale.

    Args:
        max_age: Maximum cache age in seconds (default 10 min).
                 The health check refreshes every 5 min, so 10 min
                 gives a comfortable margin.

    Returns instantly from memory on page loads. If the cache is empty
    (e.g. first load, cache still warming), falls back to the fast
    get_status_light() which skips per-container stats.
    """
    if _status_cache and (time.monotonic() - _status_cache_time) < max_age:
        return _status_cache
    # Cache empty or stale — return fast light status (no CPU/memory)
    # rather than blocking for 20+ seconds on get_status()
    return get_status_light()


def _external_candidates(client: Any, image_map: dict[str, str]) -> list[Any]:
    """Every container on the host that may run a catalog image, inspected.

    A plain list inspects each container it returns, and on a direct socket
    that is every container on the host, CashPilot's or not. The sparse list
    carries each container's image ID, so a container is inspected only when
    its image's tags or digests name a catalog repository. That is the same
    set of names the match below reads, whatever the container was created
    from: a tag, a local alias of the image, or a bare ID. Each image is read
    once. A container whose image cannot be read, or has no name left, is
    inspected as before. Raises what the list or an inspect raises, except a
    container removed in between.
    """
    repos = {_image_repository(k).lower() for k in image_map} - {""}
    names_by_image: dict[str, str | None] = {}

    def image_names(image_id: str) -> str | None:
        if image_id not in names_by_image:
            try:
                attrs = client.images.get(image_id).attrs or {}
                names = [*(attrs.get("RepoTags") or []), *(attrs.get("RepoDigests") or [])]
                names_by_image[image_id] = " ".join(str(n) for n in names).lower()
            except Exception:  # noqa: BLE001 - unknown: the container is inspected as before
                names_by_image[image_id] = None
        return names_by_image[image_id]

    found = []
    for c in client.containers.list(all=True, sparse=True):
        attrs = getattr(c, "attrs", None)
        attrs = attrs if isinstance(attrs, dict) else {}
        image_id = attrs.get("ImageID")
        if image_id:
            names = image_names(str(image_id))
            # An image with no tag and no digest left (its reference was
            # removed while a container still uses it) says nothing: the
            # container's own Config.Image may still be a catalog reference.
            if names and not any(r in names for r in repos):
                continue
        if "Config" not in attrs and callable(getattr(c, "reload", None)):
            try:
                c.reload()
            except NotFound:
                # Removed between the list and the inspect. Any other error is
                # the daemon's and propagates, so the caller marks Docker blind.
                logger.debug("Container %s is gone", getattr(c, "short_id", "?"))
                continue
        found.append(c)
    return found


def _image_ref(image: Any, created_from: str = "") -> str:
    """The name an image was pulled by: its first tag, else its digest reference.

    An image pulled by digest, as the catalog pins ProxyBase, has no tag at all,
    only ``repo@sha256:...`` in RepoDigests. Reporting its bare ID instead made
    the dashboard compare "sha256" against the catalog's repository and flag a
    current container as outdated.

    ``created_from`` is the reference the container was created with. When that
    is a digest reference it wins: it is exactly what the catalog pinned, while
    RepoDigests is sorted alphabetically and an image can carry several.
    The same holds for a tag: when the image carries the one it was created
    from, that tag wins over whichever Docker lists first.
    """
    if "@sha256:" in created_from:
        return created_from
    tags = image.tags if isinstance(image.tags, list) else []
    if created_from and created_from in tags:
        # One image can carry several tags (busybox:latest and busybox:1.36 on
        # one ID); the one the container was created from is the true answer.
        return created_from
    if image.tags:
        return image.tags[0]
    attrs = getattr(image, "attrs", None)
    digests = attrs.get("RepoDigests") if isinstance(attrs, dict) else None
    return digests[0] if isinstance(digests, list) and digests and isinstance(digests[0], str) else ""


def _image_repository(image_name: str) -> str:
    """The repository of an image reference: no tag, no digest."""
    return image_name.split("@")[0].split(":")[0]


def _build_image_slug_map() -> dict[str, str]:
    """Build a map of Docker image names to service slugs from catalog."""
    if not get_services:
        return {}
    mapping: dict[str, str] = {}
    for svc in get_services():
        docker_conf = svc.get("docker", {})
        image = docker_conf.get("image", "")
        if image:
            # Map both "image" and "image:latest" to the slug
            mapping[image] = svc["slug"]
            if "@" in image:
                # A digest-pinned image: an external container on an older
                # digest of the same repository is still this service.
                mapping[image.split("@")[0]] = svc["slug"]
            elif ":" not in image:
                mapping[f"{image}:latest"] = svc["slug"]
    return mapping


def get_status_light() -> list[dict[str, Any]]:
    """Return container list/status WITHOUT resource stats (fast).

    Only queries Docker for container list + labels, skips the slow
    per-container stats() call. Used when we need fresh container
    states (running/stopped) but don't need CPU/memory numbers.

    Finds containers by cashpilot label OR by matching Docker image
    to known catalog services (for containers deployed externally).
    """
    try:
        client = _get_client()
    except RuntimeError:
        return []

    # First: labeled containers (CashPilot-managed)
    try:
        labeled = client.containers.list(
            all=True,
            filters={"label": f"{LABEL_MANAGED}=true"},
        )
    except Exception as exc:
        # Mirror of get_status: "ping works, list fails" must flag the outage,
        # not serve an empty-but-healthy answer.
        _mark_docker_unavailable("container listing failed", exc)
        return []
    seen_ids: set[str] = {c.id for c in labeled if is_proxied(c)}
    labeled = [c for c in labeled if not is_proxied(c)]

    results: list[dict[str, Any]] = []
    for c in labeled:
        try:
            seen_ids.add(c.id)
            slug = c.labels.get(LABEL_SERVICE, "unknown")
            entry = {
                "slug": slug,
                "name": c.name,
                "status": c.status,
                "image": _image_ref(c.image, (c.attrs.get("Config") or {}).get("Image", "")) or str(c.image.short_id),
                "cpu_percent": 0.0,
                "memory_mb": 0.0,
                "created": c.attrs.get("Created", ""),
                "container_id": c.short_id,
                "deployed_by": c.labels.get(LABEL_DEPLOYED_BY, "unknown"),
                "category": c.labels.get(LABEL_CATEGORY, ""),
                "instance": _instance_of(c),
                **_shape_entry(c),
                **_stop_facts(c),
                **_fatal_entry(c, slug),
                **_held_entry(c),
            }
            # Same contract as get_status: key present only when declared+set.
            if advertised := _advertised_address(c, slug):
                entry["advertised_address"] = advertised
            results.append(entry)
        except Exception as exc:
            logger.warning("Skipping corrupted container %s: %s", getattr(c, "short_id", "?"), exc)

    # Second: scan all containers and match by image name
    image_map = _build_image_slug_map()
    if image_map:
        try:
            all_containers = _external_candidates(client, image_map)
        except Exception as exc:
            # Same rule as the labeled list: a partial result with the flag
            # still true would show EXTERNAL deployments as down instead of
            # Docker-blind — the exact lie this change removes.
            _mark_docker_unavailable("container listing failed", exc)
            return []
        for c in all_containers:
            try:
                if c.id in seen_ids:
                    continue
                image_name = _image_ref(c.image, (c.attrs.get("Config") or {}).get("Image", ""))
                slug = image_map.get(image_name, "")
                if not slug and image_name:
                    slug = image_map.get(_image_repository(image_name), "")
                # Dedupe on container ID only, NOT on slug. get_status does the
                # same, and get_status_cached serves whichever of the two is
                # current -- so a host running two containers of one external
                # image reported two of them or one depending purely on how warm
                # the cache was, with nothing in the code saying so
                # (CashPilot-dw1).
                #
                # Returning every container is the correct side of that
                # disagreement: the UI's per-instance rows exist to show each
                # one, and collapsing them hides a running container from the
                # person who has to manage it.
                if slug:
                    seen_ids.add(c.id)
                    entry = {
                        "slug": slug,
                        "name": c.name,
                        "status": c.status,
                        "image": image_name or str(c.image.short_id),
                        "cpu_percent": 0.0,
                        "memory_mb": 0.0,
                        "created": c.attrs.get("Created", ""),
                        "container_id": c.short_id,
                        "deployed_by": "external",
                        "category": "",
                        **_fatal_entry(c, slug),
                    }
                    # Same contract as the labeled loops; external storj nodes
                    # are the common adoption path and must not be blind spots.
                    if advertised := _advertised_address(c, slug):
                        entry["advertised_address"] = advertised
                    results.append(entry)
            except Exception as exc:
                logger.warning("Skipping corrupted container %s: %s", getattr(c, "short_id", "?"), exc)

    return results


def get_service_logs(slug: str, lines: int = 50, instance: int = 1) -> str:
    """Return the last N lines of logs for a service container."""
    container = _find_container(slug, instance)
    return container.logs(tail=lines, timestamps=True).decode("utf-8", errors="replace")


_MAX_PENDING_LOG_BYTES = 1 << 20


def grep_service_logs(
    slug: str, match: re.Pattern[str], since_hours: float, lines: int = 1000, instance: int = 1
) -> str:
    """The last ``lines`` log lines from the past ``since_hours`` that match ``match``.

    The tail cannot answer "has this happened in the last hours": Mysterium
    writes about 11,000 lines an hour, so 200 lines cover a minute. The window
    is read as a stream and filtered here, so megabytes of logs never leave the
    worker and never sit in memory at once.
    """
    container = _find_container(slug, instance)
    since = int(time.time() - since_hours * 3600)
    kept: collections.deque[str] = collections.deque(maxlen=lines)
    pending = b""
    # follow=False: docker-py follows a streamed log unless told not to, and
    # this read would then never return.
    for chunk in container.logs(stream=True, follow=False, since=since, timestamps=True):
        pending += chunk
        *complete, pending = pending.split(b"\n")
        # A record with no newline must not grow without bound; its tail is enough.
        pending = pending[-_MAX_PENDING_LOG_BYTES:]
        for raw in complete:
            line = raw.decode("utf-8", errors="replace")
            if match.search(line):
                kept.append(line)
    if pending:
        line = pending.decode("utf-8", errors="replace")
        if match.search(line):
            kept.append(line)
    return "\n".join(kept)
