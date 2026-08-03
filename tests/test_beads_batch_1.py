"""Regression tests for the first batch of verified audit beads.

Each class names the bead it closes. All ten were independently re-verified
against this branch before being fixed — the audit's own adversarial pass had
already refuted 13 of 94 findings, so nothing here was taken on trust.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"


class TestUnknownCredentialAgeIsNotFabricatedAsFresh:
    """CashPilot-c1q / CashPilot-i21 (one defect, filed twice).

    The updated_at migration back-filled every pre-existing row with
    datetime('now'), so an upgraded volume reported every credential as brand
    new — including a Bytelixir session cookie that expires after two hours and
    had in fact expired days earlier. Unknown age rendered as the most
    favourable known age.
    """

    def test_the_migration_does_not_stamp_existing_rows(self):
        source = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
        assert "UPDATE config SET updated_at = datetime('now')" not in source

    @pytest.mark.asyncio
    async def test_a_pre_migration_row_reports_unknown_age(self, tmp_path):
        """End-to-end: an old-schema config table upgraded in place."""
        import aiosqlite

        from app import database

        db_path = tmp_path / "old.db"
        async with aiosqlite.connect(db_path) as db:
            await db.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT)")
            await db.execute("INSERT INTO config (key, value) VALUES ('bytelixir_session_cookie', 'x')")
            await db.commit()

        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", db_path):
            await database.init_db()
            stamps = await database.get_config_updated_at()

        assert "bytelixir_session_cookie" not in stamps, (
            "an upgraded row was stamped with the upgrade time and will read as fresh"
        )


class TestAStoredFlagMeansWhatItSays:
    """CashPilot-153: bool() on a TEXT config value.

    "false", "0" and "no" were all truthy, and the flag decides whether the
    fleet page says "turning it off would save that" or "this machine would be
    on anyway" — opposite advice from the same setting.
    """

    @pytest.mark.parametrize("value", ["false", "False", "0", "no", "off", "", "  "])
    def test_falsey_strings_are_false(self, value):
        from app.main import _config_flag

        assert _config_flag({"k": value}, "k") is False

    @pytest.mark.parametrize("value", ["true", "True", "1", "yes", "on"])
    def test_truthy_strings_are_true(self, value):
        from app.main import _config_flag

        assert _config_flag({"k": value}, "k") is True

    def test_an_absent_key_is_false(self):
        from app.main import _config_flag

        assert _config_flag({}, "k") is False

    def test_the_endpoint_uses_it(self):
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert "dedicated=bool(config.get(" not in source


class TestTheLegacyTariffKeyWorksEverywhere:
    """CashPilot-a02: one endpoint honoured the old key name, the other did not.

    An upgrading user who had set electricity_price_per_kwh saw running costs
    on the fleet page and "cost unknown" on the dashboard, from one value.
    """

    def test_both_key_names_resolve(self):
        from app.main import _tariff_price

        assert _tariff_price({"power_price_per_kwh": "0.20"}) == 0.20
        assert _tariff_price({"electricity_price_per_kwh": "0.21"}) == 0.21

    def test_the_current_name_wins_when_both_are_set(self):
        from app.main import _tariff_price

        assert _tariff_price({"power_price_per_kwh": "0.20", "electricity_price_per_kwh": "0.99"}) == 0.20

    def test_neither_set_is_zero_not_an_error(self):
        from app.main import _tariff_price

        assert _tariff_price({}) == 0.0

    def test_no_endpoint_reads_the_key_directly_any_more(self):
        """The asymmetry could only exist because two sites parsed it themselves."""
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        body = source[source.index("def _tariff_price") + 100 :]
        assert 'cfg.get("power_price_per_kwh") or 0' not in body

    @pytest.mark.asyncio
    async def test_the_legacy_key_alone_makes_cost_known(self):
        """The user-visible symptom, not just the helper."""
        from app import main

        cfg = {"electricity_price_per_kwh": "0.20", "power_currency": "EUR"}
        with (
            patch.object(main, "_require_auth_api", lambda r: None),
            patch.object(main.database, "get_config", AsyncMock(return_value=cfg)),
            patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=[])),
            patch.object(main.database, "list_workers", AsyncMock(return_value=[])),
            patch.object(main.database, "get_earned_by_platform", AsyncMock(return_value={})),
        ):
            out = await main.api_earnings_net(MagicMock(), days=30)
        assert out["cost_known"] is True, "the legacy tariff key still reads as no tariff set"


class TestTheAdminSchemaIsNotPublished:
    """CashPilot-4ks: /docs, /redoc and /openapi.json were unauthenticated.

    The schema is a complete map of the admin surface — every route, parameter
    and body shape, including the worker and payout endpoints.
    """

    def test_the_interactive_docs_are_disabled(self):
        from app.main import app

        assert app.docs_url is None
        assert app.redoc_url is None

    def test_the_schema_endpoint_is_disabled(self):
        from app.main import app

        assert app.openapi_url is None

    def test_no_route_serves_them(self):
        from app.main import app

        paths = {getattr(r, "path", "") for r in app.routes}
        assert not paths & {"/docs", "/redoc", "/openapi.json"}


class TestAPartiallyConfiguredCollectorSaysSo:
    """CashPilot-0id: `.some` meant one of two credentials read as Configured.

    The server skipped that collector for the missing field, so the badge
    asserted the opposite of what was happening — it silently never collected.
    """

    def test_the_badge_requires_every_required_field(self):
        source = APP_JS.read_text(encoding="utf-8")
        assert "setCount === required.length" in source
        assert "const configured = col.fields.some(" not in source

    def test_there_is_a_distinct_incomplete_state(self):
        """Configured and untouched are not the only two possibilities."""
        source = APP_JS.read_text(encoding="utf-8")
        assert "Incomplete" in source
        assert "const partial =" in source

    def test_optional_fields_do_not_block_it(self):
        """Bytelixir's durable cookies are optional; requiring them would lie the other way."""
        source = APP_JS.read_text(encoding="utf-8")
        assert "col.fields.filter(f => f.required)" in source


class TestTheCredentialHintReachesSettings:
    """CashPilot-0rw: the hint was rendered only in the modal.

    services/_schema.yml says it is "shown next to the input in Settings" —
    the one screen a tracking-only user actually uses.
    """

    def test_the_collector_body_renders_it(self):
        source = APP_JS.read_text(encoding="utf-8")
        body = source[source.index('<div class="collector-body">') :][:400]
        assert "col.hint" in body

    def test_it_goes_through_the_sanitiser(self):
        """The hints contain anchors, so raw insertion would be an XSS sink."""
        source = APP_JS.read_text(encoding="utf-8")
        body = source[source.index('<div class="collector-body">') :][:400]
        assert "sanitizeHint(col.hint)" in body


class TestChangingTheEntrypointBuildsAnImage:
    """CashPilot-x2r: entrypoint.sh is the ENTRYPOINT of both images.

    It was in neither the release paths filter nor either detect regex, so a
    change to the privilege-drop and Docker-socket-group script shipped no
    image at all.
    """

    def _release(self) -> str:
        return (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    def test_it_triggers_the_workflow(self):
        assert "- 'entrypoint.sh'" in self._release()

    def test_it_builds_both_images(self):
        """It is COPY'd into both, so one regex is not enough."""
        source = self._release()
        assert source.count("entrypoint\\.sh") >= 2

    def test_it_really_is_in_both_dockerfiles(self):
        """If this stops being true, the two-regex requirement above changes."""
        for name in ("Dockerfile", "Dockerfile.worker"):
            assert "entrypoint.sh" in (ROOT / name).read_text(encoding="utf-8")


class TestASuppliedEncryptionKeyIsNotTreatedAsEphemeral:
    """CashPilot-w3g: startup refused when the key file could not be written.

    A key supplied through CASHPILOT_ENCRYPTION_KEY is identical on every
    restart, so failing to cache it loses nothing. The refusal told the user to
    "supply a key via CASHPILOT_ENCRYPTION_KEY" — which they already had.
    """

    def test_the_flag_is_conditional_on_where_the_key_came_from(self):
        source = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
        assert "_fernet_key_is_ephemeral = env_key is None" in source
        assert "_fernet_key_is_ephemeral = True\n        _logger.error" not in source

    def test_a_minted_key_is_still_ephemeral_when_unwritable(self):
        """The guard must keep working for the case it was built for."""
        source = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
        assert "env_key is None" in source


class TestTheSaladHintPointsAtAHostThatExists:
    """CashPilot-ecc: app.salad.com does not resolve. The dashboard is app.salad.io."""

    def test_the_hint_uses_the_working_host(self):
        text = (ROOT / "services" / "compute" / "salad.yml").read_text(encoding="utf-8")
        assert "app.salad.com" not in text
        assert "app.salad.io" in text

    def test_it_matches_the_dashboard_url_in_the_same_file(self):
        """The right host was already in the file, three lines away."""
        text = (ROOT / "services" / "compute" / "salad.yml").read_text(encoding="utf-8")
        hint = re.search(r"credential_hint: \"(.*)\"", text)
        assert hint and "app.salad.io" in hint.group(1)


class TestTheDocsDescribeTheCodeThatExists:
    """CashPilot-i5l: CLAUDE.md described a synthetic baseline row.

    No such code exists — `grep -rni synthetic app/` returns nothing. The
    documented outcome is delivered by the no-predecessor rule instead.
    """

    def test_no_synthetic_baseline_is_claimed(self):
        text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        assert "insert synthetic baseline record" not in text

    def test_no_synthetic_baseline_is_written(self):
        """The doc was wrong, so the fix is to the doc — assert that stays true."""
        for path in (ROOT / "app").rglob("*.py"):
            assert "synthetic" not in path.read_text(encoding="utf-8").lower(), path.name


def test_the_batch_touched_ten_beads():
    """A count, so a silently dropped fix is visible in review."""
    classes = [name for name, obj in globals().items() if name.startswith("Test") and isinstance(obj, type)]
    assert len(classes) == 10, f"expected 10 bead classes, found {len(classes)}: {sorted(classes)}"
