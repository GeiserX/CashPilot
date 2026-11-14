"""The optional sign-in CAPTCHA (app/captcha.py, POST /login, the login CSP).

The provider is reached through httpx.MockTransport, so the real request
building, status handling and JSON parsing run. The routes run against a real
SQLite database and real bcrypt, the way tests/test_login_hardening.py does.

The keys below are the providers' own public test keys.
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app import auth, captcha, database, metrics
from app import login_rate_limit as rl
from app.main import _content_security_policy, app

OWNER_PW = "owner-password-1"

TURNSTILE_SITE = "1x00000000000000000000AA"
TURNSTILE_PASS = "1x0000000000000000000000000000000AA"
TURNSTILE_FAIL = "2x0000000000000000000000000000000AA"
HCAPTCHA_SITE = "10000000-ffff-ffff-ffff-000000000001"
HCAPTCHA_SECRET = "0x0000000000000000000000000000000000000000"
RECAPTCHA_SITE = "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"
RECAPTCHA_SECRET = "6LeIxAcTAAAAAGG-vFI1TnRWxMZNFuojJ4WifJWe"

KEYS = {
    "turnstile": (TURNSTILE_SITE, TURNSTILE_PASS),
    "hcaptcha": (HCAPTCHA_SITE, HCAPTCHA_SECRET),
    "recaptcha": (RECAPTCHA_SITE, RECAPTCHA_SECRET),
}

ENV_VARS = ("CASHPILOT_CAPTCHA_PROVIDER", "CASHPILOT_CAPTCHA_SITE_KEY", "CASHPILOT_CAPTCHA_SECRET_KEY")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _captcha_off(monkeypatch):
    """Every test starts with the CAPTCHA off and no CAPTCHA variables set.

    monkeypatch restores the module state afterwards, so nothing leaks into
    the rest of the suite.
    """
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(captcha, "_config", None)
    monkeypatch.setattr(captcha, "_config_error", None)


def _turn_on(monkeypatch, provider: str = "turnstile", secret: str | None = None) -> captcha.Config:
    site, default_secret = KEYS[provider]
    cfg = captcha.Config(provider=captcha.PROVIDERS[provider], site_key=site, secret_key=secret or default_secret)
    monkeypatch.setattr(captcha, "_config", cfg)
    return cfg


class _Provider:
    """A fake siteverify endpoint that records what it was sent."""

    def __init__(self, handler=None):
        self.requests: list[httpx.Request] = []
        self._handler = handler or (lambda request: httpx.Response(200, json={"success": True}))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)

    def form(self, i: int = 0) -> dict[str, str]:
        return dict(urllib.parse.parse_qsl(self.requests[i].content.decode()))

    def install(self, monkeypatch) -> _Provider:
        monkeypatch.setattr(
            captcha, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(self), timeout=1)
        )
        return self


def _turnstile_like(request: httpx.Request) -> httpx.Response:
    """Answers like Turnstile does for its pass and fail test secrets."""
    form = dict(urllib.parse.parse_qsl(request.content.decode()))
    if form.get("secret") == TURNSTILE_PASS:
        return httpx.Response(200, json={"success": True, "error-codes": []})
    return httpx.Response(200, json={"success": False, "error-codes": ["invalid-input-response"]})


def _no_network(monkeypatch) -> None:
    def _boom():
        raise AssertionError("siteverify must not be called")

    monkeypatch.setattr(captcha, "_client", _boom)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_DIR", tmp_path)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "t.db")

    async def _init():
        await database.init_db()
        await database.create_user("owner1", auth.hash_password(OWNER_PW), "owner")

    asyncio.run(_init())
    rl._login_attempts.clear()
    yield
    rl._login_attempts.clear()


def _client() -> TestClient:
    # Not entered as a context manager: the lifespan does not matter to per-request auth.
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


def _login(c: TestClient, password: str = OWNER_PW, **extra: str) -> httpx.Response:
    return c.post("/login", data={"username": "owner1", "password": password, **extra})


def _directive(csp: str, name: str) -> str:
    for part in csp.split(";"):
        part = part.strip()
        if part.split(" ", 1)[0] == name:
            return part
    return ""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestConfig:
    def test_unset_is_off(self):
        assert captcha.load_config() is None

    def test_empty_is_off(self, monkeypatch):
        monkeypatch.setenv("CASHPILOT_CAPTCHA_PROVIDER", "  ")
        monkeypatch.setenv("CASHPILOT_CAPTCHA_SITE_KEY", "ignored")
        assert captcha.load_config() is None

    @pytest.mark.parametrize("name", sorted(KEYS))
    def test_each_provider_loads(self, monkeypatch, name):
        site, secret = KEYS[name]
        monkeypatch.setenv("CASHPILOT_CAPTCHA_PROVIDER", name.upper())
        monkeypatch.setenv("CASHPILOT_CAPTCHA_SITE_KEY", site)
        monkeypatch.setenv("CASHPILOT_CAPTCHA_SECRET_KEY", secret)
        cfg = captcha.load_config()
        assert cfg is not None
        assert cfg.provider is captcha.PROVIDERS[name]
        assert (cfg.site_key, cfg.secret_key) == (site, secret)

    def test_an_unknown_provider_names_the_variable(self, monkeypatch):
        monkeypatch.setenv("CASHPILOT_CAPTCHA_PROVIDER", "recaptcha-v3")
        with pytest.raises(captcha.CaptchaConfigError, match="CASHPILOT_CAPTCHA_PROVIDER"):
            captcha.load_config()

    @pytest.mark.parametrize(
        ("site", "secret", "missing"),
        [
            ("", TURNSTILE_PASS, ["CASHPILOT_CAPTCHA_SITE_KEY"]),
            (TURNSTILE_SITE, "", ["CASHPILOT_CAPTCHA_SECRET_KEY"]),
            ("", "", ["CASHPILOT_CAPTCHA_SITE_KEY", "CASHPILOT_CAPTCHA_SECRET_KEY"]),
        ],
    )
    def test_a_missing_key_names_the_variable(self, monkeypatch, site, secret, missing):
        monkeypatch.setenv("CASHPILOT_CAPTCHA_PROVIDER", "turnstile")
        monkeypatch.setenv("CASHPILOT_CAPTCHA_SITE_KEY", site)
        monkeypatch.setenv("CASHPILOT_CAPTCHA_SECRET_KEY", secret)
        with pytest.raises(captcha.CaptchaConfigError) as exc:
            captcha.load_config()
        for var in missing:
            assert var in str(exc.value)

    def test_a_broken_setting_is_still_required(self, monkeypatch):
        """Broken is never off: sign-in must refuse rather than skip the check."""
        monkeypatch.setenv("CASHPILOT_CAPTCHA_PROVIDER", "turnstile")
        captcha.configure()
        assert captcha.config() is None
        assert captcha.required()

    def test_off_is_not_required(self):
        captcha.configure()
        assert not captcha.required()


class TestStartup:
    def test_a_broken_setting_refuses_to_start(self, monkeypatch):
        monkeypatch.setenv("CASHPILOT_CAPTCHA_PROVIDER", "turnstile")
        monkeypatch.setenv("CASHPILOT_CAPTCHA_SITE_KEY", TURNSTILE_SITE)
        captcha.configure()
        with pytest.raises(RuntimeError, match="CASHPILOT_CAPTCHA_SECRET_KEY"):
            captcha.check_startup()

    def test_the_app_lifespan_refuses_to_start(self, monkeypatch):
        """The real lifespan raises before it touches the database.

        Called directly, not through TestClient: several test modules swap
        app.router.lifespan_context for a no-op at import time.
        """
        import app.main as main_mod

        monkeypatch.setenv("CASHPILOT_CAPTCHA_PROVIDER", "friendlycaptcha")
        captcha.configure()
        init_db = AsyncMock()

        async def _start():
            async with main_mod.lifespan(main_mod.app):
                pass

        with (
            patch("app.main.database.init_db", init_db),
            pytest.raises(RuntimeError, match="CASHPILOT_CAPTCHA_PROVIDER"),
        ):
            asyncio.run(_start())
        init_db.assert_not_awaited()

    def test_on_logs_one_line_naming_the_provider_and_no_key(self, monkeypatch, caplog):
        monkeypatch.setenv("CASHPILOT_CAPTCHA_PROVIDER", "turnstile")
        monkeypatch.setenv("CASHPILOT_CAPTCHA_SITE_KEY", TURNSTILE_SITE)
        monkeypatch.setenv("CASHPILOT_CAPTCHA_SECRET_KEY", TURNSTILE_PASS)
        captcha.configure()
        with caplog.at_level(logging.INFO, logger="app.captcha"):
            captcha.check_startup()
        lines = [r.getMessage() for r in caplog.records if r.name == "app.captcha"]
        assert lines == ["Sign-in CAPTCHA is on: Cloudflare Turnstile."]

    def test_off_logs_nothing(self, caplog):
        captcha.configure()
        with caplog.at_level(logging.INFO, logger="app.captcha"):
            captcha.check_startup()
        assert not [r for r in caplog.records if r.name == "app.captcha"]


# ---------------------------------------------------------------------------
# verify()
# ---------------------------------------------------------------------------


class TestVerify:
    @pytest.mark.parametrize("token", [None, "", "   "])
    def test_no_token_fails_without_a_network_call(self, monkeypatch, token):
        _turn_on(monkeypatch)
        _no_network(monkeypatch)
        assert asyncio.run(captcha.verify(token, "203.0.113.9")) == captcha.Result(False, "missing")

    def test_off_fails_closed(self, monkeypatch):
        _no_network(monkeypatch)
        assert asyncio.run(captcha.verify("tok", None)) == captcha.Result(False, "unavailable")

    @pytest.mark.parametrize("name", sorted(KEYS))
    def test_success_posts_the_form_to_the_providers_endpoint(self, monkeypatch, name):
        cfg = _turn_on(monkeypatch, name)
        fake = _Provider().install(monkeypatch)
        assert asyncio.run(captcha.verify("tok-123", "203.0.113.9")) == captcha.Result(True, "ok")
        assert str(fake.requests[0].url) == cfg.provider.verify_url
        assert fake.requests[0].method == "POST"
        expected = {"secret": cfg.secret_key, "response": "tok-123", "remoteip": "203.0.113.9"}
        if name == "hcaptcha":
            # hCaptcha secrets are account-wide; the sitekey pins the token to this site.
            expected["sitekey"] = cfg.site_key
        assert fake.form() == expected

    @pytest.mark.parametrize("remote_ip", [None, "", "testclient", "unknown"])
    def test_remoteip_is_sent_only_when_it_is_an_address(self, monkeypatch, remote_ip):
        _turn_on(monkeypatch)
        fake = _Provider().install(monkeypatch)
        asyncio.run(captcha.verify("tok", remote_ip))
        assert "remoteip" not in fake.form()

    def test_the_fail_secret_is_rejected_and_logs_codes_not_secrets(self, monkeypatch, caplog):
        _turn_on(monkeypatch, secret=TURNSTILE_FAIL)
        _Provider(_turnstile_like).install(monkeypatch)
        with caplog.at_level(logging.INFO, logger="app.captcha"):
            result = asyncio.run(captcha.verify("secret-token-value", "203.0.113.9"))
        assert result == captcha.Result(False, "rejected")
        logged = caplog.text
        assert "invalid-input-response" in logged
        assert "secret-token-value" not in logged
        assert TURNSTILE_FAIL not in logged

    @pytest.mark.parametrize(
        "body",
        [
            {"success": "true"},
            {"success": 1},
            {"error-codes": []},
            {},
        ],
    )
    def test_only_a_literal_true_passes(self, monkeypatch, body):
        _turn_on(monkeypatch)
        _Provider(lambda r: httpx.Response(200, json=body)).install(monkeypatch)
        assert asyncio.run(captcha.verify("tok", None)) == captcha.Result(False, "rejected")

    @pytest.mark.parametrize(
        "handler",
        [
            lambda r: httpx.Response(500, json={"success": True}),
            lambda r: httpx.Response(403, text="forbidden"),
            lambda r: httpx.Response(200, text="<html>not json</html>"),
            lambda r: httpx.Response(200, json=[True]),
        ],
        ids=["http-500", "http-403", "not-json", "json-list"],
    )
    def test_a_bad_answer_fails_closed(self, monkeypatch, handler):
        _turn_on(monkeypatch)
        _Provider(handler).install(monkeypatch)
        assert asyncio.run(captcha.verify("tok", None)) == captcha.Result(False, "unavailable")

    @pytest.mark.parametrize("exc", [httpx.ConnectError("down"), httpx.ReadTimeout("slow")], ids=["connect", "timeout"])
    def test_an_unreachable_provider_fails_closed(self, monkeypatch, exc):
        _turn_on(monkeypatch)

        def _raise(request):
            raise exc

        _Provider(_raise).install(monkeypatch)
        assert asyncio.run(captcha.verify("tok", None)) == captcha.Result(False, "unavailable")

    def test_the_real_client_has_a_short_timeout(self):
        async def _timeout():
            async with captcha._client() as client:
                return client.timeout

        timeout = asyncio.run(_timeout())
        assert timeout.connect == timeout.read == captcha.VERIFY_TIMEOUT_SECONDS <= 10


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------


class TestLoginRoute:
    def test_off_the_flow_is_unchanged(self, db, monkeypatch):
        _no_network(monkeypatch)
        c = _client()
        page = c.get("/login")
        assert page.status_code == 200
        assert "cp-captcha" not in page.text
        assert _login(c, "wrong").status_code == 401
        assert _login(c).status_code == 303

    def test_no_token_is_400_with_no_network_call_and_no_bcrypt(self, db, monkeypatch):
        _turn_on(monkeypatch)
        _no_network(monkeypatch)
        bcrypt = AsyncMock(return_value=True)
        with patch.object(auth, "verify_password_async", bcrypt):
            resp = _login(_client())
        assert resp.status_code == 400
        assert "Complete the CAPTCHA check and try again." in resp.text
        bcrypt.assert_not_awaited()

    def test_a_failing_check_is_400_and_never_reaches_bcrypt(self, db, monkeypatch):
        _turn_on(monkeypatch, secret=TURNSTILE_FAIL)
        fake = _Provider(_turnstile_like).install(monkeypatch)
        bcrypt = AsyncMock(return_value=True)
        with patch.object(auth, "verify_password_async", bcrypt):
            resp = _login(_client(), **{"cf-turnstile-response": "XXXX.DUMMY.TOKEN.XXXX"})
        assert resp.status_code == 400
        assert "Complete the CAPTCHA check and try again." in resp.text
        assert len(fake.requests) == 1
        assert fake.form()["response"] == "XXXX.DUMMY.TOKEN.XXXX"
        bcrypt.assert_not_awaited()

    def test_a_passing_check_goes_on_to_the_password(self, db, monkeypatch):
        _turn_on(monkeypatch)
        _Provider(_turnstile_like).install(monkeypatch)
        c = _client()
        token = {"cf-turnstile-response": "XXXX.DUMMY.TOKEN.XXXX"}
        wrong = _login(c, "wrong", **token)
        assert wrong.status_code == 401
        assert "Invalid username or password" in wrong.text
        ok = _login(c, **token)
        assert ok.status_code == 303
        assert ok.headers["location"] == "/"

    @pytest.mark.parametrize("name", sorted(KEYS))
    def test_each_provider_reads_its_own_field(self, db, monkeypatch, name):
        cfg = _turn_on(monkeypatch, name)
        fake = _Provider().install(monkeypatch)
        c = _client()
        # Another provider's field is not this provider's token.
        other = next(p.response_field for p in captcha.PROVIDERS.values() if p is not cfg.provider)
        assert _login(c, **{other: "tok"}).status_code == 400
        assert not fake.requests
        assert _login(c, **{cfg.provider.response_field: "tok"}).status_code == 303

    def test_an_unreachable_provider_says_so(self, db, monkeypatch):
        _turn_on(monkeypatch)

        def _down(request):
            raise httpx.ConnectError("down")

        _Provider(_down).install(monkeypatch)
        resp = _login(_client(), **{"cf-turnstile-response": "tok"})
        assert resp.status_code == 400
        assert "could not be completed" in resp.text
        assert "Complete the CAPTCHA check and try again." not in resp.text

    def test_a_broken_setting_refuses_sign_in(self, db, monkeypatch):
        """If a request ever arrives despite the startup refusal, it fails closed."""
        monkeypatch.setattr(captcha, "_config_error", "CASHPILOT_CAPTCHA_SECRET_KEY is not set")
        _no_network(monkeypatch)
        resp = _login(_client(), **{"cf-turnstile-response": "tok"})
        assert resp.status_code == 400
        assert "could not be completed" in resp.text

    def test_a_failure_counts_as_an_attempt(self, db, monkeypatch):
        _turn_on(monkeypatch)
        _no_network(monkeypatch)
        c = _client()
        for _ in range(rl.MAX_ATTEMPTS):
            assert _login(c).status_code == 400
        assert _login(c).status_code == 429

    def test_the_rate_limit_comes_before_the_provider(self, db, monkeypatch):
        _turn_on(monkeypatch)
        fake = _Provider(_turnstile_like).install(monkeypatch)
        c = _client()
        for _ in range(rl.MAX_ATTEMPTS):
            _login(c, "wrong", **{"cf-turnstile-response": "tok"})
        sent = len(fake.requests)
        assert _login(c, "wrong", **{"cf-turnstile-response": "tok"}).status_code == 429
        assert len(fake.requests) == sent

    def test_the_rerendered_page_shows_the_widget_again(self, db, monkeypatch):
        _turn_on(monkeypatch)
        _no_network(monkeypatch)
        resp = _login(_client())
        assert resp.status_code == 400
        assert f'data-sitekey="{TURNSTILE_SITE}"' in resp.text
        assert "https://challenges.cloudflare.com" in _directive(resp.headers["content-security-policy"], "frame-src")

    def test_a_failure_is_counted_in_metrics(self, db, monkeypatch):
        _turn_on(monkeypatch)
        _no_network(monkeypatch)
        with (
            patch.object(metrics, "record_login") as record_login,
            patch.object(metrics, "record_captcha_failure") as record_captcha,
        ):
            _login(_client())
        record_login.assert_called_once_with(success=False)
        record_captcha.assert_called_once_with("missing")


class TestCaptchaMetric:
    @pytest.fixture(autouse=True)
    def _metrics_on(self, monkeypatch):
        pytest.importorskip("prometheus_client")
        # monkeypatch puts the registry and the metric map back afterwards.
        monkeypatch.setattr(metrics, "METRICS_ENABLED", True)
        monkeypatch.setattr(metrics, "_registry", metrics._registry)
        monkeypatch.setattr(metrics, "_metrics", metrics._metrics.copy())
        metrics._init_metrics()

    def test_record_captcha_failure(self):
        metrics.record_captcha_failure("rejected")
        metrics.record_captcha_failure("rejected")
        metrics.record_captcha_failure("unavailable")
        counter = metrics._metrics["login_captcha_failed_total"]
        assert counter.labels(reason="rejected")._value.get() == 2
        assert counter.labels(reason="unavailable")._value.get() == 1


# ---------------------------------------------------------------------------
# The page and its CSP
# ---------------------------------------------------------------------------


class TestLoginPage:
    @pytest.mark.parametrize("name", sorted(KEYS))
    def test_the_widget_and_script_render(self, db, monkeypatch, name):
        cfg = _turn_on(monkeypatch, name)
        resp = _client().get("/login")
        assert resp.status_code == 200
        html = resp.text
        nonce = re.search(r"'nonce-([^']+)'", resp.headers["content-security-policy"]).group(1)
        widget = re.search(r'<div id="cp-captcha"[^>]*>', html).group(0)
        assert f'class="{cfg.provider.widget_class}"' in widget
        assert f'data-sitekey="{cfg.site_key}"' in widget
        assert 'data-theme="dark"' in widget
        assert cfg.secret_key not in html
        script = re.search(rf'<script src="{re.escape(cfg.provider.script_url)}"[^>]*>', html).group(0)
        assert f'nonce="{nonce}"' in script
        assert "async" in script
        assert "defer" in script
        # Inside the form, before the submit button.
        form = html[html.index("<form") : html.index("</form>")]
        assert form.index('id="cp-captcha"') < form.index('type="submit"')
        # No inline event handlers, and every inline script carries the nonce.
        assert not re.search(r"\son[a-z]+=", html)
        for tag in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html):
            assert f'nonce="{nonce}"' in tag

    def test_the_register_page_has_no_widget(self, monkeypatch):
        _turn_on(monkeypatch)
        with (
            patch("app.database.has_any_users", new_callable=AsyncMock, return_value=True),
            patch("app.auth.get_current_user", return_value={"uid": 1, "u": "o", "r": "owner"}),
        ):
            resp = _client().get("/register")
        assert resp.status_code == 200
        assert "cp-captcha" not in resp.text
        assert "challenges.cloudflare.com" not in resp.headers["content-security-policy"]


class TestCsp:
    def test_off_the_policy_is_the_global_one(self):
        assert _content_security_policy("N") == (
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net/npm/chart.js@4.4.8/dist/chart.umd.min.js 'nonce-N'; "
            "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'none'; "
            "object-src 'none'; "
            "form-action 'self'"
        )

    def test_off_the_login_page_gets_the_global_policy(self, db):
        resp = _client().get("/login")
        nonce = re.search(r"'nonce-([^']+)'", resp.headers["content-security-policy"]).group(1)
        assert resp.headers["content-security-policy"] == _content_security_policy(nonce)

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            (
                "turnstile",
                {
                    "script-src": ["https://challenges.cloudflare.com"],
                    "frame-src": ["https://challenges.cloudflare.com"],
                },
            ),
            (
                "hcaptcha",
                {
                    d: ["https://hcaptcha.com", "https://*.hcaptcha.com"]
                    for d in ("script-src", "frame-src", "style-src", "connect-src")
                },
            ),
            (
                "recaptcha",
                {
                    "script-src": ["https://www.google.com/recaptcha/", "https://www.gstatic.com/recaptcha/"],
                    "frame-src": ["https://www.google.com/recaptcha/", "https://recaptcha.google.com/recaptcha/"],
                    "connect-src": ["https://www.google.com/recaptcha/"],
                },
            ),
        ],
    )
    def test_on_the_login_page_adds_exactly_the_providers_origins(self, db, monkeypatch, name, expected):
        _turn_on(monkeypatch, name)
        resp = _client().get("/login")
        csp = resp.headers["content-security-policy"]
        nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
        base = _content_security_policy(nonce)
        for directive in ("script-src", "style-src", "connect-src", "frame-src"):
            got = _directive(csp, directive).split()[1:]
            before = _directive(base, directive).split()[1:] or (["'self'"] if directive == "frame-src" else [])
            added = expected.get(directive, [])
            if not added and directive == "frame-src":
                assert got == []
                continue
            assert got == before + added, directive
        # Nothing else moved.
        others = ("default-src", "font-src", "img-src", "frame-ancestors", "base-uri", "object-src", "form-action")
        for directive in others:
            assert _directive(csp, directive) == _directive(base, directive)

    def test_on_other_pages_keep_the_global_policy(self, db, monkeypatch):
        _turn_on(monkeypatch)
        c = _client()
        for path in ("/onboarding", "/static/js/delegate.js", "/api/health"):
            resp = c.get(path)
            csp = resp.headers.get("content-security-policy", "")
            assert "challenges.cloudflare.com" not in csp, path
            assert "frame-src" not in csp, path

    def test_on_the_signed_in_redirect_keeps_the_global_policy(self, db, monkeypatch):
        _turn_on(monkeypatch)
        with patch("app.auth.get_current_user", return_value={"uid": 1, "u": "owner1", "r": "owner"}):
            resp = _client().get("/login")
        assert resp.status_code == 303
        assert "challenges.cloudflare.com" not in resp.headers["content-security-policy"]
