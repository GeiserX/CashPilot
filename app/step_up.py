"""Password step-up: the owner re-enters their password before one sensitive action.

A signed-in session is not enough for an action that can take or destroy
something that cannot be recovered (a wallet, a node identity). A stolen
session cookie, or the ``CASHPILOT_ADMIN_API_KEY`` pasted into some dashboard,
must not be able to do it alone. So such an action asks for the password again,
and the worker that carries it out checks a short-lived approval the UI signs
only after that password check.

Two halves, one module, so the UI and the worker cannot drift apart:

* ``app.deps.require_step_up`` runs on the UI. It checks that the caller is a
  signed-in owner (never an API key: uid 0 has no password to re-enter), counts
  the try against the login rate limit, checks the password and writes an
  audit row.
* :func:`sign` and :func:`check` are the approval the worker verifies. It is an
  HMAC over the action, the target, an expiry and a nonce, keyed with this
  worker's own per-worker key. Only the UI and that worker hold that key: the
  shared fleet key an owner can reveal is not it, and a worker still on the
  shared key accepts no approval at all. :func:`check` refuses an approval that
  has expired, that names another action or target, or that was already used.

How a later feature uses it (backup export, restore, a route switch): pick an
action name, build the target string from what the action touches, call
``await deps.require_step_up(request, password, action=..., target=...)`` in the
UI route, and when a worker carries the action out, send it ``sign(key, action,
target)`` and have the worker call ``check``. This module is stdlib only, so the
worker image (Dockerfile.worker) carries it without any UI module.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from typing import Any

#: Deploying an image other than the catalog's on a service that keeps
#: irreplaceable state (``critical_volumes`` in its YAML). Target: ``slug|image``.
ACTION_CUSTOM_IMAGE = "deploy-custom-image"

#: How long an approval stays valid. Long enough for a slow pull before the
#: worker checks it (the check runs before the pull), short enough that one seen
#: in a log is useless soon after. The UI and the worker clocks must agree to
#: within this much.
APPROVAL_TTL_SECONDS = 300

#: An approval claiming to live longer than this is refused whatever its
#: signature: nothing in this codebase mints one that long.
_MAX_TTL_SECONDS = 900

# Domain separation: the approval key is derived from the worker key, never the
# key itself, so an approval can never be replayed as a bearer token or the other
# way round.
_KEY_LABEL = b"cashpilot-step-up-v1"


class StepUpError(Exception):
    """An approval that must not be honoured. The message is safe to show."""


def _derive(worker_key: str) -> bytes:
    return hmac.new(worker_key.encode(), _KEY_LABEL, hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(worker_key: str, action: str, target: str, ttl: int = APPROVAL_TTL_SECONDS, now: float | None = None) -> str:
    """An approval for one ``action`` on one ``target``, for the worker holding ``worker_key``."""
    if not worker_key:
        raise StepUpError("No per-worker key to sign the approval with")
    issued = int(now if now is not None else time.time())
    payload = {"a": action, "t": target, "exp": issued + int(ttl), "n": secrets.token_hex(16)}
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    mac = hmac.new(_derive(worker_key), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{mac}"


# Nonces of approvals already honoured, with their expiry, so one approval
# carries one action. In memory only: a worker restart forgets them, and an
# approval lives minutes, so the window that opens is a restart inside those
# minutes by someone who already saw the approval on the wire.
_used: dict[str, int] = {}
_used_lock = threading.Lock()


def check(worker_key: str | None, token: str | None, action: str, target: str, now: float | None = None) -> None:
    """Raise :class:`StepUpError` unless ``token`` approves ``action`` on ``target`` right now."""
    if not worker_key:
        raise StepUpError(
            "This worker is still on the shared fleet key, so it cannot check a password confirmation. "
            "Let it finish enrolling (one heartbeat), then try again."
        )
    if not token or not isinstance(token, str) or token.count(".") != 1:
        raise StepUpError("The password confirmation is missing or malformed")
    body, mac = token.split(".")
    expected = hmac.new(_derive(worker_key), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected):
        raise StepUpError("The password confirmation was not signed by this worker's UI")
    try:
        payload: Any = json.loads(_unb64(body))
    except (ValueError, UnicodeDecodeError):
        raise StepUpError("The password confirmation is malformed") from None
    if not isinstance(payload, dict):
        raise StepUpError("The password confirmation is malformed")
    current = int(now if now is not None else time.time())
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp <= current:
        raise StepUpError("The password confirmation has expired; confirm again")
    if exp - current > _MAX_TTL_SECONDS:
        raise StepUpError("The password confirmation claims too long a life")
    if payload.get("a") != action or payload.get("t") != target:
        raise StepUpError("The password confirmation was given for another action")
    nonce = payload.get("n")
    if not isinstance(nonce, str) or not nonce:
        raise StepUpError("The password confirmation is malformed")
    with _used_lock:
        for seen in [n for n, until in _used.items() if until <= current]:
            del _used[seen]
        if nonce in _used:
            raise StepUpError("The password confirmation was already used; confirm again")
        _used[nonce] = exp
