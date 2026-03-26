"""Bytelixir earnings collector.

Authenticates via email/password to the Bytelixir dashboard API and
fetches the current balance.
"""

from __future__ import annotations

import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

DASH_BASE = "https://dash.bytelixir.com"


class BytelixirCollector(BaseCollector):
    """Collect earnings from Bytelixir's dashboard."""

    platform = "bytelixir"

    def __init__(self, email: str, password: str) -> None:
        self.email = email
        self.password = password
        self._token: str | None = None

    async def _authenticate(self, client: httpx.AsyncClient) -> str:
        """Log in and obtain a session/token."""
        resp = await client.post(
            f"{DASH_BASE}/api/auth/login",
            json={"email": self.email, "password": self.password},
            headers={
                "User-Agent": "Mozilla/5.0",
                "Origin": DASH_BASE,
                "Referer": f"{DASH_BASE}/",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        # Try common token locations in response
        token = (
            data.get("token")
            or data.get("access_token")
            or data.get("data", {}).get("token", "")
            or data.get("data", {}).get("access_token", "")
        )
        if not token:
            raise ValueError(f"No token in Bytelixir login response (keys: {list(data.keys())})")
        return token

    async def collect(self) -> EarningsResult:
        """Fetch current Bytelixir balance."""
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                if not self._token:
                    self._token = await self._authenticate(client)

                headers = {
                    "Authorization": f"Bearer {self._token}",
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json",
                    "Origin": DASH_BASE,
                    "Referer": f"{DASH_BASE}/",
                }

                # Try the dashboard/earnings endpoints
                for path in (
                    "/api/user/balance",
                    "/api/user/earnings",
                    "/api/dashboard",
                    "/api/user",
                    "/api/me",
                ):
                    resp = await client.get(
                        f"{DASH_BASE}{path}",
                        headers=headers,
                    )

                    # Token expired — retry auth once
                    if resp.status_code == 401:
                        self._token = await self._authenticate(client)
                        headers["Authorization"] = f"Bearer {self._token}"
                        resp = await client.get(
                            f"{DASH_BASE}{path}",
                            headers=headers,
                        )

                    if resp.status_code == 200:
                        data = resp.json()
                        balance = _extract_balance(data)
                        if balance is not None:
                            return EarningsResult(
                                platform=self.platform,
                                balance=round(balance, 4),
                                currency="USD",
                            )

                return EarningsResult(
                    platform=self.platform,
                    balance=0.0,
                    error="Could not find balance in Bytelixir API responses",
                )
        except Exception as exc:
            logger.error("Bytelixir collection failed: %s", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )


def _extract_balance(data: dict) -> float | None:
    """Try to extract a USD balance from various response shapes."""
    # Direct balance field
    for key in ("balance", "total_balance", "earnings", "total_earnings"):
        val = data.get(key)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                continue

    # Nested under 'data'
    inner = data.get("data", {})
    if isinstance(inner, dict):
        for key in ("balance", "total_balance", "earnings", "total_earnings"):
            val = inner.get(key)
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    continue

    # Nested under 'user'
    user = data.get("user", {})
    if isinstance(user, dict):
        for key in ("balance", "earnings"):
            val = user.get(key)
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    continue

    return None
