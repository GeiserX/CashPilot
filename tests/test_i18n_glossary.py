"""The product glossary (i18n/glossary.yml) has a word for every term in every locale.

Every surface translates with this file, so a term missing in one locale means
that surface's translator picks a word on their own, and Desktop and the web
UI end up with two names for one thing.
"""

import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
GLOSSARY = yaml.safe_load((ROOT / "i18n" / "glossary.yml").read_text(encoding="utf-8"))

# The 19 target locales of the i18n plan, as BCP 47 tags.
LOCALES = [
    "es",
    "pt-BR",
    "fr",
    "de",
    "it",
    "nl",
    "pl",
    "ru",
    "uk",
    "tr",
    "ar",
    "hi",
    "id",
    "vi",
    "th",
    "fil",
    "zh-Hans",
    "ja",
    "ko",
]


def test_every_term_has_every_locale():
    terms = GLOSSARY["terms"]
    assert len(terms) >= 40
    for tid, term in terms.items():
        assert set(term) == {"en", "kind", "note", *LOCALES}, tid
        assert all(isinstance(v, str) and v.strip() for v in term.values()), tid
        assert term["kind"] in ("term", "brand"), tid


def test_brand_terms_keep_the_english_word():
    for tid, term in GLOSSARY["terms"].items():
        if term["kind"] == "brand":
            assert all(term[loc] == term["en"] for loc in LOCALES), tid


def test_core_terms_of_the_plan_are_there():
    for tid in (
        "earner",
        "worker",
        "fleet",
        "secure-vm",
        "claim",
        "cash-out",
        "payout",
        "referral",
        "heartbeat",
        "fence",
    ):
        assert tid in GLOSSARY["terms"], tid
