"""ProxyRack earnings collector.

Uses the ProxyRack peer API with API key authentication to fetch
the current balance.
"""

from __future__ import annotations

import logging

import httpx  # noqa: F401 — needed for test patching

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://peer.proxyrack.com/api"


class ProxyRackCollector(BaseCollector):
    """Collect earnings from ProxyRack's peer API."""

    platform = "proxyrack"

    def __init__(self, api_key: str) -> None:
        super().__init__()
        self.api_key = api_key

    async def collect(self) -> EarningsResult:
        """Fetch current ProxyRack balance."""
        try:
            headers = {
                "Api-Key": self.api_key,
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }

            async def _fetch_balance() -> httpx.Response:
                client = self._get_client(timeout=30)
                return await client.post(
                    f"{API_BASE}/balance",
                    headers=headers,
                )

            resp = await self._retry(_fetch_balance)

            if resp.status_code in (401, 403):
                return EarningsResult(
                    platform=self.platform,
                    balance=0.0,
                    error="Authentication failed — check API key",
                )

            resp.raise_for_status()
            data = resp.json()

            # Balance is a USD string like "$1.23"
            raw = data.get("data", {}).get("balance")
            if raw is None:
                raise ValueError("balance field missing — API shape may have changed")
            balance = float(str(raw).replace("$", "").strip())

            return EarningsResult(
                platform=self.platform,
                balance=round(balance, 4),
                currency="USD",
            )
        except Exception as exc:
            logger.error("ProxyRack collection failed: %s", exc, exc_info=True)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
