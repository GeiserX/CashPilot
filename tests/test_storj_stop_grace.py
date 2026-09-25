"""A storage node gets the stop grace its catalog entry declares, on every stop.

Two limits used to cut it short. Docker gives a container 10 seconds on any
stop that does not pass its own timeout, and docker-py could not set a longer
one at create time. Inside the Storj image, supervisord SIGKILLs the node 10
seconds after a stop because its program section sets no stopwaitsecs. A node
killed mid-flush restarts with "hashstore unclean shutdown detected".

The catalog's stop_timeout now becomes the container's own stop timeout, and
Storj's catalog entry wraps the image's entrypoint to give supervisord a
matching grace. The wrapper's effect on the real image was checked by running
it: supervisord reports stopwaitsecs 270 for the node and the image's own
entrypoint still runs.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import docker
import pytest
import yaml

from app import catalog, compose_generator, orchestrator, worker_api


def _run_kwargs(**deploy_kwargs):
    container = MagicMock()
    container.id = "abc"
    container.short_id = "short"
    client = MagicMock()
    client.containers.get.side_effect = orchestrator.NotFound("nope")
    client.containers.run.return_value = container
    with patch.object(orchestrator, "_get_client", return_value=client):
        orchestrator.deploy_raw(**deploy_kwargs)
    return client.containers.run.call_args.kwargs


class TestTheContainerCarriesTheCatalogsGrace:
    def test_storj_is_created_with_its_300_seconds(self):
        assert _run_kwargs(slug="storj", image="storjlabs/storagenode")["stop_timeout"] == 300

    def test_a_service_that_declares_none_gets_the_documented_default(self):
        assert _run_kwargs(slug="honeygain", image="honeygain/honeygain")["stop_timeout"] == 30

    def test_docker_py_forwards_it_to_the_engine(self):
        """run() used to refuse the key; the create call it builds must now carry it."""
        created = docker.models.containers._create_container_args(
            {"image": "storjlabs/storagenode", "version": "1.44", "stop_timeout": 300}
        )
        assert created["stop_timeout"] == 300


class TestTheEntrypointComesFromTheWorkersCatalog:
    def test_storj_gets_its_wrapper(self):
        entrypoint = _run_kwargs(slug="storj", image="storjlabs/storagenode")["entrypoint"]
        assert entrypoint[:2] == ["/bin/sh", "-c"]
        assert "stopwaitsecs=270" in entrypoint[2]
        assert entrypoint[2].rstrip().endswith('exec /entrypoint "$@"'), "the image's own entrypoint must still run"

    def test_a_service_without_one_keeps_the_images(self):
        assert _run_kwargs(slug="honeygain", image="honeygain/honeygain")["entrypoint"] is None

    def test_a_deploy_request_cannot_choose_one(self):
        """What runs as root in the container is the catalog's call, not the caller's."""
        spec = worker_api.DeploySpec(image="x", entrypoint=["/bin/sh", "-c", "anything"])
        assert not hasattr(spec, "entrypoint")

    @pytest.mark.parametrize("raw", ["/bin/sh -c x", [], ["/bin/sh", 1], None])
    def test_a_malformed_catalog_value_is_ignored(self, raw):
        with patch.object(orchestrator, "get_service", return_value={"docker": {"entrypoint": raw}}):
            assert orchestrator._get_entrypoint("x") is None

    def test_the_grace_fits_inside_the_containers(self):
        """supervisord must finish before Docker gives up on it."""
        docker_conf = catalog.get_service("storj")["docker"]
        grace = int(re.search(r"a stopwaitsecs=(\d+)", docker_conf["entrypoint"][2]).group(1))
        assert 0 < grace < int(docker_conf["stop_timeout"])


class TestTheExportCarriesBoth:
    def _export(self, slug):
        return yaml.safe_load(compose_generator.generate_compose_single(slug))["services"][f"cashpilot-{slug}"]

    def test_storj_exports_its_grace_and_escaped_wrapper(self):
        svc = self._export("storj")
        assert svc["stop_grace_period"] == "300s"
        # $$ is Compose's escape for a literal $: "$F" and "$@" reach the shell intact.
        script = svc["entrypoint"][2]
        assert script.rstrip().endswith('exec /entrypoint "$$@"')
        assert '"$$F"' in script
        assert re.search(r"(?<!\$)\$(?!\$)", script.replace("$$", "")) is None, "no bare $ left for Compose to fill"

    def test_a_service_without_either_exports_neither(self):
        svc = self._export("honeygain")
        assert "stop_grace_period" not in svc
        assert "entrypoint" not in svc
