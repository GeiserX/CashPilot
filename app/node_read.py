"""Read a node's own earnings figures from inside its container (worker side).

Mysterium's cloud API reports only a trailing 30-day sum, and its per-node
lifetime figure comes back as 0, so neither can be a balance or a lifetime
total (issue #488). The node itself knows both: TequilAPI's identity answers
with the unsettled amount and the lifetime total. TequilAPI listens on loopback
inside the node, so the UI cannot ask it. The worker runs next to the
container, so it asks here.

The catalog declares how, in ``collector.node_read``:

    node_read:
      command: ["sh", "-c", "..."]          # run inside the container
      node: '"id":"(0x[0-9a-fA-F]{40})"'    # group 1 names the node
      balance: '...'                        # group 1 is the unsettled amount
      lifetime: '...'                       # group 1 is everything it ever earned
      settled_net: '...'                    # optional, every match summed: paid to the wallet
      settled_fees: '...'                   # optional, every match summed: fees kept back

The two optional sums, in any one unit, give the share of each settlement the
provider keeps as a fee (Mysterium's Hermes fee, about a fifth): lifetime and
balance are gross, and only the rest reaches the wallet.

Read-only by construction, like ``app/payout_read.py``: the command comes from
the catalog in this image, never from a request, and only the three groups
leave the worker.
"""

from __future__ import annotations

import concurrent.futures
import logging
import math
import re
from typing import Any

from app import orchestrator

logger = logging.getLogger(__name__)

#: Seconds one container's read may take before it is reported as unread.
READ_TIMEOUT = 10

_FIELDS = ("node", "balance", "lifetime")
#: Optional; every match is summed, and both must be declared to be used.
_SUMS = ("settled_net", "settled_fees")

_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="node-read")


def readers(services: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """slug -> its declared reader, for services that declare a well-formed one."""
    out: dict[str, dict[str, Any]] = {}
    for svc in services:
        spec = (svc.get("collector") or {}).get("node_read")
        if not isinstance(spec, dict):
            continue
        command = spec.get("command")
        if not (isinstance(command, list) and command and all(isinstance(p, str) for p in command)):
            continue
        compiled: dict[str, re.Pattern[str]] = {}
        for field in _FIELDS:
            pattern = spec.get(field)
            if not isinstance(pattern, str):
                break
            try:
                compiled[field] = re.compile(pattern)
            except re.error:
                logger.warning(
                    "Ignoring %s collector.node_read: the %s pattern does not compile", svc.get("slug"), field
                )
                break
            if compiled[field].groups < 1:
                break
        if len(compiled) != len(_FIELDS):
            continue
        sums: dict[str, re.Pattern[str]] = {}
        for field in _SUMS:
            pattern = spec.get(field)
            try:
                compiled_sum = re.compile(pattern) if isinstance(pattern, str) else None
            except re.error:
                compiled_sum = None
            if compiled_sum is not None and compiled_sum.groups == 1:
                sums[field] = compiled_sum
        if len(sums) == len(_SUMS):
            compiled.update(sums)
        out[svc["slug"]] = {"command": command, **compiled}
    return out


def _amount(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) and value >= 0 else None


def extract(output: bytes | str | None, reader: dict[str, Any]) -> dict[str, Any] | None:
    """The node's id, unsettled amount and lifetime total, or None if any is missing.

    A lifetime below the unsettled amount is not a reading: everything waiting
    to settle is part of what the node ever earned.
    """
    text = output.decode(errors="replace") if isinstance(output, bytes) else (output or "")
    found: dict[str, str] = {}
    for field in _FIELDS:
        match = reader[field].search(text)
        if not match:
            return None
        found[field] = match.group(1)
    balance, lifetime = _amount(found["balance"]), _amount(found["lifetime"])
    if balance is None or lifetime is None or lifetime < balance:
        return None
    figures: dict[str, Any] = {"node": found["node"], "balance": balance, "lifetime": lifetime}
    if all(field in reader for field in _SUMS):
        totals = {field: [_amount(m) for m in reader[field].findall(text)] for field in _SUMS}
        # No match at all is "not known" (the history could not be read), not
        # "no fee": a node that never settled has nothing to net anyway.
        if all(totals[field] and None not in totals[field] for field in _SUMS):
            for field in _SUMS:
                figures[field] = sum(totals[field])
    return figures


def _read_one(container: Any, reader: dict[str, Any]) -> dict[str, Any] | None:
    code, output = container.exec_run(reader["command"])
    if code != 0:
        return None
    return extract(output, reader)


def read_all(services: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per running managed copy of a service that declares a reader.

    A row carries ``node``, ``balance`` and ``lifetime`` when the read worked,
    and ``error`` when it did not. The UI uses only the rows that worked.
    """
    rows: list[dict[str, Any]] = []
    for slug, reader in sorted(readers(services).items()):
        try:
            copies = orchestrator.service_instances(slug)
        except Exception as exc:  # noqa: BLE001 - one service never fails the rest
            logger.warning("Could not list %s containers for the node read: %s", slug, exc)
            continue
        for container in copies:
            if getattr(container, "status", "") != "running":
                continue
            row: dict[str, Any] = {"slug": slug, "instance": orchestrator._instance_of(container)}
            try:
                figures = _pool.submit(_read_one, container, reader).result(timeout=READ_TIMEOUT)
            except concurrent.futures.TimeoutError:
                row["error"] = "timed out"
            except Exception as exc:  # noqa: BLE001
                logger.warning("Node read failed for %s: %s", slug, exc)
                row["error"] = "read failed"
            else:
                if figures is None:
                    row["error"] = "no figures in the node's answer"
                else:
                    row.update(figures)
            rows.append(row)
    return rows
