"""Tests for exchange rate service."""

import os

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest

from app import exchange_rates


class TestToUsd:
    def test_usd_passthrough(self):
        assert exchange_rates.to_usd(10.0, "USD") == 10.0

    def test_unknown_currency_returns_none(self):
        assert exchange_rates.to_usd(10.0, "UNKNOWN_XYZ") is None

    def test_crypto_conversion(self):
        exchange_rates._crypto_usd["MYST"] = 0.10
        try:
            result = exchange_rates.to_usd(100.0, "MYST")
            assert result == pytest.approx(10.0)
        finally:
            exchange_rates._crypto_usd.pop("MYST", None)

    def test_fiat_conversion(self):
        exchange_rates._fiat_rates["EUR"] = 0.92
        try:
            result = exchange_rates.to_usd(92.0, "EUR")
            assert result == pytest.approx(100.0)
        finally:
            exchange_rates._fiat_rates.pop("EUR", None)

    def test_fiat_zero_rate_returns_none(self):
        exchange_rates._fiat_rates["ZZZ"] = 0.0
        try:
            assert exchange_rates.to_usd(10.0, "ZZZ") is None
        finally:
            exchange_rates._fiat_rates.pop("ZZZ", None)


class TestGetAll:
    def test_returns_structure(self):
        result = exchange_rates.get_all()
        assert "fiat" in result
        assert "crypto_usd" in result
        assert "last_updated" in result
        assert isinstance(result["fiat"], dict)
        assert result["fiat"]["USD"] == 1.0


class TestRefresh:
    @pytest.mark.asyncio
    async def test_refresh_handles_network_error(self):
        """Refresh should not raise even if APIs are unreachable."""
        from unittest.mock import AsyncMock, patch

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("Network error"))

        with patch("app.exchange_rates.httpx.AsyncClient", return_value=mock_client):
            await exchange_rates.refresh()
