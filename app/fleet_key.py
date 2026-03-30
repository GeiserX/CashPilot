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


def resolve_fleet_key() -> str:
    """Resolve the fleet API key.

    Priority:
    1. CASHPILOT_API_KEY env var (explicit configuration)
    2. Shared key file at /fleet/.fleet_key (auto-generated on first use)
    """
    key = os.getenv("CASHPILOT_API_KEY", "")
    if key:
        return key

    # Try to read existing shared key file
    try:
        if _FLEET_KEY_FILE.is_file():
            stored = _FLEET_KEY_FILE.read_text().strip()
            if stored:
                _logger.info("Loaded fleet key from %s", _FLEET_KEY_FILE)
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
        return new_key
    except FileExistsError:
        # Other container created it first — poll briefly for content
        # (file exists but may be empty until the writer finishes)
        for _ in range(20):
            try:
                stored = _FLEET_KEY_FILE.read_text().strip()
                if stored:
                    _logger.info("Loaded fleet key from %s", _FLEET_KEY_FILE)
                    return stored
            except OSError:
                pass
            time.sleep(0.1)
    except OSError as exc:
        _logger.warning(
            "Could not persist fleet key to %s: %s — set CASHPILOT_API_KEY or mount a shared /fleet volume",
            _FLEET_KEY_FILE,
            exc,
        )

    return ""
