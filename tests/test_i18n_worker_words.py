"""A worker older than its translations answers in English, whatever language it is asked in.

The UI reads some of a worker's answers by their words ("not found" means a
first deploy). Those words must count in the page's language and in English.
"""

from __future__ import annotations

import contextvars
import json
from pathlib import Path

import pytest

from app import i18n, main

ROOT = Path(__file__).resolve().parent.parent
SOURCE = json.loads((ROOT / "app/i18n/en.json").read_text(encoding="utf-8"))
KEY = "err.orchestrator.container_not_found"
SPANISH = "No se encontró el contenedor de {slug}"


@pytest.fixture
def spanish(tmp_path, monkeypatch):
    directory = tmp_path / "i18n"
    directory.mkdir()
    (directory / "en.json").write_text(json.dumps(SOURCE), encoding="utf-8")
    stamped = {KEY: {"text": SPANISH, "source": i18n.source_hash(SOURCE[KEY])}}
    (directory / "es.json").write_text(json.dumps(stamped, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(i18n, "DIR", directory)
    i18n.reload()
    yield
    i18n.reload()


def _on_a_spanish_page(fn, *args, **kwargs):
    def run():
        i18n.use("es")
        return fn(*args, **kwargs)

    return contextvars.Context().run(run)


def test_a_worker_answer_counts_in_the_page_language_and_in_english(spanish):
    english = i18n.format_message(SOURCE[KEY], {"slug": "honeygain"})
    spanish_text = "No se encontró el contenedor de honeygain"
    assert _on_a_spanish_page(i18n.t, KEY, slug="honeygain") == spanish_text
    assert _on_a_spanish_page(main._worker_says, spanish_text, KEY, slug="honeygain")
    assert _on_a_spanish_page(main._worker_says, english, KEY, slug="honeygain")
    assert not _on_a_spanish_page(main._worker_says, english, KEY, slug="mysterium")
    assert not _on_a_spanish_page(main._worker_says, "Internal error", KEY, slug="honeygain")
