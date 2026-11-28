"""The one copyable command that installs, checks or removes a security layer on a host.

A layer such as gVisor needs root on the host, which the worker does not have
and must not get: the socket proxy refuses privileged containers by design. So
the UI shows a command for the owner to run. The command downloads the helper
from this repository at the tag of the release the UI runs, checks it against
the sha256 of the UI image's own copy, and only then runs it with sudo. A file
that changed on the way, or a tag that does not hold it, stops the command
before anything runs as root.

The helper's own arguments are shell-quoted. A secret never goes in them: a
helper that needs one asks for it, so it stays out of shell history and ps.
"""

from __future__ import annotations

import functools
import hashlib
import re
import shlex
from pathlib import Path

from app import i18n, version

REPO_RAW = "https://raw.githubusercontent.com/GeiserX/CashPilot"
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"

#: Each helper the UI offers, and the interpreter it runs under.
SCRIPTS: dict[str, str] = {"cashpilot-gvisor": "bash", "cashpilot-vm": "bash"}

_RELEASE = re.compile(r"\d+\.\d+\.\d+")


class Unavailable(Exception):
    """No pinned command can be shown; the message says why."""


@functools.cache
def sha256(name: str) -> str:
    return hashlib.sha256((SCRIPTS_DIR / name).read_bytes()).hexdigest()


def problem(name: str) -> str | None:
    """Why no pinned command can be shown for ``name``, or None when one can."""
    if name not in SCRIPTS:
        return i18n.t("layers.cmd.unknown", name=name)
    if not _RELEASE.fullmatch(version.current().removeprefix("v")):
        return i18n.t("layers.cmd.dev_build")
    try:
        sha256(name)
    except OSError:
        return i18n.t("layers.cmd.not_shipped", name=name)
    return None


def command(name: str, action: str, args: list[str] | tuple[str, ...] = ()) -> str:
    """The command line for ``name action args``, pinned to this release's tag and its sha256."""
    if (why := problem(name)) is not None:
        raise Unavailable(why)
    release = version.current().removeprefix("v")
    digest = sha256(name)
    url = f"{REPO_RAW}/v{release}/scripts/{name}"
    run = " ".join(shlex.quote(part) for part in (action, *args))
    return (
        f'd=$(mktemp -d) && curl -fsSL -o "$d/{name}" {url} '
        f'&& echo "{digest}  $d/{name}" | sha256sum -c - '
        f'&& sudo {SCRIPTS[name]} "$d/{name}" {run}'
    )
