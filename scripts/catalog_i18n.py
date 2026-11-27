#!/usr/bin/env python3
"""Write services/_i18n/en.yml, the English source of the catalog translations.

The service files stay English. app/catalog.py names every string the web UI
and Desktop show (I18N_FIELDS) and keys it "<slug>.<path>"; this script writes
those strings to en.yml, which scripts/i18n_check.py compares with the 19
translated files.

    python scripts/catalog_i18n.py            rewrite en.yml from services/
    python scripts/catalog_i18n.py --check    exit 1 if en.yml is out of date

A changed English string changes its hash, so its translations turn stale
and show English until a translator updates them and runs
    python scripts/i18n_check.py services/_i18n/en.yml services/_i18n/<locale>.yml --restamp '<key>'
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import catalog  # noqa: E402
from scripts.i18n_check import dump_yaml_string  # noqa: E402

EN = catalog.I18N_DIR / f"{catalog.SOURCE_LOCALE}.yml"

HEADER = """\
# The English source of the catalog translations. Generated from services/
# by scripts/catalog_i18n.py: do not edit by hand, edit the service file and
# run the script. Each key is <slug>.<path to the field>.
"""


def render(strings: dict[str, str]) -> str:
    lines = [HEADER]
    lines += [f"{key}: {dump_yaml_string(text)}" for key, text in strings.items()]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="fail if en.yml does not match services/")
    args = ap.parse_args(argv)

    strings = catalog.catalog_strings(catalog.load_services())
    want = render(strings)
    have = EN.read_text(encoding="utf-8") if EN.exists() else ""
    if args.check:
        if have != want:
            print(f"{EN.relative_to(ROOT)} is out of date. Run: python scripts/catalog_i18n.py", file=sys.stderr)
            return 1
        # A deleted locale file would pass the parity check, which only sees
        # the files that exist.
        absent = [loc for loc in catalog.LOCALES if not (catalog.I18N_DIR / f"{loc}.yml").is_file()]
        if absent:
            print(f"No translation file for: {', '.join(absent)}", file=sys.stderr)
            return 1
        print(f"{EN.relative_to(ROOT)} matches the catalog, and all {len(catalog.LOCALES)} locale files exist.")
        return 0
    EN.parent.mkdir(parents=True, exist_ok=True)
    EN.write_text(want, encoding="utf-8")
    print(f"wrote {EN.relative_to(ROOT)}: {len(strings)} keys")
    return 0


if __name__ == "__main__":
    sys.exit(main())
