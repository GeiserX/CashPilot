"""Login rate limiting (CashPilot-sux).

Lifted out of ``app.main`` because it was the last thing the routers genuinely
needed from it. Everything else they imported through ``app.main`` —
``templates``, ``client_ip``, the auth guards — already lives in ``app.deps``
and was only being re-exported, so moving this one module-level dict is what
actually breaks the ``main -> routers -> main`` import cycle rather than merely
moving it around.

The state stays a module-level dict on purpose, and ``app.main`` re-exports the
SAME object. Tests reach for ``app.main._login_attempts`` and a conftest fixture
clears it between tests; rebinding it here — or handing out a copy — would leave
those pointing at a dict nothing reads, and the fixture would silently stop
isolating tests from each other.
"""

from __future__ import annotations

from time import monotonic

from fastapi import HTTPException

# A plain dict, NOT a defaultdict, so a stale empty bucket never lingers. Every
# distinct client IP that ever hits /login would otherwise leave a permanent key
# behind once its attempts aged out, growing without bound for the life of the
# process — a slow leak that only shows up on a host exposed long enough to see
# a lot of addresses.
_login_attempts: dict[str, list[float]] = {}

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 300


def check_login_rate(ip: str) -> None:
    """Raise 429 when this address has failed too often, recently.

    Also prunes the bucket as a side effect, which is what keeps the dict from
    growing: entries are dropped the next time their address is seen, and an
    address that never returns leaves nothing that a later lookup would revive.
    """
    now = monotonic()
    attempts = [t for t in _login_attempts.get(ip, []) if now - t < WINDOW_SECONDS]
    if attempts:
        _login_attempts[ip] = attempts
    else:
        _login_attempts.pop(ip, None)
    if len(attempts) >= MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again in a few minutes.")


def record_failed_login(ip: str) -> None:
    """Count one failed attempt against this address."""
    _login_attempts.setdefault(ip, []).append(monotonic())


def clear(ip: str) -> None:
    """Forget an address's failures, after it successfully logs in."""
    _login_attempts.pop(ip, None)
