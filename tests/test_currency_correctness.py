"""Money arithmetic that a price move must not be able to distort.

The rule this codebase states for itself: take the delta in the NATIVE currency,
then price it. Converting a cumulative balance first turns an exchange-rate
movement into fabricated earnings.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


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
                ("2026-08-01", 1000.0, "ANYONE", 0.10),
                ("2026-08-02", 1000.0, "ANYONE", 0.12),
            ],
            tmp_path,
        )
        assert total == 0.0, "a token price move alone was counted as earnings"

    @pytest.mark.asyncio
    async def test_real_new_tokens_are_counted(self, tmp_path):
        """The control: without this the test above passes with earnings broken."""
        total = await self._daily(
            [
                ("2026-08-01", 1000.0, "ANYONE", 0.10),
                ("2026-08-02", 1100.0, "ANYONE", 0.10),
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
                ("2026-08-01", 100.0, "USD", 1.0),
                ("2026-08-02", 1000.0, "ANYONE", 0.10),
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
