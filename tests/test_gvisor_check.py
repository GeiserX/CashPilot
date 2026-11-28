"""The gVisor self-test must go red unless gVisor's kernel answers and names resolve.

A runtime's name proves nothing: "runsc-hostnet" can point at runc. The probe
runs under each gVisor runtime an earner would get, on the earners' network,
and the check is green only when every probe saw gVisor's kernel and resolved
a public name. The outputs below are the ones measured on real hosts.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import gvisor_check, layers, worker_api

GVISOR = {
    "release": "4.19.0-gvisor",
    "version": "Linux version 4.19.0-gvisor #1 SMP Sun Jan 10 15:06:54 PST 2016",
    "dns": ["104.16.132.229"],
}
RUNC = {
    "release": "6.8.0-151-generic",
    "version": "Linux version 6.8.0-151-generic (buildd@lcy02-amd64-009) #151-Ubuntu SMP",
    "dns": ["104.16.132.229"],
}


class TestJudge:
    def test_gvisor_with_dns_is_green(self):
        verdict = gvisor_check.judge(GVISOR)
        assert verdict["kernel"] and verdict["dns"]

    def test_the_hosts_kernel_is_red(self):
        verdict = gvisor_check.judge(RUNC)
        assert not verdict["kernel"]
        assert "real Linux kernel (6.8.0-151-generic)" in verdict["kernel_why"]

    def test_no_dns_is_red_and_says_why(self):
        verdict = gvisor_check.judge({**GVISOR, "dns": [], "dns_error": "gaierror: [Errno -3] Try again"})
        assert verdict["kernel"] and not verdict["dns"]
        assert "--network=host" in verdict["dns_why"]

    def test_an_empty_answer_is_red(self):
        verdict = gvisor_check.judge({})
        assert not verdict["kernel"] and not verdict["dns"]


def _run(facts, probes, dns=None):
    client = MagicMock()
    me = MagicMock()
    me.attrs = {"Image": "sha256:worker"}
    calls = []

    def probe(client, image, runtime, network, leftovers, dns=None):
        calls.append((runtime, network, dns))
        return probes[runtime]

    with (
        patch.object(gvisor_check, "_client", return_value=client),
        patch.object(layers, "daemon_runtimes", return_value=facts),
        patch.object(gvisor_check.orchestrator, "container_dns", return_value=dns),
        patch.object(gvisor_check.orchestrator, "proxied", return_value=True),
        patch.object(gvisor_check.orchestrator, "_self_container", return_value=me),
        patch.object(gvisor_check.lan_fence, "effective_network", return_value=("on", "cashpilot-isolated")),
        patch.object(gvisor_check, "_probe", side_effect=probe),
    ):
        return gvisor_check.run(), calls


FACTS = layers.runtime_facts(
    {
        "runc": {"path": "runc"},
        "runsc-hostnet": {
            "path": "/usr/local/lib/cashpilot-gvisor/20261123.1/runsc",
            "runtimeArgs": ["--network=host"],
        },
        "runsc-hostnet-raw": {
            "path": "/usr/local/lib/cashpilot-gvisor/20261123.1/runsc",
            "runtimeArgs": ["--network=host", "--net-raw"],
        },
    }
)


class TestRun:
    def test_green_when_every_runtime_passes(self):
        result, calls = _run(FACTS, {"runsc-hostnet": GVISOR, "runsc-hostnet-raw": GVISOR})
        assert result["state"] == "green"
        assert calls == [
            ("runsc-hostnet", "cashpilot-isolated", None),
            ("runsc-hostnet-raw", "cashpilot-isolated", None),
        ]

    def test_red_when_one_runtime_is_really_runc(self):
        result, _ = _run(FACTS, {"runsc-hostnet": GVISOR, "runsc-hostnet-raw": RUNC})
        assert result["state"] == "red"
        assert [r["kernel"] for r in result["runtimes"]] == [True, False]

    def test_red_when_the_probe_cannot_run(self):
        result, _ = _run(
            FACTS, {"runsc-hostnet": {"error": "Docker could not run the probe"}, "runsc-hostnet-raw": GVISOR}
        )
        assert result["state"] == "red"

    def test_no_gvisor_is_not_installed(self):
        result, calls = _run(layers.runtime_facts({"runc": {"path": "runc"}}), {})
        assert result["state"] == "not_installed"
        assert calls == []

    def test_plain_runsc_only_is_not_installed_and_says_why(self):
        result, _ = _run(layers.runtime_facts({"runsc": {"path": "/usr/local/bin/runsc"}}), {})
        assert result["state"] == "not_installed"
        assert "--network=host" in result["message"]

    def test_the_probe_uses_the_resolvers_the_earners_get(self):
        _, calls = _run(FACTS, {"runsc-hostnet": GVISOR, "runsc-hostnet-raw": GVISOR}, dns=["1.1.1.1", "9.9.9.9"])
        assert [c[2] for c in calls] == [["1.1.1.1", "9.9.9.9"]] * 2

    def test_a_bad_resolver_setting_is_red(self):
        with patch.object(
            gvisor_check.orchestrator, "container_dns", side_effect=gvisor_check.orchestrator.ContainerNetworkError("x")
        ):
            client = MagicMock()
            me = MagicMock()
            me.attrs = {"Image": "sha256:worker"}
            with (
                patch.object(gvisor_check, "_client", return_value=client),
                patch.object(layers, "daemon_runtimes", return_value=FACTS),
                patch.object(gvisor_check.orchestrator, "proxied", return_value=True),
                patch.object(gvisor_check.orchestrator, "_self_container", return_value=me),
                patch.object(gvisor_check.lan_fence, "effective_network", return_value=("on", "cashpilot-isolated")),
                patch.object(gvisor_check, "_probe") as probe,
            ):
                result = gvisor_check.run()
        assert result["state"] == "red"
        assert "CASHPILOT_CONTAINER_DNS" in result["message"]
        probe.assert_not_called()

    def test_an_unreadable_runtime_list_is_no_answer_not_not_installed(self):
        with (
            patch.object(gvisor_check, "_client", return_value=MagicMock()),
            patch.object(layers, "daemon_runtimes", return_value=None),
            patch.object(layers, "set_last_check") as saved,
            pytest.raises(RuntimeError),
        ):
            gvisor_check.run()
        saved.assert_not_called()

    def test_the_heartbeat_carries_the_last_answer(self):
        result, _ = _run(FACTS, {"runsc-hostnet": GVISOR, "runsc-hostnet-raw": GVISOR})
        with patch.object(layers, "docker_info", return_value=None), patch.object(layers, "kvm", return_value=None):
            assert layers.report({}, None)["gvisor_check"]["state"] == result["state"] == "green"


class TestTheEndpoint:
    def test_busy_is_a_409_the_ui_can_forward(self):
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(gvisor_check, "run", side_effect=gvisor_check.CheckBusy("busy")),
        ):
            resp = TestClient(worker_api.app).post("/api/layers/gvisor-check")
        assert resp.status_code == 409
        assert resp.json()["detail"]["error"] == "gvisor_check_busy"

    def test_no_docker_is_a_503(self):
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(gvisor_check, "run", side_effect=RuntimeError("Docker socket not available")),
        ):
            resp = TestClient(worker_api.app).post("/api/layers/gvisor-check")
        assert resp.status_code == 503
        assert resp.json()["detail"]["error"] == "gvisor_check_unavailable"

    def test_it_needs_the_key(self):
        resp = TestClient(worker_api.app).post("/api/layers/gvisor-check")
        assert resp.status_code in (401, 503)


class TestTheProbeContainer:
    """Two workers on one Docker daemon must never remove each other's probe."""

    def _probe(self, worker_id, stale_labels=None):
        client = MagicMock()
        client.containers.get.return_value.attrs = {"Config": {"Labels": stale_labels or {}}}
        container = client.containers.run.return_value
        container.wait.return_value = {"StatusCode": 0}
        container.logs.return_value = b'{"release": "4.19.0-gvisor"}'
        with patch.object(gvisor_check.activity, "WORKER_ID", worker_id):
            gvisor_check._probe(client, "img", "runsc-hostnet", "cashpilot-isolated", [], ["1.1.1.1"])
            name = gvisor_check.probe_name()
        return client, name

    def test_each_worker_has_its_own_probe_name(self):
        _, a = self._probe("worker-a")
        _, b = self._probe("worker-b")
        assert a != b
        assert a.startswith(gvisor_check.PROBE_PREFIX)

    def test_it_creates_and_removes_only_its_own_probe(self):
        client, name = self._probe("worker-a")
        kwargs = client.containers.run.call_args.kwargs
        assert kwargs["name"] == name
        assert kwargs["labels"][gvisor_check.activity.WORKER_LABEL] == "worker-a"
        assert kwargs["dns"] == ["1.1.1.1"]
        assert {c.args[0] for c in client.containers.get.call_args_list} == {name}

    def test_it_removes_the_container_it_created_by_its_handle(self):
        client, _ = self._probe("worker-a")
        client.containers.run.return_value.remove.assert_called_once_with(force=True, v=True)

    def test_a_stale_probe_of_its_own_is_removed_first(self):
        labels = {gvisor_check.PROBE_LABEL: "gvisor-check", gvisor_check.activity.WORKER_LABEL: "worker-a"}
        client, _ = self._probe("worker-a", stale_labels=labels)
        client.containers.get.return_value.remove.assert_called_once_with(force=True, v=True)

    def test_a_container_that_only_shares_the_name_is_left_alone(self):
        labels = {gvisor_check.PROBE_LABEL: "gvisor-check", gvisor_check.activity.WORKER_LABEL: "worker-b"}
        client, _ = self._probe("worker-a", stale_labels=labels)
        client.containers.get.return_value.remove.assert_not_called()

    def test_a_create_that_failed_halfway_is_cleaned_up_by_name(self):
        client = MagicMock()
        client.containers.run.side_effect = gvisor_check.DockerException("start failed")
        stale = client.containers.get.return_value
        with patch.object(gvisor_check.activity, "WORKER_ID", "worker-a"):
            stale.attrs = {
                "Config": {
                    "Labels": {gvisor_check.PROBE_LABEL: "gvisor-check", gvisor_check.activity.WORKER_LABEL: "worker-a"}
                }
            }
            result = gvisor_check._probe(client, "img", "runsc-hostnet", "", [])
        assert "error" in result
        assert stale.remove.call_count == 2  # once before the run, once after it failed
