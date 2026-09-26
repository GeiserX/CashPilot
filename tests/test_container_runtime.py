"""The operator can run bridge-networked earners under a runtime such as gVisor.

The worker already accepted a runtime in a deploy request, but the dashboard
never sends one, so a service moved to gVisor by hand went back to Docker's
default on its next redeploy. CASHPILOT_CONTAINER_RUNTIME makes the choice a
worker setting, with per-service exceptions in
CASHPILOT_CONTAINER_RUNTIME_OVERRIDES (Bitping needs a runtime registered with
--net-raw). A runtime the daemon does not provide is refused before the running
container is touched.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import orchestrator, worker_api

INSTALLED = {"runc", "runsc-hostnet", "runsc-hostnet-raw"}


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


def _deploy(client, default="", overrides="", installed=INSTALLED, **kwargs):
    kwargs.setdefault("slug", "honeygain")
    kwargs.setdefault("image", "honeygain/honeygain")
    with (
        patch.object(orchestrator, "_CONTAINER_RUNTIME", default),
        patch.object(orchestrator, "_CONTAINER_RUNTIME_OVERRIDES", overrides),
        patch.object(orchestrator, "_CONTAINER_NETWORK", ""),
        patch.object(orchestrator, "available_runtimes", return_value=installed),
        patch.object(orchestrator, "_get_client", return_value=client),
    ):
        orchestrator.deploy_raw(**kwargs)
    return client.containers.run.call_args.kwargs


class TestTheDefault:
    def test_unset_keeps_dockers_default_runtime(self):
        assert _deploy(_client())["runtime"] is None

    def test_set_applies_to_a_bridge_networked_service(self):
        assert _deploy(_client(), default="runsc-hostnet")["runtime"] == "runsc-hostnet"

    @pytest.mark.parametrize("mode", ["host", "none"])
    def test_host_and_none_networking_keep_dockers_default(self, mode):
        kwargs = _deploy(_client(), default="runsc-hostnet", slug="mysterium", network_mode=mode)
        assert kwargs["runtime"] is None

    def test_a_runtime_named_in_the_request_wins(self):
        kwargs = _deploy(_client(), default="runsc-hostnet", runtime="runsc-hostnet-raw")
        assert kwargs["runtime"] == "runsc-hostnet-raw"


class TestOverrides:
    def test_a_service_gets_its_own_runtime(self):
        kwargs = _deploy(
            _client(), default="runsc-hostnet", overrides="bitping=runsc-hostnet-raw", slug="bitping", image="b/b"
        )
        assert kwargs["runtime"] == "runsc-hostnet-raw"

    def test_other_services_keep_the_default(self):
        kwargs = _deploy(_client(), default="runsc-hostnet", overrides="bitping=runsc-hostnet-raw")
        assert kwargs["runtime"] == "runsc-hostnet"

    def test_runc_opts_a_service_out(self):
        kwargs = _deploy(_client(), default="runsc-hostnet", overrides=" honeygain = runc , ")
        assert kwargs["runtime"] == "runc"

    def test_an_override_works_without_a_default(self):
        kwargs = _deploy(_client(), overrides="honeygain=runsc-hostnet")
        assert kwargs["runtime"] == "runsc-hostnet"


class TestItIsRefusedBeforeAnythingIsTouched:
    def _refused(self, **kwargs):
        old = MagicMock()
        client = _client(old=old)
        with pytest.raises(orchestrator.ContainerRuntimeError) as err:
            _deploy(client, **kwargs)
        old.stop.assert_not_called()
        old.remove.assert_not_called()
        client.containers.run.assert_not_called()
        return err.value

    def test_a_runtime_the_daemon_lacks(self):
        err = self._refused(default="runsc")
        assert err.status_code == 409
        assert "'runsc'" in str(err)

    def test_an_override_the_daemon_lacks(self):
        err = self._refused(default="runsc-hostnet", overrides="honeygain=kata")
        assert "'kata'" in str(err)

    def test_a_malformed_override(self):
        err = self._refused(default="runsc-hostnet", overrides="bitping")
        assert err.status_code == 409
        assert "slug=runtime" in str(err)

    def test_a_daemon_that_cannot_be_asked(self):
        err = self._refused(default="runsc-hostnet", installed=None)
        assert err.status_code == 503


class TestTheWorkerApi:
    def _post(self, default, installed, old):
        client = _client(old=old)
        with (
            patch.object(orchestrator, "_CONTAINER_RUNTIME", default),
            patch.object(orchestrator, "_CONTAINER_RUNTIME_OVERRIDES", ""),
            patch.object(orchestrator, "_CONTAINER_NETWORK", ""),
            patch.object(orchestrator, "available_runtimes", return_value=installed),
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(worker_api, "_verify_api_key"),
            patch.object(worker_api, "_validate_deploy_spec"),
        ):
            return TestClient(worker_api.app).post("/api/containers/honeygain/deploy", json={"image": "x"})

    def test_a_missing_runtime_is_a_409_that_says_why(self):
        old = MagicMock()
        resp = self._post("runsc", INSTALLED, old)
        assert resp.status_code == 409, resp.text
        assert "runsc" in resp.json()["detail"]
        old.remove.assert_not_called()

    def test_an_unaskable_daemon_is_a_503(self):
        resp = self._post("runsc-hostnet", None, MagicMock())
        assert resp.status_code == 503, resp.text

    def test_the_runtimes_endpoint_reports_the_default(self):
        with (
            patch.object(orchestrator, "_CONTAINER_RUNTIME", "runsc-hostnet"),
            patch.object(orchestrator, "available_runtimes", return_value=INSTALLED),
            patch.object(worker_api, "_verify_api_key"),
        ):
            resp = TestClient(worker_api.app).get("/api/runtimes")
        assert resp.json()["default"] == "runsc-hostnet"
