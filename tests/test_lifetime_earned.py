"""Cashing out must not make CashPilot forget what a service earned.

The dashboard total is the sum of current balances, so it fell by $37.54 the
morning EarnApp paid out. Confirmed payouts are the rest of the answer, and a
user needs to be able to record the ones detection never saw.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app import database, main


@pytest.fixture
def db(tmp_path):
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
        asyncio.run(database.init_db())
        yield


def _add(**kw):
    with patch.object(main, "_require_writer", lambda request: {"r": "owner"}):
        return asyncio.run(main.api_add_payout(MagicMock(), main.ManualPayout(**kw)))


def test_a_recorded_cash_out_is_confirmed_and_counts(db):
    out = _add(platform="earnapp", amount=37.54, method="PayPal", date="2026-01-15")
    assert out["ok"] and out["currency"] == "USD"
    rows = asyncio.run(database.get_payouts("earnapp", confirmed_only=True))
    assert len(rows) == 1 and rows[0]["method"] == "PayPal" and rows[0]["detected_at"].startswith("2026-01-15")
    assert asyncio.run(database.get_confirmed_payout_totals()) == {"earnapp": 37.54}


def test_the_summary_adds_payouts_to_the_balance_total(db):
    asyncio.run(database.add_manual_payout("earnapp", 37.54, "USD", 1.0, "PayPal"))
    with (
        patch("app.main._require_reader", lambda request: None),
        patch.object(
            main.database,
            "get_earnings_dashboard_summary",
            AsyncMock(return_value={"total": 120.0, "today": 0, "month": 0, "today_change": 0, "month_change": None}),
        ),
        patch.object(main.database, "get_earnings_summary", AsyncMock(return_value=[])),
        patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=[])),
    ):
        s = asyncio.run(main.api_earnings_summary(MagicMock()))
    assert s["paid_out"] == 37.54
    assert s["earned_all_time"] == 157.54


def test_an_unknown_service_is_refused(db):
    with pytest.raises(HTTPException) as exc:
        _add(platform="no-such-service", amount=5)
    assert exc.value.status_code == 404


def test_a_future_date_or_a_non_positive_amount_is_refused():
    with pytest.raises(ValueError):
        main.ManualPayout(platform="earnapp", amount=5, date="2999-01-01")
    with pytest.raises(ValueError):
        main.ManualPayout(platform="earnapp", amount=0)


def test_a_mistaken_entry_can_be_removed(db):
    pid = asyncio.run(database.add_manual_payout("earnapp", 5.0))
    with patch.object(main, "_require_writer", lambda request: {"r": "owner"}):
        assert asyncio.run(main.api_delete_payout(MagicMock(), pid))["removed"]
        with pytest.raises(HTTPException):
            asyncio.run(main.api_delete_payout(MagicMock(), pid))
    assert asyncio.run(database.get_payouts("earnapp")) == []


def test_removing_never_touches_an_unanswered_question(db):
    pid = asyncio.run(database.record_probable_payout("honeygain", 25.65))
    assert not asyncio.run(database.delete_confirmed_payout(pid))
    assert len(asyncio.run(database.get_payouts("honeygain"))) == 1


def _summary(**patches):
    with (
        patch("app.main._require_reader", lambda request: None),
        patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=[])),
    ):
        for target, value in patches.items():
            patch.object(main.database, target, value).start()
        try:
            return asyncio.run(main.api_earnings_summary(MagicMock()))
        finally:
            patch.stopall()


def test_promo_credit_the_balance_card_subtracts_is_not_counted_back(db):
    # Real rows, no mocked dashboard summary: $25 balance of which $5 is signup
    # bonus, so the card shows $20; a $10 cash-out makes $30 earned, not $35.
    asyncio.run(database.upsert_earnings("honeygain", 25.0, "USD"))
    asyncio.run(database.set_config("honeygain_signup_bonus", "5"))
    asyncio.run(database.add_manual_payout("honeygain", 10.0, "USD", 1.0, "PayPal", "2026-01-15"))
    s = _summary()
    assert s["total_adjusted"] == 20.0 and s["total_bonus"] == 5.0
    assert s["paid_out"] == 10.0
    assert s["earned_all_time"] == 30.0


def test_payouts_that_cannot_be_read_are_unknown_not_zero(db):
    asyncio.run(database.upsert_earnings("honeygain", 25.0, "USD"))
    s = _summary(get_confirmed_payout_totals=AsyncMock(side_effect=RuntimeError("database is locked")))
    assert s["paid_out"] is None and s["earned_all_time"] is None


def test_unpriced_payouts_reach_the_summary(db):
    asyncio.run(database.add_manual_payout("mysterium", 500.0, "MYST", None, "", "2026-01-15"))
    asyncio.run(database.add_manual_payout("honeygain", 10.0, "USD", 1.0))
    s = _summary()
    assert s["paid_out"] == 10.0 and s["unpriced_payouts"] == 1


def test_a_backdated_token_cash_out_is_not_priced_at_todays_rate(db):
    with patch.object(main.exchange_rates, "to_usd", lambda amount, currency: amount * 0.03):
        old = _add(platform="mysterium", amount=500, currency="MYST", date="2026-01-15")
        today = _add(platform="mysterium", amount=100, currency="MYST")
    assert old["priced"] is False and today["priced"] is True
    assert asyncio.run(database.get_confirmed_payout_totals()) == {"mysterium": pytest.approx(3.0)}
    assert asyncio.run(database.count_unpriced_confirmed_payouts()) == 1


def test_a_cash_out_cannot_be_recorded_while_a_detected_one_waits(db):
    # The bell prompt may be this same cash-out; recording it as well and then
    # confirming the prompt would count it twice.
    asyncio.run(database.record_probable_payout("earnapp", 37.54))
    with pytest.raises(HTTPException) as exc:
        _add(platform="earnapp", amount=37.54)
    assert exc.value.status_code == 409
    assert asyncio.run(database.get_payouts("earnapp", confirmed_only=True)) == []
