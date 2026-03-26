"""Repocket earnings collector.

Authenticates via Firebase (Google Identity Toolkit) and fetches the
current balance from the Repocket API.
"""

from __future__ import annotations

import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

FIREBASE_KEY = "AIzaSyBJf6hyw47O-5TrAwQszkwvDEh-Ri6q6SU"
FIREBASE_AUTH = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_KEY}"
FIREBASE_REFRESH = f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_KEY}"
API_BASE = "https://api.repocket.com/api"


class RepocketCollector(BaseCollector):
    """Collect earnings from Repocket's API via Firebase auth."""

    platform = "repocket"

    def __init__(self, email: str, password: str) -> None:
        self.email = email
        self.password = password
        self._id_token: str | None = None
        self._refresh_token: str | None = None

    async def _authenticate(self, client: httpx.AsyncClient) -> str:
        """Obtain Firebase ID token via email/password."""
        resp = await client.post(
            FIREBASE_AUTH,
            json={
                "email": self.email,
                "password": self.password,
                "returnSecureToken": True,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._id_token = data.get("idToken", "")
        self._refresh_token = data.get("refreshToken", "")
        if not self._id_token:
            raise ValueError("No idToken in Firebase login response")
        return self._id_token

    async def _refresh(self, client: httpx.AsyncClient) -> str:
        """Refresh Firebase ID token."""
        if not self._refresh_token:
            return await self._authenticate(client)
        resp = await client.post(
            FIREBASE_REFRESH,
            json={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            },
        )
        if resp.status_code in (401, 403):
            return await self._authenticate(client)
        resp.raise_for_status()
        data = resp.json()
        self._id_token = data.get("id_token", "")
        self._refresh_token = data.get("refresh_token", self._refresh_token)
        return self._id_token

    async def collect(self) -> EarningsResult:
        """Fetch current Repocket balance."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if not self._id_token:
                    await self._authenticate(client)

                headers = {"Auth-Token": self._id_token}
                resp = await client.get(
                    f"{API_BASE}/reports/current",
                    headers=headers,
                )

                if resp.status_code == 401:
                    await self._refresh(client)
                    headers = {"Auth-Token": self._id_token}
                    resp = await client.get(
                        f"{API_BASE}/reports/current",
                        headers=headers,
                    )

                resp.raise_for_status()
                data = resp.json()

                # centsCredited is in cents
                cents = float(data.get("centsCredited", 0))
                balance_usd = round(cents / 100, 4)

                return EarningsResult(
                    platform=self.platform,
                    balance=balance_usd,
                    currency="USD",
                )
        except Exception as exc:
            logger.error("Repocket collection failed: %s", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
