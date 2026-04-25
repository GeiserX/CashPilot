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

    def test_fleet_key_returns_writer(self):
        with patch("app.auth._fleet_key_mod.resolve_fleet_key", return_value="fleet-secret"):
            req = self._make_request(headers={"Authorization": "Bearer fleet-secret"})
            user = auth.get_current_user(req)
            assert user is not None
            assert user["r"] == "writer"

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
