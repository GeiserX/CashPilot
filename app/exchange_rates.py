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
# Rates are considered stale (refreshes are failing) after 2x the cache TTL.
STALE_THRESHOLD = 2 * CACHE_TTL  # 30 minutes

# In-memory caches
_fiat_rates: dict[str, float] = {"USD": 1.0}
_crypto_usd: dict[str, float] = {}
# Crypto (CoinGecko) and fiat (Frankfurter) are independent sources with their own
# staleness clocks, each advanced ONLY on that source's own HTTP 200 -- a failure
# on one source must never mark the other source's rates stale, and must never be
# papered over as "fresh" for the source that actually failed.
_crypto_last_fetch: float = 0
_fiat_last_fetch: float = 0
# Aggregate clock kept for backward-compat callers (rates_stale()/get_all()). It
# reflects the WORSE of the two sources (the older of the two timestamps), so a
# partial failure is never reported as fully fresh.
_last_fetch: float = 0


async def refresh() -> None:
    """Fetch latest exchange rates from external APIs.

    Only a genuine HTTP 200 from a source advances THAT source's own last-fetch
    time -- a non-200 (or an unreachable API) leaves it untouched so staleness is
    tracked per-source and a partial failure can't mislabel the other source.
    """
    global _fiat_rates, _crypto_usd, _last_fetch, _crypto_last_fetch, _fiat_last_fetch

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
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
                    _crypto_last_fetch = time.time()
                else:
                    logger.warning(
                        "exchange rate fetch got HTTP %s from %s",
                        resp.status_code,
                        "CoinGecko",
                    )
            else:
                # Nothing to fetch -- don't let an empty crypto map hold the
                # aggregate staleness clock back forever.
                _crypto_last_fetch = time.time()

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
                _fiat_last_fetch = time.time()
            else:
                logger.warning(
                    "exchange rate fetch got HTTP %s from %s",
                    resp.status_code,
                    "Frankfurter",
                )

        _last_fetch = min(_crypto_last_fetch, _fiat_last_fetch)
        logger.info(
            "Exchange rates updated: %d fiat currencies, %d crypto tokens",
            len(_fiat_rates),
            len(_crypto_usd),
        )
    except Exception as exc:
        logger.error("Exchange rate fetch failed: %s", exc)


def rates_stale() -> bool:
    """Return True if cached rates are stale (refreshes appear to be failing).

    Rates are stale once more than ``STALE_THRESHOLD`` seconds have elapsed
    since the last successful fetch (``_last_fetch`` is only updated on
    success, and reflects the WORSE of the crypto/fiat sources -- see
    ``crypto_rates_stale()``/``fiat_rates_stale()`` for the per-source signal).
    A never-fetched cache (``_last_fetch == 0``) is also stale. Callers can use
    this to avoid silently summing balances against rates that may be badly
    out of date.
    """
    return time.time() - _last_fetch > STALE_THRESHOLD


def crypto_rates_stale() -> bool:
    """Return True if crypto rates are stale (CoinGecko refreshes are failing)."""
    return time.time() - _crypto_last_fetch > STALE_THRESHOLD


def fiat_rates_stale() -> bool:
    """Return True if fiat rates are stale (Frankfurter refreshes are failing)."""
    return time.time() - _fiat_last_fetch > STALE_THRESHOLD


def get_all() -> dict[str, Any]:
    """Return all cached rates for the frontend."""
    return {
        "fiat": dict(_fiat_rates),
        "crypto_usd": dict(_crypto_usd),
        "last_updated": _last_fetch,
        "stale": rates_stale(),
        "crypto_stale": crypto_rates_stale(),
        "fiat_stale": fiat_rates_stale(),
    }


def to_usd(amount: float, currency: str) -> float | None:
    """Convert an amount in *currency* to USD.

    Returns None if no rate is available (e.g. unknown token).
    """
    if currency == "USD":
        return amount
    if currency in _crypto_usd:
        return amount * _crypto_usd[currency]
    # Fiat: _fiat_rates stores USD->X rates, so divide to get X->USD
    if currency in _fiat_rates and _fiat_rates[currency] > 0:
        return amount / _fiat_rates[currency]
    return None
