"""CashPilot-1bz: a service was called idle before it had a chance to earn.

``get_earned_by_platform`` sums DELTAS over a window, in USD. The producer-state
endpoint read a zero from it as "not earning". A zero there has three possible
causes and only one of them is idle:

* **one reading so far** — there is no delta to take. Within an hour of a
  healthy first install the endpoint answered ``{"state": "idle", "reasons":
  ["Recorded earnings have not moved recently."]}`` about a service that had
  produced one perfectly good reading and had had no chance to move;
* **nothing priceable** — the sum is USD, so a platform whose readings have no
  rate sums to zero forever. A MystNodes balance climbing 40 → 55 → 70 MYST with
  no rate available was reported idle indefinitely;
* it genuinely did not earn.

The first two are "we cannot see", not "it is not earning" — and
``app/producer_state.py`` says so itself:

    ``earned_recently`` is None when it cannot be determined [...] That is
    reported as UNKNOWN rather than guessed, because telling a user their
    service is idle when we simply cannot see its earnings is the same false
    confidence this module exists to remove.

The module was right; the caller handed it a fabricated False.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SERVICE = {"slug": "mysterium", "name": "MystNodes", "status": "active"}


def _reading(date, balance, currency="USD", fx=1.0):
    return {"date": date, "balance": balance, "currency": currency, "fx_rate_usd": fx}


def _state(history, earned, containers=None):
    from app import main

    async def run():
        with (
            patch.object(main, "_require_auth_api", lambda r: None),
            patch.object(main.catalog, "get_service", return_value=SERVICE),
            patch.dict("app.collectors.COLLECTOR_MAP", {"mysterium": object()}, clear=True),
            patch.object(main.database, "get_balance_history", AsyncMock(return_value=history)),
            patch.object(main.database, "get_earned_by_platform", AsyncMock(return_value=earned)),
            patch.object(
                main,
                "_get_all_worker_containers",
                AsyncMock(
                    return_value=containers
                    if containers is not None
                    else [{"slug": "mysterium", "status": "running", "_worker_id": 1}]
                ),
            ),
            patch.object(main, "_proxy_worker_logs", AsyncMock(return_value={"logs": ""})),
        ):
            return await main.api_producer_state(MagicMock(), "mysterium")

    return asyncio.run(run())


class TestOneReadingIsNotEvidenceOfIdleness:
    def test_a_single_reading_reports_unknown(self):
        out = _state([_reading("2026-08-01", 5.0)], {"mysterium": 0.0})
        assert out["state"] != "idle", f"called idle after one reading: {out}"

    def test_no_readings_at_all_reports_unknown(self):
        out = _state([], {})
        assert out["state"] != "idle"

    def test_it_does_not_claim_earnings_have_not_moved(self):
        """The specific sentence a fresh install was shown."""
        out = _state([_reading("2026-08-01", 5.0)], {"mysterium": 0.0})
        assert not any("have not moved" in r for r in out.get("reasons", []))

    def test_two_readings_that_did_not_move_are_still_idle(self):
        """The control. Without it this passes by never reporting idle at all.

        Two priced readings with no gain between them IS evidence, and the
        verdict must survive.
        """
        history = [_reading("2026-07-30", 5.0), _reading("2026-07-31", 5.0)]
        out = _state(history, {"mysterium": 0.0})
        assert out["state"] == "idle"

    def test_two_readings_that_moved_are_producing(self):
        history = [_reading("2026-07-30", 5.0), _reading("2026-07-31", 7.0)]
        out = _state(history, {"mysterium": 2.0})
        assert out["state"] != "idle"


class TestAnUnpriceableBalanceIsNotIdle:
    """The MystNodes case: the balance climbs, the USD sum stays zero."""

    def test_a_climbing_token_balance_with_no_rate_is_not_idle(self):
        history = [
            _reading("2026-07-29", 40.0, "MYST", None),
            _reading("2026-07-30", 55.0, "MYST", None),
            _reading("2026-07-31", 70.0, "MYST", None),
        ]
        out = _state(history, {"mysterium": 0.0})
        assert out["state"] != "idle", f"a balance that grew 40 -> 70 was called idle: {out}"

    def test_one_unpriced_reading_is_enough_to_withhold_the_verdict(self):
        """A gap in the rates makes the window's total unreliable, not just smaller."""
        history = [
            _reading("2026-07-30", 40.0, "MYST", 0.5),
            _reading("2026-07-31", 55.0, "MYST", None),
        ]
        assert _state(history, {"mysterium": 0.0})["state"] != "idle"

    def test_a_priced_token_balance_is_still_judged(self):
        """The control: a rate being available is the whole difference."""
        history = [
            _reading("2026-07-30", 40.0, "MYST", 0.5),
            _reading("2026-07-31", 40.0, "MYST", 0.5),
        ]
        assert _state(history, {"mysterium": 0.0})["state"] == "idle"

    def test_usd_readings_need_no_rate(self):
        """USD is already USD; requiring an fx_rate_usd would break every service."""
        history = [_reading("2026-07-30", 5.0, "USD", None), _reading("2026-07-31", 5.0, "USD", None)]
        assert _state(history, {"mysterium": 0.0})["state"] == "idle"


class TestTheModuleContractIsUnchanged:
    """producer_state was always right; the caller fabricated the input."""

    @pytest.mark.parametrize("value", [None, True, False])
    def test_it_still_accepts_three_values(self, value):
        from app import producer_state

        out = producer_state.assess(slug="mysterium", has_collector=True, earned_recently=value, container_running=True)
        assert "state" in out

    def test_none_is_not_reported_as_idle(self):
        from app import producer_state

        assert (
            producer_state.assess(slug="mysterium", has_collector=True, earned_recently=None, container_running=True)[
                "state"
            ]
            != "idle"
        )

    def test_false_still_is(self):
        from app import producer_state

        assert (
            producer_state.assess(slug="mysterium", has_collector=True, earned_recently=False, container_running=True)[
                "state"
            ]
            == "idle"
        )
