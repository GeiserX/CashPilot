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
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

OK = "ok"
BAD_CREDENTIALS = "bad_credentials"
NOT_CONFIGURED = "not_configured"
UNREACHABLE = "unreachable"
UNEXPECTED_SHAPE = "unexpected_shape"
RATE_LIMITED = "rate_limited"
# The PROVIDER refused to answer for now. RATE_LIMITED above is CashPilot's own
# cooldown on this button; this one is the provider's.
PROVIDER_RATE_LIMITED = "provider_rate_limited"
# The provider answered with a server error (5xx): its problem, not the credentials'.
PROVIDER_DOWN = "provider_down"
UNSUPPORTED = "unsupported"
ACCOUNT_DISABLED = "account_disabled"

# One test per service per this many seconds. Generous enough to be useless as a
# brute-force tool, short enough that fixing a typo does not mean waiting.
COOLDOWN_SECONDS = 20.0

_last_attempt: dict[str, float] = {}

# Substrings that identify the failure without repeating anything sensitive.
# The text is only the fallback: a collector's own error_kind wins (see classify).
_AUTH_MARKERS = (
    "401",
    "403",
    "unauthorized",
    "forbidden",
    "invalid credentials",
    "login failed",
    "bad credentials",
    # "Authentication failed", "Auth token rejected", "Token rejected",
    # "Session expired", "Auth cookie expired" from the collectors themselves.
    "authentication failed",
    "rejected",
    "session expired",
    "token expired",
    "cookie expired",
)
# Checked BEFORE the auth words: httpx's "[SSL: CERTIFICATE_VERIFY_FAILED] ...
# certificate has expired" is the connection failing, not the credentials. Only
# the TLS error's own text moves up: a bare "ssl" or "certificate", like the
# rest of the network words, can appear in a provider URL inside a plain 401.
_TLS_MARKERS = ("[ssl:", "certificate verify failed", "ssl handshake")
_NETWORK_MARKERS = (
    "timeout",
    "timed out",
    "connect",
    "dns",
    "network",
    "unreachable",
    "not reachable",
    "ssl",
    "certificate",
)
# httpx's raise_for_status text for a 5xx: "Server error '503 Service Unavailable'".
_SERVER_ERROR_MARKERS = ("server error", "service unavailable", "bad gateway", "gateway time")
# "rate-limited the login" (IPRoyal/Pawns), "Cloudflare rate limit" (Grass),
# httpx's "429 Too Many Requests" from raise_for_status.
_RATE_LIMIT_MARKERS = ("rate-limit", "rate limit", "too many requests", "throttl")
_SHAPE_MARKERS = (
    "keyerror",
    "no access_token",
    "not in",
    "expecting value",
    "jsondecode",
    "nonetype",
    "unexpected",
    # "usd_cents field missing — API shape may have changed": checked before the
    # not-configured test, whose "missing" would otherwise claim it.
    "shape",
    "structure",
    "field missing",
)
_NOT_CONFIGURED = re.compile(r"not configured|\bno\b.*\bconfigured\b|missing")

# The collectors' own failure marks (app.collectors.base.KIND_*). Kept as
# strings so this module imports nothing from the collectors.
_KIND_AUTH = "auth"
_KIND_TRANSIENT = "transient"
_KIND_SHAPE = "shape"
_KIND_UNREAD = "unread"


def classify(error: str | None, kind: str | None = None) -> str:
    """Map a collector's error to a stable, non-sensitive outcome.

    ``kind`` is the collector's own mark (EarningsResult.error_kind). It is
    evidence where the text is a guess, so it decides before the text does,
    except for the two messages more specific than any kind: a disabled account
    (not a bad password) and a rate limit (transient, but "try later" is the
    useful sentence).
    """
    if not error:
        return OK
    text = error.lower()
    # A disabled account is not a bad password, and its message may also
    # mention the 401 that led to the re-login.
    if "account disabled" in text:
        return ACCOUNT_DISABLED
    # A refused-for-now request says nothing about whether the credentials are right.
    if any(m in text for m in _RATE_LIMIT_MARKERS):
        return PROVIDER_RATE_LIMITED
    if kind == _KIND_AUTH:
        return BAD_CREDENTIALS
    # The provider accepted the login; only the figure could not be read.
    if kind == _KIND_UNREAD:
        return OK
    if kind == _KIND_SHAPE:
        return UNEXPECTED_SHAPE
    if any(m in text for m in _SERVER_ERROR_MARKERS):
        return PROVIDER_DOWN
    if kind == _KIND_TRANSIENT:
        return UNREACHABLE
    if any(m in text for m in _TLS_MARKERS):
        return UNREACHABLE
    if any(m in text for m in _AUTH_MARKERS):
        return BAD_CREDENTIALS
    if any(m in text for m in _NETWORK_MARKERS):
        return UNREACHABLE
    if any(m in text for m in _SHAPE_MARKERS):
        return UNEXPECTED_SHAPE
    if _NOT_CONFIGURED.search(text):
        return NOT_CONFIGURED
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
    if outcome == ACCOUNT_DISABLED:
        return (
            f"{service_name} has disabled this account. The credentials are fine; "
            f"only {service_name} support can re-enable it."
        )
    if outcome == NOT_CONFIGURED:
        return f"{service_name} has no credentials saved yet."
    if outcome == UNREACHABLE:
        return f"Could not reach {service_name}. That is a network problem here, not a problem with your credentials."
    if outcome == RATE_LIMITED:
        return (
            "Give it a few seconds before testing again — repeatedly retrying a bad login can get an account flagged."
        )
    if outcome == PROVIDER_RATE_LIMITED:
        return (
            f"{service_name} is rate-limiting requests right now, so it could not check these credentials. "
            "Try again later."
        )
    if outcome == PROVIDER_DOWN:
        return (
            f"{service_name} is having trouble right now (it answered with a server error), "
            "so it could not check these credentials. Try again later."
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
