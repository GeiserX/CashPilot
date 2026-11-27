"""The gVisor self-test must go red unless gVisor's kernel answers and names resolve.

A runtime's name proves nothing: "runsc-hostnet" can point at runc. The probe
runs under each gVisor runtime an earner would get, on the earners' network,
and the check is green only when every probe saw gVisor's kernel and resolved
a public name. The outputs below are the ones measured on real hosts.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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


def _run(facts, probes):
    client = MagicMock()
    me = MagicMock()
    me.attrs = {"Image": "sha256:worker"}
    calls = []

    def probe(client, image, runtime, network, leftovers):
        calls.append((runtime, network))
        return probes[runtime]

    with (
        patch.object(gvisor_check, "_client", return_value=client),
        patch.object(layers, "daemon_runtimes", return_value=facts),
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
        assert calls == [("runsc-hostnet", "cashpilot-isolated"), ("runsc-hostnet-raw", "cashpilot-isolated")]

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
