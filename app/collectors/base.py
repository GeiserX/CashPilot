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


class BaseCollector(abc.ABC):
    """Abstract base for platform-specific earnings collectors.

    Subclasses must set `platform` and implement `collect()`.
    """

    platform: str = ""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

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
