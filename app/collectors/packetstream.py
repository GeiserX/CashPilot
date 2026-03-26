"""PacketStream earnings collector.

Authenticates via JWT cookie and scrapes dashboard data from
the PacketStream web interface.
"""

from __future__ import annotations

import logging
import re

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://app.packetstream.io"


class PacketStreamCollector(BaseCollector):
    """Collect earnings from PacketStream's dashboard."""

    platform = "packetstream"

    def __init__(self, auth_token: str) -> None:
        self.auth_token = auth_token

    async def collect(self) -> EarningsResult:
        """Fetch current PacketStream balance by scraping dashboard."""
        try:
            cookies = {"auth": self.auth_token}

            async with httpx.AsyncClient(timeout=30, cookies=cookies) as client:
                resp = await client.get(f"{API_BASE}/dashboard")

                if resp.status_code in (401, 403) or "/login" in str(resp.url):
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error="Authentication failed — check auth JWT cookie",
                    )

                resp.raise_for_status()
                html = resp.text

                # Extract balance from window.userData in the HTML
                balance = 0.0
                match = re.search(
                    r"window\.userData\s*=\s*(\{[^}]+\})",
                    html,
                )
                if match:
                    import json

                    try:
                        user_data = json.loads(match.group(1))
                        balance = float(user_data.get("balance", 0))
                    except (json.JSONDecodeError, ValueError):
                        pass

                # Fallback: look for balance pattern
                if balance == 0.0:
                    match = re.search(r'"balance"\s*:\s*([\d.]+)', html)
                    if match:
                        balance = float(match.group(1))

                return EarningsResult(
                    platform=self.platform,
                    balance=round(balance, 4),
                    currency="USD",
                )
        except Exception as exc:
            logger.error("PacketStream collection failed: %s", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
