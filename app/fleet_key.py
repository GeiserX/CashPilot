"""Auto-generate and share a fleet API key between UI and worker containers.

When CASHPILOT_API_KEY is not set, both containers resolve the key from a
shared volume at /fleet/.fleet_key. The first container to start generates
the key atomically; the second reads it.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from pathlib import Path

_logger = logging.getLogger(__name__)

_FLEET_KEY_DIR = Path(os.getenv("CASHPILOT_FLEET_DIR", "/fleet"))
_FLEET_KEY_FILE = _FLEET_KEY_DIR / ".fleet_key"


#: The last successful resolution, as (path it was resolved for, key).
#:
#: app/auth.py calls this on EVERY request carrying an Authorization header —
#: every worker heartbeat, every Home Assistant poll. Nothing rotates the file
#: and nothing outside this module writes it, so re-reading it per request buys
#: nothing and costs two filesystem syscalls each time.
#:
#: Keyed on the path so a test that patches _FLEET_KEY_FILE re-resolves rather
#: than seeing another test's key.
_resolved: tuple[Path, str] | None = None

#: The last failure already reported, as (path, message). Without this the log
#: filled with one ERROR per request on an install whose /fleet is not writable
#: — an Unraid run with an explicit --user, where entrypoint.sh skips the chown
#: — burying the single line that explains it (CashPilot-9mw).
_reported_failure: tuple[Path, str] | None = None


def resolve_fleet_key() -> str:
    """Resolve the fleet API key.

    Priority:
    1. CASHPILOT_API_KEY env var (explicit configuration)
    2. Shared key file at /fleet/.fleet_key (auto-generated on first use)

    A successful resolution is remembered. A failure is not: the volume may be
    fixed while the process runs, and a cached failure would keep rejecting
    workers long after the cause was gone. Only the LOG is suppressed.
    """
    global _resolved
    key = os.getenv("CASHPILOT_API_KEY", "")
    if key:
        return key

    if _resolved is not None and _resolved[0] == _FLEET_KEY_FILE:
        return _resolved[1]

    # Try to read existing shared key file
    try:
        if _FLEET_KEY_FILE.is_file():
            stored = _FLEET_KEY_FILE.read_text().strip()
            if stored:
                _logger.info("Loaded fleet key from %s", _FLEET_KEY_FILE)
                _resolved = (_FLEET_KEY_FILE, stored)
                return stored
    except OSError:
        pass

    # Auto-generate and persist atomically (O_EXCL = only one writer wins)
    new_key = secrets.token_urlsafe(32)
    try:
        _FLEET_KEY_DIR.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(_FLEET_KEY_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(fd, new_key.encode())
        os.close(fd)
        _logger.info("Generated shared fleet key at %s", _FLEET_KEY_FILE)
        _resolved = (_FLEET_KEY_FILE, new_key)
        return new_key
    except FileExistsError:
        # Other container created it first — poll briefly for content
        # (file exists but may be empty until the writer finishes)
        for _ in range(20):
            try:
                stored = _FLEET_KEY_FILE.read_text().strip()
                if stored:
                    _logger.info("Loaded fleet key from %s", _FLEET_KEY_FILE)
                    _resolved = (_FLEET_KEY_FILE, stored)
                    return stored
            except OSError:
                pass
            time.sleep(0.1)
    except OSError as exc:
        # Reported once per distinct failure, not once per request. A changed
        # error is a changed situation and is reported again.
        global _reported_failure
        signature = (_FLEET_KEY_FILE, str(exc))
        if _reported_failure != signature:
            _reported_failure = signature
            _logger.error(
                "Cannot write fleet key to %s: %s. "
                "Fix: set CASHPILOT_API_KEY env var explicitly, "
                "or fix /fleet volume permissions (chown 1000:0 /fleet on the host). "
                "This is logged once; every request that needs the fleet key will keep failing until it is fixed.",
                _FLEET_KEY_FILE,
                exc,
            )

    return ""
