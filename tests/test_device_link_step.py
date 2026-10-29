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


def _deploy(client, slug, env, recorded=None, config=None):
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
        patch("app.main.database.get_config", new_callable=AsyncMock, return_value=config or {}),
    ):
        return client.post(f"/api/deploy/{slug}", json={"env": env})


def test_an_earnapp_deploy_returns_the_link_with_its_uuid(client):
    resp = _deploy(client, "earnapp", {"EARNAPP_UUID": EARNAPP_UUID})
    assert resp.status_code == 200, resp.text
    link = resp.json()["device_link"]
    assert link["id"] == EARNAPP_UUID
    assert link["url"] == f"https://earnapp.com/r/{EARNAPP_UUID}"
    assert "signed in" in link["steps"]
    assert link["registered"] is False  # EarnApp has no API for it: the manual step stays


def test_a_proxyrack_deploy_returns_the_uuid_to_add_by_hand(client):
    resp = _deploy(client, "proxyrack", {"UUID": PROXYRACK_UUID})
    assert resp.status_code == 200, resp.text
    link = resp.json()["device_link"]
    assert link["id"] == PROXYRACK_UUID
    assert link["url"] == "https://peer.proxyrack.com"
    assert "Add device" in link["steps"]
    assert link["registered"] is False  # no ProxyRack API key saved


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
        "docker": {
            "image": "x/x:1",
            "env": [
                {"key": "ID"},
                {"key": "TOKEN", "secret": True},
                {"key": "TWICE"},
                {"key": "TWICE", "secret": True},
            ],
        },
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
        {"id_env": "ID", "url": "https://x.test/${TOKEN}", "steps": "Open it."},  # a secret in the link
        {"id_env": "ID", "url": "https://x.test/${NOPE}", "steps": "Open it."},  # an undeclared placeholder
        {"id_env": "TWICE", "steps": "Open it."},  # declared twice, once secret: secret
        "EARNAPP_UUID",  # not a mapping
    ],
)
def test_the_loader_refuses_a_malformed_block(tmp_path, link):
    assert any("device_link" in e for e in _errors(tmp_path, link))


# ProxyRack's peer API adds a device itself (POST /api/device/add), so with the
# collector's API key saved the deploy registers the UUID instead of asking the
# user to. Answers below are the shapes the API returned on 2026-10-29.
def _proxyrack_api(answers):
    """An httpx client stand-in that answers each POST from ``answers`` by path."""
    from unittest.mock import MagicMock

    calls = []

    async def post(url, headers=None, json=None):
        calls.append((url.rsplit("/api", 1)[1], json, headers))
        status, body = answers[url.rsplit("/api", 1)[1]]
        resp = MagicMock()
        resp.status_code = status
        resp.json.return_value = body
        return resp

    client = AsyncMock()
    client.is_closed = False
    client.post.side_effect = post
    return client, calls


ADDED = (200, {"status": "success", "message": "Device added successfully", "data": {}})
REFUSED = (400, {"status": "error", "error": "Invalid request parameters", "details": {"device_id": "taken"}})
KNOWN = (200, {"status": "success", "data": {"device_id": PROXYRACK_UUID, "status": "Offline"}})
LIMITED = (429, {"status": "error", "error": "Requests limit exceeded (5 per minute)."})


def _pr_deploy(client, answers):
    api, calls = _proxyrack_api(answers)
    with patch("app.collectors.proxyrack.httpx.AsyncClient", return_value=api):
        resp = _deploy(
            client, "proxyrack", {"UUID": PROXYRACK_UUID, "DEVICE_NAME": "box"}, config={"proxyrack_api_key": "k"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["device_link"], calls


def test_with_an_api_key_the_proxyrack_device_is_added_for_the_user(client):
    link, calls = _pr_deploy(client, {"/device/add": ADDED})
    assert link["registered"] is True
    path, body, headers = calls[0]
    assert path == "/device/add"
    assert body == {"device_id": PROXYRACK_UUID, "device_name": "box"}
    assert headers["User-Agent"] and headers["Api-Key"] == "k"


def test_a_redeploy_of_a_device_already_on_the_account_counts_as_added(client):
    link, calls = _pr_deploy(client, {"/device/add": REFUSED, "/device/status": KNOWN})
    assert link["registered"] is True
    assert [c[0] for c in calls] == ["/device/add", "/device/status"]


def test_a_rate_limited_add_leaves_the_manual_step(client):
    link, _ = _pr_deploy(client, {"/device/add": LIMITED, "/device/status": LIMITED})
    assert link["registered"] is False


def test_a_deleted_workers_device_ids_are_not_checked(tmp_path, monkeypatch):
    """Deleting a worker leaves its spec rows; its device is nobody's to report."""
    import asyncio

    from app import database

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "cashpilot.db")

    async def run():
        await database.init_db()
        live = await database.upsert_worker("client-live", name="w1")
        for worker_id, uuid in ((live, "live-node"), (live + 1, "orphan-node")):
            await database.save_deployment(
                slug="earnapp", container_id="c", spec={"env": {"EARNAPP_UUID": uuid}}, worker_id=worker_id
            )
        return await database.get_deployed_env_values("earnapp", "EARNAPP_UUID")

    assert asyncio.run(run()) == {"live-node"}
