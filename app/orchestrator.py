"""Docker container orchestrator for CashPilot.

Manages lifecycle (deploy, stop, restart, remove) and status inspection
for cashpilot-managed containers via the Docker SDK.

CashPilot operates in two modes:
  - **Direct mode**: Docker socket is mounted. Full container management
    (deploy, stop, restart, remove) and live monitoring.
  - **Monitor-only mode**: No Docker socket. CashPilot functions as a
    dashboard for earnings tracking and service catalog only. Container
    management endpoints return 503 with a clear message.
"""

from __future__ import annotations

import logging
import re
import socket
from typing import Any

import docker
from docker.errors import APIError, DockerException, NotFound

try:
    from app.catalog import get_service
except ImportError:
    # Worker image doesn't include catalog module
    get_service = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

LABEL_SERVICE = "cashpilot.service"
LABEL_MANAGED = "cashpilot.managed"
LABEL_VERSION = "cashpilot.version"
LABEL_CATEGORY = "cashpilot.category"
LABEL_DEPLOYED_BY = "cashpilot.deployed-by"
CONTAINER_PREFIX = "cashpilot-"

# Cached Docker availability (checked once at startup, refreshed on demand)
_docker_available: bool | None = None


def docker_available() -> bool:
    """Check whether the Docker socket is accessible. Result is cached."""
    global _docker_available
    if _docker_available is None:
        try:
            client = docker.from_env()
            client.ping()
            _docker_available = True
            client.close()
        except Exception:
            _docker_available = False
    return _docker_available


def reset_docker_status() -> None:
    """Force re-check of Docker availability on next call."""
    global _docker_available
    _docker_available = None


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


def deploy_service(
    slug: str,
    env_vars: dict[str, str] | None = None,
    hostname: str | None = None,
) -> str:
    """Create and start a container for the given service slug.

    Args:
        slug: Service identifier (must exist in catalog).
        env_vars: User-provided environment variables (override defaults).
        hostname: Optional container hostname.

    Returns:
        Container ID.
    """
    svc = get_service(slug)
    if not svc:
        raise ValueError(f"Unknown service: {slug}")

    docker_conf = svc.get("docker", {})
    image = docker_conf.get("image")
    if not image:
        raise ValueError(f"Service {slug} has no Docker image defined")

    client = _get_client()
    name = _container_name(slug)

    # Remove any existing container with the same name
    try:
        old = client.containers.get(name)
        logger.info("Removing existing container %s", name)
        old.remove(force=True)
    except NotFound:
        pass

    # Build environment: defaults from YAML + user overrides
    env: dict[str, str] = {}
    for var in docker_conf.get("env", []):
        default = var.get("default", "")
        if default:
            # Substitute {hostname} placeholder
            default = default.replace("{hostname}", hostname or socket.gethostname())
            env[var["key"]] = default
    if env_vars:
        env.update(env_vars)

    # Ports: list of "host:container" strings
    ports: dict[str, int] = {}
    for mapping in docker_conf.get("ports", []):
        if ":" in str(mapping):
            container_port, host_port = str(mapping).split(":", 1)
            ports[container_port] = int(host_port)

    # Volumes: list of "host:container" strings
    volumes: dict[str, dict[str, str]] = {}
    for mapping in docker_conf.get("volumes", []):
        if ":" in str(mapping):
            parts = str(mapping).split(":")
            host_path = parts[0]
            container_path = parts[1]
            mode = parts[2] if len(parts) > 2 else "rw"
            volumes[host_path] = {"bind": container_path, "mode": mode}

    # Optional settings
    network_mode = docker_conf.get("network_mode") or None
    cap_add = docker_conf.get("cap_add") or None
    privileged = docker_conf.get("privileged", False)

    # Command: resolve ${VAR} placeholders from env dict
    raw_command = docker_conf.get("command") or None
    command = None
    if raw_command:
        resolved = re.sub(
            r"\$\{(\w+)\}",
            lambda m: env.get(m.group(1), m.group(0)),
            raw_command,
        )
        command = resolved

    labels = {
        LABEL_SERVICE: slug,
        LABEL_MANAGED: "true",
        LABEL_VERSION: "1",
        LABEL_CATEGORY: svc.get("category", "bandwidth"),
        LABEL_DEPLOYED_BY: "direct",
    }

    logger.info("Pulling image %s", image)
    try:
        client.images.pull(image)
    except APIError as exc:
        logger.warning("Failed to pull image %s: %s (trying local)", image, exc)

    logger.info("Creating container %s from %s", name, image)
    container = client.containers.run(
        image=image,
        name=name,
        environment=env,
        ports=ports if ports and network_mode != "host" else None,
        volumes=volumes if volumes else None,
        network_mode=network_mode,
        cap_add=cap_add,
        privileged=privileged,
        command=command if command else None,
        labels=labels,
        hostname=hostname or f"cashpilot-{slug}",
        detach=True,
        restart_policy={"Name": "unless-stopped"},
    )

    logger.info("Container %s started: %s", name, container.short_id)
    return container.id


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
    category: str = "bandwidth",
) -> str:
    """Deploy a container from a raw spec (no catalog lookup).

    Used by CashPilot Worker when the UI sends a full container spec.
    Returns the container ID.
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
    )

    logger.info("Container %s started: %s", name, container.short_id)
    return container.id


def stop_service(slug: str) -> None:
    """Stop the container for a service."""
    container = _find_container(slug)
    container.stop(timeout=30)
    logger.info("Stopped container %s", container.name)


def restart_service(slug: str) -> None:
    """Restart the container for a service."""
    container = _find_container(slug)
    container.restart(timeout=30)
    logger.info("Restarted container %s", container.name)


def remove_service(slug: str) -> None:
    """Stop and remove the container for a service."""
    container = _find_container(slug)
    container.remove(force=True)
    logger.info("Removed container %s", container.name)


def start_service(slug: str) -> None:
    """Start a stopped container for a service."""
    container = _find_container(slug)
    container.start()
    logger.info("Started container %s", container.name)


def get_status() -> list[dict[str, Any]]:
    """Return status of all cashpilot-managed containers."""
    try:
        client = _get_client()
    except RuntimeError:
        return []

    containers = client.containers.list(
        all=True,
        filters={"label": f"{LABEL_MANAGED}=true"},
    )

    results: list[dict[str, Any]] = []
    for c in containers:
        slug = c.labels.get(LABEL_SERVICE, "unknown")
        # Gather resource stats (non-streaming)
        cpu_pct = 0.0
        mem_mb = 0.0
        try:
            stats = c.stats(stream=False)
            # CPU %
            cpu_delta = (
                stats["cpu_stats"]["cpu_usage"]["total_usage"] - stats["precpu_stats"]["cpu_usage"]["total_usage"]
            )
            system_delta = stats["cpu_stats"]["system_cpu_usage"] - stats["precpu_stats"]["system_cpu_usage"]
            num_cpus = stats["cpu_stats"].get(
                "online_cpus",
                len(stats["cpu_stats"]["cpu_usage"].get("percpu_usage", [1])),
            )
            if system_delta > 0:
                cpu_pct = round((cpu_delta / system_delta) * num_cpus * 100, 2)

            # Memory
            mem_usage = stats["memory_stats"].get("usage", 0)
            mem_mb = round(mem_usage / (1024 * 1024), 1)
        except (KeyError, ZeroDivisionError, APIError):
            pass

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

    return results


def get_service_logs(slug: str, lines: int = 50) -> str:
    """Return the last N lines of logs for a service container."""
    container = _find_container(slug)
    return container.logs(tail=lines, timestamps=True).decode("utf-8", errors="replace")
