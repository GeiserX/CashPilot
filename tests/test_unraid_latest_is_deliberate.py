"""The unraid templates use :latest ON PURPOSE, and that has to be legible.

Everywhere else this project pins a major.minor series, and #280 added a sweep
that fails any doc shipping `image: drumsergio/...:latest`. The unraid
Community Applications templates are the one deliberate exception.

THE REASONING, so this test is not just a lock on an arbitrary state:
CA is how unraid users receive updates at all. A template pinned to 1.19 leaves
every CA user on 1.19 until the template itself is re-published -- trading
"unknowable version" for "silently frozen version", which is worse for an app
whose whole job is to keep earning.

Decided 2026-08-07 (CashPilot-3c2n). These assertions exist so that a later
reader tidying `:latest` out of the repository finds a failing test explaining
why, rather than quietly changing how every unraid user gets updates.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = sorted((ROOT / "unraid").glob("*.xml"))


def test_there_are_templates_to_check():
    """CONTROL. If the directory were empty or renamed, every assertion below
    would hold vacuously."""
    assert TEMPLATES, "no unraid templates found; the checks below prove nothing"


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_the_template_is_valid_xml(path):
    """A malformed template is rejected by CA with no useful message."""
    ET.parse(path)


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_it_uses_latest(path):
    repo = ET.parse(path).getroot().findtext("Repository") or ""
    assert repo.endswith(":latest"), (
        f"{path.name} no longer uses :latest. That may be right, but it changes how every "
        "unraid user receives updates -- a pinned template freezes them until it is "
        "re-published. Read CashPilot-3c2n before changing this."
    )


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_it_explains_why(path):
    """The tag alone looks like an oversight. Without the comment beside it,
    the next person to tidy the repository removes it in good faith."""
    text = path.read_text(encoding="utf-8")
    assert "DELIBERATE" in text, f"{path.name} uses :latest with no explanation next to it"
    assert "CashPilot-3c2n" in text, f"{path.name} does not point at the decision record"
