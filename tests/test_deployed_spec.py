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

    def test_a_resource_key_added_to_the_catalog_since_deployment_still_lands(self):
        """The cpu_shares rollout bug: resources merged as an opaque whole.

        The recorded dict predated the key, differed from the catalog, and so
        beat it forever — every deployed storj kept the default CPU weight, and
        the only escape was the remove-and-redeploy that risks the node
        identity. Resources merge per key now, like env: the catalog supplies
        keys the record never set.
        """
        merged, divergence = _merge_recorded_spec(
            {"image": "i", "env": {}, "resources": {"mem_limit": "2g", "oom_score_adj": -100, "cpu_shares": 4096}},
            {"image": "i", "env": {}, "resources": {"mem_limit": "2g", "oom_score_adj": -100}},
            user_env={},
        )
        assert merged["resources"] == {"mem_limit": "2g", "oom_score_adj": -100, "cpu_shares": 4096}
        # Nothing was kept over the catalog, so nothing may be reported as kept.
        assert not any("resources" in d for d in divergence)

    def test_a_resource_value_the_deployment_ran_with_still_wins_per_key(self):
        """Control for the test above: per-key must not mean catalog-clobbers.

        The record's own mem_limit survives — that is the value this container
        verifiably ran with — while the catalog's new key still lands beside it.
        """
        merged, divergence = _merge_recorded_spec(
            {"image": "i", "env": {}, "resources": {"mem_limit": "2g", "cpu_shares": 4096}},
            {"image": "i", "env": {}, "resources": {"mem_limit": "1g"}},
            user_env={},
        )
        assert merged["resources"] == {"mem_limit": "1g", "cpu_shares": 4096}
        assert any("resources" in d for d in divergence)

    def test_a_recorded_resources_block_survives_a_catalog_that_dropped_its_own(self):
        merged, divergence = _merge_recorded_spec(
            {"image": "i", "env": {}},
            {"image": "i", "env": {}, "resources": {"mem_limit": "1g"}},
            user_env={},
        )
        assert merged["resources"] == {"mem_limit": "1g"}
        assert any("resources" in d for d in divergence)

    def test_a_record_without_resources_takes_the_catalog_block_untouched(self):
        merged, divergence = _merge_recorded_spec(
            {"image": "i", "env": {}, "resources": {"cpu_shares": 4096}},
            {"image": "i", "env": {}},
            user_env={},
        )
        assert merged["resources"] == {"cpu_shares": 4096}
        assert not any("resources" in d for d in divergence)

    def test_a_non_dict_recorded_resources_value_is_ignored_not_merged(self):
        # The isinstance guard: a record predating the feature, or a corrupted
        # one, may carry None here — the catalog block must survive untouched
        # rather than crash the redeploy or clobber the limits with junk.
        merged, divergence = _merge_recorded_spec(
            {"image": "i", "env": {}, "resources": {"cpu_shares": 4096}},
            {"image": "i", "env": {}, "resources": None},
            user_env={},
        )
        assert merged["resources"] == {"cpu_shares": 4096}
        assert not any("resources" in d for d in divergence)

    def test_hostname_is_preserved_when_the_operator_leaves_it_blank(self):
        """Several services key device identity to the hostname."""
        merged, divergence = _merge_recorded_spec(
            {"image": "i", "env": {}, "hostname": None},
            {"image": "i", "env": {}, "hostname": "cashpilot-node-7"},
            user_env={},
        )
        assert merged["hostname"] == "cashpilot-node-7"
        assert any("hostname" in d for d in divergence)

    def test_a_hostname_typed_this_deploy_wins(self):
        merged, _ = _merge_recorded_spec(
            {"image": "i", "env": {}, "hostname": "new-name"},
            {"image": "i", "env": {}, "hostname": "old-name"},
            user_env={},
        )
        assert merged["hostname"] == "new-name"


class TestRedeployUsesTheRecordedSpec:
    """The endpoint wiring, not just the merge function.

    This is where keys_by_target is built from the catalog volume templates and
    handed to _merge_recorded_spec, and where the required-field check has to
    honour what the deployment already has - otherwise a redeploy demands the
    operator retype values the record already holds, which is exactly what
    recording the spec exists to prevent.
    """

    SERVICE = {
        "slug": "demo",
        "name": "Demo",
        "status": "active",
        "category": "storage",
        "docker": {
            "image": "demo:2",
            "env": [{"key": "DATA_DIR", "required": True, "label": "Data directory"}],
            "volumes": ["${DATA_DIR}:/app/data"],
            "ports": [],
        },
    }

    def _deploy(self, recorded, body_env=None):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from app import main

        captured = {}

        async def _capture(worker_id, s, spec):
            captured["spec"] = spec
            return {"container_id": "abc"}

        body = MagicMock()
        body.env = body_env or {}
        body.hostname = None

        async def run():
            with (
                patch.object(main, "_require_owner", lambda r: None),
                patch.object(main.catalog, "get_service", return_value=self.SERVICE),
                patch.object(main, "_resolve_worker_id", AsyncMock(return_value=1)),
                patch.object(main, "_proxy_worker_deploy", _capture),
                patch.object(main.database, "get_deployment_spec", AsyncMock(return_value=recorded)),
                patch.object(main.database, "save_deployment", AsyncMock()),
                patch.object(main.database, "record_health_event", AsyncMock()),
                patch.object(main, "_spawn", lambda coro: coro.close()),
                patch.object(main.metrics, "record_container_lifecycle", lambda *a: None),
            ):
                result = await main.api_deploy(MagicMock(), "demo", body)
            return result, captured.get("spec")

        return asyncio.run(run())

    RECORDED = {
        "image": "demo:1",
        "env": {"DATA_DIR": "/mnt/user/data"},
        "volumes": {"/mnt/user/data": {"bind": "/app/data", "mode": "rw"}},
    }

    def test_a_redeploy_does_not_demand_values_the_record_already_has(self):
        """The acceptance case: no retyping of the path on every redeploy."""
        result, spec = self._deploy(self.RECORDED)
        assert result["status"] == "deployed"
        assert spec["env"]["DATA_DIR"] == "/mnt/user/data"

    def test_a_redeploy_reproduces_the_recorded_mounts(self):
        _, spec = self._deploy(self.RECORDED)
        assert spec["volumes"] == self.RECORDED["volumes"]
        assert "${DATA_DIR}" not in str(spec["volumes"])

    def test_the_image_still_comes_from_the_catalog(self):
        _, spec = self._deploy(self.RECORDED)
        assert spec["image"] == "demo:2", "upgrades must still land"

    def test_supplying_the_path_this_deploy_relocates_it(self):
        _, spec = self._deploy(self.RECORDED, body_env={"DATA_DIR": "/mnt/user/moved"})
        assert "/mnt/user/moved" in spec["volumes"]

    def test_a_first_deploy_still_requires_its_fields(self):
        """No record means the required-field check must still bite."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            self._deploy(None)
        assert exc.value.status_code == 400
        assert "Data directory" in exc.value.detail

    def test_a_first_deploy_with_the_field_supplied_succeeds(self):
        result, spec = self._deploy(None, body_env={"DATA_DIR": "/mnt/user/new"})
        assert result["status"] == "deployed"
        assert "kept_from_previous_deployment" not in result


class TestTheSpecIsRecordedPerWorker:
    """One service, several machines, several specs.

    The record used to be one row per service for the whole fleet. Two Storj
    nodes advertise different addresses, and a dashboard redeploy on one
    machine rebuilt its node with the address the OTHER machine had recorded
    last, so satellites dialled the wrong node. Seen in the recorded spec on
    the fleet, 2026-09-25, before any redeploy acted on it.
    """

    A = {"image": "storjlabs/storagenode", "env": {"ADDRESS": "node-a.example:28967", "STORAGE": "1TB"}}
    B = {"image": "storjlabs/storagenode", "env": {"ADDRESS": "node-b.example:28968", "STORAGE": "2TB"}}

    @staticmethod
    def _workers(containers_a="[]", containers_b="[]"):
        async def run():
            a = await database.upsert_worker(client_id="wa", name="a", url="", containers=containers_a)
            b = await database.upsert_worker(client_id="wb", name="b", url="", containers=containers_b)
            return a, b

        return asyncio.run(run())

    def test_each_worker_reads_back_its_own_spec(self, db):
        a, b = self._workers()

        async def run():
            await database.save_deployment(slug="storj", container_id="ca" * 32, spec=self.A, worker_id=a)
            await database.save_deployment(slug="storj", container_id="cb" * 32, spec=self.B, worker_id=b)
            return (
                await database.get_deployment_spec("storj", worker_id=a),
                await database.get_deployment_spec("storj", worker_id=b),
            )

        spec_a, spec_b = asyncio.run(run())
        assert spec_a["env"]["ADDRESS"] == "node-a.example:28967"
        assert spec_b["env"]["ADDRESS"] == "node-b.example:28968"

    def test_a_worker_with_no_record_gets_none_not_another_workers_spec(self, db):
        a, b = self._workers()

        async def run():
            await database.save_deployment(slug="storj", container_id="cb" * 32, spec=self.B, worker_id=b)
            return await database.get_deployment_spec("storj", worker_id=a)

        assert asyncio.run(run()) is None

    def test_a_record_from_before_this_belongs_to_the_worker_running_its_container(self, db):
        """Migration: the old fleet-wide row is attributed by container id, or not at all."""
        legacy_id = "2ce66514c05695d1c6ae6ce14580c3968859bb2c1a2b96319ab22a3dabc74e30"
        running_b = '[{"slug": "storj", "container_id": "2ce66514c056"}]'
        running_a = '[{"slug": "storj", "container_id": "a742c69d61c9"}]'
        a, b = self._workers(containers_a=running_a, containers_b=running_b)

        async def run():
            # Written the old way: no worker.
            await database.save_deployment(slug="storj", container_id=legacy_id, spec=self.B)
            return (
                await database.get_deployment_spec("storj", worker_id=a),
                await database.get_deployment_spec("storj", worker_id=b),
            )

        spec_a, spec_b = asyncio.run(run())
        assert spec_a is None, "worker A runs a different container; the old row is not its spec"
        assert spec_b["env"]["ADDRESS"] == "node-b.example:28968"

    def test_without_a_worker_the_fleet_wide_answer_is_unchanged(self, db):
        """The payout registry asks "is an address configured anywhere"."""
        a, b = self._workers()

        async def run():
            await database.save_deployment(slug="storj", container_id="ca" * 32, spec=self.A, worker_id=a)
            await database.save_deployment(slug="storj", container_id="cb" * 32, spec=self.B, worker_id=b)
            return await database.get_deployment_spec("storj")

        assert asyncio.run(run())["env"]["ADDRESS"] == "node-b.example:28968"

    def test_removing_on_one_worker_keeps_the_others_spec(self, db):
        a, b = self._workers()

        async def run():
            await database.save_deployment(slug="storj", container_id="ca" * 32, spec=self.A, worker_id=a)
            await database.save_deployment(slug="storj", container_id="cb" * 32, spec=self.B, worker_id=b)
            await database.remove_deployment("storj", worker_id=a)
            return (
                await database.get_deployment_spec("storj", worker_id=a),
                await database.get_deployment_spec("storj", worker_id=b),
            )

        spec_a, spec_b = asyncio.run(run())
        assert spec_a is None
        assert spec_b["env"]["ADDRESS"] == "node-b.example:28968"


class TestRemovingOnOneWorkerKeepsTheServiceDeployedElsewhere:
    """Collection, metrics and the payout registry read the fleet-wide row as "deployed"."""

    SPEC = {"image": "storjlabs/storagenode", "env": {}}

    @staticmethod
    def _run(coro):
        return asyncio.run(coro)

    def test_another_workers_spec_keeps_the_row(self, db):
        async def run():
            a = await database.upsert_worker(client_id="wa", name="a", url="")
            b = await database.upsert_worker(client_id="wb", name="b", url="")
            await database.save_deployment(slug="storj", container_id="ca" * 32, spec=self.SPEC, worker_id=a)
            await database.save_deployment(slug="storj", container_id="cb" * 32, spec=self.SPEC, worker_id=b)
            await database.remove_deployment("storj", worker_id=a)
            return await database.get_deployment("storj")

        assert self._run(run()) is not None

    def test_another_workers_heartbeat_keeps_the_row(self, db):
        """A deployment from before per-worker specs is known only from the heartbeat."""

        async def run():
            a = await database.upsert_worker(client_id="wa", name="a", url="")
            await database.upsert_worker(
                client_id="wb", name="b", url="", containers='[{"slug": "storj", "container_id": "cb0000000000"}]'
            )
            await database.save_deployment(slug="storj", container_id="ca" * 32, spec=self.SPEC)
            await database.remove_deployment("storj", worker_id=a)
            return await database.get_deployment("storj")

        assert self._run(run()) is not None

    def test_the_last_worker_removes_the_row(self, db):
        async def run():
            a = await database.upsert_worker(
                client_id="wa", name="a", url="", containers='[{"slug": "storj", "container_id": "ca0000000000"}]'
            )
            await database.upsert_worker(client_id="wb", name="b", url="", containers='[{"slug": "honeygain"}]')
            await database.save_deployment(slug="storj", container_id="ca" * 32, spec=self.SPEC, worker_id=a)
            await database.remove_deployment("storj", worker_id=a)
            return await database.get_deployment("storj")

        assert self._run(run()) is None
