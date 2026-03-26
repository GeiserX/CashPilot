"""EarnApp earnings collector.

Authenticates via cookie-based session (Bright Data) and fetches the
current balance from the EarnApp dashboard API.
"""

from __future__ import annotations

import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://earnapp.com/dashboard/api"
API_PARAMS = {"appid": "earnapp", "version": "1.613.719"}


class EarnAppCollector(BaseCollector):
    """Collect earnings from EarnApp's dashboard API."""

    platform = "earnapp"

    def __init__(self, oauth_token: str, brd_sess_id: str = "") -> None:
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

            async with httpx.AsyncClient(timeout=30, cookies=cookies) as client:
                # Step 1: Rotate XSRF token
                xsrf_resp = await client.get(
                    f"{API_BASE}/sec/rotate_xsrf",
                    params=API_PARAMS,
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

                resp = await client.get(
                    f"{API_BASE}/money",
                    headers=headers,
                    params=API_PARAMS,
                )

                if resp.status_code == 403:
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error="Authentication failed — check OAuth token and session cookie",
                    )

                resp.raise_for_status()
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
            logger.error("EarnApp collection failed: %s", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
