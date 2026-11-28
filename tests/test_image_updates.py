"""Automatic app image updates: the worker's check and check period, and the UI's decisions.

The design is in app/image_updates.py. These pin the rules that keep it safe:
an unchanged build is never recreated, a build that fails its check period is
undone and never tried again on that box, Off checks nothing and Notify only
changes nothing, and only a copy the blank redeploy rebuilds as it runs is
updated by itself.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app import database, image_updates, orchestrator
from tests import test_mysterium_fenced as fenced
from tests.test_mysterium_fenced import _FakeDocker, _raw_deploy, _running_old

# The fixture the fenced tests use, shared rather than copied.
markers = fenced.markers
HONEYGAIN = {"cashpilot.service": "honeygain", "cashpilot.managed": "true"}


# ---------------------------------------------------------------------------
# The worker: a check period after the new container starts
# ---------------------------------------------------------------------------


def _deploy(docker, old, **kwargs):
    return _raw_deploy(client=docker.client, old=old, slug="honeygain", **kwargs)


def _docker(new_status="running", **new_attrs):
    old = _running_old("cashpilot-honeygain", HONEYGAIN)
    old.attrs = {"Mounts": [], "Image": "sha256:old"}
    docker = _FakeDocker(old)
    docker.created.status = new_status
    docker.created.attrs = {"Image": "sha256:new", "State": {"Status": new_status}, "RestartCount": 0, **new_attrs}
    docker.created.logs.return_value = b""
    return old, docker


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(orchestrator, "_SETTLE_POLL_SECONDS", 0)


class TestCheckPeriod:
    def test_a_new_build_that_stops_is_undone_and_the_old_container_runs_again(self, markers, fast):
        old, docker = _docker("exited", State={"Status": "exited", "ExitCode": 1})
        with pytest.raises(orchestrator.ImageUpdateFailed) as failed:
            _deploy(docker, old, settle_seconds=0.01)
        assert "undone" in str(failed.value) and "put back and is running again" in str(failed.value)
        assert docker.get("cashpilot-honeygain") is old and not old.removed
        old.start.assert_called_once()
        assert docker.created.removed
        docker.client.images.remove.assert_not_called()

    def test_a_restart_by_docker_fails_the_check(self, markers, fast):
        old, docker = _docker(RestartCount=2)
        with pytest.raises(orchestrator.ImageUpdateFailed, match=r"restarted by Docker \(2x\)"):
            _deploy(docker, old, settle_seconds=0.01)
        assert docker.get("cashpilot-honeygain") is old

    def test_an_unhealthy_image_health_check_fails_the_check(self, markers, fast):
        old, docker = _docker(State={"Status": "running", "Health": {"Status": "unhealthy"}})
        with pytest.raises(orchestrator.ImageUpdateFailed, match="unhealthy"):
            _deploy(docker, old, settle_seconds=0.01)

    def test_a_catalog_failure_signal_in_the_new_log_fails_the_check(self, markers, fast, monkeypatch):
        old, docker = _docker()
        docker.created.logs.return_value = b"update server cannot be reached\n"
        signal = {"pattern": "cannot be reached", "unless": "connected to server", "means": "It cannot start."}
        monkeypatch.setattr(orchestrator, "get_service", lambda slug: {"docker": {"health_signals": [signal]}})
        with pytest.raises(orchestrator.ImageUpdateFailed, match="It cannot start"):
            _deploy(docker, old, settle_seconds=0.01)
        assert docker.get("cashpilot-honeygain") is old

    def test_an_unless_line_or_an_idle_signal_is_not_a_failure(self, markers, fast, monkeypatch):
        old, docker = _docker()
        docker.created.logs.return_value = b"cannot be reached\nconnected to server\nno traffic yet\n"
        signals = [
            {"pattern": "cannot be reached", "unless": "connected to server"},
            {"pattern": "no traffic", "state": "idle"},
        ]
        monkeypatch.setattr(orchestrator, "get_service", lambda slug: {"docker": {"health_signals": signals}})
        _deploy(docker, old, settle_seconds=0.01)
        assert old.removed

    def test_a_healthy_build_replaces_the_old_and_its_image_goes(self, markers, fast):
        old, docker = _docker()
        report: dict = {}
        _deploy(docker, old, settle_seconds=0.01, image_update=report)
        assert old.removed and docker.get("cashpilot-honeygain") is docker.created
        docker.client.images.remove.assert_called_once_with("sha256:old")
        assert report == {"old_image": "sha256:old", "new_image": "sha256:new", "old_kept": ""}

    def test_the_proxy_refusing_the_delete_keeps_the_image_and_says_why(self, markers, fast):
        old, docker = _docker()
        refused = orchestrator.APIError("403 Forbidden", response=MagicMock(status_code=403))
        docker.client.images.remove.side_effect = refused
        report: dict = {}
        _deploy(docker, old, settle_seconds=0.01, image_update=report)
        assert old.removed
        assert "socket proxy" in report["old_kept"]

    def test_a_plain_deploy_has_no_check_period_and_deletes_no_image(self, markers, fast):
        old, docker = _docker("exited")
        _deploy(docker, old)
        assert old.removed
        docker.client.images.remove.assert_not_called()


def _image(image_id, digest="", ref="honeygain/honeygain"):
    return MagicMock(id=image_id, attrs={"RepoDigests": [f"{ref}@{digest}"] if digest else []})


class TestCheckImage:
    def _client(self, running_id, latest_id, ref="honeygain/honeygain:latest"):
        c = MagicMock(id="c1", status="running", labels=HONEYGAIN)
        c.attrs = {"Image": running_id, "Config": {"Image": ref}}
        client = MagicMock()
        client.containers.list.return_value = [c]
        images = {ref: _image(latest_id, "sha256:" + latest_id[-4:]), running_id: _image(running_id, "sha256:aaaa")}
        client.images.get.side_effect = lambda r: images[r]
        return client

    def test_an_unchanged_build_says_so(self):
        client = self._client("sha256:same", "sha256:same")
        with patch.object(orchestrator, "_get_client", return_value=client):
            answer = orchestrator.check_image("honeygain")
        client.images.pull.assert_called_once_with("honeygain/honeygain:latest")
        assert answer["floating"] and answer["latest"]["id"] == answer["containers"][0]["image_id"]

    def test_a_moved_tag_names_both_builds(self):
        client = self._client("sha256:old", "sha256:beef")
        with patch.object(orchestrator, "_get_client", return_value=client):
            answer = orchestrator.check_image("honeygain")
        assert answer["latest"] == {"id": "sha256:beef", "digest": "sha256:beef"}
        assert answer["containers"][0]["digest"] == "sha256:aaaa"

    @pytest.mark.parametrize("ref", ["honeygain/honeygain@sha256:" + "a" * 64, "sha256:" + "b" * 64])
    def test_a_pinned_image_is_not_pulled(self, ref):
        client = self._client("sha256:old", "sha256:new", ref=ref)
        with patch.object(orchestrator, "_get_client", return_value=client):
            assert orchestrator.check_image("honeygain")["floating"] is False
        client.images.pull.assert_not_called()

    def test_floating_refs(self):
        assert orchestrator.floating_ref("busybox")
        assert orchestrator.floating_ref("localhost:5000/x:latest")
        assert not orchestrator.floating_ref("x@sha256:" + "a" * 64)
        assert not orchestrator.floating_ref("")


# ---------------------------------------------------------------------------
# The UI: what a run does with the worker's answer
# ---------------------------------------------------------------------------


def _answer(running="sha256:old", latest="sha256:new", status="running", floating=True):
    return {
        "floating": floating,
        "ref": "honeygain/honeygain:latest",
        "latest": {"id": latest, "digest": "sha256:" + latest[-3:]},
        "containers": [{"instance": 1, "container_id": "c1", "status": status, "image_id": running, "digest": "d"}],
    }


class _Hooks:
    def __init__(self, answer, *, blocker="", deploy=None, seen=()):
        self.rows: list[tuple] = []
        self.deploys: list[tuple] = []
        self.checks = 0
        self._seen = set(seen)
        self._answer, self._blocker, self._deploy = answer, blocker, deploy

    def hooks(self):
        async def check(wid, slug):
            self.checks += 1
            return self._answer

        async def blocker(wid, slug, answer):
            return self._blocker

        async def deploy(wid, slug, expected):
            self.deploys.append((wid, slug, expected))
            if isinstance(self._deploy, Exception):
                raise self._deploy
            return self._deploy or {"image_update": {"new_image": "sha256:new", "old_kept": ""}}

        async def record(wid, slug, result, **facts):
            self.rows.append((result, facts))
            self._seen.add((result, facts.get("new_image")))

        async def seen(wid, slug, new_image, results):
            return any((r, new_image) in self._seen for r in results)

        return image_updates.Hooks(
            check=check, blocker=blocker, deploy=deploy, record=record, seen=seen, sleep=AsyncMock()
        )


async def _run(state, mode):
    return await image_updates.update_service(state.hooks(), 1, "honeygain", mode)


@pytest.mark.asyncio
class TestDecisions:
    async def test_off_checks_nothing(self):
        state = _Hooks(_answer())
        assert await _run(state, image_updates.OFF) == "off"
        assert state.checks == 0 and not state.deploys and not state.rows

    async def test_an_unchanged_build_is_a_no_op(self):
        state = _Hooks(_answer(running="sha256:new"))
        assert await _run(state, image_updates.AUTO) == "current"
        assert not state.deploys and not state.rows

    async def test_a_pinned_image_is_left_to_releases(self):
        state = _Hooks(_answer(floating=False))
        assert await _run(state, image_updates.AUTO) == "pinned"
        assert not state.deploys

    async def test_notify_only_records_once_and_deploys_nothing(self):
        state = _Hooks(_answer())
        assert await _run(state, image_updates.NOTIFY) == "available"
        assert await _run(state, image_updates.NOTIFY) == "available"
        assert [r for r, _ in state.rows] == ["available"]
        assert not state.deploys

    async def test_auto_runs_the_blank_redeploy_against_the_checked_containers(self):
        state = _Hooks(_answer())
        assert await _run(state, image_updates.AUTO) == "updated"
        assert state.deploys == [(1, "honeygain", {"1": "c1"})]
        result, facts = state.rows[0]
        assert result == "updated" and facts["old_image"] == "sha256:old" and facts["new_image"] == "sha256:new"

    async def test_a_rolled_back_build_is_held_so_it_never_loops(self):
        state = _Hooks(_answer(), deploy=image_updates.DeployRefused("undone", rolled_back=True))
        assert await _run(state, image_updates.AUTO) == "rolled_back"
        for _ in range(3):
            assert await _run(state, image_updates.AUTO) == "held"
        assert len(state.deploys) == 1
        # A newer build is tried.
        state._answer = _answer(latest="sha256:newer")
        state._deploy = None
        assert await _run(state, image_updates.AUTO) == "updated"

    async def test_a_failed_deploy_is_not_held_and_is_tried_at_the_next_run(self):
        state = _Hooks(_answer(), deploy=image_updates.DeployRefused("registry down", rolled_back=False))
        assert await _run(state, image_updates.AUTO) == "failed"
        assert await _run(state, image_updates.AUTO) == "failed"
        assert len(state.deploys) == 2

    async def test_a_blocked_copy_is_reported_once_and_never_recreated(self):
        state = _Hooks(_answer(), blocker="it differs from what a redeploy builds")
        assert await _run(state, image_updates.AUTO) == "skipped"
        assert await _run(state, image_updates.AUTO) == "skipped"
        assert [r for r, _ in state.rows] == ["skipped"] and not state.deploys

    async def test_a_stopped_copy_is_not_started_by_an_update(self):
        state = _Hooks(_answer(status="exited"))
        assert await _run(state, image_updates.AUTO) == "skipped"
        assert not state.deploys

    async def test_a_box_pauses_after_each_real_update(self):
        state = _Hooks(_answer())
        hooks = state.hooks()
        settings = image_updates.parse_settings({"mode": "auto"})
        out = await image_updates.run_worker(hooks, settings, 1, ["a", "b"])
        assert out == {"a": "updated", "b": "updated"}
        assert hooks.sleep.await_count == 2


class TestSettings:
    def test_the_most_specific_choice_wins(self):
        s = image_updates.parse_settings({"mode": "auto", "workers": {"2": "notify"}, "services": {"proxyrack": "off"}})
        assert image_updates.effective_mode(s, 1, "honeygain") == "auto"
        assert image_updates.effective_mode(s, 2, "honeygain") == "notify"
        assert image_updates.effective_mode(s, 2, "proxyrack") == "off"

    def test_anything_unreadable_is_off(self):
        assert image_updates.parse_settings("not json")["mode"] == "off"
        assert image_updates.parse_settings({"mode": "always", "hour": 99}) == {
            "mode": "off",
            "hour": image_updates.DEFAULT_HOUR,
            "workers": {},
            "services": {},
        }

    def test_a_run_is_due_once_a_day_from_the_hour(self):
        from datetime import datetime

        s = image_updates.parse_settings({"mode": "auto", "hour": 4})
        assert not image_updates.due(s, datetime(2026, 11, 28, 3, 59))
        assert image_updates.due(s, datetime(2026, 11, 28, 4, 0))
        s["last_run"] = "2026-11-28"
        assert not image_updates.due(s, datetime(2026, 11, 28, 23, 0))
        assert image_updates.due(s, datetime(2026, 11, 29, 4, 5))


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_DIR", tmp_path)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "cashpilot.db")
    return tmp_path


@pytest.mark.asyncio
class TestDefaults:
    async def test_a_new_install_updates_by_itself(self, db):
        await database.init_db()
        settings = image_updates.parse_settings(await database.get_config(image_updates.CONFIG_KEY))
        assert settings["mode"] == "auto" and "offer" not in settings

    async def test_an_upgraded_install_is_offered_and_stays_off(self, db):
        await database.init_db()
        # The install as it was before this release: no table, no setting.
        connection = await database._get_db()
        try:
            await connection.execute("DROP TABLE image_updates")
            await connection.execute("DELETE FROM config WHERE key = ?", (image_updates.CONFIG_KEY,))
            await connection.commit()
        finally:
            await connection.close()
        await database.init_db()
        settings = image_updates.parse_settings(await database.get_config(image_updates.CONFIG_KEY))
        assert settings["mode"] == "off" and settings["offer"] is True
        # A later start never changes the owner's choice.
        await database.set_config(image_updates.CONFIG_KEY, json.dumps({"mode": "notify", "hour": 3}))
        await database.init_db()
        assert image_updates.parse_settings(await database.get_config(image_updates.CONFIG_KEY))["mode"] == "notify"

    async def test_rows_are_recorded_and_found(self, db):
        await database.init_db()
        await database.record_image_update(1, "honeygain", "rolled_back", new_image="sha256:new", detail="x")
        assert await database.image_update_seen(1, "honeygain", "sha256:new", ("rolled_back",))
        assert not await database.image_update_seen(2, "honeygain", "sha256:new", ("rolled_back",))
        assert (await database.list_image_updates())[0]["result"] == "rolled_back"


def _worker_answer(status, payload):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    return resp


@pytest.mark.asyncio
class TestTheDashboardSide:
    """What the UI makes of the worker's answers, and the settings routes."""

    def test_the_workers_undo_reaches_the_dashboard_with_its_reason(self):
        from app.main import _safe_worker_detail

        message = (
            "The new cashpilot-x crashed and was restarted by Docker (1x) within its 120 s check, so it was undone."
        )
        detail = _safe_worker_detail(
            _worker_answer(409, {"detail": {"error": "image_update_rolled_back", "message": message}})
        )
        assert detail == {"error": "image_update_rolled_back", "message": message}

    async def test_an_undone_update_is_recorded_as_undone_and_so_held(self):
        """Seen live: without the worker's code the undo read as a plain failure, which is retried."""
        from fastapi import HTTPException

        from app import main

        refusal = HTTPException(
            status_code=409,
            detail=main._safe_worker_detail(
                _worker_answer(409, {"detail": {"error": "image_update_rolled_back", "message": "undone"}})
            ),
        )
        failed = HTTPException(status_code=502, detail="pull")
        with (
            patch.object(main, "_deploy", AsyncMock(side_effect=refusal)),
            pytest.raises(image_updates.DeployRefused) as caught,
        ):
            await main._image_update_deploy(1, "honeygain", {"1": "abc"})
        assert caught.value.rolled_back and str(caught.value) == "undone"
        with (
            patch.object(main, "_deploy", AsyncMock(side_effect=failed)),
            pytest.raises(image_updates.DeployRefused) as caught,
        ):
            await main._image_update_deploy(1, "honeygain", {"1": "abc"})
        assert not caught.value.rolled_back

    async def test_saving_keeps_the_last_run_and_ends_the_offer(self, db):
        from app import main

        await database.init_db()
        await database.set_config(
            image_updates.CONFIG_KEY, json.dumps({"mode": "off", "hour": 4, "offer": True, "last_run": "2026-11-28"})
        )
        body = main.ImageUpdateSettingsBody(mode="auto", hour=2, workers={"3": "notify", "4": None}, services={})
        saved = (await main.api_set_image_updates(body, _auth={"r": "owner"}))["settings"]
        assert saved["mode"] == "auto" and saved["hour"] == 2 and saved["workers"] == {"3": "notify"}
        assert saved["last_run"] == "2026-11-28" and "offer" not in saved

    async def test_check_now_does_not_use_up_the_daily_run(self, db):
        from app import main

        class FiveAm(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 11, 28, 5, 0)

        await database.init_db()
        with (
            patch.object(main, "datetime", FiveAm),
            patch.object(main.database, "list_workers", AsyncMock(return_value=[])),
            patch.object(main, "_refresh_image_update_bell", AsyncMock()),
        ):
            await main._run_image_updates(force=True)
            assert "last_run" not in await main._image_update_settings()
            # A new install is on Update automatically, and 05:00 is past its hour.
            await main._run_image_updates()
            assert (await main._image_update_settings())["last_run"] == "2026-11-28"
