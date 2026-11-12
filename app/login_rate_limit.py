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
# distinct key that ever hits /login would otherwise leave a permanent entry
# behind once its attempts aged out. Pruning on lookup only covers keys that come
# back, so _sweep() also drops stale keys once per window and caps the total.
#
# /login keys a bucket by (client IP, username), see key_for(). An IP-only bucket
# let one account's successful login reset the counter for every other account
# on that IP, and let anyone behind the same proxy lock the owner out.
_login_attempts: dict[str, list[float]] = {}

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 300
# Upper bound on tracked buckets. Past it the stale ones go first, then the
# least recently used, so memory stays bounded under a flood of usernames.
MAX_TRACKED_KEYS = 10_000
# Usernames are 3-32 characters; anything longer is cut so a key stays small.
_MAX_USERNAME_IN_KEY = 64

_last_sweep = 0.0


def key_for(ip: str, username: str) -> str:
    """The bucket key for one login attempt: client IP plus the username tried."""
    return f"{ip}\x00{username[:_MAX_USERNAME_IN_KEY]}"


def _sweep(now: float) -> None:
    """Drop stale buckets once per window, and the oldest ones past the cap."""
    global _last_sweep
    if len(_login_attempts) < MAX_TRACKED_KEYS and now - _last_sweep < WINDOW_SECONDS:
        return
    _last_sweep = now
    for key in [k for k, v in _login_attempts.items() if not v or now - v[-1] >= WINDOW_SECONDS]:
        del _login_attempts[key]
    excess = len(_login_attempts) - MAX_TRACKED_KEYS
    if excess >= 0:
        # Evict down to 90% of the cap, so a sustained flood does not sort on every call.
        excess += MAX_TRACKED_KEYS // 10
        for key in sorted(_login_attempts, key=lambda k: _login_attempts[k][-1])[:excess]:
            del _login_attempts[key]


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


def reserve_attempt(key: str) -> None:
    """Count one login attempt BEFORE the password is checked.

    Raises 429 when the key is already at the limit. The check and the append
    run with no await between them, so concurrent requests cannot all pass the
    check before any of them is counted: the 6th request in a parallel burst is
    refused, not only the next batch. A successful login calls clear(key).
    """
    _sweep(monotonic())
    check_login_rate(key)
    record_failed_login(key)


def record_failed_login(ip: str) -> None:
    """Count one failed attempt against this address."""
    _login_attempts.setdefault(ip, []).append(monotonic())


def clear(ip: str) -> None:
    """Forget an address's failures, after it successfully logs in."""
    _login_attempts.pop(ip, None)
