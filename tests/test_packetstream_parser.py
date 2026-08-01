"""PacketStream dashboard parsing.

The balance is scraped from server-rendered HTML, so a layout change silently
zeroes the collector. It has already happened twice: the heading moved from
<h3>Balance</h3> to <h2 class=metric-title>Balance</h2>, and window.userData
disappeared. These tests pin the shapes we have actually seen in the wild.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.collectors.base import EarningsResult
from app.collectors.packetstream import PacketStreamCollector

# Captured from the live dashboard: minified, attributes unquoted, and the
# referral strip further down also contains a $ amount that must NOT be picked.
LIVE_HTML = (
    '<div class="card metric-card metric-card-balance"><h2 class=metric-title>Balance</h2>'
    '<p class="card-subtitle mb-4 text-muted">Available Funds'
    '<h2 class="default-font fw-600">$2.12</h2></div>'
    '<div class="card metric-card metric-card-sold"><h2 class=metric-title>Sold</h2></div>'
    "<div class=referral-strip-earned><p class=referral-strip-label>Earned to date"
    "<p class=referral-strip-value>$0.00</div>"
)


def _collect(html: str) -> EarningsResult:
    resp = MagicMock()
    resp.status_code = 200
    resp.url = "https://app.packetstream.io/dashboard"
    resp.text = html
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.__aenter__ = MagicMock(return_value=client)

    async def _get(*a, **k):
        return resp

    client.get = _get
    with patch("app.collectors.packetstream.httpx.AsyncClient", return_value=client):
        return asyncio.run(PacketStreamCollector(auth_token="jwt").collect())


class TestPacketStreamBalanceParsing:
    def test_current_layout(self):
        r = _collect(LIVE_HTML)
        assert r.error is None, r.error
        assert r.balance == 2.12, "must read the Balance card, not the referral strip"

    def test_does_not_grab_the_referral_amount(self):
        # Referral strip first in the document; the balance card still wins.
        html = "<div class=referral-strip-earned><p class=referral-strip-value>$99.99</div>" + LIVE_HTML
        assert _collect(html).balance == 2.12

    def test_thousands_separator(self):
        html = LIVE_HTML.replace("$2.12", "$1,234.56")
        assert _collect(html).balance == 1234.56

    def test_previous_layout_still_parses(self):
        # Older card: <h3>Balance</h3> ... <h2>$0.13</h2>
        assert _collect("<h3>Balance</h3><div><h2 class=x>$0.13</h2></div>").balance == 0.13

    def test_legacy_window_userdata(self):
        assert _collect('window.userData = {"balance": 7.5}').balance == 7.5

    @pytest.mark.parametrize("html", ["<html><body>nothing here</body></html>", ""])
    def test_unparseable_reports_an_error_rather_than_zero_earnings(self, html):
        r = _collect(html)
        assert r.error is not None
        assert "page structure" in r.error
