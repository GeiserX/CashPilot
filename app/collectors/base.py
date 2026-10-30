"""Base collector interface for CashPilot earnings collectors."""

from __future__ import annotations

import abc
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx

T = TypeVar("T")


@dataclass
class EarningsResult:
    """Result of a single collection attempt."""

    platform: str
    balance: float
    currency: str = "USD"
    error: str | None = None
    # A caveat about a reading that SUCCEEDED. `error` used to carry both, and
    # the collection loop stores a balance only when `error` is unset — so a
    # collector reporting a real figure with a note attached had that figure
    # silently discarded and the user was told the collector had failed.
    # Bytelixir's API fallback did exactly this: a valid withdrawable balance,
    # thrown away, reported as a failure.
    warning: str | None = None
    # WHAT KIND of failure `error` describes (CashPilot-5bdm). A 401 and a
    # timeout used to be the same free-text string, so the UI could only ever
    # say "collection failed" — teaching the user to ignore the one alert that
    # needs them (an expired credential earns $0 until a human acts; a provider
    # outage fixes itself). One of KIND_AUTH / KIND_TRANSIENT / KIND_SHAPE, or
    # None when the cause is genuinely unknown — never guess a kind: an
    # unknown labelled "transient" teaches the user to wait for something that
    # will not heal.
    error_kind: str | None = None
    # Device ids CashPilot deployed that the provider says are NOT on this
    # account, so they earn for nobody. None when the collector did not or
    # could not check; the collection loop turns a non-empty list into a notice.
    unlinked_devices: list[str] | None = None
    # Each node's own figures, for a provider read node by node (issue #488):
    # dicts with ``node``, ``balance`` (waiting to settle) and ``lifetime``. The
    # collection loop stores them and replaces ``balance`` with the total over
    # every node it knows. A balance that comes with these drops by itself when
    # a node settles, so it is never asked about as a payout.
    nodes: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        # An empty error is falsy, so the collection loop would store the 0.0
        # balance as a real reading and the credential test would say the
        # provider "accepted these credentials". A real httpx timeout has an
        # empty str(exc), so this happened on every timeout. A failure must
        # always carry text.
        if self.error is not None and not self.error.strip():
            self.error = "collection failed with no error message"


def describe_exception(exc: BaseException) -> str:
    """Error text for a caught exception that is never empty.

    ``str(exc)`` is "" for an httpx timeout, so the type name always leads.
    """
    text = str(exc).strip()
    name = type(exc).__name__
    return f"{name}: {text}" if text else name


#: The stored credential was REJECTED (401/403/login redirect). Only a human
#: pasting a fresh credential fixes this; every hour it stands is $0 collected.
KIND_AUTH = "auth"
#: Network trouble or the provider having a bad afternoon (timeout, 5xx).
#: Self-heals; the user should NOT be told to touch their credential.
KIND_TRANSIENT = "transient"
#: The provider changed its page/API shape. A code problem — the user can do
#: nothing except report it; their credential is (probably) fine.
KIND_SHAPE = "shape"
#: The login worked, but nothing could read the figure (a Mysterium node that
#: no CashPilot worker runs, issue #488). Not a credential problem, and not
#: an API change either.
KIND_UNREAD = "unread"


def classify_exception(exc: BaseException) -> str | None:
    """Best-effort failure kind for an exception a collector did not classify.

    Only claims what the exception type actually proves: transport errors and
    5xx are transient, 401/403 are auth. Everything else stays None -- absent
    is not transient, and a wrong "will self-heal" label is worse than none.
    """
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return KIND_TRANSIENT
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return KIND_AUTH
        if code >= 500:
            return KIND_TRANSIENT
    return None


class BaseCollector(abc.ABC):
    """Abstract base for platform-specific earnings collectors.

    Subclasses must set `platform` and implement `collect()`.
    """

    platform: str = ""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        # The device ids CashPilot deployed for this service, set by the
        # collection loop before each run for services with a catalog
        # `device_link` block. Empty means nothing to check.
        self.device_ids: set[str] = set()

    async def register_device(self, device_id: str, name: str) -> bool | None:
        """Add a deployed device to the account, where the provider's API allows it.

        True when the device is on the account afterwards, False when it is not,
        None when this provider has no way to do it (the user links it by hand).
        """
        return None

    def _get_client(self, **kwargs: Any) -> httpx.AsyncClient:
        """Return a reusable httpx client, creating one if needed."""
        if self._client is None or self._client.is_closed:
            defaults: dict[str, Any] = {"timeout": 30}
            defaults.update(kwargs)
            self._client = httpx.AsyncClient(**defaults)
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client. Safe to call multiple times."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _retry(
        self,
        coro_fn: Callable[[], Awaitable[T]],
        max_retries: int = 2,
        backoff: float = 1.0,
    ) -> T:
        """Retry a coroutine on transient network failures."""
        last_exc: BaseException | None = None
        for attempt in range(max_retries + 1):
            try:
                return await coro_fn()
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt < max_retries:
                    await asyncio.sleep(backoff * (2**attempt))
        raise last_exc  # type: ignore[misc]

    @abc.abstractmethod
    async def collect(self) -> EarningsResult:
        raise NotImplementedError


def log_failure(logger: Any, service_name: str, exc: BaseException) -> None:
    """Log a collector failure without writing the user's credential to the log.

    Every collector used to do this itself, as
    ``logger.error("X collection failed: %s", exc, exc_info=True)``. Both halves
    leak. Several providers are authenticated with a bare header value — Salad's
    auth cookie, Grass's access token, ProxyRack's API key, EarnApp's OAuth
    token, PacketStream's JWT — so when httpx rejects one, the exception TEXT is
    the credential, and ``exc_info`` then prints it again inside the chained
    httpcore/httpx traceback.

    That put a live credential in plaintext in ``docker logs cashpilot-ui``, and
    in whatever ships those logs off the box. Anyone in the ``docker`` group, or
    with read access to the log store, could take it — while the same string was
    being carefully redacted one layer up for the alert bell, which is what made
    the leak easy to miss.

    Routed through one helper so a new collector cannot reintroduce it by
    copying the idiom from its neighbours, which is exactly how it reached all
    fifteen of them.
    """
    from app import notify

    logger.error("%s collection failed: %s", service_name, notify.redact(str(exc)))
