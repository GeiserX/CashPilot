"""Grass earnings collector.

Uses the Grass API with an access token (from browser localStorage) to
fetch cumulative points from the /retrieveUser endpoint.

To get the token: open app.grass.io, log in, press F12, go to
Application > Local Storage, and copy the `accessToken` value.
"""

from __future__ import annotations

import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://api.getgrass.io"


class GrassCollector(BaseCollector):
    """Collect earnings from Grass's API using an access token."""

    platform = "grass"

    def __init__(self, access_token: str) -> None:
        self.access_token = access_token

    async def collect(self) -> EarningsResult:
        """Fetch current Grass points."""
        try:
            headers = {
                "Authorization": self.access_token,
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://app.grass.io",
                "Referer": "https://app.grass.io/",
                "User-Agent": "Mozilla/5.0",
            }

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{API_BASE}/retrieveUser",
                    headers=headers,
                )

                if resp.status_code in (401, 403):
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error="Token expired — get a new accessToken from app.grass.io Local Storage",
                    )

                resp.raise_for_status()
                data = resp.json()

                user = data.get("result", {}).get("data", {})
                total_points = float(user.get("totalPoints", 0))

                return EarningsResult(
                    platform=self.platform,
                    balance=round(total_points, 4),
                    currency="GRASS_POINTS",
                )
        except Exception as exc:
            logger.error("Grass collection failed: %s", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
