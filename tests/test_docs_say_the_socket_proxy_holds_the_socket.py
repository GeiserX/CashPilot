"""Since v1.71.0 the worker has no Docker socket: ``cashpilot-socket-proxy``
holds it read-only and the worker reaches Docker through a filtered copy.
Since v1.70.0 new installs fence earners off the LAN by default.

The README, the docs home page and five other pages kept saying "two
containers", "the worker holds the Docker socket" and "it does not keep the
containers off your LAN by itself" after both shipped. This test fails when
one of those claims comes back while the shipped compose file still runs the
proxy.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Pages describing what the shipped compose file installs today. Changelogs,
# upgrade notes and research notes describe the past on purpose.
# CLAUDE.md is read by every agent that changes the code, so it counts too.
PAGES = [ROOT / "README.md", ROOT / "CLAUDE.md", *sorted((ROOT / "docs").glob("*.md"))]

STALE = [
    r"\btwo (docker )?containers\b",
    r"\bworker (itself )?(holds|mounts|touches|has) the docker socket\b",
    r"\bonly the worker (holds|mounts|touches) the docker socket\b",
    r"\bboth can command the docker socket\b",
    r"\bdoes not keep the containers off your lan by itself\b",
    r"\brequiring (docker )?socket access\b",
    r"\b(must|requires?) (have )?docker socket access\b",
    r"\bworkers must be privileged\b",
]

# Each entry: a page and a pattern that is true there, with the reason.
ALLOWED = {
    # The app-store listings do not ship the proxy yet (two containers, the
    # worker mounts the socket); the page says so.
    ("app-stores.md", STALE[0]),
    ("app-stores.md", STALE[1]),
    # A proxied copy really is two containers (the earner and its tunnel).
    ("proxies.md", STALE[0]),
}


def stale_claims(name: str, text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text).lower()
    return [p for p in STALE if (name, p) not in ALLOWED and re.search(p, flat)]


def test_the_shipped_compose_file_runs_the_socket_proxy():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "cashpilot-socket-proxy:" in compose, "the proxy is gone; this test's premise no longer holds"
    assert "DOCKER_HOST=unix:///run/cashpilot-docker/docker.sock" in compose


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_no_page_says_the_worker_holds_the_socket(page: Path):
    assert stale_claims(page.name, page.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    "text",
    [
        "It is two Docker containers: a UI and a worker.",
        "A worker holds the Docker socket on its server.",
        "Only the worker\ntouches the Docker socket.",
        "It does not keep the containers off your LAN by itself.",
        "cashpilot-worker (port 8081, Docker agent requiring socket access)",
        "Agent running on each server. **Must have Docker socket access**.",
        "- Worker requires Docker socket access (`/var/run/docker.sock`)",
        "2. **Workers must be privileged.** A worker without Docker socket is useless.",
    ],
)
def test_the_check_catches_each_old_claim(text: str):
    assert stale_claims("index.md", text)
