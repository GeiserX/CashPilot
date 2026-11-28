"""Settings: where CashPilot keeps the keys and passwords that matter.

Two cards. The credential encryption key (moving it out of the data folder,
below) and the earner credentials on each worker (CASHPILOT_EARNER_SECRETS,
app/secret_env.py): whether they sit in Docker's container config or in a
file that only the earner reads.

The encryption key:

The key that decrypts every stored credential sits in ``<data>/.fernet_key``
on a default install, so a copy of the data folder holds the ciphertext and
its key together. ``CASHPILOT_ENCRYPTION_KEY_FILE`` (a Docker secret, or a
file a secret manager writes) and ``CASHPILOT_ENCRYPTION_KEY`` keep it
elsewhere; app/database.py decides which one wins and refuses a key that
reads none of the stored credentials.

Three owner-only routes:

* ``GET`` the status: where the key comes from and whether a copy is still
  in the data folder. Never the key.
* ``POST .../reveal``: the key itself, once, to copy into a secret store.
  The owner's password first (step-up), and an audit row before the key leaves.
* ``POST .../remove-data-copy``: delete the data folder's copy once the same
  key comes from outside. The owner's password first.

No module may import main (tests/test_login_rate_limit.py).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app import catalog, database, deps, egress, secret_env, step_up

router = APIRouter()
logger = logging.getLogger(__name__)

AUDIT_TARGET = "credential encryption key"


async def _password(request: Request, message: str) -> str:
    """The step-up password in the JSON body, or 403 step_up_required, which the dashboard turns into a prompt."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - no body, or not JSON
        body = {}
    password = body.get("step_up_password") if isinstance(body, dict) else None
    if not isinstance(password, str) or not password:
        raise HTTPException(status_code=403, detail={"error": "step_up_required", "message": message})
    return password


@router.get("/api/settings/encryption-key")
async def api_encryption_key_status(request: Request) -> dict[str, Any]:
    deps._require_owner(request)
    return database.encryption_key_status()


@router.post("/api/settings/encryption-key/reveal")
async def api_encryption_key_reveal(request: Request) -> JSONResponse:
    deps._require_owner(request)
    password = await _password(
        request,
        "The key decrypts every credential CashPilot stores. Enter your password to show it.",
    )
    user = await deps.require_step_up(
        request, password, action=step_up.ACTION_REVEAL_ENCRYPTION_KEY, target=AUDIT_TARGET
    )
    # Fail closed: no audit row, no key.
    await database.add_audit_event("encryption_key_reveal", AUDIT_TARGET, "revealed", actor=user)
    logger.warning("Credential encryption key revealed by uid=%s", user.get("uid"))
    return JSONResponse({"key": database.encryption_key_value()}, headers={"Cache-Control": "no-store"})


@router.post("/api/settings/encryption-key/remove-data-copy")
async def api_encryption_key_remove_copy(request: Request) -> dict[str, Any]:
    deps._require_owner(request)
    if not database.encryption_key_status()["removable"]:
        raise HTTPException(
            status_code=409,
            detail="The key file in the data folder is the only copy of a key CashPilot needs, so it was not deleted.",
        )
    password = await _password(
        request,
        "After this, the data folder alone can no longer decrypt your credentials. Enter your password to delete "
        "the copy.",
    )
    user = await deps.require_step_up(request, password, action=step_up.ACTION_REMOVE_KEY_COPY, target=AUDIT_TARGET)
    try:
        database.remove_data_folder_key()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not delete the key file: {exc}") from None
    await database.add_audit_event("encryption_key_copy_removed", AUDIT_TARGET, "deleted", actor=user)
    logger.warning("The data folder's copy of the credential encryption key was deleted by uid=%s", user.get("uid"))
    return database.encryption_key_status()


@router.get("/api/settings/earner-secrets")
async def api_earner_secrets(request: Request) -> list[dict[str, Any]]:
    """Per worker: its CASHPILOT_EARNER_SECRETS setting and how many earners keep credentials in a file.

    ``mode`` is what the worker last reported ("file", "env", "unavailable" for
    a worker image without the shim), or None for a worker older than this.
    ``in_file`` and ``in_config`` count the containers of services that have a
    secret (and do not opt out): the first got the file, the second still has
    the values in Docker's config and needs a redeploy (or the setting). Both are None
    for a worker whose containers carry no shape. Never a value.
    """
    deps._require_owner(request)
    out: list[dict[str, Any]] = []
    for worker in await database.list_workers():
        try:
            info = json.loads(worker.get("system_info") or "{}")
            containers = json.loads(worker.get("containers") or "[]")
        except (TypeError, ValueError):
            info, containers = {}, []
        in_file = in_config = 0
        # A worker that sends no shapes (CashPilot-Desktop, or CASHPILOT_DRIFT_WARNINGS=off)
        # reports only its setting: its counts are unknown, never zero.
        shaped = False
        for container in containers if isinstance(containers, list) else []:
            if not isinstance(container, dict):
                continue
            slug = egress.container_slug(container)
            shape = container.get("shape")
            if not isinstance(shape, dict):
                continue
            shaped = True
            if not secret_env.covers(catalog.get_service(slug), slug):
                continue
            if shape.get("secrets_file"):
                in_file += 1
            else:
                in_config += 1
        mode = info.get("earner_secrets") if isinstance(info, dict) else None
        out.append(
            {
                "worker_id": worker.get("id"),
                "worker": worker.get("name") or "",
                "status": worker.get("status") or "",
                "mode": mode if mode in ("file", "env", "unavailable") else None,
                "in_file": in_file if shaped or not containers else None,
                "in_config": in_config if shaped or not containers else None,
            }
        )
    return out
