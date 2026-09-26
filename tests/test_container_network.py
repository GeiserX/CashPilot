"""Earners can run on a bridge the operator firewalled off the LAN.

The isolation advice asked people to put the managed containers on their own
bridge and firewall that interface, but a worker deploy always used Docker's
default bridge, so the advice could not be applied to anything CashPilot
deployed. The snippet it handed out also named the interface
"cashpilot-isolated", which Linux refuses (15 characters at most), so Docker
could not even create that network.

CASHPILOT_CONTAINER_NETWORK names a bridge the operator created; containers that
would land on the default bridge join it instead. The worker never creates it,
and refuses a deploy while it is missing, before the running container is
touched.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import lan_isolation, orchestrator, worker_api


def _client(networks=None, old=None):
    """A mocked Docker client with the given networks by name and an optional running container."""
    networks = networks or {}
    client = MagicMock()

    def _net(name):
        if name not in networks:
            raise orchestrator.NotFound("no such network")
        net = MagicMock()
        net.attrs = {"Driver": networks[name]}
        return net

    client.networks.get.side_effect = _net
    if old is None:
        client.containers.get.side_effect = orchestrator.NotFound("nope")
    else:
        client.containers.get.return_value = old
    created = MagicMock()
    created.id = "new"
    created.short_id = "new"
    client.containers.run.return_value = created
    return client


def _deploy(client, network_setting, network_mode=None):
    with (
        patch.object(orchestrator, "_CONTAINER_NETWORK", network_setting),
        patch.object(orchestrator, "_get_client", return_value=client),
    ):
        orchestrator.deploy_raw(slug="honeygain", image="honeygain/honeygain", network_mode=network_mode)
    return client.containers.run.call_args.kwargs


class TestTheSetting:
    def test_unset_keeps_dockers_default_bridge(self):
        kwargs = _deploy(_client(), "")
        assert kwargs["network"] is None
        assert kwargs["network_mode"] is None

    def test_set_joins_the_operators_bridge(self):
        kwargs = _deploy(_client({"cashpilot-isolated": "bridge"}), "cashpilot-isolated")
        assert kwargs["network"] == "cashpilot-isolated"
        assert kwargs["network_mode"] is None, "docker-py refuses network and network_mode together"

    @pytest.mark.parametrize("mode", ["host", "none"])
    def test_host_and_none_networking_are_left_alone(self, mode):
        kwargs = _deploy(_client({"cashpilot-isolated": "bridge"}), "cashpilot-isolated", network_mode=mode)
        assert kwargs["network"] is None
        assert kwargs["network_mode"] == mode


class TestItIsRefusedBeforeAnythingIsTouched:
    def test_a_missing_network_leaves_the_running_container_alone(self):
        old = MagicMock()
        client = _client({}, old=old)
        with pytest.raises(orchestrator.ContainerNetworkError, match="docker network create"):
            _deploy(client, "cashpilot-isolated")
        old.stop.assert_not_called()
        old.remove.assert_not_called()
        client.containers.run.assert_not_called()

    def test_a_network_that_is_not_a_bridge_is_refused(self):
        with pytest.raises(orchestrator.ContainerNetworkError, match="macvlan"):
            _deploy(_client({"cashpilot-isolated": "macvlan"}), "cashpilot-isolated")

    def test_the_worker_answers_409_with_the_fix(self):
        """The operator's own setting, so the answer names it instead of a bare 500."""
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(worker_api, "_validate_deploy_spec"),
            patch.object(
                worker_api.orchestrator,
                "deploy_raw",
                side_effect=orchestrator.ContainerNetworkError("CASHPILOT_CONTAINER_NETWORK is 'x' ... create it"),
            ),
        ):
            resp = TestClient(worker_api.app).post("/api/containers/honeygain/deploy", json={"image": "x"})
        assert resp.status_code == 409
        assert "CASHPILOT_CONTAINER_NETWORK" in resp.json()["detail"]


class TestTheSnippetIsOneDockerAccepts:
    def test_the_bridge_interface_fits_linuxs_limit(self):
        assert len(lan_isolation.BRIDGE_INTERFACE) <= 15

    def test_the_snippet_names_that_interface(self):
        snippet = lan_isolation.compose_snippet()
        assert f'com.docker.network.bridge.name: "{lan_isolation.BRIDGE_INTERFACE}"' in snippet
        assert 'bridge.name: "cashpilot-isolated"' not in snippet
