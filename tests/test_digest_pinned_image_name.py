"""A digest-pinned service is not reported as outdated.

The catalog pins ProxyBase by digest (``ghcr.io/proxybaseorg/peer-cli@sha256:...``).
An image pulled that way has no tag, so the worker reported its bare image ID
(``sha256:ca262f32663d``). The dashboard's outdated check compares repositories,
read "sha256" against the catalog's repository, and asked for a redeploy of a
container that was already running the pinned image.

The worker now reports a tagless image by its digest reference from RepoDigests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app import catalog, main, orchestrator
from app.constants import LABEL_DEPLOYED_BY, LABEL_SERVICE

PINNED = catalog.get_service("proxybase")["docker"]["image"]


def _image(tags=(), digests=()):
    image = MagicMock()
    image.tags = list(tags)
    image.short_id = "sha256:ca262f32663d"
    image.attrs = {"RepoDigests": list(digests)}
    return image


def _container(image, *, cid, slug=None, created_from=""):
    c = MagicMock()
    c.id = cid
    c.short_id = cid[:12]
    c.name = f"c-{cid}"
    c.status = "running"
    c.labels = {LABEL_SERVICE: slug, LABEL_DEPLOYED_BY: "worker"} if slug else {}
    c.image = image
    c.attrs = {"Created": "2026-09-27T00:00:00Z", "Config": {"Image": created_from}}
    return c


class TestTheImageName:
    def test_a_tag_wins(self):
        assert orchestrator._image_ref(_image(["honeygain/honeygain:latest"], ["honeygain/honeygain@sha256:1"])) == (
            "honeygain/honeygain:latest"
        )

    def test_a_tagless_image_is_named_by_its_digest_reference(self):
        assert orchestrator._image_ref(_image(digests=[PINNED])) == PINNED

    def test_neither_gives_nothing(self):
        assert orchestrator._image_ref(_image()) == ""

    def test_the_digest_the_container_was_created_from_wins(self):
        """RepoDigests is sorted, so with two digests the first may be the old one."""
        stale = "ghcr.io/proxybaseorg/peer-cli@sha256:0000"
        assert orchestrator._image_ref(_image(digests=[stale, PINNED]), created_from=PINNED) == PINNED

    def test_a_tag_the_container_was_created_from_does_not_override(self):
        assert orchestrator._image_ref(_image(["a/b:1"]), created_from="a/b:latest") == "a/b:1"


class TestTheOutdatedCheck:
    def test_a_bare_image_id_is_unknown_not_outdated(self):
        assert main._image_outdated("sha256:ca262f32663d", PINNED) is False

    def test_the_same_repository_on_an_old_digest_is_outdated(self):
        assert main._image_outdated("ghcr.io/proxybaseorg/peer-cli@sha256:0000", PINNED) is True


@pytest.mark.parametrize("fn", ["get_status", "get_status_light"])
class TestBothStatusPaths:
    def _run(self, fn, containers):
        client = MagicMock()
        client.containers.list.side_effect = containers
        with (
            patch.object(orchestrator, "_get_client", return_value=client),
            patch.object(orchestrator, "_collect_stats_bulk", return_value={}),
        ):
            return getattr(orchestrator, fn)()

    def test_a_managed_digest_pinned_container_is_not_outdated(self, fn):
        managed = _container(_image(digests=[PINNED]), cid="managed-proxybase", slug="proxybase")
        [entry] = self._run(fn, [[managed], [managed]])
        assert entry["image"] == PINNED
        assert main._image_outdated(entry["image"], PINNED) is False

    def test_an_external_digest_pinned_container_is_still_recognised(self, fn):
        external = _container(_image(digests=[PINNED]), cid="external-proxybase")
        [entry] = self._run(fn, [[], [external]])
        assert entry["slug"] == "proxybase"
        assert entry["image"] == PINNED

    def test_a_container_created_from_the_pin_is_not_outdated_despite_a_stale_digest(self, fn):
        stale = "ghcr.io/proxybaseorg/peer-cli@sha256:0000"
        managed = _container(
            _image(digests=[stale, PINNED]), cid="managed-proxybase", slug="proxybase", created_from=PINNED
        )
        [entry] = self._run(fn, [[managed], [managed]])
        assert main._image_outdated(entry["image"], PINNED) is False

    def test_a_really_different_repository_is_still_flagged(self, fn):
        old = _container(_image(digests=["proxybase/old-cli@sha256:1"]), cid="managed-old", slug="proxybase")
        [entry] = self._run(fn, [[old], [old]])
        assert main._image_outdated(entry["image"], PINNED) is True
