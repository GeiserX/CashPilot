"""The Mysterium WebUI address is a per-machine setting, loopback by default.

1.37.4 bound the node's WebUI to 127.0.0.1 so host networking stopped
publishing it on every interface. That also cut off any reverse proxy in front
of it, and the command had no way to say "loopback, plus the one address my
proxy connects to". UI_ADDRESS is that way: the default is unchanged, and the
value is checked before it reaches the command line, where a stray space turns
into an argument and the node refuses to start.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest
import yaml
from fastapi.testclient import TestClient

from app import catalog, compose_generator
from app.main import app

LOOPBACK = "--ui.address=127.0.0.1 --tequilapi.address=127.0.0.1 service --agreed-terms-and-conditions"


@asynccontextmanager
async def _noop_lifespan(a):
    yield


app.router.lifespan_context = _noop_lifespan


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _deploy(client, body, recorded=None):
    """Deploy the REAL catalog entry; return (response, spec sent to the worker)."""
    worker = {"id": 1, "name": "w1", "status": "online", "url": "http://192.168.1.10:8081"}
    sent: dict = {}

    async def _fake_deploy(worker_id, slug, spec):
        sent.update(spec)
        return {"container_id": "abc123"}

    with (
        patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "admin", "r": "owner"}),
        patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
        patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
        patch("app.main.database.get_deployment_spec", new_callable=AsyncMock, return_value=recorded),
        patch("app.main._proxy_worker_deploy", side_effect=_fake_deploy),
        patch("app.main.database.save_deployment", new_callable=AsyncMock),
        patch("app.main.database.record_health_event", new_callable=AsyncMock),
        patch("app.main._run_collection", new_callable=AsyncMock),
    ):
        resp = client.post("/api/deploy/mysterium", json=body)
    return resp, sent


def _record(env):
    return {"image": "mysteriumnetwork/myst", "env": env, "command": LOOPBACK}


def test_a_first_deploy_stays_on_loopback(client):
    resp, sent = _deploy(client, {"env": {}})
    assert resp.status_code == 200, resp.text
    assert sent["command"] == LOOPBACK


def test_the_form_posting_its_prefilled_default_stays_on_loopback(client):
    resp, sent = _deploy(client, {"env": {"UI_ADDRESS": "127.0.0.1"}})
    assert resp.status_code == 200, resp.text
    assert sent["command"] == LOOPBACK


def test_a_node_deployed_before_the_setting_existed_stays_on_loopback(client):
    """The 1.37.4 fleet: recorded env has no UI_ADDRESS at all."""
    resp, sent = _deploy(client, {"env": {}}, recorded=_record({}))
    assert resp.status_code == 200, resp.text
    assert sent["command"] == LOOPBACK


def test_an_added_address_reaches_the_webui_and_never_the_api(client):
    resp, sent = _deploy(client, {"env": {"UI_ADDRESS": "127.0.0.1,172.18.0.1"}})
    assert resp.status_code == 200, resp.text
    assert sent["command"] == (
        "--ui.address=127.0.0.1,172.18.0.1 --tequilapi.address=127.0.0.1 service --agreed-terms-and-conditions"
    )


def test_a_blank_redeploy_keeps_the_address_this_machine_was_given(client):
    resp, sent = _deploy(client, {"env": {}}, recorded=_record({"UI_ADDRESS": "127.0.0.1,172.18.0.1"}))
    assert resp.status_code == 200, resp.text
    assert "--ui.address=127.0.0.1,172.18.0.1 " in sent["command"]


def test_localhost_takes_a_machine_back_to_loopback(client):
    """The way out: the prefilled 127.0.0.1 is not a decision, so it cannot undo one."""
    recorded = _record({"UI_ADDRESS": "127.0.0.1,172.18.0.1"})
    resp, sent = _deploy(client, {"env": {"UI_ADDRESS": "127.0.0.1"}}, recorded=recorded)
    assert "--ui.address=127.0.0.1,172.18.0.1 " in sent["command"]

    resp, sent = _deploy(client, {"env": {"UI_ADDRESS": "localhost"}}, recorded=recorded)
    assert resp.status_code == 200, resp.text
    assert sent["command"].startswith("--ui.address=localhost --tequilapi.address=127.0.0.1 ")


@pytest.mark.parametrize(
    "value",
    [
        "127.0.0.1, 172.18.0.1",  # a space: "172.18.0.1" becomes the node's subcommand
        "127.0.0.1 --tequilapi.address=0.0.0.0",  # a second flag smuggled onto the command line
        "127.0.0.1,",
        "172.18.0.1;reboot",
        "::1",  # the node formats "<addr>:<port>" without brackets, so IPv6 never binds
        "256.0.0.1",  # not an address: the WebUI listener fails to bind while the node runs on
        "127.0.0.1,999.999.999.999",
        "127.0.0.01",  # a leading zero is not how the node parses an octet
    ],
)
def test_anything_but_addresses_is_refused_before_a_deploy(client, value):
    resp, sent = _deploy(client, {"env": {"UI_ADDRESS": value}})
    assert resp.status_code == 400
    assert "WebUI address" in resp.json()["detail"]
    assert not sent, "nothing may reach the worker"


def test_the_exported_compose_file_stays_on_loopback():
    exported = yaml.safe_load(compose_generator.generate_compose_single("mysterium"))
    service = exported["services"]["cashpilot-mysterium"]
    assert service["command"] == LOOPBACK


def test_a_pattern_that_does_not_compile_is_a_catalog_error(tmp_path):
    entry = {
        "name": "X",
        "slug": "x",
        "category": "bandwidth",
        "status": "active",
        "website": "https://example.com",
        "description": "x",
        "docker": {"image": "x/x", "env": [{"key": "A", "pattern": "(unclosed"}]},
    }
    missing = catalog._REQUIRED_FIELDS - set(entry)
    entry.update({field: "x" for field in missing})
    errors = catalog._validate(entry, tmp_path / "x.yml")
    assert any("pattern" in e for e in errors)
    entry["docker"]["env"][0]["pattern"] = "[a-z]+"
    assert not catalog._validate(entry, tmp_path / "x.yml")
