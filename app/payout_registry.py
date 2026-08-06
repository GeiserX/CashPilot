"""Where the money goes: the payout registry (CashPilot-luj, tier 1).

Distinct from ``app/payouts.py``, which is about payout *events* — detecting that
a balance dropped, and projecting when the next threshold is reached. This module
is about payout *destinations*: which address does each service actually pay to.

The catalog declares each service's payout MODEL; the deployed spec holds the
address the container was really given. Joining the two lets a user answer "which
addresses do my services pay to?" from one screen instead of reading env vars on
every worker.

THE RULE THIS MODULE EXISTS TO ENFORCE: an address is shown only when it is
KNOWN, and four states are genuinely different. Collapsing them is how a registry
starts lying.

* ``external`` with a resolved address — show it.
* ``external`` with nothing resolved — **"not set", and that is ACTIONABLE**: the
  service may be earning into nowhere.
* ``internal`` — there is NO address, by design. A blank here would read as "you
  forgot to configure this" when nothing is configurable.
* ``unknown`` — we have not classified this service. Say so; do not imply the
  user got something wrong.

STRICTLY NO PRIVATE KEYS. This reads a public address out of a spec the server
already stores, and nothing else. It never touches a key, a seed or a keystore —
which is precisely why it can ship ahead of the on-chain tiers.
"""

from __future__ import annotations

import logging
from typing import Any

from app import catalog, database

logger = logging.getLogger(__name__)

#: The models the catalog may declare. Mirrors ``services/_schema.yml``.
MODELS = ("external", "internal", "minted", "unknown")


def address_from_spec(spec: dict[str, Any] | None, env_name: str) -> str | None:
    """The address the container was actually deployed with, if present.

    Reads the RESOLVED spec rather than the catalog default. That distinction is
    the whole point: a catalog default would display an address the user never
    entered, which is worse than displaying nothing.

    Handles both shapes a Docker spec takes — a mapping, and a ``KEY=value`` list.
    """
    if not spec or not env_name:
        return None

    env = spec.get("environment")
    if env is None:
        env = spec.get("env")

    value: Any = None
    if isinstance(env, dict):
        value = env.get(env_name)
    elif isinstance(env, list):
        prefix = f"{env_name}="
        for item in env:
            text = str(item)
            if text.startswith(prefix):
                value = text[len(prefix) :]
                break

    text = str(value).strip() if value is not None else ""
    return text or None


def entry(service: dict[str, Any], spec: dict[str, Any] | None, *, deployed: bool) -> dict[str, Any]:
    """One row of the registry."""
    payout = service.get("payout") or {}
    model = payout.get("model") or "unknown"
    if model not in MODELS:
        # A catalog that says something we do not understand is UNKNOWN — not a
        # crash, and not passed through to the UI to render as it likes.
        logger.warning("Service %s declares an unrecognised payout model %r", service.get("slug"), model)
        model = "unknown"

    env_name = payout.get("address_env") or ""
    address = address_from_spec(spec, env_name) if model == "external" else None

    return {
        "slug": service.get("slug"),
        "name": service.get("name") or service.get("slug"),
        "category": service.get("category"),
        "deployed": deployed,
        "model": model,
        "chain": payout.get("chain"),
        "address": address,
        "address_env": env_name or None,
        "address_source": payout.get("address_source"),
        # True only where a service SHOULD have an address and does not. This is
        # the one state that asks the user to do something.
        "address_missing": model == "external" and address is None,
        "notes": payout.get("notes"),
    }


async def registry() -> dict[str, Any]:
    """Every service's payout destination, deployed or not.

    Undeployed services are included deliberately: someone choosing what to run
    wants to know Storj needs a wallet address BEFORE deploying it, not after.
    """
    try:
        deployed_slugs = {row["slug"] for row in await database.get_deployments()}
    except Exception as exc:  # noqa: BLE001 - the screen must render regardless
        logger.warning("Could not read deployments for the payout registry: %s", exc)
        deployed_slugs = set()

    entries: list[dict[str, Any]] = []
    for service in catalog.get_services():
        slug = service.get("slug")
        is_deployed = slug in deployed_slugs
        spec = None
        if is_deployed:
            try:
                spec = await database.get_deployment_spec(slug)
            except Exception as exc:  # noqa: BLE001
                # A spec that cannot be decrypted is UNKNOWN, not absent: the row
                # still renders, and address_missing stays honest about it.
                logger.warning("Could not read the deployed spec for %s: %s", slug, exc)
        entries.append(entry(service, spec, deployed=is_deployed))

    entries.sort(key=lambda row: (not row["deployed"], (row["name"] or "").lower()))
    return {
        "entries": entries,
        "summary": {
            "total": len(entries),
            "deployed": sum(1 for row in entries if row["deployed"]),
            # The two numbers worth putting in front of a person: money that may
            # be going nowhere, and services we cannot yet answer for.
            "needs_an_address": sum(1 for row in entries if row["address_missing"] and row["deployed"]),
            "unclassified": sum(1 for row in entries if row["model"] == "unknown"),
        },
    }
