"""Salad earnings collector.

Authenticates via Bearer token and fetches the current balance from
the Salad API at app-api.salad.com.

To get the token: open salad.com in your browser, log in, press F12,
go to Network tab, find any request to app-api.salad.com, and copy
the Authorization header value (without the "Bearer " prefix).
"""

from __future__ import annotations

import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://app-api.salad.com/api/v1"


class SaladCollector(BaseCollector):
    """Collect earnings from Salad's API using a Bearer token."""

    platform = "salad"

    def __init__(self, access_token: str) -> None:
        self.access_token = access_token

    async def collect(self) -> EarningsResult:
        """Fetch current Salad balance."""
        try:
            headers = {"Authorization": f"Bearer {self.access_token}"}

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{API_BASE}/profile/balance",
                    headers=headers,
                )

                if resp.status_code in (401, 403):
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error="Token expired — get a new Bearer token from salad.com Network tab",
                    )

                resp.raise_for_status()
                data = resp.json()

                balance = float(data.get("currentBalance", 0))

                return EarningsResult(
                    platform=self.platform,
                    balance=round(balance, 4),
                    currency="USD",
                )
        except Exception as exc:
            logger.error("Salad collection failed: %s", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
