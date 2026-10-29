"""A one-reading balance dip must not leave a payout question up forever.

Honeygain, 2026-08-31: 25.72, then one low reading (a probable payout of 25.65
was filed), then 25.79 the next day. Its payout history is empty, and the
question waited two months for someone to reject it.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app import database, main


@pytest.fixture
def db(tmp_path):
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
        asyncio.run(database.init_db())
        yield


def _pending(platform):
    async def run():
        return [p for p in await database.get_payouts(platform) if not p["confirmed"]]

    return asyncio.run(run())


def test_a_recovered_balance_withdraws_the_question(db):
    asyncio.run(database.record_probable_payout("honeygain", 25.65))
    assert asyncio.run(database.withdraw_recovered_payout("honeygain", 25.79))
    assert _pending("honeygain") == []


def test_a_real_payout_stays_until_answered(db):
    asyncio.run(database.record_probable_payout("honeygain", 25.65))
    # After a cashout the balance restarts near zero and grows slowly.
    assert not asyncio.run(database.withdraw_recovered_payout("honeygain", 0.42))
    assert len(_pending("honeygain")) == 1


def test_an_old_question_is_not_withdrawn(db):
    async def run():
        await database.record_probable_payout("honeygain", 25.65)
        conn = await database._get_db()
        await conn.execute("UPDATE payouts SET detected_at = datetime('now', '-3 days')")
        await conn.commit()
        return await database.withdraw_recovered_payout("honeygain", 30.0)

    assert not asyncio.run(run())
    assert len(_pending("honeygain")) == 1


def test_a_confirmed_payout_is_never_withdrawn(db):
    async def run():
        pid = await database.record_probable_payout("honeygain", 25.65)
        await database.confirm_payout(pid, "PayPal")
        return await database.withdraw_recovered_payout("honeygain", 30.0)

    assert not asyncio.run(run())


def test_detection_withdraws_and_clears_the_alert(db):
    asyncio.run(database.record_probable_payout("honeygain", 25.65))
    result = SimpleNamespace(platform="honeygain", balance=25.79, currency="USD")
    with (
        patch.object(main.database, "get_latest_balance", AsyncMock(return_value=0.07)),
        patch.object(main.database, "clear_alerts", AsyncMock()) as clear,
    ):
        assert asyncio.run(main._detect_payout(result)) is None
    clear.assert_awaited_once_with("payout", "honeygain")
    assert _pending("honeygain") == []
