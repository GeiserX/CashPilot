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
import io
import itertools
import json
import os
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

from app import orchestrator, proxies, proxy_tunnel  # noqa: E402
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

    def deploy_raw(*, slug, image, env, network_mode, labels, name, deadline=None, **_kw):
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
        patch.dict(os.environ, {"CASHPILOT_TUNNEL_IMAGE": IMAGE}),
        patch.object(proxy_tunnel.time, "sleep", lambda _s: None),
    ):
        yield d


def _deploy(slug, proxy=None, proxy_id=3):
    return proxy_tunnel.deploy(
        slug, proxy_id, {"image": f"{slug}/{slug}:1", "env": {"K": slug}}, proxy or _socks(), None
    )


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
        assert proxy_tunnel.stop("honeygain", 3) is True
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
            docker.create(image=image, name=name, labels={**labels, LABEL_SERVICE: slug, LABEL_MANAGED: "true"})
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
        assert proxy_tunnel.stop("honeygain", 3) is True
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
        assert proxy_tunnel.stop("honeygain", 3) is True
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
        assert proxy_tunnel.stop("honeygain", 3) is True
        assert proxy_tunnel.stop("honeygain", 3) is False

    def test_a_crashed_copy_beside_a_running_tunnel_counts_as_running_for_the_cap(self, docker):
        _deploy("honeygain")
        _deploy("earnfm")
        docker.named("cashpilot-honeygain-p3").status = "exited"  # crashed, never stopped by the owner
        assert proxy_tunnel.stop("honeygain", 3) is True

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
        # A reboot: everything down, then Docker starts the tunnel (unless-stopped)
        # and no earner (restart policy "no").
        for c in docker.by_id.values():
            c.status = "exited"
        docker.broken_auth.add(tunnel.files["proxy_auth"])  # not ready yet
        tunnel.start()
        with patch.object(orchestrator, "_collect_stats_bulk", return_value={}):
            proxy_tunnel.status()
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
    _fake_deploy_raw(docker)(
        slug=slug,
        image=f"{slug}/{slug}:1",
        env={"K": slug},
        network_mode=f"container:{tunnel.id}",
        labels={LABEL_PROXY: str(proxy_id)},
        name=proxy_tunnel.earner_name(slug, proxy_id),
    )
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
        assert moved.kw["image"] == "honeygain/honeygain:1" and moved.kw["environment"] == ["K=honeygain"]
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
    return old


def _rename_fails_for(name, exc):
    real = FakeContainer.rename

    def rename(self, new):
        if new == name and self.name.endswith("-next"):
            raise exc
        return real(self, new)

    return patch.object(FakeContainer, "rename", rename)


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
        docker.create(
            name="cashpilot-b-p3-next", image="b/b:1", labels=dict(b.labels), network_mode=f"container:{tunnel.id}"
        )
        # c: only a clone, the name free.
        c = docker.named("cashpilot-c-p3")
        c.rename("cashpilot-c-p3-next")
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
                stopped.append(proxy_tunnel.stop("earnfm", 3))
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
            docker.create(
                name=name,
                image="x",
                network_mode=network_mode,
                labels={**labels, LABEL_SERVICE: slug, LABEL_MANAGED: "true"},
            )
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
    def test_a_folder_that_cannot_be_flushed_still_records_the_start(self, docker):
        _deploy("honeygain")
        proxy_tunnel.stop("honeygain", 3)
        real = os.fsync
        calls = []

        def folder_fails(fd):
            calls.append(fd)
            if len(calls) % 2 == 0:  # the second fsync of each write is the folder's
                raise OSError("EIO")
            return real(fd)

        with patch.object(proxy_tunnel.os, "fsync", side_effect=folder_fails):
            proxy_tunnel.start("honeygain", 3, _socks(), None)
        assert proxy_tunnel.held() == set()
        assert docker.named("cashpilot-honeygain-p3").status == "running"

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
        """Docker restarts both tunnels (unless-stopped) but no copy (restart policy no)."""
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
        assert proxy_tunnel.stop("honeygain", 3) is True
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
            docker.create(image=image, name=name, labels={**labels, LABEL_SERVICE: slug, LABEL_MANAGED: "true"})
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
        assert proxy_tunnel.stop("honeygain", 3) is True
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
        assert proxy_tunnel.stop("honeygain", 3) is True
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
            _heartbeat()
            assert earner.id in docker.by_id and failed.status == "exited"
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
        proxy_tunnel._start_when_ready(listed, tunnel, "honeygain")
        # The fake's start acts on the model it is called on, as docker-py's acts on the container's id.
        assert listed.starts == starts and listed.status == "exited"
        assert earner.name.endswith(orchestrator.REPLACED_SUFFIX)

    def test_an_unreadable_failure_record_removes_no_earner(self, docker, tmp_path):
        """Not known whether a deploy failed: nothing is started, and nothing is removed for it."""
        _deploy("honeygain")
        earner = docker.named("cashpilot-honeygain-p3")
        tunnel = docker.named("cashpilot-tunnel-p3")
        earner.stop()
        unreadable = tmp_path / "failed-dir"
        unreadable.mkdir()  # reading a folder raises IsADirectoryError, an OSError
        with patch.object(proxy_tunnel, "FAILED_MARKER", str(unreadable)):
            proxy_tunnel._start_when_ready(earner, tunnel, "honeygain")
        assert earner.id in docker.by_id and earner.status == "exited"
