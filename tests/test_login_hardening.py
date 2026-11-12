"""Login and session hardening: rate limit buckets, username timing, cross-site
requests, server-side logout, and a few small auth bugs.

These run against a real SQLite database and real bcrypt, so the rate limiter,
the session cookie and the revocation path are exercised end to end.
"""

from __future__ import annotations

import asyncio
from time import monotonic
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth, database, main, setup_token
from app import login_rate_limit as rl
from app.main import app

OWNER_PW = "owner-password-1"
VIEWER_PW = "viewer-password-1"


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_DIR", tmp_path)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "t.db")

    async def _init():
        await database.init_db()
        await database.create_user("owner1", auth.hash_password(OWNER_PW), "owner")
        await database.create_user("viewer1", auth.hash_password(VIEWER_PW), "viewer")

    asyncio.run(_init())
    rl._login_attempts.clear()
    yield
    rl._login_attempts.clear()


def _client() -> TestClient:
    # Not entered as a context manager: the lifespan installs signal handlers and
    # starts the scheduler, and none of that matters to per-request auth.
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


def _login(c: TestClient, username: str, password: str) -> int:
    return c.post("/login", data={"username": username, "password": password}).status_code


class TestPerUserBuckets:
    def test_another_accounts_success_does_not_reset_the_owners_counter(self, db):
        """sec-auth-1: a viewer logging in every 4 guesses used to clear the IP bucket."""
        c = _client()
        for _ in range(4):
            assert _login(c, "owner1", "wrong") == 401
        assert _login(c, "viewer1", VIEWER_PW) == 303
        assert _login(c, "owner1", "wrong") == 401  # the 5th guess
        assert _login(c, "owner1", "wrong") == 429

    def test_failures_against_one_account_do_not_lock_out_another(self, db):
        """sec-auth-3: five bad POSTs from a shared IP locked out every user."""
        c = _client()
        for _ in range(rl.MAX_ATTEMPTS):
            _login(c, "nosuchuser", "wrong")
        assert _login(c, "nosuchuser", "wrong") == 429
        assert _login(c, "owner1", OWNER_PW) == 303

    def test_a_success_clears_only_its_own_bucket(self, db):
        c = _client()
        _login(c, "owner1", "wrong")
        _login(c, "viewer1", "wrong")
        assert _login(c, "viewer1", VIEWER_PW) == 303
        assert rl.key_for("testclient", "viewer1") not in rl._login_attempts
        assert len(rl._login_attempts[rl.key_for("testclient", "owner1")]) == 1


class TestConcurrentBurst:
    def test_a_parallel_burst_gets_only_max_attempts_password_checks(self, db):
        """sec-auth-2 / perf-2: the check ran before the await and the count after,
        so a parallel burst all passed the check and each ran bcrypt."""

        async def _burst():
            transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 1234))
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
                return await asyncio.gather(
                    *[ac.post("/login", data={"username": "owner1", "password": "wrong"}) for _ in range(12)]
                )

        codes = sorted(r.status_code for r in asyncio.run(_burst()))
        assert codes.count(401) == rl.MAX_ATTEMPTS
        assert codes.count(429) == 12 - rl.MAX_ATTEMPTS

    def test_reserve_counts_before_the_check_completes(self):
        rl._login_attempts.clear()
        for _ in range(rl.MAX_ATTEMPTS):
            rl.reserve_attempt("k")
        with pytest.raises(HTTPException) as exc:
            rl.reserve_attempt("k")
        assert exc.value.status_code == 429
        rl._login_attempts.clear()


class TestBoundedMemory:
    def test_a_key_that_never_returns_is_swept(self, monkeypatch):
        """The perf audit's missed item: pruning ran only for the key being checked."""
        rl._login_attempts.clear()
        monkeypatch.setattr(rl, "_last_sweep", 0.0)
        rl._login_attempts["gone"] = [monotonic() - (rl.WINDOW_SECONDS + 1)]
        rl.reserve_attempt("someone-else")
        assert "gone" not in rl._login_attempts
        rl._login_attempts.clear()

    def test_the_number_of_buckets_is_capped(self, monkeypatch):
        rl._login_attempts.clear()
        monkeypatch.setattr(rl, "MAX_TRACKED_KEYS", 50)
        for i in range(200):
            rl.reserve_attempt(f"k{i}")
        assert len(rl._login_attempts) <= 50
        assert "k199" in rl._login_attempts
        rl._login_attempts.clear()

    def test_a_huge_username_does_not_make_a_huge_key(self):
        assert len(rl.key_for("1.2.3.4", "x" * 100_000)) < 100


class TestUnknownUserTiming:
    def test_an_unknown_username_still_runs_bcrypt(self, db):
        """sec-auth-4: an unknown name answered ~100x faster than a wrong password."""
        real = auth.verify_password
        with patch("app.auth.verify_password", side_effect=real) as spy:
            assert _login(_client(), "nosuchuser", "whatever") == 401
        assert spy.call_count == 1


class TestCrossSiteRequests:
    def _owner(self) -> TestClient:
        c = _client()
        assert _login(c, "owner1", OWNER_PW) == 303
        return c

    @pytest.mark.parametrize(
        "headers",
        [
            {"Sec-Fetch-Site": "same-site"},
            {"Sec-Fetch-Site": "cross-site"},
            {"Origin": "http://testserver:9999"},
            {"Origin": "null"},
        ],
    )
    def test_a_cookie_request_from_another_site_is_refused(self, db, headers):
        """sec-auth-6: SameSite=Lax still sends the cookie from a same-site page."""
        resp = self._owner().post("/api/collect", headers=headers)
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Cross-site request refused"

    @pytest.mark.parametrize(
        "headers",
        [
            {"Sec-Fetch-Site": "same-origin"},
            {"Origin": "http://testserver"},
            {},  # a non-browser client that kept the cookie
        ],
    )
    def test_a_cookie_request_from_the_ui_itself_passes(self, db, headers):
        resp = self._owner().post("/logout", headers=headers)
        assert resp.status_code == 303

    def test_safe_methods_are_not_checked(self, db):
        resp = self._owner().get("/api/users", headers={"Sec-Fetch-Site": "cross-site"})
        assert resp.status_code == 200

    def test_api_key_callers_without_a_cookie_are_not_checked(self, db, monkeypatch):
        """Desktop, Android, Home Assistant and scripts send a Bearer key and no cookie."""
        monkeypatch.setenv("CASHPILOT_ADMIN_API_KEY", "test-admin-key")
        resp = _client().post(
            "/api/preferences",
            json={"theme": "dark"},
            headers={"Authorization": "Bearer test-admin-key", "Origin": "http://elsewhere"},
        )
        assert resp.status_code != 403

    def test_the_worker_heartbeat_is_not_checked(self, db, monkeypatch):
        monkeypatch.setattr(main, "FLEET_API_KEY", "fleet-key-for-test")
        resp = _client().post(
            "/api/workers/heartbeat",
            json={"name": "w1"},
            headers={"Authorization": "Bearer fleet-key-for-test", "Sec-Fetch-Site": "cross-site"},
        )
        assert resp.status_code != 403


class TestLogout:
    def test_logout_ends_the_session_on_the_server(self, db):
        """sec-auth-7: a copied cookie stayed valid for 30 days after sign-out."""
        c = _client()
        assert _login(c, "owner1", OWNER_PW) == 303
        cookie = c.cookies.get(auth.SESSION_COOKIE)
        assert c.get("/api/users").status_code == 200
        assert c.post("/logout").status_code == 303
        stale = _client()
        stale.cookies.set(auth.SESSION_COOKIE, cookie)
        assert stale.get("/api/users").status_code == 401

    def test_logout_is_not_a_get(self, db):
        """A GET let any cross-site link sign the user out."""
        assert _client().get("/logout").status_code == 405

    def test_a_new_login_after_logout_works(self, db):
        c = _client()
        _login(c, "owner1", OWNER_PW)
        c.post("/logout")
        assert _login(c, "owner1", OWNER_PW) == 303
        assert c.get("/api/users").status_code == 200


class TestSmallAuthBugs:
    def test_adding_a_user_lands_on_a_page_that_exists(self, db):
        """sec-auth-9: the redirect pointed at /users, which is a 404."""
        c = _client()
        _login(c, "owner1", OWNER_PW)
        resp = c.post(
            "/register",
            data={"username": "newuser", "password": "long-password-1", "password_confirm": "long-password-1"},
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/settings"
        assert c.get("/settings").status_code == 200

    def test_preferences_with_an_api_key_is_a_400_not_a_500(self, db, monkeypatch):
        """sec-auth-10: uid 0 failed the users foreign key."""
        monkeypatch.setenv("CASHPILOT_ADMIN_API_KEY", "test-admin-key")
        resp = _client().post(
            "/api/preferences", json={"theme": "dark"}, headers={"Authorization": "Bearer test-admin-key"}
        )
        assert resp.status_code == 400

    @pytest.mark.parametrize("path", ["/login", "/register"])
    def test_the_error_query_parameter_is_not_shown(self, db, path, monkeypatch):
        """sec-auth-11: ?error= put attacker-chosen text on the real sign-in page."""
        c = _client()
        if path == "/register":
            _login(c, "owner1", OWNER_PW)
        resp = c.get(f"{path}?error=Session+expired+call+support+555")
        assert resp.status_code == 200
        assert "call support 555" not in resp.text

    def test_a_non_ascii_setup_token_is_refused_not_a_crash(self, monkeypatch):
        """The audit's missed item: compare_digest on str raises for non-ASCII."""
        monkeypatch.setattr(setup_token, "_active", "abc")
        assert setup_token.verify("ñandú") is False
        assert setup_token.verify("abc") is True


class TestContentSecurityPolicy:
    def test_script_src_names_only_the_chart_js_file(self, db):
        """sec-auth-8 / sec-data-3: the whole jsdelivr host is a known CSP bypass."""
        csp = _client().get("/login").headers["content-security-policy"]
        directives = {d.split()[0]: d.split()[1:] for d in csp.split("; ") if d}
        assert "https://cdn.jsdelivr.net" not in directives["script-src"]
        assert main._CHART_JS_URL in directives["script-src"]
        assert directives["connect-src"] == ["'self'"]

    def test_the_csp_path_matches_the_script_the_page_loads(self):
        """If base.html moves to another chart.js version the CSP must follow."""
        from pathlib import Path

        base = (Path(main.__file__).parent / "templates" / "base.html").read_text(encoding="utf-8")
        assert f'src="{main._CHART_JS_URL}"' in base
