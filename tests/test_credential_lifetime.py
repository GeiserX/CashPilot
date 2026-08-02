"""Credential lifetime honesty (CashPilot-aug).

Several collectors need a value copied out of a browser, and some die within
hours. Nothing used to tell the user that: a collector configured in the morning
could be dead by evening, and the only symptom was earnings quietly not being
recorded — indistinguishable from a provider outage.

These tests pin the two halves that make it visible BEFORE it happens: the stored
age of every credential, and the declared lifetime that turns an age into
"fresh", "expiring soon" or "likely expired".
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app import database
from app.collectors import _COLLECTOR_ARGS, CREDENTIAL_LIFETIMES, credential_lifetime, durable_alternative


@pytest.fixture
def db_dir(tmp_path):
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"),
    ):
        yield tmp_path


@pytest.fixture
def db(db_dir):
    asyncio.run(database.init_db())
    return db_dir


class TestCredentialAgeIsRecorded:
    def test_setting_a_config_value_records_when(self, db):
        async def run():
            await database.set_config("bytelixir_session_cookie", "abc")
            return await database.get_config_updated_at()

        stamps = asyncio.run(run())
        assert "bytelixir_session_cookie" in stamps
        assert stamps["bytelixir_session_cookie"]

    def test_bulk_writes_record_when_too(self, db):
        async def run():
            await database.set_config_bulk({"honeygain_email": "a@b.c", "honeygain_password": "x"})
            return await database.get_config_updated_at()

        stamps = asyncio.run(run())
        assert {"honeygain_email", "honeygain_password"} <= set(stamps)

    def test_ages_are_reported_without_exposing_values(self, db):
        """The age view must never carry the credential itself."""

        async def run():
            await database.set_config("grass_access_token", "super-sensitive")
            return await database.get_config_updated_at()

        stamps = asyncio.run(run())
        assert "super-sensitive" not in str(stamps)

    def test_migration_adds_updated_at_to_an_existing_database(self, db_dir):
        """An install created before this must not need a manual step."""

        async def run():
            await database.init_db()
            conn = await database._get_db()
            try:
                await conn.execute("ALTER TABLE config DROP COLUMN updated_at")
                await conn.commit()
            finally:
                await conn.close()
            await database.init_db()  # next start runs the migration
            await database.set_config("k", "v")
            return await database.get_config_updated_at()

        assert "k" in asyncio.run(run())


class TestDeclaredLifetimes:
    def test_bytelixir_short_lived_cookie_is_declared_with_a_reason(self):
        """The instance actually hit in the wild."""
        meta = credential_lifetime("bytelixir", "session_cookie")
        assert meta["hours"] == 2
        assert meta["durable"] is False
        assert "2 hours" in meta["why"]

    def test_bytelixir_offers_a_durable_alternative(self):
        assert "remember_web" in durable_alternative("bytelixir")

    def test_an_unknown_field_simply_has_no_metadata(self):
        assert credential_lifetime("honeygain", "password") is None
        assert credential_lifetime("no-such-service", "x") is None

    def test_every_declared_field_is_a_real_collector_argument(self):
        """A typo here would describe a credential that is never asked for."""
        for slug, fields in CREDENTIAL_LIFETIMES.items():
            assert slug in _COLLECTOR_ARGS, f"{slug} declares lifetimes but has no collector args"
            known = {a.lstrip("?") for a in _COLLECTOR_ARGS[slug]}
            for field in fields:
                assert field in known, f"{slug}.{field} is not a collector argument (known: {sorted(known)})"

    def test_every_declared_field_explains_itself(self):
        """A lifetime with no explanation cannot help the user decide anything."""
        for slug, fields in CREDENTIAL_LIFETIMES.items():
            for field, meta in fields.items():
                assert str(meta.get("why", "")).strip(), f"{slug}.{field} declares no reason"


class TestCredentialHealthEndpoint:
    """Age + declared lifetime must turn into an honest, actionable status."""

    def _report(self, db_path, tmp_path, stamps):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from app import main

        async def run():
            with (
                patch.object(main.database, "get_config_updated_at", AsyncMock(return_value=stamps)),
                patch.object(main, "_require_auth_api", lambda r: None),
            ):
                return await main.api_credential_health(MagicMock())

        return asyncio.run(run())

    def _stamp(self, hours_ago):
        from datetime import UTC, datetime, timedelta

        return (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat()

    def test_a_two_hour_cookie_reads_expired_after_three_hours(self, tmp_path):
        report = self._report(None, tmp_path, {"bytelixir_session_cookie": self._stamp(3)})
        entry = next(e for e in report if e["field"] == "session_cookie")
        assert entry["status"] == "likely_expired"
        assert entry["expected_lifetime_hours"] == 2

    def test_it_warns_before_it_dies_not_after(self, tmp_path):
        """The whole point: visible BEFORE earnings silently stop."""
        report = self._report(None, tmp_path, {"bytelixir_session_cookie": self._stamp(1.6)})
        entry = next(e for e in report if e["field"] == "session_cookie")
        assert entry["status"] == "expiring_soon"

    def test_a_fresh_cookie_is_fresh(self, tmp_path):
        report = self._report(None, tmp_path, {"bytelixir_session_cookie": self._stamp(0.2)})
        assert next(e for e in report if e["field"] == "session_cookie")["status"] == "fresh"

    def test_a_credential_with_no_known_expiry_is_not_alarmed_about(self, tmp_path):
        report = self._report(None, tmp_path, {"grass_access_token": self._stamp(24 * 400)})
        entry = next(e for e in report if e["service"] == "grass")
        assert entry["status"] == "no_known_expiry"

    def test_the_durable_alternative_is_suggested_when_missing(self, tmp_path):
        report = self._report(None, tmp_path, {"bytelixir_session_cookie": self._stamp(1)})
        entry = next(e for e in report if e["field"] == "session_cookie")
        assert "remember_web" in entry["durable_alternative_missing"]

    def test_no_nag_once_the_durable_credential_is_supplied(self, tmp_path):
        report = self._report(
            None,
            tmp_path,
            {
                "bytelixir_session_cookie": self._stamp(1),
                "bytelixir_remember_web": self._stamp(1),
                "bytelixir_xsrf_token": self._stamp(1),
            },
        )
        entry = next(e for e in report if e["field"] == "session_cookie")
        assert "durable_alternative_missing" not in entry

    def test_unconfigured_credentials_are_not_reported(self, tmp_path):
        assert self._report(None, tmp_path, {}) == []

    def test_no_credential_value_is_ever_returned(self, tmp_path):
        report = self._report(None, tmp_path, {"bytelixir_session_cookie": self._stamp(1)})
        assert all("value" not in e for e in report)
