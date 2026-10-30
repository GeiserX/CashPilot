"""A Mysterium node CashPilot deploys uses the UDP range its guide says to forward.

The guide and the catalog notes said to forward UDP 56000-56100, but the
deploy command never passed --udp.ports, so the node picked ports from its
default 10000:60000. The forward was never used and every session fell back to
hole punching (325 sessions in 24 h on three nodes, none direct). UDP_PORTS puts
the range on the command line, defaulting to the one the guide names.
"""

from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

from app import compose_generator
from tests.test_mysterium_ui_address import _deploy, _record, app


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_a_first_deploy_uses_the_range_the_guide_says_to_forward(client):
    resp, sent = _deploy(client, {"env": {}})
    assert resp.status_code == 200, resp.text
    assert " --udp.ports=56000:56100 service " in sent["command"]


def test_a_node_deployed_before_the_setting_existed_gets_the_default(client):
    resp, sent = _deploy(client, {"env": {}}, recorded=_record({"UI_ADDRESS": "127.0.0.1"}))
    assert resp.status_code == 200, resp.text
    assert " --udp.ports=56000:56100 service " in sent["command"]


def test_a_typed_range_reaches_the_node(client):
    resp, sent = _deploy(client, {"env": {"UDP_PORTS": "41000:41050"}})
    assert resp.status_code == 200, resp.text
    assert " --udp.ports=41000:41050 service " in sent["command"]


def test_a_blank_redeploy_keeps_the_range_this_machine_was_given(client):
    recorded = _record({"UDP_PORTS": "41000:41050"})
    for env in ({}, {"UDP_PORTS": ""}, {"UDP_PORTS": "56000:56100"}):
        resp, sent = _deploy(client, {"env": env}, recorded=recorded)
        assert resp.status_code == 200, resp.text
        assert " --udp.ports=41000:41050 service " in sent["command"]


@pytest.mark.parametrize(
    "value",
    [
        "56100:56000",  # reversed: the node refuses to start
        "56000:70000",  # past 65535
        "56000-56100",  # the guide's spelling, not the node's
        "56000:56100 --ui.address=0.0.0.0",  # a second flag smuggled onto the command line
        "56000",
        "٥٦٠٠٠:٥٦١٠٠",  # Arabic-Indic digits
    ],
)
def test_anything_but_a_port_range_is_refused_before_a_deploy(client, value):
    resp, sent = _deploy(client, {"env": {"UDP_PORTS": value}})
    assert resp.status_code == 400
    assert "UDP port range" in resp.json()["detail"]
    assert not sent, "nothing may reach the worker"


def test_a_recorded_reversed_range_is_refused_too(client):
    resp, sent = _deploy(client, {"env": {}}, recorded=_record({"UDP_PORTS": "56100:56000"}))
    assert resp.status_code == 400
    assert not sent


def test_the_exported_compose_file_uses_the_default_range():
    exported = yaml.safe_load(compose_generator.generate_compose_single("mysterium"))
    assert " --udp.ports=56000:56100 service " in exported["services"]["cashpilot-mysterium"]["command"]
