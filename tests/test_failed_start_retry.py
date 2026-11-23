"""The worker starts again an earner Docker could not start at its boot.

dockerd starts each container with restart policy unless-stopped or always
once, when it starts, and never tries again if that start fails: the restart
policy acts only when a running container exits. After an unclean power loss
a gVisor earner fails that one start on a stale filestore ("creating gofer
filestore files"), and such earners stayed down for two days until someone
started them by hand. orchestrator.start_failed_starts finds them by Docker's
own sign (exited, State.Error set, a restarting policy) and starts them again
through start_service, so every hold a Start honours still holds.
"""

from __future__ import annotations

import asyncio
import logging
import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402
from docker.errors import APIError, NotFound  # noqa: E402

from app import orchestrator, route_gate, worker_api  # noqa: E402
from app.constants import LABEL_MANAGED, LABEL_ROLE, ROLE_TUNNEL  # noqa: E402

GOFER = (
    "failed to create task for container: failed to create shim task: OCI runtime create failed: "
    "creating container: cannot create gofer process: gofer: creating gofer filestore files: file exists"
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(route_gate, "ROUTED_MARKER", str(tmp_path / ".routed"))
    monkeypatch.setattr(orchestrator, "RESTORE_MARKER", str(tmp_path / ".restores"))
    monkeypatch.delenv(route_gate.PROXIED_ONLY_ENV, raising=False)
    monkeypatch.setattr(orchestrator, "_start_retried_at", {})
    monkeypatch.setattr(orchestrator, "get_service", lambda slug: None)


def _earner(
    name="cashpilot-honeygain",
    slug="honeygain",
    *,
    error=GOFER,
    status="exited",
    policy="unless-stopped",
    network_mode="cashpilot-isolated",
    labels=None,
):
    c = MagicMock()
    c.name = name
    c.id = f"id-{name}"
    c.labels = {LABEL_MANAGED: "true", "cashpilot.service": slug} if labels is None else labels
    c.attrs = {
        "State": {"Status": status, "Running": status == "running", "Error": error, "ExitCode": 128},
        "HostConfig": {"NetworkMode": network_mode, "RestartPolicy": {"Name": policy}, "Runtime": "runsc"},
    }
    return c


def _client(*containers):
    """A Docker client that lists ``containers`` and finds each by its name, as Docker answers."""
    client = MagicMock()
    client.containers.list.return_value = list(containers)
    by_name = {c.name: c for c in containers}

    def get(name):
        if name in by_name:
            return by_name[name]
        raise NotFound("no such container")

    client.containers.get.side_effect = get
    return client


def _pass(*containers, client=None):
    client = client or _client(*containers)
    with patch.object(orchestrator, "_get_client", return_value=client):
        return orchestrator.start_failed_starts()


class TestWhatIsStartedAgain:
    def test_an_earner_whose_boot_start_failed_is_started(self, caplog):
        earner = _earner()
        assert _pass(earner) == ["cashpilot-honeygain"]
        earner.start.assert_called_once()
        assert "Started cashpilot-honeygain again" in caplog.text
        assert "gofer filestore" in caplog.text

    def test_policy_always_counts_too(self):
        earner = _earner(policy="always")
        assert _pass(earner) == ["cashpilot-honeygain"]

    def test_the_second_copy_is_started_as_itself(self):
        earner = _earner("cashpilot-honeygain-2", labels={LABEL_MANAGED: "true", "cashpilot.service": "honeygain"})
        earner.labels["cashpilot.instance"] = "2"
        other = _earner(error="")  # copy 1, which exited on its own
        assert _pass(earner, other) == ["cashpilot-honeygain-2"]
        earner.start.assert_called_once()
        other.start.assert_not_called()

    def test_only_exited_containers_are_listed_from_docker(self):
        client = _client()
        _pass(client=client)
        filters = client.containers.list.call_args.kwargs["filters"]
        assert client.containers.list.call_args.kwargs["all"] is True
        assert filters == {"label": f"{LABEL_MANAGED}=true", "status": "exited"}


class TestWhatIsLeftAlone:
    def test_an_earner_that_exited_on_its_own_or_was_stopped(self):
        """No State.Error: Docker was not refused a start, so its policy already decided."""
        earner = _earner(error="")
        assert _pass(earner) == []
        earner.start.assert_not_called()

    @pytest.mark.parametrize("policy", ["no", "on-failure", ""])
    def test_a_container_docker_does_not_mean_to_run(self, policy):
        """Fence-gated nodes and proxied copies have policy "no" and a guard of their own."""
        earner = _earner(policy=policy)
        assert _pass(earner) == []
        earner.start.assert_not_called()

    def test_a_running_or_restarting_container(self):
        for status in ("running", "restarting", "created"):
            earner = _earner(status=status)
            assert _pass(earner) == []
            earner.start.assert_not_called()

    def test_a_proxied_copy_and_a_tunnel(self):
        copy = _earner(
            "cashpilot-honeygain-p3",
            network_mode="container:abc",
            labels={LABEL_MANAGED: "true", "cashpilot.service": "honeygain", "cashpilot.proxy": "3"},
        )
        tunnel = _earner(
            "cashpilot-tunnel-p3",
            labels={LABEL_MANAGED: "true", LABEL_ROLE: ROLE_TUNNEL, "cashpilot.service": "proxy-tunnel"},
        )
        assert _pass(copy, tunnel) == []
        copy.start.assert_not_called()
        tunnel.start.assert_not_called()

    def test_a_container_without_a_service_label(self):
        earner = _earner(labels={LABEL_MANAGED: "true"})
        assert _pass(earner) == []
        earner.start.assert_not_called()

    def test_a_proxied_only_worker_keeps_a_direct_earner_stopped(self, monkeypatch, caplog):
        """start_service's route check holds here as it holds a Start from the dashboard."""
        caplog.set_level(logging.INFO, logger="app.orchestrator")
        monkeypatch.setenv(route_gate.PROXIED_ONLY_ENV, "true")
        earner = _earner()
        assert _pass(earner) == []
        earner.start.assert_not_called()
        assert "Left cashpilot-honeygain stopped" in caplog.text
        assert "Started" not in caplog.text

    def test_a_restore_that_did_not_finish_keeps_it_stopped(self, tmp_path):
        (tmp_path / ".restores").write_text("honeygain honeygain-data\n")
        earner = _earner()
        assert _pass(earner) == []
        earner.start.assert_not_called()


class TestHowOftenItTries:
    def test_one_try_per_container_every_retry_interval(self):
        earner = _earner()
        earner.start.side_effect = APIError("creating gofer filestore files: file exists")
        clock = {"now": 1000.0}
        with patch.object(orchestrator.time, "monotonic", side_effect=lambda: clock["now"]):
            assert _pass(earner) == []
            assert earner.start.call_count == 1
            clock["now"] += orchestrator.START_RETRY_SECONDS - 1
            _pass(earner)
            assert earner.start.call_count == 1
            clock["now"] += 1
            _pass(earner)
            assert earner.start.call_count == 2

    def test_a_failed_try_is_logged_with_dockers_reason_and_never_raises(self, caplog):
        earner = _earner()
        earner.start.side_effect = APIError("still broken")
        assert _pass(earner) == []
        assert "Could not start cashpilot-honeygain again (still broken)" in caplog.text
        assert "gofer filestore" in caplog.text

    def test_a_container_that_runs_again_is_forgotten(self):
        earner = _earner()
        _pass(earner)
        assert set(orchestrator._start_retried_at) == {earner.id}
        _pass()
        assert orchestrator._start_retried_at == {}


class TestTheWorkerRunsIt:
    def test_every_guard_pass_runs_it_and_never_raises(self, monkeypatch):
        calls = []
        monkeypatch.setattr(worker_api.lan_fence, "guard", lambda: {})
        monkeypatch.setattr(worker_api.orchestrator, "hold_direct_earners", lambda: [])
        monkeypatch.setattr(worker_api.orchestrator, "start_failed_starts", lambda: calls.append(1) or [])
        asyncio.run(worker_api._guard_once())
        assert calls == [1]
        monkeypatch.setattr(
            worker_api.orchestrator, "start_failed_starts", MagicMock(side_effect=RuntimeError("docker is down"))
        )
        asyncio.run(worker_api._guard_once())  # never raises

    def test_it_runs_after_the_proxied_only_hold(self, monkeypatch):
        """The hold stops direct earners first; the start then refuses them by the same rule."""
        order = []
        monkeypatch.setattr(worker_api.lan_fence, "guard", lambda: order.append("guard") or {})
        monkeypatch.setattr(worker_api.orchestrator, "hold_direct_earners", lambda: order.append("hold") or [])
        monkeypatch.setattr(worker_api.orchestrator, "start_failed_starts", lambda: order.append("start") or [])
        asyncio.run(worker_api._guard_once())
        assert order == ["guard", "hold", "start"]
