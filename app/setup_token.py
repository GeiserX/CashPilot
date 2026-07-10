"""First-run setup-token gate.

The very first account created on a fresh install becomes the ``owner``. The
private-network check in :mod:`app.deps` is not enough on its own: behind a
reverse proxy ``request.client`` is the *proxy* (a loopback/private address), so
the network check always passes and the first person to reach ``/register`` from
the public internet could seize the owner account.

This module adds a proxy-independent second factor: a one-time token generated at
startup while no users exist, printed to the container logs. Only someone who can
read the server logs (i.e. already has host access) can complete first-run setup.
Once the owner account is created the token is cleared and never required again
(further users are added by an authenticated owner).

The active token is held in a module global so the synchronous request guard can
check it without a DB round-trip; it is also persisted in the ``config`` table so
it survives restarts until consumed.
"""

from __future__ import annotations

import hmac
import secrets

# The token currently required for first-run registration, or ``None`` when no
# first-run gate is active (owner already exists, or not yet initialised).
_active: str | None = None


def generate() -> str:
    """Return a fresh, URL-safe setup token."""
    return secrets.token_urlsafe(24)


def set_active(token: str | None) -> None:
    """Install (or clear, with ``None``) the token required for first-run setup."""
    global _active
    _active = token or None


def clear() -> None:
    """Drop the first-run gate — called once the owner account exists."""
    set_active(None)


def active() -> str | None:
    """Return the currently required setup token, or ``None`` if none is active."""
    return _active


def verify(provided: str | None) -> bool:
    """Check a caller-supplied token against the active one.

    Returns ``True`` when no token is active (nothing to enforce) or when the
    supplied value matches in constant time; ``False`` otherwise.
    """
    current = _active
    if current is None:
        return True
    if not provided:
        return False
    return hmac.compare_digest(current, provided)
