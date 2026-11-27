#!/usr/bin/env python3
"""Check translated locale files against their English source.

Standard library only, so every CashPilot repo (web UI, Desktop, Android, the
site, the docs) can copy this file unchanged.

Usage:
    i18n_check.py SOURCE TARGET [TARGET ...] [options]

    python scripts/i18n_check.py services/_i18n/en.yml services/_i18n/*.yml
    python scripts/i18n_check.py frontend/locales/en.json frontend/locales/*.json \
        --hashes-dir frontend/locales/.source-hashes
    python scripts/i18n_check.py app/src/main/res/values/strings.xml \
        app/src/main/res/values-*/strings.xml --hashes-dir i18n/source-hashes

What it reports, per target:
    missing      a source key that is absent from the target, or empty there   (error)
    placeholder  the target's placeholders differ from the source's            (error)
    extra        a target key the source does not have                         (warning)
    stale        the stored source hash does not match the current English     (warning)
    unstamped    hashes are in use for the target but this key has none        (warning)

It exits 1 on any error, 2 on a usage or parse error, and 0 otherwise.
--strict makes extra, stale and unstamped keys errors too. A target equal to
SOURCE is skipped, so a glob that also matches the source file is safe.

Formats (--format, default auto):
    json     nested objects, flattened to dotted keys ("a.b.c")
    yaml     nested mappings, flattened the same way. A single top-level key
             equal to the file's locale (Rails style, "fr:") is dropped.
    android  res/values*/strings.xml: <string>, <string-array> (keys
             "name[0]", "name[1]"...) and <plurals>. translatable="false"
             entries are not translatable and are ignored.
    catalog  CashPilot's services/_i18n/<locale>.yml: flat keys, each target
             value a mapping {text, source}. The source file (en.yml) holds
             plain strings.
    textdir  a directory of .txt files, one string per file, keyed by the
             relative path ("title.txt", "changelogs/42.txt"): fastlane's
             metadata/android/<locale>/. The locale is the directory name.
    auto     a directory -> textdir, .json -> json, .xml -> android,
             .yml/.yaml inside a directory named _i18n -> catalog, other
             .yml/.yaml -> yaml.

    In json and yaml files a translation may also be written inline as
    {"text": "...", "source": "<hash>"} (exactly those two keys); see below.

YAML is read by a small parser for the subset locale files use: block
mappings, plain, single- and double-quoted scalars, and | / > block scalars
with -/+ chomping. Sequences, flow collections, anchors and multi-line plain
or quoted scalars are rejected with the line number, never misread.

Plurals:
    ICU MessageFormat inside a string: {count, plural, one {...} other {...}}.
    Android <plurals> items. With --i18next-plurals, i18next key families
    ("files_one", "files_other", "files_few"...) are grouped under the base key.
    A plural's quantity set may differ from English (Russian has few/many,
    Japanese only other), but every plural must have "other". Placeholders are
    compared over the union of all forms.

Placeholders compared:
    ${NAME}                 shell-style, used in catalog health messages
    {{name}}                mustache / i18next
    {name}, {n, number}     ICU arguments, including the argument type
    {n, plural|select ...}  ICU plural, selectordinal and select (select keys must match)
    %s %d %1$s %.2f %@      printf / Java / Android, compared by position and type
    %(name)s                Python named
    <tag href="...">        HTML and Android markup: tag names, and each link's href
The ICU parser follows ICU's apostrophe rule: a quote starts literal text only
before { } (or # inside a plural), so "l'utilisateur" stays plain text.

Source hashes (the freshness check):
    hash = sha256(value.encode("utf-8")).hexdigest()[:12]

    "value" is the English source string exactly as this script's parser
    returns it: JSON and YAML string values after unescaping; for Android, the
    element's inner XML (text plus child markup) with XML entities decoded and
    Android backslash escapes left as written. A plural (Android <plurals>, an
    i18next family) hashes the forms sorted by quantity name, each written as
    "<quantity>\\x1e<text>" and joined with "\\x1f".

    Where the hash lives:
    - catalog format: inline, the "source" field of each target entry.
    - json and yaml: inline {"text", "source"} values, or a sidecar.
    - android and textdir: a sidecar JSON object {key: hash} at
      <--hashes-dir>/<locale>.json.
    A file with neither (no inline entry, no --hashes-dir) is not checked for
    freshness. Once a file has inline entries, a plain-string value in it is
    reported as unstamped. --hashes-dir wins over inline hashes. An inline
    entry is an object with exactly "text" and "source", where source is 12
    lowercase hex characters or empty; any other object is ordinary nesting.
    There is one sidecar per locale, so a locale split over several files
    (locales/fr/common.json, locales/fr/menu.json) needs a --hashes-dir per
    file set, or keys that are unique across the files.

    The locale of a file is its file name without the extension (fr.json,
    pt-BR.yml) when that looks like a BCP 47 tag, else its parent directory's
    name (locales/fr/common.json). For Android it comes from the values-*
    directory: values-fr -> fr, values-pt-rBR -> pt-BR, values-b+zh+Hans ->
    zh-Hans, and the legacy codes values-in -> id, values-tl -> fil,
    values-iw -> he. values-zh-rCN gives zh-CN.

--ignore GLOB skips source keys matching GLOB (repeatable), for example
--ignore 'changelogs/*' for fastlane changelogs that are not translated.

Stamping, after a translation is written or updated:
    --stamp            store the current source hash for every translated key
                       that has none yet
    --restamp GLOB     store it for every key matching GLOB (fnmatch), even when
                       a hash exists: use it after you updated a stale key.
                       Repeatable.
    Stamping rewrites catalog files in canonical form (comments are not kept)
    sidecar files as sorted JSON, and json targets without a sidecar inline
    (indent 2). yaml, android and textdir targets are never written.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import pathlib
import re
import sys
import tempfile
import xml.etree.ElementTree as ET

PLURAL_CATEGORIES = ("zero", "one", "two", "few", "many", "other")

# ---------------------------------------------------------------------------
# Hashing


def source_hash(value: str | dict[str, str]) -> str:
    """The stored freshness hash of one English value (see the module docstring)."""
    if isinstance(value, dict):
        value = "\x1f".join(f"{q}\x1e{value[q]}" for q in sorted(value))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# A strict YAML subset parser


class ParseError(Exception):
    pass


_BLOCK_HEADER = re.compile(r"^([|>])([+-]?)([1-9]?)([+-]?)$")


def _strip_comment(text: str) -> str:
    """Drop a trailing ' # comment' from an unquoted value."""
    m = re.search(r"(^|\s)#", text)
    return text[: m.start()].rstrip() if m else text.rstrip()


def _parse_double(s: str, lineno: int) -> tuple[str, str]:
    """Parse a double-quoted scalar at the start of s; return (value, rest)."""
    out = []
    i = 1
    escapes = {
        "0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v",
        "f": "\f", "r": "\r", "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\",
        "N": "\x85", "_": "\xa0", "L": "\u2028", "P": "\u2029",
    }  # fmt: skip
    while i < len(s):
        c = s[i]
        if c == '"':
            return "".join(out), s[i + 1 :]
        if c == "\\":
            i += 1
            if i >= len(s):
                break
            e = s[i]
            if e in escapes:
                out.append(escapes[e])
            elif e in "xuU":
                n = {"x": 2, "u": 4, "U": 8}[e]
                code = s[i + 1 : i + 1 + n]
                if len(code) != n or not all(ch in "0123456789abcdefABCDEF" for ch in code):
                    raise ParseError(f"line {lineno}: bad \\{e} escape")
                if int(code, 16) > 0x10FFFF:
                    raise ParseError(f"line {lineno}: \\{e}{code} is not a Unicode code point")
                if 0xD800 <= int(code, 16) <= 0xDFFF:
                    raise ParseError(f"line {lineno}: \\{e}{code} is a lone surrogate, not a character")
                out.append(chr(int(code, 16)))
                i += n
            else:
                raise ParseError(f"line {lineno}: unknown escape \\{e}")
        else:
            out.append(c)
        i += 1
    raise ParseError(f"line {lineno}: unterminated double-quoted string (multi-line quoted scalars are not supported)")


def _parse_single(s: str, lineno: int) -> tuple[str, str]:
    out = []
    i = 1
    while i < len(s):
        if s[i] == "'":
            if s[i + 1 : i + 2] == "'":
                out.append("'")
                i += 2
                continue
            return "".join(out), s[i + 1 :]
        out.append(s[i])
        i += 1
    raise ParseError(f"line {lineno}: unterminated single-quoted string (multi-line quoted scalars are not supported)")


def _parse_scalar(raw: str, lineno: int) -> str:
    raw = raw.strip()
    if raw.startswith('"') or raw.startswith("'"):
        value, rest = (_parse_double if raw[0] == '"' else _parse_single)(raw, lineno)
        if _strip_comment(rest):
            raise ParseError(f"line {lineno}: text after a quoted scalar: {rest.strip()!r}")
        return value
    value = _strip_comment(raw)
    if value[:1] in ("[", "{", "&", "*", "!", "|", ">", "@", "`"):
        raise ParseError(f"line {lineno}: unsupported YAML construct {value[:1]!r}")
    if ": " in value or value.endswith(":"):
        raise ParseError(f"line {lineno}: a plain value cannot contain ': '; quote it")
    if value in ("~", "null", "Null", "NULL"):
        return ""
    return value


def _split_key(line: str, lineno: int) -> tuple[str, str]:
    """Split 'key: rest' (key plain or quoted); return (key, rest after the colon)."""
    if line.startswith('"') or line.startswith("'"):
        key, rest = (_parse_double if line[0] == '"' else _parse_single)(line, lineno)
        if not rest.startswith(":"):
            raise ParseError(f"line {lineno}: expected ':' after the quoted key")
        return key, rest[1:]
    if line[:1] in ("[", "{", "&", "*", "!", "?", "|", ">", "@", "`", "%"):
        raise ParseError(f"line {lineno}: unsupported YAML construct {line[:1]!r} in a key")
    m = re.match(r"^([^:#]+?|[^:#]*?:[^\s][^#]*?)\s*:(\s|$)", line)
    if not m:
        raise ParseError(f"line {lineno}: expected 'key: value'")
    return m.group(1), line[m.end() :]


def parse_yaml(text: str) -> dict:
    """Parse the locale-file YAML subset into nested dicts of strings."""
    # Split on \n only: str.splitlines() also breaks at characters that can
    # sit inside a quoted value.
    lines = [ln[:-1] if ln.endswith("\r") else ln for ln in text.split("\n")]
    if text.endswith("\n"):
        lines.pop()  # the empty string after the final newline is not a line
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    pending: tuple[int, dict, str] | None = None  # a key waiting for its nested mapping
    i = 0
    while i < len(lines):
        lineno = i + 1
        line = lines[i]
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise ParseError(f"line {lineno}: tab in indentation")
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or (stripped == "---" and not root and pending is None):
            i += 1
            continue
        if stripped.startswith("- ") or stripped == "-":
            raise ParseError(f"line {lineno}: sequences are not supported in locale files")
        indent = len(line) - len(line.lstrip(" "))
        if pending is not None:
            p_indent, p_parent, p_key = pending
            if indent > p_indent:
                child: dict = {}
                p_parent[p_key] = child
                stack.append((indent, child))
            else:
                p_parent[p_key] = ""
            pending = None
        while stack and indent < stack[-1][0]:
            stack.pop()
        if not stack or indent != stack[-1][0] and stack[-1][0] != -1:
            raise ParseError(f"line {lineno}: inconsistent indentation")
        if stack[-1][0] == -1:
            if indent != 0:
                raise ParseError(f"line {lineno}: the document must start at column 0")
            stack[-1] = (0, root)
        parent = stack[-1][1]
        key, rest = _split_key(stripped, lineno)
        if key in parent:
            raise ParseError(f"line {lineno}: duplicate key {key!r}")
        rest_value = _strip_comment(rest).strip()
        header = _BLOCK_HEADER.match(rest_value)
        if header:
            style = header.group(1)
            chomp = header.group(2) or header.group(4)
            explicit = int(header.group(3)) if header.group(3) else None
            body: list[str] = []
            j = i + 1
            block_indent = indent + explicit if explicit else None
            while j < len(lines):
                ln = lines[j]
                if ln.strip() == "":
                    # Spaces past the block's indentation are content.
                    body.append(ln[block_indent:] if block_indent is not None and len(ln) > block_indent else "")
                    j += 1
                    continue
                ind = len(ln) - len(ln.lstrip(" "))
                if block_indent is None:
                    if ind <= indent:
                        break
                    block_indent = ind
                if ind < block_indent:
                    break
                body.append(ln[block_indent:])
                j += 1
            # A block that runs to the end of a file with no final newline
            # has no line break after its last line.
            parent[key] = _finish_block(body, style, chomp, j < len(lines) or text.endswith("\n"))
            i = j
            continue
        if rest_value == "":
            pending = (indent, parent, key)
            i += 1
            continue
        parent[key] = _parse_scalar(rest, lineno)
        i += 1
    if pending is not None:
        pending[1][pending[2]] = ""
    return root


def _finish_block(body: list[str], style: str, chomp: str, last_break: bool = True) -> str:
    content = list(body)
    trailing = 0
    while content and content[-1] == "":
        content.pop()
        trailing += 1
    if not content:
        return "\n" * trailing if chomp == "+" else ""
    if style == "|":
        text = "\n".join(content)
    else:
        # Folding: a line break between two ordinary lines becomes a space, and
        # each empty line between them a newline. Breaks next to a
        # more-indented line are kept as they are.
        text, prev, blanks = "", None, 0
        for ln in content:
            if ln == "":
                blanks += 1
                continue
            if prev is None:
                text = "\n" * blanks + ln
            elif ln[0] in " \t" or prev[0] in " \t":
                text += "\n" * (blanks + 1) + ln
            else:
                text += (" " if blanks == 0 else "\n" * blanks) + ln
            prev, blanks = ln, 0
    if chomp == "-":
        return text
    if chomp == "+":
        return text + "\n" * (trailing + int(last_break))
    return text + "\n" if last_break or trailing else text


def dump_yaml_string(value: str) -> str:
    """A double-quoted YAML scalar. JSON string syntax is valid YAML.

    YAML also breaks lines at U+0085, U+2028 and U+2029, which JSON leaves
    raw, so those are escaped too.
    """
    out = json.dumps(value, ensure_ascii=False)
    return out.replace("\x85", "\\x85").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


# ---------------------------------------------------------------------------
# Loaders. Each returns (entries, inline_hashes or None). An entry is a str or
# a dict of plural forms {quantity: text}.


_HASH = re.compile(r"^([0-9a-f]{12})?$")


def _is_inline(node) -> bool:
    """A {"text", "source"} translation entry: exactly those keys, source a hash or empty.

    An object of prose that happens to use those two key names has a source
    that is not a 12-hex hash, so it stays an ordinary nested object.
    """
    return (
        isinstance(node, dict)
        and set(node) == {"text", "source"}
        and isinstance(node["text"], str)
        and isinstance(node["source"], str)
        and bool(_HASH.match(node["source"]))
    )


def _flatten(node, prefix: str, out: dict, path: pathlib.Path, hashes: dict | None = None) -> None:
    if prefix in out:
        raise ParseError(f"{path}: {prefix}: the same key is written twice (a dotted key and a nested one)")
    if prefix == "" and _is_inline(node):
        raise ParseError(f"{path}: the whole file is one {{text, source}} entry, not a locale file")
    if _is_inline(node) and hashes is not None:
        out[prefix] = node["text"]
        hashes[prefix] = node["source"]
    elif isinstance(node, dict):
        for k, v in node.items():
            _flatten(v, f"{prefix}.{k}" if prefix else str(k), out, path, hashes)
    elif isinstance(node, str):
        out[prefix] = node
    elif isinstance(node, bool) or node is None:
        raise ParseError(f"{path}: {prefix}: expected a string, found {node!r}")
    elif isinstance(node, (int, float)):
        out[prefix] = str(node)
    else:
        raise ParseError(f"{path}: {prefix}: lists are not supported in locale files")


_BCP47 = re.compile(r"^[a-z]{2,3}(-[a-z]{4})?(-([a-z]{2}|[0-9]{3}))?$|^[a-z]{2,3}(_[a-z]{2})?$", re.IGNORECASE)


# Android still names some languages by their pre-1989 ISO 639 codes.
_ANDROID_LEGACY = {"in": "id", "iw": "he", "ji": "yi", "tl": "fil"}


def locale_of(path: pathlib.Path, fmt: str) -> str:
    if fmt == "android":
        d = path.parent.name
        if d == "values":
            return "en"
        tag = d[len("values-") :] if d.startswith("values-") else d
        if tag.startswith("b+"):
            return "-".join(tag[2:].split("+"))
        lang, _, region = tag.partition("-r")
        lang = _ANDROID_LEGACY.get(lang, lang)
        return f"{lang}-{region}" if region else lang
    if fmt == "textdir":
        return path.name
    stem = path.name.split(".")[0]
    return stem if _BCP47.match(stem) else path.parent.name


def _drop_locale_root(tree: dict, locale: str) -> dict:
    if len(tree) == 1:
        (only,) = tree
        same = only.lower().replace("_", "-") == locale.lower().replace("_", "-")
        if same and isinstance(tree[only], dict) and not _is_inline(tree[only]):
            return tree[only]
    return tree


def _no_duplicates(pairs: list) -> dict:
    out: dict = {}
    for k, v in pairs:
        if k in out:
            raise ParseError(f"duplicate key {k!r}")
        out[k] = v
    return out


def load_json(path: pathlib.Path) -> tuple[dict, dict]:
    try:
        tree = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicates)
    except (json.JSONDecodeError, ParseError) as e:
        raise ParseError(f"{path}: {e}") from e
    if not isinstance(tree, dict):
        raise ParseError(f"{path}: the top level must be an object")
    out: dict = {}
    hashes: dict = {}
    _flatten(_drop_locale_root(tree, locale_of(path, "json")), "", out, path, hashes)
    return out, hashes


def load_yaml(path: pathlib.Path) -> tuple[dict, dict]:
    try:
        tree = parse_yaml(path.read_text(encoding="utf-8"))
    except ParseError as e:
        raise ParseError(f"{path}: {e}") from e
    out: dict = {}
    hashes: dict = {}
    _flatten(_drop_locale_root(tree, locale_of(path, "yaml")), "", out, path, hashes)
    return out, hashes


def load_catalog(path: pathlib.Path) -> tuple[dict, dict]:
    try:
        tree = parse_yaml(path.read_text(encoding="utf-8"))
    except ParseError as e:
        raise ParseError(f"{path}: {e}") from e
    entries: dict = {}
    hashes: dict = {}
    for key, value in tree.items():
        if isinstance(value, str):
            entries[key] = value
        elif isinstance(value, dict) and set(value) <= {"text", "source"} and "text" in value:
            if not isinstance(value["text"], str):
                raise ParseError(f"{path}: {key}.text must be a string")
            entries[key] = value["text"]
            hashes[key] = str(value.get("source") or "")
        else:
            raise ParseError(f"{path}: {key}: expected a string or a mapping with 'text' and optional 'source'")
    return entries, hashes


def _write_atomic(path: pathlib.Path, text: str) -> None:
    """Replace path with text in one step, so a failed write leaves the old file."""
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    tmp = pathlib.Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_catalog(path: pathlib.Path, entries: dict, hashes: dict, header: str = "") -> None:
    lines = [header.rstrip("\n")] if header else []
    for key, text in entries.items():
        # A plain key must stay a string for every YAML reader: start with a
        # letter or "_", and never spell a YAML 1.1 bool or null.
        plain = re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.\-]*", key) and key.lower() not in (
            "null",
            "true",
            "false",
            "yes",
            "no",
            "on",
            "off",
            "~",
        )
        lines.append(f"{key if plain else dump_yaml_string(key)}:")
        lines.append(f"  text: {dump_yaml_string(text)}")
        if hashes.get(key):
            lines.append(f"  source: {dump_yaml_string(hashes[key])}")
    _write_atomic(path, "\n".join(lines) + "\n")


def _inner_xml(elem: ET.Element) -> str:
    parts = [elem.text or ""]
    for child in elem:
        parts.append(ET.tostring(child, encoding="unicode"))
    return "".join(parts).strip()


def load_android(path: pathlib.Path) -> dict:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        raise ParseError(f"{path}: {e}") from e
    out: dict = {}
    for elem in root:
        name = elem.get("name")
        if not name or elem.get("translatable") == "false":
            continue
        if elem.tag == "string":
            out[name] = _inner_xml(elem)
        elif elem.tag == "string-array":
            for idx, item in enumerate(elem.findall("item")):
                out[f"{name}[{idx}]"] = _inner_xml(item)
        elif elem.tag == "plurals":
            out[name] = {item.get("quantity", ""): _inner_xml(item) for item in elem.findall("item")}
    return out


def load_textdir(path: pathlib.Path) -> dict:
    """Every .txt file under a directory, keyed by its path relative to it (fastlane metadata)."""
    if not path.is_dir():
        raise ParseError(f"{path}: not a directory")
    return {f.relative_to(path).as_posix(): f.read_text(encoding="utf-8").strip() for f in sorted(path.rglob("*.txt"))}


def group_i18next_plurals(entries: dict) -> dict:
    out: dict = {}
    for key, value in entries.items():
        base, _, suffix = key.rpartition("_")
        if base and suffix in PLURAL_CATEGORIES and isinstance(value, str):
            out.setdefault(base, {})
            if not isinstance(out[base], dict):
                raise ParseError(f"{key}: '{base}' is both a plain key and a plural family")
            out[base][suffix] = value
        else:
            if isinstance(out.get(key), dict):
                raise ParseError(f"{key}: is both a plain key and a plural family")
            out[key] = value
    return out


def detect_format(path: pathlib.Path) -> str:
    if path.is_dir():
        return "textdir"
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix == ".xml":
        return "android"
    if suffix in (".yml", ".yaml"):
        return "catalog" if path.parent.name == "_i18n" else "yaml"
    raise ParseError(f"{path}: cannot tell the format from the extension; pass --format")


def load(path: pathlib.Path, fmt: str, i18next: bool) -> tuple[dict, dict | None]:
    """Return (entries, inline hashes or None)."""
    if fmt == "auto":
        fmt = detect_format(path)
    hashes = None
    if fmt == "json":
        entries, hashes = load_json(path)
        hashes = hashes or None
    elif fmt == "yaml":
        entries, hashes = load_yaml(path)
        hashes = hashes or None
    elif fmt == "catalog":
        entries, hashes = load_catalog(path)
    elif fmt == "android":
        entries = load_android(path)
    elif fmt == "textdir":
        entries = load_textdir(path)
    else:
        raise ParseError(f"unknown format {fmt!r}")
    if i18next:
        entries = group_i18next_plurals(entries)
        if hashes:
            # A family is current only when every form carries the same hash;
            # a form without one, or forms stamped against different English,
            # make the family stale.
            families: dict = {}
            for base, forms in entries.items():
                if not isinstance(forms, dict):
                    continue
                found = {hashes.get(f"{base}_{q}") for q in forms}
                if found != {None}:
                    families[base] = found.pop() if len(found) == 1 else "mixed"
            for base, forms in entries.items():
                if isinstance(forms, dict):
                    for q in forms:
                        hashes.pop(f"{base}_{q}", None)
            hashes.update(families)
    return entries, hashes


# ---------------------------------------------------------------------------
# Placeholders

_SHELL = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_MUSTACHE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_TAG = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)\b([^<>]*?)/?>")
_HREF = re.compile(r"""(?<![\w-])href\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_ATTR_VALUE = re.compile(r"""=\s*(?:"([^"]*)"|'([^']*)')""")
_PRINTF = re.compile(r"%(?:(\d+)\$)?([-#+0,(]*)(\d+|\*)?(?:\.(\d+|\*))?([sdfiuxXeEgGoc@])")
_PY_NAMED = re.compile(r"%\(([A-Za-z_][A-Za-z0-9_]*)\)[-#+0 ]*\d*(?:\.\d+)?([sdfiuxXeEgGoc])")
_ICU_COMPLEX = re.compile(r"\{\s*[\w.\-]+\s*,\s*(plural|selectordinal|select)\s*,")


class IcuError(Exception):
    pass


def _icu_scan(s: str, i: int, in_plural: bool, out: set, depth: int) -> int:
    """Scan message text from i until an unmatched '}' (returned) or the end."""
    n = len(s)
    while i < n:
        c = s[i]
        if c == "'":
            nxt = s[i + 1 : i + 2]
            if nxt == "'":
                i += 2
                continue
            if nxt in ("{", "}") or (in_plural and nxt == "#"):
                end = s.find("'", i + 1)
                while end != -1 and s[end + 1 : end + 2] == "'":
                    end = s.find("'", end + 2)
                if end == -1:
                    raise IcuError("unterminated quote")
                i = end + 1
                continue
            i += 1
            continue
        if c == "#" and in_plural:
            out.add(("plural-number",))  # the count shown in a plural branch
        if c == "{":
            i = _icu_argument(s, i + 1, out, depth)
            continue
        if c == "}":
            if depth == 0:
                raise IcuError("unmatched '}'")
            return i
        i += 1
    if depth:
        raise IcuError("unclosed '{'")
    return i


_ICU_HEAD = re.compile(r"\s*([\w.\-]+)\s*(?:,\s*(\w+)\s*)?")
_ICU_OPTION = re.compile(r"\s*(offset:\s*\d+|=?[\w\-]+)\s*")


def _icu_argument(s: str, i: int, out: set, depth: int) -> int:
    """Parse one argument starting just after its '{'; return the index after its '}'."""
    m = _ICU_HEAD.match(s, i)
    if not m:
        raise IcuError("bad argument name")
    name, kind = m.group(1), m.group(2)
    j = m.end()
    if kind is None:
        if s[j : j + 1] != "}":
            raise IcuError(f"bad argument {name!r}")
        out.add(("arg", name))
        return j + 1
    if kind in ("plural", "selectordinal", "select"):
        if s[j : j + 1] != ",":
            raise IcuError(f"{kind} {name!r} has no options")
        j += 1
        keys: list[str] = []
        while True:
            while j < len(s) and s[j].isspace():
                j += 1
            if j >= len(s):
                raise IcuError("unclosed '{'")
            if s[j] == "}":
                break
            o = _ICU_OPTION.match(s, j)
            if not o:
                raise IcuError(f"bad {kind} option in {name!r}")
            j = o.end()
            if o.group(1).startswith("offset:"):
                continue
            if s[j : j + 1] != "{":
                raise IcuError(f"{kind} option {o.group(1)!r} needs a {{message}}")
            keys.append(o.group(1))
            j = _icu_scan(s, j + 1, kind != "select", out, depth + 1) + 1
        if kind == "select":
            out.add(("select", name, tuple(sorted(keys))))
        else:
            out.add((kind, name))
            if "other" not in keys:
                out.add(("no-other", name))
        return j + 1
    # number, date, time, ... with an optional style
    if s[j : j + 1] == "}":
        out.add(("arg", name, kind))
        return j + 1
    if s[j : j + 1] == ",":
        end = s.find("}", j)
        if end == -1 or "{" in s[j:end]:
            raise IcuError(f"bad style in {name!r}")
        out.add(("arg", name, kind))
        return end + 1
    raise IcuError(f"bad argument {name!r}")


def placeholders(text: str) -> frozenset:
    """The placeholder signature of one string."""
    out: set = set()

    links: dict = {}
    # In an ICU plural or select each branch may repeat a link, and other
    # languages have more branches, so a link inside braces is not counted.
    icu = bool(_ICU_COMPLEX.search(text))

    def tag(m: re.Match) -> str:
        href = _HREF.search(m.group(3))
        dest = (href.group(1) or href.group(2)) if href else ""
        out.add(("tag", m.group(1) + m.group(2).lower(), dest))
        before = text[: m.start()]
        if href and not (icu and before.count("{") > before.count("}")):
            # links to A, A, B differ from links to A, B, B
            links[dest] = links.get(dest, 0) + 1
            out.add(("link", dest, links[dest]))
        # A placeholder in another attribute (title="{name}") still counts: the
        # tag becomes its attribute values, unquoted and in place, so implicit
        # printf positions keep their order.
        values = [a or b for a, b in _ATTR_VALUE.findall(_HREF.sub("", m.group(3)))]
        return " " + " ".join(values) + " " if values else ""

    text = _TAG.sub(tag, text)
    for m in _SHELL.finditer(text):
        out.add(("shell", m.group(1)))
    body = _SHELL.sub("", text)
    # In an ICU plural or select, "{{" is a branch opening on an argument
    # ("other {{who} has #}"), not a mustache placeholder.
    if not _ICU_COMPLEX.search(body):
        for m in _MUSTACHE.finditer(body):
            out.add(("mustache", m.group(1)))
        body = _MUSTACHE.sub("", body)
    body = body.replace("%%", "")  # a literal percent sign, never a conversion
    for m in _PY_NAMED.finditer(body):
        conv = m.group(2)
        out.add(("py", m.group(1), "s" if conv == "s" else ("d" if conv in "diu" else conv)))
    body = _PY_NAMED.sub("", body)
    # Unindexed conversions take the next argument in turn, and a "*" width or
    # precision takes one too (an integer); %2$s does not move that counter.
    implicit = 0
    for m in _PRINTF.finditer(body):
        for star in (m.group(3), m.group(4)):
            if star == "*":
                implicit += 1
                out.add(("printf", implicit, "d"))
        conv = m.group(5)
        if m.group(1):
            pos = int(m.group(1))
        else:
            implicit += 1
            pos = implicit
        out.add(("printf", pos, "s" if conv in "s@" else ("d" if conv in "diu" else conv)))
    body = _PRINTF.sub("", body)
    if "{" in body or "}" in body:
        try:
            _icu_scan(body, 0, False, out, 0)
        except IcuError:
            out.add(("broken-braces",))
            out.update(("arg", n) for n in re.findall(r"\{\s*([\w.\-]+)\s*\}", body))
    return frozenset(out)


def signature(value: str | dict) -> frozenset:
    if isinstance(value, dict):
        sig: set = set()
        for form in value.values():
            sig |= placeholders(form)
        return frozenset(sig)
    return placeholders(value)


def _describe(sig: frozenset) -> str:
    def one(t: tuple) -> str:
        kind = t[0]
        if kind == "shell":
            return "${" + t[1] + "}"
        if kind == "mustache":
            return "{{" + t[1] + "}}"
        if kind == "py":
            return f"%({t[1]}){t[2]}"
        if kind == "printf":
            return f"%{t[1]}${t[2]}"
        if kind == "arg":
            return "{" + t[1] + ("" if len(t) == 2 else f", {t[2]}") + "}"
        if kind in ("plural", "selectordinal"):
            return "{" + t[1] + f", {kind}}}"
        if kind == "select":
            return "{" + t[1] + ", select: " + "|".join(t[2]) + "}"
        if kind == "no-other":
            return f"(no 'other' branch in {t[1]})"
        if kind == "tag":
            return f"<{t[1]}" + (f" href={t[2]}" if t[2] else "") + ">"
        if kind == "broken-braces":
            return "(unbalanced braces)"
        return str(t)

    return ", ".join(sorted(one(t) for t in sig)) or "none"


# ---------------------------------------------------------------------------
# The check


def is_empty(value) -> bool:
    if isinstance(value, dict):
        return not value or all(not v.strip() for v in value.values())
    return not value.strip()


def check_target(source: dict, target: dict, hashes: dict | None) -> dict:
    """Compare one target with the source. Returns lists of findings by kind."""
    found: dict[str, list] = {k: [] for k in ("missing", "placeholder", "extra", "stale", "unstamped")}
    for key, src in source.items():
        if is_empty(src):
            continue
        tgt = target.get(key)
        if tgt is None or is_empty(tgt):
            found["missing"].append((key, ""))
            continue
        if isinstance(src, dict) != isinstance(tgt, dict):
            found["placeholder"].append((key, "the source is " + ("a plural" if isinstance(src, dict) else "a string")))
            continue
        if isinstance(tgt, dict) and not (tgt.get("other") or "").strip():
            found["placeholder"].append((key, "the plural has no 'other' form"))
        elif isinstance(tgt, dict) and any(not (v or "").strip() for v in tgt.values()):
            # A form given as "" would show nothing for its counts.
            empty = sorted(q for q, v in tgt.items() if not (v or "").strip())
            found["placeholder"].append((key, f"empty plural form {', '.join(empty)}"))
        s_sig, t_sig = signature(src), signature(tgt)
        no_other = sorted(t[1] for t in t_sig if t[0] == "no-other")
        if no_other:
            # Reported even when the English lacks it too: ICU needs "other".
            found["placeholder"].append((key, f"no 'other' branch in {', '.join(no_other)}"))
        elif s_sig != t_sig:
            found["placeholder"].append((key, f"source {_describe(s_sig)}; target {_describe(t_sig)}"))
        if hashes is not None:
            stored = hashes.get(key)
            if not stored:
                found["unstamped"].append((key, ""))
            elif stored != source_hash(src):
                found["stale"].append((key, f"stored {stored}, English is now {source_hash(src)}"))
    for key in target:
        if key not in source:
            found["extra"].append((key, ""))
    return found


def _sidecar(hashes_dir: pathlib.Path | None, locale: str) -> pathlib.Path | None:
    return hashes_dir / f"{locale}.json" if hashes_dir else None


def _load_sidecar(path: pathlib.Path | None) -> dict | None:
    if path is None:
        return None
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
        raise ParseError(f"{path}: expected a JSON object of key -> hash strings")
    return data


def stamp(source: dict, target: dict, hashes: dict, patterns: list[str], missing_only: bool) -> int:
    """Store current source hashes in `hashes`; return how many changed."""
    changed = 0
    for key, value in target.items():
        if key not in source or is_empty(value):
            continue
        want = source_hash(source[key])
        restamp = any(fnmatch.fnmatchcase(key, p) for p in patterns)
        if ((missing_only and not hashes.get(key)) or restamp) and hashes.get(key) != want:
            hashes[key] = want
            changed += 1
    return changed


def _leading_comments(path: pathlib.Path) -> str:
    """The comment block at the top of a file, kept when the file is rewritten."""
    head = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.startswith("#"):
            break
        head.append(ln)
    return "\n".join(head) + "\n" if head else ""


def write_json_inline(path: pathlib.Path, hashes: dict, checked: dict) -> None:
    """Rewrite a JSON locale file with every hashed leaf as {"text", "source"}.

    `checked` is what the check read; a file that changed since is refused.
    """
    if load_json(path)[0] != checked:
        raise ParseError(f"{path}: the file changed while it was being checked; run again")
    tree = json.loads(path.read_text(encoding="utf-8"))
    root = _drop_locale_root(tree, locale_of(path, "json"))

    def walk(node: dict, prefix: str) -> None:
        for k, v in node.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (str, int, float)) and not isinstance(v, bool) and key in hashes:
                node[k] = {"text": str(v), "source": hashes[key]}
            elif _is_inline(v) and key in hashes:
                v["source"] = hashes[key]
            elif isinstance(v, dict) and not _is_inline(v):
                walk(v, key)

    walk(root, "")
    _write_atomic(path, json.dumps(tree, ensure_ascii=False, indent=2) + "\n")


def _drop_ignored(entries: dict, globs: list[str]) -> dict:
    return {k: v for k, v in entries.items() if not any(fnmatch.fnmatchcase(k, g) for g in globs)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("source", type=pathlib.Path, help="the English source locale file")
    ap.add_argument("targets", type=pathlib.Path, nargs="+", help="translated locale files")
    ap.add_argument("--format", default="auto", choices=["auto", "json", "yaml", "android", "catalog", "textdir"])
    ap.add_argument("--hashes-dir", type=pathlib.Path, help="directory of <locale>.json source-hash sidecars")
    ap.add_argument("--i18next-plurals", action="store_true", help="group key_one/key_other... families")
    ap.add_argument("--ignore", action="append", default=[], metavar="GLOB", help="skip source keys matching GLOB")
    ap.add_argument("--strict", action="store_true", help="extra, stale and unstamped keys fail too")
    ap.add_argument("--stamp", action="store_true", help="store hashes for translated keys that have none")
    ap.add_argument(
        "--restamp", action="append", default=[], metavar="GLOB", help="re-store hashes for keys matching GLOB"
    )
    ap.add_argument("--max-listed", type=int, default=50, help="findings listed per kind and file (default 50)")
    args = ap.parse_args(argv)

    try:
        source, _ = load(args.source, args.format, args.i18next_plurals)
        source = _drop_ignored(source, args.ignore)
    except (ParseError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    errors = warnings = 0
    fail_kinds = {"missing", "placeholder"} | ({"extra", "stale", "unstamped"} if args.strict else set())
    targets = [t for t in args.targets if t.resolve() != args.source.resolve()]
    inputs = {p.resolve() for p in (args.source, *targets)}
    for path in targets:
        fmt = args.format if args.format != "auto" else None
        try:
            fmt = fmt or detect_format(path)
            whole, inline = load(path, fmt, args.i18next_plurals)
            # Ignored keys leave the comparison, never the file a stamp rewrites.
            target = _drop_ignored(whole, args.ignore)
            # An explicit --hashes-dir wins over inline hashes; the catalog
            # format always keeps them inline.
            sidecar = _sidecar(args.hashes_dir, locale_of(path, fmt)) if fmt != "catalog" else None
            if sidecar is not None and sidecar.resolve() in inputs:
                print(
                    f"error: {sidecar}: the hash file is also an input file; pick another --hashes-dir", file=sys.stderr
                )
                return 2
            hashes = _load_sidecar(sidecar) if sidecar is not None else inline
        except (ParseError, OSError, ValueError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2

        if args.stamp or args.restamp:
            inline_json = fmt == "json" and sidecar is None
            if args.i18next_plurals and (inline_json or fmt == "catalog"):
                # A family's hash cannot be written back onto its _one/_other leaves.
                fix = "is not supported" if fmt == "catalog" else "needs --hashes-dir"
                print(f"error: {path}: stamping i18next plural families in the {fmt} format {fix}", file=sys.stderr)
                return 2
            if hashes is None and inline_json:
                hashes = {}  # stamp inline: values become {"text", "source"}
            if hashes is None or (sidecar is None and fmt not in ("catalog", "json")):
                print(f"error: {path}: stamping the {fmt} format needs --hashes-dir", file=sys.stderr)
                return 2
            n = stamp(source, target, hashes, args.restamp, args.stamp)
            if n:
                try:
                    if fmt == "catalog":
                        write_catalog(path, whole, hashes, _leading_comments(path))
                    elif sidecar is not None:
                        sidecar.parent.mkdir(parents=True, exist_ok=True)
                        _write_atomic(sidecar, json.dumps(hashes, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
                    else:
                        write_json_inline(path, hashes, whole)
                except (OSError, ParseError) as e:
                    print(
                        f"error: writing the hashes for {path} failed: {e}. Earlier targets stay stamped.",
                        file=sys.stderr,
                    )
                    return 2
                print(f"{path}: stamped {n} key(s)")

        found = check_target(source, target, hashes)
        counts = ", ".join(f"{len(v)} {k}" for k, v in found.items() if v) or "ok"
        print(f"{path}: {counts}")
        for kind, items in found.items():
            for key, detail in items[: args.max_listed]:
                print(f"  {kind:<11} {key}" + (f": {detail}" if detail else ""))
            if len(items) > args.max_listed:
                print(f"  {kind:<11} ... and {len(items) - args.max_listed} more")
            if kind in fail_kinds:
                errors += len(items)
            else:
                warnings += len(items)

    print(f"{len(targets)} target(s), {len(source)} source key(s): {errors} error(s), {warnings} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
