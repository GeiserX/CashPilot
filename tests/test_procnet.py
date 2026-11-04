"""app/procnet.py: the parsers, the summary and the classifier the Activity probe runs.

Fixture text is in the kernel's own format. Addresses are written with the
host's byte order (as the kernel does), through ``hx``/``hx6``, plus literal
lines for a little-endian host, which every supported platform is.
"""

from __future__ import annotations

import json
import socket
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from app import lan_isolation, procnet

ROOT = Path(__file__).resolve().parent.parent
HEADER = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
LITTLE = sys.byteorder == "little"


def hx(ip: str) -> str:
    return "{:08X}".format(struct.unpack("=I", socket.inet_aton(ip))[0])


def hx6(ip: str) -> str:
    raw = socket.inet_pton(socket.AF_INET6, ip)
    return "".join("{:08X}".format(struct.unpack("=I", raw[i : i + 4])[0]) for i in range(0, 16, 4))


def line(n: int, local: str, lport: int, remote: str, rport: int, state: str, v6: bool = False) -> str:
    enc = hx6 if v6 else hx
    return (
        f"  {n}: {enc(local)}:{lport:04X} {enc(remote)}:{rport:04X} {state} 00000000:00000000 "
        "00:00000000 00000000 65534 0 12345 1 0000000000000000 100 0 0 10 0\n"
    )


TCP = (
    HEADER
    + line(0, "0.0.0.0", 8080, "0.0.0.0", 0, "0A")
    + line(1, "127.0.0.1", 9000, "0.0.0.0", 0, "0A")
    + line(2, "172.18.0.5", 8080, "203.0.113.7", 51000, "01")  # inbound to a listener
    + line(3, "172.18.0.5", 40000, "198.51.100.9", 443, "01")
    + line(4, "172.18.0.5", 40001, "192.168.1.10", 22, "02")
    + line(5, "127.0.0.1", 40002, "127.0.0.1", 9000, "01")  # loopback, dropped
    + line(6, "172.18.0.5", 40003, "198.51.100.9", 443, "06")  # TIME_WAIT
)
SNMP = (
    "Ip: Forwarding DefaultTTL\nIp: 1 64\n"
    "Tcp: RtoAlgorithm RtoMin RtoMax MaxConn ActiveOpens PassiveOpens AttemptFails EstabResets CurrEstab InSegs\n"
    "Tcp: 1 200 120000 -1 100 7 3 2 4 5000\n"
    "Udp: InDatagrams NoPorts InErrors OutDatagrams RcvbufErrors\n"
    "Udp: 50 0 0 60 0\n"
)


class TestParseSockets:
    @pytest.mark.skipif(not LITTLE, reason="literal fixture is little-endian")
    def test_literal_kernel_lines(self):
        text = (
            HEADER
            + "   0: 0100007F:0035 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1 1\n"
            + "   1: 050012AC:9C40 0701A8C0:01BB 01 00000000:00000000 00:00000000 00000000     0        0 2 1\n"
        )
        socks, bad = procnet.parse_sockets(text, "tcp")
        assert bad == 0
        assert socks[0] == {
            "proto": "tcp",
            "lip": "127.0.0.1",
            "lport": 53,
            "rip": "0.0.0.0",
            "rport": 0,
            "state": "listen",
        }
        assert socks[1]["lip"] == "172.18.0.5" and socks[1]["rip"] == "192.168.1.7"
        assert socks[1]["rport"] == 443 and socks[1]["state"] == "est"

    @pytest.mark.skipif(not LITTLE, reason="literal fixture is little-endian")
    def test_v4_mapped_ipv6_folds_to_ipv4(self):
        text = (
            HEADER
            + "   0: 00000000000000000000000000000000:1F90 0000000000000000FFFF000004030201:C350 01 0 0 0 0 0 1 1\n"
        )
        socks, bad = procnet.parse_sockets(text, "tcp6")
        assert bad == 0
        assert socks[0]["rip"] == "1.2.3.4"
        assert socks[0]["lip"] == "::"

    def test_real_ipv6_stays_ipv6(self):
        socks, _ = procnet.parse_sockets(HEADER + line(0, "fd00::5", 40000, "2001:db8::1", 443, "01", v6=True), "tcp6")
        assert socks[0]["rip"] == "2001:db8::1"

    def test_every_state(self):
        text = HEADER + "".join(
            line(i, "172.18.0.5", 40000 + i, "198.51.100.1", 443, st)
            for i, st in enumerate(("01", "02", "03", "0A", "06", "08"))
        )
        socks, _ = procnet.parse_sockets(text, "tcp")
        assert [s["state"] for s in socks] == ["est", "syn_sent", "syn_recv", "listen", "closed", "closed"]

    def test_malformed_lines_are_counted_and_skipped(self):
        text = (
            TCP + "  9: ZZZZ:0035 00000000:0000 0A\n" + "  10: 0100007F\n" + "  11: 0100007F:0035 00000000:0000 XYZ\n"
        )
        socks, bad = procnet.parse_sockets(text, "tcp")
        assert bad == 3
        assert len(socks) == 7

    def test_mutated_line_is_not_read_as_a_socket(self):
        """Negative control: break the remote address of a good line and it disappears."""
        good = line(0, "172.18.0.5", 40000, "198.51.100.9", 443, "01")
        mutated = good.replace(hx("198.51.100.9"), "GG" + hx("198.51.100.9")[2:])
        assert procnet.parse_sockets(HEADER + good, "tcp") == ([procnet.parse_sockets(HEADER + good, "tcp")[0][0]], 0)
        assert procnet.parse_sockets(HEADER + mutated, "tcp") == ([], 1)

    def test_udp_bound_vs_connected(self):
        text = (
            HEADER
            + line(0, "0.0.0.0", 51820, "0.0.0.0", 0, "07")
            + line(1, "172.18.0.5", 5000, "198.51.100.3", 3478, "01")
        )
        socks, _ = procnet.parse_sockets(text, "udp")
        assert [s["state"] for s in socks] == ["other", "est"]
        assert socks[0]["proto"] == "udp"

    def test_missing_file_is_empty(self):
        assert procnet.parse_sockets(None, "tcp6") == ([], 0)


class TestParseSnmp:
    def test_reads_the_counters(self):
        got = procnet.parse_snmp(SNMP)
        assert got["tcp"] == {
            "ActiveOpens": 100,
            "PassiveOpens": 7,
            "AttemptFails": 3,
            "EstabResets": 2,
            "CurrEstab": 4,
        }
        assert got["udp"] == {"InDatagrams": 50, "OutDatagrams": 60}

    def test_missing_is_null_never_zero(self):
        assert procnet.parse_snmp(None) is None
        assert procnet.parse_snmp("") is None
        assert procnet.parse_snmp("Tcp: ActiveOpens\nTcp: 5\n") is None


class TestSummarise:
    def _summary(self, text=TCP, **kw):
        socks, _ = procnet.parse_sockets(text, "tcp")
        return procnet.summarise([socks], **kw)

    def test_inbound_vs_outbound_by_the_listen_set(self):
        s = self._summary()
        assert s["in"] == [["203.0.113.7", 8080, 1]]
        outs = {(o[0], o[1], o[2]) for o in s["out"]}
        assert outs == {("tcp", "198.51.100.9", 443), ("tcp", "192.168.1.10", 22)}
        assert s["listen_ports"] == [8080]  # 9000 is loopback-only
        assert s["est_max"] == 2 and s["syn_sent_max"] == 1

    def test_state_mix_and_seen_across_snapshots(self):
        socks, _ = procnet.parse_sockets(TCP, "tcp")
        s = procnet.summarise([socks, socks, socks])
        row = next(o for o in s["out"] if o[1] == "198.51.100.9")
        assert row[3] == 3
        assert row[4] == {"est": 3, "closed": 3}

    def test_caps_with_exact_total(self):
        text = HEADER + "".join(
            line(i, "172.18.0.5", 30000 + i, f"198.51.{i // 250}.{i % 250 + 1}", 443, "01") for i in range(100)
        )
        s = self._summary(text, cap_out=10, cap_in=5)
        assert len(s["out"]) == 10
        assert s["remotes_total"] == 100
        assert s["truncated"] is True

    def test_udp_bound_counted(self):
        socks, _ = procnet.parse_sockets(HEADER + line(0, "0.0.0.0", 51820, "0.0.0.0", 0, "07"), "udp")
        s = procnet.summarise([socks])
        assert s["udp_bound"] == 1 and s["out"] == []


class TestClassify:
    CTX = {"gateways": ["172.18.0.1"], "dns": ["1.1.1.1"], "subnets": [("172.18.0.5/16", "bridge")]}

    @pytest.mark.parametrize(
        ("ip", "port", "want"),
        [
            ("127.0.0.11", 53, "infra"),
            ("172.18.0.1", 53, "infra"),
            ("1.1.1.1", 53, "infra"),
            ("100.100.100.100", 53, "infra"),
            ("172.18.0.1", 22, "docker_host"),
            ("169.254.169.254", 80, "metadata"),
            ("fd00:ec2::254", 80, "metadata"),
            ("172.18.0.9", 8080, "peer"),
            ("192.168.1.1", 80, "lan"),
            ("172.16.0.1", 80, "lan"),
            ("172.31.255.255", 80, "lan"),
            ("fd12::1", 80, "lan"),
            ("100.64.0.1", 22, "tailnet"),
            ("100.100.100.100", 80, "tailnet"),
            ("169.254.1.1", 80, "link_local"),
            ("fe80::1", 80, "link_local"),
            ("224.0.0.251", 5353, "multicast"),
            ("172.15.255.255", 443, "public"),
            ("172.32.0.1", 443, "public"),
            ("100.63.255.255", 443, "public"),
            ("100.128.0.0", 443, "public"),
            ("1.1.1.1", 443, "public"),
            ("2001:db8::1", 443, "public"),
        ],
    )
    def test_edges(self, ip, port, want):
        assert procnet.classify(ip, port, self.CTX) == want

    def test_macvlan_subnet_is_lan_bridge_subnet_is_peer(self):
        assert procnet.classify("10.0.0.7", 80, {"subnets": [("10.0.0.5/24", "macvlan")]}) == "lan"
        assert procnet.classify("10.0.0.7", 80, {"subnets": [("10.0.0.5/24", "bridge")]}) == "peer"

    def test_ranges_equal_lan_isolation(self):
        assert procnet.RFC1918 == lan_isolation.RFC1918
        assert procnet.LINK_LOCAL == lan_isolation.LINK_LOCAL


class TestMain:
    def test_script_prints_valid_json_against_fixture_files(self, tmp_path):
        """The probe's own source, run as ``python -c``, against fixture files."""
        net = tmp_path / "net"
        net.mkdir()
        (net / "tcp").write_text(TCP)
        (net / "snmp").write_text(SNMP)
        (net / "udp").write_text(HEADER)
        source = (ROOT / "app" / "procnet.py").read_text(encoding="utf-8")
        # Point the reader at the fixtures; tcp6 and udp6 do not exist there.
        source = source.replace('"/proc/net/', f'"{net}/')
        out = subprocess.run(
            [sys.executable, "-c", source],
            env={"PROBE_SNAPSHOTS": "2", "PROBE_GAP": "0", "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        data = json.loads(out.stdout)
        assert data["v"] == 1
        assert data["snapshots"] == 2
        assert data["files"] == {"tcp": True, "tcp6": False, "udp": True, "udp6": False}
        assert data["snmp_start"]["tcp"]["ActiveOpens"] == 100
        assert data["summary"]["est_max"] == 2
        assert data["summary"]["out"][0][3] == 2  # seen in both snapshots

    def test_env_inputs_are_clamped(self, monkeypatch):
        monkeypatch.setenv("PROBE_SNAPSHOTS", "500")
        assert procnet._env_int("PROBE_SNAPSHOTS", 5, 1, 10) == 10
        monkeypatch.setenv("PROBE_SNAPSHOTS", "x")
        assert procnet._env_int("PROBE_SNAPSHOTS", 5, 1, 10) == 5


SNMP6 = (
    "Udp6InDatagrams                 \t40\nUdp6NoPorts                     \t0\nUdp6OutDatagrams                \t30\n"
)


class TestFixes:
    """Regressions from the review of the first cut."""

    @pytest.mark.parametrize(
        ("ip", "port"),
        [("192.168.1.1", 53), ("10.0.0.1", 853), ("fd12::1", 53), ("100.64.0.2", 53), ("169.254.1.1", 53)],
    )
    def test_dns_to_a_local_resolver_is_infra(self, ip, port):
        """Docker copies the host's resolv.conf (often the router) into a default-bridge earner."""
        assert procnet.classify(ip, port, {}) == "infra"

    def test_dns_rule_is_only_for_dns_ports(self):
        assert procnet.classify("192.168.1.1", 22, {}) == "lan"
        assert procnet.classify("169.254.169.254", 53, {}) == "metadata"
        assert procnet.classify("8.8.8.8", 53, {}) == "public"

    def test_bridge_neighbour_that_is_not_an_earner_is_docker_peer(self):
        ctx = {"subnets": [("172.17.0.2/16", "bridge")], "peers": ["172.17.0.9"]}
        assert procnet.classify("172.17.0.9", 8080, ctx) == "peer"
        assert procnet.classify("172.17.0.5", 5432, ctx) == "docker_peer"
        assert procnet.classify("172.17.0.7", 8123, ctx) == "docker_peer"

    def test_closing_states_are_closed(self):
        text = HEADER + "".join(
            line(i, "172.18.0.5", 40000 + i, "198.51.100.1", 25, st)
            for i, st in enumerate(("04", "05", "06", "08", "09", "0B", "07"))
        )
        socks, _ = procnet.parse_sockets(text, "tcp")
        assert [s["state"] for s in socks] == ["closed"] * 6 + ["other"]

    def test_udp6_counters_are_added(self):
        got = procnet.parse_snmp(SNMP, SNMP6)
        assert got["udp"] == {"InDatagrams": 90, "OutDatagrams": 90}
        assert procnet.parse_snmp(SNMP, None)["udp"] == {"InDatagrams": 50, "OutDatagrams": 60}
        assert procnet.parse_snmp(SNMP, "garbage\n")["udp"] == {"InDatagrams": 50, "OutDatagrams": 60}
