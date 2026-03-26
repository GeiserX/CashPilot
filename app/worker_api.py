"""CashPilot Worker — Lightweight container management agent.

Runs on each server in the fleet. Manages local Docker containers,
sends heartbeats to the CashPilot UI, and accepts commands from it.

Configure via environment variables:
    CASHPILOT_UI_URL        URL of the CashPilot UI (e.g. http://192.168.10.100:8080)
    CASHPILOT_API_KEY       Shared API key for worker<->UI auth
    CASHPILOT_WORKER_NAME   Human-readable name (default: hostname)
    CASHPILOT_PORT          Mini-UI port (default: 8081)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import platform
import socket
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app import orchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

UI_URL = os.getenv("CASHPILOT_UI_URL", "")
API_KEY = os.getenv("CASHPILOT_API_KEY", "")
WORKER_NAME = os.getenv("CASHPILOT_WORKER_NAME", socket.gethostname())
WORKER_PORT = int(os.getenv("CASHPILOT_PORT", "8081"))
HEARTBEAT_INTERVAL = 60  # seconds

_heartbeat_task: asyncio.Task | None = None
_ui_connected = False
_last_heartbeat: str = "never"
_last_error: str = ""


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _verify_api_key(request: Request) -> None:
    """Verify the shared API key from Authorization header."""
    if not API_KEY:
        return  # No key = no auth (local-only / standalone)
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="Invalid API key")


# ---------------------------------------------------------------------------
# Heartbeat loop
# ---------------------------------------------------------------------------


async def _send_heartbeat() -> None:
    """Send a single heartbeat to the UI."""
    global _ui_connected, _last_heartbeat, _last_error

    containers = []
    with contextlib.suppress(Exception):
        containers = orchestrator.get_status()

    payload = {
        "name": WORKER_NAME,
        "url": f"http://{_get_local_ip()}:{WORKER_PORT}",
        "containers": containers,
        "system_info": {
            "os": f"{platform.system()} {platform.release()}",
            "arch": platform.machine(),
            "hostname": socket.gethostname(),
            "docker_available": orchestrator.docker_available(),
        },
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{UI_URL.rstrip('/')}/api/workers/heartbeat",
                json=payload,
                headers={"Authorization": f"Bearer {API_KEY}"},
            )
            resp.raise_for_status()
            _ui_connected = True
            _last_heartbeat = "just now"
            _last_error = ""
            logger.debug("Heartbeat sent to %s", UI_URL)
    except Exception as exc:
        _ui_connected = False
        _last_error = str(exc)
        logger.warning("Heartbeat failed: %s", exc)


async def _heartbeat_loop() -> None:
    """Send heartbeats to the UI at regular intervals."""
    # Send first heartbeat immediately
    await _send_heartbeat()
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        await _send_heartbeat()


def _get_local_ip() -> str:
    """Best-effort local IP detection for worker URL."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return socket.gethostname()


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _heartbeat_task

    logger.info("CashPilot Worker '%s' starting", WORKER_NAME)
    docker_mode = "direct" if orchestrator.docker_available() else "monitor-only"
    logger.info("Docker: %s", docker_mode)

    if UI_URL and API_KEY:
        _heartbeat_task = asyncio.create_task(_heartbeat_loop())
        logger.info("Heartbeat enabled -> %s (every %ds)", UI_URL, HEARTBEAT_INTERVAL)
    else:
        logger.warning("No CASHPILOT_UI_URL or CASHPILOT_API_KEY — running without UI connection")

    yield

    if _heartbeat_task and not _heartbeat_task.done():
        _heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _heartbeat_task
    logger.info("CashPilot Worker stopped")


app = FastAPI(title="CashPilot Worker", version="0.1.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Mini-UI (status page)
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def worker_status_page():
    """Self-contained HTML status page for the worker."""
    containers = []
    with contextlib.suppress(Exception):
        containers = orchestrator.get_status()

    container_rows = ""
    for c in containers:
        status_color = "#22c55e" if c.get("status") == "running" else "#ef4444"
        container_rows += f"""
        <tr>
            <td>{c.get("slug", "unknown")}</td>
            <td><span style="color:{status_color}">{c.get("status", "unknown")}</span></td>
            <td>{c.get("image", "")}</td>
            <td>{c.get("cpu_percent", 0)}%</td>
            <td>{c.get("memory_mb", 0)} MB</td>
        </tr>"""

    if not container_rows:
        container_rows = '<tr><td colspan="5" style="text-align:center;color:#6b7280">No managed containers</td></tr>'

    ui_status = (
        f'<span style="color:#22c55e">Connected</span> to <code>{UI_URL}</code>'
        if _ui_connected
        else '<span style="color:#ef4444">Disconnected</span>' + (f" — {_last_error}" if _last_error else "")
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>CashPilot Worker — {WORKER_NAME}</title>
    <meta http-equiv="refresh" content="30">
    <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ font-family:-apple-system,BlinkMacSystemFont,sans-serif; background:#0f1117; color:#e5e7eb; padding:2rem; }}
        h1 {{ font-size:1.5rem; margin-bottom:1.5rem; color:#3b82f6; }}
        .card {{ background:#1a1d26; border-radius:8px; padding:1.25rem; margin-bottom:1rem; }}
        .card h2 {{ font-size:1rem; color:#9ca3af; margin-bottom:.75rem; }}
        .info {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:.5rem; }}
        .info div {{ padding:.5rem; background:#0f1117; border-radius:4px; }}
        .info label {{ font-size:.75rem; color:#6b7280; display:block; }}
        .info span {{ font-size:.875rem; }}
        table {{ width:100%; border-collapse:collapse; }}
        th {{ text-align:left; padding:.5rem; color:#9ca3af; font-size:.75rem; text-transform:uppercase; border-bottom:1px solid #2d3748; }}
        td {{ padding:.5rem; font-size:.875rem; border-bottom:1px solid #1e2433; }}
        code {{ background:#2d3748; padding:.125rem .375rem; border-radius:3px; font-size:.8rem; }}
    </style>
</head>
<body>
    <h1>CashPilot Worker</h1>
    <div class="card">
        <h2>Worker Info</h2>
        <div class="info">
            <div><label>Name</label><span>{WORKER_NAME}</span></div>
            <div><label>Host</label><span>{socket.gethostname()}</span></div>
            <div><label>Platform</label><span>{platform.system()} {platform.machine()}</span></div>
            <div><label>Docker</label><span>{"Available" if orchestrator.docker_available() else "Not available"}</span></div>
            <div><label>UI Connection</label><span>{ui_status}</span></div>
            <div><label>Last Heartbeat</label><span>{_last_heartbeat}</span></div>
        </div>
    </div>
    <div class="card">
        <h2>Managed Containers ({len(containers)})</h2>
        <table>
            <thead><tr><th>Service</th><th>Status</th><th>Image</th><th>CPU</th><th>Memory</th></tr></thead>
            <tbody>{container_rows}</tbody>
        </table>
    </div>
    <p style="margin-top:2rem;color:#4b5563;font-size:.75rem">Auto-refreshes every 30s</p>
</body>
</html>"""


# ---------------------------------------------------------------------------
# API: Container management (called by UI)
# ---------------------------------------------------------------------------


class DeploySpec(BaseModel):
    image: str
    env: dict[str, str] = {}
    ports: dict[str, int] = {}
    volumes: dict[str, dict[str, str]] = {}
    network_mode: str | None = None
    cap_add: list[str] | None = None
    privileged: bool = False
    command: str | None = None
    hostname: str | None = None
    labels: dict[str, str] = {}


@app.get("/api/status")
async def api_worker_status(request: Request) -> dict[str, Any]:
    """Return worker status summary."""
    _verify_api_key(request)
    containers = []
    with contextlib.suppress(Exception):
        containers = orchestrator.get_status()
    return {
        "name": WORKER_NAME,
        "docker_available": orchestrator.docker_available(),
        "ui_connected": _ui_connected,
        "container_count": len(containers),
        "running_count": sum(1 for c in containers if c.get("status") == "running"),
    }


@app.get("/api/containers")
async def api_list_containers(request: Request) -> list[dict[str, Any]]:
    """List all CashPilot-managed containers."""
    _verify_api_key(request)
    try:
        return orchestrator.get_status()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/containers/{slug}/deploy")
async def api_deploy_container(request: Request, slug: str, spec: DeploySpec) -> dict[str, str]:
    """Deploy a container from spec sent by UI."""
    _verify_api_key(request)
    try:
        container_id = orchestrator.deploy_raw(
            slug=slug,
            image=spec.image,
            env=spec.env,
            ports=spec.ports,
            volumes=spec.volumes,
            network_mode=spec.network_mode,
            cap_add=spec.cap_add,
            privileged=spec.privileged,
            command=spec.command,
            hostname=spec.hostname,
            labels=spec.labels,
        )
        return {"status": "deployed", "container_id": container_id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/containers/{slug}/restart")
async def api_restart_container(request: Request, slug: str) -> dict[str, str]:
    _verify_api_key(request)
    try:
        orchestrator.restart_service(slug)
        return {"status": "restarted"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/containers/{slug}/stop")
async def api_stop_container(request: Request, slug: str) -> dict[str, str]:
    _verify_api_key(request)
    try:
        orchestrator.stop_service(slug)
        return {"status": "stopped"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/containers/{slug}/start")
async def api_start_container(request: Request, slug: str) -> dict[str, str]:
    _verify_api_key(request)
    try:
        orchestrator.start_service(slug)
        return {"status": "started"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.delete("/api/containers/{slug}")
async def api_remove_container(request: Request, slug: str) -> dict[str, str]:
    _verify_api_key(request)
    try:
        orchestrator.remove_service(slug)
        return {"status": "removed"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/containers/{slug}/logs")
async def api_container_logs(request: Request, slug: str, lines: int = 50) -> dict[str, str]:
    _verify_api_key(request)
    try:
        logs = orchestrator.get_service_logs(slug, lines=min(lines, 1000))
        return {"logs": logs}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/health")
async def api_health() -> dict[str, str]:
    """Health check endpoint (no auth required)."""
    return {"status": "ok", "worker": WORKER_NAME}
