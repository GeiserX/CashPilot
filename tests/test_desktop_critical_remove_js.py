"""Removing a service with its data from a Desktop never asks for a delete the Desktop refuses.

CashPilot Desktop deletes a node identity or wallet only on that computer and
refuses that delete from the server whatever the password. The server still
asked the owner to review the volumes and type the password, then showed the
refusal as if the password was wrong.

removeService runs in node against the real app.js, with api() answering the
box's critical_volume refusal.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.i18n_source import NODE_T

APP_JS = Path(__file__).resolve().parent.parent / "app/static/js/app.js"

_HARNESS = r"""
const src = require('fs').readFileSync(process.argv[process.argv.length - 2], 'utf8');
const cut = (head) => {
  const from = src.indexOf(head);
  if (from < 0) { console.log(JSON.stringify({ error: `${head} moved` })); process.exit(0); }
  return src.slice(from, src.indexOf('\n  }\n', from) + 4);
};
const { deviceType, first, leftover } = JSON.parse(process.argv[process.argv.length - 1]);
const calls = [];
const toasts = [];
const env = {
  _detailWorkers: [{ id: 5, name: 'mac', system_info: deviceType ? { device_type: deviceType } : {} }],
  _isOwner: true,
  confirm: () => true,
  toast: (m, kind) => toasts.push([m, kind]),
  removed: () => calls.push('removed'),
  confirmCriticalVolumes: () => { calls.push('review'); return 'critical_set='; },
  api: async (path) => {
    calls.push(path);
    // The first answer may be a partial restore's refusal; every other one is critical_volume.
    const code = first && calls.length === 1 ? first : 'critical_volume';
    const err = new Error(code); err.code = code;
    err.refusal = code === 'restore_unfinished' ? { worker_id: 5, worker_name: 'mac' } : { blocked: [], critical_set: '' };
    throw err;
  },
};
const body = [cut('  function isDesktopWorker('), cut('  function _desktopKeepsCriticalData('),
  cut('  async function removeService(')].join('\n');
const removeService = new Function(...Object.keys(env), `${body}; return removeService;`)(...Object.values(env));
(async () => {
  await removeService('proxybase', '5', 'mac', leftover);
  console.log(JSON.stringify({ calls, toasts }));
})();
"""


def _remove(device_type: str | None, first: str | None = None, leftover: str | None = None) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    out = subprocess.run(
        [
            node,
            *NODE_T,
            "-e",
            _HARNESS,
            str(APP_JS),
            json.dumps({"deviceType": device_type, "first": first, "leftover": leftover}),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    result = json.loads(out.stdout)
    assert "error" not in result, result
    return result


def test_a_desktop_is_not_asked_for_a_delete_it_refuses():
    result = _remove("desktop")
    assert result["calls"] == ["/api/services/proxybase?worker_id=5&delete_volumes=true"]
    [(message, kind)] = result["toasts"]
    assert kind == "error"
    assert "only on that computer" in message and "keep the data" in message


def test_a_server_box_still_reviews_the_volumes_and_asks():
    result = _remove(None)
    assert "review" in result["calls"]
    assert any("allow_delete_critical=true" in c for c in result["calls"])


def test_a_desktop_is_not_asked_when_a_partial_restore_is_deleted_either():
    result = _remove("desktop", first="restore_unfinished")
    assert result["calls"][1].endswith("&delete_volumes=true&only_if_restore_unfinished=true")
    assert "review" not in result["calls"]
    assert not any("allow_delete_critical=true" in c for c in result["calls"])
    [(message, kind)] = result["toasts"]
    assert kind == "error" and "only on that computer" in message
    # Its own reason: a Remove that keeps the data is refused while a partial restore stays.
    assert "partial restore" in message and "press Remove again" not in message


def test_a_server_box_still_reviews_the_partial_restore_delete():
    result = _remove(None, first="restore_unfinished")
    assert "review" in result["calls"]
    assert any("allow_delete_critical=true" in c for c in result["calls"])


def test_a_desktop_partial_restore_row_gets_the_partial_restore_message():
    # The row of a partial restore sends only_if_restore_unfinished at once, so
    # its first critical_volume refusal is the partial restore's.
    result = _remove("desktop", leftover="leftover")
    assert result["calls"] == [
        "/api/services/proxybase?worker_id=5&delete_volumes=true&only_if_restore_unfinished=true"
    ]
    [(message, kind)] = result["toasts"]
    assert kind == "error" and "partial restore" in message and "press Remove again" not in message
