"""A template's or a script's source with its English strings put back.

Many tests read a template or app.js as text and assert that its copy says
something ("does not take effect", a referral disclosure, a button label).
Since the strings moved into app/i18n/en.json, that copy is no longer in the
file: the file holds ``t('settings.env.desc_html')`` and en.json holds the
words. ``english_source(path)`` gives those tests the file as a reader of the
English page sees it: each ``{{ t('key', ...) }}`` and each ``t('key', ...)``
call is replaced by the English message for that key: a call in code as a quoted
string literal, a ``{{ t() }}`` or a ``${t()}`` slot as the bare text. Placeholders stay as
they are in the message (``{name}``), so an assertion on fixed words still
works, and one on a filled-in value has to render the page instead.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_JINJA = re.compile(r"""\{\{\s*t\(\s*(['"])([^'"]+)\1""")
_CALL = re.compile(r"""(?<![\w$])(?:CPI18N\.|i18n\.)?t\(\s*(['"])([^'"]+)\1""")


@cache
def _english() -> dict[str, str]:
    return json.loads((ROOT / "app/i18n/en.json").read_text(encoding="utf-8"))


def _call_end(text: str, start: int) -> int:
    """The index just past the ``)`` that closes the call whose ``(`` is at ``start``."""
    depth = 0
    i = start
    quote = None
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "'\"`":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


def english(text: str) -> str:
    """``text`` with every t() call replaced by its English message."""
    en = _english()
    out: list[str] = []
    pos = 0
    while True:
        jinja = _JINJA.search(text, pos)
        call = _CALL.search(text, pos)
        found = min((m for m in (jinja, call) if m), key=lambda m: m.start(), default=None)
        if found is None:
            out.append(text[pos:])
            return "".join(out)
        key = found.group(2)
        out.append(text[pos : found.start()])
        paren = text.index("(", found.start())
        end = _call_end(text, paren)
        message = en.get(key, key)
        if found is jinja:
            close = text.find("}}", end)
            end = close + 2 if close >= 0 else end
        elif out[-1].endswith("${") and text[end : end + 1] == "}":
            # `${t('key')}` inside a template literal: the English stands in for the whole slot.
            out[-1] = out[-1][:-2]
            end += 1
        else:
            # A call in code reads back as the string literal it replaced, `flag('warn', 'Docker unreachable')`,
            # and keeps the code that fills its placeholders in a comment after it.
            args = text[text.index(found.group(1), paren + 1) + len(key) + 2 : end - 1].strip().lstrip(",").strip()
            message = f"'{message}'" + (f" /* {args} */" if args else "")
        out.append(message)
        pos = end


def english_source(path: str | Path) -> str:
    """The file at ``path`` (relative to the repo root, or absolute) with its English put back."""
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    return english(p.read_text(encoding="utf-8"))


# Node flags that give a check run with ``node -e`` the page's global t(), in English.
NODE_T = ["--import", (ROOT / "scripts" / "i18n_stub.mjs").as_uri()]
