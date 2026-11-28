"""Automatic app image updates (UI side).

Most earner images in the catalog follow a tag (``:latest``, ``:lite``, no
tag), and the provider ships a new build under the same tag. Before this, an
earner got a new build only when its owner redeployed it.

How it works, once a day at the owner's hour, one box at a time per worker:

1. The worker pulls the tag its copies run and says whether the build moved
   (``POST /api/containers/{slug}/image-check``, orchestrator.check_image).
   The socket proxy lets it pull and inspect images and nothing more, so the
   check is a pull. An unchanged build is a no-op: nothing is recreated.
2. A moved build is either reported ("Notify only") or deployed ("Update
   automatically") through the dashboard's own blank redeploy (main._deploy),
   which rebuilds the container from its deployment record: env, volumes,
   identity, network and fence, runtime, labels and limits all come from the
   same code a manual Redeploy runs. Only a copy the redeploy would rebuild
   exactly as it runs (no drift, the same image reference, running, direct)
   is updated by itself.
3. The worker watches the new container for SETTLE_SECONDS before it removes
   the old one (orchestrator.deploy_raw ``settle_seconds``). One that stops,
   restarts, turns unhealthy or logs a catalog failure signal is undone: the
   old container, with its old image, runs again. That build is then held:
   it is never tried again on that box, only a newer one is, so a build that
   fails after every recreate cannot loop.

Images pinned by digest in the catalog are not checked: a CashPilot release
moves them.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_KEY = "image_updates"
OFF, NOTIFY, AUTO = "off", "notify", "auto"
MODES = (OFF, NOTIFY, AUTO)
#: The local hour the daily check runs at, unless the owner picks another.
DEFAULT_HOUR = 4
#: How long a new container must stay healthy before the old one is removed.
SETTLE_SECONDS = 120
#: The pause after each real update on a box, so updates are spread out.
GAP_SECONDS = 60
#: The worker feature that says it takes the check and settle_seconds.
FEATURE = "image_updates"

#: Results kept in the image_updates table.
UPDATED, ROLLED_BACK, FAILED, AVAILABLE, SKIPPED = "updated", "rolled_back", "failed", "available", "skipped"
RESULTS = (UPDATED, ROLLED_BACK, FAILED, AVAILABLE, SKIPPED)


def default_settings(fresh_install: bool) -> dict[str, Any]:
    """What an install starts with: a new one updates by itself, an upgraded one is offered it."""
    if fresh_install:
        return {"mode": AUTO, "hour": DEFAULT_HOUR}
    return {"mode": OFF, "hour": DEFAULT_HOUR, "offer": True}


def parse_settings(raw: Any) -> dict[str, Any]:
    """The stored settings, with anything unreadable replaced by a safe value (off)."""
    try:
        data = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else {})
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    mode = data.get("mode") if data.get("mode") in MODES else OFF
    hour = data.get("hour")
    hour = hour if isinstance(hour, int) and not isinstance(hour, bool) and 0 <= hour <= 23 else DEFAULT_HOUR
    workers = _overrides(data.get("workers"))
    services = _overrides(data.get("services"))
    out: dict[str, Any] = {"mode": mode, "hour": hour, "workers": workers, "services": services}
    if data.get("offer") is True:
        out["offer"] = True
    if isinstance(data.get("last_run"), str):
        out["last_run"] = data["last_run"]
    return out


def _overrides(raw: Any) -> dict[str, str]:
    """The valid entries of one override map; anything that is not a map is none."""
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, str) and v in MODES}


def effective_mode(settings: dict[str, Any], worker_id: int, slug: str) -> str:
    """The mode for one service on one box: the service's own, else the box's, else the fleet's."""
    return (
        settings.get("services", {}).get(slug)
        or settings.get("workers", {}).get(str(worker_id))
        or settings.get("mode")
        or OFF
    )


def due(settings: dict[str, Any], now: datetime) -> bool:
    """Whether the daily run should start now: the owner's hour has come and today's run has not happened."""
    return now.hour >= settings.get("hour", DEFAULT_HOUR) and settings.get("last_run") != now.date().isoformat()


def anything_on(settings: dict[str, Any]) -> bool:
    """Whether any service on any box could be checked: not every choice is off."""
    return any(m != OFF for m in (settings.get("mode"), *settings["workers"].values(), *settings["services"].values()))


@dataclass
class Hooks:
    """What a run needs from the dashboard (app/main.py), passed in so this module stays testable."""

    #: Ask the worker to check: (worker_id, slug) -> the worker's answer.
    check: Callable[[int, str], Awaitable[dict[str, Any]]]
    #: Why the dashboard will not update this service by itself, or "" when it may.
    blocker: Callable[[int, str, dict[str, Any]], Awaitable[str]]
    #: Run the blank redeploy with the check period: (worker_id, slug, expected containers, checked image ID)
    #: -> the deploy's answer.
    deploy: Callable[[int, str, dict[str, str], str], Awaitable[dict[str, Any]]]
    #: Write one result row.
    record: Callable[..., Awaitable[None]]
    #: Whether a row with this result already names this new image on this box.
    seen: Callable[[int, str, str, tuple[str, ...]], Awaitable[bool]]
    #: Sleep between updates (asyncio.sleep, replaced in tests).
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep


class DeployRefused(Exception):
    """The deploy did not go through; ``rolled_back`` when the worker undid an unhealthy update."""

    def __init__(self, message: str, *, rolled_back: bool) -> None:
        super().__init__(message)
        self.rolled_back = rolled_back


class ModeChanged(Exception):
    """The owner chose another mode for the service while its check ran: nothing is deployed or recorded."""


def _short(digest: str) -> str:
    return digest.split(":", 1)[-1][:12] if digest else ""


async def update_service(hooks: Hooks, worker_id: int, slug: str, mode: str) -> str:
    """Check one service on one box and act on the mode. Returns what happened, for the log and the tests."""
    if mode == OFF:
        return "off"
    answer = await hooks.check(worker_id, slug)
    if not answer.get("floating"):
        return "pinned"
    latest = answer.get("latest") or {}
    new_id, new_digest = str(latest.get("id") or ""), str(latest.get("digest") or "")
    copies = [c for c in answer.get("containers") or [] if isinstance(c, dict)]
    if not new_id or not copies:
        return "unknown"
    stale = [c for c in copies if c.get("image_id") != new_id]
    if not stale:
        return "current"
    old_id, old_digest = str(stale[0].get("image_id") or ""), str(stale[0].get("digest") or "")
    facts = {"old_image": old_id, "new_image": new_id, "old_digest": old_digest, "new_digest": new_digest}
    # A build that already failed here is never tried again; a newer one is.
    if await hooks.seen(worker_id, slug, new_id, (ROLLED_BACK,)):
        return "held"
    if mode == NOTIFY:
        if not await hooks.seen(worker_id, slug, new_id, (AVAILABLE,)):
            await hooks.record(worker_id, slug, AVAILABLE, **facts)
        return "available"
    why = await hooks.blocker(worker_id, slug, answer)
    if not why and any(c.get("status") != "running" for c in copies):
        why = "not every copy of it is running, and an update would start it"
    if not why and len(copies) > 1:
        # Copies are replaced one by one, so a later copy that fails would leave
        # the box running two builds of it under one undone result.
        why = f"it runs {len(copies)} copies here, and only a single copy is updated by itself"
    if why:
        if not await hooks.seen(worker_id, slug, new_id, (SKIPPED,)):
            await hooks.record(worker_id, slug, SKIPPED, detail=why, **facts)
        return "skipped"
    expected = {str(c.get("instance") or 1): str(c.get("container_id") or "") for c in copies}
    try:
        # The checked build, and only it: a tag that moved since is refused by
        # the worker, so the build undone and held is the one named here.
        result = await hooks.deploy(worker_id, slug, expected, new_id)
    except ModeChanged:
        return "off"
    except DeployRefused as exc:
        await hooks.record(worker_id, slug, ROLLED_BACK if exc.rolled_back else FAILED, detail=str(exc), **facts)
        return "rolled_back" if exc.rolled_back else "failed"
    done = result.get("image_update") if isinstance(result.get("image_update"), dict) else {}
    kept = str(done.get("old_kept") or "")
    detail = f"The old image stays on disk: {kept}." if kept else ""
    await hooks.record(
        worker_id, slug, UPDATED, detail=detail, **{**facts, "new_image": str(done.get("new_image") or new_id)}
    )
    logger.info("Updated %s on worker %s from %s to %s", slug, worker_id, _short(old_digest), _short(new_digest))
    return "updated"


async def run_worker(hooks: Hooks, settings: dict[str, Any], worker_id: int, slugs: list[str]) -> dict[str, str]:
    """Check each service on one box in turn; a pause follows each real update. Never raises."""
    outcomes: dict[str, str] = {}
    for slug in slugs:
        mode = effective_mode(settings, worker_id, slug)
        try:
            outcomes[slug] = await update_service(hooks, worker_id, slug, mode)
        except Exception as exc:  # noqa: BLE001 - one service's failure never stops the others
            logger.warning("Image check of %s on worker %s failed: %s", slug, worker_id, exc)
            outcomes[slug] = "error"
        if outcomes[slug] in ("updated", "rolled_back"):
            await hooks.sleep(GAP_SECONDS)
    return outcomes
