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

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EN = json.loads((ROOT / "app/i18n/en.json").read_text(encoding="utf-8"))

# t('key', ...) or t("key", ...): the Jinja global, the browser global and
# app.i18n.t. A preceding letter, digit, _ or $ means another identifier.
CALL = re.compile(r"""(?<![\w$])t\(\s*(['"])([^'"]+)\1""")
ANY_CALL = re.compile(r"""(?<![\w$])t\(\s*(?=\S)(?![)'"])""")
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
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            used.update(m.group(2) for m in CALL.finditer(line))
            listed = LISTED.search(line)
            if listed:
                used.update(k.strip() for k in listed.group(1).split(","))
            elif (
                path.name != "i18n.js"  # the implementation: t(key, params) is its own signature
                and ANY_CALL.search(line)
                and not line.lstrip().startswith(("#", "//", "*", "{#"))
            ):
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


def test_en_json_is_sorted_so_parallel_edits_merge():
    """Fix with: python3 -c "import json,sys;p='app/i18n/en.json';d=json.load(open(p));json.dump(dict(sorted(d.items())),open(p,'w'),ensure_ascii=False,indent=2);open(p,'a').write('\\n')" """
    keys = list(EN)
    assert keys == sorted(keys), "app/i18n/en.json keys are not sorted; see this test's docstring"


def test_the_scan_sees_a_call_a_built_key_and_a_shadow():
    """The scan itself can fail: each pattern matches what it is meant to."""
    assert [m.group(2) for m in CALL.finditer("""{{ t('a.b') }} x t("c.d", {n}) CPI18N.t('e')""")] == ["a.b", "c.d", "e"]
    assert not CALL.search("const at('x'); format('y')")
    assert ANY_CALL.search("t(`status.${x}`)") and ANY_CALL.search("t(key)")
    assert not ANY_CALL.search("t('a')") and not ANY_CALL.search("calls t() first")
    for bad in ["const t = 1", "items.map(t => t.id)", "(t) => x", "function f(a, t) {", "for (const t of xs)"]:
        assert SHADOW.search(bad), bad
    for good in ["const tab = 1", "x.t => 1", "function f(text) {", "t('a')", "const total = t('a')"]:
        assert not SHADOW.search(good), good
