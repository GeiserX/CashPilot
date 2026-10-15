"""A stored JWT says when it dies, and the credential health report believes it.

The TraffMonetizer token is a 7-day JWT that the lifetime table recorded as
"no known expiry". It expired on 2026-08-08 and nothing said so for two months.
These tests pin that a credential's own `exp` claim drives the status, ahead of
the paste date and the per-service guess, and that the value itself never
leaves the endpoint.
"""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app import main
from app.collectors import CREDENTIAL_LIFETIMES
from app.credential_expiry import jwt_times


def _seg(obj) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


def _raw_jwt(claims) -> str:
    return f"{_seg({'alg': 'HS256', 'typ': 'JWT'})}.{_seg(claims)}.signature-not-checked"


def _jwt(exp: datetime | None, iat: datetime | None = None, **extra) -> str:
    claims = dict(extra)
    if exp is not None:
        claims["exp"] = int(exp.timestamp())
    if iat is not None:
        claims["iat"] = int(iat.timestamp())
    return _raw_jwt(claims)


class TestJwtTimes:
    def test_reads_issued_and_expiry(self):
        exp = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
        iat = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
        assert jwt_times(_jwt(exp, iat)) == (iat, exp)

    def test_expiry_without_issued_at(self):
        exp = datetime(2027, 3, 20, tzinfo=UTC)
        assert jwt_times(_jwt(exp)) == (None, exp)

    def test_opaque_values_have_no_expiry(self):
        for value in ("", "abc", "a.b", "a.b.c.d", "not.base64!.here", _jwt(None, None, sub="x")):
            assert jwt_times(value) == (None, None), value

    def test_a_boolean_or_text_exp_is_ignored(self):
        assert jwt_times(_raw_jwt({"exp": True})) == (None, None)
        assert jwt_times(_raw_jwt({"exp": "2027-01-01"})) == (None, None)

    def test_an_absurd_exp_does_not_raise(self):
        assert jwt_times(_raw_jwt({"exp": 10**20})) == (None, None)

    def test_a_payload_that_is_not_an_object_is_ignored(self):
        assert jwt_times(_raw_jwt([1, 2, 3])) == (None, None)


class TestHealthReportUsesTheTokenExpiry:
    def _report(self, stamps, values):
        async def run():
            with (
                patch.object(main.database, "get_config_updated_at", AsyncMock(return_value=stamps)),
                patch.object(main.database, "get_config", AsyncMock(return_value=values)),
                patch.object(main, "_require_auth_api", lambda r: None),
            ):
                return await main.api_credential_health(MagicMock())

        return asyncio.run(run())

    def _stamp(self, hours_ago):
        return (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat()

    def _grass(self, report):
        return next(e for e in report if e["service"] == "grass")

    def test_an_expired_token_reads_expired_whatever_the_table_says(self):
        """The real TraffMonetizer failure: the table said 'no known expiry'."""
        now = datetime.now(UTC)
        token = _jwt(now - timedelta(days=60), now - timedelta(days=67))
        report = self._report({"grass_access_token": self._stamp(24 * 70)}, {"grass_access_token": token})
        assert self._grass(report)["status"] == "likely_expired"

    def test_a_token_in_its_last_day_warns_before_it_dies(self):
        now = datetime.now(UTC)
        token = _jwt(now + timedelta(hours=20), now - timedelta(days=6))
        report = self._report({"grass_access_token": self._stamp(24 * 6)}, {"grass_access_token": token})
        assert self._grass(report)["status"] == "expiring_soon"

    def test_a_long_token_is_fresh_and_shows_its_date(self):
        now = datetime.now(UTC)
        exp = now + timedelta(days=300)
        token = _jwt(exp, now - timedelta(days=65))
        report = self._report({"grass_access_token": self._stamp(24 * 65)}, {"grass_access_token": token})
        entry = self._grass(report)
        assert entry["status"] == "fresh"
        assert entry["expires_at"] == exp.replace(microsecond=0).isoformat()
        assert entry["expected_lifetime_hours"] == 24 * 365

    def test_the_last_quarter_of_a_long_token_warns(self):
        now = datetime.now(UTC)
        token = _jwt(now + timedelta(days=80), now - timedelta(days=285))
        report = self._report({"grass_access_token": self._stamp(24 * 285)}, {"grass_access_token": token})
        assert self._grass(report)["status"] == "expiring_soon"

    def test_the_token_itself_never_leaves(self):
        now = datetime.now(UTC)
        token = _jwt(now + timedelta(days=5), now)
        report = self._report({"grass_access_token": self._stamp(1)}, {"grass_access_token": token})
        assert token not in json.dumps(report)
        assert token.split(".")[1] not in json.dumps(report)

    def test_an_opaque_value_keeps_the_table_verdict(self):
        report = self._report({"grass_access_token": self._stamp(24 * 400)}, {"grass_access_token": "opaque-cookie"})
        entry = self._grass(report)
        assert entry["status"] == "no_known_expiry"
        assert "expires_at" not in entry

    def test_the_report_survives_an_unreadable_database(self):
        async def run():
            with (
                patch.object(
                    main.database,
                    "get_config_updated_at",
                    AsyncMock(return_value={"grass_access_token": self._stamp(1)}),
                ),
                patch.object(main.database, "get_config", AsyncMock(side_effect=RuntimeError("locked"))),
                patch.object(main, "_require_auth_api", lambda r: None),
            ):
                return await main.api_credential_health(MagicMock())

        report = asyncio.run(run())
        assert self._grass(report)["status"] == "no_known_expiry"


class TestTraffmonetizerDeclaresItsSevenDays:
    def test_the_token_has_a_declared_lifetime(self):
        meta = CREDENTIAL_LIFETIMES["traffmonetizer"]["token"]
        assert meta["hours"] == 24 * 7
        assert meta["durable"] is False
        assert "authToken" in meta["why"]
