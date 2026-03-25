"""Base collector interface for CashPilot earnings collectors."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EarningsResult:
    """Result of a single collection attempt."""

    platform: str
    balance: float
    currency: str = "USD"
    bytes_uploaded: int = 0
    error: str | None = None


class BaseCollector:
    """Abstract base for platform-specific earnings collectors.

    Subclasses must set `platform` and implement `collect()`.
    """

    platform: str = ""

    async def collect(self) -> EarningsResult:
        raise NotImplementedError
