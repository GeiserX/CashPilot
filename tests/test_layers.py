"""The owner chooses an earner's runtime in the UI; the worker reports what it can give.

The worker reports the runtimes Docker registered, which of them are gVisor,
whether the host has KVM, and what an environment variable pins
(system_info.layers). A deploy carries the owner's choice as runtime_choice,
"runc" or "gvisor". The worker turns gVisor into the variant Docker's DNS and
the earner's capabilities need, and refuses a choice that its catalog or its
environment overrules, with the reason, before the running container is touched.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import layers, orchestrator, worker_api

RUNTIMES = {
    "io.containerd.runc.v2": {"path": "runc"},
    "runc": {"path": "runc"},
    "runsc": {"path": "/usr/local/bin/runsc"},
    "runsc-hostnet": {"path": "/usr/local/bin/runsc", "runtimeArgs": ["--network=host"]},
    "runsc-hostnet-raw": {"path": "/usr/local/bin/runsc", "runtimeArgs": ["--network=host", "--net-raw"]},
}
FACTS = layers.runtime_facts(RUNTIMES)


class TestRuntimeFacts:
    def test_gvisor_is_judged_by_its_binary(self):
        by_name = {f["name"]: f for f in FACTS}
        assert not by_name["runc"]["gvisor"]
        assert by_name["runsc"]["gvisor"] and not by_name["runsc"]["hostnet"]
        assert by_name["runsc-hostnet"]["hostnet"] and not by_name["runsc-hostnet"]["net_raw"]
        assert by_name["runsc-hostnet-raw"]["net_raw"]

    def test_a_runc_binary_under_a_gvisor_name_is_not_gvisor(self):
        # The negative control of the self-test: a runtime named runsc-hostnet
        # that really points at runc must not count as a layer.
        facts = layers.runtime_facts({"runsc-hostnet": {"path": "/usr/bin/runc", "runtimeArgs": ["--network=host"]}})
        assert facts == [{"name": "runsc-hostnet", "gvisor": False, "hostnet": False, "net_raw": False}]

    def test_the_space_separated_flag_form(self):
        facts = layers.runtime_facts(
            {"g": {"path": "/opt/runsc", "runtimeArgs": ["--network", "host", "--net-raw=true"]}}
        )
        assert facts[0]["hostnet"] and facts[0]["net_raw"]

    def test_nothing_readable_is_no_runtimes(self):
        assert layers.runtime_facts(None) == []


class TestKvm:
    def test_present(self, tmp_path):
        (tmp_path / "class" / "misc" / "kvm").mkdir(parents=True)
        with patch.object(layers.platform, "system", return_value="Linux"):
            assert layers.kvm(tmp_path, docker_host="") is True

    def test_absent(self, tmp_path):
        (tmp_path / "class" / "misc" / "tun").mkdir(parents=True)
        with patch.object(layers.platform, "system", return_value="Linux"):
            assert layers.kvm(tmp_path, docker_host="") is False

    def test_unreadable_sysfs_is_unknown_not_absent(self, tmp_path):
        with patch.object(layers.platform, "system", return_value="Linux"):
            assert layers.kvm(tmp_path, docker_host="") is None

    def test_a_remote_docker_is_unknown(self, tmp_path):
        (tmp_path / "class" / "misc" / "kvm").mkdir(parents=True)
        with patch.object(layers.platform, "system", return_value="Linux"):
            assert layers.kvm(tmp_path, docker_host="tcp://10.0.0.2:2375") is None

    def test_not_linux_is_unknown(self, tmp_path):
        with patch.object(layers.platform, "system", return_value="Darwin"):
            assert layers.kvm(tmp_path, docker_host="") is None


class TestPick:
    def _pick(self, choice, facts=FACTS, net_raw=False, allowed=None):
        return layers.pick(choice, "x", facts, net_raw=net_raw, allowed=allowed, service="X")

    def test_runc(self):
        assert self._pick("runc") == "runc"

    def test_gvisor_takes_the_dns_safe_variant_without_raw_sockets(self):
        assert self._pick("gvisor") == "runsc-hostnet"

    def test_raw_sockets_take_the_net_raw_variant(self):
        assert self._pick("gvisor", net_raw=True) == "runsc-hostnet-raw"

    def test_plain_runsc_is_not_enough(self):
        facts = layers.runtime_facts({"runc": {"path": "runc"}, "runsc": {"path": "/usr/local/bin/runsc"}})
        with pytest.raises(layers.ChoiceRefused, match="--network=host"):
            self._pick("gvisor", facts=facts)

    def test_raw_sockets_without_the_variant_are_refused(self):
        facts = layers.runtime_facts({"runsc-hostnet": RUNTIMES["runsc-hostnet"]})
        with pytest.raises(layers.ChoiceRefused, match="raw sockets"):
            self._pick("gvisor", facts=facts, net_raw=True)

    def test_a_name_the_proxy_refuses_is_not_used(self):
        facts = layers.runtime_facts({"gv": {"path": "/usr/local/bin/runsc", "runtimeArgs": ["--network=host"]}})
        with pytest.raises(layers.ChoiceRefused):
            self._pick("gvisor", facts=facts, allowed=("runc", "runsc-hostnet"))

    def test_an_unaskable_daemon(self):
        with pytest.raises(layers.ChoiceRefused, match="not answering"):
            self._pick("gvisor", facts=None)


def _client(old=None):
    client = MagicMock()
    if old is None:
        client.containers.get.side_effect = orchestrator.NotFound("nope")
    else:
        client.containers.get.return_value = old
    created = MagicMock()
    created.id = "new"
    created.short_id = "new"
    client.containers.run.return_value = created
    return client


def _deploy(client, choice, default="", overrides="", **kwargs):
    kwargs.setdefault("slug", "honeygain")
    kwargs.setdefault("image", "honeygain/honeygain")
    with (
        patch.object(orchestrator, "_CONTAINER_RUNTIME", default),
        patch.object(orchestrator, "_CONTAINER_RUNTIME_OVERRIDES", overrides),
        patch.object(orchestrator, "_CONTAINER_NETWORK", ""),
        patch.object(orchestrator, "available_runtimes", return_value=set(RUNTIMES)),
        patch.object(layers, "daemon_runtimes", return_value=FACTS),
        patch.object(orchestrator, "_get_client", return_value=client),
    ):
        orchestrator.deploy_raw(runtime_choice=choice, **kwargs)
    return client.containers.run.call_args.kwargs


class TestTheChoiceOnADeploy:
    def test_no_choice_keeps_dockers_default(self):
        assert _deploy(_client(), None)["runtime"] is None

    def test_gvisor(self):
        assert _deploy(_client(), "gvisor")["runtime"] == "runsc-hostnet"

    def test_standard(self):
        assert _deploy(_client(), "runc")["runtime"] == "runc"

    def test_bitping_gets_raw_sockets_back_from_its_own_catalog(self):
        assert _deploy(_client(), "gvisor", slug="bitping", image="bitping/bitpingd")["runtime"] == "runsc-hostnet-raw"

    def test_an_env_pin_that_agrees_is_used(self):
        kwargs = _deploy(_client(), "gvisor", overrides="honeygain=runsc-hostnet-raw")
        assert kwargs["runtime"] == "runsc-hostnet-raw"

    def test_runc_under_a_catalog_requirement_of_runc(self):
        # Mysterium is fence-gated, so its deploy takes another path; the
        # runtime is decided here, before either path starts.
        with patch.object(layers, "daemon_runtimes", return_value=FACTS):
            assert orchestrator.container_runtime("mysterium", None, None, "runc") == "runc"


class TestARefusedChoiceTouchesNothing:
    def _refused(self, choice, **kwargs):
        old = MagicMock()
        client = _client(old=old)
        with pytest.raises(orchestrator.ContainerRuntimeError) as err:
            _deploy(client, choice, **kwargs)
        old.stop.assert_not_called()
        old.remove.assert_not_called()
        client.containers.run.assert_not_called()
        return str(err.value)

    def test_mysterium_under_gvisor_names_its_catalog(self):
        with (
            patch.object(layers, "daemon_runtimes", return_value=FACTS),
            pytest.raises(orchestrator.ContainerRuntimeError) as err,
        ):
            orchestrator.container_runtime("mysterium", None, None, "gvisor")
        assert "catalog entry requires the 'runc' runtime" in str(err.value)
        assert err.value.status_code == 409

    def test_the_worker_default_wins_and_says_so(self):
        why = self._refused("runc", default="runsc-hostnet")
        assert "CASHPILOT_CONTAINER_RUNTIME on this worker is runsc-hostnet" in why

    def test_an_override_wins_and_says_so(self):
        why = self._refused("gvisor", overrides="honeygain=runc")
        assert "CASHPILOT_CONTAINER_RUNTIME_OVERRIDES on this worker sets honeygain=runc" in why

    def test_gvisor_without_the_runtime(self):
        with patch.object(layers, "daemon_runtimes", return_value=layers.runtime_facts({"runc": {"path": "runc"}})):
            old = MagicMock()
            client = _client(old=old)
            with (
                patch.object(orchestrator, "_CONTAINER_RUNTIME", ""),
                patch.object(orchestrator, "_CONTAINER_RUNTIME_OVERRIDES", ""),
                patch.object(orchestrator, "_CONTAINER_NETWORK", ""),
                patch.object(orchestrator, "_get_client", return_value=client),
                pytest.raises(orchestrator.ContainerRuntimeError, match="gVisor install command"),
            ):
                orchestrator.deploy_raw("honeygain", "honeygain/honeygain", runtime_choice="gvisor")
            client.containers.run.assert_not_called()
            old.stop.assert_not_called()

    def test_a_choice_that_disagrees_with_the_named_runtime_is_refused(self):
        with (
            patch.object(layers, "daemon_runtimes", return_value=FACTS),
            pytest.raises(orchestrator.ContainerRuntimeError, match="the deploy names the 'runc' runtime"),
        ):
            orchestrator.container_runtime("honeygain", None, "runc", "gvisor")

    def test_a_choice_that_agrees_with_the_named_runtime_is_used(self):
        with (
            patch.object(layers, "daemon_runtimes", return_value=FACTS),
            patch.object(orchestrator, "_proxy_allows_runtime", side_effect=lambda slug, r: r),
        ):
            assert orchestrator.container_runtime("honeygain", None, "runsc-hostnet", "gvisor") == "runsc-hostnet"

    def test_an_unknown_choice(self):
        with pytest.raises(orchestrator.ContainerRuntimeError) as err:
            orchestrator.container_runtime("honeygain", None, None, "kata")
        assert err.value.status_code == 400


class TestTheWorkerApi:
    def test_an_unknown_choice_is_a_400(self):
        with patch.object(worker_api, "_verify_api_key"):
            resp = TestClient(worker_api.app).post(
                "/api/containers/honeygain/deploy", json={"image": "x", "runtime_choice": "kata"}
            )
        assert resp.status_code == 400, resp.text
        assert "runtime_choice" in resp.json()["detail"]

    def test_the_report_carries_pins_and_unknowns(self):
        with (
            patch.object(layers, "docker_info", return_value=None),
            patch.object(layers, "kvm", return_value=None),
            patch.object(orchestrator, "_CONTAINER_RUNTIME", "runsc-hostnet"),
            patch.object(orchestrator, "_CONTAINER_RUNTIME_OVERRIDES", "bitping=runsc-hostnet-raw"),
            patch.object(orchestrator, "proxied", return_value=True),
        ):
            report = worker_api._layers_report()
        assert report["runtimes"] is None
        assert report["default_runtime"] is None
        assert report["kvm"] is None
        assert report["pins"] == {"default": "runsc-hostnet", "overrides": {"bitping": "runsc-hostnet-raw"}}
        assert "runsc-hostnet" in report["proxy_runtimes"]

    def test_a_malformed_override_is_reported(self):
        with patch.object(orchestrator, "_CONTAINER_RUNTIME_OVERRIDES", "bitping"):
            pins = orchestrator.runtime_pins()
        assert pins["overrides"] == {}
        assert "slug=runtime" in pins["error"]

    @pytest.mark.parametrize("runtimes", [None, "runc", ["runc"]])
    def test_an_unreadable_runtime_list_is_unknown_not_empty(self, runtimes):
        info = {"DefaultRuntime": "runc"} if runtimes is None else {"Runtimes": runtimes}
        with patch.object(layers, "docker_info", return_value=info), patch.object(layers, "kvm", return_value=None):
            assert layers.report({"default": None, "overrides": {}}, None)["runtimes"] is None
            assert layers.daemon_runtimes() is None

    def test_a_readable_empty_list_is_empty(self):
        with patch.object(layers, "docker_info", return_value={"Runtimes": {}}):
            assert layers.daemon_runtimes() == []

    def test_a_routed_copy_refuses_a_runtime_choice(self):
        body = {
            "earner": {"image": "honeygain/honeygain", "runtime_choice": "gvisor"},
            "proxy": {"kind": "socks5", "host": "203.0.113.9", "port": 1080},
        }
        with patch.object(worker_api, "_verify_api_key"):
            resp = TestClient(worker_api.app).post("/api/proxied/honeygain/3/deploy", json=body)
        assert resp.status_code == 400, resp.text
        assert "routed through a proxy" in resp.json()["detail"]

    def test_the_report_lists_the_runtimes(self):
        info = {"Runtimes": RUNTIMES, "DefaultRuntime": "runc"}
        with patch.object(layers, "docker_info", return_value=info), patch.object(layers, "kvm", return_value=True):
            report = layers.report({"default": None, "overrides": {}}, None)
        assert [f["name"] for f in report["runtimes"] if f["gvisor"]] == ["runsc", "runsc-hostnet", "runsc-hostnet-raw"]
        assert report["default_runtime"] == "runc"
        assert report["kvm"] is True
        assert report["proxy_runtimes"] is None


def test_each_container_says_which_runtime_and_network_it_got():
    container = MagicMock()
    container.attrs = {"HostConfig": {"Runtime": "runsc-hostnet", "NetworkMode": "cashpilot-isolated"}}
    assert orchestrator._layer_entry(container) == {"runtime": "runsc-hostnet", "network": "cashpilot-isolated"}
    container.attrs = {}
    assert orchestrator._layer_entry(container) == {"runtime": None, "network": None}
