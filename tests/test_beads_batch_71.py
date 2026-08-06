"""CashPilot-luj tier 1, the registry: joining the catalog to what was deployed.

The catalog says each service's payout MODEL; the deployed spec holds the address
the container was really given. This module joins them so "which addresses do my
services pay to?" is one screen rather than an audit of every worker.

FOUR STATES THAT MUST NOT COLLAPSE INTO EACH OTHER, because collapsing them is
how a registry starts lying to the person who trusts it:

  external + resolved   -> show the address
  external + nothing    -> "not set", and ACTIONABLE: money may be going nowhere
  internal              -> there is NO address by design; a blank would read as
                           "you forgot something" when nothing is configurable
  unknown               -> unclassified; say so rather than imply user error

NO PRIVATE KEYS anywhere in this tier.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app import payout_registry


class TestReadingTheAddressOutOfADeployedSpec:
    def test_a_mapping_style_environment(self):
        spec = {"environment": {"WALLET": "0xabc"}}
        assert payout_registry.address_from_spec(spec, "WALLET") == "0xabc"

    def test_a_list_style_environment(self):
        """Docker specs take both shapes; only supporting one silently returns
        "not set" for every service deployed the other way."""
        spec = {"environment": ["TZ=UTC", "WALLET=0xdef"]}
        assert payout_registry.address_from_spec(spec, "WALLET") == "0xdef"

    def test_the_env_key_is_also_accepted(self):
        assert payout_registry.address_from_spec({"env": {"WALLET": "0x1"}}, "WALLET") == "0x1"

    def test_a_blank_value_is_not_an_address(self):
        """An env var present but empty is exactly the "you deployed it without
        setting this" case, and it must NOT read as configured."""
        assert payout_registry.address_from_spec({"environment": {"WALLET": "   "}}, "WALLET") is None

    def test_a_missing_spec_is_none_rather_than_an_error(self):
        assert payout_registry.address_from_spec(None, "WALLET") is None
        assert payout_registry.address_from_spec({}, "WALLET") is None

    def test_a_prefix_collision_does_not_match(self):
        """WALLET_TYPE must not satisfy a lookup for WALLET."""
        spec = {"environment": ["WALLET_TYPE=erc20"]}
        assert payout_registry.address_from_spec(spec, "WALLET") is None


class TestTheFourStatesStayDistinct:
    def test_external_with_an_address_shows_it(self):
        row = payout_registry.entry(
            {"slug": "storj", "payout": {"model": "external", "address_env": "WALLET"}},
            {"environment": {"WALLET": "0xabc"}},
            deployed=True,
        )
        assert row["address"] == "0xabc"
        assert row["address_missing"] is False

    def test_external_without_an_address_is_flagged_as_actionable(self):
        """The state that matters: deployed, expects an address, has none."""
        row = payout_registry.entry(
            {"slug": "storj", "payout": {"model": "external", "address_env": "WALLET"}},
            {"environment": {}},
            deployed=True,
        )
        assert row["address"] is None
        assert row["address_missing"] is True

    def test_internal_is_never_flagged_as_missing(self):
        """There is nothing to configure. Flagging it would send the user
        looking for a setting that does not exist."""
        row = payout_registry.entry({"slug": "honeygain", "payout": {"model": "internal"}}, None, deployed=True)
        assert row["address"] is None
        assert row["address_missing"] is False

    def test_unknown_is_never_flagged_as_missing(self):
        """Unclassified is OUR gap, not the user's."""
        row = payout_registry.entry({"slug": "x", "payout": {"model": "unknown"}}, None, deployed=True)
        assert row["address_missing"] is False

    def test_minted_is_never_flagged_as_missing(self):
        """The container made its own wallet; the user was never asked for one."""
        row = payout_registry.entry({"slug": "nosana", "payout": {"model": "minted"}}, None, deployed=True)
        assert row["address_missing"] is False

    def test_an_internal_service_never_reads_an_address(self):
        """Even if a spec happens to carry something address-shaped, an internal
        payout has no address -- reporting one would invent a destination."""
        row = payout_registry.entry(
            {"slug": "honeygain", "payout": {"model": "internal", "address_env": "WALLET"}},
            {"environment": {"WALLET": "0xdead"}},
            deployed=True,
        )
        assert row["address"] is None


class TestAnUnrecognisedModelDegradesToUnknown:
    def test_it_does_not_raise(self):
        """A catalog typo must not take the screen down."""
        row = payout_registry.entry({"slug": "x", "payout": {"model": "wat"}}, None, deployed=False)
        assert row["model"] == "unknown"

    def test_a_service_with_no_payout_block_is_unknown(self):
        row = payout_registry.entry({"slug": "x"}, None, deployed=False)
        assert row["model"] == "unknown"


class TestTheRegistryOverTheRealCatalog:
    @staticmethod
    def _registry(deployments=None, spec=None):
        with (
            patch(
                "app.payout_registry.database.get_deployments", new_callable=AsyncMock, return_value=deployments or []
            ),
            patch("app.payout_registry.database.get_deployment_spec", new_callable=AsyncMock, return_value=spec),
        ):
            return asyncio.run(payout_registry.registry())

    def test_it_covers_every_service_in_the_catalog(self):
        """Undeployed services are included on purpose: someone choosing what to
        run wants to know Storj needs a wallet BEFORE deploying it."""
        from app import catalog

        result = self._registry()
        assert result["summary"]["total"] == len(catalog.get_services())
        assert result["summary"]["total"] >= 40

    def test_every_row_declares_one_of_the_four_models(self):
        for row in self._registry()["entries"]:
            assert row["model"] in payout_registry.MODELS, row

    def test_a_deployed_service_resolves_its_address(self):
        result = self._registry(deployments=[{"slug": "storj"}], spec={"environment": {"WALLET": "0xfeed"}})
        storj = next(r for r in result["entries"] if r["slug"] == "storj")
        assert storj["deployed"] is True
        assert storj["address"] == "0xfeed"

    def test_deployed_services_sort_first(self):
        """The rows a user can act on belong at the top."""
        result = self._registry(deployments=[{"slug": "storj"}], spec={"environment": {"WALLET": "0x1"}})
        assert result["entries"][0]["deployed"] is True

    def test_needs_an_address_counts_only_deployed_services(self):
        """An undeployed Storj has no address and that is fine -- counting it
        would put a permanent nag on the dashboard of someone not running it."""
        result = self._registry(deployments=[], spec=None)
        assert result["summary"]["needs_an_address"] == 0

    def test_a_database_failure_still_renders_the_screen(self):
        """The registry is read-only reporting. It must not be the thing that
        takes the page down."""
        with (
            patch(
                "app.payout_registry.database.get_deployments",
                new_callable=AsyncMock,
                side_effect=RuntimeError("db down"),
            ),
            patch("app.payout_registry.database.get_deployment_spec", new_callable=AsyncMock, return_value=None),
        ):
            result = asyncio.run(payout_registry.registry())
        assert result["summary"]["total"] >= 40
        assert result["summary"]["deployed"] == 0

    def test_an_undecryptable_spec_does_not_hide_the_service(self):
        """A spec that cannot be decrypted means UNKNOWN address, not a missing
        row -- and the row stays honest by reporting the address as unset."""
        with (
            patch(
                "app.payout_registry.database.get_deployments", new_callable=AsyncMock, return_value=[{"slug": "storj"}]
            ),
            patch(
                "app.payout_registry.database.get_deployment_spec",
                new_callable=AsyncMock,
                side_effect=RuntimeError("cannot decrypt"),
            ),
        ):
            result = asyncio.run(payout_registry.registry())
        storj = next(r for r in result["entries"] if r["slug"] == "storj")
        assert storj["deployed"] is True
        assert storj["address"] is None
        assert storj["address_missing"] is True


class TestNoSecretIsEverExposed:
    def test_a_row_carries_no_key_shaped_field(self):
        from app import catalog

        with (
            patch("app.payout_registry.database.get_deployments", new_callable=AsyncMock, return_value=[]),
            patch("app.payout_registry.database.get_deployment_spec", new_callable=AsyncMock, return_value=None),
        ):
            result = asyncio.run(payout_registry.registry())
        assert catalog.get_services()
        for row in result["entries"]:
            for key in row:
                assert not any(bad in key.lower() for bad in ("private", "secret", "seed", "mnemonic", "keystore")), (
                    f"{row['slug']}: the registry exposes {key}"
                )

    def test_the_module_reads_no_credential_store(self):
        """It joins the catalog to deployment specs and nothing else."""
        from pathlib import Path

        source = (Path(__file__).resolve().parents[1] / "app" / "payout_registry.py").read_text()
        for forbidden in ("get_credentials", "decrypt_value", "fernet", "private_key"):
            assert forbidden not in source, f"the registry touches {forbidden}"


@pytest.mark.parametrize("model", ["external", "internal", "minted", "unknown"])
def test_every_documented_model_is_accepted(model):
    row = payout_registry.entry({"slug": "x", "payout": {"model": model}}, None, deployed=False)
    assert row["model"] == model
