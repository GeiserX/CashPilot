"""Resource use per server: CPU, memory and traffic from worker heartbeats.

Docker's network counters are cumulative since the container started, so the
traffic is the difference between two heartbeats. These tests pin the cases
where a naive difference lies: the first sight of a container, a restart that
reset the counters, a baseline left over from a long outage, and a
host-network container that has no counters at all.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app import database, usage

MB = 1024 * 1024
GB = 1024 * MB


def container(slug="honeygain", cid="abc123", rx=0, tx=0, cpu=1.0, mem=50.0, status="running"):
    return {
        "slug": slug,
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
    def test_instances_of_one_service_add_up(self):
        out = usage.samples_from_heartbeat(
            [container(cid="a", rx=100, tx=10), container(cid="b", rx=200, tx=20)],
            {"a": (50, 5, 940.0), "b": (100, 10, 940.0)},
            now=1000.0,
        )
        s = out["honeygain"]
        assert (s.rx_bytes, s.tx_bytes) == (150, 15)
        assert s.cpu_percent == 2.0
        assert s.memory_mb == 100.0

    def test_host_network_container_has_unknown_traffic(self):
        c = container(slug="mysterium")
        c["net_rx_bytes"] = c["net_tx_bytes"] = None
        s = usage.samples_from_heartbeat([c], {}, now=1000.0)["mysterium"]
        assert s.rx_bytes is None and s.tx_bytes is None
        assert s.cpu_percent == 1.0  # CPU and memory are still measured
        assert s.counters == []

    def test_stopped_container_is_skipped(self):
        assert usage.samples_from_heartbeat([container(status="exited")], {}, now=1000.0) == {}

    def test_container_without_counters_marks_a_gap(self):
        bridge = container(cid="a", rx=100, tx=10)
        host = container(cid="b")
        host["net_rx_bytes"] = host["net_tx_bytes"] = None
        s = usage.samples_from_heartbeat([bridge, host], {"a": (50, 5, 940.0)}, now=1000.0)["honeygain"]
        assert s.traffic_gap is True
        assert (s.rx_bytes, s.tx_bytes) == (50, 5)

    def test_stale_baseline_marks_a_gap(self):
        s = usage.samples_from_heartbeat(
            [container(cid="a", rx=500, tx=50)], {"a": (100, 10, 0.0)}, now=usage.MAX_BASELINE_AGE_SECONDS + 1
        )["honeygain"]
        assert s.traffic_gap is True and s.rx_bytes == 0

    def test_unreadable_memory_marks_a_gap(self):
        out = usage.samples_from_heartbeat([container(cid="a"), container(cid="b", mem=None)], {}, now=1000.0)
        assert out["honeygain"].memory_gap is True

    def test_infinite_readings_are_rejected(self):
        s = usage.samples_from_heartbeat([container(cpu="Infinity", mem=float("nan"))], {}, now=1000.0)["honeygain"]
        assert s.cpu_percent is None and s.memory_mb is None

    def test_failed_stats_are_unknown_not_zero(self):
        s = usage.samples_from_heartbeat([container(cpu=None, mem=None)], {}, now=1000.0)["honeygain"]
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


class TestRecordUsage:
    def test_restart_between_heartbeats_is_counted(self, tmp_path):
        async def go():
            now = 1_800_000_000.0
            await database.record_usage(1, [container(rx=1 * GB, tx=MB)], now=now)
            await database.record_usage(1, [container(rx=2 * GB, tx=2 * MB)], now=now + 60)
            # Restarted: counters reset and climbed back to 100 MB / 1 MB.
            await database.record_usage(1, [container(rx=100 * MB, tx=MB)], now=now + 120)
            db = await database._get_db()
            cursor = await db.execute("SELECT * FROM usage_daily")
            return [dict(r) for r in await cursor.fetchall()]

        rows = run_db(tmp_path, go)
        assert len(rows) == 1
        row = rows[0]
        # 1 GB growth, then 100 MB after the restart. The first sight is a baseline.
        assert row["rx_bytes"] == GB + 100 * MB
        assert row["tx_bytes"] == MB + MB
        assert row["cpu_n"] == 3 and row["mem_n"] == 3

    def test_host_network_stays_null_in_the_table(self, tmp_path):
        async def go():
            c = container(slug="mysterium")
            c["net_rx_bytes"] = c["net_tx_bytes"] = None
            await database.record_usage(1, [c], now=1_800_000_000.0)
            await database.record_usage(1, [c], now=1_800_000_060.0)
            db = await database._get_db()
            cursor = await db.execute("SELECT rx_bytes, tx_bytes FROM usage_daily")
            return [tuple(r) for r in await cursor.fetchall()]

        assert run_db(tmp_path, go) == [(None, None)]

    def test_a_failure_halfway_saves_nothing(self, tmp_path):
        """Day rows and baselines are one transaction: half of it would double count."""

        async def go():
            now = 1_800_000_000.0
            await database.record_usage(1, [container(rx=GB, tx=0)], now=now)
            real = usage.samples_from_heartbeat

            def boom(*a, **kw):
                out = real(*a, **kw)
                # The day row goes in, then the baseline write fails (NOT NULL),
                # so the real baseline after it is never stored.
                out["honeygain"].counters.insert(0, ("x", 0, None))
                return out

            with patch.object(usage, "samples_from_heartbeat", boom), contextlib.suppress(Exception):
                await database.record_usage(1, [container(rx=2 * GB, tx=0)], now=now + 60)
            # A clean heartbeat afterwards must still measure from the first baseline once.
            await database.record_usage(1, [container(rx=2 * GB, tx=0)], now=now + 120)
            db = await database._get_db()
            row = await (await db.execute("SELECT rx_bytes FROM usage_daily WHERE slug = 'honeygain'")).fetchone()
            return row[0]

        assert run_db(tmp_path, go) == GB

    def test_retention_trims_old_days_and_baselines(self, tmp_path):
        async def go():
            db = await database._get_db()
            await db.execute(
                "INSERT INTO usage_daily (worker_id, slug, day) VALUES (1, 'x', date('now', '-40 days')), "
                "(1, 'x', date('now'))"
            )
            await db.execute(
                "INSERT INTO usage_counters (worker_id, container_id, rx_bytes, tx_bytes, seen_at) "
                "VALUES (1, 'old', 0, 0, 0)"
            )
            await db.commit()
            await database.purge_old_data()
            days = await (await db.execute("SELECT COUNT(*) FROM usage_daily")).fetchone()
            counters = await (await db.execute("SELECT COUNT(*) FROM usage_counters")).fetchone()
            return days[0], counters[0]

        assert run_db(tmp_path, go) == (1, 0)


def earned_stub(values, priced=None):
    """get_earned_by_platform: returns ``values``; ``priced`` (default: all) are reported as measured."""

    async def stub(days=30, measured=None):
        if measured is not None:
            measured.update(values if priced is None else priced)
        return dict(values)

    return stub


def usage_rows(*rows, running=(), extra_workers=()):
    """api_usage_servers over hand-written usage_daily rows (no DB).

    ``running`` lists ``(worker_id, slug)`` copies the workers report right now.
    """
    from app import main

    workers = [
        {"id": 1, "name": "watchtower", "status": "online"},
        {"id": 2, "name": "geiserback", "status": "online"},
        *extra_workers,
    ]
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    base = {
        "day": today,
        "cpu_sum": 1.0,
        "cpu_n": 1,
        "mem_sum": 512.0,
        "mem_n": 1,
        "rx_bytes": GB,
        "tx_bytes": 0,
        "net_gaps": 0,
        "mem_gaps": 0,
    }
    full = [{**base, **r} for r in rows]

    def run(values, priced=None):
        async def go():
            with (
                patch.object(main, "_require_auth_api", lambda r: None),
                patch.object(main.database, "get_usage_daily", AsyncMock(return_value=full)),
                patch.object(main.database, "list_workers", AsyncMock(return_value=workers)),
                patch.object(main.database, "get_earned_by_platform", earned_stub(values, priced)),
                patch.object(
                    main,
                    "_get_all_worker_containers",
                    AsyncMock(return_value=[{"slug": s, "status": "running", "_worker_id": w} for w, s in running]),
                ),
            ):
                return await main.api_usage_servers(MagicMock())

        return asyncio.run(go())

    return run


def service(data, worker, slug):
    server = next(s for s in data["servers"] if s["name"] == worker)
    return next(s for s in server["services"] if s["slug"] == slug)


class TestRatiosNeedEveryCopyMeasured:
    def test_one_host_network_copy_makes_per_gb_unknown(self):
        # Same account earns on both boxes; geiserback's copy has no counters.
        data = usage_rows(
            {"worker_id": 1, "slug": "mysterium"},
            {"worker_id": 2, "slug": "mysterium", "rx_bytes": None, "tx_bytes": None},
        )({"mysterium": 5.0})
        assert service(data, "watchtower", "mysterium")["usd_per_gb"] is None

    def test_a_partly_measured_day_makes_per_gb_unknown(self):
        data = usage_rows({"worker_id": 1, "slug": "honeygain", "net_gaps": 3})({"honeygain": 1.0})
        assert service(data, "watchtower", "honeygain")["usd_per_gb"] is None
        assert service(data, "watchtower", "honeygain")["rx"] == GB  # the measured part is still shown

    def test_fully_measured_service_gets_a_ratio(self):
        data = usage_rows({"worker_id": 1, "slug": "honeygain"})({"honeygain": 1.0})
        assert abs(service(data, "watchtower", "honeygain")["usd_per_gb"] - 1.0) < 1e-9

    def test_unmeasured_memory_makes_per_gb_ram_unknown(self):
        data = usage_rows(
            {"worker_id": 1, "slug": "honeygain"},
            {"worker_id": 2, "slug": "honeygain", "mem_n": 0, "mem_sum": 0.0},
        )({"honeygain": 1.0})
        assert service(data, "watchtower", "honeygain")["usd_per_gb_ram"] is None

    def test_a_running_copy_with_no_usage_row_makes_ratios_unknown(self):
        # geiserback runs honeygain right now but never reported usage for it.
        data = usage_rows({"worker_id": 1, "slug": "honeygain"}, running=[(1, "honeygain"), (2, "honeygain")])(
            {"honeygain": 1.0}
        )
        svc = service(data, "watchtower", "honeygain")
        assert svc["usd_per_gb"] is None and svc["usd_per_gb_ram"] is None

    def test_partly_read_memory_makes_per_gb_ram_unknown(self):
        data = usage_rows({"worker_id": 1, "slug": "honeygain", "mem_gaps": 2})({"honeygain": 1.0})
        assert service(data, "watchtower", "honeygain")["usd_per_gb_ram"] is None

    def test_a_server_total_without_every_service_is_marked_partial(self):
        data = usage_rows(
            {"worker_id": 1, "slug": "honeygain"},
            {"worker_id": 1, "slug": "mysterium", "rx_bytes": None, "tx_bytes": None},
            {"worker_id": 2, "slug": "honeygain"},
        )({"honeygain": 1.0})
        totals = {s["name"]: s["total"] for s in data["servers"]}
        assert totals["watchtower"]["traffic_partial"] is True
        assert totals["geiserback"]["traffic_partial"] is False

    def test_rows_from_a_phone_are_left_out(self):
        # Rows 1.54.0 recorded for phones, before they were skipped, must not show.
        phone = {"id": 3, "name": "OPPO", "status": "online", "system_info": '{"os": "Android"}'}
        data = usage_rows(
            {"worker_id": 1, "slug": "honeygain"},
            {"worker_id": 3, "slug": "traffmonetizer", "cpu_n": 0, "mem_n": 0, "rx_bytes": None, "tx_bytes": None},
            extra_workers=[phone],
        )({"honeygain": 1.0})
        assert [s["name"] for s in data["servers"]] == ["watchtower"]

    def test_a_phone_running_the_service_makes_ratios_unknown_even_offline(self):
        phone = {
            "id": 3,
            "name": "OPPO",
            "status": "offline",
            "system_info": '{"os": "Android"}',
            "containers": '[{"slug": "honeygain", "status": "running"}]',
        }
        data = usage_rows({"worker_id": 1, "slug": "honeygain"}, extra_workers=[phone])({"honeygain": 1.0})
        svc = service(data, "watchtower", "honeygain")
        assert svc["usd_per_gb"] is None and svc["usd_per_gb_ram"] is None
        assert svc["earned_usd"] == 1.0

    def test_a_deleted_workers_rows_do_not_stretch_the_window(self):
        old = (datetime.now(UTC) - timedelta(days=20)).strftime("%Y-%m-%d")
        data = usage_rows({"worker_id": 1, "slug": "honeygain"}, {"worker_id": 99, "slug": "honeygain", "day": old})(
            {"honeygain": 1.0}
        )
        assert data["window_days"] == 1


class TestUnmeasuredEarningsAreUnknown:
    def test_platform_with_no_priced_delta_is_a_dash_not_zero(self):
        # get_earned_by_platform reports 0.0 for a platform it could not price
        # or has only one reading for; that is not "earned nothing".
        data = usage_rows({"worker_id": 1, "slug": "mysterium"})({"mysterium": 0.0}, priced=set())
        svc = service(data, "watchtower", "mysterium")
        assert svc["earned_usd"] is None and svc["usd_per_gb"] is None and svc["usd_per_gb_ram"] is None

    def test_measured_zero_stays_zero(self):
        data = usage_rows({"worker_id": 1, "slug": "honeygain"})({"honeygain": 0.0})
        assert service(data, "watchtower", "honeygain")["earned_usd"] == 0.0

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


class TestUsageEndpoint:
    def test_per_server_rows_totals_and_ratios(self, tmp_path):
        from app import main

        workers = [
            {"id": 1, "name": "watchtower", "status": "online"},
            {"id": 2, "name": "geiserback", "status": "online"},
        ]

        async def go():
            # Noon UTC, so the two samples a minute apart never straddle midnight.
            now = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0).timestamp()
            for wid in (1, 2):
                await database.record_usage(
                    wid,
                    [container(rx=0, tx=0, mem=512), container(slug="mysterium", cid="m", rx=None, tx=None)],
                    now=now - 60,
                )
                await database.record_usage(
                    wid,
                    [container(rx=GB, tx=0, mem=512), container(slug="mysterium", cid="m", rx=None, tx=None)],
                    now=now,
                )
            with (
                patch.object(main, "_require_auth_api", lambda r: None),
                patch.object(main.database, "list_workers", AsyncMock(return_value=workers)),
                patch.object(main.database, "get_earned_by_platform", earned_stub({"honeygain": 1.0})),
            ):
                return await main.api_usage_servers(MagicMock())

        data = run_db(tmp_path, go)
        assert data["window_days"] == 1
        assert [s["name"] for s in data["servers"]] == ["geiserback", "watchtower"]
        server = data["servers"][0]
        hg = next(s for s in server["services"] if s["slug"] == "honeygain")
        myst = next(s for s in server["services"] if s["slug"] == "mysterium")
        assert hg["rx"] == GB and hg["rx_today"] == GB
        # Earnings are per account: $1 over 2 GB moved on the whole fleet.
        assert abs(hg["usd_per_gb"] - 0.5) < 1e-9
        # $1 over 1 GB of average memory across both servers.
        assert abs(hg["usd_per_gb_ram"] - 1.0) < 1e-9
        assert myst["rx"] is None and myst["usd_per_gb"] is None and myst["earned_usd"] is None
        assert server["total"]["rx"] == GB
        assert server["total"]["memory_mb"] == 562.0

    def test_no_rows_is_an_empty_panel(self, tmp_path):
        from app import main

        async def go():
            with patch.object(main, "_require_auth_api", lambda r: None):
                return await main.api_usage_servers(MagicMock())

        assert run_db(tmp_path, go)["servers"] == []


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
