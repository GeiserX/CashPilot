"""Proxied copies on the worker side (app/proxy_tunnel.py, docs/proxies.md).

The Docker SDK is mocked. What is proved against a real daemon (fail closed,
DNS, no password in docker inspect) lives in scripts/proxy_leak_test.sh.
"""

from __future__ import annotations

import io
import os
import tarfile
from unittest.mock import MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

pytest.importorskip("docker")

from docker.errors import NotFound  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import orchestrator, proxy_tunnel, worker_api  # noqa: E402
from app.constants import LABEL_INSTANCE, LABEL_MANAGED, LABEL_PROXY, LABEL_ROLE, LABEL_SERVICE  # noqa: E402

PASSWORD = "s3cr3t-p@ss"
AUTH_KEY = "tskey-auth-kTEST-0123456789"


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
    c.attrs = {"Created": "2026-11-04T00:00:00Z", "State": {"StartedAt": "2026-11-04T10:00:00Z"}}
    c.image.tags = [f"{slug}:1"]
    return c


# ---------------------------------------------------------------------------
# The orchestrator never mistakes a proxied copy for copy N of its service
# ---------------------------------------------------------------------------


class TestCopiesAreNotProxied:
    def test_find_container_fallback_skips_a_proxied_copy(self):
        proxied = _container("cashpilot-honeygain-p3", "honeygain", proxy=3)
        tunnel = _container("cashpilot-tunnel-honeygain-p3", "honeygain", proxy=3, role="tunnel")
        client = MagicMock()
        client.containers.get.side_effect = NotFound("gone")
        client.containers.list.return_value = [proxied, tunnel]
        with patch.object(orchestrator, "_get_client", return_value=client), pytest.raises(ValueError):
            orchestrator._find_container("honeygain", 1)

    def test_find_container_picks_the_real_first_copy(self):
        proxied = _container("cashpilot-honeygain-p3", "honeygain", proxy=3)
        real = _container("cashpilot-honeygain-renamed", "honeygain")
        client = MagicMock()
        client.containers.get.side_effect = NotFound("gone")
        client.containers.list.return_value = [proxied, real]
        with patch.object(orchestrator, "_get_client", return_value=client):
            assert orchestrator._find_container("honeygain", 1) is real

    def test_service_instances_leaves_out_proxied_copies_and_tunnels(self):
        real = _container("cashpilot-honeygain", "honeygain")
        second = _container("cashpilot-honeygain-2", "honeygain", instance=2)
        proxied = _container("cashpilot-honeygain-p3", "honeygain", proxy=3)
        tunnel = _container("cashpilot-tunnel-honeygain-p3", "honeygain", proxy=3, role="tunnel")
        client = MagicMock()
        client.containers.list.return_value = [proxied, second, tunnel, real]
        with patch.object(orchestrator, "_get_client", return_value=client):
            assert orchestrator.service_instances("honeygain") == [real, second]

    def test_status_light_reports_neither_the_copy_nor_its_tunnel(self):
        real = _container("cashpilot-honeygain", "honeygain")
        proxied = _container("cashpilot-honeygain-p3", "honeygain", proxy=3)
        tunnel = _container("cashpilot-tunnel-honeygain-p3", "honeygain", proxy=3, role="tunnel")
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
        client.containers.get.side_effect = NotFound("none")
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
        assert kw["volumes"] == [proxy_tunnel.SECRET_DIR]
        assert not any("docker.sock" in str(v) for v in kw["volumes"])
        assert "environment" not in kw and "command" not in kw

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
            url = tar.extractfile(members["proxy_url"]).read().decode()
        assert url == "socks5://u1:s3cr3t-p%40ss@203.0.113.9:1080"
        assert all(m.mode == 0o400 and m.uid == 0 and m.gid == 0 for m in members.values())
        # Started only after the settings were in place.
        order = [c[0] for c in created.method_calls if c[0] in ("put_archive", "start")]
        assert order == ["put_archive", "start"]

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

    def test_tailscale_files(self):
        files = proxy_tunnel.secret_files(
            {"kind": "tailscale", "auth_key": AUTH_KEY, "exit_node": "macbook-pro-de-francisco"}, None, "w1-x"
        )
        assert files["auth_key"] == AUTH_KEY
        assert files["exit_node"] == "macbook-pro-de-francisco"
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
    def test_sidecar_is_ready_before_the_earner_is_created(self):
        calls: list[str] = []
        sidecar = MagicMock(id="sidecar-id")

        def fake_start_sidecar(*a, **kw):
            calls.append("sidecar-ready")
            return sidecar, {"ip": "93.184.215.14", "country": "DE"}

        def fake_deploy_raw(**kw):
            calls.append("earner")
            assert kw["network_mode"] == "container:sidecar-id"
            assert kw["labels"][LABEL_PROXY] == "3"
            assert "ports" not in kw and "volumes" not in kw
            return "earner-id"

        with (
            patch.object(orchestrator, "_get_client", return_value=MagicMock()),
            patch.object(proxy_tunnel, "remove", side_effect=lambda *a: calls.append("old-removed") or []),
            patch.object(proxy_tunnel, "start_sidecar", side_effect=fake_start_sidecar),
            patch.object(orchestrator, "deploy_raw", side_effect=fake_deploy_raw),
        ):
            result = proxy_tunnel.deploy("honeygain", 3, {"image": "honeygain/honeygain:1"}, _socks(), None)
        assert calls == ["old-removed", "sidecar-ready", "earner"]
        assert result["container_id"] == "earner-id"

    def test_earner_failure_removes_the_sidecar(self):
        sidecar = MagicMock(id="sidecar-id")
        with (
            patch.object(orchestrator, "_get_client", return_value=MagicMock()),
            patch.object(proxy_tunnel, "remove", return_value=[]),
            patch.object(proxy_tunnel, "start_sidecar", return_value=(sidecar, {"ip": "93.184.215.14"})),
            patch.object(orchestrator, "deploy_raw", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError),
        ):
            proxy_tunnel.deploy("honeygain", 3, {"image": "honeygain/honeygain:1"}, _socks(), None)
        sidecar.remove.assert_called_once_with(force=True, v=True)

    def test_remove_all_takes_earners_before_tunnels(self):
        tunnel = _container("cashpilot-tunnel-x-p1", "x", proxy=1, role="tunnel")
        earner = _container("cashpilot-x-p1", "x", proxy=1)
        client = MagicMock()
        client.containers.list.return_value = [tunnel, earner]
        with patch.object(orchestrator, "_get_client", return_value=client):
            assert proxy_tunnel.remove_all("x") == ["cashpilot-x-p1", "cashpilot-tunnel-x-p1"]

    def test_earner_restarts_when_its_tunnel_restarted_after_it(self):
        earner = _container("cashpilot-x-p1", "x", proxy=1)
        tunnel = _container("cashpilot-tunnel-x-p1", "x", proxy=1, role="tunnel")
        earner.attrs["State"]["StartedAt"] = "2026-11-04T10:00:00.1Z"
        tunnel.attrs["State"]["StartedAt"] = "2026-11-04T11:00:00.1Z"
        assert proxy_tunnel.needs_earner_restart(earner, tunnel)
        tunnel.attrs["State"]["StartedAt"] = "2026-11-04T09:00:00.1Z"
        assert not proxy_tunnel.needs_earner_restart(earner, tunnel)
        tunnel.status = "exited"
        tunnel.attrs["State"]["StartedAt"] = "2026-11-04T11:00:00.1Z"
        assert not proxy_tunnel.needs_earner_restart(earner, tunnel)

    def test_status_reports_the_tunnels_traffic_and_exit(self):
        earner = _container("cashpilot-x-p1", "x", proxy=1)
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
