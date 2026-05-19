"""EarnApp earnings collector.

Authenticates via cookie-based session (Bright Data) and fetches the
current balance from the EarnApp dashboard API.
"""

from __future__ import annotations

import logging

import httpx  # noqa: F401 — needed for test patching

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://earnapp.com/dashboard/api"


class EarnAppCollector(BaseCollector):
    """Collect earnings from EarnApp's dashboard API."""

    platform = "earnapp"
    _API_VERSION = "1.627.783"

    def __init__(self, oauth_token: str, brd_sess_id: str = "") -> None:
        super().__init__()
        self.oauth_token = oauth_token
        self.brd_sess_id = brd_sess_id

    async def collect(self) -> EarningsResult:
        """Fetch current EarnApp balance."""
        try:
            cookies = {
                "auth": "1",
                "auth-method": "google",
                "oauth-refresh-token": self.oauth_token,
            }
            if self.brd_sess_id:
                cookies["brd_sess_id"] = self.brd_sess_id

            api_params = {"appid": "earnapp", "version": self._API_VERSION}
            client = self._get_client(timeout=30, cookies=cookies)

            # Step 1: Rotate XSRF token
            await client.get(
                f"{API_BASE}/sec/rotate_xsrf",
                params=api_params,
            )
            xsrf_token = ""
            for cookie_name, cookie_value in client.cookies.items():
                if cookie_name == "xsrf-token":
                    xsrf_token = cookie_value
                    break

            # Step 2: Fetch balance
            headers = {
                "X-Requested-With": "XMLHttpRequest",
            }
            if xsrf_token:
                headers["xsrf-token"] = xsrf_token

            async def _fetch_balance():
                resp = await client.get(
                    f"{API_BASE}/money",
                    headers=headers,
                    params=api_params,
                )

                if resp.status_code == 403:
                    return resp

                resp.raise_for_status()
                return resp

            resp = await self._retry(_fetch_balance)

            if resp.status_code == 403:
                return EarningsResult(
                    platform=self.platform,
                    balance=0.0,
                    error="Authentication failed — check OAuth token and session cookie",
                )

            data = resp.json()

            if "error" in data:
                return EarningsResult(
                    platform=self.platform,
                    balance=0.0,
                    error=data["error"],
                )

            balance = float(data.get("balance", 0))

            return EarningsResult(
                platform=self.platform,
                balance=round(balance, 4),
                currency="USD",
            )
        except Exception as exc:
            logger.error("EarnApp collection failed: %s", exc, exc_info=True)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
