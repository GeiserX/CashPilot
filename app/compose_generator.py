"""Generate docker-compose.yml files from CashPilot service definitions.

Allows users to export compose files for individual services or all
deployed services, so they can run them independently via Portainer,
manual `docker compose up`, or any other tooling -- without giving
CashPilot direct Docker socket access.

Generated compose files include CashPilot labels so that if the socket
IS available, CashPilot can still discover and monitor these containers.
"""

from __future__ import annotations

import re
import socket
from typing import Any

import yaml

from app.catalog import get_service, get_services
from app.constants import (
    CONTAINER_PREFIX,
    LABEL_CATEGORY,
    LABEL_DEPLOYED_BY,
    LABEL_MANAGED,
    LABEL_SERVICE,
    LABEL_VERSION,
)


def _escape_interpolation(value: str) -> str:
    """Escape ${VAR} as $${VAR} so Docker Compose treats it as literal.

    Skips already-escaped sequences ($${). Does not handle bare $VAR (without braces)
    since catalog YAML exclusively uses the braced form.
    """
    return re.sub(r"(?<!\$)\$\{", "$${", value)


def _is_named_volume(volume_str: str) -> str | None:
    """Return the volume name if the mapping uses a named volume, else None.

    Named volumes have a source that doesn't start with /, ., or ~.
    """
    source = volume_str.split(":")[0]
    if source and not source.startswith(("/", ".", "~")):
        return source
    return None


def _service_to_compose(
    svc: dict[str, Any],
    env_vars: dict[str, str] | None = None,
    hostname: str | None = None,
) -> dict[str, Any] | None:
    """Convert a single YAML service definition to a compose service block.

    Returns None if the service has no Docker image.
    """
    docker_conf = svc.get("docker", {})
    image = docker_conf.get("image")
    if not image:
        return None

    slug = svc.get("slug", svc["name"].lower().replace(" ", "-"))
    service_name = f"{CONTAINER_PREFIX}{slug}"

    category = svc.get("category", "bandwidth")

    compose_svc: dict[str, Any] = {
        "image": image,
        "container_name": service_name,
        "restart": "unless-stopped",
        "labels": {
            LABEL_MANAGED: "true",
            LABEL_SERVICE: slug,
            LABEL_VERSION: "1",
            LABEL_CATEGORY: category,
            LABEL_DEPLOYED_BY: "compose",
        },
        "logging": {
            "driver": "json-file",
            "options": {"max-size": "10m", "max-file": "3"},
        },
    }

    # Hostname
    compose_svc["hostname"] = hostname or f"cashpilot-{slug}"

    # Environment variables
    env: dict[str, str] = {}
    for var in docker_conf.get("env", []):
        key = var["key"]
        default = var.get("default", "")
        if default:
            default = default.replace("{hostname}", hostname or socket.gethostname())
        if env_vars and key in env_vars:
            env[key] = env_vars[key]
        elif default:
            env[key] = default
        elif var.get("required"):
            env[key] = f"<{var.get('label', key)}>"
    if env:
        compose_svc["environment"] = env

    # Ports
    ports = docker_conf.get("ports", [])
    if ports:
        compose_svc["ports"] = [str(p) for p in ports]

    # Volumes — escape ${VAR} interpolation in host paths
    volumes = docker_conf.get("volumes", [])
    if volumes:
        compose_svc["volumes"] = [_escape_interpolation(str(v)) for v in volumes]

    # Network mode
    network_mode = docker_conf.get("network_mode")
    if network_mode:
        compose_svc["network_mode"] = network_mode

    # Capabilities
    cap_add = docker_conf.get("cap_add")
    if cap_add:
        compose_svc["cap_add"] = cap_add

    # Command — escape ${VAR} interpolation
    command = docker_conf.get("command")
    if command:
        compose_svc["command"] = _escape_interpolation(command)

    return compose_svc


def generate_compose_single(
    slug: str,
    env_vars: dict[str, str] | None = None,
    hostname: str | None = None,
) -> str:
    """Generate a docker-compose.yml for a single service."""
    svc = get_service(slug)
    if not svc:
        raise ValueError(f"Unknown service: {slug}")

    compose_svc = _service_to_compose(svc, env_vars, hostname)
    if not compose_svc:
        raise ValueError(f"Service {slug} has no Docker image")

    compose = {
        "services": {
            f"{CONTAINER_PREFIX}{slug}": compose_svc,
        },
    }

    return _dump_compose(compose, slug)


def generate_compose_multi(
    slugs: list[str],
    env_map: dict[str, dict[str, str]] | None = None,
    hostname: str | None = None,
) -> str:
    """Generate a docker-compose.yml for multiple services."""
    services: dict[str, Any] = {}
    env_map = env_map or {}

    for slug in slugs:
        svc = get_service(slug)
        if not svc:
            continue
        compose_svc = _service_to_compose(svc, env_map.get(slug), hostname)
        if compose_svc:
            services[f"{CONTAINER_PREFIX}{slug}"] = compose_svc

    if not services:
        raise ValueError("No deployable services found")

    compose = {"services": services}
    return _dump_compose(compose, "cashpilot-services")


def generate_compose_all(
    env_map: dict[str, dict[str, str]] | None = None,
    hostname: str | None = None,
) -> str:
    """Generate a docker-compose.yml for ALL services with Docker images."""
    all_svcs = get_services()
    slugs = [s.get("slug", s["name"].lower().replace(" ", "-")) for s in all_svcs if s.get("docker", {}).get("image")]
    return generate_compose_multi(slugs, env_map, hostname)


def _dump_compose(compose: dict, name: str) -> str:
    """Serialize compose dict to YAML with a header comment."""
    # Collect named volumes from all services
    named_volumes: set[str] = set()
    for svc in compose.get("services", {}).values():
        for vol in svc.get("volumes", []):
            vol_name = _is_named_volume(vol)
            if vol_name:
                named_volumes.add(vol_name)

    if named_volumes:
        compose["volumes"] = {v: {} for v in sorted(named_volumes)}

    header = (
        f"# Generated by CashPilot for: {name}\n"
        "# https://github.com/GeiserX/CashPilot\n"
        "#\n"
        "# Replace <placeholder> values with your actual credentials.\n"
        "# Deploy with: docker compose up -d\n"
        "#\n"
        "# CashPilot labels are included so the dashboard can discover\n"
        "# and monitor these containers even without Docker socket access.\n\n"
    )
    return header + yaml.dump(
        compose,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
