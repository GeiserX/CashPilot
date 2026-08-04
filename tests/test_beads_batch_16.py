"""CashPilot-dlr: the fleet running-costs card subtracted EUR from USD.

Every gross in /api/fleet/economics comes from ``get_earned_by_platform``,
which is USD by contract (database.py: "USD earned per platform"). The
electricity price came straight from the tariff config, in whatever currency
the user set. ``machine_economics`` then did ``net = gross - cost``.

Live, that rendered gross 5.00 (USD) minus cost 14.24 (EUR, 65 W at €0.30/kWh)
= net −9.24, verdict "losing money", with "turning it off would save that" — a
recommendation to switch off hardware, wrong by the whole FX spread. At the
live rate the true net is about −$11.35, not −9.24 of any currency. With a
weaker tariff currency the error is not 15% but orders of magnitude.

The payload also carried no currency field at all, and fleet.html printed
``Number(v).toFixed(2)``, so the user saw bare numbers they could not attribute
to a unit — while those numbers silently mixed two.

Fixed the same way /api/earnings/net was: convert the TARIFF to USD, so the
endpoint stays canonical USD like the rest of the API and the frontend's
display-currency layer renders it in whatever the viewer reads in.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def without_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in text.splitlines())


async def _economics(config, *, rate=0.92, rate_available=True):
    """Drive api_fleet_economics with one online worker drawing 100 W.

    machine_economics bills a month as 730 hours (365 * 24 / 12), so 100 W is
    73 kWh and a €0.30 tariff is €21.90 — large enough that a missing conversion
    cannot hide inside rounding.
    """
    from app import main

    worker = {
        "id": 1,
        "client_id": "abc",
        "name": "watchtower",
        "status": "online",
        "system_info": {},
    }

    def to_usd(amount, currency):
        if currency == "USD":
            return amount
        return amount * rate if rate_available else None

    with (
        patch.object(main, "_require_auth_api", lambda r: None),
        patch.object(main.database, "get_config", AsyncMock(return_value=config)),
        patch.object(main.database, "list_workers", AsyncMock(return_value=[worker])),
        patch.object(main.database, "get_earned_by_platform", AsyncMock(return_value={"honeygain": 5.0})),
        patch.object(
            main,
            "_get_all_worker_containers",
            AsyncMock(return_value=[{"slug": "honeygain", "_worker_id": 1}]),
        ),
        patch.object(main, "_decoded_worker", lambda w: w),
        patch.object(main.exchange_rates, "to_usd", to_usd),
    ):
        return await main.api_fleet_economics(MagicMock())


CONFIG = {"power_price_per_kwh": "0.30", "power_currency": "EUR", "worker_abc_watts": "100"}


class TestTheCostIsConvertedBeforeItIsSubtracted:
    @pytest.mark.asyncio
    async def test_the_cost_is_the_tariff_in_usd_not_the_raw_number(self):
        out = await _economics(CONFIG)
        machine = out["machines"][0]
        # 100 W * 730 h = 73 kWh; 73 * 0.30 = EUR 21.90; * 0.92 = USD 20.15.
        assert machine["monthly_cost"] == pytest.approx(20.15, abs=0.05), (
            f"cost {machine['monthly_cost']} — EUR 21.90 was subtracted from a USD gross"
        )

    @pytest.mark.asyncio
    async def test_the_net_is_a_like_for_like_subtraction(self):
        out = await _economics(CONFIG)
        machine = out["machines"][0]
        assert machine["monthly_net"] == pytest.approx(5.0 - 20.15, abs=0.05)

    @pytest.mark.asyncio
    async def test_a_usd_tariff_is_left_alone(self):
        """The control: converting when no conversion is needed is its own bug."""
        out = await _economics({**CONFIG, "power_currency": "USD"})
        assert out["machines"][0]["monthly_cost"] == pytest.approx(21.90, abs=0.05)

    @pytest.mark.asyncio
    async def test_the_payload_says_what_currency_it_is_in(self):
        """It carried none, so the card printed numbers with no unit."""
        assert (await _economics(CONFIG))["currency"] == "USD"


class TestNoRateMeansNoCostRatherThanAWrongOne:
    """Absent is not zero. A zero cost renders gross as net and overstates it."""

    @pytest.mark.asyncio
    async def test_the_cost_is_unknown_when_the_rate_is_missing(self):
        out = await _economics(CONFIG, rate_available=False)
        machine = out["machines"][0]
        assert machine["monthly_cost"] is None
        assert machine["monthly_net"] is None

    @pytest.mark.asyncio
    async def test_it_does_not_advise_switching_the_machine_off(self):
        out = await _economics(CONFIG, rate_available=False)
        assert "turning it off would save" not in out["machines"][0]["summary"].lower()

    @pytest.mark.asyncio
    async def test_the_payload_explains_why(self):
        out = await _economics(CONFIG, rate_available=False)
        assert out["fx_unavailable"] is True
        assert out["tariff_currency"] == "EUR"
        assert "two different currencies" in out["cost_unavailable_reason"]

    @pytest.mark.asyncio
    async def test_nothing_is_flagged_when_the_rate_is_there(self):
        """The control: this must not nag on a healthy install."""
        out = await _economics(CONFIG)
        assert "fx_unavailable" not in out
        assert "cost_unavailable_reason" not in out

    @pytest.mark.asyncio
    async def test_a_usd_tariff_never_needs_a_rate(self):
        """A USD user must not lose their cost figure when CoinGecko is down."""
        out = await _economics({**CONFIG, "power_currency": "USD"}, rate_available=False)
        assert out["machines"][0]["monthly_cost"] is not None
        assert "fx_unavailable" not in out


class TestTheCardRendersAUnit:
    def test_the_fleet_card_no_longer_prints_a_bare_number(self):
        text = without_comments((ROOT / "app" / "templates" / "fleet.html").read_text(encoding="utf-8"))
        assert "Number(v).toFixed(2)" not in text, "running costs still render with no currency"
        assert "CP.formatCurrency(v)" in text

    def test_unknown_still_renders_as_a_dash_not_zero(self):
        """The distinction the endpoint works to preserve must survive display."""
        text = without_comments((ROOT / "app" / "templates" / "fleet.html").read_text(encoding="utf-8"))
        assert "v == null ? '—'" in text

    def test_format_currency_is_actually_exported(self):
        """fleet.html calls it through CP; an unexported helper is a dead card."""
        source = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
        public_api = source[source.rindex("  return {") :]
        assert "formatCurrency," in public_api
