"""CashPilot — FastAPI application.

Self-hosted passive income dashboard: service catalog, Docker container
management, and earnings tracking.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any
from urllib.parse import urlparse

import httpx
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from app import auth, catalog, compose_generator, database, exchange_rates, fleet_key, metrics, setup_token

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# In-memory store for the latest collector alerts (errors from last run)
_collector_alerts: list[dict[str, str]] = []
_collection_lock = asyncio.Lock()
_collection_semaphore = asyncio.Semaphore(8)

# Fire-and-forget background tasks (e.g. triggered collection runs). Keeping a
# reference prevents the task from being garbage-collected mid-run and lets us
# retrieve/log any exception it raised (bare `asyncio.create_task(...)` drops
# the reference and silently swallows exceptions).
_background_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> asyncio.Task:
    """Fire-and-forget a coroutine while keeping a reference and logging errors."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)

    def _on_done(t: asyncio.Task) -> None:
        _background_tasks.discard(t)
        if not t.cancelled():
            exc = t.exception()
            if exc is not None:
                logger.error("Background task failed: %s", exc, exc_info=exc)

    task.add_done_callback(_on_done)
    return task


# Login rate limiting
_login_attempts: dict[str, list[float]] = defaultdict(list)
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 300


def _check_login_rate(ip: str) -> None:
    now = monotonic()
    attempts = _login_attempts[ip]
    _login_attempts[ip] = [t for t in attempts if now - t < _LOGIN_WINDOW_SECONDS]
    if len(_login_attempts[ip]) >= _LOGIN_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again in a few minutes.")


def _record_failed_login(ip: str) -> None:
    _login_attempts[ip].append(monotonic())


def _safe_json(raw: str, fallback: Any = None) -> Any:
    """Parse JSON with a fallback so one malformed DB row doesn't 500 the fleet."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return fallback if fallback is not None else []


async def _get_all_worker_containers() -> list[dict[str, Any]]:
    """Collect container/app data from all online workers' heartbeat data in DB."""
    workers = await database.list_workers()
    result: list[dict[str, Any]] = []
    for w in workers:
        if w.get("status") != "online":
            continue
        sys_info = _safe_json(w.get("system_info", "{}"), {})
        worker_has_docker = sys_info.get("docker_available", False)
        is_android = sys_info.get("device_type") == "android"
        worker_name = w.get("name", "worker")

        # Docker containers (from Docker-based workers only — skip for Android)
        if not is_android:
            containers = _safe_json(w.get("containers", "[]"))
            for c in containers:
                slug = c.get("slug", "")
                if slug:
                    result.append(
                        {
                            "slug": slug,
                            "name": c.get("name", slug),
                            "status": c.get("status", "unknown"),
                            "image": c.get("image", ""),
                            "cpu_percent": c.get("cpu_percent", 0),
                            "memory_mb": c.get("memory_mb", 0),
                            "category": "",
                            "deployed_by": worker_name,
                            "_node": worker_name,
                            "_worker_id": w.get("id"),
                            "_has_docker": worker_has_docker,
                            "_is_android": False,
                        }
                    )

        # Android apps (from Android workers)
        if is_android:
            apps = _safe_json(w.get("apps", "[]"))
            for a in apps:
                slug = a.get("slug", "")
                if slug:
                    result.append(
                        {
                            "slug": slug,
                            "name": a.get("slug", slug),
                            "status": "running" if a.get("running") else "stopped",
                            "image": "",
                            "cpu_percent": 0,
                            "memory_mb": 0,
                            "category": "",
                            "deployed_by": worker_name,
                            "_node": worker_name,
                            "_worker_id": w.get("id"),
                            "_has_docker": False,
                            "_is_android": True,
                            "_net_tx_24h": a.get("net_tx_24h", 0),
                            "_net_rx_24h": a.get("net_rx_24h", 0),
                        }
                    )
    return result


async def _resolve_worker_id(worker_id: int | None) -> int:
    """Return a valid worker_id, auto-resolving when only one worker is online."""
    if worker_id is not None:
        return worker_id
    workers = await database.list_workers()
    online = [w for w in workers if w["status"] == "online"]
    if len(online) == 1:
        return online[0]["id"]
    if len(online) == 0:
        raise HTTPException(status_code=503, detail="No workers online")
    raise HTTPException(
        status_code=400,
        detail="worker_id is required (multiple workers online)",
    )


# ---------------------------------------------------------------------------
# Periodic collection job
# ---------------------------------------------------------------------------


async def _run_health_check() -> None:
    """Check health of all deployed containers and record events.

    Deduplicates by slug: if *any* instance of a service is running,
    record a single check_ok for that slug (avoids penalising services
    deployed on multiple nodes where one may be stopped).
    """
    try:
        statuses = await _get_all_worker_containers()
        # Aggregate: slug -> best status (running wins)
        slug_best: dict[str, str] = {}
        for s in statuses:
            slug = s["slug"]
            status = s.get("status", "unknown")
            if slug_best.get(slug) != "running":
                slug_best[slug] = status
        for slug, status in slug_best.items():
            if status == "running":
                await database.record_health_event(slug, "check_ok")
            else:
                await database.record_health_event(slug, "check_down", status)
    except Exception as exc:
        logger.warning("Health check skipped: %s", exc)


async def _collect_bounded(collector) -> Any:
    """Run a single collector's `collect()` under the shared concurrency limit."""
    async with _collection_semaphore:
        return await collector.collect()


async def _run_collection() -> None:
    """Collect earnings from all deployed services that have collectors."""
    global _collector_alerts
    if _collection_lock.locked():
        logger.info("Collection already in progress, skipping")
        return
    async with _collection_lock:
        success = True
        start_time = 0.0
        try:
            start_time = metrics.record_collection_start()
            deployments = await database.get_deployments()
            config = await database.get_config() or {}
            if not isinstance(config, dict):
                config = {}
            from app.collectors import _close_stale, make_collectors

            collectors = make_collectors(deployments, config)
            await _close_stale()
            results = await asyncio.gather(*(_collect_bounded(c) for c in collectors), return_exceptions=True)
            alerts: list[dict[str, str]] = []
            platforms_ok = 0
            for result in results:
                if isinstance(result, Exception):
                    logger.warning("Collector raised exception: %s", result)
                    success = False
                    continue
                if result.error:
                    logger.warning("Collection error for %s: %s", result.platform, result.error)
                    alerts.append({"platform": result.platform, "error": result.error})
                    metrics.record_collection_error(result.platform)
                else:
                    await database.upsert_earnings(
                        platform=result.platform,
                        balance=result.balance,
                        currency=result.currency,
                    )
                    logger.info("Collected %s: %.4f %s", result.platform, result.balance, result.currency)
                    platforms_ok += 1
            _collector_alerts = alerts
        except Exception as exc:
            logger.error("Collection run failed: %s", exc)
            success = False
            platforms_ok = 0
            _collector_alerts = [{"platform": "collection", "error": "Collection run failed — see server logs"}]
        finally:
            metrics.record_collection_end(start_time, success, platforms_ok)


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------


async def _run_data_retention() -> None:
    """Purge data older than 400 days."""
    try:
        deleted = await database.purge_old_data()
        if deleted:
            logger.info("Data retention: purged %d old rows", deleted)
    except Exception as exc:
        logger.warning("Data retention error: %s", exc)


async def _run_vacuum() -> None:
    """Reclaim disk left by retention deletes (SQLite does not auto-shrink)."""
    try:
        await database.vacuum_database()
        logger.info("Database VACUUM complete")
    except Exception as exc:
        logger.warning("Database VACUUM error: %s", exc)


async def _check_stale_workers() -> None:
    """Mark workers as offline if stale, and purge workers offline > 1 hour."""
    try:
        workers = await database.list_workers()
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=STALE_WORKER_SECONDS)
        purge_cutoff = now - timedelta(hours=1)
        for w in workers:
            last_hb = w.get("last_heartbeat")
            if not last_hb:
                continue
            last = datetime.fromisoformat(last_hb).replace(tzinfo=UTC)
            if w["status"] == "online" and last < cutoff:
                await database.set_worker_status(w["id"], "offline")
                logger.info("Worker '%s' marked offline (last heartbeat: %s)", w["name"], last_hb)
            elif w["status"] == "offline" and last < purge_cutoff:
                await database.delete_worker(w["id"])
                logger.info("Purged stale worker '%s' (offline since %s)", w["name"], last_hb)
    except Exception as exc:
        logger.warning("Stale worker check error: %s", exc)


FLEET_API_KEY = fleet_key.resolve_fleet_key()
HOSTNAME_PREFIX = os.getenv("CASHPILOT_HOSTNAME_PREFIX", "cashpilot")
COLLECT_INTERVAL_MIN = int(os.getenv("CASHPILOT_COLLECT_INTERVAL", "60"))
STALE_WORKER_SECONDS = 180  # Mark worker offline after 3 missed heartbeats


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await database.init_db()
    await database.connect_shared()
    # Warm the per-user password-change epoch cache so existing sessions issued
    # before a password change are rejected without a DB hit in the request path.
    for _u in await database.list_users_with_pwd_epoch():
        _changed = _u.get("password_changed_at") or 0.0
        if _changed:
            auth.set_user_pwd_epoch(_u["id"], _changed)
    # First-run setup token: while no users exist, require a one-time token
    # (printed below) for /register so a proxy-exposed instance cannot be seized
    # by the first public visitor. Persisted in config so it survives restarts;
    # cleared once the owner account is created.
    if not await database.has_any_users():
        _tok = await database.get_config("_setup_token")
        if not _tok:
            _tok = setup_token.generate()
            await database.set_config("_setup_token", _tok)
        setup_token.set_active(_tok)
        logger.warning(
            "FIRST-RUN SETUP: no account exists yet. Open /register and enter this "
            "one-time setup token to create the owner account: %s  (shown only here; "
            "not embedded in any URL so it stays out of proxy logs and browser history)",
            _tok,
        )
    catalog.load_services()
    catalog.register_sighup()

    def _on_job_event(event):
        logger.error("Scheduler job %s failed or missed", event.job_id, exc_info=getattr(event, "exception", None))

    scheduler.add_listener(_on_job_event, EVENT_JOB_ERROR | EVENT_JOB_MISSED)
    scheduler.add_job(
        _run_collection,
        "interval",
        minutes=COLLECT_INTERVAL_MIN,
        id="collect",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _run_health_check,
        "interval",
        minutes=5,
        id="health_check",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _check_stale_workers,
        "interval",
        minutes=2,
        id="stale_workers",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _run_data_retention,
        "interval",
        hours=24,
        id="data_retention",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _run_vacuum,
        "interval",
        weeks=1,
        id="db_vacuum",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        exchange_rates.refresh,
        "interval",
        minutes=15,
        id="exchange_rates",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.start()
    await exchange_rates.refresh()
    _spawn(_run_collection())
    logger.info("CashPilot UI started (container ops via workers)")

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    await database.close_shared()
    from app.collectors import close_all_collectors

    await close_all_collectors()
    logger.info("CashPilot stopped")


app = FastAPI(
    title="CashPilot",
    version="0.1.0",
    lifespan=lifespan,
)
metrics.setup(app)


# Security headers middleware
class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
            "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self' https://cdn.jsdelivr.net; "
            "frame-ancestors 'none'"
        )
        return response


app.add_middleware(_SecurityHeadersMiddleware)

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")


# ---------------------------------------------------------------------------
# Auth helpers + templates (shared, defined in app.deps).
#
# Imported here so ``app.main._require_owner`` / ``app.main.templates`` keep
# resolving for tests and for the split router groups, which reference them
# through the ``app.main`` namespace (e.g. ``main._require_owner``).
# ---------------------------------------------------------------------------
from app.deps import (  # noqa: E402
    _login_redirect,  # noqa: F401  (re-exported for app.main.* test/router surface)
    _require_auth_api,
    _require_first_run_access,  # noqa: F401  (re-exported for app.main.* router surface)
    _require_owner,
    _require_private_network,  # noqa: F401  (re-exported for app.main.* router surface)
    _require_writer,
    client_ip,  # noqa: F401  (re-exported for app.main.* router surface)
    templates,  # noqa: F401  (re-exported for app.main.* router/test surface)
)

# ---------------------------------------------------------------------------
# API: Services
# ---------------------------------------------------------------------------


@app.get("/api/mode")
async def api_mode(request: Request) -> dict[str, Any]:
    """Return CashPilot operating mode and Docker availability."""
    _require_auth_api(request)
    return {"docker": False, "mode": "ui"}


@app.get("/api/services")
async def api_list_services(request: Request) -> list[dict[str, Any]]:
    _require_auth_api(request)
    return catalog.get_services()


def _collector_needs_setup(slug: str, config: dict[str, str]) -> bool:
    """True if `slug` has an earnings collector whose required config is unset.

    A service can be deployed and earning while CashPilot still can't read its
    balance because the (separate) collector credentials haven't been entered.
    This distinguishes that "not set up yet" state from a real collector error.
    """
    from app.collectors import _COLLECTOR_ARGS, COLLECTOR_MAP

    if slug not in COLLECTOR_MAP:
        return False
    for arg in _COLLECTOR_ARGS.get(slug, []):
        if arg.startswith("?"):  # optional arg — not required for setup
            continue
        if not config.get(f"{slug}_{arg}", ""):
            return True
    return False


@app.get("/api/services/deployed")
async def api_services_deployed(request: Request) -> list[dict[str, Any]]:
    """Return deployed services with container status, balance, CPU, memory.

    Multiple containers for the same slug (multi-node) are aggregated into a
    single row with summed CPU/memory, an instance count, and per-instance
    details for the expandable sub-row UI.
    """
    _require_auth_api(request)
    statuses: list[dict[str, Any]] = await _get_all_worker_containers()

    # Get latest earnings per platform for balance display
    earnings = await database.get_earnings_summary()
    balance_map = {e["platform"]: e["balance"] for e in earnings}
    currency_map = {e["platform"]: e["currency"] for e in earnings}

    # Get health scores
    health_scores = await database.get_health_scores(7)
    health_map = {h["slug"]: h for h in health_scores}

    # Build set of slugs with collector errors (disconnected)
    alert_slugs = {a["platform"] for a in _collector_alerts}

    # Config (decrypted) to detect collectors whose credentials aren't set yet.
    # A config-read failure must not blank the dashboard — degrade to "unknown".
    config: dict[str, str] = {}
    try:
        cfg = await database.get_config()
        if isinstance(cfg, dict):
            config = cfg
    except Exception as exc:
        logger.warning("Could not load config for collector-setup check: %s", exc)

    # Aggregate by slug: one row per service
    _STATUS_PRIORITY = {"running": 0, "restarting": 1, "exited": 2, "created": 3, "dead": 4}
    slug_agg: dict[str, dict[str, Any]] = {}
    for s in statuses:
        slug = s["slug"]
        if slug not in slug_agg:
            slug_agg[slug] = {
                "instances": [],
                "total_cpu": 0.0,
                "total_mem": 0.0,
                "best_status": s.get("status", "unknown"),
                "image": s.get("image", ""),
            }
        agg = slug_agg[slug]
        agg["instances"].append(s)
        agg["total_cpu"] += float(s.get("cpu_percent", 0))
        agg["total_mem"] += float(s.get("memory_mb", 0))
        cur = s.get("status", "unknown")
        if _STATUS_PRIORITY.get(cur, 9) < _STATUS_PRIORITY.get(agg["best_status"], 9):
            agg["best_status"] = cur

    result = []
    for slug, agg in slug_agg.items():
        svc = catalog.get_service(slug)
        health = health_map.get(slug, {})

        # Build per-instance detail list (local first)
        instance_details = []
        for inst in agg["instances"]:
            detail = {
                "node": inst.get("_node", "unknown"),
                "worker_id": inst.get("_worker_id"),
                "status": inst.get("status", "unknown"),
                "cpu": f"{float(inst.get('cpu_percent', 0)):.2f}",
                "memory": f"{float(inst.get('memory_mb', 0)):.1f} MB",
                "container_name": inst.get("name", ""),
                "has_docker": inst.get("_has_docker", False),
                "is_android": inst.get("_is_android", False),
            }
            if inst.get("_is_android"):
                detail["net_tx_24h"] = inst.get("_net_tx_24h", 0)
                detail["net_rx_24h"] = inst.get("_net_rx_24h", 0)
            instance_details.append(detail)
        # Sort: local first, then alphabetically by node name
        instance_details.sort(key=lambda x: (0 if x["node"] == "local" else 1, x["node"]))

        entry = {
            "slug": slug,
            "name": svc["name"] if svc else slug,
            "container_status": agg["best_status"],
            "balance": balance_map.get(slug, 0.0),
            "currency": currency_map.get(slug, "USD"),
            "cpu": f"{agg['total_cpu']:.2f}",
            "memory": f"{agg['total_mem']:.1f} MB",
            "image": agg["image"],
            "category": agg["instances"][0].get("category", ""),
            "health_score": health.get("score"),
            "uptime_pct": health.get("uptime_pct"),
            "restarts_7d": health.get("restarts", 0),
            "crashes_7d": health.get("crashes", 0),
            # "unstable" flags a service that has crashed repeatedly in the health window
            # so the dashboard can surface it at a glance (not just via the score number).
            "unstable": health.get("crashes", 0) >= 3,
            "instances": len(agg["instances"]),
            "instance_details": instance_details,
            "collector_disconnected": slug in alert_slugs,
            "collector_needs_setup": slug not in alert_slugs and _collector_needs_setup(slug, config),
        }
        if svc:
            cashout = svc.get("cashout", {})
            if cashout:
                entry["cashout"] = cashout
            referral = svc.get("referral", {})
            if referral:
                entry["referral_url"] = referral.get("signup_url", "")
            entry["website"] = svc.get("website", "")
        result.append(entry)

    # Include external services (no Docker container, e.g. Grass, Bytelixir)
    seen_slugs = {r["slug"] for r in result}
    deployments = await database.get_deployments()
    for d in deployments:
        slug = d["slug"]
        if slug in seen_slugs:
            continue
        if d.get("status") != "external":
            continue
        svc = catalog.get_service(slug)
        health = health_map.get(slug, {})
        entry = {
            "slug": slug,
            "name": svc["name"] if svc else slug,
            "container_status": "external",
            "balance": balance_map.get(slug, 0.0),
            "currency": currency_map.get(slug, "USD"),
            "cpu": "",
            "memory": "",
            "image": "",
            "category": svc.get("category", "") if svc else "",
            "health_score": None,
            "uptime_pct": None,
            "restarts_7d": 0,
            "crashes_7d": 0,
            "unstable": False,
            "instances": 0,
            "instance_details": [],
            "collector_disconnected": slug in alert_slugs,
            "collector_needs_setup": slug not in alert_slugs and _collector_needs_setup(slug, config),
        }
        if svc:
            cashout = svc.get("cashout", {})
            if cashout:
                entry["cashout"] = cashout
            referral = svc.get("referral", {})
            if referral:
                entry["referral_url"] = referral.get("signup_url", "")
            entry["website"] = svc.get("website", "")
        result.append(entry)

    return result


@app.get("/api/services/available")
async def api_services_available(request: Request) -> list[dict[str, Any]]:
    """Return available services from catalog, enriched with deployment status."""
    _require_auth_api(request)
    services = catalog.get_services()
    deployments = await database.get_deployments()
    deployed_slugs = {d["slug"] for d in deployments}

    # Also check worker containers for deployed status (catches externally-deployed services)
    worker_containers = await _get_all_worker_containers()
    worker_slugs: set[str] = set()
    worker_node_counts: dict[str, set[str]] = {}
    for c in worker_containers:
        slug = c.get("slug", "")
        if slug:
            worker_slugs.add(slug)
            node = c.get("_node", "unknown")
            if slug not in worker_node_counts:
                worker_node_counts[slug] = set()
            worker_node_counts[slug].add(node)

    available = []
    for svc in services:
        if svc.get("status") in ("broken", "dead", "dropped"):
            continue  # Known non-functional — hide completely
        docker_conf = svc.get("docker", {})
        has_image = bool(docker_conf and docker_conf.get("image"))
        slug = svc.get("slug", "")
        svc["deployed"] = slug in deployed_slugs or slug in worker_slugs
        svc["manual_only"] = not has_image
        svc["node_count"] = len(worker_node_counts.get(slug, set()))
        available.append(svc)
    return available


@app.get("/api/services/{slug}")
async def api_get_service(request: Request, slug: str) -> dict[str, Any]:
    _require_auth_api(request)
    svc = catalog.get_service(slug)
    if not svc:
        raise HTTPException(status_code=404, detail=f"Service '{slug}' not found")

    # Enrich with deployment status (same logic as /api/services/available)
    deployments = await database.get_deployments()
    deployed_slugs = {d["slug"] for d in deployments}
    worker_containers = await _get_all_worker_containers()
    worker_slugs = {c["slug"] for c in worker_containers if c.get("slug")}
    worker_nodes: set[str] = set()
    for c in worker_containers:
        if c.get("slug") == slug:
            worker_nodes.add(c.get("_node", "unknown"))

    svc["deployed"] = slug in deployed_slugs or slug in worker_slugs
    svc["node_count"] = len(worker_nodes)

    # Flag whether earnings tracking uses separate credentials (entered in
    # Settings → Collectors), so the deploy UI can tell users the container
    # credentials alone won't populate the in-dashboard balance.
    from app.collectors import COLLECTOR_MAP

    svc["has_collector"] = slug in COLLECTOR_MAP
    return svc


# ---------------------------------------------------------------------------
# API: Container management
# ---------------------------------------------------------------------------


@app.get("/api/status")
async def api_status(request: Request) -> list[dict[str, Any]]:
    """Return container statuses from all workers."""
    _require_auth_api(request)
    return await _get_all_worker_containers()


class DeployRequest(BaseModel):
    env: dict[str, str] = {}
    hostname: str | None = None


@app.post("/api/deploy/{slug}")
async def api_deploy(request: Request, slug: str, body: DeployRequest, worker_id: int | None = None) -> dict[str, str]:
    _require_owner(request)
    worker_id = await _resolve_worker_id(worker_id)
    svc = catalog.get_service(slug)
    if not svc:
        raise HTTPException(status_code=404, detail=f"Service '{slug}' not found")
    if svc.get("status") == "dead":
        raise HTTPException(status_code=410, detail=f"Service '{slug}' is no longer available (dead/discontinued)")

    docker_conf = svc.get("docker", {})
    image = docker_conf.get("image")
    if not image:
        raise HTTPException(status_code=400, detail=f"Service '{slug}' has no Docker image")

    # Build full env: YAML defaults + {hostname} substitution + user overrides
    hn = body.hostname or HOSTNAME_PREFIX
    env: dict[str, str] = {}
    for var in docker_conf.get("env", []):
        default = var.get("default", "")
        if default and "{hostname}" in str(default):
            default = str(default).replace("{hostname}", hn)
        env[var["key"]] = str(default)
    env.update(body.env or {})

    # Validate required env vars are not blank
    missing = [
        var.get("label", var["key"])
        for var in docker_conf.get("env", [])
        if var.get("required") and not env.get(var["key"], "").strip()
    ]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required fields: {', '.join(missing)}")

    # Ports — key is "container_port/protocol" per Docker SDK
    ports: dict[str, int] = {}
    for mapping in docker_conf.get("ports", []):
        raw = str(mapping)
        if ":" not in raw:
            continue
        parts = raw.split(":")
        host_port = int(parts[0])
        container_part = parts[1]  # e.g. "28967/tcp" or "28967"
        if "/" not in container_part:
            container_part += "/tcp"
        ports[container_part] = host_port

    # Volumes: resolve ${VAR} in host paths using env
    volumes: dict[str, dict[str, str]] = {}
    for mapping in docker_conf.get("volumes", []):
        if ":" in str(mapping):
            parts = str(mapping).split(":")
            host_path = re.sub(r"\$\{(\w+)\}", lambda m: env.get(m.group(1), m.group(0)), parts[0])
            container_path = parts[1]
            mode = parts[2] if len(parts) > 2 else "rw"
            volumes[host_path] = {"bind": container_path, "mode": mode}

    spec: dict[str, Any] = {
        "image": image,
        "env": env,
        "hostname": body.hostname,
        "ports": ports,
        "volumes": volumes,
        "network_mode": docker_conf.get("network_mode") or None,
        "cap_add": docker_conf.get("cap_add") or None,
        "privileged": docker_conf.get("privileged", False),
    }

    # Command: resolve ${VAR} placeholders
    raw_command = docker_conf.get("command") or None
    if raw_command:
        spec["command"] = re.sub(r"\$\{(\w+)\}", lambda m: env.get(m.group(1), m.group(0)), raw_command)

    # Durable resource limits (mem_limit / mem_reservation / oom_score_adj),
    # declared in the service YAML. Only forwarded when present.
    resources = docker_conf.get("resources")
    if resources:
        spec["resources"] = resources

    result = await _proxy_worker_deploy(worker_id, slug, spec)
    container_id = result.get("container_id", "remote")
    await database.save_deployment(slug=slug, container_id=container_id)
    await database.record_health_event(slug, "start", f"deployed to worker {worker_id}")
    metrics.record_container_lifecycle("deploy", slug)
    _spawn(_run_collection())
    return {"status": "deployed", "container_id": container_id}


@app.post("/api/stop/{slug}")
async def api_stop(request: Request, slug: str, worker_id: int | None = None) -> dict[str, str]:
    _require_writer(request)
    worker_id = await _resolve_worker_id(worker_id)
    result = await _proxy_worker_command(worker_id, "stop", slug)
    await database.record_health_event(slug, "stop")
    metrics.record_container_lifecycle("stop", slug)
    return result


@app.post("/api/restart/{slug}")
async def api_restart(request: Request, slug: str, worker_id: int | None = None) -> dict[str, str]:
    _require_writer(request)
    worker_id = await _resolve_worker_id(worker_id)
    result = await _proxy_worker_command(worker_id, "restart", slug)
    await database.record_health_event(slug, "restart")
    metrics.record_container_lifecycle("restart", slug)
    return result


@app.delete("/api/remove/{slug}")
async def api_remove(
    request: Request, slug: str, worker_id: int | None = None, delete_volumes: bool = False
) -> dict[str, Any]:
    _require_writer(request)
    worker_id = await _resolve_worker_id(worker_id)
    params = {"delete_volumes": "true"} if delete_volumes else None
    result = await _proxy_worker_command(worker_id, "remove", slug, params=params)
    await database.remove_deployment(slug)
    await database.record_health_event(slug, "remove")
    metrics.record_container_lifecycle("remove", slug)
    return result


# ---------------------------------------------------------------------------
# Helpers: proxy commands / logs to worker nodes
# ---------------------------------------------------------------------------

_ALLOWED_WORKER_SCHEMES = {"http", "https"}

# SSRF guard for worker URLs. The worker `url` arrives in the (fleet-key-authed)
# heartbeat body and is later fetched WITH the fleet bearer token attached, so an
# attacker holding the fleet key could otherwise turn the UI into a confused-deputy
# proxy into the internal network. Policy is OPT-IN: the default ("permissive")
# preserves today's behaviour — LAN (RFC1918) and Tailscale (CGNAT 100.64.0.0/10)
# workers keep working out of the box — while always closing the free gaps
# (cloud-metadata IPs, IPv6 loopback/link-local, IPv4-mapped bypasses, DNS rebinding).
# "strict" mode restricts to CASHPILOT_WORKER_ALLOWED_HOSTS (CIDRs + *.suffix names).
_WORKER_URL_POLICY = os.getenv("CASHPILOT_WORKER_URL_POLICY", "permissive").strip().lower()
_WORKER_ALLOW_METADATA = os.getenv("CASHPILOT_WORKER_ALLOW_METADATA", "false").strip().lower() == "true"

# Cloud metadata endpoints — never a valid worker; always blocked (unless the
# explicit escape hatch is set). The IPv6 one is inside ULA fd00::/8 so a
# "permissive" policy would otherwise allow it.
_METADATA_IPS = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),  # AWS/GCP/Azure IMDS (IPv4)
        ipaddress.ip_address("fd00:ec2::254"),  # AWS IMDS over IPv6
    }
)
# Loopback + link-local, IPv4 and IPv6 — always blocked.
_BLOCKED_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
)


def _parse_worker_allowlist() -> tuple[list[ipaddress._BaseNetwork], list[str], set[str]]:
    """Parse CASHPILOT_WORKER_ALLOWED_HOSTS into (cidrs, host_suffixes, exact_hosts)."""
    cidrs: list[ipaddress._BaseNetwork] = []
    suffixes: list[str] = []
    exact: set[str] = set()
    for entry in os.getenv("CASHPILOT_WORKER_ALLOWED_HOSTS", "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        if entry.startswith("*."):
            suffixes.append(entry[2:].lower())
            continue
        try:
            cidrs.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            exact.add(entry.lower())
    return cidrs, suffixes, exact


_WORKER_ALLOWED_CIDRS, _WORKER_ALLOWED_SUFFIXES, _WORKER_ALLOWED_HOSTS = _parse_worker_allowlist()


def _normalize_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address):
    """Collapse IPv4-mapped IPv6 (::ffff:a.b.c.d) to the underlying IPv4 address."""
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def _assert_ip_not_blocked(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    """Always-on checks: metadata + loopback/link-local, regardless of policy."""
    addr = _normalize_ip(addr)
    if not _WORKER_ALLOW_METADATA and addr in _METADATA_IPS:
        raise HTTPException(status_code=400, detail="Worker URL points to a cloud metadata address")
    for net in _BLOCKED_NETWORKS:
        if addr.version == net.version and addr in net:
            raise HTTPException(status_code=400, detail="Worker URL points to loopback/link-local address")


def _assert_ip_strict_allowed(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    """In strict mode, the resolved IP must fall inside an allowed CIDR."""
    addr = _normalize_ip(addr)
    if any(addr.version == c.version and addr in c for c in _WORKER_ALLOWED_CIDRS):
        return
    raise HTTPException(status_code=400, detail="Worker URL not in allowed hosts (strict mode)")


def _validate_worker_url(raw_url: str) -> str:
    """Validate and return a safe worker URL; raise 400 on SSRF-risky targets.

    Resolves hostnames and validates the resolved IP(s) so a DNS name that
    points at a metadata/loopback address is rejected (DNS-rebinding guard).
    Synchronous — its only blocking op is DNS resolution; event-loop callers
    MUST invoke it via ``asyncio.to_thread`` (see _get_verified_worker_url) so a
    slow/hanging resolver never blocks the whole UI.
    """
    parsed = urlparse(raw_url)
    if parsed.scheme not in _ALLOWED_WORKER_SCHEMES:
        raise HTTPException(status_code=400, detail=f"Invalid worker URL scheme: {parsed.scheme}")
    host = parsed.hostname or ""
    if not host:
        raise HTTPException(status_code=400, detail="Worker URL has no host")
    if host in ("localhost", "localhost.localdomain"):
        raise HTTPException(status_code=400, detail="Worker URL points to localhost")

    # Case A: literal IP — classify directly, no DNS needed.
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    if addr is not None:
        _assert_ip_not_blocked(addr)
        if _WORKER_URL_POLICY == "strict":
            _assert_ip_strict_allowed(addr)
        return raw_url.rstrip("/")

    # Case B: hostname. In strict mode an explicit name/suffix match short-circuits
    # the CIDR check (so Tailscale MagicDNS names work by name), but the resolved
    # IPs are still checked against the always-blocked set.
    hostname_allowed = host.lower() in _WORKER_ALLOWED_HOSTS or any(
        host.lower() == s or host.lower().endswith("." + s) for s in _WORKER_ALLOWED_SUFFIXES
    )
    try:
        infos = socket.getaddrinfo(host, parsed.port, proto=socket.IPPROTO_TCP)
        resolved = {ipaddress.ip_address(info[4][0]) for info in infos}
    except (socket.gaierror, ValueError):
        # Unresolvable: fatal in strict (can't prove it's allowed), non-fatal in
        # permissive (the request itself will fail if the host is truly dead; we
        # don't want a transiently-unresolvable worker to hard-400).
        if _WORKER_URL_POLICY == "strict" and not hostname_allowed:
            raise HTTPException(status_code=400, detail="Worker URL host does not resolve") from None
        return raw_url.rstrip("/")

    for addr in resolved:
        _assert_ip_not_blocked(addr)
    if _WORKER_URL_POLICY == "strict" and not hostname_allowed:
        for addr in resolved:
            _assert_ip_strict_allowed(addr)
    return raw_url.rstrip("/")


async def _get_verified_worker_url(worker: dict[str, Any]) -> tuple[str, dict[str, str]]:
    """Validate a worker record and return (url, headers)."""
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    if worker["status"] != "online":
        raise HTTPException(status_code=503, detail="Worker is offline")
    if not worker["url"]:
        raise HTTPException(status_code=503, detail="Worker URL not known")
    url = await asyncio.to_thread(_validate_worker_url, worker["url"])
    headers: dict[str, str] = {}
    if FLEET_API_KEY:
        headers["Authorization"] = f"Bearer {FLEET_API_KEY}"
    return url, headers


async def _proxy_worker_command(
    worker_id: int, command: str, slug: str, *, params: dict[str, str] | None = None
) -> dict[str, Any]:
    """Forward a container command (restart/stop/start/remove) to a worker."""
    worker = await database.get_worker(worker_id)
    url, headers = await _get_verified_worker_url(worker)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if command == "remove":
                resp = await client.delete(f"{url}/api/containers/{slug}", headers=headers, params=params)
            else:
                resp = await client.post(f"{url}/api/containers/{slug}/{command}", headers=headers)
            if resp.status_code >= 400:
                logger.warning("worker proxy error (%s): %s", resp.status_code, resp.text)
                raise HTTPException(status_code=resp.status_code, detail="Worker request failed")
            return resp.json()
    except httpx.HTTPError as exc:
        logger.warning("worker proxy error: %s", exc)
        raise HTTPException(status_code=503, detail="Worker communication failed")


async def _proxy_worker_deploy(worker_id: int, slug: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Forward a deploy command with full spec to a worker."""
    worker = await database.get_worker(worker_id)
    url, headers = await _get_verified_worker_url(worker)

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{url}/api/containers/{slug}/deploy", json=spec, headers=headers)
            if resp.status_code >= 400:
                logger.warning("worker deploy error (%s): %s", resp.status_code, resp.text)
                raise HTTPException(status_code=resp.status_code, detail="Worker request failed")
            return resp.json()
    except httpx.HTTPError as exc:
        logger.warning("worker proxy error: %s", exc)
        raise HTTPException(status_code=503, detail="Worker communication failed")


async def _proxy_worker_logs(worker_id: int, slug: str, lines: int = 50) -> dict[str, str]:
    """Forward a logs request to a worker."""
    worker = await database.get_worker(worker_id)
    url, headers = await _get_verified_worker_url(worker)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{url}/api/containers/{slug}/logs",
                params={"lines": min(lines, 1000)},
                headers=headers,
            )
            if resp.status_code >= 400:
                logger.warning("worker proxy error (%s): %s", resp.status_code, resp.text)
                raise HTTPException(status_code=resp.status_code, detail="Worker request failed")
            return resp.json()
    except httpx.HTTPError as exc:
        logger.warning("worker proxy error: %s", exc)
        raise HTTPException(status_code=503, detail="Worker communication failed")


# ---------------------------------------------------------------------------
# API: Service management (new-style routes matching frontend)
# ---------------------------------------------------------------------------


@app.post("/api/services/{slug}/restart")
async def api_service_restart(request: Request, slug: str, worker_id: int | None = None) -> dict[str, str]:
    _require_writer(request)
    worker_id = await _resolve_worker_id(worker_id)
    result = await _proxy_worker_command(worker_id, "restart", slug)
    await database.record_health_event(slug, "restart")
    metrics.record_container_lifecycle("restart", slug)
    return result


@app.post("/api/services/{slug}/stop")
async def api_service_stop(request: Request, slug: str, worker_id: int | None = None) -> dict[str, str]:
    _require_writer(request)
    worker_id = await _resolve_worker_id(worker_id)
    result = await _proxy_worker_command(worker_id, "stop", slug)
    await database.record_health_event(slug, "stop")
    metrics.record_container_lifecycle("stop", slug)
    return result


@app.post("/api/services/{slug}/start")
async def api_service_start(request: Request, slug: str, worker_id: int | None = None) -> dict[str, str]:
    _require_writer(request)
    worker_id = await _resolve_worker_id(worker_id)
    result = await _proxy_worker_command(worker_id, "start", slug)
    await database.record_health_event(slug, "start")
    metrics.record_container_lifecycle("start", slug)
    return result


@app.get("/api/services/{slug}/logs")
async def api_service_logs(
    request: Request, slug: str, lines: int = 50, worker_id: int | None = None
) -> dict[str, str]:
    _require_writer(request)
    worker_id = await _resolve_worker_id(worker_id)
    return await _proxy_worker_logs(worker_id, slug, lines)


@app.delete("/api/services/{slug}")
async def api_service_remove(
    request: Request, slug: str, worker_id: int | None = None, delete_volumes: bool = False
) -> dict[str, Any]:
    _require_writer(request)
    worker_id = await _resolve_worker_id(worker_id)
    params = {"delete_volumes": "true"} if delete_volumes else None
    result = await _proxy_worker_command(worker_id, "remove", slug, params=params)
    await database.remove_deployment(slug)
    await database.record_health_event(slug, "remove")
    metrics.record_container_lifecycle("remove", slug)
    return result


# ---------------------------------------------------------------------------
# API: Compose export
# ---------------------------------------------------------------------------


@app.get("/api/compose/{slug}", response_class=PlainTextResponse)
async def api_compose_single(request: Request, slug: str):
    """Export a docker-compose.yml for a single service."""
    _require_auth_api(request)
    svc = catalog.get_service(slug)
    if not svc:
        raise HTTPException(status_code=404, detail=f"Service '{slug}' not found")
    try:
        return compose_generator.generate_compose_single(slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class ComposeMultiRequest(BaseModel):
    slugs: list[str]


@app.post("/api/compose", response_class=PlainTextResponse)
async def api_compose_multi(request: Request, body: ComposeMultiRequest):
    """Export a docker-compose.yml for multiple services."""
    _require_auth_api(request)
    try:
        return compose_generator.generate_compose_multi(body.slugs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/compose", response_class=PlainTextResponse)
async def api_compose_all(request: Request):
    """Export a docker-compose.yml for ALL services with Docker images."""
    _require_auth_api(request)
    try:
        return compose_generator.generate_compose_all()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# API: Earnings
# ---------------------------------------------------------------------------


@app.get("/api/earnings")
async def api_earnings(request: Request) -> list[dict[str, Any]]:
    _require_auth_api(request)
    return await database.get_earnings_summary()


@app.get("/api/earnings/summary")
async def api_earnings_summary(request: Request) -> dict[str, Any]:
    """Aggregated earnings stats for the dashboard."""
    _require_auth_api(request)
    summary = await database.get_earnings_dashboard_summary()

    # Load config for signup bonus offsets
    all_config = await database.get_config()
    if not isinstance(all_config, dict):
        all_config = {}

    # Include non-USD balances converted to USD in the total.
    # Compute total_adjusted as the sum of clamped per-service adjusted
    # balances (converted to USD) so it always matches the breakdown view.
    all_earnings = await database.get_earnings_summary()
    total_bonus_usd = 0.0
    total_adjusted = 0.0
    for e in all_earnings:
        slug = e.get("platform", "")
        balance = float(e["balance"])
        currency = e["currency"]

        bonus = 0.0
        with contextlib.suppress(ValueError, TypeError):
            bonus = float(all_config.get(f"{slug}_signup_bonus", "0") or "0")
        adjusted = max(0.0, balance - bonus)

        if currency != "USD":
            usd_val = exchange_rates.to_usd(balance, currency)
            if usd_val is not None:
                summary["total"] = round(summary["total"] + usd_val, 2)
            adj_usd = exchange_rates.to_usd(adjusted, currency)
            if adj_usd is not None:
                total_adjusted += adj_usd
            bonus_usd = exchange_rates.to_usd(bonus, currency) if bonus > 0 else 0.0
            if bonus_usd is not None:
                total_bonus_usd += bonus_usd
        else:
            total_adjusted += adjusted
            total_bonus_usd += bonus

    # Count active (running) services from worker data
    active = 0
    try:
        worker_containers = await _get_all_worker_containers()
        active = sum(1 for s in worker_containers if s.get("status") == "running")
    except Exception as exc:
        logger.debug("active-service count failed: %s", exc)
    summary["active_services"] = active
    summary["total_bonus"] = round(total_bonus_usd, 2)
    summary["total_adjusted"] = round(total_adjusted, 2)
    return summary


@app.get("/api/earnings/daily")
async def api_earnings_daily(request: Request, days: int = 7) -> list[dict[str, Any]]:
    """Daily earnings for charting."""
    _require_auth_api(request)
    if days < 1 or days > 365:
        raise HTTPException(status_code=400, detail="days must be between 1 and 365")
    return await database.get_daily_earnings(days)


@app.get("/api/earnings/breakdown")
async def api_earnings_breakdown(request: Request) -> list[dict[str, Any]]:
    """Per-service earnings breakdown with cashout eligibility."""
    _require_auth_api(request)
    rows = await database.get_earnings_per_service()

    # Load config for per-service signup bonus offsets
    all_config = await database.get_config()
    if not isinstance(all_config, dict):
        all_config = {}

    result = []
    for row in rows:
        slug = row["platform"]
        svc = catalog.get_service(slug)
        cashout = (svc.get("cashout", {}) if svc else {}) or {}
        min_amount = float(cashout.get("min_amount", 0))
        balance = float(row["balance"])
        prev_balance = float(row.get("prev_balance", 0))
        delta = balance - prev_balance

        # Signup bonus offset (stored in config as {slug}_signup_bonus)
        signup_bonus = 0.0
        with contextlib.suppress(ValueError, TypeError):
            signup_bonus = float(all_config.get(f"{slug}_signup_bonus", "0") or "0")
        balance_adjusted = round(max(0.0, balance - signup_bonus), 4)

        entry = {
            "platform": slug,
            "name": svc["name"] if svc else slug,
            "balance": round(balance, 4),
            "balance_adjusted": balance_adjusted,
            "signup_bonus": round(signup_bonus, 4),
            "currency": row["currency"],
            "last_updated": row["date"],
            "delta": round(delta, 4),
            "cashout": {
                "eligible": bool(cashout) and balance > 0 and balance >= min_amount,
                "min_amount": min_amount,
                "method": cashout.get("method", "redirect"),
                "dashboard_url": cashout.get("dashboard_url", ""),
                "notes": cashout.get("notes", ""),
            },
        }
        result.append(entry)
    return result


@app.get("/api/earnings/history")
async def api_earnings_history(request: Request, period: str = "week") -> list[dict[str, Any]]:
    _require_auth_api(request)
    if period not in ("week", "month", "year", "all"):
        raise HTTPException(status_code=400, detail="period must be week, month, year, or all")
    return await database.get_earnings_history(period)


@app.get("/api/health/scores")
async def api_health_scores(request: Request, days: int = 7) -> list[dict[str, Any]]:
    """Health scores for all services."""
    _require_auth_api(request)
    if days < 1 or days > 90:
        raise HTTPException(status_code=400, detail="days must be between 1 and 90")
    scores = await database.get_health_scores(days)
    # Enrich with service names
    for s in scores:
        svc = catalog.get_service(s["slug"])
        s["name"] = svc["name"] if svc else s["slug"]
    return scores


@app.post("/api/collect")
async def api_collect(request: Request) -> dict[str, str]:
    _require_writer(request)
    _spawn(_run_collection())
    return {"status": "collection_started"}


_MAX_ALERT_ERROR_LEN = 200


@app.get("/api/collector-alerts")
async def api_collector_alerts(request: Request) -> list[dict[str, str]]:
    """Return collector errors from the last collection run (sanitized)."""
    _require_auth_api(request)
    sanitized: list[dict[str, str]] = []
    for alert in _collector_alerts:
        error_msg = alert.get("error", "")
        clean = error_msg[:_MAX_ALERT_ERROR_LEN]
        if len(error_msg) > _MAX_ALERT_ERROR_LEN:
            clean += "..."
        sanitized.append({"platform": alert["platform"], "error": clean})
    return sanitized


@app.get("/api/exchange-rates")
async def api_exchange_rates(request: Request) -> dict[str, Any]:
    """Return current exchange rates (fiat + crypto) for frontend conversion."""
    _require_auth_api(request)
    return exchange_rates.get_all()


@app.get("/api/services/{slug}/per-node-earnings")
async def api_per_node_earnings(request: Request, slug: str) -> list[dict[str, Any]]:
    """Return per-node earnings for services that support it (e.g. MystNodes)."""
    _require_auth_api(request)
    config = await database.get_config() or {}
    if not isinstance(config, dict):
        config = {}

    if slug == "mysterium":
        from app.collectors.mystnodes import MystNodesCollector

        collector = MystNodesCollector(
            email=config.get("mysterium_email", ""),
            password=config.get("mysterium_password", ""),
        )
        return await collector.get_per_node_earnings()

    return []


# ---------------------------------------------------------------------------
# API: User Preferences (onboarding state)
# ---------------------------------------------------------------------------


@app.get("/api/preferences")
async def api_get_preferences(request: Request) -> dict[str, Any]:
    user = _require_auth_api(request)
    prefs = await database.get_user_preferences(user["uid"])
    if not prefs:
        return {"setup_mode": "fresh", "selected_categories": "[]", "timezone": "UTC", "setup_completed": False}
    return prefs


class PreferencesUpdate(BaseModel):
    setup_mode: str | None = None
    selected_categories: str | None = None
    timezone: str | None = None
    setup_completed: bool | None = None


@app.post("/api/preferences")
async def api_set_preferences(request: Request, body: PreferencesUpdate) -> dict[str, str]:
    user = _require_auth_api(request)
    if body.setup_mode is not None and body.setup_mode not in ("fresh", "monitoring", "mixed"):
        raise HTTPException(status_code=400, detail="setup_mode must be fresh, monitoring, or mixed")

    # Merge with existing preferences so partial updates don't overwrite
    existing = await database.get_user_preferences(user["uid"]) or {}
    await database.save_user_preferences(
        user_id=user["uid"],
        setup_mode=body.setup_mode if body.setup_mode is not None else existing.get("setup_mode", "fresh"),
        selected_categories=body.selected_categories
        if body.selected_categories is not None
        else existing.get("selected_categories", "[]"),
        timezone=body.timezone if body.timezone is not None else existing.get("timezone", "UTC"),
        setup_completed=body.setup_completed
        if body.setup_completed is not None
        else existing.get("setup_completed", False),
    )
    # If setup is completed, trigger an immediate collection
    if body.setup_completed:
        _spawn(_run_collection())
    return {"status": "saved"}


# ---------------------------------------------------------------------------
# API: Environment Info
# ---------------------------------------------------------------------------


@app.get("/api/env-info")
async def api_env_info(request: Request) -> list[dict[str, Any]]:
    _require_owner(request)
    # (key, label, secret, read_only, default, description)
    env_defs = [
        ("CASHPILOT_API_KEY", "Fleet API Key", True, False, "", "Bearer token for worker-to-UI authentication"),
        (
            "CASHPILOT_SECRET_KEY",
            "Session Secret Key",
            True,
            False,
            "changeme-generate-a-random-secret",
            "Secret for JWT session tokens — change from default for security",
        ),
        (
            "CASHPILOT_HOSTNAME_PREFIX",
            "Hostname Prefix",
            False,
            False,
            "cashpilot",
            "Containers named {prefix}-{service}",
        ),
        (
            "CASHPILOT_COLLECT_INTERVAL",
            "Collect Interval (min)",
            False,
            False,
            "60",
            "Minutes between automatic earnings collection",
        ),
        ("CASHPILOT_DATA_DIR", "Data Directory", False, True, "/data", "Directory containing the SQLite database"),
        ("TZ", "System Timezone", False, False, "", "Container timezone in IANA format (e.g. Europe/Madrid)"),
    ]
    result = []
    for key, label, secret, read_only, default, desc in env_defs:
        raw = os.getenv(key, "")
        entry: dict[str, Any] = {
            "key": key,
            "label": label,
            "secret": secret,
            "read_only": read_only,
            "description": desc,
            "set_via_env": bool(raw),
        }
        if key == "CASHPILOT_SECRET_KEY":
            # Auth always resolves a key at runtime (env, persisted, or generated),
            # so it is effectively always set; never expose its value and treat as
            # read-only in the UI.
            entry["is_set"] = True
            entry["read_only"] = True
        elif secret:
            # Drop the value for secrets — only report presence.
            entry["is_set"] = bool(raw)
        else:
            entry["value"] = raw or default
        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# API: Collectors Metadata
# ---------------------------------------------------------------------------


@app.get("/api/collectors/meta")
async def api_collectors_meta(request: Request) -> list[dict[str, Any]]:
    _require_owner(request)
    from app.collectors import _COLLECTOR_ARGS, COLLECTOR_MAP

    # Single-sourced from database.SECRET_CONFIG_KEYS so this endpoint can never
    # disagree with the encryption-at-rest / masking logic about which config
    # keys are secret (a hand-maintained duplicate here previously missed
    # `remember_web` and `xsrf_token`, unmasking them).
    secret_args = database.SECRET_CONFIG_KEYS
    # Per-service hints on how to obtain the credentials
    hints: dict[str, str] = {
        "bitping": "Use your Bitping account email and password (same as <a href='https://nodes.bitping.com' target='_blank'>nodes.bitping.com</a>).",
        "bytelixir": "Log in at <a href='https://dash.bytelixir.com' target='_blank'>dash.bytelixir.com</a> (tick Remember Me), press F12 → Application → expand <b>Cookies</b> in the left sidebar → click <code>https://dash.bytelixir.com</code> → find <b>bytelixir_session</b> → copy its Value.",
        "earnapp": "Log in at <a href='https://earnapp.com' target='_blank'>earnapp.com</a>, press F12 → Application → Cookies, copy the <b>oauth-refresh-token</b> value.",
        "earnfm": "Use your Earn.fm account email and password (same as <a href='https://app.earn.fm' target='_blank'>app.earn.fm</a> login).",
        "grass": "Log in at <a href='https://app.getgrass.io' target='_blank'>app.getgrass.io</a>, press F12 → Application → Local Storage, copy the <b>accessToken</b> value.",
        "honeygain": "Use your Honeygain account email and password (same as <a href='https://dashboard.honeygain.com' target='_blank'>dashboard.honeygain.com</a>).",
        "iproyal": "Use your IPRoyal Pawns account email and password (same as <a href='https://pawns.app' target='_blank'>pawns.app</a>).",
        "mysterium": "Use your MystNodes account email and password (same as <a href='https://my.mystnodes.com' target='_blank'>my.mystnodes.com</a>).",
        "packetstream": "Log in at <a href='https://packetstream.io' target='_blank'>packetstream.io</a>, press F12 → Application → Cookies, copy the <b>auth</b> cookie value (it’s a JWT).",
        "proxyrack": "Log in at <a href='https://peer.proxyrack.com' target='_blank'>peer.proxyrack.com</a>, press F12 → Network, find any API request and copy the <b>Api-Key</b> header value.",
        "repocket": "Use your Repocket account email and password (same as <a href='https://app.repocket.com' target='_blank'>app.repocket.com</a>).",
        "salad": "Log in at <a href='https://app.salad.com' target='_blank'>app.salad.com</a>, press F12 → Application → Cookies, copy the <b>auth</b> cookie value.",
        "traffmonetizer": "Log in at <a href='https://app.traffmonetizer.com' target='_blank'>app.traffmonetizer.com</a>, press F12 → Application → Local Storage → <b>token</b> value (a long JWT starting with <code>eyJ</code>).",
    }
    meta = []
    for slug in sorted(COLLECTOR_MAP.keys()):
        args = _COLLECTOR_ARGS.get(slug, [])
        svc = catalog.get_service(slug)
        name = svc.get("name", slug) if svc else slug
        fields = []
        for arg in args:
            optional = arg.startswith("?")
            arg_name = arg.lstrip("?")
            config_key = f"{slug}_{arg_name}"
            fields.append(
                {
                    "key": config_key,
                    "label": arg_name.replace("_", " ").title(),
                    "secret": arg_name in secret_args,
                    "required": not optional,
                }
            )
        # Payment currency for bonus offset labeling
        payment = (svc.get("payment", {}) if svc else {}) or {}
        pay_currency = payment.get("currency", "USD")

        entry: dict[str, Any] = {"slug": slug, "name": name, "fields": fields, "currency": pay_currency}
        if slug in hints:
            entry["hint"] = hints[slug]
        meta.append(entry)
    return meta


# ---------------------------------------------------------------------------
# API: Config
# ---------------------------------------------------------------------------


@app.get("/api/config")
async def api_get_config(request: Request) -> dict[str, Any]:
    _require_owner(request)
    # Masked read path: non-secret values plus a {secret_key: is_set} map under
    # "_secrets". Stored credentials never cross the wire in plaintext.
    return await database.get_config_masked()


class ConfigUpdate(BaseModel):
    data: dict[str, str]


def _sanitize_credential(value: str) -> str:
    """Clean common copy-paste artifacts from credential values."""
    from urllib.parse import unquote

    v = value.strip()
    if v.startswith('"') and v.endswith('"'):
        v = v[1:-1]
    if v.startswith("'") and v.endswith("'"):
        v = v[1:-1]
    if "%3D" in v or "%3d" in v or "%2F" in v or "%2f" in v or "%2B" in v or "%2b" in v:
        v = unquote(v)
    return v


@app.post("/api/config")
async def api_set_config(request: Request, body: ConfigUpdate) -> dict[str, str]:
    _require_owner(request)
    sanitized = {k: _sanitize_credential(v) for k, v in body.data.items()}
    await database.set_config_bulk(sanitized)

    # Auto-create "external" deployment records for manual-only services
    # whose collector credentials were just saved.  Without a deployment
    # row, _run_collection() will never instantiate the collector.
    from app.collectors import _COLLECTOR_ARGS

    for slug, arg_keys in _COLLECTOR_ARGS.items():
        required_keys = [f"{slug}_{a.lstrip('?')}" for a in arg_keys if not a.startswith("?")]
        if not required_keys:
            continue
        if not all(sanitized.get(k) for k in required_keys):
            continue
        svc = catalog.get_service(slug)
        if not svc:
            continue
        docker_conf = svc.get("docker", {})
        has_image = bool(docker_conf and docker_conf.get("image"))
        if has_image:
            continue  # Docker services get deployed normally
        existing = await database.get_deployment(slug)
        if not existing:
            await database.save_deployment(slug=slug, container_id="", status="external")
            logger.info("Auto-created external deployment for %s", slug)

    return {"status": "saved"}


@app.delete("/api/config/{slug}")
async def api_clear_service_config(request: Request, slug: str) -> dict[str, str]:
    """Remove all stored credentials (and signup bonus) for a service."""
    _require_owner(request)
    from app.collectors import _COLLECTOR_ARGS

    arg_keys = _COLLECTOR_ARGS.get(slug)
    if not arg_keys:
        raise HTTPException(status_code=404, detail="Unknown service")

    config_keys = [f"{slug}_{a.lstrip('?')}" for a in arg_keys]
    config_keys.append(f"{slug}_signup_bonus")
    await database.delete_config_keys(config_keys)

    # Remove the auto-created "external" deployment record if present
    svc = catalog.get_service(slug)
    if svc:
        docker_conf = svc.get("docker", {})
        if not (docker_conf and docker_conf.get("image")):
            await database.remove_deployment(slug)

    logger.info("Cleared credentials for %s", slug)
    return {"status": "cleared"}


# ---------------------------------------------------------------------------
# API: Users — change password (owner-reset + self-service).
#
# User list/role/delete routes live in app.routers.users. The password routes
# stay here to avoid the direct-import problem (no test imports them directly).
# ---------------------------------------------------------------------------


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class AdminPasswordSet(BaseModel):
    new_password: str


@app.post("/api/users/me/password")
async def api_change_own_password(request: Request, body: PasswordChange) -> JSONResponse:
    """Change the authenticated user's own password (verifies current password)."""
    user = _require_auth_api(request)
    uid = user["uid"]
    if uid == 0:
        raise HTTPException(status_code=400, detail="API-key sessions cannot change a password")
    record = await database.get_user_by_id(uid)
    if not record:
        raise HTTPException(status_code=404, detail="User not found")
    if not auth.verify_password(body.current_password, record["password"]):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    if len(body.new_password) < 10:
        raise HTTPException(status_code=400, detail="Password must be at least 10 characters")
    if body.new_password == body.current_password:
        raise HTTPException(status_code=400, detail="New password must differ from the current password")

    hashed = auth.hash_password(body.new_password)
    await database.update_user_password(uid, hashed)
    changed = await database.get_user_by_id(uid)
    auth.set_user_pwd_epoch(uid, changed["password_changed_at"])
    # Re-mint the session cookie so the caller stays logged in after the epoch bump.
    token = auth.create_session_token(uid, user["u"], user["r"])
    return auth.set_session_cookie(JSONResponse({"status": "password_changed"}), token)


@app.post("/api/users/{user_id}/password")
async def api_admin_set_password(request: Request, user_id: int, body: AdminPasswordSet) -> dict[str, str]:
    """Owner resets another user's password (no current-password check, no re-mint)."""
    _require_owner(request)
    target = await database.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if len(body.new_password) < 10:
        raise HTTPException(status_code=400, detail="Password must be at least 10 characters")
    hashed = auth.hash_password(body.new_password)
    await database.update_user_password(user_id, hashed)
    changed = await database.get_user_by_id(user_id)
    auth.set_user_pwd_epoch(user_id, changed["password_changed_at"])
    return {"status": "password_set"}


# ---------------------------------------------------------------------------
# API: Fleet (Workers)
# ---------------------------------------------------------------------------


def _bearer_token(request: Request) -> str:
    """Extract the bearer token from an Authorization header (empty if absent)."""
    h = request.headers.get("Authorization", "")
    return h[7:] if h.startswith("Bearer ") else ""


def _verify_fleet_api_key(request: Request) -> None:
    """Verify the shared fleet (enrollment/bootstrap) API key from a worker."""
    if not FLEET_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Fleet key not configured — set CASHPILOT_API_KEY or mount shared /fleet volume",
        )
    if not hmac.compare_digest(_bearer_token(request).encode(), FLEET_API_KEY.encode()):
        raise HTTPException(status_code=401, detail="Invalid API key")


async def _authenticate_worker_heartbeat(request: Request, cid: str) -> bool:
    """Authenticate a heartbeat; return True if this is an enrollment.

    Cutover model (per-worker fleet keys):
    - A worker with NO stored per-worker key must present the shared fleet key
      (the enrollment/bootstrap credential) → returns True so the caller mints and
      stores this worker's own key and hands it back once.
    - A worker that already has a per-worker key MUST present it (verified against
      the stored hash); the shared key is rejected here → returns False. This is
      what stops a holder of the shared key from impersonating an enrolled worker.
    """
    if not FLEET_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Fleet key not configured — set CASHPILOT_API_KEY or mount shared /fleet volume",
        )
    token = _bearer_token(request)
    stored = await database.get_worker_key_hash(cid) if cid else None
    if stored is None:
        # Unenrolled → shared bootstrap key required.
        if token and hmac.compare_digest(token.encode(), FLEET_API_KEY.encode()):
            return True
        raise HTTPException(status_code=401, detail="Invalid API key")
    # Enrolled → this worker's own key required; the shared key no longer works.
    if token and hmac.compare_digest(database.hash_worker_key(token).encode(), stored.encode()):
        return False
    raise HTTPException(status_code=401, detail="Invalid or missing per-worker key")


class WorkerHeartbeat(BaseModel):
    name: str
    url: str = ""
    client_id: str = ""
    containers: list[dict[str, Any]] = []
    apps: list[dict[str, Any]] = []
    system_info: dict[str, Any] = {}


@app.post("/api/workers/heartbeat")
async def api_worker_heartbeat(request: Request, body: WorkerHeartbeat) -> dict[str, Any]:
    """Receive a heartbeat from a worker. Registers or updates the worker."""
    # Use client_id for identity; fall back to name for backward compat
    cid = body.client_id or body.name
    enrolling = await _authenticate_worker_heartbeat(request, cid)
    worker_id = await database.upsert_worker(
        client_id=cid,
        name=body.name,
        url=body.url,
        containers=json.dumps(body.containers),
        apps=json.dumps(body.apps),
        system_info=json.dumps(body.system_info),
    )
    metrics.record_heartbeat(body.name)
    resp: dict[str, Any] = {"status": "ok", "worker_id": worker_id}
    if enrolling:
        # First contact from this worker: mint its own key, store only the hash,
        # and return the key once so the worker can persist + use it thereafter.
        new_key = secrets.token_urlsafe(32)
        await database.set_worker_key_hash(cid, database.hash_worker_key(new_key))
        resp["worker_key"] = new_key
        logger.info("Worker '%s' enrolled with its own per-worker fleet key", cid)
    return resp


@app.get("/api/workers")
async def api_list_workers(request: Request) -> list[dict[str, Any]]:
    """List all registered workers."""
    _require_auth_api(request)
    workers = await database.list_workers()
    for w in workers:
        _parse_worker_json(w)
    return workers


def _parse_worker_json(w: dict[str, Any]) -> None:
    """Parse stored JSON columns and compute counts for a worker dict."""
    w["containers"] = _safe_json(w.get("containers", "[]"))
    w["apps"] = _safe_json(w.get("apps", "[]"))
    w["system_info"] = _safe_json(w.get("system_info", "{}"), {})
    is_android = w["system_info"].get("device_type") == "android"
    if is_android:
        w["container_count"] = len(w["apps"])
        w["running_count"] = sum(1 for a in w["apps"] if a.get("running"))
    else:
        w["container_count"] = len(w["containers"])
        w["running_count"] = sum(1 for c in w["containers"] if c.get("status") == "running")


@app.get("/api/workers/{worker_id}")
async def api_get_worker(request: Request, worker_id: int) -> dict[str, Any]:
    """Get details for a specific worker."""
    _require_auth_api(request)
    worker = await database.get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    _parse_worker_json(worker)
    return worker


@app.delete("/api/workers/{worker_id}")
async def api_delete_worker(request: Request, worker_id: int) -> dict[str, str]:
    """Remove a registered worker."""
    _require_owner(request)
    worker = await database.get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    await database.delete_worker(worker_id)
    return {"status": "deleted"}


class WorkerCommand(BaseModel):
    command: str  # deploy, stop, restart, start, remove
    slug: str = ""
    spec: dict[str, Any] = {}


@app.post("/api/workers/{worker_id}/command")
async def api_worker_command(request: Request, worker_id: int, body: WorkerCommand) -> dict[str, Any]:
    """Send a command to a worker by proxying to its REST API."""
    # Deploy is owner-gated everywhere else (see /api/deploy/{slug}); a writer
    # must not be able to bypass that gate by sending command="deploy" here.
    if body.command == "deploy":
        _require_owner(request)
    else:
        _require_writer(request)

    worker = await database.get_worker(worker_id)
    url, headers = await _get_verified_worker_url(worker)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if body.command == "deploy":
                resp = await client.post(
                    f"{url}/api/containers/{body.slug}/deploy",
                    json=body.spec,
                    headers=headers,
                )
            elif body.command in ("stop", "restart", "start"):
                resp = await client.post(
                    f"{url}/api/containers/{body.slug}/{body.command}",
                    headers=headers,
                )
            elif body.command == "remove":
                resp = await client.delete(
                    f"{url}/api/containers/{body.slug}",
                    headers=headers,
                )
            else:
                raise HTTPException(status_code=400, detail=f"Unknown command: {body.command}")

            if resp.status_code >= 400:
                logger.warning("worker proxy error (%s): %s", resp.status_code, resp.text)
                raise HTTPException(status_code=resp.status_code, detail="Worker request failed")
            return resp.json()
    except httpx.HTTPError as exc:
        logger.warning("worker proxy error: %s", exc)
        raise HTTPException(status_code=503, detail="Worker communication failed")


@app.get("/api/fleet/summary")
async def api_fleet_summary(request: Request) -> dict[str, Any]:
    """Aggregate fleet stats across local + all workers."""
    _require_auth_api(request)

    workers = await database.list_workers()
    total_services = 0
    total_running = 0
    online_workers = 0

    for w in workers:
        if w["status"] != "online":
            continue
        online_workers += 1
        _parse_worker_json(w)
        total_services += w["container_count"]
        total_running += w["running_count"]

    return {
        "total_workers": len(workers),
        "online_workers": online_workers,
        "total_containers": total_services,
        "running_containers": total_running,
    }


@app.get("/api/fleet/api-key")
async def api_fleet_api_key(request: Request) -> dict[str, Any]:
    """Report whether a fleet API key is configured (owner only).

    Never returns the key value — use POST /api/fleet/api-key/reveal for that.
    """
    _require_owner(request)
    source = "env" if os.getenv("CASHPILOT_API_KEY") else ("file" if FLEET_API_KEY else "none")
    return {"is_set": bool(FLEET_API_KEY), "source": source}


@app.post("/api/fleet/api-key/reveal")
async def api_fleet_api_key_reveal(request: Request) -> dict[str, str]:
    """Reveal the configured fleet API key (owner only, audit-logged)."""
    user = _require_owner(request)
    logger.warning("Fleet key revealed by uid=%s", user.get("uid"))
    return {"api_key": FLEET_API_KEY or ""}


# ---------------------------------------------------------------------------
# Router groups (auth / pages / users)
#
# Imported and included LAST, after ``app`` and every shared symbol above is
# defined, so the handlers (which reference state via ``app.main.*``) resolve
# correctly. Kept here to preserve the public ``app.main`` test surface while
# splitting the low-regression route groups into app.routers.
# ---------------------------------------------------------------------------
from app.routers import auth as auth_router  # noqa: E402
from app.routers import pages as pages_router  # noqa: E402
from app.routers import users as users_router  # noqa: E402

app.include_router(auth_router.router)
app.include_router(pages_router.router)
app.include_router(users_router.router)
