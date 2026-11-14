"""Which earners may run from this box's own IP (worker side; docs/proxies.md).

A service can be routed through one of the owner's proxies from its first
deploy, so it never runs once from the box's own connection. That promise is
kept here, on the worker, and not in the UI's records: the UI has several ways
to deploy (the deploy form, the raw command route, extra copies, a redeploy)
and a record can be lost, but every earner container this worker creates goes
through ``orchestrator.deploy_raw``, which calls :func:`check`.

Two rules, one function:

* ``CASHPILOT_PROXIED_ONLY=true`` in the worker's environment: no earner runs
  outside a tunnel on this box, whatever the UI sends. The UI cannot change it.
* A service once routed through a proxy on this box (``ROUTED_MARKER``) is
  refused from the box's own IP until the owner confirms the switch with their
  password: the UI then sends a signed, single-use approval
  (``step_up.ACTION_LEAVE_ROUTE``) that the worker checks before the deploy.
  Removing the service does not clear the mark, so a removal and a fresh
  deploy cannot skip that confirmation.

Stdlib only: the worker image carries it (Dockerfile.worker).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

from app.constants import LABEL_MANAGED, LABEL_ROLE, ROLE_TUNNEL

logger = logging.getLogger(__name__)

PROXIED_ONLY_ENV = "CASHPILOT_PROXIED_ONLY"

#: slug -> the proxy id it was last routed through, as JSON.
ROUTED_MARKER = os.path.join(os.getenv("CASHPILOT_DATA_DIR", "/data"), ".routed")
_lock = threading.Lock()
_deploying: dict[str, threading.RLock] = {}


def deploying(slug: str) -> threading.RLock:
    """The lock a deploy of ``slug`` holds while it decides how the service runs and creates it.

    A direct deploy holds it from its check to its container's start
    (orchestrator.deploy_raw), and a routed deploy from its mark to its earner
    or the undoing of that mark (worker_api.api_proxied_deploy). Otherwise a
    direct earner could be created after a routed deploy found none, and a
    failed routed deploy could undo the route of one that succeeded meanwhile.
    """
    with _lock:
        return _deploying.setdefault(slug, threading.RLock())


class RouteRefused(Exception):
    """An earner that must not run from this box's own IP. The message is safe to show."""

    def __init__(self, error: str, message: str) -> None:
        super().__init__(message)
        self.error = error


def proxied_only() -> bool:
    """Whether the operator set this worker to run earners only through a tunnel."""
    return (os.getenv("CASHPILOT_PROXIED_ONLY") or "").strip().lower() in ("1", "true", "yes", "on")


def routed() -> dict[str, int]:
    """slug -> proxy id of every service routed on this box.

    Raises OSError (or ValueError) when the marker exists but cannot be read:
    an empty answer then would let a routed service start from the box's IP.
    """
    try:
        with open(ROUTED_MARKER, encoding="utf-8") as fh:
            data: Any = json.load(fh)
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{ROUTED_MARKER} is not a JSON object")
    return {str(k): int(v) for k, v in data.items()}


def _write(data: dict[str, int]) -> None:
    tmp = f"{ROUTED_MARKER}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, ROUTED_MARKER)


def mark(slug: str, proxy_id: int) -> int | None:
    """Record that ``slug`` runs through ``proxy_id`` on this box. Returns the
    proxy it was marked with before, if any. Raises OSError when it cannot be
    written: a routed deploy that is not recorded is not deployed."""
    with _lock:
        data = routed()
        before = data.get(slug)
        if before != int(proxy_id):
            data[slug] = int(proxy_id)
            _write(data)
        return before


def release(slug: str, restore: int | None = None) -> None:
    """Forget the route of ``slug``, or put back the proxy it had (``restore``).

    Best effort: a mark that stays only means the next switch to direct asks
    for the password again."""
    with _lock:
        try:
            data = routed()
            if restore is None:
                if slug not in data:
                    return
                data.pop(slug)
            else:
                data[slug] = int(restore)
            _write(data)
        except (OSError, ValueError) as exc:
            logger.warning("Could not update the route of %s in %s: %s", slug, ROUTED_MARKER, exc)


def check(slug: str, network_mode: str | None, client: Any, *, leave_route: bool = False) -> None:
    """Refuse an earner that would run from this box's own IP when it must not.

    ``network_mode`` ``container:<id>`` is an earner inside a tunnel: allowed
    only when that container is one of this worker's tunnels. Anything else
    runs from the box's own connection: refused when the box is proxied-only,
    or when ``slug`` is routed here and ``leave_route`` (a checked password
    approval) is not set.
    """
    mode = str(network_mode or "")
    if mode.startswith("container:"):
        target = mode.removeprefix("container:")
        try:
            tunnel = client.containers.get(target)
            labels = tunnel.labels if isinstance(getattr(tunnel, "labels", None), dict) else {}
        except Exception:  # noqa: BLE001 - gone or unreadable: not a tunnel we can vouch for
            labels = {}
        if labels.get(LABEL_MANAGED) != "true" or labels.get(LABEL_ROLE) != ROLE_TUNNEL:
            raise RouteRefused("route_not_tunnel", f"{slug} may share a network only with one of this worker's tunnels")
        return
    if proxied_only():
        raise RouteRefused(
            "proxied_only",
            f"This worker runs services only through a proxy ({PROXIED_ONLY_ENV} is set on it), so {slug} was "
            "not started from its own IP. Deploy it with a route through one of your proxies.",
        )
    if leave_route:
        return
    try:
        lock = routed()
    except (OSError, ValueError) as exc:
        raise RouteRefused(
            "route_unknown",
            f"Could not read which services are routed on this worker ({exc}), so {slug} was not started from "
            "its own IP.",
        ) from None
    if slug in lock:
        raise RouteRefused(
            "route_locked",
            f"{slug} runs through a proxy on this worker. Running it from the worker's own IP needs the owner's "
            "password. Nothing was deployed.",
        )
