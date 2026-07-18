"""Service catalog loader for CashPilot.

Reads YAML service definitions from the services/ directory, validates
basic structural expectations, and caches the results in memory.
Reload on SIGHUP.
"""

from __future__ import annotations

import logging
import signal
import sys
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

SERVICES_DIR = Path(__file__).resolve().parent.parent / "services"

# In-memory cache
_services: list[dict[str, Any]] = []
_by_slug: dict[str, dict[str, Any]] = {}

# Fields every service YAML must contain
_REQUIRED_FIELDS = {"name", "slug", "category", "status", "description", "docker"}


_CATEGORIES = {"bandwidth", "depin", "storage", "compute"}
_VALID_STATUSES = {"active", "beta", "broken", "dead", "dropped"}


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

    category = data.get("category")
    if category is not None and category not in _CATEGORIES:
        errors.append(f"{path.name}: invalid category {category!r} (expected one of {sorted(_CATEGORIES)})")

    status = data.get("status")
    if status is not None and status not in _VALID_STATUSES:
        errors.append(f"{path.name}: invalid status {status!r} (expected one of {sorted(_VALID_STATUSES)})")

    docker = data.get("docker")
    if isinstance(docker, dict):
        image = docker.get("image")
        # Extension/app-only services legitimately have an empty (or absent) image —
        # they are listed but not Docker-deployable. Only reject a non-string image.
        if image is not None and not isinstance(image, str):
            errors.append(f"{path.name}: docker.image must be a string")
        env = docker.get("env")
        if env is not None and not isinstance(env, list):
            errors.append(f"{path.name}: docker.env must be a list")
        elif isinstance(env, list):
            for i, item in enumerate(env):
                key = item.get("key") if isinstance(item, dict) else None
                if not isinstance(key, str) or not key.strip():
                    errors.append(f"{path.name}: docker.env[{i}] must have a non-empty string 'key'")

    reqs = data.get("requirements")
    if isinstance(reqs, dict):
        for field in ("residential_ip", "vps_ip", "gpu"):
            if field in reqs and not isinstance(reqs[field], bool):
                errors.append(f"{path.name}: requirements.{field} must be a boolean")

    return errors


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
