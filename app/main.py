"""CashPilot — FastAPI application.

Self-hosted passive income dashboard: service catalog, Docker container
management, and earnings tracking.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app import auth, catalog, compose_generator, database, orchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


# ---------------------------------------------------------------------------
# Periodic collection job
# ---------------------------------------------------------------------------


async def _run_collection() -> None:
    """Collect earnings from all deployed services that have collectors."""
    try:
        deployments = await database.get_deployments()
        config = await database.get_config() or {}
        if not isinstance(config, dict):
            config = {}
        collectors = __import__("app.collectors", fromlist=["make_collectors"]).make_collectors(deployments, config)
        for collector in collectors:
            result = await collector.collect()
            if result.error:
                logger.warning("Collection error for %s: %s", result.platform, result.error)
            else:
                await database.upsert_earnings(
                    platform=result.platform,
                    balance=result.balance,
                    currency=result.currency,
                )
                logger.info("Collected %s: %.4f %s", result.platform, result.balance, result.currency)
    except Exception as exc:
        logger.error("Collection run failed: %s", exc)


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await database.init_db()
    catalog.load_services()
    catalog.register_sighup()
    scheduler.add_job(_run_collection, "interval", hours=6, id="collect")
    scheduler.start()
    docker_mode = "direct" if orchestrator.docker_available() else "monitor-only"
    logger.info("CashPilot started (Docker: %s)", docker_mode)
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
    return templates.TemplateResponse(request, "settings.html", {"user": user})


# ---------------------------------------------------------------------------
# API: Services
# ---------------------------------------------------------------------------


@app.get("/api/mode")
async def api_mode(request: Request) -> dict[str, Any]:
    """Return CashPilot operating mode and Docker availability."""
    _require_auth_api(request)
    has_docker = orchestrator.docker_available()
    return {
        "docker": has_docker,
        "mode": "direct" if has_docker else "monitor-only",
    }


@app.get("/api/services")
async def api_list_services(request: Request) -> list[dict[str, Any]]:
    _require_auth_api(request)
    return catalog.get_services()


@app.get("/api/services/{slug}")
async def api_get_service(request: Request, slug: str) -> dict[str, Any]:
    _require_auth_api(request)
    svc = catalog.get_service(slug)
    if not svc:
        raise HTTPException(status_code=404, detail=f"Service '{slug}' not found")
    return svc


# ---------------------------------------------------------------------------
# API: Container management
# ---------------------------------------------------------------------------


@app.get("/api/status")
async def api_status(request: Request) -> list[dict[str, Any]]:
    _require_auth_api(request)
    try:
        return orchestrator.get_status()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


class DeployRequest(BaseModel):
    env: dict[str, str] = {}
    hostname: str | None = None


@app.post("/api/deploy/{slug}")
async def api_deploy(request: Request, slug: str, body: DeployRequest) -> dict[str, str]:
    _require_writer(request)
    svc = catalog.get_service(slug)
    if not svc:
        raise HTTPException(status_code=404, detail=f"Service '{slug}' not found")
    try:
        container_id = orchestrator.deploy_service(
            slug=slug,
            env_vars=body.env,
            hostname=body.hostname,
        )
        await database.save_deployment(slug=slug, container_id=container_id)
        return {"status": "deployed", "container_id": container_id}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/stop/{slug}")
async def api_stop(request: Request, slug: str) -> dict[str, str]:
    _require_writer(request)
    try:
        orchestrator.stop_service(slug)
        return {"status": "stopped"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/restart/{slug}")
async def api_restart(request: Request, slug: str) -> dict[str, str]:
    _require_writer(request)
    try:
        orchestrator.restart_service(slug)
        return {"status": "restarted"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.delete("/api/remove/{slug}")
async def api_remove(request: Request, slug: str) -> dict[str, str]:
    _require_writer(request)
    try:
        orchestrator.remove_service(slug)
        await database.remove_deployment(slug)
        return {"status": "removed"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


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


@app.get("/api/earnings/history")
async def api_earnings_history(request: Request, period: str = "week") -> list[dict[str, Any]]:
    _require_auth_api(request)
    if period not in ("week", "month", "year", "all"):
        raise HTTPException(status_code=400, detail="period must be week, month, year, or all")
    return await database.get_earnings_history(period)


@app.post("/api/collect")
async def api_collect(request: Request) -> dict[str, str]:
    _require_writer(request)
    asyncio.create_task(_run_collection())
    return {"status": "collection_started"}


# ---------------------------------------------------------------------------
# API: Config
# ---------------------------------------------------------------------------


@app.get("/api/config")
async def api_get_config(request: Request) -> dict[str, str]:
    _require_auth_api(request)
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
    _require_owner(request)
    if body.role not in ("viewer", "writer", "owner"):
        raise HTTPException(status_code=400, detail="Role must be viewer, writer, or owner")
    user = await database.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
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
