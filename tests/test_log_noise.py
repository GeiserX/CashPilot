"""Two warnings that fired on every cycle about things that are not faults.

``app.database`` warned that earnings totals were understated each time any
total was computed, because Grass rows are in GRASS points, which CashPilot
deliberately leaves unpriced: they are not the token, so there is no rate to
miss. Every Grass user got the warning forever, about 1,700 times in six hours
on our own instance, which buried the real case (a token whose rate is
genuinely missing).

``app.main`` warned on every health check that an Android worker "cannot read
Docker". A phone has no Docker by design, so it can never host a missing
container, and treating it as blind also switched missing-container downtime off
for the whole fleet whenever a phone was online.

Both warnings now speak once per change of state, and only about real gaps.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import database, main


def _day(n: int) -> str:
    return (datetime.now(UTC) - timedelta(days=n)).strftime("%Y-%m-%d")


def _understated(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "understated" in r.getMessage()]


class _Db:
    """A throwaway database holding the given readings."""

    def __init__(self, tmp_path, name, readings):
        self.tmp_path, self.name, self.readings = tmp_path, name, readings

    def run(self, coro_fn):
        async def go():
            with (
                patch.object(database, "DB_DIR", self.tmp_path),
                patch.object(database, "DB_PATH", self.tmp_path / f"{self.name}.db"),
            ):
                await database.init_db()
                for platform, days_ago, balance, currency, rate in self.readings:
                    await database.upsert_earnings(
                        platform, balance, currency=currency, date=_day(days_ago), fx_rate_usd=rate
                    )
                return await coro_fn()

        return asyncio.run(go())


GRASS = [("grass", 2, 100.0, "GRASS", None), ("grass", 1, 110.0, "GRASS", None)]
UNRATED_MYST = [("mysterium", 2, 10.0, "MYST", None), ("mysterium", 1, 11.0, "MYST", None)]


class TestPointsAreNotMissingMoney:
    def test_grass_points_do_not_warn(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger="app.database"):
            _Db(tmp_path, "g", GRASS).run(lambda: database.get_earned_by_platform(days=30))
        assert not _understated(caplog)

    def test_a_token_with_no_rate_still_warns(self, tmp_path, caplog):
        """The control: the warning must survive for a genuinely missing rate."""
        with caplog.at_level(logging.WARNING, logger="app.database"):
            _Db(tmp_path, "m", UNRATED_MYST).run(lambda: database.get_earned_by_platform(days=30))
        messages = _understated(caplog)
        assert messages and "mysterium" in messages[0]

    def test_grass_points_do_not_warn_on_the_dashboard_cards_either(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger="app.database"):
            _Db(tmp_path, "d", GRASS).run(database.get_earnings_dashboard_summary)
            _Db(tmp_path, "c", GRASS).run(lambda: database.get_daily_earnings(days=7))
        assert not _understated(caplog)

    @pytest.mark.asyncio
    async def test_the_headline_does_not_call_points_a_partial_total(self):
        """unpriced_platforms says the Total is missing money; points are not money."""
        rows = [
            {"platform": "grass", "balance": 1200.0, "currency": "GRASS", "date": "d", "fx_rate_usd": None},
            {"platform": "mysterium", "balance": 10.0, "currency": "MYST", "date": "d", "fx_rate_usd": None},
        ]
        with (
            patch.object(main, "_require_auth_api", lambda r: None),
            patch.object(main, "_require_reader", lambda r: None),
            patch.object(
                database,
                "get_earnings_dashboard_summary",
                AsyncMock(
                    return_value={"total": 0.0, "today": 0.0, "month": 0.0, "today_change": 0.0, "month_change": None}
                ),
            ),
            patch.object(database, "get_earnings_summary", AsyncMock(return_value=rows)),
            patch.object(database, "get_config", AsyncMock(return_value={})),
            patch.object(database, "get_confirmed_payout_totals", AsyncMock(return_value={})),
            patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=[])),
            patch.object(main.exchange_rates, "to_usd", lambda amt, cur: None),
        ):
            out = await main.api_earnings_summary(MagicMock())
        assert out["unpriced_platforms"] == ["mysterium"]


class TestAGenuineGapIsReportedOncePerChange:
    def test_the_same_gap_is_logged_once(self, tmp_path, caplog):
        db = _Db(tmp_path, "once", UNRATED_MYST)
        with caplog.at_level(logging.WARNING, logger="app.database"):
            for _ in range(5):
                db.run(lambda: database.get_earned_by_platform(days=30))
        assert len(_understated(caplog)) == 1

    def test_a_new_platform_joining_the_gap_is_logged_again(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger="app.database"):
            _Db(tmp_path, "a", UNRATED_MYST).run(lambda: database.get_earned_by_platform(days=30))
            more = UNRATED_MYST + [("anyone", 2, 5.0, "ANYONE", None), ("anyone", 1, 6.0, "ANYONE", None)]
            _Db(tmp_path, "b", more).run(lambda: database.get_earned_by_platform(days=30))
        assert len(_understated(caplog)) == 2

    def test_the_gap_closing_is_said_once_and_rearms_the_warning(self, tmp_path, caplog):
        with caplog.at_level(logging.INFO, logger="app.database"):
            _Db(tmp_path, "x", UNRATED_MYST).run(lambda: database.get_earned_by_platform(days=30))
            priced = [("mysterium", 2, 10.0, "MYST", 0.1), ("mysterium", 1, 11.0, "MYST", 0.1)]
            _Db(tmp_path, "y", priced).run(lambda: database.get_earned_by_platform(days=30))
            _Db(tmp_path, "z", priced).run(lambda: database.get_earned_by_platform(days=30))
            _Db(tmp_path, "w", UNRATED_MYST).run(lambda: database.get_earned_by_platform(days=30))
        assert len(_understated(caplog)) == 2
        assert len([r for r in caplog.records if "priced again" in r.getMessage()]) == 1


def _worker(name, *, docker, device_type=None):
    info = {"docker_available": docker}
    if device_type:
        info["device_type"] = device_type
    return {
        "id": hash(name) % 1000,
        "client_id": f"cid-{name}",
        "name": name,
        "status": "online",
        "containers": "[]",
        "apps": "[]",
        "system_info": json.dumps(info),
        "last_heartbeat": "2026-10-29T00:00:00",
    }


def _health_check(workers):
    recorded = AsyncMock()
    with (
        patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
        patch(
            "app.main.database.get_deployments",
            new_callable=AsyncMock,
            return_value=[{"slug": "honeygain", "status": "running"}],
        ),
        patch("app.main.database.record_health_events", recorded),
    ):
        asyncio.run(main._run_health_check())
    return list(recorded.call_args.args[0]) if recorded.call_args else []


def _blind_warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "cannot read Docker" in r.getMessage()]


class TestAPhoneIsNotABlindDockerHost:
    def test_an_android_worker_does_not_warn(self, caplog):
        phone = _worker("motorola", docker=False, device_type="android")
        with caplog.at_level(logging.WARNING, logger="app.main"):
            _health_check([_worker("watchtower", docker=True), phone])
        assert not _blind_warnings(caplog)

    def test_an_android_worker_does_not_switch_off_missing_container_downtime(self):
        """A phone cannot host the missing container, so the evidence still holds."""
        phone = _worker("motorola", docker=False, device_type="android")
        events = _health_check([_worker("watchtower", docker=True), phone])
        assert ("honeygain", "check_down", "missing from heartbeat") in events

    def test_a_blind_server_still_suppresses_and_warns(self, caplog):
        """The control: the safety behaviour for a real Docker host is unchanged."""
        with caplog.at_level(logging.WARNING, logger="app.main"):
            events = _health_check([_worker("geiserback", docker=False)])
        assert not [e for e in events if e[2] == "missing from heartbeat"]
        assert any("geiserback" in m for m in _blind_warnings(caplog))

    def test_a_blind_server_is_warned_about_once_per_change(self, caplog):
        with caplog.at_level(logging.INFO, logger="app.main"):
            for _ in range(4):
                _health_check([_worker("geiserback", docker=False)])
            _health_check([_worker("geiserback", docker=False), _worker("geiserct", docker=False)])
            _health_check([_worker("geiserback", docker=True)])
            _health_check([_worker("geiserback", docker=True)])
        assert len(_blind_warnings(caplog)) == 2
        assert len([r for r in caplog.records if "can read Docker again" in r.getMessage()]) == 1
