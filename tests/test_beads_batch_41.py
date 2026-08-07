"""CashPilot-45k and -tb5: two affirmatives nobody had earned.

**45k** — the Active Services card showed "0" when the count could not be taken.
``_get_all_worker_containers`` opens SQLite, so a locked or busy database, or a
JSON-decode failure on a worker row, lands in the ``except`` while containers
are in fact running. The fallback was ``0``, which reads as "nothing is
running", and the only other signal was a ``logger.debug`` — and DEBUG is off in
production, so both places that could have said something said nothing.

**tb5** — the bell rendered an empty alert list as "All collectors healthy". On
a fresh install, or after a restart before the first hourly collection, nothing
has been checked. The bell's own FAILURE path is written correctly ("Alerts
unavailable" rather than healthy), which makes the never-ran case the outlier
rather than a matter of style.

Both are the same shape: absent presented as an affirmative.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"


def js() -> str:
    text = APP_JS.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in text.splitlines())


async def _summary(*, worker_read_fails):
    from app import main

    containers = (
        AsyncMock(side_effect=Exception("database is locked")) if worker_read_fails else AsyncMock(return_value=[])
    )
    with (
        patch.object(main, "_require_auth_api", lambda r: None),
        patch.object(main, "_require_reader", lambda r: None),
        patch.object(main.database, "get_earnings_dashboard_summary", AsyncMock(return_value={"total": 0})),
        patch.object(main.database, "get_config", AsyncMock(return_value={})),
        patch.object(main.database, "get_earnings_summary", AsyncMock(return_value=[])),
        patch.object(main, "_get_all_worker_containers", containers),
    ):
        return await main.api_earnings_summary(MagicMock())


class TestAnUncountableFleetIsUnknown:
    @pytest.mark.asyncio
    async def test_a_failed_read_reports_none(self):
        assert (await _summary(worker_read_fails=True))["active_services"] is None

    @pytest.mark.asyncio
    async def test_a_successful_read_of_nothing_still_reports_zero(self):
        """The control. A fleet with no running containers really is zero."""
        assert (await _summary(worker_read_fails=False))["active_services"] == 0

    @pytest.mark.asyncio
    async def test_the_failure_is_logged_where_it_can_be_seen(self, caplog):
        """DEBUG is off in production, so a debug log is the same as silence."""
        import logging

        with caplog.at_level(logging.WARNING, logger="app.main"):
            caplog.clear()
            await _summary(worker_read_fails=True)
        assert any("Could not count active services" in r.getMessage() for r in caplog.records)

    def test_the_card_renders_a_dash(self):
        source = js()
        assert "data.active_services || 0" not in source, "unknown still renders as 0"
        assert "data.active_services == null" in source


class TestTheBellDoesNotClaimUncheckedHealth:
    async def _alerts(self, *, alerts, has_run):
        from app import main

        with (
            patch.object(main, "_require_auth_api", lambda r: None),
            patch.object(main, "_require_reader", lambda r: None),
            patch.object(main, "_collector_alerts", alerts),
            patch.object(main, "_collection_has_run", has_run),
        ):
            return await main.api_collector_alerts(MagicMock())

    @pytest.mark.asyncio
    async def test_a_fresh_install_reports_that_nothing_has_run(self):
        out = await self._alerts(alerts=[], has_run=False)
        assert out["collected"] is False
        assert out["alerts"] == []

    @pytest.mark.asyncio
    async def test_after_a_run_with_no_problems_it_says_so(self):
        """The control: a genuine all-clear must remain expressible."""
        out = await self._alerts(alerts=[], has_run=True)
        assert out["collected"] is True

    @pytest.mark.asyncio
    async def test_the_alerts_still_come_through_tagged(self):
        out = await self._alerts(alerts=[{"platform": "grass", "error": "boom"}], has_run=True)
        assert out["alerts"][0]["kind"] == "collector"

    def test_the_ui_distinguishes_the_two(self):
        source = js()
        assert "payload.collected" in source
        assert "No collection has run yet" in source

    def test_the_all_clear_is_still_possible(self):
        """The control: the affirmative must survive for the case that earns it."""
        assert "All collectors healthy" in js()

    def test_the_ui_reads_the_new_shape(self):
        source = js()
        assert "payload.alerts" in source


class TestTheFlagSurvivesARestart:
    """A restart must not make the bell claim nothing has ever been checked."""

    async def _warm(self, *, stored_alerts, earnings):
        from app import main

        with (
            patch.object(main, "_collection_has_run", False),
            patch.object(main.database, "list_alerts", AsyncMock(return_value=stored_alerts)),
            patch.object(main.database, "get_earnings_summary", AsyncMock(return_value=earnings)),
        ):
            await main._warm_collector_alerts()
            return main._collection_has_run

    @pytest.mark.asyncio
    async def test_stored_alerts_prove_a_run_happened(self):
        stored = [{"kind": "collector", "subject": "grass", "message": "boom"}]
        assert await self._warm(stored_alerts=stored, earnings=[]) is True

    @pytest.mark.asyncio
    async def test_earnings_rows_prove_it_too(self):
        rows = [{"platform": "honeygain", "balance": 1.0, "currency": "USD"}]
        assert await self._warm(stored_alerts=[], earnings=rows) is True

    @pytest.mark.asyncio
    async def test_a_genuinely_fresh_install_stays_false(self):
        """The control: without it this passes by always claiming a run."""
        assert await self._warm(stored_alerts=[], earnings=[]) is False

    @pytest.mark.asyncio
    async def test_a_failed_lookup_does_not_claim_a_run(self):
        from app import main

        with (
            patch.object(main, "_collection_has_run", False),
            patch.object(main.database, "list_alerts", AsyncMock(return_value=[])),
            patch.object(main.database, "get_earnings_summary", AsyncMock(side_effect=Exception("locked"))),
        ):
            await main._warm_collector_alerts()
            assert main._collection_has_run is False
