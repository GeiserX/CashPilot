"""Tests for the critical-volume delete guard (CashPilot-efx).

`remove_service(..., delete_volumes=True)` force-deletes named volumes. It is the
only genuinely irreversible path in the codebase: node identities, keystores and
generated wallets have no server-side copy, so a mistake cannot be undone by
redeploying. These tests pin the refusal, the override, and — importantly — that
nothing is destroyed when the guard fires.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
