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

    def test_a_listener_closed_mid_sample_keeps_its_connections_inbound(self):
        listen = line(0, "0.0.0.0", 8080, "0.0.0.0", 0, "0A")
        conn = line(1, "172.18.0.5", 8080, "192.168.1.10", 51000, "01")
        first, _ = procnet.parse_sockets(HEADER + listen + conn, "tcp")
        later, _ = procnet.parse_sockets(HEADER + conn, "tcp")
        s = procnet.summarise([first, later])
        assert s["out"] == []
        assert s["in"] == [["192.168.1.10", 8080, 2]]

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


# ---------------------------------------------------------------------------
# Host-network earners: sock_diag sockets matched by cgroup
# ---------------------------------------------------------------------------


def _diag_msg(family, state, sport, dport, src, dst, cgroup=None, pad_attr=False):
    """One SOCK_DIAG_BY_FAMILY message as the kernel lays it out."""
    raw_src = socket.inet_pton(family, src).ljust(16, b"\0")
    raw_dst = socket.inet_pton(family, dst).ljust(16, b"\0")
    body = procnet._DIAG_MSG.pack(
        family, state, 0, 0, socket.htons(sport), socket.htons(dport), raw_src, raw_dst, 0, 0, 0, 0, 0, 0
    )
    if pad_attr:
        # An unrelated 5-byte attribute (padded to 8) before the cgroup id.
        body += struct.pack("=HH", 5, 99) + b"x" + b"\0" * 3
    if cgroup is not None:
        body += struct.pack("=HHQ", 12, procnet.INET_DIAG_CGROUP_ID, cgroup)
    return struct.pack("=IHHII", 16 + len(body), procnet.SOCK_DIAG_BY_FAMILY, 2, 1, 0) + body


def _done():
    return struct.pack("=IHHII", 20, procnet.NLMSG_DONE, 2, 1, 0) + b"\0" * 4


def _error(errno):
    return struct.pack("=IHHII", 36, procnet.NLMSG_ERROR, 0, 1, 0) + struct.pack("=i", -errno) + b"\0" * 16


class TestParseDiag:
    def test_reads_addresses_ports_state_and_cgroup(self):
        data = _diag_msg(socket.AF_INET, 1, 40000, 443, "10.0.0.5", "1.1.1.1", cgroup=4242, pad_attr=True)
        data += _diag_msg(socket.AF_INET6, 10, 4449, 0, "::", "::")
        socks, done, err = procnet.parse_diag(data, "tcp")
        assert (done, err) == (False, 0)
        assert socks == [
            {
                "proto": "tcp",
                "lip": "10.0.0.5",
                "lport": 40000,
                "rip": "1.1.1.1",
                "rport": 443,
                "cgroup": 4242,
                "state": "est",
            },
            {"proto": "tcp", "lip": "::", "lport": 4449, "rip": "::", "rport": 0, "cgroup": None, "state": "listen"},
        ]

    def test_udp_state_is_connected_or_not(self):
        data = _diag_msg(socket.AF_INET, 7, 5000, 53, "10.0.0.5", "9.9.9.9", cgroup=7)
        data += _diag_msg(socket.AF_INET, 7, 5001, 0, "0.0.0.0", "0.0.0.0", cgroup=7)
        socks, _, _ = procnet.parse_diag(data, "udp")
        assert [s["state"] for s in socks] == ["est", "other"]

    def test_done_and_error_end_the_dump(self):
        socks, done, err = procnet.parse_diag(
            _diag_msg(socket.AF_INET, 1, 1, 2, "10.0.0.1", "10.0.0.2", 3) + _done(), "tcp"
        )
        assert len(socks) == 1 and (done, err) == (True, 0)
        assert procnet.parse_diag(_error(13), "tcp") == ([], True, 13)

    def test_a_truncated_message_stops_with_an_error(self):
        data = _diag_msg(socket.AF_INET, 1, 1, 2, "10.0.0.1", "10.0.0.2", 3)
        assert procnet.parse_diag(data[:-4], "tcp") == ([], True, -1)


class TestCgroupIds:
    CID = "ab" * 32

    def _tree(self, tmp_path, v2=True):
        if v2:
            (tmp_path / "cgroup.controllers").write_text("cpu memory\n")
        return tmp_path

    def test_finds_the_container_and_its_children(self, tmp_path):
        root = self._tree(tmp_path)
        mine = root / "system.slice" / f"docker-{self.CID}.scope"
        (mine / "init").mkdir(parents=True)
        (root / "system.slice" / f"docker-{'cd' * 32}.scope").mkdir()
        ids, reason = procnet.cgroup_ids(self.CID, root=str(root))
        assert reason == ""
        assert ids == {mine.stat().st_ino, (mine / "init").stat().st_ino}

    def test_cgroupfs_layout(self, tmp_path):
        root = self._tree(tmp_path)
        (root / "docker" / self.CID).mkdir(parents=True)
        ids, reason = procnet.cgroup_ids(self.CID, root=str(root))
        assert ids == {(root / "docker" / self.CID).stat().st_ino} and reason == ""

    def test_v1_and_missing(self, tmp_path):
        assert procnet.cgroup_ids(self.CID, root=str(tmp_path)) == (set(), "cgroup_v1")
        root = self._tree(tmp_path)
        (root / "docker" / ("cd" * 32)).mkdir(parents=True)
        assert procnet.cgroup_ids(self.CID, root=str(root)) == (set(), "cgroup_missing")

    @pytest.mark.parametrize("bad", ["", "ab" * 6, "zz" * 32, "ab" * 33])
    def test_a_short_or_odd_id_never_matches(self, tmp_path, bad):
        root = self._tree(tmp_path)
        (root / "docker" / self.CID).mkdir(parents=True)
        assert procnet.cgroup_ids(bad, root=str(root)) == (set(), "cgroup_missing")

    def test_depth_and_directory_caps(self, tmp_path):
        root = self._tree(tmp_path)
        deep = root / "a" / "b" / "c" / self.CID
        deep.mkdir(parents=True)
        assert procnet.cgroup_ids(self.CID, root=str(root), max_depth=3)[1] == "cgroup_missing"
        assert procnet.cgroup_ids(self.CID, root=str(root), max_depth=4)[1] == ""
        for i in range(20):
            (root / f"x{i:02d}").mkdir()
        assert procnet.cgroup_ids(self.CID, root=str(root), max_dirs=5)[1] == "cgroup_missing"

    def test_the_directory_cap_holds_inside_one_large_directory(self, tmp_path):
        root = self._tree(tmp_path)
        mine = root / self.CID
        for i in range(50):
            (mine / f"c{i:02d}").mkdir(parents=True)
        ids, _ = procnet.cgroup_ids(self.CID, root=str(root), max_dirs=5)
        assert 1 <= len(ids) <= 5


def _sock(lport, cgroup, rip="1.1.1.1"):
    return {
        "proto": "tcp",
        "lip": "10.0.0.5",
        "lport": lport,
        "rip": rip,
        "rport": 443,
        "state": "est",
        "cgroup": cgroup,
    }


class TestCgroupSnapshot:
    def test_keeps_only_this_containers_sockets(self):
        dumps = (("tcp", 2, 6),)
        mine, tagged, worked = procnet.cgroup_snapshot(
            {10, 11}, dumps, lambda *a: [_sock(1, 10), _sock(2, 11), _sock(3, 99), _sock(4, None)]
        )
        assert [s["lport"] for s in mine] == [1, 2] and tagged and worked == 1
        assert "cgroup" not in mine[0]

    def test_a_missing_id_never_matches(self):
        """None == None must not hand the host's TIME_WAIT sockets to the earner."""
        mine, tagged, _ = procnet.cgroup_snapshot({None, 10}, (("tcp", 2, 6),), lambda *a: [_sock(1, None)])
        assert mine == [] and tagged is False

    def test_only_root_ids_count_as_untagged(self):
        _, tagged, _ = procnet.cgroup_snapshot({10}, (("tcp", 2, 6),), lambda *a: [_sock(1, 1), _sock(2, 1)])
        assert tagged is False

    def test_a_refused_dump_is_skipped(self):
        def dump(proto, *_):
            if proto == "tcp6":
                raise OSError(13, "refused")
            return [_sock(1, 10)]

        mine, _, worked = procnet.cgroup_snapshot({10}, (("tcp", 2, 6), ("tcp6", 10, 6)), dump)
        assert len(mine) == 1 and worked == 1


class TestCgroupReading:
    CID = "ab" * 32

    def _patch(self, monkeypatch, ids=({5}, ""), snap=None):
        monkeypatch.setattr(procnet, "cgroup_ids", lambda cid: ids)
        monkeypatch.setattr(procnet, "cgroup_snapshot", lambda ids: snap)
        monkeypatch.setattr(procnet.time, "sleep", lambda s: None)

    def test_ok(self, monkeypatch):
        self._patch(monkeypatch, snap=([_sock(1, 5)], True, 4))
        snaps, reason = procnet._cgroup_reading(self.CID, 3, 0)
        assert reason == "" and len(snaps) == 3

    @pytest.mark.parametrize(
        "ids,snap,reason",
        [
            ((set(), "cgroup_v1"), None, "cgroup_v1"),
            ((set(), "cgroup_missing"), None, "cgroup_missing"),
            (({5}, ""), ([], False, 0), "sock_diag_refused"),
            (({5}, ""), ([], False, 4), "kernel_no_cgroup_id"),
        ],
    )
    def test_reasons(self, monkeypatch, ids, snap, reason):
        self._patch(monkeypatch, ids=ids, snap=snap)
        assert procnet._cgroup_reading(self.CID, 2, 0) == ([], reason)


class TestMainModes:
    def _run(self, capsys, monkeypatch, env):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("PROBE_SNAPSHOTS", "2")
        monkeypatch.setenv("PROBE_GAP", "0")
        procnet.main()
        return json.loads(capsys.readouterr().out)

    def test_cgroup_mode_reports_no_namespace_or_counters(self, capsys, monkeypatch):
        monkeypatch.setattr(
            procnet, "_cgroup_reading", lambda cid, n, g: ([[_sock(1, 5) | {"rip": "1.1.1.1"}]] * n, "")
        )
        out = self._run(capsys, monkeypatch, {"PROBE_MODE": "cgroup", "PROBE_CONTAINER": "ab" * 32})
        assert out["attribution"] == "cgroup" and out["reason"] == ""
        assert out["netns"] is None and out["snmp_start"] is None and out["snmp_end"] is None
        assert out["summary"]["est_max"] == 1 and "classified" not in out

    def test_cgroup_mode_failure_carries_its_reason(self, capsys, monkeypatch):
        monkeypatch.setattr(procnet, "_cgroup_reading", lambda cid, n, g: ([], "cgroup_v1"))
        out = self._run(capsys, monkeypatch, {"PROBE_MODE": "cgroup", "PROBE_CONTAINER": "ab" * 32})
        assert out["reason"] == "cgroup_v1" and out["summary"]["out"] == []

    def test_probe_ctx_classifies_rows_in_the_helper(self, capsys, monkeypatch):
        socks = [_sock(1, 5, "192.168.1.1"), _sock(2, 5, "1.1.1.1")]
        monkeypatch.setattr(procnet, "_cgroup_reading", lambda cid, n, g: ([socks] * n, ""))
        ctx = {"gateways": [], "dns": [], "subnets": [], "peers": []}
        out = self._run(
            capsys, monkeypatch, {"PROBE_MODE": "cgroup", "PROBE_CONTAINER": "ab" * 32, "PROBE_CTX": json.dumps(ctx)}
        )
        assert out["classified"] is True
        assert {r[1]: r[3] for r in out["summary"]["out"]} == {"192.168.1.1": "lan", "1.1.1.1": "public"}

    @pytest.mark.parametrize("raw", ["", "not json", "[1, 2]"])
    def test_an_unreadable_ctx_is_ignored(self, monkeypatch, raw):
        monkeypatch.setenv("PROBE_CTX", raw)
        assert procnet._ctx_from_env() is None
