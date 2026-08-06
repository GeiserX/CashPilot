"""Protected HTML page routes (dashboard, setup, catalog, settings, fleet).

Handlers reach shared state through ``app.deps``, ``app.auth`` and
``app.database`` directly — NOT through ``app.main``, which is what breaks the
``main -> routers -> main`` import cycle. Test patches therefore target
``app.auth.*`` / ``app.database.*``. ``app.auth`` is bound locally as
``auth_module`` only to avoid shadowing the route helpers.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth as auth_module
from app import database, deps

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def page_dashboard(request: Request):
    user = auth_module.get_current_user(request)
    if not user:
        if not await database.has_any_users():
            return RedirectResponse("/onboarding", status_code=303)
        return RedirectResponse("/login", status_code=303)
    return deps.templates.TemplateResponse(request, "dashboard.html", {"user": user})


@router.get("/setup", response_class=HTMLResponse)
async def page_setup(request: Request):
    user = auth_module.get_current_user(request)
    if not user:
        return deps._login_redirect()
    return deps.templates.TemplateResponse(request, "setup.html", {"user": user})


@router.get("/catalog", response_class=HTMLResponse)
async def page_catalog(request: Request):
    user = auth_module.get_current_user(request)
    if not user:
        return deps._login_redirect()
    return deps.templates.TemplateResponse(request, "catalog.html", {"user": user})


@router.get("/settings", response_class=HTMLResponse)
async def page_settings(request: Request):
    user = auth_module.get_current_user(request)
    if not user:
        return deps._login_redirect()
    if not auth_module.require_role(user, "owner"):
        raise HTTPException(status_code=403, detail="Owner access required")
    return deps.templates.TemplateResponse(request, "settings.html", {"user": user})


@router.get("/payouts", response_class=HTMLResponse)
async def page_payouts(request: Request):
    """Where every service pays out (CashPilot-luj, tier 1).

    OWNER-ONLY, matching ``/api/payout-registry`` exactly. The page is useless
    without that endpoint, so a laxer gate here would only produce a screen that
    renders its own 403 — and it would advertise to a viewer that the owner's
    wallet map exists.
    """
    user = auth_module.get_current_user(request)
    if not user:
        return deps._login_redirect()
    if not auth_module.require_role(user, "owner"):
        raise HTTPException(status_code=403, detail="Owner access required")
    return deps.templates.TemplateResponse(request, "payouts.html", {"user": user})


@router.get("/fleet", response_class=HTMLResponse)
async def page_fleet(request: Request):
    user = auth_module.get_current_user(request)
    if not user:
        return deps._login_redirect()
    return deps.templates.TemplateResponse(request, "fleet.html", {"user": user})
