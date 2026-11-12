"""A timeout must say it was a timeout in the worker log.

TimeoutError and httpx's timeout classes have an empty str(), so the worker
logged "Fence guard pass did not finish: " and "Heartbeat failed: " with no
reason at all.
"""

from __future__ import annotations

import asyncio
import logging
import os
from unittest.mock import patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import httpx  # noqa: E402

from app import worker_api  # noqa: E402


def test_a_guard_pass_that_times_out_says_so(caplog):
    async def too_slow(*_a, **_k):
        raise TimeoutError

    with (
        patch.object(worker_api.asyncio, "wait_for", too_slow),
        caplog.at_level(logging.WARNING, logger=worker_api.logger.name),
    ):
        asyncio.run(worker_api._guard_once())
    assert "Fence guard pass did not finish: TimeoutError" in caplog.text


def test_a_fence_check_that_times_out_says_so(caplog):
    async def too_slow(*_a, **_k):
        raise TimeoutError

    with (
        patch.object(worker_api.asyncio, "wait_for", too_slow),
        caplog.at_level(logging.WARNING, logger=worker_api.logger.name),
    ):
        asyncio.run(worker_api._check_fence())
    assert "LAN fence check did not finish: TimeoutError" in caplog.text


def test_a_heartbeat_that_times_out_says_so(caplog):
    class _TimingOutClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            raise httpx.ReadTimeout("")

    with (
        patch.object(worker_api.httpx, "AsyncClient", _TimingOutClient),
        patch.object(worker_api.orchestrator, "get_status", return_value=[]),
        caplog.at_level(logging.WARNING, logger=worker_api.logger.name),
    ):
        asyncio.run(worker_api._send_heartbeat())
    assert "Heartbeat failed: ReadTimeout" in caplog.text


def test_a_message_is_kept_as_it_was():
    assert worker_api._reason(OSError("[Errno -3] Try again")) == "[Errno -3] Try again"
