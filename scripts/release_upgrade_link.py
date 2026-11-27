#!/usr/bin/env python3
"""Print the first line of a GitHub Release body: where to read before upgrading.

usage: python3 scripts/release_upgrade_link.py <tag> [UPGRADING.md]

A major (vX.0.0) links its own section of UPGRADING.md, the "## X.0: ..."
heading (older majors wrote "## vX.0.0: ..."), so its release notes open on
what changed and how to upgrade. Every other release links the top of the
file. A major with no section yet gets the top of the file too, with a
warning on stderr, so the release still publishes.

The anchor is GitHub's: the heading text in lower case, with every character
that is not a letter, a digit, a space, a hyphen or an underscore removed, and
each space turned into a hyphen.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

URL = "https://github.com/GeiserX/CashPilot/blob/main/UPGRADING.md"
ROOT = Path(__file__).resolve().parents[1]


def anchor(heading: str) -> str:
    """The id GitHub gives a Markdown heading."""
    slug = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return slug.replace(" ", "-")


def upgrade_url(tag: str, text: str) -> str:
    """The UPGRADING.md link for a release tag."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", tag.strip())
    if not match or match.group(2) != "0" or match.group(3) != "0":
        return URL
    major = match.group(1)
    for line in text.splitlines():
        heading = re.fullmatch(rf"## (v?{re.escape(major)}\.0(?:\.0)?:.*)", line.rstrip())
        if heading:
            return f"{URL}#{anchor(heading.group(1))}"
    print(f"warning: UPGRADING.md has no '## {major}.0:' section; linking the top of the file", file=sys.stderr)
    return URL


def body(tag: str, text: str) -> str:
    return f"Upgrading? Read {upgrade_url(tag, text)} first."


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__.splitlines()[2], file=sys.stderr)
        return 2
    path = Path(argv[2]) if len(argv) == 3 else ROOT / "UPGRADING.md"
    print(body(argv[1], path.read_text(encoding="utf-8")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
