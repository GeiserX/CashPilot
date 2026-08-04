"""CashPilot-jtv: a worker that cannot read Docker fabricated downtime for everything.

``orchestrator.get_status()`` returns ``[]`` when the Docker client cannot be
built, and the worker sends that empty list alongside ``docker_available: false``
while continuing to heartbeat normally. ``_run_health_check`` only asked whether
*some* worker was online — it never read ``docker_available`` — so it wrote a
durable ``check_down`` ("missing from heartbeat") for EVERY deployment, every
five minutes.

The user watches every service's Health column fall and its uptime read 0% while
the containers are up and earning, and the events persist in ``health_events``,
dragging the 7-day score long after the socket is fixed.

Reproduced by unmounting /var/run/docker.sock and restarting only the worker.

The ``deployments`` table has no worker column, so a missing container cannot be
attributed to a particular host: if any online worker is blind, the container
might be on that one. Unknown is not down, so nothing is recorded — the score is
left untouched rather than invented. That is the same rule this codebase applies
to unreadable balances, unknown costs and unreachable machines.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest


def _worker(*, online=True, docker=True, name="watchtower", containers="[]"):
    return {
        "id": 1,
        "client_id": f"cid-{name}",
        "name": name,
        "status": "online" if online else "offline",
        "containers": containers,
        "apps": "[]",
        "system_info": json.dumps({"docker_available": docker}),
        "last_heartbeat": "2026-08-04T12:00:00",
    }


def _events(workers, deployments):
    """The batched events _run_health_check would write."""
    from app.main import _run_health_check

    recorded = AsyncMock()
    with (
        patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
        patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=deployments),
        patch("app.main.database.record_health_events", recorded),
    ):
        asyncio.run(_run_health_check())
    return list(recorded.call_args.args[0]) if recorded.call_args else []


DEPLOYMENTS = [{"slug": "honeygain", "status": "running"}, {"slug": "traffmonetizer", "status": "running"}]


class TestABlindWorkerDoesNotProveAnythingIsDown:
    def test_nothing_is_recorded_when_the_only_worker_cannot_read_docker(self):
        events = _events([_worker(docker=False)], DEPLOYMENTS)
        assert not [e for e in events if e[1] == "check_down"], (
            f"downtime was fabricated for containers nobody could see: {events}"
        )

    def test_a_docker_capable_worker_still_reports_a_missing_container(self):
        """The control. Without it this passes by never recording anything.

        A genuinely missing container on a worker that CAN see Docker is real
        evidence, and losing it would freeze the health score wherever it was.
        """
        events = _events([_worker(docker=True)], DEPLOYMENTS)
        assert ("honeygain", "check_down", "missing from heartbeat") in events

    def test_one_blind_worker_suppresses_it_for_the_whole_fleet(self):
        """deployments has no worker column, so the container might be on it.

        Recording downtime here would be a guess about which host owns which
        container — precisely the guess that produced the bug.
        """
        events = _events([_worker(docker=True, name="a"), _worker(docker=False, name="b")], DEPLOYMENTS)
        assert not [e for e in events if e[2] == "missing from heartbeat"]

    def test_a_missing_docker_available_field_counts_as_blind(self):
        """Absent is not "yes". An old or partial heartbeat is not evidence."""
        worker = _worker(docker=True)
        worker["system_info"] = "{}"
        assert not [e for e in _events([worker], DEPLOYMENTS) if e[1] == "check_down"]

    def test_an_offline_worker_does_not_suppress_anything(self):
        """Only ONLINE workers are consulted; an offline one is already handled."""
        workers = [_worker(docker=True, name="a"), _worker(online=False, docker=False, name="b")]
        events = _events(workers, DEPLOYMENTS)
        assert ("honeygain", "check_down", "missing from heartbeat") in events

    def test_no_workers_at_all_records_nothing(self):
        """Pre-existing behaviour: with nothing online there is nothing to say."""
        assert not [e for e in _events([], DEPLOYMENTS) if e[1] == "check_down"]


class TestTheRealSignalsAreUnaffected:
    def test_a_reported_running_container_is_still_healthy(self):
        containers = json.dumps([{"slug": "honeygain", "status": "running"}])
        events = _events([_worker(docker=True, containers=containers)], DEPLOYMENTS)
        assert ("honeygain", "check_ok", "") in events

    def test_a_reported_stopped_container_is_still_down(self):
        """Direct evidence from a worker that CAN see: that is not a guess."""
        containers = json.dumps([{"slug": "honeygain", "status": "exited"}])
        events = _events([_worker(docker=True, containers=containers)], DEPLOYMENTS)
        assert ("honeygain", "check_down", "exited") in events

    def test_an_external_deployment_is_still_never_flagged(self):
        """It is reported by no worker by design; flagging it would be constant."""
        events = _events([_worker(docker=True)], [{"slug": "grass", "status": "external"}])
        assert not [e for e in events if e[0] == "grass"]

    def test_a_blind_worker_still_reports_what_it_can_see(self):
        """If it somehow lists a container, that reading is still used.

        The suppression is about inferring absence, not about distrusting the
        worker entirely.
        """
        containers = json.dumps([{"slug": "honeygain", "status": "running"}])
        events = _events([_worker(docker=False, containers=containers)], DEPLOYMENTS)
        assert ("honeygain", "check_ok", "") in events


class TestTheOperatorIsTold:
    def test_it_logs_which_workers_are_blind(self, caplog):
        """Silence here would turn a visible wrong number into an invisible gap."""
        import logging

        with caplog.at_level(logging.WARNING, logger="app.main"):
            caplog.clear()
            _events([_worker(docker=False, name="geiserback")], DEPLOYMENTS)
        messages = [r.getMessage() for r in caplog.records]
        assert any("cannot read Docker" in m for m in messages)
        assert any("geiserback" in m for m in messages)

    def test_it_stays_quiet_on_a_healthy_fleet(self, caplog):
        """The control: this must not warn on every ordinary check cycle."""
        import logging

        with caplog.at_level(logging.WARNING, logger="app.main"):
            caplog.clear()
            _events([_worker(docker=True)], DEPLOYMENTS)
        assert not [r for r in caplog.records if "cannot read Docker" in r.getMessage()]


@pytest.mark.parametrize("docker_available", [True, False])
def test_the_worker_still_reports_the_field_this_depends_on(docker_available):
    """The premise: worker_api puts docker_available in every heartbeat."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "worker_api.py").read_text(encoding="utf-8")
    assert '"docker_available"' in source
