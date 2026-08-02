"""Per-service disclosure (CashPilot-66x).

"Is this malware?" is the most common reaction to software in this space, and a
fair one: the user runs closed-source third-party containers that route traffic
through their home connection.

The tests that matter are the ones about absence. A service nobody has documented
is exactly the one to be careful with, so an undocumented service must never read
as a safe one, and a half-filled block must not look complete.
"""

from __future__ import annotations

import pytest

from app import catalog, disclosure


class TestAbsenceIsNotSafety:
    def test_an_undocumented_service_says_so_explicitly(self):
        out = disclosure.for_service({"slug": "x", "name": "X"})
        assert out["documented"] is False
        assert "not a statement that it is safe" in out["summary"]
        assert out["unanswered"] == list(disclosure.FIELDS)

    def test_a_missing_service_is_not_an_error_but_is_undocumented(self):
        out = disclosure.for_service(None)
        assert out["documented"] is False
        assert out["answers"] == {}

    def test_a_partly_documented_service_admits_the_gaps(self):
        """A half-filled disclosure that looks complete is worse than an empty one."""
        out = disclosure.for_service({"slug": "x", "name": "X", "disclosure": {"sells": "Bandwidth."}})
        assert out["documented"] is True
        assert "still unanswered" in out["summary"]
        assert "third_party_traffic" in out["unanswered"]

    def test_blank_values_count_as_unanswered(self):
        out = disclosure.for_service({"slug": "x", "disclosure": {"sells": "   ", "isp_risk": ""}})
        assert out["answers"] == {}
        assert set(out["unanswered"]) == set(disclosure.FIELDS)

    def test_an_explicit_unknown_is_kept_as_an_answer(self):
        """Somebody looked and could not find out — different from nobody looking."""
        out = disclosure.for_service(
            {"slug": "x", "disclosure": {"third_party_traffic": "unknown - the provider does not say"}}
        )
        assert "third_party_traffic" in out["answers"]
        assert "third_party_traffic" not in out["unanswered"]


class TestThirdPartyTraffic:
    """The single most consequential fact about most services in this catalog."""

    def test_yes_and_no_are_read(self):
        assert (
            disclosure.routes_third_party_traffic({"disclosure": {"third_party_traffic": "Yes. Strangers..."}}) is True
        )
        assert (
            disclosure.routes_third_party_traffic({"disclosure": {"third_party_traffic": "No. You store..."}}) is False
        )

    def test_undocumented_is_none_never_false(self):
        """Not documented must not collapse into 'no' — that is the dangerous default."""
        assert disclosure.routes_third_party_traffic({"disclosure": {}}) is None
        assert disclosure.routes_third_party_traffic({}) is None
        assert disclosure.routes_third_party_traffic(None) is None

    def test_an_explicit_unknown_is_none(self):
        assert disclosure.routes_third_party_traffic({"disclosure": {"third_party_traffic": "unknown"}}) is None

    def test_unparseable_prose_is_none_rather_than_guessed(self):
        assert disclosure.routes_third_party_traffic({"disclosure": {"third_party_traffic": "it depends"}}) is None


class TestCoverageIsHonest:
    def test_it_reports_the_gap_not_just_the_documented_subset(self):
        services = [
            {"slug": "a", "disclosure": {"sells": "x"}},
            {"slug": "b"},
            {"slug": "c"},
        ]
        out = disclosure.coverage(services)
        assert out == {
            "total": 3,
            "documented": 1,
            "undocumented": 2,
            "undocumented_slugs": ["b", "c"],
        }


class TestAgainstTheRealCatalog:
    @pytest.mark.parametrize("slug", ["mysterium", "anyone-protocol", "proxybase-xyz", "storj"])
    def test_the_documented_services_answer_every_question(self, slug):
        out = disclosure.for_service(catalog.get_service(slug))
        assert out["documented"] is True
        assert out["unanswered"] == [], f"{slug} left {out['unanswered']} unanswered"

    def test_the_services_that_resell_the_users_ip_say_so(self):
        """Getting this wrong would understate the real risk of the category."""
        for slug in ("mysterium", "anyone-protocol", "proxybase-xyz"):
            assert disclosure.routes_third_party_traffic(catalog.get_service(slug)) is True, slug

    def test_storj_correctly_says_it_does_not(self):
        assert disclosure.routes_third_party_traffic(catalog.get_service("storj")) is False

    def test_every_declared_disclosure_uses_known_fields(self):
        """A typo'd key would be silently dropped rather than shown."""
        for svc in catalog.get_services():
            for key in svc.get("disclosure") or {}:
                assert key in disclosure.FIELDS, f"{svc['slug']}: unknown disclosure field {key!r}"

    def test_the_catalog_can_report_its_own_incompleteness(self):
        out = disclosure.coverage(catalog.get_services())
        assert out["total"] > out["documented"], "expected the catalog to be partly documented"
        assert out["undocumented_slugs"], "the gap must be enumerable, not just counted"


class TestEndpoints:
    def _call(self, fn, *args):
        import asyncio
        from unittest.mock import MagicMock, patch

        from app import main

        async def run():
            with patch.object(main, "_require_auth_api", lambda r: None):
                return await fn(MagicMock(), *args)

        return asyncio.run(run())

    def test_a_documented_service_returns_its_answers(self):
        from app import main

        out = self._call(main.api_service_disclosure, "mysterium")
        assert out["documented"] is True
        assert "third_party_traffic" in out["answers"]

    def test_an_undocumented_service_returns_the_honest_summary(self):
        from app import main

        out = self._call(main.api_service_disclosure, "honeygain")
        assert out["documented"] is False
        assert "not a statement that it is safe" in out["summary"]

    def test_an_unknown_slug_is_a_404(self):
        from fastapi import HTTPException

        from app import main

        with pytest.raises(HTTPException) as exc:
            self._call(main.api_service_disclosure, "no-such-service")
        assert exc.value.status_code == 404

    def test_coverage_endpoint_names_the_undocumented(self):
        from app import main

        out = self._call(main.api_disclosure_coverage)
        assert out["undocumented"] > 0
        assert "honeygain" in out["undocumented_slugs"]


class TestTheVerdictWordMustStandAlone:
    """A phrase beginning with "no" that MEANS yes is the worst silent answer.

    Prefix matching read "notably, strangers DO use your IP" as no, and a plain
    word boundary read "No longer — since v2 they route traffic" as no. Both
    invert the single most consequential fact in the catalog.
    """

    @pytest.mark.parametrize(
        "prose",
        [
            "No longer — since v2 they route traffic",
            "No longer",
            "Normally no, but exit nodes do relay",
            "Nobody knows",
            "None documented, but likely yes",
            "Not exactly - only for premium buyers",
            "notably, strangers DO use your IP",
            "nothing is routed",
            "yesterday's docs said no",
            "TRUE-ish",
            "it depends",
        ],
    )
    def test_prose_we_cannot_parse_is_unknown_never_a_verdict(self, prose):
        assert disclosure.parse_verdict(prose) is None

    @pytest.mark.parametrize(
        ("prose", "expected"),
        [
            ("Yes. Strangers route through you.", True),
            ("Yes, buyers proxy through your connection.", True),
            ("No. You store encrypted fragments.", False),
            ("no", False),
            ("yes", True),
            ("unknown - the provider does not say", None),
        ],
    )
    def test_a_standalone_verdict_is_read(self, prose, expected):
        assert disclosure.parse_verdict(prose) is expected

    def test_yaml_booleans_are_handled_because_the_schema_invites_them(self):
        """An unquoted `no:` in YAML arrives here as a real bool, not a string."""
        assert disclosure.parse_verdict(False) is False
        assert disclosure.parse_verdict(True) is True

    def test_every_declared_answer_in_the_real_catalog_is_machine_readable(self):
        """Unparseable prose must fail CI, not silently become "undocumented"."""
        for svc in catalog.get_services():
            raw = (svc.get("disclosure") or {}).get("third_party_traffic")
            if raw is None:
                continue
            text = raw if isinstance(raw, bool) else str(raw).strip()
            assert disclosure.parse_verdict(text) is not None or str(text).lower().startswith("unknown"), (
                f"{svc['slug']}: third_party_traffic {text!r} does not open with a standalone "
                "yes/no/unknown, so it would be reported as undocumented"
            )


class TestFiveUnknownsIsNotADocumentedService:
    ALL_UNKNOWN = {f: "unknown - the provider does not say" for f in disclosure.FIELDS}

    def test_it_does_not_claim_to_be_fully_documented(self):
        out = disclosure.for_service({"slug": "x", "name": "ShadyNode", "disclosure": self.ALL_UNKNOWN})
        assert "fully documented" not in out["summary"]
        assert "NONE could be answered" in out["summary"]
        assert "not as reassurance" in out["summary"]

    def test_the_unknowns_are_counted_separately(self):
        out = disclosure.for_service({"slug": "x", "disclosure": self.ALL_UNKNOWN})
        assert set(out["unknown"]) == set(disclosure.FIELDS)
        assert out["unanswered"] == []

    def test_a_genuinely_answered_service_still_reads_as_complete(self):
        out = disclosure.for_service(catalog.get_service("storj"))
        assert out["summary"].endswith("is fully documented below.")
        assert out["unknown"] == []


class TestThePayloadCarriesTheFactsAConsumerNeeds:
    def test_the_tri_state_is_exposed_so_nobody_reimplements_the_parse(self):
        assert disclosure.for_service(catalog.get_service("storj"))["routes_third_party_traffic"] is False
        assert disclosure.for_service(catalog.get_service("mysterium"))["routes_third_party_traffic"] is True
        assert disclosure.for_service({"slug": "x"})["routes_third_party_traffic"] is None

    def test_the_most_consequential_gap_is_flagged_on_its_own(self):
        """1-of-5 missing reads the same as 1-of-5 missing — unless it is THIS one."""
        answered_but_not_the_key_one = disclosure.for_service(
            {"slug": "x", "disclosure": {f: "Something." for f in disclosure.FIELDS if f != "third_party_traffic"}}
        )
        assert answered_but_not_the_key_one["critical_unanswered"] is True

        other_gap = disclosure.for_service(
            {"slug": "x", "disclosure": {f: "Something." for f in disclosure.FIELDS if f != "account_rules"}}
        )
        assert other_gap["critical_unanswered"] is False

    def test_partial_documentation_is_countable_not_just_a_boolean(self):
        out = disclosure.for_service({"slug": "x", "disclosure": {"sells": "Bandwidth."}})
        assert (out["answered_count"], out["total_questions"]) == (1, 5)

    def test_every_return_path_has_the_same_shape(self):
        """A consumer reading out["questions"] must not KeyError on one branch."""
        shapes = [
            sorted(disclosure.for_service(None)),
            sorted(disclosure.for_service({"slug": "x"})),
            sorted(disclosure.for_service(catalog.get_service("storj"))),
        ]
        assert shapes[0] == shapes[1] == shapes[2]

    def test_the_questions_dict_is_a_copy_not_the_module_constant(self):
        out = disclosure.for_service({"slug": "x"})
        out["questions"]["sells"] = "mutated"
        assert disclosure.FIELDS["sells"] != "mutated"


class TestMalformedCatalogEntries:
    def test_a_non_mapping_disclosure_does_not_500(self):
        """`disclosure: TODO` loaded fine and then crashed at request time."""
        assert disclosure.for_service({"slug": "x", "disclosure": "TODO"})["documented"] is False
        assert disclosure.for_service({"slug": "x", "disclosure": ["a"]})["documented"] is False

    def test_the_catalog_loader_now_rejects_it_up_front(self):
        from pathlib import Path

        from app import catalog as cat

        errors = cat._validate(
            {
                "name": "X",
                "slug": "x",
                "category": "bandwidth",
                "status": "active",
                "description": "d",
                "docker": {},
                "disclosure": "TODO",
            },
            Path("x.yml"),
        )
        assert any("disclosure must be a mapping" in e for e in errors)

    def test_a_null_slug_does_not_crash_coverage(self):
        assert disclosure.coverage([{"slug": None}, {"slug": "b"}])["undocumented"] == 2

    def test_coverage_and_for_service_agree_on_what_documented_means(self):
        """coverage() re-tested dict truthiness and so OVERSTATED coverage."""
        blank = {"slug": "a", "disclosure": {"sells": "   "}}
        typo = {"slug": "b", "disclosure": {"typo_field": "x"}}
        assert disclosure.coverage([blank, typo])["documented"] == 0
        assert disclosure.for_service(blank)["documented"] is False
        assert disclosure.for_service(typo)["documented"] is False


class TestTheEndpointsRequireAuth:
    """Deleting the guard left all the other endpoint tests green."""

    def _unauthenticated(self, fn, *args):
        import asyncio
        from unittest.mock import MagicMock

        request = MagicMock()
        request.session = {}
        request.headers = {}
        request.cookies = {}
        return asyncio.run(fn(request, *args))

    def test_the_per_service_endpoint_rejects_an_anonymous_caller(self):
        from fastapi import HTTPException

        from app import main

        with pytest.raises(HTTPException) as exc:
            self._unauthenticated(main.api_service_disclosure, "mysterium")
        assert exc.value.status_code == 401

    def test_the_coverage_endpoint_rejects_an_anonymous_caller(self):
        from fastapi import HTTPException

        from app import main

        with pytest.raises(HTTPException) as exc:
            self._unauthenticated(main.api_disclosure_coverage)
        assert exc.value.status_code == 401
