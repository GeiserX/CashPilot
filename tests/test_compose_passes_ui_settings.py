"""A UI setting the docs tell you to put in .env must reach the UI container.

The compose files have no ``env_file``, so Compose passes a variable into the
container only when the service's ``environment`` list names it. The docs and
cashpilot-mcp told users to set ``CASHPILOT_READONLY_API_KEY`` and
``CASHPILOT_METRICS_ENABLED`` in ``.env``, but no compose file passed them on:
the read-only key got 401 on every call and ``/metrics`` stayed 404.

This holds every file that ships the UI to the same list: the root compose
files, the CasaOS and Runtipi packages and the Unraid template.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

#: UI settings a user sets in .env (or the store's form) on a running install.
UI_SETTINGS = (
    "CASHPILOT_READONLY_API_KEY",
    "CASHPILOT_METRICS_ENABLED",
    "CASHPILOT_METRICS_TOKEN",
)

ROOT_COMPOSE = ("docker-compose.yml", "docker-compose.fleet.yml", "docker-compose.build.yml")


def _ui_environment(path: Path, service: str) -> dict[str, str]:
    env = yaml.safe_load(path.read_text(encoding="utf-8"))["services"][service]["environment"]
    if isinstance(env, dict):
        return {k: str(v) for k, v in env.items()}
    return dict(item.split("=", 1) for item in env)


@pytest.mark.parametrize("name", ROOT_COMPOSE)
@pytest.mark.parametrize("var", UI_SETTINGS + ("CASHPILOT_ADMIN_API_KEY",))
def test_the_root_compose_files_pass_the_setting_from_env(name, var):
    env = _ui_environment(ROOT / name, "cashpilot-ui")
    assert var in env, f"{name}: a {var} set in .env never reaches the UI"
    assert re.fullmatch(r"\$\{" + var + r"(:-[^}]*)?\}", env[var]), (
        f"{name}: {var} must come from .env as ${{{var}:-...}}, not a fixed value: {env[var]!r}"
    )


@pytest.mark.parametrize("var", UI_SETTINGS)
def test_the_casaos_package_offers_the_setting(var):
    path = ROOT / "contrib/app-stores/casaos/CashPilot/docker-compose.yml"
    assert var in _ui_environment(path, "cashpilot-ui")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    listed = {e["container"] for e in doc["services"]["cashpilot-ui"]["x-casaos"]["envs"]}
    assert var in listed, f"CasaOS shows no field for {var}, so nobody can set it"


@pytest.mark.parametrize("var", UI_SETTINGS)
def test_the_runtipi_package_offers_the_setting(var):
    folder = ROOT / "contrib/app-stores/runtipi/cashpilot"
    assert _ui_environment(folder / "docker-compose.yml", "cashpilot").get(var) == f"${{{var}}}"
    fields = json.loads((folder / "config.json").read_text(encoding="utf-8"))["form_fields"]
    assert any(f.get("env_variable") == var and f.get("required") is False for f in fields), (
        f"Runtipi has no optional form field for {var}"
    )


@pytest.mark.parametrize("var", UI_SETTINGS)
def test_the_unraid_template_offers_the_setting(var):
    root = ET.parse(ROOT / "unraid" / "cashpilot.xml").getroot()
    targets = {c.get("Target") for c in root.iter("Config") if c.get("Type") == "Variable"}
    assert var in targets


def test_the_metrics_guide_turns_metrics_on_from_env():
    guide = (ROOT / "docs" / "guides" / "prometheus-metrics.md").read_text(encoding="utf-8")
    assert "CASHPILOT_METRICS_ENABLED=true" in guide
    assert "CASHPILOT_METRICS_TOKEN" in guide, "the guide must say how to require a token"
    assert 'CASHPILOT_METRICS_ENABLED: "true"' not in guide, (
        "mapping syntax breaks the list-syntax environment of the shipped compose files"
    )
