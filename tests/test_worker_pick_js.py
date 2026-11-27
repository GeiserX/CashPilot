"""The deploy forms tick the only online box, so Deploy works on the first click.

A fresh single-box install left that box unticked, and Deploy in the setup
wizard only answered "Select at least one worker node".

workerCheckboxList runs in node against the real app.js.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parent.parent / "app/static/js/app.js"

_HARNESS = r"""
const src = require('fs').readFileSync(process.argv[process.argv.length - 2], 'utf8');
const from = src.indexOf('  function workerCheckboxList(');
const to = src.indexOf('\n  }\n', from) + 4;
if (from < 0 || to <= from) { console.log(JSON.stringify({ error: 'block moved' })); process.exit(0); }
const { svc, workers } = JSON.parse(process.argv[process.argv.length - 1]);
const helpers = {
  workerCopies: (w, slug) => (w.containers || []).filter(c => c.slug === slug),
  isDesktopWorker: () => false,
  escapeHtml: s => String(s),
};
const fn = new Function(...Object.keys(helpers), `${src.slice(from, to)}; return workerCheckboxList;`)(
  ...Object.values(helpers));
const { rows } = fn(svc, workers, 'cb');
const boxes = [...rows.matchAll(/<input type="checkbox"[^>]*>/g)].map(m => m[0]);
console.log(JSON.stringify(boxes.map(b => ({ checked: / checked/.test(b), disabled: / disabled/.test(b) }))));
"""


def _boxes(workers: list[dict]) -> list[dict]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    out = subprocess.run(
        [node, "-e", _HARNESS, str(APP_JS), json.dumps({"svc": {"slug": "mysterium"}, "workers": workers})],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    result = json.loads(out.stdout)
    assert not isinstance(result, dict), result
    return result


def test_the_only_online_box_starts_ticked():
    assert _boxes([{"id": 1, "name": "local"}]) == [{"checked": True, "disabled": False}]


def test_with_two_boxes_the_owner_still_picks():
    assert _boxes([{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]) == [
        {"checked": False, "disabled": False},
        {"checked": False, "disabled": False},
    ]


def test_a_box_that_runs_it_stays_locked():
    workers = [{"id": 1, "name": "local", "containers": [{"slug": "mysterium"}]}]
    assert _boxes(workers) == [{"checked": True, "disabled": True}]
