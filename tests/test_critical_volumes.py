"""Tests for the critical-volume delete guard (CashPilot-efx).

`remove_service(..., delete_volumes=True)` force-deletes named volumes. It is the
only genuinely irreversible path in the codebase: node identities, keystores and
generated wallets have no server-side copy, so a mistake cannot be undone by
redeploying. These tests pin the refusal, the override, and — importantly — that
nothing is destroyed when the guard fires.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

# Must be set before app.worker_api is imported: with no key configured the
# worker refuses every request, so this module would otherwise pass only when
# some other test module happened to be collected first and set it.
os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest

from app import catalog, orchestrator


def _container(mounts):
    c = MagicMock()
    c.name = "cashpilot-storj"
    c.attrs = {"Mounts": mounts}
    return c


def _volume_mount(name, destination):
    return {"Type": "volume", "Name": name, "Destination": destination}


class TestCatalogDeclaration:
    def test_critical_targets_are_read_from_yaml_not_hardcoded(self):
        targets = catalog.critical_volume_targets("storj")
        assert set(targets) == {"/app/identity", "/app/config"}
        assert "proof-of-work" in targets["/app/identity"]

    def test_service_without_critical_volumes_returns_empty_not_none(self):
        # Empty means "catalog read, nothing critical"; None means "unknown".
        assert catalog.critical_volume_targets("honeygain") == {}

    def test_unknown_slug_is_unknown_not_empty(self):
        assert catalog.critical_volume_targets("no-such-service") is None

    def test_every_declared_target_matches_a_real_mount(self):
        """A typo in `target` would silently protect nothing."""
        for svc in catalog.get_services():
            docker = svc.get("docker") or {}
            declared = [e["target"] for e in (docker.get("critical_volumes") or [])]
            if not declared:
                continue
            mounted = {v.split(":", 1)[1].split(":")[0] for v in (docker.get("volumes") or []) if ":" in v}
            for target in declared:
                assert target in mounted, (
                    f"{svc['slug']}: critical_volumes target {target!r} is not in volumes {sorted(mounted)}"
                )


class TestRemoveGuard:
    def test_critical_volume_delete_is_refused(self):
        container = _container([_volume_mount("storj-identity", "/app/identity")])
        with (
            patch.object(orchestrator, "_find_container", return_value=container),
            pytest.raises(orchestrator.CriticalVolumeError) as exc,
        ):
            orchestrator.remove_service("storj", delete_volumes=True)

        assert exc.value.blocked[0]["target"] == "/app/identity"
        assert "proof-of-work" in exc.value.blocked[0]["holds"]

    def test_nothing_is_destroyed_when_the_guard_fires(self):
        """The refusal must happen BEFORE the container is removed."""
        container = _container([_volume_mount("storj-identity", "/app/identity")])
        client = MagicMock()
        with (
            patch.object(orchestrator, "_find_container", return_value=container),
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(orchestrator.CriticalVolumeError),
        ):
            orchestrator.remove_service("storj", delete_volumes=True)

        container.remove.assert_not_called()
        client.volumes.get.assert_not_called()

    def test_explicit_override_allows_the_delete(self):
        container = _container([_volume_mount("storj-identity", "/app/identity")])
        client = MagicMock()
        with (
            patch.object(orchestrator, "_find_container", return_value=container),
            patch.object(orchestrator, "_get_client", return_value=client),
        ):
            result = orchestrator.remove_service("storj", delete_volumes=True, allow_delete_critical=True)

        container.remove.assert_called_once()
        assert result["deleted_volumes"] == ["storj-identity"]

    def test_non_critical_volume_is_unaffected(self):
        container = _container([_volume_mount("honeygain-data", "/data")])
        client = MagicMock()
        with (
            patch.object(orchestrator, "_find_container", return_value=container),
            patch.object(orchestrator, "_get_client", return_value=client),
        ):
            result = orchestrator.remove_service("honeygain", delete_volumes=True)

        assert result["deleted_volumes"] == ["honeygain-data"]

    def test_unknown_service_fails_closed(self):
        """A catalog-less build must not silently permit an irreversible delete."""
        container = _container([_volume_mount("mystery-data", "/data")])
        with (
            patch.object(orchestrator, "_find_container", return_value=container),
            pytest.raises(orchestrator.CriticalVolumeError) as exc,
        ):
            orchestrator.remove_service("not-in-catalog", delete_volumes=True)

        assert "not in the catalog" in exc.value.blocked[0]["holds"]

    def test_bind_mounts_are_never_deleted(self):
        container = _container([{"Type": "bind", "Source": "/mnt/user/data", "Destination": "/app/config"}])
        client = MagicMock()
        with (
            patch.object(orchestrator, "_find_container", return_value=container),
            patch.object(orchestrator, "_get_client", return_value=client),
        ):
            result = orchestrator.remove_service("storj", delete_volumes=True)

        # A bind mount is the host's data; Docker will not delete it and neither
        # do we, so there is nothing to guard and nothing to remove.
        assert result["deleted_volumes"] == []
        container.remove.assert_called_once()

    def test_removal_without_delete_volumes_is_never_blocked(self):
        container = _container([_volume_mount("storj-identity", "/app/identity")])
        with patch.object(orchestrator, "_find_container", return_value=container):
            result = orchestrator.remove_service("storj", delete_volumes=False)

        container.remove.assert_called_once()
        assert result["deleted_volumes"] == []


class TestCatalogRobustness:
    def test_malformed_entries_are_skipped_not_crashed_on(self):
        """A hand-edited YAML must not take the worker down."""
        bad = {
            "slug": "bad-svc",
            "docker": {"critical_volumes": ["not-a-mapping", {"holds": "no target"}, {"target": "/keep"}]},
        }
        with patch.object(catalog, "get_service", return_value=bad):
            assert catalog.critical_volume_targets("bad-svc") == {"/keep": "Irreplaceable service state."}


class TestWorkerEndpoint:
    """The refusal must reach the caller as a 409 carrying the reason."""

    def _client(self):
        from contextlib import asynccontextmanager

        from fastapi.testclient import TestClient

        from app import worker_api

        @asynccontextmanager
        async def _noop(app):
            yield

        worker_api.app.router.lifespan_context = _noop
        return TestClient(worker_api.app, raise_server_exceptions=False), worker_api

    def test_blocked_delete_returns_409_with_the_reason(self):
        client, worker_api = self._client()
        blocked = [{"volume": "storj-identity", "target": "/app/identity", "holds": "Node identity."}]
        err = orchestrator.CriticalVolumeError("storj", blocked)

        with patch("app.worker_api.orchestrator.remove_service", side_effect=err):
            resp = client.delete(
                "/api/containers/storj?delete_volumes=true",
                headers={"Authorization": f"Bearer {worker_api.API_KEY}"},
            )

        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["error"] == "critical_volume"
        assert detail["blocked"] == blocked
        assert "allow_delete_critical" in detail["hint"]

    def test_override_is_forwarded_to_the_orchestrator(self):
        client, worker_api = self._client()
        removal = {"container": "cashpilot-storj", "deleted_volumes": [], "failed_volumes": []}

        with patch("app.worker_api.orchestrator.remove_service", return_value=removal) as mock:
            resp = client.delete(
                "/api/containers/storj?delete_volumes=true&allow_delete_critical=true",
                headers={"Authorization": f"Bearer {worker_api.API_KEY}"},
            )

        assert resp.status_code == 200
        mock.assert_called_once_with("storj", delete_volumes=True, allow_delete_critical=True)


class TestSafeWorkerDetail:
    """The UI must forward the reason without becoming a generic error relay."""

    def _resp(self, payload):
        r = MagicMock()
        r.json.return_value = payload
        return r

    def test_critical_volume_detail_is_forwarded_and_sanitised(self):
        from app.main import _safe_worker_detail

        detail = _safe_worker_detail(
            self._resp(
                {
                    "detail": {
                        "error": "critical_volume",
                        "message": "no",
                        "hint": "back up first",
                        "blocked": [{"volume": "v", "target": "/t", "holds": "h", "secret": "leak"}],
                    }
                }
            )
        )
        assert detail["blocked"] == [{"volume": "v", "target": "/t", "holds": "h"}]
        assert "secret" not in detail["blocked"][0]

    def test_other_worker_errors_stay_generic(self):
        from app.main import _safe_worker_detail

        assert _safe_worker_detail(self._resp({"detail": {"error": "something_else", "blocked": []}})) is None
        assert _safe_worker_detail(self._resp({"detail": "plain string"})) is None
        assert _safe_worker_detail(self._resp({})) is None

    def test_non_json_body_is_not_forwarded(self):
        from app.main import _safe_worker_detail

        r = MagicMock()
        r.json.side_effect = ValueError("not json")
        assert _safe_worker_detail(r) is None

    def test_malformed_blocked_list_is_not_forwarded(self):
        from app.main import _safe_worker_detail

        assert _safe_worker_detail(self._resp({"detail": {"error": "critical_volume", "blocked": "nope"}})) is None


class TestOverrideAuthorization:
    """Destroying irreplaceable state must not be easier than deploying."""

    def test_override_requires_owner_not_merely_writer(self):
        from fastapi import HTTPException

        from app import main

        calls = []

        def _writer_ok(request):
            calls.append("writer")

        def _owner_denied(request):
            calls.append("owner")
            raise HTTPException(status_code=403, detail="owner required")

        with (
            patch.object(main, "_require_writer", _writer_ok),
            patch.object(main, "_require_owner", _owner_denied),
            pytest.raises(HTTPException) as exc,
        ):
            import asyncio

            asyncio.run(
                main._svc_remove(
                    request=MagicMock(), slug="storj", worker_id=1, delete_volumes=True, allow_delete_critical=True
                )
            )

        assert exc.value.status_code == 403
        assert "owner" in calls

    def test_ordinary_removal_still_only_needs_writer(self):
        from app import main

        owner_checked = []

        async def _resolve(worker_id):
            return 1

        async def _proxy(worker_id, command, slug, params=None):
            return {"status": "removed"}

        with (
            patch.object(main, "_require_writer", lambda r: None),
            patch.object(main, "_require_owner", lambda r: owner_checked.append(1)),
            patch.object(main, "_resolve_worker_id", _resolve),
            patch.object(main, "_proxy_worker_command", _proxy),
            patch.object(main.database, "remove_deployment", AsyncMock()),
            patch.object(main.database, "record_health_event", AsyncMock()),
        ):
            import asyncio

            asyncio.run(main._svc_remove(request=MagicMock(), slug="honeygain", worker_id=1, delete_volumes=True))

        assert owner_checked == [], "a normal delete must not suddenly require owner"
