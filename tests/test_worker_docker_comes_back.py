"""A worker that starts before Docker answers runs its start steps once Docker does.

After a reboot Docker starts containers by their restart policy and ignores
compose depends_on, so the worker can win the race against
cashpilot-socket-proxy. Before this fix the guard, the hold, the proxied-copy
recovery and the migration never started for the life of the process, while
/api/health turned OK, and a fence-gated node (Mysterium, no restart policy)
stayed stopped.

These tests enter the real worker lifespan with every step stubbed and
recorded, so they pin the order and that each step runs once.
"""

from __future__ import annotations

import asyncio
import logging
import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

from app import route_gate, worker_api  # noqa: E402

COME_BACK_LOG = "came back after start"
ONE_TIME = ["hold", "egress", "set-egress", "fence", "guard", "hold", "recover", "sweep"]
#: The min_age each sweep_test_tunnels call got.
SWEEP_MIN_AGES: list[float] = []


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(route_gate, "ROUTED_MARKER", str(tmp_path / ".routed"))
    monkeypatch.delenv(route_gate.PROXIED_ONLY_ENV, raising=False)
    monkeypatch.setattr(worker_api.lan_fence, "GUARD_SECONDS", 0.01)
    SWEEP_MIN_AGES.clear()


def _run(*, docker_at_start: bool, docker_later: bool, proxied_only: bool = False, monkeypatch, wait_loop=None):
    """Enter the lifespan, flip Docker on after a while, and return what ran, in order."""
    if proxied_only:
        monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, "true")
    events: list[str] = []
    up = {"docker": docker_at_start, "probes": 0}

    def docker_available():
        up["probes"] += 1
        return up["docker"]

    async def check_fence(startup=False):
        events.append("fence" if startup else "fence-recheck")

    def sweep(min_age=0.0):
        events.append("sweep")
        SWEEP_MIN_AGES.append(min_age)
        return []

    async def detect():
        events.append("egress")
        return "81.61.1.9"

    async def until(done):
        # Waits on what happened, not on a clock, so a loaded runner cannot cut a phase short.
        for _ in range(1000):
            if done():
                return
            await asyncio.sleep(0.005)
        raise AssertionError(f"timed out; ran so far: {events}")

    def guard_passes(at_least):
        return lambda: events.count("guard") >= at_least

    async def run():
        async with worker_api.lifespan(worker_api.app):
            await until(guard_passes(3) if docker_at_start else lambda: up["probes"] >= 5)
            events.append("--docker-up--")
            up["docker"] = docker_later or docker_at_start
            if docker_at_start:
                await until(guard_passes(events.count("guard") + 2))
            elif docker_later:
                await until(guard_passes(4))
            else:
                probes = up["probes"]
                await until(lambda: up["probes"] >= probes + 3)
        events.append("--stopped--")
        return worker_api._guard_task

    patches = [
        patch.object(worker_api.orchestrator, "docker_available", side_effect=docker_available),
        patch.object(worker_api.orchestrator, "hold_direct_earners", side_effect=lambda: events.append("hold")),
        patch.object(worker_api.orchestrator, "proxy_policy_fix", return_value=None),
        patch.object(worker_api, "_detect_egress_ip", side_effect=detect),
        patch.object(worker_api.lan_fence, "set_egress_ip", side_effect=lambda ip: events.append("set-egress")),
        patch.object(worker_api, "_check_fence", side_effect=check_fence),
        patch.object(worker_api, "_fence_loop", AsyncMock()),
        patch.object(worker_api.lan_fence, "guard", side_effect=lambda: events.append("guard") or {}),
        patch.object(worker_api.proxy_tunnel, "recover_moves", side_effect=lambda: events.append("recover") or []),
        patch.object(worker_api.proxy_tunnel, "sweep_test_tunnels", side_effect=sweep),
        patch.object(worker_api, "UI_URL", ""),
    ]
    if wait_loop is not None:
        patches.append(patch.object(worker_api, "_wait_for_docker_loop", wait_loop))
    for p in patches:
        p.start()
    try:
        guard_task = asyncio.run(run())
    finally:
        for p in reversed(patches):
            p.stop()
    return events, up["probes"], guard_task


def _after(events, marker):
    return events[events.index(marker) + 1 :]


class TestDockerComesBackAfterStart:
    def test_the_start_steps_run_once_in_order_then_the_guard_loop_carries_on(self, monkeypatch, caplog):
        caplog.set_level(logging.INFO, logger=worker_api.logger.name)
        events, _, guard_task = _run(docker_at_start=False, docker_later=True, monkeypatch=monkeypatch)
        # Before Docker answers: the startup fence check (it records "n/a") and nothing else.
        assert events[: events.index("--docker-up--")] == ["fence"]
        later = _after(events, "--docker-up--")
        later = later[: later.index("--stopped--")]
        # Hold first, the public IP, the fence before the guard pass that may
        # start a fence-gated node, then the proxied-copy steps: the direct start's order.
        assert later[: len(ONE_TIME)] == ONE_TIME
        for once in ("egress", "set-egress", "fence", "recover", "sweep"):
            assert later.count(once) == 1, (once, later)
        # Then the guard loop: more passes, each with the proxied-only hold.
        rest = later[len(ONE_TIME) :]
        assert rest.count("guard") >= 2
        assert rest[:4] == ["guard", "hold", "guard", "hold"]
        assert sum(COME_BACK_LOG in r.getMessage() for r in caplog.records) == 1
        # The API served all along, so a proxy test can be in flight: the sweep
        # keeps every Test tunnel younger than this process.
        (min_age,) = SWEEP_MIN_AGES
        assert min_age > 0
        # Shutdown cancels it like every other loop.
        assert guard_task is not None and guard_task.cancelled()

    def test_until_docker_answers_it_only_keeps_asking(self, monkeypatch, caplog):
        caplog.set_level(logging.INFO, logger=worker_api.logger.name)
        events, probes, guard_task = _run(docker_at_start=False, docker_later=False, monkeypatch=monkeypatch)
        assert events == ["fence", "--docker-up--", "--stopped--"]
        assert probes >= 5
        assert not any(COME_BACK_LOG in r.getMessage() for r in caplog.records)
        assert guard_task is not None and guard_task.cancelled()


class TestAProxiedOnlyWorkerStartedWithoutDocker:
    def test_it_holds_at_start_waits_and_holds_first_once_docker_answers(self, monkeypatch):
        events, probes, _ = _run(docker_at_start=False, docker_later=True, proxied_only=True, monkeypatch=monkeypatch)
        # The hold at start (Docker can come up any second and restart a direct earner).
        assert events[: events.index("--docker-up--")] == ["fence", "hold"]
        assert probes >= 5
        later = _after(events, "--docker-up--")
        assert later[: len(ONE_TIME)] == ONE_TIME
        # Every guard pass after that holds again (the stop can land between the two halves of the last one).
        rest = [e for e in later[len(ONE_TIME) :] if e != "--stopped--"]
        assert rest.count("guard") >= 2
        assert rest[: 2 * (rest.count("guard") - 1)] == ["guard", "hold"] * (rest.count("guard") - 1)

    def test_without_docker_it_does_not_try_and_log_forever(self, monkeypatch):
        events, _, _ = _run(docker_at_start=False, docker_later=False, proxied_only=True, monkeypatch=monkeypatch)
        assert events == ["fence", "hold", "--docker-up--", "--stopped--"]


class TestDockerAtStart:
    @pytest.mark.parametrize("proxied_only", [False, True])
    def test_unchanged_the_steps_run_at_start_and_the_late_loop_never_starts(self, monkeypatch, caplog, proxied_only):
        caplog.set_level(logging.INFO, logger=worker_api.logger.name)

        async def never():
            raise AssertionError("the wait-for-Docker loop started on a worker that had Docker")

        events, _, guard_task = _run(
            docker_at_start=True,
            docker_later=True,
            proxied_only=proxied_only,
            monkeypatch=monkeypatch,
            wait_loop=never,
        )
        before = events[: events.index("--docker-up--")]
        head = ONE_TIME[: ONE_TIME.index("recover")]
        assert before[: len(head)] == head
        for once in ("egress", "set-egress", "fence", "recover", "sweep"):
            assert events.count(once) == 1, (once, events)
        # The guard loop starts before the proxied-copy steps, and GUARD_SECONDS is
        # 10 ms here, so a periodic pass may land before recover: only their order counts.
        assert [e for e in events if e in ("recover", "sweep")] == ["recover", "sweep"]
        after_sweep = [e for e in _after(events, "sweep") if e not in ("--docker-up--", "--stopped--")]
        assert after_sweep[:2] == ["guard", "hold"]
        # Nothing can be in flight before the API serves: every leftover goes.
        assert SWEEP_MIN_AGES == [0.0]
        assert not any(COME_BACK_LOG in r.getMessage() for r in caplog.records)
        assert guard_task is not None and guard_task.cancelled()
