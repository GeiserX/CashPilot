"""The security layers this worker can give an earner, and the runtime each one gets.

The owner picks, per worker and per earner, whether an earner runs under
Docker's own runtime (runc) or under gVisor. The UI stores the choice and sends
it with the deploy as ``runtime_choice``. This module is the worker's side:

* ``report()`` says what this host has, for the heartbeat: the runtimes Docker
  registered and which of them are gVisor, whether the host has KVM, and which
  runtime an environment variable pins. Every value that could not be read is
  None, never False or an empty list: an older or blind worker must read as
  "unknown", not as "absent".
* ``pick()`` turns the owner's choice into the runtime Docker gets, from what
  the daemon registered. A gVisor choice needs a runtime registered with
  ``--network=host``, or Docker's DNS fails on our own bridge (gVisor issue
  7469), and an earner that declares NET_RAW (Bitping) needs one with
  ``--net-raw`` as well (docs/home-network-security.md, section 7).

Nothing here picks gVisor by itself. No choice means Docker's default, as before.
"""

from __future__ import annotations

import contextlib
import logging
import os
import platform
import threading
import time
from pathlib import Path
from typing import Any

import docker

from app import gpu

logger = logging.getLogger(__name__)

RUNC = "runc"
GVISOR = "gvisor"
CHOICES = (RUNC, GVISOR)

#: The heartbeat feature that says this worker takes ``runtime_choice`` and
#: reports ``system_info.layers``.
FEATURE = "runtime_choice"

#: Seconds report() keeps Docker's /info. The heartbeat runs every minute; a
#: gVisor install reloads Docker, and the self-test refreshes this at once.
INFO_TTL = 120.0
_info: tuple[float, dict[str, Any]] | None = None
_info_lock = threading.Lock()

#: The last gVisor self-test this worker ran (app/gvisor_check.py), for the heartbeat.
_last_check: dict[str, Any] | None = None


class ChoiceRefused(Exception):
    """The owner's runtime choice cannot be honoured on this worker. Nothing was touched."""


def _args(spec: dict[str, Any]) -> list[str]:
    raw = spec.get("runtimeArgs") or spec.get("args") or []
    return [str(a) for a in raw] if isinstance(raw, list) else []


def _has_flag(args: list[str], flag: str, value: str | None = None) -> bool:
    """``--network=host`` and ``--network host`` alike; a bare ``--net-raw`` or ``--net-raw=true``."""
    for i, arg in enumerate(args):
        name, sep, val = arg.partition("=")
        if name != flag:
            continue
        if value is None:
            return not sep or val.lower() in ("true", "1")
        if sep:
            return val == value
        return i + 1 < len(args) and args[i + 1] == value
    return False


def runtime_facts(runtimes: Any) -> list[dict[str, Any]]:
    """One entry per runtime Docker registered: its name and whether it is gVisor.

    A runtime is gVisor when its binary is runsc. ``hostnet`` is the
    ``--network=host`` passthrough Docker's DNS needs on our bridge, and
    ``net_raw`` the ``--net-raw`` flag that gives raw sockets back.
    """
    if not isinstance(runtimes, dict):
        return []
    facts = []
    for name in sorted(runtimes):
        spec = runtimes[name] if isinstance(runtimes[name], dict) else {}
        path = str(spec.get("path") or "")
        args = _args(spec)
        gvisor = Path(path).name.startswith("runsc") if path else str(name).startswith("runsc")
        facts.append(
            {
                "name": str(name),
                "gvisor": gvisor,
                "hostnet": gvisor and _has_flag(args, "--network", "host"),
                "net_raw": gvisor and _has_flag(args, "--net-raw"),
            }
        )
    return facts


def kind(runtime: str, facts: list[dict[str, Any]] | None) -> str:
    """``gvisor`` or ``runc`` for a runtime name, judged from what the daemon registered."""
    for fact in facts or []:
        if fact["name"] == runtime:
            return GVISOR if fact["gvisor"] else RUNC
    return GVISOR if runtime.startswith("runsc") else RUNC


def kvm(sysfs: Path = Path("/sys"), docker_host: str | None = None) -> bool | None:
    """Whether the machine Docker runs on has KVM, for the Secure VM layer.

    Read from sysfs, which shows the host's devices from inside a container
    with nothing passed in: /dev/kvm exists exactly when the kvm module made
    /sys/class/misc/kvm. None when this cannot say anything about that machine:
    not Linux, a Docker endpoint on another machine, or sysfs unreadable.
    """
    if platform.system() != "Linux":
        return None
    if not gpu.local_endpoint(os.environ.get("DOCKER_HOST", "") if docker_host is None else docker_host):
        return None
    misc = sysfs / "class" / "misc"
    try:
        if not misc.is_dir():
            return None
        return (misc / "kvm").exists()
    except OSError:
        return None


def _read_info() -> dict[str, Any] | None:
    client = None
    try:
        client = docker.from_env(timeout=5)
        info = client.info()
    except Exception as exc:  # noqa: BLE001 - unknown is an answer here
        logger.debug("Could not read Docker's runtimes: %s", exc)
        return None
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                client.close()
    return info if isinstance(info, dict) else None


def docker_info(fresh: bool = False) -> dict[str, Any] | None:
    """Docker's /info, cached for INFO_TTL. None when the daemon cannot be asked."""
    global _info
    now = time.monotonic()
    with _info_lock:
        if not fresh and _info is not None and now - _info[0] < INFO_TTL:
            return _info[1]
    info = _read_info()
    if info is not None:
        with _info_lock:
            _info = (now, info)
    return info


def daemon_runtimes(fresh: bool = False) -> list[dict[str, Any]] | None:
    info = docker_info(fresh=fresh)
    return runtime_facts(info.get("Runtimes")) if info is not None else None


def pick(
    choice: str,
    slug: str,
    facts: list[dict[str, Any]] | None,
    *,
    net_raw: bool,
    allowed: tuple[str, ...] | None,
    service: str,
) -> str:
    """The runtime Docker gets for the owner's choice, or ChoiceRefused with the reason.

    ``allowed`` is the socket proxy's runtime list when the worker is behind it
    (the proxy refuses any other name), None when it is not.
    """
    if choice == RUNC:
        return RUNC
    if choice != GVISOR:
        raise ChoiceRefused(f"{choice!r} is not a runtime choice; use one of {', '.join(CHOICES)}.")
    if facts is None:
        raise ChoiceRefused("Cannot check for gVisor: the Docker daemon is not answering.")
    usable = [f for f in facts if f["gvisor"] and f["hostnet"] and (allowed is None or f["name"] in allowed)]
    if net_raw:
        usable = [f for f in usable if f["net_raw"]]
    else:
        # A runtime without --net-raw first: an earner that never asked for raw
        # sockets does not get them back.
        usable.sort(key=lambda f: f["net_raw"])
    if usable:
        return usable[0]["name"]
    if net_raw:
        raise ChoiceRefused(
            f"{service} needs raw sockets, and this worker has no gVisor runtime registered with --network=host "
            f"and --net-raw (runsc-hostnet-raw). Run the gVisor install command from the Fleet page, "
            f"or keep {service} on Standard."
        )
    raise ChoiceRefused(
        f"This worker has no gVisor runtime registered with --network=host (runsc-hostnet), which Docker's DNS "
        f"needs on CashPilot's network. Run the gVisor install command from the Fleet page, or keep {service} "
        f"on Standard."
    )


def set_last_check(result: dict[str, Any]) -> None:
    global _last_check
    _last_check = dict(result)


def report(pins: dict[str, Any], proxy_runtimes: tuple[str, ...] | None) -> dict[str, Any]:
    """``system_info.layers`` for the heartbeat. Reads Docker's cached /info and sysfs; runs no container."""
    info = docker_info()
    return {
        "runtimes": runtime_facts(info.get("Runtimes")) if info is not None else None,
        "default_runtime": (str(info.get("DefaultRuntime") or "") or None) if info is not None else None,
        "kvm": kvm(),
        # What an environment variable pins on this worker. The UI shows the
        # choice locked where one does: the variable wins over the UI.
        "pins": pins,
        # The runtimes the socket proxy accepts; None when the worker is not behind it.
        "proxy_runtimes": list(proxy_runtimes) if proxy_runtimes is not None else None,
        "gvisor_check": dict(_last_check) if _last_check is not None else None,
    }
