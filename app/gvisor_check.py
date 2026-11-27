"""Does gVisor really protect the earners on this host? A red/green self-test.

The owner installs gVisor with one command on the host (scripts/cashpilot-gvisor),
because that needs root and the worker has none. The worker cannot see what the
command did, only what Docker reports afterwards, and a runtime's name proves
nothing: a ``runsc-hostnet`` entry can point at runc. So this starts one short
probe container per gVisor runtime the earners would use, on the network they
are on, and checks two things from inside it:

* **gVisor's kernel.** The probe reads its kernel release and /proc/version.
  gVisor answers with its own (``4.19.0-gvisor``, measured on release
  20261123.1), never the host's. The worker runs under runc, so its own
  release is the host's, unless it runs under gVisor itself (Docker's default
  runtime inside a Secure VM), so only gVisor's own answer counts.
* **DNS on the earners' network.** Plain runsc cannot resolve names on a
  user-defined bridge (gVisor issue 7469), which is why the install registers
  the ``--network=host`` passthrough. The probe resolves a public name.

Green needs both, for every runtime checked. No gVisor runtime at all is
"not installed", which the UI shows as such, never as a failure of the earners.
The probes run from the worker's own image with no capabilities, as nobody, on
a read-only root, and are removed on every path, as in app/isolation_check.py.
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
from datetime import UTC, datetime
from typing import Any

import docker
from docker.errors import DockerException, NotFound

from app import activity, lan_fence, layers, orchestrator, socket_policy

logger = logging.getLogger(__name__)

PROBE_PREFIX = "cashpilot-gvisor-probe-"
PROBE_LABEL = lan_fence.PROBE_LABEL
PROBE_TIMEOUT = 60
DOCKER_TIMEOUT = 30
#: A public name whose lookup must work from the earners' network.
DNS_NAME = "cloudflare.com"

_lock = threading.Lock()

PROBE_SCRIPT = r"""
import json, platform, socket, sys
out = {"release": platform.release()}
try:
    with open("/proc/version") as fh:
        out["version"] = fh.read().strip()
except OSError as exc:
    out["version_error"] = str(exc)
try:
    socket.setdefaulttimeout(10)
    out["dns"] = sorted({a[4][0] for a in socket.getaddrinfo(sys.argv[1], 443, proto=socket.IPPROTO_TCP)})[:4]
except Exception as exc:
    out["dns_error"] = f"{type(exc).__name__}: {exc}"
print(json.dumps(out))
"""


class CheckBusy(Exception):
    pass


def judge(probe: dict[str, Any]) -> dict[str, Any]:
    """Whether one probe saw gVisor's kernel and could resolve names, with the reason for each."""
    release = str(probe.get("release") or "")
    seen = f"{release} {probe.get('version') or ''}".lower()
    # Not "differs from the worker's own release": inside a Secure VM the
    # worker itself may run under gVisor, as Docker's default runtime there.
    kernel = "gvisor" in seen
    if kernel:
        kernel_why = f"gVisor's kernel answered ({release})"
    elif release:
        kernel_why = f"the probe ran on a real Linux kernel ({release}), so this runtime is not gVisor"
    else:
        kernel_why = "the probe saw no sign of gVisor's kernel"
    dns = bool(probe.get("dns"))
    dns_why = (
        f"{DNS_NAME} resolved"
        if dns
        else f"{DNS_NAME} did not resolve ({probe.get('dns_error') or 'no answer'}); "
        "gVisor needs the --network=host passthrough for Docker's DNS on this network"
    )
    return {"kernel": kernel, "kernel_why": kernel_why, "dns": dns, "dns_why": dns_why}


def _client() -> Any:
    try:
        client = docker.from_env(timeout=DOCKER_TIMEOUT)
        client.ping()
    except Exception as exc:
        raise RuntimeError(f"Docker socket not available: {exc}") from exc
    return client


def probe_name() -> str:
    """This worker's probe name. Two workers on one Docker daemon each remove only their own."""
    return f"{PROBE_PREFIX}{activity._worker_tag()}"


def _remove(client: Any, leftovers: list[str]) -> None:
    name = probe_name()
    try:
        client.containers.get(name).remove(force=True, v=True)
    except NotFound:
        pass
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        logger.warning("Could not remove the gVisor probe: %s", exc)
        leftovers.append(name)


def _probe(
    client: Any, image: str, runtime: str, network: str, leftovers: list[str], dns: list[str] | None = None
) -> dict[str, Any]:
    _remove(client, [])
    try:
        container = client.containers.run(
            image=image,
            name=probe_name(),
            entrypoint=["python", "-c", PROBE_SCRIPT],
            command=[DNS_NAME],
            runtime=runtime,
            network=network or None,
            # The resolvers an earner on this network gets (orchestrator.container_dns).
            dns=dns,
            user="65534:65534",
            read_only=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            privileged=False,
            pids_limit=64,
            mem_limit="128m",
            healthcheck={"test": ["NONE"]},
            labels={PROBE_LABEL: "gvisor-check", activity.WORKER_LABEL: activity.WORKER_ID},
            detach=True,
        )
        status = container.wait(timeout=PROBE_TIMEOUT)
        logs = container.logs(stdout=True, stderr=False)
        if (status or {}).get("StatusCode") != 0:
            return {"error": f"the probe exited with status {(status or {}).get('StatusCode')}"}
        return json.loads(logs)
    except (DockerException, ValueError) as exc:
        # Docker's own answer can name paths; the runtime and a short reason are enough.
        logger.warning("gVisor probe under %s failed: %s", runtime, exc)
        return {"error": f"Docker could not run the probe under {runtime}: {str(exc)[:200]}"}
    finally:
        _remove(client, leftovers)


def run() -> dict[str, Any]:
    """Run the self-test. Raises CheckBusy when one runs already, RuntimeError without Docker."""
    if not _lock.acquire(blocking=False):
        raise CheckBusy("A gVisor check is already running on this worker.")
    try:
        client = _client()
        try:
            result = _run(client)
        finally:
            with contextlib.suppress(Exception):
                client.close()
        layers.set_last_check(result)
        return result
    finally:
        _lock.release()


def _run(client: Any) -> dict[str, Any]:
    facts = layers.daemon_runtimes(fresh=True)
    if facts is None:
        # Not "not installed": Docker did not say which runtimes it has.
        raise RuntimeError("Docker did not report its runtimes.")
    allowed = socket_policy.ALLOWED_RUNTIMES if orchestrator.proxied() else None
    gvisor = [f for f in facts if f["gvisor"]]
    # The runtimes an earner would get (layers.pick): the passthrough ones the proxy accepts.
    targets = [f["name"] for f in gvisor if f["hostnet"] and (allowed is None or f["name"] in allowed)]
    _mode, network = lan_fence.effective_network(client)
    checked_at = datetime.now(UTC).isoformat(timespec="seconds")
    base: dict[str, Any] = {"checked_at": checked_at, "network": network or "bridge", "runtimes": []}
    if not targets:
        why = (
            "Docker has gVisor registered, but not with --network=host, which Docker's DNS needs on this network."
            if gvisor
            else "Docker on this host has no gVisor runtime registered."
        )
        return {**base, "state": "not_installed", "message": why}
    image = orchestrator._self_container(client)
    image = ((image.attrs or {}).get("Image") or None) if image is not None else None
    if not image:
        return {**base, "state": "red", "message": "The worker could not find its own image to run the probe from."}
    try:
        dns = orchestrator.container_dns(network or None)
    except orchestrator.ContainerNetworkError:
        # The deploys refuse the same setting, so no earner runs with it either.
        return {
            **base,
            "state": "red",
            "message": "CASHPILOT_CONTAINER_DNS is not a list of IP addresses, so no earner can start on this network.",
        }
    leftovers: list[str] = []
    for name in targets:
        probe = _probe(client, image, name, network, leftovers, dns)
        if "error" in probe:
            base["runtimes"].append({"name": name, "kernel": False, "dns": False, "error": probe["error"]})
            continue
        base["runtimes"].append({"name": name, **judge(probe)})
    green = all(r["kernel"] and r["dns"] for r in base["runtimes"])
    base["state"] = "green" if green else "red"
    base["message"] = (
        "Every earner that runs under gVisor here gets gVisor's kernel, and its name lookups work."
        if green
        else "gVisor is not protecting the earners correctly on this host; see each runtime below."
    )
    if leftovers:
        base["leftovers"] = leftovers
    return base
