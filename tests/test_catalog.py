"""Validate all YAML service definitions against the schema."""

from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVICES_DIR = PROJECT_ROOT / "services"
CATEGORIES = {"bandwidth", "depin", "storage", "compute"}
VALID_STATUSES = {"active", "beta", "broken", "dead", "dropped"}

REQUIRED_FIELDS = {"name", "slug", "category", "status", "website", "description"}


def _discover_yamls():
    """Find all service YAML files across category subdirectories."""
    yamls = []
    for category_dir in SERVICES_DIR.iterdir():
        if not category_dir.is_dir() or category_dir.name.startswith("_"):
            continue
        for yml in category_dir.glob("*.yml"):
            if yml.name.startswith("_"):
                continue
            yamls.append(yml)
    return sorted(yamls, key=lambda p: p.name)


ALL_YAMLS = _discover_yamls()


@pytest.mark.parametrize("yml_path", ALL_YAMLS, ids=[y.stem for y in ALL_YAMLS])
class TestServiceYAML:
    def test_parses_without_error(self, yml_path):
        with open(yml_path) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict), f"{yml_path.name} did not parse to a dict"

    def test_required_fields_present(self, yml_path):
        with open(yml_path) as f:
            data = yaml.safe_load(f)
        missing = REQUIRED_FIELDS - set(data.keys())
        assert not missing, f"{yml_path.name} missing fields: {missing}"

    def test_category_valid(self, yml_path):
        with open(yml_path) as f:
            data = yaml.safe_load(f)
        assert data["category"] in CATEGORIES, f"Invalid category: {data['category']}"

    def test_status_valid(self, yml_path):
        with open(yml_path) as f:
            data = yaml.safe_load(f)
        assert data["status"] in VALID_STATUSES, f"Invalid status: {data['status']}"

    def test_docker_has_image(self, yml_path):
        with open(yml_path) as f:
            data = yaml.safe_load(f)
        if "docker" in data and data["docker"]:
            assert "image" in data["docker"], f"{yml_path.name}: docker section missing image"

    def test_docker_section_present(self, yml_path):
        """Runtime catalog loader expects a docker section on every service."""
        with open(yml_path) as f:
            data = yaml.safe_load(f)
        assert "docker" in data, f"{yml_path.name}: missing docker section (required at runtime)"

    def test_volumes_are_strings(self, yml_path):
        """Deploy code splits volumes on ':'. Mappings break it."""
        with open(yml_path) as f:
            data = yaml.safe_load(f)
        volumes = (data.get("docker") or {}).get("volumes") or []
        for v in volumes:
            assert isinstance(v, str), (
                f"{yml_path.name}: volume must be a colon-delimited string, got {type(v).__name__}: {v}"
            )

    def test_slug_matches_filename(self, yml_path):
        with open(yml_path) as f:
            data = yaml.safe_load(f)
        assert data["slug"] == yml_path.stem, f"Slug '{data['slug']}' does not match filename '{yml_path.stem}'"


def test_no_duplicate_slugs():
    slugs = []
    for yml_path in ALL_YAMLS:
        with open(yml_path) as f:
            data = yaml.safe_load(f)
        slugs.append(data["slug"])
    duplicates = [s for s in slugs if slugs.count(s) > 1]
    assert not duplicates, f"Duplicate slugs found: {set(duplicates)}"


def test_repocket_container_env_keys():
    """Regression for #82: the repocket/repocket image reads RP_EMAIL + RP_API_KEY.

    A prior 'audit' (PR #46) renamed these to REPOCKET_EMAIL/REPOCKET_PASSWORD to
    match the earnings collector's auth model, which silently broke deployment —
    the container ignores unknown env vars and logs 'User credentials are missing!'.
    The container env contract is independent of the collector's Firebase login.
    """
    repocket = SERVICES_DIR / "bandwidth" / "repocket.yml"
    with open(repocket) as f:
        data = yaml.safe_load(f)
    env_keys = {e["key"] for e in data["docker"]["env"]}
    assert env_keys == {"RP_EMAIL", "RP_API_KEY"}, (
        f"Repocket container env must be exactly RP_EMAIL + RP_API_KEY, got {env_keys}"
    )
    by_key = {e["key"]: e for e in data["docker"]["env"]}
    assert by_key["RP_API_KEY"]["secret"] is True, "RP_API_KEY must be marked secret"
    assert by_key["RP_API_KEY"]["required"] is True, "RP_API_KEY must be required"
    assert by_key["RP_EMAIL"]["required"] is True, "RP_EMAIL must be required"
