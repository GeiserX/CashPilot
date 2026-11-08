"""Mysterium is fenced like every other earner, and Docker never starts it unfenced.

Through 2.0.3 the node ran with ``network_mode: host`` and NET_ADMIN. That put
NET_ADMIN in the host's own network namespace: the node, or a malicious image
update, could rewrite the host's firewall (the LAN fence included), add routes
and addresses, bind any port on every host address and reach the LAN, the
tailnet, cloud metadata and every other container. No host rule holds against
a process that can rewrite the host's rules.

Now the node runs in its own namespace on the fenced bridge, with its UDP range
published 1:1, so its NET_ADMIN reaches only its own tables and the host's
fence drops what it sends inward whatever it does to them. Docker gives it no
restart policy: the worker starts it only once the fence reads complete, and
stops it within 30 s if the fence or the container's shape goes.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest
import yaml
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import catalog, drift, isolation_check, lan_fence, orchestrator, socket_policy, worker_api
from app.worker_api import DeploySpec, _validate_deploy_spec

#: The mode rule (lan_fence.mode_problem) is part of what these tests check.
pytestmark = pytest.mark.real_gated_mode

ROOT = Path(__file__).resolve().parent.parent
MYST = catalog.get_service("mysterium")
PINNED = MYST["docker"]["image"]
LABELS = {"cashpilot.service": "mysterium", "cashpilot.managed": "true"}


def _entry(**docker):
    entry = {"name": "X", "slug": "x", "category": "bandwidth", "status": "active", "description": "x"}
    entry["docker"] = {"image": "x/x@sha256:" + "a" * 64, "fence_gated": True, **docker}
    return entry


# ---------------------------------------------------------------------------
# (a) The catalog: no host network, and the rule that keeps the threat class out
# ---------------------------------------------------------------------------


class TestTheCatalog:
    def test_mysterium_no_longer_shares_the_hosts_network(self):
        raw = yaml.safe_load((ROOT / "services/bandwidth/mysterium.yml").read_text())["docker"]
        assert "network_mode" not in raw
        assert raw["fence_gated"] is True
        assert raw["runtime"] == "runc"
        assert "4449:4449" not in [str(p) for p in raw.get("ports") or []]

    def test_its_image_is_pinned_by_digest(self):
        assert "@sha256:" in PINNED and PINNED.startswith("mysteriumnetwork/myst:")

    def test_its_own_firewall_stays_as_the_second_layer(self):
        cmd = MYST["docker"]["command"]
        assert "--ui.address=0.0.0.0 " in cmd
        assert "--tequilapi.address=127.0.0.1 " in cmd
        assert "100.64.0.0/10" in cmd and "169.254.0.0/16" in cmd

    def test_net_admin_on_the_host_network_is_refused(self, tmp_path):
        errors = catalog._validate(_entry(cap_add=["NET_ADMIN"], network_mode="host"), tmp_path / "x.yml")
        assert any("cannot use network_mode: host" in e for e in errors)

    def test_sys_admin_is_held_to_the_same_rule(self, tmp_path):
        errors = catalog._validate(_entry(cap_add=["CAP_SYS_ADMIN"], network_mode="host"), tmp_path / "x.yml")
        assert any("cannot use network_mode: host" in e for e in errors)

    def test_net_admin_needs_a_digest(self, tmp_path):
        errors = catalog._validate(_entry(cap_add=["NET_ADMIN"], image="x/x:1.0"), tmp_path / "x.yml")
        assert any("@sha256:" in e for e in errors)

    def test_net_admin_needs_the_fence_gate(self, tmp_path):
        errors = catalog._validate(_entry(cap_add=["NET_ADMIN"], fence_gated=False), tmp_path / "x.yml")
        assert any("fence_gated" in e for e in errors)

    def test_control_a_pinned_fenced_net_admin_service_loads(self, tmp_path):
        assert catalog._validate(_entry(cap_add=["NET_ADMIN"]), tmp_path / "x.yml") == []

    def test_a_udp_range_must_name_a_port_range_env(self, tmp_path):
        bad = _entry(env=[{"key": "P", "default": "1:2"}], udp_port_range={"env": "P"})
        assert any("port_range" in e for e in catalog._validate(bad, tmp_path / "x.yml"))
        good = _entry(env=[{"key": "P", "default": "1:2", "port_range": True}], udp_port_range={"env": "P"})
        assert catalog._validate(good, tmp_path / "x.yml") == []

    def test_a_udp_range_cap_above_the_ceiling_is_refused(self, tmp_path):
        bad = _entry(
            env=[{"key": "P", "default": "1:2", "port_range": True}],
            udp_port_range={"env": "P", "max_ports": 5000},
        )
        assert any("max_ports" in e for e in catalog._validate(bad, tmp_path / "x.yml"))


# ---------------------------------------------------------------------------
# (b) The UDP range, published 1:1
# ---------------------------------------------------------------------------


class TestTheUdpRange:
    def test_the_default_range_is_30_ports_each_on_itself(self):
        default = next(e["default"] for e in MYST["docker"]["env"] if e["key"] == "UDP_PORTS")
        ports = catalog.expand_udp_range(default)
        # About two ports per session: 15 at once, and about 2.5 MB of
        # docker-proxy memory per port, so a wider default only costs memory.
        assert len(ports) == 30
        assert ports["56000/udp"] == 56000 and ports["56029/udp"] == 56029

    def test_the_default_stays_inside_the_range_routers_forward_since_2_0_3(self):
        default = next(e["default"] for e in MYST["docker"]["env"] if e["key"] == "UDP_PORTS")
        assert set(catalog.expand_udp_range(default)) <= set(catalog.expand_udp_range("56000:56100"))

    @pytest.mark.parametrize("value", ["56100:56000", "1:70000", "56000", "a:b", "56000-56100"])
    def test_anything_but_a_range_is_refused(self, value):
        with pytest.raises(ValueError):
            catalog.expand_udp_range(value)

    def test_a_range_over_the_cap_is_refused(self):
        with pytest.raises(ValueError, match="at most 1000"):
            catalog.expand_udp_range("10000:11000")
        assert len(catalog.expand_udp_range("10000:10999")) == 1000

    def test_the_webui_addresses_become_bindings(self):
        assert catalog.ui_bindings("localhost,172.18.0.1", 4449) == [["127.0.0.1", 4449], ["172.18.0.1", 4449]]
        with pytest.raises(ValueError):
            catalog.ui_bindings("::1", 4449)


# ---------------------------------------------------------------------------
# (c) The deploy: a node recorded on the host network moves onto the bridge
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _noop_lifespan(a):
    yield


@pytest.fixture
def ui():
    from app.main import app

    app.router.lifespan_context = _noop_lifespan
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _ui_deploy(client, body, recorded=None, features=("fence_gated",)):
    worker = {
        "id": 1,
        "name": "w1",
        "status": "online",
        "url": "http://192.168.1.10:8081",
        "system_info": json.dumps({"features": list(features)}),
    }
    sent: dict = {}

    async def _fake_deploy(worker_id, slug, spec):
        sent.update(spec)
        return {"container_id": "abc123"}

    with (
        patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "admin", "r": "owner"}),
        patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
        patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
        patch("app.main.database.get_deployment_spec", new_callable=AsyncMock, return_value=recorded),
        patch("app.main._proxy_worker_deploy", side_effect=_fake_deploy),
        patch("app.main.database.save_deployment", new_callable=AsyncMock),
        patch("app.main.database.record_health_event", new_callable=AsyncMock),
        patch("app.main._run_collection", new_callable=AsyncMock),
    ):
        resp = client.post("/api/deploy/mysterium", json=body)
    return resp, sent


#: What every Mysterium deployed through 2.0.3 has on record.
HOST_RECORD = {
    "image": "mysteriumnetwork/myst",
    "env": {"UI_ADDRESS": "127.0.0.1", "UDP_PORTS": "56000:56100"},
    "network_mode": "host",
    "ports": {"4449/tcp": 4449},
    "volumes": {"/mnt/appdata/myst/data": {"bind": "/var/lib/mysterium-node", "mode": "rw"}},
}


class TestTheDeploy:
    def test_a_first_deploy_is_on_the_bridge_with_its_range_and_loopback_webui(self, ui):
        resp, sent = _ui_deploy(ui, {"env": {}})
        assert resp.status_code == 200, resp.text
        assert sent["network_mode"] is None
        assert sum(k.endswith("/udp") for k in sent["ports"]) == 30
        assert sent["ports"]["4449/tcp"] == ["127.0.0.1", 4449]

    def test_a_node_recorded_on_the_host_network_moves_onto_the_bridge(self, ui):
        resp, sent = _ui_deploy(ui, {"env": {}}, recorded=HOST_RECORD)
        assert resp.status_code == 200, resp.text
        assert sent["network_mode"] is None, "the record must not carry NET_ADMIN back into the host's namespace"
        # 4449 on every interface was the host-network record; now loopback only.
        assert sent["ports"]["4449/tcp"] == ["127.0.0.1", 4449]
        # The range on record is kept, so the router's forward still matches.
        assert sum(k.endswith("/udp") for k in sent["ports"]) == 101
        # The identity lives in the data directory, which the redeploy keeps.
        assert sent["volumes"] == HOST_RECORD["volumes"]
        kept = " ".join(resp.json().get("kept_from_previous_deployment") or [])
        assert "fenced bridge" in kept and "keeping the deployed value" not in kept

    def test_a_worker_too_old_to_gate_it_is_refused_and_the_node_left_alone(self, ui):
        resp, sent = _ui_deploy(ui, {"env": {}}, recorded=HOST_RECORD, features=("instances",))
        assert resp.status_code == 409
        assert "Update the worker" in resp.json()["detail"]
        assert not sent

    def test_another_image_is_refused(self, ui):
        resp, sent = _ui_deploy(ui, {"env": {}, "image": "mysteriumnetwork/myst:latest"})
        assert resp.status_code == 400
        assert not sent


# ---------------------------------------------------------------------------
# The worker checks its own catalog, never the request
# ---------------------------------------------------------------------------


@pytest.fixture
def real_catalog(monkeypatch):
    monkeypatch.setattr(worker_api, "_catalog_get_services", catalog.get_services)


class TestTheWorkerRefuses:
    def test_mysterium_on_the_host_network(self, real_catalog):
        with pytest.raises(HTTPException) as refused:
            _validate_deploy_spec(DeploySpec(image=PINNED, network_mode="host"), "mysterium")
        assert refused.value.status_code == 403

    def test_mysterium_on_another_image(self, real_catalog):
        with pytest.raises(HTTPException) as refused:
            _validate_deploy_spec(DeploySpec(image="mysteriumnetwork/myst:latest"), "mysterium")
        assert refused.value.status_code == 403

    def test_more_ports_than_a_range_can_need(self, real_catalog):
        ports = {f"{p}/udp": p for p in range(20000, 21100)}
        with pytest.raises(HTTPException) as refused:
            _validate_deploy_spec(DeploySpec(image="x", ports=ports), "honeygain")
        assert refused.value.status_code == 400

    def test_control_the_catalog_spec_passes(self, real_catalog):
        docker = MYST["docker"]
        ports = {**catalog.expand_udp_range("56000:56100"), "4449/tcp": [("127.0.0.1", 4449), ("10.0.0.2", 4449)]}
        spec = DeploySpec(image=PINNED, cap_add=docker["cap_add"], devices=docker["devices"], ports=ports)
        _validate_deploy_spec(spec, "mysterium")
        assert spec.ports["4449/tcp"] == [("127.0.0.1", 4449), ("10.0.0.2", 4449)]


# ---------------------------------------------------------------------------
# (d) deploy_raw: no restart policy, started only behind a confirmed fence
# ---------------------------------------------------------------------------


@pytest.fixture
def markers(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrator, "STOPPED_MARKER", str(tmp_path / "stopped"))
    monkeypatch.setattr(orchestrator, "IDENTITY_DIR", str(tmp_path / "identity"))
    return tmp_path


def _raw_deploy(problem=None, slug="mysterium", old=None, mode=lan_fence.MODE_ON, **kwargs):
    created = MagicMock(id="new", short_id="new")
    client = MagicMock()
    if old is None:
        client.containers.get.side_effect = orchestrator.NotFound("nope")
    else:
        client.containers.get.return_value = old
    client.containers.create.return_value = created
    client.containers.run.return_value = created
    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        patch.object(orchestrator, "_CONTAINER_RUNTIME", "runsc"),
        patch.object(orchestrator, "available_runtimes", return_value={"runc", "runsc"}),
        patch("app.lan_fence.fence_problem", return_value=problem),
        patch("app.lan_fence.mode_problem", return_value=lan_fence.mode_problem(mode)),
    ):
        orchestrator.deploy_raw(slug=slug, image=PINNED, **kwargs)
    return client, created


class TestDeployRaw:
    def test_docker_never_starts_it_on_its_own(self, markers):
        client, created = _raw_deploy()
        kwargs = client.containers.create.call_args.kwargs
        assert kwargs["restart_policy"] == {"Name": "no"}
        client.containers.run.assert_not_called()
        created.start.assert_called_once()

    def test_runc_wins_over_an_operator_default_of_gvisor(self, markers):
        client, _ = _raw_deploy()
        assert client.containers.create.call_args.kwargs["runtime"] == "runc"

    def test_without_the_fence_nothing_starts(self, markers):
        created = MagicMock(id="new", short_id="new")
        client = MagicMock()
        client.containers.get.side_effect = orchestrator.NotFound("nope")
        client.containers.create.return_value = created
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch("app.lan_fence.fence_problem", return_value="missing"),
            patch("app.lan_fence.mode_problem", return_value=None),
            pytest.raises(orchestrator.ContainerNetworkError),
        ):
            orchestrator.deploy_raw(slug="mysterium", image=PINNED)
        created.start.assert_not_called()
        client.containers.run.assert_not_called()

    @pytest.mark.parametrize("mode", [lan_fence.MODE_LEGACY, lan_fence.MODE_OFF])
    def test_on_the_default_bridge_it_is_refused_before_the_old_node_is_touched(self, markers, mode):
        old = MagicMock()
        old.name = "cashpilot-mysterium"
        old.labels = dict(LABELS)
        with pytest.raises(orchestrator.ContainerNetworkError, match="not touched"):
            _raw_deploy(old=old, mode=mode)
        old.stop.assert_not_called()
        old.remove.assert_not_called()

    def test_control_on_the_operators_own_network_it_deploys(self, markers):
        client, created = _raw_deploy(mode=lan_fence.MODE_OPERATOR)
        created.start.assert_called_once()

    def test_control_an_ordinary_earner_keeps_unless_stopped(self, markers):
        client, _ = _raw_deploy(slug="honeygain")
        assert client.containers.run.call_args.kwargs["restart_policy"] == {"Name": "unless-stopped"}

    def test_the_identity_is_read_before_the_old_node_goes(self, markers):
        old = MagicMock()
        old.name = "cashpilot-mysterium"
        old.status = "running"
        old.labels = dict(LABELS)
        old.attrs = {"Mounts": []}
        old.exec_run.return_value = (0, b'{"identities":[{"id":"0x' + b"a" * 40 + b'"}]} {"id":"0x' + b"a" * 40 + b'"}')
        _raw_deploy(old=old)
        assert (markers / "identity" / "cashpilot-mysterium").read_text() == "0x" + "a" * 40


# ---------------------------------------------------------------------------
# (e) The socket proxy no longer lets anything join the host's cgroup namespace
# ---------------------------------------------------------------------------


def test_the_socket_policy_keeps_host_cgroupns_off():
    create = yaml.safe_load(socket_policy.policy())["request_body"]["container_create"]
    assert create["allow_host_cgroupns"] is False
    assert create["allow_privileged"] is False


# ---------------------------------------------------------------------------
# (f) Drift: a node still on the host network is flagged, whatever its record says
# ---------------------------------------------------------------------------


def _shape(network_mode="cashpilot-isolated", restart="no", image=PINNED):
    attrs = {
        "Config": {"Image": image, "Env": ["UI_ADDRESS=127.0.0.1", "UDP_PORTS=56000:56100"]},
        "HostConfig": {
            "CapAdd": ["NET_ADMIN", "SETUID", "SETGID"],
            "NetworkMode": network_mode,
            "Devices": [{"PathInContainer": "/dev/net/tun"}],
            "PortBindings": {"4449/tcp": [{"HostIp": "127.0.0.1", "HostPort": "4449"}]},
            "RestartPolicy": {"Name": restart},
        },
        "Mounts": [{"Destination": "/var/lib/mysterium-node"}],
    }
    return orchestrator._shape(SimpleNamespace(attrs=attrs))


class TestDrift:
    def test_a_node_on_the_host_network_is_flagged_though_its_record_says_host(self):
        found = drift.container_drift(MYST, _shape(network_mode="host"), HOST_RECORD)
        assert any("shares the host's network" in f and "NET_ADMIN" in f for f in found)

    def test_a_restart_policy_is_flagged(self):
        found = drift.container_drift(MYST, _shape(restart="unless-stopped"), None)
        assert any("restart policy unless-stopped" in f for f in found)

    def test_another_image_is_flagged(self):
        found = drift.container_drift(MYST, _shape(image="mysteriumnetwork/myst:latest"), None)
        assert any("the catalog pins" in f for f in found)

    def test_control_a_migrated_node_has_no_drift(self):
        assert drift.container_drift(MYST, _shape(), None) == []


# ---------------------------------------------------------------------------
# (g) The isolation check goes red on NET_ADMIN in the host's namespace
# ---------------------------------------------------------------------------


def _c(name, mode, caps=(), privileged=False):
    return SimpleNamespace(
        name=name, attrs={"HostConfig": {"NetworkMode": mode, "CapAdd": list(caps), "Privileged": privileged}}
    )


class TestIsolationCheck:
    def test_net_admin_in_the_host_netns_is_an_exposure(self):
        found = isolation_check.host_netns_findings([_c("cashpilot-mysterium", "host", ["NET_ADMIN", "SETUID"])])
        assert found and found[0]["exposure"] is True
        assert "cashpilot-mysterium (NET_ADMIN)" in found[0]["detail"]

    def test_control_net_admin_in_its_own_namespace_is_not(self):
        assert (
            isolation_check.host_netns_findings([_c("cashpilot-mysterium", "cashpilot-isolated", ["NET_ADMIN"])]) == []
        )

    def test_control_the_host_network_without_those_capabilities_is_not(self):
        assert isolation_check.host_netns_findings([_c("cashpilot-x", "host", ["NET_RAW"])]) == []


# ---------------------------------------------------------------------------
# (h) The guard: started behind the fence, stopped without it
# ---------------------------------------------------------------------------


class _Container(MagicMock):
    """Like docker-py's Container: ``status`` is a read-only property."""

    @property
    def status(self):
        return self._status


def _node(status="running", network_mode="cashpilot-isolated", caps=("NET_ADMIN", "SETUID", "SETGID"), image=PINNED):
    c = _Container()
    c._status = status
    c.name = "cashpilot-mysterium"
    c.labels = dict(LABELS)
    c.attrs = {
        "Config": {"Image": image},
        "HostConfig": {"NetworkMode": network_mode, "CapAdd": list(caps), "RestartPolicy": {"Name": "no"}},
    }
    c.exec_run.return_value = (1, b"")
    return c


def _guard(containers, problem=None, mode=lan_fence.MODE_ON):
    client = MagicMock()
    client.containers.list.return_value = containers
    with (
        patch.object(orchestrator, "docker_available", return_value=True),
        patch.object(orchestrator, "_get_client", return_value=client),
        patch.object(lan_fence, "resolve_mode", return_value=mode),
        patch.object(lan_fence, "fence_problem", return_value=problem),
        patch.object(lan_fence, "apply_fence") as apply,
    ):
        held = lan_fence.guard()
    return held, apply


class TestTheGuard:
    def test_a_missing_fence_stops_the_node_and_puts_the_fence_back(self, markers):
        node = _node()
        held, apply = _guard([node], problem="the LAN fence is not complete on this host")
        node.stop.assert_called_once()
        apply.assert_called_once()
        assert "not complete" in held["cashpilot-mysterium"]
        assert lan_fence.status()["guard"] == held

    def test_a_stopped_node_starts_once_the_fence_reads_complete(self, markers):
        node = _node(status="exited")
        held, _ = _guard([node])
        node.start.assert_called_once()
        assert held == {}

    def test_a_node_the_owner_stopped_stays_stopped(self, markers):
        orchestrator._mark_stopped("cashpilot-mysterium", True)
        node = _node(status="exited")
        _guard([node])
        node.start.assert_not_called()

    def test_without_the_fence_a_stopped_node_is_not_started(self, markers):
        node = _node(status="exited")
        _guard([node], problem="missing")
        node.start.assert_not_called()

    @pytest.mark.parametrize(
        "change",
        [
            {"network_mode": "host"},
            {"caps": ("NET_ADMIN", "SETUID", "SETGID", "SYS_ADMIN")},
            {"image": "mysteriumnetwork/myst:latest"},
            {"network_mode": "bridge"},
        ],
    )
    def test_a_node_recreated_another_way_is_stopped(self, markers, change):
        node = _node(**change)
        held, _ = _guard([node])
        node.stop.assert_called_once()
        assert held["cashpilot-mysterium"]

    def test_a_node_with_another_identity_is_stopped_and_stays_stopped(self, markers):
        orchestrator._remember_identity("cashpilot-mysterium", "0x" + "a" * 40)
        node = _node()
        node.exec_run.return_value = (0, b'{"id":"0x' + b"b" * 40 + b'"}')
        held, _ = _guard([node])
        node.stop.assert_called_once()
        assert "0x" + "a" * 40 in held["cashpilot-mysterium"]
        # Stopped, it reads no identity, and must not be started again because of that.
        stopped = _node(status="exited")
        held, _ = _guard([stopped])
        stopped.start.assert_not_called()
        assert held["cashpilot-mysterium"]

    def test_the_same_identity_clears_the_record(self, markers):
        orchestrator._remember_identity("cashpilot-mysterium", "0x" + "a" * 40)
        node = _node()
        node.exec_run.return_value = (0, b'{"id":"0x' + b"a" * 40 + b'"}')
        held, _ = _guard([node])
        node.stop.assert_not_called()
        assert held == {}
        assert not (markers / "identity" / "cashpilot-mysterium").exists()

    def test_control_a_running_node_behind_the_fence_is_left_alone(self, markers):
        node = _node()
        held, apply = _guard([node])
        node.stop.assert_not_called()
        node.start.assert_not_called()
        apply.assert_not_called()
        assert held == {}

    def test_on_the_operators_own_network_there_is_no_fence_to_wait_for(self, markers):
        node = _node(status="exited", network_mode="operator-net")
        _guard([node], mode=lan_fence.MODE_OPERATOR)
        node.start.assert_called_once()

    @pytest.mark.parametrize("mode", [lan_fence.MODE_LEGACY, lan_fence.MODE_OFF])
    def test_on_the_default_bridge_it_does_not_run_at_all(self, markers, mode):
        # Every other earner there reaches its WebUI, and nothing keeps it off the LAN.
        running, stopped = _node(network_mode="bridge"), _node(status="exited", network_mode="bridge")
        held, apply = _guard([running, stopped], problem=lan_fence.mode_problem(mode), mode=mode)
        running.stop.assert_called_once()
        stopped.start.assert_not_called()
        apply.assert_not_called()
        assert (
            "Turn on isolation" in held["cashpilot-mysterium"] or "CASHPILOT_ISOLATION" in held["cashpilot-mysterium"]
        )


class TestFenceProblem:
    def _read(self, result, mode=lan_fence.MODE_ON):
        with (
            patch.object(lan_fence, "resolve_mode", return_value=mode),
            patch.object(lan_fence, "read_fence", return_value=result),
        ):
            return lan_fence.fence_problem(MagicMock())

    def test_a_complete_table_is_no_problem(self):
        assert self._read({"present": True, "matches": True}) is None

    def test_a_table_missing_a_rule_is(self):
        assert self._read({"present": True, "matches": False})

    def test_no_table_is(self):
        assert self._read({"present": False, "matches": False})

    def test_no_network_is(self):
        assert self._read(None)

    def test_on_the_operators_network_nothing_is_waited_for(self):
        assert self._read(None, mode=lan_fence.MODE_OPERATOR) is None

    @pytest.mark.parametrize("mode", [lan_fence.MODE_LEGACY, lan_fence.MODE_OFF, lan_fence.MODE_UNSUPPORTED])
    def test_a_mode_without_a_fence_is_a_problem(self, mode):
        assert "NET_ADMIN" in self._read(None, mode=mode)


# ---------------------------------------------------------------------------
# (i) A deploy and the guard never act on the same node at once
# ---------------------------------------------------------------------------


class TestTheGuardDuringADeploy:
    def test_it_starts_nothing_while_a_deploy_replaces_the_node(self, markers):
        node = _node(status="exited")
        with orchestrator.GATED_DEPLOY_LOCK:
            _guard([node])
        node.start.assert_not_called()

    def test_it_does_not_clear_the_record_by_reading_the_old_node(self, markers):
        # deploy_raw recorded the old node's identity and is about to stop it.
        orchestrator._remember_identity("cashpilot-mysterium", "0x" + "a" * 40)
        old = _node()
        old.exec_run.return_value = (0, b'{"id":"0x' + b"a" * 40 + b'"}')
        with orchestrator.GATED_DEPLOY_LOCK:
            _guard([old])
        assert (markers / "identity" / "cashpilot-mysterium").exists(), "the new node would never be compared"

    def test_it_still_stops_a_node_when_the_fence_goes(self, markers):
        node = _node()
        with orchestrator.GATED_DEPLOY_LOCK:
            _guard([node], problem="the LAN fence is not complete on this host")
        node.stop.assert_called_once()

    def test_control_once_the_deploy_is_done_it_starts_the_node(self, markers):
        node = _node(status="exited")
        _guard([node])
        node.start.assert_called_once()
        assert not orchestrator.GATED_DEPLOY_LOCK.locked()

    def test_deploy_raw_holds_the_lock_while_it_replaces_the_node(self, markers):
        seen = []
        old = MagicMock()
        old.name = "cashpilot-mysterium"
        old.status = "exited"
        old.labels = dict(LABELS)
        old.attrs = {"Mounts": []}
        old.stop.side_effect = lambda **_: seen.append(orchestrator.GATED_DEPLOY_LOCK.locked())
        _raw_deploy(old=old)
        assert seen == [True]
        assert not orchestrator.GATED_DEPLOY_LOCK.locked()

    def test_control_an_ordinary_earner_does_not_take_it(self, markers):
        seen = []
        old = MagicMock()
        old.name = "cashpilot-honeygain"
        old.status = "running"
        old.labels = {"cashpilot.service": "honeygain", "cashpilot.managed": "true"}
        old.attrs = {"Mounts": []}
        old.stop.side_effect = lambda **_: seen.append(orchestrator.GATED_DEPLOY_LOCK.locked())
        _raw_deploy(old=old, slug="honeygain")
        assert seen == [False]


# ---------------------------------------------------------------------------
# (j) Start and Restart refuse a node the guard holds stopped
# ---------------------------------------------------------------------------


def _start(node, action="start_service"):
    with (
        patch.object(orchestrator, "_find_container", return_value=node),
        patch.object(orchestrator, "_get_client", return_value=MagicMock()),
        patch.object(lan_fence, "fence_problem", return_value=None),
        patch.object(lan_fence, "resolve_mode", return_value=lan_fence.MODE_ON),
    ):
        getattr(orchestrator, action)("mysterium")


class TestStartRefusesAHeldNode:
    def test_a_node_held_for_another_identity_is_not_started(self, markers):
        orchestrator._remember_identity("cashpilot-mysterium", "MISMATCH its identity is 0xb, not 0xa")
        node = _node(status="exited")
        with pytest.raises(orchestrator.ContainerNetworkError, match="identity"):
            _start(node)
        node.start.assert_not_called()

    @pytest.mark.parametrize("action", ["start_service", "restart_service"])
    def test_a_node_on_the_host_network_is_not_started(self, markers, action):
        node = _node(status="exited", network_mode="host")
        with pytest.raises(orchestrator.ContainerNetworkError, match="host's network"):
            _start(node, action)
        node.start.assert_not_called()
        node.restart.assert_not_called()

    def test_control_a_node_as_the_catalog_says_starts(self, markers):
        orchestrator._mark_stopped("cashpilot-mysterium", True)
        node = _node(status="exited")
        _start(node)
        node.start.assert_called_once()
        assert "cashpilot-mysterium" not in orchestrator.user_stopped()
