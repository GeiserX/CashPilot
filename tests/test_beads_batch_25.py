"""CashPilot-qul: a correct balance was thrown away and reported as a failure.

``EarningsResult.error`` was doing two jobs — "this collection failed" and "this
succeeded, with a caveat" — and ``_run_collection`` stores a balance only in the
``else`` branch of ``if result.error:``.

Bytelixir's API fallback returns a real, valid withdrawable balance together
with an informational note ("Withdrawable balance only (HTML scrape failed,
using API fallback)"). Because that note went in ``error``, the balance was
discarded, no earnings row was written, and the user was told the collector had
failed — with an "Update credentials" button whose credentials were fine.

A caveat now has its own field. The reading is stored like any other, and the
note is surfaced as a `notice`, which the bell renders as a note rather than a
fault: the same reasoning already written for payouts, where the warning
triangle and the Update button "would tell the user something is broken at the
exact moment they got paid".
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"


def without_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in text.splitlines())


class TestACaveatIsNotAFailure:
    def test_the_result_type_can_hold_one(self):
        from app.collectors.base import EarningsResult

        result = EarningsResult(platform="bytelixir", balance=1.5, warning="partial")
        assert result.warning == "partial"
        assert result.error is None, "a caveat must not present as a failure"

    def test_a_plain_result_carries_neither(self):
        """The control: the new field must not appear on ordinary readings."""
        from app.collectors.base import EarningsResult

        result = EarningsResult(platform="honeygain", balance=3.0)
        assert result.warning is None
        assert result.error is None

    def test_bytelixirs_fallback_no_longer_reports_an_error(self):
        source = (ROOT / "app" / "collectors" / "bytelixir.py").read_text(encoding="utf-8")
        assert 'error="Withdrawable balance only' not in source, "the fallback still reports a failure"
        assert 'warning="Withdrawable balance only' in source

    def test_a_real_bytelixir_failure_is_still_an_error(self):
        """The control: this must not turn genuine failures into notes.

        An expired session is the common Bytelixir failure and needs the exact
        "Update credentials" affordance a notice deliberately withholds.
        """
        source = (ROOT / "app" / "collectors" / "bytelixir.py").read_text(encoding="utf-8")
        assert 'error="Session expired' in source


class TestTheBalanceIsStoredAndTheNoteIsShown:
    async def _collect(self, result):
        """Drive the part of _run_collection that decides store-or-alert."""
        from app import main
        from app.collectors.base import EarningsResult

        assert isinstance(result, EarningsResult)
        stored: list[dict] = []
        alerts: list[dict] = []

        async def fake_upsert(**kwargs):
            stored.append(kwargs)

        with (
            patch.object(main.database, "get_deployments", AsyncMock(return_value=[{"slug": "bytelixir"}])),
            patch.object(main.database, "get_config", AsyncMock(return_value={})),
            patch.object(main.database, "upsert_earnings", AsyncMock(side_effect=fake_upsert)),
            patch.object(main.database, "record_alert", AsyncMock(return_value=False)),
            patch.object(main.database, "list_alerts", AsyncMock(return_value=[])),
            patch.object(main, "_detect_payout", AsyncMock(return_value=None)),
            patch.object(main, "_flatline_check", AsyncMock(return_value=[])),
            patch.object(main, "_pending_payout_alerts", AsyncMock(return_value=[])),
            patch.object(main, "_collect_bounded", AsyncMock(return_value=result)),
            patch("app.collectors.make_collectors", lambda deployments, config: [object()]),
            patch("app.collectors._close_stale", AsyncMock()),
            patch.object(main, "_spawn", lambda coro: coro.close()),
        ):
            await main._run_collection()
            alerts = list(main._collector_alerts)
        return stored, alerts

    @pytest.mark.asyncio
    async def test_a_reading_with_a_caveat_is_stored(self):
        from app.collectors.base import EarningsResult

        stored, _ = await self._collect(
            EarningsResult(platform="bytelixir", balance=1.2345, currency="USD", warning="partial figure")
        )
        assert stored, "the balance was discarded again"
        assert stored[0]["balance"] == pytest.approx(1.2345)

    @pytest.mark.asyncio
    async def test_the_caveat_is_surfaced_as_a_notice(self):
        from app.collectors.base import EarningsResult

        _, alerts = await self._collect(EarningsResult(platform="bytelixir", balance=1.2345, warning="partial figure"))
        notices = [a for a in alerts if a.get("kind") == "notice"]
        assert len(notices) == 1
        assert notices[0]["platform"] == "bytelixir"
        assert "partial figure" in notices[0]["error"]

    @pytest.mark.asyncio
    async def test_it_is_not_reported_as_a_collector_failure(self):
        from app.collectors.base import EarningsResult

        _, alerts = await self._collect(EarningsResult(platform="bytelixir", balance=1.2345, warning="partial figure"))
        assert not [a for a in alerts if a.get("kind") == "collector"], (
            "a successful reading is still being reported as a broken collector"
        )

    @pytest.mark.asyncio
    async def test_a_genuine_error_still_stores_nothing(self):
        """The control. Without it this could pass by storing everything."""
        from app.collectors.base import EarningsResult

        stored, alerts = await self._collect(EarningsResult(platform="bytelixir", balance=0.0, error="Session expired"))
        assert not stored, "a failed collection wrote an earnings row"
        assert [a for a in alerts if a.get("kind") == "collector"]

    @pytest.mark.asyncio
    async def test_an_ordinary_reading_produces_no_notice(self):
        """The control: the bell must not gain an entry per successful collection."""
        from app.collectors.base import EarningsResult

        stored, alerts = await self._collect(EarningsResult(platform="honeygain", balance=5.0))
        assert stored
        assert not [a for a in alerts if a.get("kind") == "notice"]


class TestTheBellRendersANoteRatherThanAFault:
    def _js(self):
        return without_comments(APP_JS.read_text(encoding="utf-8"))

    def test_a_notice_is_recognised(self):
        assert "a.kind === 'notice'" in self._js()

    def test_a_notice_does_not_offer_update_credentials(self):
        """The button points at the one action that cannot help here."""
        assert "!isPayout && !isNotice && _isOwner" in self._js()

    def test_a_notice_does_not_use_the_warning_triangle(self):
        js = self._js()
        assert "NOTICE_ICON" in js
        assert "isNotice ? NOTICE_ICON : WARNING_ICON" in js

    def test_a_collector_failure_still_gets_the_triangle_and_the_button(self):
        """The control: the fault path must survive intact."""
        js = self._js()
        assert "WARNING_ICON" in js
        assert "openCredentialModal" in js
