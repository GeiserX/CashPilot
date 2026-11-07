"""The Storj guide's Chapter 11 and held-back claims each name their source.

The guide stated the filing date, the freeze on pre-filing node earnings and
the held-back schedule with no link, so a reader could not check them and a
reviewer could not tell when one went stale.
"""

from __future__ import annotations

from pathlib import Path

import pytest

GUIDE = Path(__file__).resolve().parents[1] / "docs" / "guides" / "storj.md"

FILING = "https://www.storj.io/blog/storj-announces-voluntary-financial-restructuring"
FREEZE = "https://forum.storj.io/t/storagenode-payout-update-august-prepayments-and-july-2026-status/32266"
HELD = "https://storj.dev/node/faq/held-back-amount"


def _line(marker: str) -> str:
    lines = [line for line in GUIDE.read_text(encoding="utf-8").splitlines() if marker in line]
    assert len(lines) == 1, f"expected one line with {marker!r} in the Storj guide"
    return lines[0]


@pytest.mark.parametrize(
    ("marker", "sources"),
    [
        ("5:26-bk-00512", [FILING, FREEZE]),
        ("**Held-back earnings**", [HELD, FREEZE]),
    ],
)
def test_each_claim_links_its_source(marker: str, sources: list[str]):
    line = _line(marker)
    assert [s for s in sources if f"]({s}" not in line] == []
