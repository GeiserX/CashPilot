"""Tests targeting uncovered lines in app/orchestrator.py.

Covers get_status / get_status_light (running / exited / missing-container /
docker-unavailable branches and the image-matched external-container path),
_collect_stats CPU/memory parsing (including zero-delta and error edge
cases), and _find_container's label-based fallback lookup.

Mocks the Docker SDK entirely — no real Docker socket is used.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

docker = pytest.importorskip("docker")  # noqa: E402

from docker.errors import APIError, NotFound  # noqa: E402

from app import orchestrator  # noqa: E402
from app.constants import LABEL_MANAGED, LABEL_SERVICE  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_container(*, name, status, slug, deployed_by="worker", category="bandwidth", container_id="short123"):
    c = MagicMock()
    c.id = f"id-{name}"
    c.name = name
    c.status = status
    c.short_id = container_id
    c.labels = {
        LABEL_SERVICE: slug,
        LABEL_MANAGED: "true",
        "cashpilot.deployed-by": deployed_by,
        "cashpilot.category": category,
    }
    c.image.tags = [f"{slug}:latest"]
    c.image.short_id = "sha256:abcdef"
    c.attrs = {"Created": "2026-01-01T00:00:00Z"}
    return c


def _zero_stats():
    return {
        "cpu_stats": {"cpu_usage": {"total_usage": 1, "percpu_usage": [1]}, "system_cpu_usage": 10},
        "precpu_stats": {"cpu_usage": {"total_usage": 0}, "system_cpu_usage": 5},
        "memory_stats": {"usage": 0},
    }


# ---------------------------------------------------------------------------
# _collect_stats
# ---------------------------------------------------------------------------


class TestCollectStats:
    def test_parses_cpu_and_memory(self):
        c = MagicMock()
        c.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 2_000_000_000, "percpu_usage": [1, 1]},
                "system_cpu_usage": 100_000_000_000,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 1_000_000_000},
                "system_cpu_usage": 90_000_000_000,
            },
            "memory_stats": {"usage": 209_715_200},  # 200 MB
        }
        cpu_pct, mem_mb = orchestrator._collect_stats(c)
        assert cpu_pct == 20.0
        assert mem_mb == 200.0

    def test_zero_system_delta_returns_zero_cpu(self):
        c = MagicMock()
        c.stats.return_value = {
            "cpu_stats": {"cpu_usage": {"total_usage": 500, "percpu_usage": [1]}, "system_cpu_usage": 500},
            "precpu_stats": {"cpu_usage": {"total_usage": 500}, "system_cpu_usage": 500},
            "memory_stats": {"usage": 0},
        }
        cpu_pct, mem_mb = orchestrator._collect_stats(c)
        assert cpu_pct == 0.0
        assert mem_mb == 0.0

    def test_missing_memory_usage_defaults_to_zero(self):
        c = MagicMock()
        c.stats.return_value = {
            "cpu_stats": {"cpu_usage": {"total_usage": 100, "percpu_usage": [1]}, "system_cpu_usage": 500},
            "precpu_stats": {"cpu_usage": {"total_usage": 50}, "system_cpu_usage": 400},
            "memory_stats": {},  # no "usage" key
        }
        _, mem_mb = orchestrator._collect_stats(c)
        assert mem_mb == 0.0

    def test_missing_key_returns_zero_tuple(self):
        c = MagicMock()
        c.stats.return_value = {"cpu_stats": {}}  # precpu_stats missing -> KeyError
        assert orchestrator._collect_stats(c) == (0.0, 0.0)

    def test_stats_api_error_returns_zero_tuple(self):
        c = MagicMock()
        c.stats.side_effect = APIError("stats unavailable")
        assert orchestrator._collect_stats(c) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# _find_container
# ---------------------------------------------------------------------------


class TestFindContainer:
    def test_finds_by_name(self):
        container = MagicMock()
        client = MagicMock()
        client.containers.get.return_value = container
        with patch.object(orchestrator, "_get_client", return_value=client):
            result = orchestrator._find_container("honeygain")
        assert result is container
        client.containers.get.assert_called_once_with("cashpilot-honeygain")
        client.containers.list.assert_not_called()

    def test_falls_back_to_label_lookup_when_renamed(self):
        container = MagicMock()
        client = MagicMock()
        client.containers.get.side_effect = NotFound("nope")
        client.containers.list.return_value = [container]
        with patch.object(orchestrator, "_get_client", return_value=client):
            result = orchestrator._find_container("honeygain")
        assert result is container
        _, kwargs = client.containers.list.call_args
        assert kwargs["filters"]["label"] == [
            f"{LABEL_SERVICE}=honeygain",
            f"{LABEL_MANAGED}=true",
        ]

    def test_raises_value_error_when_not_found_anywhere(self):
        client = MagicMock()
        client.containers.get.side_effect = NotFound("nope")
        client.containers.list.return_value = []
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(ValueError, match="honeygain"),
        ):
            orchestrator._find_container("honeygain")


# ---------------------------------------------------------------------------
# get_status (slow path, includes CPU/mem stats)
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_docker_unavailable_returns_empty(self):
        with patch.object(orchestrator, "_get_client", side_effect=RuntimeError("no socket")):
            assert orchestrator.get_status() == []

    def test_running_container_reports_stats(self):
        container = _mock_container(name="cashpilot-honeygain", status="running", slug="honeygain")
        container.stats.return_value = {
            "cpu_stats": {"cpu_usage": {"total_usage": 100, "percpu_usage": [1]}, "system_cpu_usage": 500},
            "precpu_stats": {"cpu_usage": {"total_usage": 50}, "system_cpu_usage": 400},
            "memory_stats": {"usage": 1_048_576},
        }
        client = MagicMock()
        client.containers.list.return_value = [container]
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value={}),
        ):
            results = orchestrator.get_status()
        assert len(results) == 1
        row = results[0]
        assert row["slug"] == "honeygain"
        assert row["status"] == "running"
        assert row["memory_mb"] == 1.0

    def test_exited_container_missing_stats_handled_gracefully(self):
        container = _mock_container(name="cashpilot-earnapp", status="exited", slug="earnapp")
        container.stats.side_effect = APIError("exited, no stats")
        client = MagicMock()
        client.containers.list.return_value = [container]
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value={}),
        ):
            results = orchestrator.get_status()
        assert results[0]["status"] == "exited"
        assert results[0]["cpu_percent"] == 0.0
        assert results[0]["memory_mb"] == 0.0

    def test_corrupted_container_is_skipped_not_crashed(self):
        good = _mock_container(name="cashpilot-honeygain", status="running", slug="honeygain")
        good.stats.return_value = _zero_stats()
        bad = MagicMock()
        bad.id = "bad-id"
        bad.short_id = "bad12"
        bad.labels.get.side_effect = RuntimeError("corrupted container labels")
        client = MagicMock()
        client.containers.list.return_value = [bad, good]
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value={}),
        ):
            results = orchestrator.get_status()
        assert len(results) == 1
        assert results[0]["slug"] == "honeygain"

    def test_image_matched_external_container_included(self):
        external = MagicMock()
        external.id = "ext-1"
        external.name = "manually-run-storj"
        external.status = "running"
        external.image.tags = ["storjlabs/storagenode:latest"]
        external.short_id = "ext1"
        external.attrs = {"Created": "2026-01-01T00:00:00Z"}
        external.stats.return_value = _zero_stats()
        client = MagicMock()
        client.containers.list.side_effect = [[], [external]]
        image_map = {"storjlabs/storagenode:latest": "storj"}
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value=image_map),
        ):
            results = orchestrator.get_status()
        assert len(results) == 1
        assert results[0]["slug"] == "storj"
        assert results[0]["deployed_by"] == "external"

    def test_all_containers_listing_failure_still_returns_labeled(self):
        labeled = _mock_container(name="cashpilot-honeygain", status="running", slug="honeygain")
        labeled.stats.return_value = _zero_stats()
        client = MagicMock()
        client.containers.list.side_effect = [[labeled], Exception("docker daemon hiccup")]
        image_map = {"some/image:latest": "svc"}
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value=image_map),
        ):
            results = orchestrator.get_status()
        assert len(results) == 1
        assert results[0]["slug"] == "honeygain"


# ---------------------------------------------------------------------------
# get_status_light (fast path, no CPU/mem stats)
# ---------------------------------------------------------------------------


class TestGetStatusLight:
    def test_docker_unavailable_returns_empty(self):
        with patch.object(orchestrator, "_get_client", side_effect=RuntimeError("no socket")):
            assert orchestrator.get_status_light() == []

    def test_no_stats_call_even_when_running(self):
        container = _mock_container(name="cashpilot-honeygain", status="running", slug="honeygain")
        client = MagicMock()
        client.containers.list.return_value = [container]
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value={}),
        ):
            results = orchestrator.get_status_light()
        assert results[0]["cpu_percent"] == 0.0
        assert results[0]["memory_mb"] == 0.0
        container.stats.assert_not_called()

    def test_image_matched_container_skipped_when_slug_already_seen(self):
        labeled = _mock_container(name="cashpilot-honeygain", status="running", slug="honeygain")
        dup = MagicMock()
        dup.id = "dup-id"
        dup.image.tags = ["honeygain/desktop:latest"]
        client = MagicMock()
        client.containers.list.side_effect = [[labeled], [dup]]
        image_map = {"honeygain/desktop:latest": "honeygain"}
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value=image_map),
        ):
            results = orchestrator.get_status_light()
        # The duplicate slug from the image-matched scan must not be added again.
        assert len(results) == 1

    def test_all_containers_listing_failure_handled(self):
        labeled = _mock_container(name="cashpilot-honeygain", status="running", slug="honeygain")
        client = MagicMock()
        client.containers.list.side_effect = [[labeled], Exception("boom")]
        image_map = {"x": "y"}
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value=image_map),
        ):
            results = orchestrator.get_status_light()
        assert len(results) == 1
