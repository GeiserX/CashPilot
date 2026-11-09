"""Drives the worker's own proxied-copy code against a real Docker daemon.

Called by scripts/proxy_shared_tunnel_lab.sh, never by the worker. It imports
app/proxy_tunnel.py from CASHPILOT_SRC (default: this checkout), so the same
lab runs against the code under review and against the base branch, and
deploys copies of a stand-in earner through a Tailscale proxy on a throwaway
headscale tailnet.

    python scripts/proxy_shared_tunnel_lab.py deploy <n>     # n copies through proxy LAB_PROXY_ID
    python scripts/proxy_shared_tunnel_lab.py migrate         # proxy_tunnel.migrate_legacy()
    python scripts/proxy_shared_tunnel_lab.py heartbeat       # one proxy_tunnel.status() pass
    python scripts/proxy_shared_tunnel_lab.py stop <slug>     # proxy_tunnel.stop(slug, LAB_PROXY_ID)

Environment: LAB_AUTH_KEY, LAB_EXIT_NODE, LAB_LOGIN_SERVER, LAB_PROXY_ID,
LAB_EARNER_IMAGE, CASHPILOT_TUNNEL_IMAGE, CASHPILOT_CONTAINER_NETWORK,
CASHPILOT_DATA_DIR, DOCKER_HOST.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.environ.get("CASHPILOT_SRC") or os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("CASHPILOT_API_KEY", "lab")

from app import proxy_tunnel  # noqa: E402

PROXY_ID = int(os.environ.get("LAB_PROXY_ID", "3"))
PROXY = {
    "kind": "tailscale",
    "auth_key": os.environ.get("LAB_AUTH_KEY", ""),
    "exit_node": os.environ.get("LAB_EXIT_NODE", ""),
    "login_server": os.environ.get("LAB_LOGIN_SERVER", ""),
}
EARNER = os.environ.get("LAB_EARNER_IMAGE", "")


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "deploy":
        for i in range(int(argv[2])):
            slug = f"labearner{i}"
            out = proxy_tunnel.deploy(slug, PROXY_ID, {"image": EARNER, "command": ["sleep", "infinity"]}, PROXY, None)
            print(json.dumps({"slug": slug, "tunnel": out["tunnel_id"][:12], "exit": out["exit"]}))
        return 0
    if cmd == "migrate":
        print(json.dumps(proxy_tunnel.migrate_legacy()))
        return 0
    if cmd == "heartbeat":
        for entry in proxy_tunnel.status(collect_stats=False):
            print(json.dumps({k: entry.get(k) for k in ("name", "status", "tunnel_status", "exit_ip")}))
        return 0
    if cmd == "stop":
        print(json.dumps({"was_running": proxy_tunnel.stop(argv[2], PROXY_ID)}))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
