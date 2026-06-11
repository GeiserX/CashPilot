"""Shared FastAPI dependencies and template environment for CashPilot.

These auth guards and the Jinja2 template environment are imported into
``app.main`` (via ``from app.deps import *``) so that ``app.main._require_owner``
et al. keep resolving for tests that patch/import them through ``app.main``.
Route handlers split into ``app.routers.*`` reference these through the
``app.main`` namespace so existing ``patch("app.main.auth.*")`` /
``patch("app.main.database.*")`` test seams keep landing.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import auth

__all__ = [
    "templates",
    "_login_redirect",
    "_require_auth_api",
    "_require_writer",
    "_require_owner",
    "_require_private_network",
]

templates = Jinja2Templates(directory="app/templates")


def _login_redirect() -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


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


def _require_private_network(request: Request) -> None:
    """Block requests from public IPs (for first-run setup)."""
    if not request.client or not request.client.host:
        return
    try:
        client_ip = ipaddress.ip_address(request.client.host)
    except ValueError:
        return
    if not (client_ip.is_loopback or client_ip.is_private):
        raise HTTPException(status_code=403, detail="First-run setup only allowed from private networks")
