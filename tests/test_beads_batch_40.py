"""CashPilot-zdi: a container nobody could measure reported 0.00% CPU.

``_collect_stats`` returned ``(0.0, 0.0, None, None)`` when the Docker stats
call failed. The network counters were None because a failed read is not
evidence of no traffic — the docstring right above says so — and exactly the
same argument applies to CPU and memory, which were reporting a confident
0.00% / 0.0 MB for a container that may be working hard.

One ``return`` statement, two kinds of unknown, reported two different ways.

Fixing the source meant fixing every consumer, because ``.get(key, 0)`` does not
help when the key EXISTS with value None:

* the per-service aggregate summed it as zero, dragging the average down;
* /metrics published a flat zero line instead of a gap;
* the running-costs estimate billed it as an idle container;
* the dashboard rendered ``|| '0'`` as ``0%``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestAFailedStatsReadIsUnknown:
    def test_an_api_error_reports_nothing(self):
        from docker.errors import APIError

        from app import orchestrator

        c = MagicMock()
        c.stats.side_effect = APIError("stats unavailable")
        assert orchestrator._collect_stats(c) == (None, None, None, None)

    def test_a_malformed_payload_reports_nothing(self):
        from app import orchestrator

        c = MagicMock()
        c.stats.return_value = {"cpu_stats": {}}
        assert orchestrator._collect_stats(c) == (None, None, None, None)

    def test_a_successful_read_still_reports_numbers(self):
        """The control. Without it this passes by never measuring anything."""
        from app import orchestrator

        c = MagicMock()
        c.stats.return_value = {
            "cpu_stats": {"cpu_usage": {"total_usage": 200, "percpu_usage": [1]}, "system_cpu_usage": 1000},
            "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 500},
            "memory_stats": {"usage": 52428800},
        }
        cpu, mem, _, _ = orchestrator._collect_stats(c)
        assert cpu is not None and cpu > 0
        assert mem == pytest.approx(50.0)

    def test_a_genuine_zero_is_still_zero(self):
        """An idle container measured at 0% must stay distinguishable."""
        from app import orchestrator

        c = MagicMock()
        c.stats.return_value = {
            "cpu_stats": {"cpu_usage": {"total_usage": 100, "percpu_usage": [1]}, "system_cpu_usage": 500},
            "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 500},
            "memory_stats": {"usage": 0},
        }
        cpu, mem, _, _ = orchestrator._collect_stats(c)
        assert cpu == 0.0
        assert mem == 0.0


class TestTheAggregateDoesNotCountUnknownAsZero:
    def _rows(self, instances):
        import asyncio
        from unittest.mock import AsyncMock

        from app import main

        with (
            patch.object(main, "_require_auth_api", lambda r: None),
            patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=instances)),
            patch.object(main.database, "get_deployments", AsyncMock(return_value=[])),
            patch.object(main.database, "get_earnings_summary", AsyncMock(return_value=[])),
            patch.object(main.database, "get_config", AsyncMock(return_value={})),
            patch.object(main.database, "get_health_scores", AsyncMock(return_value={})),
            patch.object(main.catalog, "get_service", lambda slug: {"name": "Honeygain", "slug": slug}),
        ):
            return asyncio.run(main.api_services_deployed(MagicMock()))

    def _instance(self, cpu, mem, node="watchtower"):
        return {
            "slug": "honeygain",
            "name": "honeygain",
            "status": "running",
            "cpu_percent": cpu,
            "memory_mb": mem,
            "deployed_by": node,
            "_node": node,
            "_worker_id": 1,
            "_has_docker": True,
            "_is_android": False,
        }

    def test_a_wholly_unmeasured_service_reports_no_figure(self):
        row = self._rows([self._instance(None, None)])[0]
        assert row["cpu"] is None
        assert row["memory"] is None

    def test_it_says_how_many_were_unmeasured(self):
        row = self._rows([self._instance(None, None), self._instance(None, None, "b")])[0]
        assert row["stats_unknown"] == 2

    def test_a_measured_service_still_reports_one(self):
        """The control: this must not blank out working containers."""
        row = self._rows([self._instance(12.5, 100.0)])[0]
        assert row["cpu"] == "12.50"
        assert row["memory"] == "100.0 MB"
        assert row["stats_unknown"] == 0

    def test_a_mixed_service_totals_only_what_was_measured(self):
        """Summing the unknown as 0 is what dragged the average down."""
        row = self._rows([self._instance(10.0, 100.0), self._instance(None, None, "b")])[0]
        assert row["cpu"] == "10.00"
        assert row["stats_unknown"] == 1

    def test_the_per_instance_rows_carry_the_same_distinction(self):
        rows = self._rows([self._instance(None, None)])[0]["instance_details"]
        assert rows[0]["cpu"] is None
        assert rows[0]["memory"] is None


class TestNothingDownstreamFabricatesAZero:
    def test_metrics_skips_unmeasured_containers(self):
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "app" / "metrics.py").read_text(encoding="utf-8")
        assert "if cpu is not None and mem is not None" in source, (
            "/metrics would publish a flat zero line for a container nobody could measure"
        )

    def test_power_estimation_skips_them(self):
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
        assert 'if c.get("cpu_percent") is None:' in source, (
            "an unmeasurable container would be billed as idle in the running-costs estimate"
        )

    def test_the_dashboard_renders_a_dash(self):
        import re
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
        code = "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in source.splitlines())
        assert "svc.cpu || '0'" not in code, "the main row still renders unknown as 0%"
        assert "inst.cpu || '0'" not in code, "the instance row still renders unknown as 0%"

    def test_the_average_divides_by_what_was_measured(self):
        import re
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
        code = "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in source.splitlines())
        assert "instances - (svc.stats_unknown || 0)" in code
