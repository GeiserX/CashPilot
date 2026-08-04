"""CashPilot-364: the one failure nothing else can surface reached nobody.

A container is up, its collector authenticates fine, and the balance has not
moved for days. That is exactly what ``_flatline_check`` was built for — its own
docstring says "Every other view of the system looks healthy, so nothing else
would surface it".

It wrote the alert to SQLite and handed it to ``notify.send``, and then the row
was silently dropped on the way to the UI. ``_flatline_check`` never appended to
``_collector_alerts``, and ``_run_collection`` assigned that list *before*
calling it. ``_warm_collector_alerts`` filtered on ``kind in ("collector",
"payout")``, so a restart dropped it too.

On a default install ``notify`` is the only other route and it is not
configured: ``configured_targets()`` returns [] and ``send`` returns 0
immediately, and neither docker-compose.yml nor docker-compose.fleet.yml sets
any NTFY/WEBHOOK/TELEGRAM variable. So the bell said "All collectors healthy"
while a service earned nothing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

FLAT = [{"platform": "honeygain", "days_flat": 6, "balance": 3.5}]


async def _run_check(flat_services, *, record_returns=True):
    from app import main

    with (
        patch.object(main.database, "get_flatlined_services", AsyncMock(return_value=flat_services)),
        patch.object(main.database, "get_alert_subjects", AsyncMock(return_value=set())),
        patch.object(main.database, "clear_alerts", AsyncMock()),
        patch.object(main.database, "record_alert", AsyncMock(return_value=record_returns)),
        patch.object(main, "_spawn", lambda coro: coro.close()),
    ):
        return await main._flatline_check()


class TestAFlatlinedServiceReachesTheBell:
    @pytest.mark.asyncio
    async def test_the_check_reports_what_it_found(self):
        bell = await _run_check(FLAT)
        assert [a["platform"] for a in bell] == ["honeygain"]

    @pytest.mark.asyncio
    async def test_the_entry_says_what_is_wrong(self):
        bell = await _run_check(FLAT)
        assert bell[0]["kind"] == "flatline"
        assert "not earning" in bell[0]["error"]
        assert "6 days" in bell[0]["error"]

    @pytest.mark.asyncio
    async def test_a_healthy_install_reports_nothing(self):
        """The control: this must not put a permanent entry in the bell."""
        assert await _run_check([]) == []

    @pytest.mark.asyncio
    async def test_the_cooldown_does_not_blank_the_bell(self):
        """record_alert returning False means "already notified", not "fine".

        The cooldown exists to stop repeat NOTIFICATIONS. The bell is a standing
        statement of what is wrong right now, so gating it the same way would
        clear the warning on the second collection while the service was still
        not earning — which is the original bug wearing a different hat.
        """
        bell = await _run_check(FLAT, record_returns=False)
        assert [a["platform"] for a in bell] == ["honeygain"]

    @pytest.mark.asyncio
    async def test_a_failing_check_still_returns_a_list(self):
        """It is a diagnostic; it must not break the collection run.

        The docstring promises it never raises, and the caller now extends a
        list with its result — so returning None would turn a diagnostic failure
        into a TypeError that takes down collection.
        """
        from app import main

        with patch.object(main.database, "get_flatlined_services", AsyncMock(side_effect=RuntimeError("boom"))):
            assert await main._flatline_check() == []


class TestTheCollectionRunKeepsThem:
    def test_the_check_runs_before_the_bell_is_assigned(self):
        """Ordering is the whole defect: it ran after, so its result was lost."""
        import inspect

        from app import main

        source = inspect.getsource(main._run_collection)
        extend_at = source.index("await _flatline_check()")
        assign_at = source.index("_collector_alerts = alerts")
        assert extend_at < assign_at, "_flatline_check still runs after the bell is set"

    def test_its_result_is_actually_used(self):
        import inspect

        from app import main

        source = inspect.getsource(main._run_collection)
        assert "alerts.extend(await _flatline_check())" in source, "the result is discarded again"


class TestARestartDoesNotClearTheWarning:
    async def _warm(self, stored):
        from app import main

        with patch.object(main.database, "list_alerts", AsyncMock(return_value=stored)):
            await main._warm_collector_alerts()
            return list(main._collector_alerts)

    @pytest.mark.asyncio
    async def test_a_persisted_flatline_is_restored(self):
        restored = await self._warm([{"kind": "flatline", "subject": "honeygain", "message": "not earning"}])
        assert [a["platform"] for a in restored] == ["honeygain"]

    @pytest.mark.asyncio
    async def test_collector_and_payout_alerts_still_survive(self):
        """The control: widening the filter must not narrow it elsewhere."""
        restored = await self._warm(
            [
                {"kind": "collector", "subject": "grass", "message": "auth failed"},
                {"kind": "payout", "subject": "storj", "message": "payout?"},
                {"kind": "flatline", "subject": "honeygain", "message": "not earning"},
            ]
        )
        assert {a["platform"] for a in restored} == {"grass", "storj", "honeygain"}

    @pytest.mark.asyncio
    async def test_unrelated_kinds_are_still_dropped(self):
        """The filter must stay a filter, not become "restore everything"."""
        restored = await self._warm([{"kind": "debug", "subject": "x", "message": "noise"}])
        assert restored == []

    @pytest.mark.asyncio
    async def test_a_platform_can_carry_both_a_failure_and_a_flatline(self):
        """Dedup is by kind AND subject; these are different things to say."""
        restored = await self._warm(
            [
                {"kind": "collector", "subject": "honeygain", "message": "auth failed"},
                {"kind": "flatline", "subject": "honeygain", "message": "not earning"},
            ]
        )
        assert len(restored) == 2
