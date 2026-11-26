"""What a hashrate should earn on average, from the network's own figures.

Only Bitcoin for now, read from the same Esplora/mempool endpoint as the
on-chain balance (``CASHPILOT_ONCHAIN_URL_BITCOIN``, default mempool.space), so
an operator who pointed Bitcoin at their own node or turned it off gets the same
here. The log redaction already masks that variable's value.

The result is an ESTIMATE, never money owed: it is the long-run average of a
random process (who finds the next block), before the pool's fee and luck. A
pool can credit less or more in any month, and a solo pool credits nothing in
most months.

Absent is not zero here either: an endpoint we could not read gives no
estimate, never an estimate of 0.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any

import httpx

from app import onchain

logger = logging.getLogger(__name__)

#: Difficulty changes every two weeks and the reward average spans a day of
#: blocks, so one read an hour is plenty and keeps us welcome on a free API.
CACHE_TTL = 3600
#: After a failure, wait this long before asking again.
BACKOFF = 600
TIMEOUT = 5.0
#: Blocks the average reward (subsidy plus fees) is taken over: about one day.
REWARD_BLOCKS = 144

KNOWN = "known"
UNREACHABLE = "unreachable"
UNSUPPORTED = "unsupported"

# endpoint -> (expires_at, result)
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_backoff_until: dict[str, float] = {}


def _now() -> float:
    return time.monotonic()


def _positive(value: Any) -> float | None:
    """A finite number above zero from a JSON number or numeric string, or None."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def expected_btc_per_day(hashrate_hs: float, difficulty: float, reward_btc_per_block: float) -> float:
    """The average BTC a hashrate earns in a day, before any pool fee.

    A hash finds a block with probability 1 / (difficulty x 2^32), so a
    hashrate of H finds H x 86400 / (D x 2^32) blocks a day on average.
    """
    return hashrate_hs * 86400 / (difficulty * 2**32) * reward_btc_per_block


async def _get_json(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    response = await client.get(url, follow_redirects=False)
    response.raise_for_status()
    if response.status_code != 200:
        raise ValueError("unexpected status")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("expected a JSON object")
    return payload


async def _read(base: str, client: httpx.AsyncClient) -> tuple[float, float]:
    hashrate = await _get_json(client, f"{base}/v1/mining/hashrate/3d")
    difficulty = _positive(hashrate.get("currentDifficulty"))
    rewards = await _get_json(client, f"{base}/v1/mining/reward-stats/{REWARD_BLOCKS}")
    total_sats = _positive(rewards.get("totalReward"))
    start, end = rewards.get("startBlock"), rewards.get("endBlock")
    if type(start) is not int or type(end) is not int or end < start:
        raise ValueError("reward stats carry no block range")
    if difficulty is None or total_sats is None:
        raise ValueError("no difficulty or reward in the answer")
    return difficulty, total_sats / (end - start + 1) / 1e8


async def bitcoin(*, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Bitcoin's current difficulty and average block reward, or why not."""
    url, why_not = onchain.endpoint(onchain.CHAINS["bitcoin"])
    if url is None:
        return {"state": UNSUPPORTED, "detail": why_not}
    base = str(url)
    hit = _cache.get(base)
    if hit and hit[0] > _now():
        return dict(hit[1])
    if _backoff_until.get(base, 0) > _now():
        return {"state": UNREACHABLE, "detail": "Backing off after a recent failure from this endpoint."}
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        difficulty, reward = await _read(base, client)
    except Exception as exc:  # noqa: BLE001 - every failure means no estimate
        _backoff_until[base] = _now() + BACKOFF
        # The type only: the text of an httpx error carries the URL.
        logger.warning("Could not read Bitcoin network stats: %s", type(exc).__name__)
        return {"state": UNREACHABLE, "detail": f"{type(exc).__name__} while reading the network stats."}
    finally:
        if owns_client:
            await client.aclose()
    out = {
        "state": KNOWN,
        "difficulty": difficulty,
        "reward_btc_per_block": reward,
        "reward_blocks": REWARD_BLOCKS,
        "source": url.host,
    }
    _cache[base] = (_now() + CACHE_TTL, out)
    return dict(out)


def reset_state() -> None:
    """Clear the cache and backoff. For tests."""
    _cache.clear()
    _backoff_until.clear()
