"""A referral link says it is one, next to the link, before the click.

The disclosure used to live in one README section, which a docs rework dropped
without anyone noticing, and the app's Sign Up buttons never had one at all. A
reader who follows a guide or clicks Sign Up should not need to find a separate
page to learn that the maintainer may earn from it. These tests pin the note to
each place a referral link is shown.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import catalog
from scripts.new_service_stub import referral_note

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")


def _referral_services() -> list[dict]:
    return [s for s in catalog.get_services() if (s.get("referral") or {}).get("code")]


def _guide_cases() -> list[tuple[str, Path]]:
    """Every guide of a live service that has a referral code.

    Not filtered on the guide's content: a guide that lost its signup link must
    fail below, not drop out of the list.
    """
    cases = []
    for svc in _referral_services():
        guide = ROOT / "docs" / "guides" / f"{svc['slug']}.md"
        if guide.exists() and svc.get("status") in {"active", "beta"}:
            cases.append((svc["slug"], guide))
    return cases


def test_there_are_guides_to_check():
    """An empty parametrisation would pass every test below without checking anything."""
    assert len(_guide_cases()) >= 20


@pytest.mark.parametrize(("slug", "guide"), _guide_cases(), ids=[c[0] for c in _guide_cases()])
def test_every_guide_notes_its_referral_link_right_under_it(slug, guide):
    svc = catalog.get_service(slug)
    lines = guide.read_text(encoding="utf-8").splitlines()
    hits = [i for i, line in enumerate(lines) if svc["referral"]["signup_url"] in line]
    assert hits, f"{guide.name}: the catalog's signup link is missing"
    first = hits[0]
    # The next non-blank line, with a blockquote marker stripped.
    following = [line.lstrip("> ").strip() for line in lines[first + 1 : first + 4]]
    following = [line for line in following if line]
    assert following and following[0] == referral_note(svc), f"{guide.name}: note missing under the signup link"


def test_a_bare_signup_url_gets_no_note():
    assert referral_note({"referral": {"signup_url": "https://x.example"}, "website": "https://x.example"}) == ""


def test_the_note_only_states_the_commission():
    """No alternative link: the note says what the link is, nothing more."""
    note = referral_note(
        {"referral": {"code": "A1", "signup_url": "https://x.example/r/A1"}, "website": "https://www.x.example"}
    )
    assert note == "<small>Referral link: the CashPilot maintainer may earn a commission from it.</small>"


def test_the_readme_discloses_before_the_first_list_of_links():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    disclosure = readme.find("**Disclosure.**")
    first_list = readme.find("<!-- BEGIN GENERATED: docker-services -->")
    assert 0 <= disclosure < first_list
    assert first_list - disclosure < 600, "the disclosure must sit right above the lists, not somewhere earlier"


def test_the_app_note_only_appears_for_a_referral_code():
    body = APP_JS[APP_JS.index("function referralNote(") :]
    body = body[: body.index("\n  function ")]
    assert "ref.code" in body


@pytest.mark.parametrize("fn", ["renderServiceSetupForm", "renderServiceDetail"])
def test_every_sign_up_button_in_the_app_carries_the_note(fn):
    body = APP_JS[APP_JS.index(f"function {fn}(") :]
    body = body[: body.index("\n  function ", 1)]
    buttons = len(re.findall(r"Sign Up", body))
    assert buttons, fn
    assert body.count("referralNote(svc)") >= (2 if fn == "renderServiceSetupForm" else 1), fn
