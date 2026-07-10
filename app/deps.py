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
import os
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import auth, setup_token

__all__ = [
    "templates",
    "_login_redirect",
    "_require_auth_api",
    "_require_writer",
    "_require_owner",
    "_require_private_network",
    "_require_first_run_access",
    "client_ip",
]

# Opt-in: set CASHPILOT_TRUSTED_PROXY=1 only when the app sits behind exactly one
# reverse proxy you control. X-Forwarded-For is attacker-controlled, so we ignore
# it unless the operator asserts a trusted proxy is stripping/appending it.
_TRUST_PROXY = os.getenv("CASHPILOT_TRUSTED_PROXY", "").strip().lower() in ("1", "true", "yes", "on")

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


def client_ip(request: Request) -> str | None:
    """Best-effort real client IP.

    Behind a trusted reverse proxy (opt-in via ``CASHPILOT_TRUSTED_PROXY``) the
    real peer is the right-most ``X-Forwarded-For`` entry — the value appended by
    the trusted proxy, which a client cannot forge by prepending its own. Without
    that opt-in we never trust the header and use the direct peer.
    """
    if _TRUST_PROXY:
        xff = request.headers.get("x-forwarded-for", "")
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else None


def _require_private_network(request: Request) -> None:
    """Block requests whose real client IP is public (first-run defense in depth)."""
    ip_str = client_ip(request)
    if not ip_str:
        return
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return
    if not (ip.is_loopback or ip.is_private):
        raise HTTPException(status_code=403, detail="First-run setup only allowed from private networks")


def _require_first_run_access(request: Request, setup_token_value: str | None = None) -> None:
    """Gate first-run owner creation: private network AND the one-time setup token.

    The network check alone is spoofable behind a reverse proxy (the peer is then
    the proxy), so the setup token — printed to the server logs, readable only
    with host access — is the real gate. The token is accepted from the explicit
    argument (the registration form field) or the ``X-Setup-Token`` header.

    Deliberately NOT read from the query string: a ``?setup_token=`` URL leaks the
    secret into reverse-proxy access logs and browser history. The form field
    (typed into the setup page) and the header keep it out of URLs.
    """
    _require_private_network(request)
    token = setup_token_value or request.headers.get("x-setup-token")
    if not setup_token.verify(token):
        raise HTTPException(
            status_code=403,
            detail="First-run setup requires the setup token printed in the server logs",
        )
