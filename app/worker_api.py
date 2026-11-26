"""CashPilot Worker — Lightweight container management agent.

Runs on each server in the fleet. Manages local Docker containers,
sends heartbeats to the CashPilot UI, and accepts commands from it.

Configure via environment variables:
    CASHPILOT_UI_URL        URL of the CashPilot UI (e.g. http://192.168.50.100:8080)
    CASHPILOT_API_KEY       Shared API key for worker<->UI auth
    CASHPILOT_WORKER_NAME   Human-readable name (default: hostname)
    CASHPILOT_PORT          Mini-UI port (default: 8081)
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import logging
import os
import platform
import re
import shutil
import socket
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from html import escape as _esc
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
import requests
from docker.errors import APIError, DockerException
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, SecretStr, StrictBool, ValidationError

from app import (
    activity,
    egress,
    fleet_key,
    gpu,
    health_probe,
    isolation_check,
    lan_fence,
    log_redaction,
    miner_read,
    node_read,
    orchestrator,
    payout_read,
    proxy_tunnel,
    route_gate,
    state_backup,
    step_up,
    version,
    wallet_seed,
)
from app.constants import DEPLOY_DEADLINE_SECONDS, MAX_INSTANCES, PROXIED_FORBIDDEN_CAPS

try:
    from app.catalog import get_services as _catalog_get_services
except ImportError:
    # Worker image may not include the catalog module in some builds.
    _catalog_get_services = None  # type: ignore[assignment]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# httpx logs every request URL at INFO; secrets ride in some of them.
log_redaction.install()
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
MINER_TARGETS, MINER_ERRORS = miner_read.parse_targets(os.getenv("CASHPILOT_MINERS", ""))

_heartbeat_task: asyncio.Task | None = None
_miner_snapshot: dict[str, Any] | None = None
_activity_task: asyncio.Task | None = None
# Activity sampling (app/activity.py): off until the UI's heartbeat response
# says the owner switched it on for this worker. An older UI never says so.
_activity_enabled = False
# The last finished round not yet delivered, and its sequence number. A newer
# round replaces an older one; a delivered round is cleared only if no newer
# one replaced it while the heartbeat was in flight.
_pending_activity: dict[str, Any] | None = None
_activity_seq = 0
# Whether this UI has ever answered with the activity key. Once it has, a
# reply without the key (the UI could not read its config) leaves things as
# they are instead of switching sampling off.
_activity_setting_seen = False
# Replies in a row without the key since it was last seen. A UI that could not
# read its switch misses it once; a UI rolled back to a version without
# Activity never sends it again, so after a few the switch counts as off.
_activity_missing_replies = 0
ACTIVITY_MISSING_REPLIES_OFF = 3
# Bumped on every switch change, so a round that spanned an off and an on is
# dropped even though the switch is on again when it ends.
_activity_switches = 0
_ui_connected = False
_last_heartbeat: str = "never"
_last_error: str = ""

# Consecutive 401s while holding our own per-worker key. One is unremarkable (the UI
# may be restarting); a run of them means our identity no longer matches our key.
_consecutive_auth_failures = 0
_AUTH_FAILURE_ALARM_AFTER = 3
# Well above the alarm: the operator is told first, and a key is only discarded
# after the rejection has clearly persisted rather than on a flaky link.
_AUTH_FAILURE_DISCARD_AFTER = 10

# Consecutive heartbeats that did not land, for ANY reason — refused, timed out,
# unresolvable. This is what /api/health reports on, because from the operator's
# side the only thing that matters is "is this worker still reporting in".
_consecutive_heartbeat_failures = 0
# Monotonic time of the last heartbeat the UI actually accepted. The counter
# above only moves when a cycle RETURNS; a payload helper that blocks forever
# (statvfs against a wedged /data mount, a wedged Docker socket) freezes the
# loop with the counter at zero, which is the 42-hour false-healthy all over
# again. Staleness of this stamp catches raise, hang and dead-task alike.
# Initialized to process start so a freshly booted worker gets the same grace
# window before it is expected to have reported in.
_last_heartbeat_ok = time.monotonic()
# The endpoint DEGRADES once 12 consecutive sends have missed (~11 min after
# the outage starts — the first failure lands at t≈0) or the last accepted
# heartbeat is _HEARTBEAT_STALE_AFTER (16 min) old; `docker ps` flips to
# unhealthy up to 3 failed checks (~90s) later — the counter path is visible
# the same quarter-hour, the hang path within 20 minutes. Long enough that a
# UI restart or a brief blip does not flap the container. It MUST stay
# above _AUTH_FAILURE_DISCARD_AFTER: this repo documents an autoheal sidecar
# that restarts unhealthy containers, a restart resets the in-memory auth
# ladder while the stale key file survives on disk — so an unhealthy threshold
# below the discard threshold would restart-loop a locked-out worker at N
# failures forever and the discard-and-re-enrol self-heal could never run.
_HEARTBEAT_FAILURES_UNHEALTHY_AFTER = 12
# The staleness backstop gets its own, LONGER window. The discard ladder is
# counted in CYCLES and a cycle costs 60s plus payload time (container stats
# stretch it with fleet size; nvidia-smi alone may burn its 10s timeout), so a
# wall-clock window equal to 12 nominal cycles can expire BEFORE failure #10
# lands on a slow host — tripping unhealthy (and any restart-on-unhealthy
# supervisor) during the worker's own self-heal. Four extra nominal cycles
# tolerate ~36s of per-cycle overhead before that ordering could invert.
_HEARTBEAT_STALE_AFTER = (_HEARTBEAT_FAILURES_UNHEALTHY_AFTER + 4) * HEARTBEAT_INTERVAL
# How long Docker may fail every call before /api/health says so. A daemon
# restart or a docker-ce upgrade (live-restore keeps the containers) takes a
# minute or two; the shipped compose files bind the socket FILE into the proxy,
# and when the host replaces that socket the proxy never sees the new one, so
# the outage lasts until someone restarts the proxy. On 2026-11-17 that was 17
# hours of a worker answering 200 here while it could not manage a container.
_DOCKER_UNHEALTHY_AFTER = 10 * 60
# The name-resolution hint is logged ONCE per outage, not every cycle. A warning
# repeated every 60 seconds for 42 hours is precisely how the last one was missed.
_link_hint_logged = False

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


def _discard_worker_key(reason: str) -> None:
    """Forget our per-worker key so the next heartbeat re-enrols.

    Removing a worker in the fleet dashboard deletes its row and its key on the
    UI side, but the worker keeps sending the key it persisted — so it 401s
    forever, on a host whose containers are still running and still earning.
    Nothing on either side says why: the UI shows one fewer worker, the worker
    logs a bare 401. The documented recovery ("remove it and the shared key is
    accepted again") could not work, and the real fix was SSHing in to delete a
    file that is documented nowhere.

    Bounded on purpose. Discarding after a single failure would re-enrol on any
    transient blip and widen the window in which the shared key is accepted; it
    takes sustained rejection, which is what a deleted row actually looks like.
    """
    global _worker_key, _consecutive_auth_failures
    try:
        _WORKER_KEY_FILE.unlink(missing_ok=True)
    except OSError as exc:
        logger.error(
            "Could not remove the stale per-worker key at %s: %s. Delete it by hand "
            "and restart this container to re-enrol.",
            _WORKER_KEY_FILE,
            exc,
        )
        return
    _worker_key = None
    _consecutive_auth_failures = 0
    logger.warning(
        "Discarded this worker's per-worker key (%s). Re-enrolling with the shared key on the next heartbeat.",
        reason,
    )


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
# Activity probes carry it, so two workers on one Docker host never remove each other's.
activity.WORKER_ID = CLIENT_ID


def _active_key() -> str:
    """The key we authenticate with: our own once enrolled, else the shared key."""
    return _worker_key or API_KEY


# The heartbeat's identity_digest is keyed with the same key, which the UI holds too.
orchestrator.identity_digest_key = _active_key


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
# Wall-clock budget for the WHOLE attempt, shared across every endpoint tried
# (see the deadline in _detect_egress_ip). Per-endpoint would multiply by the
# endpoint count: at 3 endpoints plus the 15s heartbeat POST that is already 45s
# on a 60s serial cycle, and a longer list would breach the 180s offline
# threshold — the exact failure this bound exists to prevent. httpx's timeout is PER
# OPERATION — its read timeout is the maximum gap between chunks, not a deadline
# — so an endpoint dribbling one byte every few seconds would hold the request
# open indefinitely. That matters here because the heartbeat loop is serial: a
# stalled lookup stops heartbeats entirely and the UI marks this worker offline
# after 180s, so deploys and restarts for this host start failing. A diagnostic
# nicety must never be able to take the control plane down.
_EGRESS_TOTAL_TIMEOUT = 10.0
# Enough for any textual IP form; the body is never read past this.
_EGRESS_MAX_BYTES = 128


def _disk_usage() -> dict[str, Any] | None:
    """Free and total bytes on the filesystem holding the data directory.

    Storj is paid for data it STORES, so free space is earning capacity, not a
    housekeeping detail -- a node that quietly fills up stops growing and nothing
    in CashPilot said so.

    Returns None when it cannot be read. None is UNKNOWN; a caller must not
    render it as 0 (a full disk) or as 100% (an empty one). Both are worse than
    an em-dash.
    """
    try:
        usage = shutil.disk_usage(str(_WORKER_ID_FILE.parent))
    except OSError as exc:
        logger.debug("Could not read disk usage: %s", exc)
        return None
    return {"path": str(_WORKER_ID_FILE.parent), "free_bytes": usage.free, "total_bytes": usage.total}


def _gpu_info() -> dict[str, Any]:
    """What this worker can see of a GPU, and how sure it is.

    Salad, Nosana, io.net and Vast.ai only earn when a real GPU is present AND
    usable. Today a GPU service that is running but idle -- because the device
    was never passed into the container -- looks exactly like one that is
    earning. That is the Mysterium /dev/net/tun failure again: healthy-looking
    and worth nothing.

    THE THREE-VALUED PART MATTERS:

        available True   we saw a device
        available False  sysfs was read and lists no NVIDIA, AMD or Intel GPU,
                         so the host really has none
        available None   we could not tell (not Linux, WSL, sysfs unreadable)

    sysfs shows the host's PCI bus from inside a container with nothing passed
    in, so the worker behind the socket proxy reads the host's GPUs there first
    (app/gpu.py). nvidia-smi and /dev/dri stay as the fallback where sysfs says
    nothing. Reporting None as False would tell someone their machine has no
    GPU when it may have an unused one, which is the opposite of the useful answer.
    """
    info = _gpu_presence()
    # What Docker says about passing in an NVIDIA GPU (orchestrator.gpu_runtime_facts).
    facts = orchestrator.gpu_runtime_facts()
    info["nvidia_toolkit"] = facts.get("nvidia_toolkit")
    info["default_runtime"] = facts.get("default_runtime")
    return info


def _gpu_presence() -> dict[str, Any]:
    host = gpu.host_gpus()
    if host["conclusive"]:
        vendors = host["vendors"]
        devices = []
        for vendor in gpu.VENDORS:
            if vendor not in vendors:
                continue
            nodes = len(vendors[vendor].get("render_nodes") or [])
            devices.append(
                f"{gpu.VENDOR_NAMES[vendor]} GPU"
                + (f" ({nodes} render node{'s' if nodes != 1 else ''})" if nodes else "")
            )
        info: dict[str, Any] = {
            "available": bool(vendors),
            "devices": devices,
            "detected_by": "sysfs" if vendors else None,
            "vendors": vendors,
        }
        if not vendors:
            info["reason"] = "sysfs lists no NVIDIA, AMD or Intel GPU on this machine"
        return info
    if not gpu.local_endpoint(os.environ.get("DOCKER_HOST", "")):
        # Docker may run on another machine: nvidia-smi and /dev/dri below
        # would describe this one, so say why nothing is known instead.
        return {"available": None, "devices": [], "detected_by": None, "reason": host["reason"]}

    devices: list[str] = []
    how = None

    nvidia = shutil.which("nvidia-smi")
    if nvidia:
        try:
            out = subprocess.run(  # noqa: S603 - fixed binary, no shell, no user input
                [nvidia, "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if out.returncode == 0:
                devices = [line.strip() for line in out.stdout.splitlines() if line.strip()]
                how = "nvidia-smi"
        except (OSError, subprocess.SubprocessError) as exc:
            logger.debug("nvidia-smi failed: %s", exc)

    if not devices:
        # A DRM render node means SOME GPU is reachable -- integrated, AMD, or an
        # NVIDIA card without the management tool. Enough to say "yes", not
        # enough to name it.
        render_nodes = sorted(str(p) for p in Path("/dev/dri").glob("renderD*")) if Path("/dev/dri").is_dir() else []
        if render_nodes:
            devices = [f"DRM render node ({len(render_nodes)})"]
            how = "drm"

    if devices:
        return {"available": True, "devices": devices, "detected_by": how}

    # Both probes above are LINUX-specific: nvidia-smi is not on a stock macOS,
    # and /dev/dri is the Linux DRM interface. Their absence on any other
    # platform proves nothing at all -- every Mac has a GPU. Caught by running
    # this on macOS, where the first version confidently reported "no GPU".
    if platform.system() != "Linux":
        return {
            "available": None,
            "devices": [],
            "detected_by": None,
            "reason": f"GPU detection is not implemented for {platform.system()}; this says nothing about whether one exists",
        }

    if Path("/.dockerenv").exists():
        # On Linux, in a container, with nothing passed through. We genuinely
        # cannot tell -- and this is exactly when a user most needs to know,
        # because it is the case where a GPU service runs and earns nothing.
        return {
            "available": None,
            "devices": [],
            "detected_by": None,
            "reason": "no GPU is visible from inside this container; the host may still have one that was not passed through",
        }

    # Linux, sysfs unreadable (or WSL), no NVIDIA tool and no render node. Only
    # a conclusive sysfs read says "no".
    return {"available": None, "devices": [], "detected_by": None, "reason": host.get("reason")}


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

    if egress.detection_off():
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

    deadline = time.monotonic() + _EGRESS_TOTAL_TIMEOUT
    for url in endpoints:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            logger.debug("Egress IP lookup budget exhausted before trying %s", url)
            break
        try:
            found = await asyncio.wait_for(_fetch_egress_ip(url), timeout=remaining)
        except Exception as exc:  # noqa: BLE001 — never let this break a heartbeat
            logger.debug("Egress IP lookup via %s failed: %s", url, exc)
            continue
        if found:
            _egress_cache = (found, now)
            return found

    _egress_cache = (None, now)
    return None


def _ui_host() -> str:
    """Hostname of UI_URL, safe to log.

    CASHPILOT_UI_URL can carry userinfo (a UI behind reverse-proxy basic auth is
    `https://user:pass@host`), and string-splitting leaked it: `token@host` kept
    the whole token, `user:pass@host` printed the username as the "host". Parse
    properly and log only the hostname.
    """
    raw = UI_URL if "://" in UI_URL else f"//{UI_URL}"
    try:
        host = urlsplit(raw).hostname
    except ValueError:
        host = None
    return host or "<unparseable CASHPILOT_UI_URL>"


def _reason(exc: BaseException) -> str:
    """What failed, for a log line. A timeout (TimeoutError, httpx.ReadTimeout) has an empty str()."""
    return str(exc) or type(exc).__name__


def _redact_userinfo(text: str) -> str:
    """Strip URL credentials (user:pass@ / token@) from a URL or a message.

    Applied to log text that can embed UI_URL: httpx's HTTPStatusError message
    interpolates str(request.url) UNREDACTED, so a credentialed CASHPILOT_UI_URL
    put the password in the per-cycle "Heartbeat failed" warning.

    The userinfo class deliberately allows '@' so the greedy match runs to the
    LAST '@' before the path — a password containing an unencoded '@' must not
    half-survive. Scheme matching is case-insensitive ('HTTPS://user:pass@h'
    is a working httpx config).
    """
    text = re.sub(r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s'\"]*@", r"\1", text)
    return re.sub(r"^[^/\s]*@", "", text, count=1)


def _log_link_failure_hint(exc: BaseException) -> None:
    """Explain a heartbeat that never reached the UI, once per outage.

    A worker that cannot resolve CASHPILOT_UI_URL logs the same opaque line
    every 60 seconds — `Heartbeat failed: [Errno -3] Try again` — which says
    nothing about the cause and is trivially scrolled past. In production this
    ran for 42 hours on two hosts before anyone looked, while the containers
    kept earning and the UI simply showed the workers as offline.

    The usual cause is not DNS being broken: it is that the worker is not on the
    same Docker network as the UI. Compose service names only resolve inside a
    shared user-defined network, so a container that was started detached (an
    unclean shutdown, `docker start` on a container whose project network was
    since recreated) fails to resolve a name that is otherwise perfectly valid.
    """
    global _link_hint_logged
    if _link_hint_logged:
        return

    # The resolution failure is usually wrapped (httpx.ConnectError -> gaierror),
    # so inspect the whole chain rather than just the surface exception.
    seen: set[int] = set()
    cur: BaseException | None = exc
    is_resolution_failure = False
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, socket.gaierror):
            is_resolution_failure = True
            break
        # Honor `raise X from None`: a suppressed context was deliberately
        # disowned, and following it anyway would blame DNS for an exception
        # that merely HAPPENED during a resolution failure's cleanup.
        cur = cur.__cause__ if cur.__cause__ is not None or cur.__suppress_context__ else cur.__context__

    if not is_resolution_failure:
        return

    host = _ui_host()
    logger.error(
        "Cannot resolve %r from inside this container, so no heartbeat can reach the UI. "
        "If that is a Compose service name, this worker and the UI must share a Docker "
        "network — check `docker inspect %s --format '{{json .NetworkSettings.Networks}}'`: "
        "an empty result means this container is attached to NO network, which `docker start` "
        "can leave behind after an unclean shutdown. `docker compose up -d` reattaches it. "
        "If the UI is on another host, use an address this container can actually resolve. "
        "Logging this once; the per-cycle warning continues.",
        host,
        WORKER_NAME,
    )
    _link_hint_logged = True


async def _send_heartbeat() -> None:
    """Send a single heartbeat to the UI."""
    global _ui_connected, _last_heartbeat, _last_error, _consecutive_auth_failures
    global _consecutive_heartbeat_failures, _link_hint_logged, _last_heartbeat_ok

    containers = []
    listed = False
    try:
        containers = await asyncio.to_thread(orchestrator.get_status)
        listed = orchestrator.status_listed()
    except Exception as exc:
        logger.warning("Failed to get container status for heartbeat: %s", exc)

    # The isolation check needs the Docker socket, so a worker without one
    # does not offer it in "features": the button could only fail.
    # A daemon that answers the ping but would not list the containers above
    # is blind too: its outage clock is still running (orchestrator._mark_listing_failed).
    docker_ok = await asyncio.to_thread(orchestrator.docker_available)
    docker_down = orchestrator.docker_unreachable_for()
    docker_ok = docker_ok and docker_down is None
    egress_ip = await _detect_egress_ip()
    # The fence drops this address too, so the router's NAT loopback cannot
    # carry an earner back into the LAN. A new address is fenced at once,
    # not at the next five-minute check.
    if lan_fence.set_egress_ip(egress_ip) and docker_ok:
        await _check_fence()
    features = (
        ["instances", "isolation_check", "state_backup", "activity", "proxy_tunnel"] if docker_ok else ["instances"]
    )
    # Every deploy this worker runs ends by DEPLOY_DEADLINE_SECONDS, so the UI
    # may let go of the ids of one it got no answer for (main._settle_pending_identities).
    features.extend(("deploy_deadline", "expected_container"))
    # Keeps a catalog seed_file wallet in the node's own volume, never in its
    # env, and makes or takes one on deploy (app/wallet_seed.py). The UI sends
    # a new seed-file deploy to no other worker.
    features.append(wallet_seed.FEATURE)
    # None, not an empty list, when they could not be read: the UI alerts on a
    # copy this list leaves out, and "could not look" must not read as "gone".
    proxied: list[dict[str, Any]] | None = []
    if docker_ok:
        try:
            proxied = await asyncio.to_thread(proxy_tunnel.status)
        except Exception as exc:  # noqa: BLE001 - one missed reading, not a missed heartbeat
            logger.warning("Failed to read proxied copies for heartbeat: %s", exc)
            proxied = None
    routes_read = _mark_routed(proxied) if proxied else True
    payload = {
        "name": WORKER_NAME,
        "client_id": CLIENT_ID,
        "url": WORKER_URL or f"http://{_get_local_ip()}:{WORKER_PORT}",
        "containers": containers,
        "system_info": {
            "os": f"{platform.system()} {platform.release()}",
            "arch": platform.machine(),
            "hostname": socket.gethostname(),
            "docker_available": docker_ok,
            # False when "containers" is not the whole list (Docker would not
            # list them, or one could not be read): the UI then retires no
            # device id of a copy the list leaves out.
            "containers_listed": listed,
            # So the UI can tell an operator when the two halves are different
            # releases. An older worker sends nothing here, which reads as
            # unknown rather than as a mismatch (CashPilot-l6c).
            "version": version.current(),
            # What this worker can do that an older one cannot. The UI sends a
            # second copy of a service only to a worker listing "instances": an
            # older worker would read the deploy as the first copy and replace it.
            "features": features,
            # Providers count devices per public IP, so the UI needs the address
            # the provider sees — not this container's LAN or tailnet address.
            "egress_ip": egress_ip,
            "egress_network_type": _detect_network_type(),
            # Disk is earning capacity for Storj; GPU decides whether the compute
            # services can earn at all. Both are None/unknown-aware -- see the
            # helpers (CashPilot-cle).
            "disk": await asyncio.to_thread(_disk_usage),
            "gpu": await asyncio.to_thread(_gpu_info),
            # Which isolation mode this worker is in and whether its fence holds.
            # Cached by the fence check, so no helper container runs per heartbeat.
            "isolation": lan_fence.status(),
            # Copies of services that leave through a proxy (app/proxy_tunnel.py).
            # Kept out of "containers": they are on another exit IP and are not
            # copies of the service, so nothing that counts copies may see them.
            "proxied": proxied,
            # False when the routes could not be read: no entry above says
            # routed, so the list shows no routed service's copy 1, which
            # may still run (main.api_worker_heartbeat).
            "routes_read": routes_read,
            # Set by the operator (app/route_gate.py): no earner runs from this
            # box's own IP, so the UI offers only routed deploys here.
            "proxied_only": route_gate.proxied_only(),
        },
    }
    if MINER_TARGETS or MINER_ERRORS:
        features.append("miner_read")
        payload["system_info"]["miners"] = _miner_snapshot or {
            "read_at": None,
            "devices": [],
            "errors": MINER_ERRORS,
        }
    # "proxy" or "socket": what to restart when Docker stops answering, so the
    # UI's alert can name it (main._worker_docker_check).
    payload["system_info"]["docker_access"] = orchestrator.docker_access()
    if docker_down is not None:
        # How long Docker has failed, so the UI's alert grace counts from the
        # outage's start and not from the UI's own restart.
        payload["system_info"]["docker_unreachable_for"] = int(docker_down)
    if docker_ok:
        # This worker fences its earners off the LAN by itself and takes
        # POST /api/isolation to switch an upgraded install over (app/lan_fence.py).
        payload["system_info"]["features"].append("isolation_default")
        # Starts a fence_gated service (Mysterium) only behind a confirmed fence,
        # on the bridge, with its port range and several WebUI addresses.
        payload["system_info"]["features"].append("fence_gated")
        # Deploys a service through a proxy from its first start, and keeps it
        # off this box's own IP until the owner confirms otherwise (route_gate).
        payload["system_info"]["features"].append("route_at_deploy")
        # Takes "only_if_running" on a proxied copy deploy, so the UI can rebuild
        # a running copy without starting one the owner stopped meanwhile.
        payload["system_info"]["features"].append("proxied_if_running")
        # Restores a passphrase backup into a new container (POST /api/containers/{slug}/restore).
        payload["system_info"]["features"].append("state_restore")
        # Gives a catalog service the GPU its own catalog entry declares (docker.gpu, app/gpu.py).
        payload["system_info"]["features"].append("gpu_grant")
        payload["system_info"]["gpu_grants"] = {
            service["slug"]: grant
            for service in (_catalog_get_services() if _catalog_get_services else [])
            if not service["slug"].startswith("custom-") and (grant := gpu.spec_of(service))
        }
        # The services a restore that did not finish left half-written here. The
        # box may hold no container of one, so the dashboard draws its Remove
        # from this list. Left out when it cannot be read.
        try:
            payload["system_info"]["restore_unfinished"] = await asyncio.to_thread(orchestrator.unfinished_restores)
        except Exception as exc:  # noqa: BLE001 - one missed reading, not a missed heartbeat
            logger.warning("Failed to list unfinished restores for heartbeat: %s", exc)
    # Only what the owner asked for, and only a finished round.
    sent_seq = _activity_seq
    if _activity_enabled and _pending_activity is not None:
        payload["activity"] = _pending_activity

    fleet_exits_changed = False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{UI_URL.rstrip('/')}/api/workers/heartbeat",
                json=payload,
                headers={"Authorization": f"Bearer {_active_key()}"},
            )
            resp.raise_for_status()
            # The heartbeat LANDED — record the success before any enrollment
            # bookkeeping. This state measures "did the UI hear from us", and a
            # bug in the bookkeeping below (a UI version skew handing back a
            # malformed worker_key, say) must not count a delivered heartbeat
            # as a connection failure and degrade a perfectly reporting worker.
            _ui_connected = True
            _last_heartbeat = datetime.now(UTC).strftime("%H:%M:%S UTC")
            _last_heartbeat_ok = time.monotonic()
            _last_error = ""
            _consecutive_auth_failures = 0
            _consecutive_heartbeat_failures = 0
            _link_hint_logged = False
            logger.debug("Heartbeat sent to %s", _ui_host())
            try:
                _apply_activity_reply(resp, sent_seq if "activity" in payload else None)
            except Exception:  # noqa: BLE001 - never counts against the heartbeat
                logger.warning("Activity bookkeeping failed (heartbeat itself landed)")
            try:
                fleet_exits_changed = _apply_fleet_exits_reply(resp)
            except Exception:  # noqa: BLE001 - never counts against the heartbeat
                logger.warning("Fleet exits bookkeeping failed (heartbeat itself landed)")
            try:
                # Enrollment: the UI returns our own per-worker key exactly once.
                # Taken only while we are still on the shared key. The real UI
                # never sends one to an enrolled worker, so a key in the reply
                # then can only come from whoever answered in its place, and
                # adopting it would lock the real UI out of this worker.
                issued = None
                with contextlib.suppress(Exception):
                    issued = resp.json().get("worker_key")
                if issued and _worker_key is None:
                    if _save_worker_key(issued):
                        logger.info("Enrolled: received and persisted this worker's own fleet key")
                    else:
                        logger.error("Received per-worker key but could not persist it — staying on shared key")
            except Exception as exc:  # noqa: BLE001 - bookkeeping must not report as an outage
                logger.error("Enrollment bookkeeping failed (heartbeat itself landed): %s", _redact_userinfo(str(exc)))
    except httpx.HTTPStatusError as exc:
        _ui_connected = False
        _consecutive_heartbeat_failures += 1
        # A reply — any reply — proves the UI's name resolves, so a resolution
        # outage is over and the hint must re-arm. Resetting only on full
        # success left the flag stuck True through a post-outage 401 spell,
        # silencing the hint for the NEXT resolution outage.
        _link_hint_logged = False
        status = exc.response.status_code
        _last_error = f"authentication rejected ({status})" if status in (401, 403) else "connection failed"
        logger.warning("Heartbeat failed: %s", _redact_userinfo(str(exc)))
        if status == 401:
            # Counted whether or not we hold our own key. The condition used to
            # be `and _worker_key`, which skipped the alarm in exactly the case
            # it is most needed: a worker that LOST /data/.worker_key — a partial
            # restore, an appdata copy that skips dotfiles — holds no key, sends
            # the shared one, and is refused because the UI's row for this
            # client_id is enrolled and confirmed. That worker 401'd forever and
            # logged nothing but a generic "Heartbeat failed" every 60 seconds,
            # while its service containers kept earning (CashPilot-65s).
            _consecutive_auth_failures += 1
            if _consecutive_auth_failures == _AUTH_FAILURE_ALARM_AFTER:
                # Two different lockouts, two different fixes. Saying the wrong
                # one is worse than saying nothing: the previous message told the
                # operator to write a client_id into /data/.worker_id, which is
                # the fix for neither of the lockouts that actually happen — in
                # both the id is fine and it is the KEY that has to change — and
                # it named an id the dashboard has never displayed.
                if _worker_key:
                    logger.error(
                        "Rejected %d times with this worker's own key. Either it was removed "
                        "in the fleet dashboard, or the UI's credential-encryption key changed "
                        "so it can no longer read the copy it stored. Both are recovered the "
                        "same way and this worker will do it itself after about %d more "
                        "rejections: discard the key and re-enrol. To fix it now, delete %s "
                        "on this host and restart the container.",
                        _consecutive_auth_failures,
                        _AUTH_FAILURE_DISCARD_AFTER - _consecutive_auth_failures,
                        _WORKER_KEY_FILE,
                    )
                else:
                    logger.error(
                        "Rejected %d times using the shared CASHPILOT_API_KEY. The UI already "
                        "has a confirmed enrolment for client_id %r, so it refuses the shared "
                        "key for it — this worker has lost the per-worker key it was issued "
                        "(%s is missing). Restore that file, or remove this worker in the fleet "
                        "dashboard and it will enrol again on its next heartbeat.",
                        _consecutive_auth_failures,
                        CLIENT_ID,
                        _WORKER_KEY_FILE,
                    )
            elif _worker_key and _consecutive_auth_failures >= _AUTH_FAILURE_DISCARD_AFTER:
                # Sustained rejection of our own key is what a worker REMOVED in
                # the dashboard looks like from here. Re-enrol rather than 401
                # forever on a host that is still running containers.
                _discard_worker_key(f"rejected {_consecutive_auth_failures} times; the UI no longer has this enrolment")
        else:
            # Any other outcome breaks the run. "Consecutive" has to mean it:
            # 401 -> timeout -> 401 -> 500 -> 401 is a flaky link, not an
            # identity mismatch, and must not raise the alarm.
            _consecutive_auth_failures = 0
    except Exception as exc:
        _ui_connected = False
        _last_error = "connection failed"
        # A network failure is not an auth rejection, so it breaks the run too.
        _consecutive_auth_failures = 0
        _consecutive_heartbeat_failures += 1
        logger.warning("Heartbeat failed: %s", _redact_userinfo(_reason(exc)))
        _log_link_failure_hint(exc)
    # The other boxes' exits are fenced as soon as they arrive or change, as
    # this box's own new IP is above.
    if fleet_exits_changed and docker_ok:
        await _check_fence()


def _apply_fleet_exits_reply(resp: Any) -> bool:
    """Take the other boxes' public IPs from the UI's reply. True when the fence must be applied again.

    A null list comes from a UI that could not read the fleet this time: the
    list stays as it is, unknown after a restart, so the table keeps its drops.
    A reply without the key comes from an older UI. If the UI rolled back to
    before the list, keep the drops it gave. Start with an empty list only if
    the worker has no list yet.
    """
    body: Any = None
    with contextlib.suppress(Exception):
        body = resp.json()
    if not isinstance(body, dict) or "fleet_exits" in body and not isinstance(body["fleet_exits"], list):
        return False
    if isinstance(body.get("fleet_exits"), list):
        return lan_fence.set_fleet_exits(body["fleet_exits"])
    if lan_fence._fleet_exits["ips"] is None:
        return lan_fence.set_fleet_exits([])
    return False


def _mark_routed(entries: list[dict[str, Any]]) -> bool:
    """Flag the proxied entries that are a routed service, not a copy beside a direct one.

    The UI counts those as the service running on this box (app/placement.py)
    and shows them on the dashboard; a copy keeps its own list on the Proxies page.
    False when the routes could not be read, so nothing is flagged.
    """
    try:
        lock = route_gate.routed()
    except (OSError, ValueError) as exc:
        logger.warning("Could not read which services are routed: %s", exc)
        return False
    for entry in entries:
        if lock.get(str(entry.get("slug"))) == entry.get("proxy_id"):
            entry["routed"] = True
    return True


async def _miner_loop() -> None:
    global _miner_snapshot
    while True:
        snapshot = await miner_read.read_all(MINER_TARGETS)
        _miner_snapshot = {**snapshot, "errors": MINER_ERRORS}
        await asyncio.sleep(miner_read.READ_INTERVAL)


async def _heartbeat_loop() -> None:
    """Send heartbeats to the UI at regular intervals.

    Every cycle is guarded. _send_heartbeat builds its payload OUTSIDE its own
    try (docker_available, the egress lookup and the network-type probe all run
    while the dict literal is evaluated), so an exception there would otherwise
    propagate out of this loop and kill the task silently and permanently.
    That is strictly worse than any single failed heartbeat: a missed cycle
    costs one 180s offline window and self-heals, whereas a dead task means
    offline until someone restarts the container — while the service containers
    keep earning and nothing surfaces the problem.
    """
    global _ui_connected, _last_error, _consecutive_heartbeat_failures
    while True:
        try:
            await _send_heartbeat()
        except asyncio.CancelledError:
            raise
        except Exception:
            # A cycle that died before the POST is still a heartbeat that did
            # not land. Without this accounting a worker whose payload
            # construction fails every time never degrades /api/health — 200
            # "ok" forever while it never reports in, which is exactly the
            # invisible state this endpoint exists to expose.
            _ui_connected = False
            _consecutive_heartbeat_failures += 1
            _last_error = "internal error preparing the heartbeat"
            logger.exception("Heartbeat cycle failed — continuing")
        await asyncio.sleep(HEARTBEAT_INTERVAL)


_fence_task: asyncio.Task | None = None
#: Seconds the startup fence check may hold the worker before it carries on.
FENCE_STARTUP_TIMEOUT = 30


async def _check_fence(startup: bool = False) -> None:
    """Put the fence back if it went, and refresh what the heartbeat reports. Never raises."""
    started = time.monotonic()
    try:
        state = await asyncio.wait_for(asyncio.to_thread(lan_fence.reconcile), FENCE_STARTUP_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 - a fence problem must never stop the worker
        logger.warning("LAN fence check did not finish: %s", _reason(exc))
        return
    if startup:
        fence = state.get("fence") or {}
        logger.info(
            "Isolation: mode %s, fence %s%s (%.1f s after start)",
            state.get("mode"),
            fence.get("state"),
            f": {fence['error']}" if fence.get("error") else "",
            time.monotonic() - started,
        )


async def _fence_loop() -> None:
    """Every RECHECK_SECONDS: a reboot, ``nft flush ruleset`` or a firewalld reload removes the table."""
    while True:
        await asyncio.sleep(lan_fence.RECHECK_SECONDS)
        await _check_fence()
        await _recheck_status_listing()


async def _recheck_status_listing() -> None:
    """Read the whole status again while an outage get_status recorded is open. Never raises.

    The fence lists only the managed containers, so its success cannot end
    that outage (orchestrator._mark_docker_listed), and a worker with no UI
    runs no get_status of its own. Without this, one failed read on a page
    load kept /api/health 503 until the next page load.
    """
    if orchestrator._docker_listing_failed != "status":
        return
    try:
        await asyncio.wait_for(asyncio.to_thread(orchestrator.get_status_light), FENCE_STARTUP_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 - the next pass tries again
        logger.debug("Status recheck did not finish: %s", _reason(exc))


_guard_task: asyncio.Task | None = None
#: time.monotonic() when lifespan began: what the sweep's min_age counts from.
_started_at = time.monotonic()


async def _guard_once() -> None:
    """One pass of the fence guard (lan_fence.guard), then of the proxied-only one, then the failed starts. Never raises."""
    try:
        await asyncio.wait_for(asyncio.to_thread(lan_fence.guard), FENCE_STARTUP_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 - the next pass tries again
        logger.warning("Fence guard pass did not finish: %s", _reason(exc))
    await _hold_direct_earners()
    await _start_failed_starts()


async def _start_failed_starts() -> None:
    """Start again the earners Docker could not start at its boot (orchestrator.start_failed_starts). Never raises."""
    try:
        await asyncio.wait_for(asyncio.to_thread(orchestrator.start_failed_starts), FENCE_STARTUP_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 - the next pass tries again
        logger.warning("Could not look for earners whose start failed: %s", _reason(exc))


async def _hold_direct_earners() -> None:
    """On a CASHPILOT_PROXIED_ONLY worker, stop any earner running from the box's own IP. Never raises."""
    try:
        await asyncio.to_thread(orchestrator.hold_direct_earners)
    except Exception as exc:  # noqa: BLE001 - the next guard pass tries again
        logger.warning("Could not check for earners outside a tunnel: %s", _reason(exc))


async def _guard_loop() -> None:
    """Every GUARD_SECONDS: start fence-gated services behind a confirmed fence, stop them without one."""
    while True:
        await asyncio.sleep(lan_fence.GUARD_SECONDS)
        await _guard_once()


async def _wait_for_docker_loop() -> None:
    """Every GUARD_SECONDS until Docker answers, for a worker that started without it; then the guard loop.

    Docker starts containers by their restart policy after a reboot and ignores
    compose depends_on, so the worker can come up before cashpilot-socket-proxy
    (or the proxy is recreated under it). /api/health turns OK as soon as Docker
    answers, so without this the steps below never ran for the life of the
    process and nothing said so: a fence-gated node (Mysterium) has no restart
    policy, and only the guard starts it.

    A pass does nothing until Docker answers: without it there is no earner to
    hold, and each pass would log the same failure forever. The first pass that
    sees Docker runs the start's steps in the start's order, then this becomes
    the guard loop, which holds direct earners on every pass.
    """
    while True:
        await asyncio.sleep(lan_fence.GUARD_SECONDS)
        if await asyncio.to_thread(orchestrator.docker_available):
            break
    logger.info(
        "Docker: direct (%s, came back after start)",
        "through the socket proxy" if orchestrator.proxied() else "direct socket",
    )
    await _hold_direct_earners()
    lan_fence.set_egress_ip(await _detect_egress_ip())
    # The fence before the guard pass that may start a fence-gated node.
    await _check_fence(startup=True)
    await _guard_once()
    # The API has been serving since the start, so a proxy test can be in flight:
    # the sweep keeps every Test tunnel younger than this process.
    await _resume_proxied_work(sweep_min_age=time.monotonic() - _started_at)
    await _guard_loop()


async def _resume_proxied_work(sweep_min_age: float = 0.0) -> None:
    """The start's proxied-copy steps, once Docker answers. Never raises."""
    # A proxied copy this worker was moving into another tunnel when it
    # stopped: finished or put back before anything else looks at it.
    try:
        await asyncio.to_thread(proxy_tunnel.recover_moves)
    except Exception as exc:  # noqa: BLE001 - never block the start on it; the heartbeat tries again
        logger.warning("Could not look for half-done proxied copy moves: %s", exc)
    # A proxy Test tunnel this worker left behind when it stopped mid-test.
    try:
        if swept := await asyncio.to_thread(proxy_tunnel.sweep_test_tunnels, min_age=sweep_min_age):
            logger.info("Removed %d leftover proxy test tunnel(s)", len(swept))
    except Exception as exc:  # noqa: BLE001 - never block the start on it
        logger.warning("Could not look for leftover proxy test tunnels: %s", exc)


def _apply_activity_reply(resp: Any, delivered_seq: int | None) -> None:
    """Follow the UI's activity switch, and drop a round it has stored.

    A reply without the key comes from a UI that predates Activity (off), or,
    once this UI has sent the key before, from one that could not read its
    switch this time (unchanged). A round is dropped only when the UI says it
    stored it; a UI that sends no ``stored`` predates the field and stored it.
    """
    global _activity_enabled, _pending_activity, _activity_setting_seen, _activity_missing_replies
    global _activity_switches
    body: Any = None
    with contextlib.suppress(Exception):
        body = resp.json()
    setting = body.get("activity") if isinstance(body, dict) else None
    if isinstance(setting, dict):
        _activity_setting_seen = True
        _activity_missing_replies = 0
    elif _activity_setting_seen:
        _activity_missing_replies += 1
        if _activity_missing_replies < ACTIVITY_MISSING_REPLIES_OFF:
            return
    enabled = bool(setting.get("enabled")) if isinstance(setting, dict) else False
    if not enabled:
        if _activity_enabled:
            logger.info("Activity sampling switched off by the UI")
            _activity_switches += 1
        _activity_enabled = False
        _pending_activity = None
        activity.reset()
        return
    if not _activity_enabled:
        logger.info("Activity sampling switched on by the UI")
        _activity_switches += 1
        # Counter state from before the switch-off would turn the first new
        # reading into one window holding the whole gap.
        activity.reset()
    _activity_enabled = True
    stored = setting.get("stored", True) is not False if isinstance(setting, dict) else False
    if delivered_seq is not None and delivered_seq == _activity_seq and stored:
        _pending_activity = None


def _seconds_to_next_window(now: float | None = None) -> float:
    now = time.time() if now is None else now
    return activity.WINDOW_SECONDS - (now % activity.WINDOW_SECONDS) + 1


def _sweep_probes() -> None:
    """Open a client, sweep, close it, all in one thread: a cancelled await cannot drop the client."""
    client = activity._client()
    try:
        activity.sweep(client)
    finally:
        with contextlib.suppress(Exception):
            client.close()


async def _activity_cycle() -> None:
    """One round, if the owner switched Activity on and Docker answers.

    With Activity off there is no round, but probes other workers left behind
    are still swept: their logs hold raw addresses and nothing else removes them.
    """
    global _pending_activity, _activity_seq
    if not await asyncio.to_thread(orchestrator.docker_available):
        return
    if not _activity_enabled:
        await asyncio.to_thread(_sweep_probes)
        return
    switches = _activity_switches
    result = await asyncio.to_thread(activity.run_round)
    if not _activity_enabled or _activity_switches != switches:
        # Switched off while the round ran (even if on again by now): the round
        # wrote counter state the switch-off had already cleared, and part of
        # it was sampled while the owner had it off.
        activity.reset()
        return
    if result is None:
        return
    _activity_seq += 1
    _pending_activity = result


async def _activity_loop() -> None:
    """Sample on every 5-minute wall-clock boundary, out of band from the heartbeat.

    Nothing here touches the heartbeat counters or /api/health: a failed round
    is a missing window on the Activity page, never a worker going unhealthy.
    """
    with contextlib.suppress(Exception):
        if await asyncio.to_thread(orchestrator.docker_available):
            await asyncio.to_thread(_sweep_probes)
    while True:
        await asyncio.sleep(_seconds_to_next_window())
        try:
            await _activity_cycle()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.warning("Activity round failed")


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
    global _heartbeat_task, _fence_task, _activity_task, _guard_task, _started_at

    _started_at = time.monotonic()
    logger.info("CashPilot Worker '%s' starting", WORKER_NAME)
    docker_mode = "direct" if await asyncio.to_thread(orchestrator.docker_available) else "monitor-only"
    logger.info(
        "Docker: %s (%s)", docker_mode, "through the socket proxy" if orchestrator.proxied() else "direct socket"
    )
    if fix := orchestrator.proxy_policy_fix():
        logger.warning("Docker socket proxy: %s", orchestrator.proxy_policy_fix_text(fix))

    # The fence goes in before anything else, so the gap after a reboot in
    # which earners run without it is as short as this worker can make it.
    # Without the fence they have no internet unless the host or an upstream
    # router masquerades their subnet, and they can still reach the host itself
    # (docs/isolation.md). The public IP is looked up first (bounded by
    # _EGRESS_TOTAL_TIMEOUT), so the first table drops it unless that lookup fails.
    if docker_mode == "direct":
        # First of all: Docker starts a direct earner again after a reboot, and on
        # a CASHPILOT_PROXIED_ONLY worker each second it runs is traffic from this
        # box's own IP (app/route_gate.py).
        await _hold_direct_earners()
        lan_fence.set_egress_ip(await _detect_egress_ip())
    await _check_fence(startup=True)
    _fence_task = asyncio.create_task(_fence_loop())
    if docker_mode == "direct":
        # Right after the fence: a fence-gated node (Mysterium) has no restart
        # policy, so after a reboot this is what starts it, and only now.
        await _guard_once()
        _guard_task = asyncio.create_task(_guard_loop())
    else:
        if route_gate.proxied_only():
            # Docker can come up after this worker, and start the direct earners
            # again: on a proxied-only worker they are held all the same.
            await _hold_direct_earners()
        # Docker answers later (the socket proxy lost the start race after a
        # reboot, or was recreated): the steps above and below run then.
        _guard_task = asyncio.create_task(_wait_for_docker_loop())
    if docker_mode == "direct":
        await _resume_proxied_work()

    miner_task = None
    if MINER_TARGETS or MINER_ERRORS:
        for error in MINER_ERRORS:
            logger.warning("CASHPILOT_MINERS rejected an entry (%s)", error)
        miner_task = asyncio.create_task(_miner_loop())

    if UI_URL:
        _heartbeat_task = asyncio.create_task(_heartbeat_loop())
        _activity_task = asyncio.create_task(_activity_loop())
        logger.info("Heartbeat enabled -> %s (every %ds)", _redact_userinfo(UI_URL), HEARTBEAT_INTERVAL)
        if not API_KEY:
            logger.warning("CASHPILOT_API_KEY not set — heartbeats sent without auth")
    else:
        logger.warning("No CASHPILOT_UI_URL — running without UI connection")

    yield

    for task in (_heartbeat_task, _fence_task, _activity_task, _guard_task, miner_task):
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    logger.info("CashPilot Worker stopped")


app = FastAPI(title="CashPilot Worker", version=version.current(), lifespan=lifespan)


_SECRET_BODY_PATHS = ("/api/proxied/", "/api/proxy-test")


def _secret_body(path: str) -> bool:
    """Whether a 422 on ``path`` must not echo its input: a proxy secret, or a deploy's env and wallet seed."""
    return path.startswith(_SECRET_BODY_PATHS) or (path.startswith("/api/containers/") and path.endswith("/deploy"))


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's 422 echoes the rejected input. On the proxy routes that input
    can be a proxy password or a Tailscale auth key, so it is dropped there;
    every other route keeps the default body."""
    errors = exc.errors()
    if _secret_body(request.url.path):
        errors = [{k: v for k, v in err.items() if k not in ("input", "ctx")} for err in errors]
    return JSONResponse(status_code=422, content={"detail": jsonable_errors(errors)})


def jsonable_errors(errors: Any) -> Any:
    from fastapi.encoders import jsonable_encoder

    return jsonable_encoder(errors)


# ---------------------------------------------------------------------------
# Mini-UI (status page)
# ---------------------------------------------------------------------------


def _docker_access_text() -> str:
    if not orchestrator.proxied():
        return "direct socket (root on this host)"
    if fix := orchestrator.proxy_policy_fix():
        return f"socket proxy: {orchestrator.proxy_policy_fix_text(fix)}"
    return "socket proxy"


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
            <div><label>Docker access</label><span>{_esc(_docker_access_text())}</span></div>
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
    cpu_shares is a *relative* weight (Docker's default is 1024) that only
    takes effect while the host is contended, so it protects a latency-
    sensitive earner from noisy neighbours without capping it on an idle box.
    """

    mem_limit: str | None = None
    mem_reservation: str | None = None
    oom_score_adj: int | None = None
    cpu_shares: int | None = None


class WalletSeedSpec(BaseModel):
    """What a deploy asks of a seed-file wallet (app/wallet_seed.py).

    generate: make one when the node has none; import: write ``phrase`` when the
    node has none; migrate: as import, for a phrase CashPilot recorded before
    the file existed, and a file that holds another one wins; keep: the node
    must have one already.
    """

    mode: Literal["generate", "import", "migrate", "keep"]
    phrase: str | None = None


class DeploySpec(BaseModel):
    image: str
    env: dict[str, str] = {}
    # A host port, or (host address, host port) for a bind to one interface, or
    # several of those pairs for one container port published on several
    # addresses (Mysterium's WebUI on each UI_ADDRESS). Docker reads a list as
    # several bindings, so each pair must be a tuple.
    ports: dict[str, int | tuple[str, int] | list[tuple[str, int]]] = {}
    volumes: dict[str, dict[str, str]] = {}
    # Mount targets the operator relocated on purpose this deploy. Every other
    # mount of a container being replaced is kept where it is.
    moved_mounts: list[str] = []
    network_mode: str | None = None
    cap_add: list[str] | None = None
    devices: list[str] | None = None
    privileged: bool = False
    command: str | None = None
    hostname: str | None = None
    labels: dict[str, str] = {}
    resources: ResourceSpec | None = None
    # Advanced and unsupported. Absent means Docker's default runtime, which is
    # what everything uses and what everything is tested against.
    runtime: str | None = None
    # Which copy of the service this is; see constants.LABEL_INSTANCE.
    instance: int = 1
    # The UI's signed note that the owner re-entered their password for this
    # exact spec on this service (app/step_up.py). Needed only to run a service
    # with critical volumes other than as the catalog says.
    approval: str | None = None
    # The UI's signed note that the owner confirmed, with their password, running
    # a service routed through a proxy on this worker from the worker's own IP
    # instead (app/route_gate.py, step_up.ACTION_LEAVE_ROUTE).
    route_approval: str | None = None
    # A service that keeps its wallet seed in a file (catalog seed_file): the
    # wallet this deploy wants. The phrase rides only here, never in env, and
    # this worker writes it into the node's own volume (app/wallet_seed.py).
    wallet_seed: WalletSeedSpec | None = None


class CheckedDeploySpec(DeploySpec):
    expected_container: str = "none"
    # Older Desktop sends this alone. It changes the wording of a refusal, never the target.
    replace_existing: StrictBool = False


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
        refusal = _allowlist_refusal(entry)
        if refusal:
            logger.warning("Refusing CASHPILOT_ALLOWED_VOLUME_ROOTS entry %r: %s", entry, refusal)
            continue
        allowed.add(os.path.realpath(entry))
    return frozenset(allowed)


def _allowlist_refusal(entry: str) -> str | None:
    """Why an absolute path can never be opted in through CASHPILOT_ALLOWED_VOLUME_ROOTS, or None.

    The two gates of _parse_allowed_volume_roots, also used to decide whether a
    blocked volume's refusal may tell the operator to allowlist it: advice that
    the parser would refuse only sends them round in a circle.
    """
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
        return f"{real} is a system path and can never be opted in"
    if real == "/" or real in _BLOCKED_VOLUME_ROOTS:
        return "that is a whole root, not a service directory"
    for blocked in _BLOCKED_VOLUME_ROOTS:
        if blocked != "/" and real.startswith(blocked + "/"):
            if real[len(blocked) + 1 :].count("/") < _MIN_DEPTH_BELOW_ROOT - 1:
                return (
                    "name a specific service directory (e.g. /mnt/user/storj), not a whole root like /mnt or /mnt/user"
                )
            break
    return None


# The socket proxy's bind folders count too, so one setting opens a folder for
# both; each entry still has to clear the gates above.
_ALLOWED_VOLUME_ROOTS = _parse_allowed_volume_roots(
    os.getenv("CASHPILOT_ALLOWED_VOLUME_ROOTS", "")
    + ":"
    + os.getenv("CASHPILOT_PROXY_BIND_MOUNTS", "").replace(",", ":")
)

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


def _catalog_volume_targets(slug: str | None) -> set[str]:
    """Container paths the catalog mounts for a slug — the only ones a redeploy keeps.

    ``deploy_raw`` keeps a replaced container's mount without re-checking its
    source against the bind-path rules, so which targets qualify must not be the
    caller's choice. An unknown slug or a missing catalog keeps nothing.
    """
    if not _catalog_get_services or not slug:
        return set()
    for svc in _catalog_get_services():
        if svc.get("slug") != slug:
            continue
        targets: set[str] = set()
        for mapping in (svc.get("docker") or {}).get("volumes") or []:
            parts = str(mapping).split(":")
            if len(parts) >= 2:
                targets.add(parts[1])
        return targets
    return set()


def _catalog_host_network_slugs() -> set[str]:
    """Slugs whose catalog definition legitimately declares network_mode: host."""
    if not _catalog_get_services:
        return set()
    return {svc["slug"] for svc in _catalog_get_services() if (svc.get("docker") or {}).get("network_mode") == "host"}


# Named volumes (bridge/none/unset) are always allowed. `host` is allowed only for
# catalog services that declare it (checked separately below, by slug). `container:<id>`
# (namespace join) and any other value are rejected outright.
_ALLOWED_NETWORK_MODES = {None, "", "bridge", "none", "host"}


def _validate_runtime(runtime: str | None) -> None:
    """Allow only a runtime this daemon actually reports.

    Deliberately NOT a hardcoded list. A runtime CashPilot recognises but the
    host has not installed would fail at container-create time with a Docker
    error the user cannot act on; asking the daemon means the only runtimes
    accepted are ones that exist here.

    Nothing selects a non-default runtime on its own. See
    docs/home-network-security.md for when gVisor is worth it: measured, it costs
    about a fifth of peak throughput and six to nine times the CPU per byte, it
    turns off raw sockets unless registered with --net-raw, it gains little for
    host-networked services, it cannot run on stock Unraid, and it does not
    address the risks that actually occur in this category.
    """
    if not runtime:
        return
    available = orchestrator.available_runtimes()
    if available is None:
        # An unreachable daemon is an OUTAGE, not a caller mistake: answering
        # 400 here told the operator their runtime choice was wrong when the
        # actual fix was the daemon. The deploy would fail against the dead
        # daemon anyway — refuse honestly first.
        raise HTTPException(
            status_code=503,
            detail=f"Cannot verify the {runtime!r} runtime — the Docker daemon is not answering.",
        )
    if runtime not in available:
        raise HTTPException(
            status_code=400,
            detail=(
                f"This host's Docker daemon does not provide a {runtime!r} runtime. "
                f"Available: {sorted(available) or 'none reported'}."
            ),
        )


def _validate_instance(instance: int) -> None:
    if not 1 <= instance <= MAX_INSTANCES:
        raise HTTPException(status_code=400, detail=f"instance must be between 1 and {MAX_INSTANCES}")


#: The most container ports one deploy may publish: a 1000-port UDP range plus
#: a handful of TCP ones. The catalog now caps a range at 300
#: (catalog.MAX_UDP_PORTS), but a UI older than that may still send 1,000, and
#: the worker waits out the slow start such a range brings (orchestrator._await_start).
MAX_PUBLISHED_PORTS = 1024


def _catalog_service(slug: str | None) -> dict[str, Any] | None:
    if not _catalog_get_services or not slug:
        return None
    return next((svc for svc in _catalog_get_services() if svc.get("slug") == slug), None)


def _validate_fence_gated(spec: DeploySpec, slug: str | None) -> None:
    """A fence-gated service runs exactly as this worker's own catalog says.

    Decided here from the worker's catalog, never from the request: the image
    must be the pinned one and the network a bridge, so a caller cannot put a
    NET_ADMIN service back on the host network or swap its image.
    """
    docker_conf = (_catalog_service(slug) or {}).get("docker") or {}
    if docker_conf.get("fence_gated") is not True:
        return
    pinned = {docker_conf.get("image")} | set((docker_conf.get("image_by_arch") or {}).values())
    if spec.image not in pinned - {None, ""}:
        raise HTTPException(status_code=403, detail=f"'{slug}' runs only the image this worker's catalog pins")
    if (spec.network_mode or "bridge") not in ("bridge", "default"):
        raise HTTPException(status_code=403, detail=f"'{slug}' runs only on the fenced bridge")


def _validate_critical_spec(spec: DeploySpec, slug: str) -> None:
    """A service that keeps a wallet or identity runs as the catalog says, or as the owner confirmed.

    Decided from this worker's catalog: the service's YAML marks the volumes
    (``critical_volumes``), and the image, the command, the env keys and the
    mount targets must be the ones its YAML names
    (orchestrator.critical_spec_deviations). Anything else needs the UI's signed
    approval, which the UI gives only after the owner re-entered their password
    and which is bound to this exact spec (step_up.deploy_target); a stolen
    session or the admin API key cannot get one. Without this, an image or a
    command of anyone's choosing would start on the wallet volume and could copy
    or replace the wallet.
    """
    if slug not in orchestrator.critical_slugs():
        return
    found = orchestrator.critical_spec_deviations(slug, spec.image, spec.command, spec.env, spec.volumes)
    if not found:
        return
    if not spec.approval:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "step_up_required",
                "message": f"{slug} keeps a wallet or node identity, and this deploy differs from the catalog: "
                f"{'; '.join(found)}. That needs the owner's password. Nothing was deployed.",
            },
        )
    target = step_up.deploy_target(slug, spec.image, spec.command, spec.env, spec.volumes)
    try:
        step_up.check(_worker_key, spec.approval, step_up.ACTION_CUSTOM_IMAGE, target)
    except step_up.StepUpError as exc:
        raise HTTPException(
            status_code=403, detail={"error": "step_up_rejected", "message": f"{exc}. Nothing was deployed."}
        ) from None


def _validate_route_approval(spec: DeploySpec, slug: str) -> bool:
    """Whether this deploy carries the owner's checked approval to leave a route.

    Only the UI holds this worker's key, and it signs the approval only after
    the owner re-entered their password (step_up.ACTION_LEAVE_ROUTE). Without
    one, route_gate.check refuses a routed service from the box's own IP.
    """
    if not spec.route_approval:
        return False
    try:
        step_up.check(_worker_key, spec.route_approval, step_up.ACTION_LEAVE_ROUTE, slug)
    except step_up.StepUpError as exc:
        raise HTTPException(
            status_code=403, detail={"error": "step_up_rejected", "message": f"{exc}. Nothing was deployed."}
        ) from None
    return True


def _validate_gpu(slug: str | None, spec: DeploySpec) -> None:
    """A GPU grant (app/gpu.py) refused before the running container is touched.

    The grant comes from this worker's catalog. It is refused here when the
    socket proxy runs an older policy, which refuses the GPU, or when sysfs
    says for sure that this machine has no GPU of that vendor.
    """
    try:
        grant = orchestrator.gpu_grant_for_deploy(slug, spec.image, spec.instance)
    except orchestrator.ContainerRuntimeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    if not grant:
        return
    name = orchestrator.service_name(slug or "")
    if orchestrator.proxy_policy_current() is False and (fix := orchestrator.proxy_policy_fix()):
        raise HTTPException(
            status_code=409,
            detail=f"{name} needs this machine's GPU, and the Docker socket proxy would refuse it: "
            f"{orchestrator.proxy_policy_fix_text(fix)} Nothing was deployed.",
        )
    if problem := gpu.missing(grant, gpu.host_gpus()):
        raise HTTPException(status_code=409, detail=f"{problem} Nothing was deployed.")


def _validate_deploy_spec(spec: DeploySpec, slug: str | None = None) -> None:
    _validate_runtime(spec.runtime)
    if blocked_env := sorted(k for k in spec.env if str(k).upper().startswith(gpu.ENV_PREFIX)):
        # The void stamp and the GPU grant are this worker's (app/gpu.py): a
        # request that set NVIDIA_VISIBLE_DEVICES could undo the stamp.
        raise HTTPException(
            status_code=403,
            detail=f"CashPilot sets the {gpu.ENV_PREFIX} variables itself; refused: {', '.join(blocked_env)}",
        )
    _validate_instance(spec.instance)
    if len(spec.ports) > MAX_PUBLISHED_PORTS:
        raise HTTPException(status_code=400, detail=f"At most {MAX_PUBLISHED_PORTS} ports can be published")
    if spec.instance > 1 and (spec.volumes or spec.ports):
        # Two copies would share the same host directories and fight over the
        # same host ports. The UI refuses this first; this is the backstop.
        raise HTTPException(
            status_code=400, detail="Only services without volumes or published ports can run more than once"
        )
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
    _validate_fence_gated(spec, slug)
    _validate_gpu(slug, spec)
    proxy_roots = orchestrator._proxy_bind_roots() if orchestrator.proxied() else None
    compose_dir = os.getenv(orchestrator.COMPOSE_DIR_ENV, "").strip()
    compose_dir = orchestrator.host_path_key(compose_dir) if compose_dir.startswith("/") else ""
    for source in spec.volumes:
        if source in orchestrator.PROXY_VOLUMES:
            # The volume holds the worker's own Docker socket; a container
            # given it could drive Docker exactly as the worker does.
            raise HTTPException(status_code=403, detail=f"Volume '{source}' is the worker's Docker socket")
        if not source.startswith("/"):
            continue  # named volume (e.g. "mysterium-data") — always allowed
        # host_path_key, not normpath: normpath keeps "//" and would let
        # "//compose/dir" past a comparison with "/compose/dir".
        src = orchestrator.host_path_key(source)
        if compose_dir and (
            src == compose_dir or src.startswith(compose_dir + "/") or compose_dir.startswith(src.rstrip("/") + "/")
        ):
            # The proxy opens the compose folder for the in-app update only. A
            # deploy that binds it, a folder under it or a folder above it could
            # rewrite the compose file, read the .env beside it, or plant a
            # symlink there that a second bind follows to the host's root
            # (docs/security-defaults.md).
            raise HTTPException(
                status_code=403,
                detail=f"Volume '{source}' reaches the compose folder ({orchestrator.COMPOSE_DIR_ENV}); "
                "no service may bind it",
            )
        if proxy_roots is not None and not any(
            os.path.normpath(source) == root or os.path.normpath(source).startswith(root.rstrip("/") + "/")
            for root in proxy_roots
        ):
            # Refused here, before the running container is removed, rather
            # than by the proxy halfway through the replacement.
            raise HTTPException(
                status_code=403,
                detail=(
                    f"The Docker socket proxy does not let containers bind {source}. To allow it, add "
                    f"the folder to {orchestrator.BIND_MOUNTS_ENV} in the .env next to your compose "
                    "file (comma-separated), then run docker compose up -d"
                ),
            )
        real = os.path.realpath(source)
        if any(real == root or real.startswith(root + "/") for root in _ALLOWED_VOLUME_ROOTS):
            continue  # explicitly opted in by the operator (see _parse_allowed_volume_roots)
        for blocked in _BLOCKED_VOLUME_ROOTS:
            if real == blocked or real.startswith(blocked + "/"):
                detail = f"Volume mount '{source}' is blocked"
                if not _allowlist_refusal(source):
                    detail += (
                        ". To allow it, add the path to CASHPILOT_ALLOWED_VOLUME_ROOTS on this worker and restart it"
                    )
                raise HTTPException(status_code=403, detail=detail)
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
    # 2..262144 is the kernel's cpu.shares range (MIN_SHARES..MAX_SHARES);
    # Docker documents no bound of its own, and daemons vary at the edges
    # (0 means "use the default", modern ones clamp out-of-range values rather
    # than erroring). The guard rejects everything outside the kernel range —
    # including 0, where OMITTING the key is the honest spelling of "default" —
    # because a 400 is actionable where a silently clamped weight is not.
    if resources.cpu_shares is not None and not (2 <= resources.cpu_shares <= 262144):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid cpu_shares '{resources.cpu_shares}': must be between 2 and 262144 (Docker's default is 1024)",
        )


class ProxySpec(BaseModel):
    """The proxy a copy leaves through. Secrets are SecretStr so a repr or a
    log line can never print them."""

    kind: str
    host: str = ""
    port: int = 0
    username: SecretStr | None = None
    password: SecretStr | None = None
    auth_key: SecretStr | None = None
    exit_node: str = ""
    login_server: str = ""

    def plain(self) -> dict[str, Any]:
        def reveal(value: SecretStr | None) -> str:
            return value.get_secret_value() if value is not None else ""

        return {
            "kind": self.kind,
            "host": self.host,
            "port": self.port,
            "username": reveal(self.username),
            "password": reveal(self.password),
            "auth_key": reveal(self.auth_key),
            "exit_node": self.exit_node,
            "login_server": self.login_server,
        }


class ProxiedDeploySpec(BaseModel):
    expected_container: str = "none"
    earner: DeploySpec
    proxy: ProxySpec
    # The service itself, routed at deploy, not a copy beside a direct one:
    # recorded on this worker so it is never started from the box's own IP
    # without the owner's password (app/route_gate.py).
    routed: bool = False
    # Replace the copy only while it runs and the owner has not stopped it:
    # a rebuild the UI makes on its own (a device rename) must never start it.
    only_if_running: bool = False


class ProxyTestSpec(BaseModel):
    proxy: ProxySpec


class ProxiedStartSpec(BaseModel):
    """The proxy as the UI stores it now, so a start applies an edit."""

    proxy: ProxySpec


_EXIT_NODE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,253}$")
# The same rule as app/proxies.py (the UI image has it, this one does not):
# no user name or password, query or fragment in a login server.
_LOGIN_SERVER_RE = re.compile(r"^https://[A-Za-z0-9.-]{1,253}(:[0-9]{1,5})?(/[A-Za-z0-9._~/-]*)?$")


def _validate_proxy(proxy: ProxySpec) -> None:
    if proxy.kind not in proxy_tunnel.PROXY_KINDS:
        raise HTTPException(status_code=400, detail=f"Unknown proxy type {proxy.kind!r}")
    if proxy.kind == "tailscale":
        if not proxy.auth_key or not _EXIT_NODE_RE.match(proxy.exit_node or ""):
            raise HTTPException(
                status_code=400, detail="A Tailscale proxy needs an auth key and the exit node's 100.x address"
            )
        if proxy.login_server and not _LOGIN_SERVER_RE.match(proxy.login_server):
            raise HTTPException(status_code=400, detail="The Tailscale login server must be an https:// URL")
        return
    if not re.match(r"^[A-Za-z0-9.-]{1,253}$", proxy.host or "") or not 1 <= proxy.port <= 65535:
        raise HTTPException(status_code=400, detail="A proxy needs a host name or IPv4 address and a port")


def _validate_proxied(slug: str, spec: ProxiedDeploySpec) -> None:
    """A proxied copy uses the earner checks plus three of its own."""
    if spec.earner.ports or spec.earner.volumes or spec.earner.network_mode:
        raise HTTPException(
            status_code=400,
            detail="A proxied copy cannot publish ports, mount volumes or choose its network: it lives inside its tunnel",
        )
    if spec.earner.instance != 1:
        raise HTTPException(status_code=400, detail="A proxied copy has no instance number")
    # The earner shares the tunnel's network namespace, so anything that could
    # rewrite or bypass the tunnel's firewall is refused whatever the catalog says.
    caps = {str(c).upper().removeprefix("CAP_") for c in spec.earner.cap_add or []}
    if risky := sorted(caps & PROXIED_FORBIDDEN_CAPS):
        raise HTTPException(
            status_code=400,
            detail=f"A proxied copy cannot hold {', '.join(risky)}: it could change or bypass its tunnel's firewall",
        )
    if spec.earner.devices:
        raise HTTPException(status_code=400, detail="A proxied copy gets no host devices")
    if gpu.grant(slug):
        raise HTTPException(status_code=400, detail="A proxied copy gets no GPU")
    _validate_deploy_spec(spec.earner, slug)
    _validate_proxy(spec.proxy)


async def _own_egress_ip() -> str | None:
    try:
        return await _detect_egress_ip()
    except Exception:  # noqa: BLE001 - unknown just skips the comparison
        return None


def _deploy_target_error(exc: orchestrator.DeployTargetChanged) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"error": "deploy_target_changed", "message": str(exc), "current_container": exc.actual},
    )


def _proxy_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, orchestrator.DeployTargetChanged):
        return _deploy_target_error(exc)
    if isinstance(exc, proxy_tunnel.ProxyTunnelError):
        return HTTPException(status_code=exc.status_code, detail=str(exc))
    if isinstance(exc, orchestrator.ContainerNetworkError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, orchestrator.ContainerRuntimeError):
        return HTTPException(status_code=exc.status_code, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, APIError):
        refusal = orchestrator.proxy_refusal(exc)
        if refusal:
            return HTTPException(status_code=403, detail=refusal)
        reason = " ".join(proxy_tunnel.redact(str(exc.explanation or exc)).split())[:300]
        return HTTPException(status_code=409, detail=f"Docker refused the container: {reason}")
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=503, detail=proxy_tunnel.redact(str(exc)))
    logger.error("Proxied copy operation failed: %s", proxy_tunnel.redact(f"{type(exc).__name__}: {exc}"))
    return HTTPException(status_code=500, detail="The proxied copy operation failed")


def _deploy_routed(
    slug: str,
    proxy_id: int,
    earner: dict[str, Any],
    proxy: dict[str, Any],
    own_ip: str | None,
    only_if_running: bool = False,
    deadline: float | None = None,
    expected_container: str = "none",
) -> dict[str, Any]:
    """Deploy the routed copy of ``slug``, holding route_gate.deploying from its mark to its end.

    A direct deploy of the same service waits for it, and it for a direct
    deploy, so neither can create its earner after the other checked; and
    the route put back after a failure is the one this deploy found.

    ``deadline`` is the request's (api_proxied_deploy): past it, the route is
    not moved and no earner is created (proxy_tunnel.deploy).
    """
    if deadline is None:
        deadline = time.monotonic() + DEPLOY_DEADLINE_SECONDS
    with route_gate.deploying(slug):
        # The wait for the lock has no bound of its own.
        try:
            orchestrator._refuse_past(deadline, str(earner.get("image") or slug))
        except orchestrator.ContainerRuntimeError as exc:
            raise _proxy_http_error(exc) from None
        # A routed copy through another proxy stays when this one is made
        # (proxy_tunnel._deploy replaces only its own proxy's), and the mark
        # moved here would hide it from the next switch to direct. Every copy
        # deploy and start of this service holds the same lock from its mark
        # read to its earner, so this list is complete.
        try:
            elsewhere = [
                name
                for pid, name in proxy_tunnel.routed_copies(slug, route_gate.routed().get(slug))
                if pid != int(proxy_id)
            ]
        except Exception as exc:  # noqa: BLE001 - not knowing is not "none"
            raise HTTPException(
                status_code=503,
                detail=f"Could not list the proxied copies of {slug} on this worker ({exc}); nothing changed",
            ) from None
        if elsewhere:
            raise HTTPException(
                status_code=409,
                detail=f"{slug} already runs through another proxy on this worker ({', '.join(elsewhere)}). "
                "Remove it first, then deploy it through this one; nothing changed",
            )
        # Recorded before the earner exists, so no deploy path can start this
        # service from the box's own IP while the routed one is being made.
        try:
            before = route_gate.mark(slug, proxy_id)
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Could not record the route of {slug} on this worker ({exc}); nothing changed",
            ) from None
        # The routed copy beside a direct container of the same account would
        # show the provider one device on both the box's IP and the proxy's.
        try:
            direct = [c.name for c in orchestrator.service_instances(slug)]
        except Exception as exc:  # noqa: BLE001 - not knowing is not "none"
            route_gate.release(slug, before)
            raise HTTPException(
                status_code=503,
                detail=f"Could not list the containers of {slug} on this worker ({exc}); nothing changed",
            ) from None
        if direct:
            route_gate.release(slug, before)
            raise HTTPException(
                status_code=409,
                detail=f"{slug} already runs from this worker's own IP ({', '.join(direct)}). Remove it first, "
                "then deploy it with a route; nothing changed",
            )
        try:
            # In a tunnel of its own: the mark now names this proxy (proxy_tunnel.deploy).
            return proxy_tunnel.deploy(
                slug,
                proxy_id,
                earner,
                proxy,
                own_ip,
                only_if_running=only_if_running,
                deadline=deadline,
                expected_container=expected_container,
            )
        except Exception as exc:  # noqa: BLE001 - mapped to a status below
            error = _proxy_http_error(exc)
            if isinstance(exc, orchestrator.DeployTargetChanged):
                route_gate.release(slug, before)
                raise error from None
            # A deploy can fail after its earner exists (a start whose answer
            # was lost, a cleanup that failed too). Released then, the route
            # would let a direct deploy run the same account from this box's
            # own IP beside it without the owner's password. The previous
            # route goes back otherwise: no copy was made while the mark named
            # this proxy, since every copy waits for this lock.
            try:
                left = [name for pid, name in proxy_tunnel.routed_copies(slug, proxy_id) if pid == int(proxy_id)]
            except Exception as look:  # noqa: BLE001 - not knowing is not "none"
                left = [f"unknown ({proxy_tunnel.redact(str(look))[:120]})"]
            if not left:
                route_gate.release(slug, before)
            else:
                # A code the UI reads, as after a timeout: it keeps the copy and
                # the routed deployment records, so the earner stays capped and listed.
                error.detail = {
                    "error": "routed_copy_may_exist",
                    "message": f"{error.detail}. {slug} stays routed through proxy {proxy_id} on this worker, "
                    f"because its routed copy may still exist: {', '.join(left)}",
                }
            raise error from None


#: How many deploys of each copy, by (slug, proxy id), this worker is running,
#: counted from the request's arrival to its answer. The UI stops waiting after
#: 180 s and lets a removal of the copy through, but the deploy goes on here (a
#: routed one may still be waiting on route_gate.deploying); a removal that ran
#: first would leave the earner it makes running with no record in the UI.
_copy_deploys: dict[tuple[str, int], int] = {}
#: How many deploys of each copy ever started here. A removal compares it before
#: and after, so a deploy that started and ended inside it is not missed.
_copy_starts: dict[tuple[str, int], int] = {}
#: How many removals of each copy, by (slug, proxy id), are running here. A
#: deploy of that copy is refused meanwhile: it would wait on the proxy's lock
#: and make its earner after the removal answered, and the UI then drops the
#: copy's record, leaving that earner running with none.
_copy_removals: dict[tuple[str, int], int] = {}


@app.post("/api/proxied/{slug}/{proxy_id}/deploy")
async def api_proxied_deploy(request: Request, slug: str, proxy_id: int, spec: ProxiedDeploySpec) -> dict[str, Any]:
    """Run a copy of ``slug`` whose only way out is the given proxy (docs/proxies.md)."""
    _verify_api_key(request)
    # Counted from now, as a direct deploy's is (api_deploy_container): the UI
    # holds the ids of a copy deploy it got no answer for, and the hold must
    # outlast it, however long this one waits for locks or a tunnel pull.
    deadline = time.monotonic() + DEPLOY_DEADLINE_SECONDS
    key = (slug, int(proxy_id))
    if _copy_removals.get(key):
        raise HTTPException(
            status_code=409,
            detail=f"A removal of {slug} through proxy {proxy_id} is running on this worker; "
            "deploy it again once it ends",
        )
    _copy_deploys[key] = _copy_deploys.get(key, 0) + 1
    _copy_starts[key] = _copy_starts.get(key, 0) + 1
    try:
        return await _proxied_deploy(slug, proxy_id, spec, deadline)
    finally:
        _copy_deploys[key] -= 1
        if not _copy_deploys[key]:
            del _copy_deploys[key]


async def _proxied_deploy(slug: str, proxy_id: int, spec: ProxiedDeploySpec, deadline: float) -> dict[str, Any]:
    await asyncio.to_thread(_validate_proxied, slug, spec)
    own_ip = await _own_egress_ip()
    earner = {
        "image": spec.earner.image,
        "env": spec.earner.env,
        "cap_add": spec.earner.cap_add,
        "devices": spec.earner.devices,
        "command": spec.earner.command,
        "labels": spec.earner.labels,
        "resources": spec.earner.resources,
    }
    if not spec.routed:
        try:
            result = await asyncio.to_thread(
                proxy_tunnel.deploy,
                slug,
                proxy_id,
                earner,
                spec.proxy.plain(),
                own_ip,
                only_if_running=spec.only_if_running,
                deadline=deadline,
                expected_container=spec.expected_container,
            )
        except Exception as exc:  # noqa: BLE001 - mapped to a status below
            raise _proxy_http_error(exc) from None
    else:
        result = await asyncio.to_thread(
            _deploy_routed,
            slug,
            proxy_id,
            earner,
            spec.proxy.plain(),
            own_ip,
            spec.only_if_running,
            deadline,
            spec.expected_container,
        )
    return {"status": "deployed", **result}


@app.post("/api/proxied/{slug}/{proxy_id}/stop")
async def api_proxied_stop(request: Request, slug: str, proxy_id: int) -> dict[str, Any]:
    _verify_api_key(request)
    try:
        result = await asyncio.to_thread(proxy_tunnel.stop, slug, proxy_id)
    except Exception as exc:  # noqa: BLE001
        raise _proxy_http_error(exc) from None
    return {"status": "stopped", **result}


@app.post("/api/proxied/{slug}/{proxy_id}/start")
async def api_proxied_start(
    request: Request, slug: str, proxy_id: int, spec: ProxiedStartSpec | None = None
) -> dict[str, Any]:
    """Start a proxied copy. With a body, the tunnel's settings are rewritten
    from it first; a UI older than this worker sends none."""
    _verify_api_key(request)
    proxy: dict[str, Any] | None = None
    own_ip: str | None = None
    if spec is not None:
        await asyncio.to_thread(_validate_proxy, spec.proxy)
        proxy = spec.proxy.plain()
        own_ip = await _own_egress_ip()
    try:
        result = await asyncio.to_thread(proxy_tunnel.start, slug, proxy_id, proxy, own_ip)
    except Exception as exc:  # noqa: BLE001
        raise _proxy_http_error(exc) from None
    return {"status": "started", **result}


@app.post("/api/proxied/{slug}/{proxy_id}/restart")
async def api_proxied_restart(request: Request, slug: str, proxy_id: int) -> dict[str, Any]:
    """Restart a running proxied copy where it is, for a health signal a restart clears.

    Never a stop and a start, and never a copy its owner or the cap stopped
    (proxy_tunnel.restart).
    """
    _verify_api_key(request)
    try:
        result = await asyncio.to_thread(proxy_tunnel.restart, slug, proxy_id)
    except Exception as exc:  # noqa: BLE001
        raise _proxy_http_error(exc) from None
    return {"status": "restarted", **result}


@app.get("/api/proxied/{slug}/{proxy_id}/logs")
async def api_proxied_logs(
    request: Request, slug: str, proxy_id: int, lines: int = 50, match: str = "", since_hours: float = 0
) -> dict[str, Any]:
    """The log tail of a proxied copy's earner, as /api/containers/{slug}/logs gives a service's.

    With ``match`` and ``since_hours``, the matching lines of that window, and
    ``filtered`` to say so, as there.
    """
    _verify_api_key(request)
    compiled = _log_filter(match, since_hours)
    lines = max(1, min(lines, 1000))
    try:
        if compiled is not None:
            logs = await asyncio.to_thread(
                proxy_tunnel.grep_logs, slug, proxy_id, compiled, since_hours=min(since_hours, 24), lines=lines
            )
            return {"logs": logs, "filtered": True}
        logs = await asyncio.to_thread(proxy_tunnel.logs, slug, proxy_id, lines)
    except Exception as exc:  # noqa: BLE001
        raise _proxy_http_error(exc) from None
    return {"logs": logs}


@app.delete("/api/proxied/{slug}/{proxy_id}")
async def api_proxied_remove(request: Request, slug: str, proxy_id: int) -> dict[str, Any]:
    _verify_api_key(request)
    key = (slug, int(proxy_id))
    if _copy_deploys.get(key):
        # 503 keeps the removal pending in the UI, which asks again with each
        # heartbeat (main._resume_copy_removals) and then removes what it made.
        raise HTTPException(
            status_code=503,
            detail=f"A deploy of {slug} through proxy {proxy_id} is still running on this worker; "
            "the removal waits for it",
        )
    # Marked in the same step as the check, with no await between: from here
    # until the removal ends, a deploy of this copy is refused.
    _copy_removals[key] = _copy_removals.get(key, 0) + 1
    try:
        removed = await asyncio.to_thread(proxy_tunnel.remove, slug, proxy_id)
    except Exception as exc:  # noqa: BLE001
        raise _proxy_http_error(exc) from None
    finally:
        _copy_removals[key] -= 1
        if not _copy_removals[key]:
            del _copy_removals[key]
    return {"status": "removed", "containers": removed}


@app.post("/api/proxy-test")
async def api_proxy_test(request: Request, spec: ProxyTestSpec) -> dict[str, Any]:
    """Start a throwaway tunnel through the proxy and report the exit IP it gets.

    Passes only when the exit IP is public and is not this worker's own.
    """
    _verify_api_key(request)
    await asyncio.to_thread(_validate_proxy, spec.proxy)
    own_ip = await _own_egress_ip()
    try:
        result = await asyncio.to_thread(proxy_tunnel.test, spec.proxy.plain(), own_ip)
    except Exception as exc:  # noqa: BLE001
        raise _proxy_http_error(exc) from None
    if not egress.public_ip(result.get("ip")):
        raise HTTPException(status_code=409, detail="The tunnel came up, but its exit address is not a public IP")
    return {"exit_ip": result["ip"], "country": result.get("country") or "", "ms": result.get("ms")}


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
        # Read now, not from the last heartbeat: the UI asks before it removes
        # a routed copy to run the service from this box's own IP.
        "proxied_only": route_gate.proxied_only(),
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


def _refuse_beside_routed_copy(slug: str) -> None:
    """Refuse leaving the route while the routed copy of ``slug`` still exists.

    The UI removes that copy before it sends the direct deploy, but a routed
    redeploy that ran in between puts it back; deployed direct beside it, the
    same account would run from the box's own IP and from the proxy's.
    """
    try:
        proxy_id = route_gate.routed().get(slug)
        copy = proxy_tunnel.copy_name(slug, proxy_id) if proxy_id is not None else None
        # Through any proxy, not only the marked one: a routed copy through an
        # earlier proxy keeps running when the mark moves to a later one.
        found = [(proxy_id, copy)] if copy else proxy_tunnel.routed_copies(slug, proxy_id)[:1]
    except Exception as exc:  # noqa: BLE001 - not knowing is not "none"
        raise HTTPException(
            status_code=503,
            detail=f"Could not check whether {slug} still runs through a proxy on this worker ({exc}); nothing changed",
        ) from None
    if found:
        pid, name = found[0]
        raise HTTPException(
            status_code=409,
            detail=f"{slug} still runs through proxy {pid} on this worker ({name}). Remove that copy first, "
            "then deploy it direct; nothing changed",
        )


def _deploy_target_id(name: str) -> str:
    try:
        target = orchestrator.deploy_target(orchestrator._get_client(), name)
    except (DockerException, RuntimeError):
        raise HTTPException(status_code=503, detail="Could not look up the deploy container in Docker.") from None
    return "none" if target is None else target.id


@app.get("/api/containers/{slug}/deploy-checked")
async def api_checked_deploy_state(request: Request, slug: str, instance: int = 1) -> dict[str, Any]:
    """Read the deploy target from Docker without reading its logs."""
    _verify_api_key(request)
    _validate_instance(instance)
    target = await asyncio.to_thread(_deploy_target_id, orchestrator._container_name(slug, instance))
    return {"exists": target != "none", "expected_container": target}


@app.get("/api/proxied/{slug}/{proxy_id}/deploy")
async def api_proxied_deploy_state(request: Request, slug: str, proxy_id: int) -> dict[str, str]:
    _verify_api_key(request)
    target = await asyncio.to_thread(_deploy_target_id, proxy_tunnel.earner_name(slug, proxy_id))
    return {"expected_container": target}


def _deploy_direct(**kwargs: Any) -> str:
    """Keep the route check, deploy and release under the same service lock."""
    slug = kwargs["slug"]
    with route_gate.deploying(slug):
        if not kwargs.get("leave_route"):
            return orchestrator.deploy_raw(**kwargs)
        _refuse_beside_routed_copy(slug)
        container_id = orchestrator.deploy_raw(**kwargs)
        # It runs from this box's own IP now, as the owner confirmed.
        route_gate.release(slug)
        return container_id


@app.post("/api/containers/{slug}/deploy")
async def api_deploy_container(request: Request, slug: str, spec: CheckedDeploySpec) -> dict[str, Any]:
    """Deploy through the legacy URL using the same check as the checked URL."""
    return await _deploy_container(request, slug, spec)


@app.post("/api/containers/{slug}/deploy-checked")
async def api_deploy_container_checked(request: Request, slug: str, spec: CheckedDeploySpec) -> dict[str, Any]:
    """Create a container, or replace one only with the controller's approval."""
    return await _deploy_container(request, slug, spec)


async def _deploy_container(request: Request, slug: str, spec: CheckedDeploySpec) -> dict[str, Any]:
    _verify_api_key(request)
    # Counted from now, not from when a thread is free: the UI's hold on the ids
    # of a deploy it got no answer for must outlast it (constants.DEPLOY_DEADLINE_SECONDS).
    deadline = time.monotonic() + DEPLOY_DEADLINE_SECONDS
    # Threaded like every other Docker touch in this file: _validate_runtime
    # inside does a live daemon round-trip (available_runtimes has no cache and
    # no timeout), and unthreaded it blocked the WHOLE event loop on a wedged
    # daemon — including /api/health, so the container flipped unhealthy
    # because an unrelated route was stuck. HTTPException propagates through
    # to_thread unchanged, so the 400/403 behaviour is identical.
    await asyncio.to_thread(_validate_deploy_spec, spec, slug)
    # Last of the checks: it spends the approval, which a refusal above must not.
    await asyncio.to_thread(_validate_critical_spec, spec, slug)
    leave_route = await asyncio.to_thread(_validate_route_approval, spec, slug)
    kept_mounts: list[dict[str, str]] = []
    replaced: dict[str, str] = {}
    wallet: dict[str, Any] = {}
    try:
        container_id = await asyncio.to_thread(
            _deploy_direct,
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
            runtime=spec.runtime,
            moved_mounts=spec.moved_mounts,
            kept_mounts=kept_mounts,
            keep_targets=_catalog_volume_targets(slug),
            instance=spec.instance,
            expected_container=spec.expected_container,
            leave_route=leave_route,
            replaced_identity=replaced,
            deadline=deadline,
            wallet_seed=spec.wallet_seed.model_dump() if spec.wallet_seed else None,
            wallet=wallet,
        )
        await asyncio.to_thread(lan_fence.refresh_outside)
        response: dict[str, Any] = {"status": "deployed", "container_id": container_id}
        if wallet:
            # The phrase only when this deploy made the wallet: the UI shows it
            # once and keeps nothing (app/wallet_seed.py).
            response["wallet"] = wallet
        if kept_mounts:
            response["kept_mounts"] = kept_mounts
        # The ids the replaced container ran, for the UI's ledger (a replacement
        # is a removal of the old container).
        if digest := replaced.get("identity_digest"):
            response["replaced_identity_digest"] = digest
        return response
    except orchestrator.DeployTargetChanged as exc:
        if spec.replace_existing and spec.expected_container == "none":
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "replace_existing",
                    "message": "Update CashPilot-Desktop to confirm the exact container before replacing it.",
                    "current_container": exc.actual,
                },
            ) from None
        raise _deploy_target_error(exc) from None
    except orchestrator.ContainerNetworkError as exc:
        # The operator's own setting, and the message says how to fix it; a bare
        # 500 would hide both. Raised before the old container was touched.
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except orchestrator.CriticalMountError as exc:
        # Structured, so the UI can show it and write it to its audit table.
        logger.warning("Deploy of %s refused: %s", slug, exc)
        raise HTTPException(status_code=403, detail={"error": "critical_volume_mount", "message": str(exc)}) from None
    except route_gate.RouteRefused as exc:
        # Raised before the running container was touched (orchestrator.deploy_raw).
        logger.warning("Deploy of %s refused: %s", slug, exc)
        raise HTTPException(status_code=403, detail={"error": exc.error, "message": str(exc)}) from None
    except orchestrator.WalletSeedRefused as exc:
        # Before the running container was touched. Structured, so the UI can
        # offer the way out; the message never holds a phrase.
        logger.warning("Deploy of %s refused: %s", slug, exc.code)
        raise HTTPException(status_code=exc.status_code, detail={"error": exc.code, "message": str(exc)}) from None
    except orchestrator.ContainerRuntimeError as exc:
        # Same shape as the network setting; 503 when the daemon could not be
        # asked at all. Mostly raised before the old container was touched; a
        # deadline passed after its stop puts it back and starts it again.
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    except APIError as exc:
        refusal = orchestrator.proxy_refusal(exc)
        if refusal:
            # The socket proxy's policy said no; its reason names the rule.
            logger.warning("Deploy of %s refused by the Docker socket proxy: %s", slug, refusal)
            raise HTTPException(status_code=403, detail=refusal) from None
        # Docker itself refused to create or start the container: a host port
        # another container holds, a device the host lacks. Its explanation is
        # what the operator needs, so it goes back as a 409 the UI shows, on one
        # line and capped, instead of the bare 500 below.
        logger.warning("Deploy of %s refused by Docker: %s", slug, exc)
        reason = " ".join(str(exc.explanation or exc).split())[:300]
        raise HTTPException(status_code=409, detail=f"Docker refused the container: {reason}") from None
    except HTTPException:
        raise
    except Exception:
        logger.exception("Deploy failed for %s", slug)
        raise HTTPException(status_code=500, detail="Container deployment failed")


@app.post("/api/containers/{slug}/wallet-seed")
async def api_wallet_seed(request: Request, slug: str) -> JSONResponse:
    """The seed phrase in the node's own file, for the owner's Reveal (app/wallet_seed.py).

    Only with the UI's signed note that the owner re-entered their password for
    this service on this worker (step_up.ACTION_REVEAL_WALLET_SEED), checked with
    this worker's own key: neither the shared fleet key nor the admin API key
    reads it alone. Read from the deployed container, running or not; nothing
    is logged but that it was read.
    """
    _verify_api_key(request)
    try:
        step_up.check(
            _worker_key,
            request.headers.get(step_up.APPROVAL_HEADER),
            step_up.ACTION_REVEAL_WALLET_SEED,
            step_up.reveal_target(slug, CLIENT_ID),
        )
    except step_up.StepUpError as exc:
        raise HTTPException(
            status_code=403, detail={"error": "step_up_rejected", "message": f"{exc}. Nothing was read."}
        ) from None
    svc = orchestrator.get_service(slug) if orchestrator.get_service else None
    if wallet_seed.seed_var(svc) is None:
        raise HTTPException(
            status_code=404, detail={"error": "wallet_none", "message": f"{slug} keeps no wallet seed."}
        )

    def _read() -> str:
        container = orchestrator._find_container(slug)
        if container is None:
            raise wallet_seed.WalletSeedError(f"{slug} is not deployed on this worker.", "wallet_missing", 404)
        return wallet_seed.reveal(container, svc)

    try:
        phrase = await asyncio.to_thread(_read)
    except wallet_seed.WalletSeedError as exc:
        raise HTTPException(status_code=exc.status, detail={"error": exc.code, "message": str(exc)}) from None
    logger.warning("The wallet seed of %s was read for the owner's Reveal", slug)
    return JSONResponse({"phrase": phrase}, headers={"Cache-Control": "no-store"})


@app.post("/api/containers/{slug}/restart")
async def api_restart_container(request: Request, slug: str, instance: int = 1) -> dict[str, str]:
    _verify_api_key(request)
    _validate_instance(instance)
    try:
        await asyncio.to_thread(orchestrator.restart_service, slug, instance)
        return {"status": "restarted"}
    except route_gate.RouteRefused as exc:
        # The deploy's rule: not from this box's own IP (app/route_gate.py).
        logger.warning("Restart of %s refused: %s", slug, exc)
        raise HTTPException(status_code=403, detail={"error": exc.error, "message": str(exc)}) from None
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except orchestrator.ContainerRuntimeError as exc:
        # A refusal (a restore of it runs or did not finish), not an unreachable Docker.
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/containers/{slug}/stop")
async def api_stop_container(request: Request, slug: str, instance: int = 1) -> dict[str, str]:
    _verify_api_key(request)
    _validate_instance(instance)
    try:
        await asyncio.to_thread(orchestrator.stop_service, slug, instance)
        return {"status": "stopped"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/containers/{slug}/start")
async def api_start_container(request: Request, slug: str, instance: int = 1) -> dict[str, str]:
    _verify_api_key(request)
    _validate_instance(instance)
    try:
        await asyncio.to_thread(orchestrator.start_service, slug, instance)
        return {"status": "started"}
    except route_gate.RouteRefused as exc:
        # The deploy's rule: not from this box's own IP (app/route_gate.py).
        logger.warning("Start of %s refused: %s", slug, exc)
        raise HTTPException(status_code=403, detail={"error": exc.error, "message": str(exc)}) from None
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except orchestrator.ContainerRuntimeError as exc:
        # A refusal (a restore of it runs or did not finish), not an unreachable Docker.
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def _check_critical_delete_approval(request: Request, slug: str, critical_set: str | None = None) -> None:
    """Refuse a delete of critical data that does not carry the owner's checked approval.

    Overriding the critical-volume guard destroys a node identity or a wallet
    for good. The UI signs this approval (step_up.ACTION_DELETE_CRITICAL, bound
    to this service on this worker) only after the owner re-entered their
    password, and only this worker's own key checks it, so neither the shared
    fleet key nor the admin API key can do it alone. A worker still on the
    shared key refuses it, as it refuses a restore. ``critical_set`` is the set
    of critical volumes the owner reviewed: the approval must name it, and the
    removal then deletes those volumes or nothing (orchestrator.remove_service).
    """
    try:
        step_up.check(
            _worker_key,
            request.headers.get(step_up.APPROVAL_HEADER),
            step_up.ACTION_DELETE_CRITICAL,
            step_up.delete_target(slug, CLIENT_ID, critical_set),
        )
    except step_up.StepUpError as exc:
        raise HTTPException(
            status_code=403, detail={"error": "step_up_rejected", "message": f"{exc}. Nothing was removed."}
        ) from None


@app.delete("/api/containers/{slug}")
async def api_remove_container(
    request: Request,
    slug: str,
    delete_volumes: bool = False,
    allow_delete_critical: bool = False,
    only_if_restore_unfinished: bool = False,
    critical_set: str | None = None,
) -> dict[str, Any]:
    _verify_api_key(request)
    approved = None
    if delete_volumes and allow_delete_critical:
        _check_critical_delete_approval(request, slug, critical_set)
        # A delete that names no reviewed set reviewed none: it removes no
        # critical volume (orchestrator.remove_service refuses and names them).
        approved = critical_set or ""
    # Copy deploys running when the removal starts, and how many had started.
    # One may finish inside remove_all, after it listed the copies, or start
    # and finish inside it, so the set read afterwards alone would miss the
    # earner it made.
    deploying = {pid for s, pid in list(_copy_deploys) if s == slug}
    started = {pid: n for (s, pid), n in list(_copy_starts.items()) if s == slug}
    try:
        result = await asyncio.to_thread(
            orchestrator.remove_service,
            slug,
            delete_volumes=delete_volumes,
            allow_delete_critical=allow_delete_critical,
            only_if_restore_unfinished=only_if_restore_unfinished,
            approved_critical=approved,
        )
        # Read before they go: the UI keeps the ids the copies ran with.
        try:
            digests = await asyncio.to_thread(orchestrator.copy_identity_digests, slug)
        except Exception:  # noqa: BLE001 - bookkeeping never blocks a removal
            digests = {}
        if digests:
            result["identity_digests"] = digests
        extras = await asyncio.to_thread(orchestrator.remove_extra_instances, slug)
        if extras:
            result["extra_instances"] = extras
        # Proxied copies go with the service, earners before their tunnels, so
        # no tunnel is left running for a service the UI no longer knows.
        try:
            proxied = await asyncio.to_thread(proxy_tunnel.remove_all, slug)
        except Exception as exc:  # noqa: BLE001 - the service itself is already gone
            logger.warning("Removed %s, but could not remove its proxied copies: %s", slug, exc)
            proxied = []
            # The UI keeps the copies' records when this is set, so a copy that
            # survived stays listed and can be removed again.
            result["proxied_error"] = proxy_tunnel.redact(str(exc))[:300]
        # remove_all sees only copies that exist. One whose deploy ran during
        # the removal (the UI gave up on it after 180 s) may be made after it
        # listed them, so the UI must keep the copies' records, as
        # api_proxied_remove holds them.
        deploying |= {pid for s, pid in list(_copy_deploys) if s == slug}
        deploying |= {pid for (s, pid), n in list(_copy_starts.items()) if s == slug and n != started.get(pid)}
        if held := sorted(deploying):
            result.setdefault(
                "proxied_error",
                f"A deploy of {slug} through proxy {', '.join(map(str, held))} ran during this removal on this worker",
            )
        if proxied:
            result["proxied"] = proxied
        await asyncio.to_thread(lan_fence.refresh_outside)
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
                # What the owner's approval names to delete exactly these (step_up.delete_target).
                "critical_set": exc.critical_set,
                "hint": (
                    "Nothing was removed. Back up the listed volumes first. To proceed "
                    "anyway, repeat the request with allow_delete_critical=true."
                ),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except orchestrator.RestoreUnfinishedError as exc:
        # A code, so the dashboard's Remove can offer to delete the half-written data.
        raise HTTPException(status_code=409, detail={"error": "restore_unfinished", "message": str(exc)})
    except orchestrator.RestoreClearedError as exc:
        # The owner's yes was to delete a partial restore, which is gone now.
        raise HTTPException(status_code=409, detail={"error": "restore_cleared", "message": str(exc)})
    except orchestrator.ContainerRuntimeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.delete("/api/containers/{slug}/instances/{instance}")
async def api_remove_instance(request: Request, slug: str, instance: int) -> dict[str, Any]:
    """Remove one extra copy of a service, when the UI scales it down."""
    _verify_api_key(request)
    _validate_instance(instance)
    try:
        result = await asyncio.to_thread(orchestrator.remove_instance, slug, instance)
        return {"status": "removed", **result}
    except orchestrator.ContainerNotFoundError as exc:
        # A code, so the UI tells "this box has no such copy" from any other 404
        # (an unknown route on an older worker, a proxy in between).
        raise HTTPException(status_code=404, detail={"error": "copy_not_found", "message": str(exc)})
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def _log_filter(match: str, since_hours: float) -> re.Pattern[str] | None:
    """The compiled ``match`` of a windowed log read, or None for a plain tail. 400 for a bad one."""
    if not match or since_hours <= 0:
        return None
    if len(match) > 200:
        raise HTTPException(status_code=400, detail="match is too long")
    try:
        return re.compile(match)
    except re.error:
        raise HTTPException(status_code=400, detail="match is not a valid regular expression") from None


@app.get("/api/containers/{slug}/logs")
async def api_container_logs(
    request: Request, slug: str, lines: int = 50, instance: int = 1, match: str = "", since_hours: float = 0
) -> dict[str, Any]:
    """The log tail, or with ``match`` and ``since_hours`` the matching lines of that window.

    ``filtered`` tells the caller its filter was applied: a worker from before
    these parameters ignores them and returns the plain tail, which must not be
    read as the window.
    """
    _verify_api_key(request)
    _validate_instance(instance)
    compiled = _log_filter(match, since_hours)
    try:
        if compiled is not None:
            logs = await asyncio.to_thread(
                orchestrator.grep_service_logs,
                slug,
                compiled,
                since_hours=min(since_hours, 24),
                lines=min(lines, 1000),
                instance=instance,
            )
            return {"logs": logs, "filtered": True}
        logs = await asyncio.to_thread(orchestrator.get_service_logs, slug, lines=min(lines, 1000), instance=instance)
        return {"logs": logs}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


class BackupRequest(BaseModel):
    """Target for an export. Exactly one of the two must be supplied.

    A passphrase arrives, is used to derive a key, and is discarded with the
    request. It is never written to disk, never logged, and never returned.
    """

    passphrase: str | None = None
    recipient_public_key: str | None = None


class VerifyRequest(BackupRequest):
    """A bundle to check against the state currently on disk.

    Recipient-mode verification needs the PRIVATE half — decryption happens in
    memory on the worker and the key is discarded with the request. This is the
    one moment recipient mode is not key-free, so the field says so rather than
    letting someone paste a private key into something named `_public_key`
    without noticing what they just did. Verify from a host you trust, or use
    passphrase mode if that is not acceptable.
    """

    bundle_b64: str = ""
    recipient_private_key: str | None = None


@app.post("/api/containers/{slug}/backup")
async def api_backup(slug: str, body: BackupRequest, request: Request) -> dict[str, Any]:
    """Export this service's irreplaceable state, encrypted HERE.

    Encryption happens on the worker so the UI only ever handles ciphertext:
    plaintext key material must not cross the wire even inside the fleet, and it
    must not sit in the UI's memory where a different compromise would reach it.

    The bundle is returned in THIS response and nowhere else. There is
    deliberately no upload, sync or webhook path in the code — the absence is
    what makes the guarantee checkable, rather than a policy nobody audits.
    """
    _verify_api_key(request)
    try:
        payload, targets, fingerprint = await asyncio.to_thread(orchestrator.read_critical_state, slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except orchestrator.ContainerRuntimeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Backup read failed for %s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Could not read this service's state") from exc

    try:
        # The restore's own checks, run now while the user can still act: a bundle
        # that split_archives would refuse must not be handed over as a backup.
        await asyncio.to_thread(state_backup.split_archives, payload)
        bundle = await asyncio.to_thread(
            lambda: state_backup.seal(
                payload,
                passphrase=body.passphrase,
                recipient_public_key=body.recipient_public_key,
                metadata={"slug": slug, "worker": WORKER_NAME, "targets": targets},
            )
        )
    except state_backup.BackupError as exc:
        # Safe to surface: these messages are about the CALLER's inputs and
        # deliberately contain neither the passphrase nor any state.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # "state_id" says which state this bundle holds, so the UI can tell when it
    # no longer matches what runs; read_critical_state took it from the volume
    # the archive came from. Unknown is fine: the UI falls back to a time limit.
    # The heartbeat's "state_backup" feature tells the UI this field exists.
    return {
        "slug": slug,
        "targets": targets,
        "bytes": len(bundle),
        "bundle_b64": base64.b64encode(bundle).decode("ascii"),
        "state_id": fingerprint,
    }


@app.post("/api/containers/{slug}/backup/verify")
async def api_backup_verify(slug: str, body: VerifyRequest, request: Request) -> dict[str, Any]:
    """Does this bundle still match what is on disk?

    "I have a backup file" and "I have a backup that works" are different
    claims. Believing the first is how people find a dead node and an unusable
    file on the same afternoon.

    Decryption happens in memory on the worker and nothing is written anywhere;
    only digests are compared, so no plaintext is produced for the caller.
    """
    _verify_api_key(request)
    try:
        bundle = base64.b64decode(body.bundle_b64 or "", validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Bundle is not valid base64") from exc
    if not state_backup.looks_like_bundle(bundle):
        raise HTTPException(status_code=400, detail="That file is not a CashPilot backup bundle")

    try:
        payload, _targets, _state = await asyncio.to_thread(orchestrator.read_critical_state, slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except orchestrator.ContainerRuntimeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Backup verify read failed for %s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Could not read this service's state") from exc

    return await asyncio.to_thread(
        lambda: state_backup.verify(
            bundle,
            payload,
            passphrase=body.passphrase,
            recipient_private_key=body.recipient_private_key,
        )
    )


#: The largest restore request the worker reads: a bundle of the largest export
#: (orchestrator.MAX_BACKUP_BYTES) in base64, plus the deploy spec. Read by hand
#: and counted as it arrives, so a bigger body is refused without being held.
MAX_RESTORE_BODY = (orchestrator.MAX_BACKUP_BYTES + 1024 * 1024) * 4 // 3 + 256 * 1024


async def _read_capped(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail="The restore request is larger than any backup can be")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise HTTPException(status_code=413, detail="The restore request is larger than any backup can be")
    return bytes(body)


@app.post("/api/containers/{slug}/restore")
async def api_restore(slug: str, request: Request) -> dict[str, Any]:
    """Restore a passphrase backup into a new container of ``slug`` on this box (issue #741).

    The body is the deploy spec the UI built for a plain deploy, plus
    ``bundle_b64``, ``passphrase`` and ``approval``. It is read by hand, never
    through a model, so no error can echo the passphrase, and it is capped.

    In order: the spec passes every deploy check, and must be exactly the
    catalog's (no custom image, command, env key or mount, even with a
    password); the approval must be the UI's, for this action, this service,
    this worker and the SHA-256 of these bytes. Then the bundle is opened here and checked by the same rules as
    the command line restore, outside any lock, and orchestrator.restore_state
    writes it into a new container, compares and starts it. Recipient-key
    bundles are refused: their private key never comes through the dashboard.
    """
    _verify_api_key(request)
    raw = await _read_capped(request, MAX_RESTORE_BODY)
    try:
        body = json.loads(raw)
    except ValueError:
        body = None
    del raw
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object")
    bundle_b64, passphrase, approval = (
        body.pop("bundle_b64", None),
        body.pop("passphrase", None),
        body.pop("approval", None),
    )
    if not all(isinstance(v, str) and v for v in (bundle_b64, passphrase, approval)):
        raise HTTPException(status_code=400, detail="A restore needs the file, its passphrase and the approval")
    try:
        spec = DeploySpec(**body)
    except (ValidationError, TypeError):
        raise HTTPException(status_code=400, detail="The deploy spec of the restore is malformed") from None
    if spec.instance != 1 or spec.approval:
        raise HTTPException(status_code=400, detail="A restore creates the first copy, as the catalog runs it")
    await asyncio.to_thread(_validate_deploy_spec, spec, slug)
    if slug not in orchestrator.critical_slugs() or orchestrator.restore_targets(slug) is None:
        raise HTTPException(
            status_code=409,
            detail=f"{slug} cannot be restored from the dashboard: it keeps its state in a host folder, or none. "
            "Use the command line steps in the backup guide.",
        )
    found = orchestrator.critical_spec_deviations(slug, spec.image, spec.command, spec.env, spec.volumes)
    if found:
        raise HTTPException(
            status_code=403,
            detail=f"A restore runs {slug} exactly as this worker's catalog does, and this one differs: "
            f"{'; '.join(found)}. Nothing was restored.",
        )
    # The deviations above compare mount targets only: a spec that mounts
    # another volume at a critical folder, or none, would pass them and fail
    # only after the restore made its volume. Refused here, before anything.
    mounted = {
        orchestrator._norm_mount(str((m or {}).get("bind") or "")): str(source)
        for source, m in (spec.volumes or {}).items()
    }
    for target, volume in sorted((orchestrator.restore_targets(slug) or {}).items()):
        if mounted.get(orchestrator._norm_mount(target)) != volume:
            raise HTTPException(
                status_code=400,
                detail=f"A restore writes {target} into the volume {volume}, as this worker's catalog runs {slug}, "
                "and this deploy spec does not mount it there. Nothing was restored.",
            )
    try:
        bundle = base64.b64decode(bundle_b64, validate=True)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="The backup file is not valid base64") from None
    del bundle_b64
    digest = hashlib.sha256(bundle).hexdigest()
    try:
        step_up.check(_worker_key, approval, step_up.ACTION_RESTORE, step_up.restore_target(slug, CLIENT_ID, digest))
    except step_up.StepUpError as exc:
        raise HTTPException(
            status_code=403, detail={"error": "step_up_rejected", "message": f"{exc}. Nothing was restored."}
        ) from None
    try:
        header = state_backup.read_header(bundle)
        if header.get("mode") != state_backup.MODE_PASSPHRASE:
            raise state_backup.BackupError(
                "This file is sealed to a key, not a passphrase. Its private key never goes through the dashboard: "
                "restore it with the command line steps in the backup guide."
            )
        payload = await asyncio.to_thread(state_backup.open_bundle, bundle, passphrase=passphrase)
        del passphrase
        meta = header.get("metadata") or {}
        if meta.get("slug") != slug:
            # The header is authenticated, so this is what the file really holds.
            raise state_backup.BackupError(f"This is a backup of {meta.get('slug')!r}, not of {slug}.")
        archives = await asyncio.to_thread(state_backup.split_archives, payload)
        del payload
    except state_backup.BackupError as exc:
        raise HTTPException(status_code=400, detail=f"{exc} Nothing was restored.") from None
    deploy = {
        "image": spec.image,
        "env": spec.env,
        "ports": spec.ports,
        "volumes": spec.volumes,
        "network_mode": spec.network_mode,
        "cap_add": spec.cap_add,
        "devices": spec.devices,
        "command": spec.command,
        "hostname": spec.hostname,
        "labels": spec.labels,
        "resources": spec.resources,
        "runtime": spec.runtime,
        "keep_targets": _catalog_volume_targets(slug),
    }
    try:
        result = await asyncio.to_thread(orchestrator.restore_state, slug, archives, deploy)
    except orchestrator.RestoreError as exc:
        logger.warning("Restore of %s refused or undone: %s", slug, exc)
        # exc.detail, never str(exc): the message RestoreError was built with,
        # fixed text and names only (Docker's own answer stays in the log).
        if exc.left:
            # The undo could not remove these: the restored data may still be
            # on the box, so the UI keeps holding the identity there.
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "left": exc.left})
        # "restored": false tells the UI this is the worker's own answer, so a
        # 503 here is not a gateway's: nothing of this restore is on the box.
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "restored": False})
    await asyncio.to_thread(lan_fence.refresh_outside)
    return {"status": "restored", "bundle_sha256": digest, **result}


@app.get("/api/runtimes")
async def api_runtimes(request: Request) -> dict[str, Any]:
    """Container runtimes this host actually provides.

    Advanced and unsupported. CashPilot never selects one: the default runtime
    is what every service is tested against, and the alternatives cost real
    throughput on a workload that is pure network I/O.
    """
    _verify_api_key(request)
    runtimes = await asyncio.to_thread(orchestrator.available_runtimes)
    if runtimes is None:
        # Same split as _validate_runtime: unreachable daemon is an outage,
        # and an empty list here would read as "no runtimes installed".
        raise HTTPException(status_code=503, detail="The Docker daemon is not answering.")
    available = sorted(runtimes)
    return {
        "available": available,
        "default": orchestrator._CONTAINER_RUNTIME or None,
        "supported": False,
        "note": (
            "Selecting a non-default runtime is an advanced, unsupported choice. It is not a "
            "hardening recommendation — see the docs for why."
        ),
    }


@app.post("/api/isolation-check")
async def api_isolation_check(request: Request) -> dict[str, Any]:
    """What an earner on this host can reach (issue #451).

    Starts two short-lived probe containers from the worker's own image and
    removes them on every path. Creates nothing else and changes no firewall
    rule; see app/isolation_check.py. The errors are structured so the UI
    forwards them (main._safe_worker_detail).
    """
    _verify_api_key(request)
    try:
        return await asyncio.to_thread(isolation_check.run)
    except isolation_check.CheckBusy as exc:
        raise HTTPException(status_code=409, detail={"error": "isolation_check_busy", "message": str(exc)})
    except (RuntimeError, DockerException, requests.exceptions.RequestException):
        # No Docker socket, or a daemon that failed or stalled past the check's
        # own timeout halfway through: the same outage split as the rest of
        # this API, never a bare 500. A fixed message: the exception text can
        # name internal paths.
        raise HTTPException(
            status_code=503,
            detail={
                "error": "isolation_check_unavailable",
                "message": "The worker's Docker daemon did not answer, so it cannot run the check.",
            },
        )


@app.post("/api/isolation")
async def api_isolation(request: Request) -> dict[str, Any]:
    """Turn LAN isolation on for an upgraded worker.

    Creates CashPilot's network and writes its firewall table, then answers with
    the earners still on Docker's default bridge: the UI redeploys each one onto
    the new network. Turning it off is the CASHPILOT_ISOLATION=off setting, never
    a request, so one click cannot undo the fence.
    """
    _verify_api_key(request)
    # Read after the key check, so an unauthenticated caller learns nothing
    # about the body this route takes.
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or body.get("enable") is not True:
        raise HTTPException(
            status_code=400,
            detail="Isolation is turned off with CASHPILOT_ISOLATION=off on the worker, not from the dashboard.",
        )
    try:
        return await asyncio.to_thread(lan_fence.enable)
    except lan_fence.IsolationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except (DockerException, requests.exceptions.RequestException):
        raise HTTPException(status_code=503, detail="The worker's Docker daemon did not answer.") from None


@app.get("/api/payout-addresses")
async def api_payout_addresses(request: Request) -> dict[str, Any]:
    """Payout addresses set inside this worker's running containers.

    Only for services whose catalog entry declares ``payout.address_read``
    (Mysterium's beneficiary, Anyone's anonrc wallet). Read-only: see
    app/payout_read.py.
    """
    _verify_api_key(request)
    if not _catalog_get_services:
        return {"addresses": []}
    try:
        rows = await asyncio.to_thread(payout_read.read_all, _catalog_get_services())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"addresses": rows}


@app.get("/api/node-earnings")
async def api_node_earnings(request: Request) -> dict[str, Any]:
    """Earnings figures a node on this worker reports about itself (issue #488).

    Only for services whose catalog entry declares ``collector.node_read``
    (Mysterium's TequilAPI identity). Read-only: see app/node_read.py.
    """
    _verify_api_key(request)
    if not _catalog_get_services:
        return {"nodes": []}
    try:
        rows = await asyncio.to_thread(node_read.read_all, _catalog_get_services())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"nodes": rows}


@app.get("/api/health-probes")
async def api_health_probes(request: Request) -> dict[str, Any]:
    """Which declared health checks hold for each node on this worker.

    Only for services whose catalog entry declares ``docker.health_probe``
    (Mysterium's monitoring status and recent sessions). Read-only, and only
    the indexes of the checks that hold leave the worker: see
    app/health_probe.py.
    """
    _verify_api_key(request)
    if not _catalog_get_services:
        return {"probes": []}
    try:
        rows = await asyncio.to_thread(health_probe.read_all, _catalog_get_services())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"probes": rows}


@app.get("/api/update/info")
async def api_update_info(request: Request) -> dict[str, Any]:
    """Whether this install can update itself, and what it runs (issue #342)."""
    _verify_api_key(request)
    try:
        return await asyncio.to_thread(orchestrator.self_update_info)
    except RuntimeError as exc:
        # No Docker socket — same outage split as everywhere else on this API.
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/update/self")
async def api_update_self(request: Request) -> dict[str, Any]:
    """Run the documented update (`docker compose pull && up -d`) via a one-shot
    helper container.

    Deliberately parameterless: the compose project location comes from the
    labels on this worker's own container, the helper image is pinned, and the
    command is fixed — the caller controls nothing that reaches Docker. The
    caller still has to hold the per-worker key, and whoever holds that already
    commands this worker's Docker socket through the deploy API.
    """
    _verify_api_key(request)
    try:
        result = await asyncio.to_thread(orchestrator.spawn_self_update)
    except orchestrator.SelfUpdateUnavailable as exc:
        # Structured, so the UI's worker-detail sanitizer can forward the
        # instructions verbatim — a bare string detail gets replaced with a
        # generic message and the operator never sees what to do instead.
        raise HTTPException(status_code=409, detail={"error": "self_update_unavailable", "message": str(exc)})
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"status": "updating", **result}


@app.get("/api/health")
async def api_health(response: Response) -> dict[str, Any]:
    """Health check endpoint (no auth required).

    Reports whether this worker can still REPORT IN, not merely whether its own
    process is listening. The container healthcheck used to be a TCP connect to
    this port, which is true of a worker that has been unable to reach the UI
    for days — so `docker ps` showed "healthy" throughout a 42-hour outage on
    two hosts while the fleet page showed both as offline and nobody reconciled
    the two. A check that cannot fail for the failure you actually have is not a
    check.

    Two triggers, two windows: a sustained run of counted misses (12 cycles),
    OR a last-success stamp older than the separate, longer _HEARTBEAT_STALE_AFTER
    wall-clock window — they are deliberately NOT the same number, because the
    auth-discard ladder is cycle-counted and a wall clock equal to 12 nominal
    cycles would pre-empt it on a slow host (see the constants).
    The stamp is what catches a cycle that never RETURNS —
    a payload helper blocking on a wedged /data mount or Docker socket freezes
    the loop with the counter at zero, and only staleness can see that. It also
    covers a dead heartbeat task outright. Degraded only after a full window,
    so a UI restart or a brief blip does not flap the container. Deliberately
    NOT degraded when no UI_URL is configured: a worker with nowhere to report
    is doing exactly what it was told to.

    Docker that has failed every call for _DOCKER_UNHEALTHY_AFTER degrades it
    too, with or without a UI: a worker that cannot reach Docker manages
    nothing, while its heartbeat goes on landing. The outage clock is read from
    memory (orchestrator.docker_unreachable_for), never by calling Docker here,
    so a hung socket cannot hang this endpoint; the heartbeat and the fence
    check do the calls. The fix text is fixed: nothing of Docker's own answer.

    The annotation is dict[str, Any] on purpose: FastAPI validates the response
    against it AFTER the work is done, and a stricter type turns a future
    non-str field into a 500 exactly when the endpoint has news (the api_deploy
    lesson). Every value is still deliberately built as a str.
    """
    body: dict[str, Any] = {"status": "ok", "worker": WORKER_NAME}
    reasons: list[str] = []
    success_age = time.monotonic() - _last_heartbeat_ok
    if UI_URL and (
        _consecutive_heartbeat_failures >= _HEARTBEAT_FAILURES_UNHEALTHY_AFTER or success_age > _HEARTBEAT_STALE_AFTER
    ):
        reasons.append("not reporting to the UI")
        body["last_heartbeat"] = _last_heartbeat
        body["consecutive_failures"] = str(_consecutive_heartbeat_failures)
        body["last_success_age"] = f"{int(success_age)}s"
        if _last_error:
            body["error"] = _last_error
    docker_down = orchestrator.docker_unreachable_for()
    if docker_down is not None and docker_down > _DOCKER_UNHEALTHY_AFTER:
        reasons.append("cannot reach Docker")
        body["docker_unreachable_for"] = f"{int(docker_down)}s"
        body["docker"] = orchestrator._docker_unreachable_text()
    if reasons:
        response.status_code = 503
        body["status"] = "degraded"
        body["reason"] = "; ".join(reasons)
    return body
