"""The shipped compose files must not use :latest (CashPilot-jz3).

The project's own rule is semver tags, never `latest`, and the security posture
claims images are pinned. The example compose files contradicted both: a user
following the quickstart got whatever was pushed most recently, with no way to
know what they were running and a breaking change possible on a routine
`docker compose pull`.

They now pin the major.minor tag, which is a real published tag: patch fixes
still arrive automatically, but a new minor or major needs a deliberate edit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SHIPPED_COMPOSE = ["docker-compose.yml", "docker-compose.fleet.yml"]

_IMAGE = re.compile(r"^\s*image:\s*(\S+)", re.M)


def _images(name: str) -> list[str]:
    return _IMAGE.findall((PROJECT_ROOT / name).read_text())


@pytest.mark.parametrize("compose", SHIPPED_COMPOSE)
def test_no_latest_tag_in_shipped_compose(compose):
    offenders = [i for i in _images(compose) if i.endswith(":latest")]
    assert not offenders, (
        f"{compose} uses :latest for {offenders}. A user following the quickstart "
        "would not know what they are running, and a routine `docker compose pull` "
        "could carry a breaking change. Pin the major.minor tag instead."
    )


@pytest.mark.parametrize("compose", SHIPPED_COMPOSE)
def test_every_cashpilot_image_carries_an_explicit_tag(compose):
    """An untagged image is :latest by another name."""
    for image in _images(compose):
        if "drumsergio/cashpilot" not in image:
            continue
        assert ":" in image.split("/")[-1], f"{compose}: {image} has no explicit tag"


@pytest.mark.parametrize("compose", SHIPPED_COMPOSE)
def test_the_two_cashpilot_images_are_pinned_together(compose):
    """A UI and worker on different versions is a support problem nobody wants."""
    tags = {image.rsplit(":", 1)[1] for image in _images(compose) if "drumsergio/cashpilot" in image}
    assert len(tags) == 1, f"{compose}: UI and worker pinned to different tags {sorted(tags)}"
