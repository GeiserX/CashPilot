"""A Mysterium node behind a router that rewrites UDP source ports is flagged, not shown healthy.

Some routers rewrite the source port of a node's answers from a port that has
had a packet in from outside, and every session starts with one (the node's
own port check). Inbound still works, so the
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
import copy
import importlib.util
import json
import os
import re
import shutil
import socket
import socket as _socket
import struct
import subprocess
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
    """What the catalog command prints: each read that worked, with its marker.

    The sessions come one per line behind their end time, as the command's awk
    prints them, then their marker; None leaves a read out, as when it failed.
    """
    out = []
    if status is not None:
        out.append("monitoring read: " + json.dumps({"status": status}, separators=(",", ":")))
    if sessions is not None:
        out += [f"{1793806663 - i} " + json.dumps(x, separators=(",", ":")) for i, x in enumerate(sessions)]
        out.append("sessions read: all")
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


def test_the_socket_proxy_lets_the_worker_run_the_probe():
    """Behind the shipped socket proxy only listed exec commands run; an unlisted
    probe would be refused on every read and the node shown as unreadable."""
    from app import socket_policy

    assert _spec()["command"] in socket_policy.catalog_commands()


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
    assert "monitoring-status" in status and status.startswith("if ") and sessions.startswith("set -o pipefail\nif ")
    assert sessions.rstrip().endswith('echo "sessions read: all"\nfi'), "the marker comes after the data"
    assert [c.get("answered") for c in _spec()["checks"]] == ["monitoring read: ", "sessions read: all"]


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
    assert "page_size=100" in script
    assert "mktime(t) + d" in script and "| sort -rn)" in script and '"$sorted" | head -5' in script


def _awk_has_mktime() -> bool:
    """Whether this machine's awk has mktime, as BusyBox's and mawk's do (macOS's does not)."""
    probe = subprocess.run(["awk", 'BEGIN { print mktime("2026 11 04 15 36 42") }'], capture_output=True, text=True)
    return probe.returncode == 0 and probe.stdout.strip().isdigit()


@pytest.mark.skipif(not _awk_has_mktime(), reason="this awk has no mktime")
def test_a_long_session_that_ended_last_is_judged_though_it_started_first():
    """Runs the catalog's own sessions pipeline on a page in the API's order."""
    script = _spec()["command"][-1]
    start = script.index('echo "$s" | ') + len('echo "$s" | ')
    pipeline = script[start : script.index("| sort -rn") + len("| sort -rn")] + " | head -5"
    dead = [_session(i, 61, 0, 0) | {"created_at": f"2026-11-08T1{i // 6}:{i % 6}0:00Z"} for i in range(30)]
    long_good = _session(99, 40 * 3600, 900_000, 400_000) | {"created_at": "2026-11-07T00:00:00Z"}
    page = {"items": [*reversed(dead), long_good], "page": 1, "page_size": 100, "total_items": 31, "total_pages": 1}
    env = {**os.environ, "s": json.dumps(page, separators=(",", ":"))}
    out = subprocess.run(["sh", "-c", 'echo "$s" | ' + pipeline], capture_output=True, text=True, env=env, check=True)
    assert len(out.stdout.splitlines()) == 5 and "00000000-0000-4000-8000-000000000099" in out.stdout
    assert health_probe.judge(_answer("success", None) + "\n" + out.stdout + "sessions read: all", _spec()) == []
    dead_only = {**page, "items": list(reversed(dead))}
    env["s"] = json.dumps(dead_only, separators=(",", ":"))
    out = subprocess.run(["sh", "-c", 'echo "$s" | ' + pipeline], capture_output=True, text=True, env=env, check=True)
    assert health_probe.judge(out.stdout + "sessions read: all", _spec()) == [1]


def _run_sessions_branch(tmp_path, page: str, *, broken_awk: bool = False) -> str:
    """Run the catalog command under bash with a stub wget answering ``page``
    (monitoring fails); ``broken_awk`` makes awk exit with an error."""
    stubs = tmp_path / "bin"
    stubs.mkdir()
    (stubs / "wget").write_text('#!/bin/sh\ncase "$*" in *monitoring*) exit 1;; esac\nprintf "%s" "$PAGE"\n')
    if broken_awk:
        (stubs / "awk").write_text("#!/bin/sh\ncat >/dev/null\nexit 2\n")
    for stub in stubs.iterdir():
        stub.chmod(0o755)
    env = {**os.environ, "PATH": f"{stubs}:{os.environ['PATH']}", "PAGE": page}
    script = _spec()["command"][-1]
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env).stdout


def test_a_failed_sessions_pipeline_is_no_full_read(tmp_path):
    """awk or sort failing after a good fetch must leave the sessions check unread,
    not judged healthy on empty output."""
    page = json.dumps({"items": [_session(i, 61, 0, 0) for i in range(6)]}, separators=(",", ":"))
    out = _run_sessions_branch(tmp_path, page, broken_awk=True)
    assert "sessions read: all" not in out
    assert health_probe.unanswered(out, _spec()) == [0, 1]


@pytest.mark.skipif(not _awk_has_mktime(), reason="this awk has no mktime")
def test_an_empty_session_list_is_still_a_full_read(tmp_path):
    """A node with no completed sessions yet was read in full and holds no bad run."""
    out = _run_sessions_branch(tmp_path, '{"items":[],"page":1,"page_size":100,"total_items":0}')
    assert out.splitlines() == ["sessions read: all"]
    assert health_probe.unanswered(out, _spec()) == [0] and health_probe.judge(out, _spec()) == []


def test_the_monitoring_finding_sends_to_the_tun_check_first():
    """The monitoring finding points at the tun and SETUID check first."""
    means = _spec()["checks"][0]["means"]
    assert "/dev/net/tun" in means and "#running-but-not-earning-monitoring-failed-quality-0" in means


# --- The worker's read ---------------------------------------------------------


def _frames(output: bytes) -> bytes:
    """Docker's multiplexed exec stream for ``output``, split over two stdout frames."""
    half = len(output) // 2
    return b"".join(struct.pack(">BxxxI", 1, len(part)) + part for part in (output[:half], output[half:]))


class _Api:
    """The low-level Docker API calls the probe makes, answering per container id.

    An answer is (exit code, output), or None for an exec stream that never
    sends: its socket stays silent until ``hang`` is set.
    """

    def __init__(self, answers):
        """Map container id to its answer."""
        self.answers = answers
        self.ran = []
        self.hang = threading.Event()

    def exec_create(self, container_id, cmd):
        """Record the exec; its id is the container id."""
        self.ran.append(container_id)
        return {"Id": container_id}

    def exec_start(self, exec_id, socket=False):
        """The raw socket of the exec stream, as docker-py hands it out."""
        assert socket, "the probe must read the raw socket, never docker-py's unbounded reader"
        ours, theirs = _socket.socketpair()
        answer = self.answers[exec_id]
        if answer is None:

            def _close_later():
                """End the silent stream once the test lets go."""
                self.hang.wait(30)
                theirs.close()

            threading.Thread(target=_close_later, daemon=True).start()
        else:
            theirs.sendall(_frames(answer[1]))
            theirs.close()
        return ours

    def exec_inspect(self, exec_id):
        """The container's exit code."""
        answer = self.answers[exec_id]
        return {"ExitCode": 0 if answer is None else answer[0]}


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


def _fake_docker(path: str, stop: threading.Event) -> socket.socket:
    """A Docker API on a unix socket that creates the exec, starts its stream, then never sends."""
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(32)

    def _serve(conn):
        """Answer one connection's requests until the exec stream starts."""
        buf = b""
        while not stop.is_set():
            while b"\r\n\r\n" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                buf += chunk
            head, buf = buf.split(b"\r\n\r\n", 1)
            length = int(re.search(rb"(?i)content-length: *(\d+)", head).group(1)) if b"ength:" in head else 0
            while len(buf) < length:
                buf += conn.recv(65536)
            buf = buf[length:]
            if b"/exec/stalled-exec/start" in head:
                conn.sendall(
                    b"HTTP/1.1 101 UPGRADED\r\nContent-Type: application/vnd.docker.raw-stream\r\n"
                    b"Connection: Upgrade\r\nUpgrade: tcp\r\n\r\n"
                )
                stop.wait(30)  # the stream has started and never sends a byte
                return
            body = b'{"Id":"stalled-exec"}'
            conn.sendall(
                b"HTTP/1.1 201 Created\r\nContent-Type: application/json\r\n"
                + f"Content-Length: {len(body)}\r\n\r\n".encode()
                + body
            )

    def _accept():
        """Serve every connection on its own thread."""
        while True:
            try:
                conn = server.accept()[0]
            except OSError:
                return
            threading.Thread(target=_serve, args=(conn,), daemon=True).start()

    threading.Thread(target=_accept, daemon=True).start()
    return server


def test_a_stalled_exec_stream_does_not_hold_a_pool_thread(monkeypatch):
    """The daemon creates the exec and starts its stream, then never sends: the read
    must end by its deadline and free its thread, or four of them leave every
    later read queued for good. docker-py's own reader polls with no timeout."""
    import docker

    # /tmp, not tmp_path: a unix socket path must stay under about 100 characters.
    folder = tempfile.mkdtemp(dir="/tmp")
    path = os.path.join(folder, "d.sock")
    stop = threading.Event()
    server = _fake_docker(path, stop)
    monkeypatch.setattr(health_probe, "READ_TIMEOUT", 1)
    monkeypatch.setattr(health_probe, "probes", lambda services: {"mysterium": _spec()})
    monkeypatch.setattr(
        health_probe, "_client", lambda: docker.DockerClient(base_url=f"unix://{path}", timeout=1, version="1.41")
    )
    try:
        with (
            patch("app.orchestrator.service_instances", return_value=_containers("stalled")),
            patch("app.orchestrator._instance_of", return_value=1),
        ):
            for _ in range(6):
                rows = health_probe.read_all([catalog.get_service("mysterium")])
                assert "hits" not in rows[0] and rows[0]["error"] in {"timed out", "read failed"}
                time.sleep(0.3)
            time.sleep(1.5)
            rows = health_probe.read_all([catalog.get_service("mysterium")])
        assert rows[0]["error"] != "busy with earlier reads", "every stalled read ended and gave back its slot"
        assert health_probe._pool.submit(lambda: "free").result(timeout=2) == "free"
    finally:
        stop.set()
        server.close()
        shutil.rmtree(folder, ignore_errors=True)


def test_reads_never_queue_behind_busy_threads(monkeypatch):
    """With every thread on a read that has not ended, the next copy is reported
    busy at once instead of waiting in the pool's queue."""
    api = _Api({f"c{i}": None for i in range(6)})
    monkeypatch.setattr(health_probe, "READ_TIMEOUT", 0.2)
    monkeypatch.setattr(health_probe, "probes", lambda services: {"mysterium": _spec()})
    monkeypatch.setattr(health_probe, "_recv", lambda sock, deadline: (api.hang.wait(30), b"")[1])
    try:
        with (
            patch("app.orchestrator.service_instances", return_value=_containers(*api.answers)),
            patch("app.orchestrator._instance_of", side_effect=range(1, 7)),
            patch("app.health_probe._client", return_value=MagicMock(api=api)),
        ):
            rows = health_probe.read_all([catalog.get_service("mysterium")])
        assert [r["error"] for r in rows] == ["timed out"] * 4 + ["busy with earlier reads"] * 2
        assert api.ran == ["c0", "c1", "c2", "c3"]
    finally:
        api.hang.set()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not health_probe._slots.acquire(blocking=False):
        time.sleep(0.05)
    health_probe._slots.release()


def test_copies_read_before_the_batch_deadline_still_go_back(monkeypatch):
    """The UI waits 60 s for the whole answer; one slow copy must not cost the others."""
    api = _Api({"fast": (0, FAILING.encode()), "slow": None, "late": (0, b"")})
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
        api.hang.set()
    assert rows[0]["hits"] == [0, 1]
    assert rows[1]["error"] == "timed out" and rows[2]["error"] == "not reached in time"
    assert "late" not in api.ran


def test_the_next_call_starts_with_the_copy_this_one_did_not_reach(monkeypatch):
    """A slow copy that eats the budget every time must not leave the later ones unread for good."""
    api = _Api({"fast": (0, FAILING.encode()), "slow": None, "late": (0, FAILING.encode())})
    monkeypatch.setattr(health_probe, "BATCH_BUDGET", 0.5)
    try:
        with (
            patch("app.orchestrator.service_instances", return_value=_containers("fast", "slow", "late")),
            patch("app.orchestrator._instance_of", side_effect=[1, 2, 3, 1, 2, 3]),
            patch("app.health_probe._client", return_value=MagicMock(api=api)),
        ):
            health_probe.read_all([catalog.get_service("mysterium")])
            assert api.ran == ["fast", "slow"]
            rows = health_probe.read_all([catalog.get_service("mysterium")])
    finally:
        api.hang.set()
    assert api.ran[2] == "late", "the copy the first call never reached goes first"
    assert [r["instance"] for r in rows] == [1, 2, 3], "rows keep the copies' order"
    assert rows[2]["hits"] == [0, 1]


def test_listing_the_copies_uses_the_probe_client_and_the_budget(monkeypatch):
    """A stalled container listing on the shared client (60 s) would outlast the UI's wait."""
    probe_client = MagicMock(api=_Api({}))
    listed = []

    def _list(slug, client=None):
        """Record which client listed the copies."""
        listed.append(client)
        return []

    with (
        patch("app.orchestrator.service_instances", side_effect=_list),
        patch("app.health_probe._client", return_value=probe_client),
    ):
        health_probe.read_all([catalog.get_service("mysterium")])
        assert listed == [probe_client]
        monkeypatch.setattr(health_probe, "BATCH_BUDGET", 0)
        assert health_probe.read_all([catalog.get_service("mysterium")]) == []
    assert len(listed) == 1, "no listing starts once the budget is spent"


def _proxy_403():
    """The APIError docker-py raises when sockguard refuses a call."""
    import docker

    response = MagicMock(status_code=403)
    response.json.return_value = {"message": "request denied by sockguard policy", "reason": "exec command not allowed"}
    return docker.errors.APIError("403 Client Error", response=response)


@pytest.mark.parametrize(("stale", "says_update"), [(True, True), (False, False)])
def test_a_proxy_refusal_says_so_and_names_the_fix_when_the_policy_is_old(stale, says_update):
    """A refused read says the proxy refused it, and names the update when the policy is stale."""
    refused = MagicMock(api=MagicMock(**{"exec_create.side_effect": _proxy_403()}))
    with (
        patch("app.orchestrator.service_instances", return_value=_containers("node")),
        patch("app.orchestrator._instance_of", return_value=1),
        patch("app.orchestrator.proxy_policy_fix", return_value={"release": "x"} if stale else None),
        patch("app.health_probe._client", return_value=refused),
    ):
        rows = health_probe.read_all([catalog.get_service("mysterium")])
    assert "socket proxy refused" in rows[0]["error"]
    assert ("status page" in rows[0]["error"]) is says_update


def test_a_proxy_refusal_does_not_send_the_operator_to_the_node_logs():
    """A refusal by the proxy names its own fix, not the node's logs."""
    _sweep([_row(error="the Docker socket proxy refused the read")])
    later = main.time.time() + main.PROBE_STALE_SECONDS + 3600
    with patch("app.main.time.time", return_value=later):
        hints, _ = _sweep([_row(error="the Docker socket proxy refused the read")])
    assert len(hints) == 1 and "socket proxy refused" in hints[0] and "logs" not in hints[0]


def test_a_probe_in_a_yaml_file_reaches_the_proxy_policy(tmp_path):
    """app/catalog.py loads .yaml as well as .yml, so the policy must list both."""
    from app import socket_policy

    svc = tmp_path / "bandwidth" / "newnode.yaml"
    svc.parent.mkdir()
    command = ["timeout", "5", "cat", "/x"]
    svc.write_text(json.dumps({"slug": "newnode", "docker": {"health_probe": {"command": command}}}))
    assert command in socket_policy.catalog_commands(tmp_path)


def test_a_read_cut_short_keeps_the_checks_it_finished():
    """timeout ends the command during the sessions read: the monitoring verdict
    already printed stands, and the unfinished sessions read counts as unread,
    never as healthy."""
    cut = ("monitoring read: " + '{"status":"failed"}\n' + "1793806663 " + json.dumps(DEAD[0])).encode()
    api = _Api({"cut": (124, cut), "nothing": (124, b"")})
    with (
        patch("app.orchestrator.service_instances", return_value=_containers("cut", "nothing")),
        patch("app.orchestrator._instance_of", side_effect=[1, 2]),
        patch("app.health_probe._client", return_value=MagicMock(api=api)),
    ):
        rows = health_probe.read_all([catalog.get_service("mysterium")])
    assert rows[0]["hits"] == [0] and rows[0]["unread"] == [1]
    assert rows[1]["error"] == "the node did not answer"


def test_a_check_without_a_marker_is_unread_when_the_command_fails():
    spec = {"command": ["timeout", "5", "true"], "checks": [{"pattern": "bad", "means": "m"}]}
    api = _Api({"x": (1, b"")})
    assert health_probe._read_one(MagicMock(api=api), "x", spec) is None


def _two_services():
    """Two services that declare the same probe, so a batch can run out between them."""
    spec = _spec()
    return [{"slug": "aaa", "docker": {"health_probe": spec}}, {"slug": "bbb", "docker": {"health_probe": spec}}]


def test_the_next_batch_starts_with_the_service_this_one_did_not_reach(monkeypatch):
    """A slow first service that eats the budget every time must not leave the next one unread."""
    api = _Api({"slow": None, "fast": (0, FAILING.encode())})
    listed = []

    def _list(slug, client=None):
        """aaa's only copy never answers; bbb's answers at once."""
        listed.append(slug)
        return _containers("slow" if slug == "aaa" else "fast")

    monkeypatch.setattr(health_probe, "BATCH_BUDGET", 0.5)
    try:
        with (
            patch("app.orchestrator.service_instances", side_effect=_list),
            patch("app.orchestrator._instance_of", return_value=1),
            patch("app.health_probe._client", return_value=MagicMock(api=api)),
        ):
            first = health_probe.read_all(_two_services())
            api.hang.set()
            second = health_probe.read_all(_two_services())
    finally:
        api.hang.set()
    assert [r["slug"] for r in first] == ["aaa"] and listed[:1] == ["aaa"]
    assert listed[1] == "bbb", "the service the first batch never reached goes first"
    assert second[0]["slug"] == "bbb" and second[0]["hits"] == [0, 1]


def test_a_stalled_listing_ends_with_the_batch_and_keeps_the_rows_read(monkeypatch):
    """The UI waits 60 s in all; a listing that hangs must not cost the rows already read."""
    release = threading.Event()
    api = _Api({"fast": (0, FAILING.encode())})

    def _list(slug, client=None):
        """aaa lists at once; bbb's listing hangs."""
        if slug == "bbb":
            release.wait(10)
            return []
        return _containers("fast")

    monkeypatch.setattr(health_probe, "BATCH_BUDGET", 0.5)
    try:
        with (
            patch("app.orchestrator.service_instances", side_effect=_list),
            patch("app.orchestrator._instance_of", return_value=1),
            patch("app.health_probe._client", return_value=MagicMock(api=api)),
        ):
            started = time.monotonic()
            rows = health_probe.read_all(_two_services())
            took = time.monotonic() - started
    finally:
        release.set()
    assert took < 2 and [r["slug"] for r in rows] == ["aaa"] and rows[0]["hits"] == [0, 1]


def test_a_client_that_cannot_be_made_gives_its_slot_back():
    """Docker down at the start of a batch must not use up the pool's slots for good."""
    api = _Api({"fast": (0, FAILING.encode())})
    with (
        patch("app.orchestrator.service_instances", return_value=_containers("fast")),
        patch("app.orchestrator._instance_of", return_value=1),
    ):
        for _ in range(health_probe._POOL_SIZE + 1):
            with patch("app.health_probe._client", side_effect=OSError("no docker")):
                assert health_probe.read_all(_two_services()) == []
        with patch("app.health_probe._client", return_value=MagicMock(api=api)):
            rows = health_probe.read_all(_two_services())
    assert [r.get("hits") for r in rows] == [[0, 1], [0, 1]]


def test_a_listing_that_always_stalls_lets_the_next_service_go_first(monkeypatch):
    """The cursor moves past a stalled listing, or the services behind it are never read."""
    release = threading.Event()
    api = _Api({"fast": (0, FAILING.encode())})
    listed = []

    def _list(slug, client=None):
        """aaa's listing always hangs; bbb lists at once."""
        listed.append(slug)
        if slug == "aaa":
            release.wait(10)
            return []
        return _containers("fast")

    monkeypatch.setattr(health_probe, "BATCH_BUDGET", 0.3)
    try:
        with (
            patch("app.orchestrator.service_instances", side_effect=_list),
            patch("app.orchestrator._instance_of", return_value=1),
            patch("app.health_probe._client", return_value=MagicMock(api=api)),
        ):
            assert health_probe.read_all(_two_services()) == []
            second = health_probe.read_all(_two_services())
    finally:
        release.set()
    assert listed[1] == "bbb" and second[0]["slug"] == "bbb" and second[0]["hits"] == [0, 1]


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


def _sweep(probes=None, *, probe_error=None, logs="", log_error=None, worker_error=None):
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
        patch(
            "app.main.database.get_worker",
            new_callable=AsyncMock,
            return_value=WORKER,
            side_effect=worker_error,
        ),
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
def _no_carried_turn():
    """Each test starts read_all with the first copy."""
    health_probe._resume.clear()
    health_probe._resume_service = None
    yield
    health_probe._resume.clear()
    health_probe._resume_service = None


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


def test_a_verdict_kept_from_another_definition_is_dropped():
    """After a catalog change an old index could name another check: an unread
    probe must not keep a verdict read against another definition."""
    _sweep([_row([1])])
    changed = copy.deepcopy(catalog.get_service("mysterium"))
    changed["docker"]["health_probe"]["checks"].reverse()
    with patch("app.main.catalog.get_service", return_value=changed):
        hints, _ = _sweep(
            [_row(error="timed out", definition=health_probe.fingerprint(changed["docker"]["health_probe"]))]
        )
    assert hints == [], "the session verdict must not come back as the monitoring one"


def test_a_worker_lookup_failure_keeps_log_verdicts_but_not_another_definitions_probe():
    """When the worker row cannot be read, the log verdict stays, and a probe
    verdict read against another definition must not come back."""
    _sweep([_row([1])], logs=FAILED_LOG)
    changed = copy.deepcopy(catalog.get_service("mysterium"))
    changed["docker"]["health_probe"]["checks"].reverse()
    with patch("app.main.catalog.get_service", return_value=changed):
        hints, _ = _sweep(worker_error=RuntimeError("database is locked"))
    assert len(hints) == 1 and "forward the UDP port range" in hints[0]
    assert ("mysterium", 7, 1) not in main._probe_state


def test_a_failing_sweep_does_not_keep_a_verdict_past_a_day():
    """The kept probe hints obey the same one-day limit as a working sweep."""
    _sweep([_row([1])])
    later = main.time.time() + main.PROBE_STALE_SECONDS + 3600
    with patch("app.main.time.time", return_value=later):
        with patch("app.main._probe_step", side_effect=RuntimeError("boom")):
            hints, _ = _sweep([_row([1])])
        assert hints == [], "a day-old verdict must not survive a failing probe step"
        hints, _ = _sweep(worker_error=RuntimeError("database is locked"))
        assert hints == [], "nor a failing worker lookup"


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


@pytest.mark.parametrize(
    ("args", "code"),
    [
        (["--start", "1"], 4),
        (["--start", "65535", "--pairs", "2"], 4),
        (["--pairs", "0"], 4),
        (["--start", "70000"], 4),
    ],
)
def test_ports_that_do_not_exist_are_an_input_error_not_a_verdict(monkeypatch, args, code):
    """Port 0 binds anywhere and ports past 65535 raise: neither may read as a rewrite."""
    stun = _stun()
    monkeypatch.setattr(stun, "run", lambda *a: pytest.fail("no port may be tested"))
    monkeypatch.setattr("sys.argv", ["stun_port_pair.py", *args])
    with pytest.raises(SystemExit) as stop:
        stun.main()
    assert stop.value.code == code


def test_the_highest_real_pair_is_still_tested(monkeypatch):
    """65534 and 65535 are real ports and still tested."""
    stun = _stun()
    monkeypatch.setattr(stun, "_servers", lambda: [("192.0.2.1", 3478)])
    monkeypatch.setattr(stun, "run", lambda server, start, pairs: (2, 0, 1))
    monkeypatch.setattr("sys.argv", ["stun_port_pair.py", "--start", "65534", "--pairs", "1"])
    assert stun.main() == 0


def test_stray_datagrams_cannot_keep_a_try_waiting():
    """Each try ends on its own deadline, whatever arrives meanwhile."""
    stun = _stun()
    started = time.monotonic()

    class _Noisy:
        """A socket that receives a datagram that is not the answer, again and again."""

        def settimeout(self, value):
            """Accept the timeout."""

        def sendto(self, data, server):
            """Send nothing."""

        def recvfrom(self, size):
            """Something that is not a STUN answer, at once, until the test gives up."""
            if time.monotonic() - started > 3:
                raise RuntimeError("the try never ended")
            return b"not stun", ("192.0.2.9", 1)

    assert stun.probe(_Noisy(), ("192.0.2.1", 3478), tries=2, wait=0.2) is None
    assert time.monotonic() - started < 1.5


def test_no_socket_is_its_own_status_and_pairs_close_as_they_go(monkeypatch):
    """Running out of sockets is no rewrite (exit 5), and a long run keeps only one pair open."""
    stun = _stun()
    real = socket.socket

    def _refuse(*a, **k):
        """This machine is out of file descriptors."""
        raise OSError(24, "Too many open files")

    monkeypatch.setattr(stun, "_servers", lambda: [("192.0.2.1", 3478)])
    monkeypatch.setattr("sys.argv", ["stun_port_pair.py"])
    monkeypatch.setattr(stun.socket, "socket", _refuse)
    assert stun.main() == 5
    monkeypatch.setattr(stun.socket, "socket", real)
    open_now = peak = 0

    class _Counted:
        """A UDP socket that counts how many are open at once."""

        def __init__(self, *a, **k):
            """Open one."""
            nonlocal open_now, peak
            open_now += 1
            peak = max(peak, open_now)
            self.port = 0

        def settimeout(self, value):
            """Accept the timeout."""

        def bind(self, address):
            """Remember the port."""
            self.port = address[1]

        def close(self):
            """Close one."""
            nonlocal open_now
            open_now -= 1

    monkeypatch.setattr(stun.socket, "socket", _Counted)
    monkeypatch.setattr(stun, "probe", lambda sock, server: sock.port)
    assert stun.run(("192.0.2.1", 3478), 30000, 50) == (100, 0, 50)
    assert peak == 2 and open_now == 0


def test_a_rewrite_seen_before_the_sockets_ran_out_still_counts(monkeypatch):
    """Running out of sockets after a rewrite was measured keeps that verdict, exit 1."""
    stun = _stun()
    opened = 0

    class _Few:
        """UDP sockets until the third, then out of file descriptors."""

        def __init__(self, *a, **k):
            """Open one, or refuse past two."""
            nonlocal opened
            opened += 1
            if opened > 2:
                raise OSError(24, "Too many open files")
            self.port = 0

        def settimeout(self, value):
            """Accept the timeout."""

        def bind(self, address):
            """Remember the port."""
            self.port = address[1]

        def close(self):
            """Close it."""

    monkeypatch.setattr(stun, "_servers", lambda: [("192.0.2.1", 3478)])
    monkeypatch.setattr("sys.argv", ["stun_port_pair.py"])
    monkeypatch.setattr(stun.socket, "socket", _Few)
    # The odd port goes out first and comes back rewritten; its partner keeps its number.
    monkeypatch.setattr(stun, "probe", lambda sock, server: sock.port + 100 if sock.port % 2 else sock.port)
    assert stun.main() == 1


def test_every_port_rewritten_makes_no_claim_about_a_forward(monkeypatch, capsys):
    """The test measures ports with no forward, so it says nothing about one."""
    stun = _stun()
    monkeypatch.setattr(stun, "_servers", lambda: [("192.0.2.1", 3478)])
    monkeypatch.setattr(stun, "run", lambda *a: (8, 8, 4))
    monkeypatch.setattr("sys.argv", ["stun_port_pair.py"])
    assert stun.main() == 1
    out = capsys.readouterr().out
    assert "cannot work" not in out and "only measures ports with no forward" in out
    assert "or a VPN" not in out, "some VPNs forward UDP ports"


def test_the_guide_stops_the_node_from_cashpilot_for_the_decisive_test():
    """A plain docker stop is not a stop the worker knows about; it can start the node mid-test."""
    guide = (Path(__file__).resolve().parents[1] / "docs" / "guides" / "mysterium.md").read_text()
    section = guide[guide.index("**Confirm it.**") : guide.index("**Fix.**")]
    assert "docker stop cashpilot" not in section and "docker start cashpilot" not in section
    assert "**Stop**" in section and "**Start**" in section
    assert "port-check-servers" not in guide and "Tried without success" in guide
