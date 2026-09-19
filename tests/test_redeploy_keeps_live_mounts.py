"""A redeploy must not move a node's data to another place on its own.

Seen live: a mysterium container kept its keystore in a bind-mounted directory
that no deployment record described. A dashboard redeploy rebuilt it from the
catalog, mounted the ``mysterium-data`` volume at the same target, and the node
came up with a different identity. The record could not have prevented it: it
is one row per service for the whole fleet, and this container had been edited
by hand. The running container is the only thing that knows where its data is,
so the worker asks it.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app import orchestrator

TARGET = "/var/lib/mysterium-node"
CATALOG_VOLUMES = {"mysterium-data": {"bind": TARGET, "mode": "rw"}}


def _old(mounts):
    old = MagicMock()
    old.attrs = {"Mounts": mounts}
    return old


def _bind(source, destination=TARGET):
    return {"Type": "bind", "Source": source, "Destination": destination}


def _volume(name, destination=TARGET):
    return {
        "Type": "volume",
        "Name": name,
        "Source": f"/var/lib/docker/volumes/{name}/_data",
        "Destination": destination,
    }


def _deploy(old, **kwargs):
    container = MagicMock()
    container.id = "cid"
    client = MagicMock()
    if old is None:
        client.containers.get.side_effect = orchestrator.NotFound("nope")
    else:
        client.containers.get.return_value = old
    client.containers.run.return_value = container
    kept: list[dict[str, str]] = []
    with patch.object(orchestrator, "_get_client", return_value=client):
        orchestrator.deploy_raw(slug="mysterium", image="img", kept_mounts=kept, **kwargs)
    return client.containers.run.call_args.kwargs["volumes"], kept


class TestTheRunningContainerDecidesWhereItsDataLives:
    def test_a_bind_mount_the_spec_does_not_know_survives_a_redeploy(self):
        volumes, kept = _deploy(_old([_bind("/mnt/user/appdata/myst/data")]), volumes=CATALOG_VOLUMES)
        assert volumes == [f"/mnt/user/appdata/myst/data:{TARGET}:rw"]
        assert kept == [{"target": TARGET, "kept": "/mnt/user/appdata/myst/data", "requested": "mysterium-data"}]

    def test_a_differently_named_volume_survives_too(self):
        volumes, _ = _deploy(_old([_volume("myst-identity")]), volumes=CATALOG_VOLUMES)
        assert volumes == [f"myst-identity:{TARGET}:rw"]

    def test_a_trailing_slash_does_not_hide_the_mount(self):
        spec = {"mysterium-data": {"bind": TARGET + "/", "mode": "rw"}}
        volumes, _ = _deploy(_old([_bind("/srv/myst")]), volumes=spec)
        assert volumes == [f"/srv/myst:{TARGET}/:rw"]

    def test_a_read_only_mount_stays_read_only(self):
        live = {**_bind("/srv/myst"), "Mode": "ro", "RW": False}
        volumes, _ = _deploy(_old([live]), volumes=CATALOG_VOLUMES)
        assert volumes == [f"/srv/myst:{TARGET}:ro"]

    def test_read_only_survives_even_when_the_source_is_the_same(self):
        live = {**_volume("mysterium-data"), "Mode": "ro", "RW": False}
        volumes, kept = _deploy(_old([live]), volumes=CATALOG_VOLUMES)
        assert volumes == [f"mysterium-data:{TARGET}:ro"]
        assert len(kept) == 1

    def test_two_targets_on_one_source_both_survive(self):
        """A dict keyed by source dropped one, and that target came up empty."""
        spec = {
            "catalog-a": {"bind": "/app/identity", "mode": "rw"},
            "catalog-b": {"bind": "/app/config", "mode": "rw"},
        }
        old = _old([_bind("/srv/storj", "/app/identity"), _bind("/srv/storj", "/app/config")])
        volumes, kept = _deploy(old, volumes=spec)
        assert sorted(volumes) == ["/srv/storj:/app/config:rw", "/srv/storj:/app/identity:rw"]
        assert len(kept) == 2

    def test_a_kept_source_equal_to_another_requested_one_drops_nothing(self):
        spec = {
            "catalog-a": {"bind": "/app/identity", "mode": "rw"},
            "/srv/storj": {"bind": "/app/config", "mode": "rw"},
        }
        volumes, _ = _deploy(_old([_bind("/srv/storj", "/app/identity")]), volumes=spec)
        assert sorted(volumes) == ["/srv/storj:/app/config:rw", "/srv/storj:/app/identity:rw"]

    def test_the_old_container_is_still_replaced(self):
        old = _old([_bind("/srv/myst")])
        _deploy(old, volumes=CATALOG_VOLUMES)
        old.remove.assert_called_once_with(force=True)


class TestTheOldContainerGetsToShutDown:
    """A redeploy used to SIGKILL it; stop and restart already honoured the timeout."""

    def test_it_is_stopped_with_the_catalog_timeout_before_it_is_removed(self):
        old = _old([])
        calls = MagicMock()
        calls.attach_mock(old.stop, "stop")
        calls.attach_mock(old.remove, "remove")
        with patch.object(orchestrator, "_get_stop_timeout", return_value=300):
            _deploy(old)
        assert [c[0] for c in calls.mock_calls] == ["stop", "remove"]
        old.stop.assert_called_once_with(timeout=300)

    def test_a_stop_that_fails_does_not_abandon_the_deploy(self):
        old = _old([])
        old.stop.side_effect = orchestrator.APIError("daemon said no")
        _deploy(old)
        old.remove.assert_called_once_with(force=True)


class TestItOnlyKeepsWhatIsThere:
    def test_the_same_mount_is_not_reported_as_kept(self):
        volumes, kept = _deploy(_old([_volume("mysterium-data")]), volumes=CATALOG_VOLUMES)
        assert volumes == CATALOG_VOLUMES
        assert kept == []

    def test_a_first_deploy_uses_the_spec(self):
        volumes, kept = _deploy(None, volumes=CATALOG_VOLUMES)
        assert volumes == CATALOG_VOLUMES
        assert kept == []

    def test_a_mount_the_catalog_added_since_is_added(self):
        spec = {**CATALOG_VOLUMES, "myst-logs": {"bind": "/var/log/myst", "mode": "rw"}}
        volumes, _ = _deploy(_old([_bind("/srv/myst")]), volumes=spec)
        assert volumes == [f"/srv/myst:{TARGET}:rw", "myst-logs:/var/log/myst:rw"]

    def test_a_mount_at_another_target_is_not_pulled_in(self):
        volumes, kept = _deploy(_old([_bind("/etc/localtime", "/etc/localtime")]), volumes=CATALOG_VOLUMES)
        assert volumes == CATALOG_VOLUMES
        assert kept == []


class TestTheOperatorCanStillMoveIt:
    def test_a_path_typed_this_deploy_wins(self):
        spec = {"/new/identity": {"bind": "/app/identity", "mode": "rw"}}
        volumes, kept = _deploy(
            _old([_bind("/old/identity", "/app/identity")]), volumes=spec, moved_mounts=["/app/identity"]
        )
        assert volumes == spec
        assert kept == []

    def test_moving_one_mount_keeps_the_others(self):
        spec = {
            "/new/identity": {"bind": "/app/identity", "mode": "rw"},
            "/catalog/storage": {"bind": "/app/config", "mode": "rw"},
        }
        old = _old([_bind("/old/identity", "/app/identity"), _bind("/old/storage", "/app/config")])
        volumes, _ = _deploy(old, volumes=spec, moved_mounts=["/app/identity"])
        assert volumes == ["/new/identity:/app/identity:rw", "/old/storage:/app/config:rw"]

    def test_only_targets_the_caller_vouches_for_are_kept(self):
        """The kept source skips the bind-path rules, so the target is not the caller's pick."""
        spec = {"x": {"bind": "/secrets", "mode": "rw"}, **CATALOG_VOLUMES}
        old = _old([_bind("/root/.ssh", "/secrets"), _bind("/srv/myst")])
        volumes, kept = _deploy(old, volumes=spec, keep_targets={TARGET})
        assert volumes == ["x:/secrets:rw", f"/srv/myst:{TARGET}:rw"]
        assert [k["target"] for k in kept] == [TARGET]


@pytest.fixture
def worker_client(monkeypatch):
    from fastapi.testclient import TestClient

    from app import catalog, worker_api

    monkeypatch.setattr(worker_api, "_verify_api_key", lambda request: None)
    monkeypatch.setattr(worker_api, "_catalog_get_services", catalog.get_services)
    monkeypatch.setattr(worker_api, "_validate_runtime", lambda *a, **k: None, raising=False)
    return TestClient(worker_api.app), worker_api


def _mysterium_spec():
    from app import catalog

    docker = catalog.get_service("mysterium")["docker"]
    return {
        "image": docker["image"],
        "volumes": CATALOG_VOLUMES,
        "network_mode": docker["network_mode"],
        "cap_add": docker["cap_add"],
        "devices": docker["devices"],
    }


class TestTheWorkerSaysWhatItKept:
    """Through the REAL spec validation: a stubbed one hid a 403 on the second redeploy."""

    def test_the_deploy_response_names_the_kept_mount(self, worker_client):
        client, worker_api = worker_client
        seen = {}

        def fake_deploy_raw(**kwargs):
            seen.update(kwargs)
            kwargs["kept_mounts"].append({"target": TARGET, "kept": "/srv/myst", "requested": "mysterium-data"})
            return "cid"

        with patch.object(worker_api.orchestrator, "deploy_raw", side_effect=fake_deploy_raw):
            resp = client.post("/api/containers/mysterium/deploy", json={**_mysterium_spec(), "moved_mounts": ["/x"]})
        assert resp.status_code == 200, resp.text
        assert resp.json()["kept_mounts"] == [{"target": TARGET, "kept": "/srv/myst", "requested": "mysterium-data"}]
        assert seen["moved_mounts"] == ["/x"]
        assert seen["keep_targets"] == {TARGET}, "only what the worker's own catalog mounts for the slug"

    def test_nothing_kept_means_no_key(self, worker_client):
        client, worker_api = worker_client
        with patch.object(worker_api.orchestrator, "deploy_raw", return_value="cid"):
            resp = client.post("/api/containers/mysterium/deploy", json=_mysterium_spec())
        assert resp.status_code == 200, resp.text
        assert "kept_mounts" not in resp.json()

    def test_an_unknown_slug_keeps_nothing(self, worker_client):
        _, worker_api = worker_client
        assert worker_api._catalog_volume_targets("no-such-service") == set()
        assert worker_api._catalog_volume_targets(None) == set()
