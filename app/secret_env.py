"""Earner credentials outside Docker's container config (CASHPILOT_EARNER_SECRETS=file).

Docker keeps a container's environment and command line in its config, so
``docker inspect``, a backup of /var/lib/docker/containers and any tool that
holds the Docker socket show every earner password in plain text. With this
mode on, the worker creates a catalog earner without the values of its secret
variables (``secret: true`` in its catalog entry):

* its environment has no secret variable, and its command line carries
  ``${NAME}`` where the catalog put a secret (Honeygain's ``-pass``);
* a volume of its own, ``cashpilot-secret-<id>``, is mounted at
  ``/run/cashpilot-secret``, the one folder the socket proxy lets the worker
  write into a container. Between create and start the worker puts two files
  there with put_archive: ``env`` (the secret variables) and ``cashpilot-env``
  (a static program, app/shim/cashpilot-env.c);
* the entrypoint is ``cashpilot-env`` and the arguments are the earner's own
  entrypoint and command. It sets the variables, fills each ``${NAME}`` in the
  arguments and execs the earner. No shell is needed, so it works in any image.

``docker restart`` and a reboot run the same entrypoint again, and the volume
keeps the files, so nothing changes there. The volume goes with the container
(remove_volume). What this does not do: root on the host still reads the
values from ``/proc/<pid>/environ`` and from the volume on disk, and any
client with the Docker API can still read the file through ``docker cp`` (the
archive endpoint) or ``docker exec``. It keeps them out of ``docker inspect``,
the container config and every copy of that config.

Off by default, so nothing changes until the owner sets the variable. A
service can opt out with ``docker.secrets_in_file: false`` in its catalog
entry. Custom services always keep the plain environment.
"""

from __future__ import annotations

import io
import logging
import os
import shlex
import tarfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: The worker's setting: "file" turns this on, anything else leaves it off.
MODE_ENV = "CASHPILOT_EARNER_SECRETS"
MODE_FILE = "file"
MODE_ENV_VALUE = "env"

#: The folder in the earner. The socket proxy's container_archive rule allows
#: writes here and nowhere else (app/socket_policy.py), the tunnel sidecar's too.
SECRET_DIR = "/run/cashpilot-secret"
SHIM_NAME = "cashpilot-env"
SHIM_PATH = f"{SECRET_DIR}/{SHIM_NAME}"
ENV_NAME = "env"

#: The shim in the worker image (Dockerfile.worker builds it).
SHIM_BINARY = Path(os.getenv("CASHPILOT_SHIM_BINARY", "/usr/local/lib/cashpilot/cashpilot-env"))

#: On the earner: the names (never the values) of the variables kept in the file.
LABEL_KEYS = "cashpilot.secret-env"
#: On the earner: how many leading arguments were its own entrypoint, so the
#: shape the UI compares with the catalog (orchestrator._shape) is the earner's.
LABEL_ENTRYPOINT_LEN = "cashpilot.secret-env-entrypoint"
#: On the volume: the container it belongs to.
VOLUME_LABEL = "cashpilot.secret-env-for"
VOLUME_PREFIX = "cashpilot-secret-"


def mode() -> str:
    """This worker's setting, read on each deploy."""
    value = os.getenv("CASHPILOT_EARNER_SECRETS", "").strip().lower()
    return MODE_FILE if value == MODE_FILE else MODE_ENV_VALUE


def shim_available() -> bool:
    return SHIM_BINARY.is_file()


@dataclass
class Plan:
    """How one earner is created with its secrets in the file."""

    env: dict[str, str]
    entrypoint: list[str]
    command: list[str]
    keys: list[str]
    entrypoint_len: int
    files: dict[str, bytes] = field(repr=False)
    uid: int
    mode: int
    volume: str

    def labels(self) -> dict[str, str]:
        return {LABEL_KEYS: ",".join(self.keys), LABEL_ENTRYPOINT_LEN: str(self.entrypoint_len)}


def secret_keys(service: dict[str, Any] | None) -> list[str]:
    """The catalog's secret variables of a service, in catalog order."""
    docker_conf = (service or {}).get("docker") or {}
    return [
        str(var["key"])
        for var in docker_conf.get("env") or []
        if isinstance(var, dict) and var.get("key") and var.get("secret")
    ]


def covers(service: dict[str, Any] | None, slug: str) -> bool:
    """Whether this mode applies to the service at all: a catalog entry with a secret, not opted out."""
    if not service or slug.startswith("custom-"):
        return False
    if ((service.get("docker") or {}).get("secrets_in_file")) is False:
        return False
    return bool(secret_keys(service))


def _owner(user: str) -> tuple[int, int]:
    """The env file's owner and mode for the image's user.

    Root in the earner has no CAP_DAC_OVERRIDE (every capability is dropped),
    so the file must belong to the user that reads it. A user given by name
    cannot be resolved without the image's /etc/passwd: the file is then
    readable by every user in the container, which only runs the earner.
    """
    name = (user or "").split(":", 1)[0].strip()
    if name in ("", "root", "0"):
        return 0, 0o400
    if name.isdigit():
        return int(name), 0o400
    return 0, 0o444


def _hide(token: str, values: dict[str, str]) -> str:
    """``token`` with each secret value replaced by ``${NAME}``, in one pass.

    Longest value first at each position, and a placeholder once written is
    never searched again, so the shim's one pass gives back exactly ``token``.
    """
    ordered = sorted(((v, k) for k, v in values.items() if v), key=lambda item: len(item[0]), reverse=True)
    out: list[str] = []
    i = 0
    while i < len(token):
        for value, key in ordered:
            if token.startswith(value, i):
                out.append("${" + key + "}")
                i += len(value)
                break
        else:
            out.append(token[i])
            i += 1
    return "".join(out)


def plan(
    slug: str,
    service: dict[str, Any] | None,
    env: dict[str, str],
    command: str | None,
    entrypoint: list[str] | None,
    image_config: dict[str, Any],
    user: str | None = None,
) -> Plan | None:
    """The plan for this earner, or None to create it as before (mode off, nothing secret, or it cannot be done).

    Never raises: the deploy calls it after the old container is stopped and
    before its rollback begins, so a failure here would leave the old earner down.
    """
    if mode() != MODE_FILE or not covers(service, slug):
        return None
    keys = [key for key in secret_keys(service) if str(env.get(key) or "")]
    if not keys:
        return None
    if not shim_available():
        logger.warning(
            "%s=file is set, but %s is missing from this worker image; %s keeps its credentials in its environment",
            MODE_ENV,
            SHIM_BINARY,
            slug,
        )
        return None
    try:
        shim = SHIM_BINARY.read_bytes()
    except OSError as exc:
        logger.warning("%s could not be read (%s); %s keeps its credentials in its environment", SHIM_BINARY, exc, slug)
        return None
    values = {key: str(env[key]) for key in keys}
    for value in values.values():
        if "\0" in value:
            logger.warning("A credential of %s holds a NUL byte; it keeps its credentials in its environment", slug)
            return None

    base = [str(p) for p in entrypoint] if entrypoint else [str(p) for p in image_config.get("Entrypoint") or []]
    # Docker drops the image's CMD when the entrypoint is set on create.
    image_cmd = [] if entrypoint else [str(p) for p in image_config.get("Cmd") or []]
    try:
        tokens = shlex.split(command) if command else image_cmd
    except ValueError:
        # Docker splits it the same way and refuses it, inside the deploy's rollback.
        logger.warning("The command of %s cannot be split; it keeps its credentials in its environment", slug)
        return None
    for token in [*base, *tokens]:
        if any("${" + key + "}" in token for key in keys):
            # The shim would fill it in, changing an argument the earner was given as written.
            logger.warning(
                "The command of %s already holds a placeholder for a credential; it keeps its credentials in its "
                "environment",
                slug,
            )
            return None
    if any(value in token for value in values.values() for token in base):
        logger.warning("The entrypoint of %s holds a credential; it keeps its credentials in its environment", slug)
        return None
    tokens = [_hide(token, values) for token in tokens]
    argv = base + tokens
    if not argv:
        logger.warning("%s has no entrypoint or command to start; it keeps its credentials in its environment", slug)
        return None

    uid, file_mode = _owner(user if user is not None else str(image_config.get("User") or ""))
    record = b"".join(f"{key}={values[key]}".encode() + b"\0" for key in keys)
    return Plan(
        env={k: v for k, v in env.items() if k not in values},
        entrypoint=[SHIM_PATH],
        command=argv,
        keys=keys,
        entrypoint_len=len(base),
        files={ENV_NAME: record, SHIM_NAME: shim},
        uid=uid,
        mode=file_mode,
        volume=f"{VOLUME_PREFIX}{uuid.uuid4().hex[:16]}",
    )


def archive(p: Plan) -> bytes:
    """The two files as a tar for put_archive: the program for anyone to run, the variables for the earner's user."""
    buf = io.BytesIO()
    now = int(time.time())
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data, owner, file_mode in (
            (SHIM_NAME, p.files[SHIM_NAME], 0, 0o555),
            (ENV_NAME, p.files[ENV_NAME], p.uid, p.mode),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = file_mode
            info.uid = info.gid = owner
            info.mtime = now
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def create_volume(client: Any, p: Plan, container_name: str) -> None:
    client.volumes.create(name=p.volume, labels={VOLUME_LABEL: container_name})


def mount(p: Plan) -> Any:
    from docker.types import Mount

    return Mount(SECRET_DIR, p.volume, type="volume")


def provision(container: Any, p: Plan) -> None:
    """Write the files into the created, not yet started, earner. Raises when Docker refuses."""
    if not container.put_archive(SECRET_DIR, archive(p)):
        raise RuntimeError("Docker did not take the credentials file")


def volume_of(container: Any) -> str | None:
    """The name of a container's secret volume, or None."""
    attrs = container.attrs if isinstance(getattr(container, "attrs", None), dict) else {}
    for m in attrs.get("Mounts") or []:
        if (
            isinstance(m, dict)
            and m.get("Destination") == SECRET_DIR
            and str(m.get("Name") or "").startswith(VOLUME_PREFIX)
        ):
            return str(m["Name"])
    return None


def remove_volume(client: Any, name: str | None) -> None:
    """Remove a secret volume once no container uses it; a failure only leaves it behind, logged."""
    if not name:
        return
    try:
        client.volumes.get(name).remove()
    except Exception as exc:  # noqa: BLE001 - in use by a clone, or already gone
        logger.info("Left a credentials volume behind: %s", exc)


def is_shimmed(attrs: dict[str, Any]) -> bool:
    config = attrs.get("Config") if isinstance(attrs.get("Config"), dict) else {}
    return (config.get("Entrypoint") or []) == [SHIM_PATH] and LABEL_KEYS in (config.get("Labels") or {})


def logical_view(attrs: dict[str, Any]) -> tuple[list[str] | None, list[str]]:
    """The earner's own entrypoint and the secret keys of a shimmed container, for its shape."""
    config = attrs.get("Config") if isinstance(attrs.get("Config"), dict) else {}
    labels = config.get("Labels") or {}
    try:
        n = int(labels.get(LABEL_ENTRYPOINT_LEN) or 0)
    except ValueError:
        n = 0
    cmd = [str(p) for p in config.get("Cmd") or []]
    keys = [k for k in str(labels.get(LABEL_KEYS) or "").split(",") if k]
    return (cmd[:n] or None), keys
