"""The security layers per worker and per earner, as the UI shows and stores them.

The worker reports what its host can give (``system_info.layers``, app/layers.py)
and which runtime and network each container got. This module turns that into
what the Fleet page shows, and keeps the owner's runtime choice:

* per worker, the runtime for earners deployed there from now on;
* per earner, its own runtime, which the deploy sends as ``runtime_choice``.

A choice is locked, with the reason, when the earner's catalog entry requires
another runtime (Mysterium needs runc), when an environment variable on the
worker pins it, or when the worker cannot honour it. Nothing here changes a
running earner by itself: an earner's runtime changes on its next deploy, and
the Fleet page redeploys it only when the owner asks.

The choices live in the config table, one JSON value per worker, keyed by the
worker's client_id as the other per-worker settings are.
"""

from __future__ import annotations

import json
import time
from typing import Any

from app import catalog, database, i18n, layer_scripts, placement

RUNC = "runc"
GVISOR = "gvisor"
CHOICES = (RUNC, GVISOR)
FEATURE = "runtime_choice"
CHECK_FEATURE = "gvisor_check"
FENCE_NETWORK = "cashpilot-isolated"


def config_key(worker: dict[str, Any]) -> str:
    return f"worker_{worker.get('client_id') or worker.get('id') or ''}_runtime_choice"


def _containers(worker: dict[str, Any]) -> list[dict[str, Any]]:
    raw = worker.get("containers")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except ValueError:
            return []
    return [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []


def _features(info: dict[str, Any]) -> set[str]:
    features = info.get("features")
    return {str(f) for f in features} if isinstance(features, list) else set()


async def choices(worker: dict[str, Any]) -> dict[str, Any]:
    """``{"default": runc|gvisor|None, "earners": {slug: choice}}`` for one worker."""
    raw = await database.get_config(config_key(worker))
    try:
        data = json.loads(raw) if isinstance(raw, str) and raw else {}
    except ValueError:
        data = {}
    default = data.get("default") if data.get("default") in CHOICES else None
    earners = data.get("earners") if isinstance(data.get("earners"), dict) else {}
    return {"default": default, "earners": {str(k): v for k, v in earners.items() if v in CHOICES}}


async def save(worker: dict[str, Any], data: dict[str, Any]) -> None:
    await database.set_config(config_key(worker), json.dumps(data, sort_keys=True))


def kind(runtime: str | None, report: dict[str, Any] | None) -> str | None:
    """``gvisor``, ``runc`` or None (unknown) for the runtime a container got.

    Judged from the worker's own list, which looks at the binary; a name the
    list does not hold is judged by its name.
    """
    if not runtime:
        return None
    for fact in (report or {}).get("runtimes") or []:
        if isinstance(fact, dict) and fact.get("name") == runtime:
            return GVISOR if fact.get("gvisor") else RUNC
    return GVISOR if runtime.startswith("runsc") else RUNC


def gvisor_ready(report: dict[str, Any] | None) -> bool:
    """Whether the worker has the --network=host gVisor runtime an earner would get."""
    runtimes = (report or {}).get("runtimes") or []
    allowed = (report or {}).get("proxy_runtimes")
    return any(
        isinstance(f, dict) and f.get("gvisor") and f.get("hostnet") and (allowed is None or f.get("name") in allowed)
        for f in runtimes
    )


def gvisor_state(info: dict[str, Any]) -> dict[str, Any]:
    """Whether gVisor can be offered on this worker, and why not when it cannot."""
    report = info.get("layers") if isinstance(info.get("layers"), dict) else None
    os_name = str(info.get("os") or "")
    if "unraid" in os_name.lower():
        return {
            "state": "unsupported",
            "why": i18n.t("layers.why.unraid"),
        }
    if os_name and not os_name.lower().startswith("linux"):
        return {"state": "unsupported", "why": i18n.t("layers.why.not_linux")}
    if report is None or FEATURE not in _features(info):
        return {"state": "unknown", "why": i18n.t("layers.why.old_worker")}
    if report.get("runtimes") is None:
        return {"state": "unknown", "why": i18n.t("layers.why.no_docker")}
    if gvisor_ready(report):
        return {"state": "installed", "why": ""}
    return {"state": "missing", "why": i18n.t("layers.why.missing")}


def _catalog_runtime(slug: str) -> str | None:
    runtime = ((catalog.get_service(slug) or {}).get("docker") or {}).get("runtime")
    return runtime.strip() if isinstance(runtime, str) and runtime.strip() else None


def _pin(slug: str, report: dict[str, Any] | None, network_mode: str | None) -> str | None:
    pins = (report or {}).get("pins") if isinstance((report or {}).get("pins"), dict) else {}
    # The worker applies both variables to bridge networking only (orchestrator.container_runtime).
    if (network_mode or "bridge") not in ("bridge", "default"):
        return None
    overrides = pins.get("overrides") if isinstance(pins.get("overrides"), dict) else {}
    if slug in overrides:
        return i18n.t("layers.why.pin_override", slug=slug, runtime=str(overrides[slug]))
    if pins.get("default"):
        return i18n.t("layers.why.pin_default", runtime=str(pins["default"]))
    return None


def locked(slug: str, info: dict[str, Any], choice: str) -> str | None:
    """Why ``choice`` cannot be made for ``slug`` on this worker, or None when it can."""
    report = info.get("layers") if isinstance(info.get("layers"), dict) else None
    name = (catalog.get_service(slug) or {}).get("name") or slug
    required = _catalog_runtime(slug)
    if required and (GVISOR if required.startswith("runsc") else RUNC) != choice:
        reason = ((catalog.get_service(slug) or {}).get("docker") or {}).get("runtime_reason")
        if isinstance(reason, str) and reason.strip():
            return i18n.t("layers.why.catalog_reason", service=name, runtime=required, reason=reason.strip())
        return i18n.t("layers.why.catalog", service=name, runtime=required)
    network_mode = ((catalog.get_service(slug) or {}).get("docker") or {}).get("network_mode")
    if pin := _pin(slug, report, network_mode):
        return pin
    state = gvisor_state(info)
    if state["state"] in ("unknown", "unsupported"):
        return state["why"]
    if choice == GVISOR and state["state"] != "installed":
        return i18n.t("layers.why.install_first")
    return None


def fence(container: dict[str, Any], info: dict[str, Any]) -> bool | None:
    """Whether this container sits behind the LAN fence. None when the worker does not say."""
    network = container.get("network")
    if network is None:
        return None
    iso = info.get("isolation") if isinstance(info.get("isolation"), dict) else {}
    if network == FENCE_NETWORK:
        # With isolation off the network keeps its masquerade but loses its filter.
        return iso.get("mode") == "on" and (iso.get("fence") or {}).get("state") != "failed"
    # The operator's own bridge (CASHPILOT_CONTAINER_NETWORK), with their own firewall.
    return bool(iso.get("mode") == "operator" and network == iso.get("network"))


#: Seconds after which a Secure VM fence state is stale. The host's guard
#: pushes it into the guest at most every 5 minutes, or at once on a change.
VM_FENCE_STALE = 600


def secure_vm(info: dict[str, Any], now: float | None = None) -> dict[str, Any] | None:
    """The Secure VM fence of a worker that runs inside one, or None for any other worker.

    ``state`` is ``ok`` only for a fresh ok from the host's guard. A missing,
    unreadable or old state is ``unknown`` or ``stale``, never ``ok``.
    """
    if "secure_vm" not in _features(info) or not isinstance(info.get("secure_vm"), dict):
        return None
    block = info["secure_vm"]
    fence = block.get("fence") if isinstance(block.get("fence"), dict) else None
    view = {"host": str(block.get("host") or ""), "state": "unknown", "reason": ""}
    if fence is None:
        return view
    checked = fence.get("checked_at")
    view["reason"] = str(fence.get("reason") or "")[:200]
    if fence.get("state") == "failed":
        view["state"] = "failed"
    elif fence.get("state") == "ok" and isinstance(checked, (int, float)):
        fresh = ((time.time() if now is None else now) - checked) <= VM_FENCE_STALE
        view["state"] = "ok" if fresh else "stale"
    return view


def worker_view(worker: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
    """What the Fleet page shows for one worker's layers."""
    info = placement.system_info(worker)
    report = info.get("layers") if isinstance(info.get("layers"), dict) else None
    vm = secure_vm(info)
    earners = []
    seen: set[str] = set()
    for c in _containers(worker):
        slug = str(c.get("slug") or "")
        if not slug or slug in seen or c.get("deployed_by") == "external":
            continue
        seen.add(slug)
        runtime = kind(c.get("runtime"), report)
        choice = stored["earners"].get(slug)
        other = GVISOR if (choice or runtime or RUNC) == RUNC else RUNC
        earners.append(
            {
                "slug": slug,
                "service": (catalog.get_service(slug) or {}).get("name") or slug,
                "status": c.get("status"),
                "runtime": runtime,
                "runtime_name": c.get("runtime"),
                "fence": fence(c, info),
                # Inside a Secure VM: True only for a fresh ok fence, None when unknown or stale.
                "vm": None
                if vm is None
                else (True if vm["state"] == "ok" else False if vm["state"] == "failed" else None),
                "choice": choice,
                # Why the owner cannot switch this earner to the other runtime.
                "locked": locked(slug, info, other),
            }
        )
    state = gvisor_state(info)
    return {
        "known": report is not None,
        "gvisor": state,
        "check": (report or {}).get("gvisor_check"),
        "can_check": CHECK_FEATURE in _features(info),
        "kvm": (report or {}).get("kvm"),
        "secure_vm": vm,
        "pins": (report or {}).get("pins"),
        "default": stored["default"],
        "default_locked": locked("", info, GVISOR) if stored["default"] != GVISOR else None,
        "earners": earners,
    }


def commands() -> dict[str, Any]:
    """The install, status and undo commands, or the reason none can be shown."""
    try:
        return {action: layer_scripts.command("cashpilot-gvisor", action) for action in ("install", "status", "undo")}
    except layer_scripts.Unavailable as exc:
        return {"error": str(exc)}


async def set_default(worker: dict[str, Any], choice: str | None) -> dict[str, Any]:
    """Set the runtime for earners first deployed here from now on.

    Earners already on the worker keep the runtime they have: each one without
    its own choice gets the one it runs under now, so a later redeploy of it
    does not move it either.
    """
    stored = await choices(worker)
    info = placement.system_info(worker)
    report = info.get("layers") if isinstance(info.get("layers"), dict) else None
    for c in _containers(worker):
        slug = str(c.get("slug") or "")
        if slug and slug not in stored["earners"] and (now := kind(c.get("runtime"), report)):
            stored["earners"][slug] = now
    stored["default"] = choice
    await save(worker, stored)
    return stored


async def set_earner(worker: dict[str, Any], slug: str, choice: str | None) -> dict[str, Any]:
    stored = await choices(worker)
    if choice is None:
        stored["earners"].pop(slug, None)
    else:
        stored["earners"][slug] = choice
    await save(worker, stored)
    return stored


async def for_new_deploy(worker: dict[str, Any], slug: str) -> str | None:
    """The choice a deploy sends: the earner's own, else the worker's default, recorded as the earner's."""
    stored = await choices(worker)
    if slug in stored["earners"]:
        return stored["earners"][slug]
    default = stored["default"]
    if default is None:
        return None
    info = placement.system_info(worker)
    if locked(slug, info, default):
        # The default does not fit this earner (Mysterium, a pin): Docker's default, as before.
        return None
    stored["earners"][slug] = default
    await save(worker, stored)
    return default
