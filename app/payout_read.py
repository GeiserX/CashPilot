"""Read a payout address that is set inside a running container (worker side).

Some services take their payout address after deploy rather than from an env
var: Mysterium's beneficiary is set through its TequilAPI, Anyone's wallet sits
in the anonrc ContactInfo line. The UI cannot read either, so the payouts page
said "Not set" for addresses that were set. The worker runs next to the
container, so it reads them here.

The catalog declares how, in ``payout.address_read``:

    address_read:
      command: ["cat", "/etc/anon/anonrc"]     # run inside the container
      pattern: '@anon:\\s*(0x[0-9a-fA-F]{40})'  # group 1 is the address

Read-only by construction: the command comes from the catalog in this image,
never from a request, and only the pattern's first group leaves the worker, so
anything else the output holds (an email in ContactInfo) stays here.
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
from typing import Any

from app import orchestrator

logger = logging.getLogger(__name__)

#: Seconds one container's read may take before it is reported as unread.
READ_TIMEOUT = 10

_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="payout-read")


def readers(services: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """slug -> its declared reader, for services that declare a well-formed one."""
    out: dict[str, dict[str, Any]] = {}
    for svc in services:
        spec = (svc.get("payout") or {}).get("address_read")
        if not isinstance(spec, dict):
            continue
        command, pattern = spec.get("command"), spec.get("pattern")
        if not (isinstance(command, list) and command and all(isinstance(p, str) for p in command)):
            continue
        if not isinstance(pattern, str):
            continue
        try:
            compiled = re.compile(pattern)
        except re.error:
            logger.warning("Ignoring %s payout.address_read: the pattern does not compile", svc.get("slug"))
            continue
        if compiled.groups < 1:
            continue
        out[svc["slug"]] = {"command": command, "pattern": compiled}
    return out


def extract(output: bytes | str | None, pattern: re.Pattern[str]) -> str | None:
    text = output.decode(errors="replace") if isinstance(output, bytes) else (output or "")
    match = pattern.search(text)
    return match.group(1) if match else None


def _read_one(container: Any, reader: dict[str, Any]) -> str | None:
    code, output = container.exec_run(reader["command"])
    if code != 0:
        return None
    return extract(output, reader["pattern"])


def read_all(services: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per running managed copy of a service that declares a reader.

    ``address`` is None when the read ran and found nothing, and ``error`` says
    why when it could not run. Neither is ever "no address": the UI shows both
    as not checked.
    """
    rows: list[dict[str, Any]] = []
    for slug, reader in sorted(readers(services).items()):
        try:
            copies = orchestrator.service_instances(slug)
        except Exception as exc:  # noqa: BLE001 - one service never fails the rest
            logger.warning("Could not list %s containers for the payout read: %s", slug, exc)
            continue
        for container in copies:
            if getattr(container, "status", "") != "running":
                continue
            row: dict[str, Any] = {"slug": slug, "instance": orchestrator._instance_of(container), "address": None}
            try:
                row["address"] = _pool.submit(_read_one, container, reader).result(timeout=READ_TIMEOUT)
            except concurrent.futures.TimeoutError:
                row["error"] = "timed out"
            except Exception as exc:  # noqa: BLE001
                logger.warning("Payout address read failed for %s: %s", slug, exc)
                row["error"] = "read failed"
            rows.append(row)
    return rows
