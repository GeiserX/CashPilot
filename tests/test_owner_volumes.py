"""Behind owner isolation a container may only name a volume that exists and
carries the worker's label, so deploy_raw creates each named volume through the
proxy first, and refuses one an older release made, before touching anything."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app import orchestrator
from tests.test_socket_proxy import SOCKGUARD_403, _api_error

VOLUMES = {"mysterium-data": {"bind": "/var/lib/mysterium-node", "mode": "rw"}, "/srv/x": {"bind": "/x", "mode": "rw"}}


def _client(old=None):
    client = MagicMock()
    if old is None:
        client.containers.get.side_effect = orchestrator.NotFound("nope")
    else:
        client.containers.get.return_value = old
    client.containers.run.return_value = MagicMock(id="cid")
    return client


def _deploy(client, **kwargs):
    with patch.object(orchestrator, "_get_client", return_value=client):
        return orchestrator.deploy_raw(slug="mysterium", image="img", **kwargs)


def test_a_missing_named_volume_is_created_before_the_container():
    client = _client()
    client.volumes.get.side_effect = orchestrator.NotFound("no volume")
    calls = []
    client.volumes.create.side_effect = lambda name: calls.append(("create", name))
    client.containers.run.side_effect = lambda **kw: calls.append(("run", kw["name"])) or MagicMock(id="cid")
    _deploy(client, volumes=VOLUMES)
    # Only the named volume: a host folder is not a volume.
    assert calls == [("create", "mysterium-data"), ("run", "cashpilot-mysterium")]


def test_an_existing_volume_is_used_as_it_is():
    client = _client()
    _deploy(client, volumes=VOLUMES)
    client.volumes.get.assert_called_with("mysterium-data")
    client.volumes.create.assert_not_called()


def test_a_volume_the_proxy_will_not_let_the_worker_use_stops_the_redeploy_before_the_node_is_touched():
    old = MagicMock()
    old.labels = {"cashpilot.service": "mysterium"}
    old.attrs = {"Mounts": [{"Type": "volume", "Name": "mysterium-data", "Destination": "/var/lib/mysterium-node"}]}
    client = _client(old)
    client.volumes.get.side_effect = _api_error(
        403, {**SOCKGUARD_403, "reason": "owner policy denied access to volume"}
    )
    with pytest.raises(orchestrator.ContainerRuntimeError) as err:
        _deploy(client, volumes=VOLUMES)
    assert "was not made by this worker" in str(err.value)
    assert "cashpilot-migrate" in str(err.value)
    old.stop.assert_not_called()
    old.remove.assert_not_called()
    client.containers.run.assert_not_called()


def test_behind_a_proxy_from_an_older_compose_file_docker_still_makes_the_volume():
    # That policy refuses the volume create call and has no owner isolation.
    client = _client()
    client.volumes.get.side_effect = orchestrator.NotFound("no volume")
    client.volumes.create.side_effect = _api_error(
        403, {**SOCKGUARD_403, "reason": "the CashPilot worker does not use this Docker API call"}
    )
    _deploy(client, volumes=VOLUMES)
    client.containers.run.assert_called_once()


def test_any_other_docker_error_is_not_dressed_up_as_a_proxy_refusal():
    client = _client()
    client.volumes.get.side_effect = _api_error(500, {"message": "daemon broke"})
    with pytest.raises(orchestrator.APIError):
        _deploy(client, volumes=VOLUMES)


def _info(ui_error):
    client = MagicMock()

    def get(name):
        if name == "cashpilot-ui":
            raise ui_error
        raise orchestrator.NotFound(name)

    client.containers.get.side_effect = get
    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        patch.object(orchestrator, "_self_container", return_value=None),
    ):
        return orchestrator.self_update_info()


def test_the_update_card_says_the_dashboard_on_this_server_is_updated_by_hand():
    info = _info(_api_error(403, {**SOCKGUARD_403, "reason": "owner policy denied access to container"}))
    assert info["ui_by_hand"] is True
    assert info["ui_image"] == ""


def test_a_server_without_a_dashboard_says_nothing_about_it():
    assert "ui_by_hand" not in _info(orchestrator.NotFound("no such container"))


def test_activity_asks_nothing_more_of_a_daemon_that_failed():
    from app import activity

    client = MagicMock()
    client.networks.get.side_effect = _api_error(500, {"message": "daemon stalled"})
    assert activity._network_info(client, "n1", {"cashpilot-honeygain"}) == ("", [])
    client.containers.get.assert_not_called()


def test_activity_knows_the_earners_on_the_default_bridge_it_may_not_inspect():
    from app import activity

    client = MagicMock()
    client.networks.get.side_effect = _api_error(
        403, {**SOCKGUARD_403, "reason": "owner policy denied access to network"}
    )
    earner = MagicMock()
    earner.attrs = {
        "NetworkSettings": {
            "Networks": {
                "bridge": {"NetworkID": "n1", "IPAddress": "172.17.0.3"},
                "other": {"NetworkID": "n2", "IPAddress": "10.0.0.9"},
            }
        }
    }
    client.containers.get.return_value = earner
    # Otherwise every other earner beside it would read as a stranger on the bridge.
    assert activity._network_info(client, "n1", {"cashpilot-honeygain"}) == ("", ["172.17.0.3"])
