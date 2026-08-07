"""Authentication utilities for CashPilot.

Session-based auth using signed cookies (itsdangerous) and bcrypt password hashing.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any

import bcrypt as _bcrypt
from fastapi import Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadData, URLSafeTimedSerializer

from app import fleet_key as _fleet_key_mod

_logger = logging.getLogger(__name__)

_KNOWN_DEFAULTS = {
    "changeme-generate-a-random-secret",
    "changeme",
    "",
}


def _resolve_secret_key() -> str:
    """Return a cryptographically safe secret key.

    Priority:
    1. CASHPILOT_SECRET_KEY env var (if not a known default)
    2. Persisted key in <data_dir>/.secret_key
    3. Generate, persist, and return a new random key
    """
    env_key = os.getenv("CASHPILOT_SECRET_KEY", "")
    if env_key and env_key not in _KNOWN_DEFAULTS:
        return env_key

    if env_key in _KNOWN_DEFAULTS and env_key:
        _logger.warning(
            "CASHPILOT_SECRET_KEY is set to a known default — ignoring it. "
            "Set a strong random value or remove it to auto-generate."
        )

    # Try to read persisted key
    data_dir = Path(os.getenv("CASHPILOT_DATA_DIR", "/data"))
    key_file = data_dir / ".secret_key"
    try:
        if key_file.is_file():
            stored = key_file.read_text().strip()
            if stored and stored not in _KNOWN_DEFAULTS:
                return stored
    except OSError:
        pass

    # Generate and persist
    new_key = secrets.token_urlsafe(48)
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        key_file.write_text(new_key)
        key_file.chmod(0o600)
        _logger.info("Generated and persisted new secret key to %s", key_file)
    except OSError as exc:
        _logger.warning("Could not persist secret key to %s: %s", key_file, exc)

    return new_key


SECRET_KEY = _resolve_secret_key()
SESSION_COOKIE = "cashpilot_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

_serializer = URLSafeTimedSerializer(SECRET_KEY)

# Global session epoch: tokens issued before this timestamp are rejected.
# Bump via env var to mass-invalidate all sessions (e.g. after a credential leak).
_SESSION_EPOCH = float(os.getenv("CASHPILOT_SESSION_EPOCH", "0"))

# Per-user password-change epoch: tokens for a given uid issued before this
# timestamp are rejected, invalidating only that user's existing sessions
# (e.g. after a password change). Mirrors the global _SESSION_EPOCH pattern but
# scoped per uid. Warmed at startup from the DB and bumped by the
# password-change route. Read-only/in-memory in the request path (no DB call).
_USER_PWD_EPOCH: dict[int, float] = {}


def set_user_pwd_epoch(uid: int, changed_at: float) -> None:
    """Record the password-change epoch for a user.

    Tokens for ``uid`` with ``iat`` earlier than ``changed_at`` are rejected.
    """
    _USER_PWD_EPOCH[uid] = changed_at


def _user_pwd_epoch(uid: int) -> float:
    """Return the password-change epoch for ``uid`` (0.0 if unknown)."""
    return _USER_PWD_EPOCH.get(uid, 0.0)


def hash_password(password: str) -> str:
    # bcrypt enforces a 72-byte limit; truncate UTF-8 bytes (not characters)
    pw = password.encode("utf-8")[:72]
    return _bcrypt.hashpw(pw, _bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    pw = password.encode("utf-8")[:72]
    return _bcrypt.checkpw(pw, hashed.encode("ascii"))


async def hash_password_async(password: str) -> str:
    """bcrypt is CPU-bound (~200-500ms); run it off the event loop so a login or
    password change doesn't block every other request on the single uvicorn loop."""
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password: str, hashed: str) -> bool:
    return await asyncio.to_thread(verify_password, password, hashed)


def create_session_token(user_id: int, username: str, role: str) -> str:
    return _serializer.dumps({"uid": user_id, "u": username, "r": role, "iat": time.time()})


def decode_session_token(token: str) -> dict[str, Any] | None:
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except BadData as exc:
        # Expected token-decode failures: tampering, expiry, malformed signed
        # payload. BadData is the base class of BadSignature/SignatureExpired,
        # so this covers all legitimate "bad token -> not logged in" cases.
        # Any OTHER exception is an unexpected bug and is intentionally NOT
        # caught here, so it surfaces instead of masquerading as a logout.
        _logger.debug("session token rejected: %s", exc)
        return None
    # Reject tokens issued before session epoch (for mass invalidation)
    if data.get("iat", 0) < _SESSION_EPOCH:
        return None
    # Reject tokens issued before this user's password-change epoch (per-user
    # invalidation). In-memory lookup only — no DB call in the request path.
    uid = data.get("uid")
    if isinstance(uid, int) and data.get("iat", 0) < _user_pwd_epoch(uid):
        return None
    return data


def get_current_user(request: Request) -> dict[str, Any] | None:
    """Extract user info from Bearer API key or session cookie.

    Checks Authorization header first (for programmatic access like Home Assistant),
    then falls back to session cookie (for browser sessions).
    """
    # Check Bearer token — admin key gets owner, fleet key gets fleet (limited)
    auth_header = request.headers.get("Authorization", "")
    if auth_header:
        # Checked FIRST, before the admin key, deliberately. If an operator sets
        # both variables to the same value that is a misconfiguration either way,
        # and the two possible resolutions are not equally bad: resolving it to
        # "owner" would silently hand full container control to whatever they
        # pasted into a dashboard widget. Resolving it to "reader" merely stops
        # the admin path working, which is loud and harmless. Fail toward less
        # privilege.
        readonly_key = os.getenv("CASHPILOT_READONLY_API_KEY", "")
        if readonly_key and hmac.compare_digest(auth_header.encode(), f"Bearer {readonly_key}".encode()):
            return {"uid": 0, "u": "readonly", "r": "reader"}
        admin_key = os.getenv("CASHPILOT_ADMIN_API_KEY", "")
        if admin_key and hmac.compare_digest(auth_header.encode(), f"Bearer {admin_key}".encode()):
            return {"uid": 0, "u": "api", "r": "owner"}
        resolved_fleet_key = _fleet_key_mod.resolve_fleet_key()
        if resolved_fleet_key and hmac.compare_digest(auth_header.encode(), f"Bearer {resolved_fleet_key}".encode()):
            return {"uid": 0, "u": "fleet", "r": "fleet"}

    # Fall back to session cookie
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return decode_session_token(token)


_SECURE_COOKIE = os.getenv("CASHPILOT_SECURE_COOKIE", "auto").lower()

# Recognized explicit values for CASHPILOT_SECURE_COOKIE. Anything else --
# including the "auto" default and unrecognized values/typos -- falls back to
# the https-base-url auto-detect below rather than silently forcing Secure off.
_SECURE_COOKIE_TRUE = {"true", "1", "yes", "on"}
_SECURE_COOKIE_FALSE = {"false", "0", "no", "off"}

# Only trust an X-Forwarded-Proto header (to detect TLS terminated at a reverse proxy)
# when the operator opts in — matches app.deps._TRUST_PROXY; read here to avoid importing
# deps into auth (deps imports auth, so the reverse would be a cycle).
_TRUST_PROXY = os.getenv("CASHPILOT_TRUSTED_PROXY", "").strip().lower() in ("1", "true", "yes", "on")


def set_session_cookie(response: RedirectResponse, token: str, request=None) -> RedirectResponse:
    # Secure-flag precedence (highest wins):
    #   1. CASHPILOT_SECURE_COOKIE explicitly truthy -> Secure on
    #   2. CASHPILOT_SECURE_COOKIE explicitly falsy   -> Secure off (e.g. TLS is
    #      terminated by a reverse proxy this process can't see)
    #   3. Otherwise ("auto" / unset / unrecognized)  -> auto-detect: Secure on when
    #      CASHPILOT_BASE_URL starts with "https", OR (behind a trusted proxy) when the
    #      request arrived as https per X-Forwarded-Proto. This closes the common gap
    #      where TLS terminates at Caddy, the operator configures the domain there (not
    #      via CASHPILOT_BASE_URL), and the session cookie would otherwise ship non-Secure
    #      over the proxy hop. Never hardcoded on by default, so plain-HTTP local dev
    #      isn't broken by a Secure cookie the browser would silently refuse to send back.
    if _SECURE_COOKIE in _SECURE_COOKIE_TRUE:
        use_secure = True
    elif _SECURE_COOKIE in _SECURE_COOKIE_FALSE:
        use_secure = False
    else:
        use_secure = os.getenv("CASHPILOT_BASE_URL", "").startswith("https")
        if not use_secure and request is not None and _TRUST_PROXY:
            use_secure = request.headers.get("x-forwarded-proto", "").lower() == "https"
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=use_secure,
    )
    return response


def clear_session_cookie(response: RedirectResponse) -> RedirectResponse:
    response.delete_cookie(SESSION_COOKIE)
    return response


def require_role(user: dict[str, Any] | None, *roles: str) -> bool:
    """Check if user has one of the required roles."""
    if not user:
        return False
    role = user.get("r")
    # The fleet role deliberately does NOT satisfy writer.
    #
    # It used to, "for heartbeat/status endpoints" — but the heartbeat never
    # went through here. app/main.py::api_worker_heartbeat authenticates with
    # _authenticate_worker_heartbeat, so this granted nothing the workers
    # needed, while unlocking five user-facing routes for anyone holding the
    # shared key: payout confirm, payout REJECT (a hard DELETE), container
    # logs, collection, and arbitrary worker commands.
    #
    # That key is handed to every worker host by design — it is in each
    # worker's compose file and readable with `docker inspect` — so a second
    # machine in the fleet could permanently destroy the owner's payout
    # records with no login. Verified before removal: a bare
    # `Authorization: Bearer <fleet key>` POST to
    # /api/earnings/payouts/1/reject returned 200 and deleted the row, on a
    # server with no session at all.
    #
    # Automation that genuinely needs write access uses
    # CASHPILOT_ADMIN_API_KEY, which resolves to the owner role above and is
    # not distributed to workers.
    return role in roles
