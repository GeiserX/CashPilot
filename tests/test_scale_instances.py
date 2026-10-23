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

    def test_a_set_hostname_is_suffixed_too(self):
        copy = main._instance_spec({"env": {}, "hostname": "box"}, 3, SCALABLE["docker"])
        assert copy["hostname"] == "box-3"


def _worker(features=("instances",), copies=(1,)):
    return {
        "id": 1,
        "system_info": json.dumps({"features": list(features)}),
        "containers": json.dumps([{"slug": "demo", "instance": n} for n in copies]),
    }


def _deploy(instances, *, svc=SCALABLE, recorded=None, worker=None):
    deploys, deletes = [], []

    async def _deploy_hop(worker_id, slug, spec):
        deploys.append(dict(spec))
        return {"container_id": f"c{spec.get('instance', 1)}"}

    async def _hop(worker_id, method, path, **kwargs):
        deletes.append((method, path))
        return {"status": "removed"}

    body = MagicMock()
    body.env = {"TOKEN": "t"}
    body.hostname = None
    body.instances = instances
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
