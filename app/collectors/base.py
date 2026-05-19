"""Base collector interface for CashPilot earnings collectors."""

from __future__ import annotations

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


class BaseCollector:
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

    async def collect(self) -> EarningsResult:
        raise NotImplementedError
