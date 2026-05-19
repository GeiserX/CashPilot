"""Traffmonetizer earnings collector.

Traffmonetizer enforces reCAPTCHA on their login endpoint, making
programmatic email/password authentication impossible. Users must
extract a JWT from their browser session.

To get the token: open app.traffmonetizer.com, log in, press F12,
go to Application > Local Storage > https://app.traffmonetizer.com,
and copy the `access_token` value (a long JWT string).
"""

from __future__ import annotations

import logging

import httpx  # noqa: F401 (used by test patches targeting this module)

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://data.traffmonetizer.com/api"


class TraffmonetizerCollector(BaseCollector):
    """Collect earnings from Traffmonetizer's API using a browser JWT."""

    platform = "traffmonetizer"

    def __init__(self, token: str = "") -> None:
        super().__init__()
        self._token = token.strip()

    async def collect(self) -> EarningsResult:
        """Fetch current Traffmonetizer balance."""
        if not self._token:
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error="No token configured — extract access_token from browser Local Storage",
            )

        try:
            client = self._get_client(timeout=30)
            headers = {
                "Authorization": f"Bearer {self._token}",
                "Origin": "https://app.traffmonetizer.com",
                "Referer": "https://app.traffmonetizer.com/",
            }

            resp = await self._retry(
                lambda: client.get(
                    f"{API_BASE}/app_user/get_balance",
                    headers=headers,
                )
            )

            if resp.status_code in (401, 403):
                return EarningsResult(
                    platform=self.platform,
                    balance=0.0,
                    error="Token expired — refresh access_token from browser Local Storage",
                )

            resp.raise_for_status()
            data = resp.json()

            balance = float(data.get("data", {}).get("balance", 0))

            return EarningsResult(
                platform=self.platform,
                balance=round(balance, 4),
                currency="USD",
            )
        except Exception as exc:
            logger.error("Traffmonetizer collection failed: %s", exc, exc_info=True)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
