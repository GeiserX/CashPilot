"""Ask the UI to forget this worker. Run by ``cashpilot-vm remove`` in the Secure VM's guest.

    docker exec cashpilot-worker python -m app.worker_retire

It signs the request with this worker's own key, and the UI accepts it only
from a worker that reported itself as a Secure VM (``POST /api/workers/retire``).
Exit 0 when the UI forgot the worker, 1 otherwise, with the reason on stdout.
"""

from __future__ import annotations

import sys

import httpx

from app import worker_api


def retire() -> tuple[bool, str]:
    if not worker_api.UI_URL:
        return False, "CASHPILOT_UI_URL is not set"
    if refusal := worker_api._ui_url_refusal():
        return False, refusal
    key = worker_api._load_worker_key()
    if not key:
        return False, "this worker has no key of its own yet, so the UI has nothing to forget"
    try:
        resp = httpx.post(
            f"{worker_api.UI_URL.rstrip('/')}/api/workers/retire",
            json={"client_id": worker_api.CLIENT_ID},
            headers={"Authorization": f"Bearer {key}"},
            timeout=15,
        )
    except httpx.HTTPError as exc:
        return False, f"the UI did not answer: {type(exc).__name__}"
    if resp.status_code == 200:
        return True, "the UI forgot this worker"
    try:
        detail = resp.json().get("detail")
    except ValueError:
        detail = None
    return False, f"the UI refused ({resp.status_code}): {detail or resp.reason_phrase}"


def main() -> int:
    ok, message = retire()
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
