"""Bring a money4band, CashFactory or InternetIncome setup over (owner only).

Preview is stateless: the files are parsed and a dry-run table comes back,
with secrets shown only as "set". Apply parses the same files again on the
server (the browser never sends a masked value back), stores each ready row
as an encrypted import draft, and fills the earnings login where the deploy
login is the same account. Deploying a draft goes through ``api_deploy``
unchanged, so every check a normal deploy runs still runs.

The two routes that need ``api_set_config`` and ``api_deploy`` are declared in
``app.main`` and call ``apply`` and ``draft_env`` here: no module may import
main (tests/test_login_rate_limit.py), so main hands those in.

Nothing from a pasted file is executed or fetched, and the files are never
stored. Bodies are read by hand, with a size cap, rather than through a
pydantic model: a 422 would echo the pasted text, which holds passwords.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app import catalog, database
from app.deps import _require_owner
from app.importers import parse

logger = logging.getLogger(__name__)

router = APIRouter()

#: The whole request, files and all. Past this the body is not read further.
MAX_BODY_BYTES = 256 * 1024


async def _read_body(request: Request) -> dict[str, Any]:
    size = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail=f"The upload is larger than {MAX_BODY_BYTES // 1024} KiB.")
        chunks.append(chunk)
    try:
        body = json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object.")
    return body


def _source(body: dict[str, Any]) -> str:
    source = body.get("source") or "auto"
    if source != "auto" and source not in parse.SOURCES:
        raise HTTPException(status_code=400, detail="Unknown tool.")
    return source


def _preview(body: dict[str, Any], extra: dict[str, dict[str, str]] | None = None) -> dict[str, Any]:
    """Parse ``body``'s files into the full preview, env included (server side only)."""
    source = _source(body)
    try:
        files = parse.read_files(body.get("files"), source)
        detected = parse.detect_source(files, source)
        return parse.build_preview(files, detected, catalog.get_service, extra)
    except parse.ImportRefused as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None


def _collector_keys(slug: str, env: dict[str, str]) -> dict[str, str]:
    """The earnings-login config this row's deploy values also fill, if any."""
    links = parse.SOURCES_DATA.get("collector_links") or {}
    mapping = links.get(slug) or {}
    if not mapping or not all(env.get(k) for k in mapping):
        return {}
    return {f"{slug}_{arg}": env[k] for k, arg in mapping.items()}


def _public(row: dict[str, Any]) -> dict[str, Any]:
    """A row as it may leave the server: no env, secret fields carry no value."""
    out = {k: v for k, v in row.items() if k != "env"}
    out["fields"] = [{k: v for k, v in f.items() if not (k == "value" and f.get("secret"))} for f in row["fields"]]
    return out


@router.post("/api/import/preview")
async def api_import_preview(request: Request, _auth: dict[str, Any] = Depends(_require_owner)) -> dict[str, Any]:
    body = await _read_body(request)
    preview = _preview(body)
    config = await database.get_config() or {}
    drafts = {d["slug"] for d in await database.list_import_drafts()}
    rows = []
    for row in preview["rows"]:
        public = _public(row)
        keys = _collector_keys(row["slug"], row["env"])
        if not (parse.SOURCES_DATA.get("collector_links") or {}).get(row["slug"]):
            public["collector"] = "none"
        elif keys and all(config.get(k) for k in keys):
            public["collector"] = "already_set"
        else:
            public["collector"] = "will_set" if keys else "none"
        public["existing"] = {
            "deployed": bool(await database.get_deployment(row["slug"])),
            "draft": row["slug"] in drafts,
        }
        rows.append(public)
    return {**preview, "rows": rows}


def _extra(body: dict[str, Any]) -> dict[str, dict[str, str]]:
    raw = body.get("extra")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="extra must be an object.")
    out: dict[str, dict[str, str]] = {}
    for slug, fields in raw.items():
        if not isinstance(fields, dict):
            raise HTTPException(status_code=400, detail="extra must map each service to its fields.")
        out[str(slug)] = {str(k): v for k, v in fields.items() if isinstance(v, str)}
    return out


async def apply(request: Request, set_collector_config: Callable[[dict[str, str]], Awaitable[Any]]) -> dict[str, Any]:
    """Save the chosen rows as drafts. Only rows that end up ready are written.

    ``set_collector_config`` stores earnings credentials the way Settings does
    (``api_set_config`` in main, which also starts tracking the service); main
    passes it in because no module may import main.
    """
    body = await _read_body(request)
    slugs = body.get("slugs")
    if not isinstance(slugs, list) or not slugs or not all(isinstance(s, str) for s in slugs):
        raise HTTPException(status_code=400, detail="Choose at least one service.")
    preview = _preview(body, _extra(body))
    by_slug = {row["slug"]: row for row in preview["rows"]}
    chosen = []
    for slug in dict.fromkeys(slugs):
        row = by_slug.get(slug)
        if row is None:
            raise HTTPException(status_code=400, detail=f"{slug[:60]} is not in these files.")
        if row["state"] != "ready":
            raise HTTPException(status_code=400, detail=f"{row['name']} cannot be imported yet: {row['reason']}")
        chosen.append(row)

    config = await database.get_config() or {}
    saved, collectors = [], []
    for row in chosen:
        try:
            await database.save_import_draft(row["slug"], preview["source"], row["env"])
        except database.EphemeralKeyError:
            raise HTTPException(
                status_code=409,
                detail="CashPilot's encryption key is temporary, so it will not store credentials. "
                "Set CASHPILOT_ENCRYPTION_KEY or fix the data directory, then restart.",
            ) from None
        saved.append(row["slug"])
        keys = _collector_keys(row["slug"], row["env"])
        # Never over working earnings credentials: only where none are set.
        if keys and not any(config.get(k) for k in keys):
            await set_collector_config(keys)
            collectors.append(row["slug"])
    logger.info("Imported from %s: %s (earnings login set for: %s)", preview["source"], saved, collectors or "none")
    return {"saved": saved, "collectors_set": collectors}


async def draft_env(slug: str) -> dict[str, str]:
    """The saved env of ``slug``'s import, for main's deploy route to hand to api_deploy."""
    draft = await database.get_import_draft(slug)
    if not draft:
        raise HTTPException(status_code=404, detail="Nothing imported for this service.")
    return draft["env"]


@router.get("/api/import/drafts")
async def api_import_drafts(_auth: dict[str, Any] = Depends(_require_owner)) -> list[dict[str, Any]]:
    drafts = await database.list_import_drafts()
    for draft in drafts:
        svc = catalog.get_service(draft["slug"]) or {}
        draft["name"] = svc.get("name") or draft["slug"]
    return drafts


@router.delete("/api/import/drafts/{slug}")
async def api_import_draft_forget(slug: str, _auth: dict[str, Any] = Depends(_require_owner)) -> dict[str, Any]:
    if not await database.delete_import_draft(slug):
        raise HTTPException(status_code=404, detail="Nothing imported for this service.")
    return {"status": "forgotten"}
