"""Traffmonetizer earnings collector.

Traffmonetizer enforces reCAPTCHA on their login endpoint, making
programmatic email/password authentication impossible. Users must
extract a token from their browser session.

To get the token: open app.traffmonetizer.io, log in, press F12,
go to Application > Local Storage > https://app.traffmonetizer.io,
and copy the `authToken` value. It expires after some days, with no fixed
lifetime (one lasted about 12), and a rejected token is reported as such.
"""

from __future__ import annotations

import logging

import httpx  # noqa: F401 (used by test patches targeting this module)

from app.collectors import base
from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://data.traffmonetizer.io/api"


class TraffmonetizerCollector(BaseCollector):
    """Collect earnings from Traffmonetizer's API using a browser session token."""

    platform = "traffmonetizer"

    def __init__(self, token: str = "") -> None:
        super().__init__()
        self._token = token.strip()

    async def collect(self) -> EarningsResult:
        """Fetch current Traffmonetizer balance."""
        if not self._token:
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error="No token configured — copy authToken from browser Local Storage",
            )

        try:
            client = self._get_client(timeout=30)
            headers = {
                "Authorization": f"Bearer {self._token}",
                "Origin": "https://app.traffmonetizer.io",
                "Referer": "https://app.traffmonetizer.io/",
            }

            resp = await self._retry(
                lambda: client.get(
                    f"{API_BASE}/app_user/get_balance",
                    headers=headers,
                )
            )

            if resp.status_code in (401, 403):
                return EarningsResult(
                    platform=self.platform,
                    balance=0.0,
                    error="Token rejected, so it has expired or was revoked — copy a fresh authToken from browser Local Storage",
                    error_kind=base.KIND_AUTH,
                )

            resp.raise_for_status()
            data = resp.json()

            raw = data.get("data", {}).get("balance")
            if raw is None:
                raise ValueError("balance field missing — API shape may have changed")
            balance = float(raw)

            return EarningsResult(
                platform=self.platform,
                balance=round(balance, 4),
                currency="USD",
            )
        except Exception as exc:
            base.log_failure(logger, "Traffmonetizer", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=base.describe_exception(exc),
            )
