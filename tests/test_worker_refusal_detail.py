"""A worker's refusal reaches the dashboard instead of "Worker request failed" (#508).

Every UI action that talks to a worker (deploy, redeploy, start, stop, restart,
remove, logs) goes through ``_proxy_to_worker``. These tests run that real proxy
with only httpx mocked, through the command route the dashboard uses.
"""

from __future__ import annotations

import json as _json
import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

# Same key as the other worker suites, set before app.worker_api is first imported.
os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

from docker.errors import APIError  # noqa: E402

from app import worker_api  # noqa: E402
from app.main import app as ui_app  # noqa: E402

WORKER = {"id": 1, "name": "w1", "status": "online", "url": "http://192.168.1.10:8081"}


@asynccontextmanager
async def _noop_lifespan(a):
    yield


def _client():
    ui_app.router.lifespan_context = _noop_lifespan
    return TestClient(ui_app, raise_server_exceptions=False)


def _resp(status: int, body: object | None = None, text: str | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    if body is not None:
        resp.json.return_value = body
        resp.text = _json.dumps(body)
    else:
        resp.json.side_effect = ValueError("not JSON")
        resp.text = text or ""
    return resp


def _send(command: str, *, answer: MagicMock | None = None, raises: Exception | None = None, spec=None):
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    for verb in ("get", "post", "delete"):
        method = getattr(mock_client, verb)
        if raises is not None:
            method.side_effect = raises
        else:
            method.return_value = answer
    with (
        patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "admin", "r": "owner"}),
        patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=WORKER),
        patch("app.main.httpx.AsyncClient", return_value=mock_client),
        patch("app.main.FLEET_API_KEY", "test-key"),
    ):
        return _client().post(
            "/api/workers/1/command",
            json={"command": command, "slug": "mysterium", "spec": spec or {}},
        )


@pytest.mark.parametrize("command", ["deploy", "start", "stop", "restart", "remove"])
def test_volume_refusal_reaches_the_dashboard_as_written(command):
    reason = (
        "Volume mount '/mnt/user/appdata/myst/data' is blocked. To allow it, add the path to "
        "CASHPILOT_ALLOWED_VOLUME_ROOTS on this worker and restart it"
    )
    resp = _send(command, answer=_resp(403, {"detail": reason}))
    assert resp.status_code == 403
    assert resp.json()["detail"] == reason


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 503])
def test_each_vetted_status_forwards_the_worker_text(status):
    resp = _send("deploy", answer=_resp(status, {"detail": "the worker's own reason"}))
    assert resp.status_code == status
    assert resp.json()["detail"] == "the worker's own reason"


def test_control_characters_are_dropped():
    resp = _send("deploy", answer=_resp(403, {"detail": "Blocked\x1b[31m devices: /dev/kvm\x07"}))
    detail = resp.json()["detail"]
    assert "\x1b" not in detail and "\x07" not in detail
    assert detail == "Blocked[31m devices: /dev/kvm"


def test_short_env_values_do_not_garble_the_reason():
    reason = "oom_score_adj must be between -1000 and 1000; network mode 'host' is not allowed"
    spec = {"image": "a", "env": {"PUID": "1000", "MODE": "host"}}
    resp = _send("deploy", answer=_resp(400, {"detail": reason}), spec=spec)
    assert resp.json()["detail"] == reason


def test_fastapi_not_found_says_the_worker_may_be_older():
    resp = _send("remove", answer=_resp(404, {"detail": "Not Found"}))
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail != "Not Found"
    assert "older than the UI" in detail


@pytest.mark.parametrize("exc", [httpx.ConnectTimeout("syn lost"), httpx.PoolTimeout("pool full")])
def test_connect_and_pool_timeouts_never_reached_the_worker(exc):
    resp = _send("restart", raises=exc)
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Worker communication failed"


def test_init_image_refusal_is_forwarded():
    reason = (
        "venatum/earnapp:latest runs an init system as its main process (/sbin/init, usually systemd), "
        "which needs a privileged container with the host's cgroup tree."
    )
    resp = _send("deploy", answer=_resp(409, {"detail": reason}))
    assert resp.status_code == 409
    assert resp.json()["detail"] == reason


def test_forwarded_text_masks_env_values_and_is_capped():
    secret = "s3cr3t-token-value"
    reason = f"Blocked capabilities: NET_ADMIN token={secret}\n" + "x" * 2000
    resp = _send("deploy", answer=_resp(403, {"detail": reason}), spec={"image": "a", "env": {"TOKEN": secret}})
    detail = resp.json()["detail"]
    assert secret not in detail
    assert "Blocked capabilities: NET_ADMIN" in detail
    assert "\n" not in detail
    assert len(detail) <= 400


def test_unhandled_500_text_stays_generic_but_says_the_status():
    resp = _send("deploy", answer=_resp(500, {"detail": "secret-laden arbitrary worker error"}))
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert "secret-laden" not in detail
    assert "HTTP 500" in detail


def test_validation_422_echo_is_not_forwarded():
    # FastAPI's 422 detail echoes the request body, env values included.
    body = {"detail": [{"loc": ["body", "env"], "input": {"TOKEN": "live-credential"}}]}
    resp = _send("deploy", answer=_resp(422, body))
    assert "live-credential" not in _json.dumps(resp.json())


def test_non_json_error_body_is_reported_with_its_status():
    resp = _send("stop", answer=_resp(502, text="<html>Bad Gateway from some proxy</html>"))
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "HTTP 502" in detail
    assert "<html>" not in detail


def test_timeout_says_the_worker_did_not_answer():
    resp = _send("restart", raises=httpx.ReadTimeout("timed out"))
    assert resp.status_code == 504
    assert "did not answer within 30 s" in resp.json()["detail"]


def test_unreachable_worker_still_reads_communication_failed():
    resp = _send("restart", raises=httpx.ConnectError("refused"))
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Worker communication failed"


# -- the worker side: what it writes into those refusals ---------------------


def _worker_client():
    worker_api.app.router.lifespan_context = _noop_lifespan
    return TestClient(worker_api.app, raise_server_exceptions=False)


def _worker_deploy(spec: dict, **patches):
    with patch("app.worker_api._verify_api_key"), patch("app.worker_api.orchestrator.deploy_raw", **patches):
        return _worker_client().post("/api/containers/honeygain/deploy", json=spec)


def test_docker_refusal_is_a_409_with_its_explanation():
    err = APIError(
        "500 Server Error",
        explanation="driver failed programming external connectivity: Bind for 0.0.0.0:4449 failed:\n"
        "port is already allocated",
    )
    resp = _worker_deploy({"image": "img"}, side_effect=err)
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail.startswith("Docker refused the container: ")
    assert "port is already allocated" in detail
    assert "\n" not in detail


def test_unexpected_deploy_failure_stays_a_generic_500():
    resp = _worker_deploy({"image": "img"}, side_effect=Exception("boom"))
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Container deployment failed"


def test_blocked_volume_names_the_allowlist_when_it_can_work():
    resp = _worker_deploy({"image": "img", "volumes": {"/mnt/user/appdata/myst/data": {"bind": "/d"}}})
    assert resp.status_code == 403
    assert resp.json()["detail"] == (
        "Volume mount '/mnt/user/appdata/myst/data' is blocked. To allow it, add the path to "
        "CASHPILOT_ALLOWED_VOLUME_ROOTS on this worker and restart it"
    )


@pytest.mark.parametrize("path", ["/root/myst", "/mnt/user"])
def test_blocked_volume_never_suggests_an_allowlist_the_worker_refuses(path):
    resp = _worker_deploy({"image": "img", "volumes": {path: {"bind": "/d"}}})
    assert resp.status_code == 403
    assert resp.json()["detail"] == f"Volume mount '{path}' is blocked"
