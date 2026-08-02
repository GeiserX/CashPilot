"""Payouts and payout projection (CashPilot-1og).

Two failures this exists to prevent, and both of them mislead quietly:

* One number doing two jobs. "Earned" went DOWN when the user got paid, because
  the earnings table stores balance snapshots and a payout is invisible in them.
* Nobody could see how far away the payout was. A 20 USD minimum can be months
  on one device, and not knowing that is what makes people quit.

The tests that matter most are the ones about NOT recording and NOT projecting:
an unconfirmed guess written as income corrupts lifetime-earned invisibly, and a
confident wrong date is worse than saying there is not enough data.
"""

from __future__ import annotations

import pytest

from app import payouts

HONEYGAIN = {"slug": "honeygain", "name": "Honeygain", "cashout": {"min_amount": 20.0}}
NO_MINIMUM = {"slug": "x", "name": "X", "cashout": {}}


def series(*balances: float) -> list[dict[str, float]]:
    return [{"balance": b} for b in balances]


class TestNothingIsEverAutoConfirmed:
    """A balance falls for reasons that are not a payout."""

    def test_a_detected_drop_is_never_confirmed(self):
        out = payouts.detect(25.0, 1.0, HONEYGAIN)
        assert out is not None
        assert out["confirmed"] is False

    def test_the_reason_tells_the_user_why_it_is_asking(self):
        out = payouts.detect(25.0, 1.0, HONEYGAIN)
        assert "correction" in out["reason"]
        assert "until you say so" in out["reason"]

    def test_a_drop_smaller_than_the_minimum_is_not_a_payout(self):
        assert payouts.detect(25.0, 24.0, HONEYGAIN) is None

    def test_a_drop_exactly_at_the_minimum_counts(self):
        assert payouts.detect(25.0, 5.0, HONEYGAIN) is not None

    def test_a_rise_is_never_a_payout(self):
        assert payouts.detect(1.0, 25.0, HONEYGAIN) is None

    def test_a_service_with_no_documented_minimum_never_fires(self):
        """Inventing a threshold would fire on every provider correction."""
        assert payouts.detect(1000.0, 0.0, NO_MINIMUM) is None
        assert payouts.detect(1000.0, 0.0, None) is None

    def test_a_malformed_minimum_is_treated_as_undocumented(self):
        for bad in ({"min_amount": "twenty"}, {"min_amount": -5}, {}):
            assert payouts.min_payout({"slug": "x", "cashout": bad}) is None

    def test_a_documented_zero_minimum_is_a_real_answer(self):
        """At least one catalogued service declares min_amount: 0.

        Reading that as "undocumented" would tell a user with no minimum that
        there is nothing to count down to, when in fact they can cash out now.
        """
        zero = {"slug": "x", "cashout": {"min_amount": 0}}
        assert payouts.min_payout(zero) == 0.0
        out = payouts.project(1.23, zero, series(1.0, 1.1, 1.2, 1.23))
        assert out["state"] == payouts.NO_MINIMUM_REQUIRED
        assert "at any time" in out["summary"]

    def test_a_zero_minimum_never_drives_payout_detection(self):
        """Every drop of any size would qualify, so the prompt becomes noise."""
        zero = {"slug": "x", "cashout": {"min_amount": 0}}
        assert payouts.detect(10.0, 0.0, zero) is None


class TestLifetimeCountsConfirmedPayoutsOnly:
    def test_lifetime_is_balance_plus_confirmed(self):
        confirmed = [{"amount": 20.0, "confirmed": 1}, {"amount": 30.0, "confirmed": 1}]
        assert payouts.lifetime_earned(5.0, confirmed) == 55.0

    def test_a_probable_payout_does_not_inflate_lifetime(self):
        """A single misread drop would otherwise inflate earnings forever."""
        assert payouts.lifetime_earned(5.0, [{"amount": 999.0, "confirmed": 0}]) == 5.0

    def test_no_payouts_means_lifetime_equals_balance(self):
        assert payouts.lifetime_earned(7.5, None) == 7.5
        assert payouts.lifetime_earned(7.5, []) == 7.5

    def test_lifetime_never_goes_down_when_you_get_paid(self):
        """The whole point: the number that means "earned" must not fall."""
        before = payouts.lifetime_earned(25.0, [])
        after = payouts.lifetime_earned(0.0, [{"amount": 25.0, "confirmed": 1}])
        assert after >= before


class TestTheRateIgnoresPayouts:
    def test_a_payout_does_not_read_as_negative_earnings(self):
        """Otherwise a cashout drags the projection into nonsense."""
        with_payout = series(1.0, 2.0, 3.0, 0.0, 1.0, 2.0)
        assert payouts.daily_rate(with_payout) > 0

    def test_a_flat_series_earns_nothing(self):
        assert payouts.daily_rate(series(1.0, 1.0, 1.0, 1.0)) == 0.0

    def test_too_little_history_is_unknown_not_zero(self):
        assert payouts.daily_rate(series(1.0)) is None
        assert payouts.daily_rate([]) is None
        assert payouts.daily_rate(None) is None

    def test_the_rate_is_per_day_not_per_reading(self):
        assert payouts.daily_rate(series(0.0, 1.0, 2.0, 3.0)) == 1.0


class TestItRefusesToProjectRatherThanProjectBadly:
    def test_not_enough_history_says_exactly_that(self):
        out = payouts.project(1.0, HONEYGAIN, series(1.0))
        assert out["state"] == payouts.NOT_ENOUGH_DATA
        assert out["days"] is None
        assert "not enough history" in out["summary"]

    def test_a_service_earning_nothing_says_it_will_not_get_there(self):
        """Different problem from "not enough data", and a different fix."""
        out = payouts.project(1.0, HONEYGAIN, series(1.0, 1.0, 1.0, 1.0))
        assert out["state"] == payouts.NOT_EARNING
        assert out["days"] is None
        assert "will not get there" in out["summary"]

    def test_an_absurdly_distant_date_is_not_rendered_as_a_date(self):
        """ "Four years" is not a plan, and a precise date invites belief."""
        out = payouts.project(0.0, HONEYGAIN, series(0.0, 0.001, 0.002, 0.003))
        assert out["state"] == payouts.TOO_FAR
        assert out["days"] is None
        assert "over a year" in out["summary"]

    def test_a_reachable_balance_says_cash_out_now(self):
        out = payouts.project(25.0, HONEYGAIN, series(1.0, 2.0, 3.0))
        assert out["state"] == payouts.REACHED
        assert out["days"] == 0

    def test_a_service_with_no_minimum_has_nothing_to_count_down_to(self):
        out = payouts.project(5.0, NO_MINIMUM, series(1.0, 2.0, 3.0, 4.0))
        assert out["state"] == payouts.NO_THRESHOLD

    def test_a_real_projection_reports_days_and_the_rate(self):
        out = payouts.project(10.0, HONEYGAIN, series(1.0, 2.0, 3.0, 4.0, 5.0))
        assert out["state"] == payouts.PROJECTED
        assert out["days"] == pytest.approx(10.0, abs=0.5)
        assert out["rate_per_day"] == 1.0
        assert out["remaining"] == 10.0

    def test_every_state_carries_a_sentence_a_user_can_act_on(self):
        cases = [
            (1.0, HONEYGAIN, series(1.0)),
            (1.0, HONEYGAIN, series(1.0, 1.0, 1.0)),
            (25.0, HONEYGAIN, series(1.0, 2.0, 3.0)),
            (5.0, NO_MINIMUM, series(1.0, 2.0, 3.0, 4.0)),
            (10.0, HONEYGAIN, series(1.0, 2.0, 3.0, 4.0, 5.0)),
        ]
        for balance, service, history in cases:
            out = payouts.project(balance, service, history)
            assert out["summary"] and out["summary"].endswith(".")


class TestAgainstTheRealCatalog:
    def test_documented_minimums_are_read_from_the_catalog(self):
        from app import catalog

        assert payouts.min_payout(catalog.get_service("honeygain")) == 20.0
        assert payouts.min_payout(catalog.get_service("storj")) == 4.0

    def test_every_catalogued_minimum_is_a_usable_number(self):
        """A malformed min_amount silently disables payout detection."""
        from app import catalog

        for svc in catalog.get_services():
            raw = (svc.get("cashout") or {}).get("min_amount")
            if raw is None:
                continue
            assert payouts.min_payout(svc) is not None, (
                f"{svc['slug']}: cashout.min_amount {raw!r} does not parse, so payout detection "
                "and the projection are both silently off for this service"
            )


class TestEndpoints:
    def _call(self, fn, *args, **patches):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from app import main

        with (
            # Stand in for an authorized caller. Reads need auth; confirm/reject
            # need writer. Which guard each endpoint actually enforces is the
            # subject of tests/test_audit_guards.py, not of these.
            patch.object(main, "_require_auth_api", lambda r: None),
            patch.object(main, "_require_writer", lambda r: None),
            patch.object(main.database, "get_latest_balance", AsyncMock(return_value=patches.get("balance"))),
            patch.object(main.database, "get_balance_history", AsyncMock(return_value=patches.get("history", []))),
            patch.object(main.database, "get_payouts", AsyncMock(return_value=patches.get("payouts", []))),
            patch.object(main.database, "confirm_payout", AsyncMock(return_value=patches.get("ok", True))),
            patch.object(main.database, "reject_payout", AsyncMock(return_value=patches.get("ok", True))),
        ):
            return asyncio.run(fn(MagicMock(), *args))

    def test_progress_splits_balance_from_lifetime(self):
        from app import main

        out = self._call(
            main.api_payout_progress,
            "honeygain",
            balance=5.0,
            history=series(1.0, 2.0, 3.0, 4.0, 5.0),
            payouts=[{"amount": 20.0, "confirmed": 1}],
        )
        assert out["current_balance"] == 5.0
        assert out["lifetime_earned"] == 25.0, "lifetime must include the confirmed payout"
        assert out["projection"]["state"] == payouts.PROJECTED

    def test_progress_for_a_never_collected_service_says_the_balance_is_unknown(self):
        from app import main

        out = self._call(main.api_payout_progress, "honeygain", balance=None)
        assert out["balance_known"] is False
        assert out["projection"]["state"] == payouts.NOT_ENOUGH_DATA

    def test_an_unknown_service_is_a_404(self):
        from fastapi import HTTPException

        from app import main

        with pytest.raises(HTTPException) as exc:
            self._call(main.api_payout_progress, "no-such-service")
        assert exc.value.status_code == 404

    def test_listing_separates_probable_from_confirmed(self):
        from app import main

        rows = [{"id": 1, "confirmed": 1, "amount": 20.0}, {"id": 2, "confirmed": 0, "amount": 5.0}]
        out = self._call(main.api_payouts, payouts=rows)
        assert [r["id"] for r in out["confirmed"]] == [1]
        assert [r["id"] for r in out["probable"]] == [2]

    def test_confirming_a_missing_payout_is_a_404(self):
        from fastapi import HTTPException

        from app import main

        with pytest.raises(HTTPException) as exc:
            self._call(main.api_confirm_payout, 99, ok=False)
        assert exc.value.status_code == 404

    def test_rejecting_a_missing_payout_is_a_404(self):
        from fastapi import HTTPException

        from app import main

        with pytest.raises(HTTPException) as exc:
            self._call(main.api_reject_payout, 99, ok=False)
        assert exc.value.status_code == 404

    def test_confirm_and_reject_report_what_they_did(self):
        from app import main

        assert self._call(main.api_confirm_payout, 1)["confirmed"] is True
        assert self._call(main.api_reject_payout, 1)["removed"] is True


class TestDetectionIsHookedIntoCollectionSafely:
    def _result(self, platform="honeygain", balance=1.0, currency="USD"):
        from app.collectors.base import EarningsResult

        return EarningsResult(platform=platform, balance=balance, currency=currency)

    def test_a_first_ever_reading_is_not_a_payout(self):
        """Nothing to compare against; an absent history is not a balance of zero."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        from app import main

        with (
            patch.object(main.database, "get_latest_balance", AsyncMock(return_value=None)),
            patch.object(main.database, "record_probable_payout", AsyncMock()) as record,
        ):
            asyncio.run(main._detect_payout(self._result()))
        record.assert_not_awaited()

    def test_a_real_drop_is_recorded_and_alerted(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from app import main

        with (
            patch.object(main.database, "get_latest_balance", AsyncMock(return_value=25.0)),
            patch.object(main.database, "record_probable_payout", AsyncMock(return_value=7)) as record,
            patch.object(main.database, "record_alert", AsyncMock(return_value=True)) as alert,
        ):
            asyncio.run(main._detect_payout(self._result(balance=1.0)))
        record.assert_awaited_once()
        alert.assert_awaited_once()

    def test_a_pending_duplicate_does_not_alert_again(self):
        """One event must not produce a growing pile of identical prompts."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        from app import main

        with (
            patch.object(main.database, "get_latest_balance", AsyncMock(return_value=25.0)),
            patch.object(main.database, "record_probable_payout", AsyncMock(return_value=None)),
            patch.object(main.database, "record_alert", AsyncMock()) as alert,
        ):
            asyncio.run(main._detect_payout(self._result(balance=1.0)))
        alert.assert_not_awaited()

    def test_a_failure_here_never_breaks_earnings_collection(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from app import main

        with patch.object(main.database, "get_latest_balance", AsyncMock(side_effect=RuntimeError("db down"))):
            asyncio.run(main._detect_payout(self._result()))


class TestThePayoutTableAgainstRealSqlite:
    """The SQL, executed rather than mocked.

    Everything above mocks the database, which proves the logic and nothing
    about whether the statements are valid. These are new tables, new indexes
    and new queries; a typo in one would pass every test above and fail the
    first time a real payout was recorded.
    """

    @pytest.fixture
    def db(self, tmp_path):
        import asyncio
        from unittest.mock import patch

        from app import database

        with (
            patch.object(database, "DB_DIR", tmp_path),
            patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"),
        ):
            asyncio.run(database.init_db())
            yield database

    def _run(self, coro):
        import asyncio

        return asyncio.run(coro)

    def test_the_table_and_index_are_created(self, db):
        async def check():
            conn = await db._get_db()
            try:
                cur = await conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','index')")
                return {r["name"] for r in await cur.fetchall()}
            finally:
                await conn.close()

        names = self._run(check())
        assert "payouts" in names
        assert "idx_payouts_platform" in names

    def test_a_probable_payout_round_trips(self, db):
        payout_id = self._run(db.record_probable_payout("honeygain", 20.0, "USD", 1.0))
        assert payout_id
        rows = self._run(db.get_payouts(platform="honeygain"))
        assert len(rows) == 1
        assert rows[0]["amount"] == 20.0
        assert rows[0]["confirmed"] == 0, "a detected drop must never start confirmed"

    def test_a_second_probable_payout_is_not_filed_while_one_is_pending(self, db):
        """One event must not become a growing pile of identical prompts."""
        assert self._run(db.record_probable_payout("honeygain", 20.0))
        assert self._run(db.record_probable_payout("honeygain", 20.0)) is None
        assert len(self._run(db.get_payouts(platform="honeygain"))) == 1

    def test_confirming_marks_it_and_stamps_the_time(self, db):
        payout_id = self._run(db.record_probable_payout("honeygain", 20.0))
        assert self._run(db.confirm_payout(payout_id, method="paypal")) is True
        row = self._run(db.get_payouts(platform="honeygain"))[0]
        assert row["confirmed"] == 1
        assert row["method"] == "paypal"
        assert row["confirmed_at"]

    def test_confirming_twice_is_refused(self, db):
        payout_id = self._run(db.record_probable_payout("honeygain", 20.0))
        assert self._run(db.confirm_payout(payout_id)) is True
        assert self._run(db.confirm_payout(payout_id)) is False

    def test_a_confirmed_payout_cannot_be_rejected(self, db):
        """Rejection deletes; allowing it after confirmation would erase income."""
        payout_id = self._run(db.record_probable_payout("honeygain", 20.0))
        self._run(db.confirm_payout(payout_id))
        assert self._run(db.reject_payout(payout_id)) is False
        assert len(self._run(db.get_payouts(platform="honeygain"))) == 1

    def test_rejecting_removes_it_entirely(self, db):
        payout_id = self._run(db.record_probable_payout("honeygain", 20.0))
        assert self._run(db.reject_payout(payout_id)) is True
        assert self._run(db.get_payouts(platform="honeygain")) == []

    def test_confirmed_only_filters_out_the_probable(self, db):
        confirmed = self._run(db.record_probable_payout("honeygain", 20.0))
        self._run(db.confirm_payout(confirmed))
        self._run(db.record_probable_payout("iproyal", 5.0))
        rows = self._run(db.get_payouts(confirmed_only=True))
        assert [r["platform"] for r in rows] == ["honeygain"]

    def test_totals_use_the_rate_recorded_when_the_payout_landed(self, db):
        """A token payout must not be restated by today's price."""
        payout_id = self._run(db.record_probable_payout("mysterium", 10.0, "MYST", 0.25))
        self._run(db.confirm_payout(payout_id))
        totals = self._run(db.get_confirmed_payout_totals())
        assert totals["mysterium"] == pytest.approx(2.5)

    def test_a_missing_rate_is_treated_as_one_to_one(self, db):
        payout_id = self._run(db.record_probable_payout("honeygain", 7.0, "USD", None))
        self._run(db.confirm_payout(payout_id))
        assert self._run(db.get_confirmed_payout_totals())["honeygain"] == pytest.approx(7.0)

    def test_unconfirmed_payouts_are_excluded_from_totals(self, db):
        self._run(db.record_probable_payout("honeygain", 99.0, "USD", 1.0))
        assert self._run(db.get_confirmed_payout_totals()) == {}


class TestBalanceHistoryAgainstRealSqlite:
    @pytest.fixture
    def db(self, tmp_path):
        import asyncio
        from unittest.mock import patch

        from app import database

        with (
            patch.object(database, "DB_DIR", tmp_path),
            patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"),
        ):
            asyncio.run(database.init_db())
            yield database

    def _run(self, coro):
        import asyncio

        return asyncio.run(coro)

    def test_a_platform_never_seen_has_no_balance(self, db):
        """None, not zero: a first reading has nothing to compare against."""
        assert self._run(db.get_latest_balance("honeygain")) is None

    def test_the_latest_balance_is_the_most_recent_reading(self, db):
        self._run(db.upsert_earnings("honeygain", 1.0, "USD", date="2026-01-01"))
        self._run(db.upsert_earnings("honeygain", 5.0, "USD", date="2026-01-02"))
        assert self._run(db.get_latest_balance("honeygain")) == 5.0

    def test_history_comes_back_oldest_first(self, db):
        from datetime import UTC, datetime, timedelta

        today = datetime.now(UTC)
        for offset, balance in ((2, 1.0), (1, 2.0), (0, 3.0)):
            day = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
            self._run(db.upsert_earnings("honeygain", balance, "USD", date=day))
        history = self._run(db.get_balance_history("honeygain", days=30))
        assert [row["balance"] for row in history] == [1.0, 2.0, 3.0]

    def test_history_for_an_unknown_platform_is_empty(self, db):
        assert self._run(db.get_balance_history("nope")) == []
