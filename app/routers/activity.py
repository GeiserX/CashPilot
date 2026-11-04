"""Activity API: what each earner did on the network (docs/activity.md).

Owner only, every route: the page shows other people's traffic metadata, and
the switch makes a worker start containers. Changes are POST, because the
session cookie is SameSite=lax and still rides a cross-site GET.

Like the other routers, handlers reach shared state through ``app.deps`` and
``app.database``, never ``app.main``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import activity_ui, database, deps, ipgeo, placement

router = APIRouter()
logger = logging.getLogger(__name__)

DAYS = (1, 7, 30)


def _system_info(worker: dict[str, Any]) -> dict[str, Any]:
    try:
        info = json.loads(worker.get("system_info") or "{}")
    except (TypeError, ValueError):
        return {}
    return info if isinstance(info, dict) else {}


def _features(worker: dict[str, Any]) -> list[str]:
    features = _system_info(worker).get("features")
    return [str(f) for f in features] if isinstance(features, list) else []


async def _workers() -> list[dict[str, Any]]:
    """Every worker that can run Activity at all: phones have no containers to sample."""
    return [w for w in await database.list_workers() if not placement.is_android(_system_info(w))]


async def _worker(worker_id: int) -> dict[str, Any]:
    for w in await _workers():
        if w["id"] == worker_id:
            return w
    raise HTTPException(status_code=404, detail="Worker not found")


def _days(days: int) -> int:
    if days not in DAYS:
        raise HTTPException(status_code=400, detail="days must be 1, 7 or 30")
    return days


async def _alert_subjects() -> dict[str, int]:
    """Activity alerts of the last day, counted by subject (worker client_id:container[:class])."""
    cutoff = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    counts: dict[str, int] = {}
    for a in await database.list_alerts(limit=500):
        if str(a.get("kind", "")).startswith("activity_") and str(a.get("created_at", "")) >= cutoff:
            counts[a["subject"]] = counts.get(a["subject"], 0) + 1
    return counts


@router.get("/api/activity/summary")
async def api_activity_summary(request: Request, days: int = 1) -> dict[str, Any]:
    deps._require_owner(request)
    days = _days(days)
    now = int(time.time())
    since = now - days * 86400
    config = await database.get_config() or {}
    latest = await database.get_activity_latest(since)
    series_rows = await database.get_activity_series(since, hourly=days > 1)
    dim_rows = await database.get_activity_dims(since - since % 3600)
    alerts = await _alert_subjects()
    last = await database.get_activity_last_windows()
    out = []
    for w in sorted(await _workers(), key=lambda w: (w.get("name") or "").lower()):
        cid = str(w.get("client_id") or w["id"])
        out.append(
            {
                "worker_id": w["id"],
                "name": w.get("name") or f"worker {w['id']}",
                "status": w.get("status"),
                "enabled": activity_ui.enabled(config, w),
                "supported": "activity" in _features(w),
                "last_window": last.get(w["id"]),
                "round": activity_ui.LAST_STATUS.get(w["id"]),
                "containers": activity_ui.container_rows(
                    [r for r in latest if r["worker_id"] == w["id"]],
                    [r for r in series_rows if r["worker_id"] == w["id"]],
                    [r for r in dim_rows if r["worker_id"] == w["id"]],
                    alerts,
                    cid,
                ),
            }
        )
    return {"days": days, "now": now, "workers": out, "asn": await asyncio.to_thread(ipgeo.status)}


@router.get("/api/activity/container")
async def api_activity_container(
    request: Request, worker_id: int = 0, container: str = "", days: int = 1
) -> dict[str, Any]:
    # Optional in the signature so the auth check runs before any validation:
    # a 422 to an anonymous caller would describe the route to them.
    deps._require_owner(request)
    if not container:
        raise HTTPException(status_code=400, detail="container is required")
    days = _days(days)
    w = await _worker(worker_id)
    now = int(time.time())
    since = now - days * 86400
    series_rows = await database.get_activity_series(since, days > 1, worker_id, container)
    dim_rows = await database.get_activity_dims(since - since % 3600, worker_id, container)
    raw = await database.get_activity_raw(worker_id, container)
    return {
        "worker_id": worker_id,
        "name": w.get("name"),
        "container": container,
        "days": days,
        "series": activity_ui.series(series_rows),
        "dims": activity_ui.dims(dim_rows, top=50),
        "raw": raw,
        "raw_hours": activity_ui.RAW_HOURS,
    }


class ActivitySetting(BaseModel):
    worker_id: int
    enabled: bool


@router.post("/api/activity/settings")
async def api_activity_settings(request: Request, body: ActivitySetting) -> dict[str, Any]:
    """Switch Activity on or off for one worker. Off deletes its raw addresses at once."""
    deps._require_owner(request)
    w = await _worker(body.worker_id)
    await database.set_config(activity_ui.flag_key(w), "true" if body.enabled else "false")
    deleted = 0
    if not body.enabled:
        deleted = await database.delete_activity(w["id"], raw_only=True)
        activity_ui.LAST_STATUS.pop(w["id"], None)
    logger.info("Activity %s for worker %s", "enabled" if body.enabled else "disabled", w["id"])
    return {"worker_id": w["id"], "enabled": body.enabled, "deleted_raw": deleted}


class ActivityDelete(BaseModel):
    worker_id: int


@router.post("/api/activity/delete")
async def api_activity_delete(request: Request, body: ActivityDelete) -> dict[str, Any]:
    """Delete every Activity row of one worker. The switch stays as it is."""
    deps._require_owner(request)
    w = await _worker(body.worker_id)
    deleted = await database.delete_activity(w["id"])
    activity_ui.LAST_STATUS.pop(w["id"], None)
    return {"worker_id": w["id"], "deleted": deleted}


@router.post("/api/activity/asn/refresh")
async def api_activity_asn_refresh(request: Request) -> dict[str, Any]:
    """Download the network table now, instead of waiting for the weekly refresh."""
    deps._require_owner(request)
    if not ipgeo.source_url():
        raise HTTPException(status_code=409, detail="The download is disabled (CASHPILOT_ACTIVITY_ASN_URL is empty).")
    try:
        await asyncio.to_thread(ipgeo.download)
    except ipgeo.DownloadBusy:
        raise HTTPException(status_code=409, detail="A download is already running.") from None
    except Exception as exc:  # noqa: BLE001 - a fixed message, never the exception text
        logger.warning("Network table download failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="The network table could not be downloaded.") from None
    return await asyncio.to_thread(ipgeo.status)
