"""CashPilot keeps the device ids it deployed with, after a removal too (issue #740).

Before this, removing a service deleted its deploy record, and with it the
EarnApp or ProxyRack UUID and the device names CashPilot had set: nothing could
show them again or put them on a new box. These tests pin the identity ledger
(retired, not deleted), which keys it keeps (only what the catalog marks, never
a secret), the owner-only list with audited reveals, the deploy form's reuse
offer, and the refusal to put one device id on two boxes without asking.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import auth, catalog, database, main  # noqa: E402

UUID_A = "sdk-node-" + "a" * 32
UUID_B = "sdk-node-" + "b" * 28 + "1234"
UUID_C = "sdk-node-" + "c" * 28 + "5678"
OWNER = {"uid": 1, "u": "owner", "r": "owner"}


@pytest.fixture
def db(tmp_path):
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
        asyncio.run(database.init_db())
        # Boxes 1 and 2, which most tests deploy to: a deleted box's rows count
        # for nothing, so a box a test names must exist.
        for n in (1, 2):
            asyncio.run(database.upsert_worker(f"client-box-{n}", name=f"box-{n}"))
        yield tmp_path / "cashpilot.db"


def _rows():
    return asyncio.run(database.list_identities())


def _active(rows=None):
    return {
        (r["slug"], r["worker_id"], r["instance"], r["name"]): r["value"]
        for r in (rows or _rows())
        if r["status"] == "active"
    }


def _retired(rows=None):
    return {
        (r["slug"], r["worker_id"], r["instance"], r["name"], r["value"])
        for r in (rows or _rows())
        if r["status"] == "retired"
    }


# ---------------------------------------------------------------------------
# Which values are identifiers: the catalog says, and never a secret
# ---------------------------------------------------------------------------


class TestFromTheCatalog:
    def test_device_ids_and_names_are_identifiers(self):
        assert set(catalog.identity_keys(catalog.get_service("earnapp"))) == {"EARNAPP_UUID"}
        assert set(catalog.identity_keys(catalog.get_service("proxyrack"))) == {"UUID", "DEVICE_NAME"}
        assert set(catalog.identity_keys(catalog.get_service("honeygain"))) == {"HONEYGAIN_DEVICE_NAME"}
        assert set(catalog.identity_keys(catalog.get_service("iproyal"))) == {
            "IPROYALPAWNS_DEVICE_NAME",
            "IPROYALPAWNS_DEVICE_ID",
        }

    def test_no_identifier_in_the_catalog_is_a_secret(self):
        for svc in catalog.get_services():
            secrets_ = {v["key"] for v in (svc.get("docker") or {}).get("env") or [] if v.get("secret")}
            assert not set(catalog.identity_keys(svc)) & secrets_, svc["slug"]

    def test_every_device_name_the_catalog_fills_per_box_is_an_identifier(self):
        """A {hostname} default is a device name the provider counts by: it must be kept too."""
        for svc in catalog.get_services():
            named = {
                v["key"]
                for v in (svc.get("docker") or {}).get("env") or []
                if "{hostname}" in str(v.get("default", ""))
            }
            assert named <= set(catalog.identity_keys(svc)), svc["slug"]

    def test_the_loader_refuses_a_secret_identifier(self, tmp_path):
        data = {
            "name": "X",
            "slug": "x",
            "docker": {"image": "x/x:1", "env": [{"key": "K", "secret": True, "identifier": True}]},
        }
        errors = catalog._validate(data, tmp_path / "x.yml")
        assert any("cannot be an identifier" in e for e in errors)

    def test_the_loader_refuses_a_secret_per_device_key(self, tmp_path):
        data = {
            "name": "X",
            "slug": "x",
            "docker": {"image": "x/x:1", "env": [{"key": "K", "secret": True, "per_device": True}]},
        }
        assert any("cannot be an identifier" in e for e in catalog._validate(data, tmp_path / "x.yml"))

    def test_the_loader_wants_a_boolean(self, tmp_path):
        data = {"name": "X", "slug": "x", "docker": {"image": "x/x:1", "env": [{"key": "K", "identifier": "yes"}]}}
        assert any("identifier must be a boolean" in e for e in catalog._validate(data, tmp_path / "x.yml"))

    def test_identity_keys_skips_a_secret_even_if_marked(self):
        svc = {"docker": {"env": [{"key": "K", "secret": True, "identifier": True}, {"key": "N", "identifier": True}]}}
        assert catalog.identity_keys(svc) == {"N": "N"}


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------


class TestTheLedger:
    def test_only_identifier_keys_are_kept_never_a_password(self, db):
        env = {"HONEYGAIN_EMAIL": "me@example.com", "HONEYGAIN_PASSWORD": "hunter22", "HONEYGAIN_DEVICE_NAME": "box-a"}
        asyncio.run(database.record_identities("honeygain", 1, {"1": env}))
        assert _active() == {("honeygain", 1, "1", "HONEYGAIN_DEVICE_NAME"): "box-a"}
        raw = sqlite3.connect(db).execute("SELECT value_encrypted FROM device_identities").fetchall()
        assert all(r[0].startswith("enc:") and "box-a" not in r[0] for r in raw)
        assert "hunter22" not in str(_rows())

    def test_a_redeploy_with_another_value_retires_the_old_one(self, db):
        asyncio.run(database.record_identities("earnapp", 1, {"1": {"EARNAPP_UUID": UUID_A}}))
        asyncio.run(database.record_identities("earnapp", 1, {"1": {"EARNAPP_UUID": UUID_B}}))
        rows = _rows()
        assert _active(rows) == {("earnapp", 1, "1", "EARNAPP_UUID"): UUID_B}
        assert ("earnapp", 1, "1", "EARNAPP_UUID", UUID_A) in _retired(rows)

    def test_the_same_value_again_keeps_one_row(self, db):
        for _ in range(3):
            asyncio.run(database.record_identities("earnapp", 1, {"1": {"EARNAPP_UUID": UUID_A}}))
        assert len(_rows()) == 1

    def test_reusing_a_retired_value_on_the_same_copy_brings_its_row_back(self, db):
        for value in (UUID_A, UUID_B, UUID_A):
            asyncio.run(database.record_identities("earnapp", 1, {"1": {"EARNAPP_UUID": value}}))
        rows = _rows()
        assert len(rows) == 2
        assert _active(rows) == {("earnapp", 1, "1", "EARNAPP_UUID"): UUID_A}

    def test_fewer_copies_retire_the_copies_that_went(self, db):
        env = lambda n: {"HONEYGAIN_DEVICE_NAME": f"box-{n}"}  # noqa: E731
        asyncio.run(database.record_identities("honeygain", 1, {"1": env(1), "2": env(2), "3": env(3)}))
        asyncio.run(database.record_identities("honeygain", 1, {"1": env(1)}))
        rows = _rows()
        assert set(_active(rows)) == {("honeygain", 1, "1", "HONEYGAIN_DEVICE_NAME")}
        assert {r[2] for r in _retired(rows)} == {"2", "3"}

    def test_a_deploy_leaves_the_proxied_copies_alone(self, db):
        asyncio.run(
            database.record_identities("honeygain", 1, {"p4": {"HONEYGAIN_DEVICE_NAME": "box-p4"}}, scope="given")
        )
        asyncio.run(database.record_identities("honeygain", 1, {"1": {"HONEYGAIN_DEVICE_NAME": "box"}}))
        assert ("honeygain", 1, "p4", "HONEYGAIN_DEVICE_NAME") in _active()

    def test_removing_the_service_retires_its_ids_instead_of_deleting_them(self, db):
        """The regression: remove_deployment used to forget the ids it deployed with."""
        spec = {"env": {"EARNAPP_UUID": UUID_A}}
        asyncio.run(database.save_deployment("earnapp", "c1", spec=spec, worker_id=1))
        asyncio.run(database.record_identities("earnapp", 1, {"1": spec["env"]}))
        asyncio.run(database.remove_deployment("earnapp", worker_id=1))
        rows = _rows()
        assert _active(rows) == {}
        assert ("earnapp", 1, "1", "EARNAPP_UUID", UUID_A) in _retired(rows)

    def test_a_deployment_from_before_the_ledger_is_kept_on_removal(self, db):
        """No ledger row yet, only the deploy record: its ids still survive the removal."""
        asyncio.run(database.save_deployment("earnapp", "c1", spec={"env": {"EARNAPP_UUID": UUID_A}}, worker_id=2))
        asyncio.run(database.remove_deployment("earnapp"))
        assert _retired() == {("earnapp", 2, "1", "EARNAPP_UUID", UUID_A)}

    def test_removing_on_one_box_keeps_the_other_box_active(self, db):
        asyncio.run(database.record_identities("earnapp", 1, {"1": {"EARNAPP_UUID": UUID_A}}))
        asyncio.run(database.record_identities("earnapp", 2, {"1": {"EARNAPP_UUID": UUID_B}}))
        asyncio.run(database.remove_deployment("earnapp", worker_id=1))
        assert _active() == {("earnapp", 2, "1", "EARNAPP_UUID"): UUID_B}

    def test_a_proxied_copy_removed_is_retired(self, db):
        asyncio.run(database.save_proxied_copy(4, 1, "honeygain"))
        asyncio.run(
            database.record_identities("honeygain", 1, {"p4": {"HONEYGAIN_DEVICE_NAME": "box-p4"}}, scope="given")
        )
        asyncio.run(database.delete_proxied_copy(4, 1, "honeygain"))
        assert ("honeygain", 1, "p4", "HONEYGAIN_DEVICE_NAME", "box-p4") in _retired()

    def test_only_a_retired_row_can_be_forgotten(self, db):
        asyncio.run(database.record_identities("earnapp", 1, {"1": {"EARNAPP_UUID": UUID_A}}))
        row = _rows()[0]
        assert asyncio.run(database.delete_identity(row["id"])) is False
        asyncio.run(database.remove_deployment("earnapp", worker_id=1))
        assert asyncio.run(database.delete_identity(row["id"])) is True
        assert _rows() == []

    def test_in_use_names_the_other_boxes_only(self, db):
        asyncio.run(database.record_identities("earnapp", 1, {"1": {"EARNAPP_UUID": UUID_A}}))
        assert asyncio.run(database.identity_in_use("earnapp", "EARNAPP_UUID", UUID_A, except_worker=2)) == [1]
        assert asyncio.run(database.identity_in_use("earnapp", "EARNAPP_UUID", UUID_A, except_worker=1)) == []
        assert asyncio.run(database.identity_in_use("earnapp", "EARNAPP_UUID", UUID_B)) == []

    @pytest.mark.parametrize("value", ["0x" + "ab" * 20, "node-1.box:2"])
    def test_a_plain_node_identity_is_kept_as_reported(self, db, value):
        assert asyncio.run(database.record_node_identity("mysterium", 3, value)) is True
        assert asyncio.run(database.record_node_identity("mysterium", 3, value.upper())) is True
        rows = _rows()
        assert len(rows) == 1
        assert (rows[0]["kind"], rows[0]["source"], rows[0]["value"]) == ("node", "node", value)

    @pytest.mark.parametrize("value", ["", "<img src=x onerror=alert(1)>", "0x12 rm -rf", "a" * 129, "=HYPERLINK(1)"])
    def test_anything_else_a_node_says_is_left_out(self, db, value):
        assert asyncio.run(database.record_node_identity("mysterium", 3, value)) is False
        assert _rows() == []


# ---------------------------------------------------------------------------
# The owner-only routes
# ---------------------------------------------------------------------------


ROUTES = [
    ("GET", "/api/identities"),
    ("POST", "/api/identities/1/reveal"),
    ("DELETE", "/api/identities/1"),
    ("GET", "/api/identities/reuse/earnapp?key=EARNAPP_UUID"),
]


def _call(user, method, path):
    client = TestClient(main.app)
    with patch.object(auth, "get_current_user", return_value=user):
        return client.request(method, path)


class TestWhoMayRead:
    @pytest.mark.parametrize(("method", "path"), ROUTES)
    @pytest.mark.parametrize(
        "user",
        [
            {"uid": 2, "u": "viewer", "r": "viewer"},
            {"uid": 3, "u": "writer", "r": "writer"},
            {"uid": 0, "u": "readonly", "r": "reader"},
            {"uid": 0, "u": "api", "r": "owner"},
            {"uid": 0, "u": "fleet", "r": "fleet"},
        ],
        ids=["viewer", "writer", "reader-key", "admin-key", "fleet-key"],
    )
    def test_no_one_but_a_signed_in_owner(self, db, method, path, user):
        asyncio.run(database.record_identities("earnapp", 1, {"1": {"EARNAPP_UUID": UUID_A}}))
        response = _call(user, method, path)
        assert response.status_code in (401, 403), response.text
        assert UUID_A not in response.text

    @pytest.mark.parametrize(("method", "path"), ROUTES)
    def test_signed_out_is_refused(self, db, method, path):
        assert _call(None, method, path).status_code in (401, 403)

    def test_the_settings_page_is_owner_only(self, db):
        for role in ("viewer", "writer"):
            assert _call({"uid": 5, "u": role, "r": role}, "GET", "/settings").status_code == 403


class TestTheList:
    def test_the_list_is_masked(self, db):
        asyncio.run(database.record_identities("earnapp", 1, {"1": {"EARNAPP_UUID": UUID_A}}))
        response = _call(OWNER, "GET", "/api/identities")
        assert response.status_code == 200
        assert UUID_A not in response.text
        [row] = response.json()
        assert row["masked"] == "..." + UUID_A[-4:]
        assert (row["service"], row["label"], row["status"]) == ("EarnApp", "Node UUID", "active")

    def test_a_reveal_is_audited_and_returns_the_value(self, db):
        asyncio.run(database.record_identities("earnapp", 1, {"1": {"EARNAPP_UUID": UUID_A}}))
        row_id = _rows()[0]["id"]
        response = _call(OWNER, "POST", f"/api/identities/{row_id}/reveal")
        assert response.json() == {"value": UUID_A}
        [event] = asyncio.run(database.get_audit_events())
        assert (event["action"], event["outcome"], event["actor"], event["worker_id"]) == (
            "identity_reveal",
            "revealed",
            "owner",
            1,
        )
        assert UUID_A not in str(event)

    def test_no_audit_row_no_value(self, db):
        asyncio.run(database.record_identities("earnapp", 1, {"1": {"EARNAPP_UUID": UUID_A}}))
        row_id = _rows()[0]["id"]
        client = TestClient(main.app, raise_server_exceptions=False)
        with (
            patch.object(auth, "get_current_user", return_value=OWNER),
            patch.object(database, "add_audit_event", AsyncMock(side_effect=sqlite3.OperationalError("full"))),
        ):
            response = client.post(f"/api/identities/{row_id}/reveal")
        assert response.status_code == 500 and UUID_A not in response.text

    def test_forgetting_an_id_in_use_is_refused(self, db):
        asyncio.run(database.record_identities("earnapp", 1, {"1": {"EARNAPP_UUID": UUID_A}}))
        row_id = _rows()[0]["id"]
        assert _call(OWNER, "DELETE", f"/api/identities/{row_id}").status_code == 409
        asyncio.run(database.remove_deployment("earnapp", worker_id=1))
        assert _call(OWNER, "DELETE", f"/api/identities/{row_id}").status_code == 200
        assert asyncio.run(database.get_audit_events())[0]["action"] == "identity_forget"

    def test_a_node_reported_identity_is_labelled(self, db):
        asyncio.run(database.record_node_identity("mysterium", 3, "0x" + "ab" * 20))
        [row] = _call(OWNER, "GET", "/api/identities").json()
        assert (row["source"], row["label"]) == ("node", "Node identity")


class TestTheReuseOffer:
    def test_it_offers_retired_deploy_values_with_where_they_run(self, db):
        asyncio.run(database.record_identities("earnapp", 1, {"1": {"EARNAPP_UUID": UUID_A}}))
        asyncio.run(database.remove_deployment("earnapp", worker_id=1))
        [offer] = _call(OWNER, "GET", "/api/identities/reuse/earnapp?key=EARNAPP_UUID").json()
        assert offer["masked"].endswith(UUID_A[-4:]) and offer["in_use_on"] == []
        # Deployed again elsewhere: the offer now says where.
        asyncio.run(database.record_identities("earnapp", 2, {"1": {"EARNAPP_UUID": UUID_A}}))
        [offer] = _call(OWNER, "GET", "/api/identities/reuse/earnapp?key=EARNAPP_UUID").json()
        assert offer["in_use_on"] == ["box-2"]
        [offer] = _call(OWNER, "GET", "/api/identities/reuse/earnapp?key=EARNAPP_UUID&worker_id=2").json()
        assert offer["in_use_on"] == []

    def test_it_never_offers_an_active_or_node_reported_value(self, db):
        asyncio.run(database.record_identities("earnapp", 1, {"1": {"EARNAPP_UUID": UUID_A}}))
        asyncio.run(database.record_node_identity("mysterium", 1, "0x" + "ab" * 20))
        asyncio.run(database.remove_deployment("mysterium", worker_id=1))
        assert _call(OWNER, "GET", "/api/identities/reuse/earnapp?key=EARNAPP_UUID").json() == []
        assert _call(OWNER, "GET", "/api/identities/reuse/mysterium?key=node%20identity").status_code == 404

    def test_a_field_that_is_not_an_identifier_is_refused(self, db):
        response = _call(OWNER, "GET", "/api/identities/reuse/honeygain?key=HONEYGAIN_PASSWORD")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# The deploy and removal routes
# ---------------------------------------------------------------------------


def _request():
    request = MagicMock()
    request.client.host = "192.0.2.10"
    request.headers = {}
    return request


def _deploy(
    slug,
    env,
    worker_id,
    *,
    instances=None,
    allow=False,
    fail=None,
    running=frozenset(),
    ran=None,
    replaced=None,
    user=OWNER,
    image=None,
    password=None,
):
    """Deploy through the route.

    ``ran``: {copy: the ids it runs with}, which a DELETE answers as a digest.
    ``replaced``: {copy: the ids the container a deploy replaces ran}, which the
    worker's deploy answer carries as ``replaced_identity_digest``.
    """
    sent: list[dict] = []

    async def hop(wid, method, path, *, json=None, **kwargs):
        if fail and fail(method, path, json):
            raise HTTPException(status_code=502, detail="worker failed")
        sent.append({"worker": wid, "path": path, "json": json})
        if method == "DELETE":
            n = int(path.rsplit("/", 1)[1])
            return {"status": "removed", **({"identity_digest": _digest(slug, ran[n])} if (ran or {}).get(n) else {})}
        n = (json or {}).get("instance") or 1
        old = (replaced or {}).get(n)
        return {"container_id": f"c{wid}", **({"replaced_identity_digest": _digest(slug, old)} if old else {})}

    body = main.DeployRequest(
        env=env, instances=instances, allow_shared_identity=allow, image=image, step_up_password=password
    )

    async def run():
        with (
            patch.object(auth, "get_current_user", return_value=user),
            patch.object(main, "_resolve_worker_id", AsyncMock(return_value=worker_id)),
            patch.object(main, "_proxy_to_worker", hop),
            patch.object(main, "_worker_features", AsyncMock(return_value={"instances"})),
            patch.object(main, "_worker_instances", AsyncMock(return_value=set(running))),
            patch.object(main, "_register_device", AsyncMock(return_value=True)),
            patch.object(main.database, "record_health_event", AsyncMock()),
            patch.object(main, "_spawn", lambda coro: coro.close()),
            patch.object(main.metrics, "record_container_lifecycle", lambda *a: None),
        ):
            try:
                await main.api_deploy(_request(), slug, body, worker_id)
            except HTTPException as exc:
                return exc
            return None

    return asyncio.run(run()), sent


class TestTheDeploy:
    def test_a_deploy_records_each_copys_own_device_name(self, db):
        env = {"HONEYGAIN_EMAIL": "me@example.com", "HONEYGAIN_PASSWORD": "pw", "HONEYGAIN_DEVICE_NAME": "box"}
        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            error, sent = _deploy("honeygain", env, 1, instances=2)
        assert error is None
        sent_names = {s["json"]["env"]["HONEYGAIN_DEVICE_NAME"] for s in sent if s["json"]}
        assert _active() == {
            ("honeygain", 1, "1", "HONEYGAIN_DEVICE_NAME"): "box",
            ("honeygain", 1, "2", "HONEYGAIN_DEVICE_NAME"): "box-2",
        }
        assert set(_active().values()) == sent_names

    def test_the_same_device_id_on_a_second_box_asks_first(self, db):
        assert _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 1)[0] is None
        error, sent = _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 2)
        assert error.status_code == 409 and error.detail["error"] == "identity_in_use"
        assert UUID_A not in str(error.detail)
        assert sent == []

    def test_the_owner_may_confirm_it(self, db):
        assert _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 1)[0] is None
        error, sent = _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 2, allow=True)
        assert error is None and sent

    def test_a_redeploy_on_the_same_box_does_not_ask(self, db):
        assert _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 1)[0] is None
        assert _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 1)[0] is None

    def test_a_retired_id_is_free_to_reuse(self, db):
        assert _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 1)[0] is None
        asyncio.run(database.remove_deployment("earnapp", worker_id=1))
        assert _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 2)[0] is None
        assert _active() == {("earnapp", 2, "1", "EARNAPP_UUID"): UUID_A}

    def test_the_remove_route_keeps_the_id(self, db):
        """End to end: deploy, remove through the route, and the id is still listed."""
        assert _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 1)[0] is None

        async def remove():
            with (
                patch.object(main, "_require_writer", lambda r: OWNER),
                patch.object(main, "_resolve_worker_id", AsyncMock(return_value=1)),
                patch.object(main, "_proxy_worker_command", AsyncMock(return_value={"status": "removed"})),
                patch.object(main.database, "record_health_event", AsyncMock()),
                patch.object(main.metrics, "record_container_lifecycle", lambda *a: None),
            ):
                await main._svc_remove(_request(), "earnapp", 1, False)

        asyncio.run(remove())
        assert asyncio.run(database.get_deployment_spec("earnapp", worker_id=1)) is None
        assert ("earnapp", 1, "1", "EARNAPP_UUID", UUID_A) in _retired()


# ---------------------------------------------------------------------------
# Review of #753: bounded node rows, deleted boxes, old deployments, raw route,
# and the admin key that must not mint an owner
# ---------------------------------------------------------------------------


NODE_A = "0x" + "ab" * 20
NODE_B = "0x" + "cd" * 20


class TestNodeRows:
    def test_a_new_node_identity_retires_the_old_one_of_that_copy(self, db):
        asyncio.run(database.record_node_identity("mysterium", 1, NODE_A))
        asyncio.run(database.record_node_identity("mysterium", 1, NODE_B))
        rows = _rows()
        assert {(r["instance"], r["value"]) for r in rows if r["status"] == "active"} == {("1", NODE_B)}
        assert {r["value"] for r in rows if r["status"] == "retired"} == {NODE_A}

    def test_each_copy_keeps_its_own_node_identity(self, db):
        asyncio.run(database.record_node_identity("mysterium", 1, NODE_A, 1))
        asyncio.run(database.record_node_identity("mysterium", 1, NODE_B, 2))
        assert {(r["instance"], r["value"]) for r in _rows() if r["status"] == "active"} == {
            ("1", NODE_A),
            ("2", NODE_B),
        }

    def test_a_node_rotating_its_identity_cannot_grow_the_table(self, db):
        for n in range(300):
            assert asyncio.run(database.record_node_identity("mysterium", 1, f"0x{n:040x}")) is True
        rows = _rows()
        assert sum(r["status"] == "active" for r in rows) == 1
        assert len(rows) <= 1 + database.NODE_IDENTITY_KEEP_RETIRED

    @pytest.mark.parametrize("copy", [0, -1, 33, 10**9, "x", None])
    def test_a_copy_number_out_of_range_is_left_out(self, db, copy):
        assert asyncio.run(database.record_node_identity("mysterium", 1, NODE_A, copy)) is False
        assert _rows() == []

    def test_the_owner_may_forget_an_active_node_row(self, db):
        asyncio.run(database.record_node_identity("mysterium", 1, NODE_A))
        row = _rows()[0]
        assert _call(OWNER, "DELETE", f"/api/identities/{row['id']}").status_code == 200
        assert _rows() == []

    def test_the_earnings_read_passes_each_copy(self, db):
        asyncio.run(main._record_node_identities("mysterium", 1, [(NODE_A, 1), (NODE_B, 2)]))
        assert {(r["instance"], r["value"]) for r in _rows()} == {("1", NODE_A), ("2", NODE_B)}


class TestADeletedBox:
    def test_its_ids_are_retired_and_offered_for_the_replacement(self, db):
        asyncio.run(database.record_identities("earnapp", 1, {"1": {"EARNAPP_UUID": UUID_A}}))
        asyncio.run(database.record_identities("proxyrack", 1, {"p5": {"UUID": UUID_B}}, scope="given"))
        asyncio.run(database.delete_worker(1))
        assert _active() == {}
        assert ("earnapp", 1, "1", "EARNAPP_UUID", UUID_A) in _retired()
        assert ("proxyrack", 1, "p5", "UUID", UUID_B) in _retired()
        assert asyncio.run(database.identity_in_use("earnapp", "EARNAPP_UUID", UUID_A)) == []
        offers = _call(OWNER, "GET", "/api/identities/reuse/earnapp?key=EARNAPP_UUID&worker_id=2").json()
        assert len(offers) == 1 and offers[0]["in_use_on"] == []
        assert _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 2)[0] is None

    def test_a_deploy_record_from_before_the_ledger_is_kept(self, db):
        asyncio.run(
            database.save_deployment(
                slug="earnapp", container_id="c1", spec={"env": {"EARNAPP_UUID": UUID_A}}, worker_id=1
            )
        )
        asyncio.run(database.delete_worker(1))
        assert ("earnapp", 1, "1", "EARNAPP_UUID", UUID_A) in _retired()


# The per-worker key _worker enrols each test box with: what its digests are keyed with.
WORKER_KEY = "test-worker-key-" + "k" * 32


def _digest(slug, ids, key=WORKER_KEY):
    """What a worker reports for a container running with ``ids`` (orchestrator._identity_entry)."""
    return catalog.identity_digest(catalog.get_service(slug), ids, key)


def _entries(slug, copies):
    """Heartbeat entries for ``copies``: copy numbers, or {copy: the ids it runs with}."""
    ids = copies if isinstance(copies, dict) else dict.fromkeys(copies)
    out = []
    for n, env in ids.items():
        entry = {"slug": slug, "instance": n, "container_id": f"{slug}{n}" * 4}
        if env:
            entry["identity_digest"] = _digest(slug, env)
        out.append(entry)
    return out


def _worker(name="box-a", running=()):
    """A box whose last heartbeat lists ``running``: (slug, copies) as _entries takes them."""
    containers = [e for slug, copies in running for e in _entries(slug, copies)]
    wid = asyncio.run(database.upsert_worker(f"client-{name}", name=name, containers=json.dumps(containers)))
    asyncio.run(database.set_worker_key(f"client-{name}", WORKER_KEY))
    return wid


class TestOldDeployments:
    def test_a_deployment_from_before_the_ledger_is_listed(self, db):
        wid = _worker()
        asyncio.run(
            database.save_deployment(
                slug="earnapp", container_id="c1", spec={"env": {"EARNAPP_UUID": UUID_A}}, worker_id=wid
            )
        )
        assert _rows() == []
        asyncio.run(main._backfill_identities())
        listed = _call(OWNER, "GET", "/api/identities").json()
        assert [(r["slug"], r["worker_id"], r["status"]) for r in listed] == [("earnapp", wid, "active")]
        asyncio.run(main._backfill_identities())
        assert len(_rows()) == 1

    def test_its_copies_and_proxied_copies_are_listed(self, db):
        hex_uuid = "ab" * 32
        spec = {"env": {"UUID": hex_uuid, "DEVICE_NAME": "box", "API_KEY": "secret-key"}, "instances": 2}
        copy_two = main._instance_spec(spec, 2, catalog.get_service("proxyrack")["docker"])["env"]
        wid = _worker(running=[("proxyrack", {1: None, 2: copy_two})])
        asyncio.run(database.save_deployment(slug="proxyrack", container_id="c1", spec=spec, worker_id=wid))
        asyncio.run(database.save_proxied_copy(7, wid, "proxyrack"))
        p7 = main.proxies.earner_spec(spec, catalog.get_service("proxyrack")["docker"], 7)["env"]
        _proxied_heartbeat(wid, "proxyrack", 7, p7)
        asyncio.run(main._backfill_identities())
        active = _active()
        assert {k[2] for k in active} == {"1", "2", "p7"}
        assert "secret-key" not in active.values()
        assert active[("proxyrack", wid, "1", "UUID")] == hex_uuid
        assert active[("proxyrack", wid, "p7", "UUID")] not in ("", hex_uuid)

    def test_it_never_overrides_what_a_deploy_recorded(self, db):
        wid = _worker()
        asyncio.run(
            database.save_deployment(
                slug="earnapp", container_id="c1", spec={"env": {"EARNAPP_UUID": UUID_A}}, worker_id=wid
            )
        )
        asyncio.run(database.record_identities("earnapp", wid, {"1": {"EARNAPP_UUID": UUID_B}}))
        asyncio.run(main._backfill_identities())
        assert _active() == {("earnapp", wid, "1", "EARNAPP_UUID"): UUID_B}


class TestTheRawCommandRoute:
    def _raw(self, env, worker_id=1):
        async def run():
            with (
                patch.object(main, "_require_owner", lambda r: OWNER),
                patch.object(main, "_proxy_to_worker", AsyncMock(return_value={"container_id": "c"})),
                patch.object(main.database, "record_health_event", AsyncMock()),
                patch.object(main, "_spawn", lambda coro: coro.close()),
                patch.object(main.metrics, "record_container_lifecycle", lambda *a: None),
            ):
                body = main.WorkerCommand(command="deploy", slug="earnapp", spec={"env": env})
                await main.api_worker_command(_request(), worker_id, body)

        asyncio.run(run())

    def test_a_raw_redeploy_with_a_new_id_retires_the_old_one(self, db):
        asyncio.run(database.record_identities("earnapp", 1, {"1": {"EARNAPP_UUID": UUID_A}}))
        self._raw({"EARNAPP_UUID": UUID_B})
        assert _active() == {("earnapp", 1, "1", "EARNAPP_UUID"): UUID_B}
        assert ("earnapp", 1, "1", "EARNAPP_UUID", UUID_A) in _retired()
        assert asyncio.run(database.identity_in_use("earnapp", "EARNAPP_UUID", UUID_A)) == []


ADMIN_KEY = {"uid": 0, "u": "api", "r": "owner"}


class TestTheAdminKeyCannotMintAnOwner:
    def _user(self, role):
        return asyncio.run(database.create_user(f"u-{role}", "x" * 60, role))

    def test_it_cannot_promote_an_account_to_owner(self, db):
        uid = self._user("viewer")
        client = TestClient(main.app)
        with patch.object(auth, "get_current_user", return_value=ADMIN_KEY):
            response = client.patch(f"/api/users/{uid}", json={"role": "owner"})
        assert response.status_code == 403
        assert asyncio.run(database.get_user_by_id(uid))["role"] == "viewer"

    def test_it_may_still_set_a_lower_role(self, db):
        uid = self._user("viewer")
        client = TestClient(main.app)
        with patch.object(auth, "get_current_user", return_value=ADMIN_KEY):
            assert client.patch(f"/api/users/{uid}", json={"role": "writer"}).status_code == 200

    def test_it_cannot_set_an_owners_password(self, db):
        uid = self._user("owner")
        client = TestClient(main.app)
        with patch.object(auth, "get_current_user", return_value=ADMIN_KEY):
            response = client.post(f"/api/users/{uid}/password", json={"new_password": "n" * 12})
        assert response.status_code == 403

    def test_a_signed_in_owner_still_can(self, db):
        self._user("owner")
        uid = self._user("viewer")
        client = TestClient(main.app)
        with patch.object(auth, "get_current_user", return_value=OWNER):
            assert client.patch(f"/api/users/{uid}", json={"role": "owner"}).status_code == 200


# ---------------------------------------------------------------------------
# Review of #753, second round: a key declared twice, two writes at once,
# fleet-wide specs, the copy a raw deploy named, and a deploy that fails halfway
# ---------------------------------------------------------------------------


class TestASecretDeclaredTwice:
    SVC = {
        "slug": "dup",
        "docker": {
            "env": [{"key": "K", "secret": True}, {"key": "K", "identifier": True}, {"key": "N", "identifier": True}]
        },
    }

    def test_it_is_never_an_identity_key(self):
        assert catalog.identity_keys(self.SVC) == {"N": "N"}

    def test_its_value_never_reaches_the_ledger(self, db):
        with patch.object(catalog, "get_service", lambda slug: self.SVC):
            asyncio.run(database.record_identities("dup", 1, {"1": {"K": "the-secret", "N": "box"}}))
        assert _active() == {("dup", 1, "1", "N"): "box"}

    def test_the_loader_refuses_it(self, tmp_path):
        data = {"name": "X", "slug": "x", "docker": {"image": "x/x:1", "env": self.SVC["docker"]["env"]}}
        assert any("key K is secret" in e for e in catalog._validate(data, tmp_path / "x.yml"))


class TestTwoWritesAtOnce:
    def test_two_records_of_one_copy_keep_one_active_row(self, db):
        async def both():
            await asyncio.gather(
                *(
                    database.record_identities("earnapp", 1, {"p5": {"EARNAPP_UUID": UUID_A}}, scope="given")
                    for _ in range(4)
                )
            )

        asyncio.run(both())
        assert [r["status"] for r in _rows()] == ["active"]


def _legacy_deployment(slug, env, container_id="abcdef0123456789"):
    """A deployment from before per-worker specs: only the fleet-wide row, and a box running it."""
    wid = asyncio.run(
        database.upsert_worker(
            "client-old", name="box-old", containers=f'[{{"slug": "{slug}", "container_id": "{container_id[:12]}"}}]'
        )
    )
    asyncio.run(database.save_deployment(slug=slug, container_id=container_id, spec={"env": env}))
    return wid


class TestAFleetWideSpec:
    def test_removing_it_keeps_its_ids(self, db):
        wid = _legacy_deployment("earnapp", {"EARNAPP_UUID": UUID_A})
        asyncio.run(database.remove_deployment("earnapp", worker_id=wid))
        assert ("earnapp", wid, "1", "EARNAPP_UUID", UUID_A) in _retired()

    def test_removing_it_everywhere_keeps_its_ids(self, db):
        wid = _legacy_deployment("earnapp", {"EARNAPP_UUID": UUID_A})
        asyncio.run(database.remove_deployment("earnapp"))
        assert ("earnapp", wid, "1", "EARNAPP_UUID", UUID_A) in _retired()

    def test_another_box_removing_it_does_not_claim_its_ids(self, db):
        wid = _legacy_deployment("earnapp", {"EARNAPP_UUID": UUID_A})
        other = _worker("box-b")
        asyncio.run(database.remove_deployment("earnapp", worker_id=other))
        assert {r["worker_id"] for r in _rows()} <= {wid}

    def test_the_backfill_lists_it(self, db):
        wid = _legacy_deployment("earnapp", {"EARNAPP_UUID": UUID_A})
        asyncio.run(main._backfill_identities())
        assert _active() == {("earnapp", wid, "1", "EARNAPP_UUID"): UUID_A}


class TestTheCopyARawDeployNamed:
    def _raw_copy(self, env, copy, worker_id=1):
        async def run():
            with (
                patch.object(main, "_require_owner", lambda r: OWNER),
                patch.object(main, "_proxy_to_worker", AsyncMock(return_value={"container_id": "c"})),
                patch.object(main.database, "record_health_event", AsyncMock()),
                patch.object(main, "_spawn", lambda coro: coro.close()),
                patch.object(main.metrics, "record_container_lifecycle", lambda *a: None),
            ):
                body = main.WorkerCommand(command="deploy", slug="earnapp", spec={"env": env, "instance": copy})
                await main.api_worker_command(_request(), worker_id, body)

        asyncio.run(run())

    def test_removal_keeps_it_on_that_copy(self, db):
        self._raw_copy({"EARNAPP_UUID": UUID_A}, 2)
        asyncio.run(database.remove_deployment("earnapp", worker_id=1))
        assert {(r["instance"], r["status"]) for r in _rows()} == {("2", "retired")}

    def test_the_backfill_lists_it_on_that_copy(self, db):
        wid = _worker()
        spec = {"env": {"EARNAPP_UUID": UUID_A}, "instance": 2}
        asyncio.run(database.save_deployment(slug="earnapp", container_id="c", spec=spec, worker_id=wid))
        asyncio.run(main._backfill_identities())
        assert _active() == {("earnapp", wid, "2", "EARNAPP_UUID"): UUID_A}


class TestADeployThatFailsHalfway:
    HG = {"HONEYGAIN_EMAIL": "me@example.com", "HONEYGAIN_PASSWORD": "pw"}

    def test_a_copy_that_failed_keeps_the_id_it_still_runs(self, db):
        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            assert _deploy("honeygain", {**self.HG, "HONEYGAIN_DEVICE_NAME": "box"}, 1, instances=2)[0] is None

            def copy_two(method, path, json):
                return path.endswith("/deploy") and (json or {}).get("instance") == 2

            error, _ = _deploy("honeygain", {**self.HG, "HONEYGAIN_DEVICE_NAME": "new"}, 1, instances=2, fail=copy_two)
        assert error is not None
        assert _active() == {
            ("honeygain", 1, "1", "HONEYGAIN_DEVICE_NAME"): "new",
            ("honeygain", 1, "2", "HONEYGAIN_DEVICE_NAME"): "box-2",
        }

    def test_a_copy_whose_removal_failed_stays_active(self, db):
        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            assert _deploy("honeygain", {**self.HG, "HONEYGAIN_DEVICE_NAME": "box"}, 1, instances=2)[0] is None

            def delete(method, path, json):
                return method == "DELETE"

            error, _ = _deploy(
                "honeygain", {**self.HG, "HONEYGAIN_DEVICE_NAME": "box"}, 1, instances=1, fail=delete, running={1, 2}
            )
        assert error is not None
        assert ("honeygain", 1, "2", "HONEYGAIN_DEVICE_NAME") in _active()

    def test_a_copy_removed_is_retired(self, db):
        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            assert _deploy("honeygain", {**self.HG, "HONEYGAIN_DEVICE_NAME": "box"}, 1, instances=2)[0] is None
            error, _ = _deploy("honeygain", {**self.HG, "HONEYGAIN_DEVICE_NAME": "box"}, 1, instances=1, running={1, 2})
        assert error is None
        assert _active() == {("honeygain", 1, "1", "HONEYGAIN_DEVICE_NAME"): "box"}
        assert ("honeygain", 1, "2", "HONEYGAIN_DEVICE_NAME", "box-2") in _retired()


# ---------------------------------------------------------------------------
# Review of #753, third round: a heartbeat that predates a copy, and a copy
# whose ledger write failed at deploy
# ---------------------------------------------------------------------------


class TestAHeartbeatThatPredatesACopy:
    HG = {"HONEYGAIN_EMAIL": "me@example.com", "HONEYGAIN_PASSWORD": "pw", "HONEYGAIN_DEVICE_NAME": "box"}

    def test_a_scale_down_it_cannot_see_retires_nothing(self, db):
        """The heartbeat lists no copy yet, so no DELETE goes out and copy 2 still runs."""
        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            assert _deploy("honeygain", self.HG, 1, instances=2)[0] is None
            error, sent = _deploy("honeygain", self.HG, 1, instances=1, running=set())
        assert error is None
        assert not any(s["path"].endswith("/instances/2") for s in sent)
        assert _active()[("honeygain", 1, "2", "HONEYGAIN_DEVICE_NAME")] == "box-2"


class TestACopyWhoseWriteFailed:
    HG = {"HONEYGAIN_EMAIL": "me@example.com", "HONEYGAIN_PASSWORD": "pw", "HONEYGAIN_DEVICE_NAME": "box"}

    def _deploy_losing_copy_two(self, wid):
        real = database.record_identities

        async def flaky(slug, worker_id, values, **kwargs):
            if "2" in values:
                raise RuntimeError("database is locked")
            return await real(slug, worker_id, values, **kwargs)

        with (
            patch.object(main, "scaling_limit", lambda svc: (3, "")),
            patch.object(main.database, "record_identities", flaky),
        ):
            assert _deploy("honeygain", self.HG, wid, instances=2)[0] is None
        assert set(_active()) == {("honeygain", wid, "1", "HONEYGAIN_DEVICE_NAME")}

    def test_the_backfill_retries_it(self, db):
        wid = _worker(running=[("honeygain", {1: None, 2: {"HONEYGAIN_DEVICE_NAME": "box-2"}})])
        self._deploy_losing_copy_two(wid)
        asyncio.run(main._backfill_identities())
        assert _active() == {
            ("honeygain", wid, "1", "HONEYGAIN_DEVICE_NAME"): "box",
            ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME"): "box-2",
        }

    def test_its_removal_then_keeps_its_id(self, db):
        wid = _worker(running=[("honeygain", {1: None, 2: {"HONEYGAIN_DEVICE_NAME": "box-2"}})])
        self._deploy_losing_copy_two(wid)
        asyncio.run(main._backfill_identities())
        asyncio.run(database.remove_deployment("honeygain", worker_id=wid))
        assert ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME", "box-2") in _retired()

    def test_a_copy_whose_deploy_failed_gets_no_row(self, db):
        """The record says two copies, but copy 2 never ran: the heartbeat lists only copy 1."""
        wid = _worker(running=[("honeygain", [1])])

        def copy_two(method, path, json):
            return path.endswith("/deploy") and (json or {}).get("instance") == 2

        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            error, _ = _deploy("honeygain", self.HG, wid, instances=2, fail=copy_two)
        assert error is not None
        asyncio.run(main._backfill_identities())
        assert _active() == {("honeygain", wid, "1", "HONEYGAIN_DEVICE_NAME"): "box"}


# ---------------------------------------------------------------------------
# Review of #753, fourth round: a copy whose write failed keeps its id through
# to its removal, whether or not a heartbeat or a restart came between
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_checked_copies():
    """Each test starts with no copy marked as checked by an earlier heartbeat."""
    getattr(main, "_IDENTITIES_CHECKED", {}).clear()
    getattr(main, "_IDENTITIES_LISTED", {}).clear()
    yield
    getattr(main, "_IDENTITIES_CHECKED", {}).clear()
    getattr(main, "_IDENTITIES_LISTED", {}).clear()


def _heartbeat(name, copies, *, slug="honeygain", containers=None, listed=None):
    """Send box ``name``'s heartbeat through the real route, listing ``copies`` of ``slug`` (see _entries).

    ``containers``: the raw list instead. ``listed``: the worker's ``containers_listed``.
    """
    containers = _entries(slug, copies) if containers is None else containers
    info = {} if listed is None else {"containers_listed": listed}
    body = main.WorkerHeartbeat(name=name, client_id=f"client-{name}", containers=containers, system_info=info)
    with (
        patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
        patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
    ):
        return asyncio.run(main.api_worker_heartbeat(MagicMock(), body))


def _remove(slug, wid, ran=None):
    """Remove ``slug`` from box ``wid`` through the route.

    ``ran``: {copy: the ids it ran with} for the extra copies the worker removed,
    which it answers with as digests, as worker_api does.
    """
    answer = {"status": "removed", "container": f"cashpilot-{slug}"}
    if ran:
        answer["extra_instances"] = [f"cashpilot-{slug}-{n}" for n in ran]
        answer["identity_digests"] = {str(n): _digest(slug, ids) for n, ids in ran.items()}

    async def run():
        with (
            patch.object(main, "_require_writer", lambda r: OWNER),
            patch.object(main, "_resolve_worker_id", AsyncMock(return_value=wid)),
            patch.object(main, "_proxy_worker_command", AsyncMock(return_value=answer)),
            patch.object(main.database, "record_health_event", AsyncMock()),
            patch.object(main.metrics, "record_container_lifecycle", lambda *a: None),
        ):
            await main._svc_remove(_request(), slug, wid, False)

    asyncio.run(run())


class TestACopyWhoseWriteFailedUntilItsRemoval:
    COPY_2 = ("honeygain", "2", "HONEYGAIN_DEVICE_NAME")

    def _lose_copy_two(self):
        wid = _worker(running=[("honeygain", [1])])
        TestACopyWhoseWriteFailed()._deploy_losing_copy_two(wid)
        return wid

    def test_the_review_sequence(self, db):
        """Copy 2's write fails, a restart comes before any heartbeat lists it, then a heartbeat, then removal."""
        wid = self._lose_copy_two()
        asyncio.run(main._backfill_identities())
        assert (self.COPY_2[0], wid, *self.COPY_2[1:]) not in _active()
        assert (
            _heartbeat("box-a", {1: {"HONEYGAIN_DEVICE_NAME": "box"}, 2: {"HONEYGAIN_DEVICE_NAME": "box-2"}})["status"]
            == "ok"
        )
        assert _active()[(self.COPY_2[0], wid, *self.COPY_2[1:])] == "box-2"
        _remove("honeygain", wid, ran={2: {"HONEYGAIN_DEVICE_NAME": "box-2"}})
        assert _active() == {}
        assert ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME", "box-2") in _retired()

    def test_a_removal_before_any_heartbeat_or_restart(self, db):
        wid = self._lose_copy_two()
        _remove("honeygain", wid, ran={2: {"HONEYGAIN_DEVICE_NAME": "box-2"}})
        assert _active() == {}
        assert _retired() == {
            ("honeygain", wid, "1", "HONEYGAIN_DEVICE_NAME", "box"),
            ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME", "box-2"),
        }

    def test_a_scale_down_of_it(self, db):
        """The confirmed DELETE of copy 2 keeps the id it ran with, though it never had a row."""
        wid = self._lose_copy_two()
        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            error, _ = _deploy(
                "honeygain",
                TestACopyWhoseWriteFailed.HG,
                wid,
                instances=1,
                running={1, 2},
                ran={2: {"HONEYGAIN_DEVICE_NAME": "box-2"}},
            )
        assert error is None
        assert _active() == {("honeygain", wid, "1", "HONEYGAIN_DEVICE_NAME"): "box"}
        assert ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME", "box-2") in _retired()

    def test_a_removal_the_worker_did_not_confirm_for_a_copy_records_nothing_for_it(self, db):
        """Copy 2 never deployed: the worker removed no copy 2, so it gets no row, active or retired."""
        wid = _worker(running=[("honeygain", [1])])

        def copy_two(method, path, json):
            return path.endswith("/deploy") and (json or {}).get("instance") == 2

        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            assert _deploy("honeygain", TestACopyWhoseWriteFailed.HG, wid, instances=2, fail=copy_two)[0] is not None
        _remove("honeygain", wid)
        assert {r["instance"] for r in _rows()} == {"1"}


class TestTheHeartbeatStaysCheap:
    def test_a_steady_heartbeat_reads_the_ledger_once(self, db):
        wid = _worker(running=[("honeygain", [1])])
        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            assert _deploy("honeygain", TestACopyWhoseWriteFailed.HG, wid, instances=2)[0] is None
        real = database.active_identity_values
        reads = AsyncMock(side_effect=real)
        with patch.object(main.database, "active_identity_values", reads):
            for _ in range(3):
                _heartbeat("box-a", {1: {"HONEYGAIN_DEVICE_NAME": "box"}, 2: {"HONEYGAIN_DEVICE_NAME": "box-2"}})
        assert reads.await_count == 1

    def test_an_older_worker_sends_no_proof_so_nothing_is_read_or_written(self, db):
        wid = TestACopyWhoseWriteFailedUntilItsRemoval()._lose_copy_two()
        reads = AsyncMock(side_effect=database.active_identity_values)
        with patch.object(main.database, "active_identity_values", reads):
            _heartbeat("box-a", [1, 2])
        reads.assert_not_awaited()
        assert set(_active()) == {("honeygain", wid, "1", "HONEYGAIN_DEVICE_NAME")}

    def test_a_copy_above_the_count_needs_a_matching_digest(self, db):
        """Copy 3, above the record's two: written for the ids it really runs, never for others."""
        wid = _worker(running=[("honeygain", [1])])
        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            assert _deploy("honeygain", TestACopyWhoseWriteFailed.HG, wid, instances=2)[0] is None
        runs = {1: {"HONEYGAIN_DEVICE_NAME": "box"}, 2: {"HONEYGAIN_DEVICE_NAME": "box-2"}}
        _heartbeat("box-a", {**runs, 3: {"HONEYGAIN_DEVICE_NAME": "someone-else"}})
        assert {k[2] for k in _active()} == {"1", "2"}
        _heartbeat("box-a", {**runs, 3: {"HONEYGAIN_DEVICE_NAME": "box-3"}})
        assert _active()[("honeygain", wid, "3", "HONEYGAIN_DEVICE_NAME")] == "box-3"


# ---------------------------------------------------------------------------
# Review of #753, fifth round: a copy number is no proof of the ids a copy runs
# with; the worker's digest of its real env is
# ---------------------------------------------------------------------------


class TestAReplacementThatFailed:
    """Copy 2 runs box-2 with no row; a redeploy saves "new" but fails to replace copy 2.

    The record now says new-2 for copy 2, an id it never ran. The spec it replaced
    (prior_spec_encrypted) still derives box-2, which the worker's digest proves.
    """

    HG = TestACopyWhoseWriteFailed.HG
    RUNS = {1: {"HONEYGAIN_DEVICE_NAME": "new"}, 2: {"HONEYGAIN_DEVICE_NAME": "box-2"}}

    def _replace_and_fail(self):
        wid = TestACopyWhoseWriteFailedUntilItsRemoval()._lose_copy_two()

        def copy_two(method, path, json):
            return path.endswith("/deploy") and (json or {}).get("instance") == 2

        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            error, _ = _deploy(
                "honeygain", {**self.HG, "HONEYGAIN_DEVICE_NAME": "new"}, wid, instances=2, fail=copy_two
            )
        assert error is not None
        return wid

    def _never_new_2(self):
        assert all(r["value"] != "new-2" for r in _rows())

    def _box_2_runs(self, wid):
        self._never_new_2()
        assert _active() == {
            ("honeygain", wid, "1", "HONEYGAIN_DEVICE_NAME"): "new",
            ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME"): "box-2",
        }

    def test_the_heartbeat_records_the_id_copy_2_still_runs(self, db):
        wid = self._replace_and_fail()
        _heartbeat("box-a", self.RUNS)
        self._box_2_runs(wid)

    def test_the_backfill_records_the_id_copy_2_still_runs(self, db):
        wid = self._replace_and_fail()
        asyncio.run(
            database.upsert_worker(
                "client-box-a", name="box-a", containers=json.dumps(_entries("honeygain", self.RUNS))
            )
        )
        asyncio.run(main._backfill_identities())
        self._box_2_runs(wid)

    def test_its_removal_keeps_box_2(self, db):
        wid = self._replace_and_fail()
        _remove("honeygain", wid, ran={2: self.RUNS[2]})
        self._never_new_2()
        assert _active() == {}
        assert ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME", "box-2") in _retired()

    def test_a_digest_neither_spec_derives_records_nothing(self, db):
        wid = self._replace_and_fail()
        _remove("honeygain", wid, ran={2: {"HONEYGAIN_DEVICE_NAME": "elsewhere-2"}})
        assert {r["instance"] for r in _rows()} == {"1"}
        assert asyncio.run(database.prior_deployment_spec("honeygain", wid)) is None

    def test_a_full_redeploy_forgets_the_prior_spec(self, db):
        wid = self._replace_and_fail()
        assert asyncio.run(database.prior_deployment_spec("honeygain", wid))["env"]["HONEYGAIN_DEVICE_NAME"] == "box"
        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            assert _deploy("honeygain", {**self.HG, "HONEYGAIN_DEVICE_NAME": "new"}, wid, instances=2)[0] is None
        assert asyncio.run(database.prior_deployment_spec("honeygain", wid)) is None

    def test_a_retry_of_the_same_spec_keeps_the_prior_one(self, db):
        wid = self._replace_and_fail()
        self._replace_and_fail_again(wid)
        assert asyncio.run(database.prior_deployment_spec("honeygain", wid))["env"]["HONEYGAIN_DEVICE_NAME"] == "box"

    def test_only_one_prior_spec_is_kept(self, db):
        wid = self._replace_and_fail()
        self._replace_and_fail_again(wid, name="third")
        assert asyncio.run(database.prior_deployment_spec("honeygain", wid))["env"]["HONEYGAIN_DEVICE_NAME"] == "new"

    def _replace_and_fail_again(self, wid, name="new"):
        def copy_two(method, path, json):
            return path.endswith("/deploy") and (json or {}).get("instance") == 2

        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            error, _ = _deploy("honeygain", {**self.HG, "HONEYGAIN_DEVICE_NAME": name}, wid, instances=2, fail=copy_two)
        assert error is not None

    def test_a_matching_digest_is_still_recorded(self, db):
        """The positive control: the same heartbeat, with copy 2 really running new-2, writes it."""
        wid = self._replace_and_fail()
        _heartbeat("box-a", {**self.RUNS, 2: {"HONEYGAIN_DEVICE_NAME": "new-2"}})
        assert _active()[("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME")] == "new-2"


class TestTheWorkersDigest:
    """orchestrator._identity_entry: what the heartbeat carries about a copy's ids."""

    @pytest.fixture(autouse=True)
    def _keyed(self):
        from app import orchestrator

        orchestrator._identity_values.clear()
        with patch.object(orchestrator, "identity_digest_key", lambda: WORKER_KEY):
            yield
        orchestrator._identity_values.clear()

    def _container(self, env, cid="abc123"):
        container = MagicMock()
        container.id = cid
        container.client.api.inspect_container.return_value = {"Config": {"Env": env}}
        return container

    def test_it_matches_the_digest_the_ui_derives(self, db):
        from app import orchestrator

        container = self._container(
            ["HONEYGAIN_EMAIL=me@example.com", "HONEYGAIN_PASSWORD=pw", "HONEYGAIN_DEVICE_NAME=box-2"]
        )
        entry = orchestrator._identity_entry(container, "honeygain")
        assert entry == {"identity_digest": _digest("honeygain", {"HONEYGAIN_DEVICE_NAME": "box-2"})}

    def test_it_never_carries_an_id_or_a_secret(self, db):
        from app import orchestrator

        container = self._container([f"EARNAPP_UUID={UUID_A}"])
        entry = orchestrator._identity_entry(container, "earnapp")
        assert UUID_A not in json.dumps(entry) and len(entry["identity_digest"]) == 16
        container = self._container(["HONEYGAIN_PASSWORD=hunter2", "HONEYGAIN_DEVICE_NAME=box"], cid="def456")
        assert "hunter2" not in json.dumps(orchestrator._identity_entry(container, "honeygain"))

    def test_a_container_is_inspected_once(self, db):
        from app import orchestrator

        container = self._container([f"EARNAPP_UUID={UUID_A}"])
        for _ in range(3):
            orchestrator._identity_entry(container, "earnapp")
        assert container.client.api.inspect_container.call_count == 1

    def test_a_service_with_no_device_ids_is_never_inspected(self, db):
        from app import orchestrator

        container = self._container(["X=1"], cid="ghi789")
        assert orchestrator._identity_entry(container, "not-a-service") == {}
        container.client.api.inspect_container.assert_not_called()

    def test_without_a_key_the_worker_sends_no_digest(self, db):
        from app import orchestrator

        container = self._container([f"EARNAPP_UUID={UUID_A}"], cid="nokey1")
        with patch.object(orchestrator, "identity_digest_key", lambda: None):
            assert orchestrator._identity_entry(container, "earnapp") == {}


# ---------------------------------------------------------------------------
# Review of #753, sixth round: the digest is keyed, so whoever reads a
# heartbeat cannot test a guessed device name against it
# ---------------------------------------------------------------------------


class TestTheDigestIsKeyed:
    IDS = {"HONEYGAIN_DEVICE_NAME": "box-2"}

    def test_it_changes_with_the_key(self):
        assert _digest("honeygain", self.IDS, "key-one") != _digest("honeygain", self.IDS, "key-two")

    def test_without_the_key_it_is_not_a_plain_hash_of_the_values(self):
        import hashlib

        digest = _digest("honeygain", self.IDS)
        pairs = json.dumps([["HONEYGAIN_DEVICE_NAME", "box-2"]])
        plain = {
            hashlib.sha256(pairs.encode()).hexdigest()[:16],
            hashlib.sha256(json.dumps(["cashpilot-identity", json.loads(pairs)]).encode()).hexdigest()[:16],
            hashlib.sha256(b"box-2").hexdigest()[:16],
        }
        assert digest not in plain

    def test_no_key_no_digest(self):
        assert _digest("honeygain", self.IDS, "") is None
        assert _digest("honeygain", self.IDS, None) is None

    def test_a_digest_under_a_key_the_ui_does_not_hold_proves_nothing(self, db):
        wid = TestACopyWhoseWriteFailedUntilItsRemoval()._lose_copy_two()
        forged = _entries("honeygain", [1, 2])
        forged[1]["identity_digest"] = _digest("honeygain", self.IDS, "someone-elses-key")
        body = main.WorkerHeartbeat(name="box-a", client_id="client-box-a", containers=forged)
        with (
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
        ):
            asyncio.run(main.api_worker_heartbeat(MagicMock(), body))
        assert set(_active()) == {("honeygain", wid, "1", "HONEYGAIN_DEVICE_NAME")}

    def test_a_worker_not_yet_enrolled_keys_it_with_the_fleet_key(self, db):
        wid = TestACopyWhoseWriteFailedUntilItsRemoval()._lose_copy_two()
        asyncio.run(database.set_worker_key("client-box-a", ""))
        entries = _entries("honeygain", [1])
        entries.append(
            {**_entries("honeygain", [2])[0], "identity_digest": _digest("honeygain", self.IDS, "fleet-key")}
        )
        body = main.WorkerHeartbeat(name="box-a", client_id="client-box-a", containers=entries)
        with (
            patch.object(main, "FLEET_API_KEY", "fleet-key"),
            patch.object(main, "_authenticate_worker_heartbeat", AsyncMock(return_value="ok")),
            patch.object(main, "_earnings_for_worker", AsyncMock(return_value=None)),
        ):
            asyncio.run(main.api_worker_heartbeat(MagicMock(), body))
        assert _active()[("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME")] == "box-2"


# ---------------------------------------------------------------------------
# Review of #753, seventh round: a copy above the saved count, and a heartbeat
# that comes before the deploy record
# ---------------------------------------------------------------------------


class TestACopyAboveTheSavedCount:
    BOX_2 = {2: {"HONEYGAIN_DEVICE_NAME": "box-2"}}

    def test_a_scale_down_a_stale_heartbeat_hid_keeps_its_copy(self, db):
        """Copy 2's write fails; a scale-down to one copy named "new" cannot see it, so copy 2 keeps box-2."""
        wid = TestACopyWhoseWriteFailedUntilItsRemoval()._lose_copy_two()
        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            error, sent = _deploy(
                "honeygain",
                {**TestACopyWhoseWriteFailed.HG, "HONEYGAIN_DEVICE_NAME": "new"},
                wid,
                instances=1,
                running=set(),
            )
        assert error is None and not any("/instances/" in s["path"] for s in sent)
        assert asyncio.run(database.get_deployment_spec("honeygain", worker_id=wid)).get("instances") is None
        # The record now derives new-2 for copy 2; only the spec it replaced proves box-2.
        assert asyncio.run(database.prior_deployment_spec("honeygain", wid)) is not None
        _heartbeat("box-a", {1: {"HONEYGAIN_DEVICE_NAME": "new"}, **self.BOX_2})
        assert _active()[("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME")] == "box-2"
        _remove("honeygain", wid, ran=self.BOX_2)
        assert _active() == {}
        assert ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME", "box-2") in _retired()

    def test_a_confirmed_delete_lets_the_prior_spec_go(self, db):
        wid = TestACopyWhoseWriteFailedUntilItsRemoval()._lose_copy_two()
        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            assert (
                _deploy(
                    "honeygain",
                    {**TestACopyWhoseWriteFailed.HG, "HONEYGAIN_DEVICE_NAME": "new"},
                    wid,
                    instances=1,
                    running={1, 2},
                    ran=self.BOX_2,
                )[0]
                is None
            )
        assert asyncio.run(database.prior_deployment_spec("honeygain", wid)) is None
        assert ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME", "box-2") in _retired()

    def test_a_removal_before_any_heartbeat(self, db):
        wid = TestACopyWhoseWriteFailedUntilItsRemoval()._lose_copy_two()
        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            assert _deploy("honeygain", TestACopyWhoseWriteFailed.HG, wid, instances=1, running=set())[0] is None
        _remove("honeygain", wid, ran=self.BOX_2)
        assert ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME", "box-2") in _retired()


class TestAHeartbeatBeforeTheRecord:
    def test_the_copy_is_checked_again_once_the_record_exists(self, db):
        wid = _worker()
        ids = {1: {"EARNAPP_UUID": UUID_A}}
        _heartbeat("box-a", ids, slug="earnapp")
        assert _rows() == []
        asyncio.run(
            database.save_deployment(
                slug="earnapp", container_id="c1", spec={"env": {"EARNAPP_UUID": UUID_A}}, worker_id=wid
            )
        )
        # As every deploy route does right after its save.
        main._forget_checked_copies(wid, "earnapp")
        _heartbeat("box-a", ids, slug="earnapp")
        assert _active() == {("earnapp", wid, "1", "EARNAPP_UUID"): UUID_A}


# ---------------------------------------------------------------------------
# Review of #753, eighth round: a redeploy replaces a copy whose ids never
# reached the ledger; the replaced container's ids are kept, as on a removal
# ---------------------------------------------------------------------------


class TestAReplacementOfAnUnrecordedCopy:
    def test_copy_2_box_2_is_retired_and_new_2_is_active(self, db):
        """Copy 2's write fails, no heartbeat, then a redeploy to "new" succeeds."""
        wid = TestACopyWhoseWriteFailedUntilItsRemoval()._lose_copy_two()
        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            error, _ = _deploy(
                "honeygain",
                {**TestACopyWhoseWriteFailed.HG, "HONEYGAIN_DEVICE_NAME": "new"},
                wid,
                instances=2,
                replaced={1: {"HONEYGAIN_DEVICE_NAME": "box"}, 2: {"HONEYGAIN_DEVICE_NAME": "box-2"}},
            )
        assert error is None
        assert _active() == {
            ("honeygain", wid, "1", "HONEYGAIN_DEVICE_NAME"): "new",
            ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME"): "new-2",
        }
        assert {
            ("honeygain", wid, "1", "HONEYGAIN_DEVICE_NAME", "box"),
            ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME", "box-2"),
        } <= _retired()

    def test_the_first_copy_of_a_one_copy_service(self, db):
        """EarnApp ran UUID_A, whose write failed; a redeploy to UUID_B keeps UUID_A as retired."""
        wid = _worker()
        real = database.record_identities

        async def failing(*args, **kwargs):
            raise RuntimeError("database is locked")

        with patch.object(main.database, "record_identities", failing):
            assert _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, wid)[0] is None
        assert _rows() == []
        with patch.object(main.database, "record_identities", real):
            assert _deploy("earnapp", {"EARNAPP_UUID": UUID_B}, wid, replaced={1: {"EARNAPP_UUID": UUID_A}})[0] is None
        assert _active() == {("earnapp", wid, "1", "EARNAPP_UUID"): UUID_B}
        assert ("earnapp", wid, "1", "EARNAPP_UUID", UUID_A) in _retired()

    def test_a_digest_the_old_record_does_not_derive_writes_nothing(self, db):
        wid = _worker()

        async def failing(*args, **kwargs):
            raise RuntimeError("database is locked")

        with patch.object(main.database, "record_identities", failing):
            assert _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, wid)[0] is None
        assert _deploy("earnapp", {"EARNAPP_UUID": UUID_B}, wid, replaced={1: {"EARNAPP_UUID": "elsewhere"}})[0] is None
        assert {r["value"] for r in _rows()} == {UUID_B}


class TestTheWorkerReportsTheReplacedIds:
    """worker_api's deploy answer carries the digest of the container it replaced."""

    def _post(self, old):
        from fastapi.testclient import TestClient

        from app import orchestrator, worker_api

        client = MagicMock()
        client.containers.get.return_value = old
        created = MagicMock()
        created.id = created.short_id = "new"
        client.containers.run.return_value = created
        with (
            patch.object(orchestrator, "_CONTAINER_RUNTIME", ""),
            patch.object(orchestrator, "_CONTAINER_NETWORK", ""),
            patch.object(orchestrator, "available_runtimes", return_value={"runc"}),
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "identity_digest_key", lambda: WORKER_KEY),
            patch.object(worker_api, "_verify_api_key"),
            patch.object(worker_api, "_validate_deploy_spec"),
        ):
            orchestrator._identity_values.clear()
            return TestClient(worker_api.app).post(
                "/api/containers/honeygain/deploy",
                json={"image": "honeygain/honeygain", "env": {"HONEYGAIN_DEVICE_NAME": "new"}},
            )

    def test_the_answer_names_the_old_containers_ids_as_a_digest(self, db):
        from app import constants

        old = MagicMock()
        old.id = "old-container"
        old.labels = {constants.LABEL_SERVICE: "honeygain", constants.LABEL_MANAGED: "true"}
        old.client.api.inspect_container.return_value = {"Config": {"Env": ["HONEYGAIN_DEVICE_NAME=box"]}}
        resp = self._post(old)
        assert resp.status_code == 200, resp.text
        assert resp.json()["replaced_identity_digest"] == _digest("honeygain", {"HONEYGAIN_DEVICE_NAME": "box"})
        assert "box" not in resp.text.replace(resp.json()["replaced_identity_digest"], "")


class TestANewRecordIsCheckedAgain:
    def test_a_heartbeat_checked_against_the_old_record_is_checked_against_the_new_one(self, db):
        """Copy 1 runs UUID_B, which the old record (UUID_A) did not derive; a new record does."""
        wid = _worker()

        async def failing(*args, **kwargs):
            raise RuntimeError("database is locked")

        with patch.object(main.database, "record_identities", failing):
            assert _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, wid)[0] is None
        runs_b = {1: {"EARNAPP_UUID": UUID_B}}
        _heartbeat("box-a", runs_b, slug="earnapp")
        assert _rows() == []
        with patch.object(main.database, "record_identities", failing):
            assert _deploy("earnapp", {"EARNAPP_UUID": UUID_B}, wid)[0] is None
        _heartbeat("box-a", runs_b, slug="earnapp")
        assert _active() == {("earnapp", wid, "1", "EARNAPP_UUID"): UUID_B}


# ---------------------------------------------------------------------------
# Review of #753, ninth round: a stale active row, and a rename-pending copy
# ---------------------------------------------------------------------------


def _deploy_losing_the_write(slug, env, wid):
    async def failing(*args, **kwargs):
        raise RuntimeError("database is locked")

    with patch.object(main.database, "record_identities", failing):
        assert _deploy(slug, env, wid)[0] is None


class TestAStaleActiveRow:
    """EarnApp copy 1 has an active row UUID_A; a replacement to UUID_B ran but its write failed."""

    def _stale(self):
        wid = _worker()
        assert _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, wid)[0] is None
        _deploy_losing_the_write("earnapp", {"EARNAPP_UUID": UUID_B}, wid)
        assert _active() == {("earnapp", wid, "1", "EARNAPP_UUID"): UUID_A}
        return wid

    def test_a_heartbeat_the_record_proves_repairs_it(self, db):
        wid = self._stale()
        _heartbeat("box-a", {1: {"EARNAPP_UUID": UUID_B}}, slug="earnapp")
        assert _active() == {("earnapp", wid, "1", "EARNAPP_UUID"): UUID_B}
        assert ("earnapp", wid, "1", "EARNAPP_UUID", UUID_A) in _retired()

    def test_an_unproven_digest_leaves_it_and_is_not_read_again(self, db):
        """Nothing that could prove it changes until a new record, which checks it again."""
        wid = self._stale()
        reads = AsyncMock(side_effect=database.active_identity_values)
        with patch.object(main.database, "active_identity_values", reads):
            for _ in range(2):
                _heartbeat("box-a", {1: {"EARNAPP_UUID": "0123456789abcdef"}}, slug="earnapp")
        assert _active() == {("earnapp", wid, "1", "EARNAPP_UUID"): UUID_A}
        assert reads.await_count == 1

    def test_only_the_current_record_proves_the_repair(self, db):
        wid = self._stale()
        # A deploy to UUID_C saved its record and stopped before its write and its
        # prior clear: the prior record (UUID_B) would prove this digest, the current
        # one (UUID_C) does not.
        spec = asyncio.run(database.get_deployment_spec("earnapp", worker_id=wid))
        newer = {**spec, "env": {"EARNAPP_UUID": UUID_C}}
        asyncio.run(database.save_deployment(slug="earnapp", container_id="c3", spec=newer, worker_id=wid))
        assert asyncio.run(database.prior_deployment_spec("earnapp", wid))["env"] == {"EARNAPP_UUID": UUID_B}
        _heartbeat("box-a", {1: {"EARNAPP_UUID": UUID_B}}, slug="earnapp")
        assert _active() == {("earnapp", wid, "1", "EARNAPP_UUID"): UUID_A}

    def test_a_matching_row_is_left_alone_and_cached(self, db):
        wid = _worker()
        assert _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, wid)[0] is None
        reads = AsyncMock(side_effect=database.active_identity_values)
        with patch.object(main.database, "active_identity_values", reads):
            for _ in range(2):
                _heartbeat("box-a", {1: {"EARNAPP_UUID": UUID_A}}, slug="earnapp")
        assert reads.await_count == 1
        assert _active() == {("earnapp", wid, "1", "EARNAPP_UUID"): UUID_A}


class TestARenamePendingProxiedCopy:
    def test_the_backfill_does_not_give_it_the_renamed_ids(self, db):
        wid = _worker()
        spec = {"env": {"UUID": "ab" * 32, "DEVICE_NAME": "renamed", "API_KEY": "secret-key"}}
        asyncio.run(database.save_deployment(slug="proxyrack", container_id="c1", spec=spec, worker_id=wid))
        asyncio.run(database.save_proxied_copy(7, wid, "proxyrack"))
        asyncio.run(database.set_proxied_copy_rename_pending(7, wid, "proxyrack", True))
        asyncio.run(main._backfill_identities())
        assert {k[2] for k in _active()} == {"1"}


# ---------------------------------------------------------------------------
# Review of #753, tenth round: the raw deploy route, a late heartbeat after a
# scale-down, and a digest that can never match
# ---------------------------------------------------------------------------


def _raw_deploy(env, worker_id, *, allow=False, answer=None):
    """Deploy earnapp through POST /api/workers/{id}/command; returns (error, the worker hop)."""
    hop = AsyncMock(return_value={"container_id": "c", **(answer or {})})

    async def run():
        with (
            patch.object(main, "_require_owner", lambda r: OWNER),
            patch.object(main, "_proxy_to_worker", hop),
            patch.object(main.database, "record_health_event", AsyncMock()),
            patch.object(main, "_spawn", lambda coro: coro.close()),
            patch.object(main.metrics, "record_container_lifecycle", lambda *a: None),
        ):
            body = main.WorkerCommand(command="deploy", slug="earnapp", spec={"env": env}, allow_shared_identity=allow)
            try:
                await main.api_worker_command(_request(), worker_id, body)
            except HTTPException as exc:
                return exc
            return None

    return asyncio.run(run()), hop


class TestTheRawDeployChecksSharedIds:
    def test_it_refuses_an_id_another_box_runs(self, db):
        asyncio.run(database.record_identities("earnapp", 1, {"1": {"EARNAPP_UUID": UUID_A}}))
        error, hop = _raw_deploy({"EARNAPP_UUID": UUID_A}, 2)
        assert isinstance(error, HTTPException) and error.status_code == 409
        assert error.detail["error"] == "identity_in_use" and UUID_A not in str(error.detail)
        hop.assert_not_awaited()
        assert asyncio.run(database.identity_in_use("earnapp", "EARNAPP_UUID", UUID_A)) == [1]

    def test_the_owner_may_confirm_it(self, db):
        asyncio.run(database.record_identities("earnapp", 1, {"1": {"EARNAPP_UUID": UUID_A}}))
        error, hop = _raw_deploy({"EARNAPP_UUID": UUID_A}, 2, allow=True)
        assert error is None
        hop.assert_awaited_once()

    def test_the_same_box_is_not_a_second_one(self, db):
        asyncio.run(database.record_identities("earnapp", 1, {"1": {"EARNAPP_UUID": UUID_A}}))
        assert _raw_deploy({"EARNAPP_UUID": UUID_A}, 1)[0] is None


class TestALateHeartbeatAfterAScaleDown:
    """A heartbeat built before copy 3's DELETE arrives after it."""

    def test_the_removed_copy_does_not_stay_active(self, db):
        wid = _worker(running=[("honeygain", [1])])
        hg = TestACopyWhoseWriteFailed.HG
        runs = {n: {"HONEYGAIN_DEVICE_NAME": "box" if n == 1 else f"box-{n}"} for n in (1, 2, 3)}
        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            assert _deploy("honeygain", hg, wid, instances=3)[0] is None
            _heartbeat("box-a", runs)
            assert _deploy("honeygain", hg, wid, instances=2, running={1, 2, 3}, ran={3: runs[3]})[0] is None
        copy_three = ("honeygain", wid, "3", "HONEYGAIN_DEVICE_NAME")
        assert copy_three not in _active()
        _heartbeat("box-a", runs)  # the late one
        _heartbeat("box-a", {1: runs[1], 2: runs[2]})
        _heartbeat("box-a", {1: runs[1], 2: runs[2]})
        assert copy_three not in _active()
        assert ("honeygain", wid, "3", "HONEYGAIN_DEVICE_NAME", "box-3") in _retired()
        assert set(_active()) == {
            ("honeygain", wid, "1", "HONEYGAIN_DEVICE_NAME"),
            ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME"),
        }

    def test_a_copy_within_the_count_that_drops_out_keeps_its_row(self, db):
        """Copy 2 missing from one heartbeat (being replaced, or its inspect failed) is no removal."""
        wid = _worker(running=[("honeygain", [1])])
        runs = {1: {"HONEYGAIN_DEVICE_NAME": "box"}, 2: {"HONEYGAIN_DEVICE_NAME": "box-2"}}
        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            assert _deploy("honeygain", TestACopyWhoseWriteFailed.HG, wid, instances=2)[0] is None
        _heartbeat("box-a", runs)
        _heartbeat("box-a", {1: runs[1]})
        assert ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME") in _active()

    def test_a_copy_above_the_count_that_comes_back_is_proven_again(self, db):
        """Retired when a heartbeat stops listing it; a later one that lists it again restores it."""
        wid = _worker(running=[("honeygain", [1])])
        hg = TestACopyWhoseWriteFailed.HG
        runs = {n: {"HONEYGAIN_DEVICE_NAME": "box" if n == 1 else f"box-{n}"} for n in (1, 2)}
        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            assert _deploy("honeygain", hg, wid, instances=2)[0] is None
            # A scale-down a stale heartbeat hid: copy 2 keeps running above the count.
            assert _deploy("honeygain", hg, wid, instances=1, running=set())[0] is None
        _heartbeat("box-a", runs)
        _heartbeat("box-a", {1: runs[1]})
        assert ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME") not in _active()
        _heartbeat("box-a", runs)
        assert _active()[("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME")] == "box-2"


class TestADigestThatNeverMatches:
    """The UI and the worker disagree on a service's identity keys (different releases)."""

    def test_the_heartbeat_reads_it_once_until_the_record_changes(self, db):
        wid = _worker()
        assert _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, wid)[0] is None
        reads = AsyncMock(side_effect=database.active_identity_values)
        with patch.object(main.database, "active_identity_values", reads):
            for _ in range(3):
                _heartbeat("box-a", {1: {"EARNAPP_UUID": "0123456789abcdef"}}, slug="earnapp")
            assert reads.await_count == 1
            # A new record is checked again.
            assert _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, wid)[0] is None
            _heartbeat("box-a", {1: {"EARNAPP_UUID": "0123456789abcdef"}}, slug="earnapp")
            assert reads.await_count == 2
        assert _active() == {("earnapp", wid, "1", "EARNAPP_UUID"): UUID_A}


# ---------------------------------------------------------------------------
# Review of #753, eleventh round: the admin key and a custom image, two deploys
# of one id at once, proxied copies at startup, a restart after a scale-down,
# and the import page's deploy
# ---------------------------------------------------------------------------


class TestTheAdminKeyCannotCarryADeviceIdOut:
    """A recorded per_device id must not ride an image the caller chose without the owner's password."""

    def test_the_admin_key_cannot_send_the_recorded_id_to_another_image(self, db):
        assert _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 1)[0] is None
        error, sent = _deploy("earnapp", {}, 1, user=ADMIN_KEY, image="attacker/exfil:1")
        assert isinstance(error, HTTPException) and error.status_code == 403
        assert not any(UUID_A in str(s["json"]) for s in sent)

    def test_a_signed_in_owner_is_asked_for_the_password(self, db):
        assert _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 1)[0] is None
        error, sent = _deploy("earnapp", {}, 1, image="mirror/earnapp:1")
        assert error.status_code == 403 and error.detail["error"] == "step_up_required"
        assert sent == []
        with patch.object(main, "require_step_up", AsyncMock(return_value=OWNER)) as step_up_:
            error, sent = _deploy("earnapp", {}, 1, image="mirror/earnapp:1", password="pw")
        assert error is None and sent[0]["json"]["image"] == "mirror/earnapp:1"
        step_up_.assert_awaited_once()
        assert "approval" not in sent[0]["json"]

    def test_a_redeploy_that_keeps_the_owners_image_is_not_asked_again(self, db):
        assert _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 1)[0] is None
        with patch.object(main, "require_step_up", AsyncMock(return_value=OWNER)):
            assert _deploy("earnapp", {}, 1, image="mirror/earnapp:1", password="pw")[0] is None
        error, sent = _deploy("earnapp", {}, 1, user=ADMIN_KEY)
        assert error is None and sent[0]["json"]["image"] == "mirror/earnapp:1"

    def test_a_service_with_no_device_id_is_not_asked(self, db):
        env = {"HONEYGAIN_EMAIL": "me@example.com", "HONEYGAIN_PASSWORD": "pw", "HONEYGAIN_DEVICE_NAME": "box"}
        assert _deploy("honeygain", env, 1, user=ADMIN_KEY, image="mirror/honeygain:1")[0] is None


class TestTwoDeploysOfOneIdAtOnce:
    def test_only_one_box_gets_it_without_asking(self, db):
        async def hop(wid, method, path, *, json=None, **kwargs):
            await asyncio.sleep(0.05)  # an image pull
            return {"container_id": f"c{wid}"}

        async def one(wid):
            body = main.DeployRequest(env={"EARNAPP_UUID": UUID_A})
            try:
                await main.api_deploy(_request(), "earnapp", body, wid)
            except HTTPException as exc:
                return exc.status_code
            return 200

        async def run():
            with (
                patch.object(auth, "get_current_user", return_value=OWNER),
                patch.object(main, "_resolve_worker_id", AsyncMock(side_effect=lambda wid: wid)),
                patch.object(main, "_proxy_to_worker", hop),
                patch.object(main, "_register_device", AsyncMock(return_value=True)),
                patch.object(main.database, "record_health_event", AsyncMock()),
                patch.object(main, "_spawn", lambda coro: coro.close()),
                patch.object(main.metrics, "record_container_lifecycle", lambda *a: None),
            ):
                return await asyncio.gather(one(1), one(2))

        assert sorted(asyncio.run(run())) == [200, 409]
        assert len(_active()) == 1
        assert not main._DEVICE_ID_CLAIMS

    def test_two_different_ids_do_not_wait_for_each_other(self, db):
        """The claim is per id: deploys of different ids to two boxes still run side by side."""
        started: list[int] = []
        both = asyncio.Event()

        async def hop(wid, method, path, *, json=None, **kwargs):
            started.append(wid)
            if len(started) == 2:
                both.set()
            await asyncio.wait_for(both.wait(), 1)
            return {"container_id": f"c{wid}"}

        async def one(wid, uuid):
            await main.api_deploy(_request(), "earnapp", main.DeployRequest(env={"EARNAPP_UUID": uuid}), wid)

        async def run():
            with (
                patch.object(auth, "get_current_user", return_value=OWNER),
                patch.object(main, "_resolve_worker_id", AsyncMock(side_effect=lambda wid: wid)),
                patch.object(main, "_proxy_to_worker", hop),
                patch.object(main, "_register_device", AsyncMock(return_value=True)),
                patch.object(main.database, "record_health_event", AsyncMock()),
                patch.object(main, "_spawn", lambda coro: coro.close()),
                patch.object(main.metrics, "record_container_lifecycle", lambda *a: None),
            ):
                await asyncio.gather(one(1, UUID_A), one(2, UUID_B))

        asyncio.run(run())
        assert len(_active()) == 2

    def test_two_raw_deploys_at_once_too(self, db):
        async def hop(*args, **kwargs):
            await asyncio.sleep(0.05)
            return {"container_id": "c"}

        async def one(wid):
            body = main.WorkerCommand(command="deploy", slug="earnapp", spec={"env": {"EARNAPP_UUID": UUID_A}})
            try:
                await main.api_worker_command(_request(), wid, body)
            except HTTPException as exc:
                return exc.status_code
            return 200

        async def run():
            with (
                patch.object(main, "_require_owner", lambda r: OWNER),
                patch.object(main, "_proxy_to_worker", hop),
                patch.object(main.database, "record_health_event", AsyncMock()),
                patch.object(main, "_spawn", lambda coro: coro.close()),
                patch.object(main.metrics, "record_container_lifecycle", lambda *a: None),
            ):
                return await asyncio.gather(one(1), one(2))

        assert sorted(asyncio.run(run())) == [200, 409]


def _proxied_heartbeat(wid, slug, proxy_id, ids):
    """Store a heartbeat whose proxied copy ``proxy_id`` runs with ``ids`` (proxy_tunnel.status)."""
    entry = {"slug": slug, "proxy_id": proxy_id, "status": "running"}
    if ids:
        entry["identity_digest"] = _digest(slug, ids)
    worker = asyncio.run(database.get_worker(wid))
    asyncio.run(
        database.upsert_worker(
            worker["client_id"],
            name=worker["name"],
            containers=worker["containers"],
            system_info=json.dumps({"proxied": [entry]}),
        )
    )


class TestAProxiedCopyAtStartup:
    """The backfill records a proxied copy only when its box proves the ids it runs."""

    def _setup(self, name):
        wid = _worker()
        spec = {"env": {"HONEYGAIN_EMAIL": "me@example.com", "HONEYGAIN_PASSWORD": "pw", "HONEYGAIN_DEVICE_NAME": name}}
        asyncio.run(database.save_deployment(slug="honeygain", container_id="c1", spec=spec, worker_id=wid))
        asyncio.run(database.save_proxied_copy(7, wid, "honeygain"))
        return wid

    def test_a_copy_built_from_an_older_record_is_not_given_the_new_name(self, db):
        wid = self._setup("boxB")
        _proxied_heartbeat(wid, "honeygain", 7, {"HONEYGAIN_DEVICE_NAME": "boxA-p7"})
        asyncio.run(main._backfill_identities())
        assert ("honeygain", wid, "p7", "HONEYGAIN_DEVICE_NAME") not in _active()

    def test_a_copy_with_no_digest_is_not_recorded(self, db):
        wid = self._setup("boxB")
        _proxied_heartbeat(wid, "honeygain", 7, None)
        asyncio.run(main._backfill_identities())
        assert ("honeygain", wid, "p7", "HONEYGAIN_DEVICE_NAME") not in _active()

    def test_a_proven_copy_is_recorded(self, db):
        wid = self._setup("boxB")
        _proxied_heartbeat(wid, "honeygain", 7, {"HONEYGAIN_DEVICE_NAME": "boxB-p7"})
        asyncio.run(main._backfill_identities())
        assert _active()[("honeygain", wid, "p7", "HONEYGAIN_DEVICE_NAME")] == "boxB-p7"


class TestTheWorkerReportsAProxiedCopysDigest:
    def test_status_carries_the_digest_never_the_id(self, db):
        from app import orchestrator, proxy_tunnel

        earner = MagicMock()
        earner.id, earner.short_id, earner.name, earner.status = "e1", "e1", "cashpilot-earnapp-p7", "running"
        earner.labels = {"cashpilot.service": "earnapp", "cashpilot.managed": "true", proxy_tunnel.LABEL_PROXY: "7"}
        earner.client.api.inspect_container.return_value = {"Config": {"Env": [f"EARNAPP_UUID={UUID_A}"]}}
        client = MagicMock()
        client.containers.list.return_value = [earner]
        orchestrator._identity_values.clear()
        with (
            patch.object(orchestrator, "identity_digest_key", lambda: WORKER_KEY),
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_collect_stats_bulk", return_value={}),
            patch.object(proxy_tunnel, "held", return_value=set()),
        ):
            (entry,) = proxy_tunnel.status()
        orchestrator._identity_values.clear()
        assert entry["identity_digest"] == _digest("earnapp", {"EARNAPP_UUID": UUID_A})
        assert UUID_A not in json.dumps(entry)


class TestARestartAfterAScaleDown:
    """The in-memory list of copies is empty after a restart; a removed copy must still stay retired."""

    HG = {"HONEYGAIN_EMAIL": "me@example.com", "HONEYGAIN_PASSWORD": "pw", "HONEYGAIN_DEVICE_NAME": "box"}
    RUNS = {n: {"HONEYGAIN_DEVICE_NAME": "box" if n == 1 else f"box-{n}"} for n in (1, 2, 3)}
    COPY_THREE = ("honeygain", None, "3", "HONEYGAIN_DEVICE_NAME")

    def _scaled_down(self):
        wid = _worker(running=[("honeygain", [1])])
        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            assert _deploy("honeygain", self.HG, wid, instances=3)[0] is None
            _heartbeat("box-a", self.RUNS)  # stored: still lists copy 3
            assert _deploy("honeygain", self.HG, wid, instances=2, running={1, 2, 3}, ran={3: self.RUNS[3]})[0] is None
        assert ("honeygain", wid, "3", "HONEYGAIN_DEVICE_NAME") not in _active()
        return wid

    def _restart(self):
        main._IDENTITIES_CHECKED.clear()
        main._IDENTITIES_LISTED.clear()

    def test_the_backfill_does_not_bring_it_back(self, db):
        wid = self._scaled_down()
        self._restart()
        asyncio.run(main._backfill_identities())
        assert ("honeygain", wid, "3", "HONEYGAIN_DEVICE_NAME") not in _active()
        for _ in range(3):
            _heartbeat("box-a", {1: self.RUNS[1], 2: self.RUNS[2]})
        assert ("honeygain", wid, "3", "HONEYGAIN_DEVICE_NAME") not in _active()

    def test_a_late_heartbeat_then_a_restart(self, db):
        wid = self._scaled_down()
        _heartbeat("box-a", self.RUNS)  # built before the DELETE, it proves copy 3 again
        self._restart()
        for _ in range(2):
            _heartbeat("box-a", {1: self.RUNS[1], 2: self.RUNS[2]})
        assert ("honeygain", wid, "3", "HONEYGAIN_DEVICE_NAME") not in _active()
        assert ("honeygain", wid, "3", "HONEYGAIN_DEVICE_NAME", "box-3") in _retired()
        assert set(_active()) == {
            ("honeygain", wid, "1", "HONEYGAIN_DEVICE_NAME"),
            ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME"),
        }

    def test_a_copy_above_the_count_that_still_runs_is_kept(self, db):
        wid = self._scaled_down()
        _heartbeat("box-a", self.RUNS)
        self._restart()
        _heartbeat("box-a", self.RUNS)
        assert _active()[("honeygain", wid, "3", "HONEYGAIN_DEVICE_NAME")] == "box-3"


class TestTheImportPagesDeploy:
    def _deploy(self, wid, body):
        hop = AsyncMock(return_value={"container_id": "c"})

        async def run():
            with (
                patch.object(main, "_resolve_worker_id", AsyncMock(return_value=wid)),
                patch.object(main.importers_router, "draft_env", AsyncMock(return_value={"EARNAPP_UUID": UUID_A})),
                patch.object(main, "_proxy_to_worker", hop),
                patch.object(main, "_register_device", AsyncMock(return_value=True)),
                patch.object(main.database, "record_health_event", AsyncMock()),
                patch.object(main, "_spawn", lambda coro: coro.close()),
                patch.object(main.metrics, "record_container_lifecycle", lambda *a: None),
            ):
                try:
                    await main.api_import_draft_deploy(_request(), "earnapp", body, worker_id=wid, user=OWNER)
                except HTTPException as exc:
                    return exc
                return None

        return asyncio.run(run()), hop

    def test_the_owner_may_confirm_a_shared_id(self, db):
        asyncio.run(database.record_identities("earnapp", 1, {"1": {"EARNAPP_UUID": UUID_A}}))
        error, hop = self._deploy(2, main.ImportDeployRequest())
        assert error.status_code == 409 and error.detail["error"] == "identity_in_use"
        hop.assert_not_awaited()
        error, hop = self._deploy(2, main.ImportDeployRequest(allow_shared_identity=True))
        assert error is None
        hop.assert_awaited_once()

    def test_the_page_posts_a_body_the_retry_can_extend(self):
        source = (Path(__file__).resolve().parents[1] / "app/static/js/import.js").read_text()
        call = source[source.index("/api/import/drafts/") :]
        call = call[: call.index(");")]
        assert "body: {}" in call


# ---------------------------------------------------------------------------
# Review of #753, twelfth round: a box that could not list its containers, a
# deleted box's records, a stale row at removal and replacement, the raw
# route's replaced copy, a heartbeat that outlives the record it read, and
# a device id in capitals
# ---------------------------------------------------------------------------


HEX = "a1" * 32


def _hg_losing_copy_two(wid, name):
    """Redeploy honeygain as ``name`` on two copies; copy 2's write fails, so its row stays what it was."""
    real = database.record_identities

    async def flaky(slug, worker_id, values, **kwargs):
        if "2" in values:
            raise RuntimeError("database is locked")
        return await real(slug, worker_id, values, **kwargs)

    with (
        patch.object(main, "scaling_limit", lambda svc: (3, "")),
        patch.object(main.database, "record_identities", flaky),
    ):
        assert (
            _deploy("honeygain", {**TestACopyWhoseWriteFailed.HG, "HONEYGAIN_DEVICE_NAME": name}, wid, instances=2)[0]
            is None
        )


class TestABoxThatCouldNotListItsContainers:
    """A worker whose Docker would not list sends an empty list: no copy it leaves out is gone."""

    def _copy_two_above_the_count(self):
        wid = _worker(running=[("honeygain", [1])])
        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            assert _deploy("honeygain", TestACopyWhoseWriteFailed.HG, wid, instances=2)[0] is None
            assert _deploy("honeygain", TestACopyWhoseWriteFailed.HG, wid, instances=1, running=set())[0] is None
        runs = {1: {"HONEYGAIN_DEVICE_NAME": "box"}, 2: {"HONEYGAIN_DEVICE_NAME": "box-2"}}
        _heartbeat("box-a", runs)
        return wid, runs

    def test_its_empty_list_retires_nothing(self, db):
        wid, runs = self._copy_two_above_the_count()
        _heartbeat("box-a", {}, listed=False)
        assert ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME") in _active()
        # And the next real list still compares against the last real one.
        _heartbeat("box-a", {1: runs[1]}, listed=True)
        assert ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME") not in _active()

    def test_a_real_empty_list_still_retires(self, db):
        """The positive control: a box that listed and found no copy 2."""
        wid, _ = self._copy_two_above_the_count()
        _heartbeat("box-a", {}, listed=True)
        assert ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME") not in _active()

    def test_get_status_says_whether_it_listed(self):
        from app import orchestrator

        client = MagicMock()
        client.containers.list.side_effect = RuntimeError("daemon 500")
        with patch.object(orchestrator, "_get_client", return_value=client):
            assert orchestrator.get_status() == []
        assert orchestrator.status_listed() is False
        client.containers.list.side_effect = None
        client.containers.list.return_value = []
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value={}),
        ):
            orchestrator.get_status()
        assert orchestrator.status_listed() is True

    def test_the_worker_sends_it(self):
        from app import worker_api

        resp = MagicMock()
        resp.json = MagicMock(return_value={"status": "ok"})
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.post = AsyncMock(return_value=resp)
        sent = []
        for listed in (False, True):
            with (
                patch.object(worker_api, "UI_URL", "http://ui:8080"),
                patch.object(worker_api.orchestrator, "get_status", return_value=[]),
                patch.object(worker_api.orchestrator, "status_listed", return_value=listed),
                patch.object(worker_api.orchestrator, "docker_available", return_value=False),
                patch.object(worker_api, "_detect_egress_ip", AsyncMock(return_value=None)),
                patch.object(worker_api.httpx, "AsyncClient", return_value=client),
            ):
                asyncio.run(worker_api._send_heartbeat())
            sent.append(client.post.await_args.kwargs["json"]["system_info"]["containers_listed"])
        assert sent == [False, True]


class TestARestartThenAnEmptyList:
    def test_a_reactivated_copy_of_a_service_the_list_leaves_out_is_retired(self, db):
        case = TestARestartAfterAScaleDown()
        wid = case._scaled_down()
        _heartbeat("box-a", case.RUNS)  # built before the DELETE, it proves copy 3 again
        case._restart()
        for _ in range(2):
            _heartbeat("box-a", {})
        assert ("honeygain", wid, "3", "HONEYGAIN_DEVICE_NAME") not in _active()
        assert ("honeygain", wid, "3", "HONEYGAIN_DEVICE_NAME", "box-3") in _retired()


class TestAFailedRetirement:
    def test_the_next_heartbeat_retires_it(self, db):
        wid, runs = TestABoxThatCouldNotListItsContainers()._copy_two_above_the_count()
        real = database.record_identities

        async def locked(slug, worker_id, values, **kwargs):
            if values == {"2": {}}:
                raise RuntimeError("database is locked")
            return await real(slug, worker_id, values, **kwargs)

        with patch.object(main.database, "record_identities", locked):
            _heartbeat("box-a", {1: runs[1]})
        assert ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME") in _active()
        _heartbeat("box-a", {1: runs[1]})
        assert ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME") not in _active()


class TestACopyWithNoRecord:
    def test_the_heartbeat_reads_it_once(self, db):
        """A labelled copy that runs with no deploy record (a box enrolled again, a forgotten record)."""
        _worker()
        specs = AsyncMock(side_effect=database.get_deployment_spec)
        reads = AsyncMock(side_effect=database.active_identity_values)
        with (
            patch.object(main.database, "get_deployment_spec", specs),
            patch.object(main.database, "active_identity_values", reads),
        ):
            for _ in range(4):
                _heartbeat("box-a", {1: {"EARNAPP_UUID": UUID_A}}, slug="earnapp")
        assert (specs.await_count, reads.await_count) == (1, 1)
        assert _rows() == []


class TestACopyListedTwice:
    """A redeploy keeps the old container aside under the same copy until the new one runs."""

    def test_neither_digest_counts(self):
        both = [
            {"slug": "earnapp", "instance": 1, "container_id": "old", "identity_digest": "x"},
            {"slug": "earnapp", "instance": 1, "container_id": "new", "identity_digest": "y"},
            {"slug": "earnapp", "instance": 2, "container_id": "two", "identity_digest": "z"},
        ]
        assert main._copy_digests(both, "earnapp") == {2: "z"}

    def test_the_stale_row_is_still_repaired_once_the_old_one_is_gone(self, db):
        wid = TestAStaleActiveRow()._stale()
        old, new = (
            {"slug": "earnapp", "instance": 1, "container_id": cid, "identity_digest": _digest("earnapp", ids)}
            for cid, ids in (("old" * 4, {"EARNAPP_UUID": UUID_A}), ("new" * 4, {"EARNAPP_UUID": UUID_B}))
        )
        _heartbeat("box-a", None, containers=[old, new])
        _heartbeat("box-a", None, containers=[new])
        assert _active() == {("earnapp", wid, "1", "EARNAPP_UUID"): UUID_B}


class TestAStaleRowAtRemovalAndReplacement:
    """Copy 2's row says box-2, but a redeploy to "new" put it on new-2 and that write failed."""

    def _stale_copy_two(self):
        wid = _worker(running=[("honeygain", [1])])
        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            assert _deploy("honeygain", TestACopyWhoseWriteFailed.HG, wid, instances=2)[0] is None
        _hg_losing_copy_two(wid, "new")
        assert _active()[("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME")] == "box-2"
        return wid

    def test_a_removal_keeps_new_2(self, db):
        wid = self._stale_copy_two()
        _remove("honeygain", wid, ran={2: {"HONEYGAIN_DEVICE_NAME": "new-2"}})
        assert _active() == {}
        assert {
            ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME", "box-2"),
            ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME", "new-2"),
        } <= _retired()

    def test_a_replacement_keeps_new_2(self, db):
        wid = self._stale_copy_two()
        with patch.object(main, "scaling_limit", lambda svc: (3, "")):
            error, _ = _deploy(
                "honeygain",
                {**TestACopyWhoseWriteFailed.HG, "HONEYGAIN_DEVICE_NAME": "third"},
                wid,
                instances=2,
                replaced={2: {"HONEYGAIN_DEVICE_NAME": "new-2"}},
            )
        assert error is None
        assert _active()[("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME")] == "third-2"
        assert {
            ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME", "box-2"),
            ("honeygain", wid, "2", "HONEYGAIN_DEVICE_NAME", "new-2"),
        } <= _retired()


class TestTheRawRouteKeepsTheReplacedIds:
    def test_a_raw_redeploy_keeps_the_id_whose_write_failed(self, db):
        wid = _worker()

        async def failing(*args, **kwargs):
            raise RuntimeError("database is locked")

        with patch.object(main.database, "record_identities", failing):
            assert _raw_deploy({"EARNAPP_UUID": UUID_A}, wid)[0] is None
        assert _rows() == []
        answer = {"replaced_identity_digest": _digest("earnapp", {"EARNAPP_UUID": UUID_A})}
        assert _raw_deploy({"EARNAPP_UUID": UUID_B}, wid, answer=answer)[0] is None
        assert _active() == {("earnapp", wid, "1", "EARNAPP_UUID"): UUID_B}
        assert ("earnapp", wid, "1", "EARNAPP_UUID", UUID_A) in _retired()


class TestAHeartbeatThatOutlivesItsRecord:
    def test_a_removal_between_its_read_and_its_write_keeps_the_id_retired(self, db):
        wid = _worker()
        _deploy_losing_the_write("earnapp", {"EARNAPP_UUID": UUID_A}, wid)
        real = database.get_deployment_spec

        async def read_then_removed(slug, worker_id=None):
            spec = await real(slug, worker_id=worker_id)
            await database.remove_deployment(slug, worker_id=worker_id)
            return spec

        with patch.object(main.database, "get_deployment_spec", read_then_removed):
            asyncio.run(main._reconcile_running_identities(wid, _entries("earnapp", {1: {"EARNAPP_UUID": UUID_A}})))
        assert _active() == {}
        assert ("earnapp", wid, "1", "EARNAPP_UUID", UUID_A) in _retired()

    def test_with_the_record_in_place_it_writes(self, db):
        """The positive control: the same heartbeat, no removal, records the id."""
        wid = _worker()
        _deploy_losing_the_write("earnapp", {"EARNAPP_UUID": UUID_A}, wid)
        asyncio.run(main._reconcile_running_identities(wid, _entries("earnapp", {1: {"EARNAPP_UUID": UUID_A}})))
        assert _active() == {("earnapp", wid, "1", "EARNAPP_UUID"): UUID_A}


class TestADeletedBoxsRecords:
    def _deleted_box_ran(self, uuid):
        wid = _worker()
        asyncio.run(
            database.save_deployment(
                slug="earnapp", container_id="c1", spec={"env": {"EARNAPP_UUID": uuid}}, worker_id=wid
            )
        )
        asyncio.run(database.record_identities("earnapp", wid, {"1": {"EARNAPP_UUID": uuid}}))
        asyncio.run(database.delete_worker(wid))
        return wid

    @pytest.mark.parametrize("where", ["everywhere", "that box"])
    def test_a_forgotten_id_stays_forgotten(self, db, where):
        wid = self._deleted_box_ran(UUID_A)
        (row,) = _rows()
        assert asyncio.run(database.delete_identity(row["id"]))
        asyncio.run(database.remove_deployment("earnapp", worker_id=None if where == "everywhere" else wid))
        assert _rows() == []

    def test_a_write_after_the_delete_claims_no_box(self, db):
        """A deploy that finished after its box was deleted."""
        wid = _worker()
        asyncio.run(database.delete_worker(wid))
        asyncio.run(database.record_identities("proxyrack", wid, {"1": {"UUID": HEX}}))
        assert asyncio.run(database.identity_in_use("proxyrack", "UUID", HEX)) == []

    def test_a_deployment_from_before_per_box_records_is_kept(self, db):
        wid = _legacy_deployment("earnapp", {"EARNAPP_UUID": UUID_A})
        asyncio.run(database.delete_worker(wid))
        assert _active() == {}
        assert ("earnapp", wid, "1", "EARNAPP_UUID", UUID_A) in _retired()


class TestAFleetWideSpecIsInUse:
    def test_the_shared_id_check_sees_it(self, db):
        """A deployment from before per-box records, whose backfill has not run: no ledger row."""
        wid = _legacy_deployment("earnapp", {"EARNAPP_UUID": UUID_A})
        assert _rows() == []
        assert asyncio.run(database.identity_in_use("earnapp", "EARNAPP_UUID", UUID_A, except_worker=2)) == [wid]
        error, sent = _deploy("earnapp", {"EARNAPP_UUID": UUID_A}, 2)
        assert error.status_code == 409 and sent == []


class TestADeviceIdInCapitals:
    def test_the_shared_id_check_ignores_letter_case(self, db):
        asyncio.run(database.record_identities("proxyrack", 1, {"1": {"UUID": HEX}}))
        assert asyncio.run(database.identity_in_use("proxyrack", "UUID", HEX.upper(), except_worker=2)) == [1]

    def test_the_claim_holds_an_id_in_any_letter_case(self):
        svc = catalog.get_service("proxyrack")

        async def run():
            entered = asyncio.Event()

            async def second():
                async with main._device_id_claim("proxyrack", svc, {"UUID": HEX.upper()}):
                    entered.set()

            async with main._device_id_claim("proxyrack", svc, {"UUID": HEX}):
                task = asyncio.create_task(second())
                await asyncio.sleep(0.02)
                held = not entered.is_set()
            await task
            return held

        assert asyncio.run(run())
        assert not main._DEVICE_ID_CLAIMS
