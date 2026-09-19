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
        assert volumes == {"/mnt/user/appdata/myst/data": {"bind": TARGET, "mode": "rw"}}
        assert kept == [{"target": TARGET, "kept": "/mnt/user/appdata/myst/data", "requested": "mysterium-data"}]

    def test_a_differently_named_volume_survives_too(self):
        volumes, _ = _deploy(_old([_volume("myst-identity")]), volumes=CATALOG_VOLUMES)
        assert list(volumes) == ["myst-identity"]

    def test_a_trailing_slash_does_not_hide_the_mount(self):
        spec = {"mysterium-data": {"bind": TARGET + "/", "mode": "rw"}}
        volumes, _ = _deploy(_old([_bind("/srv/myst")]), volumes=spec)
        assert list(volumes) == ["/srv/myst"]

    def test_the_old_container_is_still_replaced(self):
        old = _old([_bind("/srv/myst")])
        _deploy(old, volumes=CATALOG_VOLUMES)
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
        assert volumes == {
            "/srv/myst": {"bind": TARGET, "mode": "rw"},
            "myst-logs": {"bind": "/var/log/myst", "mode": "rw"},
        }

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
        assert set(volumes) == {"/new/identity", "/old/storage"}


@pytest.fixture
def worker_client(monkeypatch):
    from fastapi.testclient import TestClient

    from app import worker_api

    monkeypatch.setattr(worker_api, "_verify_api_key", lambda request: None)
    monkeypatch.setattr(worker_api, "_validate_deploy_spec", lambda spec, slug=None: None)
    return TestClient(worker_api.app), worker_api


class TestTheWorkerSaysWhatItKept:
    def test_the_deploy_response_names_the_kept_mount(self, worker_client):
        client, worker_api = worker_client
        seen = {}

        def fake_deploy_raw(**kwargs):
            seen.update(kwargs)
            kwargs["kept_mounts"].append({"target": TARGET, "kept": "/srv/myst", "requested": "mysterium-data"})
            return "cid"

        with patch.object(worker_api.orchestrator, "deploy_raw", side_effect=fake_deploy_raw):
            resp = client.post(
                "/api/containers/mysterium/deploy",
                json={"image": "img", "volumes": CATALOG_VOLUMES, "moved_mounts": ["/x"]},
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["kept_mounts"] == [{"target": TARGET, "kept": "/srv/myst", "requested": "mysterium-data"}]
        assert seen["moved_mounts"] == ["/x"]

    def test_nothing_kept_means_no_key(self, worker_client):
        client, worker_api = worker_client
        with patch.object(worker_api.orchestrator, "deploy_raw", return_value="cid"):
            resp = client.post("/api/containers/mysterium/deploy", json={"image": "img"})
        assert resp.status_code == 200, resp.text
        assert "kept_mounts" not in resp.json()
