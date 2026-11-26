"""Tests targeting uncovered lines in app/worker_api.py.

Covers _verify_api_key negative paths (missing header, wrong key, no key
configured), _validate_deploy_spec rejections not already exercised by
test_worker_resources.py (privileged, blocked capabilities, disallowed
network_mode, blocked volume roots, named-volume allow-list), and the
container command endpoints (status/list/deploy/restart/stop/start/remove/
logs) success + docker-error paths.

Mocks app.orchestrator entirely — no real Docker socket is used.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

try:
    from fastapi import HTTPException  # noqa: E402
    from fastapi.testclient import TestClient  # noqa: E402

    from app import worker_api  # noqa: E402
    from app.worker_api import DeploySpec, _validate_deploy_spec, _verify_api_key  # noqa: E402
except ImportError:
    pytest.skip(
        "Requires full app dependencies (fastapi, docker, etc.) — runs in CI",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers — match the TestClient harness used in test_worker_resources.py
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _noop_lifespan(a):
    yield


def _client():
    # Disable the heartbeat lifespan so the TestClient stays isolated.
    worker_api.app.router.lifespan_context = _noop_lifespan
    return TestClient(worker_api.app, raise_server_exceptions=False)


def _auth():
    return {"Authorization": f"Bearer {worker_api.API_KEY}"}


# ---------------------------------------------------------------------------
# _verify_api_key — negative paths
# ---------------------------------------------------------------------------


class TestVerifyApiKeyUnit:
    def test_missing_header_rejected(self):
        req = MagicMock()
        req.headers = {}
        with pytest.raises(HTTPException) as ei:
            _verify_api_key(req)
        assert ei.value.status_code == 401

    def test_wrong_key_rejected(self):
        req = MagicMock()
        req.headers = {"Authorization": "Bearer wrong-key"}
        with pytest.raises(HTTPException) as ei:
            _verify_api_key(req)
        assert ei.value.status_code == 401

    def test_no_key_configured_returns_503(self):
        req = MagicMock()
        req.headers = {"Authorization": "Bearer anything"}
        with patch.object(worker_api, "API_KEY", ""), pytest.raises(HTTPException) as ei:
            _verify_api_key(req)
        assert ei.value.status_code == 503

    def test_correct_key_passes(self):
        req = MagicMock()
        req.headers = {"Authorization": f"Bearer {worker_api.API_KEY}"}
        _verify_api_key(req)  # must not raise


class TestEndpointAuthRejection:
    def test_endpoint_rejects_missing_header(self):
        resp = _client().get("/api/status")
        assert resp.status_code == 401

    def test_endpoint_rejects_wrong_key(self):
        resp = _client().get("/api/status", headers={"Authorization": "Bearer nope"})
        assert resp.status_code == 401

    def test_deploy_endpoint_rejects_missing_auth(self):
        # api_deploy_container is the socket-privileged endpoint (host-RCE trust
        # boundary via orchestrator/Docker) -- an unauthenticated request must
        # be rejected before the deploy spec is even validated.
        resp = _client().post("/api/containers/honeygain/deploy", json={"image": "img"})
        assert resp.status_code == 401

    def test_deploy_endpoint_rejects_wrong_key(self):
        resp = _client().post(
            "/api/containers/honeygain/deploy",
            json={"image": "img"},
            headers={"Authorization": "Bearer nope"},
        )
        assert resp.status_code == 401

    def test_health_endpoint_requires_no_auth(self):
        resp = _client().get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "worker": worker_api.WORKER_NAME}


# ---------------------------------------------------------------------------
# _validate_deploy_spec — rejections not covered by test_worker_resources.py
# ---------------------------------------------------------------------------


class TestValidateDeploySpecRejections:
    def test_privileged_rejected(self):
        spec = DeploySpec(image="x", privileged=True)
        with pytest.raises(HTTPException) as ei:
            _validate_deploy_spec(spec)
        assert ei.value.status_code == 403

    def test_blocked_capability_rejected(self):
        spec = DeploySpec(image="x", cap_add=["SYS_ADMIN"])
        with pytest.raises(HTTPException) as ei:
            _validate_deploy_spec(spec)
        assert ei.value.status_code == 403

    def test_blocked_capability_rejected_case_insensitive(self):
        spec = DeploySpec(image="x", cap_add=["sys_ptrace"])
        with pytest.raises(HTTPException) as ei:
            _validate_deploy_spec(spec)
        assert ei.value.status_code == 403

    @pytest.mark.parametrize("cap", ["SYS_MODULE", "DAC_READ_SEARCH", "SYS_RAWIO", "BPF", "SYS_BOOT"])
    def test_capability_not_declared_by_any_catalog_service_rejected(self, cap):
        # Allowlist, not a denylist: only what a catalog service declares is allowed,
        # so anything else -- including caps the old 3-entry denylist missed -- is refused.
        spec = DeploySpec(image="x", cap_add=[cap])
        with pytest.raises(HTTPException) as ei:
            _validate_deploy_spec(spec)
        assert ei.value.status_code == 403

    def test_allowed_capability_passes(self):
        # NET_ADMIN is allowed because mysterium.yml declares cap_add: [NET_ADMIN].
        _validate_deploy_spec(DeploySpec(image="x", cap_add=["NET_ADMIN"]))  # must not raise

    def test_disallowed_network_mode_rejected(self):
        spec = DeploySpec(image="x", network_mode="container:abc123")
        with pytest.raises(HTTPException) as ei:
            _validate_deploy_spec(spec)
        assert ei.value.status_code == 403

    @pytest.mark.parametrize("slug", ["mysterium", "honeygain", "storj", "not-a-real-slug", None])
    def test_host_network_mode_rejected_for_non_allowlisted_slug(self, slug):
        spec = DeploySpec(image="x", network_mode="host")
        with pytest.raises(HTTPException) as ei:
            _validate_deploy_spec(spec, slug=slug)
        assert ei.value.status_code == 403

    def test_bridge_network_mode_allowed(self):
        _validate_deploy_spec(DeploySpec(image="x", network_mode="bridge"))  # must not raise

    @pytest.mark.parametrize(
        "root", ["/etc", "/root", "/var/run", "/proc", "/mnt", "/data", "/opt", "/media", "/srv", "/tmp"]
    )
    def test_blocked_volume_root_rejected(self, root):
        # Patch realpath to identity: on macOS dev machines /etc and /var/run
        # are themselves symlinks (-> /private/etc, /private/var/run), which
        # would dodge the block by resolving to a path outside the blocklist.
        # In the worker's actual Linux container this resolution is a no-op.
        spec = DeploySpec(image="x", volumes={root: {"bind": "/data", "mode": "rw"}})
        with (
            patch("app.worker_api.os.path.realpath", side_effect=lambda p: p),
            pytest.raises(HTTPException) as ei,
        ):
            _validate_deploy_spec(spec)
        assert ei.value.status_code == 403

    def test_blocked_volume_subpath_rejected(self):
        spec = DeploySpec(image="x", volumes={"/etc/passwd": {"bind": "/x", "mode": "ro"}})
        with (
            patch("app.worker_api.os.path.realpath", side_effect=lambda p: p),
            pytest.raises(HTTPException) as ei,
        ):
            _validate_deploy_spec(spec)
        assert ei.value.status_code == 403

    def test_unraid_array_bind_mount_rejected(self):
        # The concrete attack this closes: a fleet-key holder bind-mounting the
        # whole Unraid array to read co-located apps' secrets under /mnt/user.
        spec = DeploySpec(image="x", volumes={"/mnt/user/appdata/some-other-app": {"bind": "/x", "mode": "ro"}})
        with (
            patch("app.worker_api.os.path.realpath", side_effect=lambda p: p),
            pytest.raises(HTTPException) as ei,
        ):
            _validate_deploy_spec(spec)
        assert ei.value.status_code == 403

    def test_named_volume_always_allowed(self):
        # Not an absolute path -> named volume (e.g. mysterium-data), always allowed.
        spec = DeploySpec(image="x", volumes={"mysterium-data": {"bind": "/data", "mode": "rw"}})
        _validate_deploy_spec(spec)  # must not raise

    def test_allowed_bind_mount_passes(self):
        # A custom absolute path that isn't under any blocked root still works.
        spec = DeploySpec(image="x", volumes={"/storage/honeygain": {"bind": "/data", "mode": "rw"}})
        _validate_deploy_spec(spec)  # must not raise

    def test_operator_allowlisted_subdir_permitted(self):
        # The Storj-on-Unraid case: /mnt is blocked wholesale, but the operator can
        # opt in the one directory Storj actually needs.
        spec = DeploySpec(image="x", volumes={"/mnt/user/storj/data": {"bind": "/app/config", "mode": "rw"}})
        with (
            patch("app.worker_api.os.path.realpath", side_effect=lambda p: p),
            patch("app.worker_api._ALLOWED_VOLUME_ROOTS", frozenset({"/mnt/user/storj"})),
        ):
            _validate_deploy_spec(spec)  # must not raise

    def test_allowlist_does_not_leak_to_sibling_paths(self):
        # Opting in /mnt/user/storj must NOT unblock the rest of the array.
        spec = DeploySpec(image="x", volumes={"/mnt/user/appdata/some-other-app": {"bind": "/x", "mode": "ro"}})
        with (
            patch("app.worker_api.os.path.realpath", side_effect=lambda p: p),
            patch("app.worker_api._ALLOWED_VOLUME_ROOTS", frozenset({"/mnt/user/storj"})),
            pytest.raises(HTTPException) as ei,
        ):
            _validate_deploy_spec(spec)
        assert ei.value.status_code == 403

    def test_allowlist_prefix_is_path_aware(self):
        # /mnt/user/storj must not accidentally allow /mnt/user/storjevil.
        spec = DeploySpec(image="x", volumes={"/mnt/user/storjevil": {"bind": "/x", "mode": "ro"}})
        with (
            patch("app.worker_api.os.path.realpath", side_effect=lambda p: p),
            patch("app.worker_api._ALLOWED_VOLUME_ROOTS", frozenset({"/mnt/user/storj"})),
            pytest.raises(HTTPException) as ei,
        ):
            _validate_deploy_spec(spec)
        assert ei.value.status_code == 403

    @pytest.mark.parametrize("entry", ["/", "/mnt", "/var/run", "/etc", "/data", "/tmp", "/opt"])
    def test_allowlist_refuses_whole_system_roots(self, entry):
        from app.worker_api import _parse_allowed_volume_roots

        with patch("app.worker_api.os.path.realpath", side_effect=lambda p: p):
            assert _parse_allowed_volume_roots(entry) == frozenset()

    @pytest.mark.parametrize(
        "entry",
        [
            "/run/docker.sock",  # the Docker socket == host root
            "/var/run/docker.sock",
            "/var/lib/docker/volumes",
            "/etc/shadow",
            "/root/.ssh",
            "/dev/sda",
            "/proc/self",
            "/usr/bin",
        ],
    )
    def test_allowlist_refuses_system_paths_at_any_depth(self, entry):
        """A CHILD of a blocked root must not sneak past the guard.

        Regression: the first version tested exact membership only, so
        `/run/docker.sock` was accepted (only `/run` was in the blocked set) and a
        deploy mounting `/var/run/docker.sock` then matched the allowlist and skipped
        the deny list entirely — handing a third-party container host root.
        """
        from app.worker_api import _parse_allowed_volume_roots

        with patch("app.worker_api.os.path.realpath", side_effect=lambda p: p):
            assert _parse_allowed_volume_roots(entry) == frozenset()

    @pytest.mark.parametrize("entry", ["/mnt/user", "/mnt/disks", "/data/x"])
    def test_allowlist_refuses_paths_too_shallow_to_be_a_service_dir(self, entry):
        # /mnt/user IS the whole Unraid array — too broad to be a "specific directory".
        from app.worker_api import _parse_allowed_volume_roots

        with patch("app.worker_api.os.path.realpath", side_effect=lambda p: p):
            assert _parse_allowed_volume_roots(entry) == frozenset()

    @pytest.mark.parametrize("entry", ["/mnt/user/storj", "/mnt/disks/ssd/storj", "/srv/data/storj"])
    def test_allowlist_accepts_a_specific_service_directory(self, entry):
        from app.worker_api import _parse_allowed_volume_roots

        with patch("app.worker_api.os.path.realpath", side_effect=lambda p: p):
            assert _parse_allowed_volume_roots(entry) == frozenset({entry})

    def test_allowlist_refuses_relative_entries(self):
        # The natural missing-leading-slash typo would otherwise anchor to the
        # worker's CWD and be accepted silently.
        from app.worker_api import _parse_allowed_volume_roots

        assert _parse_allowed_volume_roots("mnt/user/storj") == frozenset()

    def test_allowlist_parses_multiple_entries(self):
        from app.worker_api import _parse_allowed_volume_roots

        with patch("app.worker_api.os.path.realpath", side_effect=lambda p: p):
            parsed = _parse_allowed_volume_roots("/mnt/user/storj: /srv/data/storj :")
        assert parsed == frozenset({"/mnt/user/storj", "/srv/data/storj"})


# ---------------------------------------------------------------------------
# Container command endpoints — success + docker-error paths
# ---------------------------------------------------------------------------


class TestStatusAndListEndpoints:
    def test_status_reports_docker_and_counts(self):
        containers = [{"status": "running"}, {"status": "exited"}]
        with (
            patch("app.worker_api.orchestrator.get_status_cached", return_value=containers),
            patch("app.worker_api.orchestrator.docker_available", return_value=True),
        ):
            resp = _client().get("/api/status", headers=_auth())
        assert resp.status_code == 200
        body = resp.json()
        assert body["docker_available"] is True
        assert body["container_count"] == 2
        assert body["running_count"] == 1

    def test_status_handles_status_fetch_exception(self):
        with (
            patch("app.worker_api.orchestrator.get_status_cached", side_effect=Exception("boom")),
            patch("app.worker_api.orchestrator.docker_available", return_value=False),
        ):
            resp = _client().get("/api/status", headers=_auth())
        assert resp.status_code == 200
        assert resp.json()["container_count"] == 0

    def test_list_containers_success(self):
        containers = [{"slug": "honeygain"}]
        with patch("app.worker_api.orchestrator.get_status_cached", return_value=containers):
            resp = _client().get("/api/containers", headers=_auth())
        assert resp.status_code == 200
        assert resp.json() == containers

    def test_list_containers_docker_unavailable_returns_503(self):
        with patch("app.worker_api.orchestrator.get_status_cached", side_effect=RuntimeError("no docker")):
            resp = _client().get("/api/containers", headers=_auth())
        assert resp.status_code == 503


class TestDeployEndpointErrors:
    def test_generic_exception_returns_500(self):
        with (
            patch("app.worker_api.orchestrator.deploy_raw", side_effect=Exception("boom")),
        ):
            resp = _client().post(
                "/api/containers/honeygain/deploy",
                json={"image": "img"},
                headers=_auth(),
            )
        assert resp.status_code == 500


class TestStopRestartStartEndpoints:
    def test_stop_success(self):
        with patch("app.worker_api.orchestrator.stop_service") as mock_stop:
            resp = _client().post("/api/containers/honeygain/stop", headers=_auth())
        assert resp.status_code == 200
        assert resp.json() == {"status": "stopped"}
        mock_stop.assert_called_once_with("honeygain", 1)

    def test_stop_not_found_returns_404(self):
        with patch("app.worker_api.orchestrator.stop_service", side_effect=ValueError("not found")):
            resp = _client().post("/api/containers/missing/stop", headers=_auth())
        assert resp.status_code == 404

    def test_stop_docker_unavailable_returns_503(self):
        with patch("app.worker_api.orchestrator.stop_service", side_effect=RuntimeError("no docker")):
            resp = _client().post("/api/containers/honeygain/stop", headers=_auth())
        assert resp.status_code == 503

    def test_restart_success(self):
        with patch("app.worker_api.orchestrator.restart_service") as mock_restart:
            resp = _client().post("/api/containers/honeygain/restart", headers=_auth())
        assert resp.status_code == 200
        assert resp.json() == {"status": "restarted"}
        mock_restart.assert_called_once_with("honeygain", 1)

    def test_restart_not_found_returns_404(self):
        with patch("app.worker_api.orchestrator.restart_service", side_effect=ValueError("gone")):
            resp = _client().post("/api/containers/x/restart", headers=_auth())
        assert resp.status_code == 404

    def test_restart_docker_unavailable_returns_503(self):
        with patch("app.worker_api.orchestrator.restart_service", side_effect=RuntimeError("no docker")):
            resp = _client().post("/api/containers/honeygain/restart", headers=_auth())
        assert resp.status_code == 503

    def test_start_success(self):
        with patch("app.worker_api.orchestrator.start_service") as mock_start:
            resp = _client().post("/api/containers/honeygain/start", headers=_auth())
        assert resp.status_code == 200
        assert resp.json() == {"status": "started"}
        mock_start.assert_called_once_with("honeygain", 1)

    def test_start_not_found_returns_404(self):
        with patch("app.worker_api.orchestrator.start_service", side_effect=ValueError("gone")):
            resp = _client().post("/api/containers/x/start", headers=_auth())
        assert resp.status_code == 404

    def test_start_docker_unavailable_returns_503(self):
        with patch("app.worker_api.orchestrator.start_service", side_effect=RuntimeError("no docker")):
            resp = _client().post("/api/containers/honeygain/start", headers=_auth())
        assert resp.status_code == 503


class TestRemoveEndpoint:
    def test_remove_success(self):
        removal = {"container": "cashpilot-honeygain", "deleted_volumes": [], "failed_volumes": []}
        with (
            patch("app.worker_api.orchestrator.remove_service", return_value=removal) as mock_remove,
            patch("app.worker_api.orchestrator.remove_extra_instances", return_value=[]),
        ):
            resp = _client().delete("/api/containers/honeygain", headers=_auth())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "removed"
        assert body["container"] == "cashpilot-honeygain"
        mock_remove.assert_called_once_with(
            "honeygain",
            delete_volumes=False,
            allow_delete_critical=False,
            only_if_restore_unfinished=False,
            approved_critical=None,
        )

    def test_remove_with_delete_volumes_query_param(self):
        removal = {"container": "cashpilot-honeygain", "deleted_volumes": ["v1"], "failed_volumes": []}
        with (
            patch("app.worker_api.orchestrator.remove_service", return_value=removal) as mock_remove,
            patch("app.worker_api.orchestrator.remove_extra_instances", return_value=[]),
        ):
            resp = _client().delete("/api/containers/honeygain?delete_volumes=true", headers=_auth())
        assert resp.status_code == 200
        mock_remove.assert_called_once_with(
            "honeygain",
            delete_volumes=True,
            allow_delete_critical=False,
            only_if_restore_unfinished=False,
            approved_critical=None,
        )

    def test_remove_not_found_returns_404(self):
        with patch("app.worker_api.orchestrator.remove_service", side_effect=ValueError("gone")):
            resp = _client().delete("/api/containers/x", headers=_auth())
        assert resp.status_code == 404

    def test_remove_docker_unavailable_returns_503(self):
        with patch("app.worker_api.orchestrator.remove_service", side_effect=RuntimeError("no docker")):
            resp = _client().delete("/api/containers/honeygain", headers=_auth())
        assert resp.status_code == 503


class TestLogsEndpoint:
    def test_logs_success(self):
        with patch("app.worker_api.orchestrator.get_service_logs", return_value="line1\nline2") as mock_logs:
            resp = _client().get("/api/containers/honeygain/logs", headers=_auth())
        assert resp.status_code == 200
        assert resp.json() == {"logs": "line1\nline2"}
        mock_logs.assert_called_once_with("honeygain", lines=50, instance=1)

    def test_logs_lines_capped_at_1000(self):
        with patch("app.worker_api.orchestrator.get_service_logs", return_value="") as mock_logs:
            resp = _client().get("/api/containers/honeygain/logs?lines=5000", headers=_auth())
        assert resp.status_code == 200
        mock_logs.assert_called_once_with("honeygain", lines=1000, instance=1)

    def test_logs_not_found_returns_404(self):
        with patch("app.worker_api.orchestrator.get_service_logs", side_effect=ValueError("gone")):
            resp = _client().get("/api/containers/x/logs", headers=_auth())
        assert resp.status_code == 404

    def test_logs_docker_unavailable_returns_503(self):
        with patch("app.worker_api.orchestrator.get_service_logs", side_effect=RuntimeError("no docker")):
            resp = _client().get("/api/containers/honeygain/logs", headers=_auth())
        assert resp.status_code == 503


_OLD_UI_REFUSAL = (
    "This worker runs CashPilot v3.0.0 and replaces an existing container only when the UI confirms "
    "which container it replaces, and this UI is too old to do that. Update the UI, then redeploy. "
    "Nothing was changed."
)


@pytest.mark.parametrize("route", ["deploy", "deploy-checked"])
def test_deploy_requires_the_current_id_for_a_replacement(route):
    from types import SimpleNamespace

    from docker.errors import NotFound

    client = _client()
    path = f"/api/containers/honeygain/{route}"
    current = None
    original = "a" * 64
    successor = "b" * 64

    def lookup(name):
        assert name == "cashpilot-honeygain"
        if current is None:
            raise NotFound(name)
        return SimpleNamespace(id=current)

    def deploy(**kwargs):
        nonlocal current
        assert worker_api.route_gate.deploying("honeygain")._is_owned()
        worker_api.orchestrator.require_deploy_target(
            kwargs["expected_container"], None if current is None else lookup("cashpilot-honeygain")
        )
        current = original if current is None else successor
        return current

    docker = MagicMock()
    docker.containers.get.side_effect = lookup
    with (
        patch.object(worker_api.orchestrator, "_get_client", return_value=docker),
        patch.object(worker_api.orchestrator, "deploy_raw", side_effect=deploy),
        patch.object(worker_api.lan_fence, "refresh_outside"),
    ):
        state = client.get("/api/containers/honeygain/deploy-checked", headers=_auth())
        assert state.json() == {"exists": False, "expected_container": "none"}
        first = client.post(path, json={"image": "img"}, headers=_auth())
        assert first.status_code == 200
        with patch.dict(os.environ, {"CASHPILOT_VERSION": "3.0.0"}):
            refused = client.post(path, json={"image": "img"}, headers=_auth())
        assert refused.status_code == 409
        if route == "deploy":
            # A UI older than the checked deploy sends no expected_container and
            # shows only a plain-string 409 detail: it reads why, not "HTTP 409".
            assert refused.json()["detail"] == _OLD_UI_REFUSAL
        else:
            assert refused.json()["detail"]["current_container"] == original
        assert current == original
        # The current UI always sends the field, and gets the structured refusal on both routes.
        new_ui = client.post(path, json={"image": "img", "expected_container": "none"}, headers=_auth())
        assert new_ui.status_code == 409
        assert new_ui.json()["detail"]["error"] == "deploy_target_changed"
        assert new_ui.json()["detail"]["current_container"] == original
        assert current == original

        desktop = client.post(path, json={"image": "img", "replace_existing": True}, headers=_auth())
        assert desktop.status_code == 409
        assert desktop.json()["detail"]["current_container"] == original

        state = client.get("/api/containers/honeygain/deploy-checked", headers=_auth())
        assert state.json() == {"exists": True, "expected_container": original}
        approved = {"image": "img", "expected_container": original}
        assert client.post(path, json=approved, headers=_auth()).status_code == 200
        replay = client.post(path, json=approved, headers=_auth())
        assert replay.status_code == 409
        assert replay.json()["detail"]["current_container"] == successor
        assert current == successor


@pytest.mark.parametrize("build", ["dev", "latest"])
def test_old_ui_refusal_names_no_version_for_a_non_release_build(build):
    exc = worker_api.orchestrator.DeployTargetChanged("abc")
    refusal = worker_api._deploy_target_error(exc)
    with patch.dict(os.environ, {"CASHPILOT_VERSION": build}):
        old_ui = worker_api._old_ui_target_error(refusal, worker_api.CheckedDeploySpec(image="img"))
    assert old_ui.detail.startswith("This worker runs a newer CashPilot and replaces an existing container")


def test_checked_deploy_inventory_fails_closed_if_docker_cannot_be_read():
    with patch.object(worker_api.orchestrator, "_get_client", side_effect=RuntimeError("Docker offline")):
        assert _client().get("/api/containers/honeygain/deploy-checked", headers=_auth()).status_code == 503


def test_checked_routes_require_worker_auth():
    path = "/api/containers/honeygain/deploy-checked"
    assert _client().get(path).status_code == 401
    assert _client().post(path, json={"image": "img"}).status_code == 401
