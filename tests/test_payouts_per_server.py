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
            assert not re.search(r"(^|\s)(rm|mv|cp|tee|chmod|chown|kill)\s|>|-X\s*(POST|PUT|DELETE)", command), slug
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
