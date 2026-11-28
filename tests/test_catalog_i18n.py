"""The catalog translations (services/_i18n/) and their loader in app/catalog.py.

The service files stay English. Translations sit beside them, keyed
"<slug>.<path>", each with the hash of the English it translates, and the UI
shows English whenever a translation is missing, empty or stale.
"""

import importlib.util
import pathlib
import re

import pytest

from app import catalog

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


i18n_check = _script("i18n_check")

SERVICE = {
    "slug": "demo",
    "status": "active",
    "description": "Share your bandwidth.\n",
    "short_description": "Bandwidth sharing",
    "website": "https://demo.example",
    "docker": {
        "image": "demo/demo:1.0",
        "env": [
            {"key": "DEMO_EMAIL", "label": "Email", "description": "Your demo login"},
            {"key": "DEMO_TOKEN", "label": "Token"},
        ],
        "health_signals": [{"pattern": "login failed", "means": "Login failed on ${WORKER_NAME}."}],
    },
    "payment": {"minimum_payout": "$5", "frequency": "Weekly"},
    "obligations": [{"id": "withdraw-yearly", "title": "Withdraw yearly", "how": "Open the dashboard."}],
    "rating": {"cons": [{"text": "Slow support."}], "notes": {"support": "Not shown in the UI."}},
}


@pytest.mark.parametrize(
    ("tag", "want"),
    [
        ("es", "es"),
        ("es-MX", "es"),
        ("pt-PT", "pt-BR"),
        ("pt", "pt-BR"),
        ("zh-TW", "zh-Hans"),
        ("zh_CN", "zh-Hans"),
        ("ZH-HANS", "zh-Hans"),
        ("tl", "fil"),
        ("in", "id"),
        ("en-GB", "en"),
        ("xx", "en"),
        ("", "en"),
        (None, "en"),
    ],
)
def test_match_locale(tag, want):
    assert catalog.match_locale(tag) == want


@pytest.mark.parametrize(
    ("header", "want"),
    [
        ("es-ES,es;q=0.9,en;q=0.8", "es"),
        ("xx-YY, de;q=0.5", "de"),
        ("en-US,en;q=0.9,fr;q=0.8", "en"),
        ("fr;q=0.2, ja;q=0.7", "ja"),
        ("*", "en"),
        ("", "en"),
        (None, "en"),
    ],
)
def test_negotiate_locale(header, want):
    assert catalog.negotiate_locale(header) == want


def test_translatable_strings_name_list_items_by_their_key():
    strings = catalog.translatable_strings(SERVICE)
    assert strings == {
        "demo.description": "Share your bandwidth.\n",
        "demo.short_description": "Bandwidth sharing",
        "demo.docker.env.DEMO_EMAIL.label": "Email",
        "demo.docker.env.DEMO_EMAIL.description": "Your demo login",
        "demo.docker.env.DEMO_TOKEN.label": "Token",
        "demo.docker.health_signals.0.means": "Login failed on ${WORKER_NAME}.",
        "demo.payment.frequency": "Weekly",  # "$5" has no letters, so nothing to translate
        "demo.obligations.withdraw-yearly.title": "Withdraw yearly",
        "demo.obligations.withdraw-yearly.how": "Open the dashboard.",
        "demo.rating.cons.0.text": "Slow support.",
    }


@pytest.fixture
def es_table(tmp_path, monkeypatch):
    d = tmp_path / "_i18n"
    d.mkdir()
    h = catalog.i18n_source_hash
    (d / "es.yml").write_text(
        f'demo.description:\n  text: "Comparte tu ancho de banda."\n  source: "{h("Share your bandwidth.\n")}"\n'
        f'demo.short_description:\n  text: "Viejo"\n  source: "000000000000"\n'
        f'demo.docker.env.DEMO_EMAIL.label:\n  text: ""\n  source: "{h("Email")}"\n'
        f'demo.docker.health_signals.0.means:\n  text: "Error de acceso en ${{WORKER_NAME}}."\n'
        f'  source: "{h("Login failed on ${WORKER_NAME}.")}"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(catalog, "I18N_DIR", d)
    catalog._i18n_tables.clear()
    yield
    catalog._i18n_tables.clear()


def test_translate_falls_back_to_english_unless_fresh(es_table):
    assert catalog.translate("demo.description", "Share your bandwidth.\n", "es-MX") == "Comparte tu ancho de banda."
    assert catalog.translate("demo.short_description", "Bandwidth sharing", "es") == "Bandwidth sharing"  # stale
    assert catalog.translate("demo.docker.env.DEMO_EMAIL.label", "Email", "es") == "Email"  # empty
    assert catalog.translate("demo.payment.frequency", "Weekly", "es") == "Weekly"  # missing
    assert catalog.translate("demo.description", "Share your bandwidth.\n", "en") == "Share your bandwidth.\n"
    assert catalog.translate("demo.description", "Share your bandwidth.\n", "de") == "Share your bandwidth.\n"


def test_localized_service_is_a_translated_copy(es_table):
    out = catalog.localized_service(SERVICE, "es")
    assert out["description"] == "Comparte tu ancho de banda."
    assert out["docker"]["health_signals"][0]["means"] == "Error de acceso en ${WORKER_NAME}."
    assert out["docker"]["health_signals"][0]["pattern"] == "login failed"
    assert out["short_description"] == "Bandwidth sharing"
    assert SERVICE["description"] == "Share your bandwidth.\n"  # the cached original is untouched


def test_the_hash_matches_the_parity_check():
    for text in ("Email", "Share your bandwidth.\n", "日本語 ${X}"):
        assert catalog.i18n_source_hash(text) == i18n_check.source_hash(text)


def test_i18n_files_are_not_service_entries():
    assert not catalog.is_service_file(catalog.SERVICES_DIR / "_i18n" / "es.yml")
    assert not catalog.is_service_file(catalog.SERVICES_DIR / "_schema.yml")
    assert catalog.is_service_file(catalog.SERVICES_DIR / "bandwidth" / "iproyal.yml")
    assert "es" not in {s["slug"] for s in catalog.get_services()}


def test_en_yml_matches_the_catalog_and_every_locale_has_a_file():
    assert _script("catalog_i18n").main(["--check"]) == 0


def test_every_locale_translates_every_catalog_string(capsys):
    files = sorted((catalog.SERVICES_DIR / "_i18n").glob("*.yml"))
    code = i18n_check.main([str(catalog.SERVICES_DIR / "_i18n" / "en.yml"), *map(str, files)])
    assert code == 0, capsys.readouterr().out[-4000:]


# Locales that write the decimal mark as a comma, so "1,000" reads as one.
COMMA_DECIMAL = ("es", "pt-BR", "fr", "de", "it", "nl", "pl", "ru", "uk", "tr", "id", "vi")
# 1,000 or 12,500 or 300,000: thousands grouped with a comma, not part of an
# address list such as 127.0.0.1,172.18.0.1.
ENGLISH_THOUSANDS = re.compile(r"(?<![\d.,])\d{1,3}(?:,\d{3})+(?![\d.,]*\d)")


@pytest.mark.parametrize("locale", COMMA_DECIMAL)
def test_numbers_use_the_locales_thousands_separator(locale):
    entries, _ = i18n_check.load(catalog.SERVICES_DIR / "_i18n" / f"{locale}.yml", "catalog", False)
    wrong = {key: ENGLISH_THOUSANDS.findall(text) for key, text in entries.items() if isinstance(text, str)}
    assert not {k: v for k, v in wrong.items() if v}, f"{locale}: write 1000 or 12.500 or 12 500, never 12,500"


def test_the_thousands_check_finds_a_comma_and_skips_an_address_list():
    assert ENGLISH_THOUSANDS.findall("desde $1,000 y 12,500 FLUX") == ["1,000", "12,500"]
    assert ENGLISH_THOUSANDS.findall("127.0.0.1,172.18.0.1 y 1.000 y 0,5") == []
