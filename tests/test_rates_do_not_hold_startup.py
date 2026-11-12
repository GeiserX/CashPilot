"""Exchange rates must not hold startup, and must not pay a redirect.

The UI awaited the first rate refresh inside lifespan. Behind an egress
firewall that drops the request, nothing answered until the 15 s client
timeout ran out. The first collection still waits for the rates, because it
stores the fx rate of every balance it records.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import exchange_rates, main


def _lifespan_patches(refresh, collection):
    return (
        patch("app.main.database.init_db", new_callable=AsyncMock),
        patch("app.main.database.connect_shared", new_callable=AsyncMock),
        patch("app.main.database.close_shared", new_callable=AsyncMock),
        patch("app.main.database.list_users_with_pwd_epoch", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.list_session_revocations", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=True),
        patch("app.main.catalog.load_services"),
        patch("app.main.catalog.register_sighup"),
        patch("app.main.exchange_rates.refresh", refresh),
        patch("app.main.update_check.refresh", new_callable=AsyncMock),
        patch("app.main.update_check.refresh_android", new_callable=AsyncMock),
        patch("app.main._run_collection", collection),
        patch("app.main._run_data_retention", new_callable=AsyncMock),
        patch("app.main._run_rate_backfill", new_callable=AsyncMock),
        patch("app.main._run_activity_purge", new_callable=AsyncMock),
        patch("app.main._run_vacuum", new_callable=AsyncMock),
        patch("app.main._run_proxy_cap_resets", new_callable=AsyncMock),
        patch("app.main._check_windowed_signals", new_callable=AsyncMock),
    )


def test_startup_serves_before_the_rates_answer_and_collects_after():
    rates_answer = None
    collection = AsyncMock()

    async def slow_refresh():
        await rates_answer.wait()

    async def run():
        nonlocal rates_answer
        rates_answer = asyncio.Event()
        patches = _lifespan_patches(slow_refresh, collection)
        for p in patches:
            p.start()
        try:
            # A rate API that never answers must not keep the app from serving.
            async with asyncio.timeout(5):
                async with main.lifespan(main.app):
                    await asyncio.sleep(0.05)
                    assert collection.await_count == 0, "the first collection ran before the rates were known"
                    rates_answer.set()
                    await asyncio.sleep(0.05)
                    assert collection.await_count == 1
        finally:
            for p in reversed(patches):
                p.stop()

    asyncio.run(run())


@pytest.mark.asyncio
async def test_fiat_rates_use_the_current_frankfurter_address():
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"rates": {"EUR": 0.9}}
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    saved = (exchange_rates._fiat_rates, exchange_rates._fiat_last_fetch)
    try:
        await exchange_rates._fetch_fiat(client)
    finally:
        exchange_rates._fiat_rates, exchange_rates._fiat_last_fetch = saved
    # api.frankfurter.app/latest answers 301 to this address on every refresh.
    assert client.get.await_args.args[0] == "https://api.frankfurter.dev/v1/latest"
