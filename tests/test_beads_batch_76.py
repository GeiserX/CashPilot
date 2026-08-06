"""CashPilot-e8u: telling the user which volumes hold money.

Tier 3's stated aim is visibility, not custody. Reading a minted wallet's
address needs a worker-side primitive that does not exist yet; this is the half
that needs nothing new and is worth more than it looks.

Four catalogued services keep state that exists NOWHERE else, the worker has
been able to export it since `read_critical_state` landed, and the UI never
mentioned either fact. A user could not learn their ProxyBase Markets volume
"IS the money" from anywhere in the product.

The rule these tests hold: **the catalog's own sentence is the warning.** A
generic "this volume is important" trains people to dismiss it; "This volume IS
the money: there is no server-side copy" is what makes someone act.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app import catalog, payout_registry


def _service(slug: str) -> dict:
    svc = next((s for s in catalog.get_services() if s.get("slug") == slug), None)
    assert svc is not None, f"{slug} is not in the catalog"
    return svc


class TestReadingCriticalStateOffAService:
    def test_a_minted_service_reports_its_wallet_volume(self):
        state = payout_registry.critical_state(_service("proxybase-xyz"))
        assert state, "proxybase-xyz declares a critical volume and it must surface"
        assert state[0]["target"] == "/home/proxybase/.proxybase"

    def test_the_catalogs_own_wording_is_carried_through(self):
        """Not paraphrased and not replaced by a generic warning -- the specific
        sentence is the thing that makes someone act."""
        holds = payout_registry.critical_state(_service("proxybase-xyz"))[0]["holds"]
        assert "IS the money" in holds

    def test_a_service_with_nothing_irreplaceable_reports_an_empty_list(self):
        """CONTROL. If every service reported critical state, the tests above
        would pass while the feature warned about everything, which is the same
        as warning about nothing."""
        assert payout_registry.critical_state(_service("honeygain")) == []

    def test_a_malformed_entry_is_skipped_rather_than_crashing_the_screen(self):
        service = {"docker": {"critical_volumes": ["not a mapping", {}, {"target": "/ok"}]}}
        state = payout_registry.critical_state(service)
        assert [v["target"] for v in state] == ["/ok"]

    def test_an_entry_without_holds_gets_a_plainly_generic_fallback(self):
        """A fallback that pretended to be specific would be worse than none."""
        state = payout_registry.critical_state({"docker": {"critical_volumes": [{"target": "/x"}]}})
        assert state[0]["holds"] == "Irreplaceable service state."

    def test_a_service_with_no_docker_block_does_not_raise(self):
        assert payout_registry.critical_state({}) == []


class TestTheSummaryCountsOnlyWhatIsAtRisk:
    @staticmethod
    def _registry(deployments):
        with (
            patch(
                "app.payout_registry.database.get_deployments",
                new_callable=AsyncMock,
                return_value=deployments,
            ),
            patch("app.payout_registry.database.get_deployment_spec", new_callable=AsyncMock, return_value=None),
        ):
            return asyncio.run(payout_registry.registry())

    def test_a_deployed_service_with_irreplaceable_state_is_counted(self):
        result = self._registry([{"slug": "proxybase-xyz"}])
        assert result["summary"]["holding_irreplaceable_state"] == 1

    def test_an_undeployed_one_is_not(self):
        """You cannot lose state you do not have, and a permanent warning on the
        dashboard of someone who is not running it is noise."""
        result = self._registry([])
        assert result["summary"]["holding_irreplaceable_state"] == 0

    def test_control_deploying_something_harmless_does_not_raise_the_count(self):
        """Without this, the count could be 'number of deployed services' and
        both tests above would still pass."""
        result = self._registry([{"slug": "honeygain"}])
        assert result["summary"]["deployed"] == 1
        assert result["summary"]["holding_irreplaceable_state"] == 0

    def test_every_entry_carries_the_field_so_the_ui_never_reads_undefined(self):
        for row in self._registry([])["entries"]:
            assert isinstance(row["critical_state"], list)
