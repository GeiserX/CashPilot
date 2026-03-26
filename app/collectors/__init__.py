"""Collector registry for CashPilot.

Maps service slugs to their collector classes and provides a factory
to instantiate collectors for all currently deployed services.
"""

from __future__ import annotations

import logging
from typing import Any

from app.collectors.base import BaseCollector, EarningsResult
from app.collectors.bitping import BitpingCollector
from app.collectors.bytelixir import BytelixirCollector
from app.collectors.earnapp import EarnAppCollector
from app.collectors.earnfm import EarnFMCollector
from app.collectors.grass import GrassCollector
from app.collectors.honeygain import HoneygainCollector
from app.collectors.iproyal import IPRoyalCollector
from app.collectors.mystnodes import MystNodesCollector
from app.collectors.packetstream import PacketStreamCollector
from app.collectors.proxyrack import ProxyRackCollector
from app.collectors.repocket import RepocketCollector
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
    "repocket": RepocketCollector,
    "proxyrack": ProxyRackCollector,
    "bitping": BitpingCollector,
    "earnfm": EarnFMCollector,
    "packetstream": PacketStreamCollector,
    "grass": GrassCollector,
    "bytelixir": BytelixirCollector,
}

# Map of slug -> list of config keys needed to instantiate the collector
_COLLECTOR_ARGS: dict[str, list[str]] = {
    "honeygain": ["email", "password"],
    "earnapp": ["oauth_token", "?brd_sess_id"],
    "iproyal": ["email", "password"],
    "mysterium": ["email", "password"],
    "storj": ["api_url"],
    "traffmonetizer": ["token"],
    "repocket": ["email", "password"],
    "proxyrack": ["api_key"],
    "bitping": ["email", "password"],
    "earnfm": ["email", "password"],
    "packetstream": ["auth_token"],
    "grass": ["access_token"],
    "bytelixir": ["email", "password"],
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
        # Args prefixed with ? are optional
        kwargs: dict[str, str] = {}
        missing: list[str] = []
        for arg in arg_keys:
            optional = arg.startswith("?")
            arg_name = arg.lstrip("?")
            config_key = f"{slug}_{arg_name}"
            val = config.get(config_key, "")
            if not val and not optional:
                missing.append(config_key)
            elif val:
                kwargs[arg_name] = val

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
