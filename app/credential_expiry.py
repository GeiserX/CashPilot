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
from typing import Any


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


def report(
    updated: dict[str, str],
    values: dict[str, Any],
    rejected: set[str],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """How old each stored credential is and when it is expected to die.

    ``updated`` maps ``<slug>_<field>`` to the paste time, ``values`` holds the
    decrypted values so a JWT's own expiry can be read, and ``rejected`` names
    the services whose last collection the provider refused. The rows carry
    dates and verdicts, never a value. Shared by ``/api/credentials/health``
    and the reminders (app/obligations.py), so the two never disagree.
    """
    from app.collectors import _COLLECTOR_ARGS, credential_lifetime, durable_alternative

    now = now or datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for slug, args in _COLLECTOR_ARGS.items():
        missing_durable = [field for field in durable_alternative(slug) if f"{slug}_{field}" not in updated]
        for arg in args:
            field = arg.lstrip("?")
            key = f"{slug}_{field}"
            stamp = updated.get(key)
            if not stamp:
                continue  # not configured; nothing to report an age for

            meta = credential_lifetime(slug, field) or {}
            hours_total = meta.get("hours")
            try:
                age_hours = (now - datetime.fromisoformat(stamp).replace(tzinfo=UTC)).total_seconds() / 3600
            except ValueError:
                continue

            if hours_total is None:
                status = "no_known_expiry"
            elif age_hours >= hours_total:
                status = "likely_expired"
            elif age_hours >= hours_total * 0.75:
                status = "expiring_soon"
            else:
                status = "fresh"

            # A JWT says when it dies. That beats both the paste date and the
            # per-service guess: a token pasted half-spent, or one the provider
            # now issues for 7 days instead of a year, is judged on its own
            # claim. The 25% window mirrors the age-based one; 48 h is the floor
            # so a short token still gets a warning a human can act on.
            issued_at, expires_at = jwt_times(str(values.get(key) or ""))
            if expires_at is not None:
                remaining_hours = (expires_at - now).total_seconds() / 3600
                span_hours = (
                    (expires_at - issued_at).total_seconds() / 3600
                    if issued_at is not None and expires_at > issued_at
                    else None
                )
                warn_hours = max(48.0, span_hours * 0.25) if span_hours else 48.0
                if remaining_hours <= 0:
                    status = "likely_expired"
                elif remaining_hours <= warn_hours:
                    status = "expiring_soon"
                else:
                    status = "fresh"
                if span_hours:
                    hours_total = round(span_hours)

            # A short-lived credential backed by its durable alternative is
            # re-established on every run (Bytelixir's 2 h session cookie by the
            # year-long remember-me cookie), so its own age says nothing.
            # Its lifetime and its "dies this afternoon" reason would then
            # contradict the calm status, so the row explains the cover instead.
            # Assumes every durable field of a service re-creates its
            # short-lived ones; true for Bytelixir, check it for the next one.
            why = meta.get("why")
            covered = bool(durable_alternative(slug)) and not missing_durable and not meta.get("durable")
            if covered and expires_at is None:
                status = "no_known_expiry"
                hours_total = None
                why = (
                    "Short-lived on its own, but re-created on every run from the saved "
                    + " and ".join(durable_alternative(slug))
                    + ", so its age does not matter."
                )

            if slug in rejected:
                status = "likely_expired"
                # The age-based reason (or "its age does not matter") would
                # contradict the status; the refusal is the reason now.
                why = (
                    "The provider rejected the saved credentials on the last run, "
                    "so they need replacing whatever their age."
                )

            entry: dict[str, Any] = {
                "service": slug,
                "field": field,
                "age_hours": round(age_hours, 1),
                "expected_lifetime_hours": hours_total,
                "status": status,
            }
            if expires_at is not None:
                entry["expires_at"] = expires_at.isoformat()
            if why:
                entry["why"] = why
            # Only nag about a durable alternative when the short-lived credential
            # is the one actually at risk.
            if missing_durable and hours_total is not None and not meta.get("durable"):
                entry["durable_alternative_missing"] = missing_durable
            rows.append(entry)
    return rows
