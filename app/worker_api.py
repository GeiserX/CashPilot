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
import base64
import contextlib
import hmac
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
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app import egress, fleet_key, orchestrator, state_backup, version

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

    THE THREE-VALUED PART MATTERS. Inside a container with no device passed
    through, the absence of nvidia-smi proves nothing about the HOST. So:

        available True   we saw a device
        available False  we looked, found none, and we are NOT in a container,
                         so the host really has none
        available None   we could not tell -- in a container with nothing passed
                         through, which is exactly when a user most needs to know

    Reporting None as False would tell someone their machine has no GPU when it
    may have an unused one, which is the opposite of the useful answer.
    """
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

    # Linux, on the host, with no NVIDIA tool and no render node. This is the
    # one case where "no" is a real answer.
    return {"available": False, "devices": [], "detected_by": None}


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
            # So the UI can tell an operator when the two halves are different
            # releases. An older worker sends nothing here, which reads as
            # unknown rather than as a mismatch (CashPilot-l6c).
            "version": version.current(),
            # Providers count devices per public IP, so the UI needs the address
            # the provider sees — not this container's LAN or tailnet address.
            "egress_ip": await _detect_egress_ip(),
            "egress_network_type": _detect_network_type(),
            # Disk is earning capacity for Storj; GPU decides whether the compute
            # services can earn at all. Both are None/unknown-aware -- see the
            # helpers (CashPilot-cle).
            "disk": await asyncio.to_thread(_disk_usage),
            "gpu": await asyncio.to_thread(_gpu_info),
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
                # Enrollment: the UI returns our own per-worker key exactly once.
                issued = None
                with contextlib.suppress(Exception):
                    issued = resp.json().get("worker_key")
                if issued and issued != _worker_key:
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
        logger.warning("Heartbeat failed: %s", _redact_userinfo(str(exc)))
        _log_link_failure_hint(exc)


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
        logger.info("Heartbeat enabled -> %s (every %ds)", _redact_userinfo(UI_URL), HEARTBEAT_INTERVAL)
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


app = FastAPI(title="CashPilot Worker", version=version.current(), lifespan=lifespan)


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
    cpu_shares is a *relative* weight (Docker's default is 1024) that only
    takes effect while the host is contended, so it protects a latency-
    sensitive earner from noisy neighbours without capping it on an idle box.
    """

    mem_limit: str | None = None
    mem_reservation: str | None = None
    oom_score_adj: int | None = None
    cpu_shares: int | None = None


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
    # Advanced and unsupported. Absent means Docker's default runtime, which is
    # what everything uses and what everything is tested against.
    runtime: str | None = None


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


def _validate_runtime(runtime: str | None) -> None:
    """Allow only a runtime this daemon actually reports.

    Deliberately NOT a hardcoded list. A runtime CashPilot recognises but the
    host has not installed would fail at container-create time with a Docker
    error the user cannot act on; asking the daemon means the only runtimes
    accepted are ones that exist here.

    Nothing selects a non-default runtime on its own. See docs/security-defaults.md for
    why gVisor is not adopted as a default or as a supported profile: it costs
    roughly 1.7x network throughput on a workload that is pure network I/O, it
    breaks host-networked services outright, and it does not address the risks
    that actually occur in this category.
    """
    if not runtime:
        return
    available = orchestrator.available_runtimes()
    if runtime not in available:
        raise HTTPException(
            status_code=400,
            detail=(
                f"This host's Docker daemon does not provide a {runtime!r} runtime. "
                f"Available: {sorted(available) or 'none reported'}."
            ),
        )


def _validate_deploy_spec(spec: DeploySpec, slug: str | None = None) -> None:
    _validate_runtime(spec.runtime)
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
            runtime=spec.runtime,
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
        payload, targets = await asyncio.to_thread(orchestrator.read_critical_state, slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Backup read failed for %s: %s", slug, exc)
        raise HTTPException(status_code=500, detail="Could not read this service's state") from exc

    try:
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

    return {
        "slug": slug,
        "targets": targets,
        "bytes": len(bundle),
        "bundle_b64": base64.b64encode(bundle).decode("ascii"),
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
        payload, _targets = await asyncio.to_thread(orchestrator.read_critical_state, slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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


@app.get("/api/runtimes")
async def api_runtimes(request: Request) -> dict[str, Any]:
    """Container runtimes this host actually provides.

    Advanced and unsupported. CashPilot never selects one: the default runtime
    is what every service is tested against, and the alternatives cost real
    throughput on a workload that is pure network I/O.
    """
    _verify_api_key(request)
    available = sorted(await asyncio.to_thread(orchestrator.available_runtimes))
    return {
        "available": available,
        "default": None,
        "supported": False,
        "note": (
            "Selecting a non-default runtime is an advanced, unsupported choice. It is not a "
            "hardening recommendation — see the docs for why."
        ),
    }


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

    The annotation is dict[str, Any] on purpose: FastAPI validates the response
    against it AFTER the work is done, and a stricter type turns a future
    non-str field into a 500 exactly when the endpoint has news (the api_deploy
    lesson). Every value is still deliberately built as a str.
    """
    body: dict[str, Any] = {"status": "ok", "worker": WORKER_NAME}
    success_age = time.monotonic() - _last_heartbeat_ok
    if UI_URL and (
        _consecutive_heartbeat_failures >= _HEARTBEAT_FAILURES_UNHEALTHY_AFTER or success_age > _HEARTBEAT_STALE_AFTER
    ):
        response.status_code = 503
        body["status"] = "degraded"
        body["reason"] = "not reporting to the UI"
        body["last_heartbeat"] = _last_heartbeat
        body["consecutive_failures"] = str(_consecutive_heartbeat_failures)
        body["last_success_age"] = f"{int(success_age)}s"
        if _last_error:
            body["error"] = _last_error
    return body
