"""Grass earnings collector.

Uses the Grass API with an access token (from browser session) to fetch
cumulative points. Grass uses OTP email login with no password, so users
must provide their access token from the browser.

To get the token: open app.grass.io, log in, then run in the browser console:
  localStorage.getItem('token')
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
                    f"{API_BASE}/users/earnings/epochs",
                    headers=headers,
                )

                if resp.status_code in (401, 403):
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error="Token expired — get a new one from app.grass.io browser console: localStorage.getItem('token')",
                    )

                resp.raise_for_status()
                data = resp.json()

                # Extract total cumulative points from epochs
                epoch_earnings = data.get("result", {}).get("data", {}).get("epochEarnings", [])
                total_points = 0.0
                if epoch_earnings:
                    total_points = float(epoch_earnings[0].get("totalCumulativePoints", 0))

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
