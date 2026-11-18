"""A worker that cannot reach Docker must say so on /api/health.

On 2026-11-17 a Docker update on geiserct replaced /var/run/docker.sock. The
socket proxy had bound the old socket file, so for 17 hours every Docker call
the worker made failed, while /api/health answered 200 and the heartbeat kept
landing. The worker logged the outage once and nothing else saw it.

These tests pin the fix: the outage clock in the orchestrator, and
/api/health turning 503 after a sustained outage (never after a blip), without
calling Docker itself.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402
import requests  # noqa: E402
from docker import errors as docker_errors  # noqa: E402

try:
    from fastapi.testclient import TestClient  # noqa: E402
except ImportError:  # pragma: no cover - exercised only without fastapi
    pytest.skip("fastapi not installed", allow_module_level=True)

from app import orchestrator, worker_api  # noqa: E402

PROXY_HOST = f"unix://{orchestrator.PROXY_SOCKET_DIR}/docker.sock"


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


def _client():
    worker_api.app.router.lifespan_context = _noop_lifespan
    return TestClient(worker_api.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _docker_state(monkeypatch):
    monkeypatch.setattr(orchestrator, "_docker_available", None)
    monkeypatch.setattr(orchestrator, "_docker_unreachable_since", None)
    monkeypatch.setattr(orchestrator, "_docker_listing_failed", None)


def _outage_for(seconds: float) -> None:
    """Docker has failed every call for this long."""
    orchestrator._mark_docker_unavailable("test", RuntimeError("connection refused"))
    orchestrator._docker_unreachable_since = time.monotonic() - seconds


class TestOutageClock:
    def test_starts_on_the_first_failure_also_at_startup(self):
        # None -> False is a worker that starts with Docker unreachable.
        assert orchestrator.docker_unreachable_for() is None
        orchestrator._mark_docker_unavailable("ping failed", RuntimeError("refused"))
        assert orchestrator.docker_unreachable_for() is not None

    def test_a_repeated_failure_does_not_restart_it(self):
        orchestrator._mark_docker_unavailable("ping failed", RuntimeError("refused"))
        orchestrator._docker_unreachable_since = started = time.monotonic() - 3600
        orchestrator._mark_docker_unavailable("container listing failed", RuntimeError("refused"))
        assert orchestrator._docker_unreachable_since == started

    def test_a_success_stops_it(self):
        _outage_for(3600)
        orchestrator._mark_docker_available()
        assert orchestrator.docker_unreachable_for() is None


def _ping_ok_listing_fails():
    """A daemon that answers /_ping but cannot list containers (containerd wedged)."""
    client = MagicMock()
    client.ping.return_value = True
    client.containers.list.side_effect = RuntimeError("Read timed out")
    return client


class TestAListingOutage:
    """The ping works and every listing fails: still an outage, and only a listing ends it."""

    def _cycle(self, client):
        """What one heartbeat does with Docker: list, then ask whether Docker is there."""
        with (
            patch.object(orchestrator.docker, "from_env", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value={}),
        ):
            assert orchestrator.get_status() == []
            orchestrator.docker_available()

    def test_a_working_ping_does_not_end_it(self):
        client = _ping_ok_listing_fails()
        self._cycle(client)
        orchestrator._docker_unreachable_since = started = time.monotonic() - 3600
        for _ in range(3):
            self._cycle(client)
        assert orchestrator._docker_unreachable_since == started
        assert orchestrator.docker_unreachable_for() > worker_api._DOCKER_UNHEALTHY_AFTER
        assert _client().get("/api/health").status_code == 503

    def test_a_working_listing_ends_it(self):
        client = _ping_ok_listing_fails()
        self._cycle(client)
        client.containers.list.side_effect = None
        client.containers.list.return_value = []
        self._cycle(client)
        assert orchestrator.docker_unreachable_for() is None
        assert orchestrator._docker_listing_failed is None

    def test_a_ping_still_ends_a_ping_outage(self):
        """Negative control: a worker without a UI has no listing to end it."""
        _outage_for(3600)
        client = MagicMock()
        client.ping.return_value = True
        with patch.object(orchestrator.docker, "from_env", return_value=client):
            assert orchestrator.docker_available() is True
        assert orchestrator.docker_unreachable_for() is None

    def test_warns_once_per_outage(self, caplog):
        orchestrator._docker_available = True
        client = _ping_ok_listing_fails()
        with caplog.at_level(logging.WARNING, logger=orchestrator.logger.name):
            for _ in range(5):
                self._cycle(client)
            client.containers.list.side_effect = None
            client.containers.list.return_value = []
            self._cycle(client)
        said = [r.getMessage() for r in caplog.records]
        assert len([m for m in said if "became unreachable" in m]) == 1
        assert len([m for m in said if "reachable again" in m]) == 0
        assert len([m for m in said if "lists containers again" in m]) == 1


class TestTheFenceFeedsTheClock:
    """The fence lists containers every five minutes, also on a worker with no heartbeat."""

    def test_a_failed_fence_listing_starts_the_outage_and_a_working_one_ends_it(self):
        from app import lan_fence

        client = MagicMock()
        client.containers.list.side_effect = RuntimeError("500 Server Error")
        with pytest.raises(RuntimeError):
            lan_fence._managed(client)
        assert orchestrator.docker_unreachable_for() is not None

        client.containers.list.side_effect = None
        client.containers.list.return_value = []
        assert lan_fence._managed(client) == []
        assert orchestrator.docker_unreachable_for() is None


def _ext_listing_fails():
    """The managed list works; listing the external candidates fails."""
    client = MagicMock()
    client.ping.return_value = True
    client.containers.list.return_value = []
    return client


def _status_patches(client, external):
    return (
        patch.object(orchestrator.docker, "from_env", return_value=client),
        patch.object(orchestrator, "_build_image_slug_map", return_value={"example/earner:1": "earner"}),
        patch.object(orchestrator, "_external_candidates", side_effect=external),
        patch.object(orchestrator, "_collect_stats_bulk", return_value={}),
    )


class TestAFenceListingDoesNotEndAStatusOutage:
    """The fence lists only the managed containers; it cannot say the external listing works again."""

    def _status(self, client, external):
        a, b, c, d = _status_patches(client, external)
        with a, b, c, d:
            return orchestrator.get_status()

    def test_a_fence_success_leaves_an_external_listing_outage_running(self):
        from app import lan_fence

        client = _ext_listing_fails()
        assert self._status(client, RuntimeError("Read timed out")) == []
        orchestrator._docker_unreachable_since = started = time.monotonic() - 3600
        assert lan_fence._managed(client) == []
        assert orchestrator._docker_unreachable_since == started
        assert _client().get("/api/health").status_code == 503

        # Only a status read that lists everything again ends it.
        assert self._status(client, lambda *_a: []) == []
        assert orchestrator.docker_unreachable_for() is None

    def test_a_status_success_ends_a_fence_outage(self):
        """The reverse: get_status makes the fence's list and more, so it ends the fence's outage."""
        from app import lan_fence

        client = MagicMock()
        client.containers.list.side_effect = RuntimeError("500 Server Error")
        with pytest.raises(RuntimeError):
            lan_fence._managed(client)
        assert orchestrator.docker_unreachable_for() is not None
        client.containers.list.side_effect = None
        client.containers.list.return_value = []
        assert self._status(client, lambda *_a: []) == []
        assert orchestrator.docker_unreachable_for() is None


def _candidate(image_error: BaseException, managed: bool, created_from: str = "example/earner:1"):
    """A container whose image read raises: the list named it, the read failed."""
    c = MagicMock()
    c.id = c.short_id = "c0ffee"
    c.name = "cashpilot-earner" if managed else "earner"
    c.status = "running"
    c.labels = {"cashpilot.managed": "true", "cashpilot.service": "earner"} if managed else {}
    c.attrs = {"Config": {"Image": created_from}, "Created": ""}
    type(c).image = PropertyMock(side_effect=image_error)
    return c


DOCKER_FAILURES = [
    pytest.param(lambda: requests.exceptions.ConnectionError("Connection aborted"), id="connection"),
    pytest.param(lambda: requests.exceptions.ReadTimeout("Read timed out"), id="timeout"),
]


def _broken_image():
    return docker_errors.APIError("500 Server Error: layer does not exist")


@pytest.mark.parametrize("read", ["get_status", "get_status_light"])
@pytest.mark.parametrize("managed", [True, False], ids=["managed", "external"])
class TestADockerErrorOnOneContainerIsAListingOutage:
    """A copy skipped because Docker did not answer is not gone: the status must not say Docker is fine."""

    def _run(self, read, managed, error, created_from="example/earner:1"):
        c = _candidate(error, managed, created_from)
        client = _ext_listing_fails()
        client.containers.list.return_value = [c] if managed else []
        orchestrator._docker_available = True
        a, b, d, e = _status_patches(client, lambda *_a: [] if managed else [c])
        with a, b, d, e:
            return getattr(orchestrator, read)()

    @pytest.mark.parametrize("error", DOCKER_FAILURES)
    def test_keeps_the_outage(self, read, managed, error):
        assert self._run(read, managed, error()) == []
        assert orchestrator.docker_unreachable_for() is not None
        assert orchestrator._docker_listing_failed == "status"

    def test_a_container_removed_after_the_list_is_still_skipped(self, read, managed):
        """NotFound: its image or the container went away in between, which is no outage."""
        assert self._run(read, managed, docker_errors.NotFound("No such container")) == []
        assert orchestrator.docker_unreachable_for() is None

    def test_an_error_answer_about_one_container_is_no_outage(self, read, managed):
        """Docker answered, about that container only: it is skipped and the worker stays healthy."""
        assert self._run(read, managed, _broken_image()) == []
        assert orchestrator.docker_unreachable_for() is None
        assert orchestrator._docker_listing_failed is None


@pytest.mark.parametrize("managed", [True, False], ids=["managed", "external"])
def test_a_catalog_copy_skipped_on_an_error_answer_marks_the_heartbeat_partial(managed):
    """The skipped copy may be running: the UI must not record it as down or gone."""
    c = _candidate(_broken_image(), managed)
    client = _ext_listing_fails()
    client.containers.list.return_value = [c] if managed else []
    a, b, d, e = _status_patches(client, lambda *_a: [] if managed else [c])
    with a, b, d, e:
        assert orchestrator.get_status() == []
    assert orchestrator.status_listed() is False
    assert orchestrator.docker_unreachable_for() is None


@pytest.mark.parametrize("managed", [True, False], ids=["managed", "external"])
@pytest.mark.parametrize(
    ("error", "whole"),
    [
        (lambda: docker_errors.NotFound("No such container"), True),
        (lambda: docker_errors.ImageNotFound("No such image"), False),
    ],
    ids=["container-gone", "image-lookup-failed"],
)
def test_only_a_container_that_is_gone_leaves_the_heartbeat_whole(managed, error, whole):
    """ImageNotFound is a NotFound, but the container is still there and may be a running copy.

    The labeled loop marks any skip partial, a container gone included: one
    partial heartbeat costs nothing, and a CashPilot container is always a copy.
    """
    c = _candidate(error(), managed)
    client = _ext_listing_fails()
    client.containers.list.return_value = [c] if managed else []
    a, b, d, e = _status_patches(client, lambda *_a: [] if managed else [c])
    with a, b, d, e:
        assert orchestrator.get_status() == []
    assert orchestrator.status_listed() is (whole and not managed)
    assert orchestrator.docker_unreachable_for() is None


def test_a_matched_external_copy_that_cannot_be_read_marks_the_heartbeat_partial():
    """Matched by its image, then a field read fails: the copy is left out, so the list is not whole."""
    c = _candidate(_broken_image(), managed=False)
    image = MagicMock(tags=["example/earner:1"])
    type(c).image = PropertyMock(return_value=image)
    type(c).status = PropertyMock(side_effect=KeyError("State"))
    client = _ext_listing_fails()
    a, b, d, e = _status_patches(client, lambda *_a: [c])
    with a, b, d, e:
        assert orchestrator.get_status() == []
    assert orchestrator.status_listed() is False
    assert orchestrator.docker_unreachable_for() is None


def test_a_candidate_created_from_a_local_alias_marks_the_heartbeat_partial_and_the_worker_healthy():
    """Created as a local alias of a catalog image: the name it was created from says nothing.

    _external_candidates keeps it because its image's tags name a catalog
    repository. Its image read answers 500 every time, over many heartbeats:
    the list is partial, so the UI records no copy as down, and Docker answered,
    so the worker stays healthy.
    """
    from app import lan_fence

    c = _candidate(_broken_image(), managed=False, created_from="my-local-earner:latest")
    client = _ext_listing_fails()
    a, b, d, e = _status_patches(client, lambda *_a: [c])
    with a, b, d, e:
        for _ in range(3):
            assert orchestrator.get_status() == []
            assert orchestrator.status_listed() is False
            assert lan_fence._managed(client) == []
    assert orchestrator.docker_unreachable_for() is None
    assert _client().get("/api/health").status_code == 200


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (lambda: docker_errors.APIError("500 Server Error: inspect failed"), "skipped"),
        (lambda: docker_errors.NotFound("No such container"), "gone"),
        (lambda: requests.exceptions.ConnectionError("Connection refused"), "raises"),
        (lambda: requests.exceptions.ReadTimeout("Read timed out"), "raises"),
    ],
)
def test_a_candidate_inspect_error_is_about_that_container_unless_docker_did_not_answer(error, outcome):
    """One container whose inspect Docker answers with an error must not make the worker Docker-blind."""
    c = MagicMock(attrs={}, short_id="abc123")
    c.reload.side_effect = error()
    client = MagicMock()
    client.containers.list.return_value = [c]
    skipped: list = []
    if outcome == "raises":
        with pytest.raises(requests.exceptions.RequestException):
            orchestrator._external_candidates(client, {"example/earner:1": "earner"}, skipped)
        return
    assert orchestrator._external_candidates(client, {"example/earner:1": "earner"}, skipped) == []
    assert skipped == ([c] if outcome == "skipped" else [])


def test_a_candidate_left_out_on_an_inspect_error_marks_the_heartbeat_partial():
    """The left-out container may be a running copy: the UI must not record it as down."""
    c = MagicMock()

    def candidates(_client, _image_map, skipped=None):
        if skipped is not None:
            skipped.append(c)
        return []

    client = _ext_listing_fails()
    a, b, d, e = _status_patches(client, candidates)
    with a, b, d, e:
        assert orchestrator.get_status() == []
    assert orchestrator.status_listed() is False
    assert orchestrator.docker_unreachable_for() is None


def test_a_fence_failure_during_a_status_outage_keeps_the_wider_scope():
    """A fence listing failure must not narrow a status outage: the next fence success would end it."""
    from app import lan_fence

    client = _ext_listing_fails()
    a, b, d, e = _status_patches(client, RuntimeError("Read timed out"))
    with a, b, d, e:
        assert orchestrator.get_status() == []
    started = orchestrator._docker_unreachable_since
    client.containers.list.side_effect = RuntimeError("500 Server Error")
    with pytest.raises(RuntimeError):
        lan_fence._managed(client)
    client.containers.list.side_effect = None
    assert lan_fence._managed(client) == []
    assert orchestrator._docker_listing_failed == "status"
    assert orchestrator._docker_unreachable_since == started


def test_the_fence_loop_ends_a_status_outage_on_a_worker_with_no_ui(monkeypatch):
    """No heartbeat runs get_status, so the fence pass reads the status again once Docker works."""
    monkeypatch.setattr(worker_api, "UI_URL", "")
    client = _ext_listing_fails()
    a, b, d, e = _status_patches(client, RuntimeError("Read timed out"))
    with a, b, d, e:
        assert orchestrator.get_status_light() == []
    orchestrator._docker_unreachable_since = time.monotonic() - 3600
    assert _client().get("/api/health").status_code == 503

    sleeps = iter([None])

    async def one_pass(_seconds):
        if next(sleeps, "stop") == "stop":
            raise asyncio.CancelledError

    a, b, d, e = _status_patches(client, lambda *_a: [])
    with (
        a,
        b,
        d,
        e,
        patch.object(worker_api.asyncio, "sleep", side_effect=one_pass),
        patch.object(worker_api, "_check_fence", AsyncMock()),
        pytest.raises(asyncio.CancelledError),
    ):
        asyncio.run(worker_api._fence_loop())
    assert orchestrator.docker_unreachable_for() is None
    assert _client().get("/api/health").status_code == 200


class TestHealthReportsALostDocker:
    def test_a_short_outage_stays_healthy(self):
        """A daemon restart or a docker-ce upgrade must not flap the container."""
        _outage_for(worker_api._DOCKER_UNHEALTHY_AFTER - 30)
        resp = _client().get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "worker": worker_api.WORKER_NAME}

    def test_a_sustained_outage_degrades_with_the_reason(self, monkeypatch):
        monkeypatch.setenv("DOCKER_HOST", PROXY_HOST)
        _outage_for(worker_api._DOCKER_UNHEALTHY_AFTER + 60)
        resp = _client().get("/api/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["reason"] == "cannot reach Docker"
        assert body["docker_unreachable_for"].endswith("s")
        assert int(body["docker_unreachable_for"][:-1]) >= worker_api._DOCKER_UNHEALTHY_AFTER
        # Fixed text that names the fix, nothing of Docker's own answer.
        assert "docker restart cashpilot-socket-proxy" in body["docker"]
        assert "connection refused" not in resp.text

    def test_degrades_without_a_ui_too(self):
        """Unlike the heartbeat rule: a worker with no UI and no Docker does nothing it was told."""
        _outage_for(worker_api._DOCKER_UNHEALTHY_AFTER + 60)
        with patch.object(worker_api, "UI_URL", ""):
            resp = _client().get("/api/health")
        assert resp.status_code == 503
        assert resp.json()["reason"] == "cannot reach Docker"

    def test_both_faults_are_named(self):
        _outage_for(worker_api._DOCKER_UNHEALTHY_AFTER + 60)
        worker_api._consecutive_heartbeat_failures = worker_api._HEARTBEAT_FAILURES_UNHEALTHY_AFTER
        with patch.object(worker_api, "UI_URL", "http://cashpilot-ui:8080"):
            resp = _client().get("/api/health")
        assert resp.status_code == 503
        assert resp.json()["reason"] == "not reporting to the UI; cannot reach Docker"

    def test_recovery_returns_to_the_healthy_body(self):
        _outage_for(worker_api._DOCKER_UNHEALTHY_AFTER + 60)
        assert _client().get("/api/health").status_code == 503
        orchestrator._mark_docker_available()
        resp = _client().get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "worker": worker_api.WORKER_NAME}

    def test_never_calls_docker(self):
        """A hung socket must not hang the healthcheck: the clock is read from memory.

        The calls are recorded, not raised: docker_available() swallows any
        exception from from_env, so a raising stub would let a call through.
        """
        _outage_for(worker_api._DOCKER_UNHEALTHY_AFTER + 60)
        calls: list[str] = []

        def record(name):
            def stub(*_a, **_k):
                calls.append(name)
                return MagicMock()

            return stub

        with (
            patch.object(orchestrator.docker, "from_env", record("from_env")),
            patch.object(orchestrator, "docker_available", record("docker_available")),
            patch.object(orchestrator, "_get_client", record("_get_client")),
        ):
            resp = _client().get("/api/health")
        assert resp.status_code == 503
        assert calls == []

    def test_a_raw_socket_worker_is_told_to_restart_itself(self, monkeypatch):
        """Unraid and TrueNAS bind the socket into the worker: it is mounted, and the fix is a restart."""
        monkeypatch.delenv("DOCKER_HOST", raising=False)
        _outage_for(worker_api._DOCKER_UNHEALTHY_AFTER + 60)
        body = _client().get("/api/health").json()
        assert "restart this worker" in body["docker"]
        assert "monitor-only" not in body["docker"], "a worker without Docker is unhealthy now, not a mode"


def _heartbeat_payload(monkeypatch) -> dict:
    """Run one heartbeat against a fake UI and return what it sent."""
    captured: dict = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            captured.update(json or {})
            return _Resp()

    monkeypatch.setattr(worker_api, "UI_URL", "http://cashpilot-ui:8080")
    with (
        patch.object(worker_api, "_detect_egress_ip", AsyncMock(return_value=None)),
        patch.object(worker_api, "_disk_usage", return_value=None),
        patch.object(worker_api, "_gpu_info", return_value={}),
        patch.object(worker_api.httpx, "AsyncClient", _Client),
    ):
        asyncio.run(worker_api._send_heartbeat())
    return captured


class TestHeartbeatSaysHowDockerIsReached:
    def test_heartbeat_carries_docker_access(self, monkeypatch):
        """The UI's alert names what to restart: the proxy, or the worker itself."""
        monkeypatch.setenv("DOCKER_HOST", PROXY_HOST)
        monkeypatch.setattr(orchestrator, "get_status", lambda: [])
        monkeypatch.setattr(orchestrator, "docker_available", lambda: False)
        captured = _heartbeat_payload(monkeypatch)
        assert captured["system_info"]["docker_access"] == "proxy"
        assert captured["system_info"]["docker_available"] is False

    def test_a_listing_outage_is_reported_blind(self, monkeypatch):
        """The ping works and the listing fails: the heartbeat must not say Docker is there.

        Saying it was there with containers=[] kept the UI's alert and the
        fleet flag quiet for as long as the daemon stayed wedged.
        """
        monkeypatch.setenv("DOCKER_HOST", PROXY_HOST)
        client = _ping_ok_listing_fails()
        with (
            patch.object(orchestrator.docker, "from_env", return_value=client),
            patch.object(orchestrator, "_build_image_slug_map", return_value={}),
        ):
            captured = _heartbeat_payload(monkeypatch)
        assert captured["containers"] == []
        assert captured["system_info"]["docker_available"] is False

    def test_heartbeat_carries_how_long_docker_has_failed(self, monkeypatch):
        """The UI counts its alert grace from this, so a UI restart does not start it again."""
        monkeypatch.setattr(orchestrator, "get_status", lambda: [])
        monkeypatch.setattr(orchestrator, "docker_available", lambda: False)
        _outage_for(1200)
        captured = _heartbeat_payload(monkeypatch)
        assert 1200 <= captured["system_info"]["docker_unreachable_for"] < 1260
        assert isinstance(captured["system_info"]["docker_unreachable_for"], int)

    def test_a_worker_that_reaches_docker_sends_no_outage_age(self, monkeypatch):
        monkeypatch.setattr(orchestrator, "get_status", lambda: [])
        monkeypatch.setattr(orchestrator, "docker_available", lambda: True)
        captured = _heartbeat_payload(monkeypatch)
        assert "docker_unreachable_for" not in captured["system_info"]
