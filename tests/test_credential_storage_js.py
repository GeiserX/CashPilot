"""The Settings cards for the encryption key and the earner credentials say the right thing.

encryptionKeyStatusHtml and earnerSecretsHtml run in node against the real
app.js, with the real i18n.js and en.json, so a message that lost an argument
or a select that lost a branch shows here.
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
const [appPath, i18nPath, enPath, fnName, input] = process.argv.slice(-5);
global.window = { CP_I18N: { lang: 'en', dir: 'ltr', messages: JSON.parse(fs.readFileSync(enPath, 'utf8')) } };
global.navigator = { languages: ['en'], language: 'en' };
global.document = { readyState: 'complete', querySelectorAll: () => [], cookie: '' };
new Function(fs.readFileSync(i18nPath, 'utf8'))();
const src = fs.readFileSync(appPath, 'utf8');
const from = src.indexOf(`  function ${fnName}(`);
const to = src.indexOf('\n  }\n', from) + 4;
if (from < 0 || to <= from) { console.log(JSON.stringify({ error: 'block moved' })); process.exit(0); }
const escapeHtml = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const fn = new Function('t', 'escapeHtml', `${src.slice(from, to)}; return ${fnName};`)(window.t, escapeHtml);
const html = fn(JSON.parse(input));
console.log(JSON.stringify([...html.matchAll(/<p[^>]*>(.*?)<\/p>/g)].map(m => m[1])));
"""


def _lines(fn: str, value) -> list[str]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    out = subprocess.run(
        [
            node,
            "-e",
            _HARNESS,
            str(ROOT / "app/static/js/app.js"),
            str(ROOT / "app/static/js/i18n.js"),
            str(ROOT / "app/i18n/en.json"),
            fn,
            json.dumps(value),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    result = json.loads(out.stdout)
    assert not isinstance(result, dict), result
    return result


def _key(**status) -> list[str]:
    base = {
        "source": "data",
        "file": None,
        "data_file": "/data/.fernet_key",
        "data_copy": "same",
        "env_same": False,
        "outside": False,
        "removable": False,
    }
    return _lines("encryptionKeyStatusHtml", {**base, **status})


class TestTheKeyCard:
    def test_a_default_install_is_told_its_key_sits_with_the_data(self):
        lines = _key()
        assert len(lines) == 1
        assert "in the data folder (/data/.fernet_key)" in lines[0]
        assert "can decrypt every stored credential" in lines[0]

    def test_the_same_key_in_the_variable_offers_the_way_out(self):
        lines = _key(env_same=True, removable=True)
        assert any("CASHPILOT_ENCRYPTION_KEY holds the same key" in line for line in lines)

    def test_a_key_file_with_a_copy_left_asks_to_delete_the_copy(self):
        lines = _key(source="file", file="/run/secrets/k", removable=True)
        assert "comes from /run/secrets/k, outside the data folder" in lines[0]
        assert "still in the data folder (/data/.fernet_key)" in lines[1]
        assert not any(line.startswith("Done") for line in lines)

    def test_a_finished_move_says_done(self):
        lines = _key(source="file", file="/run/secrets/k", data_copy="none", outside=True)
        assert len(lines) == 2
        assert lines[1].startswith("Done: the data folder holds no copy of the key")

    def test_another_key_left_in_the_folder_is_named_and_kept(self):
        lines = _key(source="file", file="/run/secrets/k", data_copy="different")
        assert any("older key file (/data/.fernet_key) that is not the key in use" in line for line in lines)

    def test_a_path_is_escaped(self):
        lines = _key(source="file", file="/run/<b>")
        assert "/run/&lt;b&gt;" in lines[0]


class TestTheEarnerCredentialsCard:
    def test_no_worker(self):
        assert _lines("earnerSecretsHtml", []) == ["No workers yet."]

    @pytest.mark.parametrize(
        ("mode", "said"),
        [
            ("file", "credentials go in a file"),
            ("env", "credentials go in the container settings"),
            ("unavailable", "this worker image cannot keep credentials in a file"),
            (None, "this worker is too old to say"),
        ],
    )
    def test_each_mode_reads_as_words(self, mode, said):
        [line] = _lines("earnerSecretsHtml", [{"worker": "box", "mode": mode, "in_file": 0, "in_config": 0}])
        assert line.startswith(f"box: {said}.")

    def test_counts_use_plurals(self):
        [one] = _lines("earnerSecretsHtml", [{"worker": "a", "mode": "file", "in_file": 1, "in_config": 0}])
        [many] = _lines("earnerSecretsHtml", [{"worker": "a", "mode": "file", "in_file": 3, "in_config": 2}])
        assert "{" not in one and "{" not in many
        assert one != many
        assert "3" in many and "2" in many

    def test_a_worker_without_counts_says_only_its_setting(self):
        [line] = _lines("earnerSecretsHtml", [{"worker": "mac", "mode": "file", "in_file": None, "in_config": None}])
        assert line == "mac: credentials go in a file. It does not report its earners one by one."
