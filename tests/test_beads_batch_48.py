"""CashPilot-c6u: a worker-status failure made net earnings report gross as profit.

``/api/earnings/net`` exists to answer "what did I actually keep?". Its docstring
promises it never presents gross as profit, and ``app/power.py`` says the same
thing twice: *"a zero cost would render gross as net and quietly overstate
earnings."*

It did exactly that. ``_get_all_worker_containers`` reaches the workers over
HTTP, so it fails for ordinary reasons — a host down, a proxy blip, a busy
SQLite. The handler caught that and substituted ``statuses = []``, which is a
different FACT from "nothing is running" but was indistinguishable downstream.
Every service was then charged 0 W, ``total_cost`` summed to 0.00, and
``total_net`` came out equal to ``total_gross``.

The lie is ``cost_known``. ``app/power.py:137`` derives it from
``price_per_kwh > 0`` — the tariff alone — and never asks whether any watts were
measured. So with a tariff configured the endpoint reported a cost of zero and
a net equal to gross, and labelled it *known*.

The endpoint's own comment already described this outcome as a bug that had bitten
the project twice, both times through the ``service`` vs ``slug`` key. The except
branch recreates the same precondition by a different route.

The fix reuses the mechanism already in this handler for unavailable FX: a zero
price makes ``summarise`` report cost and net as ``None`` rather than as numbers.
Unknown watts now suppress the net the same way, and say why.

Gross is still reported. It comes from the database and is unaffected by whether
a worker answered.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def rows():
    """One platform with real earnings, so a zero net is unmistakably wrong."""
    return [{"platform": "honeygain", "usd": 10.0}]


async def _call_net(monkeypatch, *, worker_lookup, config, days=7):
    """Drive api_earnings_net with the worker lookup and config under test."""
    from app import main

    with (
        patch.object(main, "_get_all_worker_containers", worker_lookup),
        # list_workers supplies the per-machine power metadata; it is a real DB
        # read that is irrelevant to this bead. Checked the actual names rather
        # than guessing: main.py:2385 calls database.list_workers().
        patch.object(main.database, "list_workers", AsyncMock(return_value=[])),
        patch.object(main.database, "get_earned_by_platform", AsyncMock(return_value={"honeygain": 10.0})),
        patch.object(main.database, "get_config", AsyncMock(return_value=config)),
        patch.object(main, "_require_auth_api", lambda _r: None),
    ):
        return await main.api_earnings_net(request=None, days=days)


TARIFF = {"power_price_per_kwh": "0.30", "power_currency": "USD"}


class TestAFailedWorkerLookupSuppressesTheNet:
    """The bead. A tariff IS configured, so the old code produced numbers."""

    @pytest.mark.asyncio
    async def test_cost_is_not_reported_as_known(self, monkeypatch):
        result = await _call_net(
            monkeypatch,
            worker_lookup=AsyncMock(side_effect=RuntimeError("worker unreachable")),
            config=TARIFF,
        )
        assert result["cost_known"] is False, (
            "the endpoint claims to know a cost it could not measure — this is the whole bead"
        )

    @pytest.mark.asyncio
    async def test_the_net_is_not_reported_at_all(self, monkeypatch):
        result = await _call_net(
            monkeypatch,
            worker_lookup=AsyncMock(side_effect=RuntimeError("worker unreachable")),
            config=TARIFF,
        )
        assert result["total_net"] is None, "a net figure was produced from watts nobody could read"

    @pytest.mark.asyncio
    async def test_the_cost_is_not_reported_as_zero(self, monkeypatch):
        """Zero is a measurement. This was not one."""
        result = await _call_net(
            monkeypatch,
            worker_lookup=AsyncMock(side_effect=RuntimeError("worker unreachable")),
            config=TARIFF,
        )
        assert result["total_cost"] is None

    @pytest.mark.asyncio
    async def test_net_does_not_silently_equal_gross(self, monkeypatch):
        """The precise shape of the old bug, asserted directly."""
        result = await _call_net(
            monkeypatch,
            worker_lookup=AsyncMock(side_effect=RuntimeError("worker unreachable")),
            config=TARIFF,
        )
        assert not (result["total_net"] == result["total_gross"] and result["cost_known"]), (
            "gross is being presented as profit, which this endpoint promises never to do"
        )

    @pytest.mark.asyncio
    async def test_gross_is_still_reported(self, monkeypatch):
        """It comes from the database and a worker outage cannot affect it."""
        result = await _call_net(
            monkeypatch,
            worker_lookup=AsyncMock(side_effect=RuntimeError("worker unreachable")),
            config=TARIFF,
        )
        assert result["total_gross"] == pytest.approx(10.0)

    @pytest.mark.asyncio
    async def test_it_says_why(self, monkeypatch):
        """A suppressed figure with no explanation reads as a broken page."""
        result = await _call_net(
            monkeypatch,
            worker_lookup=AsyncMock(side_effect=RuntimeError("worker unreachable")),
            config=TARIFF,
        )
        reason = result["cost_unavailable_reason"]
        assert "workers" in reason
        assert "not zero" in reason, "the reason must rule out the reading the number would have suggested"

    @pytest.mark.asyncio
    async def test_the_cause_is_machine_readable(self, monkeypatch):
        """Distinguishable from the FX cause, which sets its own flag."""
        result = await _call_net(
            monkeypatch,
            worker_lookup=AsyncMock(side_effect=RuntimeError("worker unreachable")),
            config=TARIFF,
        )
        assert result.get("watts_unavailable") is True
        assert result.get("fx_unavailable") is not True


class TestAWorkingLookupIsUnaffected:
    """The suppression must be narrow, or it silences the normal case."""

    @pytest.mark.asyncio
    async def test_an_empty_but_successful_lookup_still_reports_a_cost(self, monkeypatch):
        """A fleet with nothing running is a MEASUREMENT of zero draw.

        This is the case that separates the fix from "always report unknown":
        the same empty list, arrived at honestly, must still produce a net.
        """
        result = await _call_net(monkeypatch, worker_lookup=AsyncMock(return_value=[]), config=TARIFF)
        assert result["cost_known"] is True
        assert result["total_net"] is not None
        assert result.get("watts_unavailable") is not True

    @pytest.mark.asyncio
    async def test_a_running_fleet_reports_a_cost(self, monkeypatch):
        statuses = [{"slug": "honeygain", "status": "running", "worker_id": 1}]
        result = await _call_net(monkeypatch, worker_lookup=AsyncMock(return_value=statuses), config=TARIFF)
        assert result["cost_known"] is True
        assert result["total_cost"] is not None

    @pytest.mark.asyncio
    async def test_no_tariff_still_reports_unknown_for_its_own_reason(self, monkeypatch):
        """The pre-existing behaviour, which this must not disturb."""
        result = await _call_net(monkeypatch, worker_lookup=AsyncMock(return_value=[]), config={})
        assert result["cost_known"] is False
        assert result["total_net"] is None
        assert result.get("watts_unavailable") is not True


class TestTheTwoUnknownCausesDoNotMaskEachOther:
    @pytest.mark.asyncio
    async def test_both_failing_reports_both(self, monkeypatch):
        """A tariff in a currency with no rate AND unreachable workers."""
        from app import main

        with patch.object(main.exchange_rates, "to_usd", lambda *_a, **_k: None):
            result = await _call_net(
                monkeypatch,
                worker_lookup=AsyncMock(side_effect=RuntimeError("down")),
                config={"power_price_per_kwh": "0.30", "power_currency": "GBP"},
            )
        assert result["cost_known"] is False
        assert result["total_net"] is None
        assert result.get("watts_unavailable") is True
        assert result.get("fx_unavailable") is True
