"""Tests for main.py deploy/stop/restart/remove routes and worker proxy commands.

These routes proxy commands to workers via httpx, so we mock the httpx calls
and the database layer.
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote, quote_plus

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import httpx
import pytest
from fastapi.testclient import TestClient

from app import catalog, database, wallet_seed
from app.main import app


# No-op lifespan
@asynccontextmanager
async def _noop_lifespan(a):
    yield


app.router.lifespan_context = _noop_lifespan


def _owner_user():
    return {"uid": 1, "u": "admin", "r": "owner"}


def _writer_user():
    return {"uid": 2, "u": "writer", "r": "writer"}


def _auth_owner():
    return patch("app.main.auth.get_current_user", return_value=_owner_user())


def _auth_writer():
    return patch("app.main.auth.get_current_user", return_value=_writer_user())


def _no_auth():
    return patch("app.main.auth.get_current_user", return_value=None)


@pytest.fixture(autouse=True)
def _no_recorded_deployment_spec():
    """Default these tests to "this service has never been deployed".

    The deploy route now reads the previously recorded spec so a redeploy
    reproduces the container that is actually running. Returning None keeps the
    pre-existing behaviour these tests assert on - build the spec from the
    catalog - without each of them having to mock the database.
    """
    # The deploy also reads the worker's row: its client_id names the device
    # (tests/test_device_names.py). A test that needs a particular row patches it.
    with (
        patch("app.main.database.get_deployment_spec", new_callable=AsyncMock, return_value=None),
        patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=_online_worker()),
    ):
        yield


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def deploy_capture():
    """Capture the spec forwarded to ``_proxy_worker_deploy``.

    Returns ``(captured, side_effect)``: patch ``app.main._proxy_worker_deploy``
    with ``side_effect``, then read the forwarded spec from ``captured["spec"]``.
    """
    captured: dict = {}

    async def _capture_deploy(worker_id, slug, spec):
        captured["spec"] = spec
        return {"container_id": "abc123"}

    return captured, _capture_deploy


def _online_worker(wid=1, url="http://192.168.1.10:8081"):
    return {"id": wid, "name": "w1", "status": "online", "url": url}


def _mock_httpx_resp(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = json.dumps(json_data or {})
    resp.headers = {"content-type": "application/json"}
    return resp


class TestDesktopWalletDeploys:
    _PHRASE_12 = "abandon " * 11 + "about"
    _PHRASE_24 = "abandon " * 23 + "art"
    # Round-8 offline fixtures generated and validated by siad and hostd.
    _LEGACY_SIA = (
        "orphans deepest spout owed symptoms lukewarm knowledge zesty eternal physics nomad jump across lodge "
        "womanly axes yanks cocoa pairing pastry vivid itself nineteen ecstatic kickoff lending oxidant aloof adept"
    )
    _HOSTD_PHRASE = "cushion board east legend empty place lecture tongue retire repeat avoid acquire"
    _LOCATION_TAGS = (
        "airport,beach,bridge,canal,canyon,cave,city,cliff,coast,country,desert,farm,forest,garden,harbor,hill,island,"
        "jungle,lake,meadow,mountain,ocean,park,river,road,school,ski,stadium,station,street,town,trail,valley,village"
    )
    _HOST_NAMES = _LOCATION_TAGS.split(",")[2:14]
    _BAD_CHECKSUM = "people walk home before lunch then enjoy fresh bread near apple tree"
    _LONG_TEXT = (
        "The local community group meets near the river each Thursday. "
        "Our volunteers prepare meals for anyone who needs one."
    )
    _HONEYGAIN_ENV = {"HONEYGAIN_EMAIL": "owner@example.test", "HONEYGAIN_PASSWORD": "test-password"}

    @pytest.fixture(autouse=True)
    def desktop_db(self, tmp_path):
        with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
            asyncio.run(database.init_db())
            yield

    @pytest.fixture
    def worker_target(self):
        worker = {
            **_online_worker(2, url="http://192.168.1.30:8086"),
            "client_id": "desk",
            "system_info": json.dumps({"device_type": "desktop"}),
        }
        post = AsyncMock(return_value=_mock_httpx_resp(200, {"container_id": "c1"}))
        with (
            _auth_owner(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.get_worker_key_state", new_callable=AsyncMock, return_value=("desk-key", True)),
            patch("app.main._validate_worker_url", return_value=(worker["url"], None)),
            patch("app.main.database.forget_env_value", new_callable=AsyncMock, return_value=(False, False)),
            patch("app.main.database.prior_deployment_spec", new_callable=AsyncMock, return_value=None),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main.database.record_identities", new_callable=AsyncMock),
            patch("app.main._spawn", lambda coro: coro.close()),
            patch("httpx.AsyncClient.post", post),
        ):
            yield worker, post

    @pytest.fixture
    def fake_wallet_seed(self):
        return " ".join(f"fake-test-word-{index}" for index in range(12))

    @pytest.fixture
    def hostd_env(self):
        return {"HOSTD_API_PASSWORD": "test-password", "SIA_STORAGE_DIR": "/srv/sia"}

    def _assert_wallet_refusal(self, response, post, fake_wallet_seed=None):
        if fake_wallet_seed is not None:
            seed_was_sent = any(fake_wallet_seed in json.dumps(call.kwargs["json"]) for call in post.await_args_list)
            assert not seed_was_sent, "The web server sent the wallet seed to the Desktop"
        assert not post.await_count, "The web server sent a request to the Desktop"
        assert response.status_code == 409
        assert "runs only on the machine that holds its wallet" in response.json()["detail"]

    @pytest.mark.parametrize("source", ["posted", "recorded"])
    def test_legacy_seed_never_reaches_desktop(self, client, worker_target, fake_wallet_seed, hostd_env, source):
        _, post = worker_target
        env = {**hostd_env, "HOSTD_WALLET_SEED": fake_wallet_seed}
        recorded = {"env": env} if source == "recorded" else None
        with patch("app.main.database.get_deployment_spec", new_callable=AsyncMock, return_value=recorded):
            response = client.post("/api/deploy/sia-hostd?worker_id=2", json={"env": {} if recorded else env})
        self._assert_wallet_refusal(response, post, fake_wallet_seed)

    def test_wallet_choice_stays_off_desktop_even_if_it_advertises_support(self, client, worker_target, hostd_env):
        worker, post = worker_target
        worker["system_info"] = json.dumps({"device_type": "desktop", "features": ["wallet_seed_file"]})
        response = client.post(
            "/api/deploy/sia-hostd?worker_id=2", json={"env": hostd_env, "wallet_seed": {"mode": "generate"}}
        )
        self._assert_wallet_refusal(response, post)

    @pytest.mark.parametrize(
        ("slug", "field"),
        [
            ("sia-hostd", "env"),
            ("sia-hostd", "wallet_seed"),
            ("other-service", "env"),
            ("other-service", "wallet_seed"),
        ],
    )
    def test_raw_deploy_never_forwards_a_wallet_seed(self, client, worker_target, fake_wallet_seed, slug, field):
        _, post = worker_target
        spec = (
            {"env": {"HOSTD_WALLET_SEED": fake_wallet_seed}}
            if field == "env"
            else {"wallet_seed": {"mode": "import", "phrase": fake_wallet_seed}}
        )
        response = client.post("/api/workers/2/command", json={"command": "deploy", "slug": slug, "spec": spec})
        self._assert_wallet_refusal(response, post, fake_wallet_seed)

    @pytest.mark.parametrize(
        "field", ["HOSTD_WALLET_SEED", "hostd_wallet_seed", "HostD_Wallet_Seed", "hostd-wallet-seed"]
    )
    def test_raw_deploy_refuses_legacy_seed_key_spellings(self, client, worker_target, fake_wallet_seed, field):
        _, post = worker_target
        spec = {
            "image": "honeygain/honeygain:latest",
            "env": {
                "HONEYGAIN_EMAIL": "owner@example.test",
                "HONEYGAIN_PASSWORD": "test-password",
                field: fake_wallet_seed,
            },
        }
        response = client.post("/api/workers/2/command", json={"command": "deploy", "slug": "honeygain", "spec": spec})
        self._assert_wallet_refusal(response, post, fake_wallet_seed)

    def test_raw_deploy_refuses_a_seed_in_fields_docker_strips(self, client, worker_target, fake_wallet_seed):
        _, post = worker_target
        spec = {"image": "honeygain/honeygain:latest", "env": {}, "approval": [{"walletSeed": fake_wallet_seed}]}
        response = client.post("/api/workers/2/command", json={"command": "deploy", "slug": "honeygain", "spec": spec})
        self._assert_wallet_refusal(response, post, fake_wallet_seed)
        assert fake_wallet_seed not in response.text

    def test_raw_deploy_refuses_a_valid_phrase_under_an_unrelated_key(self, client, worker_target):
        _, post = worker_target
        # Public BIP-39 test vector for zero entropy.
        phrase = "abandon " * 11 + "about"
        spec = {"image": "honeygain/honeygain:latest", "env": {"HONEYGAIN_PASSWORD": phrase}}
        response = client.post("/api/workers/2/command", json={"command": "deploy", "slug": "honeygain", "spec": spec})
        self._assert_wallet_refusal(response, post, phrase)
        assert phrase not in response.text

    @pytest.mark.parametrize(
        "shape",
        ["valid-24", "comma", "embedded", "newline", "tab", "valid-15", "valid-18", "valid-21"],
    )
    def test_raw_deploy_refuses_a_phrase_in_request_values(self, client, worker_target, shape):
        _, post = worker_target
        words = self._PHRASE_12.split()
        assert wallet_seed.phrase_problem(self._PHRASE_12) is None
        assert wallet_seed.phrase_problem(self._PHRASE_24, words=24) is None
        env = dict(self._HONEYGAIN_ENV)
        spec = {"image": catalog.get_service("honeygain")["docker"]["image"], "env": env}
        env["HONEYGAIN_PASSWORD"] = {
            "valid-24": self._PHRASE_24,
            "comma": ", ".join(words),
            "embedded": f"Example text: {self._PHRASE_12} (end of example)",
            "newline": "\n".join(words),
            "tab": "\t".join(words),
            "valid-15": "abandon " * 14 + "address",
            "valid-18": "abandon " * 17 + "agent",
            "valid-21": "abandon " * 20 + "admit",
        }[shape]
        other_http = AsyncMock(side_effect=AssertionError("unexpected outbound HTTP"))
        with patch("httpx.AsyncClient.send", other_http):
            response = client.post(
                "/api/workers/2/command", json={"command": "deploy", "slug": "honeygain", "spec": spec}
            )
        other_http.assert_not_awaited()
        assert (response.status_code, post.await_count) == (409, 0)
        assert "abandon" not in response.text

    @pytest.mark.parametrize("shape", ["hyphen", "split-fields", "split-list"])
    def test_raw_deploy_refuses_a_saved_phrase_with_unusual_separators(self, client, worker_target, shape):
        _, post = worker_target
        asyncio.run(database.set_config("sia-hostd_HOSTD_WALLET_SEED", self._PHRASE_12))
        words = self._PHRASE_12.split()
        env = dict(self._HONEYGAIN_ENV)
        spec = {"image": catalog.get_service("honeygain")["docker"]["image"], "env": env}
        if shape == "hyphen":
            env["HONEYGAIN_PASSWORD"] = "-".join(words)
        elif shape == "split-fields":
            env["HONEYGAIN_PASSWORD"] = " ".join(words[:6])
            env["HONEYGAIN_DEVICE_NAME"] = " ".join(words[6:])
        else:
            spec["extra"] = words
        response = client.post("/api/workers/2/command", json={"command": "deploy", "slug": "honeygain", "spec": spec})
        self._assert_wallet_refusal(response, post, self._PHRASE_12)
        assert "abandon" not in response.text

    def test_raw_deploy_checks_saved_phrase_in_the_serialized_body_order(self, client, worker_target):
        _, post = worker_target
        asyncio.run(database.set_config("sia-hostd_HOSTD_WALLET_SEED", self._PHRASE_12))
        words = self._PHRASE_12.split()
        spec = {"env": {"PASSWORD": " ".join(words[6:])}, "image": "fixture.invalid/" + "-".join(words[:6])}
        response = client.post("/api/workers/2/command", json={"command": "deploy", "slug": "honeygain", "spec": spec})
        self._assert_wallet_refusal(response, post, self._PHRASE_12)
        assert "abandon" not in response.text

    @pytest.mark.parametrize(
        ("phrase", "shape"),
        [
            (_LEGACY_SIA, "url-encoded-comma"),
            (_LEGACY_SIA, "json-escaped-newline"),
            (_LEGACY_SIA, "json-escaped-tab"),
            (_HOSTD_PHRASE, "url-encoded-comma"),
            (_HOSTD_PHRASE, "json-escaped-newline"),
            (_LEGACY_SIA, "nested-encodings"),
        ],
        ids=["sia-url", "sia-json-newline", "sia-json-tab", "hostd-url", "hostd-json", "nested-encodings"],
    )
    def test_desktop_refuses_an_encoded_saved_phrase(self, client, worker_target, caplog, phrase, shape):
        _, post = worker_target
        asyncio.run(database.set_config("sia-hostd_HOSTD_WALLET_SEED", phrase))
        words = phrase.split()
        value = {
            "url-encoded-comma": "https://fixture.invalid/?note=" + quote(",".join(words), safe=""),
            "json-escaped-newline": json.dumps({"note": "\n".join(words)}),
            "json-escaped-tab": json.dumps({"note": "\t".join(words)}),
            "nested-encodings": quote_plus(quote(json.dumps(json.dumps({"note": r"\u002b".join(words)})), safe="")),
        }[shape]
        spec = {
            "image": catalog.get_service("honeygain")["docker"]["image"],
            "env": {**self._HONEYGAIN_ENV, "NOTE": value},
        }
        response = client.post("/api/workers/2/command", json={"command": "deploy", "slug": "honeygain", "spec": spec})
        self._assert_wallet_refusal(response, post, phrase)
        assert all(secret not in response.text and secret not in caplog.text for secret in (phrase, value))

    def test_desktop_refuses_a_saved_phrase_with_a_word_split_between_values(self, client, worker_target):
        _, post = worker_target
        asyncio.run(database.set_config("sia-hostd_HOSTD_WALLET_SEED", self._LEGACY_SIA))
        spec = {
            "image": catalog.get_service("honeygain")["docker"]["image"],
            "env": {**self._HONEYGAIN_ENV, "PART_1": "Note%3A+or", "PART_2": self._LEGACY_SIA[2:]},
        }
        response = client.post("/api/workers/2/command", json={"command": "deploy", "slug": "honeygain", "spec": spec})
        self._assert_wallet_refusal(response, post, self._LEGACY_SIA)

    @pytest.mark.parametrize("phrase", [_PHRASE_12, _LEGACY_SIA])
    def test_desktop_refuses_an_unsaved_phrase_wrapped_in_quotes(self, client, worker_target, phrase):
        _, post = worker_target
        spec = {
            "image": catalog.get_service("honeygain")["docker"]["image"],
            "env": {**self._HONEYGAIN_ENV, "NOTE": f'"{phrase}"'},
        }
        response = client.post("/api/workers/2/command", json={"command": "deploy", "slug": "honeygain", "spec": spec})
        self._assert_wallet_refusal(response, post, phrase)

    def test_invalid_env_value_does_not_echo_a_recovery_phrase_in_its_key(self, client, worker_target):
        _, post = worker_target
        response = client.post("/api/deploy/honeygain?worker_id=2", json={"env": {self._PHRASE_12: {"wrong": "type"}}})
        assert response.status_code == 422
        assert self._PHRASE_12 not in response.text
        post.assert_not_awaited()

    @pytest.mark.parametrize("phrase", [_PHRASE_12, _LEGACY_SIA], ids=["bip39", "sia"])
    @pytest.mark.parametrize("raw", [False, True], ids=["catalog", "raw"])
    def test_desktop_refuses_mixed_recovery_phrase_separators(self, client, worker_target, phrase, raw):
        _, post = worker_target
        pasted = phrase.replace(" ", ", ", 1)
        env = {**self._HONEYGAIN_ENV, "NOTE": pasted}
        if raw:
            spec = {"image": catalog.get_service("honeygain")["docker"]["image"], "env": env}
            response = client.post(
                "/api/workers/2/command", json={"command": "deploy", "slug": "honeygain", "spec": spec}
            )
        else:
            response = client.post("/api/deploy/honeygain?worker_id=2", json={"env": env})
        self._assert_wallet_refusal(response, post, pasted)

    def test_desktop_refuses_an_unsaved_legacy_sia_phrase(self, client, worker_target):
        _, post = worker_target
        spec = {
            "image": catalog.get_service("honeygain")["docker"]["image"],
            "env": {**self._HONEYGAIN_ENV, "NOTE": f"Notes: {self._LEGACY_SIA} (end)"},
        }
        response = client.post("/api/workers/2/command", json={"command": "deploy", "slug": "honeygain", "spec": spec})
        self._assert_wallet_refusal(response, post, self._LEGACY_SIA)

    @pytest.mark.parametrize("source", ["credentials", "fleet", "current", "prior"])
    def test_desktop_refuses_a_saved_phrase_even_with_an_invalid_checksum(self, client, worker_target, source):
        _, post = worker_target
        words = self._BAD_CHECKSUM.split()
        saved = " / ".join(words).upper()
        seed_key = "HOSTD_WALLET_SEED"
        stored = {"env": {seed_key: saved}}
        empty = {"env": {}}

        async def save():
            if source == "credentials":
                await database.set_config(f"sia-hostd_{seed_key}", saved)
            elif source == "fleet":
                await database.save_deployment("sia-hostd", "old", spec=stored)
            else:
                await database.save_deployment("sia-hostd", "old", spec=stored, worker_id=1)
                if source == "prior":
                    await database.save_deployment("sia-hostd", "new", spec=empty, worker_id=1)
                else:
                    await database.save_deployment("sia-hostd", "another", spec=empty)

        asyncio.run(save())
        env = {
            **self._HONEYGAIN_ENV,
            "HONEYGAIN_PASSWORD": "Entry: " + "-".join(words[:6]),
            "HONEYGAIN_DEVICE_NAME": ", ".join(words[6:]) + " (end)",
        }
        response = client.post("/api/deploy/honeygain?worker_id=2", json={"env": env})
        self._assert_wallet_refusal(response, post)
        assert words[0] not in response.text

    @pytest.mark.parametrize(
        ("slug", "env", "raw"),
        [
            ("honeygain", {**_HONEYGAIN_ENV, "HONEYGAIN_PASSWORD": _BAD_CHECKSUM}, True),
            ("honeygain", {**_HONEYGAIN_ENV, "HONEYGAIN_PASSWORD": _LONG_TEXT}, False),
            ("honeygain", {**_HONEYGAIN_ENV, "HONEYGAIN_PASSWORD": "abandon " * 10 + "about"}, True),
            ("iproyal", {"IPROYALPAWNS_EMAIL": "owner@example.test", "IPROYALPAWNS_PASSWORD": _LONG_TEXT}, False),
            ("packetstream", {"CID": "review-fixture"}, True),
            ("traffmonetizer", {"TRAFFMONETIZER_TOKEN": "review-fixture"}, False),
        ],
    )
    def test_desktop_accepts_ordinary_deploy_values(self, client, worker_target, slug, env, raw):
        _, post = worker_target
        assert all(word in wallet_seed._wordlist() for word in self._BAD_CHECKSUM.split())
        assert "does not check out" in wallet_seed.phrase_problem(self._BAD_CHECKSUM)
        if raw:
            spec = {"image": catalog.get_service(slug)["docker"]["image"], "env": env}
            response = client.post("/api/workers/2/command", json={"command": "deploy", "slug": slug, "spec": spec})
        else:
            response = client.post(f"/api/deploy/{slug}?worker_id=2", json={"env": env})
        assert (response.status_code, post.await_count) == (200, 1)
        for key, value in env.items():
            assert post.await_args.kwargs["json"]["env"][key] == value

    @pytest.mark.parametrize(
        "value",
        [
            ",".join(f"{name}01" for name in _HOST_NAMES),
            ",".join(f"{name}.example.test" for name in _HOST_NAMES),
            _LOCATION_TAGS,
            _LOCATION_TAGS.replace(",", ", "),
        ],
        ids=["numbered-hostnames", "fqdn-list", "location-tags", "spaced-location-tags"],
    )
    def test_desktop_accepts_hostname_and_location_tag_lists(self, client, worker_target, value):
        _, post = worker_target
        spec = {
            "image": catalog.get_service("honeygain")["docker"]["image"],
            "env": {**self._HONEYGAIN_ENV, "NOTE": value},
        }
        response = client.post("/api/workers/2/command", json={"command": "deploy", "slug": "honeygain", "spec": spec})
        assert (response.status_code, post.await_count) == (200, 1)
        assert post.await_args.kwargs["json"]["env"]["NOTE"] == value

    @pytest.mark.parametrize("field", ["Env", "unexpected", "approval"])
    def test_raw_desktop_deploy_requires_exact_schema_keys(self, client, worker_target, field):
        _, post = worker_target
        spec = {"image": "honeygain/honeygain:latest", "env": {}, field: {"HONEYGAIN_PASSWORD": "test-password"}}
        response = client.post("/api/workers/2/command", json={"command": "deploy", "slug": "honeygain", "spec": spec})
        post.assert_not_awaited()
        assert response.status_code == 422
        assert "deploy request" in response.json()["detail"]
        assert "test-password" not in response.text

    def test_raw_desktop_deploy_accepts_the_desktop_fields(self, client, worker_target):
        _, post = worker_target
        spec = {"image": "honeygain/honeygain:latest", "env": {"EMAIL": "user@example.test"}, "instance": 1}
        response = client.post("/api/workers/2/command", json={"command": "deploy", "slug": "honeygain", "spec": spec})
        assert response.status_code == 200
        post.assert_awaited_once()
        assert post.await_args.kwargs["json"] == spec

    @pytest.mark.real_worker_deploy_inventory
    @pytest.mark.parametrize("raw", [False, True], ids=["canonical", "raw-command"])
    def test_desktop_deploy_uses_legacy_route_and_requires_replacement_approval(self, client, worker_target, raw):
        worker, post = worker_target
        slug = "honeygain"
        env = {**self._HONEYGAIN_ENV, "HONEYGAIN_DEVICE_NAME": "test-desktop"}
        image = catalog.get_service(slug)["docker"]["image"]
        spec = {"image": image, "env": env}
        if raw:
            path = "/api/workers/2/command"
            body = {"command": "deploy", "slug": slug, "spec": {**spec, "instance": 1}}
            spec = body["spec"]
        else:
            path = f"/api/deploy/{slug}?worker_id=2"
            body = {"env": env}
        first = "a" * 12
        second = "b" * 12
        other_copy = {"slug": slug, "instance": 2, "container_id": "c" * 12}

        async def inventory(url, **kwargs):
            assert url == f"{worker['url']}/api/containers"
            rows = [other_copy]
            if post.await_count:
                rows.append({"slug": slug, "instance": 1, "container_id": first if post.await_count == 1 else second})
            return _mock_httpx_resp(200, rows)

        with patch("httpx.AsyncClient.get", side_effect=inventory) as get:
            response = client.post(path, json=body)
            assert response.status_code == 200, response.text
            assert post.await_count == 1

            response = client.post(path, json=body)
            assert response.status_code == 409, response.text
            detail = response.json()["detail"]
            assert detail["error"] == "confirm_deploy_targets"
            assert "Update CashPilot-Desktop" in detail["message"]
            assert detail["expected_containers"] == {"1": first}
            assert post.await_count == 1

            if raw:
                approved = {**body, "spec": {**spec, "expected_container": first}}
            else:
                approved = {**body, "expected_containers": detail["expected_containers"]}
            response = client.post(path, json=approved)
            assert response.status_code == 200, response.text

            response = client.post(path, json=approved)
            assert response.status_code == 409, response.text
            assert response.json()["detail"]["current_container"] == second

        assert get.await_count == 4
        assert post.await_count == 2
        for call in post.await_args_list:
            assert call.args == (f"{worker['url']}/api/containers/{slug}/deploy",)
            assert call.kwargs["json"] == spec

    def test_fleet_copy_gets_the_wallet_refusal(self, client, worker_target):
        _, post = worker_target
        with patch("app.main.database.get_proxy", new_callable=AsyncMock, return_value={"definition": {}, "state": {}}):
            response = client.post("/api/proxies/1/copies", json={"worker_id": 2, "slug": "sia-hostd"})
        self._assert_wallet_refusal(response, post)

    def test_fleet_copy_cannot_forward_a_seed_recorded_under_another_slug(
        self, client, worker_target, fake_wallet_seed
    ):
        worker, post = worker_target
        worker["system_info"] = json.dumps({"device_type": "desktop", "features": ["proxy_tunnel"]})
        recorded = {"image": "test", "env": {"HOSTD_WALLET_SEED": fake_wallet_seed}}
        copy = {"worker_id": 2, "slug": "honeygain"}
        with (
            patch("app.main.database.get_proxy", new_callable=AsyncMock, return_value={"definition": {}, "state": {}}),
            patch("app.main.database.get_deployment_spec", new_callable=AsyncMock, return_value=recorded),
            patch("app.main.database.list_proxied_copies", new_callable=AsyncMock, side_effect=[[], [copy]]),
            patch("app.main.database.save_proxied_copy", new_callable=AsyncMock),
            patch("app.main.database.delete_proxied_copy", new_callable=AsyncMock) as delete_copy,
        ):
            response = client.post("/api/proxies/1/copies", json={"worker_id": 2, "slug": "honeygain"})
        self._assert_wallet_refusal(response, post, fake_wallet_seed)
        delete_copy.assert_awaited_once_with(1, 2, "honeygain")

    def test_older_docker_worker_still_receives_legacy_seed(self, client, worker_target, fake_wallet_seed, hostd_env):
        worker, post = worker_target
        worker["system_info"] = json.dumps({"docker_available": True, "features": []})
        env = {**hostd_env, "HOSTD_WALLET_SEED": fake_wallet_seed}
        response = client.post("/api/deploy/sia-hostd?worker_id=2", json={"env": env})
        assert response.status_code == 200
        post.assert_awaited_once()
        spec = post.await_args.kwargs["json"]
        assert spec["env"].get("HOSTD_WALLET_SEED") == fake_wallet_seed
        assert "wallet_seed" not in spec


# ---------------------------------------------------------------------------
# Deploy route
# ---------------------------------------------------------------------------


class TestApiDeploy:
    def test_deploy_automatically_picks_the_worker_with_a_url(self, client):
        desktop = _online_worker(2, url="")
        phone = _online_worker(3, url=None)
        worker = _online_worker()
        send_deploy = AsyncMock(return_value={"container_id": "abc123"})
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[desktop, phone, worker]),
            patch("app.main.catalog.get_service", return_value={"slug": "honeygain", "docker": {"image": "test"}}),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main._proxy_worker_deploy", send_deploy),
        ):
            resp = client.post("/api/deploy/honeygain", json={})

        assert resp.status_code == 200, resp.text
        assert send_deploy.await_args.args[:2] == (worker["id"], "honeygain")

    @pytest.mark.parametrize(
        ("query", "status", "message"),
        [
            ("", "online", "No workers online that can receive commands"),
            (
                "?worker_id=2",
                "online",
                "This device only reports to CashPilot, so the server cannot deploy to it or control it. Add services in the CashPilot app on that device, or pick a Docker worker.",
            ),
            (
                "?worker_id=2",
                "offline",
                "This device only reports to CashPilot, so the server cannot deploy to it or control it. Add services in the CashPilot app on that device, or pick a Docker worker.",
            ),
        ],
    )
    def test_deploy_to_a_fleet_with_only_a_report_only_worker(self, client, query, status, message):
        desktop = {**_online_worker(2, url=""), "status": status}
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[desktop]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=desktop),
            patch("app.main.catalog.get_service", return_value={"slug": "honeygain", "docker": {"image": "test"}}),
        ):
            resp = client.post(f"/api/deploy/honeygain{query}", json={})

        assert resp.status_code == 503, resp.text
        assert resp.json()["detail"] == message

    def test_deploy_goes_to_a_desktop_that_takes_commands_with_its_own_key(self, client):
        """A joined Desktop that reports a command URL is a box the server deploys to."""
        desktop = {
            **_online_worker(2, url="http://192.168.1.30:8086"),
            "client_id": "desk",
            "system_info": json.dumps({"device_type": "desktop", "arch": "x86_64"}),
        }
        sent = {}

        async def post(self, url, json=None, params=None, headers=None, **kwargs):
            sent.update(url=url, headers=headers, json=json)
            return _mock_httpx_resp(200, {"status": "deployed", "container_id": "abc123def456"})

        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[desktop]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=desktop),
            patch("app.main.database.get_worker_key_state", new_callable=AsyncMock, return_value=("desk-key", True)),
            patch("app.main._validate_worker_url", return_value=("http://192.168.1.30:8086", None)),
            patch("app.main.FLEET_API_KEY", "shared-key"),
            patch("app.main.catalog.get_service", return_value={"slug": "honeygain", "docker": {"image": "test"}}),
            patch("app.main.database.get_saved_wallet_phrases", new_callable=AsyncMock, return_value=set()),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("httpx.AsyncClient.post", post),
        ):
            resp = client.post("/api/deploy/honeygain?worker_id=2", json={})

        assert resp.status_code == 200, resp.text
        assert sent["url"] == "http://192.168.1.30:8086/api/containers/honeygain/deploy"
        assert sent["headers"]["Authorization"] == "Bearer desk-key"
        assert sent["json"] == {"image": "test", "env": {}}

    def test_deploy_success(self, client):
        svc = {
            "slug": "honeygain",
            "name": "Honeygain",
            "docker": {
                "image": "honeygain/honeygain:latest",
                "env": [{"key": "EMAIL", "default": "user@test.com"}],
                "ports": ["8080:80/tcp"],
                "volumes": ["/data:/app/data"],
            },
        }
        worker = _online_worker()
        httpx_resp = _mock_httpx_resp(200, {"container_id": "abc123"})

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.return_value = httpx_resp

        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post("/api/deploy/honeygain", json={"env": {}, "hostname": "myhost"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "deployed"

    def test_divergent_redeploy_returns_the_kept_list_over_http(self, client):
        """CashPilot-23yb: the deploy response must survive FastAPI's response model.

        `kept_from_previous_deployment` is a list, and the route used to be
        annotated `-> dict[str, str]` — so the very deployments that had
        something to tell the user 500'd AFTER deploying and persisting, and a
        retry could deploy again. Exercised through HTTP because a direct call
        to the function bypasses response validation entirely.
        """
        svc = {
            "slug": "honeygain",
            "name": "Honeygain",
            "docker": {
                "image": "honeygain/honeygain:latest",
                "env": [{"key": "EMAIL", "default": "user@test.com"}],
                "ports": ["8080:80/tcp"],
                "volumes": ["/data:/app/data"],
            },
        }
        # The recorded container ran with a command the catalog no longer has:
        # the redeploy drops it and reports the divergence.
        recorded = {"image": "honeygain/honeygain:latest", "command": "--legacy-flag"}
        worker = _online_worker()

        async def _fake_deploy(worker_id, slug, spec):
            return {"container_id": "abc123"}

        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch(
                "app.main.database.get_deployment_spec",
                new_callable=AsyncMock,
                return_value=recorded,
            ),
            patch("app.main._proxy_worker_deploy", side_effect=_fake_deploy),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main._run_collection", new_callable=AsyncMock),
        ):
            resp = client.post("/api/deploy/honeygain", json={"env": {}})
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["status"] == "deployed"
            kept = data["kept_from_previous_deployment"]
            assert isinstance(kept, list) and kept
            assert any("command" in line for line in kept)

    def test_a_port_with_a_host_address_keeps_the_address(self, client):
        """'127.0.0.1:9980:9980' used to crash the deploy on int('127.0.0.1').

        A wallet dashboard (Sia hostd) must bind to loopback only, so the
        address has to reach the worker rather than be dropped or misread.
        """
        svc = {
            "slug": "sia-hostd",
            "name": "Sia (hostd)",
            "docker": {
                "image": "ghcr.io/siafoundation/hostd",
                "env": [],
                "ports": ["127.0.0.1:9980:9980", "9981:9981", "9984:9984/udp"],
            },
        }
        worker = _online_worker()
        sent = {}

        async def _fake_deploy(worker_id, slug, spec):
            sent.update(spec)
            return {"container_id": "abc123"}

        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main._proxy_worker_deploy", side_effect=_fake_deploy),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main._run_collection", new_callable=AsyncMock),
        ):
            resp = client.post("/api/deploy/sia-hostd", json={"env": {}})
        assert resp.status_code == 200, resp.text
        assert sent["ports"] == {
            "9980/tcp": ["127.0.0.1", 9980],
            "9981/tcp": 9981,
            "9984/udp": 9984,
        }

    def test_a_malformed_port_is_a_400_not_a_500(self, client):
        """The loader rejects these, but a 500 is the wrong answer if one slips by."""
        svc = {
            "slug": "x",
            "name": "X",
            "docker": {"image": "x/x", "env": [], "ports": [":9980"]},
        }
        worker = _online_worker()
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main._proxy_worker_deploy") as deploy,
        ):
            resp = client.post("/api/deploy/x", json={"env": {}})
        assert resp.status_code == 400, resp.text
        assert "':9980'" in resp.json()["detail"]
        deploy.assert_not_called()

    def test_plain_deploy_response_has_no_kept_key(self, client):
        # Negative control: without a recorded spec there is no divergence and
        # the key must be absent — the toast only fires when there is news.
        svc = {
            "slug": "honeygain",
            "name": "Honeygain",
            "docker": {"image": "honeygain/honeygain:latest", "env": []},
        }
        worker = _online_worker()

        async def _fake_deploy(worker_id, slug, spec):
            return {"container_id": "abc123"}

        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main._proxy_worker_deploy", side_effect=_fake_deploy),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main._run_collection", new_callable=AsyncMock),
        ):
            resp = client.post("/api/deploy/honeygain", json={"env": {}})
            assert resp.status_code == 200, resp.text
            assert "kept_from_previous_deployment" not in resp.json()

    def _deploy_with_worker_reply(self, client, svc, body, reply):
        """POST /api/deploy and return (response, spec sent to the worker, spec recorded)."""
        worker = _online_worker()
        sent = {}

        async def _fake_deploy(worker_id, slug, spec):
            sent.update(spec)
            return reply

        save = AsyncMock()
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main._proxy_worker_deploy", side_effect=_fake_deploy),
            patch("app.main.database.save_deployment", save),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main._run_collection", new_callable=AsyncMock),
        ):
            resp = client.post(f"/api/deploy/{svc['slug']}", json=body)
        return resp, sent, save.call_args.kwargs["spec"]

    def test_a_mount_the_worker_kept_is_reported_and_not_recorded(self, client):
        """Seen live: a redeploy moved a mysterium node onto another identity.

        The worker now keeps the running container's mounts and the operator
        hears about it. The kept source stays OUT of the record: the record is
        one row for the whole fleet, and a recorded host path is sent back on the
        next redeploy, where the worker's bind-path rules refuse it (403).
        """
        svc = {
            "slug": "mysterium",
            "name": "MystNodes",
            "docker": {"image": "mysteriumnetwork/myst", "volumes": ["mysterium-data:/var/lib/mysterium-node"]},
        }
        reply = {
            "container_id": "abc123",
            "kept_mounts": [{"target": "/var/lib/mysterium-node", "kept": "/srv/myst", "requested": "mysterium-data"}],
        }
        resp, sent, recorded = self._deploy_with_worker_reply(client, svc, {"env": {}}, reply)
        assert resp.status_code == 200, resp.text
        kept = resp.json()["kept_from_previous_deployment"]
        assert any("/srv/myst" in line and "mysterium-data" in line for line in kept)
        assert list(recorded["volumes"]) == ["mysterium-data"]
        assert sent["moved_mounts"] == []
        assert "moved_mounts" not in recorded

    @pytest.mark.parametrize("junk", [5, "kept", {"target": "x"}, [5, None, "x"]])
    def test_a_malformed_kept_list_cannot_fail_a_deploy_that_already_happened(self, client, junk):
        svc = {"slug": "honeygain", "name": "Honeygain", "docker": {"image": "honeygain/honeygain", "env": []}}
        resp, _, _ = self._deploy_with_worker_reply(
            client, svc, {"env": {}}, {"container_id": "abc123", "kept_mounts": junk}
        )
        assert resp.status_code == 200, resp.text
        assert "kept_from_previous_deployment" not in resp.json()

    def test_a_path_typed_this_deploy_is_sent_as_a_deliberate_move(self, client):
        svc = {
            "slug": "storj",
            "name": "Storj",
            "docker": {
                "image": "storjlabs/storagenode",
                "env": [{"key": "IDENTITY_DIR", "default": ""}, {"key": "STORAGE_DIR", "default": "/s"}],
                "volumes": ["${IDENTITY_DIR}:/app/identity", "${STORAGE_DIR}:/app/config"],
            },
        }
        resp, sent, _ = self._deploy_with_worker_reply(
            client, svc, {"env": {"IDENTITY_DIR": "/new/identity"}}, {"container_id": "abc123"}
        )
        assert resp.status_code == 200, resp.text
        assert sent["moved_mounts"] == ["/app/identity"]
        assert "kept_from_previous_deployment" not in resp.json()

    def test_the_form_posting_blanks_and_defaults_is_not_the_operator_typing(self, client):
        """The dashboard redeploys by posting the deploy form, every field included.

        An empty box must not erase the recorded credential, and a path still
        showing the catalog default must not count as relocating the mount.
        """
        svc = {
            "slug": "storj",
            "name": "Storj",
            "docker": {
                "image": "storjlabs/storagenode",
                "env": [
                    {"key": "WALLET", "default": ""},
                    {"key": "STORAGE_DIR", "default": "/mnt/storj"},
                ],
                "volumes": ["${STORAGE_DIR}:/app/config"],
            },
        }
        recorded = {
            "image": "storjlabs/storagenode",
            "env": {"WALLET": "0xrecorded", "STORAGE_DIR": "/mnt/disk7/storj"},
            "volumes": {"/mnt/disk7/storj": {"bind": "/app/config", "mode": "rw"}},
        }
        with patch("app.main.database.get_deployment_spec", new_callable=AsyncMock, return_value=recorded):
            resp, sent, _ = self._deploy_with_worker_reply(
                client, svc, {"env": {"WALLET": "", "STORAGE_DIR": "/mnt/storj"}}, {"container_id": "abc123"}
            )
        assert resp.status_code == 200, resp.text
        assert sent["env"]["WALLET"] == "0xrecorded"
        assert list(sent["volumes"]) == ["/mnt/disk7/storj"]
        assert sent["moved_mounts"] == []

    def test_a_new_path_typed_into_the_form_still_moves_the_mount(self, client):
        """Control for the test above: a real decision is still honoured."""
        svc = {
            "slug": "storj",
            "name": "Storj",
            "docker": {
                "image": "storjlabs/storagenode",
                "env": [{"key": "STORAGE_DIR", "default": "/mnt/storj"}],
                "volumes": ["${STORAGE_DIR}:/app/config"],
            },
        }
        recorded = {
            "image": "storjlabs/storagenode",
            "env": {"STORAGE_DIR": "/mnt/disk7/storj"},
            "volumes": {"/mnt/disk7/storj": {"bind": "/app/config", "mode": "rw"}},
        }
        with patch("app.main.database.get_deployment_spec", new_callable=AsyncMock, return_value=recorded):
            resp, sent, _ = self._deploy_with_worker_reply(
                client, svc, {"env": {"STORAGE_DIR": "/mnt/disk9/storj"}}, {"container_id": "abc123"}
            )
        assert resp.status_code == 200, resp.text
        assert list(sent["volumes"]) == ["/mnt/disk9/storj"]
        assert sent["moved_mounts"] == ["/app/config"]

    def test_a_blank_box_does_not_erase_the_default_on_a_first_deploy(self, client):
        """The form shows {hostname} templates as a placeholder and posts "" for them."""
        svc = {
            "slug": "honeygain",
            "name": "Honeygain",
            "docker": {
                "image": "honeygain/honeygain",
                "env": [{"key": "DEVICE", "default": "cashpilot-{hostname}"}, {"key": "EMAIL", "default": ""}],
            },
        }
        resp, sent, _ = self._deploy_with_worker_reply(
            client, svc, {"env": {"DEVICE": "", "EMAIL": " me@example.com "}, "hostname": "nas"}, {"container_id": "x"}
        )
        assert resp.status_code == 200, resp.text
        assert sent["env"]["DEVICE"] == "cashpilot-nas"
        assert sent["env"]["EMAIL"] == "me@example.com"

    def test_trailing_whitespace_is_not_a_new_path(self, client):
        svc = {
            "slug": "storj",
            "name": "Storj",
            "docker": {
                "image": "storjlabs/storagenode",
                "env": [{"key": "STORAGE_DIR", "default": "/mnt/storj"}],
                "volumes": ["${STORAGE_DIR}:/app/config"],
            },
        }
        resp, sent, _ = self._deploy_with_worker_reply(
            client, svc, {"env": {"STORAGE_DIR": "/mnt/storj "}}, {"container_id": "x"}
        )
        assert resp.status_code == 200, resp.text
        assert sent["moved_mounts"] == []
        assert list(sent["volumes"]) == ["/mnt/storj"]

    @pytest.mark.parametrize(("declared", "expected"), [(300, 360 + 120), (None, 90 + 120), ("junk", 90 + 120)])
    def test_the_deploy_wait_covers_the_old_containers_clean_stop(self, declared, expected):
        """The worker stops the old container with this timeout before replacing it, and may
        then wait START_SETTLE_SECONDS (120) for a start Docker was slow to answer."""
        import asyncio

        from app import main

        svc = {"slug": "storj", "docker": {"image": "i", "stop_timeout": declared}}
        proxy = AsyncMock(return_value={})
        with patch("app.main.catalog.get_service", return_value=svc), patch("app.main._proxy_to_worker", proxy):
            asyncio.run(main._proxy_worker_deploy(1, "storj", {}))
        assert proxy.call_args.kwargs["timeout"] == expected

    @pytest.mark.real_worker_deploy_inventory
    @pytest.mark.parametrize("approve", [False, True], ids=["first-deploy", "approved-redeploy"])
    def test_dashboard_forwards_the_expected_container_only_for_this_request(self, client, approve):
        worker = _online_worker()
        slug = "demo"
        svc = {"slug": slug, "docker": {"image": "img"}}
        save = AsyncMock()
        expected = "a" * 64 if approve else "none"
        send = AsyncMock(side_effect=[{"expected_container": expected}, {"container_id": "new"}])
        body = {"expected_containers": {"1": expected}} if approve else {}
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", AsyncMock(return_value=[worker])),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main._proxy_to_worker", send),
            patch("app.main.database.prior_deployment_spec", AsyncMock(return_value=None)),
            patch("app.main.database.save_deployment", save),
            patch("app.main.database.record_health_event", AsyncMock()),
            patch("app.main._run_collection", AsyncMock()),
        ):
            resp = client.post(f"/api/deploy/{slug}", json=body)
        assert resp.status_code == 200, resp.text
        assert [call.args for call in send.await_args_list] == [
            (1, "GET", "/api/containers/demo/deploy-checked"),
            (1, "POST", "/api/containers/demo/deploy-checked"),
        ]
        assert send.call_args.kwargs["json"]["expected_container"] == expected
        assert "expected_container" not in save.call_args.kwargs["spec"]

    @pytest.mark.real_worker_deploy_inventory
    @pytest.mark.parametrize("imported", [False, True], ids=["dashboard", "import"])
    def test_old_worker_always_checks_live_inventory_before_a_replacement(self, client, imported):
        from fastapi import HTTPException

        slug = "demo"
        worker = _online_worker()
        svc = {"slug": slug, "docker": {"image": "img"}}
        current = None
        sent = []
        first, second = "a" * 64, "b" * 64

        async def worker_call(worker_id, method, path, *, json=None, **kwargs):
            nonlocal current
            if method == "POST":
                sent.append(json)
                current = first if current is None else second
                return {"container_id": current}
            if path.endswith("deploy-checked"):
                raise HTTPException(404)
            if path.endswith("/logs"):
                if current is None:
                    raise HTTPException(404, f"Container for {slug} not found")
                return {"logs": ""}
            assert path == "/api/containers"
            return [{"slug": slug, "container_id": current[:12]}]

        path = f"/api/import/drafts/{slug}/deploy" if imported else f"/api/deploy/{slug}"
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", AsyncMock(return_value=[worker])),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.importers_router.draft_env", AsyncMock(return_value={})),
            patch("app.main._proxy_to_worker", side_effect=worker_call),
            patch("app.main.database.save_deployment", AsyncMock()),
            patch("app.main.database.record_health_event", AsyncMock()),
            patch("app.main._run_collection", AsyncMock()),
        ):
            assert client.post(path, json={}).status_code == 200
            refused = client.post(path, json={})
            assert refused.status_code == 409
            detail = refused.json()["detail"]
            assert "Update this worker" in detail["message"]
            assert "container IDs this worker last reported" in detail["message"]
            assert "could replace a different container" in detail["message"]
            assert detail["expected_containers"] == {"1": first[:12]}
            assert current == first and len(sent) == 1

            approved = {"expected_containers": detail["expected_containers"]}
            assert client.post(path, json=approved).status_code == 200
            assert client.post(path, json=approved).status_code == 409
            assert current == second and len(sent) == 2

    def test_deploy_service_not_found(self, client):
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[_online_worker()]),
            patch("app.main.catalog.get_service", return_value=None),
        ):
            resp = client.post("/api/deploy/nope", json={})
            assert resp.status_code == 404

    def test_deploy_no_image(self, client):
        svc = {"slug": "grass", "name": "Grass", "docker": {}}
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[_online_worker()]),
            patch("app.main.catalog.get_service", return_value=svc),
        ):
            resp = client.post("/api/deploy/grass", json={})
            assert resp.status_code == 400

    def test_deploy_dead_service(self, client):
        svc = {"slug": "peer2profit", "name": "Peer2Profit", "status": "dead", "docker": {"image": "x"}}
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[_online_worker()]),
            patch("app.main.catalog.get_service", return_value=svc),
        ):
            resp = client.post("/api/deploy/peer2profit", json={})
            assert resp.status_code == 410
            assert "no longer available" in resp.json()["detail"]

    def test_deploy_broken_service_refused(self, client):
        # The catalog listing already hides broken services; the deploy gate used to
        # let them through, so a direct link or stale page could still deploy one.
        svc = {"slug": "speedshare", "name": "SpeedShare", "status": "broken", "docker": {"image": "x"}}
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[_online_worker()]),
            patch("app.main.catalog.get_service", return_value=svc),
        ):
            resp = client.post("/api/deploy/speedshare", json={})
            assert resp.status_code == 409  # broken may come back; not "gone"
            assert "broken" in resp.json()["detail"]

    def test_deploy_dropped_service_refused(self, client):
        svc = {"slug": "gone", "name": "Gone", "status": "dropped", "docker": {"image": "x"}}
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[_online_worker()]),
            patch("app.main.catalog.get_service", return_value=svc),
        ):
            resp = client.post("/api/deploy/gone", json={})
            assert resp.status_code == 410
            assert "dropped" in resp.json()["detail"]

    def test_deploy_no_auth(self, client):
        with _no_auth():
            resp = client.post("/api/deploy/honeygain", json={})
            assert resp.status_code == 401

    def test_deploy_repocket_emits_rp_env_keys(self, client, deploy_capture):
        """#82 guard at the deploy layer: the real repocket catalog entry must
        produce RP_EMAIL/RP_API_KEY in the container spec sent to the worker.

        Uses the real catalog (no get_service mock), so a future regression that
        renames the YAML keys OR a refactor of api_deploy that mangles env names
        is caught independently of the catalog-level test.
        """
        captured, capture = deploy_capture

        # Reload the real catalog from disk so this test is independent of any
        # earlier test that swapped SERVICES_DIR and left the cache polluted.
        from app import catalog

        catalog.load_services()

        with (
            _auth_owner(),
            patch("app.main._resolve_worker_id", new_callable=AsyncMock, return_value=1),
            patch("app.main._proxy_worker_deploy", side_effect=capture),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.post(
                "/api/deploy/repocket",
                json={"env": {"RP_EMAIL": "me@example.com", "RP_API_KEY": "12345678-1234-4abc-8def-123456789abc"}},
            )
            assert resp.status_code == 200, resp.text
            spec_env = captured["spec"]["env"]
            assert set(spec_env) == {"RP_EMAIL", "RP_API_KEY"}, (
                f"repocket container spec must carry exactly RP_EMAIL + RP_API_KEY, got {set(spec_env)}"
            )
            assert spec_env["RP_API_KEY"] == "12345678-1234-4abc-8def-123456789abc"
            assert spec_env["RP_EMAIL"] == "me@example.com"

    @pytest.mark.parametrize(
        "key",
        ["account-password", "12345678-1234-1abc-8def-123456789abc", "12345678-1234-4abc-7def-123456789abc"],
    )
    @pytest.mark.parametrize("recorded", [False, True])
    def test_repocket_rejects_invalid_key_before_worker_call(self, client, key, recorded):
        """Reject invalid submitted or recorded keys without exposing them or contacting the worker."""
        from app import catalog

        catalog.load_services()
        previous = {"env": {"RP_EMAIL": "me@example.com", "RP_API_KEY": key}} if recorded else None
        posted = {} if recorded else {"RP_EMAIL": "me@example.com", "RP_API_KEY": key}
        with (
            _auth_owner(),
            patch("app.main._resolve_worker_id", new_callable=AsyncMock, return_value=1),
            patch("app.main.database.get_deployment_spec", new_callable=AsyncMock, return_value=previous),
            patch("app.main._proxy_worker_deploy", new_callable=AsyncMock) as deploy,
            patch("app.main.database.save_deployment", new_callable=AsyncMock) as save,
        ):
            resp = client.post("/api/deploy/repocket", json={"env": posted})
        assert resp.status_code == 400, resp.text
        assert "UUIDv4" in resp.json()["detail"]
        assert key not in resp.text
        deploy.assert_not_awaited()
        save.assert_not_awaited()

    @pytest.mark.parametrize("replace", [False, True])
    def test_repocket_redeploy_preserves_or_corrects_key(self, client, deploy_capture, replace):
        """Preserve a valid saved UUIDv4 key or replace an old password with a trimmed valid key."""
        from app import catalog

        catalog.load_services()
        valid = "12345678-1234-4ABC-BDEF-123456789ABC"
        previous = {"env": {"RP_EMAIL": "me@example.com", "RP_API_KEY": "old-password" if replace else valid}}
        captured, capture = deploy_capture
        with (
            _auth_owner(),
            patch("app.main._resolve_worker_id", new_callable=AsyncMock, return_value=1),
            patch("app.main.database.get_deployment_spec", new_callable=AsyncMock, return_value=previous),
            patch("app.main._proxy_worker_deploy", side_effect=capture),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.post("/api/deploy/repocket", json={"env": {"RP_API_KEY": f" {valid} " if replace else ""}})
        assert resp.status_code == 200, resp.text
        assert captured["spec"]["env"] == {"RP_EMAIL": "me@example.com", "RP_API_KEY": valid}

    def test_deploy_forwards_resources_from_yaml(self, client, deploy_capture):
        """A resources block in the service YAML must reach the worker spec."""
        captured, capture = deploy_capture

        svc = {
            "slug": "storj",
            "name": "Storj",
            "docker": {
                "image": "storjlabs/storagenode",
                "env": [],
                "ports": [],
                "volumes": [],
                "resources": {"mem_limit": "2g", "oom_score_adj": -100},
            },
        }
        with (
            _auth_owner(),
            patch("app.main._resolve_worker_id", new_callable=AsyncMock, return_value=1),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main._proxy_worker_deploy", side_effect=capture),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.post("/api/deploy/storj", json={})
            assert resp.status_code == 200, resp.text
            assert captured["spec"]["resources"] == {"mem_limit": "2g", "oom_score_adj": -100}

    def test_deploy_omits_resources_when_absent(self, client, deploy_capture):
        """A service YAML without a resources block must not add one to the spec."""
        captured, capture = deploy_capture

        svc = {
            "slug": "nores",
            "name": "NoRes",
            "docker": {"image": "x", "env": [], "ports": [], "volumes": []},
        }
        with (
            _auth_owner(),
            patch("app.main._resolve_worker_id", new_callable=AsyncMock, return_value=1),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main._proxy_worker_deploy", side_effect=capture),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.post("/api/deploy/nores", json={})
            assert resp.status_code == 200, resp.text
            assert "resources" not in captured["spec"]

    def test_deploy_storj_real_catalog_carries_resources(self, client, deploy_capture):
        """Guard: the real storj YAML resources must reach the container spec.

        Uses the real catalog (no get_service mock) so a rename of the YAML
        `resources` keys is caught independently of the schema-level test.
        """
        captured, capture = deploy_capture

        from app import catalog

        catalog.load_services()

        with (
            _auth_owner(),
            patch("app.main._resolve_worker_id", new_callable=AsyncMock, return_value=1),
            patch("app.main._proxy_worker_deploy", side_effect=capture),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.post(
                "/api/deploy/storj",
                json={
                    "env": {
                        "WALLET": "0xabc",
                        "EMAIL": "a@b.com",
                        "ADDRESS": "1.2.3.4:28967",
                        "STORAGE": "2TB",
                        "IDENTITY_DIR": "/mnt/id",
                        "STORAGE_DIR": "/mnt/data",
                    }
                },
            )
            assert resp.status_code == 200, resp.text
            assert captured["spec"]["resources"] == {
                "mem_limit": "2g",
                "oom_score_adj": -100,
                # 4096, not 2048: older runc maps shares below ~2600 UNDER the
                # unset cgroup-v2 default weight — see _schema.yml.
                "cpu_shares": 4096,
            }

    def test_deploy_proxybase_real_catalog_passes_credentials_as_arguments(self, client, deploy_capture):
        """Guard for issue #343: the peer client reads ONLY positional arguments.

        Its own error text offers "environment variables ID and NAME", but no
        published image honors them (verified live against the pinned digest
        and tag v2.0.3): an env-only container loops on "Missing ID and NAME"
        while showing as running. The catalog command must therefore reach the
        worker spec with both values substituted — if a catalog rewrite drops
        the command line again (the 2026-07-17 fix shipped without it), this
        goes red.
        """
        captured, capture = deploy_capture

        from app import catalog

        catalog.load_services()

        with (
            _auth_owner(),
            patch("app.main._resolve_worker_id", new_callable=AsyncMock, return_value=1),
            patch("app.main._proxy_worker_deploy", side_effect=capture),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            # No ledger table here; the hold written before the worker call is
            # tested in test_identity_ledger, and a failed one refuses the deploy.
            patch("app.main.database.hold_pending_identities", new_callable=AsyncMock, return_value="u1"),
            patch("app.main.database.release_pending_identities", new_callable=AsyncMock),
        ):
            resp = client.post(
                "/api/deploy/proxybase",
                json={"env": {"ID": "tok123", "NAME": "mydev"}},
            )
            assert resp.status_code == 200, resp.text
            assert captured["spec"]["command"] == "tok123 mydev"

    def test_deploy_bitping_real_catalog_requires_credentials(self, client, deploy_capture):
        """Guard for issue #341: bitping must not deploy credential-less.

        The 2026-03-28 catalog rewrite dropped BITPING_EMAIL/BITPING_PASSWORD
        while the guide and the image kept supporting them, so every deploy
        for months shipped a node that sat at "No active session" earning
        nothing. With the env block restored, an empty deploy is rejected up
        front; if the block is ever dropped again, the empty deploy succeeds
        and this goes red.
        """
        captured, capture = deploy_capture

        from app import catalog

        catalog.load_services()

        with (
            _auth_owner(),
            patch("app.main._resolve_worker_id", new_callable=AsyncMock, return_value=1),
            patch("app.main._proxy_worker_deploy", side_effect=capture),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.post("/api/deploy/bitping", json={"env": {}})
            assert resp.status_code == 400
            assert "Email" in resp.json()["detail"]
            assert "Password" in resp.json()["detail"]

            resp = client.post(
                "/api/deploy/bitping",
                json={"env": {"BITPING_EMAIL": "a@b.c", "BITPING_PASSWORD": "pw"}},
            )
            assert resp.status_code == 200, resp.text
            assert captured["spec"]["env"]["BITPING_EMAIL"] == "a@b.c"
            assert captured["spec"]["env"]["BITPING_PASSWORD"] == "pw"

    def test_deploy_urnetwork_real_catalog_authenticates_via_auth_provide(self, client, deploy_capture):
        """Guard for issue #344: the provider binary reads NO environment variables.

        The retired UR_AUTH_TOKEN spec deployed containers that simply ran
        unauthenticated. The working contract (the binary's own --help, verified
        live) is the auth-provide subcommand with the account credentials as
        arguments — so the substituted command must reach the worker spec, and a
        credential-less deploy must be rejected up front.
        """
        captured, capture = deploy_capture

        from app import catalog

        catalog.load_services()

        with (
            _auth_owner(),
            patch("app.main._resolve_worker_id", new_callable=AsyncMock, return_value=1),
            patch("app.main._proxy_worker_deploy", side_effect=capture),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.post("/api/deploy/urnetwork", json={"env": {}})
            assert resp.status_code == 400
            assert "Email" in resp.json()["detail"]
            assert "Password" in resp.json()["detail"]

            resp = client.post(
                "/api/deploy/urnetwork",
                json={"env": {"UR_USER_AUTH": "a@b.c", "UR_PASSWORD": "pw"}},
            )
            assert resp.status_code == 200, resp.text
            assert captured["spec"]["command"] == "auth-provide --user_auth=a@b.c --password=pw"


# ---------------------------------------------------------------------------
# Stop / Restart / Start / Remove (service management routes)
# ---------------------------------------------------------------------------


class TestServiceManagement:
    def _setup_proxy(self):
        """Common setup for proxy tests: single online worker, mock httpx."""
        worker = _online_worker()
        httpx_resp = _mock_httpx_resp(200, {"status": "ok"})

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.return_value = httpx_resp
        mock_client.delete.return_value = httpx_resp

        return worker, mock_client

    def test_restart_service(self, client):
        worker, mock_client = self._setup_proxy()
        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post("/api/services/honeygain/restart")
            assert resp.status_code == 200

    def test_stop_service(self, client):
        worker, mock_client = self._setup_proxy()
        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post("/api/services/honeygain/stop")
            assert resp.status_code == 200

    def test_stop_on_a_desktop_that_takes_commands_sends_its_own_key(self, client):
        _, mock_client = self._setup_proxy()
        desktop = {
            **_online_worker(2, url="http://192.168.1.30:8086"),
            "client_id": "desk",
            "system_info": json.dumps({"device_type": "desktop"}),
        }
        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=desktop),
            patch("app.main.database.get_worker_key_state", new_callable=AsyncMock, return_value=("desk-key", True)),
            patch("app.main._validate_worker_url", return_value=("http://192.168.1.30:8086", None)),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post("/api/services/honeygain/stop?worker_id=2")
        assert resp.status_code == 200, resp.text
        assert mock_client.post.call_args.args[0] == "http://192.168.1.30:8086/api/containers/honeygain/stop"
        assert mock_client.post.call_args.kwargs["headers"]["Authorization"] == "Bearer desk-key"

    def test_a_desktop_is_not_offered_the_docker_update(self, client):
        desktop = {
            **_online_worker(2, url="http://192.168.1.30:8086"),
            "system_info": json.dumps({"device_type": "desktop"}),
        }
        send = AsyncMock()
        with (
            _auth_owner(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=desktop),
            patch("app.main._proxy_to_worker", send),
        ):
            info = client.get("/api/update-info?worker_id=2")
            update = client.post("/api/update?worker_id=2")
        assert info.status_code == 409 and update.status_code == 409, (info.text, update.text)
        assert "updates itself from its own app" in info.json()["detail"]
        send.assert_not_awaited()

    def test_start_service(self, client):
        worker, mock_client = self._setup_proxy()
        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post("/api/services/honeygain/start")
            assert resp.status_code == 200

    @pytest.mark.parametrize(
        ("path", "answer"),
        [
            (
                "/api/services/honeygain/start",
                {"status": "started", "exit": {"ip": "93.184.215.14"}, "durable": False, "warning": "w"},
            ),
            ("/api/services/honeygain/restart", {"status": "started", "exit": {"ip": "93.184.215.14"}}),
            ("/api/services/honeygain/stop", {"status": "stopped", "was_running": True, "durable": False}),
            ("/api/restart/honeygain", {"status": "started", "exit": {"ip": "93.184.215.14"}}),
            ("/api/stop/honeygain", {"status": "stopped", "was_running": True}),
        ],
    )
    def test_a_routed_service_answers_its_copys_reply(self, client, path, answer):
        """A routed service's command returns the worker's proxied answer, whose ``exit`` is a dict and whose
        ``was_running`` and ``durable`` are booleans: a ``dict[str, str]`` response model turned every one into a
        500 after the worker had done it."""
        with (
            _auth_writer(),
            patch("app.main._resolve_worker_id", new_callable=AsyncMock, return_value=1),
            patch("app.main._or_routed", new_callable=AsyncMock, return_value=answer),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.post(path)
        assert resp.status_code == 200, resp.text
        assert resp.json() == answer

    def test_remove_service(self, client):
        worker, mock_client = self._setup_proxy()
        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.remove_deployment", new_callable=AsyncMock),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.delete("/api/services/honeygain")
            assert resp.status_code == 200

    def test_service_logs(self, client):
        worker = _online_worker()
        httpx_resp = _mock_httpx_resp(200, {"logs": "log content"})
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get.return_value = httpx_resp

        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.get("/api/services/honeygain/logs?lines=50")
            assert resp.status_code == 200

    def test_old_stop_route(self, client):
        """Test the legacy /api/stop/{slug} route."""
        worker, mock_client = self._setup_proxy()
        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.post("/api/stop/honeygain")
            assert resp.status_code == 200

    def test_old_restart_route(self, client):
        worker, mock_client = self._setup_proxy()
        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.post("/api/restart/honeygain")
            assert resp.status_code == 200

    def test_old_remove_route(self, client):
        worker, mock_client = self._setup_proxy()
        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.remove_deployment", new_callable=AsyncMock),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.delete("/api/remove/honeygain")
            assert resp.status_code == 200

    def test_remove_with_delete_volumes(self, client):
        worker, mock_client = self._setup_proxy()
        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.remove_deployment", new_callable=AsyncMock),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
        ):
            resp = client.delete("/api/services/honeygain?delete_volumes=true")
            assert resp.status_code == 200
            assert mock_client.delete.call_args.kwargs["params"] == {"delete_volumes": "true"}


# ---------------------------------------------------------------------------
# Worker proxy error handling
# ---------------------------------------------------------------------------


class TestProxyErrors:
    def test_proxy_worker_error_response(self, client):
        worker = _online_worker()
        error_resp = _mock_httpx_resp(500, {"detail": "Docker error"})

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.return_value = error_resp

        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post("/api/services/honeygain/restart")
            assert resp.status_code == 500

    def test_proxy_worker_httpx_error(self, client):
        worker = _online_worker()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")

        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post("/api/services/honeygain/restart")
            assert resp.status_code == 503

    def test_proxy_worker_offline(self, client):
        worker = {"id": 1, "name": "w1", "status": "offline", "url": "http://192.168.1.10:8081"}
        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
        ):
            resp = client.post("/api/services/honeygain/restart?worker_id=1")
            assert resp.status_code == 503

    def test_proxy_worker_not_found(self, client):
        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=None),
        ):
            resp = client.post("/api/services/honeygain/restart?worker_id=99")
            assert resp.status_code == 404

    def test_proxy_worker_no_url(self, client):
        worker = {"id": 1, "name": "w1", "status": "online", "url": ""}
        with (
            _auth_writer(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
        ):
            resp = client.post("/api/services/honeygain/restart?worker_id=1")
            assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Worker command proxy route
# ---------------------------------------------------------------------------


class TestWorkerCommand:
    def _setup(self):
        worker = _online_worker()
        httpx_resp = _mock_httpx_resp(200, {"status": "ok"})
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.return_value = httpx_resp
        mock_client.delete.return_value = httpx_resp
        return worker, mock_client

    def test_command_deploy(self, client):
        # Deploy via the command route is OWNER-gated (matching /api/deploy/{slug}),
        # so it must not be reachable with a mere writer role — use owner here.
        worker, mock_client = self._setup()
        with (
            _auth_owner(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.save_deployment", new_callable=AsyncMock) as save_dep,
            patch("app.main.database.record_health_event", new_callable=AsyncMock) as health_evt,
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post(
                "/api/workers/1/command",
                json={
                    "command": "deploy",
                    "slug": "honeygain",
                    "spec": {"image": "test"},
                },
            )
            assert resp.status_code == 200
            # The bug fix: a deploy via the command route must record the deployment
            # (so it starts earning) and a "start" health event — not silently skip both.
            save_dep.assert_awaited_once()
            health_evt.assert_awaited()

    def test_raw_deploy_forwards_approval_without_saving_it(self, client):
        worker, mock_client = self._setup()
        with (
            _auth_owner(),
            patch("app.main.database.get_worker", AsyncMock(return_value=worker)),
            patch("app.main.database.save_deployment", AsyncMock()) as save,
            patch("app.main.database.record_health_event", AsyncMock()),
            patch("app.main._run_collection", AsyncMock()),
            patch("app.main._worker_deploy_target", AsyncMock(return_value=("none", True))),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            response = client.post(
                "/api/workers/1/command",
                json={
                    "command": "deploy",
                    "slug": "honeygain",
                    "spec": {"image": "test", "expected_container": "a" * 64},
                },
            )
        assert response.status_code == 200, response.text
        assert mock_client.post.call_args.kwargs["json"]["expected_container"] == "a" * 64
        assert "expected_container" not in save.call_args.kwargs["spec"]

    def test_command_deploy_writer_denied(self, client):
        """A writer must NOT be able to deploy via /api/workers/{id}/command — deploy is
        owner-only, so this route must not become an owner-gate bypass (writer stays
        allowed for stop/restart/remove, tested separately)."""
        worker, mock_client = self._setup()
        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post(
                "/api/workers/1/command",
                json={"command": "deploy", "slug": "honeygain", "spec": {"image": "test"}},
            )
            assert resp.status_code == 403

    def test_command_stop(self, client):
        worker, mock_client = self._setup()
        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.record_health_event", new_callable=AsyncMock) as health_evt,
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post(
                "/api/workers/1/command",
                json={
                    "command": "stop",
                    "slug": "honeygain",
                },
            )
            assert resp.status_code == 200
            health_evt.assert_awaited_once()

    def test_command_remove(self, client):
        worker, mock_client = self._setup()
        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.remove_deployment", new_callable=AsyncMock) as rm_dep,
            patch("app.main.database.delete_proxied_copies_of", new_callable=AsyncMock) as rm_copies,
            patch("app.main.database.record_health_event", new_callable=AsyncMock) as health_evt,
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post(
                "/api/workers/1/command",
                json={
                    "command": "remove",
                    "slug": "honeygain",
                },
            )
            assert resp.status_code == 200
            # A remove via the command route must clean up the deployments row,
            # and, as in _svc_remove, the records of the proxied copies the worker removed.
            rm_dep.assert_awaited_once()
            rm_copies.assert_awaited_once_with(1, "honeygain")
            health_evt.assert_awaited()

    def test_command_remove_keeps_the_records_of_proxied_copies_that_survived(self, client):
        worker, mock_client = self._setup()
        mock_client.delete.return_value = _mock_httpx_resp(200, {"status": "ok", "proxied_error": "p4 left"})
        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.remove_deployment", new_callable=AsyncMock),
            patch("app.main.database.delete_proxied_copies_of", new_callable=AsyncMock) as rm_copies,
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post("/api/workers/1/command", json={"command": "remove", "slug": "honeygain"})
            assert resp.status_code == 200
            rm_copies.assert_not_awaited()

    def test_command_remove_that_cannot_drop_the_copy_records_still_reports_success(self, client):
        worker, mock_client = self._setup()
        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.remove_deployment", new_callable=AsyncMock),
            patch("app.main.database.delete_proxied_copies_of", new_callable=AsyncMock, side_effect=OSError("locked")),
            patch("app.main.database.record_health_event", new_callable=AsyncMock) as health_evt,
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post("/api/workers/1/command", json={"command": "remove", "slug": "honeygain"})
            assert resp.status_code == 200
            health_evt.assert_awaited()

    def test_command_restart(self, client):
        worker, mock_client = self._setup()
        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.record_health_event", new_callable=AsyncMock) as health_evt,
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post(
                "/api/workers/1/command",
                json={"command": "restart", "slug": "honeygain"},
            )
            assert resp.status_code == 200
            health_evt.assert_awaited_once()

    def test_command_start(self, client):
        worker, mock_client = self._setup()
        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.record_health_event", new_callable=AsyncMock) as health_evt,
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post(
                "/api/workers/1/command",
                json={"command": "start", "slug": "honeygain"},
            )
            assert resp.status_code == 200
            health_evt.assert_awaited_once()

    def test_command_deploy_refuses_broken_service(self, client):
        """The raw worker-command route is a THIRD deploy path.

        It proxies straight to the worker and then runs the full bookkeeping, so
        without the same status gate a broken service would look deployed while
        earning nothing — the exact drift the shared constant exists to prevent.
        """
        worker, mock_client = self._setup()
        svc = {"slug": "speedshare", "name": "SpeedShare", "status": "broken", "docker": {"image": "x"}}
        with (
            _auth_owner(),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post(
                "/api/workers/1/command",
                json={"command": "deploy", "slug": "speedshare", "spec": {"image": "x"}},
            )
            assert resp.status_code == 409
        # Refused before the worker was ever contacted.
        mock_client.post.assert_not_called()

    def test_command_stop_still_allowed_for_broken_service(self, client):
        # You must still be able to STOP a running service that has since been
        # marked broken — only deploy is gated.
        worker, mock_client = self._setup()
        svc = {"slug": "speedshare", "name": "SpeedShare", "status": "broken", "docker": {"image": "x"}}
        with (
            _auth_writer(),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post("/api/workers/1/command", json={"command": "stop", "slug": "speedshare"})
            assert resp.status_code == 200
        # A 200 alone would also pass if the route silently did nothing, so assert
        # the stop actually reached the worker at the right path.
        assert mock_client.post.call_count == 1
        assert mock_client.post.call_args.args[0].endswith("/api/containers/speedshare/stop")

    def test_command_unknown(self, client):
        worker, mock_client = self._setup()
        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post(
                "/api/workers/1/command",
                json={
                    "command": "nuke",
                    "slug": "honeygain",
                },
            )
            assert resp.status_code == 400

    def test_command_worker_offline(self, client):
        worker = {"id": 1, "name": "w1", "status": "offline", "url": "http://192.168.1.10:8081"}
        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
        ):
            resp = client.post(
                "/api/workers/1/command",
                json={
                    "command": "stop",
                    "slug": "honeygain",
                },
            )
            assert resp.status_code == 503

    def test_command_worker_not_found(self, client):
        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=None),
        ):
            resp = client.post(
                "/api/workers/99/command",
                json={
                    "command": "stop",
                    "slug": "honeygain",
                },
            )
            assert resp.status_code == 404

    def test_command_httpx_error(self, client):
        worker = _online_worker()
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("refused")

        with (
            _auth_writer(),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.httpx.AsyncClient", return_value=mock_client),
            patch("app.main.FLEET_API_KEY", "test-key"),
        ):
            resp = client.post(
                "/api/workers/1/command",
                json={
                    "command": "restart",
                    "slug": "honeygain",
                },
            )
            assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Deployed services aggregation (multi-node)
# ---------------------------------------------------------------------------


class TestDeployedServicesAggregation:
    def test_aggregation_with_workers_and_earnings(self, client):
        workers = [
            {
                "id": 1,
                "name": "w1",
                "status": "online",
                "system_info": json.dumps({"docker_available": True}),
                "containers": json.dumps(
                    [
                        {
                            "slug": "honeygain",
                            "name": "hg",
                            "status": "running",
                            "image": "hg:latest",
                            "cpu_percent": 1.5,
                            "memory_mb": 50,
                        },
                    ]
                ),
                "apps": "[]",
            }
        ]
        earnings = [{"platform": "honeygain", "balance": 5.0, "currency": "USD"}]
        health = [{"slug": "honeygain", "score": 95, "uptime_pct": 99, "restarts": 0}]
        svc = {
            "name": "Honeygain",
            "category": "bandwidth",
            "cashout": {"min_amount": 20},
            "referral": {"signup_url": "https://r.hg.com"},
            "website": "https://honeygain.com",
        }

        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=earnings),
            patch("app.main.database.get_health_scores", new_callable=AsyncMock, return_value=health),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
            patch("app.main.catalog.get_service", return_value=svc),
        ):
            resp = client.get("/api/services/deployed")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["slug"] == "honeygain"
            assert data[0]["balance"] == 5.0
            assert data[0]["instances"] == 1
            assert len(data[0]["instance_details"]) == 1

    def test_multi_node_aggregation(self, client):
        workers = [
            {
                "id": 1,
                "name": "w1",
                "status": "online",
                "system_info": json.dumps({"docker_available": True}),
                "containers": json.dumps(
                    [
                        {
                            "slug": "honeygain",
                            "name": "hg-1",
                            "status": "running",
                            "image": "hg:latest",
                            "cpu_percent": 1.0,
                            "memory_mb": 30,
                        },
                    ]
                ),
                "apps": "[]",
            },
            {
                "id": 2,
                "name": "w2",
                "status": "online",
                "system_info": json.dumps({"docker_available": True}),
                "containers": json.dumps(
                    [
                        {
                            "slug": "honeygain",
                            "name": "hg-2",
                            "status": "running",
                            "image": "hg:latest",
                            "cpu_percent": 2.0,
                            "memory_mb": 40,
                        },
                    ]
                ),
                "apps": "[]",
            },
        ]
        svc = {"name": "Honeygain", "category": "bandwidth"}

        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=workers),
            patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_health_scores", new_callable=AsyncMock, return_value=[]),
            patch("app.main.database.get_deployments", new_callable=AsyncMock, return_value=[]),
            patch("app.main.catalog.get_service", return_value=svc),
        ):
            resp = client.get("/api/services/deployed")
            data = resp.json()
            assert len(data) == 1
            assert data[0]["instances"] == 2
            assert float(data[0]["cpu"].rstrip("%")) == 3.0


# ---------------------------------------------------------------------------
# Earnings summary with non-USD and bonuses
# ---------------------------------------------------------------------------


class TestEarningsSummaryAdvanced:
    def test_earnings_summary_with_non_usd(self, client):
        summary = {"total": 0.0, "today": 0.0, "month": 0.0, "today_change": 0.0}
        earnings = [
            {"platform": "grass", "balance": 100.0, "currency": "GRASS"},
        ]
        with (
            _auth_owner(),
            patch("app.main.database.get_earnings_dashboard_summary", new_callable=AsyncMock, return_value=summary),
            patch("app.main.database.get_config", new_callable=AsyncMock, return_value={}),
            patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=earnings),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[]),
            patch("app.main.exchange_rates.to_usd", return_value=0.50),
        ):
            resp = client.get("/api/earnings/summary")
            assert resp.status_code == 200

    def test_earnings_summary_with_bonus(self, client):
        summary = {"total": 10.0, "today": 1.0, "month": 5.0, "today_change": 0.5}
        earnings = [
            {"platform": "honeygain", "balance": 15.0, "currency": "USD"},
        ]
        config = {"honeygain_signup_bonus": "5.0"}
        with (
            _auth_owner(),
            patch("app.main.database.get_earnings_dashboard_summary", new_callable=AsyncMock, return_value=summary),
            patch("app.main.database.get_config", new_callable=AsyncMock, return_value=config),
            patch("app.main.database.get_earnings_summary", new_callable=AsyncMock, return_value=earnings),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[]),
        ):
            resp = client.get("/api/earnings/summary")
            data = resp.json()
            assert data["total_bonus"] == 5.0
            assert data["total_adjusted"] == 10.0


class TestRedeployTakesTheCatalogCommand:
    """A redeploy rebuilds the command from the catalog, filled from the merged env.

    The recorded command used to win over the catalog. Nobody can type a
    command, so that froze two things that must change: Mysterium kept
    publishing its WebUI and API on 0.0.0.0 after the catalog bound them to
    loopback, and a password retyped on redeploy never reached a service that
    takes it on the command line. Seen live on the fleet, 2026-09-25.
    """

    CREDENTIAL_SVC = {
        "slug": "honeygain",
        "name": "Honeygain",
        "docker": {
            "image": "honeygain/honeygain:latest",
            "env": [
                {"key": "HG_EMAIL", "required": True, "default": ""},
                {"key": "HG_PASSWORD", "required": True, "secret": True, "default": ""},
            ],
            "command": "-tou-accept -email ${HG_EMAIL} -pass ${HG_PASSWORD}",
        },
    }
    CREDENTIAL_RECORD = {
        "image": "honeygain/honeygain:latest",
        "env": {"HG_EMAIL": "me@example.com", "HG_PASSWORD": "pw1"},
        "command": "-tou-accept -email me@example.com -pass pw1",
    }

    def _redeploy(self, client, svc, recorded, body):
        worker = _online_worker()
        sent: dict = {}

        async def _fake_deploy(worker_id, slug, spec):
            sent.update(spec)
            return {"container_id": "abc123"}

        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.catalog.get_service", return_value=svc),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.get_deployment_spec", new_callable=AsyncMock, return_value=recorded),
            patch("app.main._proxy_worker_deploy", side_effect=_fake_deploy),
            patch("app.main.database.save_deployment", new_callable=AsyncMock),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main._run_collection", new_callable=AsyncMock),
        ):
            resp = client.post(f"/api/deploy/{svc['slug']}", json=body)
        assert resp.status_code == 200, resp.text
        return resp.json(), sent

    def test_a_catalog_fix_to_the_command_reaches_a_running_service(self, client):
        svc = {
            "slug": "mysterium",
            "name": "Mysterium",
            "docker": {
                "image": "mysteriumnetwork/myst",
                "env": [],
                "command": "--ui.address=127.0.0.1 --tequilapi.address=127.0.0.1 service",
            },
        }
        recorded = {
            "image": "mysteriumnetwork/myst",
            "env": {},
            "command": "--ui.address=0.0.0.0 --tequilapi.address=0.0.0.0 service",
        }
        data, sent = self._redeploy(client, svc, recorded, {"env": {}})
        assert sent["command"] == "--ui.address=127.0.0.1 --tequilapi.address=127.0.0.1 service"
        assert any(line.startswith("command:") for line in data["kept_from_previous_deployment"])

    def test_a_command_the_catalog_dropped_is_dropped(self, client):
        """Storj's sunset zkSync flag: gone from the catalog, gone from the node."""
        svc = {"slug": "storj", "name": "Storj", "docker": {"image": "storjlabs/storagenode", "env": []}}
        recorded = {"image": "storjlabs/storagenode", "env": {}, "command": "--operator.wallet-features=zksync-era"}
        data, sent = self._redeploy(client, svc, recorded, {"env": {}})
        assert not sent.get("command")
        assert any(line.startswith("command:") for line in data["kept_from_previous_deployment"])

    def test_a_blank_redeploy_fills_the_command_from_the_recorded_credentials(self, client):
        """Why the record used to win: the form's own env has no credentials in it."""
        data, sent = self._redeploy(client, self.CREDENTIAL_SVC, self.CREDENTIAL_RECORD, {"env": {}})
        assert sent["command"] == "-tou-accept -email me@example.com -pass pw1"
        assert "${" not in sent["command"]
        # Nothing changed, so there is nothing to report about the command.
        assert not any(line.startswith("command:") for line in data.get("kept_from_previous_deployment", []))

    def test_a_retyped_password_reaches_the_command_line(self, client):
        data, sent = self._redeploy(
            client, self.CREDENTIAL_SVC, self.CREDENTIAL_RECORD, {"env": {"HG_PASSWORD": "pw2"}}
        )
        assert sent["command"] == "-tou-accept -email me@example.com -pass pw2"

    def test_a_retyped_password_is_not_a_changed_command(self, client):
        """The filled command differs, but the catalog's command did not change: nothing to report."""
        data, _ = self._redeploy(client, self.CREDENTIAL_SVC, self.CREDENTIAL_RECORD, {"env": {"HG_PASSWORD": "pw2"}})
        assert not any(line.startswith("command:") for line in data.get("kept_from_previous_deployment", []))

    def test_the_report_never_repeats_the_command(self, client):
        """Commands carry credentials; the toast and the log line must not."""
        # An older catalog command (no -tou-accept), so the report has a command line.
        recorded = {**self.CREDENTIAL_RECORD, "command": "-email me@example.com -pass pw1"}
        data, _ = self._redeploy(client, self.CREDENTIAL_SVC, recorded, {"env": {"HG_PASSWORD": "pw2"}})
        report = " ".join(data["kept_from_previous_deployment"])
        assert "command:" in report
        for secret in ("pw2", "pw1", "me@example.com"):
            assert secret not in report


class TestRedeployReadsThisWorkersRecord:
    """A redeploy on one machine must never rebuild from another machine's spec."""

    SVC = {
        "slug": "storj",
        "name": "Storj",
        "docker": {
            "image": "storjlabs/storagenode",
            "env": [
                {"key": "ADDRESS", "required": True, "default": ""},
                {"key": "STORAGE", "required": True, "default": "1TB"},
            ],
        },
    }
    RECORDS = {
        1: {"image": "storjlabs/storagenode", "env": {"ADDRESS": "node-a.example:28967", "STORAGE": "1TB"}},
        2: {"image": "storjlabs/storagenode", "env": {"ADDRESS": "node-b.example:28968", "STORAGE": "2TB"}},
    }

    def _redeploy(self, client, worker_id, records):
        worker = _online_worker(wid=worker_id)
        sent: dict = {}
        read_for: list = []

        async def _spec(slug, worker_id=None):
            read_for.append(worker_id)
            return records.get(worker_id)

        async def _fake_deploy(wid, slug, spec):
            sent.update(spec)
            return {"container_id": "abc123"}

        save = AsyncMock()
        with (
            _auth_owner(),
            patch("app.main.database.list_workers", new_callable=AsyncMock, return_value=[worker]),
            patch("app.main.catalog.get_service", return_value=self.SVC),
            patch("app.main.database.get_worker", new_callable=AsyncMock, return_value=worker),
            patch("app.main.database.get_deployment_spec", side_effect=_spec),
            patch("app.main._proxy_worker_deploy", side_effect=_fake_deploy),
            patch("app.main.database.save_deployment", save),
            patch("app.main.database.record_health_event", new_callable=AsyncMock),
            patch("app.main._run_collection", new_callable=AsyncMock),
        ):
            resp = client.post(f"/api/deploy/storj?worker_id={worker_id}", json={"env": {}})
        return resp, sent, read_for, save

    def test_the_redeploy_uses_the_target_workers_address(self, client):
        resp, sent, read_for, save = self._redeploy(client, 1, self.RECORDS)
        assert resp.status_code == 200, resp.text
        assert read_for == [1]
        assert sent["env"]["ADDRESS"] == "node-a.example:28967"
        assert sent["env"]["STORAGE"] == "1TB"
        assert save.call_args.kwargs["worker_id"] == 1

    def test_no_record_for_this_worker_asks_instead_of_borrowing(self, client):
        """Only worker 2 has a record: worker 1 must be asked for its address."""
        resp, sent, _, _ = self._redeploy(client, 1, {2: self.RECORDS[2]})
        assert resp.status_code == 400
        assert "External address" in resp.text or "ADDRESS" in resp.text
        assert not sent, "nothing may reach the worker with another machine's address"
