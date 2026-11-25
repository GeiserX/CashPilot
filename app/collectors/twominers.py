"""Read unpaid balances from the 2Miners pool API."""

from __future__ import annotations

import logging
import time
from decimal import Decimal

import httpx

from app import onchain
from app.collectors import base
from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

STALE_SHARES_SECONDS = 3600


def _unsigned_int(value: object) -> int | None:
    if type(value) is not int or not 0 <= value < 2**64:
        return None
    return value


class _TwoMinersCollector(BaseCollector):
    coin: str
    currency: str
    chain: str
    units: int

    def __init__(self, address: str) -> None:
        super().__init__()
        self.address = (address or "").strip()

    def _fail(self, error: str, kind: str | None = None) -> EarningsResult:
        return EarningsResult(platform=self.platform, balance=0.0, currency=self.currency, error=error, error_kind=kind)

    def _unseen_address(self) -> EarningsResult:
        return self._fail(
            "2Miners has no record of this address yet. Check your payout address and wait for your first shares."
        )

    async def collect(self) -> EarningsResult:
        if not onchain.address_looks_valid(self.chain, self.address):
            return self._fail(f"Enter the {self.currency} payout address your miner uses on 2Miners.", base.KIND_AUTH)

        client = self._get_client(timeout=10)

        async def fetch() -> httpx.Response:
            return await client.get(f"https://{self.coin}.2miners.com/api/accounts/{self.address}")

        try:
            response = await self._retry(fetch)
            if response.status_code == 404:
                return self._unseen_address()
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # The request URL contains the user's payout address.
            status = exc.response.status_code
            error = f"2Miners returned HTTP {status} {exc.response.reason_phrase}."
            logger.warning("%s", error)
            # The endpoint is public. A refused request says nothing about the address.
            kind = base.KIND_TRANSIENT if status in (401, 403) else base.classify_exception(exc)
            return self._fail(error, kind)
        except httpx.RequestError as exc:
            base.log_failure(logger, "2Miners", exc)
            return self._fail(base.describe_exception(exc), base.classify_exception(exc))

        try:
            payload = response.json()
        except ValueError:
            return self._fail("2Miners did not return valid JSON.", base.KIND_SHAPE)
        stats = payload.get("stats") if isinstance(payload, dict) and "error" not in payload else None
        if not isinstance(stats, dict):
            return self._fail("2Miners did not return account stats.", base.KIND_SHAPE)

        # Older replies for an unseen address carried a zero lastShare.
        last_share = _unsigned_int(stats.get("lastShare"))
        if last_share == 0:
            return self._unseen_address()
        balance = _unsigned_int(stats.get("balance"))
        if balance is None or last_share is None:
            return self._fail("2Miners did not return a valid unpaid balance or share time.", base.KIND_SHAPE)

        age = time.time() - last_share
        warning = None
        if age > STALE_SHARES_SECONDS:
            warning = f"2Miners has had no shares from this address for {int(age // 3600)} h."

        return EarningsResult(
            platform=self.platform,
            balance=float(Decimal(balance) / self.units),
            currency=self.currency,
            warning=warning,
        )


class TwoMinersETCCollector(_TwoMinersCollector):
    platform = "2miners-etc"
    coin = "etc"
    currency = "ETC"
    chain = "ethereum-classic"
    units = 1_000_000_000
