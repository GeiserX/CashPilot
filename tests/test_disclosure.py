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
