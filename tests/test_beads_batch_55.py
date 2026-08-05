"""CashPilot-416: worker names churned on every container recreate.

Inside a container, ``socket.gethostname()`` returns the first 12 hex characters
of the container ID, and Docker regenerates that on every recreate — which is
what an image bump does. ``worker_api.py:59`` defaults ``WORKER_NAME`` to it, and
``upsert_worker`` wrote ``name = excluded.name`` unconditionally.

So a worker with no ``CASHPILOT_WORKER_NAME`` set reported a brand-new
meaningless name after every upgrade. Observed live: three workers renamed
themselves during a routine 1.10.1 → 1.11.34 roll, from ``489bd13891b2`` and
friends to ``35c04a0f43f5`` and friends. The machines had not changed at all.

A name that changes when nothing about the machine changed is worse than no
name: a user who learns which row is which loses that knowledge on the next
upgrade.

The worker's **identity** was already protected from exactly this —
``worker_api._name_is_ephemeral`` guards ``client_id``, which is why the roll did
not also create duplicate rows. The display name was not.
"""

from __future__ import annotations

import asyncio

import pytest

CONTAINER_ID = "35c04a0f43f5"
ANOTHER_CONTAINER_ID = "b69b686b7a2b"


@pytest.fixture
def db(tmp_path, monkeypatch):
    from app import database

    monkeypatch.setattr(database, "DB_DIR", tmp_path)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "names.db")
    asyncio.run(database.init_db())
    return database


async def _name_after(db, first: str, second: str) -> str:
    """Upsert twice under one client_id and return the stored name."""
    await db.upsert_worker(client_id="c1", name=first)
    await db.upsert_worker(client_id="c1", name=second)
    row = await db.get_worker_by_client_id("c1") if hasattr(db, "get_worker_by_client_id") else None
    if row is None:
        workers = await db.list_workers()
        row = next(w for w in workers if w["client_id"] == "c1")
    return row["name"]


class TestAContainerIdNeverOverwritesARealName:
    @pytest.mark.asyncio
    async def test_a_recreate_does_not_rename_a_named_worker(self, db):
        """The bead: a user-set name must survive an image bump."""
        assert await _name_after(db, "watchtower", CONTAINER_ID) == "watchtower"

    @pytest.mark.asyncio
    async def test_it_survives_repeated_recreates(self, db):
        await db.upsert_worker(client_id="c1", name="geiserback")
        for cid in (CONTAINER_ID, ANOTHER_CONTAINER_ID, "0111c4f0efd6"):
            await db.upsert_worker(client_id="c1", name=cid)
        workers = await db.list_workers()
        assert next(w for w in workers if w["client_id"] == "c1")["name"] == "geiserback"

    @pytest.mark.asyncio
    async def test_one_container_id_does_not_replace_another(self, db):
        """Churn between two meaningless names is still churn."""
        assert await _name_after(db, CONTAINER_ID, ANOTHER_CONTAINER_ID) == CONTAINER_ID


class TestRealNamesStillWin:
    """The guard must be narrow, or it freezes names nobody can change."""

    @pytest.mark.asyncio
    async def test_a_user_can_rename_a_worker(self, db):
        assert await _name_after(db, CONTAINER_ID, "watchtower") == "watchtower"

    @pytest.mark.asyncio
    async def test_a_user_can_rename_one_real_name_to_another(self, db):
        assert await _name_after(db, "old-name", "new-name") == "new-name"

    @pytest.mark.asyncio
    async def test_a_first_registration_keeps_whatever_it_reports(self, db):
        """With nothing stored, even a container ID is better than blank."""
        await db.upsert_worker(client_id="c1", name=CONTAINER_ID)
        workers = await db.list_workers()
        assert next(w for w in workers if w["client_id"] == "c1")["name"] == CONTAINER_ID

    @pytest.mark.parametrize(
        "name",
        ["35c04a0f43f", "35c04a0f43f5a", "ABCDEF012345", "my-host-12ab", "raspberrypi", "watchtower"],
        ids=["11-hex", "13-hex", "uppercase", "hyphenated", "hostname", "word"],
    )
    @pytest.mark.asyncio
    async def test_only_the_exact_container_id_shape_is_rejected(self, db, name):
        """Guards against a sloppy pattern eating legitimate hostnames."""
        assert await _name_after(db, "watchtower", name) == name


class TestTheOtherFieldsStillUpdate:
    """Freezing the name must not freeze the heartbeat's actual payload."""

    @pytest.mark.asyncio
    async def test_containers_and_url_still_change(self, db):
        await db.upsert_worker(client_id="c1", name="watchtower", url="http://a:8081", containers="[]")
        await db.upsert_worker(client_id="c1", name=CONTAINER_ID, url="http://b:8081", containers='[{"slug": "grass"}]')
        workers = await db.list_workers()
        row = next(w for w in workers if w["client_id"] == "c1")
        assert row["name"] == "watchtower"
        assert row["url"] == "http://b:8081"
        assert "grass" in row["containers"]


class TestTheIdentityGuardIsStillThere:
    """This fix is about the DISPLAY name; identity was already protected."""

    def test_the_worker_still_refuses_an_ephemeral_client_id(self):
        from app import worker_api

        assert hasattr(worker_api, "_name_is_ephemeral")

    def test_it_recognises_the_container_id_shape(self, monkeypatch):
        from pathlib import Path

        from app import worker_api

        monkeypatch.setattr(Path, "exists", lambda self: True)
        assert worker_api._name_is_ephemeral(CONTAINER_ID) is True
        assert worker_api._name_is_ephemeral("watchtower") is False
