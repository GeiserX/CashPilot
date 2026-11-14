"""Optional CAPTCHA on the sign-in page.

Off unless ``CASHPILOT_CAPTCHA_PROVIDER`` names a provider. Then the login page
shows that provider's widget, its CSP grows by exactly that provider's origins,
and ``POST /login`` asks the provider to confirm the token before it checks the
password.

Three providers are supported, all of the "visible widget, server checks the
token" kind: Cloudflare Turnstile, hCaptcha and Google reCAPTCHA v2 (the
checkbox). reCAPTCHA v3 is score-based, needs a policy for what score is good
enough, and is not supported.

A provider with a key missing, or a provider we do not know, is a startup error
(``check_startup``), never a silent fallback to no CAPTCHA: the operator asked
for one. Every failure while checking a token fails closed.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

#: How long one siteverify call may take. The user is waiting on the sign-in page.
VERIFY_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class Provider:
    name: str
    label: str
    #: The widget script, loaded with ``async defer``.
    script_url: str
    #: The CSS class the script looks for to render the widget.
    widget_class: str
    #: The form field the widget fills with the token.
    response_field: str
    verify_url: str
    #: Origins to add to each CSP directive, from each provider's own CSP docs.
    csp: dict[str, tuple[str, ...]]
    #: Send ``sitekey`` to siteverify. hCaptcha secrets cover the whole account,
    #: so without it a token solved on another of the account's sites passes here.
    send_sitekey: bool = False


_HCAPTCHA_ORIGINS = ("https://hcaptcha.com", "https://*.hcaptcha.com")

PROVIDERS: dict[str, Provider] = {
    "turnstile": Provider(
        name="turnstile",
        label="Cloudflare Turnstile",
        script_url="https://challenges.cloudflare.com/turnstile/v0/api.js",
        widget_class="cf-turnstile",
        response_field="cf-turnstile-response",
        verify_url="https://challenges.cloudflare.com/turnstile/v0/siteverify",
        csp={
            "script-src": ("https://challenges.cloudflare.com",),
            "frame-src": ("https://challenges.cloudflare.com",),
        },
    ),
    "hcaptcha": Provider(
        name="hcaptcha",
        label="hCaptcha",
        script_url="https://js.hcaptcha.com/1/api.js",
        widget_class="h-captcha",
        response_field="h-captcha-response",
        verify_url="https://api.hcaptcha.com/siteverify",
        csp={
            "script-src": _HCAPTCHA_ORIGINS,
            "frame-src": _HCAPTCHA_ORIGINS,
            "style-src": _HCAPTCHA_ORIGINS,
            "connect-src": _HCAPTCHA_ORIGINS,
        },
        send_sitekey=True,
    ),
    "recaptcha": Provider(
        name="recaptcha",
        label="Google reCAPTCHA v2",
        script_url="https://www.google.com/recaptcha/api.js",
        widget_class="g-recaptcha",
        response_field="g-recaptcha-response",
        verify_url="https://www.google.com/recaptcha/api/siteverify",
        csp={
            "script-src": ("https://www.google.com/recaptcha/", "https://www.gstatic.com/recaptcha/"),
            "frame-src": ("https://www.google.com/recaptcha/", "https://recaptcha.google.com/recaptcha/"),
            "connect-src": ("https://www.google.com/recaptcha/",),
        },
    ),
}


@dataclass(frozen=True)
class Config:
    provider: Provider
    site_key: str
    secret_key: str


class CaptchaConfigError(RuntimeError):
    """The environment asks for a CAPTCHA that cannot work."""


def load_config() -> Config | None:
    """Read the three variables. None means off; a broken setting raises."""
    name = os.environ.get("CASHPILOT_CAPTCHA_PROVIDER", "").strip().lower()
    if not name:
        return None
    provider = PROVIDERS.get(name)
    if provider is None:
        raise CaptchaConfigError(
            f"CASHPILOT_CAPTCHA_PROVIDER={name!r} is not a provider CashPilot knows. "
            f"Set it to one of {', '.join(sorted(PROVIDERS))}, or remove it to turn the sign-in CAPTCHA off."
        )
    site_key = os.environ.get("CASHPILOT_CAPTCHA_SITE_KEY", "").strip()
    secret_key = os.environ.get("CASHPILOT_CAPTCHA_SECRET_KEY", "").strip()
    missing = [
        var
        for var, value in (("CASHPILOT_CAPTCHA_SITE_KEY", site_key), ("CASHPILOT_CAPTCHA_SECRET_KEY", secret_key))
        if not value
    ]
    if missing:
        raise CaptchaConfigError(
            f"CASHPILOT_CAPTCHA_PROVIDER is {name}, but {' and '.join(missing)} "
            f"{'is' if len(missing) == 1 else 'are'} not set. Set {'it' if len(missing) == 1 else 'them'}, "
            "or remove CASHPILOT_CAPTCHA_PROVIDER to turn the sign-in CAPTCHA off."
        )
    return Config(provider=provider, site_key=site_key, secret_key=secret_key)


_config: Config | None = None
_config_error: str | None = None


def configure() -> None:
    """(Re)read the environment. Runs at import; tests call it after changing env."""
    global _config, _config_error
    try:
        _config, _config_error = load_config(), None
    except CaptchaConfigError as exc:
        _config, _config_error = None, str(exc)


def config() -> Config | None:
    """The working configuration, or None when the CAPTCHA is off or broken."""
    return _config


def required() -> bool:
    """True when the operator asked for a CAPTCHA, even a broken one.

    The app refuses to start on a broken one (``check_startup``). If a request
    still arrives, sign-in must refuse rather than skip the check.
    """
    return _config is not None or _config_error is not None


def check_startup() -> None:
    """Refuse to start on a broken setting; say once that the CAPTCHA is on."""
    if _config_error:
        raise RuntimeError(_config_error)
    if _config is not None:
        logger.info("Sign-in CAPTCHA is on: %s.", _config.provider.label)


@dataclass(frozen=True)
class Result:
    ok: bool
    #: ``ok``, ``missing`` (no token sent), ``rejected`` (the provider said no)
    #: or ``unavailable`` (we could not get an answer, or the setting is broken).
    reason: str


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=VERIFY_TIMEOUT_SECONDS)


async def verify(token: str | None, remote_ip: str | None) -> Result:
    """Ask the provider whether ``token`` is a solved challenge. Fails closed."""
    cfg = _config
    if cfg is None:
        return Result(False, "unavailable")
    if not token or not token.strip():
        return Result(False, "missing")
    data = {"secret": cfg.secret_key, "response": token}
    if cfg.provider.send_sitekey:
        data["sitekey"] = cfg.site_key
    if remote_ip and _is_ip(remote_ip):
        data["remoteip"] = remote_ip
    try:
        async with _client() as client:
            resp = await client.post(cfg.provider.verify_url, data=data)
        if resp.status_code != 200:
            logger.warning("%s siteverify answered HTTP %s.", cfg.provider.label, resp.status_code)
            return Result(False, "unavailable")
        body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("%s siteverify could not be reached: %s.", cfg.provider.label, type(exc).__name__)
        return Result(False, "unavailable")
    if not isinstance(body, dict):
        logger.warning("%s siteverify answered something other than a JSON object.", cfg.provider.label)
        return Result(False, "unavailable")
    if body.get("success") is True:
        return Result(True, "ok")
    codes = body.get("error-codes")
    codes = [str(c) for c in codes] if isinstance(codes, list) else []
    logger.info("Sign-in CAPTCHA rejected by %s: %s.", cfg.provider.label, ", ".join(codes) or "no error code")
    return Result(False, "rejected")


configure()
