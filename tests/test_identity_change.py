"""Change one deployed device id from Settings > Device ids (issue #740).

Before this, a box that already ran a service could not get a new EarnApp,
ProxyRack, Spide or SpeedShare UUID, or a new device name, without removing it
and deploying again: the deploy form keeps a running box checked and disabled,
and Redeploy keeps the recorded values. Docker fixes a container's env when it
is created, so the one container must be made again with the new value, and
nothing else may move.

These tests pin who may change which row, how the new value is checked, that
the change is a redeploy of that one service on that one box through _deploy
(so every guard of a deploy still applies), that the typed device name is what
ships, the ledger and audit rows it leaves, and what happens to the proxied
copies, whose ids are made from the box's id.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import auth, database, main, proxies  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
UUID_A = "sdk-node-" + "a" * 32
UUID_B = "sdk-node-" + "b" * 28 + "1234"
UUID_C = "sdk-node-" + "c" * 28 + "5678"
RACK_A = "a1" * 32
RACK_B = "b2" * 32
OWNER = {"uid": 1, "u": "owner", "r": "owner"}
HONEYGAIN = {"HONEYGAIN_EMAIL": "me@example.com", "HONEYGAIN_PASSWORD": "pw"}


@pytest.fixture
def db(tmp_path):
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
        asyncio.run(database.init_db())
        for n in (1, 2):
            asyncio.run(database.upsert_worker(f"client-box-{n}", name=f"box-{n}"))
        yield tmp_path / "cashpilot.db"


def _rows():
    return asyncio.run(database.list_identities())


def _row(slug, worker_id, name, value, instance="1"):
    [row] = [
        r
        for r in _rows()
        if (r["slug"], r["worker_id"], r["name"], r["value"], r["instance"]) == (slug, worker_id, name, value, instance)
    ]
    return row


def _active():
    return {
        (r["slug"], r["worker_id"], r["instance"], r["name"]): r["value"] for r in _rows() if r["status"] == "active"
    }


class _Req:
    """A dashboard request carrying a JSON body."""

    def __init__(self, body=None):
        self._body = body or {}
        self.client = MagicMock(host="192.0.2.10")
        self.headers = {}
        self.url = MagicMock(path="/api/identities")
        self.cookies = {}

    async def json(self):
        return self._body


def _worker_mocks(sent, worker_id=1):
    async def hop(wid, method, path, *, json=None, **kwargs):
        sent.append({"worker": wid, "method": method, "path": path, "json": json})
        return {"container_id": f"c{wid}"}

    return [
        patch.object(main, "_proxy_to_worker", hop),
        patch.object(main, "_worker_features", AsyncMock(return_value={"instances"})),
        patch.object(main, "_worker_instances", AsyncMock(return_value=set())),
        patch.object(main, "_register_device", AsyncMock(return_value=False)),
        patch.object(main.database, "record_health_event", AsyncMock()),
        patch.object(main, "_spawn", lambda coro: coro.close()),
        patch.object(main.metrics, "record_container_lifecycle", lambda *a: None),
    ]


async def _with(patches, coro_fn):
    for p in patches:
        p.start()
    try:
        return await coro_fn()
    finally:
        for p in reversed(patches):
            p.stop()


def _deploy(slug, env, worker_id, *, instances=None):
    """A first deploy through the deploy route, so the record and the ledger are what a real one leaves."""
    sent: list[dict] = []
    body = main.DeployRequest(env=env, instances=instances)

    async def run():
        return await main.api_deploy(_Req(), slug, body, worker_id)

    patches = [
        patch.object(auth, "get_current_user", return_value=OWNER),
        patch.object(main, "_resolve_worker_id", AsyncMock(return_value=worker_id)),
        *_worker_mocks(sent, worker_id),
    ]
    asyncio.run(_with(patches, run))
    return sent


def _change(row_id, value, *, allow=False, user=OWNER, extra=(), body=None):
    """POST a change through the handler. Returns (answer or HTTPException, what reached the worker)."""
    sent: list[dict] = []
    body = {"value": value, **({"allow_shared_identity": True} if allow else {}), **(body or {})}

    async def run():
        try:
            return await main.api_identity_change(_Req(body), row_id)
        except HTTPException as exc:
            return exc

    patches = [patch.object(auth, "get_current_user", return_value=user), *_worker_mocks(sent), *extra]
    return asyncio.run(_with(patches, run)), sent


def _deploys(sent):
    return [
        s
        for s in sent
        if s["method"] == "POST" and s["path"].endswith("/deploy") and s["path"].startswith("/api/containers/")
    ]


# ---------------------------------------------------------------------------
# Which rows offer Change
# ---------------------------------------------------------------------------


class TestWhichRows:
    def test_only_an_id_a_deploy_set_and_a_box_runs_now(self, db):
        _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 1)
        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            _deploy("honeygain", {**HONEYGAIN, "HONEYGAIN_DEVICE_NAME": "box"}, 1, instances=2)
        # A proxied copy's own id, a node-reported one, one the owner typed in, and a removed one.
        asyncio.run(
            database.record_identities("honeygain", 1, {"p4": {"HONEYGAIN_DEVICE_NAME": "box-p4"}}, scope="given")
        )
        asyncio.run(database.record_node_identity("mysterium", 1, "0x" + "ab" * 20))
        asyncio.run(database.add_manual_identity("earnapp", 2, "1", "EARNAPP_UUID", UUID_C))
        _deploy("earnapp", {"EARNAPP_UUID": UUID_B}, 2)
        asyncio.run(database.remove_deployment("earnapp", worker_id=2))

        with patch.object(auth, "get_current_user", return_value=OWNER):
            listed = TestClient(main.app).get("/api/identities").json()
        changeable = {(r["slug"], r["worker_id"], r["key"], r["copy"]) for r in listed if r["changeable"]}
        assert changeable == {
            ("earnapp", 1, "EARNAPP_UUID", ""),
            ("honeygain", 1, "HONEYGAIN_DEVICE_NAME", ""),
        }

    @pytest.mark.parametrize(
        "which",
        ["retired", "proxied copy", "second copy", "node", "manual"],
    )
    def test_any_other_row_is_refused_and_nothing_is_deployed(self, db, which):
        _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 1)
        if which == "retired":
            _deploy("earnapp", {"EARNAPP_UUID": UUID_C}, 1)
            row = _row("earnapp", 1, "EARNAPP_UUID", UUID_A)
        elif which == "proxied copy":
            asyncio.run(
                database.record_identities("honeygain", 1, {"p4": {"HONEYGAIN_DEVICE_NAME": "x-p4"}}, scope="given")
            )
            row = _row("honeygain", 1, "HONEYGAIN_DEVICE_NAME", "x-p4", "p4")
        elif which == "second copy":
            with patch.object(main, "scaling_limit", lambda svc: (3, "")):
                _deploy("honeygain", {**HONEYGAIN, "HONEYGAIN_DEVICE_NAME": "box"}, 1, instances=2)
            row = _row("honeygain", 1, "HONEYGAIN_DEVICE_NAME", "box-2", "2")
        elif which == "node":
            asyncio.run(database.record_node_identity("mysterium", 1, "0x" + "ab" * 20))
            [row] = [r for r in _rows() if r["kind"] == "node"]
        else:
            asyncio.run(database.add_manual_identity("earnapp", 1, "1", "EARNAPP_UUID", UUID_C))
            [row] = [r for r in _rows() if r["kind"] == "manual"]
        answer, sent = _change(row["id"], UUID_B if row["slug"] == "earnapp" else "new-name")
        assert isinstance(answer, HTTPException) and answer.status_code == 409, answer
        assert _deploys(sent) == []

    def test_a_service_the_catalog_no_longer_deploys_has_no_change(self, db):
        """SpeedShare is dead in the catalog: _deploy refuses it, so a Change button could only ever fail."""
        record = {"image": "speedshare/speedshare", "env": {"CODE": "abc", "SPEEDSHARE_UUID": UUID_A}}
        asyncio.run(database.save_deployment("speedshare", "c1", spec=record, worker_id=1))
        asyncio.run(database.record_identities("speedshare", 1, {"1": record["env"]}))
        row = _row("speedshare", 1, "SPEEDSHARE_UUID", UUID_A)
        assert main.catalog.get_service("speedshare")["status"] in main._UNDEPLOYABLE_STATUSES

        with patch.object(auth, "get_current_user", return_value=OWNER):
            listed = TestClient(main.app).get("/api/identities").json()
        [view] = [r for r in listed if r["id"] == row["id"]]
        assert view["changeable"] is False
        answer, sent = _change(row["id"], UUID_B)
        assert answer.status_code == 409 and "Only an id" in answer.detail, answer.detail
        assert _deploys(sent) == []

    def test_an_unknown_row_is_404(self, db):
        answer, sent = _change(999, UUID_B)
        assert answer.status_code == 404 and sent == []

    @pytest.mark.parametrize(
        "user",
        [
            None,
            {"uid": 2, "u": "viewer", "r": "viewer"},
            {"uid": 3, "u": "writer", "r": "writer"},
            {"uid": 0, "u": "api", "r": "owner"},
        ],
        ids=["signed-out", "viewer", "writer", "admin-key"],
    )
    def test_only_a_signed_in_owner(self, db, user):
        _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 1)
        row = _row("earnapp", 1, "EARNAPP_UUID", UUID_A)
        sent: list[dict] = []
        patches = [patch.object(auth, "get_current_user", return_value=user), *_worker_mocks(sent)]
        for p in patches:
            p.start()
        try:
            response = TestClient(main.app).post(f"/api/identities/{row['id']}/change", json={"value": UUID_B})
        finally:
            for p in reversed(patches):
                p.stop()
        assert response.status_code in (401, 403), response.text
        assert _deploys(sent) == []


# ---------------------------------------------------------------------------
# The new value
# ---------------------------------------------------------------------------


class TestTheNewValue:
    @pytest.mark.parametrize(
        "value",
        ["sdk-node-XYZ", "sdk-node-" + "a" * 31, "", "   ", "sdk-node-" + "b" * 32 + " extra"],
    )
    def test_a_value_the_catalog_pattern_refuses_is_refused(self, db, value):
        """Refused by the change itself, before the deploy path (and its route and instance checks) runs."""
        _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 1)
        deploy = AsyncMock(return_value={"status": "deployed"})
        answer, sent = _change(
            _row("earnapp", 1, "EARNAPP_UUID", UUID_A)["id"], value, extra=[patch.object(main, "_deploy", deploy)]
        )
        assert isinstance(answer, HTTPException) and answer.status_code == 400, answer
        assert deploy.await_count == 0 and _deploys(sent) == []
        assert _active()[("earnapp", 1, "1", "EARNAPP_UUID")] == UUID_A

    @pytest.mark.parametrize("value", ["living room", "box;reboot", "cashpilot-{hostname}", "$(id)", "x" * 300])
    def test_a_device_name_must_be_one_safe_word(self, db, value):
        """It reaches the provider's command line, which the worker splits on whitespace."""
        _deploy("honeygain", {**HONEYGAIN, "HONEYGAIN_DEVICE_NAME": "box"}, 1)
        answer, sent = _change(_row("honeygain", 1, "HONEYGAIN_DEVICE_NAME", "box")["id"], value)
        assert answer.status_code == 400 and _deploys(sent) == []

    def test_the_same_value_is_refused(self, db):
        _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 1)
        answer, sent = _change(_row("earnapp", 1, "EARNAPP_UUID", UUID_A)["id"], f"  {UUID_A} ")
        assert answer.status_code == 400 and "already" in answer.detail and _deploys(sent) == []

    def test_a_value_another_box_runs_asks_first(self, db):
        _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 1)
        _deploy("earnapp", {"EARNAPP_UUID": UUID_C}, 2)
        row_id = _row("earnapp", 1, "EARNAPP_UUID", UUID_A)["id"]
        answer, sent = _change(row_id, UUID_C)
        assert answer.status_code == 409 and answer.detail["error"] == "identity_in_use"
        assert "box-2" in answer.detail["message"] and UUID_C not in str(answer.detail)
        assert _deploys(sent) == []
        # The owner saw it and confirms.
        answer, sent = _change(row_id, UUID_C, allow=True)
        assert answer["status"] == "deployed"
        assert [s["json"]["env"]["EARNAPP_UUID"] for s in _deploys(sent)] == [UUID_C]

    def test_a_device_name_another_box_runs_asks_first(self, db):
        _deploy("honeygain", {**HONEYGAIN, "HONEYGAIN_DEVICE_NAME": "box"}, 1)
        _deploy("honeygain", {**HONEYGAIN, "HONEYGAIN_DEVICE_NAME": "attic"}, 2)
        answer, sent = _change(_row("honeygain", 1, "HONEYGAIN_DEVICE_NAME", "box")["id"], "attic")
        assert answer.status_code == 409 and answer.detail["error"] == "identity_in_use"
        assert _deploys(sent) == []


# ---------------------------------------------------------------------------
# The change itself
# ---------------------------------------------------------------------------


class TestTheChange:
    def test_it_redeploys_only_that_service_on_that_box_with_the_new_id(self, db):
        _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 1)
        _deploy("earnapp", {"EARNAPP_UUID": UUID_C}, 2)
        _deploy("honeygain", {**HONEYGAIN, "HONEYGAIN_DEVICE_NAME": "box"}, 1)
        answer, sent = _change(_row("earnapp", 1, "EARNAPP_UUID", UUID_A)["id"], UUID_B)

        assert answer["status"] == "deployed"
        [deploy] = _deploys(sent)
        assert (deploy["worker"], deploy["path"]) == (1, "/api/containers/earnapp/deploy")
        assert deploy["json"]["env"]["EARNAPP_UUID"] == UUID_B
        # The rest of the spec is the record's: the volume that holds the node is still mounted.
        assert deploy["json"]["volumes"] == {"earnapp-data": {"bind": "/etc/earnapp", "mode": "rw"}}
        # The ledger: the old id removed, the new one in use, the other box and service untouched.
        assert _active() == {
            ("earnapp", 1, "1", "EARNAPP_UUID"): UUID_B,
            ("earnapp", 2, "1", "EARNAPP_UUID"): UUID_C,
            ("honeygain", 1, "1", "HONEYGAIN_DEVICE_NAME"): "box",
        }
        assert _row("earnapp", 1, "EARNAPP_UUID", UUID_A)["status"] == "retired"
        assert asyncio.run(database.get_deployment_spec("earnapp", worker_id=1))["env"]["EARNAPP_UUID"] == UUID_B

    def test_it_answers_the_notes_a_redeploy_answers(self, db):
        _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 1)
        answer, _ = _change(_row("earnapp", 1, "EARNAPP_UUID", UUID_A)["id"], UUID_B)
        # An EarnApp node earns for nobody until it is linked at earnapp.com/r/<uuid>.
        assert answer["device_link"]["id"] == UUID_B
        assert UUID_B in answer["device_link"]["url"]

    def test_it_is_audited_without_the_id(self, db):
        _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 1)
        _change(_row("earnapp", 1, "EARNAPP_UUID", UUID_A)["id"], UUID_B)
        [event] = [e for e in asyncio.run(database.get_audit_events()) if e["action"] == "identity_change"]
        assert (event["outcome"], event["actor"], event["worker_id"]) == ("changed", "owner", 1)
        assert "earnapp" in event["target"] and "EARNAPP_UUID" in event["target"]
        assert UUID_A not in str(event) and UUID_B not in str(event)

    def test_a_refused_deploy_changes_nothing_and_is_not_audited_as_a_change(self, db):
        _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 1)

        async def refuse(*a, **kw):
            raise HTTPException(status_code=409, detail="worker said no")

        answer, _ = _change(
            _row("earnapp", 1, "EARNAPP_UUID", UUID_A)["id"],
            UUID_B,
            extra=[patch.object(main, "_proxy_worker_deploy", refuse)],
        )
        assert answer.status_code == 409
        assert _active()[("earnapp", 1, "1", "EARNAPP_UUID")] == UUID_A
        assert not [e for e in asyncio.run(database.get_audit_events()) if e["action"] == "identity_change"]

    def test_the_typed_device_name_is_what_ships(self, db):
        """_deploy puts a running box's old shared name back after the merge (device_renames): never over a change."""
        legacy = f"cashpilot-{main.HOSTNAME_PREFIX}"
        record = {"image": "honeygain/honeygain", "env": {**HONEYGAIN, "HONEYGAIN_DEVICE_NAME": legacy}}
        asyncio.run(database.save_deployment("honeygain", "c1", spec=record, worker_id=1))
        asyncio.run(database.record_identities("honeygain", 1, {"1": record["env"]}))
        answer, sent = _change(_row("honeygain", 1, "HONEYGAIN_DEVICE_NAME", legacy)["id"], "living-room")

        assert answer["status"] == "deployed"
        [deploy] = _deploys(sent)
        assert deploy["json"]["env"]["HONEYGAIN_DEVICE_NAME"] == "living-room"
        assert "-device living-room" in deploy["json"]["command"]
        # The credentials came from the record: nothing but the name changed.
        assert deploy["json"]["env"]["HONEYGAIN_PASSWORD"] == "pw"
        assert _active()[("honeygain", 1, "1", "HONEYGAIN_DEVICE_NAME")] == "living-room"

    def test_a_second_name_of_the_same_service_is_left_alone(self, db):
        """IPRoyal has a device name and a device id, both made from the box: changing one keeps the other."""
        legacy = f"cashpilot-{main.HOSTNAME_PREFIX}"
        env = {
            "IPROYALPAWNS_EMAIL": "me@example.com",
            "IPROYALPAWNS_PASSWORD": "pw",
            "IPROYALPAWNS_DEVICE_NAME": legacy,
            "IPROYALPAWNS_DEVICE_ID": legacy,
        }
        asyncio.run(database.save_deployment("iproyal", "c1", spec={"image": "x", "env": env}, worker_id=1))
        asyncio.run(database.record_identities("iproyal", 1, {"1": env}))
        row = _row("iproyal", 1, "IPROYALPAWNS_DEVICE_NAME", legacy)
        answer, sent = _change(row["id"], "living-room")
        assert answer["status"] == "deployed"
        [deploy] = _deploys(sent)
        assert deploy["json"]["env"]["IPROYALPAWNS_DEVICE_NAME"] == "living-room"
        assert deploy["json"]["env"]["IPROYALPAWNS_DEVICE_ID"] == legacy

    def test_a_route_the_worker_remembers_asks_for_the_password_and_then_goes_through(self, db):
        """The UI lost the box's route record; the worker still refuses a direct deploy (route_locked).

        _deploy asks for the owner's password, the dashboard sends it with the
        change again, and the change must hand it on, or the same 403 comes back
        and the change can never finish.
        """
        _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 1)
        row_id = _row("earnapp", 1, "EARNAPP_UUID", UUID_A)["id"]
        calls: list[bool] = []

        async def worker(worker_id, slug, spec, *, approve=False, leave_route=False):
            calls.append(leave_route)
            if not leave_route:
                raise HTTPException(status_code=403, detail={"error": "route_locked", "message": "routed"})
            return {"container_id": "c1"}

        step_up_check = AsyncMock()
        extra = [
            patch.object(main, "_proxy_worker_deploy", worker),
            patch.object(main, "require_step_up", step_up_check),
            patch.object(main, "_routes_on", AsyncMock(return_value=[])),
            patch.object(main, "_refuse_direct_on_proxied_only", AsyncMock()),
        ]
        answer, _ = _change(row_id, UUID_B, extra=extra)
        assert answer.status_code == 403 and answer.detail["error"] == "step_up_required"
        assert _active()[("earnapp", 1, "1", "EARNAPP_UUID")] == UUID_A

        calls.clear()
        answer, _ = _change(row_id, UUID_B, extra=extra, body={"step_up_password": "pw"})
        assert answer["status"] == "deployed", answer
        assert calls == [False, True]
        assert step_up_check.await_args.args[1] == "pw"
        assert _active()[("earnapp", 1, "1", "EARNAPP_UUID")] == UUID_B

    def test_a_service_no_longer_deployed_there_is_refused(self, db):
        """An active row whose deployment record is gone: there is nothing to redeploy."""
        asyncio.run(database.record_identities("earnapp", 1, {"1": {"EARNAPP_UUID": UUID_A}}))
        answer, sent = _change(_row("earnapp", 1, "EARNAPP_UUID", UUID_A)["id"], UUID_B)
        assert answer.status_code == 409 and _deploys(sent) == []


# ---------------------------------------------------------------------------
# The proxied copies: their ids are made from the box's id
# ---------------------------------------------------------------------------


class TestProxiedCopies:
    def test_running_copies_follow_the_new_id_and_a_stopped_one_is_marked(self, db):
        """A copy left on an id made from the old one would change id unseen at its next rebuild.

        So a change rebuilds the running copies now, from the new record, the way
        a confirmed device rename does, and marks a stopped one, which the
        service page then lists with its rebuild button, and the answer says so.
        """
        worker_calls: list[dict] = []

        async def go():
            pids = []
            for host in ("a.example.net", "b.example.net"):
                created = await main.api_create_proxy(
                    _ProxyReq({"name": host, "kind": "socks5", "host": host, "port": 7777}), {}
                )
                pids.append(created["id"])
            running, stopped = pids
            record = {"image": "proxyrack/pop", "env": {"UUID": RACK_A, "DEVICE_NAME": "rack"}}
            await database.save_deployment("proxyrack", "c1", spec=record, worker_id=1)
            await database.record_identities("proxyrack", 1, {"1": record["env"]})
            for pid in pids:
                await database.save_proxied_copy(pid, 1, "proxyrack")
                earner = proxies.earner_spec(record, {"env": [{"key": "UUID", "per_device": True}]}, pid)
                await database.record_identities("proxyrack", 1, {f"p{pid}": earner["env"]}, scope="given")
            worker = await database.get_worker(1)
            worker["system_info"] = json.dumps(
                {
                    "docker_available": True,
                    "features": ["instances", "proxy_tunnel", "proxied_if_running"],
                    "proxied": [
                        {"proxy_id": running, "slug": "proxyrack", "held": False, "status": "running"},
                        {"proxy_id": stopped, "slug": "proxyrack", "held": False, "status": "exited"},
                    ],
                }
            )
            [row] = [
                r
                for r in await database.list_identities()
                if (r["instance"], r["name"], r["status"]) == ("1", "UUID", "active")
            ]

            async def worker_call(worker_id, method, path, definition, *, json=None, timeout=30):
                worker_calls.append({"path": path, "json": json})
                return {"status": "deployed", "exit": {}}

            sent: list[dict] = []
            patches = [
                patch.object(auth, "get_current_user", return_value=OWNER),
                *_worker_mocks(sent),
                patch.object(
                    main,
                    "_worker_features",
                    AsyncMock(return_value={"instances", "proxy_tunnel", "proxied_if_running"}),
                ),
                patch.object(main.database, "get_worker", AsyncMock(return_value=worker)),
                patch.object(main, "_proxy_worker_call", side_effect=worker_call),
            ]
            answer = await _with(patches, lambda: main.api_identity_change(_Req({"value": RACK_B}), row["id"]))
            return answer, sent, running, stopped

        answer, sent, running, stopped = asyncio.run(go())
        [deploy] = _deploys(sent)
        assert deploy["json"]["env"]["UUID"] == RACK_B
        # The running copy was rebuilt on an id made from the new one, and only it.
        [rebuilt] = worker_calls
        assert rebuilt["path"] == f"/api/proxied/proxyrack/{running}/deploy"
        assert rebuilt["json"]["earner"]["env"]["UUID"] == proxies.copy_device_id(RACK_B, running)
        active = _active()
        assert active[("proxyrack", 1, "1", "UUID")] == RACK_B
        assert active[("proxyrack", 1, f"p{running}", "UUID")] == proxies.copy_device_id(RACK_B, running)
        # The stopped one keeps its old id until the owner rebuilds it, and is told so.
        assert active[("proxyrack", 1, f"p{stopped}", "UUID")] == proxies.copy_device_id(RACK_A, stopped)
        notes = answer["kept_from_previous_deployment"]
        [note] = [n for n in notes if f"p{stopped}" in n]
        # The change was to a UUID: the note says so, and how to give the copy the new one.
        assert "device name or id" in note and "add it again" in note, note
        marked = {c["proxy_id"]: c["rename_pending"] for c in asyncio.run(database.list_proxied_copies())}
        assert marked == {running: 0, stopped: 1}

    def test_a_copy_list_that_cannot_be_read_is_a_note_not_an_error(self, db):
        """The new id is already deployed when the copies are looked up.

        If the copy list, its marks or the worker cannot be read then, the
        change stands, so the answer must be the deploy's, with a note that the
        proxied copies may keep the old id, never an error.
        """
        _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 1)
        broken = patch.object(main.database, "list_proxied_copies", AsyncMock(side_effect=RuntimeError("db locked")))
        answer, sent = _change(_row("earnapp", 1, "EARNAPP_UUID", UUID_A)["id"], UUID_B, extra=(broken,))
        assert not isinstance(answer, Exception), answer
        assert _deploys(sent)[0]["json"]["env"]["EARNAPP_UUID"] == UUID_B
        assert _active()[("earnapp", 1, "1", "EARNAPP_UUID")] == UUID_B
        [note] = [n for n in answer["kept_from_previous_deployment"] if "proxied copies" in n]
        assert "old device name or id" in note and UUID_A not in note and UUID_B not in note

    @pytest.mark.parametrize("fails", ["set_proxied_copy_rename_pending", "get_worker"])
    def test_the_helper_never_raises_while_it_prepares(self, db, fails):
        record = {"image": "proxyrack/pop", "env": {"UUID": RACK_A, "DEVICE_NAME": "rack"}}

        async def go():
            await database.save_proxied_copy(5, 1, "proxyrack")
            with patch.object(main.database, fails, AsyncMock(side_effect=RuntimeError("db locked"))):
                return await main._refresh_proxied_copies("proxyrack", 1, {"slug": "proxyrack"}, {}, record)

        [note] = asyncio.run(go())
        assert "proxied copies" in note and "old device name or id" in note


class _ProxyReq:
    def __init__(self, body):
        self._body = body
        self.url = MagicMock(path="/api/proxies")

    async def json(self):
        return self._body


# ---------------------------------------------------------------------------
# The list's Change button and form, run in node
# ---------------------------------------------------------------------------


_HARNESS = r"""
const src = require('fs').readFileSync(process.argv[process.argv.length - 2], 'utf8');
const from = src.indexOf('  function identityRowsHtml(rows) {');
const to = src.indexOf('  // The form for an id CashPilot did not deploy with.');
if (from < 0 || to <= from) { console.log(JSON.stringify({error: 'block moved'})); process.exit(0); }
const escapeHtml = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
const fns = new Function('escapeHtml', `${src.slice(from, to)}; return { identityRowsHtml, identityChangeHtml };`)(escapeHtml);
const [fn, arg] = JSON.parse(process.argv[process.argv.length - 1]);
console.log(JSON.stringify({ html: fns[fn](arg) }));
"""


def _render(fn, arg):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    out = subprocess.run(
        [node, "-e", _HARNESS, str(ROOT / "app/static/js/app.js"), json.dumps([fn, arg])],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    result = json.loads(out.stdout)
    assert "error" not in result, result
    return result["html"]


_VIEW = {
    "id": 7,
    "slug": "earnapp",
    "service": "EarnApp",
    "worker_id": 3,
    "worker": "attic",
    "copy": "",
    "kind": "env",
    "key": "EARNAPP_UUID",
    "label": "Node UUID",
    "masked": "...aaaa",
    "readable": True,
    "source": "deploy",
    "status": "active",
    "pending": False,
    "forgettable": False,
    "changeable": True,
}


class TestTheListUi:
    def test_a_changeable_row_has_a_change_button(self):
        html = _render("identityRowsHtml", [_VIEW])
        assert 'data-action="openIdentityChange" data-a1="7"' in html
        assert 'id="identity-change-7"' in html

    def test_any_other_row_has_none(self):
        html = _render("identityRowsHtml", [{**_VIEW, "changeable": False}])
        assert "openIdentityChange" not in html

    def test_the_form_offers_earlier_ids_for_that_box_and_says_what_happens(self):
        html = _render("identityChangeHtml", _VIEW)
        # "Use one this service had before", asked for this field on this box.
        assert 'data-action="pickPreviousIdentity" data-a1="earnapp" data-a2="EARNAPP_UUID" data-a3="3"' in html
        assert 'data-slug="earnapp" data-key="EARNAPP_UUID"' in html
        assert 'data-action="changeIdentity" data-a1="7"' in html
        assert "proxied copies" in html and "nothing else" in html
        # The service page's button skips a stopped copy: adding it to its proxy again is what rebuilds it.
        assert "add it to its proxy again" in html and "rebuild it on the service page" not in html

    def test_names_are_escaped(self):
        html = _render("identityChangeHtml", {**_VIEW, "service": "<b>x</b>", "worker": "<i>y</i>"})
        assert "<b>x</b>" not in html and "<i>y</i>" not in html and "&lt;b&gt;" in html


# A tiny DOM: each id="..." in the HTML an element gets becomes a fresh element,
# and redrawing a parent drops its old children, as the browser does.
_REFRESH_HARNESS = r"""
const src = require('fs').readFileSync(process.argv[process.argv.length - 1], 'utf8');
const cut = (a, b) => {
  const from = src.indexOf(a); const to = src.indexOf(b);
  if (from < 0 || to <= from) { console.log(JSON.stringify({error: 'block moved'})); process.exit(0); }
  return src.slice(from, to);
};
const escapeHtml = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
const els = new Map();
function el(id) {
  const e = { id, value: '', kids: [], _html: '', focus() {}, get isConnected() { return els.get(id) === e; },
    get innerHTML() { return this._html; },
    set innerHTML(h) {
      const drop = k => { const c = els.get(k); if (c) { c.kids.forEach(drop); els.delete(k); } };
      this.kids.forEach(drop);
      this._html = h;
      this.kids = [...h.matchAll(/id="([^"]+)"/g)].map(m => m[1]);
      this.kids.forEach(k => els.set(k, el(k)));
    } };
  return e;
}
els.set('identities-container', el('identities-container'));
const document = {
  getElementById: id => els.get(id) || null,
  querySelectorAll: sel => sel === '.identity-change'
    ? [...els.values()].filter(e => /^identity-change-\d+$/.test(e.id)) : [],
};
const rows = [1, 2].map(id => ({ id, slug: 'earnapp', service: 'EarnApp', worker_id: id, worker: `box-${id}`,
  copy: '', kind: 'env', key: 'EARNAPP_UUID', label: 'Node UUID', masked: '...', readable: true,
  source: 'deploy', status: 'active', pending: false, forgettable: false, changeable: true }));
let release;
const api = (path) => path === '/api/identities'
  ? Promise.resolve(rows) : new Promise(r => { release = () => r({ status: 'deployed' }); });
const window = { confirm: () => true };
const toast = () => {};
const fns = new Function('escapeHtml', 'document', 'api', 'window', 'toast',
  `${cut('  function identityRowsHtml(rows) {', '  // The form for an id CashPilot did not deploy with.')}
   ${cut('  // The rows last listed, by id, for the Change form', '  // Every id in full, as a file.')}
   return { loadIdentities, openIdentityChange, closeIdentityChange, changeIdentity };`
)(escapeHtml, document, api, window, toast);
(async () => {
  await fns.loadIdentities();
  // Change box 1, then open box 2's form and type in it while box 1 redeploys.
  fns.openIdentityChange(1);
  document.getElementById('identity-change-value-1').value = 'sdk-node-new';
  const pending = fns.changeIdentity(1);
  fns.openIdentityChange(2);
  document.getElementById('identity-change-value-2').value = 'half typed';
  release();
  await pending;
  await new Promise(r => setTimeout(r, 0));
  const one = document.getElementById('identity-change-1');
  const two = document.getElementById('identity-change-value-2');
  console.log(JSON.stringify({ oneOpen: !!(one && one.innerHTML), two: two ? two.value : null }));
})();
"""


def test_a_finished_change_keeps_the_form_open_on_another_row():
    """Box 1's change redraws the list when it ends; box 2's open form and what was typed in it stay."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    out = subprocess.run(
        [node, "-e", _REFRESH_HARNESS, str(ROOT / "app/static/js/app.js")],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    result = json.loads(out.stdout)
    assert result == {"oneOpen": False, "two": "half typed"}, result
