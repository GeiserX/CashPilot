"""The update surface (issue #342): version comparison, the worker's self-update
endpoints, and the UI routes that drive them.

The worker side is the security-sensitive half: the endpoint is deliberately
parameterless and everything that reaches Docker (helper image, command, binds)
is either a pinned constant or derived from the worker's OWN container labels.
The spawn-kwargs test pins that property — if a caller-controlled value ever
reaches the helper, it fails.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import orchestrator, version, worker_api
from app.main import app as ui_app


@asynccontextmanager
async def _noop_lifespan(a):
    yield


def _worker_client():
    worker_api.app.router.lifespan_context = _noop_lifespan
    return TestClient(worker_api.app, raise_server_exceptions=False)


def _worker_auth():
    return {"Authorization": f"Bearer {worker_api.API_KEY}"}


def _ui_client():
    ui_app.router.lifespan_context = _noop_lifespan
    return TestClient(ui_app, raise_server_exceptions=False)


def _auth_owner():
    return patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "admin", "r": "owner"})


# ---------------------------------------------------------------------------
# version.release_tuple / version.is_newer
# ---------------------------------------------------------------------------


class TestVersionComparison:
    def test_release_tuple_parses_clean_releases(self):
        assert version.release_tuple("1.35.2") == (1, 35, 2)
        assert version.release_tuple("v1.36.0") == (1, 36, 0)

    def test_release_tuple_refuses_non_releases(self):
        # A non-release compared as a version is how an update check invents an
        # update — every one of these must land on None.
        for value in (None, "", "dev", "latest", "1.36.0-rc1", "not-a-release"):
            assert version.release_tuple(value) is None, value

    def test_is_newer_true_for_newer_patch_and_series(self):
        assert version.is_newer("1.35.2", "1.35.0")
        assert version.is_newer("1.36.0", "1.35.9")

    def test_is_newer_false_for_equal_and_older(self):
        assert not version.is_newer("1.35.2", "1.35.2")
        assert not version.is_newer("1.34.9", "1.35.0")

    def test_is_newer_handles_tenth_release_numerically(self):
        # String comparison gets 1.9 vs 1.10 backwards — the exact trap
        # update_check._tuple documents.
        assert version.is_newer("1.10.0", "1.9.9")

    def test_is_newer_false_when_either_side_is_not_a_release(self):
        assert not version.is_newer("1.36.0", "dev")
        assert not version.is_newer("dev", "1.35.0")
        assert not version.is_newer(None, "1.35.0")

    def test_is_newer_pads_shorter_tuples(self):
        assert version.is_newer("1.36", "1.35.9")
        assert not version.is_newer("1.35", "1.35.0")


# ---------------------------------------------------------------------------
# orchestrator.self_update_info / spawn_self_update — fake docker client
# ---------------------------------------------------------------------------


def _fake_container(labels=None, image="drumsergio/cashpilot-worker:1.35", status="running"):
    c = MagicMock()
    c.attrs = {"Config": {"Labels": labels or {}, "Image": image}}
    c.status = status
    c.id = "f" * 64
    return c


_COMPOSE_LABELS = {
    "com.docker.compose.project.working_dir": "/srv/cashpilot",
    "com.docker.compose.project.config_files": "/srv/cashpilot/docker-compose.yml,/srv/cashpilot/override.yml",
    "com.docker.compose.project": "cashpilot",
    "com.docker.compose.service": "cashpilot-worker",
}


def _fake_docker(me=None, ui=None, updater=None):
    """A docker client whose containers.get resolves the three names involved."""
    from docker.errors import NotFound

    client = MagicMock()

    def get(name):
        if me is not None and name in ("cashpilot-worker", os.uname().nodename if hasattr(os, "uname") else "host"):
            return me
        if me is not None and name not in ("cashpilot-ui", orchestrator.UPDATER_NAME):
            # gethostname() candidate — resolve to the worker container too.
            return me
        if name == "cashpilot-ui":
            if ui is None:
                raise NotFound("no ui")
            return ui
        if name == orchestrator.UPDATER_NAME:
            if updater is None:
                raise NotFound("no updater")
            return updater
        raise NotFound(name)

    client.containers.get.side_effect = get
    return client


class TestSelfUpdateInfo:
    def test_compose_managed_install_reports_its_project(self):
        me = _fake_container(labels=_COMPOSE_LABELS)
        ui = _fake_container(image="drumsergio/cashpilot:1.35")
        with patch.object(orchestrator, "_get_client", return_value=_fake_docker(me=me, ui=ui)):
            info = orchestrator.self_update_info()
        assert info["compose_managed"] is True
        assert info["working_dir"] == "/srv/cashpilot"
        assert info["project"] == "cashpilot"
        assert info["worker_image"] == "drumsergio/cashpilot-worker:1.35"
        assert info["ui_image"] == "drumsergio/cashpilot:1.35"
        assert info["updater_running"] is False

    def test_docker_run_install_is_not_compose_managed(self):
        me = _fake_container(labels={})
        with patch.object(orchestrator, "_get_client", return_value=_fake_docker(me=me)):
            info = orchestrator.self_update_info()
        assert info["compose_managed"] is False

    def test_running_updater_is_reported(self):
        me = _fake_container(labels=_COMPOSE_LABELS)
        updater = _fake_container(status="running")
        with patch.object(orchestrator, "_get_client", return_value=_fake_docker(me=me, updater=updater)):
            info = orchestrator.self_update_info()
        assert info["updater_running"] is True


class TestSpawnSelfUpdate:
    def test_spawns_the_pinned_helper_with_only_derived_values(self):
        me = _fake_container(labels=_COMPOSE_LABELS)
        client = _fake_docker(me=me)
        client.containers.run.return_value = _fake_container()
        with patch.object(orchestrator, "_get_client", return_value=client):
            result = orchestrator.spawn_self_update()

        assert result["working_dir"] == "/srv/cashpilot"
        assert result["services"] == ["cashpilot-worker"]
        kwargs = client.containers.run.call_args.kwargs
        args = client.containers.run.call_args.args
        # Image pinned — never :latest, never caller-supplied.
        assert args[0] == orchestrator.UPDATER_IMAGE
        assert ":" in orchestrator.UPDATER_IMAGE and not orchestrator.UPDATER_IMAGE.endswith(":latest")
        # Fixed script template: guards first, then the documented update SCOPED
        # to the label-derived service names — never a whole-project `up -d`.
        assert kwargs["command"][:2] == ["sh", "-c"]
        script = kwargs["command"][2]
        assert "docker compose config" in script
        assert "is not set" in script
        assert "docker compose pull cashpilot-worker" in script
        assert "docker compose up -d --no-deps cashpilot-worker" in script
        # Exactly two binds: the socket and the compose project dir.
        assert set(kwargs["volumes"]) == {"/var/run/docker.sock", "/srv/cashpilot"}
        assert kwargs["working_dir"] == "/srv/cashpilot"
        # Compose label separates files with commas; COMPOSE_FILE wants colons.
        assert kwargs["environment"] == {
            "COMPOSE_FILE": "/srv/cashpilot/docker-compose.yml:/srv/cashpilot/override.yml"
        }
        assert kwargs["name"] == orchestrator.UPDATER_NAME
        assert kwargs["detach"] is True
        assert kwargs["remove"] is True

    def test_refuses_without_compose_labels(self):
        me = _fake_container(labels={})
        client = _fake_docker(me=me)
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(orchestrator.SelfUpdateUnavailable) as ei,
        ):
            orchestrator.spawn_self_update()
        assert "not managed by Docker Compose" in str(ei.value)
        client.containers.run.assert_not_called()

    def test_refuses_when_it_cannot_see_itself(self):
        client = _fake_docker(me=None)
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(orchestrator.SelfUpdateUnavailable),
        ):
            orchestrator.spawn_self_update()
        client.containers.run.assert_not_called()

    def test_refuses_while_an_update_is_running(self):
        me = _fake_container(labels=_COMPOSE_LABELS)
        updater = _fake_container(status="running")
        client = _fake_docker(me=me, updater=updater)
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(orchestrator.SelfUpdateUnavailable) as ei,
        ):
            orchestrator.spawn_self_update()
        assert "already running" in str(ei.value)
        client.containers.run.assert_not_called()

    def test_clears_a_leftover_stopped_helper_then_spawns(self):
        me = _fake_container(labels=_COMPOSE_LABELS)
        leftover = _fake_container(status="exited")
        client = _fake_docker(me=me, updater=leftover)
        client.containers.run.return_value = _fake_container()
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.spawn_self_update()
        leftover.remove.assert_called_once_with(force=True)
        client.containers.run.assert_called_once()

    def test_refuses_when_the_service_name_cannot_be_derived(self):
        # Compose project labels but NO service label: the scoped update cannot
        # be constructed, and an unscoped whole-project `up -d` is forbidden.
        labels = {k: v for k, v in _COMPOSE_LABELS.items() if k != "com.docker.compose.service"}
        client = _fake_docker(me=_fake_container(labels=labels))
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(orchestrator.SelfUpdateUnavailable) as ei,
        ):
            orchestrator.spawn_self_update()
        assert "scoped" in str(ei.value)
        client.containers.run.assert_not_called()

    def test_racing_updates_map_the_name_conflict_to_already_running(self):
        from docker.errors import APIError

        me = _fake_container(labels=_COMPOSE_LABELS)
        client = _fake_docker(me=me)
        conflict = APIError("conflict", response=MagicMock(status_code=409))
        client.containers.run.side_effect = conflict
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(orchestrator.SelfUpdateUnavailable) as ei,
        ):
            orchestrator.spawn_self_update()
        assert "already running" in str(ei.value)

    def test_other_daemon_errors_surface_as_outage_not_500(self):
        from docker.errors import APIError

        me = _fake_container(labels=_COMPOSE_LABELS)
        client = _fake_docker(me=me)
        client.containers.run.side_effect = APIError("boom", response=MagicMock(status_code=500))
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(RuntimeError, match="refused to start"),
        ):
            orchestrator.spawn_self_update()


# ---------------------------------------------------------------------------
# Worker endpoints
# ---------------------------------------------------------------------------


class TestWorkerUpdateEndpoints:
    def test_update_info_requires_auth(self):
        resp = _worker_client().get("/api/update/info", headers={"Authorization": "Bearer nope"})
        assert resp.status_code == 401

    def test_update_info_returns_orchestrator_facts(self):
        facts = {"compose_managed": True, "working_dir": "/srv/x", "updater_running": False}
        with patch.object(orchestrator, "self_update_info", return_value=facts):
            resp = _worker_client().get("/api/update/info", headers=_worker_auth())
        assert resp.status_code == 200
        assert resp.json()["compose_managed"] is True

    def test_update_info_maps_daemon_outage_to_503(self):
        with patch.object(orchestrator, "self_update_info", side_effect=RuntimeError("Docker socket not available")):
            resp = _worker_client().get("/api/update/info", headers=_worker_auth())
        assert resp.status_code == 503

    def test_update_self_requires_auth(self):
        resp = _worker_client().post("/api/update/self", headers={"Authorization": "Bearer nope"})
        assert resp.status_code == 401

    def test_update_self_starts_the_helper(self):
        with patch.object(
            orchestrator, "spawn_self_update", return_value={"updater_id": "abc123def456", "working_dir": "/srv/x"}
        ):
            resp = _worker_client().post("/api/update/self", headers=_worker_auth())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "updating"
        assert body["updater_id"] == "abc123def456"

    def test_update_self_unavailable_is_409_with_structured_instructions(self):
        with patch.object(
            orchestrator,
            "spawn_self_update",
            side_effect=orchestrator.SelfUpdateUnavailable("Update manually: docker compose pull"),
        ):
            resp = _worker_client().post("/api/update/self", headers=_worker_auth())
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        # Structured on purpose: the UI's worker-detail sanitizer forwards only
        # allowlisted shapes, and a bare string would be replaced with a
        # generic message — losing the instructions this refusal exists for.
        assert detail["error"] == "self_update_unavailable"
        assert "Update manually" in detail["message"]


# ---------------------------------------------------------------------------
# UI routes
# ---------------------------------------------------------------------------


class TestUiUpdateRoutes:
    def test_update_info_merges_worker_facts_with_release_state(self):
        worker_facts = {"compose_managed": True, "working_dir": "/srv/x", "updater_running": False}
        with (
            _auth_owner(),
            patch("app.main._resolve_worker_id", new_callable=AsyncMock, return_value=1),
            patch("app.main._proxy_to_worker", new_callable=AsyncMock, return_value=dict(worker_facts)),
            patch("app.main.update_check.state", return_value={"known": True, "latest": "v1.35.2", "behind": False}),
            patch("app.main.version.current", return_value="1.35.0"),
        ):
            resp = _ui_client().get("/api/update-info")
        assert resp.status_code == 200
        body = resp.json()
        assert body["compose_managed"] is True
        assert body["current"] == "1.35.0"
        assert body["latest"] == "v1.35.2"
        # Same series, strictly newer patch: the button has something to install.
        assert body["patch_available"] is True

    def test_patch_available_false_across_series(self):
        # A newer SERIES is not something `compose pull` can install on a
        # series-pinned install — that is `behind`, handled as guidance.
        with (
            _auth_owner(),
            patch("app.main._resolve_worker_id", new_callable=AsyncMock, return_value=1),
            patch("app.main._proxy_to_worker", new_callable=AsyncMock, return_value={"compose_managed": True}),
            patch("app.main.update_check.state", return_value={"known": True, "latest": "v1.36.0", "behind": True}),
            patch("app.main.version.current", return_value="1.35.1"),
        ):
            resp = _ui_client().get("/api/update-info")
        body = resp.json()
        assert body["patch_available"] is False
        assert body["behind"] is True

    def test_patch_available_false_when_latest_unknown(self):
        with (
            _auth_owner(),
            patch("app.main._resolve_worker_id", new_callable=AsyncMock, return_value=1),
            patch("app.main._proxy_to_worker", new_callable=AsyncMock, return_value={"compose_managed": True}),
            patch("app.main.update_check.state", return_value={"known": False, "latest": None, "behind": False}),
            patch("app.main.version.current", return_value="1.35.1"),
        ):
            resp = _ui_client().get("/api/update-info")
        body = resp.json()
        assert body["patch_available"] is False
        assert body["known"] is False

    def test_update_posts_to_the_worker_with_a_long_timeout(self):
        captured: dict = {}

        async def fake_proxy(worker_id, method, path, **kwargs):
            captured.update({"worker_id": worker_id, "method": method, "path": path, **kwargs})
            return {"status": "updating", "updater_id": "abc"}

        with (
            _auth_owner(),
            patch("app.main._resolve_worker_id", new_callable=AsyncMock, return_value=3),
            patch("app.main._proxy_to_worker", side_effect=fake_proxy),
        ):
            resp = _ui_client().post("/api/update?worker_id=3")
        assert resp.status_code == 200
        assert resp.json()["status"] == "updating"
        assert captured["method"] == "POST"
        assert captured["path"] == "/api/update/self"
        # The helper-image pull can be slow; the default 30s proxy timeout is
        # exactly the kind of silent cap that turns a working update into a 503.
        assert captured["timeout"] == 120

    def test_worker_refusal_passes_through(self):
        with (
            _auth_owner(),
            patch("app.main._resolve_worker_id", new_callable=AsyncMock, return_value=1),
            patch(
                "app.main._proxy_to_worker",
                new_callable=AsyncMock,
                side_effect=HTTPException(status_code=409, detail="This install is not managed by Docker Compose"),
            ),
        ):
            resp = _ui_client().post("/api/update")
        assert resp.status_code == 409
        assert "not managed by Docker Compose" in resp.json()["detail"]

    def test_update_requires_owner(self):
        with patch("app.main.auth.get_current_user", return_value={"uid": 2, "u": "w", "r": "writer"}):
            resp = _ui_client().post("/api/update")
        assert resp.status_code in (401, 403)

    def test_the_refusal_survives_the_real_worker_detail_sanitizer(self):
        """Regression for the finding my own earlier test mocked past.

        The earlier passthrough test patched _proxy_to_worker, so the real
        _safe_worker_detail never ran — and it replaces every non-allowlisted
        detail with "Worker request failed", which would have eaten the manual
        instructions. This goes through the REAL proxy with only httpx mocked.
        """
        import json as _json

        refusal = {
            "detail": {
                "error": "self_update_unavailable",
                "message": "Update manually: docker compose pull && docker compose up -d",
            }
        }
        resp409 = MagicMock()
        resp409.status_code = 409
        resp409.json.return_value = refusal
        resp409.text = _json.dumps(refusal)
        resp409.headers = {"content-type": "application/json"}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.return_value = resp409

        worker = {"id": 1, "name": "w1", "status": "online", "url": "http://192.168.1.10:8081"}
        with (
            _auth_owner(),
            patch("app.main._resolve_worker_id", new_callable=AsyncMock, return_value=1),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = _ui_client().post("/api/update?worker_id=1")
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["error"] == "self_update_unavailable"
        assert "Update manually" in detail["message"]

    def test_arbitrary_worker_error_bodies_stay_generic(self):
        # Negative control for the sanitizer: a non-allowlisted shape must NOT
        # pass through — that protection is the reason the refusal is structured.
        import json as _json

        leak = {"detail": "secret-laden arbitrary worker error"}
        resp500 = MagicMock()
        resp500.status_code = 500
        resp500.json.return_value = leak
        resp500.text = _json.dumps(leak)
        resp500.headers = {"content-type": "application/json"}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.return_value = resp500

        worker = {"id": 1, "name": "w1", "status": "online", "url": "http://192.168.1.10:8081"}
        with (
            _auth_owner(),
            patch("app.main._resolve_worker_id", new_callable=AsyncMock, return_value=1),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = _ui_client().post("/api/update?worker_id=1")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Worker request failed"


class TestVersionPrefixStrictness:
    def test_multiple_leading_v_is_not_a_release(self):
        # lstrip("v") would accept vv1.36.0; removeprefix must not.
        assert version.release_tuple("vv1.36.0") is None
        assert version.series("vv1.36.0") is None
        assert not version.is_newer("vv9.9.9", "1.35.0")
