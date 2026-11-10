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

    def test_a_public_client_does_not_arm_a_token(self, client):
        """The network check runs first, so the internet cannot fill the log with tokens."""
        setup_token.clear()
        with (
            patch("app.main.auth.get_current_user", return_value=None),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
            patch("app.main.database.set_config", new_callable=AsyncMock) as set_cfg,
            patch("app.deps.client_ip", return_value="8.8.8.8"),
        ):
            resp = client.post("/register", data=_FORM, follow_redirects=False)
        assert resp.status_code == 403
        assert setup_token.active() is None
        set_cfg.assert_not_called()

    def test_a_failed_save_leaves_no_unlogged_token(self, client, caplog):
        """A token that was never logged must not stay active, or setup stays blocked."""
        setup_token.clear()
        with (
            patch("app.main.auth.get_current_user", return_value=None),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=False),
            patch(
                "app.main.database.set_config",
                new_callable=AsyncMock,
                side_effect=[Exception("database is locked"), None],
            ),
            caplog.at_level(logging.WARNING),
        ):
            first = client.post("/register", data=_FORM, follow_redirects=False)
            assert first.status_code == 500
            assert setup_token.active() is None
            second = client.post("/register", data=_FORM, follow_redirects=False)
        assert second.status_code == 403
        tok = setup_token.active()
        assert tok and tok in caplog.text

    def test_an_owner_created_meanwhile_arms_no_token(self, client, caplog):
        """Another request created the owner while this one was arming a token."""
        setup_token.clear()
        with (
            patch("app.main.auth.get_current_user", return_value=None),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, side_effect=[False, True]),
            patch("app.main.database.set_config", new_callable=AsyncMock),
            patch("app.main.database.delete_config_keys", new_callable=AsyncMock) as delete_keys,
            patch("app.main.database.create_first_owner", new_callable=AsyncMock) as create,
            caplog.at_level(logging.WARNING),
        ):
            resp = client.post("/register", data=_FORM, follow_redirects=False)
        assert resp.status_code == 409
        create.assert_not_called()
        assert setup_token.active() is None
        delete_keys.assert_awaited_once_with(["_setup_token"])
        assert "FIRST-RUN SETUP" not in caplog.text


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


class TestLoginPage:
    def _login_html(self, client):
        with (
            patch("app.main.auth.get_current_user", return_value=None),
            patch("app.main.database.has_any_users", new_callable=AsyncMock, return_value=True),
        ):
            resp = client.get("/login")
        assert resp.status_code == 200
        return resp.text

    def test_no_dead_sign_up_link(self, client):
        html = self._login_html(client)
        assert 'href="/register"' not in html
        assert "No account?" not in html

    def test_names_the_recovery_command_and_the_faq(self, client):
        html = self._login_html(client)
        assert "Forgot your password or username?" in html
        assert "python -m app.users reset-password" in html
        assert "Do not delete the data volume" in html
        assert "https://github.com/GeiserX/CashPilot/blob/main/docs/faq.md#forgot-password" in html

    def test_the_faq_anchor_exists(self):
        faq = (ROOT / "docs" / "faq.md").read_text(encoding="utf-8")
        assert '<a id="forgot-password"></a>' in faq
        assert "python -m app.users reset-password" in faq
        assert "python -m app.users rename" in faq

    def test_the_faq_names_the_containers_the_install_files_use(self):
        faq = (ROOT / "docs" / "faq.md").read_text(encoding="utf-8")
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        casaos = (ROOT / "contrib/app-stores/casaos/CashPilot/docker-compose.yml").read_text(encoding="utf-8")
        unraid = (ROOT / "unraid/cashpilot.xml").read_text(encoding="utf-8")
        assert "container_name: cashpilot-ui" in compose and "container_name: cashpilot-ui" in casaos
        assert "<Name>cashpilot</Name>" in unraid
        assert "docker exec -it cashpilot-ui python -m app.users" in faq
        assert "docker exec -it cashpilot python -m app.users" in faq

    def test_security_md_states_there_is_no_in_app_recovery(self):
        sec = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        assert "No in-app password recovery; a reset requires access to the server, by design." in sec
