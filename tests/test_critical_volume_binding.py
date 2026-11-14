"""A critical volume stays with its own service, on its own image (issue #741).

A critical volume (``critical_volumes`` in a service's YAML) holds a wallet or
a node identity: ProxyBase's volume IS the money. Before this, a stolen owner
session or the admin API key could deploy any image onto ``proxybase-data``
through the raw command route, or set a custom image on ProxyBase itself, and
read or replace the wallet with no password. These tests pin the worker's rule
(only the owning service mounts it, on the catalog's image unless the owner
confirmed another with their password), the step-up approval, and the audit rows.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import auth, catalog, database, deps, main, orchestrator, step_up, worker_api  # noqa: E402

WORKER_KEY = "per-worker-key-abc"
WALLET = "ghcr.io/proxybasehq/proxybase-cli"
PROXYBASE_IMAGE = catalog.get_service("proxybase-xyz")["docker"]["image"]


# ---------------------------------------------------------------------------
# The approval
# ---------------------------------------------------------------------------


class TestTheApproval:
    def test_a_fresh_approval_for_this_target_passes(self):
        token = step_up.sign(WORKER_KEY, "act", "slug|img")
        step_up.check(WORKER_KEY, token, "act", "slug|img")

    def test_it_is_good_for_one_use(self):
        token = step_up.sign(WORKER_KEY, "act", "slug|img")
        step_up.check(WORKER_KEY, token, "act", "slug|img")
        with pytest.raises(step_up.StepUpError, match="already used"):
            step_up.check(WORKER_KEY, token, "act", "slug|img")

    def test_it_expires(self):
        token = step_up.sign(WORKER_KEY, "act", "slug|img", ttl=60, now=1_000_000)
        early = step_up.sign(WORKER_KEY, "act", "slug|img", ttl=60, now=1_000_000)
        step_up.check(WORKER_KEY, early, "act", "slug|img", now=1_000_059)
        with pytest.raises(step_up.StepUpError, match="expired"):
            step_up.check(WORKER_KEY, token, "act", "slug|img", now=1_000_060)

    @pytest.mark.parametrize(("action", "target"), [("act", "slug|other"), ("act", "other|img"), ("other", "slug|img")])
    def test_it_is_bound_to_its_action_and_target(self, action, target):
        token = step_up.sign(WORKER_KEY, "act", "slug|img")
        with pytest.raises(step_up.StepUpError, match="another action"):
            step_up.check(WORKER_KEY, token, action, target)

    def test_another_workers_key_cannot_check_it(self):
        token = step_up.sign("someone-else", "act", "slug|img")
        with pytest.raises(step_up.StepUpError, match="not signed"):
            step_up.check(WORKER_KEY, token, "act", "slug|img")

    def test_a_tampered_payload_is_refused(self):
        body, mac = step_up.sign(WORKER_KEY, "act", "slug|img").split(".")
        forged = step_up._b64(step_up._unb64(body).replace(b"slug|img", b"slug|evil"))
        with pytest.raises(step_up.StepUpError):
            step_up.check(WORKER_KEY, f"{forged}.{mac}", "act", "slug|evil")

    def test_a_long_lived_one_is_refused_even_when_signed(self):
        token = step_up.sign(WORKER_KEY, "act", "slug|img", ttl=86400)
        with pytest.raises(step_up.StepUpError, match="too long"):
            step_up.check(WORKER_KEY, token, "act", "slug|img")

    def test_a_worker_on_the_shared_key_accepts_none(self):
        """The shared fleet key can be revealed to any owner session, so it signs nothing."""
        token = step_up.sign(WORKER_KEY, "act", "slug|img")
        with pytest.raises(step_up.StepUpError, match="shared fleet key"):
            step_up.check(None, token, "act", "slug|img")

    @pytest.mark.parametrize("token", [None, "", "nodot", "a.b.c", "!!!.00"])
    def test_garbage_is_refused(self, token):
        with pytest.raises(step_up.StepUpError):
            step_up.check(WORKER_KEY, token, "act", "slug|img")


# ---------------------------------------------------------------------------
# Which volumes are critical, from the YAML
# ---------------------------------------------------------------------------


def _declares_critical(svc):
    return bool((svc.get("docker") or {}).get("critical_volumes"))


class TestFromTheYaml:
    def test_the_critical_services_are_the_ones_whose_yaml_says_so(self):
        expected = {svc["slug"] for svc in catalog.get_services() if _declares_critical(svc)}
        assert set(orchestrator.critical_slugs()) == expected
        assert {"proxybase-xyz", "mysterium", "storj", "anyone-protocol", "sia-hostd"} <= expected

    def test_the_wallet_volume_belongs_to_proxybase(self):
        named = orchestrator._catalog_critical_named_volumes(orchestrator.critical_slugs())
        assert named["proxybase-data"] == "proxybase-xyz"
        assert named["mysterium-data"] == "mysterium"
        # A ${VAR} folder is the operator's, learned from the running container.
        assert not any(name.startswith("$") for name in named)

    def test_no_two_services_declare_the_same_critical_volume(self):
        seen: dict[str, str] = {}
        for svc in catalog.get_services():
            for mapping in (svc.get("docker") or {}).get("volumes") or []:
                source = str(mapping).split(":")[0]
                if source.startswith(("/", "$")):
                    continue
                owner = orchestrator._catalog_critical_named_volumes(orchestrator.critical_slugs()).get(source)
                if owner:
                    assert seen.setdefault(source, svc["slug"]) == svc["slug"] == owner, source

    @pytest.mark.parametrize(
        ("image", "ok"),
        [
            (PROXYBASE_IMAGE, True),
            (f"docker.io/{PROXYBASE_IMAGE}" if not PROXYBASE_IMAGE.startswith("ghcr") else PROXYBASE_IMAGE, True),
            (f"{WALLET}@sha256:" + "b" * 64, False),
            (f"{WALLET}:latest", False),
            ("attacker/steal:1.0", False),
        ],
    )
    def test_a_pinned_catalog_image_matches_only_itself(self, image, ok):
        assert orchestrator.catalog_image_matches("proxybase-xyz", image) is ok

    def test_an_untagged_catalog_image_matches_any_tag_of_its_repository(self):
        assert orchestrator.catalog_image_matches("storj", "storjlabs/storagenode")
        assert orchestrator.catalog_image_matches("storj", "docker.io/storjlabs/storagenode:v1.120.0")
        assert not orchestrator.catalog_image_matches("storj", "storjlabs/storagenode-evil")

    def test_a_tagged_catalog_image_refuses_another_tag(self):
        image = catalog.get_service("anyone-protocol")["docker"]["image"]
        assert orchestrator.catalog_image_matches("anyone-protocol", image)
        assert not orchestrator.catalog_image_matches("anyone-protocol", image.rsplit(":", 1)[0] + ":9.9.9")


# ---------------------------------------------------------------------------
# The mounts
# ---------------------------------------------------------------------------


def _container(slug, mounts):
    c = MagicMock()
    c.labels = {"cashpilot.service": slug, "cashpilot.managed": "true"}
    c.attrs = {"Mounts": mounts}
    return c


def _docker(*containers):
    client = MagicMock()
    client.containers.list.return_value = list(containers)
    return client


STORJ = _container(
    "storj",
    [
        {"Type": "bind", "Source": "/mnt/user/storj/identity", "Destination": "/app/identity"},
        {"Type": "bind", "Source": "/mnt/user/storj/data", "Destination": "/app/config"},
    ],
)


class TestConflicts:
    @pytest.mark.parametrize(
        "volumes",
        [
            {"proxybase-data": {"bind": "/data", "mode": "ro"}},
            ["proxybase-data:/x:rw"],  # the kept-mounts list shape
            {"/mnt/user/storj/identity": {"bind": "/id"}},
            {"/mnt/user/storj/identity/sub": {"bind": "/id"}},  # inside it
            {"/mnt/user/storj": {"bind": "/all"}},  # above it: hands over everything under it
            {"/mnt/user/storj/identity/": {"bind": "/id"}},
        ],
    )
    def test_another_service_cannot_mount_it(self, volumes):
        with pytest.raises(orchestrator.CriticalMountError):
            orchestrator.refuse_critical_mounts("honeygain", volumes, _docker(STORJ))

    def test_its_own_service_can(self):
        orchestrator.refuse_critical_mounts("proxybase-xyz", {"proxybase-data": {"bind": "/x"}}, _docker())
        orchestrator.refuse_critical_mounts("storj", {"/mnt/user/storj/identity": {"bind": "/id"}}, _docker(STORJ))

    def test_unrelated_mounts_pass(self):
        orchestrator.refuse_critical_mounts(
            "honeygain", {"honeygain-data": {"bind": "/d"}, "/mnt/user/storjx": {"bind": "/e"}}, _docker(STORJ)
        )

    def test_a_volume_found_on_a_running_node_counts_too(self):
        """A node moved off its catalog volume by hand keeps its identity there."""
        moved = _container(
            "mysterium", [{"Type": "volume", "Name": "myst-old", "Destination": "/var/lib/mysterium-node"}]
        )
        with pytest.raises(orchestrator.CriticalMountError, match="mysterium"):
            orchestrator.refuse_critical_mounts("honeygain", {"myst-old": {"bind": "/x"}}, _docker(moved))

    def test_no_volumes_does_not_touch_docker(self):
        client = _docker()
        orchestrator.refuse_critical_mounts("honeygain", {}, client)
        client.containers.list.assert_not_called()


class TestDeployRawBackstop:
    def _deploy(self, client, **kwargs):
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "container_network", return_value=None),
            patch.object(orchestrator, "container_runtime", return_value=None),
            patch.object(orchestrator, "container_dns", return_value=None),
        ):
            return orchestrator.deploy_raw(**kwargs)

    def test_refused_before_anything_is_pulled(self):
        client = _docker()
        with pytest.raises(orchestrator.CriticalMountError):
            self._deploy(client, slug="honeygain", image="x/x:1", volumes={"proxybase-data": {"bind": "/w"}})
        client.images.pull.assert_not_called()
        client.containers.run.assert_not_called()

    def test_a_kept_mount_of_another_service_is_refused_on_redeploy(self):
        """A container made before this check carries the wallet; its redeploy must not keep it."""
        old = _container("honeygain", [{"Type": "volume", "Name": "proxybase-data", "Destination": "/d", "RW": True}])
        old.status = "exited"
        client = _docker(old)
        client.containers.get.return_value = old
        client.images.get.return_value.attrs = {"Config": {}}
        with (
            patch.object(orchestrator, "_aside_taken", return_value=None),
            pytest.raises(orchestrator.CriticalMountError),
        ):
            self._deploy(
                client,
                slug="honeygain",
                image="honeygain/honeygain",
                volumes={"honeygain-data": {"bind": "/d"}},
                keep_targets={"/d"},
            )
        old.stop.assert_not_called()
        client.containers.run.assert_not_called()


# ---------------------------------------------------------------------------
# The worker API
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _noop(_app):
    yield


@pytest.fixture
def worker(monkeypatch):
    worker_api.app.router.lifespan_context = _noop
    monkeypatch.setattr(worker_api, "API_KEY", "wk-test")
    monkeypatch.setattr(worker_api, "_worker_key", WORKER_KEY)
    deployed: list[dict] = []

    def fake_deploy(**kwargs):
        # The real backstop, with no Docker: the catalog's own volume names.
        orchestrator.refuse_critical_mounts(kwargs["slug"], kwargs.get("volumes"), _docker())
        deployed.append(kwargs)
        return "cid"

    monkeypatch.setattr(worker_api.orchestrator, "deploy_raw", fake_deploy)
    monkeypatch.setattr(worker_api, "_validate_runtime", lambda runtime: None)
    monkeypatch.setattr(worker_api.lan_fence, "refresh_outside", lambda: None)
    client = TestClient(worker_api.app, raise_server_exceptions=False)
    headers = {"Authorization": f"Bearer {WORKER_KEY}"}

    def post(path, body):
        return client.post(path, json=body, headers=headers)

    post.deployed = deployed
    return post


def _error(resp):
    detail = resp.json().get("detail")
    return detail.get("error") if isinstance(detail, dict) else detail


class TestTheWorkerRefuses:
    def test_another_image_mounting_the_wallet(self, worker):
        """The raw command route's attack: any slug, any image, the wallet volume."""
        resp = worker(
            "/api/containers/evil/deploy", {"image": "attacker/x:1", "volumes": {"proxybase-data": {"bind": "/w"}}}
        )
        assert resp.status_code == 403 and _error(resp) == "critical_volume_mount"
        assert worker.deployed == []

    def test_a_catalog_service_mounting_another_services_wallet(self, worker):
        resp = worker(
            "/api/containers/honeygain/deploy",
            {"image": "honeygain/honeygain", "volumes": {"proxybase-data": {"bind": "/w"}}},
        )
        assert resp.status_code == 403 and _error(resp) == "critical_volume_mount"

    def test_a_second_copy_mounting_it(self, worker):
        resp = worker(
            "/api/containers/evil/deploy",
            {"image": "attacker/x:1", "instance": 2, "volumes": {"proxybase-data": {"bind": "/w"}}},
        )
        assert resp.status_code in (400, 403) and worker.deployed == []

    def test_a_proxied_copy_mounting_it(self, worker):
        resp = worker(
            "/api/proxied/evil/1/deploy",
            {
                "earner": {"image": "attacker/x:1", "volumes": {"proxybase-data": {"bind": "/w"}}},
                "proxy": {"kind": "http", "host": "proxy.example", "port": 8080},
            },
        )
        assert resp.status_code == 400 and "mount volumes" in resp.text

    def test_a_custom_image_on_the_wallet_service_without_a_password(self, worker):
        resp = worker(
            "/api/containers/proxybase-xyz/deploy",
            {"image": "attacker/x:1", "volumes": {"proxybase-data": {"bind": "/home/proxybase/.proxybase"}}},
        )
        assert resp.status_code == 403 and _error(resp) == "step_up_required"
        assert worker.deployed == []

    def test_a_custom_image_with_no_volumes_still_needs_it(self, worker):
        """No volumes in the spec is no proof: a replaced container keeps its mounts."""
        resp = worker("/api/containers/proxybase-xyz/deploy", {"image": "attacker/x:1"})
        assert resp.status_code == 403 and _error(resp) == "step_up_required"

    def test_an_approval_for_another_image(self, worker):
        token = step_up.sign(WORKER_KEY, step_up.ACTION_CUSTOM_IMAGE, "proxybase-xyz|mirror/proxybase:1")
        resp = worker("/api/containers/proxybase-xyz/deploy", {"image": "attacker/x:1", "approval": token})
        assert resp.status_code == 403 and _error(resp) == "step_up_rejected"
        assert worker.deployed == []

    def test_an_approval_signed_with_the_shared_key(self, worker):
        token = step_up.sign("wk-test", step_up.ACTION_CUSTOM_IMAGE, "proxybase-xyz|mirror/proxybase:1")
        resp = worker("/api/containers/proxybase-xyz/deploy", {"image": "mirror/proxybase:1", "approval": token})
        assert resp.status_code == 403 and _error(resp) == "step_up_rejected"


class TestTheWorkerAllows:
    def test_the_wallet_service_on_its_catalog_image(self, worker):
        resp = worker(
            "/api/containers/proxybase-xyz/deploy",
            {"image": PROXYBASE_IMAGE, "volumes": {"proxybase-data": {"bind": "/home/proxybase/.proxybase"}}},
        )
        assert resp.status_code == 200, resp.text

    def test_a_confirmed_custom_image_once(self, worker):
        token = step_up.sign(WORKER_KEY, step_up.ACTION_CUSTOM_IMAGE, "proxybase-xyz|mirror/proxybase:1")
        body = {"image": "mirror/proxybase:1", "approval": token}
        assert worker("/api/containers/proxybase-xyz/deploy", body).status_code == 200
        replay = worker("/api/containers/proxybase-xyz/deploy", body)
        assert replay.status_code == 403 and "already used" in replay.text

    def test_a_custom_image_on_a_service_with_nothing_critical(self, worker):
        assert worker("/api/containers/honeygain/deploy", {"image": "mirror/honeygain:1"}).status_code == 200


def _catalog_deploys():
    """Every catalog service with an image, as the UI sends it: its image and each arch build."""
    for svc in catalog.get_services():
        docker = svc.get("docker") or {}
        for image in {docker.get("image"), *(docker.get("image_by_arch") or {}).values()} - {None, ""}:
            yield pytest.param(svc["slug"], image, id=f"{svc['slug']}:{image}")


@pytest.mark.parametrize(("slug", "image"), list(_catalog_deploys()))
def test_every_catalog_service_still_deploys_on_its_catalog_image(slug, image):
    """The rule must not refuse a normal deploy of anything in the catalog."""
    worker_api._validate_critical_image(worker_api.DeploySpec(image=image), slug)
    volumes = {}
    for mapping in catalog.get_service(slug)["docker"].get("volumes") or []:
        source, target = str(mapping).split(":")[:2]
        if not source.startswith("$"):
            volumes[source] = {"bind": target}
    assert orchestrator.critical_mount_conflicts(slug, volumes, _docker()) == []


# ---------------------------------------------------------------------------
# The UI
# ---------------------------------------------------------------------------

VAULT = {
    "slug": "vault-demo",
    "name": "Vault demo",
    "status": "active",
    "category": "bandwidth",
    "docker": {
        "image": "vault/demo:1.0",
        "env": [{"key": "TOKEN", "required": True, "label": "Token"}],
        "volumes": ["vault-data:/vault"],
        "critical_volumes": [{"target": "/vault", "holds": "The wallet."}],
    },
}


@pytest.fixture
def db(tmp_path):
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
        asyncio.run(database.init_db())
        yield tmp_path / "cashpilot.db"


def _request():
    request = MagicMock()
    request.client.host = "192.0.2.10"
    request.headers = {}
    return request


def _ui_deploy(image, password, user, *, owner_hash=None):
    """Run the UI deploy of VAULT with a custom image; returns (sent spec, saved spec, error)."""
    sent: list[dict] = []
    saved = AsyncMock()

    async def capture(worker_id, slug, spec):
        sent.append(dict(spec))
        return {"container_id": "abc"}

    body = main.DeployRequest(env={"TOKEN": "t"}, image=image, step_up_password=password)

    async def run():
        uid = None
        if owner_hash is not None:
            uid = await database.create_user("owner", owner_hash, "owner")
        who = dict(user, uid=uid) if user.get("uid") is None else user
        with (
            patch.object(auth, "get_current_user", return_value=who),
            patch.object(main.catalog, "get_service", return_value=VAULT),
            patch.object(main, "_resolve_worker_id", AsyncMock(return_value=1)),
            patch.object(main, "_proxy_worker_deploy", capture),
            patch.object(main, "_confirmed_worker_key", AsyncMock(return_value=WORKER_KEY)),
            patch.object(main.database, "get_worker", AsyncMock(return_value={"client_id": "w1"})),
            patch.object(main.database, "get_deployment_spec", AsyncMock(return_value=None)),
            patch.object(main.database, "save_deployment", saved),
            patch.object(main.database, "record_health_event", AsyncMock()),
            patch.object(main, "_spawn", lambda coro: coro.close()),
            patch.object(main.metrics, "record_container_lifecycle", lambda *a: None),
        ):
            try:
                await main.api_deploy(_request(), "vault-demo", body)
            except HTTPException as exc:
                return exc, await database.get_audit_events()
            return None, await database.get_audit_events()

    error, audit = asyncio.run(run())
    return sent, (saved.call_args.kwargs["spec"] if saved.call_args else None), error, audit


OWNER = {"u": "owner", "r": "owner"}
API_KEY_USER = {"uid": 0, "u": "api", "r": "owner"}


class TestTheUiStepUp:
    @pytest.fixture(autouse=True)
    def _fresh_rate_limit(self):
        from app import login_rate_limit

        login_rate_limit._login_attempts.clear()
        yield
        login_rate_limit._login_attempts.clear()

    def test_no_password_asks_for_one_and_sends_nothing(self, db):
        sent, _, error, _ = _ui_deploy("mirror/vault:2", None, OWNER, owner_hash=auth.hash_password("correct horse"))
        assert error.status_code == 403 and error.detail["error"] == "step_up_required"
        assert sent == []

    def test_the_admin_api_key_is_refused_and_audited(self, db):
        sent, _, error, audit = _ui_deploy("mirror/vault:2", "anything", API_KEY_USER)
        assert error.status_code == 403 and error.detail["error"] == "step_up_api_key"
        assert sent == []
        assert audit[0]["outcome"] == "refused" and audit[0]["actor"] == "api"

    def test_a_wrong_password_is_refused_and_audited(self, db):
        sent, _, error, audit = _ui_deploy(
            "mirror/vault:2", "wrong", OWNER, owner_hash=auth.hash_password("right one!")
        )
        assert error.status_code == 403 and error.detail["error"] == "step_up_failed"
        assert sent == [] and audit[0]["outcome"] == "failed"

    def test_the_right_password_sends_an_approval_the_worker_accepts(self, db):
        sent, saved, error, audit = _ui_deploy(
            "mirror/vault:2", "right one!", OWNER, owner_hash=auth.hash_password("right one!")
        )
        assert error is None
        approval = sent[0]["approval"]
        step_up.check(WORKER_KEY, approval, step_up.ACTION_CUSTOM_IMAGE, "vault-demo|mirror/vault:2")
        assert "approval" not in saved and "step_up_password" not in str(saved)
        assert audit[0]["outcome"] == "confirmed" and audit[0]["target"] == "vault-demo|mirror/vault:2"

    def test_the_catalog_image_needs_no_password(self, db):
        sent, _, error, _ = _ui_deploy("", None, OWNER)
        assert error is None and "approval" not in sent[0]

    def test_the_step_up_counts_against_the_login_rate_limit(self, db):
        user = {"uid": 7, "u": "owner", "r": "owner"}
        with (
            patch.object(deps.auth, "get_current_user", return_value=user),
            patch.object(
                database, "get_user_by_id", AsyncMock(return_value={"password": auth.hash_password("x" * 10)})
            ),
        ):

            async def attempt():
                with pytest.raises(HTTPException) as exc:
                    await deps.require_step_up(_request(), "nope", action="a", target="t")
                return exc.value.status_code

            codes = [asyncio.run(attempt()) for _ in range(6)]
        assert codes[:5] == [403] * 5 and codes[5] == 429


class TestTheRawRoute:
    def _send(self, spec, worker_reply):
        calls: list[dict] = []

        async def hop(worker_id, method, path, **kwargs):
            calls.append(kwargs.get("json"))
            if isinstance(worker_reply, HTTPException):
                raise worker_reply
            return worker_reply

        async def run():
            with (
                patch.object(main, "_require_owner", lambda r: OWNER),
                patch.object(auth, "get_current_user", return_value={"uid": 1, "u": "owner", "r": "owner"}),
                patch.object(main, "_proxy_to_worker", hop),
                patch.object(main.database, "save_deployment", AsyncMock()),
                patch.object(main.database, "record_health_event", AsyncMock()),
                patch.object(main, "_spawn", lambda coro: coro.close()),
            ):
                try:
                    await main.api_worker_command(
                        _request(), 1, main.WorkerCommand(command="deploy", slug="evil", spec=spec)
                    )
                except HTTPException as exc:
                    return exc, await database.get_audit_events()
                return None, await database.get_audit_events()

        error, audit = asyncio.run(run())
        return calls, error, audit

    def test_a_pasted_approval_never_reaches_the_worker(self, db):
        calls, _, _ = self._send({"image": "x", "approval": "a.b"}, {"container_id": "c"})
        assert "approval" not in calls[0]

    def test_the_workers_refusal_is_audited(self, db):
        refusal = HTTPException(status_code=403, detail={"error": "critical_volume_mount", "message": "no"})
        _, error, audit = self._send({"image": "x", "volumes": {"proxybase-data": {}}}, refusal)
        assert error is refusal
        assert audit[0]["action"] == "deploy" and audit[0]["outcome"] == "refused: critical_volume_mount"
        assert audit[0]["target"] == "evil" and audit[0]["worker_id"] == 1

    def test_the_refusal_reaches_the_dashboard(self):
        resp = MagicMock()
        resp.json.return_value = {"detail": {"error": "critical_volume_mount", "message": "kept for its owner"}}
        assert main._safe_worker_detail(resp) == {"error": "critical_volume_mount", "message": "kept for its owner"}


class TestTheAuditTable:
    def test_the_fleet_key_reveal_writes_a_row(self, db):
        async def run():
            with (
                patch.object(main, "_require_owner", lambda r: {"uid": 1, "u": "owner", "r": "owner"}),
                patch.object(main, "FLEET_API_KEY", "k"),
            ):
                await main.api_fleet_api_key_reveal(_request())
            return await database.get_audit_events()

        rows = asyncio.run(run())
        assert rows[0]["action"] == "fleet_key_reveal" and rows[0]["actor"] == "owner"
        assert "k" not in (rows[0]["detail"], rows[0]["target"])

    def test_the_list_is_owner_only(self, db):
        with (
            patch.object(main, "_require_owner", side_effect=HTTPException(status_code=403)),
            pytest.raises(HTTPException),
        ):
            asyncio.run(main.api_audit(_request()))

    def test_newest_first_and_capped(self, db):
        async def run():
            for n in range(5):
                await database.add_audit_event("a", f"t{n}", "ok")
            return await database.get_audit_events(3)

        rows = asyncio.run(run())
        assert [r["target"] for r in rows] == ["t4", "t3", "t2"]
