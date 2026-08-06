"""CashPilot-luj, tier 1: where does my money actually go?

A user could not answer the most basic financial question about their own
installation. Payout destinations existed only inside container env vars and
config files, scattered across every worker, with no screen listing them.

This is the CATALOG foundation: every service declares its payout MODEL, and
where applicable the address and how it is set. The catalog stays the source of
truth, so adding a service is one YAML block rather than an edit to a route.

THE DESIGN DECISION THAT SHAPES EVERYTHING: the model is a first-class field, not
an address that happens to be empty. Three real payout mechanisms exist and they
are not variations of one thing —

  * external: the user supplies an address they own. There IS one to show.
  * internal: the service holds an off-chain balance and pays out on request.
    There is NO address, and a blank field would read as "you forgot to
    configure this" when nothing is configurable.
  * minted:   the container generates its own wallet and accrues to it. The user
    has typically never seen it.

and a fourth value that is deliberate rather than a placeholder:

  * unknown:  not yet determined. The acceptance criteria ask for this
    explicitly — "visibly flagged, not silently blank".

STRICTLY NO PRIVATE KEYS. This tier is a registry of public addresses and payout
mechanics. That is why it comes first: most of the answer, zero custody risk.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SERVICE_FILES = sorted(p for p in (ROOT / "services").glob("*/*.yml") if not p.name.startswith("_"))
MODELS = {"external", "internal", "minted", "unknown"}


def service(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def payout(path: Path) -> dict:
    return service(path).get("payout") or {}


def ids(paths):
    return [f"{p.parent.name}/{p.stem}" for p in paths]


class TestEveryServiceDeclaresWhereMoneyGoes:
    def test_the_catalog_is_not_empty(self):
        """Otherwise every parametrised test below is vacuously true."""
        assert len(SERVICE_FILES) >= 40

    @pytest.mark.parametrize("path", SERVICE_FILES, ids=ids(SERVICE_FILES))
    def test_it_has_a_payout_block(self, path):
        assert payout(path), f"{path.name} declares no payout model"

    @pytest.mark.parametrize("path", SERVICE_FILES, ids=ids(SERVICE_FILES))
    def test_the_model_is_one_of_the_four(self, path):
        model = payout(path).get("model")
        assert model in MODELS, f"{path.name}: model={model!r} is not one of {sorted(MODELS)}"


class TestTheModelAndTheFieldsAgree:
    """A model that contradicts its own fields would make the screen lie."""

    @pytest.mark.parametrize("path", SERVICE_FILES, ids=ids(SERVICE_FILES))
    def test_only_an_external_payout_names_an_address_env(self, path):
        block = payout(path)
        if "address_env" in block:
            assert block["model"] == "external", (
                f"{path.name}: only an external payout has a user-supplied address to read from an env var"
            )

    @pytest.mark.parametrize("path", SERVICE_FILES, ids=ids(SERVICE_FILES))
    def test_an_address_env_actually_exists_on_the_service(self, path):
        """Naming an env var the container never receives would send the registry
        looking for an address that is never set."""
        block = payout(path)
        env_name = block.get("address_env")
        if not env_name:
            return
        # docker.env is a LIST of {key, label, ...}, which is where a service
        # actually declares what the container receives. My first version looked
        # under credentials.fields and docker.environment -- neither of which
        # exists in this schema -- so it found nothing and failed storj, which is
        # the one service that genuinely does declare WALLET. The test was right
        # to fail; the lookup was wrong.
        declared = {
            str(item.get("key"))
            for item in ((service(path).get("docker") or {}).get("env") or [])
            if isinstance(item, dict)
        }
        assert env_name in declared, f"{path.name}: address_env={env_name!r} is not a field this service declares"

    @pytest.mark.parametrize("path", SERVICE_FILES, ids=ids(SERVICE_FILES))
    def test_an_internal_payout_registers_no_address(self, path):
        """There is nothing to register until the user withdraws. Claiming
        otherwise is the exact error this model exists to prevent."""
        block = payout(path)
        if block.get("model") == "internal":
            assert "address_env" not in block, f"{path.name}: an internal balance has no address to read"

    @pytest.mark.parametrize("path", SERVICE_FILES, ids=ids(SERVICE_FILES))
    def test_an_unknown_payout_claims_nothing_else(self, path):
        """`unknown` must not carry a chain or an address, or it is not unknown."""
        block = payout(path)
        if block.get("model") == "unknown":
            for field in ("chain", "address_env", "address_source"):
                assert field not in block, f"{path.name}: model=unknown but it declares {field}"


class TestTheThingsTheResearchEstablished:
    """Spot-checks on the services whose payout mechanics were actually
    researched, so a careless bulk edit cannot quietly flatten them."""

    @staticmethod
    def _payout(slug: str) -> dict:
        path = next(p for p in SERVICE_FILES if p.stem == slug)
        return payout(path)

    def test_storj_reads_its_address_from_the_wallet_env_var(self):
        block = self._payout("storj")
        assert block["model"] == "external"
        assert block["address_env"] == "WALLET"

    def test_mysterium_is_external_but_not_readable_from_the_spec(self):
        """The beneficiary is set AFTER deploy via TequilAPI, so there is no env
        var to read -- and pretending there is would show a permanent blank."""
        block = self._payout("mysterium")
        assert block["model"] == "external"
        assert block["address_source"] == "manual"
        assert "address_env" not in block

    def test_salad_is_marked_as_having_no_chain_at_all(self):
        """Called out explicitly in the research: PayPal and gift cards only, so
        tier 2 must never try to reconcile it on-chain."""
        block = self._payout("salad")
        assert block["model"] == "internal"
        assert block["chain"] == "none"

    def test_traffmonetizer_declares_no_chain(self):
        """The chain is picked per withdrawal, so there is no persistent
        on-chain identity. Naming one would be a fabrication."""
        block = self._payout("traffmonetizer")
        assert block["model"] == "internal"
        assert "chain" not in block

    def test_urnetwork_warns_about_the_thirty_day_forfeit(self):
        """A user who never links a wallet LOSES the money. That is the single
        most valuable sentence in this registry."""
        assert "30 days" in self._payout("urnetwork").get("notes", "").lower()

    def test_the_minted_services_are_marked_for_tier_three(self):
        for slug in ("proxybase", "nosana"):
            assert self._payout(slug)["model"] == "minted", slug


class TestNoPrivateKeyIsEverDeclared:
    """The custody boundary, enforced. This tier is public addresses only."""

    @pytest.mark.parametrize("path", SERVICE_FILES, ids=ids(SERVICE_FILES))
    def test_the_payout_block_names_no_secret(self, path):
        text = " ".join(f"{k} {v}" for k, v in payout(path).items()).lower()
        for forbidden in ("private_key", "privatekey", "seed_phrase", "mnemonic", "secret_key", "keystore"):
            assert forbidden not in text, f"{path.name}: the payout registry must never reference {forbidden}"
