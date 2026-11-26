"""OCEAN mining pool collector.

Reads the unpaid balance OCEAN holds for a Bitcoin payout address. OCEAN has no
accounts: a miner logs in with the address as its username, and the pool's
public stats are keyed by it. No key, no login, and nothing that can move funds.

The unpaid balance is ACCRUED, NOT RECEIVED (``collector.accrual: pool`` in
services/mining/ocean.yml): OCEAN pays it on-chain once it passes the threshold,
and the drop is then detected as a payout to confirm.

An address OCEAN has never seen answers HTTP 200 with an error body, so the body
decides, never the status code. That answer is an error, never a balance of 0:
a typo in the address must not read as "you have earned nothing".
"""

from __future__ import annotations

import logging
import re
import time
from decimal import Decimal, InvalidOperation

import httpx

from app.collectors import base
from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://api.ocean.xyz/v1"

#: A mainnet Bitcoin address OCEAN accepts as a username: bech32/bech32m
#: (``bc1q``, ``bc1p``), P2PKH (``1``) or P2SH (``3``). Checked before any
#: request, so a malformed value is never sent to a public endpoint.
_ADDRESS = re.compile(r"^(bc1[02-9ac-hj-np-z]{11,71}|[13][1-9A-HJ-NP-Za-km-z]{25,34})$")

#: OCEAN's answer for an address it has never seen.
_UNKNOWN_USER = re.compile(r"no such user", re.I)

#: How long without a share before the reading carries a warning.
STALE_SHARES_SECONDS = 3600


def normalise_address(address: str) -> str:
    """The address as OCEAN keys it: trimmed, and bech32 in lower case.

    Bech32 is case-insensitive but written in lower case; base58 is not, so it
    is left as typed.
    """
    text = (address or "").strip()
    return text.lower() if text[:3].lower() == "bc1" else text


class OceanCollector(BaseCollector):
    """Collect the unpaid BTC balance OCEAN holds for one payout address."""

    platform = "ocean"

    def __init__(self, address: str) -> None:
        super().__init__()
        self.address = normalise_address(address)

    def _fail(self, error: str, kind: str | None = None) -> EarningsResult:
        return EarningsResult(platform=self.platform, balance=0.0, currency="BTC", error=error, error_kind=kind)

    async def collect(self) -> EarningsResult:
        if not _ADDRESS.match(self.address):
            # The saved value itself is wrong, and only a person can fix it.
            return self._fail(
                "This is not a Bitcoin address, so it was not sent to OCEAN. "
                "Paste the address your miner uses as its username, without the .workername part.",
                base.KIND_AUTH,
            )
        try:
            client = self._get_client()

            async def _fetch() -> httpx.Response:
                return await client.get(f"{API_BASE}/statsnap/{self.address}")

            resp = await self._retry(_fetch)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                return self._fail("OCEAN answered with something other than a JSON object", base.KIND_SHAPE)

            error = data.get("error")
            if error:
                if _UNKNOWN_USER.search(str(error)):
                    # Unknown cause, so no kind: a typo needs a person, while a
                    # miner that has not sent its first shares heals by itself.
                    return self._fail(
                        "OCEAN has no record of this address yet. Check that it is exactly the "
                        "username your miner uses; a miner that has not sent shares yet also shows this."
                    )
                return self._fail(f"OCEAN answered with an error: {str(error)[:200]}", base.KIND_SHAPE)

            result = data.get("result")
            unpaid = _decimal(result.get("unpaid")) if isinstance(result, dict) else None
            if unpaid is None or unpaid < 0:
                return self._fail(
                    "OCEAN's answer has no unpaid balance: the API shape may have changed", base.KIND_SHAPE
                )

            return EarningsResult(
                platform=self.platform,
                balance=float(unpaid),
                currency="BTC",
                warning=_warning(result),
                hashrate=_hashrate(result),
            )
        except Exception as exc:
            base.log_failure(logger, "OCEAN", exc)
            return self._fail(base.describe_exception(exc), base.classify_exception(exc))


def _decimal(value: object) -> Decimal | None:
    """A finite decimal from OCEAN's string amounts, or None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _hashrate(result: dict) -> float | None:
    """OCEAN's 5-minute hashrate for the address, in H/s, or None."""
    value = _decimal(result.get("hashrate_300s"))
    return float(value) if value is not None and value >= 0 else None


def _warning(result: dict, now: float | None = None) -> str | None:
    """A caveat on a good reading: no recent shares, or paid every block."""
    notes: list[str] = []
    # The API's own spelling, "lastest".
    last_share = _decimal(result.get("lastest_share_ts"))
    now = time.time() if now is None else now
    if last_share is not None and last_share > 0 and now - float(last_share) > STALE_SHARES_SECONDS:
        hours = int((now - float(last_share)) // 3600)
        notes.append(f"OCEAN has had no shares from this address for {hours} h.")
    unpaid = _decimal(result.get("unpaid"))
    next_payout = _decimal(result.get("estimated_payout_next_block"))
    if unpaid == 0 and next_payout is not None and next_payout > 0:
        notes.append(
            "OCEAN pays this address in every block it finds, so the unpaid balance stays at 0. "
            "CashPilot cannot count those payouts yet."
        )
    return " ".join(notes) or None
