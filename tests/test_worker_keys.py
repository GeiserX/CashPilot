"""Worker-side per-worker fleet key: persistence, auth selection, enrollment."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

try:
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
