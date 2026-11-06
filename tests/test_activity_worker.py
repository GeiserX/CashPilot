"""app/activity.py and its worker_api wiring, with a fake Docker client.

Nothing here talks to Docker; the probe's behaviour against a real kernel is
proven by the read-only smoke run named in the PR.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from docker.errors import NotFound

from app import activity, procnet

GOOD = {
    "v": 1,
    "netns": "net:[4026532000]",
    "snmp_start": None,
    "snmp_end": {
        "tcp": {"ActiveOpens": 100, "PassiveOpens": 5, "AttemptFails": 2, "EstabResets": 1, "CurrEstab": 3},
        "udp": {"InDatagrams": 10, "OutDatagrams": 20},
    },
    "summary": {
        "est_max": 3,
        "syn_sent_max": 1,
        "udp_bound": 0,
        "listen_ports": [8080],
        "remotes_total": 2,
        "truncated": False,
        "out": [["tcp", "198.51.100.9", 443, 5, {"est": 5}], ["tcp", "192.168.1.10", 22, 1, {"syn_sent": 1}]],
        "in": [["203.0.113.7", 8080, 2]],
    },
    "files": {"tcp": True},
    "malformed": 0,
    "snapshots": 5,
}


HOST_GOOD = {
    "v": 1,
    "attribution": "cgroup",
    "reason": "",
    "netns": None,
    "snmp_start": None,
    "snmp_end": None,
    "summary": {
        "est_max": 2,
        "syn_sent_max": 0,
        "udp_bound": 1,
        "listen_ports": [4449],
        "remotes_total": 3,
        "truncated": False,
        "out": [
            ["tcp", "198.51.100.9", 443, 5, {"est": 5}],
            ["tcp", "198.51.100.25", 25, 1, {"closed": 1}],
            ["udp", "192.168.1.1", 5351, 1, {"est": 1}],
        ],
        "in": [["203.0.113.7", 4449, 2]],
    },
    "snapshots": 5,
}


class Probe:
    def __init__(self, name, status=0, logs=None, wait_exc=None, remove_exc=None, attrs=None):
        self.name = name
        if attrs is not None:
            self.attrs = attrs
        self.status = status
        self._logs = json.dumps(GOOD).encode() if logs is None else logs
        self.wait_exc = wait_exc
        self.remove_exc = remove_exc
        self.removed = []

    def wait(self, timeout=None):
        if self.wait_exc:
            raise self.wait_exc
        return {"StatusCode": self.status}

    def logs(self, stdout=True, stderr=False):
        return self._logs

    def remove(self, force=False, v=False):
        self.removed.append((force, v))
        if self.remove_exc:
            raise self.remove_exc


def earner(name, cid, mode="bridge", runtime="", labels=None, nets=None):
    nets = (
        nets
        if nets is not None
        else {"cp": {"NetworkID": "n1", "Gateway": "172.18.0.1", "IPAddress": "172.18.0.5", "IPPrefixLen": 16}}
    )
    return SimpleNamespace(
        name=name,
        id=cid,
        attrs={
            "HostConfig": {"NetworkMode": mode, "Runtime": runtime},
            "Config": {"Labels": labels or {}},
            "NetworkSettings": {"Networks": nets},
        },
    )


class FakeClient:
    def __init__(self, earners, probe_factory=None, leftovers=()):
        self.by_key = {}
        for c in earners:
            self.by_key[c.name] = c
            self.by_key[c.id] = c
        self.me = SimpleNamespace(name="cashpilot-worker", id="self" * 16, attrs={"Image": "sha256:worker"})
        self.runs = []
        self.probes = []
        self.listed_leftovers = [Probe(n) for n in leftovers]
        self.probe_factory = probe_factory or (lambda kw: Probe(kw["name"]))
        self.containers = SimpleNamespace(get=self._get, list=self._list, run=self._run)
        self.networks = SimpleNamespace(get=lambda nid: SimpleNamespace(attrs={"Driver": "bridge"}))
        self.closed = False
        self.runtimes = {
            "runc": {"path": "runc"},
            "runsc": {"path": "/usr/local/bin/runsc"},
            "runsc-hostnet": {"path": "/usr/local/bin/runsc", "runtimeArgs": ["--network=host"]},
        }

    def info(self):
        return {"Runtimes": self.runtimes}

    def _get(self, key):
        if key in self.by_key:
            return self.by_key[key]
        raise NotFound("gone")

    def _list(self, all=False, filters=None):
        assert filters == {"label": "cashpilot.probe=activity"}
        return self.listed_leftovers

    def _run(self, **kw):
        self.runs.append(kw)
        p = self.probe_factory(kw)
        self.probes.append(p)
        return p

    def close(self):
        self.closed = True


WORKER = "worker-one"


def _stamp(offset_s):
    """A Docker timestamp (RFC 3339 in UTC, nanoseconds) offset_s seconds from now."""
    t = datetime.now(UTC) + timedelta(seconds=offset_s)
    return t.strftime("%Y-%m-%dT%H:%M:%S.%f") + "123Z"


TAG = hashlib.sha256(WORKER.encode()).hexdigest()[:8]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    activity.reset()
    monkeypatch.setattr(activity, "WORKER_ID", WORKER)
    yield
    activity.reset()


def _status(*names):
    return [{"name": n, "status": "running"} for n in names]


def _round(client, names, now=1_000_000.0):
    with (
        patch("app.activity._client", return_value=client),
        patch("app.activity.orchestrator.get_status_cached", return_value=_status(*names)),
        patch("app.activity.orchestrator._self_container", return_value=client.me),
    ):
        return activity.run_round(now=now)


class TestProbeKwargs:
    def test_exact_run_kwargs(self):
        kw = activity.probe_kwargs("sha256:img", "abcdef0123456789xyz")
        assert kw == {
            "image": "sha256:img",
            "name": f"cashpilot-activity-probe-{TAG}-abcdef012345",
            "entrypoint": ["python", "-c", activity.ACTIVITY_SCRIPT],
            "environment": {"PROBE_SNAPSHOTS": "5", "PROBE_GAP": "2"},
            "network_mode": "container:abcdef0123456789xyz",
            "user": "65534:65534",
            "read_only": True,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "privileged": False,
            "pids_limit": 32,
            "mem_limit": "48m",
            "tmpfs": {"/data": "size=64k"},
            "healthcheck": {"test": ["NONE"]},
            "log_config": {"type": "json-file", "config": {"max-size": "1m"}},
            "labels": {"cashpilot.probe": "activity", "cashpilot.probe.worker": WORKER},
            "detach": True,
        }

    def test_script_is_procnet_and_runs_main(self):
        assert "def main():" in activity.ACTIVITY_SCRIPT
        assert 'if __name__ == "__main__":' in activity.ACTIVITY_SCRIPT


class TestRemovalOnEveryPath:
    def _run(self, probe):
        client = FakeClient([], probe_factory=lambda kw: probe)
        left = []
        try:
            return activity.run_probe(client, "img", "a" * 64, left), probe, left
        except activity.ProbeFailed as exc:
            return exc.reason, probe, left

    def test_success(self):
        data, probe, left = self._run(Probe("p"))
        assert data["v"] == 1
        assert probe.removed == [(True, True)] and left == []

    def test_non_zero_exit(self):
        reason, probe, _ = self._run(Probe("p", status=1))
        assert reason == "exit_nonzero" and probe.removed == [(True, True)]

    def test_timeout(self):
        class ReadTimeout(Exception):
            pass

        reason, probe, _ = self._run(Probe("p", wait_exc=ReadTimeout()))
        assert reason == "timeout" and probe.removed == [(True, True)]

    def test_bad_output(self):
        reason, probe, _ = self._run(Probe("p", logs=b"not json"))
        assert reason == "bad_output" and probe.removed == [(True, True)]

    def test_run_exception_removes_by_name(self):
        stuck = Probe(activity.probe_name("a" * 64))
        client = FakeClient([])
        client.by_key[stuck.name] = stuck

        def boom(**kw):
            raise RuntimeError("daemon said no")

        client.containers.run = boom
        left = []
        with pytest.raises(activity.ProbeFailed) as exc:
            activity.run_probe(client, "img", "a" * 64, left)
        assert exc.value.reason == "run_error"
        # Once before the run (a stale copy), once after the failure.
        assert stuck.removed == [(True, True), (True, True)]

    def test_leftover_reported(self):
        _, _, left = self._run(Probe("p", remove_exc=RuntimeError("busy")))
        assert left == [f"cashpilot-activity-probe-{TAG}-aaaaaaaaaaaa"]


class TestRound:
    def test_label_sweep_removes_old_probes(self):
        client = FakeClient([])
        client.listed_leftovers = [
            Probe(
                "ours", attrs={"Config": {"Labels": {"cashpilot.probe.worker": WORKER}}, "State": {"Status": "running"}}
            ),
            Probe("legacy-done", attrs={"Config": {"Labels": {}}, "State": {"Status": "exited"}}),
        ]
        window = _round(client, [])
        assert [p.removed for p in client.listed_leftovers] == [[(True, True)], [(True, True)]]
        assert window["leftover_probes"] == []

    def test_none_and_sandboxed_never_probe(self):
        client = FakeClient(
            [
                earner("cashpilot-off", "n" * 64, mode="none"),
                earner("cashpilot-gv", "g" * 64, runtime="runsc"),
            ]
        )
        window = _round(client, ["cashpilot-off", "cashpilot-gv"])
        assert client.runs == []
        got = {s["container"]: s["status"] for s in window["samples"]}
        assert got == {"cashpilot-off": "no_network", "cashpilot-gv": "sandboxed"}

    def test_a_chain_ending_on_the_host_network_is_matched_by_the_members_cgroup(self):
        """An earner joining a container that joins a host-network one is on the host network."""
        client = FakeClient(
            [
                earner("hostgw", "h" * 64, mode="host"),
                earner("relay", "r" * 64, mode="container:hostgw"),
                earner("cashpilot-a", "a" * 64, mode="container:relay"),
            ],
            probe_factory=lambda kw: Probe(kw["name"], logs=json.dumps(HOST_GOOD).encode()),
        )
        window = _round(client, ["cashpilot-a"])
        assert [(r["network_mode"], r["environment"].get("PROBE_CONTAINER")) for r in client.runs] == [
            ("host", "a" * 64)
        ]
        assert [(s["container"], s["status"], s["reason"]) for s in window["samples"]] == [
            ("cashpilot-a", "ok", "host_cgroup")
        ]

    def test_gvisor_hostnet_is_probed_and_gvisor_netstack_is_sandboxed(self):
        """A gVisor runtime with --network=host keeps its sockets in the kernel's namespace."""
        client = FakeClient(
            [earner("cashpilot-a", "a" * 64, runtime="runsc-hostnet"), earner("cashpilot-b", "b" * 64, runtime="runsc")]
        )
        window = _round(client, ["cashpilot-a", "cashpilot-b"])
        assert [r["network_mode"] for r in client.runs] == [f"container:{'a' * 64}"]
        assert {s["container"]: s["status"] for s in window["samples"]} == {
            "cashpilot-a": "ok",
            "cashpilot-b": "sandboxed",
        }

    def test_joinable_runtimes(self):
        client = FakeClient([])
        client.runtimes["my-crun"] = {"path": "/usr/bin/crun"}
        client.runtimes["kata"] = {"path": "/usr/bin/kata-runtime"}
        got = activity.joinable_runtimes(client)
        assert {"runc", "runsc-hostnet", "my-crun", "io.containerd.runc.v2"} <= got
        assert "runsc" not in got and "kata" not in got

    def test_joinable_runtimes_without_info_is_the_plain_list(self):
        client = FakeClient([])

        def boom():
            raise RuntimeError("no info")

        client.info = boom
        assert activity.joinable_runtimes(client) == set(activity.PLAIN_RUNTIMES)

    def test_bridge_earner_is_probed_and_classified(self):
        client = FakeClient([earner("cashpilot-honeygain", "b" * 64)])
        window = _round(client, ["cashpilot-honeygain"])
        assert len(client.runs) == 1
        s = window["samples"][0]
        assert s["status"] == "ok" and s["est_max"] == 3
        assert s["out"][0] == ["tcp", "198.51.100.9", 443, "public", 5, {"est": 5}]
        assert s["out"][1][3] == "lan"
        assert s["in"] == [["203.0.113.7", 8080, "public", 2]]
        assert s["opens"] is None  # first round: no previous counters

    def test_shared_netns_gets_one_probe_and_members(self):
        gw = earner("gluetun", "g" * 64)
        a = earner("cashpilot-a", "a" * 64, mode="container:gluetun")
        b = earner("cashpilot-b", "c" * 64, mode=f"container:{'g' * 64}")
        client = FakeClient([gw, a, b])
        window = _round(client, ["cashpilot-a", "cashpilot-b"])
        assert len(client.runs) == 1
        assert client.runs[0]["network_mode"] == f"container:{'g' * 64}"
        s = window["samples"][0]
        assert s["container"] == "gluetun" and s["members"] == ["cashpilot-a", "cashpilot-b"]

    def test_self_and_probes_are_never_sampled(self):
        client = FakeClient(
            [earner("cashpilot-x", "x" * 64, labels={"cashpilot.probe": "activity"}), earner("cashpilot-ui", "u" * 64)]
        )
        window = _round(client, ["cashpilot-x", "cashpilot-ui"])
        assert client.runs == [] and window["samples"] == []

    def test_no_self_image(self):
        client = FakeClient([earner("cashpilot-a", "a" * 64)])
        client.me = None
        window = _round(client, ["cashpilot-a"])
        assert window["worker_status"] == "no_image" and client.runs == []

    def test_budget_stops_further_probes(self):
        client = FakeClient([earner(f"cashpilot-{i}", f"{i}" * 64) for i in range(6)])
        with patch.object(activity, "ROUND_BUDGET", -1):
            window = _round(client, [f"cashpilot-{i}" for i in range(6)])
        assert client.runs == []
        assert {s["status"] for s in window["samples"]} == {"skipped_budget"}

    def test_busy_lock_skips_the_round(self):
        client = FakeClient([earner("cashpilot-a", "a" * 64)])
        activity._lock.acquire()
        try:
            assert _round(client, ["cashpilot-a"]) is None
        finally:
            activity._lock.release()
        assert client.runs == []

    def test_lock_is_separate_from_isolation_check(self):
        from app import isolation_check

        assert activity._lock is not isolation_check._lock
        assert isinstance(activity._lock, type(threading.Lock()))


class TestDeltas:
    def _data(self, netns="net:[1]", opens=100, fails=2):
        d = json.loads(json.dumps(GOOD))
        d["netns"] = netns
        d["snmp_end"]["tcp"]["ActiveOpens"] = opens
        d["snmp_end"]["tcp"]["AttemptFails"] = fails
        return d

    def test_delta_between_rounds(self):
        assert activity.deltas("o", self._data(opens=100), 0.0)["opens"] is None
        d = activity.deltas("o", self._data(opens=160, fails=5), 300.0)
        assert d["opens"] == 60 and d["attempt_fails"] == 3 and d["delta_seconds"] == 300.0
        assert d["udp_in"] == 0

    def test_null_when_netns_changes(self):
        activity.deltas("o", self._data(netns="net:[1]", opens=100), 0.0)
        assert activity.deltas("o", self._data(netns="net:[2]", opens=160), 300.0)["opens"] is None

    def test_null_when_a_counter_goes_backwards(self):
        activity.deltas("o", self._data(opens=100), 0.0)
        assert activity.deltas("o", self._data(opens=50), 300.0)["opens"] is None
        # ...and the new reading is the next baseline.
        assert activity.deltas("o", self._data(opens=70), 600.0)["opens"] == 20

    def test_missing_snmp_is_null(self):
        d = self._data()
        d["snmp_end"] = None
        activity.deltas("o", self._data(), 0.0)
        assert activity.deltas("o", d, 300.0)["opens"] is None


class TestFit:
    def test_cap_keeps_payload_under_128kb(self):
        row = ["tcp", "2001:db8:aaaa:bbbb:cccc:dddd:eeee:ffff", 443, "public", 5, {"est": 3, "syn_sent": 2}]
        samples = []
        for i in range(64):
            s = activity._sample_base(f"cashpilot-{i:02d}-" + "x" * 40, [], "bridge", "ok")
            s["out"] = [list(row) for _ in range(40)]
            s["in"] = [["2001:db8::1", 8080, "public", 1] for _ in range(20)]
            samples.append(s)
        window = activity.fit({"v": 1, "samples": samples})
        assert len(json.dumps(window, separators=(",", ":"))) <= activity.MAX_BYTES
        assert sum(len(s["out"]) + len(s["in"]) for s in window["samples"]) <= activity.MAX_DESTINATIONS
        assert all(s["truncated"] for s in window["samples"])

    def test_sample_cap(self):
        samples = [activity._sample_base(f"c{i}", [], "bridge", "ok") for i in range(70)]
        window = activity.fit({"v": 1, "samples": samples})
        assert len(window["samples"]) == 64 and window["samples_dropped"] == 6


# ---------------------------------------------------------------------------
# worker_api wiring
# ---------------------------------------------------------------------------


@pytest.fixture
def wapi():
    from app import worker_api

    saved = (
        worker_api._activity_enabled,
        worker_api._pending_activity,
        worker_api._activity_seq,
        worker_api._activity_setting_seen,
        worker_api._activity_missing_replies,
        worker_api._activity_switches,
    )
    worker_api._activity_setting_seen = False
    worker_api._activity_missing_replies = 0
    yield worker_api
    (
        worker_api._activity_enabled,
        worker_api._pending_activity,
        worker_api._activity_seq,
        worker_api._activity_setting_seen,
        worker_api._activity_missing_replies,
        worker_api._activity_switches,
    ) = saved


_FRESH_WORKER_SCRIPT = """
import asyncio
from unittest.mock import MagicMock, patch

from app import worker_api

assert worker_api._activity_enabled is False, "a fresh worker must start with Activity off"
with (
    patch("app.worker_api.orchestrator.docker_available", return_value=True) as docker_ok,
    patch("app.worker_api.activity.run_round", return_value=None) as run_round,
):
    asyncio.run(worker_api._activity_cycle())
    assert not docker_ok.called and not run_round.called, "a round ran before any reply"
    reply = MagicMock()
    reply.json.return_value = {"activity": {"enabled": True}}
    worker_api._apply_activity_reply(reply, None)
    asyncio.run(worker_api._activity_cycle())
    assert docker_ok.called and run_round.called, "control: a reply switching it on must run a round"
print("ok")
"""


def test_a_fresh_worker_starts_off_until_the_ui_says_on(tmp_path):
    """The module's own default, in a new interpreter, so no other test's state leaks in."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "CASHPILOT_API_KEY": "test-key", "PYTHONPATH": str(root)}
    out = subprocess.run(
        [sys.executable, "-c", _FRESH_WORKER_SCRIPT],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().endswith("ok")


class TestWorkerWiring:
    def test_disabled_never_runs_a_round(self, wapi):
        wapi._activity_enabled = False
        with (
            patch("app.worker_api.orchestrator.docker_available", return_value=True),
            patch("app.worker_api.activity.run_round") as run_round,
        ):
            asyncio.run(wapi._activity_cycle())
        assert not run_round.called

    def test_enabled_runs_a_round_negative_control(self, wapi):
        """The control for the test above: the same call with the switch on runs."""
        wapi._activity_enabled = True
        with (
            patch("app.worker_api.orchestrator.docker_available", return_value=True),
            patch("app.worker_api.activity.run_round", return_value={"v": 1, "samples": []}) as run_round,
        ):
            asyncio.run(wapi._activity_cycle())
        assert run_round.called
        assert wapi._pending_activity == {"v": 1, "samples": []}

    def test_round_exception_leaves_health_counters_alone(self, wapi):
        wapi._activity_enabled = True
        before = (wapi._consecutive_heartbeat_failures, wapi._ui_connected, wapi._last_heartbeat_ok)
        with (
            patch("app.worker_api.orchestrator.docker_available", return_value=True),
            patch("app.worker_api.activity.run_round", side_effect=RuntimeError("docker")),
            pytest.raises(RuntimeError),
        ):
            asyncio.run(wapi._activity_cycle())
        assert (wapi._consecutive_heartbeat_failures, wapi._ui_connected, wapi._last_heartbeat_ok) == before

    def test_reply_switches_on_and_clears_by_seq(self, wapi):
        wapi._activity_enabled = False
        wapi._pending_activity = {"v": 1}
        wapi._activity_seq = 3
        resp = MagicMock()
        resp.json.return_value = {"status": "ok", "activity": {"enabled": True}}
        wapi._apply_activity_reply(resp, 3)
        assert wapi._activity_enabled is True and wapi._pending_activity is None

    def test_newer_round_survives_a_reply_for_an_older_one(self, wapi):
        wapi._activity_enabled = True
        wapi._pending_activity = {"v": 1, "newer": True}
        wapi._activity_seq = 4
        resp = MagicMock()
        resp.json.return_value = {"activity": {"enabled": True}}
        wapi._apply_activity_reply(resp, 3)
        assert wapi._pending_activity == {"v": 1, "newer": True}

    def test_missing_key_means_off(self, wapi):
        wapi._activity_enabled = True
        wapi._pending_activity = {"v": 1}
        activity._prev["x"] = ("net:[1]", {}, 0.0)
        resp = MagicMock()
        resp.json.return_value = {"status": "ok"}
        wapi._apply_activity_reply(resp, None)
        assert wapi._activity_enabled is False and wapi._pending_activity is None
        assert activity._prev == {}

    def _heartbeat(self, wapi, *, docker_ok=True, fail=False, reply=None):
        sent = {}

        class Resp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return reply if reply is not None else {"status": "ok", "activity": {"enabled": True}}

        class Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, json=None, headers=None):
                sent.update(json)
                if fail:
                    raise ConnectionError("down")
                return Resp()

        with (
            patch("app.worker_api.orchestrator.get_status", return_value=[]),
            patch("app.worker_api.orchestrator.docker_available", return_value=docker_ok),
            patch("app.worker_api._detect_egress_ip", new_callable=AsyncMock, return_value=None),
            patch("app.worker_api._disk_usage", return_value=None),
            patch("app.worker_api._gpu_info", return_value={}),
            patch("app.worker_api.httpx.AsyncClient", Client),
            patch("app.worker_api.UI_URL", "http://ui:8080"),
        ):
            asyncio.run(wapi._send_heartbeat())
        return sent

    def test_feature_only_with_docker(self, wapi):
        assert "activity" in self._heartbeat(wapi, docker_ok=True)["system_info"]["features"]
        assert "activity" not in self._heartbeat(wapi, docker_ok=False)["system_info"]["features"]

    def test_round_attached_only_when_enabled(self, wapi):
        wapi._activity_enabled = False
        wapi._pending_activity = {"v": 1}
        assert "activity" not in self._heartbeat(wapi, reply={"status": "ok"})
        wapi._activity_enabled = True
        wapi._pending_activity = {"v": 1}
        wapi._activity_seq = 9
        sent = self._heartbeat(wapi)
        assert sent["activity"] == {"v": 1}
        assert wapi._pending_activity is None

    def test_round_kept_when_the_send_fails(self, wapi):
        wapi._activity_enabled = True
        wapi._pending_activity = {"v": 1}
        self._heartbeat(wapi, fail=True)
        assert wapi._pending_activity == {"v": 1}


def test_procnet_has_no_app_imports():
    """The probe runs procnet's source alone, so it cannot import the app."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path(procnet.__file__).read_text(encoding="utf-8"))
    mods = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    mods += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not [m for m in mods if m and m.startswith("app")]


class TestReviewFixes:
    """Regressions from the review of the first cut."""

    def test_nvidia_and_youki_runtimes_are_joinable(self):
        client = FakeClient([])
        client.runtimes["nvidia"] = {"path": "nvidia-container-runtime"}
        client.runtimes["youki"] = {"path": "/usr/bin/youki"}
        got = activity.joinable_runtimes(client)
        assert {"nvidia", "youki"} <= got

    def test_default_bridge_earner_reaching_a_non_earner_container_is_docker_peer(self):
        """On docker0 an earner shares the bridge with the user's own services."""
        nets = {"bridge": {"NetworkID": "d0", "Gateway": "172.17.0.1", "IPAddress": "172.17.0.2", "IPPrefixLen": 16}}
        hg = earner("cashpilot-honeygain", "h" * 64, nets=nets)
        data = json.loads(json.dumps(GOOD))
        data["summary"]["out"] = [
            ["tcp", "172.17.0.5", 5432, 1, {"syn_sent": 1}],
            ["tcp", "172.17.0.3", 8080, 1, {"est": 1}],
        ]
        client = FakeClient([hg], probe_factory=lambda kw: Probe(kw["name"], logs=json.dumps(data).encode()))
        client.networks = SimpleNamespace(
            get=lambda nid: SimpleNamespace(
                attrs={
                    "Driver": "bridge",
                    "Containers": {
                        "h" * 64: {"Name": "cashpilot-honeygain", "IPv4Address": "172.17.0.2/16"},
                        "r" * 64: {"Name": "cashpilot-repocket", "IPv4Address": "172.17.0.3/16"},
                        "p" * 64: {"Name": "postgres", "IPv4Address": "172.17.0.5/16"},
                    },
                }
            )
        )
        window = _round(client, ["cashpilot-honeygain", "cashpilot-repocket"])
        s = next(x for x in window["samples"] if x["container"] == "cashpilot-honeygain")
        assert {o[1]: o[3] for o in s["out"]} == {"172.17.0.5": "docker_peer", "172.17.0.3": "peer"}

    def test_a_long_gap_gives_no_delta(self):
        def data(opens):
            d = json.loads(json.dumps(GOOD))
            d["snmp_end"]["tcp"]["ActiveOpens"] = opens
            return d

        activity.deltas("o", data(100), 0.0)
        got = activity.deltas("o", data(5000), 2 * 86400.0)
        assert got["opens"] is None and got["delta_seconds"] is None
        # ...and that reading is the next baseline.
        assert activity.deltas("o", data(5010), 2 * 86400.0 + 300)["opens"] == 10

    def test_namespace_of_a_non_earner_keeps_counters_but_no_destinations(self):
        gw = earner("gluetun", "g" * 64)
        a = earner("cashpilot-a", "a" * 64, mode="container:gluetun")
        client = FakeClient([gw, a])
        window = _round(client, ["cashpilot-a"])
        s = window["samples"][0]
        assert s["container"] == "gluetun" and s["status"] == "ok"
        assert s["reason"] == "shared_namespace"
        assert s["out"] == [] and s["in"] == [] and s["est_max"] == 3

    def test_namespace_owned_by_an_earner_keeps_destinations(self):
        """Control for the test above: the same sharing, owner an earner."""
        gw = earner("cashpilot-gw", "g" * 64)
        a = earner("cashpilot-a", "a" * 64, mode="container:cashpilot-gw")
        client = FakeClient([gw, a])
        window = _round(client, ["cashpilot-gw", "cashpilot-a"])
        s = window["samples"][0]
        assert s["reason"] == "" and len(s["out"]) == 2


class TestWorkerReplyFixes:
    def _resp(self, body):
        resp = MagicMock()
        resp.json.return_value = body
        return resp

    def test_off_to_on_resets_counter_state(self, wapi):
        wapi._activity_enabled = False
        activity._prev["x"] = ("net:[1]", {}, 0.0)
        wapi._apply_activity_reply(self._resp({"activity": {"enabled": True}}), None)
        assert wapi._activity_enabled is True and activity._prev == {}

    def test_on_to_on_keeps_counter_state(self, wapi):
        wapi._activity_enabled = True
        activity._prev["x"] = ("net:[1]", {}, 0.0)
        wapi._apply_activity_reply(self._resp({"activity": {"enabled": True}}), None)
        assert "x" in activity._prev

    def test_a_round_discarded_after_switch_off_resets(self, wapi):
        wapi._activity_enabled = True

        def round_then_off():
            activity._prev["x"] = ("net:[1]", {}, 0.0)
            wapi._activity_enabled = False
            return {"v": 1, "samples": []}

        wapi._pending_activity = None
        with (
            patch("app.worker_api.orchestrator.docker_available", return_value=True),
            patch("app.worker_api.activity.run_round", side_effect=round_then_off),
        ):
            asyncio.run(wapi._activity_cycle())
        assert wapi._pending_activity is None and activity._prev == {}

    def test_window_kept_when_the_ui_did_not_store_it(self, wapi):
        wapi._activity_enabled = True
        wapi._pending_activity = {"v": 1}
        wapi._activity_seq = 3
        wapi._apply_activity_reply(self._resp({"activity": {"enabled": True, "stored": False}}), 3)
        assert wapi._pending_activity == {"v": 1}
        wapi._apply_activity_reply(self._resp({"activity": {"enabled": True, "stored": True}}), 3)
        assert wapi._pending_activity is None

    def test_missing_key_after_a_setting_is_unchanged(self, wapi):
        wapi._activity_enabled = False
        wapi._apply_activity_reply(self._resp({"activity": {"enabled": True}}), None)
        wapi._pending_activity = {"v": 1}
        activity._prev["x"] = ("net:[1]", {}, 0.0)
        wapi._apply_activity_reply(self._resp({"status": "ok"}), 1)
        assert wapi._activity_enabled is True and wapi._pending_activity == {"v": 1}
        assert "x" in activity._prev

    def test_a_ui_that_stops_sending_the_key_switches_it_off(self, wapi):
        """A UI rolled back to a version without Activity never sends the key again."""
        wapi._activity_enabled = False
        wapi._apply_activity_reply(self._resp({"activity": {"enabled": True}}), None)
        for _ in range(wapi.ACTIVITY_MISSING_REPLIES_OFF - 1):
            wapi._apply_activity_reply(self._resp({"status": "ok"}), None)
        assert wapi._activity_enabled is True
        wapi._apply_activity_reply(self._resp({"status": "ok"}), None)
        assert wapi._activity_enabled is False

    def test_one_reply_with_the_key_resets_the_missing_count(self, wapi):
        wapi._activity_enabled = False
        wapi._apply_activity_reply(self._resp({"activity": {"enabled": True}}), None)
        for _ in range(wapi.ACTIVITY_MISSING_REPLIES_OFF - 1):
            wapi._apply_activity_reply(self._resp({"status": "ok"}), None)
        wapi._apply_activity_reply(self._resp({"activity": {"enabled": True}}), None)
        for _ in range(wapi.ACTIVITY_MISSING_REPLIES_OFF - 1):
            wapi._apply_activity_reply(self._resp({"status": "ok"}), None)
        assert wapi._activity_enabled is True

    def test_a_round_spanning_off_and_on_is_dropped(self, wapi):
        wapi._activity_enabled = True

        def round_off_then_on():
            wapi._apply_activity_reply(self._resp({"activity": {"enabled": False}}), None)
            wapi._apply_activity_reply(self._resp({"activity": {"enabled": True}}), None)
            return {"v": 1, "samples": []}

        wapi._pending_activity = None
        with (
            patch("app.worker_api.orchestrator.docker_available", return_value=True),
            patch("app.worker_api.activity.run_round", side_effect=round_off_then_on),
        ):
            asyncio.run(wapi._activity_cycle())
        assert wapi._activity_enabled is True and wapi._pending_activity is None


class TestHostNetworkByCgroup:
    """Host-network earners: probed on the host network and matched by their cgroup."""

    def _host_round(self, logs=None, names=("cashpilot-mysterium",)):
        client = FakeClient(
            [earner("cashpilot-mysterium", "m" * 64, mode="host", nets={})],
            probe_factory=lambda kw: Probe(kw["name"], logs=json.dumps(logs or HOST_GOOD).encode()),
        )
        return client, _round(client, list(names))

    def test_host_earner_is_probed_with_the_floor_on_the_host_network(self):
        client, window = self._host_round()
        assert len(client.runs) == 1
        kw = client.runs[0]
        assert kw["network_mode"] == "host" and kw["cgroupns"] == "host"
        assert kw["environment"]["PROBE_MODE"] == "cgroup" and kw["environment"]["PROBE_CONTAINER"] == "m" * 64
        s = window["samples"][0]
        assert s["status"] == "ok" and s["reason"] == "host_cgroup"
        assert [d[3] for d in s["out"]] == ["public", "public", "lan"]
        assert s["in"] == [["203.0.113.7", 4449, "public", 2]]

    def test_host_rows_never_carry_counter_changes(self):
        """The host's counters are the machine's: a host row has no deltas, even on a second round."""
        logs = dict(HOST_GOOD, netns="net:[1]", snmp_end=GOOD["snmp_end"])
        client = FakeClient(
            [earner("cashpilot-mysterium", "m" * 64, mode="host", nets={})],
            probe_factory=lambda kw: Probe(kw["name"], logs=json.dumps(logs).encode()),
        )
        _round(client, ["cashpilot-mysterium"], now=1_000_000.0)
        window = _round(client, ["cashpilot-mysterium"], now=1_000_300.0)
        s = window["samples"][0]
        assert all(s[k] is None for k in activity.DELTA_KEYS) and s["delta_seconds"] is None

    def test_a_host_round_drops_the_previous_bridge_reading(self):
        """bridge, host, bridge: the third round must not file a change measured across the host round."""
        mode = {"m": "bridge"}

        def containers():
            nets = {} if mode["m"] == "host" else None
            return [earner("cashpilot-x", "x" * 64, mode=mode["m"], nets=nets)]

        def factory(kw):
            return Probe(kw["name"], logs=json.dumps(HOST_GOOD if kw.get("network_mode") == "host" else GOOD).encode())

        client = FakeClient(containers(), probe_factory=factory)
        _round(client, ["cashpilot-x"], now=1_000_000.0)
        mode["m"] = "host"
        client.by_key.update({c.name: c for c in containers()} | {c.id: c for c in containers()})
        assert _round(client, ["cashpilot-x"], now=1_000_300.0)["samples"][0]["reason"] == "host_cgroup"
        mode["m"] = "bridge"
        client.by_key.update({c.name: c for c in containers()} | {c.id: c for c in containers()})
        window = _round(client, ["cashpilot-x"], now=1_000_600.0)
        assert window["samples"][0]["opens"] is None

    def test_host_rows_raise_mail_and_lan_alerts(self):
        from app import activity_ui

        _, window = self._host_round()
        clean = activity_ui.sanitise(window, now=window["window_end"])
        kinds = sorted(f["kind"] for f in activity_ui.alert_findings(clean))
        assert kinds == ["activity_lan", "activity_mail"]

    @pytest.mark.parametrize("reason", ["cgroup_v1", "cgroup_missing", "sock_diag_refused", "kernel_no_cgroup_id"])
    def test_a_probe_that_cannot_attribute_shows_host_network_with_its_reason(self, reason):
        _, window = self._host_round(logs=dict(HOST_GOOD, reason=reason))
        s = window["samples"][0]
        assert (s["status"], s["reason"]) == ("host_network", reason)
        assert s["out"] == [] and s["in"] == [] and s["est_max"] is None

    def test_a_reading_without_cgroup_attribution_is_not_trusted(self):
        """A netns reading for a host earner is the whole machine's table: never shown as the earner's."""
        _, window = self._host_round(logs=GOOD)
        s = window["samples"][0]
        assert s["status"] == "host_network" and s["out"] == []

    def test_host_context_has_no_bridge(self):
        c = earner("cashpilot-mysterium", "m" * 64, mode="host", nets={})
        c.attrs["HostConfig"]["Dns"] = ["192.168.1.1"]
        assert activity.host_context(c) == {"gateways": [], "dns": ["192.168.1.1"], "subnets": [], "peers": []}

    def test_probe_kwargs_host_keeps_every_floor_key(self):
        net = activity.probe_kwargs("img", "m" * 64)
        host = activity.probe_kwargs_host("img", "m" * 64)
        for key in (
            "user",
            "read_only",
            "cap_drop",
            "security_opt",
            "privileged",
            "pids_limit",
            "mem_limit",
            "tmpfs",
            "log_config",
        ):
            assert host[key] == net[key], key
        assert host["user"] == "65534:65534" and host["cap_drop"] == ["ALL"] and host["privileged"] is False
        assert "cap_add" not in host and "volumes" not in host and "devices" not in host
        assert set(host) - set(net) == {"cgroupns"}


class TestTwoWorkersOneHost:
    def test_sweep_keeps_another_workers_live_probe_and_running_legacy_ones(self):
        def theirs(name, status):
            return Probe(
                name, attrs={"Config": {"Labels": {"cashpilot.probe.worker": "other"}}, "State": {"Status": status}}
            )

        client = FakeClient([])
        client.listed_leftovers = [
            Probe(
                "ours", attrs={"Config": {"Labels": {"cashpilot.probe.worker": WORKER}}, "State": {"Status": "running"}}
            ),
            theirs("theirs-running", "running"),
            Probe(
                "theirs-created",
                attrs={
                    "Config": {"Labels": {"cashpilot.probe.worker": "other"}},
                    "State": {"Status": "created"},
                    "Created": _stamp(-1),
                },
            ),
            Probe("legacy-running", attrs={"Config": {"Labels": {}}, "State": {"Status": "running"}}),
            Probe("legacy-exited", attrs={"Config": {"Labels": {}}, "State": {"Status": "exited"}}),
        ]
        assert activity.sweep(client) == []
        removed = [p.name for p in client.listed_leftovers if p.removed]
        assert removed == ["ours", "legacy-exited"]

    @pytest.mark.parametrize("status", ["exited", "dead"])
    def test_sweep_removes_a_finished_probe_of_another_worker(self, status):
        """A finished probe keeps its round's addresses in its Docker log; it is never mid-round, so any worker removes it.

        A worker without a writable /data gets a new id on every start, so its old probes would
        otherwise stay on the host for good.
        """
        client = FakeClient([])
        client.listed_leftovers = [
            Probe(
                "theirs-done",
                attrs={"Config": {"Labels": {"cashpilot.probe.worker": "other"}}, "State": {"Status": status}},
            ),
        ]
        assert activity.sweep(client) == []
        assert client.listed_leftovers[0].removed

    @pytest.mark.parametrize("status", ["exited", "dead"])
    def test_sweep_leaves_another_workers_just_finished_probe_for_its_owner(self, status):
        """Its owner calls logs() right after wait(); removing it in that gap would lose the owner's sample."""
        client = FakeClient([])
        fresh = {"Status": status, "FinishedAt": _stamp(-2)}
        client.listed_leftovers = [
            Probe("theirs-fresh", attrs={"Config": {"Labels": {"cashpilot.probe.worker": "other"}}, "State": fresh}),
        ]
        assert activity.sweep(client) == []
        assert not client.listed_leftovers[0].removed

    def test_sweep_removes_stale_finished_and_stuck_created_probes_of_another_worker(self):
        old = _stamp(-(activity.PROBE_TIMEOUT + 5))
        labels = {"Config": {"Labels": {"cashpilot.probe.worker": "other"}}}
        client = FakeClient([])
        client.listed_leftovers = [
            Probe("theirs-old-exit", attrs={**labels, "State": {"Status": "exited", "FinishedAt": old}}),
            Probe("theirs-stuck", attrs={**labels, "State": {"Status": "created"}, "Created": old}),
        ]
        assert activity.sweep(client) == []
        assert all(p.removed for p in client.listed_leftovers)

    def test_probe_names_differ_per_worker(self, monkeypatch):
        mine = activity.probe_name("a" * 64)
        monkeypatch.setattr(activity, "WORKER_ID", "worker-two")
        assert activity.probe_name("a" * 64) != mine

    def test_the_worker_labels_its_probes_with_its_own_id(self, tmp_path):
        """In a new interpreter: importing the worker sets the id its probes carry."""
        import os
        import subprocess
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        env = {
            **os.environ,
            "CASHPILOT_API_KEY": "test-key",
            "PYTHONPATH": str(root),
            "CASHPILOT_DATA_DIR": str(tmp_path),
        }
        script = (
            "from app import activity, worker_api\n"
            "assert worker_api.CLIENT_ID and activity.WORKER_ID == worker_api.CLIENT_ID, activity.WORKER_ID\n"
            "print('ok')\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60
        )
        assert out.returncode == 0, out.stderr[-2000:]
