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
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from html import escape as _esc
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app import egress, fleet_key, orchestrator

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

# Consecutive 401s while holding our own per-worker key. One is unremarkable (the UI
# may be restarting); a run of them means our identity no longer matches our key.
_consecutive_auth_failures = 0
_AUTH_FAILURE_ALARM_AFTER = 3

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


# Stable per-worker identity. The UI keys a worker's DB row (and its per-worker key) on
# this client_id, NOT on the mutable display name: two hosts sharing a default hostname
# (ubuntu/raspberrypi/docker-desktop) must not collapse onto one identity, and renaming
# CASHPILOT_WORKER_NAME must not mint a new identity that locks the worker out.
_WORKER_ID_FILE = Path(os.getenv("CASHPILOT_DATA_DIR", "/data")) / ".worker_id"


_DOCKER_CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def _name_is_ephemeral(name: str) -> bool:
    """True when WORKER_NAME is really a Docker-assigned container ID.

    Docker defaults a container's hostname to the first 12 hex characters of its
    ID, and that ID changes every time the container is recreated -- which is
    exactly what an image bump does. Treating such a name as a durable identity
    mints a new client_id on every upgrade; the UI then sees a still-valid
    per-worker key arriving from an unknown client and correctly refuses it, so
    every heartbeat 401s while the service containers keep earning. The outage
    is silent. Observed in production upgrading 1.0.0 -> 1.4.1.

    A real host name (bare metal, a VM, or an explicit `hostname:`/
    CASHPILOT_WORKER_NAME) stays stable across restarts and remains a perfectly
    good identity, so only the container-ID shape is rejected, and only when we
    are actually inside a container.
    """
    return bool(_DOCKER_CONTAINER_ID_RE.match(name)) and Path("/.dockerenv").exists()


def _load_or_create_client_id() -> str:
    """Return this worker's stable client_id, generating and persisting one on first run.

    Migration: a worker already enrolled under the pre-client_id scheme has a persisted
    per-worker key but no id file. It keeps the identity the UI already knows it by --
    its WORKER_NAME -- so upgrading never orphans its row. The one exception is a name
    that is really a Docker container ID: that is regenerated on every recreate, so
    reusing it would mint a new identity and lock the worker out (see _name_is_ephemeral).
    A brand-new worker gets a random id.
    """
    try:
        existing = _WORKER_ID_FILE.read_text().strip()
        if existing:
            return existing
    except OSError:
        pass
    if _worker_key and not _name_is_ephemeral(WORKER_NAME):
        cid = WORKER_NAME
    else:
        cid = uuid.uuid4().hex
        if _worker_key:
            # Enrolled already, but our only clue to which row is ours was an
            # ephemeral container ID. This is NOT recoverable by re-enrolling:
            # we still send our own per-worker key (see _active_key), and the UI
            # refuses it under an id it never enrolled, so every heartbeat 401s
            # until the id is restored by hand. Say exactly that -- the symptom
            # is otherwise very hard to trace back to this decision.
            logger.error(
                "This worker holds a per-worker key but no persisted client_id, and its "
                "name (%s) is a container ID that changes on every recreate. Heartbeats "
                "will be REJECTED (401) under the generated id %s, because we authenticate "
                "with our existing key and the UI does not know that id. To recover: stop "
                "this container, write the client_id the UI lists for this worker into %s, "
                "start it again, and set CASHPILOT_WORKER_NAME so this cannot recur.",
                WORKER_NAME,
                cid,
                _WORKER_ID_FILE,
            )
    try:
        _WORKER_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
        _WORKER_ID_FILE.write_text(cid)
        _WORKER_ID_FILE.chmod(0o600)
    except OSError as exc:
        logger.warning("Could not persist worker client_id — using in-memory id: %s", exc)
    return cid


CLIENT_ID: str = _load_or_create_client_id()


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


# ---------------------------------------------------------------------------
# Egress identity (CashPilot-5qc)
# ---------------------------------------------------------------------------

# Every provider in the catalog caps per IP address, so the UI cannot warn about
# two workers behind one connection unless each worker knows its own exit.
#
# This is the one outbound call CashPilot makes purely to learn about the user,
# so it is opt-outable and endpoint-overridable. The privacy cost is genuinely
# small — a worker's whole purpose is to route traffic for these providers, all
# of whom already see this address — but "small" is not "none", and defaults
# that quietly phone somewhere are how trust is lost in this category.
_EGRESS_ENDPOINTS = ("https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com")

# Local, network-free hosting hint. Read from DMI rather than an ASN lookup so
# nothing is disclosed to a third party and it still works offline.
_DMI_PATHS = ("/sys/class/dmi/id/sys_vendor", "/sys/class/dmi/id/product_name", "/sys/class/dmi/id/chassis_vendor")

_egress_cache: tuple[str | None, float] = (None, 0.0)
_EGRESS_TTL_SECONDS = 3600.0
# A failed lookup is cached too, and briefly. Without it a blackholed network
# (DROP, not REJECT) costs the full timeout on EVERY heartbeat, forever.
_EGRESS_FAILURE_TTL_SECONDS = 300.0
# Total wall-clock budget for the whole attempt. httpx's timeout is PER
# OPERATION — its read timeout is the maximum gap between chunks, not a deadline
# — so an endpoint dribbling one byte every few seconds would hold the request
# open indefinitely. That matters here because the heartbeat loop is serial: a
# stalled lookup stops heartbeats entirely and the UI marks this worker offline
# after 180s, so deploys and restarts for this host start failing. A diagnostic
# nicety must never be able to take the control plane down.
_EGRESS_TOTAL_TIMEOUT = 10.0
# Enough for any textual IP form; the body is never read past this.
_EGRESS_MAX_BYTES = 128


def _detect_network_type() -> str:
    """residential / hosting / unknown, from local hardware identifiers only.

    An explicit ``CASHPILOT_WORKER_NETWORK`` always wins: the user knows their
    own connection better than any heuristic, and a wrong "hosting" verdict
    fires ban warnings at people who are fine.
    """
    declared = egress.normalise_network_type(os.getenv("CASHPILOT_WORKER_NETWORK"))
    if declared != egress.UNKNOWN:
        return declared
    for path in _DMI_PATHS:
        try:
            vendor = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        detected = egress.classify_vendor(vendor)
        if detected != egress.UNKNOWN:
            return detected
    return egress.UNKNOWN


async def _fetch_egress_ip(url: str) -> str | None:
    """One IP-echo request, with the response body capped while streaming."""
    async with httpx.AsyncClient(timeout=5) as client, client.stream("GET", url) as resp:
        if resp.status_code != 200:
            return None
        body = b""
        async for chunk in resp.aiter_bytes():
            body += chunk
            if len(body) >= _EGRESS_MAX_BYTES:
                break
    return egress.public_ip(body[:_EGRESS_MAX_BYTES].decode("utf-8", "replace").strip())


async def _detect_egress_ip() -> str | None:
    """This worker's public IP, cached for an hour, or None.

    Every failure mode returns None rather than a guess: a wrong address would
    group unrelated machines together, which is worse than the fleet view simply
    saying it does not know.
    """
    global _egress_cache

    if os.getenv("CASHPILOT_EGRESS_DETECT", "").strip().lower() in {"0", "off", "false", "no"}:
        return None

    cached, fetched_at = _egress_cache
    # time.monotonic(), not the event loop's clock: the loop's epoch is
    # unspecified, and one starting near zero would make this difference
    # negative — always under the TTL — pinning a stale address forever.
    now = time.monotonic()
    age = now - fetched_at
    if cached and age < _EGRESS_TTL_SECONDS:
        return cached
    if not cached and fetched_at and age < _EGRESS_FAILURE_TTL_SECONDS:
        return None

    override = os.getenv("CASHPILOT_EGRESS_IP", "").strip()
    if override:
        # A user behind a proxy or split tunnel can state the truth directly.
        confirmed = egress.public_ip(override)
        if confirmed:
            _egress_cache = (confirmed, now)
            return confirmed
        # Ignoring this silently would be cruel: "192.168.1.5" is what most
        # people would call their IP, and the only symptom is nothing happening.
        logger.warning(
            "CASHPILOT_EGRESS_IP=%r is not a public address, so it cannot be this worker's "
            "egress IP — ignoring it and looking the address up instead.",
            override,
        )

    custom = os.getenv("CASHPILOT_EGRESS_IP_URL", "").strip()
    # An operator who names their own endpoint did so to avoid disclosing to a
    # third party. Falling back to the public ones on a transient failure would
    # quietly undo exactly that choice, so a custom endpoint is used ALONE.
    endpoints = [custom] if custom else list(_EGRESS_ENDPOINTS)

    for url in endpoints:
        try:
            found = await asyncio.wait_for(_fetch_egress_ip(url), timeout=_EGRESS_TOTAL_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 — never let this break a heartbeat
            logger.debug("Egress IP lookup via %s failed: %s", url, exc)
            continue
        if found:
            _egress_cache = (found, now)
            return found

    _egress_cache = (None, now)
    return None


async def _send_heartbeat() -> None:
    """Send a single heartbeat to the UI."""
    global _ui_connected, _last_heartbeat, _last_error, _consecutive_auth_failures

    containers = []
    try:
        containers = await asyncio.to_thread(orchestrator.get_status)
    except Exception as exc:
        logger.warning("Failed to get container status for heartbeat: %s", exc)

    payload = {
        "name": WORKER_NAME,
        "client_id": CLIENT_ID,
        "url": WORKER_URL or f"http://{_get_local_ip()}:{WORKER_PORT}",
        "containers": containers,
        "system_info": {
            "os": f"{platform.system()} {platform.release()}",
            "arch": platform.machine(),
            "hostname": socket.gethostname(),
            "docker_available": await asyncio.to_thread(orchestrator.docker_available),
            # Providers count devices per public IP, so the UI needs the address
            # the provider sees — not this container's LAN or tailnet address.
            "egress_ip": await _detect_egress_ip(),
            "egress_network_type": _detect_network_type(),
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
            _consecutive_auth_failures = 0
            logger.debug("Heartbeat sent to %s", UI_URL)
    except httpx.HTTPStatusError as exc:
        _ui_connected = False
        status = exc.response.status_code
        _last_error = f"authentication rejected ({status})" if status in (401, 403) else "connection failed"
        logger.warning("Heartbeat failed: %s", exc)
        if status == 401 and _worker_key:
            _consecutive_auth_failures += 1
        else:
            # Any other outcome breaks the run. "Consecutive" has to mean it:
            # 401 -> timeout -> 401 -> 500 -> 401 is a flaky link, not an
            # identity mismatch, and must not raise the alarm.
            _consecutive_auth_failures = 0
            if _consecutive_auth_failures == _AUTH_FAILURE_ALARM_AFTER:
                # A per-worker key rejected repeatedly almost always means our
                # client_id no longer matches the row the UI enrolled — usually
                # because the id was derived from a container hostname that
                # changed on recreate. Service containers keep earning through
                # this, so nothing else surfaces the problem: say it plainly once.
                logger.error(
                    "Rejected %d times with this worker's own key. The UI does not "
                    "recognise client_id %r. If the UI still lists this worker under a "
                    "different id, stop this container, write that id into %s, and start "
                    "it again to reclaim the existing row.",
                    _consecutive_auth_failures,
                    CLIENT_ID,
                    _WORKER_ID_FILE,
                )
    except Exception as exc:
        _ui_connected = False
        _last_error = "connection failed"
        # A network failure is not an auth rejection, so it breaks the run too.
        _consecutive_auth_failures = 0
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
            <div><label>ID</label><span>{_esc(CLIENT_ID)}</span></div>
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
    devices: list[str] | None = None
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


# System roots that may never be opened up, at ANY depth. An allowlist entry under
# one of these would hand a third-party container the Docker socket (/run,
# /var/run), the host's secrets (/etc, /root) or its devices (/dev) — so unlike the
# data roots below, no subdirectory of these is ever acceptable.
_NEVER_ALLOWLISTABLE = (
    "/etc",
    "/root",
    "/proc",
    "/sys",
    "/dev",
    "/boot",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/run",
    "/var",  # covers /var/run (docker.sock) and /var/lib/docker
)

# How many path components an entry must have below the blocked root it sits under.
# 2 means /mnt/user/storj is allowed but /mnt/user — the whole Unraid array — is not.
_MIN_DEPTH_BELOW_ROOT = 2


def _parse_allowed_volume_roots(raw: str) -> frozenset[str]:
    """Parse CASHPILOT_ALLOWED_VOLUME_ROOTS into a set of opted-in real paths.

    Escape hatch for the blocked roots above. Some legitimate service volumes live
    under one: Storj needs a large data directory, and on Unraid the only such path
    is under /mnt/user/... — so a blanket /mnt deny made Storj undeployable through
    the worker on the platform most users run, pushing them to bypass CashPilot
    entirely (strictly worse for security than a scoped exception).

    Deny-by-default is unchanged, and an entry must clear BOTH gates:

    * it may not resolve under a system root (``_NEVER_ALLOWLISTABLE``) at any depth,
      so /run/docker.sock, /var/lib/docker/... and /etc/shadow are refused; and
    * it must sit at least ``_MIN_DEPTH_BELOW_ROOT`` components below the blocked
      root it belongs to, so /mnt/user/storj is accepted but /mnt and /mnt/user
      (the entire array) are not.

    RESIDUAL RISK, stated plainly rather than papered over: this worker resolves
    paths in its OWN mount namespace and cannot see the host filesystem, so a
    symlink created *inside* an allowlisted directory by the service that owns it
    resolves differently here than in the Docker daemon. Only allowlist a directory
    whose contents you are willing to treat as trusted.
    """
    allowed: set[str] = set()
    for entry in raw.split(":"):
        entry = entry.strip()
        if not entry:
            continue
        if not entry.startswith("/"):
            logger.warning(
                "Ignoring CASHPILOT_ALLOWED_VOLUME_ROOTS entry %r: must be an absolute path",
                entry,
            )
            continue
        # Check the resolved path AND the lexical one: resolving can move a path out
        # of a blocked prefix (on macOS /etc -> /private/etc), and a system path must
        # be refused under either spelling rather than relying on one platform's
        # symlink layout.
        real = os.path.realpath(entry)
        lexical = os.path.normpath(entry)
        if any(
            candidate == sys_root or candidate.startswith(sys_root + "/")
            for candidate in (real, lexical)
            for sys_root in _NEVER_ALLOWLISTABLE
        ):
            logger.warning(
                "Refusing CASHPILOT_ALLOWED_VOLUME_ROOTS entry %r: %s is a system path and can never be opted in",
                entry,
                real,
            )
            continue
        if real == "/" or real in _BLOCKED_VOLUME_ROOTS:
            logger.warning(
                "Refusing CASHPILOT_ALLOWED_VOLUME_ROOTS entry %r: that is a whole root, not a service directory",
                entry,
            )
            continue
        depth_ok = True  # not under any blocked root -> the deny list never applied anyway
        for blocked in _BLOCKED_VOLUME_ROOTS:
            if blocked != "/" and real.startswith(blocked + "/"):
                depth_ok = real[len(blocked) + 1 :].count("/") >= _MIN_DEPTH_BELOW_ROOT - 1
                break
        if not depth_ok:
            logger.warning(
                "Refusing CASHPILOT_ALLOWED_VOLUME_ROOTS entry %r: name a specific service "
                "directory (e.g. /mnt/user/storj), not a whole root like /mnt or /mnt/user",
                entry,
            )
            continue
        allowed.add(real)
    return frozenset(allowed)


_ALLOWED_VOLUME_ROOTS = _parse_allowed_volume_roots(os.getenv("CASHPILOT_ALLOWED_VOLUME_ROOTS", ""))

# Docker memory size syntax: a positive integer with an optional b/k/m/g unit.
_MEM_LIMIT_RE = re.compile(r"^\d+[bkmgBKMG]?$")


# Devices a service may ever request. A device is a direct line to the kernel,
# so this is a hard ceiling that the catalog cannot widen: adding an entry here
# is a deliberate maintainer decision, not something a service YAML can do on
# its own. /dev/net/tun is here because Mysterium genuinely cannot carry
# wireguard traffic without it — deployed without the device the node starts,
# registers and earns nothing, which is exactly the failure this closes.
_ALLOWED_DEVICES = frozenset({"/dev/net/tun"})


def _catalog_allowed_devices(slug: str | None = None) -> set[str]:
    """Devices the catalog declares for one slug, intersected with the ceiling.

    Scoped per-slug for the same reason capabilities are: with a union, one
    service declaring a device would let every other slug request it too. An
    unknown slug gets the empty set — deny rather than fall back to the union.
    """
    if not _catalog_get_services:
        return set()
    devices: set[str] = set()
    for svc in _catalog_get_services():
        if slug is not None and svc.get("slug") != slug:
            continue
        for dev in (svc.get("docker") or {}).get("devices") or []:
            devices.add(str(dev).split(":")[0].rstrip("/"))
    # Never return anything outside the ceiling, even if a YAML asks for it.
    return devices & set(_ALLOWED_DEVICES)


def _catalog_allowed_capabilities(slug: str | None = None) -> set[str]:
    """cap_add values the catalog declares — for one slug, or the union.

    Derived from services/*.yml (the single source of truth) instead of a
    hardcoded list, so it stays correct as the catalog changes. A capability
    no catalog service asks for is refused, whatever it is.

    Pass ``slug`` to scope the answer to that one service. That matters: with a
    union, a single service declaring NET_RAW would let *every* slug request
    NET_RAW, so adding one capability to one YAML quietly widens the allowlist
    for all 49. Per-slug keeps each service to exactly what its own YAML asks
    for. An unknown slug gets the empty set — deny, not fall back to the union.
    """
    if not _catalog_get_services:
        return set()
    caps: set[str] = set()
    for svc in _catalog_get_services():
        if slug is not None and svc.get("slug") != slug:
            continue
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
        blocked = requested - _catalog_allowed_capabilities(slug)
        if blocked:
            raise HTTPException(status_code=403, detail=f"Blocked capabilities: {', '.join(sorted(blocked))}")
    if spec.devices:
        requested_devices = {str(d).split(":")[0].rstrip("/") for d in spec.devices}
        blocked_devices = requested_devices - _catalog_allowed_devices(slug)
        if blocked_devices:
            raise HTTPException(
                status_code=403,
                detail=f"Blocked devices: {', '.join(sorted(blocked_devices))}",
            )
    if spec.network_mode not in _ALLOWED_NETWORK_MODES:
        raise HTTPException(status_code=403, detail=f"Network mode '{spec.network_mode}' is not allowed")
    if spec.network_mode == "host" and slug not in _catalog_host_network_slugs():
        raise HTTPException(status_code=403, detail=f"Network mode 'host' is not allowed for '{slug}'")
    for source in spec.volumes:
        if not source.startswith("/"):
            continue  # named volume (e.g. "mysterium-data") — always allowed
        real = os.path.realpath(source)
        if any(real == root or real.startswith(root + "/") for root in _ALLOWED_VOLUME_ROOTS):
            continue  # explicitly opted in by the operator (see _parse_allowed_volume_roots)
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
        "client_id": CLIENT_ID,
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
            devices=spec.devices,
            # spec.privileged is rejected outright by _validate_deploy_spec above, and
            # deploy_raw no longer accepts it at all — containers are never privileged.
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
async def api_remove_container(
    request: Request,
    slug: str,
    delete_volumes: bool = False,
    allow_delete_critical: bool = False,
) -> dict[str, Any]:
    _verify_api_key(request)
    try:
        result = await asyncio.to_thread(
            orchestrator.remove_service,
            slug,
            delete_volumes=delete_volumes,
            allow_delete_critical=allow_delete_critical,
        )
        return {"status": "removed", **result}
    except orchestrator.CriticalVolumeError as exc:
        # 409, not 400: the request is well-formed, the state is what refuses.
        # The container is left running - nothing has been destroyed yet.
        raise HTTPException(
            status_code=409,
            detail={
                "error": "critical_volume",
                "message": str(exc),
                "blocked": exc.blocked,
                "hint": (
                    "Nothing was removed. Back up the listed volumes first. To proceed "
                    "anyway, repeat the request with allow_delete_critical=true."
                ),
            },
        )
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
