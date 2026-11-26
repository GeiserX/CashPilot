"""Proxied copies on the worker side (app/proxy_tunnel.py, docs/proxies.md).

The Docker SDK is mocked. What is proved against a real daemon (fail closed,
DNS, no password in docker inspect) lives in scripts/proxy_leak_test.sh.
"""

from __future__ import annotations

import io
import os
import re
import tarfile
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

pytest.importorskip("docker")

import requests  # noqa: E402
from docker.errors import APIError, NotFound  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import orchestrator, proxy_tunnel, worker_api  # noqa: E402
from app.constants import (  # noqa: E402
    DEPLOY_DEADLINE_SECONDS,
    LABEL_INSTANCE,
    LABEL_MANAGED,
    LABEL_PROXY,
    LABEL_ROLE,
    LABEL_SERVICE,
)

PASSWORD = "s3cr3t-p@ss"
NEW_PASSWORD = "n3w-pass"  # ggignore: fake test value, not a credential
AUTH_KEY = "tskey-auth-kTEST-0123456789"


@pytest.fixture(autouse=True)
def _own_held_marker(tmp_path):
    """Each test gets its own record of stopped copies and failed replacements (proxy_tunnel.HELD_MARKER)."""
    with (
        patch.object(proxy_tunnel, "HELD_MARKER", str(tmp_path / ".proxied_held")),
        patch.object(proxy_tunnel, "FAILED_MARKER", str(tmp_path / ".proxied_failed")),
        patch.object(proxy_tunnel, "KEPT_MARKER", str(tmp_path / ".proxied_kept")),
        patch.object(proxy_tunnel, "NEW_MARKER", str(tmp_path / ".proxied_new")),
        patch.object(proxy_tunnel, "CREATED_MARKER", str(tmp_path / ".proxied_created")),
        patch.object(proxy_tunnel, "MOVE_MARKER", str(tmp_path / ".proxied_moves")),
        patch.object(proxy_tunnel, "CONTAINER_MARKER", str(tmp_path / ".proxied_containers")),
    ):
        yield


def _container(name, slug, *, proxy=None, role=None, instance=None, status="running"):
    c = MagicMock()
    c.id = f"id-{name}"
    c.short_id = name[:12]
    c.name = name
    c.status = status
    labels = {LABEL_SERVICE: slug, LABEL_MANAGED: "true", "cashpilot.deployed-by": "worker"}
    if proxy is not None:
        labels[LABEL_PROXY] = str(proxy)
    if role:
        labels[LABEL_ROLE] = role
    if instance:
        labels[LABEL_INSTANCE] = str(instance)
    c.labels = labels
    # A day old, so a staged sidecar built here is past STAGED_STALE_SECONDS whatever the clock says.
    created = (datetime.now(UTC) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    c.attrs = {"Created": created, "State": {"StartedAt": "2026-11-04T10:00:00Z"}}
    c.image.tags = [f"{slug}:1"]
    return c


# ---------------------------------------------------------------------------
# The orchestrator never mistakes a proxied copy for copy N of its service
# ---------------------------------------------------------------------------


def _copy(name, slug, proxy):
    """A proxied copy as Docker shows it: inside its tunnel's network namespace."""
    c = _container(name, slug, proxy=proxy)
    c.attrs["HostConfig"] = {"NetworkMode": f"container:id-tunnel-p{proxy}"}
    return c


def _sidecar(name, slug, proxy):
    """A tunnel as Docker shows it: labelled one and running the tunnel image."""
    c = _container(name, slug, proxy=proxy, role="tunnel")
    c.attrs["Config"] = {"Image": "drumsergio/cashpilot-tunnel:1.64.0"}
    return c


class TestCopiesAreNotProxied:
    def test_find_container_fallback_skips_a_proxied_copy(self):
        proxied = _copy("cashpilot-honeygain-p3", "honeygain", 3)
        tunnel = _sidecar("cashpilot-tunnel-honeygain-p3", "honeygain", 3)
        client = MagicMock()
        client.containers.get.side_effect = NotFound("gone")
        client.containers.list.return_value = [proxied, tunnel]
        with patch.object(orchestrator, "_get_client", return_value=client), pytest.raises(ValueError):
            orchestrator._find_container("honeygain", 1)

    def test_find_container_picks_the_real_first_copy(self):
        proxied = _copy("cashpilot-honeygain-p3", "honeygain", 3)
        real = _container("cashpilot-honeygain-renamed", "honeygain")
        client = MagicMock()
        client.containers.get.side_effect = NotFound("gone")
        client.containers.list.return_value = [proxied, real]
        with patch.object(orchestrator, "_get_client", return_value=client):
            assert orchestrator._find_container("honeygain", 1) is real

    def test_service_instances_leaves_out_proxied_copies_and_tunnels(self):
        real = _container("cashpilot-honeygain", "honeygain")
        second = _container("cashpilot-honeygain-2", "honeygain", instance=2)
        proxied = _copy("cashpilot-honeygain-p3", "honeygain", 3)
        tunnel = _sidecar("cashpilot-tunnel-honeygain-p3", "honeygain", 3)
        client = MagicMock()
        client.containers.list.return_value = [proxied, second, tunnel, real]
        with patch.object(orchestrator, "_get_client", return_value=client):
            assert orchestrator.service_instances("honeygain") == [real, second]

    def test_status_light_reports_neither_the_copy_nor_its_tunnel(self):
        real = _container("cashpilot-honeygain", "honeygain")
        proxied = _copy("cashpilot-honeygain-p3", "honeygain", 3)
        tunnel = _sidecar("cashpilot-tunnel-honeygain-p3", "honeygain", 3)
        client = MagicMock()
        client.containers.list.side_effect = lambda **kw: (
            [real, proxied, tunnel] if kw.get("filters") else [real, proxied, tunnel]
        )
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value={"honeygain:1": "honeygain"}),
        ):
            names = [e["name"] for e in orchestrator.get_status_light()]
        assert names == ["cashpilot-honeygain"]


# ---------------------------------------------------------------------------
# deploy_raw inside a tunnel's namespace
# ---------------------------------------------------------------------------


class TestDeployRawJoined:
    def test_joined_container_gets_no_ports_hostname_dns_or_network(self):
        client = MagicMock()
        tunnel = MagicMock(labels={"cashpilot.managed": "true", "cashpilot.role": "tunnel"})

        def get(key):
            # The tunnel it joins exists; no container holds the earner's name yet.
            if key == "sidecar-id":
                return tunnel
            raise NotFound("none")

        client.containers.get.side_effect = get
        client.images.get.return_value.attrs = {"Config": {"Entrypoint": ["/app/run"], "Cmd": []}}
        client.containers.run.return_value = MagicMock(id="earner-id", short_id="earner")
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_CONTAINER_NETWORK", "cp-isolated"),
        ):
            orchestrator.deploy_raw(
                slug="honeygain",
                image="honeygain/honeygain:1",
                ports={"8080/tcp": 8080},
                network_mode="container:sidecar-id",
                hostname="ignored",
                name="cashpilot-honeygain-p3",
            )
        kwargs = client.containers.run.call_args.kwargs
        assert kwargs["network_mode"] == "container:sidecar-id"
        assert kwargs["network"] is None
        assert kwargs["dns"] is None
        assert kwargs["ports"] is None
        assert kwargs["hostname"] is None
        assert kwargs["name"] == "cashpilot-honeygain-p3"
        assert kwargs["cap_drop"] == ["ALL"]
        assert kwargs["privileged"] is False
        # Docker never starts it on its own (after a reboot it would join the
        # tunnel before the tunnel's firewall is loaded); the worker does.
        assert kwargs["restart_policy"] == {"Name": "no"}

    @pytest.mark.parametrize("joined", [True, False], ids=["joined", "direct-control"])
    def test_a_failed_replacement_puts_a_joined_earner_back_stopped(self, joined):
        """Never straight into a tunnel's namespace, which may not have loaded its firewall yet."""
        client = MagicMock()
        tunnel = MagicMock(labels={"cashpilot.managed": "true", "cashpilot.role": "tunnel"})
        old = MagicMock(status="running", labels={"cashpilot.service": "honeygain", "cashpilot.proxy": "3"})
        old.attrs = {"Mounts": [], "HostConfig": {}}
        name = "cashpilot-honeygain-p3"
        names = {"sidecar-id": tunnel, name: old}

        def get(key):
            if key in names:
                return names[key]
            raise NotFound("none")

        def rename(to):
            names.pop(next(k for k, v in names.items() if v is old))
            names[to] = old

        old.rename.side_effect = rename
        client.containers.get.side_effect = get
        client.images.get.return_value.attrs = {"Config": {"Entrypoint": ["/app/run"], "Cmd": []}}
        client.containers.run.side_effect = APIError("500 Server Error: create failed")
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "container_network", return_value=None),
            patch.object(orchestrator, "container_dns", return_value=None),
            patch.object(orchestrator, "_ensure_volumes"),
            pytest.raises(orchestrator.ContainerRuntimeError) as err,
        ):
            orchestrator.deploy_raw(
                slug="honeygain",
                image="honeygain/honeygain:1",
                network_mode="container:sidecar-id" if joined else None,
                name=name,
            )
        assert names.get(name) is old
        if joined:
            old.start.assert_not_called()
            assert "until its proxy tunnel is ready" in str(err.value)
        else:
            old.start.assert_called_once()

    def test_a_create_whose_inspect_fails_is_rolled_back_by_its_docker_id(self):
        """docker-py inspects a new container before it returns it: the ID comes from the create answer."""
        client = MagicMock()
        client.api._version = "1.45"
        tunnel = MagicMock(labels={"cashpilot.managed": "true", "cashpilot.role": "tunnel"})
        old = MagicMock(status="running", labels={"cashpilot.service": "honeygain", "cashpilot.proxy": "3"})
        old.attrs = {"Mounts": [], "HostConfig": {}}
        new = MagicMock(id="b" * 64, status="created")
        name = "cashpilot-honeygain-p3"
        names = {"sidecar-id": tunnel, name: old}

        def get(key):
            if key == new.id:
                raise requests.exceptions.ReadTimeout("inspect timed out")
            if key in names:
                return names[key]
            raise NotFound("none")

        def rename(to):
            names.pop(next(k for k, v in names.items() if v is old))
            names[to] = old

        def create_container(**kwargs):
            assert kwargs["name"] == name and kwargs["host_config"]["NetworkMode"] == "container:sidecar-id"
            names[name] = new
            return {"Id": new.id}

        def sdk_create(**_kw):
            # docker-py's ContainerCollection.create: create, then inspect.
            names[name] = new
            return get(new.id)

        new.remove.side_effect = lambda **_kw: names.pop(name)
        old.rename.side_effect = rename
        client.containers.get.side_effect = get
        client.containers.create.side_effect = sdk_create
        client.api.create_container.side_effect = create_container
        client.images.get.return_value.attrs = {"Config": {"Entrypoint": ["/app/run"], "Cmd": []}}
        seen: list[str] = []
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "container_network", return_value=None),
            patch.object(orchestrator, "container_dns", return_value=None),
            patch.object(orchestrator, "_ensure_volumes"),
            pytest.raises(orchestrator.ContainerRuntimeError),
        ):
            orchestrator.deploy_raw(
                slug="honeygain",
                image="honeygain/honeygain:1",
                network_mode="container:sidecar-id",
                name=name,
                on_created=seen.append,
            )
        assert seen == [new.id]
        new.remove.assert_called_once()
        assert names.get(name) is old

    def test_the_id_first_create_sends_what_the_sdk_create_sends(self):
        """_create_container_id uses docker-py's private argument builder: an SDK that changes it fails here."""
        import docker
        from docker.models.containers import ContainerCollection

        client = docker.DockerClient(base_url="unix:///nonexistent.sock", version="1.45")
        kwargs = {
            "image": "honeygain/honeygain:1",
            "name": "cashpilot-honeygain-p3-next",
            "environment": ["A=1"],
            "labels": {"cashpilot.service": "honeygain"},
            "network_mode": "container:sidecar-id",
            "cap_drop": ["ALL"],
            "cap_add": ["NET_ADMIN"],
            "security_opt": ["no-new-privileges:true"],
            "privileged": False,
            "restart_policy": {"Name": "no"},
            "volumes": {"hg-data": {"bind": "/data", "mode": "rw"}},
            "mem_limit": 268435456,
            "entrypoint": ["/app/run"],
            "log_config": {"Type": "json-file", "Config": {}},
        }
        with (
            patch.object(client.api, "create_container", return_value={"Id": "c" * 64}) as low,
            patch.object(ContainerCollection, "get"),
        ):
            client.containers.create(**kwargs)
            sdk = low.call_args
            low.reset_mock()
            assert orchestrator._create_container_id(client, kwargs) == "c" * 64
        assert low.call_args == sdk

    def test_a_normal_container_keeps_its_restart_policy(self):
        client = MagicMock()
        client.containers.get.side_effect = NotFound("none")
        client.images.get.return_value.attrs = {"Config": {"Entrypoint": ["/app/run"], "Cmd": []}}
        client.containers.run.return_value = MagicMock(id="c", short_id="c")
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "container_network", return_value="cp-isolated"),
            patch.object(orchestrator, "container_dns", return_value=None),
        ):
            orchestrator.deploy_raw(slug="honeygain", image="honeygain/honeygain:1")
        assert client.containers.run.call_args.kwargs["restart_policy"] == {"Name": "unless-stopped"}


# ---------------------------------------------------------------------------
# The sidecar: hardening, and no secret anywhere Docker records
# ---------------------------------------------------------------------------


def _socks(**extra):
    return {"kind": "socks5", "host": "203.0.113.9", "port": 1080, "username": "u1", "password": PASSWORD, **extra}


class TestSidecar:
    def test_hardening(self):
        with patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": "drumsergio/cashpilot-tunnel:1.64.0"}):
            kw = proxy_tunnel.sidecar_kwargs("cashpilot-tunnel-x-p1", "x", 1, "cp-isolated", "x-p1")
        assert kw["cap_drop"] == ["ALL"]
        assert kw["cap_add"] == ["NET_ADMIN"]
        assert kw["devices"] == ["/dev/net/tun"]
        assert kw["privileged"] is False
        assert kw["read_only"] is True
        assert "no-new-privileges:true" in kw["security_opt"]
        assert kw["network"] == "cp-isolated"
        # An anonymous volume, as a Mount: no host path, and it survives a daemon restart.
        assert "volumes" not in kw
        assert [(m["Type"], m["Target"], m.get("Source")) for m in kw["mounts"]] == [
            ("volume", proxy_tunnel.SECRET_DIR, None)
        ]
        assert "environment" not in kw and "command" not in kw
        assert kw["log_config"] == {"type": "json-file", "config": {"max-size": "1m", "max-file": "2"}}

    @patch.object(orchestrator, "_CONTAINER_DNS", "1.1.1.1,9.9.9.9")
    def test_a_tunnel_on_the_isolated_bridge_gets_its_resolvers(self):
        # The bridge's rules refuse the daemon's LAN resolver, so the tunnel
        # needs the same resolvers every earner on it gets (container_dns).
        with patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": "drumsergio/cashpilot-tunnel:1.64.0"}):
            fenced = proxy_tunnel.sidecar_kwargs("cashpilot-tunnel-x-p1", "x", 1, "cp-isolated", "x-p1")
            plain = proxy_tunnel.sidecar_kwargs("cashpilot-tunnel-x-p1", "x", 1, None, "x-p1")
        assert fenced["dns"] == orchestrator.container_dns("cp-isolated") == ["1.1.1.1", "9.9.9.9"]
        assert plain["dns"] is None

    def test_secret_goes_only_into_the_archive(self):
        client = MagicMock()
        created = MagicMock(id="sidecar-id", status="running")
        created.put_archive.return_value = True
        created.exec_run.return_value = (0, b'{"ip":"93.184.215.14","country":"DE"}\n')
        client.containers.create.return_value = created
        with (
            patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": "drumsergio/cashpilot-tunnel:1.64.0"}),
            patch.object(orchestrator, "container_network", return_value="cp-isolated"),
        ):
            _, exit_info = proxy_tunnel.start_sidecar(client, "cashpilot-tunnel-x-p1", "x", 1, _socks(), "192.0.2.1")
        assert exit_info == {"ip": "93.184.215.14", "country": "DE"}
        recorded = repr(client.containers.create.call_args)
        assert PASSWORD not in recorded and "p%40ss" not in recorded
        path, blob = created.put_archive.call_args.args
        assert path == proxy_tunnel.SECRET_DIR
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
            members = {m.name: m for m in tar.getmembers()}
            files = {n: tar.extractfile(m).read().decode() for n, m in members.items()}
        assert files["proxy_scheme"] == "socks5" and files["proxy_auth"] == "u1:s3cr3t-p%40ss@"
        assert (files["proxy_ip"], files["proxy_port"], files["proxy_host"]) == ("203.0.113.9", "1080", "203.0.113.9")
        assert all(m.mode == 0o400 and m.uid == 0 and m.gid == 0 for m in members.values())
        # Started only after the settings were in place.
        order = [c[0] for c in created.method_calls if c[0] in ("put_archive", "start")]
        assert order == ["put_archive", "start"]

    def test_a_deploy_deadline_bounds_the_tunnel_image_pull(self):
        # docker-py's pull has no overall timeout; a deploy's tunnel must not wait past its deadline.
        client = MagicMock()
        release = threading.Event()
        client.images.pull.side_effect = lambda image: release.wait(10)
        began = time.monotonic()
        try:
            with (
                patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": "drumsergio/cashpilot-tunnel:1.64.0"}),
                patch.object(orchestrator, "container_network", return_value=None),
                pytest.raises(orchestrator.ContainerRuntimeError),
            ):
                proxy_tunnel.start_sidecar(
                    client, "cashpilot-tunnel-x-p1", "x", 1, _socks(), None, deadline=time.monotonic() + 0.3
                )
        finally:
            release.set()
        assert time.monotonic() - began < 5
        client.containers.create.assert_not_called()

    def test_a_failed_tunnel_is_removed_and_its_error_carries_no_password(self):
        client = MagicMock()
        created = MagicMock(id="sidecar-id", status="exited")
        created.put_archive.return_value = True
        created.logs.return_value = f"tun2proxy: socks5://u1:{PASSWORD}@203.0.113.9:1080 refused".encode()
        client.containers.create.return_value = created
        with (
            patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": "drumsergio/cashpilot-tunnel:1.64.0"}),
            patch.object(orchestrator, "container_network", return_value=None),
            pytest.raises(proxy_tunnel.ProxyTunnelError) as err,
        ):
            proxy_tunnel.start_sidecar(client, "cashpilot-tunnel-x-p1", "x", 1, _socks(), None)
        assert PASSWORD not in str(err.value)
        created.remove.assert_called_once_with(force=True, v=True)

    def test_no_auth_means_an_empty_auth_part(self):
        files = proxy_tunnel.secret_files({"kind": "http", "host": "203.0.113.9", "port": 8080}, None, "x")
        assert files["proxy_auth"] == "" and files["proxy_scheme"] == "http"

    def test_a_start_resolves_the_proxy_host_again(self):
        stored = {"proxy_host": "gw.example.net", "proxy_ip": "203.0.113.9"}

        def get_archive(path):
            name = path.rsplit("/", 1)[1]
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tar:
                data = stored[name].encode()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            return iter([buf.getvalue()]), {}

        sidecar = _container("cashpilot-tunnel-x-p1", "x", proxy=1, role="tunnel", status="exited")
        sidecar.get_archive.side_effect = get_archive
        with patch.object(proxy_tunnel, "resolve_proxy_ip", return_value="198.51.100.7"):
            proxy_tunnel.refresh_proxy_ip(sidecar)
        path, blob = sidecar.put_archive.call_args.args
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
            assert tar.extractfile("proxy_ip").read() == b"198.51.100.7"
        sidecar.put_archive.reset_mock()
        with patch.object(proxy_tunnel, "resolve_proxy_ip", return_value="203.0.113.9"):
            proxy_tunnel.refresh_proxy_ip(sidecar)
        sidecar.put_archive.assert_not_called()

    def test_tailscale_files(self):
        files = proxy_tunnel.secret_files(
            {"kind": "tailscale", "auth_key": AUTH_KEY, "exit_node": "exit-node-a"}, None, "w1-x"
        )
        assert files["auth_key"] == AUTH_KEY
        assert files["exit_node"] == "exit-node-a"
        assert files["hostname"] == "cashpilot-w1-x"


class TestTunnelImage:
    def test_floating_tag_is_refused(self):
        with (
            patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": "drumsergio/cashpilot-tunnel:latest"}),
            pytest.raises(proxy_tunnel.ProxyTunnelError),
        ):
            proxy_tunnel.tunnel_image()
        with (
            patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": "drumsergio/cashpilot-tunnel"}),
            pytest.raises(proxy_tunnel.ProxyTunnelError),
        ):
            proxy_tunnel.tunnel_image()

    def test_release_build_pins_its_own_version(self):
        env = {"CASHPILOT_VERSION": "1.64.0", "CASHPILOT_TUNNEL_IMAGE": ""}
        with patch.dict(os.environ, env):
            assert proxy_tunnel.tunnel_image() == "drumsergio/cashpilot-tunnel:1.64.0"

    def test_dev_build_without_override_is_refused(self):
        with (
            patch.dict(os.environ, {"CASHPILOT_VERSION": "", "CASHPILOT_TUNNEL_IMAGE": ""}),
            pytest.raises(proxy_tunnel.ProxyTunnelError),
        ):
            proxy_tunnel.tunnel_image()


# ---------------------------------------------------------------------------
# Order and coupling
# ---------------------------------------------------------------------------


class TestOrder:
    def test_a_sidecar_that_cannot_start_keeps_the_running_copy(self):
        client = MagicMock()
        client.containers.get.side_effect = NotFound("gone")
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(proxy_tunnel, "tunnel_image", return_value="drumsergio/cashpilot-tunnel:1.64.0"),
            patch.object(proxy_tunnel, "_remove") as remove,
            patch.object(proxy_tunnel, "start_sidecar", side_effect=proxy_tunnel.ProxyTunnelError("No such image")),
            pytest.raises(proxy_tunnel.ProxyTunnelError),
        ):
            proxy_tunnel.deploy("honeygain", 3, {"image": "honeygain/honeygain:1"}, _socks(), None)
        remove.assert_not_called()

    def test_a_failed_promotion_removes_the_staged_sidecar(self):
        sidecar = MagicMock(id="sidecar-id")
        sidecar.rename.side_effect = RuntimeError("409 Conflict")
        client = MagicMock()
        client.containers.get.side_effect = NotFound("gone")
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(proxy_tunnel, "tunnel_image", return_value="drumsergio/cashpilot-tunnel:1.64.0"),
            patch.object(proxy_tunnel, "_remove", return_value=[]),
            patch.object(proxy_tunnel, "start_sidecar", return_value=(sidecar, {"ip": "93.184.215.14"})),
            patch.object(orchestrator, "deploy_raw") as deploy_raw,
            pytest.raises(RuntimeError),
        ):
            proxy_tunnel.deploy("honeygain", 3, {"image": "honeygain/honeygain:1"}, _socks(), None)
        sidecar.remove.assert_called_once_with(force=True, v=True)
        deploy_raw.assert_not_called()

    def test_the_heartbeat_removes_a_stale_staged_sidecar_and_keeps_a_young_one(self):
        stale = _container("cashpilot-tunnel-x-p1-next", "x", proxy=1, role="tunnel")
        young = _container("cashpilot-tunnel-y-p1-next", "y", proxy=1, role="tunnel")
        young.attrs["Created"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        client = MagicMock()
        client.containers.list.return_value = [stale, young]
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(proxy_tunnel, "_read_exit", return_value=None),
        ):
            assert proxy_tunnel.status(collect_stats=False) == []
        stale.remove.assert_called_once_with(force=True, v=True)
        young.remove.assert_not_called()

    @pytest.mark.parametrize("op", ["stop", "start", "remove"])
    def test_stop_start_and_remove_wait_for_a_deploy_of_the_same_copy(self, op):
        import threading

        done = threading.Event()
        lock = proxy_tunnel._deploy_lock(1)
        lock.acquire()
        try:
            with patch.object(proxy_tunnel, f"_{op}", side_effect=lambda *a: done.set()):
                t = threading.Thread(target=getattr(proxy_tunnel, op), args=("x", 1))
                t.start()
                assert not done.wait(0.2), f"{op} ran while a deploy of the copy held its lock"
                lock.release()
                t.join(2)
            assert done.is_set()
        finally:
            if lock.locked():
                lock.release()

    def test_the_heartbeat_never_reports_a_staged_sidecar(self):
        earner = _container("cashpilot-x-p1", "x", proxy=1)
        tunnel = _container("cashpilot-tunnel-x-p1", "x", proxy=1, role="tunnel")
        staged = _container("cashpilot-tunnel-x-p1-next", "x", proxy=1, role="tunnel")
        staged.id = "id-staged"
        client = MagicMock()
        client.containers.list.return_value = [earner, tunnel, staged]
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(proxy_tunnel, "_read_exit", return_value=None),
        ):
            entries = proxy_tunnel.status(collect_stats=False)
        assert [(e["slug"], e["tunnel_container_id"]) for e in entries] == [("x", tunnel.short_id)]

    def test_remove_all_takes_earners_before_tunnels(self):
        tunnel = _container("cashpilot-tunnel-x-p1", "x", proxy=1, role="tunnel")
        earner = _container("cashpilot-x-p1", "x", proxy=1)
        tunnel.reload.side_effect = earner.reload.side_effect = NotFound("gone")
        client = MagicMock()
        client.containers.list.return_value = [tunnel, earner]
        with patch.object(orchestrator, "_get_client", return_value=client):
            assert proxy_tunnel.remove_all("x") == ["cashpilot-x-p1", "cashpilot-tunnel-x-p1"]

    def test_remove_all_says_so_when_a_copy_survives(self):
        """A copy Docker would not remove keeps its record on the UI, so the
        worker must not report it as removed."""
        tunnel = _container("cashpilot-tunnel-x-p1", "x", proxy=1, role="tunnel")
        earner = _container("cashpilot-x-p1", "x", proxy=1)
        tunnel.reload.side_effect = NotFound("gone")
        client = MagicMock()
        client.containers.list.return_value = [tunnel, earner]
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(proxy_tunnel.ProxyTunnelError, match="cashpilot-x-p1"),
        ):
            proxy_tunnel.remove_all("x")

    def test_a_deploy_with_settings_that_cannot_work_keeps_the_running_copy(self):
        with (
            patch.object(orchestrator, "_get_client", return_value=MagicMock()),
            patch.object(proxy_tunnel, "tunnel_image", return_value="drumsergio/cashpilot-tunnel:1.64.0"),
            patch.object(proxy_tunnel, "resolve_proxy_ip", side_effect=proxy_tunnel.ProxyTunnelError("no such host")),
            patch.object(proxy_tunnel, "_remove") as remove,
            pytest.raises(proxy_tunnel.ProxyTunnelError),
        ):
            proxy_tunnel.deploy("x", 1, {"image": "x:1"}, _socks(host="gone.example"), None)
        remove.assert_not_called()

    def test_earner_restarts_when_its_tunnel_restarted_after_it(self):
        earner = _container("cashpilot-x-p1", "x", proxy=1)
        tunnel = _container("cashpilot-tunnel-x-p1", "x", proxy=1, role="tunnel")
        earner.attrs["State"]["StartedAt"] = "2026-11-04T10:00:00.1Z"
        tunnel.attrs["State"]["StartedAt"] = "2026-11-04T11:00:00.1Z"
        assert proxy_tunnel.earner_action(earner, tunnel, ready=True) == "restart"
        # Not before the tunnel's firewall is in and an exit was seen.
        assert proxy_tunnel.earner_action(earner, tunnel, ready=False) is None
        tunnel.attrs["State"]["StartedAt"] = "2026-11-04T09:00:00.1Z"
        assert proxy_tunnel.earner_action(earner, tunnel, ready=True) is None
        tunnel.status = "exited"
        tunnel.attrs["State"]["StartedAt"] = "2026-11-04T11:00:00.1Z"
        assert proxy_tunnel.earner_action(earner, tunnel, ready=True) is None

    def test_an_earner_left_stopped_by_a_reboot_starts_only_once_its_tunnel_is_ready(self):
        earner = _container("cashpilot-x-p1", "x", proxy=1, status="exited")
        tunnel = _container("cashpilot-tunnel-x-p1", "x", proxy=1, role="tunnel")
        client = _client_with(earner, tunnel)
        client.containers.list.return_value = [earner, tunnel]
        tunnel.exec_run.return_value = (1, b"")  # /run/ready not written yet
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_collect_stats_bulk", return_value={}),
        ):
            proxy_tunnel.status()
            earner.start.assert_not_called()
            tunnel.exec_run.return_value = (0, b'{"ip":"93.184.215.14","country":"DE"}')
            proxy_tunnel.status()
        earner.start.assert_called_once()
        earner.restart.assert_not_called()

    def test_status_reports_the_tunnels_traffic_and_exit(self):
        earner = _container("cashpilot-x-p1", "x", proxy=1)
        earner.attrs["Config"] = {"Image": "x/x:1.2"}
        tunnel = _container("cashpilot-tunnel-x-p1", "x", proxy=1, role="tunnel")
        tunnel.exec_run.return_value = (0, b'{"ip":"93.184.215.14","country":"DE"}')
        client = MagicMock()
        client.containers.list.return_value = [earner, tunnel]
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_collect_stats_bulk", return_value={tunnel.id: (0.1, 5.0, 1000, 200)}),
        ):
            (entry,) = proxy_tunnel.status()
        assert entry["slug"] == "x" and entry["proxy_id"] == 1
        # What the earner runs, so the UI can say a routed service's image is outdated.
        assert entry["image"] == "x/x:1.2"
        assert (entry["net_rx_bytes"], entry["net_tx_bytes"]) == (1000, 200)
        assert entry["exit_ip"] == "93.184.215.14" and entry["exit_country"] == "DE"


# ---------------------------------------------------------------------------
# Worker API
# ---------------------------------------------------------------------------


def _api():
    return TestClient(worker_api.app, raise_server_exceptions=False)


AUTH = {"Authorization": "Bearer test-fleet-key"}


class TestWorkerApi:
    def test_container_network_mode_is_still_refused_from_callers(self):
        with patch.object(worker_api, "_verify_api_key"):
            resp = _api().post(
                "/api/containers/honeygain/deploy",
                json={"image": "honeygain/honeygain:1", "network_mode": "container:abc"},
                headers=AUTH,
            )
        assert resp.status_code == 403

    @pytest.mark.parametrize(
        "extra",
        [{"ports": {"8080/tcp": 8080}}, {"volumes": {"/x": {"bind": "/y", "mode": "rw"}}}, {"network_mode": "host"}],
    )
    def test_proxied_copy_refuses_ports_volumes_and_network(self, extra):
        body = {"earner": {"image": "honeygain/honeygain:1", **extra}, "proxy": _socks()}
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(proxy_tunnel, "deploy") as deploy,
        ):
            resp = _api().post("/api/proxied/honeygain/3/deploy", json=body, headers=AUTH)
        assert resp.status_code == 400
        deploy.assert_not_called()

    @pytest.mark.parametrize(
        "extra",
        [
            {"cap_add": ["NET_ADMIN"]},
            {"cap_add": ["NET_RAW"]},
            {"cap_add": ["CAP_SYS_ADMIN"]},
            {"cap_add": ["all"]},
            {"devices": ["/dev/net/tun"]},
        ],
    )
    def test_proxied_copy_refuses_caps_and_devices_that_reach_the_tunnel(self, extra):
        body = {"earner": {"image": "mysteriumnetwork/myst:1", **extra}, "proxy": _socks()}
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(worker_api, "_validate_deploy_spec"),
            patch.object(proxy_tunnel, "deploy") as deploy,
        ):
            resp = _api().post("/api/proxied/mysterium/3/deploy", json=body, headers=AUTH)
        assert resp.status_code == 400, resp.text
        deploy.assert_not_called()

    def test_validation_error_never_echoes_the_password(self):
        # No "kind": pydantic's error then echoes the whole proxy object as its input.
        proxy = {k: v for k, v in _socks().items() if k != "kind"}
        body = {"earner": {"image": "x"}, "proxy": proxy}
        with patch.object(worker_api, "_verify_api_key"):
            resp = _api().post("/api/proxied/honeygain/3/deploy", json=body, headers=AUTH)
        assert resp.status_code == 422
        assert PASSWORD not in resp.text

    def test_deploy_passes_the_plain_proxy_to_the_tunnel(self):
        body = {"earner": {"image": "honeygain/honeygain:1", "env": {"A": "b"}}, "proxy": _socks()}
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(worker_api, "_validate_deploy_spec"),
            patch.object(worker_api, "_detect_egress_ip", return_value="192.0.2.1"),
            patch.object(proxy_tunnel, "deploy", return_value={"container_id": "c", "tunnel_id": "t"}) as deploy,
        ):
            resp = _api().post("/api/proxied/honeygain/3/deploy", json=body, headers=AUTH)
        assert resp.status_code == 200, resp.text
        slug, proxy_id, earner, proxy, own_ip = deploy.call_args.args
        assert (slug, proxy_id, own_ip) == ("honeygain", 3, "192.0.2.1")
        assert proxy["password"] == PASSWORD and earner["env"] == {"A": "b"}
        assert PASSWORD not in resp.text
        kwargs = deploy.call_args.kwargs
        assert kwargs.pop("deadline") > time.monotonic() + DEPLOY_DEADLINE_SECONDS - 60
        assert kwargs == {"only_if_running": False, "expected_container": "none"}

    def test_deploy_passes_only_if_running_through(self):
        body = {"earner": {"image": "honeygain/honeygain:1"}, "proxy": _socks(), "only_if_running": True}
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(worker_api, "_validate_deploy_spec"),
            patch.object(worker_api, "_detect_egress_ip", return_value=None),
            patch.object(proxy_tunnel, "deploy", return_value={"container_id": "c", "tunnel_id": "t"}) as deploy,
        ):
            resp = _api().post("/api/proxied/honeygain/3/deploy", json=body, headers=AUTH)
        assert resp.status_code == 200, resp.text
        kwargs = deploy.call_args.kwargs
        assert kwargs.pop("deadline") > time.monotonic() + DEPLOY_DEADLINE_SECONDS - 60
        assert kwargs == {"only_if_running": True, "expected_container": "none"}

    def test_proxy_test_refuses_a_private_exit(self):
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(worker_api, "_detect_egress_ip", return_value=None),
            patch.object(proxy_tunnel, "test", return_value={"ip": "10.0.0.5", "country": "", "ms": 5}),
        ):
            resp = _api().post("/api/proxy-test", json={"proxy": _socks()}, headers=AUTH)
        assert resp.status_code == 409

    def test_proxy_test_reports_the_exit(self):
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(worker_api, "_detect_egress_ip", return_value=None),
            patch.object(proxy_tunnel, "test", return_value={"ip": "93.184.215.14", "country": "DE", "ms": 812}),
        ):
            resp = _api().post("/api/proxy-test", json={"proxy": _socks()}, headers=AUTH)
        assert resp.json() == {"exit_ip": "93.184.215.14", "country": "DE", "ms": 812}

    def test_removing_a_service_removes_its_proxied_copies(self):
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(orchestrator, "remove_service", return_value={"container": "cashpilot-x"}),
            patch.object(orchestrator, "remove_extra_instances", return_value=[]),
            patch.object(proxy_tunnel, "remove_all", return_value=["cashpilot-x-p1"]) as remove_all,
        ):
            resp = _api().delete("/api/containers/x", headers=AUTH)
        assert resp.status_code == 200
        remove_all.assert_called_once_with("x")
        assert resp.json()["proxied"] == ["cashpilot-x-p1"]


def _tailscale(**extra):
    return {"kind": "tailscale", "auth_key": AUTH_KEY, "exit_node": "exit-1", **extra}


class TestWorkerProxyValidation:
    @pytest.mark.parametrize(
        "proxy",
        [
            {"kind": "wireguard", "host": "203.0.113.9", "port": 51820},
            _tailscale(auth_key=None),
            _tailscale(exit_node="bad name; rm"),
            _tailscale(login_server="http://headscale.example"),
            _socks(host="bad host"),
            _socks(port=0),
            _socks(port=70000),
        ],
    )
    def test_a_malformed_proxy_is_refused_before_any_tunnel(self, proxy):
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(proxy_tunnel, "test") as test,
        ):
            resp = _api().post("/api/proxy-test", json={"proxy": proxy}, headers=AUTH)
        assert resp.status_code == 400, resp.text
        test.assert_not_called()
        assert PASSWORD not in resp.text and AUTH_KEY not in resp.text

    def test_a_tailscale_proxy_with_a_login_server_passes(self):
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(worker_api, "_detect_egress_ip", side_effect=OSError("offline")),
            patch.object(proxy_tunnel, "test", return_value={"ip": "93.184.215.14", "country": "DE", "ms": 9}) as test,
        ):
            resp = _api().post(
                "/api/proxy-test",
                json={"proxy": _tailscale(login_server="https://hs.example")},
                headers=AUTH,
            )
        assert resp.status_code == 200, resp.text
        proxy, own_ip = test.call_args.args
        assert proxy["auth_key"] == AUTH_KEY and own_ip is None

    def test_a_proxied_copy_has_no_instance_number(self):
        body = {"earner": {"image": "honeygain/honeygain:1", "instance": 2}, "proxy": _socks()}
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(proxy_tunnel, "deploy") as deploy,
        ):
            resp = _api().post("/api/proxied/honeygain/3/deploy", json=body, headers=AUTH)
        assert resp.status_code == 400
        deploy.assert_not_called()


class TestWorkerProxiedOps:
    def test_stop_start_and_remove_reach_the_tunnel_module(self):
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(proxy_tunnel, "stop", return_value={"was_running": True}) as stop,
            patch.object(proxy_tunnel, "start", return_value={"exit": {"ip": "93.184.215.14"}}) as start,
            patch.object(proxy_tunnel, "remove", return_value=["cashpilot-x-p1", "cashpilot-tunnel-x-p1"]) as remove,
        ):
            api = _api()
            assert api.post("/api/proxied/x/1/stop", headers=AUTH).json() == {
                "status": "stopped",
                "was_running": True,
            }
            assert api.post("/api/proxied/x/1/start", headers=AUTH).json() == {
                "status": "started",
                "exit": {"ip": "93.184.215.14"},
            }
            assert api.delete("/api/proxied/x/1", headers=AUTH).json() == {
                "status": "removed",
                "containers": ["cashpilot-x-p1", "cashpilot-tunnel-x-p1"],
            }
        stop.assert_called_once_with("x", 1)
        start.assert_called_once_with("x", 1, None, None)
        remove.assert_called_once_with("x", 1)

    def test_a_windowed_log_read_filters_the_copy_and_says_so(self):
        """The UI's windowed health signals read a proxied copy as they read a direct one: filtered, and told so."""
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(proxy_tunnel, "grep_logs", return_value="2026-11-21 Error: x") as grep,
            patch.object(proxy_tunnel, "logs", return_value="tail") as tail,
        ):
            api = _api()
            window = api.get("/api/proxied/x/1/logs", params={"lines": 5000, "match": "Error", "since_hours": 48})
            plain = api.get("/api/proxied/x/1/logs", params={"lines": 20})
        assert window.json() == {"logs": "2026-11-21 Error: x", "filtered": True}
        (slug, pid, pattern), kw = grep.call_args
        assert (slug, pid, pattern.pattern, kw) == ("x", 1, "Error", {"since_hours": 24, "lines": 1000})
        assert plain.json() == {"logs": "tail"}, "no filter, no claim that one was applied"
        tail.assert_called_once_with("x", 1, 20)

    @pytest.mark.parametrize("match", ["(", "x" * 201])
    def test_a_bad_filter_is_a_400(self, match):
        with patch.object(worker_api, "_verify_api_key"), patch.object(proxy_tunnel, "grep_logs") as grep:
            resp = _api().get("/api/proxied/x/1/logs", params={"match": match, "since_hours": 1})
        assert resp.status_code == 400
        grep.assert_not_called()

    def test_grep_logs_reads_only_the_window_of_our_earner(self):
        earner = _copy("cashpilot-x-p1", "x", 1)
        earner.logs.return_value = iter([b"a Error one\nb fine\nc Err", b"or two"])
        with patch.object(orchestrator, "_get_client", return_value=_client_with(earner)):
            out = proxy_tunnel.grep_logs("x", 1, re.compile("Error"), since_hours=2)
            with pytest.raises(ValueError):
                proxy_tunnel.grep_logs("y", 1, re.compile("Error"), since_hours=2)
        assert out == "a Error one\nc Error two"
        kw = earner.logs.call_args.kwargs
        assert kw["stream"] is True and kw["follow"] is False
        assert time.time() - 2 * 3600 - 5 <= kw["since"] <= time.time() - 2 * 3600 + 5

    def test_a_restart_reaches_the_tunnel_module(self):
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(proxy_tunnel, "restart", return_value={"restarted": "cashpilot-x-p1"}) as restart,
        ):
            resp = _api().post("/api/proxied/x/1/restart", headers=AUTH)
        assert resp.json() == {"status": "restarted", "restarted": "cashpilot-x-p1"}
        restart.assert_called_once_with("x", 1)

    def test_a_start_with_the_proxy_hands_it_to_the_tunnel(self):
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(worker_api, "_detect_egress_ip", return_value="192.0.2.1"),
            patch.object(proxy_tunnel, "start", return_value={"exit": {"ip": "93.184.215.14"}}) as start,
        ):
            resp = _api().post("/api/proxied/x/1/start", json={"proxy": _socks()}, headers=AUTH)
        assert resp.status_code == 200
        slug, pid, proxy, own_ip = start.call_args.args
        assert (slug, pid, proxy["host"], own_ip) == ("x", 1, "203.0.113.9", "192.0.2.1")
        assert proxy == worker_api.ProxySpec(**_socks()).plain()

    def test_a_service_removal_reports_proxied_copies_that_survived(self):
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(orchestrator, "remove_service", return_value={"container": "cashpilot-x"}),
            patch.object(orchestrator, "remove_extra_instances", return_value=[]),
            patch.object(
                proxy_tunnel,
                "remove_all",
                side_effect=proxy_tunnel.ProxyTunnelError("Docker did not remove cashpilot-x-p1"),
            ),
        ):
            resp = _api().delete("/api/containers/x", headers=AUTH)
        assert resp.status_code == 200
        assert "cashpilot-x-p1" in resp.json()["proxied_error"]

    @pytest.mark.parametrize(
        ("exc", "code"),
        [
            (proxy_tunnel.ProxyTunnelError("the proxy refused the login", 502), 502),
            (orchestrator.ContainerNetworkError("no such network"), 409),
            (ValueError("No proxied copy of x through proxy 1 on this worker"), 404),
            (RuntimeError(f"dial socks5://u1:{PASSWORD}@203.0.113.9:1080 failed"), 503),
            (KeyError(PASSWORD), 500),
        ],
    )
    def test_errors_map_to_a_status_and_never_carry_the_password(self, exc, code):
        for method, path in (
            ("post", "/api/proxied/x/1/stop"),
            ("post", "/api/proxied/x/1/start"),
            ("post", "/api/proxied/x/1/restart"),
            ("delete", "/api/proxied/x/1"),
        ):
            with (
                patch.object(worker_api, "_verify_api_key"),
                patch.object(proxy_tunnel, "stop", side_effect=exc),
                patch.object(proxy_tunnel, "start", side_effect=exc),
                patch.object(proxy_tunnel, "restart", side_effect=exc),
                patch.object(proxy_tunnel, "remove", side_effect=exc),
            ):
                resp = getattr(_api(), method)(path, headers=AUTH)
            assert resp.status_code == code, (path, resp.text)
            assert PASSWORD not in resp.text

    def test_a_docker_refusal_is_a_409_without_the_password(self):
        from docker.errors import APIError

        exc = APIError("conflict", explanation=f"bad mount socks5://u1:{PASSWORD}@h:1")
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(proxy_tunnel, "deploy", side_effect=exc),
            patch.object(worker_api, "_validate_deploy_spec"),
            patch.object(worker_api, "_detect_egress_ip", return_value=None),
        ):
            resp = _api().post(
                "/api/proxied/honeygain/3/deploy",
                json={"earner": {"image": "honeygain/honeygain:1"}, "proxy": _socks()},
                headers=AUTH,
            )
        assert resp.status_code == 409
        assert "Docker refused" in resp.text and PASSWORD not in resp.text

    def test_a_runtime_setting_error_keeps_its_status(self):
        exc = orchestrator.ContainerRuntimeError("daemon unreachable")
        exc.status_code = 503
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(worker_api, "_detect_egress_ip", return_value=None),
            patch.object(proxy_tunnel, "test", side_effect=exc),
        ):
            resp = _api().post("/api/proxy-test", json={"proxy": _socks()}, headers=AUTH)
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# stop / start / remove / test on the worker side
# ---------------------------------------------------------------------------


def _client_with(*containers):
    by_name = {c.name: c for c in containers}
    client = MagicMock()

    def get(name):
        if name not in by_name:
            raise NotFound(name)
        return by_name[name]

    client.containers.get.side_effect = get
    return client


class TestPairOps:
    def _pair(self, earner_status="running", tunnel_status="running"):
        earner = _container("cashpilot-x-p1", "x", proxy=1, status=earner_status)
        tunnel = _container("cashpilot-tunnel-x-p1", "x", proxy=1, role="tunnel", status=tunnel_status)
        return earner, tunnel

    def test_stop_takes_the_tunnel_before_its_earner(self):
        earner, tunnel = self._pair()
        order = MagicMock()
        order.attach_mock(earner.stop, "earner")
        order.attach_mock(tunnel.stop, "tunnel")
        with patch.object(orchestrator, "_get_client", return_value=_client_with(earner, tunnel)):
            proxy_tunnel.stop("x", 1)
        assert [c[0] for c in order.mock_calls] == ["tunnel", "earner"]

    def test_a_stop_that_fails_halfway_is_not_undone_by_the_heartbeat(self):
        """A ready tunnel beside a stopped earner is what the heartbeat starts
        again, so a failed stop must never leave that state."""
        for failing in ("tunnel", "earner"):
            earner, tunnel = self._pair()

            def stopped(c):
                return lambda **_kw: setattr(c, "status", "exited")

            earner.stop.side_effect = stopped(earner)
            tunnel.stop.side_effect = stopped(tunnel)
            (tunnel if failing == "tunnel" else earner).stop.side_effect = RuntimeError("daemon timeout")
            with (
                patch.object(orchestrator, "_get_client", return_value=_client_with(earner, tunnel)),
                pytest.raises(RuntimeError),
            ):
                proxy_tunnel.stop("x", 1)
            assert proxy_tunnel.earner_action(earner, tunnel, ready=True) is None, failing

    def test_stop_and_start_refuse_a_copy_that_is_not_ours(self):
        stranger = _container("cashpilot-x-p1", "y", proxy=1)
        with patch.object(orchestrator, "_get_client", return_value=_client_with(stranger)):
            with pytest.raises(ValueError):
                proxy_tunnel.stop("x", 1)
            with pytest.raises(ValueError):
                proxy_tunnel.start("x", 1)
        stranger.stop.assert_not_called()

    def test_start_refreshes_a_stopped_tunnel_and_waits_before_the_earner(self):
        earner, tunnel = self._pair(earner_status="exited", tunnel_status="exited")
        order = MagicMock()
        with (
            patch.object(orchestrator, "_get_client", return_value=_client_with(earner, tunnel)),
            patch.object(proxy_tunnel, "refresh_proxy_ip", side_effect=lambda c: order("refresh")) as refresh,
            patch.object(
                proxy_tunnel, "_wait_ready", side_effect=lambda c: (order("ready"), {"ip": "93.184.215.14"})[1]
            ),
        ):
            tunnel.start.side_effect = lambda: (order("tunnel"), setattr(tunnel, "status", "running"))
            # The earner starts only in the run that wrote /run/ready, read again just before it.
            tunnel.exec_run.return_value = (0, b'{"ip": "93.184.215.14"}')
            earner.start.side_effect = lambda: order("earner")
            out = proxy_tunnel.start("x", 1)
        assert [c.args[0] for c in order.call_args_list] == ["refresh", "tunnel", "ready", "earner"]
        refresh.assert_called_once_with(tunnel)
        earner.restart.assert_not_called()
        assert out == {"exit": {"ip": "93.184.215.14"}}

    def test_start_restarts_an_earner_still_running_in_the_old_namespace(self):
        earner, tunnel = self._pair()
        tunnel.exec_run.return_value = (0, b'{"ip": "93.184.215.14"}')
        with (
            patch.object(orchestrator, "_get_client", return_value=_client_with(earner, tunnel)),
            patch.object(proxy_tunnel, "refresh_proxy_ip") as refresh,
            patch.object(proxy_tunnel, "_wait_ready", return_value={"ip": "93.184.215.14"}),
        ):
            proxy_tunnel.start("x", 1)
        refresh.assert_not_called()
        earner.restart.assert_called_once()
        earner.start.assert_not_called()

    def test_a_legacy_start_whose_tunnel_has_no_exit_now_starts_no_earner(self):
        """_wait_ready saw /run/ready, then the tunnel restarted: the run the earner would join is not proven.
        The start says so instead of answering as if the copy started."""
        earner, tunnel = self._pair(earner_status="exited")
        tunnel.exec_run.return_value = (1, b"")
        with (
            patch.object(orchestrator, "_get_client", return_value=_client_with(earner, tunnel)),
            patch.object(proxy_tunnel, "_wait_ready", return_value={"ip": "93.184.215.14"}),
            pytest.raises(proxy_tunnel.ProxyTunnelError, match="was not started"),
        ):
            proxy_tunnel.start("x", 1)
        earner.start.assert_not_called()
        earner.restart.assert_not_called()

    def test_remove_takes_only_our_containers_and_their_volumes(self):
        earner, _ = self._pair()
        with patch.object(orchestrator, "_get_client", return_value=_client_with(earner)):
            assert proxy_tunnel.remove("x", 1) == ["cashpilot-x-p1"]
        earner.remove.assert_called_once_with(force=True, v=True)

    def test_a_proxy_test_removes_its_tunnel_on_success(self):
        sidecar = MagicMock()
        with (
            patch.object(orchestrator, "_get_client", return_value=MagicMock()),
            patch.object(
                proxy_tunnel, "start_sidecar", return_value=(sidecar, {"ip": "93.184.215.14", "country": "DE"})
            ),
        ):
            out = proxy_tunnel.test(_socks(), None)
        assert out["ip"] == "93.184.215.14" and isinstance(out["ms"], int)
        sidecar.remove.assert_called_once_with(force=True, v=True)


# ---------------------------------------------------------------------------
# An edited proxy reaches its copies; review follow-ups
# ---------------------------------------------------------------------------


def _files_in(blob):
    with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        return {m.name: tar.extractfile(m).read().decode() for m in tar.getmembers()}


class TestStartAppliesTheStoredProxy:
    def _pair(self, earner_status="exited", tunnel_status="exited"):
        earner = _container("cashpilot-x-p1", "x", proxy=1, status=earner_status)
        tunnel = _container("cashpilot-tunnel-x-p1", "x", proxy=1, role="tunnel", status=tunnel_status)
        tunnel.put_archive.return_value = True
        return earner, tunnel

    def test_a_host_that_no_longer_resolves_stops_the_start(self):
        """Keeping the old address would send the proxy login to whoever holds it now."""
        earner, tunnel = self._pair()
        with (
            patch.object(orchestrator, "_get_client", return_value=_client_with(earner, tunnel)),
            patch.object(proxy_tunnel, "_recorded_containers", return_value={earner.name: earner.id}),
            patch.object(proxy_tunnel, "resolve_proxy_ip", side_effect=proxy_tunnel.ProxyTunnelError("no such host")),
            pytest.raises(proxy_tunnel.ProxyTunnelError, match="no such host"),
        ):
            proxy_tunnel.start("x", 1, _socks(host="gw.example.net"), None)
        tunnel.start.assert_not_called()
        tunnel.put_archive.assert_not_called()

    def test_without_the_proxy_a_failed_lookup_stops_the_start_too(self):
        tunnel = MagicMock()
        tunnel.get_archive.return_value = (iter([b""]), {})
        with (
            patch.object(proxy_tunnel, "_read_secret_file", return_value="gw.example.net"),
            patch.object(proxy_tunnel, "resolve_proxy_ip", side_effect=proxy_tunnel.ProxyTunnelError("no such host")),
            pytest.raises(proxy_tunnel.ProxyTunnelError),
        ):
            proxy_tunnel.refresh_proxy_ip(tunnel)
        tunnel.put_archive.assert_not_called()


class TestReviewFollowUps:
    def test_stop_says_whether_the_copy_was_running(self):
        """A legacy pair (its own tunnel) counts as running only live: an older worker's stop left no marker, so
        down and unheld means its owner stopped it, and the cap must not mark it for its reset to start."""
        for earner_status, tunnel_status, was_held, expected in (
            ("running", "running", False, True),
            ("exited", "running", False, True),
            ("exited", "exited", False, False),
            ("exited", "exited", True, False),
        ):
            earner = _container("cashpilot-x-p1", "x", proxy=1, status=earner_status)
            tunnel = _container("cashpilot-tunnel-x-p1", "x", proxy=1, role="tunnel", status=tunnel_status)
            with (
                patch.object(orchestrator, "_get_client", return_value=_client_with(earner, tunnel)),
                patch.object(proxy_tunnel, "held", return_value={"cashpilot-x-p1"} if was_held else set()),
                patch.object(proxy_tunnel, "_set_held"),
            ):
                assert proxy_tunnel.stop("x", 1) == {"was_running": expected}

    def test_no_tunnel_restarts_with_docker(self):
        """A tunnel Docker starts on its own has a namespace open before cp-tunnel's first command (sidecar_kwargs)."""
        with patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": "drumsergio/cashpilot-tunnel:1.64.0"}):
            test_kw = proxy_tunnel.sidecar_kwargs("cashpilot-tunnel-test-ab", proxy_tunnel.TEST_SLUG, None, None, "t")
            copy_kw = proxy_tunnel.sidecar_kwargs("cashpilot-tunnel-p1", proxy_tunnel.SHARED_SLUG, 1, None, "p1")
        assert test_kw["restart_policy"] == {"Name": "no"}
        assert copy_kw["restart_policy"] == {"Name": "no"}

    def test_leftover_test_tunnels_are_swept_and_copies_are_not(self):
        leftover = _container("cashpilot-tunnel-test-ab", proxy_tunnel.TEST_SLUG, role="tunnel")
        copy_tunnel = _container("cashpilot-tunnel-proxy-test-p1", proxy_tunnel.TEST_SLUG, proxy=1, role="tunnel")
        client = MagicMock()
        client.containers.list.return_value = [leftover, copy_tunnel]
        with patch.object(orchestrator, "_get_client", return_value=client):
            assert proxy_tunnel.sweep_test_tunnels() == ["cashpilot-tunnel-test-ab"]
        leftover.remove.assert_called_once_with(force=True, v=True)
        copy_tunnel.remove.assert_not_called()

    def test_a_test_tunnel_younger_than_the_worker_is_left_to_its_test(self):
        """A worker that started without Docker sweeps with its API serving (worker_api._wait_for_docker_loop)."""
        leftover = _container("cashpilot-tunnel-test-ab", proxy_tunnel.TEST_SLUG, role="tunnel")
        in_flight = _container("cashpilot-tunnel-test-cd", proxy_tunnel.TEST_SLUG, role="tunnel")
        in_flight.attrs["Created"] = (datetime.now(UTC) - timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
        client = MagicMock()
        client.containers.list.side_effect = [[leftover, in_flight], []]
        with patch.object(orchestrator, "_get_client", return_value=client):
            assert proxy_tunnel.sweep_test_tunnels(min_age=600) == ["cashpilot-tunnel-test-ab"]
        in_flight.remove.assert_not_called()

    def test_a_staged_sidecar_of_a_deploy_that_died_is_swept(self):
        staged = _container("cashpilot-tunnel-x-p1-next", "x", proxy=1, role="tunnel")
        live = _container("cashpilot-tunnel-x-p1", "x", proxy=1, role="tunnel")
        client = MagicMock()
        answers = iter([[], [staged, live]])
        client.containers.list.side_effect = lambda **_kw: next(answers, [])
        with patch.object(orchestrator, "_get_client", return_value=client):
            assert proxy_tunnel.sweep_test_tunnels() == ["cashpilot-tunnel-x-p1-next"]
        live.remove.assert_not_called()

    def test_a_young_staged_sidecar_is_left_to_its_deploy(self):

        young = _container("cashpilot-tunnel-x-p1-next", "x", proxy=1, role="tunnel")
        young.attrs["Created"] = datetime.now(UTC).isoformat().replace("+00:00", "123Z")
        client = MagicMock()
        client.containers.list.side_effect = [[], [young]]
        with patch.object(orchestrator, "_get_client", return_value=client):
            assert proxy_tunnel.sweep_test_tunnels() == []
        young.remove.assert_not_called()

    def test_two_deploys_of_one_copy_take_turns(self):
        import threading

        inside, overlap = [], []
        gate = threading.Event()

        def slow(*_a, **_kw):
            if inside:
                overlap.append(True)
            inside.append(True)
            gate.wait(0.2)
            inside.pop()
            return {}

        with patch.object(proxy_tunnel, "_deploy", side_effect=slow):
            threads = [threading.Thread(target=proxy_tunnel.deploy, args=("x", 1, {}, {}, None)) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        assert not overlap

    def test_a_probe_answer_that_is_not_an_ip_is_not_ready(self):
        sidecar = MagicMock(status="running")
        sidecar.exec_run.return_value = (0, b'{"ip":"e","country":""}\n')
        assert proxy_tunnel._read_exit(sidecar) is None
        sidecar.exec_run.return_value = (0, b'{"ip":"93.184.215.14","country":"DE"}\n')
        assert proxy_tunnel._read_exit(sidecar)["ip"] == "93.184.215.14"

    def test_an_unversioned_worker_has_no_tunnel_image(self):
        with (
            patch.dict(os.environ, {"CASHPILOT_VERSION": "latest", "CASHPILOT_TUNNEL_IMAGE": ""}),
            pytest.raises(proxy_tunnel.ProxyTunnelError),
        ):
            proxy_tunnel.tunnel_image()

    @pytest.mark.parametrize(
        "server", ["https://u:p@hs.example", "https://hs.example/?k=v", "https://hs.example/#x", "https://@hs.example"]
    )
    def test_a_login_server_with_a_secret_part_is_refused(self, server):
        with patch.object(worker_api, "_verify_api_key"):
            resp = _api().post("/api/proxy-test", json={"proxy": _tailscale(login_server=server)}, headers=AUTH)
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# A stopped tunnel leaves no tailnet device behind
# ---------------------------------------------------------------------------

_CP_TUNNEL = (Path(__file__).resolve().parent.parent / "tunnel" / "cp-tunnel").read_text()
_CP_PROBE = Path(__file__).resolve().parent.parent / "tunnel" / "cp-probe"
#: For a test of one step on its own: every step gets its full cap, as before the deadline is near.
_NO_DEADLINE = 'cap() { echo "$1"; }\n'


def _logout_seconds() -> int:
    """How long cp-tunnel gives ``tailscale logout`` when it is stopped."""
    found = re.search(r"timeout (\d+) tailscale --socket=\S+ logout", _CP_TUNNEL)
    assert found, "cp-tunnel no longer logs out of the tailnet when it is stopped"
    return int(found.group(1))


class TestATunnelLogsOutOfTheTailnetWhenStopped:
    """Killed before its logout, a tunnel's ephemeral device stays in the
    tailnet offline, and the next start of that copy joins as "<name>-1"."""

    def test_the_tunnel_logs_out_on_a_stop(self):
        assert re.search(r"^trap leave TERM INT$", _CP_TUNNEL, re.M)
        leave = _CP_TUNNEL.split("leave() {", 1)[1].split("\n}", 1)[0]
        assert "logout" in leave and "exit 0" in leave

    def _stop_timeout(self, container):
        container.stop.assert_called_once()
        return container.stop.call_args.kwargs["timeout"]

    def test_a_proxy_test_gives_its_tunnel_time_to_log_out(self):
        sidecar = MagicMock()
        with (
            patch.object(orchestrator, "_get_client", return_value=MagicMock()),
            patch.object(proxy_tunnel, "start_sidecar", return_value=(sidecar, {"ip": "93.184.215.14"})),
        ):
            proxy_tunnel.test(_socks(), None)
        assert self._stop_timeout(sidecar) > _logout_seconds()

    def test_a_tunnel_that_fails_to_start_gets_time_to_log_out(self):
        client = MagicMock()
        created = MagicMock(id="sidecar-id", status="exited")
        created.put_archive.return_value = True
        created.logs.return_value = b"the exit node refused"
        client.containers.create.return_value = created
        with (
            patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": "drumsergio/cashpilot-tunnel:1.64.0"}),
            patch.object(orchestrator, "container_network", return_value=None),
            pytest.raises(proxy_tunnel.ProxyTunnelError),
        ):
            proxy_tunnel.start_sidecar(client, "cashpilot-tunnel-x-p1", "x", 1, _socks(), None)
        assert self._stop_timeout(created) > _logout_seconds()

    def test_a_swept_test_tunnel_gets_time_to_log_out(self):
        leftover = _container("cashpilot-tunnel-test-ab", proxy_tunnel.TEST_SLUG, role="tunnel")
        client = MagicMock()
        client.containers.list.side_effect = [[leftover], []]
        with patch.object(orchestrator, "_get_client", return_value=client):
            proxy_tunnel.sweep_test_tunnels()
        assert self._stop_timeout(leftover) > _logout_seconds()

    def test_a_removed_copy_gives_its_tunnel_time_to_log_out(self):
        earner = _container("cashpilot-x-p1", "x", proxy=1)
        tunnel = _container("cashpilot-tunnel-x-p1", "x", proxy=1, role="tunnel")
        with patch.object(orchestrator, "_get_client", return_value=_client_with(earner, tunnel)):
            proxy_tunnel.remove("x", 1)
        assert self._stop_timeout(tunnel) > _logout_seconds()


# ---------------------------------------------------------------------------
# cp-tunnel's firewall: the older rule when nft refuses the cgroup one
# ---------------------------------------------------------------------------


def _run_firewall_step(tmp_path: Path, nft_mode: str) -> tuple[int, str, str]:
    """Run cp-tunnel up to its rules being loaded, with stub ip, stat, nft and curl.

    ``nft_mode``: ``match`` (the cgroup rule loads and counts the probe),
    ``no-cgroup`` (nft refuses any rule set naming cgroupv2), ``refuse`` (it
    refuses every rule set).
    """
    import subprocess

    run = tmp_path / "run"
    secret = run / "cashpilot-secret"
    secret.mkdir(parents=True)
    for key, value in {"kind": "socks5", "proxy_ip": "203.0.113.5", "proxy_port": "1080"}.items():
        (secret / key).write_text(value)
    (tmp_path / "cgroup").write_text("0::/docker/abc\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stubs = {
        "ip": 'echo "default via 172.17.0.1 dev eth0"',
        "stat": "echo cgroup2fs",
        "curl": "exit 0",
        "nft": f"""
loaded={run}/loaded.nft
if [ "$1" = -f ]; then
    case {nft_mode} in
    refuse) echo "nft: refused" >&2; exit 1 ;;
    no-cgroup) if grep -q cgroupv2 "$2"; then echo "nft: no cgroupv2" >&2; exit 1; fi ;;
    esac
    cp "$2" "$loaded"
    exit 0
fi
if [ {nft_mode} = match ]; then sed 's/counter/counter packets 1 bytes 60/' "$loaded"; else cat "$loaded"; fi
""",
    }
    for name, body in stubs.items():
        (bin_dir / name).write_text(f"#!/bin/sh\n{body}\n")
        (bin_dir / name).chmod(0o755)
    head = _CP_TUNNEL.split("probe_until_ready() {")[0]
    assert "load_rules" in head
    script = (
        head.replace("/run/", f"{run}/")
        .replace("/run\n", f"{run}\n")
        .replace("/proc/self/cgroup", str(tmp_path / "cgroup"))
    )
    script += f'\necho RULES_LOADED\ncat "{run}/loaded.nft"\n'
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    proc = subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True, timeout=30)
    return proc.returncode, proc.stdout, proc.stderr


class TestTheTunnelFirewallFallsBack:
    def test_a_kernel_that_matches_gets_the_cgroup_rule(self, tmp_path):
        code, out, _err = _run_firewall_step(tmp_path, "match")
        assert code == 0 and "RULES_LOADED" in out
        assert "socket cgroupv2" in out

    def test_an_nft_that_refuses_the_cgroup_rule_gets_the_older_rule(self, tmp_path):
        code, out, err = _run_firewall_step(tmp_path, "no-cgroup")
        assert code == 0, err
        assert "socket cgroupv2" not in out
        assert 'oifname "eth0" ip daddr 203.0.113.5 tcp dport 1080 accept' in out
        assert "policy drop" in out
        assert "can reach the proxy directly too" in err

    def test_an_nft_that_refuses_every_rule_keeps_the_tunnel_down(self, tmp_path):
        code, out, err = _run_firewall_step(tmp_path, "refuse")
        assert code != 0 and "RULES_LOADED" not in out
        assert "refusing to start" in err


def _run_until_rules_logged(tmp_path: Path) -> tuple[int, list[str], str]:
    """Run cp-tunnel up to its rules being loaded, logging every settings read, route read and nft load in order."""
    import shutil
    import subprocess

    run = tmp_path / "run"
    secret = run / "cashpilot-secret"
    secret.mkdir(parents=True)
    for key, value in {"kind": "socks5", "proxy_ip": "203.0.113.5", "proxy_port": "1080"}.items():
        (secret / key).write_text(value)
    events = tmp_path / "events"
    real_cat = shutil.which("cat")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stubs = {
        "cat": f'case "$*" in *cashpilot-secret*) echo "read $*" >>{events} ;; esac\nexec {real_cat} "$@"',
        "ip": f'echo "ip $*" >>{events}\necho "default via 172.17.0.1 dev eth0"',
        "stat": "echo tmpfs",
        "nft": f'if [ "$1" = -f ]; then echo "nft-load" >>{events}; {real_cat} "$2" >>{events}; fi',
    }
    for name, body in stubs.items():
        (bin_dir / name).write_text(f"#!/bin/sh\n{body}\n")
        (bin_dir / name).chmod(0o755)
    head = _CP_TUNNEL.split("probe_until_ready() {")[0]
    script = head.replace("/run/", f"{run}/").replace("/run\n", f"{run}\n")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    proc = subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True, timeout=30)
    return proc.returncode, events.read_text().splitlines() if events.exists() else [], proc.stderr


def _first_ruleset(lines: list[str]) -> str:
    start = lines.index("nft-load") + 1
    end = next((i for i in range(start, len(lines)) if lines[i] == "nft-load"), len(lines))
    return "\n".join(lines[start:end])


class TestTheTunnelClosesItsNamespaceFirst:
    """A tunnel run started by hand (Docker starts none by itself any more): an earner started into it before
    cp-tunnel had read its settings, set its routes and loaded its rules could send from the box's own address."""

    def test_the_first_thing_loaded_is_a_table_that_lets_nothing_out(self, tmp_path):
        code, lines, err = _run_until_rules_logged(tmp_path)
        assert code == 0, err
        assert lines and lines[0] == "nft-load", f"something ran before the first nft load: {lines[:3]}"
        first = _first_ruleset(lines)
        out = first.split("chain out {", 1)[1].split("}", 1)[0]
        assert "policy drop;" in out and "accept" not in out
        inbound = first.split("chain in {", 1)[1].split("}", 1)[0]
        assert "policy drop;" in inbound and "accept" not in inbound
        # The real rules replace it in one transaction, on the same table.
        assert "delete table inet cashpilot" in first
        assert lines.count("nft-load") == 2
        real = "\n".join(lines[len(lines) - lines[::-1].index("nft-load") :])
        assert 'oifname "eth0" ip daddr 203.0.113.5 tcp dport 1080 accept' in real

    def test_no_setting_or_route_is_read_before_it(self, tmp_path):
        _code, lines, _err = _run_until_rules_logged(tmp_path)
        before = lines[: lines.index("nft-load")]
        assert not [e for e in before if e.startswith(("read ", "ip "))]
        # Control: the settings and the routes are read, after it.
        assert any(e.startswith("read ") for e in lines) and any(e.startswith("ip ") for e in lines)

    def test_ready_is_written_only_after_the_real_rules(self):
        """/run/ready is written by the probe alone, which starts after the real rules are loaded."""
        assert _CP_TUNNEL.count("/run/ready.tmp /run/ready") == 1
        assert _CP_TUNNEL.index("nft -f /run/cp-tunnel-closed.nft") < _CP_TUNNEL.index("KIND=$(read_key kind)")
        probe = _CP_TUNNEL.index("(probe_until_ready ||")
        assert _CP_TUNNEL.rindex("load_rules ||") < probe

    def test_a_closing_table_nft_refuses_keeps_the_tunnel_down(self, tmp_path):
        """Not closed, never started: nothing below may run on an open namespace."""
        import subprocess

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "nft").write_text("#!/bin/sh\nexit 1\n")
        (bin_dir / "nft").chmod(0o755)
        (bin_dir / "ip").write_text(f"#!/bin/sh\ntouch {tmp_path}/routes-read\n")
        (bin_dir / "ip").chmod(0o755)
        (tmp_path / "run").mkdir()
        head = _CP_TUNNEL.split("probe_until_ready() {")[0].replace("/run/", f"{tmp_path}/run/")
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
        proc = subprocess.run(["sh", "-c", head], env=env, capture_output=True, text=True, timeout=30)
        assert proc.returncode != 0 and "refusing to start" in proc.stderr
        assert not (tmp_path / "routes-read").exists()


# ---------------------------------------------------------------------------
# cp-tunnel: when names go back to the proxy (--dns virtual)
# ---------------------------------------------------------------------------


def _proxy_refuses_dns(tmp_path: Path, scheme: str, first_rc: int, out: str, rc: int) -> bool:
    """Run cp-tunnel's proxy_refuses_dns with a stub curl.

    The stub answers the first request (the proxy carries a connection) with
    ``first_rc``, and the request to port 53 by printing ``out`` (what its
    ``-w`` asks for) and exiting ``rc``. The values are what curl 8 gives:
    checked against a SOCKS5 proxy that refuses (97, pretransfer 0), stalls the
    CONNECT (28, pretransfer 0), connects and then hears nothing (28,
    pretransfer > 0), or connects and is closed (56, pretransfer > 0).
    """
    import subprocess

    start = _CP_TUNNEL.index("    proxy_refuses_dns() {")
    body = _CP_TUNNEL[start : _CP_TUNNEL.index("\n    }\n", start) + len("\n    }\n")]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "curl").write_text(
        '#!/bin/sh\ncase "$*" in *:53/*) printf %s "$STUB_OUT"; exit "$STUB_RC" ;; esac\nexit "$STUB_FIRST"\n'
    )
    (bin_dir / "curl").chmod(0o755)
    script = (
        f'read_key() {{ case "$1" in proxy_scheme) echo {scheme} ;; *) echo ;; esac; }}\n'
        f"{_NO_DEADLINE}PROXY_IP=203.0.113.5 PROXY_PORT=1080 DNS_TARGET=1.1.1.1\n"
        f"{body}\nproxy_refuses_dns\n"
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "STUB_FIRST": str(first_rc),
        "STUB_OUT": out,
        "STUB_RC": str(rc),
    }
    proc = subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True, timeout=30)
    return proc.returncode == 0


class TestTheTunnelFallsBackToProxyDns:
    @pytest.mark.parametrize(
        ("scheme", "out", "rc"),
        [
            ("socks5", "0.000000", 97),  # refused
            ("socks5", "0.000000", 28),  # the CONNECT to port 53 stalls past 6 s
            ("http", "403", 56),  # refused
            ("http", "000", 28),  # no answer to the CONNECT within 6 s
            ("http", "000", 52),  # closed without an answer
        ],
    )
    def test_a_working_proxy_that_will_not_open_port_53(self, tmp_path, scheme, out, rc):
        assert _proxy_refuses_dns(tmp_path, scheme, 0, out, rc)

    @pytest.mark.parametrize(
        ("scheme", "out", "rc"),
        [
            ("socks5", "0.005044", 28),  # connected; the resolver ignores the HTTP request
            ("socks5", "0.008344", 56),  # connected; the resolver closes
            ("http", "200", 52),
            ("http", "200", 28),
        ],
    )
    def test_control_a_proxy_that_opens_port_53_keeps_dns_over_tcp(self, tmp_path, scheme, out, rc):
        assert not _proxy_refuses_dns(tmp_path, scheme, 0, out, rc)

    @pytest.mark.parametrize("scheme", ["socks5", "http"])
    def test_control_a_proxy_that_is_down_never_switches(self, tmp_path, scheme):
        assert not _proxy_refuses_dns(tmp_path, scheme, 7, "0.000000" if scheme == "socks5" else "000", 28)


def _dns_rounds(tmp_path: Path, resolves: str, step: int) -> list[str]:
    """Run cp-tunnel's wait for DNS before the probe, with stub getent, date and a proxy that allows port 53.

    ``resolves``: the names the resolver answers. The stub clock moves ``step``
    seconds each time it is read. Returns the names asked, in order.
    """
    import subprocess

    start = _CP_TUNNEL.index("    start_tun2proxy over-tcp\n") + len("    start_tun2proxy over-tcp\n")
    loop = _CP_TUNNEL[start : _CP_TUNNEL.index("\n    done\n", start) + len("\n    done\n")]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    asked = tmp_path / "asked"
    clock = tmp_path / "clock"
    clock.write_text("0")
    stubs = {
        "getent": f'echo "$2" >>{asked}\ncase " $STUB_RESOLVES " in *" $2 "*) exit 0 ;; esac\nexit 2',
        "date": f"t=$(cat {clock})\necho $((t + {step})) >{clock}\necho $t",
        "timeout": 'shift\nexec "$@"',
        "sleep": "exit 0",
    }
    for name, body in stubs.items():
        (bin_dir / name).write_text(f"#!/bin/sh\n{body}\n")
        (bin_dir / name).chmod(0o755)
    script = f"{_NO_DEADLINE}proxy_refuses_dns() {{ return 1; }}\n/bin/sleep 30 &\nTPID=$!\n{loop}kill $TPID\n"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "STUB_RESOLVES": resolves}
    proc = subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return asked.read_text().split() if asked.exists() else []


def _dns_mode_after_wait(tmp_path: Path, blocked: str, **stubs_over: str) -> list[str]:
    """Run cp-tunnel's wait with its real proxy_refuses_dns, against an HTTP proxy that refuses port 53.

    No name resolves (over-tcp DNS needs port 53). ``blocked``: the names the
    proxy will not carry. ``stubs_over`` replaces stub commands by name. Returns
    the DNS modes tun2proxy was started again with; the clock reading at each
    restart is written to ``tmp_path / "switched"``.
    """
    import subprocess

    start = _CP_TUNNEL.index("    proxy_refuses_dns() {")
    body = _CP_TUNNEL[start : _CP_TUNNEL.index("\n    }\n", start) + len("\n    }\n")]
    begin = _CP_TUNNEL.index("    start_tun2proxy over-tcp\n") + len("    start_tun2proxy over-tcp\n")
    loop = _CP_TUNNEL[begin : _CP_TUNNEL.index("\n    done\n", begin) + len("\n    done\n")]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    clock = tmp_path / "clock"
    clock.write_text("0")
    modes = tmp_path / "modes"
    stubs = {
        "getent": "exit 2",
        "date": f"t=$(cat {clock})\necho $((t + 1)) >{clock}\necho $t",
        "timeout": 'shift\nexec "$@"',
        "sleep": "exit 0",
        "ip": "exit 0",
        "curl": 'case "$*" in *:53/*) printf 403; exit 56 ;; esac\n'
        'for n in $STUB_BLOCKED; do case "$*" in *"https://$n/"*) exit 7 ;; esac; done\nexit 0',
        **stubs_over,
    }
    for name, stub in stubs.items():
        (bin_dir / name).write_text(f"#!/bin/sh\n{stub}\n")
        (bin_dir / name).chmod(0o755)
    script = (
        'read_key() { case "$1" in proxy_scheme) echo http ;; *) echo ;; esac; }\n'
        f"{_NO_DEADLINE}PROXY_IP=203.0.113.5 PROXY_PORT=3128 DNS_TARGET=1.1.1.1\n"
        f'start_tun2proxy() {{ echo "$1" >>{modes}; date +%s >>{tmp_path / "switched"}; /bin/sleep 30 & TPID=$!; }}\n'
        f"{body}\n/bin/sleep 30 &\nTPID=$!\n{loop}kill $TPID\n"
    )
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "STUB_BLOCKED": blocked}
    proc = subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return modes.read_text().split() if modes.exists() else []


class TestTheTunnelFallsBackOnAnyProbeEndpoint:
    def test_a_proxy_that_blocks_one_endpoint_still_gets_proxy_dns(self, tmp_path):
        """It refuses port 53 and api.ipify.org: the same round asks through it for the other two, and works."""
        assert _dns_mode_after_wait(tmp_path, "api.ipify.org") == ["virtual"]

    def test_stalls_on_two_endpoints_and_on_port_53_still_reach_the_third_in_time(self, tmp_path):
        """Each stall costs its 6 s. Asked one per round, icanhazip.com came in a round the 15 s bound never started.

        The clock runs five times real time, so the 6 s stalls are 1.2 s sleeps.
        """
        import time

        stall = "/bin/sleep 1.2; printf 000; exit 28"
        modes = _dns_mode_after_wait(
            tmp_path,
            "",
            # Perl, not Python: pytest-cov hooks every Python child, which made the clock itself slow.
            date=f"exec perl -MTime::HiRes=time -e 'printf \"%d\\n\", (time - {time.time()}) * 5'",
            getent="/bin/sleep 1.2; exit 2",
            curl=f'case "$*" in *:53/*|*https://api.ipify.org/*|*https://ifconfig.me/*) {stall} ;; esac\nexit 0',
            sleep="/bin/sleep 0.2",
        )
        assert modes == ["virtual"]
        # One round of three 6 s stalls, so the exit probe keeps most of the worker's 45 s wait.
        assert int((tmp_path / "switched").read_text()) < 30

    def test_control_a_proxy_that_carries_nothing_keeps_dns_over_tcp(self, tmp_path):
        assert _dns_mode_after_wait(tmp_path, "api.ipify.org ifconfig.me icanhazip.com") == []


def _ready_at_worst_case(tmp_path: Path) -> tuple[int | None, list[str]]:
    """Run cp-tunnel from its deadline to /run/ready, with the real cp-probe, against the slowest working proxy.

    An HTTP proxy that refuses port 53, so names are not resolved until the
    switch: the first round's lookup stalls its 6 s, the liveness requests
    stall their 6 s (asked at once, so one stub stall stands for them), and the
    port 53 check stalls its 6 s. Then the probe: the first two endpoints stall
    their 8 s, the third answers in 4 s, and the country lookup stalls its 8 s.
    Every stall lasts what its timeout allows, on a stub clock that a stall
    moves on. Returns the clock when /run/ready was written (None if never)
    and the DNS modes started.
    """
    import subprocess

    def part(start_marker: str, end_marker: str) -> str:
        start = _CP_TUNNEL.index(start_marker)
        return _CP_TUNNEL[start : _CP_TUNNEL.index(end_marker, start) + len(end_marker)]

    deadline = part("DEADLINE=", "\n}\n")
    ready = tmp_path / "ready"
    probe = part("probe_until_ready() {", "\n}\n").replace("/run/ready", str(ready))
    refuses = part("    proxy_refuses_dns() {", "\n    }\n")
    begin = _CP_TUNNEL.index("    start_tun2proxy over-tcp\n") + len("    start_tun2proxy over-tcp\n")
    loop = _CP_TUNNEL[begin : _CP_TUNNEL.index("\n    done\n", begin) + len("\n    done\n")]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    clock = tmp_path / "clock"
    clock.write_text("0")
    modes = tmp_path / "modes"
    nap = f"nap() {{ echo $(($(cat {clock}) + $1)) >{clock}; }}\n"
    stubs = {
        "date": f"cat {clock}",
        "timeout": 'export STUB_LIMIT="$1"\nshift\nexec "$@"',
        "getent": f'{nap}nap "$STUB_LIMIT"\nexit 2',
        "sleep": f'{nap}nap "$1"',
        "curl": nap + 'm=\nprev=\nfor a in "$@"; do case "$prev" in -m | --max-time) m=$a ;; esac; prev=$a; done\n'
        'case "$*" in\n'
        '*" -x "*https://icanhazip.com/* | *" -x "*https://ifconfig.me/*) exit 0 ;;\n'
        '*"https://icanhazip.com") if [ "$m" -ge 4 ]; then nap 4; echo 203.0.113.7; exit 0; fi ;;\n'
        "esac\n"
        # A stall writes nothing but what -w asks for: no answer to the CONNECT.
        'nap "$m"\ncase "$*" in *:53/*) printf 000 ;; esac\nexit 28',
    }
    for name, stub in stubs.items():
        (bin_dir / name).write_text(f"#!/bin/sh\n{stub}\n")
        (bin_dir / name).chmod(0o755)
    (bin_dir / "cp-probe").write_text(_CP_PROBE.read_text())
    (bin_dir / "cp-probe").chmod(0o755)
    script = (
        'read_key() { case "$1" in proxy_scheme) echo http ;; *) echo ;; esac; }\n'
        "PROXY_IP=203.0.113.5 PROXY_PORT=3128 DNS_TARGET=1.1.1.1 OWN_IP=198.51.100.1\n"
        f"{deadline}{probe}"
        f'start_tun2proxy() {{ echo "$1" >>{modes}; /bin/sleep 30 & TPID=$!; }}\n'
        f"{refuses}\n/bin/sleep 30 &\nTPID=$!\n{loop}"
        f"probe_until_ready && date +%s >{tmp_path / 'ready_at'}\n"
        "kill $TPID\n"
    )
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    proc = subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    at = tmp_path / "ready_at"
    return (int(at.read_text()) if at.exists() else None), (modes.read_text().split() if modes.exists() else [])


class TestTheWholeWayToReadyFitsTheWorkersWait:
    def test_the_slowest_working_proxy_is_ready_before_45_seconds(self, tmp_path):
        """Each step alone fits; added up they took 46 s, past the worker's 45 s (proxy_tunnel.READY_TIMEOUT)."""
        ready_at, modes = _ready_at_worst_case(tmp_path)
        assert modes == ["virtual"]  # the worst case: names only after the switch
        assert ready_at is not None and ready_at < proxy_tunnel.READY_TIMEOUT
        assert '"ip":"203.0.113.7"' in (tmp_path / "ready").read_text()


def _stub_clock_bin(tmp_path: Path, curl_cases: str) -> tuple[Path, Path]:
    """Stub date, sleep and curl on a clock that a wait moves on; ``curl_cases`` is a case body on the URL ($*)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    clock = tmp_path / "clock"
    clock.write_text("0")
    nap = f"nap() {{ echo $(($(cat {clock}) + $1)) >{clock}; }}\n"
    stubs = {
        "date": f"cat {clock}",
        "sleep": f'{nap}nap "$1"',
        "curl": nap + 'm=\nprev=\nfor a in "$@"; do case "$prev" in -m | --max-time) m=$a ;; esac; prev=$a; done\n'
        f'now=$(cat {clock})\ncase "$*" in\n{curl_cases}esac\n'
        # Anything else stalls for all the time it is given.
        'nap "$m"\nexit 28',
    }
    for name, stub in stubs.items():
        (bin_dir / name).write_text(f"#!/bin/sh\n{stub}\n")
        (bin_dir / name).chmod(0o755)
    (bin_dir / "cp-probe").write_text(_CP_PROBE.read_text())
    (bin_dir / "cp-probe").chmod(0o755)
    return bin_dir, clock


class TestTheProbeNeverRunsPastTheWorkersWait:
    """The worker reads /run/ready for 45 s, 5 s past cp-tunnel's 40 s deadline.
    A step started in those 5 s used to get its full cap again, and the country
    lookup its 8 s, so an exit IP found there was written after the worker had
    given up on a proxy that works."""

    @pytest.mark.parametrize("start", range(30, 43))
    def test_an_answer_found_before_the_wait_ends_is_printed_before_it(self, tmp_path, start):
        """api.ipify.org stalls, ifconfig.me answers in 1 s, the country stalls."""
        import subprocess

        bin_dir, clock = _stub_clock_bin(
            tmp_path, '*https://ifconfig.me/ip*) if [ "$m" -ge 1 ]; then nap 1; echo 203.0.113.7; exit 0; fi ;;\n'
        )
        clock.write_text(str(start))
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "CP_DEADLINE": "40"}
        proc = subprocess.run(["sh", str(bin_dir / "cp-probe")], env=env, capture_output=True, text=True, timeout=30)
        assert proc.returncode == 0, proc.stderr
        assert '"ip":"203.0.113.7"' in proc.stdout
        assert int(clock.read_text()) < proxy_tunnel.READY_TIMEOUT

    def test_control_after_the_wait_the_country_gets_its_full_time(self, tmp_path):
        """Nobody waits any more: the country lookup gets its 8 s and labels the answer."""
        import subprocess

        bin_dir, clock = _stub_clock_bin(
            tmp_path,
            "*https://api.ipify.org*) echo 203.0.113.7; exit 0 ;;\n"
            '*ipinfo.io*) if [ "$m" -ge 8 ]; then echo ES; exit 0; fi ;;\n',
        )
        clock.write_text("46")
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "CP_DEADLINE": "40"}
        proc = subprocess.run(["sh", str(bin_dir / "cp-probe")], env=env, capture_output=True, text=True, timeout=30)
        assert proc.stdout.strip() == '{"ip":"203.0.113.7","country":"ES"}'

    def test_a_second_attempt_after_the_deadline_is_ready_inside_the_wait(self, tmp_path):
        """Attempt 1 fails on all three endpoints (8 + 8 + 4 s) and ends at the deadline;
        attempt 2 starts at 41, api.ipify.org answers in 1 s and the country stalls."""
        import subprocess

        start = _CP_TUNNEL.index("DEADLINE=")
        deadline = _CP_TUNNEL[start : _CP_TUNNEL.index("\n}\n", start) + 3]
        start = _CP_TUNNEL.index("probe_until_ready() {")
        ready = tmp_path / "ready"
        probe = _CP_TUNNEL[start : _CP_TUNNEL.index("\n}\n", start) + 3].replace("/run/ready", str(ready))
        bin_dir, clock = _stub_clock_bin(
            tmp_path, '*https://api.ipify.org*) if [ "$now" -ge 41 ]; then nap 1; echo 203.0.113.7; exit 0; fi ;;\n'
        )
        script = f"OWN_IP=198.51.100.1\n{deadline}echo 20 >{clock}\n{probe}probe_until_ready\n"
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
        proc = subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True, timeout=30)
        assert proc.returncode == 0, proc.stderr
        assert '"ip":"203.0.113.7"' in ready.read_text()
        assert int(clock.read_text()) < proxy_tunnel.READY_TIMEOUT

    def test_both_scripts_count_until_the_workers_wait_ends(self):
        """cp-tunnel's deadline plus the grace both caps keep after it is the worker's 45 s."""
        margin = re.search(r"^DEADLINE=\$\(\(\$\(date \+%s\) \+ (\d+)\)\)$", _CP_TUNNEL, re.M)
        assert margin
        for text in (_CP_TUNNEL, _CP_PROBE.read_text()):
            grace = re.findall(r'\[ "\$left" -lt -(\d+) \]', text)
            assert grace and {int(g) for g in grace} == {int(proxy_tunnel.READY_TIMEOUT) - int(margin.group(1))}


class TestTheTunnelWaitsForDnsInsideTheReadyBudget:
    def test_another_probe_endpoint_that_resolves_ends_the_wait(self, tmp_path):
        """A resolver that fails api.ipify.org only: cp-probe reaches ifconfig.me, so the wait stops there."""
        assert _dns_rounds(tmp_path, "ifconfig.me icanhazip.com", step=1) == ["api.ipify.org", "ifconfig.me"]

    def test_no_round_starts_after_15_seconds(self, tmp_path):
        """No name resolves and each round takes about 4 s: the probe still starts inside the worker's 45 s."""
        assert _dns_rounds(tmp_path, "", step=4) == ["api.ipify.org", "ifconfig.me", "icanhazip.com"]

    def test_control_a_resolver_that_answers_ends_the_wait_at_once(self, tmp_path):
        assert _dns_rounds(tmp_path, "api.ipify.org ifconfig.me icanhazip.com", step=1) == ["api.ipify.org"]
