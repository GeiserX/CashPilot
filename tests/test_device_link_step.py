"""A deploy says how to link the device to the user's account.

EarnApp and ProxyRack pay a device only once its id is added to the user's
account by hand. A node left unlinked runs and earns for nobody, and two of
ours did for months. The deploy response carries the id, the link and the
steps from the catalog's ``device_link`` block, so the UI can show them where
the deploy succeeded.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest
from fastapi.testclient import TestClient

from app import catalog
from app.main import app

EARNAPP_UUID = "sdk-node-" + "0123456789abcdef" * 2
PROXYRACK_UUID = "ab" * 32


@asynccontextmanager
async def _noop_lifespan(a):
    yield


app.router.lifespan_context = _noop_lifespan


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _deploy(client, slug, env, recorded=None):
    worker = {"id": 1, "name": "w1", "status": "online", "url": "http://192.168.1.10:8081"}
    with (
        patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "admin", "r": "owner"}),
        patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
        patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
        patch("app.main.database.get_deployment_spec", new_callable=AsyncMock, return_value=recorded),
        patch("app.main._proxy_worker_deploy", new_callable=AsyncMock, return_value={"container_id": "abc"}),
        patch("app.main.database.save_deployment", new_callable=AsyncMock),
        patch("app.main.database.record_health_event", new_callable=AsyncMock),
        patch("app.main._run_collection", new_callable=AsyncMock),
    ):
        return client.post(f"/api/deploy/{slug}", json={"env": env})


def test_an_earnapp_deploy_returns_the_link_with_its_uuid(client):
    resp = _deploy(client, "earnapp", {"EARNAPP_UUID": EARNAPP_UUID})
    assert resp.status_code == 200, resp.text
    link = resp.json()["device_link"]
    assert link["id"] == EARNAPP_UUID
    assert link["url"] == f"https://earnapp.com/r/{EARNAPP_UUID}"
    assert "signed in" in link["steps"]


def test_a_proxyrack_deploy_returns_the_uuid_to_add_by_hand(client):
    resp = _deploy(client, "proxyrack", {"UUID": PROXYRACK_UUID})
    assert resp.status_code == 200, resp.text
    link = resp.json()["device_link"]
    assert link["id"] == PROXYRACK_UUID
    assert link["url"] == "https://peer.proxyrack.com"
    assert "Add device" in link["steps"]


def test_a_blank_redeploy_links_the_recorded_uuid(client):
    """The form posts blanks on a redeploy; the container keeps its recorded id."""
    recorded = {"image": "drumsergio/cashpilot-earnapp:1.665.73-r1", "env": {"EARNAPP_UUID": EARNAPP_UUID}}
    resp = _deploy(client, "earnapp", {"EARNAPP_UUID": ""}, recorded=recorded)
    assert resp.status_code == 200, resp.text
    assert resp.json()["device_link"]["id"] == EARNAPP_UUID


def test_a_service_with_nothing_to_link_returns_no_step(client):
    resp = _deploy(client, "honeygain", {"HONEYGAIN_EMAIL": "a@b.c", "HONEYGAIN_PASSWORD": "x"})
    assert resp.status_code == 200, resp.text
    assert "device_link" not in resp.json()


def test_the_id_is_url_encoded_into_the_link():
    svc = {"device_link": {"id_env": "ID", "url": "https://x.test/r/${ID}", "steps": "Open it."}}
    assert catalog.device_link_step(svc, {"ID": "a/b c"})["url"] == "https://x.test/r/a%2Fb%20c"
    assert catalog.device_link_step(svc, {"ID": ""}) is None


def _errors(tmp_path: Path, link) -> list[str]:
    data = {
        "name": "X",
        "slug": "x",
        "category": "bandwidth",
        "status": "active",
        "description": "x",
        "docker": {"image": "x/x:1", "env": [{"key": "ID"}, {"key": "TOKEN", "secret": True}]},
        "device_link": link,
    }
    return catalog._validate(data, tmp_path / "x.yml")


def test_the_loader_accepts_a_well_formed_block(tmp_path):
    assert _errors(tmp_path, {"id_env": "ID", "url": "https://x.test/${ID}", "steps": "Open it."}) == []


@pytest.mark.parametrize(
    "link",
    [
        {"id_env": "TOKEN", "steps": "Open it."},  # a secret must never be shown or put in a link
        {"id_env": "NOPE", "steps": "Open it."},  # not a declared env var
        {"id_env": "ID", "steps": ""},  # no instructions
        {"id_env": "ID", "url": "http://x.test", "steps": "Open it."},  # not https
        "EARNAPP_UUID",  # not a mapping
    ],
)
def test_the_loader_refuses_a_malformed_block(tmp_path, link):
    assert any("device_link" in e for e in _errors(tmp_path, link))
