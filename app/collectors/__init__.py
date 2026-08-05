"""Collector registry for CashPilot.

Maps service slugs to their collector classes and provides a factory
to instantiate collectors for all currently deployed services.
"""

from __future__ import annotations

import logging
from typing import Any

from app.collectors.anyone import AnyoneCollector
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
    "anyone-protocol": AnyoneCollector,
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
    "anyone-protocol": ["fingerprints"],
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
    # bytelixir_session expires ~2h after issue, so on its own this collector
    # dies the same afternoon it is set up. remember_web is the durable cookie
    # (a year) that lets the session be re-established, and xsrf_token is needed
    # alongside it. Both are optional so a session-only setup still works, but
    # they must be declared here or the UI never asks for them and the values
    # are never passed to the collector — which accepts them already.
    "bytelixir": ["session_cookie", "?remember_web", "?xsrf_token"],
    "salad": ["auth_cookie"],
}

# How long each credential actually lasts, and why it matters.
#
# Several collectors need a value copied out of a browser, and some of those die
# within hours. Without this the UI cannot warn before a collector goes silent,
# and the user only finds out when earnings stop being recorded - by which point
# the failure looks the same as a provider outage.
#
# `hours` is the expected usable lifetime (None = no known expiry, e.g. an
# account password or an API key that lasts until revoked). `durable` marks the
# long-lived alternative where a service offers both. `why` is shown to the user.
CREDENTIAL_LIFETIMES: dict[str, dict[str, dict[str, object]]] = {
    "bytelixir": {
        "session_cookie": {
            "hours": 2,
            "durable": False,
            "why": (
                "Bytelixir's session cookie expires about 2 hours after it is issued. "
                "On its own this collector stops working the same afternoon you set it up."
            ),
        },
        "remember_web": {
            "hours": 24 * 365,
            "durable": True,
            "why": (
                "The durable 'remember me' cookie, good for about a year. Supply this "
                "alongside the session cookie so the session can be re-established "
                "instead of dying in a couple of hours."
            ),
        },
        "xsrf_token": {
            "hours": 24 * 365,
            "durable": True,
            "why": "Needed alongside the remember-me cookie to re-establish a session.",
        },
    },
    "earnapp": {
        "oauth_token": {
            "hours": None,
            "durable": True,
            "why": "Lasts until you sign out of EarnApp or revoke the session.",
        },
    },
    "packetstream": {
        "auth_token": {
            "hours": None,
            "durable": True,
            "why": "A browser session JWT. Lasts until you log out of PacketStream.",
        },
    },
    "grass": {
        "access_token": {
            "hours": None,
            "durable": True,
            "why": "Bearer token from browser localStorage. Re-copy it if Grass signs you out.",
        },
    },
    "salad": {
        "auth_cookie": {
            "hours": None,
            "durable": True,
            "why": "Salad's auth cookie. Lasts until you log out.",
        },
    },
}


def credential_lifetime(slug: str, field: str) -> dict[str, object] | None:
    """Return the lifetime metadata for one credential field, if known."""
    return CREDENTIAL_LIFETIMES.get(slug, {}).get(field)


def durable_alternative(slug: str) -> list[str]:
    """Fields for this service that outlive its short-lived credential."""
    return [f for f, meta in CREDENTIAL_LIFETIMES.get(slug, {}).items() if meta.get("durable")]


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


def fully_configured_slugs(config: dict[str, str]) -> set[str]:
    """Slugs whose every REQUIRED credential key has a value in ``config``.

    The one predicate behind "this service's credentials are complete". It is
    what Settings renders as the green "Configured" badge, what decides whether
    saving credentials starts tracking a service, and what the startup backfill
    uses to catch credentials stored before tracking existed. Three copies of it
    would eventually disagree, and the failure when they do is silent: a badge
    that says Configured for a service nothing collects.

    REQUIRED only. Optional args (``?``-prefixed in ``_COLLECTOR_ARGS``) are
    exactly the ones a collector works without, so demanding them would refuse
    to track a service that would collect perfectly well.

    A collector with no required args at all is NOT included. There is no
    credential to be complete, so "the user configured this" would be asserting
    something the user never did.
    """
    configured: set[str] = set()
    for slug in COLLECTOR_MAP:
        required = [f"{slug}_{arg}" for arg in _COLLECTOR_ARGS.get(slug, []) if not arg.startswith("?")]
        if required and all(config.get(key) for key in required):
            configured.add(slug)
    return configured


def build_one(slug: str, config: dict[str, str]) -> tuple[Any | None, list[str]]:
    """Build a single, UNCACHED collector for an on-demand credential test.

    Returns ``(collector, missing_config_keys)``. Uncached on purpose: the test
    button exists to check credentials the user just changed, and handing back a
    cached instance built from the previous values would validate the wrong
    thing and report success for a credential that no longer exists.

    Resolution reuses the same ``_COLLECTOR_ARGS`` table as ``make_collectors``
    so the two can never disagree about which keys a service needs.
    """
    cls = COLLECTOR_MAP.get(slug)
    if cls is None:
        return None, []

    kwargs: dict[str, str] = {}
    missing: list[str] = []
    for arg in _COLLECTOR_ARGS.get(slug, []):
        optional = arg.startswith("?")
        name = arg.lstrip("?")
        value = config.get(f"{slug}_{name}", "")
        if value:
            kwargs[name] = value
        elif not optional:
            missing.append(f"{slug}_{name}")
    if missing:
        return None, missing
    try:
        return cls(**kwargs), []
    except Exception as exc:
        logger.error("Could not construct collector for %s: %s", slug, exc)
        return None, []


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
