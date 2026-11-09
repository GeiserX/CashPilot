"""A slow start is not a failed deploy; the range cap fits a start; a held node says why.

Measured on a live node (Nov 2026): a Mysterium container publishing 1,000 UDP
ports took about 51 s to start. The worker reaches Docker through the socket
proxy, which stops waiting for an answer after 30 s and answers 502. The worker
took that as a refused start, removed the new container while Docker was still
starting it, and the node was down. The operator put the old container back by
hand, and the guard stopped it again as a leftover of the failed deploy, with
nothing saying that only a redeploy from CashPilot brings it back.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
import requests

from app import catalog, constants, drift, lan_fence, orchestrator
from tests import test_mysterium_fenced as fenced
from tests.test_mysterium_fenced import (
    BIND_REFUSED,
    MYST,
    _api_error,
    _FakeDocker,
    _guard,
    _node,
    _raw_deploy,
    _running_old,
    _shape,
    _ui_deploy,
    _up_on,
)

# The fixtures the fenced tests use, shared rather than copied.
markers = fenced.markers
ui = fenced.ui

pytestmark = pytest.mark.real_gated_mode


def _gateway(status=502):
    """What the socket proxy answers when it stopped waiting for Docker."""
    response = MagicMock(status_code=status)
    return orchestrator.APIError(
        f"{status} Server Error", response=response, explanation="upstream Docker socket unreachable"
    )


def _starts_late(container, *, polls=1, ends="running", error=""):
    """A start Docker finishes after the call gave up: ``polls`` reads show it created, then ``ends``."""
    seen = {"n": 0}
    container.status = "created"
    container.attrs = {**_up_on(running=False), "State": {"Running": False, "Error": ""}}

    def reload():
        seen["n"] += 1
        if seen["n"] > polls:
            container.status = ends
            container.attrs = {
                **_up_on(running=ends == "running"),
                "State": {"Running": ends == "running", "Error": error},
            }

    container.reload.side_effect = reload
    return seen


@pytest.fixture
def fast_poll(monkeypatch):
    monkeypatch.setattr(orchestrator, "_START_POLL_SECONDS", 0)


# ---------------------------------------------------------------------------
# 1. A start Docker is slow to answer is waited out, not rolled back
# ---------------------------------------------------------------------------


class TestASlowStartIsNotAFailedDeploy:
    def test_a_start_the_proxy_gave_up_on_is_kept_once_it_runs(self, markers, fast_poll):
        old = _running_old()
        docker = _FakeDocker(old)
        docker.created.start.side_effect = _gateway(502)
        seen = _starts_late(docker.created, polls=2)
        _raw_deploy(client=docker.client, old=old)
        assert seen["n"] >= 3
        assert not getattr(docker.created, "removed", False), "the node Docker was starting must not be removed"
        assert docker.get("cashpilot-mysterium") is docker.created
        assert old.removed, "the old node goes once the new one runs"
        old.start.assert_not_called()
        assert orchestrator.deploy_failed() == set()

    def test_a_gateway_timeout_is_waited_out_too(self, markers, fast_poll):
        old = _running_old()
        docker = _FakeDocker(old)
        docker.created.start.side_effect = _gateway(504)
        _starts_late(docker.created)
        _raw_deploy(client=docker.client, old=old)
        assert docker.get("cashpilot-mysterium") is docker.created and old.removed

    def test_docker_pys_own_read_timeout_on_an_ordinary_earner(self, markers, fast_poll):
        labels = {"cashpilot.service": "honeygain", "cashpilot.managed": "true"}
        old = _running_old("cashpilot-honeygain", labels)
        docker = _FakeDocker(old)
        # run() is create and start in one call: the container exists, the call timed out.
        docker.create_error = requests.exceptions.ReadTimeout("Read timed out. (read timeout=60)")
        _starts_late(docker.created)
        _raw_deploy(client=docker.client, old=old, slug="honeygain")
        assert docker.get("cashpilot-honeygain") is docker.created
        assert not getattr(docker.created, "removed", False) and old.removed

    def test_a_start_that_ends_exited_is_rolled_back(self, markers, fast_poll):
        old = _running_old()
        docker = _FakeDocker(old)
        docker.created.start.side_effect = _gateway(502)
        _starts_late(docker.created, ends="exited")
        with pytest.raises(orchestrator.ContainerRuntimeError, match="did not start") as failed:
            _raw_deploy(client=docker.client, old=old)
        assert "put back and is running again" in str(failed.value)
        assert docker.get("cashpilot-mysterium") is old and docker.created.removed

    def test_a_start_docker_reports_failed_is_rolled_back(self, markers, fast_poll):
        old = _running_old()
        docker = _FakeDocker(old)
        docker.created.start.side_effect = _gateway(502)
        _starts_late(docker.created, ends="created", error=BIND_REFUSED)
        with pytest.raises(orchestrator.ContainerRuntimeError, match="address already in use"):
            _raw_deploy(client=docker.client, old=old)
        assert docker.get("cashpilot-mysterium") is old

    def test_a_start_still_not_running_at_the_bound_is_rolled_back(self, markers, fast_poll):
        old = _running_old()
        docker = _FakeDocker(old)
        docker.created.start.side_effect = _gateway(502)
        _starts_late(docker.created, polls=10**9)
        clock = iter(range(0, 10**6, 30))
        with (
            patch.object(orchestrator.time, "monotonic", side_effect=lambda: next(clock)),
            pytest.raises(
                orchestrator.ContainerRuntimeError, match=f"not running {constants.START_SETTLE_SECONDS} s"
            ) as failed,
        ):
            _raw_deploy(client=docker.client, old=old)
        assert docker.get("cashpilot-mysterium") is old
        # Rolled back, so final: a 504 would tell main the worker may still be
        # deploying, and main keeps a proxied copy's record for a copy no box runs.
        assert failed.value.status_code != 504

    def test_control_a_refusal_is_not_waited_on(self, markers, fast_poll):
        old = _running_old()
        docker = _FakeDocker(old)
        docker.created.start.side_effect = _api_error(BIND_REFUSED)
        with pytest.raises(orchestrator.ContainerRuntimeError, match="put back"):
            _raw_deploy(client=docker.client, old=old)
        docker.created.reload.assert_not_called()

    def test_control_a_gated_create_with_no_answer_is_not_waited_on(self, markers, fast_poll):
        # The node was never started, so there is no start to wait for.
        old = _running_old()
        docker = _FakeDocker(old)
        docker.create_error = _gateway(502)
        with pytest.raises(orchestrator.ContainerRuntimeError, match="put back"):
            _raw_deploy(client=docker.client, old=old)
        docker.created.start.assert_not_called()
        docker.created.reload.assert_not_called()

    def test_the_ui_waits_as_long_as_the_worker_may(self):
        import asyncio
        from unittest.mock import AsyncMock

        from app import main

        proxy = AsyncMock(return_value={})
        with patch("app.main._proxy_to_worker", proxy):
            asyncio.run(main._proxy_worker_deploy(1, "mysterium", {}))
        assert proxy.call_args.kwargs["timeout"] >= 60 + 30 + constants.START_SETTLE_SECONDS

    @pytest.mark.parametrize(("slug", "waits_for_deploy"), [("mysterium", True), ("honeygain", False)])
    def test_a_stop_sent_during_a_redeploy_waits_for_the_deploy_lock(self, slug, waits_for_deploy):
        # The worker stops a fence-gated node under the lock deploy_raw holds
        # while it waits out a slow start. Cut off sooner, a stop that goes
        # through answers 504, is never recorded, and the container-down alert
        # fires for a node stopped on purpose. A service without the fence
        # takes no lock, and its wait is unchanged (the control).
        import asyncio
        from unittest.mock import AsyncMock

        from app import main

        proxy = AsyncMock(return_value={})
        with patch("app.main._proxy_to_worker", proxy):
            asyncio.run(main._proxy_worker_command(1, "stop", slug))
            stop_alone = 30 + main._catalog_stop_timeout(slug)
            deploy = main._deploy_timeout(slug)
        expected = stop_alone + deploy if waits_for_deploy else stop_alone
        assert proxy.call_args.kwargs["timeout"] == expected


# ---------------------------------------------------------------------------
# 2. The UDP range cap is one a deploy can start within
# ---------------------------------------------------------------------------

WIDE = {
    "image": MYST["docker"]["image"],
    "env": {"UI_ADDRESS": "127.0.0.1", "UDP_PORTS": "23000:23999"},
    "volumes": {"mysterium-data": {"bind": "/var/lib/mysterium-node", "mode": "rw"}},
}


class TestTheRangeCap:
    def test_the_cap_is_300(self):
        assert catalog.MAX_UDP_PORTS == 300
        assert MYST["docker"]["udp_port_range"]["max_ports"] == 300

    def test_301_ports_are_refused_and_300_are_not(self):
        with pytest.raises(ValueError, match="at most 300"):
            catalog.expand_udp_range("23000:23300", 300)
        assert len(catalog.expand_udp_range("23000:23299", 300)) == 300

    def test_a_typed_range_over_the_cap_is_refused_with_what_to_do(self, ui):
        resp, sent = _ui_deploy(ui, {"env": {"UDP_PORTS": "23000:23999"}})
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "at most 300" in detail and "23000:23299" in detail and "router" in detail
        assert not sent

    def test_a_redeploy_of_a_wider_recorded_range_is_refused_not_cut(self, ui):
        resp, sent = _ui_deploy(ui, {"env": {}}, recorded=WIDE)
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "spans 1000 ports" in detail and "was not touched" in detail
        assert not sent, "nothing reaches the worker, so the running node keeps running"

    def test_control_a_narrower_range_typed_over_the_wide_record_deploys(self, ui):
        resp, sent = _ui_deploy(ui, {"env": {"UDP_PORTS": "23000:23299"}}, recorded=WIDE)
        assert resp.status_code == 200, resp.text
        assert sum(k.endswith("/udp") for k in sent["ports"]) == 300

    def test_the_guard_keeps_a_running_node_with_a_wider_range(self, markers):
        node = _node(status="running")
        node.attrs["Config"]["Env"] = ["UDP_PORTS=23000:23999"]
        node.attrs["HostConfig"]["PortBindings"].update(
            {f"{p}/udp": [{"HostIp": "", "HostPort": str(p)}] for p in range(23000, 24000)}
        )
        held, _ = _guard([node])
        assert held == {}
        node.stop.assert_not_called()

    def test_drift_does_not_flag_a_node_running_its_wider_recorded_range(self):
        shape = _shape()
        shape["ports"] = sorted({*shape["ports"], *(f"{p}/udp" for p in range(23000, 24000))})
        found = drift.container_drift(MYST, shape, {"env": {"UDP_PORTS": "23000:23999"}})
        assert not any("/udp" in f for f in found)


# ---------------------------------------------------------------------------
# 3. A node the failed-deploy record holds says why, and what brings it back
# ---------------------------------------------------------------------------


class TestAHeldNodeSaysWhy:
    def test_a_hand_restored_node_is_stopped_with_the_way_back_in_the_log(self, markers, caplog):
        orchestrator._mark_failed("cashpilot-mysterium", True)
        node = _node(status="running")
        with caplog.at_level(logging.WARNING, logger="app.lan_fence"):
            held, _ = _guard([node])
        node.stop.assert_called_once()
        why = held["cashpilot-mysterium"]
        assert "put back or started by hand" in why and "Redeploy it from the CashPilot dashboard" in why
        assert any(
            "Stopping cashpilot-mysterium" in r.message and "Redeploy it from" in r.message for r in caplog.records
        )

    def test_the_heartbeat_carries_the_reason(self, markers):
        orchestrator._mark_failed("cashpilot-mysterium", True)
        node = _node(status="exited")
        _guard([node])
        assert orchestrator._held_entry(node) == {"held": lan_fence.FAILED_DEPLOY}

    def test_control_a_node_the_guard_does_not_hold_carries_nothing(self, markers):
        node = _node(status="running")
        _guard([node])
        assert orchestrator._held_entry(node) == {}

    def test_the_container_down_alert_says_why_and_what_to_do(self):
        from app import main

        copies = [
            {"_down_since": datetime.now(UTC), "_node": "w1", "restart_policy": "no", "held": lan_fence.FAILED_DEPLOY}
        ]
        message = main._container_down_message("mysterium", copies)
        assert "The worker keeps it stopped: its last deploy from CashPilot failed" in message
        assert "Redeploy it from the CashPilot dashboard" in message

    def test_the_dashboard_offers_a_redeploy_for_a_held_copy(self):
        from pathlib import Path

        js = (Path(__file__).resolve().parent.parent / "app/static/js/app.js").read_text()
        block = js[js.index("if (inst.held) {") : js.index("continue;", js.index("if (inst.held) {"))]
        assert "Held stopped" in block and 'data-action="redeployOnWorker"' in block

    def test_the_ui_keeps_the_reason_from_the_heartbeat(self):
        import asyncio
        import json

        from app import main

        worker = {
            "id": 7,
            "name": "alpha",
            "status": "online",
            "system_info": json.dumps({"docker_available": True}),
            "containers": json.dumps([{"slug": "mysterium", "status": "exited", "held": lan_fence.FAILED_DEPLOY}]),
        }
        [entry] = asyncio.run(main._get_all_worker_containers([worker]))
        assert entry["held"] == lan_fence.FAILED_DEPLOY


class TestTheMoveAdviceForAWideRange:
    WIDE_HOST_RECORD = {"env": {"UI_ADDRESS": "127.0.0.1", "UDP_PORTS": "56000:56999"}, "network_mode": "host"}

    def test_a_range_over_the_cap_is_told_to_narrow_not_to_reserve(self):
        move = drift.move_advice(MYST, _shape(network_mode="host"), self.WIDE_HOST_RECORD, lan_fence.MODE_ON)
        warning = move["warning"]
        assert "spans 1000 ports" in warning and "at most 300 ports" in warning
        assert "reserve it on the host" not in warning

    def test_control_a_range_within_the_cap_keeps_the_reservation_option(self):
        record = {**self.WIDE_HOST_RECORD, "env": {"UDP_PORTS": "56000:56100"}}
        warning = drift.move_advice(MYST, _shape(network_mode="host"), record, lan_fence.MODE_ON)["warning"]
        assert "reserve it on the host" in warning
