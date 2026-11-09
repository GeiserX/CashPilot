"""One shared tunnel per proxy on a worker (app/proxy_tunnel.py, docs/proxies.md).

These run the real module against a small in-memory Docker: containers have
labels, a status, a NetworkMode, a secret volume and a ready file, so a test
can follow every container through a deploy, a stop, a tunnel replacement or a
migration. What only a real daemon can prove (fail closed, the capture, RAM)
is in scripts/proxy_leak_test.sh, scripts/proxy_leak_test_tailscale.sh and
scripts/proxy_shared_tunnel_lab.sh.
"""

from __future__ import annotations

import io
import itertools
import json
import os
import tarfile
import threading
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

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
        }
        self.starts = 0

    # --- lifecycle
    def _alive(self):
        if self.id not in self._d.by_id:
            raise NotFound(self.name)

    def reload(self):
        self._alive()

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
    def deploy_raw(*, slug, image, env, network_mode, labels, name, **_kw):
        all_labels = {**labels, LABEL_SERVICE: slug, LABEL_MANAGED: "true", "cashpilot.deployed-by": "worker"}
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

    def test_a_stopped_pair_moves_and_stays_stopped(self, docker):
        _legacy_pair(docker, "honeygain")
        _legacy_pair(docker, "earnfm", running=False)
        proxy_tunnel.migrate_legacy()
        # Recreated inside the shared tunnel but never started.
        assert docker.named("cashpilot-earnfm-p3").status == "created"
        assert proxy_tunnel.held() == {"cashpilot-earnfm-p3"}
        with patch.object(orchestrator, "_collect_stats_bulk", return_value={}):
            proxy_tunnel.status()
        assert docker.named("cashpilot-earnfm-p3").status == "created"

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
