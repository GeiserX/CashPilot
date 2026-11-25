"""SupportXMR mining pool collector.

Reads the XMR balance SupportXMR holds for a Monero payout address. The pool
has no accounts: a miner logs in with the address as its username, and the
pool's public stats are keyed by it. No key, no login, nothing that moves funds.

The balance is ``amtDue``, in piconero (10^-12 XMR). It is accrued until the
pool pays it. CashPilot asks the user to confirm a drop as a payout.

SupportXMR returns HTTP 200 for unseen addresses. When ``lastHash``,
``totalHashes``, ``amtDue`` and ``amtPaid`` all equal zero, the collector
reports the address as unknown. Ignore ``txnCount`` because it can be zero
even when ``amtPaid`` is positive.
"""

from __future__ import annotations

import logging
import re
import time
from decimal import Decimal

import httpx

from app.collectors import base
from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://www.supportxmr.com/api"
PICONERO = Decimal(10) ** 12

#: A mainnet Monero address: a standard (4…) or subaddress (8…) of 95 base58
#: characters, or an integrated address (4…) of 106. Checked before any request.
_ADDRESS = re.compile(r"^(?:[48][1-9A-HJ-NP-Za-km-z]{94}|4[1-9A-HJ-NP-Za-km-z]{105})$")

#: How long without a share before the reading carries a warning.
STALE_SHARES_SECONDS = 3600


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


class SupportXMRCollector(BaseCollector):
    """Collect the XMR balance SupportXMR holds for one payout address."""

    platform = "supportxmr"

    def __init__(self, address: str) -> None:
        super().__init__()
        self.address = (address or "").strip()

    def _fail(self, error: str, kind: str | None = None) -> EarningsResult:
        return EarningsResult(platform=self.platform, balance=0.0, currency="XMR", error=error, error_kind=kind)

    async def collect(self) -> EarningsResult:
        if not _ADDRESS.fullmatch(self.address):
            # The saved value itself is wrong, and only a person can fix it.
            return self._fail(
                "This is not a Monero address, so it was not sent to SupportXMR. "
                "Paste the address your miner uses as its username, without any .workername or +difficulty part.",
                base.KIND_AUTH,
            )
        try:
            client = self._get_client()

            async def _fetch() -> httpx.Response:
                return await client.get(f"{API_BASE}/miner/{self.address}/stats")

            resp = await self._retry(_fetch)
            resp.raise_for_status()
            stats = resp.json()
            if not isinstance(stats, dict):
                return self._fail("SupportXMR answered with something other than a JSON object", base.KIND_SHAPE)

            due = _nonnegative_int(stats.get("amtDue"))
            paid = _nonnegative_int(stats.get("amtPaid"))
            last_hash = _nonnegative_int(stats.get("lastHash"))
            total_hashes = _nonnegative_int(stats.get("totalHashes"))
            if due is None or paid is None or last_hash is None or total_hashes is None:
                return self._fail(
                    "SupportXMR's answer has missing or invalid balance or mining history fields", base.KIND_SHAPE
                )
            if due == paid == last_hash == total_hashes == 0:
                # Unknown cause, so no kind: a typo needs a person, while a
                # miner that has not sent its first shares heals by itself.
                return self._fail(
                    "SupportXMR has no record of this address yet. Check that it is exactly the "
                    "username your miner uses; a miner that has not sent shares yet also shows this."
                )

            return EarningsResult(
                platform=self.platform,
                balance=float(Decimal(due) / PICONERO),
                currency="XMR",
                warning=_stale_warning(last_hash),
            )
        except Exception as exc:
            base.log_failure(logger, "SupportXMR", exc)
            return self._fail(base.describe_exception(exc), base.classify_exception(exc))


def _stale_warning(last_hash: int) -> str | None:
    """A caveat on a good reading when the pool has had no shares for a while."""
    age = time.time() - last_hash
    if last_hash and age > STALE_SHARES_SECONDS:
        return f"SupportXMR has had no shares from this address for {int(age // 3600)} h."
    return None
