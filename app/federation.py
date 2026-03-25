"""Federation module for CashPilot.

Handles master/child roles, join token generation/validation,
and WebSocket-based communication between nodes.

Two auth methods for child nodes:
  1. **Join token** (generated in master UI) — HMAC-signed, can be
     time-limited or permanent, reusable across multiple nodes.
  2. **Master key** — persistent reusable key derived from
     CASHPILOT_SECRET_KEY. Always valid. Best for automation/IaC.

The child sets CASHPILOT_JOIN_TOKEN to either kind; the master
validates both the same way.

Configuration via environment variables:
  CASHPILOT_ROLE          = master | child | standalone (default: standalone)
  CASHPILOT_NODE_NAME     = human-readable node name (default: hostname)
  CASHPILOT_MASTER_URL    = wss://master-host:port/ws/federation (child only)
  CASHPILOT_JOIN_TOKEN    = token or master key (child only)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import platform
import secrets
import socket
import time
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROLE = os.getenv("CASHPILOT_ROLE", "master").lower()
NODE_NAME = os.getenv("CASHPILOT_NODE_NAME", socket.gethostname())
MASTER_URL = os.getenv("CASHPILOT_MASTER_URL", "")
JOIN_TOKEN = os.getenv("CASHPILOT_JOIN_TOKEN", "")
SECRET_KEY = os.getenv("CASHPILOT_SECRET_KEY", "changeme-generate-a-random-secret")

# Heartbeat interval in seconds
HEARTBEAT_INTERVAL = 30

# Valid roles
VALID_ROLES = ("master", "child", "standalone")


def is_master() -> bool:
    return ROLE == "master"


def is_child() -> bool:
    return ROLE == "child"


def is_standalone() -> bool:
    return ROLE == "standalone"


def get_role() -> str:
    return ROLE if ROLE in VALID_ROLES else "standalone"


def get_node_info() -> dict[str, Any]:
    """Return basic info about this node."""
    return {
        "name": NODE_NAME,
        "role": get_role(),
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "python": platform.python_version(),
        "hostname": socket.gethostname(),
    }


# ---------------------------------------------------------------------------
# Join Token Management
# ---------------------------------------------------------------------------

# Token format: base64(json({"node_name": ..., "created": ..., "nonce": ...}))
# Signed with HMAC-SHA256 using CASHPILOT_SECRET_KEY
# Format: payload_hex.signature_hex


def generate_join_token(
    node_name: str = "",
    expires_hours: int = 24,
) -> str:
    """Generate an HMAC-signed join token (master only).

    Args:
        node_name: Optional pre-assigned name for the joining node.
        expires_hours: Token validity in hours (0 = no expiry).

    Returns:
        A signed token string: payload_hex.signature_hex
    """
    payload = {
        "n": node_name,
        "c": int(time.time()),
        "x": int(time.time()) + (expires_hours * 3600) if expires_hours else 0,
        "r": secrets.token_hex(8),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode()
    payload_hex = payload_bytes.hex()
    sig = hmac.new(SECRET_KEY.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return f"{payload_hex}.{sig}"


def validate_join_token(token: str) -> dict[str, Any] | None:
    """Validate a join token and return its payload, or None if invalid.

    Returns:
        Dict with keys: n (node_name), c (created), x (expires), r (nonce)
        or None if the token is invalid/expired.
    """
    try:
        parts = token.split(".", 1)
        if len(parts) != 2:
            return None
        payload_hex, sig = parts
        payload_bytes = bytes.fromhex(payload_hex)
        expected_sig = hmac.new(SECRET_KEY.encode(), payload_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            logger.warning("Join token signature mismatch")
            return None
        payload = json.loads(payload_bytes)
        # Check expiry
        if payload.get("x") and payload["x"] < time.time():
            logger.warning("Join token expired")
            return None
        return payload
    except Exception as exc:
        logger.warning("Join token validation failed: %s", exc)
        return None


def get_master_key() -> str:
    """Derive a persistent, reusable master key from the secret.

    This key never expires and can be used by any number of child nodes.
    It's shown in the master Fleet UI and is the easiest way to enroll
    nodes in automated/IaC setups.
    """
    return hmac.new(SECRET_KEY.encode(), b"cashpilot-master-key-v1", hashlib.sha256).hexdigest()


def validate_master_key(token: str) -> bool:
    """Check if a token matches the derived master key."""
    return hmac.compare_digest(token, get_master_key())


def hash_token(token: str) -> str:
    """Create a storage-safe hash of a join token."""
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# WebSocket Message Protocol
# ---------------------------------------------------------------------------

# Message types (child -> master)
MSG_AUTH = "auth"  # Initial authentication with join token
MSG_HEARTBEAT = "heartbeat"  # Periodic status update
MSG_EARNINGS = "earnings"  # Earnings data sync

# Message types (master -> child)
MSG_AUTH_OK = "auth_ok"
MSG_AUTH_FAIL = "auth_fail"
MSG_COMMAND = "command"  # Remote command (deploy, stop, restart, remove)
MSG_ACK = "ack"  # Command acknowledgment


def make_message(msg_type: str, data: dict[str, Any] | None = None) -> str:
    """Create a JSON WebSocket message."""
    msg = {"type": msg_type, "ts": int(time.time())}
    if data:
        msg["data"] = data
    return json.dumps(msg)


def parse_message(raw: str) -> dict[str, Any] | None:
    """Parse a JSON WebSocket message, returning None on failure."""
    try:
        msg = json.loads(raw)
        if not isinstance(msg, dict) or "type" not in msg:
            return None
        return msg
    except (json.JSONDecodeError, TypeError):
        return None
