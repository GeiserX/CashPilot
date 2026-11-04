"""The app store packages under contrib/app-stores pin one exact, real release.

These files are what CasaOS and Runtipi users install. A store's update bot can
only bump an exact tag, so a floating tag such as ``latest`` leaves users unable
to tell what they run. A UI and a worker on different tags is a support
problem. And the version the store shows must be the version the images carry,
or the store lists one release and installs another.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
STORES = ROOT / "contrib" / "app-stores"

_COMPOSE_NAMES = ("docker-compose.yml", "docker-compose.yaml", "docker-compose.json")


def _compose_files() -> list[Path]:
    return sorted(p for p in STORES.rglob("*") if p.name in _COMPOSE_NAMES)


def _load(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    return json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)


def _images(doc: dict) -> list[str]:
    services = doc.get("services")
    # Runtipi's legacy JSON format is a list of services; compose is a mapping.
    entries = services if isinstance(services, list) else list((services or {}).values())
    return [s["image"] for s in entries if isinstance(s, dict) and "image" in s]


def _tag(image: str) -> str | None:
    name = image.split("@", 1)[0]
    last = name.rsplit("/", 1)[-1]
    return last.split(":", 1)[1] if ":" in last else None


def _ids(paths: list[Path]) -> list[str]:
    return [str(p.relative_to(STORES)) for p in paths]


COMPOSE = _compose_files()


def test_the_packages_are_found():
    """Without this, an empty glob would make every check below pass on nothing."""
    names = {p.relative_to(STORES).parts[0] for p in COMPOSE}
    assert {"casaos", "runtipi"} <= names, f"found packages for {sorted(names)} only"


@pytest.mark.parametrize("compose", COMPOSE, ids=_ids(COMPOSE))
def test_every_image_pins_an_exact_tag(compose):
    images = _images(_load(compose))
    assert images, f"{compose} declares no images"
    for image in images:
        tag = _tag(image)
        assert tag, f"{compose}: {image} has no tag, which is latest by another name"
        assert tag != "latest", f"{compose}: {image} floats on latest; pin the release tag"
        assert re.search(r"\d", tag), f"{compose}: {image} tag {tag!r} names no version"


@pytest.mark.parametrize("compose", COMPOSE, ids=_ids(COMPOSE))
def test_ui_and_worker_carry_the_same_tag(compose):
    tags = {_tag(i) for i in _images(_load(compose)) if i.startswith("drumsergio/cashpilot")}
    assert len(tags) == 1, f"{compose}: UI and worker pinned to different tags {sorted(tags)}"


def _cashpilot_tag(compose: Path) -> str:
    return next(_tag(i) for i in _images(_load(compose)) if i.startswith("drumsergio/cashpilot"))


def test_casaos_lists_the_version_it_installs():
    compose = STORES / "casaos" / "CashPilot" / "docker-compose.yml"
    listed = str(_load(compose)["x-casaos"]["version"])
    assert listed == _cashpilot_tag(compose), f"CasaOS shows version {listed} but installs {_cashpilot_tag(compose)}"


def test_runtipi_lists_the_version_it_installs():
    package = STORES / "runtipi" / "cashpilot"
    listed = json.loads((package / "config.json").read_text(encoding="utf-8"))["version"]
    installed = _cashpilot_tag(package / "docker-compose.yml")
    assert listed == installed, f"Runtipi shows version {listed} but installs {installed}"


def test_runtipi_offers_no_public_exposure():
    """The dashboard commands the worker that holds the Docker socket (root on
    the host), and the package's own text says to keep it on the LAN or VPN.
    With ``exposable`` true Runtipi shows an "Expose app" switch that puts it on
    a public domain, so the listing would offer the setup its text forbids.
    Users reach it on APP_PORT instead."""
    config = json.loads((STORES / "runtipi" / "cashpilot" / "config.json").read_text(encoding="utf-8"))
    assert config.get("exposable", False) is False, "Runtipi listing offers public exposure; set exposable to false"
