"""One shared tunnel per proxy on a worker (app/proxy_tunnel.py, docs/proxies.md).

These run the real module against a small in-memory Docker: containers have
labels, a status, a NetworkMode, a secret volume and a ready file, so a test
can follow every container through a deploy, a stop, a tunnel replacement or a
migration. What only a real daemon can prove (fail closed, the capture, RAM)
is in scripts/proxy_leak_test.sh, scripts/proxy_leak_test_tailscale.sh and
scripts/proxy_shared_tunnel_lab.sh.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import errno
import io
import itertools
import json
import os
import re
import stat
import tarfile
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

pytest.importorskip("docker")

from docker.errors import APIError, NotFound  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import orchestrator, proxies, proxy_tunnel, worker_api  # noqa: E402
from app.constants import LABEL_MANAGED, LABEL_PROXY, LABEL_ROLE, LABEL_SERVICE  # noqa: E402

IMAGE = "drumsergio/cashpilot-tunnel:2.2.0"
NEW_IMAGE = "drumsergio/cashpilot-tunnel:2.3.0"
EXIT = {"ip": "93.184.215.14", "country": "DE"}
PASSWORD = "s3cr3t-p@ss"
NEW_PASSWORD = "n3w-pass"  # ggignore: fake test value, not a credential
_clock = itertools.count(1)
# The fixture makes time.sleep a no-op; a test that needs time to pass uses this.
_real_sleep = time.sleep


def _now() -> str:
    # Strictly increasing, so "started after" comparisons mean what they say.
    return f"2026-11-09T10:{next(_clock) // 60:02d}:{next(_clock) % 60:02d}.{next(_clock):06d}Z"


class FakeContainer:
    def __init__(self, docker: FakeDocker, name: str, kw: dict[str, Any]):
        self._d = docker
        self.id = f"{next(docker.ids):064x}"
        self.short_id = self.id[:12]
        self.name = name
        self.status = "created"
        self.labels = dict(kw.get("labels") or {})
        self.files: dict[str, str] = {}
        self.kw = kw
        created = (datetime.now(UTC) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
        self.attrs = {
            "Created": created,
            "State": {"StartedAt": ""},
            "Config": {
                "Image": kw.get("image"),
                "Env": kw.get("environment") or [],
                "Labels": self.labels,
                "Cmd": kw.get("command"),
                "Hostname": kw.get("hostname") or self.id[:12],
            },
            "HostConfig": {
                "NetworkMode": kw.get("network_mode") or kw.get("network") or "bridge",
                "CapDrop": kw.get("cap_drop"),
                "CapAdd": kw.get("cap_add"),
                "SecurityOpt": kw.get("security_opt"),
                "Memory": kw.get("mem_limit") or 0,
                "RestartPolicy": dict(kw.get("restart_policy") or {"Name": "no"}),
            },
            "Mounts": [
                {"Type": "volume", "Name": n, "Destination": d["bind"], "RW": d["mode"] == "rw"}
                for n, d in (kw.get("volumes") or {}).items()
            ],
        }
        self.starts = 0

    # --- lifecycle
    def _alive(self):
        if self.id not in self._d.by_id:
            raise NotFound(self.name)

    def reload(self):
        self._alive()
        real = self._d.by_id[self.id]
        if real is not self:
            # A model read earlier (copy.copy of the container): docker-py keeps
            # its name and status cached until reload.
            self.name, self.status = real.name, real.status

    def start(self):
        self._alive()
        if self.id in self._d.broken:
            raise APIError("500 Server Error: get: no such volume")
        joined = self.attrs["HostConfig"]["NetworkMode"]
        if joined.startswith("container:"):
            host = self._d.by_id.get(joined.removeprefix("container:"))
            # Docker refuses to start a container whose namespace holder is not running.
            if host is None or host.status != "running":
                raise RuntimeError(f"cannot join network of a non running container: {joined}")
        self.status = "running"
        self.starts += 1
        self.attrs["State"]["StartedAt"] = _now()

    def stop(self, timeout=None):
        self._alive()
        if self.status == "running":
            self.status = "exited"
            self._d.events.append(("stop", self.name))

    def restart(self, timeout=None):
        self.stop()
        self.start()

    def update(self, **_kw):
        # The shipped socket proxy refuses POST /containers/{id}/update on purpose
        # (docs/security-defaults.md, tests/test_socket_proxy.py).
        self._alive()
        self._d.updates.append(self.name)
        raise APIError("403 Client Error: Forbidden (request denied by socket proxy policy)")

    def remove(self, force=False, v=False):
        self._alive()
        del self._d.by_id[self.id]
        self._d.removals.append((self.name, v))
        self._d.events.append(("remove", self.name))

    def rename(self, name):
        self._alive()
        if any(c.name == name for c in self._d.by_id.values()):
            raise RuntimeError("409 Conflict: name in use")
        self.name = name

    # --- the tunnel's secret volume and ready file
    def put_archive(self, path, blob):
        if self.id in self._d.broken:
            # What Docker 29 answers for a container a daemon restart left
            # with a Binds entry that has no source.
            raise APIError(f'500 Server Error: /containers/{self.id}/archive ("get: no such volume")')
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
            for m in tar.getmembers():
                self.files[m.name] = tar.extractfile(m).read().decode()
        return True

    def get_archive(self, path):
        if self.id in self._d.unreadable:
            # Docker mounts a container's volumes to read its files as it does
            # to write them, so a broken one refuses the read the same way.
            raise APIError(f'500 Server Error: /containers/{self.id}/archive ("get: no such volume")')
        name = path.rsplit("/", 1)[1]
        if name not in self.files:
            raise NotFound(path)
        data = self.files[name].encode()
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        return iter([buf.getvalue()]), {}

    def exec_run(self, cmd, demux=False):
        if self.status == "running" and self.labels.get(LABEL_ROLE) == "tunnel" and self._d.ready(self):
            return 0, json.dumps(EXIT).encode()
        return 1, b""

    def logs(self, tail=5):
        return b"tunnel log"


class FakeDocker:
    def __init__(self):
        self.ids = itertools.count(1)
        self.by_id: dict[str, FakeContainer] = {}
        self.events: list[tuple[str, str]] = []
        self.removals: list[tuple[str, bool]] = []  # (name, whether its volumes went too)
        self.broken_auth: set[str] = set()  # proxy_auth values whose tunnel never gets an exit
        self.broken: set[str] = set()  # container ids Docker can no longer write to or start
        self.unreadable: set[str] = set()  # container ids whose files Docker can no longer read
        self.updates: list[str] = []  # container updates asked for, every one refused
        self.containers = self
        self.images = self

    # images
    def pull(self, image):
        return None

    # containers
    def ready(self, c: FakeContainer) -> bool:
        return c.files.get("proxy_auth", "") not in self.broken_auth

    def get(self, key):
        for c in self.by_id.values():
            if key in (c.id, c.name):
                return c
        raise NotFound(key)

    def list(self, all=False, filters=None):
        out = []
        for c in self.by_id.values():
            ok = True
            for f in (filters or {}).get("label", []):
                k, _, v = f.partition("=")
                if k not in c.labels or ("=" in f and c.labels[k] != v):
                    ok = False
            if ok and (all or c.status == "running"):
                out.append(c)
        return out

    def create(self, **kw):
        name = kw["name"]
        if any(c.name == name for c in self.by_id.values()):
            raise RuntimeError(f"409 Conflict: {name}")
        c = FakeContainer(self, name, kw)
        self.by_id[c.id] = c
        self.events.append(("create", name))
        return c

    # helpers for assertions
    def named(self, name) -> FakeContainer | None:
        return next((c for c in self.by_id.values() if c.name == name), None)

    def tunnels(self) -> list[FakeContainer]:
        return [c for c in self.by_id.values() if c.labels.get(LABEL_ROLE) == "tunnel"]


def _socks(**extra):
    return {"kind": "socks5", "host": "203.0.113.9", "port": 1080, "username": "u1", "password": PASSWORD, **extra}


def _tailscale(**extra):
    return {"kind": "tailscale", "auth_key": "tskey-auth-kTEST-0123456789", "exit_node": "exit-box", **extra}


def _fake_deploy_raw(docker: FakeDocker):
    """orchestrator.deploy_raw's contract: a container under the name is replaced, never lost.

    Past the deadline before anything changes, nothing does. Otherwise the old
    one is stopped and moved aside until the new one runs; a deadline passed
    meanwhile (a slow stop) or a failed create puts it back, stopped: an earner
    inside a tunnel's namespace is never started there (orchestrator._start_again).
    """

    def deploy_raw(*, slug, image, env, network_mode, labels, name, deadline=None, on_created=None, **_kw):
        if deadline is not None:
            orchestrator._refuse_past(deadline, image)
        old = docker.named(name)
        was_running = old is not None and old.status == "running"
        if old is not None:
            old.stop()
            # As orchestrator._move_aside: a container already aside of the same
            # copy is taken for a leftover of an older deploy and removed.
            leftover = docker.named(f"{name}{orchestrator.REPLACED_SUFFIX}")
            if leftover is not None and leftover.id != old.id:
                leftover.remove(force=True, v=True)
            old.rename(f"{name}{orchestrator.REPLACED_SUFFIX}")
        all_labels = {**labels, LABEL_SERVICE: slug, LABEL_MANAGED: "true", "cashpilot.deployed-by": "worker"}
        try:
            if deadline is not None:
                orchestrator._refuse_past(deadline, image)
            c = docker.create(
                image=image,
                name=name,
                environment=[f"{k}={v}" for k, v in env.items()],
                labels=all_labels,
                network_mode=network_mode,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                restart_policy={"Name": "no"},
            )
            if on_created is not None:
                on_created(c.id)
            c.start()
        except Exception:
            if old is not None:
                old.rename(name)
                if was_running and not network_mode.startswith("container:"):
                    old.start()
            raise
        if old is not None:
            # As orchestrator._remove_replaced: a refused removal leaves a leftover only.
            with contextlib.suppress(Exception):
                old.remove(force=True)
        return c.id

    return deploy_raw


@pytest.fixture
def docker(tmp_path):
    d = FakeDocker()
    real_wait = proxy_tunnel._wait_ready
    with (
        # A tunnel with no exit is given up on in a fraction of a second here.
        patch.object(proxy_tunnel, "_wait_ready", lambda c, timeout=0.3: real_wait(c, timeout)),
        patch.object(orchestrator, "_get_client", return_value=d),
        patch.object(orchestrator, "deploy_raw", side_effect=_fake_deploy_raw(d)),
        patch.object(orchestrator, "container_network", return_value=None),
        patch.object(orchestrator, "_get_stop_timeout", return_value=1),
        patch.object(proxy_tunnel, "HELD_MARKER", str(tmp_path / ".proxied_held")),
        patch.object(proxy_tunnel, "FAILED_MARKER", str(tmp_path / ".proxied_failed")),
        patch.object(proxy_tunnel, "KEPT_MARKER", str(tmp_path / ".proxied_kept")),
        patch.object(proxy_tunnel, "NEW_MARKER", str(tmp_path / ".proxied_new")),
        patch.object(proxy_tunnel, "CONTAINER_MARKER", str(tmp_path / ".proxied_containers")),
        patch.object(proxy_tunnel, "CREATED_MARKER", str(tmp_path / ".proxied_created")),
        patch.object(proxy_tunnel, "MOVE_MARKER", str(tmp_path / ".proxied_moves")),
        patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": IMAGE}),
        patch.object(proxy_tunnel.time, "sleep", lambda _s: None),
        patch.dict(proxy_tunnel._replace_failed, clear=True),
        patch.object(proxy_tunnel, "_recovery_skipped", set()),
    ):
        yield d


def _deploy(slug, proxy=None, proxy_id=3):
    return proxy_tunnel.deploy(
        slug, proxy_id, {"image": f"{slug}/{slug}:1", "env": {"K": slug}}, proxy or _socks(), None
    )


@pytest.mark.parametrize("routed", [False, True])
def test_worker_proxy_deploy_requires_the_approved_id_once(docker, tmp_path, routed):
    client = TestClient(worker_api.app)
    path = "/api/proxied/honeygain/3/deploy"
    body = {"earner": {"image": "honeygain/honeygain"}, "proxy": _socks(), "routed": routed}
    with (
        patch.object(worker_api.route_gate, "ROUTED_MARKER", str(tmp_path / ".routed")),
        patch.object(worker_api, "_verify_api_key"),
        patch.object(worker_api, "_validate_proxied"),
        patch.object(worker_api, "_own_egress_ip", AsyncMock(return_value=None)),
    ):
        first = client.post(path, json=body)
        assert first.status_code == 200, first.text
        original = first.json()["container_id"]
        assert client.get(path).json()["expected_container"] == original

        refused = client.post(path, json=body)
        assert refused.status_code == 409
        assert refused.json()["detail"]["current_container"] == original
        assert docker.named("cashpilot-honeygain-p3").id == original

        body["expected_container"] = original
        approved = client.post(path, json=body)
        assert approved.status_code == 200, approved.text
        successor = approved.json()["container_id"]
        assert successor != original
        replay = client.post(path, json=body)
        assert replay.status_code == 409
        assert replay.json()["detail"]["current_container"] == successor
        assert docker.named("cashpilot-honeygain-p3").id == successor


def _member_ids(docker, tunnel):
    return sorted(
        c.name for c in docker.by_id.values() if c.attrs["HostConfig"]["NetworkMode"] == f"container:{tunnel.id}"
    )


# ---------------------------------------------------------------------------
# Deploy: one tunnel per proxy
# ---------------------------------------------------------------------------


class TestOneTunnelPerProxy:
    def test_a_second_copy_reuses_the_tunnel_and_touches_no_other_copy(self, docker):
        first = _deploy("honeygain")
        a = docker.named("cashpilot-honeygain-p3")
        a_starts = a.starts
        second = _deploy("earnfm")
        (tunnel,) = docker.tunnels()
        assert tunnel.name == "cashpilot-tunnel-p3"
        assert first["tunnel_id"] == second["tunnel_id"] == tunnel.id
        assert _member_ids(docker, tunnel) == ["cashpilot-earnfm-p3", "cashpilot-honeygain-p3"]
        # The first copy was neither recreated nor restarted.
        assert docker.named("cashpilot-honeygain-p3") is a and a.starts == a_starts
        assert [e for e in docker.events if e[0] == "create" and "tunnel" in e[1]] == [
            ("create", "cashpilot-tunnel-p3-next")
        ]

    def test_seven_copies_one_tunnel_one_tailnet_device(self, docker):
        for slug in ("repocket", "earnfm", "packetstream", "traffmonetizer", "proxyrack", "proxybase", "proxylite"):
            _deploy(slug, _tailscale())
        (tunnel,) = docker.tunnels()
        assert len(_member_ids(docker, tunnel)) == 7
        # The tailnet host name names the proxy, not a copy.
        assert tunnel.files["hostname"] == "cashpilot-p3"
        assert tunnel.kw["hostname"] == "tunnel-p3"

    def test_two_proxies_get_two_tunnels(self, docker):
        _deploy("honeygain", proxy_id=3)
        _deploy("honeygain", proxy_id=4)
        assert sorted(t.name for t in docker.tunnels()) == ["cashpilot-tunnel-p3", "cashpilot-tunnel-p4"]

    def test_new_settings_restart_the_tunnel_in_place_and_recreate_no_copy(self, docker):
        # Earners keep their device id in their writable layer: a recreated copy
        # is a new device to its provider, so an edit must never recreate one.
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        earner = docker.named("cashpilot-honeygain-p3")
        starts = earner.starts
        _deploy("earnfm", _socks(password=NEW_PASSWORD))
        assert docker.tunnels() == [tunnel] and tunnel.status == "running"
        assert tunnel.files["proxy_auth"] == f"u1:{NEW_PASSWORD}@"
        assert docker.named("cashpilot-honeygain-p3") is earner
        # Restarted into the tunnel's new namespace, not left in the old one.
        assert earner.status == "running" and earner.starts == starts + 1
        assert earner.attrs["State"]["StartedAt"] > tunnel.attrs["State"]["StartedAt"]
        assert _member_ids(docker, tunnel) == ["cashpilot-earnfm-p3", "cashpilot-honeygain-p3"]
        # The new settings proved an exit in a throwaway tunnel first, which is gone.
        created = [n for op, n in docker.events if op == "create"]
        assert any(n.startswith("cashpilot-tunnel-test-") for n in created)
        assert [c.name for c in docker.by_id.values() if "tunnel-test" in c.name] == []
        assert ("create", "cashpilot-honeygain-p3-next") not in docker.events

    def test_new_settings_that_fail_in_the_tunnel_after_the_test_put_the_old_ones_back(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        docker.broken_auth.add(f"u1:{NEW_PASSWORD}@")
        with (
            patch.object(proxy_tunnel, "_prove"),
            pytest.raises(proxy_tunnel.ProxyTunnelError) as err,
        ):
            _deploy("earnfm", _socks(password=NEW_PASSWORD))
        assert NEW_PASSWORD not in str(err.value)
        assert docker.tunnels() == [tunnel] and tunnel.status == "running"
        assert tunnel.files["proxy_auth"] == proxy_tunnel.proxy_auth("u1", PASSWORD)
        assert docker.named("cashpilot-honeygain-p3").status == "running"

    def test_a_new_tunnel_image_never_recreates_another_copy(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        earner = docker.named("cashpilot-honeygain-p3")
        with patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": NEW_IMAGE}):
            _deploy("earnfm")
            proxy_tunnel.stop("honeygain", 3)
            proxy_tunnel.start("honeygain", 3, _socks(), None)
        assert docker.tunnels() == [tunnel] and tunnel.kw["image"] == IMAGE
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "running"
        assert _member_ids(docker, tunnel) == ["cashpilot-earnfm-p3", "cashpilot-honeygain-p3"]

    def test_a_new_tunnel_image_is_taken_by_a_redeploy_with_no_other_copy(self, docker):
        _deploy("honeygain")
        old = docker.named("cashpilot-tunnel-p3")
        with patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": NEW_IMAGE}):
            _deploy("honeygain")
        (tunnel,) = docker.tunnels()
        assert tunnel.id != old.id and tunnel.kw["image"] == NEW_IMAGE
        assert _member_ids(docker, tunnel) == ["cashpilot-honeygain-p3"]

    def test_an_earner_image_that_cannot_be_pulled_never_replaces_the_tunnel(self, docker):
        """A new tunnel image is taken by moving the copy into a new tunnel: never for a deploy that cannot finish."""
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        earner = docker.named("cashpilot-honeygain-p3")
        with (
            patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": NEW_IMAGE}),
            patch.object(docker, "pull", side_effect=APIError("manifest for honeygain/honeygain:1 unknown")),
            pytest.raises(orchestrator.ContainerRuntimeError),
        ):
            _deploy("honeygain")
        # The same containers: the copy's writable layer, and its device, are intact.
        assert docker.tunnels() == [tunnel] and tunnel.status == "running"
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "running"

    def test_a_deadline_passed_while_the_old_copy_stops_keeps_it(self, docker):
        """The old copy stays until its replacement runs, so a slow stop past the deadline puts it back."""
        _deploy("honeygain")
        earner = docker.named("cashpilot-honeygain-p3")
        real_stop = earner.stop

        def slow_stop(timeout=None):
            _real_sleep(1.2)
            real_stop(timeout)

        earner.stop = slow_stop
        with pytest.raises(orchestrator.ContainerRuntimeError):
            proxy_tunnel.deploy(
                "honeygain",
                3,
                {"image": "honeygain/honeygain:1", "env": {"K": "honeygain"}},
                _socks(),
                None,
                deadline=time.monotonic() + 1.0,
            )
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "running"

    def test_a_redeploy_drops_the_volumes_the_old_earners_image_declared(self, docker):
        """As removing the old earner with its volumes did: the new copy starts on fresh ones, none is left behind."""
        _deploy("honeygain")
        anonymous, named = "ab" * 32, "cashpilot-data"
        docker.named("cashpilot-honeygain-p3").attrs["Mounts"] = [
            {"Type": "volume", "Name": anonymous, "Destination": "/data", "RW": True},
            {"Type": "volume", "Name": named, "Destination": "/keep", "RW": True},
        ]
        removed = []

        class Volumes:
            def get(self, name):
                return type("V", (), {"remove": lambda _self: removed.append(name)})()

        docker.volumes = Volumes()
        _deploy("honeygain")
        assert removed == [anonymous]

    def test_a_redeploy_of_a_legacy_pair_moves_it_into_the_shared_tunnel_and_drops_its_own(self, docker):
        legacy = _legacy_pair(docker, "honeygain", proxy=_socks())
        _deploy("honeygain")
        (tunnel,) = docker.tunnels()
        assert tunnel.id != legacy.id and docker.named(legacy.name) is None
        assert _member_ids(docker, tunnel) == ["cashpilot-honeygain-p3"]
        assert docker.named("cashpilot-honeygain-p3").status == "running"

    def test_a_failed_redeploy_of_a_legacy_pair_puts_the_pair_back_running(self, docker):
        legacy = _legacy_pair(docker, "honeygain", proxy=_socks())
        earner = docker.named("cashpilot-honeygain-p3")
        real_create = docker.create

        def refuse_the_earner(**kw):
            if kw["name"] == "cashpilot-honeygain-p3":
                raise APIError("500 Server Error: create failed")
            return real_create(**kw)

        with patch.object(docker, "create", side_effect=refuse_the_earner), pytest.raises(APIError):
            _deploy("honeygain")
        assert docker.tunnels() == [legacy] and legacy.status == "running"
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "running"

    def test_a_failed_redeploy_starts_the_old_earner_only_once_its_tunnel_is_ready(self, docker):
        """A tunnel Docker restarted meanwhile may not have loaded its firewall yet: the earner waits for /run/ready."""
        legacy = _legacy_pair(docker, "honeygain", proxy=_socks())
        earner = docker.named("cashpilot-honeygain-p3")
        real_create = docker.create

        def refuse_the_earner(**kw):
            if kw["name"] == "cashpilot-honeygain-p3":
                # The legacy tunnel restarted and has not written /run/ready yet.
                legacy.files["proxy_auth"] = "restarting"
                docker.broken_auth.add("restarting")
                raise APIError("500 Server Error: create failed")
            return real_create(**kw)

        with patch.object(docker, "create", side_effect=refuse_the_earner), pytest.raises(APIError):
            _deploy("honeygain")
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "exited"
        proxy_tunnel.status()
        assert earner.status == "exited"
        # Ready again: the heartbeat starts it.
        docker.broken_auth.discard("restarting")
        proxy_tunnel.status()
        assert earner.status == "running"

    def test_a_failed_redeploy_of_a_stopped_copy_keeps_it_stopped(self, docker):
        """The deploy clears the stop before it begins; a failure puts it back, so the heartbeat never starts it."""
        _deploy("honeygain")
        assert proxy_tunnel.stop("honeygain", 3) == {"was_running": True}
        earner = docker.named("cashpilot-honeygain-p3")
        real_create = docker.create

        def refuse_the_earner(**kw):
            if kw["name"] == "cashpilot-honeygain-p3":
                raise APIError("500 Server Error: create failed")
            return real_create(**kw)

        with patch.object(docker, "create", side_effect=refuse_the_earner), pytest.raises(APIError):
            _deploy("honeygain")
        assert "cashpilot-honeygain-p3" in proxy_tunnel.held()
        proxy_tunnel.status()
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "exited"

    def test_control_a_failed_redeploy_of_a_running_copy_runs_it_again(self, docker):
        _deploy("honeygain")
        earner = docker.named("cashpilot-honeygain-p3")
        real_create = docker.create

        def refuse_the_earner(**kw):
            if kw["name"] == "cashpilot-honeygain-p3":
                raise APIError("500 Server Error: create failed")
            return real_create(**kw)

        with patch.object(docker, "create", side_effect=refuse_the_earner), pytest.raises(APIError):
            _deploy("honeygain")
        assert "cashpilot-honeygain-p3" not in proxy_tunnel.held()
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "running"

    def test_a_failed_redeploy_that_left_the_old_earner_aside_puts_it_back(self, docker):
        """deploy_raw keeps it aside when the failed container still holds the name; that one goes, so it comes back."""
        _deploy("honeygain")
        earner = docker.named("cashpilot-honeygain-p3")

        def failed_and_left(*, slug, image, env, network_mode, labels, name, **_kw):
            earner.stop()
            earner.rename(f"{name}{orchestrator.REPLACED_SUFFIX}")
            created = docker.create(
                image=image, name=name, labels={**labels, LABEL_SERVICE: slug, LABEL_MANAGED: "true"}
            )
            _kw["on_created"](created.id)
            raise orchestrator.ContainerRuntimeError("start failed; the previous container is kept as -replaced")

        with (
            patch.object(orchestrator, "deploy_raw", side_effect=failed_and_left),
            pytest.raises(orchestrator.ContainerRuntimeError),
        ):
            _deploy("honeygain")
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "running"
        assert docker.named("cashpilot-honeygain-p3-replaced") is None

    def test_a_failed_redeploy_of_a_stopped_copy_keeps_it_stopped_when_the_rename_back_fails(self, docker):
        """The stop is recorded again before anything else is tried, so a failed step cannot skip it."""
        _deploy("honeygain")
        assert proxy_tunnel.stop("honeygain", 3) == {"was_running": True}
        earner = docker.named("cashpilot-honeygain-p3")
        real_create, real_rename = docker.create, earner.rename
        refusals = iter(range(2))  # deploy_raw's rename back, then _put_old_back's

        def refuse_the_earner(**kw):
            if kw["name"] == "cashpilot-honeygain-p3":
                raise APIError("500 Server Error: create failed")
            return real_create(**kw)

        def flaky_rename(to):
            if to == "cashpilot-honeygain-p3" and next(refusals, None) is not None:
                raise APIError("500 Server Error: rename failed")
            real_rename(to)

        earner.rename = flaky_rename
        with patch.object(docker, "create", side_effect=refuse_the_earner), pytest.raises(APIError):
            _deploy("honeygain")
        assert earner.name.endswith(orchestrator.REPLACED_SUFFIX)
        assert "cashpilot-honeygain-p3" in proxy_tunnel.held()
        # The heartbeat gives it its name back, and leaves it stopped.
        proxy_tunnel.status()
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "exited"

    def test_a_failed_replacement_docker_will_not_remove_never_replaces_the_copy(self, docker):
        """deploy_raw keeps the old earner aside for this: it comes back, the container that failed never runs."""
        _deploy("honeygain")
        earner = docker.named("cashpilot-honeygain-p3")
        refused = {"on": True}
        made = []

        def failed_and_stuck(*, slug, image, env, network_mode, labels, name, **_kw):
            earner.stop()
            earner.rename(f"{name}{orchestrator.REPLACED_SUFFIX}")
            new = docker.create(
                image=image,
                name=name,
                network_mode=network_mode,
                labels={**labels, LABEL_SERVICE: slug, LABEL_MANAGED: "true"},
            )
            _kw["on_created"](new.id)
            real_remove = new.remove

            def stuck_remove(force=False, v=False):
                if refused["on"]:
                    raise APIError("409 Client Error: removal of container is already in progress")
                real_remove(force=force, v=v)

            new.remove = stuck_remove
            made.append(new)
            raise orchestrator.ContainerRuntimeError("start failed; the previous container is kept as -replaced")

        with (
            patch.object(orchestrator, "deploy_raw", side_effect=failed_and_stuck),
            pytest.raises(orchestrator.ContainerRuntimeError),  # the deploy's own error, not the refused removal
        ):
            _deploy("honeygain")
        (new,) = made
        # While Docker refuses, neither is lost and the failed one is never started.
        proxy_tunnel.status()
        assert earner.id in docker.by_id and earner.status == "exited"
        assert new.status == "created"
        # Once it can, the failed one goes and the old earner is the copy again.
        refused["on"] = False
        proxy_tunnel.status()
        assert new.id not in docker.by_id
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "running"

    def test_a_tunnel_that_cannot_start_costs_the_running_copies_nothing(self, docker):
        _deploy("honeygain")
        old = docker.named("cashpilot-tunnel-p3")
        earner = docker.named("cashpilot-honeygain-p3")
        starts = (old.starts, earner.starts)
        docker.broken_auth.add("u1:wrong@")
        with pytest.raises(proxy_tunnel.ProxyTunnelError) as err:
            _deploy("earnfm", _socks(password="wrong"))
        assert "wrong" not in str(err.value)
        assert docker.tunnels() == [old] and old.status == "running"
        assert (
            old.files["proxy_auth"] == proxy_tunnel.proxy_auth("u1", PASSWORD) and (old.starts, earner.starts) == starts
        )
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "running"
        assert docker.named("cashpilot-earnfm-p3") is None

    def test_a_copy_that_fails_to_create_leaves_no_empty_tunnel(self, docker):
        with (
            patch.object(orchestrator, "deploy_raw", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError),
        ):
            _deploy("honeygain")
        assert docker.tunnels() == []

    def test_a_copy_that_fails_to_create_keeps_a_tunnel_others_use(self, docker):
        _deploy("honeygain")
        with (
            patch.object(orchestrator, "deploy_raw", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError),
        ):
            _deploy("earnfm")
        (tunnel,) = docker.tunnels()
        assert tunnel.status == "running"

    def test_a_redeploy_of_one_copy_replaces_only_its_earner(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        b = docker.named("cashpilot-earnfm-p3")
        old_a = docker.named("cashpilot-honeygain-p3")
        _deploy("honeygain")
        assert docker.named("cashpilot-honeygain-p3") is not old_a
        assert docker.named("cashpilot-earnfm-p3") is b and b.status == "running"
        assert len(docker.tunnels()) == 1

    def test_a_start_on_the_same_settings_leaves_the_running_tunnel_alone(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        tunnel = docker.named("cashpilot-tunnel-p3")
        # The box's address is a setting too (the leak guard reads it): recorded first.
        proxy_tunnel.start("honeygain", 3, _socks(), "192.0.2.1")
        starts = tunnel.starts
        proxy_tunnel.start("honeygain", 3, _socks(), "192.0.2.1")
        assert docker.named("cashpilot-tunnel-p3") is tunnel and tunnel.starts == starts

    def test_a_stale_staged_tunnel_is_replaced_but_never_a_stranger(self, docker):
        leftover = docker.create(
            name="cashpilot-tunnel-p3-next",
            image=IMAGE,
            labels={
                LABEL_MANAGED: "true",
                LABEL_ROLE: "tunnel",
                LABEL_SERVICE: proxy_tunnel.SHARED_SLUG,
                LABEL_PROXY: "3",
            },
        )
        _deploy("honeygain")
        assert leftover.id not in docker.by_id
        proxy_tunnel.remove("honeygain", 3)
        stranger = docker.create(name="cashpilot-tunnel-p3-next", image="x", labels={"foo": "bar"})
        with pytest.raises(proxy_tunnel.ProxyTunnelError, match="did not create"):
            _deploy("honeygain")
        assert stranger.id in docker.by_id

    def test_a_young_staged_tunnel_is_left_to_the_deploy_that_owns_it(self, docker):
        young = docker.create(
            name="cashpilot-tunnel-p3-next",
            image=IMAGE,
            labels={
                LABEL_MANAGED: "true",
                LABEL_ROLE: "tunnel",
                LABEL_SERVICE: proxy_tunnel.SHARED_SLUG,
                LABEL_PROXY: "3",
            },
        )
        young.attrs["Created"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        with pytest.raises(proxy_tunnel.ProxyTunnelError, match="may still be running"):
            _deploy("honeygain")
        assert young.id in docker.by_id

    def test_a_stranger_on_the_tunnel_name_is_refused(self, docker):
        docker.create(name="cashpilot-tunnel-p3", image="x", labels={"foo": "bar"})
        with pytest.raises(proxy_tunnel.ProxyTunnelError, match="did not create"):
            _deploy("honeygain")


# ---------------------------------------------------------------------------
# Stop, start, remove: the tunnel serves every copy that should run
# ---------------------------------------------------------------------------


class TestStopStartRemove:
    def test_stopping_one_copy_leaves_the_tunnel_and_the_others_running(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        assert proxy_tunnel.stop("honeygain", 3) == {"was_running": True}
        tunnel = docker.named("cashpilot-tunnel-p3")
        assert tunnel.status == "running"
        assert docker.named("cashpilot-earnfm-p3").status == "running"
        assert docker.named("cashpilot-honeygain-p3").status == "exited"
        assert proxy_tunnel.held() == {"cashpilot-honeygain-p3"}

    def test_stopping_the_last_copy_stops_the_tunnel(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        proxy_tunnel.stop("honeygain", 3)
        proxy_tunnel.stop("earnfm", 3)
        assert docker.named("cashpilot-tunnel-p3").status == "exited"
        assert ("stop", "cashpilot-tunnel-p3") in docker.events

    def test_a_second_stop_says_the_copy_was_not_running(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        assert proxy_tunnel.stop("honeygain", 3) == {"was_running": True}
        assert proxy_tunnel.stop("honeygain", 3) == {"was_running": False}

    def test_a_crashed_copy_beside_a_running_tunnel_counts_as_running_for_the_cap(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        docker.named("cashpilot-honeygain-p3").status = "exited"  # crashed, never stopped by the owner
        assert proxy_tunnel.stop("honeygain", 3) == {"was_running": True}

    def test_the_heartbeat_starts_no_held_copy_and_starts_a_crashed_one(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        _deploy("repocket")
        proxy_tunnel.stop("honeygain", 3)
        docker.named("cashpilot-earnfm-p3").status = "exited"  # a crash
        with patch.object(orchestrator, "_collect_stats_bulk", return_value={}):
            proxy_tunnel.status()
        assert docker.named("cashpilot-honeygain-p3").status == "exited"
        assert docker.named("cashpilot-earnfm-p3").status == "running"

    def test_a_stop_that_cannot_be_recorded_stops_nothing(self, docker, tmp_path):
        _deploy("honeygain")
        with (
            patch.object(proxy_tunnel, "HELD_MARKER", str(tmp_path / "no-such-dir" / "held")),
            pytest.raises(proxy_tunnel.ProxyTunnelError, match="Could not record"),
        ):
            proxy_tunnel.stop("honeygain", 3)
        assert docker.named("cashpilot-honeygain-p3").status == "running"

    def test_a_stop_that_fails_halfway_is_not_undone_by_the_heartbeat(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        earner = docker.named("cashpilot-honeygain-p3")

        def flaky(timeout=None):
            earner.status = "exited"
            raise RuntimeError("daemon timeout")

        earner.stop = flaky
        with pytest.raises(RuntimeError):
            proxy_tunnel.stop("honeygain", 3)
        with patch.object(orchestrator, "_collect_stats_bulk", return_value={}):
            proxy_tunnel.status()
        assert earner.status == "exited"

    def test_start_brings_the_tunnel_back_in_place_and_only_that_copy(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        proxy_tunnel.stop("honeygain", 3)
        proxy_tunnel.stop("earnfm", 3)
        tunnel = docker.named("cashpilot-tunnel-p3")
        proxy_tunnel.start("honeygain", 3, _socks(), None)
        # Same container, so the other copy's NetworkMode still points at it.
        assert docker.named("cashpilot-tunnel-p3") is tunnel and tunnel.status == "running"
        assert docker.named("cashpilot-honeygain-p3").status == "running"
        assert docker.named("cashpilot-earnfm-p3").status == "exited"
        assert proxy_tunnel.held() == {"cashpilot-earnfm-p3"}
        with patch.object(orchestrator, "_collect_stats_bulk", return_value={}):
            proxy_tunnel.status()
        assert docker.named("cashpilot-earnfm-p3").status == "exited"

    def test_start_with_an_edited_proxy_rewrites_a_stopped_tunnel(self, docker):
        _deploy("honeygain")
        proxy_tunnel.stop("honeygain", 3)
        tunnel = docker.named("cashpilot-tunnel-p3")
        proxy_tunnel.start("honeygain", 3, _socks(password=NEW_PASSWORD, port=2080), "192.0.2.1")
        assert docker.named("cashpilot-tunnel-p3") is tunnel
        assert tunnel.files["proxy_auth"] == f"u1:{NEW_PASSWORD}@" and tunnel.files["proxy_port"] == "2080"
        assert set(tunnel.files) == set(proxy_tunnel.SECRET_KEYS)
        assert tunnel.files["auth_key"] == "" and tunnel.files["own_ip"] == "192.0.2.1"

    def test_start_with_an_edited_proxy_while_others_run_keeps_every_container(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        proxy_tunnel.stop("honeygain", 3)
        tunnel = docker.named("cashpilot-tunnel-p3")
        before = {c.id for c in docker.by_id.values()}
        proxy_tunnel.start("honeygain", 3, _socks(password=NEW_PASSWORD), None)
        assert {c.id for c in docker.by_id.values()} == before
        assert tunnel.files["proxy_auth"] == f"u1:{NEW_PASSWORD}@"
        for slug in ("earnfm", "honeygain"):
            earner = docker.named(f"cashpilot-{slug}-p3")
            assert earner.status == "running"
            assert earner.attrs["State"]["StartedAt"] > tunnel.attrs["State"]["StartedAt"]

    def test_start_without_settings_uses_the_tunnel_as_it_is(self, docker):
        _deploy("honeygain")
        proxy_tunnel.stop("honeygain", 3)
        with patch.object(proxy_tunnel, "refresh_proxy_ip") as refresh:
            proxy_tunnel.start("honeygain", 3)
        refresh.assert_called_once()
        assert docker.named("cashpilot-honeygain-p3").status == "running"

    def test_a_tunnel_that_cannot_come_back_is_stopped_and_starts_no_earner(self, docker):
        _deploy("honeygain")
        proxy_tunnel.stop("honeygain", 3)
        docker.broken_auth.add("u1:wrong@")
        with pytest.raises(proxy_tunnel.ProxyTunnelError):
            proxy_tunnel.start("honeygain", 3, _socks(password="wrong"), None)
        assert docker.named("cashpilot-tunnel-p3").status == "exited"
        assert docker.named("cashpilot-honeygain-p3").status == "exited"

    def test_removing_one_copy_keeps_the_tunnel_for_the_others(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        assert proxy_tunnel.remove("honeygain", 3) == ["cashpilot-honeygain-p3"]
        assert docker.named("cashpilot-tunnel-p3").status == "running"
        assert proxy_tunnel.remove("earnfm", 3) == ["cashpilot-earnfm-p3", "cashpilot-tunnel-p3"]
        assert docker.tunnels() == []

    def test_removing_a_stopped_copy_drops_its_stop_record(self, docker):
        _deploy("honeygain")
        proxy_tunnel.stop("honeygain", 3)
        proxy_tunnel.remove("honeygain", 3)
        assert proxy_tunnel.held() == set()

    def test_remove_all_never_removes_a_tunnel_another_service_still_uses(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        assert proxy_tunnel.remove_all("honeygain") == ["cashpilot-honeygain-p3"]
        assert docker.named("cashpilot-tunnel-p3").status == "running"
        assert docker.named("cashpilot-earnfm-p3").status == "running"
        assert proxy_tunnel.remove_all("earnfm") == ["cashpilot-earnfm-p3", "cashpilot-tunnel-p3"]

    def test_copies_of_one_proxy_take_turns(self, docker):
        lock = proxy_tunnel._deploy_lock(3)
        done = threading.Event()
        lock.acquire()
        try:
            with patch.object(proxy_tunnel, "_stop", side_effect=lambda *a: done.set()):
                t = threading.Thread(target=proxy_tunnel.stop, args=("other", 3))
                t.start()
                assert not done.wait(0.2), "a stop of another copy ran while the proxy's lock was held"
                lock.release()
                t.join(2)
            assert done.is_set()
        finally:
            if lock.locked():
                lock.release()


# ---------------------------------------------------------------------------
# Heartbeat, traffic and the cap
# ---------------------------------------------------------------------------


class TestHeartbeat:
    def test_a_reboot_starts_every_copy_that_should_run_only_once_the_tunnel_is_ready(self, docker):
        for slug in ("honeygain", "earnfm", "repocket"):
            _deploy(slug)
        proxy_tunnel.stop("repocket", 3)
        tunnel = docker.named("cashpilot-tunnel-p3")
        # A reboot: everything down, and Docker starts nothing (restart policy
        # "no" on the tunnel too): the heartbeat starts the tunnel, then the copies.
        for c in docker.by_id.values():
            c.status = "exited"
        docker.broken_auth.add(tunnel.files["proxy_auth"])  # not ready yet
        with patch.object(orchestrator, "_collect_stats_bulk", return_value={}):
            proxy_tunnel.status()
            assert tunnel.status == "running"
            assert {docker.named(f"cashpilot-{s}-p3").status for s in ("honeygain", "earnfm")} == {"exited"}
            docker.broken_auth.clear()
            proxy_tunnel.status()
        assert docker.named("cashpilot-honeygain-p3").status == "running"
        assert docker.named("cashpilot-earnfm-p3").status == "running"
        assert docker.named("cashpilot-repocket-p3").status == "exited"

    def test_copies_left_in_an_old_namespace_are_restarted_into_the_new_one(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        tunnel = docker.named("cashpilot-tunnel-p3")
        tunnel.restart()
        with patch.object(orchestrator, "_collect_stats_bulk", return_value={}):
            proxy_tunnel.status()
        for slug in ("honeygain", "earnfm"):
            assert docker.named(f"cashpilot-{slug}-p3").attrs["State"]["StartedAt"] > tunnel.attrs["State"]["StartedAt"]

    def test_status_reports_one_tunnel_for_every_copy_and_the_cap_counts_it_once(self, docker):
        for slug in ("honeygain", "earnfm", "repocket"):
            _deploy(slug)
        tunnel = docker.named("cashpilot-tunnel-p3")
        with patch.object(orchestrator, "_collect_stats_bulk", return_value={tunnel.id: (0.1, 5.0, 1000, 200)}):
            entries = proxy_tunnel.status()
        assert [e["slug"] for e in entries] == ["earnfm", "honeygain", "repocket"]
        assert {e["tunnel_container_id"] for e in entries} == {tunnel.short_id}
        assert all(e["tunnel_shared"] and e["exit_ip"] == EXIT["ip"] for e in entries)
        state, _ = proxies.account({}, {"cap_gb": 10}, 1, entries, 1000.0)
        assert state["used_bytes"] == 1200
        # The next reading counts only what moved since, once.
        with patch.object(orchestrator, "_collect_stats_bulk", return_value={tunnel.id: (0.1, 5.0, 1500, 300)}):
            entries = proxy_tunnel.status()
        state, _ = proxies.account(state, {"cap_gb": 10}, 1, entries, 1060.0)
        assert state["used_bytes"] == 1800

    def test_status_reads_the_ready_file_once_per_tunnel(self, docker):
        for slug in ("honeygain", "earnfm", "repocket"):
            _deploy(slug)
        tunnel = docker.named("cashpilot-tunnel-p3")
        calls = []
        real = tunnel.exec_run
        tunnel.exec_run = lambda *a, **kw: (calls.append(1), real(*a, **kw))[1]
        with patch.object(orchestrator, "_collect_stats_bulk", return_value={}):
            proxy_tunnel.status()
        assert len(calls) == 1

    def test_a_staged_tunnel_that_copies_live_in_is_never_swept(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        tunnel.name = "cashpilot-tunnel-p3-next"  # a swap that failed after moving the copy
        assert proxy_tunnel.sweep_test_tunnels() == []
        assert tunnel.id in docker.by_id
        # The heartbeat finishes that change instead of sweeping it.
        with patch.object(orchestrator, "_collect_stats_bulk", return_value={}):
            proxy_tunnel.status()
        assert tunnel.id in docker.by_id and tunnel.name == "cashpilot-tunnel-p3"


# ---------------------------------------------------------------------------
# Moving the copies of an older worker (one tunnel each) into a shared tunnel
# ---------------------------------------------------------------------------


def _legacy_pair(docker, slug, proxy_id=3, *, proxy=None, running=True):
    proxy = proxy or _tailscale()
    tunnel = docker.create(
        name=proxy_tunnel.tunnel_name(slug, proxy_id),
        image=IMAGE,
        hostname=f"tunnel-{slug}-p{proxy_id}",
        labels={
            LABEL_MANAGED: "true",
            LABEL_ROLE: "tunnel",
            LABEL_SERVICE: slug,
            LABEL_PROXY: str(proxy_id),
            "cashpilot.deployed-by": "worker",
        },
    )
    tunnel.put_archive(
        proxy_tunnel.SECRET_DIR,
        proxy_tunnel._secret_tar(proxy_tunnel.secret_files(proxy, "192.0.2.1", f"{slug}-p{proxy_id}")),
    )
    tunnel.start()
    container_id = _fake_deploy_raw(docker)(
        slug=slug,
        image=f"{slug}/{slug}:1",
        env={"K": slug},
        network_mode=f"container:{tunnel.id}",
        labels={LABEL_PROXY: str(proxy_id)},
        name=proxy_tunnel.earner_name(slug, proxy_id),
    )
    proxy_tunnel._record_container(proxy_tunnel.earner_name(slug, proxy_id), container_id)
    if not running:
        tunnel.stop()
        docker.named(proxy_tunnel.earner_name(slug, proxy_id)).stop()
    return tunnel


class TestMigration:
    def test_legacy_pairs_move_into_one_tunnel_with_the_settings_they_had(self, docker):
        for slug in ("honeygain", "earnfm", "repocket"):
            _legacy_pair(docker, slug)
        moved = proxy_tunnel.migrate_legacy()
        assert sorted(moved) == ["cashpilot-earnfm-p3", "cashpilot-honeygain-p3", "cashpilot-repocket-p3"]
        (tunnel,) = docker.tunnels()
        assert tunnel.name == "cashpilot-tunnel-p3" and tunnel.labels[LABEL_SERVICE] == proxy_tunnel.SHARED_SLUG
        assert tunnel.files["auth_key"] == "tskey-auth-kTEST-0123456789" and tunnel.files["exit_node"] == "exit-box"
        assert tunnel.files["hostname"] == "cashpilot-p3"
        assert _member_ids(docker, tunnel) == sorted(moved)
        assert all(docker.named(n).status == "running" for n in moved)
        # A later start from the UI with the same proxy keeps this tunnel.
        assert tunnel.files["settings"] == proxy_tunnel.secret_files(_tailscale(), None, "p3")["settings"]

    def test_running_it_again_does_nothing(self, docker):
        for slug in ("honeygain", "earnfm"):
            _legacy_pair(docker, slug)
        proxy_tunnel.migrate_legacy()
        before = {c.id for c in docker.by_id.values()}
        assert proxy_tunnel.migrate_legacy() == []
        assert {c.id for c in docker.by_id.values()} == before

    def test_a_stopped_pair_stays_as_it_was_until_its_next_start(self, docker):
        _legacy_pair(docker, "honeygain")
        old = _legacy_pair(docker, "earnfm", running=False)
        earner = docker.named("cashpilot-earnfm-p3")
        proxy_tunnel.migrate_legacy()
        # Not moved and not held: whoever stopped it, nothing is decided for it.
        assert docker.named("cashpilot-tunnel-earnfm-p3") is old and old.status == "exited"
        assert docker.named("cashpilot-earnfm-p3") is earner and earner.status == "exited"
        assert proxy_tunnel.held() == set()
        _heartbeat()
        assert earner.status == "exited" and old.status == "exited"
        # Its next start moves it into the shared tunnel.
        proxy_tunnel.start("earnfm", 3, _tailscale(), None)
        shared = docker.named("cashpilot-tunnel-p3")
        assert docker.named("cashpilot-earnfm-p3").status == "running"
        assert _member_ids(docker, shared) == ["cashpilot-earnfm-p3", "cashpilot-honeygain-p3"]

    def test_a_pair_whose_tunnel_docker_could_not_start_moves_and_runs_again(self, docker):
        _legacy_pair(docker, "honeygain")
        dead = _legacy_pair(docker, "earnfm", running=False)
        # unless-stopped, so down only because Docker could not start it (not an owner stop).
        dead.attrs["State"]["Error"] = "get: no such volume"
        proxy_tunnel.migrate_legacy()
        assert proxy_tunnel.held() == set()
        _heartbeat()
        assert docker.named("cashpilot-earnfm-p3").status == "running"
        (tunnel,) = docker.tunnels()
        assert _member_ids(docker, tunnel) == ["cashpilot-earnfm-p3", "cashpilot-honeygain-p3"]

    def test_a_failed_tunnel_leaves_every_pair_as_it_was(self, docker):
        a = _legacy_pair(docker, "honeygain")
        b = _legacy_pair(docker, "earnfm")
        before = {c.id: c.status for c in docker.by_id.values()}
        with patch.object(proxy_tunnel, "start_sidecar", side_effect=proxy_tunnel.ProxyTunnelError("no exit")):
            assert proxy_tunnel.migrate_legacy() == []
        assert {c.id: c.status for c in docker.by_id.values()} == before
        assert {a.id, b.id} <= set(docker.by_id)

    def test_a_proxy_with_no_running_tunnel_waits_for_its_next_start(self, docker):
        _legacy_pair(docker, "honeygain", running=False)
        assert proxy_tunnel.migrate_legacy() == []
        assert len(docker.tunnels()) == 1
        # Its next start from the UI moves it.
        proxy_tunnel.start("honeygain", 3, _tailscale(), None)
        (tunnel,) = docker.tunnels()
        assert tunnel.name == "cashpilot-tunnel-p3"
        assert docker.named("cashpilot-honeygain-p3").status == "running"
        assert _member_ids(docker, tunnel) == ["cashpilot-honeygain-p3"]

    def test_a_legacy_pair_still_stops_tunnel_first_and_starts_without_settings(self, docker):
        tunnel = _legacy_pair(docker, "honeygain")
        order = []
        earner = docker.named("cashpilot-honeygain-p3")
        real_t, real_e = tunnel.stop, earner.stop
        tunnel.stop = lambda timeout=None: (order.append("tunnel"), real_t())
        earner.stop = lambda timeout=None: (order.append("earner"), real_e())
        proxy_tunnel.stop("honeygain", 3)
        assert order == ["tunnel", "earner"]
        with patch.object(proxy_tunnel, "refresh_proxy_ip"):
            proxy_tunnel.start("honeygain", 3)
        assert tunnel.status == "running" and earner.status == "running"
        assert docker.named("cashpilot-tunnel-p3") is None

    def test_status_reports_legacy_and_shared_copies_side_by_side(self, docker):
        _legacy_pair(docker, "honeygain", proxy_id=4)
        _deploy("earnfm", proxy_id=3)
        with patch.object(orchestrator, "_collect_stats_bulk", return_value={}):
            entries = {e["name"]: e for e in proxy_tunnel.status()}
        assert entries["cashpilot-honeygain-p4"]["tunnel_shared"] is False
        assert entries["cashpilot-earnfm-p3"]["tunnel_shared"] is True
        assert entries["cashpilot-honeygain-p4"]["exit_ip"] == EXIT["ip"]


class TestHeldMarker:
    def test_marker_round_trip(self, tmp_path):
        with patch.object(proxy_tunnel, "HELD_MARKER", str(tmp_path / "held")):
            proxy_tunnel._set_held("a", True, strict=True)
            proxy_tunnel._set_held("b", True, strict=True)
            proxy_tunnel._set_held("a", False)
            assert proxy_tunnel.held() == {"b"}
            assert (tmp_path / "held").read_text() == "b\n"


# ---------------------------------------------------------------------------
# A daemon restart, and moves that fail or that a worker dies in
# ---------------------------------------------------------------------------


def _heartbeat():
    with patch.object(orchestrator, "_collect_stats_bulk", return_value={}):
        return proxy_tunnel.status()


def _break_tunnel(docker, tunnel):
    """A daemon restart that left the tunnel unable to start (the Binds form)."""
    for c in docker.by_id.values():
        c.status = "exited"
    docker.broken.add(tunnel.id)
    docker.unreadable.add(tunnel.id)


@pytest.fixture
def detection_off(monkeypatch):
    """A worker that never knows its own address (CASHPILOT_EGRESS_DETECT=off): only then does a broken tunnel,
    whose recorded address Docker cannot read either, get replaced with none to compare (_carry_own_ip)."""
    monkeypatch.setenv("CASHPILOT_EGRESS_DETECT", "off")


@pytest.mark.usefixtures("detection_off")
class TestBrokenTunnel:
    def test_the_secret_volume_is_a_mount_not_a_bind_with_no_source(self, docker):
        kw = proxy_tunnel.sidecar_kwargs("cashpilot-tunnel-p3", proxy_tunnel.SHARED_SLUG, 3, None, "tunnel-p3")
        assert "volumes" not in kw
        (mount,) = kw["mounts"]
        assert mount["Type"] == "volume" and mount["Target"] == proxy_tunnel.SECRET_DIR
        assert mount.get("Source") in (None, "")

    def test_a_start_replaces_a_tunnel_docker_cannot_start_and_keeps_held_copies_stopped(self, docker):
        for slug in ("honeygain", "earnfm", "repocket"):
            _deploy(slug)
        proxy_tunnel.stop("repocket", 3)
        old = docker.named("cashpilot-tunnel-p3")
        _break_tunnel(docker, old)
        proxy_tunnel.start("honeygain", 3, _socks(), None)
        (tunnel,) = docker.tunnels()
        assert tunnel.id != old.id and tunnel.name == "cashpilot-tunnel-p3" and tunnel.status == "running"
        assert _member_ids(docker, tunnel) == ["cashpilot-earnfm-p3", "cashpilot-honeygain-p3", "cashpilot-repocket-p3"]
        moved = docker.named("cashpilot-honeygain-p3")
        assert moved.status == "running"
        # Recreated from what Docker recorded, hardening included.
        assert moved.kw["image"] == "honeygain/honeygain:1"
        assert moved.kw["environment"] == ["K=honeygain", "NVIDIA_VISIBLE_DEVICES=void"]
        assert moved.kw["cap_drop"] == ["ALL"] and moved.kw["privileged"] is False
        assert moved.kw["restart_policy"] == {"Name": "no"} and moved.labels[LABEL_PROXY] == "3"
        _heartbeat()
        assert docker.named("cashpilot-earnfm-p3").status == "running"
        assert docker.named("cashpilot-repocket-p3").status != "running"
        assert proxy_tunnel.held() == {"cashpilot-repocket-p3"}

    def test_a_redeploy_replaces_a_tunnel_docker_cannot_start(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        old = docker.named("cashpilot-tunnel-p3")
        _break_tunnel(docker, old)
        _deploy("earnfm")
        (tunnel,) = docker.tunnels()
        assert tunnel.id != old.id
        assert _member_ids(docker, tunnel) == ["cashpilot-earnfm-p3", "cashpilot-honeygain-p3"]


def _three_copies_on_a_broken_tunnel(docker):
    for slug in ("m1", "m2", "m3"):
        _deploy(slug)
    old = docker.named("cashpilot-tunnel-p3")
    old.stop()
    docker.broken.add(old.id)
    docker.unreadable.add(old.id)
    return old


def _rename_fails_for(name, exc):
    real = FakeContainer.rename

    def rename(self, new):
        if new == name and self.name.endswith("-next"):
            raise exc
        return real(self, new)

    return patch.object(FakeContainer, "rename", rename)


@pytest.mark.usefixtures("detection_off")
class TestMoves:
    def test_a_worker_that_dies_mid_move_loses_no_copy(self, docker):
        _three_copies_on_a_broken_tunnel(docker)
        with _rename_fails_for("cashpilot-m3-p3", SystemExit("worker killed")), pytest.raises(SystemExit):
            proxy_tunnel.start("m1", 3, _socks(), None)
        names = {c.name for c in docker.by_id.values()}
        # Nothing of m3 was removed: its container is aside, its clone staged.
        assert {"cashpilot-m3-p3-moving", "cashpilot-m3-p3-next"} <= names
        # The next heartbeat (the change is past its timeout) puts it all together.
        _heartbeat()
        (tunnel,) = docker.tunnels()
        assert tunnel.name == "cashpilot-tunnel-p3"
        assert _member_ids(docker, tunnel) == ["cashpilot-m1-p3", "cashpilot-m2-p3", "cashpilot-m3-p3"]
        assert not [c.name for c in docker.by_id.values() if c.name.endswith(("-next", "-moving"))]
        _heartbeat()
        assert {docker.named(f"cashpilot-{s}-p3").status for s in ("m1", "m2", "m3")} == {"running"}

    def test_a_young_half_move_holds_the_staged_tunnel_until_it_is_settled(self, docker):
        # Right after a worker restart the clone is young: recover_moves leaves
        # it, and the staged tunnel must wait too, or the copy's container aside
        # would be cloned as if it were a copy of its own.
        _three_copies_on_a_broken_tunnel(docker)
        with _rename_fails_for("cashpilot-m3-p3", SystemExit("worker killed")), pytest.raises(SystemExit):
            proxy_tunnel.start("m1", 3, _socks(), None)
        clone = docker.named("cashpilot-m3-p3-next")
        clone.attrs["Created"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        before = sorted(c.name for c in docker.by_id.values())
        _heartbeat()
        assert sorted(c.name for c in docker.by_id.values()) == before
        with pytest.raises(proxy_tunnel.ProxyTunnelError, match="still being moved"):
            proxy_tunnel.start("m1", 3, _socks(), None)
        clone.attrs["Created"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        _heartbeat()
        (tunnel,) = docker.tunnels()
        assert tunnel.name == "cashpilot-tunnel-p3"
        assert _member_ids(docker, tunnel) == ["cashpilot-m1-p3", "cashpilot-m2-p3", "cashpilot-m3-p3"]

    def test_recover_moves_reads_the_stale_age_when_it_runs(self, docker):
        _deploy("a")
        a = docker.named("cashpilot-a-p3")
        a.rename("cashpilot-a-p3-moving")
        clone = docker.create(name="cashpilot-a-p3-next", image="a/a:1", labels=dict(a.labels))
        clone.attrs["Created"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        proxy_tunnel._record_pair(proxy_tunnel.MOVE_MARKER, "cashpilot-a-p3", a.id, clone.id)
        with patch.object(proxy_tunnel, "STAGED_STALE_SECONDS", 0):
            assert proxy_tunnel.recover_moves() == ["restored cashpilot-a-p3"]

    def test_a_failed_move_puts_the_copy_back_and_leaves_nothing_in_the_way(self, docker):
        old = _three_copies_on_a_broken_tunnel(docker)
        with _rename_fails_for("cashpilot-m3-p3", RuntimeError("daemon timeout")), pytest.raises(RuntimeError):
            proxy_tunnel.start("m1", 3, _socks(), None)
        # Every copy back in the old tunnel under its own name; the staged one gone.
        assert docker.tunnels() == [old]
        assert _member_ids(docker, old) == ["cashpilot-m1-p3", "cashpilot-m2-p3", "cashpilot-m3-p3"]
        # And the next start is not blocked by a half-done change.
        proxy_tunnel.start("m1", 3, _socks(), None)
        (tunnel,) = docker.tunnels()
        assert _member_ids(docker, tunnel) == ["cashpilot-m1-p3", "cashpilot-m2-p3", "cashpilot-m3-p3"]

    def test_recover_moves_settles_each_half_done_state(self, docker):
        _deploy("a")
        _deploy("b")
        _deploy("c")
        tunnel = docker.named("cashpilot-tunnel-p3")
        # a: the clone holds the name, the original is still aside.
        a = docker.named("cashpilot-a-p3")
        twin = docker.create(
            name="cashpilot-a-p3-moving", image="a/a:1", labels=dict(a.labels), network_mode=f"container:{tunnel.id}"
        )
        # b: aside, with a half-made clone and the name free.
        b = docker.named("cashpilot-b-p3")
        b.rename("cashpilot-b-p3-moving")
        b_clone = docker.create(
            name="cashpilot-b-p3-next", image="b/b:1", labels=dict(b.labels), network_mode=f"container:{tunnel.id}"
        )
        # c: only a clone, the name free.
        c = docker.named("cashpilot-c-p3")
        c.rename("cashpilot-c-p3-next")
        proxy_tunnel._record_pair(proxy_tunnel.MOVE_MARKER, "cashpilot-a-p3", twin.id, a.id)
        proxy_tunnel._record_pair(proxy_tunnel.MOVE_MARKER, "cashpilot-b-p3", b.id, b_clone.id)
        proxy_tunnel._record_pair(proxy_tunnel.MOVE_MARKER, "cashpilot-c-p3", "gone", c.id)
        assert sorted(proxy_tunnel.recover_moves()) == [
            "finished cashpilot-c-p3",
            "removed cashpilot-a-p3-moving",
            "restored cashpilot-b-p3",
        ]
        assert twin.id not in docker.by_id
        assert docker.named("cashpilot-b-p3") is b and docker.named("cashpilot-c-p3") is c
        assert not [x.name for x in docker.by_id.values() if x.name.endswith(("-next", "-moving"))]

    def test_a_young_clone_belongs_to_a_move_still_running(self, docker):
        _deploy("a")
        a = docker.named("cashpilot-a-p3")
        a.rename("cashpilot-a-p3-moving")
        clone = docker.create(name="cashpilot-a-p3-next", image="a/a:1", labels=dict(a.labels))
        clone.attrs["Created"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        assert proxy_tunnel.recover_moves() == []
        assert clone.id in docker.by_id and a.name == "cashpilot-a-p3-moving"

    def test_the_heartbeat_never_sweeps_a_staged_tunnel_only_a_staged_copy_lives_in(self, docker):
        _deploy("m1")
        tunnel = docker.named("cashpilot-tunnel-p3")
        staged = docker.create(
            name="cashpilot-tunnel-p3-next",
            image=IMAGE,
            labels={
                LABEL_MANAGED: "true",
                LABEL_ROLE: "tunnel",
                LABEL_SERVICE: proxy_tunnel.SHARED_SLUG,
                LABEL_PROXY: "3",
            },
        )
        staged.start()
        m2 = docker.create(
            name="cashpilot-m2-p3-next",
            image="m2/m2:1",
            labels={LABEL_MANAGED: "true", LABEL_SERVICE: "m2", LABEL_PROXY: "3"},
            network_mode=f"container:{staged.id}",
        )
        proxy_tunnel._record_pair(proxy_tunnel.MOVE_MARKER, "cashpilot-m2-p3", "gone", m2.id)
        _heartbeat()
        assert m2.id in docker.by_id and m2.name == "cashpilot-m2-p3"
        # The change was finished instead: every copy in one tunnel, under its name.
        (only,) = docker.tunnels()
        assert only is staged and staged.name == "cashpilot-tunnel-p3" and tunnel.id not in docker.by_id
        assert _member_ids(docker, staged) == ["cashpilot-m1-p3", "cashpilot-m2-p3"]


# ---------------------------------------------------------------------------
# Stops, starts and removals against the heartbeat (review fixes)
# ---------------------------------------------------------------------------


class TestStopsAgainstTheHeartbeat:
    def test_an_unreadable_stop_marker_starts_no_copy(self, docker, tmp_path):
        _deploy("honeygain")
        _deploy("earnfm")
        proxy_tunnel.stop("honeygain", 3)
        unreadable = tmp_path / "marker-is-a-dir"
        unreadable.mkdir()
        with patch.object(proxy_tunnel, "HELD_MARKER", str(unreadable)):
            _heartbeat()
        assert docker.named("cashpilot-honeygain-p3").status == "exited"

    def test_a_stop_with_an_unreadable_marker_stops_nothing(self, docker, tmp_path):
        _deploy("honeygain")
        unreadable = tmp_path / "marker-is-a-dir"
        unreadable.mkdir()
        with (
            patch.object(proxy_tunnel, "HELD_MARKER", str(unreadable)),
            pytest.raises(proxy_tunnel.ProxyTunnelError, match="Could not read which copies are stopped"),
        ):
            proxy_tunnel.stop("honeygain", 3)
        assert docker.named("cashpilot-honeygain-p3").status == "running"

    def test_a_start_that_cannot_clear_its_stop_starts_nothing(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        proxy_tunnel.stop("honeygain", 3)
        with (
            patch.object(proxy_tunnel.os, "replace", side_effect=OSError("read-only file system")),
            pytest.raises(proxy_tunnel.ProxyTunnelError, match="is no longer stopped"),
        ):
            proxy_tunnel.start("honeygain", 3, _socks(), None)
        assert docker.named("cashpilot-honeygain-p3").status == "exited"
        assert proxy_tunnel.held() == {"cashpilot-honeygain-p3"}

    def test_a_deploy_that_cannot_clear_its_stop_changes_nothing(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        proxy_tunnel.stop("honeygain", 3)
        old = docker.named("cashpilot-honeygain-p3")
        with (
            patch.object(proxy_tunnel.os, "replace", side_effect=OSError("read-only file system")),
            pytest.raises(proxy_tunnel.ProxyTunnelError, match="was stopped .*left as it was"),
        ):
            _deploy("honeygain")
        assert docker.named("cashpilot-honeygain-p3") is old and old.status == "exited"
        assert proxy_tunnel.held() == {"cashpilot-honeygain-p3"}

    def test_the_heartbeat_leaves_a_copy_alone_while_its_proxy_is_locked(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        docker.named("cashpilot-earnfm-p3").status = "exited"  # a crash
        lock = proxy_tunnel._deploy_lock(3)
        with lock:
            _heartbeat()
        assert docker.named("cashpilot-earnfm-p3").status == "exited"
        _heartbeat()
        assert docker.named("cashpilot-earnfm-p3").status == "running"

    def test_a_stop_made_while_the_heartbeat_decides_is_not_undone(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        docker.named("cashpilot-earnfm-p3").status = "exited"  # a crash, then the owner stops it
        real = proxy_tunnel.earner_action
        stopped: list[bool] = []

        def decide_then_stop(earner, sidecar, ready):
            action = real(earner, sidecar, ready)
            if earner.name == "cashpilot-earnfm-p3" and not stopped:
                stopped.append(proxy_tunnel.stop("earnfm", 3)["was_running"])
            return action

        with patch.object(proxy_tunnel, "earner_action", side_effect=decide_then_stop):
            _heartbeat()
        assert stopped == [True]
        assert docker.named("cashpilot-earnfm-p3").status == "exited"


class TestStartAndRemoveReconcile:
    def test_a_start_recreates_a_copy_whose_tunnel_is_gone_inside_the_shared_tunnel(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        proxy_tunnel.stop("honeygain", 3)
        old = docker.named("cashpilot-honeygain-p3")
        old.attrs["HostConfig"]["NetworkMode"] = f"container:{'f' * 64}"  # a tunnel that no longer exists
        proxy_tunnel.start("honeygain", 3, _socks(), None)
        tunnel = docker.named("cashpilot-tunnel-p3")
        copy = docker.named("cashpilot-honeygain-p3")
        assert copy.id != old.id and old.id not in docker.by_id
        assert copy.status == "running"
        assert _member_ids(docker, tunnel) == ["cashpilot-earnfm-p3", "cashpilot-honeygain-p3"]

    def test_remove_all_waits_for_the_proxys_lock(self, docker):
        _deploy("honeygain")
        lock = proxy_tunnel._deploy_lock(3)
        result: list[list[str]] = []
        with lock:
            worker = threading.Thread(target=lambda: result.append(proxy_tunnel.remove_all("honeygain")))
            worker.start()
            worker.join(0.3)
            # A move or a migration of this proxy holds the lock: nothing is removed under it.
            assert docker.named("cashpilot-honeygain-p3") is not None
        worker.join(5)
        assert result == [["cashpilot-honeygain-p3", "cashpilot-tunnel-p3"]]


class TestEditsAndMovesSecondReview:
    def test_a_moved_copy_gets_no_nvidia_devices(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        old = docker.named("cashpilot-honeygain-p3")
        old.attrs["Config"]["Env"] = ["K=value", "NVIDIA_VISIBLE_DEVICES=all"]
        clone = proxy_tunnel._clone_into(docker, old, tunnel)
        assert clone.attrs["Config"]["Env"] == ["K=value", "NVIDIA_VISIBLE_DEVICES=void"]

    def test_a_copy_with_device_requests_is_not_moved(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        old = docker.named("cashpilot-honeygain-p3")
        old.attrs["HostConfig"]["DeviceRequests"] = [{"Driver": "nvidia", "Capabilities": [["gpu"]]}]
        with pytest.raises(proxy_tunnel.ProxyTunnelError, match="device requests"):
            proxy_tunnel._clone_into(docker, old, tunnel)
        assert docker.named(old.name) is old and old.status == "running"

    def test_a_copy_that_does_not_stop_is_not_moved(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        member = docker.named("cashpilot-honeygain-p3")
        member.stop = lambda timeout=None: None  # Docker answers, but it keeps running
        with pytest.raises(proxy_tunnel.ProxyTunnelError, match="did not stop"):
            proxy_tunnel._clone_into(docker, member, tunnel)
        assert docker.named("cashpilot-honeygain-p3") is member and member.status == "running"
        assert not [c.name for c in docker.by_id.values() if c.name.endswith(("-next", "-moving"))]

    def test_an_edit_whose_old_settings_cannot_be_read_changes_nothing(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        real = tunnel.get_archive

        def flaky(path):
            if path.endswith("/proxy_port"):
                raise APIError("500 Server Error: daemon busy")
            return real(path)

        tunnel.get_archive = flaky
        with (
            patch.object(proxy_tunnel, "_prove"),
            pytest.raises(proxy_tunnel.ProxyTunnelError, match="Could not read the tunnel's current settings"),
        ):
            _deploy("earnfm", _socks(password=NEW_PASSWORD))
        assert tunnel.status == "running" and ("stop", "cashpilot-tunnel-p3") not in docker.events
        assert tunnel.files["proxy_auth"] == proxy_tunnel.proxy_auth("u1", PASSWORD)

    def test_a_rolled_back_edit_restarts_the_copies_inside_the_tunnel(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        earner = docker.named("cashpilot-honeygain-p3")
        docker.broken_auth.add(f"u1:{NEW_PASSWORD}@")
        with patch.object(proxy_tunnel, "_prove"), pytest.raises(proxy_tunnel.ProxyTunnelError):
            _deploy("earnfm", _socks(password=NEW_PASSWORD))
        # Back on the old settings, and the copy restarted into the tunnel's new namespace.
        assert earner.status == "running"
        assert earner.attrs["State"]["StartedAt"] > tunnel.attrs["State"]["StartedAt"]

    def test_a_failed_edit_keeps_the_old_password_out_of_the_tunnel_log(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        tunnel.logs = lambda tail=5: f"tun2proxy: auth u1 {PASSWORD} refused".encode()
        docker.broken_auth.add(f"u1:{NEW_PASSWORD}@")
        with patch.object(proxy_tunnel, "_prove"), pytest.raises(proxy_tunnel.ProxyTunnelError) as err:
            _deploy("earnfm", _socks(password=NEW_PASSWORD))
        assert PASSWORD not in str(err.value) and "Tunnel log" in str(err.value)

    def test_a_redeploy_counts_the_copies_of_a_staged_tunnel_before_taking_a_new_image(self, docker):
        _deploy("m1")
        staged = docker.create(
            name="cashpilot-tunnel-p3-next",
            image=IMAGE,
            labels={
                LABEL_MANAGED: "true",
                LABEL_ROLE: "tunnel",
                LABEL_SERVICE: proxy_tunnel.SHARED_SLUG,
                LABEL_PROXY: "3",
            },
        )
        staged.files = dict(docker.named("cashpilot-tunnel-p3").files)
        staged.start()
        m2 = docker.create(
            name="cashpilot-m2-p3",
            image="m2/m2:1",
            labels={LABEL_MANAGED: "true", LABEL_SERVICE: "m2", LABEL_PROXY: "3"},
            network_mode=f"container:{staged.id}",
        )
        m2.start()
        with patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": NEW_IMAGE}):
            _deploy("m1")
        # The staged change was finished, and m2 (another copy) kept its container.
        assert docker.named("cashpilot-m2-p3") is m2
        (tunnel,) = docker.tunnels()
        assert tunnel is staged and tunnel.kw["image"] == IMAGE

    def test_recovery_keeps_the_aside_copy_while_the_clone_holding_the_name_is_young(self, docker):
        _deploy("a")
        a = docker.named("cashpilot-a-p3")
        tunnel = docker.named("cashpilot-tunnel-p3")
        aside = docker.create(
            name="cashpilot-a-p3-moving", image="a/a:1", labels=dict(a.labels), network_mode=f"container:{tunnel.id}"
        )
        a.attrs["Created"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")  # a clone that took the name now
        assert proxy_tunnel.recover_moves() == []
        assert aside.id in docker.by_id


class TestThirdReview:
    def test_a_migrated_password_is_redacted_in_its_decoded_form(self, docker):
        files = proxy_tunnel.secret_files(_socks(), None, "p3")
        with (
            patch.object(proxy_tunnel, "_wait_ready", side_effect=RuntimeError(f"auth u1 {PASSWORD} refused")),
            pytest.raises(proxy_tunnel.ProxyTunnelError) as err,
        ):
            proxy_tunnel.start_sidecar(
                docker, "cashpilot-tunnel-p3", proxy_tunnel.SHARED_SLUG, 3, None, None, files=files
            )
        assert PASSWORD not in str(err.value) and "refused" in str(err.value)

    def test_docker_refusing_an_edit_once_does_not_replace_the_tunnel(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        earner = docker.named("cashpilot-honeygain-p3")
        real, calls = tunnel.put_archive, []

        def once(path, blob):
            calls.append(path)
            if len(calls) == 1:
                raise APIError("500 Server Error: daemon busy")
            return real(path, blob)

        tunnel.put_archive = once
        _deploy("earnfm", _socks(password=NEW_PASSWORD))
        assert docker.tunnels() == [tunnel] and tunnel.status == "running"
        assert tunnel.files["proxy_auth"] == f"u1:{NEW_PASSWORD}@"
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "running"

    def test_a_copy_whose_start_fails_leaves_no_created_earner(self, docker):
        _deploy("honeygain")

        def created_then_failed(*, name, network_mode, labels, slug, **_kw):
            created = docker.create(
                name=name,
                image="x",
                network_mode=network_mode,
                labels={**labels, LABEL_SERVICE: slug, LABEL_MANAGED: "true"},
            )
            _kw["on_created"](created.id)
            raise APIError("500 Server Error: start failed")

        with patch.object(orchestrator, "deploy_raw", side_effect=created_then_failed), pytest.raises(APIError):
            _deploy("earnfm")
        assert docker.named("cashpilot-earnfm-p3") is None
        _heartbeat()
        assert docker.named("cashpilot-earnfm-p3") is None

    def test_a_settings_read_error_leaves_the_legacy_pairs_as_they_were(self, docker):
        _legacy_pair(docker, "honeygain")
        before = {c.id: c.status for c in docker.by_id.values()}
        real = proxy_tunnel._read_secret_file_or_raise

        def flaky(container, key):
            if key == "exit_node":
                raise proxy_tunnel.ProxyTunnelError("Could not read the tunnel's current settings")
            return real(container, key)

        with patch.object(proxy_tunnel, "_read_secret_file_or_raise", side_effect=flaky):
            assert proxy_tunnel.migrate_legacy() == []
        assert {c.id: c.status for c in docker.by_id.values()} == before
        assert docker.named("cashpilot-tunnel-p3") is None

    def test_the_migration_reads_the_tunnel_again_under_the_lock(self, docker):
        old = _legacy_pair(docker, "honeygain")
        earner = docker.named("cashpilot-honeygain-p3")

        def stopped_since_the_listing():
            old.status = earner.status = "exited"  # the owner stopped it meanwhile

        old.reload = stopped_since_the_listing
        proxy_tunnel.migrate_legacy()
        assert docker.named("cashpilot-tunnel-honeygain-p3") is old
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "exited"

    def test_an_empty_shared_tunnel_left_behind_is_removed_by_the_heartbeat(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        docker.named("cashpilot-honeygain-p3").remove(force=True)
        _heartbeat()
        assert docker.named("cashpilot-tunnel-p3") is None and tunnel.id not in docker.by_id

    def test_a_young_empty_shared_tunnel_is_left_for_the_deploy_filling_it(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        tunnel.attrs["Created"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        docker.named("cashpilot-honeygain-p3").remove(force=True)
        _heartbeat()
        assert docker.named("cashpilot-tunnel-p3") is tunnel

    def test_a_start_that_cannot_clear_the_stop_leaves_the_tunnel_down(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        proxy_tunnel.stop("honeygain", 3)
        assert tunnel.status == "exited"
        real = proxy_tunnel._set_held

        def read_only(name, on, *, strict=False):
            if not on:
                raise proxy_tunnel.ProxyTunnelError("Could not record the stop")
            return real(name, on, strict=strict)

        with (
            patch.object(proxy_tunnel, "_set_held", side_effect=read_only),
            pytest.raises(proxy_tunnel.ProxyTunnelError),
        ):
            proxy_tunnel.start("honeygain", 3, _socks(), None)
        assert tunnel.status == "exited" and docker.named("cashpilot-honeygain-p3").status == "exited"

    def test_a_start_that_cannot_clear_the_stop_keeps_a_tunnel_another_copy_runs_in(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        tunnel = docker.named("cashpilot-tunnel-p3")
        proxy_tunnel.stop("honeygain", 3)
        real = proxy_tunnel._set_held

        def read_only(name, on, *, strict=False):
            if not on:
                raise proxy_tunnel.ProxyTunnelError("Could not record the stop")
            return real(name, on, strict=strict)

        with (
            patch.object(proxy_tunnel, "_set_held", side_effect=read_only),
            pytest.raises(proxy_tunnel.ProxyTunnelError),
        ):
            proxy_tunnel.start("honeygain", 3, _socks(), None)
        assert tunnel.status == "running" and docker.named("cashpilot-earnfm-p3").status == "running"

    def test_a_migrated_edit_keeps_the_decoded_password_out_of_the_tunnel_log(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        tunnel.logs = lambda tail=5: f"tun2proxy: auth u1 {NEW_PASSWORD} refused".encode()
        docker.broken_auth.add(f"u1:{NEW_PASSWORD}@")
        # Settings read from a legacy tunnel: no proxy dict, the password only inside proxy_auth.
        files = proxy_tunnel.secret_files(_socks(password=NEW_PASSWORD), None, "p3")
        with patch.object(proxy_tunnel, "_prove"), pytest.raises(proxy_tunnel.ProxyTunnelError) as err:
            proxy_tunnel._ensure_tunnel(docker, 3, None, None, files=files)
        assert NEW_PASSWORD not in str(err.value) and "Tunnel log" in str(err.value)


class TestFourthReview:
    def test_a_folder_that_cannot_be_flushed_is_reported_by_the_start_and_a_retry_flushes_it(self, docker):
        """The marker's rename is on disk only once its folder is flushed: a start acknowledged before that could
        come back stopped after a power cut, so the start says so (the copy runs: the marker already says it should).
        And a retry that finds the marker already saying so flushes it."""
        _deploy("honeygain")
        proxy_tunnel.stop("honeygain", 3)
        real = os.fsync
        folders = []

        def fsync(fd, fail):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                folders.append(fd)
                if fail:
                    raise OSError("EIO")
            return real(fd)

        with patch.object(proxy_tunnel.os, "fsync", side_effect=lambda fd: fsync(fd, True)):
            answer = proxy_tunnel.start("honeygain", 3, _socks(), None)
        assert answer["durable"] is False and re.search("was started, but .*Could not record", answer["warning"])
        assert docker.named(NAME).status == "running"
        folders.clear()
        with patch.object(proxy_tunnel.os, "fsync", side_effect=lambda fd: fsync(fd, False)):
            proxy_tunnel.start("honeygain", 3, _socks(), None)
        assert folders, "the retry found the marker already saying so and never flushed its folder"
        assert proxy_tunnel.held() == set() and docker.named(NAME).status == "running"

    def test_an_edit_whose_tunnel_does_not_stop_changes_nothing(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        tunnel.stop = lambda timeout=None: None  # Docker answers, but it keeps running
        with patch.object(proxy_tunnel, "_prove"), pytest.raises(proxy_tunnel.ProxyTunnelError, match="did not stop"):
            _deploy("earnfm", _socks(password=NEW_PASSWORD))
        assert tunnel.status == "running"
        assert tunnel.files["proxy_auth"] == proxy_tunnel.proxy_auth("u1", PASSWORD)
        assert tunnel.files["settings"] == proxy_tunnel.secret_files(_socks(), None, "p3")["settings"]

    def test_an_edit_redacts_settings_only_the_second_read_found(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        tunnel.logs = lambda tail=5: f"tun2proxy: auth u1 {PASSWORD} refused".encode()
        real, seen = tunnel.get_archive, []

        def first_read_fails(path):
            seen.append(path)
            if path.endswith("/proxy_auth") and seen.count(path) == 1:
                raise NotFound(path)
            return real(path)

        tunnel.get_archive = first_read_fails
        docker.broken_auth.add(f"u1:{NEW_PASSWORD}@")
        docker.broken_auth.add(proxy_tunnel.proxy_auth("u1", PASSWORD))  # the rollback fails too
        with patch.object(proxy_tunnel, "_prove"), pytest.raises(proxy_tunnel.ProxyTunnelError) as err:
            _deploy("earnfm", _socks(password=NEW_PASSWORD))
        assert PASSWORD not in str(err.value)

    def test_a_stop_whose_earner_does_not_stop_still_stops_the_tunnel(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        earner = docker.named("cashpilot-honeygain-p3")

        def refuses(timeout=None):
            raise APIError("500 Server Error: cannot stop")

        earner.stop = refuses
        with pytest.raises(APIError):
            proxy_tunnel.stop("honeygain", 3)
        assert tunnel.status == "exited"
        assert proxy_tunnel.held() == {"cashpilot-honeygain-p3"}

    def test_a_stop_whose_earner_does_not_stop_keeps_a_tunnel_another_copy_runs_in(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        tunnel = docker.named("cashpilot-tunnel-p3")

        def refuses(timeout=None):
            raise APIError("500 Server Error: cannot stop")

        docker.named("cashpilot-honeygain-p3").stop = refuses
        with pytest.raises(APIError):
            proxy_tunnel.stop("honeygain", 3)
        assert tunnel.status == "running" and docker.named("cashpilot-earnfm-p3").status == "running"

    def test_an_edit_of_a_stopped_tunnel_keeps_the_old_password_out_of_its_log(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        proxy_tunnel.stop("honeygain", 3)
        assert tunnel.status == "exited"
        tunnel.logs = lambda tail=5: f"tun2proxy: auth u1 {PASSWORD} refused".encode()
        docker.broken_auth.add(f"u1:{NEW_PASSWORD}@")
        with pytest.raises(proxy_tunnel.ProxyTunnelError) as err:
            proxy_tunnel.start("honeygain", 3, _socks(password=NEW_PASSWORD), None)
        assert PASSWORD not in str(err.value) and "Tunnel log" in str(err.value)


class TestFifthReview:
    def test_a_moved_copy_keeps_the_volumes_its_image_declares(self, docker):
        _legacy_pair(docker, "honeygain")
        earner = docker.named("cashpilot-honeygain-p3")
        earner.attrs["Mounts"] = [{"Type": "volume", "Name": "hg-id", "Destination": "/root/.hg", "RW": True}]
        proxy_tunnel.migrate_legacy()
        clone = docker.named("cashpilot-honeygain-p3")
        assert clone is not earner and clone.kw["volumes"] == {"hg-id": {"bind": "/root/.hg", "mode": "rw"}}
        assert ("cashpilot-honeygain-p3-moving", False) in docker.removals

    def _staged(self, docker, files):
        staged = docker.create(
            name="cashpilot-tunnel-p3-next",
            image=IMAGE,
            labels={
                LABEL_MANAGED: "true",
                LABEL_ROLE: "tunnel",
                LABEL_SERVICE: proxy_tunnel.SHARED_SLUG,
                LABEL_PROXY: "3",
            },
        )
        staged.files = dict(files)
        return staged

    def test_copies_never_move_into_a_staged_tunnel_that_cannot_run(self, docker):
        _deploy("m1")
        current = docker.named("cashpilot-tunnel-p3")
        staged = self._staged(docker, {**current.files, "proxy_auth": "u1:dead@"})
        docker.broken_auth.add("u1:dead@")
        assert proxy_tunnel._finish_staged(docker, staged, current, "cashpilot-tunnel-p3") is current
        assert docker.named("cashpilot-tunnel-p3") is current and current.status == "running"
        assert staged.id not in docker.by_id
        assert _member_ids(docker, current) == ["cashpilot-m1-p3"]
        assert docker.named("cashpilot-m1-p3").status == "running"

    def test_a_stopped_staged_tunnel_is_started_before_running_copies_move_in(self, docker):
        _deploy("m1")
        current = docker.named("cashpilot-tunnel-p3")
        staged = self._staged(docker, current.files)
        proxy_tunnel._finish_staged(docker, staged, current, "cashpilot-tunnel-p3")
        assert docker.named("cashpilot-tunnel-p3") is staged and staged.status == "running"
        assert docker.named("cashpilot-m1-p3").status == "running"

    def test_a_start_whose_move_fails_leaves_no_tunnel_running_for_nobody(self, docker):
        _legacy_pair(docker, "honeygain", running=False)
        with (
            patch.object(proxy_tunnel, "_clone_into", side_effect=APIError("500 Server Error: create failed")),
            pytest.raises(APIError),
        ):
            proxy_tunnel.start("honeygain", 3, _tailscale(), None)
        shared = docker.named("cashpilot-tunnel-p3")
        assert shared is None or shared.status != "running"


# ---------------------------------------------------------------------------
# A rebuild the UI makes on its own (a device rename) never starts a stopped copy
# ---------------------------------------------------------------------------


def _rebuild(slug, proxy_id=3):
    earner = {"image": f"{slug}/{slug}:1", "env": {"K": f"{slug}-new"}}
    return proxy_tunnel.deploy(slug, proxy_id, earner, _socks(), None, only_if_running=True)


class TestOnlyIfRunning:
    def test_a_running_copy_is_replaced(self, docker):
        _deploy("honeygain")
        old = docker.named("cashpilot-honeygain-p3")
        _rebuild("honeygain")
        new = docker.named("cashpilot-honeygain-p3")
        assert new is not old and new.status == "running"
        assert "K=honeygain-new" in new.attrs["Config"]["Env"]

    def test_a_copy_the_owner_stopped_first_stays_stopped(self, docker):
        _deploy("honeygain")
        proxy_tunnel.stop("honeygain", 3)
        copy = docker.named("cashpilot-honeygain-p3")
        with pytest.raises(proxy_tunnel.ProxyTunnelError) as err:
            _rebuild("honeygain")
        assert err.value.status_code == 409
        assert docker.named("cashpilot-honeygain-p3") is copy and copy.status == "exited"
        assert "cashpilot-honeygain-p3" in proxy_tunnel.held()

    def test_a_copy_that_exited_on_its_own_is_not_started(self, docker):
        _deploy("honeygain")
        copy = docker.named("cashpilot-honeygain-p3")
        copy.status = "exited"
        with pytest.raises(proxy_tunnel.ProxyTunnelError):
            _rebuild("honeygain")
        assert docker.named("cashpilot-honeygain-p3") is copy and copy.status == "exited"

    def test_no_copy_is_not_created(self, docker):
        with pytest.raises(proxy_tunnel.ProxyTunnelError):
            _rebuild("honeygain")
        assert docker.named("cashpilot-honeygain-p3") is None and not docker.tunnels()

    def test_the_check_waits_for_a_stop_in_progress(self, docker):
        """The check runs under the lock a stop holds, so a stop that started first wins."""
        _deploy("honeygain")
        lock = proxy_tunnel._deploy_lock(3)
        lock.acquire()
        result: dict = {}

        def rebuild():
            try:
                _rebuild("honeygain")
                result["ok"] = True
            except proxy_tunnel.ProxyTunnelError as exc:
                result["refused"] = str(exc)
            except Exception as exc:  # noqa: BLE001 - reported by the assert below
                result["error"] = repr(exc)

        t = threading.Thread(target=rebuild, daemon=True)
        try:
            t.start()
            t.join(0.2)
            assert t.is_alive(), "the rebuild must wait for the lock"
            proxy_tunnel._stop("honeygain", 3)  # the owner's stop, inside the lock it holds
        finally:
            lock.release()
        t.join(5)
        assert "refused" in result and docker.named("cashpilot-honeygain-p3").status == "exited"


# ---------------------------------------------------------------------------
# What the heartbeat tells the UI's proxied-copy alert
# ---------------------------------------------------------------------------


class TestHeartbeatForTheAlert:
    def test_a_copy_the_owner_stopped_is_reported_as_held_and_a_crashed_one_is_not(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        proxy_tunnel.stop("honeygain", 3)
        entries = {e["slug"]: e for e in _heartbeat()}
        assert entries["honeygain"]["held"] is True
        assert entries["earnfm"]["held"] is False

    def test_an_unreadable_stop_marker_says_nothing_about_held(self, docker):
        _deploy("honeygain")
        with patch.object(proxy_tunnel, "held", side_effect=OSError("denied")):
            entries = _heartbeat()
        assert "held" not in entries[0]

    def test_a_listing_that_fails_raises_instead_of_reporting_no_copies(self, docker):
        """An empty list would read as every copy gone; the worker sends None instead."""
        with (
            patch.object(docker, "list", side_effect=RuntimeError("daemon down")),
            pytest.raises(proxy_tunnel.ProxyTunnelError),
        ):
            _heartbeat()


# ---------------------------------------------------------------------------
# A tunnel change the heartbeat cannot finish is reported, not left silent
# ---------------------------------------------------------------------------


class TestAStuckTunnelChangeIsReported:
    """A change whose worker died after m1 moved into the staged tunnel, with
    m2 still running in the current one. The heartbeat finishes such a change;
    when it cannot, the copies in the staged tunnel say why (tunnel_change),
    so the UI does not take them for copies whose tunnel is gone."""

    def _half_done(self, docker, *, auth=None):
        _deploy("m1")
        _deploy("m2")
        current = docker.named("cashpilot-tunnel-p3")
        staged = docker.create(
            name="cashpilot-tunnel-p3-next",
            image=IMAGE,
            labels={
                LABEL_MANAGED: "true",
                LABEL_ROLE: "tunnel",
                LABEL_SERVICE: proxy_tunnel.SHARED_SLUG,
                LABEL_PROXY: "3",
            },
        )
        staged.files = {**current.files, **({"proxy_auth": auth} if auth else {})}
        proxy_tunnel._clone_into(docker, docker.named("cashpilot-m1-p3"), staged, start=False)
        return current, staged

    def test_a_staged_tunnel_with_no_exit_is_reported_with_the_error(self, docker):
        current, staged = self._half_done(docker, auth="u1:dead@")
        docker.broken_auth.add("u1:dead@")
        # Its copies cannot move back into the working tunnel either.
        with patch.object(proxy_tunnel, "_move_members", side_effect=APIError("500 Server Error: create failed")):
            entries = {e["slug"]: e for e in _heartbeat()}
        change = entries["m1"]["tunnel_change"]
        assert entries["m1"]["tunnel_status"] == "missing"
        assert change["tunnel"] == "cashpilot-tunnel-p3-next"
        assert change["age_seconds"] >= proxy_tunnel.STAGED_STALE_SECONDS
        assert "could not start" in change["reason"] and "could not move back" in change["reason"]
        # Stopped again, so it holds no proxy login while nothing can use it.
        assert staged.status != "running"
        # The copy still in the current tunnel is fine and says nothing of it.
        assert "tunnel_change" not in entries["m2"]
        assert docker.named("cashpilot-tunnel-p3") is current

    def test_running_copies_stay_in_the_working_tunnel_and_the_rest_come_back(self, docker):
        current, staged = self._half_done(docker, auth="u1:dead@")
        docker.broken_auth.add("u1:dead@")
        entries = {e["slug"]: e for e in _heartbeat()}
        assert not [e for e in entries.values() if "tunnel_change" in e]
        assert docker.named("cashpilot-tunnel-p3") is current and current.status == "running"
        assert staged.id not in docker.by_id
        assert _member_ids(docker, current) == ["cashpilot-m1-p3", "cashpilot-m2-p3"]
        assert docker.named("cashpilot-m2-p3").status == "running"

    def test_a_running_staged_tunnel_with_no_exit_takes_no_copy(self, docker):
        current, staged = self._half_done(docker, auth="u1:dead@")
        docker.broken_auth.add("u1:dead@")
        staged.start()  # running, as an older worker left it, but with no exit
        with patch.object(proxy_tunnel, "_move_members", side_effect=APIError("500 Server Error: create failed")):
            entries = {e["slug"]: e for e in _heartbeat()}
        assert "has no exit" in entries["m1"]["tunnel_change"]["reason"]
        assert docker.named("cashpilot-tunnel-p3") is current
        assert _member_ids(docker, current) == ["cashpilot-m2-p3"]
        assert docker.named("cashpilot-m2-p3").status == "running"
        # Once the move back works, the copy in the staged tunnel joins the working one.
        _heartbeat()
        assert staged.id not in docker.by_id
        assert _member_ids(docker, current) == ["cashpilot-m1-p3", "cashpilot-m2-p3"]

    def test_new_settings_get_past_a_staged_tunnel_whose_old_settings_died(self, docker):
        _current, _staged = self._half_done(docker, auth="u1:dead@")
        docker.broken_auth.add("u1:dead@")
        _deploy("m2", _socks(password=NEW_PASSWORD))
        tunnel = docker.named("cashpilot-tunnel-p3")
        assert tunnel.status == "running" and tunnel.files["proxy_auth"] == f"u1:{NEW_PASSWORD}@"
        assert docker.named("cashpilot-tunnel-p3-next") is None
        assert _member_ids(docker, tunnel) == ["cashpilot-m1-p3", "cashpilot-m2-p3"]

    def test_copies_go_back_into_the_working_tunnel_once(self, docker):
        current, staged = self._half_done(docker, auth="u1:dead@")
        docker.broken_auth.add("u1:dead@")
        assert not [e for e in _heartbeat() if "tunnel_change" in e]
        assert docker.named("cashpilot-tunnel-p3") is current and staged.id not in docker.by_id
        assert _member_ids(docker, current) == ["cashpilot-m1-p3", "cashpilot-m2-p3"]
        # The next beat has no staged tunnel left to wait for.
        with patch.object(proxy_tunnel, "_wait_ready", side_effect=AssertionError("waited again")):
            _heartbeat()

    def test_after_a_reboot_the_copies_go_back_into_the_working_tunnel(self, docker):
        """Both tunnels up again after a reboot (an older worker's restart policy), no copy (restart policy no)."""
        current, staged = self._half_done(docker, auth="u1:dead@")
        docker.broken_auth.add("u1:dead@")
        for c in docker.by_id.values():
            c.status = "exited"
        current.status = staged.status = "running"
        _heartbeat()
        assert docker.named("cashpilot-tunnel-p3") is current and staged.id not in docker.by_id
        assert _member_ids(docker, current) == ["cashpilot-m1-p3", "cashpilot-m2-p3"]
        _heartbeat()
        assert {docker.named(n).status for n in ("cashpilot-m1-p3", "cashpilot-m2-p3")} == {"running"}

    def test_a_running_staged_tunnel_still_writing_its_ready_file_is_waited_for(self, docker):
        current, staged = self._half_done(docker)
        staged.start()
        reads = {"n": 0}
        real = staged.exec_run

        def slow(cmd, demux=False):
            reads["n"] += 1
            return (1, b"") if reads["n"] == 1 else real(cmd, demux)

        staged.exec_run = slow
        assert proxy_tunnel._finish_staged(docker, staged, current, "cashpilot-tunnel-p3") is staged
        assert current.id not in docker.by_id
        assert _member_ids(docker, staged) == ["cashpilot-m1-p3", "cashpilot-m2-p3"]

    def test_with_the_working_tunnel_down_the_change_finishes_without_a_start(self, docker):
        """Nothing has an exit to keep, so the staged tunnel is not started just to be judged."""
        current, staged = self._half_done(docker, auth="u1:dead@")
        docker.broken_auth.add("u1:dead@")
        for c in docker.by_id.values():
            c.status = "exited"
        assert proxy_tunnel._finish_staged(docker, staged, current, "cashpilot-tunnel-p3") is staged
        assert staged.status != "running" and current.id not in docker.by_id
        assert _member_ids(docker, staged) == ["cashpilot-m1-p3", "cashpilot-m2-p3"]

    def test_a_half_moved_copy_is_the_reason_given(self, docker):
        _current, staged = self._half_done(docker)
        m2 = docker.named("cashpilot-m2-p3")
        m2.rename("cashpilot-m2-p3-moving")
        clone = docker.create(name="cashpilot-m2-p3-next", image="m2/m2:1", labels=dict(m2.labels))
        clone.attrs["Created"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")  # young: left alone
        (entry,) = [e for e in _heartbeat() if e["slug"] == "m1"]
        assert "cashpilot-m2-p3-moving" in entry["tunnel_change"]["reason"]
        assert "half moved" in entry["tunnel_change"]["reason"]

    def test_a_stranger_on_the_final_name_is_the_reason_given(self, docker):
        current, _staged = self._half_done(docker)
        current.labels = {}  # no longer ours: someone else's container holds the name
        (entry,) = [e for e in _heartbeat() if e["slug"] == "m1"]
        assert "did not create" in entry["tunnel_change"]["reason"]

    def test_an_error_with_no_text_is_still_reported(self, docker):
        self._half_done(docker)
        with patch.object(proxy_tunnel, "_finish_staged", side_effect=RuntimeError()):
            (entry,) = [e for e in _heartbeat() if e["slug"] == "m1"]
        assert entry["tunnel_change"]["reason"] == "RuntimeError"

    def test_a_change_it_can_finish_reports_nothing(self, docker):
        self._half_done(docker)
        entries = _heartbeat()
        assert {e["tunnel_status"] for e in entries} == {"running"}
        assert not [e for e in entries if "tunnel_change" in e]

    def test_a_young_change_is_left_to_its_deploy_and_not_reported(self, docker):
        _current, staged = self._half_done(docker, auth="u1:dead@")
        docker.broken_auth.add("u1:dead@")
        staged.attrs["Created"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        assert not [e for e in _heartbeat() if "tunnel_change" in e]


class TestADirectEarnerWithATunnelsLabelsIsNotOne:
    """Before deploy_raw refused a tunnel's name (and, before ed3afa9, kept the
    service label a caller gave it), a direct deploy of slug tunnel-p3 could make
    cashpilot-tunnel-p3 with every label of a shared tunnel and an image of its
    caller's choosing. deploy_raw's own version label it cannot lose, and no
    tunnel carries it: such a container never gets a proxy login or an earner."""

    @pytest.mark.parametrize("slug", [None, "honeygain"])
    def test_it_gets_no_proxy_login(self, docker, slug):
        labels = {
            LABEL_MANAGED: "true",
            LABEL_ROLE: "tunnel",
            LABEL_SERVICE: proxy_tunnel.SHARED_SLUG,
            LABEL_PROXY: "3",
            "cashpilot.deployed-by": "worker",
            "cashpilot.version": "1",
        }
        if slug:
            labels[proxy_tunnel.LABEL_TUNNEL_FOR] = slug
        planted = docker.create(name=proxy_tunnel.shared_tunnel_name(3, slug), image=IMAGE, labels=labels)
        planted.start()
        assert not proxy_tunnel._is_tunnel_for(planted, 3, slug)
        with pytest.raises(proxy_tunnel.ProxyTunnelError, match="did not create"):
            proxy_tunnel._ensure_tunnel(docker, 3, _socks(), None, slug=slug)
        assert planted.files == {}
        # Control: the same container without deploy_raw's label is a tunnel, and gets the login.
        del planted.labels["cashpilot.version"]
        proxy_tunnel._ensure_tunnel(docker, 3, _socks(), None, slug=slug)
        assert planted.files["proxy_auth"] == "u1:s3cr3t-p%40ss@"

    def test_a_migration_reads_no_settings_from_it_and_moves_nothing_into_it(self, docker):
        planted = _legacy_pair(docker, "honeygain")
        planted.labels["cashpilot.version"] = "1"
        assert proxy_tunnel.migrate_legacy() == []
        assert docker.tunnels() == [planted]
        assert docker.named("cashpilot-tunnel-p3") is None


# ---------------------------------------------------------------------------
# An old earner a redeploy left aside (<name>-replaced)
# ---------------------------------------------------------------------------


def _left_aside(docker):
    """What a worker that died between deploy_raw's move aside and the new earner leaves."""
    _deploy("honeygain")
    earner = docker.named("cashpilot-honeygain-p3")
    earner.stop()
    earner.rename(f"cashpilot-honeygain-p3{orchestrator.REPLACED_SUFFIX}")
    return earner


class TestAnOldEarnerLeftAside:
    def test_removing_the_copy_removes_it_and_its_tunnel(self, docker):
        """Not left holding the proxy login (a live tailnet device) with no copy the owner can see."""
        aside = _left_aside(docker)
        tunnel = docker.named("cashpilot-tunnel-p3")
        removed = proxy_tunnel.remove("honeygain", 3)
        assert aside.name in removed and tunnel.name in removed
        assert docker.by_id == {}

    def test_the_heartbeat_gives_it_back_its_name_and_starts_it(self, docker):
        """The deploy never finished: the old copy is the copy, and runs again once its tunnel is ready."""
        aside = _left_aside(docker)
        (entry,) = proxy_tunnel.status()
        assert aside.name == "cashpilot-honeygain-p3" and aside.status == "running"
        assert entry["name"] == "cashpilot-honeygain-p3" and entry["container_id"] == aside.short_id

    def test_the_heartbeat_keeps_a_held_one_stopped(self, docker):
        aside = _left_aside(docker)
        proxy_tunnel._set_held("cashpilot-honeygain-p3", True)
        (entry,) = proxy_tunnel.status()
        assert aside.name == "cashpilot-honeygain-p3" and aside.status == "exited" and entry["held"] is True

    def test_the_heartbeat_removes_one_beside_its_replacement(self, docker):
        """A removal Docker refused after the new earner ran: a leftover only, and the tunnel can empty again."""
        _deploy("honeygain")
        aside = docker.named("cashpilot-honeygain-p3")
        real_remove = aside.remove
        refusals = iter(range(1))

        def refused_once(force=False, v=False):
            if next(refusals, None) is not None:
                raise APIError("500 Server Error: removal failed")
            real_remove(force=force, v=v)

        aside.remove = refused_once
        _deploy("honeygain")
        new = docker.named("cashpilot-honeygain-p3")
        assert aside.name == f"cashpilot-honeygain-p3{orchestrator.REPLACED_SUFFIX}"
        assert aside.id in docker.by_id and new.id != aside.id and new.status == "running"
        (entry,) = proxy_tunnel.status()
        assert aside.id not in docker.by_id
        assert entry["container_id"] == new.short_id

    def test_while_a_deploy_of_its_proxy_runs_it_is_listed_unproven_and_never_started(self, docker):
        """Until its replacement runs it is still the copy: listed with no digest, and left to the deploy."""
        aside = _left_aside(docker)
        lock = proxy_tunnel._deploy_lock(3)
        with lock, patch.object(orchestrator, "_identity_entry", return_value={"identity_digest": "d"}):
            (entry,) = proxy_tunnel.status()
        assert entry["name"] == "cashpilot-honeygain-p3" and entry["status"] == "exited"
        assert "identity_digest" not in entry
        assert aside.name.endswith(orchestrator.REPLACED_SUFFIX) and aside.status == "exited"


# ---------------------------------------------------------------------------
# What a redeploy does around deploy_raw: the read before it, the cleanup after
# ---------------------------------------------------------------------------


def _get_fails(docker, key, when):
    """containers.get(key) raises a Docker error whenever ``when()`` is true; every other read is as it was."""
    real_get = docker.get

    def get(k):
        if k == key and when():
            raise APIError("500 Server Error: read timed out")
        return real_get(k)

    return patch.object(docker, "get", side_effect=get)


class TestAroundDeployRaw:
    def test_a_legacy_tunnel_read_that_fails_after_the_earner_runs_is_still_a_success(self, docker):
        """The new earner already replaced the copy: the cleanup after it never turns that into a failure."""
        _deploy("honeygain")
        real = orchestrator.deploy_raw.side_effect
        ran = {"done": False}

        def deploy_raw(**kw):
            out = real(**kw)
            ran["done"] = True
            return out

        with (
            patch.object(orchestrator, "deploy_raw", side_effect=deploy_raw),
            _get_fails(docker, proxy_tunnel.tunnel_name("honeygain", 3), lambda: ran["done"]),
        ):
            result = _deploy("honeygain")
        new = docker.named("cashpilot-honeygain-p3")
        assert result["container_id"] == new.id and new.status == "running"

    def test_a_legacy_tunnel_removal_that_fails_after_the_earner_runs_is_still_a_success(self, docker):
        legacy = _legacy_pair(docker, "honeygain", proxy=_socks())

        def refused(force=False, v=False):
            raise APIError("500 Server Error: removal failed")

        legacy.remove = refused
        result = _deploy("honeygain")
        new = docker.named("cashpilot-honeygain-p3")
        assert result["container_id"] == new.id and new.status == "running"
        assert new.attrs["HostConfig"]["NetworkMode"] != f"container:{legacy.id}"

    def test_a_failed_read_before_deploy_raw_keeps_a_stopped_copy_stopped(self, docker):
        """The stop is cleared only once nothing before deploy_raw can fail: the heartbeat never starts the copy."""
        _deploy("honeygain")
        assert proxy_tunnel.stop("honeygain", 3) == {"was_running": True}
        earner = docker.named("cashpilot-honeygain-p3")
        reads = {"n": 0}

        def second_read():
            reads["n"] += 1
            return reads["n"] == 2  # _deploy reads the copy twice: the old earner, then what deploy_raw replaces

        with _get_fails(docker, "cashpilot-honeygain-p3", second_read), pytest.raises(APIError):
            _deploy("honeygain")
        assert "cashpilot-honeygain-p3" in proxy_tunnel.held()
        proxy_tunnel.status()
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "exited"

    def test_a_retry_while_the_failed_container_cannot_go_never_removes_the_copy_aside(self, docker):
        """The real deploy_raw takes <name>-replaced for a leftover: the deploy refuses before it, touching nothing."""
        _deploy("honeygain")
        earner = docker.named("cashpilot-honeygain-p3")
        refused = {"on": True}
        made = []

        def failed_and_stuck(*, slug, image, env, network_mode, labels, name, **_kw):
            earner.stop()
            earner.rename(f"{name}{orchestrator.REPLACED_SUFFIX}")
            new = docker.create(
                image=image,
                name=name,
                network_mode=network_mode,
                labels={**labels, LABEL_SERVICE: slug, LABEL_MANAGED: "true"},
            )
            _kw["on_created"](new.id)
            real_remove = new.remove

            def stuck_remove(force=False, v=False):
                if refused["on"]:
                    raise APIError("409 Client Error: removal of container is already in progress")
                real_remove(force=force, v=v)

            new.remove = stuck_remove
            made.append(new)
            raise orchestrator.ContainerRuntimeError("start failed; the previous container is kept as -replaced")

        with (
            patch.object(orchestrator, "deploy_raw", side_effect=failed_and_stuck),
            pytest.raises(orchestrator.ContainerRuntimeError),
        ):
            _deploy("honeygain")
        (failed,) = made
        # The retry, while Docker still refuses to remove the failed container.
        with pytest.raises(proxy_tunnel.ProxyTunnelError, match="Nothing was changed"):
            _deploy("honeygain")
        assert earner.id in docker.by_id and earner.name.endswith(orchestrator.REPLACED_SUFFIX)
        assert failed.id in docker.by_id and failed.status == "created"
        # Once Docker can, the heartbeat gives the copy its name back and starts it.
        refused["on"] = False
        proxy_tunnel.status()
        assert failed.id not in docker.by_id
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "running"

    def test_a_retry_once_the_failed_container_can_go_settles_it_first_and_deploys(self, docker):
        """Control: the aside is settled under the proxy lock, so a retry that can go ahead replaces the copy itself."""
        _deploy("honeygain")
        earner = docker.named("cashpilot-honeygain-p3")

        def failed_and_left(*, slug, image, env, network_mode, labels, name, **_kw):
            earner.stop()
            earner.rename(f"{name}{orchestrator.REPLACED_SUFFIX}")
            created = docker.create(
                image=image, name=name, labels={**labels, LABEL_SERVICE: slug, LABEL_MANAGED: "true"}
            )
            _kw["on_created"](created.id)
            raise orchestrator.ContainerRuntimeError("start failed")

        real_remove_quietly = proxy_tunnel._remove_quietly
        with (
            patch.object(orchestrator, "deploy_raw", side_effect=failed_and_left),
            # The failed deploy's own cleanup cannot remove it; the next deploy can.
            patch.object(proxy_tunnel, "_remove_quietly", side_effect=APIError("409 removal in progress")),
            pytest.raises(orchestrator.ContainerRuntimeError),
        ):
            _deploy("honeygain")
        assert docker.named("cashpilot-honeygain-p3-replaced") is earner
        with patch.object(proxy_tunnel, "_remove_quietly", side_effect=real_remove_quietly):
            result = _deploy("honeygain")
        new = docker.named("cashpilot-honeygain-p3")
        assert result["container_id"] == new.id and new.status == "running"
        assert docker.named("cashpilot-honeygain-p3-replaced") is None and earner.id not in docker.by_id


class _WorkerDied(BaseException):
    """The worker process ends mid-deploy: no except Exception in _deploy runs."""


class TestReplacementSafety:
    def test_a_worker_that_dies_mid_redeploy_never_starts_a_stopped_copy(self, docker):
        """The stop stays recorded until the new earner runs, so recovery gives the old one its name back, stopped."""
        _deploy("honeygain")
        assert proxy_tunnel.stop("honeygain", 3) == {"was_running": True}
        earner = docker.named("cashpilot-honeygain-p3")

        def dies_after_the_move_aside(*, name, **_kw):
            earner.rename(f"{name}{orchestrator.REPLACED_SUFFIX}")
            raise _WorkerDied

        with (
            patch.object(orchestrator, "deploy_raw", side_effect=dies_after_the_move_aside),
            pytest.raises(_WorkerDied),
        ):
            _deploy("honeygain")
        assert "cashpilot-honeygain-p3" in proxy_tunnel.held()
        _heartbeat()
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "exited"
        _heartbeat()
        assert earner.status == "exited"

    def test_a_failed_redeploy_on_a_new_tunnel_image_keeps_the_original_earner_and_tunnel(self, docker):
        """Never a clone in its place: the old tunnel runs with the old earner inside until the new one runs."""
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        earner = docker.named("cashpilot-honeygain-p3")
        real_create = docker.create

        def create(**kw):
            if kw["name"] == "cashpilot-honeygain-p3":
                raise APIError("500 Server Error: create failed")
            return real_create(**kw)

        with (
            patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": NEW_IMAGE}),
            patch.object(docker, "create", side_effect=create),
            pytest.raises(APIError),
        ):
            _deploy("honeygain")
        assert docker.tunnels() == [tunnel] and tunnel.name == "cashpilot-tunnel-p3" and tunnel.status == "running"
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "running"
        assert _member_ids(docker, tunnel) == ["cashpilot-honeygain-p3"]

    def test_a_redeploy_on_a_new_tunnel_image_removes_the_old_tunnel_once_the_earner_runs(self, docker):
        _deploy("honeygain")
        old = docker.named("cashpilot-tunnel-p3")
        with patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": NEW_IMAGE}):
            result = _deploy("honeygain")
        (tunnel,) = docker.tunnels()
        assert tunnel.id == result["tunnel_id"] != old.id and tunnel.name == "cashpilot-tunnel-p3"
        assert old.id not in docker.by_id
        assert docker.named("cashpilot-honeygain-p3").status == "running"

    def test_a_stale_read_of_an_aside_earner_a_deploy_restored_is_never_removed(self, docker):
        """The heartbeat listed it aside; a deploy gave it its name back before the heartbeat took the lock."""
        _deploy("honeygain")
        earner = docker.named("cashpilot-honeygain-p3")
        stale = copy.copy(earner)
        stale.name = f"cashpilot-honeygain-p3{orchestrator.REPLACED_SUFFIX}"
        proxy_tunnel._settle_replaced_unless_busy(docker, stale)
        assert earner.id in docker.by_id and earner.status == "running"
        assert docker.named("cashpilot-honeygain-p3") is earner


# ---------------------------------------------------------------------------
# A failed redeploy's leftovers: the old earner and its old tunnel stay the copy
# ---------------------------------------------------------------------------


def _failing_redeploy(docker, earner, *, state="created"):
    """deploy_raw as it fails when Docker keeps the failed container: the old earner stays aside.

    ``state`` is what the failed one is left in: "created" (its start was
    refused) or "exited" (its start got no answer and it exited; _await_start
    reports a failure). Returns (deploy_raw stub, the failed containers, a
    switch that lets Docker remove them)."""
    refused = {"on": True}
    made: list[FakeContainer] = []

    def deploy_raw(*, slug, image, env, network_mode, labels, name, **_kw):
        earner.stop()
        earner.rename(f"{name}{orchestrator.REPLACED_SUFFIX}")
        failed = docker.create(
            image=image,
            name=name,
            network_mode=network_mode,
            labels={**labels, LABEL_SERVICE: slug, LABEL_MANAGED: "true"},
        )
        _kw["on_created"](failed.id)
        if state == "exited":
            failed.start()
            failed.stop()
        real_remove = failed.remove

        def stuck_remove(force=False, v=False):
            if refused["on"]:
                raise APIError("409 Client Error: removal of container is already in progress")
            real_remove(force=force, v=v)

        failed.remove = stuck_remove
        made.append(failed)
        raise orchestrator.ContainerRuntimeError("did not start; the previous container is kept as -replaced")

    return deploy_raw, made, refused


class TestFailedRedeployLeftovers:
    def test_an_exited_replacement_docker_will_not_remove_never_costs_the_old_earner(self, docker):
        """A start with no answer that then exited is a failed deploy: the predecessor is kept, then restored."""
        _deploy("honeygain")
        earner = docker.named("cashpilot-honeygain-p3")
        stub, made, refused = _failing_redeploy(docker, earner, state="exited")
        with (
            patch.object(orchestrator, "deploy_raw", side_effect=stub),
            pytest.raises(orchestrator.ContainerRuntimeError),
        ):
            _deploy("honeygain")
        (failed,) = made
        assert earner.id in docker.by_id and earner.name.endswith(orchestrator.REPLACED_SUFFIX)
        # While Docker keeps it, the heartbeat neither removes the copy aside nor starts the failed one.
        _heartbeat()
        assert earner.id in docker.by_id and failed.status == "exited"
        refused["on"] = False
        _heartbeat()
        assert failed.id not in docker.by_id
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "running"

    def test_control_a_replacement_that_ran_beside_a_leftover_aside_is_the_copy(self, docker):
        """A redeploy that went through and could not remove the old earner: the old one goes, as before."""
        _deploy("honeygain")
        old = docker.named("cashpilot-honeygain-p3")
        old.remove = lambda force=False, v=False: (_ for _ in ()).throw(APIError("500 removal failed"))
        _deploy("honeygain")
        new = docker.named("cashpilot-honeygain-p3")
        new.stop()  # it ran, then exited: still the copy
        del old.remove
        _heartbeat()
        assert old.id not in docker.by_id and docker.named("cashpilot-honeygain-p3") is new

    def test_a_worker_that_dies_after_the_tunnel_is_retired_keeps_the_earner_on_the_next_start(self, docker):
        """The old earner stays in its old tunnel under the retired name: a start gives that tunnel its name back."""
        _deploy("honeygain")
        earner = docker.named("cashpilot-honeygain-p3")
        old_tunnel = docker.named("cashpilot-tunnel-p3")
        with (
            patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": NEW_IMAGE}),
            patch.object(orchestrator, "deploy_raw", side_effect=_WorkerDied),
            pytest.raises(_WorkerDied),
        ):
            _deploy("honeygain")
        assert old_tunnel.name == "cashpilot-tunnel-p3" + proxy_tunnel.RETIRED_SUFFIX
        _heartbeat()
        assert proxy_tunnel.stop("honeygain", 3) == {"was_running": True}
        proxy_tunnel.start("honeygain", 3, _socks())
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "running"
        assert old_tunnel.name == "cashpilot-tunnel-p3" and _member_ids(docker, old_tunnel) == [
            "cashpilot-honeygain-p3"
        ]
        assert docker.tunnels() == [old_tunnel]

    def test_a_failed_redeploy_on_a_new_tunnel_image_whose_failed_earner_docker_keeps_loses_nothing(self, docker):
        """The new tunnel still holds the failed earner, so the old one keeps the retired name; a start reclaims it."""
        _deploy("honeygain")
        earner = docker.named("cashpilot-honeygain-p3")
        old_tunnel = docker.named("cashpilot-tunnel-p3")
        stub, made, refused = _failing_redeploy(docker, earner)
        with (
            patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": NEW_IMAGE}),
            patch.object(orchestrator, "deploy_raw", side_effect=stub),
            pytest.raises(orchestrator.ContainerRuntimeError),
        ):
            _deploy("honeygain")
        (failed,) = made
        assert old_tunnel.name.endswith(proxy_tunnel.RETIRED_SUFFIX)
        # A start while Docker still keeps the failed earner starts nothing.
        with pytest.raises(proxy_tunnel.ProxyTunnelError, match="Nothing was changed"):
            proxy_tunnel.start("honeygain", 3, _socks())
        assert failed.status == "created" and earner.name.endswith(orchestrator.REPLACED_SUFFIX)
        refused["on"] = False
        proxy_tunnel.start("honeygain", 3, _socks())
        assert failed.id not in docker.by_id
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "running"
        assert old_tunnel.name == "cashpilot-tunnel-p3" and docker.tunnels() == [old_tunnel]


def _aside_that_cannot_be_settled(docker):
    """An old earner aside whose rename back Docker refuses, with its name free."""
    earner = _left_aside(docker)
    real_rename = earner.rename

    def refused(new):
        if new == "cashpilot-honeygain-p3":
            raise APIError("500 Server Error: rename failed")
        real_rename(new)

    earner.rename = refused
    return earner


class TestAnAsideTheHeartbeatCannotSettle:
    def test_it_is_listed_as_the_copy_with_no_digest_and_never_started(self, docker):
        earner = _aside_that_cannot_be_settled(docker)
        with patch.object(orchestrator, "_identity_entry", return_value={"identity_digest": "d"}):
            (entry,) = _heartbeat()
        assert entry["name"] == "cashpilot-honeygain-p3" and entry["status"] == "exited"
        assert entry["container_id"] == earner.short_id and "identity_digest" not in entry
        assert earner.status == "exited"

    def test_control_a_settled_aside_is_listed_with_its_digest(self, docker):
        earner = _left_aside(docker)
        with patch.object(orchestrator, "_identity_entry", return_value={"identity_digest": "d"}):
            (entry,) = _heartbeat()
        assert entry["name"] == "cashpilot-honeygain-p3" and entry["identity_digest"] == "d"
        assert earner.status == "running"

    def test_the_ui_keeps_an_expired_hold_while_the_copy_is_aside(self, docker):
        """Listed with no digest, the copy proves nothing: an unanswered deploy's hold is not let go."""
        from app import main

        _aside_that_cannot_be_settled(docker)
        entries = _heartbeat()
        for entry in entries:
            entry["routed"] = True  # worker_api._mark_routed, for a routed service
        containers = main._ledger_containers([], {"proxied": entries})
        hold = {"slug": "honeygain", "copy": 1, "env": {"K": "new"}, "age": 10**9, "instance": "pending-1"}
        settle = AsyncMock()
        with (
            patch.object(main.database, "pending_identities", AsyncMock(return_value=[hold])),
            patch.object(main, "_identity_digest_keys", AsyncMock(return_value=["k"])),
            patch.object(main.database, "active_identity_values", AsyncMock(return_value={"1": {"K": "old"}})),
            patch.object(main.database, "settle_pending_identities", settle),
        ):
            asyncio.run(main._settle_pending_identities(7, containers, complete=True, deadline=True))
        settle.assert_not_awaited()


# ---------------------------------------------------------------------------
# A failed redeploy whose outcome cannot be read or recorded keeps the old earner
# ---------------------------------------------------------------------------


class TestAFailureThatCannotBeRecorded:
    def test_a_read_that_fails_after_deploy_raw_never_costs_the_old_earner(self, docker):
        """The daemon that did not answer the start does not answer the read either: the copy aside stays."""
        _deploy("honeygain")
        earner = docker.named("cashpilot-honeygain-p3")
        stub, made, refused = _failing_redeploy(docker, earner, state="exited")
        reads = {"left": 0}

        def failing_once():
            if made and reads["left"] == 0:
                reads["left"] = 1
                return True
            return False

        with (
            patch.object(orchestrator, "deploy_raw", side_effect=stub),
            _get_fails(docker, "cashpilot-honeygain-p3", failing_once),
            pytest.raises(orchestrator.ContainerRuntimeError),
        ):
            _deploy("honeygain")
        (failed,) = made
        assert reads["left"] == 1
        _heartbeat()
        assert earner.id in docker.by_id and failed.status == "exited"
        refused["on"] = False
        _heartbeat()
        assert failed.id not in docker.by_id
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "running"

    def test_a_failure_marker_the_disk_refuses_never_costs_the_old_earner(self, docker, tmp_path):
        _deploy("honeygain")
        earner = docker.named("cashpilot-honeygain-p3")
        stub, made, refused = _failing_redeploy(docker, earner, state="exited")
        with (
            patch.object(proxy_tunnel, "FAILED_MARKER", str(tmp_path / "no-such-dir" / "failed")),
            patch.object(orchestrator, "deploy_raw", side_effect=stub),
        ):
            with pytest.raises(orchestrator.ContainerRuntimeError):
                _deploy("honeygain")
            (failed,) = made
            with patch.object(orchestrator, "_identity_entry", return_value={"identity_digest": "d"}):
                (entry,) = _heartbeat()
            assert earner.id in docker.by_id and failed.status == "exited"
            # The copy reported is the one kept aside, never the failed one, and with no identity proof.
            assert entry["container_id"] == earner.short_id and "identity_digest" not in entry
            refused["on"] = False
            _heartbeat()
        assert failed.id not in docker.by_id
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "running"

    def test_a_kept_record_the_disk_refuses_refuses_the_redeploy_before_anything_changes(self, docker, tmp_path):
        _deploy("honeygain")
        earner = docker.named("cashpilot-honeygain-p3")
        with (
            patch.object(proxy_tunnel, "KEPT_MARKER", str(tmp_path / "no-such-dir" / "kept")),
            pytest.raises(proxy_tunnel.ProxyTunnelError, match="left as it was"),
        ):
            _deploy("honeygain")
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "running"

    def test_a_failed_first_deploy_docker_keeps_is_never_started(self, docker):
        """No old earner to keep: the failed one is not the copy, so the heartbeat removes it, never starts it."""
        _deploy("earnapp")
        refused = {"on": True}
        made: list[FakeContainer] = []

        def deploy_raw(*, slug, image, env, network_mode, labels, name, **_kw):
            failed = docker.create(
                image=image,
                name=name,
                network_mode=network_mode,
                labels={**labels, LABEL_SERVICE: slug, LABEL_MANAGED: "true"},
            )
            _kw["on_created"](failed.id)
            real_remove = failed.remove

            def stuck_remove(force=False, v=False):
                if refused["on"]:
                    raise APIError("409 Client Error: removal of container is already in progress")
                real_remove(force=force, v=v)

            failed.remove = stuck_remove
            made.append(failed)
            raise orchestrator.ContainerRuntimeError("did not start")

        with (
            patch.object(orchestrator, "deploy_raw", side_effect=deploy_raw),
            pytest.raises(orchestrator.ContainerRuntimeError),
        ):
            _deploy("honeygain")
        (failed,) = made
        assert failed.status == "created"
        _heartbeat()
        assert failed.status == "created"
        refused["on"] = False
        _heartbeat()
        assert failed.id not in docker.by_id

    def test_a_copy_kept_in_a_retired_tunnel_is_not_cloned_by_another_copys_deploy(self, docker):
        """Its tunnel gets its name back and is used in place: the copy inside keeps its writable layer."""
        _deploy("honeygain")
        earner = docker.named("cashpilot-honeygain-p3")
        old_tunnel = docker.named("cashpilot-tunnel-p3")
        with patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": NEW_IMAGE}):
            with (
                patch.object(orchestrator, "deploy_raw", side_effect=_WorkerDied),
                pytest.raises(_WorkerDied),
            ):
                _deploy("honeygain")
            assert old_tunnel.name == "cashpilot-tunnel-p3" + proxy_tunnel.RETIRED_SUFFIX
            _deploy("earnapp")
        assert docker.named("cashpilot-honeygain-p3") is earner and earner.status == "running"
        assert old_tunnel.name == "cashpilot-tunnel-p3"
        assert _member_ids(docker, old_tunnel) == ["cashpilot-earnapp-p3", "cashpilot-honeygain-p3"]

    def test_an_earner_moved_aside_after_the_listing_is_never_started_under_the_aside_name(self, docker):
        """The heartbeat listed it under the copy's name; a deploy moved it aside and left a failed one there."""
        _deploy("honeygain")
        earner = docker.named("cashpilot-honeygain-p3")
        tunnel = docker.named("cashpilot-tunnel-p3")
        earner.stop()
        listed = copy.copy(earner)
        earner.rename(f"cashpilot-honeygain-p3{orchestrator.REPLACED_SUFFIX}")
        docker.create(
            image="honeygain/honeygain:1",
            name="cashpilot-honeygain-p3",
            network_mode=f"container:{tunnel.id}",
            labels={**earner.labels},
        )
        starts = listed.starts
        proxy_tunnel._start_when_ready(listed, tunnel, "honeygain", ready=True)
        # The fake's start acts on the model it is called on, as docker-py's acts on the container's id.
        assert listed.starts == starts and listed.status == "exited"
        assert earner.name.endswith(orchestrator.REPLACED_SUFFIX)

    def test_an_earner_whose_tunnel_restarts_during_its_start_is_stopped_again(self, docker):
        """The read said ready, then the tunnel restarted before the start: its new run may have no firewall yet."""
        _deploy("honeygain")
        earner = docker.named("cashpilot-honeygain-p3")
        tunnel = docker.named("cashpilot-tunnel-p3")
        earner.stop()
        real_start = earner.start

        def start():
            tunnel.attrs["State"]["StartedAt"] = "9999-01-01T00:00:00Z"  # a new run of the tunnel
            real_start()

        earner.start = start
        proxy_tunnel._start_when_ready(earner, tunnel, "honeygain", ready=True)
        assert earner.status == "exited"

    def test_control_an_earner_whose_tunnel_stays_on_its_run_is_started(self, docker):
        _deploy("honeygain")
        earner = docker.named("cashpilot-honeygain-p3")
        tunnel = docker.named("cashpilot-tunnel-p3")
        earner.stop()
        proxy_tunnel._start_when_ready(earner, tunnel, "honeygain", ready=True)
        assert earner.status == "running"

    def test_an_unreadable_failure_record_removes_no_earner(self, docker, tmp_path):
        """Not known whether a deploy failed: nothing is started, and nothing is removed for it."""
        _deploy("honeygain")
        earner = docker.named("cashpilot-honeygain-p3")
        tunnel = docker.named("cashpilot-tunnel-p3")
        earner.stop()
        unreadable = tmp_path / "failed-dir"
        unreadable.mkdir()  # reading a folder raises IsADirectoryError, an OSError
        with patch.object(proxy_tunnel, "FAILED_MARKER", str(unreadable)):
            proxy_tunnel._start_when_ready(earner, tunnel, "honeygain", ready=True)
        assert earner.id in docker.by_id and earner.status == "exited"

    def test_a_failed_first_deploy_whose_failure_cannot_be_recorded_is_never_started(self, docker, tmp_path):
        """The deploy recorded it was in flight before it created anything: a missing failure record proves nothing."""
        _deploy("earnapp")
        refused = {"on": True}
        made: list[FakeContainer] = []

        def deploy_raw(*, slug, image, env, network_mode, labels, name, **_kw):
            failed = docker.create(
                image=image,
                name=name,
                network_mode=network_mode,
                labels={**labels, LABEL_SERVICE: slug, LABEL_MANAGED: "true"},
            )
            _kw["on_created"](failed.id)
            real_remove = failed.remove

            def stuck_remove(force=False, v=False):
                if refused["on"]:
                    raise APIError("409 Client Error: removal of container is already in progress")
                real_remove(force=force, v=v)

            failed.remove = stuck_remove
            made.append(failed)
            raise orchestrator.ContainerRuntimeError("did not start")

        with (
            patch.object(proxy_tunnel, "FAILED_MARKER", str(tmp_path / "no-such-dir" / "failed")),
            patch.object(orchestrator, "deploy_raw", side_effect=deploy_raw),
        ):
            with pytest.raises(orchestrator.ContainerRuntimeError):
                _deploy("honeygain")
            (failed,) = made
            with patch.object(orchestrator, "_identity_entry", return_value={"identity_digest": "d"}):
                entries = _heartbeat()
            assert failed.status == "created"
            assert all("identity_digest" not in e for e in entries if e["slug"] == "honeygain")
            refused["on"] = False
            _heartbeat()
        assert failed.id not in docker.by_id
        assert docker.named("cashpilot-earnapp-p3").status == "running"

    def test_a_first_deploy_whose_record_the_disk_refuses_creates_nothing(self, docker, tmp_path):
        _deploy("earnapp")
        with (
            patch.object(proxy_tunnel, "NEW_MARKER", str(tmp_path / "no-such-dir" / "new")),
            pytest.raises(proxy_tunnel.ProxyTunnelError, match="left as it was"),
        ):
            _deploy("honeygain")
        assert docker.named("cashpilot-honeygain-p3") is None


# ---------------------------------------------------------------------------
# A deploy reported as done is never undone by a record it left behind
# ---------------------------------------------------------------------------

NAME = "cashpilot-honeygain-p3"


@contextlib.contextmanager
def _clearing_fails(marker: str):
    """Writes to proxy_tunnel.<marker> that drop an entry raise OSError; writes that add one still work."""
    real = proxy_tunnel._write_names
    on = {"on": True}

    def write(path, names):
        if on["on"] and path == getattr(proxy_tunnel, marker) and not proxy_tunnel._read_names(path) <= set(names):
            raise OSError(28, "No space left on device")
        real(path, names)

    with patch.object(proxy_tunnel, "_write_names", side_effect=write):
        yield on


def _refuse_removal(container, times: int | None = None):
    """Docker refuses to remove ``container``: every time, or the first ``times`` times."""
    real_remove = container.remove
    left = {"n": times}

    def remove(force=False, v=False):
        if left["n"] is None or left["n"] > 0:
            if left["n"] is not None:
                left["n"] -= 1
            raise APIError("500 Server Error: removal failed")
        real_remove(force=force, v=v)

    container.remove = remove


class TestADeployReportedDoneStaysDone:
    def test_a_retry_while_the_copy_aside_cannot_get_its_name_back_is_refused(self, docker):
        """The old earner aside is the copy while the name is free: a deploy now would be undone by the heartbeat."""
        _deploy("honeygain")
        earner = docker.named(NAME)
        real_rename = earner.rename
        refused = {"on": True}

        def rename(new):
            if new == NAME and refused["on"]:
                raise APIError("500 Server Error: rename failed")
            real_rename(new)

        earner.rename = rename

        def fails_after_the_move_aside(*, name, **_kw):
            earner.stop()
            earner.rename(f"{name}{orchestrator.REPLACED_SUFFIX}")
            raise orchestrator.ContainerRuntimeError("create failed")

        with (
            patch.object(orchestrator, "deploy_raw", side_effect=fails_after_the_move_aside),
            pytest.raises(orchestrator.ContainerRuntimeError),
        ):
            _deploy("honeygain")
        assert earner.name == NAME + orchestrator.REPLACED_SUFFIX
        assert earner.id in proxy_tunnel._read_names(proxy_tunnel.KEPT_MARKER)
        creates = sum(1 for e in docker.events if e == ("create", NAME))
        with pytest.raises(proxy_tunnel.ProxyTunnelError, match="could not be put back"):
            _deploy("honeygain")
        assert docker.named(NAME) is None and sum(1 for e in docker.events if e == ("create", NAME)) == creates
        assert earner.name == NAME + orchestrator.REPLACED_SUFFIX
        assert earner.id in proxy_tunnel._read_names(proxy_tunnel.KEPT_MARKER)
        # Once Docker renames again, the heartbeat puts the copy back; a later deploy then stays done.
        refused["on"] = False
        _heartbeat()
        assert docker.named(NAME) is earner and earner.status == "running"
        result = _deploy("honeygain")
        new = docker.named(NAME)
        assert result["container_id"] == new.id != earner.id
        _heartbeat()
        assert docker.named(NAME) is new and new.status == "running" and earner.id not in docker.by_id

    def test_a_success_whose_kept_record_cannot_be_cleared_removes_the_old_earner_itself(self, docker):
        """deploy_raw could not remove the old earner and the record keeping it cannot go: it is removed instead."""
        _deploy("honeygain")
        old = docker.named(NAME)
        _refuse_removal(old, times=1)  # deploy_raw's removal only
        with _clearing_fails("KEPT_MARKER"):
            result = _deploy("honeygain")
            new = docker.named(NAME)
            assert result["container_id"] == new.id and new.status == "running"
            _heartbeat()
        assert docker.named(NAME) is new and new.status == "running" and old.id not in docker.by_id

    def test_a_success_that_can_neither_clear_its_record_nor_remove_the_old_earner_is_undone(self, docker):
        """Nothing can make the new earner the copy for good: the deploy fails, and the old earner is the copy."""
        _deploy("honeygain")
        old = docker.named(NAME)
        _refuse_removal(old)
        with _clearing_fails("KEPT_MARKER"):
            with pytest.raises(proxy_tunnel.ProxyTunnelError, match="previous copy"):
                _deploy("honeygain")
            assert docker.named(NAME) is old and old.status == "running"
            assert [c for c in docker.by_id.values() if c.name.startswith(NAME)] == [old]
            _heartbeat()
        assert docker.named(NAME) is old and old.status == "running"

    def test_control_a_kept_record_that_cannot_be_cleared_after_the_old_earner_went_is_a_success(self, docker):
        _deploy("honeygain")
        old = docker.named(NAME)
        with _clearing_fails("KEPT_MARKER"):
            result = _deploy("honeygain")
            _heartbeat()
        new = docker.named(NAME)
        assert result["container_id"] == new.id and new.status == "running" and old.id not in docker.by_id

    def test_a_first_deploy_whose_record_cannot_be_cleared_is_undone(self, docker):
        """Its record would keep the new earner from ever starting again: reported as failed, and removed."""
        _deploy("earnapp")
        with _clearing_fails("NEW_MARKER"):
            with pytest.raises(proxy_tunnel.ProxyTunnelError):
                _deploy("honeygain")
            assert docker.named(NAME) is None
            _heartbeat()
        assert docker.named(NAME) is None

    def test_a_first_deploy_a_worker_died_in_is_removed_never_kept(self, docker):
        """The deploy never said it went through: its earner goes, as a redeploy's is undone."""
        _deploy("earnapp")
        real = orchestrator.deploy_raw.side_effect

        def dies_after_the_start(**kw):
            real(**kw)
            raise _WorkerDied

        with patch.object(orchestrator, "deploy_raw", side_effect=dies_after_the_start), pytest.raises(_WorkerDied):
            _deploy("honeygain")
        assert docker.named(NAME).status == "running"
        with patch.object(orchestrator, "_identity_entry", return_value={"identity_digest": "d"}):
            entries = _heartbeat()
        assert docker.named(NAME) is None
        assert all("identity_digest" not in e for e in entries if e["slug"] == "honeygain")

    def test_control_a_first_deploy_clears_its_record(self, docker):
        _deploy("honeygain")
        assert proxy_tunnel._read_names(proxy_tunnel.NEW_MARKER) == set()
        _heartbeat()
        assert docker.named(NAME).status == "running"

    def test_a_redeploy_whose_new_record_cannot_be_read_leaves_the_copy_as_it_was(self, docker, tmp_path):
        """Read before deploy_raw: undoing after it would remove the new earner with the old one already gone."""
        _deploy("honeygain")
        old = docker.named(NAME)
        tunnel = docker.named("cashpilot-tunnel-p3")
        (tmp_path / "new-dir").mkdir()
        with (
            patch.object(proxy_tunnel, "NEW_MARKER", str(tmp_path / "new-dir")),
            pytest.raises(proxy_tunnel.ProxyTunnelError, match="left as it was"),
        ):
            _deploy("honeygain")
        assert docker.named(NAME) is old and old.status == "running"
        assert docker.named("cashpilot-tunnel-p3") is tunnel and tunnel.status == "running"

    def test_a_redeploy_whose_new_record_is_not_text_leaves_the_copy_as_it_was(self, docker, tmp_path):
        _deploy("honeygain")
        old = docker.named(NAME)
        marker = tmp_path / "new-garbled"
        marker.write_bytes(b"\xff\xfe\x00garbled\n")
        with (
            patch.object(proxy_tunnel, "NEW_MARKER", str(marker)),
            pytest.raises(proxy_tunnel.ProxyTunnelError, match="left as it was"),
        ):
            _deploy("honeygain")
        assert docker.named(NAME) is old and old.status == "running"

    def test_a_kept_record_that_cannot_be_cleared_with_the_aside_unreadable_is_a_success(self, docker):
        """The old earner is gone by id: the deploy went through, whatever a name lookup answers."""
        _deploy("honeygain")
        old = docker.named(NAME)
        real_get = docker.get

        def get(key):
            if key == NAME + orchestrator.REPLACED_SUFFIX and old.id not in docker.by_id:
                raise APIError("500 Server Error: daemon busy")
            return real_get(key)

        with _clearing_fails("KEPT_MARKER"), patch.object(docker, "get", side_effect=get):
            result = _deploy("honeygain")
        new = docker.named(NAME)
        assert result["container_id"] == new.id and new.status == "running" and old.id not in docker.by_id
        _heartbeat()
        assert docker.named(NAME) is new and new.status == "running"

    def test_a_failed_commit_never_removes_the_new_earner_once_the_old_one_may_be_gone(self, docker):
        """Not known whether the old earner is still here: the new one stays, never the box left with no copy."""
        _deploy("honeygain")
        old = docker.named(NAME)
        old_id = old.id
        real_get = docker.get

        def get(key):
            if key == old_id and old_id not in docker.by_id:
                raise APIError("500 Server Error: daemon busy")
            return real_get(key)

        with _clearing_fails("KEPT_MARKER"), patch.object(docker, "get", side_effect=get):
            with pytest.raises(proxy_tunnel.ProxyTunnelError):
                _deploy("honeygain")
            new = docker.named(NAME)
            assert new is not None and new.id != old_id and new.status == "running"
        _heartbeat()
        assert docker.named(NAME) is new and new.status == "running"

    def test_a_container_under_the_aside_name_that_is_not_this_copy_never_blocks_a_deploy(self, docker):
        """Only this copy's own old earner aside is the copy; anything else is deploy_raw's to handle."""
        _deploy("earnapp")
        docker.create(
            name=NAME + orchestrator.REPLACED_SUFFIX,
            labels={LABEL_MANAGED: "true", LABEL_SERVICE: "honeygain"},
            network_mode="bridge",
        )
        result = _deploy("honeygain")
        new = docker.named(NAME)
        assert result["container_id"] == new.id and new.status == "running"

    def test_a_manual_start_never_runs_an_earner_a_first_deploy_died_in(self, docker):
        """Recorded in NEW_MARKER: it never was the copy, so a start refuses it as the heartbeat would."""
        _deploy("earnapp")
        real = orchestrator.deploy_raw.side_effect

        def dies_after_the_start(**kw):
            real(**kw)
            raise _WorkerDied

        with patch.object(orchestrator, "deploy_raw", side_effect=dies_after_the_start), pytest.raises(_WorkerDied):
            _deploy("honeygain")
        left = docker.named(NAME)
        left.stop()
        starts = left.starts
        with pytest.raises(proxy_tunnel.ProxyTunnelError, match="did not finish"):
            proxy_tunnel.start("honeygain", 3, _socks(), None)
        assert left.status == "exited" and left.starts == starts

    def test_a_redeploy_never_needs_the_new_record_once_the_old_earner_is_gone(self, docker):
        """Unreadable only after deploy_raw removed the old earner: never named there, so the deploy stands."""
        _deploy("honeygain")
        old = docker.named(NAME)
        real_read = proxy_tunnel._read_names
        real_raw = orchestrator.deploy_raw.side_effect
        broken = []

        def read(path):
            if broken and path == proxy_tunnel.NEW_MARKER:
                raise OSError(5, "Input/output error")
            return real_read(path)

        def raw(**kw):
            result = real_raw(**kw)
            broken.append(True)
            return result

        with (
            patch.object(proxy_tunnel, "_read_names", side_effect=read),
            patch.object(orchestrator, "deploy_raw", side_effect=raw),
        ):
            result = _deploy("honeygain")
        new = docker.named(NAME)
        assert result["container_id"] == new.id and new.status == "running" and old.id not in docker.by_id
        _heartbeat()
        assert docker.named(NAME) is new and new.status == "running"


class TestAnEarnerNeverStartsInATunnelNotReady:
    @pytest.mark.parametrize("marker", ["FAILED_MARKER", "NEW_MARKER"])
    def test_a_marker_read_that_fails_once_starts_nothing(self, docker, marker):
        """After a reboot: the tunnel runs but has not written /run/ready, and one read of a record fails."""
        _deploy("honeygain")
        earner = docker.named(NAME)
        earner.status = "exited"  # Docker does not start a proxied earner after a reboot
        real_read = proxy_tunnel._read_names
        left = {"n": 1}

        def read(path):
            if path == getattr(proxy_tunnel, marker) and left["n"]:
                left["n"] -= 1
                raise OSError(24, "Too many open files")
            return real_read(path)

        with patch.object(docker, "ready", return_value=False):
            _heartbeat()  # control: no read error, nothing starts
            assert earner.status == "exited"
            with patch.object(proxy_tunnel, "_read_names", side_effect=read):
                _heartbeat()
            assert left["n"] == 0 and earner.status == "exited"
        _heartbeat()
        assert earner.status == "running"


class TestAStaleFirstDeployRecord:
    @staticmethod
    def _dead_first_deploy(docker):
        """A first deploy the worker died in after its earner started: NAME stays recorded in NEW_MARKER."""
        _deploy("earnapp")
        real = orchestrator.deploy_raw.side_effect

        def dies_after_the_start(**kw):
            real(**kw)
            raise _WorkerDied

        with patch.object(orchestrator, "deploy_raw", side_effect=dies_after_the_start), pytest.raises(_WorkerDied):
            _deploy("honeygain")
        assert NAME in proxy_tunnel._read_names(proxy_tunnel.NEW_MARKER)
        return docker.named(NAME)

    def test_a_redeploy_whose_record_cannot_be_cleared_never_loses_its_replacement(self, docker):
        """The record named the copy, not the replacement: the replacement stays, and nothing removes it later."""
        left = self._dead_first_deploy(docker)
        real_raw = orchestrator.deploy_raw.side_effect
        with _clearing_fails("NEW_MARKER") as clearing:
            clearing["on"] = False

            def raw(**kw):
                result = real_raw(**kw)
                clearing["on"] = True  # the predecessor is gone; now no record can be cleared
                return result

            with patch.object(orchestrator, "deploy_raw", side_effect=raw):
                result = _deploy("honeygain")
            new = docker.named(NAME)
            assert new is not None and result["container_id"] == new.id and left.id not in docker.by_id
            _heartbeat()
            assert docker.named(NAME) is new and new.status == "running"
        _heartbeat()
        assert docker.named(NAME) is new and new.status == "running"

    def test_control_a_failed_redeploy_still_takes_the_dead_first_deploys_earner_for_no_copy(self, docker):
        """Bound to that earner, the record still says it is not the copy once a failed redeploy puts it back."""
        left = self._dead_first_deploy(docker)
        with (
            patch.object(orchestrator, "deploy_raw", side_effect=orchestrator.ContainerRuntimeError("no start")),
            pytest.raises(orchestrator.ContainerRuntimeError),
        ):
            _deploy("honeygain")
        assert left.id not in docker.by_id and docker.named(NAME) is None  # put back, then removed, never started
        _heartbeat()
        assert docker.named(NAME) is None

    def test_a_record_the_disk_will_not_bind_refuses_the_redeploy_before_anything_changes(self, docker):
        left = self._dead_first_deploy(docker)
        with _clearing_fails("NEW_MARKER"), pytest.raises(proxy_tunnel.ProxyTunnelError, match="left as it was"):
            _deploy("honeygain")
        assert docker.named(NAME) is left
        assert proxy_tunnel._read_names(proxy_tunnel.NEW_MARKER) == {NAME}


class TestARetiredTunnelIsOnlyEverItsOwn:
    def test_no_slug_names_a_tunnel_another_tunnels_retired_name_could_take(self):
        """Slugs are [a-z0-9-]: a suffix with any other character is never a routed service's own tunnel."""
        assert set(proxy_tunnel.RETIRED_SUFFIX) - set("abcdefghijklmnopqrstuvwxyz0123456789-")

    def test_a_redeploy_never_moves_its_earner_for_a_service_whose_slug_ends_in_old(self, docker):
        """honeygain's old tunnel is kept aside; honeygain-old's own tunnel is never touched or taken for it."""
        with patch.object(proxy_tunnel.route_gate, "routed", return_value={"honeygain": 3, "honeygain-old": 3}):
            _deploy("honeygain-old")
            other = docker.named("cashpilot-tunnel-p3-honeygain-old")
            other_earner = docker.named("cashpilot-honeygain-old-p3")
            _deploy("honeygain")
            earner = docker.named(NAME)
            own = docker.named("cashpilot-tunnel-p3-honeygain")
            with (
                patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": NEW_IMAGE}),
                patch.object(orchestrator, "deploy_raw", side_effect=_WorkerDied),
                pytest.raises(_WorkerDied),
            ):
                _deploy("honeygain")
        assert docker.named(NAME) is earner and _member_ids(docker, own) == [NAME]
        assert own.name == "cashpilot-tunnel-p3-honeygain" + proxy_tunnel.RETIRED_SUFFIX
        assert docker.named("cashpilot-tunnel-p3-honeygain-old") is other and other.status == "running"
        assert _member_ids(docker, other) == ["cashpilot-honeygain-old-p3"] and other_earner.status == "running"


class TestARecoveredSharedCopyIsNeverRecreated:
    def test_a_start_runs_it_in_its_retired_tunnel_while_another_copy_holds_the_name(self, docker):
        """The new tunnel took another copy before the failed one went: the old earner starts where it is."""
        _deploy("honeygain")
        earner = docker.named(NAME)
        old_tunnel = docker.named("cashpilot-tunnel-p3")
        stub, made, refused = _failing_redeploy(docker, earner)
        with patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": NEW_IMAGE}):
            with (
                patch.object(orchestrator, "deploy_raw", side_effect=stub),
                pytest.raises(orchestrator.ContainerRuntimeError),
            ):
                _deploy("honeygain")
            _deploy("earnapp")
        new_tunnel = docker.named("cashpilot-tunnel-p3")
        assert new_tunnel.id != old_tunnel.id and "cashpilot-earnapp-p3" in _member_ids(docker, new_tunnel)
        refused["on"] = False
        _heartbeat()
        (failed,) = made
        assert failed.id not in docker.by_id and docker.named(NAME) is earner
        assert old_tunnel.name == "cashpilot-tunnel-p3" + proxy_tunnel.RETIRED_SUFFIX
        proxy_tunnel.stop("honeygain", 3)
        assert earner.status == "exited"
        proxy_tunnel.start("honeygain", 3, _socks())
        assert docker.named(NAME) is earner and earner.status == "running"
        assert _member_ids(docker, old_tunnel) == [NAME] and old_tunnel.status == "running"
        assert _member_ids(docker, new_tunnel) == ["cashpilot-earnapp-p3"]

    @staticmethod
    def _stopped_in_retired_tunnel(docker):
        """honeygain stopped in its old tunnel under the retired name, earnapp in the new tunnel under the name."""
        _deploy("honeygain")
        earner = docker.named(NAME)
        old_tunnel = docker.named("cashpilot-tunnel-p3")
        stub, _made, refused = _failing_redeploy(docker, earner)
        with patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": NEW_IMAGE}):
            with (
                patch.object(orchestrator, "deploy_raw", side_effect=stub),
                pytest.raises(orchestrator.ContainerRuntimeError),
            ):
                _deploy("honeygain")
            _deploy("earnapp")
        refused["on"] = False
        _heartbeat()
        proxy_tunnel.stop("honeygain", 3)
        assert old_tunnel.name == "cashpilot-tunnel-p3" + proxy_tunnel.RETIRED_SUFFIX
        assert old_tunnel.status == "exited" and docker.named(NAME) is earner
        return earner, old_tunnel

    def test_a_start_after_a_password_change_runs_it_on_the_new_settings_and_own_ip(self, docker):
        """The retired tunnel takes the settings the owner sent and the box's current address, in place."""
        earner, old_tunnel = self._stopped_in_retired_tunnel(docker)
        proxy_tunnel.start("honeygain", 3, _socks(password=NEW_PASSWORD), "198.51.100.7")
        assert old_tunnel.files["proxy_auth"] == proxy_tunnel.proxy_auth("u1", NEW_PASSWORD)
        assert old_tunnel.files["own_ip"] == "198.51.100.7"
        assert docker.named(NAME) is earner and earner.status == "running"
        assert _member_ids(docker, old_tunnel) == [NAME] and old_tunnel.status == "running"

    @pytest.mark.parametrize("password", [PASSWORD, NEW_PASSWORD])
    def test_a_failed_start_keeps_the_old_password_out_of_the_error(self, docker, password):
        """Its log holds the old password; the error the UI shows never does, whether or not it changed."""
        earner, old_tunnel = self._stopped_in_retired_tunnel(docker)
        real_ready = docker.ready
        docker.ready = lambda c: c.id != old_tunnel.id and real_ready(c)  # only its own tunnel finds no exit
        old_tunnel.logs = lambda tail=5: f"tun2proxy: auth u1 {PASSWORD} refused".encode()
        with pytest.raises(proxy_tunnel.ProxyTunnelError) as caught:
            proxy_tunnel.start("honeygain", 3, _socks(password=password))
        assert "refused" in str(caught.value) and PASSWORD not in str(caught.value)
        assert earner.status == "exited" and old_tunnel.status == "exited"


class TestAnOldEarnerRemovedDespiteAnError:
    def test_a_removal_that_took_effect_but_errored_is_a_success(self, docker):
        """deploy_raw could not remove the old earner and the record cannot go; the commit's DELETE times out after it worked."""
        _deploy("honeygain")
        old = docker.named(NAME)
        real_remove = old.remove
        calls = {"n": 0}

        def remove(force=False, v=False):
            calls["n"] += 1
            if calls["n"] == 1:
                raise APIError("500 Server Error: removal failed")
            real_remove(force=force, v=v)
            raise APIError("500 Server Error: read timed out")

        old.remove = remove
        with _clearing_fails("KEPT_MARKER"):
            result = _deploy("honeygain")
            new = docker.named(NAME)
            assert result["container_id"] == new.id != old.id and new.status == "running"
            assert old.id not in docker.by_id
            _heartbeat()
        assert docker.named(NAME) is new and new.status == "running"


class TestAForeignContainerOnTheRetiredName:
    def test_a_redeploy_on_a_new_tunnel_image_is_refused_before_anything_changes(self, docker):
        """The old tunnel cannot be kept aside, so the earner would be recreated: nothing is touched instead."""
        _deploy("honeygain")
        earner = docker.named(NAME)
        tunnel = docker.named("cashpilot-tunnel-p3")
        foreign = docker.create(name="cashpilot-tunnel-p3" + proxy_tunnel.RETIRED_SUFFIX, labels={}, image="x")
        before = set(docker.by_id)
        with (
            patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": NEW_IMAGE}),
            pytest.raises(proxy_tunnel.ProxyTunnelError, match=r"cashpilot-tunnel-p3\.old"),
        ):
            _deploy("honeygain")
        assert set(docker.by_id) == before
        assert docker.named(NAME) is earner and earner.status == "running"
        assert docker.named("cashpilot-tunnel-p3") is tunnel and tunnel.status == "running"
        assert _member_ids(docker, tunnel) == [NAME] and foreign.name.endswith(".old")

    def test_control_without_it_the_redeploy_takes_the_new_image(self, docker):
        _deploy("honeygain")
        old = docker.named(NAME)
        with patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": NEW_IMAGE}):
            _deploy("honeygain")
        (tunnel,) = docker.tunnels()
        assert tunnel.attrs["Config"]["Image"] == NEW_IMAGE and old.id not in docker.by_id


def _running_in_retired_tunnel(docker):
    """honeygain running in its old tunnel under the retired name, earnapp in the new tunnel under the name."""
    _deploy("honeygain")
    earner = docker.named(NAME)
    old_tunnel = docker.named("cashpilot-tunnel-p3")
    stub, _made, refused = _failing_redeploy(docker, earner)
    with patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": NEW_IMAGE}):
        with (
            patch.object(orchestrator, "deploy_raw", side_effect=stub),
            pytest.raises(orchestrator.ContainerRuntimeError),
        ):
            _deploy("honeygain")
        _deploy("earnapp")
    refused["on"] = False
    _heartbeat()
    assert old_tunnel.name == "cashpilot-tunnel-p3" + proxy_tunnel.RETIRED_SUFFIX
    assert docker.named(NAME) is earner and earner.status == "running" and old_tunnel.status == "running"
    return earner, old_tunnel


class TestAnOwnIpChangeRestartsTheTunnel:
    """own_ip is outside the settings digest, but the leak guard reads it when the tunnel starts."""

    def test_a_running_retired_tunnel_takes_a_new_own_ip_on_the_same_settings(self, docker):
        earner, old_tunnel = _running_in_retired_tunnel(docker)
        assert old_tunnel.files["own_ip"] == ""
        starts = old_tunnel.starts
        proxy_tunnel.start("honeygain", 3, _socks(), "198.51.100.7")
        assert old_tunnel.files["own_ip"] == "198.51.100.7" and old_tunnel.starts == starts + 1
        assert docker.named(NAME) is earner and earner.status == "running"
        # Restarted into the tunnel's new run, never recreated.
        assert earner.attrs["State"]["StartedAt"] > old_tunnel.attrs["State"]["StartedAt"]
        assert _member_ids(docker, old_tunnel) == [NAME] and old_tunnel.status == "running"

    def test_the_shared_tunnel_of_a_running_copy_takes_a_new_own_ip_on_the_same_settings(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        earner = docker.named(NAME)
        starts = tunnel.starts
        proxy_tunnel.start("honeygain", 3, _socks(), None)  # control: no address known is no change
        assert tunnel.starts == starts and tunnel.files["own_ip"] == ""
        proxy_tunnel.start("honeygain", 3, _socks(), "198.51.100.7")
        assert docker.named("cashpilot-tunnel-p3") is tunnel and tunnel.status == "running"
        assert tunnel.files["own_ip"] == "198.51.100.7" and tunnel.starts == starts + 1
        assert docker.named(NAME) is earner and earner.status == "running"
        assert earner.attrs["State"]["StartedAt"] > tunnel.attrs["State"]["StartedAt"]
        proxy_tunnel.start("honeygain", 3, _socks(), "198.51.100.7")  # the same address again: no restart
        assert tunnel.starts == starts + 1

    # An address the worker could not tell this time ('' in the files) never
    # replaces a known one: cp-tunnel's leak guard lets any exit through when
    # own_ip is empty, the box's own address too.

    @pytest.mark.parametrize("password", [PASSWORD, NEW_PASSWORD])
    def test_a_stopped_retired_tunnel_keeps_its_own_ip_when_the_address_is_unknown(self, docker, password):
        earner, old_tunnel = TestARecoveredSharedCopyIsNeverRecreated._stopped_in_retired_tunnel(docker)
        proxy_tunnel.start("honeygain", 3, _socks(), "198.51.100.7")
        proxy_tunnel.stop("honeygain", 3)
        old_tunnel.stop()
        proxy_tunnel.start("honeygain", 3, _socks(password=password), None)
        assert old_tunnel.files["own_ip"] == "198.51.100.7"
        assert old_tunnel.files["proxy_auth"] == proxy_tunnel.proxy_auth("u1", password)
        assert docker.named(NAME) is earner and earner.status == "running"

    @pytest.mark.parametrize("stopped", [True, False])
    def test_the_shared_tunnel_keeps_its_own_ip_on_a_settings_change_with_the_address_unknown(self, docker, stopped):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        proxy_tunnel.start("honeygain", 3, _socks(), "198.51.100.7")
        if stopped:
            proxy_tunnel.stop("honeygain", 3)
            tunnel.stop()
        proxy_tunnel.start("honeygain", 3, _socks(password=NEW_PASSWORD), None)
        assert docker.named("cashpilot-tunnel-p3") is tunnel and tunnel.status == "running"
        assert tunnel.files["proxy_auth"] == proxy_tunnel.proxy_auth("u1", NEW_PASSWORD)
        assert tunnel.files["own_ip"] == "198.51.100.7"

    def test_a_tunnel_replaced_for_a_new_image_keeps_its_own_ip_when_the_address_is_unknown(self, docker):
        _deploy("honeygain")
        old = docker.named("cashpilot-tunnel-p3")
        proxy_tunnel.start("honeygain", 3, _socks(), "198.51.100.7")
        with patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": NEW_IMAGE}):
            _deploy("honeygain")  # own_ip None
        new = docker.named("cashpilot-tunnel-p3")
        assert new.id != old.id and new.attrs["Config"]["Image"] == NEW_IMAGE
        assert new.files["own_ip"] == "198.51.100.7"


class TestAnOldEarnerDockerIsStillRemoving:
    @pytest.mark.parametrize("end", ["gone", "dead"])
    def test_the_new_earner_stays_the_copy(self, docker, end):
        """The commit's DELETE times out while Docker is removing the old earner, and the record cannot go."""
        _deploy("honeygain")
        old = docker.named(NAME)
        real_remove, real_rename, real_start = old.remove, old.rename, old.start
        calls = {"n": 0}

        def remove(force=False, v=False):
            calls["n"] += 1
            if calls["n"] == 1:
                raise APIError("500 Server Error: removal failed")  # deploy_raw's own removal
            if old.status == "removing":
                raise APIError("409 Client Error: removal of container is already in progress")
            if old.status == "dead":
                return real_remove(force=force, v=v)
            old.status = "removing"
            raise APIError("500 Server Error: read timed out")

        def refused_while_removing(real):
            def call(*args):
                if old.status in ("removing", "dead"):
                    raise APIError("409 Client Error: container is dead or marked for removal")
                return real(*args)

            return call

        old.remove, old.rename, old.start = (
            remove,
            refused_while_removing(real_rename),
            refused_while_removing(real_start),
        )
        with _clearing_fails("KEPT_MARKER"):
            result = _deploy("honeygain")
            new = docker.named(NAME)
            assert result["container_id"] == new.id != old.id and new.status == "running"
            assert old.status == "removing"
            if end == "gone":
                del docker.by_id[old.id]  # the daemon finishes the removal
            else:
                old.status = "dead"  # the daemon's removal failed: it can never run again
            _heartbeat()
        assert docker.named(NAME) is new and new.status == "running"


class TestABrokenTunnelWithTheRetiredNameTaken:
    def test_a_redeploy_still_goes_through_on_a_new_tunnel(self, docker):
        """Docker cannot start the stopped tunnel again: refusing would leave the copy offline for nothing."""
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        docker.create(name="cashpilot-tunnel-p3" + proxy_tunnel.RETIRED_SUFFIX, labels={}, image="x")
        docker.broken.add(tunnel.id)  # it runs, but Docker can no longer write to or start it
        result = _deploy("honeygain", _socks(password=NEW_PASSWORD))
        current = docker.named("cashpilot-tunnel-p3")
        assert current.id != tunnel.id and current.status == "running" and result["tunnel_id"] == current.id
        assert current.files["proxy_auth"] == proxy_tunnel.proxy_auth("u1", NEW_PASSWORD)
        assert _member_ids(docker, current) == [NAME] and docker.named(NAME).status == "running"


class TestReadinessIsReadUnderTheLock:
    def test_a_tunnel_that_restarted_after_the_heartbeat_read_it_starts_nothing(self, docker):
        """The heartbeat saw /run/ready; the tunnel restarted before recovery took the lock and has no exit yet."""
        _deploy("honeygain")
        earner = docker.named(NAME)
        tunnel = docker.named("cashpilot-tunnel-p3")
        earner.status = "exited"
        real_recover, real_ready = proxy_tunnel._recover, docker.ready
        restarted = {"on": False}

        def recover(*args, **kwargs):
            tunnel.restart()
            restarted["on"] = True
            return real_recover(*args, **kwargs)

        with (
            patch.object(docker, "ready", lambda c: not restarted["on"] and real_ready(c)),
            patch.object(proxy_tunnel, "_recover", side_effect=recover),
        ):
            _heartbeat()
        assert restarted["on"] and earner.status == "exited"
        _heartbeat()  # control: once the current run is ready, it starts
        assert earner.status == "running"


def _own_ip_read_fails(container):
    """The recorded own_ip is there, but Docker fails to hand it over (any error but "not there")."""
    real = container.get_archive

    def get_archive(path):
        if path.endswith("/own_ip"):
            raise APIError("500 Server Error: archive read timed out")
        return real(path)

    container.get_archive = get_archive


class TestAnUnreadableOwnIpIsNeverWrittenOver:
    """Taken for "none recorded", a recorded address that cannot be read was written over with an empty one,
    and cp-tunnel's leak guard lets any exit through when own_ip is empty, the box's own address too."""

    @pytest.mark.parametrize("password", [PASSWORD, NEW_PASSWORD])
    def test_a_stopped_tunnel_starts_and_keeps_the_recorded_address(self, docker, password):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        earner = docker.named(NAME)
        proxy_tunnel.start("honeygain", 3, _socks(), "198.51.100.7")
        proxy_tunnel.stop("honeygain", 3)
        assert tunnel.status == "exited" and tunnel.files["own_ip"] == "198.51.100.7"
        _own_ip_read_fails(tunnel)
        proxy_tunnel.start("honeygain", 3, _socks(password=password), None)
        assert tunnel.files["own_ip"] == "198.51.100.7"
        assert tunnel.files["proxy_auth"] == proxy_tunnel.proxy_auth("u1", password)
        assert tunnel.status == "running" and earner.status == "running" and docker.tunnels() == [tunnel]

    def test_a_running_tunnel_on_new_settings_is_left_as_it_was(self, docker):
        """Its settings could not be put back if the new ones failed, so nothing is changed."""
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        earner = docker.named(NAME)
        proxy_tunnel.start("honeygain", 3, _socks(), "198.51.100.7")
        files, starts = dict(tunnel.files), tunnel.starts
        _own_ip_read_fails(tunnel)
        with pytest.raises(proxy_tunnel.ProxyTunnelError, match="Could not read the tunnel's current settings"):
            _deploy("honeygain", _socks(password=NEW_PASSWORD))
        assert tunnel.files == files and tunnel.starts == starts and tunnel.status == "running"
        assert docker.named(NAME) is earner and earner.status == "running"

    def test_control_with_no_address_recorded_the_tunnel_starts_without_the_comparison(self, docker):
        """A first deploy with the address unknown: none recorded, none written, nothing to compare the exit with."""
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        proxy_tunnel.stop("honeygain", 3)
        del tunnel.files["own_ip"]  # "not there" (NotFound), never a failed read
        proxy_tunnel.start("honeygain", 3, _socks(password=NEW_PASSWORD), None)
        assert tunnel.status == "running" and tunnel.files["own_ip"] == ""
        assert docker.named(NAME).status == "running"


class TestABrokenTunnelIsReplacedWithTheAddressUnknown:
    """Docker refuses to read a broken tunnel's files as it refuses to write them. Refusing the start until its
    recorded address could be read left the tunnel and its copies down for good when the worker cannot tell its
    own address (CASHPILOT_EGRESS_DETECT=off)."""

    @pytest.mark.usefixtures("detection_off")
    @pytest.mark.parametrize("recorded", ["198.51.100.7", ""])
    def test_a_start_replaces_it_and_starts_its_copies(self, docker, recorded):
        _deploy("honeygain")
        _deploy("earnfm")
        old = docker.named("cashpilot-tunnel-p3")
        old.files["own_ip"] = recorded
        _break_tunnel(docker, old)
        proxy_tunnel.start("honeygain", 3, _socks(), None)
        (tunnel,) = docker.tunnels()
        assert tunnel.id != old.id and tunnel.status == "running"
        # The old address went with the container Docker cannot read; none is compared until a start knows it.
        assert tunnel.files.get("own_ip", "") == ""
        assert _member_ids(docker, tunnel) == ["cashpilot-earnfm-p3", "cashpilot-honeygain-p3"]
        assert docker.named(NAME).status == "running"
        _heartbeat()
        assert docker.named("cashpilot-earnfm-p3").status == "running"

    def test_control_a_known_address_reaches_the_replacement(self, docker):
        _deploy("honeygain")
        old = docker.named("cashpilot-tunnel-p3")
        _break_tunnel(docker, old)
        proxy_tunnel.start("honeygain", 3, _socks(), "198.51.100.9")
        (tunnel,) = docker.tunnels()
        assert tunnel.id != old.id and tunnel.files["own_ip"] == "198.51.100.9"

    def test_with_detection_on_a_lookup_that_failed_refuses_until_a_try_knows_the_address(self, docker):
        """The lookup failed this time (its failure is cached a while): a later start knows the address."""
        _deploy("honeygain")
        old = docker.named("cashpilot-tunnel-p3")
        old.files["own_ip"] = "198.51.100.7"
        _break_tunnel(docker, old)
        with pytest.raises(proxy_tunnel.ProxyTunnelError, match="Could not read the address"):
            proxy_tunnel.start("honeygain", 3, _socks(), None)
        assert docker.tunnels() == [old] and docker.named(NAME).attrs["HostConfig"]["NetworkMode"].endswith(old.id)
        proxy_tunnel.start("honeygain", 3, _socks(), "198.51.100.7")
        (tunnel,) = docker.tunnels()
        assert tunnel.id != old.id and tunnel.files["own_ip"] == "198.51.100.7"
        assert docker.named(NAME).status == "running"


class TestAHealthyTunnelIsNeverReplacedWithoutItsAddress:
    """A new tunnel image replaces a healthy tunnel (upgrade). One failed read of its recorded own_ip gave the new
    tunnel none, and cp-tunnel's leak guard then lets any exit through, the box's own address too; the old tunnel,
    which held the address, was removed."""

    @pytest.mark.parametrize("detection", ["on", "off"])
    def test_an_upgrade_is_refused_and_the_old_tunnel_kept(self, docker, monkeypatch, detection):
        if detection == "off":
            monkeypatch.setenv("CASHPILOT_EGRESS_DETECT", "off")
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        earner = docker.named(NAME)
        proxy_tunnel.start("honeygain", 3, _socks(), "198.51.100.7")
        _own_ip_read_fails(tunnel)
        with (
            patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": NEW_IMAGE}),
            pytest.raises(proxy_tunnel.ProxyTunnelError, match="Could not read the address"),
        ):
            _deploy("honeygain")
        assert docker.tunnels() == [tunnel] and tunnel.status == "running"
        assert tunnel.files["own_ip"] == "198.51.100.7" and tunnel.attrs["Config"]["Image"] == IMAGE
        assert docker.named(NAME) is earner and earner.status == "running"

    def test_control_the_upgrade_goes_through_once_the_address_reads(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        proxy_tunnel.start("honeygain", 3, _socks(), "198.51.100.7")
        with patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": NEW_IMAGE}):
            _deploy("honeygain")
        (new,) = docker.tunnels()
        assert new.id != tunnel.id and new.files["own_ip"] == "198.51.100.7"


class TestNoTunnelRestartsByItself:
    """A run Docker starts on its own has its interface and default route before cp-tunnel's first command loads
    the drop-all table, so an earner starting into it then sends from the box's own address. No tunnel has a
    restart policy now; the worker starts one only under the proxy's lock, which every earner start holds."""

    def test_a_shared_tunnel_has_no_restart_policy(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        assert tunnel.attrs["HostConfig"]["RestartPolicy"] == {"Name": "no"}

    def test_the_heartbeat_replaces_an_older_shared_tunnel_only(self, docker):
        _deploy("honeygain")
        legacy = _legacy_pair(docker, "earnfm", proxy_id=4)
        tunnel = docker.named("cashpilot-tunnel-p3")
        for c in (tunnel, legacy):
            _made_by_an_older_worker(c)
        _heartbeat()
        (new,) = [t for t in docker.tunnels() if t.name == "cashpilot-tunnel-p3"]
        assert new.id != tunnel.id and new.attrs["HostConfig"]["RestartPolicy"] == {"Name": "no"}
        # A legacy pair's stop by an older worker left no marker: Docker keeps deciding it.
        assert docker.named(legacy.name) is legacy
        assert legacy.attrs["HostConfig"]["RestartPolicy"] == {"Name": "unless-stopped"}
        assert docker.updates == []

    def test_a_tunnel_that_went_down_is_started_by_the_heartbeat_and_its_copies_once_it_is_ready(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        earner = docker.named(NAME)
        tunnel.stop()  # its tunnel process died; Docker does not start it again
        assert earner.status == "running"  # in a namespace with no interface left
        with patch.object(docker, "ready", return_value=False):
            _heartbeat()
            assert tunnel.status == "running" and earner.starts == 1  # nothing joins the run yet
        _heartbeat()
        assert earner.status == "running" and earner.starts == 2
        assert earner.attrs["State"]["StartedAt"] > tunnel.attrs["State"]["StartedAt"]

    def test_control_a_tunnel_whose_copies_are_all_held_stays_down(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        proxy_tunnel.stop("honeygain", 3)
        tunnel.stop()
        _heartbeat()
        assert tunnel.status == "exited" and docker.named(NAME).status == "exited"

    def test_a_tunnel_start_waits_for_the_proxys_lock(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        tunnel.stop()
        with proxy_tunnel._deploy_lock(3):
            _heartbeat()
            assert tunnel.status == "exited"
        _heartbeat()
        assert tunnel.status == "running"


def _made_by_an_older_worker(tunnel, image=IMAGE):
    """What a v2.5.0 worker left: unless-stopped, which the socket proxy will not let the worker take away."""
    tunnel.attrs["HostConfig"]["RestartPolicy"] = {"Name": "unless-stopped"}
    tunnel.attrs["Config"]["Image"] = image


OLD_IMAGE = "drumsergio/cashpilot-tunnel:2.1.0"


class TestAnOlderWorkersTunnelIsReplacedNeverReused:
    """The worker took the restart policy away with a container update, which the shipped socket proxy refuses on
    purpose: every tunnel an older worker made kept unless-stopped (and its old image) for good, so Docker could
    start a new run between the ready read and an earner's start. Such a tunnel is replaced now, and no earner
    starts in it meanwhile."""

    def _copies(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        old = docker.named("cashpilot-tunnel-p3")
        # A volume the earner's image declares, where it keeps its device id.
        honeygain = docker.named(NAME)
        honeygain.attrs["Mounts"] = [{"Type": "volume", "Name": "hg-data", "Destination": "/data", "RW": True}]
        proxy_tunnel.stop("earnfm", 3)
        _made_by_an_older_worker(old, OLD_IMAGE)
        return old

    def test_the_heartbeat_replaces_it_and_keeps_each_copy_as_it_was(self, docker):
        old = self._copies(docker)
        env = {n: list(docker.named(n).attrs["Config"]["Env"]) for n in (NAME, "cashpilot-earnfm-p3")}
        labels = {n: dict(docker.named(n).labels) for n in (NAME, "cashpilot-earnfm-p3")}
        _heartbeat()
        (new,) = docker.tunnels()
        assert new.id != old.id and new.name == "cashpilot-tunnel-p3"
        assert new.attrs["HostConfig"]["RestartPolicy"] == {"Name": "no"} and new.attrs["Config"]["Image"] == IMAGE
        assert new.files["proxy_auth"] == old.files["proxy_auth"] and new.files["own_ip"] == old.files["own_ip"]
        assert _member_ids(docker, new) == ["cashpilot-earnfm-p3", NAME]
        for n in (NAME, "cashpilot-earnfm-p3"):
            assert docker.named(n).attrs["Config"]["Env"] == [*env[n], "NVIDIA_VISIBLE_DEVICES=void"]
            assert docker.named(n).labels == labels[n]
        assert docker.named(NAME).kw["volumes"] == {"hg-data": {"bind": "/data", "mode": "rw"}}
        # The running copy started again in the new run, once it was ready; the stopped one stays stopped.
        assert docker.named(NAME).status == "running"
        assert docker.named(NAME).attrs["State"]["StartedAt"] > new.attrs["State"]["StartedAt"]
        assert docker.named("cashpilot-earnfm-p3").status != "running"
        assert proxy_tunnel.held() == {"cashpilot-earnfm-p3"}
        assert docker.updates == []
        _heartbeat()  # done once: the next beat leaves it as it is
        assert docker.tunnels() == [new]

    def test_a_deploy_before_the_first_heartbeat_replaces_it_first(self, docker):
        old = self._copies(docker)
        _deploy("repocket")
        (new,) = docker.tunnels()
        assert new.id != old.id and new.attrs["HostConfig"]["RestartPolicy"] == {"Name": "no"}
        assert _member_ids(docker, new) == ["cashpilot-earnfm-p3", NAME, "cashpilot-repocket-p3"]
        assert docker.named("cashpilot-repocket-p3").status == "running"
        assert docker.named(NAME).status == "running" and docker.named("cashpilot-earnfm-p3").status != "running"

    def test_a_redeploy_of_its_only_copy_replaces_it_and_keeps_the_old_one_until_it_runs(self, docker):
        _deploy("honeygain")
        old = docker.named("cashpilot-tunnel-p3")
        _made_by_an_older_worker(old)  # its image is current: only the policy tells it apart
        _deploy("honeygain")
        (new,) = docker.tunnels()
        assert new.id != old.id and new.attrs["HostConfig"]["RestartPolicy"] == {"Name": "no"}
        assert _member_ids(docker, new) == [NAME] and docker.named(NAME).status == "running"

    @pytest.mark.parametrize("settings", ["current UI", "older UI"])
    def test_a_start_before_the_first_heartbeat_replaces_it_first(self, docker, settings):
        old = self._copies(docker)
        proxy_tunnel.stop("honeygain", 3)
        assert old.status == "exited"
        proxy_tunnel.start("earnfm", 3, _socks() if settings == "current UI" else None, None)
        (new,) = docker.tunnels()
        assert new.id != old.id and new.attrs["HostConfig"]["RestartPolicy"] == {"Name": "no"}
        assert docker.named("cashpilot-earnfm-p3").status == "running"
        assert docker.named("cashpilot-earnfm-p3").attrs["HostConfig"]["NetworkMode"] == f"container:{new.id}"
        assert docker.named(NAME).status != "running" and proxy_tunnel.held() == {NAME}

    def test_no_earner_starts_in_it_while_it_cannot_be_replaced(self, docker):
        old = self._copies(docker)
        earner = docker.named(NAME)
        earner.stop()  # its own crash: the heartbeat would start it again
        real_start_sidecar = proxy_tunnel.start_sidecar

        tries = []

        def no_exit(*a, **kw):
            tries.append(a[1])
            raise proxy_tunnel.ProxyTunnelError("The tunnel did not reach the internet through the proxy")

        with patch.object(proxy_tunnel, "start_sidecar", no_exit):
            _heartbeat()
            _heartbeat()  # a failed try waits a few minutes for the next: the heartbeat is never held up each beat
        assert tries == ["cashpilot-tunnel-p3-next"]
        assert docker.tunnels() == [old] and earner.status == "exited" and earner.starts == 1
        assert proxy_tunnel._start_in_ready_run(earner, old, "honeygain") is False
        proxy_tunnel._replace_failed.clear()  # those minutes later
        with patch.object(proxy_tunnel, "start_sidecar", real_start_sidecar):
            _heartbeat()  # control: once the replacement proves its exit, the copy runs again
        (new,) = docker.tunnels()
        assert new.id != old.id and docker.named(NAME).status == "running"

    def test_one_that_is_down_is_replaced_never_started_as_it_is(self, docker):
        old = self._copies(docker)
        old.stop()
        starts = old.starts
        with proxy_tunnel._deploy_lock(3):
            _heartbeat()  # the lock is busy: neither replaced nor started
        assert old.status == "exited" and old.starts == starts
        _heartbeat()
        (new,) = docker.tunnels()
        assert new.id != old.id and new.status == "running"
        _heartbeat()
        assert docker.named(NAME).status == "running"

    def test_one_per_beat_so_the_heartbeat_is_late_by_one_at_most(self, docker):
        old = self._copies(docker)
        _deploy("honeygain", proxy_id=4)
        other = docker.named("cashpilot-tunnel-p4")
        _made_by_an_older_worker(other, OLD_IMAGE)
        _heartbeat()
        assert sum(t.id in (old.id, other.id) for t in docker.tunnels()) == 1
        _heartbeat()
        assert {t.name for t in docker.tunnels()} == {"cashpilot-tunnel-p3", "cashpilot-tunnel-p4"}
        assert not {old.id, other.id} & {t.id for t in docker.tunnels()}

    def test_a_running_one_with_no_exit_is_left_as_it_is(self, docker):
        """A new tunnel on its settings would have none either: no try holds the heartbeat up for nothing."""
        old = self._copies(docker)
        with (
            patch.object(docker, "ready", return_value=False),
            patch.object(proxy_tunnel, "start_sidecar", side_effect=AssertionError("tried")) as start_sidecar,
        ):
            _heartbeat()
        start_sidecar.assert_not_called()
        assert docker.tunnels() == [old]

    def test_control_one_whose_copies_are_all_stopped_waits_for_a_start(self, docker):
        old = self._copies(docker)
        proxy_tunnel.stop("honeygain", 3)
        _heartbeat()
        assert docker.tunnels() == [old] and old.status == "exited"

    def test_one_with_a_copy_a_redeploy_left_aside_waits_until_that_is_settled(self, docker):
        old = self._copies(docker)
        aside = docker.named("cashpilot-earnfm-p3")
        aside.rename("cashpilot-earnfm-p3" + orchestrator.REPLACED_SUFFIX)
        with patch.object(proxy_tunnel, "_settle_replaced_unless_busy"):
            _heartbeat()
        assert old in docker.tunnels() and docker.named(aside.name) is aside


class TestAStopIsNeverUndoneByATunnelStart:
    """_status read the stop markers once, without the proxy's lock, and _start_down_tunnel did not read them
    again: a Stop between the two left a tunnel running with no copy that should run in it."""

    def test_a_stop_between_the_read_and_the_tunnel_start_wins(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        tunnel.stop()  # its tunnel process died; the copy should still run
        real = proxy_tunnel._failed_or_unknown

        def stop_lands_now(earner):
            proxy_tunnel.stop("honeygain", 3)  # the owner presses Stop right after the heartbeat's read
            return real(earner)

        with patch.object(proxy_tunnel, "_failed_or_unknown", stop_lands_now):
            _heartbeat()
        assert proxy_tunnel.held() == {NAME}
        assert tunnel.status == "exited" and docker.named(NAME).status == "exited"

    def test_control_with_no_stop_the_tunnel_starts(self, docker):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        tunnel.stop()
        _heartbeat()
        assert tunnel.status == "running"


class TestEveryEarnerStartReadsTheRun:
    """_clone_into and _put_back started an earner with a bare start(), with no look at the run it joined."""

    def test_a_clone_is_not_started_in_a_run_that_restarted_before_it(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        old = docker.named("cashpilot-tunnel-p3")
        docker.broken.add(old.id)  # it runs, but Docker can no longer write to or start it: replaced
        real_create, real_ready = docker.create, docker.ready
        restarted = {"on": False}

        def create(**kw):
            c = real_create(**kw)
            if kw["name"].endswith(proxy_tunnel.STAGED_SUFFIX) and kw["labels"].get(LABEL_ROLE) != "tunnel":
                real_rename = c.rename

                def rename(name):
                    real_rename(name)
                    if not restarted["on"]:
                        # The new tunnel restarts just before the first clone would start.
                        docker.by_id[kw["network_mode"].removeprefix("container:")].restart()
                        restarted["on"] = True

                c.rename = rename
            return c

        with (
            patch.object(docker, "create", side_effect=create),
            patch.object(docker, "ready", lambda c: not restarted["on"] and real_ready(c)),
            pytest.raises(proxy_tunnel.ProxyTunnelError, match="was not started"),
        ):
            proxy_tunnel.start("honeygain", 3, _socks(password=NEW_PASSWORD), None)
        (tunnel,) = docker.tunnels()
        assert restarted["on"] and tunnel.id != old.id
        assert _member_ids(docker, tunnel) == ["cashpilot-earnfm-p3", NAME]
        assert {docker.named(n).status for n in ("cashpilot-earnfm-p3", NAME)} == {"created"}
        _heartbeat()  # control: the run is ready now
        assert {docker.named(n).status for n in ("cashpilot-earnfm-p3", NAME)} == {"running"}

    @pytest.mark.parametrize("ready", [False, True])
    def test_a_copy_put_back_starts_only_in_a_ready_run(self, docker, ready):
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        earner = docker.named(NAME)
        earner.stop()
        earner.rename(NAME + proxy_tunnel.MOVING_SUFFIX)
        with patch.object(docker, "ready", return_value=ready):
            proxy_tunnel._put_back(docker, earner, NAME, True)
        assert earner.name == NAME and tunnel.status == "running"
        assert earner.status == ("running" if ready else "exited")


def _tunnel_restarts_on_start(tunnel, earner, *, then_reload_fails=False):
    """The earner's start races a restart of its tunnel (by hand: Docker starts none by itself)."""
    real_start, real_reload = earner.start, tunnel.reload
    state = {"started": False}

    def start():
        tunnel.attrs["State"]["StartedAt"] = "9999-01-01T00:00:00Z"  # a new run of the tunnel
        state["started"] = True
        real_start()

    def reload():
        if then_reload_fails and state["started"]:
            raise APIError("500 Server Error: read timed out")
        real_reload()

    earner.start = start
    tunnel.reload = reload
    return state


class TestAnEarnerNeverStaysInAnUnprovenRun:
    def test_a_failed_check_after_the_start_stops_the_earner(self, docker):
        """The tunnel restarted during the start, and the read after it failed: the run is not proven."""
        _deploy("honeygain")
        earner = docker.named(NAME)
        tunnel = docker.named("cashpilot-tunnel-p3")
        earner.stop()
        state = _tunnel_restarts_on_start(tunnel, earner, then_reload_fails=True)
        proxy_tunnel._start_when_ready(earner, tunnel, "honeygain", ready=True)
        assert state["started"] and earner.status == "exited"

    def test_a_user_start_that_races_a_tunnel_restart_stops_the_earner(self, docker):
        _deploy("honeygain")
        earner = docker.named(NAME)
        tunnel = docker.named("cashpilot-tunnel-p3")
        proxy_tunnel.stop("honeygain", 3)
        state = _tunnel_restarts_on_start(tunnel, earner)
        with pytest.raises(proxy_tunnel.ProxyTunnelError, match="was not started"):
            proxy_tunnel.start("honeygain", 3, _socks(), None)
        assert state["started"] and earner.status == "exited"
        assert NAME not in proxy_tunnel.held()  # the heartbeat starts it once the run it is in is ready

    def test_a_restart_into_a_tunnel_on_new_settings_that_races_a_restart_stops_the_earner(self, docker):
        """_restart_members: the tunnel restarted in place for new settings, then once more by itself."""
        _deploy("honeygain")
        earner = docker.named(NAME)
        tunnel = docker.named("cashpilot-tunnel-p3")
        real_start, real_ready = earner.start, docker.ready
        new_run = {"on": False}

        def start():  # restart() calls start()
            tunnel.attrs["State"]["StartedAt"] = "9999-01-01T00:00:00Z"  # its new run has no exit yet
            new_run["on"] = True
            real_start()

        earner.start = start
        with (
            patch.object(docker, "ready", lambda c: not (c is tunnel and new_run["on"]) and real_ready(c)),
            pytest.raises(proxy_tunnel.ProxyTunnelError, match="was not started"),
        ):
            proxy_tunnel.start("honeygain", 3, _socks(password=NEW_PASSWORD), None)
        assert tunnel.files["proxy_auth"] == proxy_tunnel.proxy_auth("u1", NEW_PASSWORD)
        assert new_run["on"] and earner.status == "exited"

    @pytest.mark.parametrize("settings_sent", [True, False])
    def test_control_a_start_on_a_steady_run_starts_the_earner(self, docker, settings_sent):
        _deploy("honeygain")
        earner = docker.named(NAME)
        proxy_tunnel.stop("honeygain", 3)
        proxy_tunnel.start("honeygain", 3, _socks() if settings_sent else None, None)
        assert earner.status == "running"

    def test_the_heartbeat_stops_an_earner_running_in_a_run_not_ready(self, docker):
        """Started into the tunnel's current run, which never wrote /run/ready: stopped, then started once ready."""
        _deploy("honeygain")
        earner = docker.named(NAME)
        tunnel = docker.named("cashpilot-tunnel-p3")
        tunnel.restart()
        earner.restart()  # joined the new run before anyone proved it
        with patch.object(docker, "ready", return_value=False):
            _heartbeat()
            assert earner.status == "exited" and NAME not in proxy_tunnel.held()
        _heartbeat()
        assert earner.status == "running"

    def test_control_the_heartbeat_leaves_an_earner_in_the_old_run(self, docker):
        """Started before the tunnel's current run, it sits in the old namespace, which has no way out."""
        _deploy("honeygain")
        earner = docker.named(NAME)
        tunnel = docker.named("cashpilot-tunnel-p3")
        tunnel.restart()
        with patch.object(docker, "ready", return_value=False):
            _heartbeat()
            assert earner.status == "running" and earner.starts == 1
        _heartbeat()  # ready: restarted into the new run
        assert earner.status == "running" and earner.starts == 2


def _tunnel_exec_fails(tunnel, times=None):
    """``docker exec`` into the tunnel raises (a busy daemon, an exec timeout): /run/ready is not known, not absent."""
    real = tunnel.exec_run
    left = {"n": times}

    def exec_run(*args, **kwargs):
        if left["n"] is None or left["n"] > 0:
            if left["n"] is not None:
                left["n"] -= 1
            raise APIError("500 Server Error: exec timed out")
        return real(*args, **kwargs)

    tunnel.exec_run = exec_run


class TestAReadyFileNotReadStopsNothing:
    """A False the heartbeat got from a failed read, or from a run that has ended, is not "this run never proved an
    exit": stopping on it took every copy in a healthy tunnel down for a beat."""

    @pytest.mark.parametrize("times", [1, None], ids=["once", "every-time"])
    def test_a_failed_exec_into_a_proven_tunnel_leaves_its_copies_running(self, docker, times):
        _deploy("honeygain")
        _deploy("earnfm")
        tunnel = docker.named("cashpilot-tunnel-p3")
        copies = [docker.named(NAME), docker.named("cashpilot-earnfm-p3")]
        starts = [c.starts for c in copies]
        _tunnel_exec_fails(tunnel, times)
        _heartbeat()
        assert [c.status for c in copies] == ["running", "running"]
        assert [c.starts for c in copies] == starts and not [e for e in docker.events if e[0] == "stop"]

    def test_a_stale_false_from_a_run_that_since_proved_its_exit_stops_nothing(self, docker):
        """status() read the tunnel mid-restart; a user start then started the earner in the new, proven run."""
        _deploy("honeygain")
        earner = docker.named(NAME)
        tunnel = docker.named("cashpilot-tunnel-p3")
        proxy_tunnel._start_when_ready(earner, tunnel, "honeygain", ready=False)
        assert earner.status == "running" and earner.starts == 1

    def test_control_a_run_that_answers_it_has_no_ready_file_still_stops_the_earner(self, docker):
        _deploy("honeygain")
        earner = docker.named(NAME)
        tunnel = docker.named("cashpilot-tunnel-p3")
        tunnel.restart()
        earner.restart()  # joined the new run before anyone proved it
        with patch.object(docker, "ready", return_value=False):  # cat /run/ready exits 1
            proxy_tunnel._start_when_ready(earner, tunnel, "honeygain", ready=False)
        assert earner.status == "exited"


def _fail_create(docker, name):
    """Docker refuses to create the container ``name`` (a clone in the way, a timed-out create)."""
    real = docker.create

    def create(**kw):
        if kw["name"] == name:
            raise APIError("500 Server Error: create timed out")
        return real(**kw)

    return patch.object(docker, "create", side_effect=create)


def _older_tunnel_retired_beside_a_current_one(docker):
    """honeygain in an older worker's tunnel kept under the retired name (a redeploy that did not finish), while
    earnfm holds the name in a tunnel this worker made, so the old one cannot get its name back."""
    _deploy("honeygain")
    _deploy("earnfm")
    old = docker.named("cashpilot-tunnel-p3")
    old.rename("cashpilot-tunnel-p3" + proxy_tunnel.RETIRED_SUFFIX)
    current, _ = proxy_tunnel.start_sidecar(
        docker, "cashpilot-tunnel-p3", proxy_tunnel.SHARED_SLUG, 3, _socks(), None, label=proxy_tunnel.shared_label(3)
    )
    proxy_tunnel._clone_into(docker, docker.named("cashpilot-earnfm-p3"), current)
    _made_by_an_older_worker(old)
    return old, current


@pytest.mark.parametrize("journal", ["kept", "first"])
@pytest.mark.parametrize("trigger", ["start", "heartbeat"])
def test_recovery_conflict_preserves_an_unrecorded_holder(docker, journal, trigger, caplog):
    _deploy("honeygain" if journal == "kept" else "earnfm")
    tunnel = docker.named("cashpilot-tunnel-p3")
    if journal == "kept":
        old = docker.named(NAME)
        old.stop()
        old.rename(NAME + orchestrator.REPLACED_SUFFIX)
        proxy_tunnel._set_kept(old.id, True, strict=True)
    else:
        proxy_tunnel._set_new(NAME, True, strict=True)
    _fake_deploy_raw(docker)(
        slug="honeygain",
        image="honeygain/honeygain:1",
        env={},
        labels={LABEL_PROXY: "3"},
        network_mode=f"container:{tunnel.id}",
        name=NAME,
    )
    changed = docker.named(NAME)
    if trigger == "start":
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(worker_api, "_validate_proxy"),
            patch.object(worker_api, "_own_egress_ip", AsyncMock(return_value=None)),
        ):
            reply = TestClient(worker_api.app).post(
                "/api/proxied/honeygain/3/start-checked", json={"proxy": _socks(), "expected_container": changed.id}
            )
        assert reply.status_code == 409, reply.text
    else:
        row = next(e for e in _heartbeat() if e["slug"] == "honeygain")
        assert "Recovery skipped" in row.get("recovery_skipped", "")
        assert "Recovery skipped" in caplog.text
    assert docker.named(NAME) is changed and changed.status == "running"


def test_checked_start_can_approve_two_pre_upgrade_copies_together(docker):
    _deploy("honeygain")
    _deploy("earnfm")
    _made_by_an_older_worker(docker.named("cashpilot-tunnel-p3"))
    os.unlink(proxy_tunnel.CONTAINER_MARKER)
    slugs = ("honeygain", "earnfm")
    ids = {slug: docker.named(proxy_tunnel.earner_name(slug, 3)).id for slug in slugs}
    for slug in slugs:
        proxy_tunnel.stop(slug, 3)

    with (
        patch.object(worker_api, "_verify_api_key"),
        patch.object(worker_api, "_validate_proxy"),
        patch.object(worker_api, "_own_egress_ip", AsyncMock(return_value=None)),
    ):
        client = TestClient(worker_api.app)
        path = "/api/proxied/honeygain/3/start-checked"
        question = client.post(path, json={"proxy": _socks(), "expected_container": ids["honeygain"]})
        assert question.status_code == 409
        assert question.json()["detail"]["expected_containers"] == ids
        assert all(docker.named(proxy_tunnel.earner_name(slug, 3)).id == cid for slug, cid in ids.items())
        reply = client.post(path, json={"proxy": _socks(), "expected_containers": ids})
        assert reply.status_code == 200, reply.text
        neighbor = docker.named(proxy_tunnel.earner_name("earnfm", 3))
        assert neighbor.status not in ("running", "restarting")
        assert str(neighbor.name) in proxy_tunnel.held()
        reply = client.post(
            "/api/proxied/earnfm/3/start-checked", json={"proxy": _socks(), "expected_container": neighbor.id}
        )
        assert reply.status_code == 200, reply.text
    assert all(docker.named(proxy_tunnel.earner_name(slug, 3)).status == "running" for slug in slugs)


class TestAnOlderWorkersTunnelReplacementFollowups:
    def test_recovery_skips_a_copy_with_a_changed_container_id(self, docker, caplog):
        _deploy("honeygain")
        old = docker.named("cashpilot-tunnel-p3")
        _made_by_an_older_worker(old)
        original = docker.named(NAME)
        original.remove(force=True)
        _fake_deploy_raw(docker)(
            slug="honeygain",
            image="honeygain/honeygain:1",
            env={},
            network_mode=f"container:{old.id}",
            labels={LABEL_PROXY: "3"},
            name=NAME,
        )
        replacement = docker.named(NAME)
        (entry,) = _heartbeat()

        assert docker.named(NAME) is replacement and replacement.status == "running"
        assert docker.tunnels() == [old]
        assert "Recovery skipped" in caplog.text
        assert "container ID" in entry["recovery_skipped"]

    def test_worker_start_checks_the_exact_id_before_moving_a_legacy_copy(self, docker):
        _legacy_pair(docker, "honeygain", proxy=_socks())
        earner = docker.named(NAME)
        path = "/api/proxied/honeygain/3/start"
        body = {"proxy": _socks(), "expected_container": "b" * 64}
        with (
            patch.object(worker_api, "_verify_api_key"),
            patch.object(worker_api, "_validate_proxy"),
            patch.object(worker_api, "_own_egress_ip", AsyncMock(return_value=None)),
        ):
            client = TestClient(worker_api.app)
            reply = client.post(path, json=body)
            assert reply.status_code == 409, reply.text
            assert reply.json()["detail"]["error"] == "deploy_target_changed"
            assert reply.json()["detail"]["current_container"] == earner.id
            assert docker.named(NAME) is earner
            reply = client.post(path, json={**body, "expected_container": earner.id})
            assert reply.status_code == 200, reply.text
            assert docker.named(NAME).id != earner.id

    def test_copies_moved_before_a_failure_stay_running_in_the_new_tunnel_never_recreated_twice(self, docker):
        """Moved back into the older tunnel, where no earner starts, each copy was recreated a second time and left
        stopped, and the heartbeat did it again every five minutes while the other copy's fault lasted."""
        _deploy("honeygain")
        _deploy("earnfm")
        old = docker.named("cashpilot-tunnel-p3")
        _made_by_an_older_worker(old)
        earnfm = docker.named("cashpilot-earnfm-p3")
        with _fail_create(docker, "cashpilot-earnfm-p3" + proxy_tunnel.STAGED_SUFFIX):
            _heartbeat()
            staged = docker.named("cashpilot-tunnel-p3" + proxy_tunnel.STAGED_SUFFIX)
            moved = docker.named(NAME)
            assert staged is not None and moved.status == "running"
            assert moved.attrs["HostConfig"]["NetworkMode"] == f"container:{staged.id}"
            assert docker.named("cashpilot-earnfm-p3") is earnfm and earnfm.status == "running"
            assert earnfm.attrs["HostConfig"]["NetworkMode"] == f"container:{old.id}"
            _heartbeat()  # the next beat recreates nothing
            assert docker.named(NAME) is moved and moved.status == "running"
        staged.attrs["Created"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        _heartbeat()  # the change is finished once it is stale, with the fault gone
        (tunnel,) = docker.tunnels()
        assert tunnel.id == staged.id and tunnel.name == "cashpilot-tunnel-p3"
        assert _member_ids(docker, tunnel) == ["cashpilot-earnfm-p3", NAME]
        assert docker.named(NAME) is moved and docker.named("cashpilot-earnfm-p3").status == "running"

    @pytest.mark.parametrize("settings", ["current UI", "older UI"])
    def test_a_start_of_a_copy_in_a_retired_older_tunnel_moves_it_into_the_tunnel_under_the_name(
        self, docker, settings
    ):
        """The older-UI start read readiness from the tunnel under the name while the earner joined the retired
        one, which may sit in a run nobody proved; the current-UI start restarted the retired one in place and then
        refused to start the earner in it, for good."""
        old, current = _older_tunnel_retired_beside_a_current_one(docker)
        files = dict(current.files)
        docker.named(NAME).stop()  # its own crash
        real_ready = docker.ready
        with patch.object(docker, "ready", lambda c: c is not old and real_ready(c)):  # restarted, not proved yet
            proxy_tunnel.start("honeygain", 3, _socks() if settings == "current UI" else None, None)
        earner = docker.named(NAME)
        assert earner.status == "running"
        assert earner.attrs["HostConfig"]["NetworkMode"] == f"container:{current.id}"
        assert docker.tunnels() == [current] and current.files == files

    def test_the_heartbeat_moves_a_copy_out_of_a_retired_older_tunnel(self, docker):
        old, current = _older_tunnel_retired_beside_a_current_one(docker)
        docker.named(NAME).stop()  # its own crash: the heartbeat should start it again
        _heartbeat()
        _heartbeat()
        earner = docker.named(NAME)
        assert earner.status == "running"
        assert earner.attrs["HostConfig"]["NetworkMode"] == f"container:{current.id}"
        assert docker.tunnels() == [current]

    def test_a_start_refuses_an_earner_that_is_not_in_the_tunnel_proved_ready(self, docker):
        old, current = _older_tunnel_retired_beside_a_current_one(docker)
        docker.named(NAME).stop()
        with (
            patch.object(proxy_tunnel, "_replace_restarting", return_value=(current, EXIT)),
            pytest.raises(proxy_tunnel.ProxyTunnelError, match="not in the tunnel that was proved ready"),
        ):
            proxy_tunnel.start("honeygain", 3, None, None)
        assert docker.named(NAME).status == "exited"

    def test_a_copy_with_a_host_device_is_never_carried_into_a_tunnel(self, docker):
        """The worker API gives a proxied copy no host devices (_validate_proxied). The move carried every device
        Docker recorded into the new tunnel's namespace, so a copy that got one some other way kept it there."""
        _deploy("honeygain")
        old = docker.named("cashpilot-tunnel-p3")
        _made_by_an_older_worker(old)
        earner = docker.named(NAME)
        earner.attrs["HostConfig"]["Devices"] = [
            {"PathOnHost": "/dev/dri/renderD128", "PathInContainer": "/dev/dri/card0", "CgroupPermissions": "r"},
        ]
        _heartbeat()
        assert docker.named(NAME) is earner and earner.status == "running"
        assert earner.attrs["HostConfig"]["NetworkMode"] == f"container:{old.id}"
        assert docker.tunnels() == [old]
        assert sorted(c.name for c in docker.by_id.values()) == ["cashpilot-honeygain-p3", "cashpilot-tunnel-p3"]
        with pytest.raises(proxy_tunnel.ProxyTunnelError, match="host devices"):
            proxy_tunnel._clone_into(docker, earner, old)
        assert docker.named(NAME + proxy_tunnel.STAGED_SUFFIX) is None and earner.status == "running"

    def test_the_heartbeat_replacement_bounds_its_image_pull(self, docker):
        _deploy("honeygain")
        _made_by_an_older_worker(docker.named("cashpilot-tunnel-p3"))
        real = proxy_tunnel.start_sidecar
        deadlines = []

        def start_sidecar(*a, **kw):
            deadlines.append(kw.get("deadline"))
            return real(*a, **kw)

        with patch.object(proxy_tunnel, "start_sidecar", side_effect=start_sidecar):
            began = time.monotonic()
            _heartbeat()
        assert deadlines and deadlines[0] is not None
        assert deadlines[0] <= began + proxy_tunnel.REPLACE_PULL_SECONDS + 1

    @pytest.mark.real_background_replacement
    def test_the_heartbeat_is_never_held_up_by_a_replacement(self, docker):
        """One try waits for an image pull, the new tunnel's exit and each copy's stop: minutes, past the UI's
        offline threshold, when the heartbeat ran it in place."""
        _deploy("honeygain")
        old = docker.named("cashpilot-tunnel-p3")
        _made_by_an_older_worker(old)
        real = proxy_tunnel.start_sidecar
        go, tries = threading.Event(), []

        def slow_start_sidecar(*a, **kw):
            tries.append(a[1])
            go.wait(5)
            return real(*a, **kw)

        with patch.object(proxy_tunnel, "start_sidecar", side_effect=slow_start_sidecar):
            began = time.monotonic()
            report = _heartbeat()
            _heartbeat()  # no second try while one runs
            took = time.monotonic() - began
            go.set()
            assert took < 2, took
            for _ in range(500):
                if not proxy_tunnel._replacing.locked():
                    break
                _real_sleep(0.01)
        assert [e["name"] for e in report] == [NAME]
        assert tries == ["cashpilot-tunnel-p3" + proxy_tunnel.STAGED_SUFFIX]
        (new,) = docker.tunnels()
        assert new.id != old.id and docker.named(NAME).status == "running"

    def test_a_reading_that_waits_for_a_change_moving_copies_gives_up_and_the_heartbeat_goes_out(self, docker):
        _deploy("honeygain")
        outcome = {}

        def read():
            try:
                outcome["report"] = _heartbeat()
            except proxy_tunnel.ProxyTunnelError as exc:
                outcome["error"] = str(exc)

        with patch.object(proxy_tunnel, "STATUS_SWAP_WAIT", 0.05), proxy_tunnel._swap_lock:
            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            reader.join(3)
            assert not reader.is_alive()
        assert "moving copies" in outcome["error"]
        assert [e["name"] for e in _heartbeat()] == [NAME]  # control: free again, read again


class TestALegacyPairNeverStartsInATunnelThatRestartsByItself:
    """A legacy pair's tunnel keeps Docker's restart policy: an earner started in it could join a run Docker started
    between the ready read and the start, and the check after the start stops it only after it sent."""

    def test_the_heartbeat_moves_a_pair_whose_copy_must_start_into_the_shared_tunnel(self, docker):
        legacy = _legacy_pair(docker, "earnfm", proxy_id=4)
        _made_by_an_older_worker(legacy)
        earner = docker.named("cashpilot-earnfm-p4")
        earner.stop()  # its own crash
        starts = earner.starts
        _heartbeat()
        _heartbeat()
        assert earner.starts == starts  # never started where it was
        (shared,) = docker.tunnels()
        assert shared.name == "cashpilot-tunnel-p4" and shared.attrs["HostConfig"]["RestartPolicy"] == {"Name": "no"}
        clone = docker.named("cashpilot-earnfm-p4")
        assert clone.attrs["HostConfig"]["NetworkMode"] == f"container:{shared.id}" and clone.status == "running"

    def test_a_start_from_an_older_ui_moves_the_pair_into_the_shared_tunnel_first(self, docker):
        legacy = _legacy_pair(docker, "earnfm", proxy_id=4)
        _made_by_an_older_worker(legacy)
        proxy_tunnel.stop("earnfm", 4)
        earner = docker.named("cashpilot-earnfm-p4")
        starts = earner.starts
        proxy_tunnel.start("earnfm", 4, None, None)
        assert earner.starts == starts
        (shared,) = docker.tunnels()
        clone = docker.named("cashpilot-earnfm-p4")
        assert clone.attrs["HostConfig"]["NetworkMode"] == f"container:{shared.id}" and clone.status == "running"
        assert proxy_tunnel.held() == set()

    def test_no_earner_start_reaches_docker_in_such_a_tunnel(self, docker):
        legacy = _legacy_pair(docker, "earnfm", proxy_id=4)
        _made_by_an_older_worker(legacy)
        earner = docker.named("cashpilot-earnfm-p4")
        earner.stop()

        def start():
            raise AssertionError("started in a tunnel Docker restarts on its own")

        earner.start = earner.restart = start
        with proxy_tunnel._deploy_lock(4):
            assert proxy_tunnel._start_in_ready_run(earner, legacy, "earnfm") is False

    def test_control_a_running_pair_is_left_where_it_is(self, docker):
        legacy = _legacy_pair(docker, "earnfm", proxy_id=4)
        _made_by_an_older_worker(legacy)
        earner = docker.named("cashpilot-earnfm-p4")
        _heartbeat()
        assert docker.tunnels() == [legacy] and docker.named("cashpilot-earnfm-p4") is earner


class TestTheGuaranteesThatHadNoTest:
    def test_an_older_tunnel_that_is_down_is_never_started_as_it_is_while_its_replacement_fails(self, docker):
        _deploy("honeygain")
        old = docker.named("cashpilot-tunnel-p3")
        _made_by_an_older_worker(old)
        old.stop()
        starts = old.starts
        with patch.object(proxy_tunnel, "start_sidecar", side_effect=proxy_tunnel.ProxyTunnelError("no exit")):
            _heartbeat()
        with patch.object(proxy_tunnel, "_start_down_tunnel", wraps=proxy_tunnel._start_down_tunnel) as spy:
            _heartbeat()  # the replacement waits a few minutes for its next try
        spy.assert_not_called()
        proxy_tunnel._start_down_tunnel(old, "3", NAME)
        assert old.status == "exited" and old.starts == starts

    def test_legacy_pairs_move_into_the_replacement_of_an_older_shared_tunnel_that_is_ready(self, docker):
        _deploy("honeygain")
        old = docker.named("cashpilot-tunnel-p3")
        _made_by_an_older_worker(old)
        _legacy_pair(docker, "earnfm", proxy=_socks())
        assert sorted(proxy_tunnel.migrate_legacy()) == ["cashpilot-earnfm-p3"]
        (shared,) = docker.tunnels()
        assert shared.id != old.id and shared.attrs["HostConfig"]["RestartPolicy"] == {"Name": "no"}
        assert _member_ids(docker, shared) == ["cashpilot-earnfm-p3", NAME]
        assert {docker.named(n).status for n in ("cashpilot-earnfm-p3", NAME)} == {"running"}


def _folder_fsync(err: int | None, folders: list | None = None):
    """os.fsync that fails with ``err`` on a folder (None: works), and counts each folder flush in ``folders``."""
    real = os.fsync

    def fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            if folders is not None:
                folders.append(fd)
            if err is not None:
                raise OSError(err, os.strerror(err))
        return real(fd)

    return patch.object(proxy_tunnel.os, "fsync", side_effect=fsync)


class TestARecordThatCannotBeFlushed:
    def test_a_stop_whose_record_cannot_be_flushed_still_stops_the_copy(self, docker):
        """The stop raised before it stopped anything, and every retry of the cap raised again: the copy kept
        spending the metered proxy past its cap until the disk could flush its folder."""
        _deploy("honeygain")
        tunnel = docker.named("cashpilot-tunnel-p3")
        with _folder_fsync(errno.EIO):
            first = proxy_tunnel.stop("honeygain", 3)
            again = proxy_tunnel.stop("honeygain", 3)
        assert proxy_tunnel.held() == {NAME}
        assert docker.named(NAME).status == "exited" and tunnel.status == "exited"
        assert first["was_running"] is True and first["durable"] is False
        assert "was stopped, but the stop may not survive a power cut" in first["warning"]
        assert again["was_running"] is False and again["durable"] is False
        # Control: once the folder flushes, the stop is durable again.
        assert proxy_tunnel.stop("honeygain", 3) == {"was_running": False}

    def test_a_stop_whose_record_cannot_be_flushed_is_a_stop_for_the_cap(self, docker):
        """The stop answered 409 although it had stopped the copy: the cap read that as "could not stop" and never
        marked the copy, and its second try found it already held (was_running False) and skipped the mark too, so
        the monthly reset never started it again."""
        _deploy("honeygain")
        with _folder_fsync(errno.EIO), patch.object(worker_api, "_verify_api_key"):
            resp = TestClient(worker_api.app, raise_server_exceptions=False).post("/api/proxied/honeygain/3/stop")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "stopped" and body["was_running"] is True and body["durable"] is False
        assert docker.named(NAME).status == "exited"

    def test_a_legacy_stop_whose_record_cannot_be_flushed_still_stops_the_pair(self, docker):
        legacy = _legacy_pair(docker, "honeygain")
        with _folder_fsync(errno.EIO):
            out = proxy_tunnel.stop("honeygain", 3)
        assert out["was_running"] is True and out["durable"] is False
        assert legacy.status == "exited" and docker.named(NAME).status == "exited"

    def test_a_filesystem_that_never_flushes_a_folder_still_deploys_starts_and_stops(self, docker):
        """EINVAL on a folder is what some network and shared-folder filesystems always answer: raising broke every
        deploy, start and stop there."""
        with _folder_fsync(errno.EINVAL):
            _deploy("honeygain")
            assert docker.named(NAME).status == "running"
            proxy_tunnel.stop("honeygain", 3)
            assert proxy_tunnel.held() == {NAME} and docker.named(NAME).status == "exited"
            proxy_tunnel.start("honeygain", 3, _socks(), None)
        assert proxy_tunnel.held() == set() and docker.named(NAME).status == "running"

    @pytest.mark.parametrize("marker", ["held", "kept"])
    def test_a_retry_after_a_worker_restart_flushes_the_folder(self, docker, marker):
        """Which writes had not flushed their folder lived in the process: after a restart, a retry that found the
        marker already saying so was acknowledged with the rename maybe not on disk."""
        path = proxy_tunnel.HELD_MARKER if marker == "held" else proxy_tunnel.KEPT_MARKER
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("cashpilot-honeygain-p3\n")  # renamed by the worker before the restart, folder not flushed
        folders: list = []
        with _folder_fsync(None, folders):
            if marker == "held":
                proxy_tunnel._set_held(NAME, True, strict=True)
            else:
                proxy_tunnel._set_kept(NAME, True, strict=True)
        assert folders, "the retry found the marker already saying so and never flushed its folder"
        with _folder_fsync(errno.EIO), pytest.raises(proxy_tunnel.ProxyTunnelError):
            proxy_tunnel._set_held(NAME, True, strict=True)  # and a flush that fails is never acknowledged


class TestRoundThreeFollowups:
    @pytest.mark.parametrize("by", ["older UI", "heartbeat"])
    def test_a_copy_in_a_retired_older_tunnel_runs_again_when_the_tunnel_under_the_name_is_down(self, docker, by):
        """Only a running tunnel under the name took the copy, and nothing started that tunnel: the copy stayed down
        for good, while the retired tunnel held the proxy's login with no copy running in it."""
        old, current = _older_tunnel_retired_beside_a_current_one(docker)
        proxy_tunnel.stop("earnfm", 3)  # the only copy in the current tunnel, which goes down with it
        assert current.status == "exited"
        docker.named(NAME).stop()  # its own crash
        if by == "older UI":
            proxy_tunnel.start("honeygain", 3, None, None)
        else:
            _heartbeat()
            _heartbeat()
        earner = docker.named(NAME)
        assert earner.status == "running" and earner.attrs["HostConfig"]["NetworkMode"] == f"container:{current.id}"
        assert docker.tunnels() == [current] and current.status == "running"
        assert docker.named("cashpilot-earnfm-p3").status == "exited" and proxy_tunnel.held() == {"cashpilot-earnfm-p3"}

    def test_a_down_tunnel_under_the_name_that_never_gets_ready_goes_down_again(self, docker):
        old, current = _older_tunnel_retired_beside_a_current_one(docker)
        proxy_tunnel.stop("earnfm", 3)
        docker.named(NAME).stop()
        real_ready = docker.ready
        with (
            patch.object(docker, "ready", lambda c: c is not current and real_ready(c)),
            pytest.raises(proxy_tunnel.ProxyTunnelError),
        ):
            proxy_tunnel.start("honeygain", 3, None, None)
        assert current.status == "exited" and docker.named(NAME).status == "exited"

    def test_an_older_ui_start_that_cannot_move_a_legacy_pair_stops_its_tunnel_again(self, docker):
        """The legacy tunnel was started for its settings and left running, Docker restarting it, while its only
        copy stayed stopped: the proxy's login (or an online tailnet node) held for nothing."""
        legacy = _legacy_pair(docker, "earnfm", proxy_id=4)
        _made_by_an_older_worker(legacy)
        proxy_tunnel.stop("earnfm", 4)
        assert legacy.status == "exited"
        with (
            patch.object(proxy_tunnel, "start_sidecar", side_effect=proxy_tunnel.ProxyTunnelError("no exit")),
            pytest.raises(proxy_tunnel.ProxyTunnelError),
        ):
            proxy_tunnel.start("earnfm", 4, None, None)
        assert legacy.status == "exited" and proxy_tunnel.held() == {"cashpilot-earnfm-p4"}
        proxy_tunnel.start("earnfm", 4, None, None)  # control: the next start moves it
        assert docker.named("cashpilot-earnfm-p4").status == "running"

    @pytest.mark.parametrize("shared", ["no shared tunnel", "an older shared tunnel"])
    def test_the_heartbeat_move_of_a_legacy_pair_gives_up_on_a_pull_that_never_returns(self, docker, shared):
        """The legacy path pulled the tunnel image with no deadline, holding the proxy's lock: a stalled registry
        kept a cap's Stop waiting for as long as the pull hung."""
        legacy = _legacy_pair(docker, "earnfm", proxy_id=4, proxy=_socks())
        _made_by_an_older_worker(legacy)
        if shared == "an older shared tunnel":
            _deploy("honeygain", proxy_id=4)
            older = docker.named("cashpilot-tunnel-p4")
            _made_by_an_older_worker(older)
        docker.named("cashpilot-earnfm-p4").stop()  # its own crash: the pair must move
        release = threading.Event()
        pulls = []

        def pull(image):
            pulls.append(image)
            release.wait(3)  # never returns within the test's bound

        try:
            with (
                patch.object(docker, "pull", side_effect=pull),
                patch.object(proxy_tunnel, "REPLACE_PULL_SECONDS", 0.2),
            ):
                began = time.monotonic()
                _heartbeat()
                took = time.monotonic() - began
        finally:
            release.set()
        assert pulls, "the heartbeat never tried to move the pair"
        assert took < 2, took
        assert not proxy_tunnel._deploy_lock(4).locked()
        assert docker.named("cashpilot-earnfm-p4").status == "exited"


class TestRoundFourFollowups:
    @pytest.mark.parametrize("path", ["current UI", "older UI", "legacy pair", "retired tunnel"])
    def test_a_start_that_replaces_an_older_tunnel_gives_up_on_a_pull_that_never_returns(self, docker, path):
        """A start that replaced an older worker's tunnel pulled the image with no deadline, holding the proxy's
        lock: every Stop through that proxy, the traffic cap's too, waited for as long as the pull hung. The same
        for a start with new settings of a copy a failed redeploy left in its old tunnel under the retired name:
        the Test tunnel that proves them pulls the image too."""
        settings = _socks() if path == "current UI" else None
        if path == "retired tunnel":
            _deploy("honeygain")
            _deploy("earnfm")
            old = docker.named("cashpilot-tunnel-p3")
            old.rename("cashpilot-tunnel-p3" + proxy_tunnel.RETIRED_SUFFIX)
            current, _ = proxy_tunnel.start_sidecar(
                docker,
                "cashpilot-tunnel-p3",
                proxy_tunnel.SHARED_SLUG,
                3,
                _socks(),
                None,
                label=proxy_tunnel.shared_label(3),
            )
            proxy_tunnel._clone_into(docker, docker.named("cashpilot-earnfm-p3"), current)
            settings = _socks(password=NEW_PASSWORD)  # proved in a Test tunnel before the retired one takes them
        else:
            if path == "legacy pair":
                tunnel = _legacy_pair(docker, "honeygain", proxy=_socks())
            else:
                _deploy("honeygain")
                tunnel = docker.named("cashpilot-tunnel-p3")
            _made_by_an_older_worker(tunnel)
            proxy_tunnel.stop("honeygain", 3)
        release = threading.Event()
        pulls = []

        def pull(image):
            pulls.append(image)
            release.wait(3)  # never returns within the test's bound

        try:
            with (
                patch.object(docker, "pull", side_effect=pull),
                patch.object(proxy_tunnel, "REPLACE_PULL_SECONDS", 0.2),
                pytest.raises(proxy_tunnel.ProxyTunnelError) as caught,
            ):
                began = time.monotonic()
                try:
                    proxy_tunnel.start("honeygain", 3, settings, None)
                finally:
                    took = time.monotonic() - began
        finally:
            release.set()
        # A transient pull, never "a deploy past its 60-minute limit" nor a 409 setting to fix.
        assert caught.value.status_code == 503
        assert "tunnel image took longer than 0.2 seconds to pull" in str(caught.value)
        assert "limit" not in str(caught.value)
        assert pulls, "the start never replaced the tunnel"
        assert took < 2, took
        assert not proxy_tunnel._deploy_lock(3).locked()
        if path == "retired tunnel":
            # Never stopped: it keeps running on the settings it had.
            assert docker.named(NAME).status == "running" and proxy_tunnel.held() == set()
            assert old.files["proxy_auth"] == proxy_tunnel.proxy_auth("u1", PASSWORD)
        else:
            assert docker.named(NAME).status == "exited" and proxy_tunnel.held() == {NAME}

    @pytest.mark.parametrize("pair", ["shared", "legacy"])
    def test_a_start_whose_record_cannot_be_flushed_starts_the_copy_and_says_so(self, docker, pair):
        """The start reported a failure once the marker already said the copy runs, and left the earner down:
        the next heartbeat started it, so the owner (or the cap) was told the opposite of what happened."""
        if pair == "legacy":
            _legacy_pair(docker, "honeygain")
        else:
            _deploy("honeygain")
        proxy_tunnel.stop("honeygain", 3)
        assert docker.named(NAME).status == "exited"
        with _folder_fsync(errno.EIO):
            answer = proxy_tunnel.start("honeygain", 3, _socks() if pair == "shared" else None, None)
        # Started, so a 2xx: an error would have the UI keep the copy recorded as stopped (by the cap, too).
        assert answer["durable"] is False and "was started, but" in answer["warning"]
        assert proxy_tunnel.held() == set()
        assert docker.named(NAME).status == "running"
        _heartbeat()
        assert docker.named(NAME).status == "running"

    def test_a_copy_whose_move_out_of_an_older_tunnel_fails_stays_stopped_until_the_next_try(self, docker):
        """A copy stops before its move, so a move that fails leaves it stopped in an older worker's tunnel, where no
        earner starts: that is the cost of never having two of one copy running. The next try moves it, and the
        heartbeat starts it in the new tunnel."""
        _deploy("honeygain")
        old = docker.named("cashpilot-tunnel-p3")
        _made_by_an_older_worker(old)
        earner = docker.named(NAME)
        real_create = docker.create
        failed = []

        def create(**kw):
            c = real_create(**kw)
            if kw["name"] == NAME + proxy_tunnel.STAGED_SUFFIX:
                real_rename = c.rename

                def rename(name):
                    if name == NAME and not failed:
                        failed.append(name)
                        raise APIError("500 Server Error: rename failed")
                    real_rename(name)

                c.rename = rename
            return c

        with patch.object(docker, "create", side_effect=create):
            _heartbeat()
            _heartbeat()
        assert failed, "the move never reached the clone's rename"
        assert docker.named(NAME) is earner and earner.status == "exited"
        assert earner.attrs["HostConfig"]["NetworkMode"] == f"container:{old.id}"
        assert proxy_tunnel.held() == set()  # still marked to run
        proxy_tunnel._replace_failed.clear()  # the next try, minutes later, moves it
        _heartbeat()
        _heartbeat()
        (new,) = docker.tunnels()
        clone = docker.named(NAME)
        assert new.id != old.id and clone.status == "running"
        assert clone.attrs["HostConfig"]["NetworkMode"] == f"container:{new.id}"


def _running(docker):
    return sorted(
        c.name for c in docker.by_id.values() if c.status == "running" and c.labels.get(LABEL_ROLE) != "tunnel"
    )


class TestRoundFiveFollowups:
    @staticmethod
    def _killed_mid_move(docker, step):
        """A legacy pair through proxy 3 whose move into the shared tunnel a worker died in, at ``step``."""
        _legacy_pair(docker, "honeygain", proxy=_socks())
        earner = docker.named(NAME)
        real_create = docker.create

        def killed(*_a, **_kw):
            raise SystemExit("worker killed")

        def create(**kw):
            c = real_create(**kw)
            if kw["name"] == NAME + proxy_tunnel.STAGED_SUFFIX:
                if step == "clone rename":
                    c.rename = killed
                elif step == "clone start":
                    c.start = killed
            return c

        if step == "member stop":
            earner.stop = killed
        elif step == "member rename":
            earner.rename = killed
        with patch.object(docker, "create", side_effect=create), pytest.raises(SystemExit):
            proxy_tunnel.migrate_legacy()
        for attr in ("stop", "rename"):
            earner.__dict__.pop(attr, None)
        for c in docker.by_id.values():
            for attr in ("rename", "start"):
                c.__dict__.pop(attr, None)
            if c.name.endswith(proxy_tunnel.STAGED_SUFFIX) or c is docker.named(NAME) and c is not earner:
                c.attrs["Created"] = _now()  # a worker just restarted: the move is too young to settle

    @pytest.mark.parametrize("step", ["member stop", "member rename", "clone rename", "clone start"])
    @pytest.mark.parametrize("then", ["stop", "redeploy", "remove"])
    def test_a_worker_that_dies_mid_move_never_leaves_the_old_container_running_aside(self, docker, step, then):
        """The member stopped only once its clone held the name. A worker that died in between left the old container
        running as <name>-moving: a Stop then stopped only the clone and said so, a redeploy started a second copy
        beside it, and a remove deleted only the clone while recover_moves gave the running one its name back.
        The member stops before it is renamed now, so the one aside is never running, and every path ends right."""
        self._killed_mid_move(docker, step)
        aside = docker.named(NAME + proxy_tunnel.MOVING_SUFFIX)
        assert aside is None or aside.status != "running", aside.status
        assert len(_running(docker)) <= 1
        if then == "stop":
            proxy_tunnel.stop("honeygain", 3)
            _heartbeat()
            assert _running(docker) == []
        elif then == "redeploy":
            _deploy("honeygain")
            _heartbeat()
            assert _running(docker) == [NAME]
        else:
            proxy_tunnel.remove("honeygain", 3)
            proxy_tunnel.recover_moves(min_age=0)
            _heartbeat()
            assert _running(docker) == []

    def test_a_stop_whose_data_folder_cannot_be_opened_still_stops_the_copy(self, docker):
        """The folder was opened outside the flush's error mapping: an open that failed after the rename (EMFILE)
        raised a plain error, so the stop skipped the halt and the copy kept running while the marker said stopped."""
        _deploy("honeygain")
        real = os.open

        def open_(path, flags, *args, **kwargs):
            if os.path.isdir(path):
                raise OSError(errno.EMFILE, os.strerror(errno.EMFILE))
            return real(path, flags, *args, **kwargs)

        with patch.object(proxy_tunnel.os, "open", side_effect=open_):
            out = proxy_tunnel.stop("honeygain", 3)
        assert out["was_running"] is True and out["durable"] is False
        assert proxy_tunnel.held() == {NAME}
        assert docker.named(NAME).status == "exited"

    @pytest.mark.parametrize("how", ["start without settings", "worker start", "heartbeat"])
    def test_a_routed_legacy_pair_moves_into_its_own_tunnel_never_the_shared_one(self, docker, how):
        """A start with no settings (an older UI), the worker start and the heartbeat moved a routed service's legacy
        pair into the proxy's shared tunnel, beside every other service's earner; a start with settings keeps a
        routed service in a tunnel of its own."""
        _deploy("earnapp")  # another service's copy, in the proxy's shared tunnel
        legacy = _legacy_pair(docker, "honeygain", proxy=_socks())
        _made_by_an_older_worker(legacy)
        if how == "start without settings":
            proxy_tunnel.stop("honeygain", 3)
        elif how == "heartbeat":
            docker.named(NAME).stop()  # not held: the heartbeat starts it, so it moves first
        with patch.object(proxy_tunnel.route_gate, "routed", return_value={"honeygain": 3}):
            if how == "start without settings":
                proxy_tunnel.start("honeygain", 3, None, None)
            elif how == "worker start":
                assert proxy_tunnel.migrate_legacy() == [NAME]
            else:
                _heartbeat()
                _heartbeat()
        own = docker.named(proxy_tunnel.shared_tunnel_name(3, "honeygain"))
        shared = docker.named(proxy_tunnel.shared_tunnel_name(3))
        assert own is not None and own.labels.get(proxy_tunnel.LABEL_TUNNEL_FOR) == "honeygain"
        earner = docker.named(NAME)
        assert earner.attrs["HostConfig"]["NetworkMode"] == f"container:{own.id}"
        assert _member_ids(docker, shared) == ["cashpilot-earnapp-p3"]
        assert docker.named(proxy_tunnel.tunnel_name("honeygain", 3)) is None
        assert earner.status == "running" and own.status == "running"


class TestRoundSixFollowups:
    @pytest.mark.parametrize("cap", ["NET_ADMIN", "CAP_NET_RAW", "sys_admin", "ALL"])
    def test_a_copy_holding_a_capability_that_reaches_the_firewall_is_never_carried_into_a_tunnel(self, docker, cap):
        """The worker API refuses these for a proxied copy (_validate_proxied): in a tunnel's namespace they could
        flush its firewall. A move carried them, into a namespace every other copy through that proxy shares."""
        _deploy("honeygain")
        old = docker.named("cashpilot-tunnel-p3")
        _made_by_an_older_worker(old)
        earner = docker.named(NAME)
        earner.attrs["HostConfig"]["CapAdd"] = ["NET_BIND_SERVICE", cap]
        _heartbeat()
        assert docker.named(NAME) is earner and earner.status == "running"
        assert earner.attrs["HostConfig"]["NetworkMode"] == f"container:{old.id}"
        assert docker.tunnels() == [old]
        with pytest.raises(proxy_tunnel.ProxyTunnelError, match="which a proxied copy never gets"):
            proxy_tunnel._clone_into(docker, earner, old)
        assert docker.named(NAME + proxy_tunnel.STAGED_SUFFIX) is None and earner.status == "running"

    def test_a_moved_copy_keeps_its_harmless_capabilities_but_never_a_weaker_confinement(self, docker):
        """SecurityOpt was carried verbatim, so a recorded seccomp=unconfined replaced the no-new-privileges every
        proxied copy gets."""
        _deploy("honeygain")
        old = docker.named("cashpilot-tunnel-p3")
        _made_by_an_older_worker(old)
        earner = docker.named(NAME)
        earner.attrs["HostConfig"]["CapAdd"] = ["NET_BIND_SERVICE"]
        earner.attrs["HostConfig"]["SecurityOpt"] = ["seccomp=unconfined", "apparmor=unconfined"]
        _heartbeat()
        clone = docker.named(NAME)
        assert clone is not earner and clone.status == "running"
        assert clone.attrs["HostConfig"]["NetworkMode"] != f"container:{old.id}"
        assert clone.kw["cap_add"] == ["NET_BIND_SERVICE"]
        assert clone.kw["security_opt"] == ["no-new-privileges:true"]

    def test_the_worker_start_migration_gives_up_on_a_pull_that_never_returns(self, docker):
        """migrate_legacy pulled the tunnel image with no deadline under the proxy's lock: a Stop through that
        proxy, the traffic cap's too, waited for as long as the pull hung."""
        _legacy_pair(docker, "honeygain", proxy=_socks())
        release = threading.Event()
        pulls = []

        def pull(image):
            pulls.append(image)
            release.wait(3)  # never returns within the test's bound

        try:
            with (
                patch.object(docker, "pull", side_effect=pull),
                patch.object(proxy_tunnel, "REPLACE_PULL_SECONDS", 0.2),
            ):
                began = time.monotonic()
                moved = proxy_tunnel.migrate_legacy()
                took = time.monotonic() - began
        finally:
            release.set()
        assert pulls, "the migration never pulled the tunnel image"
        assert moved == [] and took < 2, took
        assert not proxy_tunnel._deploy_lock(3).locked()
        assert docker.named(NAME).status == "running"
        assert docker.named(proxy_tunnel.tunnel_name("honeygain", 3)).status == "running"


class TestRoundSevenFollowups:
    def test_a_moved_copy_never_keeps_dockers_default_capabilities(self, docker):
        """The move carried the member's recorded CapDrop: one that dropped only MKNOD, with no CapAdd, kept Docker's
        default NET_RAW inside the tunnel's namespace, where raw frames skip its firewall. Every proxied copy gets
        every capability dropped (orchestrator.deploy_raw), the moved one too."""
        _deploy("honeygain")
        old = docker.named("cashpilot-tunnel-p3")
        _made_by_an_older_worker(old)
        earner = docker.named(NAME)
        earner.attrs["HostConfig"]["CapDrop"] = ["MKNOD"]
        earner.attrs["HostConfig"]["CapAdd"] = None
        _heartbeat()
        clone = docker.named(NAME)
        assert clone is not earner and clone.status == "running"
        assert clone.attrs["HostConfig"]["NetworkMode"] != f"container:{old.id}"
        assert clone.kw["cap_drop"] == ["ALL"] and clone.kw.get("cap_add") is None

    def test_a_copy_that_can_never_move_is_refused_before_any_tunnel_is_built(self, docker):
        """The refusal ran only once a whole new tunnel was pulled, started and logged in: one such copy made every
        start through the proxy, and every heartbeat try, build one and throw it away. And the error did not say
        what to do."""
        _deploy("earnapp")
        _deploy("honeygain")
        old = docker.named("cashpilot-tunnel-p3")
        _made_by_an_older_worker(old)
        docker.named("cashpilot-earnapp-p3").attrs["HostConfig"]["Devices"] = [
            {"PathOnHost": "/dev/dri/renderD128", "PathInContainer": "/dev/dri/card0", "CgroupPermissions": "r"},
        ]
        proxy_tunnel.stop("honeygain", 3)
        docker.events.clear()  # the first deploy built the shared tunnel under the staged name
        for proxy in (_socks(), None):
            with pytest.raises(proxy_tunnel.ProxyTunnelError) as err:
                proxy_tunnel.start("honeygain", 3, proxy, None)
            assert "cashpilot-earnapp-p3 holds host devices" in str(err.value)
            assert "Remove cashpilot-earnapp-p3" in str(err.value)
        for _ in range(3):
            proxy_tunnel._replace_failed.clear()
            _heartbeat()
        assert ("create", "cashpilot-tunnel-p3" + proxy_tunnel.STAGED_SUFFIX) not in docker.events
        assert docker.tunnels() == [old]
        assert docker.named("cashpilot-earnapp-p3").attrs["HostConfig"]["NetworkMode"] == f"container:{old.id}"

    @staticmethod
    def _killed_mid_shared_move(docker):
        """earnapp and honeygain in an older worker's shared tunnel, whose replacement a worker died in just after
        honeygain was renamed aside: only cashpilot-honeygain-p3-moving (stopped) and -next are left of it."""
        _deploy("earnapp")
        _deploy("honeygain")
        old = docker.named("cashpilot-tunnel-p3")
        _made_by_an_older_worker(old)
        real_create = docker.create

        def killed(*_a, **_kw):
            raise SystemExit("worker killed")

        def create(**kw):
            c = real_create(**kw)
            if kw["name"] == NAME + proxy_tunnel.STAGED_SUFFIX:
                c.rename = killed
            return c

        with patch.object(docker, "create", side_effect=create), pytest.raises(SystemExit):
            proxy_tunnel._replace_restarting(docker, old)
        for c in docker.by_id.values():
            c.__dict__.pop("rename", None)
        assert docker.named(NAME) is None
        assert docker.named(NAME + proxy_tunnel.MOVING_SUFFIX).status == "exited"
        assert docker.named(NAME + proxy_tunnel.STAGED_SUFFIX) is not None
        assert docker.named(proxy_tunnel.tunnel_name("honeygain", 3)) is None  # no legacy tunnel to find it by

    def test_a_stop_of_a_copy_left_half_moved_in_a_shared_tunnel_holds(self, docker):
        """With only the two halves left and no legacy tunnel, the Stop was refused as "no proxied copy" before the
        stop was written down: recover_moves gave the copy its name back and the heartbeat started it."""
        self._killed_mid_shared_move(docker)
        assert proxy_tunnel.held() == set()
        # The owner never stopped it, so it counts as running, as a stopped copy in a live shared tunnel does: the
        # cap then marks it, and its monthly reset starts it again (main._release_capped_copies).
        assert proxy_tunnel.stop("honeygain", 3) == {"was_running": True}
        assert proxy_tunnel.held() == {NAME}
        proxy_tunnel.recover_moves(min_age=0)
        for _ in range(3):
            proxy_tunnel._replace_failed.clear()
            _heartbeat()
        assert NAME not in _running(docker)
        assert "cashpilot-earnapp-p3" in _running(docker)

    def test_a_remove_of_a_copy_left_half_moved_in_a_shared_tunnel_leaves_nothing_to_restore(self, docker):
        """_remove deletes <name>-moving too: left behind, recover_moves gave it the name back, and in a shared
        tunnel, which the remove keeps for the other copies, the heartbeat started it again."""
        self._killed_mid_shared_move(docker)
        proxy_tunnel.remove("honeygain", 3)
        proxy_tunnel.recover_moves(min_age=0)
        for _ in range(3):
            proxy_tunnel._replace_failed.clear()
            _heartbeat()
        assert NAME not in _running(docker)
        assert not [c.name for c in docker.by_id.values() if c.name.startswith(NAME)]
        assert "cashpilot-earnapp-p3" in _running(docker)

    def test_control_a_stop_of_a_half_moved_copy_the_owner_had_stopped_reports_not_running(self, docker):
        self._killed_mid_shared_move(docker)
        proxy_tunnel._set_held(NAME, True, strict=True)
        assert proxy_tunnel.stop("honeygain", 3) == {"was_running": False}
        assert proxy_tunnel.held() == {NAME}


class TestRoundEightFollowups:
    def test_a_half_that_cannot_stop_never_keeps_the_copy_or_its_tunnel_running(self, docker):
        """A half's failed stop escaped before the named copy and its tunnel were stopped: the marker said stopped,
        so the heartbeat left the copy running for good."""
        _deploy("honeygain")
        old = docker.named("cashpilot-tunnel-p3")
        _made_by_an_older_worker(old)
        earner = docker.named(NAME)

        def cannot_remove(force=False, v=False):
            raise APIError("500 Server Error: remove timed out")

        earner.remove = cannot_remove  # the move succeeds, its predecessor stays as <name>-moving
        _heartbeat()
        clone = docker.named(NAME)
        moving = docker.named(NAME + proxy_tunnel.MOVING_SUFFIX)
        assert clone is not earner and clone.status == "running" and moving is earner
        (tunnel,) = docker.tunnels()
        assert tunnel.status == "running"

        def cannot_stop(timeout=None):
            raise APIError("500 Server Error: stop timed out")

        moving.stop = cannot_stop
        answer = proxy_tunnel.stop("honeygain", 3)
        assert proxy_tunnel.held() == {NAME}
        assert clone.status == "exited" and tunnel.status == "exited"
        # A stop, never an error: the cap marks the copy it stopped, so its reset starts it again.
        assert answer["was_running"] is True
        assert "durable" not in answer
        assert "could not be stopped" in answer["warning"] and "stop timed out" in answer["warning"]

    def test_a_half_that_still_runs_and_cannot_stop_is_a_failed_stop_the_cap_retries(self, docker):
        """A half that cannot stop was turned into a warning even when it still ran: the cap dropped its retry while
        that copy kept using the proxy. Only a half that was already down is a warning."""
        _deploy("honeygain")
        _made_by_an_older_worker(docker.named("cashpilot-tunnel-p3"))
        earner = docker.named(NAME)

        def cannot_remove(force=False, v=False):
            raise APIError("500 Server Error: remove timed out")

        earner.remove = cannot_remove
        _heartbeat()
        moving = docker.named(NAME + proxy_tunnel.MOVING_SUFFIX)
        moving.status = "running"  # not what a current worker leaves, but a stop must never hide it

        def cannot_stop(timeout=None):
            raise APIError("500 Server Error: stop timed out")

        moving.stop = cannot_stop
        with pytest.raises(APIError, match="stop timed out"):
            proxy_tunnel.stop("honeygain", 3)
        assert proxy_tunnel.held() == {NAME}
        assert docker.named(NAME).status == "exited"
        # The cap's retry: the half still runs, so the copy counts as running and is marked.
        moving.stop = lambda timeout=None: setattr(moving, "status", "exited")
        assert proxy_tunnel.stop("honeygain", 3)["was_running"] is True

    def test_a_half_that_cannot_stop_still_leaves_a_capped_copy_marked_for_its_reset(self, docker):
        """A half's failed stop raised after the copy and its tunnel were down and the marker held: the cap read
        "could not stop", a second stop found the copy held and down (was_running False), so it was never marked
        and the monthly reset never started it again."""
        _deploy("honeygain")
        _made_by_an_older_worker(docker.named("cashpilot-tunnel-p3"))
        earner = docker.named(NAME)

        def cannot_remove(force=False, v=False):
            raise APIError("500 Server Error: remove timed out")

        earner.remove = cannot_remove
        _heartbeat()
        moving = docker.named(NAME + proxy_tunnel.MOVING_SUFFIX)
        calls = {"n": 0}

        def stop_fails_once(timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise APIError("500 Server Error: stop timed out")

        moving.stop = stop_fails_once
        with patch.object(worker_api, "_verify_api_key"):
            answer = TestClient(worker_api.app, raise_server_exceptions=False).post("/api/proxied/honeygain/3/stop")
        assert answer.status_code == 200, answer.text
        body = answer.json()
        assert body["status"] == "stopped" and body["was_running"] is True and "stop timed out" in body["warning"]

    def test_a_retired_older_tunnel_with_an_unmovable_copy_never_starts_the_tunnel_under_the_name(self, docker):
        """The refusal comes before the down tunnel under the name is started for the move: after it, _move_members
        refused the copy, and that tunnel stayed up for copies that were all stopped."""
        old, current = _older_tunnel_retired_beside_a_current_one(docker)
        proxy_tunnel.stop("earnfm", 3)  # the only copy in the current tunnel, which goes down with it
        assert current.status == "exited"
        docker.named(NAME).attrs["HostConfig"]["Devices"] = [
            {"PathOnHost": "/dev/dri/renderD128", "PathInContainer": "/dev/dri/card0", "CgroupPermissions": "r"},
        ]
        starts = current.starts
        with pytest.raises(proxy_tunnel.ProxyTunnelError, match="holds host devices"):
            proxy_tunnel._replace_restarting(docker, old)
        assert current.status == "exited" and current.starts == starts
        assert docker.named(NAME).attrs["HostConfig"]["NetworkMode"] == f"container:{old.id}"

    def test_a_redeploy_of_a_lone_copy_with_host_devices_keeps_it_aside_and_succeeds(self, docker):
        """The copy a deploy replaces is kept aside, never moved, so its devices are no reason to refuse: only the
        other copies in its tunnel would move."""
        _deploy("honeygain")
        old = docker.named("cashpilot-tunnel-p3")
        _made_by_an_older_worker(old)
        earner = docker.named(NAME)
        earner.attrs["HostConfig"]["Devices"] = [
            {"PathOnHost": "/dev/dri/renderD128", "PathInContainer": "/dev/dri/card0", "CgroupPermissions": "r"},
        ]
        _deploy("honeygain")
        new = docker.named(NAME)
        assert new is not earner and new.status == "running"
        assert not new.attrs["HostConfig"].get("Devices")
        (tunnel,) = docker.tunnels()
        assert tunnel is not old and new.attrs["HostConfig"]["NetworkMode"] == f"container:{tunnel.id}"


class TestRoundNineFollowups:
    def test_a_stop_of_a_copy_left_only_as_its_old_earner_aside_holds(self, docker):
        """With the name free, a failed redeploy's old earner aside (<name>-replaced) is the copy. The Stop did not
        look it up and was refused as "no proxied copy" before the stop was written down: the heartbeat gave it
        its name back and started the copy the owner had stopped."""
        aside = _left_aside(docker)
        assert proxy_tunnel.stop("honeygain", 3) == {"was_running": True}  # never stopped by the owner: wanted
        assert proxy_tunnel.held() == {NAME}
        for _ in range(3):
            _heartbeat()
        assert aside.name == NAME and aside.status == "exited"

    def test_control_a_stop_of_an_aside_the_owner_had_stopped_reports_not_running(self, docker):
        _left_aside(docker)
        proxy_tunnel._set_held(NAME, True, strict=True)
        assert proxy_tunnel.stop("honeygain", 3) == {"was_running": False}

    def test_a_copy_and_its_tunnel_down_after_a_reboot_count_as_running_for_the_cap(self, docker):
        """Both exited and never stopped by the owner: the stop answered was_running False, so the cap never marked
        the copy it held, and its monthly reset never started it again."""
        _deploy("honeygain")
        for c in docker.by_id.values():
            c.status = "exited"
        with patch.object(worker_api, "_verify_api_key"):
            answer = TestClient(worker_api.app, raise_server_exceptions=False).post("/api/proxied/honeygain/3/stop")
        assert answer.status_code == 200, answer.text
        assert answer.json()["was_running"] is True
        assert proxy_tunnel.held() == {NAME}
        # Held now, so a second stop of the same copy is the owner's own stop: not marked again.
        assert proxy_tunnel.stop("honeygain", 3) == {"was_running": False}

    def test_a_held_copy_that_still_runs_counts_as_running(self, docker):
        """A stop that wrote the marker and then failed is tried again: the copy still runs, so the cap marks it."""
        _deploy("honeygain")
        proxy_tunnel._set_held(NAME, True, strict=True)
        assert docker.named(NAME).status == "running"
        assert proxy_tunnel.stop("honeygain", 3) == {"was_running": True}

    def test_a_copy_left_only_as_young_halves_is_listed_so_its_hold_stays(self, docker):
        """recover_moves leaves a young pair alone, and status skipped both halves: the heartbeat said the routes
        were read and listed no copy, so the UI let go of the copy's unconfirmed ids past their time while the
        copy could still be recovered and run them."""
        from app import main

        TestRoundSevenFollowups._killed_mid_shared_move(docker)
        clone = docker.named(NAME + proxy_tunnel.STAGED_SUFFIX)
        clone.attrs["Created"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")  # a move still young
        with patch.object(orchestrator, "_identity_entry", return_value={"identity_digest": "d"}):
            entries = _heartbeat()
        (entry,) = [e for e in entries if e["slug"] == "honeygain"]
        assert entry["name"] == NAME and "identity_digest" not in entry
        moving = docker.named(NAME + proxy_tunnel.MOVING_SUFFIX)
        assert moving is not None and moving.status == "exited"  # listed, never started or recovered here
        assert docker.named(NAME) is None
        for e in entries:
            e["routed"] = True  # worker_api._mark_routed, for a routed service
        containers = main._ledger_containers([], {"proxied": entries})
        hold = {"slug": "honeygain", "copy": 1, "env": {"K": "new"}, "age": 10**9, "instance": "pending-1"}
        settle = AsyncMock()
        with (
            patch.object(main.database, "pending_identities", AsyncMock(return_value=[hold])),
            patch.object(main, "_identity_digest_keys", AsyncMock(return_value=["k"])),
            patch.object(main.database, "active_identity_values", AsyncMock(return_value={"1": {"K": "old"}})),
            patch.object(main.database, "settle_pending_identities", settle),
        ):
            asyncio.run(main._settle_pending_identities(7, containers, complete=True, deadline=True))
        settle.assert_not_awaited()


class TestRoundTenFollowups:
    def test_a_legacy_copy_left_only_as_its_halves_with_its_tunnel_down_counts_as_running(self, docker):
        """migrate_legacy moves only a pair the owner wanted running, so its halves are a copy never stopped. With
        no named earner, its legacy tunnel down by name took the legacy rule (live only): the halves are always
        down, so the stop answered was_running False, the cap never marked the copy it held, and its monthly
        reset never started it again."""
        TestRoundFiveFollowups._killed_mid_move(docker, "clone rename")
        assert docker.named(NAME) is None
        legacy = docker.named(proxy_tunnel.tunnel_name("honeygain", 3))
        assert legacy is not None
        legacy.stop()
        assert proxy_tunnel.held() == set()
        assert proxy_tunnel.stop("honeygain", 3) == {"was_running": True}
        assert proxy_tunnel.held() == {NAME}

    def test_a_legacy_earner_whose_tunnel_is_gone_counts_only_live(self, docker):
        """An older worker's stop left no marker, and nothing starts an earner with no tunnel: down and unheld, it
        was stopped by its owner. With its tunnel gone the stop took the shared rule and answered was_running
        True, so the cap marked it and its monthly reset started a copy its owner had stopped."""
        tunnel = _legacy_pair(docker, "honeygain", running=False)
        tunnel.remove(force=True)
        earner = docker.named(NAME)
        assert earner.status == "exited" and proxy_tunnel._tunnel_of(docker, earner, "honeygain", 3) is None
        assert proxy_tunnel.stop("honeygain", 3) == {"was_running": False}
        assert proxy_tunnel.held() == {NAME}

    def test_a_legacy_pair_killed_mid_move_with_its_named_earner_still_counts_as_running(self, docker):
        """migrate_legacy moves only a pair the owner wanted running. Killed after the clone was made and before the
        member was renamed aside, the named earner and its -next clone are both left: the legacy rule (live only)
        answered was_running False for them, so the cap never marked the copy and its reset never started it."""
        TestRoundFiveFollowups._killed_mid_move(docker, "member rename")
        assert docker.named(NAME) is not None and docker.named(NAME + proxy_tunnel.STAGED_SUFFIX) is not None
        docker.named(proxy_tunnel.tunnel_name("honeygain", 3)).stop()
        assert proxy_tunnel.held() == set()
        assert proxy_tunnel.stop("honeygain", 3) == {"was_running": True}

    def test_a_down_legacy_tunnel_left_with_no_earner_counts_as_stopped(self, docker):
        """Docker restarts a legacy tunnel unless its owner stopped it. Left down with no earner, it answered
        was_running True, so the cap marked a copy that can never start, and its reset retried the start on every
        heartbeat."""
        _legacy_pair(docker, "honeygain", running=False)
        docker.named(NAME).remove(force=True)
        assert proxy_tunnel.stop("honeygain", 3) == {"was_running": False}
        assert proxy_tunnel.held() == {NAME}

    def test_control_a_live_legacy_earner_whose_tunnel_is_gone_counts_as_running(self, docker):
        tunnel = _legacy_pair(docker, "honeygain")
        tunnel.remove(force=True)
        assert docker.named(NAME).status == "running"
        assert proxy_tunnel.stop("honeygain", 3) == {"was_running": True}


class TestARestartInPlace:
    """proxy_tunnel.restart: what the UI's windowed health sweep asks for a copy stuck in a state a restart clears.

    A stop and a start would do it too, but the stop marks the copy held first,
    so a start that then failed would leave it stopped for good. A restart
    writes no marker and keeps the container, so its device id stays."""

    def test_the_copy_restarts_in_its_tunnel_and_nothing_else_moves(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        tunnel = docker.named("cashpilot-tunnel-p3")
        earner, other = docker.named(NAME), docker.named("cashpilot-earnfm-p3")
        before = (earner.starts, other.starts, tunnel.starts, len(docker.events))
        assert proxy_tunnel.restart("honeygain", 3) == {"restarted": NAME}
        assert docker.named(NAME) is earner and earner.status == "running"
        assert earner.starts == before[0] + 1
        assert (other.starts, tunnel.starts) == before[1:3]
        assert docker.events[before[3] :] == [("stop", NAME)]
        assert proxy_tunnel.held() == set()

    def test_a_copy_its_owner_stopped_is_left_stopped(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        proxy_tunnel.stop("honeygain", 3)
        earner = docker.named(NAME)
        starts = earner.starts
        with pytest.raises(proxy_tunnel.ProxyTunnelError, match="left stopped"):
            proxy_tunnel.restart("honeygain", 3)
        assert earner.status == "exited" and earner.starts == starts
        assert proxy_tunnel.held() == {NAME}

    def test_a_copy_that_is_not_running_is_left_as_it_is(self, docker):
        _deploy("honeygain")
        earner = docker.named(NAME)
        earner.status = "exited"
        with pytest.raises(proxy_tunnel.ProxyTunnelError, match="not running"):
            proxy_tunnel.restart("honeygain", 3)
        assert earner.status == "exited" and proxy_tunnel.held() == set()

    def test_a_copy_whose_tunnel_is_not_ready_is_not_restarted(self, docker):
        _deploy("honeygain")
        earner = docker.named(NAME)
        starts = earner.starts
        docker.broken_auth.add(docker.named("cashpilot-tunnel-p3").files["proxy_auth"])
        with pytest.raises(proxy_tunnel.ProxyTunnelError, match="was not restarted") as err:
            proxy_tunnel.restart("honeygain", 3)
        assert err.value.status_code == 503
        assert earner.status == "running" and earner.starts == starts
        assert proxy_tunnel.held() == set()

    def test_a_copy_a_failed_deploy_left_is_not_restarted(self, docker):
        _deploy("honeygain")
        earner = docker.named(NAME)
        starts = earner.starts
        proxy_tunnel._set_failed(earner.id, True)
        with pytest.raises(proxy_tunnel.ProxyTunnelError, match="did not finish"):
            proxy_tunnel.restart("honeygain", 3)
        assert earner.starts == starts

    def test_a_restart_reads_the_copy_only_after_a_stop_under_the_proxys_lock(self, docker):
        """The owner's stop, the cap's and a deploy hold the proxy's lock: a restart asked meanwhile waits for them."""
        _deploy("honeygain")
        earner = docker.named(NAME)
        outcome: list[Any] = []

        def _restart() -> None:
            try:
                outcome.append(proxy_tunnel.restart("honeygain", 3))
            except proxy_tunnel.ProxyTunnelError as exc:
                outcome.append(exc)

        with proxy_tunnel._deploy_lock(3):
            worker = threading.Thread(target=_restart)
            worker.start()
            worker.join(0.3)
            assert outcome == [], "the restart ran while the proxy's lock was held"
            proxy_tunnel._stop("honeygain", 3)  # what stop() does under that lock
        worker.join(5)
        assert len(outcome) == 1 and "left stopped" in str(outcome[0])
        assert earner.status == "exited" and proxy_tunnel.held() == {NAME}

    def test_the_worker_route_answers_a_restart_a_refusal_and_no_such_copy(self, docker):
        _deploy("honeygain")
        with patch.object(worker_api, "_verify_api_key"):
            api = TestClient(worker_api.app, raise_server_exceptions=False)
            assert api.post("/api/proxied/earnfm/3/restart").status_code == 404
            ok = api.post("/api/proxied/honeygain/3/restart")
            proxy_tunnel.stop("honeygain", 3)
            held = api.post("/api/proxied/honeygain/3/restart")
        assert ok.status_code == 200 and ok.json() == {"status": "restarted", "restarted": NAME}
        assert held.status_code == 409 and "left stopped" in held.json()["detail"]
