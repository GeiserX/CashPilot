"""Mysterium is fenced like every other earner, and Docker never starts it unfenced.

Through 2.0.6 the node ran with ``network_mode: host`` and NET_ADMIN. That put
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

import contextlib
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
        assert ports["23000/udp"] == 23000 and ports["23029/udp"] == 23029

    def test_the_default_stays_below_linuxs_ephemeral_range(self):
        """Docker fails the whole publish on one port a host program holds, and 32768-60999 is where they take them."""
        default = next(e["default"] for e in MYST["docker"]["env"] if e["key"] == "UDP_PORTS")
        assert max(catalog.expand_udp_range(default).values()) < orchestrator.EPHEMERAL_PORTS[0]
        # Nor in the Kubernetes NodePort range just under it.
        assert max(catalog.expand_udp_range(default).values()) < 30000

    @pytest.mark.parametrize("value", ["56100:56000", "1:70000", "56000", "a:b", "56000-56100"])
    def test_anything_but_a_range_is_refused(self, value):
        with pytest.raises(ValueError):
            catalog.expand_udp_range(value)

    def test_a_range_over_the_cap_is_refused(self):
        with pytest.raises(ValueError, match="at most 300"):
            catalog.expand_udp_range("10000:10300")
        assert len(catalog.expand_udp_range("10000:10299")) == 300

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


#: What every Mysterium deployed through 2.0.6 has on record.
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
    monkeypatch.setattr(orchestrator, "_MISMATCH_HELD", {}, raising=False)
    monkeypatch.setattr(orchestrator, "FAILED_MARKER", str(tmp_path / "failed"), raising=False)
    monkeypatch.setattr(orchestrator, "_FAILED_UNWRITTEN", {}, raising=False)
    return tmp_path


def _up_on(network="cashpilot-isolated", running=True, address="172.30.0.2"):
    """attrs of a container that came up on ``network`` (inspect after start)."""
    return {
        "State": {"Running": running},
        "NetworkSettings": {"Networks": {network: {"IPAddress": address}}},
    }


def _not_found(name):
    raise orchestrator.NotFound(f"no {name}")


def _raw_deploy(problem=None, slug="mysterium", old=None, mode=lan_fence.MODE_ON, created=None, client=None, **kwargs):
    real = lan_fence.mode_problem
    if created is None:
        created = MagicMock(id="new", short_id="new")
        created.attrs = _up_on(
            orchestrator._CONTAINER_NETWORK if mode == lan_fence.MODE_OPERATOR else "cashpilot-isolated"
        )
    if client is None:
        client = MagicMock()
        if old is None:
            client.containers.get.side_effect = orchestrator.NotFound("nope")
        else:
            client.containers.get.side_effect = lambda n: old if n == old.name else _not_found(n)
        client.containers.create.return_value = created
        client.containers.run.return_value = created
    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        patch.object(orchestrator, "_CONTAINER_RUNTIME", "runsc"),
        patch.object(orchestrator, "available_runtimes", return_value={"runc", "runsc"}),
        patch("app.lan_fence.fence_problem", return_value=problem),
        patch("app.lan_fence.mode_problem", side_effect=lambda _mode, service="this service": real(mode, service)),
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


#: The 30-port default range, published 1:1 as the worker does.
UDP_BINDINGS = {f"{p}/udp": [{"HostIp": "", "HostPort": str(p)}] for p in range(23000, 23030)}


def _shape(network_mode="cashpilot-isolated", restart="no", image=PINNED, udp=True):
    attrs = {
        "Config": {"Image": image, "Env": ["UI_ADDRESS=127.0.0.1", "UDP_PORTS=23000:23029"]},
        "HostConfig": {
            "CapAdd": ["NET_ADMIN", "SETUID", "SETGID"],
            "NetworkMode": network_mode,
            "Devices": [{"PathInContainer": "/dev/net/tun"}],
            "PortBindings": {
                "4449/tcp": [{"HostIp": "127.0.0.1", "HostPort": "4449"}],
                **(UDP_BINDINGS if udp else {}),
            },
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
        assert "Redeploy them once to move them onto the fenced bridge" in found[0]["detail"]

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
        "HostConfig": {
            "NetworkMode": network_mode,
            "CapAdd": list(caps),
            "RestartPolicy": {"Name": "no"},
            "PortBindings": {"4449/tcp": [{"HostIp": "127.0.0.1", "HostPort": "4449"}], **UDP_BINDINGS},
        },
        "NetworkSettings": {"Networks": {network_mode: {"IPAddress": "172.30.0.2"}}},
        "State": {"Running": status == "running"},
    }
    c.exec_run.return_value = (1, b"")
    # docker-py's start; a reload then reads it running on its network.
    c.start.side_effect = lambda *a, **k: c.attrs["State"].update(Running=True)
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
    def test_one_pass_lists_the_managed_containers_once(self, markers):
        """Each list inspects every managed container; the guard runs every 30 s."""
        client = MagicMock()
        client.containers.list.return_value = [_node()]
        with (
            patch.object(orchestrator, "docker_available", return_value=True),
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(lan_fence, "resolve_mode", return_value=lan_fence.MODE_ON),
            patch.object(lan_fence, "fence_problem", return_value=None),
            patch.object(lan_fence, "apply_fence"),
        ):
            lan_fence.guard()
        assert client.containers.list.call_count == 1

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

    def test_on_the_operators_own_network_there_is_no_fence_to_wait_for(self, markers, monkeypatch):
        monkeypatch.setattr(orchestrator, "_CONTAINER_NETWORK", "operator-net")
        node = _node(status="exited", network_mode="operator-net")
        _guard([node], mode=lan_fence.MODE_OPERATOR)
        node.start.assert_called_once()

    @pytest.mark.parametrize("network_mode", ["bridge", "cashpilot-isolated"])
    def test_in_operator_mode_a_node_off_the_operators_network_is_held(self, markers, monkeypatch, network_mode):
        # Docker's default bridge has inter-container traffic on, and nothing of the operator's applies there.
        monkeypatch.setattr(orchestrator, "_CONTAINER_NETWORK", "operator-net")
        running, stopped = _node(network_mode=network_mode), _node(status="exited", network_mode=network_mode)
        held, _ = _guard([running, stopped], mode=lan_fence.MODE_OPERATOR)
        running.stop.assert_called_once()
        stopped.start.assert_not_called()
        assert "operator-net" in held["cashpilot-mysterium"]

    @pytest.mark.parametrize("mode", [lan_fence.MODE_LEGACY, lan_fence.MODE_OFF])
    def test_on_the_default_bridge_it_does_not_run_at_all(self, markers, mode):
        # Every other earner there reaches its WebUI, and nothing keeps it off the LAN.
        running, stopped = _node(network_mode="bridge"), _node(status="exited", network_mode="bridge")
        held, apply = _guard([running, stopped], problem=lan_fence.mode_problem(mode), mode=mode)
        running.stop.assert_called_once()
        stopped.start.assert_not_called()
        apply.assert_not_called()
        assert "runs only behind the LAN fence" in held["cashpilot-mysterium"]


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
        assert "runs only behind the LAN fence" in self._read(None, mode=mode)


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
    @pytest.mark.parametrize("action", ["start_service", "restart_service"])
    def test_a_node_a_failed_deploy_left_is_not_started(self, markers, action):
        orchestrator._mark_failed("cashpilot-mysterium", True)
        node = _node(status="exited")
        with pytest.raises(orchestrator.ContainerNetworkError, match="last deploy from CashPilot failed"):
            _start(node, action)
        node.start.assert_not_called()
        node.restart.assert_not_called()

    def test_a_node_held_for_another_identity_is_not_started(self, markers):
        orchestrator._remember_identity("cashpilot-mysterium", "MISMATCH its identity is 0xb, not 0xa")
        node = _node(status="exited")
        with pytest.raises(orchestrator.ContainerNetworkError, match="identity"):
            _start(node)
        node.start.assert_not_called()

    @pytest.mark.parametrize("action", ["start_service", "restart_service"])
    def test_a_node_with_a_capability_the_catalog_does_not_grant_is_not_started(self, markers, action):
        node = _node(status="exited", caps=("NET_ADMIN", "SETUID", "SETGID", "SYS_ADMIN"))
        with pytest.raises(orchestrator.ContainerNetworkError, match="SYS_ADMIN"):
            _start(node, action)
        node.start.assert_not_called()
        node.restart.assert_not_called()

    def test_control_a_node_as_the_catalog_says_starts(self, markers):
        orchestrator._mark_stopped("cashpilot-mysterium", True)
        node = _node(status="exited")
        _start(node)
        node.start.assert_called_once()
        assert "cashpilot-mysterium" not in orchestrator.user_stopped()


# ---------------------------------------------------------------------------
# (k) A node from 2.0.6 or earlier keeps running untouched until its redeploy
# ---------------------------------------------------------------------------


def _old_node(status="running"):
    """What every Mysterium through 2.0.6 is: host network, unless-stopped, an unpinned image."""
    c = _node(status=status, network_mode="host", image="mysteriumnetwork/myst")
    c.attrs["HostConfig"]["RestartPolicy"] = {"Name": "unless-stopped"}
    return c


class TestAnOldHostNetworkNode:
    @pytest.mark.parametrize("mode", [lan_fence.MODE_ON, lan_fence.MODE_LEGACY, lan_fence.MODE_OFF])
    def test_the_guard_leaves_a_running_one_alone(self, markers, mode):
        node = _old_node()
        held, _ = _guard([node], problem=lan_fence.mode_problem(mode), mode=mode)
        node.stop.assert_not_called()
        node.start.assert_not_called()
        node.restart.assert_not_called()
        node.exec_run.assert_not_called()
        assert held == {}

    def test_the_guard_leaves_it_alone_when_the_fence_goes_too(self, markers):
        node = _old_node()
        _guard([node], problem="the LAN fence is not complete on this host")
        node.stop.assert_not_called()

    def test_the_guard_does_not_start_a_stopped_one(self, markers):
        node = _old_node(status="exited")
        _guard([node])
        node.start.assert_not_called()

    @pytest.mark.parametrize("action", ["start_service", "restart_service"])
    def test_start_and_restart_work_as_before_in_legacy_mode(self, markers, action):
        node = _old_node(status="exited")
        with (
            patch.object(orchestrator, "_find_container", return_value=node),
            patch.object(orchestrator, "_get_client", return_value=MagicMock()),
            patch.object(lan_fence, "resolve_mode", return_value=lan_fence.MODE_LEGACY),
        ):
            getattr(orchestrator, action)("mysterium")
        assert node.start.called or node.restart.called

    def test_stop_records_nothing_for_the_guard(self, markers):
        node = _old_node()
        with patch.object(orchestrator, "_find_container", return_value=node):
            orchestrator.stop_service("mysterium")
        node.stop.assert_called_once()
        assert orchestrator.user_stopped() == set()

    def test_a_redeploy_in_legacy_mode_is_refused_and_says_what_to_do(self, markers):
        old = _old_node()
        with pytest.raises(orchestrator.ContainerNetworkError) as refused:
            _raw_deploy(old=old, mode=lan_fence.MODE_LEGACY)
        # The catalog's name, the one on the dashboard card the owner redeploys from.
        assert f"Switch isolation on in Fleet first, then redeploy {MYST['name']} once" in str(refused.value)
        old.stop.assert_not_called()
        old.remove.assert_not_called()

    def test_drift_still_flags_it_and_gives_the_order(self):
        found = " ".join(drift.container_drift(MYST, _shape(network_mode="host"), HOST_RECORD))
        assert "shares the host's network" in found
        move = drift.move_advice(MYST, _shape(network_mode="host"), HOST_RECORD, lan_fence.MODE_LEGACY)
        assert move["action"].startswith(f"Switch isolation on in Fleet first, then redeploy {MYST['name']} once")

    def test_control_a_fence_gated_one_in_legacy_mode_is_stopped(self, markers):
        node = _node(network_mode="bridge")
        _guard([node], problem=lan_fence.mode_problem(lan_fence.MODE_LEGACY), mode=lan_fence.MODE_LEGACY)
        node.stop.assert_called_once()


# ---------------------------------------------------------------------------
# (l) Review round: the guard fails closed, Stop stays a stop, nothing escapes it
# ---------------------------------------------------------------------------


class TestStopStaysAStop:
    def test_stop_holds_the_guards_lock_and_records_first(self, markers):
        node = _node()
        seen = {}

        def stopping(**_):
            seen["locked"] = orchestrator.GATED_DEPLOY_LOCK.locked()
            seen["recorded"] = "cashpilot-mysterium" in orchestrator.user_stopped()

        node.stop.side_effect = stopping
        with patch.object(orchestrator, "_find_container", return_value=node):
            orchestrator.stop_service("mysterium")
        assert seen == {"locked": True, "recorded": True}
        assert not orchestrator.GATED_DEPLOY_LOCK.locked()

    def test_a_guard_pass_that_read_the_records_first_cannot_start_it_after(self, markers):
        """The guard holds the lock from reading the records to its start, so Stop waits for it."""
        node = _node(status="exited")
        with patch.object(orchestrator, "_find_container", return_value=node):
            orchestrator.GATED_DEPLOY_LOCK.acquire()
            try:
                import threading

                stopper = threading.Thread(target=orchestrator.stop_service, args=("mysterium",))
                stopper.start()
                stopper.join(0.3)
                assert stopper.is_alive(), "Stop must wait for the guard pass"
                assert orchestrator.user_stopped() == set()
            finally:
                orchestrator.GATED_DEPLOY_LOCK.release()
            stopper.join(5)
        assert orchestrator.user_stopped() == {"cashpilot-mysterium"}

    def test_a_stop_that_cannot_be_recorded_fails_and_says_so(self, markers, monkeypatch):
        monkeypatch.setattr(orchestrator, "STOPPED_MARKER", str(markers / "missing-dir" / "stopped"))
        node = _node()
        with (
            patch.object(orchestrator, "_find_container", return_value=node),
            pytest.raises(orchestrator.ContainerRuntimeError, match="could not be recorded"),
        ):
            orchestrator.stop_service("mysterium")
        node.stop.assert_not_called()

    def test_control_an_ordinary_earner_stops_without_a_record(self, markers, monkeypatch):
        monkeypatch.setattr(orchestrator, "STOPPED_MARKER", str(markers / "missing-dir" / "stopped"))
        node = MagicMock()
        node.name = "cashpilot-honeygain"
        with patch.object(orchestrator, "_find_container", return_value=node):
            orchestrator.stop_service("honeygain")
        node.stop.assert_called_once()


class TestTheGuardFailsClosed:
    def test_a_mode_it_cannot_read_stops_the_node(self, markers):
        node = _node()
        client = MagicMock()
        client.containers.list.return_value = [node]
        with (
            patch.object(orchestrator, "docker_available", return_value=True),
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(lan_fence, "resolve_mode", side_effect=RuntimeError("docker info failed")),
            patch.object(lan_fence, "apply_fence") as apply,
        ):
            held = lan_fence.guard()
        node.stop.assert_called_once()
        node.start.assert_not_called()
        apply.assert_not_called()
        assert "could not be read" in held["cashpilot-mysterium"]

    def test_control_a_mode_it_reads_leaves_a_fenced_node_running(self, markers):
        node = _node()
        _guard([node])
        node.stop.assert_not_called()

    def test_a_node_also_attached_to_another_network_is_stopped(self, markers):
        node = _node()
        node.attrs["NetworkSettings"] = {"Networks": {"cashpilot-isolated": {}, "bridge": {}}}
        held, _ = _guard([node])
        node.stop.assert_called_once()
        assert "bridge" in held["cashpilot-mysterium"]

    def test_control_a_node_on_its_one_network_is_left_alone(self, markers):
        node = _node()
        node.attrs["NetworkSettings"] = {"Networks": {"cashpilot-isolated": {}}}
        _guard([node])
        node.stop.assert_not_called()


class TestTheFenceReadChecksTheNetwork:
    def _net(self, **options):
        opts = dict(lan_fence._REQUIRED_OPTIONS, **options)
        return SimpleNamespace(attrs={"Driver": "bridge", "Options": opts})

    def test_a_network_recreated_on_another_interface_is_not_a_fence(self):
        net = self._net(**{"com.docker.network.bridge.name": "br-other"})
        with (
            patch.object(lan_fence, "resolve_mode", return_value=lan_fence.MODE_ON),
            patch.object(lan_fence, "managed_network", return_value=net),
            patch.object(lan_fence, "run_helper", return_value={"present": True, "matches": True}) as helper,
        ):
            problem = lan_fence.fence_problem(MagicMock())
        assert problem and "bridge.name" in problem
        helper.assert_not_called()

    def test_control_the_network_as_created_reads_the_table(self):
        with (
            patch.object(lan_fence, "resolve_mode", return_value=lan_fence.MODE_ON),
            patch.object(lan_fence, "managed_network", return_value=self._net()),
            patch.object(lan_fence, "_subnet", return_value="172.30.0.0/24"),
            patch.object(lan_fence, "run_helper", return_value={"present": True, "matches": True}) as helper,
        ):
            assert lan_fence.fence_problem(MagicMock()) is None
        helper.assert_called_once()


class TestTheDeployKeepsWhatTheGuardReliesOn:
    def test_a_caller_cannot_relabel_the_node_out_of_the_guards_sight(self, markers):
        client, _ = _raw_deploy(labels={"cashpilot.service": "other", "cashpilot.managed": "false", "x": "1"})
        labels = client.containers.create.call_args.kwargs["labels"]
        assert labels["cashpilot.service"] == "mysterium"
        assert labels["cashpilot.managed"] == "true"
        assert labels["x"] == "1"

    def _replacement(self, status):
        old = MagicMock()
        old.name = "cashpilot-mysterium"
        old.status = status
        old.labels = dict(LABELS)
        old.attrs = {"Mounts": []}
        old.exec_run.return_value = (1, b"")
        return old

    def test_a_retry_over_an_unconfirmed_replacement_keeps_the_identity_to_match(self, markers):
        orchestrator._remember_identity("cashpilot-mysterium", "0xa")
        _raw_deploy(old=self._replacement("created"))
        assert orchestrator._pending_identity("cashpilot-mysterium") == "0xa"

    def test_a_retry_over_a_running_replacement_keeps_it_too(self, markers):
        orchestrator._remember_identity("cashpilot-mysterium", "0xa")
        _raw_deploy(old=self._replacement("running"))
        assert orchestrator._pending_identity("cashpilot-mysterium") == "0xa"

    def test_control_a_redeploy_over_a_held_mismatch_clears_it(self, markers):
        """The owner's way out once they restored the volume, as the hold says."""
        orchestrator._remember_identity("cashpilot-mysterium", "MISMATCH its identity is 0xb, not 0xa")
        _raw_deploy(old=self._replacement("exited"))
        assert orchestrator.identity_problem(self._replacement("exited")) is None

    def test_control_a_redeploy_over_a_stopped_node_with_no_record_records_nothing(self, markers):
        _raw_deploy(old=self._replacement("exited"))
        assert orchestrator._pending_identity("cashpilot-mysterium") is None


class TestNoComposeExport:
    def test_mysterium_has_no_compose_export(self):
        from app import compose_generator

        with pytest.raises(ValueError, match="LAN fence"):
            compose_generator.generate_compose_single("mysterium")

    def test_a_multi_export_leaves_it_out(self):
        from app import compose_generator

        exported = yaml.safe_load(compose_generator.generate_compose_multi(["mysterium", "bitping"]))
        assert list(exported["services"]) == ["cashpilot-bitping"]


class TestTheMessagesNameTheService:
    def test_the_mode_refusal_names_the_service_it_is_given(self):
        problem = lan_fence.mode_problem(lan_fence.MODE_LEGACY, "Other")
        assert "Other runs only behind the LAN fence" in problem
        assert problem.endswith(
            "Switch isolation on in Fleet first, then redeploy Other once to move it onto the fenced bridge."
        )

    def test_drift_names_the_service_and_claims_no_capability_it_lacks(self):
        other = {**MYST, "name": "Other", "docker": {**MYST["docker"], "cap_add": []}}
        shape = _shape(network_mode="host")
        shape["cap_add"] = []
        found = " ".join(drift.container_drift(other, shape, None))
        assert "NET_ADMIN" not in found
        assert "Redeploy Other once" in drift.move_advice(other, shape, None, lan_fence.MODE_ON)["action"]

    def test_drift_flags_a_node_that_publishes_its_webui_but_not_its_range(self):
        found = drift.container_drift(MYST, _shape(udp=False), None)
        assert any("does not publish port" in f and "23000/udp" in f for f in found)

    def test_drift_judges_the_range_on_record(self):
        record = {"env": {"UDP_PORTS": "56000:56100"}}
        found = drift.container_drift(MYST, _shape(), record)
        assert any("56100/udp" in f for f in found)

    def test_the_container_down_alert_does_not_promise_a_restart_policy(self):
        from datetime import UTC, datetime

        from app import main as main_mod

        copies = [{"_down_since": datetime.now(UTC), "_node": "w1", "restart_policy": "no", "exit_code": 0}]
        message = main_mod._container_down_message("mysterium", copies)
        assert "unless-stopped" not in message
        assert "LAN fence" in message
        control = main_mod._container_down_message("honeygain", copies)
        assert "sets unless-stopped" in control


def test_a_ui_default_on_any_loopback_address_is_no_inbound_exception():
    from app import lan_isolation

    def svc(default):
        return {"docker": {"ui_port": {"env": "UI", "port": 4449}, "env": [{"key": "UI", "default": default}]}}

    assert lan_isolation.published_ports(svc("127.0.0.2")) == []
    assert lan_isolation.published_ports(svc("::1,localhost")) == []
    assert lan_isolation.published_ports(svc("192.168.1.5")) == ["192.168.1.5:4449"]


# ---------------------------------------------------------------------------
# (m) The upgrade: the old node keeps earning, the Fleet page offers the move,
#     and the move compares the identity with the node it replaces
# ---------------------------------------------------------------------------

IDENTITY_A = "0x" + "a" * 40
IDENTITY_B = "0x" + "b" * 40


def _says(identity):
    return (0, b'{"identities":[{"id":"' + identity.encode() + b'"}]}')


class TestTheUpgrade:
    @pytest.mark.parametrize("mode", [lan_fence.MODE_ON, lan_fence.MODE_LEGACY])
    def test_the_old_node_keeps_running_and_the_fleet_page_is_told(self, markers, mode):
        node = _old_node()
        problem = None if mode == lan_fence.MODE_ON else lan_fence.mode_problem(mode)
        _guard([node], problem=problem, mode=mode)
        node.stop.assert_not_called()
        node.restart.assert_not_called()
        node.remove.assert_not_called()
        assert lan_fence.status()["unfenced"] == [
            {"name": "cashpilot-mysterium", "slug": "mysterium", "service": MYST["name"]}
        ]

    def test_control_a_fenced_node_is_not_reported_as_unfenced(self, markers):
        _guard([_node()])
        assert lan_fence.status()["unfenced"] == []

    def _old_with_data(self, identity):
        old = _old_node()
        old.attrs["Mounts"] = [
            {"Type": "bind", "Source": "/mnt/appdata/myst/data", "Destination": "/var/lib/mysterium-node", "RW": True}
        ]
        old.exec_run.return_value = _says(identity)
        return old

    def test_the_redeploy_reads_the_running_old_nodes_identity_before_replacing_it(self, markers):
        old = self._old_with_data(IDENTITY_A)
        order = []
        old.exec_run.side_effect = lambda *a, **k: order.append("read") or _says(IDENTITY_A)
        old.stop.side_effect = lambda **_: order.append("stop")
        old.remove.side_effect = lambda **_: order.append("remove")
        client, _ = _raw_deploy(old=old, volumes={"mysterium-data": {"bind": "/var/lib/mysterium-node", "mode": "rw"}})
        assert order[0] == "read" and "stop" in order
        assert orchestrator._pending_identity("cashpilot-mysterium") == IDENTITY_A
        volumes = client.containers.create.call_args.kwargs["volumes"]
        assert "/mnt/appdata/myst/data" in str(volumes), "the node's own data must come with it"

    def test_a_different_identity_after_the_move_holds_it_and_keeps_the_volume(self, markers):
        _raw_deploy(old=self._old_with_data(IDENTITY_A))
        new = _node()
        new.exec_run.return_value = _says(IDENTITY_B)
        held, _ = _guard([new])
        new.stop.assert_called_once()
        new.remove.assert_not_called()
        assert IDENTITY_A in held["cashpilot-mysterium"] and IDENTITY_B in held["cashpilot-mysterium"]
        # Sticky: stopped, it reads no identity, and it still is not started.
        stopped = _node(status="exited")
        _guard([stopped])
        stopped.start.assert_not_called()

    def test_control_the_same_identity_after_the_move_runs(self, markers):
        _raw_deploy(old=self._old_with_data(IDENTITY_A))
        new = _node()
        new.exec_run.return_value = _says(IDENTITY_A)
        held, _ = _guard([new])
        new.stop.assert_not_called()
        assert held == {}
        assert orchestrator._pending_identity("cashpilot-mysterium") is None


def test_the_fleet_page_offers_the_move_and_says_isolation_first():
    fleet = (ROOT / "app" / "templates" / "fleet.html").read_text(encoding="utf-8")
    assert "iso.unfenced" in fleet
    assert "to move behind the fence</button>" in fleet
    assert "Switch isolation on first, then redeploy it once" in fleet
    assert "moveBehindFence(" in fleet


class TestAHoldThatCannotBeWritten:
    """Found in the lab: a pending record the worker could not overwrite let the guard restart the node each pass."""

    def _unwritable(self, markers):
        orchestrator._remember_identity("cashpilot-mysterium", IDENTITY_A)
        (markers / "identity").chmod(0o500)
        (markers / "identity" / "cashpilot-mysterium").chmod(0o400)

    def test_the_hold_survives_and_the_node_is_not_started_again(self, markers):
        self._unwritable(markers)
        try:
            new = _node()
            new.exec_run.return_value = _says(IDENTITY_B)
            _guard([new])
            new.stop.assert_called_once()
            stopped = _node(status="exited")
            held, _ = _guard([stopped])
            stopped.start.assert_not_called()
            assert IDENTITY_B in held["cashpilot-mysterium"]
            with pytest.raises(orchestrator.ContainerNetworkError, match="identity"):
                _start(_node(status="exited"))
        finally:
            (markers / "identity").chmod(0o700)

    def test_control_a_redeploy_lifts_the_hold(self, markers):
        self._unwritable(markers)
        try:
            new = _node()
            new.exec_run.return_value = _says(IDENTITY_B)
            _guard([new])
        finally:
            (markers / "identity").chmod(0o700)
            (markers / "identity" / "cashpilot-mysterium").chmod(0o600)
        orchestrator._remember_identity("cashpilot-mysterium", None)
        stopped = _node(status="exited")
        _guard([stopped])
        stopped.start.assert_called_once()


def test_a_failed_scan_drops_the_unfenced_report(markers):
    """No Fleet button on a report the worker could not refresh."""
    _guard([_old_node()])
    assert lan_fence.status()["unfenced"]
    client = MagicMock()
    client.containers.list.side_effect = RuntimeError("docker is gone")
    with (
        patch.object(orchestrator, "docker_available", return_value=True),
        patch.object(orchestrator, "_get_client", return_value=client),
    ):
        lan_fence.guard()
    assert lan_fence.status()["unfenced"] == []


def test_a_later_failure_in_the_pass_keeps_a_fresh_unfenced_report(markers):
    """Another node failing to start does not hide the move of the one on the host network."""
    old = _old_node()
    other = _node(status="exited")
    other.name = "cashpilot-mysterium-2"
    other.start.side_effect = RuntimeError("the start failed")
    _guard([old, other])
    other.start.assert_called_once()
    assert [u["name"] for u in lan_fence.status()["unfenced"]] == ["cashpilot-mysterium"]


def test_the_fleet_page_does_not_offer_a_move_it_just_made():
    fleet = (ROOT / "app" / "templates" / "fleet.html").read_text(encoding="utf-8")
    assert "_movedBehindFence.add(" in fleet
    assert "!_movedBehindFence.has(" in fleet


class TestTheMoveNeedsTheOldIdentity:
    def test_a_running_node_whose_identity_cannot_be_read_is_not_replaced(self, markers):
        old = _node()
        old.exec_run.return_value = (1, b"")
        old.attrs["Mounts"] = []
        with pytest.raises(orchestrator.ContainerRuntimeError, match="not touched"):
            _raw_deploy(old=old)
        old.stop.assert_not_called()
        old.remove.assert_not_called()

    def test_the_refusal_keeps_a_hold_kept_only_in_memory(self, markers):
        # No record on disk: the hold could not be written, so memory is all there is.
        orchestrator._MISMATCH_HELD["cashpilot-mysterium"] = "its identity is 0xb, not 0xa"
        old = _node()
        old.exec_run.return_value = (1, b"")
        old.attrs["Mounts"] = []
        with pytest.raises(orchestrator.ContainerRuntimeError, match="not touched"):
            _raw_deploy(old=old)
        assert orchestrator._MISMATCH_HELD.get("cashpilot-mysterium") == "its identity is 0xb, not 0xa"
        assert "0xb" in orchestrator.identity_problem(_node(status="exited"))

    def test_the_refusal_leaves_the_record_on_disk_alone(self, markers):
        # Written by someone else while the deploy ran: the refusal must not undo it.
        old = _node()
        old.exec_run.return_value = (1, b"")
        old.attrs["Mounts"] = []
        real = orchestrator.read_node_identity

        def read_and_race(container, slug):
            orchestrator._remember_identity("cashpilot-mysterium", "MISMATCH written meanwhile")
            return real(container, slug)

        with (
            patch.object(orchestrator, "read_node_identity", side_effect=read_and_race),
            pytest.raises(orchestrator.ContainerRuntimeError, match="not touched"),
        ):
            _raw_deploy(old=old)
        assert orchestrator._identity_snapshot("cashpilot-mysterium") == "MISMATCH written meanwhile"

    def test_the_refusal_keeps_a_hold_set_while_it_ran(self, markers):
        orchestrator._MISMATCH_HELD["cashpilot-mysterium"] = "the older reason"
        old = _node()
        old.exec_run.return_value = (1, b"")
        old.attrs["Mounts"] = []
        real = orchestrator.read_node_identity

        def read_and_race(container, slug):
            orchestrator._MISMATCH_HELD["cashpilot-mysterium"] = "the newer reason"
            return real(container, slug)

        with (
            patch.object(orchestrator, "read_node_identity", side_effect=read_and_race),
            pytest.raises(orchestrator.ContainerRuntimeError, match="not touched"),
        ):
            _raw_deploy(old=old)
        assert orchestrator._MISMATCH_HELD["cashpilot-mysterium"] == "the newer reason"

    def test_control_a_stopped_node_is_replaced_without_the_check(self, markers):
        old = _node(status="exited")
        old.exec_run.return_value = (1, b"")
        old.attrs["Mounts"] = []
        _raw_deploy(old=old)
        old.remove.assert_called_once()

    def test_a_redeploy_lifts_a_hold_kept_only_in_memory(self, markers):
        orchestrator._remember_identity("cashpilot-mysterium", IDENTITY_A)
        orchestrator._MISMATCH_HELD["cashpilot-mysterium"] = "its identity is 0xb, not 0xa"
        old = _node(status="exited")
        old.attrs["Mounts"] = []
        _raw_deploy(old=old)
        assert "cashpilot-mysterium" not in orchestrator._MISMATCH_HELD
        # The identity to match is kept, so the restored volume is still checked.
        assert orchestrator._pending_identity("cashpilot-mysterium") == IDENTITY_A


# ---------------------------------------------------------------------------
# (n) A deploy Docker refuses puts the old node back; the guard never starts
#     what a failed deploy left; the default range is out of the ephemeral one
# ---------------------------------------------------------------------------

BIND_REFUSED = "failed to bind host port 0.0.0.0:56033/udp: address already in use"


class _FakeDocker:
    """Containers by name, with rename and remove, so a roll-back can be followed."""

    def __init__(self, *containers):
        self.by_name = {}
        self.client = MagicMock()
        self.client.containers.get.side_effect = self.get
        self.client.containers.create.side_effect = self.create
        self.client.containers.run.side_effect = self.create
        self.created = MagicMock(id="new", short_id="new")
        self.created.attrs = _up_on()
        for c in containers:
            self.add(c)

    def add(self, c):
        self.by_name[c.name] = c
        if not isinstance(getattr(c, "remove_error", None), BaseException):
            c.remove_error = None

        def rename(new, c=c):
            self.by_name.pop(c.name, None)
            c.name = new
            self.by_name[new] = c

        def remove(c=c, **_):
            if getattr(c, "remove_error", None):
                raise c.remove_error
            self.by_name.pop(c.name, None)
            c.removed = True

        c.rename.side_effect = rename
        c.remove.side_effect = remove
        c.removed = False

    def get(self, name):
        if name in self.by_name:
            return self.by_name[name]
        raise orchestrator.NotFound(f"no {name}")

    def create(self, **kwargs):
        self.created.name = kwargs["name"]
        self.add(self.created)
        if getattr(self, "create_error", None):
            raise self.create_error
        return self.created


def _running_old(name="cashpilot-mysterium", labels=None, status="running"):
    old = MagicMock()
    old.name = name
    old.status = status
    old.labels = dict(labels or LABELS)
    old.attrs = {"Mounts": []}
    old.exec_run.return_value = _says(IDENTITY_A)
    return old


def _api_error(text):
    return orchestrator.APIError("500 Server Error", explanation=text)


class TestARefusedDeployPutsTheOldNodeBack:
    def test_a_refused_start_puts_the_running_node_back_and_running(self, markers):
        old = _running_old()
        docker = _FakeDocker(old)
        docker.created.start.side_effect = _api_error(BIND_REFUSED)
        with pytest.raises(orchestrator.ContainerRuntimeError) as refused:
            _raw_deploy(client=docker.client, old=old)
        message = str(refused.value)
        assert "56033/udp" in message and "ephemeral range" in message
        assert "put back and is running again" in message
        assert docker.get("cashpilot-mysterium") is old and not old.removed
        old.start.assert_called_once()
        assert docker.created.removed

    def test_the_identity_record_is_as_it_was(self, markers):
        orchestrator._remember_identity("cashpilot-mysterium", "MISMATCH its identity is 0xb, not 0xa")
        before = orchestrator._identity_snapshot("cashpilot-mysterium")
        old = _running_old(status="exited")
        docker = _FakeDocker(old)
        docker.created.start.side_effect = _api_error(BIND_REFUSED)
        with pytest.raises(orchestrator.ContainerRuntimeError):
            _raw_deploy(client=docker.client, old=old)
        assert orchestrator._identity_snapshot("cashpilot-mysterium") == before
        assert "0xb" in orchestrator.identity_problem(_node(status="exited"))

    def test_a_hold_kept_only_in_memory_comes_back(self, markers):
        # The record says which identity to match; the hold could not be written.
        orchestrator._remember_identity("cashpilot-mysterium", IDENTITY_A)
        orchestrator._MISMATCH_HELD["cashpilot-mysterium"] = "its identity is 0xb, not 0xa"
        old = _running_old(status="exited")
        docker = _FakeDocker(old)
        docker.created.start.side_effect = _api_error(BIND_REFUSED)
        with pytest.raises(orchestrator.ContainerRuntimeError):
            _raw_deploy(client=docker.client, old=old)
        assert orchestrator._pending_identity("cashpilot-mysterium") == IDENTITY_A
        assert "0xb" in orchestrator.identity_problem(_node(status="exited"))

    def test_a_record_the_deploy_wrote_is_taken_back(self, markers):
        old = _running_old()
        docker = _FakeDocker(old)
        docker.created.start.side_effect = _api_error(BIND_REFUSED)
        with pytest.raises(orchestrator.ContainerRuntimeError):
            _raw_deploy(client=docker.client, old=old)
        assert orchestrator._identity_snapshot("cashpilot-mysterium") is None

    def test_a_refused_create_puts_it_back_too(self, markers):
        old = _running_old()
        docker = _FakeDocker(old)
        docker.create_error = _api_error("Conflict. The container name is already in use")
        with pytest.raises(orchestrator.ContainerRuntimeError, match="put back"):
            _raw_deploy(client=docker.client, old=old)
        assert docker.get("cashpilot-mysterium") is old
        old.start.assert_called_once()

    def test_a_node_the_owner_had_stopped_goes_back_stopped(self, markers):
        orchestrator._mark_stopped("cashpilot-mysterium", True)
        old = _running_old(status="exited")
        docker = _FakeDocker(old)
        docker.created.start.side_effect = _api_error(BIND_REFUSED)
        with pytest.raises(orchestrator.ContainerRuntimeError, match="stopped as it was"):
            _raw_deploy(client=docker.client, old=old)
        old.start.assert_not_called()
        assert "cashpilot-mysterium" in orchestrator.user_stopped()

    def test_a_new_node_with_no_network_is_rolled_back(self, markers):
        old = _running_old()
        docker = _FakeDocker(old)
        docker.created.attrs = _up_on(address="")
        with (
            patch("app.lan_fence.resolve_mode", return_value=lan_fence.MODE_ON),
            patch("app.lan_fence.network_for_deploy", return_value="cashpilot-isolated"),
            pytest.raises(orchestrator.ContainerRuntimeError, match="no address on cashpilot-isolated"),
        ):
            _raw_deploy(client=docker.client, old=old)
        assert docker.get("cashpilot-mysterium") is old

    def test_a_leftover_that_cannot_be_removed_is_marked_and_the_old_one_kept_aside(self, markers):
        old = _running_old()
        docker = _FakeDocker(old)
        docker.created.start.side_effect = _api_error(BIND_REFUSED)
        docker.created.remove_error = _api_error("removal of container is already in progress")
        with pytest.raises(orchestrator.ContainerRuntimeError, match="cashpilot-mysterium-replaced"):
            _raw_deploy(client=docker.client, old=old)
        assert old.name == "cashpilot-mysterium-replaced" and not old.removed
        assert "cashpilot-mysterium" in orchestrator.deploy_failed()

    def test_an_ordinary_earner_is_put_back_too(self, markers):
        old = _running_old("cashpilot-honeygain", {"cashpilot.service": "honeygain", "cashpilot.managed": "true"})
        docker = _FakeDocker(old)
        docker.create_error = _api_error("failed to bind host port 0.0.0.0:8080/tcp: address already in use")
        with pytest.raises(orchestrator.ContainerRuntimeError, match="running again"):
            _raw_deploy(client=docker.client, old=old, slug="honeygain")
        assert docker.get("cashpilot-honeygain") is old
        old.start.assert_called_once()

    def test_control_a_deploy_that_runs_removes_the_old_one_after(self, markers):
        orchestrator._mark_failed("cashpilot-mysterium", True)
        old = _running_old()
        docker = _FakeDocker(old)
        order = []
        docker.created.start.side_effect = lambda: order.append("new started")
        old.remove.side_effect = lambda **_: order.append("old removed")
        _raw_deploy(client=docker.client, old=old)
        assert order == ["new started", "old removed"]
        assert orchestrator._pending_identity("cashpilot-mysterium") == IDENTITY_A
        assert orchestrator.deploy_failed() == set()

    def test_a_deploy_that_runs_lifts_a_mark_the_file_cannot_drop(self, markers, monkeypatch):
        orchestrator._mark_failed("cashpilot-mysterium", True)
        real_open = open

        def read_only_marker(path, mode="r", *a, **k):
            if path == orchestrator.FAILED_MARKER and "w" in mode:
                raise PermissionError(13, "Permission denied", path)
            return real_open(path, mode, *a, **k)

        monkeypatch.setattr(orchestrator, "open", read_only_marker, raising=False)
        old = _running_old()
        _raw_deploy(client=_FakeDocker(old).client, old=old)
        assert orchestrator.deploy_failed() == set()
        node = _node(status="exited")
        _guard([node])
        node.start.assert_called_once()


class TestAMoveAsideThatFails:
    def test_an_old_node_that_can_neither_move_nor_go_runs_again(self, markers):
        old = _running_old()
        old.remove_error = _api_error("removal of container is already in progress")
        docker = _FakeDocker(old)
        old.rename.side_effect = _api_error("rename refused")
        with pytest.raises(orchestrator.ContainerRuntimeError, match="not replaced and is running again"):
            _raw_deploy(client=docker.client, old=old)
        old.start.assert_called_once()
        docker.client.containers.create.assert_not_called()
        assert orchestrator._identity_snapshot("cashpilot-mysterium") is None

    def test_a_refused_rename_never_removes_the_old_node(self, markers):
        old = _running_old()
        docker = _FakeDocker(old)
        old.rename.side_effect = _api_error("rename refused")
        with pytest.raises(orchestrator.ContainerRuntimeError, match="running again"):
            _raw_deploy(client=docker.client, old=old)
        assert not old.removed and docker.get("cashpilot-mysterium") is old
        old.start.assert_called_once()
        docker.client.containers.create.assert_not_called()

    def test_a_move_aside_that_times_out_puts_the_old_node_back_running(self, markers):
        old = _running_old()
        docker = _FakeDocker(old)

        def renamed_then_timed_out(new):
            docker.by_name.pop(old.name, None)
            old.name = new
            docker.by_name[new] = old
            old.attrs["Name"] = "/" + new
            old.rename.side_effect = lambda back: old.attrs.update(Name="/" + back)
            raise ConnectionError("read timed out")

        old.rename.side_effect = renamed_then_timed_out
        with pytest.raises(orchestrator.ContainerRuntimeError, match="running again"):
            _raw_deploy(client=docker.client, old=old)
        assert old.attrs["Name"] == "/cashpilot-mysterium"
        old.start.assert_called_once()
        docker.client.containers.create.assert_not_called()

    def test_a_stop_that_times_out_on_a_running_node_is_not_replaced(self, markers):
        old = _running_old()
        docker = _FakeDocker(old)
        old.stop.side_effect = ConnectionError("read timed out")
        with pytest.raises(orchestrator.ContainerRuntimeError, match="could not be stopped"):
            _raw_deploy(client=docker.client, old=old)
        old.rename.assert_not_called()

    def test_an_old_node_that_will_not_stop_is_not_replaced(self, markers):
        old = _running_old()
        docker = _FakeDocker(old)
        old.stop.side_effect = _api_error("tried to kill container, but did not receive an exit event")
        with pytest.raises(orchestrator.ContainerRuntimeError, match="could not be stopped"):
            _raw_deploy(client=docker.client, old=old)
        old.rename.assert_not_called()
        docker.client.containers.create.assert_not_called()

    def test_control_a_failed_stop_of_a_node_that_did_stop_goes_ahead(self, markers):
        old = _running_old()
        docker = _FakeDocker(old)

        def stopped_anyway(**_):
            old.status = "exited"
            raise _api_error("tried to kill container, but did not receive an exit event")

        old.stop.side_effect = stopped_anyway
        _raw_deploy(client=docker.client, old=old)
        docker.created.start.assert_called_once()

    def test_an_aside_name_another_service_holds_is_refused_before_anything_moves(self, markers):
        old = _running_old()
        other = _running_old(
            "cashpilot-mysterium-replaced", {"cashpilot.service": "mysterium-replaced", "cashpilot.managed": "true"}
        )
        docker = _FakeDocker(old, other)
        with pytest.raises(orchestrator.ContainerRuntimeError, match="belongs to mysterium-replaced"):
            _raw_deploy(client=docker.client, old=old)
        old.stop.assert_not_called()
        assert not other.removed

    def test_a_new_node_the_fence_went_under_clears_the_failed_mark(self, markers):
        orchestrator._mark_failed("cashpilot-mysterium", True)
        old = _running_old()
        docker = _FakeDocker(old)
        with (
            patch.object(orchestrator, "_require_fence", side_effect=orchestrator.ContainerNetworkError("gone")),
            pytest.raises(orchestrator.ContainerNetworkError),
        ):
            _raw_deploy(client=docker.client, old=old)
        assert orchestrator.deploy_failed() == set()

    def test_a_name_another_deploy_took_is_left_to_it(self, markers):
        old = _running_old()
        docker = _FakeDocker(old)
        other = MagicMock(id="other", status="running")
        other.name = "cashpilot-mysterium"

        def taken(*_a, **_k):
            docker.by_name["cashpilot-mysterium"] = other
            raise _api_error("container is not running")

        docker.created.start.side_effect = taken
        with pytest.raises(orchestrator.ContainerRuntimeError, match="Another deploy took the name"):
            _raw_deploy(client=docker.client, old=old)
        other.remove.assert_not_called()
        assert docker.get("cashpilot-mysterium-replaced") is old
        old.start.assert_not_called()

    def test_the_old_node_waits_for_the_fence_before_it_runs_again(self, markers):
        old = _running_old()
        docker = _FakeDocker(old)

        def fence_gone(*_a, **_k):
            lan_fence.fence_problem.return_value = "the LAN fence is not complete on this host"
            raise _api_error(BIND_REFUSED)

        docker.created.start.side_effect = fence_gone
        with pytest.raises(orchestrator.ContainerRuntimeError, match="kept stopped until the LAN fence"):
            _raw_deploy(client=docker.client, old=old)
        assert docker.get("cashpilot-mysterium") is old
        old.start.assert_not_called()

    def test_a_leftover_that_cannot_go_does_not_fail_a_deploy_that_runs(self, markers):
        orchestrator._mark_failed("cashpilot-mysterium", True)
        old = _running_old()
        old.remove_error = _api_error("removal of container is already in progress")
        docker = _FakeDocker(old)
        _raw_deploy(client=docker.client, old=old)
        docker.created.start.assert_called_once()
        assert orchestrator.deploy_failed() == set()
        assert docker.get("cashpilot-mysterium-replaced") is old


class TestTheGuardStartsOnlyAWholeNode:
    def test_a_start_it_could_not_read_back_is_tried_again(self, markers):
        node = _node(status="exited")
        node.reload.side_effect = RuntimeError("the daemon did not answer")
        held, _ = _guard([node])
        node.stop.assert_called_once()
        assert lan_fence.UNREAD in held["cashpilot-mysterium"]
        assert orchestrator.deploy_failed() == set()

    def test_never_one_missing_part_of_its_udp_range(self, markers):
        node = _node(status="exited")
        node.attrs["Config"]["Env"] = ["UDP_PORTS=23000:23029"]
        del node.attrs["HostConfig"]["PortBindings"]["23015/udp"]
        held, _ = _guard([node])
        node.start.assert_not_called()
        assert "UDP 23015" in held["cashpilot-mysterium"]

    def test_control_one_with_its_whole_range_is_started(self, markers):
        node = _node(status="exited")
        node.attrs["Config"]["Env"] = ["UDP_PORTS=23000:23029"]
        _guard([node])
        node.start.assert_called_once()

    def test_never_the_old_node_a_deploy_moved_aside(self, markers):
        aside = _node(status="exited")
        aside.name = "cashpilot-mysterium-replaced"
        _guard([aside])
        aside.start.assert_not_called()

    def test_never_a_container_a_failed_deploy_left(self, markers):
        orchestrator._mark_failed("cashpilot-mysterium", True)
        node = _node(status="exited")
        held, _ = _guard([node])
        node.start.assert_not_called()
        assert held["cashpilot-mysterium"] == lan_fence.FAILED_DEPLOY

    def test_never_one_not_attached_to_its_network(self, markers):
        node = _node(status="exited")
        node.attrs["NetworkSettings"] = {"Networks": {}}
        held, _ = _guard([node])
        node.start.assert_not_called()
        assert "not attached to cashpilot-isolated" in held["cashpilot-mysterium"]

    def test_never_one_without_its_udp_publishes(self, markers):
        node = _node(status="exited")
        node.attrs["HostConfig"]["PortBindings"] = {"4449/tcp": [{"HostIp": "127.0.0.1", "HostPort": "4449"}]}
        held, _ = _guard([node])
        node.start.assert_not_called()
        assert "UDP" in held["cashpilot-mysterium"]

    def test_one_that_comes_up_with_no_address_is_stopped_and_not_started_again(self, markers, caplog):
        node = _node(status="exited")

        def up_without_network(*_a, **_k):
            node.attrs["State"]["Running"] = True
            node.attrs["NetworkSettings"]["Networks"]["cashpilot-isolated"]["IPAddress"] = ""

        node.start.side_effect = up_without_network
        with caplog.at_level("INFO"):
            held, _ = _guard([node])
        node.stop.assert_called_once()
        assert "no address" in held["cashpilot-mysterium"]
        assert "fence is confirmed" not in caplog.text
        again = _node(status="exited")
        _guard([again])
        again.start.assert_not_called()

    def test_control_a_whole_node_is_started_and_logged(self, markers, caplog):
        node = _node(status="exited")
        with caplog.at_level("INFO"):
            _guard([node])
        node.start.assert_called_once()
        node.stop.assert_not_called()
        assert "fence is confirmed and it is on its network" in caplog.text


class TestTheEphemeralRangeHint:
    def test_a_taken_port_in_the_ephemeral_range_says_why_and_what_to_do(self):
        hint = orchestrator._ephemeral_hint(BIND_REFUSED, "mysterium")
        assert "32768-60999" in hint and "below 32768" in hint and "UDP_PORTS" in hint and "23000:23029" in hint

    def test_a_service_without_a_udp_range_setting_gets_general_advice(self):
        hint = orchestrator._ephemeral_hint(BIND_REFUSED, "honeygain")
        assert "32768-60999" in hint and "below 32768" in hint
        assert "UDP_PORTS" not in hint and "23000" not in hint

    def test_control_a_taken_port_below_it_gets_no_hint(self):
        assert orchestrator._ephemeral_hint(BIND_REFUSED.replace("56033", "23005")) == ""

    def test_control_another_refusal_gets_no_hint(self):
        assert orchestrator._ephemeral_hint("no such device /dev/net/tun") == ""


# ---------------------------------------------------------------------------
# The move off the host's network: one action for the worker's mode, then why
# ---------------------------------------------------------------------------

NEW_RECORD = {**HOST_RECORD, "env": {"UI_ADDRESS": "127.0.0.1", "UDP_PORTS": "23000:23029"}}


class TestTheMoveAdvice:
    @pytest.mark.parametrize(
        ("mode", "says", "redeploy"),
        [
            (lan_fence.MODE_ON, f"Redeploy {MYST['name']} once to move it onto the fenced bridge.", True),
            (lan_fence.MODE_OPERATOR, f"Redeploy {MYST['name']} once to move it onto your own network", True),
            (lan_fence.MODE_LEGACY, "Switch isolation on in Fleet first, then redeploy", False),
            (lan_fence.MODE_OFF, "Set CASHPILOT_ISOLATION=auto on this worker and restart it, then redeploy", False),
            (lan_fence.MODE_UNSUPPORTED, "cannot be fenced on this worker", False),
            (None, "if isolation is not on for this worker, switch it on in Fleet first", False),
        ],
    )
    def test_the_action_fits_the_workers_mode(self, mode, says, redeploy):
        move = drift.move_advice(MYST, _shape(network_mode="host"), NEW_RECORD, mode)
        assert move["action"].startswith(says) or says in move["action"]
        assert move["redeploy"] is redeploy
        if mode in (lan_fence.MODE_ON, lan_fence.MODE_OPERATOR):
            # Switching isolation on is refused in operator mode: a redeploy alone is the way.
            assert "Switch isolation" not in move["action"] and "CASHPILOT_ISOLATION" not in move["action"]

    def test_the_drift_reason_carries_no_action_of_its_own(self):
        found = drift.container_drift(MYST, _shape(network_mode="host"), HOST_RECORD)
        host = next(f for f in found if "host's network" in f)
        assert host == "shares the host's network, where its NET_ADMIN reaches the host's firewall"

    def test_a_recorded_range_in_the_ephemeral_range_is_flagged_before_the_redeploy(self):
        move = drift.move_advice(MYST, _shape(network_mode="host"), HOST_RECORD, lan_fence.MODE_ON)
        warning = move["warning"]
        assert "56000:56100" in warning and "32768-60999" in warning
        assert "Before you redeploy" in warning and "below 32768 other than the default" in warning
        assert "23100:23129" in warning

    def test_the_warning_offers_reserving_the_range_on_the_host_instead(self):
        warning = drift.move_advice(MYST, _shape(network_mode="host"), HOST_RECORD, lan_fence.MODE_ON)["warning"]
        assert "keep this range and reserve it on the host" in warning
        assert "sudo sysctl -w net.ipv4.ip_local_reserved_ports=56000-56100" in warning
        # systemd-sysctl skips a file without .conf, so the file is named.
        assert "net.ipv4.ip_local_reserved_ports = 56000-56100 in /etc/sysctl.d/90-mysterium-ports.conf" in warning
        # Read before the write: sysctl -w replaces the whole list.
        assert warning.index("First read sysctl net.ipv4.ip_local_reserved_ports") < warning.index("sudo sysctl -w")
        assert "add 56000-56100 to them, comma-separated" in warning
        # The kernel keeps it from automatic picks only; an explicit bind still takes the port.
        assert "stops automatic picks only" in warning and "binds one of these ports by number" in warning
        # The worker cannot read the host's reservation, so it says when to ignore the warning.
        assert warning.endswith("If you've reserved this range on the host, you can redeploy.")

    def test_the_reservation_names_the_recorded_range_not_a_fixed_one(self):
        record = {**HOST_RECORD, "env": {"UDP_PORTS": "40000:40020"}}
        warning = drift.move_advice(MYST, _shape(network_mode="host"), record, lan_fence.MODE_ON)["warning"]
        assert "ip_local_reserved_ports=40000-40020" in warning and "56000" not in warning

    def test_the_guide_and_the_upgrade_notes_give_the_same_reservation(self):
        for doc in ("docs/guides/mysterium.md", "UPGRADING.md"):
            text = (ROOT / doc).read_text(encoding="utf-8")
            assert "sysctl -w net.ipv4.ip_local_reserved_ports=56000-56100" in text, doc
            assert "net.ipv4.ip_local_reserved_ports = 56000-56100" in text, doc
            assert "/etc/sysctl.d/90-mysterium-ports.conf" in text, doc
            flat = " ".join(text.split())
            assert flat.index("read `sysctl net.ipv4.ip_local_reserved_ports`") < flat.index("sudo sysctl -w"), doc

    def test_the_guide_no_longer_says_the_node_runs_on_the_host_network(self):
        guide = (ROOT / "docs" / "guides" / "mysterium.md").read_text(encoding="utf-8")
        assert "--net host" not in guide

    def test_control_a_range_below_it_or_none_on_record_is_not(self):
        for record in (NEW_RECORD, None, {**HOST_RECORD, "env": {}}):
            assert drift.move_advice(MYST, _shape(network_mode="host"), record, lan_fence.MODE_ON)["warning"] is None

    def test_control_a_node_already_off_the_host_network_gets_no_advice(self):
        assert drift.move_advice(MYST, _shape(), NEW_RECORD, lan_fence.MODE_ON) is None

    @pytest.mark.parametrize(
        ("mode", "switch"),
        [(lan_fence.MODE_ON, False), (lan_fence.MODE_OPERATOR, False), (lan_fence.MODE_LEGACY, True)],
    )
    def test_the_isolation_check_gives_the_same_action(self, mode, switch):
        found = isolation_check.host_netns_findings([_c("cashpilot-mysterium", "host", ["NET_ADMIN"])], mode)
        assert ("Switch isolation on in Fleet first" in found[0]["detail"]) is switch
        assert "Redeploy them once" in found[0]["detail"] or "redeploy them once" in found[0]["detail"]

    def test_the_mode_refusal_uses_the_same_advice(self):
        assert lan_fence.move_advice(lan_fence.MODE_OFF, "Other") in lan_fence.mode_problem(lan_fence.MODE_OFF, "Other")
        unknown = lan_fence.mode_problem("weird", "Other")
        assert "Redeploy Other once" in unknown and "switch it on in Fleet first" in unknown

    def test_the_dashboard_gets_the_workers_mode_and_the_warning(self):
        from tests.test_drift import _deployed_row

        row = _deployed_row(MYST, _shape(network_mode="host"), recorded=HOST_RECORD, isolation_mode="operator")
        move = row["instance_details"][0]["drift_move"]
        assert move["action"].startswith(f"Redeploy {MYST['name']} once to move it onto your own network")
        assert "56000:56100" in move["warning"]

    def test_the_dashboard_leads_with_the_action_and_offers_redeploy_only_where_it_works(self):
        js = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
        assert "${escapeHtml(move.action)}${move.warning ? ` ${escapeHtml(move.warning)}` : ''}" in js
        assert "!(move && move.redeploy === false)" in js


def test_the_isolation_check_passes_the_workers_mode_to_the_finding():
    client = MagicMock()
    client.containers.list.return_value = []
    with (
        patch.object(lan_fence, "effective_network", return_value=(lan_fence.MODE_OPERATOR, "x")),
        patch.object(isolation_check, "host_netns_findings", return_value=[]) as spy,
        patch.object(isolation_check, "placement_findings", return_value=[]),
        patch.object(isolation_check, "ipv6_findings", return_value=[]),
        contextlib.suppress(Exception),
    ):
        isolation_check._run(client)
    spy.assert_called_once_with([], lan_fence.MODE_OPERATOR)
