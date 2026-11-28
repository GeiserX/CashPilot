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
        ("Use <a href='https://x.io'>your login</a>", 'Usa <a href="https://x.io">tu cuenta</a>'),
        ("<b>Bold</b> and 1 < 2", "<b>Negrita</b> y 1 < 2"),
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
        ("Use <a href='https://x.io'>your login</a>", "Usa <a href='https://y.io'>tu cuenta</a>"),
        ("Use <a href='https://x.io'>your login</a>", "Usa tu cuenta en https://x.io"),
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


def test_an_android_target_in_utf16_is_read_by_its_encoding_declaration(tmp_path):
    res = tmp_path / "res"
    en = write(res / "values" / "strings.xml", '<resources><string name="hi">Hello %1$s</string></resources>')
    de = res / "values-de" / "strings.xml"
    de.parent.mkdir(parents=True)
    xml = '<?xml version="1.0" encoding="utf-16"?><resources><string name="hi">Hallo %1$s</string></resources>'
    de.write_bytes(xml.encode("utf-16"))
    code, out = run(en, de)
    assert code == 0 and "error:" not in out


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


def test_yaml_line_separators_stay_inside_a_value():
    value = "a b c\x85d"
    doc = f"k: {ic.dump_yaml_string(value)}\nnext: x\n"
    assert ic.parse_yaml(doc) == {"k": value, "next": "x"} == yaml.safe_load(doc)


# --- Review findings (CodeRabbit on #876) ---------------------------------------------


@pytest.mark.parametrize(
    "doc",
    [
        "a: >\n  one\n    more indented\n\n  back\n",
        "a: |+\n\n",
        "a: >\n\n  leading blank\n",
    ],
)
def test_yaml_folding_and_keep_chomping_match_pyyaml(doc):
    assert ic.parse_yaml(doc) == yaml.safe_load(doc)


@pytest.mark.parametrize("doc", ['a: "\\U00110000"\n', "[a, b]: Hello\n", "{a: b}: c\n"])
def test_yaml_rejects_bad_escapes_and_flow_keys(doc):
    with pytest.raises(ic.ParseError):
        ic.parse_yaml(doc)


def test_quoted_flow_key_is_a_plain_string():
    assert ic.parse_yaml("'[a, b]': Hello\n") == {"[a, b]": "Hello"}


@pytest.mark.parametrize(
    ("src", "tgt"),
    [
        ("%(name)s", "%(name)d"),
        ("%*s", "%s"),
        ("%2$s %s", "%2$s %2$s"),
    ],
)
def test_printf_types_and_positions(src, tgt):
    assert ic.placeholders(src) != ic.placeholders(tgt)


def test_printf_explicit_reorder_and_mustache_inside_icu():
    assert ic.placeholders("%2$d %1$s") == ic.placeholders("%1$s %2$d")
    assert ic.placeholders("{n, plural, other {Hello {who}}}") == ic.placeholders("{n, plural, other {{who}}}")
    assert ic.placeholders("{{who}}") == {("mustache", "who")}


def test_icu_plural_without_other_fails_even_when_english_lacks_it(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"a": "{n, plural, one {# box}}"}))
    es = write(tmp_path / "es.json", json.dumps({"a": "{n, plural, one {# caja}}"}))
    code, out = run(en, es)
    assert code == 1 and "no 'other' branch in n" in out


def test_blank_other_form_in_android_plural_fails(tmp_path):
    en = write(
        tmp_path / "res" / "values" / "strings.xml",
        '<resources><plurals name="p"><item quantity="one">a box</item><item quantity="other">boxes</item></plurals></resources>',
    )
    de = write(
        tmp_path / "res" / "values-de" / "strings.xml",
        '<resources><plurals name="p"><item quantity="one">eine Kiste</item><item quantity="other"> </item></plurals></resources>',
    )
    code, out = run(en, de)
    assert code == 1 and "no 'other' form" in out


def test_prose_object_named_text_and_source_is_not_a_hash(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"page": {"text": "Welcome", "source": "From {name}"}}))
    es = write(tmp_path / "es.json", json.dumps({"page": {"text": "Bienvenido", "source": "De"}}))
    code, out = run(en, es)
    assert code == 1 and "placeholder page.source" in out


def test_dotted_and_nested_key_collision_is_an_error(tmp_path):
    en = write(tmp_path / "en.json", '{"menu.title": "Hi {name}", "menu": {"title": "Title"}}')
    es = write(tmp_path / "es.json", json.dumps({"menu": {"title": "Título"}}))
    assert run(en, es)[0] == 2


def test_empty_inline_hash_counts_as_unstamped(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"a": "Hello", "b": "Bye"}))
    es = write(tmp_path / "es.json", json.dumps({"a": {"text": "Hola", "source": ""}, "b": "Adiós"}))
    code, out = run(en, es, "--strict")
    assert code == 1 and "2 unstamped" in out


def test_catalog_keys_that_need_quotes_round_trip(tmp_path):
    d = tmp_path / "_i18n"
    en = write(d / "en.yml", '"menu: title": "Hello"\nplain.key: "Bye"\n')
    es = write(d / "es.yml", '"menu: title":\n  text: "Hola"\nplain.key:\n  text: "Adiós"\n')
    run(en, es, "--stamp")
    code, out = run(en, es, "--strict")
    assert code == 0, out


def test_numeric_json_leaf_is_stamped_inline(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"year": "2026"}))
    es = write(tmp_path / "es.json", json.dumps({"year": 2026}))
    run(en, es, "--stamp")
    assert json.loads(es.read_text()) == {"year": {"text": "2026", "source": ic.source_hash("2026")}}


def test_ignore_applies_to_target_keys_too(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"a": "Hello", "changelog": "Fixes"}))
    es = write(tmp_path / "es.json", json.dumps({"a": "Hola", "changelog": "Arreglos"}))
    code, out = run(en, es, "--ignore", "changelog", "--strict")
    assert code == 0 and "extra" not in out


def test_invalid_utf8_exits_2(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"a": "Hello"}))
    es = tmp_path / "es.json"
    es.write_bytes(b'{"a": "\xff"}')
    assert run(en, es)[0] == 2


def test_inline_i18next_stamping_is_refused(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"f_one": "{{count}} file", "f_other": "{{count}} files"}))
    es = write(tmp_path / "es.json", json.dumps({"f_one": "{{count}} archivo", "f_other": "{{count}} archivos"}))
    code, out = run(en, es, "--i18next-plurals", "--stamp")
    assert code == 2 and "--hashes-dir" in out
    assert run(en, es, "--i18next-plurals", "--stamp", "--hashes-dir", tmp_path / "h")[0] == 0


def test_placeholder_in_an_attribute_is_compared(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"a": '<span title="{name}">Hello</span>'}))
    es = write(tmp_path / "es.json", json.dumps({"a": '<span title="{count}">Hola</span>'}))
    code, out = run(en, es)
    assert code == 1 and "placeholder a" in out
    write(es, json.dumps({"a": "<span title='{name}'>Hola</span>"}))
    assert run(en, es)[0] == 0


def test_catalog_stamp_keeps_ignored_entries(tmp_path):
    d, en = catalog(tmp_path)
    es = write(
        d / "es.yml",
        'iproyal.description:\n  text: "Comparte"\niproyal.notes:\n  text: "Paga el ${DAY}"\n',
    )
    code, out = run(en, es, "--ignore", "iproyal.notes", "--stamp")
    assert code == 0 and "stamped 1" in out
    data = yaml.safe_load(es.read_text(encoding="utf-8"))
    assert data["iproyal.notes"] == {"text": "Paga el ${DAY}"}
    assert data["iproyal.description"]["source"] == ic.source_hash("Share bandwidth")


def test_attribute_placeholders_keep_their_printf_order(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"a": '<span title="%s">%d</span>'}))
    es = write(tmp_path / "es.json", json.dumps({"a": '<span title="%1$s">%2$d</span>'}))
    assert run(en, es)[0] == 0
    en2 = write(tmp_path / "en2.json", json.dumps({"a": '<span title="%s">Hello</span> %d'}))
    es2 = write(tmp_path / "es2.json", json.dumps({"a": '%d <span title="%s">Hola</span>'}))
    assert run(en2, es2)[0] == 1


# --- The second full review --------------------------------------------------


def test_lone_surrogate_escape_is_a_parse_error(tmp_path):
    en = write(tmp_path / "en.yml", 'a: "\\uD800"\n')
    code, out = run(en, write(tmp_path / "es.yml", 'a: "x"\n'))
    assert code == 2 and "surrogate" in out
    assert ic.parse_yaml('a: "\\U0001F600"\n') == {"a": "\U0001f600"}


@pytest.mark.parametrize(
    "text",
    [
        "a: |\n  Hello",
        "a: |\n  Hello\n",
        "a: |+\n  Hello",
        "a: |+\n  Hello\n\n",
        "a: >\n  Hello\n  world",
        "a: |-\n  Hi",
    ],
)
def test_block_scalar_at_the_end_of_the_file_matches_pyyaml(text):
    assert ic.parse_yaml(text) == yaml.safe_load(text)


def test_locale_file_names_match_in_any_case(tmp_path):
    en = write(tmp_path / "locales" / "en.yml", "en:\n  a: Hello\n")
    pt = write(tmp_path / "locales" / "pt-br.yml", "pt-br:\n  a: Olá\n")
    assert ic.locale_of(pt, "yaml") == "pt-br"
    assert run(en, pt)[0] == 0


def test_catalog_keys_stay_strings_for_pyyaml(tmp_path):
    out = tmp_path / "es.yml"
    ic.write_catalog(out, {"123": "uno", "True": "sí", "a.b": "x"}, {})
    assert set(yaml.safe_load(out.read_text(encoding="utf-8"))) == {"123", "True", "a.b"}


def test_i18next_family_with_mixed_hashes_is_stale_in_any_order(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"f_one": "{{count}} file", "f_other": "{{count}} files"}))
    fam = ic.source_hash(
        "\x1f".join(f"{q}\x1e{t}" for q, t in sorted({"one": "{{count}} file", "other": "{{count}} files"}.items()))
    )
    for order in (("f_one", "f_other"), ("f_other", "f_one")):
        tree = {
            "f_one": {"text": "{{count}} archivo", "source": fam},
            "f_other": {"text": "{{count}} archivos", "source": "000000000000"},
        }
        es = write(tmp_path / "es.json", json.dumps({k: tree[k] for k in order}))
        code, out = run(en, es, "--i18next-plurals", "--strict")
        assert code == 1 and "stale" in out, order


def test_only_the_real_href_is_compared(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"a": "<a href='https://a.example'>Go</a>"}))
    es = write(
        tmp_path / "es.json", json.dumps({"a": "<a data-href='https://a.example' href='https://evil.example'>Ir</a>"})
    )
    assert run(en, es)[0] == 1


def test_a_dropped_plural_number_is_a_mismatch(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"a": "{n, plural, one {# box} other {# boxes}}"}))
    es = write(tmp_path / "es.json", json.dumps({"a": "{n, plural, one {una caja} other {cajas}}"}))
    assert run(en, es)[0] == 1
    write(es, json.dumps({"a": "{n, plural, one {una caja} other {# cajas}}"}))
    assert run(en, es)[0] == 0
    write(es, json.dumps({"a": "{n, plural, other {'#' cajas}}"}))
    assert run(en, es)[0] == 1


def test_escaped_percent_is_not_a_named_conversion(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"a": "100%%(name)s and %(user)s"}))
    es = write(tmp_path / "es.json", json.dumps({"a": "100%%(nombre)s y %(user)s"}))
    assert run(en, es)[0] == 0


def test_root_level_inline_entry_is_refused(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"a": "Hello"}))
    es = write(tmp_path / "es.json", json.dumps({"text": "Hola", "source": ""}))
    code, out = run(en, es, "--stamp")
    assert code == 2 and "one {text, source} entry" in out


def test_a_file_changed_between_check_and_stamp_is_not_written(tmp_path):
    es = write(tmp_path / "es.json", json.dumps({"a": "Hola"}))
    checked = ic.load_json(es)
    # The control: an unchanged file is stamped.
    ic.write_json_inline(es, {"a": ic.source_hash("Hello")}, checked)
    assert json.loads(es.read_text())["a"] == {"text": "Hola", "source": ic.source_hash("Hello")}
    checked = ic.load_json(es)
    write(es, json.dumps({"a": "Adiós"}))
    with pytest.raises(ic.ParseError):
        ic.write_json_inline(es, {"a": ic.source_hash("Hello")}, checked)
    assert json.loads(es.read_text()) == {"a": "Adiós"}


def test_a_hash_file_that_is_an_input_is_refused(tmp_path):
    d = tmp_path / "locales"
    en = write(d / "en.json", json.dumps({"a": "Hello"}))
    fr = write(d / "fr.json", json.dumps({"a": "Bonjour"}))
    code, out = run(en, fr, "--hashes-dir", d, "--restamp", "*")
    assert code == 2 and "also an input" in out
    assert json.loads(fr.read_text()) == {"a": "Bonjour"}


def test_catalog_plural_stamping_is_refused(tmp_path):
    d = tmp_path / "services" / "_i18n"
    en = write(d / "en.yml", 'f_one: "{{count}} file"\nf_other: "{{count}} files"\n')
    es = write(d / "es.yml", 'f_one:\n  text: "{{count}} archivo"\nf_other:\n  text: "{{count}} archivos"\n')
    before = es.read_text()
    code, out = run(en, es, "--i18next-plurals", "--stamp")
    assert code == 2 and es.read_text() == before


# --- The third full review ---------------------------------------------------


@pytest.mark.parametrize("text", ["a: |2-\n  Hi\n    \n  Bye\n", "a: |\n  Hi\n    \n", "a: >\n  Hi\n    \n  Bye\n"])
def test_spaces_on_a_blank_block_line_are_content(text):
    assert ic.parse_yaml(text) == yaml.safe_load(text)


def test_an_inline_entry_named_like_the_locale_is_not_a_root(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"es": "Hello"}))
    es = write(tmp_path / "es.json", json.dumps({"es": "Hola"}))
    assert run(en, es, "--stamp")[0] == 0
    code, out = run(en, es, "--strict")
    assert code == 0, out


def test_duplicate_json_members_are_refused(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"a": "Hello"}))
    es = write(tmp_path / "es.json", '{"a": "Hola", "a": "Buenas"}')
    before = es.read_text()
    code, out = run(en, es, "--stamp")
    assert code == 2 and "duplicate key" in out and es.read_text() == before


def _family_hash(forms: dict) -> str:
    return ic.source_hash("\x1f".join(f"{q}\x1e{t}" for q, t in sorted(forms.items())))


def test_a_plural_form_without_a_hash_makes_the_family_stale(tmp_path):
    en_forms = {"one": "{{count}} file", "other": "{{count}} files"}
    en = write(tmp_path / "en.json", json.dumps({f"f_{q}": t for q, t in en_forms.items()}))
    fam = _family_hash(en_forms)
    es = write(
        tmp_path / "es.json",
        json.dumps({"f_one": {"text": "{{count}} archivo", "source": fam}, "f_other": "{{count}} archivos"}),
    )
    assert run(en, es, "--i18next-plurals", "--strict")[0] == 1
    write(
        es,
        json.dumps(
            {
                "f_one": {"text": "{{count}} archivo", "source": fam},
                "f_other": {"text": "{{count}} archivos", "source": fam},
            }
        ),
    )
    assert run(en, es, "--i18next-plurals", "--strict")[0] == 0


def test_overlapping_plural_families_do_not_borrow_hashes(tmp_path):
    a = {"one": "{{count}} a", "other": "{{count}} as"}
    en = write(
        tmp_path / "en.json", json.dumps({"f_one_other": "{{count}} b", "f_one": a["one"], "f_other": a["other"]})
    )
    good_a = _family_hash(a)
    for order in (("f_one_other", "f_one", "f_other"), ("f_one", "f_other", "f_one_other")):
        tree = {
            "f_one_other": {"text": "{{count}} be", "source": "000000000000"},
            "f_one": {"text": "{{count}} a", "source": good_a},
            "f_other": {"text": "{{count}} as", "source": good_a},
        }
        es = write(tmp_path / "es.json", json.dumps({k: tree[k] for k in order}))
        code, out = run(en, es, "--i18next-plurals", "--strict")
        assert code == 1 and "stale       f_one:" in out and "  f:" not in out, (order, out)


def test_link_destinations_are_counted(tmp_path):
    a, b = "https://a.example", "https://b.example"
    en = write(tmp_path / "en.json", json.dumps({"x": f"<a href='{a}'>1</a> <a href='{a}'>2</a> <a href='{b}'>3</a>"}))
    es = write(tmp_path / "es.json", json.dumps({"x": f"<a href='{a}'>1</a> <a href='{b}'>2</a> <a href='{b}'>3</a>"}))
    assert run(en, es)[0] == 1
    write(es, json.dumps({"x": f"<a href='{b}'>3</a> <a href='{a}'>1</a> <a href='{a}'>2</a>"}))
    assert run(en, es)[0] == 0


def test_catalog_plural_refusal_says_it_is_unsupported(tmp_path):
    d = tmp_path / "services" / "_i18n"
    en = write(d / "en.yml", 'f_one: "{{count}} file"\nf_other: "{{count}} files"\n')
    es = write(d / "es.yml", 'f_one:\n  text: "{{count}} archivo"\nf_other:\n  text: "{{count}} archivos"\n')
    code, out = run(en, es, "--i18next-plurals", "--stamp")
    assert code == 2 and "not supported" in out and "--hashes-dir" not in out


def test_a_failed_write_keeps_the_old_file(tmp_path, monkeypatch):
    out = write(tmp_path / "es.yml", 'a:\n  text: "Hola"\n')

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(ic.os, "replace", boom)
    with pytest.raises(OSError):
        ic.write_catalog(out, {"a": "Adiós"}, {})
    assert out.read_text() == 'a:\n  text: "Hola"\n'
    assert list(tmp_path.iterdir()) == [out]


def test_a_link_in_every_plural_branch_is_fine(tmp_path):
    link = "<a href='/help'>help</a>"
    en = write(
        tmp_path / "en.json", json.dumps({"x": f"{{n, plural, one {{# box, {link}}} other {{# boxes, {link}}}}}"})
    )
    pl = write(
        tmp_path / "pl.json",
        json.dumps(
            {
                "x": f"{{n, plural, one {{# pudło, {link}}} few {{# pudła, {link}}} many {{# pudeł, {link}}} other {{# pudła, {link}}}}}"
            }
        ),
    )
    assert run(en, pl)[0] == 0


def test_the_temporary_file_never_overwrites_another_file(tmp_path):
    out = write(tmp_path / "es.yml", 'a:\n  text: "Hola"\n')
    other = write(tmp_path / ".es.yml.tmp", "keep me\n")
    ic.write_catalog(out, {"a": "Adiós"}, {})
    assert other.read_text() == "keep me\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == [".es.yml.tmp", "es.yml"]


def test_an_icu_message_checks_links_by_destination(tmp_path):
    link = "<a href='/help'>help</a>"
    en = write(
        tmp_path / "en.json", json.dumps({"x": f"{{n, plural, one {{# box, {link}}} other {{# boxes, {link}}}}}"})
    )
    # The link moved out of the branches: the same message.
    es = write(tmp_path / "es.json", json.dumps({"x": f"{link}: {{n, plural, one {{# caja}} other {{# cajas}}}}"}))
    assert run(en, es)[0] == 0
    write(es, json.dumps({"x": "<a href='/ayuda'>ayuda</a>: {n, plural, one {# caja} other {# cajas}}"}))
    assert run(en, es)[0] == 1
    write(es, json.dumps({"x": "{n, plural, one {# caja} other {# cajas}}"}))
    assert run(en, es)[0] == 1


def test_an_empty_plural_form_fails(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"f_one": "{{count}} file", "f_other": "{{count}} files"}))
    es = write(tmp_path / "es.json", json.dumps({"f_one": "", "f_other": "{{count}} archivos"}))
    code, out = run(en, es, "--i18next-plurals")
    assert code == 1 and "empty plural form one" in out
    write(es, json.dumps({"f_other": "{{count}} archivos"}))
    assert run(en, es, "--i18next-plurals")[0] == 0


# --- The Desktop copy's review -----------------------------------------------


def test_a_placeholder_moved_between_select_keywords_fails(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"a": "{g, select, male {He, {name}} other {They}}"}))
    es = write(tmp_path / "es.json", json.dumps({"a": "{g, select, male {Él} other {Ellos, {name}}}"}))
    code, out = run(en, es)
    assert code == 1 and "male" in out
    write(es, json.dumps({"a": "{g, select, other {Ellos} male {Él, {name}}}"}))
    assert run(en, es)[0] == 0


def test_broken_braces_fail_even_when_the_english_is_broken_too(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"a": "Hello {name"}))
    es = write(tmp_path / "es.json", json.dumps({"a": "Hola {name"}))
    code, out = run(en, es)
    assert code == 1 and "braces" in out


def _edit_after_read(monkeypatch, path, n, text):
    """Rewrite path right after its n-th read, as another editor would."""
    real = pathlib.Path.read_text
    reads = []

    def read_text(self, *a, **k):
        out = real(self, *a, **k)
        if self == path:
            reads.append(1)
            if len(reads) == n:
                path.write_text(text, encoding="utf-8")
        return out

    monkeypatch.setattr(pathlib.Path, "read_text", read_text)


def test_a_source_hash_changed_after_the_check_is_not_overwritten(tmp_path, monkeypatch):
    en = write(tmp_path / "en.json", json.dumps({"a": "Hi", "b": "Bye"}))
    es = write(tmp_path / "es.json", json.dumps({"a": {"text": "Hola", "source": "111111111111"}, "b": "Adiós"}))
    edited = json.dumps({"a": {"text": "Hola", "source": "222222222222"}, "b": "Adiós"})
    # The first read keeps the text a write compares against, the second parses it.
    _edit_after_read(monkeypatch, es, 2, edited)
    assert ic.main([str(en), str(es), "--stamp"]) != 0
    assert json.loads(es.read_text(encoding="utf-8"))["a"]["source"] == "222222222222"


def test_text_edited_during_the_stamp_is_never_stamped_current(tmp_path, monkeypatch):
    en = write(tmp_path / "en.json", json.dumps({"a": "Hi"}))
    es = write(tmp_path / "es.json", json.dumps({"a": "Hola"}))
    # The second read is the stamp's own check; the edit lands just after it.
    _edit_after_read(monkeypatch, es, 2, json.dumps({"a": "Hola {name}"}))
    assert ic.main([str(en), str(es), "--stamp"]) != 0
    # The edit stays, unstamped.
    assert json.loads(es.read_text(encoding="utf-8")) == {"a": "Hola {name}"}


def test_a_stamp_keeps_the_file_mode(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"a": "Hi"}))
    es = write(tmp_path / "es.json", json.dumps({"a": "Hola"}))
    es.chmod(0o644)
    assert run(en, es, "--stamp")[0] == 0
    assert "source" in es.read_text(encoding="utf-8")
    assert es.stat().st_mode & 0o777 == 0o644


def test_restamp_leaves_a_still_broken_translation_stale(tmp_path):
    d, en = catalog(tmp_path)
    es = write(
        d / "es.yml",
        'iproyal.description:\n  text: "Comparte"\n  source: "000000000000"\n'
        'iproyal.notes:\n  text: "Paga el día"\n  source: "000000000000"\n',
    )
    code, out = run(en, es, "--restamp", "*")
    assert code == 1 and "stamped 1" in out
    data = yaml.safe_load(es.read_text(encoding="utf-8"))
    assert data["iproyal.notes"]["source"] == "000000000000"
    assert data["iproyal.description"]["source"] == ic.source_hash("Share bandwidth")


def test_a_select_that_wraps_more_of_the_sentence_passes(tmp_path):
    # Filipino puts the verb first, so its select holds the whole sentence.
    en = (
        "{n, plural, =1 {{slug}} other {Copy {n} of {slug}}} on {worker} {cmd, select, stop {stopped} other {removed}}."
    )
    branch = "{n, plural, =1 {{slug}} other {kopya {n} ng {slug}}} sa {worker}"
    fil = f"{{cmd, select, stop {{Inihinto ang {branch}.}} other {{Inalis ang {branch}.}}}}"
    en_f = write(tmp_path / "en.json", json.dumps({"a": en}))
    fil_f = write(tmp_path / "fil.json", json.dumps({"a": fil}))
    assert run(en_f, fil_f)[0] == 0
    # Dropping {worker} from one keyword still fails.
    write(fil_f, json.dumps({"a": fil.replace(f"Inalis ang {branch}", "Inalis ang {slug}")}))
    assert run(en_f, fil_f)[0] == 1


def test_a_hash_belongs_to_its_own_plural(tmp_path):
    en = write(
        tmp_path / "en.json", json.dumps({"a": "{f, plural, other {# files}} in {d, plural, other {{d} folders}}"})
    )
    es = write(
        tmp_path / "es.json", json.dumps({"a": "{f, plural, other {{f} archivos}} en {d, plural, other {# carpetas}}"})
    )
    code, out = run(en, es)
    assert code == 1 and "# of f" in out


def _nested_selects(n: int, leaf: str) -> str:
    for i in range(n):
        leaf = f"{{s{i}, select, other {{{leaf}}}}}"
    return leaf


def test_the_report_on_nested_selects_stays_small():
    # Each level once copied every level below it, so the report doubled per level.
    found = ic.check_target({"k": _nested_selects(14, "{a}")}, {"k": _nested_selects(14, "{b}")}, None)
    assert found["placeholder"] and len(str(found)) < 100_000


def test_a_message_nested_too_deep_is_broken():
    found = ic.check_target({"k": _nested_selects(40, "{a}")}, {"k": _nested_selects(40, "{a}")}, None)
    assert found["placeholder"] == [("k", "unbalanced or malformed braces")]


def test_a_placeholder_moved_between_two_selects_keywords_fails(tmp_path):
    src = "{a, select, x {{b, select, x {{p}} other {{q}}}} other {{b, select, x {{q}} other {{p}}}}}"
    swapped = "{a, select, x {{b, select, x {{q}} other {{p}}}} other {{b, select, x {{p}} other {{q}}}}}"
    en = write(tmp_path / "en.json", json.dumps({"k": src}))
    es = write(tmp_path / "es.json", json.dumps({"k": swapped}))
    code, out = run(en, es)
    assert code == 1 and "a = x, b = x" in out
    write(es, json.dumps({"k": src}))
    assert run(en, es)[0] == 0


def test_a_message_with_too_many_select_combinations_fails(tmp_path):
    src = "{a, select, x {{b, select, x {{p}} other {{q}}}} other {{b, select, x {{q}} other {{p}}}}}"
    src += "".join(f" {{{n}, select, x {{{n.upper()}}} other {{{n.upper()}}}}}" for n in "cdefg")
    en = write(tmp_path / "en.json", json.dumps({"k": src}))
    es = write(tmp_path / "es.json", json.dumps({"k": src}))
    code, out = run(en, es)
    assert code == 1 and "more than 64 select combinations" in out


def test_two_selects_with_one_name_share_their_keywords(tmp_path):
    en = write(
        tmp_path / "en.json", json.dumps({"k": "{g, select, x {{p} {q}} other {}} {g, select, y {{p}} other {}}"})
    )
    es = write(
        tmp_path / "es.json", json.dumps({"k": "{g, select, x {{p} {q}} other {}} {g, select, y {{q}} other {}}"})
    )
    code, out = run(en, es)
    assert code == 1 and "g = y" in out


def test_one_select_may_take_the_place_of_two_with_its_name(tmp_path):
    en = write(
        tmp_path / "en.json", json.dumps({"k": "{g, select, x {{p}} other {{q}}} {g, select, y {{r}} other {{s}}}"})
    )
    es = write(tmp_path / "es.json", json.dumps({"k": "{g, select, x {{p} {s}} y {{q} {r}} other {{q} {s}}}"}))
    assert run(en, es)[0] == 0


@pytest.mark.parametrize("p, q", [("${p}", "${q}"), ("%(p)s", "%(q)s"), ("<b>", "<i>")])
def test_a_placeholder_of_another_kind_moved_between_select_keywords_fails(tmp_path, p, q):
    en = write(tmp_path / "en.json", json.dumps({"k": f"{{g, select, x {{a {p}}} other {{b {q}}}}}"}))
    es = write(tmp_path / "es.json", json.dumps({"k": f"{{g, select, x {{a {q}}} other {{b {p}}}}}"}))
    assert run(en, es)[0] == 1
    write(es, json.dumps({"k": f"{{g, select, other {{b {q}}} x {{a {p}}}}}"}))
    assert run(en, es)[0] == 0


def test_a_placeholder_moved_between_select_keywords_inside_quoted_braces_fails(tmp_path):
    en = write(tmp_path / "en.json", json.dumps({"k": "{g, select, x {'{%(p)s}'} other {'{%(q)s}'}}"}))
    es = write(tmp_path / "es.json", json.dumps({"k": "{g, select, x {'{%(q)s}'} other {'{%(p)s}'}}"}))
    code, out = run(en, es)
    assert code == 1 and "g = x" in out
    write(es, json.dumps({"k": "{g, select, other {'{%(q)s}'} x {'{%(p)s}'}}"}))
    assert run(en, es)[0] == 0


def test_a_select_inside_a_plural_may_lose_the_one_form(tmp_path):
    # Japanese has only "other", so the select in the English "one" form goes.
    en = write(
        tmp_path / "en.json",
        json.dumps(
            {
                "k": "{n, plural, one {{g, select, x {A single box} other {One box}}} other {{g, select, x {{who} has # boxes} other {# boxes}}}}"
            }
        ),
    )
    ja = write(
        tmp_path / "ja.json", json.dumps({"k": "{n, plural, other {{g, select, x {{who} の # 個} other {# 個}}}}"})
    )
    assert run(en, ja)[0] == 0


def _edit_during_the_temp_write(monkeypatch, path, text):
    real = ic.os.fdopen

    def fdopen(*a, **k):
        path.write_text(text, encoding="utf-8")
        return real(*a, **k)

    monkeypatch.setattr(ic.os, "fdopen", fdopen)


def test_a_json_save_during_the_stamp_is_kept(tmp_path, monkeypatch):
    en = write(tmp_path / "en.json", json.dumps({"a": "Hi"}))
    es = write(tmp_path / "es.json", json.dumps({"a": "Hola"}))
    _edit_during_the_temp_write(monkeypatch, es, json.dumps({"a": "Hola, editado"}))
    assert ic.main([str(en), str(es), "--stamp"]) != 0
    assert json.loads(es.read_text(encoding="utf-8")) == {"a": "Hola, editado"}
    assert not list(tmp_path.glob(".es.json.*"))


def test_a_catalog_save_during_the_stamp_is_kept(tmp_path, monkeypatch):
    d, en = catalog(tmp_path)
    es = write(d / "es.yml", 'iproyal.description:\n  text: "Comparte"\n')
    _edit_during_the_temp_write(monkeypatch, es, 'iproyal.description:\n  text: "Comparte, editado"\n')
    assert ic.main([str(en), str(es), "--stamp"]) != 0
    assert "editado" in es.read_text(encoding="utf-8")
