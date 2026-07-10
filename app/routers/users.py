"""User management routes (list, role update, delete) — owner only.

The change-password routes (Task 4 / H4) deliberately stay in ``app.main`` to
avoid the direct-import problem. Handlers reference shared state through
``app.main`` so test patches on ``app.main.database.*`` continue to land.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import app.main as main

router = APIRouter()


@router.get("/api/users")
async def api_list_users(request: Request) -> list[dict[str, Any]]:
    main._require_owner(request)
    return await main.database.list_users()


class UserRoleUpdate(BaseModel):
    role: str


@router.patch("/api/users/{user_id}")
async def api_update_user_role(request: Request, user_id: int, body: UserRoleUpdate) -> dict[str, str]:
    current = main._require_owner(request)
    if body.role not in ("viewer", "writer", "owner"):
        raise HTTPException(status_code=400, detail="Role must be viewer, writer, or owner")
    user = await main.database.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if current["uid"] == user_id and body.role != "owner":
        raise HTTPException(status_code=400, detail="Cannot demote yourself")
    if user["role"] == "owner" and body.role != "owner":
        all_users = await main.database.list_users()
        owner_count = sum(1 for u in all_users if u["role"] == "owner")
        if owner_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the last owner")
    await main.database.update_user_role(user_id, body.role)
    # Invalidate any outstanding session tokens for this user — they carry the
    # old role and must not be trusted until re-issued (same mechanism used
    # for password changes).
    main.auth.set_user_pwd_epoch(user_id, time.time())
    return {"status": "updated"}


@router.delete("/api/users/{user_id}")
async def api_delete_user(request: Request, user_id: int) -> dict[str, str]:
    current = main._require_owner(request)
    if current["uid"] == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    user = await main.database.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await main.database.delete_user(user_id)
    # Invalidate any outstanding session tokens for the now-deleted account.
    # The epoch cache is in-memory keyed by uid, so it survives the row being
    # gone from the DB — decode_session_token rejects the token on iat alone.
    main.auth.set_user_pwd_epoch(user_id, time.time())
    return {"status": "deleted"}
