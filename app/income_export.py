"""Income rows and the CSV download format."""

from __future__ import annotations

import csv
import math
from bisect import bisect_right
from collections.abc import AsyncIterator
from contextlib import aclosing
from io import StringIO

from app import catalog, database

HEADER = (
    "date",
    "period_start",
    "kind",
    "service",
    "coin",
    "amount",
    "usd_rate",
    "usd_value",
    "local_currency",
    "local_rate",
    "local_value",
    "method",
)
_CHUNK_ROWS = 500


def csv_safe(text: str) -> str:
    # Some spreadsheet importers trim whitespace or accept full-width operators.
    if text.startswith(("\t", "\r", "\n")) or text.lstrip().startswith(("=", "+", "-", "@", "＝", "＋", "－", "＠")):
        return "'" + text
    return text


def fmt(value: float | None, places: int) -> str:
    if value is None or not math.isfinite(value):
        return ""
    return f"{value:.{places}f}".rstrip("0").rstrip(".")


def rate_on(days: list[str], rates: dict[str, float], day: str) -> float | None:
    index = bisect_right(days, day) - 1
    return rates[days[index]] if index >= 0 else None


def kind_for(slug: str) -> str:
    collector = (catalog.get_service(slug) or {}).get("collector") or {}
    return "accrued" if collector.get("accrual") == "pool" else "earned"


def _row(
    day: str,
    period_start: str,
    kind: str,
    service: str,
    coin: str,
    amount: float,
    usd_rate: float | None,
    local_currency: str,
    local_rate: float | None,
    method: str = "",
) -> tuple[str, ...]:
    usd_value = amount * usd_rate if usd_rate is not None else None
    local_value = usd_value * local_rate if usd_value is not None and local_rate is not None else None
    return (
        day,
        period_start,
        kind,
        csv_safe(service),
        csv_safe(coin),
        fmt(amount, 12),
        fmt(usd_rate, 12),
        fmt(usd_value, 8),
        csv_safe(local_currency),
        fmt(local_rate, 12),
        fmt(local_value, 8),
        csv_safe(method),
    )


async def iter_rows(start: str, end: str, currency: str, fiat: dict[str, float]) -> AsyncIterator[tuple[str, ...]]:
    days = sorted(fiat)
    async with aclosing(database.iter_earned_steps(end)) as steps:
        async for step in steps:
            if step.date >= start:
                yield _row(
                    step.date,
                    step.since,
                    kind_for(step.platform),
                    step.platform,
                    step.currency,
                    step.amount,
                    step.rate,
                    currency,
                    rate_on(days, fiat, step.date),
                )

    for payout in reversed(await database.get_payouts(confirmed_only=True)):
        day = payout["detected_at"][:10]
        if start <= day <= end:
            yield _row(
                day,
                "",
                "payout",
                payout["platform"],
                payout["currency"],
                max(0.0, payout["amount"]),
                database._usd_rate(payout["currency"], payout["fx_rate_usd"]),
                currency,
                rate_on(days, fiat, day),
                payout["method"],
            )


async def stream_csv(start: str, end: str, currency: str, fiat: dict[str, float]) -> AsyncIterator[str]:
    with StringIO() as buffer:
        writer = csv.writer(buffer)
        writer.writerow(HEADER)
        count = 0
        async with aclosing(iter_rows(start, end, currency, fiat)) as rows:
            async for row in rows:
                writer.writerow(row)
                count += 1
                if count == _CHUNK_ROWS:
                    yield buffer.getvalue()
                    buffer.seek(0)
                    buffer.truncate()
                    count = 0
        if buffer.tell():
            yield buffer.getvalue()
