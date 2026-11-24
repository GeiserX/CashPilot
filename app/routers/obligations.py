"""Money waiting API: the reminders before a provider writes off earnings.

``GET /api/obligations`` (reader and up) returns what is due now, for the
dashboard panel; credential reminders go to owners only. ``POST /api/obligations/{slug}/{rule}`` (writer and up) marks
one done, snoozes it, or mutes it ("Not for me"), the same rights as answering
a payout question; a credential reminder takes the owner. Every write leaves an audit row, so the household can see
who closed what. The engine is app/obligations.py and docs/reminders.md says
what each reminder means.

No module may import main (tests/test_login_rate_limit.py), and the
evaluation reads main's worker and alert state, so main hands it in as
``evaluate``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import auth, catalog, database, deps, obligations

router = APIRouter()
logger = logging.getLogger(__name__)

#: Set by app.main: returns the evaluation and the local "now" it used.
evaluate: Callable[[], Awaitable[tuple[obligations.Evaluation, datetime]]] | None = None

ACTIONS = ("done", "snooze", "mute", "unmute")
SNOOZE_DAYS = (1, 7)


class ObligationAction(BaseModel):
    action: str
    days: int | None = None
    occurrence: str | None = None


async def _evaluate() -> tuple[obligations.Evaluation, datetime]:
    if evaluate is None:
        raise HTTPException(status_code=503, detail="Could not check")
    try:
        return await evaluate()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - "could not check" is never an all-clear
        logger.warning("Reminders: could not evaluate: %s", exc)
        raise HTTPException(status_code=503, detail="Could not check")


@router.get("/api/obligations")
async def api_obligations(request: Request) -> dict[str, Any]:
    user = deps._require_reader(request)
    evaluation, now = await _evaluate()
    # Credential health is the owner's, as on /api/credentials/health and in
    # Needs attention. The push job reads the evaluation itself, not this.
    owner = auth.require_role(user, "owner")
    return {
        "evaluated_at": now.isoformat(),
        "items": [item.as_dict() for item in evaluation.items if owner or item.kind != "credential"],
        "muted": [m for m in evaluation.muted if owner or not m["rule"].startswith(obligations.CREDENTIAL_PREFIX)],
    }


def _known_rule(slug: str, rule: str) -> bool:
    svc = catalog.get_service(slug)
    if not svc or svc.get("status") == "dead":
        return False
    if rule in (obligations.WHOLE_SERVICE, obligations.CASH_OUT):
        return True
    if rule.startswith(obligations.CREDENTIAL_PREFIX):
        return bool(rule.removeprefix(obligations.CREDENTIAL_PREFIX))
    return any(r.get("id") == rule for r in svc.get("obligations") or [])


async def _done_for(slug: str, rule: str, occurrence: str, today: date) -> str:
    """The ``done_for`` value once ``occurrence`` is marked done.

    A date or monthly rule keeps every occurrence already done that is still
    open, so closing December's window does not reopen November's on the day
    both are open. A clock, a cash-out and a credential have one occurrence at
    a time: a new one replaces the old.
    """
    svc = catalog.get_service(slug) or {}
    spec = next((r for r in svc.get("obligations") or [] if r.get("id") == rule), None)
    if spec is None or "since" in spec["when"]:
        return occurrence
    still_open = {o.isoformat() for o, _ in obligations.open_occurrences(spec, today)}
    row = (await database.get_obligation_state()).get((slug, rule))
    kept = obligations.done_occurrences(row) & still_open
    return ",".join(sorted(kept | {occurrence}))


@router.post("/api/obligations/{slug}/{rule}")
async def api_obligation_action(slug: str, rule: str, body: ObligationAction, request: Request) -> dict[str, Any]:
    user = deps._require_writer(request)
    if body.action not in ACTIONS:
        raise HTTPException(status_code=400, detail=f"action must be one of {', '.join(ACTIONS)}")
    # Credential reminders are the owner's (see api_obligations): a writer who
    # never sees one must not mute or snooze it for the household either.
    owner_only = rule.startswith(obligations.CREDENTIAL_PREFIX) and not auth.require_role(user, "owner")
    if owner_only or not _known_rule(slug, rule):
        raise HTTPException(status_code=404, detail="No such reminder")
    uid = user.get("uid") if isinstance(user.get("uid"), int) else None
    result: dict[str, Any] = {"slug": slug, "rule": rule, "action": body.action}

    if body.action in ("mute", "unmute"):
        await database.set_obligation_action(slug, rule, updated_by=uid, muted=body.action == "mute")
    else:
        evaluation, now = await _evaluate()
        today = now.date()
        matches = [i for i in evaluation.items if i.slug == slug and i.rule == rule]
        if body.occurrence is not None:
            matches = [i for i in matches if i.occurrence == body.occurrence]
        if not matches:
            raise HTTPException(status_code=404, detail="This reminder is not due now")
        item = matches[0]
        if body.action == "done":
            if not item.can_done:
                raise HTTPException(status_code=400, detail="This one clears by itself once it is fixed")
            await database.set_obligation_action(
                slug,
                rule,
                updated_by=uid,
                done_for=await _done_for(slug, rule, item.occurrence, today),
                done_at=today.isoformat(),
            )
            result["occurrence"] = item.occurrence
        else:
            if body.days not in SNOOZE_DAYS:
                raise HTTPException(status_code=400, detail="days must be 1 or 7")
            if not item.can_snooze:
                raise HTTPException(status_code=409, detail="Too close to its deadline to snooze")
            until = today + timedelta(days=body.days)
            await database.set_obligation_action(slug, rule, updated_by=uid, snoozed_until=until.isoformat())
            result["snoozed_until"] = until.isoformat()

    await database.add_audit_event(
        f"obligation_{body.action}", f"{slug}:{rule}", "ok", actor=user, detail=result.get("occurrence", "")
    )
    return result
