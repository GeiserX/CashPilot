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
import json
import logging
import os
import posixpath
import re
import tarfile
import urllib.parse
from contextlib import ExitStack, asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import DEFAULT, AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import httpx  # noqa: E402
import pytest  # noqa: E402
import requests  # noqa: E402
from docker.errors import APIError, NotFound  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import (  # noqa: E402
    auth,
    catalog,
    database,
    main,
    orchestrator,
    payout_registry,
    route_gate,
    socket_policy,
    state_backup,
    step_up,
    worker_api,
)
from tests.i18n_source import english_source  # noqa: E402

PASSPHRASE = "correct horse battery staple"
#: The real proxy, before the ui fixture swaps it out.
REAL_PROXY = main._proxy_to_worker
REAL_RESOLVE = main._resolve_worker_id
#: The real deploy_raw with its guard, before the docker fixture swaps it out.
REAL_DEPLOY_RAW = orchestrator.deploy_raw
#: The real restore, before the worker fixture swaps it out.
REAL_RESTORE_STATE = orchestrator.restore_state
#: The real fingerprint readers, before the ui fixture swaps them out.
REAL_STATE_IDS = payout_registry.state_ids
REAL_ALL_STATE_IDS = payout_registry.all_state_ids


def _sha(bundle: bytes) -> str:
    """The SHA-256 of a sealed backup file, as the dashboard and the worker name it.

    Through file_digest, not hashlib.sha256(bundle): CodeQL reads every sealed
    file as a password, because its header says mode "passphrase"
    (state_backup.MODE_PASSPHRASE), and flags its SHA-256 as weak password
    hashing. A sealed file is not a password, and the digest is the same one.
    """
    return hashlib.file_digest(io.BytesIO(bundle), "sha256").hexdigest()


def test_the_file_digest_is_the_sha256_the_app_uses():
    assert _sha(b"a sealed file") == hashlib.sha256(b"a sealed file").hexdigest()


WORKER_KEY = "per-worker-key-restore"
CLIENT_ID = "worker-client-1"
KEY_FILE = b'{"address":"0xabc","crypto":{"cipher":"aes-128-ctr"}}'


# ---------------------------------------------------------------------------
# Docker-shaped archives and bundles
# ---------------------------------------------------------------------------


def docker_archive(
    folder: str, entries: list[tuple[str, str, int, int, int, bytes | str]], root: tuple[int, int, int] = (0o755, 0, 0)
) -> bytes:
    """A tar shaped like Docker's GET archive of ``/.../folder``.

    ``entries``: (path below the folder, type 'dir'/'file'/'symlink'/'hardlink', mode, uid, gid, data or link
    target; a hard link's target is a path below the folder). ``root``: the folder's own (mode, uid, gid).
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        top = tarfile.TarInfo(folder)
        top.type, top.mtime = tarfile.DIRTYPE, 1_700_000_000
        top.mode, top.uid, top.gid = root
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
            elif kind == "hardlink":
                # Docker names a hard link's target by its full path in the archive.
                info.type, info.linkname = tarfile.LNKTYPE, f"{folder}/{data}"
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


#: A keystore file as Mysterium names it: UTC--<ISO time with nanoseconds>--<40 hex address>.
KEYSTORE_NAME = "UTC--2024-05-17T09-31-27.123456789Z--" + "3f" * 20
LONG_NAME_TREE = [
    ("keystore", "dir", 0o700, 1000, 1000, b""),
    (f"keystore/{KEYSTORE_NAME}", "file", 0o600, 1000, 1000, KEY_FILE),
    ("keystore/clé-ñ", "file", 0o600, 1000, 1000, b"accented"),
    ("keystore/linked", "hardlink", 0o600, 1000, 1000, f"keystore/{KEYSTORE_NAME}"),
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

    def test_the_relative_archive_writes_under_the_folder_it_is_given(self):
        archive = state_backup.split_archives(docker_archive("mysterium-node", MYSTERIUM_TREE))["mysterium-node"]
        with tarfile.open(fileobj=io.BytesIO(state_backup.relative_archive(archive, "volume"))) as tar:
            names = tar.getnames()
        # The folder's own entry stays, renamed: it carries the root's owner and mode.
        assert names == [
            "volume",
            "volume/keystore",
            "volume/keystore/UTC--2024-01-01--abc",
            "volume/keystore/current",
            "volume/myst.db",
        ]

    def test_a_root_that_is_not_a_folder_is_never_written_over_the_mount(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            top = tarfile.TarInfo("mysterium-node")
            top.type, top.linkname = tarfile.SYMTYPE, "elsewhere"
            tar.addfile(top)
        with tarfile.open(fileobj=io.BytesIO(state_backup.relative_archive(buf.getvalue(), "volume"))) as tar:
            assert tar.getnames() == []
        want = state_backup.tree_manifest(buf.getvalue())
        found = state_backup.tree_manifest(docker_archive("mysterium-node", []))
        assert state_backup.manifest_differences(want, found) == ["the folder itself: a dir, not a symlink"]

    def test_long_and_non_ascii_names_are_renamed_in_full(self):
        """split_archives writes these names as PAX records, which tarfile writes back in preference to the name."""
        archive = state_backup.split_archives(docker_archive("mysterium-node", LONG_NAME_TREE))["mysterium-node"]
        with tarfile.open(fileobj=io.BytesIO(state_backup.relative_archive(archive, "volume"))) as tar:
            members = {m.name: m for m in tar}
        assert sorted(members) == [
            "volume",
            "volume/keystore",
            f"volume/keystore/{KEYSTORE_NAME}",
            "volume/keystore/clé-ñ",
            "volume/keystore/linked",
        ]
        assert members["volume/keystore/linked"].linkname == f"volume/keystore/{KEYSTORE_NAME}"

    def test_a_real_mysterium_keystore_name_restores(self, docker):
        """'mysterium-node/keystore/UTC--<time>--<address>' is 101 bytes: one past a plain tar name."""
        assert len(f"mysterium-node/keystore/{KEYSTORE_NAME}".encode()) > 100
        result = orchestrator.restore_state("mysterium", _archives(LONG_NAME_TREE), MYSTERIUM_DEPLOY)
        assert result["started"] is True
        assert set(docker.volume_map["mysterium-data"].files) == {
            "keystore",
            f"keystore/{KEYSTORE_NAME}",
            "keystore/clé-ñ",
            "keystore/linked",
        }

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

    def test_the_folders_own_owner_and_mode_is_compared(self):
        """A service that cannot write its own folder fails after a restore that said it worked."""
        want = state_backup.tree_manifest(docker_archive("mysterium-node", MYSTERIUM_TREE, (0o700, 1000, 1000)))
        got = state_backup.tree_manifest(docker_archive("mysterium-node", MYSTERIUM_TREE, (0o755, 0, 0)))
        assert want[state_backup.ROOT] == ("dir", 0o700, 1000, 1000, "")
        assert state_backup.manifest_differences(want, got) == ["the folder itself: owner or permissions differ"]

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
        # Docker gives each volume the time it made it: a volume made again under the name reads another.
        docker.made += 1
        self.attrs = {
            "Name": name,
            "Labels": dict(labels),
            "CreatedAt": f"2026-11-14T10:{docker.made // 60:02d}:{docker.made % 60:02d}Z",
        }
        self.files: dict[str, tuple[tarfile.TarInfo, bytes | None]] = {}
        # The root's (mode, uid, gid): Docker gives a new volume the image folder's.
        self.root = (0o755, 0, 0)

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
        into = posixpath.normpath(path)
        mounts = {posixpath.normpath(t): t for t in self.mounts}
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            for member in tar:
                body = tar.extractfile(member).read() if member.isfile() else None
                full = posixpath.normpath(f"{into}/{member.name}")
                if full == into:
                    # Docker skips an entry for the folder written into ("." or "./"): that
                    # folder keeps the owner and mode it had, even when a volume is mounted there.
                    continue
                # The mount the entry lands in, the deepest one.
                target = max((t for t in mounts if full == t or full.startswith(t + "/")), key=len)
                volume = self._volume(mounts[target])
                below = full[len(target) + 1 :]
                if member.islnk():
                    # Docker resolves a hard link's target from the folder written into.
                    member.linkname = posixpath.normpath(f"{into}/{member.linkname}")[len(target) + 1 :]
                if not below:
                    # Docker applies a folder entry's owner and mode to the folder that exists.
                    volume.root = (member.mode & 0o777, member.uid, member.gid)
                else:
                    volume.files[below] = (member, body)
        return True

    def get_archive(self, path):
        volume = self._volume(path)
        buf = io.BytesIO()
        folder = path.rstrip("/").rsplit("/", 1)[-1]
        with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
            top = tarfile.TarInfo(folder)
            top.type = tarfile.DIRTYPE
            top.mode, top.uid, top.gid = volume.root
            tar.addfile(top)
            for name, (member, body) in sorted(volume.files.items()):
                copy = tarfile.TarInfo(f"{folder}/{name}")
                copy.type, copy.mode, copy.uid, copy.gid = member.type, member.mode, member.uid, member.gid
                copy.size = member.size
                # Docker names a hard link's target by its path in the archive, under the folder.
                copy.linkname = f"{folder}/{member.linkname}" if member.islnk() else member.linkname
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
        labels = (filters or {}).get("label", "")
        wanted = [label.partition("=") for label in ([labels] if isinstance(labels, str) else labels)]
        return [c for c in self.docker.container_map.values() if not [k for k, _, v in wanted if c.labels.get(k) != v]]

    def create(self, **kwargs):
        self.docker.creates.append(kwargs)
        mounts = {m["Target"]: m["Source"] for m in kwargs.get("mounts") or []}
        for target, source in mounts.items():
            if source not in self.docker.volume_map:
                raise AssertionError(f"helper mounts a volume that does not exist: {source} at {target}")
        container = FakeContainer(self.docker, kwargs["name"], mounts, kwargs.get("labels"), kwargs.get("image"))
        # As Docker's inspect shows them: what a leftover helper is found to hold.
        container.attrs["Mounts"] = [
            {"Type": "volume", "Name": source, "Destination": target} for target, source in mounts.items()
        ]
        self.docker.container_map[container.name] = container
        return container


class FakeDocker:
    def __init__(self):
        self.volume_map: dict[str, FakeVolume] = {}
        self.made = 0
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
            self,
            name,
            mounts,
            {orchestrator.LABEL_MANAGED: "true", orchestrator.LABEL_SERVICE: slug},
            "sha256:catalog-image",
        )
        self.container_map[name].attrs["Mounts"] = [
            {"Type": "volume", "Name": source, "Destination": target} for target, source in mounts.items()
        ]
        return self.container_map[name].id


#: Where a helper mounts the volume it writes: one level below the folder the proxy lets it write into.
WRITE_MOUNT = f"{orchestrator.RESTORE_WRITE_DIR}/{orchestrator.RESTORE_ROOT}"

MYSTERIUM_DEPLOY = {
    "image": catalog.get_service("mysterium")["docker"]["image"],
    "volumes": {"mysterium-data": {"bind": "/var/lib/mysterium-node", "mode": "rw"}},
}


@pytest.fixture(autouse=True)
def _restore_marks_on_tmp(tmp_path, monkeypatch):
    """Each test gets its own unfinished-restore record on disk, as a box has one in /data."""
    monkeypatch.setattr(orchestrator, "RESTORE_MARKER", str(tmp_path / "restore-unfinished"), raising=False)
    monkeypatch.setattr(orchestrator, "_RESTORE_MARK_UNWRITTEN", {}, raising=False)


def _marker_io(monkeypatch, path: str, error: OSError, mode: str | None = None) -> None:
    """open() of ``path`` raises ``error`` in the orchestrator (only for ``mode`` when given), as a disk that refuses it."""
    import builtins

    real_open = builtins.open

    def fake_open(file, *args, **kwargs):
        wanted = args[0] if args else kwargs.get("mode", "r")
        if str(file) == path and (mode is None or wanted == mode):
            raise error
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(orchestrator, "open", fake_open, raising=False)


def _assert_kept_and_held(docker: FakeDocker, *volumes: str, slug: str = "mysterium") -> None:
    """What a failed restore's undo leaves: no volume deleted, the ones it made kept, its record holding the slug.

    Docker deletes a volume by name only, so the undo cannot prove at the
    delete that a volume is still the one it made, and never deletes one.
    """
    assert not [r for r in docker.removed if r[0] == "volume"]
    assert set(volumes) <= set(docker.volume_map)
    assert slug in orchestrator.restore_marks()
    assert set(volumes) <= set(orchestrator._restore_mark_volumes(slug))


def _record_names() -> str:
    """The record on disk without the nonces, which are random: ``slug name name``."""
    return re.sub(r":[0-9a-f]+", "", Path(orchestrator.RESTORE_MARKER).read_text(encoding="utf-8"))


def _recorded(docker: FakeDocker | None, slug: str = "mysterium", volume: str = "mysterium-data") -> None:
    """A restore's record naming ``volume`` with its nonce, and (with ``docker``) the volume it made with that nonce."""
    nonce = "ab" * 16
    Path(orchestrator.RESTORE_MARKER).write_text(f"{slug} {volume}:{nonce}\n", encoding="utf-8")
    if docker is not None:
        docker.volumes.create(volume, labels={orchestrator.LABEL_RESTORE: nonce})


def _owner_removes(slug: str, **kwargs: Any) -> dict[str, Any]:
    """Remove ``slug`` with its data as the dashboard's owner does.

    The box first names the critical volumes it finds (a CriticalVolumeError
    with their critical_set), the owner reviews exactly those, and the delete
    goes with that set: never the override alone.
    """
    try:
        return orchestrator.remove_service(slug, delete_volumes=True, **kwargs)
    except orchestrator.CriticalVolumeError as refusal:
        reviewed = refusal.critical_set
    return orchestrator.remove_service(
        slug, delete_volumes=True, allow_delete_critical=True, approved_critical=reviewed, **kwargs
    )


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


def _archives(tree=None, root=(0o755, 0, 0)):
    return state_backup.split_archives(docker_archive("mysterium-node", tree or MYSTERIUM_TREE, root))


class TestTheRestoreSequence:
    def test_it_creates_writes_reads_back_and_then_starts(self, docker):
        result = orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert result["started"] is True and result["files"] == 2
        assert result["targets"] == ["/var/lib/mysterium-node"]
        # The new volume's fingerprint, which links a later export of it to this backup's node.
        assert isinstance(result["state_id"], str) and result["state_id"]
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
        assert {m["Target"]: m["Source"] for m in helper["mounts"]} == {WRITE_MOUNT: "mysterium-data"}
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

    def test_the_folders_own_owner_and_mode_come_back_as_the_backup_had_them(self, docker):
        result = orchestrator.restore_state("mysterium", _archives(root=(0o700, 1000, 1000)), MYSTERIUM_DEPLOY)
        assert result["started"] is True
        assert docker.volume_map["mysterium-data"].root == (0o700, 1000, 1000)

    def test_a_folder_that_does_not_read_back_with_its_owner_and_mode_undoes_the_restore(self, docker):
        """As Docker does with a "." entry for the folder written into: the root keeps the image's owner and mode."""
        real_put = FakeContainer.put_archive

        def root_skipped(self, path, data):
            out = io.BytesIO()
            with tarfile.open(fileobj=io.BytesIO(data)) as src, tarfile.open(fileobj=out, mode="w") as dst:
                for member in src:
                    if member.name != orchestrator.RESTORE_ROOT:
                        dst.addfile(member, src.extractfile(member) if member.isfile() else None)
            return real_put(self, path, out.getvalue())

        with (
            patch.object(FakeContainer, "put_archive", root_skipped),
            pytest.raises(orchestrator.RestoreError, match="the folder itself: owner or permissions differ"),
        ):
            orchestrator.restore_state("mysterium", _archives(root=(0o700, 1000, 1000)), MYSTERIUM_DEPLOY)
        assert docker.started == [] and "cashpilot-mysterium" not in docker.container_map
        _assert_kept_and_held(docker, "mysterium-data")

    EXTRA_DEPLOY = {
        **MYSTERIUM_DEPLOY,
        "volumes": {**MYSTERIUM_DEPLOY["volumes"], "mysterium-extra": {"bind": "/etc/extra", "mode": "rw"}},
    }

    def test_another_volume_another_client_made_after_the_check_is_never_removed(self, docker):
        """Absent at the check is not made by this restore: one created first by someone else stays."""
        real_exists = orchestrator._volume_exists

        def raced(client, volume):
            found = real_exists(client, volume)
            if volume == "mysterium-extra":
                docker.volumes.create("mysterium-extra", labels={"theirs": "1"})
            return found

        docker.corrupt_put = True
        with (
            patch.object(orchestrator, "_volume_exists", side_effect=raced),
            pytest.raises(orchestrator.RestoreError, match="does not read back"),
        ):
            orchestrator.restore_state("mysterium", _archives(), self.EXTRA_DEPLOY)
        assert docker.volume_map["mysterium-extra"].attrs["Labels"] == {"theirs": "1"}
        assert ("volume", "mysterium-extra") not in docker.removed
        # Not this restore's, so not named as what it left or holds.
        assert "mysterium-extra" not in orchestrator._restore_mark_volumes("mysterium")
        _assert_kept_and_held(docker, "mysterium-data")

    def test_control_another_volume_this_restore_made_is_kept_and_held_on_failure(self, docker):
        docker.corrupt_put = True
        with pytest.raises(orchestrator.RestoreError, match="does not read back") as caught:
            orchestrator.restore_state("mysterium", _archives(), self.EXTRA_DEPLOY)
        _assert_kept_and_held(docker, "mysterium-data", "mysterium-extra")
        assert "mysterium-extra" in orchestrator._restore_mark_volumes("mysterium")
        # Only the written one may hold the backup: the dashboard holds the identity for it alone.
        assert caught.value.left == ["mysterium-data"]

    def test_control_another_volume_that_was_there_is_kept(self, docker):
        docker.volumes.create("mysterium-extra", labels={"theirs": "1"})
        docker.corrupt_put = True
        with pytest.raises(orchestrator.RestoreError, match="does not read back"):
            orchestrator.restore_state("mysterium", _archives(), self.EXTRA_DEPLOY)
        assert set(docker.volume_map) == {"mysterium-data", "mysterium-extra"}
        assert "mysterium-extra" not in orchestrator._restore_mark_volumes("mysterium")

    def test_a_read_back_that_differs_undoes_everything_but_the_volume(self, docker):
        docker.corrupt_put = True
        with pytest.raises(
            orchestrator.RestoreError, match="does not read back as the backup.*removed.*mysterium-data.*stays held"
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert docker.started == [] and "cashpilot-mysterium" not in docker.container_map
        _assert_kept_and_held(docker, "mysterium-data")

    def test_a_docker_failure_mid_write_undoes_everything_but_the_volume(self, docker):
        with (
            patch.object(FakeContainer, "put_archive", side_effect=RuntimeError("boom")),
            pytest.raises(orchestrator.RestoreError, match="undone"),
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert "cashpilot-mysterium" not in docker.container_map and docker.started == []
        _assert_kept_and_held(docker, "mysterium-data")

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

    def test_a_failed_restore_that_made_nothing_leaves_no_hold(self, gated):
        with (
            patch.object(orchestrator, "_create_restore_volume", side_effect=orchestrator.RestoreError("refused")),
            pytest.raises(orchestrator.RestoreError),
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert gated.container_map == {} and gated.volume_map == {}
        assert self.NAME not in orchestrator.deploy_failed() and "mysterium" not in orchestrator.restore_marks()

    def test_a_written_volume_the_undo_keeps_stays_held(self, gated):
        """The name is free, but the unchecked volume stayed: the failed mark must not be lifted."""
        gated.corrupt_put = True
        with pytest.raises(orchestrator.RestoreError, match="stays held"):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert self.NAME not in gated.container_map and "mysterium-data" in gated.volume_map
        assert self.NAME in orchestrator._failed_on_disk()

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
        digest = _sha(bundle)
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
    post.client = client
    return post


def _delete_approval(slug="mysterium", client_id=CLIENT_ID, key=WORKER_KEY):
    """The header the UI sends with a delete of critical data once the owner gave the password."""
    target = step_up.delete_target(slug, client_id)
    return {step_up.APPROVAL_HEADER: step_up.sign(key, step_up.ACTION_DELETE_CRITICAL, target)}


def _detail(resp):
    detail = resp.json().get("detail")
    return detail.get("message") if isinstance(detail, dict) else detail


class TestTheWorker:
    def test_a_good_restore_reaches_the_restore_with_the_catalogs_folders(self, worker):
        bundle = proxybase_bundle()
        resp = worker("proxybase-xyz", bundle)
        assert resp.status_code == 200, resp.text
        assert resp.json()["bundle_sha256"] == _sha(bundle)
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
        target = step_up.restore_target("proxybase-xyz", "another-box", _sha(bundle))
        resp = worker("proxybase-xyz", bundle, approval=step_up.sign(WORKER_KEY, step_up.ACTION_RESTORE, target))
        assert resp.status_code == 403 and worker.calls == []

    def test_a_deploy_approval_cannot_restore(self, worker):
        bundle = proxybase_bundle()
        target = step_up.restore_target("proxybase-xyz", CLIENT_ID, _sha(bundle))
        resp = worker("proxybase-xyz", bundle, approval=step_up.sign(WORKER_KEY, step_up.ACTION_CUSTOM_IMAGE, target))
        assert resp.status_code == 403 and worker.calls == []

    def test_the_api_key_alone_cannot_restore(self, worker):
        """A stolen fleet key has no worker key to sign with."""
        bundle = proxybase_bundle()
        target = step_up.restore_target("proxybase-xyz", CLIENT_ID, _sha(bundle))
        resp = worker("proxybase-xyz", bundle, approval=step_up.sign("wk-test", step_up.ACTION_RESTORE, target))
        assert resp.status_code == 403 and worker.calls == []

    def test_an_approval_is_good_once(self, worker):
        bundle = proxybase_bundle()
        target = step_up.restore_target("proxybase-xyz", CLIENT_ID, _sha(bundle))
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
        answer = {"container_id": "cid", "files": 2, "targets": ["/var/lib/mysterium-node"], "started": True}
        if path.endswith("/restore") and state.get("landed"):
            answer["state_id"] = state["landed"]  # the fingerprint of the volume the restore made
        return answer

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
    state: dict[str, Any] = {"runs_on": {}, "user": None, "states": {}}

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
            patch.object(main.payout_registry, "state_ids", side_effect=lambda ws: state["states"]),
            patch.object(
                main.payout_registry,
                "all_state_ids",
                side_effect=lambda ws: {k: [v] for k, v in state["states"].items()},
            ),
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
            client.workers = workers  # type: ignore[attr-defined]
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
        digest = _sha(bundle)
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
        asyncio.run(database.record_backup("mysterium", 2, _sha(bundle), "export"))
        upload = _upload(ui, bundle).json()
        assert upload["known"] is True and upload["history"][0]["worker"] == "box-b"
        resp = _restore(ui, upload["upload_id"], step_up_password=OWNER_PASSWORD)
        assert resp.status_code == 200, resp.text

    def test_an_identity_live_on_another_box_is_refused_naming_it(self, ui):
        bundle = mysterium_bundle()
        asyncio.run(database.record_backup("mysterium", 2, _sha(bundle), "export"))
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

    def test_a_service_routed_on_that_box_is_refused_before_the_worker(self, ui):
        """A restored container runs from the box's own IP, which a route there forbids.

        Its deployment record refuses it here; the worker's route check (TestARestoreAndTheRoute) is the backstop.
        """
        upload = _upload(ui, mysterium_bundle()).json()
        routed = {"image": "x", "env": {}, "route": {"proxy_id": 3}}
        with patch.object(
            main.database,
            "get_deployment_spec",
            AsyncMock(side_effect=lambda slug, worker_id=None: routed if worker_id == 1 else None),
        ):
            resp = _restore(
                ui, upload["upload_id"], worker_id=1, confirm_name="Mysterium", step_up_password=OWNER_PASSWORD
            )
        assert resp.status_code == 409 and "already runs" in _detail(resp)
        assert not [s for s in ui.sent if s["path"].endswith("/restore")]

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
        main._restore_inflight.add(_sha(bundle))
        try:
            resp = _restore(ui, upload["upload_id"], confirm_name="Mysterium", step_up_password=OWNER_PASSWORD)
        finally:
            main._restore_inflight.clear()
        assert resp.status_code == 409 and "already being restored" in _detail(resp) and ui.sent == []

    def test_another_file_waits_too_while_one_is_being_restored(self, ui):
        """Two exports of one node are two files: one restore at a time, whatever the file."""
        upload = _upload(ui, mysterium_bundle()).json()
        main._restore_inflight.add("f" * 64)
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

        bundle = mysterium_bundle()
        upload = _upload(ui, bundle).json()
        with patch.object(main, "_proxy_to_worker", AsyncMock(side_effect=main._WorkerNoAnswer(504, "no answer"))):
            resp = _restore(ui, upload["upload_id"], confirm_name="Mysterium", step_up_password=OWNER_PASSWORD)
        assert resp.status_code == 504
        rows = asyncio.run(database.backup_records(_sha(bundle)))
        assert [(r["worker_id"], r["source"]) for r in rows] == [(1, "pending")]

    def test_a_refused_restore_is_not_recorded(self, ui):
        from fastapi import HTTPException

        bundle = mysterium_bundle()
        upload = _upload(ui, bundle).json()
        with patch.object(main, "_proxy_to_worker", AsyncMock(side_effect=HTTPException(409, "volume exists"))):
            _restore(ui, upload["upload_id"], confirm_name="Mysterium", step_up_password=OWNER_PASSWORD)
        assert asyncio.run(database.backup_records(_sha(bundle))) == []


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
        rows = asyncio.run(database.backup_records(_sha(bundle)))
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


# ---------------------------------------------------------------------------
# One node, many files: the review's findings on the identity check
# ---------------------------------------------------------------------------


def _export(bundle: bytes, worker_id: int, state_id: str = "sid-1") -> None:
    origin = database.backup_origin(worker_id, state_id)
    asyncio.run(database.record_backup("mysterium", worker_id, _sha(bundle), "export", origin, origin))


class TestOneNodeManyFiles:
    def test_a_second_export_of_a_node_restored_elsewhere_is_refused(self, ui):
        """Each export has its own nonce, so its own hash: the files are linked by the volume they came from."""
        first, second = mysterium_bundle(), mysterium_bundle()
        assert _sha(first) != _sha(second)
        _export(first, 2)
        _export(second, 2)
        # box-b's node was removed; the first file goes onto box-a.
        upload = _upload(ui, first).json()
        assert _restore(ui, upload["upload_id"], worker_id=1, step_up_password=OWNER_PASSWORD).status_code == 200
        ui.state["runs_on"] = {"mysterium": [{"worker_id": 1}]}
        preview = _upload(ui, second).json()
        assert preview["known"] is True and preview["live_on"] == ["box-a"]
        assert [(w["name"], w["ok"]) for w in preview["workers"]] == [("box-a", False), ("box-b", False)]
        resp = _restore(ui, preview["upload_id"], worker_id=2, step_up_password=OWNER_PASSWORD, allow_plain_http=True)
        assert resp.status_code == 409 and "box-a" in _detail(resp)
        assert len(ui.sent) == 1

    def test_the_export_route_records_where_the_file_came_from(self, ui):
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
        (row,) = asyncio.run(database.backup_records(_sha(bundle)))
        assert row["origin"] == "state:1:fp"

    def test_a_box_wiped_and_redeployed_since_the_export_does_not_hold_the_old_identity(self, ui):
        """box-a runs a new volume now (another state fingerprint): its new node is not this file's."""
        bundle = mysterium_bundle()
        _export(bundle, 1, "old-volume")
        ui.state["runs_on"] = {"mysterium": [{"worker_id": 1}]}
        ui.state["states"] = {(1, "mysterium"): "new-volume"}
        _heartbeat(ui, 1)
        upload = _upload(ui, bundle).json()
        assert upload["live_on"] == []
        resp = _restore(ui, upload["upload_id"], worker_id=2, step_up_password=OWNER_PASSWORD, allow_plain_http=True)
        assert resp.status_code == 200, resp.text

    def test_the_box_it_was_exported_from_still_holds_it_on_the_same_volume(self, ui):
        bundle = mysterium_bundle()
        _export(bundle, 1, "same-volume")
        ui.state["runs_on"] = {"mysterium": [{"worker_id": 1}]}
        ui.state["states"] = {(1, "mysterium"): "same-volume"}
        upload = _upload(ui, bundle).json()
        assert upload["live_on"] == ["box-a"]
        resp = _restore(ui, upload["upload_id"], worker_id=2, step_up_password=OWNER_PASSWORD, allow_plain_http=True)
        assert resp.status_code == 409 and "box-a" in _detail(resp) and ui.sent == []


def _heartbeat(ui, worker_id: int, at: str | None = None) -> None:
    """A heartbeat from ``worker_id`` at ``at`` (SQLite UTC text), by default just now: after every ledger row."""
    at = at or (datetime.now(UTC) + timedelta(seconds=2)).strftime("%Y-%m-%d %H:%M:%S")
    next(w for w in ui.workers if w["id"] == worker_id)["last_heartbeat"] = at


def _export_route(ui, bundle: bytes, worker_id: int, state_id: str) -> None:
    """An export through the dashboard's own route, which decides the file's origin."""
    answer = {"bundle_b64": base64.b64encode(bundle).decode(), "state_id": state_id, "targets": [], "bytes": 1}
    box = {"worker_id": worker_id, "name": f"box-{worker_id}", "workers": []}
    with (
        patch.object(main, "_backup_box", AsyncMock(return_value=box)),
        patch.object(main, "_worker_features", AsyncMock(return_value={"state_backup"})),
        patch.object(main, "_proxy_to_worker", AsyncMock(return_value=answer)),
    ):
        resp = ui.post(
            "/api/payout-registry/mysterium/backup-export",
            json={"worker_id": worker_id, "passphrase": PASSPHRASE, "passphrase_repeat": PASSPHRASE},
        )
    assert resp.status_code == 200, resp.text


def _runs(ui, worker_id: int | None, state_id: str | None = None) -> None:
    """The fleet as the next heartbeat shows it: Mysterium on one box with this volume, or nowhere."""
    if worker_id is None:
        # Removed from the dashboard: the deploy records go with it.
        asyncio.run(database.remove_deployment("mysterium"))
    ui.state["runs_on"] = {"mysterium": [{"worker_id": worker_id}]} if worker_id else {}
    ui.state["states"] = {(worker_id, "mysterium"): state_id} if worker_id and state_id else {}
    if worker_id:
        _heartbeat(ui, worker_id)


def _restore_ok(ui, bundle: bytes, worker_id: int, landed: str, **extra) -> None:
    ui.state["landed"] = landed
    upload = _upload(ui, bundle).json()
    plain = {"allow_plain_http": True} if worker_id == 2 else {}
    resp = _restore(ui, upload["upload_id"], worker_id=worker_id, step_up_password=OWNER_PASSWORD, **plain, **extra)
    assert resp.status_code == 200, resp.text
    _runs(ui, worker_id, landed)


class TestOneNodeMovedTwice:
    """An export taken after a restore is a file of the restored node, not of a new one."""

    def test_the_first_file_of_a_node_moved_twice_is_refused_where_it_does_not_run(self, ui):
        f1, f2 = mysterium_bundle(), mysterium_bundle()
        _runs(ui, 2, "S1")
        _export_route(ui, f1, 2, "S1")  # 1. F1 from box-b
        _runs(ui, None)
        _restore_ok(ui, f1, 1, "SA")  # 2. removed on box-b, F1 restored on box-a
        _export_route(ui, f2, 1, "SA")  # 3. F2 from box-a
        _runs(ui, None)
        _restore_ok(ui, f2, 2, "SB")  # 4. removed on box-a, F2 restored on box-b
        preview = _upload(ui, f1).json()  # 5. F1 again
        assert preview["live_on"] == ["box-b"]
        resp = _restore(ui, preview["upload_id"], worker_id=1, step_up_password=OWNER_PASSWORD)
        assert resp.status_code == 409 and "box-b" in _detail(resp)
        assert len(ui.sent) == 2

    def test_a_file_this_cashpilot_did_not_make_gets_a_lineage_where_it_lands(self, ui):
        f0, f2 = mysterium_bundle(), mysterium_bundle()
        _restore_ok(ui, f0, 1, "SA", confirm_name="Mysterium")
        _export_route(ui, f2, 1, "SA")
        _runs(ui, None)
        _restore_ok(ui, f2, 2, "SB")
        preview = _upload(ui, f0).json()
        assert preview["known"] is True and preview["live_on"] == ["box-b"]

    def test_a_restore_the_worker_gave_no_volume_for_still_links_the_next_export(self, ui):
        f1, f2 = mysterium_bundle(), mysterium_bundle()
        _export(f1, 2, "S1")
        _restore_ok(ui, f1, 1, "")  # an answer with no state_id
        _export_route(ui, f2, 1, "SA")
        _runs(ui, None)
        _restore_ok(ui, f2, 2, "SB")
        assert _upload(ui, f1).json()["live_on"] == ["box-b"]


class TestALineageThroughAnUnknown:
    """An export still joins the node it came from when the restore or the export named no volume."""

    def test_an_export_after_a_restore_that_got_no_answer_keeps_the_node(self, ui):
        f1, f2 = mysterium_bundle(), mysterium_bundle()
        _runs(ui, 2, "S1")
        _export_route(ui, f1, 2, "S1")
        _runs(ui, None)
        upload = _upload(ui, f1).json()
        with patch.object(main, "_proxy_to_worker", AsyncMock(side_effect=main._WorkerNoAnswer(504, "no answer"))):
            assert _restore(ui, upload["upload_id"], worker_id=1, step_up_password=OWNER_PASSWORD).status_code == 504
        _runs(ui, 1, "SA")  # the worker finished it after all
        _export_route(ui, f2, 1, "SA")
        (row,) = asyncio.run(database.backup_records(_sha(f2)))
        assert row["origin"] == "state:2:S1"
        _runs(ui, None)
        # The restore box-a never answered still holds the node, for every file of it.
        preview = _upload(ui, f2).json()
        assert preview["live_on"] == ["box-a"]
        resp = _restore(ui, preview["upload_id"], worker_id=2, step_up_password=OWNER_PASSWORD, allow_plain_http=True)
        assert resp.status_code == 409 and "box-a" in _detail(resp)

    def test_an_export_with_no_volume_after_a_restore_keeps_the_node(self, ui):
        f1, f2 = mysterium_bundle(), mysterium_bundle()
        _export(f1, 2, "S1")
        _restore_ok(ui, f1, 1, "SA")
        _runs(ui, 1)  # box-a runs it, and reports no volume
        _export_route(ui, f2, 1, "")
        (row,) = asyncio.run(database.backup_records(_sha(f2)))
        assert row["origin"] == "state:2:S1"
        _runs(ui, None)
        _restore_ok(ui, f2, 2, "SB")
        preview = _upload(ui, f1).json()
        assert preview["live_on"] == ["box-b"]
        resp = _restore(ui, preview["upload_id"], worker_id=1, step_up_password=OWNER_PASSWORD)
        assert resp.status_code == 409 and "box-b" in _detail(resp)


class TestALineageWhenNothingNamesTheVolume:
    """When the volume of an export or a restore is not known, its file still joins the node the box runs."""

    def test_an_export_with_no_volume_joins_the_node_the_box_ran_last(self, ui):
        f1, fn0, fn1 = mysterium_bundle(), mysterium_bundle(), mysterium_bundle()
        _runs(ui, 2, "S1")
        _export_route(ui, f1, 2, "S1")  # node L1 on box-b
        _runs(ui, None)
        _restore_ok(ui, f1, 1, "SA1")  # L1 moved to box-a
        _runs(ui, None)  # removed with its data
        _runs(ui, 1, "X")  # a fresh node N on box-a
        _export_route(ui, fn0, 1, "X")
        _runs(ui, 1)  # no fingerprint from the worker or the heartbeat
        _export_route(ui, fn1, 1, "")
        (row,) = asyncio.run(database.backup_records(_sha(fn1)))
        assert row["origin"] == "state:1:X"
        _runs(ui, None)
        _restore_ok(ui, fn1, 2, "SB")  # N moved to box-b
        preview = _upload(ui, fn0).json()
        assert preview["live_on"] == ["box-b"]
        resp = _restore(ui, preview["upload_id"], worker_id=1, step_up_password=OWNER_PASSWORD)
        assert resp.status_code == 409 and "box-b" in _detail(resp)
        # The dead node L1 is not held by box-b, which runs N.
        assert _upload(ui, f1).json()["live_on"] == []

    def test_a_first_export_with_no_volume_links_the_next_one(self, ui):
        fa, fb = mysterium_bundle(), mysterium_bundle()
        _runs(ui, 2)  # box-b runs its own node and reports no volume
        _export_route(ui, fa, 2, "")
        _runs(ui, 2, "S1")
        _export_route(ui, fb, 2, "S1")
        _runs(ui, None)
        _restore_ok(ui, fb, 1, "SA")
        preview = _upload(ui, fa).json()
        assert preview["live_on"] == ["box-a"]
        resp = _restore(ui, preview["upload_id"], worker_id=2, step_up_password=OWNER_PASSWORD, allow_plain_http=True)
        assert resp.status_code == 409 and "box-a" in _detail(resp)

    def test_an_unknown_file_restored_with_no_volume_links_the_next_export(self, ui):
        f0, f2 = mysterium_bundle(), mysterium_bundle()
        _restore_ok(ui, f0, 1, "", confirm_name="Mysterium")  # the worker named no volume
        _export_route(ui, f2, 1, "SA")
        _runs(ui, None)
        _restore_ok(ui, f2, 2, "SB")
        preview = _upload(ui, f0).json()
        assert preview["live_on"] == ["box-b"]
        resp = _restore(ui, preview["upload_id"], worker_id=1, step_up_password=OWNER_PASSWORD)
        assert resp.status_code == 409 and "box-b" in _detail(resp)


class TestARestoredBoxRedeployedSince:
    """A restore row holds the identity only while its box still runs the volume the restore made."""

    def test_a_fresh_node_on_that_box_does_not_hold_the_old_identity(self, ui):
        bundle = mysterium_bundle()
        _export(bundle, 2, "S1")
        _restore_ok(ui, bundle, 1, "SA")
        _runs(ui, 1, "a-fresh-volume")
        preview = _upload(ui, bundle).json()
        assert preview["live_on"] == []

    def test_the_same_volume_still_holds_it_and_the_refusal_names_the_way_out(self, ui):
        bundle = mysterium_bundle()
        _export(bundle, 2, "S1")
        _restore_ok(ui, bundle, 1, "SA")
        upload = _upload(ui, bundle).json()
        assert upload["live_on"] == ["box-a"]
        resp = _restore(ui, upload["upload_id"], worker_id=2, step_up_password=OWNER_PASSWORD, allow_plain_http=True)
        assert resp.status_code == 409 and "box-a" in _detail(resp) and "Device ids" in _detail(resp)

    def test_a_heartbeat_from_before_the_restore_does_not_free_the_identity(self, ui):
        """box-a's last heartbeat still shows the node it ran before: it says nothing about the restored one."""
        bundle = mysterium_bundle()
        _export(bundle, 2, "S1")
        ui.state["states"] = {(1, "mysterium"): "OLD"}
        _heartbeat(ui, 1, "2000-01-01 00:00:00")
        ui.state["landed"] = "SA"
        upload = _upload(ui, bundle).json()
        assert _restore(ui, upload["upload_id"], worker_id=1, step_up_password=OWNER_PASSWORD).status_code == 200
        preview = _upload(ui, bundle).json()
        assert preview["live_on"] == ["box-a"]
        resp = _restore(ui, preview["upload_id"], worker_id=2, step_up_password=OWNER_PASSWORD, allow_plain_http=True)
        assert resp.status_code == 409 and "box-a" in _detail(resp)
        assert len(ui.sent) == 1

    def test_a_newer_heartbeat_with_another_volume_frees_it(self, ui):
        bundle = mysterium_bundle()
        _export(bundle, 2, "S1")
        _restore_ok(ui, bundle, 1, "SA")
        ui.state["states"] = {(1, "mysterium"): "a-fresh-volume"}
        _heartbeat(ui, 1)
        assert _upload(ui, bundle).json()["live_on"] == []


class TestOneMoreContainerOfTheImage:
    """A box reports one fingerprint per container; one more of the same image must not hide the restored node."""

    def _beat(self, ui, worker_id: int, *state_ids: str | None) -> None:
        """The heartbeat as the worker sends it: one entry per container, with its own fingerprint (None: none sent)."""
        box = next(w for w in ui.workers if w["id"] == worker_id)
        box["containers"] = [{"slug": "mysterium", **({"state_id": s} if s else {})} for s in state_ids]
        _heartbeat(ui, worker_id)

    def test_an_unknown_fingerprint_beside_another_container_still_holds_it(self, ui):
        """The restored node's volume read failed this beat; one more container of the image reports its own."""
        f1 = mysterium_bundle()
        _runs(ui, 2, "S1")
        _export_route(ui, f1, 2, "S1")
        _runs(ui, None)
        _restore_ok(ui, f1, 1, "SA")
        with (
            patch.object(main.payout_registry, "state_ids", REAL_STATE_IDS),
            patch.object(main.payout_registry, "all_state_ids", REAL_ALL_STATE_IDS),
        ):
            self._beat(ui, 1, None, "H")
            preview = _upload(ui, f1).json()
            assert preview["live_on"] == ["box-a"]
            resp = _restore(
                ui, preview["upload_id"], worker_id=2, step_up_password=OWNER_PASSWORD, allow_plain_http=True
            )
        assert resp.status_code == 409 and "box-a" in _detail(resp)
        assert [s["worker_id"] for s in ui.sent if s["path"].endswith("/restore")] == [1]

    def test_a_second_container_does_not_free_the_restored_node(self, ui):
        f1 = mysterium_bundle()
        _runs(ui, 2, "S1")
        _export_route(ui, f1, 2, "S1")  # F1 from box-b
        _runs(ui, None)
        _restore_ok(ui, f1, 1, "SA")  # F1 restored on box-a
        with (
            patch.object(main.payout_registry, "state_ids", REAL_STATE_IDS),
            patch.object(main.payout_registry, "all_state_ids", REAL_ALL_STATE_IDS),
        ):
            # box-a's heartbeat: the restored node, then one more mysterium-image container listed after it.
            self._beat(ui, 1, "SA", "H")
            preview = _upload(ui, f1).json()
            assert preview["live_on"] == ["box-a"]
            resp = _restore(
                ui, preview["upload_id"], worker_id=2, step_up_password=OWNER_PASSWORD, allow_plain_http=True
            )
        assert resp.status_code == 409 and "box-a" in _detail(resp)
        assert [s["worker_id"] for s in ui.sent if s["path"].endswith("/restore")] == [1]

    def test_no_container_on_the_restored_volume_frees_it(self, ui):
        """The check still goes red: when nothing on the box reports the restored volume, it is free."""
        f1 = mysterium_bundle()
        _runs(ui, 2, "S1")
        _export_route(ui, f1, 2, "S1")
        _runs(ui, None)
        _restore_ok(ui, f1, 1, "SA")
        with (
            patch.object(main.payout_registry, "state_ids", REAL_STATE_IDS),
            patch.object(main.payout_registry, "all_state_ids", REAL_ALL_STATE_IDS),
        ):
            self._beat(ui, 1, "a-fresh-volume", "H")
            assert _upload(ui, f1).json()["live_on"] == []

    def test_a_partial_heartbeat_does_not_free_the_restored_node(self, ui):
        """The box could not read the restored node's container this beat: a list with only the other one is not proof."""
        f1 = mysterium_bundle()
        _runs(ui, 2, "S1")
        _export_route(ui, f1, 2, "S1")
        _runs(ui, None)
        _restore_ok(ui, f1, 1, "SA")
        box = next(w for w in ui.workers if w["id"] == 1)
        box["system_info"] = json.dumps({"containers_listed": False})
        with (
            patch.object(main.payout_registry, "state_ids", REAL_STATE_IDS),
            patch.object(main.payout_registry, "all_state_ids", REAL_ALL_STATE_IDS),
        ):
            self._beat(ui, 1, "H")
            preview = _upload(ui, f1).json()
            assert preview["live_on"] == ["box-a"]
            resp = _restore(
                ui, preview["upload_id"], worker_id=2, step_up_password=OWNER_PASSWORD, allow_plain_http=True
            )
        assert resp.status_code == 409 and "box-a" in _detail(resp)
        assert [s["worker_id"] for s in ui.sent if s["path"].endswith("/restore")] == [1]

    def test_a_partial_heartbeat_that_lists_no_container_of_the_service_does_not_free_it(self, ui):
        """With no deploy record and a heartbeat that could not list its containers, the box looked like it ran no
        Mysterium at all: the export row stopped holding the identity, so a second box was offered it."""
        f1 = mysterium_bundle()
        _runs(ui, 2, "S1")
        _export_route(ui, f1, 2, "S1")
        _runs(ui, None)  # the deploy record is gone, and no runs_on lists box-b
        box = next(w for w in ui.workers if w["id"] == 2)
        box["system_info"] = json.dumps({"containers_listed": False})
        with (
            patch.object(main.payout_registry, "state_ids", REAL_STATE_IDS),
            patch.object(main.payout_registry, "all_state_ids", REAL_ALL_STATE_IDS),
        ):
            self._beat(ui, 2)  # no container of the slug listed, and the list is partial
            preview = _upload(ui, f1).json()
            assert preview["live_on"] == ["box-b"]
            resp = _restore(ui, preview["upload_id"], worker_id=1, step_up_password=OWNER_PASSWORD)
        assert resp.status_code == 409 and "box-b" in _detail(resp)
        assert [s["worker_id"] for s in ui.sent if s["path"].endswith("/restore")] == []

    def test_control_a_whole_heartbeat_with_no_container_of_the_service_frees_it(self, ui):
        f1 = mysterium_bundle()
        _runs(ui, 2, "S1")
        _export_route(ui, f1, 2, "S1")
        _runs(ui, None)
        with (
            patch.object(main.payout_registry, "state_ids", REAL_STATE_IDS),
            patch.object(main.payout_registry, "all_state_ids", REAL_ALL_STATE_IDS),
        ):
            self._beat(ui, 2)
            assert _upload(ui, f1).json()["live_on"] == []

    def test_an_export_with_no_fingerprint_does_not_take_another_containers(self, ui):
        """The worker could not fingerprint the volume it exported: the heartbeat's last container is not that volume."""
        f1 = mysterium_bundle()
        ui.state["runs_on"] = {"mysterium": [{"worker_id": 2}]}
        box_b = next(w for w in ui.workers if w["id"] == 2)
        answer = {"bundle_b64": base64.b64encode(f1).decode(), "state_id": None, "targets": [], "bytes": 1}
        with (
            patch.object(main.payout_registry, "state_ids", REAL_STATE_IDS),
            patch.object(main.payout_registry, "all_state_ids", REAL_ALL_STATE_IDS),
        ):
            # box-b runs the node (S1), and one more container of the image (H) listed after it.
            self._beat(ui, 2, "S1", "H")
            with (
                patch.object(
                    main,
                    "_backup_box",
                    AsyncMock(return_value={"worker_id": 2, "name": "box-b", "workers": ui.workers}),
                ),
                patch.object(main, "_worker_features", AsyncMock(return_value={"state_backup"})),
                patch.object(main, "_proxy_to_worker", AsyncMock(return_value=answer)),
            ):
                resp = ui.post(
                    "/api/payout-registry/mysterium/backup-export",
                    json={"worker_id": 2, "passphrase": PASSPHRASE, "passphrase_repeat": PASSPHRASE},
                )
            assert resp.status_code == 200, resp.text
            # A newer heartbeat: the other container went, the node still runs on box-b.
            box_b["containers"] = [{"slug": "mysterium", "state_id": "S1"}]
            _heartbeat(ui, 2, (datetime.now(UTC) + timedelta(seconds=5)).strftime("%Y-%m-%d %H:%M:%S"))
            preview = _upload(ui, f1).json()
            assert preview["live_on"] == ["box-b"]
            resp = _restore(ui, preview["upload_id"], worker_id=1, step_up_password=OWNER_PASSWORD)
        assert resp.status_code == 409 and "box-b" in _detail(resp)
        assert [s["worker_id"] for s in ui.sent if s["path"].endswith("/restore")] == []

    def test_a_restore_helper_is_not_listed_as_a_node_of_its_image(self):
        image = MYSTERIUM_DEPLOY["image"]

        def container(cid, labels):
            return MagicMock(id=cid, short_id=cid, labels=labels, attrs={"Config": {"Image": image}})

        helper = container("helper", {orchestrator.LABEL_RESTORE: "helper"})
        node = container("node", {})
        client = MagicMock()
        client.containers.list.return_value = [node, helper]
        assert orchestrator._external_candidates(client, {image: "mysterium"}) == [node]

    def test_the_fingerprint_list_keeps_every_container_in_order(self):
        workers = [
            {"id": 1, "containers": [{"slug": "mysterium", "state_id": "SA"}, {"slug": "mysterium", "state_id": "H"}]}
        ]
        assert payout_registry.all_state_ids(workers) == {(1, "mysterium"): ["SA", "H"]}
        assert payout_registry.state_ids(workers) == {(1, "mysterium"): "H"}

    def test_a_container_with_no_fingerprint_is_kept_as_unknown(self):
        workers = [{"id": 1, "containers": [{"slug": "mysterium"}, {"slug": "mysterium", "state_id": "H"}]}]
        assert payout_registry.all_state_ids(workers) == {(1, "mysterium"): [None, "H"]}
        assert payout_registry.state_ids(workers) == {(1, "mysterium"): "H"}
        assert payout_registry.state_ids([{"id": 1, "containers": [{"slug": "mysterium"}]}]) == {}


class TestARestoreWithNoAnswer:
    def _lost(self, ui, bundle, exc):
        upload = _upload(ui, bundle).json()
        with patch.object(main, "_proxy_to_worker", AsyncMock(side_effect=exc)):
            return _restore(ui, upload["upload_id"], worker_id=1, step_up_password=OWNER_PASSWORD)

    def test_a_box_still_pulling_after_a_timeout_holds_the_identity(self, ui):
        """No heartbeat lists it yet, and no deploy record: the pending row alone refuses another box."""
        bundle = mysterium_bundle()
        _export(bundle, 2)
        assert self._lost(ui, bundle, main._WorkerNoAnswer(504, "no answer")).status_code == 504
        upload = _upload(ui, bundle).json()
        assert upload["live_on"] == ["box-a"]
        resp = _restore(ui, upload["upload_id"], worker_id=2, step_up_password=OWNER_PASSWORD, allow_plain_http=True)
        assert resp.status_code == 409 and "box-a" in _detail(resp)

    def test_a_dropped_connection_holds_it_too(self, ui):
        bundle = mysterium_bundle()
        _export(bundle, 2)
        assert self._lost(ui, bundle, main._WorkerNoAnswer(503, "Worker communication failed")).status_code == 503
        upload = _upload(ui, bundle).json()
        resp = _restore(ui, upload["upload_id"], worker_id=2, step_up_password=OWNER_PASSWORD, allow_plain_http=True)
        assert resp.status_code == 409 and "box-a" in _detail(resp)

    def test_the_box_it_was_sent_to_may_take_it_again_and_that_settles_it(self, ui):
        bundle = mysterium_bundle()
        _export(bundle, 2)
        self._lost(ui, bundle, main._WorkerNoAnswer(504, "no answer"))
        upload = _upload(ui, bundle).json()
        resp = _restore(ui, upload["upload_id"], worker_id=1, step_up_password=OWNER_PASSWORD)
        assert resp.status_code == 200, resp.text
        rows = [(r["worker_id"], r["source"]) for r in asyncio.run(database.backup_records(_sha(bundle)))]
        assert rows == [(2, "export"), (1, "restore")]

    def test_a_restore_that_was_never_sent_leaves_no_row(self, ui):
        bundle = mysterium_bundle()
        from fastapi import HTTPException

        self._lost(ui, bundle, HTTPException(503, "Worker communication failed"))
        assert asyncio.run(database.backup_records(_sha(bundle))) == []

    def test_a_failure_after_the_worker_restored_it_is_still_recorded(self, ui):
        bundle = mysterium_bundle()
        upload = _upload(ui, bundle).json()
        with patch.object(main.database, "save_deployment", AsyncMock(side_effect=RuntimeError("db locked"))):
            resp = _restore(ui, upload["upload_id"], confirm_name="Mysterium", step_up_password=OWNER_PASSWORD)
        assert resp.status_code == 500
        assert [r["source"] for r in asyncio.run(database.backup_records(_sha(bundle)))] == ["restore"]


class TestTheWorkerProxyErrors:
    """Only a failure to connect means the worker never got the request."""

    async def _call(self, exc, answer=None, marked=True):
        worker = {"id": 1, "url": "https://a"}
        with (
            patch.object(main.database, "get_worker", AsyncMock(return_value=worker)),
            patch.object(main, "_get_verified_worker_url", AsyncMock(return_value=("https://a", {}))),
            patch("httpx.AsyncClient.post", AsyncMock(side_effect=exc, return_value=answer)),
        ):
            await main._proxy_to_worker(1, "POST", "/api/containers/mysterium/restore", json={}, marked=marked)

    @pytest.mark.parametrize(
        "exc", [httpx.ReadError("reset"), httpx.RemoteProtocolError("closed"), httpx.ReadTimeout("slow")]
    )
    def test_an_error_after_the_request_went_out_is_no_answer(self, exc):
        with pytest.raises(main._WorkerNoAnswer):
            asyncio.run(self._call(exc))

    @pytest.mark.parametrize("status", [502, 503, 504, 520, 524])
    def test_a_gateway_error_in_front_of_the_worker_is_no_answer(self, status):
        answer = httpx.Response(status, request=httpx.Request("POST", "https://a/api/containers/mysterium/restore"))
        with pytest.raises(main._WorkerNoAnswer):
            asyncio.run(self._call(None, answer))

    def test_an_unmarked_route_keeps_the_status_reading(self):
        """A deploy's 503 is the worker's own (main._GATEWAY_NO_ANSWER): only the restore marks its answers."""
        from fastapi import HTTPException

        answer = httpx.Response(503, request=httpx.Request("POST", "https://a/api/containers/mysterium/deploy"))
        with pytest.raises(HTTPException) as caught:
            asyncio.run(self._call(None, answer, marked=False))
        assert not isinstance(caught.value, main._WorkerNoAnswer) and not main._outcome_unknown(caught.value)

    def test_the_workers_own_refusal_is_a_plain_refusal(self):
        answer = httpx.Response(409, json={"detail": "volume exists"}, request=httpx.Request("POST", "https://a/x"))
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as caught:
            asyncio.run(self._call(None, answer))
        assert caught.value.status_code == 409 and not isinstance(caught.value, main._WorkerNoAnswer)

    @pytest.mark.parametrize(
        "exc", [httpx.ConnectError("refused"), httpx.ConnectTimeout("slow"), httpx.PoolTimeout("full")]
    )
    def test_a_connect_failure_is_a_plain_refusal(self, exc):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as caught:
            asyncio.run(self._call(exc))
        assert caught.value.status_code == 503 and not isinstance(caught.value, main._WorkerNoAnswer)


class TestRemoveAfterARestoreThatDidNotFinish:
    """The dashboard's Remove gets the worker's code, and the delete it then offers stays owner-only and audited."""

    UNFINISHED = {
        "detail": {
            "error": "restore_unfinished",
            "message": "A restore of mysterium did not finish, so its data volume holds a partial restore.",
        }
    }

    def _remove(self, ui, query, status, body, box="?worker_id=1", password=OWNER_PASSWORD):
        """A Remove as the dashboard sends it: a data delete carries the owner's password in its body."""
        request = httpx.Request("DELETE", "https://a/api/containers/mysterium")
        answer = httpx.Response(status, request=request, json=body)
        sent = AsyncMock(return_value=answer)
        with (
            patch.object(main, "_proxy_to_worker", REAL_PROXY),
            patch.object(main, "_get_verified_worker_url", AsyncMock(return_value=("https://a", {}))),
            patch("httpx.AsyncClient.delete", sent),
        ):
            url = f"/api/services/mysterium{box}{query}"
            if password is None:
                return ui.delete(url), sent
            return ui.request("DELETE", url, json={"step_up_password": password}), sent

    def test_the_refusal_reaches_the_dashboard_with_its_code(self, ui):
        resp, _sent = self._remove(ui, "", 409, self.UNFINISHED, box="?worker_id=2")
        assert resp.status_code == 409
        assert resp.json()["detail"] == {**self.UNFINISHED["detail"], "worker_id": 2, "worker_name": "box-b"}

    def test_the_refusal_names_the_box_it_picked(self, ui, monkeypatch):
        """With one box online the Remove names none; the refusal says which, so the delete goes there only."""
        monkeypatch.setattr(main, "_resolve_worker_id", REAL_RESOLVE)
        ui.workers[1]["status"] = "offline"
        resp, _sent = self._remove(ui, "", 409, self.UNFINISHED, box="")
        assert resp.status_code == 409
        assert resp.json()["detail"] == {**self.UNFINISHED["detail"], "worker_id": 1, "worker_name": "box-a"}

    def test_the_owner_deletes_the_data_and_it_is_audited(self, ui):
        resp, sent = self._remove(
            ui,
            "&delete_volumes=true&allow_delete_critical=true",
            200,
            {"status": "removed", "deleted_volumes": ["mysterium-data"]},
        )
        assert resp.status_code == 200
        assert sent.call_args.kwargs["params"] == {"delete_volumes": "true", "allow_delete_critical": "true"}
        assert ("delete_critical_volumes", "deleted") in _audit()

    def test_a_delete_that_removed_no_volume_is_not_audited_as_deleted(self, ui):
        resp, _sent = self._remove(
            ui,
            "&delete_volumes=true&allow_delete_critical=true",
            200,
            {"status": "removed", "deleted_volumes": [], "failed_volumes": []},
        )
        assert resp.status_code == 200
        assert ("delete_critical_volumes", "none_deleted") in _audit()
        assert ("delete_critical_volumes", "deleted") not in _audit()

    def test_a_replaced_volume_alone_is_audited_as_partial(self, ui):
        """A worker answer that names a replaced volume only in replaced_volumes still did not delete it."""
        resp, _sent = self._remove(
            ui,
            "&delete_volumes=true&allow_delete_critical=true",
            200,
            {"status": "removed", "deleted_volumes": ["other"], "replaced_volumes": ["mysterium-data"]},
        )
        assert resp.status_code == 200
        assert ("delete_critical_volumes", "partial") in _audit()

    def test_a_volume_the_box_kept_is_audited_as_partial(self, ui):
        resp, _sent = self._remove(
            ui,
            "&delete_volumes=true&allow_delete_critical=true",
            200,
            {"status": "removed", "deleted_volumes": [], "failed_volumes": ["mysterium-data"]},
        )
        assert resp.status_code == 200
        assert resp.json()["failed_volumes"] == ["mysterium-data"]
        assert ("delete_critical_volumes", "partial") in _audit()
        assert ("delete_critical_volumes", "deleted") not in _audit()

    def test_a_writer_cannot_delete_it(self, ui):
        ui.state["user"] = {**ui.state["user"], "r": "writer"}
        resp, sent = self._remove(ui, "&delete_volumes=true&allow_delete_critical=true", 200, {"status": "removed"})
        assert resp.status_code == 403 and not sent.called


class TestDeletingANodeIdentityNeedsThePassword:
    """Destroying a wallet or node identity asks for the owner's password, as restoring one does."""

    CRITICAL = "&delete_volumes=true&allow_delete_critical=true"
    REMOVED = {"status": "removed", "deleted_volumes": ["mysterium-data"]}

    def _remove(self, ui, query, password, box="?worker_id=2"):
        return TestRemoveAfterARestoreThatDidNotFinish()._remove(ui, query, 200, self.REMOVED, box, password)

    def test_without_the_password_it_asks_and_deletes_nothing(self, ui):
        resp, sent = self._remove(ui, self.CRITICAL, None)
        detail = resp.json()["detail"]
        assert resp.status_code == 403 and detail["error"] == "step_up_required"
        assert "mysterium on box-b" in detail["message"] and "password" in detail["message"]
        assert not sent.called
        assert ("delete_critical_volumes", "deleted") not in _audit()

    def test_a_wrong_password_deletes_nothing_and_is_audited(self, ui):
        resp, sent = self._remove(ui, self.CRITICAL, "nope")
        assert resp.status_code == 403 and resp.json()["detail"]["error"] == "step_up_failed"
        assert not sent.called
        assert ("delete-critical-volumes", "failed") in _audit()

    def test_with_the_password_it_deletes_and_both_are_audited(self, ui):
        resp, sent = self._remove(ui, self.CRITICAL, OWNER_PASSWORD)
        assert resp.status_code == 200 and sent.called
        assert sent.call_args.kwargs["params"] == {"delete_volumes": "true", "allow_delete_critical": "true"}
        events = asyncio.run(database.get_audit_events())
        confirmed = [e for e in events if e["action"] == "delete-critical-volumes"]
        assert [(e["target"], e["outcome"]) for e in confirmed] == [("mysterium|2", "confirmed")]
        assert ("delete_critical_volumes", "deleted") in _audit()

    def test_the_delete_carries_an_approval_only_that_box_accepts(self, ui):
        resp, sent = self._remove(ui, self.CRITICAL, OWNER_PASSWORD)
        assert resp.status_code == 200
        approval = sent.call_args.kwargs["headers"][step_up.APPROVAL_HEADER]
        with pytest.raises(step_up.StepUpError, match="another action"):
            step_up.check(WORKER_KEY, approval, step_up.ACTION_DELETE_CRITICAL, "mysterium|client-a")
        step_up.check(WORKER_KEY, approval, step_up.ACTION_DELETE_CRITICAL, "mysterium|client-b")

    def test_a_box_that_has_not_enrolled_is_sent_nothing(self, ui):
        with patch.object(main, "_confirmed_worker_key", AsyncMock(return_value=None)):
            resp, sent = self._remove(ui, self.CRITICAL, OWNER_PASSWORD)
        assert resp.status_code == 409 and "enrolling" in _detail(resp)
        assert not sent.called

    def test_control_a_removal_that_keeps_critical_data_sends_no_approval(self, ui):
        resp, sent = self._remove(ui, "&delete_volumes=true", None)
        assert resp.status_code == 200
        assert step_up.APPROVAL_HEADER not in sent.call_args.kwargs["headers"]

    def test_the_api_key_cannot_delete_it(self, ui):
        ui.state["user"] = {"uid": 0, "u": "api", "r": "owner"}
        resp, sent = self._remove(ui, self.CRITICAL, OWNER_PASSWORD)
        assert resp.status_code == 403 and not sent.called
        assert ("delete-critical-volumes", "refused") in _audit()

    def test_the_delete_of_a_partial_restore_asks_too(self, ui):
        resp, sent = self._remove(ui, self.CRITICAL + "&only_if_restore_unfinished=true", None)
        assert resp.status_code == 403 and resp.json()["detail"]["error"] == "step_up_required"
        assert not sent.called

    @pytest.mark.parametrize("query", ["", "&delete_volumes=true", "&only_if_restore_unfinished=true"])
    def test_control_a_removal_that_keeps_critical_data_needs_no_password(self, ui, query):
        resp, sent = self._remove(ui, query, None)
        assert resp.status_code == 200 and sent.called
        assert not [e for e in _audit() if e[0] == "delete-critical-volumes"]


class TestTheWorkerChecksTheCriticalDeleteApproval:
    """The worker itself refuses a delete of critical data without the owner's approval.

    The fleet key an owner can reveal, or the admin API key behind it, must
    not reach past the UI's password check by calling the worker directly.
    """

    URL = "/api/containers/mysterium?delete_volumes=true&allow_delete_critical=true"

    def _delete(self, worker, monkeypatch, headers):
        removed = MagicMock(return_value={"container": "cashpilot-mysterium", "deleted_volumes": []})
        monkeypatch.setattr(worker_api.orchestrator, "remove_service", removed)
        monkeypatch.setattr(worker_api.orchestrator, "remove_extra_instances", lambda slug: [])
        monkeypatch.setattr(worker_api.orchestrator, "copy_identity_digests", lambda slug: {})
        monkeypatch.setattr(worker_api.proxy_tunnel, "remove_all", lambda slug: [])
        resp = worker.client.delete(self.URL, headers={"Authorization": f"Bearer {WORKER_KEY}", **headers})
        return resp, removed

    def test_without_an_approval_nothing_is_removed(self, worker, monkeypatch):
        resp, removed = self._delete(worker, monkeypatch, {})
        detail = resp.json()["detail"]
        assert resp.status_code == 403 and detail["error"] == "step_up_rejected"
        assert "Nothing was removed" in detail["message"]
        assert not removed.called

    def test_on_the_shared_fleet_key_nothing_is_removed(self, worker, monkeypatch):
        monkeypatch.setattr(worker_api, "_worker_key", None)
        monkeypatch.setattr(worker_api, "API_KEY", WORKER_KEY)  # the revealed shared key
        resp, removed = self._delete(worker, monkeypatch, _delete_approval())
        assert resp.status_code == 403 and "shared fleet key" in resp.json()["detail"]["message"]
        assert not removed.called

    @pytest.mark.parametrize(
        "other",
        [{"slug": "storj"}, {"client_id": "another-box"}, {"key": "the-shared-fleet-key"}],
        ids=["another-service", "another-box", "another-key"],
    )
    def test_an_approval_for_something_else_removes_nothing(self, worker, monkeypatch, other):
        resp, removed = self._delete(worker, monkeypatch, _delete_approval(**other))
        assert resp.status_code == 403 and resp.json()["detail"]["error"] == "step_up_rejected"
        assert not removed.called

    def test_an_approval_carries_one_delete(self, worker, monkeypatch):
        approval = _delete_approval()
        assert self._delete(worker, monkeypatch, approval)[0].status_code == 200
        resp, removed = self._delete(worker, monkeypatch, approval)
        assert resp.status_code == 403 and "already used" in resp.json()["detail"]["message"]
        assert not removed.called

    def test_control_the_owners_approval_removes_it(self, worker, monkeypatch):
        resp, removed = self._delete(worker, monkeypatch, _delete_approval())
        assert resp.status_code == 200, resp.text
        removed.assert_called_once_with(
            "mysterium",
            delete_volumes=True,
            allow_delete_critical=True,
            only_if_restore_unfinished=False,
            # The approval named no reviewed set, so the removal deletes no critical volume.
            approved_critical="",
        )

    @pytest.mark.parametrize("query", ["?delete_volumes=true", "?allow_delete_critical=true", ""])
    def test_control_a_removal_that_keeps_the_guard_needs_none(self, worker, monkeypatch, query):
        monkeypatch.setattr(self, "URL", f"/api/containers/mysterium{query}")
        resp, removed = self._delete(worker, monkeypatch, {})
        assert resp.status_code == 200 and removed.called


class TestARestoreTheWorkerUndid:
    """The worker's own 503 says the restore was undone: no gateway sends that, so nothing holds the identity."""

    UNDONE = {"detail": "Docker is not reachable. The restore was undone.", "restored": False}

    def test_the_worker_says_so_in_its_answer(self, worker, monkeypatch):
        def fails(*_a):
            raise orchestrator.RestoreError("Docker is not reachable. The restore was undone.", 503)

        monkeypatch.setattr(worker_api.orchestrator, "restore_state", fails)
        resp = worker("proxybase-xyz", proxybase_bundle())
        assert resp.status_code == 503 and resp.json() == self.UNDONE

    def _answer(self, ui, bundle, status, body):
        request = httpx.Request("POST", "https://a/api/containers/mysterium/restore")
        answer = httpx.Response(status, request=request, **({"json": body} if body is not None else {}))
        upload = _upload(ui, bundle).json()
        with (
            patch.object(main, "_proxy_to_worker", REAL_PROXY),
            patch.object(main, "_get_verified_worker_url", AsyncMock(return_value=("https://a", {}))),
            patch("httpx.AsyncClient.post", AsyncMock(return_value=answer)),
        ):
            return _restore(ui, upload["upload_id"], worker_id=1, step_up_password=OWNER_PASSWORD)

    def test_an_undone_restore_leaves_no_pending_row(self, ui):
        bundle = mysterium_bundle()
        _export(bundle, 2)
        resp = self._answer(ui, bundle, 503, self.UNDONE)
        assert resp.status_code == 503 and "undone" in _detail(resp)
        assert [r["source"] for r in asyncio.run(database.backup_records(_sha(bundle)))] == ["export"]
        assert _upload(ui, bundle).json()["live_on"] == []

    def test_a_gateways_503_still_holds_it(self, ui):
        bundle = mysterium_bundle()
        _export(bundle, 2)
        assert self._answer(ui, bundle, 503, None).status_code == 503
        assert _upload(ui, bundle).json()["live_on"] == ["box-a"]

    def test_a_restore_the_worker_could_not_fully_undo_says_so(self, worker, monkeypatch):
        def fails(*_a):
            raise orchestrator.RestoreError("Could not remove cashpilot-proxybase-xyz", 409, left=["cashpilot-x"])

        monkeypatch.setattr(worker_api.orchestrator, "restore_state", fails)
        resp = worker("proxybase-xyz", proxybase_bundle())
        assert resp.status_code == 409 and "restored" not in resp.json()
        assert resp.json()["left"] == ["cashpilot-x"]

    @pytest.mark.parametrize("status", [409, 500, 503])
    def test_what_the_worker_left_on_the_box_still_holds_it(self, ui, status):
        """The data it wrote may still be there, in a container the owner can start."""
        bundle = mysterium_bundle()
        _export(bundle, 2)
        body = {"detail": "It was undone. Could not remove cashpilot-mysterium: remove it by hand.", "left": ["x"]}
        assert self._answer(ui, bundle, status, body).status_code == status
        assert [r["source"] for r in asyncio.run(database.backup_records(_sha(bundle)))] == ["export", "pending"]
        assert _upload(ui, bundle).json()["live_on"] == ["box-a"]

    def test_remove_of_a_volume_another_client_replaced_keeps_the_hold(self, ui):
        """Remove clears the box's mark of the restore, never the dashboard's hold, and docs/backup.md says so."""
        bundle = mysterium_bundle()
        _export(bundle, 2)
        left = {"detail": "Another client replaced mysterium-data while the restore wrote it.", "left": ["x"]}
        assert self._answer(ui, bundle, 409, left).status_code == 409
        removed = {
            "container": "cashpilot-mysterium",
            "deleted_volumes": [],
            "failed_volumes": ["mysterium-data"],
            "replaced_volumes": ["mysterium-data"],
        }
        resp, _sent = TestRemoveAfterARestoreThatDidNotFinish()._remove(
            ui, "&delete_volumes=true&allow_delete_critical=true&only_if_restore_unfinished=true", 200, removed
        )
        assert resp.status_code == 200, resp.text
        assert [r["source"] for r in asyncio.run(database.backup_records(_sha(bundle)))] == ["export", "pending"]
        assert _upload(ui, bundle).json()["live_on"] == ["box-a"]
        doc = " ".join((Path(__file__).resolve().parents[1] / "docs" / "backup.md").read_text("utf-8").split())
        assert "The hold ends when you press" not in doc
        assert "That Remove does not end the dashboard's hold on the identity on that box" in doc


class TestTheUploadFolder:
    def test_a_sweep_from_another_request_spares_an_upload_still_arriving(self, ui):
        real = main._read_bundle_header

        def header_after_a_sweep(path):
            main._restore_sweep()  # another tab's request, while this body was streaming
            return real(path)

        with patch.object(main, "_read_bundle_header", side_effect=header_after_a_sweep):
            resp = _upload(ui, mysterium_bundle())
        assert resp.status_code == 200, resp.text
        assert main._restore_receiving == set()

    @staticmethod
    def _upload_then_wait(ui, monkeypatch, *, held: bool = False) -> list[list[str]]:
        """Upload on one event loop that keeps running, as the server's does, and send nothing more.

        No request and no scheduler sweep runs after the upload: only the
        upload's own timer can delete the file. Returns what is on disk at
        each look.
        """
        monkeypatch.setattr(main, "RESTORE_UPLOAD_TTL", 0.2)
        seen: list[list[str]] = []

        async def go():
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                resp = await client.post(
                    "/api/restore/upload",
                    content=mysterium_bundle(),
                    headers={"Content-Type": "application/octet-stream"},
                )
                assert resp.status_code == 200, resp.text
                seen.append(_uploads_on_disk(ui))
                if held:
                    main._restore_inflight.add(next(iter(main._restore_uploads.values()))["sha256"])
                await asyncio.sleep(0.6)
                seen.append(_uploads_on_disk(ui))
                if held:
                    main._restore_inflight.clear()
                    await asyncio.sleep(1.3)
                    seen.append(_uploads_on_disk(ui))

        try:
            asyncio.run(go())
        finally:
            main._restore_inflight.clear()
        return seen

    def test_an_upload_no_restore_used_is_deleted_at_the_ttl_with_no_request(self, ui, monkeypatch):
        seen = self._upload_then_wait(ui, monkeypatch)
        assert len(seen[0]) == 1 and seen[1] == [] and main._restore_uploads == {}

    def test_an_upload_a_restore_is_sending_waits_for_it_then_goes(self, ui, monkeypatch):
        seen = self._upload_then_wait(ui, monkeypatch, held=True)
        assert len(seen[0]) == 1 and seen[1] == seen[0] and seen[2] == []

    def test_a_sweep_while_the_restore_is_past_its_step_up_spares_the_file(self, ui):
        upload = _upload(ui, mysterium_bundle()).json()
        real = main.require_step_up

        async def step_up_then_a_sweep(*args, **kwargs):
            await real(*args, **kwargs)
            # The TTL passes and the scheduler's sweep, or another upload, runs
            # before the restore opens the file.
            main._restore_uploads[upload["upload_id"]]["created"] -= main.RESTORE_UPLOAD_TTL + 1
            main._restore_sweep()

        with patch.object(main, "require_step_up", side_effect=step_up_then_a_sweep):
            resp = _restore(ui, upload["upload_id"], confirm_name="Mysterium", step_up_password=OWNER_PASSWORD)
        assert resp.status_code == 200, resp.text
        assert len(ui.sent) == 1 and _uploads_on_disk(ui) == [] and main._restore_uploads == {}

    def test_a_sweep_after_a_refused_restore_deletes_the_expired_file(self, ui):
        upload = _upload(ui, mysterium_bundle()).json()
        resp = _restore(ui, upload["upload_id"], confirm_name="Mysterium")
        assert resp.status_code == 403 and _uploads_on_disk(ui) != []
        main._restore_uploads[upload["upload_id"]]["created"] -= main.RESTORE_UPLOAD_TTL + 1
        main._restore_sweep()
        assert _uploads_on_disk(ui) == [] and main._restore_uploads == {}

    def test_a_file_changed_on_disk_after_the_upload_is_not_sent(self, ui):
        upload = _upload(ui, mysterium_bundle()).json()
        (name,) = _uploads_on_disk(ui)
        with open(ui.tmp / "restore-uploads" / name, "ab") as fh:
            fh.write(b"x")
        resp = _restore(ui, upload["upload_id"], confirm_name="Mysterium", step_up_password=OWNER_PASSWORD)
        assert resp.status_code == 409 and "changed on disk" in _detail(resp) and ui.sent == []


class TestARestoreAndADeployOfOneService:
    """Nothing else serializes them for a service that is not fence-gated."""

    def test_a_deploy_while_the_restore_writes_is_refused(self, docker):
        seen: list[Exception] = []
        real_put = FakeContainer.put_archive

        def put(self, path, data):
            try:
                orchestrator._holds_gated_lock(lambda **_kw: "deployed")(slug="mysterium")
            except orchestrator.ContainerRuntimeError as exc:
                seen.append(exc)
            return real_put(self, path, data)

        with patch.object(FakeContainer, "put_archive", put):
            result = orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert result["started"] is True
        assert len(seen) == 1 and seen[0].status_code == 409 and "restore of mysterium" in str(seen[0])
        assert orchestrator._restoring == set()

    def test_a_restore_while_a_deploy_runs_is_refused(self, docker):
        def deploy(**_kw):
            return orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)

        with pytest.raises(orchestrator.RestoreError, match="a deploy of mysterium is running"):
            orchestrator._holds_gated_lock(deploy)(slug="mysterium")
        assert docker.creates == [] and docker.volume_map == {}
        assert orchestrator._deploying == {}


class TestARestoreAndTheRoute:
    """A restored container runs from this box's own IP: the deploy's route rule holds it too."""

    def test_the_real_deploy_raw_decorators_do_not_refuse_the_restore_itself(self, docker):
        """restore_state calls the undecorated deploy_raw: both decorators wrap it now.

        Wrapped the way the real one is, a call one decorator deep reaches the
        restore check of _holds_gated_lock, which refuses every restore.
        """
        stacked = orchestrator._holds_route_lock(orchestrator._holds_gated_lock(docker.deploy_raw))
        with patch.object(orchestrator, "deploy_raw", stacked):
            result = orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert result["started"] is True and docker.started == ["cashpilot-mysterium"]

    def test_a_proxied_only_box_refuses_the_restore_and_nothing_is_made(self, docker, monkeypatch):
        monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, "1")
        with pytest.raises(orchestrator.RestoreError, match="Nothing was restored: This worker runs") as exc:
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert exc.value.status_code == 403
        assert docker.volume_map == {} and docker.creates == [] and docker.started == []
        assert orchestrator._restoring == set()

    def test_a_service_routed_here_refuses_the_restore_and_nothing_is_made(self, docker):
        with (
            patch.object(route_gate, "routed", return_value={"mysterium": 3}),
            pytest.raises(orchestrator.RestoreError, match="runs through a proxy on this worker") as exc,
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert exc.value.status_code == 403
        assert docker.volume_map == {} and docker.creates == [] and docker.started == []

    def test_control_a_service_routed_elsewhere_restores(self, docker):
        with patch.object(route_gate, "routed", return_value={"storj": 3}):
            result = orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert result["started"] is True

    def test_the_route_lock_is_held_from_the_check_to_the_start(self, docker):
        """No routed deploy can mark the route while the restore writes, and start it from the box's IP."""
        import threading

        held: list[bool] = []
        real_start = FakeContainer.start

        def other_thread_gets_lock() -> bool:
            got: list[bool] = []

            def take():
                lock = route_gate.deploying("mysterium")
                ok = lock.acquire(timeout=0.2)
                if ok:
                    lock.release()
                got.append(ok)

            t = threading.Thread(target=take)
            t.start()
            t.join()
            return got[0]

        def start(self):
            held.append(not other_thread_gets_lock())
            return real_start(self)

        with patch.object(FakeContainer, "start", start):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert held == [True]
        assert other_thread_gets_lock() is True


class TestTheRestoreSafetyBranches:
    def test_a_container_started_by_something_else_mid_restore_is_undone(self, docker):
        with (
            patch.object(FakeContainer, "reload", lambda self: setattr(self, "status", "running")),
            pytest.raises(orchestrator.RestoreError, match="started before the restore finished"),
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert "cashpilot-mysterium" not in docker.container_map and docker.started == []
        _assert_kept_and_held(docker, "mysterium-data")

    def test_a_volume_the_proxy_will_not_show_counts_as_there(self, docker):
        response = requests.Response()
        response.status_code = 403
        with (
            patch.object(docker.volumes, "get", side_effect=APIError("forbidden", response=response)),
            pytest.raises(orchestrator.RestoreError, match="could not be checked"),
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert docker.creates == [] and docker.volume_map == {}

    def test_a_volume_still_held_by_our_own_unremovable_container_is_named_for_removal(self, docker):
        docker.corrupt_put = True
        real_remove = FakeContainer.remove

        def remove(self, force=False):
            if self.name == "cashpilot-mysterium":
                raise RuntimeError("busy")
            return real_remove(self, force)

        with patch.object(FakeContainer, "remove", remove), pytest.raises(orchestrator.RestoreError) as caught:
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert "cashpilot-mysterium" in str(caught.value) and "mysterium-data" in str(caught.value)
        assert caught.value.left == ["cashpilot-mysterium", "mysterium-data"]

    def test_a_helper_whose_removal_failed_is_removed_by_the_cleanup(self, docker):
        real_remove = FakeContainer.remove
        tries: list[str] = []

        def remove(self, force=False):
            tries.append(self.name)
            if self.name.endswith(".restore") and tries.count(self.name) == 1:
                raise RuntimeError("busy")
            return real_remove(self, force)

        with patch.object(FakeContainer, "remove", remove), pytest.raises(orchestrator.RestoreError) as caught:
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert tries.count("cashpilot-mysterium.restore") == 2
        assert "cashpilot-mysterium" not in docker.container_map
        _assert_kept_and_held(docker, "mysterium-data")
        assert caught.value.left == ["mysterium-data"]


class TestStartAndRemoveAroundARestore:
    """Start, Restart and Remove go around deploy_raw, so its guard alone left them open."""

    def _service(self, docker, *, helper=False):
        mounts = {"/var/lib/mysterium-node": "mysterium-data"}
        docker.volumes.create("mysterium-data")
        container = FakeContainer(
            docker,
            "cashpilot-mysterium",
            mounts,
            {orchestrator.LABEL_MANAGED: "true", orchestrator.LABEL_SERVICE: "mysterium"},
        )
        container.attrs["Mounts"] = [
            {"Type": "volume", "Name": "mysterium-data", "Destination": "/var/lib/mysterium-node"}
        ]
        docker.container_map[container.name] = container
        if helper:
            left = FakeContainer(
                docker,
                "cashpilot-mysterium.restore",
                {"/restore": "mysterium-data"},
                {orchestrator.LABEL_RESTORE: "helper"},
            )
            left.attrs["Mounts"] = [{"Type": "volume", "Name": "mysterium-data", "Destination": "/restore"}]
            docker.container_map[left.name] = left
        return container

    @pytest.mark.parametrize("command", ["start_service", "restart_service"])
    def test_no_start_while_the_restore_writes(self, docker, command):
        seen: list[Exception] = []
        real_put = FakeContainer.put_archive

        def put(self, path, data):
            try:
                getattr(orchestrator, command)("mysterium")
            except orchestrator.ContainerRuntimeError as exc:
                seen.append(exc)
            return real_put(self, path, data)

        with patch.object(FakeContainer, "put_archive", put):
            result = orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert result["started"] is True and docker.started == ["cashpilot-mysterium"]
        assert len(seen) == 1 and seen[0].status_code == 409 and "restore of mysterium is running" in str(seen[0])

    @pytest.mark.parametrize("command", ["start_service", "restart_service"])
    def test_a_half_written_restore_is_never_started(self, docker, command):
        """The worker died mid-write: its helper is still there, and the volume may hold half the backup."""
        self._service(docker, helper=True)
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish") as caught:
            getattr(orchestrator, command)("mysterium")
        assert caught.value.status_code == 409 and docker.started == []

    def test_a_service_with_no_leftover_starts(self, docker):
        self._service(docker)
        orchestrator.start_service("mysterium")
        assert docker.started == ["cashpilot-mysterium"]

    def test_remove_clears_the_leftover_helper_so_the_volume_goes(self, docker):
        self._service(docker, helper=True)
        result = _owner_removes("mysterium")
        assert result["deleted_volumes"] == ["mysterium-data"] and result["failed_volumes"] == []
        assert docker.container_map == {} and docker.volume_map == {}

    def test_a_volume_that_will_not_go_gets_its_restore_mark_back(self, docker):
        """The helper had to go first; a half-written volume that stays must still refuse a start and a deploy."""
        self._service(docker, helper=True)
        response = requests.Response()
        response.status_code = 500
        with patch.object(FakeVolume, "remove", side_effect=APIError("daemon timeout", response=response)):
            result = _owner_removes("mysterium")
        assert result["failed_volumes"] == ["mysterium-data"] and "mysterium-data" in docker.volume_map
        # A delete Docker refused is not another client's volume: Remove again is the way out.
        assert result["replaced_volumes"] == []
        assert docker.container_map["cashpilot-mysterium.restore"].mounts == {WRITE_MOUNT: "mysterium-data"}
        assert orchestrator._restore_helper("mysterium") is not None
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish"):
            self._deploy(docker)

    def test_remove_with_data_clears_a_helper_whose_service_is_gone(self, docker):
        """A restore's undo removed the container but not its helper: remove with data is the way out."""
        self._service(docker, helper=True)
        del docker.container_map["cashpilot-mysterium"]
        with pytest.raises(orchestrator.CriticalVolumeError):
            orchestrator.remove_service("mysterium", delete_volumes=True)
        assert "cashpilot-mysterium.restore" in docker.container_map and "mysterium-data" in docker.volume_map
        result = _owner_removes("mysterium")
        assert result["deleted_volumes"] == ["mysterium-data"] and result["failed_volumes"] == []
        assert docker.container_map == {} and docker.volume_map == {}
        with pytest.raises(orchestrator.ContainerRuntimeError, match="not available"):
            self._deploy(docker)

    def test_a_restore_attempt_keeps_the_mark_of_a_half_written_volume(self, docker):
        """Helper only, its volume still there: the restore refuses and keeps the helper, so no deploy starts on it."""
        self._service(docker, helper=True)
        del docker.container_map["cashpilot-mysterium"]
        with pytest.raises(orchestrator.RestoreError, match="with its data"):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert "cashpilot-mysterium.restore" in docker.container_map and "mysterium-data" in docker.volume_map
        assert orchestrator._restore_helper("mysterium") is not None
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish"):
            self._deploy(docker)

    def test_a_volume_delete_that_times_out_still_gets_its_mark_back(self, docker):
        """A transport error is not an APIError; the half-written volume that stays must keep its mark."""
        self._service(docker, helper=True)
        with patch.object(FakeVolume, "remove", side_effect=requests.exceptions.ReadTimeout("proxy timed out")):
            result = _owner_removes("mysterium")
        assert result["failed_volumes"] == ["mysterium-data"] and "mysterium-data" in docker.volume_map
        assert orchestrator._restore_helper("mysterium") is not None
        # A restore tried next on this box keeps the mark it put back.
        with pytest.raises(orchestrator.RestoreError, match="with its data"):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert orchestrator._restore_helper("mysterium") is not None
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish"):
            self._deploy(docker)

    def test_an_undo_that_cannot_remove_the_container_keeps_the_mark(self, docker):
        """The write died halfway and the undo could not remove the container: the volume stays in use, marked."""
        real_put, real_remove = FakeContainer.put_archive, FakeContainer.remove

        def put(container, path, data):
            real_put(container, path, data)
            raise RuntimeError("connection reset mid-write")

        def remove(container, force=False):
            if container.name == "cashpilot-mysterium":
                raise RuntimeError("read timeout")
            return real_remove(container, force)

        with (
            patch.object(FakeContainer, "put_archive", put),
            patch.object(FakeContainer, "remove", remove),
            pytest.raises(orchestrator.RestoreError, match="by hand"),
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert "cashpilot-mysterium" in docker.container_map and "mysterium-data" in docker.volume_map
        assert orchestrator._restore_helper("mysterium") is not None
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish"):
            orchestrator.start_service("mysterium")
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish"):
            self._deploy(docker)

    def test_an_undo_keeps_the_unchecked_volume_marked(self, docker):
        """The data did not read back: the undo keeps the unchecked volume, marked."""
        docker.corrupt_put = True
        with pytest.raises(orchestrator.RestoreError, match="stays held"):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert "cashpilot-mysterium" not in docker.container_map and "mysterium-data" in docker.volume_map
        assert orchestrator._restore_helper("mysterium") is not None
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish"):
            self._deploy(docker)

    def test_an_undo_that_made_nothing_leaves_no_mark(self, docker):
        with (
            patch.object(orchestrator, "_create_restore_volume", side_effect=orchestrator.RestoreError("refused")),
            pytest.raises(orchestrator.RestoreError),
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert docker.container_map == {} and docker.volume_map == {}
        assert orchestrator._restore_helper("mysterium") is None and "mysterium" not in orchestrator.restore_marks()

    def test_remove_with_no_container_and_no_helper_is_still_not_found(self, docker):
        with pytest.raises(ValueError):
            _owner_removes("mysterium")

    def _deploy(self, docker):
        """The real deploy_raw, as the worker's deploy route calls it. The fake has no image, so
        a deploy past the guard stops at 'not available' before it touches the old container."""
        docker.images = MagicMock()
        docker.images.get.side_effect = orchestrator.DockerException("no such image")
        return REAL_DEPLOY_RAW(slug="mysterium", image=MYSTERIUM_DEPLOY["image"], volumes=MYSTERIUM_DEPLOY["volumes"])

    def test_a_half_written_restore_is_never_redeployed(self, docker):
        """After a worker restart _restoring is empty; the helper is the only mark, and a deploy keeps the volume."""
        container = self._service(docker, helper=True)
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish") as caught:
            self._deploy(docker)
        assert caught.value.status_code == 409
        docker.images.pull.assert_not_called()
        assert docker.container_map["cashpilot-mysterium"] is container and docker.started == []

    def test_a_service_with_no_leftover_gets_past_the_guard(self, docker):
        self._service(docker)
        with pytest.raises(orchestrator.ContainerRuntimeError, match="not available"):
            self._deploy(docker)
        docker.images.pull.assert_called_once()

    def test_remove_without_data_keeps_the_helper_and_the_refusal(self, docker):
        """The helper marks the half-written volume; removing it alone would let the next deploy start on it."""
        container = self._service(docker, helper=True)
        with pytest.raises(orchestrator.ContainerRuntimeError, match="with its data") as caught:
            orchestrator.remove_service("mysterium", delete_volumes=False)
        assert caught.value.status_code == 409
        assert docker.container_map["cashpilot-mysterium"] is container
        assert "cashpilot-mysterium.restore" in docker.container_map and "mysterium-data" in docker.volume_map
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish"):
            orchestrator.start_service("mysterium")

    def test_the_worker_answers_remove_without_data_with_a_code(self, docker, worker):
        """The dashboard's Remove reads the code to offer deleting the half-written data."""
        self._service(docker, helper=True)
        headers = {"Authorization": f"Bearer {WORKER_KEY}"}
        resp = worker.client.delete("/api/containers/mysterium", headers=headers)
        detail = resp.json()["detail"]
        assert resp.status_code == 409 and detail["error"] == "restore_unfinished"
        assert "partial restore" in detail["message"]
        # The critical-volume rule still holds for that data.
        resp = worker.client.delete("/api/containers/mysterium?delete_volumes=true", headers=headers)
        assert resp.status_code == 409 and resp.json()["detail"]["error"] == "critical_volume"
        assert "cashpilot-mysterium.restore" in docker.container_map and "mysterium-data" in docker.volume_map

    def test_remove_without_data_of_a_service_with_no_leftover_goes(self, docker):
        self._service(docker)
        orchestrator.remove_service("mysterium", delete_volumes=False)
        assert docker.container_map == {} and "mysterium-data" in docker.volume_map

    def test_no_remove_while_the_restore_writes(self, docker):
        seen: list[Exception] = []
        real_put = FakeContainer.put_archive

        def put(self, path, data):
            try:
                _owner_removes("mysterium")
            except orchestrator.ContainerRuntimeError as exc:
                seen.append(exc)
            return real_put(self, path, data)

        with patch.object(FakeContainer, "put_archive", put):
            result = orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert result["started"] is True and "mysterium-data" in docker.volume_map
        assert len(seen) == 1 and seen[0].status_code == 409

    def test_no_export_while_the_restore_writes(self, docker):
        seen: list[Exception] = []
        real_put = FakeContainer.put_archive

        def put(self, path, data):
            try:
                orchestrator.read_critical_state("mysterium")
            except orchestrator.ContainerRuntimeError as exc:
                seen.append(exc)
            return real_put(self, path, data)

        with patch.object(FakeContainer, "put_archive", put):
            result = orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert result["started"] is True
        assert len(seen) == 1 and seen[0].status_code == 409 and "restore of mysterium is running" in str(seen[0])

    def test_a_half_written_restore_is_never_exported(self, docker):
        """A file of half the data would read back as itself, so a restore of it would pass as good."""
        self._service(docker, helper=True)
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish") as caught:
            orchestrator.read_critical_state("mysterium")
        assert caught.value.status_code == 409

    def test_the_worker_answers_an_export_refusal_as_409(self, worker):
        refusal = orchestrator.ContainerRuntimeError("A restore of mysterium did not finish", 409)
        with patch.object(orchestrator, "read_critical_state", side_effect=refusal):
            resp = worker.client.post(
                "/api/containers/mysterium/backup",
                json={"passphrase": PASSPHRASE},
                headers={"Authorization": f"Bearer {WORKER_KEY}"},
            )
        assert resp.status_code == 409 and "did not finish" in resp.text

    def test_the_worker_answers_a_refusal_as_409(self, worker):
        with patch.object(
            orchestrator, "start_service", side_effect=orchestrator.ContainerRuntimeError("did not finish", 409)
        ):
            resp = worker.client.post(
                "/api/containers/mysterium/start", headers={"Authorization": f"Bearer {WORKER_KEY}"}
            )
        assert resp.status_code == 409 and "did not finish" in resp.text


class TestABoxWithOnlyAPartialRestore:
    """An undo (it keeps every volume it made) or a Remove whose volume delete failed leaves the helper and the volume.

    The box lists no container of the service, so the heartbeat names the slug
    and the dashboard draws that box's Remove from this box from it.
    """

    def _leftover(self, docker):
        docker.corrupt_put = True
        with (
            patch.object(FakeVolume, "remove", side_effect=requests.exceptions.ReadTimeout("proxy timed out")),
            pytest.raises(orchestrator.RestoreError),
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert "cashpilot-mysterium" not in docker.container_map and "mysterium-data" in docker.volume_map
        docker.corrupt_put = False

    def test_the_worker_names_the_service(self, docker):
        self._leftover(docker)
        assert orchestrator.unfinished_restores() == ["mysterium"]

    def test_nothing_is_named_without_a_leftover(self, docker):
        TestStartAndRemoveAroundARestore()._service(docker)
        assert orchestrator.unfinished_restores() == []

    def test_a_restore_that_runs_now_is_not_named(self, docker):
        seen: list[list[str]] = []
        real_put = FakeContainer.put_archive

        def put(self, path, data):
            seen.append(orchestrator.unfinished_restores())
            return real_put(self, path, data)

        with patch.object(FakeContainer, "put_archive", put):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert seen == [[]]

    def test_the_heartbeat_carries_it(self, docker):
        self._leftover(docker)
        sent: dict = {}

        class Resp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"status": "ok"}

        class Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, json=None, headers=None):
                sent.update(json)
                return Resp()

        with (
            patch.object(worker_api.orchestrator, "get_status", return_value=[]),
            patch.object(worker_api.orchestrator, "docker_available", return_value=True),
            patch.object(worker_api, "_detect_egress_ip", new_callable=AsyncMock, return_value=None),
            patch.object(worker_api, "_check_fence", new_callable=AsyncMock),
            patch.object(worker_api, "_disk_usage", return_value=None),
            patch.object(worker_api, "_gpu_info", return_value={}),
            patch.object(worker_api.proxy_tunnel, "status", return_value=[]),
            patch.object(worker_api.httpx, "AsyncClient", Client),
            patch.object(worker_api, "UI_URL", "http://ui:8080"),
        ):
            asyncio.run(worker_api._send_heartbeat())
        assert sent["containers"] == [] and sent["system_info"]["restore_unfinished"] == ["mysterium"]

    def test_its_remove_from_this_box_clears_it(self, docker, worker):
        """What the row's Remove sends: the plain remove is refused with the code, the owner's delete goes."""
        # The state _leftover makes (the worker fixture stands in for restore_state).
        TestStartAndRemoveAroundARestore()._service(docker, helper=True)
        del docker.container_map["cashpilot-mysterium"]
        headers = {"Authorization": f"Bearer {WORKER_KEY}"}
        resp = worker.client.delete("/api/containers/mysterium", headers=headers)
        assert resp.status_code == 409 and resp.json()["detail"]["error"] == "restore_unfinished"
        # The owner's yes to the partial restore: the box first names what it finds critical.
        retry = "/api/containers/mysterium?delete_volumes=true&only_if_restore_unfinished=true"
        resp = worker.client.delete(retry, headers=headers)
        assert resp.status_code == 409 and resp.json()["detail"]["error"] == "critical_volume"
        reviewed = resp.json()["detail"]["critical_set"]
        assert reviewed.startswith("mysterium-data@2026-")
        resp = worker.client.delete(
            f"{retry}&allow_delete_critical=true&critical_set={urllib.parse.quote(reviewed, safe='')}",
            headers={**headers, **_bound_delete_approval(reviewed)},
        )
        assert resp.status_code == 200, resp.text
        assert docker.container_map == {} and docker.volume_map == {}
        assert orchestrator.unfinished_restores() == []


class TestTheDeleteOfAPartialRestoreIsTiedToIt:
    """The owner agreed to delete a partial restore. A restore that succeeded since is not that, and stays."""

    def test_a_restore_that_succeeded_meanwhile_is_not_deleted(self, docker):
        TestStartAndRemoveAroundARestore()._service(docker)  # the box runs a verified node now, no helper
        with pytest.raises(orchestrator.RestoreClearedError) as caught:
            _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert caught.value.status_code == 409
        assert "cashpilot-mysterium" in docker.container_map and "mysterium-data" in docker.volume_map
        assert docker.removed == []

    def test_the_partial_restore_itself_is_deleted(self, docker):
        TestStartAndRemoveAroundARestore()._service(docker, helper=True)
        result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert result["deleted_volumes"] == ["mysterium-data"]
        assert docker.container_map == {} and docker.volume_map == {}

    def test_the_worker_answers_it_with_a_code(self, docker, worker):
        TestStartAndRemoveAroundARestore()._service(docker)
        resp = worker.client.delete(
            "/api/containers/mysterium?delete_volumes=true&allow_delete_critical=true&only_if_restore_unfinished=true",
            headers={"Authorization": f"Bearer {WORKER_KEY}", **_delete_approval()},
        )
        detail = resp.json()["detail"]
        assert resp.status_code == 409 and detail["error"] == "restore_cleared"
        assert "nothing was removed" in detail["message"]
        assert "mysterium-data" in docker.volume_map

    def test_the_ui_sends_the_condition_and_forwards_the_refusal(self, ui):
        cleared = {
            "detail": {"error": "restore_cleared", "message": "No restore of mysterium ... nothing was removed."}
        }
        resp, sent = TestRemoveAfterARestoreThatDidNotFinish()._remove(
            ui, "&delete_volumes=true&allow_delete_critical=true&only_if_restore_unfinished=true", 409, cleared
        )
        assert sent.call_args.kwargs["params"] == {
            "delete_volumes": "true",
            "allow_delete_critical": "true",
            "only_if_restore_unfinished": "true",
        }
        assert resp.status_code == 409
        assert resp.json()["detail"]["error"] == "restore_cleared"
        assert "nothing was removed" in resp.json()["detail"]["message"]
        assert ("delete_critical_volumes", "deleted") not in _audit()


# ---------------------------------------------------------------------------
# The restore on main's identity ledger (#753): the deploy's holds and Forget
# ---------------------------------------------------------------------------


class TestARestoreOnTheIdentityLedger:
    """A restore sends a deploy spec, so its device ids are held as a deploy's are."""

    HELD = ("u1", {"DEVICE_ID": "dev-1"})

    def _restore_with(self, ui, side_effect=None, answer=None):
        upload = _upload(ui, mysterium_bundle()).json()
        release = AsyncMock()
        patches = [
            patch.object(main, "_reserve_pending_identities", AsyncMock(return_value=self.HELD)),
            patch.object(main, "_release_pending_identities", release),
        ]
        if answer is not None:
            patches += [
                patch.object(main, "_proxy_to_worker", REAL_PROXY),
                patch.object(main, "_get_verified_worker_url", AsyncMock(return_value=("https://a", {}))),
                patch("httpx.AsyncClient.post", AsyncMock(return_value=answer)),
            ]
        else:
            patches.append(patch.object(main, "_proxy_to_worker", AsyncMock(side_effect=side_effect)))
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            resp = _restore(ui, upload["upload_id"], confirm_name="Mysterium", step_up_password=OWNER_PASSWORD)
        return resp, release

    def test_a_refusal_ends_the_hold(self, ui):
        from fastapi import HTTPException

        resp, release = self._restore_with(ui, HTTPException(409, "volume exists"))
        assert resp.status_code == 409
        release.assert_awaited_once_with("mysterium", 1, self.HELD)

    def test_no_answer_keeps_the_hold(self, ui):
        resp, release = self._restore_with(ui, main._WorkerNoAnswer(504, "no answer"))
        assert resp.status_code == 504
        release.assert_not_awaited()

    def test_the_workers_own_undo_behind_a_gateway_status_ends_it(self, ui):
        """A 504 the worker marks "restored": false is its answer; _outcome_unknown alone would keep the hold."""
        request = httpx.Request("POST", "https://a/api/containers/mysterium/restore")
        answer = httpx.Response(504, request=request, json={"detail": "Undone.", "restored": False})
        resp, release = self._restore_with(ui, answer=answer)
        assert resp.status_code == 504
        release.assert_awaited_once_with("mysterium", 1, self.HELD)

    def test_a_backup_row_offers_forget(self, ui):
        """The view's forgettable matches what delete_identity accepts for a backup row."""
        row_id = asyncio.run(database.record_backup("mysterium", 1, "b" * 64, "export"))
        view = next(r for r in ui.get("/api/identities").json() if r["id"] == row_id)
        assert view["kind"] == "backup" and view["forgettable"] is True
        assert asyncio.run(database.delete_identity(row_id)) is True


def test_the_backup_file_selector_has_a_label():
    """A screen reader names the file input by its label, not by the paragraph above it."""
    html = english_source("app/templates/settings.html")
    assert re.search(r'<label[^>]*\bfor="restore-file"[^>]*>\s*Backup file\s*</label>', html)


class TestARestoreRefusedBeforeItStarts:
    """A Docker that cannot be reached or asked creates nothing: a plain refusal, never an opaque 500."""

    def test_no_docker_is_a_503_that_restored_nothing(self, docker):
        no_docker = RuntimeError("connect to /internal/run/sock-7f3a refused")
        with (
            patch.object(orchestrator, "_get_client", side_effect=no_docker),
            patch.object(orchestrator, "proxied", return_value=True),
            pytest.raises(orchestrator.RestoreError) as caught,
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert caught.value.status_code == 503 and not caught.value.left
        assert "Nothing was restored" in caught.value.detail and "socket proxy" in caught.value.detail
        # The exception's own text goes to the log, never to the owner.
        assert "sock-7f3a" not in caught.value.detail
        assert docker.container_map == {} and docker.volume_map == {}

    def test_a_refused_check_restored_nothing(self, docker):
        response = requests.Response()
        response.status_code = 403
        with (
            patch.object(docker.containers, "list", side_effect=APIError("forbidden", response=response)),
            pytest.raises(orchestrator.RestoreError) as caught,
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert caught.value.status_code == 409 and not caught.value.left
        assert "Nothing was restored" in str(caught.value)
        assert docker.container_map == {} and docker.volume_map == {}

    def test_the_worker_answers_it_as_its_own(self, worker, monkeypatch):
        monkeypatch.setattr(worker_api.orchestrator, "restore_state", REAL_RESTORE_STATE)
        monkeypatch.setattr(worker_api.orchestrator, "_get_client", MagicMock(side_effect=RuntimeError("no docker")))
        resp = worker("proxybase-xyz", proxybase_bundle())
        assert resp.status_code == 503 and resp.json()["restored"] is False


# ---------------------------------------------------------------------------
# What the owner reads of a failed restore: fixed text and names, never
# Docker's own answer or another exception's text (CodeQL stack-trace-exposure)
# ---------------------------------------------------------------------------

#: Stands for a path, a host or a daemon message inside Docker's answer.
INTERNAL = "/var/lib/docker/overlay2/7f3a-internal"


def _docker_error(status: int, *, body: dict | None = None) -> APIError:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = body if body is not None else {"message": INTERNAL}
    return APIError(f"server said {INTERNAL}", response=response, explanation=INTERNAL)


def _sockguard_refusal() -> APIError:
    return _docker_error(403, body={"message": "request denied by sockguard policy", "reason": "archive path denied"})


class TestARestoreAnswerHoldsNoDockerText:
    def test_dockers_answer_to_a_write_stays_in_the_log(self, docker, caplog):
        with (
            caplog.at_level(logging.WARNING, logger="app.orchestrator"),
            patch.object(FakeContainer, "put_archive", side_effect=_docker_error(500)),
            pytest.raises(orchestrator.RestoreError) as caught,
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert "Docker refused the restore, so it was undone." in caught.value.detail
        assert "log has Docker's answer" in caught.value.detail
        assert INTERNAL not in caught.value.detail and INTERNAL not in str(caught.value)
        assert INTERNAL in caplog.text

    def test_the_proxys_allowlisted_reason_still_reaches_the_owner(self, docker):
        with (
            patch.object(FakeContainer, "put_archive", side_effect=_sockguard_refusal()),
            pytest.raises(orchestrator.RestoreError) as caught,
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert "The Docker socket proxy refused this: archive path denied." in caught.value.detail

    def test_a_create_refusal_names_the_container_not_dockers_text(self, docker, caplog):
        def refused(**_kw):
            raise orchestrator.ContainerRuntimeError(f"Docker refused the container: {INTERNAL}", 409)

        orchestrator.deploy_raw.__wrapped__ = refused
        with (
            caplog.at_level(logging.WARNING, logger="app.orchestrator"),
            pytest.raises(orchestrator.RestoreError) as caught,
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert caught.value.status_code == 409
        assert "Docker could not create cashpilot-mysterium" in caught.value.detail
        assert INTERNAL not in caught.value.detail and INTERNAL in caplog.text

    def test_a_create_the_proxy_refused_says_the_proxys_reason(self, docker):
        def refused(**_kw):
            cause = _sockguard_refusal()
            raise orchestrator.ContainerRuntimeError(f"wrapped {INTERNAL}", 403) from cause

        orchestrator.deploy_raw.__wrapped__ = refused
        with pytest.raises(orchestrator.RestoreError) as caught:
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert caught.value.status_code == 403 and "archive path denied" in caught.value.detail
        assert INTERNAL not in caught.value.detail

    def test_a_leftover_helper_docker_would_not_remove(self, docker, caplog):
        stale = FakeContainer(docker, "cashpilot-mysterium.restore", {}, {orchestrator.LABEL_RESTORE: "helper"})
        docker.container_map[stale.name] = stale
        with (
            caplog.at_level(logging.WARNING, logger="app.orchestrator"),
            patch.object(stale, "remove", side_effect=RuntimeError(INTERNAL)),
            pytest.raises(orchestrator.RestoreError) as caught,
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert "cashpilot-mysterium.restore, left by a restore that did not finish, could not be removed" in (
            caught.value.detail
        )
        assert ".." not in caught.value.detail
        assert INTERNAL not in caught.value.detail and INTERNAL in caplog.text

    def test_a_volume_docker_would_not_show(self, docker):
        with (
            patch.object(docker.volumes, "get", side_effect=_docker_error(500)),
            pytest.raises(orchestrator.RestoreError) as caught,
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert "the volume mysterium-data could not be checked" in caught.value.detail
        assert INTERNAL not in caught.value.detail

    def test_a_listing_docker_refused(self, docker):
        with (
            patch.object(docker.containers, "list", side_effect=_docker_error(500)),
            pytest.raises(orchestrator.RestoreError) as caught,
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert "Docker refused to show what is on this box" in caught.value.detail
        assert INTERNAL not in caught.value.detail

    def test_the_worker_answers_with_the_fixed_text(self, worker, monkeypatch):
        fake = FakeDocker()
        monkeypatch.setattr(worker_api.orchestrator, "restore_state", REAL_RESTORE_STATE)
        monkeypatch.setattr(worker_api.orchestrator, "_get_client", lambda: fake)
        monkeypatch.setattr(fake.containers, "list", MagicMock(side_effect=_docker_error(500)))
        resp = worker("proxybase-xyz", proxybase_bundle())
        assert resp.status_code == 409 and resp.json()["restored"] is False
        assert "Docker refused to show what is on this box" in resp.json()["detail"]
        assert INTERNAL not in resp.text


# ---------------------------------------------------------------------------
# The half-written mark lasts until the data is checked, and a removal never
# deletes a restore that started after its check
# ---------------------------------------------------------------------------


class TestTheHelperMarksTheVolumeUntilItIsChecked:
    def test_the_helper_holds_the_volume_through_the_read_back(self, docker):
        seen = []
        real_read = orchestrator._read_back

        def read_back(container, target):
            # A worker that dies here leaves this helper: the volume stays marked.
            helper = orchestrator._restore_helper("mysterium")
            seen.append(helper and helper.mounts)
            return real_read(container, target)

        with patch.object(orchestrator, "_read_back", read_back):
            result = orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert seen == [{WRITE_MOUNT: "mysterium-data"}]
        assert result["started"] is True and set(docker.container_map) == {"cashpilot-mysterium"}

    def test_the_helper_goes_right_before_the_start(self, docker):
        at_start = []
        real_start = orchestrator._start_restored

        def start(slug, container):
            at_start.append(orchestrator._restore_helper(slug))
            return real_start(slug, container)

        with patch.object(orchestrator, "_start_restored", start):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert at_start == [None]

    def test_a_failed_read_back_still_undoes_everything_but_the_volume(self, docker):
        docker.corrupt_put = True
        with pytest.raises(orchestrator.RestoreError, match="does not read back as the backup"):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert "cashpilot-mysterium" not in docker.container_map and docker.started == []
        # The written volume keeps its helper, the mark of a half-written volume.
        assert orchestrator._restore_helper("mysterium") is not None
        _assert_kept_and_held(docker, "mysterium-data")

    def test_every_volume_of_a_restore_stays_held_by_the_one_helper(self, docker):
        """Two volumes: the restore's helper holds both from before the first write; the second writer goes."""
        nonces = {"vol-a": "aa" * 16, "vol-b": "bb" * 16}
        for volume, nonce in nonces.items():
            docker.volumes.create(volume, labels={orchestrator.LABEL_RESTORE: nonce})
        service = FakeContainer(docker, "cashpilot-two", {}, {orchestrator.LABEL_SERVICE: "two"})
        docker.container_map[service.name] = service
        made: list[Any] = [service]
        written: list[str] = []
        payload = state_backup.relative_archive(_archives()["mysterium-node"], orchestrator.RESTORE_ROOT)
        mark = orchestrator._write_through_helper(
            docker, service, [("vol-a", payload), ("vol-b", payload)], made, written, nonces
        )
        assert mark.name == "cashpilot-two.restore" and made == [service, mark] and written == ["vol-a", "vol-b"]
        assert set(mark.mounts.values()) == {"vol-a", "vol-b"}
        assert mark.mounts[WRITE_MOUNT] == "vol-a"
        assert docker.puts == [
            ("cashpilot-two.restore", orchestrator.RESTORE_WRITE_DIR),
            ("cashpilot-two.restore-1", orchestrator.RESTORE_WRITE_DIR),
        ]
        assert set(docker.container_map) == {"cashpilot-two", "cashpilot-two.restore"}


class TestARemovalHoldsItsServiceAgainstARestore:
    def test_a_restore_that_starts_during_a_removal_is_refused(self, docker):
        outcome: dict[str, str] = {}
        real_helper = orchestrator._restore_helper

        def racing(slug):
            # The removal has passed its "no restore runs" check: a restore starts now.
            try:
                orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
                outcome["restore"] = "ran"
            except orchestrator.RestoreError as exc:
                outcome["restore"] = exc.detail
            return real_helper(slug)

        with patch.object(orchestrator, "_restore_helper", racing), pytest.raises(ValueError):
            _owner_removes("mysterium")
        assert "a removal of mysterium is running on this box" in outcome["restore"]
        assert docker.creates == [] and docker.volume_map == {} and docker.started == []
        assert orchestrator._removing == {}

    def test_the_hold_ends_with_the_removal(self, docker):
        with pytest.raises(ValueError):
            _owner_removes("mysterium")
        assert orchestrator._removing == {}
        assert orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)["started"] is True


# ---------------------------------------------------------------------------
# Plain HTTP: the owner's answer is checked against the URL the passphrase goes to
# ---------------------------------------------------------------------------


class TestPlainHttpIsCheckedWhereThePassphraseIsSent:
    @staticmethod
    def _dispatch(ui, sent_to: list[str]):
        def client(*_a, **_kw):
            raise AssertionError("the request must not be sent")

        async def verified(worker):
            sent_to.append(worker["url"])
            return worker["url"], {}

        return (
            patch.object(main, "_proxy_to_worker", REAL_PROXY),
            patch.object(main, "_get_verified_worker_url", side_effect=verified),
            patch.object(main.httpx, "AsyncClient", side_effect=client),
        )

    def test_a_worker_that_turned_to_http_after_the_check_gets_nothing(self, ui):
        upload = _upload(ui, mysterium_bundle()).json()
        sent_to: list[str] = []

        async def step_up_then_the_url_changes(*_a, **_kw):
            # A heartbeat rewrites box-a's address while the owner types the password.
            ui.workers[0]["url"] = "http://a"

        with ExitStack() as stack:
            for p in self._dispatch(ui, sent_to):
                stack.enter_context(p)
            stack.enter_context(patch.object(main, "require_step_up", side_effect=step_up_then_the_url_changes))
            resp = _restore(ui, upload["upload_id"], worker_id=1, confirm_name="Mysterium", step_up_password="x")
        assert resp.status_code == 400 and resp.json()["detail"]["error"] == "restore_plain_http"
        assert "Nothing was sent" in resp.json()["detail"]["message"]
        assert sent_to == ["http://a"]
        # Refused before it was sent: the ledger row of this try is settled as not applied.
        assert [r["source"] for r in asyncio.run(database.backup_records(upload["sha256"]))] == []

    def test_the_owners_yes_lets_it_go_to_that_url(self):
        async def verified(worker):
            return worker["url"], {}

        async def run(allow):
            with (
                patch.object(main.database, "get_worker", AsyncMock(return_value={"name": "box-b", "url": "http://b"})),
                patch.object(main, "_get_verified_worker_url", side_effect=verified),
                patch.object(main.httpx, "AsyncClient", side_effect=ConnectionAbortedError("sent")),
            ):
                return await REAL_PROXY(2, "POST", "/api/containers/x/restore", json={}, allow_plain_http=allow)

        with pytest.raises(ConnectionAbortedError):
            asyncio.run(run(True))
        with pytest.raises(HTTPException) as caught:
            asyncio.run(run(False))
        assert caught.value.status_code == 400 and caught.value.detail["error"] == "restore_plain_http"


# ---------------------------------------------------------------------------
# An uploaded file that is left goes without a request to trigger it
# ---------------------------------------------------------------------------


class TestALeftUploadGoesWithoutARequest:
    def test_the_start_deletes_uploads_from_before_it_and_schedules_the_sweep(self, tmp_path):
        from tests.test_rates_do_not_hold_startup import _lifespan_patches

        folder = tmp_path / "restore-uploads"
        folder.mkdir()
        (folder / "from-before-the-restart").write_bytes(b"sealed")

        async def noop():
            return None

        async def run():
            patches = (*_lifespan_patches(noop, noop), patch.object(database, "DB_DIR", tmp_path))
            for p in patches:
                p.start()
            try:
                async with main.lifespan(main.app):
                    assert os.listdir(folder) == []
                    job = main.scheduler.get_job("restore_sweep")
                    assert job.func is main._run_restore_sweep
                    assert job.trigger.interval == timedelta(minutes=5)
            finally:
                for p in reversed(patches):
                    p.stop()

        asyncio.run(run())

    def test_the_scheduled_sweep_deletes_an_expired_upload_and_keeps_a_fresh_one(self, tmp_path):
        folder = tmp_path / "restore-uploads"
        folder.mkdir()
        now = datetime.now(UTC).timestamp()
        entries = {"old": now - main.RESTORE_UPLOAD_TTL - 1, "new": now}
        try:
            with patch.object(database, "DB_DIR", tmp_path):
                for upload_id, created in entries.items():
                    (folder / upload_id).write_bytes(b"sealed")
                    main._restore_uploads[upload_id] = {
                        "id": upload_id,
                        "path": str(folder / upload_id),
                        "sha256": upload_id,
                        "created": created,
                    }
                asyncio.run(main._run_restore_sweep())
            assert os.listdir(folder) == ["new"] and set(main._restore_uploads) == {"new"}
        finally:
            main._restore_uploads.clear()


# ---------------------------------------------------------------------------
# Round 9: what holds a slug, and what survives a worker that died
# ---------------------------------------------------------------------------


class TestAServiceNotFenceGatedStaysHeldAfterACrash:
    """ProxyBase and Anyone have no failed mark of their own: the restore's record on disk holds them."""

    def _died_after_the_create(self, docker):
        """The worker is killed after the service container exists and before any helper.

        A killed worker runs no undo: Docker keeps what it made, and the disk
        keeps what it held at that instant, which is put back after the call.
        """
        marker = Path(orchestrator.RESTORE_MARKER)
        disk: dict[str, bytes | None] = {}

        def die(*_a, **_kw):
            disk["at_death"] = marker.read_bytes() if marker.exists() else None
            raise SystemExit("worker killed")

        with (
            patch.object(orchestrator, "_write_through_helper", die),
            patch.object(orchestrator, "_restore_cleanup", lambda *a, **k: ([], [], [])),
            pytest.raises(SystemExit),
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        if disk["at_death"] is None:
            marker.unlink(missing_ok=True)
        else:
            marker.write_bytes(disk["at_death"])
        assert (
            "cashpilot-mysterium" in docker.container_map and "cashpilot-mysterium.restore" not in docker.container_map
        )
        # A worker restart empties what the process held; only the disk is left.
        orchestrator._RESTORE_MARK_UNWRITTEN.clear()
        assert orchestrator._restoring == set()

    @pytest.mark.parametrize("command", ["start_service", "restart_service", "read_critical_state"])
    def test_a_crash_before_the_helper_never_starts_or_reads_it(self, docker, command):
        self._died_after_the_create(docker)
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish") as caught:
            getattr(orchestrator, command)("mysterium")
        assert caught.value.status_code == 409 and docker.started == []

    def test_a_crash_before_the_helper_is_never_redeployed(self, docker):
        self._died_after_the_create(docker)
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish"):
            TestStartAndRemoveAroundARestore()._deploy(docker)
        assert orchestrator.unfinished_restores() == ["mysterium"]

    def test_its_remove_with_data_ends_the_hold(self, docker):
        self._died_after_the_create(docker)
        result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert result["deleted_volumes"] == ["mysterium-data"] and result["failed_volumes"] == []
        assert docker.container_map == {} and docker.volume_map == {}
        assert orchestrator.unfinished_restores() == []
        with pytest.raises(orchestrator.ContainerRuntimeError, match="not available"):
            TestStartAndRemoveAroundARestore()._deploy(docker)

    def test_a_restore_that_finished_leaves_no_hold(self, docker):
        """The control: a restore that read back right holds nothing once it ends."""
        orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert orchestrator.unfinished_restores() == []
        orchestrator._refuse_mid_restore("mysterium", "started")

    def test_a_record_that_cannot_be_written_makes_nothing(self, docker, monkeypatch):
        _marker_io(monkeypatch, orchestrator.RESTORE_MARKER + ".tmp", PermissionError(13, "Permission denied"))
        with pytest.raises(orchestrator.RestoreError, match="could not record"):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert docker.creates == [] and docker.volume_map == {} and docker.container_map == {}

    def test_a_record_whose_volume_is_there_refuses_the_next_restore(self, docker):
        self._died_after_the_create(docker)
        del docker.container_map["cashpilot-mysterium"]
        with pytest.raises(orchestrator.RestoreError, match="did not finish"):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert orchestrator.unfinished_restores() == ["mysterium"]


class TestAHoldThatOutlivesALostHelper:
    """The helper had to go before the volume; when the volume stays and the helper cannot come back."""

    def test_a_remove_whose_volume_and_helper_both_fail_still_holds_it(self, docker):
        TestStartAndRemoveAroundARestore()._service(docker, helper=True)
        with (
            patch.object(FakeVolume, "remove", side_effect=requests.exceptions.ReadTimeout("proxy timed out")),
            patch.object(orchestrator, "_create_restore_helper", side_effect=RuntimeError("daemon gone")),
        ):
            result = _owner_removes("mysterium")
        assert result["failed_volumes"] == ["mysterium-data"] and docker.container_map == {}
        assert orchestrator._restore_helper("mysterium") is None
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish"):
            TestStartAndRemoveAroundARestore()._deploy(docker)
        assert orchestrator.unfinished_restores() == ["mysterium"]

    def test_an_undo_whose_volume_and_helper_both_fail_still_holds_it(self, docker):
        docker.corrupt_put = True
        real = orchestrator._create_restore_helper
        calls: list[str] = []

        def helper(client, image, name, volumes):
            calls.append(name)
            if len(calls) > 1:
                raise RuntimeError("daemon gone")
            return real(client, image, name, volumes)

        with (
            patch.object(orchestrator, "_create_restore_helper", helper),
            pytest.raises(orchestrator.RestoreError, match="stays held"),
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert len(calls) == 2 and docker.container_map == {} and "mysterium-data" in docker.volume_map
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish"):
            TestStartAndRemoveAroundARestore()._deploy(docker)
        assert orchestrator.unfinished_restores() == ["mysterium"]


class TestStartRestartAndExportHoldTheirService:
    """Each holds its slug from its check to its last Docker action, so no restore starts in between."""

    @pytest.mark.parametrize("command", ["start_service", "restart_service", "read_critical_state"])
    def test_a_restore_that_starts_between_the_check_and_the_container_is_refused(self, docker, command):
        outcome: dict[str, str] = {}
        real_find = orchestrator._find_container

        def racing(slug, *args, **kwargs):
            try:
                orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
                outcome["restore"] = "ran"
            except orchestrator.RestoreError as exc:
                outcome["restore"] = exc.detail
            return real_find(slug, *args, **kwargs)

        with patch.object(orchestrator, "_find_container", racing), pytest.raises(ValueError):
            getattr(orchestrator, command)("mysterium")
        assert "is running on this box" in outcome["restore"] and outcome["restore"].startswith("Nothing was restored")
        assert docker.creates == [] and docker.volume_map == {} and docker.started == []

    def test_the_hold_ends_with_the_command(self, docker):
        with pytest.raises(ValueError):
            orchestrator.start_service("mysterium")
        assert orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)["started"] is True


class TestADeployDuringARemoval:
    def test_a_deploy_that_starts_during_a_removal_is_refused(self, docker):
        TestStartAndRemoveAroundARestore()._service(docker)
        seen: list[Exception] = []
        real_remove = FakeContainer.remove

        def remove(container, force=False):
            try:
                TestStartAndRemoveAroundARestore()._deploy(docker)
            except orchestrator.ContainerRuntimeError as exc:
                seen.append(exc)
            return real_remove(container, force)

        with patch.object(FakeContainer, "remove", remove):
            _owner_removes("mysterium")
        assert len(seen) == 1 and seen[0].status_code == 409, seen
        assert "removal of mysterium is running" in str(seen[0])
        docker.images.pull.assert_not_called()

    def test_control_a_deploy_after_the_removal_goes_on(self, docker):
        TestStartAndRemoveAroundARestore()._service(docker)
        _owner_removes("mysterium")
        with pytest.raises(orchestrator.ContainerRuntimeError, match="not available"):
            TestStartAndRemoveAroundARestore()._deploy(docker)


class TestARemovalDuringADeployOrAStart:
    """A removal with its data, during a deploy's pull, would leave the deploy a new empty identity volume."""

    @staticmethod
    def _remove(seen: list[Exception]) -> None:
        try:
            _owner_removes("mysterium")
        except orchestrator.ContainerRuntimeError as exc:
            seen.append(exc)

    def test_a_removal_during_a_deploy_is_refused_and_touches_nothing(self, docker):
        container = TestStartAndRemoveAroundARestore()._service(docker)
        seen: list[Exception] = []
        docker.images = MagicMock()
        docker.images.get.side_effect = orchestrator.DockerException("no such image")

        def pull(*_a, **_kw):
            # The deploy holds the slug through its pull: a removal now must not delete its volume.
            self._remove(seen)
            return DEFAULT

        docker.images.pull.side_effect = pull
        with pytest.raises(orchestrator.ContainerRuntimeError, match="not available"):
            REAL_DEPLOY_RAW(slug="mysterium", image=MYSTERIUM_DEPLOY["image"], volumes=MYSTERIUM_DEPLOY["volumes"])
        assert len(seen) == 1 and seen[0].status_code == 409, seen
        assert "deploy of mysterium is running" in str(seen[0]) and "nothing was removed" in str(seen[0])
        assert docker.container_map["cashpilot-mysterium"] is container
        assert "mysterium-data" in docker.volume_map
        assert orchestrator._removing == {}

    def test_a_removal_during_a_start_is_refused_and_touches_nothing(self, docker):
        container = TestStartAndRemoveAroundARestore()._service(docker)
        seen: list[Exception] = []
        real_find = orchestrator._find_container

        raced: list[bool] = []

        def racing(slug, *args, **kwargs):
            if not raced:
                # Once, as the start reaches its container: the removal runs now.
                raced.append(True)
                self._remove(seen)
            return real_find(slug, *args, **kwargs)

        with patch.object(orchestrator, "_find_container", racing):
            orchestrator.start_service("mysterium")
        assert len(seen) == 1 and seen[0].status_code == 409, seen
        assert "start, restart or backup of mysterium is running" in str(seen[0])
        assert docker.container_map["cashpilot-mysterium"] is container
        assert "mysterium-data" in docker.volume_map
        assert orchestrator._removing == {}

    def test_control_with_no_holder_the_removal_goes_on(self, docker):
        TestStartAndRemoveAroundARestore()._service(docker)
        _owner_removes("mysterium")
        assert "cashpilot-mysterium" not in docker.container_map
        assert "mysterium-data" not in docker.volume_map


class TestUploadsStillArrivingCountAgainstTheLimit:
    def test_files_still_streaming_in_take_their_slots(self, ui, monkeypatch):
        monkeypatch.setattr(
            main, "_restore_receiving", {f"/nowhere/{n}" for n in range(main.RESTORE_UPLOAD_MAX_PENDING)}
        )
        resp = _upload(ui, mysterium_bundle())
        assert resp.status_code == 429 and _uploads_on_disk(ui) == []

    def test_one_slot_short_still_takes_the_file(self, ui, monkeypatch):
        monkeypatch.setattr(
            main, "_restore_receiving", {f"/nowhere/{n}" for n in range(main.RESTORE_UPLOAD_MAX_PENDING - 1)}
        )
        assert _upload(ui, mysterium_bundle()).status_code == 200

    def test_a_failed_upload_gives_its_slot_back(self, ui):
        for _ in range(main.RESTORE_UPLOAD_MAX_PENDING + 1):
            assert _upload(ui, b"junk").status_code == 400
        assert main._restore_receiving == set() and _upload(ui, mysterium_bundle()).status_code == 200


class TestAPendingRestoreRowIsForgottenOnlyWhenItCanNoLongerLand:
    """A 'pending' backup row is the hold of a restore whose outcome is not known; it ages like a deploy's hold."""

    @staticmethod
    def _age(row_id: int) -> None:
        import sqlite3

        with sqlite3.connect(database.DB_PATH) as conn:
            conn.execute(
                "UPDATE device_identities SET last_seen = datetime('now', ?) WHERE id = ?",
                (f"-{main.PENDING_IDENTITY_SECONDS + 60} seconds", row_id),
            )

    def test_a_fresh_pending_row_is_not_forgotten(self, ui):
        row_id = asyncio.run(database.record_backup("mysterium", 1, "c" * 64, "pending"))
        view = next(r for r in ui.get("/api/identities").json() if r["id"] == row_id)
        assert view["forgettable"] is False
        assert asyncio.run(database.delete_identity(row_id)) is False
        resp = ui.delete(f"/api/identities/{row_id}")
        assert resp.status_code == 409 and "may still finish" in _detail(resp) and "6 h" in _detail(resp)
        # The row is still there, so the worker's late answer can still settle it.
        asyncio.run(database.settle_backup(row_id, True))
        assert [r["source"] for r in asyncio.run(database.backup_records("c" * 64))] == ["restore"]

    def test_once_its_time_is_up_the_owner_may_forget_it(self, ui):
        row_id = asyncio.run(database.record_backup("mysterium", 1, "d" * 64, "pending"))
        self._age(row_id)
        view = next(r for r in ui.get("/api/identities").json() if r["id"] == row_id)
        assert view["forgettable"] is True
        assert ui.delete(f"/api/identities/{row_id}").status_code == 200
        assert asyncio.run(database.backup_records("d" * 64)) == []


class TestARecordThatCannotBeReadHoldsEverything:
    """A record on disk that cannot be read is not an empty one: it may hold a half-written volume."""

    def _unreadable(self, monkeypatch):
        Path(orchestrator.RESTORE_MARKER).write_text("mysterium mysterium-data\n", encoding="utf-8")
        _marker_io(monkeypatch, orchestrator.RESTORE_MARKER, PermissionError(13, "Permission denied"), "r")

    @pytest.mark.parametrize("command", ["start_service", "restart_service", "read_critical_state"])
    def test_start_restart_and_export_are_refused(self, docker, monkeypatch, command):
        TestStartAndRemoveAroundARestore()._service(docker)
        self._unreadable(monkeypatch)
        with pytest.raises(orchestrator.ContainerRuntimeError, match="could not read its record") as caught:
            getattr(orchestrator, command)("mysterium")
        assert caught.value.status_code == 503 and docker.started == []

    def test_a_deploy_is_refused(self, docker, monkeypatch):
        self._unreadable(monkeypatch)
        with pytest.raises(orchestrator.ContainerRuntimeError, match="could not read its record"):
            TestStartAndRemoveAroundARestore()._deploy(docker)

    def test_a_removal_is_refused_and_nothing_goes(self, docker, monkeypatch):
        TestStartAndRemoveAroundARestore()._service(docker)
        self._unreadable(monkeypatch)
        with pytest.raises(orchestrator.ContainerRuntimeError, match="nothing was removed"):
            _owner_removes("mysterium")
        assert "cashpilot-mysterium" in docker.container_map and "mysterium-data" in docker.volume_map

    def test_a_restore_is_refused_and_nothing_is_made(self, docker, monkeypatch):
        self._unreadable(monkeypatch)
        with pytest.raises(orchestrator.RestoreError, match="could not read its record"):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert docker.creates == [] and docker.volume_map == {}

    def test_another_slugs_mark_never_rewrites_the_file_from_a_failed_read(self, monkeypatch):
        self._unreadable(monkeypatch)
        assert orchestrator._mark_restore_unfinished("proxybase-xyz", True, ["proxybase-data"]) is False
        assert Path(orchestrator.RESTORE_MARKER).read_text(encoding="utf-8") == "mysterium mysterium-data\n"

    def test_a_failed_mark_never_rewrites_its_file_from_a_failed_read(self, tmp_path, monkeypatch):
        marker = tmp_path / "failed"
        marker.write_text("cashpilot-mysterium\n", encoding="utf-8")
        monkeypatch.setattr(orchestrator, "FAILED_MARKER", str(marker))
        monkeypatch.setattr(orchestrator, "_FAILED_UNWRITTEN", {})
        _marker_io(monkeypatch, str(marker), PermissionError(13, "Permission denied"), "r")
        orchestrator._mark_failed("cashpilot-other", True)
        assert marker.read_text(encoding="utf-8") == "cashpilot-mysterium\n"

    def test_control_a_missing_record_holds_nothing(self, docker):
        TestStartAndRemoveAroundARestore()._service(docker)
        orchestrator.start_service("mysterium")
        assert docker.started == ["cashpilot-mysterium"]


class TestTheRecordNamesTheVolumesItsRestoreWrote:
    def test_a_removal_deletes_them_when_the_catalog_no_longer_says(self, docker):
        TestAServiceNotFenceGatedStaysHeldAfterACrash()._died_after_the_create(docker)
        assert _record_names() == "mysterium mysterium-data\n"
        del docker.container_map["cashpilot-mysterium"]
        with patch.object(orchestrator, "restore_targets", return_value=None):
            result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert result["deleted_volumes"] == ["mysterium-data"] and docker.volume_map == {}
        assert orchestrator.restore_marks() == set()

    def test_a_record_that_names_no_volume_is_never_cleared_on_nothing(self, docker):
        Path(orchestrator.RESTORE_MARKER).write_text("mysterium\n", encoding="utf-8")
        with patch.object(orchestrator, "restore_targets", return_value=None):
            result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert result["deleted_volumes"] == []
        assert orchestrator.restore_marks() == {"mysterium"}


class TestARestoreWhoseEndCannotBeRecorded:
    def test_it_is_undone_rather_than_started_under_a_record_that_stays(self, docker):
        real = orchestrator._mark_restore_unfinished

        def mark(slug, held, *volumes):
            return False if not held and docker.puts else real(slug, held, *volumes)

        with (
            patch.object(orchestrator, "_mark_restore_unfinished", mark),
            pytest.raises(orchestrator.RestoreError, match="could not record that the restore of mysterium finished"),
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert docker.started == [] and "cashpilot-mysterium" not in docker.container_map
        _assert_kept_and_held(docker, "mysterium-data")


class TestAWrittenVolumeAnotherContainerMounts:
    """Docker refuses the delete of a written volume another container mounts: it holds restored data."""

    def test_it_is_left_and_stays_held(self, docker):
        docker.corrupt_put = True
        real_read = orchestrator._read_back

        def read_back(container, target):
            other = FakeContainer(docker, "someone-else", {"/data": "mysterium-data"})
            docker.container_map[other.name] = other
            return real_read(container, target)

        with (
            patch.object(orchestrator, "_read_back", read_back),
            pytest.raises(orchestrator.RestoreError) as caught,
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert "mysterium-data" in caught.value.left and "mysterium-data" in docker.volume_map
        assert orchestrator.restore_marks() == {"mysterium"}
        assert orchestrator._restore_helper("mysterium") is not None

    def test_control_an_unwritten_volume_another_deploy_took_is_kept_and_named(self, docker):
        def taken(**_kw):
            docker.volumes.create("mysterium-data")
            theirs = FakeContainer(docker, "cashpilot-mysterium", {"/var/lib/mysterium-node": "mysterium-data"})
            docker.container_map[theirs.name] = theirs
            raise orchestrator.ContainerRuntimeError("cashpilot-mysterium already exists", 409)

        orchestrator.deploy_raw.__wrapped__ = taken
        with pytest.raises(orchestrator.RestoreError) as caught:
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        # The volume this restore made stays (the undo deletes none), and a container
        # under the name mounts it with no check read: the record holds both, as the
        # gated branch's mark does, and left names the container so the dashboard
        # holds it too. The volume was never written, so it holds none of the backup.
        assert caught.value.left == ["cashpilot-mysterium"] and "mysterium-data" in docker.volume_map
        assert orchestrator.restore_marks() == {"mysterium"}


class TestAnUndoThatLeavesAnUncheckedContainer:
    def test_the_hold_stays_when_the_helper_was_never_made_and_the_container_stays(self, docker):
        real_remove = FakeContainer.remove

        def remove(container, force=False):
            if container.name == "cashpilot-mysterium":
                raise RuntimeError("daemon gone")
            return real_remove(container, force)

        with (
            patch.object(orchestrator, "_create_restore_helper", side_effect=RuntimeError("create refused")),
            patch.object(FakeContainer, "remove", remove),
            pytest.raises(orchestrator.RestoreError) as caught,
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert "cashpilot-mysterium" in caught.value.left and docker.puts == []
        orchestrator._RESTORE_MARK_UNWRITTEN.clear()
        assert orchestrator.restore_marks() == {"mysterium"}
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish"):
            orchestrator.start_service("mysterium")
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish"):
            TestStartAndRemoveAroundARestore()._deploy(docker)
        assert docker.started == []

    def test_control_an_undo_that_made_nothing_ends_the_hold(self, docker):
        with (
            patch.object(orchestrator, "_create_restore_volume", side_effect=orchestrator.RestoreError("refused")),
            pytest.raises(orchestrator.RestoreError) as caught,
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert caught.value.left == [] and orchestrator.restore_marks() == set()


class TestARemovalPersistsTheHoldBeforeTheHelperGoes:
    def test_a_record_that_cannot_be_written_refuses_the_removal(self, docker):
        TestStartAndRemoveAroundARestore()._service(docker, helper=True)
        with (
            patch.object(orchestrator, "_mark_restore_unfinished", return_value=False),
            pytest.raises(orchestrator.ContainerRuntimeError, match="nothing was removed") as caught,
        ):
            _owner_removes("mysterium")
        assert caught.value.status_code == 503
        assert {"cashpilot-mysterium", "cashpilot-mysterium.restore"} <= set(docker.container_map)
        assert "mysterium-data" in docker.volume_map and docker.removed == []

    def test_a_written_record_holds_after_a_restart_when_the_delete_and_the_helper_fail(self, docker):
        TestStartAndRemoveAroundARestore()._service(docker, helper=True)
        with (
            patch.object(FakeVolume, "remove", side_effect=requests.exceptions.ReadTimeout("proxy timed out")),
            patch.object(orchestrator, "_create_restore_helper", side_effect=RuntimeError("daemon gone")),
        ):
            result = _owner_removes("mysterium")
        assert result["failed_volumes"] == ["mysterium-data"] and orchestrator._restore_helper("mysterium") is None
        orchestrator._RESTORE_MARK_UNWRITTEN.clear()
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish"):
            TestStartAndRemoveAroundARestore()._deploy(docker)

    def test_a_record_write_that_fails_then_a_restart_still_holds_by_the_helper(self, docker, monkeypatch):
        """The write fails for real, the removal is refused, the worker restarts: the helper it kept still holds."""
        TestStartAndRemoveAroundARestore()._service(docker, helper=True)
        _record_unwritable(monkeypatch)
        with pytest.raises(orchestrator.ContainerRuntimeError, match="nothing was removed") as caught:
            _owner_removes("mysterium")
        assert caught.value.status_code == 503 and docker.removed == []
        orchestrator._RESTORE_MARK_UNWRITTEN.clear()
        assert orchestrator.restore_marks() == set()
        assert orchestrator._restore_helper("mysterium") is not None
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish"):
            TestStartAndRemoveAroundARestore()._deploy(docker)
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish"):
            orchestrator.start_service("mysterium")
        assert docker.started == []


class TestABackupFingerprintIsOfTheVolumeItRead:
    def test_the_state_id_comes_from_the_read_not_a_later_one(self, docker, worker):
        TestStartAndRemoveAroundARestore()._service(docker)
        docker.volume_map["mysterium-data"].attrs["CreatedAt"] = "the-volume-read"
        container = docker.container_map["cashpilot-mysterium"]
        container.status = "exited"
        targets = {"/var/lib/mysterium-node": "node identity"}
        expected = orchestrator.state_id(container, targets, docker)
        real_read = orchestrator.read_critical_state

        def read_then_replace(slug):
            found = real_read(slug)
            # The volume is replaced right after the read: a fingerprint taken now names the new one.
            docker.volume_map["mysterium-data"].attrs["CreatedAt"] = "a-volume-made-since"
            return found

        with (
            patch.object(orchestrator, "_critical_volume_targets", return_value=targets),
            patch.object(orchestrator, "read_critical_state", read_then_replace),
            patch.object(worker_api.state_backup, "split_archives", lambda payload: {}),
        ):
            resp = worker.client.post(
                "/api/containers/mysterium/backup",
                json={"passphrase": PASSPHRASE},
                headers={"Authorization": f"Bearer {WORKER_KEY}"},
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["state_id"] == expected


class TestARestoreSpecMountsTheCatalogVolume:
    @pytest.mark.parametrize(
        "volumes",
        [{}, {"another-volume": {"bind": "/home/proxybase/.proxybase"}}],
        ids=["no-volume", "another-volume"],
    )
    def test_a_critical_folder_on_another_volume_or_none_is_refused_first(self, worker, volumes):
        resp = worker("proxybase-xyz", proxybase_bundle(), spec={**PROXYBASE_SPEC, "volumes": volumes})
        assert resp.status_code == 400 and "does not mount it there" in _detail(resp) and worker.calls == []

    def test_control_the_catalog_volume_goes_on(self, worker):
        assert worker("proxybase-xyz", proxybase_bundle()).status_code == 200


class TestAStalledUploadGivesItsSlotBack:
    def test_an_upload_that_stops_arriving_ends_and_frees_its_slot(self, ui, monkeypatch):
        monkeypatch.setattr(main, "RESTORE_UPLOAD_IDLE", 0.05)
        monkeypatch.setattr(main, "_require_owner_session", lambda request: {"uid": 1})

        class Stalled:
            headers: dict[str, str] = {}

            async def stream(self):
                yield b"CPBK"
                await asyncio.Event().wait()

        with pytest.raises(HTTPException) as caught:
            asyncio.run(asyncio.wait_for(main.api_restore_upload(Stalled()), 5))
        assert caught.value.status_code == 408
        assert main._restore_receiving == set() and _uploads_on_disk(ui) == []


def _record_unwritable(monkeypatch, when=lambda: True) -> None:
    """The record's .tmp cannot be written while ``when()``, as a full or read-only /data."""
    import builtins

    real_open = builtins.open
    temp = f"{orchestrator.RESTORE_MARKER}.tmp"

    def fake_open(file, *args, **kwargs):
        if str(file) == temp and when():
            raise OSError(28, "No space left on device")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(orchestrator, "open", fake_open, raising=False)


class TestAClearTheDiskDidNotTakeKeepsTheHold:
    """A clear that did not reach the disk lifts nothing: after a restart the file would hold a fresh node."""

    @staticmethod
    def _refused_before_any_volume(failed: list[bool]):
        """An undo with nothing to keep: the first volume's create is refused, so its clear runs."""

        def refuse(*_a):
            failed.append(True)
            raise orchestrator.RestoreError("refused")

        return patch.object(orchestrator, "_create_restore_volume", refuse)

    def test_the_undo_keeps_holding_the_slug_in_this_process(self, docker, monkeypatch):
        failed: list[bool] = []
        # The hold goes on disk; only the clear, once the create failed, cannot.
        _record_unwritable(monkeypatch, lambda: bool(failed))
        with self._refused_before_any_volume(failed), pytest.raises(orchestrator.RestoreError) as caught:
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert caught.value.left == [] and docker.container_map == {} and docker.volume_map == {}
        assert _record_names() == "mysterium mysterium-data\n"
        assert orchestrator.restore_marks() == {"mysterium"}
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish"):
            TestStartAndRemoveAroundARestore()._deploy(docker)

    def test_a_removal_keeps_holding_the_slug_in_this_process(self, docker, monkeypatch):
        _recorded(docker)
        _record_unwritable(monkeypatch)
        result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert result["deleted_volumes"] == ["mysterium-data"]
        assert orchestrator.restore_marks() == {"mysterium"}

    def test_control_a_clear_the_disk_took_ends_the_hold(self, docker):
        with self._refused_before_any_volume([]), pytest.raises(orchestrator.RestoreError):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert orchestrator.restore_marks() == set() and not Path(orchestrator.RESTORE_MARKER).read_text()


class TestAnUndoKeepsTheVolumesInTheRecord:
    def test_a_start_that_fails_after_the_clear_records_the_volume_again(self, docker):
        with (
            patch.object(orchestrator, "_start_restored", side_effect=RuntimeError("start refused")),
            patch.object(FakeVolume, "remove", side_effect=requests.exceptions.ReadTimeout("proxy timed out")),
            pytest.raises(orchestrator.RestoreError) as caught,
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert caught.value.left == ["mysterium-data"]
        assert _record_names() == "mysterium mysterium-data\n"


class TestALeftoverUnderTheNameHoldsANonGatedRestore:
    """deploy_raw's roll-back can leave a container the restore never listed, mounting the volume it made."""

    def test_the_record_stays_and_nothing_starts_it(self, docker):
        def half_made(**kwargs):
            docker.deploy_raw(**kwargs)
            raise orchestrator.ContainerRuntimeError("create timed out; the leftover could not be removed")

        orchestrator.deploy_raw.__wrapped__ = half_made
        with pytest.raises(orchestrator.RestoreError) as caught:
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        # Named in left: the worker answers "left", not "restored": false, so the
        # dashboard keeps holding it as the worker does.
        assert caught.value.left == ["cashpilot-mysterium"]
        assert "cashpilot-mysterium" in docker.container_map
        assert orchestrator.restore_marks() == {"mysterium"}
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish"):
            orchestrator.start_service("mysterium")
        assert docker.started == []


# ---------------------------------------------------------------------------
# Round 15: a volume this restore made is its own only while its nonce is on
# it, and a container left under the name is reported, not hidden
# ---------------------------------------------------------------------------


def _replace_after_creation(docker, volume: str):
    """_created_new, then another client removes ``volume`` (still unused) and creates its own under the name."""
    real = orchestrator._created_new

    def created_then_replaced(client, name, nonce=None):
        made = real(client, name, nonce)
        if name == volume:
            docker.volume_map.pop(name)
            docker.volumes.create(name, labels={"theirs": "1"})
        return made

    return patch.object(orchestrator, "_created_new", created_then_replaced)


class TestAVolumeReplacedAfterTheRestoreMadeIt:
    EXTRA_DEPLOY = TestTheRestoreSequence.EXTRA_DEPLOY

    def test_another_volume_replaced_before_the_mount_survives_the_undo(self, docker):
        docker.corrupt_put = True
        with _replace_after_creation(docker, "mysterium-extra"), pytest.raises(orchestrator.RestoreError):
            orchestrator.restore_state("mysterium", _archives(), self.EXTRA_DEPLOY)
        assert docker.volume_map["mysterium-extra"].attrs["Labels"] == {"theirs": "1"}
        assert ("volume", "mysterium-extra") not in docker.removed and docker.started == []
        # Not this restore's any more: not named as what it left, and not held for a delete.
        assert "mysterium-extra" not in orchestrator._restore_mark_volumes("mysterium")
        _assert_kept_and_held(docker, "mysterium-data")

    def test_the_data_volume_replaced_before_the_mount_is_never_written_or_removed(self, docker):
        with (
            _replace_after_creation(docker, "mysterium-data"),
            pytest.raises(orchestrator.RestoreError, match="mysterium-data") as caught,
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        replacement = docker.volume_map["mysterium-data"]
        assert replacement.attrs["Labels"] == {"theirs": "1"} and replacement.files == {}
        assert docker.puts == [] and docker.started == [] and docker.container_map == {}
        assert caught.value.left == []

    def test_control_a_volume_still_carrying_its_nonce_is_kept_and_held(self, docker):
        docker.corrupt_put = True
        with pytest.raises(orchestrator.RestoreError) as caught:
            orchestrator.restore_state("mysterium", _archives(), self.EXTRA_DEPLOY)
        _assert_kept_and_held(docker, "mysterium-data", "mysterium-extra")
        assert caught.value.left == ["mysterium-data"]


class TestAContainerLeftUnderTheNameIsReported:
    def test_the_worker_answers_left_so_the_dashboard_keeps_the_hold(self, docker, worker, monkeypatch):
        def half_made(**kwargs):
            docker.deploy_raw(**kwargs)
            raise orchestrator.ContainerRuntimeError("create timed out; the leftover could not be removed")

        orchestrator.deploy_raw.__wrapped__ = half_made
        monkeypatch.setattr(worker_api.orchestrator, "restore_state", REAL_RESTORE_STATE)
        resp = worker("proxybase-xyz", proxybase_bundle())
        body = resp.json()
        assert resp.status_code >= 400 and "cashpilot-proxybase-xyz" in docker.container_map
        assert body.get("left") == ["cashpilot-proxybase-xyz"] and "restored" not in body, body
        assert orchestrator.restore_marks() == {"proxybase-xyz"}

    def test_control_an_undo_that_made_nothing_says_nothing_was_restored(self, docker):
        with (
            patch.object(orchestrator, "_create_restore_volume", side_effect=orchestrator.RestoreError("refused")),
            pytest.raises(orchestrator.RestoreError) as caught,
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert caught.value.left == [] and orchestrator.restore_marks() == set()


# ---------------------------------------------------------------------------
# Round 15: the owner's approval of a critical delete names the volumes they
# reviewed, and the worker deletes those or nothing
# ---------------------------------------------------------------------------


def _bound_delete_approval(critical_set: str, slug="mysterium"):
    target = step_up.delete_target(slug, CLIENT_ID, critical_set)
    return {step_up.APPROVAL_HEADER: step_up.sign(WORKER_KEY, step_up.ACTION_DELETE_CRITICAL, target)}


class TestACriticalDeleteIsBoundToTheVolumesTheOwnerReviewed:
    URL = "/api/containers/mysterium?delete_volumes=true"
    AUTH = {"Authorization": f"Bearer {WORKER_KEY}"}
    CREATED = "2026-11-01T10:00:00Z"

    @pytest.fixture
    def box(self, docker, worker, monkeypatch):
        """A box that runs mysterium on mysterium-data; the copies and tunnels around a removal are not here."""
        monkeypatch.setattr(worker_api.orchestrator, "remove_extra_instances", lambda slug: [])
        monkeypatch.setattr(worker_api.orchestrator, "copy_identity_digests", lambda slug: {})
        monkeypatch.setattr(worker_api.proxy_tunnel, "remove_all", lambda slug: [])
        monkeypatch.setattr(worker_api.lan_fence, "refresh_outside", lambda: None)
        TestStartAndRemoveAroundARestore()._service(docker)
        docker.volume_map["mysterium-data"].attrs["CreatedAt"] = self.CREATED
        return docker

    def _review(self, worker):
        """The first delete, as the dashboard sends it: refused, naming what is critical."""
        resp = worker.client.delete(self.URL, headers=self.AUTH)
        detail = resp.json()["detail"]
        assert resp.status_code == 409 and detail["error"] == "critical_volume", resp.text
        return detail["critical_set"]

    def _confirm(self, worker, reviewed, *, approved=None, query=None):
        """The owner's retry: the reviewed set in the query and in the approval the UI signed."""
        sent = reviewed if query is None else query
        url = f"{self.URL}&allow_delete_critical=true"
        if sent is not None:
            url += f"&critical_set={urllib.parse.quote(sent, safe='')}"
        approval = _bound_delete_approval(reviewed if approved is None else approved)
        return worker.client.delete(url, headers={**self.AUTH, **approval})

    def test_the_refusal_names_each_volume_with_when_it_was_made(self, box, worker):
        assert self._review(worker) == f"mysterium-data@{self.CREATED}"

    def test_the_reviewed_volumes_are_deleted(self, box, worker):
        resp = self._confirm(worker, self._review(worker))
        assert resp.status_code == 200, resp.text
        assert box.container_map == {} and box.volume_map == {}

    def test_another_volume_mounted_since_the_review_is_not_deleted(self, box, worker):
        reviewed = self._review(worker)
        # Another tab redeployed the service on a fresh volume before the owner confirmed.
        box.volumes.create("mysterium-data-2")
        box.volume_map["mysterium-data-2"].attrs["CreatedAt"] = "2026-11-02T09:00:00Z"
        container = box.container_map["cashpilot-mysterium"]
        container.mounts = {"/var/lib/mysterium-node": "mysterium-data-2"}
        container.attrs["Mounts"] = [
            {"Type": "volume", "Name": "mysterium-data-2", "Destination": "/var/lib/mysterium-node"}
        ]
        resp = self._confirm(worker, reviewed)
        detail = resp.json()["detail"]
        assert resp.status_code == 409 and detail["error"] == "critical_volume", resp.text
        assert "changed since" in detail["message"] and "Nothing was removed" in detail["message"]
        assert detail["critical_set"] == "mysterium-data-2@2026-11-02T09:00:00Z"
        assert "cashpilot-mysterium" in box.container_map
        assert {"mysterium-data", "mysterium-data-2"} <= set(box.volume_map) and box.removed == []

    def test_a_volume_made_again_under_the_same_name_since_the_review_is_not_deleted(self, box, worker):
        reviewed = self._review(worker)
        box.volume_map["mysterium-data"].attrs["CreatedAt"] = "2026-11-03T08:00:00Z"
        resp = self._confirm(worker, reviewed)
        assert resp.status_code == 409 and resp.json()["detail"]["error"] == "critical_volume"
        assert "mysterium-data" in box.volume_map and box.removed == []

    def test_an_approval_for_another_set_removes_nothing(self, box, worker):
        reviewed = self._review(worker)
        resp = self._confirm(worker, reviewed, approved="mysterium-data@2020-01-01T00:00:00Z")
        assert resp.status_code == 403 and resp.json()["detail"]["error"] == "step_up_rejected"
        assert box.removed == []

    def test_a_bound_approval_without_its_set_removes_nothing(self, box, worker):
        reviewed = self._review(worker)
        url = f"{self.URL}&allow_delete_critical=true"
        resp = worker.client.delete(url, headers={**self.AUTH, **_bound_delete_approval(reviewed)})
        assert resp.status_code == 403 and resp.json()["detail"]["error"] == "step_up_rejected"
        assert box.removed == []


class TestTheDashboardCarriesTheReviewedSet:
    CRITICAL = "&delete_volumes=true&allow_delete_critical=true"
    REVIEWED = "mysterium-data@2026-11-01T10:00:00+01:00"

    def _remove(self, ui, query):
        return TestRemoveAfterARestoreThatDidNotFinish()._remove(
            ui, query, 200, {"status": "removed", "deleted_volumes": ["mysterium-data"]}, "?worker_id=2"
        )

    def test_the_set_goes_to_the_worker_and_into_the_approval(self, ui):
        resp, sent = self._remove(ui, f"{self.CRITICAL}&critical_set={urllib.parse.quote(self.REVIEWED, safe='')}")
        assert resp.status_code == 200, resp.text
        assert sent.call_args.kwargs["params"] == {
            "delete_volumes": "true",
            "allow_delete_critical": "true",
            "critical_set": self.REVIEWED,
        }
        approval = sent.call_args.kwargs["headers"][step_up.APPROVAL_HEADER]
        with pytest.raises(step_up.StepUpError, match="another action"):
            step_up.check(WORKER_KEY, approval, step_up.ACTION_DELETE_CRITICAL, "mysterium|client-b")
        step_up.check(
            WORKER_KEY,
            approval,
            step_up.ACTION_DELETE_CRITICAL,
            step_up.delete_target("mysterium", "client-b", self.REVIEWED),
        )

    def test_the_refusal_forwards_the_set_to_review(self):
        answer = MagicMock()
        answer.json.return_value = {
            "detail": {
                "error": "critical_volume",
                "message": "m",
                "hint": "h",
                "blocked": [{"volume": "mysterium-data", "target": "/var/lib/mysterium-node", "holds": "x"}],
                "critical_set": self.REVIEWED,
            }
        }
        assert main._safe_worker_detail(answer)["critical_set"] == self.REVIEWED


# ---------------------------------------------------------------------------
# Round 16: no critical delete without the owner's reviewed set, a held volume
# is critical wherever it is mounted, and the undo never deletes a volume
# ---------------------------------------------------------------------------


class TestNoCriticalDeleteWithoutTheReviewedSet:
    AUTH = {"Authorization": f"Bearer {WORKER_KEY}"}

    @pytest.fixture
    def box(self, docker, worker, monkeypatch):
        """A partial restore left under the name: its container mounts the identity volume, its helper too."""
        monkeypatch.setattr(worker_api.orchestrator, "remove_extra_instances", lambda slug: [])
        monkeypatch.setattr(worker_api.orchestrator, "copy_identity_digests", lambda slug: {})
        monkeypatch.setattr(worker_api.proxy_tunnel, "remove_all", lambda slug: [])
        monkeypatch.setattr(worker_api.lan_fence, "refresh_outside", lambda: None)
        TestStartAndRemoveAroundARestore()._service(docker, helper=True)
        return docker

    def test_the_partial_restore_retry_without_a_set_deletes_nothing(self, box, worker):
        """The override and the owner's password alone: nobody listed the identity volume to them."""
        url = "/api/containers/mysterium?delete_volumes=true&allow_delete_critical=true&only_if_restore_unfinished=true"
        resp = worker.client.delete(url, headers={**self.AUTH, **_delete_approval()})
        detail = resp.json()["detail"]
        assert resp.status_code == 409 and detail["error"] == "critical_volume", resp.text
        # The set the owner then reviews, the volume with the time Docker made it.
        assert detail["critical_set"].startswith("mysterium-data@2026-")
        assert box.removed == [] and "mysterium-data" in box.volume_map

    def test_control_the_retry_with_the_reviewed_set_deletes_it(self, box, worker):
        url = "/api/containers/mysterium?delete_volumes=true&only_if_restore_unfinished=true"
        reviewed = worker.client.delete(url, headers=self.AUTH).json()["detail"]["critical_set"]
        resp = worker.client.delete(
            f"{url}&allow_delete_critical=true&critical_set={urllib.parse.quote(reviewed, safe='')}",
            headers={**self.AUTH, **_bound_delete_approval(reviewed)},
        )
        assert resp.status_code == 200, resp.text
        assert box.volume_map == {} and box.container_map == {}


class TestAHeldVolumeIsCriticalWhereverItIsMounted:
    """The catalog may no longer list the target a partial restore's container mounts its volume at."""

    def _leftover_at_an_old_target(self, docker):
        container = TestStartAndRemoveAroundARestore()._service(docker)
        container.mounts = {"/var/lib/old-node": "mysterium-data"}
        container.attrs["Mounts"] = [{"Type": "volume", "Name": "mysterium-data", "Destination": "/var/lib/old-node"}]
        _recorded(None)
        docker.volume_map["mysterium-data"].attrs["Labels"] = {orchestrator.LABEL_RESTORE: "ab" * 16}

    def test_its_delete_is_refused_without_the_override(self, docker):
        self._leftover_at_an_old_target(docker)
        with pytest.raises(orchestrator.CriticalVolumeError) as caught:
            orchestrator.remove_service("mysterium", delete_volumes=True)
        assert [b["volume"] for b in caught.value.blocked] == ["mysterium-data"]
        assert docker.removed == [] and "cashpilot-mysterium" in docker.container_map

    def test_control_the_owners_reviewed_delete_removes_it(self, docker):
        self._leftover_at_an_old_target(docker)
        result = _owner_removes("mysterium")
        assert result["deleted_volumes"] == ["mysterium-data"] and docker.volume_map == {}
        assert orchestrator.restore_marks() == set()


class TestATimeDockerDoesNotGiveBindsNothing:
    def test_a_set_reviewed_and_confirmed_without_a_time_deletes_nothing(self, docker):
        """Both reads failed: "name@" on both sides would match a volume made again under the name."""
        TestStartAndRemoveAroundARestore()._service(docker)
        del docker.volume_map["mysterium-data"].attrs["CreatedAt"]
        with pytest.raises(orchestrator.CriticalVolumeError) as review:
            orchestrator.remove_service("mysterium", delete_volumes=True)
        assert review.value.critical_set == "mysterium-data@?"
        for confirmed in ("mysterium-data@?", "mysterium-data@"):
            with pytest.raises(orchestrator.CriticalVolumeError, match="did not say when it made"):
                orchestrator.remove_service(
                    "mysterium", delete_volumes=True, allow_delete_critical=True, approved_critical=confirmed
                )
        assert docker.removed == [] and "cashpilot-mysterium" in docker.container_map

    def test_a_recorded_volume_that_is_gone_still_lets_the_record_go(self, docker):
        """Gone is known, not unknown: the owner's delete ends a record whose volume no longer exists."""
        _recorded(None)
        # Nothing of the restore is left to review, so nothing is asked and nothing is deleted.
        result = orchestrator.remove_service("mysterium", delete_volumes=True, only_if_restore_unfinished=True)
        assert result["deleted_volumes"] == [] and orchestrator.restore_marks() == set()

    def test_a_volume_made_under_a_gone_name_since_the_review_is_not_deleted(self, docker):
        _recorded(docker)
        with pytest.raises(orchestrator.CriticalVolumeError) as review:
            orchestrator.remove_service("mysterium", delete_volumes=True)
        del docker.volume_map["mysterium-data"]
        docker.volumes.create("mysterium-data", labels={"theirs": "1"})
        with pytest.raises(orchestrator.CriticalVolumeError, match="changed since"):
            orchestrator.remove_service(
                "mysterium",
                delete_volumes=True,
                allow_delete_critical=True,
                approved_critical=review.value.critical_set,
            )
        assert "mysterium-data" in docker.volume_map and docker.removed == []


class TestAVolumeMadeAgainBeforeItsDeleteIsKept:
    def test_a_volume_replaced_after_the_container_went_is_not_deleted(self, docker):
        """The check passed; then the container freed the volume and another client made its own under the name."""
        TestStartAndRemoveAroundARestore()._service(docker)
        real_remove = FakeContainer.remove

        def remove_then_replace(container, force=False):
            real_remove(container, force)
            if container.name == "cashpilot-mysterium":
                docker.volume_map.pop("mysterium-data")
                docker.volumes.create("mysterium-data", labels={"theirs": "1"})

        with patch.object(FakeContainer, "remove", remove_then_replace):
            result = _owner_removes("mysterium")
        assert result["failed_volumes"] == ["mysterium-data"] and result["deleted_volumes"] == []
        assert result["replaced_volumes"] == ["mysterium-data"]
        assert docker.volume_map["mysterium-data"].attrs["Labels"] == {"theirs": "1"}


class TestTheUndoNeverDeletesAVolume:
    def test_a_volume_swapped_right_after_its_nonce_is_read_survives(self, docker):
        """Docker deletes by name: a check, then a delete, takes whatever another client put under it between."""
        docker.corrupt_put = True
        real_get = FakeVolumes.get

        def get_then_swap(volumes, name):
            found = real_get(volumes, name)
            undoing = docker.puts and "cashpilot-mysterium" not in docker.container_map
            if undoing and name == "mysterium-data" and "theirs" not in found.attrs["Labels"]:
                docker.volume_map.pop(name)
                docker.volumes.create(name, labels={"theirs": "1"})
            return found

        with patch.object(FakeVolumes, "get", get_then_swap), pytest.raises(orchestrator.RestoreError):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert docker.volume_map["mysterium-data"].attrs["Labels"] == {"theirs": "1"}
        assert ("volume", "mysterium-data") not in docker.removed
        # Its owner unknown, so the slug stays held for the owner's reviewed delete.
        assert orchestrator.restore_marks() == {"mysterium"}


class TestANameDockerCannotReadIsNotSaidToHoldAContainer:
    def test_the_note_says_it_could_not_read_it(self, docker):
        docker.corrupt_put = True
        real_get = FakeContainers.get
        response = requests.Response()
        response.status_code = 500

        def get(containers, name):
            if docker.puts and name == "cashpilot-mysterium":
                raise APIError("proxy error", response=response)
            return real_get(containers, name)

        with patch.object(FakeContainers, "get", get), pytest.raises(orchestrator.RestoreError) as caught:
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert "could not read whether a container holds the name cashpilot-mysterium" in str(caught.value)
        assert "is on this box now" not in str(caught.value)
        # Not known is still held.
        assert "cashpilot-mysterium" in caught.value.left and orchestrator.restore_marks() == {"mysterium"}


# ---------------------------------------------------------------------------
# Round 16: the record keeps each volume's nonce, so the owner's Remove deletes
# only what the failed restore still provably made, and all of it
# ---------------------------------------------------------------------------


def _refused_by_deploy_raw():
    """deploy_raw refuses (the proxy, the image): the volumes exist, nothing was written, nothing is left under the name."""

    def refused(**_kw):
        raise orchestrator.ContainerRuntimeError("refused by the socket proxy", 403)

    orchestrator.deploy_raw.__wrapped__ = refused


class TestARemoveDeletesOnlyWhatTheFailedRestoreStillMade:
    def _failed_before_any_write(self, docker):
        _refused_by_deploy_raw()
        with pytest.raises(orchestrator.RestoreError):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        _assert_kept_and_held(docker, "mysterium-data")

    def test_a_volume_another_client_made_under_the_name_since_survives_the_owners_remove(self, docker):
        self._failed_before_any_write(docker)
        # Unmounted, so any client can remove it and make its own, with its own node identity.
        docker.volume_map.pop("mysterium-data")
        docker.volumes.create("mysterium-data", labels={"theirs": "1"})
        result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert result["deleted_volumes"] == [] and ("volume", "mysterium-data") not in docker.removed
        assert docker.volume_map["mysterium-data"].attrs["Labels"] == {"theirs": "1"}
        # Nothing of the restore is left, so its record goes.
        assert orchestrator.restore_marks() == set()

    def test_control_the_volume_it_made_goes_with_the_owners_remove(self, docker):
        self._failed_before_any_write(docker)
        result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert result["deleted_volumes"] == ["mysterium-data"] and docker.volume_map == {}
        assert orchestrator.restore_marks() == set()

    def test_every_volume_it_made_goes_even_when_its_helper_holds_only_the_written_one(self, docker):
        docker.corrupt_put = True
        with pytest.raises(orchestrator.RestoreError):
            orchestrator.restore_state("mysterium", _archives(), TestTheRestoreSequence.EXTRA_DEPLOY)
        helper = orchestrator._restore_helper("mysterium")
        assert [m["Name"] for m in helper.attrs["Mounts"]] == ["mysterium-data"]
        result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert sorted(result["deleted_volumes"]) == ["mysterium-data", "mysterium-extra"]
        assert docker.volume_map == {} and orchestrator.restore_marks() == set()

    def test_a_volume_that_cannot_be_read_removes_nothing(self, docker):
        self._failed_before_any_write(docker)
        with (
            patch.object(FakeVolumes, "get", side_effect=requests.exceptions.ReadTimeout("proxy timed out")),
            pytest.raises(orchestrator.ContainerRuntimeError, match="could not read the volume") as caught,
        ):
            _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert caught.value.status_code == 503 and docker.removed == []
        assert orchestrator.restore_marks() == {"mysterium"}


class TestAnUnwrittenVolumeDoesNotHoldTheIdentityOnTheDashboard:
    def test_the_worker_answers_restored_false_when_nothing_was_written(self, docker, worker, monkeypatch):
        _refused_by_deploy_raw()
        monkeypatch.setattr(worker_api.orchestrator, "restore_state", REAL_RESTORE_STATE)
        resp = worker("proxybase-xyz", proxybase_bundle())
        body = resp.json()
        assert resp.status_code >= 400 and body.get("restored") is False and "left" not in body, body
        # The empty volume stays, and this box alone holds the service until the owner removes it.
        assert "proxybase-data" in docker.volume_map and orchestrator.restore_marks() == {"proxybase-xyz"}
        assert "proxybase-data" in body["detail"]


class TestTheLiveDriverRemovesAsTheOwnerDoes:
    """scripts/socket_proxy_live_driver.py removes with data; the override alone reviews nothing and deletes nothing."""

    def test_the_fresh_phase_removes_the_service_and_its_volume(self, docker, capsys):
        import importlib.util

        path = Path(__file__).resolve().parents[1] / "scripts" / "socket_proxy_live_driver.py"
        spec = importlib.util.spec_from_file_location("socket_proxy_live_driver", path)
        driver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(driver)
        with (
            patch.object(orchestrator, "deploy_raw", lambda **kw: docker.deploy_raw(**{**kw, "start": False})),
            patch.object(driver.docker, "from_env", return_value=docker),
        ):
            driver.phase_fresh()
        out = capsys.readouterr().out
        assert "FAIL" not in out, out
        assert "PASS  the volume is gone" in out and docker.volume_map == {}

    def test_the_fresh_phase_waits_until_its_new_volume_can_be_reviewed(self, docker, capsys, frozen_clock):
        """On a real box the remove follows the deploy within a second: the volume reads "?" and binds no approval."""
        import importlib.util

        path = Path(__file__).resolve().parents[1] / "scripts" / "socket_proxy_live_driver.py"
        spec = importlib.util.spec_from_file_location("socket_proxy_live_driver", path)
        driver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(driver)

        def deploy_now(**kw):
            done = docker.deploy_raw(**{**kw, "start": False})
            for volume in docker.volume_map.values():
                volume.attrs["CreatedAt"] = _docker_time()
            return done

        def sleep(seconds):
            frozen_clock["now"] += timedelta(seconds=seconds)

        with (
            patch.object(orchestrator, "deploy_raw", deploy_now),
            patch.object(driver.docker, "from_env", return_value=docker),
            patch("time.sleep", sleep),
        ):
            driver.phase_fresh()
        out = capsys.readouterr().out
        assert "FAIL" not in out, out
        assert "PASS  the volume is gone" in out and docker.volume_map == {} and docker.container_map == {}


# ---------------------------------------------------------------------------
# Round 17: the nonce is read again right before each write and each delete,
# and a helper's mount counts as the restore's only with its nonce
# ---------------------------------------------------------------------------


def _swap(docker: FakeDocker, volume: str = "mysterium-data", same_time: bool = False) -> None:
    """Another client removes ``volume`` and makes its own under the name (with the same CreatedAt when ``same_time``)."""
    old = docker.volume_map.pop(volume)
    new = docker.volumes.create(volume, labels={"theirs": "1"})
    if same_time:
        # Docker gives CreatedAt to the second: a volume made again within it reads the same time.
        new.attrs["CreatedAt"] = old.attrs["CreatedAt"]


class TestAVolumeSwappedBeforeItsWriteGetsNoBackup:
    def test_a_volume_swapped_after_the_container_check_is_not_written_and_stays_held(self, docker):
        """Another client prunes the created container, then swaps the volume before the helper mounts it."""
        real = orchestrator._create_restore_helper

        def prune_and_swap_first(client, image, name, volumes):
            if "cashpilot-mysterium" in docker.container_map:
                docker.container_map.pop("cashpilot-mysterium")
                _swap(docker)
            return real(client, image, name, volumes)

        with (
            patch.object(orchestrator, "_create_restore_helper", prune_and_swap_first),
            pytest.raises(orchestrator.RestoreError) as caught,
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        replacement = docker.volume_map["mysterium-data"]
        assert replacement.attrs["Labels"] == {"theirs": "1"} and replacement.files == {}
        assert docker.puts == [] and docker.started == []
        assert ("volume", "mysterium-data") not in docker.removed
        # Fail closed: reported as left (never restored: false) and the slug stays held.
        assert "mysterium-data" in caught.value.left
        assert orchestrator.restore_marks() == {"mysterium"}

    def test_a_written_volume_swapped_before_the_undo_is_reported_left_and_held(self, docker):
        """Written, then replaced: the undo cannot tell where the backup went, so the dashboard keeps holding it."""
        real_put = FakeContainer.put_archive

        def put_then_swap(container, path, data):
            done = real_put(container, path, data)
            _swap(docker)
            return done

        with (
            patch.object(FakeContainer, "put_archive", put_then_swap),
            pytest.raises(orchestrator.RestoreError) as caught,
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert docker.volume_map["mysterium-data"].attrs["Labels"] == {"theirs": "1"}
        assert ("volume", "mysterium-data") not in docker.removed and docker.started == []
        assert "mysterium-data" in caught.value.left and "replaced" in str(caught.value)
        assert orchestrator.restore_marks() == {"mysterium"}


class TestTheRemoveAfterASwapNamesTheVolumeItKept:
    """A restore left a volume another client replaced: the owner's Remove names it as kept, never a plain success.

    The restore answered that it left the volume and that the dashboard holds
    the identity there. The Remove is the one step that ends that hold, so its
    answer must name the volume the box kept, or nothing names it any more.
    """

    TWO_TARGETS = TestTheRestoreSequence.EXTRA_DEPLOY
    TARGETS = {"/var/lib/mysterium-node": "mysterium-data", "/etc/extra": "mysterium-extra"}

    @staticmethod
    def _two_archives():
        extra = state_backup.split_archives(docker_archive("extra", [("extra.conf", "file", 0o644, 0, 0, b"x=1\n")]))
        return {**_archives(), **extra}

    def test_the_first_remove_after_a_swap_before_the_write_reports_it_replaced(self, docker):
        real = orchestrator._create_restore_helper

        def prune_and_swap_first(client, image, name, volumes):
            if "cashpilot-mysterium" in docker.container_map:
                docker.container_map.pop("cashpilot-mysterium")
                _swap(docker)
            return real(client, image, name, volumes)

        with (
            patch.object(orchestrator, "_create_restore_helper", prune_and_swap_first),
            pytest.raises(orchestrator.RestoreError) as caught,
        ):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        assert caught.value.left == ["mysterium-data"] and orchestrator.restore_marks() == {"mysterium"}

        # The dashboard's leftover-row Remove: a plain DELETE, no review, no password.
        result = orchestrator.remove_service("mysterium", delete_volumes=True, only_if_restore_unfinished=True)
        assert result["deleted_volumes"] == []
        assert result["replaced_volumes"] == ["mysterium-data"]
        # Still read as a partial delete by a caller that reads only failed_volumes.
        assert result["failed_volumes"] == ["mysterium-data"]
        assert docker.volume_map["mysterium-data"].attrs["Labels"] == {"theirs": "1"}
        assert ("volume", "mysterium-data") not in docker.removed
        # Named once, as another client's, which no Remove can change: the record goes.
        assert orchestrator.restore_marks() == set()

    def test_the_remove_after_a_second_target_failed_its_write_check_reports_it_replaced(self, docker):
        real_put = FakeContainer.put_archive

        def put_then_swap_extra(container, path, data):
            done = real_put(container, path, data)
            if "mysterium-extra" in docker.volume_map and docker.volume_map["mysterium-extra"].attrs["Labels"].get(
                orchestrator.LABEL_RESTORE
            ):
                _swap(docker, "mysterium-extra")
            return done

        with (
            patch.object(orchestrator, "restore_targets", return_value=self.TARGETS),
            patch.object(FakeContainer, "put_archive", put_then_swap_extra),
            pytest.raises(orchestrator.RestoreError) as caught,
        ):
            orchestrator.restore_state("mysterium", self._two_archives(), self.TWO_TARGETS)
        # The first target was written and kept; the second failed its write-time re-check.
        assert set(caught.value.left) >= {"mysterium-data", "mysterium-extra"}
        assert docker.volume_map["mysterium-data"].files and docker.volume_map["mysterium-extra"].files == {}
        assert orchestrator.restore_marks() == {"mysterium"}

        result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert result["deleted_volumes"] == ["mysterium-data"]
        assert result["replaced_volumes"] == ["mysterium-extra"]
        assert result["failed_volumes"] == ["mysterium-extra"]
        assert docker.volume_map["mysterium-extra"].attrs["Labels"] == {"theirs": "1"}
        assert ("volume", "mysterium-extra") not in docker.removed
        assert orchestrator.restore_marks() == set()

    def test_control_a_remove_with_nothing_replaced_reports_nothing_replaced(self, docker):
        docker.corrupt_put = True
        with pytest.raises(orchestrator.RestoreError):
            orchestrator.restore_state("mysterium", _archives(), MYSTERIUM_DEPLOY)
        result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert result["deleted_volumes"] == ["mysterium-data"]
        assert result["replaced_volumes"] == [] and result["failed_volumes"] == []
        assert orchestrator.restore_marks() == set()


class TestAHelperMountWithoutTheNonceIsNotTheRestores:
    def test_a_volume_swapped_under_the_put_back_helper_survives_the_owners_remove(self, docker):
        docker.corrupt_put = True
        real = orchestrator._create_restore_helper
        calls = []

        def swap_before_put_back(client, image, name, volumes):
            calls.append(name)
            if len(calls) == 2:
                _swap(docker)
            return real(client, image, name, volumes)

        with (
            patch.object(orchestrator, "_create_restore_helper", swap_before_put_back),
            pytest.raises(orchestrator.RestoreError),
        ):
            orchestrator.restore_state("mysterium", _archives(), TestTheRestoreSequence.EXTRA_DEPLOY)
        helper = orchestrator._restore_helper("mysterium")
        assert [m["Name"] for m in helper.attrs["Mounts"]] == ["mysterium-data"]
        # The owner is never asked to approve the other client's volume as what the restore wrote.
        with pytest.raises(orchestrator.CriticalVolumeError) as refusal:
            orchestrator.remove_service("mysterium", delete_volumes=True, only_if_restore_unfinished=True)
        assert [b["volume"] for b in refusal.value.blocked] == ["mysterium-extra"]
        assert "mysterium-data" not in refusal.value.critical_set
        result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert result["deleted_volumes"] == ["mysterium-extra"]
        # Kept as another client's, and the answer says so rather than reading as a full delete.
        assert result["failed_volumes"] == ["mysterium-data"] and result["replaced_volumes"] == ["mysterium-data"]
        assert docker.volume_map["mysterium-data"].attrs["Labels"] == {"theirs": "1"}
        assert ("volume", "mysterium-data") not in docker.removed

    def test_control_the_helpers_own_volume_goes_with_the_owners_remove(self, docker):
        docker.corrupt_put = True
        with pytest.raises(orchestrator.RestoreError):
            orchestrator.restore_state("mysterium", _archives(), TestTheRestoreSequence.EXTRA_DEPLOY)
        result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert sorted(result["deleted_volumes"]) == ["mysterium-data", "mysterium-extra"]


class TestTheLastReadBeforeTheDelete:
    """The owner's delete reads each volume fresh right before the remove call.

    A volume replaced after the first reads (the review's CreatedAt, the
    record's nonce) and before that last read is kept. The instant between the
    last read and Docker's delete by name stays open (docs/backup.md), so no
    test claims it.
    """

    def _leftover(self, docker):
        _recorded(docker)
        helper = FakeContainer(
            docker,
            "cashpilot-mysterium.restore",
            {"/restore": "mysterium-data"},
            {orchestrator.LABEL_RESTORE: "helper"},
        )
        helper.attrs["Mounts"] = [{"Type": "volume", "Name": "mysterium-data", "Destination": "/restore"}]
        docker.container_map[helper.name] = helper

    def test_a_replacement_with_the_same_time_made_after_the_first_reads_is_kept(self, docker):
        self._leftover(docker)
        real_remove = FakeContainer.remove

        def remove_then_swap(container, force=False):
            real_remove(container, force)
            if container.name == "cashpilot-mysterium.restore":
                _swap(docker, same_time=True)

        with patch.object(FakeContainer, "remove", remove_then_swap):
            result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert result["deleted_volumes"] == [] and result["failed_volumes"] == ["mysterium-data"]
        # Kept as another client's, which a Remove again cannot change: the dashboard says so.
        assert result["replaced_volumes"] == ["mysterium-data"]
        assert docker.volume_map["mysterium-data"].attrs["Labels"] == {"theirs": "1"}
        # Not the restore's, so no helper is put back over it, and the restore's record goes.
        assert orchestrator._restore_helper("mysterium") is None
        assert orchestrator.restore_marks() == set()

    def test_control_the_restores_own_volume_is_deleted(self, docker):
        self._leftover(docker)
        result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert result["deleted_volumes"] == ["mysterium-data"] and docker.volume_map == {}
        assert orchestrator.restore_marks() == set()


# ---------------------------------------------------------------------------
# Round 18: a replacement service mounting a replacement volume, a volume made
# this second, and a delete that holds no worker-wide lock
# ---------------------------------------------------------------------------


#: The worker's clock in the tests that judge a volume's age: a slow runner
#: must not age a volume the test made "this second".
_NOW = datetime(2026, 11, 15, 10, 0, 0, tzinfo=UTC)


def _docker_time(seconds_ago: float = 0) -> str:
    """A CreatedAt as Docker gives it, ``seconds_ago`` before the frozen clock: RFC 3339, to the second."""
    return (_NOW - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def frozen_clock():
    """Freeze the clock orchestrator._volume_created reads; ``clock["now"]`` moves it."""
    clock = {"now": _NOW}

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"] if tz is not None else clock["now"].replace(tzinfo=None)

    with patch.object(orchestrator, "datetime", Frozen):
        yield clock


class TestAReplacementServiceOverAReplacementVolumeIsNotTheRestores:
    def test_the_owners_remove_of_the_unfinished_restore_removes_nothing(self, docker):
        _recorded(docker)
        # Another client replaces the restore's volume and deploys the service over it.
        _swap(docker)
        docker.deploy_raw(slug="mysterium", volumes=MYSTERIUM_DEPLOY["volumes"], start=False)
        with pytest.raises(orchestrator.RestoreClearedError, match="mysterium-data"):
            _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert "cashpilot-mysterium" in docker.container_map and docker.removed == []
        assert docker.volume_map["mysterium-data"].attrs["Labels"] == {"theirs": "1"}
        assert orchestrator.restore_marks() == {"mysterium"}

    def test_control_the_restores_own_volume_under_the_service_goes(self, docker):
        _recorded(docker)
        docker.deploy_raw(slug="mysterium", volumes=MYSTERIUM_DEPLOY["volumes"], start=False)
        result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert result["deleted_volumes"] == ["mysterium-data"] and docker.volume_map == {}
        assert orchestrator.restore_marks() == set()


class TestAVolumeMadeThisSecondBindsNoReview:
    """Docker gives CreatedAt to the second; a record with no nonce leaves only that time to tell volumes apart."""

    def _legacy_record(self, docker, made: str) -> None:
        """An older worker's record and helper: the volume's name with no nonce."""
        Path(orchestrator.RESTORE_MARKER).write_text("mysterium mysterium-data\n", encoding="utf-8")
        docker.volumes.create("mysterium-data").attrs["CreatedAt"] = made
        helper = FakeContainer(
            docker,
            "cashpilot-mysterium.restore",
            {"/restore": "mysterium-data"},
            {orchestrator.LABEL_RESTORE: "helper"},
        )
        helper.attrs["Mounts"] = [{"Type": "volume", "Name": "mysterium-data", "Destination": "/restore"}]
        docker.container_map[helper.name] = helper

    def test_a_replacement_made_in_the_reviewed_second_is_not_deleted(self, docker, frozen_clock):
        self._legacy_record(docker, _docker_time())
        with pytest.raises(orchestrator.CriticalVolumeError) as refusal:
            orchestrator.remove_service("mysterium", delete_volumes=True, only_if_restore_unfinished=True)
        _swap(docker, same_time=True)
        with pytest.raises(orchestrator.CriticalVolumeError, match="last 2 seconds"):
            orchestrator.remove_service(
                "mysterium",
                delete_volumes=True,
                only_if_restore_unfinished=True,
                allow_delete_critical=True,
                approved_critical=refusal.value.critical_set,
            )
        assert docker.volume_map["mysterium-data"].attrs["Labels"] == {"theirs": "1"} and docker.removed == []
        assert orchestrator.restore_marks() == {"mysterium"}

    def test_control_a_volume_made_a_minute_ago_goes(self, docker, frozen_clock):
        self._legacy_record(docker, _docker_time(60))
        result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert result["deleted_volumes"] == ["mysterium-data"] and docker.volume_map == {}

    def test_the_owners_remove_again_after_the_refusal_reviews_afresh_and_goes(self, docker, frozen_clock):
        """The "?" refusal never sticks: the dashboard's next Remove starts with a new review, never the old approval."""
        self._legacy_record(docker, _docker_time())
        with pytest.raises(orchestrator.CriticalVolumeError) as young:
            orchestrator.remove_service("mysterium", delete_volumes=True, only_if_restore_unfinished=True)
        assert young.value.critical_set == "mysterium-data@?"
        with pytest.raises(orchestrator.CriticalVolumeError, match="last 2 seconds"):
            orchestrator.remove_service(
                "mysterium",
                delete_volumes=True,
                only_if_restore_unfinished=True,
                allow_delete_critical=True,
                approved_critical=young.value.critical_set,
            )
        frozen_clock["now"] += timedelta(seconds=3)
        result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert result["deleted_volumes"] == ["mysterium-data"] and docker.volume_map == {}
        assert orchestrator.restore_marks() == set()


class TestTheDeleteHoldsNoWorkerWideLock:
    def test_a_volume_delete_leaves_other_slugs_and_the_heartbeat_free(self, docker):
        """Docker's delete of a big volume can take a minute: every other slug's claim and release need the lock."""
        _recorded(docker)
        locked_while_deleting = []
        real_remove = FakeVolume.remove

        def remove(volume, force=False):
            locked_while_deleting.append(orchestrator._SLUG_WORK_LOCK.locked())
            return real_remove(volume, force)

        with patch.object(FakeVolume, "remove", remove):
            result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert result["deleted_volumes"] == ["mysterium-data"] and locked_while_deleting == [False]


class TestALegacyRecordWhoseHelperIsLost:
    """A record from an older worker names the volume with no nonce: only the helper said it was the restore's."""

    def _first_remove_loses_the_helper(self, docker) -> dict[str, Any]:
        """The helper goes, the volume delete fails, and the helper cannot come back."""
        TestAVolumeMadeThisSecondBindsNoReview()._legacy_record(docker, "2026-11-14T10:00:00Z")
        with (
            patch.object(FakeVolume, "remove", side_effect=requests.exceptions.ReadTimeout("proxy timed out")),
            patch.object(orchestrator, "_create_restore_helper", side_effect=RuntimeError("daemon gone")),
        ):
            result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert result["failed_volumes"] == ["mysterium-data"] and docker.container_map == {}
        assert orchestrator.restore_marks() == {"mysterium"}
        return result

    def test_the_first_answer_already_names_the_volume_to_clean_up(self, docker):
        """With its helper lost, no Remove can delete it again: the first answer must not send the owner back."""
        result = self._first_remove_loses_the_helper(docker)
        assert result["unverified_volumes"] == ["mysterium-data"] and result["failed_volumes"] == ["mysterium-data"]

    def test_a_helper_with_no_record_names_the_volume_in_the_first_answer_too(self, docker):
        """A helper from a worker that kept no record: the hold written before it goes is the volume's only mark."""
        TestAVolumeMadeThisSecondBindsNoReview()._legacy_record(docker, "2026-11-14T10:00:00Z")
        Path(orchestrator.RESTORE_MARKER).unlink()
        with (
            patch.object(FakeVolume, "remove", side_effect=requests.exceptions.ReadTimeout("proxy timed out")),
            patch.object(orchestrator, "_create_restore_helper", side_effect=RuntimeError("daemon gone")),
        ):
            result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert docker.container_map == {} and orchestrator.restore_marks() == {"mysterium"}
        assert result["unverified_volumes"] == ["mysterium-data"] and result["failed_volumes"] == ["mysterium-data"]

    def test_control_a_helper_with_no_record_whose_volume_goes_ends_the_hold(self, docker):
        TestAVolumeMadeThisSecondBindsNoReview()._legacy_record(docker, "2026-11-14T10:00:00Z")
        Path(orchestrator.RESTORE_MARKER).unlink()
        result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert result["deleted_volumes"] == ["mysterium-data"] and result["unverified_volumes"] == []
        assert orchestrator.restore_marks() == set()

    def test_control_a_helper_that_comes_back_lets_remove_try_again(self, docker):
        TestAVolumeMadeThisSecondBindsNoReview()._legacy_record(docker, "2026-11-14T10:00:00Z")
        with patch.object(FakeVolume, "remove", side_effect=requests.exceptions.ReadTimeout("proxy timed out")):
            result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert result["failed_volumes"] == ["mysterium-data"] and result["unverified_volumes"] == []
        assert "cashpilot-mysterium.restore" in docker.container_map
        result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert result["deleted_volumes"] == ["mysterium-data"] and orchestrator.restore_marks() == set()

    def test_the_retry_keeps_the_hold_and_names_the_volume_to_clean_up(self, docker):
        self._first_remove_loses_the_helper(docker)
        result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert "mysterium-data" in docker.volume_map and docker.removed == [
            ("container", "cashpilot-mysterium.restore")
        ]
        assert orchestrator.restore_marks() == {"mysterium"}
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not finish"):
            TestStartAndRemoveAroundARestore()._deploy(docker)
        assert result["deleted_volumes"] == [] and result["unverified_volumes"] == ["mysterium-data"]
        assert "mysterium-data" in result["failed_volumes"]

    def test_control_once_the_owner_deletes_the_volume_the_next_remove_ends_the_hold(self, docker):
        self._first_remove_loses_the_helper(docker)
        del docker.volume_map["mysterium-data"]
        result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert result["failed_volumes"] == [] and result["unverified_volumes"] == []
        assert orchestrator.restore_marks() == set()

    def test_a_volume_that_cannot_be_read_keeps_the_hold(self, docker):
        self._first_remove_loses_the_helper(docker)
        response = requests.Response()
        response.status_code = 500
        with patch.object(docker.volumes, "get", side_effect=APIError("daemon gone", response=response)):
            result = _owner_removes("mysterium", only_if_restore_unfinished=True)
        assert orchestrator.restore_marks() == {"mysterium"}
        # Not known to be there, so it is not named for the owner to delete
        # by hand: it is reported as unread, for a Remove again.
        assert result["unverified_volumes"] == []
        assert result["unread_volumes"] == ["mysterium-data"]
        assert "mysterium-data" in result["failed_volumes"]


def test_the_roadmap_never_lets_the_private_key_leave_the_owner():
    """Only the passphrase crosses to the worker. The private key of a key-sealed
    bundle never goes anywhere: the dashboard refuses such a file for that reason."""
    root = Path(__file__).resolve().parents[1]
    roadmap = " ".join((root / "docs" / "roadmap.md").read_text("utf-8").split())
    assert "The private key never leaves the owner's machine." in roadmap
    assert "never goes through the" in (root / "app" / "main.py").read_text("utf-8")


def test_backup_doc_does_not_deny_the_passphrase_trip_it_describes():
    """The passphrase is key material and does cross UI to worker, so the doc's
    "never crosses" claim must carve it out instead of contradicting itself."""
    root = Path(__file__).resolve().parents[1]
    doc = " ".join((root / "docs" / "backup.md").read_text("utf-8").split())
    assert ". Plaintext key material never crosses" not in doc
    assert "Apart from the passphrase below, plaintext key material never crosses the fleet network" in doc
    assert "A passphrase is the one secret that crosses" in doc


def test_backup_doc_says_the_bundle_header_is_readable():
    """encrypt() writes the header as plain JSON (authenticated, not encrypted),
    so the doc must not call the whole bundle ciphertext."""
    root = Path(__file__).resolve().parents[1]
    doc = " ".join((root / "docs" / "backup.md").read_text("utf-8").split())
    assert "The bundle is ciphertext" not in doc
    assert "The bundle header is readable JSON, authenticated but not encrypted" in doc
    assert "header_bytes = json.dumps(header" in (root / "app" / "state_backup.py").read_text("utf-8")
