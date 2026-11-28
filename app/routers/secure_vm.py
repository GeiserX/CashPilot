"""The Fleet page's Secure VM commands: add one to a host, check it, remove it.

A Secure VM (scripts/cashpilot-vm, docs/secure-vm.md) is installed as root on
the host, which the UI cannot do and must not try. So, as for gVisor, the UI
shows one command for the owner to run, pinned to this release's tag and
sha256 (app/layer_scripts.py). The fleet key is never in the command: the
installer asks for it.

The UI address in the install command is the one the browser uses, as in the
add-worker box, because that is the address the owner's workers report to.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request

from app import cleartext, database, deps, i18n, layer_scripts, placement, version

router = APIRouter()

SCRIPT = "cashpilot-vm"


# What the installer accepts for --host-worker (scripts/cashpilot-vm), and the
# 64 characters the guest's worker keeps of CASHPILOT_SECURE_VM_OF.
_HOST_NAME = re.compile(r"[A-Za-z0-9._ -]{1,64}")


def _ui_url(raw: str) -> str:
    try:
        parts = urlsplit(raw.strip())
        hostname = parts.hostname
    except ValueError:
        raise HTTPException(status_code=400, detail=i18n.t("secure_vm.cmd.bad_ui_url")) from None
    if (
        parts.scheme not in ("http", "https")
        or not hostname
        or parts.username
        or parts.password
        or len(raw) > 300
        or any(c.isspace() for c in raw)
    ):
        raise HTTPException(status_code=400, detail=i18n.t("secure_vm.cmd.bad_ui_url"))
    url = f"{parts.scheme}://{parts.netloc}"
    # The guest's worker refuses to send its key over plain http to a public
    # host, so such an install could never enrol: say so before it starts.
    if not cleartext.bearer_allowed(url):
        raise HTTPException(status_code=400, detail=i18n.t("secure_vm.cmd.public_http"))
    return url


def commands(host_name: str, ui_url: str, has_vm: bool) -> dict[str, str]:
    """``install`` for a host without a Secure VM; ``status``, ``verify`` and ``remove`` for one with it."""
    if not has_vm and not _HOST_NAME.fullmatch(host_name):
        return {"error": i18n.t("secure_vm.cmd.bad_host_name", name=host_name)}
    try:
        if has_vm:
            return {action: layer_scripts.command(SCRIPT, action) for action in ("status", "verify", "remove")}
        # --ref: the guest takes its compose file from the same release as the
        # script, which checks it against its own pin.
        ref = "v" + version.current().removeprefix("v")
        return {
            "install": layer_scripts.command(
                SCRIPT, "install", ["--ui", ui_url, "--host-worker", host_name, "--ref", ref]
            )
        }
    except layer_scripts.Unavailable as exc:
        return {"error": str(exc)}


def vm_host(vm_info: dict[str, Any], workers: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The one worker a Secure VM names as its host, or None.

    A VM names its host by worker name, and two workers can share a name (an
    old offline worker and its replacement, say). Then the VM belongs to
    neither: showing it under both could put its status and its controls
    under the wrong computer.
    """
    name = (vm_info.get("secure_vm") or {}).get("host")
    hosts = [w for w in workers if w["name"] == name and not is_secure_vm(placement.system_info(w))]
    return hosts[0] if len(hosts) == 1 else None


def is_secure_vm(info: dict[str, Any]) -> bool:
    return "secure_vm" in (info.get("features") or []) and isinstance(info.get("secure_vm"), dict)


@router.get("/api/workers/{worker_id}/secure-vm/commands")
async def api_secure_vm_commands(request: Request, worker_id: int, ui_url: str = "") -> dict[str, Any]:
    # ui_url is optional so that FastAPI does not answer 422 before the owner check.
    deps._require_owner(request)
    url = _ui_url(ui_url)
    workers = await database.list_workers()
    host = next((w for w in workers if w["id"] == worker_id), None)
    if host is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    info = placement.system_info(host)
    if placement.is_android(info) or placement.is_desktop(info) or is_secure_vm(info):
        raise HTTPException(status_code=400, detail=i18n.t("secure_vm.cmd.not_a_host"))
    if sum(1 for w in workers if w["name"] == host["name"] and not is_secure_vm(placement.system_info(w))) > 1:
        raise HTTPException(status_code=409, detail=i18n.t("secure_vm.cmd.same_name", name=host["name"]))
    has_vm = any(
        is_secure_vm(vi) and (h := vm_host(vi, workers)) is not None and h["id"] == host["id"]
        for vi in (placement.system_info(w) for w in workers)
    )
    return commands(host["name"], url, has_vm)
