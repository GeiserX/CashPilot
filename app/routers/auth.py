"""Authentication + onboarding routes (login, register, logout, onboarding).

Imports its dependencies directly from ``app.deps`` and friends rather than
reaching through ``app.main``. That is what removes the main -> routers -> main
import cycle (bead sux): everything these handlers used from ``app.main`` was
already a re-export of something in ``app.deps``, except the login rate limiter,
which now lives in ``app.login_rate_limit``.

Test patches on ``app.database.*`` and ``app.auth.*`` still land, because those
name the same module objects this module holds references to.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

# setup_token is aliased because it is ALSO a Form parameter name inside
# do_register, so importing it bare would be shadowed exactly where it is used.
from app import auth as auth_module
from app import database, deps, login_rate_limit, metrics
from app import setup_token as setup_token_module

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def page_login(request: Request, error: str = ""):
    # If no users exist, redirect to onboarding
    if not await database.has_any_users():
        return RedirectResponse("/onboarding", status_code=303)
    # If already logged in, go to dashboard
    if auth_module.get_current_user(request):
        return RedirectResponse("/", status_code=303)
    return deps.templates.TemplateResponse(
        request,
        "auth.html",
        {
            "title": "Sign In",
            "subtitle": "Sign in to your CashPilot instance",
            "mode": "login",
            "action": "/login",
            "button_text": "Sign In",
            "error": error,
            "is_first": False,
        },
    )


@router.post("/login")
async def do_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    client_ip = deps.client_ip(request) or "unknown"
    try:
        login_rate_limit.check_login_rate(client_ip)
    except HTTPException:
        metrics.record_rate_limit()
        raise
    user = await database.get_user_by_username(username)
    if not user or not await auth_module.verify_password_async(password, user["password"]):
        login_rate_limit.record_failed_login(client_ip)
        metrics.record_login(success=False)
        return deps.templates.TemplateResponse(
            request,
            "auth.html",
            {
                "title": "Sign In",
                "subtitle": "Sign in to your CashPilot instance",
                "mode": "login",
                "action": "/login",
                "button_text": "Sign In",
                "error": "Invalid username or password",
                "is_first": False,
            },
            status_code=401,
        )

    login_rate_limit.clear(client_ip)
    metrics.record_login(success=True)
    token = auth_module.create_session_token(user["id"], user["username"], user["role"])
    response = RedirectResponse("/", status_code=303)
    return auth_module.set_session_cookie(response, token, request)


@router.get("/register", response_class=HTMLResponse)
async def page_register(request: Request, error: str = ""):
    is_first = not await database.has_any_users()
    # Only allow registration if first user OR if requester is owner
    if not is_first:
        user = auth_module.get_current_user(request)
        if not user or user.get("r") != "owner":
            return RedirectResponse("/login", status_code=303)
    # The GET page is gated only by the network check so the operator can reach the
    # form; the setup token is entered into a form field and verified on POST (never
    # via URL, which would leak it into access logs / browser history).
    if is_first:
        deps._require_private_network(request)

    return deps.templates.TemplateResponse(
        request,
        "auth.html",
        {
            "title": "Create Account" if is_first else "Add User",
            "subtitle": "Create the first admin account" if is_first else "Add a new user to this instance",
            "mode": "register",
            "action": "/register",
            "button_text": "Create Account",
            "error": error,
            "is_first": is_first,
        },
    )


@router.post("/register")
async def do_register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    setup_token: str = Form(""),
):
    is_first = not await database.has_any_users()

    # Only allow registration if first user or owner
    if not is_first:
        user = auth_module.get_current_user(request)
        if not user or user.get("r") != "owner":
            raise HTTPException(status_code=403, detail="Only owners can add users")

    if is_first:
        deps._require_first_run_access(request, setup_token)

    if not re.match(r"^[a-zA-Z0-9_-]{3,32}$", username):
        return deps.templates.TemplateResponse(
            request,
            "auth.html",
            {
                "title": "Create Account" if is_first else "Add User",
                "subtitle": "Create the first admin account" if is_first else "Add a new user",
                "mode": "register",
                "action": "/register",
                "button_text": "Create Account",
                "error": "Username must be 3-32 alphanumeric characters (a-z, 0-9, _ -)",
                "is_first": is_first,
                "setup_token": setup_token if is_first else "",
            },
            status_code=400,
        )

    if password != password_confirm:
        return deps.templates.TemplateResponse(
            request,
            "auth.html",
            {
                "title": "Create Account" if is_first else "Add User",
                "subtitle": "Create the first admin account" if is_first else "Add a new user",
                "mode": "register",
                "action": "/register",
                "button_text": "Create Account",
                "error": "Passwords do not match",
                "is_first": is_first,
                "setup_token": setup_token if is_first else "",
            },
            status_code=400,
        )

    if len(password) < 10:
        return deps.templates.TemplateResponse(
            request,
            "auth.html",
            {
                "title": "Create Account" if is_first else "Add User",
                "subtitle": "Create the first admin account" if is_first else "Add a new user",
                "mode": "register",
                "action": "/register",
                "button_text": "Create Account",
                "error": "Password must be at least 10 characters",
                "is_first": is_first,
                "setup_token": setup_token if is_first else "",
            },
            status_code=400,
        )

    existing = await database.get_user_by_username(username)
    if existing:
        return deps.templates.TemplateResponse(
            request,
            "auth.html",
            {
                "title": "Create Account" if is_first else "Add User",
                "subtitle": "Create the first admin account" if is_first else "Add a new user",
                "mode": "register",
                "action": "/register",
                "button_text": "Create Account",
                "error": "Username already taken",
                "is_first": is_first,
                "setup_token": setup_token if is_first else "",
            },
            status_code=400,
        )

    # First user is always owner
    role = "owner" if is_first else "viewer"
    hashed = await auth_module.hash_password_async(password)
    if is_first:
        # Atomic: only one concurrent first-run registration can win, so a single
        # setup token can't be raced into minting two owners.
        user_id = await database.create_first_owner(username, hashed)
        if user_id is None:
            return deps.templates.TemplateResponse(
                request,
                "auth.html",
                {
                    "title": "Create Account",
                    "subtitle": "Create the first admin account",
                    "mode": "register",
                    "action": "/register",
                    "button_text": "Create Account",
                    "error": "An account already exists on this instance — please log in.",
                    "is_first": False,
                    "setup_token": "",
                },
                status_code=409,
            )
    else:
        user_id = await database.create_user(username, hashed, role)

    if is_first:
        # Owner now exists — retire the one-time setup token permanently.
        await database.delete_config_keys(["_setup_token"])
        setup_token_module.clear()

    if not is_first:
        # An owner adding a user must STAY the owner.
        #
        # This minted a session for the account just created and set it as the
        # caller's cookie, so an owner who added a viewer was silently demoted
        # into that viewer's session — losing their own access, with no sign
        # anything had happened beyond landing on the dashboard.
        #
        # Only the first-run owner gets signed in here, which is the case this
        # code was written for.
        return RedirectResponse("/users", status_code=303)

    token = auth_module.create_session_token(user_id, username, role)
    response = RedirectResponse("/setup", status_code=303)
    return auth_module.set_session_cookie(response, token, request)


@router.get("/logout")
async def do_logout():
    response = RedirectResponse("/login", status_code=303)
    return auth_module.clear_session_cookie(response)


@router.get("/onboarding", response_class=HTMLResponse)
async def page_onboarding(request: Request):
    if await database.has_any_users():
        return RedirectResponse("/login", status_code=303)
    return deps.templates.TemplateResponse(request, "onboarding.html")
