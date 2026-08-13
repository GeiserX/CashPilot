"""Docker container orchestrator for CashPilot.

Runs inside the CashPilot Worker, which has the Docker socket mounted.
Manages container lifecycle (deploy, stop, restart, remove) and status
inspection for cashpilot-managed containers via the Docker SDK.
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import docker
from docker.errors import APIError, DockerException, NotFound

try:
    from app.catalog import critical_volume_targets, get_service, get_services
except ImportError:
    # Defensive fallback if the catalog module isn't importable in some context.
    # (The worker image does ship catalog.py + services/, so this normally no-ops.)
    get_service = None  # type: ignore[assignment]
    get_services = None  # type: ignore[assignment]
    critical_volume_targets = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

from app.constants import (  # noqa: E402
    CONTAINER_PREFIX,
    LABEL_CATEGORY,
    LABEL_DEPLOYED_BY,
    LABEL_MANAGED,
    LABEL_SERVICE,
    LABEL_VERSION,
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
    try:
        client = docker.from_env()
        client.ping()
        client.close()
        _mark_docker_available()
    except Exception as exc:
        logger.debug("Docker ping failed: %s", exc)
        _mark_docker_unavailable("ping failed", exc)
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
        raise RuntimeError(
            "Docker socket not available. Mount /var/run/docker.sock to "
            "enable container management, or use CashPilot in monitor-only "
            "mode for earnings tracking and compose file export."
        ) from exc


def _container_name(slug: str) -> str:
    return f"{CONTAINER_PREFIX}{slug}"


def _find_container(slug: str):
    """Find a MANAGED container by name, falling back to label-based lookup.

    The name match must verify the cashpilot.managed label, not just the
    prefix: the platform's own containers are named cashpilot-worker and
    cashpilot-ui, so slug "worker" name-matched the worker's OWN container
    and a writer-role command could force-remove it -- the worker deleting
    itself, unrecoverable remotely (CashPilot-o4uw). A name hit without the
    label is treated exactly like NotFound.
    """
    client = _get_client()
    name = _container_name(slug)
    try:
        container = client.containers.get(name)
        if (container.labels or {}).get(LABEL_MANAGED) == "true":
            return container
    except NotFound:
        pass
    # Fallback: find by label (handles renamed containers)
    matches = client.containers.list(
        all=True,
        filters={
            "label": [
                f"{LABEL_SERVICE}={slug}",
                f"{LABEL_MANAGED}=true",
            ]
        },
    )
    if matches:
        return matches[0]
    raise ValueError(f"Container for {slug} not found")


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


def available_runtimes() -> set[str]:
    """Runtimes the local Docker daemon actually reports.

    The allowlist is derived from the daemon rather than hardcoded, because a
    runtime CashPilot has heard of but the host has not installed would fail at
    container-create time with a Docker error the user cannot act on. Asking the
    daemon means the only runtimes offered are ones that exist here.
    """
    try:
        info = _get_client().info()
    except Exception:
        logger.warning("Could not read Docker runtimes; treating none as available")
        return set()
    runtimes = info.get("Runtimes")
    return set(runtimes) if isinstance(runtimes, dict) else set()


def deploy_raw(
    slug: str,
    image: str,
    env: dict[str, str] | None = None,
    ports: dict[str, int] | None = None,
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
) -> str:
    """Deploy a container from a raw spec (no catalog lookup).

    Used by CashPilot Worker when the UI sends a full container spec.
    ``resources`` (mem_limit / mem_reservation / oom_score_adj / cpu_shares)
    makes the container's cgroup limits durable across recreates. Returns the
    container ID.
    """
    client = _get_client()
    name = _container_name(slug)

    # Remove any existing container with the same name
    try:
        old = client.containers.get(name)
        logger.info("Removing existing container %s", name)
        old.remove(force=True)
    except NotFound:
        pass

    all_labels = {
        LABEL_SERVICE: slug,
        LABEL_MANAGED: "true",
        LABEL_VERSION: "1",
        LABEL_CATEGORY: category,
        LABEL_DEPLOYED_BY: "worker",
    }
    if labels:
        all_labels.update(labels)

    logger.info("Pulling image %s", image)
    try:
        client.images.pull(image)
    except APIError as exc:
        logger.warning("Failed to pull image %s: %s (trying local)", image, exc)

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
    container = client.containers.run(
        image=image,
        name=name,
        environment=env or {},
        ports=ports if ports and network_mode != "host" else None,
        volumes=volumes if volumes else None,
        network_mode=network_mode,
        # These images are third-party and closed-source, so they get the minimum
        # kernel surface: every capability dropped, then only the ones the service's
        # own catalog entry declares added back (today that is mysterium's NET_ADMIN
        # alone — the rest are plain outbound TCP clients). Without this they ran as
        # in-container root with Docker's full default set, which includes NET_RAW
        # (ARP/DNS spoofing on the bridge), MKNOD, SETUID and SYS_CHROOT.
        devices=devices or None,
        cap_drop=["ALL"],
        cap_add=cap_add or None,
        # no-new-privileges blocks privilege escalation via setuid binaries; privileged
        # is hardcoded off so the dangerous state is unrepresentable here rather than
        # merely refused upstream by the worker's spec validation.
        security_opt=["no-new-privileges:true"],
        privileged=False,
        pids_limit=_PIDS_LIMIT,
        command=command if command else None,
        labels=all_labels,
        hostname=hostname or f"cashpilot-{slug}",
        detach=True,
        restart_policy={"Name": "unless-stopped"},
        # None means Docker's default runtime, which is what every service uses
        # unless an advanced user has deliberately opted one into another.
        runtime=runtime or None,
        **resource_kwargs,
    )

    logger.info("Container %s started: %s", name, container.short_id)
    return container.id


def _parse_stop_timeout(value: Any) -> int:
    """Parse a stop_timeout value, returning 30 on invalid input."""
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        return 30
    return timeout if timeout > 0 else 30


def _get_stop_timeout(slug: str) -> int:
    """Return the stop timeout from the catalog, or 30s default."""
    if get_service:
        svc = get_service(slug)
        if svc:
            return _parse_stop_timeout(svc.get("docker", {}).get("stop_timeout"))
    return 30


def stop_service(slug: str) -> None:
    """Stop the container for a service."""
    container = _find_container(slug)
    container.stop(timeout=_get_stop_timeout(slug))
    logger.info("Stopped container %s", container.name)


def restart_service(slug: str) -> None:
    """Restart the container for a service."""
    container = _find_container(slug)
    container.restart(timeout=_get_stop_timeout(slug))
    logger.info("Restarted container %s", container.name)


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

    if was_running:
        container.pause()
    read_failure: BaseException | None = None
    try:
        for target in sorted(targets):
            stream, _stat = container.get_archive(target)
            chunks.append(b"".join(stream))
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


def start_service(slug: str) -> None:
    """Start a stopped container for a service."""
    container = _find_container(slug)
    container.start()
    logger.info("Started container %s", container.name)


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
                # stats; _collect_stats already degrades to zeros itself.
                logger.warning("Stats unavailable for %s: %s", getattr(container, "short_id", "?"), exc)
                results[container.id] = (0.0, 0.0, None, None)
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
    labeled_stats = _collect_stats_bulk(list(labeled))
    for c in labeled:
        try:
            seen_ids.add(c.id)
            slug = c.labels.get(LABEL_SERVICE, "unknown")
            cpu_pct, mem_mb, net_rx, net_tx = labeled_stats.get(c.id, (0.0, 0.0, None, None))
            entry = {
                "slug": slug,
                "name": c.name,
                "status": c.status,
                "image": c.image.tags[0] if c.image.tags else str(c.image.short_id),
                "cpu_percent": cpu_pct,
                "memory_mb": mem_mb,
                # Cumulative since container start; None when unavailable.
                "net_rx_bytes": net_rx,
                "net_tx_bytes": net_tx,
                "created": c.attrs.get("Created", ""),
                "container_id": c.short_id,
                "deployed_by": c.labels.get(LABEL_DEPLOYED_BY, "unknown"),
                "category": c.labels.get(LABEL_CATEGORY, ""),
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
            all_containers = client.containers.list(all=True)
        except Exception as exc:
            logger.warning("Failed to list all containers: %s", exc)
            all_containers = []
        # Resolve which externally-deployed containers we actually care about
        # BEFORE fetching stats, so nothing is paid for a container we skip.
        matched: list[tuple[Any, str, str]] = []
        for c in all_containers:
            try:
                if c.id in seen_ids:
                    continue
                image_name = c.image.tags[0] if c.image.tags else ""
                slug = image_map.get(image_name, "")
                if not slug and image_name:
                    slug = image_map.get(image_name.split(":")[0], "")
                if slug:
                    seen_ids.add(c.id)
                    matched.append((c, slug, image_name))
            except Exception as exc:
                logger.warning("Skipping corrupted container %s: %s", getattr(c, "short_id", "?"), exc)

        matched_stats = _collect_stats_bulk([c for c, _, _ in matched])
        for c, slug, image_name in matched:
            try:
                cpu_pct, mem_mb, net_rx, net_tx = matched_stats.get(c.id, (0.0, 0.0, None, None))
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
            if ":" not in image:
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
    labeled = client.containers.list(
        all=True,
        filters={"label": f"{LABEL_MANAGED}=true"},
    )
    seen_ids: set[str] = set()

    results: list[dict[str, Any]] = []
    for c in labeled:
        try:
            seen_ids.add(c.id)
            slug = c.labels.get(LABEL_SERVICE, "unknown")
            entry = {
                "slug": slug,
                "name": c.name,
                "status": c.status,
                "image": c.image.tags[0] if c.image.tags else str(c.image.short_id),
                "cpu_percent": 0.0,
                "memory_mb": 0.0,
                "created": c.attrs.get("Created", ""),
                "container_id": c.short_id,
                "deployed_by": c.labels.get(LABEL_DEPLOYED_BY, "unknown"),
                "category": c.labels.get(LABEL_CATEGORY, ""),
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
            all_containers = client.containers.list(all=True)
        except Exception as exc:
            logger.warning("Failed to list all containers: %s", exc)
            all_containers = []
        for c in all_containers:
            try:
                if c.id in seen_ids:
                    continue
                image_name = c.image.tags[0] if c.image.tags else ""
                slug = image_map.get(image_name, "")
                if not slug and image_name:
                    # Try without tag
                    base = image_name.split(":")[0]
                    slug = image_map.get(base, "")
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
                    }
                    # Same contract as the labeled loops; external storj nodes
                    # are the common adoption path and must not be blind spots.
                    if advertised := _advertised_address(c, slug):
                        entry["advertised_address"] = advertised
                    results.append(entry)
            except Exception as exc:
                logger.warning("Skipping corrupted container %s: %s", getattr(c, "short_id", "?"), exc)

    return results


def get_service_logs(slug: str, lines: int = 50) -> str:
    """Return the last N lines of logs for a service container."""
    container = _find_container(slug)
    return container.logs(tail=lines, timestamps=True).decode("utf-8", errors="replace")
