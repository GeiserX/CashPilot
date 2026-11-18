"""A worker that reports in but cannot reach Docker raises an alert.

Such a worker heartbeats on time, so the fleet page shows it online and the
offline alert never fires, while it can start, stop or see nothing. On
2026-11-17 one ran like that for 17 hours after a Docker update replaced the
socket its proxy had bound; the UI only wrote a log line. _worker_docker_check
alerts after the same grace the container alerts use.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app import main


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.setattr(main, "_docker_first_seen", {})
    monkeypatch.setattr(main, "_docker_bell", {})
    monkeypatch.setattr(main, "_collector_alerts", [])


def _worker(*, cid="cid-ct", name="geiserct", online=True, docker=False, access="proxy", **info):
    system_info = {"docker_available": docker, **info}
    if access is not None:
        system_info["docker_access"] = access
    return {
        "id": 1,
        "client_id": cid,
        "name": name,
        "status": "online" if online else "offline",
        "system_info": json.dumps(system_info),
    }


class _Alerts:
    """The alerts table and its dedupe, in memory."""

    def __init__(self):
        self.rows: dict[str, str] = {}
        # created_at of each row, as SQLite writes it (UTC).
        self.created: dict[str, str] = {}
        self.pushes: list[tuple[str, str]] = []

    async def record(self, kind, subject, message, **_):
        assert kind == "docker"
        fresh = subject not in self.rows
        self.rows[subject] = message
        if fresh:
            self.created[subject] = f"{datetime.now(UTC):%Y-%m-%d %H:%M:%S}"
        return len(self.rows) if fresh else None

    async def first_times(self, kind):
        return {s: self.created.get(s, "") for s in self.rows} if kind == "docker" else {}

    async def clear(self, kind=None, subject=None):
        assert kind == "docker"
        self.rows.pop(subject, None)
        self.created.pop(subject, None)

    def run(self, workers, *, age=None):
        def spawn(coro):
            frame = coro.cr_frame.f_locals
            self.pushes.append((frame["title"], frame["message"]))
            coro.close()

        with (
            patch.object(main.database, "record_alert", self.record),
            patch.object(main.database, "get_alert_first_times", self.first_times),
            patch.object(main.database, "clear_alerts", self.clear),
            patch.object(main, "_spawn", spawn),
        ):
            if age is not None:
                for key in main._docker_first_seen:
                    main._docker_first_seen[key] = datetime.now(UTC) - age
            asyncio.run(main._worker_docker_check(workers))


PAST_GRACE = main.CONTAINER_DOWN_GRACE + timedelta(minutes=1)


def _bell():
    return [a for a in main._collector_alerts if a.get("kind") == "docker"]


class TestABlindWorkerIsAnAlert:
    def test_quiet_inside_the_grace(self):
        """A Docker restart or update must not page anyone."""
        alerts = _Alerts()
        alerts.run([_worker()])
        assert alerts.rows == {} and alerts.pushes == [] and _bell() == []

    def test_alerts_past_the_grace_naming_the_worker_and_the_fix(self):
        alerts = _Alerts()
        alerts.run([_worker()])
        alerts.run([_worker()], age=PAST_GRACE)
        assert set(alerts.rows) == {"cid-ct"}, "keyed by client_id, never the cosmetic name"
        [(title, message)] = alerts.pushes
        assert title == "CashPilot: worker 'geiserct' cannot reach Docker"
        assert "docker restart cashpilot-socket-proxy" in message
        assert main.DOCKER_LOST_DOC in message
        [entry] = _bell()
        assert entry["platform"] == "geiserct" and entry["client_id"] == "cid-ct"

    def test_one_push_per_outage(self):
        alerts = _Alerts()
        alerts.run([_worker()])
        alerts.run([_worker()], age=PAST_GRACE)
        alerts.run([_worker()], age=PAST_GRACE + timedelta(minutes=5))
        assert len(alerts.pushes) == 1
        assert len(_bell()) == 1

    def test_a_raw_socket_worker_is_told_to_restart_itself(self):
        alerts = _Alerts()
        alerts.run([_worker(access="socket")])
        alerts.run([_worker(access="socket")], age=PAST_GRACE)
        [(_, message)] = alerts.pushes
        assert "restart the worker" in message
        assert "cashpilot-socket-proxy" not in message

    def test_an_older_worker_gets_both_fixes(self):
        """A worker from before docker_access may hold the socket itself (Unraid, or older than the proxy)."""
        alerts = _Alerts()
        alerts.run([_worker(access=None)])
        alerts.run([_worker(access=None)], age=PAST_GRACE)
        [(_, message)] = alerts.pushes
        assert "docker restart cashpilot-socket-proxy" in message
        assert "restart the worker if it has no proxy" in message


class TestTheBellShowsTheFix:
    """/api/collector-alerts cuts every message at _MAX_ALERT_ERROR_LEN; the push carries all of it."""

    @pytest.mark.parametrize(
        ("access", "fix"),
        [
            ("proxy", "Fix: on that machine, run docker restart cashpilot-socket-proxy."),
            ("socket", "Fix: on that machine, restart the worker container. It holds the Docker socket itself."),
            (
                None,
                "Fix: on that machine, run docker restart cashpilot-socket-proxy, or restart the worker if it has no proxy.",
            ),
        ],
    )
    def test_the_whole_fix_fits_in_the_bell_for_a_long_name(self, access, fix):
        name = "a-worker-name-of-thirty-chars"
        _, message = main._docker_alert_text(name, _worker(access=access), datetime.now(UTC))
        assert fix in message[: main._MAX_ALERT_ERROR_LEN]


class TestWhatIsNotAnAlert:
    def test_a_worker_that_reaches_docker(self):
        alerts = _Alerts()
        alerts.run([_worker(docker=True)])
        alerts.run([_worker(docker=True)], age=PAST_GRACE)
        assert alerts.rows == {} and _bell() == []

    def test_a_phone_or_a_desktop(self):
        """Neither has Docker to lose; a Desktop sends no docker_available, a phone may send false."""
        phone = _worker(cid="p", os="Android")
        desktop = _worker(cid="d", device_type="desktop")
        alerts = _Alerts()
        alerts.run([phone, desktop])
        alerts.run([phone, desktop], age=PAST_GRACE)
        assert alerts.rows == {}

    def test_a_worker_with_no_docker_flag_at_all(self):
        """A missing flag says nothing, unlike an explicit false."""
        w = _worker()
        w["system_info"] = json.dumps({})
        alerts = _Alerts()
        alerts.run([w])
        alerts.run([w], age=PAST_GRACE)
        assert alerts.rows == {}

    def test_an_offline_worker_neither_raises_nor_clears(self):
        alerts = _Alerts()
        alerts.run([_worker(online=False)])
        alerts.run([_worker(online=False)], age=PAST_GRACE)
        assert alerts.rows == {}, "an offline worker has its own alert"
        alerts.run([_worker()])
        alerts.run([_worker()], age=PAST_GRACE)
        assert set(alerts.rows) == {"cid-ct"}
        alerts.run([_worker(online=False, docker=True)])
        assert set(alerts.rows) == {"cid-ct"}, "its last heartbeat says nothing about now"
        assert len(_bell()) == 1


class TestRecovery:
    def test_clears_when_docker_answers_again_and_rearms(self):
        alerts = _Alerts()
        alerts.run([_worker()])
        alerts.run([_worker()], age=PAST_GRACE)
        alerts.run([_worker(docker=True)])
        assert alerts.rows == {} and _bell() == []
        assert main._docker_first_seen == {}
        # The next outage starts its own grace and pushes again.
        alerts.run([_worker()])
        assert len(alerts.pushes) == 1
        alerts.run([_worker()], age=PAST_GRACE)
        assert len(alerts.pushes) == 2

    def test_clears_when_the_worker_is_removed(self):
        alerts = _Alerts()
        alerts.run([_worker()])
        alerts.run([_worker()], age=PAST_GRACE)
        alerts.run([])
        assert alerts.rows == {} and _bell() == []

    def test_a_stored_alert_stands_at_once_after_a_ui_restart(self):
        """The UI forgot when the outage began; the stored row is proof it is past the grace."""
        alerts = _Alerts()
        alerts.rows["cid-ct"] = "stored before the restart"
        alerts.run([_worker()])
        assert len(_bell()) == 1

    def test_a_ui_restart_keeps_when_the_outage_began(self):
        """The stored row was written a grace after the outage began; the restart time is not the start."""
        alerted = datetime.now(UTC) - timedelta(hours=6)
        alerts = _Alerts()
        alerts.rows["cid-ct"] = "stored before the restart"
        alerts.created["cid-ct"] = f"{alerted:%Y-%m-%d %H:%M:%S}"
        alerts.run([_worker()])
        began = alerted - main.CONTAINER_DOWN_GRACE
        [entry] = _bell()
        assert f"since {began:%Y-%m-%d %H:%M} UTC" in entry["error"]
        assert f"since {began:%Y-%m-%d %H:%M} UTC" in alerts.rows["cid-ct"], "the stored row keeps it too"
        assert alerts.pushes == [], "the outage was already pushed"

    def test_a_ui_restart_inside_the_grace_keeps_the_worker_reported_start(self):
        """No alert row yet, so only the worker knows: it reports how long Docker has failed.

        Counting from the restart instead postponed the alert by a whole grace
        on each restart, and forever on a UI that restarts more often than that.
        """
        heartbeat = datetime.now(UTC) - timedelta(seconds=40)
        worker = _worker(docker_unreachable_for=int(PAST_GRACE.total_seconds()))
        worker["last_heartbeat"] = f"{heartbeat:%Y-%m-%d %H:%M:%S}"
        alerts = _Alerts()
        alerts.run([worker])
        began = heartbeat - PAST_GRACE
        [entry] = _bell()
        assert f"since {began:%Y-%m-%d %H:%M} UTC" in entry["error"]
        assert len(alerts.pushes) == 1

    def test_a_reported_start_inside_the_grace_stays_quiet(self):
        worker = _worker(docker_unreachable_for=20 * 60)
        worker["last_heartbeat"] = f"{datetime.now(UTC):%Y-%m-%d %H:%M:%S}"
        alerts = _Alerts()
        alerts.run([worker])
        assert alerts.rows == {} and _bell() == []

    @pytest.mark.parametrize("seconds", ["1200", -5, True, 10**30, None])
    def test_an_unusable_reported_age_falls_back_to_now(self, seconds):
        worker = _worker(docker_unreachable_for=seconds)
        worker["last_heartbeat"] = f"{datetime.now(UTC):%Y-%m-%d %H:%M:%S}"
        alerts = _Alerts()
        alerts.run([worker])
        assert alerts.rows == {} and _bell() == []
        assert datetime.now(UTC) - main._docker_first_seen["cid-ct"] < timedelta(minutes=1)

    def test_an_unreadable_stored_time_falls_back_to_now(self):
        alerts = _Alerts()
        alerts.rows["cid-ct"] = "stored before the restart"
        alerts.created["cid-ct"] = "not a time"
        alerts.run([_worker()])
        assert len(_bell()) == 1


class TestWiring:
    def test_runs_in_the_health_check(self):
        """A check nothing calls is not a check."""
        called = AsyncMock()
        with (
            patch.object(main, "_worker_docker_check", called),
            patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=[])),
            patch.object(main.database, "list_workers", AsyncMock(return_value=[_worker()])),
            patch.object(main.database, "record_health_events", AsyncMock()),
            patch.object(main, "_container_down_check", AsyncMock()),
            patch.object(main, "_account_disabled_check", AsyncMock()),
            patch.object(main, "_missing_deployment_check", AsyncMock()),
            patch.object(main, "_proxied_copy_check", AsyncMock()),
        ):
            asyncio.run(main._run_health_check())
        called.assert_awaited_once()

    def test_restored_after_a_ui_restart(self):
        rows = [{"kind": "docker", "subject": "cid-ct", "message": "cannot reach Docker"}]
        with (
            patch.object(main.database, "list_alerts", AsyncMock(return_value=rows)),
            patch.object(main.database, "list_workers", AsyncMock(return_value=[_worker()])),
            patch.object(main, "_proxy_cap_alerts", AsyncMock(return_value=[])),
        ):
            asyncio.run(main._warm_collector_alerts())
        assert main._docker_bell["cid-ct"]["platform"] == "geiserct"
        assert [a["platform"] for a in _bell()] == ["geiserct"]


class TestEveryScreenShowsIt:
    """The bell list is replaced wholesale every hour, and the pages draw it by kind."""

    def test_the_hourly_rebuild_keeps_it(self):
        import inspect

        assert "_docker_bell.values()" in inspect.getsource(main._run_collection)

    def test_an_alert_cleared_during_the_rebuild_stays_cleared(self):
        """The health check can clear the entry while the rebuild awaits; a copy taken first restored it."""
        from app.collectors.base import EarningsResult

        main._docker_bell["cid-ct"] = {"kind": "docker", "platform": "geiserct", "error": "cannot reach Docker"}

        async def health_check_clears_it():
            main._docker_bell.pop("cid-ct", None)
            return []

        async def run():
            with (
                patch.object(main.database, "get_deployments", AsyncMock(return_value=[{"slug": "honeygain"}])),
                patch.object(main.database, "get_config", AsyncMock(return_value={})),
                patch.object(main.database, "upsert_earnings", AsyncMock()),
                patch.object(main.database, "record_alert", AsyncMock(return_value=False)),
                patch.object(main.database, "list_alerts", AsyncMock(return_value=[])),
                patch.object(main, "_detect_payout", AsyncMock(return_value=None)),
                patch.object(main, "_flatline_check", AsyncMock(return_value=[])),
                patch.object(main, "_pending_payout_alerts", AsyncMock(return_value=[])),
                patch.object(main, "_proxy_cap_alerts", health_check_clears_it),
                patch.object(
                    main, "_collect_bounded", AsyncMock(return_value=EarningsResult(platform="honeygain", balance=1.0))
                ),
                patch("app.collectors.make_collectors", lambda deployments, config: [object()]),
                patch("app.collectors._close_stale", AsyncMock()),
                patch.object(main, "_spawn", lambda coro: coro.close()),
            ):
                await main._run_collection()

        asyncio.run(run())
        assert _bell() == []

    def test_dashboard_and_bell_draw_it_without_a_credential_button(self):
        from pathlib import Path

        js = (Path(main.__file__).parent / "static" / "js" / "app.js").read_text()
        assert "a.kind === 'docker'" in js, "the attention list has a card for it"
        assert "|| a.kind === 'docker')" in js, "a change redraws the attention list"
        assert "!isProxied && !isDocker;" in js, "no credential fixes Docker"

    @pytest.mark.parametrize("access", ["proxy", "socket", None])
    def test_the_push_keeps_the_whole_link(self, access):
        """notify cuts a push at its own limit; a link at the end lost its tail for a long name."""
        from app import notify

        _, message = main._docker_alert_text("a-worker-name-of-thirty-chars", _worker(access=access), datetime.now(UTC))
        assert main.DOCKER_LOST_DOC in notify.redact(message)

    def test_a_bell_redraw_takes_its_own_generation(self):
        """Two redraws in flight shared one generation, so the older could write last.

        The interleavings run for real in scripts/attention_race_check.mjs.
        """
        from pathlib import Path

        js = (Path(main.__file__).parent / "static" / "js" / "app.js").read_text()
        assert "alerts.slice(), ++_attentionDrawSeq);" in js

    def test_the_doc_link_is_a_button_because_the_message_is_cut(self):
        """The 200-character cap always cuts the link off the end of the message."""
        from pathlib import Path

        _, message = main._docker_alert_text("a-worker-name-of-thirty-chars", _worker(access=None), datetime.now(UTC))
        assert main.DOCKER_LOST_DOC not in message[: main._MAX_ALERT_ERROR_LEN]
        js = (Path(main.__file__).parent / "static" / "js" / "app.js").read_text()
        assert f"const DOCKER_LOST_DOC = '{main.DOCKER_LOST_DOC}';" in js
        assert js.count('href="${DOCKER_LOST_DOC}" target="_blank" rel="noopener">How to fix</a>') == 2, (
            "the attention card and the bell"
        )
        html = (Path(main.__file__).parent / "templates" / "fleet.html").read_text()
        assert main.DOCKER_LOST_DOC in html, "the fleet flag names where the lasting fix is"

    def test_fleet_page_flags_the_worker_at_once(self):
        from pathlib import Path

        html = (Path(main.__file__).parent / "templates" / "fleet.html").read_text()
        assert "sysInfo.docker_available === false" in html
        assert "'Docker unreachable')" in html


class TestTheStoredStartTime:
    """The real alerts table: the first time a subject was alerted, in a form _docker_outage_start reads."""

    def test_first_times_reads_the_oldest_row_of_each_subject(self, tmp_path):
        async def run():
            await main.database.init_db()
            await main.database.record_alert("docker", "cid-ct", "first")
            db = await main.database._get_db()
            try:
                await db.execute("UPDATE alerts SET created_at = '2026-11-17 06:40:00' WHERE subject = 'cid-ct'")
                await db.commit()
            finally:
                await db.close()
            # The daily re-notify after the cooldown adds a newer row for the same outage.
            await main.database.record_alert("docker", "cid-ct", "again", cooldown_hours=0)
            await main.database.record_alert("container", "cid-ct", "another kind")
            return await main.database.get_alert_first_times("docker")

        with (
            patch.object(main.database, "DB_DIR", tmp_path),
            patch.object(main.database, "DB_PATH", tmp_path / "cashpilot.db"),
        ):
            times = asyncio.run(run())
        assert times == {"cid-ct": "2026-11-17 06:40:00"}
        began = main._docker_outage_start(times["cid-ct"], datetime.now(UTC))
        assert began == datetime(2026, 11, 17, 6, 40, tzinfo=UTC) - main.CONTAINER_DOWN_GRACE
