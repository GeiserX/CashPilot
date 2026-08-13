"""A worker that cannot see Docker must say so — loudly, and in-band.

Three fixes pinned here:

- Docker dying mid-life was a logger.debug, invisible at the default INFO
  level: the worker silently degraded to monitor-only and `docker logs` held
  no reason at all. The True -> False transition now warns once.
- "Ping works, list fails" escaped get_status, so the heartbeat shipped
  containers=[] WITH docker_available=true — an online-looking worker the UI
  then punished with a durable check_down for every deployment it could no
  longer see. The enumeration failure now flags the outage so the same
  heartbeat reports blind.
- The deploy route called available_runtimes() unthreaded — a live daemon
  round-trip with no cache and no timeout on the event loop, starving
  /api/health on a wedged daemon.
"""

import logging
import os

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

try:
    from app import orchestrator  # noqa: E402
except ImportError:
    pytest.skip(
        "Requires full app dependencies — runs in CI",
        allow_module_level=True,
    )

from unittest.mock import MagicMock, patch  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_docker_memo():
    before = orchestrator._docker_available
    orchestrator._docker_available = None
    yield
    orchestrator._docker_available = before


class TestMidLifeDockerLossIsLoud:
    def test_true_to_false_warns_once(self, caplog):
        orchestrator._docker_available = True
        with caplog.at_level(logging.WARNING, logger=orchestrator.logger.name):
            orchestrator._mark_docker_unavailable("test", RuntimeError("daemon gone"))
            orchestrator._mark_docker_unavailable("test", RuntimeError("still gone"))
        warns = [r for r in caplog.records if "became unreachable" in r.getMessage()]
        assert len(warns) == 1
        assert orchestrator._docker_available is False

    def test_startup_discovery_stays_quiet(self, caplog):
        # Negative control: None -> False is a monitor-only worker booting,
        # which lifespan already announces — no mid-life warning.
        orchestrator._docker_available = None
        with caplog.at_level(logging.WARNING, logger=orchestrator.logger.name):
            orchestrator._mark_docker_unavailable("test", RuntimeError("no socket"))
        assert not [r for r in caplog.records if "became unreachable" in r.getMessage()]
        assert orchestrator._docker_available is False

    def test_recovery_is_announced(self, caplog):
        orchestrator._docker_available = False
        with caplog.at_level(logging.WARNING, logger=orchestrator.logger.name):
            orchestrator._mark_docker_available()
        assert [r for r in caplog.records if "reachable again" in r.getMessage()]
        assert orchestrator._docker_available is True

    def test_first_success_is_silent(self, caplog):
        # Negative control: None -> True at startup is not a "recovery".
        orchestrator._docker_available = None
        with caplog.at_level(logging.WARNING, logger=orchestrator.logger.name):
            orchestrator._mark_docker_available()
        assert not [r for r in caplog.records if "reachable again" in r.getMessage()]


class TestListFailureFlagsTheOutage:
    def test_enumeration_failure_returns_empty_and_flags_blind(self):
        client = MagicMock()
        client.ping.return_value = True
        client.containers.list.side_effect = RuntimeError("daemon 500")
        orchestrator._docker_available = True
        with patch.object(orchestrator, "_get_client", return_value=client):
            assert orchestrator.get_status() == []
        # The same heartbeat that ships containers=[] must now also report
        # docker_available=False — that is what keeps the UI from writing a
        # durable check_down for every deployment it can no longer see.
        assert orchestrator._docker_available is False

    def test_a_healthy_list_keeps_the_flag(self):
        # Negative control.
        client = MagicMock()
        client.containers.list.return_value = []
        orchestrator._docker_available = True
        with patch.object(orchestrator, "_get_client", return_value=client):
            orchestrator.get_status()
        assert orchestrator._docker_available is True


class TestDeployValidationIsThreaded:
    def test_deploy_route_threads_the_validation(self):
        """The validation must run via to_thread, not on the event loop.

        Pinned by behavior, measured DURING the call: a probe task ticking
        every 10ms is started first, then the deploy route (whose validation
        blocks for 0.4s) is awaited, and the ticks accumulated strictly while
        it ran are compared. Unthreaded, the loop freezes and the probe scores
        ~0 in that window; threaded it keeps ticking. (An earlier version of
        this test measured the probe's own later window, which an unthreaded
        block simply finished before — a check that could not fail.)
        """
        import asyncio
        import contextlib
        import time as _time

        from app import worker_api

        measured = {}

        def _slow_validate(spec, slug=None):
            _time.sleep(0.4)

        async def _drive():
            with (
                patch.object(worker_api, "_verify_api_key", lambda request: None),
                patch.object(worker_api, "_validate_deploy_spec", _slow_validate),
                patch.object(
                    worker_api.orchestrator,
                    "deploy_raw",
                    lambda **kw: (_ for _ in ()).throw(RuntimeError("stop here")),
                ),
            ):
                ticks = {"n": 0}
                stop = asyncio.Event()

                async def _probe():
                    while not stop.is_set():
                        ticks["n"] += 1
                        await asyncio.sleep(0.01)

                probe_task = asyncio.create_task(_probe())
                await asyncio.sleep(0.05)  # the probe is demonstrably ticking
                before = ticks["n"]
                with contextlib.suppress(Exception):
                    await worker_api.api_deploy_container(MagicMock(), "storj", worker_api.DeploySpec(image="x"))
                measured["during"] = ticks["n"] - before
                stop.set()
                await probe_task

        asyncio.run(_drive())
        # Unthreaded, the 0.4s sleep freezes the loop: ~0-2 ticks. Threaded,
        # the probe keeps its ~10ms cadence: ~30+.
        assert measured["during"] > 10
