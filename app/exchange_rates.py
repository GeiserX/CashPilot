"""Exchange rate service for CashPilot.

Fetches crypto-to-USD rates from CoinGecko and USD-to-fiat rates from
Frankfurter API.  Rates are cached in memory with periodic refresh
(every 15 minutes via the scheduler).

No API keys required — both services are free-tier.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# CoinGecko IDs for crypto tokens tracked by CashPilot collectors.
# Map: our internal currency code -> CoinGecko coin id
# Note: Grass *points* are NOT the GRASS token — they're an internal reward
# that converts to tokens only during airdrops at unknown ratios, so we
# intentionally do NOT map GRASS here.
CRYPTO_IDS: dict[str, str] = {
    "MYST": "mysterium",
}

CACHE_TTL = 900  # 15 minutes

# In-memory caches
_fiat_rates: dict[str, float] = {"USD": 1.0}
_crypto_usd: dict[str, float] = {}
_last_fetch: float = 0


async def refresh() -> None:
    """Fetch latest exchange rates from external APIs."""
    global _fiat_rates, _crypto_usd, _last_fetch

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # --- Crypto rates from CoinGecko (free, no key) ---
            if CRYPTO_IDS:
                ids = ",".join(CRYPTO_IDS.values())
                resp = await client.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": ids, "vs_currencies": "usd"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for token, cg_id in CRYPTO_IDS.items():
                        price = (data.get(cg_id) or {}).get("usd")
                        if price is not None:
                            _crypto_usd[token] = float(price)

            # --- Fiat rates from Frankfurter (free, no key) ---
            resp = await client.get(
                "https://api.frankfurter.app/latest",
                params={"from": "USD"},
            )
            if resp.status_code == 200:
                data = resp.json()
                new_rates: dict[str, float] = {"USD": 1.0}
                for code, rate in data.get("rates", {}).items():
                    new_rates[code] = float(rate)
                _fiat_rates = new_rates

        _last_fetch = time.time()
        logger.info(
            "Exchange rates updated: %d fiat currencies, %d crypto tokens",
            len(_fiat_rates),
            len(_crypto_usd),
        )
    except Exception as exc:
        logger.error("Exchange rate fetch failed: %s", exc)


def get_all() -> dict[str, Any]:
    """Return all cached rates for the frontend."""
    return {
        "fiat": dict(_fiat_rates),
        "crypto_usd": dict(_crypto_usd),
        "last_updated": _last_fetch,
    }


def to_usd(amount: float, currency: str) -> float | None:
    """Convert an amount in *currency* to USD.

    Returns None if no rate is available (e.g. unknown token).
    """
    if currency == "USD":
        return amount
    if currency in _crypto_usd:
        return amount * _crypto_usd[currency]
    return None
