"""Settings > Credential encryption key and Earner credentials: the routes (app/routers/credential_storage.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import database, deps, main

OWNER = {"uid": 1, "u": "owner", "r": "owner"}


def _client():
    return TestClient(main.app)


def _status(**over):
    base = {
        "source": "data",
        "file": None,
        "data_file": "/data/.fernet_key",
        "data_copy": "same",
        "env_same": False,
        "outside": False,
        "removable": False,
    }
    return {**base, **over}


def test_the_status_never_carries_the_key():
    with patch.object(deps, "_require_owner", lambda r: OWNER):
        body = _client().get("/api/settings/encryption-key").json()
    assert set(body) == {"source", "file", "data_file", "data_copy", "env_same", "outside", "removable"}
    assert database.encryption_key_value() not in str(body)


def test_the_status_is_owner_only():
    def refuse(request):
        raise HTTPException(status_code=403, detail="owner only")

    with patch.object(deps, "_require_owner", refuse):
        assert _client().get("/api/settings/encryption-key").status_code == 403
        assert _client().post("/api/settings/encryption-key/reveal", json={}).status_code == 403


def test_the_reveal_asks_for_the_password_first():
    with (
        patch.object(deps, "_require_owner", lambda r: OWNER),
        patch.object(database, "add_audit_event", AsyncMock()) as audit,
    ):
        res = _client().post("/api/settings/encryption-key/reveal", json={})
    assert res.status_code == 403 and res.json()["detail"]["error"] == "step_up_required"
    assert "key" not in res.json()
    audit.assert_not_awaited()


def test_the_reveal_gives_the_key_after_the_password_and_an_audit_row():
    with (
        patch.object(deps, "_require_owner", lambda r: OWNER),
        patch.object(deps, "require_step_up", AsyncMock(return_value=OWNER)) as step_up_,
        patch.object(database, "add_audit_event", AsyncMock()) as audit,
    ):
        res = _client().post("/api/settings/encryption-key/reveal", json={"step_up_password": "pw"})
    assert res.status_code == 200 and res.json() == {"key": database.encryption_key_value()}
    assert res.headers["cache-control"] == "no-store"
    assert step_up_.await_args.kwargs["action"] == "reveal-encryption-key"
    audit.assert_awaited_once()


def test_a_failed_audit_reveals_nothing():
    with (
        patch.object(deps, "_require_owner", lambda r: OWNER),
        patch.object(deps, "require_step_up", AsyncMock(return_value=OWNER)),
        patch.object(database, "add_audit_event", AsyncMock(side_effect=RuntimeError("disk full"))),
    ):
        res = TestClient(main.app, raise_server_exceptions=False).post(
            "/api/settings/encryption-key/reveal", json={"step_up_password": "pw"}
        )
    assert res.status_code == 500
    assert database.encryption_key_value() not in res.text


def test_the_only_copy_is_not_deleted():
    with (
        patch.object(deps, "_require_owner", lambda r: OWNER),
        patch.object(database, "encryption_key_status", lambda: _status()),
        patch.object(database, "remove_data_folder_key") as remove,
    ):
        res = _client().post("/api/settings/encryption-key/remove-data-copy", json={"step_up_password": "pw"})
    assert res.status_code == 409
    remove.assert_not_called()


def test_the_copy_is_deleted_after_the_password():
    states = iter([_status(source="file", removable=True), _status(source="file", data_copy="none", outside=True)])
    with (
        patch.object(deps, "_require_owner", lambda r: OWNER),
        patch.object(deps, "require_step_up", AsyncMock(return_value=OWNER)) as step_up_,
        patch.object(database, "add_audit_event", AsyncMock()),
        patch.object(database, "encryption_key_status", lambda: next(states)),
        patch.object(database, "remove_data_folder_key") as remove,
    ):
        res = _client().post("/api/settings/encryption-key/remove-data-copy", json={"step_up_password": "pw"})
    assert res.status_code == 200 and res.json()["outside"] is True
    remove.assert_called_once()
    assert step_up_.await_args.kwargs["action"] == "remove-key-copy"


def _workers():
    import json

    shape = {"entrypoint": None}
    return [
        {
            "id": 1,
            "name": "box",
            "status": "online",
            "system_info": json.dumps({"earner_secrets": "file"}),
            "containers": json.dumps(
                [
                    {"slug": "honeygain", "shape": {**shape, "secrets_file": True}},
                    {"slug": "iproyal", "shape": shape},
                    # No secret variable: never counted.
                    {"slug": "mysterium", "shape": shape},
                ]
            ),
        },
        {
            "id": 2,
            "name": "mac",
            "status": "online",
            "system_info": json.dumps({"earner_secrets": "env"}),
            "containers": json.dumps([{"slug": "honeygain"}]),
        },
        {"id": 3, "name": "old", "status": "online", "system_info": "{}", "containers": "[]"},
    ]


def test_the_earner_credentials_count_per_worker():
    with (
        patch.object(deps, "_require_owner", lambda r: OWNER),
        patch.object(database, "list_workers", AsyncMock(return_value=_workers())),
    ):
        rows = _client().get("/api/settings/earner-secrets").json()
    by = {row["worker"]: row for row in rows}
    assert (by["box"]["mode"], by["box"]["in_file"], by["box"]["in_config"]) == ("file", 1, 1)
    # A worker that sends no shapes (CashPilot-Desktop) has unknown counts, never zero.
    assert (by["mac"]["mode"], by["mac"]["in_file"], by["mac"]["in_config"]) == ("env", None, None)
    assert (by["old"]["mode"], by["old"]["in_file"], by["old"]["in_config"]) == (None, 0, 0)
