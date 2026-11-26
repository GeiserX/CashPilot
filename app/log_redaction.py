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
# The public payout address in a HeroMiners request identifies this installation's wallet.
_KASPA_ADDRESS_PARAM_RE = re.compile(r"(\baddress=)kaspa(?::|%3a)[a-z0-9]+", re.IGNORECASE)
_ONCHAIN_ADDRESS_RE = re.compile(
    r"(/address/)(bc1[a-z0-9]{11,87}|[13][a-z0-9]{13,34})(?=[^a-z0-9]|$)"
    r"|(/addresses/)kaspa(?::|%3a)([a-z0-9]{61,63})(?=/balance)",
    re.IGNORECASE,
)
# 2Miners puts the ETC payout address in the account stats path.
_TWO_MINERS_ADDRESS_RE = re.compile(r"\betc\.2miners\.com/api/accounts/(0x[0-9a-f]{40})\b", re.IGNORECASE)
# OCEAN puts the Bitcoin payout address in its stats paths (statsnap, user_hashrate...).
# Address-shaped only (bech32 or base58, as the collector checks), so other ids stay readable.
_OCEAN_ADDRESS_RE = re.compile(
    r"(\bapi\.ocean\.xyz/v1/[a-z_]+/)(bc1[02-9ac-hj-np-z]{11,71}|[13][1-9A-HJ-NP-Za-km-z]{25,34})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
# unMineable puts the payout address of any coin in the address stats path.
_UNMINEABLE_ADDRESS_RE = re.compile(r"(\bapi\.unminable\.com/v4/address/)([A-Za-z0-9]+)")
# Preserve the AxeOS status code. The address and reason phrase can both carry device data.
_AXEOS_REQUEST_RE = re.compile(r'\A(HTTP Request: GET http://)[^/\s]+(/api/system/info "[^ ]+ [0-9]{3}).*\Z', re.DOTALL)
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
# On-chain endpoint overrides (app/onchain.py, one per chain). A private node or
# a paid RPC URL often carries its access token in the path.
_SECRET_URL_ENV_PREFIX = "CASHPILOT_ONCHAIN_URL_"


def _configured_secrets() -> list[tuple[str, str]]:
    """(secret text, replacement) pairs taken from the notifier settings."""
    pairs = []
    for name in _SECRET_ENV:
        value = os.getenv(name, "").strip()
        if value:
            pairs.append((value, _REDACTED))
    names = [*_SECRET_URL_ENV, *sorted(n for n in os.environ if n.startswith(_SECRET_URL_ENV_PREFIX))]
    for name in names:
        value = os.getenv(name, "").strip()
        if not value:
            continue
        # httpx logs str(request.url), which is normalized: lowercase host, no
        # default port, spaces and non-ASCII percent-encoded. Match that form as
        # well as the raw value, or an operator's ``https://Hooks.Example.com/...``
        # or ``https://ntfy.sh:443/topic`` reaches the log untouched. The
        # on-chain client strips a trailing slash before it builds the request.
        forms = [value, value.rstrip("/")]
        for raw in forms[:2]:
            with contextlib.suppress(Exception):  # an unparsable URL keeps only its raw form
                forms.append(str(httpx.URL(raw)))
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
    text = _KASPA_ADDRESS_PARAM_RE.sub(rf"\1{_REDACTED}", text)
    # The reason phrase on the same line can repeat an address from the path,
    # in any case, and a Kaspa address as ``kaspa:`` or ``kaspa%3a``.
    onchain = {address for match in _ONCHAIN_ADDRESS_RE.finditer(text) for address in match.group(2, 4) if address}
    text = _ONCHAIN_ADDRESS_RE.sub(rf"\1\3{_REDACTED}", text)
    for address in onchain:
        text = re.sub(rf"(?:kaspa(?::|%3a))?{re.escape(address)}", _REDACTED, text, flags=re.IGNORECASE)
    text = _AXEOS_REQUEST_RE.sub(rf'\1{_REDACTED}\2"', text)
    # HTTPX logs the reason phrase on the same line. It can repeat the address.
    for address in _TWO_MINERS_ADDRESS_RE.findall(text):
        text = re.sub(address, _REDACTED, text, flags=re.IGNORECASE)
    for _, address in _UNMINEABLE_ADDRESS_RE.findall(text):
        text = text.replace(address, _REDACTED)
    # Bech32 is case-insensitive, so an echo in the reason phrase may differ in case.
    for _, address in _OCEAN_ADDRESS_RE.findall(text):
        text = re.sub(re.escape(address), _REDACTED, text, flags=re.IGNORECASE)
    return _SECRET_PARAM_RE.sub(rf"\1{_REDACTED}", text)


def _clean_arg(value):
    """One argument of a log call whose formatting failed, safe to print."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact(value if isinstance(value, str) else repr(value))


def _redacting(factory):
    def make_record(*args, **kwargs) -> logging.LogRecord:
        record = factory(*args, **kwargs)
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a broken log call is the logging module's to report
            # ...and it reports it on stderr with the message and the arguments,
            # so those are cleaned too. The call stays broken and still gets reported.
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            if isinstance(record.args, dict):
                record.args = {key: _clean_arg(value) for key, value in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(_clean_arg(value) for value in record.args)
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
