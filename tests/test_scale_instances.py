"""A worker can run more than one copy of a service (discussion #441).

Providers count devices per public IP, so on one connection extra copies only
help where the catalog says several devices per IP are allowed. The rules:

* one copy where the provider allows one device per IP, or where the service
  has host volumes or published ports (copies would share them);
* copy N is ``cashpilot-<slug>-N`` with ``cashpilot.instance=N``, and every
  device name the catalog derives from {hostname} gets ``-N``, so the provider
  sees separate devices;
* only a worker that advertises the ``instances`` feature is sent copy 2+, since
  an older one would read it as the first copy and replace that;
* the count is recorded per worker and kept by a redeploy that does not change it.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app import main, orchestrator
from app.constants import LABEL_INSTANCE, LABEL_MANAGED, LABEL_SERVICE, MAX_INSTANCES

ROOT = Path(__file__).resolve().parents[1]

SCALABLE = {
    "slug": "demo",
    "name": "Demo",
    "status": "active",
    "category": "bandwidth",
    "requirements": {"devices_per_ip": 0},
    "docker": {
        "image": "demo/demo",
        "env": [
            {"key": "TOKEN", "required": True, "label": "Token"},
            {"key": "DEVICE", "default": "cashpilot-{hostname}", "label": "Device name"},
        ],
        "ports": [],
        "volumes": [],
    },
}


class TestTheCeiling:
    def test_several_devices_per_ip_scales(self):
        assert main.scaling_limit(SCALABLE) == (MAX_INSTANCES, "")

    def test_an_undocumented_limit_is_not_a_refusal(self):
        svc = {**SCALABLE, "requirements": {}}
        assert main.scaling_limit(svc)[0] == MAX_INSTANCES

    def test_one_device_per_ip_is_one_copy(self):
        limit, why = main.scaling_limit({**SCALABLE, "requirements": {"devices_per_ip": 1}})
        assert limit == 1 and "one device per IP" in why

    def test_a_host_volume_is_one_copy(self):
        limit, why = main.scaling_limit({**SCALABLE, "docker": {**SCALABLE["docker"], "volumes": ["/x:/y"]}})
        assert limit == 1 and "host directory" in why

    def test_a_published_port_is_one_copy(self):
        limit, why = main.scaling_limit({**SCALABLE, "docker": {**SCALABLE["docker"], "ports": ["9001:9001"]}})
        assert limit == 1 and "port" in why

    def test_the_real_catalog_lets_traffmonetizer_scale_and_honeygain_not(self):
        from app import catalog

        assert main.scaling_limit(catalog.get_service("traffmonetizer"))[0] == MAX_INSTANCES
        assert main.scaling_limit(catalog.get_service("honeygain"))[0] == 1


class TestTheCopySpec:
    def test_each_copy_is_its_own_device(self):
        spec = {"image": "demo/demo", "env": {"TOKEN": "t", "DEVICE": "cashpilot-box"}, "hostname": None}
        copy = main._instance_spec(spec, 2, SCALABLE["docker"])
        assert copy["env"] == {"TOKEN": "t", "DEVICE": "cashpilot-box-2"}
        assert copy["instance"] == 2
        assert copy["hostname"] is None
        assert spec["env"]["DEVICE"] == "cashpilot-box", "the first copy's spec must not change"

    def test_a_command_carrying_the_device_name_names_the_copy(self):
        docker_conf = {**SCALABLE["docker"], "command": "start --token ${TOKEN} --device-name ${DEVICE}"}
        spec = {
            "env": {"TOKEN": "t", "DEVICE": "cashpilot-box"},
            "command": "start --token t --device-name cashpilot-box",
            "hostname": None,
        }
        copy = main._instance_spec(spec, 2, docker_conf)
        assert copy["command"] == "start --token t --device-name cashpilot-box-2"
        assert spec["command"].endswith("cashpilot-box")

    def test_the_real_traffmonetizer_copy_registers_its_own_device(self):
        from app import catalog

        svc = catalog.get_service("traffmonetizer")
        deploys, _, _ = _deploy(2, svc={**svc, "slug": "demo"}, env={"TRAFFMONETIZER_TOKEN": "t"})
        names = [d["command"].split("--device-name ")[1] for d in deploys]
        assert names[1] == names[0] + "-2"

    def test_a_set_hostname_is_suffixed_too(self):
        copy = main._instance_spec({"env": {}, "hostname": "box"}, 3, SCALABLE["docker"])
        assert copy["hostname"] == "box-3"


def _worker(features=("instances",), copies=(1,)):
    return {
        "id": 1,
        "system_info": json.dumps({"features": list(features)}),
        "containers": json.dumps([{"slug": "demo", "instance": n} for n in copies]),
    }


def _deploy(instances, *, svc=SCALABLE, recorded=None, worker=None, image=None, env=None):
    deploys, deletes = [], []

    async def _deploy_hop(worker_id, slug, spec):
        deploys.append(dict(spec))
        return {"container_id": f"c{spec.get('instance', 1)}"}

    async def _hop(worker_id, method, path, **kwargs):
        deletes.append((method, path))
        return {"status": "removed"}

    body = MagicMock()
    body.env = env or {"TOKEN": "t"}
    body.hostname = None
    body.instances = instances
    body.image = image
    saved = AsyncMock()

    async def run():
        with (
            patch.object(main, "_require_owner", lambda r: None),
            patch.object(main.catalog, "get_service", return_value=svc),
            patch.object(main, "_resolve_worker_id", AsyncMock(return_value=1)),
            patch.object(main, "_proxy_worker_deploy", _deploy_hop),
            patch.object(main, "_proxy_to_worker", _hop),
            patch.object(main.database, "get_worker", AsyncMock(return_value=worker or _worker())),
            patch.object(main.database, "get_deployment_spec", AsyncMock(return_value=recorded)),
            patch.object(main.database, "save_deployment", saved),
            patch.object(main.database, "record_health_event", AsyncMock()),
            patch.object(main, "_spawn", lambda coro: coro.close()),
            patch.object(main.metrics, "record_container_lifecycle", lambda *a: None),
        ):
            await main.api_deploy(MagicMock(), "demo", body)

    asyncio.run(run())
    return deploys, deletes, saved.call_args.kwargs["spec"] if saved.call_args else None


class TestTheDeploy:
    def test_three_copies_are_three_deploys(self):
        deploys, deletes, record = _deploy(3)
        assert [d.get("instance", 1) for d in deploys] == [1, 2, 3]
        assert [d["env"]["DEVICE"] for d in deploys] == [
            "cashpilot-cashpilot",
            "cashpilot-cashpilot-2",
            "cashpilot-cashpilot-3",
        ]
        assert record["instances"] == 3
        assert deletes == []

    def test_a_redeploy_without_a_count_keeps_the_recorded_one(self):
        recorded = {"image": "demo/demo", "env": {"TOKEN": "t"}, "instances": 2}
        deploys, _, record = _deploy(None, recorded=recorded, worker=_worker(copies=(1, 2)))
        assert [d.get("instance", 1) for d in deploys] == [1, 2]
        assert record["instances"] == 2

    def test_scaling_down_removes_the_highest_copies(self):
        recorded = {"image": "demo/demo", "env": {"TOKEN": "t"}, "instances": 3}
        deploys, deletes, record = _deploy(1, recorded=recorded, worker=_worker(copies=(1, 2, 3)))
        assert [d.get("instance", 1) for d in deploys] == [1]
        assert deletes == [
            ("DELETE", "/api/containers/demo/instances/2"),
            ("DELETE", "/api/containers/demo/instances/3"),
        ]
        assert "instances" not in record

    def test_a_plain_deploy_is_unchanged(self):
        deploys, deletes, record = _deploy(None)
        assert [d.get("instance", 1) for d in deploys] == [1]
        assert "instance" not in deploys[0]
        assert "instances" not in record

    def test_every_copy_runs_the_chosen_image(self):
        deploys, _, record = _deploy(2, image="mirror.example/demo:1.2")
        assert [d["image"] for d in deploys] == ["mirror.example/demo:1.2"] * 2
        assert record["custom_image"] == "mirror.example/demo:1.2"

    def test_one_device_per_ip_refuses_a_second_copy(self):
        with pytest.raises(HTTPException) as err:
            _deploy(2, svc={**SCALABLE, "requirements": {"devices_per_ip": 1}})
        assert err.value.status_code == 400

    def test_an_older_worker_is_never_sent_a_second_copy(self):
        with pytest.raises(HTTPException) as err:
            _deploy(2, worker=_worker(features=()))
        assert err.value.status_code == 409

    def test_the_count_is_bounded(self):
        with pytest.raises(HTTPException):
            _deploy(MAX_INSTANCES + 1)
        with pytest.raises(HTTPException):
            _deploy(0)


def _container(name, slug="demo", instance=None):
    c = MagicMock()
    c.name = name
    c.labels = {LABEL_SERVICE: slug, LABEL_MANAGED: "true"}
    if instance:
        c.labels[LABEL_INSTANCE] = str(instance)
    return c


class TestTheOrchestrator:
    def test_copy_names(self):
        assert orchestrator._container_name("demo") == "cashpilot-demo"
        assert orchestrator._container_name("demo", 2) == "cashpilot-demo-2"

    def test_the_label_fallback_finds_the_copy_asked_for(self):
        from docker.errors import NotFound

        first, second = _container("renamed-a"), _container("renamed-b", instance=2)
        client = MagicMock()
        client.containers.get.side_effect = NotFound("gone")
        client.containers.list.return_value = [second, first]
        with patch.object(orchestrator, "_get_client", return_value=client):
            assert orchestrator._find_container("demo") is first
            assert orchestrator._find_container("demo", 2) is second

    def test_a_name_hit_on_the_wrong_copy_is_not_returned(self):
        """cashpilot-demo-2 could also be a service whose slug is demo-2."""
        other = _container("cashpilot-demo-2", slug="demo")
        client = MagicMock()
        client.containers.get.return_value = other
        client.containers.list.return_value = [other]
        with patch.object(orchestrator, "_get_client", return_value=client), pytest.raises(ValueError):
            orchestrator._find_container("demo", 2)

    def test_removing_the_service_removes_the_extra_copies(self):
        first, second, third = _container("a"), _container("b", instance=2), _container("c", instance=3)
        client = MagicMock()
        client.containers.list.return_value = [third, first, second]
        with patch.object(orchestrator, "_get_client", return_value=client):
            assert orchestrator.remove_extra_instances("demo") == ["b", "c"]
        first.remove.assert_not_called()

    def test_the_first_copy_cannot_be_removed_on_its_own(self):
        with pytest.raises(ValueError):
            orchestrator.remove_instance("demo", 1)


class TestTheWorker:
    def _spec(self, **kw):
        from app.worker_api import DeploySpec

        return DeploySpec(image="demo/demo", **kw)

    def test_a_second_copy_with_volumes_is_refused(self):
        from app import worker_api

        with pytest.raises(HTTPException) as err:
            worker_api._validate_deploy_spec(
                self._spec(instance=2, volumes={"/x": {"bind": "/y", "mode": "rw"}}), "demo"
            )
        assert err.value.status_code == 400

    def test_an_out_of_range_copy_is_refused(self):
        from app import worker_api

        with pytest.raises(HTTPException):
            worker_api._validate_instance(MAX_INSTANCES + 1)
        with pytest.raises(HTTPException):
            worker_api._validate_instance(0)

    def test_the_heartbeat_advertises_the_feature(self):
        src = (ROOT / "app" / "worker_api.py").read_text(encoding="utf-8")
        assert '"features": ["instances"]' in src


class TestTheForm:
    JS = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")

    def test_the_count_is_posted(self):
        assert "body.instances = instances" in self.JS

    def test_copy_actions_carry_the_instance(self):
        assert 'data-a4="${inst.container.instance || 1}"' in self.JS
        assert "function _instanceQuery(" in self.JS

    def test_the_dispatcher_passes_a_fourth_argument(self):
        delegate = (ROOT / "app" / "static" / "js" / "delegate.js").read_text(encoding="utf-8")
        assert "i <= 4" in delegate


class TestTheCopyContainer:
    """deploy_raw names and labels copy N; copy 1 is created as it always was."""

    def _run(self, instance):
        client = MagicMock()
        client.networks.get.return_value = MagicMock(attrs={"Driver": "bridge"})
        client.containers.get.side_effect = orchestrator.NotFound("nope")
        client.containers.run.return_value = MagicMock(id="new", short_id="new")
        with (
            patch.object(orchestrator, "_CONTAINER_NETWORK", ""),
            patch.object(orchestrator, "_get_client", return_value=client),
        ):
            orchestrator.deploy_raw(slug="demo", image="demo/demo", instance=instance)
        return client.containers.run.call_args.kwargs

    def test_copy_two_is_named_and_labelled(self):
        kwargs = self._run(2)
        assert kwargs["name"] == "cashpilot-demo-2"
        assert kwargs["labels"][LABEL_INSTANCE] == "2"

    def test_copy_one_carries_no_instance_label(self):
        kwargs = self._run(1)
        assert kwargs["name"] == "cashpilot-demo"
        assert LABEL_INSTANCE not in kwargs["labels"]

    def test_an_unreadable_label_reads_as_the_first_copy(self):
        assert orchestrator._instance_of(_container("x", instance="two")) == 1


class TestCopyCommands:
    """Stop, restart, start, logs and remove reach the copy they were asked for."""

    def _client(self):
        first, second = _container("cashpilot-demo"), _container("cashpilot-demo-2", instance=2)
        second.logs.return_value = b"copy two"
        client = MagicMock()
        client.containers.get.side_effect = lambda name: {"cashpilot-demo": first, "cashpilot-demo-2": second}[name]
        client.containers.list.return_value = [first, second]
        return client, first, second

    def test_each_command_hits_copy_two_only(self):
        client, first, second = self._client()
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.stop_service("demo", 2)
            orchestrator.restart_service("demo", 2)
            orchestrator.start_service("demo", 2)
            assert orchestrator.get_service_logs("demo", 10, 2) == "copy two"
            assert orchestrator.remove_instance("demo", 2) == {"container": "cashpilot-demo-2"}
        second.stop.assert_called()
        second.restart.assert_called_once()
        second.start.assert_called_once()
        second.remove.assert_called_once_with(force=True)
        for call in ("stop", "restart", "start", "remove", "logs"):
            getattr(first, call).assert_not_called()

    def test_a_copy_that_will_not_stop_is_still_removed(self):
        from docker.errors import APIError

        client, _, second = self._client()
        second.stop.side_effect = APIError("busy")
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.remove_instance("demo", 2)
        second.remove.assert_called_once_with(force=True)


class TestTheWorkerRoutes:
    def teardown_method(self):
        if getattr(self, "_key", None):
            self._key.stop()

    def _client(self):
        from contextlib import asynccontextmanager

        from fastapi.testclient import TestClient

        from app import worker_api

        @asynccontextmanager
        async def _noop(a):
            yield

        worker_api.app.router.lifespan_context = _noop
        # The key is read from the environment at import; whichever test file
        # imported the worker first decided it, so this test sets its own.
        self._key = patch.object(worker_api, "API_KEY", "scale-test-key")
        self._key.start()
        return TestClient(worker_api.app, raise_server_exceptions=False), {
            "Authorization": f"Bearer {worker_api.API_KEY}"
        }

    def test_scaling_down_removes_one_copy(self):
        client, auth = self._client()
        with patch("app.worker_api.orchestrator.remove_instance", return_value={"container": "c-2"}) as rm:
            resp = client.delete("/api/containers/demo/instances/2", headers=auth)
        assert resp.status_code == 200 and resp.json() == {"status": "removed", "container": "c-2"}
        rm.assert_called_once_with("demo", 2)

    @pytest.mark.parametrize(("error", "status"), [(ValueError("gone"), 404), (RuntimeError("no docker"), 503)])
    def test_scaling_down_errors_map_to_http(self, error, status):
        client, auth = self._client()
        with patch("app.worker_api.orchestrator.remove_instance", side_effect=error):
            assert client.delete("/api/containers/demo/instances/2", headers=auth).status_code == status

    def test_an_out_of_range_copy_is_refused_before_docker(self):
        client, auth = self._client()
        with patch("app.worker_api.orchestrator.remove_instance") as rm:
            assert client.delete(f"/api/containers/demo/instances/{MAX_INSTANCES + 1}", headers=auth).status_code == 400
        rm.assert_not_called()

    def test_removing_the_service_reports_the_extra_copies(self):
        client, auth = self._client()
        removal = {"container": "cashpilot-demo", "deleted_volumes": [], "failed_volumes": []}
        with (
            patch("app.worker_api.orchestrator.remove_service", return_value=removal),
            patch("app.worker_api.orchestrator.remove_extra_instances", return_value=["cashpilot-demo-2"]) as extra,
        ):
            resp = client.delete("/api/containers/demo", headers=auth)
        assert resp.json()["extra_instances"] == ["cashpilot-demo-2"]
        extra.assert_called_once_with("demo")


class TestTheUiPassthrough:
    def test_copy_logs_name_the_copy_and_copy_one_does_not(self):
        hop = AsyncMock(return_value={"logs": ""})
        with patch.object(main, "_proxy_to_worker", hop):
            asyncio.run(main._proxy_worker_logs(1, "demo", 50, instance=2))
            asyncio.run(main._proxy_worker_logs(1, "demo", 50))
        assert hop.call_args_list[0].kwargs["params"] == {"lines": 50, "instance": 2}
        assert hop.call_args_list[1].kwargs["params"] == {"lines": 50}

    def test_a_heartbeat_entry_with_a_bad_instance_counts_as_the_first_copy(self):
        worker = {"containers": json.dumps([{"slug": "demo", "instance": "x"}, {"slug": "demo", "instance": 3}])}
        with patch.object(main.database, "get_worker", AsyncMock(return_value=worker)):
            assert asyncio.run(main._worker_instances(1, "demo")) == {1, 3}


class TestTheDashboardCopies:
    """A copy's number survives the trip from the heartbeat to the dashboard rows."""

    def test_copy_two_reaches_the_instance_details(self):
        worker = {
            "id": 1,
            "name": "box",
            "status": "online",
            "system_info": json.dumps({"docker_available": True}),
            "containers": json.dumps(
                [
                    {"slug": "demo", "name": "cashpilot-demo", "status": "running"},
                    {"slug": "demo", "name": "cashpilot-demo-2", "status": "running", "instance": 2},
                ]
            ),
        }
        rows = asyncio.run(main._get_all_worker_containers([worker]))
        assert sorted(r["instance"] for r in rows) == [1, 2]
