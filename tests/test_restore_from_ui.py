"""Restore a node identity backup from the dashboard (issue #741, docs/backup.md).

Before this, a .cpbackup file could only be put back with the command line
steps. These tests pin the rules of the dashboard restore:

- it only creates: a box that has the service, or one of its volumes, is
  refused, and nothing is ever written over;
- passphrase files only: a file sealed to a key is refused before any secret
  is asked for;
- owner only, with the password, and the worker checks an approval bound to
  this service, this worker and the SHA-256 of these exact bytes;
- the write goes through a helper container that never starts, into the one
  folder the socket proxy already allowed, so the proxy rule is not widened;
- the folder is read back from the restored container and compared file by
  file before the container first starts, and any failure removes everything
  the restore made;
- a file this CashPilot did not make needs the service name typed, and a file
  whose identity already runs on another box is refused, naming that box.

The archives are real tar files laid out as Docker's GET archive returns them
(the folder's own entry first, owners and modes kept), sealed with the real
bundle code.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import logging
import os
import tarfile
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402
import requests  # noqa: E402
from docker.errors import APIError, NotFound  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import (  # noqa: E402
    auth,
    catalog,
    database,
    main,
    orchestrator,
    socket_policy,
    state_backup,
    step_up,
    worker_api,
)

PASSPHRASE = "correct horse battery staple"
WORKER_KEY = "per-worker-key-restore"
CLIENT_ID = "worker-client-1"
KEY_FILE = b'{"address":"0xabc","crypto":{"cipher":"aes-128-ctr"}}'


# ---------------------------------------------------------------------------
# Docker-shaped archives and bundles
# ---------------------------------------------------------------------------


def docker_archive(folder: str, entries: list[tuple[str, str, int, int, int, bytes | str]]) -> bytes:
    """A tar shaped like Docker's GET archive of ``/.../folder``.

    ``entries``: (path below the folder, type 'dir'/'file'/'symlink', mode, uid, gid, data or link target).
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        top = tarfile.TarInfo(folder)
        top.type, top.mode, top.mtime = tarfile.DIRTYPE, 0o755, 1_700_000_000
        tar.addfile(top)
        for path, kind, mode, uid, gid, data in entries:
            info = tarfile.TarInfo(f"{folder}/{path}")
            info.mode, info.uid, info.gid, info.mtime = mode, uid, gid, 1_700_000_000
            if kind == "dir":
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            elif kind == "symlink":
                info.type, info.linkname = tarfile.SYMTYPE, str(data)
                tar.addfile(info)
            else:
                assert isinstance(data, bytes)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


MYSTERIUM_TREE = [
    ("keystore", "dir", 0o700, 1000, 1000, b""),
    ("keystore/UTC--2024-01-01--abc", "file", 0o600, 1000, 1000, KEY_FILE),
    ("keystore/current", "symlink", 0o777, 1000, 1000, "UTC--2024-01-01--abc"),
    ("myst.db", "file", 0o644, 1000, 1000, b"sqlite-ish bytes"),
]


def mysterium_bundle(*, slug: str = "mysterium", passphrase: str | None = PASSPHRASE, tree=None) -> bytes:
    payload = docker_archive("mysterium-node", tree or MYSTERIUM_TREE)
    meta = {"slug": slug, "worker": "box-a", "targets": ["/var/lib/mysterium-node"]}
    if passphrase:
        return state_backup.seal(payload, passphrase=passphrase, metadata=meta)
    _private, public = state_backup.generate_recipient_keypair()
    return state_backup.seal(payload, recipient_public_key=public, metadata=meta)


# ---------------------------------------------------------------------------
# Which services the dashboard restores
# ---------------------------------------------------------------------------


class TestWhatTheDashboardRestores:
    @pytest.mark.parametrize(
        ("slug", "volume", "target"),
        [
            ("mysterium", "mysterium-data", "/var/lib/mysterium-node"),
            ("proxybase-xyz", "proxybase-data", "/home/proxybase/.proxybase"),
            ("anyone-protocol", "anon-data", "/var/lib/anon"),
        ],
    )
    def test_the_identity_services_on_named_volumes(self, slug, volume, target):
        docker = catalog.get_service(slug)["docker"]
        assert state_backup.restore_volumes(docker) == {target: volume}

    @pytest.mark.parametrize("slug", ["storj", "sia-hostd"])
    def test_a_service_on_host_folders_is_left_to_the_command_line(self, slug):
        assert state_backup.restore_volumes(catalog.get_service(slug)["docker"]) is None

    def test_a_service_with_nothing_critical(self):
        assert state_backup.restore_volumes(catalog.get_service("honeygain")["docker"]) is None


# ---------------------------------------------------------------------------
# The archive as written and as read back
# ---------------------------------------------------------------------------


class TestTheComparison:
    def _manifest(self, tree):
        return state_backup.tree_manifest(docker_archive("mysterium-node", tree))

    def test_the_relative_archive_writes_inside_the_folder(self):
        archive = state_backup.split_archives(docker_archive("mysterium-node", MYSTERIUM_TREE))["mysterium-node"]
        with tarfile.open(fileobj=io.BytesIO(state_backup.relative_archive(archive))) as tar:
            names = tar.getnames()
        assert names == ["keystore", "keystore/UTC--2024-01-01--abc", "keystore/current", "myst.db"]

    def test_the_same_tree_has_no_differences(self):
        assert state_backup.manifest_differences(self._manifest(MYSTERIUM_TREE), self._manifest(MYSTERIUM_TREE)) == []

    def test_one_changed_byte_is_a_difference(self):
        changed = [
            *MYSTERIUM_TREE[:1],
            ("keystore/UTC--2024-01-01--abc", "file", 0o600, 1000, 1000, b"x"),
            *MYSTERIUM_TREE[2:],
        ]
        diff = state_backup.manifest_differences(self._manifest(MYSTERIUM_TREE), self._manifest(changed))
        assert diff == ["keystore/UTC--2024-01-01--abc: different content"]

    def test_another_owner_is_a_difference(self):
        """A keystore the node user cannot read starts a node with a new identity."""
        changed = [
            *MYSTERIUM_TREE[:1],
            ("keystore/UTC--2024-01-01--abc", "file", 0o600, 0, 0, KEY_FILE),
            *MYSTERIUM_TREE[2:],
        ]
        diff = state_backup.manifest_differences(self._manifest(MYSTERIUM_TREE), self._manifest(changed))
        assert diff == ["keystore/UTC--2024-01-01--abc: owner or permissions differ"]

    def test_a_missing_and_an_extra_file_are_differences(self):
        changed = [*MYSTERIUM_TREE[:3], ("planted", "file", 0o644, 1000, 1000, b"x")]
        diff = state_backup.manifest_differences(self._manifest(MYSTERIUM_TREE), self._manifest(changed))
        assert diff == ["myst.db: missing", "planted: not in the backup"]

    def test_an_empty_folder_the_image_brought_is_not(self):
        """Docker copies the image's folders into a new volume at create; ProxyBase's wallet/ is one."""
        changed = [*MYSTERIUM_TREE, ("wallet", "dir", 0o755, 1000, 1000, b"")]
        assert state_backup.manifest_differences(self._manifest(MYSTERIUM_TREE), self._manifest(changed)) == []


# ---------------------------------------------------------------------------
# A Docker with volumes that hold files, enough for the restore sequence
# ---------------------------------------------------------------------------


class FakeVolume:
    def __init__(self, docker: FakeDocker, name: str, labels: dict[str, str]):
        self.docker, self.name = docker, name
        self.attrs = {"Name": name, "Labels": dict(labels)}
        self.files: dict[str, tuple[tarfile.TarInfo, bytes | None]] = {}

    def remove(self, force=False):
        # Docker refuses to remove a volume a container mounts, force or not.
        if any(self.name in c.mounts.values() for c in self.docker.container_map.values()):
            response = requests.Response()
            response.status_code = 409
            raise APIError("volume is in use", response=response)
        self.docker.volume_map.pop(self.name, None)
        self.docker.removed.append(("volume", self.name))


class FakeVolumes:
    def __init__(self, docker: FakeDocker):
        self.docker = docker

    def get(self, name):
        if name not in self.docker.volume_map:
            raise NotFound(name)
        return self.docker.volume_map[name]

    def create(self, name, labels=None, **_kw):
        # Docker answers a create for a name that exists with the existing volume.
        if name not in self.docker.volume_map:
            self.docker.volume_map[name] = FakeVolume(self.docker, name, labels or {})
        return self.docker.volume_map[name]


class FakeContainer:
    def __init__(self, docker: FakeDocker, name: str, mounts: dict[str, str], labels=None, image="sha256:img"):
        self.docker, self.name, self.mounts = docker, name, mounts
        self.id = self.short_id = f"id-{name}"
        self.status = "created"
        self.labels = labels or {}
        self.attrs = {"Image": image}

    def _volume(self, path: str) -> FakeVolume:
        return self.docker.volume_map[self.mounts[path]]

    def put_archive(self, path, data):
        self.docker.puts.append((self.name, path))
        if self.docker.corrupt_put:
            data = data.replace(KEY_FILE, KEY_FILE[:-1] + b"!")
        volume = self._volume(path)
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            for member in tar:
                body = tar.extractfile(member).read() if member.isfile() else None
                volume.files[member.name] = (member, body)
        return True

    def get_archive(self, path):
        volume = self._volume(path)
        buf = io.BytesIO()
        folder = path.rstrip("/").rsplit("/", 1)[-1]
        with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
            top = tarfile.TarInfo(folder)
            top.type, top.mode = tarfile.DIRTYPE, 0o755
            tar.addfile(top)
            for name, (member, body) in sorted(volume.files.items()):
                copy = tarfile.TarInfo(f"{folder}/{name}")
                copy.type, copy.mode, copy.uid, copy.gid = member.type, member.mode, member.uid, member.gid
                copy.linkname, copy.size = member.linkname, member.size
                tar.addfile(copy, io.BytesIO(body) if body is not None else None)
        return [buf.getvalue()], {}

    def start(self):
        self.status = "running"
        self.docker.started.append(self.name)

    def reload(self):
        pass

    def remove(self, force=False):
        self.docker.container_map.pop(self.name, None)
        self.docker.removed.append(("container", self.name))


class FakeContainers:
    def __init__(self, docker: FakeDocker):
        self.docker = docker

    def get(self, name_or_id):
        # Docker finds a container by its name or its id.
        for container in self.docker.container_map.values():
            if name_or_id in (container.name, container.id):
                return container
        raise NotFound(name_or_id)

    def list(self, all=False, filters=None):  # noqa: A002 - docker-py's name
        label = (filters or {}).get("label", "")
        key, _, value = label.partition("=")
        return [c for c in self.docker.container_map.values() if c.labels.get(key) == value]

    def create(self, **kwargs):
        self.docker.creates.append(kwargs)
        mounts = {m["Target"]: m["Source"] for m in kwargs.get("mounts") or []}
        for target, source in mounts.items():
            if source not in self.docker.volume_map:
                raise AssertionError(f"helper mounts a volume that does not exist: {source} at {target}")
        container = FakeContainer(self.docker, kwargs["name"], mounts, kwargs.get("labels"), kwargs.get("image"))
        self.docker.container_map[container.name] = container
        return container


class FakeDocker:
    def __init__(self):
        self.volume_map: dict[str, FakeVolume] = {}
        self.container_map: dict[str, FakeContainer] = {}
        self.volumes = FakeVolumes(self)
        self.containers = FakeContainers(self)
        self.creates: list[dict] = []
        self.puts: list[tuple[str, str]] = []
        self.started: list[str] = []
        self.removed: list[tuple[str, str]] = []
        self.corrupt_put = False
        self.deploys: list[dict] = []

    def deploy_raw(self, *, slug, volumes, start=True, **kwargs):
        """deploy_raw's create-only branch: a container mounting the spec's named volumes."""
        assert start is False, "a restore must never start the container from deploy_raw"
        self.deploys.append({"slug": slug, "volumes": volumes, **kwargs})
        mounts = {}
        for source, mount in (volumes or {}).items():
            self.volumes.create(source)
            mounts[mount["bind"]] = source
        name = f"cashpilot-{slug}"
        self.container_map[name] = FakeContainer(
            self, name, mounts, {orchestrator.LABEL_SERVICE: slug}, "sha256:catalog-image"
        )
        return self.container_map[name].id


MYSTERIUM_DEPLOY = {
    "image": catalog.get_service("mysterium")["docker"]["image"],
    "volumes": {"mysterium-data": {"bind": "/var/lib/mysterium-node", "mode": "rw"}},
}


@pytest.fixture
def docker():
    fake = FakeDocker()
    wrapped = MagicMock()
    wrapped.__wrapped__ = fake.deploy_raw
    with (
        patch.object(orchestrator, "_get_client", return_value=fake),
        patch.object(orchestrator, "deploy_raw", wrapped),
        patch.object(orchestrator, "fence_gated", return_value=False),
    ):
        yield fake


def _archives(tree=None):
    return state_backup.split_archives(docker_archive("mysterium-node", tree or MYSTERIUM_TREE))


class TestTheRestoreSequence:
    def test_it_creates_writes_reads_back_and_then_starts(self, docker):
        result = orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert result["started"] is True and result["files"] == 2
        assert result["targets"] == ["/var/lib/mysterium-node"]
        assert docker.started == ["cashpilot-mysterium"]
        volume = docker.volume_map["mysterium-data"]
        member, body = volume.files["keystore/UTC--2024-01-01--abc"]
        assert body == KEY_FILE and (member.uid, member.gid, member.mode & 0o777) == (1000, 1000, 0o600)
        # The helper is gone; the restored container and its volume stay.
        assert set(docker.container_map) == {"cashpilot-mysterium"}

    def test_the_volume_is_created_new_and_proven_new(self, docker):
        orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert docker.volume_map["mysterium-data"].attrs["Labels"][orchestrator.LABEL_RESTORE]

    def test_every_write_goes_through_the_never_started_helper_into_the_proxys_one_folder(self, docker):
        """No wider socket proxy rule: the write lands where the proxy already allowed it."""
        orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert docker.puts == [("cashpilot-mysterium.restore", orchestrator.RESTORE_WRITE_DIR)]
        helper = next(c for c in docker.creates if c["name"].endswith(".restore"))
        assert helper["network_mode"] == "none" and helper["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in helper["security_opt"]
        assert {m["Target"]: m["Source"] for m in helper["mounts"]} == {
            orchestrator.RESTORE_WRITE_DIR: "mysterium-data"
        }
        assert "cashpilot-mysterium.restore" not in docker.started
        assert ("container", "cashpilot-mysterium.restore") in docker.removed

    def test_the_proxy_policy_still_allows_writes_into_one_folder_only(self):
        policy = socket_policy.policy()
        assert f"allowed_paths: [{orchestrator.RESTORE_WRITE_DIR}]" in policy
        assert "/var/lib/mysterium-node" not in policy.split("container_archive:")[1].split("exec:")[0]

    def test_the_deploy_goes_through_deploy_raw_create_only(self, docker):
        orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert docker.deploys[0]["image"] == MYSTERIUM_DEPLOY["image"]

    def test_a_box_that_has_the_service_is_refused_and_nothing_is_made(self, docker):
        docker.container_map["cashpilot-mysterium"] = FakeContainer(
            docker, "cashpilot-mysterium", {}, {orchestrator.LABEL_SERVICE: "mysterium"}
        )
        with pytest.raises(orchestrator.RestoreError, match="already has a container"):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert docker.volume_map == {} and docker.creates == [] and docker.puts == []

    def test_an_existing_volume_is_refused_and_left_alone(self, docker):
        docker.volumes.create("mysterium-data", labels={"someone": "else"})
        with pytest.raises(orchestrator.RestoreError, match="already exists"):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert "mysterium-data" in docker.volume_map and docker.puts == [] and docker.removed == []

    def test_a_volume_hidden_from_the_check_is_not_used_or_removed(self, docker):
        """The proxy hides volumes the worker does not own; Docker would hand that one back on create."""
        hidden = FakeVolume(docker, "mysterium-data", {"theirs": "1"})
        real_get = docker.volumes.get

        def get(name):
            if name == "mysterium-data" and docker.volume_map.get(name) is hidden:
                raise NotFound(name)
            return real_get(name)

        docker.volume_map["mysterium-data"] = hidden
        with (
            patch.object(docker.volumes, "get", side_effect=get),
            pytest.raises(orchestrator.RestoreError, match="already existed"),
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert docker.volume_map["mysterium-data"] is hidden and docker.puts == []

    def test_a_read_back_that_differs_undoes_everything(self, docker):
        docker.corrupt_put = True
        with pytest.raises(orchestrator.RestoreError, match="does not read back as the backup.*removed"):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert docker.started == []
        assert docker.container_map == {} and docker.volume_map == {}

    def test_a_docker_failure_mid_write_undoes_everything(self, docker):
        with (
            patch.object(FakeContainer, "put_archive", side_effect=RuntimeError("boom")),
            pytest.raises(orchestrator.RestoreError, match="undone"),
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert docker.container_map == {} and docker.volume_map == {} and docker.started == []

    def test_a_backup_of_other_folders_is_refused(self, docker):
        other = state_backup.split_archives(docker_archive("proxybase", MYSTERIUM_TREE))
        with pytest.raises(orchestrator.RestoreError, match="not a backup of mysterium"):
            orchestrator.restore_state("mysterium", other, MYSTERIUM_DEPLOY)
        assert docker.creates == [] and docker.volume_map == {}

    def test_storj_is_left_to_the_command_line(self, docker):
        with pytest.raises(orchestrator.RestoreError, match="command line"):
            orchestrator.restore_state("storj", {"identity": b""}, {})

    def test_a_name_another_deploy_took_meanwhile_is_left_alone(self, docker):
        """deploy_raw refuses with 409 because the name is taken: that container is someone else's."""

        def taken(**_kw):
            theirs = FakeContainer(
                docker,
                "cashpilot-mysterium",
                {"/var/lib/mysterium-node": "mysterium-data"},
                {orchestrator.LABEL_SERVICE: "mysterium"},
            )
            theirs.status = "running"
            docker.container_map[theirs.name] = theirs
            raise orchestrator.ContainerRuntimeError("cashpilot-mysterium already exists", 409)

        orchestrator.deploy_raw.__wrapped__ = taken
        with pytest.raises(orchestrator.RestoreError) as caught:
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert docker.container_map["cashpilot-mysterium"].status == "running"
        assert ("container", "cashpilot-mysterium") not in docker.removed
        # Its volume is in use: kept, and the owner is not told to remove it by hand.
        assert "mysterium-data" in docker.volume_map and "by hand" not in str(caught.value)

    def test_the_helper_a_dead_restore_left_is_removed_and_the_restore_goes_on(self, docker):
        stale = FakeContainer(docker, "cashpilot-mysterium.restore", {}, {orchestrator.LABEL_RESTORE: "helper"})
        docker.container_map[stale.name] = stale
        result = orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert result["started"] is True and ("container", "cashpilot-mysterium.restore") in docker.removed

    def test_a_container_of_the_helpers_name_that_is_not_a_helper_refuses(self, docker):
        other = FakeContainer(docker, "cashpilot-mysterium.restore", {}, {"someone": "else"})
        docker.container_map[other.name] = other
        with pytest.raises(orchestrator.RestoreError, match="already exists"):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert docker.container_map["cashpilot-mysterium.restore"] is other

    def test_one_restore_at_a_time_on_a_box(self, docker):
        with orchestrator._RESTORE_LOCK, pytest.raises(orchestrator.RestoreError, match="another restore is running"):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert docker.creates == [] and docker.volume_map == {}


@pytest.fixture
def gated(docker, tmp_path, monkeypatch):
    """Mysterium as it really runs: fence-gated, with the guard's records on disk."""
    # The docker fixture patched fence_gated already; re-patched on its mock, so
    # the real function comes back whatever order the patches unwind in.
    orchestrator.fence_gated.side_effect = lambda slug: slug == "mysterium"
    monkeypatch.setattr(orchestrator, "FAILED_MARKER", str(tmp_path / "failed"))
    monkeypatch.setattr(orchestrator, "STOPPED_MARKER", str(tmp_path / "stopped"))
    monkeypatch.setattr(orchestrator, "IDENTITY_DIR", str(tmp_path / "identity"))
    monkeypatch.setattr(orchestrator, "_FAILED_UNWRITTEN", {})
    monkeypatch.setattr(orchestrator, "_MISMATCH_HELD", {})
    fence: dict[str, Any] = {"problem": None, "asked": 0}

    def require_fence(slug):
        fence["asked"] += 1
        if fence["problem"]:
            raise orchestrator.ContainerNetworkError(fence["problem"])

    monkeypatch.setattr(orchestrator, "_require_fence", require_fence)
    docker.fence = fence
    real = docker.deploy_raw

    def deploy_raw(**kwargs):
        docker.locked_at_create = orchestrator.GATED_DEPLOY_LOCK.locked()
        return real(**kwargs)

    orchestrator.deploy_raw.__wrapped__ = deploy_raw
    return docker


class TestAFenceGatedRestore:
    NAME = "cashpilot-mysterium"

    def test_it_holds_the_guards_lock_and_starts_only_behind_the_fence(self, gated):
        result = orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert gated.locked_at_create is True and gated.fence["asked"] == 1
        assert result["started"] is True and gated.started == [self.NAME]
        assert self.NAME not in orchestrator.deploy_failed() and self.NAME not in orchestrator.user_stopped()

    def test_without_the_fence_it_waits_created_for_the_guard(self, gated):
        gated.fence["problem"] = "the fence is not confirmed"
        result = orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert result["started"] is False and gated.started == []
        assert gated.container_map[self.NAME].status == "created"
        # Checked data: the guard may start it once the fence holds.
        assert self.NAME not in orchestrator.deploy_failed() and self.NAME not in orchestrator.user_stopped()

    def test_while_the_data_is_written_the_guard_is_held_off_on_disk(self, gated):
        """A worker that dies mid-write leaves a created node the guard must never start."""
        seen = []
        real_put = FakeContainer.put_archive

        def put(container, path, data):
            seen.append(self.NAME in orchestrator._failed_on_disk())
            return real_put(container, path, data)

        with patch.object(FakeContainer, "put_archive", put):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert seen == [True]
        assert self.NAME not in orchestrator.deploy_failed()

    def test_a_failed_restore_whose_container_stays_is_never_started_by_the_guard(self, gated):
        gated.corrupt_put = True
        with (
            patch.object(FakeContainer, "remove", side_effect=RuntimeError("proxy down")),
            pytest.raises(orchestrator.RestoreError, match="by hand"),
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert gated.container_map[self.NAME].status == "created"
        assert self.NAME in orchestrator._failed_on_disk()

    def test_a_failed_restore_that_removed_everything_leaves_no_hold(self, gated):
        gated.corrupt_put = True
        with pytest.raises(orchestrator.RestoreError):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert gated.container_map == {} and self.NAME not in orchestrator.deploy_failed()

    def test_a_leftover_deploy_raws_roll_back_could_not_remove_stays_held(self, gated):
        """deploy_raw marks such a leftover failed; the restore's own cleanup must not lift that."""

        def half_made(**_kw):
            left = FakeContainer(gated, self.NAME, {}, {orchestrator.LABEL_SERVICE: "mysterium"})
            gated.container_map[self.NAME] = left
            orchestrator._mark_failed(self.NAME, True)
            raise orchestrator.ContainerRuntimeError("create failed; the leftover could not be removed")

        orchestrator.deploy_raw.__wrapped__ = half_made
        with pytest.raises(orchestrator.RestoreError):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert self.NAME in orchestrator._failed_on_disk()

    def test_an_old_identity_hold_does_not_stop_the_restored_node(self, gated):
        """The owner removed a node held on the wrong keystore, then restored it: the restore proved the data."""
        orchestrator._remember_identity(self.NAME, "MISMATCH its identity is 0xnew, not 0xold")
        orchestrator._MISMATCH_HELD[self.NAME] = "its identity is 0xnew, not 0xold"
        orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert orchestrator.identity_problem(gated.container_map[self.NAME]) is None
        assert not os.path.exists(orchestrator._identity_file(self.NAME))


# ---------------------------------------------------------------------------
# The worker endpoint
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _noop(_app):
    yield


PROXYBASE = catalog.get_service("proxybase-xyz")["docker"]
PROXYBASE_SPEC = {
    "image": PROXYBASE["image"],
    "command": PROXYBASE["command"],
    "volumes": {"proxybase-data": {"bind": "/home/proxybase/.proxybase"}},
}


def proxybase_bundle(*, passphrase: str | None = PASSPHRASE, slug="proxybase-xyz") -> bytes:
    payload = docker_archive(".proxybase", [("wallet.json", "file", 0o600, 1000, 1000, b'{"k":"secret"}')])
    meta = {"slug": slug, "worker": "box-a", "targets": ["/home/proxybase/.proxybase"]}
    if passphrase:
        return state_backup.seal(payload, passphrase=passphrase, metadata=meta)
    _private, public = state_backup.generate_recipient_keypair()
    return state_backup.seal(payload, recipient_public_key=public, metadata=meta)


@pytest.fixture
def worker(monkeypatch):
    worker_api.app.router.lifespan_context = _noop
    monkeypatch.setattr(worker_api, "API_KEY", "wk-test")
    monkeypatch.setattr(worker_api, "_worker_key", WORKER_KEY)
    monkeypatch.setattr(worker_api, "CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(worker_api, "_validate_runtime", lambda runtime: None)
    monkeypatch.setattr(worker_api.lan_fence, "refresh_outside", lambda: None)
    calls: list[tuple[str, dict, dict]] = []

    def fake_restore(slug, archives, deploy):
        calls.append((slug, archives, deploy))
        return {"container_id": "cid", "targets": ["/home/proxybase/.proxybase"], "files": 1, "started": True}

    monkeypatch.setattr(worker_api.orchestrator, "restore_state", fake_restore)
    client = TestClient(worker_api.app, raise_server_exceptions=False)

    def post(slug, bundle, *, approval=None, spec=None, passphrase=PASSPHRASE, raw=None):
        digest = hashlib.sha256(bundle).hexdigest()
        if approval is None:
            approval = step_up.sign(WORKER_KEY, step_up.ACTION_RESTORE, step_up.restore_target(slug, CLIENT_ID, digest))
        body = {
            **(spec or PROXYBASE_SPEC),
            "bundle_b64": base64.b64encode(bundle).decode(),
            "passphrase": passphrase,
            "approval": approval,
        }
        headers = {"Authorization": f"Bearer {WORKER_KEY}"}
        if raw is not None:
            return client.post(f"/api/containers/{slug}/restore", content=raw, headers=headers)
        return client.post(f"/api/containers/{slug}/restore", json=body, headers=headers)

    post.calls = calls
    return post


def _detail(resp):
    detail = resp.json().get("detail")
    return detail.get("message") if isinstance(detail, dict) else detail


class TestTheWorker:
    def test_a_good_restore_reaches_the_restore_with_the_catalogs_folders(self, worker):
        bundle = proxybase_bundle()
        resp = worker("proxybase-xyz", bundle)
        assert resp.status_code == 200, resp.text
        assert resp.json()["bundle_sha256"] == hashlib.sha256(bundle).hexdigest()
        slug, archives, deploy = worker.calls[0]
        assert slug == "proxybase-xyz" and set(archives) == {".proxybase"}
        assert deploy["image"] == PROXYBASE["image"]

    def test_the_heartbeat_names_the_feature_the_ui_looks_for(self):
        import inspect

        assert '"state_restore"' in inspect.getsource(worker_api._send_heartbeat)

    def test_an_approval_for_another_file_is_refused(self, worker):
        other = step_up.sign(
            WORKER_KEY, step_up.ACTION_RESTORE, step_up.restore_target("proxybase-xyz", CLIENT_ID, "0" * 64)
        )
        resp = worker("proxybase-xyz", proxybase_bundle(), approval=other)
        assert resp.status_code == 403 and resp.json()["detail"]["error"] == "step_up_rejected"
        assert worker.calls == []

    def test_an_approval_for_another_worker_is_refused(self, worker):
        bundle = proxybase_bundle()
        target = step_up.restore_target("proxybase-xyz", "another-box", hashlib.sha256(bundle).hexdigest())
        resp = worker("proxybase-xyz", bundle, approval=step_up.sign(WORKER_KEY, step_up.ACTION_RESTORE, target))
        assert resp.status_code == 403 and worker.calls == []

    def test_a_deploy_approval_cannot_restore(self, worker):
        bundle = proxybase_bundle()
        target = step_up.restore_target("proxybase-xyz", CLIENT_ID, hashlib.sha256(bundle).hexdigest())
        resp = worker("proxybase-xyz", bundle, approval=step_up.sign(WORKER_KEY, step_up.ACTION_CUSTOM_IMAGE, target))
        assert resp.status_code == 403 and worker.calls == []

    def test_the_api_key_alone_cannot_restore(self, worker):
        """A stolen fleet key has no worker key to sign with."""
        bundle = proxybase_bundle()
        target = step_up.restore_target("proxybase-xyz", CLIENT_ID, hashlib.sha256(bundle).hexdigest())
        resp = worker("proxybase-xyz", bundle, approval=step_up.sign("wk-test", step_up.ACTION_RESTORE, target))
        assert resp.status_code == 403 and worker.calls == []

    def test_an_approval_is_good_once(self, worker):
        bundle = proxybase_bundle()
        target = step_up.restore_target("proxybase-xyz", CLIENT_ID, hashlib.sha256(bundle).hexdigest())
        approval = step_up.sign(WORKER_KEY, step_up.ACTION_RESTORE, target)
        assert worker("proxybase-xyz", bundle, approval=approval).status_code == 200
        assert worker("proxybase-xyz", bundle, approval=approval).status_code == 403

    def test_a_custom_image_is_refused_even_with_an_approval(self, worker):
        resp = worker("proxybase-xyz", proxybase_bundle(), spec={**PROXYBASE_SPEC, "image": "attacker/x:1"})
        assert resp.status_code == 403 and worker.calls == []

    def test_a_key_sealed_file_is_refused(self, worker):
        resp = worker("proxybase-xyz", proxybase_bundle(passphrase=None))
        assert resp.status_code == 400 and "command line" in _detail(resp) and worker.calls == []

    def test_a_backup_of_another_service_is_refused(self, worker):
        resp = worker("proxybase-xyz", proxybase_bundle(slug="mysterium"))
        assert resp.status_code == 400 and "not of proxybase-xyz" in _detail(resp) and worker.calls == []

    def test_a_wrong_passphrase_is_refused_and_never_echoed(self, worker, caplog):
        caplog.set_level(logging.DEBUG)
        resp = worker("proxybase-xyz", proxybase_bundle(), passphrase="the wrong one, kept secret")
        assert resp.status_code == 400 and worker.calls == []
        assert "kept secret" not in resp.text and "kept secret" not in caplog.text

    def test_storj_is_refused_with_the_command_line(self, worker):
        resp = worker(
            "storj", proxybase_bundle(slug="storj"), spec={"image": catalog.get_service("storj")["docker"]["image"]}
        )
        assert resp.status_code in (400, 409) and worker.calls == []

    def test_a_body_bigger_than_any_backup_is_refused_unread(self, worker):
        resp = worker("proxybase-xyz", b"", raw=b"x" * (worker_api.MAX_RESTORE_BODY + 1))
        assert resp.status_code == 413 and worker.calls == []


# ---------------------------------------------------------------------------
# The dashboard
# ---------------------------------------------------------------------------

OWNER_PASSWORD = "the owner's own password"


@pytest.fixture
def ui(tmp_path):
    """The UI with a real database, one owner, two online workers with the restore feature."""
    sent: list[dict] = []

    async def proxy(worker_id, method, path, *, json=None, **kwargs):
        sent.append({"worker_id": worker_id, "path": path, "json": dict(json or {})})
        return {"container_id": "cid", "files": 2, "targets": ["/var/lib/mysterium-node"], "started": True}

    workers = [
        {
            "id": 1,
            "name": "box-a",
            "status": "online",
            "client_id": "client-a",
            "url": "https://a",
            "system_info": "{}",
        },
        {"id": 2, "name": "box-b", "status": "online", "client_id": "client-b", "url": "http://b", "system_info": "{}"},
    ]
    state: dict[str, Any] = {"runs_on": {}, "user": None}

    async def get_worker(worker_id):
        return next((w for w in workers if w["id"] == worker_id), None)

    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"),
    ):
        asyncio.run(database.init_db())
        uid = asyncio.run(database.create_user("owner", auth.hash_password(OWNER_PASSWORD), "owner"))
        state["user"] = {"uid": uid, "u": "owner", "r": "owner"}
        with (
            patch.object(auth, "get_current_user", side_effect=lambda request: state["user"]),
            patch.object(main.database, "list_workers", AsyncMock(return_value=workers)),
            patch.object(main.database, "get_worker", side_effect=get_worker),
            patch.object(
                main, "_worker_features", AsyncMock(return_value={"state_restore", "fence_gated", "instances"})
            ),
            patch.object(main.placement, "runs_on", side_effect=lambda ws: state["runs_on"]),
            patch.object(main, "_confirmed_worker_key", AsyncMock(return_value=WORKER_KEY)),
            patch.object(main, "_resolve_worker_id", AsyncMock(side_effect=lambda wid, *a, **k: wid)),
            patch.object(main, "_proxy_to_worker", proxy),
            patch.object(main.database, "record_health_event", AsyncMock()),
            patch.object(main, "_spawn", lambda coro: coro.close()),
            patch.object(main.metrics, "record_container_lifecycle", lambda *a: None),
        ):
            from app import login_rate_limit

            login_rate_limit._login_attempts.clear()
            main._restore_uploads.clear()
            client = TestClient(main.app, raise_server_exceptions=False)
            client.sent = sent  # type: ignore[attr-defined]
            client.state = state  # type: ignore[attr-defined]
            client.tmp = tmp_path  # type: ignore[attr-defined]
            yield client
            main._restore_uploads.clear()
            login_rate_limit._login_attempts.clear()


def _upload(ui, bundle):
    return ui.post("/api/restore/upload", content=bundle, headers={"Content-Type": "application/octet-stream"})


def _restore(ui, upload_id, worker_id=1, **extra):
    body = {"upload_id": upload_id, "worker_id": worker_id, "passphrase": PASSPHRASE, **extra}
    return ui.post("/api/restore", json=body)


def _audit():
    return [(e["action"], e["outcome"]) for e in asyncio.run(database.get_audit_events())]


def _uploads_on_disk(ui):
    folder = ui.tmp / "restore-uploads"
    return sorted(os.listdir(folder)) if folder.exists() else []


class TestTheUpload:
    def test_it_previews_what_will_be_created_where(self, ui):
        resp = _upload(ui, mysterium_bundle())
        assert resp.status_code == 200, resp.text
        preview = resp.json()
        assert preview["slug"] == "mysterium" and preview["container"] == "cashpilot-mysterium"
        assert preview["creates"] == [{"target": "/var/lib/mysterium-node", "volume": "mysterium-data"}]
        assert preview["known"] is False
        assert [(w["name"], w["ok"], w["plain_http"]) for w in preview["workers"]] == [
            ("box-a", True, False),
            ("box-b", True, True),
        ]

    def test_a_viewer_cannot_upload(self, ui):
        ui.state["user"] = {"uid": 9, "u": "viewer", "r": "viewer"}
        assert _upload(ui, mysterium_bundle()).status_code == 403
        assert _uploads_on_disk(ui) == []

    def test_the_api_key_cannot_upload(self, ui):
        ui.state["user"] = {"uid": 0, "u": "api", "r": "owner"}
        assert _upload(ui, mysterium_bundle()).status_code in (401, 403)

    def test_a_file_bigger_than_any_backup_is_refused_and_not_kept(self, ui):
        with patch.object(main, "RESTORE_UPLOAD_MAX", 1024):
            resp = _upload(ui, mysterium_bundle() + b"\0" * 2048)
        assert resp.status_code == 413 and _uploads_on_disk(ui) == []

    def test_a_key_sealed_file_is_refused_before_any_secret_is_asked(self, ui):
        resp = _upload(ui, mysterium_bundle(passphrase=None))
        assert resp.status_code == 400 and "command line" in resp.json()["detail"]
        assert _uploads_on_disk(ui) == []

    def test_a_storj_backup_points_to_the_command_line(self, ui):
        payload = docker_archive("identity", [("ca.cert", "file", 0o644, 0, 0, b"cert")])
        bundle = state_backup.seal(payload, passphrase=PASSPHRASE, metadata={"slug": "storj"})
        resp = _upload(ui, bundle)
        assert resp.status_code == 400 and "command line" in resp.json()["detail"]
        assert _uploads_on_disk(ui) == []

    def test_junk_is_refused(self, ui):
        assert _upload(ui, b"not a bundle at all").status_code == 400
        assert _uploads_on_disk(ui) == []

    def test_the_file_is_kept_private(self, ui):
        _upload(ui, mysterium_bundle())
        (name,) = _uploads_on_disk(ui)
        assert os.stat(ui.tmp / "restore-uploads" / name).st_mode & 0o777 == 0o600
        assert os.stat(ui.tmp / "restore-uploads").st_mode & 0o777 == 0o700


class TestTheRestoreRoute:
    def test_no_password_asks_for_one_and_sends_nothing(self, ui):
        upload = _upload(ui, mysterium_bundle()).json()
        resp = _restore(ui, upload["upload_id"], confirm_name="Mysterium")
        assert resp.status_code == 403 and resp.json()["detail"]["error"] == "step_up_required"
        assert ui.sent == []

    def test_a_wrong_password_sends_nothing_and_is_audited(self, ui):
        upload = _upload(ui, mysterium_bundle()).json()
        resp = _restore(ui, upload["upload_id"], confirm_name="Mysterium", step_up_password="nope")
        assert resp.status_code == 403 and ui.sent == []
        assert ("restore-backup", "failed") in _audit()

    def test_the_api_key_cannot_restore(self, ui):
        upload = _upload(ui, mysterium_bundle()).json()
        ui.state["user"] = {"uid": 0, "u": "api", "r": "owner"}
        resp = _restore(ui, upload["upload_id"], confirm_name="Mysterium", step_up_password=OWNER_PASSWORD)
        assert resp.status_code in (401, 403) and ui.sent == []

    def test_a_file_this_cashpilot_did_not_make_needs_the_name_typed(self, ui):
        upload = _upload(ui, mysterium_bundle()).json()
        resp = _restore(ui, upload["upload_id"], step_up_password=OWNER_PASSWORD)
        assert resp.status_code == 400 and resp.json()["detail"]["error"] == "restore_confirm_required"
        assert ui.sent == [] and ("restore", "refused") in _audit()

    def test_the_right_password_sends_an_approval_for_this_file_on_this_worker(self, ui):
        bundle = mysterium_bundle()
        upload = _upload(ui, bundle).json()
        resp = _restore(ui, upload["upload_id"], confirm_name="Mysterium", step_up_password=OWNER_PASSWORD)
        assert resp.status_code == 200, resp.text
        (call,) = ui.sent
        assert call["worker_id"] == 1 and call["path"] == "/api/containers/mysterium/restore"
        sent = call["json"]
        digest = hashlib.sha256(bundle).hexdigest()
        assert base64.b64decode(sent["bundle_b64"]) == bundle and sent["passphrase"] == PASSPHRASE
        step_up.check(
            WORKER_KEY,
            sent["approval"],
            step_up.ACTION_RESTORE,
            step_up.restore_target("mysterium", "client-a", digest),
        )
        assert "step_up_password" not in sent
        # Used once: the file is gone, the ledger knows it, the audit says so.
        assert _uploads_on_disk(ui) == [] and main._restore_uploads == {}
        assert [r["source"] for r in asyncio.run(database.backup_records(digest))] == ["restore"]
        assert ("restore-backup", "confirmed") in _audit() and ("restore", "restored") in _audit()

    def test_the_passphrase_is_never_stored(self, ui):
        upload = _upload(ui, mysterium_bundle()).json()
        _restore(ui, upload["upload_id"], confirm_name="Mysterium", step_up_password=OWNER_PASSWORD)
        with open(database.DB_PATH, "rb") as fh:
            assert PASSPHRASE.encode() not in fh.read()

    def test_a_file_this_cashpilot_exported_needs_no_typed_name(self, ui):
        bundle = mysterium_bundle()
        asyncio.run(database.record_backup("mysterium", 2, hashlib.sha256(bundle).hexdigest(), "export"))
        upload = _upload(ui, bundle).json()
        assert upload["known"] is True and upload["history"][0]["worker"] == "box-b"
        resp = _restore(ui, upload["upload_id"], step_up_password=OWNER_PASSWORD)
        assert resp.status_code == 200, resp.text

    def test_an_identity_live_on_another_box_is_refused_naming_it(self, ui):
        bundle = mysterium_bundle()
        asyncio.run(database.record_backup("mysterium", 2, hashlib.sha256(bundle).hexdigest(), "export"))
        ui.state["runs_on"] = {"mysterium": [{"worker_id": 2}]}
        upload = _upload(ui, bundle).json()
        assert upload["live_on"] == ["box-b"]
        resp = _restore(ui, upload["upload_id"], worker_id=1, step_up_password=OWNER_PASSWORD)
        assert resp.status_code == 409 and "box-b" in _detail(resp)
        assert ui.sent == [] and ("restore", "refused") in _audit()

    def test_a_box_that_runs_the_service_is_refused(self, ui):
        ui.state["runs_on"] = {"mysterium": [{"worker_id": 1}]}
        upload = _upload(ui, mysterium_bundle()).json()
        resp = _restore(ui, upload["upload_id"], confirm_name="mysterium", step_up_password=OWNER_PASSWORD)
        assert resp.status_code == 409 and "already runs" in _detail(resp) and ui.sent == []

    def test_a_box_with_an_old_worker_is_refused(self, ui):
        upload = _upload(ui, mysterium_bundle()).json()
        with patch.object(main, "_worker_features", AsyncMock(return_value={"instances"})):
            resp = _restore(ui, upload["upload_id"], confirm_name="Mysterium", step_up_password=OWNER_PASSWORD)
        assert resp.status_code == 409 and "update it" in _detail(resp) and ui.sent == []

    def test_another_users_upload_is_not_theirs_to_restore(self, ui):
        upload = _upload(ui, mysterium_bundle()).json()
        ui.state["user"] = {"uid": 999, "u": "owner2", "r": "owner"}
        assert _restore(ui, upload["upload_id"], confirm_name="Mysterium").status_code == 404

    def test_a_worker_refusal_is_audited_and_the_file_is_gone(self, ui):
        from fastapi import HTTPException

        upload = _upload(ui, mysterium_bundle()).json()
        with patch.object(main, "_proxy_to_worker", AsyncMock(side_effect=HTTPException(409, "volume exists"))):
            resp = _restore(ui, upload["upload_id"], confirm_name="Mysterium", step_up_password=OWNER_PASSWORD)
        assert resp.status_code == 409
        assert ("restore", "failed") in _audit() and _uploads_on_disk(ui) == []


class TestTheRestoreRouteGuards:
    def test_a_plain_http_box_needs_the_owner_to_accept_it(self, ui):
        """The passphrase crosses the network unencrypted to an http:// worker: never without an explicit yes."""
        upload = _upload(ui, mysterium_bundle()).json()
        resp = _restore(ui, upload["upload_id"], worker_id=2, confirm_name="Mysterium", step_up_password=OWNER_PASSWORD)
        assert resp.status_code == 400 and resp.json()["detail"]["error"] == "restore_plain_http"
        assert ui.sent == [] and ("restore", "refused") in _audit()

    def test_with_the_owners_yes_it_goes_and_the_audit_says_so(self, ui):
        upload = _upload(ui, mysterium_bundle()).json()
        resp = _restore(
            ui,
            upload["upload_id"],
            worker_id=2,
            confirm_name="Mysterium",
            step_up_password=OWNER_PASSWORD,
            allow_plain_http=True,
        )
        assert resp.status_code == 200, resp.text
        (row,) = [e for e in asyncio.run(database.get_audit_events()) if e["outcome"] == "restored"]
        assert "plain HTTP" in row["detail"]

    def test_an_unknown_file_from_a_box_that_runs_the_service_is_refused(self, ui):
        """A file made before the ledger: its header names box-a, and box-a runs Mysterium now."""
        ui.state["runs_on"] = {"mysterium": [{"worker_id": 1}]}
        upload = _upload(ui, mysterium_bundle()).json()
        assert upload["known"] is False and upload["live_on"] == ["box-a"]
        resp = _restore(
            ui,
            upload["upload_id"],
            worker_id=2,
            confirm_name="Mysterium",
            step_up_password=OWNER_PASSWORD,
            allow_plain_http=True,
        )
        assert resp.status_code == 409 and "box-a" in _detail(resp) and ui.sent == []

    def test_an_unknown_file_names_where_the_service_runs_now(self, ui):
        ui.state["runs_on"] = {"mysterium": [{"worker_id": 2}]}
        upload = _upload(ui, mysterium_bundle()).json()
        assert upload["live_on"] == [] and upload["runs_on"] == ["box-b"]

    def test_a_file_already_being_restored_is_refused(self, ui):
        """Two tabs, two boxes, one file: the second waits for the first, or the identity lands twice."""
        bundle = mysterium_bundle()
        upload = _upload(ui, bundle).json()
        main._restore_inflight.add(hashlib.sha256(bundle).hexdigest())
        try:
            resp = _restore(ui, upload["upload_id"], confirm_name="Mysterium", step_up_password=OWNER_PASSWORD)
        finally:
            main._restore_inflight.clear()
        assert resp.status_code == 409 and "already being restored" in _detail(resp) and ui.sent == []

    def test_a_restore_leaves_nothing_in_flight(self, ui):
        upload = _upload(ui, mysterium_bundle()).json()
        _restore(ui, upload["upload_id"], confirm_name="Mysterium", step_up_password=OWNER_PASSWORD)
        assert main._restore_inflight == set()

    def test_a_restore_whose_outcome_is_unknown_is_recorded_on_that_box(self, ui):
        """The worker may finish after the dashboard gave up: a later restore elsewhere must still see it."""
        from fastapi import HTTPException

        bundle = mysterium_bundle()
        upload = _upload(ui, bundle).json()
        with patch.object(main, "_proxy_to_worker", AsyncMock(side_effect=HTTPException(504, "no answer"))):
            resp = _restore(ui, upload["upload_id"], confirm_name="Mysterium", step_up_password=OWNER_PASSWORD)
        assert resp.status_code == 504
        rows = asyncio.run(database.backup_records(hashlib.sha256(bundle).hexdigest()))
        assert [(r["worker_id"], r["source"]) for r in rows] == [(1, "restore")]

    def test_a_refused_restore_is_not_recorded(self, ui):
        from fastapi import HTTPException

        bundle = mysterium_bundle()
        upload = _upload(ui, bundle).json()
        with patch.object(main, "_proxy_to_worker", AsyncMock(side_effect=HTTPException(409, "volume exists"))):
            _restore(ui, upload["upload_id"], confirm_name="Mysterium", step_up_password=OWNER_PASSWORD)
        assert asyncio.run(database.backup_records(hashlib.sha256(bundle).hexdigest())) == []


class TestTheExportHook:
    def test_an_export_records_the_files_hash_so_its_restore_needs_no_typed_name(self, ui):
        bundle = mysterium_bundle()
        answer = {"bundle_b64": base64.b64encode(bundle).decode(), "state_id": "fp", "targets": [], "bytes": 1}
        box = {"worker_id": 1, "name": "box-a", "workers": []}
        with (
            patch.object(main, "_backup_box", AsyncMock(return_value=box)),
            patch.object(main, "_worker_features", AsyncMock(return_value={"state_backup"})),
            patch.object(main, "_proxy_to_worker", AsyncMock(return_value=answer)),
        ):
            resp = ui.post(
                "/api/payout-registry/mysterium/backup-export",
                json={"worker_id": 1, "passphrase": PASSPHRASE, "passphrase_repeat": PASSPHRASE},
            )
        assert resp.status_code == 200, resp.text
        rows = asyncio.run(database.backup_records(hashlib.sha256(bundle).hexdigest()))
        assert [(r["slug"], r["worker_id"], r["source"]) for r in rows] == [("mysterium", 1, "export")]
        assert _upload(ui, bundle).json()["known"] is True

    def test_backup_rows_are_not_retired_when_the_service_goes(self, ui):
        """The row is the record of a file that exists, not an id a container runs with."""

        async def run():
            await database.record_backup("mysterium", 1, "a" * 64, "export")
            db = await database._get_db()
            try:
                await database._retire_identity_rows(db, "mysterium", 1)
                await db.commit()
            finally:
                await db.close()
            return [r for r in await database.list_identities() if r["kind"] == "backup"]

        rows = asyncio.run(run())
        assert rows and rows[0]["status"] == "active"

    def test_a_bad_hash_is_not_recorded(self, ui):
        with pytest.raises(ValueError):
            asyncio.run(database.record_backup("mysterium", 1, "not-a-hash", "export"))
