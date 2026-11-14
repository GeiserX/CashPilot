"""An unlinked device's id never leaves the owner's bell (issue #740).

EarnApp and ProxyRack pay the account a device is linked to, so while it is
unlinked its id claims its earnings for whoever adds it first. The notice that
says a device is unlinked used to carry the full id and the EarnApp claim link,
and that one string went to the log, the alerts table, the bell of every role,
the read-only dashboard feed and the ntfy, Telegram and webhook pushes. Now every
one of those gets a masked suffix and no link; the owner's bell alone carries
the full id and the link, beside the notice.

The per-node earnings route names each Mysterium node's identity and LAN
address, so it is owner only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main, notify  # noqa: E402
from app.collectors.base import EarningsResult  # noqa: E402
from app.collectors.earnapp import EarnAppCollector  # noqa: E402
from app.collectors.proxyrack import ProxyRackCollector  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EARNAPP_ID = "sdk-node-" + "0123456789abcdef" * 2
PROXYRACK_ID = "f" * 60 + "9a8b"

OWNER = {"uid": 1, "u": "admin", "r": "owner"}
WRITER = {"uid": 2, "u": "writer", "r": "writer"}
VIEWER = {"uid": 3, "u": "viewer", "r": "viewer"}
READER = {"uid": 0, "u": "api", "r": "reader"}


@asynccontextmanager
async def _noop_lifespan(a):
    yield


@pytest.fixture
def client():
    main.app.router.lifespan_context = _noop_lifespan
    with TestClient(main.app, raise_server_exceptions=False) as c:
        yield c


# --------------------------------------------------------------------------
# The mask itself, and the backstop in notify.redact
# --------------------------------------------------------------------------


def test_the_mask_keeps_only_a_short_suffix():
    assert notify.mask_device_id(EARNAPP_ID) == "...cdef"
    assert notify.mask_device_id(PROXYRACK_ID) == "...9a8b"
    # Too short to cut safely: nothing of it is shown.
    assert notify.mask_device_id("abcd1234") == "..."
    assert notify.mask_device_id("") == "..."


def test_redact_masks_an_earnapp_id_and_drops_its_claim_link_in_any_text():
    text = notify.redact(f"device {EARNAPP_ID} failed; add it at https://earnapp.com/r/{EARNAPP_ID} now")
    assert EARNAPP_ID not in text and "earnapp.com/r/" not in text
    assert "...cdef" in text and "<link in CashPilot>" in text


def test_redact_leaves_other_hex_alone():
    # A digest or a Mysterium address is not a claim token; the backstop
    # matches only the EarnApp shapes.
    digest = "sha256:" + "a" * 64
    addr = "0x" + "b" * 40
    assert notify.redact(f"{digest} {addr}") == f"{digest} {addr}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("env", "body_of"),
    [
        ({"CASHPILOT_NTFY_URL": "https://ntfy.sh/topic"}, lambda kw: kw["content"].decode()),
        ({"CASHPILOT_WEBHOOK_URL": "https://example.com/hook"}, lambda kw: json.dumps(kw["json"])),
        (
            {"CASHPILOT_TELEGRAM_BOT_TOKEN": "tok", "CASHPILOT_TELEGRAM_CHAT_ID": "42"},
            lambda kw: json.dumps(kw["json"]),
        ),
    ],
    ids=["ntfy", "webhook", "telegram"],
)
async def test_no_push_channel_gets_an_earnapp_id_or_claim_link(env, body_of):
    http = MagicMock()
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=False)
    http.post = AsyncMock(return_value=MagicMock(status_code=200))
    cleared = {
        "CASHPILOT_NTFY_URL": "",
        "CASHPILOT_WEBHOOK_URL": "",
        "CASHPILOT_TELEGRAM_BOT_TOKEN": "",
        "CASHPILOT_TELEGRAM_CHAT_ID": "",
    }
    with patch.dict(os.environ, {**cleared, **env}), patch("app.notify.httpx.AsyncClient", return_value=http):
        assert await notify.send(f"CashPilot: {EARNAPP_ID}", f"Open https://earnapp.com/r/{EARNAPP_ID}") == 1
    body = body_of(http.post.call_args.kwargs) + json.dumps(http.post.call_args.kwargs.get("headers") or {})
    assert EARNAPP_ID not in body and "earnapp.com/r/" not in body
    assert "...cdef" in body


# --------------------------------------------------------------------------
# The collection loop: log, alerts table, push, bell entry
# --------------------------------------------------------------------------


def _collect_once(slug: str, collector, device_id: str, caplog):
    collector.collect = AsyncMock(return_value=EarningsResult(platform=slug, balance=1.0, unlinked_devices=[device_id]))
    push = MagicMock(return_value=None)
    with (
        patch("app.main._collector_alerts", []),
        patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[{"slug": slug}]),
        patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
        patch("app.collectors.make_collectors", return_value=[collector]),
        patch("app.collectors._close_stale", new_callable=AsyncMock),
        patch("app.main.database.get_deployed_env_values", new_callable=AsyncMock, return_value={device_id}),
        patch("app.main.database.list_pending_device_links", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.record_alert", new_callable=AsyncMock, return_value=7) as record,
        patch("app.main.database.clear_alerts", new_callable=AsyncMock),
        patch("app.main.database.upsert_earnings", new_callable=AsyncMock),
        patch("app.main._detect_payout", new_callable=AsyncMock, return_value=None),
        patch("app.main._pending_payout_alerts", new_callable=AsyncMock, return_value=[]),
        patch("app.main._flatline_check", new_callable=AsyncMock, return_value=[]),
        patch("app.main._offline_worker_alerts", new_callable=AsyncMock, return_value=[]),
        patch("app.main._push_alert", push),
        patch("app.main._spawn"),
        caplog.at_level(logging.INFO, logger="app.main"),
    ):
        asyncio.run(main._run_collection())
        alerts = list(main._collector_alerts)
    notices = [a for a in alerts if a.get("kind") == "notice" and a["platform"] == slug]
    stored = [c.args for c in record.await_args_list if c.args[0] == "notice"]
    return notices, stored, push


@pytest.mark.parametrize(
    ("slug", "make", "device_id", "masked", "url"),
    [
        (
            "earnapp",
            lambda: EarnAppCollector(oauth_token="t"),
            EARNAPP_ID,
            "...cdef",
            f"https://earnapp.com/r/{EARNAPP_ID}",
        ),
        ("proxyrack", lambda: ProxyRackCollector(api_key="k"), PROXYRACK_ID, "...9a8b", "https://peer.proxyrack.com"),
    ],
)
def test_the_loop_masks_the_id_in_every_sink_and_keeps_it_for_the_owner(slug, make, device_id, masked, url, caplog):
    notices, stored, push = _collect_once(slug, make(), device_id, caplog)

    (notice,) = notices
    # The bell text every role reads, and the read-only feed's collector_notice.
    assert device_id not in notice["error"] and masked in notice["error"]
    assert "earnapp.com" not in notice["error"]
    # The alerts table.
    ((_, _, message),) = stored
    assert device_id not in message and masked in message
    # The push (ntfy, Telegram, webhook all get this one message).
    (call,) = push.call_args_list
    assert all(device_id not in str(arg) for arg in call.args)
    # The container log.
    assert device_id not in caplog.text
    # Beside the notice, in memory only, for the owner's bell.
    assert notice["devices"] == [{"id": device_id, "masked": masked, "url": url}]
    assert notice["device_steps"]


# --------------------------------------------------------------------------
# The bell API: the full id and link for the owner only
# --------------------------------------------------------------------------


_NOTICE = {
    "kind": "notice",
    "platform": "earnapp",
    "error": "A deployed device is not on your EarnApp account and earns for nobody: ...cdef.",
    "devices": [{"id": EARNAPP_ID, "masked": "...cdef", "url": f"https://earnapp.com/r/{EARNAPP_ID}"}],
    "device_steps": "Open this link while signed in to EarnApp.",
}


def _bell(client, user):
    with (
        patch("app.main._collector_alerts", [dict(_NOTICE)]),
        patch("app.main.auth.get_current_user", return_value=user),
    ):
        return client.get("/api/collector-alerts")


def test_the_owners_bell_has_the_full_id_and_link(client):
    resp = _bell(client, OWNER)
    assert resp.status_code == 200
    (entry,) = resp.json()["alerts"]
    assert entry["devices"] == _NOTICE["devices"]
    assert entry["device_steps"] == _NOTICE["device_steps"]


@pytest.mark.parametrize("user", [WRITER, VIEWER], ids=["writer", "viewer"])
def test_no_other_role_gets_the_full_id_or_link(client, user):
    resp = _bell(client, user)
    assert resp.status_code == 200
    (entry,) = resp.json()["alerts"]
    assert "devices" not in entry and "device_steps" not in entry
    assert EARNAPP_ID not in resp.text and "earnapp.com" not in resp.text
    assert "...cdef" in entry["error"]


def test_the_read_only_key_still_cannot_read_the_bell(client):
    assert _bell(client, READER).status_code == 403


# --------------------------------------------------------------------------
# Per-node earnings: owner only
# --------------------------------------------------------------------------


def _per_node(client, user):
    collector = MagicMock()
    collector.get_per_node_earnings = AsyncMock(
        return_value=[{"identity": "0x" + "c" * 40, "local_ip": "192.0.2.5", "earnings_myst": 1.0}]
    )
    collector.close = AsyncMock()
    with (
        patch("app.main.auth.get_current_user", return_value=user),
        patch(
            "app.main.database.get_config",
            new_callable=AsyncMock,
            return_value={"mysterium_email": "a@b.c", "mysterium_password": "p"},
        ),
        patch("app.collectors.build_one", return_value=(collector, [])),
    ):
        return client.get("/api/services/mysterium/per-node-earnings")


def test_the_owner_reads_per_node_earnings(client):
    resp = _per_node(client, OWNER)
    assert resp.status_code == 200
    assert resp.json()[0]["identity"] == "0x" + "c" * 40


@pytest.mark.parametrize("user", [WRITER, VIEWER, READER], ids=["writer", "viewer", "reader"])
def test_no_other_role_reads_per_node_earnings(client, user):
    resp = _per_node(client, user)
    assert resp.status_code == 403
    assert "192.0.2.5" not in resp.text and "0x" + "c" * 40 not in resp.text


# --------------------------------------------------------------------------
# The bell's rendering, run in node against the real app.js
# --------------------------------------------------------------------------

_HARNESS = r"""
const src = require('fs').readFileSync(process.argv[process.argv.length - 3], 'utf8');
const from = src.indexOf('  function notifyDevicesHtml(a) {');
const to = src.indexOf('  async function loadCollectorAlerts() {');
if (from < 0 || to <= from) { console.log(JSON.stringify({error: 'block moved'})); process.exit(0); }
const escapeHtml = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
const isOwner = process.argv[process.argv.length - 2] === 'owner';
const fn = new Function('escapeHtml', '_isOwner', `${src.slice(from, to)}; return notifyDevicesHtml;`)(escapeHtml, isOwner);
console.log(JSON.stringify({ html: fn(JSON.parse(process.argv[process.argv.length - 1])) }));
"""


def _render(alert: dict, role: str) -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    out = subprocess.run(
        [node, "-e", _HARNESS, str(ROOT / "app/static/js/app.js"), role, json.dumps(alert)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    result = json.loads(out.stdout)
    assert "error" not in result, result
    return result["html"]


def test_the_owners_bell_shows_the_full_id_and_an_add_link():
    html = _render(_NOTICE, "owner")
    assert f"<code>{EARNAPP_ID}</code>" in html
    assert f'href="https://earnapp.com/r/{EARNAPP_ID}"' in html
    assert 'rel="noopener noreferrer"' in html


def test_a_non_owner_page_renders_nothing_even_if_handed_devices():
    assert _render(_NOTICE, "viewer") == ""


def test_a_link_that_is_not_https_is_not_rendered_and_values_are_escaped():
    alert = {**_NOTICE, "devices": [{"id": "<b>x</b>", "masked": "...", "url": "javascript:alert(1)"}]}
    html = _render(alert, "owner")
    assert "href" not in html and "javascript:" not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html
