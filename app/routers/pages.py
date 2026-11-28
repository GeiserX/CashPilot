"""Protected HTML page routes (dashboard, setup, catalog, settings, fleet).

Handlers reach shared state through ``app.deps``, ``app.auth`` and
``app.database`` directly — NOT through ``app.main``, which is what breaks the
``main -> routers -> main`` import cycle. Test patches therefore target
``app.auth.*`` / ``app.database.*``. ``app.auth`` is bound locally as
``auth_module`` only to avoid shadowing the route helpers.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth as auth_module
from app import database, deps, i18n, themes
from app.i18n import t

logger = logging.getLogger(__name__)

router = APIRouter()


async def _page(request: Request, template: str, user: dict) -> HTMLResponse:
    """Render a signed-in page with the user's saved theme and language.

    The server decides the theme of a signed-in page, so it paints right from the
    first frame on any browser, and a theme left in localStorage by whoever used
    this browser before never applies. Never chosen, or a value that is no
    longer a theme, means the default (app/themes.json).

    The saved language works the same way (app/i18n): it wins over the cookie
    and the browser's Accept-Language, and is copied into the cookie so the
    sign-in page and the API's messages match it. Never chosen means the cookie
    or the browser decides.
    """
    prefs = None
    try:
        prefs = await database.get_user_preferences(user["uid"])
    except Exception as exc:  # a preference read must never break a page
        logger.warning("Could not read the saved preferences, showing the defaults: %s", type(exc).__name__)
    theme = themes.resolve(prefs and prefs.get("theme"))
    saved_language = prefs.get("language") if prefs else None
    locale = i18n.from_request(request, saved_language)
    i18n.use(locale)
    if user.get("r") == "owner" and i18n.set_background(locale):
        # Alerts and pushes follow the owner's language, also after a restart.
        try:
            await database.set_config(i18n.BACKGROUND_KEY, locale)
        except Exception as exc:  # losing it only leaves the alerts in the old language
            logger.warning("Could not keep the owner's language for alerts: %s", type(exc).__name__)
    response = deps.templates.TemplateResponse(
        request,
        template,
        {"user": user, "saved_theme": theme, "saved_language": saved_language if saved_language == locale else None},
    )
    if saved_language == locale and request.cookies.get(i18n.COOKIE) != locale:
        response.set_cookie(i18n.COOKIE, locale, max_age=i18n.COOKIE_MAX_AGE, samesite="lax", path="/")
    return response


@router.get("/", response_class=HTMLResponse)
async def page_dashboard(request: Request):
    user = auth_module.get_current_user(request)
    if not user:
        if not await database.has_any_users():
            return RedirectResponse("/onboarding", status_code=303)
        return RedirectResponse("/login", status_code=303)
    return await _page(request, "dashboard.html", user)


@router.get("/setup", response_class=HTMLResponse)
async def page_setup(request: Request):
    user = auth_module.get_current_user(request)
    if not user:
        return deps._login_redirect()
    return await _page(request, "setup.html", user)


@router.get("/catalog", response_class=HTMLResponse)
async def page_catalog(request: Request):
    user = auth_module.get_current_user(request)
    if not user:
        return deps._login_redirect()
    return await _page(request, "catalog.html", user)


@router.get("/settings", response_class=HTMLResponse)
async def page_settings(request: Request):
    user = auth_module.get_current_user(request)
    if not user:
        return deps._login_redirect()
    if not auth_module.require_role(user, "owner"):
        raise HTTPException(status_code=403, detail=t("api.owner_access_required"))
    return await _page(request, "settings.html", user)


@router.get("/import", response_class=HTMLResponse)
async def page_import(request: Request):
    """Bring settings over from money4band, CashFactory or InternetIncome. Owner only, like its API."""
    user = auth_module.get_current_user(request)
    if not user:
        return deps._login_redirect()
    if not auth_module.require_role(user, "owner"):
        raise HTTPException(status_code=403, detail=t("api.owner_access_required"))
    return await _page(request, "import.html", user)


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
        raise HTTPException(status_code=403, detail=t("api.owner_access_required"))
    return await _page(request, "payouts.html", user)


@router.get("/activity", response_class=HTMLResponse)
async def page_activity(request: Request):
    """What each earner does on the network (docs/activity.md).

    OWNER-ONLY, like every /api/activity route: it shows metadata of other
    people's traffic and holds the switch that makes a worker start probes.
    """
    user = auth_module.get_current_user(request)
    if not user:
        return deps._login_redirect()
    if not auth_module.require_role(user, "owner"):
        raise HTTPException(status_code=403, detail=t("api.owner_access_required"))
    return await _page(request, "activity.html", user)


@router.get("/fleet", response_class=HTMLResponse)
async def page_fleet(request: Request):
    user = auth_module.get_current_user(request)
    if not user:
        return deps._login_redirect()
    return await _page(request, "fleet.html", user)
