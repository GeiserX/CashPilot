"""An unauthenticated caller must be told 401, not handed the request schema.

CashPilot-nz4d. Guards used to be called inside handler bodies:

    @app.post("/api/config")
    async def api_set_config(request: Request, body: ConfigUpdate):
        _require_owner(request)

FastAPI validates `body` BEFORE the function runs, so a malformed body from an
entirely unauthenticated caller returned 422 with the field-level schema:

    {"detail":[{"type":"missing","loc":["body","data"],"msg":"Field required"}]}

Authentication still held -- nothing was read or written -- but the write
surface could be enumerated and its schemas learned without credentials, and
Pydantic parsed untrusted input before anyone was identified.

Moving the guard into Depends() resolves auth first. Verified in isolation
before the change was made:

    in-body guard   malformed+noauth -> 422    valid+noauth -> 401
    Depends() guard malformed+noauth -> 401    valid+noauth -> 401
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

#: Endpoints whose guard was moved into a dependency. Each takes a Pydantic
#: body and an UNCONDITIONAL guard.
CONVERTED = [
    ("post", "/api/deploy/honeygain"),
    ("post", "/api/compose"),
    ("post", "/api/preferences"),
    ("post", "/api/config"),
    ("post", "/api/users/me/password"),
    ("post", "/api/users/1/password"),
]


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(("method", "path"), CONVERTED, ids=[p for _, p in CONVERTED])
def test_malformed_body_unauthenticated_is_401_not_422(client, method, path):
    """The finding itself: a schema error must not precede the auth error."""
    resp = getattr(client, method)(path, json={"deliberately": "wrong"})
    assert resp.status_code == 401, (
        f"{path} returned {resp.status_code}; a 422 here hands the request schema "
        f"to an unauthenticated caller. Body: {resp.text[:200]}"
    )


@pytest.mark.parametrize(("method", "path"), CONVERTED, ids=[p for _, p in CONVERTED])
def test_valid_body_unauthenticated_is_also_401(client, method, path):
    """The control that stops the test above passing for the wrong reason.

    If an endpoint were simply broken, misrouted, or removed, the malformed
    case could return 401 (or 404) while proving nothing about ordering. This
    asserts the endpoint is genuinely reachable and genuinely guarded: a
    WELL-FORMED request from an unauthenticated caller must also be refused,
    and refused with the same status.
    """
    body = {"data": {}, "slugs": [], "current_password": "x", "new_password": "y", "password": "z"}
    resp = getattr(client, method)(path, json=body)
    assert resp.status_code == 401, f"{path} returned {resp.status_code}: {resp.text[:200]}"


def test_the_schema_is_not_leaked_to_an_unauthenticated_caller(client):
    """No field-level validation detail may appear in an unauthenticated reply."""
    resp = client.post("/api/config", json={})
    assert resp.status_code == 401
    text = resp.text.lower()
    for leaked in ("field required", '"loc"', "body", "missing"):
        assert leaked not in text, f"unauthenticated 401 body leaked {leaked!r}: {resp.text[:200]}"


def test_a_conditional_guard_endpoint_is_deliberately_not_converted(client):
    """/api/workers/{id}/command decides its guard FROM the body.

    Deploy requires owner, everything else requires writer, so the body must be
    parsed before the right guard is known. It therefore cannot be hoisted into
    a dependency, and this records that as a deliberate exception rather than an
    oversight -- while still asserting it refuses an unauthenticated caller.
    """
    resp = client.post("/api/workers/1/command", json={"command": "deploy"})
    assert resp.status_code in (401, 403), f"got {resp.status_code}: {resp.text[:200]}"
