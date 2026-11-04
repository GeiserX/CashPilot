"""Provider grades come only from the published criteria (app/ratings.py).

The rules file (services/_ratings.yml) is the method; each service YAML holds
verdicts with cited cons and pros; nobody types a letter. These tests pin the
parts a later edit could quietly break: no A, the band edges, the ceilings,
unknown counting as poor, the validator refusing a typed grade or a sponsor
field, and the real catalog being fully rated.
"""

from __future__ import annotations

import copy
import datetime as dt
import re
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient

from app import catalog, ratings

ROOT = Path(__file__).resolve().parents[1]
RULES = ratings.load_rules()
KEYS = ratings.criteria_keys(RULES)
TODAY = dt.date(2026, 11, 4)


def _item(criterion: str, text: str = "A cited fact.") -> dict:
    return {
        "text": text,
        "criterion": criterion,
        "kind": "terms",
        "source": "https://example.com/terms",
        "checked_on": "2026-11-04",
    }


def _rating(**verdicts: str) -> dict:
    """A valid block: every criterion good unless overridden, with the citations it needs."""
    v = dict.fromkeys(KEYS, "good")
    v.update(verdicts)
    block = {"reviewed_on": "2026-11-04", "verdicts": v, "notes": {}, "cons": [], "pros": []}
    for key, value in v.items():
        if value == "good":
            block["pros"].append(_item(key))
        elif value in ("fair", "poor"):
            block["cons"].append(_item(key, f"Con about {key}."))
        else:
            block["notes"][key] = "Searched the terms and review sites, found nothing either way."
    return block


def _svc(rating: dict | None = None, **reqs) -> dict:
    return {"slug": "x", "name": "X", "requirements": reqs, "rating": rating}


def _grade(rating: dict, **reqs) -> dict:
    return ratings.for_service(_svc(rating, **reqs), rules=RULES)


def _with_score(score: int) -> dict:
    """Verdicts that add up to exactly ``score`` with no unknowns and no poor payout/safety."""
    order = [k for k in KEYS if k not in ("payout_record", "account_safety")] + ["payout_record", "account_safety"]
    v = dict.fromkeys(KEYS, "fair")  # 1 each = 10
    remaining = score - len(KEYS)
    for key in order:
        if remaining > 0:
            v[key] = "good"
            remaining -= 1
        elif remaining < 0 and key not in ("payout_record", "account_safety"):
            v[key] = "poor"
            remaining += 1
    assert remaining == 0
    return _rating(**v)


class TestNoA:
    def test_every_criterion_good_is_a_b(self):
        result = _grade(_rating())
        assert result["score"] == result["max"] == 20
        assert result["grade"] == "B"

    def test_the_rules_have_no_a_band_and_say_why(self):
        assert [b["grade"] for b in RULES["bands"]] == ["B", "C", "D", "F"]
        assert "No provider gets an A" in RULES["cap_reason"]

    def test_the_rules_never_mention_money_to_the_project(self):
        text = ratings.RULES_PATH.read_text(encoding="utf-8").lower()
        for word in ("sponsor", "commission", "paid placement", "affiliate", "featured"):
            assert word not in text


class TestBands:
    @pytest.mark.parametrize(
        ("score", "grade"),
        [(15, "B"), (14, "C"), (11, "C"), (10, "D"), (7, "D"), (6, "F")],
    )
    def test_band_edges(self, score, grade):
        # 15/20 = 75 %, 11/20 = 55 %, 7/20 = 35 %.
        result = _grade(_with_score(score))
        assert result["score"] == score
        assert result["grade"] == grade
        assert result["caps"] == []


class TestCaps:
    def test_container_prohibited_caps_at_d(self):
        result = _grade(_rating(terms_fit="poor"), container_prohibited=True)
        assert result["band_grade"] == "B"
        assert result["grade"] == "D"
        assert [c["key"] for c in result["caps"]] == ["container_prohibited"]

    @pytest.mark.parametrize("key", ["payout_record", "account_safety"])
    def test_poor_payout_or_safety_caps_at_c(self, key):
        result = _grade(_rating(**{key: "poor"}))
        assert result["band_grade"] == "B"
        assert result["grade"] == "C"
        assert [c["key"] for c in result["caps"]] == ["poor_payout_or_safety"]

    def test_both_caps_report_in_order_and_the_stricter_wins(self):
        result = _grade(_rating(terms_fit="poor", payout_record="poor"), container_prohibited=True)
        assert [c["key"] for c in result["caps"]] == ["container_prohibited", "poor_payout_or_safety"]
        assert result["grade"] == "D"

    def test_a_cap_above_the_earned_grade_is_not_reported(self):
        # Score 6 is an F already; the C ceiling of a poor payout record changes nothing.
        rating = _with_score(6)
        rating["verdicts"]["payout_record"] = "poor"
        rating["pros"] = [p for p in rating["pros"] if p["criterion"] != "payout_record"]
        rating["cons"].append(_item("payout_record"))
        result = _grade(rating)
        assert result["grade"] == "F"
        assert result["caps"] == []


class TestUnknown:
    def test_unknown_scores_zero(self):
        result = _grade(_rating(support="unknown"))
        assert result["score"] == 18
        assert result["unknown_count"] == 1
        assert result["thin_evidence"] is False

    def test_four_unknowns_cap_at_c_as_thin_evidence(self):
        # 6 good + 4 unknown = 12 of 20 = 60 %, a C by score; add pros so B is
        # reachable on score alone and the cap is what holds it down.
        unknowns = ["support", "privacy", "identity_checks", "longevity"]
        result = _grade(_rating(**dict.fromkeys(unknowns, "unknown")))
        assert result["thin_evidence"] is True
        assert result["grade"] in ("C", "D")
        three = _grade(_rating(**dict.fromkeys(unknowns[:3], "unknown")))
        assert three["thin_evidence"] is False

    def test_thin_evidence_cap_binds_when_the_score_alone_would_be_b(self):
        rules = copy.deepcopy(RULES)
        rules["points"]["unknown"] = 2  # unknown worth as much as good: band B
        unknowns = ["support", "privacy", "identity_checks", "longevity"]
        result = ratings.for_service(_svc(_rating(**dict.fromkeys(unknowns, "unknown"))), rules=rules)
        assert result["band_grade"] == "B"
        assert result["grade"] == "C"
        assert [c["key"] for c in result["caps"]] == ["thin_evidence"]

    def test_no_block_is_not_rated_never_a_grade(self):
        result = ratings.for_service({"slug": "x"}, rules=RULES)
        assert result == {"rated": False, "grade": None, "summary": "Not rated yet"}
        assert ratings.for_service(None, rules=RULES)["rated"] is False


def _errors(rating, service=None):
    return ratings.validate(rating, service, rules=RULES, today=TODAY)


class TestValidator:
    def test_a_valid_block_passes(self):
        assert _errors(_rating(support="fair", longevity="unknown")) == []

    @pytest.mark.parametrize("key", ["grade", "override", "sponsored", "featured", "paid"])
    def test_a_typed_grade_or_paid_field_is_rejected(self, key):
        block = _rating()
        block[key] = "B" if key in ("grade", "override") else True
        assert any("not allowed" in e for e in _errors(block))

    def test_non_https_source(self):
        block = _rating()
        block["pros"][0]["source"] = "http://example.com"
        assert any("https://" in e for e in _errors(block))

    def test_future_checked_on(self):
        block = _rating()
        block["pros"][0]["checked_on"] = "2026-11-05"
        assert any("in the future" in e for e in _errors(block))

    def test_unknown_criterion_and_kind(self):
        block = _rating()
        block["pros"].append({**_item("payout_record"), "criterion": "vibes"})
        block["pros"].append({**_item("payout_record"), "kind": "rumour"})
        errs = _errors(block)
        assert any("'vibes' is not a published criterion" in e for e in errs)
        assert any("kind must be one of" in e for e in errs)

    def test_fair_with_no_con(self):
        block = _rating(support="fair")
        block["cons"] = []
        assert any("support is fair but no con cites support" in e for e in _errors(block))

    def test_good_with_no_pro(self):
        block = _rating()
        block["pros"] = [p for p in block["pros"] if p["criterion"] != "privacy"]
        assert any("privacy is good but no pro cites privacy" in e for e in _errors(block))

    def test_unknown_with_no_note(self):
        block = _rating(support="unknown")
        block["notes"] = {}
        assert any("support is unknown" in e for e in _errors(block))

    def test_a_missing_verdict(self):
        block = _rating()
        del block["verdicts"]["longevity"]
        assert any("missing ['longevity']" in e for e in _errors(block))

    def test_container_prohibited_needs_terms_fit_poor(self):
        assert any(
            "terms_fit must be poor" in e for e in _errors(_rating(), {"requirements": {"container_prohibited": True}})
        )
        assert _errors(_rating(terms_fit="poor"), {"requirements": {"container_prohibited": True}}) == []

    def test_a_typed_grade_never_shows_and_never_drops_the_service(self, tmp_path, monkeypatch):
        # The rating is a display field: a bad block makes the provider "Not
        # rated yet" at runtime, never removes a working service from the
        # catalog. CI still fails on it (TestStrictCheck below).
        svc = _load_one(tmp_path, monkeypatch, lambda d: d["rating"].__setitem__("grade", "B"))
        assert svc is not None, "an invalid rating block dropped the whole service"
        assert ratings.for_service(svc)["rated"] is False


def _load_one(tmp_path, monkeypatch, edit):
    """Load honeygain.yml, edited, through the real loader from a temp services dir."""
    data = yaml.safe_load((ROOT / "services" / "bandwidth" / "honeygain.yml").read_text(encoding="utf-8"))
    edit(data)
    (tmp_path / "honeygain.yml").write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setattr(catalog, "SERVICES_DIR", tmp_path)
    return next((s for s in catalog._load_from_disk() if s["slug"] == "honeygain"), None)


def _future(data):
    data["rating"]["reviewed_on"] = "2099-01-01"
    data["rating"]["cons"][0]["checked_on"] = "2099-01-01"


class TestRuntimeClock:
    def test_a_clock_behind_the_review_date_keeps_the_service_rated(self, tmp_path, monkeypatch):
        svc = _load_one(tmp_path, monkeypatch, _future)
        assert svc is not None, "a review date ahead of the box's clock dropped the service"
        assert ratings.for_service(svc)["rated"] is True

    def test_the_strict_validator_still_rejects_a_future_date(self):
        block = _rating()
        block["reviewed_on"] = "2099-01-01"
        assert any("future" in e for e in _errors(block))
        assert not any("future" in e for e in ratings.validate(block, rules=RULES, today=TODAY, check_future=False))


class TestStrictCheck:
    """generate_ratings_page.py --check is the CI gate the loader no longer is."""

    def test_the_real_catalog_passes(self):
        from scripts import generate_ratings_page as gen

        assert gen.problems() == []

    def test_an_invalid_block_fails(self):
        from scripts import generate_ratings_page as gen

        svc = {"slug": "x", "name": "X", "status": "active", "rating": {**_rating(), "grade": "B"}}
        assert any("not allowed" in p for p in gen.problems([svc], today=TODAY))

    def test_a_future_date_fails(self):
        from scripts import generate_ratings_page as gen

        block = _rating()
        block["reviewed_on"] = "2099-01-01"
        svc = {"slug": "x", "name": "X", "status": "active", "rating": block}
        assert any("future" in p for p in gen.problems([svc], today=TODAY))

    def test_an_unrated_live_service_fails(self):
        from scripts import generate_ratings_page as gen

        assert any(
            "not rated" in p for p in gen.problems([{"slug": "x", "name": "X", "status": "active"}], today=TODAY)
        )


def _live():
    return [s for s in catalog.get_services() if s.get("status") in ("active", "beta")]


class TestTheRealCatalog:
    def test_there_are_live_services(self):
        assert len(_live()) >= 40

    @pytest.mark.parametrize("slug", [s["slug"] for s in _live()])
    def test_every_live_service_is_rated(self, slug):
        svc = catalog.get_service(slug)
        assert "rating" in svc, f"{slug} has no rating block"
        assert ratings.validate(svc["rating"], svc) == []
        result = ratings.for_service(svc)
        assert result["rated"] and result["grade"] in ("B", "C", "D", "F")
        for item in svc["rating"].get("cons", []) + svc["rating"].get("pros", []):
            assert item["source"].startswith("https://")

    def test_earnapp_forbids_containers_so_it_is_d_or_below(self):
        result = ratings.for_service(catalog.get_service("earnapp"))
        assert result["grade"] in ("D", "F")

    def test_nobody_is_an_a(self):
        assert all(ratings.for_service(s)["grade"] != "A" for s in _live())

    # Verdicts a review found resting on user reports below the published
    # threshold (three reviewers, or two plus an independent source). Each
    # stays unknown until a source that meets it is cited.
    BELOW_THRESHOLD = [
        ("theta-edge", "earnings_realism"),  # one forum post
        ("packetstream", "earnings_realism"),  # two Trustpilot reviewers
        ("earnfm", "payout_record"),  # two Trustpilot reviewers
    ]

    @pytest.mark.parametrize(("slug", "criterion"), BELOW_THRESHOLD)
    def test_thin_user_reports_do_not_carry_a_verdict(self, slug, criterion):
        rating = catalog.get_service(slug)["rating"]
        assert rating["verdicts"][criterion] == "unknown"
        assert "threshold" in rating["notes"][criterion]
        cited = [
            item
            for item in rating.get("cons", []) + rating.get("pros", [])
            if item["criterion"] == criterion and item["kind"] == "user_reports"
        ]
        assert cited == []

    def test_grades_after_dropping_thin_reports(self):
        assert ratings.for_service(catalog.get_service("theta-edge"))["grade"] == "F"
        assert ratings.for_service(catalog.get_service("packetstream"))["grade"] == "C"

    def test_terms_fit_good_rests_on_the_providers_own_word(self):
        # "Good" means containers are allowed or the official client is an
        # image. A provider CashPilot does not run at all is fair, never good.
        for svc in _live():
            rating = svc["rating"]
            if rating["verdicts"]["terms_fit"] != "good":
                continue
            pros = [p for p in rating["pros"] if p["criterion"] == "terms_fit"]
            assert not any(p["text"].startswith("CashPilot does not run") for p in pros), svc["slug"]


class TestCatalogNarrowScreen:
    """On a phone the catalog hides some columns; header and cells must hide together."""

    def test_headers_are_hidden_by_class_not_position(self):
        css = (ROOT / "app" / "static" / "css" / "style.css").read_text(encoding="utf-8")
        js = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
        assert not re.search(r"catalog-table thead th:nth-child", css), (
            "a positional header rule shifts when a column is added"
        )
        for col in ("kind", "plat", "needs"):
            assert re.search(rf'<th scope="col" class="cat-col-{col}"', js), f"the {col} header has no class"
            assert f".catalog-table .cat-col-{col}" in css, f"the {col} header is not hidden with its cells"
        assert re.search(r'<th scope="col" class="cat-col-grade"', js)
        assert ".cat-col-grade" not in css, "the Grade header must stay visible"


@asynccontextmanager
async def _noop_lifespan(a):
    yield


@pytest.fixture
def client():
    from app.main import app

    app.router.lifespan_context = _noop_lifespan
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _owner():
    return patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "admin", "r": "owner"})


class TestApi:
    def test_available_carries_the_grade(self, client):
        svcs = [{"slug": "hg", "name": "HG", "status": "active", "docker": {"image": "t"}, "rating": _rating()}]
        with (
            _owner(),
            patch("app.main.catalog.get_services", return_value=svcs),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[]),
        ):
            data = client.get("/api/services/available").json()
        assert data[0]["rating_result"]["grade"] == "B"

    def test_detail_carries_the_grade(self, client):
        svc = {"slug": "hg", "name": "HG", "docker": {"image": "t"}, "rating": _rating(payout_record="poor")}
        with (
            _owner(),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_custom_images", new_callable=AsyncMock, return_value={}),
        ):
            data = client.get("/api/services/hg").json()
        assert data["rating_result"]["grade"] == "C"
        assert data["rating_result"]["top_cons"][0]["criterion"] == "payout_record"

    def test_a_custom_service_is_not_rated(self, client):
        custom = {"slug": "custom-abc", "name": "Mine", "custom": True, "docker": {"image": "t"}, "rating": _rating()}
        with (
            _owner(),
            patch("app.main.catalog.get_service", return_value=None),
            patch("app.main._custom_service", new_callable=AsyncMock, return_value=custom),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_custom_images", new_callable=AsyncMock, return_value={}),
        ):
            data = client.get("/api/services/custom-abc").json()
        assert data["rating_result"]["rated"] is False


class TestDocsPage:
    def test_the_generated_page_is_current(self):
        from scripts import generate_ratings_page as gen

        assert gen.render_file(gen.PAGE.read_text(encoding="utf-8")) == gen.PAGE.read_text(encoding="utf-8")

    def test_a_hand_edit_inside_the_markers_is_caught(self):
        from scripts import generate_ratings_page as gen

        page = gen.PAGE.read_text(encoding="utf-8")
        edited = re.sub(r"(\| )([BCDF])( \|)", r"\1A\3", page, count=1)
        assert edited != page
        assert gen.render_file(edited) != edited

    def test_the_page_does_not_claim_desktop_shows_grades_yet(self):
        page = (ROOT / "docs" / "ratings.md").read_text(encoding="utf-8")
        assert "CashPilot-Desktop show the same grade" not in page

    def test_the_page_has_no_signup_links_or_payment_wording(self):
        page = (ROOT / "docs" / "ratings.md").read_text(encoding="utf-8").lower()
        for svc in catalog.get_services():
            url = (svc.get("referral") or {}).get("signup_url")
            if url:
                assert url.lower() not in page, f"{svc['slug']} signup link on the ratings page"
        for word in ("commission", "sponsor", "affiliate", "paid placement"):
            assert word not in page
