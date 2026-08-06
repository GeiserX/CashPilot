"""Tell the operator when a newer CashPilot has been released.

WHY THIS EXISTS (CashPilot-w0ss)
--------------------------------
A live fleet sat **33 releases** behind and nothing anywhere said so. Not the
dashboard, not a log line, not the fleet page.

Half the machinery was already here: ``app/version.py`` knows what this build is
and ``version.skewed()`` compares it against each worker. What was missing is a
reference point OUTSIDE the deployment -- nothing in the application had any idea
what the newest published release was.

THREE CONSTRAINTS, and they are the difference between a useful feature and an
unwelcome one:

* **Degrade silently when offline.** An air-gapped or firewalled install must not
  show an error, a spinner, or a warning about the check itself. Unknown is
  unknown -- the same rule the rest of this codebase follows for absent data.
* **Never auto-update.** This deploys containers and holds credentials. It tells
  you; you decide.
* **Answerable.** ``CASHPILOT_UPDATE_CHECK=off`` disables the outbound call
  entirely, for anyone who does not want their install talking to GitHub.

The check is a single unauthenticated GET to the public releases endpoint, once a
day. It sends no telemetry: GitHub learns an IP asked what the latest release is,
and nothing else. There is no request body, no identifier, and no version
reported upstream.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from app import version

logger = logging.getLogger(__name__)

#: The public releases endpoint. Unauthenticated, and deliberately the "latest"
#: single-object form rather than a paginated list: it is one small response and
#: it cannot be made expensive by a repository with a long release history.
LATEST_URL = "https://api.github.com/repos/GeiserX/CashPilot/releases/latest"

#: Once a day. A release is not urgent, and a self-hosted app polling a third
#: party more often than that is rude.
CHECK_INTERVAL_SECONDS = 24 * 60 * 60

_HTTP_TIMEOUT = 10.0

#: Cached result. `tag` is None for UNKNOWN -- never for "up to date", which is a
#: different statement and is carried by `known`.
_latest_tag: str | None = None
_checked_at: float = 0.0


def enabled() -> bool:
    """Whether the outbound check is allowed at all.

    On by default, matching how comparable self-hosted projects behave, and how
    this application already reaches CoinGecko and Frankfurter. Off is one
    environment variable away, and when off NOTHING is fetched -- the banner
    simply never appears rather than showing an error.
    """
    return os.getenv("CASHPILOT_UPDATE_CHECK", "").strip().lower() not in {"0", "off", "false", "no"}


def _parse_tag(payload: Any) -> str | None:
    """The tag name from a releases payload, or None if it is not one.

    Validated rather than trusted: this is third-party JSON, and a tag that is
    not a real version would otherwise be rendered to the operator as one.
    """
    if not isinstance(payload, dict):
        return None
    tag = str(payload.get("tag_name") or "").strip()
    return tag if version.series(tag) else None


async def refresh(*, force: bool = False) -> str | None:
    """Fetch the newest published release tag. Returns it, or None for unknown.

    Never raises. Every failure mode -- offline, DNS, rate limit, a 500, a body
    that is not JSON, a tag that is not a version -- lands on the same answer:
    UNKNOWN. That is what makes the banner safe on an air-gapped install.
    """
    global _latest_tag, _checked_at

    if not enabled():
        return None
    if not force and _checked_at and (time.time() - _checked_at) < CHECK_INTERVAL_SECONDS:
        return _latest_tag

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(LATEST_URL, headers={"Accept": "application/vnd.github+json"})
            response.raise_for_status()
            tag = _parse_tag(response.json())
    except Exception as exc:  # noqa: BLE001 - every failure means the same thing
        # DEBUG, not WARNING. A firewalled install would otherwise log a warning
        # every day forever about a feature its operator never asked for, and a
        # log full of harmless warnings is a log nobody reads.
        logger.debug("Update check could not reach %s: %s", LATEST_URL, exc)
        _checked_at = time.time()  # do not hammer a host that is refusing us
        return _latest_tag

    _latest_tag = tag
    _checked_at = time.time()
    if tag:
        logger.debug("Newest published release is %s", tag)
    return tag


def state() -> dict[str, Any]:
    """What the UI needs to decide whether to say anything.

    ``known`` is the honest three-valued part: False means we do not know, which
    is NOT the same as "up to date" and must not be rendered as reassurance.
    """
    running = version.current()
    running_series = version.series(running)
    latest_series = version.series(_latest_tag)

    behind = False
    if running_series and latest_series:
        behind = _tuple(latest_series) > _tuple(running_series)

    return {
        "enabled": enabled(),
        # Unknown whenever the check is off, has not run, failed, or this build
        # is not a release (a dev checkout must not be told it is behind).
        "known": bool(_latest_tag and running_series),
        "current": running,
        "latest": _latest_tag,
        "behind": behind,
    }


def _tuple(series_text: str) -> tuple[int, ...]:
    """MAJOR.MINOR as integers, so 1.9 sorts BELOW 1.10.

    String comparison gets this backwards, and it would do so exactly once a
    project reaches its tenth minor -- which this one has.
    """
    return tuple(int(part) for part in series_text.split("."))


def _reset_for_tests() -> None:
    """Clear the module cache. Tests only."""
    global _latest_tag, _checked_at
    _latest_tag, _checked_at = None, 0.0
