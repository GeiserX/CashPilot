"""A quiet balance is a heads-up judged by the service's own rhythm, never a verdict.

The old rule was "the balance has not moved for 7 recorded days". That alerted
on a daily earner a week late, and on a batch earner (Storj vetting, Mysterium
settlements, Grass epochs) it fired between perfectly normal batches. It also
re-pushed every 24 hours while the balance stayed flat, and fired while the
container was down or the worker offline, which have their own alerts.

The heads-up now waits for longer than max(3 days, 3x the service's median gap
between increases over the last 30 days, its catalog quiet_days), gives a new
service a grace period, holds back unless the container runs and the collector
succeeds, pushes once per quiet spell, and clears only when the balance grows.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app import catalog, database, main

TODAY = "2026-10-29"


def _days_before(n: int) -> str:
    return (datetime.fromisoformat(TODAY) - timedelta(days=n)).strftime("%Y-%m-%d")


def _series(balances: list[float], *, source="server", currency="USD"):
    """One reading per day, oldest first, ending TODAY."""
    n = len(balances)
    return [(source, _days_before(n - 1 - i), b, currency) for i, b in enumerate(balances)]


def verdict(readings, **kw):
    return database.quiet_verdict(readings, TODAY, **kw)


class TestTheBarIsTheServicesOwnRhythm:
    def test_a_daily_earner_is_mentioned_after_more_than_three_quiet_days(self):
        assert verdict(_series([1, 2, 3, 4, 5, 5, 5, 5])) is None, "three quiet days is still normal"
        flat = verdict(_series([1, 2, 3, 4, 5, 5, 5, 5, 5]))
        assert flat["days_flat"] == 4 and flat["usual_gap_days"] == 1

    def test_one_quiet_day_is_never_mentioned(self):
        assert verdict(_series([1, 2, 3, 4, 4])) is None

    def test_a_weekly_earner_waits_three_of_its_own_gaps(self):
        weekly = [1.0] * 7 + [2.0] * 7 + [3.0] * 7 + [4.0]
        balances = weekly + [4.0] * 20  # quiet 20 days after a 7-day rhythm
        assert verdict(_series(balances)) is None, "20 days is under 3 x 7"
        flat = verdict(_series(weekly + [4.0] * 22))
        assert flat["usual_gap_days"] == 7 and flat["days_flat"] == 22

    def test_the_catalog_quiet_days_raises_the_floor(self):
        balances = [1, 2, 3, 4, 5] + [5] * 8
        assert verdict(_series(balances)) is not None, "the control: without an override it is mentioned"
        assert verdict(_series(balances), quiet_days=10) is None

    def test_any_source_growing_counts_as_earning(self):
        a = _series([1, 2, 3] + [3] * 6, source="server")
        b = _series([1, 2, 3, 4, 5, 6, 7, 8, 9], source="worker-b")
        assert verdict(sorted(a + b, key=lambda r: r[1])) is None


class TestPayoutsDoNotMoveTheClock:
    def test_a_payout_drop_is_not_an_increase(self):
        """The drop must not reset the clock to the payout day."""
        balances = [1, 2, 3, 4, 25, 25, 25, 25, 0.5, 0.5]
        flat = verdict(_series(balances))
        assert flat is not None and flat["last_increase"] == _days_before(5)

    def test_earning_after_a_payout_is_earning(self):
        """And a payout followed by growth from a lower base is not quiet."""
        assert verdict(_series([1, 2, 3, 4, 25, 0.2, 0.4, 0.6])) is None


class TestANewServiceGetsAGracePeriod:
    def test_seven_days_by_default(self):
        assert verdict(_series([0.0] * 8)) is None
        flat = verdict(_series([0.0] * 9))
        assert flat["last_increase"] is None and flat["days_flat"] == 8

    def test_the_catalog_quiet_days_extends_it(self):
        """Storj vets a new node for about a month."""
        assert verdict(_series([0.0] * 20), quiet_days=30) is None

    def test_an_old_deploy_does_not_count_against_a_collector_that_just_started(self):
        assert verdict(_series([0.0, 0.0]), first_deployed="2026-01-01 10:00:00") is None

    def test_no_reading_today_is_not_quiet(self):
        """A failing collector stops writing rows; its old ones are not a flatline."""
        stale = [("server", _days_before(n), 5.0, "USD") for n in range(30, 1, -1)]
        assert verdict(stale) is None


def _flat(platform="honeygain"):
    return {
        "platform": platform,
        "days_flat": 5,
        "balance": 4.0,
        "currency": "USD",
        "last_increase": "2026-10-24",
        "usual_gap_days": 1,
        "since": "2026-10-24",
        "last_recorded": TODAY,
    }


class _Check:
    def __init__(self, flat, stored=()):
        self.flat = flat
        self.rows = set(stored)
        self.pushes: list[str] = []
        self.cooldowns: list[int] = []

    async def record(self, kind, subject, message, *, cooldown_hours=24, **_):
        self.cooldowns.append(cooldown_hours)
        if subject in self.rows:
            return None
        self.rows.add(subject)
        return 1

    async def subjects(self, kind):
        return set(self.rows)

    async def clear(self, kind, subject):
        self.rows.discard(subject)

    def run(self, **kw):
        def spawn(coro):
            coro.close()
            self.pushes.append("push")

        with (
            patch.object(main.database, "get_flatlined_services", AsyncMock(return_value=self.flat)),
            patch.object(main.database, "record_alert", self.record),
            patch.object(main.database, "get_alert_subjects", self.subjects),
            patch.object(main.database, "clear_alerts", self.clear),
            patch.object(main, "_spawn", spawn),
        ):
            return asyncio.run(main._flatline_check(**kw))


DEPLOYED = [{"slug": "honeygain", "status": "running", "deployed_at": "2026-09-01 10:00:00"}]
RUNNING = [{"slug": "honeygain", "status": "running"}]


class TestItHoldsBackUnlessEverythingElseIsFine:
    def test_all_preconditions_met_raises_it(self):
        check = _Check([_flat()])
        bell = check.run(collected={"honeygain"}, deployments=DEPLOYED, statuses=RUNNING)
        assert [b["platform"] for b in bell] == ["honeygain"]

    def test_not_while_the_container_is_down(self):
        check = _Check([_flat()])
        bell = check.run(
            collected={"honeygain"}, deployments=DEPLOYED, statuses=[{"slug": "honeygain", "status": "exited"}]
        )
        assert bell == [] and not check.pushes

    def test_not_while_no_online_worker_reports_it(self):
        check = _Check([_flat()])
        assert check.run(collected={"honeygain"}, deployments=DEPLOYED, statuses=[]) == []

    def test_not_while_the_collector_is_failing(self):
        check = _Check([_flat()])
        assert check.run(collected=set(), deployments=DEPLOYED, statuses=RUNNING) == []

    def test_a_service_with_no_container_needs_only_its_collector(self):
        """Grass runs as a browser extension; no worker will ever list it."""
        check = _Check([_flat("grass")])
        external = [{"slug": "grass", "status": "external", "deployed_at": ""}]
        bell = check.run(collected={"grass"}, deployments=external, statuses=[])
        assert [b["platform"] for b in bell] == ["grass"]

    def test_a_held_back_alert_is_not_cleared(self):
        """Clearing it would re-arm a second push when the container comes back."""
        check = _Check([_flat()], stored={"honeygain"})
        check.run(collected={"honeygain"}, deployments=DEPLOYED, statuses=[])
        assert "honeygain" in check.rows


class TestOnePushPerQuietSpell:
    def test_it_pushes_once_and_never_repeats_on_a_timer(self):
        check = _Check([_flat()])
        for _ in range(5):
            check.run(collected={"honeygain"}, deployments=DEPLOYED, statuses=RUNNING)
        assert len(check.pushes) == 1
        assert min(check.cooldowns) > 24 * 365, "the 24 h default would push again every day"

    def test_growth_clears_it_and_re_arms_the_next_spell(self):
        check = _Check([_flat()])
        check.run(collected={"honeygain"}, deployments=DEPLOYED, statuses=RUNNING)
        check.flat = []
        check.run(collected={"honeygain"}, deployments=DEPLOYED, statuses=RUNNING)
        assert not check.rows
        check.flat = [_flat()]
        check.run(collected={"honeygain"}, deployments=DEPLOYED, statuses=RUNNING)
        assert len(check.pushes) == 2


class TestTheWording:
    def test_it_is_informational(self):
        [entry] = _Check([_flat()]).run()
        text = entry["error"]
        assert "hasn't earned since 2026-10-24" in text
        assert "usually earns every day" in text
        assert "Common causes" in text
        assert "clears by itself" in text
        for word in ("remove", "delete", "uninstall", "stop it"):
            assert word not in text.lower(), word


@pytest.mark.parametrize("slug", ["storj", "mysterium", "anyone-protocol", "grass"])
def test_batch_earners_declare_their_quiet_days(slug):
    """The catalog carries the override; app/ holds no per-service numbers."""
    catalog.load_services()
    assert main._quiet_days_by_platform().get(slug, 0) >= 7


class TestADeviceNotOnTheAccountNamesTheCauseAlready:
    """A notice saying a deployed device is not on the account is the specific cause.

    A second, vaguer "gone quiet" for the same service would only repeat it.
    """

    def test_it_holds_back_while_the_device_is_not_linked(self):
        check = _Check([_flat()])
        bell = check.run(collected={"honeygain"}, deployments=DEPLOYED, statuses=RUNNING, unlinked={"honeygain"})
        assert bell == [] and not check.pushes

    def test_another_service_is_unaffected(self):
        """The control: only the service the notice is about is held back."""
        check = _Check([_flat()])
        bell = check.run(collected={"honeygain"}, deployments=DEPLOYED, statuses=RUNNING, unlinked={"earnapp"})
        assert [b["platform"] for b in bell] == ["honeygain"]

    def test_the_collection_run_passes_what_collectors_reported(self):
        """The finding travels on EarningsResult.unlinked_devices, not on the notice text."""
        from types import SimpleNamespace

        results = [
            SimpleNamespace(
                platform="earnapp", balance=1.0, currency="USD", error=None, warning=None, unlinked_devices=["d1"]
            ),
            SimpleNamespace(
                platform="honeygain", balance=2.0, currency="USD", error=None, warning=None, unlinked_devices=[]
            ),
        ]
        seq = iter(results)
        flatline = AsyncMock(return_value=[])
        with (
            patch.object(main.database, "get_deployments", AsyncMock(return_value=[{"slug": "x"}])),
            patch.object(main.database, "get_config", AsyncMock(return_value={})),
            patch.object(main.database, "upsert_earnings", AsyncMock()),
            patch.object(main.database, "record_alert", AsyncMock(return_value=None)),
            patch.object(main.database, "clear_alerts", AsyncMock()),
            patch.object(main, "_detect_payout", AsyncMock(return_value=None)),
            patch.object(main, "_flatline_check", flatline),
            patch.object(main, "_pending_payout_alerts", AsyncMock(return_value=[])),
            patch.object(main, "_offline_worker_alerts", AsyncMock(return_value=[])),
            patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=[])),
            patch.object(main, "_collect_bounded", AsyncMock(side_effect=lambda c: next(seq))),
            patch.object(main, "_collector_alerts", []),
            patch("app.collectors.make_collectors", lambda deployments, config: [object() for _ in results]),
            patch("app.collectors._close_stale", AsyncMock()),
            patch.object(main, "_spawn", lambda coro: coro.close()),
        ):
            asyncio.run(main._run_collection())
        assert flatline.call_args.kwargs["unlinked"] == {"earnapp"}
