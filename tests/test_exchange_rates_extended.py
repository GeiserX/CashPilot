"""Extended tests for exchange_rates.py — covers the refresh() function."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

from app import exchange_rates


def _mock_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


class TestRefreshSuccess:
    def test_refresh_fetches_rates(self):
        crypto_resp = _mock_response(200, {"mysterium": {"usd": 0.10}})
        fiat_resp = _mock_response(200, {"rates": {"EUR": 0.92, "GBP": 0.79}})

        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get.side_effect = [crypto_resp, fiat_resp]

        with patch("app.exchange_rates.httpx.AsyncClient", return_value=client):
            asyncio.run(exchange_rates.refresh())

        assert exchange_rates._crypto_usd.get("MYST") == 0.10
        assert "EUR" in exchange_rates._fiat_rates
        assert exchange_rates._fiat_rates["EUR"] == 0.92
        assert exchange_rates._last_fetch > 0

    def test_refresh_crypto_failure_still_fetches_fiat(self):
        crypto_resp = _mock_response(500)
        fiat_resp = _mock_response(200, {"rates": {"JPY": 150.0}})

        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get.side_effect = [crypto_resp, fiat_resp]

        with patch("app.exchange_rates.httpx.AsyncClient", return_value=client):
            asyncio.run(exchange_rates.refresh())

        assert "JPY" in exchange_rates._fiat_rates

    def test_refresh_total_failure(self):
        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get.side_effect = Exception("Network error")

        with patch("app.exchange_rates.httpx.AsyncClient", return_value=client):
            asyncio.run(exchange_rates.refresh())  # Should not raise
