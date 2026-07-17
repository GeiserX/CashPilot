"""Tests for worker heartbeat, fleet summary, Android app support, stale-worker
purge, health-check gap detection, and login rate-limit cleanup.

Exercises /api/workers/heartbeat, /api/workers, /api/fleet/summary, the DB
migration (client_id identity, apps column), _check_stale_workers,
_run_health_check, and the login-attempt rate limiter.

Requires fastapi + httpx (installed in CI via requirements.txt).
Skipped automatically in minimal local environments.
"""

import asyncio
import os

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

try:
    from app.main import (  # noqa: E402
        _authenticate_worker_heartbeat,
        _check_login_rate,
        _check_stale_workers,
        _record_failed_login,
        _run_health_check,
        api_fleet_summary,
        api_list_workers,
        api_worker_heartbeat,
    )
except ImportError:
    pytest.skip(
        "Requires full app dependencies (fastapi, httpx, etc.) — runs in CI",
        allow_module_level=True,
    )

from time import monotonic  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

from fastapi import HTTPException  # noqa: E402

from app import main  # noqa: E402

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
    api_key_enc: str | None = None,
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
        "api_key_enc": api_key_enc,
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
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value=False),
            patch("app.main.database.upsert_worker", mock_upsert),
        ):
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
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value=False),
            patch("app.main.database.upsert_worker", mock_upsert),
        ):
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

        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value=False),
            patch("app.main.database.upsert_worker", side_effect=fake_upsert),
        ):
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


# ---------------------------------------------------------------------------
# Stale-worker purge — enrolled workers must survive long outages
# ---------------------------------------------------------------------------


class TestStaleWorkerPurge:
    def test_enrolled_worker_offline_over_1h_not_deleted(self):
        """A worker that completed enrollment (has api_key_enc) must never be
        auto-deleted, even after a long outage — deleting the row would strand
        its persisted per-worker key with no matching row, locking it out
        forever on its next heartbeat (it no longer holds the shared key)."""
        workers = [
            _worker_row(
                id=1,
                status="offline",
                last_heartbeat="2020-01-01T00:00:00",  # long past the 1h purge cutoff
                api_key_enc="encrypted-key-blob",
            ),
        ]
        mock_delete = AsyncMock()
        with (
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.database.set_worker_status", new_callable=AsyncMock),
            patch("app.main.database.delete_worker", mock_delete),
        ):
            _run(_check_stale_workers())
        mock_delete.assert_not_called()

    def test_unenrolled_worker_offline_over_1h_still_purged(self):
        """A worker that never completed enrollment (no api_key_enc) holds no
        identity worth preserving, so it is still purged after a long outage —
        the fix must not turn purging off entirely."""
        workers = [
            _worker_row(
                id=2,
                client_id="srv-2",
                name="never-enrolled",
                status="offline",
                last_heartbeat="2020-01-01T00:00:00",
                api_key_enc=None,
            ),
        ]
        mock_delete = AsyncMock()
        with (
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.database.set_worker_status", new_callable=AsyncMock),
            patch("app.main.database.delete_worker", mock_delete),
        ):
            _run(_check_stale_workers())
        mock_delete.assert_called_once_with(2)

    def test_enrolled_worker_can_reauthenticate_after_surviving_outage(self):
        """After surviving a long outage (not deleted), the worker's own
        per-worker key must still authenticate normally."""
        worker_key = "worker-own-key-abc"
        with patch(
            "app.main.database.get_worker_key_state",
            new_callable=AsyncMock,
            return_value=(worker_key, True),
        ):
            state = _run(_authenticate_worker_heartbeat(_request(worker_key), "srv-1"))
        assert state == "ok"

    def test_bad_worker_entry_does_not_abort_others(self):
        """A malformed last_heartbeat on one worker must not stop the others
        in the same batch from being processed (per-worker error boundary)."""
        bad = _worker_row(id=4, name="bad", status="online", last_heartbeat="not-a-real-timestamp")
        good = _worker_row(id=3, name="good", status="online", last_heartbeat="2020-01-01T00:00:00")
        mock_set_status = AsyncMock()
        with (
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[bad, good]),
            patch("app.main.database.set_worker_status", mock_set_status),
            patch("app.main.database.delete_worker", new_callable=AsyncMock),
        ):
            _run(_check_stale_workers())
        mock_set_status.assert_called_once_with(3, "offline")


# ---------------------------------------------------------------------------
# Health check — a service vanished entirely from the heartbeat
# ---------------------------------------------------------------------------


class TestHealthCheckVanishedService:
    def test_known_deployment_missing_from_heartbeat_gets_check_down(self):
        """A Docker-backed deployment absent from every online worker's
        current data (not merely stopped — genuinely missing) must get an
        explicit check_down so its health score reflects reality instead of
        freezing wherever it last was."""
        workers = [_worker_row(id=1, status="online", containers="[]")]
        deployments = [{"slug": "honeygain", "status": "running"}]
        mock_record = AsyncMock()
        with (
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=deployments),
            patch("app.main.database.record_health_event", mock_record),
        ):
            _run(_run_health_check())
        mock_record.assert_any_call("honeygain", "check_down", "missing from heartbeat")

    def test_external_deployment_never_flagged_missing(self):
        """External (no-container) deployments like Grass/Bytelixir are never
        reported by any worker, so they must never be flagged 'missing' —
        that would flag them as down on every single check cycle."""
        workers = [_worker_row(id=1, status="online", containers="[]")]
        deployments = [{"slug": "grass", "status": "external"}]
        mock_record = AsyncMock()
        with (
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=deployments),
            patch("app.main.database.record_health_event", mock_record),
        ):
            _run(_run_health_check())
        mock_record.assert_not_called()

    def test_fully_offline_fleet_does_not_flag_missing(self):
        """With no worker online there is no heartbeat data to trust either
        way, so a known deployment must not be flagged check_down — that
        would misreport downtime we can't actually observe."""
        workers = [_worker_row(id=1, status="offline", containers="[]")]
        deployments = [{"slug": "honeygain", "status": "running"}]
        mock_record = AsyncMock()
        with (
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=deployments),
            patch("app.main.database.record_health_event", mock_record),
        ):
            _run(_run_health_check())
        mock_record.assert_not_called()

    def test_service_present_in_heartbeat_not_double_flagged(self):
        """A service still reported by a worker must get exactly one health
        event — the normal per-instance one — never a second 'missing' event
        stacked on top of it (no double-counting)."""
        workers = [
            _worker_row(
                id=1,
                status="online",
                containers='[{"slug":"honeygain","status":"running"}]',
            )
        ]
        deployments = [{"slug": "honeygain", "status": "running"}]
        mock_record = AsyncMock()
        with (
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=deployments),
            patch("app.main.database.record_health_event", mock_record),
        ):
            _run(_run_health_check())
        mock_record.assert_called_once_with("honeygain", "check_ok")


# ---------------------------------------------------------------------------
# Login rate limiting — the attempts dict must not grow forever
# ---------------------------------------------------------------------------


class TestLoginRateLimitCleanup:
    def test_key_removed_once_attempts_age_out(self):
        """Once a client's failed-attempt timestamps all age past the
        window, its dict entry must be deleted entirely — not left behind as
        an empty list forever (the unbounded-growth bug: one key per
        distinct IP ever seen, never reclaimed)."""
        main._login_attempts.clear()
        ip = "203.0.113.5"
        main._login_attempts[ip] = [monotonic() - (main._LOGIN_WINDOW_SECONDS + 10)]
        _check_login_rate(ip)
        assert ip not in main._login_attempts

    def test_never_failed_ip_leaves_no_key(self):
        """An IP that merely checks in (e.g. a successful first-try login)
        must not leave any dict entry behind at all."""
        main._login_attempts.clear()
        ip = "203.0.113.8"
        _check_login_rate(ip)
        assert ip not in main._login_attempts

    def test_key_present_while_within_window(self):
        """A recent failed attempt is still tracked — the cleanup fix must
        not break real rate limiting."""
        main._login_attempts.clear()
        ip = "203.0.113.6"
        _record_failed_login(ip)
        _check_login_rate(ip)
        assert ip in main._login_attempts

    def test_rate_limit_still_triggers_after_cleanup_fix(self):
        """5 failed attempts within the window still 429 (behavior preserved
        by the cleanup fix)."""
        main._login_attempts.clear()
        ip = "203.0.113.7"
        for _ in range(main._LOGIN_MAX_ATTEMPTS):
            _record_failed_login(ip)
        with pytest.raises(HTTPException) as exc_info:
            _check_login_rate(ip)
        assert exc_info.value.status_code == 429
