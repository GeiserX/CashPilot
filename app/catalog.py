"""Service catalog loader for CashPilot.

Reads YAML service definitions from the services/ directory, validates
basic structural expectations, and caches the results in memory.
Reload on SIGHUP.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import signal
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from app import arch, ratings

logger = logging.getLogger(__name__)

SERVICES_DIR = Path(__file__).resolve().parent.parent / "services"

# In-memory cache
_services: list[dict[str, Any]] = []
_by_slug: dict[str, dict[str, Any]] = {}

# Fields every service YAML must contain
_REQUIRED_FIELDS = {"name", "slug", "category", "status", "description", "docker"}


_CATEGORIES = {"bandwidth", "depin", "storage", "compute"}
#: The keys ``docker.image_by_arch`` may use. The deploy path folds whatever a
#: worker reports (x86_64, aarch64, armv7l, ...) onto these; a key outside the
#: set could never be chosen, so it is a mistake and the entry is rejected.
IMAGE_ARCH_FAMILIES = arch.FAMILIES
_VALID_STATUSES = {"active", "beta", "broken", "dead", "dropped"}
#: The ``health_signals`` state for a provider that refuses to run the client.
ACCOUNT_DISABLED = "account_disabled"
#: Every ``health_signals`` state the readers know. Absent means failing.
HEALTH_SIGNAL_STATES = frozenset({"failing", "idle", ACCOUNT_DISABLED})

_PORT_RE = re.compile(r"(?:(?P<address>[^:]+):)?(?P<host>\d+):(?P<container>\d+)(?:/(?P<protocol>tcp|udp))?")


def parse_port(mapping: object) -> tuple[str, int | list[str | int]]:
    """One catalog port mapping as the Docker SDK's key and host binding.

    ``"9981:9981"`` gives ``("9981/tcp", 9981)``; ``"127.0.0.1:9980:9980"``
    gives ``("9980/tcp", ["127.0.0.1", 9980])``, a list because the binding
    travels to the worker as JSON. Raises ValueError saying what is wrong, so
    the loader can reject the entry and name the mistake.
    """
    raw = str(mapping).strip()
    match = _PORT_RE.fullmatch(raw)
    if not match:
        raise ValueError(
            f"port {raw!r} must be 'HOST:CONTAINER', 'ADDRESS:HOST:CONTAINER', optionally ending in /tcp or /udp"
        )
    host, container = int(match["host"]), int(match["container"])
    if not (1 <= host <= 65535 and 1 <= container <= 65535):
        raise ValueError(f"port {raw!r} is outside 1-65535")
    key = f"{container}/{match['protocol'] or 'tcp'}"
    address = match["address"]
    if address is None:
        return key, host
    try:
        ipaddress.IPv4Address(address)
    except ValueError:
        raise ValueError(f"port {raw!r} must bind to an IPv4 address, not {address!r}") from None
    return key, [address, host]


#: Capabilities that reach a network namespace's firewall, routes and
#: interfaces (SYS_ADMIN reaches far more). Held in the host's namespace they
#: rewrite the host firewall, the LAN fence included, so a service asking for
#: one must run in a namespace of its own and on an image named exactly.
NETNS_CAPABILITIES = frozenset({"NET_ADMIN", "SYS_ADMIN"})

#: The most UDP ports one udp_port_range may publish. Each published port is a
#: rule and, with Docker's userland proxy, a process on the host, and each one
#: slows the container's start. Measured on a live node (Nov 2026): 300 ports
#: start in about 12 s, about 350 take 30 s, where the socket proxy stops
#: waiting for Docker's answer, and 1,000 take about 51 s. 300 keeps a deploy's
#: start well inside the proxy's 30 s on a slower host too.
MAX_UDP_PORTS = 300


def is_port_range(value: str) -> bool:
    """A blank value, or "start:end" with 1 <= start <= end <= 65535.

    A pattern can check the shape but not the order, and Mysterium refuses to
    start on a reversed or out-of-range --udp.ports, so the node stops earning.
    """
    if not value:
        return True
    start, sep, end = value.partition(":")
    if not (sep and start.isascii() and start.isdigit() and end.isascii() and end.isdigit()):
        return False
    return 1 <= int(start) <= int(end) <= 65535


def expand_udp_range(value: str, cap: int = MAX_UDP_PORTS) -> dict[str, int]:
    """``"56000:56100"`` as Docker port bindings published 1:1: ``{"56000/udp": 56000, ...}``.

    A NAT traversal range only works when each port reaches the same port in
    the container. Raises ValueError for a value that is not a range, a
    reversed one, or one wider than ``cap``. A blank value publishes nothing.
    """
    value = str(value or "").strip()
    if not value:
        return {}
    if not is_port_range(value):
        raise ValueError(f"{value!r} is not a port range start:end with start <= end <= 65535")
    start, _, end = value.partition(":")
    first, last = int(start), int(end)
    if last - first + 1 > cap:
        raise ValueError(
            f"{value!r} spans {last - first + 1} ports; at most {cap} can be published, since every published "
            f"port slows the container's start and a wider range runs past what a deploy can wait for. Choose a "
            f"range of {cap} ports or fewer, such as {first}:{min(first + cap - 1, 65535)}, and forward the same "
            "range on your router"
        )
    return {f"{port}/udp": port for port in range(first, last + 1)}


def ui_bindings(value: str, port: int) -> list[list[str | int]]:
    """``[[address, port], ...]`` for each address in a comma-separated list.

    ``localhost`` becomes 127.0.0.1, since Docker binds addresses, not names.
    Raises ValueError for anything that is not an IPv4 address.
    """
    found: list[list[str | int]] = []
    for raw in str(value or "").split(","):
        address = raw.strip()
        if not address:
            continue
        if address == "localhost":
            address = "127.0.0.1"
        try:
            ipaddress.IPv4Address(address)
        except ValueError:
            raise ValueError(f"{address!r} is not an IPv4 address") from None
        if [address, port] not in found:
            found.append([address, port])
    return found


def fence_gated(svc: dict[str, Any] | None) -> bool:
    """Whether the worker starts this service only behind a confirmed LAN fence."""
    return bool(((svc or {}).get("docker") or {}).get("fence_gated") is True)


def _validate_network_shape(docker: dict[str, Any], name: str) -> list[str]:
    """The keys that decide where a service's network namespace lives."""
    errors: list[str] = []
    env_vars = {v.get("key"): v for v in docker.get("env") or [] if isinstance(v, dict)}
    rng = docker.get("udp_port_range")
    if rng is not None:
        if not isinstance(rng, dict) or not isinstance(rng.get("env"), str):
            errors.append(f"{name}: docker.udp_port_range must be a mapping with an env key")
        else:
            var = env_vars.get(rng["env"])
            if not var or var.get("port_range") is not True:
                errors.append(f"{name}: docker.udp_port_range.env must name a docker.env key with port_range: true")
            cap = rng.get("max_ports", MAX_UDP_PORTS)
            if isinstance(cap, bool) or not isinstance(cap, int) or not 1 <= cap <= MAX_UDP_PORTS:
                errors.append(f"{name}: docker.udp_port_range.max_ports must be 1 to {MAX_UDP_PORTS}")
            elif var and str(var.get("default") or ""):
                try:
                    expand_udp_range(str(var["default"]), cap)
                except ValueError as exc:
                    errors.append(f"{name}: docker.udp_port_range default: {exc}")
    ui = docker.get("ui_port")
    if ui is not None:
        port = ui.get("port") if isinstance(ui, dict) else None
        if (
            not isinstance(ui, dict)
            or ui.get("env") not in env_vars
            or isinstance(port, bool)
            or not isinstance(port, int)
            or not 1 <= port <= 65535
        ):
            errors.append(f"{name}: docker.ui_port must name a docker.env key and a port 1-65535")
    if "fence_gated" in docker and not isinstance(docker["fence_gated"], bool):
        errors.append(f"{name}: docker.fence_gated must be a boolean")
    runtime = docker.get("runtime")
    if runtime is not None and (not isinstance(runtime, str) or not runtime.strip()):
        errors.append(f"{name}: docker.runtime must be a runtime name")
    caps = {str(c).upper().removeprefix("CAP_") for c in docker.get("cap_add") or []}
    if held := sorted(caps & NETNS_CAPABILITIES):
        # The threat class this rule closes: a container with these in the host's
        # namespace can rewrite the host firewall, the LAN fence included, and
        # no host rule holds against it. Mysterium ran that way through 2.0.6.
        if str(docker.get("network_mode") or "").strip().lower() == "host":
            errors.append(
                f"{name}: a service with {', '.join(held)} cannot use network_mode: host; it would hold them "
                "in the host's network namespace"
            )
        images = [docker.get("image")] + list((docker.get("image_by_arch") or {}).values())
        if not all(isinstance(i, str) and re.search(r"@sha256:[0-9a-f]{64}$", i) for i in images if i):
            errors.append(f"{name}: a service with {', '.join(held)} must pin its image by @sha256: digest")
        if docker.get("fence_gated") is not True:
            errors.append(f"{name}: a service with {', '.join(held)} must be fence_gated: true")
    return errors


def _validate(data: dict[str, Any], path: Path) -> list[str]:
    """Return a list of validation errors (empty = OK).

    A service with ANY error is skipped at load (it silently disappears from the
    UI), so these checks only assert invariants every real entry already satisfies
    — they exist to catch a malformed NEW entry, not to drop valid ones.
    """
    errors: list[str] = []
    missing = _REQUIRED_FIELDS - set(data.keys())
    if missing:
        errors.append(f"{path.name}: missing required fields: {missing}")

    slug = data.get("slug")
    if isinstance(slug, str) and slug.startswith("custom-"):
        # Reserved for services users add themselves (app/custom_services.py):
        # a catalog entry with such a slug would take over a user's service and
        # hand it whatever capabilities the entry declares.
        errors.append(f"{path.name}: slug {slug!r} uses the reserved 'custom-' prefix")

    category = data.get("category")
    if category is not None and category not in _CATEGORIES:
        errors.append(f"{path.name}: invalid category {category!r} (expected one of {sorted(_CATEGORIES)})")

    status = data.get("status")
    if status is not None and status not in _VALID_STATUSES:
        errors.append(f"{path.name}: invalid status {status!r} (expected one of {sorted(_VALID_STATUSES)})")

    disclosure = data.get("disclosure")
    if disclosure is not None and not isinstance(disclosure, dict):
        # `disclosure: TODO` loaded fine and then 500'd the endpoint at request
        # time, so the fault was invisible until someone opened that one service.
        errors.append(f"{path.name}: disclosure must be a mapping, not {type(disclosure).__name__}")

    if "rating" in data:
        # The grade is computed from these verdicts (app/ratings.py). The rating
        # is a display field, so a bad block (a typed grade, an override, a
        # sponsor field, a typo) makes the provider "Not rated yet" instead of
        # dropping a working service. The date-versus-today check is skipped
        # here because a box with its clock behind would drop every block
        # reviewed today. CI fails on both: scripts/generate_ratings_page.py --check.
        rating_errors = ratings.validate(data["rating"], data, check_future=False)
        if rating_errors:
            for err in rating_errors:
                logger.warning("Validation: %s: %s (shown as not rated)", path.name, err)
            del data["rating"]

    docker = data.get("docker")
    if isinstance(docker, dict):
        image = docker.get("image")
        # Extension/app-only services legitimately have an empty (or absent) image —
        # they are listed but not Docker-deployable. Only reject a non-string image.
        if image is not None and not isinstance(image, str):
            errors.append(f"{path.name}: docker.image must be a string")
        by_arch = docker.get("image_by_arch")
        if by_arch is not None and (
            not isinstance(by_arch, dict)
            or not all(k in IMAGE_ARCH_FAMILIES and isinstance(v, str) for k, v in by_arch.items())
        ):
            errors.append(
                f"{path.name}: docker.image_by_arch must map an architecture family "
                f"({', '.join(sorted(IMAGE_ARCH_FAMILIES))}) to an image string"
            )
        # A bare `ports:` loads as None, and the deploy iterates these three
        # without a fallback, so a present key must hold a list.
        for field in ("env", "ports", "volumes"):
            if field in docker and not isinstance(docker[field], list):
                errors.append(f"{path.name}: docker.{field} must be a list")
        env = docker.get("env")
        if isinstance(env, list):
            for i, item in enumerate(env):
                key = item.get("key") if isinstance(item, dict) else None
                if not isinstance(key, str) or not key.strip():
                    errors.append(f"{path.name}: docker.env[{i}] must have a non-empty string 'key'")
                pattern = item.get("pattern") if isinstance(item, dict) else None
                if pattern is not None:
                    try:
                        re.compile(pattern)
                    except (re.error, TypeError):
                        errors.append(f"{path.name}: docker.env[{i}].pattern must be a valid regular expression")
                if isinstance(item, dict) and "per_device" in item and not isinstance(item["per_device"], bool):
                    errors.append(f"{path.name}: docker.env[{i}].per_device must be a boolean")
        signals = docker.get("health_signals")
        if isinstance(signals, list):
            for i, item in enumerate(signals):
                if not isinstance(item, dict):
                    continue
                state = item.get("state")
                if state is not None:
                    if not isinstance(state, str) or state.strip().lower() not in HEALTH_SIGNAL_STATES:
                        errors.append(
                            f"{path.name}: docker.health_signals[{i}].state must be one of "
                            f"{', '.join(sorted(HEALTH_SIGNAL_STATES))}, got {state!r}"
                        )
                        continue
                    # The one place the case is normalised: every reader
                    # compares the lowercase name.
                    item["state"] = state.strip().lower()
                if item.get("state") != ACCOUNT_DISABLED:
                    continue
                # The worker judges this one on a stopped container's tail.
                pattern = item.get("pattern")
                try:
                    if not isinstance(pattern, str) or not pattern.strip():
                        raise TypeError
                    re.compile(pattern)
                except (re.error, TypeError):
                    errors.append(
                        f"{path.name}: docker.health_signals[{i}].pattern must be a non-empty regular expression"
                    )
                if item.get("window_hours"):
                    errors.append(
                        f"{path.name}: docker.health_signals[{i}]: state account_disabled cannot have window_hours"
                    )
        ports = docker.get("ports")
        if isinstance(ports, list):
            # A bad mapping used to load fine and then 500 the deploy, on
            # int("127.0.0.1") or an empty host port. Two mappings of one
            # container port collapse into one binding at deploy, so the later
            # one would silently replace a loopback bind with a public one.
            seen: dict[str, int] = {}
            for i, mapping in enumerate(ports):
                try:
                    key, _binding = parse_port(mapping)
                except ValueError as exc:
                    errors.append(f"{path.name}: docker.ports[{i}]: {exc}")
                    continue
                if key in seen:
                    errors.append(
                        f"{path.name}: docker.ports[{i}] maps container port {key} again "
                        f"(already docker.ports[{seen[key]}])"
                    )
                seen.setdefault(key, i)
        errors.extend(_validate_network_shape(docker, path.name))

    reqs = data.get("requirements")
    if isinstance(reqs, dict):
        for field in ("residential_ip", "vps_ip", "gpu"):
            if field in reqs and not isinstance(reqs[field], bool):
                errors.append(f"{path.name}: requirements.{field} must be a boolean")

    link = data.get("device_link")
    if link is not None:
        # The id is shown on screen and put in a link, so it must be a value the
        # catalog already treats as public: a declared, non-secret env var.
        env_vars = (docker.get("env") if isinstance(docker, dict) else None) or []
        # A key declared secret anywhere is secret, even if declared twice.
        declared = [v for v in env_vars if isinstance(v, dict)]
        public = {v.get("key") for v in declared} - {v.get("key") for v in declared if v.get("secret")}
        url = str(link.get("url") or "") if isinstance(link, dict) else ""
        if not isinstance(link, dict) or link.get("id_env") not in public:
            errors.append(f"{path.name}: device_link.id_env must name a non-secret docker.env key")
        elif link["id_env"] not in {v.get("key") for v in declared if v.get("per_device") is True}:
            # Copies through a proxy derive their own id only from marked keys.
            errors.append(f"{path.name}: device_link.id_env must be marked per_device: true")
        elif not isinstance(link.get("steps"), str) or not link["steps"].strip():
            errors.append(f"{path.name}: device_link.steps must say what to do with the id")
        elif url and not url.startswith("https://"):
            errors.append(f"{path.name}: device_link.url must be an https:// link")
        elif not set(re.findall(r"\$\{(\w+)\}", url)) <= public:
            errors.append(f"{path.name}: device_link.url may only fill in non-secret docker.env keys")

    support = data.get("support_url")
    if support is not None and (not isinstance(support, str) or not support.startswith("https://")):
        errors.append(f"{path.name}: support_url must be an https:// link")

    priority = data.get("priority")
    if priority is not None and (isinstance(priority, bool) or not isinstance(priority, int) or priority < 1):
        errors.append(f"{path.name}: priority must be a positive integer (1 first), got {priority!r}")

    return errors


def priority_key(service: dict[str, Any]) -> tuple[bool, int]:
    """Sort key that puts prioritised entries first, lowest number first.

    Everything without a priority sorts after them and keeps whatever order it
    already had (the sort is stable), so a reorder never touches the rest.
    """
    priority = service.get("priority")
    return (priority is None, priority if isinstance(priority, int) else 0)


def _load_from_disk() -> list[dict[str, Any]]:
    """Walk services/ recursively and parse all .yml/.yaml files."""
    services: list[dict[str, Any]] = []
    if not SERVICES_DIR.is_dir():
        logger.warning("Services directory not found: %s", SERVICES_DIR)
        return services

    for path in sorted(SERVICES_DIR.rglob("*.yml")):
        # Skip the schema reference file
        if path.name.startswith("_"):
            continue
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            logger.error("Failed to parse %s: %s", path, exc)
            continue

        if not isinstance(data, dict):
            logger.error("Expected a mapping in %s, got %s", path, type(data).__name__)
            continue

        errors = _validate(data, path)
        if errors:
            for err in errors:
                logger.warning("Validation: %s", err)
            continue
        services.append(data)

    # Also pick up .yaml extension
    for path in sorted(SERVICES_DIR.rglob("*.yaml")):
        if path.name.startswith("_"):
            continue
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            logger.error("Failed to parse %s: %s", path, exc)
            continue
        if isinstance(data, dict):
            errors = _validate(data, path)
            if errors:
                for err in errors:
                    logger.warning("Validation: %s", err)
                continue
            services.append(data)

    services.sort(key=priority_key)
    return services


def load_services() -> list[dict[str, Any]]:
    """Load (or reload) all service definitions and return them."""
    global _services, _by_slug
    _services = _load_from_disk()
    _by_slug = {s["slug"]: s for s in _services}
    logger.info("Loaded %d service(s) from %s", len(_services), SERVICES_DIR)
    return _services


def get_services() -> list[dict[str, Any]]:
    """Return shallow copies of cached services (safe to mutate per-request)."""
    if not _services:
        load_services()
    return [dict(s) for s in _services]


def get_services_by_category() -> dict[str, list[dict[str, Any]]]:
    """Return services grouped by category."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for svc in get_services():
        cat = svc.get("category", "other")
        grouped.setdefault(cat, []).append(svc)
    return grouped


def get_service(slug: str) -> dict[str, Any] | None:
    """Look up a single service by slug (returns a shallow copy)."""
    if not _by_slug:
        load_services()
    svc = _by_slug.get(slug)
    return dict(svc) if svc else None


def _sighup_handler(signum: int, frame: Any) -> None:
    logger.info("Received SIGHUP — reloading service catalog")
    load_services()


def register_sighup() -> None:
    """Register SIGHUP handler for catalog reload (Unix only)."""
    if sys.platform != "win32":
        signal.signal(signal.SIGHUP, _sighup_handler)


def critical_volume_targets(slug: str) -> dict[str, str] | None:
    """Return {container_path: why_it_matters} for a service's irreplaceable mounts.

    Returns ``None`` when criticality cannot be determined at all — an unknown
    slug, or a build whose image does not ship the catalog. Callers must treat
    ``None`` as "unsafe to destroy", not as "nothing is critical": silently
    allowing deletion because the catalog was missing is exactly the kind of
    fail-open this guard exists to prevent. An empty dict means the catalog was
    read and the service genuinely declares nothing critical.
    """
    svc = get_service(slug)
    if svc is None:
        return None
    docker = svc.get("docker") or {}
    entries = docker.get("critical_volumes") or []
    targets: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        target = entry.get("target")
        if target:
            targets[str(target)] = str(entry.get("holds") or "Irreplaceable service state.")
    return targets


def device_link_step(svc: dict[str, Any], env: dict[str, Any]) -> dict[str, str] | None:
    """What the user must do so a deployed device earns for their account.

    Some providers create the device id on the machine and pay nobody until
    the user adds it to their account (EarnApp, ProxyRack). Returns the id, the
    link with the id filled in, and the steps, from the service's ``device_link``
    block and the env the container was deployed with; None when the service
    needs no linking or the env has no id.
    """
    link = svc.get("device_link")
    if not isinstance(link, dict):
        return None
    device_id = str(env.get(link.get("id_env"), "") or "").strip()
    if not device_id:
        return None
    url = str(link.get("url") or "")
    url = re.sub(r"\$\{(\w+)\}", lambda m: quote(str(env.get(m.group(1), "")), safe=""), url)
    return {"id": device_id, "url": url, "steps": str(link["steps"]).strip()}


def vps_allowed(requirements: dict[str, Any] | None) -> bool | None:
    """Whether a VPS is permitted, applying the schema's documented default.

    ``services/_schema.yml`` states that ``vps_ip`` defaults to the opposite of
    ``residential_ip``. Two consumers read this one fact and disagreed:
    ``scripts/generate_readme_tables.py`` applied the default (so the catalog
    page tells the user "VPS not allowed"), while ``app/preflight.py`` tested
    ``reqs.get("vps_ip") is False`` — demanding the literal boolean, so an
    absent key never entered the branch and 21 services that the docs describe
    as residential-only produced no warning at all before a deploy onto a
    hosting worker.

    Returns None when neither field is set: unknown, not permitted.
    """
    reqs = requirements or {}
    if reqs.get("vps_ip") is not None:
        return bool(reqs["vps_ip"])
    residential = reqs.get("residential_ip")
    return None if residential is None else not residential
