"""Worker-side per-worker fleet key: persistence, auth selection, enrollment."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

try:
    import httpx  # noqa: E402
    from fastapi import HTTPException  # noqa: E402

    import app.worker_api as w  # noqa: E402
except ImportError:
    pytest.skip(
        "Requires full app dependencies (fastapi, docker, etc.) — runs in CI",
        allow_module_level=True,
    )


class TestActiveKey:
    def test_prefers_own_key_when_enrolled(self):
        with patch.object(w, "_worker_key", "own"), patch.object(w, "API_KEY", "shared"):
            assert w._active_key() == "own"

    def test_falls_back_to_shared_before_enrollment(self):
        with patch.object(w, "_worker_key", None), patch.object(w, "API_KEY", "shared"):
            assert w._active_key() == "shared"


class TestKeyPersistence:
    def test_save_and_load_round_trip(self, tmp_path):
        f = tmp_path / ".worker_key"
        with patch.object(w, "_WORKER_KEY_FILE", f), patch.object(w, "_worker_key", None):
            w._save_worker_key("k1")
            assert f.read_text() == "k1"
            assert w._load_worker_key() == "k1"

    def test_load_missing_file_is_none(self, tmp_path):
        with patch.object(w, "_WORKER_KEY_FILE", tmp_path / "nope"):
            assert w._load_worker_key() is None


class TestInboundVerify:
    def _req(self, token):
        r = MagicMock()
        r.headers = {"Authorization": f"Bearer {token}"}
        return r

    def test_requires_own_key_once_enrolled(self):
        with patch.object(w, "_worker_key", "own"), patch.object(w, "API_KEY", "shared"):
            assert w._verify_api_key(self._req("own")) is None  # own key accepted
            with pytest.raises(HTTPException) as ei:
                w._verify_api_key(self._req("shared"))  # shared rejected post-cutover
            assert ei.value.status_code == 401

    def test_accepts_shared_before_enrollment(self):
        with patch.object(w, "_worker_key", None), patch.object(w, "API_KEY", "shared"):
            assert w._verify_api_key(self._req("shared")) is None

    def test_503_when_no_key_configured(self):
        with patch.object(w, "_worker_key", None), patch.object(w, "API_KEY", ""):
            with pytest.raises(HTTPException) as ei:
                w._verify_api_key(self._req("anything"))
            assert ei.value.status_code == 503


class TestHeartbeatEnrollment:
    def test_heartbeat_persists_issued_key(self, tmp_path):
        f = tmp_path / ".worker_key"
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"status": "ok", "worker_id": 1, "worker_key": "issued-key"})
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=resp)

        with (
            patch.object(w, "_WORKER_KEY_FILE", f),
            patch.object(w, "_worker_key", None),
            patch.object(w, "UI_URL", "http://ui:8080"),
            patch.object(w, "API_KEY", "shared"),
            patch("app.worker_api.orchestrator.get_status", return_value=[]),
            patch("app.worker_api.orchestrator.docker_available", return_value=True),
            patch("app.worker_api.httpx.AsyncClient", return_value=mock_client),
        ):
            asyncio.run(w._send_heartbeat())
            # The issued key was persisted and adopted.
            assert f.read_text() == "issued-key"
            assert w._worker_key == "issued-key"

    def test_heartbeat_does_not_adopt_key_when_persist_fails(self):
        # Regression: previously the worker adopted the issued key in memory
        # (_worker_key = key) BEFORE attempting to persist it, so a failed
        # write still left the new key active for the rest of this process's
        # life. On restart _load_worker_key() would find nothing on disk and
        # fall back to the shared key -- which the UI (having seen this worker
        # authenticate with its own key) may no longer accept: a lockout.
        fake_file = MagicMock()
        fake_file.parent.mkdir = MagicMock()
        fake_file.write_text = MagicMock(side_effect=OSError("read-only filesystem"))

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"status": "ok", "worker_id": 1, "worker_key": "issued-key"})
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=resp)

        with (
            patch.object(w, "_WORKER_KEY_FILE", fake_file),
            patch.object(w, "_worker_key", None),
            patch.object(w, "UI_URL", "http://ui:8080"),
            patch.object(w, "API_KEY", "shared"),
            patch("app.worker_api.orchestrator.get_status", return_value=[]),
            patch("app.worker_api.orchestrator.docker_available", return_value=True),
            patch("app.worker_api.httpx.AsyncClient", return_value=mock_client),
        ):
            asyncio.run(w._send_heartbeat())
            # NOT adopted -- still None, so _active_key() keeps using the shared key.
            assert w._worker_key is None
            assert w._active_key() == "shared"


class TestKeyPersistFailure:
    def test_persist_failure_returns_false_and_does_not_adopt(self):
        fake_file = MagicMock()
        fake_file.parent.mkdir = MagicMock()
        fake_file.write_text = MagicMock(side_effect=OSError("disk full"))
        with patch.object(w, "_WORKER_KEY_FILE", fake_file), patch.object(w, "_worker_key", None):
            result = w._save_worker_key("new-key")
            assert result is False
            assert w._worker_key is None

    def test_persist_success_returns_true_and_adopts(self, tmp_path):
        f = tmp_path / ".worker_key"
        with patch.object(w, "_WORKER_KEY_FILE", f), patch.object(w, "_worker_key", None):
            result = w._save_worker_key("new-key")
            assert result is True
            assert w._worker_key == "new-key"
            assert f.read_text() == "new-key"


class TestHeartbeatErrorClassification:
    """worker_api.py:163 nit: distinguish auth rejection (401/403) from network errors."""

    def _client_returning_status(self, status_code: int):
        request = httpx.Request("POST", "http://ui:8080/api/workers/heartbeat")
        response = httpx.Response(status_code, request=request)
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=response)
        return mock_client

    def _run_heartbeat_with(self, mock_client):
        with (
            patch.object(w, "_worker_key", "own"),
            patch.object(w, "UI_URL", "http://ui:8080"),
            patch("app.worker_api.orchestrator.get_status", return_value=[]),
            patch("app.worker_api.orchestrator.docker_available", return_value=True),
            patch("app.worker_api.httpx.AsyncClient", return_value=mock_client),
        ):
            asyncio.run(w._send_heartbeat())

    def test_401_sets_distinct_auth_rejected_message(self):
        self._run_heartbeat_with(self._client_returning_status(401))
        assert w._last_error == "authentication rejected (401)"
        assert w._ui_connected is False

    def test_403_sets_distinct_auth_rejected_message(self):
        self._run_heartbeat_with(self._client_returning_status(403))
        assert w._last_error == "authentication rejected (403)"

    def test_other_http_error_keeps_generic_message(self):
        self._run_heartbeat_with(self._client_returning_status(500))
        assert w._last_error == "connection failed"

    def test_network_error_keeps_generic_message(self):
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        self._run_heartbeat_with(mock_client)
        assert w._last_error == "connection failed"


class TestClientId:
    """CashPilot-ng1: stable worker identity (client_id) decoupled from the display name."""

    def test_returns_existing_id_file(self, tmp_path):
        f = tmp_path / ".worker_id"
        f.write_text("stable-123\n")
        with patch.object(w, "_WORKER_ID_FILE", f):
            assert w._load_or_create_client_id() == "stable-123"

    def test_mints_random_id_for_brand_new_worker(self, tmp_path):
        f = tmp_path / ".worker_id"
        with patch.object(w, "_WORKER_ID_FILE", f), patch.object(w, "_worker_key", None):
            cid = w._load_or_create_client_id()
            assert cid == f.read_text()  # persisted
            # A fresh random id, never the mutable display name.
            assert cid != w.WORKER_NAME
            assert len(cid) >= 16

    def test_preserves_name_identity_for_already_enrolled_worker(self, tmp_path):
        # Migration: an already-enrolled worker (has a key) with no id file yet keeps the
        # identity the UI knows it by (WORKER_NAME), so the upgrade never re-enrolls it.
        f = tmp_path / ".worker_id"
        with (
            patch.object(w, "_WORKER_ID_FILE", f),
            patch.object(w, "_worker_key", "already-enrolled-key"),
            patch.object(w, "WORKER_NAME", "my-host"),
        ):
            assert w._load_or_create_client_id() == "my-host"
            assert f.read_text() == "my-host"

    def test_id_is_stable_across_calls(self, tmp_path):
        f = tmp_path / ".worker_id"
        with patch.object(w, "_WORKER_ID_FILE", f), patch.object(w, "_worker_key", None):
            first = w._load_or_create_client_id()
            assert w._load_or_create_client_id() == first

    def test_persist_failure_falls_back_to_in_memory_id(self):
        fake = MagicMock()
        fake.parent.mkdir = MagicMock()
        fake.write_text = MagicMock(side_effect=OSError("read-only fs"))
        fake.read_text = MagicMock(side_effect=OSError("missing"))
        with patch.object(w, "_WORKER_ID_FILE", fake), patch.object(w, "_worker_key", None):
            cid = w._load_or_create_client_id()
            # A usable id is still returned even though it could not be persisted.
            assert len(cid) >= 16

    def test_heartbeat_payload_includes_client_id(self, tmp_path):
        captured: dict = {}
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"status": "ok", "worker_id": 1})
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        async def _post(_url, **kwargs):
            captured.update(kwargs.get("json", {}))
            return resp

        mock_client.post = AsyncMock(side_effect=_post)
        with (
            patch.object(w, "_WORKER_KEY_FILE", tmp_path / ".worker_key"),
            patch.object(w, "_worker_key", None),
            patch.object(w, "CLIENT_ID", "cid-abc"),
            patch.object(w, "UI_URL", "http://ui:8080"),
            patch.object(w, "API_KEY", "shared"),
            patch("app.worker_api.orchestrator.get_status", return_value=[]),
            patch("app.worker_api.orchestrator.docker_available", return_value=True),
            patch("app.worker_api.httpx.AsyncClient", return_value=mock_client),
        ):
            asyncio.run(w._send_heartbeat())
        # Identity travels as client_id; name remains present but display-only.
        assert captured.get("client_id") == "cid-abc"
        assert captured.get("name") == w.WORKER_NAME
