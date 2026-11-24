"""The Storj collector reads several nodes and stores their sum, or nothing.

One wallet often runs several storage nodes, one per disk or per site, and
each node's dashboard reports only its own payout. ``storj_api_url`` takes a
comma-separated list. Every node must read for the sum to be stored: a partial
sum would be recorded as a real balance that dropped (which reads as a payout)
and the next full reading would book the missing node's month as a gain.

These run a real httpx client against a MockTransport, so the requests are
routed by URL rather than by the order of a mock's side effects.
"""

import asyncio
import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

from app.collectors import base, make_collectors  # noqa: E402
from app.collectors.storj import DEFAULT_API_URL, StorjCollector  # noqa: E402

NODE_A = "http://node-a.example:14002"
NODE_B = "http://node-b.example:14002"
HEALTHY = {"lastPinged": "2999-01-01T00:00:00Z", "quicStatus": "OK"}


def _run(collector, routes):
    """Collect with each node answered by ``routes[host]`` (a callable or a JSON body)."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.url.host}{request.url.path}")
        answer = routes[request.url.host]
        if callable(answer):
            return answer(request)
        if request.url.path == "/api/sno/":
            return httpx.Response(200, json=HEALTHY)
        return httpx.Response(200, json=answer)

    async def go():
        collector._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await collector.collect()
        finally:
            await collector.close()

    # A refused connection is retried with a back-off; the test need not wait it out.
    with patch.object(base.asyncio, "sleep", AsyncMock()):
        result = asyncio.run(go())
    return result, seen


class TestTheUrlList:
    def test_one_url_is_unchanged(self):
        c = StorjCollector(api_url="http://node-a.example:14002/")
        assert c.api_urls == [NODE_A]
        assert c.api_url == NODE_A

    def test_a_comma_list_is_split_trimmed_and_kept_in_order(self):
        c = StorjCollector(api_url=f" {NODE_B}/ ,{NODE_A} ")
        assert c.api_urls == [NODE_B, NODE_A]
        assert c.api_url == NODE_B, "api_url stays the first node for callers that read one"

    def test_a_url_listed_twice_is_read_once(self):
        # Counted twice, that node's earnings would double.
        c = StorjCollector(api_url=f"{NODE_A},{NODE_A}/,{NODE_B}")
        assert c.api_urls == [NODE_A, NODE_B]

    @pytest.mark.parametrize("raw", ["", " ", ",", " , ,", "/"])
    def test_nothing_usable_falls_back_to_the_default(self, raw):
        assert StorjCollector(api_url=raw).api_urls == [DEFAULT_API_URL]

    def test_make_collectors_passes_the_whole_list(self):
        collectors = make_collectors([{"slug": "storj"}], config={"storj_api_url": f"{NODE_A},{NODE_B}"})
        assert len(collectors) == 1
        assert collectors[0].api_urls == [NODE_A, NODE_B]


class TestTheSum:
    def test_two_nodes_are_summed(self):
        result, seen = _run(
            StorjCollector(api_url=f"{NODE_A},{NODE_B}"),
            {
                "node-a.example": {"currentMonth": {"egressBandwidthPayout": 150, "diskSpacePayout": 100}},
                "node-b.example": {"estimatedPayout": 125},
            },
        )
        assert result.error is None
        assert result.balance == 3.75  # 2.50 + 1.25
        assert result.currency == "USD"
        assert "node-a.example/api/sno/estimated-payout" in seen
        assert "node-b.example/api/sno/estimated-payout" in seen

    def test_a_single_node_reads_exactly_as_before(self):
        result, seen = _run(StorjCollector(api_url=NODE_A), {"node-a.example": {"estimatedPayout": 250}})
        assert result.error is None and result.balance == 2.50
        assert seen == ["node-a.example/api/sno/estimated-payout", "node-a.example/api/sno/"]

    def test_an_older_node_on_the_fallback_path_still_counts(self):
        def old_node(request):
            if request.url.path == "/api/sno/estimated-payout":
                return httpx.Response(404)
            if request.url.path == "/api/sno":
                return httpx.Response(200, json={"currentMonthExpectations": 50})
            return httpx.Response(200, json=HEALTHY)

        result, _ = _run(
            StorjCollector(api_url=f"{NODE_A},{NODE_B}"),
            {"node-a.example": {"estimatedPayout": 100}, "node-b.example": old_node},
        )
        assert result.error is None and result.balance == 1.50


class TestOneFailingNodeFailsTheReading:
    """No partial sum is ever returned as a balance."""

    def test_a_server_error_on_the_second_node_names_it(self):
        result, _ = _run(
            StorjCollector(api_url=f"{NODE_A},{NODE_B}"),
            {"node-a.example": {"estimatedPayout": 250}, "node-b.example": lambda r: httpx.Response(500)},
        )
        assert result.error is not None
        assert result.error.startswith(f"Storagenode at {NODE_B}:")
        assert NODE_A not in result.error
        assert result.balance == 0.0, "node A's 2.50 must not be stored as the Storj balance"

    def test_an_unreachable_node_names_it(self):
        def refused(request):
            raise httpx.ConnectError("Connection refused", request=request)

        result, _ = _run(
            StorjCollector(api_url=f"{NODE_A},{NODE_B}"),
            {"node-a.example": {"estimatedPayout": 250}, "node-b.example": refused},
        )
        assert result.error is not None
        assert "not reachable" in result.error and NODE_B in result.error
        assert result.balance == 0.0

    def test_an_unknown_shape_on_one_node_fails_the_reading(self):
        # A renamed payout field is the case that once stored a confident 0.00.
        result, _ = _run(
            StorjCollector(api_url=f"{NODE_A},{NODE_B}"),
            {"node-a.example": {"somethingNew": 1}, "node-b.example": {"estimatedPayout": 250}},
        )
        assert result.error is not None and result.error.startswith(f"Storagenode at {NODE_A}:")
        assert result.balance == 0.0

    def test_a_single_node_error_keeps_its_old_text(self):
        # With one node the URL is the setting itself, so the text is not prefixed.
        result, _ = _run(StorjCollector(api_url=NODE_A), {"node-a.example": lambda r: httpx.Response(500)})
        assert result.error is not None
        assert not result.error.startswith("Storagenode at")


class TestReachabilityWarnings:
    def test_each_node_is_probed_and_the_warning_names_the_node(self):
        def never_pinged(request):
            if request.url.path == "/api/sno/":
                return httpx.Response(200, json={"lastPinged": "0001-01-01T00:00:00Z", "quicStatus": "OK"})
            return httpx.Response(200, json={"estimatedPayout": 100})

        result, seen = _run(
            StorjCollector(api_url=f"{NODE_A},{NODE_B}"),
            {"node-a.example": {"estimatedPayout": 100}, "node-b.example": never_pinged},
        )
        assert result.error is None and result.balance == 2.0
        assert "node-a.example/api/sno/" in seen and "node-b.example/api/sno/" in seen
        assert result.warning and "EVER" in result.warning
        assert NODE_B in result.warning
        assert NODE_A not in result.warning, "a healthy node must not be named in the warning"

    def test_healthy_nodes_carry_no_warning(self):
        result, _ = _run(
            StorjCollector(api_url=f"{NODE_A},{NODE_B}"),
            {"node-a.example": {"estimatedPayout": 100}, "node-b.example": {"estimatedPayout": 100}},
        )
        assert result.warning is None
