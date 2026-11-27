"""The web UI's languages: which one a request gets, and its strings.

One JSON file per locale sits beside this module (``app/i18n/<locale>.json``).
``en.json`` is the source: a flat map of key to English text. Every other file
maps the same keys to ``{"text": <translation>, "source": <source hash>}``,
where the hash is :func:`source_hash` of the English text the translation was made from.
When the English text changes, the hash no longer matches, the translation is
stale, and the English text shows until a translator updates it. A missing key
or a missing file shows English too, never a blank.

Messages use a small subset of ICU MessageFormat: ``{name}`` for a value,
``{count, plural, one {# box} other {# boxes}}`` and ``{kind, select, a {...}
other {...}}``. The same subset runs in the browser (app/static/js/i18n.js), so
a message reads the same on both sides. Keys that end in ``_html`` hold trusted
markup (a link, a <code>): only those are rendered unescaped, and their values
are escaped before they go in.

Which language a request gets, first match wins:

1. the user's saved choice (``user_preferences.language``), on a signed-in page;
2. the ``cp-lang`` cookie: the choice made on the sign-in page, or the saved
   choice mirrored there so API replies and the sign-in page match it;
3. the browser's ``Accept-Language``;
4. English.

A tag matches by language first, then region: ``es-MX`` gets ``es``,
``pt-PT`` gets ``pt-BR`` and ``zh-TW`` gets ``zh-Hans``.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import math
import re
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

from markupsafe import Markup, escape

DIR = Path(__file__).parent
SOURCE = "en"
COOKIE = "cp-lang"
#: A year: the choice is the browser's until it is changed.
COOKIE_MAX_AGE = 365 * 24 * 3600

#: Every locale the UI can show, in picker order, with its name in itself.
NAMES: dict[str, str] = {
    "en": "English",
    "es": "Español",
    "pt-BR": "Português (Brasil)",
    "fr": "Français",
    "de": "Deutsch",
    "it": "Italiano",
    "nl": "Nederlands",
    "pl": "Polski",
    "ru": "Русский",
    "uk": "Українська",
    "tr": "Türkçe",
    "ar": "العربية",
    "hi": "हिन्दी",
    "id": "Bahasa Indonesia",
    "vi": "Tiếng Việt",
    "th": "ไทย",
    "fil": "Filipino",
    "zh-Hans": "中文（简体）",
    "ja": "日本語",
    "ko": "한국어",
}
RTL = frozenset({"ar"})

# A tag's language subtag, lower-cased, to the locale it gets. Region and script
# subtags never pick a different locale except through this map.
_BY_LANGUAGE: dict[str, str] = {code.split("-")[0].lower(): code for code in NAMES}
# Old or alternative codes browsers still send.
_BY_LANGUAGE.update({"in": "id", "tl": "fil", "fil": "fil"})


def source_hash(text: str) -> str:
    """The hash a translation stores of the English text it was made from.

    The same hash scripts/i18n_check.py computes and ``--stamp`` writes.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Catalogs
# ---------------------------------------------------------------------------


def _read(locale: str) -> dict[str, Any]:
    path = DIR / f"{locale}.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return data


@cache
def source() -> dict[str, str]:
    """The English strings, key to text."""
    data = _read(SOURCE)
    bad = [k for k, v in data.items() if not isinstance(v, str)]
    if bad:
        raise ValueError(f"app/i18n/en.json: values must be strings: {bad[:5]}")
    return data


@cache
def translated(locale: str) -> dict[str, str]:
    """The keys with a current translation in ``locale``, key to text."""
    en = source()
    if locale == SOURCE or locale not in NAMES:
        return {}
    out = {}
    for key, entry in _read(locale).items():
        if key not in en or not isinstance(entry, dict):
            continue
        text, made_from = entry.get("text"), entry.get("source")
        if isinstance(text, str) and text and made_from == source_hash(en[key]):
            out[key] = text
    return out


@cache
def catalog(locale: str) -> dict[str, str]:
    """Every key in ``locale``: its current translation, or the English text."""
    return {**source(), **translated(locale)}


def fallback(locale: str) -> list[str]:
    """The keys that ``locale`` shows in English: they take English plural rules too."""
    if locale == SOURCE:
        return []
    done = translated(locale)
    return sorted(k for k in source() if k not in done)


@cache
def available() -> tuple[str, ...]:
    """The locales with a file, in picker order. English is always there."""
    return tuple(code for code in NAMES if code == SOURCE or (DIR / f"{code}.json").is_file())


def reload() -> None:
    """Forget the cached files (tests, and a translator editing a running dev server)."""
    source.cache_clear()
    translated.cache_clear()
    catalog.cache_clear()
    available.cache_clear()


# ---------------------------------------------------------------------------
# Negotiation
# ---------------------------------------------------------------------------


def match(tag: str | None) -> str | None:
    """The locale for one BCP 47 tag, or None when we have none for it."""
    if not tag:
        return None
    tag = tag.strip().replace("_", "-")
    if not tag or tag == "*":
        return None
    have = available()
    for code in have:
        if code.lower() == tag.lower():
            return code
    code = _BY_LANGUAGE.get(tag.split("-")[0].lower())
    return code if code in have else None


_QUALITY = re.compile(r"^q=([0-9.]+)$")


def negotiate(header: str | None) -> str | None:
    """The best locale for an ``Accept-Language`` header, or None."""
    if not header:
        return None
    ranked: list[tuple[float, int, str]] = []
    for index, part in enumerate(header.split(",")):
        tag, *params = (p.strip() for p in part.split(";"))
        quality = 1.0
        for param in params:
            found = _QUALITY.match(param)
            if found:
                try:
                    quality = float(found.group(1))
                except ValueError:
                    quality = 0.0
        if tag and quality > 0:
            ranked.append((-quality, index, tag))
    for _, _, tag in sorted(ranked):
        if code := match(tag):
            return code
    return None


def resolve(saved: str | None = None, cookie: str | None = None, accept_language: str | None = None) -> str:
    """The locale for a request, from the sources in the module docstring's order."""
    for choice in (saved, cookie):
        if choice and choice in available():
            return choice
    return negotiate(accept_language) or SOURCE


def from_request(request: Any, saved: str | None = None) -> str:
    """:func:`resolve` with the cookie and header read from a Starlette request."""
    return resolve(saved, request.cookies.get(COOKIE), request.headers.get("accept-language"))


_current: contextvars.ContextVar[str] = contextvars.ContextVar("cashpilot_locale", default=SOURCE)


def current() -> str:
    """The locale of the request being served (English outside one)."""
    return _current.get()


def use(locale: str) -> None:
    """Make ``locale`` the current one for the rest of this request."""
    _current.set(locale if locale in NAMES else SOURCE)


def direction(locale: str | None = None) -> str:
    return "rtl" if (locale or current()) in RTL else "ltr"


class LocaleMiddleware:
    """Set the current locale from the cookie and ``Accept-Language`` on every request.

    Pure ASGI, so the value set here is the one the endpoint sees. A signed-in
    page then replaces it with the user's saved choice (app.routers.pages._page).
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket"):
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
            cookie = None
            for part in headers.get("cookie", "").split(";"):
                name, _, value = part.strip().partition("=")
                if name == COOKIE:
                    cookie = value.strip()
            token = _current.set(resolve(None, cookie, headers.get("accept-language")))
            try:
                await self.app(scope, receive, send)
            finally:
                _current.reset(token)
            return
        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# Plurals (CLDR cardinal rules)
# ---------------------------------------------------------------------------


def _operands(n: float | int) -> tuple[float, int, int, int]:
    """CLDR operands n, i, v, f of a number as it would be written."""
    text = repr(n) if isinstance(n, float) else str(int(n))
    text = text.lstrip("-")
    if "e" in text or "E" in text:
        text = f"{abs(float(n)):f}".rstrip("0").rstrip(".")
    whole, _, frac = text.partition(".")
    if frac == "0" and isinstance(n, float) and float(n).is_integer():
        frac = ""
    return abs(float(n)), int(whole or 0), len(frac), int(frac or 0)


def _million(i: int, v: int) -> bool:
    return v == 0 and i != 0 and i % 1_000_000 == 0


def plural_category(locale: str, n: float | int) -> str:
    """The CLDR plural category of ``n`` in ``locale``.

    The browser asks Intl.PluralRules instead; tests/test_i18n.py checks these
    rules against what Node's Intl answers for the same numbers.
    """
    lang = locale.split("-")[0]
    num, i, v, f = _operands(n)
    if lang in ("en", "de", "nl"):
        return "one" if i == 1 and v == 0 else "other"
    if lang == "it":
        if i == 1 and v == 0:
            return "one"
        return "many" if _million(i, v) else "other"
    if lang == "es":
        if num == 1:
            return "one"
        return "many" if _million(i, v) else "other"
    if lang in ("fr", "pt"):
        if i in (0, 1):
            return "one"
        return "many" if _million(i, v) else "other"
    if lang == "pl":
        if i == 1 and v == 0:
            return "one"
        if v == 0 and 2 <= i % 10 <= 4 and not 12 <= i % 100 <= 14:
            return "few"
        if v == 0:
            return "many"
        return "other"
    if lang in ("ru", "uk"):
        if v == 0 and i % 10 == 1 and i % 100 != 11:
            return "one"
        if v == 0 and 2 <= i % 10 <= 4 and not 12 <= i % 100 <= 14:
            return "few"
        if v == 0:
            return "many"
        return "other"
    if lang == "tr":
        return "one" if num == 1 else "other"
    if lang == "ar":
        if num == 0:
            return "zero"
        if num == 1:
            return "one"
        if num == 2:
            return "two"
        if num.is_integer() and 3 <= int(num) % 100 <= 10:
            return "few"
        if num.is_integer() and 11 <= int(num) % 100 <= 99:
            return "many"
        return "other"
    if lang in ("hi", "vi"):
        return "one" if i == 0 or num == 1 else "other"
    if lang == "fil":
        if v == 0 and (i in (1, 2, 3) or i % 10 not in (4, 6, 9)):
            return "one"
        if v != 0 and f % 10 not in (4, 6, 9):
            return "one"
        return "other"
    return "other"


# ---------------------------------------------------------------------------
# Formatting (the ICU MessageFormat subset)
# ---------------------------------------------------------------------------


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def message(self, depth: int = 0) -> list:
        parts: list = []
        buf: list[str] = []
        text = self.text
        while self.pos < len(text):
            ch = text[self.pos]
            if ch == "'" and self.pos + 1 < len(text) and text[self.pos + 1] in "'{}#":
                if text[self.pos + 1] == "'":
                    buf.append("'")
                    self.pos += 2
                    continue
                end = text.find("'", self.pos + 1)
                end = len(text) if end < 0 else end
                buf.append(text[self.pos + 1 : end])
                self.pos = end + 1
                continue
            if ch == "{":
                if buf:
                    parts.append("".join(buf))
                    buf = []
                parts.append(self.argument())
                continue
            if ch == "}":
                if depth == 0:
                    raise ValueError(f"unmatched '}}' at {self.pos} in {text!r}")
                break
            if ch == "#" and depth > 0:
                if buf:
                    parts.append("".join(buf))
                    buf = []
                parts.append(("#",))
                self.pos += 1
                continue
            buf.append(ch)
            self.pos += 1
        if buf:
            parts.append("".join(buf))
        return parts

    def _word(self) -> str:
        found = re.compile(r"\s*([^\s,{}]+)\s*").match(self.text, self.pos)
        if not found:
            raise ValueError(f"expected a name at {self.pos} in {self.text!r}")
        self.pos = found.end()
        return found.group(1)

    def argument(self) -> tuple:
        self.pos += 1  # {
        name = self._word()
        if self.text[self.pos : self.pos + 1] == "}":
            self.pos += 1
            return ("arg", name)
        if self.text[self.pos : self.pos + 1] != ",":
            raise ValueError(f"expected ',' or '}}' at {self.pos} in {self.text!r}")
        self.pos += 1
        kind = self._word()
        if kind not in ("plural", "select"):
            raise ValueError(f"unsupported argument type {kind!r} in {self.text!r}")
        if self.text[self.pos : self.pos + 1] != ",":
            raise ValueError(f"expected ',' after {kind} in {self.text!r}")
        self.pos += 1
        options: dict[str, list] = {}
        while True:
            while self.pos < len(self.text) and self.text[self.pos].isspace():
                self.pos += 1
            if self.text[self.pos : self.pos + 1] == "}":
                self.pos += 1
                break
            selector = self._word()
            if self.text[self.pos : self.pos + 1] != "{":
                raise ValueError(f"expected '{{' after {selector!r} in {self.text!r}")
            self.pos += 1
            options[selector] = self.message(depth=1)
            if self.text[self.pos : self.pos + 1] != "}":
                raise ValueError(f"unclosed option {selector!r} in {self.text!r}")
            self.pos += 1
        if "other" not in options:
            raise ValueError(f"{kind} needs an 'other' option in {self.text!r}")
        return (kind, name, options)


def _count(value: Any) -> float:
    """A plural's value as a number, as the browser reads it: not a finite number counts as 0."""
    try:
        count = float(value)
    except (TypeError, ValueError):
        return 0.0
    return count if math.isfinite(count) else 0.0


@lru_cache(maxsize=4096)
def parse(text: str) -> tuple:
    """A message as a tree of literal strings and argument tuples. Raises ValueError."""
    return tuple(_Parser(text).message())


def _render(parts: tuple | list, params: dict[str, Any], locale: str, number: Any, esc: bool) -> str:
    out: list[str] = []
    for part in parts:
        if isinstance(part, str):
            out.append(part)
        elif part[0] == "#":
            out.append(str(escape(number)) if esc else str(number))
        elif part[0] == "arg":
            value = params.get(part[1], "{" + part[1] + "}")
            out.append(str(escape(value)) if esc else str(value))
        else:
            kind, name, options = part
            value = params.get(name)
            chosen = None
            if kind == "plural":
                count = _count(value)
                exact = f"={int(count)}" if count.is_integer() else None
                chosen = options.get(exact) if exact else None
                if chosen is None:
                    chosen = options.get(plural_category(locale, count))
                # The count as the browser writes it (String(Number(value))): 1.0 is "1".
                inner_number = int(count) if count.is_integer() else count
            else:
                chosen = options.get(str(value))
                inner_number = number
            if chosen is None:
                chosen = options["other"]
            out.append(_render(chosen, params, locale, inner_number, esc))
    return "".join(out)


def format_message(text: str, params: dict[str, Any] | None = None, locale: str = SOURCE, *, html: bool = False) -> str:
    """Fill a message's arguments. With ``html``, the values are HTML-escaped."""
    return _render(parse(text), params or {}, locale, "", html)


def join_and(items: list[str] | tuple[str, ...]) -> str:
    """``items`` joined with the current locale's "and": "a and b", "a and b and c"."""
    if not items:
        return ""
    text = str(items[0])
    for item in items[1:]:
        text = t("i18n.list_and", first=text, last=item)
    return text


def t(key: str, /, **params: Any) -> str:
    """The text for ``key`` in the current locale. An unknown key shows the key."""
    locale = current()
    text = catalog(locale).get(key)
    if text is None:
        return key
    # A message shown in English (no current translation) counts in English too.
    rules = locale if key in translated(locale) else SOURCE
    if key.endswith("_html"):
        return Markup(format_message(text, params, rules, html=True))
    return format_message(text, params, rules)


def bundle_js(locale: str) -> str:
    """The script that hands the browser its strings (served at /i18n/<locale>.js)."""
    locale = locale if locale in available() else SOURCE
    payload = {"lang": locale, "dir": direction(locale), "messages": catalog(locale), "fallback": fallback(locale)}
    return (
        "window.CP_I18N=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") + ";\n"
    )


def languages() -> list[dict[str, str]]:
    """The picker's options: each available locale in its own name."""
    return [{"code": code, "name": NAMES[code]} for code in available()]
