"""Money arithmetic that a price move must not be able to distort.

The rule this codebase states for itself: take the delta in the NATIVE currency,
then price it. Converting a cumulative balance first turns an exchange-rate
movement into fabricated earnings.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _day(n: int) -> str:
    """An ISO date n days ago on the UTC clock get_daily_earnings reads.

    The rows below were pinned to 1 and 2 August 2026, and get_daily_earnings
    only looks back 30 days. On 1 September the control test stopped seeing its
    own rows and went red on main with nothing merged, while its two siblings
    kept passing on 0.0 == 0.0 without touching the code they name. Dating the
    rows relative to today keeps them inside the window for good, the way
    test_power.py already does.
    """
    return (datetime.now(UTC) - timedelta(days=n)).strftime("%Y-%m-%d")


@pytest.fixture(autouse=True)
def _isolate_fiat_rates():
    """Save and restore exchange_rates._fiat_rates around every test here.

    These tests set a rate to exercise the conversion. Without restoring it the
    rate leaks into the rest of the suite, where unrelated endpoints then
    convert a gross they were never meant to convert — test_power.py started
    seeing 6.44 where it expected 7.0, failing for a reason that had nothing to
    do with it.
    """
    from app import exchange_rates as fx

    saved = dict(fx._fiat_rates)
    try:
        yield
    finally:
        fx._fiat_rates.clear()
        fx._fiat_rates.update(saved)


class TestACryptoPriceMoveCannotFabricateEarnings:
    """anyone-protocol priced a CUMULATIVE balance before the delta was taken.

    balance is lifetime accumulated rewards, and earnings are the difference
    between two readings. Converting first meant the same 1000 ANYONE, read at
    $0.10 and then at $0.12, produced $20 of "earned today" without a single
    token being paid out. The user saw income that did not exist, and it would
    reverse into an apparent loss when the price fell back.

    get_daily_earnings already takes the delta natively and prices it afterwards
    — that is why it is written that way. Handing it USD defeated it for this
    one service.
    """

    async def _daily(self, rows, tmp_path):
        from app import database

        with (
            patch.object(database, "DB_DIR", tmp_path),
            patch.object(database, "DB_PATH", tmp_path / "fx.db"),
        ):
            await database.init_db()
            for date, balance, currency, rate in rows:
                await database.upsert_earnings(
                    platform="anyone-protocol",
                    date=date,
                    balance=balance,
                    currency=currency,
                    fx_rate_usd=rate,
                )
            rows = await database.get_daily_earnings(days=30)
            # Rows are {"date": "Aug 02", "amount": 10.0} — a FORMATTED label
            # and an "amount" key. Reading r["earnings"] keyed off an ISO date
            # made every lookup return 0.0, so the assertions below passed
            # without touching the code they name. Summing sidesteps the label
            # format entirely.
            return sum(float(r.get("amount") or 0.0) for r in rows)

    @pytest.mark.asyncio
    async def test_a_price_move_with_no_new_tokens_earns_nothing(self, tmp_path):
        """The exact fabrication: identical token count, higher price."""
        total = await self._daily(
            [
                (_day(2), 1000.0, "ANYONE", 0.10),
                (_day(1), 1000.0, "ANYONE", 0.12),
            ],
            tmp_path,
        )
        assert total == 0.0, "a token price move alone was counted as earnings"

    @pytest.mark.asyncio
    async def test_real_new_tokens_are_counted(self, tmp_path):
        """The control: without this the test above passes with earnings broken."""
        total = await self._daily(
            [
                (_day(2), 1000.0, "ANYONE", 0.10),
                (_day(1), 1100.0, "ANYONE", 0.10),
            ],
            tmp_path,
        )
        assert total == pytest.approx(10.0), "100 new tokens at $0.10 is $10"

    @pytest.mark.asyncio
    async def test_the_switch_from_usd_to_native_is_not_counted_as_a_gain(self, tmp_path):
        """Existing installs have USD rows from before this fix.

        1000 tokens stored as $100 becomes 1000 stored as 1000 ANYONE. Compared
        blindly that is a 900-unit gain. database.py only takes a delta when the
        currency matches, so the changeover reading is skipped — which is what
        makes this safe to ship to an upgrading user.
        """
        total = await self._daily(
            [
                (_day(2), 100.0, "USD", 1.0),
                (_day(1), 1000.0, "ANYONE", 0.10),
            ],
            tmp_path,
        )
        assert total == 0.0, "the currency changeover was counted as earnings"

    def test_the_collector_reports_native_tokens(self):
        source = (ROOT / "app" / "collectors" / "anyone.py").read_text(encoding="utf-8")
        assert 'currency="USD"' not in source, "the collector still pre-converts to USD"

    def test_anyone_is_priceable(self):
        """Native storage is only useful if something can price it."""
        from app import exchange_rates

        assert "ANYONE" in exchange_rates.CRYPTO_IDS
        assert exchange_rates.CRYPTO_IDS["ANYONE"] == "airtor-protocol"


class TestNetEarningsSubtractLikeFromLike:
    """CashPilot-dlr: an electricity cost in EUR taken off a gross in USD.

    ``gross`` comes from ``get_earned_by_platform``, which is USD by contract.
    ``cost`` is computed from a tariff the user entered in ``power_currency``.
    Subtracting one from the other produced a number in neither, labelled with
    the tariff currency.

    At roughly 1.08 USD/EUR that is an ~8% error, in the direction that flatters
    the result, on the single figure that decides whether a machine is worth
    keeping powered on.
    """

    def _net(self, rate, currency="EUR", gross=100.0):
        import asyncio

        from app import exchange_rates as fx
        from app import main

        fx._fiat_rates.clear()
        if rate is not None:
            fx._fiat_rates[currency] = rate
        cfg = {"power_price_per_kwh": "0.20", "power_currency": currency}
        workers = [{"id": 1, "name": "w", "status": "online", "system_info": '{"network_type":"residential"}'}]
        conts = [{"slug": "honeygain", "status": "running", "cpu_percent": 4.0, "_worker_id": 1}]

        async def run():
            with (
                patch.object(main, "_require_auth_api", lambda r: None),
                patch.object(main.database, "get_config", AsyncMock(return_value=cfg)),
                patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=conts)),
                patch.object(main.database, "list_workers", AsyncMock(return_value=workers)),
                patch.object(main.database, "get_earned_by_platform", AsyncMock(return_value={"honeygain": gross})),
            ):
                return await main.api_earnings_net(MagicMock(), days=30)

        return asyncio.run(run())

    def test_the_tariff_is_converted_into_usd(self):
        """The TARIFF moves, not the gross.

        My first attempt converted gross into the tariff currency. Converting
        the price instead keeps this endpoint canonical USD like every other
        money figure in the API, and the frontend's display-currency layer
        renders it in whatever the user reads in — converting the other way
        would have made this one endpoint the exception.
        """
        out = self._net(rate=0.92)
        assert out["currency"] == "USD"
        assert out["total_gross"] == pytest.approx(100.0), "gross is USD by contract and should not move"
        assert out["cost_known"] is True

    def test_net_is_then_a_real_subtraction(self):
        """Both sides in USD, so the subtraction means something."""
        out = self._net(rate=0.92)
        assert out["total_net"] == pytest.approx(out["total_gross"] - out["total_cost"])

    def test_without_a_rate_it_stays_in_usd_and_says_so(self):
        """Mixing silently is the failure; reporting one currency honestly is not."""
        out = self._net(rate=None)
        assert out["total_gross"] == pytest.approx(100.0)
        assert out["cost_known"] is False, "a net here would subtract EUR from USD"
        assert out["fx_unavailable"] is True
        assert out["tariff_currency"] == "EUR"
        assert "no" in out["cost_unavailable_reason"].lower()

    def test_a_usd_tariff_needs_no_conversion(self):
        out = self._net(rate=None, currency="USD")
        assert out["currency"] == "USD"
        assert out["cost_known"] is True
        assert "fx_unavailable" not in out

    def test_the_inverse_rate_direction_is_right(self):
        """_fiat_rates holds USD->X, so from_usd multiplies where to_usd divides.

        Inverting this would be worse than the bug: at 0.92 it would report 109
        EUR for 100 USD and flatter the result further.
        """
        from app import exchange_rates as fx

        fx._fiat_rates.clear()
        fx._fiat_rates["EUR"] = 0.92
        assert fx.from_usd(100.0, "EUR") == pytest.approx(92.0)
        assert fx.to_usd(92.0, "EUR") == pytest.approx(100.0)
