"""Services the user adds from an image reference, without editing the catalog.

The catalog (services/*.yml) is reviewed and ships with CashPilot. A custom
service is the user's own: a name, an image, some environment variables, an
optional command and an optional data directory, stored encrypted in the
database and turned here into the same shape the deploy path already reads for
a catalog entry.

That shape is deliberately narrow. It never carries ports, capabilities,
devices, a network mode, privileged mode or an entrypoint, so a custom service
gets exactly the hardening every catalog service gets and nothing a catalog
entry can be granted. The worker enforces the same thing on its own side: it
grants capabilities, devices and host networking only to slugs its own catalog
declares them for, and a ``custom-`` slug is never in that catalog
(catalog._validate refuses the prefix).

Pure functions only; storage lives in app/database.py and the routes in
app/main.py.
"""

from __future__ import annotations

import posixpath
import re
from typing import Any

#: Every custom slug starts with this, and no catalog slug may (catalog._validate).
SLUG_PREFIX = "custom-"

# repository[:tag][@sha256:digest], with an optional registry host (and port) in
# front. No scheme, no spaces, nothing a shell or Docker would read as an option.
IMAGE_REF = re.compile(
    r"(?:[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::[0-9]{1,5})?/)?"
    r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*"
    r"(?:/[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*)*"
    r"(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?"
    r"(?:@sha256:[a-f0-9]{64})?"
)
IMAGE_MAX_LEN = 255

MAX_NAME_LEN = 60
MAX_ENV = 50
MAX_ENV_VALUE = 4096
MAX_COMMAND = 1024
DEFAULT_MEM_LIMIT = "512m"

_ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_DATA_PATH = re.compile(r"/[A-Za-z0-9._/-]{1,200}")
_MEM_LIMIT = re.compile(r"(\d+)([mg])")
_MEM_MIN_MB = 32
_MEM_MAX_MB = 16 * 1024

UNPINNED_WARNING = "No version tag: every redeploy pulls whatever the publisher pushed last. Pin a tag or digest."


def split_image(ref: str) -> tuple[str, str, str]:
    """Split a Docker image reference into (repository, tag, digest)."""
    digest = ""
    if "@" in ref:
        ref, digest = ref.split("@", 1)
    repo, tag = ref, ""
    # A ':' is a tag only if it comes after the last '/', else it's a registry port.
    last_colon = ref.rfind(":")
    if last_colon > ref.rfind("/"):
        repo, tag = ref[:last_colon], ref[last_colon + 1 :]
    return repo, tag, digest


def is_custom_slug(slug: str) -> bool:
    return isinstance(slug, str) and slug.startswith(SLUG_PREFIX)


def make_slug(name: str, taken: set[str] | frozenset[str]) -> str:
    """A new ``custom-`` slug for ``name`` that no existing one uses.

    Fixed at creation: the container name, the data volume and every record
    key on it, so renaming the service later never moves anything.

    A slug never ends in ``-<digits>``. Copy N of a service runs as
    ``cashpilot-<slug>-N`` (orchestrator._container_name), so a slug like
    ``custom-foo-2`` would share its container name with copy 2 of
    ``custom-foo``, and a deploy of one would replace the other. "Foo 2" becomes
    ``custom-foo2``, and a second "Foo" becomes ``custom-foo-v2``.

    ``taken`` must hold every slug ever used, deleted ones included
    (database.custom_service_slugs): a reused slug would mount the data volume
    a deleted service left behind.
    """
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-") or "service"
    base = re.sub(r"-(\d+)$", r"\1", base)
    slug = f"{SLUG_PREFIX}{base}"
    n = 2
    while slug in taken:
        slug = f"{SLUG_PREFIX}{base}-v{n}"
        n += 1
    return slug


def _printable(value: str) -> bool:
    return all(ch.isprintable() for ch in value)


def _validate_name(raw: Any) -> str:
    name = str(raw or "").strip()
    if not 1 <= len(name) <= MAX_NAME_LEN or not _printable(name):
        raise ValueError(f"Name must be 1 to {MAX_NAME_LEN} printable characters")
    return name


def _validate_image(raw: Any) -> str:
    image = str(raw or "").strip()
    if not image or len(image) > IMAGE_MAX_LEN or not IMAGE_REF.fullmatch(image):
        raise ValueError("Image is not a valid image reference (repository[:tag][@digest])")
    return image


def _validate_env(raw: Any, previous: dict[str, Any] | None) -> list[dict[str, Any]]:
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ValueError("Environment variables must be a list")
    if len(raw) > MAX_ENV:
        raise ValueError(f"At most {MAX_ENV} environment variables")
    stored = {
        e["key"]: e["value"] for e in (previous or {}).get("env") or [] if isinstance(e, dict) and e.get("secret")
    }
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Each environment variable needs a key and a value")
        key = str(item.get("key") or "").strip()
        if not _ENV_KEY.fullmatch(key):
            raise ValueError(
                "Variable names start with a letter or _, then letters, digits or _ (at most 128 characters)"
            )
        if key in seen:
            raise ValueError(f"{key} is set twice")
        seen.add(key)
        secret = bool(item.get("secret"))
        value = item.get("value")
        value = "" if value is None else str(value)
        if value == "" and key in stored:
            # A stored secret is never sent back to the browser, so a blank box
            # on an edit means "unchanged", not "erase it". That holds when the
            # Secret tick is cleared too: the box was blank because the value
            # was hidden, not because the user emptied it.
            value = stored[key]
        if len(value) > MAX_ENV_VALUE or "\x00" in value:
            raise ValueError(f"The value of {key} is too long or holds a NUL character")
        out.append({"key": key, "value": value, "secret": secret})
    return out


def _validate_command(raw: Any) -> str:
    command = str(raw or "").strip()
    if len(command) > MAX_COMMAND or any(ch in command for ch in "\x00\n\r"):
        raise ValueError(f"Command must be one line of at most {MAX_COMMAND} characters")
    return command


def _validate_data_path(raw: Any) -> str:
    path = str(raw or "").strip()
    if not path:
        return ""
    if not _DATA_PATH.fullmatch(path) or posixpath.normpath(path) != path or ".." in path.split("/") or path == "/":
        raise ValueError("Data path must be an absolute path inside the container, like /data, with no '..'")
    return path


def _validate_mem_limit(raw: Any) -> str:
    value = str(raw or "").strip().lower() or DEFAULT_MEM_LIMIT
    match = _MEM_LIMIT.fullmatch(value)
    if not match:
        raise ValueError("Memory limit must look like 512m or 2g")
    mb = int(match[1]) * (1024 if match[2] == "g" else 1)
    if not _MEM_MIN_MB <= mb <= _MEM_MAX_MB:
        raise ValueError("Memory limit must be between 32m and 16g")
    return value


def image_warnings(image: str) -> list[str]:
    _, tag, digest = split_image(image)
    if not digest and tag in ("", "latest"):
        return [UNPINNED_WARNING]
    return []


def validate(payload: dict[str, Any], previous: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[str]]:
    """The stored definition for ``payload``, and warnings worth showing.

    Raises ValueError with a message meant for the user. ``previous`` is the
    stored definition on an edit, so a secret left blank keeps its value.
    """
    if not isinstance(payload, dict):
        raise ValueError("Expected an object")
    image = _validate_image(payload.get("image"))
    definition = {
        "name": _validate_name(payload.get("name")),
        "image": image,
        "env": _validate_env(payload.get("env"), previous),
        "command": _validate_command(payload.get("command")),
        "data_path": _validate_data_path(payload.get("data_path")),
        "mem_limit": _validate_mem_limit(payload.get("mem_limit")),
    }
    return definition, image_warnings(image)


def volume_name(slug: str) -> str:
    """The named volume a custom service keeps its data in.

    Named, not a host path: the worker refuses host binds under system roots,
    and a deterministic name means every redeploy, and a change of data path,
    lands on the same volume.
    """
    return f"cashpilot-{slug}-data"


def masked(definition: dict[str, Any]) -> dict[str, Any]:
    """The definition as the editor may see it: secret values never leave the server."""
    return {
        **{k: definition.get(k, "") for k in ("name", "image", "command", "data_path", "mem_limit")},
        "env": [
            {
                "key": e["key"],
                "value": "" if e.get("secret") else e.get("value", ""),
                "secret": bool(e.get("secret")),
                "is_set": bool(e.get("value")),
            }
            for e in definition.get("env") or []
        ],
    }


def redacted(svc: dict[str, Any]) -> dict[str, Any]:
    """A masked service (``as_service(reveal=False)``) for a caller who is not
    the owner: the variable names, but no value and no command.

    Non-secret values are plain text in ``masked``, and a command often carries
    a token, so a viewer, a writer or the read-only token sees only which
    variables exist, as /api/config is owner-only for the catalog's.
    """
    shown = dict(svc.get("definition") or {})
    shown["command_set"] = bool(shown.get("command"))
    shown["command"] = ""
    shown["env"] = [{**e, "value": ""} for e in shown.get("env") or []]
    docker = {k: v for k, v in (svc.get("docker") or {}).items() if k != "command"}
    return {**svc, "definition": shown, "docker": docker}


def as_service(slug: str, definition: dict[str, Any], *, reveal: bool) -> dict[str, Any]:
    """A catalog-shaped dict for the deploy path and the service detail view.

    ``reveal=True`` puts the real env values in ``docker.env`` (as defaults) for
    api_deploy and must never be returned to a client. ``reveal=False`` leaves
    ``docker.env`` empty, so the deploy form shows no inputs, and carries the
    masked definition for the editor instead.
    """
    image = definition["image"]
    data_path = definition.get("data_path") or ""
    docker: dict[str, Any] = {
        "image": image,
        "volumes": [f"{volume_name(slug)}:{data_path}"] if data_path else [],
        "resources": {"mem_limit": definition.get("mem_limit") or DEFAULT_MEM_LIMIT},
        "env": (
            [
                {"key": e["key"], "label": e["key"], "default": e.get("value", ""), "secret": bool(e.get("secret"))}
                for e in definition.get("env") or []
            ]
            if reveal
            else []
        ),
    }
    if definition.get("command"):
        docker["command"] = definition["command"]
    svc: dict[str, Any] = {
        "slug": slug,
        "name": definition["name"],
        "category": "custom",
        "status": "custom",
        "custom": True,
        "description": f"Added by you from {image}. CashPilot has not reviewed this image.",
        "short_description": f"Your image: {image}",
        "docker": docker,
    }
    if not reveal:
        svc["definition"] = masked(definition)
        svc["warnings"] = image_warnings(image)
    return svc
