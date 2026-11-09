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
import importlib.util
import json
import os
import socket
import tempfile
import threading
import time
from pathlib import Path
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


def _answer(status: str | None, sessions: list[dict] | None) -> str:
    """What the catalog command prints: each read that worked, behind its marker.

    The sessions come one per line behind their end time, as the command's awk
    prints them; None leaves a read out, as when it failed.
    """
    out = []
    if status is not None:
        out.append("monitoring read: " + json.dumps({"status": status}, separators=(",", ":")))
    if sessions is not None:
        out.append("sessions read:")
        out += [f"{1793806663 - i} " + json.dumps(x, separators=(",", ":")) for i, x in enumerate(sessions)]
    return "\n".join(out)


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
    """The Mysterium catalog entry's probe."""
    return catalog.get_service("mysterium")["docker"]["health_probe"]


def test_the_failing_node_trips_both_checks():
    """A node with monitoring "failed" and five dead sessions trips both checks."""
    assert health_probe.judge(FAILING, _spec()) == [0, 1]
    assert health_probe.judge(FAILING.encode(), _spec()) == [0, 1]


def test_negative_control_a_healthy_node_raises_nothing():
    """A working node trips neither check."""
    assert health_probe.judge(HEALTHY, _spec()) == []


def test_monitoring_failed_alone_is_flagged_without_the_session_check():
    """Each check stands on its own."""
    assert health_probe.judge(_answer("failed", WORKING), _spec()) == [0]
    assert health_probe.judge(_answer("pending", DEAD[:4]), _spec()) == []


def test_four_dead_sessions_are_not_yet_a_pattern():
    """Fewer than five sessions say nothing."""
    assert health_probe.judge(_answer("success", DEAD[:4]), _spec()) == []
    assert health_probe.judge(_answer("success", []), _spec()) == []


def test_one_session_that_carried_data_clears_it():
    """One session that moved data clears the session check."""
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
    """Only a session of about a minute with no bytes either way counts as dead."""
    sessions = [*DEAD[:4], _session(7, duration, received, sent)]
    assert (1 in health_probe.judge(_answer("success", sessions), _spec())) is dead


def test_the_probe_only_reads_the_node():
    """Nothing in it may change the node: plain GETs on the node's own loopback."""
    script = " ".join(_spec()["command"])
    assert "--post" not in script and "-X" not in script and "curl" not in script
    urls = [w.strip('";)') for w in script.split() if "http" in w]
    assert urls and all(u.startswith("http://127.0.0.1:4050/") for u in urls)
    assert {u.split("?")[0].split("4050")[1] for u in urls} == {"/node/monitoring-status", "/sessions"}


def test_the_finding_names_the_cause_and_the_guide_section():
    """Each finding names the box, the cause and the guide section."""
    for check in _spec()["checks"]:
        assert "${WORKER_NAME}" in check["means"]
        assert "rewrit" in check["means"] and GUIDE in check["means"]


@pytest.mark.parametrize(
    "spec",
    [
        None,
        {"command": "wget x", "checks": [{"pattern": "a", "means": "m"}]},
        # exec_run has no timeout: an unbounded command could hold a pool thread for ever.
        {"command": ["sh", "-c", "x"], "checks": [{"pattern": "a", "means": "m"}]},
        {"command": ["timeout", "15", "sh"], "checks": [{"pattern": "a", "means": "m"}]},
        {"command": ["timeout", "12", "sh"], "checks": []},
        {"command": ["timeout", "12", "sh"], "checks": [{"pattern": "(", "means": "m"}]},
        {"command": ["timeout", "12", "sh"], "checks": [{"pattern": "a", "items": "(", "means": "m"}]},
        {"command": ["timeout", "12", "sh"], "checks": [{"pattern": "a", "means": " "}]},
        {"command": ["timeout", "12", "sh"], "checks": [{"pattern": "a", "means": "m", "min_matches": 0}]},
        {"command": ["timeout", "12", "sh"], "checks": [{"pattern": "a", "means": "m", "min_matches": True}]},
    ],
)
def test_a_malformed_probe_is_rejected_and_never_read(spec):
    """A declaration that cannot be read safely is refused by the catalog and the worker."""
    assert health_probe.spec_errors(spec)
    assert health_probe.probes([{"slug": "x", "docker": {"health_probe": spec}}]) == {}


def test_the_catalog_entry_is_well_formed():
    """The shipped Mysterium probe passes the checks."""
    assert health_probe.spec_errors(_spec()) == []


def test_the_session_read_has_no_date_window_and_does_not_hang_on_the_status_read():
    """A date window empties out on a broken node no one is offered any more, and the
    check would clear itself; the status read (which asks a remote oracle) must not
    cost the local sessions read, nor the other way round."""
    script = _spec()["command"][-1]
    assert "date_from" not in script and "date " not in script
    status, sessions = script.split("\nfi\n", 1)
    assert "monitoring-status" in status and status.startswith("if ") and sessions.startswith("if ")
    assert [c.get("answered") for c in _spec()["checks"]] == ["monitoring read: ", "sessions read:"]


def test_one_failed_read_costs_only_its_own_checks():
    """A failed sessions read must not throw away a monitoring status of "failed"."""
    output = _answer("failed", None)
    assert health_probe.judge(output, _spec()) == [0]
    assert health_probe.unanswered(output, _spec()) == [1]
    assert health_probe.unanswered(_answer(None, DEAD), _spec()) == [0]
    assert health_probe.judge(_answer(None, DEAD), _spec()) == [1]


def test_the_loopback_reads_skip_any_inherited_proxy():
    """Both loopback reads turn off BusyBox wget proxy use."""
    script = _spec()["command"][-1]
    assert script.count("wget ") == script.count("wget -qO- -Y off ") == 2


def test_the_sessions_judged_are_the_five_that_ended_last():
    """TequilAPI lists sessions by start time; a long session that started first
    but ended after a run of short ones must still be among those judged."""
    script = _spec()["command"][-1]
    assert "page_size=25" in script
    assert "mktime(t) + d" in script and "sort -rn | head -5" in script


def test_the_monitoring_finding_sends_to_the_tun_check_first():
    """The monitoring finding points at the tun and SETUID check first."""
    means = _spec()["checks"][0]["means"]
    assert "/dev/net/tun" in means and "#running-but-not-earning-monitoring-failed-quality-0" in means


# --- The worker's read ---------------------------------------------------------


class _Api:
    """The low-level Docker API calls the probe makes, answering per container id."""

    def __init__(self, answers):
        """Map container id to (exit code, output), or to a callable producing the output."""
        self.answers = answers
        self.ran = []

    def exec_create(self, container_id, cmd):
        """Record the exec; its id is the container id."""
        self.ran.append(container_id)
        return {"Id": container_id}

    def exec_start(self, exec_id):
        """The container's output."""
        answer = self.answers[exec_id]
        if callable(answer):
            return answer()
        return answer[1]

    def exec_inspect(self, exec_id):
        """The container's exit code."""
        answer = self.answers[exec_id]
        return {"ExitCode": 0 if callable(answer) else answer[0]}


def _containers(*names, status="running"):
    """Fake containers with the given ids."""
    return [MagicMock(status=status, id=n) for n in names]


def test_the_worker_sends_back_only_which_checks_hold():
    """Only check indexes, the unread ones and the definition leave the worker."""
    api = _Api(
        {
            "good": (0, FAILING.encode()),
            "bad": (1, b"wget: can't connect"),
            "half": (0, _answer("failed", None).encode()),
        }
    )
    good, bad, half = _containers("good", "bad", "half")
    stopped = MagicMock(status="exited", id="stopped")
    definition = health_probe.fingerprint(_spec())
    with (
        patch("app.orchestrator.service_instances", return_value=[good, bad, half, stopped]),
        patch("app.orchestrator._instance_of", side_effect=[1, 2, 3]),
        patch("app.health_probe._client", return_value=MagicMock(api=api)),
    ):
        rows = health_probe.read_all([catalog.get_service("mysterium")])
    assert rows == [
        {"slug": "mysterium", "instance": 1, "definition": definition, "hits": [0, 1], "unread": []},
        {"slug": "mysterium", "instance": 2, "definition": definition, "error": "the node did not answer"},
        {"slug": "mysterium", "instance": 3, "definition": definition, "hits": [0], "unread": [1]},
    ]
    assert "stopped" not in api.ran
    assert "consumer_id" not in json.dumps(rows), "the node's answer never leaves the worker"


def test_a_stalled_exec_stream_does_not_hold_a_pool_thread(monkeypatch):
    """A Docker socket that accepts the exec and never answers must not keep a pool
    thread: four of them would leave every later read queued for good."""
    import docker

    folder = tempfile.mkdtemp(dir="/tmp")
    path = os.path.join(folder, "d.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(32)
    held = []

    def _accept():
        """Accept connections and never answer them."""
        while True:
            try:
                held.append(server.accept()[0])
            except OSError:
                return

    threading.Thread(target=_accept, daemon=True).start()
    release = threading.Event()
    stalled = MagicMock(status="running", id="stalled")
    stalled.exec_run.side_effect = lambda *a, **k: (release.wait(30), (0, b""))[1]
    monkeypatch.setattr(health_probe, "READ_TIMEOUT", 1)
    monkeypatch.setattr(health_probe, "probes", lambda services: {"mysterium": _spec()})
    monkeypatch.setattr(
        health_probe, "_client", lambda: docker.DockerClient(base_url=f"unix://{path}", timeout=1, version="1.41")
    )
    try:
        with (
            patch("app.orchestrator.service_instances", return_value=[stalled]),
            patch("app.orchestrator._instance_of", return_value=1),
        ):
            for _ in range(5):
                rows = health_probe.read_all([catalog.get_service("mysterium")])
                assert "hits" not in rows[0] and rows[0]["error"] in {"timed out", "read failed"}
        assert health_probe._pool.submit(lambda: "free").result(timeout=4) == "free"
    finally:
        release.set()
        server.close()
        for conn in held:
            conn.close()


def test_copies_read_before_the_batch_deadline_still_go_back(monkeypatch):
    """The UI waits 60 s for the whole answer; one slow copy must not cost the others."""
    release = threading.Event()
    api = _Api(
        {"fast": (0, FAILING.encode()), "slow": lambda: (release.wait(10), FAILING.encode())[1], "late": (0, b"")}
    )
    monkeypatch.setattr(health_probe, "BATCH_BUDGET", 0.5)
    try:
        with (
            patch("app.orchestrator.service_instances", return_value=_containers("fast", "slow", "late")),
            patch("app.orchestrator._instance_of", side_effect=[1, 2, 3]),
            patch("app.health_probe._client", return_value=MagicMock(api=api)),
        ):
            started = time.monotonic()
            rows = health_probe.read_all([catalog.get_service("mysterium")])
        assert time.monotonic() - started < 2
    finally:
        release.set()
    assert rows[0]["hits"] == [0, 1]
    assert rows[1]["error"] == "timed out" and rows[2]["error"] == "not reached in time"
    assert "late" not in api.ran


def test_the_worker_endpoint_serves_the_rows():
    """The worker endpoint returns what read_all reads."""
    client = TestClient(worker_api.app)
    row = {"slug": "mysterium", "instance": 1, "definition": "x", "hits": [1], "unread": []}
    with (
        patch("app.worker_api._verify_api_key"),
        patch("app.worker_api.health_probe.read_all", return_value=[row]),
    ):
        resp = client.get("/api/health-probes")
    assert resp.status_code == 200 and resp.json() == {"probes": [row]}


# --- The UI's sweep ------------------------------------------------------------

WORKER = {"id": 7, "name": "attic-nas", "status": "online", "url": "http://192.168.50.100:8081"}
RUNNING = {"slug": "mysterium", "status": "running", "instance": 1, "_worker_id": 7}


def _row(hits=None, *, error=None, unread=(), definition=None):
    """One row of the worker's /api/health-probes for the copy under test."""
    row = {"slug": "mysterium", "instance": 1, "definition": definition or health_probe.fingerprint(_spec())}
    if error:
        row["error"] = error
    else:
        row.update(hits=list(hits or []), unread=list(unread))
    return row


def _sweep(probes=None, *, probe_error=None, logs="", log_error=None):
    """Run one sweep against fake worker answers; returns the copy's hints and the paths called."""
    calls = []

    async def _proxy(wid, method, path, params=None, **kw):
        """Answer like the worker would."""
        calls.append(path)
        if path == "/api/health-probes":
            if probe_error:
                raise probe_error
            return {"probes": probes or []}
        if log_error:
            raise log_error
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
    """Each test starts and ends with no sweep state."""
    main._windowed_hints, main._signal_hints, main._probe_hints, main._probe_state = {}, {}, {}, {}
    yield
    main._windowed_hints, main._signal_hints, main._probe_hints, main._probe_state = {}, {}, {}, {}


def test_the_sweep_lists_a_failing_node_by_box_with_the_guide():
    """Both findings show, naming the box and the guide."""
    hints, calls = _sweep([_row([0, 1])])
    assert len(hints) == 2
    assert all("attic-nas" in h and GUIDE in h and "${" not in h for h in hints)
    assert "about a minute having moved no data" in hints[1]
    assert calls.count("/api/health-probes") == 1


def test_negative_control_the_sweep_says_nothing_for_a_healthy_node():
    """A healthy read shows nothing."""
    hints, _ = _sweep([_row([])])
    assert hints == []


def test_an_unread_probe_keeps_the_last_verdict_and_a_healthy_read_clears_it():
    """A blip keeps the last verdict; a healthy read clears it."""
    _sweep([_row([1])])
    hints, _ = _sweep(probe_error=HTTPException(status_code=504, detail="slow"))
    assert len(hints) == 1, "a blip must not clear a real problem"
    hints, _ = _sweep([_row(error="timed out")])
    assert len(hints) == 1
    hints, _ = _sweep([_row([])])
    assert hints == []


def test_a_verdict_does_not_outlive_a_day_of_unread_probes():
    """After a day unread the old verdict goes and the unreadable node is named."""
    _sweep([_row([1])])
    later = main.time.time() + main.PROBE_STALE_SECONDS + 3600
    with patch("app.main.time.time", return_value=later):
        hints, _ = _sweep([_row(error="timed out")])
    assert len(hints) == 1 and "has not been able to read" in hints[0] and "attic-nas" in hints[0]
    assert "about a minute" not in hints[0], "the stale verdict is gone"
    with patch("app.main.time.time", return_value=later):
        hints, _ = _sweep(probe_error=HTTPException(status_code=504, detail="slow"))
    assert hints == [], "a worker that does not answer at all drops the stale verdict without a claim"


def test_a_short_unread_spell_names_nothing_new():
    """A node unread for less than a day gets no new finding."""
    _sweep([_row(error="timed out")])
    hints, _ = _sweep([_row(error="timed out")])
    assert hints == []


def test_an_old_worker_without_the_endpoint_gives_no_verdict_and_keeps_the_log_signals():
    """A worker without the endpoint costs no log signal."""
    hints, _ = _sweep(probe_error=HTTPException(status_code=404, detail="Not Found"))
    assert hints == []
    failed = "DBG event={Identity:0xabc Method:manual Success:false}"
    hints, _ = _sweep(probe_error=HTTPException(status_code=404, detail="Not Found"), logs="\n".join([failed] * 5))
    assert len(hints) == 1 and "forward the UDP port range 23000:23029" in hints[0]


def test_out_of_range_hits_are_ignored():
    """Hit values that are not valid indexes are ignored."""
    hints, _ = _sweep([_row([5, -1, True, "0"])])
    assert hints == []


FAILED_LOG = "\n".join(["DBG event={Identity:0xabc Method:manual Success:false}"] * 5)


def test_a_failed_log_read_still_lets_the_probe_update():
    """A failed log read keeps the log verdict and still updates the probe."""
    hints, _ = _sweep([_row([])], logs=FAILED_LOG)
    assert len(hints) == 1 and "forward the UDP port range" in hints[0]
    hints, _ = _sweep([_row([1])], log_error=HTTPException(status_code=504, detail="slow"))
    assert len(hints) == 2, "the log verdict stands and the new probe verdict shows"
    assert "forward the UDP port range" in hints[0] and "about a minute having moved no data" in hints[1]
    hints, _ = _sweep([_row([])], log_error=HTTPException(status_code=504, detail="slow"))
    assert len(hints) == 1 and "forward the UDP port range" in hints[0], "a healthy probe clears its own part"


def test_hits_from_another_probe_definition_are_no_verdict():
    """During an upgrade the worker may run another catalog: its indexes may name
    another check, and its empty hits prove nothing."""
    _sweep([_row([1])])
    hints, _ = _sweep([_row([], definition="another")])
    assert len(hints) == 1 and "about a minute having moved no data" in hints[0]
    hints, _ = _sweep([_row([0, 1], definition="another")])
    assert len(hints) == 1, "an index from another definition never shows"
    hints, _ = _sweep([{k: v for k, v in _row([0]).items() if k != "definition"}])
    assert len(hints) == 1 and "about a minute" in hints[0]


def test_an_unread_check_keeps_its_verdict_while_the_other_updates():
    """A check the worker could not read keeps its verdict; the other updates."""
    hints, _ = _sweep([_row([0, 1])])
    assert len(hints) == 2
    hints, _ = _sweep([_row([], unread=[0])])
    assert len(hints) == 1 and "monitoring marks the node" in hints[0]
    hints, _ = _sweep([_row([1], unread=[0])])
    assert len(hints) == 2


def test_a_check_unread_for_a_day_says_so():
    """A check unread for a day is reported as unreadable."""
    _sweep([_row([0, 1])])
    later = main.time.time() + main.PROBE_STALE_SECONDS + 3600
    with patch("app.main.time.time", return_value=later):
        hints, _ = _sweep([_row([1], unread=[0])])
    assert len(hints) == 2 and "about a minute" in hints[0]
    assert "has not been able to read" in hints[1] and "did not answer every read" in hints[1]


# --- The two-port STUN test ----------------------------------------------------


def _stun():
    """Load scripts/stun_port_pair.py as a module."""
    path = Path(__file__).resolve().parents[1] / "scripts" / "stun_port_pair.py"
    spec = importlib.util.spec_from_file_location("stun_port_pair", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_network_error_is_no_answer_not_a_rewritten_port():
    """A send or receive error is no answer, never a traceback that exits 1."""
    stun = _stun()
    sock = MagicMock()
    sock.sendto.side_effect = OSError(101, "Network is unreachable")
    assert stun.probe(sock, ("192.0.2.1", 3478)) is None
    sock = MagicMock()
    sock.recvfrom.side_effect = ConnectionRefusedError(111, "Connection refused")
    assert stun.probe(sock, ("192.0.2.1", 3478)) is None


def test_a_silent_stun_server_falls_back_to_the_next(monkeypatch, capsys):
    """A STUN server that never answers hands over to the next one."""
    stun = _stun()
    first, second = ("192.0.2.1", 19302), ("192.0.2.2", 3478)
    tried = []

    def _run(server, start, pairs):
        """The first server is silent, the second answers."""
        tried.append(server)
        return (0, 0, 0) if server == first else (8, 0, 4)

    monkeypatch.setattr(stun, "_servers", lambda: [first, second])
    monkeypatch.setattr(stun, "run", _run)
    monkeypatch.setattr("sys.argv", ["stun_port_pair.py"])
    assert stun.main() == 0 and tried == [first, second]
    monkeypatch.setattr(stun, "run", lambda *a: (0, 0, 0))
    assert stun.main() == 2


@pytest.mark.parametrize(
    ("result", "code"),
    [((8, 0, 4), 0), ((6, 0, 2), 3), ((4, 0, 0), 3), ((6, 1, 2), 1), ((8, 8, 4), 1)],
)
def test_an_incomplete_pair_is_inconclusive_not_clean(monkeypatch, result, code):
    """No rewrite with an untested pair exits 3, never 0."""
    stun = _stun()
    monkeypatch.setattr(stun, "_servers", lambda: [("192.0.2.1", 3478)])
    monkeypatch.setattr(stun, "run", lambda *a: result)
    monkeypatch.setattr("sys.argv", ["stun_port_pair.py"])
    assert stun.main() == code
