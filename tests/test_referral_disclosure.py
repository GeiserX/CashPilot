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


# Guides whose header still links the bare homepage on purpose, each with the
# reason. Strict xfail: once the header is fixed the case passes, the run goes
# red, and the entry must be removed.
_HEADER_PENDING = {
    "deeper-network": "the shop link's affiliate ID waits on the account owner's confirmation",
}

_MD_HREF = re.compile(r"\]\(([^)\s]+)\)")


def _header_cases() -> list:
    return [
        pytest.param(
            slug,
            guide,
            id=slug,
            marks=[pytest.mark.xfail(strict=True, reason=_HEADER_PENDING[slug])] if slug in _HEADER_PENDING else [],
        )
        for slug, guide in _guide_cases()
    ]


@pytest.mark.parametrize(("slug", "guide"), _header_cases())
def test_no_bare_homepage_link_comes_before_the_signup_link(slug, guide):
    """The header's Website link is the first link a reader sees.

    It used to be the bare homepage in 27 guides, so a reader who clicked it
    signed up without the code and the referral was lost. The stub generator
    wrote it that way for every new guide.
    """
    svc = catalog.get_service(slug)
    text = guide.read_text(encoding="utf-8")
    first = text.find(svc["referral"]["signup_url"])
    assert first >= 0, f"{guide.name}: the catalog's signup link is missing"
    homepage = svc["website"].rstrip("/")
    bare = [h for h in _MD_HREF.findall(text[:first]) if h.rstrip("/") == homepage]
    assert not bare, f"{guide.name}: links the bare homepage {homepage} before the referral signup link"


def test_a_new_guide_header_links_the_referral_signup():
    from scripts.new_service_stub import render

    svc = catalog.get_service("honeygain")
    header = render("honeygain").split("## Description", 1)[0]
    assert f"({svc['referral']['signup_url']})" in header
    assert f"({svc['website']})" not in header
    assert referral_note(svc) in header


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


def _js_code(fn: str) -> str:
    """The body of an app.js function, with its comments dropped.

    A count over raw source passed on a comment alone: the detail dialog's only
    "Sign Up" was the comment above its buttons, so the button could go and
    the test stay green.
    """
    body = APP_JS[APP_JS.index(f"function {fn}(") :]
    body = body[: body.index("\n  function ", 1)]
    body = re.sub(r"/\*.*?\*/|<!--.*?-->", "", body, flags=re.S)
    return re.sub(r"^\s*//.*$", "", body, flags=re.M)


@pytest.mark.parametrize(("fn", "buttons"), [("renderServiceSetupForm", 2), ("renderServiceDetail", 1)])
def test_every_sign_up_button_in_the_app_carries_the_note(fn, buttons):
    body = _js_code(fn)
    assert body.count('href="${escapeHtml(signupUrl)}"') >= buttons, fn
    assert len(re.findall(r"Sign up", body, flags=re.I)) >= buttons, fn
    assert body.count("referralNote(svc)") >= buttons, fn


@pytest.mark.parametrize("fn", ["renderServiceSetupForm", "renderServiceDetail"])
def test_a_deployed_service_keeps_its_sign_up_link(fn):
    """A deploy does not prove an account: a MystNodes node runs before anyone signs up.

    The setup form and the detail dialog used to swap Sign Up and its note for
    the dashboard once a service was deployed, so a user who deployed first and
    signed up later never saw the referral link. Desktop keeps both.
    """
    body = _js_code(fn)
    assert not re.search(r"\?\s*''\s*:\s*referralNote\(svc\)", body), f"{fn}: the referral note is hidden on deploy"
    assert not re.search(r"isDeployed[^\n]*:\s*signupUrl", body), f"{fn}: Sign Up turns into the dashboard on deploy"
    assert "else if (!isDeployed)" not in body, f"{fn}: Sign Up is shown only before deploy"


def test_the_new_user_bonus_is_shown_next_to_the_sign_up_button():
    """The bonus is the reason to use the link; it used to sit only on the detail page."""
    note_fn = APP_JS[APP_JS.index("function referralNote(svc)") :]
    note_fn = note_fn[: note_fn.index("\n  }\n")]
    assert "ref.bonus && ref.bonus.referee" in note_fn
    detail = (ROOT / "app" / "templates" / "service_detail.html").read_text(encoding="utf-8")
    assert "service.referral.bonus.referee" in detail.split("Sign Up", 1)[1]


def test_a_code_typed_by_hand_is_shown_with_a_copy_button_next_to_sign_up():
    """Dawn's extension and Gradient's form never read the code from the link.

    The note then names the code and offers a Copy button, in the app and on the
    detail page, or every user who signs up from the app credits nobody.
    """
    note_fn = APP_JS[APP_JS.index("function referralNote(svc)") :]
    note_fn = note_fn[: note_fn.index("\n  }\n")]
    assert "ref.code_entry" in note_fn
    assert 'data-action="copyText" data-a1="${escapeHtml(ref.code_entry)}"' in note_fn
    detail = (ROOT / "app" / "templates" / "service_detail.html").read_text(encoding="utf-8")
    after_sign_up = detail.split("Sign Up", 1)[1]
    assert 'data-action="copyText" data-a1="{{ service.referral.code_entry }}"' in after_sign_up


def test_every_typed_code_belongs_to_a_referral_code():
    """A typed code with no referral code would ask users to type something unchecked."""
    for svc in catalog.get_services():
        ref = svc.get("referral") or {}
        if ref.get("code_entry"):
            assert ref["code_entry"] == ref.get("code"), f"{svc['slug']}: code_entry must equal referral.code"


def test_the_detail_page_never_prints_na_for_a_missing_bonus():
    """A row of N/A hid the bonus where it existed and said nothing where it did not."""
    detail = (ROOT / "app" / "templates" / "service_detail.html").read_text(encoding="utf-8")
    card = detail[detail.index("<!-- Referral Info") : detail.index("<!-- Right: Setup")]
    assert "N/A" not in card


def test_every_recorded_bonus_belongs_to_a_referral_code():
    """A bonus without a code would promise a reward the link cannot deliver."""
    for svc in catalog.get_services():
        ref = svc.get("referral") or {}
        if ref.get("bonus"):
            assert ref.get("code"), f"{svc['slug']}: bonus recorded without a referral code"
