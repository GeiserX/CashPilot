"""An image that boots systemd is refused before the running container is touched.

A custom image's full tag (venatum/earnapp, ubuntu systemd images in general)
runs /sbin/init as PID 1. Under the capability drop every deploy gets it exits
255 at once, with empty logs, and the restart policy loops it forever. The
worker now pulls first, reads what the image would run, and answers 409 with
the fix, while the old container keeps earning.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app import orchestrator


def _client(image_config: dict, old=None):
    client = MagicMock()
    if old is None:
        client.containers.get.side_effect = orchestrator.NotFound("nope")
    else:
        client.containers.get.return_value = old
    client.images.get.return_value.attrs = {"Config": image_config}
    created = MagicMock()
    created.id = "new"
    created.short_id = "new"
    client.containers.run.return_value = created
    return client


def _deploy(client, **kwargs):
    kwargs.setdefault("slug", "earnapp")
    kwargs.setdefault("image", "venatum/earnapp:latest")
    with (
        patch.object(orchestrator, "_CONTAINER_NETWORK", ""),
        patch.object(orchestrator, "_get_client", return_value=client),
    ):
        return orchestrator.deploy_raw(**kwargs)


class TestRefusal:
    def test_a_systemd_image_is_refused_with_the_fix(self):
        client = _client({"Cmd": ["/sbin/init"]})
        with pytest.raises(orchestrator.ContainerRuntimeError) as exc:
            _deploy(client)
        assert exc.value.status_code == 409
        assert "systemd" in str(exc.value)
        assert "':lite'" in str(exc.value)
        client.containers.run.assert_not_called()

    def test_the_running_container_is_not_touched(self):
        old = MagicMock()
        client = _client({"Cmd": ["/sbin/init"]}, old=old)
        with pytest.raises(orchestrator.ContainerRuntimeError):
            _deploy(client)
        old.stop.assert_not_called()
        old.remove.assert_not_called()

    def test_the_pull_happens_before_the_old_container_goes(self):
        """A registry outage must not cost the running container either."""
        old = MagicMock()
        order: list[str] = []
        client = _client({"Cmd": ["entrypoint"]}, old=old)
        client.images.pull.side_effect = lambda *_a, **_k: order.append("pull")
        old.remove.side_effect = lambda *_a, **_k: order.append("remove")
        _deploy(client)
        assert order == ["pull", "remove"]

    def test_a_lite_image_deploys(self):
        client = _client({"Entrypoint": ["entrypoint"], "Cmd": None})
        assert _deploy(client, image="venatum/earnapp:lite") == "new"

    def test_an_image_docker_cannot_describe_is_left_to_run(self):
        """No local copy after a failed pull: containers.run names that error itself."""
        client = _client({})
        client.images.get.side_effect = orchestrator.DockerException("no such image")
        assert _deploy(client) == "new"


class TestWhatRunsFirst:
    """Only the first word of what finally runs as PID 1 decides."""

    @pytest.mark.parametrize("init", sorted(orchestrator._SYSTEMD_INITS))
    def test_every_init_spelling(self, init):
        assert orchestrator._boots_systemd({"Cmd": [init]}, None, None)

    def test_the_image_entrypoint_wins_over_its_cmd(self):
        assert orchestrator._boots_systemd({"Entrypoint": ["/sbin/init"], "Cmd": ["bash"]}, None, None)
        assert not orchestrator._boots_systemd({"Entrypoint": ["entrypoint"], "Cmd": ["/sbin/init"]}, None, None)

    def test_the_catalog_entrypoint_replaces_the_images(self):
        assert not orchestrator._boots_systemd({"Cmd": ["/sbin/init"]}, ["/run.sh"], None)

    def test_the_request_command_replaces_the_cmd_but_not_the_entrypoint(self):
        assert not orchestrator._boots_systemd({"Cmd": ["/sbin/init"]}, None, "earnapp run")
        assert orchestrator._boots_systemd({"Entrypoint": ["/sbin/init"]}, None, "earnapp run")

    def test_an_empty_config_is_not_systemd(self):
        assert not orchestrator._boots_systemd({}, None, None)
