"""CashPilot-dv6 tier 2: reading balances on-chain, honestly.

THE DISTINCTION THIS WHOLE MODULE EXISTS FOR: an address holding nothing and a
chain we could not reach are DIFFERENT ANSWERS. Both are "no number to show",
and collapsing them tells a user their money is gone when the truth is that a
public RPC rate-limited us.

So the tests below care much less about arithmetic than about which state comes
back, and several assert that ``amount`` is None rather than 0.

Driven through httpx.MockTransport rather than patching internals, so the real
request-building, real status handling and real JSON parsing all run. A test
that patched ``_read`` would prove only that the wrapper returns what the mock
said.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from app import onchain


@pytest.fixture(autouse=True)
def _clean_state():
    onchain.reset_state()
    yield
    onchain.reset_state()


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ok(result):
    return lambda request: httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})


EVM_ADDR = "0x" + "ab" * 20
SOL_ADDR = "So11111111111111111111111111111111111111112"


class TestAddressValidation:
    def test_a_well_formed_evm_address_passes(self):
        assert onchain.address_looks_valid("ethereum", EVM_ADDR) is True

    def test_a_short_evm_address_fails(self):
        assert onchain.address_looks_valid("ethereum", "0xdeadbeef") is False

    def test_an_evm_address_is_not_valid_on_solana(self):
        """Chains do not share an address format, and sending one to the other
        is how you get a confident wrong answer."""
        assert onchain.address_looks_valid("solana", EVM_ADDR) is False

    def test_base58_excludes_the_ambiguous_characters(self):
        """0, O, I and l are excluded from base58 on purpose."""
        assert onchain.address_looks_valid("solana", "0" * 40) is False

    def test_an_unknown_chain_is_never_valid(self):
        assert onchain.address_looks_valid("dogecoin", EVM_ADDR) is False


class TestTheFourStates:
    @pytest.mark.anyio
    async def test_a_real_balance_is_known(self):
        # 1 ETH in wei, hex, as an RPC really returns it.
        async with _client(_ok(hex(10**18))) as client:
            out = await onchain.balance("ethereum", EVM_ADDR, client=client)
        assert out["state"] == onchain.KNOWN
        assert out["amount"] == Decimal(1)

    @pytest.mark.anyio
    async def test_a_genuine_zero_is_known_and_zero(self):
        """The counterpart to the test below. An address really holding nothing
        IS a fact, and must be reported as one."""
        async with _client(_ok("0x0")) as client:
            out = await onchain.balance("ethereum", EVM_ADDR, client=client)
        assert out["state"] == onchain.KNOWN
        assert out["amount"] == Decimal(0)

    @pytest.mark.anyio
    async def test_an_unreachable_chain_is_NOT_zero(self):
        """THE test. A failed read must not look like an empty wallet."""

        def boom(request):
            raise httpx.ConnectError("no route to host")

        async with _client(boom) as client:
            out = await onchain.balance("ethereum", EVM_ADDR, client=client)
        assert out["state"] == onchain.UNREACHABLE
        assert out["amount"] is None
        assert out["amount"] != 0

    @pytest.mark.anyio
    async def test_an_rpc_error_payload_is_unreachable_not_a_balance(self):
        """A 200 response carrying an `error` object is still a failure. Reading
        `result` off it would raise, or worse, silently produce None."""

        def errored(request):
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32005, "message": "limit"}})

        async with _client(errored) as client:
            out = await onchain.balance("ethereum", EVM_ADDR, client=client)
        assert out["state"] == onchain.UNREACHABLE
        assert out["amount"] is None

    @pytest.mark.anyio
    async def test_a_500_is_unreachable(self):
        async with _client(lambda r: httpx.Response(500, text="upstream boom")) as client:
            out = await onchain.balance("ethereum", EVM_ADDR, client=client)
        assert out["state"] == onchain.UNREACHABLE

    @pytest.mark.anyio
    async def test_an_unsupported_chain_says_so(self):
        async with _client(_ok("0x0")) as client:
            out = await onchain.balance("dogecoin", EVM_ADDR, client=client)
        assert out["state"] == onchain.UNSUPPORTED
        assert out["amount"] is None

    @pytest.mark.anyio
    async def test_a_malformed_address_is_never_sent_to_the_endpoint(self):
        """We do not use someone else's free RPC as a validator."""
        calls = []

        def record(request):
            calls.append(request)
            return httpx.Response(200, json={"result": "0x0"})

        async with _client(record) as client:
            out = await onchain.balance("ethereum", "not-an-address", client=client)
        assert out["state"] == onchain.INVALID
        assert calls == [], "a malformed address reached the network"


class TestSolana:
    @pytest.mark.anyio
    async def test_it_reads_the_nested_value(self):
        async with _client(_ok({"context": {"slot": 1}, "value": 2_500_000_000})) as client:
            out = await onchain.balance("solana", SOL_ADDR, client=client)
        assert out["state"] == onchain.KNOWN
        assert out["amount"] == Decimal("2.5")

    @pytest.mark.anyio
    async def test_an_unexpected_shape_is_unreachable_not_a_guess(self):
        async with _client(_ok({"context": {"slot": 1}})) as client:
            out = await onchain.balance("solana", SOL_ADDR, client=client)
        assert out["state"] == onchain.UNREACHABLE
        assert out["amount"] is None


class TestPrecision:
    @pytest.mark.anyio
    async def test_wei_survives_exactly(self):
        """18 decimals does not survive a float. 0.1 + 0.2 arithmetic in a
        balance is how a wallet loses trust."""
        async with _client(_ok(hex(123456789012345678))) as client:
            out = await onchain.balance("ethereum", EVM_ADDR, client=client)
        assert out["amount"] == Decimal("0.123456789012345678")
        assert isinstance(out["amount"], Decimal)


class TestCachingAndBackoff:
    @pytest.mark.anyio
    async def test_a_second_read_is_served_from_cache(self):
        calls = []

        def counting(request):
            calls.append(1)
            return httpx.Response(200, json={"result": "0x0"})

        async with _client(counting) as client:
            await onchain.balance("ethereum", EVM_ADDR, client=client)
            await onchain.balance("ethereum", EVM_ADDR, client=client)
        assert len(calls) == 1, "the cache did not prevent a second call"

    @pytest.mark.anyio
    async def test_a_failure_backs_the_endpoint_off(self):
        calls = []

        def failing(request):
            calls.append(1)
            raise httpx.ConnectError("down")

        async with _client(failing) as client:
            first = await onchain.balance("ethereum", EVM_ADDR, client=client)
            second = await onchain.balance("ethereum", EVM_ADDR, client=client)
        assert first["state"] == second["state"] == onchain.UNREACHABLE
        assert len(calls) == 1, "backoff did not stop the second attempt"

    @pytest.mark.anyio
    async def test_a_failure_is_not_cached_as_a_result(self):
        """CONTROL: if a failure were cached like a success, it would outlive the
        backoff and keep reporting unreachable after the chain recovered."""
        onchain.reset_state()
        assert onchain._cache == {}

        def failing(request):
            raise httpx.ConnectError("down")

        async with _client(failing) as client:
            await onchain.balance("ethereum", EVM_ADDR, client=client)
        assert onchain._cache == {}, "a failure was written into the success cache"

    @pytest.mark.anyio
    async def test_backoff_is_per_endpoint_not_global(self):
        """A failing Ethereum RPC must not silence Solana."""
        onchain._backoff_until[onchain.CHAINS["ethereum"].rpc] = onchain._now() + 999
        async with _client(_ok({"value": 1_000_000_000})) as client:
            eth = await onchain.balance("ethereum", EVM_ADDR, client=client)
            sol = await onchain.balance("solana", SOL_ADDR, client=client)
        assert eth["state"] == onchain.UNREACHABLE
        assert sol["state"] == onchain.KNOWN


class TestTheContract:
    def test_no_state_but_known_ever_carries_an_amount(self):
        """CONTROL over the helper itself. If this ever passes an amount through
        for a non-known state, every honesty test above becomes decorative."""
        for state in (onchain.UNREACHABLE, onchain.UNSUPPORTED, onchain.INVALID):
            out = onchain._result(state, "ethereum", amount=Decimal(5))
            assert out["amount"] is None, f"{state} leaked an amount"

    def test_known_does_carry_its_amount(self):
        """The negative control for the test above: if _result dropped every
        amount, the assertions there would pass for the wrong reason."""
        assert onchain._result(onchain.KNOWN, "ethereum", amount=Decimal(5))["amount"] == Decimal(5)

    def test_every_configured_chain_is_keyless(self):
        """A shared API key must never ship. If an endpoint ever needs one, the
        chain stays unsupported until the user supplies it."""
        for spec in onchain.CHAINS.values():
            assert "key=" not in spec.rpc.lower()
            assert "apikey" not in spec.rpc.lower()
            assert spec.rpc.startswith("https://")


class TestTheCacheCannotBeCorruptedOrGrowForever:
    """Both of these were REAL defects in the first draft of this module, found
    by self-review rather than by any test, and fixed before it shipped."""

    @pytest.mark.anyio
    async def test_a_caller_mutating_its_result_does_not_poison_the_cache(self):
        """The cache used to hand out the stored dict itself. A caller that
        modified what it got corrupted every later read -- and since this
        module's whole contract is "amount is None unless state is known", a
        mutated entry is exactly the lie it exists to prevent.
        """
        async with _client(_ok(hex(10**18))) as client:
            first = await onchain.balance("ethereum", EVM_ADDR, client=client)
            first["amount"] = "TAMPERED"
            first["state"] = "nonsense"
            second = await onchain.balance("ethereum", EVM_ADDR, client=client)

        assert second["state"] == onchain.KNOWN
        assert second["amount"] == Decimal(1)
        assert second is not first, "the cache handed back the same object twice"

    @pytest.mark.anyio
    async def test_control_the_cache_is_actually_being_used(self):
        """Negative control for the test above. If caching were simply broken,
        it would pass for the wrong reason -- every read would be fresh."""
        calls = []

        def counting(request):
            calls.append(1)
            return httpx.Response(200, json={"result": hex(10**18)})

        async with _client(counting) as client:
            await onchain.balance("ethereum", EVM_ADDR, client=client)
            await onchain.balance("ethereum", EVM_ADDR, client=client)
        assert len(calls) == 1, "not a cache hit, so the poisoning test proves nothing"

    @pytest.mark.anyio
    async def test_expired_entries_do_not_accumulate_forever(self):
        """Expiry was only ever noticed on read, so entries piled up for the life
        of the process -- one per address ever asked about, never released."""
        for i in range(600):
            onchain._cache[f"ethereum:0x{i:040x}"] = (0.0, {})  # all long expired

        async with _client(_ok(hex(1))) as client:
            await onchain.balance("ethereum", "0x" + "cd" * 20, client=client)

        assert len(onchain._cache) == 1, f"expired entries survived: {len(onchain._cache)}"

    @pytest.mark.anyio
    async def test_live_entries_are_capped_rather_than_grown_without_bound(self):
        """Even if every entry is live, there is a ceiling."""
        future = onchain._now() + 9999
        for i in range(onchain.MAX_CACHE_ENTRIES + 50):
            onchain._cache[f"ethereum:0x{i:040x}"] = (future, {"state": "known"})

        async with _client(_ok(hex(1))) as client:
            await onchain.balance("ethereum", "0x" + "ef" * 20, client=client)

        assert len(onchain._cache) <= onchain.MAX_CACHE_ENTRIES


class TestAMalformedRpcResultIsNeverReportedAsABalance:
    """A tolerant parser turns a malformed response into a CONFIDENT WRONG
    NUMBER, reported as `known` -- the one outcome worse than admitting we could
    not read the chain. All three of these produced a fake balance before the
    parser was tightened (CodeRabbit, #273).
    """

    @pytest.mark.anyio
    async def test_a_json_number_is_not_read_as_hex(self):
        """`int(str(10), 16)` is 16. A decimal 10 became 16 wei, reported as
        fact."""
        async with _client(_ok(10)) as client:
            out = await onchain.balance("ethereum", EVM_ADDR, client=client)
        assert out["state"] == onchain.UNREACHABLE
        assert out["amount"] is None

    @pytest.mark.anyio
    async def test_a_non_hex_string_is_rejected(self):
        async with _client(_ok("banana")) as client:
            out = await onchain.balance("ethereum", EVM_ADDR, client=client)
        assert out["state"] == onchain.UNREACHABLE

    @pytest.mark.anyio
    async def test_a_bool_is_not_a_solana_balance(self):
        """isinstance(True, int) is True, so a boolean became 1e-9 SOL."""
        async with _client(_ok({"value": True})) as client:
            out = await onchain.balance("solana", SOL_ADDR, client=client)
        assert out["state"] == onchain.UNREACHABLE
        assert out["amount"] is None

    @pytest.mark.anyio
    async def test_a_negative_balance_is_impossible_and_rejected(self):
        async with _client(_ok({"value": -5_000_000_000})) as client:
            out = await onchain.balance("solana", SOL_ADDR, client=client)
        assert out["state"] == onchain.UNREACHABLE
        assert out["amount"] is None

    @pytest.mark.anyio
    async def test_a_bare_integer_result_is_a_protocol_change_not_a_balance(self):
        async with _client(_ok(2_500_000_000)) as client:
            out = await onchain.balance("solana", SOL_ADDR, client=client)
        assert out["state"] == onchain.UNREACHABLE

    @pytest.mark.anyio
    async def test_control_the_documented_shapes_still_work(self):
        """The negative control. If the parser now rejected EVERYTHING, every
        assertion above would pass for the wrong reason."""
        async with _client(_ok(hex(10**18))) as client:
            evm = await onchain.balance("ethereum", EVM_ADDR, client=client)
        onchain.reset_state()
        async with _client(_ok({"context": {"slot": 1}, "value": 2_500_000_000})) as client:
            sol = await onchain.balance("solana", SOL_ADDR, client=client)
        assert evm["state"] == onchain.KNOWN and evm["amount"] == Decimal(1)
        assert sol["state"] == onchain.KNOWN and sol["amount"] == Decimal("2.5")
