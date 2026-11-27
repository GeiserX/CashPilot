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

APP_JS = Path(__file__).resolve().parent.parent / "app/static/js/app.js"

_HARNESS = r"""
const src = require('fs').readFileSync(process.argv[process.argv.length - 2], 'utf8');
const cut = (head) => {
  const from = src.indexOf(head);
  if (from < 0) { console.log(JSON.stringify({ error: `${head} moved` })); process.exit(0); }
  return src.slice(from, src.indexOf('\n  }\n', from) + 4);
};
const { deviceType } = JSON.parse(process.argv[process.argv.length - 1]);
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
    const err = new Error('critical'); err.code = 'critical_volume'; err.refusal = { blocked: [], critical_set: '' };
    throw err;
  },
};
const body = [cut('  function isDesktopWorker('), cut('  function _desktopKeepsCriticalData('),
  cut('  async function removeService(')].join('\n');
const removeService = new Function(...Object.keys(env), `${body}; return removeService;`)(...Object.values(env));
(async () => {
  await removeService('proxybase', '5', 'mac', undefined);
  console.log(JSON.stringify({ calls, toasts }));
})();
"""


def _remove(device_type: str | None) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    out = subprocess.run(
        [node, "-e", _HARNESS, str(APP_JS), json.dumps({"deviceType": device_type})],
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
