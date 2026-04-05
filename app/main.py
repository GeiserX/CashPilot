"""CashPilot — FastAPI application.

Self-hosted passive income dashboard: service catalog, Docker container
management, and earnings tracking.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app import auth, catalog, compose_generator, database, exchange_rates, fleet_key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# In-memory store for the latest collector alerts (errors from last run)
_collector_alerts: list[dict[str, str]] = []


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

        # Docker containers (from Docker-based workers)
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
        logger.debug("Health check skipped: %s", exc)


async def _run_collection() -> None:
    """Collect earnings from all deployed services that have collectors."""
    global _collector_alerts
    try:
        deployments = await database.get_deployments()
        config = await database.get_config() or {}
        if not isinstance(config, dict):
            config = {}
        collectors = __import__("app.collectors", fromlist=["make_collectors"]).make_collectors(deployments, config)
        alerts: list[dict[str, str]] = []
        for collector in collectors:
            result = await collector.collect()
            if result.error:
                logger.warning("Collection error for %s: %s", result.platform, result.error)
                alerts.append({"platform": result.platform, "error": result.error})
            else:
                await database.upsert_earnings(
                    platform=result.platform,
                    balance=result.balance,
                    currency=result.currency,
                )
                logger.info("Collected %s: %.4f %s", result.platform, result.balance, result.currency)
        _collector_alerts = alerts
    except Exception as exc:
        logger.error("Collection run failed: %s", exc)


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
        logger.debug("Data retention error: %s", exc)


async def _check_stale_workers() -> None:
    """Mark workers as offline if they haven't sent a heartbeat recently."""
    try:
        workers = await database.list_workers()
        from datetime import datetime, timedelta

        cutoff = datetime.utcnow() - timedelta(seconds=STALE_WORKER_SECONDS)
        for w in workers:
            if w["status"] == "online" and w.get("last_heartbeat"):
                last = datetime.fromisoformat(w["last_heartbeat"])
                if last < cutoff:
                    await database.set_worker_status(w["id"], "offline")
                    logger.info("Worker '%s' marked offline (last heartbeat: %s)", w["name"], w["last_heartbeat"])
    except Exception as exc:
        logger.debug("Stale worker check error: %s", exc)


FLEET_API_KEY = fleet_key.resolve_fleet_key()
HOSTNAME_PREFIX = os.getenv("CASHPILOT_HOSTNAME_PREFIX", "cashpilot")
COLLECT_INTERVAL_MIN = int(os.getenv("CASHPILOT_COLLECT_INTERVAL", "60"))
STALE_WORKER_SECONDS = 180  # Mark worker offline after 3 missed heartbeats


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await database.init_db()
    catalog.load_services()
    catalog.register_sighup()
    scheduler.add_job(_run_collection, "interval", minutes=COLLECT_INTERVAL_MIN, id="collect")
    scheduler.add_job(_run_health_check, "interval", minutes=5, id="health_check")
    scheduler.add_job(_check_stale_workers, "interval", minutes=2, id="stale_workers")
    scheduler.add_job(_run_data_retention, "interval", hours=24, id="data_retention")
    scheduler.add_job(exchange_rates.refresh, "interval", minutes=15, id="exchange_rates")
    scheduler.start()
    await exchange_rates.refresh()
    asyncio.create_task(_run_collection())
    logger.info("CashPilot UI started (container ops via workers)")

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("CashPilot stopped")


app = FastAPI(
    title="CashPilot",
    version="0.1.0",
    lifespan=lifespan,
)

# Static files and templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _login_redirect() -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


def _require_auth(request: Request) -> dict[str, Any]:
    """Return user dict or raise redirect. For page routes."""
    user = auth.get_current_user(request)
    if not user:
        raise HTTPException(status_code=401)
    return user


def _require_auth_api(request: Request) -> dict[str, Any]:
    """Return user dict or raise 401 for API routes."""
    user = auth.get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _require_writer(request: Request) -> dict[str, Any]:
    user = _require_auth_api(request)
    if not auth.require_role(user, "owner", "writer"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user


def _require_owner(request: Request) -> dict[str, Any]:
    user = _require_auth_api(request)
    if not auth.require_role(user, "owner"):
        raise HTTPException(status_code=403, detail="Owner access required")
    return user


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------


@app.get("/login", response_class=HTMLResponse)
async def page_login(request: Request, error: str = ""):
    # If no users exist, redirect to register
    if not await database.has_any_users():
        return RedirectResponse("/register", status_code=303)
    # If already logged in, go to dashboard
    if auth.get_current_user(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "auth.html",
        {
            "title": "Sign In",
            "subtitle": "Sign in to your CashPilot instance",
            "mode": "login",
            "action": "/login",
            "button_text": "Sign In",
            "error": error,
            "is_first": False,
        },
    )


@app.post("/login")
async def do_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    user = await database.get_user_by_username(username)
    if not user or not auth.verify_password(password, user["password"]):
        return templates.TemplateResponse(
            request,
            "auth.html",
            {
                "title": "Sign In",
                "subtitle": "Sign in to your CashPilot instance",
                "mode": "login",
                "action": "/login",
                "button_text": "Sign In",
                "error": "Invalid username or password",
                "is_first": False,
            },
            status_code=401,
        )

    token = auth.create_session_token(user["id"], user["username"], user["role"])
    response = RedirectResponse("/", status_code=303)
    return auth.set_session_cookie(response, token)


@app.get("/register", response_class=HTMLResponse)
async def page_register(request: Request, error: str = ""):
    is_first = not await database.has_any_users()
    # Only allow registration if first user OR if requester is owner
    if not is_first:
        user = auth.get_current_user(request)
        if not user or user.get("r") != "owner":
            return RedirectResponse("/login", status_code=303)

    return templates.TemplateResponse(
        request,
        "auth.html",
        {
            "title": "Create Account" if is_first else "Add User",
            "subtitle": "Create the first admin account" if is_first else "Add a new user to this instance",
            "mode": "register",
            "action": "/register",
            "button_text": "Create Account",
            "error": error,
            "is_first": is_first,
        },
    )


@app.post("/register")
async def do_register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
):
    is_first = not await database.has_any_users()

    # Only allow registration if first user or owner
    if not is_first:
        user = auth.get_current_user(request)
        if not user or user.get("r") != "owner":
            raise HTTPException(status_code=403, detail="Only owners can add users")

    if password != password_confirm:
        return templates.TemplateResponse(
            request,
            "auth.html",
            {
                "title": "Create Account" if is_first else "Add User",
                "subtitle": "Create the first admin account" if is_first else "Add a new user",
                "mode": "register",
                "action": "/register",
                "button_text": "Create Account",
                "error": "Passwords do not match",
                "is_first": is_first,
            },
            status_code=400,
        )

    if len(password) < 6:
        return templates.TemplateResponse(
            request,
            "auth.html",
            {
                "title": "Create Account" if is_first else "Add User",
                "subtitle": "Create the first admin account" if is_first else "Add a new user",
                "mode": "register",
                "action": "/register",
                "button_text": "Create Account",
                "error": "Password must be at least 6 characters",
                "is_first": is_first,
            },
            status_code=400,
        )

    existing = await database.get_user_by_username(username)
    if existing:
        return templates.TemplateResponse(
            request,
            "auth.html",
            {
                "title": "Create Account" if is_first else "Add User",
                "subtitle": "Create the first admin account" if is_first else "Add a new user",
                "mode": "register",
                "action": "/register",
                "button_text": "Create Account",
                "error": "Username already taken",
                "is_first": is_first,
            },
            status_code=400,
        )

    # First user is always owner
    role = "owner" if is_first else "viewer"
    hashed = auth.hash_password(password)
    user_id = await database.create_user(username, hashed, role)

    token = auth.create_session_token(user_id, username, role)
    # First user goes to onboarding, subsequent users go to dashboard
    dest = "/onboarding" if is_first else "/"
    response = RedirectResponse(dest, status_code=303)
    return auth.set_session_cookie(response, token)


@app.get("/logout")
async def do_logout():
    response = RedirectResponse("/login", status_code=303)
    return auth.clear_session_cookie(response)


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------


@app.get("/onboarding", response_class=HTMLResponse)
async def page_onboarding(request: Request):
    user = auth.get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "onboarding.html")


# ---------------------------------------------------------------------------
# Page routes (HTML) — protected
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def page_dashboard(request: Request):
    user = auth.get_current_user(request)
    if not user:
        # Check if first run
        if not await database.has_any_users():
            return RedirectResponse("/register", status_code=303)
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "dashboard.html", {"user": user})


@app.get("/setup", response_class=HTMLResponse)
async def page_setup(request: Request):
    user = auth.get_current_user(request)
    if not user:
        return _login_redirect()
    return templates.TemplateResponse(request, "setup.html", {"user": user})


@app.get("/catalog", response_class=HTMLResponse)
async def page_catalog(request: Request):
    user = auth.get_current_user(request)
    if not user:
        return _login_redirect()
    return templates.TemplateResponse(request, "catalog.html", {"user": user})


@app.get("/settings", response_class=HTMLResponse)
async def page_settings(request: Request):
    user = auth.get_current_user(request)
    if not user:
        return _login_redirect()
    if not auth.require_role(user, "owner"):
        raise HTTPException(status_code=403, detail="Owner access required")
    return templates.TemplateResponse(request, "settings.html", {"user": user})


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
            "instances": len(agg["instances"]),
            "instance_details": instance_details,
            "collector_disconnected": slug in alert_slugs,
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
            "instances": 0,
            "instance_details": [],
            "collector_disconnected": slug in alert_slugs,
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
        if svc.get("status") in ("broken", "dead"):
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
    _require_writer(request)
    worker_id = await _resolve_worker_id(worker_id)
    svc = catalog.get_service(slug)
    if not svc:
        raise HTTPException(status_code=404, detail=f"Service '{slug}' not found")

    docker_conf = svc.get("docker", {})
    image = docker_conf.get("image")
    if not image:
        raise HTTPException(status_code=400, detail=f"Service '{slug}' has no Docker image")

    # Build full env: YAML defaults + {hostname} substitution + user overrides
    import re

    hn = body.hostname or HOSTNAME_PREFIX
    env: dict[str, str] = {}
    for var in docker_conf.get("env", []):
        default = var.get("default", "")
        if default and "{hostname}" in str(default):
            default = str(default).replace("{hostname}", hn)
        env[var["key"]] = str(default)
    env.update(body.env or {})

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

    result = await _proxy_worker_deploy(worker_id, slug, spec)
    container_id = result.get("container_id", "remote")
    await database.save_deployment(slug=slug, container_id=container_id)
    await database.record_health_event(slug, "start", f"deployed to worker {worker_id}")
    asyncio.create_task(_run_collection())
    return {"status": "deployed", "container_id": container_id}


@app.post("/api/stop/{slug}")
async def api_stop(request: Request, slug: str, worker_id: int | None = None) -> dict[str, str]:
    _require_writer(request)
    worker_id = await _resolve_worker_id(worker_id)
    return await _proxy_worker_command(worker_id, "stop", slug)


@app.post("/api/restart/{slug}")
async def api_restart(request: Request, slug: str, worker_id: int | None = None) -> dict[str, str]:
    _require_writer(request)
    worker_id = await _resolve_worker_id(worker_id)
    return await _proxy_worker_command(worker_id, "restart", slug)


@app.delete("/api/remove/{slug}")
async def api_remove(request: Request, slug: str, worker_id: int | None = None) -> dict[str, str]:
    _require_writer(request)
    worker_id = await _resolve_worker_id(worker_id)
    result = await _proxy_worker_command(worker_id, "remove", slug)
    await database.remove_deployment(slug)
    return result


# ---------------------------------------------------------------------------
# Helpers: proxy commands / logs to worker nodes
# ---------------------------------------------------------------------------


async def _proxy_worker_command(worker_id: int, command: str, slug: str) -> dict[str, str]:
    """Forward a container command (restart/stop/start/remove) to a worker."""
    worker = await database.get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    if worker["status"] != "online":
        raise HTTPException(status_code=503, detail="Worker is offline")
    if not worker["url"]:
        raise HTTPException(status_code=503, detail="Worker URL not known")

    url = worker["url"].rstrip("/")
    headers = {}
    if FLEET_API_KEY:
        headers["Authorization"] = f"Bearer {FLEET_API_KEY}"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if command == "remove":
                resp = await client.delete(f"{url}/api/containers/{slug}", headers=headers)
            else:
                resp = await client.post(f"{url}/api/containers/{slug}/{command}", headers=headers)
            if resp.status_code >= 400:
                detail = (
                    resp.json().get("detail", resp.text)
                    if resp.headers.get("content-type", "").startswith("application/json")
                    else resp.text
                )
                raise HTTPException(status_code=resp.status_code, detail=f"Worker error: {detail}")
            return resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Worker communication failed: {exc}")


async def _proxy_worker_deploy(worker_id: int, slug: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Forward a deploy command with full spec to a worker."""
    worker = await database.get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    if worker["status"] != "online":
        raise HTTPException(status_code=503, detail="Worker is offline")
    if not worker["url"]:
        raise HTTPException(status_code=503, detail="Worker URL not known")

    url = worker["url"].rstrip("/")
    headers = {}
    if FLEET_API_KEY:
        headers["Authorization"] = f"Bearer {FLEET_API_KEY}"

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{url}/api/containers/{slug}/deploy", json=spec, headers=headers)
            if resp.status_code >= 400:
                detail = (
                    resp.json().get("detail", resp.text)
                    if resp.headers.get("content-type", "").startswith("application/json")
                    else resp.text
                )
                raise HTTPException(status_code=resp.status_code, detail=f"Worker deploy error: {detail}")
            return resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Worker communication failed: {exc}")


async def _proxy_worker_logs(worker_id: int, slug: str, lines: int = 50) -> dict[str, str]:
    """Forward a logs request to a worker."""
    worker = await database.get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    if worker["status"] != "online":
        raise HTTPException(status_code=503, detail="Worker is offline")
    if not worker["url"]:
        raise HTTPException(status_code=503, detail="Worker URL not known")

    url = worker["url"].rstrip("/")
    headers = {}
    if FLEET_API_KEY:
        headers["Authorization"] = f"Bearer {FLEET_API_KEY}"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{url}/api/containers/{slug}/logs",
                params={"lines": min(lines, 1000)},
                headers=headers,
            )
            if resp.status_code >= 400:
                detail = (
                    resp.json().get("detail", resp.text)
                    if resp.headers.get("content-type", "").startswith("application/json")
                    else resp.text
                )
                raise HTTPException(status_code=resp.status_code, detail=f"Worker error: {detail}")
            return resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Worker communication failed: {exc}")


# ---------------------------------------------------------------------------
# API: Service management (new-style routes matching frontend)
# ---------------------------------------------------------------------------


@app.post("/api/services/{slug}/restart")
async def api_service_restart(request: Request, slug: str, worker_id: int | None = None) -> dict[str, str]:
    _require_writer(request)
    worker_id = await _resolve_worker_id(worker_id)
    result = await _proxy_worker_command(worker_id, "restart", slug)
    await database.record_health_event(slug, "restart")
    return result


@app.post("/api/services/{slug}/stop")
async def api_service_stop(request: Request, slug: str, worker_id: int | None = None) -> dict[str, str]:
    _require_writer(request)
    worker_id = await _resolve_worker_id(worker_id)
    result = await _proxy_worker_command(worker_id, "stop", slug)
    await database.record_health_event(slug, "stop")
    return result


@app.post("/api/services/{slug}/start")
async def api_service_start(request: Request, slug: str, worker_id: int | None = None) -> dict[str, str]:
    _require_writer(request)
    worker_id = await _resolve_worker_id(worker_id)
    result = await _proxy_worker_command(worker_id, "start", slug)
    await database.record_health_event(slug, "start")
    return result


@app.get("/api/services/{slug}/logs")
async def api_service_logs(
    request: Request, slug: str, lines: int = 50, worker_id: int | None = None
) -> dict[str, str]:
    _require_writer(request)
    worker_id = await _resolve_worker_id(worker_id)
    return await _proxy_worker_logs(worker_id, slug, lines)


@app.delete("/api/services/{slug}")
async def api_service_remove(request: Request, slug: str, worker_id: int | None = None) -> dict[str, str]:
    _require_writer(request)
    worker_id = await _resolve_worker_id(worker_id)
    result = await _proxy_worker_command(worker_id, "remove", slug)
    await database.remove_deployment(slug)
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

    # Include non-USD balances converted to USD in the total
    all_earnings = await database.get_earnings_summary()
    for e in all_earnings:
        if e["currency"] != "USD":
            usd_val = exchange_rates.to_usd(e["balance"], e["currency"])
            if usd_val is not None:
                summary["total"] = round(summary["total"] + usd_val, 2)

    # Count active (running) services from worker data
    active = 0
    try:
        worker_containers = await _get_all_worker_containers()
        active = sum(1 for s in worker_containers if s.get("status") == "running")
    except Exception:
        pass
    summary["active_services"] = active
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

    result = []
    for row in rows:
        slug = row["platform"]
        svc = catalog.get_service(slug)
        cashout = (svc.get("cashout", {}) if svc else {}) or {}
        min_amount = float(cashout.get("min_amount", 0))
        balance = float(row["balance"])
        prev_balance = float(row.get("prev_balance", 0))
        delta = balance - prev_balance

        entry = {
            "platform": slug,
            "name": svc["name"] if svc else slug,
            "balance": round(balance, 4),
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
    asyncio.create_task(_run_collection())
    return {"status": "collection_started"}


@app.get("/api/collector-alerts")
async def api_collector_alerts(request: Request) -> list[dict[str, str]]:
    """Return collector errors from the last collection run."""
    _require_auth_api(request)
    return _collector_alerts


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
        asyncio.create_task(_run_collection())
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
        val = raw or default
        result.append(
            {
                "key": key,
                "label": label,
                "secret": secret,
                "read_only": read_only,
                "description": desc,
                "set_via_env": bool(raw),
                "value": val,
            }
        )
    return result


# ---------------------------------------------------------------------------
# API: Collectors Metadata
# ---------------------------------------------------------------------------


@app.get("/api/collectors/meta")
async def api_collectors_meta(request: Request) -> list[dict[str, Any]]:
    _require_owner(request)
    from app.collectors import _COLLECTOR_ARGS, COLLECTOR_MAP

    secret_args = {
        "password",
        "token",
        "auth_token",
        "access_token",
        "api_key",
        "session_cookie",
        "auth_cookie",
        "oauth_token",
        "brd_sess_id",
    }
    # Per-service hints on how to obtain the credentials
    hints: dict[str, str] = {
        "bitping": "Use your Bitping account email and password (same as nodes.bitping.com).",
        "bytelixir": "Log in at dash.bytelixir.com (tick Remember Me), press F12 → Application → Cookies, copy the <b>bytelixir_session</b> value.",
        "earnapp": "Log in at earnapp.com, press F12 → Application → Cookies, copy the <b>oauth-refresh-token</b> value.",
        "earnfm": "Use your Earn.fm account email and password (same as earn.fm).",
        "grass": "Log in at app.getgrass.io, press F12 → Application → Local Storage, copy the <b>accessToken</b> value.",
        "honeygain": "Use your Honeygain account email and password (same as dashboard.honeygain.com).",
        "iproyal": "Use your IPRoyal Pawns account email and password (same as pawns.app).",
        "mysterium": "Use your MystNodes account email and password (same as my.mystnodes.com).",
        "packetstream": "Log in at packetstream.io, press F12 → Application → Cookies, copy the <b>auth</b> cookie value (it\u2019s a JWT).",
        "proxyrack": "Log in at proxyrack.com, press F12 → Network, find any API request and copy the <b>api_key</b> from the query string.",
        "repocket": "Use your Repocket account email and password (same as app.repocket.com).",
        "salad": "Log in at app.salad.com, press F12 → Application → Cookies, copy the <b>auth</b> cookie value.",
        "traffmonetizer": "Find your token in the Traffmonetizer app or in your Docker container\u2019s <b>TRAFFMONETIZER_TOKEN</b> env variable.",
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
        entry: dict[str, Any] = {"slug": slug, "name": name, "fields": fields}
        if slug in hints:
            entry["hint"] = hints[slug]
        meta.append(entry)
    return meta


# ---------------------------------------------------------------------------
# API: Config
# ---------------------------------------------------------------------------


@app.get("/api/config")
async def api_get_config(request: Request) -> dict[str, str]:
    _require_owner(request)
    result = await database.get_config()
    if isinstance(result, dict):
        return result
    return {}


class ConfigUpdate(BaseModel):
    data: dict[str, str]


@app.post("/api/config")
async def api_set_config(request: Request, body: ConfigUpdate) -> dict[str, str]:
    _require_owner(request)
    await database.set_config_bulk(body.data)

    # Auto-create "external" deployment records for manual-only services
    # whose collector credentials were just saved.  Without a deployment
    # row, _run_collection() will never instantiate the collector.
    from app.collectors import _COLLECTOR_ARGS

    for slug, arg_keys in _COLLECTOR_ARGS.items():
        required_keys = [f"{slug}_{a.lstrip('?')}" for a in arg_keys if not a.startswith("?")]
        if not required_keys:
            continue
        if not all(body.data.get(k) for k in required_keys):
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


# ---------------------------------------------------------------------------
# API: Users (owner only)
# ---------------------------------------------------------------------------


@app.get("/api/users")
async def api_list_users(request: Request) -> list[dict[str, Any]]:
    _require_owner(request)
    return await database.list_users()


class UserRoleUpdate(BaseModel):
    role: str


@app.patch("/api/users/{user_id}")
async def api_update_user_role(request: Request, user_id: int, body: UserRoleUpdate) -> dict[str, str]:
    current = _require_owner(request)
    if body.role not in ("viewer", "writer", "owner"):
        raise HTTPException(status_code=400, detail="Role must be viewer, writer, or owner")
    user = await database.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if current["uid"] == user_id and body.role != "owner":
        raise HTTPException(status_code=400, detail="Cannot demote yourself")
    if user["role"] == "owner" and body.role != "owner":
        all_users = await database.list_users()
        owner_count = sum(1 for u in all_users if u["role"] == "owner")
        if owner_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the last owner")
    await database.update_user_role(user_id, body.role)
    return {"status": "updated"}


@app.delete("/api/users/{user_id}")
async def api_delete_user(request: Request, user_id: int) -> dict[str, str]:
    current = _require_owner(request)
    if current["uid"] == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    user = await database.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await database.delete_user(user_id)
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Page: Fleet dashboard
# ---------------------------------------------------------------------------


@app.get("/fleet", response_class=HTMLResponse)
async def page_fleet(request: Request):
    user = auth.get_current_user(request)
    if not user:
        return _login_redirect()
    return templates.TemplateResponse(request, "fleet.html", {"user": user})


# ---------------------------------------------------------------------------
# API: Fleet (Workers)
# ---------------------------------------------------------------------------


def _verify_fleet_api_key(request: Request) -> None:
    """Verify the shared fleet API key from a worker's request."""
    if not FLEET_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Fleet key not configured — set CASHPILOT_API_KEY or mount shared /fleet volume",
        )
    auth_header = request.headers.get("Authorization", "")
    if auth_header != f"Bearer {FLEET_API_KEY}":
        raise HTTPException(status_code=401, detail="Invalid API key")


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
    _verify_fleet_api_key(request)
    # Use client_id for identity; fall back to name for backward compat
    cid = body.client_id or body.name
    worker_id = await database.upsert_worker(
        client_id=cid,
        name=body.name,
        url=body.url,
        containers=json.dumps(body.containers),
        apps=json.dumps(body.apps),
        system_info=json.dumps(body.system_info),
    )
    return {"status": "ok", "worker_id": worker_id}


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
    _require_writer(request)

    worker = await database.get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    if worker["status"] != "online":
        raise HTTPException(status_code=503, detail="Worker is offline")
    if not worker["url"]:
        raise HTTPException(status_code=503, detail="Worker URL not known")

    url = worker["url"].rstrip("/")
    headers = {}
    if FLEET_API_KEY:
        headers["Authorization"] = f"Bearer {FLEET_API_KEY}"

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
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            return resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Worker communication failed: {exc}")


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
async def api_fleet_api_key(request: Request) -> dict[str, str]:
    """Return the configured fleet API key (owner only)."""
    _require_owner(request)
    return {"api_key": FLEET_API_KEY or ""}
