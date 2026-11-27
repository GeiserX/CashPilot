"""The 3.0 section of UPGRADING.md must be followable word for word.

An upgrade sweep found that a reader who did exactly what it said could not roll
back: step 2 replaced the compose file without saying to keep the old one, and
the rollback asked for that file back. Step 2 named no file and no command, the
409 example put its fields at the top level although FastAPI wraps them in
``detail``, the refusal quote hardcoded v3.0.0, and Unraid had no way back.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.i18n_source import english_source

ROOT = Path(__file__).resolve().parents[1]


def _section(title: str, end: str) -> str:
    text = (ROOT / "UPGRADING.md").read_text(encoding="utf-8")
    start = text.index(title)
    return text[start : text.index(end, start + len(title))]


UPGRADE = _section("### Upgrade from 2.x", "\n### ")
API = _section("### API scripts and cashpilot-mcp", "\n### ")
ROLLBACK = _section("### Rolling back", "\n---")


def test_step_two_keeps_the_old_file_and_names_the_new_one():
    assert "cp docker-compose.yml docker-compose.2.10.yml" in UPGRADE
    assert re.search(r"curl -fsSLO https://raw\.githubusercontent\.com/GeiserX/CashPilot/v3\.0\.\d+/", UPGRADE)
    for name in ("docker-compose.yml", "docker-compose.fleet.yml", "docker-compose.worker.yml"):
        assert name in UPGRADE, name
    assert "keep your `.env`" in UPGRADE


def test_the_rollback_restores_the_kept_file_or_fetches_it():
    assert "cp docker-compose.2.10.yml docker-compose.yml" in ROLLBACK
    assert "https://raw.githubusercontent.com/GeiserX/CashPilot/v2.10.2/docker-compose.yml" in ROLLBACK


# Each compose file a host may run, the copy step 2 or 3 keeps of it, and the
# command that recreates its containers. A rollback that writes
# docker-compose.yml on a worker host leaves docker-compose.worker.yml on 3.0.
FILES = {
    "docker-compose.yml": ("docker-compose.2.10.yml", "docker compose up -d --force-recreate"),
    "docker-compose.fleet.yml": (
        "docker-compose.fleet.2.10.yml",
        "docker compose -f docker-compose.fleet.yml up -d --force-recreate",
    ),
    "docker-compose.worker.yml": (
        "docker-compose.worker.2.10.yml",
        "docker compose -f docker-compose.worker.yml up -d --force-recreate",
    ),
}


def test_every_compose_file_is_kept_and_restored_under_its_own_name():
    for name, (copy, recreate) in FILES.items():
        assert f"cp {name} {copy}" in UPGRADE, f"no copy of {name} before the upgrade"
        assert recreate in UPGRADE, f"no recreate command for {name} in the upgrade"
        assert f"cp {copy} {name}" in ROLLBACK, f"the rollback does not restore {name}"
        assert recreate in ROLLBACK, f"no recreate command for {name} in the rollback"


def test_the_rollback_names_where_the_proxy_policy_command_is():
    assert "status page" not in ROLLBACK
    assert "**Settings**, **About and updates**" in ROLLBACK
    page = english_source("app/templates/settings.html")
    assert "About and updates" in page


def test_the_env_fix_is_its_own_section_with_the_lines_to_add():
    text = (ROOT / "UPGRADING.md").read_text(encoding="utf-8")
    title = "## After 3.0.1: the read-only key and metrics work from `.env`"
    assert text.index(title) < text.index("## 3.0: upgrade the UI first")
    section = _section(title, "\n---")
    for var in ("CASHPILOT_READONLY_API_KEY", "CASHPILOT_METRICS_ENABLED", "CASHPILOT_METRICS_TOKEN"):
        assert f"- {var}=${{{var}:-" in section, var
    assert (
        "curl -fsSL -o docker-compose.upstream.yml https://raw.githubusercontent.com/GeiserX/CashPilot/main/" in section
    ), "download the current file under another name, never over the reader's own"
    assert "docker compose -f docker-compose.yml up -d" in section
    assert "docker compose -f docker-compose.fleet.yml up -d" in section
    assert "put that name after `-f`" in section
    assert "docker compose up -d" not in section, "a bare up -d uses the default file, not the fleet one"
    assert "#after-301-the-read-only-key-and-metrics-work-from-env" in UPGRADE


def test_the_rollback_covers_unraid():
    assert "Unraid" in ROLLBACK
    assert "drumsergio/cashpilot:2.10" in ROLLBACK
    assert "drumsergio/cashpilot-worker:2.10" in ROLLBACK


def test_the_409_example_wraps_its_fields_in_detail():
    assert '"detail": {' in API
    assert "detail.expected_containers" in API
    assert "detail.current_container" in API


def test_the_expected_containers_keys_cover_proxied_copies_and_none():
    assert "`p<proxy id>` for a proxied copy" in API
    assert "or `none`" in API
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert 'keys = [f"p{route}"]' in source


def test_the_refusal_quote_matches_any_3_0_worker():
    assert "v3.0.0 and replaces" not in UPGRADE
    assert "v3.0.x and replaces" in UPGRADE
    source = (ROOT / "app" / "worker_api.py").read_text(encoding="utf-8")
    assert "and replaces an existing container only when the UI confirms " in source
    assert "which container it replaces, and this UI is too old to do that. Update the UI, then" in source
