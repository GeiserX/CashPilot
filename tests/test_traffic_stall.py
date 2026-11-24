"""A running copy that sends almost nothing while its service's other copies are busy raises one alert.

A Honeygain copy can stay connected after a dropped session and get no work for
days. Its container runs, its log says it runs, and the balance still grows from
the other copies, so no other check saw it: the copy sends a fraction of a MB an
hour while the others send tens of MB. A service opts in with
docker.traffic_stall; the UI compares each copy's hourly bytes sent with the
median of the other copies and alerts. It never restarts anything.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from app import catalog, main, traffic_stall
from app.traffic_stall import MB, Spec, Stall

ROOT = Path(__file__).resolve().parent.parent
SPEC = Spec(share=0.05, peer_min_bytes=10 * MB, hours=12)
NOW = 1_800_000_600.0  # ten minutes into an hour
LAST = traffic_stall.last_whole_hour(NOW)
A, B, C = (1, "cashpilot-honeygain"), (2, "cashpilot-honeygain"), (3, "cashpilot-honeygain")


def _rows(sent_mb, *, end=LAST, slug="honeygain", received_mb=0.0, seconds=3600.0):
    """usage_hourly rows: per copy, MB sent in each hour, oldest first, the last one in hour ``end``.

    None is an hour with no row at all.
    """
    rows = []
    for (wid, container), series in sent_mb.items():
        for i, mb in enumerate(series):
            if mb is None:
                continue
            rows.append(
                {
                    "worker_id": wid,
                    "container": container,
                    "hour": end - 3600 * (len(series) - 1 - i),
                    "slug": slug,
                    "tx_bytes": int(mb * MB * seconds / 3600),
                    "rx_bytes": int(received_mb * MB * seconds / 3600),
                    "net_seconds": seconds,
                }
            )
    return rows


def _judge(sent_mb, **kw):
    return traffic_stall.judge(_rows(sent_mb, **kw), SPEC, NOW)


class TestWhatIsAStall:
    def test_a_copy_far_below_its_busy_peers_for_twelve_whole_hours_is_stalled(self):
        stalled, carrying = _judge({A: [30] * 12, B: [25] * 12, C: [0.3] * 12})
        assert list(stalled) == [C]
        assert stalled[C].sent == pytest.approx(0.3 * MB, rel=0.01)
        assert stalled[C].peers == pytest.approx(27.5 * MB, rel=0.01)
        assert carrying == {A, B}

    def test_eleven_hours_is_not_yet(self):
        stalled, carrying = _judge({A: [30] * 12, B: [25] * 12, C: [30] + [0.3] * 11})
        assert not stalled
        assert C not in carrying, "still quiet in the last hour: undecided, not recovered"

    def test_the_hour_in_progress_is_left_out(self):
        assert LAST == 1_800_000_000 - 3600, "the hour that started at 1_800_000_000 is still running at NOW"
        rows = _rows({A: [30] * 12, B: [25] * 12, C: [0.3] * 12}) + _rows({C: [40]}, end=LAST + 3600)
        stalled, _ = traffic_stall.judge(rows, SPEC, NOW)
        assert C in stalled

    def test_two_stalled_copies_of_three_are_both_seen(self):
        """The median of the others, not all of them: one busy copy is enough to compare with."""
        stalled, _ = _judge({A: [40] * 12, B: [0.3] * 12, C: [0.3] * 12})
        assert set(stalled) == {B, C}

    def test_no_stall_while_the_other_copies_are_quiet_too(self):
        """A quiet hour for the whole service (no demand) is no stall of one copy."""
        stalled, carrying = _judge({A: [6] * 12, B: [5] * 12, C: [0.1] * 12})
        assert not stalled
        assert C not in carrying

    @pytest.mark.parametrize("gap", [None, "no counter"])
    def test_an_hour_without_a_reading_gives_no_verdict(self, gap):
        rows = _rows({A: [30] * 12, B: [25] * 12, C: [0.3] * 5 + [None] + [0.3] * 6})
        if gap == "no counter":
            rows += [{**rows[-1], "hour": LAST - 6 * 3600, "tx_bytes": None}]
        stalled, _ = traffic_stall.judge(rows, SPEC, NOW)
        assert not stalled, "an hour with no reading is unknown, never zero"

    def test_received_bytes_do_not_hide_a_stall(self):
        """Some hosts deliver a few MB an hour of broadcasts to every container."""
        stalled, _ = _judge({A: [30] * 12, B: [25] * 12, C: [0.3] * 12}, received_mb=6)
        assert C in stalled

    def test_a_lone_copy_is_never_stalled(self):
        assert _judge({C: [0.3] * 12}) == ({}, set())

    def test_rates_are_per_hour_of_measured_time(self):
        """Half an hour of readings is not drawn as half the traffic."""
        rows = _rows({C: [30]}, seconds=1800.0)
        assert traffic_stall.sent_per_hour(rows)[C][LAST] == pytest.approx(30 * MB)


class TestWhenACopyCarriesTrafficAgain:
    def test_at_the_share_of_busy_peers(self):
        _, carrying = _judge({A: [30] * 12, B: [25] * 12, C: [0.3] * 11 + [2]})
        assert C in carrying

    def test_at_the_floor_whatever_the_peers_do(self):
        _, carrying = _judge({A: [6] * 12, B: [5] * 12, C: [0.3] * 11 + [12]})
        assert C in carrying

    def test_not_at_a_share_of_peers_that_are_quiet_too(self):
        _, carrying = _judge({A: [6] * 12, B: [5] * 12, C: [0.3] * 11 + [0.4]})
        assert C not in carrying


class TestTheDeclaration:
    def test_every_key_has_a_default(self):
        assert traffic_stall.spec_of({"docker": {"traffic_stall": {}}}) == SPEC

    def test_a_service_without_it_has_none(self):
        assert traffic_stall.spec_of({"docker": {}}) is None
        assert traffic_stall.spec_of(None) is None

    @pytest.mark.parametrize(
        "raw",
        [
            [],
            {"share": 0},
            {"share": 1},
            {"share": True},
            {"share": "5%"},
            {"peer_min_mb_per_hour": 0},
            {"peer_min_mb_per_hour": float("nan")},
            {"hours": 0},
            {"hours": 1.5},
            {"hours": traffic_stall.MAX_HOURS + 1},
            {"hours": True},
            {"window_hours": 12},
        ],
    )
    def test_a_broken_one_is_refused(self, raw):
        assert traffic_stall.spec_errors(raw)
        assert traffic_stall.spec_of({"docker": {"traffic_stall": raw}}) is None

    def test_honeygain_declares_it(self):
        assert traffic_stall.spec_of(catalog.get_service("honeygain")) == SPEC

    def test_the_loader_refuses_a_broken_one(self):
        path = ROOT / "services" / "bandwidth" / "honeygain.yml"
        data = yaml.safe_load(path.read_text())
        assert not catalog._validate(copy.deepcopy(data), path)
        data["docker"]["traffic_stall"]["share"] = 2
        assert any("docker.traffic_stall: share" in e for e in catalog._validate(data, path))

    def test_the_worker_image_carries_it(self):
        """catalog.py imports it, and the worker image copies catalog.py."""
        assert "COPY app/traffic_stall.py ./app/" in (ROOT / "Dockerfile.worker").read_text()


# --- The check the health check runs ---------------------------------------


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.setattr(main, "_stall_bell", {})
    monkeypatch.setattr(main, "_collector_alerts", [])


WORKERS = [
    {"id": i, "name": n, "status": "online", "system_info": json.dumps({"docker_available": True})}
    for i, n in ((1, "alpha"), (2, "bravo"), (3, "charlie"))
]


def _statuses(slug="honeygain", **status_of):
    return [
        {"slug": slug, "name": f"cashpilot-{slug}", "status": status_of.get(n, "running"), "_worker_id": i}
        for i, n in ((1, "alpha"), (2, "bravo"), (3, "charlie"))
    ]


def _live_rows(a, b, c, slug="honeygain"):
    """Rows ending in the hour now in progress, so an hour that turns during the test changes nothing."""
    container = f"cashpilot-{slug}"
    end = traffic_stall.last_whole_hour(time.time()) + 3600
    copies = {(1, container): a + a[-1:], (2, container): b + b[-1:], (3, container): c + c[-1:]}
    return _rows(copies, end=end, slug=slug)


STALLED = ([30] * 12, [25] * 12, [0.3] * 12)
SUBJECT = "cashpilot-honeygain@3"


class _Alerts:
    """The alerts table and its dedupe, in memory."""

    def __init__(self):
        self.rows: dict[str, str] = {}
        self.titles: list[str] = []

    async def record(self, kind, subject, message, **_):
        assert kind == "stall"
        fresh = subject not in self.rows
        self.rows[subject] = message
        return len(self.rows) if fresh else None

    async def subjects(self, kind):
        return set(self.rows) if kind == "stall" else set()

    async def clear(self, kind=None, subject=None):
        assert kind == "stall"
        self.rows.pop(subject, None)

    def run(self, rows, *, workers=WORKERS, statuses=None):
        def spawn(coro):
            # _push_alert(kind, subject, title, ...): keep the title.
            self.titles.append(coro.cr_frame.f_locals["title"])
            coro.close()

        restart = AsyncMock()
        with (
            patch.object(main.database, "record_alert", self.record),
            patch.object(main.database, "get_alert_subjects", self.subjects),
            patch.object(main.database, "clear_alerts", self.clear),
            patch.object(main.database, "get_usage_hourly", AsyncMock(return_value=rows)),
            patch.object(main, "_spawn", spawn),
            patch.object(main, "_command_and_record", restart),
        ):
            asyncio.run(main._traffic_stall_check(workers, _statuses() if statuses is None else statuses))
        assert not restart.called, "alerts only: it never restarts a copy"


def _bell():
    return [(a["kind"], a["platform"]) for a in main._collector_alerts if a.get("kind") == "stall"]


class TestAStallIsAnAlert:
    def test_one_alert_and_one_push_however_often_it_runs(self):
        alerts = _Alerts()
        for _ in range(3):
            alerts.run(_live_rows(*STALLED))
        assert list(alerts.rows) == [SUBJECT]
        assert alerts.titles == ["CashPilot: Honeygain on charlie carries almost no traffic"]
        message = alerts.rows[SUBJECT]
        assert "Honeygain on charlie" in message and "12 hours" in message
        assert "0.3 MB an hour" in message and "27.5 MB an hour" in message
        assert "does not restart it" in message
        assert "restart it from the dashboard" in message[: main._MAX_ALERT_ERROR_LEN], "the bell cuts the rest"

    def test_it_reaches_the_bell(self):
        _Alerts().run(_live_rows(*STALLED))
        assert _bell() == [("stall", "cashpilot-honeygain")]

    def test_not_for_a_copy_that_no_longer_runs(self):
        alerts = _Alerts()
        alerts.run(_live_rows(*STALLED), statuses=_statuses(charlie="exited"))
        assert not alerts.rows and not _bell()

    def test_not_for_a_service_that_does_not_declare_it(self):
        alerts = _Alerts()
        alerts.run(_live_rows(*STALLED, slug="earnfm"), statuses=_statuses("earnfm"))
        assert not alerts.rows


class TestItClearsOnlyWhenItCanTell:
    def _raised(self):
        alerts = _Alerts()
        alerts.run(_live_rows(*STALLED))
        assert SUBJECT in alerts.rows
        return alerts

    def test_it_clears_once_the_copy_carries_traffic_again(self):
        alerts = self._raised()
        alerts.run(_live_rows([30] * 12, [25] * 12, [0.3] * 11 + [20]))
        assert not alerts.rows and not _bell()

    def test_it_clears_once_the_copy_stops(self):
        alerts = self._raised()
        alerts.run(_live_rows(*STALLED), statuses=_statuses(charlie="exited"))
        assert not alerts.rows and not _bell()

    def test_it_stays_while_its_box_is_offline(self):
        alerts = self._raised()
        offline = [{**w, "status": "offline"} if w["id"] == 3 else w for w in WORKERS]
        alerts.run([], workers=offline, statuses=_statuses()[:2])
        assert SUBJECT in alerts.rows and _bell() == [("stall", "cashpilot-honeygain")]

    def test_it_clears_once_its_box_is_removed(self):
        """A removed box never reports again: waiting for it kept the alert for good."""
        alerts = self._raised()
        alerts.run([], workers=WORKERS[:2], statuses=_statuses()[:2])
        assert not alerts.rows and not _bell()

    @pytest.mark.parametrize(
        "info",
        [{"docker_available": False}, {"docker_available": True, "containers_listed": False}],
        ids=["cannot read Docker", "partial list"],
    )
    def test_it_stays_while_its_box_cannot_list_what_runs(self, info):
        """Such a box leaves out copies that still run there, so their absence says nothing."""
        alerts = self._raised()
        blind = [{**w, "system_info": json.dumps(info)} if w["id"] == 3 else w for w in WORKERS]
        alerts.run(_live_rows(*STALLED), workers=blind, statuses=_statuses()[:2])
        assert SUBJECT in alerts.rows and _bell() == [("stall", "cashpilot-honeygain")]
        assert len(alerts.titles) == 1

    def test_a_crash_loop_is_one_push(self):
        """Docker lists a crash-looping copy as restarting between its runs: that neither clears nor re-arms."""
        alerts = self._raised()
        for _ in range(3):
            alerts.run(_live_rows(*STALLED), statuses=_statuses(charlie="restarting"))
            assert SUBJECT in alerts.rows and _bell() == [("stall", "cashpilot-honeygain")]
            alerts.run(_live_rows(*STALLED))
        assert len(alerts.titles) == 1, "one push, however often Docker restarts it"

    def test_it_stays_while_the_other_copies_are_quiet_too(self):
        alerts = self._raised()
        alerts.run(_live_rows([6] * 12, [5] * 12, [0.3] * 12))
        assert SUBJECT in alerts.rows and _bell()
        assert len(alerts.titles) == 1, "no second push"

    def test_a_failing_read_never_raises(self, caplog):
        with (
            patch.object(main.database, "get_alert_subjects", AsyncMock(return_value=set())),
            patch.object(main.database, "get_usage_hourly", AsyncMock(side_effect=RuntimeError("locked"))),
        ):
            asyncio.run(main._traffic_stall_check(WORKERS, _statuses()))
        assert "Traffic-stall check failed" in caplog.text


class TestItIsWiredIn:
    def test_the_health_check_runs_it_with_what_it_read(self):
        statuses = _statuses()
        check = AsyncMock()
        with (
            patch.object(main.database, "list_workers", AsyncMock(return_value=WORKERS)),
            patch.object(main.database, "get_deployments", AsyncMock(return_value=[])),
            patch.object(main.database, "record_health_events", AsyncMock()),
            patch.object(main, "_get_all_worker_containers", AsyncMock(return_value=statuses)),
            patch.object(main, "_container_down_check", AsyncMock()),
            patch.object(main, "_account_disabled_check", AsyncMock()),
            patch.object(main, "_missing_deployment_check", AsyncMock()),
            patch.object(main, "_proxied_copy_check", AsyncMock()),
            patch.object(main, "_worker_docker_check", AsyncMock()),
            patch.object(main, "_traffic_stall_check", check),
        ):
            asyncio.run(main._run_health_check())
        check.assert_awaited_once_with(WORKERS, statuses)

    def test_the_hourly_rebuild_keeps_it(self):
        import inspect

        assert "_stall_bell.values()" in inspect.getsource(main._run_collection)

    def test_a_stored_alert_comes_back_after_a_restart(self):
        rows = [{"kind": "stall", "subject": SUBJECT, "message": "Honeygain on charlie has sent almost nothing"}]
        with (
            patch.object(main.database, "list_alerts", AsyncMock(return_value=rows)),
            patch.object(main, "_proxy_cap_alerts", AsyncMock(return_value=[])),
        ):
            asyncio.run(main._warm_collector_alerts())
        assert main._stall_bell[SUBJECT]["platform"] == "cashpilot-honeygain"
        assert _bell() == [("stall", "cashpilot-honeygain")]


class TestTheDashboardSaysSo:
    def test_it_is_a_card_on_the_attention_list(self):
        from tests.test_account_disabled import _HARNESS

        node = shutil.which("node")
        if not node:
            pytest.skip("node is not installed")
        harness = _HARNESS.replace(": { alerts: [] };", ": JSON.parse(process.env.BELL);")
        assert harness != _HARNESS
        bell = {"alerts": [{"kind": "stall", "platform": "cashpilot-honeygain", "error": "Honeygain on charlie"}]}
        svc = {"slug": "honeygain", "name": "Honeygain", "instance_details": []}
        out = subprocess.run(
            [node, "-e", harness, str(ROOT / "app/static/js/app.js"), json.dumps(svc)],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "BELL": json.dumps(bell)},
        )
        result = json.loads(out.stdout)
        assert "error" not in result, result
        assert "Almost no traffic" in result["tags"]
        assert "Honeygain on charlie" in result["html"]

    def test_the_bell_offers_no_credential_fix_and_a_change_redraws_the_list(self):
        js = (ROOT / "app/static/js/app.js").read_text()
        assert "isStall ? ' — almost no traffic'" in js
        assert "&& !isStall &&" in js.split("const showFix = ", 1)[1].split("\n", 1)[0]
        assert "|| a.kind === 'stall' ||" in js.split("function attentionAlertsKey", 1)[1].split("}", 1)[0]


def test_stall_numbers_are_plain_mb():
    title, message = main._stall_text("Honeygain", "charlie", Stall(sent=0.04 * MB, peers=31.26 * MB), 12)
    assert title == "CashPilot: Honeygain on charlie carries almost no traffic"
    assert "under 0.1 MB an hour" in message and "31.3 MB an hour" in message
