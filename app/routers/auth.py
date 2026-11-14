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

import logging
import re
import secrets
import time

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

# setup_token is aliased because it is ALSO a Form parameter name inside
# do_register, so importing it bare would be shadowed exactly where it is used.
from app import auth as auth_module
from app import captcha, database, deps, login_rate_limit, metrics
from app import setup_token as setup_token_module
from app.users import USERNAME_PATTERN

logger = logging.getLogger(__name__)

router = APIRouter()

# Checked against when the username does not exist, so an unknown name costs the
# same bcrypt run as a wrong password and the response time does not tell an
# outsider which usernames are real.
_DUMMY_HASH = auth_module.hash_password(secrets.token_urlsafe(16))


async def _rearm_setup_token() -> None:
    """Fail closed when first-run registration has no active setup token.

    Startup arms the token only when no users exist at that moment. If the users
    table empties while the app runs, no token is active, and without this the
    private-network check would be the only gate on creating an owner. So arm a
    new token, write it to the log the way startup does, and refuse this request.
    No await sits between the check and the set, so two requests cannot both
    arm a token.

    If the save fails, the token is dropped, because nobody could read it.
    After the save, check for users again: a concurrent request may have created
    the owner and cleared the token before this one armed it. Then drop the token
    and refuse without a log line.
    """
    if setup_token_module.active() is not None:
        return
    tok = setup_token_module.generate()
    setup_token_module.set_active(tok)
    try:
        await database.set_config("_setup_token", tok)
        owner_exists = await database.has_any_users()
    except Exception:
        setup_token_module.clear()
        raise
    if owner_exists:
        setup_token_module.clear()
        await database.delete_config_keys(["_setup_token"])
        raise HTTPException(status_code=409, detail="An account already exists on this instance. Please log in.")
    logger.warning(
        "FIRST-RUN SETUP: no account exists. Open /register and enter this one-time setup token to create the owner account: %s",
        tok,
    )
    raise HTTPException(status_code=403, detail="A setup token was just written to the container log.")


_CAPTCHA_ERRORS = {
    "missing": "Complete the CAPTCHA check and try again.",
    "rejected": "Complete the CAPTCHA check and try again.",
    "unavailable": "The CAPTCHA check could not be completed. Try again in a moment.",
}


def _login_page(request: Request, error: str = "", status_code: int = 200):
    """The sign-in page, with the CAPTCHA widget when one is configured.

    Setting ``request.state.captcha`` is what tells the security-headers
    middleware to widen this one response's CSP to the provider's origins.
    """
    cfg = captcha.config()
    if cfg is not None:
        request.state.captcha = cfg
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
            "captcha": cfg,
        },
        status_code=status_code,
    )


@router.get("/login", response_class=HTMLResponse)
async def page_login(request: Request):
    # If no users exist, redirect to onboarding
    if not await database.has_any_users():
        return RedirectResponse("/onboarding", status_code=303)
    # If already logged in, go to dashboard
    if auth_module.get_current_user(request):
        return RedirectResponse("/", status_code=303)
    return _login_page(request)


@router.post("/login")
async def do_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    client_ip = deps.client_ip(request) or "unknown"
    # One bucket per (IP, username), and the attempt is counted before the
    # password check: a success then clears only its own bucket, a parallel
    # burst cannot slip past the limit, and failures against one account never
    # lock out another account on the same IP (or behind the same proxy). A
    # looser per-IP budget on top stops one client from rotating usernames to
    # get unlimited guesses and bcrypt runs.
    rate_key = login_rate_limit.key_for(client_ip, username)
    try:
        login_rate_limit.reserve_attempt(rate_key, ip=client_ip)
    except HTTPException:
        metrics.record_rate_limit()
        raise
    # The CAPTCHA after the rate limit, so a flood cannot make this server call
    # the provider without limit, and before the password, so a bot that did
    # not solve it never costs a bcrypt run. A failure stays counted as an
    # attempt: the bucket is cleared only by a successful sign-in.
    if captcha.required():
        cfg = captcha.config()
        form = await request.form()
        token = form.get(cfg.provider.response_field) if cfg is not None else None
        result = await captcha.verify(token if isinstance(token, str) else None, deps.client_ip(request))
        if not result.ok:
            metrics.record_login(success=False)
            metrics.record_captcha_failure(result.reason)
            return _login_page(request, error=_CAPTCHA_ERRORS[result.reason], status_code=400)
    user = await database.get_user_by_username(username)
    if user:
        ok = await auth_module.verify_password_async(password, user["password"])
    else:
        await auth_module.verify_password_async(password, _DUMMY_HASH)
        ok = False
    if not ok:
        metrics.record_login(success=False)
        return _login_page(request, error="Invalid username or password", status_code=401)

    login_rate_limit.clear(rate_key)
    metrics.record_login(success=True)
    token = auth_module.create_session_token(user["id"], user["username"], user["role"])
    response = RedirectResponse("/", status_code=303)
    return auth_module.set_session_cookie(response, token, request)


@router.get("/register", response_class=HTMLResponse)
async def page_register(request: Request):
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
            "error": "",
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
        deps._require_private_network(request)
        await _rearm_setup_token()
        deps._require_first_run_access(request, setup_token)

    if not re.fullmatch(USERNAME_PATTERN, username):
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
        # There is no users page, so the form returns to Settings (/users was a 404).
        return RedirectResponse("/settings", status_code=303)

    token = auth_module.create_session_token(user_id, username, role)
    response = RedirectResponse("/setup", status_code=303)
    return auth_module.set_session_cookie(response, token, request)


@router.post("/logout")
async def do_logout(request: Request):
    """Sign out, and end the session on the server too.

    Deleting the cookie alone left a copied cookie valid for its full 30 days.
    The token carries no per-session id, so this revokes every session of the
    user issued up to now, through the same durable per-user epoch a role change
    uses. That signs the user out on every device.

    POST, not GET: a GET let any cross-site link or redirect sign a user out.
    """
    user = auth_module.get_current_user(request)
    if user and isinstance(user.get("uid"), int) and user["uid"] > 0:
        revoked_at = time.time()
        await database.revoke_user_sessions(user["uid"], revoked_at)
        auth_module.set_user_pwd_epoch(user["uid"], revoked_at)
    response = RedirectResponse("/login", status_code=303)
    return auth_module.clear_session_cookie(response)


@router.get("/onboarding", response_class=HTMLResponse)
async def page_onboarding(request: Request):
    if await database.has_any_users():
        return RedirectResponse("/login", status_code=303)
    return deps.templates.TemplateResponse(request, "onboarding.html")
