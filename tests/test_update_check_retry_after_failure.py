"""A refused release check is retried within the hour, not the next day.

A home connection shares GitHub's unauthenticated limit (60 requests an hour per
public IP) with everything else in the house. The one check CashPilot makes at
startup was refused with a 403 on a live dashboard, and the old cooldown treated
that failure like a success: nothing asked again for 24 hours, so the update
card said "unknown" and no phone was judged against the Android release for a
whole day after every restart.

The contract now: a check that worked is not repeated for a day; one that failed
is repeated after RETRY_AFTER_FAILURE_SECONDS, and not before.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app import update_check


@pytest.fixture(autouse=True)
def _clean():
    update_check._reset_for_tests()
    yield
    update_check._reset_for_tests()


def _client(*outcomes):
    """An AsyncClient stand-in whose get() yields each outcome in turn."""
    client = AsyncMock()
    client.get.side_effect = list(outcomes)
    client.__aenter__.return_value = client
    return client


def _ok(url, tag):
    return httpx.Response(200, json={"tag_name": tag}, request=httpx.Request("GET", url))


def _rate_limited(url):
    response = httpx.Response(403, json={"message": "API rate limit exceeded"}, request=httpx.Request("GET", url))
    return response


class _Clock:
    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize(
    ("refresh_name", "url", "tag"),
    [
        ("refresh", update_check.LATEST_URL, "v2.0.1"),
        ("refresh_android", update_check.ANDROID_LATEST_URL, "v1.0.1"),
    ],
)
class TestARefusedCheckIsRetriedSoon:
    def _run(self, refresh_name, client, clock):
        with (
            patch.dict("os.environ", {"CASHPILOT_VERSION": "2.0.0"}, clear=False),
            patch("app.update_check.httpx.AsyncClient", return_value=client),
            patch("app.update_check.time.time", clock),
        ):
            return asyncio.run(getattr(update_check, refresh_name)())

    def test_a_403_at_startup_is_retried_after_an_hour_not_a_day(self, refresh_name, url, tag):
        clock = _Clock()
        client = _client(_rate_limited(url), _ok(url, tag))

        assert self._run(refresh_name, client, clock) is None  # startup: refused

        clock.now += update_check.RETRY_AFTER_FAILURE_SECONDS - 1
        assert self._run(refresh_name, client, clock) is None
        assert client.get.await_count == 1, "retried before the failure cooldown ran out"

        clock.now += 1
        assert self._run(refresh_name, client, clock) == tag
        assert client.get.await_count == 2, "a refused check waited longer than the retry window"

    def test_a_check_that_worked_still_waits_a_day(self, refresh_name, url, tag):
        clock = _Clock()
        client = _client(_ok(url, tag), _ok(url, "v9.9.9"))

        assert self._run(refresh_name, client, clock) == tag
        clock.now += update_check.RETRY_AFTER_FAILURE_SECONDS * 5
        assert self._run(refresh_name, client, clock) == tag
        assert client.get.await_count == 1, "a working install asked GitHub more than once a day"

        clock.now = 1_000_000.0 + update_check.CHECK_INTERVAL_SECONDS
        assert self._run(refresh_name, client, clock) == "v9.9.9"
        assert client.get.await_count == 2

    def test_a_failure_after_a_success_keeps_the_known_tag(self, refresh_name, url, tag):
        """A refused retry must not blank what was already known."""
        clock = _Clock()
        client = _client(_ok(url, tag), _rate_limited(url))

        assert self._run(refresh_name, client, clock) == tag
        clock.now += update_check.CHECK_INTERVAL_SECONDS
        assert self._run(refresh_name, client, clock) == tag
        assert client.get.await_count == 2


def test_the_retry_window_is_shorter_than_a_day_and_not_a_hammer():
    assert 15 * 60 <= update_check.RETRY_AFTER_FAILURE_SECONDS < update_check.CHECK_INTERVAL_SECONDS


@pytest.mark.parametrize(
    ("refresh_name", "url"),
    [
        ("refresh", update_check.LATEST_URL),
        ("refresh_android", update_check.ANDROID_LATEST_URL),
    ],
)
def test_a_reply_without_a_usable_tag_keeps_the_known_tag_and_retries_soon(refresh_name, url):
    """A 200 whose tag is not a version is a failed check, not "no release"."""
    clock = _Clock()
    bad = httpx.Response(200, json={"tag_name": "nightly"}, request=httpx.Request("GET", url))
    client = _client(_ok(url, "v1.2.3"), bad, _ok(url, "v1.2.4"))
    with (
        patch.dict("os.environ", {"CASHPILOT_VERSION": "2.0.0"}, clear=False),
        patch("app.update_check.httpx.AsyncClient", return_value=client),
        patch("app.update_check.time.time", clock),
    ):
        refresh = getattr(update_check, refresh_name)
        assert asyncio.run(refresh()) == "v1.2.3"
        clock.now += update_check.CHECK_INTERVAL_SECONDS
        assert asyncio.run(refresh()) == "v1.2.3", "an unusable reply blanked the known tag"
        clock.now += update_check.RETRY_AFTER_FAILURE_SECONDS
        assert asyncio.run(refresh()) == "v1.2.4", "an unusable reply waited a day before the next try"
    assert client.get.await_count == 3


def test_a_tick_just_before_the_cooldown_ends_does_not_cost_a_whole_extra_window():
    """Ticks run every SCHEDULER_TICK_SECONDS from scheduling time; the startup
    check fails a few seconds later, so the first tick at the hour mark is just
    early. The retry must not slip by a whole extra window."""
    clock = _Clock()
    url = update_check.LATEST_URL
    client = _client(_rate_limited(url), _ok(url, "v2.0.1"))
    scheduled_at = clock.now
    with (
        patch.dict("os.environ", {"CASHPILOT_VERSION": "2.0.0"}, clear=False),
        patch("app.update_check.httpx.AsyncClient", return_value=client),
        patch("app.update_check.time.time", clock),
    ):
        clock.now += 5  # the startup check runs a few seconds after the jobs are added
        assert asyncio.run(update_check.refresh()) is None
        tick = 0
        while client.get.await_count < 2:
            tick += 1
            clock.now = scheduled_at + tick * update_check.SCHEDULER_TICK_SECONDS
            asyncio.run(update_check.refresh())
    waited = clock.now - (scheduled_at + 5)
    assert waited < update_check.RETRY_AFTER_FAILURE_SECONDS * 1.5, f"retry came {waited:.0f} s after the failure"
