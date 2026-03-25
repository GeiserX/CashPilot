"""Authentication utilities for CashPilot.

Session-based auth using signed cookies (itsdangerous) and bcrypt password hashing.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from passlib.hash import bcrypt

SECRET_KEY = os.getenv("CASHPILOT_SECRET_KEY", "changeme-generate-a-random-secret")
SESSION_COOKIE = "cashpilot_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

_serializer = URLSafeTimedSerializer(SECRET_KEY)


def hash_password(password: str) -> str:
    return bcrypt.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.verify(password, hashed)


def create_session_token(user_id: int, username: str, role: str) -> str:
    return _serializer.dumps({"uid": user_id, "u": username, "r": role})


def decode_session_token(token: str) -> dict[str, Any] | None:
    try:
        return _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, Exception):
        return None


def get_current_user(request: Request) -> dict[str, Any] | None:
    """Extract user info from session cookie. Returns None if not authenticated."""
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
