"""A worker on ARM gets the ARM build of an image Docker cannot select itself.

Docker Hub labels every tag of traffmonetizer/cli_v2 linux/amd64, the real ARM
builds included (checked by reading the ELF header of usr/local/bin/cli in each
tag: latest is x86_64, arm64v8 is aarch64, arm32v7 is arm32). Docker therefore
never picks the ARM tag on an ARM host, and a Raspberry Pi worker deploying the
catalog's default tag got an x86_64 binary that cannot start, while the catalog
promised arm64 support.

The catalog now names the tag per architecture family and the dashboard picks
it from the architecture the worker reports in its heartbeat. The worker is
untouched: it runs whatever image it is told, so no worker upgrade is needed.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient

from app import catalog
from app.main import _image_for_arch, app
from tests.test_main_routes import _auth_owner

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _traffmonetizer_docker() -> dict:
    with open(ROOT / "services" / "bandwidth" / "traffmonetizer.yml") as f:
        return yaml.safe_load(f)["docker"]


class TestTheCatalogNamesTheArmBuilds:
    def test_traffmonetizer_declares_a_tag_per_arm_family(self):
        docker = _traffmonetizer_docker()
        assert docker["image"] == "traffmonetizer/cli_v2"
        assert docker["image_by_arch"] == {
            "arm64": "traffmonetizer/cli_v2:arm64v8",
            "arm": "traffmonetizer/cli_v2:arm32v7",
        }

    def test_the_platforms_it_promises_are_the_ones_it_can_deliver(self):
        assert set(_traffmonetizer_docker()["platforms"]) == {"linux/amd64", "linux/arm64", "linux/arm/v7"}

    def test_the_real_entry_passes_validation(self):
        path = ROOT / "services" / "bandwidth" / "traffmonetizer.yml"
        with open(path) as f:
            assert catalog._validate(yaml.safe_load(f), path) == []

    @pytest.mark.parametrize("bad", ["traffmonetizer/cli_v2:arm64v8", ["arm64"], {"arm64": 7}, {3: "x"}])
    def test_a_malformed_map_is_rejected_at_load(self, tmp_path, bad):
        """A service with an error is skipped at load, which is the loud failure we want here."""
        data = {
            "name": "T",
            "slug": "t",
            "category": "bandwidth",
            "status": "active",
            "description": "d",
            "docker": {"image": "x/y", "image_by_arch": bad},
        }
        errors = catalog._validate(data, tmp_path / "t.yml")
        assert len(errors) == 1 and "image_by_arch" in errors[0]


class TestTheImageFollowsTheWorkerArchitecture:
    DOCKER = {
        "image": "traffmonetizer/cli_v2",
        "image_by_arch": {"arm64": "traffmonetizer/cli_v2:arm64v8", "arm": "traffmonetizer/cli_v2:arm32v7"},
    }

    @pytest.mark.parametrize(
        ("machine", "expected"),
        [
            ("x86_64", "traffmonetizer/cli_v2"),
            ("amd64", "traffmonetizer/cli_v2"),
            ("aarch64", "traffmonetizer/cli_v2:arm64v8"),  # Linux, the Raspberry Pi 4/5 case
            ("arm64", "traffmonetizer/cli_v2:arm64v8"),  # macOS reports it this way
            (" AArch64 ", "traffmonetizer/cli_v2:arm64v8"),
            ("armv7l", "traffmonetizer/cli_v2:arm32v7"),  # 32-bit Raspberry Pi OS
            ("armv6l", "traffmonetizer/cli_v2:arm32v7"),
            ("riscv64", "traffmonetizer/cli_v2"),  # no build named: the default, not nothing
            ("", "traffmonetizer/cli_v2"),
            (None, "traffmonetizer/cli_v2"),  # an old worker that sends no arch
        ],
    )
    def test_each_reported_machine_gets_its_build(self, machine, expected):
        assert _image_for_arch(self.DOCKER, machine) == expected

    def test_an_entry_without_the_map_is_untouched(self):
        assert _image_for_arch({"image": "mysteriumnetwork/myst"}, "aarch64") == "mysteriumnetwork/myst"

    def test_a_blank_override_falls_back_to_the_default(self):
        docker = {"image": "x/y", "image_by_arch": {"arm64": "  "}}
        assert _image_for_arch(docker, "aarch64") == "x/y"

    def test_no_image_at_all_stays_none(self):
        """The route turns None into its 400, so the resolver must not invent a value."""
        assert _image_for_arch({"image_by_arch": {"arm64": "x:y"}}, "x86_64") is None


class TestTheDeployRouteSendsTheWorkerItsBuild:
    """End to end through /api/deploy, stubbing only the HTTP hop to the worker."""

    SVC = {
        "slug": "traffmonetizer",
        "name": "Traffmonetizer",
        "status": "active",
        "docker": {
            "image": "traffmonetizer/cli_v2",
            "image_by_arch": {"arm64": "traffmonetizer/cli_v2:arm64v8", "arm": "traffmonetizer/cli_v2:arm32v7"},
            "env": [{"key": "TRAFFMONETIZER_TOKEN", "required": True}],
            "command": "start accept --token ${TRAFFMONETIZER_TOKEN}",
        },
    }

    def _deploy_to(self, client, worker, query=""):
        """Return (JSON the worker received, spec the dashboard recorded)."""
        sent = {}

        async def _fake_hop(worker_id, method, path, *, json=None, params=None, timeout=30):
            sent.update(json or {})
            return {"container_id": "abc123"}

        save = AsyncMock()
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.catalog.get_service", return_value=self.SVC),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.get_deployment", new_callable=AsyncMock, return_value=None),
            patch("app.main._proxy_to_worker", side_effect=_fake_hop),
            patch("app.main.database.save_deployment", save),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main._run_collection", new_callable=AsyncMock),
        ):
            resp = client.post(f"/api/deploy/traffmonetizer{query}", json={"env": {"TRAFFMONETIZER_TOKEN": "t"}})
        assert resp.status_code == 200, resp.text
        return sent, save.call_args.kwargs["spec"]

    @pytest.mark.parametrize(
        ("system_info", "expected"),
        [
            ('{"arch": "aarch64"}', "traffmonetizer/cli_v2:arm64v8"),
            ('{"arch": "armv7l"}', "traffmonetizer/cli_v2:arm32v7"),
            ('{"arch": "x86_64"}', "traffmonetizer/cli_v2"),
            ("{}", "traffmonetizer/cli_v2"),
            ("not json", "traffmonetizer/cli_v2"),  # a corrupt row must not block the deploy
        ],
    )
    def test_the_worker_receives_the_build_for_its_architecture(self, client, system_info, expected):
        worker = {"id": 1, "name": "pi", "status": "online", "url": "http://10.0.0.2:8081", "system_info": system_info}
        sent, _ = self._deploy_to(client, worker)
        assert sent["image"] == expected

    def test_the_record_keeps_the_fleet_wide_default(self, client):
        """One deployment row serves every worker, so a Pi's tag must not be replayed onto an x86 box."""
        worker = {
            "id": 1,
            "name": "pi",
            "status": "online",
            "url": "http://10.0.0.2:8081",
            "system_info": '{"arch": "aarch64"}',
        }
        sent, recorded = self._deploy_to(client, worker)
        assert sent["image"] == "traffmonetizer/cli_v2:arm64v8"
        assert recorded["image"] == "traffmonetizer/cli_v2"

    def test_a_worker_row_that_is_missing_deploys_the_default(self, client):
        """get_worker returned None for a worker that resolved a moment earlier."""
        worker = {"id": 1, "name": "w", "status": "online", "url": "http://10.0.0.2:8081"}
        sent = {}

        async def _fake_hop(worker_id, method, path, *, json=None, params=None, timeout=30):
            sent.update(json or {})
            return {"container_id": "abc123"}

        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.catalog.get_service", return_value=self.SVC),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=None),
            patch("app.main.database.get_deployment", new_callable=AsyncMock, return_value=None),
            patch("app.main._proxy_to_worker", side_effect=_fake_hop),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main._run_collection", new_callable=AsyncMock),
        ):
            resp = client.post("/api/deploy/traffmonetizer", json={"env": {"TRAFFMONETIZER_TOKEN": "t"}})
        assert resp.status_code == 200, resp.text
        assert sent["image"] == "traffmonetizer/cli_v2"

    def test_an_entry_without_the_map_never_looks_the_worker_up(self):
        """The extra query is paid only by entries that need it; storj's direct-call test stubs no database."""
        import asyncio

        from app import main

        hop = AsyncMock(return_value={"ok": True})
        svc = {"slug": "storj", "docker": {"image": "storjlabs/storagenode"}}
        with (
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main._proxy_to_worker", hop),
            patch("app.main.database.get_worker", new_callable=AsyncMock) as lookup,
        ):
            asyncio.run(main._proxy_worker_deploy(1, "storj", {"image": "storjlabs/storagenode"}))
        lookup.assert_not_awaited()
        assert hop.call_args.kwargs["json"]["image"] == "storjlabs/storagenode"
