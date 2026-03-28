"""Grass earnings collector.

Uses the Grass API with an access token (from browser localStorage) to
fetch earnings points.

During an active epoch, the /retrieveUser endpoint returns totalPoints=0
because points are "estimated" and only settle after the epoch ends.
The Grass dashboard calculates estimated points client-side from device
uptime data. This collector replicates that calculation:

  estimated_points = sum(
      (device.totalUptime / 3600) * 50 * (device.ipScore / 100) * device.multiplier
      for each device
  )

Formula: 50 base points per hour, scaled by network score and multiplier.

If totalPoints > 0 (settled epoch), that value is used instead.

To get the token: open app.grass.io, log in, press F12, go to
Application > Local Storage, and copy the `accessToken` value.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.collectors.base import BaseCollector, EarningsResult

logger = logging.getLogger(__name__)

API_BASE = "https://api.getgrass.io"

# Base earning rate: 50 points per hour of uptime
_BASE_POINTS_PER_HOUR = 50


class GrassCollector(BaseCollector):
    """Collect earnings from Grass's API using an access token."""

    platform = "grass"

    def __init__(self, access_token: str) -> None:
        self.access_token = access_token

    def _make_headers(self) -> dict[str, str]:
        return {
            "Authorization": self.access_token,
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://app.grass.io",
            "Referer": "https://app.grass.io/",
            "User-Agent": "Mozilla/5.0",
        }

    async def _request_with_retry(self, client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
        """Make a request with retry on 429 (Cloudflare rate limit)."""
        max_retries = 3
        for attempt in range(max_retries + 1):
            resp = await client.get(url, headers=self._make_headers(), **kwargs)
            if resp.status_code != 429:
                return resp
            retry_after = int(resp.headers.get("Retry-After", 30))
            # Cap wait at 60s per attempt to avoid extremely long waits
            wait = min(retry_after, 60)
            logger.info("Grass API 429, retry %d/%d in %ds", attempt + 1, max_retries, wait)
            if attempt < max_retries:
                await asyncio.sleep(wait)
        return resp  # Return last 429 response if all retries exhausted

    async def _get_settled_points(self, client: httpx.AsyncClient) -> float:
        """Fetch totalPoints from /retrieveUser (non-zero only after epoch settles)."""
        resp = await self._request_with_retry(client, f"{API_BASE}/retrieveUser")

        if resp.status_code in (401, 403):
            return -1.0  # Signal auth failure

        if resp.status_code == 429:
            logger.warning("Grass API still rate-limited after retries")
            return -2.0  # Signal rate limit

        resp.raise_for_status()
        data = resp.json()
        user = data.get("result", {}).get("data", {})
        return float(user.get("totalPoints", 0))

    async def _estimate_from_devices(self, client: httpx.AsyncClient) -> float:
        """Estimate current epoch points from per-device uptime data.

        Fetches GET /devices and calculates:
          hours * 50 * (ipScore / 100) * multiplier
        for each device, summed.
        """
        resp = await self._request_with_retry(client, f"{API_BASE}/devices", params={"input": "{}"})
        if resp.status_code == 429:
            logger.warning("Grass /devices still rate-limited after retries")
            return -1.0
        resp.raise_for_status()
        data = resp.json()

        devices = data.get("result", {}).get("data", [])
        if not devices:
            logger.debug("Grass /devices returned no devices")
            return 0.0

        total_estimated = 0.0
        for device in devices:
            # totalUptime is in seconds; fall back to 0 if missing
            uptime_seconds = float(device.get("totalUptime", 0))
            ip_score = float(device.get("ipScore", 0))
            multiplier = float(device.get("multiplier", 1))

            if uptime_seconds <= 0 or ip_score <= 0:
                continue

            hours = uptime_seconds / 3600
            points = hours * _BASE_POINTS_PER_HOUR * (ip_score / 100) * multiplier
            total_estimated += points

            logger.debug(
                "Grass device %s: %.1fh uptime, score=%s%%, mult=%s -> %.2f pts",
                device.get("ipAddress", "unknown"),
                hours,
                ip_score,
                multiplier,
                points,
            )

        logger.info(
            "Grass estimated %.2f points from %d device(s)",
            total_estimated,
            len(devices),
        )
        return total_estimated

    async def collect(self) -> EarningsResult:
        """Fetch current Grass points.

        Strategy:
        1. Check /retrieveUser for settled totalPoints.
        2. If totalPoints > 0, use it (epoch has settled).
        3. Otherwise, estimate from /devices uptime data.
        """
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                # First, check if we have settled points
                settled = await self._get_settled_points(client)

                if settled == -1.0:
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error="Token expired — get a new accessToken from app.grass.io Local Storage",
                    )

                if settled == -2.0:
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error="Cloudflare rate limit — will retry next collection cycle",
                    )

                if settled > 0:
                    # Epoch has settled, use the official total
                    return EarningsResult(
                        platform=self.platform,
                        balance=round(settled, 4),
                        currency="GRASS",
                    )

                # Active epoch: estimate from device uptime
                estimated = await self._estimate_from_devices(client)

                if estimated == -1.0:
                    return EarningsResult(
                        platform=self.platform,
                        balance=0.0,
                        error="Cloudflare rate limit — will retry next collection cycle",
                    )

                return EarningsResult(
                    platform=self.platform,
                    balance=round(estimated, 4),
                    currency="GRASS",
                )
        except Exception as exc:
            logger.error("Grass collection failed: %s", exc)
            return EarningsResult(
                platform=self.platform,
                balance=0.0,
                error=str(exc),
            )
