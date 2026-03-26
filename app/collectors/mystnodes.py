"""MystNodes (Mysterium Network) earnings collector.

Fetches earnings data from the local Tequila API running on
the Mysterium node at port 4449.
"""

from __future__ import annotations

import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)


class MystNodesCollector(BaseCollector):
    """Collect earnings from MystNodes Tequila API."""

    platform = "mysterium"

    def __init__(
        self,
        api_url: str = "http://localhost:4449",
        password: str = "",
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.password = password

    async def _get_auth_header(self, client: httpx.AsyncClient) -> dict[str, str]:
        """Authenticate and return Authorization header, or empty dict if no password."""
        if not self.password:
            return {}
        resp = await client.post(
            f"{self.api_url}/tequilapi/auth/authenticate",
            json={"username": "myst", "password": self.password},
        )
        resp.raise_for_status()
        token = resp.json().get("token", "")
        return {"Authorization": f"Bearer {token}"}

    async def collect(self) -> EarningsResult:
        """Fetch current MystNodes earnings via Tequila API."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                headers = await self._get_auth_header(client)

                # Get aggregated session stats (contains total tokens earned)
                resp = await client.get(
                    f"{self.api_url}/tequilapi/sessions/stats-aggregated",
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

                # sum_tokens is in MYST wei (10^18)
                sum_tokens = float(data.get("stats", {}).get("sum_tokens", 0))
                total_myst = sum_tokens / 1e18

                return EarningsResult(
                    platform=self.platform,
                    balance=round(total_myst, 6),
                    currency="MYST",
                )
        except httpx.ConnectError:
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error="Cannot connect to Tequila API — is the node running?",
            )
        except Exception as exc:
            logger.error("MystNodes collection failed: %s", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
