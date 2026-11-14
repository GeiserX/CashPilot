"""A device the app is still adding to the account gets no "add it by hand" notice.

A new ProxyRack UUID is unknown for about five minutes, so the hourly device
check finds it "invalid" while _retry_device_links is still adding it. The
notice then told the user to add it by hand, and it took the day's notice push
for that service, so the give-up message a day later was never pushed. While a
registration is being retried the device is left out of the notice; once the
retries give up it is reported as before.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from app.collectors.base import EarningsResult
from tests.test_unlinked_devices import UNLINKED, _run_loop


def _ago(hours: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


NOW = _ago(0.1)


def _loop_with_pending(rows):
    with patch("app.main.database.list_pending_device_links", new_callable=AsyncMock, **rows):
        alerts, _, _ = _run_loop(EarningsResult(platform="earnapp", balance=1.0, unlinked_devices=[UNLINKED]))
    return [a for a in alerts if a.get("kind") == "notice" and a["platform"] == "earnapp"]


def test_a_device_being_retried_gets_no_notice():
    pending = [{"slug": "earnapp", "device_id": UNLINKED, "gave_up": 0, "first_at": NOW}]
    assert _loop_with_pending({"return_value": pending}) == []


def test_a_device_whose_retries_gave_up_is_reported_again():
    pending = [{"slug": "earnapp", "device_id": UNLINKED, "gave_up": 1, "first_at": _ago(25)}]
    (notice,) = _loop_with_pending({"return_value": pending})
    assert [d["id"] for d in notice["devices"]] == [UNLINKED]


def test_a_retry_of_another_service_or_device_changes_nothing():
    pending = [
        {"slug": "proxyrack", "device_id": UNLINKED, "gave_up": 0, "first_at": NOW},
        {"slug": "earnapp", "device_id": "sdk-node-" + "c" * 32, "gave_up": 0, "first_at": NOW},
    ]
    (notice,) = _loop_with_pending({"return_value": pending})
    assert [d["id"] for d in notice["devices"]] == [UNLINKED]


def test_an_unreadable_retry_table_keeps_the_plain_notice():
    (notice,) = _loop_with_pending({"side_effect": RuntimeError("db locked")})
    assert [d["id"] for d in notice["devices"]] == [UNLINKED]


def test_a_retry_left_past_its_window_no_longer_hides_the_notice():
    # The retry job never marked it given up (it failed every time); after the
    # day the retries were allowed, the device is reported again.
    pending = [{"slug": "earnapp", "device_id": UNLINKED, "gave_up": 0, "first_at": _ago(25)}]
    (notice,) = _loop_with_pending({"return_value": pending})
    assert [d["id"] for d in notice["devices"]] == [UNLINKED]
