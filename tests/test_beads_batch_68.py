"""CashPilot-w0ss: a fleet 33 releases behind, and nothing said so.

Half the machinery already existed -- ``version.skewed()`` compares this build
against each worker -- but nothing knew what the newest PUBLISHED release was, so
there was no reference point outside the deployment.

Three constraints separate a useful feature from an unwelcome one, and all three
are tested here:

* **Silent when unknown.** Offline, disabled, never-run, or a dev build must
  produce nothing at all -- no error, no spinner, and above all no reassuring
  "up to date" that was never earned. Unknown is unknown.
* **Never auto-updates.** This deploys containers and holds credentials.
* **Answerable.** ``CASHPILOT_UPDATE_CHECK=off`` stops the outbound call dead.
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


def _response(payload, status=200):
    request = httpx.Request("GET", update_check.LATEST_URL)
    return httpx.Response(status, json=payload, request=request)


def _refresh_with(response_or_exc, *, version_env="1.16.0", force=True):
    """Drive refresh() against a stubbed transport."""
    with patch.dict("os.environ", {"CASHPILOT_VERSION": version_env}, clear=False):
        client = AsyncMock()
        if isinstance(response_or_exc, Exception):
            client.get.side_effect = response_or_exc
        else:
            client.get.return_value = response_or_exc
        client.__aenter__.return_value = client
        with patch("app.update_check.httpx.AsyncClient", return_value=client):
            return asyncio.run(update_check.refresh(force=force))


class TestItStaysSilentWhenItDoesNotKnow:
    """The rule that makes this safe on an air-gapped install."""

    @pytest.mark.parametrize(
        "failure",
        [
            httpx.ConnectError("no route to host"),
            httpx.ReadTimeout("timed out"),
            httpx.HTTPStatusError("rate limited", request=None, response=None),
            ValueError("not json"),
        ],
    )
    def test_every_failure_means_unknown_not_an_error(self, failure):
        assert _refresh_with(failure) is None
        state = update_check.state()
        assert state["known"] is False
        assert state["behind"] is False, "an unreachable check must never claim you are behind"

    def test_a_failure_does_not_raise(self):
        """refresh() runs on the scheduler. Raising would fire the job-error
        listener and alert on a firewall rule."""
        _refresh_with(httpx.ConnectError("offline"))  # would raise if it did

    def test_never_checked_is_unknown_rather_than_up_to_date(self):
        """The state before the first run must not read as reassurance."""
        with patch.dict("os.environ", {"CASHPILOT_VERSION": "1.16.0"}, clear=False):
            state = update_check.state()
        assert state["known"] is False
        assert state["behind"] is False

    def test_a_dev_build_is_never_told_it_is_behind(self):
        """A checkout reports `dev`. Comparing that to a release number is
        meaningless, and nagging a developer about it is noise."""
        _refresh_with(_response({"tag_name": "v9.9.9"}), version_env="")
        with patch.dict("os.environ", {"CASHPILOT_VERSION": ""}, clear=False):
            state = update_check.state()
        assert state["behind"] is False
        assert state["known"] is False

    def test_a_tag_that_is_not_a_version_is_rejected(self):
        """Third-party JSON. A tag like "nightly" rendered to the operator as a
        version would be worse than saying nothing."""
        assert _refresh_with(_response({"tag_name": "nightly"})) is None
        assert _refresh_with(_response({"tag_name": ""})) is None
        assert _refresh_with(_response(["not", "an", "object"])) is None


class TestItSaysSoWhenThereIsSomethingNewer:
    def test_a_newer_minor_is_reported(self):
        _refresh_with(_response({"tag_name": "v1.20.1"}))
        with patch.dict("os.environ", {"CASHPILOT_VERSION": "1.16.0"}, clear=False):
            state = update_check.state()
        assert state["known"] is True
        assert state["behind"] is True
        assert state["latest"] == "v1.20.1"
        assert state["current"] == "1.16.0"

    def test_the_same_series_is_not_behind(self):
        """Patches inside a series are meant to interoperate; the banner is about
        crossing a minor, which is what the operator has to act on."""
        _refresh_with(_response({"tag_name": "v1.16.9"}))
        with patch.dict("os.environ", {"CASHPILOT_VERSION": "1.16.0"}, clear=False):
            assert update_check.state()["behind"] is False

    def test_a_newer_local_build_is_not_behind(self):
        """Running ahead of the published release happens on a release day."""
        _refresh_with(_response({"tag_name": "v1.16.0"}), version_env="1.17.0")
        with patch.dict("os.environ", {"CASHPILOT_VERSION": "1.17.0"}, clear=False):
            assert update_check.state()["behind"] is False

    def test_minors_are_compared_as_numbers_not_strings(self):
        """1.9 vs 1.10 is where string comparison gets it exactly backwards, and
        this project has passed its tenth minor, so it is live."""
        _refresh_with(_response({"tag_name": "v1.10.0"}))
        with patch.dict("os.environ", {"CASHPILOT_VERSION": "1.9.0"}, clear=False):
            assert update_check.state()["behind"] is True, "1.10 was judged older than 1.9"


class TestItCanBeTurnedOff:
    def test_off_means_no_request_at_all(self):
        """Not "fetch and discard": an operator who disables this expects no
        outbound connection."""
        with patch.dict("os.environ", {"CASHPILOT_UPDATE_CHECK": "off"}, clear=False):
            client = AsyncMock()
            client.__aenter__.return_value = client
            with patch("app.update_check.httpx.AsyncClient", return_value=client) as factory:
                assert asyncio.run(update_check.refresh(force=True)) is None
            factory.assert_not_called()

    @pytest.mark.parametrize("value", ["0", "off", "false", "no", "OFF", "False"])
    def test_the_usual_spellings_all_disable_it(self, value):
        with patch.dict("os.environ", {"CASHPILOT_UPDATE_CHECK": value}, clear=False):
            assert update_check.enabled() is False

    def test_it_is_on_by_default(self):
        """Matching how this application already reaches CoinGecko and
        Frankfurter, and how comparable self-hosted projects behave."""
        import os

        env = {k: v for k, v in os.environ.items() if k != "CASHPILOT_UPDATE_CHECK"}
        with patch.dict("os.environ", env, clear=True):
            assert update_check.enabled() is True


class TestItDoesNotHammerTheEndpoint:
    def test_a_second_call_inside_the_window_does_not_refetch(self):
        with patch.dict("os.environ", {"CASHPILOT_VERSION": "1.16.0"}, clear=False):
            client = AsyncMock()
            client.get.return_value = _response({"tag_name": "v1.20.1"})
            client.__aenter__.return_value = client
            with patch("app.update_check.httpx.AsyncClient", return_value=client):
                asyncio.run(update_check.refresh(force=True))
                asyncio.run(update_check.refresh())
            assert client.get.await_count == 1

    def test_a_failure_also_starts_the_cooldown(self):
        """Otherwise a host that is refusing us gets retried on every call."""
        with patch.dict("os.environ", {"CASHPILOT_VERSION": "1.16.0"}, clear=False):
            client = AsyncMock()
            client.get.side_effect = httpx.ConnectError("offline")
            client.__aenter__.return_value = client
            with patch("app.update_check.httpx.AsyncClient", return_value=client):
                asyncio.run(update_check.refresh(force=True))
                asyncio.run(update_check.refresh())
            assert client.get.await_count == 1

    def test_the_interval_is_a_day_not_a_minute(self):
        assert update_check.CHECK_INTERVAL_SECONDS >= 24 * 60 * 60


class TestItNeverUpdatesAnything:
    def test_the_module_only_ever_reads(self):
        """A GET and nothing else. The banner tells you; you decide."""
        source = (__import__("pathlib").Path(__file__).resolve().parents[1] / "app" / "update_check.py").read_text()
        for forbidden in ("client.post", "client.put", "client.patch", "client.delete", "subprocess", "docker"):
            assert forbidden not in source, f"the update check does more than read: {forbidden}"
