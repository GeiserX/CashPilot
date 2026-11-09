"""No secret that travels in a request URL may reach the container log.

httpx logs every request at INFO with its full URL, and the root logger of both
containers is at INFO. The Telegram Bot API puts the bot token in the URL path,
so every alert sent to Telegram wrote ``https://api.telegram.org/bot<token>/...``
to ``docker logs cashpilot-ui``. The same line carries a webhook's path token, an
ntfy topic, ``user:password@`` and API keys in query strings.

These tests send real requests through httpx with a mocked transport, capture
what gets logged, and assert the fake secret is nowhere in it while the request
line itself is still logged.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import httpx  # noqa: E402
import pytest  # noqa: E402

from app import log_redaction, notify  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# Obviously fake values, shaped like the real ones.
FAKE_BOT_TOKEN = "123456789:FAKE_TEST_TOKEN_not_a_real_bot_0000000"
FAKE_WEBHOOK_TOKEN = "fake-webhook-token-not-real-0000"
FAKE_NTFY_TOPIC = "fake-private-topic-not-real-0000"
FAKE_USERINFO = "fake-userinfo-not-real"
FAKE_API_KEY = "fake-api-key-not-real-0000"

_NOTIFY_ENV = {
    "CASHPILOT_NTFY_URL": "",
    "CASHPILOT_WEBHOOK_URL": "",
    "CASHPILOT_TELEGRAM_BOT_TOKEN": "",
    "CASHPILOT_TELEGRAM_CHAT_ID": "",
}


@pytest.fixture
def redacting():
    """The record factory as the containers install it, removed afterwards."""
    previous = logging.getLogRecordFactory()
    log_redaction.install()
    yield
    logging.setLogRecordFactory(previous)


class _MockedClient(httpx.AsyncClient):
    """A real httpx client, so httpx's own request logging runs, with no network."""

    def __init__(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
        super().__init__(*args, **kwargs)


def _send_alert(caplog, **env) -> str:
    with (
        patch.dict(os.environ, {**_NOTIFY_ENV, **env}),
        patch.object(notify.httpx, "AsyncClient", _MockedClient),
        caplog.at_level(logging.DEBUG),
    ):
        delivered = asyncio.run(notify.send("Collector failed", "honeygain: timeout"))
    assert delivered == 1
    return caplog.text


class TestNotifierRequests:
    def test_the_telegram_bot_token_is_not_logged(self, redacting, caplog):
        log = _send_alert(caplog, CASHPILOT_TELEGRAM_BOT_TOKEN=FAKE_BOT_TOKEN, CASHPILOT_TELEGRAM_CHAT_ID="42")
        assert FAKE_BOT_TOKEN not in log
        assert "FAKE_TEST_TOKEN" not in log
        # The request is still logged, so you can see the alert went out.
        assert "HTTP Request: POST https://api.telegram.org/bot<redacted>/sendMessage" in log

    def test_a_bot_token_of_any_shape_is_not_logged(self, redacting, caplog):
        """The configured value is redacted even when it does not look like a token."""
        odd = "fake-odd-shaped-bot-token"
        log = _send_alert(caplog, CASHPILOT_TELEGRAM_BOT_TOKEN=odd, CASHPILOT_TELEGRAM_CHAT_ID="42")
        assert odd not in log
        assert "HTTP Request: POST https://api.telegram.org/bot<redacted>/sendMessage" in log

    def test_the_webhook_path_token_is_not_logged(self, redacting, caplog):
        url = f"https://discord.example/api/webhooks/1234/{FAKE_WEBHOOK_TOKEN}"
        log = _send_alert(caplog, CASHPILOT_WEBHOOK_URL=url)
        assert FAKE_WEBHOOK_TOKEN not in log
        assert "HTTP Request: POST https://discord.example/<redacted>" in log

    def test_the_ntfy_topic_and_its_password_are_not_logged(self, redacting, caplog):
        url = f"https://alerts:{FAKE_USERINFO}@ntfy.example/{FAKE_NTFY_TOPIC}"
        log = _send_alert(caplog, CASHPILOT_NTFY_URL=url)
        assert FAKE_NTFY_TOPIC not in log
        assert FAKE_USERINFO not in log
        assert "ntfy.example/<redacted>" in log

    def test_a_webhook_token_in_the_query_is_not_logged(self, redacting, caplog):
        url = f"https://hooks.example/notify?token={FAKE_WEBHOOK_TOKEN}"
        log = _send_alert(caplog, CASHPILOT_WEBHOOK_URL=url)
        assert FAKE_WEBHOOK_TOKEN not in log
        assert "HTTP Request: POST https://hooks.example/<redacted>" in log

    @pytest.mark.parametrize(
        ("env", "url", "logged_host", "secrets"),
        [
            # httpx lowercases the host in its log line.
            (
                "CASHPILOT_WEBHOOK_URL",
                f"https://Hooks.Example/T0/B0/{FAKE_WEBHOOK_TOKEN}",
                "hooks.example",
                [FAKE_WEBHOOK_TOKEN],
            ),
            # ... drops an explicit default port ...
            ("CASHPILOT_NTFY_URL", f"https://ntfy.example:443/{FAKE_NTFY_TOPIC}", "ntfy.example", [FAKE_NTFY_TOPIC]),
            # ... and percent-encodes a space in the path or the query.
            ("CASHPILOT_NTFY_URL", f"https://ntfy.example/{FAKE_NTFY_TOPIC} x", "ntfy.example", [FAKE_NTFY_TOPIC]),
            (
                "CASHPILOT_WEBHOOK_URL",
                f"https://hooks.example/a/{FAKE_WEBHOOK_TOKEN}?x=1&y=fake words",
                "hooks.example",
                [FAKE_WEBHOOK_TOKEN, "fake%20words"],
            ),
        ],
    )
    def test_a_url_httpx_normalizes_is_still_redacted(self, redacting, caplog, env, url, logged_host, secrets):
        log = _send_alert(caplog, **{env: url})
        for secret in secrets:
            assert secret not in log
        assert f"HTTP Request: POST https://{logged_host}/<redacted>" in log


class TestAnyClientRequest:
    """Collectors and the worker log through the same httpx and urllib3 loggers."""

    def test_an_api_key_in_a_collector_query_string_is_not_logged(self, redacting, caplog):
        async def go():
            async with _MockedClient() as client:
                await client.get("https://earn.example/api/balance", params={"api_key": FAKE_API_KEY})

        with caplog.at_level(logging.DEBUG):
            asyncio.run(go())
        assert FAKE_API_KEY not in caplog.text
        assert "https://earn.example/api/balance?api_key=<redacted>" in caplog.text

    @pytest.mark.parametrize("logger_name", ["httpcore.http11", "urllib3.connectionpool", "app.worker_api"])
    def test_other_loggers_are_covered_too(self, redacting, caplog, logger_name):
        with caplog.at_level(logging.DEBUG):
            logging.getLogger(logger_name).warning(
                "GET %s failed", f"https://user:{FAKE_USERINFO}@ui.example/bot{FAKE_BOT_TOKEN}/x"
            )
        assert FAKE_USERINFO not in caplog.text
        assert FAKE_BOT_TOKEN not in caplog.text
        assert "https://<redacted>@ui.example/bot<redacted>/x" in caplog.text

    def test_a_traceback_is_redacted(self, redacting, caplog):
        with caplog.at_level(logging.DEBUG):
            try:
                raise httpx.ConnectError(f"cannot reach https://api.telegram.org/bot{FAKE_BOT_TOKEN}/sendMessage")
            except httpx.ConnectError:
                logging.getLogger("app.notify").exception("send failed")
        assert FAKE_BOT_TOKEN not in caplog.text
        assert "ConnectError" in caplog.text

    def test_an_ordinary_line_is_left_alone(self, redacting, caplog):
        with caplog.at_level(logging.INFO):
            logging.getLogger("httpx").info(
                'HTTP Request: %s %s "%s %d %s"',
                "GET",
                "https://api.honeygain.example/v2/earnings",
                "HTTP/1.1",
                200,
                "OK",
            )
        assert 'HTTP Request: GET https://api.honeygain.example/v2/earnings "HTTP/1.1 200 OK"' in caplog.text

    def test_a_broken_log_call_does_not_raise_in_the_caller(self, redacting):
        """A bad format string is the handler's to report; making the record must not raise."""
        record = logging.getLogRecordFactory()("x", logging.INFO, __file__, 1, "%s %s", ("only one arg",), None)
        assert record.msg == "%s %s"


@pytest.mark.parametrize("module", ["app.main", "app.worker_api"])
def test_both_containers_install_it(module, tmp_path):
    """Each image's entry module installs the redaction when it is imported."""
    code = (
        f"import logging, {module}\n"
        "logging.getLogger('httpx').info('HTTP Request: POST %s', "
        f"'https://api.telegram.org/bot{FAKE_BOT_TOKEN}/sendMessage')\n"
    )
    env = {**os.environ, "CASHPILOT_DATA_DIR": str(tmp_path), "CASHPILOT_API_KEY": "test-fleet-key"}
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert "HTTP Request: POST https://api.telegram.org/bot<redacted>/sendMessage" in result.stderr
    assert FAKE_BOT_TOKEN not in result.stderr + result.stdout
