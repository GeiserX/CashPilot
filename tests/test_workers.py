"""Tests for worker heartbeat, fleet summary, and Android app support.

Exercises /api/workers/heartbeat, /api/workers, /api/fleet/summary, and
the DB migration (client_id identity, apps column).

Requires fastapi + httpx (installed in CI via requirements.txt).
Skipped automatically in minimal local environments.
"""

import asyncio
import os

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

try:
    from app.main import (  # noqa: E402
        api_fleet_summary,
        api_list_workers,
        api_worker_heartbeat,
    )
except ImportError:
    pytest.skip(
        "Requires full app dependencies (fastapi, httpx, etc.) — runs in CI",
        allow_module_level=True,
    )

from types import SimpleNamespace  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FLEET_KEY = "test-fleet-key"


def _request(api_key: str = FLEET_KEY):
    """Build a fake Request with Authorization header."""
    req = MagicMock()
    req.headers = {"Authorization": f"Bearer {api_key}"}
    return req


def _worker_row(
    *,
    id: int = 1,
    client_id: str = "srv-1",
    name: str = "server-1",
    url: str = "",
    status: str = "online",
    containers: str = "[]",
    apps: str = "[]",
    system_info: str = "{}",
    last_heartbeat: str = "2026-04-04T12:00:00",
    registered_at: str = "2026-04-01T00:00:00",
):
    return {
        "id": id,
        "client_id": client_id,
        "name": name,
        "url": url,
        "status": status,
        "containers": containers,
        "apps": apps,
        "system_info": system_info,
        "last_heartbeat": last_heartbeat,
        "registered_at": registered_at,
    }


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Heartbeat — client_id identity
# ---------------------------------------------------------------------------


class TestHeartbeatClientId:
    def test_client_id_passed_to_upsert(self):
        """When client_id is provided, it's used as the worker identity."""
        mock_upsert = AsyncMock(return_value=42)
        with patch("app.main.database.upsert_worker", mock_upsert):
            result = _run(
                api_worker_heartbeat(
                    _request(),
                    SimpleNamespace(
                        name="My Phone",
                        url="",
                        client_id="android-abc123",
                        containers=[],
                        apps=[{"slug": "honeygain", "running": True}],
                        system_info={"device_type": "android"},
                    ),
                )
            )
        assert result == {"status": "ok", "worker_id": 42}
        call_kwargs = mock_upsert.call_args.kwargs
        assert call_kwargs["client_id"] == "android-abc123"
        assert call_kwargs["name"] == "My Phone"

    def test_fallback_to_name_when_no_client_id(self):
        """Old workers that don't send client_id get name used as identity."""
        mock_upsert = AsyncMock(return_value=7)
        with patch("app.main.database.upsert_worker", mock_upsert):
            result = _run(
                api_worker_heartbeat(
                    _request(),
                    SimpleNamespace(
                        name="watchtower",
                        url="",
                        client_id="",
                        containers=[{"slug": "honeygain", "status": "running"}],
                        apps=[],
                        system_info={"docker_available": True},
                    ),
                )
            )
        assert result["status"] == "ok"
        assert mock_upsert.call_args.kwargs["client_id"] == "watchtower"

    def test_two_devices_same_name_different_client_id(self):
        """Two devices with the same display name but different client_ids are separate."""
        calls = []

        async def fake_upsert(**kwargs):
            calls.append(kwargs)
            return len(calls)

        with patch("app.main.database.upsert_worker", side_effect=fake_upsert):
            _run(
                api_worker_heartbeat(
                    _request(),
                    SimpleNamespace(
                        name="Samsung S24",
                        url="",
                        client_id="device-aaa",
                        containers=[],
                        apps=[],
                        system_info={},
                    ),
                )
            )
            _run(
                api_worker_heartbeat(
                    _request(),
                    SimpleNamespace(
                        name="Samsung S24",
                        url="",
                        client_id="device-bbb",
                        containers=[],
                        apps=[],
                        system_info={},
                    ),
                )
            )
        assert len(calls) == 2
        assert calls[0]["client_id"] == "device-aaa"
        assert calls[1]["client_id"] == "device-bbb"
        # Both have same display name
        assert calls[0]["name"] == calls[1]["name"] == "Samsung S24"


# ---------------------------------------------------------------------------
# Fleet summary — online-only and Android counting
# ---------------------------------------------------------------------------


class TestFleetSummary:
    def test_only_online_workers_counted(self):
        """Offline workers should not inflate container/running counts."""
        workers = [
            _worker_row(
                id=1,
                status="online",
                containers='[{"slug":"hg","status":"running"}]',
            ),
            _worker_row(
                id=2,
                client_id="srv-2",
                name="offline-server",
                status="offline",
                containers='[{"slug":"earnapp","status":"running"},{"slug":"repocket","status":"running"}]',
            ),
        ]
        with (
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "t", "r": "owner"}),
        ):
            result = _run(api_fleet_summary(_request()))
        assert result["total_workers"] == 2
        assert result["online_workers"] == 1
        assert result["total_containers"] == 1
        assert result["running_containers"] == 1

    def test_android_apps_counted(self):
        """Android apps should be counted as services in the fleet summary."""
        workers = [
            _worker_row(
                id=1,
                status="online",
                system_info='{"device_type":"android"}',
                containers="[]",
                apps='[{"slug":"honeygain","running":true},{"slug":"earnapp","running":false}]',
            ),
        ]
        with (
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "t", "r": "owner"}),
        ):
            result = _run(api_fleet_summary(_request()))
        assert result["total_containers"] == 2
        assert result["running_containers"] == 1

    def test_malformed_json_does_not_crash(self):
        """A worker with corrupted JSON should be skipped, not 500."""
        workers = [
            _worker_row(
                id=1,
                status="online",
                system_info="NOT VALID JSON",
                containers="NOT VALID JSON",
            ),
        ]
        with (
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "t", "r": "owner"}),
        ):
            result = _run(api_fleet_summary(_request()))
        # Should not crash — malformed rows degrade gracefully
        assert result["online_workers"] == 1
        assert result["total_containers"] == 0


# ---------------------------------------------------------------------------
# Worker list — Android fields
# ---------------------------------------------------------------------------


class TestWorkerList:
    def test_android_worker_returns_apps(self):
        """Android workers should have apps parsed and counted."""
        workers = [
            _worker_row(
                id=1,
                status="online",
                system_info='{"device_type":"android","os":"Android"}',
                containers="[]",
                apps='[{"slug":"honeygain","running":true},{"slug":"repocket","running":true}]',
            ),
        ]
        with (
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "t", "r": "owner"}),
        ):
            result = _run(api_list_workers(_request()))
        w = result[0]
        assert isinstance(w["apps"], list)
        assert len(w["apps"]) == 2
        assert w["container_count"] == 2
        assert w["running_count"] == 2

    def test_docker_worker_counts_containers(self):
        """Docker workers should count containers, not apps."""
        workers = [
            _worker_row(
                id=1,
                status="online",
                system_info='{"docker_available":true}',
                containers='[{"slug":"honeygain","status":"running"},{"slug":"earnapp","status":"stopped"}]',
                apps="[]",
            ),
        ]
        with (
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "t", "r": "owner"}),
        ):
            result = _run(api_list_workers(_request()))
        w = result[0]
        assert w["container_count"] == 2
        assert w["running_count"] == 1
