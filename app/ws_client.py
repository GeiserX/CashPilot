"""WebSocket federation client (child node).

Connects to the master node, authenticates with a join token,
sends periodic heartbeats, and executes commands from the master.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed, InvalidURI

from app import database, federation, orchestrator

logger = logging.getLogger(__name__)

# State
_running = False
_task: asyncio.Task | None = None
_node_id: int | None = None

MAX_BACKOFF = 300  # 5 minutes


async def start() -> None:
    """Start the federation client background task."""
    global _task, _running
    if not federation.MASTER_URL or not federation.JOIN_TOKEN:
        logger.warning("Federation child mode requires CASHPILOT_MASTER_URL and CASHPILOT_JOIN_TOKEN")
        return
    _running = True
    _task = asyncio.create_task(_connect_loop())
    logger.info("Federation client started (master=%s)", federation.MASTER_URL)


async def stop() -> None:
    """Stop the federation client."""
    global _running, _task
    _running = False
    if _task and not _task.done():
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
    _task = None
    logger.info("Federation client stopped")


async def _connect_loop() -> None:
    """Connect to master with exponential backoff on failure."""
    backoff = 1
    while _running:
        try:
            await _run_session()
            backoff = 1  # Reset on clean disconnect
        except (ConnectionClosed, OSError, InvalidURI) as exc:
            logger.warning("Master connection lost: %s (retry in %ds)", exc, backoff)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.error("Unexpected federation error: %s (retry in %ds)", exc, backoff)

        if not _running:
            return
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, MAX_BACKOFF)


async def _run_session() -> None:
    """Run a single WebSocket session with the master."""
    global _node_id

    url = federation.MASTER_URL
    if not url.endswith("/ws/federation"):
        url = url.rstrip("/") + "/ws/federation"

    logger.info("Connecting to master at %s", url)
    async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
        # Authenticate
        node_info = federation.get_node_info()
        node_info["docker_mode"] = "direct" if orchestrator.docker_available() else "monitor-only"
        try:
            node_info["docker_version"] = _get_docker_version()
        except Exception:
            node_info["docker_version"] = ""

        await ws.send(
            federation.make_message(
                federation.MSG_AUTH,
                {
                    "token": federation.JOIN_TOKEN,
                    "node_info": node_info,
                },
            )
        )

        # Wait for auth response
        raw = await ws.recv()
        msg = federation.parse_message(raw)
        if not msg:
            logger.error("Invalid auth response from master")
            return

        if msg["type"] == federation.MSG_AUTH_FAIL:
            reason = msg.get("data", {}).get("reason", "Unknown")
            logger.error("Master rejected auth: %s", reason)
            # Don't retry with same token — backoff will be long
            await asyncio.sleep(60)
            return

        if msg["type"] == federation.MSG_AUTH_OK:
            _node_id = msg.get("data", {}).get("node_id")
            logger.info("Authenticated with master (node_id=%s)", _node_id)

        # Start heartbeat and command listener in parallel
        await asyncio.gather(
            _heartbeat_loop(ws),
            _command_listener(ws),
        )


async def _heartbeat_loop(ws) -> None:
    """Send periodic heartbeats to master."""
    while _running:
        try:
            data = await _collect_heartbeat_data()
            await ws.send(federation.make_message(federation.MSG_HEARTBEAT, data))
        except ConnectionClosed:
            return
        except Exception as exc:
            logger.error("Heartbeat send error: %s", exc)
        await asyncio.sleep(federation.HEARTBEAT_INTERVAL)


async def _command_listener(ws) -> None:
    """Listen for commands from master and execute them."""
    try:
        async for raw in ws:
            msg = federation.parse_message(raw)
            if not msg or msg["type"] != federation.MSG_COMMAND:
                continue

            cmd_data = msg.get("data", {})
            command = cmd_data.get("command", "")
            slug = cmd_data.get("slug", "")

            logger.info("Received command from master: %s %s", command, slug)

            try:
                result = await _execute_command(command, cmd_data)
                await ws.send(
                    federation.make_message(
                        federation.MSG_ACK,
                        {
                            "command": command,
                            "slug": slug,
                            "status": "ok",
                            "result": result,
                        },
                    )
                )
            except Exception as exc:
                await ws.send(
                    federation.make_message(
                        federation.MSG_ACK,
                        {
                            "command": command,
                            "slug": slug,
                            "status": "error",
                            "error": str(exc),
                        },
                    )
                )
    except ConnectionClosed:
        return


async def _execute_command(command: str, data: dict[str, Any]) -> str:
    """Execute a command from the master node."""
    slug = data.get("slug", "")

    if command == "deploy":
        env = data.get("env", {})
        container_id = orchestrator.deploy_service(slug, env_vars=env)
        await database.save_deployment(slug=slug, container_id=container_id)
        return f"Deployed {slug}: {container_id[:12]}"

    elif command == "stop":
        orchestrator.stop_service(slug)
        return f"Stopped {slug}"

    elif command == "restart":
        orchestrator.restart_service(slug)
        return f"Restarted {slug}"

    elif command == "remove":
        orchestrator.remove_service(slug)
        await database.remove_deployment(slug)
        return f"Removed {slug}"

    elif command == "status":
        status = orchestrator.get_status()
        return str(status)

    else:
        raise ValueError(f"Unknown command: {command}")


async def _collect_heartbeat_data() -> dict[str, Any]:
    """Gather local system and container status for heartbeat."""
    node_info = federation.get_node_info()
    node_info["docker_mode"] = "direct" if orchestrator.docker_available() else "monitor-only"

    # Container status
    containers = []
    with contextlib.suppress(Exception):
        containers = orchestrator.get_status()

    # Earnings summary
    earnings = []
    with contextlib.suppress(Exception):
        earnings = await database.get_earnings_summary()

    return {
        **node_info,
        "containers": containers,
        "earnings": earnings,
        "container_count": len(containers),
        "running_count": sum(1 for c in containers if c.get("status") == "running"),
    }


def _get_docker_version() -> str:
    """Get Docker version string."""
    try:
        import docker

        client = docker.from_env()
        version = client.version().get("Version", "")
        client.close()
        return version
    except Exception:
        return ""
