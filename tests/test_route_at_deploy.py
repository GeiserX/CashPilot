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

import httpx  # noqa: E402
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
from app.constants import LABEL_MANAGED, LABEL_PROXY, LABEL_ROLE, LABEL_VERSION, ROLE_TUNNEL  # noqa: E402

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
        [
            {},
            {LABEL_MANAGED: "true"},
            {LABEL_ROLE: ROLE_TUNNEL},
            {LABEL_MANAGED: "false", LABEL_ROLE: ROLE_TUNNEL},
            # A direct earner deploy_raw made with a tunnel's labels: its own version label it cannot lose.
            {LABEL_MANAGED: "true", LABEL_ROLE: ROLE_TUNNEL, LABEL_PROXY: "3", LABEL_VERSION: "1"},
        ],
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

    def test_a_direct_earner_cannot_pass_for_a_proxied_one(self):
        """The proxy and role labels are what every check skips a copy or a tunnel by.

        A direct container carrying them would hide from the routed deploy's
        own-IP check and from the proxied-only hold, and keep running from the
        box's own IP beside the route.
        """
        client = _client_with()
        client.containers.get.side_effect = NotFound("no such container")
        self._deploy(
            client,
            slug="honeygain",
            image="honeygain/honeygain",
            labels={"cashpilot.proxy": "1", LABEL_ROLE: ROLE_TUNNEL, "app": "kept"},
        )
        labels = client.containers.run.call_args.kwargs["labels"]
        assert "cashpilot.proxy" not in labels and LABEL_ROLE not in labels
        assert labels["app"] == "kept"
        made = MagicMock(labels=labels)
        assert not orchestrator.is_proxied(made)

    def test_a_copy_inside_its_tunnel_keeps_its_proxy_label(self):
        tunnel = _tunnel()

        def get(ref):
            if ref == "tid":
                return tunnel
            raise NotFound("no such container")

        client = _client_with()
        client.containers.get.side_effect = get
        self._deploy(
            client,
            slug="honeygain",
            image="honeygain/honeygain",
            network_mode="container:tid",
            name="cashpilot-honeygain-p1",
            labels={"cashpilot.proxy": "1"},
        )
        assert client.containers.run.call_args.kwargs["labels"]["cashpilot.proxy"] == "1"


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
    # No proxied copy on this box, unless a test says so.
    docker = MagicMock()
    docker.containers.get.side_effect = NotFound("no such container")
    monkeypatch.setattr(worker_api.orchestrator, "_get_client", lambda: docker)
    client = TestClient(worker_api.app, raise_server_exceptions=False)
    headers = {"Authorization": f"Bearer {WORKER_KEY}"}

    def call(method, path, body=None, **kwargs):
        return client.request(method, path, json=body, headers=headers, **kwargs)

    call.deployed = deployed
    call.docker = docker
    return call


def _detail(resp):
    return resp.json().get("detail")


def _copies_on(docker, *copies):
    """Docker on the worker holds these proxied copies: (proxy id, tunnel-for slug or None for a shared tunnel)."""
    by_name: dict[str, MagicMock] = {}
    earners = []
    for proxy_id, own in copies:
        tunnel = MagicMock()
        tunnel.id = f"t{proxy_id}"
        tunnel.labels = {
            LABEL_MANAGED: "true",
            LABEL_ROLE: ROLE_TUNNEL,
            proxy_tunnel.LABEL_PROXY: str(proxy_id),
            proxy_tunnel.LABEL_SERVICE: proxy_tunnel.SHARED_SLUG,
            **({proxy_tunnel.LABEL_TUNNEL_FOR: own} if own else {}),
        }
        earner = MagicMock()
        earner.name = proxy_tunnel.earner_name("honeygain", proxy_id)
        earner.labels = {LABEL_MANAGED: "true", "cashpilot.service": "honeygain", "cashpilot.proxy": str(proxy_id)}
        earner.attrs = {"HostConfig": {"NetworkMode": f"container:{tunnel.id}"}}
        by_name[tunnel.id] = tunnel
        by_name[earner.name] = earner
        earners.append(earner)

    def get(name):
        if name in by_name:
            return by_name[name]
        raise NotFound("no such container")

    docker.containers.get.side_effect = get
    docker.containers.list.return_value = earners
    return earners


def _tunnel_gone(docker, tunnel_id):
    """The tunnel container ``tunnel_id`` was removed out of band; its earner stays."""
    get = docker.containers.get.side_effect

    def gone(name):
        if name == tunnel_id:
            raise NotFound("gone")
        return get(name)

    docker.containers.get.side_effect = gone


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

    def test_leaving_the_route_is_refused_while_its_routed_copy_still_runs(self, worker):
        """A routed redeploy that ran between the UI's remove and this deploy put the copy back.

        Deployed direct beside it, the same account would run from the box's IP and the proxy's.
        """
        route_gate.mark("honeygain", 3)
        copy = MagicMock()
        copy.name = proxy_tunnel.earner_name("honeygain", 3)
        copy.labels = {LABEL_MANAGED: "true", "cashpilot.service": "honeygain", "cashpilot.proxy": "3"}
        worker.docker.containers.get.side_effect = None
        worker.docker.containers.get.return_value = copy
        approval = step_up.sign(WORKER_KEY, step_up.ACTION_LEAVE_ROUTE, "honeygain")
        resp = worker("POST", "/api/containers/honeygain/deploy", {**BODY, "route_approval": approval})
        assert resp.status_code == 409, resp.text
        assert copy.name in _detail(resp)
        assert worker.deployed == [] and route_gate.routed() == {"honeygain": 3}
        worker.docker.containers.get.assert_called_with(copy.name)

    def test_leaving_the_route_is_refused_while_a_routed_copy_through_another_proxy_runs(self, worker):
        """The mark names proxy 3 and nothing runs there, but the routed copy through proxy 2 still does."""
        route_gate.mark("honeygain", 3)
        (copy,) = _copies_on(worker.docker, (2, "honeygain"))
        approval = step_up.sign(WORKER_KEY, step_up.ACTION_LEAVE_ROUTE, "honeygain")
        resp = worker("POST", "/api/containers/honeygain/deploy", {**BODY, "route_approval": approval})
        assert resp.status_code == 409, resp.text
        assert copy.name in _detail(resp) and "proxy 2" in _detail(resp)
        assert worker.deployed == [] and route_gate.routed() == {"honeygain": 3}

    def test_leaving_the_route_beside_a_copy_in_a_shared_tunnel_deploys(self, worker):
        """A copy beside a direct one (not routed) is the Proxies page's, and may stay."""
        route_gate.mark("honeygain", 3)
        _copies_on(worker.docker, (2, None))
        approval = step_up.sign(WORKER_KEY, step_up.ACTION_LEAVE_ROUTE, "honeygain")
        resp = worker("POST", "/api/containers/honeygain/deploy", {**BODY, "route_approval": approval})
        assert resp.status_code == 200, resp.text
        assert len(worker.deployed) == 1 and route_gate.routed() == {}

    def test_leaving_the_route_beside_a_shared_copy_whose_tunnel_is_gone_deploys(self, worker):
        """That copy comes back in the shared tunnel of proxy 2 (proxy_tunnel._start), never routed."""
        route_gate.mark("honeygain", 3)
        _copies_on(worker.docker, (2, None))
        _tunnel_gone(worker.docker, "t2")
        approval = step_up.sign(WORKER_KEY, step_up.ACTION_LEAVE_ROUTE, "honeygain")
        resp = worker("POST", "/api/containers/honeygain/deploy", {**BODY, "route_approval": approval})
        assert resp.status_code == 200, resp.text
        assert len(worker.deployed) == 1 and route_gate.routed() == {}

    def test_leaving_the_route_when_the_copy_cannot_be_looked_up_deploys_nothing(self, worker):
        route_gate.mark("honeygain", 3)
        worker.docker.containers.get.side_effect = RuntimeError("docker is down")
        approval = step_up.sign(WORKER_KEY, step_up.ACTION_LEAVE_ROUTE, "honeygain")
        resp = worker("POST", "/api/containers/honeygain/deploy", {**BODY, "route_approval": approval})
        assert resp.status_code == 503, resp.text
        assert worker.deployed == [] and route_gate.routed() == {"honeygain": 3}

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

    @pytest.mark.parametrize("value", ["true", None])
    def test_status_says_whether_it_is_proxied_only_now(self, worker, monkeypatch, value):
        """What the UI asks before it removes a routed copy (main._refuse_direct_on_proxied_only)."""
        if value is None:
            monkeypatch.delenv(route_gate.PROXIED_ONLY_ENV, raising=False)
        else:
            monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, value)
        monkeypatch.setattr(worker_api.orchestrator, "get_status_cached", lambda: [])
        monkeypatch.setattr(worker_api.orchestrator, "docker_available", lambda: True)
        resp = worker("GET", "/api/status")
        assert resp.status_code == 200, resp.text
        assert resp.json()["proxied_only"] is (value is not None)

    def test_proxied_only_refuses_even_with_an_approval(self, worker, monkeypatch):
        monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, "true")
        approval = step_up.sign(WORKER_KEY, step_up.ACTION_LEAVE_ROUTE, "honeygain")
        resp = worker("POST", "/api/containers/honeygain/deploy", {**BODY, "route_approval": approval})
        assert resp.status_code == 403 and _detail(resp)["error"] == "proxied_only"
        assert worker.deployed == []


PROXY = {"kind": "socks5", "host": "proxy.example", "port": 1080}


class TestTheWorkerProxiedRoutes:
    def _deploy(self, worker, monkeypatch, routed, outcome, **extra):
        """The real proxy_tunnel.deploy, which picks the tunnel under its lock, with no Docker below it."""
        seen = {}

        def deploy(slug, proxy_id, earner, proxy, own_ip, *, own_tunnel):
            seen["own_tunnel"] = own_tunnel
            seen["marked_first"] = route_gate.routed().get(slug)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr(worker_api, "_validate_proxied", lambda slug, spec: None)
        monkeypatch.setattr(worker_api, "_own_egress_ip", AsyncMock(return_value="198.51.100.1"))
        monkeypatch.setattr(proxy_tunnel, "_deploy", deploy)
        monkeypatch.setattr(proxy_tunnel, "_require_running", lambda slug, pid: seen.update(only_if_running=True))
        body = {"earner": BODY, "proxy": PROXY, "routed": routed, **extra}
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

    def test_a_rename_rebuild_of_the_routed_copy_keeps_its_own_tunnel(self, worker, monkeypatch):
        """A device-rename rebuild (only_if_running, not routed) never moves it beside other services."""
        route_gate.mark("honeygain", 3)
        resp, seen = self._deploy(worker, monkeypatch, False, {"container_id": "e"}, only_if_running=True)
        assert resp.status_code == 200, resp.text
        assert seen == {"own_tunnel": True, "only_if_running": True, "marked_first": 3}

    def test_a_copy_deploy_sees_a_route_set_while_it_waited_for_the_tunnel_lock(self, worker, monkeypatch):
        """A routed deploy that finished meanwhile made it the routed service: never into the shared tunnel."""
        lock = proxy_tunnel._deploy_lock(3)

        class RoutedMeanwhile:
            def __enter__(self):
                lock.acquire()
                route_gate.mark("honeygain", 3)

            def __exit__(self, *exc):
                lock.release()

        monkeypatch.setattr(proxy_tunnel, "_deploy_lock", lambda pid: RoutedMeanwhile())
        resp, seen = self._deploy(worker, monkeypatch, False, {"container_id": "e"}, only_if_running=True)
        assert resp.status_code == 200, resp.text
        assert seen == {"own_tunnel": True, "only_if_running": True, "marked_first": 3}

    def test_a_routed_deploy_honours_only_if_running(self, worker, monkeypatch):
        """A refusal (the copy is stopped) changes nothing and leaves no route behind it."""
        resp, seen = self._deploy(worker, monkeypatch, True, {"container_id": "e"}, only_if_running=True)
        assert resp.status_code == 200, resp.text
        assert seen == {"own_tunnel": True, "only_if_running": True, "marked_first": 3}

        def stopped(slug, pid):
            raise proxy_tunnel.ProxyTunnelError("cashpilot-honeygain-p3 is not running, so it was left as it was")

        route_gate.release("honeygain")
        monkeypatch.setattr(proxy_tunnel, "_require_running", stopped)
        resp = worker(
            "POST",
            "/api/proxied/honeygain/3/deploy",
            {"earner": BODY, "proxy": PROXY, "routed": True, "only_if_running": True},
        )
        assert resp.status_code >= 400 and "not running" in _detail(resp)
        assert route_gate.routed() == {}

    def test_a_failed_first_routed_deploy_whose_copy_survived_keeps_the_route(self, worker, monkeypatch):
        """Its earner may run through the proxy: a direct deploy beside it still needs the owner's password."""
        (copy,) = _copies_on(worker.docker, (3, "honeygain"))
        resp, _ = self._deploy(worker, monkeypatch, True, RuntimeError("the start's answer was lost"))
        assert resp.status_code >= 400
        # A code the UI reads to keep both records (TestAFailedRoutedDeployWhoseEarnerSurvived).
        assert _detail(resp)["error"] == "routed_copy_may_exist"
        assert copy.name in _detail(resp)["message"] and "stays routed" in _detail(resp)["message"]
        assert route_gate.routed() == {"honeygain": 3}
        resp = worker("POST", "/api/containers/honeygain/deploy", BODY)
        assert resp.status_code == 403 and _detail(resp)["error"] == "route_locked"
        assert worker.deployed == []

    def test_a_failed_first_routed_deploy_that_cannot_look_for_its_copy_keeps_the_route(self, worker, monkeypatch):
        # The look before the mark answers; the one after the failure does not.
        worker.docker.containers.list.side_effect = [[], RuntimeError("docker is down")]
        resp, _ = self._deploy(worker, monkeypatch, True, RuntimeError("tunnel did not start"))
        assert resp.status_code >= 400 and _detail(resp)["error"] == "routed_copy_may_exist"
        assert "stays routed" in _detail(resp)["message"]
        assert route_gate.routed() == {"honeygain": 3}

    def test_a_failed_routed_deploy_puts_the_previous_route_back(self, worker, monkeypatch):
        route_gate.mark("honeygain", 2)
        resp, _ = self._deploy(worker, monkeypatch, True, RuntimeError("tunnel did not start"))
        assert resp.status_code >= 400
        assert route_gate.routed() == {"honeygain": 2}

    def test_a_failed_first_routed_deploy_leaves_no_route(self, worker, monkeypatch):
        resp, _ = self._deploy(worker, monkeypatch, True, RuntimeError("tunnel did not start"))
        assert resp.status_code >= 400
        assert isinstance(_detail(resp), str)
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

    def test_a_routed_deploy_through_another_proxy_is_refused_while_a_routed_copy_runs(self, worker, monkeypatch):
        """Made through proxy 3, it would leave the copy through 2 running and move the mark off it."""
        route_gate.mark("honeygain", 2)
        (copy,) = _copies_on(worker.docker, (2, "honeygain"))
        resp, seen = self._deploy(worker, monkeypatch, True, {"container_id": "e"})
        assert resp.status_code == 409, resp.text
        assert copy.name in _detail(resp)
        assert seen == {}
        assert route_gate.routed() == {"honeygain": 2}

    @pytest.mark.parametrize("copies", [[(3, "honeygain")], [(2, None)]])
    def test_a_routed_redeploy_through_its_own_proxy_or_beside_a_shared_copy_goes_ahead(
        self, worker, monkeypatch, copies
    ):
        _copies_on(worker.docker, *copies)
        resp, seen = self._deploy(worker, monkeypatch, True, {"container_id": "e"})
        assert resp.status_code == 200, resp.text
        assert seen == {"own_tunnel": True, "marked_first": 3}

    def test_a_routed_copy_whose_tunnel_is_gone_still_counts(self, worker, monkeypatch):
        """The mark names its proxy, so its next start brings it back in a tunnel of its own."""
        route_gate.mark("honeygain", 2)
        (copy,) = _copies_on(worker.docker, (2, "honeygain"))
        _tunnel_gone(worker.docker, "t2")
        resp, seen = self._deploy(worker, monkeypatch, True, {"container_id": "e"})
        assert resp.status_code == 409, resp.text
        assert copy.name in _detail(resp) and seen == {}
        assert route_gate.routed() == {"honeygain": 2}

    def test_a_refused_routed_deploy_never_moves_the_mark_a_start_could_read(self, worker, monkeypatch):
        """proxy_tunnel._start does not hold route_gate.deploying. A start of the copy through 2 that read a
        mark moved to 3 for a moment would rebuild it, tunnel gone, in proxy 2's shared tunnel."""
        route_gate.mark("honeygain", 2)
        _copies_on(worker.docker, (2, "honeygain"))
        _tunnel_gone(worker.docker, "t2")
        real_copies, real_write = proxy_tunnel.routed_copies, route_gate._write
        read_by_a_start, writes = [], []

        def copies_while_a_start_reads(slug, marked):
            read_by_a_start.append(proxy_tunnel._routed_here(slug, 2))
            return real_copies(slug, marked)

        monkeypatch.setattr(worker_api.proxy_tunnel, "routed_copies", copies_while_a_start_reads)
        monkeypatch.setattr(route_gate, "_write", lambda data: (writes.append(dict(data)), real_write(data)))
        resp, seen = self._deploy(worker, monkeypatch, True, {"container_id": "e"})
        assert resp.status_code == 409, resp.text
        assert seen == {}
        assert read_by_a_start == [True]
        assert writes == []
        assert route_gate.routed() == {"honeygain": 2}

    @pytest.mark.parametrize("before", [None, 3])
    def test_a_shared_copy_whose_tunnel_is_gone_does_not_count(self, worker, monkeypatch, before):
        """No mark names its proxy, so its next start brings it back in the shared tunnel, never routed."""
        if before is not None:
            route_gate.mark("honeygain", before)
        _copies_on(worker.docker, (2, None))
        _tunnel_gone(worker.docker, "t2")
        resp, seen = self._deploy(worker, monkeypatch, True, {"container_id": "e"})
        assert resp.status_code == 200, resp.text
        assert seen == {"own_tunnel": True, "marked_first": 3}

    def test_a_routed_deploy_that_cannot_list_the_copies_deploys_nothing(self, worker, monkeypatch):
        worker.docker.containers.list.side_effect = RuntimeError("docker is down")
        resp, seen = self._deploy(worker, monkeypatch, True, {"container_id": "e"})
        assert resp.status_code == 503
        assert seen == {} and route_gate.routed() == {}

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

        def deploy(slug, proxy_id, earner, proxy, own_ip, **_):
            if proxy_id == 2:
                inside.set()
                assert go.wait(5)
                raise RuntimeError("tunnel did not start")
            return {"container_id": "e"}

        monkeypatch.setattr(orchestrator, "service_instances", lambda slug: [])
        monkeypatch.setattr(proxy_tunnel, "routed_copies", lambda slug, marked: [])
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


class TestACopyDeployNeverReadsARouteThatIsTakenBack:
    """A routed deploy takes its mark back only under the tunnel lock a copy deploy reads the mark under.

    Otherwise a copy deploy (routed=false, or a rename rebuild) of the same copy
    reads the mark, builds its earner in a tunnel of its own, and the mark goes
    right after: a routed copy that no route covers, so a direct deploy of the
    same account would need no password.
    """

    @pytest.mark.parametrize("taken_back", ["failed deploy", "direct container found"])
    def test_the_copy_deploy_waits_and_then_shares_the_tunnel(self, monkeypatch, taken_back):
        routed_thread = threading.current_thread()
        copy_made = threading.Event()
        copies = []

        def tunnel_deploy(slug, proxy_id, earner, proxy, own_ip, *, own_tunnel):
            if threading.current_thread() is routed_thread:
                raise RuntimeError("tunnel did not start")
            copies.append(own_tunnel)
            copy_made.set()
            return {"container_id": "c"}

        def copy_meanwhile():
            # The copy deploy comes in while the routed deploy decides to take the mark back.
            threading.Thread(target=proxy_tunnel.deploy, args=("honeygain", 3, BODY, PROXY, None), daemon=True).start()
            copy_made.wait(0.5)

        looks = []

        def routed_copies(slug, marked):
            looks.append(marked)
            if len(looks) == 2:  # the look after the failure
                copy_meanwhile()
            return []

        direct = MagicMock()
        direct.name = "cashpilot-honeygain"

        def service_instances(slug):
            if taken_back == "failed deploy":
                return []
            copy_meanwhile()
            return [direct]

        monkeypatch.setattr(proxy_tunnel, "_deploy", tunnel_deploy)
        monkeypatch.setattr(proxy_tunnel, "routed_copies", routed_copies)
        monkeypatch.setattr(orchestrator, "service_instances", service_instances)
        with pytest.raises(HTTPException):
            worker_api._deploy_routed("honeygain", 3, BODY, PROXY, None)
        assert copy_made.wait(5)
        assert route_gate.routed() == {}
        assert copies == [False]  # in the proxy's shared tunnel, as an unrouted copy

    def test_a_route_put_back_to_another_proxy_never_covers_a_copy_sharing_its_tunnel(self, monkeypatch):
        """A failed routed deploy through 3 found the route on 2; a copy through 2 that came in meanwhile shares 2's tunnel."""
        route_gate.mark("honeygain", 2)
        routed_thread = threading.current_thread()
        copy_made = threading.Event()
        copies = []

        def tunnel_deploy(slug, proxy_id, earner, proxy, own_ip, *, own_tunnel):
            if threading.current_thread() is routed_thread:
                raise RuntimeError("tunnel did not start")
            copies.append(own_tunnel)
            copy_made.set()
            return {"container_id": "c"}

        looks = []

        def routed_copies(slug, marked):
            looks.append(marked)
            if len(looks) == 2:  # the look after the failure: a copy deploy through 2 comes in
                threading.Thread(
                    target=proxy_tunnel.deploy, args=("honeygain", 2, BODY, PROXY, None), daemon=True
                ).start()
                copy_made.wait(0.5)
            return []

        monkeypatch.setattr(proxy_tunnel, "_deploy", tunnel_deploy)
        monkeypatch.setattr(proxy_tunnel, "routed_copies", routed_copies)
        monkeypatch.setattr(proxy_tunnel, "copy_name", lambda slug, pid: "cashpilot-honeygain-p2" if copies else None)
        monkeypatch.setattr(orchestrator, "service_instances", lambda slug: [])
        with pytest.raises(HTTPException):
            worker_api._deploy_routed("honeygain", 3, BODY, PROXY, None)
        assert copy_made.wait(5)
        assert copies == [False]  # in 2's shared tunnel, as an unrouted copy
        assert route_gate.routed() == {}  # so no route through 2 covers it

    def test_a_direct_deploy_leaving_the_route_and_a_copy_deploy_never_interleave(self, monkeypatch):
        """The mark is checked and forgotten under the tunnel lock: the copy deploy waits, then shares the tunnel."""
        route_gate.mark("honeygain", 3)
        copy_made = threading.Event()
        copies = []

        def tunnel_deploy(slug, proxy_id, earner, proxy, own_ip, *, own_tunnel):
            copies.append(own_tunnel)
            copy_made.set()
            return {"container_id": "c"}

        def deploy_raw(**kwargs):
            # A copy deploy through the marked proxy comes in while the direct earner is made.
            threading.Thread(target=proxy_tunnel.deploy, args=("honeygain", 3, BODY, PROXY, None), daemon=True).start()
            copy_made.wait(0.5)
            return "direct-id"

        monkeypatch.setattr(proxy_tunnel, "_deploy", tunnel_deploy)
        monkeypatch.setattr(proxy_tunnel, "copy_name", lambda slug, pid: None)
        monkeypatch.setattr(proxy_tunnel, "routed_copies", lambda slug, marked: [])
        monkeypatch.setattr(orchestrator, "deploy_raw", deploy_raw)
        assert worker_api._deploy_direct(slug="honeygain", leave_route=True) == "direct-id"
        assert copy_made.wait(5)
        assert route_gate.routed() == {}
        assert copies == [False]  # never a tunnel of its own that no route covers


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

    def _start(self, monkeypatch, proxied_only, *, docker_comes_up=True):
        if proxied_only:
            monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, "true")
        monkeypatch.setattr(worker_api.lan_fence, "GUARD_SECONDS", 0.01)
        hold = MagicMock(return_value=[])
        monkeypatch.setattr(worker_api.orchestrator, "hold_direct_earners", hold)
        up = {"docker": False}

        async def run():
            async with worker_api.lifespan(worker_api.app):
                await asyncio.sleep(0.1)
                up["docker"] = docker_comes_up
                await asyncio.sleep(0.1)

        with (
            patch.object(worker_api.orchestrator, "docker_available", side_effect=lambda: up["docker"]),
            patch.object(worker_api, "_check_fence", AsyncMock()),
            patch.object(worker_api, "_fence_loop", AsyncMock()),
            patch.object(worker_api, "UI_URL", ""),
        ):
            asyncio.run(run())
        return hold.call_count

    def test_a_proxied_only_worker_holds_them_at_start_and_on_every_pass_once_docker_answers(self, monkeypatch):
        assert self._start(monkeypatch, True) >= 3

    def test_without_docker_the_passes_do_not_try_and_log_forever(self, monkeypatch):
        """Monitor-only for good: one hold at the start, none from the loop."""
        assert self._start(monkeypatch, True, docker_comes_up=False) == 1

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
        # What the worker itself says on GET /api/status (asked before a route
        # is left); by default what its heartbeat said. Kept out of ``calls``.
        self.status: dict | HTTPException = {
            "proxied_only": json.loads(self.worker_row["system_info"]).get("proxied_only") is True
        }
        self.status_asked = 0

    @staticmethod
    def _no_container(method, path, body):
        """A routed service has no container of its own: the worker's container routes answer 404."""
        if path.startswith("/api/containers/") and not path.endswith("/deploy"):
            return HTTPException(status_code=404, detail="Container not found")
        return {"container_id": "c", "status": "ok"}

    async def hop(self, worker_id, method, path, *, json=None, **kwargs):
        if (method, path) == ("GET", "/api/status"):
            self.status_asked += 1
            if isinstance(self.status, HTTPException):
                raise self.status
            return self.status
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


class TestARemovalDuringARoutedDeploy:
    """_deploy_routed holds the copy's lock through the worker call, as api_add_proxied_copy does."""

    def test_a_removal_waits_for_the_deploy_so_no_earner_runs_without_its_record(self, db):
        ui = _Ui()
        real_lock = main._proxy_copy_lock

        async def go():
            pid = await ui.proxy()
            entered, release, blocked = asyncio.Event(), asyncio.Event(), asyncio.Event()

            class Probe:
                """The real lock; says so when the removal finds it taken."""

                def __init__(self, lock):
                    self.lock = lock

                async def __aenter__(self):
                    if self.lock.locked():
                        blocked.set()
                    await self.lock.acquire()

                async def __aexit__(self, *exc):
                    self.lock.release()

            async def hop(worker_id, method, path, *, json=None, **kwargs):
                ui.calls.append((method, path, json))
                if path.endswith("/deploy"):
                    entered.set()
                    await release.wait()
                    return {"container_id": "c", "status": "deployed"}
                return {"status": "removed", "containers": ["cashpilot-honeygain-p1"]}

            with ui.active(
                patch.object(main, "_proxy_to_worker", hop),
                patch.object(main, "_proxy_copy_lock", lambda *key: Probe(real_lock(*key))),
            ):
                deploying = asyncio.create_task(
                    main.api_deploy(_request(), "honeygain", main.DeployRequest(env=ENV, route=pid))
                )
                await entered.wait()
                removing = asyncio.create_task(main._remove_copy(pid, 1, "honeygain"))
                waiter = asyncio.create_task(blocked.wait())
                await asyncio.wait({removing, waiter}, return_when=asyncio.FIRST_COMPLETED)
                waiter.cancel()
                release.set()
                await asyncio.gather(deploying, removing)
            copies = [c for c in await database.list_proxied_copies(pid) if c["worker_id"] == 1]
            return pid, copies, await database.get_deployment_spec("honeygain", worker_id=1)

        pid, copies, record = _run(go)
        assert ui.paths() == [
            ("POST", f"/api/proxied/honeygain/{pid}/deploy"),
            ("DELETE", f"/api/proxied/honeygain/{pid}"),
        ]
        # The removal came last, so nothing of the service is left: never a
        # routed deployment whose copy record (the cap's bookkeeping) is gone.
        assert copies == []
        assert record is None


class TestARemovalAfterTheUiGaveUpOnTheDeploy:
    """The UI answers 504 after 180 s and frees the copy's lock; the worker's deploy goes on, so its removal waits."""

    def test_the_worker_defers_the_removal_until_the_deploy_ends(self, worker, monkeypatch):
        created, removed = [], []
        service_lock = route_gate.deploying("honeygain")
        waiting = threading.Event()

        class Watched:
            """route_gate.deploying, saying when the routed deploy starts to wait on it."""

            def __enter__(self):
                waiting.set()
                service_lock.acquire()

            def __exit__(self, *exc):
                service_lock.release()

        monkeypatch.setattr(route_gate, "deploying", lambda slug: Watched())
        monkeypatch.setattr(worker_api, "_validate_proxied", lambda slug, spec: None)
        monkeypatch.setattr(worker_api, "_own_egress_ip", AsyncMock(return_value="198.51.100.1"))
        monkeypatch.setattr(worker_api.proxy_tunnel, "routed_copies", lambda slug, marked: [])
        monkeypatch.setattr(
            worker_api.proxy_tunnel, "deploy", lambda slug, pid, *a, **k: created.append(pid) or {"container_id": "e"}
        )
        monkeypatch.setattr(
            worker_api.proxy_tunnel, "remove", lambda slug, pid: removed.append((pid, list(created))) or ["e"]
        )
        answer = {}
        # Another deploy of the service holds its lock for longer than the UI waits.
        service_lock.acquire()
        try:
            deploy = threading.Thread(
                target=lambda: answer.setdefault(
                    "deploy",
                    worker("POST", "/api/proxied/honeygain/3/deploy", {"earner": BODY, "proxy": PROXY, "routed": True}),
                ),
                daemon=True,
            )
            deploy.start()
            assert waiting.wait(5)
            resp = worker("DELETE", "/api/proxied/honeygain/3")
            assert resp.status_code == 503, resp.text
            assert removed == []
            # Control: a copy through another proxy is not held up by it.
            assert worker("DELETE", "/api/proxied/honeygain/4").status_code == 200
        finally:
            service_lock.release()
        deploy.join(5)
        assert answer["deploy"].status_code == 200, answer["deploy"].text
        assert created == [3]
        # The UI's next heartbeat asks again, and now removes the earner the deploy made.
        assert worker("DELETE", "/api/proxied/honeygain/3").status_code == 200
        assert removed == [(4, []), (3, [3])]

    def test_removing_the_service_keeps_the_copy_records_while_a_copy_deploy_runs(self, worker, monkeypatch):
        """remove_all sees only copies that exist, so the one still deploying is reported, not dropped."""
        monkeypatch.setattr(worker_api.orchestrator, "remove_service", lambda slug, **k: {"container_id": "d"})
        monkeypatch.setattr(worker_api.orchestrator, "remove_extra_instances", lambda slug: [])
        monkeypatch.setattr(worker_api.proxy_tunnel, "remove_all", lambda slug: [])
        # Control: a deploy of another service does not hold this one's copies.
        monkeypatch.setitem(worker_api._copy_deploys, ("earnfm", 3), 1)
        resp = worker("DELETE", "/api/containers/honeygain")
        assert resp.status_code == 200, resp.text
        assert "proxied_error" not in resp.json()
        monkeypatch.setitem(worker_api._copy_deploys, ("honeygain", 3), 1)
        resp = worker("DELETE", "/api/containers/honeygain")
        assert resp.status_code == 200, resp.text
        assert "through proxy 3 ran during this removal" in resp.json()["proxied_error"]

    def test_a_copy_deploy_that_ends_during_the_removal_still_keeps_the_records(self, worker, monkeypatch):
        """A deploy that finishes inside remove_all made its earner after remove_all listed the copies."""
        monkeypatch.setattr(worker_api.orchestrator, "remove_service", lambda slug, **k: {"container_id": "d"})
        monkeypatch.setattr(worker_api.orchestrator, "remove_extra_instances", lambda slug: [])
        monkeypatch.setitem(worker_api._copy_deploys, ("honeygain", 3), 1)

        def remove_all(slug):
            # The deploy through proxy 3 answers while remove_all stops the other copies.
            del worker_api._copy_deploys[("honeygain", 3)]
            return ["p4"]

        monkeypatch.setattr(worker_api.proxy_tunnel, "remove_all", remove_all)
        resp = worker("DELETE", "/api/containers/honeygain")
        assert resp.status_code == 200, resp.text
        assert "through proxy 3 ran during this removal" in resp.json()["proxied_error"]
        # Control: with no deploy running at any point, nothing is held.
        monkeypatch.setattr(worker_api.proxy_tunnel, "remove_all", lambda slug: ["p4"])
        resp = worker("DELETE", "/api/containers/honeygain")
        assert resp.status_code == 200, resp.text
        assert "proxied_error" not in resp.json()

    def test_a_copy_deploy_that_starts_and_ends_during_the_removal_still_keeps_the_records(self, worker, monkeypatch):
        """In neither the set read before the removal nor the one read after it: its start is counted."""
        monkeypatch.setattr(worker_api, "_validate_proxied", lambda slug, spec: None)
        monkeypatch.setattr(worker_api, "_own_egress_ip", AsyncMock(return_value="198.51.100.1"))
        monkeypatch.setattr(worker_api.proxy_tunnel, "deploy", lambda *a, **k: {"container_id": "e"})
        monkeypatch.setattr(worker_api.orchestrator, "remove_extra_instances", lambda slug: [])
        monkeypatch.setattr(worker_api.proxy_tunnel, "remove_all", lambda slug: [])
        deployed = []

        def remove_service(slug, **k):
            # A deploy of a copy through proxy 3 arrives and answers while the service goes.
            deployed.append(worker("POST", "/api/proxied/honeygain/3/deploy", {"earner": BODY, "proxy": PROXY}))
            return {"container_id": "d"}

        monkeypatch.setattr(worker_api.orchestrator, "remove_service", remove_service)
        resp = worker("DELETE", "/api/containers/honeygain")
        assert deployed[0].status_code == 200, deployed[0].text
        assert resp.status_code == 200, resp.text
        assert "through proxy 3 ran during this removal" in resp.json()["proxied_error"]
        # Control: a removal with no deploy during it holds nothing, whatever ran before it.
        monkeypatch.setattr(worker_api.orchestrator, "remove_service", lambda slug, **k: {"container_id": "d"})
        resp = worker("DELETE", "/api/containers/honeygain")
        assert resp.status_code == 200, resp.text
        assert "proxied_error" not in resp.json()

    def test_the_ui_keeps_the_records_of_that_removal(self, db):
        ui = _Ui()
        reply = {"status": "removed", "proxied_error": "A deploy of honeygain through proxy 3 is still running"}

        async def go():
            pid = await ui.proxy()
            await database.save_deployment(slug="honeygain", container_id="d", spec={}, worker_id=1)
            await database.save_proxied_copy(pid, 1, "honeygain")
            ui.worker_reply = lambda method, path, body: reply
            with ui.active():
                await main._svc_remove(_request(), "honeygain", 1, False)
            return pid, await database.list_proxied_copies(pid)

        pid, copies = _run(go)
        assert [(c["worker_id"], c["slug"]) for c in copies] == [(1, "honeygain")]


class TestADroppedConnectionIsNotAFailedDeploy:
    """A connection that drops after the request went out leaves the worker working: the UI keeps the records."""

    @staticmethod
    def _hop_raising(exc):
        """_proxy_to_worker as it is, against a worker whose connection fails with ``exc``."""
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.post = AsyncMock(side_effect=exc)
        client.delete = AsyncMock(side_effect=exc)
        client.get = AsyncMock(side_effect=exc)
        return (
            patch.object(main.httpx, "AsyncClient", return_value=client),
            patch.object(main, "_get_verified_worker_url", AsyncMock(return_value=("http://w:8081", {}))),
            patch.object(main.database, "get_worker", AsyncMock(return_value={"id": 1, "url": "http://w:8081"})),
        )

    @pytest.mark.parametrize(
        ("exc", "status"),
        [
            (httpx.ReadError("reset"), 504),
            (httpx.RemoteProtocolError("server disconnected"), 504),
            (httpx.WriteError("broken pipe"), 504),
            # Control: these never reached the worker.
            (httpx.ConnectError("refused"), 503),
            (httpx.ConnectTimeout("slow"), 503),
        ],
        ids=["read", "remote-protocol", "write", "connect", "connect-timeout"],
    )
    def test_the_status_says_whether_the_worker_got_it(self, db, exc, status):
        async def go():
            with ExitStack() as stack:
                for p in self._hop_raising(exc):
                    stack.enter_context(p)
                with pytest.raises(HTTPException) as err:
                    await main._proxy_to_worker(1, "POST", "/api/proxied/honeygain/3/deploy", json={})
            return err.value

        assert _run(go).status_code == status

    def test_a_routed_deploy_keeps_both_records(self, db):
        ui = _Ui()
        hop = ui.hop

        async def go():
            pid = await ui.proxy()
            with ExitStack() as stack:
                for p in self._hop_raising(httpx.ReadError("reset")):
                    stack.enter_context(p)
                real = main._proxy_to_worker
                stack.enter_context(ui.active())
                # Only the deploy goes through the real mapping; the rest stays on the stub.
                main._proxy_to_worker = lambda wid, m, path, **k: (
                    real(wid, m, path, **k) if path.endswith("/deploy") else hop(wid, m, path, **k)
                )
                with pytest.raises(HTTPException) as err:
                    await main.api_deploy(_request(), "honeygain", main.DeployRequest(env=ENV, route=pid))
            copies = [c for c in await database.list_proxied_copies(pid) if c["worker_id"] == 1]
            return pid, err.value, copies, await database.get_deployment_spec("honeygain", worker_id=1)

        pid, err, copies, record = _run(go)
        assert err.status_code == 504
        assert [c["slug"] for c in copies] == ["honeygain"]
        assert proxies.route_of(record) == pid


class TestAFailedRoutedDeployWhoseEarnerSurvived:
    """The worker kept the route because the earner may still run: the UI keeps both records, as after a timeout."""

    @staticmethod
    def _worker_answering(status, detail):
        """_proxy_to_worker as it is, against a worker that answers the deploy with ``status`` and ``detail``."""
        resp = MagicMock(status_code=status, text="")
        resp.json.return_value = {"detail": detail}
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.post = AsyncMock(return_value=resp)
        return (
            patch.object(main.httpx, "AsyncClient", return_value=client),
            patch.object(main, "_get_verified_worker_url", AsyncMock(return_value=("http://w:8081", {}))),
        )

    def _deploy(self, detail):
        ui = _Ui()
        hop = ui.hop

        async def go():
            pid = await ui.proxy()
            with ExitStack() as stack:
                for p in self._worker_answering(409, detail):
                    stack.enter_context(p)
                real = main._proxy_to_worker
                stack.enter_context(ui.active())
                main._proxy_to_worker = lambda wid, m, path, **k: (
                    real(wid, m, path, **k) if path.endswith("/deploy") else hop(wid, m, path, **k)
                )
                with pytest.raises(HTTPException) as err:
                    await main.api_deploy(_request(), "honeygain", main.DeployRequest(env=ENV, route=pid))
            copies = [c for c in await database.list_proxied_copies(pid) if c["worker_id"] == 1]
            return pid, err.value, copies, await database.get_deployment_spec("honeygain", worker_id=1)

        return _run(go)

    def test_both_records_stay_and_the_reason_reaches_the_owner(self, db):
        message = "Docker refused the container: conflict. honeygain stays routed through proxy 1 on this worker"
        pid, err, copies, record = self._deploy({"error": "routed_copy_may_exist", "message": message})
        assert err.status_code == 409
        assert err.detail == {"error": "routed_copy_may_exist", "message": message}
        assert [c["slug"] for c in copies] == ["honeygain"]
        assert proxies.route_of(record) == pid

    def test_control_a_failure_that_left_nothing_drops_the_copy_record(self, db):
        _, err, copies, record = self._deploy("Docker refused the container: conflict")
        assert err.status_code == 409
        assert copies == [] and record is None


class TestTheRouteBoxFollowsTheRecord:
    """svc.routes tells the Route box what a deploy with no route does: api_deploy keeps the recorded route."""

    def _routes(self, ui, heard):
        async def read():
            with ui.active(patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=heard))):
                detail = await main.api_get_service(_request(), "honeygain")
                listed = {s["slug"]: s for s in await main.api_services_available(_request())}
            return detail["routes"], listed["honeygain"]["routes"]

        return read()

    def test_a_recorded_route_the_box_has_not_reported_yet_is_kept(self, db):
        """A routed deploy that timed out keeps its record: Keep redeploys it routed, so the box offers Keep."""
        ui = _Ui()

        async def go():
            pid = await ui.proxy()
            await ui.deploy(main.DeployRequest(env=ENV, route=pid))
            return pid, await self._routes(ui, [])

        pid, (detail, listed) = _run(go)
        assert detail == listed == {"1": pid}

    def test_a_route_only_the_heartbeat_reports_is_not_offered_as_kept(self, db):
        """With no record a deploy with no route goes direct and asks for the password, so the box says Direct."""
        ui = _Ui()
        heard = [{"slug": "honeygain", "_worker_id": 1, "_node": "box", "route": {"proxy_id": 3}}]

        async def go():
            return await self._routes(ui, heard)

        detail, listed = _run(go)
        assert detail == listed == {}


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

    def test_a_proxied_only_box_refuses_leaving_the_route_before_anything_is_removed(self, db):
        """Its worker refuses the direct deploy anyway: the copy and the route stay."""
        row = _worker_row()
        row["system_info"] = json.dumps({**json.loads(row["system_info"]), "proxied_only": True})
        ui = _Ui(row, worker_reply=self._locked)

        async def go():
            uid = await database.create_user("owner", auth.hash_password("right one!"), "owner")
            pid = await ui.proxy()
            await ui.deploy(main.DeployRequest(env=ENV, route=pid))
            ui.calls.clear()
            with pytest.raises(HTTPException) as exc:
                await ui.deploy(main.DeployRequest(env=ENV, route=0, step_up_password="right one!"), owner_uid=uid)
            return pid, exc.value, await database.get_deployment_spec("honeygain", worker_id=1)

        pid, error, record = _run(go)
        assert error.status_code == 403 and error.detail["error"] == "proxied_only"
        assert ui.calls == []
        assert proxies.route_of(record) == pid

    @pytest.mark.parametrize(
        ("status", "code"),
        [
            ({"proxied_only": True}, 403),
            (HTTPException(status_code=502, detail="worker unreachable"), 503),
            ({"name": "box"}, 503),
        ],
    )
    def test_the_worker_itself_is_asked_before_the_routed_copy_goes(self, db, status, code):
        """Its heartbeat still says it may run direct; restarted proxied-only since, or silent, it keeps its route."""
        ui = _Ui(worker_reply=self._locked)

        async def go():
            uid = await database.create_user("owner", auth.hash_password("right one!"), "owner")
            pid = await ui.proxy()
            await ui.deploy(main.DeployRequest(env=ENV, route=pid))
            ui.calls.clear()
            ui.status = status
            with pytest.raises(HTTPException) as exc:
                await ui.deploy(main.DeployRequest(env=ENV, route=0, step_up_password="right one!"), owner_uid=uid)
            return pid, exc.value, await database.get_deployment_spec("honeygain", worker_id=1)

        pid, error, record = _run(go)
        assert error.status_code == code, error.detail
        assert ui.status_asked >= 1
        assert ui.calls == [], "nothing is removed or deployed"
        assert proxies.route_of(record) == pid

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

    def test_after_a_failed_direct_deploy_the_route_can_be_taken_again(self, db):
        """The record says direct, but nothing runs on the box: going back through the proxy is not refused."""

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
            ui.calls.clear()
            ui.worker_reply = ui._no_container
            result = await ui.deploy(main.DeployRequest(env=ENV, route=pid))
            return pid, result, await database.get_deployment_spec("honeygain", worker_id=1)

        pid, result, record = _run(go)
        assert ui.paths() == [("POST", f"/api/proxied/honeygain/{pid}/deploy")]
        assert result["route"]["proxy_id"] == pid
        assert proxies.route_of(record) == pid


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

    @pytest.mark.parametrize("path", ["raw", "service"])
    def test_an_unconfirmed_removal_keeps_the_deployment_until_the_worker_confirms(self, db, path):
        """Its saved route and settings stay while the copy may still run; the confirmation drops them."""
        ui, setup = self._routed(db)

        async def go():
            pid = await setup()

            def slow(method, path_, body):
                if method == "DELETE" and path_.startswith("/api/proxied/"):
                    return HTTPException(status_code=504, detail="the worker did not answer in time")
                return _Ui._no_container(method, path_, body)

            ui.worker_reply = slow
            with ui.active(patch.object(main, "_require_writer", lambda r: None)):
                if path == "raw":
                    result = await main.api_worker_command(
                        _request(), 1, main.WorkerCommand(command="remove", slug="honeygain")
                    )
                else:
                    result = await main._svc_remove(_request(), "honeygain", 1, False)
            pending = await database.get_deployment_spec("honeygain", worker_id=1)
            await main._finish_copy_removal(pid, 1, "honeygain")
            return pid, result, pending, await database.get_deployment_spec("honeygain", worker_id=1)

        pid, result, pending, confirmed = _run(go)
        assert result["status"] == "removing"
        assert pending is not None and proxies.route_of(pending) == pid
        assert confirmed is None

    def test_the_record_stays_until_the_last_copy_of_it_on_the_worker_is_gone(self, db):
        """The routed copy confirms, another copy of it does not: the record waits for the heartbeat's retry."""
        ui, setup = self._routed(db)

        async def go():
            pid = await setup()
            other = await ui.proxy()
            await database.save_proxied_copy(other, 1, "honeygain")
            answer = {"other": HTTPException(status_code=504, detail="the worker did not answer in time")}

            def reply(method, path_, body):
                if method == "DELETE" and path_ == f"/api/proxied/honeygain/{other}" and "other" in answer:
                    return answer["other"]
                return _Ui._no_container(method, path_, body)

            ui.worker_reply = reply
            with ui.active(patch.object(main, "_require_writer", lambda r: None)):
                result = await main._svc_remove(_request(), "honeygain", 1, False)
                pending = await database.get_deployment_spec("honeygain", worker_id=1)
                del answer["other"]
                await main._resume_copy_removals([(other, 1, "honeygain")])
            left = [c for c in await database.list_proxied_copies() if c["worker_id"] == 1]
            return pid, result, pending, left, await database.get_deployment_spec("honeygain", worker_id=1)

        pid, result, pending, left, confirmed = _run(go)
        assert result["status"] == "removing"
        assert pending is not None and proxies.route_of(pending) == pid
        assert left == []
        assert confirmed is None

    @pytest.mark.parametrize("where", ["heartbeat", "again"])
    def test_a_pending_removal_that_fails_for_good_still_drops_the_record(self, db, where):
        """The record waited for the other copy; its removal then fails for good, by the heartbeat's retry or
        the owner's own Remove. Nothing routed runs any more, so the record goes; the copy stays listed."""
        ui, setup = self._routed(db)

        async def go():
            pid = await setup()
            other = await ui.proxy()
            await database.save_proxied_copy(other, 1, "honeygain")
            answer = {"other": HTTPException(status_code=504, detail="the worker did not answer in time")}

            def reply(method, path_, body):
                if method == "DELETE" and path_ == f"/api/proxied/honeygain/{other}":
                    return answer["other"]
                return _Ui._no_container(method, path_, body)

            ui.worker_reply = reply
            with ui.active(patch.object(main, "_require_writer", lambda r: None)):
                await main._svc_remove(_request(), "honeygain", 1, False)
                pending = await database.get_deployment_spec("honeygain", worker_id=1)
                answer["other"] = HTTPException(status_code=409, detail="Docker refused it")
                if where == "heartbeat":
                    await main._resume_copy_removals([(other, 1, "honeygain")])
                else:
                    with pytest.raises(HTTPException):
                        await main._remove_copy(other, 1, "honeygain")
            left = [c for c in await database.list_proxied_copies() if c["worker_id"] == 1]
            return pid, other, pending, left, await database.get_deployment_spec("honeygain", worker_id=1)

        pid, other, pending, left, record = _run(go)
        assert pending is not None and proxies.route_of(pending) == pid
        assert [(c["proxy_id"], bool(c.get("removing_since"))) for c in left] == [(other, False)]
        assert record is None

    def test_removing_the_routed_copy_beside_a_plain_one_drops_the_record(self, db):
        """A plain copy through another proxy that nobody removes runs nothing routed: the record goes."""
        ui, setup = self._routed(db)

        async def go():
            pid = await setup()
            other = await ui.proxy()
            await database.save_proxied_copy(other, 1, "honeygain")
            ui.worker_reply = _Ui._no_container
            with ui.active():
                await main._remove_copy(pid, 1, "honeygain")
            left = [c["proxy_id"] for c in await database.list_proxied_copies() if c["worker_id"] == 1]
            return other, left, await database.get_deployment_spec("honeygain", worker_id=1)

        other, left, record = _run(go)
        assert left == [other]
        assert record is None

    def test_removing_a_plain_copy_beside_the_routed_one_keeps_the_record(self, db):
        ui, setup = self._routed(db)

        async def go():
            pid = await setup()
            other = await ui.proxy()
            await database.save_proxied_copy(other, 1, "honeygain")
            ui.worker_reply = _Ui._no_container
            with ui.active():
                await main._remove_copy(other, 1, "honeygain")
            left = [c["proxy_id"] for c in await database.list_proxied_copies() if c["worker_id"] == 1]
            return pid, left, await database.get_deployment_spec("honeygain", worker_id=1)

        pid, left, record = _run(go)
        assert left == [pid]
        assert record is not None and proxies.route_of(record) == pid

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

    def test_a_copy_through_a_proxy_the_service_was_routed_through_meanwhile_is_refused(self, db):
        """The route is read again under the copy's lock: a routed deploy that finished first keeps its earner."""
        ui = _Ui()
        hop = ui.hop
        routed_asked = asyncio.Event()
        routed_may_answer = asyncio.Event()

        async def gated(worker_id, method, path, *, json=None, **kwargs):
            if (json or {}).get("routed"):
                routed_asked.set()
                await routed_may_answer.wait()
            return await hop(worker_id, method, path, json=json, **kwargs)

        async def go():
            pid = await ui.proxy()
            await ui.deploy(main.DeployRequest(env=ENV))
            with ui.active(), patch.object(main, "_proxy_to_worker", gated):
                routed = asyncio.create_task(
                    main.api_deploy(_request(), "honeygain", main.DeployRequest(env=ENV, route=pid))
                )
                await routed_asked.wait()
                ui.calls.clear()
                # Reads the record before the routed one is saved, then waits for the copy's lock.
                copy = asyncio.create_task(
                    main.api_add_proxied_copy(pid, main.ProxyCopyRequest(worker_id=1, slug="honeygain"), {})
                )
                lock = main._proxy_copy_lock(pid, 1, "honeygain")
                while not getattr(lock, "_waiters", None):
                    await asyncio.sleep(0)
                routed_may_answer.set()
                await routed
                with pytest.raises(HTTPException) as exc:
                    await copy
            copies = [c for c in await database.list_proxied_copies(pid) if c["worker_id"] == 1]
            return pid, exc.value, copies, await database.get_deployment_spec("honeygain", worker_id=1)

        pid, error, copies, record = _run(go)
        assert error.status_code == 409 and "already runs through this proxy" in str(error.detail)
        # Only the routed deploy reached the worker; its copy record and route stay.
        assert [p for _, p in ui.paths()] == [f"/api/proxied/honeygain/{pid}/deploy"]
        assert [c["slug"] for c in copies] == ["honeygain"]
        assert proxies.route_of(record) == pid

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

    def test_the_status_rows_carry_its_image_so_an_outdated_one_is_flagged(self, db):
        """A worker older than the field sends no image: the row keeps "" as before."""
        sent = {**self.ROUTED, "image": "honeygain/honeygain:1.0"}
        for entry, image in ((sent, "honeygain/honeygain:1.0"), (self.ROUTED, "")):
            with patch.object(main.database, "list_workers", AsyncMock(return_value=[_worker_row(proxied=[entry])])):
                (row,) = asyncio.run(main._get_all_worker_containers())
            assert row["image"] == image

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

    @pytest.mark.parametrize(
        "extra",
        [{"cashpilot.proxy": "3"}, {LABEL_ROLE: ROLE_TUNNEL}, {"cashpilot.proxy": "3", LABEL_ROLE: ROLE_TUNNEL}],
    )
    def test_a_direct_earner_carrying_copy_or_tunnel_labels_is_stopped(self, monkeypatch, extra):
        """Labels a direct deploy once kept (DeploySpec.labels): its own network decides, not them."""
        monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, "true")
        direct = _earner(labels={LABEL_MANAGED: "true", "cashpilot.service": "honeygain", **extra})
        direct.attrs["Config"] = {"Image": "honeygain/honeygain:1.0"}
        assert self._hold([direct], tunnel=_tunnel()) == ["cashpilot-honeygain"]
        direct.stop.assert_called_once()

    def test_a_real_tunnel_with_its_service_label_is_left_alone(self, monkeypatch):
        monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, "true")
        tunnel = _earner(
            "cashpilot-tunnel-p3",
            labels={
                LABEL_MANAGED: "true",
                LABEL_ROLE: ROLE_TUNNEL,
                "cashpilot.service": "proxy-tunnel",
                "cashpilot.proxy": "3",
            },
        )
        tunnel.attrs["Config"] = {"Image": "drumsergio/cashpilot-tunnel:1.2.3"}
        assert self._hold([tunnel]) == []
        tunnel.stop.assert_not_called()

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


# ---------------------------------------------------------------------------
# Review round: the route exit takes the copy's lock, labels never hide a
# direct earner, a tunnel is known by its name, and a routed rename
# reaches the plain copies too
# ---------------------------------------------------------------------------


class TestARouteExitDuringARoutedRedeploy:
    """_remove_routed_copies holds the copy's lock, as _remove_copy does."""

    def test_the_exit_waits_for_the_redeploy_so_no_routed_earner_runs_without_its_record(self, db):
        ui = _Ui()
        real_lock = main._proxy_copy_lock
        # The worker: whether a routed earner runs, as its deploys and removals leave it.
        box = {"routed": False}

        async def go():
            uid = await database.create_user("owner", auth.hash_password("right one!"), "owner")
            pid = await ui.proxy()
            entered, release, blocked = asyncio.Event(), asyncio.Event(), asyncio.Event()
            hold = {"on": False}

            class Probe:
                def __init__(self, lock):
                    self.lock = lock

                async def __aenter__(self):
                    if self.lock.locked():
                        blocked.set()
                    await self.lock.acquire()

                async def __aexit__(self, *exc):
                    self.lock.release()

            async def hop(worker_id, method, path, *, json=None, **kwargs):
                if (method, path) == ("GET", "/api/status"):
                    return {"proxied_only": False}
                ui.calls.append((method, path, json))
                if path == f"/api/proxied/honeygain/{pid}/deploy":
                    if hold["on"]:
                        entered.set()
                        await release.wait()
                    box["routed"] = True
                    return {"container_id": "c2", "status": "deployed"}
                if method == "DELETE":
                    box["routed"] = False
                    return {"status": "removed", "containers": []}
                if path == "/api/containers/honeygain/deploy":
                    if box["routed"]:
                        raise HTTPException(status_code=409, detail="beside a routed copy")
                    return {"container_id": "d", "status": "deployed"}
                return {"status": "ok"}

            with ui.active(
                patch.object(main, "_proxy_to_worker", hop),
                patch.object(main, "_proxy_copy_lock", lambda *key: Probe(real_lock(*key))),
                owner_uid=uid,
            ):
                await main.api_deploy(_request(), "honeygain", main.DeployRequest(env=ENV, route=pid))
                hold["on"] = True
                redeploying = asyncio.create_task(
                    main.api_deploy(_request(), "honeygain", main.DeployRequest(env=ENV, route=pid))
                )
                await entered.wait()
                leaving = asyncio.create_task(
                    main.api_deploy(
                        _request(),
                        "honeygain",
                        main.DeployRequest(env=ENV, route=0, step_up_password="right one!"),
                    )
                )
                waiter = asyncio.create_task(blocked.wait())
                await asyncio.wait({leaving, waiter}, return_when=asyncio.FIRST_COMPLETED)
                waiter.cancel()
                release.set()
                await asyncio.gather(redeploying, leaving, return_exceptions=True)
            copies = [c for c in await database.list_proxied_copies(pid) if c["worker_id"] == 1]
            return copies, await database.get_deployment_spec("honeygain", worker_id=1)

        copies, record = _run(go)
        # Whatever order the two land in, the record, the copy row and the box agree.
        routed = proxies.route_of(record) is not None
        assert routed == bool(copies) == box["routed"], (record, copies, box)
        # The exit waited for the redeploy, then removed what it made and ran direct.
        assert not routed


def _labelled_direct(extra):
    """A direct earner made on main, which kept any label it was given (DeploySpec.labels)."""
    c = _earner(labels={LABEL_MANAGED: "true", "cashpilot.service": "honeygain", **extra})
    c.attrs["Config"] = {"Image": "honeygain/honeygain:1.0"}
    return c


# The real one: the worker fixture replaces it on the module.
_SERVICE_INSTANCES = orchestrator.service_instances
_DEPLOY_RAW = orchestrator.deploy_raw
_STRAY_LABELS = [{"cashpilot.proxy": "3"}, {LABEL_ROLE: ROLE_TUNNEL}, {"cashpilot.proxy": "3", LABEL_ROLE: ROLE_TUNNEL}]


class TestLabelsNeverHideADirectEarner:
    """service_instances, _find_container and the LAN fence judge by network and image, as direct_problem does."""

    def _real_copy_and_tunnel(self):
        copy = _earner(
            "cashpilot-honeygain-p3",
            network_mode="container:t3",
            labels={LABEL_MANAGED: "true", "cashpilot.service": "honeygain", "cashpilot.proxy": "3"},
        )
        tunnel = _earner(
            "cashpilot-tunnel-p3",
            labels={LABEL_MANAGED: "true", "cashpilot.service": "honeygain", LABEL_ROLE: ROLE_TUNNEL},
        )
        tunnel.attrs["Config"] = {"Image": "drumsergio/cashpilot-tunnel:2.4.0"}
        return copy, tunnel

    @pytest.mark.parametrize("extra", _STRAY_LABELS)
    def test_service_instances_lists_it_and_still_skips_real_copies_and_tunnels(self, extra):
        direct = _labelled_direct(extra)
        copy, tunnel = self._real_copy_and_tunnel()
        client = MagicMock()
        client.containers.list.return_value = [copy, tunnel, direct]
        assert orchestrator.service_instances("honeygain", client) == [direct]

    @pytest.mark.parametrize("extra", _STRAY_LABELS)
    def test_find_container_finds_it(self, extra):
        direct = _labelled_direct(extra)
        client = MagicMock()
        client.containers.get.return_value = direct
        with patch.object(orchestrator, "_get_client", return_value=client):
            assert orchestrator._find_container("honeygain") is direct

    @pytest.mark.parametrize("extra", _STRAY_LABELS)
    def test_the_lan_fence_gates_it(self, extra):
        from app import lan_fence

        direct = _labelled_direct(extra)
        copy, tunnel = self._real_copy_and_tunnel()
        with (
            patch.object(orchestrator, "fence_gated", return_value=True),
            patch.object(orchestrator, "predates_fence", return_value=False),
        ):
            assert lan_fence._gated(MagicMock(), [copy, tunnel, direct]) == [direct]

    def test_the_worker_refuses_a_routed_deploy_beside_it(self, worker, monkeypatch):
        direct = _labelled_direct({"cashpilot.proxy": "3"})
        worker.docker.containers.list.return_value = [direct]
        monkeypatch.setattr(worker_api.orchestrator, "service_instances", _SERVICE_INSTANCES)
        monkeypatch.setattr(worker_api, "_validate_proxied", lambda slug, spec: None)
        monkeypatch.setattr(worker_api, "_own_egress_ip", AsyncMock(return_value="198.51.100.1"))
        monkeypatch.setattr(
            worker_api.proxy_tunnel, "deploy", MagicMock(side_effect=AssertionError("deployed beside it"))
        )
        resp = worker("POST", "/api/proxied/honeygain/4/deploy", {"earner": BODY, "proxy": PROXY, "routed": True})
        assert resp.status_code == 409, resp.text
        assert direct.name in _detail(resp)
        assert route_gate.routed() == {}


class TestATunnelIsKnownByItsName:
    """is_tunnel_sidecar: the tunnel label AND a tunnel's name, which a direct deploy cannot take. Never the image."""

    MIRROR = "mirror.example:5000/cp-tunnel:1.4.0"

    def _container(self, name, image, extra=None):
        c = _earner(
            name,
            labels={
                LABEL_MANAGED: "true",
                LABEL_ROLE: ROLE_TUNNEL,
                "cashpilot.service": "proxy-tunnel",
                **(extra or {}),
            },
        )
        c.attrs["Config"] = {"Image": image}
        return c

    @pytest.mark.parametrize(
        ("image", "override"),
        [
            ("docker.io/drumsergio/cashpilot-tunnel:2.4.0", ""),
            # Made from a renamed mirror; the override has been removed, or points elsewhere, since.
            (MIRROR, ""),
            (MIRROR, "other.example/own-tunnel:2.5.0"),
            # The override on a registry with a port, matching: the control for the collision below.
            (MIRROR, MIRROR),
        ],
    )
    def test_a_tunnel_stays_one_whatever_image_it_runs(self, monkeypatch, image, override):
        monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, "true")
        monkeypatch.setenv("CASHPILOT_TUNNEL_IMAGE", override)
        tunnel = self._container("cashpilot-tunnel-p3", image, {"cashpilot.proxy": "3"})
        assert orchestrator.is_tunnel_sidecar(tunnel)
        assert orchestrator.is_proxied(tunnel)
        with patch.object(orchestrator, "_get_client", return_value=_client_with()):
            assert orchestrator.direct_problem(tunnel) is None

    @pytest.mark.parametrize(
        ("image", "override"),
        [
            ("ghcr.io/attacker/cashpilot-tunnel:1", ""),
            ("drumsergio/cashpilot-tunnel:2.4.0", ""),
            # Another image on the override's registry and port, and the override's own image.
            ("mirror.example:5000/other:1.0", MIRROR),
            (MIRROR, MIRROR),
        ],
    )
    def test_a_direct_earner_with_a_tunnels_labels_and_image_is_not_one(self, monkeypatch, image, override):
        """A direct deploy once kept any label and image it was given; never the name."""
        monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, "true")
        monkeypatch.setenv("CASHPILOT_TUNNEL_IMAGE", override)
        direct = self._container(
            "cashpilot-honeygain", image, {"cashpilot.service": "honeygain", "cashpilot.proxy": "3"}
        )
        assert not orchestrator.is_tunnel_sidecar(direct)
        assert not orchestrator.is_proxied(direct)
        client = _client_with()
        client.containers.list.return_value = [direct]
        with patch.object(orchestrator, "_get_client", return_value=client):
            assert orchestrator.hold_direct_earners() == ["cashpilot-honeygain"]
        direct.stop.assert_called_once()

    @pytest.mark.parametrize("service", ["tunnel-p3", "proxy-tunnel"])
    def test_a_direct_earner_made_under_a_tunnels_name_is_not_one(self, monkeypatch, service):
        """Before deploy_raw refused the name, a direct deploy of slug tunnel-p3 was cashpilot-tunnel-p3, and
        kept the tunnel's labels (the service label too, before ed3afa9). deploy_raw's own label it cannot lose."""
        monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, "true")
        direct = self._container(
            "cashpilot-tunnel-p3",
            "honeygain/honeygain:1.0",
            {"cashpilot.service": service, "cashpilot.proxy": "3", "cashpilot.version": "1"},
        )
        assert not orchestrator.is_tunnel_sidecar(direct)
        assert not orchestrator.is_proxied(direct)
        client = _client_with()
        client.containers.list.return_value = [direct]
        with patch.object(orchestrator, "_get_client", return_value=client):
            assert orchestrator.hold_direct_earners() == ["cashpilot-tunnel-p3"]
        direct.stop.assert_called_once()

    def test_control_the_name_without_the_label_is_not_one(self):
        named = _earner("cashpilot-tunnel-p3", labels={LABEL_MANAGED: "true", "cashpilot.service": "proxy-tunnel"})
        assert not orchestrator.is_tunnel_sidecar(named)

    @pytest.mark.parametrize(
        ("kwargs", "name"),
        [
            ({"slug": "tunnel-p3"}, "cashpilot-tunnel-p3"),
            ({"slug": "tunnel", "instance": 2}, "cashpilot-tunnel-2"),
            # A proxied earner of a service slugged "tunnel" would take the proxy's shared tunnel's name.
            ({"slug": "tunnel", "name": "cashpilot-tunnel-p3", "network_mode": "container:t3"}, "cashpilot-tunnel-p3"),
        ],
    )
    def test_no_earner_can_take_a_tunnels_name(self, kwargs, name):
        client = MagicMock()
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            pytest.raises(orchestrator.ContainerRuntimeError) as exc,
        ):
            orchestrator.deploy_raw(image="honeygain/honeygain:1.0", **kwargs)
        assert name in str(exc.value)
        client.images.pull.assert_not_called()
        client.containers.run.assert_not_called()

    def test_the_worker_route_refuses_a_tunnels_name(self, worker, monkeypatch):
        monkeypatch.setattr(worker_api.orchestrator, "deploy_raw", _DEPLOY_RAW)
        resp = worker("POST", "/api/containers/tunnel-p3/deploy", BODY)
        assert resp.status_code == 409, resp.text
        assert "cashpilot-tunnel-p3" in str(_detail(resp))
        worker.docker.images.pull.assert_not_called()

    @pytest.mark.parametrize(("slug", "refused"), [("tunnel", True), ("tunnel-x", True), ("tunnelbear", False)])
    def test_the_catalog_refuses_a_slug_that_names_a_tunnel(self, tmp_path, slug, refused):
        from app import catalog

        data = {"name": "X", "slug": slug, "category": "bandwidth", "status": "active", "description": "x"}
        data["docker"] = {"image": "x/x:1"}
        errors = catalog._validate(data, tmp_path / "x.yml")
        assert any("proxy tunnel" in e for e in errors) is refused


class TestARoutedRenameReachesThePlainCopies:
    """A confirmed rename on a routed deploy rebuilds or marks the copies through other proxies, as the direct one."""

    def test_the_copy_through_another_proxy_is_marked_for_the_rename(self, db):
        ui = _Ui()
        legacy = f"{main.HOSTNAME_PREFIX}-{main.HOSTNAME_PREFIX}"

        async def go():
            routed_pid = await ui.proxy()
            other_pid = await ui.proxy()
            await ui.deploy(main.DeployRequest(env={**ENV, "HONEYGAIN_DEVICE_NAME": legacy}, route=routed_pid))
            await database.save_proxied_copy(other_pid, 1, "honeygain")
            ui.calls.clear()
            result = await ui.deploy(main.DeployRequest(env={}, rename_devices=True))
            copies = {c["proxy_id"]: c for c in await database.list_proxied_copies() if c["worker_id"] == 1}
            record = await database.get_deployment_spec("honeygain", worker_id=1)
            return routed_pid, other_pid, result, copies, record

        routed_pid, other_pid, result, copies, record = _run(go)
        assert proxies.route_of(record) == routed_pid
        assert record["env"]["HONEYGAIN_DEVICE_NAME"] != legacy
        # Its box has not reported it running, so it is not rebuilt now: it is
        # marked, so the service page offers the retry, and the deploy says so.
        assert copies[other_pid]["rename_pending"] == 1
        assert copies[routed_pid]["rename_pending"] == 0
        assert any(f"p{other_pid}" in note for note in result.get("kept_from_previous_deployment", []))
