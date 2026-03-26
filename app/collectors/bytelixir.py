"""Bytelixir earnings collector.

Uses session cookie from the browser to fetch balance. Bytelixir is a
Laravel app with hCaptcha on login, so automated email/password login
is not possible. Users must extract session cookies from their browser.

To get the cookie: open dash.bytelixir.com, log in (tick "Remember Me"),
press F12 > Application > Cookies, and copy the `bytelixir_session` value.
"""

from __future__ import annotations

import logging
import re

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

DASH_BASE = "https://dash.bytelixir.com"


class BytelixirCollector(BaseCollector):
    """Collect earnings from Bytelixir using a session cookie."""

    platform = "bytelixir"

    def __init__(self, session_cookie: str) -> None:
        self.session_cookie = session_cookie

    async def collect(self) -> EarningsResult:
        """Fetch current Bytelixir balance."""
        try:
            cookies = {"bytelixir_session": self.session_cookie}
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json, text/html",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{DASH_BASE}/",
            }

            async with httpx.AsyncClient(timeout=30, follow_redirects=True, cookies=cookies) as client:
                # Try the JSON API first
                resp = await client.get(
                    f"{DASH_BASE}/api/v1/user",
                    headers=headers,
                )

                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        balance = _extract_balance(data)
                        if balance is not None:
                            return EarningsResult(
                                platform=self.platform,
                                balance=round(balance, 4),
                                currency="USD",
                            )
                    except Exception:
                        pass

                # Fallback: scrape the dashboard HTML for data-balance
                resp = await client.get(
                    f"{DASH_BASE}/en",
                    headers={**headers, "Accept": "text/html"},
                )

                if resp.status_code == 200:
                    balance = _extract_balance_from_html(resp.text)
                    if balance is not None:
                        return EarningsResult(
                            platform=self.platform,
                            balance=round(balance, 4),
                            currency="USD",
                        )

                # Check if session expired (redirected to login)
                if "/sign-in" in str(resp.url):
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error="Session expired — get a new bytelixir_session cookie from your browser",
                    )

                return EarningsResult(
                    platform=self.platform,
                    balance=0.0,
                    error="Could not extract balance from Bytelixir dashboard",
                )
        except Exception as exc:
            logger.error("Bytelixir collection failed: %s", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )


def _extract_balance(data: dict) -> float | None:
    """Try to extract a USD balance from JSON response."""
    for key in ("balance", "total_balance", "earnings", "total_earnings"):
        val = data.get(key)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                continue

    # Nested under 'data' or 'user'
    for wrapper in ("data", "user"):
        inner = data.get(wrapper, {})
        if isinstance(inner, dict):
            for key in ("balance", "total_balance", "earnings", "total_earnings"):
                val = inner.get(key)
                if val is not None:
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                        continue
    return None


def _extract_balance_from_html(html: str) -> float | None:
    """Extract balance from data-balance attribute in dashboard HTML."""
    match = re.search(r'data-balance=["\']([^"\']+)["\']', html)
    if match:
        try:
            return float(match.group(1))
        except (ValueError, TypeError):
            pass

    # Also try matching a balance-like number near "balance" text
    match = re.search(r"(?:balance|earnings)[^>]*>\s*\$?\s*([\d.]+)", html, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except (ValueError, TypeError):
            pass

    return None
