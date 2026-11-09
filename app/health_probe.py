"""Ask a running node how it is doing, from inside its container (worker side).

Some failures never reach a log line the tail can catch and leave the
container healthy: a Mysterium node behind a router that rewrites the UDP
source port of some of its connections registers, passes its own port check
and is offered to buyers, and every session it gets ends after about a minute
having carried nothing. The node's own API knows: its monitoring status reads
"failed" and its recent sessions are all short and empty.

The catalog declares the read in ``docker.health_probe``:

    health_probe:
      command: ["timeout", "12", "sh", "-c", "..."]   # run inside the container, read-only
      checks:
        - pattern: '...'                 # regex on the command's output
          means: "..."                   # shown under Needs fixing
        - items: '...'                   # regex for one item of a list
          pattern: '...'                 # what makes an item bad
          min_matches: 3                 # items needed before judging
          answered: '...'                # (optional) regex the output holds when this
                                         # check's read worked; without it the check
                                         # is unread, not clear
          means: "..."

A check without ``items`` holds when ``pattern`` matches the output at least
``min_matches`` times (default 1). With ``items`` it holds when the output has
at least ``min_matches`` items and every one of them matches ``pattern``: one
good item clears it, and too few items say nothing. Patterns are
case-sensitive, like ``collector.node_read``.

A check with ``answered`` is judged only when its marker is in the output,
so a command that reads two things can lose one without losing the other's
verdict. A check whose marker is missing is reported in ``unread``.

The command must start with ``timeout <seconds>`` below READ_TIMEOUT, which
ends the command in the container. The exec itself runs on a Docker client of
this module's own with a READ_TIMEOUT socket timeout: a stream that stalls
(the daemon or the socket proxy stops sending) raises instead of holding its
pool thread, so stalled reads cannot fill the pool for the worker's lifetime.

Read-only by construction, like ``app/node_read.py``: the command comes from
the catalog in this image, never from a request, and only the indexes of the
checks that hold leave the worker, never the output.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

#: Seconds one container's read may take before it is reported as unread.
READ_TIMEOUT = 15
#: Seconds one /api/health-probes answer may take in all. The UI waits 60 s for
#: it; copies not read by then are reported unread, and the rest still go back.
BATCH_BUDGET = 40

_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="health-probe")


def _min_matches(check: dict[str, Any]) -> int | None:
    """A check's min_matches, or None when it is not a positive integer."""
    value = check.get("min_matches", 1)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def spec_errors(spec: Any) -> list[str]:
    """What is wrong with a ``docker.health_probe`` declaration; empty when it is usable."""
    if not isinstance(spec, dict):
        return ["must be a mapping"]
    errors: list[str] = []
    command = spec.get("command")
    if not (isinstance(command, list) and command and all(isinstance(p, str) for p in command)):
        errors.append("command must be a non-empty list of strings")
    elif not (
        len(command) > 2
        and command[0] == "timeout"
        and command[1].isascii()
        and command[1].isdigit()
        and 0 < int(command[1]) < READ_TIMEOUT
    ):
        errors.append(f"command must start with timeout <seconds>, under {READ_TIMEOUT}")
    checks = spec.get("checks")
    if not (isinstance(checks, list) and checks):
        return [*errors, "checks must be a non-empty list"]
    for i, check in enumerate(checks):
        if not isinstance(check, dict):
            errors.append(f"checks[{i}] must be a mapping")
            continue
        for field in ("pattern", "items", "answered"):
            value = check.get(field)
            if value is None and field != "pattern":
                continue
            try:
                if not isinstance(value, str) or not value:
                    raise TypeError
                re.compile(value)
            except (re.error, TypeError):
                errors.append(f"checks[{i}].{field} must be a non-empty regular expression")
        if not isinstance(check.get("means"), str) or not check["means"].strip():
            errors.append(f"checks[{i}].means must be a non-empty string")
        if _min_matches(check) is None:
            errors.append(f"checks[{i}].min_matches must be a positive integer")
    return errors


def probes(services: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """slug -> its declared probe, for services that declare a well-formed one."""
    out: dict[str, dict[str, Any]] = {}
    for svc in services:
        spec = (svc.get("docker") or {}).get("health_probe")
        if spec is None:
            continue
        if spec_errors(spec):
            logger.warning("Ignoring %s docker.health_probe: %s", svc.get("slug"), "; ".join(spec_errors(spec)))
            continue
        out[svc["slug"]] = spec
    return out


def holds(output: bytes | str | None, check: dict[str, Any]) -> bool:
    """Whether one check holds on the command's output."""
    text = output.decode(errors="replace") if isinstance(output, bytes) else (output or "")
    needed = _min_matches(check) or 1
    pattern = re.compile(check["pattern"])
    if not check.get("items"):
        return sum(1 for _ in pattern.finditer(text)) >= needed
    items = [m.group(0) for m in re.finditer(check["items"], text)]
    return len(items) >= needed and all(pattern.search(item) for item in items)


def _text(output: bytes | str | None) -> str:
    """The command's output as text."""
    return output.decode(errors="replace") if isinstance(output, bytes) else (output or "")


def unanswered(output: bytes | str | None, spec: dict[str, Any]) -> list[int]:
    """The indexes of the checks whose ``answered`` marker is missing from the output."""
    text = _text(output)
    return [i for i, c in enumerate(spec["checks"]) if c.get("answered") and not re.search(c["answered"], text)]


def judge(output: bytes | str | None, spec: dict[str, Any]) -> list[int]:
    """The indexes of the checks that hold on the command's output (unread ones never do)."""
    unread = set(unanswered(output, spec))
    return [i for i, check in enumerate(spec["checks"]) if i not in unread and holds(output, check)]


def fingerprint(spec: dict[str, Any]) -> str:
    """A short hash of a probe declaration.

    The worker sends it with its hits, and the UI uses the hits only when it
    loads the same declaration: during an upgrade the two often run different
    catalogs, and an index into another version's checks names the wrong cause.
    """
    return hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def _client() -> Any:
    """A Docker client whose socket reads give up after READ_TIMEOUT seconds."""
    import docker

    return docker.from_env(timeout=READ_TIMEOUT)


def _read_one(client: Any, container_id: str, spec: dict[str, Any]) -> dict[str, list[int]] | None:
    """Run the probe in one container: hits and unread checks, or None when nothing was read."""
    api = client.api
    exec_id = api.exec_create(container_id, spec["command"])["Id"]
    output = api.exec_start(exec_id)
    if api.exec_inspect(exec_id).get("ExitCode") != 0:
        return None
    unread = unanswered(output, spec)
    if len(unread) == len(spec["checks"]):
        return None
    return {"hits": judge(output, spec), "unread": unread}


def read_all(services: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per running managed copy of a service that declares a probe.

    A row carries ``definition`` (see fingerprint) and, when the read worked,
    ``hits``, the indexes of the checks that hold, and ``unread``, those it
    could not judge; ``error`` when it did not work at all: an unread node is
    no verdict, never a healthy one. Copies not reached within BATCH_BUDGET
    are reported unread, so the ones read in time still count.
    """
    # Imported here: the UI imports this module for nothing but the catalog
    # check, and has no Docker.
    from app import orchestrator

    rows: list[dict[str, Any]] = []
    deadline = time.monotonic() + BATCH_BUDGET
    client = None
    for slug, spec in sorted(probes(services).items()):
        try:
            copies = orchestrator.service_instances(slug)
        except Exception as exc:  # noqa: BLE001 - one service never fails the rest
            logger.warning("Could not list %s containers for the health probe: %s", slug, exc)
            continue
        for container in copies:
            if getattr(container, "status", "") != "running":
                continue
            row: dict[str, Any] = {
                "slug": slug,
                "instance": orchestrator._instance_of(container),
                "definition": fingerprint(spec),
            }
            rows.append(row)
            left = min(READ_TIMEOUT, deadline - time.monotonic())
            if left <= 0:
                row["error"] = "not reached in time"
                continue
            future = None
            try:
                if client is None:
                    client = _client()
                future = _pool.submit(_read_one, client, container.id, spec)
                read = future.result(timeout=left)
            except concurrent.futures.TimeoutError:
                # Still queued: never run it. Running: the client's socket
                # timeout ends it.
                future.cancel()
                row["error"] = "timed out"
            except Exception as exc:  # noqa: BLE001
                logger.warning("Health probe failed for %s: %s", slug, exc)
                row["error"] = "read failed"
            else:
                if read is None:
                    row["error"] = "the node did not answer"
                else:
                    row.update(read)
    # A read that timed out may still be using the client; it is dropped, not
    # closed, so that read ends on its own socket timeout.
    return rows
