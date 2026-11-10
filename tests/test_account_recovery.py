"""Issue #721: the web side of account recovery.

* The first-run setup token fails closed. With no users and no active token, a
  first-run request arms a new token, writes it to the log and is refused.
* The cookie re-mint after a password change takes the name from the database.
* The login page points at the recovery command and drops the dead sign-up link.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest
from fastapi.testclient import TestClient

from app import setup_token
from app.main import app

ROOT = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def _noop_lifespan(a):
    yield


@pytest.fixture
def client():
    app.router.lifespan_context = _noop_lifespan
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


_FORM = {"username": "intruder", "password": "password123", "password_confirm": "password123"}


class TestSetupTokenFailsClosed:
    def test_verify_refuses_when_no_token_is_active(self):
        setup_token.clear()
        assert setup_token.verify(None) is False
        assert setup_token.verify("anything") is False

    def test_an_emptied_users_table_rearms_the_token_and_refuses(self, client, caplog):
        """The users table empties while the app runs: no token is active."""
        setup_token.clear()
        with (
            patch("app.main.auth.get_current_user", return_value=None),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
            patch("app.main.database.set_config", new_callable=AsyncMock) as set_cfg,
            patch("app.main.database.create_first_owner", new_callable=AsyncMock, return_value=1) as create,
            caplog.at_level(logging.WARNING),
        ):
            resp = client.post("/register", data=_FORM, follow_redirects=False)
        assert resp.status_code == 403
        assert "A setup token was just written to the container log." in resp.text
        create.assert_not_called()
        tok = setup_token.active()
        assert tok, "no token was armed"
        set_cfg.assert_awaited_once_with("_setup_token", tok)
        assert tok in caplog.text

    def test_the_logged_token_then_works(self, client):
        setup_token.clear()
        with (
            patch("app.main.auth.get_current_user", return_value=None),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
            patch("app.main.database.set_config", new_callable=AsyncMock),
            patch("app.main.database.get_user_by_username", new_callable=AsyncMock, return_value=None),
            patch("app.main.auth.hash_password", return_value="hashed"),
            patch("app.main.database.create_first_owner", new_callable=AsyncMock, return_value=1),
            patch("app.main.database.delete_config_keys", new_callable=AsyncMock),
            patch("app.main.auth.create_session_token", return_value="tok"),
            patch("app.main.auth.set_session_cookie", side_effect=lambda r, t, req=None: r),
        ):
            assert client.post("/register", data=_FORM, follow_redirects=False).status_code == 403
            tok = setup_token.active()
            resp = client.post("/register", data={**_FORM, "setup_token": tok}, follow_redirects=False)
        assert resp.status_code == 303
        assert setup_token.active() is None

    def test_an_active_token_is_not_replaced(self, client):
        setup_token.set_active("the-token")
        with (
            patch("app.main.auth.get_current_user", return_value=None),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
            patch("app.main.database.set_config", new_callable=AsyncMock) as set_cfg,
        ):
            resp = client.post("/register", data=_FORM, follow_redirects=False)
        assert resp.status_code == 403
        assert setup_token.active() == "the-token"
        set_cfg.assert_not_called()


class TestCookieRemintUsesTheStoredName:
    def test_a_renamed_user_gets_the_new_name_in_the_cookie(self, client):
        record = {
            "id": 1,
            "username": "newname",
            "password": "x-mock-hash",
            "role": "owner",
            "password_changed_at": 123.0,
        }
        with (
            patch("app.main.auth.get_current_user", return_value={"uid": 1, "u": "oldname", "r": "owner"}),
            patch("app.main.database.get_user_by_id", new_callable=AsyncMock, return_value=record),
            patch("app.main.auth.verify_password", return_value=True),
            patch("app.main.auth.hash_password", return_value="hashed-new"),
            patch("app.main.database.update_user_password", new_callable=AsyncMock),
            patch("app.main.auth.set_user_pwd_epoch"),
            patch("app.main.auth.create_session_token", return_value="tok") as mint,
            patch("app.main.auth.set_session_cookie", side_effect=lambda r, t, req=None: r),
        ):
            resp = client.post(
                "/api/users/me/password",
                json={"current_password": "oldpassword1", "new_password": "newpassword123"},
            )
        assert resp.status_code == 200
        mint.assert_called_once_with(1, "newname", "owner")
