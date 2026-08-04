"""Can a brand-new user actually install CashPilot?

Nothing in this suite answered that. Every other test creates its owner by
calling ``database.create_user`` directly, so the real first-boot path — land on
``/onboarding``, fill the form, press Create Account — had never once been
exercised end to end. It did not work.

``/register`` requires the one-time setup token on first run
(``deps._require_first_run_access``). ``onboarding.html`` — which is where a
fresh install redirects you — had no field for it and never sent it, so every
new installation answered the form with a 403 and the message "Registration
failed. Please try again." Trying again did the same thing, forever.

Shipped that way: ``git show v1.10.1:app/templates/onboarding.html`` contains no
``setup_token`` at all. The gate landed in PR #100 and the page it gates was
never updated. Existing installs were unaffected, which is exactly why it
survived — the people who could have noticed already had accounts.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ONBOARDING = ROOT / "app" / "templates" / "onboarding.html"


class TestTheOwnerAccountCanBeCreatedFromTheDefaultLandingPage:
    def test_the_form_asks_for_the_setup_token(self):
        html = ONBOARDING.read_text(encoding="utf-8")
        assert 'id="setup_token"' in html, "the page a fresh install lands on cannot create an account"

    def test_the_field_is_required(self):
        """Submitting without it is a guaranteed 403, so the browser should say so first."""
        html = ONBOARDING.read_text(encoding="utf-8")
        field = html[html.index('id="setup_token"') - 200 : html.index('id="setup_token"') + 200]
        assert "required" in field

    def test_the_token_is_actually_sent(self):
        """A field the submit handler ignores is decoration."""
        html = ONBOARDING.read_text(encoding="utf-8")
        assert "formData.append('setup_token'" in html

    def test_the_page_says_where_to_find_the_token(self):
        """It is printed once, to the container logs. Nobody guesses that."""
        html = ONBOARDING.read_text(encoding="utf-8")
        assert "docker logs" in html

    def test_a_403_explains_itself_rather_than_saying_try_again(self):
        """ "Please try again" is the worst possible message here.

        Retrying with the same empty token fails identically and forever, which
        is precisely what a new user experienced.
        """
        html = ONBOARDING.read_text(encoding="utf-8")
        assert "resp.status === 403" in html
        assert "setup token" in html.lower()


class TestTheGateItselfStillHolds:
    """Fixing the form must not have opened the door."""

    REAL_TOKEN = "the-real-one-time-token"

    def _register(self, tmp_path, token, existing_user=False):
        import asyncio
        from unittest.mock import MagicMock, patch

        from fastapi import HTTPException

        from app import database, setup_token
        from app.routers import auth as auth_router

        async def run():
            with (
                patch.object(database, "DB_DIR", tmp_path),
                patch.object(database, "DB_PATH", tmp_path / "fb.db"),
            ):
                await database.init_db()
                # conftest clears the module global before every test, and
                # verify() returns True when NO token is active ("nothing to
                # enforce"). Without arming it here the gate is not under test
                # at all — the first version of this test passed a bad token
                # and was told "allowed", which looked like a security hole and
                # was really just an unarmed fixture.
                setup_token.set_active(self.REAL_TOKEN)
                if existing_user:
                    from app import auth as auth_module

                    await database.create_user("someone", auth_module.hash_password("x" * 12), role="owner")
                request = MagicMock()
                request.session = {}
                request.headers = {}
                request.cookies = {}
                request.client = MagicMock(host="127.0.0.1")
                try:
                    await auth_router.do_register(
                        request,
                        username="newowner",
                        password="A-real-passphrase-123",
                        password_confirm="A-real-passphrase-123",
                        setup_token=token,
                    )
                    return "allowed"
                except HTTPException as exc:
                    return exc.status_code

        return asyncio.run(run())

    def test_registration_without_a_token_is_still_refused(self, tmp_path):
        assert self._register(tmp_path, "") == 403

    def test_a_wrong_token_is_still_refused(self, tmp_path):
        assert self._register(tmp_path, "not-the-real-token") == 403

    def test_the_right_token_is_accepted(self, tmp_path):
        """Otherwise the two tests above would pass with the gate welded shut."""
        assert self._register(tmp_path, self.REAL_TOKEN) == "allowed"


class TestTheTokenIsDiscoverable:
    """The gate is only usable if the token can be found."""

    def test_it_is_logged_at_startup_with_a_findable_phrase(self):
        source = (ROOT / "app" / "setup_token.py").read_text(encoding="utf-8")
        assert re.search(r"[Ss]etup token", source), "nothing tells the operator the token exists"

    def test_the_page_and_the_log_use_the_same_words(self):
        """The user greps the logs for what the page told them to look for."""
        page = ONBOARDING.read_text(encoding="utf-8").lower()
        source = (ROOT / "app" / "setup_token.py").read_text(encoding="utf-8").lower()
        assert "owner account" in source
        assert "owner account" in page, "the page quotes a log line that does not exist"
