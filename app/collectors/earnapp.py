"""EarnApp earnings collector.

Authenticates via OAuth refresh token cookie and fetches the current
balance from the EarnApp dashboard API (Bright Data).
"""

from __future__ import annotations

import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://earnapp.com/dashboard/api"


class EarnAppCollector(BaseCollector):
    """Collect earnings from EarnApp's dashboard API."""

    platform = "earnapp"

    def __init__(self, oauth_token: str) -> None:
        self.oauth_token = oauth_token

    async def collect(self) -> EarningsResult:
        """Fetch current EarnApp balance."""
        try:
            headers = {
                "cookie": f"auth=1;auth-method=google;oauth-token={self.oauth_token}",
            }
            params = {"appid": "earnapp_dashboard"}

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{API_BASE}/money/",
                    headers=headers,
                    params=params,
                )

                if resp.status_code == 403:
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error="Authentication failed — check OAuth token",
                    )

                resp.raise_for_status()
                data = resp.json()

                if "error" in data:
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error=data["error"],
                    )

                balance = float(data.get("balance", 0))

                return EarningsResult(
                    platform=self.platform,
                    balance=round(balance, 4),
                    currency="USD",
                )
        except Exception as exc:
            logger.error("EarnApp collection failed: %s", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
