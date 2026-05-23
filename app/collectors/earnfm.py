"""Earn.fm earnings collector.

Authenticates via a UUID API key (EARNFM_TOKEN) obtained from the
Earn.fm dashboard at app.earn.fm > Account Settings.
"""

from __future__ import annotations

import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://api.earn.fm/v2"


class EarnFMCollector(BaseCollector):
    """Collect earnings from Earn.fm's API using a token."""

    platform = "earnfm"

    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token.strip()

    async def collect(self) -> EarningsResult:
        """Fetch current Earn.fm balance."""
        if not self._token:
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error="No token configured — copy API key from app.earn.fm > Settings",
            )

        try:
            client = self._get_client(timeout=30)
            headers = {"X-API-Key": self._token}

            async def _fetch_balance() -> httpx.Response:
                return await client.get(
                    f"{API_BASE}/harvester/view_balance",
                    headers=headers,
                )

            resp = await self._retry(_fetch_balance)

            if resp.status_code in (401, 403):
                return EarningsResult(
                    platform=self.platform,
                    balance=0.0,
                    error="Token invalid or expired — refresh API key from app.earn.fm",
                )

            resp.raise_for_status()
            data = resp.json()

            balance = float((data.get("data") or {}).get("totalBalance", 0))

            return EarningsResult(
                platform=self.platform,
                balance=round(balance, 4),
                currency="USD",
            )
        except Exception as exc:
            logger.error("EarnFM collection failed: %s", exc, exc_info=True)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
