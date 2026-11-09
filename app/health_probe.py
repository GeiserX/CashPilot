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
ends the command in the container. That does not bound the exec stream: if the
daemon or the socket proxy stops sending, docker-py's own reader waits on the
socket with no timeout (``docker.utils.socket.read`` polls without one). So the
exec runs on a client of this module's own with a READ_TIMEOUT socket timeout
for the API calls, and its output is read here from the raw socket against a
READ_TIMEOUT deadline (_read_stream). A stalled read ends and frees its thread,
and at most as many reads as the pool has threads are ever in flight or queued
(_slots): a copy that finds them all taken is reported unread, never queued.

Read-only by construction, like ``app/node_read.py``: the command comes from
the catalog in this image, never from a request, and only the indexes of the
checks that hold leave the worker, never the output.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import functools
import hashlib
import json
import logging
import re
import select
import socket
import struct
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

#: Seconds one container's read may take before it is reported as unread.
READ_TIMEOUT = 15
#: Seconds one /api/health-probes answer may take in all. The UI waits 60 s for
#: it; copies not read by then are reported unread, and the rest still go back.
BATCH_BUDGET = 40

_POOL_SIZE = 4
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=_POOL_SIZE, thread_name_prefix="health-probe")
#: One per read submitted and not finished, so the pool's queue never grows.
_slots = threading.BoundedSemaphore(_POOL_SIZE)
#: Per service, the copy the next read_all starts with: the first one the last
#: call did not reach, so a slow copy cannot keep the later ones unread.
_resume: dict[str, int] = {}
#: The service the next read_all starts with: the first one the last call did
#: not finish, so a slow service cannot keep the later ones unread.
_resume_service: str | None = None


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


def judge(output: bytes | str | None, spec: dict[str, Any], unread: list[int] | None = None) -> list[int]:
    """The indexes of the checks that hold on the command's output (unread ones never do)."""
    unread = set(unanswered(output, spec) if unread is None else unread)
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


def _recv(sock: Any, deadline: float) -> bytes:
    """One chunk from the exec socket, waiting no later than ``deadline``; b"" at its end."""
    left = deadline - time.monotonic()
    if left <= 0 or not select.select([sock], [], [], left)[0]:
        raise TimeoutError("the exec stream stalled")
    if hasattr(sock, "recv"):
        return sock.recv(65536)
    return sock.read(65536) or b""


def _read_stream(sock: Any, deadline: float) -> bytes:
    """The stdout and stderr of a non-tty exec, read from its raw socket by ``deadline``.

    The stream is Docker's multiplexed format: an 8-byte header (stream, three
    zero bytes, payload size) before each payload.
    """
    data = b""
    while True:
        chunk = _recv(sock, deadline)
        if not chunk:
            break
        data += chunk
    out, pos = [], 0
    while pos + 8 <= len(data):
        size = struct.unpack(">I", data[pos + 4 : pos + 8])[0]
        out.append(data[pos + 8 : pos + 8 + size])
        pos += 8 + size
    return b"".join(out)


def _close_exec_socket(sock: Any) -> None:
    """Close an exec's hijacked connection now, whatever state the read left it in.

    A read that hit its deadline leaves the exec running on the other end, so
    the connection is shut down first rather than left to the garbage
    collector. Closing only the socket would leave the HTTP response docker-py
    hangs on it to fail on its own close later, so that is closed too.
    """
    raw = getattr(sock, "_sock", sock)
    with contextlib.suppress(OSError):
        raw.shutdown(socket.SHUT_RDWR)
    response = getattr(sock, "_response", None)
    for thing in (response, sock, raw):
        if thing is not None:
            with contextlib.suppress(Exception):
                thing.close()


def _read_one(client: Any, container_id: str, spec: dict[str, Any]) -> dict[str, list[int]] | None:
    """Run the probe in one container: hits and unread checks, or None when nothing was read."""
    deadline = time.monotonic() + READ_TIMEOUT
    api = client.api
    exec_id = api.exec_create(container_id, spec["command"])["Id"]
    sock = api.exec_start(exec_id, socket=True)
    try:
        output = _read_stream(sock, deadline)
    finally:
        _close_exec_socket(sock)
    unread = unanswered(output, spec)
    if api.exec_inspect(exec_id).get("ExitCode") != 0:
        # The command failed or ran out of time part way. A check whose marker
        # made it out was read in full (the marker comes after its data); a
        # check without a marker cannot tell, so it counts as unread.
        unread = sorted({*unread, *(i for i, c in enumerate(spec["checks"]) if not c.get("answered"))})
    if len(unread) == len(spec["checks"]):
        return None
    return {"hits": judge(output, spec, unread), "unread": unread}


def _read_error(exc: Exception, slug: str) -> str:
    """Why a read raised, as the worker reports it to the UI."""
    from app import orchestrator

    if orchestrator.proxy_refusal(exc) is None:
        logger.warning("Health probe failed for %s: %s", slug, exc)
        return "read failed"
    logger.warning("The socket proxy refused the %s health probe: %s", slug, exc)
    if orchestrator.proxy_policy_fix() is not None:
        return (
            "the Docker socket proxy refused the read because its policy is older than this "
            "worker; update it as the worker's status page shows"
        )
    return "the Docker socket proxy refused the read"


def read_all(services: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per running managed copy of a service that declares a probe.

    A row carries ``definition`` (see fingerprint) and, when the read worked,
    ``hits``, the indexes of the checks that hold, and ``unread``, those it
    could not judge; ``error`` when it did not work at all: an unread node is
    no verdict, never a healthy one. Listing the copies and reading them both
    fit in BATCH_BUDGET: what is not reached is reported unread or not listed,
    and the rows already read still go back. The next call starts with the
    first service, and within it the first copy, this one did not reach, so a
    slow service or copy cannot keep the others unread.
    """
    # Imported here: the UI imports this module for nothing but the catalog
    # check, and has no Docker.
    from app import orchestrator

    global _resume_service
    rows: list[dict[str, Any]] = []
    deadline = time.monotonic() + BATCH_BUDGET
    client = None
    declared = sorted(probes(services).items())
    names = [slug for slug, _ in declared]
    if _resume_service in names:
        k = names.index(_resume_service)
        declared = declared[k:] + declared[:k]
    _resume_service = None

    def _unreached(slug: str) -> None:
        """Remember the first service this call did not finish."""
        global _resume_service
        if _resume_service is None:
            _resume_service = slug

    def _list(slug: str) -> Any:
        """Make the client if there is none yet, then list ``slug``'s copies."""
        nonlocal client
        if client is None:
            client = _client()
        return orchestrator.service_instances(slug, client=client)

    for n, (slug, spec) in enumerate(declared):
        left = min(READ_TIMEOUT, deadline - time.monotonic())
        if left <= 0 or not _slots.acquire(blocking=False):
            # Not listed: the UI keeps these copies' last verdicts.
            _unreached(slug)
            break
        try:
            # Making the client and listing both run on the pool in the slot
            # just taken, so a failure gives the slot back and a stall ends
            # within the batch's remaining time.
            copies = _run_in_pool(functools.partial(_list, slug), left)
        except TimeoutError:
            logger.warning("Listing %s containers for the health probe ran out of time", slug)
            # The next call starts after this service, so one that always
            # stalls cannot keep the ones behind it from ever being read.
            _unreached(declared[(n + 1) % len(declared)][0])
            break
        except Exception as exc:  # noqa: BLE001 - one service never fails the rest
            logger.warning("Could not list %s containers for the health probe: %s", slug, exc)
            continue
        running = [c for c in copies if getattr(c, "status", "") == "running"]
        mine = [
            {"slug": slug, "instance": orchestrator._instance_of(c), "definition": fingerprint(spec)} for c in running
        ]
        rows.extend(mine)
        start = _resume.pop(slug, 0) % len(running) if running else 0
        for i in [*range(start, len(running)), *range(start)]:
            row = mine[i]
            left = min(READ_TIMEOUT, deadline - time.monotonic())
            if left <= 0:
                row["error"] = "not reached in time"
            elif not _slots.acquire(blocking=False):
                # Every thread still busy with an earlier read: say so rather
                # than queue behind it.
                row["error"] = "busy with earlier reads"
            else:
                row.update(_read_in_pool(client, running[i].id, spec, left, slug))
            if row.get("error") in ("not reached in time", "busy with earlier reads"):
                _resume.setdefault(slug, i)
                _unreached(slug)
    # A read that timed out may still be using the client; it is dropped, not
    # closed, so that read ends by its own deadline.
    return rows


def _run_in_pool(fn: Any, left: float) -> Any:
    """Run ``fn`` on the pool in the slot already taken, waiting up to ``left`` seconds.

    Raises TimeoutError when it takes longer; the work then ends by its own
    timeout and gives the slot back.
    """
    try:
        future = _pool.submit(fn)
    except BaseException:
        _slots.release()
        raise
    future.add_done_callback(lambda _f: _slots.release())
    return future.result(timeout=left)


def _read_in_pool(client: Any, container_id: str, spec: dict[str, Any], left: float, slug: str) -> dict[str, Any]:
    """Run one read on the pool, holding the slot already taken, and wait up to ``left`` seconds."""
    try:
        read = _run_in_pool(functools.partial(_read_one, client, container_id, spec), left)
    except TimeoutError:
        # The read ends by its own deadline and frees its slot then.
        return {"error": "timed out"}
    except Exception as exc:  # noqa: BLE001
        return {"error": _read_error(exc, slug)}
    if read is None:
        return {"error": "the node did not answer"}
    return read
