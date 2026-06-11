"""Extended tests for auth.py — covers get_current_user, session cookies, secret key resolution."""

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")


from app import auth


class TestGetCurrentUser:
    def _make_request(self, headers=None, cookies=None):
        req = MagicMock()
        req.headers = headers or {}
        req.cookies = cookies or {}
        return req

    def test_no_auth_returns_none(self):
        req = self._make_request()
        assert auth.get_current_user(req) is None

    def test_admin_api_key_returns_owner(self):
        with patch.dict(os.environ, {"CASHPILOT_ADMIN_API_KEY": "admin-secret"}):
            req = self._make_request(headers={"Authorization": "Bearer admin-secret"})
            user = auth.get_current_user(req)
            assert user is not None
            assert user["r"] == "owner"
            assert user["u"] == "api"

    def test_fleet_key_returns_fleet(self):
        with patch("app.auth._fleet_key_mod.resolve_fleet_key", return_value="fleet-secret"):
            req = self._make_request(headers={"Authorization": "Bearer fleet-secret"})
            user = auth.get_current_user(req)
            assert user is not None
            assert user["r"] == "fleet"
            assert user["u"] == "fleet"

    def test_invalid_bearer_falls_through_to_cookie(self):
        req = self._make_request(
            headers={"Authorization": "Bearer wrong"},
            cookies={},
        )
        with (
            patch.dict(os.environ, {"CASHPILOT_ADMIN_API_KEY": "admin-secret"}),
            patch("app.auth._fleet_key_mod.resolve_fleet_key", return_value="fleet-secret"),
        ):
            assert auth.get_current_user(req) is None

    def test_valid_session_cookie(self):
        token = auth.create_session_token(1, "alice", "owner")
        req = self._make_request(cookies={auth.SESSION_COOKIE: token})
        user = auth.get_current_user(req)
        assert user is not None
        assert user["u"] == "alice"
        assert user["r"] == "owner"

    def test_expired_session_cookie(self):
        # Patch the serializer's loads to simulate expiration
        with patch.object(auth, "decode_session_token", return_value=None):
            token = auth.create_session_token(1, "alice", "owner")
            req = self._make_request(cookies={auth.SESSION_COOKIE: token})
            user = auth.get_current_user(req)
            assert user is None

    def test_tampered_session_cookie(self):
        req = self._make_request(cookies={auth.SESSION_COOKIE: "tampered.garbage.token"})
        assert auth.get_current_user(req) is None


class TestSetSessionCookie:
    def test_sets_cookie(self):
        resp = MagicMock()
        result = auth.set_session_cookie(resp, "test-token")
        resp.set_cookie.assert_called_once()
        args = resp.set_cookie.call_args
        assert args[1]["httponly"] is True or args[0][1] == "test-token"
        assert result is resp

    def test_secure_cookie_auto_https(self):
        resp = MagicMock()
        with (
            patch.object(auth, "_SECURE_COOKIE", "auto"),
            patch.dict(os.environ, {"CASHPILOT_BASE_URL": "https://example.com"}),
        ):
            auth.set_session_cookie(resp, "tok")
            call_kwargs = resp.set_cookie.call_args
            assert call_kwargs[1].get("secure") is True or call_kwargs.kwargs.get("secure") is True

    def test_secure_cookie_forced_true(self):
        resp = MagicMock()
        with patch.object(auth, "_SECURE_COOKIE", "true"):
            auth.set_session_cookie(resp, "tok")
            call_kwargs = resp.set_cookie.call_args
            assert call_kwargs[1].get("secure") is True or call_kwargs.kwargs.get("secure") is True


class TestClearSessionCookie:
    def test_clears_cookie(self):
        resp = MagicMock()
        result = auth.clear_session_cookie(resp)
        resp.delete_cookie.assert_called_once_with(auth.SESSION_COOKIE)
        assert result is resp


class TestRequireRole:
    def test_none_user(self):
        assert auth.require_role(None, "owner") is False

    def test_matching_role(self):
        assert auth.require_role({"r": "owner"}, "owner") is True

    def test_multiple_roles(self):
        assert auth.require_role({"r": "writer"}, "owner", "writer") is True

    def test_non_matching_role(self):
        assert auth.require_role({"r": "viewer"}, "owner", "writer") is False


class TestDecodeSessionToken:
    def test_valid_token(self):
        token = auth.create_session_token(5, "bob", "viewer")
        data = auth.decode_session_token(token)
        assert data is not None
        assert data["uid"] == 5
        assert data["u"] == "bob"
        assert data["r"] == "viewer"

    def test_invalid_token(self):
        assert auth.decode_session_token("garbage") is None

    def test_empty_token(self):
        assert auth.decode_session_token("") is None

    def test_token_before_session_epoch_rejected(self):
        """The session kill-switch: a token issued before _SESSION_EPOCH is rejected."""
        import time

        token = auth.create_session_token(9, "carol", "owner")
        # Bump the epoch to just after this token's iat → it must be invalidated.
        orig_epoch = auth._SESSION_EPOCH
        try:
            auth._SESSION_EPOCH = time.time() + 60
            assert auth.decode_session_token(token) is None
        finally:
            auth._SESSION_EPOCH = orig_epoch
        # With the epoch restored, the same token decodes again.
        assert auth.decode_session_token(token) is not None


class TestPerUserPasswordEpoch:
    """Per-user session invalidation via _USER_PWD_EPOCH."""

    def test_token_rejected_after_user_epoch_bump(self):
        """A token for a uid is rejected once that uid's pwd epoch passes its iat."""
        import time

        token = auth.create_session_token(5, "dave", "owner")
        orig = dict(auth._USER_PWD_EPOCH)
        try:
            auth.set_user_pwd_epoch(5, time.time() + 1)
            assert auth.decode_session_token(token) is None
        finally:
            auth._USER_PWD_EPOCH.clear()
            auth._USER_PWD_EPOCH.update(orig)
        # Epoch restored → token decodes again.
        assert auth.decode_session_token(token) is not None

    def test_token_survives_older_epoch(self):
        """A pwd epoch in the past does not invalidate a newer token."""
        import time

        token = auth.create_session_token(7, "erin", "viewer")
        orig = dict(auth._USER_PWD_EPOCH)
        try:
            auth.set_user_pwd_epoch(7, time.time() - 60)
            data = auth.decode_session_token(token)
            assert data is not None
            assert data["uid"] == 7
        finally:
            auth._USER_PWD_EPOCH.clear()
            auth._USER_PWD_EPOCH.update(orig)

    def test_epoch_isolated_per_uid(self):
        """Bumping one uid's epoch must not affect another uid's token."""
        import time

        token2 = auth.create_session_token(2, "frank", "owner")
        orig = dict(auth._USER_PWD_EPOCH)
        try:
            auth.set_user_pwd_epoch(1, time.time() + 60)
            data = auth.decode_session_token(token2)
            assert data is not None
            assert data["uid"] == 2
        finally:
            auth._USER_PWD_EPOCH.clear()
            auth._USER_PWD_EPOCH.update(orig)

    def test_global_epoch_still_works(self):
        """The global _SESSION_EPOCH path is unaffected by the per-user mechanism."""
        import time

        token = auth.create_session_token(3, "gina", "owner")
        orig_global = auth._SESSION_EPOCH
        orig_users = dict(auth._USER_PWD_EPOCH)
        try:
            # No per-user epoch set; global bump alone must still reject.
            auth._SESSION_EPOCH = time.time() + 60
            assert auth.decode_session_token(token) is None
        finally:
            auth._SESSION_EPOCH = orig_global
            auth._USER_PWD_EPOCH.clear()
            auth._USER_PWD_EPOCH.update(orig_users)
        assert auth.decode_session_token(token) is not None


class TestResolveSecretKey:
    def test_env_var_overrides(self):
        with patch.dict(os.environ, {"CASHPILOT_SECRET_KEY": "my-strong-secret-key-here"}):
            result = auth._resolve_secret_key()
            assert result == "my-strong-secret-key-here"

    def test_known_default_ignored(self):
        with (
            patch.dict(os.environ, {"CASHPILOT_SECRET_KEY": "changeme"}),
            patch("app.auth.Path") as mock_path_cls,
        ):
            mock_data_dir = MagicMock()
            mock_key_file = MagicMock()
            mock_key_file.is_file.return_value = False
            mock_data_dir.__truediv__ = MagicMock(return_value=mock_key_file)
            mock_path_cls.return_value = mock_data_dir
            result = auth._resolve_secret_key()
            # Should generate a new key, not return "changeme"
            assert result != "changeme"

    def test_reads_persisted_key(self, tmp_path):
        key_file = tmp_path / ".secret_key"
        key_file.write_text("persisted-secret-key")
        with (
            patch.dict(os.environ, {"CASHPILOT_SECRET_KEY": "", "CASHPILOT_DATA_DIR": str(tmp_path)}),
        ):
            result = auth._resolve_secret_key()
            assert result == "persisted-secret-key"

    def test_generates_and_persists_key(self, tmp_path):
        with (
            patch.dict(os.environ, {"CASHPILOT_SECRET_KEY": "", "CASHPILOT_DATA_DIR": str(tmp_path)}),
        ):
            result = auth._resolve_secret_key()
            assert len(result) > 20
            assert (tmp_path / ".secret_key").read_text().strip() == result
