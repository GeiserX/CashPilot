"""A proxied copy or its tunnel gone or down outside CashPilot raises an alert.

The status report the container-down and missing-deployment checks read leaves
proxied copies and their tunnels out (orchestrator.is_proxied), so a copy like
cashpilot-earnfm-p3, or the shared cashpilot-tunnel-p3 every copy through proxy
3 lives in, could vanish and nobody was told. _proxied_copy_check compares the
proxied_copies records with each worker's ``proxied`` report.
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
    monkeypatch.setattr(main, "_proxied_first_seen", {})
    monkeypatch.setattr(main, "_proxied_bell", {})
    monkeypatch.setattr(main, "_collector_alerts", [])
    monkeypatch.setattr(main, "_account_disabled", {})


def _worker(
    entries, *, wid=1, name="alpha", online=True, docker=True, features=("instances", "proxy_tunnel"), containers=()
):
    info = {"docker_available": docker, "features": list(features), "proxied": entries}
    return {
        "id": wid,
        "name": name,
        "status": "online" if online else "offline",
        "system_info": json.dumps(info),
        "containers": json.dumps(list(containers)),
    }


def _entry(slug, *, pid=3, status="running", tunnel="running", held=False, shared=True):
    e = {
        "slug": slug,
        "proxy_id": pid,
        "name": f"cashpilot-{slug}-p{pid}",
        "status": status,
        "tunnel_status": tunnel,
        "tunnel_shared": shared,
    }
    if held is not None:
        e["held"] = held
    return e


def _copy(slug, *, pid=3, wid=1, **extra):
    return {"proxy_id": pid, "worker_id": wid, "slug": slug, "stopped_by_cap": 0, "removing_since": None, **extra}


def _proxy(pid=3, **state):
    return {"id": pid, "definition": {"name": "home socks"}, "state": state}


class _Alerts:
    """The alerts table and its dedupe, in memory."""

    def __init__(self, copies, proxies=None, placements=None):
        self.copies = copies
        self.proxies = proxies if proxies is not None else [_proxy()]
        # Every copy's service is deployed on its box unless a test says otherwise.
        self.placements = (
            placements if placements is not None else [{"slug": c["slug"], "worker_id": c["worker_id"]} for c in copies]
        )
        self.rows: dict[str, str] = {}
        self.titles: list[str] = []

    async def record(self, kind, subject, message, **_):
        assert kind == "proxied"
        fresh = subject not in self.rows
        self.rows[subject] = message
        return len(self.rows) if fresh else None

    async def subjects(self, kind):
        return set(self.rows) if kind == "proxied" else set()

    async def clear(self, kind=None, subject=None):
        self.rows.pop(subject, None)

    def run(self, workers, *, age=None):
        def spawn(coro):
            # _push_alert(kind, subject, title, ...): keep the title.
            self.titles.append(coro.cr_frame.f_locals["title"])
            coro.close()

        with (
            patch.object(main.database, "record_alert", self.record),
            patch.object(main.database, "get_alert_subjects", self.subjects),
            patch.object(main.database, "clear_alerts", self.clear),
            patch.object(main.database, "list_proxied_copies", AsyncMock(return_value=self.copies)),
            patch.object(main.database, "list_proxies", AsyncMock(return_value=self.proxies)),
            patch.object(main.database, "list_deployment_placements", AsyncMock(return_value=self.placements)),
            patch.object(main, "_spawn", spawn),
        ):
            if age is not None:
                for key in main._proxied_first_seen:
                    main._proxied_first_seen[key] = datetime.now(UTC) - age
            asyncio.run(main._proxied_copy_check(workers))


PAST_GRACE = timedelta(minutes=31)


def _past_grace(alerts, workers):
    """First sight, then the same picture past the grace period."""
    alerts.run(workers)
    alerts.run(workers, age=PAST_GRACE)


class TestAGoneCopyIsAnAlert:
    def test_a_copy_gone_from_its_box_alerts_once_after_the_grace_period(self):
        alerts = _Alerts([_copy("earnfm"), _copy("honeygain")])
        workers = [_worker([_entry("honeygain")])]
        alerts.run(workers)
        assert not alerts.rows, "first seen gone is not yet 30 minutes"
        alerts.run(workers, age=PAST_GRACE)
        alerts.run(workers)
        assert list(alerts.rows) == ["cashpilot-earnfm-p3@1"]
        assert alerts.titles == ["CashPilot: cashpilot-earnfm-p3 is gone from alpha"]
        assert "alpha" in alerts.rows["cashpilot-earnfm-p3@1"] and "home socks" in alerts.rows["cashpilot-earnfm-p3@1"]

    def test_it_reaches_the_bell_without_a_credential_button_kind(self):
        alerts = _Alerts([_copy("earnfm")])
        _past_grace(alerts, [_worker([])])
        assert [(a["kind"], a["platform"]) for a in main._collector_alerts] == [("proxied", "cashpilot-earnfm-p3")]

    def test_a_copy_that_is_back_clears_its_alert_and_its_bell_entry(self):
        alerts = _Alerts([_copy("earnfm")])
        _past_grace(alerts, [_worker([])])
        assert alerts.rows
        alerts.run([_worker([_entry("earnfm")])])
        assert not alerts.rows and not main._collector_alerts

    def test_a_crashed_copy_beside_a_running_tunnel_alerts(self):
        alerts = _Alerts([_copy("earnfm")])
        _past_grace(alerts, [_worker([_entry("earnfm", status="exited")])])
        assert alerts.titles == ["CashPilot: cashpilot-earnfm-p3 has stopped running"]

    def test_a_fresh_copy_gets_the_whole_grace_from_its_record(self):
        just_now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        alerts = _Alerts([_copy("earnfm", created_at=just_now)])
        _past_grace(alerts, [_worker([])])
        assert not alerts.rows


class TestOneAlertPerTunnel:
    def test_a_missing_shared_tunnel_is_one_alert_naming_every_copy_in_it(self):
        alerts = _Alerts([_copy("earnfm"), _copy("honeygain"), _copy("repocket")])
        entries = [_entry(s, status="exited", tunnel="missing", shared=False) for s in ("earnfm", "honeygain")]
        _past_grace(alerts, [_worker([*entries, _entry("repocket", status="exited", tunnel="missing")])])
        assert list(alerts.rows) == ["cashpilot-tunnel-p3@1"]
        message = alerts.rows["cashpilot-tunnel-p3@1"]
        for slug in ("earnfm", "honeygain", "repocket"):
            assert f"cashpilot-{slug}-p3" in message
        assert alerts.titles == ["CashPilot: cashpilot-tunnel-p3 is gone from alpha"]

    def test_a_stopped_tunnel_with_copies_that_should_run_alerts(self):
        alerts = _Alerts([_copy("earnfm")])
        _past_grace(alerts, [_worker([_entry("earnfm", status="exited", tunnel="exited")])])
        assert alerts.titles == ["CashPilot: cashpilot-tunnel-p3 has stopped running"]


def _stuck(
    entry,
    *,
    age=7200,
    reason="The new tunnel of cashpilot-tunnel-p3 could not start, so its copies stay in the tunnel they run in",
):
    """An entry of a copy in the staged tunnel of a change the worker could not finish."""
    return {
        **entry,
        "tunnel_status": "missing",
        "tunnel_shared": False,
        "tunnel_change": {"tunnel": "cashpilot-tunnel-p3-next", "age_seconds": age, "reason": reason},
    }


class TestAStuckTunnelChangeSaysSo:
    """The worker reports the copies of a tunnel change it could not finish
    (proxy_tunnel._finish_stale_staged); they are not gone, the change is stuck."""

    def test_one_stuck_alert_per_tunnel_with_its_age_and_reason_instead_of_is_gone(self):
        alerts = _Alerts([_copy("earnfm"), _copy("honeygain"), _copy("repocket")])
        entries = [_stuck(_entry("earnfm")), _stuck(_entry("honeygain")), _entry("repocket")]
        _past_grace(alerts, [_worker(entries)])
        assert list(alerts.rows) == ["cashpilot-tunnel-p3-next@1"]
        assert alerts.titles == ["CashPilot: the tunnel change of home socks on alpha is stuck"]
        message = alerts.rows["cashpilot-tunnel-p3-next@1"]
        assert "2 h 0 min" in message and "could not start" in message
        assert "cashpilot-earnfm-p3, cashpilot-honeygain-p3" in message and "repocket" not in message
        assert "is gone" not in message

    def test_it_waits_out_the_grace_like_any_other(self):
        alerts = _Alerts([_copy("earnfm")])
        alerts.run([_worker([_stuck(_entry("earnfm"))])])
        assert not alerts.rows

    def test_it_clears_once_the_change_finishes(self):
        alerts = _Alerts([_copy("earnfm")])
        _past_grace(alerts, [_worker([_stuck(_entry("earnfm"))])])
        assert alerts.rows
        alerts.run([_worker([_entry("earnfm")])])
        assert not alerts.rows and not main._collector_alerts

    def test_a_box_that_cannot_tell_keeps_it(self):
        alerts = _Alerts([_copy("earnfm")])
        _past_grace(alerts, [_worker([_stuck(_entry("earnfm"))])])
        alerts.run([_worker([_stuck(_entry("earnfm"))], online=False)])
        assert list(alerts.rows) == ["cashpilot-tunnel-p3-next@1"]
        assert main._collector_alerts

    def test_an_older_worker_that_does_not_report_it_keeps_the_is_gone_alert(self):
        alerts = _Alerts([_copy("earnfm")])
        old = _stuck(_entry("earnfm"))
        del old["tunnel_change"]
        _past_grace(alerts, [_worker([old])])
        assert alerts.titles == ["CashPilot: cashpilot-tunnel-p3 is gone from alpha"]


class TestNothingCashPilotDidOnPurpose:
    @pytest.mark.parametrize(
        ("copy", "proxy"),
        [
            pytest.param({"removing_since": "2026-11-09 10:00:00"}, {}, id="being-removed"),
            pytest.param({"stopped_by_cap": 1}, {}, id="stopped-by-the-cap"),
            pytest.param({}, {"capped_at": "2026-11-09T10:00:00"}, id="proxy-capped"),
        ],
    )
    def test_a_copy_cashpilot_stopped_or_is_removing_is_quiet(self, copy, proxy):
        alerts = _Alerts([_copy("earnfm", **copy)], [_proxy(**proxy)])
        _past_grace(alerts, [_worker([])])
        assert not alerts.rows

    def test_a_copy_the_owner_stopped_is_quiet_and_so_is_its_stopped_tunnel(self):
        alerts = _Alerts([_copy("earnfm")])
        _past_grace(alerts, [_worker([_entry("earnfm", status="exited", tunnel="exited", held=True)])])
        assert not alerts.rows

    def test_an_older_worker_that_does_not_say_held_alerts_only_on_what_is_gone(self):
        alerts = _Alerts([_copy("earnfm"), _copy("honeygain")])
        workers = [_worker([_entry("earnfm", status="exited", tunnel="exited", held=None)])]
        _past_grace(alerts, workers)
        assert list(alerts.rows) == ["cashpilot-honeygain-p3@1"]

    def test_a_copy_whose_service_was_removed_from_the_box_is_quiet(self):
        # The worker's remove_all took the copies with the service, but a
        # partial failure (proxied_error) or a raw remove left their records.
        alerts = _Alerts([_copy("earnfm"), _copy("earnfm", pid=4)], [_proxy(), _proxy(4)], placements=[])
        _past_grace(alerts, [_worker([_entry("earnfm", pid=4)])])
        assert not alerts.rows

    def test_a_service_deployed_before_per_box_records_still_alerts_while_the_box_runs_it(self):
        # No placement row, but the box reports the base service: it is deployed there.
        alerts = _Alerts([_copy("earnfm")], placements=[])
        base = {"slug": "earnfm", "name": "cashpilot-earnfm", "status": "running"}
        _past_grace(alerts, [_worker([], containers=[base])])
        assert list(alerts.rows) == ["cashpilot-earnfm-p3@1"]

    def test_a_stored_alert_clears_once_the_service_is_removed_from_the_box(self):
        alerts = _Alerts([_copy("earnfm")])
        _past_grace(alerts, [_worker([])])
        assert alerts.rows
        alerts.placements = []
        alerts.run([_worker([])])
        assert not alerts.rows and not main._collector_alerts

    def test_a_disabled_account_is_quiet(self, monkeypatch):
        monkeypatch.setattr(main, "_account_disabled", {"earnfm": "disabled"})
        alerts = _Alerts([_copy("earnfm")])
        _past_grace(alerts, [_worker([])])
        assert not alerts.rows


class TestABoxThatCannotTellIsNotEverythingMissing:
    @pytest.mark.parametrize(
        "worker",
        [
            pytest.param(_worker([], online=False), id="offline"),
            pytest.param(_worker([], docker=False), id="blind"),
            pytest.param(_worker([], features=("instances",)), id="too-old"),
            pytest.param(_worker(None), id="read-failed"),
        ],
    )
    def test_nothing_is_raised_and_a_stored_alert_is_kept(self, worker):
        alerts = _Alerts([_copy("earnfm")])
        _past_grace(alerts, [worker])
        assert not alerts.rows
        alerts.rows["cashpilot-earnfm-p3@1"] = "stored before"
        main._proxied_bell["cashpilot-earnfm-p3@1"] = {"kind": "proxied", "platform": "x", "error": "stored before"}
        alerts.run([worker])
        assert alerts.rows == {"cashpilot-earnfm-p3@1": "stored before"}
        assert main._collector_alerts, "the bell keeps what it cannot re-check"

    def test_a_blind_box_keeps_the_alert_of_a_service_deployed_before_per_box_records(self):
        # No placement row, and the blind box reports no containers either: that
        # is not the service being removed, so the stored alert must stay.
        alerts = _Alerts([_copy("earnfm")], placements=[])
        base = {"slug": "earnfm", "name": "cashpilot-earnfm", "status": "running"}
        _past_grace(alerts, [_worker([], containers=[base])])
        assert list(alerts.rows) == ["cashpilot-earnfm-p3@1"]
        alerts.run([_worker([], docker=False)])
        assert list(alerts.rows) == ["cashpilot-earnfm-p3@1"]
        assert main._collector_alerts, "the bell keeps what it cannot re-check"

    def test_a_stored_alert_skips_the_grace_after_a_restart_and_is_not_pushed_again(self):
        alerts = _Alerts([_copy("earnfm")])
        alerts.rows["cashpilot-earnfm-p3@1"] = "stored before"
        alerts.run([_worker([])])
        assert main._collector_alerts and not alerts.titles


class TestTheWorkerSaysWhenItCouldNotLook:
    def test_a_failed_read_is_sent_as_none_not_an_empty_list(self):
        from app import worker_api

        sent: dict = {}

        class Resp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"status": "ok"}

        class Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, json=None, headers=None):
                sent.update(json)
                return Resp()

        with (
            patch("app.worker_api.orchestrator.get_status", return_value=[]),
            patch("app.worker_api.orchestrator.docker_available", return_value=True),
            patch("app.worker_api._detect_egress_ip", new_callable=AsyncMock, return_value=None),
            patch("app.worker_api._check_fence", new_callable=AsyncMock),
            patch("app.worker_api._disk_usage", return_value=None),
            patch("app.worker_api._gpu_info", return_value={}),
            patch("app.worker_api.proxy_tunnel.status", side_effect=RuntimeError("daemon down")),
            patch("app.worker_api.httpx.AsyncClient", Client),
            patch("app.worker_api.UI_URL", "http://ui:8080"),
        ):
            asyncio.run(worker_api._send_heartbeat())
        assert sent["system_info"]["proxied"] is None


def test_the_health_check_runs_it_with_the_workers_it_read():
    workers = [_worker([])]
    check = AsyncMock()
    with (
        patch.object(main.database, "list_workers", AsyncMock(return_value=workers)),
        patch.object(main.database, "get_deployments", AsyncMock(return_value=[])),
        patch.object(main.database, "record_health_events", AsyncMock()),
        patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=[])),
        patch.object(main, "_container_down_check", AsyncMock()),
        patch.object(main, "_account_disabled_check", AsyncMock()),
        patch.object(main, "_missing_deployment_check", AsyncMock()),
        patch.object(main, "_proxied_copy_check", check),
    ):
        asyncio.run(main._run_health_check())
    check.assert_awaited_once_with(workers)


class TestTheDashboardSaysSo:
    """The attention list, run in node against the real app.js."""

    def test_a_proxied_alert_is_a_card_on_the_attention_list(self):
        import os
        import shutil
        import subprocess

        from tests.test_account_disabled import _HARNESS, ROOT

        node = shutil.which("node")
        if not node:
            pytest.skip("node is not installed")
        harness = _HARNESS.replace(": { alerts: [] };", ": JSON.parse(process.env.BELL);")
        assert harness != _HARNESS
        bell = {"alerts": [{"kind": "proxied", "platform": "cashpilot-tunnel-p3", "error": "The tunnel is gone"}]}
        svc = {"slug": "earnfm", "name": "EarnFM", "instance_details": []}
        out = subprocess.run(
            [node, "-e", harness, str(ROOT / "app/static/js/app.js"), json.dumps(svc)],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "BELL": json.dumps(bell)},
        )
        result = json.loads(out.stdout)
        assert "error" not in result, result
        assert "Proxied copy down" in result["tags"]
        assert "cashpilot-tunnel-p3" in result["html"] and "The tunnel is gone" in result["html"]

    def test_the_list_is_drawn_again_when_the_bell_poll_sees_the_alerts_change(self):
        """The list is drawn on the services refresh; the bell polls on its own.
        An alert that appears between the two must reach the list too."""
        import shutil
        import subprocess

        from tests.test_account_disabled import _HARNESS, ROOT

        node = shutil.which("node")
        if not node:
            pytest.skip("node is not installed")
        harness = _HARNESS.replace(
            ": { alerts: [] };",
            ": fetchFails ? Promise.reject(new Error('down')) : { alerts: bell };\nlet bell = [], fetchFails = false;",
        )
        harness = harness.replace(
            "return renderAttention;`)", "return [renderAttention, refreshAttentionOnAlertChange];`)"
        )
        start = harness.index("run([svc]")
        harness = (
            harness[:start]
            + """const [render, refresh] = run;
const tagsNow = () => [...els['attention-list'].innerHTML.matchAll(/class="attn-tag">([^<]*)</g)].map(m => m[1]);
(async () => {
  await render([svc], [{ id: 1, name: 'charlie', status: 'online' }]);
  const first = refresh(bell);
  const before = tagsNow();
  const same = refresh(bell);
  bell = [{ kind: 'proxied', platform: 'cashpilot-tunnel-p3', error: 'The tunnel is gone' }];
  // The redraw uses the alerts the poll read: a second fetch that fails must not lose them.
  fetchFails = true;
  await refresh(bell);
  fetchFails = false;
  const appeared = tagsNow();
  bell = [];
  await refresh(bell);
  console.log(JSON.stringify({ first, same, before, appeared, cleared: tagsNow() }));
})();
"""
        )
        svc = {"slug": "earnfm", "name": "EarnFM", "instance_details": []}
        out = subprocess.run(
            [node, "-e", harness, str(ROOT / "app/static/js/app.js"), json.dumps(svc)],
            capture_output=True,
            text=True,
            check=True,
        )
        result = json.loads(out.stdout)
        assert result["first"] is None and result["same"] is None, "an unchanged poll must not redraw"
        assert "Proxied copy down" not in result["before"]
        assert "Proxied copy down" in result["appeared"]
        assert "Proxied copy down" not in result["cleared"]

    def test_the_bell_poll_hands_its_alerts_to_that_check(self):
        from tests.test_account_disabled import ROOT

        src = (ROOT / "app/static/js/app.js").read_text()
        poll = src[src.index("  async function loadCollectorAlerts() {") :]
        assert "refreshAttentionOnAlertChange(alerts);" in poll[: poll.index("\n  }\n")]
