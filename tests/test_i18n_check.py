"""The locale parity check (scripts/i18n_check.py).

Every CashPilot repo copies this script unchanged, so these tests pin what it
promises: it fails on a missing key and on a placeholder mismatch, only warns
on stale and extra keys, and reads JSON, YAML, Android strings.xml and the
catalog _i18n format the same way.
"""

import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "i18n_check.py"

_spec = importlib.util.spec_from_file_location("i18n_check", SCRIPT)
ic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ic)


def run(*args):
    proc = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def write(path: pathlib.Path, text: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- The check fails when it should -----------------------------------------


def test_missing_key_fails_and_complete_file_passes(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"a": "Hello", "b": {"c": "Bye {name}"}}))
    good = write(tmp_path / "es.json", json.dumps({"a": "Hola", "b": {"c": "Adiós {name}"}}))
    broken = write(tmp_path / "fr.json", json.dumps({"a": "Bonjour"}))

    code, out = run(en, good)
    assert code == 0, out

    code, out = run(en, good, broken)
    assert code == 1, out
    assert "missing     b.c" in out


def test_empty_translation_counts_as_missing(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"a": "Hello"}))
    es = write(tmp_path / "es.json", json.dumps({"a": "  "}))
    code, out = run(en, es)
    assert code == 1 and "missing     a" in out


def test_placeholder_mismatch_fails(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"a": "Hi {name}, you have %d boxes"}))
    es = write(tmp_path / "es.json", json.dumps({"a": "Hola {nombre}, tienes %d cajas"}))
    code, out = run(en, es)
    assert code == 1
    assert "placeholder a: source %1$d, {name}; target %1$d, {nombre}" in out


def test_extra_key_only_warns_unless_strict(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"a": "Hello"}))
    es = write(tmp_path / "es.json", json.dumps({"a": "Hola", "old": "Viejo"}))
    code, out = run(en, es)
    assert code == 0 and "extra       old" in out
    code, _ = run(en, es, "--strict")
    assert code == 1


def test_target_equal_to_source_is_skipped(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"a": "Hello"}))
    es = write(tmp_path / "es.json", json.dumps({"a": "Hola"}))
    code, out = run(en, en, es)
    assert code == 0 and "1 target(s)" in out


def test_parse_error_exits_2(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"a": "Hello"}))
    es = write(tmp_path / "es.json", "{not json")
    code, _ = run(en, es)
    assert code == 2


# --- Placeholders --------------------------------------------------------------


@pytest.mark.parametrize(
    ("src", "tgt"),
    [
        ("Hello {name}", "Hola {name}"),
        ("%s of %d", "%2$d de %1$s"),  # reordered with positions
        ("%(count)s files", "%(count)s archivos"),
        ("{{count}} boxes", "{{ count }} cajas"),
        ("Login failed on ${WORKER_NAME}", "Error en ${WORKER_NAME}"),
        ("Open {url}", "Ouvrez l'adresse {url}"),  # an apostrophe before a letter is text
        ("Use '{literal}' here", "Usa '{literal}' aquí"),  # quoted braces are text
        (
            "{n, plural, one {# box} other {# boxes}}",
            "{n, plural, one {# коробка} few {# коробки} many {# коробок} other {# коробки}}",
        ),
        ("{n, plural, one {# box} other {# boxes}}", "{n, plural, other {#個の箱}}"),
        ("{kind, select, worker {a worker} other {a box}}", "{kind, select, worker {un worker} other {una caja}}"),
        ("{amount, number, ::currency/USD}", "{amount, number, ::currency/USD}"),
        ("50% done", "50 % hecho"),
        ("100%% sure", "100%% seguro"),
    ],
)
def test_placeholders_that_match(src, tgt):
    assert ic.placeholders(src) == ic.placeholders(tgt), (ic.placeholders(src), ic.placeholders(tgt))


@pytest.mark.parametrize(
    ("src", "tgt"),
    [
        ("Hello {name}", "Hola"),
        ("Hello {name}", "Hola {name"),  # broken braces
        ("%s of %d", "%d de %s"),  # swapped without positions changes the types
        ("%s", "%d"),
        ("Login failed on ${WORKER_NAME}", "Error en ${HOST_ADDRESS}"),
        ("{n, plural, one {# box} other {# boxes}}", "{n, plural, one {# caja}}"),  # no other
        ("{n, plural, one {# box} other {# boxes}}", "{n} cajas"),
        ("{kind, select, worker {a worker} other {a box}}", "{kind, select, obrero {un worker} other {una caja}}"),
        ("{n, number}", "{n}"),
        ("{n, plural, other {{who} has # boxes}}", "{n, plural, other {# cajas}}"),  # nested arg lost
    ],
)
def test_placeholders_that_differ(src, tgt):
    assert ic.placeholders(src) != ic.placeholders(tgt)


def test_plural_needs_other_even_when_source_and_target_agree(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"a": "{n, plural, one {# box} other {# boxes}}"}))
    es = write(tmp_path / "es.json", json.dumps({"a": "{n, plural, one {# caja} other {# cajas}}"}))
    assert run(en, es)[0] == 0
    write(es, json.dumps({"a": "{n, plural, one {# caja} many {# cajas}}"}))
    code, out = run(en, es)
    assert code == 1 and "no 'other' branch" in out


# --- Formats ----------------------------------------------------------------------


def test_yaml_nested_and_rails_root(tmp_path):
    en = write(tmp_path / "en.yml", "en:\n  menu:\n    fleet: Fleet\n    help: 'Open {page}'\n")
    de = write(tmp_path / "de.yml", 'de:\n  menu:\n    fleet: Flotte\n    help: "Öffne {page}"\n')
    assert ic.load(en, "auto", False)[0] == {"menu.fleet": "Fleet", "menu.help": "Open {page}"}
    assert run(en, de)[0] == 0


def test_android_strings_arrays_plurals(tmp_path):
    res = tmp_path / "res"
    en = write(
        res / "values" / "strings.xml",
        """<resources>
  <string name="app_name" translatable="false">CashPilot</string>
  <string name="hello">Hello %1$s, <b>welcome</b></string>
  <string-array name="tabs"><item>Earnings</item><item>Fleet</item></string-array>
  <plurals name="boxes"><item quantity="one">%d box</item><item quantity="other">%d boxes</item></plurals>
</resources>""",
    )
    ru = write(
        res / "values-ru" / "strings.xml",
        """<resources>
  <string name="hello">Привет %1$s, <b>добро пожаловать</b></string>
  <string-array name="tabs"><item>Доход</item><item>Парк</item></string-array>
  <plurals name="boxes"><item quantity="one">%d сервер</item><item quantity="few">%d сервера</item>
    <item quantity="many">%d серверов</item><item quantity="other">%d сервера</item></plurals>
</resources>""",
    )
    entries, _ = ic.load(en, "auto", False)
    assert set(entries) == {"hello", "tabs[0]", "tabs[1]", "boxes"}
    assert entries["hello"] == "Hello %1$s, <b>welcome</b>"
    assert ic.locale_of(ru, "android") == "ru"
    assert ic.locale_of(res / "values-pt-rBR" / "strings.xml", "android") == "pt-BR"
    assert ic.locale_of(res / "values-b+zh+Hans" / "strings.xml", "android") == "zh-Hans"
    assert run(en, ru)[0] == 0

    write(ru, ru.read_text(encoding="utf-8").replace('<item quantity="other">%d сервера</item>', ""))
    code, out = run(en, ru)
    assert code == 1 and "no 'other' form" in out


def test_i18next_plural_families(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"files_one": "{{count}} file", "files_other": "{{count}} files"}))
    ru = write(
        tmp_path / "ru.json",
        json.dumps(
            {
                "files_one": "{{count}} файл",
                "files_few": "{{count}} файла",
                "files_many": "{{count}} файлов",
                "files_other": "{{count}} файла",
            }
        ),
    )
    code, out = run(en, ru)
    assert code == 0 and "extra" in out  # without the flag the few/many forms look extra
    code, out = run(en, ru, "--i18next-plurals")
    assert code == 0 and "extra" not in out.split("\n")[0]


def test_locale_from_dir_when_stem_is_not_a_tag(tmp_path):
    assert ic.locale_of(tmp_path / "locales" / "fr" / "common.json", "json") == "fr"
    assert ic.locale_of(tmp_path / "pt-BR.json", "json") == "pt-BR"
    assert ic.locale_of(tmp_path / "zh-Hans.yml", "yaml") == "zh-Hans"
    assert ic.locale_of(tmp_path / "fil.yml", "yaml") == "fil"


# --- The YAML subset parser agrees with PyYAML ---------------------------------------


@pytest.mark.parametrize(
    "doc",
    [
        "a: plain text\nb: 'it''s quoted'\nc: \"tab\\tand \\u00e9\"\n",
        "# comment\na:\n  b:\n    c: deep  # trailing comment\n  d: x\ne: y\n",
        "a: |\n  line one\n  line two\nb: next\n",
        "a: |-\n  kept\n\n  blank above\nb: x\n",
        "a: >\n  folded\n  into one\n\n  new paragraph\nb: x\n",
        "a: >-\n  folded strip\n  end\n",
        "a: |+\n  keep\n\nb: x\n",
        "key.with.dots: \"value with # hash\"\nother: 'single # hash'\n",
        'iproyal.env.IPROYAL_EMAIL.description:\n  text: "Correo"\n  source: "0123456789ab"\n',
        '---\na: "日本語 العربية"\n',
    ],
)
def test_yaml_subset_matches_pyyaml(doc):
    assert ic.parse_yaml(doc) == yaml.safe_load(doc)


@pytest.mark.parametrize(
    "doc",
    [
        "a:\n  - one\n  - two\n",
        "a: [one, two]\n",
        "a: {b: c}\n",
        "a: &anchor x\n",
        'a: "multi\n  line"\n',
        "a: x\na: y\n",
        "a: has: colon\n",
        "a:\n\tb: tab\n",
        "  a: indented start\n",
        "a:\n    b: x\n  c: between\n",
    ],
)
def test_yaml_subset_rejects_what_it_does_not_support(doc):
    with pytest.raises(ic.ParseError):
        ic.parse_yaml(doc)


def test_dumped_strings_round_trip_through_both_parsers():
    for value in ["plain", 'quote " and \\ back', "line\nbreak", "tab\t", "é 日本 ٣", "# not a comment", "{x}: y"]:
        doc = f"k: {ic.dump_yaml_string(value)}\n"
        assert ic.parse_yaml(doc) == {"k": value} == yaml.safe_load(doc)


# --- Source hashes, stale keys and stamping -------------------------------------------


def test_hash_format():
    assert ic.source_hash("Hello") == "185f8db32271"  # sha256("Hello")[:12]
    assert ic.source_hash({"other": "b", "one": "a"}) == ic.source_hash("one\x1ea\x1fother\x1eb")


def catalog(tmp_path):
    d = tmp_path / "services" / "_i18n"
    en = write(d / "en.yml", 'iproyal.description: "Share bandwidth"\niproyal.notes: "Pays on ${DAY}"\n')
    return d, en


def test_catalog_stale_warns_and_strict_fails(tmp_path):
    d, en = catalog(tmp_path)
    es = write(
        d / "es.yml",
        'iproyal.description:\n  text: "Comparte ancho de banda"\n'
        f'  source: "{ic.source_hash("Share bandwidth")}"\n'
        'iproyal.notes:\n  text: "Paga el ${DAY}"\n  source: "000000000000"\n',
    )
    code, out = run(en, es)
    assert code == 0 and "1 stale" in out and "stale       iproyal.notes" in out
    assert run(en, es, "--strict")[0] == 1


def test_catalog_stamp_and_restamp(tmp_path):
    d, en = catalog(tmp_path)
    es = write(
        d / "es.yml",
        '# header kept\niproyal.description:\n  text: "Comparte"\niproyal.notes:\n  text: "Paga el ${DAY}"\n',
    )
    code, out = run(en, es)
    assert code == 0 and "2 unstamped" in out

    code, out = run(en, es, "--stamp")
    assert code == 0 and "stamped 2" in out
    assert es.read_text(encoding="utf-8").startswith("# header kept\n")
    assert yaml.safe_load(es.read_text(encoding="utf-8"))["iproyal.notes"]["source"] == ic.source_hash("Pays on ${DAY}")
    assert "ok" in run(en, es)[1]

    # The English changes: the key goes stale, --stamp leaves it, --restamp fixes it.
    write(en, 'iproyal.description: "Share bandwidth"\niproyal.notes: "Pays monthly on ${DAY}"\n')
    assert "1 stale" in run(en, es)[1]
    run(en, es, "--stamp")
    assert "1 stale" in run(en, es)[1]
    run(en, es, "--restamp", "iproyal.notes")
    assert "ok" in run(en, es)[1]


def test_json_inline_stamp(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"menu": {"fleet": "Fleet"}}))
    es = write(tmp_path / "es.json", json.dumps({"menu": {"fleet": "Flota"}}))
    assert "unstamped" not in run(en, es)[1]  # no hashes in use yet
    run(en, es, "--stamp")
    data = json.loads(es.read_text(encoding="utf-8"))
    assert data == {"menu": {"fleet": {"text": "Flota", "source": ic.source_hash("Fleet")}}}
    assert "ok" in run(en, es)[1]


def test_android_sidecar_hashes(tmp_path):
    en = write(tmp_path / "res" / "values" / "strings.xml", '<resources><string name="a">Fleet</string></resources>')
    de = write(
        tmp_path / "res" / "values-de" / "strings.xml", '<resources><string name="a">Flotte</string></resources>'
    )
    code, out = run(en, de, "--stamp")
    assert code == 2 and "--hashes-dir" in out
    hashes = tmp_path / "i18n" / "hashes"
    run(en, de, "--stamp", "--hashes-dir", hashes)
    assert json.loads((hashes / "de.json").read_text()) == {"a": ic.source_hash("Fleet")}
    write(en, '<resources><string name="a">Your fleet</string></resources>')
    code, out = run(en, de, "--hashes-dir", hashes)
    assert code == 0 and "1 stale" in out


def test_android_legacy_language_codes(tmp_path):
    assert ic.locale_of(tmp_path / "values-in" / "strings.xml", "android") == "id"
    assert ic.locale_of(tmp_path / "values-tl" / "strings.xml", "android") == "fil"
    assert ic.locale_of(tmp_path / "values-zh-rCN" / "strings.xml", "android") == "zh-CN"


def test_fastlane_text_directories_with_ignore(tmp_path):
    meta = tmp_path / "fastlane" / "metadata" / "android"
    write(meta / "en-US" / "title.txt", "CashPilot\n")
    write(meta / "en-US" / "short_description.txt", "Run earners on your boxes\n")
    write(meta / "en-US" / "changelogs" / "42.txt", "Fixes\n")
    write(meta / "es-ES" / "title.txt", "CashPilot\n")
    write(meta / "es-ES" / "short_description.txt", "Ejecuta earners en tus equipos\n")
    code, out = run(meta / "en-US", meta / "es-ES")
    assert code == 1 and "missing     changelogs/42.txt" in out
    assert run(meta / "en-US", meta / "es-ES", "--ignore", "changelogs/*")[0] == 0
    hashes = tmp_path / "hashes"
    run(meta / "en-US", meta / "es-ES", "--ignore", "changelogs/*", "--stamp", "--hashes-dir", hashes)
    assert set(json.loads((hashes / "es-ES.json").read_text())) == {"title.txt", "short_description.txt"}
