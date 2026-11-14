"""A service routed through a proxy from its first deploy never runs from the box's own IP (issue #738).

The rule lives on the worker (app/route_gate.py), in the one function every
earner container goes through (orchestrator.deploy_raw), so no deploy path can
skip it: the deploy form, the raw command route, extra copies and redeploys.
These tests pin that rule, the worker routes that keep it, and the UI that
deploys, manages and lists a routed service.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from contextlib import ExitStack, asynccontextmanager, contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402
from docker.errors import NotFound  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import (  # noqa: E402
    auth,
    database,
    main,
    orchestrator,
    placement,
    proxies,
    proxy_tunnel,
    route_gate,
    step_up,
    worker_api,
)
from app.constants import LABEL_MANAGED, LABEL_ROLE, ROLE_TUNNEL  # noqa: E402

WORKER_KEY = "per-worker-key-route"


@pytest.fixture(autouse=True)
def marker(tmp_path, monkeypatch):
    """Each test gets its own route marker and no proxied-only setting."""
    path = tmp_path / ".routed"
    monkeypatch.setattr(route_gate, "ROUTED_MARKER", str(path))
    monkeypatch.delenv(route_gate.PROXIED_ONLY_ENV, raising=False)
    return path


def _client_with(container=None):
    client = MagicMock()
    if container is None:
        client.containers.get.side_effect = Exception("no such container")
    else:
        client.containers.get.return_value = container
    return client


def _tunnel(labels=None):
    tunnel = MagicMock()
    tunnel.labels = {LABEL_MANAGED: "true", LABEL_ROLE: ROLE_TUNNEL} if labels is None else labels
    return tunnel


# ---------------------------------------------------------------------------
# The rule (app/route_gate.py)
# ---------------------------------------------------------------------------


class TestTheRule:
    def test_a_direct_earner_runs_when_nothing_is_routed(self):
        route_gate.check("honeygain", None, _client_with())

    def test_a_routed_service_is_refused_from_the_boxs_own_ip(self):
        route_gate.mark("honeygain", 3)
        with pytest.raises(route_gate.RouteRefused) as exc:
            route_gate.check("honeygain", None, _client_with())
        assert exc.value.error == "route_locked"
        # Another service on the same box is not affected.
        route_gate.check("traffmonetizer", None, _client_with())

    def test_the_owners_approval_lets_it_leave(self):
        route_gate.mark("honeygain", 3)
        route_gate.check("honeygain", None, _client_with(), leave_route=True)

    def test_a_bridge_network_is_the_boxs_own_ip_too(self):
        route_gate.mark("honeygain", 3)
        with pytest.raises(route_gate.RouteRefused):
            route_gate.check("honeygain", "cashpilot-isolated", _client_with())

    def test_inside_one_of_its_tunnels_it_runs(self):
        route_gate.mark("honeygain", 3)
        route_gate.check("honeygain", "container:abc", _client_with(_tunnel()))

    @pytest.mark.parametrize(
        "labels",
        [{}, {LABEL_MANAGED: "true"}, {LABEL_ROLE: ROLE_TUNNEL}, {LABEL_MANAGED: "false", LABEL_ROLE: ROLE_TUNNEL}],
    )
    def test_another_containers_namespace_is_not_a_tunnel(self, labels):
        """Sharing a namespace with any container is how a raw spec would pick the box's own network."""
        with pytest.raises(route_gate.RouteRefused) as exc:
            route_gate.check("honeygain", "container:host-net-thing", _client_with(_tunnel(labels)))
        assert exc.value.error == "route_not_tunnel"

    def test_a_namespace_that_is_gone_is_refused(self):
        with pytest.raises(route_gate.RouteRefused):
            route_gate.check("honeygain", "container:gone", _client_with())

    @pytest.mark.parametrize("value", ["true", "1", "yes", "ON"])
    def test_proxied_only_refuses_every_direct_earner(self, monkeypatch, value):
        monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, value)
        with pytest.raises(route_gate.RouteRefused) as exc:
            route_gate.check("honeygain", None, _client_with(), leave_route=True)
        assert exc.value.error == "proxied_only"
        assert route_gate.PROXIED_ONLY_ENV in str(exc.value)
        # A tunnel's earner still runs.
        route_gate.check("honeygain", "container:abc", _client_with(_tunnel()))

    @pytest.mark.parametrize("value", ["", "false", "0", "no"])
    def test_proxied_only_is_off_unless_set(self, monkeypatch, value):
        monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, value)
        assert route_gate.proxied_only() is False

    def test_an_unreadable_marker_refuses_rather_than_forgets(self, marker):
        marker.write_text("not json")
        with pytest.raises(route_gate.RouteRefused) as exc:
            route_gate.check("honeygain", None, _client_with())
        assert exc.value.error == "route_unknown"
        marker.write_text("[1, 2]")
        with pytest.raises(route_gate.RouteRefused):
            route_gate.check("honeygain", None, _client_with())

    def test_mark_returns_the_previous_route_and_release_puts_it_back(self):
        assert route_gate.mark("honeygain", 3) is None
        assert route_gate.mark("honeygain", 4) == 3
        route_gate.release("honeygain", 3)
        assert route_gate.routed() == {"honeygain": 3}
        route_gate.release("honeygain")
        assert route_gate.routed() == {}
        route_gate.release("honeygain")  # nothing to forget: no error

    def test_a_mark_that_cannot_be_written_raises(self, monkeypatch, tmp_path):
        monkeypatch.setattr(route_gate, "ROUTED_MARKER", str(tmp_path / "missing-dir" / ".routed"))
        with pytest.raises(OSError):
            route_gate.mark("honeygain", 3)


class TestEveryContainerGoesThroughIt:
    """deploy_raw is the one place earner containers are made: the rule is its first step."""

    def _deploy(self, client, **kwargs):
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "container_network", return_value=None),
            patch.object(orchestrator, "container_runtime", return_value=None),
            patch.object(orchestrator, "container_dns", return_value=None),
        ):
            return orchestrator.deploy_raw(**kwargs)

    def test_a_routed_service_is_refused_before_anything_is_pulled(self):
        route_gate.mark("honeygain", 3)
        client = _client_with()
        with pytest.raises(route_gate.RouteRefused):
            self._deploy(client, slug="honeygain", image="honeygain/honeygain")
        client.images.pull.assert_not_called()
        client.containers.run.assert_not_called()

    @pytest.mark.parametrize("instance", [1, 2, 5])
    def test_every_instance_of_it(self, instance):
        route_gate.mark("honeygain", 3)
        client = _client_with()
        with pytest.raises(route_gate.RouteRefused):
            self._deploy(client, slug="honeygain", image="honeygain/honeygain", instance=instance)
        client.containers.run.assert_not_called()

    def test_proxied_only_refuses_any_direct_deploy(self, monkeypatch):
        monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, "true")
        client = _client_with()
        with pytest.raises(route_gate.RouteRefused):
            self._deploy(client, slug="traffmonetizer", image="traffmonetizer/cli_v2")
        client.containers.run.assert_not_called()


# ---------------------------------------------------------------------------
# The worker routes
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _noop(_app):
    yield


@pytest.fixture
def worker(monkeypatch):
    worker_api.app.router.lifespan_context = _noop
    monkeypatch.setattr(worker_api, "API_KEY", "wk-test")
    monkeypatch.setattr(worker_api, "_worker_key", WORKER_KEY)
    deployed: list[dict] = []

    def fake_deploy(**kwargs):
        # The real rule, with no Docker.
        route_gate.check(kwargs["slug"], kwargs.get("network_mode"), _client_with(), leave_route=kwargs["leave_route"])
        deployed.append(kwargs)
        return "cid"

    monkeypatch.setattr(worker_api.orchestrator, "deploy_raw", fake_deploy)
    # No direct container of the service on this box, unless a test says so.
    monkeypatch.setattr(worker_api.orchestrator, "service_instances", MagicMock(return_value=[]))
    monkeypatch.setattr(worker_api, "_validate_runtime", lambda runtime: None)
    monkeypatch.setattr(worker_api.lan_fence, "refresh_outside", lambda: None)
    client = TestClient(worker_api.app, raise_server_exceptions=False)
    headers = {"Authorization": f"Bearer {WORKER_KEY}"}

    def call(method, path, body=None, **kwargs):
        return client.request(method, path, json=body, headers=headers, **kwargs)

    call.deployed = deployed
    return call


def _detail(resp):
    return resp.json().get("detail")


BODY = {"image": "honeygain/honeygain", "env": {"HONEYGAIN_EMAIL": "a@b.c"}}


class TestTheWorkerDeployRoute:
    def test_a_routed_service_is_refused_and_says_so(self, worker):
        route_gate.mark("honeygain", 3)
        resp = worker("POST", "/api/containers/honeygain/deploy", BODY)
        assert resp.status_code == 403
        assert _detail(resp)["error"] == "route_locked"
        assert worker.deployed == []
        assert route_gate.routed() == {"honeygain": 3}

    def test_the_owners_approval_deploys_it_once_and_forgets_the_route(self, worker):
        route_gate.mark("honeygain", 3)
        approval = step_up.sign(WORKER_KEY, step_up.ACTION_LEAVE_ROUTE, "honeygain")
        resp = worker("POST", "/api/containers/honeygain/deploy", {**BODY, "route_approval": approval})
        assert resp.status_code == 200, resp.text
        assert len(worker.deployed) == 1 and worker.deployed[0]["leave_route"] is True
        assert route_gate.routed() == {}
        # Single use: the same approval cannot be replayed.
        route_gate.mark("honeygain", 3)
        resp = worker("POST", "/api/containers/honeygain/deploy", {**BODY, "route_approval": approval})
        assert resp.status_code == 403 and _detail(resp)["error"] == "step_up_rejected"

    @pytest.mark.parametrize(
        "approval",
        [
            step_up.sign(WORKER_KEY, step_up.ACTION_LEAVE_ROUTE, "traffmonetizer"),
            step_up.sign(WORKER_KEY, step_up.ACTION_CUSTOM_IMAGE, "honeygain"),
            step_up.sign("another-workers-key", step_up.ACTION_LEAVE_ROUTE, "honeygain"),
            "garbage",
        ],
    )
    def test_an_approval_for_anything_else_is_refused(self, worker, approval):
        route_gate.mark("honeygain", 3)
        resp = worker("POST", "/api/containers/honeygain/deploy", {**BODY, "route_approval": approval})
        assert resp.status_code == 403 and _detail(resp)["error"] == "step_up_rejected"
        assert worker.deployed == [] and route_gate.routed() == {"honeygain": 3}

    def test_proxied_only_refuses_even_with_an_approval(self, worker, monkeypatch):
        monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, "true")
        approval = step_up.sign(WORKER_KEY, step_up.ACTION_LEAVE_ROUTE, "honeygain")
        resp = worker("POST", "/api/containers/honeygain/deploy", {**BODY, "route_approval": approval})
        assert resp.status_code == 403 and _detail(resp)["error"] == "proxied_only"
        assert worker.deployed == []


PROXY = {"kind": "socks5", "host": "proxy.example", "port": 1080}


class TestTheWorkerProxiedRoutes:
    def _deploy(self, worker, monkeypatch, routed, outcome):
        seen = {}

        def deploy(slug, proxy_id, earner, proxy, own_ip, *, own_tunnel=False):
            seen["own_tunnel"] = own_tunnel
            seen["marked_first"] = route_gate.routed().get(slug)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr(worker_api, "_validate_proxied", lambda slug, spec: None)
        monkeypatch.setattr(worker_api, "_own_egress_ip", AsyncMock(return_value="198.51.100.1"))
        monkeypatch.setattr(worker_api.proxy_tunnel, "deploy", deploy)
        body = {"earner": BODY, "proxy": PROXY, "routed": routed}
        return worker("POST", "/api/proxied/honeygain/3/deploy", body), seen

    def test_a_routed_deploy_is_recorded_before_the_earner_exists(self, worker, monkeypatch):
        resp, seen = self._deploy(worker, monkeypatch, True, {"container_id": "e"})
        assert resp.status_code == 200, resp.text
        assert seen == {"own_tunnel": True, "marked_first": 3}
        assert route_gate.routed() == {"honeygain": 3}

    def test_a_copy_beside_a_direct_one_is_not_recorded_and_shares_the_tunnel(self, worker, monkeypatch):
        resp, seen = self._deploy(worker, monkeypatch, False, {"container_id": "e"})
        assert resp.status_code == 200
        assert seen == {"own_tunnel": False, "marked_first": None}
        assert route_gate.routed() == {}

    def test_a_failed_routed_deploy_puts_the_previous_route_back(self, worker, monkeypatch):
        route_gate.mark("honeygain", 2)
        resp, _ = self._deploy(worker, monkeypatch, True, RuntimeError("tunnel did not start"))
        assert resp.status_code >= 400
        assert route_gate.routed() == {"honeygain": 2}

    def test_a_failed_first_routed_deploy_leaves_no_route(self, worker, monkeypatch):
        resp, _ = self._deploy(worker, monkeypatch, True, RuntimeError("tunnel did not start"))
        assert resp.status_code >= 400
        assert route_gate.routed() == {}

    def test_an_unwritable_marker_deploys_nothing(self, worker, monkeypatch, tmp_path):
        monkeypatch.setattr(route_gate, "ROUTED_MARKER", str(tmp_path / "nope" / ".routed"))
        resp, seen = self._deploy(worker, monkeypatch, True, {"container_id": "e"})
        assert resp.status_code == 503
        assert seen == {}

    @pytest.mark.parametrize("before", [None, 2])
    def test_a_routed_deploy_beside_a_direct_container_is_refused(self, worker, monkeypatch, before):
        """The worker, not only the UI, refuses it: one account on the box's IP and the proxy's ties them."""
        if before is not None:
            route_gate.mark("honeygain", before)
        direct = MagicMock()
        direct.name = "cashpilot-honeygain"
        monkeypatch.setattr(worker_api.orchestrator, "service_instances", MagicMock(return_value=[direct]))
        resp, seen = self._deploy(worker, monkeypatch, True, {"container_id": "e"})
        assert resp.status_code == 409, resp.text
        assert "cashpilot-honeygain" in _detail(resp)
        assert seen == {}
        assert route_gate.routed() == ({} if before is None else {"honeygain": before})

    def test_a_copy_beside_a_direct_container_is_still_allowed(self, worker, monkeypatch):
        direct = MagicMock()
        direct.name = "cashpilot-honeygain"
        monkeypatch.setattr(worker_api.orchestrator, "service_instances", MagicMock(return_value=[direct]))
        resp, _ = self._deploy(worker, monkeypatch, False, {"container_id": "e"})
        assert resp.status_code == 200, resp.text

    def test_a_routed_deploy_that_cannot_list_the_containers_deploys_nothing(self, worker, monkeypatch):
        monkeypatch.setattr(
            worker_api.orchestrator, "service_instances", MagicMock(side_effect=RuntimeError("docker is down"))
        )
        resp, seen = self._deploy(worker, monkeypatch, True, {"container_id": "e"})
        assert resp.status_code == 503
        assert seen == {} and route_gate.routed() == {}

    def test_the_logs_of_a_routed_service(self, worker, monkeypatch):
        monkeypatch.setattr(worker_api.proxy_tunnel, "logs", lambda slug, pid, lines: f"{slug} {pid} {lines}")
        resp = worker("GET", "/api/proxied/honeygain/3/logs", params={"lines": 5000})
        assert resp.status_code == 200 and resp.json() == {"logs": "honeygain 3 1000"}


class TestOneDeployOfAServiceAtATime:
    """route_gate.deploying: a direct and a routed deploy of one service never interleave."""

    def _in_thread(self, fn):
        out = {}

        def run():
            try:
                out["result"] = fn()
            except BaseException as exc:  # noqa: BLE001 - handed to the test
                out["error"] = exc

        t = threading.Thread(target=run, daemon=True)
        t.start()
        return t, out

    def test_a_routed_deploy_waits_for_a_direct_one_and_then_refuses(self, monkeypatch):
        inside, go = threading.Event(), threading.Event()
        created = []
        client = MagicMock()
        client.containers.get.side_effect = NotFound("no such container")

        def run(**kwargs):
            inside.set()
            assert go.wait(5)
            created.append(kwargs["name"])
            return MagicMock(id="direct-id")

        client.containers.run.side_effect = run
        direct = MagicMock()
        direct.name = "cashpilot-honeygain"
        monkeypatch.setattr(orchestrator, "service_instances", lambda slug: [direct] if created else [])
        tunnel_deploys = []
        monkeypatch.setattr(proxy_tunnel, "deploy", lambda *a, **k: tunnel_deploys.append(a) or {"container_id": "e"})

        def direct_deploy():
            with (
                patch.object(orchestrator, "_get_client", return_value=client),
                patch.object(orchestrator, "container_network", return_value=None),
                patch.object(orchestrator, "container_runtime", return_value=None),
                patch.object(orchestrator, "container_dns", return_value=None),
            ):
                return orchestrator.deploy_raw(slug="honeygain", image="honeygain/honeygain")

        t1, _ = self._in_thread(direct_deploy)
        assert inside.wait(5)  # past its check, its container not made yet
        t2, out = self._in_thread(lambda: worker_api._deploy_routed("honeygain", 3, BODY, PROXY, None))
        time.sleep(0.3)
        assert "result" not in out and tunnel_deploys == []
        go.set()
        t1.join(5)
        t2.join(5)
        assert isinstance(out.get("error"), HTTPException) and out["error"].status_code == 409
        assert tunnel_deploys == [] and route_gate.routed() == {}

    def test_a_failed_routed_deploy_never_undoes_a_route_set_after_it(self, monkeypatch):
        inside, go = threading.Event(), threading.Event()

        def deploy(slug, proxy_id, earner, proxy, own_ip, *, own_tunnel=False):
            if proxy_id == 2:
                inside.set()
                assert go.wait(5)
                raise RuntimeError("tunnel did not start")
            return {"container_id": "e"}

        monkeypatch.setattr(orchestrator, "service_instances", lambda slug: [])
        monkeypatch.setattr(proxy_tunnel, "deploy", deploy)
        first, a = self._in_thread(lambda: worker_api._deploy_routed("honeygain", 2, BODY, PROXY, None))
        assert inside.wait(5)
        second, b = self._in_thread(lambda: worker_api._deploy_routed("honeygain", 3, BODY, PROXY, None))
        time.sleep(0.3)
        go.set()
        first.join(5)
        second.join(5)
        assert isinstance(a.get("error"), HTTPException)
        assert b.get("result") == {"container_id": "e"}
        assert route_gate.routed() == {"honeygain": 3}


class TestAnUnreadableMarker:
    def test_a_start_is_refused_rather_than_put_in_the_shared_tunnel(self, marker):
        """Not knowing whether it is routed is not "not routed" (proxy_tunnel._start picks the tunnel by it)."""
        marker.write_text("not json")
        with pytest.raises(proxy_tunnel.ProxyTunnelError) as err:
            proxy_tunnel._routed_here("honeygain", 3)
        assert err.value.status_code == 503

    def test_a_readable_marker_answers(self):
        assert proxy_tunnel._routed_here("honeygain", 3) is False
        route_gate.mark("honeygain", 3)
        assert proxy_tunnel._routed_here("honeygain", 3) is True
        assert proxy_tunnel._routed_here("honeygain", 4) is False


class TestAWorkerThatStartsWithoutDocker:
    """Docker can come up after the worker; a proxied-only worker holds direct earners all the same."""

    def _start(self, monkeypatch, proxied_only):
        if proxied_only:
            monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, "true")
        monkeypatch.setattr(worker_api.lan_fence, "GUARD_SECONDS", 0.01)
        hold = MagicMock(return_value=[])
        monkeypatch.setattr(worker_api.orchestrator, "hold_direct_earners", hold)

        async def run():
            async with worker_api.lifespan(worker_api.app):
                await asyncio.sleep(0.1)

        with (
            patch.object(worker_api.orchestrator, "docker_available", return_value=False),
            patch.object(worker_api, "_check_fence", AsyncMock()),
            patch.object(worker_api, "_fence_loop", AsyncMock()),
            patch.object(worker_api, "UI_URL", ""),
        ):
            asyncio.run(run())
        return hold.call_count

    def test_a_proxied_only_worker_holds_them_at_start_and_on_every_pass(self, monkeypatch):
        assert self._start(monkeypatch, True) >= 3

    def test_any_other_worker_starts_no_hold(self, monkeypatch):
        assert self._start(monkeypatch, False) == 0


class TestTheHeartbeat:
    def test_only_the_routed_entry_is_flagged(self):
        route_gate.mark("honeygain", 3)
        entries = [
            {"slug": "honeygain", "proxy_id": 3},
            {"slug": "honeygain", "proxy_id": 4},
            {"slug": "traffmonetizer", "proxy_id": 3},
        ]
        worker_api._mark_routed(entries)
        assert [e.get("routed") for e in entries] == [True, None, None]

    def test_an_unreadable_marker_flags_nothing(self, marker):
        marker.write_text("{")
        entries = [{"slug": "honeygain", "proxy_id": 3}]
        worker_api._mark_routed(entries)
        assert "routed" not in entries[0]


# ---------------------------------------------------------------------------
# One tunnel per routed service
# ---------------------------------------------------------------------------


class TestItsOwnTunnel:
    def test_its_name_and_label_carry_the_service(self):
        assert proxy_tunnel.shared_tunnel_name(3) == "cashpilot-tunnel-p3"
        assert proxy_tunnel.shared_tunnel_name(3, "honeygain") == "cashpilot-tunnel-p3-honeygain"
        assert proxy_tunnel.shared_label(3) == "p3"
        assert proxy_tunnel.shared_label(3, "honeygain") == "honeygain-p3"

    def test_a_shared_tunnel_is_not_a_services_own(self):
        shared = MagicMock()
        shared.labels = {
            LABEL_MANAGED: "true",
            LABEL_ROLE: ROLE_TUNNEL,
            proxy_tunnel.LABEL_PROXY: "3",
            proxy_tunnel.LABEL_SERVICE: proxy_tunnel.SHARED_SLUG,
        }
        own = MagicMock()
        own.labels = {**shared.labels, proxy_tunnel.LABEL_TUNNEL_FOR: "honeygain"}
        assert proxy_tunnel._is_tunnel_for(shared, 3, None)
        assert not proxy_tunnel._is_tunnel_for(shared, 3, "honeygain")
        assert proxy_tunnel._is_tunnel_for(own, 3, "honeygain")
        assert not proxy_tunnel._is_tunnel_for(own, 3, None)
        assert proxy_tunnel._own_key(own) == "honeygain" and proxy_tunnel._own_key(shared) is None


# ---------------------------------------------------------------------------
# The UI
# ---------------------------------------------------------------------------


class _Req:
    def __init__(self, body):
        self._body = body
        self.url = MagicMock(path="/api/proxies")

    async def json(self):
        return self._body


@pytest.fixture
def db(tmp_path):
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"),
    ):
        yield tmp_path


def _run(fn):
    async def go():
        await database.init_db()
        try:
            return await fn()
        finally:
            await database.close_shared()

    return asyncio.run(go())


def _request():
    request = MagicMock()
    request.client.host = "192.0.2.10"
    request.headers = {}
    return request


OWNER = {"u": "owner", "r": "owner"}


def _worker_row(*, containers=(), proxied=(), features=("proxy_tunnel", "route_at_deploy")):
    return {
        "id": 1,
        "name": "box",
        "status": "online",
        "client_id": "w1",
        "containers": json.dumps(list(containers)),
        "system_info": json.dumps(
            {"features": list(features), "proxied": list(proxied), "egress_ip": "93.184.216.34", "arch": "x86_64"}
        ),
    }


class _Ui:
    """The UI's deploy with a real database and a stub worker."""

    def __init__(self, worker_row=None, worker_reply=None):
        self.worker_row = worker_row or _worker_row()
        self.calls: list[tuple[str, str, dict | None]] = []
        self.worker_reply = worker_reply or self._no_container

    @staticmethod
    def _no_container(method, path, body):
        """A routed service has no container of its own: the worker's container routes answer 404."""
        if path.startswith("/api/containers/") and not path.endswith("/deploy"):
            return HTTPException(status_code=404, detail="Container not found")
        return {"container_id": "c", "status": "ok"}

    async def hop(self, worker_id, method, path, *, json=None, **kwargs):
        self.calls.append((method, path, json))
        reply = self.worker_reply(method, path, json)
        if isinstance(reply, HTTPException):
            raise reply
        return reply

    def patches(self, owner_uid=None):
        user = dict(OWNER, uid=owner_uid)
        return (
            patch.object(auth, "get_current_user", return_value=user),
            patch.object(main, "_resolve_worker_id", AsyncMock(return_value=1)),
            patch.object(main, "_proxy_to_worker", self.hop),
            patch.object(main, "_confirmed_worker_key", AsyncMock(return_value=WORKER_KEY)),
            patch.object(main.database, "get_worker", AsyncMock(return_value=self.worker_row)),
            patch.object(main.database, "list_workers", AsyncMock(return_value=[])),
            patch.object(main, "_spawn", lambda coro: coro.close()),
            patch.object(main.metrics, "record_container_lifecycle", lambda *a: None),
        )

    @contextmanager
    def active(self, *extra, owner_uid=None):
        with ExitStack() as stack:
            for p in (*self.patches(owner_uid), *extra):
                stack.enter_context(p)
            yield

    async def proxy(self):
        created = await main.api_create_proxy(
            _Req({"name": "Home", "kind": "socks5", "host": "h.example", "port": 1}), {}
        )
        return created["id"]

    async def deploy(self, body, owner_uid=None, slug="honeygain"):
        with self.active(owner_uid=owner_uid):
            return await main.api_deploy(_request(), slug, body)

    def paths(self):
        return [(m, p) for m, p, _ in self.calls]


ENV = {"HONEYGAIN_EMAIL": "a@b.c", "HONEYGAIN_PASSWORD": "pw", "HONEYGAIN_DEVICE_NAME": "box"}


class TestTheUiDeploysARoute:
    def test_it_goes_to_the_worker_as_a_routed_copy_and_is_recorded_with_its_route(self, db):
        ui = _Ui()

        async def go():
            pid = await ui.proxy()
            result = await ui.deploy(main.DeployRequest(env=ENV, route=pid))
            return pid, result, await database.get_deployment_spec("honeygain", worker_id=1)

        pid, result, record = _run(go)
        assert ui.paths() == [("POST", f"/api/proxied/honeygain/{pid}/deploy")]
        sent = ui.calls[0][2]
        assert sent["routed"] is True
        # The deploy's own device name, not a derived copy id: no phantom device.
        assert sent["earner"]["env"]["HONEYGAIN_DEVICE_NAME"] == "box"
        assert result["route"]["proxy_id"] == pid
        assert proxies.route_of(record) == pid

    def test_a_redeploy_keeps_the_route_without_being_asked(self, db):
        ui = _Ui()

        async def go():
            pid = await ui.proxy()
            await ui.deploy(main.DeployRequest(env=ENV, route=pid))
            ui.calls.clear()
            await ui.deploy(main.DeployRequest(env={}))
            return pid

        pid = _run(go)
        assert ui.paths() == [("POST", f"/api/proxied/honeygain/{pid}/deploy")]

    @pytest.mark.parametrize(
        ("body", "status", "words"),
        [
            ({"instances": 2}, 400, "runs once per worker"),
            ({"route": 99}, 404, ""),
        ],
    )
    def test_refusals(self, db, body, status, words):
        ui = _Ui()

        async def go():
            pid = await ui.proxy()
            with pytest.raises(HTTPException) as exc:
                await ui.deploy(main.DeployRequest(env=ENV, **{"route": pid, **body}))
            return exc.value

        error = _run(go)
        assert error.status_code == status and words in str(error.detail)
        assert ui.calls == []

    def test_a_service_the_catalog_cannot_route(self, db):
        ui = _Ui()

        async def go():
            pid = await ui.proxy()
            with pytest.raises(HTTPException) as exc:
                await ui.deploy(
                    main.DeployRequest(env={"EARNAPP_UUID": "sdk-node-" + "a" * 32}, route=pid), slug="earnapp"
                )
            return exc.value

        error = _run(go)
        assert error.status_code == 400 and "keeps data in a volume" in str(error.detail)
        assert ui.calls == []

    def test_a_service_already_running_from_the_boxs_ip_is_not_routed_beside_it(self, db):
        ui = _Ui(_worker_row(containers=[{"slug": "honeygain", "status": "running"}]))

        async def go():
            pid = await ui.proxy()
            with pytest.raises(HTTPException) as exc:
                await ui.deploy(main.DeployRequest(env=ENV, route=pid))
            return exc.value

        error = _run(go)
        assert error.status_code == 409 and "own IP" in str(error.detail)
        assert ui.calls == []

    def test_a_worker_too_old_to_keep_the_route(self, db):
        ui = _Ui(_worker_row(features=("proxy_tunnel",)))

        async def go():
            pid = await ui.proxy()
            with pytest.raises(HTTPException) as exc:
                await ui.deploy(main.DeployRequest(env=ENV, route=pid))
            return exc.value

        error = _run(go)
        assert error.status_code == 409 and "too old" in str(error.detail)
        assert ui.calls == []


class TestTheUiLeavesARouteOnlyWithThePassword:
    def _locked(self, method, path, body):
        if path == "/api/containers/honeygain/deploy" and not (body or {}).get("route_approval"):
            return HTTPException(status_code=403, detail={"error": "route_locked", "message": "routed"})
        return {"container_id": "c", "status": "deployed"}

    def test_without_a_password_it_asks_and_names_the_ip(self, db):
        ui = _Ui(worker_reply=self._locked)

        async def go():
            with pytest.raises(HTTPException) as exc:
                await ui.deploy(main.DeployRequest(env=ENV))
            return exc.value, await database.get_audit_events()

        error, audit = _run(go)
        assert error.status_code == 403 and error.detail["error"] == "step_up_required"
        assert "93.184.216.34" in error.detail["message"]
        # The worker's refusal that started the prompt is not an attack to audit.
        assert audit == []

    def test_with_the_password_it_sends_an_approval_the_worker_accepts(self, db):
        ui = _Ui(worker_reply=self._locked)

        async def go():
            uid = await database.create_user("owner", auth.hash_password("right one!"), "owner")
            await ui.deploy(main.DeployRequest(env=ENV, step_up_password="right one!"), owner_uid=uid)
            return await database.get_audit_events()

        audit = _run(go)
        approval = ui.calls[-1][2]["route_approval"]
        step_up.check(WORKER_KEY, approval, step_up.ACTION_LEAVE_ROUTE, "honeygain")
        assert audit[0]["action"] == step_up.ACTION_LEAVE_ROUTE and audit[0]["outcome"] == "confirmed"

    def test_a_routed_copy_the_box_reports_is_removed_first(self, db):
        ui = _Ui(
            _worker_row(proxied=[{"slug": "honeygain", "proxy_id": 1, "status": "running", "routed": True}]),
            worker_reply=self._locked,
        )

        async def go():
            uid = await database.create_user("owner", auth.hash_password("right one!"), "owner")
            pid = await ui.proxy()
            await ui.deploy(main.DeployRequest(env=ENV, step_up_password="right one!"), owner_uid=uid)
            return pid

        pid = _run(go)
        paths = ui.paths()
        assert paths.index(("DELETE", f"/api/proxied/honeygain/{pid}")) < len(paths) - 1
        assert paths[-1] == ("POST", "/api/containers/honeygain/deploy")

    def test_leaving_a_recorded_route_removes_it_first(self, db):
        ui = _Ui(worker_reply=self._locked)

        async def go():
            uid = await database.create_user("owner", auth.hash_password("right one!"), "owner")
            pid = await ui.proxy()
            await ui.deploy(main.DeployRequest(env=ENV, route=pid))
            ui.calls.clear()
            await ui.deploy(main.DeployRequest(env=ENV, route=0, step_up_password="right one!"), owner_uid=uid)
            return pid, await database.get_deployment_spec("honeygain", worker_id=1)

        pid, record = _run(go)
        assert ui.paths() == [("DELETE", f"/api/proxied/honeygain/{pid}"), ("POST", "/api/containers/honeygain/deploy")]
        assert proxies.route_of(record) is None

    def test_a_direct_deploy_that_fails_after_the_copy_went_keeps_the_settings(self, db):
        """The routed copy is gone, the direct one did not come up: a retry still has the recorded env."""

        def fails(method, path, body):
            if path == "/api/containers/honeygain/deploy":
                return HTTPException(status_code=502, detail="image pull failed")
            return {"container_id": "c", "status": "deployed"}

        ui = _Ui(worker_reply=self._locked)

        async def go():
            uid = await database.create_user("owner", auth.hash_password("right one!"), "owner")
            pid = await ui.proxy()
            await ui.deploy(main.DeployRequest(env=ENV, route=pid))
            ui.worker_reply = fails
            with pytest.raises(HTTPException):
                await ui.deploy(main.DeployRequest(env=ENV, route=0, step_up_password="right one!"), owner_uid=uid)
            return await database.get_deployment_spec("honeygain", worker_id=1)

        record = _run(go)
        assert record is not None and proxies.route_of(record) is None
        assert record["env"]["HONEYGAIN_EMAIL"] == "a@b.c"


class TestTheUiManagesARoutedService:
    def test_a_404_for_a_service_that_is_not_routed_stands(self, db):
        ui = _Ui()

        async def go():
            with ui.active(patch.object(main, "_require_writer", lambda r: None)), pytest.raises(HTTPException) as exc:
                await main._svc_stop(_request(), "honeygain", 1)
            return exc.value

        assert _run(go).status_code == 404
        assert ui.paths() == [("POST", "/api/containers/honeygain/stop")]

    def _routed(self, db):
        ui = _Ui()

        async def setup():
            pid = await ui.proxy()
            await ui.deploy(main.DeployRequest(env=ENV, route=pid))
            ui.calls.clear()
            return pid

        return ui, setup

    def test_stop_start_restart_logs_and_remove_reach_the_copy(self, db):
        ui, setup = self._routed(db)

        async def go():
            pid = await setup()
            req = _request()

            async def run():
                await main._svc_stop(req, "honeygain", 1)
                await main.api_service_start(req, "honeygain", worker_id=1)
                await main._svc_restart(req, "honeygain", 1)
                await main.api_service_logs(req, "honeygain", lines=20, worker_id=1)
                await main._svc_remove(req, "honeygain", 1, False)

            with ui.active(patch.object(main, "_require_writer", lambda r: None)):
                await run()
            return pid, await database.get_deployment_spec("honeygain", worker_id=1)

        pid, record = _run(go)
        base = f"/api/proxied/honeygain/{pid}"
        # Each asks for the container first; its 404 is what sends it to the copy.
        assert [c for c in ui.paths() if c[1].startswith("/api/proxied/")] == [
            ("POST", f"{base}/stop"),
            ("POST", f"{base}/start"),
            ("POST", f"{base}/stop"),
            ("POST", f"{base}/start"),
            ("GET", f"{base}/logs"),
            ("DELETE", base),
        ]
        assert record is None
        assert record is None

    def test_the_raw_route_acts_on_the_copy_and_never_carries_an_approval(self, db):
        ui, setup = self._routed(db)

        async def go():
            pid = await setup()
            with ui.active(patch.object(main, "_require_owner", lambda r: OWNER)):
                await main.api_worker_command(_request(), 1, main.WorkerCommand(command="stop", slug="honeygain"))
                spec = {"image": "x/y:1", "route_approval": "a.b", "route": {"proxy_id": pid}}
                await main.api_worker_command(
                    _request(), 1, main.WorkerCommand(command="deploy", slug="honeygain", spec=spec)
                )
            return pid

        pid = _run(go)
        assert ui.calls[1][:2] == ("POST", f"/api/proxied/honeygain/{pid}/stop")
        assert ui.calls[-1][1] == "/api/containers/honeygain/deploy"
        assert "route_approval" not in ui.calls[-1][2] and "route" not in ui.calls[-1][2]

    def test_a_raw_remove_the_worker_has_not_confirmed_keeps_the_copy_to_ask_again(self, db):
        ui, setup = self._routed(db)

        async def go():
            pid = await setup()

            def slow(method, path, body):
                if method == "DELETE" and path.startswith("/api/proxied/"):
                    return HTTPException(status_code=504, detail="the worker did not answer in time")
                return _Ui._no_container(method, path, body)

            ui.worker_reply = slow
            with ui.active():
                result = await main.api_worker_command(
                    _request(), 1, main.WorkerCommand(command="remove", slug="honeygain")
                )
            return pid, result, await database.list_proxied_copies(pid)

        pid, result, copies = _run(go)
        assert result["status"] == "removing"
        assert [(c["slug"], c["worker_id"]) for c in copies] == [("honeygain", 1)]
        assert copies[0].get("removing_since")

    def test_a_copy_through_the_same_proxy_is_refused(self, db):
        ui, setup = self._routed(db)

        async def go():
            pid = await setup()
            with ui.active(), pytest.raises(HTTPException) as exc:
                await main.api_add_proxied_copy(pid, main.ProxyCopyRequest(worker_id=1, slug="honeygain"), {})
            return exc.value

        error = _run(go)
        assert error.status_code == 409 and "already runs through this proxy" in str(error.detail)
        assert ui.calls == []

    def test_removing_its_copy_on_the_proxies_page_drops_its_record(self, db):
        ui, setup = self._routed(db)

        async def go():
            pid = await setup()
            await main._finish_copy_removal(pid, 1, "honeygain")
            return await database.get_deployment_spec("honeygain", worker_id=1)

        assert _run(go) is None


class TestTheDashboardCountsIt:
    ROUTED = {"slug": "honeygain", "proxy_id": 3, "status": "running", "routed": True, "exit_ip": "203.0.113.9"}
    COPY = {"slug": "traffmonetizer", "proxy_id": 3, "status": "running"}

    def test_placement_lists_the_routed_service_on_its_box(self):
        rows = placement.reported([_worker_row(proxied=[self.ROUTED, self.COPY])])
        assert [(r["slug"], r.get("routed")) for r in rows] == [("honeygain", True)]

    def test_the_status_rows_carry_its_route(self, db):
        with patch.object(main.database, "list_workers", AsyncMock(return_value=[_worker_row(proxied=[self.ROUTED])])):
            rows = asyncio.run(main._get_all_worker_containers())
        assert [r["slug"] for r in rows] == ["honeygain"]
        assert rows[0]["route"]["exit_ip"] == "203.0.113.9" and rows[0]["instance"] == 1

    def test_routed_entries_reads_a_raw_database_row(self):
        assert proxies.routed_entries(_worker_row(proxied=[self.ROUTED, self.COPY])) == [self.ROUTED]
        assert proxies.routed_entries({"system_info": "{not json"}) == []


# ---------------------------------------------------------------------------
# A container that already exists: Start, Restart, and CASHPILOT_PROXIED_ONLY
# set after it was made
# ---------------------------------------------------------------------------


def _earner(name="cashpilot-honeygain", slug="honeygain", network_mode="cashpilot-isolated", labels=None):
    c = MagicMock()
    c.name = name
    c.labels = {LABEL_MANAGED: "true", "cashpilot.service": slug} if labels is None else labels
    c.attrs = {"HostConfig": {"NetworkMode": network_mode}}
    return c


def _act(container, action, client=None):
    with (
        patch.object(orchestrator, "_find_container", return_value=container),
        patch.object(orchestrator, "_get_client", return_value=client or _client_with()),
        patch.object(orchestrator, "fence_gated", return_value=False),
    ):
        getattr(orchestrator, action)("honeygain")


class TestStartAndRestartKeepTheRule:
    @pytest.mark.parametrize("action", ["start_service", "restart_service"])
    def test_proxied_only_refuses_a_direct_container_made_before_it_was_set(self, monkeypatch, action):
        monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, "true")
        c = _earner()
        with pytest.raises(route_gate.RouteRefused) as exc:
            _act(c, action)
        assert exc.value.error == "proxied_only"
        c.start.assert_not_called()
        c.restart.assert_not_called()

    @pytest.mark.parametrize("action", ["start_service", "restart_service"])
    def test_a_routed_service_is_not_started_from_the_boxs_own_ip(self, action):
        route_gate.mark("honeygain", 3)
        c = _earner()
        with pytest.raises(route_gate.RouteRefused) as exc:
            _act(c, action)
        assert exc.value.error == "route_locked"
        c.start.assert_not_called()
        c.restart.assert_not_called()

    @pytest.mark.parametrize("action", ["start_service", "restart_service"])
    def test_control_a_direct_service_on_an_ordinary_worker_starts(self, action):
        c = _earner()
        _act(c, action)
        assert c.start.called or c.restart.called

    @pytest.mark.parametrize("command", ["start", "restart"])
    def test_the_worker_route_answers_403_with_the_reason(self, worker, monkeypatch, command):
        monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, "true")
        c = _earner()
        with (
            patch.object(orchestrator, "_find_container", return_value=c),
            patch.object(orchestrator, "_get_client", return_value=_client_with()),
        ):
            resp = worker("POST", f"/api/containers/honeygain/{command}")
        assert resp.status_code == 403, resp.text
        assert _detail(resp)["error"] == "proxied_only"
        c.start.assert_not_called()
        c.restart.assert_not_called()


class TestProxiedOnlyStopsWhatAlreadyRuns:
    def _hold(self, containers, tunnel=None):
        client = _client_with(tunnel)
        client.containers.list.return_value = containers
        with patch.object(orchestrator, "_get_client", return_value=client):
            return orchestrator.hold_direct_earners()

    def test_a_direct_earner_is_stopped(self, monkeypatch):
        monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, "true")
        direct = _earner()
        assert self._hold([direct]) == ["cashpilot-honeygain"]
        direct.stop.assert_called_once()

    def test_tunnels_copies_and_containers_cashpilot_did_not_make_are_left_alone(self, monkeypatch):
        monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, "true")
        tunnel = _earner("cashpilot-tunnel-x", labels={LABEL_MANAGED: "true", LABEL_ROLE: ROLE_TUNNEL})
        copy = _earner(
            "cashpilot-honeygain-p3",
            network_mode="container:abc",
            labels={LABEL_MANAGED: "true", "cashpilot.service": "honeygain", "cashpilot.proxy": "3"},
        )
        platform = _earner("cashpilot-worker", labels={LABEL_MANAGED: "true"})
        assert self._hold([tunnel, copy, platform], tunnel=_tunnel()) == []
        for c in (tunnel, copy, platform):
            c.stop.assert_not_called()

    def test_an_earner_in_a_namespace_that_is_not_a_tunnel_is_stopped(self, monkeypatch):
        monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, "true")
        joined = _earner(network_mode="container:someone-else")
        assert self._hold([joined], tunnel=_tunnel(labels={LABEL_MANAGED: "true"})) == ["cashpilot-honeygain"]

    def test_control_nothing_is_stopped_without_the_switch(self):
        direct = _earner()
        assert self._hold([direct]) == []
        direct.stop.assert_not_called()

    def test_a_routed_lock_alone_does_not_stop_anything(self, monkeypatch):
        """A direct deploy the owner confirmed runs before its route is released: left to the deploy."""
        route_gate.mark("honeygain", 3)
        direct = _earner()
        assert self._hold([direct]) == []

    def test_the_worker_holds_them_at_its_start_and_on_every_guard_pass(self, monkeypatch):
        calls = []
        monkeypatch.setattr(worker_api.orchestrator, "hold_direct_earners", lambda: calls.append(1) or [])
        monkeypatch.setattr(worker_api.lan_fence, "guard", lambda: {})
        asyncio.run(worker_api._guard_once())
        assert calls == [1]
        monkeypatch.setattr(
            worker_api.orchestrator, "hold_direct_earners", MagicMock(side_effect=RuntimeError("docker is down"))
        )
        asyncio.run(worker_api._guard_once())  # never raises

    def test_a_fence_gated_node_is_held_by_the_guard_too(self, monkeypatch, tmp_path):
        """The guard would otherwise start Mysterium again after this stopped it."""
        from tests.test_mysterium_fenced import _guard, _node

        monkeypatch.setattr(orchestrator, "STOPPED_MARKER", str(tmp_path / "stopped"))
        monkeypatch.setattr(orchestrator, "IDENTITY_DIR", str(tmp_path / "identity"))
        monkeypatch.setattr(orchestrator, "_MISMATCH_HELD", {}, raising=False)
        monkeypatch.setattr(orchestrator, "FAILED_MARKER", str(tmp_path / "failed"), raising=False)
        monkeypatch.setattr(orchestrator, "_FAILED_UNWRITTEN", {}, raising=False)
        monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, "true")
        node = _node(status="exited")
        held, _ = _guard([node])
        node.start.assert_not_called()
        assert "proxy" in held["cashpilot-mysterium"]
