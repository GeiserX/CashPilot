"""Money waiting: the reminders before a provider writes off earnings.

The engine (app/obligations.py) is pure, so most of this runs it on a fixed
"today" with hand-built facts. The rest covers what wraps it: the stored clock
starts, the hourly push job and its guards, the routes and their roles, and
which services count as in use. Every gate here was seen failing on a broken
input first (see the PR).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app import database, obligations
from app.obligations import CASH_OUT, Evaluation, ServiceFacts, evaluate

TODAY = date(2026, 11, 24)


def _svc(slug="acme", rules=None, **extra):
    svc = {
        "slug": slug,
        "name": slug.title(),
        "status": "active",
        "website": f"https://{slug}.example",
        "cashout": {"method": "redirect", "dashboard_url": f"https://app.{slug}.example/pay", "min_amount": 20},
        "obligations": rules or [],
    }
    svc.update(extra)
    return svc


def _rule(rid="keep", when=None, action="keep-active", warn=None, **extra):
    rule = {
        "id": rid,
        "action": action,
        "title": f"Do {rid}",
        "loss": "The balance expires.",
        "when": when or {"since": "last_activity", "days": 180},
        "source": "https://acme.example/terms",
        "checked": "2026-11-24",
    }
    if warn is not None:
        rule["warn_days"] = warn
    rule.update(extra)
    return rule


def _days(n):
    return TODAY - timedelta(days=n)


def _facts(readings=None, payouts=None, **kw):
    readings = readings or []
    balance = kw.pop("balance", readings[-1][1] if readings else None)
    return ServiceFacts(readings=readings, payouts=payouts or [], balance=balance, **kw)


def _run(services, facts, state=None, today=TODAY):
    return evaluate(services, facts, state or {}, today)


def _one(ev: Evaluation):
    assert len(ev.items) == 1, [i.as_dict() for i in ev.items]
    return ev.items[0]


# ---------------------------------------------------------------------------
# The three `when` forms
# ---------------------------------------------------------------------------


class TestFixedDate:
    RULE = _rule("claim", when={"date": "2027-01-22"}, action="claim", warn=[60, 30, 7, 1])

    def test_shows_inside_its_first_warning_with_days_left(self):
        item = _one(_run([_svc(rules=[self.RULE])], {"acme": _facts()}))
        assert (item.due, item.days_left, item.stage) == (date(2027, 1, 22), 59, "d60")

    def test_hidden_before_the_first_warning(self):
        ev = _run([_svc(rules=[self.RULE])], {"acme": _facts()}, today=date(2026, 11, 1))
        assert ev.items == []

    def test_due_today_is_still_shown(self):
        item = _one(_run([_svc(rules=[self.RULE])], {"acme": _facts()}, today=date(2027, 1, 22)))
        assert (item.days_left, item.stage) == (0, "d1")

    def test_dropped_the_day_after_because_the_money_is_gone(self):
        ev = _run([_svc(rules=[self.RULE])], {"acme": _facts()}, today=date(2027, 1, 23))
        assert ev.items == []


class TestMonthlyWindow:
    RULE = _rule("pool", when={"every": "month", "on": 1, "due_days": 30}, action="claim", warn=[30, 7])

    def test_the_window_opens_on_its_day(self):
        # 1 Dec is also the day November's window closes, so both show.
        ev = _run([_svc(rules=[self.RULE])], {"acme": _facts()}, today=date(2026, 12, 1))
        assert [(i.occurrence, i.due.isoformat(), i.stage) for i in ev.items] == [
            ("2026-11-01", "2026-12-01", "d7"),
            ("2026-12-01", "2026-12-31", "d30"),
        ]

    def test_it_stays_on_its_first_stage_between_the_warnings(self):
        # Shown through the window, but still the d30 stage: no second push.
        item = _one(_run([_svc(rules=[self.RULE])], {"acme": _facts()}, today=date(2026, 12, 10)))
        assert (item.occurrence, item.stage) == ("2026-12-01", "d30")

    def test_seven_days_before_it_closes(self):
        item = _one(_run([_svc(rules=[self.RULE])], {"acme": _facts()}, today=date(2026, 12, 24)))
        assert item.stage == "d7"

    def test_month_end_keeps_february_open_into_march(self):
        # 1 Feb + 30 days is 3 Mar: on 1 Mar both February's window (2 days
        # left) and March's (just opened) are open, and both show.
        ev = _run([_svc(rules=[self.RULE])], {"acme": _facts()}, today=date(2027, 3, 1))
        assert [(i.occurrence, i.days_left) for i in ev.items] == [("2027-02-01", 2), ("2027-03-01", 30)]


class TestClocks:
    def test_last_activity_starts_at_the_last_increase(self):
        rule = _rule(warn=[90, 30, 7])
        readings = [(_days(200), 1.0), (_days(120), 2.0), (_days(5), 2.0)]
        item = _one(_run([_svc(rules=[rule])], {"acme": _facts(readings)}))
        assert item.occurrence == _days(120).isoformat()
        assert item.days_left == 60 and item.stage == "d90"
        assert not item.censored

    def test_a_payout_after_the_last_increase_moves_the_clock(self):
        rule = _rule(warn=[90, 30, 7])
        readings = [(_days(200), 1.0), (_days(170), 2.0), (_days(5), 2.0)]
        item = _one(_run([_svc(rules=[rule])], {"acme": _facts(readings, payouts=[_days(150)])}))
        assert item.occurrence == _days(150).isoformat()

    def test_inactive_at_zero_balance(self):
        readings = [(_days(300), 1.0), (_days(5), 0.0)]
        assert _run([_svc(rules=[_rule()])], {"acme": _facts(readings)}).items == []

    def test_over_minimum_starts_at_the_first_reading_over_it(self):
        rule = _rule("write-off", when={"since": "over_minimum", "days": 730}, action="withdraw", warn=[180, 60, 30])
        readings = [(_days(700), 10.0), (_days(600), 21.0), (_days(1), 40.0)]
        item = _one(_run([_svc(rules=[rule])], {"acme": _facts(readings, minimum=20.0)}))
        assert (item.occurrence, item.days_left, item.stage) == (_days(600).isoformat(), 130, "d180")

    def test_over_minimum_is_inactive_under_the_minimum(self):
        rule = _rule("write-off", when={"since": "over_minimum", "days": 30}, action="withdraw")
        readings = [(_days(100), 25.0), (_days(1), 19.0)]
        assert _run([_svc(rules=[rule])], {"acme": _facts(readings, minimum=20.0)}).items == []

    def test_over_minimum_with_an_unknown_minimum_gives_nothing(self):
        rule = _rule("write-off", when={"since": "over_minimum", "days": 30}, action="withdraw")
        readings = [(_days(100), 25.0), (_days(1), 25.0)]
        assert _run([_svc(rules=[rule])], {"acme": _facts(readings, minimum=None)}).items == []

    def test_last_payout_with_no_payout_is_the_first_reading_and_censored(self):
        rule = _rule("forfeit", when={"since": "last_payout", "days": 365}, action="withdraw", warn=[90])
        readings = [(_days(300), 1.0), (_days(1), 3.0)]
        item = _one(_run([_svc(rules=[rule])], {"acme": _facts(readings)}))
        assert item.occurrence == _days(300).isoformat()
        assert item.censored is True

    def test_last_increase_ignores_a_partial_redemption(self):
        # Salad counts earning only: spending part of the balance does not
        # reset its 12 months. Earned until 10 Jan, redeemed part on 1 Jun.
        rule = _rule("earn", when={"since": "last_increase", "days": 365}, warn=[90, 30, 7])
        readings = [(date(2025, 12, 1), 10.0), (date(2026, 1, 10), 13.0), (date(2026, 6, 1), 3.0)]
        facts = {"acme": _facts(readings, payouts=[date(2026, 6, 1)])}
        item = _one(_run([_svc(rules=[rule])], facts, today=date(2027, 1, 10)))
        assert (item.occurrence, item.due, item.stage) == ("2026-01-10", date(2027, 1, 10), "d7")
        assert not item.censored

    def test_last_increase_with_no_increase_is_the_first_reading_and_censored(self):
        rule = _rule("earn", when={"since": "last_increase", "days": 365}, warn=[90])
        readings = [(_days(300), 5.0), (_days(100), 3.0)]
        item = _one(_run([_svc(rules=[rule])], {"acme": _facts(readings, payouts=[_days(100)])}))
        assert (item.occurrence, item.censored) == (_days(300).isoformat(), True)

    def test_salad_warns_on_the_earning_clock(self):
        from app import catalog

        salad = catalog.get_service("salad")
        readings = [(date(2025, 12, 1), 10.0), (date(2026, 1, 10), 13.0), (date(2026, 6, 1), 3.0)]
        facts = {"salad": _facts(readings, payouts=[date(2026, 6, 1)])}
        items = _run([salad], facts, today=date(2026, 12, 1)).items
        assert [(i.rule, i.due) for i in items] == [("earn-within-12-months", date(2027, 1, 10))]

    def test_an_overdue_clock_stays(self):
        rule = _rule(warn=[90, 30, 7])
        readings = [(_days(200), 1.0), (_days(190), 2.0), (_days(1), 2.0)]
        item = _one(_run([_svc(rules=[rule])], {"acme": _facts(readings)}))
        assert (item.stage, item.days_left) == ("overdue", -10)
        assert item.can_snooze is False


class TestStages:
    @pytest.mark.parametrize(
        ("days_left", "stage"),
        [(200, None), (90, "d90"), (31, "d90"), (30, "d30"), (8, "d30"), (7, "d7"), (0, "d7"), (-1, "overdue")],
    )
    def test_only_the_current_stage(self, days_left, stage):
        assert obligations.stage_for(days_left, [90, 30, 7]) == stage

    def test_an_item_first_seen_late_reports_its_own_stage_only(self):
        rule = _rule("claim", when={"date": (TODAY + timedelta(days=5)).isoformat()}, action="claim")
        ev = _run([_svc(rules=[rule])], {"acme": _facts()})
        assert [i.stage for i in ev.items] == ["d7"]


# ---------------------------------------------------------------------------
# Stored clock starts, and clocks older than CashPilot's history
# ---------------------------------------------------------------------------


class TestAnchors:
    RULE = _rule("write-off", when={"since": "over_minimum", "days": 730}, action="withdraw", warn=[180, 60, 30])

    def test_a_first_seen_start_is_returned_for_storing(self):
        readings = [(_days(300), 10.0), (_days(200), 21.0), (_days(1), 30.0)]
        ev = _run([_svc(rules=[self.RULE])], {"acme": _facts(readings, minimum=20.0)})
        assert ev.anchors == [("acme", "write-off", _days(200).isoformat(), False)]

    def test_the_stored_start_survives_a_purged_history(self):
        # The crossing 600 days ago is purged; the oldest reading left is
        # already over the minimum, so the facts alone would start the clock
        # at day 399 and push the write-off date out by 200 days.
        readings = [(_days(399), 25.0), (_days(1), 30.0)]
        state = {("acme", "write-off"): {"anchor_at": _days(600).isoformat(), "anchor_censored": 0}}
        ev = _run([_svc(rules=[self.RULE])], {"acme": _facts(readings, minimum=20.0)}, state)
        item = _one(ev)
        assert item.occurrence == _days(600).isoformat()
        assert item.days_left == 130 and not item.censored
        assert ev.anchors == []

    def test_without_the_stored_start_it_says_or_earlier(self):
        readings = [(_days(399), 25.0), (_days(1), 30.0)]
        rule = dict(self.RULE, warn_days=[400])
        item = _one(_run([_svc(rules=[rule])], {"acme": _facts(readings, minimum=20.0)}))
        assert item.censored is True
        title, body = obligations.push_text(item)
        assert "or earlier" in body

    def test_a_real_event_moves_a_stored_activity_clock_forward(self):
        rule = _rule(warn=[180])
        readings = [(_days(100), 1.0), (_days(50), 2.0), (_days(1), 2.0)]
        state = {("acme", "keep"): {"anchor_at": _days(100).isoformat(), "anchor_censored": 1}}
        ev = _run([_svc(rules=[rule])], {"acme": _facts(readings)}, state)
        assert _one(ev).occurrence == _days(50).isoformat()
        assert ev.anchors == [("acme", "keep", _days(50).isoformat(), False)]

    def test_a_payout_that_empties_the_balance_clears_the_stored_start(self):
        readings = [(_days(300), 25.0), (_days(1), 0.0)]
        state = {("acme", "write-off"): {"anchor_at": _days(300).isoformat(), "anchor_censored": 0}}
        ev = _run([_svc(rules=[self.RULE])], {"acme": _facts(readings, payouts=[_days(1)], minimum=20.0)}, state)
        assert ev.items == []
        assert ev.anchors == [("acme", "write-off", None, False)]


# ---------------------------------------------------------------------------
# Done, Snooze and Not for me
# ---------------------------------------------------------------------------


class TestUserState:
    CLAIM = _rule("claim", when={"date": "2027-01-22"}, action="claim", warn=[60, 30, 7, 1])
    POOL = _rule("pool", when={"every": "month", "on": 1, "due_days": 30}, action="claim", warn=[30, 7])

    def test_done_hides_only_its_occurrence(self):
        state = {("acme", "pool"): {"done_for": "2027-02-01", "done_at": "2027-02-02"}}
        ev = _run([_svc(rules=[self.POOL])], {"acme": _facts()}, state, today=date(2027, 3, 1))
        assert [i.occurrence for i in ev.items] == ["2027-03-01"]

    def test_done_on_two_open_windows_hides_both(self):
        # On 1 Dec November's window closes and December's opens. Closing
        # December's must not bring back November's, closed earlier.
        state = {("acme", "pool"): {"done_for": "2026-11-01,2026-12-01", "done_at": "2026-12-01"}}
        ev = _run([_svc(rules=[self.POOL])], {"acme": _facts()}, state, today=date(2026, 12, 1))
        assert ev.items == []

    def test_done_on_a_dated_rule_does_not_come_back(self):
        state = {("acme", "claim"): {"done_for": "2027-01-22", "done_at": "2026-11-24"}}
        ev = _run([_svc(rules=[self.CLAIM])], {"acme": _facts()}, state, today=date(2027, 1, 21))
        assert ev.items == []

    def test_a_clock_still_running_14_days_after_done_comes_back_as_recheck(self):
        rule = _rule("forfeit", when={"since": "last_payout", "days": 365}, action="withdraw", warn=[90])
        readings = [(_days(300), 1.0), (_days(1), 3.0)]
        occ = _days(300).isoformat()
        hidden = {("acme", "forfeit"): {"done_for": occ, "done_at": _days(13).isoformat()}}
        assert _run([_svc(rules=[rule])], {"acme": _facts(readings)}, hidden).items == []
        back = {("acme", "forfeit"): {"done_for": occ, "done_at": _days(14).isoformat()}}
        assert _one(_run([_svc(rules=[rule])], {"acme": _facts(readings)}, back)).stage == "recheck"

    def test_snooze_hides_until_its_date(self):
        state = {("acme", "claim"): {"snoozed_until": (TODAY + timedelta(days=7)).isoformat()}}
        assert _run([_svc(rules=[self.CLAIM])], {"acme": _facts()}, state).items == []
        later = TODAY + timedelta(days=7)
        assert _one(_run([_svc(rules=[self.CLAIM])], {"acme": _facts()}, state, today=later))

    def test_snooze_never_runs_past_the_last_warning(self):
        # A year-long snooze set early is cut at 21 Jan, the 1-day warning.
        state = {("acme", "claim"): {"snoozed_until": "2027-12-31"}}
        assert _run([_svc(rules=[self.CLAIM])], {"acme": _facts()}, state, today=date(2027, 1, 20)).items == []
        item = _one(_run([_svc(rules=[self.CLAIM])], {"acme": _facts()}, state, today=date(2027, 1, 21)))
        assert item.stage == "d1" and item.can_snooze is False

    def test_not_for_me_mutes_one_rule(self):
        svc = _svc(rules=[self.CLAIM, self.POOL])
        state = {("acme", "claim"): {"muted": 1}}
        ev = _run([svc], {"acme": _facts()}, state, today=date(2027, 1, 1))
        assert [i.rule for i in ev.items] == ["pool"]
        assert ev.muted == [{"slug": "acme", "rule": "claim", "name": "Acme", "title": "Do claim"}]

    def test_not_for_me_on_the_whole_service(self):
        state = {("acme", "*"): {"muted": 1}}
        ev = _run([_svc(rules=[self.CLAIM, self.POOL])], {"acme": _facts()}, state, today=date(2027, 1, 1))
        assert ev.items == []
        assert ev.muted[0]["rule"] == "*"


# ---------------------------------------------------------------------------
# The built-in cash-out reminder
# ---------------------------------------------------------------------------


def _cash(balance=25.0, usd=25.0, minimum=20.0, collected=True, **kw):
    return _facts(balance=balance, balance_usd=usd, minimum=minimum, currency="USD", collected=collected, **kw)


class TestCashOut:
    def test_ready_at_the_minimum(self):
        ev = _run([_svc()], {"acme": _cash()})
        item = _one(ev)
        assert (item.rule, item.stage, item.occurrence) == (CASH_OUT, "ready", TODAY.isoformat())
        assert ev.anchors == [("acme", CASH_OUT, TODAY.isoformat(), False)]

    def test_still_ready_after_30_days(self):
        state = {("acme", CASH_OUT): {"anchor_at": _days(30).isoformat()}}
        assert _one(_run([_svc()], {"acme": _cash()}, state)).stage == "still-ready"

    def test_the_5_dollar_floor_holds_back_a_tiny_minimum(self):
        svc = _svc()
        assert _run([svc], {"acme": _cash(balance=0.06, usd=0.06, minimum=0.05)}).items == []
        assert _one(_run([svc], {"acme": _cash(balance=5.0, usd=5.0, minimum=0.05)})).rule == CASH_OUT

    def test_a_higher_catalog_minimum_wins_over_the_floor(self):
        assert _run([_svc()], {"acme": _cash(balance=19.0, usd=19.0, minimum=20.0)}).items == []

    @pytest.mark.parametrize("missing", ["minimum", "usd"])
    def test_an_unknown_conversion_gives_no_item(self, missing):
        facts = _cash(**{missing: None})
        assert _run([_svc()], {"acme": facts}).items == []

    def test_not_for_an_automatic_payout(self):
        svc = _svc(cashout={"method": "auto", "min_amount": 5})
        assert _run([svc], {"acme": _cash()}).items == []

    def test_not_for_a_dead_service(self):
        assert _run([_svc(status="dead")], {"acme": _cash()}).items == []

    def test_not_without_a_collector(self):
        assert _run([_svc()], {"acme": _cash(collected=False)}).items == []

    def test_hidden_when_a_withdraw_rule_shows(self):
        rule = _rule("forfeit", when={"since": "last_payout", "days": 365}, action="withdraw", warn=[90])
        readings = [(_days(300), 25.0), (_days(1), 25.0)]
        ev = _run([_svc(rules=[rule])], {"acme": _cash(readings=readings)})
        assert [i.rule for i in ev.items] == ["forfeit"]

    def test_shown_while_the_withdraw_rule_is_not_yet_due(self):
        rule = _rule("forfeit", when={"since": "last_payout", "days": 365}, action="withdraw", warn=[90])
        readings = [(_days(10), 25.0), (_days(1), 25.0)]
        ev = _run([_svc(rules=[rule])], {"acme": _cash(readings=readings)})
        assert [i.rule for i in ev.items] == [CASH_OUT]

    def test_requested_then_still_there_after_14_days(self):
        start = _days(20).isoformat()
        state = {("acme", CASH_OUT): {"anchor_at": start, "done_for": start, "done_at": _days(14).isoformat()}}
        assert _one(_run([_svc()], {"acme": _cash()}, state)).stage == "recheck"

    def test_not_ready_clears_its_start(self):
        state = {("acme", CASH_OUT): {"anchor_at": _days(3).isoformat()}}
        ev = _run([_svc()], {"acme": _cash(balance=1.0, usd=1.0)}, state)
        assert ev.items == [] and ev.anchors == [("acme", CASH_OUT, None, False)]

    def test_largest_cash_out_first(self):
        small, big = _svc("small"), _svc("big")
        ev = _run([small, big], {"small": _cash(usd=6.0), "big": _cash(usd=60.0)})
        assert [i.slug for i in ev.items] == ["big", "small"]


# ---------------------------------------------------------------------------
# The built-in credential reminder
# ---------------------------------------------------------------------------


class TestCredentials:
    def _row(self, status, due=None, rejected=False):
        return {
            "field": "token",
            "status": status,
            "due": due,
            "occurrence": "2026-01-01 00:00:00",
            "rejected": rejected,
        }

    def test_expiring_soon_is_an_item_due_on_the_expiry(self):
        facts = _facts(credentials=[self._row("expiring_soon", TODAY + timedelta(days=2))])
        item = _one(_run([_svc()], {"acme": facts}))
        assert (item.rule, item.stage, item.days_left, item.can_done) == ("credential:token", "expiring", 2, False)
        assert obligations.pushable(item)

    def test_likely_expired_shows_but_does_not_push_again(self):
        item = _one(_run([_svc()], {"acme": _facts(credentials=[self._row("likely_expired", _days(1))])}))
        assert item.stage == "expired"
        assert not obligations.pushable(item)

    @pytest.mark.parametrize("status", ["no_known_expiry", "fresh"])
    def test_no_item_without_a_known_expiry(self, status):
        assert _run([_svc()], {"acme": _facts(credentials=[self._row(status)])}).items == []

    def test_a_rejected_credential_is_left_to_the_collector_alert(self):
        facts = _facts(credentials=[self._row("likely_expired", rejected=True)])
        assert _run([_svc()], {"acme": facts}).items == []


# ---------------------------------------------------------------------------
# Who a rule applies to, and the order of the panel
# ---------------------------------------------------------------------------


class TestApplicability:
    def test_a_catalog_service_not_in_use_gets_nothing(self):
        rule = _rule("claim", when={"date": "2027-01-22"}, action="claim", warn=[60])
        assert _run([_svc(rules=[rule])], {}).items == []

    def test_custom_services_get_nothing(self):
        rule = _rule("claim", when={"date": "2027-01-22"}, action="claim", warn=[60])
        assert _run([_svc("custom-x", rules=[rule])], {"custom-x": _facts()}).items == []

    def test_overdue_comes_first(self):
        overdue = _rule("old", warn=[90])
        soon = _rule("soon", when={"date": (TODAY + timedelta(days=3)).isoformat()}, action="claim")
        later = _rule("later", when={"date": (TODAY + timedelta(days=20)).isoformat()}, action="claim")
        readings = [(_days(300), 1.0), (_days(200), 2.0), (_days(1), 2.0)]
        ev = _run([_svc(rules=[later, soon, overdue])], {"acme": _cash(readings=readings)})
        assert [i.rule for i in ev.items] == ["old", "soon", CASH_OUT, "later"]


@pytest.fixture
def tmp_db(tmp_path):
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
        asyncio.run(database.init_db())
        yield


class TestWhatCountsAsInUse:
    """main._obligation_facts: deployed, external, a phone app, or a balance left."""

    def _facts_for(self, deployments, containers, summary):
        from app import main

        with (
            patch.object(main.database, "get_earnings_summary", AsyncMock(return_value=summary)),
            patch.object(main.database, "get_deployments", AsyncMock(return_value=deployments)),
            patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=containers)),
            patch.object(main, "_credential_report", AsyncMock(return_value=[])),
            patch.object(main.database, "get_config_updated_at", AsyncMock(return_value={})),
            patch.object(main.database, "get_balance_history", AsyncMock(return_value=[])),
            patch.object(main.database, "get_payouts", AsyncMock(return_value=[])),
        ):
            return asyncio.run(main._obligation_facts(datetime(2026, 11, 24, 12, tzinfo=UTC)))

    def test_each_way_in(self):
        facts = self._facts_for(
            deployments=[{"slug": "honeygain", "status": "running"}, {"slug": "grass", "status": "external"}],
            containers=[{"slug": "salad"}],
            summary=[
                {"platform": "repocket", "balance": 3.0, "currency": "USD"},
                {"platform": "bitping", "balance": 0.0, "currency": "USD"},
            ],
        )
        assert set(facts) == {"honeygain", "grass", "salad", "repocket"}

    def test_a_removed_service_with_no_balance_is_not_in_use(self):
        facts = self._facts_for([], [], [{"platform": "earnapp", "balance": 0, "currency": "USD"}])
        assert facts == {}


# ---------------------------------------------------------------------------
# The hourly push job
# ---------------------------------------------------------------------------


def _item(slug="acme", stage="d7", days_left=5, **kw):
    base = dict(
        slug=slug,
        name=slug.title(),
        rule="claim",
        kind="rule",
        action="claim",
        title="Claim it",
        loss="It is lost.",
        occurrence="2027-01-22",
        stage=stage,
        due=TODAY + timedelta(days=days_left) if days_left is not None else None,
        days_left=days_left,
        url=f"https://{slug}.example/claim",
    )
    base.update(kw)
    return obligations.Item(**base)


def _job(items, hour=10, delivered=1, enabled=True):
    from app import main

    send = AsyncMock(return_value=delivered)
    now = datetime(2026, 11, 24, hour, tzinfo=UTC)
    with (
        patch.object(main, "_evaluate_obligations", AsyncMock(return_value=(Evaluation(items=items), now))),
        patch.object(main.notify, "send", send),
        patch.object(main.notify, "is_enabled", return_value=enabled),
    ):
        asyncio.run(main._run_obligations())
    return send


@pytest.mark.usefixtures("tmp_db")
class TestPushJob:
    def _alerts(self):
        return [a for a in asyncio.run(database.list_alerts(limit=100)) if a["kind"] == "obligation"]

    def test_one_push_per_stage(self):
        assert _job([_item()]).await_count == 1
        assert _job([_item()]).await_count == 0
        assert _job([_item(stage="d1", days_left=1)]).await_count == 1

    def test_a_push_no_channel_took_is_retried(self):
        assert _job([_item()], delivered=0).await_count == 1
        assert self._alerts() == []
        assert _job([_item()]).await_count == 1

    def test_quiet_hours(self):
        assert _job([_item()], hour=3).await_count == 0
        assert self._alerts() == []
        assert _job([_item()], hour=21).await_count == 0
        assert _job([_item()], hour=9).await_count == 1

    def test_more_than_three_send_one_summary(self):
        items = [_item(slug=f"s{n}") for n in range(4)]
        send = _job(items)
        assert send.await_count == 1
        assert send.await_args.args[0] == "CashPilot: 4 things to do before you lose money"
        assert len(self._alerts()) == 4

    def test_three_go_out_one_by_one(self):
        assert _job([_item(slug=f"s{n}") for n in range(3)]).await_count == 3

    def test_a_failed_summary_releases_every_row(self):
        items = [_item(slug=f"s{n}") for n in range(5)]
        _job(items, delivered=0)
        assert self._alerts() == []
        assert _job(items).await_count == 1

    def test_an_expired_credential_does_not_push(self):
        assert _job([_item(kind="credential", stage="expired", days_left=-1)]).await_count == 0

    def test_no_balance_in_any_message(self):
        cash = _item(kind=CASH_OUT, rule=CASH_OUT, stage="ready", due=None, days_left=None, action="withdraw")
        cash.balance, cash.currency, cash.balance_usd = 123.45, "USD", 123.45
        send = _job([cash])
        title, body = send.await_args.args[:2]
        assert "123" not in title + body
        assert send.await_args.kwargs["kind"] == "obligation"

    def test_the_text_goes_through_redact(self):
        # notify.send redacts every title and message; a token in a URL must not survive.
        from app import notify

        item = _item(url="https://acme.example/claim?token=abcdefsecret")
        title, body = obligations.push_text(item)
        assert "abcdefsecret" not in notify.redact(body)

    def test_never_in_the_bell_even_after_a_restart(self):
        from app import main

        _job([_item()])
        assert self._alerts()
        with patch.object(main, "_collector_alerts", []):
            asyncio.run(main._warm_collector_alerts())
            assert not [a for a in main._collector_alerts if a.get("kind") == "obligation"]


class TestPushText:
    def test_title_says_who_and_how_long(self):
        title, body = obligations.push_text(_item(days_left=7))
        assert title == "CashPilot: Acme, claim within 7 days"
        assert "It is lost." in body and "https://acme.example/claim" in body

    def test_overdue_says_it_may_be_gone(self):
        title, body = obligations.push_text(_item(stage="overdue", days_left=-3))
        assert "deadline passed" in title and "may already have written this off" in body


# ---------------------------------------------------------------------------
# The stored state
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("tmp_db")
class TestState:
    def test_anchor_and_actions_keep_each_other(self):
        asyncio.run(database.set_obligation_anchors([("acme", "keep", "2026-01-01", True)]))
        asyncio.run(database.set_obligation_action("acme", "keep", updated_by=2, muted=True))
        asyncio.run(database.set_obligation_anchors([("acme", "keep", "2026-02-01", False)]))
        row = asyncio.run(database.get_obligation_state())[("acme", "keep")]
        assert (row["anchor_at"], row["anchor_censored"], row["muted"], row["updated_by"]) == ("2026-02-01", 0, 1, 2)

    def test_owner_timezone(self):
        asyncio.run(database.create_user("own", "x" * 60, "owner"))
        uid = asyncio.run(database.list_users())[0]["id"]
        asyncio.run(database.save_user_preferences(uid, timezone="Europe/Madrid"))
        assert asyncio.run(database.get_owner_timezone()) == "Europe/Madrid"


# ---------------------------------------------------------------------------
# Routes and roles
# ---------------------------------------------------------------------------


GRASS_ITEM = _item(slug="grass", rule="claim-stage2-usdc", occurrence="2027-01-22", days_left=59)


@pytest.fixture
def api():
    from app import main

    actions = AsyncMock()
    audit = AsyncMock()
    now = datetime(2026, 11, 24, 12, tzinfo=UTC)
    with (
        patch.object(main, "_evaluate_obligations", AsyncMock(return_value=(Evaluation(items=[GRASS_ITEM]), now))),
        patch.object(main.database, "set_obligation_action", actions),
        patch.object(main.database, "add_audit_event", audit),
        patch.object(main.database, "get_obligation_state", AsyncMock(return_value={})),
    ):
        yield TestClient(main.app, raise_server_exceptions=False), actions, audit


def _as(role):
    users = {
        "owner": {"uid": 1, "u": "admin", "r": "owner"},
        "writer": {"uid": 2, "u": "writer", "r": "writer"},
        "viewer": {"uid": 3, "u": "viewer", "r": "viewer"},
        "readonly": {"uid": 0, "u": "readonly", "r": "reader"},
        "fleet": {"uid": 0, "u": "fleet", "r": "fleet"},
    }
    return patch("app.main.auth.get_current_user", return_value=users[role])


class TestRoutes:
    @pytest.mark.parametrize("role", ["owner", "writer", "viewer", "readonly"])
    def test_every_reader_sees_the_panel(self, api, role):
        client, _, _ = api
        with _as(role):
            res = client.get("/api/obligations")
        assert res.status_code == 200
        assert res.json()["items"][0]["rule"] == "claim-stage2-usdc"

    @pytest.mark.parametrize(
        ("role", "shown"), [("owner", True), ("writer", False), ("viewer", False), ("readonly", False)]
    )
    def test_credential_reminders_only_to_the_owner(self, role, shown):
        # Credential health is owner-only on the dashboard, and the read-only
        # token never gets it (/api/credentials/health refuses it).
        from app import main

        cred = _item(slug="grass", rule="credential:token", kind="credential", action="renew", occurrence="x")
        muted = [{"slug": "grass", "rule": "credential:token", "name": "Grass", "title": "Credential reminder (token)"}]
        evaluation = Evaluation(items=[GRASS_ITEM, cred], muted=muted)
        now = datetime(2026, 11, 24, 12, tzinfo=UTC)
        with patch.object(main, "_evaluate_obligations", AsyncMock(return_value=(evaluation, now))), _as(role):
            body = TestClient(main.app, raise_server_exceptions=False).get("/api/obligations").json()
        assert [i["kind"] for i in body["items"]] == (["rule", "credential"] if shown else ["rule"])
        assert bool(body["muted"]) is shown

    def test_the_fleet_key_does_not(self, api):
        client, _, _ = api
        with _as("fleet"):
            assert client.get("/api/obligations").status_code == 403

    @pytest.mark.parametrize(("role", "code"), [("owner", 200), ("writer", 200), ("viewer", 403), ("readonly", 403)])
    def test_writers_act(self, api, role, code):
        client, actions, audit = api
        with _as(role):
            res = client.post("/api/obligations/grass/claim-stage2-usdc", json={"action": "mute"})
        assert res.status_code == code
        assert actions.await_count == (1 if code == 200 else 0)
        assert audit.await_count == (1 if code == 200 else 0)

    @pytest.mark.parametrize(("role", "code"), [("owner", 200), ("writer", 404)])
    def test_only_the_owner_acts_on_a_credential_reminder(self, api, role, code):
        # The panel hides credential reminders from everyone but the owner, so a
        # writer must not be able to mute one for the household either.
        client, actions, audit = api
        with _as(role):
            res = client.post("/api/obligations/grass/credential:token", json={"action": "mute"})
        assert res.status_code == code
        assert actions.await_count == (1 if code == 200 else 0)
        assert audit.await_count == (1 if code == 200 else 0)

    def test_done_records_the_occurrence(self, api):
        client, actions, audit = api
        with _as("writer"):
            res = client.post(
                "/api/obligations/grass/claim-stage2-usdc", json={"action": "done", "occurrence": "2027-01-22"}
            )
        assert res.status_code == 200
        assert actions.await_args.kwargs["done_for"] == "2027-01-22"
        assert audit.await_args.args[:2] == ("obligation_done", "grass:claim-stage2-usdc")

    def test_done_keeps_the_other_open_window_done(self):
        # MystNodes on 1 Dec: November's window (closed earlier) and
        # December's are both open. Closing December's keeps November's.
        from app import main

        rule = "claim-monthly-rewards-pool"
        item = _item(slug="mysterium", rule=rule, occurrence="2026-12-01", days_left=30)
        now = datetime(2026, 12, 1, 12, tzinfo=UTC)
        state = {("mysterium", rule): {"done_for": "2026-11-01", "done_at": "2026-11-20"}}
        actions = AsyncMock()
        with (
            patch.object(main, "_evaluate_obligations", AsyncMock(return_value=(Evaluation(items=[item]), now))),
            patch.object(main.database, "get_obligation_state", AsyncMock(return_value=state)),
            patch.object(main.database, "set_obligation_action", actions),
            patch.object(main.database, "add_audit_event", AsyncMock()),
            _as("writer"),
        ):
            res = TestClient(main.app, raise_server_exceptions=False).post(
                f"/api/obligations/mysterium/{rule}", json={"action": "done", "occurrence": "2026-12-01"}
            )
        assert res.status_code == 200
        assert actions.await_args.kwargs["done_for"] == "2026-11-01,2026-12-01"

    def test_snooze_is_a_day_or_a_week(self, api):
        client, actions, _ = api
        with _as("writer"):
            bad = client.post("/api/obligations/grass/claim-stage2-usdc", json={"action": "snooze", "days": 30})
            good = client.post("/api/obligations/grass/claim-stage2-usdc", json={"action": "snooze", "days": 7})
        assert bad.status_code == 400
        assert good.json()["snoozed_until"] == "2026-12-01"

    def test_an_unknown_rule_is_404(self, api):
        client, _, _ = api
        with _as("owner"):
            assert client.post("/api/obligations/grass/made-up", json={"action": "mute"}).status_code == 404

    def test_a_failed_evaluation_is_never_an_all_clear(self):
        from app import main

        with (
            patch.object(main, "_evaluate_obligations", AsyncMock(side_effect=RuntimeError("db locked"))),
            _as("viewer"),
        ):
            res = TestClient(main.app, raise_server_exceptions=False).get("/api/obligations")
        assert res.status_code == 503

    def test_the_routes_are_enumerated(self):
        from tests.route_enumeration import all_paths

        assert {"/api/obligations", "/api/obligations/{slug}/{rule}"} <= all_paths()
