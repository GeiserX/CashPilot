"""User management routes (list, role update, delete) — owner only.

The change-password routes (Task 4 / H4) deliberately stay in ``app.main`` to
avoid the direct-import problem. Handlers reference shared state through
``app.main`` so test patches on ``app.main.database.*`` continue to land.
"""

from __future__ import annotations

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
    return {"status": "deleted"}
