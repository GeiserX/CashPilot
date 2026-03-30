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


def _validate(data: dict[str, Any], path: Path) -> list[str]:
    """Return a list of validation errors (empty = OK)."""
    errors: list[str] = []
    missing = _REQUIRED_FIELDS - set(data.keys())
    if missing:
        errors.append(f"{path.name}: missing required fields: {missing}")
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
