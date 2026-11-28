"""Money waiting: warn people before a provider writes off their earnings.

Providers lose people money in a few ways that repeat: a balance that expires
after months without activity, a claim window that closes, money left sitting
at a provider after the minimum was reached, and a credential that stops
tracking. CashPilot holds the data to see most of them. This module turns that
data into dated reminders.

It is pure, in the same style as ``payouts.py``: no I/O, no clock. The caller
(``main._evaluate_obligations``) reads the facts and the stored state, passes
"today" in, and stores what comes back.

Three kinds of reminder:

* a catalog rule (``obligations:`` in a service YAML, checked by
  ``catalog.validate_obligations``): a fixed date, a monthly window, or a clock
  that starts at an event CashPilot already records;
* **cash-out**, built in: the balance reached the provider's minimum, and at
  least ``CASHOUT_FLOOR_USD``;
* **credential**, built in: a stored credential is close to its expiry
  (``credential_expiry.report``).

Two rules run through all of it. Unknown is never shown as safe: a clock whose
start is older than CashPilot's history is marked ``censored`` ("by this date
or earlier"), and a minimum that cannot be converted gives no cash-out item
rather than a wrong one. And nothing here names a service: everything comes
from the catalog.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.i18n import t

#: The cash-out nudge waits for at least this much, in USD, whatever the
#: catalog minimum. A provider with a 5-cent minimum would otherwise nag at the
#: first cent. When the catalog minimum is higher, the minimum wins.
CASHOUT_FLOOR_USD = 5.0
#: A cash-out item that is still there after this many days pushes once more.
CASHOUT_STILL_READY_DAYS = 30
#: After Done, a clock or cash-out item whose condition still holds comes back
#: once after this many days: "did the payout arrive?". It falls inside the
#: 60-day dispute windows the providers give.
RECHECK_DAYS = 14

DEFAULT_WARN_DAYS = (30, 7, 1)

CASH_OUT = "cash-out"
CREDENTIAL_PREFIX = "credential:"
WHOLE_SERVICE = "*"

#: Stages that push. ``expired`` (a credential past its life) does not: the
#: collector alert already pushed the rejection, or the age-based guess has
#: nothing new to say after the ``expiring`` push.
_SILENT_STAGES = frozenset({"expired"})


@dataclass
class ServiceFacts:
    """What CashPilot knows about one service in use, read by the caller."""

    #: One reading per day, oldest first, in the balance's own unit.
    readings: list[tuple[date, float]] = field(default_factory=list)
    balance: float | None = None
    currency: str | None = None
    balance_usd: float | None = None
    #: The provider minimum in the balance's unit (``payouts.min_payout_in``).
    minimum: float | None = None
    #: Every payout row the user did not reject, as dates.
    payouts: list[date] = field(default_factory=list)
    #: The service has a collector, so its balance is read.
    collected: bool = False
    #: ``{field, status, due, occurrence}`` per stored credential.
    credentials: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Item:
    slug: str
    name: str
    rule: str
    kind: str  # "rule" | "cash-out" | "credential"
    action: str
    title: str
    loss: str
    occurrence: str
    stage: str
    due: date | None = None
    days_left: int | None = None
    censored: bool = False
    how: str = ""
    url: str = ""
    source: str = ""
    checked: str = ""
    can_done: bool = True
    can_snooze: bool = True
    balance: float | None = None
    currency: str | None = None
    balance_usd: float | None = None

    def as_dict(self) -> dict[str, Any]:
        out = {k: v for k, v in self.__dict__.items() if k not in ("balance", "currency", "balance_usd")}
        out["due"] = self.due.isoformat() if self.due else None
        if self.kind == CASH_OUT:
            # The balance shows only on cash-out rows, and never in a push.
            out.update(balance=self.balance, currency=self.currency, balance_usd=self.balance_usd)
        return out


@dataclass
class Evaluation:
    items: list[Item] = field(default_factory=list)
    muted: list[dict[str, str]] = field(default_factory=list)
    #: ``(slug, rule, anchor_at or None, censored)``: clock starts to store, or
    #: to clear (None) once the clock's condition no longer holds.
    anchors: list[tuple[str, str, str | None, bool]] = field(default_factory=list)


def as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def stage_for(days_left: int, warn_days: list[int] | tuple[int, ...]) -> str | None:
    """``d<w>`` for the smallest warning still ahead, ``overdue`` below 0, None outside."""
    if days_left < 0:
        return "overdue"
    inside = [w for w in warn_days if days_left <= w]
    return f"d{min(inside)}" if inside else None


def _last_payout(facts: ServiceFacts) -> date | None:
    return max(facts.payouts) if facts.payouts else None


def clock_start(since: str, facts: ServiceFacts) -> tuple[date | None, bool, bool | None]:
    """Where a clock starts, from the facts alone: ``(start, censored, active)``.

    ``active`` is None when the facts cannot say (no reading yet). ``censored``
    means the start is the first reading CashPilot still has, so the real start
    may be earlier.
    """
    readings = facts.readings
    if not readings or facts.balance is None:
        return None, False, None
    first = readings[0][0]
    paid = _last_payout(facts)
    if since == "over_minimum":
        minimum = facts.minimum
        if minimum is None:
            return None, False, None
        if not (facts.balance >= minimum and facts.balance > 0):
            return None, False, False
        for i, (day, balance) in enumerate(readings):
            if paid is not None and day < paid:
                continue
            if balance >= minimum:
                return day, i == 0, True
        # The latest balance is over the minimum but no reading since the last
        # payout is: the payout was recorded after the newest reading.
        return readings[-1][0], False, True
    if facts.balance <= 0:
        return None, False, False
    if since == "last_payout":
        return (paid, False, True) if paid is not None else (first, True, True)
    increased = None
    for (_, before), (day, after) in zip(readings, readings[1:], strict=False):
        if after > before:
            increased = day
    if since == "last_increase":
        # Earning only: a partial redemption (a payout that leaves a balance)
        # does not reset a clock that the terms count from the last earning.
        return (increased, False, True) if increased is not None else (first, True, True)
    # last_activity: the later of the last balance increase and the last payout.
    events = [d for d in (increased, paid) if d is not None]
    if events:
        return max(events), False, True
    return first, True, True


def _merge_anchor(live: date, censored: bool, stored: dict[str, Any] | None) -> tuple[date, bool]:
    """Combine the start the facts show with the start stored earlier.

    Earnings older than 400 days are purged, and a clock can run for 730. So
    the first start seen is stored, and used once the history behind it is gone:
    a censored live start (the oldest reading left) never moves a stored one
    later. A real event (an increase, a payout) moves the clock forward.
    """
    stored_at = as_date((stored or {}).get("anchor_at"))
    stored_censored = bool((stored or {}).get("anchor_censored"))
    if stored_at is None:
        return live, censored
    if censored:
        return (stored_at, stored_censored) if stored_at <= live else (live, censored)
    if not stored_censored and stored_at > live:
        return stored_at, False
    return live, False


def open_occurrences(rule: dict[str, Any], today: date) -> list[tuple[date, date]]:
    """``(occurrence, due)`` pairs of a date or monthly rule that are not yet past."""
    when = rule["when"]
    if "date" in when:
        due = as_date(when["date"])
        return [(due, due)] if due and due >= today else []
    on, due_days = int(when["on"]), int(when["due_days"])
    out = []
    year, month = today.year, today.month
    # Walk back far enough to catch every window still open.
    for _ in range(due_days // 28 + 2):
        opened = date(year, month, on)
        due = opened + timedelta(days=due_days)
        if opened <= today <= due:
            out.append((opened, due))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return sorted(out)


def _muted(state: dict[tuple[str, str], dict[str, Any]], slug: str, rule: str) -> bool:
    return bool((state.get((slug, WHOLE_SERVICE)) or {}).get("muted")) or bool(
        (state.get((slug, rule)) or {}).get("muted")
    )


def done_occurrences(row: dict[str, Any] | None) -> set[str]:
    """The occurrences marked done, from ``done_for``.

    A monthly window can still be open when the next one opens, so one rule
    can have two occurrences done at once. ``done_for`` holds them comma
    separated (an occurrence is an ISO date and never has a comma).
    """
    return {o for o in str((row or {}).get("done_for") or "").split(",") if o}


def _settle(
    item: Item,
    row: dict[str, Any] | None,
    today: date,
    warn_days: list[int] | tuple[int, ...] | None,
    recheck: bool,
) -> Item | None:
    """Apply Done and Snooze to one candidate; None when it is hidden."""
    row = row or {}
    if item.can_done and item.occurrence in done_occurrences(row):
        done_at = as_date(row.get("done_at"))
        if not recheck or done_at is None or today < done_at + timedelta(days=RECHECK_DAYS):
            return None
        item.stage = "recheck"
    # A snooze can delay a reminder but never cause the loss: it cannot run
    # past the last warning of a dated item.
    limit = None
    if item.due is not None and warn_days:
        limit = item.due - timedelta(days=min(warn_days))
    item.can_snooze = limit is None or limit > today
    until = as_date(row.get("snoozed_until"))
    if until is not None:
        if limit is not None:
            until = min(until, limit)
        if today < until:
            return None
    return item


def _rule_items(svc: dict[str, Any], facts: ServiceFacts, state: dict, today: date, out: Evaluation) -> list[Item]:
    slug, name = svc["slug"], svc.get("name") or svc["slug"]
    cashout = svc.get("cashout") if isinstance(svc.get("cashout"), dict) else {}
    default_url = cashout.get("dashboard_url") or svc.get("website") or ""
    items: list[Item] = []
    for rule in svc.get("obligations") or []:
        rid = rule["id"]
        warn = rule.get("warn_days") or list(DEFAULT_WARN_DAYS)
        when = rule["when"]
        base = {
            "slug": slug,
            "name": name,
            "rule": rid,
            "kind": "rule",
            "action": rule["action"],
            "title": rule["title"],
            "loss": rule["loss"],
            "how": rule.get("how") or "",
            "url": rule.get("url") or default_url,
            "source": rule.get("source") or "",
            "checked": str(rule.get("checked") or ""),
        }
        candidates: list[tuple[date, date, bool]] = []
        if "since" in when:
            live, censored, active = clock_start(when["since"], facts)
            stored = state.get((slug, rid))
            if active is False:
                if stored and stored.get("anchor_at"):
                    out.anchors.append((slug, rid, None, False))
                continue
            if active is None or live is None:
                continue
            start, censored = _merge_anchor(live, censored, stored)
            if (
                not stored
                or as_date(stored.get("anchor_at")) != start
                or bool(stored.get("anchor_censored")) != censored
            ):
                out.anchors.append((slug, rid, start.isoformat(), censored))
            candidates.append((start, start + timedelta(days=int(when["days"])), censored))
        else:
            candidates.extend((occ, due, False) for occ, due in open_occurrences(rule, today))
        if _muted(state, slug, rid):
            continue
        for occurrence, due, censored in candidates:
            days_left = (due - today).days
            stage = stage_for(days_left, warn)
            if stage is None:
                continue
            item = Item(
                **base,
                occurrence=occurrence.isoformat(),
                stage=stage,
                due=due,
                days_left=days_left,
                censored=censored,
            )
            settled = _settle(item, state.get((slug, rid)), today, warn, recheck="since" in when)
            if settled is not None:
                items.append(settled)
    return items


def _cashout_item(svc: dict[str, Any], facts: ServiceFacts, state: dict, today: date, out: Evaluation) -> Item | None:
    slug = svc["slug"]
    cashout = svc.get("cashout") if isinstance(svc.get("cashout"), dict) else {}
    if not facts.collected or cashout.get("method") == "auto":
        return None
    if facts.balance is None or facts.minimum is None or facts.balance_usd is None:
        # Unknown is never shown as "you can withdraw".
        return None
    stored = state.get((slug, CASH_OUT)) or {}
    ready = facts.balance >= facts.minimum and facts.balance_usd >= CASHOUT_FLOOR_USD and facts.balance > 0
    if not ready:
        if stored.get("anchor_at"):
            out.anchors.append((slug, CASH_OUT, None, False))
        return None
    start = as_date(stored.get("anchor_at"))
    if start is None or start > today:
        start = today
        out.anchors.append((slug, CASH_OUT, start.isoformat(), False))
    if _muted(state, slug, CASH_OUT):
        return None
    name = svc.get("name") or slug
    item = Item(
        slug=slug,
        name=name,
        rule=CASH_OUT,
        kind=CASH_OUT,
        action="withdraw",
        title=t("obligations.cash_out.title", name=name),
        loss=t("obligations.cash_out.loss"),
        how=str(cashout.get("notes") or "").strip(),
        url=cashout.get("dashboard_url") or svc.get("website") or "",
        occurrence=start.isoformat(),
        stage="ready" if (today - start).days < CASHOUT_STILL_READY_DAYS else "still-ready",
        balance=facts.balance,
        currency=facts.currency,
        balance_usd=facts.balance_usd,
    )
    return _settle(item, stored, today, None, recheck=True)


def _credential_items(svc: dict[str, Any], facts: ServiceFacts, state: dict, today: date) -> list[Item]:
    slug, name = svc["slug"], svc.get("name") or svc["slug"]
    items = []
    for row in facts.credentials:
        status = row.get("status")
        if row.get("rejected") or status not in ("expiring_soon", "likely_expired"):
            # A rejection is already in the bell and already pushed.
            continue
        rule = f"{CREDENTIAL_PREFIX}{row['field']}"
        if _muted(state, slug, rule):
            continue
        due = as_date(row.get("due"))
        days_left = (due - today).days if due else None
        expired = status == "likely_expired" or (days_left is not None and days_left < 0)
        item = Item(
            slug=slug,
            name=name,
            rule=rule,
            kind="credential",
            action="renew",
            title=t("obligations.credential.title", name=name, field=row["field"]),
            loss=t("obligations.credential.loss"),
            how=t("obligations.credential.how"),
            occurrence=str(row.get("occurrence") or ""),
            stage="expired" if expired else "expiring",
            due=due,
            days_left=days_left,
            # Saving a new value starts a new occurrence, so it clears itself.
            can_done=False,
        )
        settled = _settle(item, state.get((slug, rule)), today, [0] if due else None, recheck=False)
        if settled is not None:
            items.append(settled)
    return items


def _sort_key(item: Item) -> tuple:
    if item.stage == "overdue" or item.stage == "expired":
        group = 0
    elif item.days_left is not None and item.days_left <= 7:
        group = 1
    elif item.kind == CASH_OUT:
        group = 2
    else:
        group = 3
    return (
        group,
        -(item.balance_usd or 0) if item.kind == CASH_OUT else 0,
        item.days_left if item.days_left is not None else 10**6,
        item.name.lower(),
        item.rule,
    )


def evaluate(
    services: list[dict[str, Any]],
    facts: dict[str, ServiceFacts],
    state: dict[tuple[str, str], dict[str, Any]],
    today: date,
) -> Evaluation:
    """Every reminder due today, for the services in ``facts`` (the ones in use).

    ``services`` is the catalog, ``state`` the ``obligation_state`` rows keyed
    by ``(slug, rule)``. Custom and dead services get nothing.
    """
    out = Evaluation()
    by_slug = {}
    for svc in services:
        slug = svc.get("slug")
        if not slug or slug not in facts or svc.get("status") == "dead" or str(slug).startswith("custom-"):
            continue
        by_slug[slug] = svc
        service_facts = facts[slug]
        rules = _rule_items(svc, service_facts, state, today, out)
        out.items.extend(rules)
        cash = _cashout_item(svc, service_facts, state, today, out)
        # A visible withdraw rule says more than the generic nudge.
        if cash is not None and not any(r.action == "withdraw" for r in rules):
            out.items.append(cash)
        out.items.extend(_credential_items(svc, service_facts, state, today))
    out.items.sort(key=_sort_key)
    for (slug, rule), row in sorted(state.items()):
        if not row.get("muted") or slug not in by_slug:
            continue
        svc = by_slug[slug]
        title = next((r["title"] for r in svc.get("obligations") or [] if r["id"] == rule), None)
        if rule == WHOLE_SERVICE:
            title = t("obligations.muted.every")
        elif rule == CASH_OUT:
            title = t("obligations.muted.cash_out")
        elif rule.startswith(CREDENTIAL_PREFIX):
            title = t("obligations.muted.credential", field=rule.removeprefix(CREDENTIAL_PREFIX))
        if title:
            out.muted.append({"slug": slug, "rule": rule, "name": svc.get("name") or slug, "title": title})
    return out


def pushable(item: Item) -> bool:
    return item.stage not in _SILENT_STAGES


def push_subject(item: Item) -> str:
    """The alert dedupe key: one push per stage of one occurrence."""
    return f"{item.slug}:{item.rule}:{item.occurrence}:{item.stage}"


_MONTHS = (
    "obligations.month.1",
    "obligations.month.2",
    "obligations.month.3",
    "obligations.month.4",
    "obligations.month.5",
    "obligations.month.6",
    "obligations.month.7",
    "obligations.month.8",
    "obligations.month.9",
    "obligations.month.10",
    "obligations.month.11",
    "obligations.month.12",
)


def _month(day: date) -> str:
    key = _MONTHS[day.month - 1]
    return t(key)  # i18n-keys: obligations.month.1, obligations.month.2, obligations.month.3, obligations.month.4, obligations.month.5, obligations.month.6, obligations.month.7, obligations.month.8, obligations.month.9, obligations.month.10, obligations.month.11, obligations.month.12  # fmt: skip


def _due_text(item: Item) -> str:
    if item.due is None:
        return ""
    day, month, year = item.due.day, _month(item.due), item.due.year
    if item.censored:
        return t("obligations.due_or_earlier", day=day, month=month, year=year)
    return t("obligations.due", day=day, month=month, year=year)


def push_text(item: Item) -> tuple[str, str]:
    """``(title, body)`` for one push. Catalog text and dates only: never a balance."""
    name, action = item.name, item.action
    if item.stage == "recheck":
        title = t("obligations.push.recheck", name=name)
    elif item.kind == CASH_OUT:
        title = t("obligations.push.cash_out", name=name)
    elif item.stage == "overdue":
        title = t("obligations.push.overdue", name=name, action=action)
    elif item.days_left == 0:
        title = t("obligations.push.today", name=name, action=action)
    elif item.days_left is not None and item.days_left <= 1:
        title = t("obligations.push.tomorrow", name=name, action=action)
    elif item.days_left is not None:
        title = t("obligations.push.within", name=name, action=action, days=item.days_left)
    else:
        title = t("obligations.push.plain", name=name, action=action)
    lines = [item.title + ".", item.loss]
    if item.stage == "overdue":
        lines.append(t("obligations.push.written_off"))
    if due := _due_text(item):
        lines.append(t("obligations.push.due_by", due=due))
    if item.url:
        lines.append(item.url)
    return title, "\n".join(lines)


def summary_text(items: list[Item]) -> tuple[str, str]:
    """One push in place of many, so upgrade day is not a flood."""
    names = []
    for item in items:
        if item.name not in names:
            names.append(item.name)
    title = t("obligations.summary.title", n=len(items))
    body = t("obligations.summary.body", names=", ".join(names))
    return title, body
