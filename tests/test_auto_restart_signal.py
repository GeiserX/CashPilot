"""A copy stuck in a state a restart clears is restarted by CashPilot.

A ProxyBase client asks for a relay once, at its start. When that ask fails it
falls back to a default relay that no longer answers, retries it every 15
seconds and never asks again, so it earns nothing until someone restarts it.
The catalog already flags it (a windowed health signal); with ``restart: true``
the windowed sweep also restarts the copy, at most once per copy every
AUTO_RESTART_COOLDOWN_S.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest

from app import catalog, main, producer_state

STUCK = "\n".join(["Failed to connect to 192.0.2.1:2931,", "retrying in 5 seconds."] * 120)
WORKING = STUCK + "\nBalance: $1.23"
WORKER = {"id": 7, "name": "nas", "status": "online", "url": "http://192.168.50.100:8081"}
RUNNING = {"slug": "proxybase", "status": "running", "instance": 1, "_worker_id": 7, "deployed_by": "worker"}
KEY = ("proxybase", 7, 1)


@pytest.fixture(autouse=True)
def _clean():
    main._windowed_hints = {}
    main._auto_restarted_at.clear()
    main._owner_stopped_at.clear()
    main._copy_locks.clear()
    yield
    main._windowed_hints = {}
    main._auto_restarted_at.clear()
    main._owner_stopped_at.clear()
    main._copy_locks.clear()


def _stop_patches(stops):
    """The owner's Stop (main._svc_stop) with the worker call recorded in ``stops``."""

    async def _routed(wid, slug, instance, direct, routed):
        stops.append(("stop", wid, slug, instance))
        return {"status": "stopped"}

    return (
        patch("app.main._require_writer"),
        patch("app.main._resolve_worker_id", new_callable=AsyncMock, side_effect=lambda wid: wid),
        patch("app.main._or_routed", side_effect=_routed),
        patch("app.main.database.record_health_event", new_callable=AsyncMock),
    )


def _sweep(
    logs, *, containers=(RUNNING,), workers=(), restart_error=None, read_error=None, during_read=None, reads=None
):
    """One sweep. Returns the restarts: ``_command_and_record``'s, and a proxied copy's as ("in place", ...).

    ``workers`` are the worker rows whose heartbeats list proxied copies;
    ``reads`` collects each log read's path and params.
    """
    restarts = []

    async def _proxy(wid, method, path, params=None, **kw):
        if method == "POST" and path.endswith("/restart"):
            restarts.append(("in place", wid, path))
            if restart_error:
                raise restart_error
            return {"status": "restarted"}
        if reads is not None:
            reads.append((path, params))
        if during_read:
            await during_read()
        if read_error:
            raise read_error
        return {"logs": logs, "filtered": True}

    async def _command(wid, command, slug, instance):
        restarts.append((wid, command, slug, instance))
        if restart_error:
            raise restart_error
        return {"status": "restarted"}

    with (
        patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=list(workers)),
        patch("app.main._get_all_worker_containers", new_callable=AsyncMock, return_value=list(containers)),
        patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=WORKER),
        patch("app.main.database.get_deployment_spec", new_callable=AsyncMock, return_value=None),
        patch("app.main.database.get_proxy", new_callable=AsyncMock, return_value={"id": 3, "definition": {}}),
        patch("app.main.database.record_health_event", new_callable=AsyncMock),
        patch("app.main._proxy_to_worker", side_effect=_proxy),
        patch("app.main._command_and_record", side_effect=_command),
    ):
        asyncio.run(main._check_windowed_signals())
    return restarts


def test_the_proxybase_signal_asks_for_a_restart():
    signals = [s for s in producer_state.signals_for(catalog.get_service("proxybase")) if producer_state.is_windowed(s)]
    assert [s.get("restart") for s in signals] == [True]


def test_a_stuck_copy_is_restarted_and_still_shown(caplog):
    assert _sweep(STUCK) == [(7, "restart", "proxybase", 1)]
    assert "A restart clears this" in main._windowed_hints[KEY][0]
    assert "Restarted proxybase copy 1 on worker 7 by itself" in caplog.text


def test_a_working_copy_is_left_alone():
    assert _sweep(WORKING) == []


def test_one_restart_per_cooldown_while_it_stays_stuck():
    clock = {"now": 1_000_000.0}
    with patch.object(main.time, "time", side_effect=lambda: clock["now"]):
        assert len(_sweep(STUCK)) == 1
        clock["now"] += main.AUTO_RESTART_COOLDOWN_S - 1
        assert _sweep(STUCK) == []
        clock["now"] += 1
        assert len(_sweep(STUCK)) == 1


def test_a_failed_log_read_keeps_the_cooldown():
    """A read that fails between two stuck passes must not let the next one restart again."""
    clock = {"now": 1_000_000.0}
    with patch.object(main.time, "time", side_effect=lambda: clock["now"]):
        assert len(_sweep(STUCK)) == 1
        clock["now"] += 1800
        assert _sweep(STUCK, read_error=RuntimeError("timed out")) == []
        clock["now"] += 1800
        assert _sweep(STUCK) == []


def test_a_cooldown_that_ended_is_forgotten():
    clock = {"now": 1_000_000.0}
    with patch.object(main.time, "time", side_effect=lambda: clock["now"]):
        _sweep(STUCK)
        assert KEY in main._auto_restarted_at
        clock["now"] += main.AUTO_RESTART_COOLDOWN_S
        _sweep(WORKING)
    assert main._auto_restarted_at == {}


def test_a_container_cashpilot_did_not_deploy_is_never_restarted():
    hand_made = {**RUNNING, "deployed_by": "unknown"}
    assert _sweep(STUCK, containers=(hand_made,)) == []
    assert main._windowed_hints[KEY], "it is still flagged"


def test_a_routed_copy_on_a_named_worker_is_restarted_in_place():
    """A routed row names the node in deployed_by; it is CashPilot's own proxied copy all the same.

    Its logs and its restart go through its proxied copy (the container routes
    answer 404 for it), and the restart is never a stop and a start."""
    routed = {**RUNNING, "deployed_by": "nas", "route": {"proxy_id": 3, "tunnel_status": "running"}}
    reads = []
    assert _sweep(STUCK, containers=(routed,), reads=reads) == [("in place", 7, "/api/proxied/proxybase/3/restart")]
    assert [path for path, _ in reads] == ["/api/proxied/proxybase/3/logs"]
    assert main._windowed_hints[KEY], "its dashboard row (copy 1) shows the hint"
    assert KEY in main._auto_restarted_at


# ---------------------------------------------------------------------------
# A proxied copy (the Proxies page) is judged and restarted where it is
# ---------------------------------------------------------------------------


def _proxied(**entry):
    """A worker row, as the database returns it, whose heartbeat lists one proxied copy of proxybase through proxy 3."""
    copy = {"slug": "proxybase", "proxy_id": 3, "status": "running", "held": False, **entry}
    return {**WORKER, "system_info": json.dumps({"proxied": [copy]})}


PROXIED_KEY = ("proxybase", 7, main.PROXIED_COPY_KEY + 3)


def test_a_stuck_proxied_copy_is_restarted_in_place_once(caplog):
    reads = []
    clock = {"now": 1_000_000.0}
    with patch.object(main.time, "time", side_effect=lambda: clock["now"]):
        assert _sweep(STUCK, containers=(), workers=(_proxied(),), reads=reads) == [
            ("in place", 7, "/api/proxied/proxybase/3/restart")
        ]
        clock["now"] += 1800
        assert _sweep(STUCK, containers=(), workers=(_proxied(),)) == [], "once per cooldown"
    path, params = reads[0]
    assert path == "/api/proxied/proxybase/3/logs"
    assert params["since_hours"] == 1.0 and "retrying in 5 seconds" in params["match"]
    assert "instance" not in params
    assert main._windowed_hints[PROXIED_KEY]
    assert "Restarted proxybase copy through proxy 3 on worker 7 by itself" in caplog.text


def test_a_proxied_copy_is_never_stopped_and_started():
    """A stop marks the copy held: a start that failed after it would leave it stopped for good."""
    with patch("app.main._proxied_command", new_callable=AsyncMock) as command:
        assert len(_sweep(STUCK, containers=(), workers=(_proxied(),))) == 1
    command.assert_not_called()


def test_a_working_proxied_copy_is_left_alone():
    assert _sweep(WORKING, containers=(), workers=(_proxied(),)) == []


def test_a_held_proxied_copy_is_never_read_or_restarted():
    reads = []
    assert _sweep(STUCK, containers=(), workers=(_proxied(held=True),), reads=reads) == []
    assert reads == []


def test_a_stopped_or_offline_proxied_copy_is_never_restarted():
    assert _sweep(STUCK, containers=(), workers=(_proxied(status="exited"),)) == []
    assert _sweep(STUCK, containers=(), workers=({**_proxied(), "status": "offline"},)) == []


def test_a_routed_entry_is_judged_once_as_its_row():
    """The heartbeat lists a routed service's copy among the proxied ones too; its row already stands for it."""
    assert _sweep(STUCK, containers=(), workers=(_proxied(routed=True),)) == []


def test_a_proxied_copy_is_read_only_for_a_signal_that_restarts_it():
    """No page shows a proxied copy's hints, so a signal that only warns is not worth hours of its logs.

    And the worker probes only the service's own copies, so its probe is not asked either."""
    copies = [
        {"slug": "earnapp", "proxy_id": 3, "status": "running"},
        {"slug": "mysterium", "proxy_id": 4, "status": "running"},
    ]
    assert catalog.get_service("mysterium")["docker"].get("health_probe"), "a service with a probe"
    reads = []
    worker = {**WORKER, "system_info": json.dumps({"proxied": copies})}
    assert _sweep("Error: Handshake timeout", containers=(), workers=(worker,), reads=reads) == []
    assert reads == []
    assert main._windowed_hints == {}


def test_an_older_worker_gives_a_proxied_copy_no_verdict():
    """A worker from before the filter returns the plain tail, which is not the window."""
    restarts = []

    async def _proxy(wid, method, path, params=None, **kw):
        if method == "POST":
            restarts.append(path)
        return {"logs": STUCK}

    with (
        patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[_proxied()]),
        patch("app.main._get_all_worker_containers", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=WORKER),
        patch("app.main.database.get_deployment_spec", new_callable=AsyncMock, return_value=None),
        patch("app.main.database.get_proxy", new_callable=AsyncMock, return_value={"id": 3, "definition": {}}),
        patch("app.main._proxy_to_worker", side_effect=_proxy),
    ):
        asyncio.run(main._check_windowed_signals())
    assert restarts == []
    assert PROXIED_KEY not in main._windowed_hints


def test_a_proxied_restart_the_worker_refuses_is_logged_and_never_raises(caplog):
    refused = main.HTTPException(status_code=409, detail="cashpilot-proxybase-p3 was stopped by its owner")
    assert len(_sweep(STUCK, containers=(), workers=(_proxied(),), restart_error=refused)) == 1
    assert "Could not restart proxybase copy through proxy 3 on worker 7 by itself" in caplog.text
    assert PROXIED_KEY in main._auto_restarted_at, "the next try waits for the cooldown"


def test_a_proxied_restart_waits_for_the_copys_stop():
    """The Proxies page Stop and this restart take the same lock: a restart asked during a Stop goes after it."""
    order = []

    async def _run():
        lock = main._proxy_copy_lock(3, 7, "proxybase")
        await lock.acquire()

        async def _proxy(wid, method, path, **kw):
            order.append("restart sent")
            return {"status": "restarted"}

        with (
            patch("app.main.database.get_proxy", new_callable=AsyncMock, return_value={"id": 3, "definition": {}}),
            patch("app.main._proxy_to_worker", side_effect=_proxy),
        ):
            restart = asyncio.create_task(main._auto_restart(PROXIED_KEY, ["stuck"], 0.0, 3))
            for _ in range(20):
                await asyncio.sleep(0)
            order.append("stop done")
            lock.release()
            await restart

    asyncio.run(_run())
    assert order == ["stop done", "restart sent"]


def test_a_container_the_user_runs_by_hand_is_never_restarted():
    external = {**RUNNING, "deployed_by": "external"}
    assert _sweep(STUCK, containers=(external,)) == []


def test_a_copy_the_owner_stops_during_the_check_stays_stopped(caplog):
    stops = []

    async def _owner_stops():
        await main._svc_stop(None, "proxybase", 7, 1)

    p1, p2, p3, p4 = _stop_patches(stops)
    with p1, p2, p3, p4, caplog.at_level("INFO", logger="app.main"):
        assert _sweep(STUCK, during_read=_owner_stops) == []
    assert stops == [("stop", 7, "proxybase", 1)]
    assert KEY not in main._auto_restarted_at, "no cooldown spent on a restart that did not happen"
    assert "Left proxybase copy 1 on worker 7 stopped: the owner stopped it" in caplog.text


def test_a_stop_from_before_the_check_does_not_block_a_restart():
    main._owner_stopped_at[KEY] = 1.0
    assert _sweep(STUCK) == [(7, "restart", "proxybase", 1)]
    assert KEY not in main._owner_stopped_at, "an old stop is forgotten"


def test_a_stop_that_comes_during_the_restart_runs_after_it():
    order = []

    async def _run():
        restarting = asyncio.Event()
        finish = asyncio.Event()

        async def _command(wid, command, slug, instance):
            order.append("restart sent")
            restarting.set()
            await finish.wait()
            order.append("restart done")

        with patch("app.main._command_and_record", side_effect=_command):
            restart = asyncio.create_task(main._auto_restart(KEY, ["stuck"], 0.0))
            await restarting.wait()
            stop = asyncio.create_task(main._svc_stop(None, "proxybase", 7, 1))
            for _ in range(20):  # time enough for an unordered Stop to reach the worker
                await asyncio.sleep(0)
            order.append("stop asked")
            finish.set()
            await restart
            await stop

    p1, p2, p3, p4 = _stop_patches(order)
    with p1, p2, p3, p4:
        asyncio.run(_run())
    assert order == ["restart sent", "stop asked", "restart done", ("stop", 7, "proxybase", 1)]


def test_a_failed_restart_is_logged_and_never_raises(caplog):
    assert len(_sweep(STUCK, restart_error=RuntimeError("worker offline"))) == 1
    assert "Could not restart proxybase copy 1 on worker 7 by itself: worker offline" in caplog.text
    assert main._windowed_hints[KEY]


def test_a_signal_without_restart_restarts_nothing():
    service = catalog.get_service("proxybase")
    signal = {k: v for k, v in service["docker"]["health_signals"][0].items() if k != "restart"}
    with patch.dict(service["docker"], {"health_signals": [signal]}):
        assert _sweep(STUCK) == []
    assert main._windowed_hints[KEY]


class TestTheCatalogKey:
    BASE = {"pattern": "x", "window_hours": 1, "means": "m"}

    @staticmethod
    def _errors(signal):
        return [e for e in catalog._validate({"docker": {"health_signals": [signal]}}, Path("x.yml")) if "restart" in e]

    def test_true_or_false_on_a_windowed_failing_signal(self):
        assert self._errors({**self.BASE, "restart": True}) == []
        assert self._errors({**self.BASE, "restart": False, "state": "failing"}) == []

    @pytest.mark.parametrize(
        "signal",
        [
            {**BASE, "restart": "yes"},
            {"pattern": "x", "means": "m", "restart": True},
            {**BASE, "restart": True, "state": "idle"},
        ],
    )
    def test_anything_else_is_refused(self, signal):
        assert self._errors(signal)
