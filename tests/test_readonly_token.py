"""The read-only API token, and the refusal that makes it safe. CashPilot-c99d.

A dashboard tile needs to read two numbers. Before this token the only ways to
authenticate that were the admin key (which deploys, stops and removes
containers, and reads stored credentials) or the fleet key (which enrols
workers). Neither is close to least privilege for showing a balance.

The token itself is the easy half. The half that has to be tested is the
REFUSAL: an allowlist fails silently, and it fails in the direction of passing.
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

from app import auth, deps  # noqa: E402

READONLY = "readonly-secret"

# The endpoints a reporting integration is allowed to reach. Deliberately small:
# widening it later is easy, narrowing it is a breaking change for whoever wired
# a dashboard against it.
ALLOWLIST = {
    "/api/earnings/summary",
    "/api/earnings/breakdown",
    "/api/fleet/summary",
    "/api/health/scores",
    "/api/services/deployed",
}


def _request(headers=None, cookies=None):
    req = MagicMock()
    req.headers = headers or {}
    req.cookies = cookies or {}
    return req


class TestTokenRecognition:
    def test_readonly_key_returns_reader_role(self):
        with patch.dict(os.environ, {"CASHPILOT_READONLY_API_KEY": READONLY}):
            user = auth.get_current_user(_request({"Authorization": f"Bearer {READONLY}"}))
            assert user is not None
            assert user["r"] == "reader"

    def test_unset_readonly_key_grants_nothing(self):
        """An empty env var must not make an empty/absent Bearer authenticate."""
        with patch.dict(os.environ, {"CASHPILOT_READONLY_API_KEY": ""}):
            assert auth.get_current_user(_request({"Authorization": "Bearer "})) is None
            assert auth.get_current_user(_request({"Authorization": "Bearer "})) is None

    def test_ambiguous_config_resolves_to_LESS_privilege(self):
        """Both variables set to one value is a misconfiguration either way.

        The two resolutions are not equally bad. Resolving to owner would hand
        full container control to whatever the operator pasted into a dashboard
        widget; resolving to reader merely stops the admin path working, which
        is loud and harmless.
        """
        both = "same-value-by-mistake"
        with patch.dict(
            os.environ,
            {"CASHPILOT_READONLY_API_KEY": both, "CASHPILOT_ADMIN_API_KEY": both},
        ):
            user = auth.get_current_user(_request({"Authorization": f"Bearer {both}"}))
            assert user is not None
            assert user["r"] == "reader", "ambiguity must resolve DOWN, never up to owner"

    def test_admin_key_still_returns_owner_when_distinct(self):
        with patch.dict(
            os.environ,
            {"CASHPILOT_READONLY_API_KEY": READONLY, "CASHPILOT_ADMIN_API_KEY": "admin-secret"},
        ):
            user = auth.get_current_user(_request({"Authorization": "Bearer admin-secret"}))
            assert user is not None and user["r"] == "owner"


class TestGuards:
    """_require_auth_api must REFUSE the reader. That refusal is the model."""

    def test_shared_guard_refuses_reader(self):
        with patch.object(auth, "get_current_user", return_value={"uid": 0, "u": "readonly", "r": "reader"}):
            with pytest.raises(HTTPException) as exc:
                deps._require_auth_api(_request())
            assert exc.value.status_code == 403

    def test_reader_guard_accepts_reader(self):
        with patch.object(auth, "get_current_user", return_value={"uid": 0, "u": "readonly", "r": "reader"}):
            assert deps._require_reader(_request())["r"] == "reader"

    @pytest.mark.parametrize("role", ["owner", "writer", "fleet"])
    def test_reader_guard_still_accepts_higher_roles(self, role):
        """Opting an endpoint in must not lock out the roles that already had it."""
        with patch.object(auth, "get_current_user", return_value={"uid": 1, "u": "x", "r": role}):
            assert deps._require_reader(_request())["r"] == role

    def test_both_guards_still_401_when_unauthenticated(self):
        with patch.object(auth, "get_current_user", return_value=None):
            for guard in (deps._require_auth_api, deps._require_reader):
                with pytest.raises(HTTPException) as exc:
                    guard(_request())
                assert exc.value.status_code == 401

    def test_writer_and_owner_reject_reader(self):
        """They delegate to _require_auth_api, so the refusal must reach them too."""
        with patch.object(auth, "get_current_user", return_value={"uid": 0, "u": "readonly", "r": "reader"}):
            for guard in (deps._require_writer, deps._require_owner):
                with pytest.raises(HTTPException) as exc:
                    guard(_request())
                assert exc.value.status_code == 403


class TestFailsClosed:
    """The test that has to survive people who never read this file.

    Walks the app's own route table rather than any hand-kept list, so an
    endpoint added later is covered the day it is added. If someone opts a new
    endpoint into the reader without widening ALLOWLIST here, this fails.
    """

    def _api_get_routes(self):
        from app.main import app as fastapi_app

        routes = []
        for route in fastapi_app.routes:
            path = getattr(route, "path", "")
            methods = getattr(route, "methods", set()) or set()
            if not path.startswith("/api/"):
                continue
            if "GET" not in methods:
                continue
            if "{" in path:  # path params need fixtures; covered by the unit guards above
                continue
            routes.append(path)
        return sorted(set(routes))

    def test_allowlist_entries_all_exist(self):
        """A typo in ALLOWLIST would silently weaken every assertion below."""
        found = set(self._api_get_routes())
        missing = ALLOWLIST - found
        assert not missing, f"ALLOWLIST names routes that do not exist: {sorted(missing)}"

    def test_there_are_endpoints_outside_the_allowlist(self):
        """Negative control. If this ever passes trivially the sweep proves nothing."""
        outside = set(self._api_get_routes()) - ALLOWLIST
        assert len(outside) > 5, f"sweep would be vacuous, only found {sorted(outside)}"

    def test_reader_is_refused_everywhere_outside_the_allowlist(self):
        from fastapi.testclient import TestClient

        from app.main import app as fastapi_app

        headers = {"Authorization": f"Bearer {READONLY}"}
        leaked = []
        with patch.dict(os.environ, {"CASHPILOT_READONLY_API_KEY": READONLY}):
            client = TestClient(fastapi_app, raise_server_exceptions=False)
            for path in self._api_get_routes():
                if path in ALLOWLIST:
                    continue
                resp = client.get(path, headers=headers)
                # 403 is the intended refusal. Anything 2xx means the read-only
                # token reached an endpoint nobody reviewed.
                if resp.status_code < 300:
                    leaked.append(f"{path} -> {resp.status_code}")
        assert not leaked, "read-only token reached non-allowlisted endpoints: " + ", ".join(leaked)

    def test_reader_is_accepted_on_the_allowlist(self):
        """The mirror image: the refusal must not be so broad it blocks the point."""
        from fastapi.testclient import TestClient

        from app.main import app as fastapi_app

        headers = {"Authorization": f"Bearer {READONLY}"}
        refused = []
        with patch.dict(os.environ, {"CASHPILOT_READONLY_API_KEY": READONLY}):
            client = TestClient(fastapi_app, raise_server_exceptions=False)
            for path in sorted(ALLOWLIST):
                resp = client.get(path, headers=headers)
                if resp.status_code in (401, 403):
                    refused.append(f"{path} -> {resp.status_code}")
        assert not refused, "allowlisted endpoints refused the read-only token: " + ", ".join(refused)
