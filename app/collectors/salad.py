"""Salad earnings collector.

Authenticates via the ``auth`` cookie and fetches the current balance
from the Salad API at app-api.salad.com.

Salad uses ASP.NET Core anti-forgery: the ``auth`` cookie value must
also be sent as the ``X-XSRF-TOKEN`` header (double-submit pattern).

To get the token: open salad.com in your browser, log in, press F12,
go to Application > Cookies > .salad.com, and copy the ``auth`` cookie.
"""

from __future__ import annotations

import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://app-api.salad.com/api/v1"


class SaladCollector(BaseCollector):
    """Collect earnings from Salad's API using the auth cookie."""

    platform = "salad"

    def __init__(self, auth_cookie: str) -> None:
        self.auth_cookie = auth_cookie

    async def collect(self) -> EarningsResult:
        """Fetch current Salad balance."""
        try:
            cookies = {"auth": self.auth_cookie}
            headers = {"X-XSRF-TOKEN": self.auth_cookie}

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{API_BASE}/profile/balance",
                    cookies=cookies,
                    headers=headers,
                )

                if resp.status_code in (401, 403):
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error="Auth cookie expired — get a new 'auth' cookie from salad.com",
                    )

                resp.raise_for_status()
                data = resp.json()

                balance = float(data.get("currentBalance", 0))

                return EarningsResult(
                    platform=self.platform,
                    balance=round(balance, 4),
                    currency="USD",
                )
        except Exception as exc:
            logger.error("Salad collection failed: %s", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
