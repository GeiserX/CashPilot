"""Out-of-band alert delivery for CashPilot.

Passive income is unattended by definition, so an alert that only appears in an
open browser tab is an alert nobody sees. This module pushes the ones that matter
somewhere a person actually looks.

Every target is opt-in through an environment variable and the module is entirely
inert until one is set, so existing deployments are unaffected. Delivery is
best-effort and never raises: a misconfigured or unreachable notifier must not be
able to break an earnings-collection run.

Configure any combination of:

* ``CASHPILOT_NTFY_URL``          -- full topic URL, e.g. ``https://ntfy.sh/my-topic``
* ``CASHPILOT_WEBHOOK_URL``       -- generic endpoint; receives a small JSON body
* ``CASHPILOT_TELEGRAM_BOT_TOKEN`` + ``CASHPILOT_TELEGRAM_CHAT_ID``
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

# Deliberately short: this runs inside the collection cycle, and a hanging notifier
# must not stretch it.
_TIMEOUT = 10.0


def configured_targets() -> list[str]:
    """Names of the notification targets currently configured (empty = inert)."""
    targets = []
    if os.getenv("CASHPILOT_NTFY_URL", "").strip():
        targets.append("ntfy")
    if os.getenv("CASHPILOT_WEBHOOK_URL", "").strip():
        targets.append("webhook")
    if os.getenv("CASHPILOT_TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("CASHPILOT_TELEGRAM_CHAT_ID", "").strip():
        targets.append("telegram")
    return targets


def is_enabled() -> bool:
    return bool(configured_targets())


async def _post_ntfy(client: httpx.AsyncClient, title: str, message: str) -> None:
    url = os.getenv("CASHPILOT_NTFY_URL", "").strip()
    # ntfy takes the body as the message and the title as a header.
    await client.post(url, content=message.encode("utf-8"), headers={"Title": title})


async def _post_webhook(client: httpx.AsyncClient, title: str, message: str, kind: str, subject: str) -> None:
    url = os.getenv("CASHPILOT_WEBHOOK_URL", "").strip()
    await client.post(url, json={"title": title, "message": message, "kind": kind, "subject": subject})


async def _post_telegram(client: httpx.AsyncClient, title: str, message: str) -> None:
    token = os.getenv("CASHPILOT_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("CASHPILOT_TELEGRAM_CHAT_ID", "").strip()
    await client.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": f"{title}\n\n{message}"},
    )


async def send(title: str, message: str, *, kind: str = "alert", subject: str = "") -> int:
    """Deliver one alert to every configured target.

    Returns how many targets accepted it. Failures are logged and swallowed --
    the caller is a background job whose real work must continue regardless.
    """
    targets = configured_targets()
    if not targets:
        return 0

    delivered = 0
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for target in targets:
            try:
                if target == "ntfy":
                    await _post_ntfy(client, title, message)
                elif target == "webhook":
                    await _post_webhook(client, title, message, kind, subject)
                elif target == "telegram":
                    await _post_telegram(client, title, message)
                delivered += 1
            except Exception as exc:  # noqa: BLE001 - notifier failure is never fatal
                logger.warning("Alert delivery to %s failed: %s", target, exc)
    return delivered
