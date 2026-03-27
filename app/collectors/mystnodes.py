"""MystNodes (Mysterium Network) earnings collector.

Uses the MystNodes cloud API at my.mystnodes.com to fetch total earnings
and per-node earnings breakdown.
"""

from __future__ import annotations

import logging
from typing import Any

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

    async def _ensure_token(self, client: httpx.AsyncClient) -> dict[str, str]:
        """Ensure we have a valid token and return auth headers."""
        if not self._access_token:
            await self._authenticate(client)
        return {"Authorization": f"Bearer {self._access_token}"}

    async def _get_with_retry(self, client: httpx.AsyncClient, url: str, params: dict | None = None) -> httpx.Response:
        """GET with automatic token refresh on 401."""
        headers = await self._ensure_token(client)
        resp = await client.get(url, headers=headers, params=params)
        if resp.status_code == 401:
            await self._refresh(client)
            headers = {"Authorization": f"Bearer {self._access_token}"}
            resp = await client.get(url, headers=headers, params=params)
        return resp

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
                resp = await self._get_with_retry(client, f"{CLOUD_BASE}/node/total-earnings")
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

    async def get_per_node_earnings(self) -> list[dict[str, Any]]:
        """Fetch per-node earnings from the MystNodes cloud API.

        Returns a list of dicts with:
          - identity: str (0x... address)
          - name: str (user-assigned node name or "unnamed")
          - local_ip: str
          - online: bool
          - earnings_myst: float (30-day MYST earnings)
          - lifetime_myst: float (lifetime total MYST)
          - lifetime_settled_myst: float
          - lifetime_unsettled_myst: float
        """
        if not self.email or not self.password:
            return []
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await self._get_with_retry(
                    client,
                    f"{CLOUD_BASE}/node",
                    params={"page": 1, "itemsPerPage": 100},
                )
                resp.raise_for_status()
                data = resp.json()

                result = []
                for node in data.get("nodes", []):
                    # Sum 30-day earnings across all service types
                    earnings_30d = sum(float(e.get("etherAmount", 0)) for e in node.get("earnings", []))

                    lifetime = node.get("lifetimeEarnings") or {}
                    total_ether = float(lifetime.get("totalEther", 0))
                    settled = float(lifetime.get("settledEther", 0))
                    unsettled = float(lifetime.get("unsettledEther", 0))

                    result.append(
                        {
                            "identity": node.get("identity", ""),
                            "name": node.get("name") or "",
                            "local_ip": node.get("localIp", ""),
                            "online": (node.get("nodeStatus", {}).get("online", False)),
                            "country": (node.get("country", {}).get("code", "")),
                            "version": node.get("version", ""),
                            "earnings_myst": round(earnings_30d, 6),
                            "lifetime_myst": round(total_ether, 6),
                            "lifetime_settled_myst": round(settled, 6),
                            "lifetime_unsettled_myst": round(unsettled, 6),
                        }
                    )
                return result
        except Exception as exc:
            logger.error("MystNodes per-node fetch failed: %s", exc)
            return []
