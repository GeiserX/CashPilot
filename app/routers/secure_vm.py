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

from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request

from app import database, deps, i18n, layer_scripts, placement

router = APIRouter()

SCRIPT = "cashpilot-vm"


def _ui_url(raw: str) -> str:
    parts = urlsplit(raw.strip())
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username
        or parts.password
        or len(raw) > 300
        or any(c.isspace() for c in raw)
    ):
        raise HTTPException(status_code=400, detail=i18n.t("secure_vm.cmd.bad_ui_url"))
    return f"{parts.scheme}://{parts.netloc}"


def commands(host_name: str, ui_url: str, has_vm: bool) -> dict[str, str]:
    """``install`` for a host without a Secure VM; ``status``, ``verify`` and ``remove`` for one with it."""
    try:
        if has_vm:
            return {action: layer_scripts.command(SCRIPT, action) for action in ("status", "verify", "remove")}
        return {"install": layer_scripts.command(SCRIPT, "install", ["--ui", ui_url, "--host-worker", host_name])}
    except layer_scripts.Unavailable as exc:
        return {"error": str(exc)}


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
    has_vm = any(
        is_secure_vm(vi) and vi["secure_vm"].get("host") == host["name"]
        for vi in (placement.system_info(w) for w in workers)
    )
    return commands(host["name"], url, has_vm)
