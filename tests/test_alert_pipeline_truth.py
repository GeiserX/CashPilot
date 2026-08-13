"""The alert pipeline must be able to report its own failures.

Four structural fixes pinned here:

- A collection run in which EVERY collector fails was recorded as a SUCCESS,
  refreshing collection_last_success_timestamp hourly through a total outage —
  both documented Prometheus alerts were structurally unable to fire.
- The dedupe row is committed BEFORE delivery is attempted, so one failed push
  used to disarm that alert for the whole 24h cooldown, invisibly.
- Payout prompts were recorded and belled but never pushed.
- The payout retire path could clear the bell in memory while the durable
  delete failed — the operator "answered" a financial prompt that then
  resurrected after the next restart.
"""

import asyncio
import os
import time

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

try:
    from app import main, metrics  # noqa: E402
    from app.collectors.base import EarningsResult  # noqa: E402
except ImportError:
    pytest.skip(
        "Requires full app dependencies (fastapi, httpx, etc.) — runs in CI",
        allow_module_level=True,
    )

from unittest.mock import AsyncMock, patch  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class TestTotalCollectionFailureIsAnError:
    async def _collect(self, results):
        """Drive _run_collection over the given per-collector results."""
        ends = []

        def _capture_end(start, success, platforms_ok=0):
            ends.append((success, platforms_ok))

        seq = iter(results)
        with (
            patch.object(main.database, "get_deployments", AsyncMock(return_value=[{"slug": "x"}])),
            patch.object(main.database, "get_config", AsyncMock(return_value={})),
            patch.object(main.database, "upsert_earnings", AsyncMock()),
            patch.object(main.database, "record_alert", AsyncMock(return_value=False)),
            patch.object(main.database, "clear_alerts", AsyncMock()),
            patch.object(main, "_detect_payout", AsyncMock(return_value=None)),
            patch.object(main, "_flatline_check", AsyncMock(return_value=[])),
            patch.object(main, "_pending_payout_alerts", AsyncMock(return_value=[])),
            patch.object(main, "_collect_bounded", AsyncMock(side_effect=lambda c: next(seq))),
            patch.object(main, "_collector_alerts", []),
            patch.object(main.metrics, "record_collection_end", _capture_end),
            patch("app.collectors.make_collectors", lambda deployments, config: [object() for _ in results]),
            patch("app.collectors._close_stale", AsyncMock()),
            patch.object(main, "_spawn", lambda coro: coro.close()),
        ):
            await main._run_collection()
        assert len(ends) == 1
        return ends[0]

    @pytest.mark.asyncio
    async def test_every_collector_failing_is_not_a_success(self):
        success, ok = await self._collect(
            [
                EarningsResult(platform="a", balance=0.0, error="down"),
                EarningsResult(platform="b", balance=0.0, error="down"),
            ]
        )
        assert success is False
        assert ok == 0

    @pytest.mark.asyncio
    async def test_a_partial_failure_is_still_a_success(self):
        # Negative control: one chronically broken collector must not freeze
        # the staleness stamp while the other platforms collect fine.
        success, ok = await self._collect(
            [
                EarningsResult(platform="a", balance=1.0),
                EarningsResult(platform="b", balance=0.0, error="down"),
            ]
        )
        assert success is True
        assert ok == 1

    @pytest.mark.asyncio
    async def test_an_empty_install_is_not_stale(self):
        # Negative control: no collectors configured means nothing to be
        # stale about — the timestamp must keep advancing.
        success, ok = await self._collect([])
        assert success is True
        assert ok == 0


class TestPushAlertFeedsBack:
    def _push(self, *, delivered, enabled, raises=False):
        cleared = []

        async def _clear(kind, subject):
            cleared.append((kind, subject))

        async def _send(title, message, **kw):
            if raises:
                raise RuntimeError("notifier exploded")
            return delivered

        recorded = []
        with (
            patch.object(main.notify, "send", _send),
            patch.object(main.notify, "is_enabled", lambda: enabled),
            patch.object(main.database, "clear_alerts", _clear),
            patch.object(main.metrics, "record_notify_delivery", recorded.append),
        ):
            _run(main._push_alert("collector", "honeygain", "t", "m"))
        return cleared, recorded

    def test_a_failed_delivery_undedupes_for_retry(self):
        cleared, recorded = self._push(delivered=0, enabled=True)
        assert cleared == [("collector", "honeygain")]
        assert recorded == [False]

    def test_a_successful_delivery_keeps_the_dedupe(self):
        # Negative control: delivered means the row must stand, or every
        # cycle would re-push the same alert.
        cleared, recorded = self._push(delivered=1, enabled=True)
        assert cleared == []
        assert recorded == [True]

    def test_no_channel_configured_means_no_churn(self):
        # Negative control: with nothing configured the bell is the channel;
        # clearing would re-insert every cycle, and a delivery metric would
        # only count an absence.
        cleared, recorded = self._push(delivered=0, enabled=False)
        assert cleared == []
        assert recorded == []

    def test_a_crashing_notifier_counts_as_failed(self):
        cleared, recorded = self._push(delivered=0, enabled=True, raises=True)
        assert cleared == [("collector", "honeygain")]
        assert recorded == [False]


class TestPayoutPromptIsPushed:
    def _detect(self, *, record_returns, payout_id=7):
        sends = []

        async def _send(title, message, **kw):
            sends.append((title, kw.get("kind"), kw.get("subject")))
            return 1

        spawned = []
        result = EarningsResult(platform="storj", balance=1.0, currency="USD")
        with (
            patch.object(main.database, "get_latest_balance", AsyncMock(return_value=6.0)),
            patch.object(main.catalog, "get_service", lambda slug: {"slug": slug}),
            patch.object(
                main.payouts,
                "detect",
                lambda prev, bal, svc: {"amount": 5.0, "reason": "balance dropped by 5"},
            ),
            patch.object(main.database, "record_probable_payout", AsyncMock(return_value=payout_id)),
            patch.object(main.database, "record_alert", AsyncMock(return_value=record_returns)),
            patch.object(main.notify, "send", _send),
            patch.object(main.notify, "is_enabled", lambda: True),
            patch.object(main.metrics, "record_notify_delivery", lambda ok: None),
            patch.object(main, "_spawn", lambda coro: spawned.append(coro)),
        ):
            out = _run(main._detect_payout(result))
            for coro in spawned:
                _run(coro)
        return out, sends

    def test_a_fresh_payout_prompt_is_pushed(self):
        out, sends = self._detect(record_returns=True)
        assert out is not None and out["kind"] == "payout"
        assert sends == [("CashPilot: storj balance dropped — was this a payout?", "payout", "storj")]

    def test_a_deduped_payout_prompt_is_not_pushed(self):
        # Negative control: inside the cooldown the bell entry still returns,
        # but no second push goes out.
        out, sends = self._detect(record_returns=False)
        assert out is not None
        assert sends == []

    def test_an_already_pending_payout_pushes_nothing(self):
        # Negative control: record_probable_payout None = a prompt is already
        # open for this platform; a second one teaches the user to dismiss.
        out, sends = self._detect(record_returns=True, payout_id=None)
        assert out is None
        assert sends == []


class TestPayoutRetireHonesty:
    def test_a_failed_durable_clear_keeps_the_bell(self):
        with (
            patch.object(main, "_collector_alerts", [{"kind": "payout", "platform": "storj", "error": "x"}]),
            patch.object(main.database, "clear_alerts", AsyncMock(side_effect=RuntimeError("db locked"))),
        ):
            _run(main._retire_payout_alert(1, platform="storj"))
            assert any(a["kind"] == "payout" for a in main._collector_alerts)

    def test_a_successful_clear_prunes_the_bell(self):
        # Negative control for the fix above.
        with (
            patch.object(main, "_collector_alerts", [{"kind": "payout", "platform": "storj", "error": "x"}]),
            patch.object(main.database, "clear_alerts", AsyncMock()),
        ):
            _run(main._retire_payout_alert(1, platform="storj"))
            assert main._collector_alerts == []

    def test_platform_lookup_failure_is_loud_and_returns_none(self, caplog):
        import logging

        with (
            patch.object(main.database, "get_payouts", AsyncMock(side_effect=RuntimeError("db gone"))),
            caplog.at_level(logging.WARNING, logger=main.logger.name),
        ):
            assert _run(main._payout_platform(9)) is None
        assert any("Could not resolve payout" in r.getMessage() for r in caplog.records)


class TestFlatlineCheckFailureIsVisible:
    def test_a_broken_flatline_check_reaches_the_bell(self):
        with patch.object(main.database, "get_flatlined_services", AsyncMock(side_effect=RuntimeError("boom"))):
            bell = _run(main._flatline_check())
        assert any(e["kind"] == "flatline" and "NOT being watched" in e["error"] for e in bell)

    def test_a_healthy_flatline_check_adds_nothing(self):
        # Negative control.
        with (
            patch.object(main.database, "get_flatlined_services", AsyncMock(return_value=[])),
            patch.object(main.database, "get_alert_subjects", AsyncMock(return_value=set())),
        ):
            bell = _run(main._flatline_check())
        assert bell == []


class TestMetricsHygiene:
    def setup_method(self):
        self._orig_enabled = metrics.METRICS_ENABLED
        self._orig_registry = metrics._registry
        self._orig_metrics = metrics._metrics.copy()
        metrics.METRICS_ENABLED = True
        metrics._init_metrics()

    def teardown_method(self):
        metrics.METRICS_ENABLED = self._orig_enabled
        metrics._registry = self._orig_registry
        metrics._metrics = self._orig_metrics

    def test_notify_delivery_metric_records_both_outcomes(self):
        metrics.record_notify_delivery(True)
        metrics.record_notify_delivery(False)
        assert metrics._metrics["notify_delivery_total"].labels(result="success")._value.get() == 1
        assert metrics._metrics["notify_delivery_total"].labels(result="error")._value.get() == 1
        assert metrics._metrics["notify_last_success_timestamp"]._value.get() == pytest.approx(time.time(), abs=5)

    def test_removed_worker_gauges_are_cleared_on_refresh(self):
        async def _drive():
            with (
                patch.object(metrics, "_last_refresh", 0.0),
                patch(
                    "app.database.list_workers",
                    AsyncMock(
                        return_value=[
                            {
                                "name": "ghost",
                                "status": "online",
                                "last_heartbeat": "2026-08-13T10:00:00",
                                "system_info": '{"docker_available": true}',
                                "containers": "[]",
                            }
                        ]
                    ),
                ),
                patch("app.database.get_earnings_summary", AsyncMock(return_value=[])),
                patch("app.database.get_deployments", AsyncMock(return_value=[])),
                patch("app.database.get_health_scores", AsyncMock(return_value=[])),
            ):
                await metrics._refresh_gauges()
            # Second refresh: the worker is GONE. Its series must vanish too.
            with (
                patch.object(metrics, "_last_refresh", 0.0),
                patch("app.database.list_workers", AsyncMock(return_value=[])),
                patch("app.database.get_earnings_summary", AsyncMock(return_value=[])),
                patch("app.database.get_deployments", AsyncMock(return_value=[])),
                patch("app.database.get_health_scores", AsyncMock(return_value=[])),
            ):
                await metrics._refresh_gauges()

        _run(_drive())
        from prometheus_client import generate_latest

        text = generate_latest(metrics._registry).decode()
        assert 'cashpilot_worker_docker_available{worker="ghost"}' not in text

    def test_unparseable_heartbeat_is_counted_not_skipped(self):
        async def _drive():
            with (
                patch.object(metrics, "_last_refresh", 0.0),
                patch(
                    "app.database.list_workers",
                    AsyncMock(
                        return_value=[
                            {
                                "name": "broken",
                                "status": "online",
                                "last_heartbeat": "not-a-timestamp",
                                "system_info": "{}",
                                "containers": "[]",
                            }
                        ]
                    ),
                ),
                patch("app.database.get_earnings_summary", AsyncMock(return_value=[])),
                patch("app.database.get_deployments", AsyncMock(return_value=[])),
                patch("app.database.get_health_scores", AsyncMock(return_value=[])),
            ):
                await metrics._refresh_gauges()

        _run(_drive())
        assert metrics._metrics["worker_heartbeat_unparseable_total"].labels(worker="broken")._value.get() == 1
