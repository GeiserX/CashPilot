"""Anyone Protocol (formerly ATOR) earnings collector.

Queries the relay-rewards AO smart contract via dry-run to get
accumulated ANYONE token rewards per relay fingerprint, then converts
to USD via CoinGecko.
"""

from __future__ import annotations

import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

RELAY_REWARDS_PROCESS_ID = "QZJTY63XZtHOHo_qPaEX7VdtemZh4rpj821xcanPGXA"
AO_CU_URL = "https://cu.anyone.tech"
RELAY_API = "https://api.ec.anyone.tech"
COINGECKO_ID = "airtor-protocol"
TOKEN_DECIMALS = 18


class AnyoneCollector(BaseCollector):
    """Collect earnings from Anyone Protocol relays via AO dry-run."""

    platform = "anyone-protocol"

    def __init__(self, fingerprints: str) -> None:
        super().__init__()
        self.fingerprints = [fp.strip() for fp in fingerprints.split(",") if fp.strip()]

    async def _get_rewards_for_fingerprint(self, client: httpx.AsyncClient, fingerprint: str) -> float:
        """Query AO relay-rewards contract for a single fingerprint's total reward."""
        payload = {
            "Id": "1234",
            "Target": RELAY_REWARDS_PROCESS_ID,
            "Owner": "1234",
            "Anchor": "0",
            "Tags": [
                {"name": "Action", "value": "Get-Rewards"},
                {"name": "Fingerprint", "value": fingerprint},
                {"name": "Address", "value": "0x0000000000000000000000000000000000000000"},
                {"name": "Data-Protocol", "value": "ao"},
                {"name": "Type", "value": "Message"},
                {"name": "Variant", "value": "ao.TN.1"},
            ],
            "Data": "1234",
        }
        resp = await client.post(
            f"{AO_CU_URL}/dry-run",
            params={"process-id": RELAY_REWARDS_PROCESS_ID},
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()

        if "error" in result:
            raise RuntimeError(f"AO CU error: {result['error']}")

        messages = result.get("Messages", [])
        if not messages:
            logger.debug("No messages returned for fingerprint %s", fingerprint)
            return 0.0

        data = messages[0].get("Data", "0")
        if not data or data == "null":
            return 0.0

        try:
            raw_tokens = int(data)
        except (ValueError, TypeError):
            raise ValueError(f"unexpected reward format: {data!r}")
        return raw_tokens / (10**TOKEN_DECIMALS)

    async def _get_token_price(self, client: httpx.AsyncClient) -> float:
        """Fetch ANYONE token price in USD from CoinGecko."""
        resp = await client.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": COINGECKO_ID, "vs_currencies": "usd"},
        )
        resp.raise_for_status()
        data = resp.json()
        return float(data.get(COINGECKO_ID, {}).get("usd", 0))

    async def collect(self) -> EarningsResult:
        """Fetch total Anyone Protocol relay rewards and convert to USD."""
        if not self.fingerprints:
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error="No fingerprints configured",
            )

        try:
            client = self._get_client(timeout=30)
            total_tokens = 0.0

            for fp in self.fingerprints:
                tokens = await self._retry(lambda fp=fp: self._get_rewards_for_fingerprint(client, fp))
                total_tokens += tokens
                logger.debug("Fingerprint %s: %.6f ANYONE", fp, tokens)

            if total_tokens <= 0:
                return EarningsResult(
                    platform=self.platform,
                    balance=0.0,
                    currency="ANYONE",
                )

            price = await self._retry(lambda: self._get_token_price(client))
            if price <= 0:
                return EarningsResult(
                    platform=self.platform,
                    balance=round(total_tokens, 6),
                    currency="ANYONE",
                )

            usd_value = total_tokens * price
            return EarningsResult(
                platform=self.platform,
                balance=round(usd_value, 2),
                currency="USD",
            )
        except Exception as exc:
            logger.error("Anyone Protocol collection failed: %s", exc, exc_info=True)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
