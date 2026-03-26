"""Bytelixir earnings collector.

Uses session cookie from the browser to fetch balance via /api/v1/user.
Bytelixir is a Laravel app with hCaptcha on login, so automated login
is not possible. Users must extract session cookies from their browser.

To get the cookie: open dash.bytelixir.com, log in (tick "Remember Me"),
press F12 > Application > Cookies, and copy the `bytelixir_session` value.

Note: session expires after ~3.5 hours. When expired, the collector
returns an error that surfaces as a notification in the CashPilot UI.
"""

from __future__ import annotations

import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://dash.bytelixir.com"


class BytelixirCollector(BaseCollector):
    """Collect earnings from Bytelixir using a session cookie."""

    platform = "bytelixir"

    def __init__(self, session_cookie: str) -> None:
        self.session_cookie = session_cookie

    async def collect(self) -> EarningsResult:
        """Fetch current Bytelixir balance."""
        try:
            cookies = httpx.Cookies()
            cookies.set("bytelixir_session", self.session_cookie, domain="dash.bytelixir.com")

            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{API_BASE}/en",
                "Origin": API_BASE,
            }

            async with httpx.AsyncClient(timeout=30, cookies=cookies) as client:
                resp = await client.get(
                    f"{API_BASE}/api/v1/user",
                    headers=headers,
                )

                if resp.status_code == 401:
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error="Session expired — refresh bytelixir_session cookie in Settings",
                    )

                resp.raise_for_status()
                data = resp.json()

                # Response shape: {"data": {"balance": "0.0000000000", ...}}
                user_data = data.get("data", {})
                balance_str = user_data.get("balance", "0")
                balance = float(balance_str)

                return EarningsResult(
                    platform=self.platform,
                    balance=round(balance, 4),
                    currency="USD",
                )
        except Exception as exc:
            logger.error("Bytelixir collection failed: %s", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
