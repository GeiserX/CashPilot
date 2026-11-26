"""Every catalog env-field pattern must work as an HTML `pattern` attribute.

The deploy forms and the import review put `docker.env[].pattern` into an
`<input pattern>`. Browsers compile that as `^(?:<pattern>)$` with the `v`
flag, and under `v` an unescaped literal `-` in a character class is a syntax
error. The browser then drops the pattern without a word, so checkValidity()
accepts any value. Python's `re` accepts both forms, so only a JavaScript
compile catches it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from app import catalog

_HARNESS = r"""
const fields = JSON.parse(process.argv[1]);
const broken = [];
for (const [where, pattern] of fields) {
  try {
    new RegExp(`^(?:${pattern})$`, 'v');
  } catch (err) {
    broken.push(`${where}: ${pattern} (${err.message})`);
  }
}
console.log(JSON.stringify(broken));
"""

_MATCH = r"""
const [pattern, value] = process.argv.slice(1);
console.log(JSON.stringify(new RegExp(`^(?:${pattern})$`, 'v').test(value)));
"""


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    return node


def _env_patterns() -> list[tuple[str, str]]:
    found = []
    for svc in catalog.load_services():
        for var in (svc.get("docker") or {}).get("env") or []:
            if isinstance(var, dict) and var.get("pattern"):
                found.append((f"{svc['slug']}.{var['key']}", var["pattern"]))
    return found


def _browser_accepts(pattern: str, value: str) -> bool:
    out = subprocess.run(
        [_node(), "-e", _MATCH, pattern, value], capture_output=True, text=True, check=True, timeout=30
    )
    return json.loads(out.stdout)


def test_every_env_pattern_compiles_as_an_html_pattern():
    fields = _env_patterns()
    assert len(fields) > 10, "the catalog lost its env patterns; this test would check nothing"
    out = subprocess.run(
        [_node(), "-e", _HARNESS, json.dumps(fields)], capture_output=True, text=True, check=True, timeout=30
    )
    assert json.loads(out.stdout) == []


@pytest.mark.parametrize(
    ("key", "value", "ok"),
    [
        ("WORKER_NAME", "rig-2", True),
        ("WORKER_NAME", "bad!", False),
        ("KRYPTEX_EMAIL", "first.last+mining@example.co.uk", True),
        ("KRYPTEX_EMAIL", "not-an-email", False),
    ],
)
def test_kryptex_fields_check_the_same_way_in_browser_and_backend(key, value, ok):
    svc = catalog.get_service("kryptex-pearl")
    pattern = next(var["pattern"] for var in svc["docker"]["env"] if var["key"] == key)
    assert _browser_accepts(pattern, value) is ok
    assert (re.fullmatch(pattern, value) is not None) is ok
