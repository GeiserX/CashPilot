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
          means: "..."

A check without ``items`` holds when ``pattern`` matches the output at least
``min_matches`` times (default 1). With ``items`` it holds when the output has
at least ``min_matches`` items and every one of them matches ``pattern``: one
good item clears it, and too few items say nothing. Patterns are
case-sensitive, like ``collector.node_read``.

The command must start with ``timeout <seconds>`` below READ_TIMEOUT.
``exec_run`` has no timeout of its own: a read that hung would keep its pool
thread after the worker stopped waiting, and four of them would leave every
later read queued behind them for the worker's lifetime.

Read-only by construction, like ``app/node_read.py``: the command comes from
the catalog in this image, never from a request, and only the indexes of the
checks that hold leave the worker, never the output.
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

#: Seconds one container's read may take before it is reported as unread.
READ_TIMEOUT = 15

_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="health-probe")


def _min_matches(check: dict[str, Any]) -> int | None:
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
        for field in ("pattern", "items"):
            value = check.get(field)
            if value is None and field == "items":
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


def judge(output: bytes | str | None, spec: dict[str, Any]) -> list[int]:
    """The indexes of the checks that hold on the command's output."""
    return [i for i, check in enumerate(spec["checks"]) if holds(output, check)]


def _read_one(container: Any, spec: dict[str, Any]) -> list[int] | None:
    code, output = container.exec_run(spec["command"])
    if code != 0:
        return None
    return judge(output, spec)


def read_all(services: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per running managed copy of a service that declares a probe.

    A row carries ``hits``, the indexes of the checks that hold, when the read
    worked, and ``error`` when it did not: an unread node is no verdict, never
    a healthy one.
    """
    # Imported here: the UI imports this module for nothing but the catalog
    # check, and has no Docker.
    from app import orchestrator

    rows: list[dict[str, Any]] = []
    for slug, spec in sorted(probes(services).items()):
        try:
            copies = orchestrator.service_instances(slug)
        except Exception as exc:  # noqa: BLE001 - one service never fails the rest
            logger.warning("Could not list %s containers for the health probe: %s", slug, exc)
            continue
        for container in copies:
            if getattr(container, "status", "") != "running":
                continue
            row: dict[str, Any] = {"slug": slug, "instance": orchestrator._instance_of(container)}
            try:
                hits = _pool.submit(_read_one, container, spec).result(timeout=READ_TIMEOUT)
            except concurrent.futures.TimeoutError:
                row["error"] = "timed out"
            except Exception as exc:  # noqa: BLE001
                logger.warning("Health probe failed for %s: %s", slug, exc)
                row["error"] = "read failed"
            else:
                if hits is None:
                    row["error"] = "the node did not answer"
                else:
                    row["hits"] = hits
            rows.append(row)
    return rows
