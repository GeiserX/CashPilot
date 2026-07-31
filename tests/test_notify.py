"""Tests for out-of-band alert delivery (app/notify.py).

Two properties matter most and are asserted explicitly:
  * the module is completely inert until a target is configured (existing
    deployments must be unaffected), and
  * a failing notifier never raises, because it runs inside the earnings
    collection cycle and must not be able to break it.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

from app import notify  # noqa: E402

_ALL_TARGET_VARS = {
    "CASHPILOT_NTFY_URL": "",
    "CASHPILOT_WEBHOOK_URL": "",
    "CASHPILOT_TELEGRAM_BOT_TOKEN": "",
    "CASHPILOT_TELEGRAM_CHAT_ID": "",
}


def _env(**overrides):
    """Env with every notification target cleared, then the given ones set."""
    return patch.dict(os.environ, {**_ALL_TARGET_VARS, **overrides})


def _mock_client():
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=MagicMock(status_code=200))
    return client


class TestConfiguration:
    def test_inert_by_default(self):
        with _env():
            assert notify.configured_targets() == []
            assert notify.is_enabled() is False

    def test_each_target_detected(self):
        with _env(CASHPILOT_NTFY_URL="https://ntfy.sh/t"):
            assert notify.configured_targets() == ["ntfy"]
        with _env(CASHPILOT_WEBHOOK_URL="https://example.com/hook"):
            assert notify.configured_targets() == ["webhook"]
        with _env(CASHPILOT_TELEGRAM_BOT_TOKEN="tok", CASHPILOT_TELEGRAM_CHAT_ID="123"):
            assert notify.configured_targets() == ["telegram"]

    def test_telegram_needs_both_token_and_chat_id(self):
        with _env(CASHPILOT_TELEGRAM_BOT_TOKEN="tok"):
            assert notify.configured_targets() == []
        with _env(CASHPILOT_TELEGRAM_CHAT_ID="123"):
            assert notify.configured_targets() == []

    def test_whitespace_only_value_is_not_configuration(self):
        with _env(CASHPILOT_NTFY_URL="   "):
            assert notify.configured_targets() == []


@pytest.mark.asyncio
class TestSend:
    async def test_inert_send_makes_no_request(self):
        client = _mock_client()
        with _env(), patch("app.notify.httpx.AsyncClient", return_value=client):
            assert await notify.send("t", "m") == 0
        client.post.assert_not_called()

    async def test_ntfy_posts_body_with_title_header(self):
        client = _mock_client()
        with (
            _env(CASHPILOT_NTFY_URL="https://ntfy.sh/topic"),
            patch("app.notify.httpx.AsyncClient", return_value=client),
        ):
            assert await notify.send("Title", "Body") == 1
        url = client.post.call_args.args[0]
        kwargs = client.post.call_args.kwargs
        assert url == "https://ntfy.sh/topic"
        assert kwargs["content"] == b"Body"
        assert kwargs["headers"]["Title"] == "Title"

    async def test_webhook_posts_structured_json(self):
        client = _mock_client()
        with (
            _env(CASHPILOT_WEBHOOK_URL="https://example.com/hook"),
            patch("app.notify.httpx.AsyncClient", return_value=client),
        ):
            assert await notify.send("Title", "Body", kind="collector", subject="honeygain") == 1
        payload = client.post.call_args.kwargs["json"]
        assert payload == {"title": "Title", "message": "Body", "kind": "collector", "subject": "honeygain"}

    async def test_telegram_uses_bot_api_with_chat_id(self):
        client = _mock_client()
        with (
            _env(CASHPILOT_TELEGRAM_BOT_TOKEN="tok", CASHPILOT_TELEGRAM_CHAT_ID="42"),
            patch("app.notify.httpx.AsyncClient", return_value=client),
        ):
            assert await notify.send("Title", "Body") == 1
        assert client.post.call_args.args[0] == "https://api.telegram.org/bottok/sendMessage"
        assert client.post.call_args.kwargs["json"]["chat_id"] == "42"

    async def test_all_targets_receive_the_alert(self):
        client = _mock_client()
        with (
            _env(
                CASHPILOT_NTFY_URL="https://ntfy.sh/t",
                CASHPILOT_WEBHOOK_URL="https://example.com/hook",
                CASHPILOT_TELEGRAM_BOT_TOKEN="tok",
                CASHPILOT_TELEGRAM_CHAT_ID="42",
            ),
            patch("app.notify.httpx.AsyncClient", return_value=client),
        ):
            assert await notify.send("t", "m") == 3
        assert client.post.await_count == 3

    async def test_failing_target_never_raises_and_others_still_deliver(self):
        # The caller is the collection cycle: a dead notifier must not break it.
        client = _mock_client()
        client.post = AsyncMock(side_effect=[RuntimeError("ntfy down"), MagicMock(status_code=200)])
        with (
            _env(CASHPILOT_NTFY_URL="https://ntfy.sh/t", CASHPILOT_WEBHOOK_URL="https://example.com/hook"),
            patch("app.notify.httpx.AsyncClient", return_value=client),
        ):
            delivered = await notify.send("t", "m")
        assert delivered == 1  # webhook still got it
