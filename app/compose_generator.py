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

from app import arch as arch_mod
from app.catalog import get_service, get_services
from app.constants import (
    CONTAINER_PREFIX,
    LABEL_CATEGORY,
    LABEL_DEPLOYED_BY,
    LABEL_MANAGED,
    LABEL_SERVICE,
    LABEL_VERSION,
    UNDEPLOYABLE_STATUSES,
)

#: What the worker gives a service that declares no stop_timeout (see
#: orchestrator._parse_stop_timeout); the export must not give it less.
_DEFAULT_STOP_GRACE = 30


def _escape_interpolation(value: str) -> str:
    """Escape ${VAR} as $${VAR} so Docker Compose treats it as literal.

    Skips already-escaped sequences ($${). Does not handle bare $VAR (without braces)
    since catalog YAML exclusively uses the braced form.
    """
    return re.sub(r"(?<!\$)\$\{", "$${", value)


def _escape_value(value: str) -> str:
    """Escape every $ in a substituted value so Compose keeps it literal.

    Compose interpolates $VAR and ${VAR} in unquoted and double-quoted YAML
    values, so a credential like ``tok$word`` written into the file verbatim
    silently CHANGES when the exported file runs. $$ is the spec's literal form.
    """
    return value.replace("$", "$$")


def _substitute_env(value: str, env: dict[str, str]) -> str:
    """Fill ${KEY} placeholders from the emitted environment map.

    The catalog uses ${KEY} in `command` and volume host paths to mean "the value
    of this service's KEY variable" — and the worker deploy path substitutes them
    (app/main.py api_deploy). The exporter used to only ESCAPE them instead, so an
    exported honeygain/iproyal/traffmonetizer/packetstream/proxybase file ran the
    client with the literal eight characters "${EMAIL}" as its credentials: a file
    that could never authenticate, silently. Placeholders with no corresponding
    entry (proxyrack's ${UUID}) are left for _escape_interpolation, preserving the
    old template behavior for values CashPilot does not hold. Inserted values are
    $-escaped so a credential containing a dollar sign survives Compose's own
    interpolation pass.
    """
    return re.sub(r"\$\{(\w+)\}", lambda m: _escape_value(env[m.group(1)]) if m.group(1) in env else m.group(0), value)


def _is_named_volume(volume_str: str) -> str | None:
    """Return the volume name if the mapping uses a named volume, else None.

    Named volumes have a source that doesn't start with /, ., or ~. A source
    that starts with $ is a host path Compose fills in from the environment
    (see _volume_mapping), never a volume name.
    """
    source = volume_str.split(":")[0]
    if source and not source.startswith(("/", ".", "~", "$")):
        return source
    return None


def _volume_mapping(volume: str, env: dict[str, str], unfilled: dict[str, str]) -> str:
    """One volume line for the export: known values filled, missing paths required."""

    def fill(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in unfilled:
            # No "}" or "$" in the message: it sits inside Compose's own ${...}.
            label = re.sub(r"[}$]", "", unfilled[key])
            return f"${{{key}:?set {key} to the host directory for {label}, in .env or the shell}}"
        if key in env:
            return _escape_value(env[key])
        return "$$" + match.group(0)[1:]

    return re.sub(r"\$\{(\w+)\}", fill, volume)


def _service_to_compose(
    svc: dict[str, Any],
    env_vars: dict[str, str] | None = None,
    hostname: str | None = None,
    arch: str | None = None,
) -> dict[str, Any] | None:
    """Convert a single YAML service definition to a compose service block.

    Returns None if the service has no Docker image. ``arch`` names the box the
    file is for (amd64, arm64, arm); an entry with a per-architecture image gets
    that build, everything else is unchanged. The export has no worker to ask,
    so the caller has to say.
    """
    docker_conf = svc.get("docker", {})
    image = arch_mod.image_for(docker_conf, arch) if arch else docker_conf.get("image")
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
    # Required values nobody supplied: the file carries a placeholder for them.
    unfilled: dict[str, str] = {}
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
            unfilled[key] = str(var.get("label", key))
    if env:
        # $-escaped at emission: Compose interpolates inside environment values
        # too, so a stored password containing $ would otherwise change (or
        # error) when the exported file runs. The raw map stays unescaped — it
        # is also the substitution source for command/volumes, which escape at
        # their own emission point.
        compose_svc["environment"] = {key: _escape_value(value) for key, value in env.items()}

    # Ports
    ports = docker_conf.get("ports", [])
    if ports:
        compose_svc["ports"] = [str(p) for p in ports]

    # Volumes — fill ${VAR} host paths from known values, escape whatever remains.
    #
    # A path nobody supplied cannot take the "<Label>" placeholder the environment
    # block uses: as a host path it reads as a named volume, the file declares a
    # volume called "<Identity directory>", and Compose rejects the whole file with
    # an error that names neither setting. It becomes ${KEY:?...} instead, which
    # Compose fills from the user's .env or shell, and refuses to run without,
    # naming the variable.
    volumes = docker_conf.get("volumes", [])
    if volumes:
        compose_svc["volumes"] = [_volume_mapping(str(v), env, unfilled) for v in volumes]

    # Network mode
    network_mode = docker_conf.get("network_mode")
    if network_mode:
        compose_svc["network_mode"] = network_mode

    # Capabilities
    cap_add = docker_conf.get("cap_add")
    if cap_add:
        compose_svc["cap_add"] = cap_add

    # Entrypoint override. EVERY $ is escaped, not just ${VAR}: a shell wrapper
    # uses bare $F and $@, and Compose would fill those from the host's
    # environment (empty), silently breaking the script. Nothing in an
    # entrypoint is meant for Compose to substitute.
    entrypoint = docker_conf.get("entrypoint")
    if isinstance(entrypoint, list) and entrypoint:
        compose_svc["entrypoint"] = [_escape_value(str(part)) for part in entrypoint]

    # The stop grace the worker gives the same service: the catalog's, or 30
    # seconds when it declares none or something unusable (orchestrator's
    # _parse_stop_timeout). Leaving the key out gave the exported container
    # Docker's 10 seconds instead, shorter than a deployed one gets.
    stop_timeout = docker_conf.get("stop_timeout")
    try:
        grace = int(stop_timeout)
    except (TypeError, ValueError):
        grace = 0
    compose_svc["stop_grace_period"] = f"{grace if grace > 0 else _DEFAULT_STOP_GRACE}s"

    # Command — fill ${VAR} credentials from known values, escape whatever remains
    command = docker_conf.get("command")
    if command:
        compose_svc["command"] = _escape_interpolation(_substitute_env(command, env))

    # Durable resource limits. Compose accepts these as top-level service keys
    # under the same names the catalog uses; dropping them exported a container
    # WITHOUT its memory ceiling, OOM bias or CPU weight — silently less
    # protected than the same service deployed by the worker (CashPilot-65q4).
    # Only keys the catalog actually sets are emitted; absent stays absent.
    resources = docker_conf.get("resources") or {}
    if isinstance(resources, dict):
        for key in ("mem_limit", "mem_reservation", "cpu_shares", "oom_score_adj"):
            value = resources.get(key)
            if value is not None:
                compose_svc[key] = value

    return compose_svc


def generate_compose_single(
    slug: str,
    env_vars: dict[str, str] | None = None,
    hostname: str | None = None,
    arch: str | None = None,
) -> str:
    """Generate a docker-compose.yml for a single service."""
    svc = get_service(slug)
    if not svc:
        raise ValueError(f"Unknown service: {slug}")
    if svc.get("status") in UNDEPLOYABLE_STATUSES:
        # A compose file for a dead service is a runnable artifact pointing at
        # something that cannot earn — the export must refuse like the deploy
        # route does, not hand the user a working-looking YAML.
        raise ValueError(f"Service {slug} is no longer available ({svc.get('status')})")

    compose_svc = _service_to_compose(svc, env_vars, hostname, arch)
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
    arch: str | None = None,
) -> str:
    """Generate a docker-compose.yml for multiple services."""
    services: dict[str, Any] = {}
    env_map = env_map or {}

    for slug in slugs:
        svc = get_service(slug)
        if not svc:
            continue
        if svc.get("status") in UNDEPLOYABLE_STATUSES:
            continue
        compose_svc = _service_to_compose(svc, env_map.get(slug), hostname, arch)
        if compose_svc:
            services[f"{CONTAINER_PREFIX}{slug}"] = compose_svc

    if not services:
        raise ValueError("No deployable services found")

    compose = {"services": services}
    return _dump_compose(compose, "cashpilot-services")


def generate_compose_all(
    env_map: dict[str, dict[str, str]] | None = None,
    hostname: str | None = None,
    arch: str | None = None,
) -> str:
    """Generate a docker-compose.yml for ALL services with Docker images."""
    all_svcs = get_services()
    slugs = [s.get("slug", s["name"].lower().replace(" ", "-")) for s in all_svcs if s.get("docker", {}).get("image")]
    return generate_compose_multi(slugs, env_map, hostname, arch)


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
