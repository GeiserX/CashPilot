"""docs/getting-started.md must not name a series the compose files left behind.

It told readers to replace `1.57` with a patch tag while docker-compose.yml
pinned 1.71, so the string it named was nowhere in the file. The release moves
the compose pins on its own; the doc now names no series, and this keeps any
series it does name equal to the shipped one.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _shipped_series() -> str:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    pins = set(re.findall(r"image: drumsergio/cashpilot(?:-worker)?:(\d+\.\d+)", text))
    assert len(pins) == 1, f"docker-compose.yml pins {sorted(pins)}"
    return pins.pop()


def test_getting_started_names_only_the_shipped_series():
    text = (ROOT / "docs" / "getting-started.md").read_text(encoding="utf-8")
    section = text[text.index("## Updating CashPilot") :]
    named = set(re.findall(r"`(?:drumsergio/cashpilot(?:-worker)?:)?(\d+\.\d+)(?:\.\d+)?`", section))
    stale = named - {_shipped_series()}
    assert not stale, f"docs/getting-started.md names series {sorted(stale)}; the compose files pin {_shipped_series()}"
