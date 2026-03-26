"""MystNodes (Mysterium Network) earnings collector.

Fetches earnings data from the local Tequila API running on
the Mysterium node at port 4449.
"""

from __future__ import annotations

import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)


class MystNodesCollector(BaseCollector):
    """Collect earnings from MystNodes Tequila API."""

    platform = "mysterium"

    def __init__(self, api_url: str = "http://localhost:4449") -> None:
        self.api_url = api_url.rstrip("/")

    async def collect(self) -> EarningsResult:
        """Fetch current MystNodes earnings via Tequila API."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # Get settled + unsettled earnings
                resp = await client.get(
                    f"{self.api_url}/tequilapi/settlement/total-fees",
                )
                resp.raise_for_status()
                data = resp.json()

                # Settlement data contains amounts in MYST wei (10^18)
                settled = float(data.get("totalSettled", 0)) / 1e18
                unsettled = float(data.get("totalUnsettled", 0)) / 1e18
                total_myst = settled + unsettled

                return EarningsResult(
                    platform=self.platform,
                    balance=round(total_myst, 6),
                    currency="MYST",
                )
        except httpx.ConnectError:
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error="Cannot connect to Tequila API — is the node running?",
            )
        except Exception as exc:
            logger.error("MystNodes collection failed: %s", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
