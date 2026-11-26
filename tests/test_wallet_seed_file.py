"""Sia hostd's wallet seed lives only in hostd's own data volume (app/wallet_seed.py).

The seed phrase IS the wallet: whoever reads it spends the node's Siacoin and
its locked collateral. It used to be an ordinary secret env var, so CashPilot
kept it Fernet-encrypted next to its own key file and Docker kept it in plain
text in the container's settings (``docker inspect``, config.v2.json,
/proc/<pid>/environ), while the catalog said "CashPilot never holds the key".

The regression tests at the top post the seed the old way, as the variable,
which is what an older dashboard or an API client still does. On the code
before the fix each of them fails: the phrase reached the container env, the
deployment records and the logs.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import shutil
import sqlite3
import subprocess
import tarfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth, catalog, database, main, orchestrator, step_up, wallet_seed, worker_api

OWNER = {"uid": 1, "u": "owner", "r": "owner"}
SLUG = "sia-hostd"
KEY = "HOSTD_WALLET_SEED"
# BIP-39 test vectors, valid checksums. Never a real wallet.
PHRASE = "legal winner thank year wave sausage worth useful legal winner thank yellow"
OTHER = "letter advice cage absurd amount doctor acoustic avoid letter advice cage above"
NEW = "zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo zoo wrong"
ADDRESS = "ab" * 38
ENV = {"HOSTD_API_PASSWORD": "dashboard-pw", "SIA_STORAGE_DIR": "/srv/sia"}
VOLUMES = {"sia-hostd-data": {"bind": "/data", "mode": "rw"}, "/srv/sia": {"bind": "/storage", "mode": "rw"}}
WORKER_KEY = "wk-" + "1" * 40
CLIENT_ID = "client-box-1"


def _words_of(text: str) -> bool:
    """Whether ``text`` holds the phrase, or a run of four of its words (a partial leak counts)."""
    for phrase in (PHRASE, OTHER, NEW):
        words = phrase.split()
        if any(" ".join(words[i : i + 4]) in text for i in range(len(words) - 3)):
            return True
    return False


# ---------------------------------------------------------------------------
# The dashboard (lead): records, the deploy body, the logs
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
        asyncio.run(database.init_db())
        asyncio.run(database.upsert_worker(CLIENT_ID, name="box-1"))
        yield tmp_path / "cashpilot.db"


def _everything_stored(db_path) -> str:
    """Every text cell of every table, decrypted where it is encrypted."""
    conn = sqlite3.connect(db_path)
    out: list[str] = []
    try:
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
            for row in conn.execute(f'SELECT * FROM "{table}"'):
                for cell in row:
                    if isinstance(cell, str):
                        out.append(cell)
                        if cell.startswith("enc:"):
                            out.append(database.decrypt_value(cell))
    finally:
        conn.close()
    return "\n".join(out)


def _request():
    request = MagicMock()
    request.client.host = "192.0.2.10"
    request.headers = {}
    return request


def _deploy(env, *, features=("instances", "wallet_seed_file"), wallet_seed=None, answer=None):
    """Deploy sia-hostd to box 1 through the route; what was sent, and the response or the refusal."""
    sent: list[dict] = []

    async def hop(wid, method, path, *, json=None, **kwargs):
        sent.append({"path": path, "json": json})
        return {"container_id": "c1", **(answer or {})}

    body = main.DeployRequest(env=env, **({"wallet_seed": wallet_seed} if wallet_seed else {}))

    async def run():
        with (
            patch.object(auth, "get_current_user", return_value=OWNER),
            patch.object(main, "_resolve_worker_id", AsyncMock(return_value=1)),
            patch.object(main, "_proxy_to_worker", hop),
            patch.object(main, "_worker_features", AsyncMock(return_value=set(features))),
            patch.object(main, "_worker_instances", AsyncMock(return_value=set())),
            patch.object(main, "_register_device", AsyncMock(return_value=True)),
            patch.object(main.database, "record_health_event", AsyncMock()),
            patch.object(main, "_spawn", lambda coro: coro.close()),
            patch.object(main.metrics, "record_container_lifecycle", lambda *a: None),
        ):
            try:
                return await main.api_deploy(_request(), SLUG, body, 1)
            except HTTPException as exc:
                return exc

    return asyncio.run(run()), [s for s in sent if s["path"].endswith("/deploy")]


def _record_legacy_deployment():
    """A deployment recorded before the seed file: the phrase in its env, as every one made so far."""
    spec = {"image": "ghcr.io/siafoundation/hostd", "env": {**ENV, KEY: PHRASE}, "volumes": VOLUMES}
    asyncio.run(database.save_deployment(slug=SLUG, container_id="c0", spec=spec, worker_id=1))
    # A second save, so the prior spec (the one a redeploy replaced) holds it too.
    asyncio.run(database.save_deployment(slug=SLUG, container_id="c0", spec=spec, worker_id=1))


def test_desktop_remove_with_data_kept_retains_an_unconfirmed_recovery_phrase(db):
    async def prepare():
        worker = await database.upsert_worker(CLIENT_ID, system_info='{"device_type": "desktop"}')
        await database.save_deployment(SLUG, "a" * 64, worker_id=worker, spec={"env": {**ENV, KEY: PHRASE}})
        await database.save_deployment(SLUG, "b" * 64, worker_id=worker, spec={"env": ENV})
        return worker

    worker = asyncio.run(prepare())
    with (
        patch.object(auth, "get_current_user", return_value=OWNER),
        patch.object(main, "_proxy_to_worker", AsyncMock(return_value={"status": "removed"})),
    ):
        response = TestClient(main.app).delete(f"/api/services/{SLUG}?worker_id={worker}")
    assert response.status_code == 200, response.text
    assert asyncio.run(database.get_deployment(SLUG)) is None
    assert PHRASE in asyncio.run(database.get_saved_wallet_phrases({wallet_seed.field_name(KEY)}))
    removed, retained = asyncio.run(database.forget_env_value(SLUG, worker, KEY, confirmed_wallet_seed=PHRASE))
    assert removed and not retained
    assert PHRASE not in asyncio.run(database.get_saved_wallet_phrases({wallet_seed.field_name(KEY)}))


def test_deploy_on_another_worker_preserves_the_desktops_fleet_only_recovery_phrase(db):
    async def go():
        container_id = "a" * 64
        desktop = await database.upsert_worker(
            "desktop",
            containers=json.dumps([{"slug": SLUG, "container_id": container_id[:12]}]),
            system_info='{"device_type": "desktop"}',
        )
        await database.save_deployment(SLUG, container_id, spec={"env": {**ENV, KEY: PHRASE}})
        await database.save_deployment(SLUG, "b" * 64, spec={"env": ENV}, worker_id=1)
        return desktop

    desktop = asyncio.run(go())
    spec = asyncio.run(database.get_deployment_spec(SLUG, desktop))
    assert spec and spec["env"][KEY] == PHRASE
    assert KEY not in asyncio.run(database.get_deployment_spec(SLUG, 1))["env"]


@pytest.mark.parametrize("inventory", ["empty", "ambiguous", "seedless-spec"])
def test_cross_worker_save_keeps_a_fleet_only_phrase_when_the_owner_spec_cannot_hold_it(db, inventory):
    async def go():
        seen = json.dumps([{"slug": SLUG, "container_id": "a" * 12}])
        desktop = await database.upsert_worker("desktop", containers="[]" if inventory == "empty" else seen)
        if inventory == "ambiguous":
            await database.upsert_worker("another-desktop", containers=seen)
        if inventory == "seedless-spec":
            await database.save_deployment(SLUG, "c" * 64, worker_id=desktop, spec={"env": ENV})
        await database.save_deployment(SLUG, "a" * 64, spec={"env": {**ENV, KEY: PHRASE}})
        await database.save_deployment(SLUG, "b" * 64, worker_id=1, spec={"env": ENV})
        assert PHRASE in await database.get_saved_wallet_phrases({wallet_seed.field_name(KEY)})
        assert KEY not in (await database.get_deployment_spec(SLUG, 1))["env"]

    asyncio.run(go())


def test_desktop_keep_data_keeps_the_fleet_only_phrase_with_empty_inventory(db):
    async def prepare():
        desktop = await database.upsert_worker("desktop", containers="[]", system_info='{"device_type": "desktop"}')
        await database.save_deployment(SLUG, "a" * 64, spec={"env": {**ENV, KEY: PHRASE}})
        return desktop

    desktop = asyncio.run(prepare())
    with (
        patch.object(auth, "get_current_user", return_value=OWNER),
        patch.object(main, "_proxy_to_worker", AsyncMock(return_value={"status": "removed"})),
    ):
        reply = TestClient(main.app).delete(f"/api/services/{SLUG}?worker_id={desktop}")
    assert reply.status_code == 200, reply.text
    assert asyncio.run(database.get_deployment(SLUG)) is None
    assert PHRASE in asyncio.run(database.get_saved_wallet_phrases({wallet_seed.field_name(KEY)}))


class TestThePhraseIsNeverStoredOrSentAsAVariable:
    """Watched failing on the code before the fix: each assertion on the phrase was red."""

    def test_a_phrase_posted_as_the_variable_is_not_in_the_database(self, db):
        result, _sent = _deploy({**ENV, KEY: PHRASE})
        assert not isinstance(result, HTTPException), result
        assert not _words_of(_everything_stored(db))

    def test_it_reaches_the_worker_as_the_wallet_never_in_the_env(self, db):
        _result, sent = _deploy({**ENV, KEY: PHRASE})
        [deploy] = sent
        assert KEY not in deploy["json"]["env"]
        assert deploy["json"].get("wallet_seed") == {"mode": "import", "phrase": PHRASE}

    def test_a_deployment_recorded_with_the_phrase_loses_it_on_its_next_redeploy(self, db):
        _record_legacy_deployment()
        assert _words_of(_everything_stored(db))  # the positive control: the old record holds it
        result, sent = _deploy(dict(ENV))
        assert not isinstance(result, HTTPException), result
        [deploy] = sent
        assert KEY not in deploy["json"]["env"]
        assert deploy["json"]["wallet_seed"] == {"mode": "migrate", "phrase": PHRASE}
        assert not _words_of(_everything_stored(db))

    def test_no_old_copy_waits_in_a_free_page_or_the_wal(self, db):
        """Encrypted with the key that sits next to it, an old copy is as good as the phrase."""
        import re

        _record_legacy_deployment()
        _deploy(dict(ENV))
        found = []
        for path in db.parent.glob(db.name + "*"):
            for token in re.findall(rb"enc:(gAAAAA[A-Za-z0-9_=-]{40,})", path.read_bytes()):
                with contextlib.suppress(Exception):
                    found.append(database._fernet.decrypt(token).decode())
        assert found  # the positive control: the records are there, encrypted
        assert not _words_of("\n".join(found))

    def test_no_log_line_holds_it(self, db, caplog):
        caplog.set_level(logging.DEBUG)
        _deploy({**ENV, KEY: PHRASE})
        _deploy(dict(ENV), wallet_seed={"mode": "generate"}, answer={"wallet": {"created": True, "phrase": NEW}})
        assert caplog.records  # the deploys did log
        assert not _words_of(caplog.text)


class TestTheWalletChoice:
    def test_a_new_wallet_comes_back_once_and_only_its_address_is_kept(self, db):
        answer = {"wallet": {"created": True, "address": ADDRESS, "phrase": NEW}}
        result, sent = _deploy(dict(ENV), wallet_seed={"mode": "generate"}, answer=answer)
        assert sent[0]["json"]["wallet_seed"] == {"mode": "generate"}
        assert result["wallet"] == {"created": True, "address": ADDRESS, "phrase": NEW}
        stored = _everything_stored(db)
        assert not _words_of(stored)
        assert asyncio.run(database.get_deployment_spec(SLUG, worker_id=1))["wallet_address"] == ADDRESS

    def test_a_redeploy_with_no_choice_keeps_the_nodes_wallet(self, db):
        _deploy(dict(ENV), wallet_seed={"mode": "generate"}, answer={"wallet": {"created": True, "phrase": NEW}})
        _result, sent = _deploy(dict(ENV))
        assert sent[0]["json"]["wallet_seed"] == {"mode": "keep"}

    def test_a_pasted_phrase_with_a_typo_is_refused_without_repeating_it(self, db):
        typo = PHRASE.replace("yellow", "yelow")
        result, sent = _deploy(dict(ENV), wallet_seed={"mode": "import", "phrase": typo})
        assert isinstance(result, HTTPException) and result.status_code == 400
        assert "yelow" not in str(result.detail) and not _words_of(str(result.detail))
        assert sent == []

    def test_a_bad_checksum_is_refused(self, db):
        result, sent = _deploy(dict(ENV), wallet_seed={"mode": "import", "phrase": PHRASE.replace("yellow", "zoo")})
        assert isinstance(result, HTTPException) and result.detail["error"] == "wallet_phrase"
        assert sent == []

    def test_another_phrase_over_a_recorded_one_is_refused(self, db):
        """The node runs the recorded wallet: a second one would abandon it."""
        _record_legacy_deployment()
        result, sent = _deploy(dict(ENV), wallet_seed={"mode": "import", "phrase": OTHER})
        assert isinstance(result, HTTPException) and result.detail["error"] == "wallet_exists"
        assert sent == []

    def test_a_new_wallet_over_a_recorded_one_moves_the_recorded_one_instead(self, db):
        _record_legacy_deployment()
        _result, sent = _deploy(dict(ENV), wallet_seed={"mode": "generate"})
        assert sent[0]["json"]["wallet_seed"] == {"mode": "migrate", "phrase": PHRASE}


class TestDesktopLegacyWallet:
    @pytest.fixture
    def legacy_desktop(self, db):
        phrase = " ".join(f"test-only-word-{index}" for index in range(12))
        asyncio.run(database.upsert_worker(CLIENT_ID, system_info=json.dumps({"device_type": "desktop"})))
        for generation in ("prior", "current"):
            spec = {"env": {**ENV, KEY: phrase}, "note": generation}
            asyncio.run(database.save_deployment(SLUG, generation, spec=spec, worker_id=1))
        return phrase

    @pytest.mark.parametrize("fleet_owner", ["desktop", "docker"])
    def test_refused_desktop_redeploy_scrubs_the_confirmed_seed(self, legacy_desktop, fleet_owner):
        phrase = legacy_desktop
        if fleet_owner == "docker":
            worker = asyncio.run(database.upsert_worker("docker-box", system_info='{"docker_available": true}'))
            # Same seed, different deploy. Ownership matters even when the values match.
            docker_spec = {"env": {**ENV, KEY: phrase}}
            asyncio.run(database.save_deployment(SLUG, "d" * 12, spec=docker_spec, worker_id=worker))

        result, sent = _deploy({}, wallet_seed={"mode": "import", "phrase": phrase.upper()})
        assert isinstance(result, HTTPException) and result.status_code == 409
        assert sent == []
        assert phrase not in result.detail
        assert asyncio.run(database.get_deployment_spec(SLUG, worker_id=1)) == {"env": ENV, "note": "current"}
        assert asyncio.run(database.prior_deployment_spec(SLUG, 1)) == {"env": ENV, "note": "prior"}
        if fleet_owner == "docker":
            assert asyncio.run(database.get_deployment_spec(SLUG, worker_id=worker)) == docker_spec
            assert asyncio.run(database.get_deployment_spec(SLUG)) == docker_spec
        else:
            assert asyncio.run(database.get_deployment_spec(SLUG)) == {"env": ENV, "note": "current"}

    @pytest.mark.parametrize("choice", ["missing", "different"])
    def test_refused_desktop_redeploy_saves_the_possible_only_copy(self, legacy_desktop, choice):
        phrase = legacy_desktop
        wallet = {"mode": "import", "phrase": f"{phrase} extra"} if choice == "different" else None
        result, sent = _deploy({}, wallet_seed=wallet)
        assert isinstance(result, HTTPException) and result.status_code == 409
        assert sent == []
        assert "your only copy" in result.detail
        assert phrase not in result.detail
        assert asyncio.run(database.get_deployment_spec(SLUG, worker_id=1))["env"][KEY] == phrase
        assert asyncio.run(database.prior_deployment_spec(SLUG, 1))["env"][KEY] == phrase
        assert asyncio.run(database.get_deployment_spec(SLUG))["env"][KEY] == phrase

    def test_refused_desktop_redeploy_scrubs_a_legacy_fleet_only_spec_on_its_worker(self, db):
        phrase = " ".join(f"test-only-word-{index}" for index in range(12))
        container_id = "abc123def456"
        asyncio.run(
            database.upsert_worker(
                CLIENT_ID,
                containers=json.dumps([{"slug": SLUG, "container_id": container_id}]),
                system_info=json.dumps({"device_type": "desktop"}),
            )
        )
        asyncio.run(database.save_deployment(SLUG, container_id, spec={"env": {**ENV, KEY: phrase}}))

        result, sent = _deploy({}, wallet_seed={"mode": "import", "phrase": phrase})
        assert isinstance(result, HTTPException) and result.status_code == 409
        assert sent == []
        assert asyncio.run(database.get_deployment_spec(SLUG)) == {"env": ENV}


class TestAnOlderWorker:
    FEATURES = ("instances",)

    def test_a_new_wallet_there_is_refused(self, db):
        result, sent = _deploy(dict(ENV), features=self.FEATURES, wallet_seed={"mode": "generate"})
        assert isinstance(result, HTTPException) and result.status_code == 409
        assert sent == []

    def test_a_joined_desktop_is_not_called_too_old(self, db):
        """A Desktop keeps the seed in a file too, but makes the wallet in its own window."""
        with patch.object(main, "_worker_is_desktop", AsyncMock(return_value=True)):
            result, sent = _deploy(dict(ENV), features=self.FEATURES, wallet_seed={"mode": "generate"})
        assert isinstance(result, HTTPException) and result.status_code == 409
        assert "too old" not in str(result.detail)
        assert "CashPilot Desktop" in str(result.detail)
        assert sent == []

    def test_a_running_deployment_keeps_working_the_old_way(self, db):
        """Until the worker is updated, its node still needs the variable."""
        _record_legacy_deployment()
        result, sent = _deploy(dict(ENV), features=self.FEATURES)
        assert not isinstance(result, HTTPException), result
        assert sent[0]["json"]["env"][KEY] == PHRASE
        assert "wallet_seed" not in sent[0]["json"]


class TestARestore:
    def _choice(self, features, recorded, *, desktop=False):
        async def run():
            with (
                patch.object(main, "_worker_features", AsyncMock(return_value=set(features))),
                patch.object(main, "_worker_is_desktop", AsyncMock(return_value=desktop)),
            ):
                return await main._wallet_choice(
                    catalog.get_service(SLUG), main.DeployRequest(), 1, {}, recorded, {"sha256": "x"}
                )

        return asyncio.run(run())

    def test_the_volume_brings_the_file_so_the_variable_goes(self):
        assert self._choice({"wallet_seed_file"}, {}) == (KEY, None)

    def test_a_backup_from_before_the_file_keeps_the_variable(self):
        """Its volume may hold no file, and the node must still find its wallet."""
        assert self._choice({"wallet_seed_file"}, {KEY: PHRASE}) == (None, None)
        assert self._choice(set(), {KEY: PHRASE}) == (None, None)

    def test_a_desktop_restore_is_refused_before_the_wallet_can_travel(self):
        with pytest.raises(HTTPException) as exc:
            self._choice({"wallet_seed_file"}, {}, desktop=True)
        assert exc.value.status_code == 409
        assert "runs only on the machine that holds its wallet" in exc.value.detail


class TestTheRawDeployRecord:
    def test_a_capable_worker_s_record_drops_the_phrase_and_the_choice(self, db):
        spec = {"image": "i", "env": {**ENV, KEY: PHRASE}, "wallet_seed": {"mode": "import", "phrase": PHRASE}}
        with patch.object(main, "_worker_features", AsyncMock(return_value={"wallet_seed_file"})):
            recorded = asyncio.run(main._recordable_raw_spec(SLUG, 1, spec))
        assert not _words_of(str(recorded))
        assert recorded["env"] == ENV


class TestTheReveal:
    def _reveal(self, password="pw", features=("wallet_seed_file",)):
        proxied = AsyncMock(return_value={"phrase": PHRASE})

        async def run():
            with (
                patch.object(main, "_require_owner_session", lambda r: OWNER),
                patch.object(main, "_resolve_worker_id", AsyncMock(return_value=1)),
                patch.object(main, "_worker_features", AsyncMock(return_value=set(features))),
                patch.object(main, "require_step_up", AsyncMock()) as stepped,
                patch.object(main, "_sign_for_worker", AsyncMock(return_value="approval")),
                patch.object(main, "_proxy_to_worker", proxied),
            ):
                try:
                    answer = await main.api_wallet_seed_reveal(
                        _request(), SLUG, main.WalletRevealRequest(step_up_password=password), 1
                    )
                except HTTPException as exc:
                    return exc, stepped, proxied
                return answer, stepped, proxied

        return asyncio.run(run())

    @pytest.fixture(autouse=True)
    def _fresh_limit(self):
        main._WALLET_REVEALS.clear()
        yield
        main._WALLET_REVEALS.clear()

    def test_it_asks_for_the_password_first(self, db):
        refused, _stepped, proxied = self._reveal(password=None)
        assert refused.status_code == 403 and refused.detail["error"] == "step_up_required"
        proxied.assert_not_called()

    def test_it_reads_the_worker_with_a_signed_approval_and_audits_without_the_phrase(self, db):
        answer, stepped, proxied = self._reveal()
        assert answer.status_code == 200 and PHRASE in answer.body.decode()
        assert answer.headers["cache-control"] == "no-store"
        assert stepped.await_args.kwargs["action"] == step_up.ACTION_REVEAL_WALLET_SEED
        assert proxied.await_args.kwargs["headers"] == {step_up.APPROVAL_HEADER: "approval"}
        events = asyncio.run(database.get_audit_events())
        assert [e["action"] for e in events] == ["wallet_seed_reveal"]
        assert not _words_of(_everything_stored(db))

    def test_a_few_an_hour_at_most(self, db):
        for _ in range(main.WALLET_REVEAL_LIMIT):
            assert self._reveal()[0].status_code == 200
        assert self._reveal()[0].status_code == 429

    def test_an_older_worker_has_nothing_to_read(self, db):
        assert self._reveal(features=())[0].status_code == 409


#: Deploy bodies the model rejects, each carrying the phrase: FastAPI's 422 echoes rejected input.
BAD_BODIES = [
    {"env": {**ENV, KEY: [PHRASE]}},
    {"env": ENV, "wallet_seed": {"mode": "bogus", "phrase": PHRASE}},
]


@pytest.mark.parametrize("body", BAD_BODIES)
def test_a_rejected_deploy_body_does_not_echo_the_phrase(body):
    client = TestClient(main.app, raise_server_exceptions=False)
    with patch.object(auth, "get_current_user", return_value=OWNER):
        resp = client.post(f"/api/deploy/{SLUG}", json=body)
    assert resp.status_code == 422
    assert not _words_of(resp.text)


# ---------------------------------------------------------------------------
# The worker: the container env, the file, the generator, the reveal
# ---------------------------------------------------------------------------


def _tar_of(name: str, content: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name)
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


class _Docker:
    """A Docker client with no hostd container yet, whose volume holds ``file`` (None: no file)."""

    def __init__(self, file: bytes | None = None, printed: str | None = None):
        self.client = MagicMock()
        self.client.containers.get.side_effect = orchestrator.NotFound("nope")
        made = MagicMock()
        made.id = made.short_id = "new"
        self.client.containers.run.return_value = made
        self.helpers: dict[str, MagicMock] = {}
        self.created: list[dict] = []

        def create(**kwargs):
            self.created.append(kwargs)
            box = MagicMock()
            if kwargs["name"].endswith(".wallet-new"):
                box.wait.return_value = {"StatusCode": 0}
                box.logs.return_value = (printed or f"Recovery Phrase: {NEW}\nAddress {ADDRESS}\n").encode()
            elif file is None:
                box.get_archive.side_effect = orchestrator.NotFound("no file")
            else:
                box.get_archive.return_value = (iter([_tar_of("hostd.yml", file)]), {})
            box.put_archive.return_value = True
            self.helpers[kwargs["name"]] = box
            return box

        self.client.containers.create.side_effect = create

    def deploy(self, env, wallet_seed=None):
        wallet: dict = {}
        with (
            patch.object(orchestrator, "_CONTAINER_NETWORK", ""),
            patch.object(orchestrator, "available_runtimes", return_value={"runc"}),
            patch.object(orchestrator, "_get_client", return_value=self.client),
            patch.object(orchestrator, "get_service", catalog.get_service),
        ):
            orchestrator.deploy_raw(
                slug=SLUG,
                image="ghcr.io/siafoundation/hostd",
                env=env,
                volumes=VOLUMES,
                wallet_seed=wallet_seed,
                wallet=wallet,
            )
        return wallet

    @property
    def run_env(self) -> dict:
        env = self.client.containers.run.call_args.kwargs["environment"]
        return dict(env) if isinstance(env, dict) else dict(e.split("=", 1) for e in env)

    def written(self) -> tuple[tarfile.TarInfo, bytes]:
        helper = self.helpers[f"cashpilot-{SLUG}.wallet"]
        where, data = helper.put_archive.call_args.args
        assert where == "/run/cashpilot-secret"
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            [member] = tar.getmembers()
            return member, tar.extractfile(member).read()


class TestTheWorkerDeploy:
    def test_a_phrase_in_the_env_never_reaches_the_container(self):
        """Watched failing on the code before the fix: the container env held the phrase."""
        docker = _Docker()
        docker.deploy({**ENV, KEY: PHRASE})
        assert KEY not in docker.run_env
        assert not _words_of(str(docker.client.containers.run.call_args))

    def test_it_goes_into_the_file_in_the_volume_readable_by_its_owner_only(self):
        docker = _Docker()
        wallet = docker.deploy({**ENV, KEY: PHRASE})
        member, content = docker.written()
        assert member.name == "wallet/hostd.yml" and member.mode == 0o600
        assert content.decode() == f"recoveryPhrase: {PHRASE}\n"
        assert wallet == {"created": True, "address": None, "phrase": None}
        # The helper mounts the volume where the socket proxy lets the worker write, and goes.
        helper = docker.created[0]
        assert helper["network_mode"] == "none" and helper["mounts"][0]["Target"] == "/run/cashpilot-secret/wallet"
        docker.helpers[f"cashpilot-{SLUG}.wallet"].remove.assert_called_once_with(force=True)

    def test_a_new_wallet_is_made_offline_by_the_image_and_comes_back_once(self, caplog):
        caplog.set_level(logging.DEBUG)
        docker = _Docker()
        wallet = docker.deploy(dict(ENV), {"mode": "generate"})
        assert wallet == {"created": True, "address": ADDRESS, "phrase": NEW}
        gen = next(c for c in docker.created if c["name"].endswith(".wallet-new"))
        assert gen["command"] == ["seed"] and gen["network_mode"] == "none"
        # Its output holds the phrase: local json-file logs that go with the container, never a log shipper.
        assert gen["log_config"]["Type"] == "json-file"
        docker.helpers[f"cashpilot-{SLUG}.wallet-new"].remove.assert_called_once_with(force=True)
        assert docker.written()[1].decode() == f"recoveryPhrase: {NEW}\n"
        assert KEY not in docker.run_env
        assert not _words_of(caplog.text)

    def test_a_redeploy_keeps_the_file_and_shows_nothing(self):
        docker = _Docker(file=f"recoveryPhrase: {PHRASE}\n".encode())
        assert docker.deploy(dict(ENV), {"mode": "keep"}) == {"created": False, "address": None, "phrase": None}
        docker.helpers[f"cashpilot-{SLUG}.wallet"].put_archive.assert_not_called()

    def test_another_settings_in_the_file_are_kept(self):
        docker = _Docker(file=b"http:\n  address: :9980\n")
        docker.deploy(dict(ENV), {"mode": "import", "phrase": PHRASE})
        assert docker.written()[1].decode() == f"http:\n  address: :9980\nrecoveryPhrase: {PHRASE}\n"

    @pytest.mark.parametrize(
        ("file", "wanted", "code"),
        [
            (f"recoveryPhrase: {PHRASE}\n".encode(), {"mode": "import", "phrase": OTHER}, "wallet_exists"),
            (None, {"mode": "keep"}, "wallet_missing"),
            (b"recoveryPhrase: [unclosed\n", {"mode": "import", "phrase": PHRASE}, "wallet_file_invalid"),
            (None, {"mode": "import", "phrase": PHRASE.replace("yellow", "zoo")}, "wallet_phrase"),
        ],
    )
    def test_a_refusal_leaves_the_running_node_alone(self, file, wanted, code):
        docker = _Docker(file=file)
        with pytest.raises(orchestrator.WalletSeedRefused) as refused:
            docker.deploy(dict(ENV), wanted)
        assert refused.value.code == code
        assert not _words_of(str(refused.value))
        docker.client.containers.run.assert_not_called()

    def test_a_generator_that_prints_no_wallet_stops_the_deploy(self):
        docker = _Docker(printed="something else\n")
        with pytest.raises(orchestrator.WalletSeedRefused) as refused:
            docker.deploy(dict(ENV), {"mode": "generate"})
        assert refused.value.code == "wallet_generate"
        docker.client.containers.run.assert_not_called()

    def test_another_service_s_env_is_untouched(self):
        docker = _Docker()
        with (
            patch.object(orchestrator, "_CONTAINER_NETWORK", ""),
            patch.object(orchestrator, "available_runtimes", return_value={"runc"}),
            patch.object(orchestrator, "_get_client", return_value=docker.client),
        ):
            orchestrator.deploy_raw(slug="honeygain", image="honeygain/honeygain", env={KEY: "x"})
        assert docker.run_env[KEY] == "x"
        docker.client.containers.create.assert_not_called()


@pytest.fixture
def worker(monkeypatch):
    @contextlib.asynccontextmanager
    async def _noop(app):
        yield

    worker_api.app.router.lifespan_context = _noop
    monkeypatch.setattr(worker_api, "API_KEY", "wk-test")
    monkeypatch.setattr(worker_api, "_worker_key", WORKER_KEY)
    monkeypatch.setattr(worker_api, "CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(worker_api.orchestrator, "get_service", catalog.get_service)
    return TestClient(worker_api.app, raise_server_exceptions=False)


class TestTheWorkerReveal:
    HEADERS = {"Authorization": f"Bearer {WORKER_KEY}"}

    def _post(self, worker, approval=None):
        headers = dict(self.HEADERS)
        if approval:
            headers[step_up.APPROVAL_HEADER] = approval
        node = MagicMock()
        node.get_archive.return_value = (iter([_tar_of("hostd.yml", f"recoveryPhrase: {PHRASE}\n".encode())]), {})
        with patch.object(worker_api.orchestrator, "_find_container", return_value=node):
            return worker.post(f"/api/containers/{SLUG}/wallet-seed", headers=headers), node

    def test_the_fleet_key_alone_reads_nothing(self, worker):
        resp, node = self._post(worker)
        assert resp.status_code == 403 and not _words_of(resp.text)
        node.get_archive.assert_not_called()

    def test_an_approval_for_another_action_reads_nothing(self, worker):
        target = step_up.reveal_target(SLUG, CLIENT_ID)
        resp, _node = self._post(worker, step_up.sign(WORKER_KEY, step_up.ACTION_RESTORE, target))
        assert resp.status_code == 403

    def test_the_owner_s_approval_reads_the_file(self, worker, caplog):
        caplog.set_level(logging.DEBUG)
        approval = step_up.sign(WORKER_KEY, step_up.ACTION_REVEAL_WALLET_SEED, step_up.reveal_target(SLUG, CLIENT_ID))
        resp, node = self._post(worker, approval)
        assert resp.status_code == 200 and resp.json() == {"phrase": PHRASE}
        assert resp.headers["cache-control"] == "no-store"
        node.get_archive.assert_called_once_with("/data/hostd.yml")
        assert not _words_of(caplog.text)

    @pytest.mark.parametrize("body", BAD_BODIES)
    def test_a_rejected_deploy_body_does_not_echo_the_phrase(self, worker, body):
        resp = worker.post(f"/api/containers/{SLUG}/deploy", json={"image": "i", **body}, headers=self.HEADERS)
        assert resp.status_code == 422
        assert not _words_of(resp.text)

    def test_the_heartbeat_says_it_keeps_the_file(self):
        import inspect

        assert "wallet_seed.FEATURE" in inspect.getsource(worker_api._send_heartbeat)


# ---------------------------------------------------------------------------
# The catalog and the phrase rules
# ---------------------------------------------------------------------------


class TestTheCatalog:
    def test_sia_hostd_keeps_its_seed_in_its_data_volume(self):
        from app import wallet_seed

        var = wallet_seed.seed_var(catalog.get_service(SLUG))
        assert var["key"] == KEY and var["seed_file"]["path"] == "/data/hostd.yml"
        assert wallet_seed.validate_spec(var, {"/data", "/storage"}) == []

    def test_a_seed_file_outside_every_volume_or_on_a_plain_variable_is_refused(self):
        from app import wallet_seed

        var = {**wallet_seed.seed_var(catalog.get_service(SLUG))}
        assert any("volumes" in e for e in wallet_seed.validate_spec(var, {"/storage"}))
        assert any("secret" in e for e in wallet_seed.validate_spec({**var, "secret": False}, {"/data"}))

    def test_the_drift_check_does_not_want_the_variable_back(self):
        from app import drift

        svc = catalog.get_service(SLUG)
        shape = {"image": svc["docker"]["image"], "env_keys": ["HOSTD_API_PASSWORD"]}
        assert not any(KEY in finding for finding in drift.container_drift(svc, shape, None))


class TestPhraseRules:
    @pytest.mark.parametrize("phrase", [PHRASE, OTHER, NEW, "abandon " * 11 + "about", f"  {PHRASE.upper()} "])
    def test_valid_phrases_pass(self, phrase):
        from app import wallet_seed

        assert wallet_seed.phrase_problem(phrase) is None

    @pytest.mark.parametrize(
        ("phrase", "says"),
        [
            (" ".join(PHRASE.split()[:11]), "has 11"),
            (PHRASE.replace("winner", "winnr"), "Words 2, 10 are not"),
            (PHRASE.replace("yellow", "yelow"), "Word 12 is not"),
            (PHRASE.replace("yellow", "zoo"), "does not check out"),
            (PHRASE + " " + PHRASE, "has 24"),
        ],
    )
    def test_a_wrong_phrase_says_why_without_its_words(self, phrase, says):
        from app import wallet_seed

        problem = wallet_seed.phrase_problem(phrase)
        assert says in problem
        assert "winnr" not in problem and not _words_of(problem)

    def test_the_wordlist_is_bip39_english(self):
        import hashlib
        from pathlib import Path

        import app

        data = (Path(app.__file__).parent / "bip39_english.txt").read_bytes()
        assert hashlib.sha256(data).hexdigest().startswith("2f5eed53")


# ---------------------------------------------------------------------------
# The page: the password prompt in front of a reveal
# ---------------------------------------------------------------------------

APP_JS = Path(__file__).resolve().parents[1] / "app/static/js/app.js"

_PROMPT_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const at = src.indexOf('function showStepUp(');
let depth = 0, i = src.indexOf('{', at);
for (; i < src.length; i++) {
  if (src[i] === '{') depth++;
  else if (src[i] === '}' && --depth === 0) break;
}
const el = () => ({ classList: { set: new Set(), add(c) { this.set.add(c); }, remove(c) { this.set.delete(c); },
  contains(c) { return this.set.has(c); } }, value: '', focus() {}, isConnected: true });
const els = Object.fromEntries(['stepup-modal', 'stepup-password', 'stepup-message', 'stepup-submit',
  'stepup-cancel', 'stepup-close'].map((id) => [id, el()]));
const document = { getElementById: (id) => els[id], activeElement: null };
class MutationObserver { observe() {} disconnect() {} }
const showStepUp = new Function('document', 'MutationObserver', 'setTimeout',
  src.slice(at, i + 1) + '; return showStepUp;')(document, MutationObserver, () => {});
const answer = showStepUp('why');
const input = els['stepup-password'];
input.value = 'pw';
let prevented = false;
input.onkeydown({ key: 'Enter', preventDefault() { prevented = true; } });
answer.then((value) => console.log(JSON.stringify({ value, prevented })));
"""


def test_enter_in_the_password_prompt_does_not_press_the_button_again():
    """Seen in the e2e run: focus went back to Show seed phrase, and the same Enter
    pressed it, so a second prompt stayed open over the revealed phrase."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    out = subprocess.run(
        [node, "-e", _PROMPT_HARNESS, str(APP_JS)], capture_output=True, text=True, check=True, timeout=30
    )
    assert json.loads(out.stdout) == {"value": "pw", "prevented": True}
