"""Automatic app image updates: the worker's check and check period, and the UI's decisions.

The design is in app/image_updates.py. These pin the rules that keep it safe:
an unchanged build is never recreated, a build that fails its check period is
undone and never tried again on that box, Off checks nothing and Notify only
changes nothing, and only a copy the blank redeploy rebuilds as it runs is
updated by itself.
"""

from __future__ import annotations

import asyncio
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


@pytest.fixture(autouse=True)
def create_answers_an_id(monkeypatch):
    """Docker's create answer, as orchestrator._create_container_id reads it: the ID only."""
    monkeypatch.setattr(orchestrator, "_create_container_id", lambda client, kw: client.containers.create(**kw).id)


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

    def test_a_health_check_still_starting_at_the_end_does_not_pass(self, markers, fast, monkeypatch):
        monkeypatch.setattr(orchestrator, "_SETTLE_GRACE_SECONDS", 0.05)
        old, docker = _docker(State={"Status": "running", "Health": {"Status": "starting"}})
        with pytest.raises(orchestrator.ImageUpdateFailed, match="had not passed its own health check"):
            _deploy(docker, old, settle_seconds=0.01)
        assert docker.get("cashpilot-honeygain") is old and not old.removed

    def test_a_health_check_that_turns_healthy_in_the_grace_passes(self, markers, fast, monkeypatch):
        monkeypatch.setattr(orchestrator, "_SETTLE_GRACE_SECONDS", 5)
        old, docker = _docker(State={"Status": "running", "Health": {"Status": "starting"}})
        looks = []

        def reload():
            looks.append(1)
            if len(looks) > 3:
                docker.created.attrs["State"]["Health"]["Status"] = "healthy"

        docker.created.reload.side_effect = reload
        _deploy(docker, old, settle_seconds=0.01)
        assert old.removed

    def test_a_stop_while_the_final_log_is_read_fails_the_check(self, markers, fast, monkeypatch):
        signal = {"pattern": "cannot be reached", "means": "It cannot start."}
        monkeypatch.setattr(orchestrator, "get_service", lambda slug: {"docker": {"health_signals": [signal]}})
        old, docker = _docker()

        def logs(**kwargs):
            # The container exits while Docker streams its log, with no failure line.
            docker.created.status = "exited"
            docker.created.attrs["State"] = {"Status": "exited", "ExitCode": 3}
            return b"starting\n"

        docker.created.logs.side_effect = logs
        with pytest.raises(orchestrator.ImageUpdateFailed, match="exit code 3"):
            _deploy(docker, old, settle_seconds=0.01)
        assert docker.get("cashpilot-honeygain") is old

    def test_a_fence_that_goes_during_an_update_puts_the_old_node_back(self, markers, fast):
        # A manual deploy leaves the new node to the fence guard. An update must
        # not: the guard would start a build nobody checked.
        old = fenced._running_old()
        docker = _FakeDocker(old)
        with (
            patch.object(orchestrator, "_require_fence", side_effect=orchestrator.ContainerNetworkError("gone")),
            pytest.raises(orchestrator.ContainerRuntimeError) as failed,
        ):
            fenced._raw_deploy(client=docker.client, old=old, settle_seconds=0.01)
        assert not isinstance(failed.value, orchestrator.ImageUpdateFailed)
        assert docker.get("cashpilot-mysterium") is old and not old.removed
        assert docker.created.removed
        # The control: a manual deploy keeps the old behaviour.
        old = fenced._running_old()
        docker = _FakeDocker(old)
        with (
            patch.object(orchestrator, "_require_fence", side_effect=orchestrator.ContainerNetworkError("gone")),
            pytest.raises(orchestrator.ContainerNetworkError),
        ):
            fenced._raw_deploy(client=docker.client, old=old)
        assert old.removed and not docker.created.removed

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

    def test_an_unless_line_written_later_in_the_period_still_cancels_the_signal(self, markers, fast, monkeypatch):
        # The failure line is in the log from the start, its unless line only
        # from halfway through the period. The log is judged once the period is
        # over, so the later line counts.
        import time as clock

        signal = {"pattern": "cannot be reached", "unless": "connected to server", "means": "It cannot start."}
        monkeypatch.setattr(orchestrator, "get_service", lambda slug: {"docker": {"health_signals": [signal]}})
        monkeypatch.setattr(orchestrator, "_SETTLE_POLL_SECONDS", 0.005)
        began = clock.monotonic()

        def logs(**kwargs):
            later = clock.monotonic() - began > 0.05
            return b"update server cannot be reached\n" + (b"connected to server\n" if later else b"")

        old, docker = _docker()
        docker.created.logs.side_effect = logs
        _deploy(docker, old, settle_seconds=0.1)
        assert old.removed

    def test_a_failure_line_with_no_unless_line_by_the_end_fails_the_check(self, markers, fast, monkeypatch):
        signal = {"pattern": "cannot be reached", "unless": "connected to server", "means": "It cannot start."}
        monkeypatch.setattr(orchestrator, "get_service", lambda slug: {"docker": {"health_signals": [signal]}})
        old, docker = _docker()
        docker.created.logs.return_value = b"update server cannot be reached\n"
        with pytest.raises(orchestrator.ImageUpdateFailed, match="It cannot start"):
            _deploy(docker, old, settle_seconds=0.02)
        assert docker.get("cashpilot-honeygain") is old

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

    def test_a_tag_that_moved_after_the_check_is_refused_before_anything_changes(self, markers, fast):
        old, docker = _docker()
        docker.client.images.get.return_value.id = "sha256:" + "b" * 64
        with pytest.raises(orchestrator.ContainerRuntimeError, match="moved to another build") as refused:
            _deploy(docker, old, settle_seconds=0.01, expect_image="sha256:" + "a" * 64)
        assert refused.value.status_code == 409
        assert docker.get("cashpilot-honeygain") is old and not old.removed
        old.stop.assert_not_called()
        docker.client.containers.create.assert_not_called()

    def test_the_checked_build_is_installed(self, markers, fast):
        old, docker = _docker(Image="sha256:" + "a" * 64)
        docker.client.images.get.return_value.id = "sha256:" + "a" * 64
        _deploy(docker, old, settle_seconds=0.01, expect_image="sha256:" + "a" * 64)
        assert old.removed

    def test_a_tag_moved_between_the_inspect_and_the_create_is_undone_and_not_held(self, markers, fast):
        # Docker reads the tag again at create time; another pull in between
        # gives the new container another build. It is undone, the previous
        # container runs again, and the error is not ImageUpdateFailed, so the
        # dashboard does not hold a build nobody tried.
        old, docker = _docker(Image="sha256:" + "b" * 64)
        docker.client.images.get.return_value.id = "sha256:" + "a" * 64
        with pytest.raises(orchestrator.ContainerRuntimeError, match="moved to another build") as refused:
            _deploy(docker, old, settle_seconds=0.01, expect_image="sha256:" + "a" * 64)
        assert not isinstance(refused.value, orchestrator.ImageUpdateFailed)
        assert refused.value.status_code == 409
        assert docker.get("cashpilot-honeygain") is old and not old.removed
        assert docker.created.removed
        # Created, checked and never started: the other build never ran on the volumes.
        docker.client.containers.run.assert_not_called()
        docker.created.start.assert_not_called()
        old.start.assert_called_once()

    def test_an_update_whose_create_gets_no_answer_is_undone_and_not_held(self, markers, fast, monkeypatch):
        # No answer to the create: whether Docker made it is unknown, and nothing
        # started it, so there is no start to wait out. The previous container
        # comes back at once.
        waited = MagicMock(side_effect=AssertionError("waited for a start nobody made"))
        monkeypatch.setattr(orchestrator, "_await_start", waited)
        old, docker = _docker(Image="sha256:" + "a" * 64)
        docker.client.images.get.return_value.id = "sha256:" + "a" * 64
        docker.client.containers.create.side_effect = orchestrator.requests.exceptions.ReadTimeout("no answer")
        with pytest.raises(orchestrator.ContainerRuntimeError) as failed:
            _deploy(docker, old, settle_seconds=0.01, expect_image="sha256:" + "a" * 64)
        waited.assert_not_called()
        assert not isinstance(failed.value, orchestrator.ImageUpdateFailed)
        assert docker.get("cashpilot-honeygain") is old
        docker.created.start.assert_not_called()
        old.start.assert_called_once()

    def test_only_a_look_that_starts_after_the_period_passes_it(self, markers, fast, monkeypatch):
        # The first look reads "running" but Docker takes 20 s to answer it, so
        # it ends after the 15 s period; the container stopped meanwhile. That
        # look cannot pass the period: the next one, which sees the stop, decides.
        clock = [0.0]
        monkeypatch.setattr(orchestrator.time, "monotonic", lambda: clock[0])
        old, docker = _docker()
        looks = iter(["running"])

        def reload():
            status = next(looks, "exited")
            if status == "running":
                clock[0] += 20
            docker.created.status = status
            docker.created.attrs["State"] = {"Status": status, "ExitCode": 1}

        docker.created.reload.side_effect = reload
        with pytest.raises(orchestrator.ImageUpdateFailed, match="stopped"):
            _deploy(docker, old, settle_seconds=15)
        assert docker.get("cashpilot-honeygain") is old

    def test_a_log_that_cannot_be_read_is_undone_when_it_has_signals(self, markers, fast, monkeypatch):
        monkeypatch.setattr(orchestrator, "_SETTLE_GRACE_SECONDS", 0.05)
        old, docker = _docker()
        docker.created.logs.side_effect = orchestrator.APIError("500 Server Error")
        signal = {"pattern": "cannot be reached", "means": "It cannot start."}
        monkeypatch.setattr(orchestrator, "get_service", lambda slug: {"docker": {"health_signals": [signal]}})
        with pytest.raises(orchestrator.ImageUpdateFailed, match="did not describe"):
            _deploy(docker, old, settle_seconds=0.01)
        assert docker.get("cashpilot-honeygain") is old

    def test_a_failure_line_far_back_in_a_long_log_still_counts(self, markers, fast, monkeypatch):
        old, docker = _docker()
        docker.created.logs.return_value = b"update server cannot be reached\n" + b"ordinary line\n" * 5000
        signal = {"pattern": "cannot be reached", "means": "It cannot start."}
        monkeypatch.setattr(orchestrator, "get_service", lambda slug: {"docker": {"health_signals": [signal]}})
        with pytest.raises(orchestrator.ImageUpdateFailed, match="It cannot start"):
            _deploy(docker, old, settle_seconds=0.01)
        assert "tail" not in docker.created.logs.call_args.kwargs

    def test_a_copy_stopped_after_the_check_is_not_started_by_the_update(self, markers, fast):
        old, docker = _docker()
        old.status = "exited"
        with pytest.raises(orchestrator.ContainerRuntimeError, match="was stopped after the check"):
            _deploy(docker, old, settle_seconds=0.01)
        assert docker.get("cashpilot-honeygain") is old and not old.removed
        old.start.assert_not_called()
        docker.client.containers.create.assert_not_called()

    def test_a_replacement_docker_cannot_describe_at_the_end_is_undone(self, markers, fast, monkeypatch):
        monkeypatch.setattr(orchestrator, "_SETTLE_GRACE_SECONDS", 0.05)
        old, docker = _docker()
        docker.created.reload.side_effect = orchestrator.APIError("500 Server Error")
        with pytest.raises(orchestrator.ImageUpdateFailed, match="did not describe"):
            _deploy(docker, old, settle_seconds=0.01)
        assert docker.get("cashpilot-honeygain") is old and not old.removed
        old.start.assert_called_once()

    def test_one_unreadable_look_then_a_good_one_passes(self, markers, fast, monkeypatch):
        monkeypatch.setattr(orchestrator, "_SETTLE_GRACE_SECONDS", 5)
        old, docker = _docker()
        looks = iter([orchestrator.APIError("500 Server Error")])

        def reload():
            if (error := next(looks, None)) is not None:
                raise error

        docker.created.reload.side_effect = reload
        _deploy(docker, old, settle_seconds=0.01)
        assert old.removed

    def test_stop_waits_for_a_deploy_that_holds_the_route_lock(self):
        # A deploy holds the route lock (deploy_raw, through its check period);
        # a Stop sent meanwhile stops the container only once it is released.
        import threading

        container = MagicMock(name="cashpilot-honeygain")
        holding, release, done = threading.Event(), threading.Event(), threading.Event()
        lock = orchestrator.route_gate.deploying("honeygain")
        free_during_stop: list[bool] = []

        def stop_call(**kwargs):
            # Another thread cannot take the route lock while the container stops.
            def probe():
                got = lock.acquire(blocking=False)
                if got:
                    lock.release()
                free_during_stop.append(got)

            prober = threading.Thread(target=probe)
            prober.start()
            prober.join()

        container.stop.side_effect = stop_call

        def deploy():
            with orchestrator.route_gate.deploying("honeygain"):
                holding.set()
                release.wait(5)

        def stop():
            with (
                patch.object(orchestrator, "_find_container", return_value=container),
                patch.object(orchestrator, "fence_gated", return_value=False),
            ):
                orchestrator.stop_service("honeygain")
            done.set()

        deployer = threading.Thread(target=deploy)
        deployer.start()
        assert holding.wait(5)
        stopper = threading.Thread(target=stop)
        stopper.start()
        assert not done.wait(0.3), "Stop ran while a deploy held the route lock"
        container.stop.assert_not_called()
        release.set()
        assert done.wait(5)
        container.stop.assert_called_once()
        assert free_during_stop == [False], "the container stopped outside the route lock"
        deployer.join()
        stopper.join()


class TestRepoDigest:
    def test_only_the_checked_repository_s_digest_is_named(self):
        image = MagicMock(attrs={"RepoDigests": ["mirror.example/other@sha256:" + "c" * 64]})
        assert orchestrator._repo_digest(image, "honeygain/honeygain:latest") == ""
        # Another registry's copy of the same path is another repository.
        image.attrs["RepoDigests"].append("mirror.example/honeygain/honeygain@sha256:" + "e" * 64)
        assert orchestrator._repo_digest(image, "honeygain/honeygain:latest") == ""
        image.attrs["RepoDigests"].append("docker.io/honeygain/honeygain@sha256:" + "d" * 64)
        assert orchestrator._repo_digest(image, "honeygain/honeygain:latest") == "sha256:" + "d" * 64

    @pytest.mark.parametrize(
        ("name", "full"),
        [
            ("busybox", "docker.io/library/busybox"),
            ("library/busybox", "docker.io/library/busybox"),
            ("docker.io/busybox", "docker.io/library/busybox"),
            ("honeygain/honeygain", "docker.io/honeygain/honeygain"),
            ("localhost/mine", "localhost/mine"),
            ("127.0.0.1:5000/mine", "127.0.0.1:5000/mine"),
            ("ghcr.io/org/app", "ghcr.io/org/app"),
            ("mirror.example/docker.io/busybox", "mirror.example/docker.io/busybox"),
        ],
    )
    def test_a_repository_is_spelled_in_full(self, name, full):
        assert orchestrator._repo_name(name) == full


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

        async def deploy(wid, slug, expected, new_image):
            self.deploys.append((wid, slug, expected, new_image))
            if isinstance(self._deploy, Exception):
                raise self._deploy
            # The worker installs the checked build.
            return self._deploy or {"image_update": {"new_image": new_image, "old_kept": ""}}

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
        # The checked build is the only one the worker may install.
        assert state.deploys == [(1, "honeygain", {"1": "c1"}, "sha256:new")]
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
        assert state.deploys[-1][3] == "sha256:newer"
        assert state.rows[-1][0] == "updated" and state.rows[-1][1]["new_image"] == "sha256:newer"

    async def test_a_mode_changed_during_the_check_deploys_and_records_nothing(self):
        state = _Hooks(_answer(), deploy=image_updates.ModeChanged("off"))
        assert await _run(state, image_updates.AUTO) == "off"
        assert not state.rows

    async def test_a_switch_to_notify_during_the_check_announces_the_build(self):
        # "off" would answer the bell's notice of a build that is still on offer.
        state = _Hooks(_answer(), deploy=image_updates.ModeChanged("notify"))
        assert await _run(state, image_updates.AUTO) == "available"
        assert [r[0] for r in state.rows] == ["available"]
        assert await _run(state, image_updates.AUTO) == "available"
        assert len(state.rows) == 1

    async def test_a_failed_deploy_is_not_held_and_is_tried_at_the_next_run(self):
        state = _Hooks(_answer(), deploy=image_updates.DeployRefused("registry down", rolled_back=False))
        assert await _run(state, image_updates.AUTO) == "failed"
        assert await _run(state, image_updates.AUTO) == "failed"
        assert len(state.deploys) == 2

    async def test_several_copies_are_reported_and_never_recreated(self):
        answer = _answer()
        answer["containers"].append({**answer["containers"][0], "instance": 2, "container_id": "c2"})
        state = _Hooks(answer)
        assert await _run(state, image_updates.AUTO) == "skipped"
        assert not state.deploys
        result, facts = state.rows[0]
        assert result == "skipped" and "2 copies" in facts["detail"]

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

    @pytest.mark.parametrize("bad", [["2"], "auto", 3, None])
    def test_an_override_that_is_not_a_map_is_none(self, bad):
        s = image_updates.parse_settings({"mode": "auto", "workers": bad, "services": bad})
        assert s["workers"] == {} and s["services"] == {}

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

    async def test_a_first_start_cut_off_before_the_setting_leaves_no_table(self, db, monkeypatch):
        # A start that fails after the schema and before the setting: nothing is
        # kept, so the next start still sees a new install and writes its setting.
        monkeypatch.setattr(database, "_image_updates_seed", lambda fresh: "\nINSERT INTO no_such_table VALUES (1);")
        with pytest.raises(Exception, match="no_such_table"):
            await database.init_db()
        connection = await database._get_db()
        try:
            cursor = await connection.execute("SELECT name FROM sqlite_master WHERE name = 'image_updates'")
            assert await cursor.fetchone() is None
        finally:
            await connection.close()
        monkeypatch.undo()
        monkeypatch.setattr(database, "DB_DIR", db)
        monkeypatch.setattr(database, "DB_PATH", db / "cashpilot.db")
        await database.init_db()
        settings = image_updates.parse_settings(await database.get_config(image_updates.CONFIG_KEY))
        assert settings["mode"] == "auto" and "offer" not in settings

    async def test_pruning_never_releases_a_held_build(self, db, monkeypatch):
        monkeypatch.setattr(database, "IMAGE_UPDATE_ROWS", 3)
        await database.init_db()
        await database.record_image_update(1, "honeygain", "rolled_back", new_image="sha256:bad")
        for n in range(6):
            await database.record_image_update(1, "honeygain", "available", new_image=f"sha256:{n}")
        assert await database.image_update_seen(1, "honeygain", "sha256:bad", ("rolled_back",))
        assert not await database.image_update_seen(1, "honeygain", "sha256:0", ("available",))

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

    async def test_the_workers_undo_reaches_the_dashboard_with_its_reason(self):
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
        auto = {"mode": "auto", "workers": {}, "services": {}}
        with (
            patch.object(main, "_image_update_settings", AsyncMock(return_value=auto)),
            patch.object(main, "_deploy", AsyncMock(side_effect=refusal)),
            pytest.raises(image_updates.DeployRefused) as caught,
        ):
            await main._image_update_deploy(1, "honeygain", {"1": "abc"}, "sha256:" + "a" * 64)
        assert caught.value.rolled_back and str(caught.value) == "undone"
        with (
            patch.object(main, "_image_update_settings", AsyncMock(return_value=auto)),
            patch.object(main, "_deploy", AsyncMock(side_effect=failed)),
            pytest.raises(image_updates.DeployRefused) as caught,
        ):
            await main._image_update_deploy(1, "honeygain", {"1": "abc"}, "sha256:" + "a" * 64)
        assert not caught.value.rolled_back

    async def test_a_choice_saved_during_the_check_is_the_one_that_decides(self):
        """The owner turned the app off while its check ran: nothing is deployed."""
        from app import main

        deploy = AsyncMock()
        saved = {"mode": "auto", "workers": {}, "services": {"honeygain": "off"}}
        with (
            patch.object(main, "_image_update_settings", AsyncMock(return_value=saved)),
            patch.object(main, "_deploy", deploy),
            pytest.raises(image_updates.ModeChanged),
        ):
            await main._image_update_deploy(1, "honeygain", {"1": "abc"}, "sha256:" + "a" * 64)
        deploy.assert_not_called()

    async def test_off_saved_while_the_custom_check_runs_is_the_one_that_decides(self):
        from app import main

        deploy = AsyncMock()
        settings = {"mode": "auto", "workers": {}, "services": {}}

        async def owner_turns_it_off(*_args):
            settings["services"] = {"custom-mine": "off"}
            return False

        with (
            patch.object(main, "_image_update_settings", AsyncMock(side_effect=lambda: dict(settings))),
            patch.object(main.database, "get_deployment_spec", AsyncMock(return_value={"env": {}})),
            patch.object(main, "_custom_values_unsaved", owner_turns_it_off),
            patch.object(main, "_deploy", deploy),
            pytest.raises(image_updates.ModeChanged),
        ):
            await main._image_update_deploy(1, "custom-mine", {"1": "abc"}, "sha256:" + "a" * 64)
        deploy.assert_not_called()

    async def test_a_custom_value_saved_after_the_blocker_is_not_deployed(self):
        from app import main

        deploy = AsyncMock()
        auto = {"mode": "auto", "workers": {}, "services": {}}
        with (
            patch.object(main, "_image_update_settings", AsyncMock(return_value=auto)),
            patch.object(main.database, "get_deployment_spec", AsyncMock(return_value={"env": {"A": "old"}})),
            patch.object(main, "_custom_values_unsaved", AsyncMock(return_value=True)),
            patch.object(main, "_deploy", deploy),
            pytest.raises(image_updates.DeployRefused) as caught,
        ):
            await main._image_update_deploy(1, "custom-mine", {"1": "abc"}, "sha256:" + "a" * 64)
        deploy.assert_not_called()
        assert "not deployed yet" in str(caught.value) and not caught.value.rolled_back

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
        from zoneinfo import ZoneInfo

        from app import main

        # 05:00 for the owner, in their own zone; the server's clock is not asked.
        five_am = datetime(2026, 11, 28, 5, 0, tzinfo=ZoneInfo("Asia/Singapore"))
        await database.init_db()
        with (
            patch.object(main, "_obligations_now", AsyncMock(return_value=five_am)),
            patch.object(main.database, "list_workers", AsyncMock(return_value=[])),
            patch.object(main, "_refresh_image_update_bell", AsyncMock()),
        ):
            await main._run_image_updates(force=True)
            assert "last_run" not in await main._image_update_settings()
            # A new install is on Update automatically, and 05:00 is past its hour.
            await main._run_image_updates()
            assert (await main._image_update_settings())["last_run"] == "2026-11-28"

    async def test_a_current_check_keeps_the_old_warning_out_of_the_bell_after_a_restart(self, db):
        from app import main

        await database.init_db()
        await database.record_image_update(1, "honeygain", "available", new_image="sha256:new")
        workers = AsyncMock(return_value=[{"id": 1, "name": "alpha"}])
        with patch.object(main.database, "list_workers", workers), patch.object(main, "_collector_alerts", []):
            await main._refresh_image_update_bell()
            assert "1|honeygain" in main._image_update_bell
            await main._refresh_image_update_bell({1: {"honeygain": "current"}})
            assert "1|honeygain" not in main._image_update_bell
            # A restart rebuilds the bell with no run's outcomes.
            main._image_update_bell.clear()
            await main._refresh_image_update_bell()
            assert "1|honeygain" not in main._image_update_bell
            # A newer row comes back.
            await database.record_image_update(1, "honeygain", "failed", new_image="sha256:newer", detail="x")
            await main._refresh_image_update_bell()
            assert "1|honeygain" in main._image_update_bell

    async def test_a_save_during_a_run_is_not_overwritten_by_its_last_run_stamp(self, db):
        from zoneinfo import ZoneInfo

        from app import main

        await database.init_db()
        five_am = datetime(2026, 11, 28, 5, 0, tzinfo=ZoneInfo("UTC"))
        real_get = main._image_update_settings
        saving = asyncio.Event()

        async def slow_get():
            settings = await real_get()
            # The owner saves Off while the run holds its copy of the settings.
            saving.set()
            await asyncio.sleep(0.05)
            return settings

        body = main.ImageUpdateSettingsBody(mode="off", hour=4, workers={}, services={})

        async def owner_saves():
            await saving.wait()
            await main.api_set_image_updates(body, _auth={"r": "owner"})

        with (
            patch.object(main, "_obligations_now", AsyncMock(return_value=five_am)),
            patch.object(main, "_image_update_settings", side_effect=slow_get),
            patch.object(main.database, "list_workers", AsyncMock(return_value=[])),
            patch.object(main, "_refresh_image_update_bell", AsyncMock()),
        ):
            await asyncio.gather(main._run_image_updates(), owner_saves())
        settings = await real_get()
        assert settings["mode"] == "off" and settings["last_run"] == "2026-11-28"


class TestImageCheckEndpoint:
    def test_a_pull_error_never_carries_a_login(self, monkeypatch):
        from fastapi import HTTPException

        from app import worker_api

        monkeypatch.setattr(worker_api, "_verify_api_key", lambda request: None)

        def refused(slug):
            raise orchestrator.ContainerRuntimeError(
                "pull from https://me:hunter2@registry.example/x failed; "
                "blob at https://cdn.example/b?X-Amz-Signature=s3cr3t&X-Amz-Credential=key failed",
                502,
            )

        monkeypatch.setattr(orchestrator, "check_image", refused)
        with pytest.raises(HTTPException) as err:
            asyncio.run(worker_api.api_image_check(MagicMock(), "honeygain"))
        detail = str(err.value.detail)
        assert "hunter2" not in detail and "registry.example" in detail
        assert "s3cr3t" not in detail and "key" not in detail and "cdn.example/b" in detail


@pytest.mark.asyncio
class TestCustomServiceBlocker:
    """An edit to a custom service waits for the owner's Redeploy (api_update_custom_service).

    So an update, which is a redeploy too, must not be what brings it in: the
    blocker judges the container against the saved definition.
    """

    async def _blocker(self, monkeypatch, saved, made_with, *, instances=1, deployed_env=None, image_volumes=()):
        from app import custom_services, main

        slug = custom_services.SLUG_PREFIX + "mine"
        definition, _ = custom_services.validate(saved)
        recorded = {
            "image": made_with["image"],
            "env": deployed_env or {},
            "command": made_with["command"],
            "instances": instances,
        }
        shape = {
            "image": made_with["image"],
            "mounts": ([made_with["data_path"]] if made_with["data_path"] else []) + list(image_volumes),
            "env_keys": [],
            "restart_policy": "unless-stopped",
        }

        async def custom_service(s, reveal):
            return custom_services.as_service(s, definition, reveal=reveal)

        async def image_for_worker(worker_id, s, asked):
            return asked

        monkeypatch.setattr(main, "_custom_service", custom_service)
        monkeypatch.setattr(main, "_image_for_worker", image_for_worker)
        monkeypatch.setattr(main.database, "get_deployment_spec", AsyncMock(return_value=recorded))
        monkeypatch.setattr(
            main.database,
            "get_worker",
            AsyncMock(return_value={"containers": json.dumps([{"slug": slug, "shape": shape}])}),
        )
        return await main._image_update_blocker(1, slug, {"ref": made_with["image"]})

    async def test_an_unchanged_definition_is_updated(self, monkeypatch):
        made = {"image": "example/mine:latest", "command": "run --fast", "data_path": "/data"}
        saved = {"name": "Mine", "image": "example/mine:latest", "command": "run --fast", "data_path": "/data"}
        assert await self._blocker(monkeypatch, saved, made) == ""

    async def test_a_saved_command_not_deployed_yet_is_left_to_the_owner(self, monkeypatch):
        made = {"image": "example/mine:latest", "command": "run --fast", "data_path": ""}
        saved = {"name": "Mine", "image": "example/mine:latest", "command": "run --slow", "data_path": ""}
        assert "older command" in await self._blocker(monkeypatch, saved, made)

    async def test_a_saved_data_path_not_deployed_yet_is_left_to_the_owner(self, monkeypatch):
        made = {"image": "example/mine:latest", "command": "", "data_path": ""}
        saved = {"name": "Mine", "image": "example/mine:latest", "command": "", "data_path": "/data"}
        assert "/data" in await self._blocker(monkeypatch, saved, made)

    async def test_a_box_recorded_with_several_copies_is_left_to_the_owner(self, monkeypatch):
        # Only one copy runs now, but a redeploy rebuilds every recorded copy.
        made = {"image": "example/mine:latest", "command": "", "data_path": ""}
        saved = {"name": "Mine", "image": "example/mine:latest", "command": "", "data_path": ""}
        assert "2 copies" in await self._blocker(monkeypatch, saved, made, instances=2)

    async def test_a_saved_value_not_deployed_yet_is_left_to_the_owner_without_naming_it(self, monkeypatch):
        made = {"image": "example/mine:latest", "command": "", "data_path": ""}
        saved = {"name": "Mine", "image": "example/mine:latest", "env": [{"key": "GREETING", "value": "new-value"}]}
        why = await self._blocker(monkeypatch, saved, made, deployed_env={"GREETING": "old-value"})
        assert "not deployed yet" in why and "new-value" not in why and "old-value" not in why
        assert await self._blocker(monkeypatch, saved, made, deployed_env={"GREETING": "new-value"}) == ""

    async def test_a_hostname_value_compares_as_the_redeploy_fills_it(self, monkeypatch):
        from app import main

        made = {"image": "example/mine:latest", "command": "", "data_path": ""}
        saved = {"name": "Mine", "image": "example/mine:latest", "env": [{"key": "NAME", "value": "box-{hostname}"}]}
        own = main._device_hostname({}, 1)
        assert await self._blocker(monkeypatch, saved, made, deployed_env={"NAME": f"box-{own}"}) == ""
        # The template changed since the deploy: the redeploy would bring it in.
        why = await self._blocker(monkeypatch, saved, made, deployed_env={"NAME": f"node-{own}"})
        assert "not deployed yet" in why

    async def test_a_device_with_the_old_shared_name_keeps_it_as_the_redeploy_does(self, monkeypatch):
        from app import main

        made = {"image": "example/mine:latest", "command": "", "data_path": ""}
        saved = {"name": "Mine", "image": "example/mine:latest", "env": [{"key": "NAME", "value": "box-{hostname}"}]}
        legacy = f"box-{main.HOSTNAME_PREFIX}"
        assert await self._blocker(monkeypatch, saved, made, deployed_env={"NAME": legacy}) == ""
        # Control: an edited template is still a saved value not deployed yet.
        edited = {**saved, "env": [{"key": "NAME", "value": "node-{hostname}"}]}
        assert "not deployed yet" in await self._blocker(monkeypatch, edited, made, deployed_env={"NAME": legacy})

    async def test_data_in_an_image_volume_outside_the_data_path_is_left_to_the_owner(self, monkeypatch):
        # The new container would get an empty anonymous volume, and the old one
        # goes with the old container.
        made = {"image": "example/mine:latest", "command": "", "data_path": "/data"}
        saved = {"name": "Mine", "image": "example/mine:latest", "data_path": "/data"}
        why = await self._blocker(monkeypatch, saved, made, image_volumes=["/var/lib/mine"])
        assert "/var/lib/mine" in why and "empty" in why
        assert await self._blocker(monkeypatch, saved, made) == ""
