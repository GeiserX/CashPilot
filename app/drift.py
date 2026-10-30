"""Does a running container still match what a redeploy would build? (UI side)

A redeploy rebuilds a container from the current catalog plus the settings this
worker's deployment was recorded with (see ``_merge_recorded_spec`` in
app/main.py). A container made before a catalog fix keeps running without it,
and nothing said so: Bitping containers ran from July to October 2026 without
NET_RAW, which the catalog added after they were made, and every probe failed
with "Operation not permitted".

``container_drift`` compares the container's shape, as the worker reads it
(``orchestrator._shape``), with what a redeploy would produce, and returns each
difference in plain words. Only differences a redeploy fixes count, so every
finding has the same remedy. The image tag of a provider image is never drift:
provider images follow their default tag on purpose. CashPilot's own images
are pinned in the catalog, so a different tag there is.
"""

from __future__ import annotations

import re
import shlex
from typing import Any

from app import arch, catalog

#: Repositories CashPilot builds itself (images/<slug>/). The catalog pins their tag.
OWN_IMAGE_PREFIX = "drumsergio/cashpilot-"


def _caps(values: Any) -> set[str]:
    return {str(cap).upper().removeprefix("CAP_") for cap in values or []}


def _device_target(spec: Any) -> str:
    """The path inside the container of a catalog device ("host[:container[:perms]]")."""
    parts = str(spec).split(":")
    return (parts[1] if len(parts) > 1 and parts[1] else parts[0]).rstrip("/")


def _volume_targets(volumes: Any) -> set[str]:
    """Mount targets of catalog volume strings or of a recorded spec's volumes dict."""
    targets: set[str] = set()
    if isinstance(volumes, dict):
        for spec in volumes.values():
            bind = str((spec or {}).get("bind") or "").rstrip("/") if isinstance(spec, dict) else ""
            if bind:
                targets.add(bind)
    elif isinstance(volumes, list):
        for mapping in volumes:
            parts = str(mapping).split(":")
            if len(parts) > 1 and parts[1]:
                targets.add(parts[1].rstrip("/"))
    return targets


def _catalog_port_keys(docker_conf: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for mapping in docker_conf.get("ports") or []:
        try:
            keys.add(catalog.parse_port(mapping)[0])
        except ValueError:
            continue
    return keys


def _split_ref(ref: str) -> tuple[str, str]:
    """repository and tag of an image reference; "latest" for no tag, "" for a bare digest."""
    ref, _, digest = ref.partition("@")
    slash = ref.rfind("/")
    colon = ref.rfind(":")
    if colon > slash:
        return ref[:colon], ref[colon + 1 :]
    return ref, "" if digest else "latest"


def _expected_command(template: str, env: dict[str, Any]) -> str:
    return re.sub(r"\$\{(\w+)\}", lambda m: str(env.get(m.group(1), m.group(0))), template)


def _same_command(a: str | None, b: str | None) -> bool:
    """Compared as Docker receives them: docker-py splits a string command with shlex."""
    try:
        return shlex.split(a or "") == shlex.split(b or "")
    except ValueError:
        return (a or "") == (b or "")


def _names(values: set[str]) -> str:
    return ", ".join(sorted(values))


def container_drift(
    svc: dict[str, Any] | None,
    shape: dict[str, Any] | None,
    recorded: dict[str, Any] | None,
    *,
    custom_image: str | None = None,
    worker_arch: str | None = None,
) -> list[str]:
    """Each way ``shape`` differs from what a redeploy on its worker would build.

    ``recorded`` is this worker's deployment record, or None for a container
    with none (made by hand, or before records were kept): then only what comes
    from the catalog alone is judged, never what a record would have decided.
    An empty list means the container matches, or that there is nothing to
    compare (an older worker sends no shape).
    """
    if not svc or not isinstance(shape, dict):
        return []
    docker_conf = svc.get("docker") or {}
    found: list[str] = []

    # Capabilities, devices and the entrypoint always come from the catalog.
    want_caps, have_caps = _caps(docker_conf.get("cap_add")), _caps(shape.get("cap_add"))
    if missing := want_caps - have_caps:
        found.append(
            f"missing {_names(missing)}, which the catalog now grants; the container was made without "
            f"{'it' if len(missing) == 1 else 'them'}"
        )
    if extra := have_caps - want_caps:
        found.append(f"still has {_names(extra)}, which the catalog no longer grants")

    want_devices = {_device_target(d) for d in docker_conf.get("devices") or []} - {""}
    if missing := want_devices - set(shape.get("devices") or []):
        found.append(f"missing device {_names(missing)}, which the catalog now passes in")
    if extra := set(shape.get("devices") or []) - want_devices:
        found.append(f"still has device {_names(extra)}, which the catalog no longer passes in")

    if shape.get("privileged") and not docker_conf.get("privileged"):
        found.append("runs privileged, which CashPilot no longer allows")

    entrypoint = docker_conf.get("entrypoint")
    if isinstance(entrypoint, list) and entrypoint and shape.get("entrypoint") != [str(p) for p in entrypoint]:
        found.append("starts with a different entrypoint than the catalog declares")

    # Network mode and ports: the record wins on a redeploy, the catalog otherwise.
    rec = recorded or {}
    network_mode = rec.get("network_mode") if "network_mode" in rec else docker_conf.get("network_mode")
    want_host = network_mode == "host"
    have_host = shape.get("network_mode") == "host"
    if want_host != have_host:
        found.append("uses its own network, but should share the host's" if want_host else "shares the host's network")
    elif not want_host:
        recorded_ports = rec.get("ports")
        want_ports = set(recorded_ports) if recorded_ports else _catalog_port_keys(docker_conf)
        if missing := want_ports - set(shape.get("ports") or []):
            found.append(f"does not publish port {_names(missing)}")

    # Mounts: a redeploy keeps the recorded ones and adds the ones the catalog gained.
    want_mounts = _volume_targets(docker_conf.get("volumes")) | _volume_targets(rec.get("volumes"))
    if missing := want_mounts - set(shape.get("mounts") or []):
        found.append(f"has no mount at {_names(missing)}, which the catalog now declares")

    # Env: the keys a redeploy always sets to something (required, or with a
    # default). A key the command template uses reaches the service on the
    # command line, so its absence from the environment changes nothing; the
    # command check below judges it.
    have_env = set(shape.get("env_keys") or [])
    in_command = set(re.findall(r"\$\{(\w+)\}", str(docker_conf.get("command") or "")))
    want_env = {
        var["key"]
        for var in docker_conf.get("env") or []
        if isinstance(var, dict)
        and var.get("key")
        and var["key"] not in in_command
        and (var.get("required") or str(var.get("default") or ""))
    }
    if missing := want_env - have_env:
        found.append(f"has no {_names(missing)} setting, which the catalog now sets")

    # The command carries credentials, so the worker never reports it. The
    # record holds the one this container was made with; a redeploy fills the
    # catalog's current template from the same recorded env.
    if recorded and "command" in recorded:
        template = docker_conf.get("command") or ""
        env = {var["key"]: var.get("default", "") for var in docker_conf.get("env") or [] if isinstance(var, dict)}
        env.update(recorded.get("env") or {})
        if not _same_command(recorded.get("command"), _expected_command(template, env) if template else ""):
            found.append("runs an older command; the catalog has changed it since")

    # CashPilot's own images are pinned, so a different tag is an image a fix
    # never reached. A different repository or digest is already reported as
    # "Outdated" by the image check, so only the tag is judged here.
    want_image = custom_image or arch.image_for(docker_conf, worker_arch) or ""
    have_image = str(shape.get("image") or "")
    if want_image.startswith(OWN_IMAGE_PREFIX) and have_image:
        w_repo, w_tag = _split_ref(want_image)
        h_repo, h_tag = _split_ref(have_image)
        if w_repo == h_repo and w_tag and h_tag and w_tag != h_tag:
            found.append(f"runs {h_repo}:{h_tag}; the catalog now pins {w_tag}")

    return found
