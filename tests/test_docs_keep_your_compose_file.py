"""Docs that change a running install must not lose the reader's compose file or settings.

A review of the metrics guide found two traps. It ran ``docker compose up -d``
before the reader added the token and the compose lines, so the UI kept an
empty token and ``/metrics`` stayed open. And it fetched the current compose
file with ``curl -O``, which writes over the reader's own file and its changes.
The 3.0.1 note and the 3.0 rollback had the same overwriting download.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "guides" / "prometheus-metrics.md"

#: ``curl`` that saves under the URL's own file name: ``-O`` in any flag group, or ``--remote-name``.
REMOTE_NAME = re.compile(r"\bcurl\b[^\n]*?\s(?:-[A-Za-z]*O[A-Za-z]*|--remote-name)\s+(\S+)")


def _sections(text: str) -> list[str]:
    return re.split(r"\n(?=#{2,4} )", text)


def _docs_for_running_installs() -> list[Path]:
    return [ROOT / "UPGRADING.md", *sorted((ROOT / "docs" / "guides").glob("*.md"))]


def test_no_download_writes_over_a_compose_file_without_a_copy_first():
    """A ``curl -O`` of a compose file is fine only after the same section copies that file away."""
    offenders = []
    for path in _docs_for_running_installs():
        for section in _sections(path.read_text(encoding="utf-8")):
            for match in REMOTE_NAME.finditer(section):
                name = match.group(1).rsplit("/", 1)[-1]
                if not name.startswith("docker-compose"):
                    continue
                if f"cp {name} " not in section[: match.start()]:
                    heading = section.splitlines()[0]
                    offenders.append(f"{path.relative_to(ROOT)}: {heading}: {match.group(0)}")
    assert not offenders, "download under another name with -o, or copy the file first:\n" + "\n".join(offenders)


def test_the_guard_catches_an_overwriting_download():
    sample = "## Fix\n\ncurl -fsSLO https://raw.githubusercontent.com/GeiserX/CashPilot/main/docker-compose.yml\n"
    assert REMOTE_NAME.search(sample).group(1).endswith("/docker-compose.yml")
    assert REMOTE_NAME.search(sample.replace("-fsSLO", "-fsSL --remote-name"))
    assert not REMOTE_NAME.search(sample.replace("-fsSLO", "-fsSL -o docker-compose.upstream.yml"))


def _enable_section() -> str:
    text = GUIDE.read_text(encoding="utf-8")
    start = text.index("## Enabling Metrics")
    return text[start : text.index("\n## ", start + 1)]


def test_the_metrics_guide_recreates_the_ui_only_after_every_setting():
    section = _enable_section()
    first_up = section.index("up -d")
    for setting in (
        "CASHPILOT_METRICS_ENABLED=true",
        "CASHPILOT_METRICS_TOKEN=a-long-random-string",
        "- CASHPILOT_METRICS_ENABLED=${CASHPILOT_METRICS_ENABLED:-false}",
        "- CASHPILOT_METRICS_TOKEN=${CASHPILOT_METRICS_TOKEN:-}",
        "-o docker-compose.upstream.yml",
    ):
        assert section.index(setting) < first_up, f"{setting} comes after docker compose up -d"


def test_the_metrics_guide_names_the_compose_file_it_recreates():
    section = _enable_section()
    assert "docker compose -f docker-compose.yml up -d" in section
    assert "docker compose -f docker-compose.fleet.yml up -d" in section
    assert "docker compose up -d" not in section, "a bare up -d uses the default file, not the fleet one"
