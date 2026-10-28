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
import struct
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
from app import main as main_module
from app.main import app as ui_app

ROOT = Path(__file__).resolve().parent.parent

GATEWAY = {"group": "lan", "host": "192.168.1.1", "port": 80, "label": "default gateway"}
CLOSED = {"group": "lan", "host": "192.168.1.1", "port": 22, "label": "default gateway"}
HOST = {"group": "host", "host": "192.168.1.10", "port": 22, "label": "this host, port 22"}
TS_DNS = {"group": "overlay", "host": "100.100.100.100", "port": 53, "label": "Tailscale DNS"}
TS_PAGE = {"group": "overlay", "host": "100.100.100.100", "port": 80, "label": "Tailscale status page"}
PIHOLE_WEB = {"group": "lan", "host": "192.168.1.2", "port": 80, "label": "DNS resolver"}
PIHOLE_DNS = {"group": "lan", "host": "192.168.1.2", "port": 53, "label": "DNS resolver"}
METADATA = {"group": "metadata", "host": "169.254.169.254", "port": 80, "label": "cloud metadata"}


def _earner(
    name="cashpilot-honeygain",
    networks=("cashpilot-isolated",),
    mode="cashpilot-isolated",
    dns=None,
    status="running",
    gateway="172.30.0.1",
    ipv6="",
):
    c = MagicMock()
    c.name = name
    c.id = f"id-{name}"
    c.status = status
    c.attrs = {
        "HostConfig": {"NetworkMode": mode, "Dns": dns or []},
        "NetworkSettings": {"Networks": {n: {"Gateway": gateway, "GlobalIPv6Address": ipv6} for n in networks}},
    }
    return c


class FakeDocker:
    """A Docker client whose probe containers answer like the real script.

    ``control`` is the discover output (candidates with ``ok``); ``earner``
    maps a target's "host:port" to whether it answers from the earner side.
    """

    def __init__(self, control, earner=None, earners=None, resolvers=None, fail=None, network_attrs=None):
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
        self.networks = MagicMock()
        self.networks.get.return_value.attrs = network_attrs or {}

    def _list(self, all=False, filters=None):
        label = (filters or {}).get("label", "")
        if label == "cashpilot.service=mysterium":
            return []
        return [c for c in self.earners if all or c.status == "running"]

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

    def test_tailscale_dns_reachable_with_no_port_80_control_is_a_finding(self):
        """Port 53 alone cannot tell the rewrite from a missing fence, so it is not waved through."""
        fake = FakeDocker(_ok(TS_DNS) + _ok(TS_PAGE, ok=False), {"100.100.100.100:53": True, **INTERNET_OK})
        report = _check(fake)
        assert report["status"] == "exposed"
        assert [f["kind"] for f in report["findings"]] == ["reachable_overlay"]
        assert "Can also mean the DNS rewrite" in report["groups"][0]["targets"][0]["note"]

    def test_a_lan_resolver_with_the_dns_exception_is_isolated(self):
        """docs/home-network-security.md: the router's port 53 allowed, its web interface blocked."""
        fake = FakeDocker(_ok(PIHOLE_WEB, PIHOLE_DNS), {"192.168.1.2:53": True, **INTERNET_OK})
        report = _check(fake)
        assert _earner_targets(fake) == ["192.168.1.2:80", "192.168.1.2:53", "1.1.1.1:443"]
        assert report["status"] == "isolated"
        dns = report["groups"][0]["targets"][1]
        assert dns["expected"] is True and "DNS exception" in dns["note"]

    def test_a_lan_resolver_reachable_on_its_other_port_is_a_finding(self):
        fake = FakeDocker(_ok(PIHOLE_WEB, PIHOLE_DNS), {"192.168.1.2:53": True, "192.168.1.2:80": True, **INTERNET_OK})
        report = _check(fake)
        assert report["status"] == "exposed"
        assert "192.168.1.2:80" in report["findings"][0]["detail"]
        assert "192.168.1.2:53" in report["findings"][0]["detail"]

    def test_a_lan_resolver_answering_only_on_53_says_it_cannot_tell(self):
        fake = FakeDocker(_ok(PIHOLE_DNS) + _ok(PIHOLE_WEB, ok=False), {"192.168.1.2:53": True, **INTERNET_OK})
        report = _check(fake)
        assert report["status"] == "isolated"
        assert "cannot tell" in report["groups"][0]["targets"][0]["note"]


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

    def test_a_stopped_earner_off_the_isolated_bridge_is_flagged(self):
        """It is unfenced again the moment it starts, so 'isolated' would be wrong."""
        stray = _earner("cashpilot-repocket", networks=("bridge",), mode="bridge", status="exited")
        fake = FakeDocker(_ok(GATEWAY), INTERNET_OK, earners=[_earner(), stray])
        report = _check(fake)
        assert report["status"] == "exposed"
        assert "cashpilot-repocket" in report["findings"][0]["detail"]
        assert fake.runs[1]["network_mode"] == "container:id-cashpilot-honeygain", "the probe joins a running one"

    def test_ipv6_on_the_earner_network_is_never_a_silent_isolated(self):
        fake = FakeDocker(_ok(GATEWAY), INTERNET_OK, network_attrs={"EnableIPv6": True})
        report = _check(fake)
        assert [f["kind"] for f in report["findings"]] == ["ipv6_not_tested"]
        assert report["findings"][0]["exposure"] is False
        assert "IPv4 only" in report["findings"][0]["detail"]

    def test_an_earner_with_an_ipv6_address_is_named(self):
        fake = FakeDocker(_ok(GATEWAY), INTERNET_OK, earners=[_earner(ipv6="2001:db8:1:2::5")])
        report = _check(fake)
        assert "cashpilot-honeygain" in report["findings"][0]["detail"]

    def test_no_ipv6_no_finding(self):
        report = _check(FakeDocker(_ok(GATEWAY), INTERNET_OK, network_attrs={"EnableIPv6": False}))
        assert report["findings"] == []

    def test_the_earner_gateway_goes_to_the_control_first(self):
        fake = FakeDocker(_ok(GATEWAY), INTERNET_OK)
        _check(fake)
        assert json.loads(fake.runs[0]["environment"]["PROBE_FIRST"]) == ["172.30.0.1"]

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

    @pytest.mark.parametrize(
        ("legacy_nat", "default_backend", "asked"),
        [
            (False, "legacy", ["iptables-nft"]),
            (False, "nf_tables", ["iptables-nft", "iptables"]),
            (True, "legacy", ["iptables-nft", "iptables-legacy", "iptables"]),
        ],
    )
    def test_the_legacy_backend_is_asked_only_when_its_nat_table_exists(
        self, tmp_path, legacy_nat, default_backend, asked
    ):
        """Asking legacy for a missing nat table loads iptable_nat on the host."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        log = tmp_path / "calls"
        for name in ("iptables-nft", "iptables-legacy", "iptables"):
            script = bin_dir / name
            version = f'[ "$1" = -V ] && {{ echo "iptables v1.8.9 ({default_backend})"; exit 0; }}\n'
            script.write_text(f"#!/bin/sh\n{version if name == 'iptables' else ''}echo {name} >> {log}\n")
            script.chmod(0o755)
        names = tmp_path / "ip_tables_names"
        names.write_text("filter\nnat\n" if legacy_nat else "filter\n")
        cmd = isolation_check.MYST_READ.replace(isolation_check.IPT_NAMES, str(names))
        assert cmd != isolation_check.MYST_READ
        subprocess.run(["sh", "-c", cmd], env={"PATH": f"{bin_dir}:/usr/bin:/bin"}, check=False)
        assert (log.read_text().split() if log.exists() else []) == asked

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


def _hex(addr):
    return f"{struct.unpack('=I', socket.inet_aton(addr))[0]:08X}"


def _tcp_line(local, lport, remote, rport, state):
    return f"   0: {_hex(local)}:{lport:04X} {_hex(remote)}:{rport:04X} {state} 0 0 0\n"


TCP_HEADER = "  sl  local_address rem_address   st tx_queue rx_queue\n"
ROUTE = (
    "Iface\tDestination\tGateway\tFlags\n"
    f"br0\t00000000\t{_hex('192.168.10.1')}\t0003\n"
    f"br0\t{_hex('192.168.10.0')}\t00000000\t0001\n"
)


@pytest.fixture(scope="module")
def probe():
    ns = {"__name__": "probe"}
    exec(isolation_check.PROBE_SCRIPT, ns)  # noqa: S102 - our own constant
    return ns


class TestDiscovery:
    """The discover half of the probe script, fed fixture text instead of /proc."""

    def _watchtower(self):
        """45 addresses, as on watchtower: Docker bridges in 10.x and 172.x sort ahead of br0."""
        ifaces = {"lo": "127.0.0.1", "br0": "192.168.10.100", "tailscale1": "100.70.1.2"}
        ifaces.update({f"br-a{i}": f"10.{i}.0.1" for i in range(14)})
        ifaces.update({f"br-b{i}": f"172.{17 + i}.0.1" for i in range(15)})
        ifaces.update({f"br-c{i}": f"192.168.{100 + i}.1" for i in range(14)})
        return ifaces

    def test_the_lan_address_survives_many_docker_bridges(self, probe):
        tcp = TCP_HEADER + _tcp_line("0.0.0.0", 22, "0.0.0.0", 0, "0A")
        out = probe["candidates"](self._watchtower(), ROUTE, tcp, "", ["172.99.0.1", "172.31.0.1"])
        hosts = {t["host"] for t in out["candidates"] if t["group"] == "host"}
        assert {"192.168.10.100", "100.70.1.2", "172.31.0.1"} <= hosts
        assert "172.99.0.1" not in hosts, "a first address that is not ours is not added"
        assert len(hosts) == probe["MAX_OWN"]
        assert len(out["addresses_left_out"]) == 45 - probe["MAX_OWN"]
        assert not hosts & set(out["addresses_left_out"])

    def test_the_default_gateway_comes_from_the_route_table(self, probe):
        out = probe["candidates"]({"eth0": "192.168.10.100"}, ROUTE, TCP_HEADER, "")
        gw = [t["port"] for t in out["candidates"] if t["host"] == "192.168.10.1"]
        assert gw == [80, 443, 22, 53]

    # tailscale1 on a custom range (Headscale): only the name gives it away.
    # tun9 in 100.64.0.0/10: only the address does.
    @pytest.mark.parametrize("ifaces", [{"tailscale1": "10.200.0.5"}, {"tun9": "100.70.1.2"}])
    def test_tailscale_by_interface_name_or_cgnat_address(self, probe, ifaces):
        out = probe["candidates"](dict(ifaces, eth0="192.168.10.100"), ROUTE, TCP_HEADER, "")
        assert {"100.100.100.100:53", "100.100.100.100:80"} <= {
            f"{t['host']}:{t['port']}" for t in out["candidates"] if t["group"] == "overlay"
        }

    def test_no_tailscale_no_overlay_targets(self, probe):
        out = probe["candidates"]({"eth0": "192.168.10.100"}, ROUTE, TCP_HEADER, "")
        assert not [t for t in out["candidates"] if t["group"] == "overlay"]

    def test_the_tailnet_peer_is_one_this_host_connected_to(self, probe):
        tcp = (
            TCP_HEADER
            + _tcp_line("0.0.0.0", 22, "0.0.0.0", 0, "0A")
            # A peer connected to our sshd: its port is ephemeral, not a service.
            + _tcp_line("100.70.1.2", 22, "100.90.0.9", 51234, "01")
            + _tcp_line("100.70.1.2", 41000, "100.80.3.4", 443, "01")
        )
        out = probe["candidates"]({"tailscale0": "100.70.1.2"}, ROUTE, tcp, "")
        peers = [f"{t['host']}:{t['port']}" for t in out["candidates"] if t["label"] == "tailnet peer"]
        assert peers == ["100.80.3.4:443"]

    def test_a_private_resolver_is_tried_on_a_port_besides_53(self, probe):
        out = probe["candidates"](
            {"eth0": "192.168.1.10"}, "Iface\n", TCP_HEADER, "nameserver 192.168.1.2\nnameserver 9.9.9.9\n"
        )
        ports = [t["port"] for t in out["candidates"] if t["host"] == "192.168.1.2"]
        assert ports == [80, 443, 22, 53]
        assert not [t for t in out["candidates"] if t["host"] == "9.9.9.9"]
        assert out["resolvers"] == ["192.168.1.2", "9.9.9.9"]

    def test_the_host_is_tried_on_the_ports_it_listens_on(self, probe):
        tcp = (
            TCP_HEADER
            + _tcp_line("0.0.0.0", 8080, "0.0.0.0", 0, "0A")
            + _tcp_line("0.0.0.0", 25, "0.0.0.0", 0, "0A")
            + _tcp_line("0.0.0.0", 21, "0.0.0.0", 0, "0A")
            + _tcp_line("0.0.0.0", 22, "0.0.0.0", 0, "0A")
            + _tcp_line("192.168.1.10", 9000, "0.0.0.0", 0, "0A")
            + _tcp_line("127.0.0.1", 5432, "0.0.0.0", 0, "0A")
        )
        out = probe["candidates"]({"eth0": "192.168.1.10"}, "Iface\n", tcp, "")
        host = [t["port"] for t in out["candidates"] if t["group"] == "host"]
        # sshd first, then the lowest two; an address-bound port always.
        assert host == [22, 21, 25, 9000]


@asynccontextmanager
async def _noop_lifespan(a):
    yield


class TestEndpoints:
    def test_the_worker_route_needs_the_fleet_key(self):
        worker_api.app.router.lifespan_context = _noop_lifespan
        client = TestClient(worker_api.app, raise_server_exceptions=False)
        with patch.object(isolation_check, "run") as run:
            resp = client.post("/api/isolation-check", headers={"Authorization": "Bearer nope"})
        assert resp.status_code == 401
        run.assert_not_called()

    def test_the_worker_route_runs_the_check(self):
        worker_api.app.router.lifespan_context = _noop_lifespan
        client = TestClient(worker_api.app, raise_server_exceptions=False)
        with patch.object(isolation_check, "run", return_value={"status": "isolated"}):
            resp = client.post("/api/isolation-check", headers={"Authorization": f"Bearer {worker_api.API_KEY}"})
        assert resp.status_code == 200 and resp.json() == {"status": "isolated"}

    def test_the_ui_route_is_owner_only(self):
        ui_app.router.lifespan_context = _noop_lifespan
        client = TestClient(ui_app, raise_server_exceptions=False)
        with (
            patch("app.main.auth.get_current_user", return_value={"uid": 2, "u": "w", "r": "writer"}),
            patch("app.main._proxy_to_worker", new_callable=AsyncMock) as proxy,
        ):
            resp = client.post("/api/workers/1/isolation-check")
        assert resp.status_code in (401, 403)
        proxy.assert_not_called()

    def test_the_ui_route_proxies_for_the_owner(self):
        ui_app.router.lifespan_context = _noop_lifespan
        client = TestClient(ui_app, raise_server_exceptions=False)
        with (
            patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "admin", "r": "owner"}),
            patch("app.main._proxy_to_worker", new_callable=AsyncMock, return_value={"status": "exposed"}) as proxy,
        ):
            resp = client.post("/api/workers/1/isolation-check")
        assert resp.status_code == 200 and resp.json() == {"status": "exposed"}
        assert proxy.call_args.args[:3] == (1, "POST", "/api/isolation-check")
        # Two probes of up to PROBE_TIMEOUT each; the proxy's 30 s default
        # would give up while the worker is still checking.
        assert proxy.call_args.kwargs["timeout"] >= 2 * isolation_check.PROBE_TIMEOUT

    def test_starting_the_check_is_not_a_get(self):
        """It starts containers; a lax session cookie rides a cross-site GET."""
        ui_app.router.lifespan_context = _noop_lifespan
        worker_api.app.router.lifespan_context = _noop_lifespan
        with (
            patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "admin", "r": "owner"}),
            patch("app.main._proxy_to_worker", new_callable=AsyncMock) as proxy,
            patch.object(isolation_check, "run") as run,
        ):
            ui = TestClient(ui_app, raise_server_exceptions=False).get("/api/workers/1/isolation-check")
            worker = TestClient(worker_api.app, raise_server_exceptions=False).get(
                "/api/isolation-check", headers={"Authorization": f"Bearer {worker_api.API_KEY}"}
            )
        assert ui.status_code == 405 and worker.status_code == 405
        proxy.assert_not_called()
        run.assert_not_called()

    @pytest.mark.parametrize(
        ("raised", "code", "error"),
        [
            (
                isolation_check.CheckBusy("An isolation check is already running on this worker."),
                409,
                "isolation_check_busy",
            ),
            (RuntimeError("Docker socket not available at /var/run/docker.sock"), 503, "isolation_check_unavailable"),
        ],
    )
    def test_busy_and_no_docker_reach_the_user(self, raised, code, error):
        worker_api.app.router.lifespan_context = _noop_lifespan
        client = TestClient(worker_api.app, raise_server_exceptions=False)
        with patch.object(isolation_check, "run", side_effect=raised):
            resp = client.post("/api/isolation-check", headers={"Authorization": f"Bearer {worker_api.API_KEY}"})
        assert resp.status_code == code
        detail = resp.json()["detail"]
        assert detail["error"] == error and "/var/run" not in detail["message"]
        # The UI proxy forwards this shape instead of "Worker request failed".
        forwarded = main_module._safe_worker_detail(resp)
        assert forwarded == {"error": error, "message": detail["message"]}


def test_mysterium_blackholes_cgnat_and_metadata_for_its_customers():
    """services/bandwidth/mysterium.yml: the node's default list leaves out both."""
    command = yaml.safe_load((ROOT / "services/bandwidth/mysterium.yml").read_text())["docker"]["command"]
    ranges = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "100.64.0.0/10", "169.254.0.0/16"]
    flag = "--firewall.protected.networks=" + ",".join(ranges)
    assert flag in command.split()
    assert command.index(flag) < command.index(" service "), "a global flag must come before `service`"
