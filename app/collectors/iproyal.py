"""IPRoyal Pawns earnings collector.

Authenticates via email/password to get a JWT, then fetches the
current balance from the Pawns API.
"""

from __future__ import annotations

import logging
import secrets
import string

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://api.pawns.app/api/v1"


def _generate_identifier(length: int = 21) -> str:
    """Generate a random alphanumeric identifier for the login request."""
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


class IPRoyalCollector(BaseCollector):
    """Collect earnings from IPRoyal Pawns API."""

    platform = "iproyal"

    def __init__(self, email: str, password: str) -> None:
        self.email = email
        self.password = password

    async def _login(self, client: httpx.AsyncClient) -> str | None:
        """Login and return a JWT access token, or None on failure."""
        resp = await client.post(
            f"{API_BASE}/users/tokens",
            json={
                "identifier": _generate_identifier(),
                "email": self.email,
                "password": self.password,
                "h_captcha_response": "",
            },
        )

        if resp.status_code == 422:
            logger.error("IPRoyal: bad credentials")
            return None
        if resp.status_code == 429:
            logger.warning("IPRoyal: rate limited on login")
            return None

        resp.raise_for_status()
        data = resp.json()
        return data.get("access_token")

    async def collect(self) -> EarningsResult:
        """Fetch current IPRoyal Pawns balance."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                token = await self._login(client)
                if not token:
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error="Login failed — check email/password",
                    )

                resp = await client.get(
                    f"{API_BASE}/users/me/balance-dashboard",
                    headers={"Authorization": f"Bearer {token}"},
                )

                if resp.status_code == 401:
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error="Authentication expired",
                    )

                resp.raise_for_status()
                data = resp.json()
                balance = float(data.get("balance", 0))

                return EarningsResult(
                    platform=self.platform,
                    balance=round(balance, 4),
                    currency="USD",
                )
        except Exception as exc:
            logger.error("IPRoyal collection failed: %s", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
