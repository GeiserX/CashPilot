"""Build and check the translated docs sites.

usage: python3 -I .github/scripts/docs-i18n.py check
       python3 -I .github/scripts/docs-i18n.py build [locale ...]
       python3 -I .github/scripts/docs-i18n.py anchors <page.md>

Run from the repository root, after the English build has written site/ (the workflow does).

Zensical gives a project one language: HTML allows one per document, and the theme takes
its `lang`, `dir` and UI strings from `theme.language`. So each locale is its own build:

  - English stays the main build, at the current URLs.
  - The other locales are the `extra.alternate` entries of zensical.toml, the theme's
    language switcher. Each one is built from a generated copy of docs/ into site/<locale>/.
  - A page translated in docs/i18n/<locale>/<path>.md replaces the English page in that
    copy. Every other page is the English page with a "not translated yet" note, so every
    link and every page exists in every locale.
  - A translated page stores the hash of the English page it was made from
    (`source_hash` in its front matter). When the English page changes, the translation is
    stale: it still builds, with a note that links the newer English page.

`check` fails on a broken translation: no `source_hash`, no English page, a locale with no
locale.toml, or a fresh page whose code blocks, inline code, link targets or heading ids
differ from the English page. Code and links are never translated, and referral links must
stay byte for byte. Links into a page (`faq.md#some-heading`) use the English ids, so a
translated heading keeps the English id with `{ #id }`; `anchors` prints them. Stale pages
are listed, never an error: a lane updates them in batches.

`build` compares the heading ids again on the built pages, of every fresh translation and
every English fallback page, so the check's Markdown reading cannot drift from Zensical's.

Stdlib only, like site-check.py, except that the heading id check needs Python-Markdown,
which Zensical installs. Without it the check says so, and fails under CI.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path.cwd()
DOCS = ROOT / "docs"
I18N = DOCS / "i18n"
SITE = ROOT / "site"
WORK = ROOT / "build" / "docs-i18n"

# The theme's language file for each locale, where its name differs from our BCP 47 code.
THEME_LANGUAGE = {"pt-BR": "pt-BR", "zh-Hans": "zh", "fil": "tl"}

COUNT = re.compile(r"(<!-- n:(\w+) -->)\d*(<!-- /n -->)")
FRONT = re.compile(r"\A---\n(.*?\n)---\n", re.S)
HASH_LINE = re.compile(r"^source_hash:\s*[\"']?([0-9a-f]{12})[\"']?\s*$", re.M)
FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
INLINE = re.compile(r"(`+)(.+?)\1")
LINKS = [
    re.compile(r"\]\(\s*<?([^)\s>]+)"),  # [text](url) and ![alt](src)
    re.compile(r"""(?:href|src)\s*=\s*["']([^"']+)["']"""),  # raw HTML
    re.compile(r"<(https?://[^>\s]+)>"),  # <https://autolink>
    re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)", re.M),  # [ref]: url
]


def fail(msg: str) -> None:
    sys.exit(f"ERROR {msg}")


def config() -> dict:
    return tomllib.loads((ROOT / "zensical.toml").read_text(encoding="utf-8"))["project"]


def locales(cfg: dict) -> list[dict]:
    """The switcher's entries other than English: {code, name, link}."""
    alts = (cfg.get("extra") or {}).get("alternate") or []
    out = [a | {"code": a["lang"]} for a in alts if a.get("lang") != "en"]
    if not out:
        fail("zensical.toml: no extra.alternate entries besides English")
    return out


def i18n_config() -> dict:
    return tomllib.loads((I18N / "config.toml").read_text(encoding="utf-8"))


def english_pages(cfg: dict) -> list[str]:
    """Every published English page, as a path relative to docs/ ('guides/grass.md')."""
    patterns = [
        line.strip()
        for line in cfg.get("exclude_docs", "").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    pages = []
    for p in sorted(DOCS.rglob("*.md")):
        rel = p.relative_to(DOCS).as_posix()
        if rel.startswith("i18n/") or any(excluded(rel, pat) for pat in patterns):
            continue
        pages.append(rel)
    return pages


def excluded(rel: str, pat: str) -> bool:
    """The subset of gitignore patterns exclude_docs uses: a dir/, a name, a glob."""
    from fnmatch import fnmatch

    if pat.endswith("/"):
        return rel.startswith(pat) or f"/{pat}" in f"/{rel}"
    name = rel.rsplit("/", 1)[-1]
    return fnmatch(rel, pat) or fnmatch(name, pat)


def source_hash(text: str) -> str:
    """The hash every CashPilot surface stores next to a translation (the first 12 hex of
    sha256, as scripts/i18n_check.py does), of the English page with its generated
    service counts blanked: a catalog change rewrites those numbers, and must not mark
    every translation stale."""
    return hashlib.sha256(COUNT.sub(r"\1\3", text).encode("utf-8")).hexdigest()[:12]


def split_front(text: str) -> tuple[str, str]:
    m = FRONT.match(text)
    return (m.group(1), text[m.end() :]) if m else ("", text)


def parts(body: str) -> tuple[list[str], set[str], set[str]]:
    """The fenced code blocks (in order), inline code spans and link targets of a page."""
    blocks, prose, lines = [], [], body.split("\n")
    i = 0
    while i < len(lines):
        m = FENCE.match(lines[i])
        if not m:
            prose.append(lines[i])
            i += 1
            continue
        indent, fence = len(m.group(1)), m.group(2)
        block = [m.group(2) + m.group(3).rstrip()]
        i += 1
        while i < len(lines):
            line = lines[i]
            i += 1
            if line.strip().startswith(fence[0] * len(fence)) and not line.strip().strip(fence[0]):
                break
            block.append(line[indent:] if line[:indent].strip() == "" else line.lstrip())
        blocks.append("\n".join(block).rstrip())
        prose.append("")
    text = "\n".join(prose)
    code = {m.group(2).strip() for m in INLINE.finditer(text)}
    bare = INLINE.sub(" ", text)
    links = {m.group(1) for rx in LINKS for m in rx.finditer(bare)}
    return blocks, code, links


def heading_ids_md(body: str) -> list[str] | None:
    """Heading ids as Python-Markdown's toc extension makes them, which is what Zensical
    renders with: an explicit `{ #id }` wins, else the slug of the heading text, with
    `_1`, `_2` for repeats. None when Python-Markdown is not installed."""
    try:
        import markdown
    except ImportError:
        return None
    # Without the fence extension a `# comment` in an indented code block reads as a
    # heading, so blank every fenced block first.
    lines, fence = [], None
    for line in body.split("\n"):
        m = FENCE.match(line)
        if fence is None and m:
            fence = m.group(2)
            lines.append("")
        elif fence is not None:
            if line.strip().startswith(fence[0] * len(fence)) and not line.strip().strip(fence[0]):
                fence = None
            lines.append("")
        else:
            lines.append(line)
    md = markdown.Markdown(extensions=["toc", "attr_list", "md_in_html"])
    md.convert("\n".join(lines))
    ids: list[str] = []

    def walk(tokens):
        for t in tokens:
            ids.append(t["id"])
            walk(t["children"])

    walk(md.toc_tokens)
    return ids


def page_url(rel: str) -> str:
    """The directory URL of a page, relative to the site root ('guides/grass/')."""
    stem = rel[:-3]
    if stem == "index":
        return ""
    if stem.endswith("/index"):
        return stem[: -len("index")]
    return stem + "/"


def check() -> int:
    cfg = config()
    locs = locales(cfg)
    english = set(english_pages(cfg))
    only = set(i18n_config().get("english_only", []))
    errors, stale = [], []
    markdown_missing = False
    for name in only - english:
        errors.append(f"docs/i18n/config.toml: english_only lists {name}, which is not a published page")
    codes = {loc["code"] for loc in locs}
    for d in sorted(p for p in I18N.iterdir() if p.is_dir()):
        if d.name not in codes:
            errors.append(f"docs/i18n/{d.name}/: no extra.alternate entry in zensical.toml has lang {d.name!r}")
    for loc in locs:
        code = loc["code"]
        base = I18N / code
        strings = base / "locale.toml"
        if not strings.is_file():
            errors.append(f"docs/i18n/{code}/locale.toml: missing")
        else:
            try:
                notes = tomllib.loads(strings.read_text(encoding="utf-8")).get("notices", {})
            except tomllib.TOMLDecodeError as e:
                errors.append(f"docs/i18n/{code}/locale.toml: {e}")
                notes = {}
            for key in ("untranslated", "english_only", "stale"):
                if not isinstance(notes.get(key), str) or not notes[key].strip():
                    errors.append(f"docs/i18n/{code}/locale.toml: notices.{key} missing")
                elif key == "stale" and "{url}" not in notes[key]:
                    errors.append(
                        f"docs/i18n/{code}/locale.toml: notices.stale must link the English page with {{url}}"
                    )
        fresh = translated = 0
        for p in sorted(base.rglob("*.md")) if base.is_dir() else []:
            rel = p.relative_to(base).as_posix()
            where = f"docs/i18n/{code}/{rel}"
            if rel not in english:
                errors.append(f"{where}: no English page docs/{rel} is published")
                continue
            if rel in only:
                errors.append(f"{where}: {rel} is English-only in docs/i18n/config.toml")
                continue
            translated += 1
            front, body = split_front(p.read_text(encoding="utf-8"))
            m = HASH_LINE.search(front)
            src = (DOCS / rel).read_text(encoding="utf-8")
            if not m:
                errors.append(f"{where}: no source_hash in its front matter (the English page's is {source_hash(src)})")
                continue
            if m.group(1) != source_hash(src):
                stale.append(where)
                continue
            fresh += 1
            eb, ec, el = parts(split_front(src)[1])
            tb, tc, tl = parts(body)
            if eb != tb:
                n = next((i for i, (a, b) in enumerate(zip(eb, tb, strict=False)) if a != b), min(len(eb), len(tb)))
                errors.append(
                    f"{where}: code blocks differ from the English page ({len(tb)} vs {len(eb)}; first difference at block {n + 1})"
                )
            for label, e, t in (("inline code", ec, tc), ("link target", el, tl)):
                for item in sorted(e - t)[:5]:
                    errors.append(f"{where}: {label} {item!r} of the English page is missing")
                for item in sorted(t - e)[:5]:
                    errors.append(f"{where}: {label} {item!r} is not in the English page")
            # A count typed as a bare number keeps the old value after the next
            # catalog change; only a marker is refreshed from the English page.
            e_n = sorted(c.group(2) for c in COUNT.finditer(src))
            t_n = sorted(c.group(2) for c in COUNT.finditer(body))
            if e_n != t_n:
                errors.append(
                    f"{where}: count markers differ from the English page: {e_n} vs {t_n}"
                    " (copy each <!-- n:... --> marker from English)"
                )
            e_ids, t_ids = heading_ids_md(split_front(src)[1]), heading_ids_md(body)
            if e_ids is None:
                markdown_missing = True
            elif sorted(e_ids) != sorted(t_ids):
                missing, extra = sorted(set(e_ids) - set(t_ids)), sorted(set(t_ids) - set(e_ids))
                errors.append(
                    f"{where}: heading ids differ from the English page: missing {missing[:5]}, extra {extra[:5]}"
                    " (keep each English id with { #id })"
                )
        total = len(english - only)
        print(
            f"{code}: {fresh} fresh, {translated - fresh} stale, {total - translated} not translated, of {total} pages"
        )
    if markdown_missing:
        msg = "heading ids not compared: python-markdown is not installed (pip install -r docs/requirements-docs.txt)"
        if os.environ.get("CI"):
            errors.append(msg)  # CI installs it with Zensical: a check that silently skips is no check
        else:
            print("NOTE", msg + "; the build still compares them")
    for s in stale:
        print(f"STALE {s}: the English page changed after this translation")
    for e in errors:
        print("ERROR", e)
    print(f"docs-i18n check: {len(locs)} locales, {len(stale)} stale, {len(errors)} errors")
    return 1 if errors else 0


def note(text: str, kind: str) -> str:
    """An admonition with no title bar, indented as the admonition extension wants."""
    return f'!!! {kind} ""\n\n    ' + text.strip().replace("\n", "\n    ") + "\n\n"


def with_note(body: str, admonition: str) -> str:
    """Put the note under the page's first-level heading, or at the top when there is none."""
    lines = body.split("\n")
    in_fence = None
    for i, line in enumerate(lines):
        m = FENCE.match(line)
        if m:
            in_fence = None if in_fence else m.group(2)[0]
        if not in_fence and re.match(r"^# \S", line):
            return "\n".join(lines[: i + 1]) + "\n\n" + admonition + "\n".join(lines[i + 1 :])
    return admonition + body


def counts(src: str) -> dict[str, str]:
    """The service counts the English page states now, by marker name."""
    return {m.group(2): m.group(0) for m in COUNT.finditer(src)}


def toml_value(v) -> str:
    """Enough TOML to write a Zensical config back: one inline value per key."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{json.dumps(k, ensure_ascii=False)} = {toml_value(x)}" for k, x in v.items()) + "}"
    fail(f"zensical.toml: cannot write a {type(v).__name__} back")


def translate_nav(nav, labels: dict):
    if isinstance(nav, list):
        return [translate_nav(x, labels) for x in nav]
    if isinstance(nav, dict):
        return {labels.get(k, k): translate_nav(v, labels) for k, v in nav.items()}
    return nav


class Ids(HTMLParser):
    """Heading ids in the article of a built page."""

    def __init__(self, text: str):
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.article = 0
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == "article":
            self.article += 1
        elif self.article and re.fullmatch(r"h[1-6]", tag):
            a = dict(attrs)
            if a.get("id"):
                self.ids.append(a["id"])

    def handle_endtag(self, tag):
        if tag == "article" and self.article:
            self.article -= 1


def heading_ids(path: Path) -> list[str]:
    return Ids(path.read_text(encoding="utf-8")).ids if path.is_file() else []


def build(only_codes: list[str]) -> int:
    if not (SITE / "index.html").is_file():
        fail("site/index.html missing: build the English site first")
    cfg = config()
    locs = [loc for loc in locales(cfg) if not only_codes or loc["code"] in only_codes]
    english = english_pages(cfg)
    english_only = set(i18n_config().get("english_only", []))
    site_url = cfg["site_url"].rstrip("/") + "/"
    errors = []
    for loc in locs:
        code = loc["code"]
        work = WORK / code
        shutil.rmtree(work, ignore_errors=True)
        gen = work / "docs"
        shutil.copytree(DOCS, gen, ignore=shutil.ignore_patterns("i18n"))
        strings = tomllib.loads((I18N / code / "locale.toml").read_text(encoding="utf-8"))
        notices = strings["notices"]
        fresh = []  # pages whose heading ids must equal the English page's: fresh translations and English fallbacks
        for rel in english:
            src = (DOCS / rel).read_text(encoding="utf-8")
            url = site_url + page_url(rel)
            tr = I18N / code / rel
            if tr.is_file() and rel not in english_only:
                text = tr.read_text(encoding="utf-8")
                front, body = split_front(text)
                m = HASH_LINE.search(front)
                if m and m.group(1) == source_hash(src):
                    fresh.append(rel)
                else:
                    body = with_note(body, note(notices["stale"].format(url=url), "warning"))
                # The catalog counts follow the English page, never the translator's copy.
                now = counts(src)
                body = COUNT.sub(lambda c, now=now: now.get(c.group(2), c.group(0)), body)
                front = HASH_LINE.sub("", front).strip()
                text = (f"---\n{front}\n---\n" if front else "") + body
            else:
                front, body = split_front(src)
                key = "english_only" if rel in english_only else "untranslated"
                # The page is English: say so, so an Arabic page lays it out left to right
                # and a screen reader reads it as English. The note stays in the locale.
                body = with_note(
                    body, note(notices[key].format(url=url), "info") + '<div lang="en" dir="ltr" markdown="block">\n\n'
                )
                text = (f"---\n{front}---\n" if front else "") + body + "\n\n</div>\n"
                fresh.append(rel)
            (gen / rel).write_text(text, encoding="utf-8")

        project = dict(cfg)
        project.pop("docs_dir", None)
        project["site_url"] = site_url + code + "/"
        project["site_dir"] = "site"
        project["edit_uri"] = f"edit/main/docs/i18n/{code}/"
        project["nav"] = translate_nav(cfg["nav"], strings.get("nav", {}))
        theme = dict(cfg.get("theme", {}))
        language = THEME_LANGUAGE.get(code, code)
        theme["language"] = language
        if language != code:
            # The theme's file sets <html lang>: make it our BCP 47 code (pt-BR, zh-Hans, fil).
            over = work / "overrides" / "partials" / "languages"
            over.mkdir(parents=True)
            (over / f"{code}.html").write_text(
                f'{{% import "partials/languages/{language}.html" as base %}}\n'
                f'{{% macro t(key) %}}{{% if key == "language" %}}{code}{{% else %}}{{{{ base.t(key) }}}}{{% endif %}}{{% endmacro %}}\n',
                encoding="utf-8",
            )
            theme["custom_dir"] = "overrides"
            theme["language"] = code
        project["theme"] = theme
        plugins = dict(cfg.get("plugins", {}))
        # Social cards render page titles with a Latin font fetched from Google Fonts; a
        # locale page has no card rather than one with missing glyphs.
        plugins.pop("social", None)
        project["plugins"] = plugins
        md = json.loads(json.dumps(cfg.get("markdown_extensions", {})))
        snippets = md.get("pymdownx.snippets")
        if isinstance(snippets, dict) and "base_path" in snippets:
            # Includes resolve from the repository root and the generated docs.
            snippets["base_path"] = [
                str((ROOT / p).resolve()) if p != "docs" else str(gen.resolve()) for p in snippets["base_path"]
            ]
        project["markdown_extensions"] = md
        conf = work / "zensical.toml"
        conf.write_text(
            "[project]\n" + "".join(f"{json.dumps(k)} = {toml_value(v)}\n" for k, v in project.items()),
            encoding="utf-8",
        )

        print(f"::group::build {code}", flush=True)
        r = subprocess.run(
            [sys.executable, "-m", "zensical", "build", "--clean", "--strict", "-f", str(conf)], cwd=work
        )
        print("::endgroup::", flush=True)
        if r.returncode:
            errors.append(f"{code}: the build failed (exit {r.returncode})")
            continue
        out = SITE / code
        shutil.rmtree(out, ignore_errors=True)
        shutil.move(str(work / "site"), out)
        # The edit button points into docs/i18n/<locale>/. A page with no translation file
        # there is the English page, so its button edits the English source instead.
        for rel in english:
            if not (I18N / code / rel).is_file() or rel in english_only:
                html = out / page_url(rel) / "index.html"
                text = html.read_text(encoding="utf-8")
                html.write_text(text.replace(f"/docs/i18n/{code}/{rel}", f"/docs/{rel}"), encoding="utf-8")
        for rel in fresh:
            e = heading_ids(SITE / page_url(rel) / "index.html")
            t = heading_ids(out / page_url(rel) / "index.html")
            if sorted(e) != sorted(t):
                missing, extra = sorted(set(e) - set(t)), sorted(set(t) - set(e))
                errors.append(
                    f"docs/i18n/{code}/{rel}: heading ids differ from the English page: missing {missing[:5]}, extra {extra[:5]} (keep each English id with {{ #id }})"
                )
        print(f"{code}: built, {sum((I18N / code / r).is_file() for r in fresh)} fresh translated pages")
    for e in errors:
        print("ERROR", e)
    return 1 if errors else 0


def anchors(rel: str) -> int:
    """The English page's heading ids, in order, for a translator to keep."""
    page = SITE / page_url(rel) / "index.html"
    if not page.is_file():
        fail(f"{page}: not built (build the English site first)")
    for i in heading_ids(page):
        print(i)
    return 0


if __name__ == "__main__":
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if cmd == "check" and not args:
        sys.exit(check())
    if cmd == "build":
        sys.exit(build(args))
    if cmd == "anchors" and len(args) == 1:
        sys.exit(anchors(args[0]))
    sys.exit(__doc__)
