"""The catalog's own words reach the UI in the reader's language.

services/_i18n/<locale>.yml holds the translations of each service's
description, setup notes, variable labels, obligations and device-link steps.
The services API, the obligations panel and the bell read them through
catalog.localized_service, in the page's language or, with no request, in the
owner's.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import catalog, i18n, main, obligations
from app.collectors.earnapp import EarnAppCollector
from tests.test_device_id_masking import EARNAPP_ID, _collect_once

ROOT = Path(__file__).resolve().parent.parent
OWNER = {"uid": 1, "u": "admin", "r": "owner"}

HONEYGAIN = catalog.get_service("honeygain")
EARNAPP = catalog.get_service("earnapp")
RULE = HONEYGAIN["obligations"][0]
SPANISH = {
    "honeygain.description": (HONEYGAIN["description"], "Comparte tu ancho de banda sin usar."),
    f"honeygain.obligations.{RULE['id']}.title": (RULE["title"], "Retira antes de que caduque"),
    "earnapp.device_link.steps": (EARNAPP["device_link"]["steps"], "Abre este enlace con tu sesión de EarnApp."),
}


@asynccontextmanager
async def _noop_lifespan(a):
    yield


@pytest.fixture
def spanish(tmp_path, monkeypatch):
    """The web UI ships Spanish, and the catalog has three fresh Spanish strings."""
    ui = tmp_path / "i18n"
    ui.mkdir()
    source = json.loads((ROOT / "app/i18n/en.json").read_text(encoding="utf-8"))
    (ui / "en.json").write_text(json.dumps(source), encoding="utf-8")
    stamped = {"lang.label": {"text": "Idioma", "source": i18n.source_hash(source["lang.label"])}}
    (ui / "es.json").write_text(json.dumps(stamped, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(i18n, "DIR", ui)
    i18n.reload()

    services = tmp_path / "_i18n"
    services.mkdir()
    table = {
        key: {"text": text, "source": catalog.i18n_source_hash(english)} for key, (english, text) in SPANISH.items()
    }
    (services / "es.yml").write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(catalog, "I18N_DIR", services)
    catalog._i18n_tables.clear()
    yield
    catalog._i18n_tables.clear()
    i18n.reload()


def _get(path: str, language: str):
    main.app.router.lifespan_context = _noop_lifespan
    with (
        patch("app.main.auth.get_current_user", return_value=OWNER),
        patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
        patch("app.main._get_all_worker_containers", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_custom_images", new_callable=AsyncMock, return_value={}),
        patch("app.main.database.list_worker_specs", new_callable=AsyncMock, return_value=[]),
        TestClient(main.app, raise_server_exceptions=False) as c,
    ):
        c.cookies.set(i18n.COOKIE, language)
        response = c.get(path)
    assert response.status_code == 200, response.text
    return response.json()


def _honeygain(body):
    return next(s for s in body if s["slug"] == "honeygain") if isinstance(body, list) else body


@pytest.mark.parametrize("path", ["/api/services", "/api/services/available", "/api/services/honeygain"])
def test_the_services_api_answers_in_the_pages_language(spanish, path):
    spanish_page = _honeygain(_get(path, "es"))
    assert spanish_page["description"] == "Comparte tu ancho de banda sin usar."
    assert spanish_page["obligations"][0]["title"] == "Retira antes de que caduque"
    # A string with no fresh translation keeps its English.
    assert spanish_page["short_description"] == HONEYGAIN["short_description"]

    english_page = _honeygain(_get(path, "en"))
    assert english_page["description"] == HONEYGAIN["description"]
    # The cached catalog itself stays English.
    assert catalog.get_service("honeygain")["description"] == HONEYGAIN["description"]


def test_the_obligations_read_the_catalog_in_the_owners_language(spanish):
    seen: dict[str, list] = {}

    def evaluate(services, facts, state, today):
        seen["services"] = services
        return obligations.Evaluation()

    async def run():
        with (
            patch("app.main._obligations_now", new_callable=AsyncMock, return_value=datetime.now(UTC)),
            patch("app.main._obligation_facts", new_callable=AsyncMock, return_value={}),
            patch("app.main.database.get_obligation_state", new_callable=AsyncMock, return_value={}),
            patch("app.main.obligations.evaluate", MagicMock(side_effect=evaluate)),
        ):
            await main._evaluate_obligations()

    i18n.set_background("es")
    contextvars.Context().run(asyncio.run, run())
    honeygain = next(s for s in seen["services"] if s["slug"] == "honeygain")
    assert honeygain["obligations"][0]["title"] == "Retira antes de que caduque"


def test_the_bell_shows_the_device_link_steps_in_the_owners_language(spanish, caplog):
    i18n.set_background("es")
    notices, _stored, _push = contextvars.Context().run(
        _collect_once, "earnapp", EarnAppCollector(oauth_token="t"), EARNAPP_ID, caplog
    )
    assert notices and notices[0]["device_steps"] == "Abre este enlace con tu sesión de EarnApp."
