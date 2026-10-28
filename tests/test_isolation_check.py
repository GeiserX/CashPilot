"""The built-in isolation check (issue #451).

Nothing told an operator whether the firewall rule between earners and the LAN
worked, and it fails silently (Tailscale's chain ordering, a flushed chain, an
earner on Docker's default bridge). The worker now probes from an earner's own
namespace. These tests pin the parts that make the answer trustworthy: the
control drops what does not answer from the host, "could not test" is never
"isolated", the probes are removed on every path, and only the owner can run it.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest
import requests
import yaml
from docker.errors import APIError
from fastapi.testclient import TestClient

from app import isolation_check, worker_api
from app.main import app as ui_app

ROOT = Path(__file__).resolve().parent.parent

GATEWAY = {"group": "lan", "host": "192.168.1.1", "port": 80, "label": "default gateway"}
CLOSED = {"group": "lan", "host": "192.168.1.1", "port": 22, "label": "default gateway"}
HOST = {"group": "host", "host": "192.168.1.10", "port": 22, "label": "this host, port 22"}
TS_DNS = {"group": "overlay", "host": "100.100.100.100", "port": 53, "label": "Tailscale DNS"}
TS_PAGE = {"group": "overlay", "host": "100.100.100.100", "port": 80, "label": "Tailscale status page"}
METADATA = {"group": "metadata", "host": "169.254.169.254", "port": 80, "label": "cloud metadata"}


def _earner(name="cashpilot-honeygain", networks=("cashpilot-isolated",), mode="cashpilot-isolated", dns=None):
    c = MagicMock()
    c.name = name
    c.id = f"id-{name}"
    c.attrs = {
        "HostConfig": {"NetworkMode": mode, "Dns": dns or []},
        "NetworkSettings": {"Networks": {n: {} for n in networks}},
    }
    return c


class FakeDocker:
    """A Docker client whose probe containers answer like the real script.

    ``control`` is the discover output (candidates with ``ok``); ``earner``
    maps a target's "host:port" to whether it answers from the earner side.
    """

    def __init__(self, control, earner=None, earners=None, resolvers=None, fail=None):
        self.control = control
        self.earner = earner or {}
        self.fail = fail or {}
        self.earners = [_earner()] if earners is None else earners
        self.resolvers = resolvers or []
        self.runs: list[dict] = []
        self.removed: list[str] = []
        self.live: set[str] = set()
        self.containers = MagicMock()
        self.containers.run.side_effect = self._run
        self.containers.get.side_effect = self._get
        self.containers.list.side_effect = self._list

    def _list(self, filters=None):
        label = (filters or {}).get("label", "")
        return [] if label == "cashpilot.service=mysterium" else list(self.earners)

    def _get(self, name):
        if name not in self.live:
            raise isolation_check.orchestrator.NotFound("gone")
        c = MagicMock()
        c.remove.side_effect = lambda force=False: (self.removed.append(name), self.live.discard(name))
        return c

    def _run(self, **kwargs):
        self.runs.append(kwargs)
        name = kwargs["name"]
        self.live.add(name)
        mode = kwargs["command"][0]
        if self.fail.get(mode) == "run":
            raise APIError("daemon said no")
        c = MagicMock()
        if self.fail.get(mode) == "timeout":
            c.wait.side_effect = requests.exceptions.ReadTimeout("probe hung")
        else:
            c.wait.return_value = {"StatusCode": 1 if self.fail.get(mode) == "exit" else 0}
        if mode == "discover":
            out = {"candidates": self.control, "resolvers": self.resolvers}
        else:
            targets = json.loads(kwargs["environment"]["PROBE_TARGETS"])
            out = {"results": [self.earner.get(f"{t['host']}:{t['port']}", False) for t in targets]}
        c.logs.return_value = json.dumps(out).encode()
        return c


def _ok(*targets, ok=True):
    return [dict(t, ok=ok) for t in targets]


def _check(fake, network="cashpilot-isolated"):
    me = MagicMock()
    me.attrs = {"Image": "sha256:worker"}
    with (
        patch.object(isolation_check.orchestrator, "_CONTAINER_NETWORK", network),
        patch.object(isolation_check.orchestrator, "_self_container", return_value=me),
    ):
        return isolation_check._run(fake)


def _earner_targets(fake):
    run = next(r for r in fake.runs if r["command"] == ["test"])
    return [f"{t['host']}:{t['port']}" for t in json.loads(run["environment"]["PROBE_TARGETS"])]


INTERNET_OK = {"1.1.1.1:443": True}


class TestTheControl:
    def test_a_target_that_does_not_answer_from_the_host_is_not_tested(self):
        fake = FakeDocker(_ok(GATEWAY) + _ok(CLOSED, ok=False), INTERNET_OK)
        report = _check(fake)
        assert _earner_targets(fake) == ["192.168.1.1:80", "1.1.1.1:443"]
        assert report["not_answering_from_host"] == ["192.168.1.1:22"]
        assert report["status"] == "isolated"

    def test_one_port_per_address_except_tailscale_dns(self):
        second = dict(GATEWAY, port=443)
        fake = FakeDocker(_ok(GATEWAY, second, TS_DNS, TS_PAGE), INTERNET_OK)
        _check(fake)
        assert _earner_targets(fake) == ["192.168.1.1:80", "100.100.100.100:53", "100.100.100.100:80", "1.1.1.1:443"]

    def test_the_control_runs_on_host_networking_and_the_earner_probe_in_its_namespace(self):
        fake = FakeDocker(_ok(GATEWAY), INTERNET_OK)
        _check(fake)
        control, earner = fake.runs
        assert control["network_mode"] == "host"
        assert earner["network_mode"] == "container:id-cashpilot-honeygain"
        for run in fake.runs:
            assert run["image"] == "sha256:worker", "the worker's own image, nothing pulled"
            assert run["cap_drop"] == ["ALL"]
            assert run["user"] == "65534:65534"
            assert run["read_only"] is True
            assert run["security_opt"] == ["no-new-privileges:true"]
            assert run["privileged"] is False


class TestTheEarnerSide:
    def test_reachable_and_blocked_are_reported_per_group(self):
        fake = FakeDocker(_ok(GATEWAY, HOST, METADATA), {"192.168.1.1:80": True, **INTERNET_OK})
        report = _check(fake)
        assert report["status"] == "exposed"
        groups = {g["group"]: g["targets"] for g in report["groups"]}
        assert groups["lan"][0]["reachable"] is True
        assert groups["host"][0]["reachable"] is False
        assert groups["metadata"][0]["reachable"] is False
        kinds = {f["kind"]: f for f in report["findings"]}
        assert set(kinds) == {"reachable_lan"}
        assert kinds["reachable_lan"]["docs"] == isolation_check.FIX_PAGE

    def test_everything_blocked_with_internet_is_isolated(self):
        fake = FakeDocker(_ok(GATEWAY, HOST, METADATA), INTERNET_OK)
        report = _check(fake)
        assert report["status"] == "isolated"
        assert report["findings"] == []
        assert report["internet"] == {"address": "1.1.1.1:443", "reachable": True}

    def test_with_no_earner_it_probes_from_the_isolated_network(self):
        fake = FakeDocker(_ok(GATEWAY), INTERNET_OK, earners=[])
        with patch.object(isolation_check.orchestrator, "container_network", return_value="cashpilot-isolated"):
            _check(fake)
        assert fake.runs[1]["network"] == "cashpilot-isolated"
        assert fake.runs[1]["network_mode"] is None

    def test_tailscale_dns_reads_reachable_through_the_rewrite(self):
        """docs/isolation-check.md: port 53 rewritten, port 80 blocked, the fence works."""
        fake = FakeDocker(_ok(TS_DNS, TS_PAGE), {"100.100.100.100:53": True, **INTERNET_OK})
        report = _check(fake)
        assert report["status"] == "isolated"
        dns = report["groups"][0]["targets"][0]
        assert dns["reachable"] is True and "rewrite" in dns["note"]

    def test_tailscale_reachable_on_both_ports_is_a_finding(self):
        fake = FakeDocker(_ok(TS_DNS, TS_PAGE), {"100.100.100.100:53": True, "100.100.100.100:80": True, **INTERNET_OK})
        report = _check(fake)
        assert report["status"] == "exposed"
        assert report["findings"][0]["docs"] == isolation_check.OVERLAY_PAGE


class TestCouldNotTest:
    def test_nothing_answering_from_the_host_is_never_isolated(self):
        fake = FakeDocker(_ok(GATEWAY, HOST, ok=False), INTERNET_OK)
        report = _check(fake)
        assert report["status"] == "could_not_test"
        assert "Nothing answered" in report["reason"]
        assert len(fake.runs) == 1, "no earner probe without a control"

    def test_no_internet_from_the_earner_side_is_never_isolated(self):
        fake = FakeDocker(_ok(GATEWAY), {})
        report = _check(fake)
        assert report["status"] == "could_not_test"
        assert "internet" in report["reason"]

    def test_no_earner_and_no_network(self):
        fake = FakeDocker(_ok(GATEWAY), INTERNET_OK, earners=[])
        report = _check(fake, network="")
        assert report["status"] == "could_not_test"


class TestProbesAreAlwaysRemoved:
    @pytest.mark.parametrize("how", ["timeout", "run", "exit"])
    @pytest.mark.parametrize("mode", ["discover", "test"])
    def test_a_failing_probe_is_removed_and_reported(self, how, mode):
        fake = FakeDocker(_ok(GATEWAY), INTERNET_OK, fail={mode: how})
        report = _check(fake)
        assert report["status"] == "could_not_test"
        assert report["reason"]
        assert fake.live == set(), f"left behind: {fake.live}"

    def test_success_removes_both(self):
        fake = FakeDocker(_ok(GATEWAY), INTERNET_OK)
        _check(fake)
        assert fake.live == set()
        assert {isolation_check.HOST_PROBE, isolation_check.EARNER_PROBE} <= set(fake.removed)

    def test_a_second_check_while_one_runs_is_refused(self):
        assert isolation_check._lock.acquire(blocking=False)
        try:
            with pytest.raises(isolation_check.CheckBusy):
                isolation_check.run()
        finally:
            isolation_check._lock.release()


class TestPlacementAndDns:
    def test_an_earner_off_the_isolated_bridge_is_flagged(self):
        stray = _earner("cashpilot-repocket", networks=("bridge",), mode="bridge")
        host_net = _earner("cashpilot-mysterium", networks=("host",), mode="host")
        found = isolation_check.placement_findings([_earner(), stray, host_net], "cashpilot-isolated")
        assert len(found) == 1 and "cashpilot-repocket" in found[0]["detail"]
        assert "mysterium" not in found[0]["detail"]

    def test_no_isolated_network_is_flagged(self):
        found = isolation_check.placement_findings([_earner(networks=("bridge",), mode="bridge")], "")
        assert found[0]["kind"] == "no_isolated_network"

    def test_an_earner_asking_a_blocked_resolver_is_flagged(self):
        old = _earner("cashpilot-old")
        new = _earner("cashpilot-new", dns=["1.1.1.1"])
        found = isolation_check.dns_findings([old, new], "cashpilot-isolated", ["100.100.100.100"], {"100.100.100.100"})
        assert "cashpilot-old" in found[0]["detail"] and "cashpilot-new" not in found[0]["detail"]
        assert found[0]["exposure"] is False


class TestMysterium:
    def _node(self, output):
        node = MagicMock()
        node.name = "cashpilot-mysterium"
        node.exec_run.return_value = (0, output)
        client = MagicMock()
        client.containers.list.return_value = [node]
        return client, node

    def test_reports_what_the_chain_blackholes_and_what_it_misses(self):
        out = b"".join(
            f"-A MYST -d {n} -j DNAT --to-destination 240.0.0.1\n".encode()
            for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8")
        )
        client, node = self._node(out + b"-N MYST\n")
        myst = isolation_check.read_myst_chain(client)
        assert myst["missing"] == ["100.64.0.0/10", "169.254.0.0/16"]
        cmd = node.exec_run.call_args.args[0][-1]
        assert "iptables-nft" in cmd and "-S MYST" in cmd and "-A " not in cmd and "-I " not in cmd

    def test_the_required_list_comes_from_the_catalog(self):
        assert isolation_check.protected_networks()["mysterium"][-2:] == ["100.64.0.0/10", "169.254.0.0/16"]

    def test_an_empty_chain_is_not_a_clean_bill(self):
        client, _ = self._node(b"")
        myst = isolation_check.read_myst_chain(client)
        assert myst["readable"] is False and myst["missing"] == []


class TestTheProbeScript:
    """The real script, in its test mode: a listening port answers, a closed one does not."""

    def test_it_tells_open_from_closed(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen()
        closed = socket.socket()
        closed.bind(("127.0.0.1", 0))
        closed_port = closed.getsockname()[1]
        closed.close()
        targets = [{"host": "127.0.0.1", "port": server.getsockname()[1]}, {"host": "127.0.0.1", "port": closed_port}]
        try:
            out = subprocess.run(
                [sys.executable, "-I", "-c", isolation_check.PROBE_SCRIPT, "test"],
                env={"PROBE_TARGETS": json.dumps(targets)},
                capture_output=True,
                text=True,
                timeout=20,
                check=True,
            )
        finally:
            server.close()
        assert json.loads(out.stdout) == {"results": [True, False]}


@asynccontextmanager
async def _noop_lifespan(a):
    yield


class TestEndpoints:
    def test_the_worker_route_needs_the_fleet_key(self):
        worker_api.app.router.lifespan_context = _noop_lifespan
        client = TestClient(worker_api.app, raise_server_exceptions=False)
        with patch.object(isolation_check, "run") as run:
            resp = client.get("/api/isolation-check", headers={"Authorization": "Bearer nope"})
        assert resp.status_code == 401
        run.assert_not_called()

    def test_the_worker_route_runs_the_check(self):
        worker_api.app.router.lifespan_context = _noop_lifespan
        client = TestClient(worker_api.app, raise_server_exceptions=False)
        with patch.object(isolation_check, "run", return_value={"status": "isolated"}):
            resp = client.get("/api/isolation-check", headers={"Authorization": f"Bearer {worker_api.API_KEY}"})
        assert resp.status_code == 200 and resp.json() == {"status": "isolated"}

    def test_the_ui_route_is_owner_only(self):
        ui_app.router.lifespan_context = _noop_lifespan
        client = TestClient(ui_app, raise_server_exceptions=False)
        with (
            patch("app.main.auth.get_current_user", return_value={"uid": 2, "u": "w", "r": "writer"}),
            patch("app.main._proxy_to_worker", new_callable=AsyncMock) as proxy,
        ):
            resp = client.get("/api/workers/1/isolation-check")
        assert resp.status_code in (401, 403)
        proxy.assert_not_called()

    def test_the_ui_route_proxies_for_the_owner(self):
        ui_app.router.lifespan_context = _noop_lifespan
        client = TestClient(ui_app, raise_server_exceptions=False)
        with (
            patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "admin", "r": "owner"}),
            patch("app.main._proxy_to_worker", new_callable=AsyncMock, return_value={"status": "exposed"}) as proxy,
        ):
            resp = client.get("/api/workers/1/isolation-check")
        assert resp.status_code == 200 and resp.json() == {"status": "exposed"}
        assert proxy.call_args.args[:3] == (1, "GET", "/api/isolation-check")


def test_mysterium_blackholes_cgnat_and_metadata_for_its_customers():
    """services/bandwidth/mysterium.yml: the node's default list leaves out both."""
    command = yaml.safe_load((ROOT / "services/bandwidth/mysterium.yml").read_text())["docker"]["command"]
    ranges = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "100.64.0.0/10", "169.254.0.0/16"]
    flag = "--firewall.protected.networks=" + ",".join(ranges)
    assert flag in command.split()
    assert command.index(flag) < command.index(" service "), "a global flag must come before `service`"
