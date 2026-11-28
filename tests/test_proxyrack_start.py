"""ProxyRack copies keep their client when ProxyRack's update host is down (#875).

The image's own start (/app/run.sh) deletes /app/script.js and downloads it
again, once. On 2026-11-27 app-updates.sock.sh refused connections, so every
new copy, and every restart of a working one, ended up up and earning nothing.
The catalog's entrypoint replaces that start. Its behaviour on the real image
was checked on a box against a stand-in update host: a copy started during the
outage waited and retried, then connected when the host came back, and a copy
restarted during the outage kept both client files and connected again.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from app import catalog, orchestrator, producer_state
from tests.test_storj_stop_grace import _run_kwargs

WAITING = (
    "2026-11-27T23:24:37.000000000Z [CashPilot] ProxyRack's update server cannot be reached, and ProxyRack's "
    "client cannot start without it. Trying again in 5 minutes."
)
STOPPED = "2026-11-27T23:18:08.000000000Z [CashPilot] ProxyRack's client stopped. Starting it again in 5 minutes."
CONNECTED = "2026-11-27T23:03:07.000000000Z INFO\tdialer_listener/dialer_listener.go:56\tconnected to server"


def _script() -> str:
    return catalog.get_service("proxyrack")["docker"]["entrypoint"][2]


def test_the_worker_deploys_proxyrack_with_the_catalogs_start():
    entrypoint = _run_kwargs(slug="proxyrack", image="proxyrack/pop")["entrypoint"]
    assert entrypoint[:2] == ["/bin/bash", "-c"]
    assert entrypoint[2] == _script()
    assert orchestrator._brings_own_init({}, entrypoint, None) is False, "bash is PID 1, so Docker's init reaps"


@pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")
def test_the_start_script_parses():
    subprocess.run(["bash", "-n", "-c", _script()], check=True)


def test_the_client_is_only_replaced_by_a_checked_download():
    script = _script()
    assert "rm -rf script.js" not in script and "rm -f script.js\n" not in script
    assert "-O script.new.js" in script
    assert "[ -s script.new.js ] && node --check script.new.js" in script, "an empty file passes node --check"
    assert script.index("node --check script.new.js") < script.index("mv -f script.new.js script.js")


def test_the_client_only_runs_when_the_update_host_answers():
    """Started without the host, the client empties /app/PoP_go and never recovers."""
    script = _script()
    lookup = script.index('version=$(curl -fsS -m 30 "$url/version.txt")')
    gate = script.index('if [ -s script.js ] && [ -n "$version" ]; then')
    assert lookup < gate < script.index("node script.js")
    assert "rm -f PoP_go go_version.txt" in script[gate : script.index("node script.js")]


def test_the_start_keeps_the_vendors_node_arguments():
    script = _script()
    node = (
        'node script.js --homeIp point-of-presence.sock.sh --homePort 443 --id "$UUID" '
        '--version "$version" --clientKey proxyrack-pop-client --clientType PoP'
    )
    assert node in script
    assert "/app/api.cfg" in script and 'DEVICE_NAME:-"Device-$UUID"' in script


def test_the_registration_retries_a_failed_request_and_encodes_the_name():
    """run.sh took a curl failure (empty answer) for success and wrote api.cfg, and pasted the name into JSON."""
    script = _script()
    assert "JSON.stringify({device_id: process.env.UUID, device_name: process.env.device_name})" in script
    assert '-d "$payload"' in script
    success = script.index('echo "Device added successfully!"')
    check = script.index('[ -n "$response" ] && ! echo "$response" | grep -Eq \'"status" *: *"error"\'')
    assert script.index("if response=$(curl -fsS") < check < success < script.index("touch /app/api.cfg")


def test_a_client_that_exits_is_started_again_in_the_same_container():
    script = _script()
    assert "exec node" not in script
    after = script[script.index("node script.js") :]
    assert "ProxyRack's client stopped" in after and "sleep 300" in after
    assert script.rstrip().endswith("done")


def test_a_waiting_copy_is_shown_and_never_restarted():
    signals = [s for s in producer_state.signals_for(catalog.get_service("proxyrack")) if producer_state.is_windowed(s)]
    (signal,) = [s for s in signals if not s.get("restart")]
    for line in (WAITING, STOPPED):
        printed = line.split("Z ", 1)[1]
        assert printed in _script(), "the signal must match a line the start really prints"
        assert producer_state.windowed_hit(line, signal)
        assert not producer_state.windowed_hit(f"{line}\n{CONNECTED}", signal)
    assert "nothing to fix on your side" in signal["means"]
