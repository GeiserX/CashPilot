"""Honeygain earnings collector.

Authenticates via JWT and fetches the current balance from the
Honeygain API.
"""

from __future__ import annotations

import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://dashboard.honeygain.com/api"


class HoneygainCollector(BaseCollector):
    """Collect earnings from Honeygain's REST API."""

    platform = "honeygain"

    def __init__(self, email: str, password: str) -> None:
        self.email = email
        self.password = password
        self._token: str | None = None

    async def _authenticate(self, client: httpx.AsyncClient) -> str:
        """Obtain a JWT token via email/password login."""
        resp = await client.post(
            f"{API_BASE}/v1/auth/login",
            json={"email": self.email, "password": self.password},
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("data", {}).get("access_token", "")
        if not token:
            raise ValueError("No access_token in Honeygain login response")
        return token

    async def collect(self) -> EarningsResult:
        """Fetch current Honeygain balance."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if not self._token:
                    self._token = await self._authenticate(client)

                headers = {"Authorization": f"Bearer {self._token}"}
                resp = await client.get(
                    f"{API_BASE}/v2/users/balances",
                    headers=headers,
                )

                # Token may have expired — retry once
                if resp.status_code == 401:
                    self._token = await self._authenticate(client)
                    headers = {"Authorization": f"Bearer {self._token}"}
                    resp = await client.get(
                        f"{API_BASE}/v2/users/balances",
                        headers=headers,
                    )

                resp.raise_for_status()
                data = resp.json()

                # Balance is in credits (1000 credits = $1)
                balances = data.get("data", {})
                credits_total = float(balances.get("realtime", {}).get("credits", 0))
                balance_usd = round(credits_total / 1000, 4)

                return EarningsResult(
                    platform=self.platform,
                    balance=balance_usd,
                    currency="USD",
                )
        except Exception as exc:
            logger.error("Honeygain collection failed: %s", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
