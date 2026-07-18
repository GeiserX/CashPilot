"""Docker container orchestrator for CashPilot.

Runs inside the CashPilot Worker, which has the Docker socket mounted.
Manages container lifecycle (deploy, stop, restart, remove) and status
inspection for cashpilot-managed containers via the Docker SDK.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import docker
from docker.errors import APIError, DockerException, NotFound

try:
    from app.catalog import get_service, get_services
except ImportError:
    # Defensive fallback if the catalog module isn't importable in some context.
    # (The worker image does ship catalog.py + services/, so this normally no-ops.)
    get_service = None  # type: ignore[assignment]
    get_services = None  # type: ignore[assignment]

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


def docker_available() -> bool:
    """Check whether the Docker socket is accessible.

    Only the positive result is memoized. A negative/unknown result is
    re-probed on every call so a transient daemon blip self-heals.
    """
    global _docker_available
    if _docker_available:
        return True
    try:
        client = docker.from_env()
        client.ping()
        client.close()
        _docker_available = True
    except Exception as exc:
        logger.debug("Docker ping failed: %s", exc)
        _docker_available = False
    return _docker_available


def _get_client() -> docker.DockerClient:
    """Return a Docker client, raising a clear error if the socket is missing."""
    try:
        client = docker.from_env()
        client.ping()
        return client
    except DockerException as exc:
        global _docker_available
        _docker_available = False
        raise RuntimeError(
            "Docker socket not available. Mount /var/run/docker.sock to "
            "enable container management, or use CashPilot in monitor-only "
            "mode for earnings tracking and compose file export."
        ) from exc


def _container_name(slug: str) -> str:
    return f"{CONTAINER_PREFIX}{slug}"


def _find_container(slug: str):
    """Find a container by name, falling back to label-based lookup."""
    client = _get_client()
    name = _container_name(slug)
    try:
        return client.containers.get(name)
    except NotFound:
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


def deploy_raw(
    slug: str,
    image: str,
    env: dict[str, str] | None = None,
    ports: dict[str, int] | None = None,
    volumes: dict[str, dict[str, str]] | None = None,
    network_mode: str | None = None,
    cap_add: list[str] | None = None,
    privileged: bool = False,
    command: str | None = None,
    hostname: str | None = None,
    labels: dict[str, str] | None = None,
    resources: Any = None,
    category: str = "bandwidth",
) -> str:
    """Deploy a container from a raw spec (no catalog lookup).

    Used by CashPilot Worker when the UI sends a full container spec.
    ``resources`` (mem_limit / mem_reservation / oom_score_adj) makes the
    container's cgroup limits durable across recreates. Returns the container ID.
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
        key: res[key] for key in ("mem_limit", "mem_reservation", "oom_score_adj") if res.get(key) is not None
    }

    logger.info("Creating container %s from %s", name, image)
    container = client.containers.run(
        image=image,
        name=name,
        environment=env or {},
        ports=ports if ports and network_mode != "host" else None,
        volumes=volumes if volumes else None,
        network_mode=network_mode,
        cap_add=cap_add,
        privileged=privileged,
        command=command if command else None,
        labels=all_labels,
        hostname=hostname or f"cashpilot-{slug}",
        detach=True,
        restart_policy={"Name": "unless-stopped"},
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


def remove_service(slug: str, delete_volumes: bool = False) -> dict[str, Any]:
    """Stop and remove the container for a service.

    When delete_volumes is True, also remove named volumes that were
    mounted into the container. Bind mounts and anonymous volumes are skipped.
    """
    container = _find_container(slug)
    name = container.name

    volume_names: list[str] = []
    if delete_volumes:
        for m in container.attrs.get("Mounts", []) or []:
            if m.get("Type") == "volume" and m.get("Name"):
                volume_names.append(m["Name"])

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


def _collect_stats(c) -> tuple[float, float]:
    """Collect CPU% and memory for a single container. Returns (cpu_pct, mem_mb)."""
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
        return cpu_pct, mem_mb
    except (KeyError, ZeroDivisionError, APIError):
        return 0.0, 0.0


def get_status() -> list[dict[str, Any]]:
    """Return live status of all known containers (labeled + image-matched).

    This is SLOW (~1-2s per container) because it calls Docker stats API.
    Use get_status_cached() for page loads; this is for background refresh.
    """
    global _status_cache, _status_cache_time

    try:
        client = _get_client()
    except RuntimeError:
        return []

    # Labeled containers (CashPilot-managed)
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
            cpu_pct, mem_mb = _collect_stats(c)
            results.append(
                {
                    "slug": slug,
                    "name": c.name,
                    "status": c.status,
                    "image": c.image.tags[0] if c.image.tags else str(c.image.short_id),
                    "cpu_percent": cpu_pct,
                    "memory_mb": mem_mb,
                    "created": c.attrs.get("Created", ""),
                    "container_id": c.short_id,
                    "deployed_by": c.labels.get(LABEL_DEPLOYED_BY, "unknown"),
                    "category": c.labels.get(LABEL_CATEGORY, ""),
                }
            )
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
                    cpu_pct, mem_mb = _collect_stats(c)
                    results.append(
                        {
                            "slug": slug,
                            "name": c.name,
                            "status": c.status,
                            "image": image_name or str(c.image.short_id),
                            "cpu_percent": cpu_pct,
                            "memory_mb": mem_mb,
                            "created": c.attrs.get("Created", ""),
                            "container_id": c.short_id,
                            "deployed_by": "external",
                            "category": "",
                        }
                    )
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
    seen_slugs: set[str] = set()

    results: list[dict[str, Any]] = []
    for c in labeled:
        try:
            seen_ids.add(c.id)
            slug = c.labels.get(LABEL_SERVICE, "unknown")
            seen_slugs.add(slug)
            results.append(
                {
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
            )
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
                if slug and slug not in seen_slugs:
                    seen_ids.add(c.id)
                    seen_slugs.add(slug)
                    results.append(
                        {
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
                    )
            except Exception as exc:
                logger.warning("Skipping corrupted container %s: %s", getattr(c, "short_id", "?"), exc)

    return results


def get_service_logs(slug: str, lines: int = 50) -> str:
    """Return the last N lines of logs for a service container."""
    container = _find_container(slug)
    return container.logs(tail=lines, timestamps=True).decode("utf-8", errors="replace")
