"""CashPilot-android-35t (server half): the heartbeat now carries earnings.

The Android client is named CashPilot and shows no money at all. It makes
exactly one HTTP call — ``POST /api/workers/heartbeat`` — and never reads
anything back. Every earnings route goes through ``_require_auth_api``, which
needs a user session, so a per-worker key cannot read any of them; handing a
phone an owner-level credential so it can render a number would be a bad trade.

So the figures ride back on the one call the worker is already authenticated
for.

**The honesty constraint shapes the payload.** Earnings are collected per
PLATFORM from the provider's account. They cannot be attributed to a device: if
two machines run Grass, the provider reports one balance and nothing can split
it. The response therefore never claims a device earned anything — it reports
what the platforms on that device earned, and flags each platform running on
more than one worker so the client can say so too.

And absent stays absent: a platform with no reading is ``null``, never ``0.0``,
and the total sums only what is known.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


def _hb(apps=(), containers=()):
    from app.main import WorkerHeartbeat

    return WorkerHeartbeat(
        name="w",
        client_id="c1",
        apps=[{"slug": s} for s in apps],
        containers=[{"slug": s} for s in containers],
    )


async def _earnings(body, *, earned, workers):
    from app import main

    with (
        patch.object(main.database, "get_earned_by_platform", AsyncMock(return_value=earned)),
        patch.object(main.database, "list_workers", AsyncMock(return_value=workers)),
    ):
        return await main._earnings_for_worker(body)


def _worker(apps=()):
    import json

    return {"apps": json.dumps([{"slug": s} for s in apps]), "containers": "[]", "system_info": "{}"}


class TestItReportsWhatThePlatformsEarned:
    @pytest.mark.asyncio
    async def test_a_platform_with_a_reading_carries_its_figure(self):
        result = await _earnings(_hb(apps=["grass"]), earned={"grass": 12.5}, workers=[_worker(["grass"])])
        assert result["platforms"] == [{"slug": "grass", "usd": 12.5, "shared_with_other_workers": False}]

    @pytest.mark.asyncio
    async def test_it_only_reports_platforms_this_worker_runs(self):
        result = await _earnings(
            _hb(apps=["grass"]), earned={"grass": 1.0, "honeygain": 99.0}, workers=[_worker(["grass"])]
        )
        assert [p["slug"] for p in result["platforms"]] == ["grass"]

    @pytest.mark.asyncio
    async def test_containers_count_as_well_as_apps(self):
        """A Docker worker reports containers; a phone reports apps."""
        result = await _earnings(_hb(containers=["storj"]), earned={"storj": 3.0}, workers=[_worker()])
        assert [p["slug"] for p in result["platforms"]] == ["storj"]

    @pytest.mark.asyncio
    async def test_the_total_is_the_sum_of_what_is_known(self):
        result = await _earnings(
            _hb(apps=["grass", "honeygain"]),
            earned={"grass": 1.5, "honeygain": 2.25},
            workers=[_worker(["grass", "honeygain"])],
        )
        assert result["total_usd"] == pytest.approx(3.75)


class TestAbsentIsNeverZero:
    @pytest.mark.asyncio
    async def test_a_platform_with_no_reading_is_null(self):
        result = await _earnings(_hb(apps=["titan"]), earned={}, workers=[_worker(["titan"])])
        assert result["platforms"][0]["usd"] is None, "a platform nobody has read reported as a number"

    @pytest.mark.asyncio
    async def test_it_names_which_platforms_have_no_readings(self):
        result = await _earnings(
            _hb(apps=["grass", "titan"]), earned={"grass": 1.0}, workers=[_worker(["grass", "titan"])]
        )
        assert result["platforms_without_readings"] == ["titan"]

    @pytest.mark.asyncio
    async def test_the_total_is_null_when_nothing_is_known(self):
        """Not 0.0 — that would state a measurement nobody took."""
        result = await _earnings(_hb(apps=["titan"]), earned={}, workers=[_worker(["titan"])])
        assert result["total_usd"] is None

    @pytest.mark.asyncio
    async def test_the_total_skips_unknowns_rather_than_zeroing_them(self):
        result = await _earnings(
            _hb(apps=["grass", "titan"]), earned={"grass": 4.0}, workers=[_worker(["grass", "titan"])]
        )
        assert result["total_usd"] == pytest.approx(4.0)


class TestItNeverClaimsADeviceEarnedSomething:
    @pytest.mark.asyncio
    async def test_a_platform_on_two_workers_is_flagged_as_shared(self):
        """The provider reports one balance; nothing can split it per device."""
        result = await _earnings(
            _hb(apps=["grass"]), earned={"grass": 10.0}, workers=[_worker(["grass"]), _worker(["grass"])]
        )
        assert result["platforms"][0]["shared_with_other_workers"] is True

    @pytest.mark.asyncio
    async def test_a_platform_on_one_worker_is_not_flagged(self):
        result = await _earnings(
            _hb(apps=["grass"]), earned={"grass": 10.0}, workers=[_worker(["grass"]), _worker(["honeygain"])]
        )
        assert result["platforms"][0]["shared_with_other_workers"] is False

    @pytest.mark.asyncio
    async def test_the_payload_has_no_per_device_figure(self):
        """Guards against a well-meaning future addition of `device_usd`."""
        result = await _earnings(_hb(apps=["grass"]), earned={"grass": 10.0}, workers=[_worker(["grass"])])
        assert not [k for k in result if "device" in k.lower()]


class TestItFailsQuietlyAndHonestly:
    @pytest.mark.asyncio
    async def test_a_worker_reporting_nothing_gets_no_earnings_block(self):
        assert await _earnings(_hb(), earned={"grass": 1.0}, workers=[]) is None

    @pytest.mark.asyncio
    async def test_a_database_failure_returns_none_rather_than_raising(self):
        """The heartbeat is how a fleet stays alive; this must never break it."""
        from app import main

        with patch.object(main.database, "get_earned_by_platform", AsyncMock(side_effect=RuntimeError("db down"))):
            assert await main._earnings_for_worker(_hb(apps=["grass"])) is None

    @pytest.mark.asyncio
    async def test_the_key_is_omitted_entirely_when_unknown(self):
        """Absent key vs empty object: the client must tell unknown from none."""
        import inspect

        from app import main

        source = inspect.getsource(main.api_worker_heartbeat)
        assert 'if earnings is not None:\n        resp["earnings"] = earnings' in source

    @pytest.mark.asyncio
    async def test_the_window_and_currency_are_stated(self):
        result = await _earnings(_hb(apps=["grass"]), earned={"grass": 1.0}, workers=[_worker(["grass"])])
        assert result["window_days"] == 30
        assert result["currency"] == "USD"
