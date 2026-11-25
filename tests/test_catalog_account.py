"""A provider with no account to sign up for must not get a Sign Up button.

Anyone Protocol's card said "No account is needed at all" under Account rules,
next to a button that said Sign Up (Create account on Desktop), a required
Relay fingerprints field and a warning that rewards need 100 ANYONE locked for
180 days in a wallet. A reader looked for an account form that does not exist.

The catalog now says it in a field the code reads, `referral.account: false`,
and the setup form and the detail dialog label the link Visit for those
entries. The link itself is still signup_url, character for character.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app import catalog

ROOT = Path(__file__).resolve().parent.parent

# How account_rules says there is no account: "no account", "no signup or
# account", "no sign-up", "there is no account in the usual sense".
NO_ACCOUNT = re.compile(r"\bno (?:sign-?up or )?account\b|\bno sign-?up\b", re.I)


def _services():
    return [s for s in catalog.get_services() if not s.get("custom")]


def test_account_is_a_boolean_or_absent():
    for svc in _services():
        ref = svc.get("referral") or {}
        assert ref.get("account", None) in (None, False, True), (
            f"{svc['slug']}: referral.account must be true, false or absent"
        )


def test_every_entry_that_says_no_account_says_it_to_the_code():
    for svc in _services():
        rules = (svc.get("disclosure") or {}).get("account_rules") or ""
        if NO_ACCOUNT.search(rules):
            assert (svc.get("referral") or {}).get("account") is False, (
                f"{svc['slug']}: account_rules says there is no account, but referral.account is not false, "
                "so the UI offers a Sign Up button for an account that does not exist"
            )


def test_an_entry_without_an_account_does_not_say_one_is_needed_at_all_while_needing_a_wallet():
    """The Anyone text said no account "at all" while a wallet with a stake is required."""
    for svc in _services():
        if (svc.get("referral") or {}).get("account") is False:
            rules = (svc.get("disclosure") or {}).get("account_rules") or ""
            assert rules.strip(), f"{svc['slug']}: no account, so account_rules must say what is needed instead"
            assert "needed at all" not in rules, f"{svc['slug']}: {rules}"


# ---------------------------------------------------------------------------
# The real functions from app.js, run in node against real catalog entries.
# ---------------------------------------------------------------------------

_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function grab(name) {
  const at = src.indexOf(`function ${name}(`);
  if (at < 0) throw new Error('missing ' + name);
  let depth = 0, i = src.indexOf(') {', at) + 2;
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}' && --depth === 0) break;
  }
  return src.slice(at, i + 1);
}
const { svc, deployed } = JSON.parse(process.argv[2]);
svc.deployed = deployed;
// Every helper the two renderers call that is not under test renders nothing.
const stubs = {
  escapeHtml: (t) => String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
  capFirst: (t) => String(t || ''),
  _isOwner: true, _detailWorkers: [], wizardState: { deployed: [] },
};
const env = new Proxy(stubs, {
  has: (t, k) => typeof k === 'string' && !(k in globalThis),
  get: (t, k) => (k in t ? t[k] : () => ''),
});
const names = ['hasAccount', 'referralNote', 'renderServiceSetupForm', 'renderServiceDetail'];
const fns = new Function('env', `with (env) { ${names.map(grab).join('\n')}\nreturn { ${names.join(', ')} }; }`)(env);
console.log(JSON.stringify({
  setup: fns.renderServiceSetupForm(svc, []),
  detail: fns.renderServiceDetail(svc, []),
}));
"""


def _render(slug: str, deployed: bool = False) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    svc = catalog.get_service(slug)
    assert svc, slug
    out = subprocess.run(
        [node, "-e", _HARNESS, str(ROOT / "app/static/js/app.js"), json.dumps({"svc": svc, "deployed": deployed})],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(out.stdout)


def _link_labels(html: str, url: str) -> list[str]:
    """The text of every link to url, tags and whitespace removed."""
    found = re.findall(rf'<a href="{re.escape(url)}"[^>]*>(.*?)</a>', html, re.S)
    assert found, f"no link to {url}"
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m)).strip() for m in found]


@pytest.mark.parametrize("slug", ["anyone-protocol", "sia-hostd", "noderr"])
@pytest.mark.parametrize("deployed", [False, True])
def test_no_account_means_visit_not_sign_up(slug, deployed):
    url = catalog.get_service(slug)["referral"]["signup_url"]
    out = _render(slug, deployed)
    for view in ("setup", "detail"):
        labels = _link_labels(out[view], url)
        assert not any("sign up" in label.lower() for label in labels), f"{slug} {view}: {labels!r}"
        assert any(label.startswith("Visit") for label in labels), f"{slug} {view}: {labels!r}"


@pytest.mark.parametrize("deployed", [False, True])
def test_a_provider_with_an_account_keeps_sign_up_and_its_referral_link(deployed):
    svc = catalog.get_service("honeygain")
    url = svc["referral"]["signup_url"]
    assert svc["referral"].get("code") and svc["referral"]["code"] in url
    out = _render("honeygain", deployed)
    for view in ("setup", "detail"):
        assert any("sign up" in label.lower() for label in _link_labels(out[view], url)), view
