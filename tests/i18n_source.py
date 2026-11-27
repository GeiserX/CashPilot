"""A template's or a script's source with its English strings put back.

Many tests read a template or app.js as text and assert that its copy says
something ("does not take effect", a referral disclosure, a button label).
Since the strings moved into app/i18n/en.json, that copy is no longer in the
file: the file holds ``t('settings.env.desc_html')`` and en.json holds the
words. ``english_source(path)`` gives those tests the file as a reader of the
English page sees it: each ``{{ t('key', ...) }}`` and each ``t('key', ...)``
call is replaced by the English message for that key: a call in code as the string
literal it replaced, a ``{{ t() }}`` or a ``${t()}`` slot as the bare text. A
placeholder that a JS call fills reads back as the expression that fills it
(``t('k', { name: escapeHtml(n) })`` with ``Hi {name}`` gives ``Hi ${escapeHtml(n)}``,
in backticks when the call is in code), so the text is the source as it was
written before the move. Other placeholders, and plural branches, stay as they
are in the message.
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


def _split_top(text: str) -> list[str]:
    """``text`` split at the commas that are not inside brackets or strings."""
    parts: list[str] = []
    depth = 0
    quote = None
    start = 0
    i = 0
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
        elif ch == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1
        i += 1
    parts.append(text[start:])
    return [part.strip() for part in parts if part.strip()]


def _params(args: str) -> dict[str, str]:
    """The ``{ name: expr, short }`` object of a JS t() call, as name -> expression."""
    args = args.strip()
    if not (args.startswith("{") and args.endswith("}")):
        return {}
    params: dict[str, str] = {}
    for part in _split_top(args[1:-1]):
        name, colon, expr = part.partition(":")
        name = name.strip().strip("'\"")
        params[name] = english(expr.strip()) if colon else name
    return params


def _fill(message: str, params: dict[str, str]) -> str:
    """``message`` with each ``{name}`` that ``params`` fills put back as ``${expr}``.

    Inside ``{name, plural, ...}`` the ``#`` that stands for the count gets the same treatment.
    """
    for m in re.finditer(r"\{(\w+), plural,", message):
        if m.group(1) not in params:
            continue
        end = _call_end(message, m.start())
        body = message[m.start() : end].replace("#", f"${{{params[m.group(1)]}}}")
        return _fill(message[: m.start()], params) + body + _fill(message[end:], params)
    return re.sub(r"\{(\w+)\}", lambda m: f"${{{params[m.group(1)]}}}" if m.group(1) in params else m.group(0), message)


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
            out.append(message)
            pos = end
            continue
        args = text[text.index(found.group(1), paren + 1) + len(key) + 2 : end - 1].strip().lstrip(",").strip()
        params = _params(args)
        message = _fill(message, params)
        if out[-1].endswith("${") and text[end : end + 1] == "}":
            # `${t('key')}` inside a template literal: the English stands in for the whole slot.
            out[-1] = out[-1][:-2]
            end += 1
        elif params:
            # A call in code that fills placeholders reads back as the template literal it replaced.
            message = f"`{message}`"
        else:
            # A call in code reads back as the string literal it replaced, `flag('warn', 'Docker unreachable')`.
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
