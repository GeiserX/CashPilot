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
import hmac
import logging
import os
import platform
import re
import socket
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from html import escape as _esc
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app import fleet_key, orchestrator

try:
    from app.catalog import get_services as _catalog_get_services
except ImportError:
    # Worker image may not include the catalog module in some builds.
    _catalog_get_services = None  # type: ignore[assignment]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

UI_URL = os.getenv("CASHPILOT_UI_URL", "")
API_KEY: str = fleet_key.resolve_fleet_key()
if not API_KEY:
    logger.warning("Could not resolve fleet API key — set CASHPILOT_API_KEY or mount a shared /fleet volume")
WORKER_NAME = os.getenv("CASHPILOT_WORKER_NAME", socket.gethostname())
WORKER_PORT = int(os.getenv("CASHPILOT_PORT", "8081"))
WORKER_URL = os.getenv("CASHPILOT_WORKER_URL", "")
HEARTBEAT_INTERVAL = 60  # seconds

_heartbeat_task: asyncio.Task | None = None
_ui_connected = False
_last_heartbeat: str = "never"
_last_error: str = ""

# Per-worker fleet key. On first contact the UI enrolls this worker and hands back
# a key unique to us, which we persist here (in our own private /data, never the
# shared /fleet volume) and use for all subsequent auth in both directions. Until
# enrollment we authenticate with the shared bootstrap key.
_WORKER_KEY_FILE = Path(os.getenv("CASHPILOT_DATA_DIR", "/data")) / ".worker_key"


def _load_worker_key() -> str | None:
    try:
        if _WORKER_KEY_FILE.is_file():
            return _WORKER_KEY_FILE.read_text().strip() or None
    except OSError as exc:
        logger.warning("Could not read per-worker key: %s", exc)
    return None


def _save_worker_key(key: str) -> bool:
    """Persist the newly issued per-worker key to disk, then adopt it in memory.

    Returns True once the key is durably on disk. On persistence failure the
    key is NOT adopted -- we keep authenticating with whatever key was active
    before, so a write failure here can never leave us relying on a key that
    only exists in memory and vanishes on the next restart (lockout).
    """
    try:
        _WORKER_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _WORKER_KEY_FILE.write_text(key)
        _WORKER_KEY_FILE.chmod(0o600)
    except OSError as exc:
        logger.error("Could not persist per-worker key — NOT adopting it: %s", exc)
        return False
    global _worker_key
    _worker_key = key
    return True


_worker_key: str | None = _load_worker_key()


def _active_key() -> str:
    """The key we authenticate with: our own once enrolled, else the shared key."""
    return _worker_key or API_KEY


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _verify_api_key(request: Request) -> None:
    """Verify an inbound UI->worker call.

    Once enrolled we require OUR OWN per-worker key; the shared bootstrap key is
    rejected (the cutover). Before enrollment we accept the shared key so the UI
    can reach us to enroll in the first place.
    """
    expected = _active_key()
    if not expected:
        raise HTTPException(status_code=503, detail="Fleet key not configured")
    auth = request.headers.get("Authorization", "")
    if not hmac.compare_digest(auth.encode(), f"Bearer {expected}".encode()):
        raise HTTPException(status_code=401, detail="Invalid API key")


# ---------------------------------------------------------------------------
# Heartbeat loop
# ---------------------------------------------------------------------------


async def _send_heartbeat() -> None:
    """Send a single heartbeat to the UI."""
    global _ui_connected, _last_heartbeat, _last_error

    containers = []
    try:
        containers = await asyncio.to_thread(orchestrator.get_status)
    except Exception as exc:
        logger.warning("Failed to get container status for heartbeat: %s", exc)

    payload = {
        "name": WORKER_NAME,
        "url": WORKER_URL or f"http://{_get_local_ip()}:{WORKER_PORT}",
        "containers": containers,
        "system_info": {
            "os": f"{platform.system()} {platform.release()}",
            "arch": platform.machine(),
            "hostname": socket.gethostname(),
            "docker_available": await asyncio.to_thread(orchestrator.docker_available),
        },
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{UI_URL.rstrip('/')}/api/workers/heartbeat",
                json=payload,
                headers={"Authorization": f"Bearer {_active_key()}"},
            )
            resp.raise_for_status()
            # Enrollment: the UI returns our own per-worker key exactly once.
            issued = None
            with contextlib.suppress(Exception):
                issued = resp.json().get("worker_key")
            if issued and issued != _worker_key:
                if _save_worker_key(issued):
                    logger.info("Enrolled: received and persisted this worker's own fleet key")
                else:
                    logger.error("Received per-worker key but could not persist it — staying on shared key")
            _ui_connected = True
            _last_heartbeat = datetime.now(UTC).strftime("%H:%M:%S UTC")
            _last_error = ""
            logger.debug("Heartbeat sent to %s", UI_URL)
    except httpx.HTTPStatusError as exc:
        _ui_connected = False
        status = exc.response.status_code
        _last_error = f"authentication rejected ({status})" if status in (401, 403) else "connection failed"
        logger.warning("Heartbeat failed: %s", exc)
    except Exception as exc:
        _ui_connected = False
        _last_error = "connection failed"
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
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return socket.gethostname()


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _heartbeat_task

    logger.info("CashPilot Worker '%s' starting", WORKER_NAME)
    docker_mode = "direct" if await asyncio.to_thread(orchestrator.docker_available) else "monitor-only"
    logger.info("Docker: %s", docker_mode)

    if UI_URL:
        _heartbeat_task = asyncio.create_task(_heartbeat_loop())
        logger.info("Heartbeat enabled -> %s (every %ds)", UI_URL, HEARTBEAT_INTERVAL)
        if not API_KEY:
            logger.warning("CASHPILOT_API_KEY not set — heartbeats sent without auth")
    else:
        logger.warning("No CASHPILOT_UI_URL — running without UI connection")

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
async def worker_status_page(request: Request):
    """Self-contained HTML status page for the worker."""
    _verify_api_key(request)
    containers = []
    try:
        containers = await asyncio.to_thread(orchestrator.get_status_cached)
    except Exception as exc:
        logger.warning("Failed to get container status for status page: %s", exc)

    container_rows = ""
    for c in containers:
        status_color = "#22c55e" if c.get("status") == "running" else "#ef4444"
        container_rows += f"""
        <tr>
            <td>{_esc(str(c.get("slug", "unknown")))}</td>
            <td><span style="color:{status_color}">{_esc(str(c.get("status", "unknown")))}</span></td>
            <td>{_esc(str(c.get("image", "")))}</td>
            <td>{c.get("cpu_percent", 0)}%</td>
            <td>{c.get("memory_mb", 0)} MB</td>
        </tr>"""

    if not container_rows:
        container_rows = '<tr><td colspan="5" style="text-align:center;color:#6b7280">No managed containers</td></tr>'

    ui_status = (
        f'<span style="color:#22c55e">Connected</span> to <code>{_esc(UI_URL)}</code>'
        if _ui_connected
        else '<span style="color:#ef4444">Disconnected</span>' + (f" — {_esc(_last_error)}" if _last_error else "")
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>CashPilot Worker — {_esc(WORKER_NAME)}</title>
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
            <div><label>Name</label><span>{_esc(WORKER_NAME)}</span></div>
            <div><label>Host</label><span>{_esc(socket.gethostname())}</span></div>
            <div><label>Platform</label><span>{_esc(platform.system())} {_esc(platform.machine())}</span></div>
            <div><label>Docker</label><span>{"Available" if await asyncio.to_thread(orchestrator.docker_available) else "Not available"}</span></div>
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


class ResourceSpec(BaseModel):
    """Optional Docker resource limits applied when the container is created.

    mem_limit / mem_reservation follow Docker's size syntax ("768m", "2g");
    oom_score_adj biases the kernel OOM killer (-1000 = sacrificed last).
    """

    mem_limit: str | None = None
    mem_reservation: str | None = None
    oom_score_adj: int | None = None


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
    resources: ResourceSpec | None = None


_BLOCKED_VOLUME_ROOTS = {
    "/",
    "/etc",
    "/root",
    "/proc",
    "/sys",
    "/boot",
    "/dev",
    "/var",
    "/usr",
    "/home",
    "/lib",
    "/lib64",
    "/bin",
    "/sbin",
    "/var/run",
    "/run",  # also covers /run/docker.sock (modern /var/run -> /run symlink)
    "/var/lib/docker",
    "/mnt",  # e.g. Unraid array root (/mnt/user/appdata/<app>) — co-located apps' secrets
    "/media",
    "/opt",
    "/srv",
    "/data",  # per-container app data roots, incl. this worker's own /data
    "/tmp",
}
# Docker memory size syntax: a positive integer with an optional b/k/m/g unit.
_MEM_LIMIT_RE = re.compile(r"^\d+[bkmgBKMG]?$")


def _catalog_allowed_capabilities() -> set[str]:
    """Union of cap_add values any bundled catalog service actually declares.

    Derived from services/*.yml (the single source of truth) instead of a
    hardcoded list, so it stays correct as the catalog changes. A capability
    no catalog service asks for is refused, whatever it is.
    """
    if not _catalog_get_services:
        return set()
    caps: set[str] = set()
    for svc in _catalog_get_services():
        for cap in (svc.get("docker") or {}).get("cap_add") or []:
            caps.add(str(cap).upper())
    return caps


def _catalog_host_network_slugs() -> set[str]:
    """Slugs whose catalog definition legitimately declares network_mode: host."""
    if not _catalog_get_services:
        return set()
    return {svc["slug"] for svc in _catalog_get_services() if (svc.get("docker") or {}).get("network_mode") == "host"}


# Named volumes (bridge/none/unset) are always allowed. `host` is allowed only for
# catalog services that declare it (checked separately below, by slug). `container:<id>`
# (namespace join) and any other value are rejected outright.
_ALLOWED_NETWORK_MODES = {None, "", "bridge", "none", "host"}


def _validate_deploy_spec(spec: DeploySpec, slug: str | None = None) -> None:
    if spec.privileged:
        raise HTTPException(status_code=403, detail="Privileged containers are not allowed")
    if spec.cap_add:
        requested = {c.upper() for c in spec.cap_add}
        blocked = requested - _catalog_allowed_capabilities()
        if blocked:
            raise HTTPException(status_code=403, detail=f"Blocked capabilities: {', '.join(sorted(blocked))}")
    if spec.network_mode not in _ALLOWED_NETWORK_MODES:
        raise HTTPException(status_code=403, detail=f"Network mode '{spec.network_mode}' is not allowed")
    if spec.network_mode == "host" and slug not in _catalog_host_network_slugs():
        raise HTTPException(status_code=403, detail=f"Network mode 'host' is not allowed for '{slug}'")
    for source in spec.volumes:
        if not source.startswith("/"):
            continue  # named volume (e.g. "mysterium-data") — always allowed
        real = os.path.realpath(source)
        for blocked in _BLOCKED_VOLUME_ROOTS:
            if real == blocked or real.startswith(blocked + "/"):
                raise HTTPException(status_code=403, detail=f"Volume mount '{source}' is blocked")
    _validate_resources(spec.resources)


def _validate_resources(resources: ResourceSpec | None) -> None:
    if resources is None:
        return
    for field, value in (("mem_limit", resources.mem_limit), ("mem_reservation", resources.mem_reservation)):
        if value is not None and not _MEM_LIMIT_RE.match(value):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid {field} '{value}': expected a size like '768m' or '2g'",
            )
    if resources.oom_score_adj is not None and not (-1000 <= resources.oom_score_adj <= 1000):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid oom_score_adj '{resources.oom_score_adj}': must be between -1000 and 1000",
        )


@app.get("/api/status")
async def api_worker_status(request: Request) -> dict[str, Any]:
    """Return worker status summary."""
    _verify_api_key(request)
    containers = []
    try:
        containers = await asyncio.to_thread(orchestrator.get_status_cached)
    except Exception as exc:
        logger.warning("Failed to get container status: %s", exc)
    return {
        "name": WORKER_NAME,
        "docker_available": await asyncio.to_thread(orchestrator.docker_available),
        "ui_connected": _ui_connected,
        "container_count": len(containers),
        "running_count": sum(1 for c in containers if c.get("status") == "running"),
    }


@app.get("/api/containers")
async def api_list_containers(request: Request) -> list[dict[str, Any]]:
    """List all CashPilot-managed containers."""
    _verify_api_key(request)
    try:
        return await asyncio.to_thread(orchestrator.get_status_cached)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/containers/{slug}/deploy")
async def api_deploy_container(request: Request, slug: str, spec: DeploySpec) -> dict[str, str]:
    """Deploy a container from spec sent by UI."""
    _verify_api_key(request)
    _validate_deploy_spec(spec, slug=slug)
    try:
        container_id = await asyncio.to_thread(
            orchestrator.deploy_raw,
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
            resources=spec.resources,
        )
        return {"status": "deployed", "container_id": container_id}
    except Exception:
        logger.exception("Deploy failed for %s", slug)
        raise HTTPException(status_code=500, detail="Container deployment failed")


@app.post("/api/containers/{slug}/restart")
async def api_restart_container(request: Request, slug: str) -> dict[str, str]:
    _verify_api_key(request)
    try:
        await asyncio.to_thread(orchestrator.restart_service, slug)
        return {"status": "restarted"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/containers/{slug}/stop")
async def api_stop_container(request: Request, slug: str) -> dict[str, str]:
    _verify_api_key(request)
    try:
        await asyncio.to_thread(orchestrator.stop_service, slug)
        return {"status": "stopped"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/containers/{slug}/start")
async def api_start_container(request: Request, slug: str) -> dict[str, str]:
    _verify_api_key(request)
    try:
        await asyncio.to_thread(orchestrator.start_service, slug)
        return {"status": "started"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.delete("/api/containers/{slug}")
async def api_remove_container(request: Request, slug: str, delete_volumes: bool = False) -> dict[str, Any]:
    _verify_api_key(request)
    try:
        result = await asyncio.to_thread(orchestrator.remove_service, slug, delete_volumes=delete_volumes)
        return {"status": "removed", **result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/containers/{slug}/logs")
async def api_container_logs(request: Request, slug: str, lines: int = 50) -> dict[str, str]:
    _verify_api_key(request)
    try:
        logs = await asyncio.to_thread(orchestrator.get_service_logs, slug, lines=min(lines, 1000))
        return {"logs": logs}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/health")
async def api_health() -> dict[str, str]:
    """Health check endpoint (no auth required)."""
    return {"status": "ok", "worker": WORKER_NAME}
