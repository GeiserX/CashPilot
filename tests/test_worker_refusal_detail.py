"""A worker's refusal reaches the dashboard instead of "Worker request failed" (#508).

Every UI action that talks to a worker (deploy, redeploy, start, stop, restart,
remove, logs) goes through ``_proxy_to_worker``. These tests run that real proxy
with only httpx mocked, through the command route the dashboard uses.
"""

from __future__ import annotations

import json as _json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app as ui_app

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
def test_volume_refusal_names_the_path_and_the_fix(command):
    answer = _resp(403, {"detail": "Volume mount '/mnt/user/appdata/myst/data' is blocked"})
    resp = _send(command, answer=answer)
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert "Volume mount '/mnt/user/appdata/myst/data' is blocked" in detail
    assert "CASHPILOT_ALLOWED_VOLUME_ROOTS" in detail


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
