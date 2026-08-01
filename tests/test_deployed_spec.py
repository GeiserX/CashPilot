"""Tests for persisting the deployed spec (CashPilot-tkd).

Every redeploy used to rebuild the container spec from catalog YAML, so a
container that had diverged from the catalog - a bind mount where the catalog
declares a named volume, a host path that only existed because of an env
substitution - was silently replaced by a *different* container. The worker
destroys the old one before anything can compare them, which is the root cause
of the whole "lost node identity" class of bug.

It is not a key-management problem. It is a memory problem: CashPilot had no
record of what it deployed.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app import database
from app.main import _merge_recorded_spec


@pytest.fixture
def db_dir(tmp_path):
    db_path = tmp_path / "cashpilot.db"
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", db_path),
    ):
        yield tmp_path


@pytest.fixture
def db(db_dir):
    asyncio.run(database.init_db())
    return db_dir


class TestSpecPersistence:
    def test_deploying_records_the_resolved_spec(self, db):
        spec = {
            "image": "storjlabs/storagenode:latest",
            "env": {"WALLET": "0xabc", "STORAGE": "2TB"},
            "volumes": {"/mnt/user/identity": {"bind": "/app/identity", "mode": "rw"}},
            "ports": {"28967/tcp": 28967},
        }

        async def run():
            await database.save_deployment(slug="storj", container_id="abc123", spec=spec)
            return await database.get_deployment_spec("storj")

        assert asyncio.run(run()) == spec

    def test_the_stored_spec_is_encrypted_at_rest(self, db):
        """env carries credentials, so the row must not hold them in plaintext."""
        spec = {"image": "x", "env": {"API_KEY": "super-secret-token"}}

        async def run():
            await database.save_deployment(slug="svc", container_id="c", spec=spec)
            conn = await database._get_db()
            try:
                cursor = await conn.execute("SELECT spec_encrypted FROM deployments WHERE slug = 'svc'")
                return (await cursor.fetchone())["spec_encrypted"]
            finally:
                await conn.close()

        stored = asyncio.run(run())
        assert "super-secret-token" not in stored
        assert stored.startswith("enc:")

    def test_a_caller_without_a_spec_does_not_erase_the_record(self, db):
        """A status-only update must not cost the deployment its memory."""
        spec = {"image": "x", "volumes": {"/host": {"bind": "/app", "mode": "rw"}}}

        async def run():
            await database.save_deployment(slug="svc", container_id="c1", spec=spec)
            # e.g. an external-service or status update that knows no spec
            await database.save_deployment(slug="svc", container_id="c2", status="external")
            return await database.get_deployment_spec("svc")

        assert asyncio.run(run()) == spec

    def test_no_record_reads_as_none_so_callers_fall_back_to_the_catalog(self, db):
        async def run():
            await database.save_deployment(slug="fresh", container_id="c")
            return await database.get_deployment_spec("fresh")

        assert asyncio.run(run()) is None

    def test_undecryptable_spec_reads_as_none_rather_than_half_a_spec(self, db):
        """A key mismatch must fall back to the catalog, not deploy a corrupt spec."""

        async def run():
            await database.save_deployment(slug="svc", container_id="c", spec={"image": "x"})
            conn = await database._get_db()
            try:
                await conn.execute("UPDATE deployments SET spec_encrypted = 'enc:garbage' WHERE slug = 'svc'")
                await conn.commit()
            finally:
                await conn.close()
            return await database.get_deployment_spec("svc")

        assert asyncio.run(run()) is None

    def test_migration_adds_the_column_to_an_existing_database(self, db_dir):
        """An install created before this change must not need a manual step."""

        async def run():
            await database.init_db()
            conn = await database._get_db()
            try:
                await conn.execute("ALTER TABLE deployments DROP COLUMN spec_encrypted")
                await conn.commit()
            finally:
                await conn.close()
            # init_db runs again on the next start
            await database.init_db()
            await database.save_deployment(slug="svc", container_id="c", spec={"image": "x"})
            return await database.get_deployment_spec("svc")

        assert asyncio.run(run()) == {"image": "x"}


class TestMergeRecordedSpec:
    """The record is authoritative for an EXISTING deployment; the catalog is not."""

    def test_bind_mount_survives_a_catalog_that_declares_a_named_volume(self):
        catalog_spec = {
            "image": "img:2",
            "env": {},
            "volumes": {"storj-identity": {"bind": "/app/identity", "mode": "rw"}},
        }
        recorded = {
            "image": "img:1",
            "env": {},
            "volumes": {"/mnt/user/appdata/storj": {"bind": "/app/identity", "mode": "rw"}},
        }

        merged, divergence = _merge_recorded_spec(catalog_spec, recorded, user_env={})

        assert merged["volumes"] == recorded["volumes"], "the running mount must be reproduced exactly"
        assert any("mounts" in d for d in divergence), "the disagreement must be surfaced, not hidden"

    def test_image_still_comes_from_the_catalog_so_upgrades_land(self):
        merged, _ = _merge_recorded_spec({"image": "img:2", "env": {}}, {"image": "img:1", "env": {}}, user_env={})
        assert merged["image"] == "img:2"

    def test_ports_are_reproduced(self):
        merged, divergence = _merge_recorded_spec(
            {"image": "i", "env": {}, "ports": {"28967/tcp": 28967}},
            {"image": "i", "env": {}, "ports": {"28967/tcp": 31000}},
            user_env={},
        )
        assert merged["ports"] == {"28967/tcp": 31000}
        assert any("ports" in d for d in divergence)

    def test_storj_redeploys_without_retyping_the_identity_paths(self):
        """The acceptance case: no user re-entry of IDENTITY_DIR / STORAGE_DIR."""
        catalog_spec = {
            "image": "storjlabs/storagenode:latest",
            # Unsubstituted, because the operator did not retype them this time.
            "env": {"IDENTITY_DIR": "", "STORAGE_DIR": "", "WALLET": "0xabc"},
            "volumes": {"${IDENTITY_DIR}": {"bind": "/app/identity", "mode": "rw"}},
        }
        recorded = {
            "image": "storjlabs/storagenode:latest",
            "env": {"IDENTITY_DIR": "/mnt/user/identity", "STORAGE_DIR": "/mnt/user/storage", "WALLET": "0xabc"},
            "volumes": {
                "/mnt/user/identity": {"bind": "/app/identity", "mode": "rw"},
                "/mnt/user/storage": {"bind": "/app/config", "mode": "rw"},
            },
        }

        merged, _ = _merge_recorded_spec(catalog_spec, recorded, user_env={})

        assert merged["volumes"] == recorded["volumes"]
        assert merged["env"]["IDENTITY_DIR"] == "/mnt/user/identity"
        assert "${IDENTITY_DIR}" not in merged["volumes"]

    def test_a_value_the_user_typed_this_time_wins_over_the_record(self):
        """Otherwise a rotated credential could never be corrected."""
        merged, _ = _merge_recorded_spec(
            {"image": "i", "env": {"TOKEN": "new-token", "OTHER": "default"}},
            {"image": "i", "env": {"TOKEN": "old-token", "OTHER": "recorded"}},
            user_env={"TOKEN": "new-token"},
        )
        assert merged["env"]["TOKEN"] == "new-token"
        assert merged["env"]["OTHER"] == "recorded"

    def test_new_catalog_env_keys_still_appear(self):
        merged, _ = _merge_recorded_spec(
            {"image": "i", "env": {"OLD": "a", "NEWLY_ADDED": "default"}},
            {"image": "i", "env": {"OLD": "kept"}},
            user_env={},
        )
        assert merged["env"] == {"OLD": "kept", "NEWLY_ADDED": "default"}

    def test_identical_catalog_and_record_report_no_divergence(self):
        spec = {"image": "i", "env": {"A": "1"}, "volumes": {"v": {"bind": "/b", "mode": "rw"}}}
        merged, divergence = _merge_recorded_spec(dict(spec), dict(spec), user_env={})
        assert divergence == []
        assert merged["volumes"] == spec["volumes"]

    def test_retyping_a_password_does_not_cost_the_service_its_mounts(self):
        """The original bug, in its most likely disguise."""
        catalog_spec = {
            "image": "i",
            "env": {"PASSWORD": "new", "IDENTITY_DIR": ""},
            "volumes": {"${IDENTITY_DIR}": {"bind": "/app/identity", "mode": "rw"}},
        }
        recorded = {
            "image": "i",
            "env": {"PASSWORD": "old", "IDENTITY_DIR": "/mnt/user/identity"},
            "volumes": {"/mnt/user/identity": {"bind": "/app/identity", "mode": "rw"}},
        }

        merged, _ = _merge_recorded_spec(
            catalog_spec,
            recorded,
            user_env={"PASSWORD": "new"},
            volume_env_keys_by_target={"/app/identity": {"IDENTITY_DIR"}},
        )

        assert merged["volumes"] == recorded["volumes"], "a password change must not move the data"
        assert merged["env"]["PASSWORD"] == "new"

    def test_supplying_a_path_variable_moves_the_data_on_purpose(self):
        """The operator explicitly relocating storage must be honoured."""
        catalog_spec = {
            "image": "i",
            "env": {"IDENTITY_DIR": "/mnt/new"},
            "volumes": {"/mnt/new": {"bind": "/app/identity", "mode": "rw"}},
        }
        recorded = {
            "image": "i",
            "env": {"IDENTITY_DIR": "/mnt/old"},
            "volumes": {"/mnt/old": {"bind": "/app/identity", "mode": "rw"}},
        }

        merged, divergence = _merge_recorded_spec(
            catalog_spec,
            recorded,
            user_env={"IDENTITY_DIR": "/mnt/new"},
            volume_env_keys_by_target={"/app/identity": {"IDENTITY_DIR"}},
        )

        assert merged["volumes"] == {"/mnt/new": {"bind": "/app/identity", "mode": "rw"}}
        assert any("supplied this deploy" in d for d in divergence)

    def test_moving_one_path_does_not_reset_the_others(self):
        """Storj has two independent path variables.

        Regression: the relocation check was computed once for the whole volumes
        block, so supplying IDENTITY_DIR silently dropped the STORAGE_DIR mount
        back to the catalog's unsubstituted template - losing a mount the
        operator never mentioned.
        """
        catalog_spec = {
            "image": "i",
            "env": {"IDENTITY_DIR": "/mnt/new-identity", "STORAGE_DIR": ""},
            "volumes": {
                "/mnt/new-identity": {"bind": "/app/identity", "mode": "rw"},
                "${STORAGE_DIR}": {"bind": "/app/config", "mode": "rw"},
            },
        }
        recorded = {
            "image": "i",
            "env": {"IDENTITY_DIR": "/mnt/old-identity", "STORAGE_DIR": "/mnt/storage"},
            "volumes": {
                "/mnt/old-identity": {"bind": "/app/identity", "mode": "rw"},
                "/mnt/storage": {"bind": "/app/config", "mode": "rw"},
            },
        }

        merged, divergence = _merge_recorded_spec(
            catalog_spec,
            recorded,
            user_env={"IDENTITY_DIR": "/mnt/new-identity"},
            volume_env_keys_by_target={
                "/app/identity": {"IDENTITY_DIR"},
                "/app/config": {"STORAGE_DIR"},
            },
        )

        assert merged["volumes"] == {
            "/mnt/new-identity": {"bind": "/app/identity", "mode": "rw"},
            "/mnt/storage": {"bind": "/app/config", "mode": "rw"},
        }, "only the mount whose variable was supplied may move"
        assert any("/app/identity" in d for d in divergence)

    def test_a_mount_added_to_the_catalog_since_deployment_still_appears(self):
        merged, _ = _merge_recorded_spec(
            {
                "image": "i",
                "env": {},
                "volumes": {
                    "/old": {"bind": "/app/data", "mode": "rw"},
                    "newvol": {"bind": "/app/cache", "mode": "rw"},
                },
            },
            {"image": "i", "env": {}, "volumes": {"/old": {"bind": "/app/data", "mode": "rw"}}},
            user_env={},
        )
        assert merged["volumes"]["newvol"] == {"bind": "/app/cache", "mode": "rw"}
        assert merged["volumes"]["/old"] == {"bind": "/app/data", "mode": "rw"}
