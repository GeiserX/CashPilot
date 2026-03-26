"""Traffmonetizer earnings collector.

Uses the Traffmonetizer dashboard API with token-based authentication
to fetch device statistics and earnings balance.
"""

from __future__ import annotations

import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://api.traffmonetizer.com/api"


class TraffmonetizerCollector(BaseCollector):
    """Collect earnings from Traffmonetizer's API."""

    platform = "traffmonetizer"

    def __init__(self, token: str) -> None:
        self.token = token

    async def collect(self) -> EarningsResult:
        """Fetch current Traffmonetizer balance."""
        try:
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{API_BASE}/dashboard",
                    headers=headers,
                )

                if resp.status_code in (401, 403):
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error="Authentication failed — check token",
                    )

                resp.raise_for_status()
                data = resp.json()

                # The dashboard endpoint typically returns balance info
                balance = float(data.get("balance", data.get("total", 0)))

                return EarningsResult(
                    platform=self.platform,
                    balance=round(balance, 4),
                    currency="USD",
                )
        except Exception as exc:
            logger.error("Traffmonetizer collection failed: %s", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
