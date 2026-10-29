"""A managed container that stays exited raises one alert, and clears it on its own.

Three urnetwork containers exited cleanly (code 0) at the same minute and, with
restart policy "no", stayed down for over two days. The health check wrote a
check_down for them every five minutes and nothing ever read it: no alert, no
notification. The worker now reports when and how a stopped container stopped,
and the UI alerts once the container has been down past the grace period,
unless the user stopped it from CashPilot.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app import main, orchestrator


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.setattr(main, "_container_first_seen_down", {})
    monkeypatch.setattr(main, "_container_down_bell", {})
    monkeypatch.setattr(main, "_collector_alerts", [])


def _ago(**kw) -> str:
    return (datetime.now(UTC) - timedelta(**kw)).strftime("%Y-%m-%dT%H:%M:%S.123456789Z")


def _entry(status="exited", *, slug="urnetwork", node="geiserback", worker_id=1, **extra):
    return {
        "slug": slug,
        "name": f"cashpilot-{slug}",
        "status": status,
        "deployed_by": node,
        "_node": node,
        "_worker_id": worker_id,
        "_is_android": False,
        **extra,
    }


class _Alerts:
    """An in-memory stand-in for the alerts table and its dedupe."""

    def __init__(self, last_event=None):
        self.rows: dict[str, str] = {}
        self.pushed: list[str] = []
        self.last_event = last_event

    async def record(self, kind, subject, message, **_):
        if subject in self.rows:
            self.rows[subject] = message
            return None
        self.rows[subject] = message
        return len(self.rows)

    async def subjects(self, kind):
        return set(self.rows)

    async def clear(self, kind=None, subject=None):
        self.rows.pop(subject, None)

    def run(self, statuses):
        def spawn(coro):
            coro.close()
            self.pushed.append("push")

        with (
            patch.object(main.database, "record_alert", self.record),
            patch.object(main.database, "get_alert_subjects", self.subjects),
            patch.object(main.database, "clear_alerts", self.clear),
            patch.object(main.database, "get_last_lifecycle_event", AsyncMock(return_value=self.last_event)),
            patch.object(main, "_spawn", spawn),
        ):
            asyncio.run(main._container_down_check(statuses))


class TestADownContainerIsAnAlert:
    def test_exited_past_the_grace_period_alerts_once(self):
        alerts = _Alerts()
        statuses = [
            _entry(node=n, worker_id=i, finished_at=_ago(days=2), exit_code=0, restart_policy="no")
            for i, n in enumerate(("watchtower", "geiserback", "geiserct"))
        ]
        for _ in range(3):
            alerts.run(statuses)
        assert list(alerts.rows) == ["urnetwork"]
        assert len(alerts.pushed) == 1, "one push per service, not one per check or per server"
        message = alerts.rows["urnetwork"]
        assert "geiserback" in message and "geiserct" in message and "watchtower" in message
        assert "exit code 0" in message

    def test_it_reaches_the_bell(self):
        _Alerts().run([_entry(finished_at=_ago(hours=1))])
        assert [a["kind"] for a in main._collector_alerts] == ["container"]

    def test_a_restart_policy_of_no_is_named_in_the_alert(self):
        alerts = _Alerts()
        alerts.run([_entry(finished_at=_ago(hours=1), restart_policy="no")])
        assert 'restart policy is "no"' in alerts.rows["urnetwork"]

    def test_unless_stopped_is_not_called_out(self):
        alerts = _Alerts()
        alerts.run([_entry(finished_at=_ago(hours=1), restart_policy="unless-stopped")])
        assert "restart policy" not in alerts.rows["urnetwork"]

    def test_a_worker_without_finished_at_alerts_after_the_grace_period(self):
        """An older worker reports no timestamp; the UI times it from first sight."""
        alerts = _Alerts()
        alerts.run([_entry()])
        assert not alerts.rows, "seen down for the first time is not yet 30 minutes"
        key = next(iter(main._container_first_seen_down))
        main._container_first_seen_down[key] = datetime.now(UTC) - timedelta(minutes=31)
        alerts.run([_entry()])
        assert "urnetwork" in alerts.rows


class TestWhatIsNotAnAlert:
    def test_inside_the_grace_period(self):
        alerts = _Alerts()
        alerts.run([_entry(finished_at=_ago(minutes=10))])
        assert not alerts.rows

    def test_a_running_container(self):
        alerts = _Alerts()
        alerts.run([_entry("running")])
        assert not alerts.rows

    def test_a_stop_made_from_cashpilot(self):
        stopped = (datetime.now(UTC) - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
        alerts = _Alerts(last_event=("stop", stopped))
        alerts.run([_entry(finished_at=_ago(hours=3))])
        assert not alerts.rows

    def test_a_stop_long_before_the_exit_does_not_explain_it(self):
        """The control for the case above: an old stop must not hide a later crash."""
        stopped = (datetime.now(UTC) - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
        alerts = _Alerts(last_event=("stop", stopped))
        alerts.run([_entry(finished_at=_ago(hours=3))])
        assert "urnetwork" in alerts.rows

    def test_an_external_container_or_an_android_app(self):
        alerts = _Alerts()
        alerts.run(
            [
                _entry(deployed_by="external", finished_at=_ago(days=1)),
                {**_entry("stopped", slug="earnapp", finished_at=_ago(days=1)), "_is_android": True},
            ]
        )
        assert not alerts.rows


class TestItClearsByItself:
    def test_running_again_clears_the_alert_and_the_bell(self):
        alerts = _Alerts()
        alerts.run([_entry(finished_at=_ago(hours=2))])
        assert "urnetwork" in alerts.rows
        alerts.run([_entry("running")])
        assert not alerts.rows
        assert not [a for a in main._collector_alerts if a.get("kind") == "container"]

    def test_a_copy_still_inside_the_grace_period_does_not_clear(self):
        """After a UI restart an old worker's container restarts its clock; that is not a recovery."""
        alerts = _Alerts()
        alerts.rows["urnetwork"] = "stored before the restart"
        alerts.run([_entry()])
        assert "urnetwork" in alerts.rows


class TestTheWorkerReportsWhyItStopped:
    def _container(self, status, state, policy):
        return SimpleNamespace(status=status, attrs={"State": state, "HostConfig": {"RestartPolicy": {"Name": policy}}})

    def test_an_exited_container_carries_its_stop_facts(self):
        c = self._container("exited", {"FinishedAt": "2026-10-26T15:15:03.5Z", "ExitCode": 0}, "")
        assert orchestrator._stop_facts(c) == {
            "finished_at": "2026-10-26T15:15:03.5Z",
            "exit_code": 0,
            "restart_policy": "no",
        }

    def test_a_running_container_carries_none(self):
        c = self._container("running", {"FinishedAt": "0001-01-01T00:00:00Z", "ExitCode": 0}, "unless-stopped")
        assert orchestrator._stop_facts(c) == {}

    def test_dockers_zero_time_is_not_a_date(self):
        c = self._container("exited", {"FinishedAt": "0001-01-01T00:00:00Z"}, "always")
        assert "finished_at" not in orchestrator._stop_facts(c)

    def test_the_ui_keeps_the_facts_from_the_heartbeat(self):
        import json

        worker = {
            "id": 7,
            "name": "geiserback",
            "status": "online",
            "system_info": json.dumps({"docker_available": True}),
            "containers": json.dumps(
                [
                    {
                        "slug": "urnetwork",
                        "status": "exited",
                        "finished_at": "2026-10-26T15:15:03Z",
                        "exit_code": 0,
                        "restart_policy": "no",
                    }
                ]
            ),
        }
        [entry] = asyncio.run(main._get_all_worker_containers([worker]))
        assert entry["finished_at"] == "2026-10-26T15:15:03Z"
        assert entry["restart_policy"] == "no"
        assert entry["exit_code"] == 0
