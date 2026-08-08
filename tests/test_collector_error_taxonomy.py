"""The collector failure taxonomy (CashPilot-5bdm).

A 401 and a timeout used to be the same free-text string, so the bell could
only ever say "collection failed" — teaching the user to ignore the one alert
that needs them. An expired credential earns $0 until a human acts; a provider
outage fixes itself. These tests pin the distinction end to end: collectors
classify, the collection loop preserves it (and the platform name, even when a
collector RAISES), the alerts table stores it, and the API serves it.

The load-bearing negative control: a TIMEOUT must never be classified as an
auth failure, and an UNKNOWN must never be classified as transient — a wrong
"will self-heal" label is worse than none.
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

from app.collectors import base  # noqa: E402


def _make_async_client():
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def _mock_response(status_code=200, json_data=None, text="", url="https://example.com"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    resp.url = url
    resp.headers = {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=resp
        )
    return resp


class TestClassifyException:
    def test_timeout_is_transient(self):
        assert base.classify_exception(httpx.TimeoutException("t")) == base.KIND_TRANSIENT

    def test_network_error_is_transient(self):
        assert base.classify_exception(httpx.ConnectError("refused")) == base.KIND_TRANSIENT

    @pytest.mark.parametrize("code", [401, 403])
    def test_auth_status_is_auth(self, code):
        resp = MagicMock(status_code=code)
        exc = httpx.HTTPStatusError("x", request=MagicMock(), response=resp)
        assert base.classify_exception(exc) == base.KIND_AUTH

    def test_5xx_is_transient_not_auth(self):
        resp = MagicMock(status_code=503)
        exc = httpx.HTTPStatusError("x", request=MagicMock(), response=resp)
        assert base.classify_exception(exc) == base.KIND_TRANSIENT

    def test_a_timeout_is_never_auth(self):
        """The control that matters most: telling a user to rotate their
        credential for a network blip teaches them to ignore the real one."""
        assert base.classify_exception(httpx.TimeoutException("t")) != base.KIND_AUTH

    @pytest.mark.parametrize("exc", [ValueError("parse"), RuntimeError("?"), KeyError("k")])
    def test_unknown_exceptions_stay_unknown_not_transient(self, exc):
        """Absent is not transient. An unknown labelled 'self-heals' hides a
        real fault behind a promise nobody made."""
        assert base.classify_exception(exc) is None

    def test_teapot_is_unknown(self):
        resp = MagicMock(status_code=418)
        exc = httpx.HTTPStatusError("x", request=MagicMock(), response=resp)
        assert base.classify_exception(exc) is None


class TestSaladTaxonomy:
    def test_401_is_an_auth_failure(self):
        from app.collectors.salad import SaladCollector

        resp = _mock_response(401)
        resp.raise_for_status = MagicMock()  # 401 handled inline by the collector
        client = _make_async_client()
        client.get.return_value = resp
        with patch("app.collectors.salad.httpx.AsyncClient", return_value=client):
            result = asyncio.run(SaladCollector(auth_cookie="expired").collect())
        assert result.error_kind == base.KIND_AUTH

    def test_timeout_is_transient_not_auth(self):
        """Negative control for the collector, not just the classifier."""
        from app.collectors.salad import SaladCollector

        client = _make_async_client()
        client.get.side_effect = httpx.TimeoutException("timed out")
        with patch("app.collectors.salad.httpx.AsyncClient", return_value=client):
            result = asyncio.run(SaladCollector(auth_cookie="fine").collect())
        assert result.error is not None
        assert result.error_kind == base.KIND_TRANSIENT
        assert result.error_kind != base.KIND_AUTH

    def test_shape_change_is_shape_not_auth(self):
        from app.collectors.salad import SaladCollector

        resp = _mock_response(200, {"unexpected": "shape"})
        client = _make_async_client()
        client.get.return_value = resp
        with patch("app.collectors.salad.httpx.AsyncClient", return_value=client):
            result = asyncio.run(SaladCollector(auth_cookie="fine").collect())
        assert result.error_kind == base.KIND_SHAPE


class TestPacketStreamTaxonomy:
    def test_401_is_auth(self):
        from app.collectors.packetstream import PacketStreamCollector

        resp = _mock_response(401)
        resp.raise_for_status = MagicMock()
        client = _make_async_client()
        client.get.return_value = resp
        with patch("app.collectors.packetstream.httpx.AsyncClient", return_value=client):
            result = asyncio.run(PacketStreamCollector(auth_token="jwt").collect())
        assert result.error_kind == base.KIND_AUTH

    def test_unparseable_dashboard_is_shape(self):
        from app.collectors.packetstream import PacketStreamCollector

        resp = _mock_response(200, text="<html>totally new layout</html>")
        client = _make_async_client()
        client.get.return_value = resp
        with patch("app.collectors.packetstream.httpx.AsyncClient", return_value=client):
            result = asyncio.run(PacketStreamCollector(auth_token="jwt").collect())
        assert result.error_kind == base.KIND_SHAPE
        assert result.error_kind != base.KIND_AUTH


class TestBytelixirTaxonomy:
    def test_login_redirect_is_auth(self):
        from app.collectors.bytelixir import BytelixirCollector

        resp = _mock_response(200, text="<html></html>")
        resp.url = MagicMock()
        resp.url.path = "/login"
        client = _make_async_client()
        client.get.return_value = resp
        with patch("app.collectors.bytelixir.httpx.AsyncClient", return_value=client):
            result = asyncio.run(BytelixirCollector(session_cookie="stale").collect())
        assert result.error_kind == base.KIND_AUTH


class TestHoneygainTaxonomy:
    def test_missing_field_is_shape(self):
        from app.collectors.honeygain import HoneygainCollector

        login = _mock_response(200, {"data": {"access_token": "tok"}})
        balances = _mock_response(200, {"data": {"payout": {}}})
        client = _make_async_client()
        client.post.return_value = login
        client.get.return_value = balances
        with patch("app.collectors.honeygain.httpx.AsyncClient", return_value=client):
            result = asyncio.run(HoneygainCollector(email="e", password="p").collect())
        assert result.error_kind == base.KIND_SHAPE


class TestRaisedExceptionsKeepTheirPlatform:
    """A collector that RAISES used to vanish: the exception reached the
    gather() where the platform name was unrecoverable, so it produced no
    alert, no bell entry and no metric — invisible exactly when broken."""

    def test_collect_bounded_attributes_the_failure(self):
        from app import main as app_main

        class ExplodingCollector:
            platform = "exploding"

            async def collect(self):
                raise httpx.ConnectError("boom")

        result = asyncio.run(app_main._collect_bounded(ExplodingCollector()))
        assert result.platform == "exploding"
        assert result.error is not None
        assert result.error_kind == base.KIND_TRANSIENT

    def test_an_unclassifiable_crash_is_unknown_not_transient(self):
        from app import main as app_main

        class BuggyCollector:
            platform = "buggy"

            async def collect(self):
                raise RuntimeError("logic error")

        result = asyncio.run(app_main._collect_bounded(BuggyCollector()))
        assert result.platform == "buggy"
        assert result.error_kind is None


class TestAlertsStoreTheCategory:
    @pytest.mark.asyncio
    async def test_category_roundtrips_through_the_alerts_table(self, tmp_path, monkeypatch):
        from app import database

        monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
        await database.init_db()
        assert await database.record_alert("collector", "salad", "cookie expired", category="auth")
        rows = await database.list_alerts()
        assert rows[0]["category"] == "auth"

    @pytest.mark.asyncio
    async def test_an_uncategorised_alert_stays_null_not_a_default(self, tmp_path, monkeypatch):
        from app import database

        monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
        await database.init_db()
        assert await database.record_alert("collector", "mystery", "who knows")
        rows = await database.list_alerts()
        assert rows[0]["category"] is None

    @pytest.mark.asyncio
    async def test_legacy_alerts_table_gains_the_column_on_migrate(self, tmp_path, monkeypatch):
        """An upgraded volume, not just a fresh install."""
        import aiosqlite

        from app import database

        db_file = str(tmp_path / "legacy.db")
        async with aiosqlite.connect(db_file) as db:
            await db.execute(
                "CREATE TABLE alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, "
                "subject TEXT NOT NULL, message TEXT NOT NULL DEFAULT '', "
                "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
            )
            await db.execute("INSERT INTO alerts (kind, subject, message) VALUES ('collector', 'old', 'pre-upgrade')")
            await db.commit()
        monkeypatch.setattr(database, "DB_PATH", db_file)
        await database.init_db()
        assert await database.record_alert("collector", "salad", "expired", category="auth")
        rows = await database.list_alerts()
        by_subject = {r["subject"]: r for r in rows}
        assert by_subject["salad"]["category"] == "auth"
        assert by_subject["old"]["category"] is None, "history must not be backfilled with a guess"


class TestTheCategoryReachesTheApi:
    """The contract the JS depends on: `category` is PRESENT for a classified
    alert and ABSENT (not null) for an unclassified one."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from app.main import app

        # No context manager: entering it runs the app lifespan (scheduler,
        # DB init), which this test neither needs nor can host.
        return TestClient(app, raise_server_exceptions=False)

    def test_present_when_classified_absent_when_not(self, client):
        from app import main as app_main

        original = app_main._collector_alerts
        app_main._collector_alerts = [
            {"kind": "collector", "platform": "salad", "error": "cookie expired", "category": "auth"},
            {"kind": "collector", "platform": "mystery", "error": "who knows"},
        ]
        try:
            with patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "admin", "r": "owner"}):
                payload = client.get("/api/collector-alerts").json()
        finally:
            app_main._collector_alerts = original
        by_platform = {a["platform"]: a for a in payload["alerts"]}
        assert by_platform["salad"]["category"] == "auth"
        assert "category" not in by_platform["mystery"], "unknown must be absent, not null"


class TestTheStoredCategoryCannotGoStale:
    """The review finding that mattered: grass alternates between an
    expired-token error (auth) and a Cloudflare rate-limit (transient) with no
    success in between, and the 24h dedupe pinned whichever came first. A
    restart then restored the stale kind — a dead credential rendered as a
    muted self-healing blip with no fix button."""

    @pytest.mark.asyncio
    async def test_a_dedupe_hit_refreshes_the_stored_kind(self, tmp_path, monkeypatch):
        from app import database

        monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
        await database.init_db()
        assert await database.record_alert("collector", "grass", "rate limit", category="transient")
        # Within the cooldown: push suppressed, but the row must stop lying.
        assert not await database.record_alert("collector", "grass", "token expired", category="auth")
        rows = await database.list_alerts()
        assert rows[0]["category"] == "auth"
        assert rows[0]["message"] == "token expired"

    @pytest.mark.asyncio
    async def test_the_warm_rebuild_carries_the_refreshed_kind(self, tmp_path, monkeypatch):
        from app import database
        from app import main as app_main

        monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
        await database.init_db()
        await database.record_alert("collector", "grass", "rate limit", category="transient")
        await database.record_alert("collector", "grass", "token expired", category="auth")
        original = app_main._collector_alerts
        try:
            await app_main._warm_collector_alerts()
            restored = {a["platform"]: a for a in app_main._collector_alerts}
        finally:
            app_main._collector_alerts = original
        assert restored["grass"]["category"] == "auth"

    @pytest.mark.asyncio
    async def test_the_category_column_is_a_closed_enum(self, tmp_path, monkeypatch):
        """error is redacted on the neighbouring line; category must never be
        a smuggling path for unredacted exception text."""
        from app import database

        monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
        await database.init_db()
        assert await database.record_alert("collector", "x", "boom", category="Bearer hunter2-live-token")
        rows = await database.list_alerts()
        assert rows[0]["category"] is None


class TestTheSemaphoreSurvivesTheNewExceptionPath:
    def test_released_after_raising_collectors(self):
        from app import main as app_main

        class ExplodingCollector:
            platform = "exploding"

            async def collect(self):
                raise RuntimeError("boom")

        async def run():
            for _ in range(3):
                await app_main._collect_bounded(ExplodingCollector())
            return app_main._collection_semaphore.locked()

        assert asyncio.run(run()) is False
