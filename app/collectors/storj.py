"""Storj storagenode earnings collector.

Fetches estimated payout from the local storagenode API (port 14002).
No authentication required — the API is only accessible on localhost.
"""

from __future__ import annotations

import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "http://localhost:14002"


class StorjCollector(BaseCollector):
    """Collect earnings from a Storj storagenode's local API."""

    platform = "storj"

    def __init__(self, api_url: str = DEFAULT_API_URL) -> None:
        self.api_url = api_url.rstrip("/")

    async def collect(self) -> EarningsResult:
        """Fetch current Storj storagenode estimated payout."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{self.api_url}/api/sno/estimated-payout")

                if resp.status_code == 404:
                    # Older storagenode versions use different endpoint
                    resp = await client.get(f"{self.api_url}/api/sno")

                resp.raise_for_status()
                data = resp.json()

                # estimated-payout endpoint returns cents
                if "currentMonth" in data:
                    # Payout values are in cents (integer)
                    payout_cents = data["currentMonth"].get("egressBandwidthPayout", 0)
                    payout_cents += data["currentMonth"].get("egressRepairAuditPayout", 0)
                    payout_cents += data["currentMonth"].get("diskSpacePayout", 0)
                    balance = payout_cents / 100.0
                elif "estimatedPayout" in data:
                    balance = data["estimatedPayout"] / 100.0
                elif "currentMonthExpectations" in data:
                    balance = data["currentMonthExpectations"] / 100.0
                else:
                    # Fallback: try /api/sno for totalPayout
                    balance = 0.0

                return EarningsResult(
                    platform=self.platform,
                    balance=round(balance, 4),
                    currency="USD",
                )
        except httpx.ConnectError:
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error="Storagenode API not reachable — is port 14002 accessible?",
            )
        except Exception as exc:
            logger.error("Storj collection failed: %s", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
