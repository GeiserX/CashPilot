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
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app import catalog, database, orchestrator
from app.collectors import make_collectors

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
        collectors = make_collectors(deployments, config)
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
    logger.info("CashPilot started")
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
# Page routes (HTML)
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def page_dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html")


@app.get("/setup", response_class=HTMLResponse)
async def page_setup(request: Request):
    return templates.TemplateResponse(request, "setup.html")


@app.get("/catalog", response_class=HTMLResponse)
async def page_catalog(request: Request):
    return templates.TemplateResponse(request, "catalog.html")


@app.get("/settings", response_class=HTMLResponse)
async def page_settings(request: Request):
    return templates.TemplateResponse(request, "settings.html")


# ---------------------------------------------------------------------------
# API: Services
# ---------------------------------------------------------------------------


@app.get("/api/services")
async def api_list_services() -> list[dict[str, Any]]:
    """List all services from YAML definitions."""
    return catalog.get_services()


@app.get("/api/services/{slug}")
async def api_get_service(slug: str) -> dict[str, Any]:
    """Get a single service by slug."""
    svc = catalog.get_service(slug)
    if not svc:
        raise HTTPException(status_code=404, detail=f"Service '{slug}' not found")
    return svc


# ---------------------------------------------------------------------------
# API: Container management
# ---------------------------------------------------------------------------


@app.get("/api/status")
async def api_status() -> list[dict[str, Any]]:
    """Container status for all deployed cashpilot services."""
    try:
        return orchestrator.get_status()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


class DeployRequest(BaseModel):
    env: dict[str, str] = {}
    hostname: str | None = None


@app.post("/api/deploy/{slug}")
async def api_deploy(slug: str, body: DeployRequest) -> dict[str, str]:
    """Deploy a service container."""
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
async def api_stop(slug: str) -> dict[str, str]:
    """Stop a service container."""
    try:
        orchestrator.stop_service(slug)
        return {"status": "stopped"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/restart/{slug}")
async def api_restart(slug: str) -> dict[str, str]:
    """Restart a service container."""
    try:
        orchestrator.restart_service(slug)
        return {"status": "restarted"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.delete("/api/remove/{slug}")
async def api_remove(slug: str) -> dict[str, str]:
    """Stop and remove a service container."""
    try:
        orchestrator.remove_service(slug)
        await database.remove_deployment(slug)
        return {"status": "removed"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ---------------------------------------------------------------------------
# API: Earnings
# ---------------------------------------------------------------------------


@app.get("/api/earnings")
async def api_earnings() -> list[dict[str, Any]]:
    """Current earnings summary (latest balance per platform)."""
    return await database.get_earnings_summary()


@app.get("/api/earnings/history")
async def api_earnings_history(period: str = "week") -> list[dict[str, Any]]:
    """Historical earnings data."""
    if period not in ("week", "month", "year", "all"):
        raise HTTPException(status_code=400, detail="period must be week, month, year, or all")
    return await database.get_earnings_history(period)


@app.post("/api/collect")
async def api_collect() -> dict[str, str]:
    """Trigger a manual earnings collection run."""
    asyncio.create_task(_run_collection())
    return {"status": "collection_started"}


# ---------------------------------------------------------------------------
# API: Config
# ---------------------------------------------------------------------------


@app.get("/api/config")
async def api_get_config() -> dict[str, str]:
    """Get all user config (referral codes, credentials, etc.)."""
    result = await database.get_config()
    if isinstance(result, dict):
        return result
    return {}


class ConfigUpdate(BaseModel):
    data: dict[str, str]


@app.post("/api/config")
async def api_set_config(body: ConfigUpdate) -> dict[str, str]:
    """Save user config entries."""
    await database.set_config_bulk(body.data)
    return {"status": "saved"}
