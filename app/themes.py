"""The built-in themes.

app/themes.json is the one list. The server render, /api/preferences, the
avatar-menu picker, the pre-paint script and the browser checks all read it, so
they cannot drift. A new theme is one entry there plus its CSS block and swatch
in app/static/css/style.css (tests/test_themes.py checks both exist).
"""

from __future__ import annotations

import json
from pathlib import Path

_SPEC = json.loads(Path(__file__).with_name("themes.json").read_text(encoding="utf-8"))

#: (id, label) in picker order.
THEME_LIST: tuple[dict[str, str], ...] = tuple({"id": t["id"], "label": t["label"]} for t in _SPEC["themes"])
#: The ids user_preferences.theme accepts.
THEMES: tuple[str, ...] = tuple(t["id"] for t in THEME_LIST)
#: What a user who never chose, or whose saved value is no longer a theme, sees.
DEFAULT_THEME: str = _SPEC["default"]
#: What the pre-paint script needs, rendered into every page.
CONFIG: dict = {"default": DEFAULT_THEME, "ids": list(THEMES)}

if DEFAULT_THEME not in THEMES or len(set(THEMES)) != len(THEMES):
    raise RuntimeError("app/themes.json: the default must be one of the themes, and ids must be unique")


def resolve(theme: str | None) -> str:
    """A saved value, or the default when it is unset or no longer a theme."""
    return theme if theme in THEMES else DEFAULT_THEME
