"""Each box gets its own device name (#740).

Every deploy from the dashboard used to fill ``{hostname}`` with the bare
prefix, because the form never sends a hostname. So every box registered as
"cashpilot-cashpilot" on IPRoyal, Honeygain, Traffmonetizer and ProxyBase, and
the providers that count devices by name saw one device.

Now a new deployment gets ``<prefix>-<8 hex of the worker's client_id>``. A
running deployment keeps the name it has unless the operator confirms the new
one, because a new name is a new device to the provider.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest
from fastapi.testclient import TestClient

from app import main, proxies
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
SAFE = re.compile(r"[a-z0-9-]+")


@asynccontextmanager
async def _noop_lifespan(a):
    yield


app.router.lifespan_context = _noop_lifespan

# IPRoyal's shape: the name goes on the command line, twice, and the service
# may run more than once per box in this fixture so copies can be checked.
SVC = {
    "slug": "iproyal",
    "name": "IPRoyal",
    "docker": {
        "image": "iproyal/pawns-cli",
        "env": [
            {"key": "EMAIL", "label": "Email", "default": ""},
            {"key": "DEVICE_NAME", "label": "Device name", "default": "cashpilot-{hostname}"},
            {"key": "DEVICE_ID", "label": "Device ID", "default": "cashpilot-{hostname}"},
            {"key": "SECRET_NAME", "label": "Secret", "default": "x-{hostname}", "secret": True},
        ],
        "command": "-email ${EMAIL} -device-name ${DEVICE_NAME} -device-id ${DEVICE_ID}",
    },
}


def _worker(wid: int, client_id: str, name: str = "local", containers: list | None = None) -> dict:
    return {
        "id": wid,
        "name": name,
        "client_id": client_id,
        "status": "online",
        "url": f"http://192.168.1.{wid}:8081",
        "containers": json.dumps(containers or []),
        "system_info": json.dumps({"features": ["instances"]}),
    }


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _post(client, path, body, workers, recorded=None, role="owner", wid=None, copies=None):
    """POST to a deploy route with the app's edges mocked. Returns (response, specs sent to the worker).

    ``copies`` stands for the proxied_copies table: the route reads these dicts
    and its marks are written back into them.
    """
    sent: list[dict] = []
    copies = [] if copies is None else copies

    async def _list_copies(proxy_id=None):
        return [dict(c) for c in copies if proxy_id is None or c["proxy_id"] == proxy_id]

    async def _mark_pending(proxy_id, worker_id, slug, pending):
        for c in copies:
            if (c["proxy_id"], c["worker_id"], c["slug"]) == (proxy_id, worker_id, slug):
                c["rename_pending"] = 1 if pending else 0

    saved: list[dict] = []

    async def _save(*args, spec=None, **kw):
        if spec is not None:
            saved.append(json.loads(json.dumps(spec)))

    async def _settle_pending(proxy_id, worker_id, slug, built_from):
        # Cleared if the copy was built from the record that is current, set otherwise.
        current = built_from == (saved[-1] if saved else recorded)
        await _mark_pending(proxy_id, worker_id, slug, not current)
        return current

    async def _fake_deploy(worker_id, slug, spec):
        sent.append(spec)
        return {"container_id": "c1"}

    by_id = {w["id"]: w for w in workers}

    async def _get_worker(worker_id):
        return by_id.get(worker_id)

    wid = wid if wid is not None else workers[0]["id"]
    with (
        patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "u", "r": role}),
        patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
        patch("app.main.database.get_worker", side_effect=_get_worker),
        patch("app.main.database.get_deployment_spec", new_callable=AsyncMock, return_value=recorded),
        patch("app.main.catalog.get_service", return_value=SVC),
        patch("app.main._proxy_worker_deploy", side_effect=_fake_deploy),
        patch("app.main._proxy_to_worker", new_callable=AsyncMock),
        patch("app.main.database.save_deployment", side_effect=_save),
        patch("app.main.database.record_health_event", new_callable=AsyncMock),
        patch("app.main._run_collection", new_callable=AsyncMock),
        patch("app.main.database.list_proxied_copies", side_effect=_list_copies),
        patch("app.main.database.set_proxied_copy_rename_pending", side_effect=_mark_pending),
        patch("app.main.database.settle_proxied_copy_rename_pending", side_effect=_settle_pending),
    ):
        resp = client.post(f"{path}?worker_id={wid}", json=body)
    return resp, sent


def _deploy(client, body, workers, **kw):
    return _post(client, "/api/deploy/iproyal", body, workers, **kw)


def _renames(client, body, workers, **kw):
    resp, sent = _post(client, "/api/deploy/iproyal/device-names", body, workers, **kw)
    assert not sent, "the check must not deploy anything"
    return resp


class TestTheSuffix:
    def test_two_workers_get_two_names(self):
        assert main.device_name_suffix("a") != main.device_name_suffix("b")

    def test_the_same_worker_gets_the_same_name_every_time(self):
        assert main.device_name_suffix("5f0c") == main.device_name_suffix("5f0c")
        assert main._device_hostname({"client_id": "5f0c"}, 1) == main._device_hostname({"client_id": "5f0c"}, 9)

    @pytest.mark.parametrize(
        "client_id",
        ["; rm -rf / #", "Living Room", "$(reboot)", "../../etc", "naïve‮name", "a" * 5000, "", "local"],
    )
    def test_any_client_id_gives_a_name_safe_for_a_command_line(self, client_id):
        name = main._device_hostname({"client_id": client_id}, 3)
        assert SAFE.fullmatch(name), name
        assert len(name) <= 41

    @pytest.mark.parametrize("prefix", ["My Box; rm -rf /", "UPPER", "  ", "-x-", "é" * 50])
    def test_a_hostile_prefix_is_cleaned_too(self, monkeypatch, prefix):
        monkeypatch.setattr(main, "HOSTNAME_PREFIX", prefix)
        name = main._device_hostname({"client_id": "abc"}, 1)
        assert SAFE.fullmatch(name) and not name.startswith("-"), name

    def test_a_worker_with_no_row_still_gets_its_own(self):
        assert main._device_hostname(None, 1) != main._device_hostname(None, 2)


class TestNewDeployments:
    def test_two_boxes_with_the_same_default_name_register_two_devices(self, client):
        """The bug: the shipped default worker names are the same on every install."""
        a, b = _worker(1, "cid-a", name="local"), _worker(2, "cid-b", name="local")
        _, sent_a = _deploy(client, {"env": {"EMAIL": "me@x.io"}}, [a, b], wid=1)
        _, sent_b = _deploy(client, {"env": {"EMAIL": "me@x.io"}}, [a, b], wid=2)
        name_a, name_b = sent_a[0]["env"]["DEVICE_NAME"], sent_b[0]["env"]["DEVICE_NAME"]
        assert name_a != name_b
        assert name_a != "cashpilot-cashpilot"
        assert sent_a[0]["env"]["DEVICE_ID"] == name_a
        assert f"-device-name {name_a} -device-id {name_a}" in sent_a[0]["command"]

    def test_the_same_box_gets_the_same_name_on_every_deploy(self, client):
        w = _worker(1, "cid-a")
        _, first = _deploy(client, {"env": {"EMAIL": "me@x.io"}}, [w])
        _, second = _deploy(client, {"env": {"EMAIL": "me@x.io"}}, [w])
        assert first[0]["env"]["DEVICE_NAME"] == second[0]["env"]["DEVICE_NAME"]

    def test_the_name_comes_from_the_client_id_not_the_worker_name(self, client):
        w = _worker(1, "cid-a", name="Living Room; rm -rf /")
        _, sent = _deploy(client, {"env": {"EMAIL": "me@x.io"}}, [w])
        assert sent[0]["env"]["DEVICE_NAME"] == "cashpilot-" + main._device_hostname(w, 1)

    def test_a_typed_name_is_used_as_typed(self, client):
        _, sent = _deploy(client, {"env": {"EMAIL": "me@x.io", "DEVICE_NAME": "my-nas"}}, [_worker(1, "cid-a")])
        assert sent[0]["env"]["DEVICE_NAME"] == "my-nas"

    def test_a_hostname_sent_by_an_api_client_still_wins(self, client):
        _, sent = _deploy(client, {"env": {"EMAIL": "me@x.io"}, "hostname": "nas"}, [_worker(1, "cid-a")])
        assert sent[0]["env"]["DEVICE_NAME"] == "cashpilot-nas"

    def test_a_new_deployment_asks_nothing(self, client):
        resp = _renames(client, {"env": {}}, [_worker(1, "cid-a")])
        assert resp.status_code == 200, resp.text
        assert resp.json()["renames"] == []


class TestCopiesStayDistinct:
    def test_every_copy_on_a_box_has_its_own_stable_name(self, client):
        w = _worker(1, "cid-a")
        with patch("app.main.scaling_limit", return_value=(5, "")):
            _, sent = _deploy(client, {"env": {"EMAIL": "me@x.io"}, "instances": 3}, [w])
            _, again = _deploy(client, {"env": {"EMAIL": "me@x.io"}, "instances": 3}, [w])
        names = [s["env"]["DEVICE_NAME"] for s in sent]
        assert len(set(names)) == 3
        assert names == [s["env"]["DEVICE_NAME"] for s in again]
        base = names[0]
        assert names[1:] == [f"{base}-2", f"{base}-3"]
        assert all(f"-device-id {n}" in s["command"] for n, s in zip(names, sent, strict=True))

    def test_a_proxied_copy_has_its_own_name(self, client):
        _, sent = _deploy(client, {"env": {"EMAIL": "me@x.io"}}, [_worker(1, "cid-a")])
        copy = proxies.earner_spec(sent[0], SVC["docker"], 5)
        assert copy["env"]["DEVICE_NAME"] == sent[0]["env"]["DEVICE_NAME"] + "-p5"
        assert copy["env"]["DEVICE_NAME"] in copy["command"]


LEGACY = "cashpilot-cashpilot"


def _recorded(name: str) -> dict:
    return {
        "image": "iproyal/pawns-cli",
        "env": {"EMAIL": "me@x.io", "DEVICE_NAME": name, "DEVICE_ID": name, "SECRET_NAME": "x-cashpilot"},
        "hostname": None,
    }


class TestRunningDeploymentsAreNotRenamedSilently:
    def test_a_redeploy_keeps_the_old_shared_name(self, client):
        _, sent = _deploy(client, {"env": {}}, [_worker(1, "cid-a")], recorded=_recorded(LEGACY))
        assert sent[0]["env"]["DEVICE_NAME"] == LEGACY
        assert sent[0]["env"]["DEVICE_ID"] == LEGACY

    def test_the_check_names_each_rename_old_to_new(self, client):
        w = _worker(1, "cid-a")
        resp = _renames(client, {"env": {}}, [w], recorded=_recorded(LEGACY))
        assert resp.status_code == 200, resp.text
        new = "cashpilot-" + main._device_hostname(w, 1)
        assert resp.json()["renames"] == [
            {"key": "DEVICE_NAME", "label": "Device name", "old": LEGACY, "new": new},
            {"key": "DEVICE_ID", "label": "Device ID", "old": LEGACY, "new": new},
        ]

    def test_a_confirmed_rename_reaches_the_container_and_its_copies(self, client):
        w = _worker(1, "cid-a")
        new = "cashpilot-" + main._device_hostname(w, 1)
        with patch("app.main.scaling_limit", return_value=(5, "")):
            _, sent = _deploy(
                client, {"env": {}, "rename_devices": True, "instances": 2}, [w], recorded=_recorded(LEGACY)
            )
        assert [s["env"]["DEVICE_NAME"] for s in sent] == [new, f"{new}-2"]
        assert f"-device-name {new} -device-id {new}" in sent[0]["command"]
        assert f"-device-name {LEGACY} " not in sent[1]["command"]
        # A secret is never part of the rename.
        assert sent[0]["env"]["SECRET_NAME"] == "x-cashpilot"

    def test_a_name_the_operator_chose_is_never_offered_or_renamed(self, client):
        w = _worker(1, "cid-a")
        assert _renames(client, {"env": {}}, [w], recorded=_recorded("my-nas")).json()["renames"] == []
        _, sent = _deploy(client, {"env": {}, "rename_devices": True}, [w], recorded=_recorded("my-nas"))
        assert sent[0]["env"]["DEVICE_NAME"] == "my-nas"

    def test_a_name_typed_on_this_deploy_is_not_offered(self, client):
        body = {"env": {"DEVICE_NAME": "living-room"}}
        resp = _renames(client, body, [_worker(1, "cid-a")], recorded=_recorded(LEGACY))
        assert [r["key"] for r in resp.json()["renames"]] == ["DEVICE_ID"]

    def test_a_running_container_with_no_record_keeps_the_old_name(self, client):
        """Deployed before records were kept: what it runs is most likely the old shared name."""
        w = _worker(1, "cid-a", containers=[{"slug": "iproyal", "status": "running"}])
        assert [r["old"] for r in _renames(client, {"env": {}}, [w]).json()["renames"]] == [LEGACY, LEGACY]
        _, kept = _deploy(client, {"env": {"EMAIL": "me@x.io"}}, [w])
        assert kept[0]["env"]["DEVICE_NAME"] == LEGACY
        _, renamed = _deploy(client, {"env": {"EMAIL": "me@x.io"}, "rename_devices": True}, [w])
        assert renamed[0]["env"]["DEVICE_NAME"] == "cashpilot-" + main._device_hostname(w, 1)

    def test_the_check_says_which_box_by_name(self, client):
        resp = _renames(client, {"env": {}}, [_worker(3, "cid-a", name="unraid")], recorded=_recorded(LEGACY))
        assert resp.json()["worker"] == "unraid"

    def test_the_check_says_what_a_one_click_rename_would_lack(self, client):
        """A box with no record runs a service with a required value: the blank redeploy cannot succeed."""
        env = [{**SVC["docker"]["env"][0], "required": True}, *SVC["docker"]["env"][1:]]
        w = _worker(1, "cid-a", containers=[{"slug": "iproyal", "status": "running"}])
        with patch.dict(SVC["docker"], {"env": env}):
            assert _renames(client, {"env": {}}, [w]).json()["missing"] == ["Email"]
            assert _renames(client, {"env": {"EMAIL": "me@x.io"}}, [w]).json()["missing"] == []
            assert _renames(client, {"env": {}}, [w], recorded=_recorded(LEGACY)).json()["missing"] == []

    def test_the_check_is_for_the_owner_only(self, client):
        resp = _renames(client, {"env": {}}, [_worker(1, "cid-a")], recorded=_recorded(LEGACY), role="writer")
        assert resp.status_code == 403


def _proxied_worker(entries: list[dict]) -> dict:
    """A box that runs IPRoyal and reports its proxied copies."""
    w = _worker(1, "cid-a", containers=[{"slug": "iproyal", "status": "running"}])
    w["system_info"] = json.dumps(
        {"features": ["instances", "proxy_tunnel", "proxied_if_running"], "docker_available": True, "proxied": entries}
    )
    return w


def _copy(pid: int, **kw) -> dict:
    return {
        "proxy_id": pid,
        "worker_id": 1,
        "slug": "iproyal",
        "stopped_by_cap": 0,
        "removing_since": None,
        "rename_pending": 0,
        **kw,
    }


def _rename_with_copies(
    client,
    copies,
    entries,
    *,
    rename=True,
    capped=(),
    worker=None,
    answer=None,
    meanwhile=None,
    path="/api/deploy/iproyal",
    recorded=None,
):
    """A rename deploy on a box with proxied copies. Returns (response, copy deploys sent to the worker).

    ``meanwhile(copies, pid)`` runs once the copy's lock is taken, before the
    record is read again: what a removal or a cap stop that held the lock did.
    """
    calls: list[tuple] = []

    async def _call(worker_id, method, path, definition, *, json=None, timeout=30):
        calls.append((worker_id, method, path, json))
        if answer is not None:
            raise answer
        return {"status": "deployed"}

    async def _proxy(pid):
        if meanwhile:
            meanwhile(copies, pid)
        return {"id": pid, "definition": {"name": f"p{pid}"}, "state": {"capped_at": "x"} if pid in capped else {}}

    with (
        patch("app.main._proxy_worker_call", side_effect=_call),
        patch("app.main._proxy_or_404", side_effect=_proxy),
        patch("app.main.proxies.worker_proxy_spec", return_value={}),
        patch("app.main._register_device", new_callable=AsyncMock),
    ):
        body = {"env": {}, "rename_devices": rename}
        resp, sent = _post(
            client,
            path,
            body,
            [worker or _proxied_worker(entries)],
            recorded=recorded or _recorded(LEGACY),
            copies=copies,
        )
    assert resp.status_code == 200, resp.text
    return resp, sent, calls


class TestARenameReachesProxiedCopies:
    def test_each_running_copy_is_redeployed_under_its_own_new_name(self, client):
        entries = [{"proxy_id": p, "slug": "iproyal", "held": False, "status": "running"} for p in (4, 9)]
        resp, sent, calls = _rename_with_copies(client, [_copy(4), _copy(9)], entries)
        new = sent[0]["env"]["DEVICE_NAME"]
        assert new != LEGACY
        assert [c[2] for c in calls] == ["/api/proxied/iproyal/4/deploy", "/api/proxied/iproyal/9/deploy"]
        names = [c[3]["earner"]["env"]["DEVICE_NAME"] for c in calls]
        assert names == [f"{new}-p4", f"{new}-p9"]
        assert all(f"-device-name {n} " in c[3]["earner"]["command"] for n, c in zip(names, calls, strict=True))
        assert all(c[3]["only_if_running"] is True for c in calls), "the worker must not start a stopped copy"
        assert "kept_from_previous_deployment" not in resp.json()

    def test_a_copy_that_exited_without_a_stop_is_not_started_by_the_rename(self, client):
        entries = [{"proxy_id": 4, "slug": "iproyal", "held": False, "status": "exited"}]
        resp, _, calls = _rename_with_copies(client, [_copy(4)], entries)
        assert calls == []
        assert resp.json()["kept_from_previous_deployment"][0].startswith("proxied copy p4: stopped")

    def test_a_stop_that_lands_after_the_report_wins(self, client):
        """The report says running; the owner stopped it since. The worker refuses, and the note says so."""
        from fastapi import HTTPException

        entries = [{"proxy_id": 4, "slug": "iproyal", "held": False, "status": "running"}]
        refused = HTTPException(409, "cashpilot-iproyal-p4 is not running, so it was left as it was")
        resp, _, calls = _rename_with_copies(client, [_copy(4)], entries, answer=refused)
        assert len(calls) == 1 and calls[0][3]["only_if_running"] is True
        (note,) = resp.json()["kept_from_previous_deployment"]
        assert "keeps its old device name" in note and "not running" in note

    def test_a_worker_too_old_to_check_is_not_sent_the_rebuild(self, client):
        entries = [{"proxy_id": 4, "slug": "iproyal", "held": False, "status": "running"}]
        old = _proxied_worker(entries)
        old["system_info"] = json.dumps(
            {"features": ["instances", "proxy_tunnel"], "docker_available": True, "proxied": entries}
        )
        resp, _, calls = _rename_with_copies(client, [_copy(4)], entries, worker=old)
        assert calls == []
        assert "too old" in resp.json()["kept_from_previous_deployment"][0]

    def test_no_rename_leaves_the_copies_alone(self, client):
        entries = [{"proxy_id": 4, "slug": "iproyal", "held": False, "status": "running"}]
        _, sent, calls = _rename_with_copies(client, [_copy(4)], entries, rename=False)
        assert sent[0]["env"]["DEVICE_NAME"] == LEGACY and calls == []

    def test_a_stopped_or_capped_copy_is_not_started_by_the_rename(self, client):
        entries = [
            {"proxy_id": 4, "slug": "iproyal", "held": True, "status": "exited"},
            {"proxy_id": 5, "slug": "iproyal", "held": False, "status": "running"},
            {"proxy_id": 6, "slug": "iproyal", "held": False, "status": "running"},
        ]
        copies = [_copy(4), _copy(5, stopped_by_cap=1), _copy(6), _copy(7)]
        resp, _, calls = _rename_with_copies(client, copies, entries, capped=(6,))
        assert calls == [], "a held, capped or unreported copy is never redeployed"
        notes = resp.json()["kept_from_previous_deployment"]
        assert [n.split(":")[0] for n in notes] == [f"proxied copy p{p}" for p in (4, 5, 6, 7)]
        assert all("old device name" in n for n in notes)

    def test_a_copy_removed_after_the_list_was_read_is_not_recreated(self, client):
        """The removal took the copy's lock first and dropped its record: the rebuild finds nothing to rebuild."""
        entries = [{"proxy_id": 4, "slug": "iproyal", "held": False, "status": "running"}]
        copies = [_copy(4)]
        resp, _, calls = _rename_with_copies(client, copies, entries, meanwhile=lambda cs, pid: cs.clear())
        assert calls == [], "a removed copy is never sent to the worker again"
        (note,) = resp.json()["kept_from_previous_deployment"]
        assert "removed meanwhile" in note

    def test_a_removal_the_worker_has_not_confirmed_is_not_rebuilt(self, client):
        """The worker timed out on the removal, so the copy may still run: rebuilding it would revive it."""
        entries = [{"proxy_id": 4, "slug": "iproyal", "held": False, "status": "running"}]

        def _removing(cs, pid):
            cs[0]["removing_since"] = "2026-11-14 12:00:00"

        resp, _, calls = _rename_with_copies(client, [_copy(4)], entries, meanwhile=_removing)
        assert calls == []
        assert "removed meanwhile" in resp.json()["kept_from_previous_deployment"][0]

    def test_a_cap_stop_after_the_list_was_read_wins(self, client):
        entries = [{"proxy_id": 4, "slug": "iproyal", "held": False, "status": "running"}]

        def _capped(cs, pid):
            cs[0]["stopped_by_cap"] = 1

        resp, _, calls = _rename_with_copies(client, [_copy(4)], entries, meanwhile=_capped)
        assert calls == []
        assert "traffic cap" in resp.json()["kept_from_previous_deployment"][0]


class TestACopyThatKeptItsOldNameCanBeRenamedLater:
    """The original is renamed and its new name saved, so the next check finds no rename for it.

    A copy whose rebuild failed or was skipped must still be offered, and only
    that copy rebuilt: the original is not redeployed again.
    """

    RUNNING = [{"proxy_id": p, "slug": "iproyal", "held": False, "status": "running"} for p in (4, 9)]

    def _renamed(self):
        return _recorded("cashpilot-" + main._device_hostname(_proxied_worker([]), 1))

    def test_a_copy_whose_rebuild_failed_stays_pending_and_one_that_worked_does_not(self, client):
        from fastapi import HTTPException

        copies = [_copy(4), _copy(9)]
        _rename_with_copies(client, copies, self.RUNNING, answer=HTTPException(502, "worker unreachable"))
        assert [c["rename_pending"] for c in copies] == [1, 1]
        copies = [_copy(4), _copy(9)]
        _rename_with_copies(client, copies, self.RUNNING)
        assert [c["rename_pending"] for c in copies] == [0, 0]

    def test_the_check_still_reports_a_pending_copy_after_the_original_was_renamed(self, client):
        copies = [_copy(4, rename_pending=1), _copy(9), _copy(5, rename_pending=1, removing_since="x")]
        resp = _renames(client, {"env": {}}, [_proxied_worker(self.RUNNING)], recorded=self._renamed(), copies=copies)
        assert resp.json()["renames"] == []
        assert resp.json()["copies"] == ["proxied copy p4"]

    def test_the_retry_rebuilds_only_the_pending_copies_and_not_the_original(self, client):
        copies = [_copy(4, rename_pending=1), _copy(9)]
        resp, sent, calls = _rename_with_copies(
            client, copies, self.RUNNING, path="/api/deploy/iproyal/device-names/copies", recorded=self._renamed()
        )
        assert sent == [], "the original is already renamed"
        assert [c[2] for c in calls] == ["/api/proxied/iproyal/4/deploy"]
        new = self._renamed()["env"]["DEVICE_NAME"]
        assert calls[0][3]["earner"]["env"]["DEVICE_NAME"] == f"{new}-p4"
        assert calls[0][3]["only_if_running"] is True
        assert copies[0]["rename_pending"] == 0
        assert resp.json()["kept_from_previous_deployment"] == []

    def test_the_retry_still_never_starts_a_stopped_copy(self, client):
        entries = [{"proxy_id": 4, "slug": "iproyal", "held": True, "status": "exited"}]
        copies = [_copy(4, rename_pending=1)]
        resp, _, calls = _rename_with_copies(
            client, copies, entries, path="/api/deploy/iproyal/device-names/copies", recorded=self._renamed()
        )
        assert calls == []
        assert copies[0]["rename_pending"] == 1, "it is still on the old name, so it is still offered"
        assert resp.json()["kept_from_previous_deployment"][0].startswith("proxied copy p4: stopped")

    def test_the_retry_is_for_the_owner_only(self, client):
        resp, _ = _post(client, "/api/deploy/iproyal/device-names/copies", {}, [_worker(1, "cid-a")], role="writer")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# The deploy form: the real functions from app.js, run in node.
# ---------------------------------------------------------------------------

_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function grab(name) {
  const at = src.indexOf(`async function ${name}(`);
  if (at < 0) throw new Error('missing ' + name);
  // The body's brace, not one in a destructured parameter.
  let depth = 0, i = src.indexOf(') {', at) + 2;
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}' && --depth === 0) break;
  }
  return src.slice(at, i + 1);
}
const scenario = JSON.parse(process.argv[2]);
const calls = [], confirms = [], toasts = [];
const env = {
  api: async (url, opts) => {
    calls.push({ url, body: opts && opts.body });
    if (url === '/api/workers') return scenario.apiWorkers || [];
    if (url.includes('/device-names/copies')) return { kept_from_previous_deployment: scenario.copyNotes || [] };
    if (url.includes('/device-names')) {
      if (scenario.checkFails) throw new Error('down');
      const wid = new URL(url, 'http://x').searchParams.get('worker_id');
      // A value typed in the form is no longer missing.
      const typed = Object.values((opts && opts.body && opts.body.env) || {}).some(v => v);
      return {
        worker: (scenario.names || {})[wid], renames: scenario.renames[wid] || [],
        missing: typed ? [] : (scenario.missing || {})[wid] || [], copies: (scenario.copies || {})[wid] || [],
      };
    }
    return scenario.deployAnswer || {};
  },
  window: { confirm: (text) => { confirms.push(text); return scenario.answer; } },
  document: { getElementById: () => null, querySelectorAll: () => [] },
  console: { warn() {} },
  toast(text, kind) { toasts.push({ text, kind }); }, _showDeviceLink() {}, _imageChoice: () => undefined, _instancesFor: () => undefined,
  _confirmPreflight: async () => true, wizardState: { deployed: [] },
  escapeHtml: (t) => String(t), loadServicesTable() {}, openServiceDetail() {}, _showDeviceLink() {},
  _detailWorkers: scenario.detailWorkers || [],
};
// The rename note on the service page, for the scenarios that open it.
const note = { innerHTML: '', style: { display: 'none' } };
// The deploy form's fields, and the fold it sits in on a deployed service.
const details = { open: false };
const inputs = Object.entries(scenario.typed || {}).map(([key, value]) => (
  { dataset: { key }, value, required: true, style: {}, pattern: '' }
));
const imageInput = { value: scenario.image || '', dataset: {} };
env.document = {
  getElementById: (id) => (id === 'device-rename-iproyal' && scenario.page ? note
    : id === 'image-input-iproyal' && scenario.run === 'image' ? imageInput : null),
  querySelectorAll: (sel) => (sel === 'details.sd-more' ? [details] : sel.includes('[data-key]') ? inputs : []),
};
env.openServiceDetail = () => { note.reopened = true; };
note.details = details;
const names = ['_deviceRenameLines', '_confirmDeviceRenames', '_deployToWorkers', 'loadDeviceRenames',
  'renameDevices', 'redeployOnWorker', 'redeployWithValues', 'redeployWithImage'];
const body = `${names.map(grab).join('\n')}\nfunction _runningWorkerIds(slug) {
  return (_detailWorkers || []).filter(w => w.status === 'online' && (w.containers || []).some(c => c.slug === slug)).map(w => w.id);
}\nreturn { ${names.join(', ')} };`;
const fns = new Function(...Object.keys(env), body)(...Object.values(env));
const run = {
  deploy: () => fns._deployToWorkers('iproyal', scenario.workers),
  page: async () => { await fns.loadDeviceRenames('iproyal'); if (scenario.click) await fns.renameDevices('iproyal'); },
  redeploy: () => fns.redeployOnWorker('iproyal', String(scenario.workers[0])),
  withValues: () => fns.redeployWithValues('iproyal', String(scenario.workers[0])),
  image: () => fns.redeployWithImage('iproyal'),
}[scenario.run || 'deploy'];
run().then(() => {
  console.log(JSON.stringify({ calls, confirms, note, toasts }));
});
"""


def _run_form(**scenario) -> dict:
    """Run the scenario and return everything the harness saw: calls, confirms, note, toasts."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    out = subprocess.run(
        [node, "-e", _HARNESS, str(ROOT / "app/static/js/app.js"), json.dumps(scenario)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(out.stdout)


def _form(**scenario):
    result = _run_form(**scenario)
    deploys = [c for c in result["calls"] if c["url"].startswith("/api/deploy/iproyal?")]
    if scenario.get("run") in ("page", "withValues"):
        return deploys, result["confirms"], result["note"]
    return deploys, result["confirms"]


RENAME = {"key": "DEVICE_NAME", "label": "Device name", "old": LEGACY, "new": "cashpilot-cashpilot-1a2b3c4d"}


class TestTheFormAsksBeforeRenaming:
    def test_the_warning_shows_old_and_new_and_ok_renames(self):
        deploys, confirms = _form(workers=[1, 2], renames={"2": [RENAME]}, answer=True)
        assert len(confirms) == 1
        assert f"Device name {LEGACY} -> cashpilot-cashpilot-1a2b3c4d" in confirms[0]
        assert [d["body"].get("rename_devices") for d in deploys] == [True, True]

    def test_cancel_keeps_the_names_and_still_deploys(self):
        deploys, confirms = _form(workers=[1], renames={"1": [RENAME]}, answer=False)
        assert len(confirms) == 1
        assert len(deploys) == 1 and "rename_devices" not in deploys[0]["body"]

    def test_nothing_to_rename_asks_nothing(self):
        deploys, confirms = _form(workers=[1, 2], renames={}, answer=True)
        assert confirms == []
        assert all("rename_devices" not in d["body"] for d in deploys)

    def test_a_check_that_fails_keeps_the_names(self):
        deploys, confirms = _form(workers=[1], renames={}, answer=True, checkFails=True)
        assert confirms == [] and len(deploys) == 1 and "rename_devices" not in deploys[0]["body"]

    def test_each_line_names_the_box_not_its_id(self):
        _, confirms = _form(
            workers=[3, 7], renames={"3": [RENAME], "7": [RENAME]}, names={"3": "local", "7": "unraid"}, answer=False
        )
        assert f"• local: Device name {LEGACY}" in confirms[0]
        assert f"• unraid: Device name {LEGACY}" in confirms[0]
        assert "node 3" not in confirms[0]


# A box that already runs the service cannot be ticked in the deploy form, and
# IPRoyal and Honeygain allow one device per IP, so they have no Instances box
# either. The service page is where those boxes get their own name.
_RUNNING = [
    {"id": 3, "name": "local", "status": "online", "containers": [{"slug": "iproyal"}]},
    {"id": 7, "name": "unraid", "status": "online", "containers": [{"slug": "iproyal"}]},
    {"id": 9, "name": "spare", "status": "online", "containers": []},
]


class TestRunningBoxesCanBeRenamed:
    def test_the_service_page_offers_the_rename_for_running_boxes(self):
        deploys, confirms, note = _form(
            run="page", page=True, detailWorkers=_RUNNING, workers=[], renames={"3": [RENAME]}, answer=True
        )
        assert note["style"]["display"] == ""
        assert 'data-action="renameDevices"' in note["innerHTML"]
        assert confirms == [] and deploys == [], "opening the page changes nothing"

    def test_nothing_to_rename_shows_nothing(self):
        _, _, note = _form(run="page", page=True, detailWorkers=_RUNNING, workers=[], renames={}, answer=True)
        assert note["style"]["display"] == "none"

    def test_the_button_asks_once_then_renames_every_running_box(self):
        deploys, confirms, _ = _form(
            run="page",
            page=True,
            click=True,
            detailWorkers=_RUNNING,
            workers=[],
            renames={"3": [RENAME], "7": [RENAME]},
            names={"3": "local", "7": "unraid"},
            answer=True,
        )
        assert len(confirms) == 1 and "• unraid:" in confirms[0]
        assert [d["url"] for d in deploys] == ["/api/deploy/iproyal?worker_id=3", "/api/deploy/iproyal?worker_id=7"]
        assert all(d["body"] == {"env": {}, "rename_devices": True} for d in deploys)

    def test_cancel_on_the_button_redeploys_nothing(self):
        deploys, confirms, _ = _form(
            run="page", page=True, click=True, detailWorkers=_RUNNING, workers=[], renames={"3": [RENAME]}, answer=False
        )
        assert len(confirms) == 1 and deploys == []

    def test_a_box_the_blank_redeploy_cannot_rename_gets_a_note_not_the_button(self):
        deploys, confirms, note = _form(
            run="page",
            page=True,
            click=True,
            detailWorkers=_RUNNING,
            workers=[],
            renames={"3": [RENAME]},
            names={"3": "local"},
            missing={"3": ["Email"]},
            answer=True,
        )
        assert note["style"]["display"] == ""
        assert "renameDevices" not in note["innerHTML"]
        assert "local: needs Email" in note["innerHTML"]
        assert confirms == [] and deploys == [], "a rename that would fail is never sent"

    def test_the_button_renames_only_the_boxes_it_can(self):
        deploys, confirms, note = _form(
            run="page",
            page=True,
            click=True,
            detailWorkers=_RUNNING,
            workers=[],
            renames={"3": [RENAME], "7": [RENAME]},
            names={"3": "local", "7": "unraid"},
            missing={"3": ["Email"]},
            answer=True,
        )
        assert 'data-action="renameDevices"' in note["innerHTML"] and "local: needs Email" in note["innerHTML"]
        assert len(confirms) == 1 and "• unraid: Device name" in confirms[0] and "local" not in confirms[0]
        assert [d["url"] for d in deploys] == ["/api/deploy/iproyal?worker_id=7"]

    def test_the_redeploy_button_offers_the_rename_too(self):
        deploys, confirms = _form(run="redeploy", workers=[3], renames={"3": [RENAME]}, answer=True)
        # The redeploy question, then the rename question.
        assert len(confirms) == 2 and LEGACY in confirms[1]
        assert deploys[0]["body"] == {"env": {}, "rename_devices": True}

    def test_a_box_that_needs_a_value_gets_its_own_redeploy_button(self):
        _, _, note = _form(
            run="page",
            page=True,
            detailWorkers=_RUNNING,
            renames={"3": [RENAME]},
            names={"3": "local"},
            missing={"3": ["Email"]},
        )
        assert 'data-action="redeployWithValues" data-a1="iproyal" data-a2="3"' in note["innerHTML"]

    def test_that_redeploy_sends_the_typed_values_and_renames(self):
        deploys, confirms, note = _form(
            run="withValues",
            workers=[3],
            renames={"3": [RENAME]},
            names={"3": "local"},
            missing={"3": ["Email"]},
            typed={"EMAIL": "me@x.io"},
            answer=True,
        )
        assert note["details"]["open"] is True, "the folded deploy form is opened"
        assert len(confirms) == 1 and LEGACY in confirms[0]
        assert [d["url"] for d in deploys] == ["/api/deploy/iproyal?worker_id=3"]
        assert deploys[0]["body"] == {"env": {"EMAIL": "me@x.io"}, "rename_devices": True}
        assert note.get("reopened") is True

    def test_that_redeploy_with_the_value_left_blank_sends_nothing(self):
        deploys, confirms, note = _form(
            run="withValues",
            workers=[3],
            renames={"3": [RENAME]},
            missing={"3": ["Email"]},
            typed={"EMAIL": ""},
            answer=True,
        )
        assert deploys == [] and confirms == [] and not note.get("reopened")

    def test_the_page_has_the_note_and_the_button_is_wired(self):
        js = (ROOT / "app/static/js/app.js").read_text(encoding="utf-8")
        assert 'id="device-rename-${escapeHtml(svc.slug)}"' in js
        assert "loadDeviceRenames(slug);" in js
        assert "\n    renameDevices,\n" in js
        assert "\n    redeployWithValues,\n" in js


class TestCopiesThatKeptTheOldNameAreOfferedAgain:
    """The original is renamed; a proxied copy whose rebuild failed is still offered, and only it is rebuilt."""

    COPY = {"3": ["proxied copy p4"]}

    def test_the_page_offers_the_button_for_a_box_with_only_a_pending_copy(self):
        deploys, confirms, note = _form(
            run="page", page=True, detailWorkers=_RUNNING, workers=[], renames={}, copies=self.COPY, answer=True
        )
        assert note["style"]["display"] == ""
        assert 'data-action="renameDevices"' in note["innerHTML"]
        assert confirms == [] and deploys == []

    def test_the_button_rebuilds_only_the_copies_never_the_original(self):
        result = _run_form(
            run="page",
            page=True,
            click=True,
            detailWorkers=_RUNNING,
            workers=[],
            renames={},
            copies=self.COPY,
            names={"3": "local"},
            answer=True,
            copyNotes=["proxied copy p4: stopped, so it keeps its old device name; add it again to rename it"],
        )
        urls = [c["url"] for c in result["calls"] if "/device-names?" not in c["url"]]
        assert urls == ["/api/deploy/iproyal/device-names/copies?worker_id=3"]
        assert (
            len(result["confirms"]) == 1
            and "• local: proxied copy p4 still has the old device name" in result["confirms"][0]
        )
        assert any(t["kind"] == "warning" and "proxied copy p4: stopped" in t["text"] for t in result["toasts"])

    def test_cancel_rebuilds_nothing(self):
        result = _run_form(
            run="page", page=True, click=True, detailWorkers=_RUNNING, workers=[], renames={}, copies=self.COPY
        )
        assert [c for c in result["calls"] if "/device-names?" not in c["url"]] == []

    def test_the_deploy_form_does_not_ask_about_copies(self):
        """A redeploy with rename_devices would not reach them: only the service page button rebuilds them."""
        deploys, confirms = _form(workers=[3], renames={}, copies=self.COPY, answer=True)
        assert confirms == [] and "rename_devices" not in deploys[0]["body"]


class TestAnImageRedeployShowsItsNotes:
    def test_a_copy_that_kept_its_old_name_is_reported(self):
        result = _run_form(
            run="image",
            image="iproyal/pawns-cli:2",
            apiWorkers=[{"id": 3, "name": "local", "status": "online", "containers": [{"slug": "iproyal"}]}],
            renames={"3": [RENAME]},
            answer=True,
            deployAnswer={"kept_from_previous_deployment": ["proxied copy p4: keeps its old device name (x)"]},
        )
        deploys = [c for c in result["calls"] if c["url"].startswith("/api/deploy/iproyal?")]
        assert deploys[0]["body"] == {"env": {}, "image": "iproyal/pawns-cli:2", "rename_devices": True}
        assert any(
            t["kind"] == "warning"
            and "local" in t["text"]
            and "proxied copy p4: keeps its old device name" in t["text"]
            for t in result["toasts"]
        )
