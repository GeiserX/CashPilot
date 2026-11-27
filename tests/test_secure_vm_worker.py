"""The Linux Secure VM's worker: how it reports itself, and how it is forgotten.

A Secure VM is a normal worker inside a fenced VM on the same host
(scripts/cashpilot-vm, docs/secure-vm.md). Two things are new:

* Its heartbeat carries ``system_info.secure_vm``: the host worker's name and
  the outer fence's last check, which the host's guard writes into the guest.
* ``cashpilot-vm remove`` asks the UI to forget it. The UI takes that only with
  the worker's own key, and only from a worker that said it is a Secure VM.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import worker_api
from app.main import app


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


class TestTheHeartbeatSaysItIsASecureVM:
    def test_nothing_outside_a_secure_vm(self, monkeypatch):
        monkeypatch.setattr(worker_api, "SECURE_VM_OF", "")
        assert worker_api._secure_vm_info() is None

    def test_the_host_and_the_guards_last_check(self, monkeypatch, tmp_path):
        fence = tmp_path / "fence.json"
        fence.write_text(json.dumps({"state": "ok", "reason": "match", "checked_at": 1795816133}))
        monkeypatch.setattr(worker_api, "SECURE_VM_OF", "nas")
        monkeypatch.setattr(worker_api, "SECURE_VM_FENCE_FILE", fence)
        monkeypatch.setattr(worker_api, "SECURE_VM_SELFTEST_FILE", tmp_path / "none.json")
        assert worker_api._secure_vm_info() == {
            "host": "nas",
            "fence": {"state": "ok", "checked_at": 1795816133, "reason": "match"},
            "selftest": None,
        }

    @pytest.mark.parametrize(
        "content",
        [
            None,  # the guard has not written it yet
            "not json",
            json.dumps(["ok"]),
            json.dumps({"state": "fine", "checked_at": 1}),
            json.dumps({"state": "ok", "checked_at": "soon"}),
            json.dumps({"state": "ok", "checked_at": True}),
        ],
    )
    def test_a_fence_state_it_cannot_read_is_unknown_not_ok(self, monkeypatch, tmp_path, content):
        fence = tmp_path / "fence.json"
        if content is not None:
            fence.write_text(content)
        monkeypatch.setattr(worker_api, "SECURE_VM_OF", "nas")
        monkeypatch.setattr(worker_api, "SECURE_VM_FENCE_FILE", fence)
        monkeypatch.setattr(worker_api, "SECURE_VM_SELFTEST_FILE", tmp_path / "none.json")
        assert worker_api._secure_vm_info() == {"host": "nas", "fence": None, "selftest": None}

    def test_the_reason_is_capped(self, monkeypatch, tmp_path):
        fence = tmp_path / "fence.json"
        fence.write_text(json.dumps({"state": "failed", "reason": "x" * 1000, "checked_at": 1}))
        monkeypatch.setattr(worker_api, "SECURE_VM_OF", "nas")
        monkeypatch.setattr(worker_api, "SECURE_VM_FENCE_FILE", fence)
        assert len(worker_api._secure_vm_info()["fence"]["reason"]) == 200

    def test_the_last_self_test(self, monkeypatch, tmp_path):
        result = tmp_path / "selftest.json"
        result.write_text(json.dumps({"ok": False, "checked_at": 5, "failed": ["FAIL  host 10.0.0.1:22 reached"] * 30}))
        monkeypatch.setattr(worker_api, "SECURE_VM_OF", "nas")
        monkeypatch.setattr(worker_api, "SECURE_VM_FENCE_FILE", tmp_path / "none.json")
        monkeypatch.setattr(worker_api, "SECURE_VM_SELFTEST_FILE", result)
        selftest = worker_api._secure_vm_info()["selftest"]
        assert selftest["ok"] is False and selftest["checked_at"] == 5
        assert len(selftest["failed"]) == 20

    def test_a_pass_with_failed_lines_is_not_a_pass(self, monkeypatch, tmp_path):
        result = tmp_path / "selftest.json"
        result.write_text(json.dumps({"ok": True, "checked_at": 5, "failed": ["FAIL  ui"]}))
        monkeypatch.setattr(worker_api, "SECURE_VM_OF", "nas")
        monkeypatch.setattr(worker_api, "SECURE_VM_SELFTEST_FILE", result)
        assert worker_api._secure_vm_info()["selftest"]["ok"] is False


class TestTheUICanAskForASelfTest:
    def test_it_leaves_a_request_for_the_host(self, monkeypatch, tmp_path):
        monkeypatch.setattr(worker_api, "SECURE_VM_OF", "nas")
        monkeypatch.setattr(worker_api, "SECURE_VM_ASK_DIR", tmp_path)
        monkeypatch.setattr(worker_api, "_verify_api_key", lambda request: None)
        resp = TestClient(worker_api.app).post("/api/secure-vm/selftest")
        assert resp.status_code == 200
        assert (tmp_path / "selftest").exists()

    def test_not_on_a_worker_that_is_not_a_secure_vm(self, monkeypatch, tmp_path):
        monkeypatch.setattr(worker_api, "SECURE_VM_OF", "")
        monkeypatch.setattr(worker_api, "SECURE_VM_ASK_DIR", tmp_path)
        monkeypatch.setattr(worker_api, "_verify_api_key", lambda request: None)
        resp = TestClient(worker_api.app).post("/api/secure-vm/selftest")
        assert resp.status_code == 404
        assert not (tmp_path / "selftest").exists()

    def test_it_needs_the_uis_key(self, monkeypatch, tmp_path):
        monkeypatch.setattr(worker_api, "SECURE_VM_OF", "nas")
        monkeypatch.setattr(worker_api, "SECURE_VM_ASK_DIR", tmp_path)
        monkeypatch.setattr(worker_api, "_active_key", lambda: "own-key")
        resp = TestClient(worker_api.app, raise_server_exceptions=False).post(
            "/api/secure-vm/selftest", headers={"Authorization": "Bearer wrong"}
        )
        assert resp.status_code == 401
        assert not (tmp_path / "selftest").exists()


def _retire(client, token="own-key", cid="vm-1"):
    return client.post(
        "/api/workers/retire",
        json={"client_id": cid},
        headers={"Authorization": f"Bearer {token}"},
    )


def _worker(system_info):
    return {"id": 7, "name": "nas-secure-vm", "system_info": json.dumps(system_info)}


class TestTheUIForgetsARemovedSecureVM:
    def test_its_own_key_and_a_secure_vm_report_delete_it(self, client):
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.get_worker_id", new_callable=AsyncMock, return_value=7),
            patch(
                "app.main.database.get_worker",
                new_callable=AsyncMock,
                return_value=_worker({"secure_vm": {"host": "nas"}}),
            ),
            patch("app.main.database.delete_worker", new_callable=AsyncMock) as delete,
        ):
            resp = _retire(client)
        assert resp.status_code == 200
        delete.assert_awaited_once_with(7)

    @pytest.mark.parametrize("state", ["enroll", "reissue"])
    def test_the_shared_key_cannot_retire_anyone(self, client, state):
        # Every worker holds the shared key, so it must not delete a worker.
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value=state),
            patch("app.main.database.delete_worker", new_callable=AsyncMock) as delete,
        ):
            resp = _retire(client, token="shared")
        assert resp.status_code == 403
        delete.assert_not_awaited()

    def test_a_bad_key_is_refused(self, client):
        with (
            patch(
                "app.main._authenticate_worker_heartbeat",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=401, detail="Invalid API key"),
            ),
            patch("app.main.database.delete_worker", new_callable=AsyncMock) as delete,
        ):
            resp = _retire(client, token="nope")
        assert resp.status_code == 401
        delete.assert_not_awaited()

    @pytest.mark.parametrize("info", [{}, {"secure_vm": None}, {"secure_vm": "nas"}])
    def test_a_worker_that_is_not_a_secure_vm_cannot_retire_itself(self, client, info):
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.get_worker_id", new_callable=AsyncMock, return_value=7),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=_worker(info)),
            patch("app.main.database.delete_worker", new_callable=AsyncMock) as delete,
        ):
            resp = _retire(client)
        assert resp.status_code == 403
        delete.assert_not_awaited()

    def test_an_unknown_worker_is_not_found(self, client):
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.get_worker_id", new_callable=AsyncMock, return_value=None),
            patch("app.main.database.delete_worker", new_callable=AsyncMock) as delete,
        ):
            resp = _retire(client)
        assert resp.status_code == 404
        delete.assert_not_awaited()


class TestTheGuestSideCommand:
    def test_it_signs_with_the_workers_own_key(self, monkeypatch):
        from app import worker_retire

        sent = {}

        class Resp:
            status_code = 200

        def fake_post(url, json, headers, timeout):
            sent.update(url=url, json=json, headers=headers)
            return Resp()

        monkeypatch.setattr(worker_api, "UI_URL", "http://ui:8080")
        monkeypatch.setattr(worker_api, "_ui_url_refusal", lambda: None)
        monkeypatch.setattr(worker_api, "_load_worker_key", lambda: "own-key")
        monkeypatch.setattr(worker_api, "CLIENT_ID", "vm-1")
        monkeypatch.setattr(worker_retire.httpx, "post", fake_post)
        assert worker_retire.retire() == (True, "the UI forgot this worker")
        assert sent == {
            "url": "http://ui:8080/api/workers/retire",
            "json": {"client_id": "vm-1"},
            "headers": {"Authorization": "Bearer own-key"},
        }

    def test_without_its_own_key_it_asks_nothing(self, monkeypatch):
        from app import worker_retire

        monkeypatch.setattr(worker_api, "UI_URL", "http://ui:8080")
        monkeypatch.setattr(worker_api, "_ui_url_refusal", lambda: None)
        monkeypatch.setattr(worker_api, "_load_worker_key", lambda: None)
        ok, message = worker_retire.retire()
        assert not ok
        assert "no key of its own" in message


class TestTheUIRoute:
    def test_the_owner_asks_the_worker(self, client):
        with (
            patch("app.main._require_owner"),
            patch("app.main._proxy_to_worker", new_callable=AsyncMock, return_value={"status": "asked"}) as proxy,
        ):
            resp = client.post("/api/workers/7/secure-vm/selftest")
        assert resp.status_code == 200
        proxy.assert_awaited_once_with(7, "POST", "/api/secure-vm/selftest", timeout=15)

    def test_nobody_else(self, client):
        with patch("app.main._proxy_to_worker", new_callable=AsyncMock) as proxy:
            resp = client.post("/api/workers/7/secure-vm/selftest")
        assert resp.status_code in (401, 403)
        proxy.assert_not_awaited()
