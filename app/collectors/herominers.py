"""Read the unpaid balance of a HeroMiners payout address."""

from __future__ import annotations

import logging
import re
import time
from decimal import Decimal

import httpx

from app.collectors import base
from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

STALE_SHARES_SECONDS = 3600


def _units_from_string(value: object) -> int | None:
    """Read an unsigned integer written as a decimal string by the pool."""
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,20}", value):
        return None
    return int(value)


class _HeroMinersCollector(BaseCollector):
    coin: str
    currency: str
    units: int
    address_pattern: re.Pattern[str]

    def __init__(self, address: str) -> None:
        super().__init__()
        self.address = (address or "").strip()

    def _fail(self, error: str, kind: str | None = None) -> EarningsResult:
        return EarningsResult(platform=self.platform, balance=0.0, currency=self.currency, error=error, error_kind=kind)

    async def collect(self) -> EarningsResult:
        address_error = f"Enter the full {self.currency} payout address your miner uses on HeroMiners."
        if not self.address_pattern.fullmatch(self.address):
            return self._fail(address_error, base.KIND_AUTH)

        client = self._get_client(timeout=10)

        async def fetch() -> httpx.Response:
            return await client.get(
                f"https://{self.coin}.herominers.com/api/stats_address",
                params={"address": self.address, "recentBlocksAmount": 0, "longpoll": "false"},
            )

        try:
            response = await self._retry(fetch)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # The request URL contains the payout address.
            status = exc.response.status_code
            error = f"HeroMiners returned HTTP {status} {exc.response.reason_phrase}."
            logger.warning("%s", error)
            # This endpoint is public. Only its JSON can reject an address.
            kind = base.KIND_TRANSIENT if status in (401, 403) else base.classify_exception(exc)
            return self._fail(error, kind)
        except httpx.RequestError as exc:
            base.log_failure(logger, "HeroMiners", exc)
            return self._fail(base.describe_exception(exc), base.classify_exception(exc))

        try:
            payload = response.json()
        except ValueError:
            return self._fail("HeroMiners did not return valid JSON.", base.KIND_SHAPE)
        if not isinstance(payload, dict):
            return self._fail("HeroMiners did not return a JSON object.", base.KIND_SHAPE)

        # Both errors come back as HTTP 200. The pool checks the checksum.
        if payload.get("error") == "Invalid address":
            return self._fail(address_error, base.KIND_AUTH)
        if payload.get("error") == "Not found":
            return self._fail(
                "HeroMiners has no record of this address yet. Check your payout address and wait for your first shares."
            )

        stats = payload.get("stats")
        balance = _units_from_string(stats.get("balance")) if isinstance(stats, dict) else None
        if "error" in payload or balance is None:
            return self._fail("HeroMiners did not return a valid unpaid balance.", base.KIND_SHAPE)

        last_share = _units_from_string(stats.get("lastShare"))
        warning = None
        if last_share:
            age = time.time() - last_share
            if age > STALE_SHARES_SECONDS:
                warning = f"HeroMiners has had no shares from this address for {int(age // 3600)} h."

        return EarningsResult(
            platform=self.platform,
            balance=float(Decimal(balance) / self.units),
            currency=self.currency,
            warning=warning,
        )


class HeroMinersKaspaCollector(_HeroMinersCollector):
    platform = "herominers-kas"
    coin = "kaspa"
    currency = "KAS"
    units = 100_000_000
    # Kaspa mainnet uses 61 characters for Schnorr and script hashes, 63 for ECDSA.
    address_pattern = re.compile(
        r"kaspa:[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{61}(?:[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{2})?"
    )
