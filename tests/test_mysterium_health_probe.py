"""A Mysterium node behind a router that rewrites UDP source ports is flagged, not shown healthy.

Some routers change the source port of part of a node's outgoing UDP flows (a
fibre box that reserves ports in pairs, a SIP ALG). Inbound still works, so the
node's own port check passes and its log says "Method:manual Success:true",
but buyers drop its answers: every session ends after about a minute having
carried nothing. Two nodes sat like that for ten days with nothing on the
dashboard. The node's own API shows it: Mysterium's monitoring status reads
"failed" and its last sessions are all a minute long and empty. The worker
reads both inside the node (docker.health_probe) and the sweep lists the node
under Needs fixing.
"""

from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import catalog, health_probe, main, worker_api

GUIDE = "https://geiserx.github.io/CashPilot/guides/mysterium/#routers-that-rewrite-udp-source-ports"


def _session(n: int, duration: int, received: int, sent: int) -> dict:
    """One item of TequilAPI's GET /sessions, with its real field order (myst 1.39.9)."""
    return {
        "id": f"00000000-0000-4000-8000-{n:012d}",
        "direction": "Provided",
        "consumer_id": "0x" + "1" * 40,
        "hermes_id": "0x" + "2" * 40,
        "provider_id": "0x" + "3" * 40,
        "service_type": "wireguard",
        "consumer_country": "DE",
        "provider_country": "NL",
        "created_at": f"2026-11-0{n % 9 + 1}T10:00:00Z",
        "duration": duration,
        "bytes_received": received,
        "bytes_sent": sent,
        "tokens": 6238559818402,
        "status": "Completed",
        "ip_type": "",
    }


def _answer(status: str, sessions: list[dict]) -> str:
    """What the catalog command prints: the monitoring status, then the sessions page."""
    page = {"items": sessions, "page": 1, "page_size": 5, "total_items": len(sessions), "total_pages": 1}
    return json.dumps({"status": status}, separators=(",", ":")) + "\n" + json.dumps(page, separators=(",", ":"))


DEAD = [_session(i, 61, 0, 0) for i in range(5)]
# A working node: real traffic, plus the odd empty session that ends at once.
WORKING = [
    _session(0, 2, 6340, 3920),
    _session(1, 1, 0, 0),
    _session(2, 1270, 222980, 166168),
    _session(3, 10, 401020, 83700),
    _session(4, 1, 0, 0),
]
FAILING = _answer("failed", DEAD)
HEALTHY = _answer("success", WORKING)


def _spec():
    return catalog.get_service("mysterium")["docker"]["health_probe"]


def test_the_failing_node_trips_both_checks():
    assert health_probe.judge(FAILING, _spec()) == [0, 1]
    assert health_probe.judge(FAILING.encode(), _spec()) == [0, 1]


def test_negative_control_a_healthy_node_raises_nothing():
    assert health_probe.judge(HEALTHY, _spec()) == []


def test_monitoring_failed_alone_is_flagged_without_the_session_check():
    assert health_probe.judge(_answer("failed", WORKING), _spec()) == [0]
    assert health_probe.judge(_answer("pending", DEAD[:4]), _spec()) == []


def test_four_dead_sessions_are_not_yet_a_pattern():
    assert health_probe.judge(_answer("success", DEAD[:4]), _spec()) == []
    assert health_probe.judge(_answer("success", []), _spec()) == []


def test_one_session_that_carried_data_clears_it():
    assert health_probe.judge(_answer("success", [_session(9, 3600, 10_000, 2_000), *DEAD[:4]]), _spec()) == []


@pytest.mark.parametrize(
    ("duration", "received", "sent", "dead"),
    [
        (55, 0, 0, True),
        (89, 0, 0, True),
        (1, 0, 0, False),  # gone at once: a buyer that changed its mind, seen on working nodes
        (90, 0, 0, False),
        (61, 124, 0, False),
        (61, 0, 628, False),
    ],
)
def test_a_dead_session_is_about_a_minute_long_and_empty(duration, received, sent, dead):
    sessions = [*DEAD[:4], _session(7, duration, received, sent)]
    assert (1 in health_probe.judge(_answer("success", sessions), _spec())) is dead


def test_the_probe_only_reads_the_node():
    """Nothing in it may change the node: plain GETs on the node's own loopback."""
    script = " ".join(_spec()["command"])
    assert "--post" not in script and "-X" not in script and "curl" not in script
    urls = [w.strip('"') for w in script.split() if "http" in w]
    assert urls and all(u.startswith("http://127.0.0.1:4050/") for u in urls)
    assert {u.split("?")[0].split("4050")[1] for u in urls} == {"/node/monitoring-status", "/sessions"}


def test_the_finding_names_the_cause_and_the_guide_section():
    for check in _spec()["checks"]:
        assert "${WORKER_NAME}" in check["means"]
        assert "rewrit" in check["means"] and GUIDE in check["means"]


@pytest.mark.parametrize(
    "spec",
    [
        None,
        {"command": "wget x", "checks": [{"pattern": "a", "means": "m"}]},
        {"command": ["sh"], "checks": []},
        {"command": ["sh"], "checks": [{"pattern": "(", "means": "m"}]},
        {"command": ["sh"], "checks": [{"pattern": "a", "items": "(", "means": "m"}]},
        {"command": ["sh"], "checks": [{"pattern": "a", "means": " "}]},
        {"command": ["sh"], "checks": [{"pattern": "a", "means": "m", "min_matches": 0}]},
        {"command": ["sh"], "checks": [{"pattern": "a", "means": "m", "min_matches": True}]},
    ],
)
def test_a_malformed_probe_is_rejected_and_never_read(spec):
    assert health_probe.spec_errors(spec)
    assert health_probe.probes([{"slug": "x", "docker": {"health_probe": spec}}]) == {}


def test_the_catalog_entry_is_well_formed():
    assert health_probe.spec_errors(_spec()) == []


# --- The worker's read ---------------------------------------------------------


def test_the_worker_sends_back_only_which_checks_hold():
    good, bad, stopped = MagicMock(status="running"), MagicMock(status="running"), MagicMock(status="exited")
    good.exec_run.return_value = (0, FAILING.encode())
    bad.exec_run.return_value = (1, b"wget: can't connect")
    with (
        patch("app.orchestrator.service_instances", return_value=[good, bad, stopped]),
        patch("app.orchestrator._instance_of", side_effect=[1, 2]),
    ):
        rows = health_probe.read_all([catalog.get_service("mysterium")])
    assert rows == [
        {"slug": "mysterium", "instance": 1, "hits": [0, 1]},
        {"slug": "mysterium", "instance": 2, "error": "the node did not answer"},
    ]
    stopped.exec_run.assert_not_called()
    assert "consumer_id" not in json.dumps(rows), "the node's answer never leaves the worker"


def test_the_worker_endpoint_serves_the_rows():
    client = TestClient(worker_api.app)
    row = {"slug": "mysterium", "instance": 1, "hits": [1]}
    with (
        patch("app.worker_api._verify_api_key"),
        patch("app.worker_api.health_probe.read_all", return_value=[row]),
    ):
        resp = client.get("/api/health-probes")
    assert resp.status_code == 200 and resp.json() == {"probes": [row]}


# --- The UI's sweep ------------------------------------------------------------

WORKER = {"id": 7, "name": "attic-nas", "status": "online", "url": "http://192.168.50.100:8081"}
RUNNING = {"slug": "mysterium", "status": "running", "instance": 1, "_worker_id": 7}


def _sweep(probes=None, *, probe_error=None, logs=""):
    calls = []

    async def _proxy(wid, method, path, params=None, **kw):
        calls.append(path)
        if path == "/api/health-probes":
            if probe_error:
                raise probe_error
            return {"probes": probes or []}
        return {"logs": logs, "filtered": True}

    with (
        patch("app.main._get_all_worker_containers", new_callable=AsyncMock, return_value=[RUNNING]),
        patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=WORKER),
        patch(
            "app.main.database.get_deployment_spec",
            new_callable=AsyncMock,
            return_value={"env": {"UDP_PORTS": "23000:23029"}},
        ),
        patch("app.main._proxy_to_worker", side_effect=_proxy),
    ):
        asyncio.run(main._check_windowed_signals())
    return main._windowed_hints.get(("mysterium", 7, 1), []), calls


@pytest.fixture(autouse=True)
def _clean_hints():
    main._windowed_hints, main._probe_hints = {}, {}
    yield
    main._windowed_hints, main._probe_hints = {}, {}


def test_the_sweep_lists_a_failing_node_by_box_with_the_guide():
    hints, calls = _sweep([{"slug": "mysterium", "instance": 1, "hits": [0, 1]}])
    assert len(hints) == 2
    assert all("attic-nas" in h and GUIDE in h and "${" not in h for h in hints)
    assert "about a minute having moved no data" in hints[1]
    assert calls.count("/api/health-probes") == 1


def test_negative_control_the_sweep_says_nothing_for_a_healthy_node():
    hints, _ = _sweep([{"slug": "mysterium", "instance": 1, "hits": []}])
    assert hints == []


def test_an_unread_probe_keeps_the_last_verdict_and_a_healthy_read_clears_it():
    _sweep([{"slug": "mysterium", "instance": 1, "hits": [1]}])
    hints, _ = _sweep(probe_error=HTTPException(status_code=504, detail="slow"))
    assert len(hints) == 1, "a blip must not clear a real problem"
    hints, _ = _sweep([{"slug": "mysterium", "instance": 1, "error": "timed out"}])
    assert len(hints) == 1
    hints, _ = _sweep([{"slug": "mysterium", "instance": 1, "hits": []}])
    assert hints == []


def test_an_old_worker_without_the_endpoint_gives_no_verdict_and_keeps_the_log_signals():
    hints, _ = _sweep(probe_error=HTTPException(status_code=404, detail="Not Found"))
    assert hints == []
    failed = "DBG event={Identity:0xabc Method:manual Success:false}"
    hints, _ = _sweep(probe_error=HTTPException(status_code=404, detail="Not Found"), logs="\n".join([failed] * 5))
    assert len(hints) == 1 and "forward the UDP port range 23000:23029" in hints[0]


def test_out_of_range_hits_are_ignored():
    hints, _ = _sweep([{"slug": "mysterium", "instance": 1, "hits": [5, -1, True, "0"]}])
    assert hints == []
