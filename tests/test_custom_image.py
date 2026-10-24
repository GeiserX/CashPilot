"""The operator can run a service from an image other than the catalog's.

Requested in discussion #441: pin an image the catalog leaves floating
(`honeygain/honeygain` follows its default tag), pull from a mirror, or use a
community build. The choice is per worker, recorded with the deployment spec, and
kept by every redeploy that does not change it, the same way a typed credential
is. Everything else about the container still comes from the catalog, so a
different image gains no capability the service did not already have.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app import database, main

ROOT = Path(__file__).resolve().parents[1]

SERVICE = {
    "slug": "demo",
    "name": "Demo",
    "status": "active",
    "category": "bandwidth",
    "docker": {
        "image": "demo/demo",
        "image_by_arch": {"arm64": "demo/demo:arm64"},
        "env": [{"key": "TOKEN", "required": True, "label": "Token"}],
        "ports": [],
        "volumes": [],
    },
}


class TestTheImageField:
    @pytest.mark.parametrize(
        "ref",
        [
            "honeygain/honeygain:0.8.1",
            "registry.example.com:5000/mirror/honeygain:0.8.1",
            "ghcr.io/proxybaseorg/peer-cli@sha256:" + "a" * 64,
            "traffmonetizer/cli_v2:arm64v8",
            "busybox",
        ],
    )
    def test_a_plain_image_reference_is_accepted(self, ref):
        assert main._custom_image(ref, None) == ref

    @pytest.mark.parametrize(
        "ref",
        [
            "https://example.com/x",
            "Honeygain/Honeygain",
            "demo/demo --privileged",
            "demo:tag;rm -rf /",
            "-v/:/host",
            "a" * 300,
        ],
    )
    def test_anything_else_is_refused(self, ref):
        with pytest.raises(HTTPException) as err:
            main._custom_image(ref, None)
        assert err.value.status_code == 400

    def test_a_box_left_out_keeps_the_recorded_choice(self):
        assert main._custom_image(None, {"custom_image": "demo/demo:1.2"}) == "demo/demo:1.2"

    def test_an_empty_box_goes_back_to_the_catalog(self):
        assert main._custom_image("", {"custom_image": "demo/demo:1.2"}) == ""

    def test_no_record_and_no_box_is_the_catalog(self):
        assert main._custom_image(None, None) == ""


def _deploy(recorded, image):
    captured = {}

    async def _capture(worker_id, slug, spec):
        captured["spec"] = dict(spec)
        return {"container_id": "abc"}

    body = MagicMock()
    body.env = {"TOKEN": "t"}
    body.hostname = None
    body.image = image
    body.instances = None
    saved = AsyncMock()

    async def run():
        with (
            patch.object(main, "_require_owner", lambda r: None),
            patch.object(main.catalog, "get_service", return_value=SERVICE),
            patch.object(main, "_resolve_worker_id", AsyncMock(return_value=1)),
            patch.object(main, "_proxy_worker_deploy", _capture),
            patch.object(main.database, "get_deployment_spec", AsyncMock(return_value=recorded)),
            patch.object(main.database, "save_deployment", saved),
            patch.object(main.database, "record_health_event", AsyncMock()),
            patch.object(main, "_spawn", lambda coro: coro.close()),
            patch.object(main.metrics, "record_container_lifecycle", lambda *a: None),
        ):
            await main.api_deploy(MagicMock(), "demo", body)

    asyncio.run(run())
    return captured["spec"], saved.call_args.kwargs["spec"]


class TestTheDeploy:
    def test_a_typed_image_is_deployed_and_recorded(self):
        sent, recorded = _deploy(None, "demo/demo:1.2")
        assert sent["image"] == "demo/demo:1.2"
        assert recorded["custom_image"] == "demo/demo:1.2"

    def test_a_redeploy_without_the_box_keeps_the_choice(self):
        previous = {"image": "demo/demo:1.2", "custom_image": "demo/demo:1.2", "env": {"TOKEN": "t"}}
        sent, recorded = _deploy(previous, None)
        assert sent["image"] == "demo/demo:1.2"
        assert recorded["custom_image"] == "demo/demo:1.2"

    def test_clearing_the_box_returns_to_the_catalog(self):
        previous = {"image": "demo/demo:1.2", "custom_image": "demo/demo:1.2", "env": {"TOKEN": "t"}}
        sent, recorded = _deploy(previous, "")
        assert sent["image"] == "demo/demo"
        assert "custom_image" not in recorded

    def test_without_a_choice_the_catalog_image_is_used(self):
        sent, recorded = _deploy({"image": "demo/demo", "env": {"TOKEN": "t"}}, None)
        assert sent["image"] == "demo/demo"
        assert "custom_image" not in recorded


class TestTheWorkerHop:
    def _hop(self, spec, arch="arm64"):
        hop = AsyncMock(return_value={"ok": True})
        with (
            patch("app.main.catalog.get_service", return_value=SERVICE),
            patch("app.main._proxy_to_worker", hop),
            patch(
                "app.main.database.get_worker",
                new_callable=AsyncMock,
                return_value={"system_info": f'{{"arch": "{arch}"}}'},
            ),
        ):
            asyncio.run(main._proxy_worker_deploy(1, "demo", spec))
        return hop.call_args.kwargs["json"]

    def test_a_custom_image_is_not_replaced_by_the_arch_build(self):
        sent = self._hop({"image": "mirror/demo:1.2", "custom_image": "mirror/demo:1.2"})
        assert sent["image"] == "mirror/demo:1.2"

    def test_the_worker_is_not_sent_the_bookkeeping_key(self):
        assert "custom_image" not in self._hop({"image": "mirror/demo:1.2", "custom_image": "mirror/demo:1.2"})

    def test_the_catalog_image_still_follows_the_arch(self):
        """The control: the same hop without a choice does swap, so the test above can fail."""
        assert self._hop({"image": "demo/demo"})["image"] == "demo/demo:arm64"


@pytest.mark.real_custom_images
class TestTheRecord:
    @pytest.fixture
    def db(self, tmp_path):
        with (
            patch.object(database, "DB_DIR", tmp_path),
            patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"),
        ):
            asyncio.run(database.init_db())
            yield

    def test_only_workers_with_a_choice_are_listed(self, db):
        async def run():
            await database.save_deployment(
                slug="demo", container_id="a", spec={"image": "m/d:1", "custom_image": "m/d:1"}, worker_id=1
            )
            await database.save_deployment(slug="demo", container_id="b", spec={"image": "demo/demo"}, worker_id=2)
            return await database.get_custom_images("demo")

        assert asyncio.run(run()) == {1: "m/d:1"}


class TestTheDashboard:
    def test_a_chosen_image_is_not_reported_as_an_update(self):
        """_image_outdated compares against the image the worker was deployed from."""
        assert main._image_outdated("mirror/demo:1.2", "mirror/demo:1.2") is False
        assert main._image_outdated("mirror/demo:1.2", "demo/demo") is True

    def test_the_form_sends_the_image_only_when_changed(self):
        js = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
        body = js[js.index("async function _deployToWorkers(") :]
        body = body[: body.index("\n  function ", 1)]
        assert "_imageChoice(slug)" in body
        assert "if (image !== undefined) body.image = image" in body

    def test_the_redeploy_button_has_a_handler(self):
        js = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
        assert 'data-action="redeployWithImage"' in js
        assert "\n    redeployWithImage,\n" in js


class TestTheDeployedRow:
    """/api/services/deployed judges each instance against its own image."""

    def _row(self, custom_images):
        import json

        from fastapi.testclient import TestClient

        worker = {
            "id": 1,
            "name": "w1",
            "status": "online",
            "system_info": json.dumps({"docker_available": True}),
            "containers": json.dumps(
                [{"slug": "demo", "name": "cashpilot-demo", "status": "running", "image": "mirror/demo:1.2"}]
            ),
            "apps": "[]",
        }
        owner = {"uid": 1, "u": "owner", "r": "owner"}

        @asynccontextmanager
        async def _noop_lifespan(app):
            yield

        with (
            patch.object(main.app.router, "lifespan_context", _noop_lifespan),
            patch("app.main.auth.get_current_user", return_value=owner),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_health_scores", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_custom_images", new_callable=AsyncMock, return_value=custom_images),
            patch("app.main.catalog.get_service", return_value=SERVICE),
            TestClient(main.app, raise_server_exceptions=False) as client,
        ):
            resp = client.get("/api/services/deployed")
        assert resp.status_code == 200, resp.text
        return resp.json()[0]

    def test_an_instance_on_its_chosen_image_is_not_outdated(self):
        row = self._row({1: "mirror/demo:1.2"})
        assert row["image_outdated"] is False
        assert row["instance_details"][0]["custom_image"] == "mirror/demo:1.2"

    def test_the_same_image_without_a_record_is_outdated(self):
        """The control: with no recorded choice the catalog decides, so the test above can fail."""
        row = self._row({})
        assert row["image_outdated"] is True
        assert row["instance_details"][0]["custom_image"] is None
