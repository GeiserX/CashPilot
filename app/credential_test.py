"""Test these credentials, now (CashPilot-bfl).

A user pastes a token, saves, and then waits up to an hour for the scheduler to
tell them — via a notification bell — whether it was even valid. Most of the
support burden in this category is exactly that loop: a typo, a cookie that
expired between copying and pasting, an account that needs a captcha.

This runs ONE collector on demand and answers in a sentence.

Two things it must never do, both learned the hard way in this codebase:

* **Never echo the credential, or the provider's raw response body.** A failing
  login often replies with the submitted payload, and a raw body has previously
  leaked into logs from a worker error path. Errors are CLASSIFIED here and the
  original text is logged at debug only, never returned to the caller.
* **Never let the button become a hammer.** Repeatedly retrying a bad login is
  how providers flag an account, and this button invites exactly that. Attempts
  are rate-limited per service.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

OK = "ok"
BAD_CREDENTIALS = "bad_credentials"
NOT_CONFIGURED = "not_configured"
UNREACHABLE = "unreachable"
UNEXPECTED_SHAPE = "unexpected_shape"
RATE_LIMITED = "rate_limited"
UNSUPPORTED = "unsupported"

# One test per service per this many seconds. Generous enough to be useless as a
# brute-force tool, short enough that fixing a typo does not mean waiting.
COOLDOWN_SECONDS = 20.0

_last_attempt: dict[str, float] = {}

# Substrings that identify the failure without repeating anything sensitive.
_AUTH_MARKERS = ("401", "403", "unauthorized", "forbidden", "invalid credentials", "login failed", "bad credentials")
_NETWORK_MARKERS = ("timeout", "timed out", "connect", "dns", "network", "unreachable", "ssl", "certificate")
_SHAPE_MARKERS = ("keyerror", "no access_token", "not in", "expecting value", "jsondecode", "nonetype", "unexpected")


def classify(error: str | None) -> str:
    """Map a collector's error string to a stable, non-sensitive outcome."""
    if not error:
        return OK
    text = error.lower()
    if any(m in text for m in _AUTH_MARKERS):
        return BAD_CREDENTIALS
    if any(m in text for m in _NETWORK_MARKERS):
        return UNREACHABLE
    if "not configured" in text or "missing" in text:
        return NOT_CONFIGURED
    if any(m in text for m in _SHAPE_MARKERS):
        return UNEXPECTED_SHAPE
    return UNEXPECTED_SHAPE


def message(outcome: str, service_name: str, balance: float | None = None, currency: str = "") -> str:
    """A sentence the user can act on, containing nothing sensitive."""
    if outcome == OK:
        if balance is None:
            return f"{service_name} accepted these credentials."
        return (
            f"{service_name} accepted these credentials and reported a balance of {balance:g} {currency}".strip() + "."
        )
    if outcome == BAD_CREDENTIALS:
        return (
            f"{service_name} rejected these credentials. If they are a browser cookie or token, "
            "they have most likely expired — copy a fresh one and try again."
        )
    if outcome == NOT_CONFIGURED:
        return f"{service_name} has no credentials saved yet."
    if outcome == UNREACHABLE:
        return f"Could not reach {service_name}. That is a network problem here, not a problem with your credentials."
    if outcome == RATE_LIMITED:
        return (
            "Give it a few seconds before testing again — repeatedly retrying a bad login can get an account flagged."
        )
    if outcome == UNSUPPORTED:
        return f"CashPilot has no earnings collector for {service_name}, so there is nothing to test."
    return (
        f"{service_name} answered in a way CashPilot did not understand. The credentials may still be fine — "
        "this usually means the provider changed its API."
    )


def cooldown_remaining(slug: str, now: float | None = None) -> float:
    """Seconds left before ``slug`` may be tested again."""
    now = time.monotonic() if now is None else now
    last = _last_attempt.get(slug)
    if last is None:
        return 0.0
    return max(0.0, COOLDOWN_SECONDS - (now - last))


def note_attempt(slug: str, now: float | None = None) -> None:
    _last_attempt[slug] = time.monotonic() if now is None else now


def result(outcome: str, service_name: str, **extra: Any) -> dict[str, Any]:
    """The response body. Deliberately has no field that could carry a secret."""
    return {
        "ok": outcome == OK,
        "outcome": outcome,
        "message": message(outcome, service_name, extra.get("balance"), extra.get("currency", "")),
        **{k: v for k, v in extra.items() if k in {"balance", "currency"}},
    }
