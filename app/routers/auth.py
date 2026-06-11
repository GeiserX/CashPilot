"""Authentication + onboarding routes (login, register, logout, onboarding).

Handlers reference shared state through ``app.main`` so test patches on
``app.main.database.*`` / ``app.main.auth.*`` continue to land.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app.main as main

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def page_login(request: Request, error: str = ""):
    # If no users exist, redirect to onboarding
    if not await main.database.has_any_users():
        return RedirectResponse("/onboarding", status_code=303)
    # If already logged in, go to dashboard
    if main.auth.get_current_user(request):
        return RedirectResponse("/", status_code=303)
    return main.templates.TemplateResponse(
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
    client_ip = request.client.host if request.client else "unknown"
    try:
        main._check_login_rate(client_ip)
    except HTTPException:
        main.metrics.record_rate_limit()
        raise
    user = await main.database.get_user_by_username(username)
    if not user or not main.auth.verify_password(password, user["password"]):
        main._record_failed_login(client_ip)
        main.metrics.record_login(success=False)
        return main.templates.TemplateResponse(
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

    main._login_attempts.pop(client_ip, None)
    main.metrics.record_login(success=True)
    token = main.auth.create_session_token(user["id"], user["username"], user["role"])
    response = RedirectResponse("/", status_code=303)
    return main.auth.set_session_cookie(response, token)


@router.get("/register", response_class=HTMLResponse)
async def page_register(request: Request, error: str = ""):
    is_first = not await main.database.has_any_users()
    # Only allow registration if first user OR if requester is owner
    if not is_first:
        user = main.auth.get_current_user(request)
        if not user or user.get("r") != "owner":
            return RedirectResponse("/login", status_code=303)
    if is_first:
        main._require_private_network(request)

    return main.templates.TemplateResponse(
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
):
    is_first = not await main.database.has_any_users()

    # Only allow registration if first user or owner
    if not is_first:
        user = main.auth.get_current_user(request)
        if not user or user.get("r") != "owner":
            raise HTTPException(status_code=403, detail="Only owners can add users")

    if is_first:
        main._require_private_network(request)

    if not re.match(r"^[a-zA-Z0-9_-]{3,32}$", username):
        return main.templates.TemplateResponse(
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
            },
            status_code=400,
        )

    if password != password_confirm:
        return main.templates.TemplateResponse(
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
            },
            status_code=400,
        )

    if len(password) < 10:
        return main.templates.TemplateResponse(
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
            },
            status_code=400,
        )

    existing = await main.database.get_user_by_username(username)
    if existing:
        return main.templates.TemplateResponse(
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
            },
            status_code=400,
        )

    # First user is always owner
    role = "owner" if is_first else "viewer"
    hashed = main.auth.hash_password(password)
    user_id = await main.database.create_user(username, hashed, role)

    token = main.auth.create_session_token(user_id, username, role)
    dest = "/setup" if is_first else "/"
    response = RedirectResponse(dest, status_code=303)
    return main.auth.set_session_cookie(response, token)


@router.get("/logout")
async def do_logout():
    response = RedirectResponse("/login", status_code=303)
    return main.auth.clear_session_cookie(response)


@router.get("/onboarding", response_class=HTMLResponse)
async def page_onboarding(request: Request):
    if await main.database.has_any_users():
        return RedirectResponse("/login", status_code=303)
    return main.templates.TemplateResponse(request, "onboarding.html")
