"""Tests for the Prometheus metrics module."""

import time
from unittest.mock import AsyncMock, patch

import pytest

from app import metrics


class TestMetricsDisabled:
    """When METRICS_ENABLED=False, instrumentation hooks are no-ops."""

    def setup_method(self):
        self._orig = metrics.METRICS_ENABLED
        metrics.METRICS_ENABLED = False

    def teardown_method(self):
        metrics.METRICS_ENABLED = self._orig

    def test_record_collection_end_noop(self):
        metrics.record_collection_end(time.time() - 5, success=True, platforms_scraped=3)

    def test_record_collection_error_noop(self):
        metrics.record_collection_error("honeygain")

    def test_record_container_lifecycle_noop(self):
        metrics.record_container_lifecycle("deploy", "earnapp")

    def test_record_login_noop(self):
        metrics.record_login(success=True)

    def test_record_rate_limit_noop(self):
        metrics.record_rate_limit()

    def test_record_heartbeat_noop(self):
        metrics.record_heartbeat("worker-1")

    def test_record_collection_start_returns_float(self):
        assert isinstance(metrics.record_collection_start(), float)


class TestMetricsEnabled:
    """When metrics are enabled, instrumentation hooks record data."""

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

    def test_record_collection_end_success(self):
        start = time.time() - 10
        metrics.record_collection_end(start, success=True, platforms_scraped=5)
        assert metrics._metrics["collection_runs_total"].labels(result="success")._value.get() == 1
        assert metrics._metrics["collection_platforms_scraped"]._value.get() == 5

    def test_record_collection_end_error(self):
        start = time.time() - 2
        metrics.record_collection_end(start, success=False, platforms_scraped=0)
        assert metrics._metrics["collection_runs_total"].labels(result="error")._value.get() == 1

    def test_record_collection_error(self):
        metrics.record_collection_error("honeygain")
        metrics.record_collection_error("honeygain")
        assert metrics._metrics["collection_errors_total"].labels(platform="honeygain")._value.get() == 2

    def test_record_container_lifecycle(self):
        metrics.record_container_lifecycle("deploy", "earnapp")
        metrics.record_container_lifecycle("stop", "earnapp")
        assert (
            metrics._metrics["container_lifecycle_total"].labels(action="deploy", service="earnapp")._value.get() == 1
        )
        assert metrics._metrics["container_lifecycle_total"].labels(action="stop", service="earnapp")._value.get() == 1

    def test_record_login(self):
        metrics.record_login(success=True)
        metrics.record_login(success=False)
        metrics.record_login(success=False)
        assert metrics._metrics["login_attempts_total"].labels(result="success")._value.get() == 1
        assert metrics._metrics["login_attempts_total"].labels(result="failure")._value.get() == 2

    def test_record_rate_limit(self):
        metrics.record_rate_limit()
        assert metrics._metrics["login_rate_limited_total"]._value.get() == 1

    def test_record_heartbeat(self):
        metrics.record_heartbeat("server-a")
        metrics.record_heartbeat("server-a")
        metrics.record_heartbeat("server-b")
        assert metrics._metrics["heartbeats_total"].labels(worker="server-a")._value.get() == 2
        assert metrics._metrics["heartbeats_total"].labels(worker="server-b")._value.get() == 1


class TestMetricsSetup:
    """Test the setup function."""

    def test_setup_disabled_does_nothing(self):
        from unittest.mock import MagicMock

        app = MagicMock()
        orig = metrics.METRICS_ENABLED
        metrics.METRICS_ENABLED = False
        metrics.setup(app)
        app.get.assert_not_called()
        app.add_middleware.assert_not_called()
        metrics.METRICS_ENABLED = orig

    def test_normalize_path(self):
        assert metrics._normalize_path("/api/services/earnapp") == "/api/services/{slug}"
        assert metrics._normalize_path("/api/deploy/honeygain") == "/api/deploy/{slug}"
        assert metrics._normalize_path("/api/stop/mystnode") == "/api/stop/{slug}"
        assert metrics._normalize_path("/api/restart/traffmonetizer") == "/api/restart/{slug}"
        assert metrics._normalize_path("/api/remove/bitping") == "/api/remove/{slug}"
        assert metrics._normalize_path("/static/js/app.js") == "/static/{file}"
        assert metrics._normalize_path("/api/earnings") == "/api/earnings"
        assert metrics._normalize_path("/login") == "/login"


class TestRefreshGauges:
    """Test the gauge refresh logic."""

    @pytest.mark.asyncio
    async def test_refresh_gauges_with_mocked_db(self):
        orig_enabled = metrics.METRICS_ENABLED
        orig_registry = metrics._registry
        orig_metrics = metrics._metrics.copy()
        metrics.METRICS_ENABLED = True
        metrics._init_metrics()

        mock_workers = [
            {
                "status": "online",
                "name": "watchtower",
                "last_seen": "2026-01-01T00:00:00",
                "system_info": '{"docker_available": true}',
                "containers": '[{"slug": "earnapp", "status": "running", "image": "fazalfarhan01/earnapp:lite-latest", "cpu_percent": 1.2, "memory_mb": 45}]',
            },
            {
                "status": "offline",
                "name": "geiserback",
                "last_seen": "2025-12-31T00:00:00",
                "system_info": '{"docker_available": true}',
                "containers": "[]",
            },
        ]
        mock_summary = [
            {"platform": "earnapp", "balance": 5.23, "currency": "USD"},
            {"platform": "honeygain", "balance": 3.10, "currency": "USD"},
        ]
        mock_deployments = [{"slug": "earnapp"}, {"slug": "honeygain"}]
        mock_scores = [
            {"slug": "earnapp", "score": 95.0, "uptime_pct": 99.2},
            {"slug": "honeygain", "score": 80.0, "uptime_pct": 88.5},
        ]

        with (
            patch("app.database.list_workers", new_callable=AsyncMock, return_value=mock_workers),
            patch("app.database.get_earnings_summary", new_callable=AsyncMock, return_value=mock_summary),
            patch("app.database.get_deployments", new_callable=AsyncMock, return_value=mock_deployments),
            patch("app.database.get_health_scores", new_callable=AsyncMock, return_value=mock_scores),
            patch("app.exchange_rates.to_usd", side_effect=lambda amt, cur: amt),
            patch("app.catalog.get_services", return_value=[{}, {}, {}]),
        ):
            await metrics._refresh_gauges()

        m = metrics._metrics
        assert m["workers_total"].labels(status="online")._value.get() == 1
        assert m["workers_total"].labels(status="offline")._value.get() == 1
        assert m["worker_docker_available"].labels(worker="watchtower")._value.get() == 1
        assert m["worker_containers_count"].labels(worker="watchtower")._value.get() == 1
        assert m["earnings_total_usd"]._value.get() == pytest.approx(8.33)
        assert m["services_deployed_total"]._value.get() == 2
        assert m["services_available_total"]._value.get() == 3
        assert m["health_score"].labels(service="earnapp")._value.get() == 95.0
        assert m["health_uptime_percent"].labels(service="earnapp")._value.get() == 99.2
        assert m["container_cpu_percent"].labels(service="earnapp", node="watchtower")._value.get() == pytest.approx(
            1.2
        )
        assert m["container_memory_mb"].labels(service="earnapp", node="watchtower")._value.get() == 45

        metrics.METRICS_ENABLED = orig_enabled
        metrics._registry = orig_registry
        metrics._metrics = orig_metrics
