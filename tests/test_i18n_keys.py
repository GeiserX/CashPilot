"""Every string key the UI asks for exists in app/i18n/en.json, and every key there is asked for.

A key the code asks for but en.json lacks renders as the bare key on the page.
A key en.json has but nothing asks for is a string that 19 translators would
translate for nothing. Both directions are checked over the templates, the
browser scripts (app/static/js) and the server (app/**/*.py).

A key must be a literal string at its call site, so this test can see it. A
call that builds its key at runtime names every key it can produce on the same
line, in a comment: ``i18n-keys: a.one, a.two``.

The same scan refuses a local variable or parameter named ``t`` in the browser
code: it would hide the global t() inside its scope, and the call there would
throw instead of showing text.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EN = json.loads((ROOT / "app/i18n/en.json").read_text(encoding="utf-8"))

# t('key', ...) or t("key", ...): the Jinja global, the browser global and
# app.i18n.t. A preceding letter, digit, _ or $ means another identifier.
CALL = re.compile(r"""(?<![\w$])t\(\s*(['"])([^'"]+)\1\s*(?=[,)])""")
# Any t( that is not a lone literal key: t(key), t(`a.${b}`), t('a.' ~ b), t('a' + b).
ANY_CALL = re.compile(r"""(?<![\w$])t\((?!\s*\))(?!\s*(['"])[^'"]+\1\s*[,)])""")
LISTED = re.compile(r"i18n-keys:\s*([\w.\-]+(?:\s*,\s*[\w.\-]+)*)")
# A local named t: `const t =`, `let t,`, `(t) =>`, `t =>`, `function f(a, t)`, `for (const t of`.
SHADOW = re.compile(
    r"""(?:\b(?:const|let|var)\s+t\b(?!\w))"""
    r"""|(?:(?<![\w$.])t\s*=>)"""
    r"""|(?:\(\s*t\s*\)\s*=>)"""
    r"""|(?:\bfunction\b[^(]*\([^)]*(?<![\w$])t(?![\w$])[^)]*\))"""
)


def _sources() -> list[Path]:
    files = sorted((ROOT / "app/templates").rglob("*.html"))
    files += sorted((ROOT / "app/static/js").glob("*.js"))
    files += sorted(p for p in (ROOT / "app").rglob("*.py") if p.parent.name != "i18n")
    return files


def _scan() -> tuple[set[str], list[str]]:
    used: set[str] = set()
    dynamic: list[str] = []
    for path in _sources():
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        # The whole file, not line by line: a formatter can put the key on the line after t(.
        used.update(m.group(2) for m in CALL.finditer(text))
        listed_lines = set()
        for number, line in enumerate(lines, 1):
            listed = LISTED.search(line)
            if listed:
                used.update(k.strip() for k in listed.group(1).split(","))
                listed_lines.add(number)
        if path.name == "i18n.js":  # the implementation: t(key, params) is its own signature
            continue
        for m in ANY_CALL.finditer(text):
            number = text.count("\n", 0, m.start()) + 1
            line = lines[number - 1]
            if number in listed_lines or line.lstrip().startswith(("#", "//", "*", "{#")):
                continue
            dynamic.append(f"{rel}:{number}: {line.strip()[:120]}")
    return used, dynamic


def test_every_key_asked_for_exists_and_every_key_is_asked_for():
    used, _ = _scan()
    missing = sorted(used - set(EN))
    unused = sorted(set(EN) - used)
    assert not missing, f"asked for but not in app/i18n/en.json: {missing[:20]}"
    assert not unused, f"in app/i18n/en.json but nothing asks for it: {unused[:20]}"


def test_a_built_key_names_the_keys_it_can_produce():
    _, dynamic = _scan()
    assert not dynamic, "t() with a key built at runtime, and no i18n-keys comment:\n" + "\n".join(dynamic[:20])


def test_nothing_in_the_browser_code_hides_the_global_t():
    found = []
    for path in sorted((ROOT / "app/static/js").glob("*.js")) + sorted((ROOT / "app/templates").rglob("*.html")):
        if path.name == "i18n.js":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if SHADOW.search(line):
                found.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:120]}")
    assert not found, "a local named t hides the global t():\n" + "\n".join(found)


# An attribute that code reads, holding a message: data-action="wizard{{ t('setup.next') }}"
# reads wizardNext in English and names no handler in French.
CODE_ATTR = re.compile(r"""\b(?:data-action|data-a\d|id|class|name|value|href|for|type)="[^"]*(?:\{\{\s*t\(|\$\{t\()""")


def test_no_message_sits_inside_an_attribute_that_code_reads():
    found = []
    for path in sorted((ROOT / "app/templates").rglob("*.html")) + sorted((ROOT / "app/static/js").glob("*.js")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if CODE_ATTR.search(line):
                found.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:120]}")
    assert not found, "a translated word inside an attribute that code reads:\n" + "\n".join(found)
    assert CODE_ATTR.search("""<button data-action="wizard{{ t('setup.next') }}">""")
    assert CODE_ATTR.search("""`<a class="x ${t('a.b')}">`""")
    assert not CODE_ATTR.search("""<button title="{{ t('a.b') }}" data-action="go">""")


def test_the_fleet_key_never_holds_a_translated_word():
    """A failed reveal's "(error)" in another language need not start with "(", so it must never be the key."""
    fleet = (ROOT / "app/templates/fleet.html").read_text(encoding="utf-8")
    assigned = re.findall(r"\b_apiKey = ([^;]*);", fleet)
    assert assigned, "the key is no longer assigned where this test looks"
    assert not [a for a in assigned if re.search(r"(?<![\w$])t\(", a)], assigned


def _python_shadows(source: str) -> list[int]:
    """Lines where a module binds a local t: an argument, an assignment or a loop name."""
    tree = ast.parse(source)
    return sorted(
        {
            n.lineno
            for n in ast.walk(tree)
            if (isinstance(n, ast.Name) and n.id == "t" and isinstance(n.ctx, ast.Store))
            or (isinstance(n, ast.arg) and n.arg == "t")
        }
    )


def test_nothing_in_the_server_code_hides_t():
    """A module that imports t must not also bind t: a message there would call the local."""
    found = []
    for path in sorted(p for p in (ROOT / "app").rglob("*.py") if p.parent.name != "i18n"):
        source = path.read_text(encoding="utf-8")
        if re.search(r"^from app\.i18n import .*\bt\b", source, re.M):
            found += [f"{path.relative_to(ROOT)}:{n}" for n in _python_shadows(source)]
    assert not found, "a local named t hides app.i18n.t:\n" + "\n".join(found)
    assert _python_shadows("x = [t for t in y]") == [1] and _python_shadows("def f(t): pass") == [1]
    assert _python_shadows("x = t('a')") == []


def test_en_json_is_sorted_so_parallel_edits_merge():
    """Fix with: python3 -c "import json,sys;p='app/i18n/en.json';d=json.load(open(p));json.dump(dict(sorted(d.items())),open(p,'w'),ensure_ascii=False,indent=2);open(p,'a').write('\\n')" """
    keys = list(EN)
    assert keys == sorted(keys), "app/i18n/en.json keys are not sorted; see this test's docstring"


def test_the_scan_sees_a_call_a_built_key_and_a_shadow():
    """The scan itself can fail: each pattern matches what it is meant to."""
    assert [m.group(2) for m in CALL.finditer("""{{ t('a.b') }} x t("c.d", {n}) CPI18N.t('e')""")] == [
        "a.b",
        "c.d",
        "e",
    ]
    assert not CALL.search("t('a.' ~ b)") and ANY_CALL.search("t('a.' ~ b)") and ANY_CALL.search("t('a' + b)")
    assert not CALL.search("const at('x'); format('y')")
    assert ANY_CALL.search("t(`status.${x}`)") and ANY_CALL.search("t(key)")
    assert not ANY_CALL.search("t('a')") and not ANY_CALL.search("calls t() first")
    wrapped = 't(\n    "a.b",\n    name=x,\n)'
    assert [m.group(2) for m in CALL.finditer(wrapped)] == ["a.b"] and not ANY_CALL.search(wrapped)
    for bad in ["const t = 1", "items.map(t => t.id)", "(t) => x", "function f(a, t) {", "for (const t of xs)"]:
        assert SHADOW.search(bad), bad
    for good in ["const tab = 1", "x.t => 1", "function f(text) {", "t('a')", "const total = t('a')"]:
        assert not SHADOW.search(good), good


#: Files whose source runs where no app package exists: the activity probe runs
#: procnet.py with ``python -c`` inside an earner's namespace, and an operator
#: runs state_backup.py with ``python -I`` to read a backup.
STANDALONE = ["app/procnet.py", "app/state_backup.py"]


def _app_imports(source: str) -> list[str]:
    """The app modules that a source imports, at any depth."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module]
        elif isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        else:
            continue
        found += [n for n in names if n == "app" or n.startswith("app.")]
    return found


def test_code_that_runs_outside_the_app_imports_nothing_from_it():
    """A t() in these files would fail where they run, so their words stay English."""
    sources = {rel: (ROOT / rel).read_text(encoding="utf-8") for rel in STANDALONE}
    found = {rel: _app_imports(src) for rel, src in sources.items() if _app_imports(src)}
    assert not found, f"standalone code imports the app: {found}"
    assert _app_imports("from app.i18n import t") == ["app.i18n"]
    assert _app_imports("def f():\n    import app.x") == ["app.x"] and _app_imports("from . import x") == []


def test_a_server_message_is_a_sentence_and_never_a_code():
    """A one-word value is a code that some caller compares (a reason, a route state), not words to translate."""
    server = ("api.", "worker.", "err.", "preflight.")
    codes = {k: v for k, v in EN.items() if k.startswith(server) and not re.search(r"\s", v)}
    assert not codes, f"these server messages look like codes: {codes}"
