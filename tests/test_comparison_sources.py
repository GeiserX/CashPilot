"""Every claim about another project on docs/comparison.md links to a fixed commit.

The comparison page describes other people's code. A link to ``/blob/main/``
moves under the reader: a month later the cited line says something else and
the page looks wrong, or worse, looks right by accident. So every GitHub file
or tree link to a repository outside GeiserX must name a full 40-character
commit, and the page must state the date it was checked.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "comparison.md"

_LINK = re.compile(
    r"https://(?:github\.com/([^/\s)]+)/([^/\s)]+)/(?:blob|tree|raw)|raw\.githubusercontent\.com/([^/\s)]+)/([^/\s)]+))"
    r"/([^/\s)#?]+)"
)
_SHA = re.compile(r"[0-9a-f]{40}")


def unpinned_links(text: str) -> list[str]:
    """GitHub blob, tree and raw links to other owners whose ref is not a full commit SHA."""
    return [
        m.group(0)
        for m in _LINK.finditer(text)
        if (m.group(1) or m.group(3)).lower() != "geiserx" and not _SHA.fullmatch(m.group(5))
    ]


def test_every_external_source_link_is_pinned_to_a_commit():
    text = PAGE.read_text(encoding="utf-8")
    assert _LINK.search(text), "the page cites no GitHub sources at all; the pattern is broken"
    assert unpinned_links(text) == []


def test_the_page_states_when_it_was_checked():
    assert re.search(r"checked every project on \d{4}-\d{2}-\d{2}", PAGE.read_text(encoding="utf-8"))


def test_the_check_catches_a_branch_link():
    sample = (
        "https://github.com/MRColorR/money4band/blob/main/README.md "
        "https://github.com/XternA/income-generator/tree/65e900dcd4342ba011b7093e9800d300804c2f2e "
        "https://github.com/GeiserX/CashPilot/blob/main/app/main.py "
        "https://raw.githubusercontent.com/engageub/InternetIncome/main/internetIncome.sh "
        "https://github.com/engageub/InternetIncome/raw/main/internetIncome.sh "
        "https://raw.githubusercontent.com/engageub/InternetIncome/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh"
    )
    assert unpinned_links(sample) == [
        "https://github.com/MRColorR/money4band/blob/main",
        "https://raw.githubusercontent.com/engageub/InternetIncome/main",
        "https://github.com/engageub/InternetIncome/raw/main",
    ]
