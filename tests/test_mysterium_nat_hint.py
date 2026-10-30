"""A Mysterium node whose sessions never connect directly says so on the dashboard.

Every session tries the forwarded UDP range first ("Method:manual"); when that
fails it falls back to hole punching, and many buyers cannot connect that way.
For weeks three nodes carried 325 sessions a day with no direct connection, and
nothing showed it. The log tail could not: the node writes about 11,000 lines
an hour, so the 200-line tail is a minute. The sweep reads six hours of matching
lines from the worker instead, and the hint goes away once a session connects
directly.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest
from fastapi.testclient import TestClient

from app import catalog, main, orchestrator, producer_state, worker_api

FAILED = "2026-10-29T10:00:00Z DBG event={Identity:0xabc Method:manual Success:false}"
PUNCHED = "2026-10-29T10:00:01Z DBG event={Identity:0xabc Method:holepunching Success:true}"
DIRECT = "2026-10-29T12:00:00Z DBG event={Identity:0xabc Method:manual Success:true}"

WORKER = {"id": 7, "name": "nas", "status": "online", "url": "http://192.168.10.100:8081"}
RUNNING = {"slug": "mysterium", "status": "running", "instance": 1, "_worker_id": 7}


def _signal():
    signals = producer_state.signals_for(catalog.get_service("mysterium"))
    return next(s for s in signals if producer_state.is_windowed(s))


def _sweep(logs, *, filtered=True, recorded=None, containers=(RUNNING,), worker=WORKER, error=None):
    calls = []

    async def _proxy(wid, method, path, params=None, **kw):
        calls.append((wid, path, params))
        if error:
            raise error
        out = {"logs": logs}
        if filtered:
            out["filtered"] = True
        return out

    with (
        patch("app.main._get_all_worker_containers", new_callable=AsyncMock, return_value=list(containers)),
        patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
        patch("app.main.database.get_deployment_spec", new_callable=AsyncMock, return_value=recorded),
        patch("app.main._proxy_to_worker", side_effect=_proxy),
    ):
        asyncio.run(main._check_windowed_signals())
    return main._windowed_hints.get(("mysterium", 7, 1), []), calls


@pytest.fixture(autouse=True)
def _clean_hints():
    main._windowed_hints = {}
    yield
    main._windowed_hints = {}


def test_only_failed_direct_connections_raise_the_hint_with_the_rule_to_create():
    hints, calls = _sweep("\n".join([FAILED, PUNCHED, FAILED, PUNCHED]))
    assert len(hints) == 1
    assert "forward the UDP port range 56000:56100" in hints[0]
    assert "to 192.168.10.100" in hints[0]
    _, path, params = calls[0]
    assert path == "/api/containers/mysterium/logs"
    assert params["since_hours"] == 6
    assert re.search(params["match"], FAILED) and re.search(params["match"], DIRECT)
    assert not re.search(params["match"], PUNCHED), "the worker sends back only the two lines that matter"


def test_the_hint_names_the_range_this_box_was_deployed_with():
    hints, _ = _sweep(FAILED, recorded={"env": {"UDP_PORTS": "41000:41050"}})
    assert "forward the UDP port range 41000:41050" in hints[0]


def test_without_a_lan_address_the_hint_says_this_machine():
    hints, _ = _sweep(FAILED, worker={**WORKER, "url": "http://nas.example.ts.net:8081"})
    assert "to this machine's LAN address" in hints[0]


def test_it_clears_once_a_session_connects_directly():
    hints, _ = _sweep(FAILED)
    assert hints
    hints, _ = _sweep("\n".join([FAILED, DIRECT, FAILED]))
    assert hints == []


def test_a_node_with_no_sessions_stays_quiet():
    hints, _ = _sweep("")
    assert hints == []


def test_an_old_worker_that_returns_the_plain_tail_gives_no_verdict():
    hints, _ = _sweep(FAILED, filtered=False)
    assert hints == []


def test_a_failed_read_keeps_the_last_verdict_and_a_stopped_node_drops_it():
    _sweep(FAILED)
    hints, _ = _sweep("", error=RuntimeError("worker unreachable"))
    assert hints, "a blip must not clear a real problem"
    hints, calls = _sweep(FAILED, containers=({**RUNNING, "status": "exited"},))
    assert hints == [] and calls == []


def test_the_tail_matcher_leaves_windowed_signals_alone():
    """On a minute of logs, one failed attempt with no success in view says nothing."""
    signals = producer_state.signals_for(catalog.get_service("mysterium"))
    assert producer_state.match_log_signals(FAILED, signals) == []


def test_the_dashboard_row_carries_the_hint_for_that_box():
    main._windowed_hints = {("mysterium", 7, 1): ["forward it"]}
    worker = {
        **WORKER,
        "system_info": json.dumps({"docker_available": True}),
        "containers": json.dumps([{"slug": "mysterium", "name": "cashpilot-mysterium", "status": "running"}]),
        "apps": "[]",
    }

    @asynccontextmanager
    async def _noop_lifespan(app):
        yield

    with (
        patch.object(main.app.router, "lifespan_context", _noop_lifespan),
        patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "owner", "r": "owner"}),
        patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
        patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_health_scores", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_custom_images", new_callable=AsyncMock, return_value={}),
        TestClient(main.app, raise_server_exceptions=False) as client,
    ):
        resp = client.get("/api/services/deployed")
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json() if r["slug"] == "mysterium")
    assert row["instance_details"][0]["hints"] == ["forward it"]


class _Container:
    def __init__(self, chunks):
        self.chunks = chunks
        self.kwargs = {}

    def logs(self, **kwargs):
        self.kwargs = kwargs
        return iter(self.chunks)


def test_the_worker_filters_a_streamed_window_across_chunk_boundaries():
    text = "\n".join([PUNCHED, FAILED, PUNCHED, DIRECT]).encode()  # no trailing newline
    container = _Container([text[i : i + 7] for i in range(0, len(text), 7)])
    match = re.compile(producer_state.window_filter(_signal()))
    with patch("app.orchestrator._find_container", return_value=container):
        out = orchestrator.grep_service_logs("mysterium", match, since_hours=6)
    assert out.split("\n") == [FAILED, DIRECT]
    assert container.kwargs["stream"] is True and container.kwargs["since"] > 0


def test_the_worker_endpoint_marks_a_filtered_answer_and_refuses_a_bad_regex():
    client = TestClient(worker_api.app)
    headers = {"Authorization": f"Bearer {os.environ['CASHPILOT_API_KEY']}"}
    with (
        patch("app.worker_api._verify_api_key"),
        patch("app.worker_api.orchestrator.grep_service_logs", return_value=FAILED) as grep,
    ):
        resp = client.get(
            "/api/containers/mysterium/logs",
            params={"match": "Method:manual", "since_hours": 48, "lines": 5000},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json() == {"logs": FAILED, "filtered": True}
        assert grep.call_args.kwargs["since_hours"] == 24 and grep.call_args.kwargs["lines"] == 1000
        resp = client.get("/api/containers/mysterium/logs", params={"match": "(", "since_hours": 6}, headers=headers)
        assert resp.status_code == 400
    with (
        patch("app.worker_api._verify_api_key"),
        patch("app.worker_api.orchestrator.get_service_logs", return_value="tail") as tail,
    ):
        resp = client.get("/api/containers/mysterium/logs", headers=headers)
    assert resp.json() == {"logs": "tail"} and tail.called


def test_windowed_hit_needs_the_pattern_and_never_the_unless():
    signal = {"pattern": "bad", "unless": "good", "window_hours": 1}
    assert producer_state.windowed_hit("x bad y", signal)
    assert not producer_state.windowed_hit("bad\ngood", signal)
    assert not producer_state.windowed_hit("", signal)
    assert not producer_state.windowed_hit("bad", {**signal, "unless": "("}), "a broken unless never fires"
    assert not producer_state.is_windowed({"window_hours": "x"})
