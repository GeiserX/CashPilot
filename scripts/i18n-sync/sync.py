#!/usr/bin/env python3
"""The nightly translation sync: carry English changes into the other 19 languages.

    sync.py [--repo NAME ...] [--base BRANCH --base-remote origin|amiga] [--dry-run] [--no-push]

For each CashPilot repo it fetches main, finds the translations whose English changed (the
source hash each surface stores) or that are missing, asks Claude (through `nd run`, model opus)
for only those entries, runs the repo's own checks, and opens one ready PR from the
Amigadelasmigas fork. It never merges. See README.md.

Standard library only. It imports scripts/i18n_check.py (the parity check every CashPilot repo
copies) for the parsers, the placeholder comparison and the source hash.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime
import difflib
import fcntl
import importlib.util
import json
import logging
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import xml.etree.ElementTree as ET

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import i18n_check as ic  # noqa: E402

ROOT = pathlib.Path(os.environ.get("I18N_SYNC_ROOT", "/Volumes/Data/scratch/i18n-sync"))
GLOSSARY = HERE.parents[1] / "i18n" / "glossary.yml"
AUTHOR = ("GeiserX", "9169332+GeiserX@users.noreply.github.com")
FORK = "Amigadelasmigas"
UPSTREAM = "GeiserX"
# A locale with more missing keys than this is a translation backlog, which a translation
# lane owns. The sync translates only what a few English edits leave behind.
MAX_MISSING = 40
BATCH = 40
WORKERS = 4

LANGUAGES = {
    "es": "Spanish (Spain and Latin America, neutral)",
    "pt-BR": "Brazilian Portuguese",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "nl": "Dutch",
    "pl": "Polish",
    "ru": "Russian",
    "uk": "Ukrainian",
    "tr": "Turkish",
    "ar": "Arabic (Modern Standard Arabic)",
    "hi": "Hindi",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "th": "Thai",
    "fil": "Filipino",
    "zh-Hans": "Simplified Chinese",
    "ja": "Japanese",
    "ko": "Korean",
}

ICU_RULES = """\
- `{name}` is a value the app fills in. Copy it exactly and never translate the word inside the braces.
  Move it where the grammar needs it. Use every placeholder of the English, and no other.
- `{n, plural, one {# box} other {# boxes}}` is a plural. Keep `n, plural,` and write one form for each
  CLDR plural category of the language, always with `other`. Keep `#` where the number goes. An exact
  form such as `=0 {...}` stays, with its text translated.
- `{kind, select, docker {...} other {...}}` is a choice. Keep the option names, translate each text.
- An apostrophe right before `{`, `}` or `#` is written twice (`''`). Elsewhere an apostrophe is plain text.
- Keep every HTML tag, attribute and link target exactly, and translate only the text between tags."""

SURFACE_RULES = {
    "json": ICU_RULES,
    "site": """\
- `{name}` is a value the site fills in. Copy it exactly, never translate the word inside the braces.
- Keep every HTML tag, attribute and link target exactly, and translate only the text between tags.""",
    "android": """\
- Each entry is one Android resource element (`<string>`, `<plurals>` or `<string-array>`). Answer with
  the whole element: the same tag, the same name attribute, the same layout, with only the text translated.
- Keep every placeholder (`%1$s`, `%1$d`, `%%`) with its number. The order in the sentence can change.
- Android escaping: an apostrophe is `\\'`, a double quote is `\\"`, `&` is `&amp;`, `<` is `&lt;`.
- A `<plurals>` element has one `<item quantity="...">` for each CLDR plural category of the language,
  always with `other`.
- Keep `https://`, `http://`, 192.168.x.x, 10.x.x.x, `.local` and `.lan` as written.""",
    "textdir": """\
- Each entry is one Google Play listing text file. title.txt has at most 30 characters,
  short_description.txt at most 80, full_description.txt at most 4000. Plain text, no Markdown.
- Keep URLs exactly.""",
}

COMMON_RULES = """\
- Copy unchanged: text in backticks, URLs, commands, file names, environment variables (`CASHPILOT_...`),
  version numbers, units, and product and provider names (CashPilot, Docker, Honeygain, Mysterium, Storj,
  Tailscale, Unraid...).
- The same facts as the English: nothing added, nothing dropped, every number, condition and warning kept.
- Referral and disclosure lines: translate them faithfully and completely; never soften or drop one.
- Use the glossary's word for every glossary term, inflected as the sentence needs. "health" and
  "status" are two different things and never get the same word.
- One English UI label gets one translation everywhere: match the existing translations shown below."""


@dataclasses.dataclass
class Surface:
    name: str
    fmt: str  # json | android | textdir | docs
    about: str
    source: str = ""
    targets: str = ""
    hashes_dir: str | None = None
    ignore: tuple[str, ...] = ()
    rules: str = ""

    def rules_text(self) -> str:
        return SURFACE_RULES[self.rules or self.fmt]


REPOS: dict[str, dict] = {
    "CashPilot": {
        "surfaces": [
            Surface(
                "web UI",
                "json",
                "the web UI of CashPilot, a self-hosted app that runs passive-income earner containers",
                "app/i18n/en.json",
                "app/i18n/*.json",
            ),
            Surface("docs", "docs", "a page of the CashPilot documentation site (Markdown, built with Zensical)"),
        ],
        "checks": ["python3 -I .github/scripts/docs-i18n.py check", "node scripts/i18n_format_check.mjs"],
    },
    "CashPilot-Desktop": {
        "surfaces": [
            Surface(
                "Desktop",
                "json",
                "CashPilot Desktop, the desktop app that runs CashPilot's earners on the user's computer",
                "frontend/src/locales/en.json",
                "frontend/src/locales/*.json",
                "i18n/source-hashes",
            ),
        ],
        "checks": ["go test ./internal/i18n/"],
    },
    "CashPilot-android": {
        "surfaces": [
            Surface(
                "Android app",
                "android",
                "the CashPilot Android app, which shows the user's CashPilot server and earners on the phone",
                "app/src/main/res/values/strings.xml",
                "app/src/main/res/values-*/strings.xml",
                "i18n/source-hashes",
            ),
            Surface(
                "Play listing",
                "textdir",
                "the Google Play store listing of the CashPilot Android app",
                "fastlane/metadata/android/en-US",
                "fastlane/metadata/android/*",
                "i18n/fastlane-hashes",
                ("changelogs/*",),
            ),
        ],
        "checks": [
            "python3 scripts/i18n_check.py app/src/main/res/values/strings.xml app/src/main/res/values-*/strings.xml"
            " --hashes-dir i18n/source-hashes",
            "python3 scripts/i18n_check.py fastlane/metadata/android/en-US fastlane/metadata/android/*/"
            " --hashes-dir i18n/fastlane-hashes --ignore 'changelogs/*'",
        ],
    },
    "CashPilot-web": {
        "surfaces": [
            Surface(
                "website",
                "json",
                "cashpilot.club, the CashPilot website",
                "src/i18n/en.json",
                "src/i18n/*.json",
                "i18n/source-hashes",
                rules="site",
            ),
        ],
        "checks": ["bun run i18n:check --strict --all"],
    },
}

log = logging.getLogger("i18n-sync")


class Refused(Exception):
    """The repo is left alone: its checks fail, or the work could not be made safe."""


# ---------------------------------------------------------------------------
# Shell helpers


def sh(cmd: list[str] | str, cwd: pathlib.Path, check: bool = True, **kw) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True, **kw)
    if check and p.returncode != 0:
        raise RuntimeError(f"{cmd!r} failed ({p.returncode}): {(p.stderr or p.stdout).strip()[-800:]}")
    return p


def git(clone: pathlib.Path, *args: str, amiga: bool = False, check: bool = True) -> str:
    base = ["git-amiga"] if amiga else ["git"]
    cmd = [*base, "-c", "core.hooksPath=/dev/null", *args]
    # The network calls get three tries: a timeout at night should not cost a day.
    for attempt in range(3 if args[0] in ("fetch", "push", "ls-remote") else 1):
        try:
            return sh(cmd, clone, check=check).stdout
        except RuntimeError as e:
            if attempt == 2 or args[0] not in ("fetch", "push", "ls-remote"):
                raise
            log.warning("%s; trying again in 30 s", e)
            time.sleep(30)
    raise AssertionError("unreachable")


# ---------------------------------------------------------------------------
# The glossary


def glossary_for(locale: str) -> str:
    data = ic.parse_yaml(GLOSSARY.read_text(encoding="utf-8"))
    lines = [f"Register (how to address the user): {data['register'].get(locale, '')}"]
    for term in data["terms"].values():
        word = term.get(locale)
        if word:
            note = term.get("note", "")
            lines.append(f"- {term['en']} -> {word} ({term.get('kind', 'term')}; {note})")
    return "\n".join(lines)


def lang_code(locale: str) -> str | None:
    """The glossary locale of a file's locale (de-DE -> de, zh-CN -> zh-Hans)."""
    if locale in LANGUAGES:
        return locale
    if locale.lower().startswith("zh"):
        return "zh-Hans"
    base = locale.split("-")[0]
    return base if base in LANGUAGES else None


# ---------------------------------------------------------------------------
# Claude, through nd


class Claude:
    def __init__(self) -> None:
        fixed = os.environ.get("I18N_SYNC_ACCOUNTS")
        if fixed:
            self.accounts = [a for a in fixed.split(",") if a]
        else:
            out = sh(["nd", "pick", "--json", "--provider", "claude"], ROOT).stdout
            self.accounts = [c["id"] for c in json.loads(out)["candidates"] if c["id"].startswith("cc-")]
        self.accounts = list(dict.fromkeys(self.accounts))  # each account once, so ask() can try them all
        if not self.accounts:
            raise RuntimeError("nd pick found no Claude account to run on")
        self.at = 0
        self.lock = threading.Lock()
        self.cwd = ROOT / "claude-cwd"  # an empty folder: no CLAUDE.md, no project settings
        self.cwd.mkdir(parents=True, exist_ok=True)

    def ask(self, prompt: str, schema: dict, timeout: int) -> dict:
        tried: set[str] = set()  # per call, so another worker moving the cursor never skips an account
        while len(tried) < len(self.accounts):
            with self.lock:
                start = self.at % len(self.accounts)
            order = self.accounts[start:] + self.accounts[:start]
            acct = next(a for a in order if a not in tried)
            cmd = ["nd", "run", acct, "--", "claude", "-p", "--model", "opus", "--tools", ""]
            cmd += ["--strict-mcp-config", "--setting-sources", "", "--no-session-persistence"]
            cmd += ["--output-format", "json", "--json-schema", json.dumps(schema)]
            try:
                p = subprocess.run(cmd, cwd=self.cwd, input=prompt, capture_output=True, text=True, timeout=timeout)
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(f"claude on {acct} took longer than {timeout} s") from e
            try:
                res = json.loads(p.stdout.strip().splitlines()[-1])
            except (json.JSONDecodeError, IndexError):
                res = {"is_error": True, "result": (p.stderr or p.stdout)[-400:]}
            if not res.get("is_error") and isinstance(res.get("structured_output"), dict):
                return res["structured_output"]
            why = str(res.get("result") or "")
            if res.get("api_error_status") in (401, 403, 429) or re.search(
                r"rate.?limit|usage limit|revoked|authenticat|log in|overloaded|quota", why, re.I
            ):
                log.warning("account %s cannot run (%s): trying the next one", acct, why[:160])
                with self.lock:
                    if self.accounts[self.at % len(self.accounts)] == acct:
                        self.at += 1
                tried.add(acct)
                continue
            raise RuntimeError(f"claude on {acct} failed: {why[:400]}")
        raise RuntimeError(f"no Claude account could run (tried {', '.join(self.accounts)})")


KEYS_SCHEMA = {
    "type": "object",
    "properties": {"translations": {"type": "object", "additionalProperties": {"type": "string"}}},
    "required": ["translations"],
}
PAGE_SCHEMA = {"type": "object", "properties": {"body": {"type": "string"}}, "required": ["body"]}


def keys_prompt(surface: Surface, code: str, entries: list[dict], context: list[dict], errors: dict) -> str:
    fix = ""
    if errors:
        fix = "\n\nYour last answer for these keys failed the check. Fix exactly this:\n" + "\n".join(
            f"- {k}: {v}" for k, v in errors.items()
        )
    return f"""You keep the {LANGUAGES[code]} translation (locale `{code}`) of {surface.about} up to date.
The English source changed. For each entry below, write the {LANGUAGES[code]} text that says what "en" says now.

- "current" is the translation we have now. Keep its wording where the English did not change, and change
  only what the English change needs.
- "old_en", when present, is the English that "current" was translated from. Compare it with "en" to see
  what changed.
- An entry without "current" is new: translate it.

Message format (a check refuses any answer that breaks these):
{surface.rules_text()}

Style:
{COMMON_RULES}
- Plain, natural {LANGUAGES[code]} that a native user of a technical app expects. Buttons, menu entries and
  headings stay short.

Glossary for {code}:
{glossary_for(code)}

Existing translations of nearby strings, for consistent wording (do not change them):
{json.dumps(context, ensure_ascii=False, indent=1)}

Entries to write:
{json.dumps(entries, ensure_ascii=False, indent=1)}{fix}

Answer with {{"translations": {{"<key>": "<text>"}}}}, one entry for every key above and nothing else."""


# ---------------------------------------------------------------------------
# Keyed surfaces (json, android, textdir)


@dataclasses.dataclass
class Target:
    path: pathlib.Path
    locale: str
    code: str
    entries: dict
    hashes: dict | None
    sidecar: pathlib.Path | None


def load_surface(clone: pathlib.Path, s: Surface) -> tuple[dict, list[Target]]:
    src_path = clone / s.source
    if not src_path.exists():
        return {}, []
    source = ic._drop_ignored(ic.load(src_path, s.fmt, False)[0], list(s.ignore))
    targets = []
    for path in sorted(clone.glob(s.targets)):
        if path.resolve() == src_path.resolve() or (s.fmt == "textdir") != path.is_dir():
            continue
        locale = ic.locale_of(path, s.fmt)
        code = lang_code(locale)
        if code is None:
            continue
        entries, inline = ic.load(path, s.fmt, False)
        entries = ic._drop_ignored(entries, list(s.ignore))
        sidecar = clone / s.hashes_dir / f"{locale}.json" if s.hashes_dir else None
        hashes = ic._load_sidecar(sidecar) if sidecar else inline
        targets.append(Target(path, locale, code, entries, hashes, sidecar))
    return source, targets


def gate(clone: pathlib.Path, s: Surface) -> list[str]:
    """Placeholder and parse errors of a surface. Staleness and gaps are never errors here."""
    try:
        source, targets = load_surface(clone, s)
    except (ic.ParseError, OSError, ValueError) as e:
        return [f"{s.name}: {e}"]
    out = []
    for t in targets:
        for key, detail in ic.check_target(source, t.entries, t.hashes)["placeholder"]:
            out.append(f"{t.path.relative_to(clone)}: {key}: {detail}")
    return out


def old_english(clone: pathlib.Path, s: Surface, wanted: dict[str, str]) -> dict[str, object]:
    """The English each stale translation was made from, found in the source file's history by its hash."""
    found: dict[str, object] = {}
    if s.fmt == "textdir" or not wanted:
        return found
    commits = git(clone, "log", "-n", "80", "--format=%H", "--", s.source).split()
    with tempfile.TemporaryDirectory() as tmp:
        for c in commits:
            p = git(clone, "show", f"{c}:{s.source}", check=False)
            f = pathlib.Path(tmp) / pathlib.Path(s.source).name
            f.write_text(p, encoding="utf-8")
            try:
                entries = ic.load(f, s.fmt, False)[0]
            except (ic.ParseError, ValueError):
                continue
            for key, h in wanted.items():
                if key not in found and key in entries and ic.source_hash(entries[key]) == h:
                    found[key] = entries[key]
            if len(found) == len(wanted):
                break
    return found


ANDROID_ELEM = r'(?ms)^([ \t]*)<(string|plurals|string-array)\b[^>]*\bname=(["\']){name}\3[^>]*>.*?</\2>[ \t]*\n'


def android_element(text: str, name: str) -> tuple[str, str] | None:
    m = re.search(ANDROID_ELEM.format(name=re.escape(name)), text)
    return (m.group(1), textwrap.dedent(m.group(0)).strip()) if m else None


def base_name(key: str) -> str:
    return key.split("[", 1)[0]


def json_paths(node: dict, segs: tuple = (), out: dict | None = None) -> dict[str, tuple]:
    out = {} if out is None else out
    for k, v in node.items():
        p = (*segs, k)
        if isinstance(v, dict) and not ic._is_inline(v):
            json_paths(v, p, out)
        else:
            out[".".join(p)] = p
    return out


def json_root(path: pathlib.Path) -> tuple[dict, dict]:
    tree = json.loads(path.read_text(encoding="utf-8"))
    return tree, ic._drop_locale_root(tree, ic.locale_of(path, "json"))


def json_put(root: dict, en_root: dict, path: tuple, value) -> None:
    """Set one leaf, creating the objects on its path in the English order."""
    node, en = root, en_root
    for seg in path[:-1]:
        if not isinstance(node.get(seg), dict) or ic._is_inline(node[seg]):
            json_insert(node, list(en) if isinstance(en, dict) else [], seg, {})
        node = node[seg]
        en = en.get(seg, {}) if isinstance(en, dict) else {}
    if path[-1] in node:
        node[path[-1]] = value
    else:
        json_insert(node, list(en) if isinstance(en, dict) else [], path[-1], value)


def json_insert(node: dict, order: list, key: str, value) -> None:
    """Insert key after the nearest English sibling before it that the target has."""
    idx = order.index(key) if key in order else len(order)
    prev = next((k for k in reversed(order[:idx]) if k in node), None)
    items = list(node.items())
    node.clear()
    if prev is None and items and key in order:
        node[key] = value
    for k, v in items:
        node[k] = v
        if k == prev:
            node[key] = value
    if key not in node:
        node[key] = value


def json_delete(root: dict, path: tuple) -> None:
    chain = [root]
    for seg in path[:-1]:
        chain.append(chain[-1][seg])
    del chain[-1][path[-1]]
    for depth in range(len(path) - 1, 0, -1):
        if not chain[depth]:
            del chain[depth - 1][path[depth - 1]]


PLAY_LIMITS = {"title.txt": 30, "short_description.txt": 80, "full_description.txt": 4000}


def check_one(s: Surface, source: dict, key_values: dict) -> dict[str, str]:
    """Placeholder or emptiness errors of new values, by key."""
    src = {k: source[k] for k in key_values}
    found = ic.check_target(src, key_values, None)
    errors = {k: d or "empty" for kind in ("missing", "placeholder") for k, d in found[kind]}
    if s.fmt == "textdir":  # Google Play's limits
        for k, v in key_values.items():
            limit = PLAY_LIMITS.get(pathlib.PurePath(k).name)
            if limit and len(v.strip()) > limit and k not in errors:
                errors[k] = f"{len(v.strip())} characters; Google Play allows {limit}"
    return errors


def parse_android(xml: str, name: str, root_tag: str) -> tuple[dict, str | None]:
    """The entries of one translated Android element, or an error."""
    try:
        wrapped = ET.fromstring(f"{root_tag}{xml}</resources>")
    except ET.ParseError as e:
        return {}, f"not valid XML: {e}"
    elems = list(wrapped)
    if len(elems) != 1 or elems[0].get("name") != name:
        return {}, f'answer with exactly one element named "{name}"'
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8") as f:
        f.write(f'<?xml version="1.0" encoding="utf-8"?>\n{root_tag}{xml}</resources>\n')
    try:
        return ic.load_android(pathlib.Path(f.name)), None
    finally:
        os.unlink(f.name)


@dataclasses.dataclass
class Work:
    surface: Surface
    target: Target
    keys: list[str]  # stale and missing keys to translate
    stale: list[str]
    extra: list[str]
    unstamped: list[str]
    result: dict = dataclasses.field(default_factory=dict)  # key -> value to write
    failed: dict = dataclasses.field(default_factory=dict)  # key -> why it stays as it was


def plan_surface(clone: pathlib.Path, s: Surface) -> list[Work]:
    source, targets = load_surface(clone, s)
    work, backlog = [], {}
    for t in targets:
        found = ic.check_target(source, t.entries, t.hashes)
        stale = [k for k, _ in found["stale"]]
        missing = [k for k, _ in found["missing"]]
        extra = [k for k, _ in found["extra"]]
        # A translated key with no hash was written by hand against today's English: record its hash.
        unstamped = [k for k, _ in found["unstamped"]]
        if len(missing) > MAX_MISSING:
            backlog[t.locale] = len(missing)
            missing = []
        keys = stale + missing
        if s.fmt == "android":  # one answer per element: a string-array is translated whole
            keys = list(dict.fromkeys(base_name(k) for k in keys))
            en_names = {base_name(k) for k in source}
            extra = list(dict.fromkeys(base_name(k) for k in extra if base_name(k) not in en_names))
        if keys or extra or unstamped:
            work.append(Work(s, t, keys, stale, extra, unstamped))
    if backlog:
        log.info(
            "%s: never-translated keys, a backlog for a translation lane, left as they are: %s",
            s.name,
            ", ".join(f"{loc} {n}" for loc, n in sorted(backlog.items())),
        )
    return work


def translate_work(clone: pathlib.Path, w: Work, claude: Claude) -> None:
    s, t = w.surface, w.target
    source = ic._drop_ignored(ic.load(clone / s.source, s.fmt, False)[0], list(s.ignore))
    en_order = list(source)
    wanted = {k: t.hashes[k] for k in w.stale if t.hashes and t.hashes.get(k)}
    old = old_english(clone, s, wanted)
    en_text = (clone / s.source).read_text(encoding="utf-8") if s.fmt == "android" else ""
    tgt_text = t.path.read_text(encoding="utf-8") if s.fmt == "android" else ""
    root_tag = re.search(r"<resources\b[^>]*>", en_text).group(0) if s.fmt == "android" else ""

    def entry(key: str) -> dict:
        if s.fmt == "android":
            e = {"key": key, "en": android_element(en_text, key)[1]}
            cur = android_element(tgt_text, key)
            if cur:
                e["current"] = cur[1]
            if key in old:
                e["old_en"] = old[key]
            return e
        e = {"key": key, "en": source[key]}
        if key in t.entries and not ic.is_empty(t.entries[key]):
            e["current"] = t.entries[key]
        if key in old:
            e["old_en"] = old[key]
        return e

    def context(keys: list[str]) -> list[dict]:
        fresh = {
            k
            for k in t.entries
            if k in source and k not in w.stale and (not t.hashes or t.hashes.get(k) == ic.source_hash(source[k]))
        }
        picked: list[str] = []
        for key in keys:
            base = next((i for i, k in enumerate(en_order) if base_name(k) == key or k == key), 0)
            for k in en_order[max(0, base - 4) : base + 5]:
                if k in fresh and k not in picked and base_name(k) not in keys:
                    picked.append(k)
        return [{"en": source[k], "translation": t.entries[k]} for k in picked[:40]]

    def validate(key: str, text: str) -> str | None:
        if s.fmt == "android":
            values, err = parse_android(text.strip(), key, root_tag)
            if err is not None:
                return err
            want = [k for k in source if base_name(k) == key]
            if set(values) != set(want):  # an extra or a missing array item, or another element's keys
                return f"the element must hold exactly {', '.join(want)}"
            bad = check_one(s, source, values)
            return "; ".join(f"{k}: {d}" for k, d in bad.items()) or None
        return check_one(s, source, {key: text}).get(key)

    todo = list(w.keys)
    errors: dict[str, str] = {}
    for attempt in range(2):
        if not todo:
            break
        last, errors = errors, {}
        for i in range(0, len(todo), BATCH):
            chunk = todo[i : i + BATCH]
            prompt = keys_prompt(s, t.code, [entry(k) for k in chunk], context(chunk), last)
            try:
                reply = claude.ask(prompt, KEYS_SCHEMA, 900)["translations"]
            except Exception as e:  # this batch stays for the retry; the batches before it are kept
                errors.update({k: f"no answer: {str(e)[:200]}" for k in chunk})
                continue
            for key in chunk:  # only the keys this batch asked for
                text = reply.get(key)
                err = "no answer for this key" if text is None else validate(key, text)
                if err is None:
                    w.result[key] = text.strip() if s.fmt == "android" else text
                else:
                    errors[key] = err
        todo = list(errors)
        if errors and attempt == 0:
            log.info("%s %s: %d entries have no valid answer yet, asking once more", s.name, t.locale, len(errors))
    w.failed = errors
    for key, why in errors.items():
        log.warning("%s %s: %s stays as it was: %s", s.name, t.locale, key, why)


def write_work(clone: pathlib.Path, w: Work) -> set[pathlib.Path]:
    """Write a locale's translations and hashes. Returns the files it changed."""
    s, t = w.surface, w.target
    source = ic._drop_ignored(ic.load(clone / s.source, s.fmt, False)[0], list(s.ignore))
    hashes = dict(t.hashes or {})
    for key in w.unstamped:
        hashes[key] = ic.source_hash(source[key])
    changed: set[pathlib.Path] = set()
    if s.fmt == "json":
        tree, root = json_root(t.path)
        _, en_root = json_root(clone / s.source)
        en_paths = json_paths(en_root)
        tgt_paths = json_paths(root)
        inline = t.sidecar is None
        # Removed keys go first: English may have turned a leaf "notice" into "notice.title".
        for key in w.extra:
            if key in tgt_paths:
                json_delete(root, tgt_paths[key])
            hashes.pop(key, None)
        for key in w.unstamped if inline else ():
            json_put(root, en_root, tgt_paths[key], {"text": t.entries[key], "source": hashes[key]})
        for key, text in w.result.items():
            h = ic.source_hash(source[key])
            json_put(root, en_root, en_paths[key], {"text": text, "source": h} if inline else text)
            hashes[key] = h
        new = json.dumps(tree, ensure_ascii=False, indent=2) + "\n"
        if new != t.path.read_text(encoding="utf-8"):
            t.path.write_text(new, encoding="utf-8")
            changed.add(t.path)
    elif s.fmt == "android":
        text = t.path.read_text(encoding="utf-8")
        en_names = list(dict.fromkeys(base_name(k) for k in source))
        for name in w.extra:
            text = re.sub(ANDROID_ELEM.format(name=re.escape(name)), "", text)
            for key in [k for k in hashes if base_name(k) == name]:
                hashes.pop(key)
        for name, xml in w.result.items():
            cur = android_element(text, name)
            indent = cur[0] if cur else "    "
            block = textwrap.indent(xml, indent) + "\n"
            m = re.search(ANDROID_ELEM.format(name=re.escape(name)), text)
            if m:
                text = text[: m.start()] + block + text[m.end() :]
            else:
                idx = en_names.index(name)
                prev = next((n for n in reversed(en_names[:idx]) if android_element(text, n)), None)
                pm = re.search(ANDROID_ELEM.format(name=re.escape(prev)), text) if prev else None
                at = pm.end() if pm else text.rindex("</resources>")
                text = text[:at] + block + text[at:]
            for key in (k for k in source if base_name(k) == name):
                hashes[key] = ic.source_hash(source[key])
        if text != t.path.read_text(encoding="utf-8"):
            t.path.write_text(text, encoding="utf-8")
            changed.add(t.path)
    elif s.fmt == "textdir":
        for key, value in w.result.items():
            f = t.path / key
            ending = "\n" if (clone / s.source / key).read_text(encoding="utf-8").endswith("\n") else ""
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(value.strip() + ending, encoding="utf-8")
            changed.add(f)
            hashes[key] = ic.source_hash(source[key])
        for key in w.extra:
            (t.path / key).unlink(missing_ok=True)
            hashes.pop(key, None)
            changed.add(t.path / key)
    if t.sidecar is not None and hashes != (t.hashes or {}):
        t.sidecar.parent.mkdir(parents=True, exist_ok=True)
        t.sidecar.write_text(json.dumps(hashes, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        changed.add(t.sidecar)
    return changed


# ---------------------------------------------------------------------------
# The docs site


def docs_module(clone: pathlib.Path):
    spec = importlib.util.spec_from_file_location("docs_i18n", clone / ".github/scripts/docs-i18n.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def docs_check(clone: pathlib.Path) -> tuple[list[str], dict[str, list[str]], str]:
    p = sh([sys.executable, "-I", ".github/scripts/docs-i18n.py", "check"], clone, check=False)
    if p.returncode not in (0, 1) or "docs-i18n check:" not in p.stdout:  # a crash, never "no findings"
        raise RuntimeError(f"docs-i18n.py check crashed ({p.returncode}): {(p.stderr or p.stdout).strip()[-600:]}")
    stale = re.findall(r"^STALE (docs/i18n/\S+\.md):", p.stdout, re.M)
    errors: dict[str, list[str]] = {}
    for m in re.finditer(r"^ERROR (\S+?):? (.*)$", p.stdout, re.M):
        errors.setdefault(m.group(1).rstrip(":"), []).append(m.group(2))
    return stale, errors, p.stdout


def page_prompt(code: str, en_body: str, old_body: str | None, current: str, ids: list[str], errors: list[str]) -> str:
    diff = ""
    if old_body is not None:
        diff = "".join(
            difflib.unified_diff(
                old_body.splitlines(True), en_body.splitlines(True), "english-before", "english-now", n=2
            )
        )
        diff = f"\nWhat changed in the English page since the translation was made:\n```diff\n{diff}```\n"
    fix = ""
    if errors:
        fix = "\nYour last answer failed the docs check. Fix exactly this:\n" + "\n".join(f"- {e}" for e in errors)
    return f"""You keep the {LANGUAGES[code]} translation (locale `{code}`) of a page of the CashPilot documentation
site up to date. The English page changed. Update the translation so it says what the English page says now.
Keep the current translation's wording wherever the English did not change; change only what the English
change needs.
{diff}
Rules (the docs check refuses a page that breaks them):
- Keep every fenced code block, every inline code span and every link target (URL or path) byte for byte.
  Referral links stay exactly as they are.
- Keep the Markdown structure: headings, lists, tables, admonitions (`!!! note ""` and their indentation),
  HTML tags and attributes, and comments such as `<!-- n:services -->12<!-- /n -->`.
- Every heading keeps the English heading id with `{{ #id }}` at its end, as the current translation does.
  The English page's heading ids, in order: {json.dumps(ids)}
{COMMON_RULES}

Glossary for {code}:
{glossary_for(code)}

The English page now (body only, no front matter):
```markdown
{en_body}```

The current {code} translation (body only):
```markdown
{current}```
{fix}
Answer with {{"body": "<the whole updated {code} page body>"}}: no front matter, no code fence around it."""


@dataclasses.dataclass
class PageWork:
    code: str
    rel: str
    path: pathlib.Path
    original: str
    new: str = ""
    failed: str = ""


def plan_docs(clone: pathlib.Path) -> list[PageWork]:
    stale, _, _ = docs_check(clone)
    out = []
    for where in stale:
        _, _, code, rel = where.split("/", 3)
        path = clone / where
        out.append(PageWork(code, rel, path, path.read_text(encoding="utf-8")))
    return out


def translate_page(clone: pathlib.Path, pw: PageWork, claude: Claude, errors: list[str]) -> None:
    mod = docs_module(clone)
    en = (clone / "docs" / pw.rel).read_text(encoding="utf-8")
    en_body = mod.split_front(en)[1]
    front, current = mod.split_front(pw.original)
    stored = mod.HASH_LINE.search(front).group(1)
    old_body = None
    for c in git(clone, "log", "-n", "200", "--format=%H", "--", f"docs/{pw.rel}").split():
        text = git(clone, "show", f"{c}:docs/{pw.rel}", check=False)
        if text and mod.source_hash(text) == stored:
            old_body = mod.split_front(text)[1]
            break
    ids = mod.heading_ids_md(en_body) or []
    code = lang_code(pw.code) or pw.code
    body = claude.ask(page_prompt(code, en_body, old_body, current, ids, errors), PAGE_SCHEMA, 1800)["body"]
    body = body.strip("\n") + "\n"
    m = mod.HASH_LINE.search(front)
    new_front = front[: m.start(1)] + mod.source_hash(en) + front[m.end(1) :]
    pw.new = f"---\n{new_front}---\n\n{body}" if current.startswith("\n") else f"---\n{new_front}---\n{body}"


def sync_docs(clone: pathlib.Path, pages: list[PageWork], claude: Claude) -> set[pathlib.Path]:
    def rel(pw: PageWork) -> str:
        return pw.path.relative_to(clone).as_posix()

    errors: dict[str, list[str]] = {}
    todo = list(pages)
    for attempt in range(2):
        with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
            futs = {pool.submit(translate_page, clone, pw, claude, errors.get(rel(pw), [])): pw for pw in todo}
            for f in concurrent.futures.as_completed(futs):
                pw = futs[f]
                try:
                    f.result()
                    pw.path.write_text(pw.new, encoding="utf-8")
                    pw.failed = ""
                except Exception as e:  # one page failing leaves that page stale, never the run broken
                    pw.failed = f"no answer: {str(e)[:200]}"
                    log.warning("docs %s %s: %s", pw.code, pw.rel, e)
        _, errors, _ = docs_check(clone)
        todo = [pw for pw in pages if pw.failed or rel(pw) in errors]
        if not todo:
            break
        if attempt == 0:
            log.info("docs: %d pages have no valid answer yet, asking once more", len(todo))
    for pw in todo:  # no valid answer after the retry: put the stale page back as it was
        pw.failed = pw.failed or "; ".join(errors.get(rel(pw), []))[:300]
        pw.new = ""
        pw.path.write_text(pw.original, encoding="utf-8")
        log.warning("docs %s %s stays stale: %s", pw.code, pw.rel, pw.failed)
    return {pw.path for pw in pages if pw.new and not pw.failed}


# ---------------------------------------------------------------------------
# One repo


def run_checks(clone: pathlib.Path, repo: str) -> list[str]:
    failures = []
    for s in REPOS[repo]["surfaces"]:
        if s.fmt != "docs":
            failures += [f"placeholder: {e}" for e in gate(clone, s)]
    for cmd in REPOS[repo]["checks"]:
        p = sh(cmd, clone, check=False)
        if p.returncode != 0:
            tail = "\n".join((p.stdout + p.stderr).strip().splitlines()[-12:])
            failures.append(f"`{cmd}` exited {p.returncode}:\n{tail}")
    return failures


def open_sync_pr(repo: str) -> str | None:
    out = sh(
        ["gh-amiga", "pr", "list", "--repo", f"{UPSTREAM}/{repo}", "--state", "open", "--author", FORK]
        + ["--json", "url,headRefName"],
        ROOT,
    ).stdout
    return next((p["url"] for p in json.loads(out) if p["headRefName"].startswith("i18n-sync/")), None)


def prepare(repo: str, base: str, remote: str) -> pathlib.Path:
    clone = ROOT / "repos" / repo
    if not clone.exists():
        clone.parent.mkdir(parents=True, exist_ok=True)
        sh(["git", "clone", "-q", f"https://github.com/{UPSTREAM}/{repo}.git", str(clone)], ROOT)
    if "amiga" not in git(clone, "remote").split():  # run.sh clones CashPilot with origin only
        git(clone, "remote", "add", "amiga", f"https://github.com/{FORK}/{repo}.git")
    git(clone, "fetch", "-q", "origin", "main")
    if remote == "amiga":
        git(clone, "fetch", "-q", "amiga", base, amiga=True)
    else:
        git(clone, "fetch", "-q", "origin", base)
    git(clone, "checkout", "-q", "-f", "--detach", "FETCH_HEAD")
    git(clone, "clean", "-fdq")
    return clone


def sync_repo(repo: str, args, claude_box: list) -> str:
    if not args.no_push and not args.dry_run:
        url = open_sync_pr(repo)
        if url:
            return f"skipped: the last sync PR is still open ({url}); it runs again once that one is merged or closed"
    clone = prepare(repo, args.base, args.base_remote)
    head = git(clone, "rev-parse", "--short", "HEAD").strip()
    log.info("%s: %s %s at %s", repo, args.base_remote, args.base, head)
    failures = run_checks(clone, repo)
    if failures:
        raise Refused(
            f"checks fail on {args.base} ({head}) before any change, so nothing was translated:\n" + "\n".join(failures)
        )

    surfaces = REPOS[repo]["surfaces"]
    work = [w for s in surfaces if s.fmt != "docs" for w in plan_surface(clone, s)]
    pages = plan_docs(clone) if any(s.fmt == "docs" for s in surfaces) else []
    if not work and not pages:
        return "nothing to translate"
    for w in work:
        log.info(
            "%s %s: %d to translate, %d removed in English, %d hashes to record",
            w.surface.name,
            w.target.locale,
            len(w.keys),
            len(w.extra),
            len(w.unstamped),
        )
    for pw in pages:
        log.info("docs %s: %s is stale", pw.code, pw.rel)
    if args.dry_run:
        return f"dry run: {sum(len(w.keys) for w in work)} entries and {len(pages)} pages would be translated"

    if not claude_box:
        claude_box.append(Claude())
    claude = claude_box[0]
    with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
        futs = {pool.submit(translate_work, clone, w, claude): w for w in work if w.keys}
        for f in concurrent.futures.as_completed(futs):
            w = futs[f]
            try:
                f.result()
            except Exception as e:
                w.failed = {k: str(e)[:200] for k in w.keys if k not in w.result}
                log.warning("%s %s: %s", w.surface.name, w.target.locale, e)
    changed: set[pathlib.Path] = set()
    for w in work:
        changed |= write_work(clone, w)
    if pages:
        changed |= sync_docs(clone, pages, claude)
    if not changed:
        return "nothing written: every answer failed the check (see the warnings above)"

    branch = f"i18n-sync/{datetime.datetime.now():%Y-%m-%d}"
    if (
        git(clone, "ls-remote", "amiga", f"refs/heads/{branch}", amiga=True).strip()
        or git(clone, "branch", "--list", branch).strip()
    ):
        branch += f"-{datetime.datetime.now():%H%M}"
    git(clone, "switch", "-q", "-c", branch)
    git(clone, "add", "--", *sorted(str(p.relative_to(clone)) for p in changed))
    title, body = pr_text(repo, work, pages, args.base)
    git(clone, "-c", f"user.name={AUTHOR[0]}", "-c", f"user.email={AUTHOR[1]}", "commit", "-q", "-m", title)
    failures = run_checks(clone, repo)
    if failures:
        raise Refused(f"checks fail after translating, so {branch} stays unpushed in {clone}:\n" + "\n".join(failures))
    if args.no_push:
        return f"committed on {branch} in {clone}, not pushed (--no-push)"
    git(clone, "push", "-q", "amiga", f"HEAD:refs/heads/{branch}", amiga=True)
    body_file = ROOT / "logs" / f"pr-{repo}-{branch.replace('/', '_')}.md"
    body_file.write_text(body, encoding="utf-8")
    create = ["gh-amiga", "pr", "create", "--repo", f"{UPSTREAM}/{repo}", "--base", "main"]
    create += ["--head", f"{FORK}:{branch}", "--title", title, "--body-file", str(body_file)]
    try:
        url = sh(create, clone).stdout.strip()
    except RuntimeError as e:
        raise Refused(f"pushed {FORK}:{branch}, but opening the PR failed: {e}. Open it by hand: {' '.join(create)}")
    return f"opened {url}"


def pr_text(repo: str, work: list[Work], pages: list[PageWork], base: str = "main") -> tuple[str, str]:
    locales = {w.target.code for w in work if w.result or w.extra}
    locales |= {pw.code for pw in pages if pw.new and not pw.failed}
    n = len(locales)
    if n:
        title = f"fix(i18n): update {n} language{'s' if n != 1 else ''} to the changed English, so none shows old text"
    else:
        title = "fix(i18n): record the source hash of translations added by hand, so their next English change is seen"
    checks = ["the placeholder check of every locale file (`scripts/i18n_check.py`)"]
    checks += [f"`{c}`" for c in REPOS[repo]["checks"]]
    lines = [
        "Some English strings changed. Their translations still said the old thing, or did not exist for a"
        " new string, so those languages showed old text or English.",
        "",
        "This PR translates only those strings. The nightly translation sync on MacMini wrote it"
        " (`scripts/i18n-sync/` in GeiserX/CashPilot). It used Claude (opus), the glossary in"
        " `i18n/glossary.yml` of GeiserX/CashPilot, and the translations we already have. A person merges it.",
        "",
        *(
            [f"This run translated the fork's branch `{base}`, so the PR also carries that branch's commits.", ""]
            if base != "main"
            else []
        ),
        "These checks passed on this branch before the PR opened:",
        "",
        *[f"- {c}" for c in checks],
        "",
        "Keys changed per locale:",
        "",
    ]
    by_surface: dict[str, list[Work]] = {}
    for w in work:
        by_surface.setdefault(w.surface.name, []).append(w)
    for name, ws in by_surface.items():
        rows = [w for w in ws if w.result or w.extra or w.unstamped]
        if not rows:
            continue
        lines += [f"### {name}", "", "| Locale | Translated | Removed with the English | Hash recorded |"]
        lines.append("|---|---|---|---|")
        for w in sorted(rows, key=lambda w: w.target.locale):
            cells = [", ".join(f"`{k}`" for k in sorted(ks)) or "none" for ks in (w.result, w.extra, w.unstamped)]
            lines.append(f"| {w.target.locale} | {' | '.join(cells)} |")
        lines.append("")
    done = [pw for pw in pages if not pw.failed and pw.new]
    if done:
        lines += ["### docs", "", "| Locale | Pages |", "|---|---|"]
        by_code: dict[str, list[str]] = {}
        for pw in done:
            by_code.setdefault(pw.code, []).append(pw.rel)
        lines += [f"| {c} | {', '.join(f'`{r}`' for r in sorted(rs))} |" for c, rs in sorted(by_code.items())]
        lines.append("")
    left = [(w.target.locale, k, why) for w in work for k, why in w.failed.items()]
    left += [(pw.code, pw.rel, pw.failed) for pw in pages if pw.failed]
    if left:
        lines += ["These stay as they were, because no answer passed the check in two tries:", ""]
        lines += [f"- {loc} `{k}`: {why}" for loc, k, why in left]
        lines.append("")
    lines.append("To review, read a few changed strings in a language you know, then merge.")
    body = "\n".join(lines) + "\n"
    if len(body) > 60000:
        body = body[:59000] + "\n\n(The list is cut here. The diff has every change.)\n"
    return title, body


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", action="append", choices=list(REPOS), help="only this repo (repeatable)")
    ap.add_argument("--base", default="main", help="the branch to translate (default main)")
    ap.add_argument("--base-remote", default="origin", choices=["origin", "amiga"], help="where --base lives")
    ap.add_argument("--dry-run", action="store_true", help="find the work, translate nothing")
    ap.add_argument("--no-push", action="store_true", help="translate and commit, but push nothing")
    args = ap.parse_args(argv)

    (ROOT / "logs").mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(ROOT / "logs" / "i18n-sync.log", encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(fmt)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    log.addHandler(handler)
    log.addHandler(stream)
    log.setLevel(logging.INFO)

    lock = open(ROOT / "i18n-sync.lock", "w")  # noqa: SIM115 - held for the whole run
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.error("another sync is running; this one stops")
        return 1

    log.info("start: %s", " ".join(sys.argv[1:]) or "nightly")
    status = 0
    claude_box: list = []
    for repo in args.repo or list(REPOS):
        try:
            log.info("%s: %s", repo, sync_repo(repo, args, claude_box))
        except Refused as e:
            log.error("%s: REFUSED: %s", repo, e)
            status = 1
        except Exception as e:  # one repo's failure never stops the others
            log.exception("%s: FAILED, nothing pushed: %s", repo, e)
            status = 1
    log.info("end: %s", "ok" if status == 0 else "with errors")
    return status


if __name__ == "__main__":
    sys.exit(main())
