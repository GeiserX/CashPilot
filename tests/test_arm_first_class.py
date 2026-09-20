"""ARM is a supported target, not a tolerated one.

Three things had to be true for that, and each has its class here:

* one vocabulary for CPU architecture (app/arch.py), shared by the deploy
  proxy, the catalog validator, the preflight and the compose export;
* the preflight tells an ARM worker, before deploying, that a provider has no
  build for its CPU, instead of letting the container die with
  "exec format error" behind a red row that explained nothing;
* the compose export, which has no worker to ask, can be told the target.
"""

from unittest.mock import AsyncMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient

from app import arch, catalog, compose_generator, preflight
from app.main import app
from tests.test_main_routes import _auth_owner


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestOneVocabulary:
    @pytest.mark.parametrize(
        ("machine", "fam"),
        [
            ("x86_64", "amd64"),
            ("aarch64", "arm64"),  # Linux on a Pi 4/5 (64-bit OS)
            ("arm64", "arm64"),  # macOS
            ("arm64-v8a", "arm64"),  # what the Android worker really sends
            ("armv7l", "arm"),  # 32-bit Pi OS
            ("armv6l", "arm"),
            ("armeabi-v7a", "arm"),
            ("arm", "arm"),  # a family name maps to itself, so the export can take one
            ("riscv64", None),
            ("", None),
            (None, None),
        ],
    )
    def test_machine_names_fold_to_a_family(self, machine, fam):
        assert arch.family(machine) == fam

    @pytest.mark.parametrize(
        ("platform", "fam"),
        [
            ("linux/amd64", "amd64"),
            ("linux/arm64/v8", "arm64"),
            ("linux/arm/v7", "arm"),
            ("linux/386", None),
            ("windows/amd64", None),
        ],
    )
    def test_manifest_platforms_fold_to_a_family(self, platform, fam):
        assert arch.platform_family(platform) == fam

    def test_the_catalog_validator_and_the_resolver_share_the_set(self):
        assert catalog.IMAGE_ARCH_FAMILIES == arch.FAMILIES
        assert set(arch.MACHINE_FAMILY.values()) == set(arch.FAMILIES)

    def test_supported_families_reads_platforms_and_overrides(self):
        docker = {"image": "x/y", "platforms": ["linux/amd64"], "image_by_arch": {"arm64": "x/y:arm64v8"}}
        assert arch.supported_families(docker) == {"amd64", "arm64"}
        assert arch.supported_families({"image": "x/y"}) == set()

    def test_every_catalog_platform_is_a_family_we_model(self):
        """A platform string nothing folds would be invisible to the preflight."""
        for svc in catalog.get_services():
            docker = svc.get("docker") or {}
            if not docker.get("image"):
                continue  # extension-only entries list "browser-extension" there; no image, nothing to run
            for p in docker.get("platforms") or []:
                assert arch.platform_family(p), f"{svc['slug']} declares {p}, which folds to nothing"


class TestThePreflightSaysWhenThereIsNoBuild:
    AMD64_ONLY = {
        "slug": "proxylite",
        "name": "ProxyLite",
        "docker": {"image": "proxylite/proxyservice", "platforms": ["linux/amd64"]},
    }
    MULTI = {
        "slug": "bitping",
        "name": "Bitping",
        "docker": {"image": "bitping/bitpingd", "platforms": ["linux/amd64", "linux/arm64"]},
    }
    OVERRIDE = {
        "slug": "traffmonetizer",
        "name": "Traffmonetizer",
        "docker": {
            "image": "traffmonetizer/cli_v2",
            "platforms": ["linux/amd64"],
            "image_by_arch": {"arm64": "traffmonetizer/cli_v2:arm64v8"},
        },
    }

    def _worst_arch_finding(self, result):
        return [f for f in result["findings"] if "publishes no build" in f["message"]]

    def test_an_arm_worker_is_told_before_deploying_an_amd64_only_image(self):
        result = preflight.assess(self.AMD64_ONLY, system_info={"arch": "aarch64"})
        [finding] = self._worst_arch_finding(result)
        assert finding["verdict"] == preflight.EARNS_NOTHING
        assert result["verdict"] == preflight.EARNS_NOTHING
        assert "64-bit ARM (aarch64)" in finding["message"]
        assert "only x86-64" in finding["message"]
        assert "exec format error" in finding["message"]
        assert "cannot check" in finding["message"]  # emulation is stated as unverified, not denied
        assert result["blocking"] is False  # informed consent, as the module promises

    def test_a_32_bit_pi_is_told_too(self):
        result = preflight.assess(self.MULTI, system_info={"arch": "armv7l"})
        [finding] = self._worst_arch_finding(result)
        assert "32-bit ARM (armv7l)" in finding["message"]

    def test_a_worker_with_a_build_hears_nothing(self):
        for machine in ("x86_64", "aarch64"):
            result = preflight.assess(self.MULTI, system_info={"arch": machine})
            assert not self._worst_arch_finding(result)
            assert "whether the image has a build for this CPU" not in result["not_checked"]

    def test_an_override_counts_as_a_build(self):
        result = preflight.assess(self.OVERRIDE, system_info={"arch": "aarch64"})
        assert not self._worst_arch_finding(result)

    @pytest.mark.parametrize("system_info", [{}, {"arch": ""}, {"arch": "riscv64"}])
    def test_an_unknown_cpu_is_reported_as_unchecked_not_passed(self, system_info):
        """An old worker sends no arch; never turn silence into a green light."""
        result = preflight.assess(self.AMD64_ONLY, system_info=system_info)
        assert not self._worst_arch_finding(result)
        assert "whether the image has a build for this CPU" in result["not_checked"]

    def test_an_entry_declaring_nothing_is_unchecked_not_failed(self):
        svc = {"slug": "x", "name": "X", "docker": {"image": "x/y"}}
        result = preflight.assess(svc, system_info={"arch": "aarch64"})
        assert not self._worst_arch_finding(result)
        assert "whether the image has a build for this CPU" in result["not_checked"]

    def test_a_service_without_an_image_says_nothing_about_cpus(self):
        svc = {"slug": "grass", "name": "Grass", "docker": {"image": ""}, "platforms": ["browser_extension"]}
        result = preflight.assess(svc, system_info={"arch": "aarch64"})
        assert not self._worst_arch_finding(result)
        assert "whether the image has a build for this CPU" not in result["not_checked"]

    def test_the_route_carries_it_for_a_real_worker(self, client):
        worker = {
            "id": 7,
            "name": "pi",
            "status": "online",
            "url": "http://10.0.0.7:8081",
            "system_info": '{"arch": "aarch64"}',
        }
        with (
            _auth_owner(),
            patch("app.main.catalog.get_service", return_value=self.AMD64_ONLY),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
        ):
            resp = client.get("/api/services/proxylite/preflight?worker_id=7")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["worker_arch"] == "aarch64"
        assert any("publishes no build" in f["message"] for f in body["findings"])


class TestTheComposeExportCanBeToldTheTarget:
    def _traffmonetizer(self):
        with open(catalog.SERVICES_DIR / "bandwidth" / "traffmonetizer.yml") as f:
            return yaml.safe_load(f)

    def test_the_generator_picks_the_build_for_the_arch(self):
        svc = self._traffmonetizer()
        for target, expected in (
            (None, "traffmonetizer/cli_v2"),
            ("amd64", "traffmonetizer/cli_v2"),
            ("arm64", "traffmonetizer/cli_v2:arm64v8"),
            ("aarch64", "traffmonetizer/cli_v2:arm64v8"),  # a raw machine name is accepted
            ("arm", "traffmonetizer/cli_v2:arm32v7"),
        ):
            block = compose_generator._service_to_compose(svc, {"TRAFFMONETIZER_TOKEN": "t"}, arch=target)
            assert block["image"] == expected, target

    def test_an_entry_without_overrides_is_unchanged_by_the_arch(self):
        svc = {
            "slug": "bitping",
            "name": "Bitping",
            "category": "bandwidth",
            "docker": {"image": "bitping/bitpingd", "env": []},
        }
        assert compose_generator._service_to_compose(svc, arch="arm64")["image"] == "bitping/bitpingd"

    def _get(self, client, path):
        with _auth_owner():
            return client.get(path)

    def test_the_single_export_route_honours_arch(self, client):
        text = self._get(client, "/api/compose/traffmonetizer?arch=arm64").text
        assert "traffmonetizer/cli_v2:arm64v8" in text
        assert "traffmonetizer/cli_v2:arm64v8" not in self._get(client, "/api/compose/traffmonetizer").text

    def test_the_multi_export_route_honours_arch(self, client):
        with _auth_owner():
            resp = client.post("/api/compose", json={"slugs": ["traffmonetizer", "bitping"], "arch": "arm"})
        assert resp.status_code == 200, resp.text
        assert "traffmonetizer/cli_v2:arm32v7" in resp.text
        assert "bitping/bitpingd" in resp.text

    def test_the_all_export_route_honours_arch(self, client):
        assert "traffmonetizer/cli_v2:arm64v8" in self._get(client, "/api/compose?arch=aarch64").text

    def test_a_made_up_arch_is_a_400_not_a_silent_default(self, client):
        resp = self._get(client, "/api/compose/traffmonetizer?arch=sparc")
        assert resp.status_code == 400
        assert "amd64" in resp.text and "arm64" in resp.text
