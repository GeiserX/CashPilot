"""Collector registry for CashPilot.

Maps service slugs to their collector classes and provides a factory
to instantiate collectors for all currently deployed services.
"""

from __future__ import annotations

import logging
from typing import Any

from app.collectors.base import BaseCollector, EarningsResult
from app.collectors.earnapp import EarnAppCollector
from app.collectors.honeygain import HoneygainCollector
from app.collectors.iproyal import IPRoyalCollector
from app.collectors.mystnodes import MystNodesCollector
from app.collectors.storj import StorjCollector
from app.collectors.traffmonetizer import TraffmonetizerCollector

logger = logging.getLogger(__name__)

# slug -> collector class
COLLECTOR_MAP: dict[str, type[BaseCollector]] = {
    "honeygain": HoneygainCollector,
    "earnapp": EarnAppCollector,
    "iproyal": IPRoyalCollector,
    "mysterium": MystNodesCollector,
    "storj": StorjCollector,
    "traffmonetizer": TraffmonetizerCollector,
}

# Map of slug -> list of config keys needed to instantiate the collector
_COLLECTOR_ARGS: dict[str, list[str]] = {
    "honeygain": ["email", "password"],
    "earnapp": ["oauth_token"],
    "iproyal": ["email", "password"],
    "mysterium": ["api_url"],
    "storj": ["api_url"],
    "traffmonetizer": ["token"],
}


def make_collectors(
    deployments: list[dict[str, Any]],
    config: dict[str, str],
) -> list[BaseCollector]:
    """Create collector instances for all deployed services that have collectors.

    Args:
        deployments: List of deployment dicts (must have 'slug' key).
        config: User config dict. Collector credentials are stored as
                ``{slug}_email``, ``{slug}_password``, etc.

    Returns:
        List of ready-to-use collector instances.
    """
    collectors: list[BaseCollector] = []

    for dep in deployments:
        slug = dep.get("slug", "")
        if slug not in COLLECTOR_MAP:
            continue

        cls = COLLECTOR_MAP[slug]
        arg_keys = _COLLECTOR_ARGS.get(slug, [])

        # Resolve constructor kwargs from config
        kwargs: dict[str, str] = {}
        missing: list[str] = []
        for arg in arg_keys:
            config_key = f"{slug}_{arg}"
            val = config.get(config_key, "")
            if not val:
                missing.append(config_key)
            else:
                kwargs[arg] = val

        if missing:
            logger.warning(
                "Skipping collector for %s — missing config keys: %s",
                slug,
                missing,
            )
            continue

        try:
            collectors.append(cls(**kwargs))
            logger.debug("Created collector for %s", slug)
        except Exception as exc:
            logger.error("Failed to create collector for %s: %s", slug, exc)

    return collectors


__all__ = [
    "BaseCollector",
    "EarningsResult",
    "COLLECTOR_MAP",
    "make_collectors",
]
