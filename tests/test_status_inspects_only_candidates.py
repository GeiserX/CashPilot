"""The external-container scan must not inspect every container on the host.

docker-py's plain list inspects each container it returns. On a direct socket
the scan for externally started earners listed every container on the host, so
a box with 80 unrelated containers paid 80 inspects and 80 image lookups per
status pass. The sparse list names the image each was created from; only
those that may be a catalog image are inspected now.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app import orchestrator

IMAGE_MAP = {"honeygain/honeygain": "honeygain", "honeygain/honeygain:latest": "honeygain"}


class _Sparse:
    """A container as the sparse list returns it: no Config until reload()."""

    def __init__(self, cid, ref, tags, image_id="sha256:" + "a" * 64):
        self.id = cid
        self.short_id = cid[:12]
        self.name = f"c-{cid}"
        self.status = "running"
        self.labels = {}
        self.attrs = {"Id": cid, "Image": ref, "ImageID": image_id, "Labels": {}}
        self._tags = tags
        self.inspected = 0
        self.image_reads = 0

    def reload(self):
        self.inspected += 1
        self.attrs = {"Id": self.id, "Created": "2026-11-01T00:00:00Z", "Config": {"Image": self.attrs["Image"]}}

    @property
    def image(self):
        self.image_reads += 1
        image = MagicMock()
        image.tags = list(self._tags)
        image.short_id = "sha256:abc"
        image.attrs = {"RepoDigests": []}
        return image


@pytest.mark.parametrize("fn", ["get_status", "get_status_light"])
def test_only_containers_that_may_be_a_catalog_image_are_inspected(fn):
    unrelated = [_Sparse(f"other{i:02d}" + "0" * 56, f"nginx:1.{i}", [f"nginx:1.{i}"]) for i in range(20)]
    named = _Sparse("hg" + "1" * 62, "docker.io/honeygain/honeygain:latest", ["honeygain/honeygain:latest"])
    # Docker lists an image ID when the container was created from one, or its tag moved on.
    retagged = _Sparse("hg" + "2" * 62, "sha256:" + "f" * 64, ["honeygain/honeygain:latest"], "sha256:" + "f" * 64)
    built = [
        _Sparse(f"built{i}" + "0" * 58, "sha256:" + "b" * 64, ["myapp:dev"], "sha256:" + "b" * 64) for i in range(5)
    ]
    unrelated += built
    images = {
        "sha256:" + "f" * 64: {"RepoTags": [], "RepoDigests": ["honeygain/honeygain@sha256:" + "1" * 64]},
        "sha256:" + "b" * 64: {"RepoTags": ["myapp:dev"], "RepoDigests": []},
    }
    client = MagicMock()
    client.containers.list.side_effect = [[], [*unrelated, named, retagged]]
    client.images.get.side_effect = lambda image_id: MagicMock(attrs=images[image_id])
    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        patch.object(orchestrator, "_build_image_slug_map", return_value=IMAGE_MAP),
        patch.object(orchestrator, "_collect_stats_bulk", return_value={}),
    ):
        results = getattr(orchestrator, fn)()
    assert sorted(r["name"] for r in results) == sorted([named.name, retagged.name])
    assert all(r["slug"] == "honeygain" for r in results)
    assert sum(c.inspected for c in unrelated) == 0
    assert sum(c.image_reads for c in unrelated) == 0
    assert named.inspected == retagged.inspected == 1
    assert client.containers.list.call_args_list[1].kwargs == {"all": True, "sparse": True}
    # One read per image, not per container.
    assert client.images.get.call_count == 2
