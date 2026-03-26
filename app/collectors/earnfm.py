"""Earn.fm earnings collector.

Authenticates via Supabase (sb.earn.fm) and fetches balance from
the Earn.fm harvester API.
"""

from __future__ import annotations

import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

SUPABASE_URL = "https://sb.earn.fm"
SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBucmFsZnNmd3Nia2pjZG1uZGF5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3MjI0NjE5NjQsImV4cCI6MjAzODAzNzk2NH0."
    "X4M2GXm8Ea_2QtoiyHn_3Ce5yvSjQZo"
)
API_BASE = "https://api.earn.fm/v2"


class EarnFMCollector(BaseCollector):
    """Collect earnings from Earn.fm's API via Supabase auth."""

    platform = "earnfm"

    def __init__(self, email: str, password: str) -> None:
        self.email = email
        self.password = password
        self._access_token: str | None = None
        self._refresh_token: str | None = None

    async def _authenticate(self, client: httpx.AsyncClient) -> str:
        """Obtain Supabase access token via email/password."""
        resp = await client.post(
            f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
            json={"email": self.email, "password": self.password},
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data.get("access_token", "")
        self._refresh_token = data.get("refresh_token", "")
        if not self._access_token:
            raise ValueError("No access_token in Supabase login response")
        return self._access_token

    async def _refresh(self, client: httpx.AsyncClient) -> str:
        """Refresh Supabase access token."""
        if not self._refresh_token:
            return await self._authenticate(client)
        resp = await client.post(
            f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token",
            json={"refresh_token": self._refresh_token},
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Content-Type": "application/json",
            },
        )
        if resp.status_code in (401, 403):
            return await self._authenticate(client)
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data.get("access_token", "")
        self._refresh_token = data.get("refresh_token", self._refresh_token)
        return self._access_token

    async def collect(self) -> EarningsResult:
        """Fetch current Earn.fm balance."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if not self._access_token:
                    await self._authenticate(client)

                headers = {"X-API-Key": self._access_token}
                resp = await client.get(
                    f"{API_BASE}/harvester/view_balance",
                    headers=headers,
                )

                if resp.status_code == 401:
                    await self._refresh(client)
                    headers = {"X-API-Key": self._access_token}
                    resp = await client.get(
                        f"{API_BASE}/harvester/view_balance",
                        headers=headers,
                    )

                resp.raise_for_status()
                data = resp.json()

                balance = float(data.get("data", {}).get("totalBalance", 0))

                return EarningsResult(
                    platform=self.platform,
                    balance=round(balance, 4),
                    currency="USD",
                )
        except Exception as exc:
            logger.error("EarnFM collection failed: %s", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
