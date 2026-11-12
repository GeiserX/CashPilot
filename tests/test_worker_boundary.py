"""The edges between the UI, its workers and the host (fix lane "worker").

Each test here pins one hole that an audit found open: an address that reaches
the UI's own loopback, an https worker the UI could not reach, a heartbeat
reply that could rekey a worker, a deploy that could bind the compose folder,
and the shared fleet key reading the owner's dashboard.
"""

from __future__ import annotations

import asyncio
import datetime
import functools
import json
import os
import ssl
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

# ---------------------------------------------------------------------------
# The worker-URL guard: unspecified addresses reach the UI's own loopback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://0.0.0.0:8080",
        "http://[::]:8080",
        "http://[::ffff:0.0.0.0]:8080",
        "http://0.1.2.3:8080",
    ],
)
def test_unspecified_worker_address_is_refused(url):
    from app.worker_proxy import _validate_worker_url

    with pytest.raises(HTTPException) as exc:
        _validate_worker_url(url)
    assert exc.value.status_code == 400


def test_hostname_resolving_to_unspecified_is_refused():
    """``http://0:8080`` is not an IP literal; it resolves to 0.0.0.0."""
    from app.worker_proxy import _validate_worker_url

    with (
        patch("app.worker_proxy.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("0.0.0.0", 8080))]),
        pytest.raises(HTTPException) as exc,
    ):
        _validate_worker_url("http://0:8080")
    assert exc.value.status_code == 400


def test_lan_worker_still_accepted():
    from app.worker_proxy import _validate_worker_url

    assert _validate_worker_url("http://192.168.1.50:8081") == ("http://192.168.1.50:8081", None)


# ---------------------------------------------------------------------------
# An https worker named by hostname: pinned IP, TLS checks the name
# ---------------------------------------------------------------------------

_NAME = "worker.cashpilot.test"


def _issue(tmp_path, san: str):
    """A throwaway CA and a server certificate for ``san``. Returns (ca_pem, cert, key)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    now = datetime.datetime.now(datetime.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "cashpilot test CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, san)]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(san)]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    ca_pem = tmp_path / "ca.pem"
    ca_pem.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_pem = tmp_path / "cert.pem"
    cert_pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_pem = tmp_path / "key.pem"
    key_pem.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return ca_pem, cert_pem, key_pem


class _TLSWorker:
    """A real TLS listener on 127.0.0.1 that records the SNI and Host it saw."""

    def __init__(self, cert, key):
        seen: dict[str, str | None] = {}
        self.seen = seen

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server API
                seen["host"] = self.headers.get("Host")
                body = json.dumps({"ok": True}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(cert, key)

        def sni(_sock, name, _ctx):
            seen["sni"] = name

        ctx.sni_callback = sni
        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def _call_https_worker(ca_pem, port):
    import app.main as main

    worker = {"id": 7, "status": "online", "url": f"https://{_NAME}:{port}", "client_id": ""}
    trusting_client = functools.partial(httpx.AsyncClient, verify=ssl.create_default_context(cafile=str(ca_pem)))
    with (
        # The name passed validation and resolved to this IP; the call must go
        # to the IP. 127.0.0.1 stands in for a LAN address here: the real guard
        # refuses loopback, which is what makes this a test of the pinning only.
        patch.object(main, "_validate_worker_url", return_value=(worker["url"], "127.0.0.1")),
        patch.object(main.database, "get_worker", AsyncMock(return_value=worker)),
        patch.object(main.database, "get_worker_key_state", AsyncMock(return_value=(None, False))),
        patch.object(main.httpx, "AsyncClient", trusting_client),
    ):
        return asyncio.run(main._proxy_to_worker(7, "GET", "/api/health"))


def test_https_worker_by_hostname_is_reached_and_verified(tmp_path):
    ca_pem, cert, key = _issue(tmp_path, _NAME)
    with _TLSWorker(cert, key) as srv:
        assert _call_https_worker(ca_pem, srv.port) == {"ok": True}
    assert srv.seen["sni"] == _NAME
    assert srv.seen["host"] == f"{_NAME}:{srv.port}"


def test_https_worker_with_a_certificate_for_another_name_is_refused(tmp_path):
    """The positive control: verification is on and checks the worker's name."""
    ca_pem, cert, key = _issue(tmp_path, "someone-else.cashpilot.test")
    with _TLSWorker(cert, key) as srv, pytest.raises(HTTPException) as exc:
        _call_https_worker(ca_pem, srv.port)
    assert exc.value.status_code == 503


# ---------------------------------------------------------------------------
# A heartbeat reply may hand a key only to a worker still on the shared key
# ---------------------------------------------------------------------------


def _beat(worker_api, reply):
    request = httpx.Request("POST", "http://ui.test:8080/api/workers/heartbeat")
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=httpx.Response(200, request=request, json=reply))
    with (
        patch.object(worker_api, "UI_URL", "http://ui.test:8080"),
        patch("app.worker_api.orchestrator.get_status", return_value=[]),
        patch("app.worker_api.orchestrator.docker_available", return_value=False),
        patch.object(worker_api, "_detect_egress_ip", AsyncMock(return_value=None)),
        patch("app.worker_api.httpx.AsyncClient", return_value=client),
    ):
        asyncio.run(worker_api._send_heartbeat())


def test_enrolled_worker_ignores_a_new_key_in_a_heartbeat_reply(tmp_path):
    from app import worker_api

    with (
        patch.object(worker_api, "_WORKER_KEY_FILE", tmp_path / ".worker_key"),
        patch.object(worker_api, "_worker_key", "own-key"),
    ):
        _beat(worker_api, {"status": "ok", "worker_key": "attacker-key"})
        assert worker_api._worker_key == "own-key"
    assert not (tmp_path / ".worker_key").exists()


def test_worker_on_the_shared_key_still_enrolls(tmp_path):
    from app import worker_api

    with (
        patch.object(worker_api, "_WORKER_KEY_FILE", tmp_path / ".worker_key"),
        patch.object(worker_api, "_worker_key", None),
    ):
        _beat(worker_api, {"status": "ok", "worker_key": "issued-key"})
        assert worker_api._worker_key == "issued-key"
    assert (tmp_path / ".worker_key").read_text() == "issued-key"


# ---------------------------------------------------------------------------
# A deploy may never bind the compose folder
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "/volume1/docker/cashpilot",
        "/volume1/docker/cashpilot/evil",
        "/volume1/docker/./cashpilot",
        # A folder above the compose folder reaches the compose file and its .env too.
        "/volume1/docker",
        "/volume1/docker/",
    ],
)
def test_deploy_cannot_bind_the_compose_folder(monkeypatch, source):
    """On a NAS path no blocked root covers, the proxy roots used to let it through."""
    from app import orchestrator, worker_api

    monkeypatch.setenv("CASHPILOT_COMPOSE_DIR", "/volume1/docker/cashpilot")
    # The proxy roots alone would let every one of these through.
    monkeypatch.setenv("CASHPILOT_PROXY_BIND_MOUNTS", "/volume1/docker")
    monkeypatch.setattr(orchestrator, "proxied", lambda: True)
    spec = worker_api.DeploySpec(image="alpine:3.20", volumes={source: {"bind": "/x", "mode": "rw"}})
    with pytest.raises(HTTPException) as exc:
        worker_api._validate_deploy_spec(spec, "custom")
    assert exc.value.status_code == 403
    assert "compose folder" in exc.value.detail


@pytest.mark.parametrize("compose_dir", ["/volume1/docker/cashpilot/", "/volume1/docker/./cashpilot"])
def test_compose_folder_written_untidily_still_closes_what_is_under_it(monkeypatch, compose_dir):
    """A trailing slash or a dot in the setting must not open the folders under it."""
    from app import orchestrator, worker_api

    monkeypatch.setenv("CASHPILOT_COMPOSE_DIR", compose_dir)
    monkeypatch.setenv("CASHPILOT_PROXY_BIND_MOUNTS", "/volume1/docker")
    monkeypatch.setattr(orchestrator, "proxied", lambda: True)
    spec = worker_api.DeploySpec(
        image="alpine:3.20", volumes={"/volume1/docker/cashpilot/evil": {"bind": "/x", "mode": "rw"}}
    )
    with pytest.raises(HTTPException) as exc:
        worker_api._validate_deploy_spec(spec, "custom")
    assert exc.value.status_code == 403


def test_deploy_may_bind_a_sibling_of_the_compose_folder(monkeypatch):
    """Only the folder itself is closed: a name that merely starts the same is not under it."""
    from app import orchestrator, worker_api

    monkeypatch.setenv("CASHPILOT_COMPOSE_DIR", "/volume1/docker/cashpilot")
    monkeypatch.setenv("CASHPILOT_PROXY_BIND_MOUNTS", "/volume1/docker/cashpilot-data")
    monkeypatch.setattr(orchestrator, "proxied", lambda: True)
    spec = worker_api.DeploySpec(
        image="alpine:3.20", volumes={"/volume1/docker/cashpilot-data": {"bind": "/x", "mode": "rw"}}
    )
    worker_api._validate_deploy_spec(spec, "custom")


# ---------------------------------------------------------------------------
# The shared fleet key enrolls workers; it reads nothing on the dashboard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("guard", ["_require_auth_api", "_require_reader", "_require_writer", "_require_owner"])
def test_fleet_key_is_refused_by_every_dashboard_guard(guard):
    from app import auth, deps

    with (
        patch.object(auth, "get_current_user", return_value={"uid": 0, "u": "fleet", "r": "fleet"}),
        pytest.raises(HTTPException) as exc,
    ):
        getattr(deps, guard)(MagicMock())
    assert exc.value.status_code == 403


def test_fleet_key_reads_no_earnings_over_http(monkeypatch):
    """End to end: a bare Bearer of the shared key gets 403 on a dashboard read."""
    from contextlib import asynccontextmanager

    from fastapi.testclient import TestClient

    from app import fleet_key
    from app.main import app as ui_app

    @asynccontextmanager
    async def _noop(_a):
        yield

    monkeypatch.setattr(fleet_key, "resolve_fleet_key", lambda: "shared-fleet-key")
    ui_app.router.lifespan_context = _noop
    client = TestClient(ui_app, raise_server_exceptions=False)
    for path in ("/api/earnings", "/api/workers", "/api/earnings/payouts"):
        resp = client.get(path, headers={"Authorization": "Bearer shared-fleet-key"})
        assert resp.status_code == 403, (path, resp.status_code)


# ---------------------------------------------------------------------------
# What the images ship: pinned bases, code the app cannot rewrite, private files
# ---------------------------------------------------------------------------

_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("name", ["Dockerfile", "Dockerfile.worker"])
def test_app_code_and_catalog_are_not_owned_by_the_app_user(name):
    """The process runs as cashpilot; owning /app/app and /app/services let it rewrite them."""
    import re

    text = (_ROOT / name).read_text(encoding="utf-8")
    owned = re.findall(r"^COPY --chown=\S+ (?:app/|services/)\S*", text, re.M)
    assert not owned, f"{name} gives the app user its own code: {owned}"


@pytest.mark.parametrize("name", ["Dockerfile", "Dockerfile.worker"])
def test_every_base_image_is_pinned_by_digest(name):
    import re

    text = (_ROOT / name).read_text(encoding="utf-8")
    stages = re.findall(r"^FROM (\S+)", text, re.M)
    assert len(stages) == 3
    assert all("@sha256:" in ref for ref in stages), stages
    # uv comes from a FROM stage Dependabot reads, never a bare image in COPY --from.
    assert not re.search(r"^COPY --from=\S*[:/]", text, re.M)


def test_the_update_helper_is_pinned_by_digest():
    from app import orchestrator

    assert "@sha256:" in orchestrator.UPDATER_IMAGE


def test_entrypoint_sets_a_private_umask_before_any_exec():
    text = (_ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    assert "umask 077" in text
    assert text.index("umask 077") < text.index("exec ")
    assert "chmod 700 /data" in text
