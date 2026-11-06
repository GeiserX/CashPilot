"""Proxies on the UI side (app/proxies.py and the /api/proxies routes, docs/proxies.md)."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app import database, egress, main, proxies

PASSWORD = "Pr0xy-P4ss-7c1e9"
USERNAME = "customer-sergio-cc-es"
AUTH_KEY = "tskey-auth-kTEST-abcdef0123"


def _socks(**over):
    return {"name": "Oxylabs ES", "kind": "socks5", "host": "pr.example.net", "port": 7777, **over}


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------


class TestDefinition:
    def test_a_valid_socks5_proxy(self):
        d = proxies.clean_definition(_socks(username=USERNAME, password=PASSWORD, cap_gb="10", reset_day=1))
        assert (d["kind"], d["host"], d["port"], d["cap_gb"], d["reset_day"]) == (
            "socks5",
            "pr.example.net",
            7777,
            10,
            1,
        )
        assert d["cap_threshold_pct"] == 90

    @pytest.mark.parametrize(
        "over",
        [
            {"kind": "ftp"},
            {"host": "bad host"},
            {"port": 0},
            {"port": 70000},
            {"name": ""},
            {"cap_gb": "-1"},
            {"reset_day": 31},
            {"cap_threshold_pct": 5},
        ],
    )
    def test_bad_input_is_refused(self, over):
        with pytest.raises(proxies.ProxyInputError):
            proxies.clean_definition(_socks(**over))

    def test_tailscale_needs_a_key_and_an_exit_node(self):
        with pytest.raises(proxies.ProxyInputError):
            proxies.clean_definition({"name": "Exit node A", "kind": "tailscale", "exit_node": "exit-node-a"})
        d = proxies.clean_definition(
            {"name": "Exit node A", "kind": "tailscale", "auth_key": AUTH_KEY, "exit_node": "exit-node-a"}
        )
        assert d["auth_key"] == AUTH_KEY and d["host"] == "" and d["password"] == ""

    def test_an_edit_keeps_secrets_left_blank_and_clears_on_request(self):
        stored = proxies.clean_definition(_socks(username=USERNAME, password=PASSWORD))
        kept = proxies.clean_definition({"name": "Renamed", "password": ""}, stored)
        assert kept["password"] == PASSWORD and kept["username"] == USERNAME and kept["name"] == "Renamed"
        cleared = proxies.clean_definition({"clear_password": True}, stored)
        assert cleared["password"] == ""

    def test_the_public_view_never_carries_a_secret(self):
        d = proxies.clean_definition(_socks(username=USERNAME, password=PASSWORD))
        view = proxies.public_view({"id": 1, "definition": d, "state": {}})
        text = json.dumps(view)
        assert PASSWORD not in text and USERNAME not in text
        assert view["secrets"] == {"username": True, "password": True, "auth_key": False}


# ---------------------------------------------------------------------------
# Which services, and with what spec
# ---------------------------------------------------------------------------


class TestEarner:
    @pytest.mark.parametrize(
        "docker",
        [{"network_mode": "host"}, {"ports": ["8080:8080"]}, {"volumes": ["/x:/y"]}, {"devices": ["/dev/net/tun"]}],
    )
    def test_services_that_need_the_host_are_refused(self, docker):
        assert proxies.refusal({"name": "X", "docker": {"image": "x", **docker}})

    def test_a_documented_prohibition_is_refused_with_its_source(self):
        svc = {"name": "X", "docker": {"image": "x"}, "requirements": {"proxy_prohibited": {"source": "https://x/tos"}}}
        assert "https://x/tos" in proxies.refusal(svc)

    @pytest.mark.parametrize("cap", ["NET_ADMIN", "NET_RAW", "SYS_ADMIN", "cap_net_admin"])
    def test_an_earner_that_could_touch_the_tunnel_firewall_is_refused(self, cap):
        why = proxies.refusal({"name": "X", "docker": {"image": "x", "cap_add": [cap]}})
        assert why and "firewall" in why

    def test_a_plain_earner_is_allowed(self):
        assert proxies.refusal({"name": "X", "docker": {"image": "x", "env": []}}) is None

    def test_the_copy_has_its_own_device_names_and_nothing_of_the_host(self):
        docker_conf = {
            "env": [{"key": "DEVICE", "default": "cashpilot-{hostname}"}, {"key": "TOKEN"}],
            "command": "run --device ${DEVICE} --token ${TOKEN}",
        }
        recorded = {
            "image": "x/x:1",
            "env": {"DEVICE": "cashpilot-box", "TOKEN": "t0k"},
            "ports": {"1/tcp": 1},
            "volumes": {"/a": {"bind": "/b", "mode": "rw"}},
            "network_mode": "bridge",
            "command": "run --device cashpilot-box --token t0k",
            "hostname": "box",
            "instances": 2,
        }
        spec = proxies.earner_spec(recorded, docker_conf, 4)
        assert spec["env"] == {"DEVICE": "cashpilot-box-p4", "TOKEN": "t0k"}
        assert spec["command"] == "run --device cashpilot-box-p4 --token t0k"
        assert not {"ports", "volumes", "network_mode", "hostname", "instances"} & set(spec)


# ---------------------------------------------------------------------------
# Traffic cap
# ---------------------------------------------------------------------------


def _entry(rx, tx, tid="t1", ip="93.184.215.14", started="2026-11-01T00:00:00Z", **extra):
    return {
        "proxy_id": 1,
        "slug": "a",
        "tunnel_container_id": tid,
        "tunnel_started_at": started,
        "net_rx_bytes": rx,
        "net_tx_bytes": tx,
        "exit_ip": ip,
        **extra,
    }


CAPPED = {"name": "P", "cap_gb": 1, "cap_threshold_pct": 90, "reset_day": 1}


class TestCap:
    def test_a_first_reading_counts_from_the_tunnels_start_then_deltas_count(self):
        # The tunnel's counter began at zero when it started, so nothing it moved
        # before the first heartbeat is lost.
        s, crossed = proxies.account({}, CAPPED, 7, [_entry(1000, 500)], 100.0)
        assert s["used_bytes"] == 1500 and not crossed
        s, crossed = proxies.account(s, CAPPED, 7, [_entry(4000, 1500)], 160.0)
        assert s["used_bytes"] == 5500 and not crossed

    def test_a_counter_that_went_backwards_is_a_restart(self):
        s, _ = proxies.account({}, CAPPED, 7, [_entry(1000, 0)], 100.0)
        s, _ = proxies.account(s, CAPPED, 7, [_entry(300, 0)], 160.0)
        assert s["used_bytes"] == 1300

    def test_a_new_start_time_is_a_restart_even_when_the_counter_is_higher(self):
        s, _ = proxies.account({}, CAPPED, 7, [_entry(1000, 0)], 100.0)
        s, _ = proxies.account(s, CAPPED, 7, [_entry(5000, 0, started="2026-11-02T00:00:00Z")], 160.0)
        assert s["used_bytes"] == 6000

    def test_a_long_gap_still_counts_every_byte(self):
        # The UI was down for three hours while the copy kept running: the
        # counter on the same tunnel is exact, so the whole gap counts.
        s, _ = proxies.account({}, CAPPED, 7, [_entry(1000, 0)], 100.0)
        s, _ = proxies.account(s, CAPPED, 7, [_entry(9_000_000, 0)], 100.0 + 3 * 3600)
        assert s["used_bytes"] == 9_000_000

    def test_a_baseline_survives_a_week_long_outage(self):
        s, _ = proxies.account({}, CAPPED, 7, [_entry(1000, 0)], 100.0)
        s, _ = proxies.account(s, CAPPED, 7, [_entry(4000, 0)], 100.0 + 7 * 86400)
        assert s["used_bytes"] == 4000

    def test_two_workers_never_share_a_baseline(self):
        s, _ = proxies.account({}, CAPPED, 7, [_entry(1000, 0)], 100.0)
        s, _ = proxies.account(s, CAPPED, 8, [_entry(5000, 0)], 110.0)
        assert s["used_bytes"] == 6000
        s, _ = proxies.account(s, CAPPED, 8, [_entry(5500, 0)], 170.0)
        assert s["used_bytes"] == 6500

    def test_crossing_the_threshold_says_why_once(self):
        s, _ = proxies.account({}, CAPPED, 7, [_entry(0, 0)], 100.0)
        s, crossed = proxies.account(s, CAPPED, 7, [_entry(900_000_000, 0)], 160.0)
        assert crossed and s["capped_at"]
        assert "90% of its 1 GB cap" in s["cap_reason"] and "day 1" in s["cap_reason"]
        s, again = proxies.account(s, CAPPED, 7, [_entry(950_000_000, 0)], 220.0)
        assert not again

    def test_turning_a_cap_on_starts_a_fresh_period(self):
        state = {"used_bytes": 40 * proxies.GB, "counters": {"7:t1": [1, 1, 1, ""]}}
        new, release = proxies.cap_change({"cap_gb": None}, {**CAPPED, "cap_gb": 20}, state, date(2026, 11, 4))
        assert new["used_bytes"] == 0 and new["period_start"] == "2026-11-04" and not release
        assert new["counters"] == state["counters"]
        _, crossed = proxies.account(new, {**CAPPED, "cap_gb": 20}, 7, [], 100.0)
        assert not crossed

    def test_removing_or_raising_the_cap_lifts_the_stop(self):
        capped = {"used_bytes": 900_000_000, "capped_at": "2026-11-04T01:00:00+00:00", "cap_reason": "old"}
        new, release = proxies.cap_change(CAPPED, {**CAPPED, "cap_gb": None}, capped, date(2026, 11, 4))
        assert release and "capped_at" not in new and "cap_reason" not in new
        new, release = proxies.cap_change(CAPPED, {**CAPPED, "cap_gb": 2}, capped, date(2026, 11, 4))
        assert release and "capped_at" not in new and new["used_bytes"] == 900_000_000

    def test_a_cap_still_exceeded_keeps_the_stop_with_the_new_numbers(self):
        capped = {"used_bytes": 900_000_000, "capped_at": "x", "cap_reason": "old"}
        new, release = proxies.cap_change(CAPPED, {**CAPPED, "cap_threshold_pct": 80}, capped, date(2026, 11, 4))
        assert not release and new["capped_at"] == "x" and "80% of its 1 GB" in new["cap_reason"]

    def test_no_cap_never_crosses(self):
        d = {**CAPPED, "cap_gb": None}
        s, _ = proxies.account({}, d, 7, [_entry(0, 0)], 100.0)
        _, crossed = proxies.account(s, d, 7, [_entry(10**15, 0)], 160.0)
        assert not crossed

    def test_a_private_exit_is_not_recorded(self):
        s, _ = proxies.account({}, CAPPED, 7, [_entry(0, 0, ip="10.0.0.1")], 100.0)
        assert "last_exit_ip" not in s

    @pytest.mark.parametrize(
        ("start", "today", "due"),
        [
            (None, date(2026, 11, 4), True),
            ("2026-10-01", date(2026, 11, 4), True),
            ("2026-11-01", date(2026, 11, 4), False),
            ("2026-10-15", date(2026, 11, 10), False),
            ("2026-10-15", date(2026, 11, 15), True),
            ("2025-12-20", date(2026, 1, 10), False),
        ],
    )
    def test_reset_due(self, start, today, due):
        day = 1 if start in (None, "2026-10-01", "2026-11-01") else (15 if "-15" in start else 20)
        state = {"period_start": start} if start else {}
        assert proxies.reset_due({"reset_day": day}, state, today) is due

    def test_a_reset_starts_only_copies_the_cap_stopped(self):
        proxy = {"id": 1, "definition": {"name": "P"}, "state": {"used_bytes": 5, "capped_at": "x", "cap_reason": "y"}}
        copies = [
            {"proxy_id": 1, "worker_id": 7, "slug": "a", "stopped_by_cap": 1},
            {"proxy_id": 1, "worker_id": 7, "slug": "b", "stopped_by_cap": 0},
        ]
        call = AsyncMock(return_value={})
        with (
            patch.object(main.database, "get_proxy", new_callable=AsyncMock, return_value=proxy),
            patch.object(main.database, "update_proxy_state", new_callable=AsyncMock) as upd,
            patch.object(main.database, "clear_alerts", new_callable=AsyncMock),
            patch.object(main.database, "list_proxied_copies", new_callable=AsyncMock, return_value=copies),
            patch.object(main.database, "set_proxied_copy_capped", new_callable=AsyncMock),
            patch.object(main, "_proxy_worker_call", call),
        ):
            started = asyncio.run(main._reset_proxy(proxy))
        assert started == ["a on worker 7"]
        assert [c.args[2] for c in call.call_args_list] == ["/api/proxied/a/1/start"]
        new_state = upd.call_args.args[1]
        assert new_state["used_bytes"] == 0 and "capped_at" not in new_state

    def test_crossing_stops_every_copy_and_raises_an_alert(self):
        proxy = {
            "id": 1,
            "definition": {**CAPPED, "password": PASSWORD},
            "state": {"capped_at": "x", "cap_reason": "P reached 90%"},
        }
        call = AsyncMock(return_value={})
        with (
            patch.object(main.database, "get_proxy", new_callable=AsyncMock, return_value=proxy),
            patch.object(main.database, "set_proxied_copy_capped", new_callable=AsyncMock) as mark,
            patch.object(main.database, "record_alert", new_callable=AsyncMock, return_value=None) as alert,
            patch.object(main, "_proxy_worker_call", call),
        ):
            asyncio.run(main._stop_capped_proxy(proxy, {(7, "a"), (8, "b")}))
        assert [c.args[2] for c in call.call_args_list] == ["/api/proxied/a/1/stop", "/api/proxied/b/1/stop"]
        assert all(c.args[3] is True for c in mark.call_args_list) and mark.call_count == 2
        assert alert.call_args.args[:2] == ("proxy_cap", "1")
        assert alert.call_args.args[2] == "Stopped: P reached 90%."
        main._drop_proxy_cap_bell(1)

    def test_a_copy_the_owner_had_stopped_is_not_marked_by_the_cap(self):
        """Docker answers a stop of a stopped container with success, so the
        worker says whether the copy was running; only those are the cap's."""
        proxy = {"id": 1, "definition": dict(CAPPED), "state": {"capped_at": "x", "cap_reason": "P reached 90%"}}

        async def worker_call(worker_id, method, path, definition, **kw):
            return {"status": "stopped", "was_running": worker_id == 7}

        with (
            patch.object(main.database, "get_proxy", new_callable=AsyncMock, return_value=proxy),
            patch.object(main.database, "set_proxied_copy_capped", new_callable=AsyncMock) as mark,
            patch.object(main.database, "record_alert", new_callable=AsyncMock, return_value=None),
            patch.object(main, "_proxy_worker_call", AsyncMock(side_effect=worker_call)),
        ):
            asyncio.run(main._stop_capped_proxy(proxy, {(7, "a"), (8, "b")}))
        assert [c.args[:4] for c in mark.call_args_list] == [(1, 7, "a", True)]
        main._drop_proxy_cap_bell(1)

    def test_a_cap_lifted_while_the_stop_ran_starts_the_copy_again(self):
        proxy = {"id": 1, "definition": dict(CAPPED), "state": {"capped_at": "x", "cap_reason": "r"}}
        lifted = {**proxy, "state": {}}
        call = AsyncMock(return_value={"status": "stopped", "was_running": True})
        with (
            patch.object(main.database, "get_proxy", new_callable=AsyncMock, return_value=lifted),
            patch.object(main.database, "set_proxied_copy_capped", new_callable=AsyncMock) as mark,
            patch.object(main.database, "record_alert", new_callable=AsyncMock, return_value=None),
            patch.object(main, "_proxy_worker_call", call),
        ):
            asyncio.run(main._stop_capped_proxy(proxy, {(7, "a")}))
        assert [c.args[2] for c in call.call_args_list] == ["/api/proxied/a/1/stop", "/api/proxied/a/1/start"]
        mark.assert_not_called()
        main._drop_proxy_cap_bell(1)


class _CapRig:
    """_account_proxy_traffic against an in-memory proxy, with the spawned stops awaited."""

    def __init__(self, copies, worker_call):
        self.proxy = {"id": 1, "definition": dict(CAPPED), "state": {}}
        self.copies = copies
        self.call = worker_call
        self.alerts: list[tuple] = []
        self.pushed: list[tuple] = []

    async def heartbeat(self, worker_id, entries):
        spawned: list = []

        async def get_proxy(_pid):
            return {**self.proxy, "state": dict(self.proxy["state"])}

        async def update_state(_pid, state):
            self.proxy["state"] = state

        async def record_alert(kind, subject, message, **_kw):
            self.alerts.append((kind, subject, message))
            return len(self.alerts) if len(self.alerts) == 1 else None

        async def push(*args):
            self.pushed.append(args)

        with (
            patch.object(main.database, "get_proxy", side_effect=get_proxy),
            patch.object(main.database, "update_proxy_state", side_effect=update_state),
            patch.object(main.database, "list_proxied_copies", new_callable=AsyncMock, return_value=self.copies),
            patch.object(main.database, "set_proxied_copy_capped", new_callable=AsyncMock),
            patch.object(main.database, "record_alert", side_effect=record_alert),
            patch.object(main.database, "list_workers", new_callable=AsyncMock, return_value=[]),
            patch.object(main, "_proxy_worker_call", self.call),
            patch.object(main, "_push_alert", side_effect=push),
            patch.object(main, "_spawn", side_effect=spawned.append),
        ):
            await main._account_proxy_traffic(worker_id, entries)
            while spawned:
                await spawned.pop(0)


class TestCapEnforcement:
    def teardown_method(self):
        main._drop_proxy_cap_bell(1)
        main._proxy_cap_stopping.clear()

    def test_a_failed_stop_is_tried_again_on_the_next_heartbeat(self):
        fails = {8: [HTTPException(status_code=503, detail="Worker offline")]}

        async def worker_call(worker_id, method, path, definition, **kw):
            if fails.get(worker_id):
                raise fails[worker_id].pop()
            return {}

        call = AsyncMock(side_effect=worker_call)
        rig = _CapRig(
            [{"proxy_id": 1, "worker_id": 7, "slug": "a"}, {"proxy_id": 1, "worker_id": 8, "slug": "a"}], call
        )

        async def go():
            await rig.heartbeat(7, [_entry(0, 0)])
            # Worker 7's reading crosses the cap; worker 8's copy cannot be stopped.
            await rig.heartbeat(7, [_entry(950_000_000, 0, status="exited", tunnel_status="exited")])
            assert "Could not stop yet" in rig.alerts[-1][2] and "a on worker 8" in rig.alerts[-1][2]
            assert any(a.get("kind") == "proxy_cap" for a in main._collector_alerts)
            # Worker 8 comes back and its heartbeat still reports the copy running.
            await rig.heartbeat(8, [_entry(10, 0, tid="t8", status="running", tunnel_status="running")])

        asyncio.run(go())
        stops = [(c.args[0], c.args[2]) for c in call.call_args_list]
        assert stops == [(7, "/api/proxied/a/1/stop"), (8, "/api/proxied/a/1/stop"), (8, "/api/proxied/a/1/stop")]
        assert rig.alerts[-1][2].startswith("Stopped: ")
        assert len(rig.pushed) == 1 and rig.pushed[0][0] == "proxy_cap"

    def test_a_running_copy_with_no_record_is_stopped_too(self):
        call = AsyncMock(return_value={})
        rig = _CapRig([], call)
        rig.proxy["state"] = {"used_bytes": 950_000_000, "capped_at": "x", "cap_reason": "P reached 90%"}

        async def go():
            await rig.heartbeat(9, [_entry(5, 0, tid="t9", slug="b", status="running", tunnel_status="running")])

        asyncio.run(go())
        assert [(c.args[0], c.args[2]) for c in call.call_args_list] == [(9, "/api/proxied/b/1/stop")]

    def test_a_stopped_copy_is_left_alone(self):
        call = AsyncMock(return_value={})
        rig = _CapRig([], call)
        rig.proxy["state"] = {"used_bytes": 950_000_000, "capped_at": "x", "cap_reason": "r"}
        asyncio.run(rig.heartbeat(9, [_entry(5, 0, tid="t9", status="exited", tunnel_status="exited")]))
        assert call.call_count == 0

    def test_the_bell_keeps_a_cap_that_still_holds_after_a_restart(self):
        capped = {"id": 3, "definition": {"name": "Oxy"}, "state": {"capped_at": "x", "cap_reason": "Oxy reached 90%"}}
        free = {"id": 4, "definition": {"name": "Free"}, "state": {}}
        with (
            patch.object(main.database, "list_alerts", new_callable=AsyncMock, return_value=[]),
            patch.object(main.database, "list_proxies", new_callable=AsyncMock, return_value=[capped, free]),
        ):
            asyncio.run(main._warm_collector_alerts())
        caps = [a for a in main._collector_alerts if a.get("kind") == "proxy_cap"]
        assert caps == [{"kind": "proxy_cap", "platform": "Oxy", "proxy_id": 3, "error": "Stopped: Oxy reached 90%."}]
        main._drop_proxy_cap_bell(3)
        assert not [a for a in main._collector_alerts if a.get("kind") == "proxy_cap"]


# ---------------------------------------------------------------------------
# Egress: proxied copies live on the proxy's exit IP, not the box's
# ---------------------------------------------------------------------------


def _worker(wid, own_ip, running=(), proxied=()):
    return {
        "id": wid,
        "name": f"w{wid}",
        "containers": [{"slug": s, "status": "running"} for s in running],
        "system_info": {"egress_ip": own_ip, "proxied": list(proxied)},
    }


def _copy(slug, proxy_id, ip, status="running"):
    return {"slug": slug, "proxy_id": proxy_id, "exit_ip": ip, "status": status}


class TestEgress:
    def test_a_proxied_copy_is_not_a_copy_on_the_box(self):
        w = _worker(1, "203.0.113.200", running=["honeygain"], proxied=[_copy("earnapp", 2, "93.184.215.14")])
        assert egress.running_slugs(w) == {"honeygain"}

    def test_groups_by_the_proxy_exit_and_keeps_the_invariants(self):
        workers = [
            _worker(1, "203.0.113.200", proxied=[_copy("a", 2, "93.184.215.14"), _copy("b", 3, "10.1.2.3")]),
            _worker(2, "203.0.113.201", proxied=[_copy("a", 2, "93.184.215.14"), _copy("c", 4, None)]),
            _worker(3, "203.0.113.202", proxied=[_copy("d", 5, "93.184.215.99"), _copy("e", 2, "1.1.1.1", "exited")]),
        ]
        groups = proxies.proxy_exits(workers, rotating_ids={5})
        known = [g for g in groups if g["known"]]
        assert [(g["exit_ip"], len(g["members"]), g["shared"]) for g in known] == [("93.184.215.14", 2, True)]
        rotating = [g for g in groups if g.get("rotating")]
        assert [m["slug"] for m in rotating[0]["members"]] == ["d"]
        unknown = [g for g in groups if not g["known"] and not g.get("rotating")]
        assert sorted(m["slug"] for m in unknown[0]["members"]) == ["b", "c"]
        assert unknown[0]["shared"] is False

    def test_same_exit_finds_boxes_and_copies_but_never_on_an_unknown_exit(self):
        workers = [
            _worker(1, "93.184.215.14", running=["a"]),
            _worker(2, "203.0.113.201", proxied=[_copy("a", 2, "93.184.215.14"), _copy("a", 3, "192.168.1.5")]),
            # Undetected box egress: never "the same" as anything.
            _worker(3, None, running=["a"]),
        ]
        found = proxies.same_exit_copies(workers, "a", "93.184.215.14")
        assert found == ["w1 (its own connection)", "w2 (through proxy 2)"]
        assert proxies.same_exit_copies(workers, "a", None) == []
        assert proxies.same_exit_copies(workers, "a", "192.168.1.5") == []

    def test_a_redeployed_copy_does_not_match_itself(self):
        workers = [_worker(2, "203.0.113.201", proxied=[_copy("a", 2, "93.184.215.14")])]
        assert proxies.same_exit_copies(workers, "a", "93.184.215.14", itself=(2, 2)) == []
        assert proxies.same_exit_copies(workers, "a", "93.184.215.14", itself=(3, 2)) == ["w2 (through proxy 2)"]


# ---------------------------------------------------------------------------
# Storage and routes, against a real database
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"),
    ):
        yield tmp_path


def _run(fn):
    async def go():
        await database.init_db()
        try:
            return await fn()
        finally:
            await database.close_shared()

    return asyncio.run(go())


class _Req:
    def __init__(self, body):
        self._body = body
        self.url = MagicMock(path="/api/proxies")

    async def json(self):
        return self._body


class TestStorageAndRoutes:
    def test_secrets_never_reach_the_database_file_in_plaintext(self, db):
        async def go():
            await main.api_create_proxy(_Req(_socks(username=USERNAME, password=PASSWORD)), {})

        _run(go)
        blobs = b"".join(p.read_bytes() for p in db.iterdir() if p.name.startswith("cashpilot.db"))
        assert b"proxies" in blobs, "the table is not in the file, so the check below proves nothing"
        assert PASSWORD.encode() not in blobs and USERNAME.encode() not in blobs

    def test_create_and_list_return_no_secret(self, db):
        async def go():
            created = await main.api_create_proxy(_Req(_socks(username=USERNAME, password=PASSWORD)), {})
            with patch.object(main.database, "list_workers", new_callable=AsyncMock, return_value=[]):
                listed = await main.api_list_proxies(MagicMock(), {})
            stored = await database.get_proxy(created["id"])
            return created, listed, stored

        created, listed, stored = _run(go)
        text = json.dumps([created, listed])
        assert PASSWORD not in text and USERNAME not in text
        assert stored["definition"]["password"] == PASSWORD

    def test_a_proxy_with_copies_is_not_deleted(self, db):
        async def go():
            created = await main.api_create_proxy(_Req(_socks()), {})
            await database.save_proxied_copy(created["id"], 7, "honeygain")
            with pytest.raises(HTTPException) as err:
                await main.api_delete_proxy(created["id"], {})
            return err.value.status_code

        assert _run(go) == 409

    def test_a_copy_needs_a_deployment_on_that_worker(self, db):
        svc = {"slug": "honeygain", "name": "Honeygain", "status": "active", "docker": {"image": "x"}}

        async def go():
            created = await main.api_create_proxy(_Req(_socks()), {})
            with (
                patch.object(main.catalog, "get_service", return_value=svc),
                patch.object(main, "_resolve_worker_id", new_callable=AsyncMock, return_value=7),
                patch.object(main, "_worker_features", new_callable=AsyncMock, return_value={"proxy_tunnel"}),
                pytest.raises(HTTPException) as err,
            ):
                await main.api_add_proxied_copy(created["id"], main.ProxyCopyRequest(worker_id=7, slug="honeygain"), {})
            return err.value.status_code

        assert _run(go) == 409

    def test_an_old_worker_is_refused(self, db):
        svc = {"slug": "honeygain", "name": "Honeygain", "status": "active", "docker": {"image": "x"}}

        async def go():
            created = await main.api_create_proxy(_Req(_socks()), {})
            with (
                patch.object(main.catalog, "get_service", return_value=svc),
                patch.object(main, "_resolve_worker_id", new_callable=AsyncMock, return_value=7),
                patch.object(main, "_worker_features", new_callable=AsyncMock, return_value={"instances"}),
                pytest.raises(HTTPException) as err,
            ):
                await main.api_add_proxied_copy(created["id"], main.ProxyCopyRequest(worker_id=7, slug="honeygain"), {})
            return err.value.status_code, err.value.detail

        status, detail = _run(go)
        assert status == 409 and "too old" in detail

    def test_a_copy_is_sent_from_the_recorded_spec_without_host_settings(self, db):
        svc = {
            "slug": "honeygain",
            "name": "Honeygain",
            "status": "active",
            "docker": {"image": "honeygain/honeygain:1", "env": [{"key": "DEVICE", "default": "cp-{hostname}"}]},
        }
        recorded = {"image": "honeygain/honeygain:1", "env": {"DEVICE": "cp-box", "EMAIL": "a@b"}, "ports": {}}
        call = AsyncMock(return_value={"status": "deployed", "exit": {"ip": "93.184.215.14", "country": "ES"}})

        async def go():
            created = await main.api_create_proxy(_Req(_socks(username=USERNAME, password=PASSWORD)), {})
            with (
                patch.object(main.catalog, "get_service", return_value=svc),
                patch.object(main, "_resolve_worker_id", new_callable=AsyncMock, return_value=7),
                patch.object(main, "_worker_features", new_callable=AsyncMock, return_value={"proxy_tunnel"}),
                patch.object(main.database, "get_deployment_spec", new_callable=AsyncMock, return_value=recorded),
                patch.object(main.database, "list_workers", new_callable=AsyncMock, return_value=[]),
                patch.object(main, "_proxy_to_worker", call),
            ):
                result = await main.api_add_proxied_copy(
                    created["id"], main.ProxyCopyRequest(worker_id=7, slug="honeygain"), {}
                )
            return created["id"], result, await database.list_proxied_copies()

        pid, result, copies = _run(go)
        worker_id, method, path = call.call_args.args
        sent = call.call_args.kwargs["json"]
        assert (worker_id, method, path) == (7, "POST", f"/api/proxied/honeygain/{pid}/deploy")
        assert sent["earner"]["env"] == {"DEVICE": "cp-box-p" + str(pid), "EMAIL": "a@b"}
        assert "ports" not in sent["earner"]
        assert sent["proxy"]["password"] == PASSWORD
        assert result["exit_ip"] == "93.184.215.14" and PASSWORD not in json.dumps(result)
        assert copies == [
            {
                "proxy_id": pid,
                "worker_id": 7,
                "slug": "honeygain",
                "stopped_by_cap": 0,
                "created_at": copies[0]["created_at"],
            }
        ]

    def test_dropping_the_cap_lifts_the_stop_and_starts_the_copies(self, db):
        call = AsyncMock(return_value={})

        async def go():
            created = await main.api_create_proxy(_Req(_socks(cap_gb=1)), {})
            pid = created["id"]
            await database.save_proxied_copy(pid, 7, "honeygain")
            await database.set_proxied_copy_capped(pid, 7, "honeygain", True)
            await database.update_proxy_state(
                pid, {"used_bytes": 950_000_000, "capped_at": "2026-11-04T01:00:00+00:00", "cap_reason": "P hit"}
            )
            with patch.object(main, "_proxy_to_worker", call):
                view = await main.api_update_proxy(_Req({"cap_gb": ""}), pid, {})
            return pid, view, await database.list_proxied_copies(pid)

        pid, view, copies = _run(go)
        assert view["cap"]["capped_at"] is None and view["cap"]["enabled"] is False
        assert call.call_args.args[:3] == (7, "POST", f"/api/proxied/honeygain/{pid}/start")
        assert copies[0]["stopped_by_cap"] == 0

    def test_turning_the_cap_on_does_not_count_old_traffic(self, db):
        async def go():
            created = await main.api_create_proxy(_Req(_socks()), {})
            await database.update_proxy_state(created["id"], {"used_bytes": 40 * proxies.GB})
            return await main.api_update_proxy(_Req({"cap_gb": 20}), created["id"], {})

        view = _run(go)
        assert view["cap"]["used_bytes"] == 0 and view["cap"]["period_start"]

    def test_a_failed_test_is_kept_on_the_proxy(self, db):
        failing = AsyncMock(side_effect=HTTPException(status_code=409, detail=f"bad auth socks5://u:{PASSWORD}@h"))

        async def go():
            created = await main.api_create_proxy(_Req(_socks(password=PASSWORD)), {})
            with (
                patch.object(main, "_resolve_worker_id", new_callable=AsyncMock, return_value=7),
                patch.object(main, "_worker_features", new_callable=AsyncMock, return_value={"proxy_tunnel"}),
                patch.object(main.database, "get_worker", new_callable=AsyncMock, return_value={"name": "box-a"}),
                patch.object(main, "_proxy_to_worker", failing),
                pytest.raises(HTTPException),
            ):
                await main.api_test_proxy(created["id"], 7, {})
            with patch.object(main.database, "list_workers", new_callable=AsyncMock, return_value=[]):
                return (await main.api_list_proxies(MagicMock(), {}))["proxies"][0]

        view = _run(go)
        assert view["last_test"]["ok"] is False and view["last_test"]["worker"] == "box-a"
        assert "bad auth" in view["last_test"]["error"] and PASSWORD not in json.dumps(view)

    def test_a_copy_on_a_deleted_worker_can_be_removed(self, db):
        async def go():
            created = await main.api_create_proxy(_Req(_socks()), {})
            await database.save_proxied_copy(created["id"], 99, "honeygain")
            await main.api_remove_proxied_copy(created["id"], 99, "honeygain", {})
            await main.api_delete_proxy(created["id"], {})
            return await database.list_proxies()

        assert _run(go) == []

    def test_deleting_a_worker_deletes_its_proxied_copies(self, db):
        async def go():
            created = await main.api_create_proxy(_Req(_socks()), {})
            await database.save_proxied_copy(created["id"], 5, "honeygain")
            await database.save_proxied_copy(created["id"], 6, "honeygain")
            await database.delete_worker(5)
            return [c["worker_id"] for c in await database.list_proxied_copies()]

        assert _run(go) == [6]

    def test_removing_a_service_drops_the_records_of_its_proxied_copies(self, db):
        async def go():
            created = await main.api_create_proxy(_Req(_socks()), {})
            await database.save_proxied_copy(created["id"], 7, "honeygain")
            await database.save_proxied_copy(created["id"], 7, "earnapp")
            await database.save_proxied_copy(created["id"], 8, "honeygain")
            with (
                patch.object(main, "_require_writer"),
                patch.object(main, "_resolve_worker_id", new_callable=AsyncMock, return_value=7),
                patch.object(main, "_proxy_worker_command", new_callable=AsyncMock, return_value={"status": "ok"}),
            ):
                await main._svc_remove(MagicMock(), "honeygain", 7, False)
            return sorted((c["worker_id"], c["slug"]) for c in await database.list_proxied_copies())

        assert _run(go) == [(7, "earnapp"), (8, "honeygain")]

    def test_a_worker_error_never_shows_the_proxy_password(self):
        definition = {"password": PASSWORD}
        failing = AsyncMock(side_effect=HTTPException(status_code=409, detail=f"refused socks5://u:{PASSWORD}@h"))
        with patch.object(main, "_proxy_to_worker", failing), pytest.raises(HTTPException) as err:
            asyncio.run(main._proxy_worker_call(7, "POST", "/x", definition))
        assert PASSWORD not in str(err.value.detail)


def _slow_first_read():
    """Patch get_proxy so its first caller holds a stale read while the others run."""
    real = database.get_proxy
    calls = {"n": 0}

    async def get_proxy(pid):
        calls["n"] += 1
        first = calls["n"] == 1
        proxy = await real(pid)
        await asyncio.sleep(0.2 if first else 0)
        return proxy

    return patch.object(main.database, "get_proxy", side_effect=get_proxy)


def _discard_spawn(coro):
    coro.close()


class TestProxyStateWriters:
    """Every read-modify-write of proxies.state runs one at a time per proxy."""

    def test_two_heartbeats_at_once_both_count(self, db):
        async def go():
            created = await main.api_create_proxy(_Req(_socks(cap_gb=10)), {})
            pid = created["id"]
            await database.save_proxied_copy(pid, 7, "a")
            await database.save_proxied_copy(pid, 8, "a")
            hb = [{**_entry(500_000_000, 0), "proxy_id": pid}]
            with _slow_first_read():
                await asyncio.gather(main._account_proxy_traffic(7, hb), main._account_proxy_traffic(8, hb))
            return (await database.get_proxy(pid))["state"]["used_bytes"]

        assert _run(go) == 1_000_000_000

    def test_a_reset_during_a_heartbeat_sticks(self, db):
        async def go():
            created = await main.api_create_proxy(_Req(_socks(cap_gb=1)), {})
            pid = created["id"]
            await database.update_proxy_state(
                pid,
                {
                    "used_bytes": 950_000_000,
                    "capped_at": "2026-11-04T01:00:00+00:00",
                    "cap_reason": "P hit",
                    "counters": {"7:t1": [1000, 0, 100.0, "2026-11-01T00:00:00Z"]},
                },
            )
            hb = [{**_entry(2100, 0), "proxy_id": pid}]
            proxy = await database.get_proxy(pid)
            with _slow_first_read(), patch.object(main, "_spawn", side_effect=_discard_spawn):
                await asyncio.gather(main._account_proxy_traffic(7, hb), main._reset_proxy(proxy))
            return (await database.get_proxy(pid))["state"]

        state = _run(go)
        assert "capped_at" not in state
        assert state["used_bytes"] in (0, 1100)

    def test_lifting_the_cap_during_a_heartbeat_sticks(self, db):
        async def go():
            created = await main.api_create_proxy(_Req(_socks(cap_gb=1)), {})
            pid = created["id"]
            await database.update_proxy_state(
                pid,
                {
                    "used_bytes": 950_000_000,
                    "capped_at": "2026-11-04T01:00:00+00:00",
                    "cap_reason": "P hit",
                    "counters": {"7:t1": [1000, 0, 100.0, "2026-11-01T00:00:00Z"]},
                },
            )
            await database.save_proxied_copy(pid, 7, "a")
            hb = [{**_entry(2100, 0), "proxy_id": pid}]
            with _slow_first_read(), patch.object(main, "_spawn", side_effect=_discard_spawn):
                await asyncio.gather(
                    main._account_proxy_traffic(7, hb), main.api_update_proxy(_Req({"cap_gb": ""}), pid, {})
                )
            return await database.get_proxy(pid)

        proxy = _run(go)
        assert proxy["definition"].get("cap_gb") is None
        assert "capped_at" not in proxy["state"]
        assert proxy["state"]["used_bytes"] == 950_001_100


class TestValidationEcho:
    def test_a_422_on_a_proxy_route_does_not_echo_the_body(self):
        from contextlib import asynccontextmanager

        from fastapi.testclient import TestClient

        @asynccontextmanager
        async def _noop(a):
            yield

        main.app.router.lifespan_context = _noop
        with patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "admin", "r": "owner"}):
            resp = TestClient(main.app, raise_server_exceptions=False).post(
                "/api/proxies/1/copies", json=[PASSWORD, USERNAME]
            )
        assert resp.status_code == 422
        assert PASSWORD not in resp.text


class TestReviewFollowUps:
    """Fixes from the review of the proxied-copies work."""

    SVC = {"slug": "honeygain", "name": "Honeygain", "status": "active", "docker": {"image": "honeygain/honeygain:1"}}
    RECORDED = {"image": "honeygain/honeygain:1", "env": {"EMAIL": "a@b"}, "ports": {}}

    def _add(self, created_id, call):
        return (
            patch.object(main.catalog, "get_service", return_value=self.SVC),
            patch.object(main, "_resolve_worker_id", new_callable=AsyncMock, return_value=7),
            patch.object(main, "_worker_features", new_callable=AsyncMock, return_value={"proxy_tunnel"}),
            patch.object(main.database, "get_deployment_spec", new_callable=AsyncMock, return_value=self.RECORDED),
            patch.object(main.database, "list_workers", new_callable=AsyncMock, return_value=[]),
            patch.object(main, "_proxy_to_worker", call),
        )

    @pytest.mark.parametrize(("status", "kept"), [(504, True), (409, False)])
    def test_a_deploy_whose_outcome_is_unknown_keeps_its_record(self, db, status, kept):
        """A 504 means the worker may still finish the copy; without a record
        it would run outside the cap and the delete guard."""
        call = AsyncMock(side_effect=HTTPException(status_code=status, detail="x"))

        async def go():
            created = await main.api_create_proxy(_Req(_socks()), {})
            a, b, c, d, e, f = self._add(created["id"], call)
            with a, b, c, d, e, f, pytest.raises(HTTPException):
                await main.api_add_proxied_copy(created["id"], main.ProxyCopyRequest(worker_id=7, slug="honeygain"), {})
            return await database.list_proxied_copies()

        assert bool(_run(go)) is kept

    def test_a_copy_being_added_blocks_deleting_its_proxy(self, db):
        async def go():
            created = await main.api_create_proxy(_Req(_socks()), {})
            pid = created["id"]

            async def slow_deploy(*a, **kw):
                with pytest.raises(HTTPException) as err:
                    await main.api_delete_proxy(pid, {})
                return {"status": "deployed", "exit": {}, "delete": err.value.status_code}

            a, b, c, d, e, f = self._add(pid, AsyncMock(side_effect=slow_deploy))
            with a, b, c, d, e, f:
                await main.api_add_proxied_copy(pid, main.ProxyCopyRequest(worker_id=7, slug="honeygain"), {})
            return await database.get_proxy(pid)

        assert _run(go) is not None

    def test_traffic_of_a_copy_this_worker_has_no_record_of_is_not_counted(self, db):
        async def go():
            created = await main.api_create_proxy(_Req(_socks(cap_gb=1)), {})
            pid = created["id"]
            await database.save_proxied_copy(pid, 8, "a")
            await main._account_proxy_traffic(7, [{**_entry(2_000_000_000, 0), "proxy_id": pid}])
            first = (await database.get_proxy(pid))["state"].get("used_bytes")
            await main._account_proxy_traffic(8, [{**_entry(1000, 0, tid="t8"), "proxy_id": pid}])
            return first, (await database.get_proxy(pid))["state"]

        first, state = _run(go)
        assert first == 0
        assert state["used_bytes"] == 1000 and "capped_at" not in state

    def test_a_new_proxy_with_a_reset_day_starts_its_period(self, db):
        async def go():
            created = await main.api_create_proxy(_Req(_socks(cap_gb=1, reset_day=1)), {})
            return await database.get_proxy(created["id"])

        proxy = _run(go)
        assert proxy["state"]["period_start"]
        assert not proxies.reset_due(proxy["definition"], proxy["state"], date.today())

    def test_a_start_by_hand_sends_the_proxy_as_stored_now(self, db):
        call = AsyncMock(return_value={"status": "started"})

        async def go():
            created = await main.api_create_proxy(_Req(_socks(username=USERNAME, password=PASSWORD)), {})
            pid = created["id"]
            await main.api_update_proxy(_Req({"password": "n3w-pass"}), pid, {})
            with patch.object(main, "_proxy_to_worker", call):
                await main.api_proxied_copy_command(pid, 7, "honeygain", "start", {})
                await main.api_proxied_copy_command(pid, 7, "honeygain", "stop", {})

        _run(go)
        start, stop = call.call_args_list
        assert start.kwargs["json"]["proxy"]["password"] == "n3w-pass"
        assert stop.kwargs["json"] is None

    def test_removing_a_service_keeps_records_of_copies_that_survived(self, db):
        async def go():
            created = await main.api_create_proxy(_Req(_socks()), {})
            await database.save_proxied_copy(created["id"], 7, "honeygain")
            answer = {"status": "removed", "proxied_error": "Docker did not remove cashpilot-honeygain-p1"}
            with (
                patch.object(main, "_require_writer"),
                patch.object(main, "_resolve_worker_id", new_callable=AsyncMock, return_value=7),
                patch.object(main, "_proxy_worker_command", new_callable=AsyncMock, return_value=answer),
            ):
                await main._svc_remove(MagicMock(), "honeygain", 7, False)
            return await database.list_proxied_copies()

        assert len(_run(go)) == 1

    @pytest.mark.parametrize(
        "server",
        ["https://u:p@hs.example", "https://hs.example/?token=x", "https://hs.example/#f", "http://hs.example"],
    )
    def test_a_login_server_with_a_secret_part_is_refused(self, server):
        with pytest.raises(proxies.ProxyInputError):
            proxies.clean_definition(
                {"name": "T", "kind": "tailscale", "auth_key": "k", "exit_node": "exit-1", "login_server": server}
            )

    def test_a_plain_login_server_is_kept(self):
        d = proxies.clean_definition(
            {
                "name": "T",
                "kind": "tailscale",
                "auth_key": "k",
                "exit_node": "e",
                "login_server": "https://hs.example:8443/x",
            }
        )
        assert d["login_server"] == "https://hs.example:8443/x"
