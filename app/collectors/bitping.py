"""Bitping earnings collector.

Authenticates via email/password and fetches earnings from the
Bitping nodes API.
"""

from __future__ import annotations

import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://nodes.bitping.com"


class BitpingCollector(BaseCollector):
    """Collect earnings from Bitping's API."""

    platform = "bitping"

    def __init__(self, email: str, password: str) -> None:
        self.email = email
        self.password = password
        self._token: str | None = None

    async def _authenticate(self, client: httpx.AsyncClient) -> str:
        """Obtain JWT token via email/password login."""
        resp = await client.post(
            f"{API_BASE}/auth/login",
            json={"email": self.email, "password": self.password},
        )
        resp.raise_for_status()
        # Token comes as HttpOnly cookie named "token"
        token = ""
        for name, value in client.cookies.items():
            if name == "token":
                token = value
                break
        # Also check response body
        if not token:
            data = resp.json()
            token = data.get("token", "")
        if not token:
            raise ValueError("No token in Bitping login response")
        return token

    async def collect(self) -> EarningsResult:
        """Fetch current Bitping earnings."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if not self._token:
                    self._token = await self._authenticate(client)

                headers = {"Authorization": f"Bearer {self._token}"}
                resp = await client.get(
                    f"{API_BASE}/api/v2/payouts/earnings",
                    headers=headers,
                )

                if resp.status_code == 401:
                    self._token = await self._authenticate(client)
                    headers = {"Authorization": f"Bearer {self._token}"}
                    resp = await client.get(
                        f"{API_BASE}/api/v2/payouts/earnings",
                        headers=headers,
                    )

                resp.raise_for_status()
                data = resp.json()

                balance = float(data.get("usdEarnings", 0))

                return EarningsResult(
                    platform=self.platform,
                    balance=round(balance, 4),
                    currency="USD",
                )
        except Exception as exc:
            logger.error("Bitping collection failed: %s", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
