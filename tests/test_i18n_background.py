"""The language of what CashPilot writes with no request: alerts, the bell, the pushes.

A scheduler job has no page to take a language from. It writes in the owner's
language: the one of the owner's last page, kept in the config table so that a
restart keeps it.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import database, i18n, main
from app.main import app

ROOT = Path(__file__).resolve().parent.parent
SOURCE = json.loads((ROOT / "app/i18n/en.json").read_text(encoding="utf-8"))
SPANISH = {
    "lang.label": "Idioma",
    "alert.title.stopped": "CashPilot: {name} dejó de funcionar",
    "alert.title.collector_auth": "CashPilot: el recolector de {name} falló (credencial rechazada)",
}


@asynccontextmanager
async def _noop_lifespan(a):
    yield


@pytest.fixture(autouse=True)
def _no_startup(monkeypatch):
    """These tests need no scheduler or database startup, and other modules keep theirs."""
    monkeypatch.setattr(app.router, "lifespan_context", _noop_lifespan)


@pytest.fixture
def spanish(tmp_path, monkeypatch):
    directory = tmp_path / "i18n"
    directory.mkdir()
    (directory / "en.json").write_text(json.dumps(SOURCE), encoding="utf-8")
    stamped = {k: {"text": v, "source": i18n.source_hash(SOURCE[k])} for k, v in SPANISH.items()}
    (directory / "es.json").write_text(json.dumps(stamped, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(i18n, "DIR", directory)
    i18n.reload()
    yield
    i18n.reload()


@pytest.fixture
def real_db(tmp_path):
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"),
    ):
        asyncio.run(database.init_db())
        yield asyncio.run(database.create_user("lang_user", "pw", "owner"))


def _page_as(role: str, uid: int, language: str) -> int:
    user = {"uid": uid, "u": "lang_user", "r": role}
    with (
        patch("app.main.auth.get_current_user", return_value=user),
        TestClient(app, raise_server_exceptions=False) as c,
    ):
        c.cookies.set(i18n.COOKIE, language)
        return c.get("/").status_code


def _no_request(fn, *args, **kwargs):
    """Run ``fn`` the way a scheduler job does: in a context no request has touched."""
    return contextvars.Context().run(fn, *args, **kwargs)


def test_an_owner_page_sets_the_background_language_and_stores_it(spanish, real_db):
    assert _page_as("owner", real_db, "es") == 200
    assert i18n.background() == "es"
    assert asyncio.run(database.get_config(i18n.BACKGROUND_KEY)) == "es"


@pytest.mark.parametrize("role", ["viewer", "writer"])
def test_another_role_leaves_the_background_language_alone(spanish, real_db, role):
    assert _page_as(role, real_db, "es") == 200
    assert i18n.background() == i18n.SOURCE
    assert asyncio.run(database.get_config(i18n.BACKGROUND_KEY)) is None


def test_the_background_language_comes_back_after_a_restart(spanish, real_db):
    asyncio.run(database.set_config(i18n.BACKGROUND_KEY, "es"))
    assert i18n.background() == i18n.SOURCE
    asyncio.run(main._restore_background_locale())
    assert i18n.background() == "es"


def test_a_stored_language_that_is_no_longer_shipped_falls_back_to_english(spanish, real_db):
    asyncio.run(database.set_config(i18n.BACKGROUND_KEY, "xx"))
    i18n.set_background("es")
    asyncio.run(main._restore_background_locale())
    assert i18n.background() == i18n.SOURCE


def test_an_alert_is_written_in_the_owners_language(spanish):
    assert _no_request(main._collector_failed_title, "honeygain", "auth") == (
        "CashPilot: honeygain collector failed (credential rejected)"
    )
    assert i18n.set_background("es") is True
    assert i18n.set_background("es") is False  # unchanged: nothing to store again
    assert _no_request(main._collector_failed_title, "honeygain", "auth") == (
        "CashPilot: el recolector de honeygain falló (credencial rechazada)"
    )
    assert _no_request(i18n.t, "alert.title.stopped", name="mysterium") == "CashPilot: mysterium dejó de funcionar"


def test_a_page_keeps_its_own_language_whatever_the_background(spanish):
    i18n.set_background("es")

    def in_a_request():
        i18n.use("en")
        return i18n.t("alert.title.stopped", name="mysterium")

    assert _no_request(in_a_request) == "CashPilot: mysterium has stopped running"


def _detached_locale(cookie: str | None, accept_language: str | None) -> str:
    """The locale a handler sees for a request with these headers."""
    seen = {}

    async def endpoint(scope, receive, send):
        seen["locale"] = i18n.current()
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    headers = []
    if cookie:
        headers.append((b"cookie", f"{i18n.COOKIE}={cookie}".encode()))
    if accept_language:
        headers.append((b"accept-language", accept_language.encode()))

    async def go():
        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(message):
            pass

        await i18n.LocaleMiddleware(endpoint)({"type": "http", "headers": headers}, receive, send)

    _no_request(asyncio.run, go())
    return seen["locale"]


def test_a_request_that_names_no_language_still_gets_english(spanish):
    """API clients (the MCP server, Desktop's server join) send no language and match on English errors."""
    i18n.set_background("es")
    assert _detached_locale(None, None) == "en"
    assert _detached_locale(None, "xx-YY") == "en"
    assert _detached_locale("es", None) == "es"
    assert _detached_locale(None, "es-ES,es;q=0.9") == "es"


def test_an_alert_raised_inside_a_request_is_in_the_owners_language(spanish):
    """A worker's heartbeat raises alerts, and they are the owner's whatever the request's language."""
    i18n.set_background("es")

    @i18n.owner_text
    async def alert():
        return i18n.t("alert.title.stopped", name="mysterium")

    async def in_a_request():
        i18n.use("en")
        text = await alert()
        return text, i18n.t("alert.title.stopped", name="mysterium")

    assert _no_request(asyncio.run, in_a_request()) == (
        "CashPilot: mysterium dejó de funcionar",
        "CashPilot: mysterium has stopped running",
    )


def test_every_function_that_raises_an_alert_writes_owner_text():
    """A new alert check that forgets the decorator would write in the request's language."""
    import ast

    tree = ast.parse((ROOT / "app/main.py").read_text(encoding="utf-8"))
    missing = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        called = {
            c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", None)
            for c in ast.walk(node)
            if isinstance(c, ast.Call)
        }
        if called & {"record_alert", "_push_alert"} and node.name != "_push_alert":
            decorators = {ast.unparse(d) for d in node.decorator_list}
            if "i18n.owner_text" not in decorators:
                missing.append(node.name)
    assert missing == []


def test_work_a_request_spawns_writes_in_the_background_language(spanish):
    """A collection that a page starts must not keep that page's language."""
    i18n.set_background("es")

    async def in_a_request():
        i18n.use("en")

        async def job():
            return i18n.t("alert.title.stopped", name="mysterium")

        return await main._spawn(job())

    assert _no_request(asyncio.run, in_a_request()) == "CashPilot: mysterium dejó de funcionar"


def test_a_failed_store_is_tried_again_on_the_next_owner_page(spanish, real_db):
    with patch.object(database, "set_config", side_effect=RuntimeError("disk full")):
        assert _page_as("owner", real_db, "es") == 200
    assert i18n.background() == i18n.SOURCE
    assert asyncio.run(database.get_config(i18n.BACKGROUND_KEY)) is None
    assert _page_as("owner", real_db, "es") == 200
    assert i18n.background() == "es"
    assert asyncio.run(database.get_config(i18n.BACKGROUND_KEY)) == "es"


@pytest.fixture
def marked(tmp_path, monkeypatch):
    """A locale "es" whose every message is the English between « and »."""
    directory = tmp_path / "i18n"
    directory.mkdir()
    (directory / "en.json").write_text(json.dumps(SOURCE), encoding="utf-8")
    stamped = {k: {"text": f"«{v}»", "source": i18n.source_hash(v)} for k, v in SOURCE.items()}
    (directory / "es.json").write_text(json.dumps(stamped, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(i18n, "DIR", directory)
    i18n.reload()
    i18n.set_background("es")
    yield
    i18n.reload()


def _all_marked(text: str) -> bool:
    import re

    return bool(re.fullmatch(r"«[^«»]*»( «[^«»]*»)*", text))


def test_every_machine_economics_verdict_is_in_the_owners_language(marked):
    from app import machine_economics as me

    heat = {"source": "resistive", "months": [11, 12, 1]}
    cases = [
        dict(monthly_gross=4.0, watts=65.0, price_per_kwh=None),
        dict(monthly_gross=4.0, watts=None, price_per_kwh=0.2),
        dict(monthly_gross=0.0, watts=65.0, price_per_kwh=None),
        dict(monthly_gross=1.0, watts=100.0, price_per_kwh=0.2, dedicated=True),
        dict(monthly_gross=1.0, watts=100.0, price_per_kwh=0.2),
        dict(monthly_gross=1.0, watts=100.0, price_per_kwh=0.2, heat=heat, heating_share=0.5),
        dict(monthly_gross=4.0, watts=25.0, price_per_kwh=0.2),
        dict(monthly_gross=50.0, watts=25.0, price_per_kwh=0.2),
        dict(monthly_gross=4.0, watts=65.0, price_per_kwh=0.2, metered=False),
        dict(monthly_gross=None, watts=65.0, price_per_kwh=0.2),
    ]
    machines = [_no_request(me.assess_machine, name="rig", **case) for case in cases]
    for case, out in zip(cases, machines, strict=True):
        assert _all_marked(out["summary"]), (case, out["summary"])
    assert {m["verdict"] for m in machines} >= {me.UNKNOWN, me.LOSING_MONEY, me.MARGINAL, me.PROFITABLE, me.NOT_METERED}
    assert _all_marked(_no_request(me.fleet_summary, machines)["summary"])
    known = [m for m in machines if m["monthly_cost"] is not None]
    assert _all_marked(_no_request(me.fleet_summary, known)["summary"])


def test_the_offline_worker_bell_entry_is_in_the_owners_language(marked):
    workers = [{"name": "nas", "status": "offline", "last_heartbeat": "2026-11-28 03:00:00", "client_id": "c1"}]
    with patch.object(database, "list_workers", return_value=workers):
        entries = _no_request(asyncio.run, main._offline_worker_alerts())
    assert _all_marked(entries[0]["error"])
    assert "2026-11-28 03:00:00" in entries[0]["error"]
