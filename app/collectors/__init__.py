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
from app.collectors.salad import SaladCollector
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
    "salad": SaladCollector,
}

# Map of slug -> list of config keys needed to instantiate the collector
_COLLECTOR_ARGS: dict[str, list[str]] = {
    "honeygain": ["email", "password"],
    "earnapp": ["oauth_token"],
    "iproyal": ["email", "password"],
    "mysterium": ["email", "password"],
    "storj": ["?api_url"],
    "traffmonetizer": ["token"],
    "repocket": ["email", "password"],
    "proxyrack": ["api_key"],
    "bitping": ["email", "password"],
    "earnfm": ["email", "password"],
    "packetstream": ["auth_token"],
    "grass": ["access_token"],
    "bytelixir": ["session_cookie"],
    "salad": ["auth_cookie"],
}

_cached_collectors: dict[str, BaseCollector] = {}
_cached_kwargs: dict[str, dict[str, str]] = {}
_stale: list[BaseCollector] = []


async def _close_stale() -> None:
    """Close collectors evicted from cache due to config changes."""
    global _stale
    for c in _stale:
        await c.close()
    _stale = []


def make_collectors(
    deployments: list[dict[str, Any]],
    config: dict[str, str],
) -> list[BaseCollector]:
    """Create or retrieve cached collector instances for deployed services.

    Reuses a cached instance when the resolved kwargs for a slug match
    the previous invocation. Evicts stale instances when config changes.
    """
    collectors: list[BaseCollector] = []
    active_slugs: set[str] = set()

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

        active_slugs.add(slug)

        # Reuse cached instance if kwargs unchanged
        if slug in _cached_collectors and _cached_kwargs.get(slug) == kwargs:
            collectors.append(_cached_collectors[slug])
            logger.debug("Reusing cached collector for %s", slug)
            continue

        # Config changed or new slug — evict old instance
        if slug in _cached_collectors:
            _stale.append(_cached_collectors[slug])

        try:
            instance = cls(**kwargs)
            _cached_collectors[slug] = instance
            _cached_kwargs[slug] = kwargs
            collectors.append(instance)
            logger.debug("Created collector for %s", slug)
        except Exception as exc:
            logger.error("Failed to create collector for %s: %s", slug, exc)

    # Evict collectors for slugs no longer deployed
    for slug in list(_cached_collectors.keys()):
        if slug not in active_slugs:
            _stale.append(_cached_collectors.pop(slug))
            _cached_kwargs.pop(slug, None)

    return collectors


async def close_all_collectors() -> None:
    """Close all cached collector HTTP clients and clear the cache."""
    global _cached_collectors, _cached_kwargs
    for collector in _cached_collectors.values():
        await collector.close()
    _cached_collectors = {}
    _cached_kwargs = {}
    await _close_stale()


__all__ = [
    "BaseCollector",
    "EarningsResult",
    "COLLECTOR_MAP",
    "make_collectors",
    "close_all_collectors",
]
