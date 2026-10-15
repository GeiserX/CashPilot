"""Read the expiry a credential carries inside itself.

Several collectors run on a token copied out of a browser. Some of those are
JWTs, and a JWT states when it stops working (`exp`) and often when it was
issued (`iat`). Until now CashPilot only knew a credential's AGE (when it was
pasted) and a per-service guess at how long that kind of value lasts, so a token
that was already half-spent when pasted, or one whose provider changed its
lifetime, still read as fresh. The TraffMonetizer token did exactly that: a
7-day JWT recorded under "no known expiry", dead for two months before anyone
noticed.

This reads the claims only. It never validates the signature, never needs the
key, and returns nothing but two timestamps.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime


def jwt_times(value: str) -> tuple[datetime | None, datetime | None]:
    """Return ``(issued_at, expires_at)`` from a JWT's claims, or ``(None, None)``.

    Anything that is not three base64url segments with a JSON object in the
    middle, or whose ``exp`` is not a number, yields ``(None, None)``: an opaque
    cookie or an API key is simply a value with no readable expiry.
    """
    parts = value.strip().split(".")
    if len(parts) != 3 or not all(parts):
        return None, None
    payload = parts[1]
    try:
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None, None
    if not isinstance(claims, dict):
        return None, None

    def _stamp(key: str) -> datetime | None:
        number = claims.get(key)
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            return None
        try:
            return datetime.fromtimestamp(number, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None

    expires_at = _stamp("exp")
    if expires_at is None:
        return None, None
    return _stamp("iat"), expires_at
