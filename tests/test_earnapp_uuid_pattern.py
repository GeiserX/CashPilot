"""EARNAPP_UUID is checked at deploy, not only by the image.

drumsergio/cashpilot-earnapp refuses a UUID that is not sdk-node- plus 32
lowercase hex characters, and exits. Under a restart policy that is a loop, so
the deploy refuses the same values first and nothing reaches the worker.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest
from fastapi.testclient import TestClient

from app.main import app

GOOD = "sdk-node-" + "0123456789abcdef" * 2


@asynccontextmanager
async def _noop_lifespan(a):
    yield


app.router.lifespan_context = _noop_lifespan


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _deploy(client, uuid):
    worker = {"id": 1, "name": "w1", "status": "online", "url": "http://192.168.1.10:8081"}
    sent: dict = {}

    async def _fake_deploy(worker_id, slug, spec):
        sent.update(spec)
        return {"container_id": "abc123"}

    with (
        patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "admin", "r": "owner"}),
        patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
        patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
        patch("app.main.database.get_deployment_spec", new_callable=AsyncMock, return_value=None),
        patch("app.main._proxy_worker_deploy", side_effect=_fake_deploy),
        patch("app.main.database.save_deployment", new_callable=AsyncMock),
        patch("app.main.database.record_health_event", new_callable=AsyncMock),
        patch("app.main._run_collection", new_callable=AsyncMock),
    ):
        resp = client.post("/api/deploy/earnapp", json={"env": {"EARNAPP_UUID": uuid}})
    return resp, sent


@pytest.mark.parametrize("uuid", [GOOD, f" {GOOD}\n"])  # the form strips pasted whitespace
def test_a_uuid_as_earnapp_prints_it_deploys(client, uuid):
    resp, sent = _deploy(client, uuid)
    assert resp.status_code == 200, resp.text
    assert sent["env"]["EARNAPP_UUID"] == GOOD


@pytest.mark.parametrize(
    "uuid",
    [
        GOOD.upper().replace("SDK-NODE-", "sdk-node-"),  # uppercase hex: the image refuses it
        GOOD[:-1],  # 31 hex characters
        GOOD + "0",  # 33 hex characters
        GOOD.removeprefix("sdk-node-"),  # the bare hex, without the prefix
        "my-earnapp-node",
    ],
)
def test_a_uuid_the_image_would_refuse_never_reaches_the_worker(client, uuid):
    resp, sent = _deploy(client, uuid)
    assert resp.status_code == 400
    assert "Node UUID" in resp.json()["detail"]
    assert not sent, "nothing may reach the worker"
