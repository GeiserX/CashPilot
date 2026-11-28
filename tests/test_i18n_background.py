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


app.router.lifespan_context = _noop_lifespan


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
