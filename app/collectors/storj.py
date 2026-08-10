"""Storj storagenode earnings collector.

Fetches estimated payout from the local storagenode API (port 14002).
No authentication required — the API is only accessible on localhost.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.collectors import base
from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "http://localhost:14002"

#: A zero-value Go time.Time — the node has NEVER been successfully pinged.
#: The Aug 2026 incident node carried this for four months while its dashboard
#: looked healthy: satellites were dialling a stale advertised IP the whole time.
_NEVER_PINGED_PREFIX = "0001-01-01"

#: Satellites ping the node on every contact cycle (well under an hour in
#: practice — a freshly fixed node was pinged within two minutes). Three hours
#: keeps maintenance pauses and satellite-side slowness from crying wolf while
#: still catching a real reachability loss the same day it starts.
_PINGED_STALE_AFTER = timedelta(hours=3)


def _parse_node_time(raw: Any) -> datetime | None:
    """A Go-marshalled timestamp as an aware datetime, or None (no claim).

    The node emits RFC 3339 with nanosecond fractions and either Z or a local
    offset; fromisoformat handles all observed forms. A naive result is read
    as UTC rather than discarded — Go only omits the offset for UTC.
    """
    try:
        parsed = datetime.fromisoformat(str(raw or ""))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class StorjCollector(BaseCollector):
    """Collect earnings from a Storj storagenode's local API."""

    platform = "storj"

    def __init__(self, api_url: str = DEFAULT_API_URL) -> None:
        super().__init__()
        self.api_url = api_url.rstrip("/")

    async def collect(self) -> EarningsResult:
        """Fetch current Storj storagenode estimated payout."""
        try:
            client = self._get_client(timeout=15)
            resp = await self._retry(lambda: client.get(f"{self.api_url}/api/sno/estimated-payout"))

            if resp.status_code == 404:
                # Older storagenode versions use different endpoint
                resp = await client.get(f"{self.api_url}/api/sno")

            resp.raise_for_status()
            data = resp.json()

            # estimated-payout endpoint returns cents
            if "currentMonth" in data:
                # Payout values are in cents (integer)
                # Absent keys are a SHAPE CHANGE, not zero earnings.
                #
                # Three .get(name, 0) defaults summed to a confident 0.00 when
                # storagenode renamed its payout sub-fields, and that zero was
                # recorded as a real balance. Because it is a DROP from the
                # previous reading, _detect_payout then asked the user to
                # confirm a payout of their entire balance that never happened
                # — and a confirmed payout is permanent.
                #
                # The ValueError below is unreachable once currentMonth exists,
                # so this branch has to do its own shape check.
                month = data["currentMonth"]
                known = [
                    k for k in ("egressBandwidthPayout", "egressRepairAuditPayout", "diskSpacePayout") if k in month
                ]
                if not known:
                    raise ValueError(
                        "storagenode currentMonth has no known payout field "
                        f"(saw: {sorted(month)[:6]}) — the API shape may have changed"
                    )
                payout_cents = sum(month.get(k, 0) for k in known)
                balance = payout_cents / 100.0
            elif "estimatedPayout" in data:
                balance = data["estimatedPayout"] / 100.0
            elif "currentMonthExpectations" in data:
                balance = data["currentMonthExpectations"] / 100.0
            else:
                raise ValueError("Unrecognized storagenode API response shape — no known payout field found")

            return EarningsResult(
                platform=self.platform,
                balance=round(balance, 4),
                currency="USD",
                # The balance can keep ticking (held amount, storage income)
                # while satellites cannot reach the node at all, so a healthy
                # collection is exactly when a reachability caveat is needed.
                warning=await self._reachability_warning(client),
            )
        except httpx.ConnectError:
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=(
                    "Storagenode API not reachable at "
                    f"{self.api_url} — if running in Docker, use "
                    "the node's LAN IP instead of localhost "
                    "(e.g. http://192.168.1.x:14002)"
                ),
            )
        except Exception as exc:
            base.log_failure(logger, "Storj", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )

    async def _reachability_warning(self, client: httpx.AsyncClient) -> str | None:
        """Can satellites actually reach this node? None is 'nothing to report'.

        The dashboard's /api/sno/ states it directly: ``lastPinged`` is the
        last time any satellite successfully dialled the node back, and
        ``quicStatus`` whether UDP 28967 got through. A node can be green in
        every other way — container healthy, balance moving — while both of
        these say the network cannot reach it (the Aug 2026 stale-ADDRESS
        incident ran ~40 failed dial-backs an hour for days, invisible).

        Every failure of this PROBE returns None: reachability is a bonus
        reading on top of a successful collection, and inventing a verdict
        from a probe that itself failed would be the same false confidence
        this exists to remove.
        """
        try:
            resp = await client.get(f"{self.api_url}/api/sno/")
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return None
        if not isinstance(data, dict):
            return None

        notes: list[str] = []
        raw_pinged = data.get("lastPinged")
        pinged_at = _parse_node_time(raw_pinged)
        if str(raw_pinged or "").startswith(_NEVER_PINGED_PREFIX):
            notes.append(
                "No satellite has EVER successfully reached this node — it is being "
                "counted offline. Check that the advertised ADDRESS matches your current "
                "public IP (prefer a DDNS hostname) and that port 28967 TCP+UDP is forwarded."
            )
        elif pinged_at is not None and datetime.now(UTC) - pinged_at > _PINGED_STALE_AFTER:
            hours = (datetime.now(UTC) - pinged_at).total_seconds() / 3600
            notes.append(
                f"No satellite has reached this node for {hours:.0f}h (last ping "
                f"{pinged_at.isoformat(timespec='seconds')}) — it is being counted offline. "
                "Check the advertised ADDRESS and that port 28967 TCP+UDP is forwarded."
            )
        # An absent or unparseable lastPinged is deliberately silent: this is a
        # bonus probe, and "cannot tell" must never read as "unreachable".

        # Only the one value we have SEEN mean broken. "Refreshing" appears
        # briefly at startup and warning on anything != OK would cry wolf.
        if data.get("quicStatus") == "Misconfigured":
            notes.append(
                "QUIC is misconfigured: UDP on port 28967 is not reaching the node. "
                "TCP transfers still work, but forward UDP 28967 too for full performance."
            )
        return " ".join(notes) or None
