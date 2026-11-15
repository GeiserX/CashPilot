"""On a real Docker daemon: no earner starts into a tunnel run that has not proved its exit (docs/proxies.md).

Opt-in, because it needs a daemon and pulls alpine's nftables package:
``CASHPILOT_REAL_DOCKER=1 uv run pytest tests/test_proxy_tunnel_real_docker.py``. Everything it makes is
named ``cpgrd-<random>-*`` and removed at the end, the image too.

The tunnel here is a stand-in that keeps what matters of cp-tunnel: Docker gives its namespace an interface and a
default route before its first command, so it is open for OPEN_SECONDS (the moment before cp-tunnel's drop-all
table, widened from milliseconds so the test can hit it); then a table that lets nothing out but loopback is
loaded (the kill switch, with no proxy to reach), and only then /run/ready is written. The earner sends a UDP
datagram to a sink on the bridge every 20 ms. Any datagram the sink gets left a namespace with no firewall in it:
a leak. The worker's own code starts the earner (proxy_tunnel._start_in_ready_run) and the tunnel
(proxy_tunnel._start_down_tunnel), under the proxy's lock.
"""

from __future__ import annotations

import contextlib
import io
import os
import random
import threading
import time
import uuid

import pytest

docker = pytest.importorskip("docker")

pytestmark = pytest.mark.skipif(
    os.environ.get("CASHPILOT_REAL_DOCKER") != "1", reason="needs a real Docker daemon: set CASHPILOT_REAL_DOCKER=1"
)

from docker.errors import APIError  # noqa: E402

from app import orchestrator, proxy_tunnel  # noqa: E402

PREFIX = f"cpgrd-{uuid.uuid4().hex[:8]}"
IMAGE = f"{PREFIX}-nft:1"
ALPINE = "alpine:3.22@sha256:2e0b81d60597f449baa56dc25d355367869d2dca4cd57e866f1e2b52af3eb55f"
SOCAT = "alpine/socat:1.8.0.3"
PROXY_ID = 4242
OPEN_SECONDS = 0.5

TUNNEL_SH = f"""
rm -f /run/ready /run/die
sleep {OPEN_SECONDS}
nft -f - <<'EOF'
table inet cpgrd {{
    chain out {{ type filter hook output priority 0; policy drop; oifname "lo" accept; }}
}}
EOF
echo '{{"ip":"203.0.113.50","country":"ZZ"}}' > /run/ready
while [ ! -f /run/die ]; do sleep 0.05; done
exit 1
"""
EARNER_SH = """
trap 'exit 0' TERM
while :; do
    echo "leak-$ARM" | nc -u -w 1 "$SINK" 9999 2>/dev/null &
    sleep 0.02
done
"""


class Lab:
    def __init__(self, client, network, sink, sink_ip):
        self.client, self.network, self.sink, self.sink_ip = client, network, sink, sink_ip

    def leaks(self, arm: str) -> int:
        return self.sink.logs().count(f"leak-{arm}".encode())

    def tunnel(self, arm: str, policy: str):
        return self.client.containers.run(
            IMAGE,
            ["sh", "-c", TUNNEL_SH],
            name=f"{PREFIX}-{arm}-tunnel",
            network=self.network.name,
            cap_add=["NET_ADMIN"],
            tmpfs={"/run": "size=1m"},
            restart_policy={"Name": policy},
            detach=True,
        )

    def earner(self, arm: str, network_mode: str):
        return self.client.containers.create(
            IMAGE,
            ["sh", "-c", EARNER_SH],
            name=f"{PREFIX}-{arm}-earner",
            network_mode=network_mode,
            environment={"SINK": self.sink_ip, "ARM": arm},
            restart_policy={"Name": "no"},
        )


def _remove_everything(client) -> None:
    for c in client.containers.list(all=True, filters={"name": PREFIX}):
        with contextlib.suppress(Exception):
            c.remove(force=True, v=True)
    for n in client.networks.list(names=[f"{PREFIX}-net"]):
        with contextlib.suppress(Exception):
            n.remove()
    with contextlib.suppress(Exception):
        client.images.remove(IMAGE, force=True)


@pytest.fixture(scope="module")
def lab():
    client = docker.from_env()
    try:
        dockerfile = f"FROM {ALPINE}\nRUN apk add --no-cache nftables\n"
        client.images.build(fileobj=io.BytesIO(dockerfile.encode()), tag=IMAGE, rm=True)
        network = client.networks.create(f"{PREFIX}-net", driver="bridge")
        sink = client.containers.run(
            SOCAT, ["-u", "UDP-RECV:9999", "-"], name=f"{PREFIX}-sink", network=network.name, detach=True
        )
        sink.reload()
        yield Lab(client, network, sink, sink.attrs["NetworkSettings"]["Networks"][network.name]["IPAddress"])
    finally:
        _remove_everything(client)


@pytest.fixture(autouse=True)
def _quick_stops(monkeypatch):
    monkeypatch.setattr(orchestrator, "_get_stop_timeout", lambda _slug: 1)


def _wait_ready(tunnel, timeout: float = 10) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with contextlib.suppress(Exception):
            tunnel.reload()
            if proxy_tunnel._read_exit(tunnel) is not None:
                return True
        time.sleep(0.05)
    return False


def _kill(tunnel) -> None:
    """The tunnel process dies (as when tun2proxy exits), at once."""
    with contextlib.suppress(Exception):
        tunnel.exec_run(["touch", "/run/die"])


def _race(lab: Lab, arm: str, policy: str, rounds: int, *, wait_for_restart: float, background: bool) -> dict:
    """Start the earner ``rounds`` times through the worker's guarded start. On every other round (every round
    without ``background``) the tunnel is killed inside the start, after the run was read as ready and before
    Docker starts the earner, and the start waits ``wait_for_restart`` for a new run of the tunnel to come up.
    With ``background``, the heartbeat's tunnel start runs all along and the tunnel is also killed at random."""
    tunnel = lab.tunnel(arm, policy)
    earner = lab.earner(arm, f"container:{tunnel.id}")
    assert _wait_ready(tunnel), "the stand-in tunnel never wrote /run/ready"
    lock = proxy_tunnel._deploy_lock(PROXY_ID)
    real_start = earner.start
    stats = {"started": 0, "refused": 0, "raced": 0}

    def start_while_the_tunnel_restarts(*args, **kwargs):
        stats["raced"] += 1
        run = proxy_tunnel._started_at(tunnel)
        _kill(tunnel)
        deadline = time.monotonic() + wait_for_restart
        while time.monotonic() < deadline:
            with contextlib.suppress(Exception):
                tunnel.reload()
                if tunnel.status == "running" and proxy_tunnel._started_at(tunnel) != run:
                    break  # a new run, which has not loaded its table yet
            time.sleep(0.02)
        return real_start(*args, **kwargs)

    stop = threading.Event()

    def heartbeat():
        own = docker.from_env().containers.get(tunnel.id)
        while not stop.is_set():
            proxy_tunnel._start_down_tunnel(own, str(PROXY_ID))
            stop.wait(0.05)

    def killer():
        own = docker.from_env().containers.get(tunnel.id)
        while not stop.wait(random.uniform(1.0, 2.5)):
            _kill(own)

    threads = [threading.Thread(target=heartbeat), threading.Thread(target=killer)] if background else []
    for t in threads:
        t.start()
    try:
        for i in range(rounds):
            with contextlib.suppress(Exception):
                earner.reload()
                if earner.status == "running":
                    earner.stop(timeout=1)
            _wait_ready(tunnel, 5)
            with lock:
                earner.start = start_while_the_tunnel_restarts if (i % 2 == 0 or not background) else real_start
                try:
                    stats["started" if proxy_tunnel._start_in_ready_run(earner, tunnel, "x") else "refused"] += 1
                except Exception:  # noqa: BLE001 - Docker refused to join a tunnel that is down
                    stats["refused"] += 1
            time.sleep(random.uniform(0.2, 0.5))  # the earner sends from where it is
    finally:
        stop.set()
        for t in threads:
            t.join()
        with contextlib.suppress(Exception):
            earner.stop(timeout=1)
    time.sleep(1.5)  # datagrams still in flight
    stats["leaks"] = lab.leaks(arm)
    return stats


def test_control_the_sink_sees_an_earner_with_no_tunnel(lab):
    earner = lab.earner("open", lab.network.name)
    earner.start()
    time.sleep(1.5)
    earner.stop(timeout=1)
    time.sleep(1)
    assert lab.leaks("open") > 10


def test_no_earner_ever_joins_a_run_that_has_not_proved_its_exit(lab):
    """No restart policy, as every tunnel has now: a kill inside the start leaves the tunnel down until the
    heartbeat starts it, which it cannot while the start holds the lock. Many rounds, with random kills too."""
    stats = _race(lab, "guarded", "no", 30, wait_for_restart=1.0, background=True)
    print(stats)
    assert stats["raced"] >= 8 and stats["started"] >= 5, stats  # the race ran, and copies did start
    assert stats["leaks"] == 0, stats


def test_control_with_dockers_restart_policy_the_same_race_leaks(lab):
    """unless-stopped, as tunnels had before: Docker starts a new run by itself inside the start, the earner
    joins it before its table is in, and sends from the box. The check after the start stops it, too late."""
    stats = _race(lab, "restarting", "unless-stopped", 4, wait_for_restart=5.0, background=False)
    print(stats)
    assert stats["raced"] >= 1 and stats["leaks"] > 0, stats


def _ready_pair(lab: Lab, arm: str):
    tunnel = lab.tunnel(arm, "no")
    earner = lab.earner(arm, f"container:{tunnel.id}")
    assert _wait_ready(tunnel)
    return tunnel, earner


def _inspect_fails_after_the_start(tunnel) -> None:
    real = tunnel.reload
    calls = {"n": 0}

    def reload():
        calls["n"] += 1
        if calls["n"] > 1:
            raise APIError("500 Server Error: inspect timed out")
        real()

    tunnel.reload = reload


def test_a_failed_inspect_after_the_start_stops_the_earner(lab):
    tunnel, earner = _ready_pair(lab, "inspect")
    _inspect_fails_after_the_start(tunnel)
    with proxy_tunnel._deploy_lock(PROXY_ID):
        assert proxy_tunnel._start_in_ready_run(earner, tunnel, "x") is False
    earner.reload()
    assert earner.status == "exited"
    time.sleep(1)
    assert lab.leaks("inspect") == 0


def test_a_failed_stop_leaves_the_earner_in_the_run_it_proved(lab):
    """The inspect after the start fails and so does the stop: the start raises, and the earner stays in the
    run it read as ready, because nothing can start a new run of the tunnel meanwhile. No datagram leaves."""
    tunnel, earner = _ready_pair(lab, "stop")
    run = proxy_tunnel._started_at(tunnel)
    _inspect_fails_after_the_start(tunnel)
    real_stop = earner.stop

    def stop(*args, **kwargs):
        raise APIError("500 Server Error: stop timed out")

    earner.stop = stop
    with proxy_tunnel._deploy_lock(PROXY_ID), pytest.raises(APIError, match="stop timed out"):
        proxy_tunnel._start_in_ready_run(earner, tunnel, "x")
    earner.reload()
    fresh = lab.client.containers.get(tunnel.id)
    assert earner.status == "running" and fresh.status == "running" and proxy_tunnel._started_at(fresh) == run
    time.sleep(2)
    real_stop(timeout=1)
    time.sleep(1)
    assert lab.leaks("stop") == 0
