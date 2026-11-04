"""Activity on the UI: ingest, storage and retention, alerts, the API gate, the network table.

Database tests run against a real SQLite file in tmp_path, the same way
tests/test_usage.py does.
"""

from __future__ import annotations

import asyncio
import gzip
import io
import json
import logging
import re
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app import activity_ui, database, ipgeo

NOW = 1_800_000_000.0
END = int(NOW // 300 * 300)
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b|2001:db8", re.I)  # every IPv4, and the IPv6 fixtures


def window(end=END, out=None, inbound=None, container="cashpilot-honeygain", **extra):
    sample = {
        "container": container,
        "members": [container],
        "network_mode": "cashpilot-isolated",
        "status": "ok",
        "reason": "",
        "opens": 12,
        "passive_opens": 1,
        "attempt_fails": 2,
        "resets": 0,
        "udp_in": 0,
        "udp_out": 0,
        "est_max": 4,
        "syn_sent_max": 1,
        "udp_bound": 0,
        "listen_ports": [8080],
        "remotes_total": 3,
        "truncated": False,
        "out": out
        if out is not None
        else [
            ["tcp", "198.51.100.9", 443, "public", 5, {"est": 5}],
            ["tcp", "203.0.113.20", 80, "public", 2, {"est": 2}],
        ],
        "in": inbound if inbound is not None else [["192.0.2.33", 8080, "public", 1]],
    }
    sample.update(extra)
    return {"v": 1, "window_end": end, "worker_status": "ok", "leftover_probes": [], "samples": [sample]}


def run_db(tmp_path, factory):
    async def go():
        with (
            patch.object(database, "DB_DIR", tmp_path),
            patch.object(database, "DB_PATH", tmp_path / "activity.db"),
        ):
            await database.init_db()
            return await factory()

    return asyncio.run(go())


async def rows(table):
    db = await database._get_db()
    cursor = await db.execute(f"SELECT * FROM {table}")  # noqa: S608
    return [dict(r) for r in await cursor.fetchall()]


# ---------------------------------------------------------------------------
# sanitise
# ---------------------------------------------------------------------------


class TestSanitise:
    def test_a_good_window(self):
        w = activity_ui.sanitise(window(), NOW)
        s = w["samples"][0]
        assert s["out"][0] == {
            "proto": "tcp",
            "ip": "198.51.100.9",
            "port": 443,
            "class": "public",
            "seen": 5,
            "states": {"est": 5},
        }
        assert s["in"][0] == {"ip": "192.0.2.33", "port": 8080, "class": "public", "seen": 1}

    @pytest.mark.parametrize(
        "payload",
        [
            None,
            [],
            {"v": 2, "window_end": END, "samples": []},
            {"v": 1, "window_end": "x"},
            {"v": 1, "window_end": int(NOW) + 3600},
        ],
    )
    def test_not_a_window_we_read(self, payload):
        assert activity_ui.sanitise(payload, NOW) is None

    def test_older_than_a_day_is_refused(self):
        assert activity_ui.sanitise(window(end=END - 2 * 86400), NOW) is None

    def test_bad_rows_are_dropped(self):
        out = [
            ["tcp", "not-an-ip", 443, "public", 1, {}],
            ["tcp", "198.51.100.9", 70000, "public", 1, {}],
            ["icmp", "198.51.100.9", 443, "public", 1, {}],
            ["tcp", "198.51.100.9", 443, "evil", 1, {}],
            ["tcp", "198.51.100.9", 443, "public", 1, {"est": 1, "bogus": 3}],
        ]
        s = activity_ui.sanitise(window(out=out), NOW)["samples"][0]
        assert len(s["out"]) == 1 and s["out"][0]["states"] == {"est": 1}

    def test_caps_are_enforced_again(self):
        out = [["tcp", f"198.51.{i // 200}.{i % 200 + 1}", 443, "public", 1, {}] for i in range(100)]
        samples = window(out=out)["samples"] * 20
        w = activity_ui.sanitise({"v": 1, "window_end": END, "samples": samples}, NOW)
        assert all(len(s["out"]) <= activity_ui.MAX_OUT for s in w["samples"])
        assert sum(len(s["out"]) + len(s["in"]) for s in w["samples"]) <= activity_ui.MAX_DESTINATIONS

    def test_constants_match_their_sources(self):
        assert activity_ui.TRUTHY == database._TRUTHY
        assert activity_ui.RAW_HOURS * 3600 == database.ACTIVITY_RAW_SECONDS


# ---------------------------------------------------------------------------
# storage and retention
# ---------------------------------------------------------------------------


class TestStorage:
    def test_rows_and_aggregates(self, tmp_path):
        async def go():
            w = activity_ui.sanitise(window(), NOW)
            await database.record_activity(1, w, {"198.51.100.9": ("AS64500 EXAMPLE", "NL")}, now=NOW)
            return await rows("activity_samples"), await rows("activity_dest_raw"), await rows("activity_hourly")

        samples, raw, hourly = run_db(tmp_path, go)
        assert len(samples) == 1 and samples[0]["opens"] == 12
        assert {r["ip"] for r in raw} == {"198.51.100.9", "203.0.113.20", "192.0.2.33"}
        dims = {(r["dim"], r["value"]): r["sightings"] for r in hourly}
        assert dims[("port", "tcp/443")] == 5
        assert dims[("asn", "AS64500 EXAMPLE")] == 5 and dims[("cc", "NL")] == 5
        assert dims[("dir", "in")] == 1 and dims[("dir", "out")] == 7

    def test_a_repeated_window_is_not_counted_twice(self, tmp_path):
        async def go():
            w = activity_ui.sanitise(window(), NOW)
            await database.record_activity(1, w, now=NOW)
            await database.record_activity(1, w, now=NOW)
            return await rows("activity_dest_raw"), await rows("activity_hourly")

        raw, hourly = run_db(tmp_path, go)
        assert len(raw) == 3
        assert {(r["dim"], r["value"]): r["sightings"] for r in hourly}[("port", "tcp/443")] == 5

    def test_purge_keeps_23h59_and_drops_24h01(self, tmp_path):
        async def go():
            db = await database._get_db()
            for age in (23 * 3600 + 59 * 60, 24 * 3600 + 60):
                await db.execute(
                    "INSERT INTO activity_dest_raw (worker_id, container, window_end, dir, proto, ip, port, class) "
                    "VALUES (1, 'c', ?, 'out', 'tcp', '198.51.100.9', 443, 'public')",
                    (int(NOW) - age,),
                )
            await db.commit()
            purged = await database.purge_activity_raw(now=NOW)
            return purged, [int(NOW) - r["window_end"] for r in await rows("activity_dest_raw")]

        purged, ages = run_db(tmp_path, go)
        assert purged == 1 and ages == [23 * 3600 + 59 * 60]

    def test_ingest_purges_in_the_same_transaction(self, tmp_path):
        async def go():
            old = activity_ui.sanitise(window(end=END - 86400 + 300), NOW)
            await database.record_activity(1, old, now=NOW - 3600)
            await database.record_activity(
                1, activity_ui.sanitise(window(container="cashpilot-other"), NOW), now=NOW + 900
            )
            return {r["container"] for r in await rows("activity_dest_raw")}

        assert run_db(tmp_path, go) == {"cashpilot-other"}

    def test_samples_and_hourly_purged_after_35_days(self, tmp_path):
        async def go():
            real_now = time.time()
            end = int(real_now // 300 * 300)
            await database.record_activity(1, activity_ui.sanitise(window(end=end), real_now), now=real_now)
            db = await database._get_db()
            old = end - 36 * 86400
            await db.execute("UPDATE activity_samples SET window_end = ?", (old,))
            await db.execute("UPDATE activity_hourly SET hour = ?", (old,))
            await db.commit()
            await database.purge_old_data()
            return len(await rows("activity_samples")), len(await rows("activity_hourly"))

        assert run_db(tmp_path, go) == (0, 0)

    def test_opt_out_and_delete(self, tmp_path):
        async def go():
            await database.record_activity(1, activity_ui.sanitise(window(), NOW), now=NOW)
            await database.record_activity(2, activity_ui.sanitise(window(), NOW), now=NOW)
            await database.delete_activity(1, raw_only=True)
            after_opt_out = (len(await rows("activity_dest_raw")), len(await rows("activity_samples")))
            await database.delete_activity(2)
            return after_opt_out, len(await rows("activity_dest_raw")), len(await rows("activity_samples"))

        assert run_db(tmp_path, go) == ((3, 2), 0, 1)

    def test_removing_a_worker_deletes_its_activity(self, tmp_path):
        async def go():
            wid = await database.upsert_worker(
                client_id="c1", name="box", url="", containers="[]", apps="[]", system_info="{}"
            )
            await database.record_activity(wid, activity_ui.sanitise(window(), NOW), now=NOW)
            await database.delete_worker(wid)
            return len(await rows("activity_dest_raw")) + len(await rows("activity_samples"))

        assert run_db(tmp_path, go) == 0


# ---------------------------------------------------------------------------
# the heartbeat
# ---------------------------------------------------------------------------


class TestHeartbeat:
    def _run(self, tmp_path, factory):
        from app import main

        async def go():
            with (
                patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
                patch.object(main.database, "get_worker_status_and_name", AsyncMock(return_value=None)),
                patch.object(main.database, "confirm_worker_key", AsyncMock()),
                patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
                patch.object(main, "_push_alert", AsyncMock()),
                patch.object(ipgeo, "db_path", lambda: tmp_path / "ipgeo.sqlite"),
            ):
                return await factory(main)

        return run_db(tmp_path, go)

    @staticmethod
    async def _hb(main, cid, activity=None, system_info=None):
        body = main.WorkerHeartbeat(
            name=cid, client_id=cid, containers=[], system_info=system_info or {}, activity=activity
        )
        return await main.api_worker_heartbeat(MagicMock(), body)

    def test_the_model_keeps_the_field(self):
        from app import main

        assert main.WorkerHeartbeat(name="w", activity={"v": 1}).activity == {"v": 1}
        assert main.WorkerHeartbeat(name="w").activity is None

    def test_only_the_opted_in_twin_stores_rows(self, tmp_path):
        async def go(main):
            await database.set_config("worker_on_activity", "true")
            on = await self._hb(main, "on", window(end=int(time.time() // 300 * 300)))
            off = await self._hb(main, "off", window(end=int(time.time() // 300 * 300)))
            return on, off, await rows("activity_samples"), await rows("workers")

        on, off, samples, workers = self._run(tmp_path, go)
        ids = {w["client_id"]: w["id"] for w in workers}
        assert on["activity"] == {"enabled": True} and off["activity"] == {"enabled": False}
        assert {s["worker_id"] for s in samples} == {ids["on"]}

    def test_a_phone_gets_no_activity_key(self, tmp_path):
        async def go(main):
            return await self._hb(main, "phone", None, {"os": "Android"})

        assert "activity" not in self._run(tmp_path, go)

    @pytest.mark.parametrize(
        "payload",
        [
            {"v": 1, "window_end": "junk", "samples": "junk"},
            {"v": 99},
            dict(window(end=int(time.time() // 300 * 300)), pad="x" * (activity_ui.MAX_PAYLOAD_BYTES + 1)),
        ],
    )
    def test_bad_payloads_still_get_200_and_store_nothing(self, tmp_path, payload):
        async def go(main):
            await database.set_config("worker_on_activity", "true")
            resp = await self._hb(main, "on", payload)
            return resp, await rows("activity_samples")

        resp, samples = self._run(tmp_path, go)
        assert resp["status"] == "ok" and resp["activity"] == {"enabled": True}
        assert samples == []

    def test_an_ingest_exception_still_gets_200_and_logs_no_address(self, tmp_path, caplog):
        async def go(main):
            await database.set_config("worker_on_activity", "true")
            with patch.object(
                main.database, "record_activity", AsyncMock(side_effect=RuntimeError("198.51.100.9 broke"))
            ):
                return await self._hb(main, "on", window(end=int(time.time() // 300 * 300)))

        with caplog.at_level(logging.DEBUG):
            resp = self._run(tmp_path, go)
        assert resp["status"] == "ok"
        assert "198.51.100.9" not in caplog.text
        assert "Could not record activity" in caplog.text


# ---------------------------------------------------------------------------
# no address outside the raw table
# ---------------------------------------------------------------------------


class TestNoAddressLeaks:
    def test_no_ip_outside_the_raw_table(self, tmp_path, caplog):
        from app import main

        out = [
            ["tcp", "198.51.100.9", 25, "public", 3, {"est": 3}],
            ["tcp", "192.168.1.10", 22, "lan", 1, {"syn_sent": 1}],
            ["tcp", "169.254.169.254", 80, "metadata", 1, {"syn_sent": 1}],
            ["tcp", "2001:db8::1", 587, "public", 1, {"syn_sent": 1}],
        ]

        async def go():
            with (
                patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
                patch.object(main.database, "get_worker_status_and_name", AsyncMock(return_value=None)),
                patch.object(main.database, "confirm_worker_key", AsyncMock()),
                patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
                patch.object(main, "_push_alert", AsyncMock()) as push,
                patch.object(ipgeo, "db_path", lambda: tmp_path / "ipgeo.sqlite"),
            ):
                await database.set_config("worker_box_activity", "true")
                body = main.WorkerHeartbeat(
                    name="box", client_id="box", activity=window(end=int(time.time() // 300 * 300), out=out)
                )
                await main.api_worker_heartbeat(MagicMock(), body)
                pushed = [json.dumps(c.args) for c in push.call_args_list]
            tables = {}
            for table in ("activity_samples", "activity_hourly", "alerts", "activity_dest_raw"):
                tables[table] = json.dumps(await rows(table))
            return tables, pushed

        with caplog.at_level(logging.DEBUG):
            tables, pushed = run_db(tmp_path, go)
        # Positive control: the raw table does hold the addresses the regex finds.
        assert IP_RE.search(tables["activity_dest_raw"])
        for table in ("activity_samples", "activity_hourly", "alerts"):
            assert not IP_RE.search(tables[table]), table
        assert pushed and not any(IP_RE.search(p) for p in pushed)
        # The app's own log lines; aiosqlite's DEBUG echo of SQL parameters is not ours.
        app_lines = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("app"))
        assert caplog.records and not IP_RE.search(app_lines)
        assert "activity_mail" in tables["alerts"] and "activity_lan" in tables["alerts"]


# ---------------------------------------------------------------------------
# alert rules
# ---------------------------------------------------------------------------


class TestAlertRules:
    def _kinds(self, out):
        return [
            (f["kind"], f["detail"]) for f in activity_ui.alert_findings(activity_ui.sanitise(window(out=out), NOW))
        ]

    def test_mail_needs_public_tcp_on_a_mail_port_connected_or_connecting(self):
        assert self._kinds([["tcp", "198.51.100.9", 587, "public", 1, {"syn_sent": 1}]]) == [("activity_mail", "")]
        assert self._kinds([["tcp", "198.51.100.9", 587, "public", 1, {"other": 1}]]) == []
        assert self._kinds([["udp", "198.51.100.9", 25, "public", 1, {"est": 1}]]) == []
        assert self._kinds([["tcp", "198.51.100.9", 443, "public", 1, {"est": 1}]]) == []

    def test_infra_and_peer_never_raise_lan(self):
        out = [
            ["tcp", "172.18.0.1", 53, "infra", 1, {"est": 1}],
            ["tcp", "172.18.0.7", 8080, "peer", 1, {"est": 1}],
            ["tcp", "198.51.100.9", 443, "public", 1, {"est": 1}],
        ]
        assert self._kinds(out) == []

    @pytest.mark.parametrize("cls", ["lan", "tailnet", "docker_host", "metadata", "link_local"])
    def test_each_lan_class_raises(self, cls):
        assert self._kinds([["tcp", "10.1.2.3", 22, cls, 1, {"syn_sent": 1}]]) == [("activity_lan", cls)]

    def test_pending_wording(self):
        f = activity_ui.alert_findings(
            activity_ui.sanitise(window(out=[["tcp", "10.1.2.3", 22, "lan", 1, {"syn_sent": 1}]]), NOW)
        )
        assert "still pending" in f[0]["message"]

    def test_mail_alert_fires_once_inside_its_cooldown(self, tmp_path):
        from app import main

        out = [["tcp", "198.51.100.9", 25, "public", 1, {"est": 1}]]

        async def go():
            with (
                patch.object(main, "_push_alert", AsyncMock()),
                patch.object(ipgeo, "db_path", lambda: tmp_path / "ipgeo.sqlite"),
            ):
                for i in range(3):
                    end = int(time.time() // 300 * 300) - i * 300
                    await main._ingest_activity(1, "box", "box", window(end=end, out=out))
                return await rows("alerts")

        alerts = run_db(tmp_path, go)
        assert [a["kind"] for a in alerts] == ["activity_mail"]


class TestSpikes:
    def test_needs_72_hours(self):
        assert activity_ui.spike([1.0] * 71, 10**10, 1) is False
        assert activity_ui.spike([1.0] * 72, 10**10, 1) is True

    def test_nulls_are_skipped_not_zero(self):
        # With None read as 0 the median would be 0 and anything would spike.
        history = [None] * 100 + [100.0] * 72
        assert activity_ui.spike(history, 900.0, 1) is False
        assert activity_ui.spike(history, 1001.0, 1) is True

    def test_floor_and_ratio(self):
        assert activity_ui.spike([1.0] * 100, 5000.0, activity_ui.SPIKE_OPENS_FLOOR) is True
        assert activity_ui.spike([1.0] * 100, 1500.0, activity_ui.SPIKE_OPENS_FLOOR) is False
        assert activity_ui.spike([1.0] * 100, None, 0) is False

    def test_byte_spike_from_usage_hourly(self, tmp_path):
        from app import main

        now = 1_900_000_000.0
        last = int(now // 3600) * 3600 - 3600

        async def go():
            db = await database._get_db()
            for i in range(1, 100):
                await db.execute(
                    "INSERT INTO usage_hourly (worker_id, container, hour, slug, rx_bytes, tx_bytes) VALUES (1, 'c', ?, 'x', ?, ?)",
                    (last - i * 3600, 10 * 1024**2, None),
                )
            await db.execute(
                "INSERT INTO usage_hourly (worker_id, container, hour, slug, rx_bytes, tx_bytes) VALUES (1, 'c', ?, 'x', ?, NULL)",
                (last, 5 * 1024**3),
            )
            await db.commit()
            await main._activity_spikes([{"id": 1, "client_id": "box", "name": "box"}], now=now)
            return await rows("alerts")

        alerts = run_db(tmp_path, go)
        assert [(a["kind"], a["subject"]) for a in alerts] == [("activity_spike", "box:c:bytes")]
        assert "received 5.0 GiB" in alerts[0]["message"]


# ---------------------------------------------------------------------------
# the API gate
# ---------------------------------------------------------------------------


ROUTES = [
    ("GET", "/activity"),
    ("GET", "/api/activity/summary"),
    ("GET", "/api/activity/container?worker_id=1&container=x"),
    ("POST", "/api/activity/settings"),
    ("POST", "/api/activity/delete"),
    ("POST", "/api/activity/asn/refresh"),
]


class TestGate:
    @pytest.fixture
    def client(self):
        from contextlib import asynccontextmanager

        from fastapi.testclient import TestClient

        from app.main import app

        @asynccontextmanager
        async def noop(a):
            yield

        saved = app.router.lifespan_context
        app.router.lifespan_context = noop
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        app.router.lifespan_context = saved

    @pytest.mark.parametrize(("method", "path"), ROUTES)
    def test_viewer_and_writer_get_403(self, client, method, path):
        for user in ({"uid": 3, "u": "v", "r": "viewer"}, {"uid": 2, "u": "w", "r": "writer"}):
            with patch("app.auth.get_current_user", return_value=user):
                resp = client.request(method, path, json={"worker_id": 1, "enabled": True})
            assert resp.status_code == 403, (path, user["r"], resp.status_code)

    @pytest.mark.parametrize(("method", "path"), [r for r in ROUTES if r[0] == "POST"])
    def test_mutations_are_post_only(self, client, method, path):
        with patch("app.auth.get_current_user", return_value={"uid": 1, "u": "o", "r": "owner"}):
            assert client.get(path).status_code == 405

    def test_owner_settings_off_deletes_raw(self, tmp_path):
        from app.routers import activity as router

        async def go():
            wid = await database.upsert_worker(
                client_id="c1", name="box", url="", containers="[]", apps="[]", system_info="{}"
            )
            await database.record_activity(wid, activity_ui.sanitise(window(), NOW), now=NOW)
            with patch.object(router.deps, "_require_owner", return_value={}):
                on = await router.api_activity_settings(
                    MagicMock(), router.ActivitySetting(worker_id=wid, enabled=True)
                )
                still = len(await rows("activity_dest_raw"))
                off = await router.api_activity_settings(
                    MagicMock(), router.ActivitySetting(worker_id=wid, enabled=False)
                )
            config = await database.get_config()
            return on, still, off, len(await rows("activity_dest_raw")), config.get("worker_c1_activity")

        on, still, off, after, flag = run_db(tmp_path, go)
        assert on["enabled"] is True and still == 3
        assert off["deleted_raw"] == 3 and after == 0 and flag == "false"

    def test_unknown_worker_is_404(self, tmp_path):
        from app.routers import activity as router

        async def go():
            with patch.object(router.deps, "_require_owner", return_value={}):
                await router.api_activity_settings(MagicMock(), router.ActivitySetting(worker_id=999, enabled=True))

        with pytest.raises(HTTPException) as exc:
            run_db(tmp_path, go)
        assert exc.value.status_code == 404

    def test_summary_shape(self, tmp_path):
        from app.routers import activity as router

        async def go():
            wid = await database.upsert_worker(
                client_id="c1",
                name="box",
                url="",
                containers="[]",
                apps="[]",
                system_info=json.dumps({"features": ["activity"]}),
            )
            await database.set_config("worker_c1_activity", "true")
            real_now = time.time()
            await database.record_activity(
                wid, activity_ui.sanitise(window(end=int(real_now // 300 * 300)), real_now), now=real_now
            )
            with (
                patch.object(router.deps, "_require_owner", return_value={}),
                patch.object(ipgeo, "db_path", lambda: tmp_path / "ipgeo.sqlite"),
            ):
                return await router.api_activity_summary(MagicMock(), days=1)

        data = run_db(tmp_path, go)
        w = data["workers"][0]
        assert w["enabled"] is True and w["supported"] is True
        c = w["containers"][0]
        assert c["container"] == "cashpilot-honeygain" and c["opens_last"] == 12
        assert c["top_ports"][0] == ["tcp/443", 5]
        assert data["asn"]["present"] is False
        assert not IP_RE.search(json.dumps(data))


class TestSeries:
    def test_hourly_sums_keep_unknown_hours_unknown(self, tmp_path):
        async def go():
            db = await database._get_db()
            hour = 1_800_000_000 // 3600 * 3600
            for i, opens in enumerate([10, None, 5]):
                await db.execute(
                    "INSERT INTO activity_samples (worker_id, container, window_end, status, opens, attempt_fails, est_max) "
                    "VALUES (1, 'c', ?, 'ok', ?, 1, ?)",
                    (hour + 300 * (i + 1), opens, i),
                )
            await db.execute(
                "INSERT INTO activity_samples (worker_id, container, window_end, status, opens) VALUES (1, 'c', ?, 'ok', NULL)",
                (hour + 3600 + 300,),
            )
            await db.commit()
            hourly = await database.get_activity_series(0, True)
            raw = await database.get_activity_series(0, False, 1, "c")
            latest = await database.get_activity_latest(0)
            return hourly, raw, latest

        hourly, raw, latest = run_db(tmp_path, go)
        assert [(r["opens"], r["est_max"]) for r in hourly] == [(15, 2), (None, None)]
        assert [r["opens"] for r in raw] == [10, None, 5, None]
        assert len(latest) == 1 and latest[0]["window_end"] == 1_800_000_000 // 3600 * 3600 + 3900

    def test_container_detail(self, tmp_path):
        from app.routers import activity as router

        async def go():
            wid = await database.upsert_worker(
                client_id="c1", name="box", url="", containers="[]", apps="[]", system_info="{}"
            )
            real_now = time.time()
            await database.record_activity(
                wid, activity_ui.sanitise(window(end=int(real_now // 300 * 300)), real_now), now=real_now
            )
            with patch.object(router.deps, "_require_owner", return_value={}):
                return await router.api_activity_container(
                    MagicMock(), worker_id=wid, container="cashpilot-honeygain", days=7
                )

        d = run_db(tmp_path, go)
        assert d["series"][0][1] == 12
        assert {r["ip"] for r in d["raw"]} == {"198.51.100.9", "203.0.113.20", "192.0.2.33"}
        assert d["dims"]["class"] == [["public", 8]]


# ---------------------------------------------------------------------------
# the network table
# ---------------------------------------------------------------------------


TSV = (
    "1.0.0.0\t1.0.0.255\t13335\tUS\tCLOUDFLARENET\n"
    "1.0.1.0\t1.0.3.255\t0\tNone\tNot routed\n"
    "8.8.8.0\t8.8.8.255\t15169\tUS\tGOOGLE\n"
    "2001:db8::\t2001:db8::ffff\t64500\tNL\tEXAMPLE-V6\n"
)


class TestIpgeo:
    def _build(self, tmp_path):
        with patch.object(ipgeo, "MIN_ROWS", 1):
            ipgeo.build(io.StringIO(TSV), tmp_path / "ipgeo.sqlite")

    def test_lookup_at_range_edges(self, tmp_path):
        self._build(tmp_path)
        with patch.object(ipgeo, "db_path", lambda: tmp_path / "ipgeo.sqlite"):
            got = ipgeo.lookup(
                [
                    "1.0.0.0",
                    "1.0.0.255",
                    "1.0.1.0",
                    "0.255.255.255",
                    "8.8.8.8",
                    "2001:db8::",
                    "2001:db8::ffff",
                    "2001:db8::1:0",
                ]
            )
            status = ipgeo.status()
        assert got["1.0.0.0"] == ("AS13335 CLOUDFLARENET", "US")
        assert got["1.0.0.255"] == ("AS13335 CLOUDFLARENET", "US")
        assert "1.0.1.0" not in got  # AS 0, not routed
        assert "0.255.255.255" not in got
        assert got["8.8.8.8"][0] == "AS15169 GOOGLE"
        assert got["2001:db8::"] == ("AS64500 EXAMPLE-V6", "NL")
        assert got["2001:db8::ffff"][1] == "NL"
        assert "2001:db8::1:0" not in got
        assert status["present"] is True and status["rows"] == 3

    def test_missing_file(self, tmp_path):
        with patch.object(ipgeo, "db_path", lambda: tmp_path / "nope.sqlite"):
            assert ipgeo.lookup(["8.8.8.8"]) == {}
            assert ipgeo.status()["present"] is False

    def test_corrupt_file(self, tmp_path):
        (tmp_path / "ipgeo.sqlite").write_bytes(b"not sqlite at all" * 100)
        with patch.object(ipgeo, "db_path", lambda: tmp_path / "ipgeo.sqlite"):
            assert ipgeo.lookup(["8.8.8.8"]) == {}

    def test_a_tiny_file_never_replaces_the_table(self, tmp_path):
        self._build(tmp_path)
        before = (tmp_path / "ipgeo.sqlite").read_bytes()
        with pytest.raises(ValueError):
            ipgeo.build(io.StringIO(TSV), tmp_path / "ipgeo.sqlite")
        assert (tmp_path / "ipgeo.sqlite").read_bytes() == before

    def test_gzip_bytes_lines(self, tmp_path):
        data = gzip.compress(TSV.encode())
        with patch.object(ipgeo, "MIN_ROWS", 1), gzip.open(io.BytesIO(data), "rb") as f:
            n = ipgeo.build(f, tmp_path / "ipgeo.sqlite")
        assert n == 3

    def test_empty_url_disables(self, monkeypatch):
        monkeypatch.setenv("CASHPILOT_ACTIVITY_ASN_URL", "")
        assert ipgeo.source_url() == ""
        assert ipgeo.needs_refresh() is False
