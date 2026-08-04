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


class TestTheComposePinTracksReleases:
    """CashPilot-yr7, and the direct cause of issue #188.

    docker-compose.yml pinned 1.4 while its own header claimed the images
    "track the `latest` tag" — and the string `:latest` it told you to replace
    appeared nowhere in the file. Following the quickstart therefore installed a
    version many releases behind.

    That is not cosmetic. radnet001 reported "Registration failed. Please try
    again." on v1.4, which is the first-run setup-token bug: v1.4.4 has the
    token gate in deps.py and no token field in onboarding.html, so the owner
    account could not be created at all. It had been fixed for months. The
    stale pin is what handed them the broken version.

    These tests are deliberately about DRIFT, not a fixed number: the pin must
    track the newest released major.minor, so this fails the next time the
    compose file falls behind.
    """

    def _newest_series(self) -> str:
        import re
        import subprocess

        out = subprocess.run(
            ["git", "tag", "--sort=-creatordate"], capture_output=True, text=True, cwd=PROJECT_ROOT
        ).stdout
        for line in out.splitlines():
            m = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", line.strip())
            if m:
                return f"{m.group(1)}.{m.group(2)}"
        pytest.skip("no semver tags available in this checkout")

    @pytest.mark.parametrize("name", ["docker-compose.yml", "docker-compose.fleet.yml"])
    def test_the_pin_matches_the_newest_released_series(self, name):
        import re

        text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
        live = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        pins = set(re.findall(r"image: drumsergio/cashpilot(?:-worker)?:(\S+)", live))
        assert pins, f"{name} pins no cashpilot image"
        newest = self._newest_series()
        assert pins == {newest}, (
            f"{name} pins {sorted(pins)} but the newest released series is {newest}. "
            "A stale pin here is what gave issue #188 a version with a first-run bug "
            "that had been fixed for months."
        )

    def test_the_header_does_not_claim_to_track_latest(self):
        """The sentence that made the stale pin invisible.

        It told the reader to replace `:latest` — a string the file did not
        contain — so anyone checking whether they were current concluded they
        were.
        """
        text = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        header = text[: text.index("services:")]
        assert "track the `latest` tag" not in header
        assert "replace `:latest`" not in header

    def test_the_header_says_what_the_file_actually_does(self):
        text = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        header = text[: text.index("services:")]
        assert "PINNED" in header or "pinned" in header
