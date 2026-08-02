"""Lateral containment and the attribution notice (CashPilot-q0o).

The risk this addresses is not container escape. It is that someone else's
traffic exits the user's address and is attributed to them, plus a hostile
image's realistic prize: the home LAN it was handed.

The tests that matter are about WHEN the warning fires. A warning on a storage
node would be false and would train people to click past the ones that are real;
silence on an undocumented service would let "nobody checked" read as "no risk".
"""

from __future__ import annotations

import pytest

from app import catalog
from app import lan_isolation as li

BANDWIDTH = {"slug": "x", "name": "X", "disclosure": {"third_party_traffic": "Yes. Strangers route through you."}}
STORAGE = {"slug": "y", "name": "Y", "disclosure": {"third_party_traffic": "No. You store fragments."}}
UNDOCUMENTED = {"slug": "z", "name": "Z"}


class TestTheWarningFiresExactlyWhereItIsTrue:
    def test_a_service_that_resells_the_ip_gets_the_full_notice(self):
        notice = li.attribution_notice(BANDWIDTH)
        assert notice["documented"] is True
        assert "sells access to your internet connection" in notice["headline"]
        assert "attributed to you" in notice["body"] or "looks like you" in notice["body"]

    def test_a_storage_node_gets_no_warning_at_all(self):
        """A false warning here trains people to click past the real ones."""
        assert li.attribution_notice(STORAGE) is None

    def test_an_undocumented_service_says_nobody_checked(self):
        """Silence would let "not documented" read as "no risk"."""
        notice = li.attribution_notice(UNDOCUMENTED)
        assert notice["documented"] is False
        assert "Nobody has documented" in notice["headline"]
        assert "not the same as it being safe" in notice["body"]

    def test_the_notice_names_its_own_source(self):
        assert li.attribution_notice(BANDWIDTH)["source"]
        assert li.attribution_notice(UNDOCUMENTED)["source"]

    def test_it_tells_the_user_to_check_their_isp_terms(self):
        """The account that gets suspended is theirs."""
        assert "ISP" in li.attribution_notice(BANDWIDTH)["body"]

    def test_every_notice_mentions_the_lateral_risk(self):
        for service in (BANDWIDTH, UNDOCUMENTED):
            assert "LAN" in li.attribution_notice(service)["lateral_note"]


class TestAgainstTheRealCatalog:
    @pytest.mark.parametrize("slug", ["mysterium", "anyone-protocol", "proxybase-xyz"])
    def test_the_documented_resellers_all_warn(self, slug):
        notice = li.attribution_notice(catalog.get_service(slug))
        assert notice is not None and notice["documented"] is True

    def test_storj_does_not_warn(self):
        assert li.attribution_notice(catalog.get_service("storj")) is None

    def test_most_of_the_catalog_is_undocumented_and_says_so(self):
        """46 of 50 today — the notice must not imply they are all safe."""
        undocumented = [
            s["slug"] for s in catalog.get_services() if (li.attribution_notice(s) or {}).get("documented") is False
        ]
        assert len(undocumented) > 10


class TestWhatCanActuallyBeIsolated:
    def test_a_host_networked_service_cannot_be_confined_by_a_bridge(self):
        out = li.assess(catalog.get_service("mysterium"))
        assert out["verdict"] == li.NOT_ISOLATABLE
        assert "VLAN or a separate machine" in out["summary"]

    def test_a_service_needing_inbound_ports_needs_exceptions(self):
        """Missing these costs a storage node its held payout balance."""
        out = li.assess(catalog.get_service("storj"))
        assert out["verdict"] == li.NEEDS_EXCEPTIONS
        kinds = {e["kind"] for e in out["exceptions"]}
        assert "inbound_port" in kinds

    def test_a_plain_outbound_only_service_is_isolatable(self):
        out = li.assess(catalog.get_service("honeygain"))
        assert out["verdict"] == li.ISOLATABLE
        assert out["exceptions"] == []

    def test_every_exception_explains_itself(self):
        for svc in catalog.get_services():
            for exception in li.assess(svc)["exceptions"]:
                assert exception["detail"].endswith("."), f"{svc['slug']}: unexplained exception"

    def test_the_blocked_list_covers_every_private_range_and_metadata(self):
        blocked = li.assess(catalog.get_service("honeygain"))["blocked_destinations"]
        assert "10.0.0.0/8" in blocked
        assert "172.16.0.0/12" in blocked
        assert "192.168.0.0/16" in blocked
        # Cloud metadata: a container reaching it on a VPS can mint credentials.
        assert "169.254.0.0/16" in blocked

    def test_an_unknown_service_is_not_claimed_isolatable(self):
        assert li.assess(None)["verdict"] == li.NOT_ISOLATABLE


class TestItDoesNotTouchTheHostNetwork:
    def test_the_module_only_produces_text(self):
        """Creating bridges and firewall rules is the operator's decision."""
        import ast
        import pathlib

        tree = ast.parse(pathlib.Path(li.__file__).read_text(encoding="utf-8"))
        called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        for forbidden in ("run", "check_output", "Popen", "create", "connect", "remove"):
            assert forbidden not in called, f"lan_isolation calls {forbidden!r} — it must only describe"

    def test_it_imports_no_docker_or_subprocess_client(self):
        import ast
        import pathlib

        tree = ast.parse(pathlib.Path(li.__file__).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert not (imported & {"docker", "subprocess", "os", "httpx"})

    def test_the_snippet_warns_that_docker_alone_is_not_enough(self):
        """A bridge without host firewall rules does not stop LAN access."""
        snippet = li.compose_snippet()
        assert "does NOT stop" in snippet
        assert "192.168.0.0/16" in snippet

    def test_the_snippet_warns_about_the_exceptions(self):
        assert "silently stop earning" in li.compose_snippet()


class TestEndpoints:
    def _call(self, fn, *args):
        import asyncio
        from unittest.mock import MagicMock, patch

        from app import main

        with patch.object(main, "_require_auth_api", lambda r: None):
            return asyncio.run(fn(MagicMock(), *args))

    def test_deploy_risk_returns_both_halves(self):
        from app import main

        out = self._call(main.api_deploy_risk, "mysterium")
        assert out["attribution"]["documented"] is True
        assert out["isolation"]["verdict"] == li.NOT_ISOLATABLE

    def test_deploy_risk_for_a_storage_node_has_no_attribution_notice(self):
        from app import main

        assert self._call(main.api_deploy_risk, "storj")["attribution"] is None

    def test_an_unknown_service_is_a_404(self):
        from fastapi import HTTPException

        from app import main

        with pytest.raises(HTTPException) as exc:
            self._call(main.api_deploy_risk, "no-such-service")
        assert exc.value.status_code == 404

    def test_the_guide_sorts_services_into_the_three_buckets(self):
        from app import main

        out = self._call(main.api_isolation_guide)
        assert "honeygain" in out["isolatable"]
        assert any(s["slug"] == "mysterium" for s in out["not_isolatable"])
        assert any(s["slug"] == "storj" for s in out["needs_exceptions"])

    def test_the_guide_hands_back_a_pasteable_snippet(self):
        from app import main

        out = self._call(main.api_isolation_guide)
        assert "driver: bridge" in out["compose_snippet"]
        assert out["network_name"] in out["compose_snippet"]
