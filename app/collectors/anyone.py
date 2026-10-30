"""Anyone Protocol (formerly ATOR) earnings collector.

Reads the cumulative ANYONE reward of each relay fingerprint from the
relay-rewards contract's ``rewards`` view on Anyone's HyperBEAM node, and
reports it in native tokens (priced later, after the delta is taken).
"""

from __future__ import annotations

import logging

import httpx

from app.collectors import base
from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

# The relay-rewards process on the live node, as published in the runtime
# config of https://dashboard.anyone.io. Anyone spawns a new process on every
# contract redeploy, and the public edge routes only the current id, so a stale
# id answers 404 rather than serving old data. The legacy AO compute unit
# (cu.anyone.tech/dry-run) this collector used to call answers 404 for
# everything since the move to native HyperBEAM contracts.
#
# Reads are free, unauthenticated GETs:
# https://github.com/anyone-protocol/smart-contracts/blob/main/ao/docs/READING-THE-CONTRACTS.md
HYPERBEAM_URL = "https://hb.anyone.tech"
RELAY_REWARDS_PROCESS_ID = "pb-19qeB0qlobop3QHOCiR_rQLUR7phal0avuJQJLSs"
RELAY_API = "https://api.ec.anyone.tech"
TOKEN_DECIMALS = 18


class AnyoneCollector(BaseCollector):
    """Collect earnings from Anyone Protocol relays via the relay-rewards contract."""

    platform = "anyone-protocol"

    def __init__(self, fingerprints: str) -> None:
        super().__init__()
        self.fingerprints = [fp.strip() for fp in fingerprints.split(",") if fp.strip()]

    async def _get_rewards_for_fingerprint(self, client: httpx.AsyncClient, fingerprint: str) -> float:
        """Read one fingerprint's cumulative reward from the relay-rewards contract."""
        resp = await client.get(
            f"{HYPERBEAM_URL}/{RELAY_REWARDS_PROCESS_ID}~process@1.0/as/rewards",
            params={"fingerprint": fingerprint},
            timeout=60,
        )
        if resp.status_code == 404:
            # Not "no rewards": the view answers 200 for any fingerprint. A 404
            # means the node does not route this process id any more.
            raise RuntimeError(
                "Anyone relay-rewards process not found (404): the process id is stale "
                "or the node is down; check relayRewardsHyperbeamProcessId on dashboard.anyone.io"
            )
        resp.raise_for_status()
        result = resp.json()

        # The view echoes the requested fingerprint back. Without that echo this
        # is not the view's answer for this relay, and reading it would record a
        # fake real reading.
        if not isinstance(result, dict) or result.get("fingerprint") != fingerprint:
            raise ValueError(
                f"Anyone rewards response for {fingerprint} does not echo that fingerprint "
                f"(saw: {sorted(result)[:6] if isinstance(result, dict) else type(result).__name__}) "
                "— the contract shape may have changed"
            )
        # The contract omits `reward` for a relay that has never been rewarded.
        reward = result.get("reward")
        if reward in (None, ""):
            return 0.0

        try:
            raw_tokens = int(reward)
        except (ValueError, TypeError):
            raise ValueError(f"unexpected reward format: {reward!r}")
        return raw_tokens / (10**TOKEN_DECIMALS)

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

            # Report the NATIVE token count, never a USD conversion of it.
            #
            # balance here is CUMULATIVE lifetime rewards, and earnings are the
            # delta between two readings. Converting the cumulative figure first
            # meant a token price move fabricated earnings out of nothing: the
            # same 1000 ANYONE read at $0.10 and then at $0.12 produced $20 of
            # "earned today" without a single token being paid out.
            #
            # get_daily_earnings takes the delta in the native currency and only
            # then prices it, which is the whole reason that code is written
            # that way. Handing it USD defeated it for this one service.
            #
            # Safe to change mid-history: the delta is only computed when the
            # stored currency matches the previous reading (database.py), so the
            # USD-to-ANYONE switchover is skipped rather than counted as a gain.
            return EarningsResult(
                platform=self.platform,
                balance=round(total_tokens, 6),
                currency="ANYONE",
            )
        except Exception as exc:
            base.log_failure(logger, "Anyone Protocol", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=base.describe_exception(exc),
            )
