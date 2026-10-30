"""A timeout must never look like a successful $0 reading.

A real httpx timeout has an empty ``str(exc)``. Collectors put that into
``EarningsResult.error``, an empty error is falsy, so the hourly collection
stored balance 0 as a success and the credential test said the provider
"accepted these credentials". This runs every registered collector against a
transport that times out with an empty message.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import httpx
import pytest

from app import credential_test
from app.collectors import _COLLECTOR_ARGS, COLLECTOR_MAP
from app.collectors.base import EarningsResult


async def _timeout(self, request, *args, **kwargs):
    raise httpx.ReadTimeout("", request=request)


async def _no_sleep(*_a, **_k):
    return None


def _args(slug: str) -> dict[str, str]:
    return {k.lstrip("?"): "dummy-value" for k in _COLLECTOR_ARGS[slug] if not k.startswith("?")}


@pytest.mark.parametrize("slug", sorted(COLLECTOR_MAP))
def test_empty_timeout_is_a_failure(slug, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    collector = COLLECTOR_MAP[slug](**_args(slug))

    async def run():
        with (
            patch.object(httpx.AsyncClient, "send", _timeout),
            patch("asyncio.sleep", _no_sleep),
        ):
            try:
                return await collector.collect()
            except httpx.TimeoutException:
                return None  # raising is a failure too; the loop counts it
            finally:
                await collector.close()

    result = asyncio.run(run())
    if result is None:
        return
    assert result.error, f"{slug}: a timeout was reported as a successful reading"
    assert credential_test.classify(result.error) != credential_test.OK


def test_empty_error_string_is_never_kept():
    assert EarningsResult(platform="x", balance=0.0, error="").error
    assert EarningsResult(platform="x", balance=0.0, error="  ").error
    assert EarningsResult(platform="x", balance=1.0).error is None


def test_describe_exception_names_the_type():
    from app.collectors.base import describe_exception

    assert describe_exception(httpx.ReadTimeout("")) == "ReadTimeout"
    assert describe_exception(ValueError("bad")) == "ValueError: bad"
    assert credential_test.classify(describe_exception(httpx.ReadTimeout(""))) == credential_test.UNREACHABLE
