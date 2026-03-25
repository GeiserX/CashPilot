"""WebSocket federation server (master node).

Accepts incoming connections from child nodes, validates join tokens,
processes heartbeats, and dispatches remote commands.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app import database, federation

logger = logging.getLogger(__name__)

# Active child connections: node_id -> WebSocket
_connections: dict[int, WebSocket] = {}

# In-memory cache of last heartbeat data per node
_node_states: dict[int, dict[str, Any]] = {}


def get_connected_nodes() -> dict[int, dict[str, Any]]:
    """Return cached state for all connected child nodes."""
    return dict(_node_states)


def get_connection_count() -> int:
    return len(_connections)


async def handle_connection(ws: WebSocket) -> None:
    """Handle a single child WebSocket connection on the master."""
    await ws.accept()
    node_id: int | None = None

    try:
        # First message must be auth
        raw = await ws.receive_text()
        msg = federation.parse_message(raw)
        if not msg or msg.get("type") != federation.MSG_AUTH:
            await ws.send_text(federation.make_message(federation.MSG_AUTH_FAIL, {"reason": "Expected auth message"}))
            await ws.close(code=4001, reason="Auth required")
            return

        token = msg.get("data", {}).get("token", "")
        node_info = msg.get("data", {}).get("node_info", {})

        # Validate: accept either a master key or a signed join token
        is_master_key = federation.validate_master_key(token)
        payload = None
        if not is_master_key:
            payload = federation.validate_join_token(token)
            if not payload:
                await ws.send_text(
                    federation.make_message(federation.MSG_AUTH_FAIL, {"reason": "Invalid or expired token"})
                )
                await ws.close(code=4002, reason="Invalid token")
                return

        # For master key, use a per-node hash (key + node hostname) so each
        # node gets its own DB entry even though they share the same key
        if is_master_key:
            node_hostname = node_info.get("hostname", "unknown")
            token_hash = federation.hash_token(f"{token}:{node_hostname}")
        else:
            # For join tokens: hash includes node hostname so the same
            # reusable token creates separate DB entries per node
            node_hostname = node_info.get("hostname", "unknown")
            token_hash = federation.hash_token(f"{token}:{node_hostname}")

        # Look up or register the node
        node = await database.get_node_by_token_hash(token_hash)

        if node:
            node_id = node["id"]
            await database.update_node_heartbeat(
                node_id,
                ip=node_info.get("ip", ""),
                os_info=node_info.get("os", ""),
                arch=node_info.get("arch", ""),
                docker_version=node_info.get("docker_version", ""),
                docker_mode=node_info.get("docker_mode", "unknown"),
            )
        else:
            default_name = payload.get("n", "") if payload else ""
            node_id = await database.register_node(
                name=node_info.get("name", default_name or "unnamed"),
                token_hash=token_hash,
                ip=node_info.get("ip", ""),
                os_info=node_info.get("os", ""),
                arch=node_info.get("arch", ""),
                docker_version=node_info.get("docker_version", ""),
                docker_mode=node_info.get("docker_mode", "unknown"),
            )

        _connections[node_id] = ws
        logger.info("Child node %d connected (name=%s)", node_id, node_info.get("name", "?"))

        await ws.send_text(federation.make_message(federation.MSG_AUTH_OK, {"node_id": node_id}))

        # Main message loop
        while True:
            raw = await ws.receive_text()
            msg = federation.parse_message(raw)
            if not msg:
                continue

            if msg["type"] == federation.MSG_HEARTBEAT:
                await _handle_heartbeat(node_id, msg.get("data", {}))
            elif msg["type"] == federation.MSG_EARNINGS:
                await _handle_earnings(node_id, msg.get("data", {}))
            else:
                logger.debug("Unknown message type from node %d: %s", node_id, msg["type"])

    except WebSocketDisconnect:
        logger.info("Child node %s disconnected", node_id or "unknown")
    except Exception as exc:
        logger.error("WebSocket error for node %s: %s", node_id or "unknown", exc)
    finally:
        if node_id is not None:
            _connections.pop(node_id, None)
            _node_states.pop(node_id, None)
            await database.set_node_status(node_id, "offline")


async def _handle_heartbeat(node_id: int, data: dict[str, Any]) -> None:
    """Process a heartbeat from a child node."""
    _node_states[node_id] = data
    await database.update_node_heartbeat(
        node_id,
        ip=data.get("ip", ""),
        os_info=data.get("os", ""),
        arch=data.get("arch", ""),
        docker_version=data.get("docker_version", ""),
        docker_mode=data.get("docker_mode", "unknown"),
    )


async def _handle_earnings(node_id: int, data: dict[str, Any]) -> None:
    """Process earnings data from a child node."""
    for entry in data.get("earnings", []):
        await database.upsert_earnings(
            platform=entry.get("platform", "unknown"),
            balance=entry.get("balance", 0.0),
            currency=entry.get("currency", "USD"),
            date=entry.get("date"),
        )


async def send_command(node_id: int, command: str, payload: dict[str, Any] | None = None) -> bool:
    """Send a command to a connected child node. Returns True if sent."""
    ws = _connections.get(node_id)
    if not ws:
        return False
    try:
        await ws.send_text(federation.make_message(federation.MSG_COMMAND, {"command": command, **(payload or {})}))
        return True
    except Exception as exc:
        logger.error("Failed to send command to node %d: %s", node_id, exc)
        return False
