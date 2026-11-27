"""Security layers API: each worker's layers, and the owner's runtime choice (app/layers_ui.py).

Reading is for anyone signed in; choosing is owner only, and POST, because the
session cookie is SameSite=lax and still rides a cross-site GET. Saving a
choice changes no container: the Fleet page redeploys a running earner only
after the owner confirmed it.

Like the other routers, handlers reach shared state through ``app.deps`` and
``app.database``, never ``app.main``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import catalog, database, deps, layers_ui, placement

router = APIRouter()


async def _workers() -> list[dict[str, Any]]:
    """Every worker that runs Docker earners: phones and Desktop have their own layer model."""
    found = []
    for w in await database.list_workers():
        info = placement.system_info(w)
        if not placement.is_android(info) and not placement.is_desktop(info):
            found.append(w)
    return found


@router.get("/api/layers")
async def api_layers(request: Request) -> dict[str, Any]:
    deps._require_reader(request)
    views = {}
    for w in await _workers():
        views[str(w["id"])] = layers_ui.worker_view(w, await layers_ui.choices(w))
    return {"workers": views, "commands": layers_ui.commands()}


class RuntimeChoice(BaseModel):
    # An earner's slug, or None for the worker's runtime for new earners.
    slug: str | None = None
    # "runc", "gvisor", or None to forget the choice (Docker's default).
    choice: str | None = None


@router.post("/api/workers/{worker_id}/runtime-choice")
async def api_runtime_choice(request: Request, worker_id: int, body: RuntimeChoice) -> dict[str, Any]:
    deps._require_owner(request)
    if body.choice is not None and body.choice not in layers_ui.CHOICES:
        raise HTTPException(status_code=400, detail=f"choice takes one of {', '.join(layers_ui.CHOICES)}, or null")
    worker = next((w for w in await _workers() if w["id"] == worker_id), None)
    if worker is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    info = placement.system_info(worker)
    if body.slug is not None and not catalog.get_service(body.slug):
        raise HTTPException(status_code=404, detail=f"Service '{body.slug}' not found")
    if body.choice is not None and (why := layers_ui.locked(body.slug or "", info, body.choice)):
        raise HTTPException(status_code=409, detail=why)
    if body.slug is None:
        stored = await layers_ui.set_default(worker, body.choice)
    else:
        stored = await layers_ui.set_earner(worker, body.slug, body.choice)
    return layers_ui.worker_view(worker, stored)
