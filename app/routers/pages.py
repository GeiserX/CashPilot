"""Protected HTML page routes (dashboard, setup, catalog, settings, fleet).

Handlers reference shared state through ``app.main`` so test patches on
``app.main.auth.*`` / ``app.main.database.*`` continue to land.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app.main as main

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def page_dashboard(request: Request):
    user = main.auth.get_current_user(request)
    if not user:
        if not await main.database.has_any_users():
            return RedirectResponse("/onboarding", status_code=303)
        return RedirectResponse("/login", status_code=303)
    return main.templates.TemplateResponse(request, "dashboard.html", {"user": user})


@router.get("/setup", response_class=HTMLResponse)
async def page_setup(request: Request):
    user = main.auth.get_current_user(request)
    if not user:
        return main._login_redirect()
    return main.templates.TemplateResponse(request, "setup.html", {"user": user})


@router.get("/catalog", response_class=HTMLResponse)
async def page_catalog(request: Request):
    user = main.auth.get_current_user(request)
    if not user:
        return main._login_redirect()
    return main.templates.TemplateResponse(request, "catalog.html", {"user": user})


@router.get("/settings", response_class=HTMLResponse)
async def page_settings(request: Request):
    user = main.auth.get_current_user(request)
    if not user:
        return main._login_redirect()
    if not main.auth.require_role(user, "owner"):
        raise HTTPException(status_code=403, detail="Owner access required")
    return main.templates.TemplateResponse(request, "settings.html", {"user": user})


@router.get("/fleet", response_class=HTMLResponse)
async def page_fleet(request: Request):
    user = main.auth.get_current_user(request)
    if not user:
        return main._login_redirect()
    return main.templates.TemplateResponse(request, "fleet.html", {"user": user})
