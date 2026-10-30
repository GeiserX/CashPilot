"""A provider that disables the account shows as exactly that: one card, one alert.

On 2026-10-31 IPRoyal Pawns deactivated the account. On three boxes
pawns-cli printed "user is disabled" (no newline) and exited 1, about 600
restarts each. The dashboard showed three "Degraded, container is restarting"
cards with Start buttons and a "No reading, Fix credentials" card, all for one
cause none of those buttons can fix. The collector's own login by then came
back 429, so its message no longer named the cause either.

The catalog now declares the provider's fatal log text, the worker reports the
match, and the UI turns it into one account-disabled state per service that
clears by itself when the container stays up or a balance is read.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from app import catalog, main, orchestrator

ROOT = Path(__file__).resolve().parent.parent
PAWNS_LOG = b"user is disabled" * 40  # what `docker logs` returns: no newline anywhere
PATTERNS = [{"pattern": "user is disabled", "kind": "account_disabled"}]


# --------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------


class TestCatalog:
    def test_pawns_declares_its_disabled_text_and_support_page(self):
        svc = catalog.get_service("iproyal")
        assert svc is not None, "iproyal.yml failed validation and was dropped"
        assert svc["docker"]["fatal_log_patterns"] == PATTERNS
        assert svc["support_url"].startswith("https://")

    @pytest.mark.parametrize(
        "fatal",
        [
            "user is disabled",
            [{"pattern": "user is disabled", "kind": "banned"}],
            [{"pattern": "(", "kind": "account_disabled"}],
            [{"pattern": "", "kind": "account_disabled"}],
        ],
    )
    def test_a_malformed_entry_is_rejected(self, fatal):
        data = {"docker": {"fatal_log_patterns": fatal}}
        errors = catalog._validate(data, Path("x.yml"))
        assert any("fatal_log_patterns" in e for e in errors), errors

    def test_a_good_entry_passes(self):
        errors = catalog._validate({"docker": {"fatal_log_patterns": PATTERNS}}, Path("x.yml"))
        assert not any("fatal_log_patterns" in e for e in errors)

    def test_support_url_must_be_https(self):
        assert any("support_url" in e for e in catalog._validate({"support_url": "http://x"}, Path("x.yml")))

    def test_iproyal_has_no_repeated_key(self):
        """Desktop's yaml.v3 rejects a repeated key that PyYAML silently accepts."""

        class Strict(yaml.SafeLoader):
            pass

        def mapping(loader, node, deep=False):
            keys = [loader.construct_object(k, deep=deep) for k, _ in node.value]
            assert len(keys) == len(set(keys)), keys
            return yaml.SafeLoader.construct_mapping(loader, node, deep)

        Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
        yaml.load((ROOT / "services/bandwidth/iproyal.yml").read_text(), Loader=Strict)  # noqa: S506


# --------------------------------------------------------------------------
# Worker: read the log of a crash-looping container
# --------------------------------------------------------------------------


class TestWorkerMatch:
    def test_repeated_text_with_no_newline_matches(self):
        assert orchestrator.match_fatal(PAWNS_LOG.decode(), PATTERNS) == "account_disabled"

    def test_case_is_ignored(self):
        assert orchestrator.match_fatal("ERROR: User Is Disabled", PATTERNS) == "account_disabled"

    def test_other_text_does_not_match(self):
        assert orchestrator.match_fatal("connection refused\n" * 20, PATTERNS) is None

    def test_only_the_tail_counts(self):
        """An old refusal far back in the log is not what the client says now."""
        logs = "user is disabled" + "x" * (orchestrator._FATAL_LOG_CHARS + 10)
        assert orchestrator.match_fatal(logs, PATTERNS) is None

    def test_a_bad_entry_is_skipped(self):
        bad = [{"pattern": "(", "kind": "account_disabled"}, *PATTERNS]
        assert orchestrator.match_fatal("user is disabled", bad) == "account_disabled"

    def _container(self, status, logs=PAWNS_LOG):
        return SimpleNamespace(status=status, name="cashpilot-iproyal", logs=MagicMock(return_value=logs))

    def _with_catalog(self):
        svc = {"slug": "iproyal", "docker": {"fatal_log_patterns": PATTERNS}}
        return patch.object(orchestrator, "get_service", lambda slug: svc if slug == "iproyal" else None)

    @pytest.mark.parametrize("status", ["restarting", "exited", "dead"])
    def test_a_stopped_or_looping_container_reports_the_kind(self, status):
        with self._with_catalog():
            assert orchestrator._fatal_entry(self._container(status), "iproyal") == {"fatal": "account_disabled"}

    def test_a_running_container_costs_no_log_read(self):
        c = self._container("running")
        with self._with_catalog():
            assert orchestrator._fatal_entry(c, "iproyal") == {}
        c.logs.assert_not_called()

    def test_a_service_without_patterns_costs_no_log_read(self):
        c = self._container("restarting")
        with self._with_catalog():
            assert orchestrator._fatal_entry(c, "honeygain") == {}
        c.logs.assert_not_called()

    def test_an_unreadable_log_says_nothing(self):
        c = self._container("restarting")
        c.logs.side_effect = RuntimeError("daemon gone")
        with self._with_catalog():
            assert orchestrator._fatal_entry(c, "iproyal") == {}

    def test_the_ui_keeps_the_field_from_the_heartbeat(self):
        worker = {
            "id": 1,
            "name": "watchtower",
            "status": "online",
            "system_info": json.dumps({"docker_available": True}),
            "containers": json.dumps([{"slug": "iproyal", "status": "restarting", "fatal": "account_disabled"}]),
        }
        rows = asyncio.run(main._get_all_worker_containers([worker]))
        assert rows[0]["fatal"] == "account_disabled"


# --------------------------------------------------------------------------
# UI server: one alert, the bell, and the way out
# --------------------------------------------------------------------------


def _status(node, wid, status="restarting", fatal="account_disabled"):
    entry = {"slug": "iproyal", "name": "cashpilot-iproyal", "status": status, "_node": node, "_worker_id": wid}
    if fatal:
        entry["fatal"] = fatal
    return entry


THREE_BOXES = [_status("watchtower", 1), _status("geiserback", 2), _status("geiserct", 3)]


class _Alerts:
    """The alerts table's dedupe, in memory."""

    def __init__(self):
        self.rows: dict[tuple[str, str], str] = {}
        self.pushed: list[str] = []
        self.cleared: list[tuple[str, str]] = []

    async def record(self, kind, subject, message, **_):
        if (kind, subject) in self.rows:
            return None
        self.rows[(kind, subject)] = message
        return len(self.rows)

    async def clear(self, kind=None, subject=None):
        self.rows.pop((kind, subject), None)
        self.cleared.append((kind, subject))

    def run(self, statuses):
        def spawn(coro):
            coro.close()
            self.pushed.append("push")

        with (
            patch.object(main.database, "record_alert", self.record),
            patch.object(main.database, "clear_alerts", self.clear),
            patch.object(main, "_spawn", spawn),
        ):
            asyncio.run(main._account_disabled_check(statuses))


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.setattr(main, "_account_disabled", {})
    monkeypatch.setattr(main, "_collector_says_disabled", set())
    monkeypatch.setattr(main, "_collected_ok_last_run", set())
    monkeypatch.setattr(
        main,
        "_collector_alerts",
        [
            {
                "kind": "collector",
                "platform": "iproyal",
                "error": "Pawns rate-limited the login — it will retry on the next run",
            },
            {"kind": "collector", "platform": "honeygain", "error": "Login failed"},
        ],
    )


class TestOneAlert:
    def test_three_looping_boxes_raise_one_alert_once(self):
        alerts = _Alerts()
        alerts.run(THREE_BOXES)
        alerts.run(THREE_BOXES)
        assert list(alerts.rows) == [("account_disabled", "iproyal")]
        assert alerts.pushed == ["push"]
        assert "IPRoyal Pawns has disabled this account" in alerts.rows[("account_disabled", "iproyal")]

    def test_the_bell_names_the_cause_instead_of_the_symptoms(self):
        _Alerts().run(THREE_BOXES)
        mine = [a for a in main._collector_alerts if a["platform"] == "iproyal"]
        assert [a["kind"] for a in mine] == ["account_disabled"]
        # Another service's failure is untouched.
        assert any(a["platform"] == "honeygain" and a["kind"] == "collector" for a in main._collector_alerts)

    def test_the_alert_is_never_repeated_while_it_lasts(self):
        assert main._ACCOUNT_DISABLED_COOLDOWN_HOURS >= 24 * 30

    def test_the_collector_alone_can_say_it(self):
        main._collector_says_disabled = {"iproyal"}
        alerts = _Alerts()
        alerts.run([_status("watchtower", 1, status="running", fatal=None)])
        assert ("account_disabled", "iproyal") in alerts.rows

    def test_nothing_is_stopped_or_removed(self):
        stop = AsyncMock()
        with patch.object(main, "_proxy_worker_command", stop):
            _Alerts().run(THREE_BOXES)
        stop.assert_not_called()

    def test_an_explained_exit_raises_no_container_down_alert(self, monkeypatch):
        monkeypatch.setattr(main, "_container_first_seen_down", {})
        monkeypatch.setattr(main, "_container_down_bell", {})
        exited = {**_status("watchtower", 1, status="exited"), "finished_at": "2026-10-01T00:00:00Z"}
        record = AsyncMock(return_value=1)
        with (
            patch.object(main.database, "record_alert", record),
            patch.object(main.database, "get_alert_subjects", AsyncMock(return_value=set())),
            patch.object(main.database, "get_last_lifecycle_event", AsyncMock(return_value=None)),
            patch.object(main, "_spawn", lambda c: c.close()),
        ):
            asyncio.run(main._container_down_check([exited]))
        record.assert_not_called()


class TestTheWayOut:
    def test_the_container_staying_up_clears_it(self):
        alerts = _Alerts()
        alerts.run(THREE_BOXES)
        alerts.run([_status(n, w, status="running", fatal=None) for n, w in (("watchtower", 1), ("geiserback", 2))])
        assert main._account_disabled == {}
        assert ("account_disabled", "iproyal") in alerts.cleared
        assert not any(a["kind"] == "account_disabled" for a in main._collector_alerts)

    def test_a_balance_read_clears_it_even_with_an_old_log(self):
        alerts = _Alerts()
        alerts.run(THREE_BOXES)
        main._collected_ok_last_run = {"iproyal"}
        alerts.run(THREE_BOXES)  # the stopped containers still end on the old refusal
        assert main._account_disabled == {}

    def test_no_heartbeat_data_keeps_what_was_known(self):
        alerts = _Alerts()
        alerts.run(THREE_BOXES)
        alerts.run([])
        assert "iproyal" in main._account_disabled
        assert alerts.pushed == ["push"]

    def test_it_alerts_again_after_a_recovery(self):
        alerts = _Alerts()
        alerts.run(THREE_BOXES)
        alerts.run([_status("watchtower", 1, status="running", fatal=None)])
        alerts.run(THREE_BOXES)
        assert alerts.pushed == ["push", "push"]


def _deployed(collector_alerts, account_disabled):
    containers = [{"slug": "iproyal", "name": "cashpilot-iproyal", "status": "restarting", "fatal": "account_disabled"}]
    worker = {
        "id": 1,
        "name": "watchtower",
        "status": "online",
        "system_info": json.dumps({"docker_available": True}),
        "containers": json.dumps(containers),
        "apps": "[]",
    }
    owner = {"uid": 1, "u": "owner", "r": "owner"}

    @asynccontextmanager
    async def _noop_lifespan(app):
        yield

    from fastapi.testclient import TestClient

    with (
        patch.object(main.app.router, "lifespan_context", _noop_lifespan),
        patch.object(main, "_collector_alerts", collector_alerts),
        patch.object(main, "_account_disabled", account_disabled),
        patch("app.main.auth.get_current_user", return_value=owner),
        patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
        patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_health_scores", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
        patch("app.main.database.get_custom_images", new_callable=AsyncMock, return_value={}),
        patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
        TestClient(main.app, raise_server_exceptions=False) as client,
    ):
        resp = client.get("/api/services/deployed")
    assert resp.status_code == 200, resp.text
    return resp.json()[0]


class TestDashboardRow:
    def test_a_disabled_account_is_not_a_credentials_problem(self):
        row = _deployed(
            [{"kind": "collector", "platform": "iproyal", "error": "rate-limited"}],
            {"iproyal": "disabled"},
        )
        assert row["account_disabled"] is True
        assert row["collector_disconnected"] is False
        assert row["support_url"].startswith("https://")
        assert row["instance_details"][0]["fatal"] == "account_disabled"

    def test_the_control_a_plain_collector_failure_still_asks_for_credentials(self):
        row = _deployed([{"kind": "collector", "platform": "iproyal", "error": "Login failed"}], {})
        assert row["account_disabled"] is False
        assert row["collector_disconnected"] is True


# --------------------------------------------------------------------------
# Dashboard: the attention list, run in node against the real app.js
# --------------------------------------------------------------------------

_HARNESS = r"""
const src = require('fs').readFileSync(process.argv[process.argv.length - 2], 'utf8');
const from = src.indexOf('  function instanceState(status) {');
const to = src.indexOf('  // Action-button icons');
if (from < 0 || to <= from) { console.log(JSON.stringify({error: 'block moved'})); process.exit(0); }
const escapeHtml = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
const els = {};
const document = { getElementById: id => (els[id] = els[id] || { innerHTML: '', classList: { toggle() {} } }) };
const api = async (url) => url === '/api/credentials/health'
  ? [{ service: 'iproyal', name: 'IPRoyal Pawns', status: 'likely_expired' }]
  : { alerts: [] };
const fmtTimestamp = () => ({ text: '' });
const _isOwner = true, _canWrite = true;
let _attentionSeq = 0;
const run = new Function('escapeHtml', 'document', 'api', 'fmtTimestamp', '_isOwner', '_canWrite', '_attentionSeq',
  `${src.slice(from, to)}; return renderAttention;`)(escapeHtml, document, api, fmtTimestamp, _isOwner, _canWrite, _attentionSeq);
const svc = JSON.parse(process.argv[process.argv.length - 1]);
run([svc], [{ id: 1, name: 'watchtower', status: 'online' }]).then(() => {
  const html = els['attention-list'].innerHTML;
  const tags = [...html.matchAll(/class="attn-tag">([^<]*)</g)].map(m => m[1]);
  console.log(JSON.stringify({ tags, html }));
});
"""


def _attention(svc: dict) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    out = subprocess.run(
        [node, "-e", _HARNESS, str(ROOT / "app/static/js/app.js"), json.dumps(svc)],
        capture_output=True,
        text=True,
        check=True,
    )
    result = json.loads(out.stdout)
    assert "error" not in result, result
    return result


def _pawns(account_disabled: bool) -> dict:
    return {
        "slug": "iproyal",
        "name": "IPRoyal Pawns",
        "account_disabled": account_disabled,
        "collector_disconnected": True,
        "support_url": "https://pawns.app/contact-us/",
        "unstable": True,
        "crashes_7d": 600,
        "instance_details": [
            {
                "node": n,
                "worker_id": w,
                "status": "restarting",
                "has_docker": True,
                "container_name": "cashpilot-iproyal",
                "fatal": "account_disabled",
            }
            for n, w in (("watchtower", 1), ("geiserback", 2), ("geiserct", 3))
        ],
    }


class TestAttentionList:
    def test_one_card_says_the_account_is_disabled(self):
        result = _attention(_pawns(account_disabled=True))
        assert result["tags"] == ["Account disabled"]
        html = result["html"]
        assert "Restarting will not help" in html
        assert 'data-action="stopEverywhere"' in html
        assert "https://pawns.app/contact-us/" in html
        for wrong in ("Fix credentials", "startService", "Degraded", "Renew"):
            assert wrong not in html, wrong

    def test_the_control_without_the_flag_shows_the_old_cards(self):
        """Proves the harness can see the cards it says are gone."""
        tags = _attention(_pawns(account_disabled=False))["tags"]
        assert tags.count("Degraded") == 3
        assert "No reading" in tags

    def test_stopped_everywhere_offers_no_stop(self):
        svc = _pawns(account_disabled=True)
        for inst in svc["instance_details"]:
            inst["status"] = "exited"
        html = _attention(svc)["html"]
        assert "stopEverywhere" not in html
        assert "Account disabled" in html

    def test_stop_everywhere_is_wired(self):
        src = (ROOT / "app/static/js/app.js").read_text()
        assert "    stopEverywhere,\n" in src
