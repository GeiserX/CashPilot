"""Authentication utilities for CashPilot.

Session-based auth using signed cookies (itsdangerous) and bcrypt password hashing.
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from passlib.hash import bcrypt

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


def hash_password(password: str) -> str:
    # bcrypt enforces a 72-byte limit; truncate to avoid ValueError on strict backends
    return bcrypt.hash(password[:72])


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.verify(password[:72], hashed)


def create_session_token(user_id: int, username: str, role: str) -> str:
    return _serializer.dumps({"uid": user_id, "u": username, "r": role})


def decode_session_token(token: str) -> dict[str, Any] | None:
    try:
        return _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, Exception):
        return None


def get_current_user(request: Request) -> dict[str, Any] | None:
    """Extract user info from Bearer API key or session cookie.

    Checks Authorization header first (for programmatic access like Home Assistant),
    then falls back to session cookie (for browser sessions).
    """
    # Check Bearer token — admin key gets owner, fleet key gets writer
    auth_header = request.headers.get("Authorization", "")
    if auth_header:
        admin_key = os.getenv("CASHPILOT_ADMIN_API_KEY", "")
        if admin_key and auth_header == f"Bearer {admin_key}":
            return {"uid": 0, "u": "api", "r": "owner"}
        fleet_key = os.getenv("CASHPILOT_API_KEY", "")
        if fleet_key and auth_header == f"Bearer {fleet_key}":
            return {"uid": 0, "u": "api", "r": "writer"}

    # Fall back to session cookie
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return decode_session_token(token)


def set_session_cookie(response: RedirectResponse, token: str) -> RedirectResponse:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return response


def clear_session_cookie(response: RedirectResponse) -> RedirectResponse:
    response.delete_cookie(SESSION_COOKIE)
    return response


def require_role(user: dict[str, Any] | None, *roles: str) -> bool:
    """Check if user has one of the required roles."""
    if not user:
        return False
    return user.get("r") in roles
