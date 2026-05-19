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
    _HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://dashboard.honeygain.com/"}

    def __init__(self, email: str, password: str) -> None:
        super().__init__()
        self.email = email
        self.password = password
        self._token: str | None = None

    async def _authenticate(self, client: httpx.AsyncClient) -> str:
        """Obtain a JWT token via email/password login."""
        resp = await client.post(
            f"{API_BASE}/v1/users/tokens",
            json={"email": self.email, "password": self.password},
            headers=self._HEADERS,
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
            client = self._get_client(timeout=30)

            if not self._token:
                self._token = await self._authenticate(client)

            async def _fetch_balance():
                headers = {**self._HEADERS, "Authorization": f"Bearer {self._token}"}
                resp = await client.get(
                    f"{API_BASE}/v1/users/balances",
                    headers=headers,
                )

                # Token may have expired — retry once
                if resp.status_code == 401:
                    self._token = await self._authenticate(client)
                    headers = {**self._HEADERS, "Authorization": f"Bearer {self._token}"}
                    resp = await client.get(
                        f"{API_BASE}/v1/users/balances",
                        headers=headers,
                    )

                resp.raise_for_status()
                return resp

            resp = await self._retry(_fetch_balance)
            data = resp.json()

            # Balance is in cents (usd_cents)
            payout = data.get("data", {}).get("payout", {})
            usd_cents = float(payout.get("usd_cents", 0))
            balance_usd = round(usd_cents / 100, 4)

            return EarningsResult(
                platform=self.platform,
                balance=balance_usd,
                currency="USD",
            )
        except Exception as exc:
            logger.error("Honeygain collection failed: %s", exc, exc_info=True)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
