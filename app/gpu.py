"""The GPU grant: which container gets a GPU, and how it is passed in.

A catalog entry declares the GPU it needs in ``docker.gpu``:

    docker:
      runtime: runc
      gpu:
        vendor: nvidia     # nvidia | amd | intel
        count: 1           # 1 (default) | "all"
        rocm: false        # amd only: also pass /dev/kfd

The worker reads that from its own catalog, never from a deploy request, so a
request cannot ask for a GPU, a custom service (``custom-`` slug, never in the
catalog) never gets one, and a proxied copy is refused one.

- NVIDIA goes in as a Docker device request (driver ``nvidia``, capability
  ``gpu``). The NVIDIA Container Toolkit on the host does the rest.
- AMD and Intel go in as DRM render nodes of that vendor only, inside
  ``RENDER_NODE_CEILING``. Never a ``card*`` node: those are the display
  control nodes. ROCm also gets ``/dev/kfd``.

Every container WITHOUT an NVIDIA grant gets ``NVIDIA_VISIBLE_DEVICES=void``.
CUDA base images set that variable to ``all``, so on a host whose default
runtime is ``nvidia`` such an image would otherwise get every GPU with no
grant at all. A container's own env wins over its image's.

Pure on purpose: no orchestrator or docker import at module level, so the UI
image (no Docker SDK) and app/socket_policy.py can import it.
"""

from __future__ import annotations

import platform
from pathlib import Path
from typing import Any

#: PCI vendor ids as sysfs writes them.
VENDOR_IDS = {"nvidia": "0x10de", "amd": "0x1002", "intel": "0x8086"}
VENDOR_NAMES = {"nvidia": "NVIDIA", "amd": "AMD", "intel": "Intel"}
VENDORS = tuple(VENDOR_IDS)

#: The render nodes a container may ever get. Exact paths, never /dev/dri as a
#: prefix: that would also open card*, the display control nodes.
RENDER_NODE_CEILING = tuple(f"/dev/dri/renderD{n}" for n in range(128, 136))
#: AMD's compute interface, for ROCm.
KFD = "/dev/kfd"

#: What a container without an NVIDIA grant gets, so a CUDA image cannot reach
#: the GPU through a host whose default runtime is nvidia.
VOID_ENV = {"NVIDIA_VISIBLE_DEVICES": "void"}
#: env keys CashPilot sets itself. A catalog entry or a deploy request may not.
ENV_PREFIX = "NVIDIA_"

TOOLKIT_URL = "https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html"
NVIDIA_HINT = (
    "This host's Docker cannot pass NVIDIA GPUs into containers: the NVIDIA Container Toolkit is missing, "
    f"or Docker was not restarted after it was installed. Install it ({TOOLKIT_URL}), run "
    "`sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker`, then deploy again."
)


class GpuRefused(Exception):
    """The grant cannot be honoured on this machine; nothing was touched."""


# ---------------------------------------------------------------------------
# The catalog block
# ---------------------------------------------------------------------------


def spec_of(svc: dict[str, Any] | None) -> dict[str, Any] | None:
    """``docker.gpu`` of a catalog entry, normalised, or None when it declares none.

    ``count`` is 1 or "all"; ``rocm`` a bool. A block the loader would refuse is
    None too: it never reaches a worker, and a guess here would hand out a GPU.
    """
    block = ((svc or {}).get("docker") or {}).get("gpu")
    if not isinstance(block, dict) or block.get("vendor") not in VENDORS:
        return None
    count = block.get("count", 1)
    if count not in (1, "all") or isinstance(count, bool):
        return None
    return {"vendor": block["vendor"], "count": count, "rocm": block.get("rocm") is True}


def spec_errors(data: dict[str, Any]) -> list[str]:
    """What is wrong with a catalog entry's ``docker.gpu`` and the keys around it."""
    docker = data.get("docker") if isinstance(data.get("docker"), dict) else {}
    errors: list[str] = []
    for item in docker.get("env") or []:
        key = item.get("key") if isinstance(item, dict) else None
        if isinstance(key, str) and key.upper().startswith(ENV_PREFIX):
            errors.append(f"docker.env key {key}: CashPilot sets the {ENV_PREFIX} variables itself")
    for dev in docker.get("devices") or []:
        path = str(dev).split(":")[0].rstrip("/")
        if path == KFD or path == "/dev/dri" or path.startswith("/dev/dri/"):
            errors.append(f"docker.devices {path}: a GPU comes only through docker.gpu")
    if "gpu" not in docker:
        return errors
    block = docker["gpu"]
    if not isinstance(block, dict):
        return [*errors, "docker.gpu must be a mapping"]
    if unknown := sorted(set(block) - {"vendor", "count", "rocm"}):
        errors.append(f"docker.gpu has unknown keys: {', '.join(map(str, unknown))}")
    vendor = block.get("vendor")
    if vendor not in VENDORS:
        errors.append(f"docker.gpu.vendor must be one of {', '.join(VENDORS)}, got {vendor!r}")
    count = block.get("count", 1)
    if isinstance(count, bool) or count not in (1, "all"):
        errors.append(f'docker.gpu.count must be 1 or "all", got {count!r}')
    if "rocm" in block and not isinstance(block["rocm"], bool):
        errors.append("docker.gpu.rocm must be true or false")
    elif block.get("rocm") and vendor != "amd":
        errors.append("docker.gpu.rocm is for vendor amd only")
    if (data.get("requirements") or {}).get("gpu") is not True:
        errors.append("docker.gpu needs requirements.gpu: true")
    if str(docker.get("runtime") or "").strip() != "runc":
        # gVisor cannot pass DRI devices through, and passes NVIDIA only with
        # flags CashPilot does not set.
        errors.append("docker.gpu needs docker.runtime: runc")
    if str(docker.get("network_mode") or "").strip().lower() == "host":
        errors.append("docker.gpu cannot be used with network_mode: host")
    return errors


def grant(slug: str | None) -> dict[str, Any] | None:
    """The GPU this worker's own catalog gives ``slug``, or None.

    Read from the catalog, like orchestrator.catalog_runtime: a deploy request
    never decides it. A ``custom-`` slug and an unknown slug get None.
    """
    if not slug or slug.startswith("custom-"):
        return None
    try:
        from app.catalog import get_service
    except ImportError:  # pragma: no cover - every image ships the catalog
        return None
    return spec_of(get_service(slug))


# ---------------------------------------------------------------------------
# What this machine has
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii", errors="replace").strip().lower()
    except OSError:
        return ""


def _render_number(path: str) -> int:
    try:
        return int(path.rsplit("renderD", 1)[1])
    except (IndexError, ValueError):
        return 1 << 30


def host_gpus(sysfs: Path = Path("/sys")) -> dict[str, Any]:
    """The GPUs this machine has, read from sysfs.

    sysfs shows the host's PCI bus from inside a container too, with nothing
    passed in, so this works for the worker behind the socket proxy.

    ``conclusive`` is False when the read says nothing about the host: not
    Linux, WSL2 (which passes GPUs through /dev/dxg, not PCI), or sysfs that
    cannot be read. Then ``vendors`` is empty and must not be read as "none".
    A display chip of another vendor (a server BMC's ASPEED) is ignored.
    """
    result: dict[str, Any] = {"conclusive": False, "vendors": {}, "kfd": False, "nvidia_module": False}
    system = platform.system()
    if system != "Linux":
        result["reason"] = f"GPU detection is not implemented for {system}; this says nothing about whether one exists"
        return result
    if "microsoft" in platform.release().lower():
        result["reason"] = "this is WSL, where a GPU is not on the PCI bus CashPilot reads"
        return result
    by_id = {pci: vendor for vendor, pci in VENDOR_IDS.items()}
    vendors: dict[str, dict[str, Any]] = {}
    try:
        pci_devices = sorted((sysfs / "bus" / "pci" / "devices").iterdir())
    except OSError as exc:
        result["reason"] = f"this machine's PCI devices could not be read ({exc.strerror or exc})"
        return result
    for dev in pci_devices:
        if not _read(dev / "class").startswith("0x03"):
            continue
        vendor = by_id.get(_read(dev / "vendor"))
        if vendor:
            vendors.setdefault(vendor, {"pci": 0, "render_nodes": []})["pci"] += 1
    try:
        nodes = sorted((sysfs / "class" / "drm").glob("renderD*"))
    except OSError:
        nodes = []
    for node in nodes:
        vendor = by_id.get(_read(node / "device" / "vendor"))
        if vendor:
            entry = vendors.setdefault(vendor, {"pci": 0, "render_nodes": []})
            entry["render_nodes"].append(f"/dev/dri/{node.name}")
    for entry in vendors.values():
        entry["render_nodes"].sort(key=_render_number)
    result["kfd"] = (sysfs / "class" / "kfd" / "kfd").exists()
    result["nvidia_module"] = (sysfs / "module" / "nvidia").exists()
    if "amd" in vendors:
        vendors["amd"]["kfd"] = result["kfd"]
    result["vendors"] = vendors
    result["conclusive"] = True
    return result


def describe(host: dict[str, Any]) -> str:
    """The vendors a conclusive read found, for a refusal: "Intel, NVIDIA" or "no GPU"."""
    names = [VENDOR_NAMES[v] for v in VENDORS if v in (host.get("vendors") or {})]
    return ", ".join(names) or "no GPU"


def missing(grant_: dict[str, Any], host: dict[str, Any]) -> str | None:
    """Why ``host`` cannot honour ``grant_``, or None. Only a conclusive read refuses."""
    if not host.get("conclusive"):
        return None
    vendor = grant_["vendor"]
    found = (host.get("vendors") or {}).get(vendor)
    label = VENDOR_NAMES[vendor]
    if not found:
        return f"This machine has no {label} GPU CashPilot can pass in (it sees: {describe(host)})."
    if vendor != "nvidia" and not [n for n in found.get("render_nodes") or [] if n in RENDER_NODE_CEILING]:
        return (
            f"This machine's {label} GPU has no render node CashPilot can pass in (/dev/dri/renderD128 to "
            "renderD135): its driver is not loaded, or the machine has more GPUs than CashPilot passes in."
        )
    if grant_.get("rocm") and not host.get("kfd"):
        return f"This machine's {label} GPU has no {KFD}: the ROCm driver (amdgpu with KFD) is not loaded."
    return None


def docker_kwargs(grant_: dict[str, Any] | None, host: dict[str, Any] | None = None) -> dict[str, list[Any]]:
    """``device_requests`` and ``devices`` for docker-py's containers.run.

    Raises GpuRefused when the machine cannot honour the grant: a conclusive
    read without the vendor, ROCm without /dev/kfd, or an AMD or Intel grant
    with no render node to name (those need a conclusive read).
    """
    if not grant_:
        return {"device_requests": [], "devices": []}
    host = host if host is not None else host_gpus()
    if problem := missing(grant_, host):
        raise GpuRefused(problem)
    vendor = grant_["vendor"]
    if vendor == "nvidia":
        from docker.types import DeviceRequest

        count = -1 if grant_["count"] == "all" else 1
        return {"device_requests": [DeviceRequest(driver="nvidia", count=count, capabilities=[["gpu"]])], "devices": []}
    if not host.get("conclusive"):
        raise GpuRefused(
            f"CashPilot could not read this machine's GPUs ({host.get('reason') or 'no reason given'}), "
            f"so it cannot pick the {VENDOR_NAMES[vendor]} render node to pass in."
        )
    nodes = [n for n in host["vendors"][vendor]["render_nodes"] if n in RENDER_NODE_CEILING]
    picked = nodes if grant_["count"] == "all" else nodes[:1]
    devices = [f"{n}:{n}:rwm" for n in picked]
    if grant_.get("rocm"):
        devices.append(f"{KFD}:{KFD}:rwm")
    return {"device_requests": [], "devices": devices}


def env_for(grant_: dict[str, Any] | None) -> dict[str, str]:
    """The env CashPilot stamps on a container: ``void`` unless it holds an NVIDIA grant."""
    if grant_ and grant_.get("vendor") == "nvidia":
        return {}
    return dict(VOID_ENV)


def in_ceiling(path: str) -> bool:
    """Whether a device path is one a GPU grant may pass in."""
    return path in RENDER_NODE_CEILING or path == KFD


def failure_hint(reason: str) -> str:
    """What to do about a GPU error Docker gives at start, or ""."""
    if 'could not select device driver "nvidia"' in reason or "failed to discover GPU vendor from CDI" in reason:
        return " " + NVIDIA_HINT
    if "error gathering device information while adding custom device" in reason:
        if KFD in reason:
            return f" {KFD} is missing on this host: the ROCm driver (amdgpu with KFD) is not loaded."
        if "/dev/dri/" in reason:
            return (
                " That render node is gone from this host since CashPilot read it: a driver update or a reboot can "
                "number them again. Deploy again."
            )
    return ""
