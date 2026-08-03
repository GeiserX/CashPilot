"""Storj storagenode earnings collector.

Fetches estimated payout from the local storagenode API (port 14002).
No authentication required — the API is only accessible on localhost.
"""

from __future__ import annotations

import logging

import httpx

from app.collectors import base
from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "http://localhost:14002"


class StorjCollector(BaseCollector):
    """Collect earnings from a Storj storagenode's local API."""

    platform = "storj"

    def __init__(self, api_url: str = DEFAULT_API_URL) -> None:
        super().__init__()
        self.api_url = api_url.rstrip("/")

    async def collect(self) -> EarningsResult:
        """Fetch current Storj storagenode estimated payout."""
        try:
            client = self._get_client(timeout=15)
            resp = await self._retry(lambda: client.get(f"{self.api_url}/api/sno/estimated-payout"))

            if resp.status_code == 404:
                # Older storagenode versions use different endpoint
                resp = await client.get(f"{self.api_url}/api/sno")

            resp.raise_for_status()
            data = resp.json()

            # estimated-payout endpoint returns cents
            if "currentMonth" in data:
                # Payout values are in cents (integer)
                # Absent keys are a SHAPE CHANGE, not zero earnings.
                #
                # Three .get(name, 0) defaults summed to a confident 0.00 when
                # storagenode renamed its payout sub-fields, and that zero was
                # recorded as a real balance. Because it is a DROP from the
                # previous reading, _detect_payout then asked the user to
                # confirm a payout of their entire balance that never happened
                # — and a confirmed payout is permanent.
                #
                # The ValueError below is unreachable once currentMonth exists,
                # so this branch has to do its own shape check.
                month = data["currentMonth"]
                known = [
                    k for k in ("egressBandwidthPayout", "egressRepairAuditPayout", "diskSpacePayout") if k in month
                ]
                if not known:
                    raise ValueError(
                        "storagenode currentMonth has no known payout field "
                        f"(saw: {sorted(month)[:6]}) — the API shape may have changed"
                    )
                payout_cents = sum(month.get(k, 0) for k in known)
                balance = payout_cents / 100.0
            elif "estimatedPayout" in data:
                balance = data["estimatedPayout"] / 100.0
            elif "currentMonthExpectations" in data:
                balance = data["currentMonthExpectations"] / 100.0
            else:
                raise ValueError("Unrecognized storagenode API response shape — no known payout field found")

            return EarningsResult(
                platform=self.platform,
                balance=round(balance, 4),
                currency="USD",
            )
        except httpx.ConnectError:
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=(
                    "Storagenode API not reachable at "
                    f"{self.api_url} — if running in Docker, use "
                    "the node's LAN IP instead of localhost "
                    "(e.g. http://192.168.1.x:14002)"
                ),
            )
        except Exception as exc:
            base.log_failure(logger, "Storj", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
