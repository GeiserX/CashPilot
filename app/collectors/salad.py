"""Salad earnings collector.

Authenticates via session cookie and fetches the current balance from
the Salad API.

To get the token: open app.salad.io in your browser, log in, press F12,
go to Application > Cookies, and copy the `sAccessToken` value.
"""

from __future__ import annotations

import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://app-api.salad.io/api/v1"


class SaladCollector(BaseCollector):
    """Collect earnings from Salad's API using the session cookie."""

    platform = "salad"

    def __init__(self, access_token: str) -> None:
        self.access_token = access_token

    async def collect(self) -> EarningsResult:
        """Fetch current Salad balance."""
        try:
            cookies = {"sAccessToken": self.access_token}

            async with httpx.AsyncClient(timeout=30, cookies=cookies) as client:
                resp = await client.get(f"{API_BASE}/profile/balance")

                if resp.status_code in (401, 403):
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error="Session expired — get a new sAccessToken cookie from app.salad.io",
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
