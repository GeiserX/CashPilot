"""CashPilot-dv6 tier 2: /api/payout-balances, the endpoint behind the column.

Two properties matter more than the arithmetic:

* We only ask about addresses we actually hold. An `internal`, `minted` or
  `unknown` service has no address, and putting a public RPC to work on nothing
  is both pointless and rude to infrastructure we do not pay for.
* A Decimal does not survive JSON. Serialising it as a float would undo, at the
  very last step, the exact precision the reader uses Decimal to preserve.
"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest


def _client():
    """Not a context manager: entering it runs the lifespan, which installs a
    SIGHUP handler, and signal() raises "only works in main thread" here."""
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


def _as(role):
    user = None if role is None else {"u": "sergio", "r": role}
    return patch("app.main.auth.get_current_user", return_value=user)


#: One of each shape the registry can produce.
REGISTRY = {
    "entries": [
        {"slug": "storj", "model": "external", "chain": "ethereum", "address": "0x" + "ab" * 20},
        {
            "slug": "nosana",
            "model": "external",
            "chain": "solana",
            "address": "So11111111111111111111111111111111111111112",
        },
        # Should NOT be queried: no address, wrong model, or a chain we cannot read.
        {"slug": "honeygain", "model": "internal", "chain": None, "address": None},
        {"slug": "minty", "model": "minted", "chain": "solana", "address": None},
        {"slug": "mystery", "model": "unknown", "chain": None, "address": None},
        {"slug": "offchain", "model": "external", "chain": "dogecoin", "address": "D" + "x" * 33},
        {"slug": "noaddr", "model": "external", "chain": "ethereum", "address": None},
    ],
    "summary": {},
}


class TestOnlyAddressesWeHoldAreQueried:
    def test_it_asks_about_exactly_the_readable_external_addresses(self):
        seen = {}

        async def fake_balances(pairs):
            seen["pairs"] = pairs
            return [
                {"state": "known", "chain": c, "symbol": "X", "amount": Decimal("1"), "detail": None} for c, _ in pairs
            ]

        client = _client()
        with (
            _as("owner"),
            patch("app.main.payout_registry.registry", new_callable=AsyncMock, return_value=REGISTRY),
            patch("app.main.onchain.balances", side_effect=fake_balances),
        ):
            resp = client.get("/api/payout-balances")

        assert resp.status_code == 200
        # storj and nosana only: the rest have no address, no readable chain, or
        # a payout model that has no address at all.
        assert [c for c, _ in seen["pairs"]] == ["ethereum", "solana"]
        assert set(resp.json()["balances"]) == {"storj", "nosana"}

    def test_a_service_with_no_address_is_never_asked_about(self):
        """CONTROL for the test above: `noaddr` is external and on a supported
        chain, so only the missing address excludes it."""
        seen = {}

        async def fake_balances(pairs):
            seen["pairs"] = pairs
            return [
                {"state": "known", "chain": c, "symbol": "X", "amount": Decimal("1"), "detail": None} for c, _ in pairs
            ]

        client = _client()
        with (
            _as("owner"),
            patch("app.main.payout_registry.registry", new_callable=AsyncMock, return_value=REGISTRY),
            patch("app.main.onchain.balances", side_effect=fake_balances),
        ):
            client.get("/api/payout-balances")

        assert all(addr is not None for _, addr in seen["pairs"])


class TestTheResponseSurvivesJson:
    def test_a_decimal_is_serialised_without_losing_digits(self):
        """A float here would undo, at the last step, the precision the reader
        uses Decimal to keep."""
        exact = Decimal("0.123456789012345678")

        async def fake_balances(pairs):
            return [{"state": "known", "chain": c, "symbol": "ETH", "amount": exact, "detail": None} for c, _ in pairs]

        client = _client()
        with (
            _as("owner"),
            patch("app.main.payout_registry.registry", new_callable=AsyncMock, return_value=REGISTRY),
            patch("app.main.onchain.balances", side_effect=fake_balances),
        ):
            body = client.get("/api/payout-balances").text

        assert "0.123456789012345678" in body
        assert json.loads(body)["balances"]["storj"]["amount"] == "0.123456789012345678"

    def test_an_unreachable_chain_serialises_as_null_not_zero(self):
        """The whole point, carried through JSON."""

        async def fake_balances(pairs):
            return [
                {"state": "unreachable", "chain": c, "symbol": "ETH", "amount": None, "detail": "timeout"}
                for c, _ in pairs
            ]

        client = _client()
        with (
            _as("owner"),
            patch("app.main.payout_registry.registry", new_callable=AsyncMock, return_value=REGISTRY),
            patch("app.main.onchain.balances", side_effect=fake_balances),
        ):
            data = client.get("/api/payout-balances").json()

        assert data["balances"]["storj"]["amount"] is None
        assert data["balances"]["storj"]["amount"] != 0
        assert data["unreadable"] == 2
        assert data["checked"] == 2


class TestItIsOwnerOnly:
    @pytest.mark.parametrize("role", ["viewer", "writer"])
    def test_a_non_owner_is_refused(self, role):
        client = _client()
        with _as(role):
            assert client.get("/api/payout-balances").status_code == 403

    def test_anonymous_is_refused(self):
        client = _client()
        with _as(None):
            assert client.get("/api/payout-balances").status_code in (401, 403)

    def test_control_the_owner_is_allowed(self):
        """Without this, the refusals above could pass because the endpoint is
        broken for everyone."""

        async def fake_balances(pairs):
            return [
                {"state": "known", "chain": c, "symbol": "X", "amount": Decimal("1"), "detail": None} for c, _ in pairs
            ]

        client = _client()
        with (
            _as("owner"),
            patch("app.main.payout_registry.registry", new_callable=AsyncMock, return_value=REGISTRY),
            patch("app.main.onchain.balances", side_effect=fake_balances),
        ):
            assert client.get("/api/payout-balances").status_code == 200
