"""Bytelixir earnings collector.

Bytelixir is a Laravel app with hCaptcha on login, so automated login
is not possible. Users must extract session cookies from their browser.

To get the cookie: open dash.bytelixir.com, log in (tick "Remember Me"),
press F12 > Application > Cookies, and copy the `bytelixir_session` value.

Earnings are obtained by scraping the server-rendered dashboard HTML,
which contains ``data-balance`` attributes on Alpine.js ``Balance()``
components.  The ``/api/v1/user`` endpoint only returns the
*withdrawable* balance (always 0 until the payout threshold is reached),
**not** the total earned amount shown on the dashboard.

Note: session lifetime depends on "Remember Me" — with it ticked, cookies
last days/weeks. Without it, they expire quickly. When expired, the collector
returns an error that surfaces as a notification in the CashPilot UI.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import unquote

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://dash.bytelixir.com"


class BytelixirCollector(BaseCollector):
    """Collect earnings from Bytelixir using a session cookie."""

    platform = "bytelixir"

    # The Laravel "remember me" cookie name — constant per app guard.
    _REMEMBER_COOKIE = "remember_web_59ba36addc2b2f9401580f014c7f58ea4e30989d"

    def __init__(
        self,
        session_cookie: str,
        remember_web: str = "",
        xsrf_token: str = "",
    ) -> None:
        self.session_cookie = unquote(session_cookie)
        self.remember_web = unquote(remember_web) if remember_web else ""
        self.xsrf_token = unquote(xsrf_token) if xsrf_token else ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_client(self) -> httpx.AsyncClient:
        """Build an httpx client with all session cookies pre-set."""
        cookies = httpx.Cookies()
        cookies.set(
            "bytelixir_session",
            self.session_cookie,
            domain="dash.bytelixir.com",
        )
        if self.remember_web:
            cookies.set(
                self._REMEMBER_COOKIE,
                self.remember_web,
                domain="dash.bytelixir.com",
            )
        if self.xsrf_token:
            cookies.set(
                "XSRF-TOKEN",
                self.xsrf_token,
                domain="dash.bytelixir.com",
            )
        return httpx.AsyncClient(
            timeout=30,
            cookies=cookies,
            follow_redirects=True,
        )

    @staticmethod
    def _browser_headers(*, accept: str = "text/html") -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": accept,
        }

    @staticmethod
    def _parse_balance_from_html(html: str) -> float | None:
        """Extract the USD balance from server-rendered HTML.

        Bytelixir renders balances as split-span dollar amounts::

            <span>$</span>0.04<span class="text-2xs">025</span>

        The integer+decimal part sits between two spans; the trailing
        precision digits are inside the next ``<span>``.  There are
        typically several instances (mobile + desktop + withdrawable).
        We return the first non-zero value found.
        """
        # Pattern: <span>$</span>DIGITS<span...>DIGITS</span>
        matches = re.findall(
            r"<span>\$</span>(\d+\.\d+)<span[^>]*>(\d*)</span>",
            html,
        )
        for main, extra in matches:
            try:
                val = float(main + extra)
                if val > 0:
                    return val
            except (ValueError, TypeError):
                continue

        # If all matched values are 0, return the first one
        if matches:
            try:
                return float(matches[0][0] + matches[0][1])
            except (ValueError, TypeError):
                pass

        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def collect(self) -> EarningsResult:
        """Fetch current Bytelixir earnings.

        Primary method: scrape the dashboard HTML for ``data-balance``.
        Fallback: ``/api/v1/user`` JSON endpoint.
        """
        try:
            async with self._make_client() as client:
                # --- 1. Try scraping the dashboard HTML ---------------
                # Use the root URL — when authenticated it redirects to
                # the localised dashboard (e.g. /en).  When not
                # authenticated it redirects to /login.
                html_resp = await client.get(
                    f"{API_BASE}/",
                    headers=self._browser_headers(),
                )

                # A 302 to /login means the session cookie is expired.
                if "login" in str(html_resp.url):
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error=("Session expired — refresh bytelixir_session cookie in Settings"),
                    )

                if html_resp.status_code == 200:
                    scraped = self._parse_balance_from_html(html_resp.text)
                    if scraped is not None:
                        logger.info(
                            "Bytelixir balance from HTML scrape: %s",
                            scraped,
                        )
                        return EarningsResult(
                            platform=self.platform,
                            balance=round(scraped, 4),
                            currency="USD",
                        )

                # --- 2. Fallback: JSON API ----------------------------
                api_resp = await client.get(
                    f"{API_BASE}/api/v1/user",
                    headers=self._browser_headers(accept="application/json")
                    | {
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": f"{API_BASE}/en",
                        "Origin": API_BASE,
                    },
                )

                if api_resp.status_code == 401:
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error=("Session expired — refresh bytelixir_session cookie in Settings"),
                    )

                api_resp.raise_for_status()
                data = api_resp.json()

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
