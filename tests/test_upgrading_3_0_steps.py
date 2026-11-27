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
        assert f"`{name}`" in UPGRADE, name
    assert "keep your `.env`" in UPGRADE


def test_the_rollback_restores_the_kept_file_or_fetches_it():
    assert "cp docker-compose.2.10.yml docker-compose.yml" in ROLLBACK
    assert "https://raw.githubusercontent.com/GeiserX/CashPilot/v2.10.2/docker-compose.yml" in ROLLBACK


def test_the_rollback_covers_unraid():
    assert "Unraid" in ROLLBACK
    assert "drumsergio/cashpilot:2.10" in ROLLBACK
    assert "drumsergio/cashpilot-worker:2.10" in ROLLBACK


def test_the_409_example_wraps_its_fields_in_detail():
    assert '"detail": {' in API
    assert "detail.expected_containers" in API
    assert "detail.current_container" in API


def test_the_refusal_quote_matches_any_3_0_worker():
    assert "v3.0.0 and replaces" not in UPGRADE
    assert "v3.0.x and replaces" in UPGRADE
    source = (ROOT / "app" / "worker_api.py").read_text(encoding="utf-8")
    assert "and replaces an existing container only when the UI confirms " in source
    assert "which container it replaces, and this UI is too old to do that. Update the UI, then" in source
