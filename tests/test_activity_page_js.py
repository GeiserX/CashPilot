"""The Activity page's own chip and detail-box id functions, run in node.

Runs the functions from app/templates/activity.html against constructed input
and asserts on what they return, never on the template's text.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const from = src.indexOf("'use strict';");
const to = src.indexOf('function renderWorkers');
if (from < 0 || to < 0) { console.log(JSON.stringify({ error: 'markers not found' })); process.exit(0); }
const fns = new Function(`${src.slice(from, to)}; return { domId, chip, num };`)();
const cases = JSON.parse(process.argv[2]);
console.log(JSON.stringify(cases.map(([fn, args]) => fns[fn](...args))));
"""


def _run(*cases):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    out = subprocess.run(
        [node, "-e", _HARNESS, str(ROOT / "app/templates/activity.html"), json.dumps(cases)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    result = json.loads(out.stdout)
    assert not isinstance(result, dict), result
    return result


class TestDetailBoxIds:
    def test_ids_are_injective(self):
        a, b, c = _run(["domId", ["a.b"]], ["domId", ["a_b"]], ["domId", ["a_002eb"]])
        assert len({a, b, c}) == 3

    def test_ids_are_valid_tokens_and_plain_names_pass_through(self):
        odd, plain = _run(["domId", ["x y/z_é"]], ["domId", ["cashpilot-myst2"]])
        assert all(ch.isascii() and (ch.isalnum() or ch in "_-") for ch in odd)
        assert plain == "activity-detail-cashpilot-myst2"


class TestHostChips:
    def test_matched_by_cgroup_says_what_it_cannot_see(self):
        (html,) = _run(["chip", ["ok", ["cashpilot-mysterium"], "host_cgroup"]])
        assert "matched by cgroup" in html and "TIME_WAIT" in html and "forwarded by the kernel" in html

    @pytest.mark.parametrize(
        "reason,words",
        [
            ("cgroup_v1", "cgroup v2"),
            ("cgroup_missing", "not found"),
            ("sock_diag_refused", "refused"),
            ("kernel_no_cgroup_id", "does not report"),
        ],
    )
    def test_not_attributable_says_why(self, reason, words):
        (html,) = _run(["chip", ["host_network", ["cashpilot-mysterium"], reason]])
        assert "cannot be told apart" in html and words in html

    def test_unknown_reason_falls_back_to_the_plain_chip(self):
        (html,) = _run(["chip", ["host_network", ["x"], "<b>"]])
        assert "host network" in html and "<b>" not in html

    def test_unknown_is_a_dash(self):
        assert _run(["num", [None]], ["num", [0]]) == ["—", "0"]
