"""The payouts page and the dashboard say where each service runs, from the workers.

Seen live on 2026-10-30: the payouts page called bytelixir, grass, titan and
uprock deployed because CashPilot's deployments table had rows for them, while
no server ran a container for any of them (three ran on phones, one nowhere).
It said "Not set" for the Mysterium and Anyone wallets, both of which were set
on every box, because they are set inside the container and the UI never
looked. And nothing warned about a recorded deployment no box ran.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest
from fastapi.testclient import TestClient

from app import main, payout_read, payout_registry, placement

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
WALLET_A = "0x" + "a" * 40
WALLET_B = "0x" + "b" * 40


def _docker(wid, name, containers, *, status="online", docker=True):
    return {
        "id": wid,
        "name": name,
        "status": status,
        "system_info": json.dumps({"docker_available": docker}),
        "containers": json.dumps([{"slug": s, "status": st} for s, st in containers]),
        "apps": "[]",
    }


def _phone(wid, name, apps, *, status="online"):
    # What CashPilot-android 0.3.0 really sends: os, no device_type.
    return {
        "id": wid,
        "name": name,
        "status": status,
        "system_info": json.dumps({"os": "Android", "version": "0.3.0"}),
        "containers": json.dumps([{"slug": s, "status": "running"} for s, _ in apps]),
        "apps": json.dumps([{"slug": s, "running": r} for s, r in apps]),
    }


def _sql(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Where a service runs
# ---------------------------------------------------------------------------


class TestPhonesAreRecognised:
    def test_the_android_client_without_device_type_is_a_phone(self):
        assert placement.is_android({"os": "Android"}) is True
        assert placement.is_android({"device_type": "android"}) is True

    def test_control_a_linux_host_is_not(self):
        assert placement.is_android({"os": "Linux", "docker_available": True}) is False

    def test_a_phone_does_not_switch_off_the_missing_container_check(self):
        """It did: the phone read as a Docker host that cannot see its socket."""
        workers = [_docker(1, "watchtower", []), _phone(2, "OPPO", [("grass", True)])]
        found = placement.missing(
            [{"slug": "storj", "status": "running", "deployed_at": _sql(NOW - timedelta(days=3))}],
            [],
            workers,
            now=NOW,
            first_missing={("storj", None): NOW - timedelta(hours=1)},
        )
        assert found is not None and "storj" in found


class TestRunsOn:
    def test_lists_every_box_that_reports_it_with_its_status(self):
        workers = [
            _docker(1, "watchtower", [("mysterium", "running")]),
            _docker(2, "geiserct", [("mysterium", "exited")]),
            _docker(3, "geiserback", [("mysterium", "running")], status="offline"),
            _phone(4, "OPPO", [("grass", True), ("titan", None)]),
        ]
        where = placement.runs_on(workers)
        assert [(r["name"], r["status"], r["online"]) for r in where["mysterium"]] == [
            ("geiserback", "running", False),
            ("geiserct", "exited", True),
            ("watchtower", "running", True),
        ]
        assert where["grass"][0]["android"] is True
        assert where["titan"][0]["status"] == "unknown"

    def test_two_copies_on_one_box_are_one_box_and_running_wins(self):
        workers = [_docker(1, "watchtower", [("earnapp", "exited"), ("earnapp", "running")])]
        assert placement.runs_on(workers)["earnapp"] == [
            {"worker_id": 1, "name": "watchtower", "online": True, "android": False, "status": "running"}
        ]


# ---------------------------------------------------------------------------
# Recorded deployments no box runs
# ---------------------------------------------------------------------------


class TestMissing:
    @staticmethod
    def _run(deployments, specs, workers, first, now=NOW):
        return placement.missing(deployments, specs, workers, now=now, first_missing=first)

    def test_a_recorded_container_no_box_runs_is_reported_after_the_grace(self):
        deps = [{"slug": "bitping", "status": "running", "deployed_at": _sql(NOW - timedelta(days=9))}]
        workers = [_docker(1, "watchtower", [("honeygain", "running")])]
        first: dict = {}
        assert self._run(deps, [], workers, first) == {}, "inside the grace on first sight"
        later = NOW + placement.MISSING_GRACE
        found = self._run(deps, [], workers, first, now=later)
        assert found == {"bitping": {"everywhere": True, "boxes": [], "still_on": []}}

    def test_a_fresh_redeploy_gets_the_full_grace(self):
        deps = [{"slug": "bitping", "status": "running", "deployed_at": _sql(NOW - timedelta(minutes=5))}]
        first = {("bitping", None): NOW - timedelta(hours=2)}
        assert self._run(deps, [], [_docker(1, "watchtower", [])], first) == {}

    def test_credentials_only_rows_are_not_alerts(self):
        """uprock: tracked for its balance, runs on something CashPilot never deployed."""
        deps = [{"slug": "uprock", "status": "external", "deployed_at": _sql(NOW - timedelta(days=200))}]
        first = {("uprock", None): NOW - timedelta(days=1)}
        assert self._run(deps, [], [_docker(1, "watchtower", [])], first) == {}

    def test_a_box_that_no_longer_runs_its_deployment_is_named(self):
        specs = [
            {"slug": "earnapp", "worker_id": 1, "deployed_at": _sql(NOW - timedelta(days=2))},
            {"slug": "earnapp", "worker_id": 2, "deployed_at": _sql(NOW - timedelta(days=2))},
        ]
        deps = [{"slug": "earnapp", "status": "running", "deployed_at": _sql(NOW - timedelta(days=2))}]
        workers = [_docker(1, "watchtower", [("earnapp", "running")]), _docker(2, "geiserct", [])]
        first = {("earnapp", 2): NOW - timedelta(hours=1)}
        found = self._run(deps, specs, workers, first)
        assert found == {
            "earnapp": {
                "everywhere": False,
                "boxes": [{"worker_id": 2, "name": "geiserct"}],
                "still_on": ["watchtower"],
            }
        }

    def test_an_offline_box_is_not_called_missing(self):
        """Its containers may well be running; it has its own offline alert."""
        specs = [{"slug": "storj", "worker_id": 2, "deployed_at": _sql(NOW - timedelta(days=30))}]
        deps = [{"slug": "storj", "status": "running", "deployed_at": _sql(NOW - timedelta(days=30))}]
        workers = [_docker(1, "watchtower", []), _docker(2, "geiserback", [("storj", "running")], status="offline")]
        first = {("storj", 2): NOW - timedelta(hours=3), ("storj", None): NOW - timedelta(hours=3)}
        assert self._run(deps, specs, workers, first) == {}

    def test_a_blind_docker_host_means_the_fleet_cannot_tell(self):
        deps = [{"slug": "bitping", "status": "running", "deployed_at": _sql(NOW - timedelta(days=9))}]
        workers = [_docker(1, "watchtower", []), _docker(2, "geiserct", [], docker=False)]
        assert self._run(deps, [], workers, {("bitping", None): NOW - timedelta(hours=2)}) is None

    def test_no_worker_online_means_the_fleet_cannot_tell(self):
        deps = [{"slug": "bitping", "status": "running"}]
        assert self._run(deps, [], [_docker(1, "watchtower", [], status="offline")], {}) is None

    def test_coming_back_resets_the_clock(self):
        first = {("bitping", None): NOW - timedelta(hours=2)}
        deps = [{"slug": "bitping", "status": "running"}]
        assert self._run(deps, [], [_docker(1, "watchtower", [("bitping", "running")])], first) == {}
        assert first == {}


class _Alerts:
    def __init__(self):
        self.rows: dict[str, str] = {}
        self.pushed: list[str] = []

    async def record(self, kind, subject, message, **_):
        assert kind == "missing"
        new = subject not in self.rows
        self.rows[subject] = message
        return len(self.rows) if new else None

    async def subjects(self, kind):
        return set(self.rows) if kind == "missing" else set()

    async def clear(self, kind=None, subject=None):
        self.rows.pop(subject, None)

    def patches(self, deployments, specs):
        def spawn(coro):
            coro.close()
            self.pushed.append("push")

        return (
            patch.object(main.database, "record_alert", self.record),
            patch.object(main.database, "get_alert_subjects", self.subjects),
            patch.object(main.database, "clear_alerts", self.clear),
            patch.object(main.database, "get_deployments", AsyncMock(return_value=deployments)),
            patch.object(main.database, "list_deployment_placements", AsyncMock(return_value=specs)),
            patch.object(main, "_spawn", spawn),
        )


@pytest.fixture
def _clean_main(monkeypatch):
    monkeypatch.setattr(main, "_deployment_first_missing", {})
    monkeypatch.setattr(main, "_missing_bell", {})
    monkeypatch.setattr(main, "_collector_alerts", [])


@pytest.mark.usefixtures("_clean_main")
class TestTheAlert:
    def _check(self, alerts, deployments, specs, workers):
        p = alerts.patches(deployments, specs)
        with p[0], p[1], p[2], p[3], p[4], p[5]:
            asyncio.run(main._missing_deployment_check(workers))

    def test_it_reaches_the_bell_and_the_push_path_once(self):
        deps = [{"slug": "bitping", "status": "running", "deployed_at": "2026-01-01 00:00:00"}]
        workers = [_docker(1, "watchtower", [])]
        main._deployment_first_missing[("bitping", None)] = datetime.now(UTC) - timedelta(hours=1)
        alerts = _Alerts()
        self._check(alerts, deps, [], workers)
        self._check(alerts, deps, [], workers)
        assert "bitping" in alerts.rows and alerts.pushed == ["push"]
        bell = [a for a in main._collector_alerts if a["kind"] == "missing"]
        assert len(bell) == 1 and bell[0]["everywhere"] is True
        assert "no box runs it" in bell[0]["error"]

    def test_it_clears_when_a_box_runs_it_again(self):
        alerts = _Alerts()
        alerts.rows["bitping"] = "old"
        main._missing_bell["bitping"] = {"kind": "missing", "platform": "bitping", "error": "old"}
        deps = [{"slug": "bitping", "status": "running"}]
        self._check(alerts, deps, [], [_docker(1, "watchtower", [("bitping", "running")])])
        assert alerts.rows == {} and main._missing_bell == {}
        assert not [a for a in main._collector_alerts if a["kind"] == "missing"]

    def test_unknown_fleet_neither_raises_nor_clears(self):
        alerts = _Alerts()
        alerts.rows["bitping"] = "old"
        deps = [{"slug": "bitping", "status": "running"}]
        self._check(alerts, deps, [], [_docker(1, "watchtower", [], docker=False)])
        assert alerts.rows == {"bitping": "old"}

    def test_a_restart_keeps_it_in_the_bell(self):
        """The stored row is restored like a container-down alert."""
        stored = [{"kind": "missing", "subject": "bitping", "message": "runs nowhere"}]
        with patch.object(main.database, "list_alerts", AsyncMock(return_value=stored)):
            asyncio.run(main._warm_collector_alerts())
        assert {"kind": "missing", "platform": "bitping", "error": "runs nowhere"} in main._collector_alerts


@asynccontextmanager
async def _noop_lifespan(a):
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main.app.router, "lifespan_context", _noop_lifespan)
    with TestClient(main.app, raise_server_exceptions=False) as c:
        yield c


def _as(role):
    return patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "x", "r": role})


@pytest.mark.usefixtures("_clean_main")
class TestForgettingIsTheWayOut:
    def test_forget_drops_every_record_and_clears_the_alert(self, client):
        alerts = _Alerts()
        alerts.rows["bitping"] = "runs nowhere"
        main._missing_bell["bitping"] = {"kind": "missing", "platform": "bitping", "error": "x"}
        main._collector_alerts.append(main._missing_bell["bitping"])
        forget = AsyncMock()
        p = alerts.patches([], [])
        with (
            _as("writer"),
            p[0],
            p[1],
            p[2],
            p[3],
            p[4],
            p[5],
            patch.object(main.database, "list_workers", AsyncMock(return_value=[_docker(1, "watchtower", [])])),
            patch.object(main.database, "forget_deployment", forget),
            patch.object(main.database, "get_deployment", AsyncMock(return_value=None)),
        ):
            resp = client.delete("/api/deployments/bitping")
        assert resp.status_code == 200, resp.text
        forget.assert_awaited_once_with("bitping")
        assert alerts.rows == {} and main._missing_bell == {} and main._collector_alerts == []

    def test_it_refuses_while_a_box_still_runs_it(self, client):
        forget = AsyncMock()
        with (
            _as("owner"),
            patch.object(
                main.database,
                "list_workers",
                AsyncMock(return_value=[_docker(1, "watchtower", [("bitping", "running")])]),
            ),
            patch.object(main.database, "forget_deployment", forget),
            patch.object(main.database, "list_deployment_placements", AsyncMock(return_value=[])),
        ):
            resp = client.delete("/api/deployments/bitping")
        assert resp.status_code == 409 and "watchtower" in resp.text
        forget.assert_not_awaited()

    def test_one_box_forgets_only_that_box(self, client):
        remove = AsyncMock()
        p = _Alerts().patches([], [])
        with (
            _as("writer"),
            p[0],
            p[1],
            p[2],
            p[3],
            p[4],
            p[5],
            patch.object(
                main.database,
                "list_workers",
                AsyncMock(
                    return_value=[_docker(1, "watchtower", [("earnapp", "running")]), _docker(2, "geiserct", [])]
                ),
            ),
            patch.object(main.database, "remove_deployment", remove),
            patch.object(main.database, "get_deployment", AsyncMock(return_value=None)),
        ):
            resp = client.delete("/api/deployments/earnapp?worker_id=2")
        assert resp.status_code == 200, resp.text
        remove.assert_awaited_once_with("earnapp", worker_id=2)

    def test_a_viewer_cannot(self, client):
        with _as("viewer"):
            assert client.delete("/api/deployments/bitping").status_code == 403


class TestTheRealForgetDeployment:
    def test_it_drops_the_fleet_row_and_every_box_record(self, tmp_path):
        from app import database

        async def go():
            await database.init_db()
            await database.save_deployment("storj", "c1", spec={"env": {}}, worker_id=1)
            await database.save_deployment("storj", "c2", spec={"env": {}}, worker_id=2)
            before = [r for r in await database.list_deployment_placements() if r["slug"] == "storj"]
            await database.forget_deployment("storj")
            after = [r for r in await database.list_deployment_placements() if r["slug"] == "storj"]
            return before, after, await database.get_deployment("storj")

        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "t.db"):
            before, after, row = asyncio.run(go())
        assert len(before) == 2 and after == [] and row is None


# ---------------------------------------------------------------------------
# The registry: runs on, and addresses set outside CashPilot
# ---------------------------------------------------------------------------


def _registry(deployments, workers, *, spec=None, specs=None, read=None):
    specs = specs or {}

    async def get_spec(slug, worker_id=None):
        if worker_id is None:
            return spec
        return specs.get((slug, worker_id))

    with (
        patch.object(payout_registry.database, "get_deployments", AsyncMock(return_value=deployments)),
        patch.object(payout_registry.database, "list_workers", AsyncMock(return_value=workers)),
        patch.object(payout_registry.database, "get_deployment_spec", get_spec),
    ):
        return asyncio.run(payout_registry.registry(read_addresses=read))


def _row(result, slug):
    return next(r for r in result["entries"] if r["slug"] == slug)


class TestTheRegistry:
    def test_deployed_means_a_box_runs_it_not_that_a_row_exists(self):
        deps = [{"slug": "bitping", "status": "running"}, {"slug": "grass", "status": "external"}]
        workers = [_docker(1, "watchtower", [("honeygain", "running")]), _phone(2, "OPPO", [("grass", True)])]
        result = _registry(deps, workers)
        bitping, grass, honeygain = _row(result, "bitping"), _row(result, "grass"), _row(result, "honeygain")
        assert bitping["deployed"] is False and bitping["recorded"] is True
        assert grass["deployed"] is True and [b["name"] for b in grass["runs_on"]] == ["OPPO"]
        assert honeygain["deployed"] is True and honeygain["recorded"] is False
        assert result["summary"]["recorded_not_running"] == 1

    def test_a_credentials_only_row_nothing_reports_is_not_counted_as_runs_nowhere(self):
        result = _registry([{"slug": "uprock", "status": "external"}], [_docker(1, "watchtower", [])])
        uprock = _row(result, "uprock")
        assert uprock["tracked_only"] is True and uprock["deployed"] is False
        assert result["summary"]["recorded_not_running"] == 0

    def test_a_wallet_set_inside_the_container_is_read_from_each_box(self):
        workers = [
            _docker(1, "watchtower", [("mysterium", "running")]),
            _docker(2, "geiserct", [("mysterium", "running")]),
        ]

        async def read(worker_id):
            return [{"slug": "mysterium", "instance": 1, "address": WALLET_A}]

        mysterium = _row(_registry([{"slug": "mysterium", "status": "running"}], workers, read=read), "mysterium")
        assert mysterium["address"] == WALLET_A
        assert mysterium["addresses"] == [{"address": WALLET_A, "servers": ["geiserct", "watchtower"]}]
        assert mysterium["address_missing"] is False and mysterium["address_unchecked"] is None

    def test_a_manual_wallet_that_could_not_be_read_is_not_checked_never_not_set(self):
        """The old code said "Not set" for Mysterium and Anyone on every box."""
        workers = [_docker(1, "watchtower", [("mysterium", "running"), ("anyone-protocol", "running")])]

        async def read(worker_id):
            raise RuntimeError("404 from an older worker")

        result = _registry([], workers, read=read)
        for slug in ("mysterium", "anyone-protocol"):
            row = _row(result, slug)
            assert row["address_missing"] is False, slug
            assert row["address_unchecked"] == "outside", slug
        assert result["summary"]["needs_an_address"] == 0

    def test_a_wallet_linked_in_the_provider_app_is_not_checked(self):
        result = _registry([], [_docker(1, "watchtower", [("urnetwork", "running")])])
        urnetwork = _row(result, "urnetwork")
        assert urnetwork["address_missing"] is False and urnetwork["address_unchecked"] == "app"

    def test_boxes_with_different_wallets_are_shown_apart(self):
        workers = [_docker(1, "watchtower", [("storj", "running")]), _docker(2, "geiserback", [("storj", "running")])]
        specs = {
            ("storj", 1): {"env": {"WALLET": WALLET_A}},
            ("storj", 2): {"env": {"WALLET": WALLET_B}},
        }
        storj = _row(_registry([{"slug": "storj", "status": "running"}], workers, specs=specs), "storj")
        assert storj["address"] is None
        assert storj["addresses"] == [
            {"address": WALLET_A, "servers": ["watchtower"]},
            {"address": WALLET_B, "servers": ["geiserback"]},
        ]
        assert storj["address_missing"] is False

    def test_a_box_whose_own_record_has_no_wallet_is_still_not_set(self):
        """The one state that asks the user to act stays."""
        workers = [_docker(1, "watchtower", [("storj", "running")]), _docker(2, "geiserback", [("storj", "running")])]
        specs = {("storj", 1): {"env": {"WALLET": WALLET_A}}, ("storj", 2): {"env": {}}}
        storj = _row(_registry([{"slug": "storj", "status": "running"}], workers, specs=specs), "storj")
        assert storj["address_missing"] is True and storj["address_missing_on"] == ["geiserback"]
        assert storj["addresses"] == [{"address": WALLET_A, "servers": ["watchtower"]}]


# ---------------------------------------------------------------------------
# The worker side of the read
# ---------------------------------------------------------------------------


def _catalog_reader(slug):
    from app import catalog

    return payout_read.readers([catalog.get_service(slug)])[slug]


class TestTheWorkerRead:
    def test_anyone_returns_only_the_wallet_never_the_contact_email(self):
        anonrc = b"Nickname relay1\nContactInfo someone@example.com @anon: " + WALLET_A.encode() + b"\nORPort 9001\n"
        address = payout_read.extract(anonrc, _catalog_reader("anyone-protocol")["pattern"])
        assert address == WALLET_A
        assert "@" not in address

    def test_mysterium_reads_the_beneficiary(self):
        body = '{"beneficiary":"' + WALLET_B + '","is_channel_address":false}'
        assert payout_read.extract(body, _catalog_reader("mysterium")["pattern"]) == WALLET_B

    def test_a_reader_with_no_group_or_a_bad_pattern_is_ignored(self):
        services = [
            {"slug": "x", "payout": {"address_read": {"command": ["cat", "f"], "pattern": "0x[0-9a-f]+"}}},
            {"slug": "y", "payout": {"address_read": {"command": ["cat", "f"], "pattern": "(unclosed"}}},
            {"slug": "z", "payout": {"address_read": {"command": "cat f", "pattern": "(0x)"}}},
        ]
        assert payout_read.readers(services) == {}

    def test_read_all_reads_running_copies_and_skips_stopped_ones(self):
        running = SimpleNamespace(
            status="running",
            labels={"cashpilot.instance": "1"},
            exec_run=lambda cmd: (0, ('{"beneficiary":"' + WALLET_A + '"}').encode()),
        )
        stopped = SimpleNamespace(status="exited", labels={}, exec_run=lambda cmd: pytest.fail("ran in a stopped copy"))
        from app import catalog

        with (
            patch.object(payout_read.orchestrator, "service_instances", return_value=[running, stopped]),
            patch.object(payout_read.orchestrator, "_instance_of", return_value=1),
        ):
            rows = payout_read.read_all([catalog.get_service("mysterium")])
        assert rows == [{"slug": "mysterium", "instance": 1, "address": WALLET_A}]

    def test_the_catalog_commands_are_read_only(self):
        """No redirection, no rm, no write: the read must not change the node."""
        from app import catalog

        for slug in ("mysterium", "anyone-protocol"):
            command = " ".join(_catalog_reader(slug)["command"])
            assert not re.search(
                r"(^|\s)(rm|mv|cp|tee|chmod|chown|kill|dd|python\d?)\s"
                r"|(^|\s)sed\s+(?:-[a-zA-Z]*i(?:\s|$)|--in-place(?:\s|$))|>|-X\s*(POST|PUT|DELETE)",
                command,
            ), slug
            assert catalog.get_service(slug)["payout"]["address_source"] == "manual"


class TestARemovalThroughTheUIRaisesNothing:
    def test_removing_on_every_box_leaves_nothing_for_the_alert(self, tmp_path):
        """The UI's Remove drops the box's record, and the fleet row with the last one."""
        from app import database

        async def go():
            await database.init_db()
            await database.save_deployment("bitping", "c1", spec={"env": {}}, worker_id=1)
            await database.save_deployment("bitping", "c2", spec={"env": {}}, worker_id=2)
            await database.remove_deployment("bitping", worker_id=1)
            await database.remove_deployment("bitping", worker_id=2)
            return await database.get_deployments(), await database.list_deployment_placements()

        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "t.db"):
            deployments, specs = asyncio.run(go())
        workers = [_docker(1, "watchtower", []), _docker(2, "geiserct", [])]
        first = {("bitping", None): NOW - timedelta(days=1), ("bitping", 1): NOW - timedelta(days=1)}
        assert placement.missing(deployments, specs, workers, now=NOW, first_missing=first) == {}
        assert first == {}

    def test_control_the_same_containers_gone_without_a_removal_do_alert(self):
        deployments = [{"slug": "bitping", "status": "running", "deployed_at": "2026-10-01 00:00:00"}]
        specs = [{"slug": "bitping", "worker_id": 1, "deployed_at": "2026-10-01 00:00:00"}]
        workers = [_docker(1, "watchtower", []), _docker(2, "geiserct", [])]
        first = {("bitping", None): NOW - timedelta(days=1), ("bitping", 1): NOW - timedelta(days=1)}
        found = placement.missing(deployments, specs, workers, now=NOW, first_missing=first)
        assert found["bitping"]["everywhere"] is True


class TestARemovedServiceStaysRemovedAcrossARestart:
    """The startup backfill gave every service with saved credentials a row, so a
    service removed from every box came back as deployed on the next restart."""

    @staticmethod
    def _creds(slug):
        from app.collectors import _COLLECTOR_ARGS

        return {f"{slug}_{a}": "x" for a in _COLLECTOR_ARGS[slug] if not a.startswith("?")}

    def _run(self, tmp_path, steps):
        from app import database

        async def go():
            await database.init_db()
            await database.set_config_bulk({**self._creds("honeygain"), **self._creds("earnapp")})
            await steps(database)
            # The restart: the real lifespan backfill.
            await main._track_fully_configured_services()
            return (
                {d["slug"] for d in await database.get_deployments()},
                await database.list_deployment_placements(),
                await database.get_config(),
            )

        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "t.db"):
            return asyncio.run(go())

    def test_removed_through_the_ui_on_every_box_stays_gone_and_raises_nothing(self, tmp_path):
        async def steps(database):
            await database.save_deployment("honeygain", "c1", spec={"env": {}}, worker_id=1)
            await database.save_deployment("honeygain", "c2", spec={"env": {}}, worker_id=2)
            # What _svc_remove does on each box.
            await database.remove_deployment("honeygain", worker_id=1)
            await database.remove_deployment("honeygain", worker_id=2)

        rows, specs, config = self._run(tmp_path, steps)
        assert "honeygain" not in rows
        assert self._creds("honeygain").keys() <= config.keys(), "the saved credentials must survive"
        deployments = [{"slug": s, "status": "external"} for s in rows]
        workers = [_docker(1, "watchtower", []), _docker(2, "geiserct", [])]
        first = {("honeygain", None): NOW - timedelta(days=1)}
        assert placement.missing(deployments, specs, workers, now=NOW, first_missing=first) == {}

    def test_control_a_collector_only_service_with_credentials_still_gets_its_row(self, tmp_path):
        async def steps(database):
            await database.save_deployment("honeygain", "c1", spec={"env": {}}, worker_id=1)
            await database.remove_deployment("honeygain", worker_id=1)

        rows, _, _ = self._run(tmp_path, steps)
        assert "earnapp" in rows and "honeygain" not in rows

    def test_removed_from_one_box_while_another_runs_it_is_not_a_removal(self, tmp_path):
        async def steps(database):
            await database.save_deployment("honeygain", "c1", spec={"env": {}}, worker_id=1)
            await database.save_deployment("honeygain", "c2", spec={"env": {}}, worker_id=2)
            await database.remove_deployment("honeygain", worker_id=1)

        rows, _, _ = self._run(tmp_path, steps)
        assert "honeygain" in rows

    def test_deploying_it_again_lifts_the_removal(self, tmp_path):
        async def steps(database):
            await database.save_deployment("honeygain", "c1", spec={"env": {}}, worker_id=1)
            await database.remove_deployment("honeygain", worker_id=1)
            await database.save_deployment("honeygain", "", status="external")
            await database.remove_deployment("honeygain")
            await database.save_deployment("honeygain", "c3", spec={"env": {}}, worker_id=1)

        rows, _, _ = self._run(tmp_path, steps)
        assert "honeygain" in rows
        from app import database

        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "t.db"):
            assert asyncio.run(database.removed_slugs()) == set()

    def test_forget_is_a_removal_too(self, tmp_path):
        async def steps(database):
            await database.save_deployment("honeygain", "c1", spec={"env": {}}, worker_id=1)
            await database.forget_deployment("honeygain")

        rows, _, _ = self._run(tmp_path, steps)
        assert "honeygain" not in rows


# ---------------------------------------------------------------------------
# Review fixes (CodeRabbit on #499)
# ---------------------------------------------------------------------------


class TestAnAlertSurvivesWhatCannotBeJudged:
    def test_an_already_alerted_service_skips_the_grace_after_a_restart(self):
        """A restart empties first_missing; the stored alert must neither clear nor wait 30 minutes."""
        deps = [{"slug": "bitping", "status": "running", "deployed_at": _sql(NOW - timedelta(days=3))}]
        first: dict = {}
        found = placement.missing(
            deps, [], [_docker(1, "watchtower", [])], now=NOW, first_missing=first, alerted={"bitping"}
        )
        assert found["bitping"]["everywhere"] is True

    def test_control_without_a_stored_alert_the_grace_applies(self):
        deps = [{"slug": "bitping", "status": "running", "deployed_at": _sql(NOW - timedelta(days=3))}]
        first: dict = {}
        assert placement.missing(deps, [], [_docker(1, "watchtower", [])], now=NOW, first_missing=first) == {}
        assert ("bitping", None) in first, "still pending, so the caller keeps any alert"

    def test_a_box_going_offline_keeps_its_verdict(self):
        specs = [{"slug": "earnapp", "worker_id": 2, "deployed_at": _sql(NOW - timedelta(days=3))}]
        deps = [{"slug": "earnapp", "status": "running", "deployed_at": _sql(NOW - timedelta(days=3))}]
        workers = [
            _docker(1, "watchtower", [("earnapp", "running")]),
            _docker(2, "geiserct", [], status="offline"),
        ]
        first = {("earnapp", 2): NOW - timedelta(hours=2)}
        assert placement.missing(deps, specs, workers, now=NOW, first_missing=first) == {}
        assert ("earnapp", 2) in first

    def test_an_offline_box_that_went_quiet_before_the_deploy_may_be_running_it(self):
        deps = [{"slug": "bitping", "status": "running", "deployed_at": _sql(NOW - timedelta(hours=2))}]
        quiet = _docker(2, "geiserct", [], status="offline")
        quiet["last_heartbeat"] = _sql(NOW - timedelta(hours=5))
        first = {("bitping", None): NOW - timedelta(hours=2)}
        workers = [_docker(1, "watchtower", []), quiet]
        assert placement.missing(deps, [], workers, now=NOW, first_missing=first) == {}
        quiet["last_heartbeat"] = _sql(NOW - timedelta(minutes=30))
        assert "bitping" in placement.missing(deps, [], workers, now=NOW, first_missing=first)


@pytest.mark.usefixtures("_clean_main")
class TestTheAlertAcrossARestart:
    def test_a_restart_neither_clears_nor_re_pushes_a_standing_alert(self):
        alerts = _Alerts()
        alerts.rows["bitping"] = "runs nowhere"
        deps = [{"slug": "bitping", "status": "running", "deployed_at": "2026-01-01 00:00:00"}]
        stored = [{"kind": "missing", "subject": "bitping", "message": "runs nowhere"}]
        with patch.object(main.database, "list_alerts", AsyncMock(return_value=stored)):
            asyncio.run(main._warm_collector_alerts())
        assert "bitping" in main._missing_bell, "restored into what the collection rebuild re-adds"
        p = alerts.patches(deps, [])
        with p[0], p[1], p[2], p[3], p[4], p[5]:
            asyncio.run(main._missing_deployment_check([_docker(1, "watchtower", [])]))
        assert alerts.rows == {"bitping": "runs nowhere"} or "bitping" in alerts.rows
        assert alerts.pushed == []
        assert main._missing_bell["bitping"]["everywhere"] is True, "Forget's fields are back"

    def test_a_box_offline_does_not_clear_its_alert(self):
        alerts = _Alerts()
        alerts.rows["earnapp"] = "gone from geiserct"
        main._deployment_first_missing[("earnapp", 2)] = datetime.now(UTC) - timedelta(hours=2)
        specs = [{"slug": "earnapp", "worker_id": 2, "deployed_at": "2026-01-01 00:00:00"}]
        workers = [_docker(1, "watchtower", [("earnapp", "running")]), _docker(2, "geiserct", [], status="offline")]
        p = alerts.patches([{"slug": "earnapp", "status": "running"}], specs)
        with p[0], p[1], p[2], p[3], p[4], p[5]:
            asyncio.run(main._missing_deployment_check(workers))
        assert "earnapp" in alerts.rows


@pytest.mark.usefixtures("_clean_main")
class TestForgetReviewFixes:
    def test_refused_while_the_box_holding_the_record_cannot_read_docker(self, client):
        forget = AsyncMock()
        with (
            _as("writer"),
            patch.object(
                main.database,
                "list_workers",
                AsyncMock(return_value=[_docker(1, "watchtower", []), _docker(2, "geiserct", [], docker=False)]),
            ),
            patch.object(
                main.database,
                "list_deployment_placements",
                AsyncMock(return_value=[{"slug": "earnapp", "worker_id": 2, "deployed_at": ""}]),
            ),
            patch.object(main.database, "forget_deployment", forget),
        ):
            resp = client.delete("/api/deployments/earnapp")
        assert resp.status_code == 409 and "geiserct" in resp.text
        forget.assert_not_awaited()

    def test_control_a_blind_box_with_no_record_does_not_block(self, client):
        p = _Alerts().patches([], [])
        with (
            _as("writer"),
            p[0],
            p[1],
            p[2],
            p[3],
            p[4],
            p[5],
            patch.object(
                main.database,
                "list_workers",
                AsyncMock(return_value=[_docker(1, "watchtower", []), _docker(2, "geiserct", [], docker=False)]),
            ),
            patch.object(main.database, "forget_deployment", AsyncMock()),
            patch.object(main.database, "get_deployment", AsyncMock(return_value=None)),
        ):
            assert client.delete("/api/deployments/bitping").status_code == 200

    def test_the_last_box_forgotten_clears_the_alert_even_when_the_fleet_cannot_tell(self, client):
        alerts = _Alerts()
        alerts.rows["earnapp"] = "gone"
        main._missing_bell["earnapp"] = {"kind": "missing", "platform": "earnapp", "error": "gone"}
        p = alerts.patches([], [])
        with (
            _as("writer"),
            p[0],
            p[1],
            p[2],
            p[3],
            p[4],
            p[5],
            patch.object(
                main.database,
                "list_workers",
                AsyncMock(return_value=[_docker(1, "watchtower", []), _docker(3, "blind", [], docker=False)]),
            ),
            patch.object(main.database, "remove_deployment", AsyncMock()),
            patch.object(main.database, "get_deployment", AsyncMock(return_value=None)),
        ):
            resp = client.delete("/api/deployments/earnapp?worker_id=1")
        assert resp.status_code == 200, resp.text
        assert alerts.rows == {} and "earnapp" not in main._missing_bell


class TestFleetWideRemovalDropsEveryBoxRecord:
    def test_it(self, tmp_path):
        from app import database

        async def go():
            await database.init_db()
            await database.save_deployment("storj", "c1", spec={"env": {}}, worker_id=1)
            await database.remove_deployment("storj")
            return [r for r in await database.list_deployment_placements() if r["slug"] == "storj"]

        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "t.db"):
            assert asyncio.run(go()) == []


class TestRegistryReviewFixes:
    def test_an_unreadable_worker_list_is_unknown_not_runs_nowhere(self):
        with (
            patch.object(
                payout_registry.database,
                "get_deployments",
                AsyncMock(return_value=[{"slug": "bitping", "status": "running"}]),
            ),
            patch.object(payout_registry.database, "list_workers", AsyncMock(side_effect=RuntimeError("db"))),
            patch.object(payout_registry.database, "get_deployment_spec", AsyncMock(return_value=None)),
        ):
            result = asyncio.run(payout_registry.registry())
        bitping = _row(result, "bitping")
        assert bitping["deployed"] is True and bitping["runs_on_unknown"] is True
        assert result["summary"]["recorded_not_running"] == 0

    def test_every_wallet_on_one_box_is_kept(self):
        workers = [_docker(1, "watchtower", [("mysterium", "running"), ("mysterium", "running")])]

        async def read(worker_id):
            return [
                {"slug": "mysterium", "instance": 1, "address": WALLET_A},
                {"slug": "mysterium", "instance": 2, "address": WALLET_B},
            ]

        mysterium = _row(_registry([], workers, read=read), "mysterium")
        assert [a["address"] for a in mysterium["addresses"]] == [WALLET_A, WALLET_B]

    def test_a_box_without_a_readable_record_beside_one_with_is_flagged(self):
        workers = [_docker(1, "watchtower", [("storj", "running")]), _docker(2, "geiserback", [("storj", "running")])]
        specs = {("storj", 1): {"env": {"WALLET": WALLET_A}}}
        storj = _row(_registry([{"slug": "storj", "status": "running"}], workers, specs=specs), "storj")
        assert storj["address"] == WALLET_A and storj["address_unchecked"] == "record"
        assert storj["address_missing"] is False


class TestAnyoneReadsOnlyALiveContactInfo:
    def test_a_commented_old_wallet_is_ignored(self):
        anonrc = f"# ContactInfo old @anon: {WALLET_B}\nContactInfo me@example.com @anon: {WALLET_A}\n"
        assert payout_read.extract(anonrc, _catalog_reader("anyone-protocol")["pattern"]) == WALLET_A
        assert (
            payout_read.extract(f"#ContactInfo @anon: {WALLET_B}\n", _catalog_reader("anyone-protocol")["pattern"])
            is None
        )


class TestSecondReviewRound:
    def test_a_box_newly_missing_beside_an_alerted_one_waits_its_own_grace(self):
        old = _sql(NOW - timedelta(days=3))
        specs = [
            {"slug": "earnapp", "worker_id": 1, "deployed_at": old},
            {"slug": "earnapp", "worker_id": 2, "deployed_at": old},
        ]
        workers = [
            _docker(1, "watchtower", []),
            _docker(2, "geiserback", []),
            _docker(3, "geiserct", [("earnapp", "running")]),
        ]
        deps = [{"slug": "earnapp", "status": "running", "deployed_at": old}]
        found = placement.missing(deps, specs, workers, now=NOW, first_missing={}, alerted={("earnapp", 1)})
        assert [b["worker_id"] for b in found["earnapp"]["boxes"]] == [1]
        # Control: an alert of unknown scope (restored) covers every box.
        found = placement.missing(deps, specs, workers, now=NOW, first_missing={}, alerted={"earnapp"})
        assert [b["worker_id"] for b in found["earnapp"]["boxes"]] == [1, 2]

    def test_tracked_only_rows_are_not_deployed_when_the_boxes_are_unknown(self):
        with (
            patch.object(
                payout_registry.database,
                "get_deployments",
                AsyncMock(return_value=[{"slug": "grass", "status": "external"}]),
            ),
            patch.object(payout_registry.database, "list_workers", AsyncMock(side_effect=RuntimeError("db"))),
            patch.object(payout_registry.database, "get_deployment_spec", AsyncMock(return_value=None)),
        ):
            grass = _row(asyncio.run(payout_registry.registry()), "grass")
        assert grass["tracked_only"] is True and grass["deployed"] is False

    def test_an_overlong_anyone_wallet_is_not_cut_to_a_valid_looking_one(self):
        pattern = _catalog_reader("anyone-protocol")["pattern"]
        assert payout_read.extract(f"ContactInfo a @anon: {WALLET_A}f\n", pattern) is None
        assert payout_read.extract(f"ContactInfo a @anon: {WALLET_A} \n", pattern) == WALLET_A


@pytest.mark.usefixtures("_clean_main")
class TestARetainedAlertNamesOnlyWhatIsStillMissing:
    def test_a_recovered_box_leaves_the_forget_actions(self):
        alerts = _Alerts()
        alerts.rows["earnapp"] = "gone from watchtower and geiserct"
        main._missing_bell["earnapp"] = {
            "kind": "missing",
            "platform": "earnapp",
            "name": "EarnApp",
            "error": "gone",
            "everywhere": False,
            "boxes": [{"worker_id": 1, "name": "watchtower"}, {"worker_id": 2, "name": "geiserct"}],
        }
        main._deployment_first_missing[("earnapp", 2)] = datetime.now(UTC) - timedelta(hours=2)
        specs = [{"slug": "earnapp", "worker_id": 2, "deployed_at": "2026-01-01 00:00:00"}]
        workers = [_docker(1, "watchtower", [("earnapp", "running")]), _docker(2, "geiserct", [], status="offline")]
        p = alerts.patches([{"slug": "earnapp", "status": "running"}], specs)
        with p[0], p[1], p[2], p[3], p[4], p[5]:
            asyncio.run(main._missing_deployment_check(workers))
        assert "earnapp" in alerts.rows
        assert [b["worker_id"] for b in main._missing_bell["earnapp"]["boxes"]] == [2]
        assert "watchtower" not in main._missing_bell["earnapp"]["error"].split("still")[0]

    def test_a_restored_alert_has_no_scope_until_a_check_names_it(self):
        stored = [{"kind": "missing", "subject": "bitping", "message": "runs nowhere"}]
        with patch.object(main.database, "list_alerts", AsyncMock(return_value=stored)):
            asyncio.run(main._warm_collector_alerts())
        assert "everywhere" not in main._missing_bell["bitping"]
        assert main._missing_scope("bitping") == {"bitping"}


# ---------------------------------------------------------------------------
# Independent review of #499
# ---------------------------------------------------------------------------


def _desktop(wid, name, containers, *, status="online"):
    # What CashPilot-Desktop sends: os and device_type, no docker_available.
    return {
        "id": wid,
        "name": name,
        "status": status,
        "system_info": json.dumps({"os": "darwin", "device_type": "desktop"}),
        "containers": json.dumps([{"slug": s, "status": st} for s, st in containers]),
        "apps": "[]",
    }


class TestAPairedDesktopIsNotABlindHost:
    def test_it_does_not_switch_off_the_runs_nowhere_alert(self):
        workers = [_docker(1, "watchtower", []), _desktop(2, "MacBook", [("honeygain", "running")])]
        found = placement.missing(
            [{"slug": "bitping", "status": "running", "deployed_at": _sql(NOW - timedelta(days=3))}],
            [],
            workers,
            now=NOW,
            first_missing={("bitping", None): NOW - timedelta(hours=1)},
        )
        assert found is not None and "bitping" in found

    def test_control_a_docker_host_that_cannot_read_its_socket_still_does(self):
        workers = [_docker(1, "watchtower", []), _docker(2, "geiserct", [], docker=False)]
        deps = [{"slug": "bitping", "status": "running", "deployed_at": _sql(NOW - timedelta(days=3))}]
        assert placement.missing(deps, [], workers, now=NOW, first_missing={}) is None

    def test_it_does_not_switch_off_the_container_down_check(self):
        workers = [_docker(1, "watchtower", []), _desktop(2, "MacBook", [])]
        record = AsyncMock()
        with (
            patch.object(main.database, "list_workers", AsyncMock(return_value=workers)),
            patch.object(
                main.database, "get_deployments", AsyncMock(return_value=[{"slug": "bitping", "status": "running"}])
            ),
            patch.object(main.database, "record_health_events", record),
            patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=[])),
            patch.object(main, "_container_down_check", AsyncMock()),
            patch.object(main, "_missing_deployment_check", AsyncMock()),
        ):
            asyncio.run(main._run_health_check())
        events = record.await_args.args[0]
        assert ("bitping", "check_down", "missing from heartbeat") in events


@pytest.mark.usefixtures("_clean_main")
class TestASettingsSaveDoesNotBringBackARemovedService:
    def _save(self, client, before, data):
        save = AsyncMock()
        with (
            _as("owner"),
            patch.object(
                main.database,
                "get_config",
                AsyncMock(side_effect=[before, {**before, **data, "_removed_deployment:honeygain": "1"}]),
            ),
            patch.object(main.database, "set_config_bulk", AsyncMock()),
            patch.object(main.database, "get_deployment", AsyncMock(return_value=None)),
            patch.object(main.database, "save_deployment", save),
        ):
            resp = client.post("/api/config", json={"data": data})
        assert resp.status_code == 200, resp.text
        return [c.kwargs.get("slug") for c in save.await_args_list]

    def test_the_prefilled_unchanged_credentials_of_another_save_do_not(self, client):
        before = {"honeygain_email": "me@example.com", "honeygain_password": "pw"}
        saved = self._save(client, before, {"honeygain_email": "me@example.com", "earnapp_oauth_token": "t"})
        assert "honeygain" not in saved and saved == ["earnapp"], "the service actually added still is"

    def test_control_a_changed_credential_does(self, client):
        before = {"honeygain_email": "me@example.com", "honeygain_password": "pw"}
        assert self._save(client, before, {"honeygain_password": "new"}) == ["honeygain"]


class TestARemovalOnOneBoxStaysOnThatBox:
    def test_another_box_running_it_without_a_deploy_record_keeps_it_tracked(self, tmp_path):
        """Deploys from before per-box records: no spec row on the other box."""
        from app import database

        async def go():
            await database.init_db()
            await database.save_deployment("honeygain", "c1", status="running")
            await database.upsert_worker(
                "geiserback-id",
                name="geiserback",
                url="http://b",
                containers=json.dumps([{"slug": "honeygain", "status": "running"}]),
                system_info=json.dumps({"docker_available": True}),
            )
            await database.remove_deployment("honeygain", worker_id=999)
            return await database.get_deployment("honeygain"), await database.removed_slugs()

        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "t.db"):
            row, removed = asyncio.run(go())
        assert row is not None and "honeygain" not in removed
