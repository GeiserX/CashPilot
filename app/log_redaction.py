"""Keep secrets that travel in a URL out of the container log.

httpx logs every request at INFO with its full URL (``HTTP Request: POST <url>
"HTTP/1.1 200 OK"``), and several secrets live in the URL itself: the Telegram
Bot API puts the bot token in the path (``/bot<token>/sendMessage``), a Discord
or Slack webhook carries its token in the path, an ntfy topic name is the only
thing guarding a public topic, a URL may carry ``user:password@``, and some
providers take an API key in the query string. ``app.notify.redact`` cleans
alert bodies, but nothing cleaned httpx's own log line, so ``docker logs
cashpilot-ui`` printed the bot token on every alert.

The fix keeps request logging (it is how you see that a collector or a notifier
actually ran) and rewrites the secret parts of every log record instead. It is a
log record factory, not a handler filter, so it covers every logger (httpx,
httpcore, urllib3 under the Docker SDK, our own) and every handler, including
the ones uvicorn installs with ``propagate=False``.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
from urllib.parse import urlsplit

import httpx

_REDACTED = "<redacted>"

# Same rule as app/notify.py's alert redaction: a credential-named query or
# form parameter.
_SECRET_PARAM_RE = re.compile(
    r"((?:token|api[_-]?key|key|secret|password|passwd|pwd|auth|session|sess|cookie|sig|signature)=)[^&\s\"']+",
    re.IGNORECASE,
)
# A Telegram bot token: ``<bot id>:<35 url-safe characters>``. Matched by shape so
# a token reaches no log even when it did not come from our own variable.
_TELEGRAM_TOKEN_RE = re.compile(r"(?<!\d)\d{6,12}:[A-Za-z0-9_-]{30,}")
# ``scheme://user:password@host``: keep the scheme and host, drop the userinfo.
# Userinfo ends at the first ``/``, ``?`` or ``#``: an ``@`` after one of those
# belongs to the path, query or fragment, and the host before it must stay.
_USERINFO_RE = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^/?#\s@'\"]+@", re.IGNORECASE)

# Values that are secret whatever they look like.
_SECRET_ENV = ("CASHPILOT_TELEGRAM_BOT_TOKEN",)
# URLs whose path and query are the secret (a webhook token, an ntfy topic).
_SECRET_URL_ENV = ("CASHPILOT_NTFY_URL", "CASHPILOT_WEBHOOK_URL")


def _configured_secrets() -> list[tuple[str, str]]:
    """(secret text, replacement) pairs taken from the notifier settings."""
    pairs = []
    for name in _SECRET_ENV:
        value = os.getenv(name, "").strip()
        if value:
            pairs.append((value, _REDACTED))
    for name in _SECRET_URL_ENV:
        value = os.getenv(name, "").strip()
        if not value:
            continue
        # httpx logs str(request.url), which is normalized: lowercase host, no
        # default port, spaces and non-ASCII percent-encoded. Match that form as
        # well as the raw value, or an operator's ``https://Hooks.Example.com/...``
        # or ``https://ntfy.sh:443/topic`` reaches the log untouched.
        forms = [value]
        with contextlib.suppress(Exception):  # an unparsable URL keeps only its raw form
            forms.append(str(httpx.URL(value)))
        for form in dict.fromkeys(forms):
            try:
                parts = urlsplit(form)
            except ValueError:
                pairs.append((form, _REDACTED))
                continue
            tail = parts.path + (f"?{parts.query}" if parts.query else "")
            host = parts.netloc.rpartition("@")[2]
            if host and tail.strip("/"):
                # Keep the host so the line still says where the request went.
                pairs.append((f"{host}{tail}", f"{host}/{_REDACTED}"))
                if parts.query:
                    pairs.append((f"{host}{parts.path}", f"{host}/{_REDACTED}"))
    # Longest first, so a URL is replaced before a shorter secret inside it.
    return sorted(pairs, key=lambda p: len(p[0]), reverse=True)


def redact(text: str) -> str:
    """Remove every secret this module knows about from one log string."""
    for secret, replacement in _configured_secrets():
        text = text.replace(secret, replacement)
    text = _USERINFO_RE.sub(rf"\1{_REDACTED}@", text)
    text = _TELEGRAM_TOKEN_RE.sub(_REDACTED, text)
    return _SECRET_PARAM_RE.sub(rf"\1{_REDACTED}", text)


def _redacting(factory):
    def make_record(*args, **kwargs) -> logging.LogRecord:
        record = factory(*args, **kwargs)
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a broken log call is the logging module's to report
            return record
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, ()
        if record.exc_info and not record.exc_text:
            # Handlers reuse exc_text instead of formatting the traceback again.
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
        if record.stack_info:
            # stack_info=True prints source lines, which can hold a URL or a token.
            record.stack_info = redact(record.stack_info)
        return record

    make_record.cashpilot_redacting = True  # type: ignore[attr-defined]
    return make_record


def install() -> None:
    """Redact every log record created from now on. Safe to call twice."""
    current = logging.getLogRecordFactory()
    if not getattr(current, "cashpilot_redacting", False):
        logging.setLogRecordFactory(_redacting(current))
