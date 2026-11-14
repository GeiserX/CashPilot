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
import os
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import auth, catalog, database, main  # noqa: E402

UUID_A = "sdk-node-" + "a" * 32
UUID_B = "sdk-node-" + "b" * 28 + "1234"
OWNER = {"uid": 1, "u": "owner", "r": "owner"}


@pytest.fixture
def db(tmp_path):
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
        asyncio.run(database.init_db())
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
        asyncio.run(database.record_identities("earnapp", 7, {"1": {"EARNAPP_UUID": UUID_A}}))
        [offer] = _call(OWNER, "GET", "/api/identities/reuse/earnapp?key=EARNAPP_UUID").json()
        assert offer["in_use_on"] == ["a removed worker (#7)"]
        [offer] = _call(OWNER, "GET", "/api/identities/reuse/earnapp?key=EARNAPP_UUID&worker_id=7").json()
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


def _deploy(slug, env, worker_id, *, instances=None, allow=False):
    sent: list[dict] = []

    async def hop(wid, method, path, *, json=None, **kwargs):
        sent.append({"worker": wid, "path": path, "json": json})
        return {"container_id": f"c{wid}"}

    body = main.DeployRequest(env=env, instances=instances, allow_shared_identity=allow)

    async def run():
        with (
            patch.object(auth, "get_current_user", return_value=OWNER),
            patch.object(main, "_resolve_worker_id", AsyncMock(return_value=worker_id)),
            patch.object(main, "_proxy_to_worker", hop),
            patch.object(main, "_worker_features", AsyncMock(return_value={"instances"})),
            patch.object(main, "_worker_instances", AsyncMock(return_value=set())),
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


def _worker(name="box-a"):
    return asyncio.run(database.upsert_worker(f"client-{name}", name=name))


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
        wid = _worker()
        hex_uuid = "ab" * 32
        spec = {"env": {"UUID": hex_uuid, "DEVICE_NAME": "box", "API_KEY": "secret-key"}, "instances": 2}
        asyncio.run(database.save_deployment(slug="proxyrack", container_id="c1", spec=spec, worker_id=wid))
        asyncio.run(database.save_proxied_copy(7, wid, "proxyrack"))
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
