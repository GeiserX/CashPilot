"""MystNodes (Mysterium Network) earnings collector.

Uses the MystNodes cloud API at my.mystnodes.com to fetch total earnings.
Falls back to local Tequila API if cloud credentials are not configured.
"""

from __future__ import annotations

import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

CLOUD_BASE = "https://my.mystnodes.com/api/v2"


class MystNodesCollector(BaseCollector):
    """Collect earnings from MystNodes cloud API."""

    platform = "mysterium"

    def __init__(
        self,
        email: str = "",
        password: str = "",
    ) -> None:
        self.email = email
        self.password = password
        self._access_token: str | None = None
        self._refresh_token: str | None = None

    async def _authenticate(self, client: httpx.AsyncClient) -> str:
        """Obtain access token via cloud login."""
        resp = await client.post(
            f"{CLOUD_BASE}/auth/login",
            json={
                "email": self.email,
                "password": self.password,
                "remember": True,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data.get("accessToken", "")
        self._refresh_token = data.get("refreshToken", "")
        if not self._access_token:
            raise ValueError("No accessToken in MystNodes login response")
        return self._access_token

    async def _refresh(self, client: httpx.AsyncClient) -> str:
        """Refresh access token."""
        if not self._refresh_token:
            return await self._authenticate(client)
        resp = await client.post(
            f"{CLOUD_BASE}/auth/refresh",
            json={"refreshToken": self._refresh_token},
        )
        if resp.status_code in (401, 403):
            return await self._authenticate(client)
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data.get("accessToken", "")
        self._refresh_token = data.get("refreshToken", self._refresh_token)
        return self._access_token

    async def collect(self) -> EarningsResult:
        """Fetch total MystNodes earnings via cloud API."""
        if not self.email or not self.password:
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error="MystNodes email/password not configured",
            )
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if not self._access_token:
                    await self._authenticate(client)

                headers = {"Authorization": f"Bearer {self._access_token}"}
                resp = await client.get(
                    f"{CLOUD_BASE}/node/total-earnings",
                    headers=headers,
                )

                # Token expired — refresh and retry
                if resp.status_code == 401:
                    await self._refresh(client)
                    headers = {"Authorization": f"Bearer {self._access_token}"}
                    resp = await client.get(
                        f"{CLOUD_BASE}/node/total-earnings",
                        headers=headers,
                    )

                resp.raise_for_status()
                data = resp.json()

                # earningsTotal is already in USD
                total_usd = float(data.get("earningsTotal", 0))

                return EarningsResult(
                    platform=self.platform,
                    balance=round(total_usd, 4),
                    currency="USD",
                )
        except Exception as exc:
            logger.error("MystNodes collection failed: %s", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
