"""No key goes over plain http to a host that is not provably private.

The worker sends its key to CASHPILOT_UI_URL on every heartbeat, and the UI
sends a worker's own key with every command. That key deploys containers on
the worker. Over plain http to a public host anyone on the path reads it.
Desktop (internal/upstream/serverurl.go) and Android (ServerUrlPolicy) already
refuse that for their server URL; app/cleartext.py is the same rule, and these
vectors are Desktop's own (serverurl_test.go), minus its cloud-metadata cases,
which are an SSRF rule of Desktop's and not part of the plain-http rule.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import cleartext, worker_api, worker_proxy  # noqa: E402

ALLOWED = [
    # https to any host.
    "https://cashpilot.example.com",
    "https://203.0.113.10:8443",
    "https://localhost:8080",
    "https://8.8.8.8",
    "HTTPS://cashpilot.example.com",
    # http only where it cannot cross the internet.
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://[::1]:8080",
    "http://192.168.1.10:8080",
    "http://10.0.0.5",
    "http://172.20.0.2",
    "http://172.16.0.1",
    "http://172.31.255.254",
    "http://169.254.10.20",
    "http://100.64.0.1",
    "http://100.101.102.103",
    "http://100.127.255.254",
    "http://[fd12:3456::1]",
    "http://[fc00::1]",
    "http://[fe80::1]",
    "http://[::ffff:192.168.1.10]",
    "http://nas.local:8080",
    "http://nas.local.:8080",
    "http://cashpilot.lan",
    "http://box.home.arpa",
    "http://ui.internal",
    "http://box.tailnet-x.ts.net:8080",
    "http://nas",
    "http://cashpilot-ui:8080",
    "HTTP://192.168.1.10:8080",
    "http://user:pass@192.168.1.10:8080",
]

REFUSED = [
    # plain http to a public host would send the key in clear text.
    "http://cashpilot.example.com",
    "http://203.0.113.10",
    "http://8.8.8.8",
    "http://172.32.0.1",
    "http://100.128.0.1",
    "http://192.169.1.1",
    "http://[::ffff:8.8.8.8]",
    "http://[2001:db8::1]",
    "http://134744072",  # dotless number: 8.8.8.8 to the resolver
    "http://0x08080808",
    "http://010.0.0.1",  # not canonical
    "http://8%2e8%2e8%2e8",  # percent-encoded dots are not decoded, so refused
    "http://cash_pilot:8080",  # not a valid host name
    "http://.local",
    "http://ts.net",
    "http://nas.local.example.com",
    "http://user:pass@cashpilot.example.com",
    # never a key target at all.
    "ftp://192.168.1.10",
    "http://",
    "192.168.1.10:8080",
    "",
]


@pytest.mark.parametrize("url", ALLOWED)
def test_bearer_allowed(url):
    assert cleartext.bearer_allowed(url)


@pytest.mark.parametrize("url", REFUSED)
def test_bearer_refused(url):
    assert not cleartext.bearer_allowed(url)


def test_the_private_suffixes_match_desktop_and_android():
    """The lists live in three repos; a fourth suffix here alone would be a fork."""
    assert cleartext.PRIVATE_SUFFIXES == (".local", ".lan", ".home.arpa", ".internal", ".ts.net")


# ---------------------------------------------------------------------------
# The worker: CASHPILOT_UI_URL
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


@pytest.fixture
def worker_state():
    saved = (
        worker_api._ui_connected,
        worker_api._last_error,
        worker_api._consecutive_heartbeat_failures,
        worker_api._ui_url_refusal_logged,
    )
    worker_api._ui_url_refusal_logged = False
    yield
    (
        worker_api._ui_connected,
        worker_api._last_error,
        worker_api._consecutive_heartbeat_failures,
        worker_api._ui_url_refusal_logged,
    ) = saved


def test_worker_sends_no_heartbeat_to_a_public_http_ui(worker_state, caplog):
    client = MagicMock()
    with (
        patch.object(worker_api, "UI_URL", "http://cashpilot.example.com:8080"),
        patch.object(worker_api.httpx, "AsyncClient", return_value=client) as made,
        patch.object(worker_api.orchestrator, "get_status", return_value=[]),
        patch.object(worker_api.orchestrator, "docker_available", return_value=False),
        patch.object(worker_api, "_detect_egress_ip", AsyncMock(return_value="198.51.100.7")),
        patch.object(worker_api.lan_fence, "set_egress_ip", return_value=False) as fenced,
    ):
        asyncio.run(worker_api._send_heartbeat())
        asyncio.run(worker_api._send_heartbeat())
    made.assert_not_called()
    # The fence still follows the public IP while the heartbeat is refused.
    fenced.assert_called_with("198.51.100.7")
    assert worker_api._ui_connected is False
    assert "CASHPILOT_UI_URL is plain http:// to cashpilot.example.com" in worker_api._last_error
    assert "https://" in worker_api._last_error
    assert worker_api._consecutive_heartbeat_failures >= 2
    # Logged once, with the fix, not once a minute.
    refusals = [r for r in caplog.records if "CASHPILOT_UI_URL is plain http://" in r.getMessage()]
    assert len(refusals) == 1
    assert refusals[0].levelname == "ERROR"


def test_a_refused_worker_still_reads_its_proxied_copies(worker_state):
    """That read is the only retry of a half-done proxied-copy move after start.

    The refusal blocks the POST to the UI, never this box's own upkeep.
    """
    with (
        patch.object(worker_api, "UI_URL", "http://cashpilot.example.com:8080"),
        patch.object(worker_api.httpx, "AsyncClient") as made,
        patch.object(worker_api.orchestrator, "get_status", return_value=[]),
        patch.object(worker_api.orchestrator, "docker_available", return_value=True),
        patch.object(worker_api.orchestrator, "docker_unreachable_for", return_value=None),
        patch.object(worker_api, "_detect_egress_ip", AsyncMock(return_value=None)),
        patch.object(worker_api.lan_fence, "set_egress_ip", return_value=False),
        patch.object(worker_api.proxy_tunnel, "status", return_value=[]) as proxied,
    ):
        asyncio.run(worker_api._send_heartbeat())
    proxied.assert_called_once()
    made.assert_not_called()
    assert "CASHPILOT_UI_URL is plain http://" in worker_api._last_error


@pytest.mark.parametrize("url", ["http://cashpilot-ui:8080", "http://100.64.0.9:8080", "https://ui.example.com"])
def test_worker_heartbeats_to_a_private_or_https_ui(worker_state, url):
    resp = httpx.Response(200, request=httpx.Request("POST", url), json={})
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    with (
        patch.object(worker_api, "UI_URL", url),
        patch.object(worker_api.httpx, "AsyncClient", return_value=client),
        patch.object(worker_api.orchestrator, "get_status", return_value=[]),
        patch.object(worker_api.orchestrator, "docker_available", return_value=False),
        patch.object(worker_api, "_detect_egress_ip", AsyncMock(return_value=None)),
    ):
        asyncio.run(worker_api._send_heartbeat())
    client.post.assert_awaited_once()
    assert client.post.await_args.args[0] == f"{url}/api/workers/heartbeat"


def test_worker_health_and_status_page_say_why(worker_state):
    worker_api.app.router.lifespan_context = _noop_lifespan
    client = TestClient(worker_api.app, raise_server_exceptions=False)
    worker_api._consecutive_heartbeat_failures = 0
    with patch.object(worker_api, "UI_URL", "http://203.0.113.7:8080"):
        health = client.get("/api/health")
        worker_api._last_error = worker_api._ui_url_refusal() or ""
        worker_api._ui_connected = False
        with patch.object(worker_api.orchestrator, "get_status_cached", return_value=[]):
            page = client.get("/", headers={"Authorization": f"Bearer {worker_api._active_key()}"})
    assert health.status_code == 503
    assert health.json()["status"] == "degraded"
    assert "CASHPILOT_UI_URL is plain http:// to a host" in health.json()["error"]
    assert "https://" in health.json()["error"]
    # /api/health answers without a key, so it does not say where the UI is.
    assert "203.0.113.7" not in health.text
    assert page.status_code == 200
    assert "plain http:// to 203.0.113.7" in page.text


def test_worker_health_is_ok_for_a_private_ui(worker_state):
    worker_api.app.router.lifespan_context = _noop_lifespan
    client = TestClient(worker_api.app, raise_server_exceptions=False)
    worker_api._consecutive_heartbeat_failures = 0
    with patch.object(worker_api, "UI_URL", "http://192.168.1.10:8080"):
        health = client.get("/api/health")
    assert health.status_code == 200


# ---------------------------------------------------------------------------
# The UI: the URL a worker advertised
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", ["http://203.0.113.10:8081", "http://worker.example.com:8081"])
def test_ui_sends_nothing_to_a_public_http_worker(url):
    with patch.object(worker_proxy.socket, "getaddrinfo") as resolve, pytest.raises(HTTPException) as caught:
        worker_proxy._validate_worker_url(url)
    assert caught.value.status_code == 400
    assert "CASHPILOT_WORKER_URL" in caught.value.detail
    assert "https://" in caught.value.detail
    # Refused from the literal host, before any DNS lookup.
    resolve.assert_not_called()


def test_ui_refuses_a_public_http_worker_in_strict_mode_too():
    with (
        patch.object(worker_proxy, "_WORKER_URL_POLICY", "strict"),
        patch.object(worker_proxy, "_WORKER_ALLOWED_CIDRS", [worker_proxy.ipaddress.ip_network("203.0.113.0/24")]),
        pytest.raises(HTTPException) as caught,
    ):
        worker_proxy._validate_worker_url("http://203.0.113.10:8081")
    assert "plain http://" in caught.value.detail


@pytest.mark.parametrize(
    "url",
    ["http://192.168.1.10:8081", "http://100.100.1.2:8081", "http://[fd00::5]:8081", "https://203.0.113.10:8081"],
)
def test_ui_still_reaches_private_and_https_workers(url):
    safe, pinned = worker_proxy._validate_worker_url(url)
    assert safe == url
    assert pinned is None


def test_ui_reaches_a_private_name_worker():
    with patch.object(worker_proxy.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("192.168.1.20", 8081))]):
        safe, pinned = worker_proxy._validate_worker_url("http://nas.local:8081")
    assert safe == "http://nas.local:8081"
    assert pinned == "192.168.1.20"


def test_plain_http_refusal_names_no_userinfo():
    text = worker_proxy.plain_http_refusal("http://user:hunter2@worker.example.com:8081")
    assert text and "hunter2" not in text and "worker.example.com" in text
    assert worker_proxy.plain_http_refusal("https://worker.example.com") is None
    assert worker_proxy.plain_http_refusal("http://10.1.1.1:8081") is None


def test_an_unparseable_worker_url_does_not_break_the_fleet_list():
    text = worker_proxy.plain_http_refusal("http://[")
    assert text and "cannot be parsed" in text
