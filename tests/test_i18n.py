"""The web UI's languages (app/i18n): which one a request gets, and its strings.

The browser's formatter runs the same cases in scripts/i18n_format_check.mjs.
Locales other than English are written into a temporary directory here, so
these tests do not depend on which translations have shipped.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import hashlib

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from app import database, i18n
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
SOURCE = json.loads((ROOT / "app/i18n/en.json").read_text(encoding="utf-8"))


@asynccontextmanager
async def _noop_lifespan(a):
    yield


app.router.lifespan_context = _noop_lifespan


@pytest.fixture
def locales(tmp_path, monkeypatch):
    """A locale directory with English plus the given translations.

    Call it with {locale: {key: text}}; each text is stamped with the hash of
    the current English, as a translator's file would be.
    """
    directory = tmp_path / "i18n"
    directory.mkdir()
    (directory / "en.json").write_text(json.dumps(SOURCE), encoding="utf-8")
    monkeypatch.setattr(i18n, "DIR", directory)
    i18n.reload()

    def write(files: dict[str, dict[str, str]]) -> Path:
        for code, entries in files.items():
            stamped = {k: {"text": v, "source": i18n.source_hash(SOURCE[k])} for k, v in entries.items()}
            (directory / f"{code}.json").write_text(json.dumps(stamped, ensure_ascii=False), encoding="utf-8")
        i18n.reload()
        return directory

    yield write
    i18n.reload()


@pytest.fixture
def all_locales(locales):
    """Every locale has a file, each with the picker label translated."""
    return locales({code: {"lang.label": f"Language in {code}"} for code in i18n.NAMES if code != "en"})


# ---------------------------------------------------------------------------
# The list and the files
# ---------------------------------------------------------------------------


def test_the_twenty_locales_of_the_plan():
    assert list(i18n.NAMES) == [
        "en", "es", "pt-BR", "fr", "de", "it", "nl", "pl", "ru", "uk",
        "tr", "ar", "hi", "id", "vi", "th", "fil", "zh-Hans", "ja", "ko",
    ]  # fmt: skip
    assert {"ar"} == i18n.RTL
    assert i18n.NAMES["es"] == "Español" and i18n.NAMES["de"] == "Deutsch"


def test_every_shipped_file_is_a_known_locale_with_known_keys():
    """A file for a locale the UI does not list, or a key English lacks, is a mistake."""
    for path in (ROOT / "app/i18n").glob("*.json"):
        assert path.stem in i18n.NAMES, path.name
        data = json.loads(path.read_text(encoding="utf-8"))
        if path.stem == "en":
            assert all(isinstance(v, str) and v for v in data.values())
            continue
        for key, entry in data.items():
            assert key in SOURCE, f"{path.name}: {key} is not in en.json"
            assert set(entry) == {"text", "source"}, f"{path.name}: {key}"


def test_every_english_message_parses():
    for text in SOURCE.values():
        i18n.parse(text)  # raises on a malformed message


# ---------------------------------------------------------------------------
# Negotiation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("es", "es"),
        ("es-MX", "es"),
        ("ES_es", "es"),
        ("pt-PT", "pt-BR"),
        ("pt", "pt-BR"),
        ("pt-br", "pt-BR"),
        ("zh-TW", "zh-Hans"),
        ("zh-Hant-HK", "zh-Hans"),
        ("zh", "zh-Hans"),
        ("tl", "fil"),
        ("fil-PH", "fil"),
        ("in", "id"),
        ("ar-EG", "ar"),
        ("sv-SE", None),
        ("*", None),
        ("", None),
    ],
)
def test_a_tag_matches_by_language_then_region(all_locales, tag, expected):
    assert i18n.match(tag) == expected


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("es-ES,es;q=0.9,en;q=0.8", "es"),
        ("sv-SE,sv;q=0.9,de;q=0.7,en;q=0.5", "de"),
        ("en;q=0.5,fr;q=0.9", "fr"),
        ("fr;q=0,de", "de"),
        ("sv,nb", None),
        ("", None),
        (None, None),
        ("garbage;;q=abc,ja", "ja"),
    ],
)
def test_accept_language_takes_the_best_match_by_quality(all_locales, header, expected):
    assert i18n.negotiate(header) == expected


def test_the_saved_choice_beats_the_cookie_which_beats_the_header(all_locales):
    assert i18n.resolve("de", "fr", "es") == "de"
    assert i18n.resolve(None, "fr", "es") == "fr"
    assert i18n.resolve(None, None, "es") == "es"
    assert i18n.resolve(None, None, "sv") == "en"
    # A value that is no longer a locale (a file was removed, or set by hand) is skipped.
    assert i18n.resolve("xx", "yy", "es") == "es"


def test_a_locale_without_a_file_is_not_offered_or_matched(locales):
    locales({"es": {"lang.label": "Idioma"}})
    assert i18n.available() == ("en", "es")
    assert i18n.match("de") is None
    assert i18n.resolve("de", None, "de") == "en"
    assert [o["code"] for o in i18n.languages()] == ["en", "es"]


# ---------------------------------------------------------------------------
# Catalogs: English fallback, never a blank
# ---------------------------------------------------------------------------


def test_a_stale_translation_falls_back_to_english(locales):
    directory = locales({"es": {"lang.label": "Idioma", "lang.auto": "Automático"}})
    data = json.loads((directory / "es.json").read_text(encoding="utf-8"))
    data["lang.auto"]["source"] = i18n.source_hash("an older English text")
    (directory / "es.json").write_text(json.dumps(data), encoding="utf-8")
    i18n.reload()
    cat = i18n.catalog("es")
    assert cat["lang.label"] == "Idioma"
    assert cat["lang.auto"] == SOURCE["lang.auto"]


def test_a_missing_or_empty_translation_shows_english(locales):
    directory = locales({"es": {"lang.label": "Idioma"}})
    data = json.loads((directory / "es.json").read_text(encoding="utf-8"))
    data["lang.auto"] = {"text": "", "source": i18n.source_hash(SOURCE["lang.auto"])}
    data["not.a.key"] = {"text": "huérfano", "source": "000000000000"}
    (directory / "es.json").write_text(json.dumps(data), encoding="utf-8")
    i18n.reload()
    cat = i18n.catalog("es")
    assert set(cat) == set(SOURCE)
    assert cat["lang.auto"] == SOURCE["lang.auto"]
    assert cat["lang.not_saved"] == SOURCE["lang.not_saved"]


def test_the_hash_is_the_one_the_parity_check_writes():
    """sha256 of the English text as json.loads returns it, first 12 hex digits."""
    assert i18n.source_hash("Idioma ñ") == hashlib.sha256("Idioma ñ".encode()).hexdigest()[:12]


def test_t_uses_the_current_locale_and_shows_an_unknown_key(locales):
    locales({"es": {"lang.not_saved": "Idioma no guardado: {error}"}})
    i18n.use("es")
    try:
        assert i18n.t("lang.not_saved", error="red") == "Idioma no guardado: red"
        assert i18n.t("no.such.key") == "no.such.key"
    finally:
        i18n.use("en")
    assert i18n.t("lang.not_saved", error="x") == "Language not saved: x"


def test_html_keys_escape_their_values_and_plain_keys_are_escaped_by_jinja(monkeypatch):
    monkeypatch.setattr(i18n, "source", lambda: {"a_html": "Read <a href='/x'>{name}</a>", "b": "{name}"})
    monkeypatch.setattr(i18n, "catalog", lambda locale: i18n.source())
    out = i18n.t("a_html", name="<script>")
    assert str(out) == "Read <a href='/x'>&lt;script&gt;</a>"
    assert hasattr(out, "__html__")
    assert not hasattr(i18n.t("b", name="<i>"), "__html__")


# ---------------------------------------------------------------------------
# Formatting and plurals
# ---------------------------------------------------------------------------


CASES = json.loads((FIXTURES / "i18n_format_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[f"{c['locale']}:{c['message'][:30]}" for c in CASES])
def test_format_cases_shared_with_the_browser(case):
    assert i18n.format_message(case["message"], case["params"], case["locale"]) == case["expected"]


@pytest.mark.parametrize(
    "bad",
    ["{n, plural, one {x}}", "{n, ordinal, other {x}}", "unclosed {name", "stray } brace", "{n, plural, one x}"],
)
def test_a_malformed_message_is_refused(bad):
    with pytest.raises(ValueError):
        i18n.parse(bad)


PLURALS = json.loads((FIXTURES / "i18n_plural_cldr.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("locale", list(PLURALS["categories"]))
def test_plural_rules_match_what_the_browser_answers(locale):
    """The fixture is Intl.PluralRules' answer (Node, CLDR) for each number.

    Regenerate it with the one-liner in its "generated_by" Node version if CLDR
    changes a rule; the server's rules must then follow.
    """
    assert set(PLURALS["categories"]) == set(i18n.NAMES)
    wrong = [
        (n, want, i18n.plural_category(locale, n))
        for n, want in zip(PLURALS["numbers"], PLURALS["categories"][locale], strict=True)
        if i18n.plural_category(locale, n) != want
    ]
    assert not wrong, wrong[:10]


# ---------------------------------------------------------------------------
# Over HTTP
# ---------------------------------------------------------------------------


@pytest.fixture
def real_db(tmp_path):
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"),
    ):
        asyncio.run(database.init_db())
        yield asyncio.run(database.create_user("lang_user", "pw", "viewer"))


def _signed_in(uid, role="viewer"):
    user = {"uid": uid, "u": "lang_user", "r": role}
    return patch("app.main.auth.get_current_user", return_value=user), TestClient(app, raise_server_exceptions=False)


def _html_lang(html):
    m = re.search(r'<html[^>]*\blang="([^"]*)"[^>]*\bdir="([^"]*)"', html)
    return m and (m.group(1), m.group(2))


def test_the_bundle_serves_every_key_with_english_where_untranslated(locales):
    locales({"es": {"lang.label": "Idioma"}})
    with TestClient(app) as c:
        r = c.get("/i18n/es.js")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/javascript")
        payload = json.loads(r.text.removeprefix("window.CP_I18N=").rstrip(";\n"))
        assert payload["lang"] == "es" and payload["dir"] == "ltr"
        assert payload["messages"]["lang.label"] == "Idioma"
        assert payload["messages"]["lang.auto"] == SOURCE["lang.auto"]
        assert set(payload["messages"]) == set(SOURCE)
        again = c.get("/i18n/es.js", headers={"If-None-Match": r.headers["etag"]})
        assert again.status_code == 304
        assert c.get("/i18n/de.js").status_code == 404
        assert c.get("/i18n/..%2fen.js").status_code == 404


def test_the_bundle_cannot_close_its_script_tag(monkeypatch):
    monkeypatch.setattr(i18n, "catalog", lambda locale: {"x": "</script><script>alert(1)</script>"})
    assert "</script>" not in i18n.bundle_js("en")


@pytest.mark.parametrize("page", ["/login", "/onboarding"])
def test_signed_out_pages_follow_the_cookie_then_the_header(tmp_path, all_locales, page):
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"),
    ):
        asyncio.run(database.init_db())
        if page == "/login":
            asyncio.run(database.create_user("someone", "pw", "owner"))
        with TestClient(app, raise_server_exceptions=False) as c:
            spanish = c.get(page, headers={"Accept-Language": "es-ES,es;q=0.9"})
            assert _html_lang(spanish.text) == ("es", "ltr")
            assert '<script src="/i18n/es.js' in spanish.text
            assert "Language in es" in spanish.text  # the picker's label, translated
            arabic = c.get(page, headers={"Accept-Language": "ar"})
            assert _html_lang(arabic.text) == ("ar", "rtl")
            c.cookies.set(i18n.COOKIE, "de")
            assert _html_lang(c.get(page, headers={"Accept-Language": "es"}).text) == ("de", "ltr")
            c.cookies.set(i18n.COOKIE, "xx")
            assert _html_lang(c.get(page, headers={"Accept-Language": "sv"}).text) == ("en", "ltr")


def test_only_english_means_no_picker_and_english_everywhere(tmp_path, locales):
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"),
    ):
        asyncio.run(database.init_db())
        with TestClient(app, raise_server_exceptions=False) as c:
            html = c.get("/onboarding", headers={"Accept-Language": "es"}).text
    assert _html_lang(html) == ("en", "ltr")
    assert "data-lang-choice" not in html


def test_the_saved_choice_wins_and_is_mirrored_into_the_cookie(real_db, all_locales):
    p, c = _signed_in(real_db)
    with p, c:
        assert _html_lang(c.get("/", headers={"Accept-Language": "es"}).text) == ("es", "ltr")
        assert c.post("/api/preferences", json={"language": "ja"}).status_code == 200
        assert c.get("/api/preferences").json()["language"] == "ja"
        c.cookies.clear()
        r = c.get("/fleet", headers={"Accept-Language": "es"})
        assert _html_lang(r.text) == ("ja", "ltr")
        assert re.search(r'<option value="ja"[^>]*selected', r.text)
        assert f"{i18n.COOKIE}=ja" in r.headers.get("set-cookie", "")
        # Automatic clears it: the browser decides again.
        assert c.post("/api/preferences", json={"language": "auto"}).status_code == 200
        assert c.get("/api/preferences").json()["language"] is None
        c.cookies.clear()
        r = c.get("/", headers={"Accept-Language": "es"})
        assert _html_lang(r.text) == ("es", "ltr")
        assert re.search(r'<option value="auto"[^>]*selected', r.text)


def test_other_preferences_keep_the_language(real_db, all_locales):
    p, c = _signed_in(real_db)
    with p, c:
        c.post("/api/preferences", json={"language": "ar"})
        c.post("/api/preferences", json={"theme": "warm"})
        assert c.get("/api/preferences").json()["language"] == "ar"


@pytest.mark.parametrize("bad", ["xx", "ES", "es-MX", "", "<script>"])
def test_an_unknown_language_is_refused(real_db, all_locales, bad):
    p, c = _signed_in(real_db)
    with p, c:
        c.post("/api/preferences", json={"language": "fr"})
        assert c.post("/api/preferences", json={"language": bad}).status_code == 400
        assert c.get("/api/preferences").json()["language"] == "fr"


def test_the_picker_lists_each_language_in_its_own_name(real_db, all_locales):
    p, c = _signed_in(real_db)
    with p, c:
        html = c.get("/").text
    options = re.findall(r'<option value="([^"]+)" lang="[^"]+" dir="(\w+)"[^>]*>([^<]+)</option>', html)
    assert [(code, name) for code, _, name in options] == list(i18n.NAMES.items())
    assert dict((code, d) for code, d, _ in options)["ar"] == "rtl"


def test_an_old_database_gains_the_language_column(tmp_path):
    db_path = tmp_path / "cashpilot.db"

    async def make_old():
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "CREATE TABLE user_preferences (user_id INTEGER PRIMARY KEY, setup_mode TEXT NOT NULL DEFAULT 'fresh',"
                " selected_categories TEXT NOT NULL DEFAULT '[]', timezone TEXT NOT NULL DEFAULT 'UTC',"
                " setup_completed INTEGER NOT NULL DEFAULT 0, theme TEXT,"
                " created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')))"
            )
            await db.execute("INSERT INTO user_preferences (user_id, theme) VALUES (7, 'warm')")
            await db.commit()

    async def columns():
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("PRAGMA table_info(user_preferences)")
            cols = {row[1] for row in await cursor.fetchall()}
            cursor = await db.execute("SELECT theme, language FROM user_preferences WHERE user_id = 7")
            return cols, await cursor.fetchone()

    asyncio.run(make_old())
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", db_path),
    ):
        asyncio.run(database.init_db())
    cols, row = asyncio.run(columns())
    assert "language" in cols
    assert row == ("warm", None)


def test_a_message_shown_in_english_counts_in_english(tmp_path, monkeypatch):
    """French puts 0 in "one"; an untranslated plural on a French page must still say "0 boxes"."""
    directory = tmp_path / "i18n"
    directory.mkdir()
    plural = "{n, plural, one {# box} other {# boxes}}"
    (directory / "en.json").write_text(json.dumps({"p": plural, "q": plural}), encoding="utf-8")
    fr = {"q": {"text": "{n, plural, one {# boîte} other {# boîtes}}", "source": i18n.source_hash(plural)}}
    (directory / "fr.json").write_text(json.dumps(fr), encoding="utf-8")
    monkeypatch.setattr(i18n, "DIR", directory)
    i18n.reload()
    try:
        i18n.use("fr")
        assert i18n.t("p", n=0) == "0 boxes"
        assert i18n.t("q", n=0) == "0 boîte"
        payload = json.loads(i18n.bundle_js("fr").removeprefix("window.CP_I18N=").rstrip(";\n"))
        assert payload["fallback"] == ["p"]
        assert json.loads(i18n.bundle_js("en").removeprefix("window.CP_I18N=").rstrip(";\n"))["fallback"] == []
    finally:
        i18n.use("en")
        i18n.reload()


def test_a_preference_read_that_fails_still_renders_the_page_and_says_so(real_db, caplog):
    patched, c = _signed_in(real_db)
    broken = patch("app.routers.pages.database.get_user_preferences", side_effect=RuntimeError("db gone"))
    with patched, broken, c, caplog.at_level("WARNING", logger="app.routers.pages"):
        page = c.get("/")
    assert page.status_code == 200
    assert "Could not read the saved preferences" in caplog.text and "db gone" not in caplog.text


# ---------------------------------------------------------------------------
# Server messages: API errors, and the worker's answers through the dashboard
# ---------------------------------------------------------------------------


def test_an_api_error_comes_in_the_language_of_the_page(locales, real_db):
    locales({"es": {"api.role_must_viewer_writer_owner": "El rol debe ser viewer, writer u owner"}})
    patched, c = _signed_in(real_db, "owner")
    with patched, c:
        body = {"role": "boss"}
        c.cookies.set(i18n.COOKIE, "es")
        spanish = c.patch(f"/api/users/{real_db}", json=body)
        assert spanish.status_code == 400, spanish.text
        assert spanish.json()["detail"] == "El rol debe ser viewer, writer u owner"
        c.cookies.delete(i18n.COOKIE)
        assert (
            c.patch(f"/api/users/{real_db}", json=body).json()["detail"] == SOURCE["api.role_must_viewer_writer_owner"]
        )


def test_the_worker_answers_in_the_language_it_is_asked_in(locales, monkeypatch):
    from app import worker_api

    locales({"es": {"worker.invalid_api_key": "Clave de API no válida"}})
    monkeypatch.setattr(worker_api, "_active_key", lambda: "right-key")
    c = TestClient(worker_api.app, raise_server_exceptions=False)
    wrong = {"Authorization": "Bearer wrong-key"}
    spanish = c.get("/api/containers", headers={**wrong, "Accept-Language": "es"})
    assert spanish.status_code == 401 and spanish.json()["detail"] == "Clave de API no válida"
    assert c.get("/api/containers", headers=wrong).json()["detail"] == SOURCE["worker.invalid_api_key"]


def test_the_dashboard_asks_the_worker_in_the_language_of_the_page(monkeypatch):
    import contextvars
    from unittest.mock import AsyncMock

    import httpx

    import app.main as main

    sent: list[dict[str, str]] = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None, headers=None, **kwargs):
            sent.append(dict(headers))
            return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(main.httpx, "AsyncClient", Client)
    monkeypatch.setattr(main.database, "get_worker", AsyncMock(return_value={"id": 1, "status": "online"}))
    verified = AsyncMock(return_value=("http://192.168.1.5:8081", {"Authorization": "Bearer k"}))
    monkeypatch.setattr(main, "_get_verified_worker_url", verified)

    def call(locale: str) -> None:
        i18n.use(locale)
        asyncio.run(main._proxy_to_worker(1, "GET", "/api/containers"))

    contextvars.copy_context().run(call, "es")
    contextvars.copy_context().run(call, "en")
    assert [h["Accept-Language"] for h in sent] == ["es", "en"]
    assert all(h["Authorization"] == "Bearer k" for h in sent)
