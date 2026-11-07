"""A phone is offline after three missed reports, not after three minutes.

The Android client reports from WorkManager, whose shortest period is 15
minutes. With the Docker workers' 180 s threshold every phone would be marked
offline, and alerted on, between two ordinary reports. Phones get three missed
periods (45 min); Docker workers keep 180 s.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

try:
    from app.main import _check_stale_workers  # noqa: E402
except ImportError:
    pytest.skip(
        "Requires full app dependencies (fastapi, httpx, etc.) — runs in CI",
        allow_module_level=True,
    )

from unittest.mock import AsyncMock, patch  # noqa: E402

from app import main  # noqa: E402

DOCKER = '{"docker_available": true}'
PHONE = '{"os": "Android", "device_type": "android"}'
# CashPilot-android 0.3.0 sends only os, no device_type.
OLD_PHONE = '{"os": "Android"}'


def _silent_for(minutes: float) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes)).replace(tzinfo=None).isoformat()


def _row(system_info: str, silent_min: float) -> dict:
    return {
        "id": 7,
        "client_id": "cid-pixel",
        "name": "pixel",
        "url": "",
        "status": "online",
        "containers": "[]",
        "apps": "[]",
        "system_info": system_info,
        "last_heartbeat": _silent_for(silent_min),
        "registered_at": "2026-04-01T00:00:00",
        "api_key_enc": "enc",
    }


@pytest.fixture(autouse=True)
def _isolate():
    before = main._collector_alerts
    main._collector_alerts = []
    main._worker_online_streak.clear()
    main._worker_last_offline_push.clear()
    yield
    main._collector_alerts = before
    main._worker_online_streak.clear()
    main._worker_last_offline_push.clear()


def _sweep(row: dict):
    record = AsyncMock(return_value=True)
    mark = AsyncMock(return_value=True)

    async def _send(*a, **kw):
        return 1

    with (
        patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[row]),
        patch("app.main.database.mark_worker_offline_if_unchanged", mark),
        patch("app.main.database.delete_worker", new_callable=AsyncMock),
        patch("app.main.database.record_alert", record),
        patch("app.main.database.clear_alerts", AsyncMock()),
        patch("app.main.notify.send", _send),
    ):
        asyncio.run(_check_stale_workers())
    return mark, record


@pytest.mark.parametrize("info", [PHONE, OLD_PHONE])
def test_phone_between_two_reports_stays_online(info):
    mark, record = _sweep(_row(info, silent_min=16))
    mark.assert_not_awaited()
    record.assert_not_awaited()


def test_phone_after_three_missed_reports_goes_offline_with_its_own_minutes():
    mark, record = _sweep(_row(PHONE, silent_min=46))
    mark.assert_awaited_once()
    msg = record.await_args.args[2]
    assert "over 45 minutes" in msg, msg


def test_docker_worker_keeps_the_three_minute_threshold():
    # Control: the same sweep, a Docker worker silent for 4 minutes, still goes
    # offline, so the phone tests above are not passing because nothing fires.
    mark, record = _sweep(_row(DOCKER, silent_min=4))
    mark.assert_awaited_once()
    assert "over 3 minutes" in record.await_args.args[2]


def test_threshold_reads_decoded_and_raw_system_info():
    assert main._stale_after_seconds({"system_info": PHONE}) == 45 * 60
    assert main._stale_after_seconds({"system_info": {"device_type": "android"}}) == 45 * 60
    assert main._stale_after_seconds({"system_info": "not json"}) == main.STALE_WORKER_SECONDS
    assert main._stale_after_seconds({}) == main.STALE_WORKER_SECONDS
