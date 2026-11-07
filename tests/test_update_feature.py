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


def _fake_container(labels=None, image="drumsergio/cashpilot-worker:1.35", status="running", port_bindings=None):
    c = MagicMock()
    c.attrs = {
        "Config": {"Labels": labels or {}, "Image": image},
        "HostConfig": {"PortBindings": port_bindings},
    }
    c.status = status
    c.id = "f" * 64
    return c


def _ui_bindings(host_ip="127.0.0.1", port="8080"):
    return {"8080/tcp": [{"HostIp": host_ip, "HostPort": port}]}


def _ui_port_cfg(host_ip="127.0.0.1", published="8080"):
    entry = {"mode": "ingress", "target": 8080, "published": published, "protocol": "tcp"}
    if host_ip is not None:
        entry["host_ip"] = host_ip
    return [entry]


def _config(**services):
    """`docker compose config --format json` output: service -> ports list."""
    return {"name": "cashpilot", "services": {name: ({"ports": p} if p else {}) for name, p in services.items()}}


def _preflight(cfg=None, code=0, stderr_bytes=b"", wait_exc=None):
    """The socketless `docker compose config` helper container."""
    import json

    c = MagicMock()
    if wait_exc is not None:
        c.wait.side_effect = wait_exc
    else:
        c.wait.return_value = {"StatusCode": code}
    out = json.dumps(cfg if cfg is not None else _config(**{"cashpilot-worker": None})).encode()
    # Compose writes the resolved file inside the check container (-o); stdout
    # stays empty. The worker copies the file out with get_archive.
    c.logs.side_effect = lambda stdout=True, stderr=True: stderr_bytes if stderr else b""
    c.get_archive.side_effect = lambda path: ([_tar_of(path, out)], {"name": path})
    return c


def _tar_of(path, data):
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name=path.rsplit("/", 1)[-1])
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _wire_runs(client, preflight=None, updater=None):
    """containers.run: the preflight (no name) first, then the named updater."""
    preflight = preflight if preflight is not None else _preflight()
    updater = updater if updater is not None else _fake_container()

    def run(image, *args, **kwargs):
        return updater if kwargs.get("name") == orchestrator.UPDATER_NAME else preflight

    client.containers.run.side_effect = run
    return preflight, updater


def _updater_call(client):
    calls = [c for c in client.containers.run.call_args_list if c.kwargs.get("name") == orchestrator.UPDATER_NAME]
    assert len(calls) == 1, f"expected one updater run, got {len(calls)}"
    return calls[0]


def _updater_started(client):
    return any(c.kwargs.get("name") == orchestrator.UPDATER_NAME for c in client.containers.run.call_args_list)


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
        _wire_runs(client)
        with patch.object(orchestrator, "_get_client", return_value=client):
            result = orchestrator.spawn_self_update()

        assert result["working_dir"] == "/srv/cashpilot"
        assert result["services"] == ["cashpilot-worker"]
        call = _updater_call(client)
        kwargs, args = call.kwargs, call.args
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
        # The project name comes from the label, so an install started with
        # `-p` is updated in place instead of in a second project.
        assert kwargs["environment"] == {
            "COMPOSE_FILE": "/srv/cashpilot/docker-compose.yml:/srv/cashpilot/override.yml",
            "COMPOSE_PROJECT_NAME": "cashpilot",
        }
        assert kwargs["name"] == orchestrator.UPDATER_NAME
        assert kwargs["detach"] is True
        assert kwargs["remove"] is True

    def test_the_preflight_resolves_the_config_without_the_socket(self):
        me = _fake_container(labels=_COMPOSE_LABELS)
        client = _fake_docker(me=me)
        preflight, _ = _wire_runs(client)
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.spawn_self_update()

        first = client.containers.run.call_args_list[0]
        assert first.args[0] == orchestrator.UPDATER_IMAGE
        assert first.kwargs["command"] == [
            "docker",
            "compose",
            "config",
            "--format",
            "json",
            "-o",
            orchestrator._PREFLIGHT_OUT,
            "cashpilot-worker",
        ]
        assert first.kwargs["volumes"] == {"/srv/cashpilot": {"bind": "/srv/cashpilot", "mode": "ro"}}
        assert "name" not in first.kwargs
        # Same environment as the updater, so it resolves what the updater will.
        assert first.kwargs["environment"] == _updater_call(client).kwargs["environment"]
        preflight.remove.assert_called_once_with(force=True)

    def test_the_resolved_config_never_goes_to_stdout(self):
        """The resolved file holds every secret from .env (session, encryption
        and API keys). On stdout it would reach the daemon's log driver (Loki,
        syslog, journald...), so it is written to a file and copied out."""
        me = _fake_container(labels=_COMPOSE_LABELS)
        client = _fake_docker(me=me)
        preflight, _ = _wire_runs(client)
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.spawn_self_update()

        cmd = client.containers.run.call_args_list[0].kwargs["command"]
        assert "-o" in cmd and cmd[cmd.index("-o") + 1] == orchestrator._PREFLIGHT_OUT
        preflight.get_archive.assert_called_once_with(orchestrator._PREFLIGHT_OUT)
        for call in preflight.logs.call_args_list:
            assert call.kwargs.get("stdout") is False, "stdout of the check must never be read"

    def test_leftover_check_containers_are_removed_before_a_new_check(self):
        me = _fake_container(labels=_COMPOSE_LABELS)
        client = _fake_docker(me=me)
        old = MagicMock()
        order: list[str] = []
        old.remove.side_effect = lambda **kw: order.append("remove-old")
        client.containers.list.return_value = [old]
        preflight, updater = _wire_runs(client)
        run = client.containers.run.side_effect

        def tracking_run(image, *args, **kwargs):
            order.append("run")
            return run(image, *args, **kwargs)

        client.containers.run.side_effect = tracking_run
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.spawn_self_update()
        client.containers.list.assert_called_once_with(all=True, filters={"label": "cashpilot.updater=check"})
        old.remove.assert_called_once_with(force=True)
        assert order[0] == "remove-old"

    def test_an_env_file_install_passes_its_files_to_check_and_updater(self):
        labels = {
            **_COMPOSE_LABELS,
            "com.docker.compose.project.environment_file": "/srv/cashpilot/prod.env,/mnt/appdata/cashpilot.env",
        }
        client = _fake_docker(me=_fake_container(labels=labels))
        _wire_runs(client)
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.spawn_self_update()

        check = client.containers.run.call_args_list[0].kwargs
        upd = _updater_call(client).kwargs
        for kw in (check, upd):
            assert kw["environment"]["COMPOSE_ENV_FILES"] == "/srv/cashpilot/prod.env,/mnt/appdata/cashpilot.env"
            # Outside the project dir: mounted read-only at its own path.
            assert kw["volumes"]["/mnt/appdata/cashpilot.env"] == {"bind": "/mnt/appdata/cashpilot.env", "mode": "ro"}
            # Inside it: already visible through the project mount.
            assert "/srv/cashpilot/prod.env" not in kw["volumes"]
        assert check["volumes"]["/srv/cashpilot"]["mode"] == "ro"
        assert upd["volumes"]["/srv/cashpilot"]["mode"] == "rw"

    def test_an_env_file_install_with_drift_names_its_file(self):
        labels = {**_COMPOSE_LABELS, "com.docker.compose.project.environment_file": "/mnt/appdata/cashpilot.env"}
        me = _fake_container(labels=labels)
        ui = _fake_container(labels=_UI_LABELS, port_bindings=_ui_bindings(port="8088"))
        client = _fake_docker(me=me, ui=ui)
        _wire_runs(client, preflight=_preflight(_config(**{"cashpilot-worker": None, "cashpilot-ui": _ui_port_cfg()})))
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(orchestrator.SelfUpdateUnavailable) as ei,
        ):
            orchestrator.spawn_self_update()
        assert "/mnt/appdata/cashpilot.env" in str(ei.value)
        assert not _updater_started(client)

    def test_a_relative_env_file_label_is_refused_before_running_anything(self):
        labels = {**_COMPOSE_LABELS, "com.docker.compose.project.environment_file": "C:\\cp\\.env"}
        client = _fake_docker(me=_fake_container(labels=labels))
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(orchestrator.SelfUpdateUnavailable),
        ):
            orchestrator.spawn_self_update()
        client.containers.run.assert_not_called()

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

    def test_refuses_a_windows_project_path_before_running_anything(self):
        labels = {**_COMPOSE_LABELS, "com.docker.compose.project.working_dir": "C:\\Users\\me\\cashpilot"}
        client = _fake_docker(me=_fake_container(labels=labels))
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(orchestrator.SelfUpdateUnavailable) as ei,
        ):
            orchestrator.spawn_self_update()
        assert "Windows" in str(ei.value)
        assert "docker compose pull" in str(ei.value)
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
        # Not even the preflight runs.
        client.containers.run.assert_not_called()

    def test_clears_a_leftover_stopped_helper_then_spawns(self):
        me = _fake_container(labels=_COMPOSE_LABELS)
        leftover = _fake_container(status="exited")
        client = _fake_docker(me=me, updater=leftover)
        _wire_runs(client)
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.spawn_self_update()
        leftover.remove.assert_called_once_with(force=True)
        _updater_call(client)

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
        preflight = _preflight()
        conflict = APIError("conflict", response=MagicMock(status_code=409))

        def run(image, *args, **kwargs):
            if kwargs.get("name") == orchestrator.UPDATER_NAME:
                raise conflict
            return preflight

        client.containers.run.side_effect = run
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


class TestUpdaterImage:
    """The helper image has to be on the host before the preflight starts. Behind
    the socket proxy, a create naming a missing image gets the proxy's 404
    ("owner policy could not resolve image"), not Docker's "No such image", so
    containers.run never pulls it by itself."""

    @staticmethod
    def _proxy_404():
        from docker.errors import NotFound

        return NotFound(
            "404 Client Error: Not Found",
            response=MagicMock(status_code=404),
            explanation=f'owner policy could not resolve image "{orchestrator.UPDATER_IMAGE}" referenced by container Image',
        )

    def test_a_missing_helper_image_is_pulled_before_the_preflight(self):
        me = _fake_container(labels=_COMPOSE_LABELS)
        client = _fake_docker(me=me)
        _wire_runs(client)
        order = []
        missing = self._proxy_404()
        run = client.containers.run.side_effect

        def get(ref):
            order.append(("get", ref))
            raise missing

        def pull(ref, *args, **kwargs):
            order.append(("pull", ref))

        def tracked_run(image, *args, **kwargs):
            order.append(("run", image))
            return run(image, *args, **kwargs)

        client.images.get.side_effect = get
        client.images.pull.side_effect = pull
        client.containers.run.side_effect = tracked_run
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.spawn_self_update()
        assert order[:3] == [
            ("get", orchestrator.UPDATER_IMAGE),
            ("pull", orchestrator.UPDATER_IMAGE),
            ("run", orchestrator.UPDATER_IMAGE),
        ]
        assert _updater_started(client)

    def test_a_present_helper_image_is_not_pulled_again(self):
        me = _fake_container(labels=_COMPOSE_LABELS)
        client = _fake_docker(me=me)
        _wire_runs(client)
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.spawn_self_update()
        client.images.get.assert_called_once_with(orchestrator.UPDATER_IMAGE)
        client.images.pull.assert_not_called()

    def test_a_pull_the_daemon_refuses_is_an_outage_and_starts_nothing(self):
        from docker.errors import APIError

        me = _fake_container(labels=_COMPOSE_LABELS)
        client = _fake_docker(me=me)
        _wire_runs(client)
        client.images.get.side_effect = self._proxy_404()
        client.images.pull.side_effect = APIError("pull access denied", response=MagicMock(status_code=500))
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(RuntimeError, match="could not pull the update helper image"),
        ):
            orchestrator.spawn_self_update()
        client.containers.run.assert_not_called()


_UI_LABELS = {
    "com.docker.compose.project": "cashpilot",
    "com.docker.compose.service": "cashpilot-ui",
}


class TestPublishedPortsSurviveTheUpdate:
    """The helper never sees the operator's shell. A port or address given there
    would be dropped on recreate, moving the dashboard back to 127.0.0.1:8080,
    which may belong to another service. The update must refuse instead."""

    def _run(self, live_ui, cfg_ui, preflight=None):
        me = _fake_container(labels=_COMPOSE_LABELS)
        ui = _fake_container(labels=_UI_LABELS, image="drumsergio/cashpilot:1.61", port_bindings=live_ui)
        client = _fake_docker(me=me, ui=ui)
        cfg = _config(**{"cashpilot-worker": None, "cashpilot-ui": cfg_ui})
        _wire_runs(client, preflight=preflight or _preflight(cfg))
        return client

    def test_a_port_set_only_in_the_shell_is_refused_before_anything_is_recreated(self):
        client = self._run(_ui_bindings(port="8088"), _ui_port_cfg(published="8080"))
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(orchestrator.SelfUpdateUnavailable) as ei,
        ):
            orchestrator.spawn_self_update()
        msg = str(ei.value)
        assert "127.0.0.1:8088" in msg and "127.0.0.1:8080" in msg
        assert "cashpilot-ui" in msg
        assert ".env" in msg
        assert "docker compose pull && docker compose up -d" in msg
        assert not _updater_started(client)

    def test_an_address_set_only_in_the_shell_is_refused(self):
        client = self._run(_ui_bindings(host_ip="0.0.0.0"), _ui_port_cfg(host_ip="127.0.0.1"))
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(orchestrator.SelfUpdateUnavailable),
        ):
            orchestrator.spawn_self_update()
        assert not _updater_started(client)

    def test_a_non_default_port_kept_in_env_updates(self):
        client = self._run(_ui_bindings(port="8088"), _ui_port_cfg(published="8088"))
        with patch.object(orchestrator, "_get_client", return_value=client):
            result = orchestrator.spawn_self_update()
        assert result["services"] == ["cashpilot-worker", "cashpilot-ui"]
        _updater_call(client)

    def test_an_empty_host_ip_equals_all_interfaces(self):
        client = self._run(_ui_bindings(host_ip=""), _ui_port_cfg(host_ip="0.0.0.0"))
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.spawn_self_update()
        _updater_call(client)

    def test_a_service_missing_from_the_resolved_file_is_refused(self):
        me = _fake_container(labels=_COMPOSE_LABELS)
        ui = _fake_container(labels=_UI_LABELS, port_bindings=_ui_bindings())
        client = _fake_docker(me=me, ui=ui)
        _wire_runs(client, preflight=_preflight(_config(**{"cashpilot-worker": None})))
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(orchestrator.SelfUpdateUnavailable) as ei,
        ):
            orchestrator.spawn_self_update()
        assert "cashpilot-ui is missing" in str(ei.value)
        assert not _updater_started(client)

    def test_compose_rejecting_the_file_is_a_refusal_carrying_its_error(self):
        client = self._run(
            _ui_bindings(), _ui_port_cfg(), preflight=_preflight(code=15, stderr_bytes=b"yaml: line 3: bad")
        )
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(orchestrator.SelfUpdateUnavailable) as ei,
        ):
            orchestrator.spawn_self_update()
        assert "yaml: line 3: bad" in str(ei.value)
        assert not _updater_started(client)

    def test_a_hung_preflight_is_an_outage_and_is_cleaned_up(self):
        import requests

        pre = _preflight(wait_exc=requests.exceptions.ReadTimeout("slow"))
        client = self._run(_ui_bindings(), _ui_port_cfg(), preflight=pre)
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(RuntimeError) as ei,
        ):
            orchestrator.spawn_self_update()
        assert not isinstance(ei.value, orchestrator.SelfUpdateUnavailable)
        pre.remove.assert_called_once_with(force=True)
        assert not _updater_started(client)


class TestPortNormalisation:
    def test_container_bindings(self):
        attrs = {"HostConfig": {"PortBindings": {"8080/tcp": [{"HostIp": "", "HostPort": "8088"}]}}}
        assert orchestrator._published_from_container(attrs) == {("0.0.0.0", "8088", 8080, "tcp")}

    def test_expose_only_container_has_no_bindings(self):
        assert orchestrator._published_from_container({"HostConfig": {"PortBindings": None}}) == set()
        assert orchestrator._published_from_container({}) == set()

    def test_config_ports(self):
        cfg = _config(
            svc=[{"target": 8081, "published": "8081", "host_ip": "[::1]"}, {"target": 53, "protocol": "UDP"}]
        )
        assert orchestrator._published_from_config(cfg, "svc") == {
            ("::1", "8081", 8081, "tcp"),
            ("0.0.0.0", "", 53, "udp"),
        }

    def test_ephemeral_ports_match(self):
        attrs = {"HostConfig": {"PortBindings": {"53/udp": [{"HostIp": "", "HostPort": ""}]}}}
        cfg = _config(svc=[{"target": 53, "protocol": "udp"}])
        assert orchestrator._port_drift([("svc", orchestrator._published_from_container(attrs))], cfg) == []

    def test_unknown_service_is_none(self):
        assert orchestrator._published_from_config(_config(), "svc") is None


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
        assert "secret-laden" not in resp.json()["detail"]
        assert resp.json()["detail"].startswith("Worker request failed")


class TestVersionPrefixStrictness:
    def test_multiple_leading_v_is_not_a_release(self):
        # lstrip("v") would accept vv1.36.0; removeprefix must not.
        assert version.release_tuple("vv1.36.0") is None
        assert version.series("vv1.36.0") is None
        assert not version.is_newer("vv9.9.9", "1.35.0")
