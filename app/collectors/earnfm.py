"""Earn.fm earnings collector.

Authenticates via Supabase (email/password) at sb.earn.fm, then uses
the access token to query the harvester balance API.
"""

from __future__ import annotations

import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

SUPABASE_URL = "https://sb.earn.fm"
SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "ewogICJyb2xlIjogImFub24iLAogICJpc3MiOiAic3VwYWJhc2UiLAogICJpYXQiOiAxNjkyNjU1MjAwLAogICJleHAiOiAxODUwNTA4MDAwCn0."
    "jp-Uj5ro0jj7MHnlE8HHZRsZAFOI1d_T9n_9tnE09vM"
)
API_BASE = "https://api.earn.fm/v2"


class EarnFMCollector(BaseCollector):
    """Collect earnings from Earn.fm using Supabase email/password auth."""

    platform = "earnfm"

    def __init__(self, email: str, password: str) -> None:
        super().__init__()
        self._email = email.strip()
        self._password = password.strip()
        self._access_token: str = ""

    async def _authenticate(self) -> str | None:
        """Sign in via Supabase and return the access token."""
        client = self._get_client(timeout=30)
        resp = await client.post(
            f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Content-Type": "application/json",
            },
            json={"email": self._email, "password": self._password},
        )
        if resp.status_code == 400:
            return None
        resp.raise_for_status()
        data = resp.json()
        return data.get("access_token")

    async def collect(self) -> EarningsResult:
        """Fetch current Earn.fm balance."""
        if not self._email or not self._password:
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error="No credentials configured — enter Earn.fm email and password",
            )

        try:
            token = await self._authenticate()
            if not token:
                return EarningsResult(
                    platform=self.platform,
                    balance=0.0,
                    error="Invalid credentials — check Earn.fm email/password in Settings",
                )

            client = self._get_client(timeout=30)

            async def _fetch_balance() -> httpx.Response:
                return await client.get(
                    f"{API_BASE}/harvester/view_balance",
                    headers={"X-API-Key": token},
                )

            resp = await self._retry(_fetch_balance)

            if resp.status_code in (401, 403):
                return EarningsResult(
                    platform=self.platform,
                    balance=0.0,
                    error="Auth token rejected — check Earn.fm email/password in Settings",
                )

            resp.raise_for_status()
            data = resp.json()

            balance_data = data.get("data") or {}
            balance = float(balance_data.get("totalBalance", 0))

            return EarningsResult(
                platform=self.platform,
                balance=round(balance, 4),
                currency="USD",
            )
        except Exception as exc:
            logger.error("EarnFM collection failed: %s", exc, exc_info=True)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )

