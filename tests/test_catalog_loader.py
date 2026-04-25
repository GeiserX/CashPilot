"""Tests for the catalog module's load/get logic."""

import os
from unittest.mock import patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

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
