"""Resource use per server and container: hourly lines from worker heartbeats.

Docker's network counters are cumulative since the container started, so the
traffic is the difference between two heartbeats. These tests pin the cases
where a naive difference lies: the first sight of a container, a restart that
reset the counters, a baseline left over from a long outage, and a
host-network container that has no counters at all. And the graph rule: an
hour with no reading is a gap (None), never a zero.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

from app import database, usage

MB = 1024 * 1024
GB = 1024 * MB


def container(slug="honeygain", cid="abc123", rx=0, tx=0, cpu=1.0, mem=50.0, status="running", name=None):
    return {
        "slug": slug,
        "name": name or f"cashpilot-{slug}-{cid}",
        "container_id": cid,
        "status": status,
        "cpu_percent": cpu,
        "memory_mb": mem,
        "net_rx_bytes": rx,
        "net_tx_bytes": tx,
    }


class TestCounterDelta:
    def test_first_sight_counts_nothing(self):
        assert usage.counter_delta(None, 5000, None) == 0

    def test_growth_is_the_difference(self):
        assert usage.counter_delta(1000, 5000, 60) == 4000

    def test_restart_counts_the_new_reading(self):
        # Counters went back to zero on restart and have since reached 300.
        assert usage.counter_delta(10_000, 300, 60) == 300

    def test_stale_baseline_counts_nothing(self):
        assert usage.counter_delta(1000, 9_000_000, usage.MAX_BASELINE_AGE_SECONDS + 1) == 0

    def test_no_counter_is_unknown_not_zero(self):
        assert usage.counter_delta(1000, None, 60) is None


class TestSamplesFromHeartbeat:
    def test_one_sample_per_container_by_name(self):
        out = usage.samples_from_heartbeat(
            [container(cid="a", rx=100, tx=10, name="hg-1"), container(cid="b", rx=200, tx=20, name="hg-2")],
            {"a": (50, 5, 940.0), "b": (100, 10, 940.0)},
            now=1000.0,
        )
        assert set(out) == {"hg-1", "hg-2"}
        assert (out["hg-1"].rx_bytes, out["hg-1"].tx_bytes, out["hg-1"].net_seconds) == (50, 5, 60.0)
        assert (out["hg-2"].rx_bytes, out["hg-2"].tx_bytes) == (100, 10)

    def test_first_sight_is_a_baseline_not_zero_traffic(self):
        s = usage.samples_from_heartbeat([container(rx=5 * GB)], {}, now=1000.0)["cashpilot-honeygain-abc123"]
        assert s.rx_bytes is None and s.net_seconds is None
        assert s.counters == (5 * GB, 0)

    def test_restart_counts_the_new_reading(self):
        s = usage.samples_from_heartbeat([container(rx=300, tx=3)], {"abc123": (10_000, 100, 940.0)}, now=1000.0)
        assert (s := s["cashpilot-honeygain-abc123"]).rx_bytes == 300 and s.tx_bytes == 3

    def test_stale_baseline_loses_the_traffic(self):
        out = usage.samples_from_heartbeat([container(rx=9 * GB)], {"abc123": (0, 0, 0.0)}, now=10_000.0)
        s = out["cashpilot-honeygain-abc123"]
        assert s.traffic_lost and s.rx_bytes is None and s.net_seconds is None

    def test_host_network_container_has_no_counters(self):
        c = container(slug="mysterium", rx=None, tx=None)
        s = usage.samples_from_heartbeat([c], {}, now=1000.0)["cashpilot-mysterium-abc123"]
        assert s.no_counters and s.rx_bytes is None and s.counters is None
        assert s.cpu_percent == 1.0

    def test_stopped_container_is_skipped(self):
        assert usage.samples_from_heartbeat([container(status="exited")], {}, now=1000.0) == {}

    def test_infinite_readings_are_rejected(self):
        s = usage.samples_from_heartbeat([container(cpu=float("inf"), mem=float("nan"))], {}, now=1000.0)
        s = s["cashpilot-honeygain-abc123"]
        assert s.cpu_percent is None and s.memory_mb is None

    def test_failed_stats_are_unknown_not_zero(self):
        s = usage.samples_from_heartbeat([container(cpu=None, mem=None)], {}, now=1000.0)
        s = s["cashpilot-honeygain-abc123"]
        assert s.cpu_percent is None and s.memory_mb is None


def run_db(tmp_path, coro_factory):
    async def go():
        with (
            patch.object(database, "DB_DIR", tmp_path),
            patch.object(database, "DB_PATH", tmp_path / "usage.db"),
        ):
            await database.init_db()
            return await coro_factory()

    return asyncio.run(go())


async def hourly_rows():
    db = await database._get_db()
    cursor = await db.execute("SELECT * FROM usage_hourly ORDER BY container, hour")
    return [dict(r) for r in await cursor.fetchall()]


HOUR = 1_800_000_000 // 3600 * 3600


class TestRecordUsage:
    def test_restart_between_heartbeats_is_counted(self, tmp_path):
        async def go():
            await database.record_usage(1, [container(rx=1 * GB, tx=MB)], now=HOUR + 10)
            await database.record_usage(1, [container(rx=2 * GB, tx=2 * MB)], now=HOUR + 70)
            # Restarted: counters reset and climbed back to 100 MB / 1 MB.
            await database.record_usage(1, [container(rx=100 * MB, tx=MB)], now=HOUR + 130)
            return await hourly_rows()

        rows = run_db(tmp_path, go)
        assert len(rows) == 1
        row = rows[0]
        # 1 GB growth, then 100 MB after the restart. The first sight is a baseline.
        assert row["rx_bytes"] == GB + 100 * MB
        assert row["tx_bytes"] == MB + MB
        assert row["net_seconds"] == 120.0
        assert row["cpu_n"] == 3 and row["mem_n"] == 3
        assert row["hour"] == HOUR and row["slug"] == "honeygain"

    def test_each_hour_is_its_own_row(self, tmp_path):
        async def go():
            await database.record_usage(1, [container(rx=0)], now=HOUR + 3570)
            await database.record_usage(1, [container(rx=MB)], now=HOUR + 3630)
            return await hourly_rows()

        rows = run_db(tmp_path, go)
        assert [(r["hour"], r["rx_bytes"]) for r in rows] == [(HOUR, None), (HOUR + 3600, MB)]

    def test_a_redeployed_container_keeps_its_line(self, tmp_path):
        """Same name, new id: one line carries on, the new id starts a fresh baseline."""

        async def go():
            await database.record_usage(1, [container(cid="old", rx=0, name="hg")], now=HOUR + 10)
            await database.record_usage(1, [container(cid="old", rx=MB, name="hg")], now=HOUR + 70)
            await database.record_usage(1, [container(cid="new", rx=5 * GB, name="hg")], now=HOUR + 130)
            return await hourly_rows()

        rows = run_db(tmp_path, go)
        assert len(rows) == 1 and rows[0]["rx_bytes"] == MB and rows[0]["cpu_n"] == 3

    def test_host_network_stays_null_in_the_table(self, tmp_path):
        async def go():
            c = container(slug="mysterium", rx=None, tx=None)
            await database.record_usage(1, [c], now=HOUR + 10)
            await database.record_usage(1, [c], now=HOUR + 70)
            return await hourly_rows()

        rows = run_db(tmp_path, go)
        assert [(r["rx_bytes"], r["tx_bytes"], r["no_counters"]) for r in rows] == [(None, None, 2)]

    def test_a_failure_halfway_saves_nothing(self, tmp_path):
        """Hour rows and baselines are one transaction: half of it would double count."""

        async def go():
            await database.record_usage(1, [container(rx=GB, tx=0)], now=HOUR + 10)
            real = usage.samples_from_heartbeat

            def boom(*a, **kw):
                out = real(*a, **kw)
                # The hour row goes in, then the baseline write fails (NOT NULL).
                out["cashpilot-honeygain-abc123"].counters = (0, None)
                return out

            with patch.object(usage, "samples_from_heartbeat", boom), contextlib.suppress(Exception):
                await database.record_usage(1, [container(rx=2 * GB, tx=0)], now=HOUR + 70)
            # A clean heartbeat afterwards must still measure from the first baseline once.
            await database.record_usage(1, [container(rx=2 * GB, tx=0)], now=HOUR + 130)
            return await hourly_rows()

        rows = run_db(tmp_path, go)
        assert rows[0]["rx_bytes"] == GB and rows[0]["cpu_n"] == 2

    def test_retention_trims_old_hours_and_baselines(self, tmp_path):
        async def go():
            db = await database._get_db()
            now = int(time.time())
            await db.execute(
                "INSERT INTO usage_hourly (worker_id, container, hour, slug) VALUES (1, 'x', ?, 'x'), (1, 'x', ?, 'x')",
                (now - 40 * 86400, now - 3600),
            )
            await db.execute(
                "INSERT INTO usage_counters (worker_id, container_id, rx_bytes, tx_bytes, seen_at) "
                "VALUES (1, 'old', 0, 0, 0)"
            )
            await db.commit()
            await database.purge_old_data()
            hours = await (await db.execute("SELECT COUNT(*) FROM usage_hourly")).fetchone()
            counters = await (await db.execute("SELECT COUNT(*) FROM usage_counters")).fetchone()
            return hours[0], counters[0]

        assert run_db(tmp_path, go) == (1, 0)

    def test_the_old_daily_table_is_dropped(self, tmp_path):
        async def go():
            db = await database._get_db()
            await db.execute("CREATE TABLE IF NOT EXISTS usage_daily (worker_id INTEGER)")
            await db.commit()
            await database.init_db()
            row = await (await db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'usage_daily'")).fetchone()
            return row[0]

        assert run_db(tmp_path, go) == 0


class TestEarnedByPlatform:
    def test_get_earned_by_platform_reports_what_it_measured(self, tmp_path):
        from tests.test_dashboard_currency import day

        async def go():
            await database.upsert_earnings("honeygain", 1.0, currency="USD", date=day(2))
            await database.upsert_earnings("honeygain", 1.5, currency="USD", date=day(1))
            await database.upsert_earnings("earnapp", 3.0, currency="USD", date=day(1))
            measured: set[str] = set()
            earned = await database.get_earned_by_platform(days=30, measured=measured)
            return earned, measured

        earned, measured = run_db(tmp_path, go)
        assert measured == {"honeygain"}
        assert earned["earnapp"] == 0.0  # the single reading the endpoint must not show


WORKERS = [
    {"id": 1, "name": "watchtower", "status": "online"},
    {"id": 2, "name": "geiserback", "status": "online"},
    {"id": 3, "name": "pixel", "status": "online", "system_info": '{"os": "Android"}'},
]


def call_usage(tmp_path, record, **params):
    """Record some heartbeats, then call /api/usage as the dashboard does."""
    from app import main

    async def go():
        await record()
        with (
            patch.object(main, "_require_auth_api", lambda r: None),
            patch.object(main.database, "list_workers", AsyncMock(return_value=WORKERS)),
        ):
            return await main.api_usage(MagicMock(), **params)

    return run_db(tmp_path, go)


# The last full hour before the one the test runs in, and the one before it.
def last_hour():
    return int(time.time() // 3600) * 3600 - 3600


async def two_servers():
    h = last_hour()
    for wid in (1, 2):
        for t, rx in ((h + 10, 0), (h + 70, 60 * MB)):
            await database.record_usage(
                wid,
                [
                    container(cid="a", rx=rx, tx=rx // 10, cpu=10.0, mem=512, name="hg"),
                    container(slug="earnapp", cid="b", rx=rx * 2, tx=0, cpu=5.0, mem=100, name="ea"),
                    container(slug="mysterium", cid="m", rx=None, tx=None, cpu=20.0, mem=200, name="myst"),
                ],
                now=t,
            )
    # A phone's rows, recorded before #510 kept phones out.
    await database.record_usage(3, [container(cid="p", name="phone-hg")], now=h + 10)


class TestUsageEndpoint:
    def test_server_total_adds_up_every_container_per_hour(self, tmp_path):
        data = call_usage(tmp_path, two_servers, days=7)
        assert len(data["hours"]) == 7 * 24
        assert data["hours"][-2] == last_hour()
        # Sorted by name; the phone is not a server.
        assert [s["name"] for s in data["servers"]] == ["geiserback", "watchtower"]
        assert data["worker_id"] == 2 and data["container"] is None
        s = data["series"]
        assert s["cpu_percent"][-2] == 35.0
        assert s["memory_mb"][-2] == 812.0
        # 60 MB + 120 MB over the 60 s between the two readings.
        assert s["rx_rate"][-2] == round(180 * MB / 60, 2)
        assert s["rx_bytes"][-2] == 180 * MB
        # Mysterium is on the host network: the total is a floor, and says so.
        assert s["traffic_partial"][-2] is True
        myst = next(c for c in data["servers"][0]["containers"] if c["name"] == "myst")
        assert myst["no_counters"] is True and myst["slug"] == "mysterium"

    def test_an_hour_with_no_reading_is_a_gap_not_zero(self, tmp_path):
        data = call_usage(tmp_path, two_servers, days=7)
        s = data["series"]
        for key in ("cpu_percent", "memory_mb", "rx_rate", "tx_rate"):
            assert s[key][0] is None, key
            assert s[key][-3] is None, key
            assert 0 not in s[key][:-2], key

    def test_drill_down_to_one_container(self, tmp_path):
        data = call_usage(tmp_path, two_servers, days=7, worker_id=1, container="ea")
        assert data["worker_id"] == 1 and data["container"] == "ea"
        s = data["series"]
        assert s["cpu_percent"][-2] == 5.0 and s["memory_mb"][-2] == 100.0
        assert s["rx_rate"][-2] == round(120 * MB / 60, 2) and s["tx_rate"][-2] == 0.0
        assert s["traffic_partial"][-2] is False

    def test_host_network_container_has_an_empty_network_line(self, tmp_path):
        data = call_usage(tmp_path, two_servers, days=7, worker_id=1, container="myst")
        s = data["series"]
        assert s["cpu_percent"][-2] == 20.0
        assert s["rx_rate"][-2] is None and s["tx_rate"][-2] is None
        assert s["traffic_partial"][-2] is True

    def test_unknown_picks_fall_back(self, tmp_path):
        data = call_usage(tmp_path, two_servers, days=99, worker_id=3, container="nope")
        # A phone is never a server to pick; a container it does not have is "all".
        assert data["worker_id"] == 2 and data["container"] is None
        assert data["days"] == 30 and len(data["hours"]) == 30 * 4 and data["step"] == 6 * 3600

    def test_thirty_days_draws_six_hour_points_from_the_hourly_rows(self, tmp_path):
        """Two hours in one 6-hour point: CPU averages, traffic adds over the seconds measured."""
        step = 6 * 3600
        point = int(time.time() // step) * step - step

        async def record():
            for t, rx, cpu in ((point + 10, 0, 10.0), (point + 70, 60 * MB, 10.0), (point + 3610, 60 * MB, 30.0)):
                await database.record_usage(1, [container(rx=rx, cpu=cpu, name="hg")], now=t)
            await database.record_usage(1, [container(rx=120 * MB, cpu=30.0, name="hg")], now=point + 3670)

        data = call_usage(tmp_path, record, days=30, worker_id=1)
        assert data["hours"][-2] == point
        s = data["series"]
        assert s["cpu_percent"][-2] == 20.0
        assert s["rx_bytes"][-2] == 120 * MB
        # 60 s + 3540 s + 60 s between the four readings, all under the 1-hour limit.
        assert s["rx_rate"][-2] == round(120 * MB / 3660, 2)
        assert s["cpu_percent"][-3] is None

    def test_no_rows_is_an_empty_panel(self, tmp_path):
        async def nothing():
            return None

        data = call_usage(tmp_path, nothing, days=7)
        assert all(not s["containers"] for s in data["servers"])
        assert set(data["series"]["cpu_percent"]) == {None}


class TestHeartbeatRecordsUsage:
    def _beat(self, record):
        from app import main

        body = main.WorkerHeartbeat(name="w", client_id="cid", containers=[container()])
        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(main.database, "get_worker_status_and_name", AsyncMock(return_value=None)),
            patch.object(main.database, "upsert_worker", AsyncMock(return_value=7)),
            patch.object(main.database, "confirm_worker_key", AsyncMock()),
            patch.object(main.database, "record_usage", record),
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
        ):
            return asyncio.run(main.api_worker_heartbeat(MagicMock(), body))

    def test_heartbeat_records_usage(self):
        record = AsyncMock()
        assert self._beat(record)["status"] == "ok"
        record.assert_awaited_once()
        assert record.await_args.args[0] == 7

    def test_a_phone_records_nothing(self):
        # The Android client sends os="Android" and no device_type.
        from app import main

        record = AsyncMock()
        body = main.WorkerHeartbeat(name="p", client_id="cid", containers=[container()], system_info={"os": "Android"})
        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(main.database, "get_worker_status_and_name", AsyncMock(return_value=None)),
            patch.object(main.database, "upsert_worker", AsyncMock(return_value=7)),
            patch.object(main.database, "confirm_worker_key", AsyncMock()),
            patch.object(main.database, "record_usage", record),
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
        ):
            asyncio.run(main.api_worker_heartbeat(MagicMock(), body))
        record.assert_not_awaited()

    def test_a_usage_failure_never_rejects_the_heartbeat(self):
        assert self._beat(AsyncMock(side_effect=RuntimeError("disk full")))["status"] == "ok"
