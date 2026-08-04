"""CashPilot-1f8 / CashPilot-ahh: credentials alone must actually collect.

Settings says, in as many words: "You don't need to deploy containers through
CashPilot — just add your credentials." That was false for 12 of the 15
collectors.

Collection is driven by DEPLOYMENT ROWS — ``make_collectors`` iterates
deployments, so a slug with no row is never instantiated no matter how complete
its credentials are. ``api_set_config`` auto-created that row only for services
with no Docker image, which is three of them (grass, salad, bytelixir). For
every other service the badge flipped to "Configured" and not one reading ever
arrived.

That is the whole of user story B — someone who already runs Honeygain by hand
and wants CashPilot to track it — and it silently did nothing.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def db(tmp_path):
    from app import database

    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "t.db"):
        yield database


async def _save(config: dict) -> None:
    from app import main

    body = MagicMock()
    body.data = config
    with patch.object(main, "_require_owner", lambda r: None):
        await main.api_set_config(MagicMock(), body)


class TestCredentialsAloneStartCollection:
    @pytest.mark.asyncio
    async def test_an_image_backed_service_gets_a_tracking_row(self, db):
        """Honeygain has a Docker image, so the old gate skipped it entirely."""
        await db.init_db()
        await _save({"honeygain_email": "me@example.com", "honeygain_password": "pw"})
        rows = await db.get_deployments()
        assert [(r["slug"], r["status"]) for r in rows] == [("honeygain", "external")]

    @pytest.mark.asyncio
    async def test_the_collector_is_actually_instantiated(self, db):
        """The row only matters because make_collectors reads deployments."""
        from app.collectors import make_collectors

        await db.init_db()
        await _save({"honeygain_email": "me@example.com", "honeygain_password": "pw"})
        collectors = make_collectors(await db.get_deployments(), await db.get_config())
        assert [c.platform for c in collectors] == ["honeygain"]

    @pytest.mark.asyncio
    async def test_incomplete_credentials_create_nothing(self, db):
        """Half a credential set would produce a collector that cannot run."""
        await db.init_db()
        await _save({"honeygain_email": "me@example.com"})
        assert await db.get_deployments() == []

    @pytest.mark.asyncio
    async def test_credentials_split_across_two_requests_still_start_collection(self, db):
        """From CodeRabbit on this PR, and a real hole in the first fix.

        set_config_bulk UPSERTS, so a credential set can legitimately arrive
        across several requests — email now, password a moment later. The first
        version judged completeness against the request payload alone, so
        neither request ever saw a complete set: both values landed in the
        database and no deployment row was created. Credentials stored,
        collection still dead, and nothing on screen to say why.
        """
        await db.init_db()
        await _save({"honeygain_email": "me@example.com"})
        assert await db.get_deployments() == [], "a partial set must not create a row"
        await _save({"honeygain_password": "pw"})
        rows = await db.get_deployments()
        assert [(r["slug"], r["status"]) for r in rows] == [("honeygain", "external")]

    @pytest.mark.asyncio
    async def test_saving_one_service_does_not_sweep_the_catalog(self, db):
        """Judging against merged config must not create rows for everything.

        The scan is still scoped to the slugs this request touched, so an
        unrelated save cannot silently enable collection for a service the user
        configured long ago and has since stopped running.
        """
        await db.init_db()
        await _save({"honeygain_email": "me@example.com", "honeygain_password": "pw"})
        await _save({"iproyal_email": "x@y.z"})
        rows = await db.get_deployments()
        assert [r["slug"] for r in rows] == ["honeygain"]

    @pytest.mark.asyncio
    async def test_an_imageless_service_still_works(self, db):
        """The three services the old gate DID handle must not regress."""
        await db.init_db()
        await _save({"grass_access_token": "tok"})
        rows = await db.get_deployments()
        assert [(r["slug"], r["status"]) for r in rows] == [("grass", "external")]


class TestClearingCredentialsRemovesOnlyThePlaceholder:
    """The teardown is gated on STATUS, not on whether the service has an image.

    Gating on the image would either strand placeholders for image-backed
    services or, far worse, delete the deployment row of a container the user
    really deployed — orphaning a running container from the dashboard.
    """

    async def _clear(self, slug: str) -> None:
        from app import main

        with patch.object(main, "_require_owner", lambda r: None):
            await main.api_clear_service_config(MagicMock(), slug)

    @pytest.mark.asyncio
    async def test_the_tracking_row_is_removed(self, db):
        await db.init_db()
        await _save({"honeygain_email": "me@example.com", "honeygain_password": "pw"})
        await self._clear("honeygain")
        assert await db.get_deployments() == []

    @pytest.mark.asyncio
    async def test_a_real_deployment_survives(self, db):
        """Clearing credentials must never undeploy a running container."""
        await db.init_db()
        await db.save_deployment(slug="honeygain", container_id="abc123", status="running")
        await self._clear("honeygain")
        rows = await db.get_deployments()
        assert [(r["slug"], r["status"]) for r in rows] == [("honeygain", "running")]


class TestTheSettingsPromiseIsNowTrue:
    def test_the_gate_is_gone(self):
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert "continue  # Docker services get deployed normally" not in source

    def test_the_teardown_keys_off_status_not_the_image(self):
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert '(existing.get("status") or "") == "external"' in source

    def test_settings_still_makes_the_claim(self):
        """If this text is ever removed, the fix above is no longer load-bearing.

        Kept as a test so the promise and the behaviour move together.
        """
        html = (ROOT / "app" / "templates" / "settings.html").read_text(encoding="utf-8")
        assert "just add your credentials" in html
