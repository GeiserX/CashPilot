"""The health check must never start in the same second as another scheduled job.

Every job's interval counted from the same start, so on the hour the health
check started beside the collection, the activity, cap-reset, stale-worker and
device-link jobs. Its write then found the database locked about one run in
twelve, and that run recorded no health events and sent no alerts.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from app import main
from tests.test_rates_do_not_hold_startup import _lifespan_patches


def _fire_times(job, until):
    times = []
    nxt = job.trigger.get_next_fire_time(None, job.next_run_time)
    while nxt is not None and nxt <= until:
        times.append(nxt)
        nxt = job.trigger.get_next_fire_time(nxt, nxt)
    return times


def test_the_health_check_never_starts_beside_another_job():
    async def noop():
        return None

    async def run():
        patches = _lifespan_patches(noop, noop)
        for p in patches:
            p.start()
        try:
            async with main.lifespan(main.app):
                jobs = {j.id: j for j in main.scheduler.get_jobs()}
                health = jobs.pop("health_check")
                until = health.next_run_time + timedelta(days=2)
                checks = _fire_times(health, until)
                assert len(checks) > 500
                for job in jobs.values():
                    for other in _fire_times(job, until):
                        nearest = min(abs((other - c).total_seconds()) for c in checks)
                        assert nearest >= 20, f"health_check starts {nearest:.0f} s from {job.id} at {other}"
        finally:
            for p in reversed(patches):
                p.stop()

    asyncio.run(run())
