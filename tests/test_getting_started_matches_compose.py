"""Getting started must describe what the shipped compose file really does.

A fresh-install sweep found three gaps on this page: the container table
missed the one-shot ``cashpilot-migrate`` (so its ``Exited (0)`` looked like a
failure), the prerequisites gave no Compose version although the file needs
2.23.1 for its inline config, and nothing said that a Docker host holds one
CashPilot. The page also told users to move series by editing tags, with no
UI-first order and no link to UPGRADING.md.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "getting-started.md"
COMPOSE = ROOT / "docker-compose.yml"


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _container_table() -> str:
    text = _page()
    start = text.index("| Container | Port | Purpose |")
    return text[start : text.index("\n\n", start)]


def test_the_table_lists_every_container_the_compose_file_starts():
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    names = {s.get("container_name", key) for key, s in services.items()}
    assert len(names) >= 4
    table = _container_table()
    missing = sorted(n for n in names if f"**{n}**" not in table)
    assert not missing, f"docs/getting-started.md does not list {missing}"


def test_the_prerequisites_name_the_compose_version_the_file_needs():
    needed = re.search(r"Needs Docker\s+(?:#\s+)?Compose (\d+\.\d+\.\d+) or newer", COMPOSE.read_text(encoding="utf-8"))
    assert needed, "docker-compose.yml no longer states its minimum Compose version"
    prereqs = _page().split("## Quick Start", 1)[0]
    assert needed.group(1) in prereqs
    assert "docker compose version" in prereqs


def test_the_page_says_one_cashpilot_per_docker_host():
    prereqs = _page().split("## Quick Start", 1)[0]
    assert "One CashPilot per Docker host" in prereqs


def test_every_compose_file_says_one_cashpilot_per_docker_host():
    for name in ("docker-compose.yml", "docker-compose.fleet.yml", "docker-compose.worker.yml"):
        assert "ONE CashPilot per Docker host" in (ROOT / name).read_text(encoding="utf-8"), name


def test_moving_series_sends_the_reader_to_upgrading_ui_first():
    text = _page()
    section = text[text.index("### Pinning a specific version") : text.index("### Automating updates")]
    assert "UPGRADING.md" in section
    assert "UI host first" in section


def test_the_prerequisites_say_how_to_install_the_compose_plugin():
    prereqs = _page().split("## Quick Start", 1)[0]
    assert "https://docs.docker.com/compose/install/linux/" in prereqs
    assert "brew install docker-compose" in prereqs
    assert "~/.docker/cli-plugins/docker-compose" in prereqs

