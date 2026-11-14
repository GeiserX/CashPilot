"""The payouts page's backup warning: amber advice, confirmations, re-arming, export.

Before this, the payouts page showed a red "At risk" card for every running
service with irreplaceable state (Mysterium, ProxyBase Markets, Anyone, Storj,
Sia hostd), forever, with no way to say the state is already backed up, and the
encrypted export in app/state_backup.py was reachable from no screen.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import subprocess
import sys
import tarfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main, orchestrator, payout_registry
from app import state_backup as sb
from app.constants import LABEL_STATE_CREATED

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
PASSPHRASE = "correct horse battery staple"
# A value that must never come back. Built at runtime: a literal next to
# "passphrase" reads to a secret scanner as a leaked password.
SENTINEL = "-".join(["never", "echo", "this", "value"])
EXPORT = {"worker_id": 1, "passphrase": PASSPHRASE, "passphrase_repeat": PASSPHRASE}


def _sql(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _worker(wid, name, containers, *, features=("instances", "isolation_check", "state_backup")):
    return {
        "id": wid,
        "name": name,
        "status": "online",
        "system_info": json.dumps({"docker_available": True, "features": list(features)}),
        "containers": json.dumps(containers),
        "apps": "[]",
    }


def _c(slug, state_id=None):
    out = {"slug": slug, "status": "running"}
    if state_id:
        out["state_id"] = state_id
    return out


# ---------------------------------------------------------------------------
# One box's backup state
# ---------------------------------------------------------------------------

BOX = [{"worker_id": 1, "name": "box-a", "online": True, "android": False}]


def _status(confirmed=None, live="aaa", *, servers=BOX):
    confirmations = {("mysterium", 1): confirmed} if confirmed else {}
    current = {(1, "mysterium"): live} if live else {}
    return payout_registry.backup_status("mysterium", servers, confirmations, current, now=NOW)


class TestBackupStatus:
    def test_nothing_confirmed_is_not_confirmed(self):
        out = _status()
        assert out["confirmed"] is False
        assert out["boxes"][0]["state"] == "none"

    def test_a_confirmation_on_the_same_volume_holds(self):
        out = _status({"state_id": "aaa", "confirmed_at": _sql(NOW - timedelta(days=10)), "method": "manual"})
        assert out["confirmed"] is True
        assert out["boxes"][0]["state"] == "confirmed"
        assert out["boxes"][0]["tracks_changes"] is True

    def test_a_new_volume_voids_it(self):
        out = _status({"state_id": "aaa", "confirmed_at": _sql(NOW - timedelta(days=1))}, live="bbb")
        assert out["confirmed"] is False
        assert out["boxes"][0]["state"] == "changed"

    def test_six_months_voids_it(self):
        out = _status({"state_id": "aaa", "confirmed_at": _sql(NOW - timedelta(days=200))})
        assert out["boxes"][0]["state"] == "expired"

    def test_control_five_months_does_not(self):
        out = _status({"state_id": "aaa", "confirmed_at": _sql(NOW - timedelta(days=150))})
        assert out["boxes"][0]["state"] == "confirmed"

    def test_an_old_worker_is_judged_on_age_alone_and_says_so(self):
        out = _status({"state_id": None, "confirmed_at": _sql(NOW - timedelta(days=10))}, live=None)
        assert out["boxes"][0]["state"] == "confirmed"
        assert out["boxes"][0]["tracks_changes"] is False

    def test_a_confirmation_without_a_fingerprint_is_asked_again_once_the_box_has_one(self):
        out = _status({"state_id": None, "confirmed_at": _sql(NOW - timedelta(days=10))}, live="aaa")
        assert out["boxes"][0]["state"] == "recheck"
        assert out["confirmed"] is False

    def test_a_new_box_running_the_service_needs_its_own_backup(self):
        servers = BOX + [{"worker_id": 2, "name": "box-b", "online": True, "android": False}]
        out = _status({"state_id": "aaa", "confirmed_at": _sql(NOW - timedelta(days=1))}, servers=servers)
        assert [b["state"] for b in out["boxes"]] == ["confirmed", "none"]
        assert out["confirmed"] is False

    def test_no_box_is_never_confirmed(self):
        assert _status(servers=[])["confirmed"] is False


class TestStateIds:
    def test_read_from_each_workers_heartbeat(self):
        workers = [_worker(1, "w", [_c("mysterium", "abc"), _c("honeygain")])]
        assert payout_registry.state_ids(workers) == {(1, "mysterium"): "abc"}

    def test_an_already_parsed_container_list_works_too(self):
        assert payout_registry.state_ids([{"id": 3, "containers": [_c("storj", "x")]}]) == {(3, "storj"): "x"}


# ---------------------------------------------------------------------------
# The registry and its counter
# ---------------------------------------------------------------------------


def _registry(workers, confirmations):
    with (
        patch.object(payout_registry.database, "get_deployments", AsyncMock(return_value=[])),
        patch.object(payout_registry.database, "list_workers", AsyncMock(return_value=workers)),
        patch.object(payout_registry.database, "get_deployment_spec", AsyncMock(return_value=None)),
        # create=True so this runs, and fails on its assertion, against code
        # that has no confirmations at all.
        patch.object(payout_registry.database, "get_state_backups", AsyncMock(return_value=confirmations), create=True),
    ):
        return asyncio.run(payout_registry.registry())


def _row(result, slug):
    return next(r for r in result["entries"] if r["slug"] == slug)


class TestTheCounter:
    WORKERS = [_worker(1, "box-a", [_c("mysterium", "m1"), _c("proxybase-xyz", "p1"), _c("honeygain")])]

    def test_unconfirmed_services_are_counted(self):
        result = _registry(self.WORKERS, {})
        assert result["summary"]["holding_irreplaceable_state"] == 2
        assert _row(result, "mysterium")["backup"]["boxes"][0]["state"] == "none"
        assert _row(result, "honeygain")["backup"] is None

    def test_a_confirmed_service_is_not_counted(self):
        """Red on the old code: the counter ignored confirmations entirely."""
        today = _sql(datetime.now(UTC))
        confirmations = {("mysterium", 1): {"state_id": "m1", "confirmed_at": today, "method": "manual"}}
        result = _registry(self.WORKERS, confirmations)
        assert result["summary"]["holding_irreplaceable_state"] == 1
        assert _row(result, "mysterium")["backup"]["confirmed"] is True

    def test_a_redeploy_onto_a_new_volume_counts_again(self):
        today = _sql(datetime.now(UTC))
        confirmations = {("mysterium", 1): {"state_id": "old-volume", "confirmed_at": today, "method": "export"}}
        result = _registry(self.WORKERS, confirmations)
        assert result["summary"]["holding_irreplaceable_state"] == 2


# ---------------------------------------------------------------------------
# The worker's fingerprint of where the state lives
# ---------------------------------------------------------------------------


def _container(mounts, cid="c1"):
    return SimpleNamespace(id=cid, attrs={"Mounts": mounts})


def _client(created):
    return SimpleNamespace(
        volumes=SimpleNamespace(get=lambda name: SimpleNamespace(attrs={"CreatedAt": created[name]}))
    )


VOLUME = [{"Type": "volume", "Name": "mysterium-data", "Destination": "/var/lib/mysterium-node"}]
TARGETS = {"/var/lib/mysterium-node": "identity"}


class TestStateId:
    def test_a_recreated_container_over_the_same_volume_keeps_it(self):
        """Every image update recreates the container; that is not a new identity."""
        client = _client({"mysterium-data": "2026-03-26T11:41:03+01:00"})
        a = orchestrator.state_id(_container(VOLUME, "old"), TARGETS, client)
        b = orchestrator.state_id(_container(VOLUME, "new"), TARGETS, client)
        assert a and a == b

    def test_a_volume_removed_and_made_again_changes_it(self):
        a = orchestrator.state_id(_container(VOLUME), TARGETS, _client({"mysterium-data": "2026-03-26T11:41:03Z"}))
        b = orchestrator.state_id(_container(VOLUME), TARGETS, _client({"mysterium-data": "2026-10-30T13:00:36Z"}))
        assert a != b

    def test_a_volume_the_owner_migration_made_again_keeps_it(self):
        """The migration copies the data onto a new volume of the same name and
        keeps the old creation time in a label; the fingerprint reads that."""
        before = orchestrator.state_id(_container(VOLUME), TARGETS, _client({"mysterium-data": "2026-03-26T11:41:03Z"}))
        migrated = SimpleNamespace(
            volumes=SimpleNamespace(
                get=lambda name: SimpleNamespace(
                    attrs={
                        "CreatedAt": "2026-11-07T13:44:20Z",
                        "Labels": {LABEL_STATE_CREATED: "2026-03-26T11:41:03Z", "cashpilot.deployed-by": "worker"},
                    }
                )
            )
        )
        assert orchestrator.state_id(_container(VOLUME), TARGETS, migrated) == before

    def test_a_bind_mount_moved_to_another_folder_changes_it(self):
        mount = {"Type": "bind", "Source": "/mnt/a", "Destination": "/app/identity"}
        a = orchestrator.state_id(_container([mount]), {"/app/identity": "x"})
        b = orchestrator.state_id(_container([{**mount, "Source": "/mnt/b"}]), {"/app/identity": "x"})
        assert a != b

    def test_state_in_the_container_itself_follows_the_container(self):
        a = orchestrator.state_id(_container([], "c1"), {"/data": "x"})
        b = orchestrator.state_id(_container([], "c2"), {"/data": "x"})
        assert a != b

    def test_an_unreadable_volume_is_unknown_not_a_change(self):
        broken = SimpleNamespace(volumes=SimpleNamespace(get=MagicMock(side_effect=RuntimeError("gone"))))
        assert orchestrator.state_id(_container(VOLUME), TARGETS, broken) is None

    def test_nothing_critical_has_no_fingerprint(self):
        assert orchestrator.state_id(_container(VOLUME), {}) is None

    def test_the_heartbeat_entry_carries_it_only_for_critical_services(self):
        client = _client({"mysterium-data": "t"})
        assert "state_id" in orchestrator._state_id_entry(_container(VOLUME), "mysterium", client)
        assert orchestrator._state_id_entry(_container(VOLUME), "honeygain", client) == {}

    def test_the_worker_advertises_the_export_protocol(self):
        src = (ROOT / "app" / "worker_api.py").read_text(encoding="utf-8")
        assert '"state_backup"' in src


class TestTheSizeCap:
    def test_the_cap_fits_an_identity_not_a_data_folder(self):
        # The bundle is held several times over on the worker and the UI.
        assert orchestrator.MAX_BACKUP_BYTES == 64 * 1024 * 1024

    def test_a_storage_folder_is_refused_and_the_node_unpaused(self):
        container = MagicMock(status="running")
        big = [b"x" * (1024 * 1024)] * 3
        container.get_archive.return_value = (iter(big), {})
        with (
            patch.object(orchestrator, "_critical_volume_targets", return_value={"/app/config": "x"}),
            patch.object(orchestrator, "_find_container", return_value=container),
            patch.object(orchestrator, "MAX_BACKUP_BYTES", 2 * 1024 * 1024),
            pytest.raises(ValueError, match="too big to export here.*at the disk level"),
        ):
            orchestrator.read_critical_state("storj")
        container.unpause.assert_called_once()

    def test_the_archive_stream_is_closed_before_the_unpause(self):
        """An open archive stream holds the container, so Docker never answers
        the unpause and the earner stays paused. The cap's raise kept the stream
        alive through its traceback; it must be closed first."""
        order: list[str] = []

        def stream():
            try:
                while True:
                    yield b"x" * (1024 * 1024)
            finally:
                order.append("closed")

        container = MagicMock(status="running")
        container.get_archive.return_value = (stream(), {})
        container.unpause.side_effect = lambda: order.append("unpaused")
        with (
            patch.object(orchestrator, "_critical_volume_targets", return_value={"/app/config": "x"}),
            patch.object(orchestrator, "_find_container", return_value=container),
            patch.object(orchestrator, "MAX_BACKUP_BYTES", 2 * 1024 * 1024),
            pytest.raises(ValueError, match="too big to export here"),
        ):
            orchestrator.read_critical_state("storj")
        assert order == ["closed", "unpaused"]


# ---------------------------------------------------------------------------
# The confirmations table
# ---------------------------------------------------------------------------


@pytest.mark.real_state_backups
class TestTheTable:
    @pytest.mark.asyncio
    async def test_confirm_replace_and_clear(self, tmp_path, monkeypatch):
        from app import database

        monkeypatch.setattr(database, "DB_DIR", tmp_path)
        monkeypatch.setattr(database, "DB_PATH", tmp_path / "cashpilot.db")
        await database.init_db()
        try:
            await database.confirm_state_backup("mysterium", 1, None, "manual")
            await database.confirm_state_backup("mysterium", 1, "abc", "export")
            rows = await database.get_state_backups()
            assert list(rows) == [("mysterium", 1)]
            assert rows[("mysterium", 1)]["state_id"] == "abc"
            assert rows[("mysterium", 1)]["method"] == "export"
            await database.clear_state_backup("mysterium", 1)
            assert await database.get_state_backups() == {}
        finally:
            await database.close_shared()


# ---------------------------------------------------------------------------
# The UI routes
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _noop_lifespan(a):
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main.app.router, "lifespan_context", _noop_lifespan)
    with TestClient(main.app, raise_server_exceptions=False) as c:
        yield c


def _as(role):
    return patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "x", "r": role})


def _fleet(features=("instances", "isolation_check", "state_backup")):
    workers = [_worker(1, "box-a", [_c("mysterium", "m1")], features=features)]
    return (
        patch.object(main.database, "list_workers", AsyncMock(return_value=workers)),
        patch.object(main.database, "get_worker", AsyncMock(return_value=workers[0])),
    )


class TestTheRoutes:
    def test_confirm_records_the_box_and_its_fingerprint(self, client):
        confirm = AsyncMock()
        w, g = _fleet()
        with _as("owner"), w, g, patch.object(main.database, "confirm_state_backup", confirm):
            resp = client.post("/api/payout-registry/mysterium/backup-confirm", json={"worker_id": 1})
        assert resp.status_code == 200, resp.text
        confirm.assert_awaited_once_with("mysterium", 1, "m1", "manual")

    def test_a_box_that_does_not_run_it_is_refused(self, client):
        w, g = _fleet()
        with _as("owner"), w, g, patch.object(main.database, "confirm_state_backup", AsyncMock()) as confirm:
            resp = client.post("/api/payout-registry/mysterium/backup-confirm", json={"worker_id": 9})
        assert resp.status_code == 404
        confirm.assert_not_awaited()

    def test_a_service_with_nothing_irreplaceable_is_refused(self, client):
        w, g = _fleet()
        with _as("owner"), w, g:
            resp = client.post("/api/payout-registry/honeygain/backup-confirm", json={"worker_id": 1})
        assert resp.status_code == 404

    @pytest.mark.parametrize("role", ["writer", "viewer"])
    def test_owner_only(self, client, role):
        w, g = _fleet()
        with _as(role), w, g:
            for path in ("backup-confirm", "backup-export"):
                resp = client.post(f"/api/payout-registry/mysterium/{path}", json={"worker_id": 1})
                assert resp.status_code == 403, path
            assert client.delete("/api/payout-registry/mysterium/backup-confirm?worker_id=1").status_code == 403

    def test_undo_clears_it(self, client):
        clear = AsyncMock()
        with _as("owner"), patch.object(main.database, "clear_state_backup", clear):
            resp = client.delete("/api/payout-registry/mysterium/backup-confirm?worker_id=1")
        assert resp.status_code == 200
        clear.assert_awaited_once_with("mysterium", 1)

    def test_an_old_worker_is_told_to_update(self, client):
        w, g = _fleet(features=("instances", "isolation_check"))
        proxy = AsyncMock()
        with _as("owner"), w, g, patch.object(main, "_proxy_to_worker", proxy):
            resp = client.post("/api/payout-registry/mysterium/backup-export", json=EXPORT)
        assert resp.status_code == 409
        assert "Update the worker" in resp.json()["detail"]
        proxy.assert_not_awaited()

    def test_a_worker_without_the_route_is_told_to_update(self, client):
        w, g = _fleet()
        proxy = AsyncMock(side_effect=HTTPException(status_code=404, detail="x"))
        with _as("owner"), w, g, patch.object(main, "_proxy_to_worker", proxy):
            resp = client.post("/api/payout-registry/mysterium/backup-export", json=EXPORT)
        assert resp.status_code == 409
        assert "Update the worker" in resp.json()["detail"]

    def test_export_returns_the_bundle_and_confirms_the_backup(self, client):
        bundle = sb.seal(b"identity", passphrase=PASSPHRASE)
        answer = {
            "bundle_b64": base64.b64encode(bundle).decode(),
            "bytes": len(bundle),
            "targets": ["/x"],
            "state_id": "m2",
        }
        confirm = AsyncMock()
        w, g = _fleet()
        with (
            _as("owner"),
            w,
            g,
            patch.object(main, "_proxy_to_worker", AsyncMock(return_value=answer)) as proxy,
            patch.object(main.database, "confirm_state_backup", confirm),
        ):
            resp = client.post("/api/payout-registry/mysterium/backup-export", json=EXPORT)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["filename"].startswith("cashpilot-mysterium-box-a-") and data["filename"].endswith(".cpbackup")
        assert sb.open_bundle(base64.b64decode(data["bundle_b64"]), passphrase=PASSPHRASE) == b"identity"
        # The worker's own fingerprint of what it read wins over the heartbeat's.
        confirm.assert_awaited_once_with("mysterium", 1, "m2", "export")
        # Only the worker's backup route is called, with only the secret given.
        args, kwargs = proxy.await_args
        assert args[2] == "/api/containers/mysterium/backup"
        assert kwargs["json"] == {"passphrase": PASSPHRASE}

    def test_a_failed_export_confirms_nothing(self, client):
        w, g = _fleet()
        confirm = AsyncMock()
        with (
            _as("owner"),
            w,
            g,
            patch.object(main, "_proxy_to_worker", AsyncMock(side_effect=HTTPException(status_code=500, detail="x"))),
            patch.object(main.database, "confirm_state_backup", confirm),
        ):
            resp = client.post("/api/payout-registry/mysterium/backup-export", json=EXPORT)
        assert resp.status_code == 500
        confirm.assert_not_awaited()

    def test_a_mistyped_repeat_exports_and_confirms_nothing(self, client):
        """A typo would give a file nobody can open, marked as a confirmed backup."""
        w, g = _fleet()
        proxy, confirm = AsyncMock(), AsyncMock()
        body = dict(EXPORT, passphrase_repeat=PASSPHRASE + "x")
        with (
            _as("owner"),
            w,
            g,
            patch.object(main, "_proxy_to_worker", proxy),
            patch.object(main.database, "confirm_state_backup", confirm),
        ):
            resp = client.post("/api/payout-registry/mysterium/backup-export", json=body)
        assert resp.status_code == 400
        assert "differ" in resp.json()["detail"]
        assert PASSPHRASE not in resp.text
        proxy.assert_not_awaited()
        confirm.assert_not_awaited()

    def test_the_repeat_is_not_sent_to_the_worker(self, client):
        answer = {"bundle_b64": base64.b64encode(b"x").decode(), "state_id": "m2"}
        w, g = _fleet()
        with (
            _as("owner"),
            w,
            g,
            patch.object(main, "_proxy_to_worker", AsyncMock(return_value=answer)) as proxy,
            patch.object(main.database, "confirm_state_backup", AsyncMock()),
        ):
            resp = client.post("/api/payout-registry/mysterium/backup-export", json=EXPORT)
        assert resp.status_code == 200, resp.text
        assert proxy.await_args.kwargs["json"] == {"passphrase": PASSPHRASE}

    @pytest.mark.parametrize(
        "body",
        [
            {"worker_id": 1},
            {"worker_id": 1, "passphrase": PASSPHRASE, "recipient_public_key": "ab" * 32},
            {"worker_id": "1", "passphrase": PASSPHRASE, "passphrase_repeat": PASSPHRASE},
            {"worker_id": 1, "passphrase": [SENTINEL]},
            {"worker_id": 1, "passphrase": PASSPHRASE},
            {"worker_id": 1, "passphrase": PASSPHRASE, "passphrase_repeat": SENTINEL},
        ],
    )
    def test_bad_input_never_echoes_the_secret(self, client, body, caplog):
        w, g = _fleet()
        with _as("owner"), w, g, caplog.at_level(logging.DEBUG):
            resp = client.post("/api/payout-registry/mysterium/backup-export", json=body)
        assert resp.status_code == 400
        for secret in (PASSPHRASE, SENTINEL):
            assert secret not in resp.text
            assert secret not in caplog.text


# ---------------------------------------------------------------------------
# End to end: a fake volume, sealed, opened with the CLI, compared byte for byte
# ---------------------------------------------------------------------------


def _docker_archive(top: str, files: dict[str, bytes]) -> bytes:
    """What Docker's get_archive returns for a mount: its folder as a tar."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        d = tarfile.TarInfo(top)
        d.type, d.mode, d.uid, d.gid = tarfile.DIRTYPE, 0o700, 1000, 1000
        tar.addfile(d)
        for name, data in files.items():
            info = tarfile.TarInfo(f"{top}/{name}")
            info.size, info.mode, info.uid, info.gid = len(data), 0o600, 1000, 1000
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


FILES_A = {"keystore/UTC--key": b'{"crypto": "not a real key"}', "node.db": os.urandom(4096)}
FILES_B = {"wallet.json": b'{"address": "0xabc"}'}


def _fake_volume_bundle(**secret) -> bytes:
    """Run the worker's real read path over a fake container with two mounts."""
    archives = {
        "/home/proxybase/.proxybase": _docker_archive(".proxybase", FILES_B),
        "/var/lib/mysterium-node": _docker_archive("mysterium-node", FILES_A),
    }
    container = MagicMock(status="running")
    container.get_archive.side_effect = lambda target: (iter([archives[target]]), {})
    with (
        patch.object(orchestrator, "_critical_volume_targets", return_value={t: "x" for t in archives}),
        patch.object(orchestrator, "_find_container", return_value=container),
    ):
        payload, targets = orchestrator.read_critical_state("fake")
    return sb.seal(payload, metadata={"slug": "fake", "worker": "w", "targets": targets}, **secret)


def _decrypt(bundle: bytes, secret: str, tmp_path: Path) -> subprocess.CompletedProcess:
    path = tmp_path / "x.cpbackup"
    path.write_bytes(bundle)
    return subprocess.run(
        [
            sys.executable,
            "-I",
            str(ROOT / "app" / "state_backup.py"),
            "decrypt",
            str(path),
            "--out",
            str(tmp_path / "out"),
        ],
        input=secret + "\n",
        capture_output=True,
        text=True,
        timeout=120,
    )


def _members(path: Path) -> dict[str, tuple[bytes | None, int, int, int]]:
    with tarfile.open(path) as tar:
        return {
            m.name: (tar.extractfile(m).read() if m.isfile() else None, m.mode, m.uid, m.gid)  # type: ignore[union-attr]
            for m in tar
        }


class TestEndToEnd:
    def _check_restored(self, out: Path):
        a, b = _members(out / "mysterium-node.tar"), _members(out / ".proxybase.tar")
        for name, data in FILES_A.items():
            assert a[f"mysterium-node/{name}"] == (data, 0o600, 1000, 1000)
        assert b[".proxybase/wallet.json"] == (FILES_B["wallet.json"], 0o600, 1000, 1000)
        assert a["mysterium-node"][1:] == (0o700, 1000, 1000)

    def test_passphrase(self, tmp_path):
        result = _decrypt(_fake_volume_bundle(passphrase=PASSPHRASE), PASSPHRASE, tmp_path)
        assert result.returncode == 0, result.stderr
        assert "checksum verified" in result.stdout
        assert "restores /var/lib/mysterium-node" in result.stdout
        self._check_restored(tmp_path / "out")
        assert PASSPHRASE not in result.stdout + result.stderr

    def test_recipient_key(self, tmp_path):
        keygen = subprocess.run(
            [sys.executable, "-I", str(ROOT / "app" / "state_backup.py"), "keygen"],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = dict(line.split(": ", 1) for line in keygen.stdout.strip().splitlines())
        private = next(v for k, v in lines.items() if k.startswith("private"))
        public = next(v for k, v in lines.items() if k.startswith("public"))
        result = _decrypt(_fake_volume_bundle(recipient_public_key=public), private, tmp_path)
        assert result.returncode == 0, result.stderr
        self._check_restored(tmp_path / "out")

    def test_a_tampered_bundle_fails(self, tmp_path):
        bundle = bytearray(_fake_volume_bundle(passphrase=PASSPHRASE))
        bundle[-20] ^= 0x01
        result = _decrypt(bytes(bundle), PASSPHRASE, tmp_path)
        assert result.returncode == 1
        assert "altered" in result.stderr
        assert not (tmp_path / "out").exists()

    def test_a_wrong_passphrase_fails_without_echoing_it(self, tmp_path):
        result = _decrypt(_fake_volume_bundle(passphrase=PASSPHRASE), "not the passphrase", tmp_path)
        assert result.returncode == 1
        assert "not the passphrase" not in result.stdout + result.stderr

    def test_the_concatenated_payload_splits_back_into_the_original_archives(self):
        """The bytes inside each restored archive are the volume's bytes."""
        payload = _docker_archive("a", {"f": b"1"}) + _docker_archive("b", {"g": b"2"})
        parts = sb.split_archives(payload)
        assert sorted(parts) == ["a", "b"]
        with tarfile.open(fileobj=io.BytesIO(parts["b"])) as tar:
            assert tar.extractfile("b/g").read() == b"2"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# The restore refuses entries that could land outside their folder
# ---------------------------------------------------------------------------


def _tar(*members: tarfile.TarInfo) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for m in members:
            tar.addfile(m, io.BytesIO(b"x" * m.size) if m.isfile() else None)
    return buf.getvalue()


def _entry(name: str, kind: bytes = tarfile.REGTYPE, link: str = "") -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type, info.linkname = kind, link
    info.size = 1 if kind == tarfile.REGTYPE else 0
    return info


def _sparse(name: str, real_size: int) -> bytes:
    """A GNU sparse member: 512 stored bytes that unpack to ``real_size`` bytes.

    Built by hand because tarfile cannot write one. The single map entry puts
    the stored block at the end of the file, so the rest unpacks as zeros.
    """
    info = tarfile.TarInfo(name)
    info.type, info.size = tarfile.GNUTYPE_SPARSE, 512
    block = bytearray(info.tobuf(format=tarfile.GNU_FORMAT))
    block[386:398] = b"%011o\0" % (real_size - 512)  # first map entry: offset
    block[398:410] = b"%011o\0" % 512  # first map entry: length
    block[483:495] = b"%011o\0" % real_size  # the size it unpacks to
    block[148:156] = b" " * 8
    block[148:156] = b"%06o\0 " % sum(block)
    return bytes(block) + b"x" * 512 + b"\0" * 1024


def _pax(name: str, records: dict[str, str], *, global_records: dict[str, str] | None = None) -> bytes:
    """One regular file carrying the given PAX records, as Docker writes xattrs."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT, pax_headers=global_records) as tar:
        info = tarfile.TarInfo(name)
        info.size, info.pax_headers = 1, records
        tar.addfile(info, io.BytesIO(b"x"))
    return buf.getvalue()


def _pax_sparse(name: str, real_size: int) -> bytes:
    """The PAX form of a sparse file (GNU sparse 0.1 records), as GNU tar writes it."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        info = tarfile.TarInfo(name)
        info.size = 512
        info.pax_headers = {
            "GNU.sparse.size": str(real_size),
            "GNU.sparse.numblocks": "1",
            "GNU.sparse.map": f"{real_size - 512},512",
        }
        tar.addfile(info, io.BytesIO(b"x" * 512))
    return buf.getvalue()


def _pax_entries(*entries: tuple[str, bytes, dict[str, str]]) -> bytes:
    """Entries of the given types whose PAX records override the name or link,
    so a record may hold bytes the ustar fields cannot (a NUL, a bad time)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, kind, records in entries:
            info = tarfile.TarInfo(name)
            info.type, info.pax_headers = kind, records
            info.size = 1 if kind == tarfile.REGTYPE else 0
            tar.addfile(info, io.BytesIO(b"x") if kind == tarfile.REGTYPE else None)
    return buf.getvalue()


CAPABILITY = {"SCHILY.xattr.security.capability": "\x01\x00\x00\x02\x00\x10"}

UNSAFE = {
    "dot-dot": _tar(_entry("node"), _entry("node/../../etc/cron.d/x")),
    "absolute": _tar(_entry("/etc/passwd")),
    "through a symlink": _tar(_entry("node/link", tarfile.SYMTYPE, "/etc"), _entry("node/link/cron")),
    "relative symlink out": _tar(_entry("node/up", tarfile.SYMTYPE, "../../etc")),
    "path through a relative symlink": _tar(_entry("node/l", tarfile.SYMTYPE, "."), _entry("node/l/f")),
    "hardlink out": _tar(_entry("node/h", tarfile.LNKTYPE, "other/secret")),
    "char device": _tar(_entry("node/null", tarfile.CHRTYPE)),
    "block device": _tar(_entry("node/sda", tarfile.BLKTYPE)),
    "fifo": _tar(_entry("node/pipe", tarfile.FIFOTYPE)),
    "sparse": _sparse("node/big", 100 * 1024 * 1024),
    "pax sparse": _pax_sparse("node/big", 100 * 1024 * 1024),
    "file capability": _pax("node/run", CAPABILITY),
    "user xattr": _pax("node/f", {"SCHILY.xattr.user.x": "y"}),
    "acl": _pax("node/f", {"SCHILY.acl.access": "user::rwx"}),
    "pax global header": _pax("node/f", {}, global_records={"comment": "x"}),
    "duplicate path": _tar(_entry("node/f"), _entry("node/f")),
    "duplicate after cleaning": _tar(_entry("node/f"), _entry("./node//f")),
    "hardlink to a later file": _tar(_entry("node/h", tarfile.LNKTYPE, "node/f"), _entry("node/f")),
    "hardlink to a folder": _tar(_entry("node/d", tarfile.DIRTYPE), _entry("node/h", tarfile.LNKTYPE, "node/d")),
    # A NUL in a PAX record survives in tarfile's name but ends it once written
    # back to the ustar field: "node/s\0" -> "..\0" would come out as node/s -> ..
    "nul in a link name and target": _pax_entries(
        ("node", tarfile.DIRTYPE, {}),
        ("node/s", tarfile.SYMTYPE, {"path": "node/s\x00", "linkpath": "..\x00"}),
        ("node/s/evil", tarfile.REGTYPE, {}),
    ),
    "nul in a link target": _pax_entries(("node/up", tarfile.SYMTYPE, {"linkpath": "..\x00"})),
    "nul in a name": _pax_entries(
        ("node/f", tarfile.REGTYPE, {}), ("node/f", tarfile.REGTYPE, {"path": "node/f\x00dup"})
    ),
    "newline in a name": _tar(_entry("node/a\nb")),
    "infinite time": _pax("node/f", {"mtime": "inf"}),
    "nan time": _pax("node/f", {"mtime": "nan"}),
    "overflowing time": _pax("node/f", {"mtime": "1e400"}),
}

#: The words each refusal must use, so the error says which rule fired.
RULE = {
    "sparse": "sparse file",
    "pax sparse": "sparse file",
    "file capability": "SCHILY.xattr.security.capability",
    "user xattr": "SCHILY.xattr.user.x",
    "acl": "SCHILY.acl.access",
    "pax global header": "global header",
    "duplicate path": "appears twice",
    "duplicate after cleaning": "appears twice",
    "hardlink to a later file": "not a file earlier",
    "hardlink to a folder": "not a file earlier",
    "char device": "device, pipe",
    "fifo": "device, pipe",
    "absolute": "absolute path",
    "dot-dot": "leaves its folder",
    "nul in a link name and target": "control character",
    "nul in a link target": "control character",
    "nul in a name": "control character",
    "newline in a name": "control character",
    "infinite time": "invalid modification time",
    "nan time": "invalid modification time",
    "overflowing time": "invalid modification time",
}


class TestUnsafeEntriesAreRefused:
    """Anyone with the public key can build a bundle that opens cleanly, and the
    documented restore extracts it as root, so the archive itself is the check."""

    @pytest.mark.parametrize("case", sorted(UNSAFE))
    def test_refused(self, case):
        with pytest.raises(sb.BackupError, match="unsafe entry"):
            sb.split_archives(UNSAFE[case])

    @pytest.mark.parametrize("case", sorted(UNSAFE))
    def test_the_cli_writes_nothing(self, case, tmp_path):
        bundle = sb.seal(UNSAFE[case], passphrase=PASSPHRASE, metadata={"slug": "x", "worker": "w"})
        result = _decrypt(bundle, PASSPHRASE, tmp_path)
        assert result.returncode == 1
        assert "unsafe entry" in result.stderr
        assert not (tmp_path / "out").exists()

    def test_links_inside_the_folder_still_restore(self):
        payload = _tar(
            _entry("node"),
            _entry("node/data"),
            _entry("node/current", tarfile.SYMTYPE, "data"),
            _entry("node/copy", tarfile.LNKTYPE, "node/data"),
        )
        parts = sb.split_archives(payload)
        with tarfile.open(fileobj=io.BytesIO(parts["node"])) as tar:
            assert tar.getmember("node/current").linkname == "data"

    def test_setuid_bits_are_dropped(self):
        f = _entry("node/run")
        f.mode = 0o4755
        with tarfile.open(fileobj=io.BytesIO(sb.split_archives(_tar(f))["node"])) as tar:
            assert tar.getmember("node/run").mode == 0o755

    @pytest.mark.parametrize("case", sorted(RULE))
    def test_the_error_names_the_rule(self, case):
        with pytest.raises(sb.BackupError, match="unsafe entry") as err:
            sb.split_archives(UNSAFE[case])
        assert RULE[case] in str(err.value)

    def test_a_sparse_member_is_refused_before_it_is_unpacked(self, monkeypatch):
        """2 KB in the file, 100 MB once read: the read itself must never happen."""
        payload = UNSAFE["sparse"]
        assert len(payload) == 2048
        with tarfile.open(fileobj=io.BytesIO(payload)) as tar:
            assert tar.getmember("node/big").size == 100 * 1024 * 1024
        monkeypatch.setattr(tarfile.TarFile, "extractfile", lambda *a, **k: pytest.fail("sparse data was read"))
        with pytest.raises(sb.BackupError, match="sparse"):
            sb.split_archives(payload)

    def test_the_output_keeps_only_the_listed_fields(self):
        """Nothing but name, type, permission bits, owner ids, time, size and link
        reaches the archive that gets extracted as root."""
        d = _entry("node", tarfile.DIRTYPE)
        d.mode, d.uid, d.gid, d.uname, d.gname = 0o1777, 100, 101, "root", "wheel"
        f = _entry("node/" + "k" * 150)  # long enough to need a PAX path record
        f.mode, f.uid, f.gid, f.mtime = 0o6755, 100, 101, 1767225600.75
        out = sb.split_archives(_tar(d, f))["node"]
        with tarfile.open(fileobj=io.BytesIO(out)) as tar:
            got = {m.name: m for m in tar}
            assert set(got) == {"node", f.name}
            assert (got["node"].mode, got["node"].uid, got["node"].gid) == (0o777, 100, 101)
            assert (got["node"].uname, got["node"].gname) == ("", "")
            assert (got[f.name].mode, got[f.name].mtime) == (0o755, 1767225600)
            assert tar.extractfile(f.name).read() == b"x"  # type: ignore[union-attr]
            assert set(got[f.name].pax_headers) == {"path"}
            assert got["node"].pax_headers == {}

    def test_harmless_pax_records_are_accepted(self):
        """Docker writes PAX records for long names and large ids; those restore."""
        payload = _pax("node/f", {"uid": "3000000", "gid": "3000001", "uname": "u", "mtime": "1767225600.5"})
        with tarfile.open(fileobj=io.BytesIO(sb.split_archives(payload)["node"])) as tar:
            m = tar.getmember("node/f")
            assert (m.uid, m.gid, m.uname) == (3000000, 3000001, "")

    def test_a_hardlink_to_an_earlier_file_with_a_dot_prefix_restores(self):
        payload = _tar(_entry("node/f"), _entry("node/h", tarfile.LNKTYPE, "./node/f"))
        with tarfile.open(fileobj=io.BytesIO(sb.split_archives(payload)["node"])) as tar:
            assert tar.getmember("node/h").linkname == "node/f"


class TestTheCaps:
    def test_the_size_cap_matches_the_export_cap(self):
        """A bundle the worker exported always fits the restore."""
        assert sb.MAX_ARCHIVE_BYTES >= orchestrator.MAX_BACKUP_BYTES

    def test_the_size_cap_opens_desktop_bundles(self):
        """CashPilot-Desktop exports up to 256 MB (MaxStateBytes) and its docs
        send users to this tool, so every Desktop bundle must open here too."""
        assert sb.MAX_ARCHIVE_BYTES >= 256 * 1024 * 1024

    def test_too_much_file_data_is_refused_before_it_is_read(self, monkeypatch):
        monkeypatch.setattr(sb, "MAX_ARCHIVE_BYTES", 2)
        payload = _tar(_entry("node/a"), _entry("node/b"), _entry("node/c"))
        with pytest.raises(sb.BackupError, match="size cap"):
            sb.split_archives(payload)
        monkeypatch.setattr(sb, "MAX_ARCHIVE_BYTES", 3)
        assert sorted(sb.split_archives(payload)) == ["node"]

    def test_too_many_entries_are_refused(self, monkeypatch):
        monkeypatch.setattr(sb, "MAX_ARCHIVE_ENTRIES", 2)
        payload = _tar(_entry("node", tarfile.DIRTYPE), _entry("node/a"), _entry("node/b"))
        with pytest.raises(sb.BackupError, match="entry cap"):
            sb.split_archives(payload)
        monkeypatch.setattr(sb, "MAX_ARCHIVE_ENTRIES", 3)
        assert sorted(sb.split_archives(payload)) == ["node"]

    def test_a_truncated_archive_is_a_backup_error(self):
        payload = _tar(_entry("node/f"))
        with pytest.raises(sb.BackupError, match="damaged"):
            sb.split_archives(payload[:512] + b"")


class TestTheCliNeverOverwrites:
    def test_an_existing_tar_is_kept(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        (out / "mysterium-node.tar").write_bytes(b"mine")
        result = _decrypt(_fake_volume_bundle(passphrase=PASSPHRASE), PASSPHRASE, tmp_path)
        assert result.returncode == 1
        assert "already exists" in result.stderr
        assert (out / "mysterium-node.tar").read_bytes() == b"mine"
        assert not (out / ".proxybase.tar").exists()
