"""Traffmonetizer earnings collector.

Uses the Traffmonetizer dashboard API with token-based authentication
to fetch device statistics and earnings balance.
"""

from __future__ import annotations

import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://data.traffmonetizer.com/api"


class TraffmonetizerCollector(BaseCollector):
    """Collect earnings from Traffmonetizer's API."""

    platform = "traffmonetizer"

    def __init__(self, email: str = "", password: str = "", token: str = "") -> None:
        self.email = email
        self.password = password
        self._token: str | None = token or None

    async def _authenticate(self, client: httpx.AsyncClient) -> str:
        """Obtain a JWT token via email/password login."""
        resp = await client.post(
            f"{API_BASE}/auth/login",
            json={
                "email": self.email,
                "password": self.password,
                "g-recaptcha-response": "",
            },
            headers={"Origin": "https://app.traffmonetizer.com"},
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("data", {}).get("token", "") or data.get("token", "")
        if not token:
            raise ValueError("No token in Traffmonetizer login response")
        return token

    async def collect(self) -> EarningsResult:
        """Fetch current Traffmonetizer balance."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if not self._token and self.email:
                    self._token = await self._authenticate(client)

                if not self._token:
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error="No token or credentials configured",
                    )

                headers = {
                    "Authorization": f"Bearer {self._token}",
                }

                resp = await client.get(
                    f"{API_BASE}/app_user/get_balance",
                    headers=headers,
                )

                # Token may have expired — retry once with re-auth
                if resp.status_code in (401, 403) and self.email:
                    self._token = await self._authenticate(client)
                    headers["Authorization"] = f"Bearer {self._token}"
                    resp = await client.get(
                        f"{API_BASE}/app_user/get_balance",
                        headers=headers,
                    )

                if resp.status_code in (401, 403):
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error="Authentication failed — check credentials or token",
                    )

                resp.raise_for_status()
                data = resp.json()

                balance = float(data.get("data", {}).get("balance", 0))
                # m4b normalizes: if balance > 10 assume milliunits
                if balance > 10:
                    balance = balance / 1000

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
