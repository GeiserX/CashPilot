"""Tests for the catalog module's load/get logic."""

import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402
import yaml

from app import catalog


def _make_service_yaml(
    slug="test-svc",
    name="Test Service",
    category="bandwidth",
    status="active",
    description="A test service",
    docker=None,
):
    data = {
        "name": name,
        "slug": slug,
        "category": category,
        "status": status,
        "description": description,
        "docker": docker or {"image": "test/image:latest"},
    }
    return yaml.dump(data)


class TestLoadFromDisk:
    def test_loads_yml_files(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "testsvc.yml").write_text(_make_service_yaml("testsvc"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            services = catalog._load_from_disk()
        assert len(services) == 1
        assert services[0]["slug"] == "testsvc"

    def test_skips_underscore_files(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "_schema.yml").write_text(_make_service_yaml("schema"))
        (svc_dir / "real.yml").write_text(_make_service_yaml("real"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            services = catalog._load_from_disk()
        assert len(services) == 1
        assert services[0]["slug"] == "real"

    def test_skips_invalid_yaml(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "bad.yml").write_text("{{{{invalid yaml")
        (svc_dir / "good.yml").write_text(_make_service_yaml("good"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            services = catalog._load_from_disk()
        assert len(services) == 1

    def test_skips_non_dict_yaml(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "list.yml").write_text("- item1\n- item2\n")
        (svc_dir / "good.yml").write_text(_make_service_yaml("good"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            services = catalog._load_from_disk()
        assert len(services) == 1

    def test_skips_missing_required_fields(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "incomplete.yml").write_text(yaml.dump({"name": "Only Name"}))
        (svc_dir / "good.yml").write_text(_make_service_yaml("good"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            services = catalog._load_from_disk()
        assert len(services) == 1

    def test_missing_services_dir(self, tmp_path):
        with patch.object(catalog, "SERVICES_DIR", tmp_path / "nonexistent"):
            services = catalog._load_from_disk()
        assert services == []

    def test_loads_yaml_extension(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "svc.yaml").write_text(_make_service_yaml("svc"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            services = catalog._load_from_disk()
        assert len(services) == 1


class TestCatalogCache:
    def test_load_services_populates_cache(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "cached.yml").write_text(_make_service_yaml("cached"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            result = catalog.load_services()
        assert len(result) == 1

    def test_get_service_by_slug(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "mysvc.yml").write_text(_make_service_yaml("mysvc"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            catalog.load_services()
            svc = catalog.get_service("mysvc")
        assert svc is not None
        assert svc["slug"] == "mysvc"

    def test_get_service_missing_returns_none(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "x.yml").write_text(_make_service_yaml("x"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            catalog.load_services()
            assert catalog.get_service("nonexistent") is None

    def test_get_services_returns_copies(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "svc.yml").write_text(_make_service_yaml("svc"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            catalog.load_services()
            services1 = catalog.get_services()
            services1[0]["name"] = "MODIFIED"
            services2 = catalog.get_services()
            assert services2[0]["name"] != "MODIFIED"

    def test_get_services_by_category(self, tmp_path):
        svc_dir = tmp_path / "services" / "bandwidth"
        svc_dir.mkdir(parents=True)
        (svc_dir / "a.yml").write_text(_make_service_yaml("a", category="bandwidth"))
        (svc_dir / "b.yml").write_text(_make_service_yaml("b", category="depin"))

        with patch.object(catalog, "SERVICES_DIR", tmp_path / "services"):
            catalog.load_services()
            grouped = catalog.get_services_by_category()
        assert "bandwidth" in grouped
        assert "depin" in grouped


class TestValidate:
    def test_validate_valid(self, tmp_path):
        data = {
            "name": "Test",
            "slug": "test",
            "category": "bandwidth",
            "status": "active",
            "description": "desc",
            "docker": {"image": "test:latest"},
        }
        errors = catalog._validate(data, tmp_path / "test.yml")
        assert errors == []

    def test_validate_missing_fields(self, tmp_path):
        data = {"name": "Test"}
        errors = catalog._validate(data, tmp_path / "test.yml")
        assert len(errors) == 1
        assert "missing" in errors[0]

    def _base(self):
        return {
            "name": "Test",
            "slug": "test",
            "category": "bandwidth",
            "status": "active",
            "description": "desc",
            "docker": {"image": "test:latest", "env": [{"key": "K"}]},
        }

    def test_validate_rejects_bad_category_and_status(self, tmp_path):
        assert catalog._validate({**self._base(), "category": "bogus"}, tmp_path / "t.yml")
        assert catalog._validate({**self._base(), "status": "nope"}, tmp_path / "t.yml")

    def test_validate_rejects_malformed_docker_and_requirements(self, tmp_path):
        p = tmp_path / "t.yml"
        assert catalog._validate({**self._base(), "docker": {"image": 123}}, p)  # non-string image
        assert catalog._validate({**self._base(), "docker": {"image": "i", "env": [{"label": "no key"}]}}, p)
        assert catalog._validate({**self._base(), "docker": {"image": "i", "env": "notalist"}}, p)
        assert catalog._validate({**self._base(), "requirements": {"gpu": "yes"}}, p)  # non-bool

    def test_validate_allows_empty_image_for_non_deployable(self, tmp_path):
        # Extension/app-only services list an empty image and must still load.
        assert catalog._validate({**self._base(), "docker": {"image": ""}}, tmp_path / "t.yml") == []

    def test_all_shipped_services_pass_validation(self):
        # The loader drops an invalid entry and only logs it, so the UI simply
        # loses that service. Every file on disk must come back as a service;
        # "at least 40" let one entry vanish without failing anything.
        services_dir = Path(catalog.__file__).resolve().parents[1] / "services"
        on_disk = {p.stem for p in services_dir.rglob("*.yml") if not p.name.startswith("_")}
        loaded = {s["slug"] for s in catalog.load_services()}
        assert on_disk - loaded == set()

    def test_validate_rejects_a_malformed_port(self, tmp_path):
        p = tmp_path / "t.yml"
        for bad in ["", "9980", ":9980", "x:9980", "localhost:9980:9980", "70000:80", "9980:9980/sctp"]:
            errors = catalog._validate({**self._base(), "docker": {"image": "i", "ports": [bad]}}, p)
            assert errors and "docker.ports[0]" in errors[0], bad
        assert catalog._validate({**self._base(), "docker": {"image": "i", "ports": "9980:9980"}}, p)


class TestParsePort:
    @pytest.mark.parametrize(
        ("mapping", "expected"),
        [
            ("9981:9981", ("9981/tcp", 9981)),
            ("28967:28967/udp", ("28967/udp", 28967)),
            ("8080:80/tcp", ("80/tcp", 8080)),
            ("127.0.0.1:9980:9980", ("9980/tcp", ["127.0.0.1", 9980])),
            ("127.0.0.1:19980:9980/tcp", ("9980/tcp", ["127.0.0.1", 19980])),
        ],
    )
    def test_reads_every_form_docker_publishes(self, mapping, expected):
        assert catalog.parse_port(mapping) == expected

    @pytest.mark.parametrize("bad", ["", "9980", "[::1]:9980:9980", "0:80", "a.b.c.d:1:1"])
    def test_rejects_with_the_mapping_named(self, bad):
        with pytest.raises(ValueError, match="port"):
            catalog.parse_port(bad)
