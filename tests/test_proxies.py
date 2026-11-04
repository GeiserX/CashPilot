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
            proxies.clean_definition({"name": "Fran", "kind": "tailscale", "exit_node": "macbook"})
        d = proxies.clean_definition(
            {"name": "Fran", "kind": "tailscale", "auth_key": AUTH_KEY, "exit_node": "macbook-pro-de-francisco"}
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


def _entry(rx, tx, tid="t1", ip="93.184.215.14"):
    return {"proxy_id": 1, "tunnel_container_id": tid, "net_rx_bytes": rx, "net_tx_bytes": tx, "exit_ip": ip}


CAPPED = {"name": "P", "cap_gb": 1, "cap_threshold_pct": 90, "reset_day": 1}


class TestCap:
    def test_first_reading_is_a_baseline_then_deltas_count(self):
        s, crossed = proxies.account({}, CAPPED, 7, [_entry(1000, 500)], 100.0)
        assert s["used_bytes"] == 0 and not crossed
        s, crossed = proxies.account(s, CAPPED, 7, [_entry(4000, 1500)], 160.0)
        assert s["used_bytes"] == 4000 and not crossed

    def test_a_counter_that_went_backwards_is_a_restart(self):
        s, _ = proxies.account({}, CAPPED, 7, [_entry(1000, 0)], 100.0)
        s, _ = proxies.account(s, CAPPED, 7, [_entry(300, 0)], 160.0)
        assert s["used_bytes"] == 300

    def test_a_stale_baseline_counts_nothing_for_the_gap(self):
        s, _ = proxies.account({}, CAPPED, 7, [_entry(1000, 0)], 100.0)
        s, _ = proxies.account(s, CAPPED, 7, [_entry(9_000_000, 0)], 100.0 + 7200)
        assert s["used_bytes"] == 0

    def test_two_workers_never_share_a_baseline(self):
        s, _ = proxies.account({}, CAPPED, 7, [_entry(1000, 0)], 100.0)
        s, _ = proxies.account(s, CAPPED, 8, [_entry(5000, 0)], 110.0)
        assert s["used_bytes"] == 0

    def test_crossing_the_threshold_says_why_once(self):
        s, _ = proxies.account({}, CAPPED, 7, [_entry(0, 0)], 100.0)
        s, crossed = proxies.account(s, CAPPED, 7, [_entry(900_000_000, 0)], 160.0)
        assert crossed and s["capped_at"]
        assert "90% of its 1 GB cap" in s["cap_reason"] and "day 1" in s["cap_reason"]
        s, again = proxies.account(s, CAPPED, 7, [_entry(950_000_000, 0)], 220.0)
        assert not again

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
        proxy = {"id": 1, "definition": {**CAPPED, "password": PASSWORD}, "state": {"cap_reason": "P reached 90%"}}
        copies = [{"proxy_id": 1, "worker_id": 7, "slug": "a"}, {"proxy_id": 1, "worker_id": 8, "slug": "b"}]
        call = AsyncMock(return_value={})
        with (
            patch.object(main.database, "list_proxied_copies", new_callable=AsyncMock, return_value=copies),
            patch.object(main.database, "set_proxied_copy_capped", new_callable=AsyncMock) as mark,
            patch.object(main.database, "record_alert", new_callable=AsyncMock) as alert,
            patch.object(main, "_proxy_worker_call", call),
        ):
            asyncio.run(main._stop_capped_proxy(proxy))
        assert [c.args[2] for c in call.call_args_list] == ["/api/proxied/a/1/stop", "/api/proxied/b/1/stop"]
        assert all(c.args[3] is True for c in mark.call_args_list) and mark.call_count == 2
        assert alert.call_args.args[:2] == ("proxy_cap", "1")


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

    def test_a_worker_error_never_shows_the_proxy_password(self):
        definition = {"password": PASSWORD}
        failing = AsyncMock(side_effect=HTTPException(status_code=409, detail=f"refused socks5://u:{PASSWORD}@h"))
        with patch.object(main, "_proxy_to_worker", failing), pytest.raises(HTTPException) as err:
            asyncio.run(main._proxy_worker_call(7, "POST", "/x", definition))
        assert PASSWORD not in str(err.value.detail)


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
