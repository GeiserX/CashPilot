"""Tests for the async SQLite database layer."""

import asyncio
import os
from unittest.mock import patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest

from app import database


@pytest.fixture
def db_dir(tmp_path):
    """Point DB at a temporary directory."""
    db_path = tmp_path / "cashpilot.db"
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", db_path),
    ):
        yield tmp_path


@pytest.fixture
def db(db_dir):
    """Initialize DB and yield the directory."""
    asyncio.run(database.init_db())
    return db_dir


class TestInitDb:
    def test_creates_tables(self, db):
        async def check():
            conn = await database._get_db()
            try:
                cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                tables = {row["name"] for row in await cursor.fetchall()}
                assert "earnings" in tables
                assert "config" in tables
                assert "deployments" in tables
                assert "users" in tables
                assert "workers" in tables
                assert "user_preferences" in tables
                assert "health_events" in tables
            finally:
                await conn.close()

        asyncio.run(check())

    def test_idempotent(self, db):
        """Running init_db twice should not error."""
        asyncio.run(database.init_db())


class TestEarnings:
    def test_upsert_and_get_summary(self, db):
        async def run():
            await database.upsert_earnings("honeygain", 5.50, "USD")
            await database.upsert_earnings("earnapp", 3.25, "USD")
            summary = await database.get_earnings_summary()
            slugs = {e["platform"] for e in summary}
            assert "honeygain" in slugs
            assert "earnapp" in slugs
            hg = next(e for e in summary if e["platform"] == "honeygain")
            assert hg["balance"] == 5.50

        asyncio.run(run())

    def test_upsert_updates_balance(self, db):
        async def run():
            await database.upsert_earnings("honeygain", 5.0, "USD", "2026-01-01")
            await database.upsert_earnings("honeygain", 7.0, "USD", "2026-01-01")
            summary = await database.get_earnings_summary()
            hg = next(e for e in summary if e["platform"] == "honeygain")
            assert hg["balance"] == 7.0

        asyncio.run(run())

    def test_get_earnings_history_week(self, db):
        async def run():
            await database.upsert_earnings("hg", 1.0, "USD")
            result = await database.get_earnings_history("week")
            assert isinstance(result, list)

        asyncio.run(run())

    def test_get_earnings_history_all(self, db):
        async def run():
            await database.upsert_earnings("hg", 1.0, "USD")
            result = await database.get_earnings_history("all")
            assert isinstance(result, list)

        asyncio.run(run())

    def test_get_daily_earnings(self, db):
        async def run():
            await database.upsert_earnings("hg", 10.0, "USD")
            result = await database.get_daily_earnings(7)
            assert len(result) == 7
            for entry in result:
                assert "date" in entry
                assert "amount" in entry

        asyncio.run(run())

    def test_get_earnings_per_service(self, db):
        async def run():
            await database.upsert_earnings("hg", 10.0, "USD")
            result = await database.get_earnings_per_service()
            assert len(result) >= 1

        asyncio.run(run())

    def test_get_earnings_dashboard_summary(self, db):
        async def run():
            await database.upsert_earnings("hg", 10.0, "USD")
            summary = await database.get_earnings_dashboard_summary()
            assert "total" in summary
            assert "today" in summary
            assert "month" in summary
            assert "today_change" in summary

        asyncio.run(run())


class TestConfig:
    def test_set_and_get_config(self, db):
        async def run():
            await database.set_config("my_key", "my_value")
            result = await database.get_config("my_key")
            assert result == "my_value"

        asyncio.run(run())

    def test_get_all_config(self, db):
        async def run():
            await database.set_config("k1", "v1")
            await database.set_config("k2", "v2")
            result = await database.get_config()
            assert isinstance(result, dict)
            assert result["k1"] == "v1"
            assert result["k2"] == "v2"

        asyncio.run(run())

    def test_get_missing_key_returns_none(self, db):
        async def run():
            result = await database.get_config("nonexistent")
            assert result is None

        asyncio.run(run())

    def test_set_config_bulk(self, db):
        async def run():
            await database.set_config_bulk({"a": "1", "b": "2"})
            cfg = await database.get_config()
            assert cfg["a"] == "1"
            assert cfg["b"] == "2"

        asyncio.run(run())

    def test_delete_config_keys(self, db):
        async def run():
            await database.set_config("del_me", "val")
            await database.delete_config_keys(["del_me"])
            result = await database.get_config("del_me")
            assert result is None

        asyncio.run(run())

    def test_delete_empty_keys_noop(self, db):
        async def run():
            await database.delete_config_keys([])

        asyncio.run(run())

    def test_secret_key_encrypted(self, db):
        async def run():
            await database.set_config("honeygain_password", "secret123")
            result = await database.get_config("honeygain_password")
            assert result == "secret123"
            # Verify it was actually stored encrypted
            conn = await database._get_db()
            try:
                cursor = await conn.execute(
                    "SELECT value FROM config WHERE key = ?",
                    ("honeygain_password",),
                )
                row = await cursor.fetchone()
                assert row["value"].startswith("enc:")
            finally:
                await conn.close()

        asyncio.run(run())


class TestDeployments:
    def test_save_and_get_deployments(self, db):
        async def run():
            await database.save_deployment("honeygain", "abc123")
            deps = await database.get_deployments()
            assert len(deps) == 1
            assert deps[0]["slug"] == "honeygain"

        asyncio.run(run())

    def test_get_deployment(self, db):
        async def run():
            await database.save_deployment("earnapp", "xyz789")
            dep = await database.get_deployment("earnapp")
            assert dep is not None
            assert dep["container_id"] == "xyz789"

        asyncio.run(run())

    def test_get_missing_deployment(self, db):
        async def run():
            dep = await database.get_deployment("missing")
            assert dep is None

        asyncio.run(run())

    def test_remove_deployment(self, db):
        async def run():
            await database.save_deployment("test", "cid")
            await database.remove_deployment("test")
            dep = await database.get_deployment("test")
            assert dep is None

        asyncio.run(run())

    def test_save_external_deployment(self, db):
        async def run():
            await database.save_deployment("grass", "", status="external")
            dep = await database.get_deployment("grass")
            assert dep["status"] == "external"

        asyncio.run(run())


class TestUsers:
    def test_create_and_get_user(self, db):
        async def run():
            uid = await database.create_user("alice", "hashed_pw", "owner")
            assert uid > 0
            user = await database.get_user_by_username("alice")
            assert user is not None
            assert user["username"] == "alice"
            assert user["role"] == "owner"

        asyncio.run(run())

    def test_get_user_by_id(self, db):
        async def run():
            uid = await database.create_user("bob", "hashed", "viewer")
            user = await database.get_user_by_id(uid)
            assert user["username"] == "bob"

        asyncio.run(run())

    def test_get_nonexistent_user(self, db):
        async def run():
            assert await database.get_user_by_username("nobody") is None
            assert await database.get_user_by_id(9999) is None

        asyncio.run(run())

    def test_has_any_users(self, db):
        async def run():
            assert not await database.has_any_users()
            await database.create_user("first", "pw", "owner")
            assert await database.has_any_users()

        asyncio.run(run())

    def test_list_users(self, db):
        async def run():
            await database.create_user("u1", "pw", "owner")
            await database.create_user("u2", "pw", "viewer")
            users = await database.list_users()
            assert len(users) == 2

        asyncio.run(run())

    def test_update_user_role(self, db):
        async def run():
            uid = await database.create_user("user1", "pw", "viewer")
            await database.update_user_role(uid, "writer")
            user = await database.get_user_by_id(uid)
            assert user["role"] == "writer"

        asyncio.run(run())

    def test_delete_user(self, db):
        async def run():
            uid = await database.create_user("del_user", "pw", "viewer")
            await database.delete_user(uid)
            assert await database.get_user_by_id(uid) is None

        asyncio.run(run())


class TestUserPreferences:
    def test_save_and_get_preferences(self, db):
        async def run():
            uid = await database.create_user("pref_user", "pw", "owner")
            await database.save_user_preferences(uid, "fresh", "[]", "UTC", False)
            prefs = await database.get_user_preferences(uid)
            assert prefs is not None
            assert prefs["setup_mode"] == "fresh"

        asyncio.run(run())

    def test_get_missing_preferences(self, db):
        async def run():
            prefs = await database.get_user_preferences(9999)
            assert prefs is None

        asyncio.run(run())

    def test_mark_setup_completed(self, db):
        async def run():
            uid = await database.create_user("setup_user", "pw", "owner")
            await database.save_user_preferences(uid)
            await database.mark_setup_completed(uid)
            prefs = await database.get_user_preferences(uid)
            assert prefs["setup_completed"] == 1

        asyncio.run(run())


class TestWorkers:
    def test_upsert_worker(self, db):
        async def run():
            wid = await database.upsert_worker("client-1", "worker-1", "http://w1:8081")
            assert wid > 0
            worker = await database.get_worker(wid)
            assert worker["name"] == "worker-1"
            assert worker["status"] == "online"

        asyncio.run(run())

    def test_upsert_worker_updates(self, db):
        async def run():
            wid1 = await database.upsert_worker("client-1", "name1", "http://w1:8081")
            wid2 = await database.upsert_worker("client-1", "name2", "http://w1:8082")
            assert wid1 == wid2
            worker = await database.get_worker(wid1)
            assert worker["name"] == "name2"

        asyncio.run(run())

    def test_list_workers(self, db):
        async def run():
            await database.upsert_worker("c1", "w1")
            await database.upsert_worker("c2", "w2")
            workers = await database.list_workers()
            assert len(workers) == 2

        asyncio.run(run())

    def test_set_worker_status(self, db):
        async def run():
            wid = await database.upsert_worker("c1", "w1")
            await database.set_worker_status(wid, "offline")
            worker = await database.get_worker(wid)
            assert worker["status"] == "offline"

        asyncio.run(run())

    def test_delete_worker(self, db):
        async def run():
            wid = await database.upsert_worker("c1", "w1")
            await database.delete_worker(wid)
            assert await database.get_worker(wid) is None

        asyncio.run(run())

    def test_get_worker_by_name(self, db):
        async def run():
            await database.upsert_worker("c1", "myworker")
            worker = await database.get_worker_by_name("myworker")
            assert worker is not None
            assert worker["name"] == "myworker"

        asyncio.run(run())

    def test_get_missing_worker(self, db):
        async def run():
            assert await database.get_worker(9999) is None
            assert await database.get_worker_by_name("nope") is None

        asyncio.run(run())


class TestHealthEvents:
    def test_record_and_get_scores(self, db):
        async def run():
            await database.record_health_event("honeygain", "check_ok")
            await database.record_health_event("honeygain", "check_ok")
            await database.record_health_event("honeygain", "restart")
            scores = await database.get_health_scores(7)
            assert len(scores) == 1
            assert scores[0]["slug"] == "honeygain"
            assert scores[0]["restarts"] == 1
            assert 0 <= scores[0]["score"] <= 100

        asyncio.run(run())

    def test_empty_scores(self, db):
        async def run():
            scores = await database.get_health_scores(7)
            assert scores == []

        asyncio.run(run())


class TestDataRetention:
    def test_purge_returns_count(self, db):
        async def run():
            result = await database.purge_old_data()
            assert result == 0  # nothing old to purge

        asyncio.run(run())


class TestEncryption:
    def test_encrypt_decrypt_round_trip(self):
        encrypted = database.encrypt_value("secret123")
        assert encrypted.startswith("enc:")
        assert database.decrypt_value(encrypted) == "secret123"

    def test_decrypt_unencrypted_value(self):
        assert database.decrypt_value("plaintext") == "plaintext"

    def test_is_secret_key(self):
        assert database._is_secret_key("honeygain_password")
        assert database._is_secret_key("grass_access_token")
        assert database._is_secret_key("proxyrack_api_key")
        assert not database._is_secret_key("honeygain_email")
        assert not database._is_secret_key("collect_interval")
