"""The log viewer's line splitter, run in node against Docker-style log text.

Docker puts an RFC 3339 time in nanoseconds before every line, which is often
longer than the message, so the viewer shows it short. These run the real
function from app/static/js/app.js, never its source text.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.i18n_source import NODE_T

ROOT = Path(__file__).resolve().parent.parent

_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const from = src.indexOf('  const LOG_TIME = ');
const to = src.indexOf('  // The text each viewer shows');
if (from < 0 || to < from) { console.log(JSON.stringify({ error: 'markers not found' })); process.exit(0); }
const logEntries = new Function(`${src.slice(from, to)}; return logEntries;`)();
const [text, now] = JSON.parse(process.argv[2]);
console.log(JSON.stringify(logEntries(text, new Date(now))));
"""


def _entries(text: str, now: str = "2026-11-24T18:00:00Z") -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    out = subprocess.run(
        [node, "-e", _HARNESS, str(ROOT / "app/static/js/app.js"), json.dumps([text, now])],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
        # Local time is what the viewer shows, so the test fixes the zone.
        env={**os.environ, "TZ": "Europe/Madrid"},
    )
    result = json.loads(out.stdout)
    assert "error" not in result, result
    return result


LOGS = (
    '2026-11-24T15:52:39.534636172Z time="2026-11-24T15:52:39Z" level=info msg="proxy connected"\n'
    "2026-11-24T15:52:40.000000001Z   indented message\n"
)


class TestLogEntries:
    def test_todays_lines_show_local_time_only_with_the_full_stamp_kept(self):
        result = _entries(LOGS)
        first, second = result["entries"]
        assert first["shown"] == "16:52:39"
        assert first["stamp"] == "2026-11-24T15:52:39.534636172Z"
        assert first["message"] == 'time="2026-11-24T15:52:39Z" level=info msg="proxy connected"'
        # Only the one space Docker adds is dropped; the message's own indent stays.
        assert second["message"] == "  indented message"
        assert result["width"] == 8

    def test_a_line_from_another_day_dates_every_line(self):
        result = _entries("2026-11-23T20:00:00.1Z old\n" + LOGS)
        assert [e["shown"] for e in result["entries"]] == [
            "2026-11-23 21:00:00",
            "2026-11-24 16:52:39",
            "2026-11-24 16:52:40",
        ]
        assert result["width"] == 19

    def test_a_date_that_is_today_in_utc_but_not_locally_is_dated(self):
        # 23:30 UTC on the 24th is the 25th in Madrid; "today" there is the 24th.
        result = _entries("2026-11-24T23:30:00Z late\n", now="2026-11-24T12:00:00Z")
        assert result["entries"][0]["shown"] == "2026-11-25 00:30:00"

    def test_lines_without_a_stamp_pass_through_whole(self):
        result = _entries("Error loading logs: nope\n\tat frame\r\n")
        assert [(e["shown"], e["message"]) for e in result["entries"]] == [
            ("", "Error loading logs: nope"),
            ("", "\tat frame"),
        ]
        assert result["width"] == 0

    def test_offsets_and_seconds_without_fraction_are_read(self):
        result = _entries("2026-11-24T10:00:05+02:00 x\n")
        assert result["entries"][0]["shown"] == "09:00:05"
        assert result["entries"][0]["message"] == "x"

    def test_an_impossible_time_is_left_as_text(self):
        result = _entries("2026-13-45T99:99:99Z broken\n")
        assert result["entries"][0]["shown"] == ""
        assert result["entries"][0]["message"] == "2026-13-45T99:99:99Z broken"


_TITLE_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const from = src.indexOf('  function logsTitle(');
const to = src.indexOf('  async function viewLogs(');
if (from < 0 || to < from) { console.log(JSON.stringify({ error: 'markers not found' })); process.exit(0); }
const logsTitle = new Function(`${src.slice(from, to)}; return logsTitle;`)();
console.log(JSON.stringify(JSON.parse(process.argv[2]).map((args) => logsTitle(...args))));
"""


def test_the_logs_title_reads_as_before_for_a_service_a_worker_and_a_copy():
    """Each case is one message now; the English must not move."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    cases = [["honeygain", None, None], ["honeygain", 3, None], ["honeygain", 3, "1"], ["honeygain", 1234, "2"]]
    out = subprocess.run(
        [node, *NODE_T, "-e", _TITLE_HARNESS, str(ROOT / "app/static/js/app.js"), json.dumps(cases)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert json.loads(out.stdout) == [
        "Logs: honeygain",
        "Logs: honeygain (worker #3)",
        "Logs: honeygain (worker #3)",
        "Logs: honeygain (worker #1234, copy 2)",
    ]
