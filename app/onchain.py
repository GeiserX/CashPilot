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

Each public explorer sees the address and the UI server's IP. The operator
can point a chain at their own node or disable the lookup. A known balance
may include a separate ``pending`` change. Private chains return
``unsupported`` with ``private`` set, without a network request.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
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
# An Ethereum JSON-RPC QUANTITY: a 0x-prefixed hex string, and nothing else.
_EVM_QUANTITY = re.compile(r"0x[0-9a-fA-F]+")
_BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_GENERATORS = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
_KASPA_GENERATORS = (0x98F2BC8E61, 0x79B76D99E2, 0xF33E5FB3C4, 0xAE2EABE2A8, 0x1E4F43E470)


@dataclass(frozen=True)
class Chain:
    """One supported chain and the keyless endpoint we read it from."""

    slug: str
    name: str
    symbol: str
    decimals: int
    rpc: str
    kind: str  # "evm", "solana", "esplora" or "kaspa"
    hrp: str | None = None
    b58_versions: tuple[int, ...] = ()

    @property
    def endpoint_variable(self) -> str:
        return f"CASHPILOT_ONCHAIN_URL_{self.slug.upper().replace('-', '_')}"


#: Only chains actually declared by a catalogued service. Adding an endpoint we
#: have no use for is a dependency on someone else's free infrastructure for no
#: benefit.
CHAINS: dict[str, Chain] = {
    "ethereum": Chain("ethereum", "Ethereum", "ETH", 18, "https://ethereum-rpc.publicnode.com", "evm"),
    "polygon": Chain("polygon", "Polygon", "POL", 18, "https://polygon-bor-rpc.publicnode.com", "evm"),
    "solana": Chain("solana", "Solana", "SOL", 9, "https://api.mainnet-beta.solana.com", "solana"),
    "bitcoin": Chain(
        "bitcoin", "Bitcoin", "BTC", 8, "https://mempool.space/api", "esplora", hrp="bc", b58_versions=(0x00, 0x05)
    ),
    "kaspa": Chain("kaspa", "Kaspa", "KAS", 8, "https://api.kaspa.org", "kaspa"),
}
PRIVATE_CHAINS = {
    "monero": ("XMR", "Reading a Monero balance needs a private view key. Check the balance in your wallet."),
}
KNOWN_SLUGS = CHAINS.keys() | PRIVATE_CHAINS.keys() | {"none", "base", "sia", "bittensor"}

# (chain, address, endpoint) -> (expires_at, result)
_cache: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
# Resolved endpoint -> time until which we do not retry it.
_backoff_until: dict[str, float] = {}
_host_sem: dict[str, asyncio.Semaphore] = {}


#: A ceiling so a long-lived process cannot grow the cache without bound even if
#: every entry is somehow live. Far above any real fleet's address count.
MAX_CACHE_ENTRIES = 512


def _now() -> float:
    return time.monotonic()


def _cache_get(key: tuple[str, str, str]) -> dict[str, Any] | None:
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


def _cache_put(key: tuple[str, str, str], value: dict[str, Any]) -> None:
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


def _polymod(values: list[int], shift: int, generators: tuple[int, ...]) -> int:
    checksum = 1
    for value in values:
        top = checksum >> shift
        checksum = ((checksum & ((1 << shift) - 1)) << 5) ^ value
        for bit, generator in enumerate(generators):
            if top & (1 << bit):
                checksum ^= generator
    return checksum


def _packed_length(groups: list[int]) -> int | None:
    """Number of bytes in the 5-bit groups if their trailing padding is valid."""
    size, padding = divmod(len(groups) * 5, 8)
    if padding >= 5 or groups[-1] & ((1 << padding) - 1):
        return None
    return size


def _bech32_ok(address: str, hrp: str) -> bool:
    # BIP 173 and 350 allow either case and use the last '1' as the separator.
    if not address.isascii() or len(address) > 90 or address.lower() != address and address.upper() != address:
        return False
    prefix, _, payload = address.lower().rpartition("1")
    if prefix != hrp or len(payload) < 8 or any(char not in _BASE32 for char in payload):
        return False
    values = [_BASE32.index(char) for char in payload]
    version, program = values[0], values[1:-6]
    size = _packed_length(program)
    if version > 16 or size is None or not 2 <= size <= 40 or (version == 0 and size not in (20, 32)):
        return False
    expanded = [ord(char) >> 5 for char in hrp] + [0] + [ord(char) & 31 for char in hrp]
    return _polymod(expanded + values, 25, _BECH32_GENERATORS) == (1 if version == 0 else 0x2BC830A3)


def _b58check_ok(address: str, versions: tuple[int, ...]) -> bool:
    if len(address) > 35 or any(char not in _BASE58 for char in address):
        return False
    value = 0
    for char in address:
        value = value * 58 + _BASE58.index(char)
    leading_zeroes = len(address) - len(address.lstrip("1"))
    decoded = bytes(leading_zeroes) + value.to_bytes((value.bit_length() + 7) // 8, "big")
    if len(decoded) != 25 or decoded[0] not in versions:
        return False
    return hashlib.sha256(hashlib.sha256(decoded[:-4]).digest()).digest()[:4] == decoded[-4:]


def _kaspa_ok(address: str) -> bool:
    prefix, _, payload = address.partition(":")
    if prefix != "kaspa" or len(payload) not in (61, 63) or any(char not in _BASE32 for char in payload):
        return False
    values = [_BASE32.index(char) for char in payload]
    # The first byte is the address version. ECDSA has a 33-byte key. A
    # Schnorr key or script hash takes 32 bytes.
    version = (values[0] << 3) | (values[1] >> 2)
    size = {0: 33, 1: 34, 8: 33}.get(version)
    if size is None or _packed_length(values[:-8]) != size:
        return False
    expanded = [ord(char) & 31 for char in prefix] + [0]
    return _polymod(expanded + values, 35, _KASPA_GENERATORS) == 1


def address_looks_valid(chain: str, address: str) -> bool:
    """Whether the address is well formed for the chain, before any request."""
    spec = CHAINS.get((chain or "").lower())
    if not spec or not address:
        return False
    text = address.strip()
    if spec.kind == "evm":
        return bool(_EVM_ADDRESS.fullmatch(text))
    if spec.kind == "esplora":
        return bool(spec.hrp and _bech32_ok(text, spec.hrp)) or _b58check_ok(text, spec.b58_versions)
    if spec.kind == "kaspa":
        return _kaspa_ok(text)
    return bool(_SOLANA_ADDRESS.fullmatch(text))


def endpoint(spec: Chain) -> tuple[httpx.URL | None, str | None]:
    variable = spec.endpoint_variable
    value = os.environ.get(variable, spec.rpc).strip()
    if not value:
        return None, f"Turned off by {variable}."
    invalid = f"{variable} must be an HTTP or HTTPS base URL without credentials, a query or a fragment."
    try:
        url = httpx.URL(value.rstrip("/"))
        host, port = url.host, url.port
    except (httpx.InvalidURL, ValueError):
        return None, invalid
    if (
        url.scheme not in {"http", "https"}
        or not host
        or (port is not None and not 1 <= port <= 65535)
        or url.userinfo
        or "?" in value
        or "#" in value
    ):
        return None, invalid
    return url, None


def _result(
    state: str,
    chain: str,
    *,
    amount: Decimal | None = None,
    pending: Decimal | None = None,
    source: str | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    spec = CHAINS.get(chain)
    private = PRIVATE_CHAINS.get(chain)
    return {
        "state": state,
        "chain": chain,
        "symbol": spec.symbol if spec else private[0] if private else None,
        "amount": amount if state == KNOWN else None,
        "pending": pending if state == KNOWN else None,
        "source": source,
        "private": private is not None,
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


async def _explorer_get(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    response = await client.get(url, follow_redirects=False)
    response.raise_for_status()
    if response.status_code != 200:
        raise ValueError("Unexpected explorer status")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Expected an explorer response object")
    return payload


def _utxo_delta(stats: Any) -> int:
    fields = ("funded_txo_count", "funded_txo_sum", "spent_txo_count", "spent_txo_sum")
    if not isinstance(stats, dict):
        raise ValueError("Missing Esplora statistics")
    values = [stats.get(field) for field in fields]
    if any(type(value) is not int or value < 0 for value in values):
        raise ValueError("Invalid Esplora count or sum")
    funded_count, funded, spent_count, spent = values
    if (funded_count == 0 and funded > 0) or (spent_count == 0 and spent > 0):
        raise ValueError("Esplora count and sum disagree")
    return funded - spent


async def _read(spec: Chain, address: str, url: str, client: httpx.AsyncClient) -> tuple[Decimal, Decimal | None]:
    """Parse a balance, refusing anything that is not exactly the documented shape.

    Being strict here is the whole point. A tolerant parser turns a malformed
    response into a CONFIDENT WRONG NUMBER, which this module reports as
    ``known`` — the one outcome worse than admitting we could not read the
    chain. Three ways that happened before this was tightened:

    * ``int(str(raw), 16)`` accepted the JSON *number* ``10`` and read it as
      hex, reporting 16 wei as fact.
    * ``isinstance(value, int)`` is True for ``True``, so a boolean became a
      balance of 1e-9 SOL.
    * nothing rejected a negative, so ``-5000000000`` rendered as -5 SOL.

    Every rejection raises, and the caller turns that into ``unreachable``.
    """
    if spec.kind == "esplora":
        payload = await _explorer_get(client, f"{url.rstrip('/')}/address/{address}")
        if "address" in payload and payload["address"] != address:
            raise ValueError("Esplora returned a different address")
        confirmed = _utxo_delta(payload.get("chain_stats"))
        if confirmed < 0:
            raise ValueError("Esplora confirmed spending exceeds funding")
        pending = _utxo_delta(payload.get("mempool_stats"))
        return _scale(confirmed, spec.decimals), _scale(pending, spec.decimals)

    if spec.kind == "kaspa":
        payload = await _explorer_get(client, f"{url.rstrip('/')}/addresses/{address}/balance")
        value = payload.get("balance")
        if payload.get("address") != address or type(value) is not int or value < 0:
            raise ValueError("Invalid Kaspa address or balance in response")
        return _scale(value, spec.decimals), None

    if spec.kind == "evm":
        raw = await _rpc(client, url, "eth_getBalance", [address, "latest"])
        # A hex STRING, not merely something str() can render.
        if not isinstance(raw, str) or not _EVM_QUANTITY.fullmatch(raw):
            raise ValueError(f"unexpected eth_getBalance result: {str(raw)[:120]}")
        return _scale(int(raw, 16), spec.decimals), None

    result = await _rpc(client, url, "getBalance", [address])
    # Solana nests the number under `value`; a bare int is a protocol change,
    # not something to accept quietly.
    if not isinstance(result, dict):
        raise ValueError(f"unexpected getBalance shape: {str(result)[:120]}")
    value = result.get("value")
    # `type(...) is not int` rather than isinstance: bool subclasses int.
    if type(value) is not int or value < 0:
        raise ValueError(f"unexpected getBalance value: {str(result)[:120]}")
    return _scale(value, spec.decimals), None


def _retry_delay(exc: Exception) -> int:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        header = exc.response.headers.get("Retry-After", "").strip()
        if header.isascii() and header.isdecimal():
            # Strip leading zeroes before capping long headers.
            digits = header.lstrip("0")
            return 900 if len(digits) > 3 else min(int(digits or "0"), 900)
    return BACKOFF


async def balance(chain: str, address: str, *, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """The balance at ``address`` on ``chain``, or an honest reason why not."""
    slug = (chain or "").lower()
    if private := PRIVATE_CHAINS.get(slug):
        return _result(UNSUPPORTED, slug, detail=private[1])
    spec = CHAINS.get(slug)
    if not spec:
        return _result(UNSUPPORTED, slug, detail="No keyless endpoint is configured for this chain.")
    url, why_not = endpoint(spec)
    if url is None:
        return _result(UNSUPPORTED, slug, detail=why_not)
    if not address_looks_valid(slug, address):
        return _result(INVALID, slug, detail="That address is not well formed for this chain.")

    address = address.strip()
    if spec.hrp and address.lower().startswith(f"{spec.hrp}1"):
        address = address.lower()
    resolved = str(url)
    key = (slug, address, resolved)
    if (cached := _cache_get(key)) is not None:
        return cached

    sem = _host_sem.setdefault(url.host, asyncio.Semaphore(2))
    async with sem:
        # A queued request may have filled the cache or hit a rate limit.
        if (cached := _cache_get(key)) is not None:
            return cached
        if _backoff_until.get(resolved, 0) > _now():
            return _result(UNREACHABLE, slug, detail="Backing off after a recent failure from this endpoint.")

        owns_client = client is None
        client = client or httpx.AsyncClient(timeout=TIMEOUT)
        try:
            amount, pending = await _read(spec, address, resolved, client)
        except Exception as exc:  # noqa: BLE001 - every failure means the balance is unknown
            until = _now() + _retry_delay(exc)
            _backoff_until[resolved] = max(_backoff_until.get(resolved, 0), until)
            error = type(exc).__name__
            logger.warning("Could not read %s balance: %s", slug, error)
            return _result(UNREACHABLE, slug, detail=f"{error} while reading the chain.")
        finally:
            if owns_client:
                await client.aclose()

        out = _result(KNOWN, slug, amount=amount, pending=pending, source=url.host)
        _cache_put(key, out)
        return out


async def balances(pairs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Read several addresses with one client and at most two requests per host."""
    if not pairs:
        return []
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        return list(await asyncio.gather(*(balance(c, a, client=client) for c, a in pairs)))


def reset_state() -> None:
    """Clear the cache and backoff. For tests, and for a config reload."""
    _cache.clear()
    _backoff_until.clear()
    _host_sem.clear()
