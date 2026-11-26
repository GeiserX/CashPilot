"""unMineable collector.

Reads the balance unMineable holds for one payout address in one coin. Mining
with a legacy address needs no account: the miner logs in as
``COIN:ADDRESS.WORKER``, and the pool's public API is keyed by the address and
the coin. No key, no login, nothing that moves funds.

``GET https://api.unminable.com/v4/address/<address>?coin=<COIN>`` answers
``{"success": true, "data": {"balance": "0.00071092", "payment_threshold":
"0.03", "fresh": false, ...}}`` with amounts as decimal strings in coin units
(XMR here). The balance is accrued until unMineable pays it, once it reaches
the coin's payment threshold. The collector reports that threshold, so a balance
drop is asked about as a payout in the coin it is counted in.

An address unMineable has never seen still answers ``success: true`` with a
zero balance and ``"fresh": true``. That is an unknown, never a 0 balance.
A wrong address or coin answers HTTP 404 with ``success: false``.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation

import httpx

from app.collectors import base
from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://api.unminable.com/v4/address"

#: The characters a coin ticker and a payout address may have. Anything else
#: (a ``.``, ``:``, ``#``, ``/`` or ``?``) would change the request, so it is
#: refused before one is sent. Coins that need a memo or tag are not supported.
_COIN = re.compile(r"[A-Za-z0-9]{2,10}")
_ADDRESS = re.compile(r"[A-Za-z0-9]{20,128}")

#: The pool's own flags on an address, as words a person can act on.
_FLAGS = {
    "payment_error": "a payment error",
    "missing_memo": "a missing memo",
    "not_activated": "an address that is not activated",
    "restricted": "a restricted address",
}


def _amount(value: object) -> Decimal | None:
    """A non-negative decimal written as a string by the pool, or None."""
    if not isinstance(value, str):
        return None
    try:
        amount = Decimal(value.strip())
    except InvalidOperation:
        return None
    return amount if amount.is_finite() and amount >= 0 else None


class UnMineableCollector(BaseCollector):
    """Collect the balance unMineable holds for one payout address and coin."""

    platform = "unmineable"

    def __init__(self, address: str, coin: str) -> None:
        super().__init__()
        self.address = (address or "").strip()
        self.coin = (coin or "").strip().upper()

    def _fail(self, error: str, kind: str | None = None) -> EarningsResult:
        currency = self.coin if _COIN.fullmatch(self.coin) else "USD"
        return EarningsResult(platform=self.platform, balance=0.0, currency=currency, error=error, error_kind=kind)

    async def collect(self) -> EarningsResult:
        if not _COIN.fullmatch(self.coin):
            return self._fail(
                "Enter the ticker of the coin unMineable pays you, such as XMR, SHIB or DOGE.", base.KIND_AUTH
            )
        if not _ADDRESS.fullmatch(self.address):
            return self._fail(
                f"Enter the {self.coin} payout address your miner uses on unMineable, "
                "without the coin, worker name or referral code.",
                base.KIND_AUTH,
            )

        client = self._get_client(timeout=10)

        async def fetch() -> httpx.Response:
            return await client.get(f"{API_BASE}/{self.address}", params={"coin": self.coin})

        try:
            response = await self._retry(fetch)
        except httpx.RequestError as exc:
            base.log_failure(logger, "unMineable", exc)
            return self._fail(base.describe_exception(exc), base.classify_exception(exc))

        status = response.status_code
        if status in (401, 403):
            # The endpoint is public. A refused request says nothing about the
            # address, whatever its body says, so it is checked before the pool's message.
            error = f"unMineable returned HTTP {status}."
            logger.warning("%s", error)
            return self._fail(error, base.KIND_TRANSIENT)

        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict) and payload.get("success") is False:
            message = str(payload.get("msg") or "")
            # Both come back as HTTP 404. Only a person can fix either one.
            if message.startswith("Invalid address"):
                return self._fail(
                    f"unMineable does not accept this address for {self.coin}. "
                    "Check the address and the coin, and that the address is on a network unMineable pays for this coin.",
                    base.KIND_AUTH,
                )
            if message.startswith("Invalid or missing coin"):
                return self._fail(f"unMineable does not list the coin {self.coin}.", base.KIND_AUTH)

        if response.is_error:
            # The request URL contains the payout address, so it is not logged here.
            error = f"unMineable returned HTTP {status}."
            logger.warning("%s", error)
            kind = base.KIND_TRANSIENT if status == 429 or status >= 500 else None
            return self._fail(error, kind)

        data = payload.get("data") if isinstance(payload, dict) and payload.get("success") is True else None
        if not isinstance(data, dict):
            return self._fail("unMineable did not return address stats.", base.KIND_SHAPE)

        if data.get("fresh") is True:
            # Unknown cause, so no kind: a typo needs a person, while a miner
            # that has not sent its first shares heals by itself.
            return self._fail(
                f"unMineable has no record of this {self.coin} address yet. Check that it is exactly the "
                "address your miner uses; a miner that has not sent shares yet also shows this."
            )

        balance = _amount(data.get("balance"))
        threshold = _amount(data.get("payment_threshold"))
        if data.get("fresh") is not False or balance is None or threshold is None or threshold == 0:
            return self._fail("unMineable did not return a valid balance and payment threshold.", base.KIND_SHAPE)

        flags = data.get("err_flags")
        raised = [text for key, text in _FLAGS.items() if isinstance(flags, dict) and flags.get(key) is True]
        warning = f"unMineable reports {' and '.join(raised)} for this address." if raised else None

        return EarningsResult(
            platform=self.platform,
            balance=float(balance),
            currency=self.coin,
            warning=warning,
            payout_threshold=float(threshold),
        )
