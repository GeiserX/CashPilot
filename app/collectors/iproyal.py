"""IPRoyal Pawns earnings collector.

Authenticates via email/password to get a JWT, then fetches the
current balance from the Pawns API.
"""

from __future__ import annotations

import logging
import secrets
import string

import httpx

from app.collectors import base
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
        super().__init__()
        self.email = email
        self.password = password
        self._device_id = _generate_identifier()
        self._token: str | None = None
        self._login_error = "Login failed — check email/password"

    async def _login(self, client: httpx.AsyncClient) -> str | None:
        """Login and return a JWT access token, or None on failure."""
        # Reset first: a message from an earlier login must never outlive it.
        self._login_error = "Login failed — check email/password"
        resp = await client.post(
            f"{API_BASE}/users/tokens",
            json={
                "identifier": self._device_id,
                "email": self.email,
                "password": self.password,
                "h_captcha_response": "",
            },
        )

        if resp.status_code == 422:
            try:
                code = (resp.json().get("error") or {}).get("code")
            except Exception:  # noqa: BLE001 - a body we cannot read is still a 422
                code = None
            if code == "user_disabled":
                # Pawns deactivated the account (a compliance review emails a
                # "deactivation notice"). The password is fine; only their
                # support can bring it back, so say that instead of "bad password".
                logger.error("IPRoyal: account disabled by Pawns")
                self._login_error = "Account disabled by Pawns — contact Pawns support (the password is fine)"
            else:
                logger.error("IPRoyal: bad credentials")
            return None
        if resp.status_code == 429:
            logger.warning("IPRoyal: rate limited on login")
            self._login_error = "Pawns rate-limited the login — it will retry on the next run"
            return None

        resp.raise_for_status()
        data = resp.json()
        return data.get("access_token")

    async def _fetch_balance(self, client: httpx.AsyncClient) -> httpx.Response:
        """Fetch balance dashboard (used as retry target)."""
        return await client.get(
            f"{API_BASE}/users/me/balance-dashboard",
            headers={"Authorization": f"Bearer {self._token}"},
        )

    async def collect(self) -> EarningsResult:
        """Fetch current IPRoyal Pawns balance."""
        try:
            client = self._get_client(timeout=30)

            if not self._token:
                self._token = await self._login(client)
            if not self._token:
                return EarningsResult(
                    platform=self.platform,
                    balance=0.0,
                    error=self._login_error,
                )

            resp = await self._retry(lambda: self._fetch_balance(client))

            if resp.status_code == 401:
                # Token expired, re-login once
                self._token = await self._login(client)
                if not self._token:
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error=self._login_error,
                    )
                resp = await self._retry(lambda: self._fetch_balance(client))

            resp.raise_for_status()
            data = resp.json()
            raw = data.get("balance")
            if raw is None:
                raise ValueError("balance field missing — API shape may have changed")
            balance = float(raw)

            return EarningsResult(
                platform=self.platform,
                balance=round(balance, 4),
                currency="USD",
            )
        except Exception as exc:
            base.log_failure(logger, "IPRoyal", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
