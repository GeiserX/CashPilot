"""Earners are fenced off the LAN by default (app/lan_fence.py).

A new install puts bridge-networked earners on CashPilot's own network, whose
masquerade lives in the same nftables table as the drops, so a missing table
leaves the earners offline instead of exposed. An upgraded install keeps its
earners where they are until the owner turns isolation on. These tests pin the
ruleset, the mode each install lands in, the refusal when the fence cannot be
applied, the switch, and the counter proof the isolation check relies on.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import stat
import subprocess
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Before worker_api is imported: it reads the fleet key once, at import, and a
# later module (test_isolation_check) relies on it being set.
os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest
from docker.errors import APIError, ImageNotFound, NotFound
from fastapi.testclient import TestClient

from app import isolation_check, lan_fence, orchestrator, worker_api
from app.main import app as ui_app

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "lan_fence"


@pytest.fixture(autouse=True)
def _fresh_state(tmp_path):
    saved = json.loads(json.dumps(lan_fence._state))
    egress = dict(lan_fence._egress)
    # Each test gets its own /data, so one test's "on" never leaks into the next.
    with patch.object(lan_fence, "ON_MARKER", tmp_path / "data" / ".isolation_on"):
        yield
    lan_fence._state.clear()
    lan_fence._state.update(saved)
    lan_fence._egress.clear()
    lan_fence._egress.update(egress)


# ---------------------------------------------------------------------------
# The ruleset
# ---------------------------------------------------------------------------


class TestTheRuleset:
    def test_nft_golden(self):
        """The text Desktop's port must produce byte for byte (shared fixture)."""
        got = lan_fence.render_nft("cp-isolated", "172.18.0.0/16", ["203.0.113.0/24"], egress="198.51.100.7", ipv6=True)
        assert got == (FIXTURES / "ruleset.nft").read_text()

    def test_reduced_keeps_only_the_masquerade(self):
        got = lan_fence.render_nft("cp-isolated", "172.18.0.0/16", [], filtered=False)
        assert got == (FIXTURES / "ruleset-reduced.nft").read_text()
        assert "drop" not in got

    def test_iptables_golden(self):
        got = lan_fence.render_iptables(
            "cp-isolated", "172.18.0.0/16", ["203.0.113.0/24"], egress="198.51.100.7", ipv6=True
        )
        assert got == (FIXTURES / "ruleset.iptables.sh").read_text()

    @pytest.mark.parametrize(
        "cidr", ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16"]
    )
    def test_every_private_range_is_dropped(self, cidr):
        nft = lan_fence.render_nft("cp-isolated", "172.18.0.0/16")
        assert f'iifname "cp-isolated" ip daddr {cidr} counter drop' in nft
        assert f"-d {cidr} " in lan_fence.render_iptables("cp-isolated", "172.18.0.0/16")

    def test_the_masquerade_is_in_the_same_table_as_the_drops(self):
        """Fail closed: whatever removes the drops removes the internet with them."""
        nft = lan_fence.render_nft("cp-isolated", "172.18.0.0/16")
        table = nft.split(f"table ip {lan_fence.TABLE} {{", 1)[1]
        assert "masquerade" in table and "drop" in table

    def test_the_host_is_dropped_on_input(self):
        nft = lan_fence.render_nft("cp-isolated", "172.18.0.0/16")
        chain = nft.split("chain input {", 1)[1]
        assert 'iifname "cp-isolated" counter drop comment "host"' in chain

    def test_the_drops_run_before_docker_and_tailscale(self):
        nft = lan_fence.render_nft("cp-isolated", "172.18.0.0/16")
        assert nft.count("priority -150;") == 2

    def test_replies_on_published_ports_still_leave(self):
        nft = lan_fence.render_nft("cp-isolated", "172.18.0.0/16")
        for chain in ("forward", "input"):
            body = nft.split(f"chain {chain} {{", 1)[1].split("}", 1)[0]
            lines = [ln for ln in body.splitlines() if "iifname" in ln]
            assert "ct state established,related" in lines[0], f"{chain}: the established accept must come first"

    def test_only_replies_pass_the_drops(self):
        """A connection an earner opened while the table was missing must not keep going once it is back."""
        nft = lan_fence.render_nft("cp-isolated", "172.18.0.0/16")
        for name in (lan_fence.FWD_EST_RULE, lan_fence.IN_EST_RULE):
            (line,) = [ln for ln in nft.splitlines() if f'comment "{name}"' in ln]
            assert "ct direction reply" in line
        ipt = lan_fence.render_iptables("cp-isolated", "172.18.0.0/16")
        accepts = [ln for ln in ipt.splitlines() if "--ctstate" in ln]
        assert len(accepts) == 2 and all("--ctdir REPLY" in ln for ln in accepts)

    @pytest.mark.parametrize("filtered", [True, False])
    @pytest.mark.parametrize(("egress", "ipv6"), [(None, False), ("198.51.100.7", True)])
    def test_every_rule_has_its_own_name(self, filtered, egress, ipv6):
        """read_fence compares the names it finds with these; a duplicate would hide a missing rule."""
        extras = ["203.0.113.0/24"]
        nft = lan_fence.render_nft("cp-isolated", "172.18.0.0/16", extras, filtered, egress, ipv6)
        names = [ln.rsplit('comment "', 1)[1].rstrip('"') for ln in nft.splitlines() if 'comment "' in ln]
        assert len(names) == len(set(names))
        expected = lan_fence.rule_names("172.18.0.0/16", extras, filtered, egress, ipv6)
        assert set(names) == expected
        ipt = lan_fence.render_iptables("cp-isolated", "172.18.0.0/16", extras, filtered, egress, ipv6)
        ipt_names = [ln.split("--comment ", 1)[1].split()[0] for ln in ipt.splitlines() if "--comment" in ln]
        assert set(ipt_names) == expected

    def test_the_masquerade_name_carries_the_subnet(self):
        """A network recreated on another subnet must change a name, or the helper keeps the old NAT."""
        assert lan_fence.rule_names("172.18.0.0/16") != lan_fence.rule_names("172.19.0.0/16")
        assert 'comment "masquerade-172.19.0.0/16"' in lan_fence.render_nft("cp-isolated", "172.19.0.0/16")

    def test_the_homes_public_ip_is_dropped(self):
        """NAT loopback: a connect to the WAN IP comes back into the LAN with a LAN source."""
        nft = lan_fence.render_nft("cp-isolated", "172.18.0.0/16", egress="198.51.100.7")
        forward = nft.split("chain forward {", 1)[1].split("}", 1)[0]
        assert 'iifname "cp-isolated" ip daddr 198.51.100.7 counter drop comment "egress-198.51.100.7"' in forward
        ipt = lan_fence.render_iptables("cp-isolated", "172.18.0.0/16", egress="198.51.100.7")
        assert "-A CP-FWD -d 198.51.100.7/32 -m comment --comment egress-198.51.100.7 -j DROP" in ipt

    @pytest.mark.parametrize("value", [None, "", "192.168.1.1", "100.64.1.1", "2001:db8::1", "x; flush ruleset"])
    def test_only_a_public_ipv4_becomes_an_egress_drop(self, value):
        assert lan_fence.egress_target(value) is None

    def test_ipv6_from_the_bridge_is_dropped_on_both_hooks(self):
        """Engines before 26 give containers an fe80:: address even on an IPv4-only network."""
        nft = lan_fence.render_nft("cp-isolated", "172.18.0.0/16", ipv6=True)
        table = nft.split("table ip6 cashpilot {", 1)[1]
        assert 'iifname "cp-isolated" counter drop comment "ipv6-forward"' in table.split("chain input", 1)[0]
        assert 'iifname "cp-isolated" counter drop comment "ipv6-host"' in table.split("chain input", 1)[1]
        assert "delete table ip6 cashpilot" in nft, "the ip6 table is replaced atomically too"
        ipt = lan_fence.render_iptables("cp-isolated", "172.18.0.0/16", ipv6=True)
        assert "ip6tables-legacy -w -t mangle -A CP6-IN -m comment --comment ipv6-host -j DROP" in ipt

    def test_reduced_with_ipv6_removes_the_ip6_table(self):
        nft = lan_fence.render_nft("cp-isolated", "172.18.0.0/16", filtered=False, ipv6=True)
        assert "delete table ip6 cashpilot" in nft and "table ip6 cashpilot {" not in nft

    def test_a_subnet_that_is_not_one_is_refused(self):
        with pytest.raises(ValueError):
            lan_fence.render_nft("cp-isolated", '172.18.0.0/16"; flush ruleset; "')


ROUTE = """Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT
eth0\t00000000\t0171A8C0\t0003\t0\t0\t0\t00000000\t0\t0\t0
eth0\t0071A8C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0
ens3\t007100CB\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0
docker0\t000011AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0
br-1234\t000012AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0
cp-isolated\t000013AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0
tailscale0\t00004064\t00000000\t0001\t0\t0\t0\t0000C0FF\t0\t0\t0
ens3\t000000CC\t017100CB\t0003\t0\t0\t0\t000000FF\t0\t0\t0
"""


class TestConnectedSubnets:
    def test_a_lan_in_public_space_is_added(self):
        """192.168.113.0/24 is already dropped; 203.0.113.0/24 on a real interface is not."""
        assert lan_fence.connected_subnets(ROUTE) == ["203.0.113.0/24"]

    def test_nothing_on_a_plain_home_host(self):
        assert lan_fence.connected_subnets(ROUTE.splitlines()[0] + "\n" + ROUTE.splitlines()[2]) == []


NFT_LISTING = """table ip cashpilot {
	chain postrouting {
		type nat hook postrouting priority srcnat; policy accept;
		ip saddr 172.18.0.0/16 oifname != "cp-isolated" counter packets 12 bytes 720 masquerade comment "masquerade"
	}
	chain forward {
		type filter hook forward priority -150; policy accept;
		iifname "cp-isolated" ip daddr 192.168.0.0/16 counter packets 3 bytes 180 drop comment "rfc1918-192"
		iifname "cp-isolated" ip daddr 10.0.0.0/8 counter packets 0 bytes 0 drop comment "rfc1918-10"
	}
}
"""

IPT_LISTING = """Chain CP-FWD (1 references)
    pkts      bytes target     prot opt in     out     source               destination
       0        0 RETURN     0    --  *      *       0.0.0.0/0            0.0.0.0/0            ctstate RELATED,ESTABLISHED ctdir REPLY /* forward-reply */
       4      240 DROP       0    --  *      *       0.0.0.0/0            10.0.0.0/8           /* rfc1918-10 */
"""


class TestCounters:
    def test_nft(self):
        assert lan_fence.parse_nft_counters(NFT_LISTING) == {"masquerade": 12, "rfc1918-192": 3, "rfc1918-10": 0}

    def test_iptables(self):
        assert lan_fence.parse_iptables_counters(IPT_LISTING) == {"forward-reply": 0, "rfc1918-10": 4}


# ---------------------------------------------------------------------------
# The helper, end to end against a fake nft
# ---------------------------------------------------------------------------

#: A stand-in for iptables-legacy: each chain is a file of listing lines, and
#: a jump into a chain is a marker file the -I adds and -C looks for.
FAKE_IPT = r"""#!/bin/sh
d="$FAKE_NFT_DIR/ipt"; mkdir -p "$d"
op=""; chain=""; hook=""; name=""; target=""
while [ $# -gt 0 ]; do
  case "$1" in
    -w) ;;
    -t) shift ;;
    -N|-F|-L) op="$1"; chain="$2"; shift ;;
    -A) op="-A"; chain="$2"; shift ;;
    -C|-I) op="$1"; hook="$2"; shift ;;
    --comment) name="$2"; shift ;;
    -j) target="$2"; shift ;;
  esac
  shift
done
case "$op" in
  -N) [ -f "$d/chain-$chain" ] && exit 1; : > "$d/chain-$chain" ;;
  -F) : > "$d/chain-$chain" ;;
  -A) echo "       0        0 $target  0 -- * * 0.0.0.0/0 0.0.0.0/0 /* $name */" >> "$d/chain-$chain" ;;
  -I) touch "$d/jump-$hook-$target" ;;
  -C) [ -f "$d/jump-$hook-$target" ] || exit 1 ;;
  -L) [ -f "$d/chain-$chain" ] || exit 1; echo "Chain $chain"; cat "$d/chain-$chain" ;;
esac
exit 0
"""

FAKE_NFT = """#!/bin/sh
# A stand-in for nft: "-f -" stores the table as nft would list it, with
# counters, and "list table" prints it back.
store="$FAKE_NFT_DIR/table"
case "$1 $2" in
  "list tables") exit 0 ;;
  "list table") [ -f "$store" ] && cat "$store" && exit 0; exit 1 ;;
  "-f -") echo x >> "$FAKE_NFT_DIR/writes"; sed 's/counter /counter packets 0 bytes 0 /' > "$store"; exit 0 ;;
esac
exit 2
"""


class TestTheHelperScript:
    def _run(
        self, tmp_path, action, filtered="1", subnet="172.18.0.0/16", ipv6=False, egress="", route=None, backend="auto"
    ):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        for tool, text in (("nft", FAKE_NFT), ("iptables-legacy", FAKE_IPT), ("ip6tables-legacy", FAKE_IPT)):
            path = bin_dir / tool
            path.write_text(text)
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        route_file = tmp_path / "route"
        if route is None:
            route_file.write_text(ROUTE.splitlines()[0] + "\n" + ROUTE.splitlines()[2] + "\n")
        elif route is not False:
            route_file.write_text(route)
        env = dict(
            os.environ,
            PATH=f"{bin_dir}:{os.environ['PATH']}",
            FAKE_NFT_DIR=str(tmp_path),
            FENCE_IFACE="cp-isolated",
            FENCE_SUBNET=subnet,
            FENCE_FILTER=filtered,
            FENCE_BACKEND=backend,
            FENCE_EGRESS=egress,
            FENCE_PROC_ROUTE=str(route_file),
            FENCE_PROC_IPV6=str(tmp_path / ("ipv6" if ipv6 else "no-ipv6")),
            FENCE_PROC_IF_INET6=str(tmp_path / "if_inet6"),
        )
        (tmp_path / "ipv6").mkdir(exist_ok=True)
        (tmp_path / "if_inet6").write_text(
            "fe80000000000000a8c1abfffe010203 0c 40 20 80  cp-isolated\n"
            "fe80000000000000a8c1abfffe0a0b0c 03 40 20 80  docker0\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", lan_fence.HELPER_SCRIPT, action],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    def _writes(self, tmp_path):
        path = tmp_path / "writes"
        return len(path.read_text().splitlines()) if path.exists() else 0

    def test_apply_writes_the_table_once_and_then_leaves_it(self, tmp_path):
        first = self._run(tmp_path, "apply")
        assert first["ok"] and first["changed"] and first["matches"] and first["backend"] == "nft"
        second = self._run(tmp_path, "apply")
        assert second["ok"] and not second["changed"], "an intact table is not rewritten (its counters are kept)"
        assert self._writes(tmp_path) == 1

    def test_a_missing_rule_is_put_back(self, tmp_path):
        self._run(tmp_path, "apply")
        table = tmp_path / "table"
        table.write_text("\n".join(ln for ln in table.read_text().splitlines() if "rfc1918-192" not in ln))
        assert not self._run(tmp_path, "read")["matches"]
        again = self._run(tmp_path, "apply")
        assert again["changed"] and again["matches"]

    def test_unreadable_routes_leave_the_table_alone(self, tmp_path):
        """Without the routes a LAN numbered in public space would lose its drop."""
        first = self._run(tmp_path, "apply", route=ROUTE)
        assert first["ok"] and "connected-203.0.113.0/24" in first["counters"]
        (tmp_path / "route").unlink()
        got = self._run(tmp_path, "apply", route=False)
        assert not got["ok"] and not got["changed"] and "routes" in got["error"]
        assert self._writes(tmp_path) == 1
        assert "connected-203.0.113.0/24" in (tmp_path / "table").read_text()

    def test_reduce_does_not_need_the_routes(self, tmp_path):
        got = self._run(tmp_path, "apply", filtered="0", route=False)
        assert got["ok"] and got["matches"]

    def test_legacy_puts_a_lost_jump_back(self, tmp_path):
        """A firewall script that flushes FORWARD keeps our chain but no longer jumps into it."""
        first = self._run(tmp_path, "apply", backend="legacy")
        assert first["ok"] and first["changed"] and first["matches"] and first["backend"] == "legacy"
        assert not self._run(tmp_path, "apply", backend="legacy")["changed"]
        (tmp_path / "ipt" / "jump-FORWARD-CP-FWD").unlink()
        assert not self._run(tmp_path, "read", backend="legacy")["matches"]
        again = self._run(tmp_path, "apply", backend="legacy")
        assert again["changed"] and again["matches"]
        assert (tmp_path / "ipt" / "jump-FORWARD-CP-FWD").exists()

    def test_read_never_writes(self, tmp_path):
        got = self._run(tmp_path, "read")
        assert not got["present"] and not got["matches"]
        assert self._writes(tmp_path) == 0

    def test_reduce_drops_the_filters_and_keeps_the_masquerade(self, tmp_path):
        self._run(tmp_path, "apply")
        got = self._run(tmp_path, "apply", filtered="0")
        assert got["changed"] and set(got["counters"]) == {"masquerade-172.18.0.0/16"}

    def test_a_new_subnet_rewrites_the_table(self, tmp_path):
        """The network came back on another subnet: the old masquerade would leave the earners offline."""
        self._run(tmp_path, "apply")
        got = self._run(tmp_path, "apply", subnet="172.19.0.0/16")
        assert got["changed"] and got["matches"]
        assert "ip saddr 172.19.0.0/16" in (tmp_path / "table").read_text()

    def test_the_egress_ip_is_written_and_a_change_rewrites(self, tmp_path):
        first = self._run(tmp_path, "apply", egress="81.61.1.9")
        assert first["egress"] == "81.61.1.9" and "egress-81.61.1.9" in first["counters"]
        again = self._run(tmp_path, "apply", egress="81.61.1.10")
        assert again["changed"] and "egress-81.61.1.10" in again["counters"]
        assert "egress-81.61.1.9" not in again["counters"]

    def test_an_unknown_public_ip_keeps_the_drop_the_table_has(self, tmp_path):
        """A worker restart or a failed lookup must not reopen NAT loopback."""
        self._run(tmp_path, "apply", egress="81.61.1.9")
        got = self._run(tmp_path, "apply", egress="")
        assert got["ok"] and not got["changed"] and got["matches"]
        assert got["egress"] == "81.61.1.9" and "egress-81.61.1.9" in got["counters"]
        self._run(tmp_path, "apply", filtered="0")
        assert self._run(tmp_path, "apply", egress="")["egress"] is None, "nothing to keep, nothing invented"

    def test_with_ipv6_on_the_host_the_ip6_drops_are_written(self, tmp_path):
        got = self._run(tmp_path, "apply", ipv6=True)
        assert got["ipv6"] and got["matches"]
        assert {"ipv6-forward", "ipv6-host"} <= set(got["counters"])
        assert got["bridge_ipv6"] == "fe80::a8c1:abff:fe01:203"

    def test_without_ipv6_on_the_host_no_ip6_table(self, tmp_path):
        """A kernel booted with ipv6.disable=1 has no ip6 hooks; asking for them would fail the whole apply."""
        got = self._run(tmp_path, "apply", ipv6=False)
        assert not got["ipv6"] and got["matches"] and got["bridge_ipv6"] is None
        assert "ip6" not in (tmp_path / "table").read_text()


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


def _container(name, mode="bridge", nets=("bridge",), slug=None, status="running"):
    c = MagicMock()
    c.name = name
    c.status = status
    c.labels = {"cashpilot.service": slug or name.removeprefix("cashpilot-")}
    c.attrs = {
        "HostConfig": {"NetworkMode": mode},
        "NetworkSettings": {"Networks": {n: {} for n in nets}},
    }
    return c


def _network(name=lan_fence.NETWORK_NAME, labeled=True, containers=None):
    net = MagicMock()
    net.name = name
    net.id = "net-" + name
    net.attrs = {
        "Name": name,
        "Driver": "bridge",
        "Options": dict(lan_fence._REQUIRED_OPTIONS),
        "Labels": {lan_fence.NETWORK_LABEL: lan_fence.NETWORK_LABEL_VALUE} if labeled else {},
        "IPAM": {"Config": [{"Subnet": "172.18.0.0/16", "Gateway": "172.18.0.1"}]},
        "Containers": containers or {},
    }
    return net


def _docker(managed=None, earners=()):
    """A client with our labeled network present or not, and these managed containers."""
    client = MagicMock()
    nets = {}
    if managed is not None:
        nets[managed.name] = managed

    def _list(filters=None, **kw):
        if filters and "label" in filters:
            return [n for n in nets.values() if n.attrs["Labels"].get(lan_fence.NETWORK_LABEL)]
        return list(nets.values())

    def _get(name):
        for n in nets.values():
            if name in (n.name, n.id):
                return n
        raise NotFound("no such network")

    client.networks.list.side_effect = _list
    client.networks.get.side_effect = _get
    client.networks.create.side_effect = lambda name, **kw: nets.setdefault(name, _network(name))
    client.containers.list.return_value = list(earners)
    client._nets = nets
    return client


def _mode(client, setting="auto", operator=""):
    with patch.object(lan_fence, "_SETTING", setting), patch.object(orchestrator, "_CONTAINER_NETWORK", operator):
        return lan_fence.resolve_mode(client)


class TestModes:
    def test_a_fresh_install_is_on(self):
        assert _mode(_docker()) == lan_fence.MODE_ON

    def test_an_install_with_only_host_network_earners_is_on(self):
        assert _mode(_docker(earners=[_container("cashpilot-mysterium", "host", ("host",))])) == lan_fence.MODE_ON

    def test_an_upgraded_install_with_bridge_earners_is_legacy(self):
        assert _mode(_docker(earners=[_container("cashpilot-honeygain")])) == lan_fence.MODE_LEGACY

    def test_our_network_keeps_it_on_even_with_earners_left_on_the_bridge(self):
        """The state lives in Docker: a lost /data or a reinstall does not switch it off."""
        client = _docker(_network(), earners=[_container("cashpilot-honeygain")])
        assert _mode(client) == lan_fence.MODE_ON

    def test_an_unlabeled_network_by_our_name_does_not_count(self):
        client = _docker(_network(labeled=False), earners=[_container("cashpilot-honeygain")])
        assert _mode(client) == lan_fence.MODE_LEGACY

    def test_an_earner_still_bound_to_our_removed_network_keeps_it_on(self):
        """Unraid removes our network on a Docker restart; a stopped earner on the default bridge must not flip it."""
        fenced = _orphan("cashpilot-honeygain", "old-id", error=TestReattach.GONE)
        client = _docker(earners=[fenced, _container("cashpilot-storj", status="exited")])
        assert _mode(client) == lan_fence.MODE_ON

    def test_an_earner_on_someone_elses_network_by_our_name_does_not_count(self):
        theirs = _container("cashpilot-a", lan_fence.NETWORK_NAME, (lan_fence.NETWORK_NAME,))
        client = _docker(_network(labeled=False), earners=[theirs, _container("cashpilot-b")])
        assert _mode(client) == lan_fence.MODE_LEGACY

    def test_on_forces_it(self):
        assert _mode(_docker(earners=[_container("cashpilot-honeygain")]), "on") == lan_fence.MODE_ON

    def test_off_is_the_opt_out(self):
        assert _mode(_docker(_network()), "off") == lan_fence.MODE_OFF

    def test_the_operators_network_wins_over_everything(self):
        assert _mode(_docker(_network()), "on", operator="mine") == lan_fence.MODE_OPERATOR

    def test_an_unknown_setting_reads_as_auto(self):
        with patch.object(lan_fence, "_SETTING", "yes please"):
            assert lan_fence.setting() == "auto"


class TestTheRememberedState:
    """Isolation on is recorded in /data, for when Docker no longer shows it."""

    def test_on_survives_a_reboot_that_took_the_network_after_every_fenced_earner_was_removed(self):
        """The fenced earners were removed, a stopped default-bridge one was left, and the reboot took the network."""
        stopped = _container("cashpilot-storj", status="exited")
        assert _mode(_docker(_network(), earners=[stopped])) == lan_fence.MODE_ON
        assert _mode(_docker(earners=[stopped])) == lan_fence.MODE_ON

    def test_enable_records_it(self):
        client = _docker(earners=[_container("cashpilot-earnapp")])
        with (
            patch.object(lan_fence, "_SETTING", "auto"),
            patch.object(orchestrator, "_CONTAINER_NETWORK", ""),
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(lan_fence, "run_helper", return_value={"ok": True, "backend": "nft"}),
        ):
            lan_fence.enable()
        assert lan_fence.ON_MARKER.is_file()
        assert _mode(_docker(earners=[_container("cashpilot-earnapp", status="exited")])) == lan_fence.MODE_ON

    def test_legacy_records_nothing(self):
        assert _mode(_docker(earners=[_container("cashpilot-honeygain")])) == lan_fence.MODE_LEGACY
        assert not lan_fence.ON_MARKER.exists()

    def test_off_forgets_it(self):
        """The way out: after off, an install with bridge earners and no network of ours is legacy again."""
        assert _mode(_docker()) == lan_fence.MODE_ON
        assert _mode(_docker(), "off") == lan_fence.MODE_OFF
        assert not lan_fence.ON_MARKER.exists()
        assert _mode(_docker(earners=[_container("cashpilot-honeygain")])) == lan_fence.MODE_LEGACY

    def test_the_operators_network_leaves_it_alone(self):
        assert _mode(_docker()) == lan_fence.MODE_ON
        assert _mode(_docker(), operator="mine") == lan_fence.MODE_OPERATOR
        assert lan_fence.ON_MARKER.is_file()

    def test_an_unwritable_data_dir_still_resolves(self, tmp_path):
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("")
        with patch.object(lan_fence, "ON_MARKER", blocker / ".isolation_on"):
            assert _mode(_docker()) == lan_fence.MODE_ON
            assert _mode(_docker(earners=[_container("cashpilot-honeygain")])) == lan_fence.MODE_LEGACY


class TestTheNetwork:
    def test_it_is_created_with_the_masquerade_off(self):
        client = _docker()
        lan_fence.ensure_network(client)
        kwargs = client.networks.create.call_args.kwargs
        assert client.networks.create.call_args.args == (lan_fence.NETWORK_NAME,)
        assert kwargs["options"]["com.docker.network.bridge.enable_ip_masquerade"] == "false"
        assert kwargs["options"]["com.docker.network.bridge.enable_icc"] == "false"
        assert kwargs["options"]["com.docker.network.bridge.name"] == lan_fence.BRIDGE_INTERFACE
        assert kwargs["labels"] == {lan_fence.NETWORK_LABEL: lan_fence.NETWORK_LABEL_VALUE}
        assert kwargs["enable_ipv6"] is False

    def test_an_empty_unlabeled_one_is_replaced(self):
        old = _network(labeled=False)
        client = _docker(old)
        lan_fence.ensure_network(client)
        old.remove.assert_called_once()
        client.networks.create.assert_called_once()

    def test_the_created_options_are_the_ones_it_checks(self):
        assert lan_fence._REQUIRED_OPTIONS == {
            "com.docker.network.bridge.name": lan_fence.BRIDGE_INTERFACE,
            "com.docker.network.bridge.enable_ip_masquerade": "false",
            "com.docker.network.bridge.enable_icc": "false",
        }

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("com.docker.network.bridge.name", "br-other"),
            ("com.docker.network.bridge.enable_ip_masquerade", "true"),
            ("com.docker.network.bridge.enable_icc", None),
        ],
    )
    def test_a_labeled_one_the_fence_cannot_hold_is_refused(self, key, value):
        """The rules match the interface by name; on another bridge they would fence nothing."""
        net = _network()
        if value is None:
            net.attrs["Options"].pop(key)
        else:
            net.attrs["Options"][key] = value
        client = _docker(net)
        with pytest.raises(lan_fence.IsolationConflict, match=key):
            lan_fence.ensure_network(client)
        client.networks.create.assert_not_called()

    def test_an_unlabeled_one_in_use_is_left_alone(self):
        old = _network(labeled=False, containers={"abc": {}})
        client = _docker(old)
        with pytest.raises(lan_fence.IsolationConflict, match="CASHPILOT_CONTAINER_NETWORK=cashpilot-isolated"):
            lan_fence.ensure_network(client)
        old.remove.assert_not_called()
        client.networks.create.assert_not_called()


# ---------------------------------------------------------------------------
# Deploys
# ---------------------------------------------------------------------------


def _deploy(client, setting, helper_result=None, helper_error=None, old=None, network_mode=None):
    if old is None:
        client.containers.get.side_effect = NotFound("nope")
    else:
        client.containers.get.side_effect = None
        client.containers.get.return_value = old
    created = MagicMock(id="new", short_id="new")
    client.containers.run.return_value = created
    helper = MagicMock(return_value=helper_result or {"ok": True, "changed": True, "backend": "nft", "counters": {}})
    if helper_error:
        helper.side_effect = helper_error
    with (
        patch.object(lan_fence, "_SETTING", setting),
        patch.object(orchestrator, "_CONTAINER_NETWORK", ""),
        patch.object(orchestrator, "_get_client", return_value=client),
        patch.object(lan_fence, "run_helper", helper),
    ):
        orchestrator.deploy_raw(slug="honeygain", image="honeygain/honeygain", network_mode=network_mode)
    return client.containers.run.call_args.kwargs, helper


class TestDeploys:
    def test_a_fresh_install_deploys_behind_the_fence(self):
        client = _docker()
        kwargs, helper = _deploy(client, "auto")
        assert kwargs["network"] == lan_fence.NETWORK_NAME
        assert kwargs["network_mode"] is None
        assert kwargs["dns"] == ["1.1.1.1", "9.9.9.9"], "a LAN resolver is behind the fence"
        assert helper.call_args.args[1:] == ("apply", "172.18.0.0/16")
        assert lan_fence.status()["fence"]["state"] == "applied"

    def test_default_network_mode_is_the_bridge_and_is_fenced(self):
        """Docker's "default" is the same default bridge; spelled that way it must not skip the fence."""
        client = _docker()
        kwargs, helper = _deploy(client, "auto", network_mode="default")
        assert kwargs["network"] == lan_fence.NETWORK_NAME and kwargs["network_mode"] is None
        helper.assert_called_once()

    def test_an_upgraded_install_keeps_the_default_bridge(self):
        client = _docker(earners=[_container("cashpilot-earnapp")])
        kwargs, helper = _deploy(client, "auto")
        assert kwargs["network"] is None
        helper.assert_not_called()
        client.networks.create.assert_not_called()

    def test_off_keeps_the_default_bridge(self):
        client = _docker()
        kwargs, helper = _deploy(client, "off")
        assert kwargs["network"] is None
        helper.assert_not_called()

    @pytest.mark.parametrize(
        ("result", "error"),
        [({"ok": False, "backend": "legacy", "error": "can't initialize iptables table"}, None), (None, OSError("x"))],
    )
    def test_a_fence_that_cannot_be_applied_refuses_before_the_old_container_is_touched(self, result, error):
        old = MagicMock()
        old.labels = {"cashpilot.service": "honeygain"}
        client = _docker()
        with pytest.raises(orchestrator.ContainerNetworkError, match="CASHPILOT_ISOLATION=off"):
            _deploy(client, "auto", helper_result=result, helper_error=error, old=old)
        old.stop.assert_not_called()
        old.remove.assert_not_called()
        client.containers.run.assert_not_called()
        client.images.pull.assert_not_called()
        assert lan_fence.status()["fence"]["state"] == "failed"

    def test_host_networking_is_never_moved(self):
        client = _docker()
        client.containers.get.side_effect = NotFound("nope")
        client.containers.run.return_value = MagicMock(id="n", short_id="n")
        with (
            patch.object(lan_fence, "_SETTING", "on"),
            patch.object(orchestrator, "_CONTAINER_NETWORK", ""),
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(lan_fence, "run_helper") as helper,
        ):
            orchestrator.deploy_raw(slug="mysterium", image="mysteriumnetwork/myst", network_mode="host")
        assert client.containers.run.call_args.kwargs["network_mode"] == "host"
        helper.assert_not_called()


# ---------------------------------------------------------------------------
# The periodic check
# ---------------------------------------------------------------------------


def _reconcile(client, setting, operator="", result=None, on_helper=None):
    answer = result or {"ok": True, "backend": "nft", "counters": {}}

    def _helper(*_a, **_kw):
        if on_helper:
            on_helper()
        return answer

    with (
        patch.object(lan_fence, "_SETTING", setting),
        patch.object(orchestrator, "_CONTAINER_NETWORK", operator),
        patch.object(orchestrator, "docker_available", return_value=True),
        patch.object(orchestrator, "_get_client", return_value=client),
        patch.object(lan_fence, "run_helper", side_effect=_helper) as helper,
    ):
        return lan_fence.reconcile(), helper


class TestReconcile:
    def test_on_puts_the_full_table_back(self):
        state, helper = _reconcile(_docker(_network()), "auto")
        assert helper.call_args.kwargs["filtered"] is True
        assert state["mode"] == "on" and state["fence"]["state"] == "applied"

    def test_off_with_our_network_left_keeps_only_the_masquerade(self):
        """The way back out: earners still on the network keep their internet."""
        state, helper = _reconcile(_docker(_network()), "off")
        assert helper.call_args.kwargs["filtered"] is False
        assert state["fence"]["state"] == "reduced"

    def test_operator_keeps_the_nat_for_earners_still_on_our_network(self):
        """A custom network was chosen; earners not yet redeployed must not lose their internet on a reload."""
        net = _network(containers={"abc": {"Name": "cashpilot-honeygain"}})
        state, helper = _reconcile(_docker(net), "auto", operator="my-net")
        assert helper.call_args.kwargs["filtered"] is False
        assert state["mode"] == "operator" and state["fence"]["state"] == "reduced"

    def test_operator_with_our_network_empty_touches_nothing(self):
        _state, helper = _reconcile(_docker(_network()), "auto", operator="my-net")
        helper.assert_not_called()

    def test_off_without_our_network_touches_nothing(self):
        _state, helper = _reconcile(_docker(), "off")
        helper.assert_not_called()

    def test_legacy_names_the_exposed_earners_and_touches_nothing(self):
        state, helper = _reconcile(_docker(earners=[_container("cashpilot-earnapp")]), "auto")
        helper.assert_not_called()
        assert state["mode"] == "legacy" and state["earners_outside"] == ["earnapp"]

    def test_on_names_earners_still_off_the_network(self):
        earners = [_container("cashpilot-earnapp"), _container("cashpilot-honeygain", nets=(lan_fence.NETWORK_NAME,))]
        state, _helper = _reconcile(_docker(_network(), earners=earners), "auto")
        assert state["earners_outside"] == ["earnapp"]

    def test_no_docker_no_helper(self):
        with (
            patch.object(orchestrator, "docker_available", return_value=False),
            patch.object(lan_fence, "run_helper") as helper,
        ):
            state = lan_fence.reconcile()
        helper.assert_not_called()
        assert state["mode"] is None

    def test_a_failure_is_reported_never_raised(self):
        client = _docker()
        client.networks.create.side_effect = RuntimeError("daemon said no")
        state, _helper = _reconcile(client, "auto")
        assert state["fence"]["state"] == "failed" and "daemon said no" in state["fence"]["error"]

    def test_stopped_earners_are_listed_apart(self):
        """The switch redeploys earners_outside, and a redeploy starts the container."""
        earners = [_container("cashpilot-earnapp"), _container("cashpilot-storj", status="exited")]
        state, _helper = _reconcile(_docker(earners=earners), "auto")
        assert state["mode"] == "legacy"
        assert state["earners_outside"] == ["earnapp"] and state["earners_outside_stopped"] == ["storj"]
        state, _helper = _reconcile(_docker(_network(), earners=earners), "auto")
        assert state["earners_outside"] == ["earnapp"] and state["earners_outside_stopped"] == ["storj"]


def _orphan(name, network_id, status="exited", error=""):
    c = _container(name, lan_fence.NETWORK_NAME, (lan_fence.NETWORK_NAME,), status=status)
    c.attrs["NetworkSettings"]["Networks"][lan_fence.NETWORK_NAME] = {"NetworkID": network_id}
    c.attrs["State"] = {"Status": status, "Error": error}
    return c


class TestReattach:
    """Unraid removes user-defined networks when Docker starts; earners keep the old ID."""

    GONE = "failed to set up container networking: network 0cf2f7961ba2 not found"

    def test_an_earner_the_missing_network_stopped_is_moved_and_started(self):
        net = _network()
        c = _orphan("cashpilot-honeygain", "old-id", error=self.GONE)
        assert lan_fence.reattach(_docker(net, earners=[c]), net) == ["cashpilot-honeygain"]
        net.disconnect.assert_called_once_with(c, force=True)
        net.connect.assert_called_once_with(c)
        c.start.assert_called_once()

    def test_one_the_owner_stopped_is_moved_but_left_stopped(self):
        net = _network()
        c = _orphan("cashpilot-storj", "old-id")
        assert lan_fence.reattach(_docker(net, earners=[c]), net) == ["cashpilot-storj"]
        net.connect.assert_called_once_with(c)
        c.start.assert_not_called()

    @pytest.mark.parametrize(
        ("network_id", "status"), [("net-cashpilot-isolated", "exited"), ("", "created"), ("old-id", "running")]
    )
    def test_earners_on_the_current_network_are_not_touched(self, network_id, status):
        """A never-started container has no NetworkID yet and resolves by name."""
        net = _network()
        c = _orphan("cashpilot-honeygain", network_id, status=status, error=self.GONE)
        assert lan_fence.reattach(_docker(net, earners=[c]), net) == []
        net.disconnect.assert_not_called()
        c.start.assert_not_called()

    def test_one_failure_does_not_stop_the_rest(self):
        net = _network()
        a = _orphan("cashpilot-a", "old-id", error=self.GONE)
        b = _orphan("cashpilot-b", "old-id", error=self.GONE)
        net.connect.side_effect = [RuntimeError("nope"), None]
        assert lan_fence.reattach(_docker(net, earners=[a, b]), net) == ["cashpilot-b"]

    def test_every_apply_reattaches_after_writing_the_table(self):
        """The recreated network is what reconcile sees after a reboot; the earners come back behind the fence."""
        c = _orphan("cashpilot-honeygain", "old-id", error=self.GONE)
        client = _docker(earners=[c])
        order = []
        c.start.side_effect = lambda: order.append("start")
        state, helper = _reconcile(client, "auto", on_helper=lambda: order.append("helper"))
        net = client._nets[lan_fence.NETWORK_NAME]
        net.connect.assert_called_once_with(c)
        assert order == ["helper", "start"]
        assert state["fence"]["state"] == "applied"

    def test_a_failed_apply_starts_no_earner(self):
        c = _orphan("cashpilot-honeygain", "old-id", error=self.GONE)
        client = _docker(earners=[c])
        state, _helper = _reconcile(client, "auto", result={"ok": False, "error": "nft: no"})
        c.start.assert_not_called()
        assert state["fence"]["state"] == "failed"


class TestTheMixedReboot:
    """An upgraded install switched over, with a stopped earner left on the default bridge, after Unraid's reboot."""

    def _client(self):
        fenced = _orphan("cashpilot-honeygain", "old-id", error=TestReattach.GONE)
        stopped = _container("cashpilot-storj", status="exited")
        return _docker(earners=[fenced, stopped]), fenced

    def test_reconcile_recreates_the_network_and_brings_the_earner_back(self):
        client, fenced = self._client()
        state, _helper = _reconcile(client, "auto")
        assert state["mode"] == "on" and state["network"] == lan_fence.NETWORK_NAME
        assert state["fence"]["state"] == "applied"
        client._nets[lan_fence.NETWORK_NAME].connect.assert_called_once_with(fenced)
        fenced.start.assert_called_once()
        assert state["earners_outside_stopped"] == ["storj"]

    def test_the_next_deploy_lands_behind_the_fence(self):
        client, _fenced = self._client()
        kwargs, _helper = _deploy(client, "auto")
        assert kwargs["network"] == lan_fence.NETWORK_NAME


@patch.object(lan_fence, "_egress", {"ip": None})
def test_the_helper_gets_the_egress_ip():
    lan_fence.set_egress_ip("81.61.1.9")
    client = MagicMock()
    helper = client.containers.create.return_value
    helper.wait.return_value = {"StatusCode": 0}
    helper.logs.return_value = b'{"ok": true}'
    client.containers.get.side_effect = NotFound("gone")
    with patch.object(lan_fence, "_helper_image", return_value="img"):
        lan_fence.run_helper(client, "apply", "172.18.0.0/16")
    assert client.containers.create.call_args.kwargs["environment"]["FENCE_EGRESS"] == "81.61.1.9"
    lan_fence.set_egress_ip("10.0.0.1")
    assert lan_fence._egress["ip"] == "81.61.1.9", "a LAN answer is a failed lookup: never dropped, the last IP kept"


# ---------------------------------------------------------------------------
# The switch: worker route, UI route, fleet page
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _noop_lifespan(a):
    yield


def _worker_client():
    worker_api.app.router.lifespan_context = _noop_lifespan
    return TestClient(worker_api.app, raise_server_exceptions=False)


class TestTheWorkerRoute:
    def _post(self, body, key=None, **patches):
        headers = {"Authorization": f"Bearer {key or worker_api.API_KEY}"}
        with (
            patch.object(worker_api, "_worker_key", None),
            patch.object(worker_api, "API_KEY", "shared-key"),
            patch.object(lan_fence, "enable", **patches) as enable,
        ):
            headers["Authorization"] = f"Bearer {key or 'shared-key'}"
            return _worker_client().post("/api/isolation", json=body, headers=headers), enable

    def test_it_needs_the_fleet_key(self):
        resp, enable = self._post({"enable": True}, key="nope", return_value={})
        assert resp.status_code == 401
        enable.assert_not_called()

    def test_it_turns_isolation_on(self):
        resp, enable = self._post({"enable": True}, return_value={"mode": "on", "earners_outside": ["earnapp"]})
        assert resp.status_code == 200 and resp.json()["earners_outside"] == ["earnapp"]
        enable.assert_called_once()

    @pytest.mark.parametrize("body", [{"enable": False}, {}, ["enable"]])
    def test_it_never_turns_it_off(self, body):
        resp, enable = self._post(body, return_value={})
        assert resp.status_code == 400 and "CASHPILOT_ISOLATION=off" in resp.json()["detail"]
        enable.assert_not_called()

    def test_a_conflict_says_how_to_fix_it(self):
        resp, _ = self._post({"enable": True}, side_effect=lan_fence.IsolationConflict("set this or that"))
        assert resp.status_code == 409 and resp.json()["detail"] == "set this or that"


class TestOutsideAndHelperOwnership:
    def test_an_earner_on_our_network_and_another_is_outside(self):
        both = _container("cashpilot-repocket", lan_fence.NETWORK_NAME, (lan_fence.NETWORK_NAME, "lan"))
        only = _container("cashpilot-honeygain", lan_fence.NETWORK_NAME, (lan_fence.NETWORK_NAME,))
        found = lan_fence._outside_containers(_docker(_network(), earners=[both, only]), lan_fence.NETWORK_NAME)
        assert [c.name for c in found] == ["cashpilot-repocket"]

    def test_a_foreign_container_by_the_helpers_name_is_left_alone(self):
        foreign = MagicMock(labels={})
        client = MagicMock()
        client.containers.get.return_value = foreign
        lan_fence._clear_helper(client)
        foreign.remove.assert_not_called()
        ours = _helper_container("exited", finished=_ago(3600))
        client.containers.get.return_value = ours
        lan_fence._clear_helper(client)
        ours.remove.assert_called_once_with(force=True, v=True)


def _ago(seconds):
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat().replace("+00:00", "123Z")


def _helper_container(status, created=None, finished="0001-01-01T00:00:00Z"):
    c = MagicMock(labels={lan_fence.PROBE_LABEL: "fence"})
    c.attrs = {
        "Created": created or _ago(3600),
        "State": {"Status": status, "Running": status == "running", "Restarting": False, "FinishedAt": finished},
    }
    return c


def _run_helper(client):
    mine = client.containers.create.return_value
    mine.wait.return_value = {"StatusCode": 0}
    mine.logs.return_value = b'{"ok": true}'
    with patch.object(lan_fence, "_helper_image", return_value="img"), patch.object(lan_fence, "HELPER_POLL", 0):
        return lan_fence.run_helper(client, "apply", "172.18.0.0/16"), mine


class TestAnotherProcesssHelper:
    """The Desktop app runs the same helper, by the same name and label, on a host that can run both."""

    @pytest.mark.parametrize(
        "theirs",
        [
            pytest.param(lambda: _helper_container("running"), id="running"),
            pytest.param(lambda: _helper_container("created", created=_ago(1)), id="just-created"),
            pytest.param(lambda: _helper_container("exited", finished=_ago(1)), id="just-exited"),
        ],
    )
    def test_a_helper_still_in_use_is_waited_for_never_killed(self, theirs):
        other = theirs()
        client = MagicMock()
        client.containers.get.side_effect = [other, other, NotFound("gone")]
        result, mine = _run_helper(client)
        assert result == {"ok": True}
        other.remove.assert_not_called()
        assert client.containers.get.call_count == 3, "it looked again until the other side removed it"
        client.containers.create.assert_called_once()
        mine.remove.assert_called_once_with(force=True, v=True)

    def test_a_leftover_is_removed(self):
        stale = _helper_container("exited", finished=_ago(3600))
        client = MagicMock()
        client.containers.get.return_value = stale
        _run_helper(client)
        stale.remove.assert_called_once_with(force=True, v=True)

    def test_one_still_there_after_the_helper_timeout_is_removed(self):
        stuck = _helper_container("running")
        client = MagicMock()
        client.containers.get.return_value = stuck
        with patch.object(lan_fence, "HELPER_TIMEOUT", 0), patch.object(lan_fence, "HELPER_GRACE", 0):
            _run_helper(client)
        stuck.remove.assert_called_once_with(force=True, v=True)

    def test_only_its_own_helper_is_removed_afterwards(self):
        """By its own object: a name lookup after the run could find the other side's new helper."""
        client = MagicMock()
        client.containers.get.side_effect = NotFound("gone")
        _, mine = _run_helper(client)
        mine.remove.assert_called_once_with(force=True, v=True)
        assert client.containers.get.call_count == 1, "no lookup by name after the run"

    def test_a_name_conflict_from_a_racing_create_is_tried_once_more(self):
        client = MagicMock()
        client.containers.get.side_effect = NotFound("gone")
        mine = client.containers.create.return_value
        response = MagicMock(status_code=409)
        client.containers.create.side_effect = [APIError("Conflict", response=response), mine]
        result, _ = _run_helper(client)
        assert result == {"ok": True}
        assert client.containers.create.call_count == 2

    def test_a_helper_that_never_started_leaves_nothing_to_remove(self):
        client = MagicMock()
        client.containers.get.side_effect = NotFound("gone")
        client.containers.create.side_effect = APIError("boom", response=MagicMock(status_code=500))
        with pytest.raises(APIError):
            _run_helper(client)
        assert client.containers.create.call_count == 1

    def test_a_helper_that_fails_to_start_is_removed_by_its_id(self):
        client = MagicMock()
        client.containers.get.side_effect = NotFound("gone")
        mine = client.containers.create.return_value
        mine.start.side_effect = APIError("no such image layer", response=MagicMock(status_code=500))
        with pytest.raises(APIError):
            _run_helper(client)
        mine.remove.assert_called_once_with(force=True, v=True)

    def test_a_missing_image_is_pulled_once(self):
        client = MagicMock()
        client.containers.get.side_effect = NotFound("gone")
        mine = client.containers.create.return_value
        client.containers.create.side_effect = [ImageNotFound("img"), mine]
        result, _ = _run_helper(client)
        assert result == {"ok": True}
        client.images.pull.assert_called_once_with("img")


class TestEnable:
    def test_off_setting_is_refused(self):
        with (
            patch.object(lan_fence, "_SETTING", "off"),
            patch.object(orchestrator, "_CONTAINER_NETWORK", ""),
            pytest.raises(lan_fence.IsolationConflict, match="CASHPILOT_ISOLATION=off"),
        ):
            lan_fence.enable()

    def test_operator_network_is_refused(self):
        with (
            patch.object(orchestrator, "_CONTAINER_NETWORK", "mine"),
            pytest.raises(lan_fence.IsolationConflict, match="CASHPILOT_CONTAINER_NETWORK=mine"),
        ):
            lan_fence.enable()

    def test_it_returns_the_earners_to_move(self):
        client = _docker(earners=[_container("cashpilot-earnapp"), _container("cashpilot-mysterium", "host")])
        with (
            patch.object(lan_fence, "_SETTING", "auto"),
            patch.object(orchestrator, "_CONTAINER_NETWORK", ""),
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(lan_fence, "run_helper", return_value={"ok": True, "backend": "nft"}),
        ):
            state = lan_fence.enable()
        assert state["mode"] == "on" and state["earners_outside"] == ["earnapp"]
        assert lan_fence.NETWORK_NAME in client._nets


class TestTheUiRoute:
    def test_owner_only(self):
        ui_app.router.lifespan_context = _noop_lifespan
        with (
            patch("app.main.auth.get_current_user", return_value={"uid": 2, "u": "w", "r": "writer"}),
            patch("app.main._proxy_to_worker", new_callable=AsyncMock) as proxy,
        ):
            resp = TestClient(ui_app, raise_server_exceptions=False).post("/api/workers/1/isolation")
        assert resp.status_code in (401, 403)
        proxy.assert_not_called()

    def test_it_proxies_enable_only(self):
        ui_app.router.lifespan_context = _noop_lifespan
        with (
            patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "admin", "r": "owner"}),
            patch("app.main._proxy_to_worker", new_callable=AsyncMock, return_value={"mode": "on"}) as proxy,
        ):
            resp = TestClient(ui_app, raise_server_exceptions=False).post("/api/workers/1/isolation")
        assert resp.status_code == 200
        assert proxy.call_args.args == (1, "POST", "/api/isolation")
        assert proxy.call_args.kwargs["json"] == {"enable": True}

    def test_not_a_get(self):
        ui_app.router.lifespan_context = _noop_lifespan
        with patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "admin", "r": "owner"}):
            resp = TestClient(ui_app, raise_server_exceptions=False).get("/api/workers/1/isolation")
        assert resp.status_code == 405


@pytest.mark.parametrize(("docker_ok", "offered"), [(True, True), (False, False)])
def test_the_heartbeat_carries_the_isolation_state(docker_ok, offered):
    sent = {}
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    async def post(url, json=None, **kw):
        sent.update(json or {})
        raise RuntimeError("stop after the payload")

    client.post = post
    lan_fence._state.update(mode="legacy", earners_outside=["earnapp"])
    with (
        patch.object(worker_api, "_detect_egress_ip", AsyncMock(return_value="81.61.1.9")),
        patch.object(worker_api, "_worker_key", "own"),
        patch.object(worker_api, "UI_URL", "http://ui:8080"),
        patch("app.worker_api.orchestrator.get_status", return_value=[]),
        patch("app.worker_api.orchestrator.docker_available", return_value=docker_ok),
        patch("app.worker_api.httpx.AsyncClient", return_value=client),
        patch.object(lan_fence, "run_helper") as helper,
        patch.object(lan_fence, "_egress", {"ip": None}),
        patch.object(worker_api, "_check_fence", AsyncMock()) as check,
    ):
        asyncio.run(worker_api._send_heartbeat())
        egress_after = lan_fence._egress["ip"]
    # A new public IP is fenced at once, where there is a Docker to fence it on.
    assert check.await_count == (1 if docker_ok else 0)
    info = sent["system_info"]
    assert ("isolation_default" in info["features"]) is offered
    assert info["isolation"]["mode"] == "legacy" and info["isolation"]["earners_outside"] == ["earnapp"]
    helper.assert_not_called()
    assert info["egress_ip"] == "81.61.1.9"
    assert egress_after == "81.61.1.9", "the next fence apply drops the home's public IP"


def test_the_same_public_ip_triggers_no_extra_check():
    with patch.object(lan_fence, "_egress", {"ip": None}):
        assert lan_fence.set_egress_ip("81.61.1.9") is True
        assert lan_fence.set_egress_ip("81.61.1.9") is False
        assert lan_fence.set_egress_ip(None) is False and lan_fence._egress["ip"] == "81.61.1.9", (
            "a failed lookup keeps dropping the last known address"
        )
        assert lan_fence.set_egress_ip("192.168.1.1") is False and lan_fence._egress["ip"] == "81.61.1.9"
        assert lan_fence.set_egress_ip("81.61.1.10") is True and lan_fence._egress["ip"] == "81.61.1.10"


def test_the_worker_image_ships_the_fence():
    dockerfile = (ROOT / "Dockerfile.worker").read_text()
    assert "COPY --chown=cashpilot:root app/lan_fence.py ./app/" in dockerfile
    apk = next(ln for ln in dockerfile.splitlines() if ln.startswith("RUN apk add") and "su-exec" in ln)
    assert "nftables" in apk.split() and "iptables-legacy" in apk.split()


FENCE_HARNESS = r"""
import fs from 'node:fs';
const html = fs.readFileSync('app/templates/fleet.html', 'utf8');
function extract(name) {
  const start = html.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`fleet.html no longer defines ${name}()`);
  let depth = 0;
  for (let j = html.indexOf('{', start); j < html.length; j++) {
    if (html[j] === '{') depth++;
    else if (html[j] === '}' && --depth === 0) return html.slice(start, j + 1);
  }
  throw new Error(`unbalanced braces reading ${name}()`);
}
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const _isOwner = true;
const _fenceSwitch = {};
const calls = [];
const loadFleet = () => {};
const confirm = () => true;
const failOn = process.argv[process.argv.length - 1];
// "left:<slug>": that service's deploy passes but an instance stays outside.
const leftOn = failOn.startsWith('left:') ? failOn.slice(5) : '';
let isolationCalls = 0;
const CP = {api: async (url, opts) => {
  calls.push([url, opts && opts.method, opts && opts.body]);
  if (url.endsWith('/isolation')) {
    isolationCalls++;
    if (isolationCalls === 1) return {mode: 'on', earners_outside: ['earnapp', 'honeygain', 'storj']};
    if (failOn === 'recount') throw new Error('worker gone');
    return {mode: 'on', earners_outside: [leftOn || failOn].filter(Boolean)};
  }
  if (failOn && !leftOn && failOn !== 'recount' && url.includes(failOn)) throw new Error('worker said no');
  return {status: 'deployed'};
}};
const renderFence = eval('(' + extract('renderFence') + ')');
const enableFence = eval('(async ' + extract('enableFence') + ')');
const feat = ['isolation_default'];
const out = {
  legacy: renderFence({id: 3, name: 'box'}, {features: feat, isolation: {mode: 'legacy', fence: {state: 'n/a'}, earners_outside: ['earnapp']}}),
  failed: renderFence({id: 3, name: 'box'}, {features: feat, isolation: {mode: 'on', fence: {state: 'failed', error: 'no nf_tables'}, earners_outside: []}}),
  quiet: renderFence({id: 3, name: 'box'}, {features: feat, isolation: {mode: 'on', fence: {state: 'applied'}, earners_outside: []}}),
  old: renderFence({id: 3, name: 'box'}, {features: [], isolation: {mode: 'legacy', fence: {}, earners_outside: ['earnapp']}}),
  stopped: renderFence({id: 3, name: 'box'}, {features: feat, isolation: {mode: 'legacy', fence: {state: 'n/a'}, earners_outside: ['earnapp'], earners_outside_stopped: ['storj']}}),
  onlyStopped: renderFence({id: 3, name: 'box'}, {features: feat, isolation: {mode: 'on', fence: {state: 'applied'}, earners_outside: [], earners_outside_stopped: ['storj']}}),
};
await enableFence(3, 'box');
out.calls = calls;
out.after = _fenceSwitch[3];
console.log(JSON.stringify(out));
"""


class TestTheFleetPage:
    def _render(self, fail_on=""):
        node = shutil.which("node")
        if node is None:
            pytest.skip("node is not installed")
        out = subprocess.run(
            [node, "--input-type=module", "-e", FENCE_HARNESS, fail_on],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    def test_a_legacy_worker_offers_the_switch(self):
        out = self._render()
        assert "can reach your LAN and this host: earnapp" in out["legacy"]
        assert "btn-fence-on" in out["legacy"]

    def test_a_worker_too_old_for_the_switch_gets_no_button(self):
        assert "btn-fence-on" not in self._render()["old"]

    def test_a_failed_fence_warns_the_host_is_reachable(self):
        """No promise that the internet is gone: another masquerade on the host can keep it."""
        out = self._render()["failed"]
        assert "no nf_tables" in out and "reach this host" in out and "CASHPILOT_ISOLATION=off" in out
        assert "fails safe" not in out

    def test_a_holding_fence_says_nothing(self):
        assert self._render()["quiet"] == ""

    def test_the_switch_moves_each_earner_in_turn(self):
        out = self._render()
        assert out["calls"][0][:2] == ["/api/workers/3/isolation", "POST"]
        assert [c[0] for c in out["calls"][1:]] == [
            "/api/deploy/earnapp?worker_id=3",
            "/api/deploy/honeygain?worker_id=3",
            "/api/deploy/storj?worker_id=3",
            "/api/workers/3/isolation",
        ]
        assert all(c[2] == {} for c in out["calls"][1:4]), "an empty body redeploys from the recorded spec"
        assert "Moved earnapp, honeygain, storj" in out["after"]["done"]

    def test_an_instance_left_outside_is_not_called_moved(self):
        """A failed scale-down can leave a second instance running that the redeploy does not recreate."""
        out = self._render(fail_on="left:honeygain")
        assert "Moved earnapp, storj." in out["after"]["error"]
        assert "honeygain (an instance is still running outside the isolated network)" in out["after"]["error"]

    def test_a_recount_that_fails_confirms_nothing(self):
        out = self._render(fail_on="recount")
        assert "Moved" not in out["after"]["error"]
        assert "earnapp (redeployed, but the worker could not confirm it moved: worker gone)" in out["after"]["error"]

    def test_one_failure_does_not_stop_the_rest(self):
        """A retired or broken earner would otherwise keep every later one exposed, on every click."""
        out = self._render(fail_on="honeygain")
        assert [c[0] for c in out["calls"][1:4]] == [
            "/api/deploy/earnapp?worker_id=3",
            "/api/deploy/honeygain?worker_id=3",
            "/api/deploy/storj?worker_id=3",
        ]
        assert "Moved earnapp, storj." in out["after"]["error"]
        assert "Could not move: honeygain (worker said no)" in out["after"]["error"]

    def test_stopped_earners_are_named_and_not_moved(self):
        out = self._render()
        assert "Stopped, so left alone: storj" in out["stopped"]
        assert "Stopped, so left alone: storj" in out["onlyStopped"]
        assert "btn-fence-on" not in out["onlyStopped"]


# ---------------------------------------------------------------------------
# The isolation check's counter proof
# ---------------------------------------------------------------------------


class TestCounterProof:
    def _targets(self):
        return isolation_check.fence_targets("172.18.0.1")

    def test_every_range_and_the_host_get_a_sentinel(self):
        targets = self._targets()
        assert {t["label"] for t in targets} == {n for n, _c, _s in lan_fence.BLOCKED} | {lan_fence.HOST_RULE}
        assert next(t for t in targets if t["label"] == "host")["host"] == "172.18.0.1"

    def test_a_counter_that_rose_is_proof(self):
        targets = self._targets()
        before = {"present": True, "matches": True, "backend": "nft", "counters": {t["label"]: 5 for t in targets}}
        after = {"present": True, "matches": True, "backend": "nft", "counters": {t["label"]: 7 for t in targets}}
        fence, findings = isolation_check.judge_fence(targets, before, after)
        assert all(r["proven"] for r in fence["ranges"]) and findings == []
        assert fence["backend"] == "nft" and fence["matches_expected"]

    def test_a_flat_counter_is_a_finding(self):
        targets = self._targets()
        before = {"present": True, "counters": {t["label"]: 5 for t in targets}}
        after = {"present": True, "matches": True, "counters": {t["label"]: 7 for t in targets} | {"cgnat": 5}}
        fence, findings = isolation_check.judge_fence(targets, before, after)
        assert [r["rule"] for r in fence["ranges"] if not r["proven"]] == ["cgnat"]
        assert findings[0]["kind"] == "fence_not_hit" and findings[0]["exposure"]
        assert "100.64.0.0/10" in findings[0]["detail"]

    def test_a_sentinel_that_connected_is_never_proof(self):
        targets = self._targets()
        targets[0]["reachable"] = True
        before = {"present": True, "counters": {t["label"]: 0 for t in targets}}
        after = {"present": True, "matches": True, "counters": {t["label"]: 1 for t in targets}}
        fence, findings = isolation_check.judge_fence(targets, before, after)
        assert not fence["ranges"][0]["proven"] and findings[0]["kind"] == "fence_not_hit"

    def test_a_table_missing_a_rule_is_a_finding_even_when_every_sentinel_passes(self):
        """A connected public subnet's drop has no sentinel; only the name check sees it is gone."""
        targets = self._targets()
        before = {"present": True, "matches": False, "counters": {t["label"]: 5 for t in targets}}
        after = {"present": True, "matches": False, "counters": {t["label"]: 7 for t in targets}}
        fence, findings = isolation_check.judge_fence(targets, before, after)
        assert all(r["proven"] for r in fence["ranges"])
        assert [f["kind"] for f in findings] == ["fence_incomplete"] and findings[0]["exposure"]

    def test_a_missing_table_is_a_finding(self):
        targets = self._targets()
        _fence, findings = isolation_check.judge_fence(targets, {"present": False}, {"present": False})
        assert findings[0]["kind"] == "fence_missing" and findings[0]["exposure"]

    READ = {
        "present": True,
        "egress": "198.51.100.7",
        "bridge_ipv6": "fe80::a8c1:abff:fe01:203",
        "counters": {"egress-198.51.100.7": 0, "ipv6-host": 0},
    }

    def test_the_public_ip_and_the_ipv6_host_get_targets_when_the_table_has_them(self):
        targets = {t["label"]: t for t in isolation_check.fence_targets("172.18.0.1", self.READ)}
        assert targets["egress-198.51.100.7"]["host"] == "198.51.100.7"
        assert targets["egress-198.51.100.7"]["refused"], "a reset from the router means the connect got out"
        assert targets["ipv6-host"]["host"] == "fe80::a8c1:abff:fe01:203%eth0"
        bare = {t["label"] for t in isolation_check.fence_targets("172.18.0.1", {"present": True, "counters": {}})}
        assert "ipv6-host" not in bare and not any(n.startswith("egress-") for n in bare)

    def _judge(self, rise, reachable_label=None):
        targets = isolation_check.fence_targets("172.18.0.1", self.READ)
        for t in targets:
            t["reachable"] = t["label"] == reachable_label
        names = {t["label"] for t in targets}
        before = {"present": True, "counters": dict.fromkeys(names, 0)}
        after = {"present": True, "matches": True, "counters": {n: (1 if n in rise else 0) for n in names}}
        return isolation_check.judge_fence(targets, before, after)

    def test_a_flat_egress_counter_is_a_finding(self):
        everything = {n for n, _c, _s in lan_fence.BLOCKED} | {"host"}
        _fence, findings = self._judge(everything)
        assert findings and "this home's public IP" in findings[0]["detail"]

    def test_an_earner_without_ipv6_is_no_finding(self):
        """It sends nothing, so the ipv6-host counter stays flat; that is not a gap."""
        everything = {n for n, _c, _s in lan_fence.BLOCKED} | {"host", "egress-198.51.100.7"}
        fence, findings = self._judge(everything)
        assert findings == []
        assert not next(r for r in fence["ranges"] if r["rule"] == "ipv6-host")["proven"]

    def test_an_earner_that_reaches_the_host_over_ipv6_is_exposed(self):
        everything = {n for n, _c, _s in lan_fence.BLOCKED} | {"host", "egress-198.51.100.7"}
        _fence, findings = self._judge(everything, reachable_label="ipv6-host")
        assert findings[0]["kind"] == "fence_not_hit" and "[fe80::a8c1:abff:fe01:203%eth0]:9" in findings[0]["detail"]


def _probe_reach():
    ns = {"__name__": "probe"}
    exec(isolation_check.PROBE_SCRIPT, ns)  # noqa: S102 - our own probe script, run as the probe would
    return ns["reach"]


def test_a_reset_counts_as_reaching_only_for_a_fence_sentinel():
    """With the drop gone, a closed port on the target answers with a reset: the packet got there."""
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    reach = _probe_reach()
    assert reach({"host": "127.0.0.1", "port": port, "refused": True}) is True
    assert reach({"host": "127.0.0.1", "port": port}) is False


class TestTheCheckInOnMode:
    """_run end to end with fake probes: proven with nothing on the LAN answering."""

    def _run(self, rise=True):
        earner = _container("cashpilot-honeygain", nets=(lan_fence.NETWORK_NAME,))
        earner.id = "e1"
        earner.attrs["NetworkSettings"]["Networks"][lan_fence.NETWORK_NAME] = {"Gateway": "172.18.0.1"}
        client = _docker(_network(), earners=[earner])
        reads = iter(
            [
                {
                    "present": True,
                    "matches": True,
                    "backend": "nft",
                    "counters": dict.fromkeys(lan_fence.rule_names("172.18.0.0/16"), 0),
                },
                {
                    "present": True,
                    "matches": True,
                    "backend": "nft",
                    "counters": dict.fromkeys(lan_fence.rule_names("172.18.0.0/16"), 1 if rise else 0),
                },
            ]
        )

        def probe(client, image, name, mode, **kw):
            if mode == "discover":
                # Nothing on the host answers (Docker Desktop, colima).
                return {"candidates": [{"group": "lan", "host": "192.168.65.1", "port": 80, "ok": False}]}
            return {"results": [False] * (len(kw["targets"]) - 1) + [True]}

        with (
            patch.object(lan_fence, "_SETTING", "auto"),
            patch.object(orchestrator, "_CONTAINER_NETWORK", ""),
            patch.object(isolation_check, "_self_image", return_value="img"),
            patch.object(isolation_check, "run_probe", side_effect=probe),
            patch.object(isolation_check, "read_node_firewall", return_value=None),
            patch.object(lan_fence, "read_fence", side_effect=lambda c: next(reads)),
            patch.object(isolation_check, "dashboard_targets", return_value=[]),
        ):
            return isolation_check._run(client)

    def test_proven_ranges_make_it_isolated_without_a_live_target(self):
        report = self._run()
        assert report["status"] == "isolated", report
        assert report["mode"] == "on" and all(r["proven"] for r in report["fence"]["ranges"])

    def test_unproven_ranges_make_it_exposed(self):
        report = self._run(rise=False)
        assert report["status"] == "exposed"
        assert any(f["kind"] == "fence_not_hit" for f in report["findings"])


class TestDashboardTarget:
    def test_the_ui_address_becomes_a_target(self):
        with patch("app.isolation_check.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("192.168.1.20", 8080))]):
            got = isolation_check.dashboard_targets("http://cashpilot-ui:8080")
        assert got == [
            {"group": "lan", "host": "192.168.1.20", "port": 8080, "label": "CashPilot dashboard", "via": "dashboard"}
        ]

    def test_a_tailnet_ui_is_an_overlay_target(self):
        with patch("app.isolation_check.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("100.70.1.2", 443))]):
            got = isolation_check.dashboard_targets("https://ui.example.ts.net")
        assert got[0]["group"] == "overlay" and got[0]["port"] == 443

    @pytest.mark.parametrize("url", ["", "http://127.0.0.1:8080", "not a url"])
    def test_nothing_useful_no_target(self, url):
        with patch("app.isolation_check.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 8080))]):
            assert isolation_check.dashboard_targets(url) == []

    def test_the_dashboard_keeps_its_own_slot_beside_the_hosts_ssh(self):
        kept = isolation_check._keep(
            [
                {"group": "host", "host": "192.168.1.20", "port": 22, "label": "ssh", "via": "host", "ok": True},
                {
                    "group": "lan",
                    "host": "192.168.1.20",
                    "port": 8080,
                    "label": "CashPilot dashboard",
                    "via": "dashboard",
                    "ok": True,
                },
            ]
        )
        assert {t["port"] for t in kept} == {22, 8080}


@pytest.mark.parametrize(("docker_ok", "looked_up"), [(True, True), (False, False)])
def test_the_first_table_already_drops_the_public_ip(docker_ok, looked_up):
    """NAT loopback has no window at startup: the address is known before the first apply."""
    seen = {}

    async def check(startup=False):
        seen["egress_at_check"] = lan_fence._egress["ip"]

    async def run():
        async with worker_api.lifespan(worker_api.app):
            pass

    with (
        patch.object(lan_fence, "_egress", {"ip": None}),
        patch("app.worker_api.orchestrator.docker_available", return_value=docker_ok),
        patch.object(worker_api, "_detect_egress_ip", AsyncMock(return_value="81.61.1.9")) as detect,
        patch.object(worker_api, "_check_fence", side_effect=check),
        patch.object(worker_api, "_fence_loop", AsyncMock()),
        patch.object(worker_api, "UI_URL", ""),
    ):
        asyncio.run(run())
    assert detect.await_count == (1 if looked_up else 0)
    assert seen["egress_at_check"] == ("81.61.1.9" if looked_up else None)
