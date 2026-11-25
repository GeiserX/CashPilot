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
from html import unescape
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app import catalog

ROOT = Path(__file__).resolve().parent.parent

NO_ACCOUNT = re.compile(r"\bno (?:sign-?up or )?account\b|\bno sign-?up\b", re.I)
NO_ACCOUNT_SLUGS = (
    "anyone-protocol",
    "golem",
    "noderr",
    "proxybase-xyz",
    "sentinel-dvpn",
    "sia-hostd",
    "storj",
)
ACCOUNT_PROMPT = "Already have an account? Enter your credentials below."


@pytest.fixture
def catalog_client():
    from app.main import app

    # Exercise the real HTTP responses without starting background jobs or contacting workers.
    with (
        patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "admin", "r": "owner"}),
        patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]) as deployments,
        patch("app.main._get_all_worker_containers", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.list_worker_specs", new_callable=AsyncMock, return_value=[]),
    ):
        yield TestClient(app), deployments


def _get(client, path):
    response = client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


def _text_fields(value, path=""):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _text_fields(item, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _text_fields(item, f"{path}[{i}]")


def test_account_is_a_boolean_or_absent():
    for svc in catalog.get_services():
        ref = svc.get("referral") or {}
        if "account" in ref:
            assert isinstance(ref["account"], bool), f"{svc['slug']}: referral.account must be a boolean"


def test_every_entry_that_says_no_account_says_it_to_the_code(catalog_client):
    client, _ = catalog_client
    claims = set()
    failures = []
    for svc in _get(client, "/api/services/available"):
        slug = svc["slug"]
        # Text used by the setup and detail cards, including the computed rating.
        card = {
            key: svc.get(key)
            for key in (
                "name",
                "category",
                "description",
                "short_description",
                "platforms",
                "disclosure",
                "rating_result",
                "earnings",
                "payment",
                "cashout",
                "route_refusal",
            )
        }
        docker = svc.get("docker") or {}
        card["docker"] = {key: docker.get(key) for key in ("env", "setup")}
        card["referral"] = {"bonus": (svc.get("referral") or {}).get("bonus")}
        for path, text in _text_fields(card):
            if not NO_ACCOUNT.search(text):
                continue
            claims.add(slug)
            if (svc.get("referral") or {}).get("account") is not False:
                failures.append(f"{slug} {path}: {text!r} requires referral.account: false")
            if "needed at all" in text.lower():
                failures.append(f"{slug} {path}: say what setup needs instead of {text!r}")

    assert not failures, "\n".join(failures)
    assert set(NO_ACCOUNT_SLUGS) <= claims, f"Missing card text for {set(NO_ACCOUNT_SLUGS) - claims}"


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
const { setup, detail } = JSON.parse(process.argv[2]);
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
  setup: fns.renderServiceSetupForm(setup, []),
  detail: fns.renderServiceDetail(detail, []),
}));
"""


def _render(catalog_client, slug: str, deployed: bool) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    client, deployments = catalog_client
    deployments.return_value = [{"slug": slug}] if deployed else []
    setup = next(svc for svc in _get(client, "/api/services/available") if svc["slug"] == slug)
    detail = _get(client, f"/api/services/{slug}")
    assert setup["deployed"] is detail["deployed"] is deployed
    out = subprocess.run(
        [node, "-e", _HARNESS, str(ROOT / "app/static/js/app.js"), json.dumps({"setup": setup, "detail": detail})],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(out.stdout)


def _link_labels(html: str, url: str) -> list[str]:
    """The text of every link to url, tags and whitespace removed."""
    found = [
        label for href, label in re.findall(r'<a href="([^"]*)"[^>]*>(.*?)</a>', html, re.S) if unescape(href) == url
    ]
    assert found, f"no link to {url}"
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m)).strip() for m in found]


@pytest.mark.parametrize("slug", NO_ACCOUNT_SLUGS)
@pytest.mark.parametrize("deployed", [False, True])
def test_no_account_means_visit_not_sign_up(catalog_client, slug, deployed):
    ref = catalog.get_service(slug)["referral"]
    url = ref["signup_url"]
    if slug == "proxybase-xyz":
        assert ref["code"] in url
    out = _render(catalog_client, slug, deployed)
    for view in ("setup", "detail"):
        labels = _link_labels(out[view], url)
        assert not any("sign up" in label.lower() for label in labels), f"{slug} {view}: {labels!r}"
        assert any(label.startswith("Visit") for label in labels), f"{slug} {view}: {labels!r}"
        assert ACCOUNT_PROMPT not in out[view]
        if slug == "proxybase-xyz":
            assert "Referral link:" in out[view]


@pytest.mark.parametrize("deployed", [False, True])
def test_a_provider_with_an_account_keeps_sign_up_and_its_referral_link(catalog_client, deployed):
    svc = catalog.get_service("honeygain")
    url = svc["referral"]["signup_url"]
    assert svc["referral"].get("code") and svc["referral"]["code"] in url
    out = _render(catalog_client, "honeygain", deployed)
    for view in ("setup", "detail"):
        assert any("sign up" in label.lower() for label in _link_labels(out[view], url)), view
    assert ACCOUNT_PROMPT in out["setup"]
