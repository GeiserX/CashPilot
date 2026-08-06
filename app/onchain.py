"""Read-only on-chain balances (CashPilot-dv6, tier 2).

Once tier 1 knows WHERE a service pays, this reads what actually arrived. It
handles no private key, constructs no transaction and signs nothing — the only
operation is "what is the balance at this public address?".

THE RULE THIS MODULE EXISTS TO ENFORCE, and it is the same rule as everywhere
else in this codebase: **absent is not zero**. A chain we could not reach must
never render as a balance of 0. Zero is a fact about an address; unreachable is
a fact about us. Showing the second as the first tells a user their money is
gone when the truth is that a public RPC rate-limited us.

So every read returns a STATE, never a bare number:

    known          we asked and got an answer. ``amount`` is real, 0 included.
    unreachable    the RPC failed, timed out, or answered nonsense.
    unsupported    we have no endpoint for that chain.
    invalid        the address is not well formed for that chain, so we did
                   not ask at all. Never send a malformed address to a public
                   endpoint just to see what happens.

Public RPCs are a courtesy, not an entitlement. Results are cached and a failing
endpoint is backed off, because a dashboard that polls hard gets blocked — and a
blocked endpoint degrades every user of this feature, not just the impatient one.

No API keys. Every endpoint here is keyless by choice; a chain that needs a key
stays ``unsupported`` until the user supplies one, and a shared key is never
shipped.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

logger = logging.getLogger(__name__)

#: How long a successful read is reused. Balances move slowly relative to a
#: dashboard refresh, and this is the main thing keeping us welcome on a free RPC.
CACHE_TTL = 300

#: After a failure, do not retry that endpoint for this long. Hammering an RPC
#: that just rate-limited us is how the block becomes permanent.
BACKOFF = 120

#: Deliberately short. A slow chain must not hold up a page render; the caller
#: gets "unreachable" and the UI says so.
TIMEOUT = 8.0

KNOWN = "known"
UNREACHABLE = "unreachable"
UNSUPPORTED = "unsupported"
INVALID = "invalid"

_EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
# Base58 excludes 0, O, I and l precisely so they cannot be confused visually.
_SOLANA_ADDRESS = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


@dataclass(frozen=True)
class Chain:
    """One supported chain and the keyless endpoint we read it from."""

    slug: str
    name: str
    symbol: str
    decimals: int
    rpc: str
    kind: str  # "evm" or "solana"


#: Only chains actually declared by a catalogued service. Adding an endpoint we
#: have no use for is a dependency on someone else's free infrastructure for no
#: benefit.
CHAINS: dict[str, Chain] = {
    "ethereum": Chain("ethereum", "Ethereum", "ETH", 18, "https://ethereum-rpc.publicnode.com", "evm"),
    "polygon": Chain("polygon", "Polygon", "POL", 18, "https://polygon-bor-rpc.publicnode.com", "evm"),
    "solana": Chain("solana", "Solana", "SOL", 9, "https://api.mainnet-beta.solana.com", "solana"),
}

# slug -> (expires_at, result)
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
# rpc url -> time until which we do not retry it
_backoff_until: dict[str, float] = {}


#: A ceiling so a long-lived process cannot grow the cache without bound even if
#: every entry is somehow live. Far above any real fleet's address count.
MAX_CACHE_ENTRIES = 512


def _now() -> float:
    return time.monotonic()


def _cache_get(key: str) -> dict[str, Any] | None:
    """A COPY of the cached result, or None.

    Returning the stored dict itself would let any caller that mutates what it
    got corrupt every later read — and this module's entire contract is that
    ``amount`` is None unless ``state`` is ``known``, so a mutated cache entry
    is exactly the lie the module exists to prevent.
    """
    hit = _cache.get(key)
    if hit and hit[0] > _now():
        return dict(hit[1])
    return None


def _cache_put(key: str, value: dict[str, Any]) -> None:
    now = _now()
    # Expired entries are only ever noticed on read, so without this sweep they
    # accumulate for the life of the process: one entry per address ever asked
    # about, never released.
    for k in [k for k, (expires, _) in _cache.items() if expires <= now]:
        del _cache[k]
    # Evict DOWN TO the ceiling, not by one. Dropping a single entry leaves an
    # over-full cache over-full forever, which is how a "capped" cache quietly
    # is not one.
    if len(_cache) >= MAX_CACHE_ENTRIES:
        by_expiry = sorted(_cache, key=lambda k: _cache[k][0])
        for k in by_expiry[: len(_cache) - MAX_CACHE_ENTRIES + 1]:
            del _cache[k]
    _cache[key] = (now + CACHE_TTL, dict(value))


def address_looks_valid(chain: str, address: str) -> bool:
    """Whether ``address`` is well formed for ``chain``.

    Checked BEFORE any network call. This is not a claim that the address
    exists — only that asking about it is meaningful.
    """
    spec = CHAINS.get((chain or "").lower())
    if not spec or not address:
        return False
    if spec.kind == "evm":
        return bool(_EVM_ADDRESS.match(address.strip()))
    return bool(_SOLANA_ADDRESS.match(address.strip()))


def _result(state: str, chain: str, *, amount: Decimal | None = None, detail: str | None = None) -> dict[str, Any]:
    spec = CHAINS.get(chain)
    return {
        "state": state,
        "chain": chain,
        "symbol": spec.symbol if spec else None,
        # None, never 0.0, for every state except `known`. A caller that
        # formats this without checking `state` will render an em dash, not a
        # figure — which is the failure mode we want.
        "amount": amount if state == KNOWN else None,
        "detail": detail,
    }


def _scale(raw: int, decimals: int) -> Decimal:
    """Integer base units -> a decimal amount, exactly.

    Decimal rather than float: 18 decimals of wei does not survive a float, and
    a balance that is wrong in the last places is a balance nobody trusts.
    """
    return Decimal(raw) / (Decimal(10) ** decimals)


async def _rpc(client: httpx.AsyncClient, url: str, method: str, params: list[Any]) -> Any:
    response = await client.post(
        url,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        headers={"content-type": "application/json"},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or "error" in payload:
        raise ValueError(f"RPC error: {str(payload)[:200]}")
    if "result" not in payload:
        raise ValueError("RPC response carried no result")
    return payload["result"]


async def _read(spec: Chain, address: str, client: httpx.AsyncClient) -> Decimal:
    if spec.kind == "evm":
        raw = await _rpc(client, spec.rpc, "eth_getBalance", [address, "latest"])
        return _scale(int(str(raw), 16), spec.decimals)
    result = await _rpc(client, spec.rpc, "getBalance", [address])
    # Solana nests the number under `value`; a bare int would be a protocol change.
    value = result.get("value") if isinstance(result, dict) else result
    if not isinstance(value, int):
        raise ValueError(f"unexpected getBalance shape: {str(result)[:120]}")
    return _scale(value, spec.decimals)


async def balance(chain: str, address: str, *, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """The balance at ``address`` on ``chain``, or an honest reason why not."""
    slug = (chain or "").lower()
    spec = CHAINS.get(slug)
    if not spec:
        return _result(UNSUPPORTED, slug, detail="No keyless endpoint is configured for this chain.")
    if not address_looks_valid(slug, address):
        return _result(INVALID, slug, detail="That address is not well formed for this chain.")

    address = address.strip()
    key = f"{slug}:{address}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    if _backoff_until.get(spec.rpc, 0) > _now():
        # Deliberately NOT cached: the moment backoff expires we should try again.
        return _result(UNREACHABLE, slug, detail="Backing off after a recent failure from this endpoint.")

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        amount = await _read(spec, address, client)
    except Exception as exc:  # noqa: BLE001 - every failure is the same answer: we do not know
        _backoff_until[spec.rpc] = _now() + BACKOFF
        logger.warning("Could not read %s balance for %s: %s", slug, address[:10] + "...", exc)
        return _result(UNREACHABLE, slug, detail=f"{type(exc).__name__} while reading the chain.")
    finally:
        if owns_client:
            await client.aclose()

    out = _result(KNOWN, slug, amount=amount)
    _cache_put(key, out)
    return out


async def balances(pairs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Read several addresses, sharing one client.

    Runs concurrently because the chains are independent, but note the per-chain
    backoff is shared state: one failing endpoint stops the others queueing
    behind it rather than each waiting out its own timeout.
    """
    if not pairs:
        return []
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        return list(await asyncio.gather(*(balance(c, a, client=client) for c, a in pairs)))


def reset_state() -> None:
    """Clear the cache and backoff. For tests, and for a config reload."""
    _cache.clear()
    _backoff_until.clear()
