"""Read another tool's config files into catalog fields, and nothing more.

Pure functions: no I/O beyond loading ``sources.yml`` once, no network, no
subprocess, no shell. A pasted file is untrusted text. Nothing in it is run,
expanded or fetched, and a value whose meaning depends on a shell is not
guessed at: it is marked for retyping.

The flow is ``read_files`` (text to per-file settings), ``detect_source``
(which tool wrote them), then ``build_preview`` (settings to one row per
CashPilot service, checked against the catalog). The router does the rest.
"""

from __future__ import annotations

import fnmatch
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.constants import UNDEPLOYABLE_STATUSES

MAX_FILES = 4
MAX_TOTAL_BYTES = 64 * 1024
MAX_LINES = 5000
MAX_LINE_BYTES = 8 * 1024
MAX_VALUE_BYTES = 4 * 1024
MAX_JSON_KEYS = 1000
MAX_JSON_DEPTH = 20
MAX_NAME_LEN = 200

SOURCES = ("money4band", "cashfactory", "internetincome")

_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PLACEHOLDER_RE = re.compile(r"<[^<>]*>|your[A-Z]{3,}")
# One line of InternetIncome's earnapp.txt: "<date> <time> https://earnapp.com/r/sdk-node-<id>".
_EARNAPP_LINE_RE = re.compile(r"https://earnapp\.com/r/(\S+)")
_HEX64_RE = re.compile(r"[0-9A-Fa-f]{64}")
# The scheme of one proxies.txt line ("socks5://user:pass@host:port"). The rest
# is checked by hand in _is_proxy_line: no backtracking on a pasted line.
_PROXY_SCHEME_RE = re.compile(r"[a-z0-9]+")
# What a shell would do something with in an unquoted word. InternetIncome
# runs every value through `eval "echo $value"`, so an unquoted value holding
# any of these is not the value its tool actually used.
_SHELL_SPECIAL = set("$`\\\"'*?[]{}()<>|&;~!#") | {" ", "\t"}

_SOURCES_PATH = Path(__file__).with_name("sources.yml")


def load_sources() -> dict[str, Any]:
    with _SOURCES_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


SOURCES_DATA: dict[str, Any] = load_sources()


class ImportRefused(ValueError):
    """A file the importer will not read. ``status`` is the HTTP code to answer with.

    The message never quotes the file: it may be a credential.
    """

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class Value:
    """One setting read from a file. ``text`` is None when it cannot be trusted."""

    text: str | None
    retype: bool = False


@dataclass
class FileSettings:
    name: str
    kind: str  # json | env | devices (earnapp.txt, proxyrack.txt) | proxies
    env: dict[str, Value] = field(default_factory=dict)
    json: dict[str, Any] | None = None
    extra_lines: int = 0  # state files: entries past the first


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _check_text(name: str, content: str) -> str:
    if "\x00" in content:
        raise ImportRefused(f"{name} is not a text file.")
    try:
        content.encode("utf-8")
    except UnicodeEncodeError:
        raise ImportRefused(f"{name} is not a UTF-8 text file.") from None
    content = content.lstrip("\ufeff")
    lines = content.splitlines()
    if len(lines) > MAX_LINES:
        raise ImportRefused(f"{name} has more than {MAX_LINES} lines; this is not a config file.")
    if any(len(line.encode("utf-8")) > MAX_LINE_BYTES for line in lines):
        raise ImportRefused(f"{name} has a line longer than {MAX_LINE_BYTES // 1024} KiB.")
    return content


def _strip_inline_comment(raw: str) -> str:
    """Cut a ` # comment` after an unquoted value; a `#` inside a word stays."""
    match = re.search(r"\s#", raw)
    return raw[: match.start()] if match else raw


def _read_env_value(raw: str, shell: bool) -> Value:
    """One value as the tool that reads it would see it, or marked for retyping.

    ``shell`` is InternetIncome's reading (``eval "echo $value"``); otherwise
    Docker Compose's .env reading. Single quotes are literal in both. Anything
    a shell or Compose would expand is never imported, because its real value
    is whatever that expansion produced, and finding out would mean running it.
    """
    raw = raw.strip()
    if not raw:
        return Value("")
    quote = raw[0]
    if quote == "'":
        end = raw.find("'", 1)
        if end == -1 or _strip_inline_comment(raw[end + 1 :]).strip():
            # Unterminated, or 'it'\''s'-style concatenation: a shell's reading.
            return Value(None, retype=True)
        return Value(raw[1:end])
    if quote == '"':
        end = 1
        while end < len(raw):
            if raw[end] == "\\":
                end += 2
                continue
            if raw[end] == '"':
                break
            end += 1
        if end >= len(raw) or _strip_inline_comment(raw[end + 1 :]).strip():
            return Value(None, retype=True)
        inner = raw[1:end]
        # Escapes mean different things to a shell and to Compose; $ and ` expand in both.
        if any(ch in inner for ch in "$`\\"):
            return Value(None, retype=True)
        return Value(inner)
    value = _strip_inline_comment(raw).strip()
    special = _SHELL_SPECIAL if shell else {"$", "`"}
    if any(ch in special for ch in value):
        return Value(None, retype=True)
    return Value(value)


def _parse_env(text: str, shell: bool) -> dict[str, Value]:
    env: dict[str, Value] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].lstrip()
        key, sep, raw = stripped.partition("=")
        key = key.strip()
        if not sep or not _KEY_RE.fullmatch(key):
            continue
        value = _read_env_value(raw, shell)
        if value.text is not None and len(value.text.encode("utf-8")) > MAX_VALUE_BYTES:
            value = Value(None, retype=True)
        env[key] = value
    return env


def _json_depth_ok(node: Any, depth: int = 0) -> bool:
    if depth > MAX_JSON_DEPTH:
        return False
    if isinstance(node, dict):
        return all(_json_depth_ok(v, depth + 1) for v in node.values())
    if isinstance(node, list):
        return all(_json_depth_ok(v, depth + 1) for v in node)
    return True


def _parse_json(name: str, text: str) -> dict[str, Any]:
    count = 0

    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        nonlocal count
        count += len(pairs)
        if count > MAX_JSON_KEYS:
            raise ImportRefused(f"{name} has more than {MAX_JSON_KEYS} keys; this is not a config file.")
        return dict(pairs)

    try:
        data = json.loads(text, object_pairs_hook=hook)
    except ImportRefused:
        raise
    except (ValueError, RecursionError):
        raise ImportRefused(f"{name} is not valid JSON.") from None
    if not isinstance(data, dict):
        raise ImportRefused(f"{name} is not a JSON object.")
    if not _json_depth_ok(data):
        raise ImportRefused(f"{name} is nested too deeply; this is not a config file.")
    return data


def _is_proxy_line(line: str) -> bool:
    scheme, sep, rest = line.partition("://")
    return bool(sep and rest and _PROXY_SCHEME_RE.fullmatch(scheme) and not any(c.isspace() for c in rest))


def _state_file(name: str, text: str) -> FileSettings | None:
    """InternetIncome's earnapp.txt or proxyrack.txt, or a proxies list; None otherwise.

    Only the first entry is taken: it is the device the main container used,
    the one the user linked to their account. The rest belong to proxy copies.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not lines:
        return None
    if all(_EARNAPP_LINE_RE.search(ln) for ln in lines):
        first = _EARNAPP_LINE_RE.search(lines[0]).group(1)
        return FileSettings(name, "devices", env={"earnapp.txt": Value(first)}, extra_lines=len(lines) - 1)
    if all(_HEX64_RE.fullmatch(ln) for ln in lines):
        return FileSettings(name, "devices", env={"proxyrack.txt": Value(lines[0])}, extra_lines=len(lines) - 1)
    if all(_is_proxy_line(ln) for ln in lines):
        return FileSettings(name, "proxies", extra_lines=len(lines))
    return None


def read_files(files: Any, source: str = "auto") -> list[FileSettings]:
    """Check and read the uploaded files. Raises ImportRefused on anything off."""
    if not isinstance(files, list) or not files:
        raise ImportRefused("Add at least one file.")
    if len(files) > MAX_FILES:
        raise ImportRefused(f"At most {MAX_FILES} files at a time.")
    total = 0
    checked: list[tuple[str, str]] = []
    for i, item in enumerate(files, 1):
        if not isinstance(item, dict):
            raise ImportRefused("Each file needs a name and its content.")
        name, content = item.get("name"), item.get("content")
        if not isinstance(content, str):
            raise ImportRefused("Each file needs a name and its content.")
        name = name if isinstance(name, str) and name.strip() else f"file {i}"
        name = "".join(ch for ch in name if ch.isprintable())[:MAX_NAME_LEN] or f"file {i}"
        try:
            total += len(content.encode("utf-8"))
        except UnicodeEncodeError:
            raise ImportRefused(f"{name} is not a UTF-8 text file.") from None
        if total > MAX_TOTAL_BYTES:
            raise ImportRefused(f"The files add up to more than {MAX_TOTAL_BYTES // 1024} KiB.", status=413)
        checked.append((name, _check_text(name, content)))

    shell = source == "internetincome"
    result = []
    env_texts: list[tuple[FileSettings, str]] = []
    for name, text in checked:
        if text.lstrip().startswith("{"):
            result.append(FileSettings(name, "json", json=_parse_json(name, text)))
            continue
        state = _state_file(name, text)
        if state is not None:
            result.append(state)
            continue
        fs = FileSettings(name, "env", env=_parse_env(text, shell))
        result.append(fs)
        env_texts.append((fs, text))
    if not shell and source == "auto" and "internetincome" in {_file_tool(f) for f in result}:
        # Any file naming InternetIncome (its properties.conf, earnapp.txt or
        # proxyrack.txt) means every env file went through its shell: read
        # them all that way, not just the one carrying the marker.
        for fs, text in env_texts:
            fs.env = _parse_env(text, True)
    return result


# ---------------------------------------------------------------------------
# Which tool
# ---------------------------------------------------------------------------


def _tools() -> dict[str, Any]:
    return SOURCES_DATA["tools"]


def _guess_tool_env(env: dict[str, Value]) -> str | None:
    hits = set()
    for tool, spec in _tools().items():
        markers = spec.get("markers") or {}
        if any(k in env for k in markers.get("keys") or []):
            hits.add(tool)
        for key, want in (markers.get("values") or {}).items():
            got = env.get(key)
            if got is not None and (got.text or "").strip().lower() == str(want).lower():
                hits.add(tool)
    return hits.pop() if len(hits) == 1 else ("ambiguous" if hits else None)


def _file_tool(fs: FileSettings) -> str | None:
    if fs.kind == "json":
        return "money4band" if isinstance(fs.json.get("apps"), dict) else None
    if fs.kind == "devices":
        return "internetincome"
    if fs.kind == "proxies":
        return None
    return _guess_tool_env(fs.env)


def detect_source(files: list[FileSettings], source: str = "auto") -> str:
    """The tool that wrote ``files``. Never guesses between two."""
    seen = {t for t in (_file_tool(f) for f in files) if t}
    if "ambiguous" in seen:
        raise ImportRefused("These files could come from more than one tool. Pick the tool you used.")
    if source in SOURCES:
        others = seen - {source}
        if others:
            name = _tools()[sorted(others)[0]]["name"]
            raise ImportRefused(f"These files look like {name}'s, not {_tools()[source]['name']}'s. Check the tool.")
        return source
    if len(seen) > 1:
        raise ImportRefused("These files come from different tools. Import one tool at a time.")
    if not seen:
        raise ImportRefused("Could not tell which tool wrote these files. Pick the tool you used.")
    return seen.pop()


# ---------------------------------------------------------------------------
# Mapping onto the catalog
# ---------------------------------------------------------------------------


def is_placeholder(text: str) -> bool:
    return not text.strip() or bool(_PLACEHOLDER_RE.search(text))


def _matches(key: str, patterns: Any) -> bool:
    return any(fnmatch.fnmatchcase(key, str(p)) for p in patterns or [])


def _not_carried_reason(key: str, spec: dict[str, Any]) -> str | None:
    for pattern, reason in (spec.get("not_carried") or {}).items():
        if fnmatch.fnmatchcase(key, pattern):
            return str(reason)
    return None


def field_problem(var: dict[str, Any], text: str) -> str | None:
    """Why the deploy would refuse ``text`` for catalog field ``var``, or None.

    The same rule api_deploy applies (a value must fullmatch the field's
    pattern), so the dry run shows what the deploy would refuse.
    """
    # A JSON "\u0000" decodes to a NUL after the file's own NUL check; no env
    # value can carry one.
    if "\x00" in text:
        return "invalid"
    pattern = var.get("pattern")
    if pattern and text and not re.fullmatch(pattern, text):
        return "invalid"
    return None


@dataclass
class _App:
    name: str
    spec: dict[str, Any]
    values: dict[str, Value]  # catalog env key -> value read
    present: bool
    enabled: bool = True


def _apps_from_json(files: list[FileSettings], spec: dict[str, Any], skipped: list[dict[str, str]]) -> list[_App]:
    apps_spec = spec.get("apps") or {}
    found: list[_App] = []
    for fs in files:
        if fs.kind != "json":
            continue
        data = fs.json or {}
        for top in data:
            if top == "apps" or top in (spec.get("ignore_json") or []):
                continue
            node = data.get(top)
            if top in ("proxies", "notifications") and not (isinstance(node, dict) and node.get("enabled")):
                continue
            reason = _not_carried_reason(top, spec) or "CashPilot does not read this setting."
            skipped.append({"key": top, "reason": reason})
        apps_conf = data.get("apps") or {}
        if not isinstance(apps_conf, dict):
            raise ImportRefused("The apps setting is not an object.")
        for app_name, app_conf in apps_conf.items():
            if not isinstance(app_conf, dict):
                continue
            app_spec = apps_spec.get(app_name)
            if app_spec is None:
                skipped.append({"key": str(app_name)[:80], "reason": "CashPilot has no such service."})
                continue
            values: dict[str, Value] = {}
            for env_key, src in (app_spec.get("fields") or {}).items():
                leaf = app_conf.get(src.get("json"))
                if isinstance(leaf, bool) or not isinstance(leaf, (str, int)):
                    continue
                text = str(leaf)
                values[env_key] = Value(None, retype=True) if len(text.encode()) > MAX_VALUE_BYTES else Value(text)
            enabled = app_conf.get("enabled") is True
            # Off with only template placeholders: the user never set this app up. Every
            # leaf counts, mapped or not, so an app CashPilot cannot carry still shows why.
            has_value = any(
                isinstance(leaf, (str, int)) and not isinstance(leaf, bool) and not is_placeholder(str(leaf))
                for key, leaf in app_conf.items()
                if key != "enabled"
            )
            if not (enabled or has_value):
                continue
            found.append(_App(app_name, app_spec, values, present=True, enabled=enabled))
    return found


def _apps_from_env(files: list[FileSettings], spec: dict[str, Any], skipped: list[dict[str, str]]) -> list[_App]:
    env: dict[str, Value] = {}
    for fs in files:
        if fs.kind in ("env", "devices"):
            env.update(fs.env)
        if fs.kind == "proxies":
            skipped.append(
                {"key": fs.name, "reason": _not_carried_reason("proxies.txt", spec) or "Proxies are not imported."}
            )
    claimed: set[str] = set()
    found: list[_App] = []
    for app_name, app_spec in (spec.get("apps") or {}).items():
        values: dict[str, Value] = {}
        own_keys: list[str] = []
        for env_key, src in (app_spec.get("fields") or {}).items():
            aliases = src.get("env") or []
            own_keys += aliases
            for alias in aliases:
                if alias in env:
                    values[env_key] = env[alias]
                    break
        own_keys += app_spec.get("other_env") or []
        on = False
        for key, want in (app_spec.get("on_env") or {}).items():
            got = env.get(key)
            if got is not None and (want == "*" or (got.text or "").strip().lower() == str(want).lower()):
                on = True
            claimed.add(key)
        claimed.update(own_keys)
        # An untouched template placeholder is not a value: the user never set this app up.
        has_value = any(env[k].retype or not is_placeholder(env[k].text or "") for k in own_keys if k in env)
        if on or has_value:
            found.append(_App(app_name, app_spec, values, present=True, enabled=True))
    for key, value in env.items():
        if key in claimed or _matches(key, spec.get("ignore_env")):
            continue
        if not value.retype and (value.text or "").strip().lower() in ("", "false"):
            continue  # blank or false: the old tool's way of saying "off"
        reason = _not_carried_reason(key, spec)
        skipped.append({"key": key, "reason": reason or "CashPilot does not read this setting."})
    return found


def build_preview(
    files: list[FileSettings],
    source: str,
    get_service: Callable[[str], dict[str, Any] | None],
    extra: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """One row per CashPilot service the files configure, plus what was left out.

    Each row carries ``env``, the values that would be deployed, under a key
    the router strips before anything leaves the server.
    """
    spec = _tools()[source]
    skipped: list[dict[str, str]] = []
    apps = _apps_from_json(files, spec, skipped) + _apps_from_env(files, spec, skipped)
    extra = extra or {}

    rows: dict[str, dict[str, Any]] = {}
    for app in apps:
        slug = app.spec["slug"]
        svc = get_service(slug)
        if not svc or slug in rows:
            continue
        rows[slug] = _row(app, svc, extra.get(slug) or {})

    notices = [spec["stop"]]
    proxies = sum(1 for s in skipped if "Proxies" in s["reason"])
    if proxies:
        notices.append(
            "Proxy settings were found and left out. Add each proxy in the Proxies section of the Fleet page."
        )
    for fs in files:
        if fs.kind == "devices" and fs.extra_lines:
            notices.append(
                f"{fs.name} lists {fs.extra_lines} more device(s) after the first. They belonged to "
                "proxy copies and are not imported; only the first, your main device, is."
            )
    return {
        "source": source,
        "source_name": spec["name"],
        "rows": sorted(rows.values(), key=lambda r: r["name"].lower()),
        "not_imported": skipped,
        "notices": notices,
    }


def _row(app: _App, svc: dict[str, Any], extra: dict[str, str]) -> dict[str, Any]:
    slug = svc["slug"]
    docker_env = {v["key"]: v for v in (svc.get("docker") or {}).get("env") or []}
    row: dict[str, Any] = {
        "slug": slug,
        "name": svc.get("name") or slug,
        "app": app.name,
        "selected": app.enabled,
        "off_in_source": not app.enabled,
        "fields": [],
        "env": {},
    }
    status = svc.get("status")
    if app.spec.get("unusable"):
        return {**row, "state": "unusable", "reason": str(app.spec["unusable"]), "selected": False}
    if status in UNDEPLOYABLE_STATUSES:
        return {**row, "state": "not_deployable", "reason": "This service is no longer available.", "selected": False}
    if not (svc.get("docker") or {}).get("image"):
        return {
            **row,
            "state": "not_deployable",
            "reason": "CashPilot tracks this service, but there is nothing to deploy for it.",
            "selected": False,
        }

    keys = list((app.spec.get("fields") or {}).keys())
    keys += [k for k, v in docker_env.items() if v.get("required") and not v.get("default") and k not in keys]
    states = []
    for key in keys:
        var = docker_env.get(key) or {"key": key}
        secret = bool(var.get("secret"))
        value = app.values.get(key)
        typed = extra.get(key)
        if isinstance(typed, str) and typed.strip():
            text, state = typed.strip(), "imported"
            if len(text.encode()) > MAX_VALUE_BYTES:
                text, state = None, "invalid"
        elif value is None:
            text, state = None, "missing"
        elif value.retype:
            text, state = None, "retype"
        elif is_placeholder(value.text or ""):
            text, state = None, "placeholder"
        else:
            text, state = value.text.strip(), "imported"
        if text is not None and field_problem(var, text):
            state = "invalid"
        entry: dict[str, Any] = {
            "key": key,
            "label": var.get("label") or key,
            "secret": secret,
            "required": bool(var.get("required")),
            "state": state,
            "pattern": var.get("pattern") or "",
        }
        if not secret and text is not None:
            entry["value"] = text
        row["fields"].append(entry)
        if state == "imported":
            row["env"][key] = text
        states.append((state, entry["required"]))

    if any(s == "invalid" for s, _ in states):
        row["state"], row["reason"] = "invalid", "A value does not have the format this service needs."
    elif any(s != "imported" and req for s, req in states):
        row["state"], row["reason"] = "missing_fields", "Fill in the fields marked below."
    else:
        row["state"], row["reason"] = "ready", ""
    if app.spec.get("note"):
        row["reason"] = str(app.spec["note"])
    elif row["state"] == "missing_fields" and app.spec.get("missing_note"):
        row["reason"] = str(app.spec["missing_note"])
    if row["off_in_source"] and row["state"] == "ready":
        row["reason"] = "Turned off in the old tool. Tick it to bring it over anyway."
    return row
