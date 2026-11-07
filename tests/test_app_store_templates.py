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
from pathlib import Path, PurePosixPath

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
        assert re.fullmatch(r"\d+\.\d+\.\d+", tag), f"{compose}: {image} tag {tag!r} is not a full release version"


@pytest.mark.parametrize("compose", COMPOSE, ids=_ids(COMPOSE))
def test_ui_and_worker_carry_the_same_tag(compose):
    images = _images(_load(compose))
    ui = {_tag(i) for i in images if i.startswith("drumsergio/cashpilot:")}
    worker = {_tag(i) for i in images if i.startswith("drumsergio/cashpilot-worker:")}
    assert ui and worker, f"{compose}: needs a CashPilot UI image and a worker image"
    assert ui == worker, f"{compose}: UI and worker pinned to different tags {sorted(ui | worker)}"


def _mounts(service: dict) -> list[tuple[str, str]]:
    """(source, target) for every volume, in short ``src:dst`` or long syntax."""
    out = []
    for v in service.get("volumes") or []:
        if isinstance(v, dict):
            out.append((str(v.get("source", "")), str(v.get("target", ""))))
        else:
            src, _, rest = str(v).partition(":")
            out.append((src, rest.split(":", 1)[0]))
    return out


def _services(compose: Path) -> dict[str, dict]:
    return {k: v for k, v in (_load(compose).get("services") or {}).items() if isinstance(v, dict)}


def _is_migration(service: dict) -> bool:
    """The one-shot owner-label migration: the worker image, another entrypoint."""
    return service.get("entrypoint") == ["python", "-m", "app.owner_migrate"]


def _is_worker(service: dict) -> bool:
    return str(service.get("image", "")).startswith("drumsergio/cashpilot-worker") and not _is_migration(service)


def _is_proxy(service: dict) -> bool:
    return str(service.get("image", "")).startswith("codeswhat/sockguard:")


def _proxy_name(services: dict) -> str:
    return next(name for name, svc in services.items() if _is_proxy(svc))


def _env(service: dict) -> dict[str, str]:
    env = service.get("environment") or {}
    if isinstance(env, dict):
        return {str(k): str(v) for k, v in env.items()}
    return dict(str(e).split("=", 1) for e in env if "=" in str(e))


@pytest.mark.parametrize("compose", COMPOSE, ids=_ids(COMPOSE))
def test_only_the_socket_proxy_holds_the_docker_socket(compose):
    """The root compose files took the raw socket (root on the host) away from
    the worker in v1.71.0 (#583). A store package that still bound it into the
    worker installed the weaker layout the shipped files had left behind."""
    services = _services(compose)
    proxies = [name for name, svc in services.items() if _is_proxy(svc)]
    workers = [name for name, svc in services.items() if _is_worker(svc)]
    assert proxies, f"{compose}: no socket proxy service"
    assert workers, f"{compose}: no worker service"
    for name, svc in services.items():
        sockets = [(s, t) for s, t in _mounts(svc) if "/var/run/docker.sock" in (s, t)]
        if _is_proxy(svc):
            assert "/var/run/docker.sock:/var/run/docker.sock:ro" in (svc.get("volumes") or []), (
                f"{compose}: the proxy {name} must hold the socket read-only"
            )
        elif _is_migration(svc):
            # It exits before the proxy starts.
            assert svc.get("restart") == "no" and svc.get("network_mode") == "none", (
                f"{compose}: the migration {name} must run once, with no network"
            )
            assert services[_proxy_name(services)]["depends_on"] == {
                name: {"condition": "service_completed_successfully"}
            }, f"{compose}: the proxy must start only after the migration finished"
            # It moves volumes and recreates containers, so it needs the raw socket.
            assert sockets == [("/var/run/docker.sock", "/var/run/docker.sock")], (
                f"{compose}: the migration {name} cannot reach Docker"
            )
        else:
            assert not sockets, f"{compose}: {name} mounts the Docker socket; only the proxy may"
    for name in workers:
        assert _env(services[name]).get("DOCKER_HOST") == "unix:///run/cashpilot-docker/docker.sock", (
            f"{compose}: worker {name} does not reach Docker through the proxy"
        )


@pytest.mark.parametrize("compose", COMPOSE, ids=_ids(COMPOSE))
def test_the_worker_joins_only_networks_that_carry_the_owner_label(compose):
    # The migration moves every network a worker container is on; one shared
    # with the unlabelled UI it can only warn about, at every start.
    doc = _load(compose)
    worker = next(s for s in doc["services"].values() if _is_worker(s))
    nets = worker.get("networks")
    assert nets, f"{compose}: the worker would join the project's unlabelled default network"
    for net in nets:
        labels = ((doc.get("networks") or {}).get(net) or {}).get("labels") or {}
        assert labels.get("cashpilot.deployed-by") == "worker", f"{compose}: {net}"


@pytest.mark.parametrize("compose", COMPOSE, ids=_ids(COMPOSE))
def test_the_worker_data_is_kept_apart_from_the_ui_data(compose):
    """The UI's /data holds the credential store and its key; the worker drives
    Docker, so it must not mount the same host folder."""
    services = _services(compose)
    data = {name: {s for s, t in _mounts(svc) if t == "/data"} for name, svc in services.items() if not _is_proxy(svc)}
    ui = {PurePosixPath(s) for n, d in data.items() if not _is_worker(services[n]) for s in d}
    worker = {PurePosixPath(s) for n, d in data.items() if _is_worker(services[n]) for s in d}
    assert ui and worker, f"{compose}: UI or worker has no /data mount"
    for w in worker:
        for u in ui:
            # One folder inside the other is as bad as the same folder.
            assert w != u and w not in u.parents and u not in w.parents, (
                f"{compose}: worker /data {w} overlaps UI /data {u}"
            )


@pytest.mark.parametrize("compose", COMPOSE, ids=_ids(COMPOSE))
def test_ui_and_worker_share_the_fleet_volume(compose):
    """/fleet holds the enrolment key, which both sides need."""
    services = _services(compose)
    fleet = {name: {s for s, t in _mounts(svc) if t == "/fleet"} for name, svc in services.items()}
    ui = set().union(*(f for n, f in fleet.items() if not _is_worker(services[n])))
    worker = set().union(*(f for n, f in fleet.items() if _is_worker(services[n])))
    assert ui and ui == worker, f"{compose}: UI and worker must mount the same /fleet folder ({ui} vs {worker})"


def _cashpilot_tag(compose: Path) -> str:
    return next(_tag(i) for i in _images(_load(compose)) if i.startswith("drumsergio/cashpilot:"))


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


# ---------------------------------------------------------------------------
# CasaOS interpolates its compose file twice
# ---------------------------------------------------------------------------
#
# Its importer (CasaOS-AppManagement NewComposeAppFromYAML) resolves variables,
# answering "$NAME" for any it does not know, writes the result out, and
# Compose resolves that file again on install. So `$$` reaches the container
# as nothing useful, and `${VAR:-default}` with VAR unset ends as "", not as the
# default. Checked against compose-go 1.20.2, the version CasaOS builds on.

_TEMPLATE = re.compile(r"\$(?:(\$)|([_a-zA-Z][_a-zA-Z0-9]*)|\{([_a-zA-Z][_a-zA-Z0-9]*)(?:(:?[-?])([^}]*))?\}|(.|$))")


def _interpolate(value, lookup):
    if isinstance(value, dict):
        return {k: _interpolate(v, lookup) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v, lookup) for v in value]
    if not isinstance(value, str):
        return value

    def sub(m):
        escaped, named, braced, op, default, invalid = m.groups()
        if escaped:
            return "$"
        if invalid is not None:
            raise ValueError(f"invalid template in {value!r}")
        return lookup(named or braced, op, default)

    return _TEMPLATE.sub(sub, value)


def _casaos_install(doc: dict) -> dict:
    def first(name, op, default):
        return "$TZ" if name == "TZ" else f"${name}"

    def second(name, op, default):
        known = {"AppID": "cashpilot", "TZ": "UTC"}
        if name in known:
            return known[name]
        return default if op and op.startswith(":") or op == "-" else ""

    return _interpolate(_interpolate(doc, first), second)


CASAOS = STORES / "casaos" / "CashPilot" / "docker-compose.yml"


def test_casaos_install_gives_the_proxy_the_generated_policy():
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import socket_proxy_policy as spp

    installed = _casaos_install(_load(CASAOS))
    policy = yaml.safe_load(installed["configs"]["cashpilot_socket_policy"]["content"])
    assert policy == yaml.safe_load(spp.policy()), "the policy CasaOS hands the proxy is not the generated one"


def test_casaos_install_never_leaves_an_empty_bind_entry():
    """sockguard reads an empty entry as the prefix of every path, so an unset
    variable turned into "" would let containers bind any host folder."""
    installed = _casaos_install(_load(CASAOS))
    env = _env(installed["services"]["cashpilot-socket-proxy"])
    binds = env["SOCKGUARD_REQUEST_BODY_CONTAINER_CREATE_ALLOWED_BIND_MOUNTS"].split(",")
    assert binds and all(b.strip() for b in binds), f"empty bind entry after a CasaOS install: {binds}"


def test_the_casaos_simulation_can_fail():
    """The control: the defaulted form plain Compose uses ends empty here."""
    doc = {"x": "${UNSET_X:-/dev/null/x},$${Y}"}
    assert _casaos_install(doc)["x"] == ","
