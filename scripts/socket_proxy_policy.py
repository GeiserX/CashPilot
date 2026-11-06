#!/usr/bin/env python3
"""Write the Docker socket proxy's policy into every shipped compose file.

The worker reaches Docker through a pinned sockguard container (see
docs/security-defaults.md). Its policy lives inline in each compose file, so
the policy travels with the file that pins the CashPilot release. This script
is the one place the policy is written: app/socket_policy.py builds it from its
template plus the exec commands the catalog declares (every ``node_read`` and
``address_read``, and the isolation check's chain read for every
``node_firewall``), and this writes the same block into each compose file, with
its fingerprint in the worker's CASHPILOT_PROXY_POLICY.

    python scripts/socket_proxy_policy.py          # rewrite the compose files
    python scripts/socket_proxy_policy.py --check  # exit 1 if any is stale

A catalog change that adds a reader without running this fails
tests/test_socket_proxy.py: the proxy would refuse that reader.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import socket_policy  # noqa: E402
from app.socket_policy import ALLOWED_CALLS, catalog_commands, policy  # noqa: E402,F401

COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.fleet.yml",
    "docker-compose.build.yml",
    "docker-compose.worker.yml",
    # The Runtipi package installs the same proxy, so it carries the same policy.
    "contrib/app-stores/runtipi/cashpilot/docker-compose.yml",
)
#: Files whose installer interpolates them twice. CasaOS resolves variables
#: when it imports a compose file, writes the result out, and Compose then
#: resolves that file again, so each `$` must be written `$$$$` to reach the
#: proxy as `$`. tests/test_app_store_templates.py checks the rest of the file.
TWICE_INTERPOLATED = ("contrib/app-stores/casaos/CashPilot/docker-compose.yml",)
BEGIN = "      # BEGIN socket proxy policy: written by scripts/socket_proxy_policy.py, do not edit by hand\n"
END = "      # END socket proxy policy\n"
#: The worker's copy of the policy's fingerprint, so it can tell when its image
#: is newer than the policy the proxy loaded (app/socket_policy.py).
DIGEST_RE = re.compile(r"(CASHPILOT_PROXY_POLICY=)[0-9a-f]*")


def compose_block(services_dir: Path = socket_policy.SERVICES_DIR, passes: int = 1) -> str:
    """The policy as it sits in a compose file: indented, each `$` doubled once
    per interpolation pass the file goes through (`$$` for plain Compose)."""
    body = "".join(f"      {line}\n" if line else "\n" for line in policy(services_dir).splitlines())
    return BEGIN + body.replace("$", "$" * 2**passes) + END


def render(text: str, block: str, fingerprint: str) -> str:
    start, end = text.find(BEGIN), text.find(END)
    if start < 0 or end < start:
        raise SystemExit("compose file has no socket proxy policy markers")
    if not DIGEST_RE.search(text):
        raise SystemExit("compose file gives the worker no CASHPILOT_PROXY_POLICY")
    text = text[:start] + block + text[end + len(END) :]
    return DIGEST_RE.sub(lambda m: m.group(1) + fingerprint, text)


def main(argv: list[str]) -> int:
    check = "--check" in argv
    blocks = {1: compose_block(), 2: compose_block(passes=2)}
    fingerprint = socket_policy.digest()
    stale = []
    for name in (*COMPOSE_FILES, *TWICE_INTERPOLATED):
        path = ROOT / name
        text = path.read_text()
        new = render(text, blocks[2 if name in TWICE_INTERPOLATED else 1], fingerprint)
        if new != text:
            stale.append(name)
            if not check:
                path.write_text(new)
    if check and stale:
        print(f"Stale socket proxy policy in {', '.join(stale)}; run python scripts/socket_proxy_policy.py")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
