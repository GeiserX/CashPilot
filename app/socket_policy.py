"""The Docker socket proxy's policy, built from the catalog.

The worker reaches Docker through a pinned sockguard container (see
docs/security-defaults.md). The policy sits inline in each shipped compose
file; scripts/socket_proxy_policy.py writes it there from this module. The
worker imports the same module, so it can tell when the policy the proxy
loaded is older than the image it runs (``digest`` against the
CASHPILOT_PROXY_POLICY value the compose file gives it), and refuse a runtime
the proxy would refuse before a running container is touched.

The policy stays in the operator's compose file, never in the image: the image
is what the policy restricts, so an image update must not be able to widen it.
An operator who keeps their own compose file brings the policy up to date with
this image, without giving the image any access to that file:

    docker run --rm -i --network none drumsergio/cashpilot-worker:<version> \
        python -m app.socket_policy < docker-compose.yml > docker-compose.new.yml

It replaces the block between the policy markers and the fingerprints, adds
the proxy's fingerprint to a file from before the proxy carried one, changes
nothing else, and the operator reads the diff before using the new file.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

from app.constants import LABEL_DEPLOYED_BY

SERVICES_DIR = Path(__file__).resolve().parent.parent / "services"

#: Exec commands the worker runs that the catalog does not declare.
FIXED_COMMANDS: list[list[str]] = [
    # The tunnel sidecar's readiness file (app/proxy_tunnel.py).
    ["cat", "/run/ready"],
]

#: What a created container may ask for. The worker's own ceilings
#: (app/worker_api.py) are at least this strict.
ALLOWED_CAPABILITIES = ("NET_ADMIN", "NET_RAW", "SETUID", "SETGID")
ALLOWED_DEVICES = ("/dev/net/tun",)
#: Docker's default runtime and the gVisor ones docs/security-defaults.md names.
ALLOWED_RUNTIMES = ("runc", "runsc", "runsc-hostnet", "runsc-hostnet-raw")

#: Owner isolation: the proxy stamps this label on everything the worker
#: creates and refuses it every container, volume and network without it, so a
#: compromised worker cannot read the UI's files, environment or data volume.
#: app/owner_migrate.py puts it on what older releases created.
OWNER_LABEL = LABEL_DEPLOYED_BY
OWNER = "worker"

#: (method, path) of every Docker API call the worker, its update helper and
#: the helper's Compose make, as the live test (scripts/socket_proxy_live_test.sh)
#: recorded them from the proxy's access log. Anything else is refused.
ALLOWED_CALLS: list[tuple[str, str]] = [
    ("GET", "/_ping"),
    ("HEAD", "/_ping"),
    ("GET", "/version"),
    ("GET", "/info"),
    ("GET", "/containers/json"),
    ("GET", "/containers/*/json"),
    ("POST", "/containers/create"),
    ("POST", "/containers/*/start"),
    ("POST", "/containers/*/stop"),
    ("POST", "/containers/*/restart"),
    ("POST", "/containers/*/pause"),
    ("POST", "/containers/*/unpause"),
    ("POST", "/containers/*/wait"),
    # Compose renames the old container while it recreates one.
    ("POST", "/containers/*/rename"),
    ("DELETE", "/containers/*"),
    ("GET", "/containers/*/logs"),
    ("GET", "/containers/*/stats"),
    ("GET", "/containers/*/archive"),
    # The tunnel sidecar's proxy settings; container_archive below limits where.
    ("PUT", "/containers/*/archive"),
    ("POST", "/containers/*/exec"),
    ("POST", "/exec/*/start"),
    ("GET", "/exec/*/json"),
    ("GET", "/images/**/json"),
    ("POST", "/images/create"),
    ("GET", "/networks"),
    ("GET", "/networks/*"),
    # The LAN fence (app/lan_fence.py) creates cashpilot-isolated, moves
    # earners onto it and recreates it after a prune. sockguard 2.4.6 cannot
    # limit these by network name, so they are allowed for any network.
    ("POST", "/networks/create"),
    ("POST", "/networks/*/connect"),
    ("POST", "/networks/*/disconnect"),
    ("DELETE", "/networks/*"),
    # Under owner isolation a volume a container names must exist and carry
    # the owner label, so the worker creates each one before the container.
    ("POST", "/volumes/create"),
    ("GET", "/volumes/*"),
    ("DELETE", "/volumes/*"),
]
DENY_REASON = "the CashPilot worker does not use this Docker API call"

TEMPLATE = """\
listen:
  socket: /run/cashpilot-docker/docker.sock
  # The worker runs as uid/gid 1000 (Dockerfile.worker). The proxy runs as
  # root with no capabilities and joins group 1000, so it can hand the socket
  # to that group without asking for the host's docker group id.
  socket_mode: "0660"
  socket_gid: 1000
upstream:
  socket: /var/run/docker.sock
  # Image pulls and container waits take minutes; the default cuts them at 60 s.
  request_timeout: "off"
log:
  level: info
  format: json
  # One line per call, refusals included: docker logs cashpilot-socket-proxy
  # shows what was refused and why. The compose file caps the log's size.
  access_log: true
health:
  enabled: false
# The worker reads its own containers' logs and files (backups, the update check).
insecure_allow_read_exfiltration: true
response:
  # A refusal carries the rule's reason, which the worker shows to you.
  deny_verbosity: verbose
  # The worker reads Env, Mounts and IPAM back (recreates, the isolation check).
  redact_container_env: false
  redact_mount_paths: false
  redact_network_topology: false
request_body:
  container_create:
    allow_privileged: false
    # The LAN fence helper and the isolation check's control probe run on the
    # host network; no earner does (the worker refuses it for every catalog
    # service, and the catalog refuses it to any service with NET_ADMIN).
    allow_host_network: true
    allow_host_pid: false
    allow_host_ipc: false
    allow_host_userns: false
    allow_host_cgroupns: false
    allowed_capabilities: [{capabilities}]
    allowed_devices: [{devices}]
    allowed_runtimes: [{runtimes}]
    allow_sysctls: true               # the tunnel sidecar turns IPv6 off in its own namespace
    require_no_new_privileges: true
    deny_unconfined_seccomp: true
    deny_unconfined_apparmor: true
    deny_unconfined_system_paths: true
    # Host folders containers may bind come from CASHPILOT_COMPOSE_DIR and
    # CASHPILOT_PROXY_BIND_MOUNTS, through the proxy service's environment.
    allowed_bind_mounts: []
  container_remove:
    allow_force: true
    allow_remove_volumes: true
  container_archive:
    # The only folder the worker writes into a container: the tunnel
    # sidecar's proxy settings.
    allowed_paths: [/run/cashpilot-secret]
    allow_setid: false
    allow_device_nodes: false
    allow_escaping_links: false
  exec:
    allow_privileged: false
    allow_root_user: true
    # The worker's exec calls send no environment. This name is never sent,
    # so any Env entry (PATH, LD_PRELOAD) is refused.
    allowed_env_vars: [CASHPILOT_EXEC_SENDS_NO_ENV]
    allowed_commands:
{commands}
  image_pull:
    allow_all_registries: true        # catalog and custom services come from many registries
  network:
    # The LAN fence (app/lan_fence.py) creates its bridge with three driver
    # options (interface name, no masquerade, no inter-container traffic) and
    # moves an earner across with a forced disconnect. Custom drivers, swarm
    # scope, custom IPAM and endpoint settings stay refused.
    allow_driver_options: true
    allow_disconnect_force: true
  volume:
    # Plain local volumes only: driver options could point one at a host folder.
    allow_custom_drivers: false
    allow_driver_opts: false
# The worker sees and touches only what carries the owner label below: what
# it created through this proxy, and what app/owner_migrate.py labelled. The
# UI's container and its data volume never carry it.
ownership:
  owner: {owner}
  label_key: {owner_label}
  # Images carry no owner: one pulled for an earner is shared with the host.
  allow_unowned_images: true
  allow_cross_owner_namespace_sharing: false
rules:
{rules}
"""


def catalog_commands(services_dir: Path = SERVICES_DIR) -> list[list[str]]:
    """Every exec argv the worker can run, in a stable order without repeats."""
    # Imported here: app.isolation_check imports the orchestrator, which imports this.
    from app.isolation_check import CHAIN_READ

    found: list[list[str]] = list(FIXED_COMMANDS)
    for path in sorted(services_dir.rglob("*.yml")):
        if path.name.startswith("_"):
            continue
        svc = yaml.safe_load(path.read_text()) or {}
        collector = svc.get("collector") or {}
        payout = svc.get("payout") or {}
        for reader in (collector.get("node_read"), payout.get("address_read"), svc.get("node_read")):
            if isinstance(reader, dict) and isinstance(reader.get("command"), list):
                found.append([str(a) for a in reader["command"]])
        firewall = (svc.get("docker") or {}).get("node_firewall")
        if isinstance(firewall, dict) and firewall.get("chain"):
            found.append(["sh", "-c", CHAIN_READ.format(chain=firewall["chain"])])
    unique: list[list[str]] = []
    for argv in found:
        if argv not in unique:
            unique.append(argv)
    return unique


def policy(services_dir: Path = SERVICES_DIR) -> str:
    """The policy as sockguard reads it."""
    commands = "\n".join(f"      - {json.dumps(argv)}" for argv in catalog_commands(services_dir))
    rules = "\n".join(
        [f'  - {{match: {{method: {m}, path: "{p}"}}, action: allow}}' for m, p in ALLOWED_CALLS]
        + [f'  - {{match: {{method: "*", path: "/**"}}, action: deny, reason: "{DENY_REASON}"}}']
    )
    return TEMPLATE.format(
        capabilities=", ".join(ALLOWED_CAPABILITIES),
        devices=", ".join(ALLOWED_DEVICES),
        runtimes=", ".join(ALLOWED_RUNTIMES),
        commands=commands,
        owner=OWNER,
        owner_label=OWNER_LABEL,
        rules=rules,
    )


def digest(services_dir: Path = SERVICES_DIR) -> str:
    """A short fingerprint of the policy, carried next to it in each compose file."""
    return hashlib.sha256(policy(services_dir).encode()).hexdigest()[:16]


BEGIN = "      # BEGIN socket proxy policy: written by scripts/socket_proxy_policy.py, do not edit by hand\n"
END = "      # END socket proxy policy\n"
#: The worker's copy of the policy's fingerprint, so it can tell when its image
#: is newer than the policy the proxy loaded.
DIGEST_RE = re.compile(r"(CASHPILOT_PROXY_POLICY=)[0-9a-f]*")


def compose_block(services_dir: Path = SERVICES_DIR, passes: int = 1) -> str:
    """The policy as it sits in a compose file: indented, each `$` doubled once
    per interpolation pass the file goes through (`$$` for plain Compose)."""
    body = "".join(f"      {line}\n" if line else "\n" for line in policy(services_dir).splitlines())
    return BEGIN + body.replace("$", "$" * 2**passes) + END


def render(text: str, block: str, fingerprint: str) -> str:
    """A compose file with its policy block and fingerprint replaced, nothing else."""
    start, end = text.find(BEGIN), text.find(END)
    if start < 0 or end < start:
        raise SystemExit("compose file has no socket proxy policy markers")
    if not DIGEST_RE.search(text):
        raise SystemExit("compose file gives the worker no CASHPILOT_PROXY_POLICY")
    text = text[:start] + block + text[end + len(END) :]
    return DIGEST_RE.sub(lambda m: m.group(1) + fingerprint, text)


#: Every shipped compose file since the proxy carries this line in the proxy's
#: environment; the proxy's fingerprint goes right after it.
_PROXY_ENV_ANCHOR = re.compile(r"^( *)- SOCKGUARD_REQUEST_BODY_CONTAINER_CREATE_ALLOWED_BIND_MOUNTS=.*\n", re.M)
_PROXY_FINGERPRINT = (
    "{indent}# The policy's fingerprint. Compose does not recreate a container when\n"
    "{indent}# only its config's content changes, so this line is what makes\n"
    "{indent}# `docker compose up -d` restart the proxy on a new policy.\n"
    "{indent}- CASHPILOT_PROXY_POLICY=0\n"
)


def update(text: str, passes: int | None = None) -> str:
    """An operator's compose file brought to this image's policy.

    Besides the block and the fingerprints, a file from before the proxy
    carried its own fingerprint gets that line, or every later policy change
    would leave the proxy on the old one. A file whose block went through two
    interpolation passes (CasaOS writes `$$$$`) keeps two. A block with no `$`
    in it says nothing, so ``passes`` overrides the guess.
    """
    if passes is None:
        start, end = text.find(BEGIN), text.find(END)
        passes = 2 if start >= 0 and "$$$$" in text[start:end] else 1
    if len(DIGEST_RE.findall(text)) == 1:
        anchor = _PROXY_ENV_ANCHOR.search(text)
        if anchor is None:
            raise SystemExit("compose file has no socket proxy environment to give the policy's fingerprint")
        line = _PROXY_FINGERPRINT.format(indent=anchor.group(1))
        text = text[: anchor.end()] + line + text[anchor.end() :]
    return render(text, compose_block(passes=passes), digest())


def main(argv: list[str] | None = None) -> int:
    """Read a compose file on stdin, write it with this image's policy on stdout.

    ``--passes N`` sets how many times the file is interpolated before the
    proxy reads it (1 for Compose, 2 for a CasaOS store template)."""
    args = sys.argv[1:] if argv is None else argv
    passes = None
    if args:
        if len(args) != 2 or args[0] != "--passes" or args[1] not in ("1", "2"):
            print("usage: python -m app.socket_policy [--passes 1|2] < compose.yml", file=sys.stderr)
            return 2
        passes = int(args[1])
    try:
        sys.stdout.write(update(sys.stdin.read(), passes))
    except SystemExit as exc:
        print(f"{exc}; take the compose file of this release instead", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
