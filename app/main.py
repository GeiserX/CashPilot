"""CashPilot — FastAPI application.

Self-hosted passive income dashboard: service catalog, Docker container
management, and earnings tracking.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import ipaddress
import json
import logging
import math
import os
import re
import secrets
import socket
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.base import BaseHTTPMiddleware

from app import (
    auth,
    catalog,
    compose_generator,
    credential_test,
    database,
    disclosure,
    egress,
    exchange_rates,
    fleet_key,
    lan_isolation,
    login_rate_limit,
    machine_economics,
    metrics,
    net_activity,
    notify,
    onchain,
    payout_registry,
    payouts,
    power,
    preflight,
    producer_state,
    setup_token,
    update_check,
    version,
)
from app.worker_proxy import _pin_url_to_ip, _validate_worker_url

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# In-memory store for the latest collector alerts (errors from last run)
_collector_alerts: list[dict[str, str]] = []
# Whether a collection has ever COMPLETED here. An empty alert list means
# "nothing is wrong" only once something has looked; before that it means
# "nothing has been checked", and the bell used to render both as "All
# collectors healthy" (CashPilot-tb5). Restored on startup from durable state so
# a restart does not reset the claim to "never ran" while data exists.
_collection_has_run: bool = False
_collection_lock = asyncio.Lock()
_collection_semaphore = asyncio.Semaphore(8)

# Fire-and-forget background tasks (e.g. triggered collection runs). Keeping a
# reference prevents the task from being garbage-collected mid-run and lets us
# retrieve/log any exception it raised (bare `asyncio.create_task(...)` drops
# the reference and silently swallows exceptions).
_background_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> asyncio.Task:
    """Fire-and-forget a coroutine while keeping a reference and logging errors."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)

    def _on_done(t: asyncio.Task) -> None:
        _background_tasks.discard(t)
        if not t.cancelled():
            exc = t.exception()
            if exc is not None:
                logger.error("Background task failed: %s", exc, exc_info=exc)

    task.add_done_callback(_on_done)
    return task


# Login rate limiting moved to app.login_rate_limit (bead sux) — it was the last
# thing the routers genuinely needed from this module, and extracting it is what
# breaks the main -> routers -> main import cycle.
#
# Re-exported by REFERENCE, not copied: tests patch app.main._check_login_rate
# and a conftest fixture clears app.main._login_attempts between tests. Binding a
# copy here would leave both pointing at an object nothing reads, and the fixture
# would silently stop isolating tests.
_login_attempts = login_rate_limit._login_attempts
_LOGIN_MAX_ATTEMPTS = login_rate_limit.MAX_ATTEMPTS
_LOGIN_WINDOW_SECONDS = login_rate_limit.WINDOW_SECONDS
_check_login_rate = login_rate_limit.check_login_rate
_record_failed_login = login_rate_limit.record_failed_login


def _safe_json(raw: str, fallback: Any = None) -> Any:
    """Parse JSON with a fallback so one malformed DB row doesn't 500 the fleet."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return fallback if fallback is not None else []


def _decoded_worker(worker: dict[str, Any]) -> dict[str, Any]:
    """A worker row with its JSON-TEXT columns decoded into real structures.

    ``list_workers``/``get_worker`` return raw rows, so ``containers`` and
    ``system_info`` arrive as strings. Passing one of those straight to code
    expecting a mapping is an AttributeError at request time, so every caller
    that reads inside them goes through here.
    """
    decoded = dict(worker)
    # Deliberately delegates rather than repeating the three _safe_json calls:
    # a second copy of the decoding is how one caller ends up forgetting it.
    _parse_worker_json(decoded)
    return decoded


# Previous network counter reading per (worker, slug), for turning Docker's
# CUMULATIVE totals into a rate. In memory on purpose: losing it on restart
# costs one unknown reading, whereas persisting a stale baseline across a
# restart risks pairing it with counters that reset in the meantime.
_net_baselines: dict[tuple[Any, str], tuple[int, float]] = {}


def _traffic_state(slug: str, containers: list[dict[str, Any]]) -> str | None:
    """MOVING/SILENT/UNKNOWN for a service, from two counter readings.

    Returns None when there is nothing to say at all, so the caller can leave
    the signal out entirely rather than assert "unknown" about a service whose
    containers were never seen.
    """
    now = time.monotonic()
    rates: list[float] = []
    measured = False

    for container in containers:
        total = net_activity.totals(container)
        if total is None:
            continue
        measured = True
        key = (container.get("_worker_id"), slug)
        previous = _net_baselines.get(key)
        _net_baselines[key] = (total, now)
        if previous is None:
            continue
        value = net_activity.rate(previous[0], total, now - previous[1])
        if value is not None:
            rates.append(value)

    if not measured:
        return None
    if not rates:
        # Counters exist but no usable interval yet — first sight of this
        # container, or its counters reset. Saying "unknown" is the point.
        return net_activity.UNKNOWN
    # Any instance moving data means the service is not silent.
    return net_activity.classify(max(rates))


async def _get_all_worker_containers(workers: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Collect container/app data from all online workers' heartbeat data in DB.

    ``workers`` lets a caller that has ALREADY fetched the worker list hand it
    in rather than causing a second `SELECT *` and a second full JSON decode of
    every row in the same request. Everyone else keeps calling this with no
    arguments and gets the fetch for free.
    """
    if workers is None:
        workers = await database.list_workers()
    result: list[dict[str, Any]] = []
    for w in workers:
        if w.get("status") != "online":
            continue
        sys_info = _safe_json(w.get("system_info", "{}"), {})
        worker_has_docker = sys_info.get("docker_available", False)
        is_android = sys_info.get("device_type") == "android"
        worker_name = w.get("name", "worker")

        # Docker containers (from Docker-based workers only — skip for Android)
        if not is_android:
            containers = _safe_json(w.get("containers", "[]"))
            for c in containers:
                slug = c.get("slug", "")
                if slug:
                    result.append(
                        {
                            "slug": slug,
                            "name": c.get("name", slug),
                            "status": c.get("status", "unknown"),
                            "image": c.get("image", ""),
                            "cpu_percent": c.get("cpu_percent", 0),
                            "memory_mb": c.get("memory_mb", 0),
                            "net_rx_bytes": c.get("net_rx_bytes"),
                            "net_tx_bytes": c.get("net_tx_bytes"),
                            "category": "",
                            # The WORKER's answer, not the node name. The image
                            # matcher sets "external" for a container it found by
                            # image rather than by CashPilot's own label — one the
                            # user started themselves. Overwriting it here meant
                            # that container appeared as an ordinary managed
                            # service with live Restart/Stop/Logs buttons, and
                            # every one of them answered "404 Container not
                            # found" for a row the same screen called Running.
                            # The node name is already carried by _node.
                            "deployed_by": c.get("deployed_by") or worker_name,
                            # The dial-back address the worker read from the ONE
                            # env var the service's catalog entry declares. None
                            # when undeclared/unreported — this dict is a key
                            # allowlist, so without this line the field the
                            # mismatch check depends on would be silently
                            # dropped right here.
                            "advertised_address": c.get("advertised_address"),
                            "_node": worker_name,
                            "_worker_id": w.get("id"),
                            "_has_docker": worker_has_docker,
                            "_is_android": False,
                        }
                    )

        # Android apps (from Android workers)
        if is_android:
            apps = _safe_json(w.get("apps", "[]"))
            for a in apps:
                slug = a.get("slug", "")
                if slug:
                    result.append(
                        {
                            "slug": slug,
                            "name": a.get("slug", slug),
                            # Three-valued, matching what the Android client
                            # now sends. `running` is None when the phone could
                            # not determine it -- every detection signal degrades
                            # to false when its permissions are denied -- and
                            # `"running" if a.get("running") else "stopped"`
                            # turned that into a confident "stopped", so the
                            # fleet page stated the user's earning apps had died
                            # when the device simply could not see them.
                            "status": _android_app_status(a.get("running")),
                            "image": "",
                            "cpu_percent": 0,
                            "memory_mb": 0,
                            "category": "",
                            # Android apps are enumerated by the worker itself and
                            # are never CashPilot-managed containers, so there is
                            # no external/managed distinction to preserve here.
                            "deployed_by": worker_name,
                            "_node": worker_name,
                            "_worker_id": w.get("id"),
                            "_has_docker": False,
                            "_is_android": True,
                            "_net_tx_24h": a.get("net_tx_24h", 0),
                            "_net_rx_24h": a.get("net_rx_24h", 0),
                        }
                    )
    return result


async def _resolve_worker_id(worker_id: int | None) -> int:
    """Return a valid worker_id, auto-resolving when only one worker is online."""
    if worker_id is not None:
        return worker_id
    workers = await database.list_workers()
    online = [w for w in workers if w["status"] == "online"]
    if len(online) == 1:
        return online[0]["id"]
    if len(online) == 0:
        raise HTTPException(status_code=503, detail="No workers online")
    raise HTTPException(
        status_code=400,
        detail="worker_id is required (multiple workers online)",
    )


# ---------------------------------------------------------------------------
# Periodic collection job
# ---------------------------------------------------------------------------


async def _run_health_check() -> None:
    """Check health of all deployed containers and record events.

    Deduplicates by slug: if *any* instance of a service is running,
    record a single check_ok for that slug (avoids penalising services
    deployed on multiple nodes where one may be stopped).

    A service that vanishes from the heartbeat entirely (container removed
    outside CashPilot, crash-removed, worker's Docker daemon down) previously
    got no health event at all — it just stopped appearing, so its score
    stayed frozen wherever it last was (often green) forever. Any known
    Docker-backed deployment missing from every online worker's current data
    now gets an explicit check_down. Scoped to "at least one worker online"
    so a fully-offline fleet (no heartbeat data to trust either way) never
    triggers false check_downs; "external" deployments (e.g. Grass, Bytelixir)
    have no container and are excluded since no worker ever reports them.
    """
    try:
        statuses = await _get_all_worker_containers()
        # Aggregate: slug -> best status (running wins)
        slug_best: dict[str, str] = {}
        for s in statuses:
            slug = s["slug"]
            status = s.get("status", "unknown")
            if slug_best.get(slug) != "running":
                slug_best[slug] = status
        # Collect every event for this cycle and write them in a single transaction
        # rather than one fsync'd commit per service (see database.record_health_events).
        events: list[tuple[str, str, str]] = []
        for slug, status in slug_best.items():
            if status == "running":
                events.append((slug, "check_ok", ""))
            else:
                events.append((slug, "check_down", status))

        workers = await database.list_workers()
        online = [w for w in workers if w.get("status") == "online"]
        # "Missing from a heartbeat" is only evidence of being DOWN if every
        # online worker could actually look. A worker whose Docker socket became
        # unreadable — unmounted by a host update, permissions changed, daemon
        # erroring — keeps heartbeating happily and reports zero containers, so
        # this loop wrote a durable check_down for EVERY deployment every five
        # minutes while those containers were up and earning. The user watched
        # each service's Health column fall and its uptime read 0%, and the
        # events kept dragging the 7-day score long after the socket was fixed.
        #
        # The deployments table has no worker column, so a missing container
        # cannot be attributed to a particular host: if any online worker is
        # blind, the container might be on that one. Unknown is not down, so
        # nothing is recorded — the score is left untouched rather than
        # invented.
        blind = [w for w in online if not _safe_json(w.get("system_info", "{}"), {}).get("docker_available", False)]
        if online and not blind:
            deployments = await database.get_deployments()
            for d in deployments:
                slug = d["slug"]
                if d.get("status") == "external" or slug in slug_best:
                    continue
                events.append((slug, "check_down", "missing from heartbeat"))
        elif blind:
            logger.warning(
                "Not recording missing-container downtime: %d online worker(s) cannot read Docker (%s). "
                "Their containers may be running; recording them as down would be a guess.",
                len(blind),
                ", ".join(sorted(str(w.get("name") or w.get("id")) for w in blind)),
            )

        await database.record_health_events(events)
    except Exception as exc:
        logger.warning("Health check skipped: %s", exc)


async def _push_alert(kind: str, subject: str, title: str, message: str, alert_id: int) -> None:
    """Push an alert out-of-band, and make a total delivery failure retryable.

    The dedupe row is committed BEFORE this runs, so a failed delivery used to
    disarm the alert for the whole cooldown window: ntfy unreachable in the
    minute a collector broke meant one WARNING in a container log and 24 silent
    hours — the push path's own failure was the one failure it could not
    report. When no target accepts the message, the row THIS delivery owns
    (record_alert's returned id) is deleted so the next collection cycle
    records-and-pushes again — by id, never by (kind, subject), because a
    recovery and a fresh failure can insert a newer row while this push was in
    flight, and taking that row's dedupe with ours would double-notify. The
    outcome feeds a metric either way so dead delivery is visible to
    Prometheus instead of indistinguishable from health.
    """
    try:
        delivered = await notify.send(title, message, kind=kind, subject=subject)
    except Exception as exc:  # noqa: BLE001 - a notifier crash must never kill collection
        logger.warning("Alert push for %s/%s crashed: %s", kind, subject, notify.redact(str(exc)))
        delivered = 0
    if not notify.is_enabled():
        # Nothing is configured: the bell is the only channel, the row must
        # stand (clearing it would re-insert every cycle and churn the bell),
        # and delivery metrics would only count an absence.
        return
    metrics.record_notify_delivery(bool(delivered))
    if not delivered:
        try:
            undeduped = await database.delete_alert(alert_id)
        except Exception as exc:  # noqa: BLE001
            undeduped = False
            logger.warning("Could not un-dedupe alert %s after failed delivery: %s", alert_id, exc)
        if undeduped:
            logger.warning(
                "No notification target accepted the %s alert for %s — will retry on the next cycle",
                kind,
                subject,
            )
        else:
            # Saying "will retry" when the dedupe row survived would be false.
            logger.warning(
                "No notification target accepted the %s alert for %s, and the dedupe row could "
                "not be released — the next push waits out the cooldown window",
                kind,
                subject,
            )


async def _detect_payout(result: Any) -> dict[str, str] | None:
    """Notice a balance drop that looks like a cashout, and ask.

    Never records income on its own. A balance also falls for a provider
    correction or a reset session, and an unconfirmed guess written as earnings
    corrupts lifetime-earned permanently and invisibly.

    Returns the alert to show the user, or None. It has to be RETURNED rather
    than filed and forgotten: the bell renders one in-memory list built during
    the collection run, and this function runs in the success branch that never
    touched that list — so a detected payout was written to the database and
    then never shown to anybody, which defeats the point of asking.
    """
    try:
        previous = await database.get_latest_balance(result.platform)
        if previous is None:
            return None
        probable = payouts.detect(previous, result.balance, catalog.get_service(result.platform))
        if not probable:
            return None
        payout_id = await database.record_probable_payout(
            platform=result.platform,
            amount=probable["amount"],
            currency=result.currency,
            fx_rate_usd=exchange_rates.to_usd(1.0, result.currency),
        )
        if payout_id is None:
            # One already pending for this platform; a second prompt for the
            # same event teaches the user to dismiss them.
            return None
        if alert_id := await database.record_alert("payout", result.platform, probable["reason"]):
            # The one alert that asks a QUESTION — unanswered, the payout never
            # counts toward lifetime earnings, so the headline number stays
            # wrong until a human replies. It was the only pushable kind that
            # never pushed: recorded, belled, and then waiting for someone to
            # happen to open the UI. The record_alert gate was already here,
            # its boolean just went unread.
            _spawn(
                _push_alert(
                    "payout",
                    result.platform,
                    f"CashPilot: {result.platform} balance dropped — was this a payout?",
                    probable["reason"],
                    alert_id,
                )
            )
        return {"kind": "payout", "platform": result.platform, "error": probable["reason"]}
    except Exception as exc:
        # Earnings collection must not fail because payout detection did.
        logger.warning("Payout detection failed for %s: %s", getattr(result, "platform", "?"), exc)
    return None


async def _pending_payout_alerts(seen: set[str] | None = None) -> list[dict[str, str]]:
    """One alert per payout still waiting for a yes or no.

    The question outlives the collection run that noticed it. Rebuilding the
    bell only from what was just detected made the prompt disappear on the next
    run, which is the one thing a prompt must not do — an unanswered payout is
    unanswered until the user answers it.
    """
    seen = seen or set()
    try:
        rows = await database.get_payouts()
    except Exception as exc:
        logger.warning("Could not load pending payouts for the alert bell: %s", exc)
        return []
    pending: list[dict[str, str]] = []
    for row in rows:
        platform = row.get("platform", "")
        if row.get("confirmed") or platform in seen:
            continue
        seen.add(platform)
        amount = row.get("amount")
        currency = row.get("currency") or ""
        pending.append(
            {
                "kind": "payout",
                "platform": platform,
                "error": f"Balance dropped by {amount:.2f} {currency}".rstrip()
                + " — was this a payout? Confirm or reject it."
                if isinstance(amount, int | float)
                else "A balance drop looks like a payout — confirm or reject it.",
            }
        )
    return pending


async def _collect_bounded(collector) -> Any:
    """Run a single collector's `collect()` under the shared concurrency limit.

    A raised exception is converted into an EarningsResult HERE, while the
    collector -- and with it the platform name -- is still in hand. It used to
    propagate to the gather(), where the platform was unrecoverable: the
    failure was logged as an anonymous line and produced no alert, no bell
    entry and no metric. A collector that raised was invisible to the user
    (CashPilot-5bdm).
    """
    from app.collectors import base as collectors_base

    async with _collection_semaphore:
        try:
            return await collector.collect()
        except Exception as exc:
            collectors_base.log_failure(logger, collector.platform or type(collector).__name__, exc)
            return collectors_base.EarningsResult(
                platform=collector.platform or type(collector).__name__,
                balance=0.0,
                error=str(exc),
                error_kind=collectors_base.classify_exception(exc),
            )


async def _offline_worker_alerts() -> list[dict[str, str]]:
    """Bell entries for every worker currently marked offline.

    Derived from the workers table on each rebuild rather than carried in
    memory: the collection loop replaces _collector_alerts wholesale every
    hour, and an entry that lived only in the list would be dropped there —
    silently un-reporting a machine that is still down. Recovery needs no
    bookkeeping either: the next heartbeat flips the row back to online and
    the entry stops being derived.
    """
    try:
        workers = await database.list_workers()
    except Exception as exc:  # noqa: BLE001 - the bell must not take down collection
        logger.warning("Could not derive offline-worker alerts: %s", exc)
        return []
    entries: list[dict[str, str]] = []
    for w in workers:
        if w.get("status") == "offline" and w.get("last_heartbeat"):
            entries.append(
                {
                    "kind": "worker",
                    "platform": w["name"],
                    # Identity travels beside the display name: recovery and
                    # dedupe match on client_id, because two hosts can share a
                    # hostname and hostnames churn across recreates.
                    "client_id": w.get("client_id") or w["name"],
                    "error": (
                        f"Offline since {w['last_heartbeat']} UTC. Its containers keep running "
                        "and earning, but CashPilot cannot see or manage them until it reconnects."
                    ),
                }
            )
    return entries


async def _flatline_check() -> list[dict[str, str]]:
    """Alert on services that are running but whose balance has stopped moving.

    A container can be up and a collector can authenticate happily while the
    balance never moves. Every other view of the system looks healthy, so
    nothing else would surface it.

    Never raises: this is a diagnostic, and a diagnostic must not be able to
    take down the collection run it is diagnosing. record_alert's per-kind
    cooldown keeps this to one notification per service rather than one per
    collection cycle.
    """
    bell: list[dict[str, str]] = []
    try:
        flat_services = await database.get_flatlined_services()
        flat_now = {f["platform"] for f in flat_services}

        # Clear the cooldown for anything that has started earning again.
        # record_alert suppresses a repeat within the quiet window, so without
        # this a service that recovered and then went flat again inside that
        # window would be silently swallowed - the alert nobody gets.
        for recovered in await database.get_alert_subjects("flatline") - flat_now:
            await database.clear_alerts("flatline", recovered)
            logger.info("%s is earning again; cleared its flatline alert", recovered)

        for flat in flat_services:
            message = (
                f"Balance has not moved in {flat['days_flat']} days "
                f"(still {flat['balance']}). The service is running but not earning."
            )
            # Built for EVERY flatlined service, not only the ones that clear
            # record_alert's cooldown. The cooldown exists to stop repeat
            # NOTIFICATIONS; the bell is a standing statement of what is wrong
            # right now, so gating it the same way would blank the bell on the
            # second collection while the service was still not earning.
            bell.append({"kind": "flatline", "platform": flat["platform"], "error": message})
            if alert_id := await database.record_alert("flatline", flat["platform"], message):
                _spawn(
                    _push_alert(
                        "flatline",
                        flat["platform"],
                        f"CashPilot: {flat['platform']} is running but not earning",
                        message,
                        alert_id,
                    )
                )
    except Exception as exc:
        logger.warning("Flatline check failed: %s", exc)
        # The check's own failure must not render as health: an empty return
        # here is indistinguishable from "nothing is flatlined", so a broken
        # query would silently retire the only detector this class of fault has.
        bell.append(
            {
                "kind": "flatline",
                "platform": "flatline check",
                "error": "The flatline check itself failed — earning anomalies are NOT being watched. See server logs.",
            }
        )
    return bell


async def _warm_collector_alerts() -> None:
    """Restore persisted collector alerts into the in-memory list the UI bell reads.

    Without this, a restart clears the bell while the collector is still broken, and
    the operator is told everything is fine until the next hourly run.
    """
    global _collector_alerts
    try:
        stored = await database.list_alerts(limit=100)
    except Exception as exc:
        logger.warning("Could not restore persisted alerts: %s", exc)
        return
    # Newest-first, keeping only the most recent row per subject: a normal run puts
    # exactly one entry per failing platform in this list, and the restored bell must
    # look the same rather than showing one row per historical message.
    seen: set[str] = set()
    restored: list[dict[str, str]] = []
    for alert in stored:
        # Payouts belong here too. Dropping every non-collector kind meant a
        # detected payout was recorded and then never shown, so the prompt the
        # user is supposed to answer never appeared. Dedup by kind AND subject:
        # a platform can legitimately have both a failing collector and a
        # pending payout, and they are different things to tell someone.
        # flatline belongs here for the same reason payout does: it is recorded,
        # and without this it is dropped on the way to the bell, so a restart
        # silently clears a warning about a service that is still not earning.
        # worker likewise: an offline machine must survive a UI restart. And
        # notice: #326 made notices durable and deduped, but a restart dropped
        # them from the bell while their 24h push-dedupe survived — so a
        # recovery inside the gap skipped clear_alerts and the stale row
        # swallowed the next genuine warning.
        if alert["kind"] not in ("collector", "payout", "flatline", "worker", "notice"):
            continue
        key = f"{alert['kind']}:{alert['subject']}"
        if key in seen:
            continue
        seen.add(key)
        entry = {"kind": alert["kind"], "platform": alert["subject"], "error": alert["message"]}
        if alert.get("category"):
            entry["category"] = alert["category"]
        restored.append(entry)
    # Worker alerts are stored under client_id (the identity); the bell shows
    # people a NAME. Resolve display names in one pass, keeping the client_id
    # beside it for recovery matching. A worker deleted since the alert was
    # stored keeps the raw id — still actionable, never wrong.
    worker_entries = [e for e in restored if e["kind"] == "worker"]
    if worker_entries:
        with contextlib.suppress(Exception):
            names = {w.get("client_id"): w["name"] for w in await database.list_workers()}
            for e in worker_entries:
                e["client_id"] = e["platform"]
                e["platform"] = names.get(e["platform"], e["platform"])
    _collector_alerts = restored
    # A restart must not make the bell claim nothing has ever been checked. Any
    # stored alert, or any earnings row, is proof that a collection ran.
    global _collection_has_run
    if restored:
        _collection_has_run = True
    else:
        try:
            _collection_has_run = bool(await database.get_earnings_summary())
        except Exception as exc:  # noqa: BLE001 - a warm-up must not block startup
            logger.warning("Could not tell whether a collection has run before: %s", exc)


async def _track_fully_configured_services() -> int:
    """Give every fully-credentialled service a deployment row, so it is collected.

    Collection iterates DEPLOYMENT ROWS (``make_collectors``), so a service with
    no row is never collected however complete its credentials are. Saving
    credentials has created that row since the fix in #187 — but only at save
    time, and nothing has ever repaired a database written before it.

    That leaves the upgrade path in exactly the state the fix was meant to end:
    credentials stored under an older version show the green "Configured" badge,
    no collector is ever built for them, and no earnings arrive. Nothing prompts
    the user to re-save, because as far as the UI is concerned everything is
    already correct. So this runs once per start and is idempotent — a slug that
    already has a row of any status is left exactly as it is, because that row
    may carry a real container id and spec that must not be replaced with an
    empty placeholder.

    Returns the number of rows created, for the log line and the tests.
    """
    from app.collectors import fully_configured_slugs

    try:
        config = await database.get_config() or {}
        if not isinstance(config, dict):
            return 0
        existing = {d.get("slug") for d in await database.get_deployments()}
        tracked = 0
        for slug in sorted(fully_configured_slugs(config)):
            if slug in existing or not catalog.get_service(slug):
                continue
            await database.save_deployment(slug=slug, container_id="", status="external")
            tracked += 1
        if tracked:
            logger.info(
                "Started tracking %d service(s) whose credentials were stored before "
                "saving them began tracking; their earnings will be collected from now on",
                tracked,
            )
        return tracked
    except Exception as exc:  # noqa: BLE001 - bookkeeping must never block startup
        logger.warning("Could not backfill tracking for stored credentials: %s", exc)
        return 0


async def _run_collection() -> None:
    """Collect earnings from all deployed services that have collectors."""
    global _collector_alerts
    if _collection_lock.locked():
        logger.info("Collection already in progress, skipping")
        return
    async with _collection_lock:
        success = True
        start_time = 0.0
        collectors: list = []
        try:
            start_time = metrics.record_collection_start()
            deployments = await database.get_deployments()
            config = await database.get_config() or {}
            if not isinstance(config, dict):
                config = {}
            from app.collectors import _close_stale, make_collectors

            collectors = make_collectors(deployments, config)
            await _close_stale()
            results = await asyncio.gather(*(_collect_bounded(c) for c in collectors), return_exceptions=True)
            alerts: list[dict[str, str]] = []
            # Platforms that were already failing before this run: used to detect a
            # recovery, so a service that breaks again later notifies again rather
            # than being deduped into silence forever.
            previously_alerting = {a["platform"] for a in _collector_alerts}
            # Notices tracked separately: a warning-free success is a notice's
            # recovery, and conflating the two would clear the wrong kind.
            previously_noticing = {a["platform"] for a in _collector_alerts if a.get("kind") == "notice"}
            platforms_ok = 0
            for result in results:
                if isinstance(result, Exception):
                    # Redacted BEFORE it is logged. A collector exception is
                    # usually an httpx error that embeds the offending header,
                    # which for several providers IS the live credential.
                    logger.warning("Collector raised exception: %s", notify.redact(str(result)))
                    success = False
                    continue
                if result.error:
                    # Redact FIRST. The comment below explains why the alert is
                    # sanitised; this line used to log the raw string one step
                    # earlier and put the credential in the container log
                    # anyway, defeating the whole exercise.
                    logger.warning("Collection error for %s: %s", result.platform, notify.redact(result.error))
                    # Redact ONCE, here, so the same sanitized string is what gets shown,
                    # stored and sent. Collector errors are usually str(exc), and an httpx
                    # exception embeds the offending header or URL — which for several
                    # providers is a live credential. The alert is now durable and readable
                    # by any authenticated role, so it must never hold a secret.
                    safe_error = notify.redact(result.error)
                    error_kind = getattr(result, "error_kind", None)
                    entry = {"kind": "collector", "platform": result.platform, "error": safe_error}
                    if error_kind:
                        entry["category"] = error_kind
                    alerts.append(entry)
                    metrics.record_collection_error(result.platform)
                    # Push out-of-band only the FIRST time this failure appears — a
                    # collector broken for a week must not notify every single hour.
                    if alert_id := await database.record_alert(
                        "collector", result.platform, safe_error, category=error_kind
                    ):
                        # The push is the only channel an unattended install
                        # has, so the taxonomy must reach it too: "rotate your
                        # cookie" and "provider hiccup" are different asks.
                        cause = {
                            "auth": " (credential rejected)",
                            "transient": " (provider unreachable)",
                            "shape": " (page changed)",
                        }.get(error_kind or "", "")
                        _spawn(
                            _push_alert(
                                "collector",
                                result.platform,
                                f"CashPilot: {result.platform} collector failed{cause}",
                                safe_error,
                                alert_id,
                            )
                        )
                else:
                    # A caveat on a SUCCESSFUL reading. It is shown, because the
                    # figure is partial and the user should know, but it is not
                    # a failure: the balance below is stored exactly as any other.
                    if getattr(result, "warning", None):
                        safe_warning = notify.redact(result.warning)
                        logger.info("Collector notice for %s: %s", result.platform, safe_warning)
                        alerts.append({"kind": "notice", "platform": result.platform, "error": safe_warning})
                        # Push out-of-band with the same once-per-window dedupe
                        # errors get. A notice used to reach ONLY the bell,
                        # which is read by whoever happens to open the UI — and
                        # "nobody looked for days" is the incident this class
                        # of warning (an unreachable storj node) comes from.
                        if alert_id := await database.record_alert("notice", result.platform, safe_warning):
                            _spawn(
                                _push_alert(
                                    "notice",
                                    result.platform,
                                    f"CashPilot: {result.platform} needs attention",
                                    safe_warning,
                                    alert_id,
                                )
                            )
                    elif result.platform in previously_noticing:
                        # A warning-free success is the notice's recovery: drop
                        # the stored row so the NEXT warning pushes again rather
                        # than being deduped into silence forever.
                        await database.clear_alerts("notice", result.platform)
                    # Compare against the last reading BEFORE writing the new one:
                    # a payout is only visible as the step between two snapshots.
                    payout_alert = await _detect_payout(result)
                    if payout_alert:
                        alerts.append(payout_alert)
                    await database.upsert_earnings(
                        platform=result.platform,
                        balance=result.balance,
                        currency=result.currency,
                        # Snapshot the rate now. to_usd(1.0, cur) is the cur -> USD
                        # rate (1.0 for USD, None if unknown); rates are only cached
                        # live, so this is the only chance to record what this reading
                        # was actually worth.
                        fx_rate_usd=exchange_rates.to_usd(1.0, result.currency),
                    )
                    logger.info("Collected %s: %.4f %s", result.platform, result.balance, result.currency)
                    platforms_ok += 1
                    if result.platform in previously_alerting:
                        # Recovered — drop the stored alert so a future failure counts
                        # as new and notifies again.
                        await database.clear_alerts("collector", result.platform)
            # Re-add every payout still awaiting an answer, not just ones
            # detected on THIS run. `record_probable_payout` returns None while
            # one is already pending, so a freshly detected payout produced an
            # alert once and then vanished from the bell on the very next
            # collection — before the user had a chance to confirm or reject
            # it. The pending rows in the database are the real source of
            # truth for "there is still a question outstanding", so the bell is
            # rebuilt from them rather than from what happened to be noticed in
            # the last few seconds.
            alerts.extend(
                await _pending_payout_alerts(seen={a["platform"] for a in alerts if a.get("kind") == "payout"})
            )
            # Flatline is the one failure mode nothing else can surface — the
            # container is up and the collector authenticates fine. It reached
            # the database and the notifier, but never this list, and on a
            # default install no notifier is configured (docker-compose.yml sets
            # none of the NTFY/WEBHOOK/TELEGRAM variables), so the only place the
            # user would ever see it was the one place it never went. The bell
            # said "All collectors healthy".
            alerts.extend(await _flatline_check())
            # Offline workers re-derived every rebuild, or the hourly wholesale
            # replacement of this list would silently un-report a dead machine.
            alerts.extend(await _offline_worker_alerts())
            _collector_alerts = alerts
            if collectors and platforms_ok == 0:
                # A run in which EVERY collector failed used to be recorded as
                # a SUCCESS: _collect_bounded converts exceptions into
                # EarningsResult.error, so the isinstance branch above never
                # fired and nothing else touched the flag. That refreshed
                # collection_last_success_timestamp hourly through a total
                # outage — both documented Prometheus alerts (CollectionFailing,
                # EarningsStale) were structurally unable to fire, proven by
                # execution. A PARTIAL failure stays a success: one chronically
                # broken collector must not freeze the staleness stamp and
                # false-alarm while fourteen others are collecting fine, and an
                # install with no collectors has nothing to be stale about.
                success = False
        except Exception as exc:
            logger.error("Collection run failed: %s", exc)
            success = False
            platforms_ok = 0
            # Keep the per-platform entries: the next run derives "which platforms were
            # failing" from this list, so clobbering it would make every platform
            # permanently unrecoverable — its stored alert would never be cleared and
            # its next real failure would be deduped into silence.
            _collector_alerts = [
                *(a for a in _collector_alerts if a.get("platform") != "collection"),
                {"platform": "collection", "error": "Collection run failed — see server logs"},
            ]
        finally:
            metrics.record_collection_end(start_time, success, platforms_ok, len(collectors))
            # Set even on a failed run: the bell's question is "has anything
            # looked", and a run that tried and failed HAS looked — its failure
            # is in the alert list the bell is about to show.
            global _collection_has_run
            _collection_has_run = True


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------


async def _run_data_retention() -> None:
    """Purge data older than 400 days."""
    try:
        deleted = await database.purge_old_data()
        if deleted:
            logger.info("Data retention: purged %d old rows", deleted)
    except Exception as exc:
        logger.warning("Data retention error: %s", exc)


async def _run_vacuum() -> None:
    """Reclaim disk left by retention deletes (SQLite does not auto-shrink)."""
    try:
        await database.vacuum_database()
        logger.info("Database VACUUM complete")
    except Exception as exc:
        logger.warning("Database VACUUM error: %s", exc)


async def _check_stale_workers() -> None:
    """Mark workers as offline if stale, and purge never-enrolled workers offline > 1 hour.

    A worker that HAS enrolled a per-worker key (``api_key_enc`` set) is never
    auto-deleted here, even after a long outage: the host persists that same
    key locally and re-presents it on its next heartbeat. Deleting the row
    would leave no match for that key, and since a confirmed worker's shared
    bootstrap key is refused too, it would be rejected forever with no way to
    re-enroll — a permanent fleet lockout after a reboot/maintenance window.
    Only a worker that never completed enrollment is purged automatically;
    removing an enrolled worker is a deliberate action via the UI.
    """
    try:
        workers = await database.list_workers()
    except Exception as exc:
        logger.warning("Stale worker check error: %s", exc)
        return
    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=STALE_WORKER_SECONDS)
    purge_cutoff = now - timedelta(hours=1)
    global _collector_alerts
    for w in workers:
        try:
            last_hb = w.get("last_heartbeat")
            if not last_hb:
                continue
            cid = w.get("client_id") or w["name"]
            last = datetime.fromisoformat(last_hb).replace(tzinfo=UTC)
            if w["status"] == "online" and last < cutoff:
                # Conditional on the heartbeat the decision was based on: a
                # recovery heartbeat landing between this sweep's read and its
                # write must win, or the worker would be alerted offline at its
                # exact moment of coming back.
                if not await database.mark_worker_offline_if_unchanged(w["id"], last_hb):
                    continue
                logger.info("Worker '%s' marked offline (last heartbeat: %s)", w["name"], last_hb)
                # The 42-hour incident, UI side: this transition used to be the
                # log line above and nothing else — the UI KNEW and told nobody.
                # Same alert/push/recovery pattern as a failing collector.
                await _raise_worker_offline_alert(w)
            elif w["status"] == "offline":
                if last < purge_cutoff and not w.get("api_key_enc"):
                    await database.delete_worker(w["id"])
                    logger.info("Purged stale unenrolled worker '%s' (offline since %s)", w["name"], last_hb)
                else:
                    # Still offline: re-attempt the durable alert. record_alert
                    # dedupes inside its window, so this is a no-op two minutes
                    # after a SUCCESSFUL insert — but an insert or push that
                    # FAILED at transition time (DB blip, notifier down) gets
                    # retried instead of being lost to the already-offline
                    # state, which used to make the miss permanent.
                    await _raise_worker_offline_alert(w)
            elif w["status"] == "online" and any(
                a.get("kind") == "worker" and a.get("client_id") == cid for a in _collector_alerts
            ):
                # Reconciliation: an online worker with a lingering worker
                # alert means a recovery clear failed or was missed (the
                # heartbeat route treats that clear as best-effort so a DB
                # hiccup can never fail a heartbeat). Finish the job here.
                await database.clear_alerts("worker", cid)
                _collector_alerts = [
                    a for a in _collector_alerts if not (a.get("kind") == "worker" and a.get("client_id") == cid)
                ]
                logger.info("Cleared lingering offline alert for recovered worker '%s'", w["name"])
        except Exception as exc:
            logger.warning("Stale worker check error for worker '%s': %s", w.get("name", w.get("id")), exc)


async def _raise_worker_offline_alert(w: dict[str, Any]) -> None:
    """Record + push + bell an offline worker, keyed by client_id.

    client_id is the identity, per this codebase's own rule: workers.name is
    the container hostname, cosmetic, mutable across recreates, and shareable
    by two hosts — keying alerts on it would let one worker suppress or clear
    another's. The display name travels in the message and title only.
    """
    cid = w.get("client_id") or w["name"]
    msg = (
        f"Worker '{w['name']}': no heartbeat for over {STALE_WORKER_SECONDS // 60} minutes. Its "
        "containers keep running and earning, but CashPilot cannot see or manage them until it reconnects."
    )
    if await database.record_alert("worker", cid, msg):
        _spawn(
            notify.send(
                f"CashPilot: worker '{w['name']}' went offline",
                msg,
                kind="worker",
                subject=cid,
            )
        )
    # Into the bell NOW (the sweep runs every 2 min); the hourly collection
    # rebuild re-derives it from the workers table.
    if not any(a.get("kind") == "worker" and a.get("client_id") == cid for a in _collector_alerts):
        _collector_alerts.append({"kind": "worker", "platform": w["name"], "client_id": cid, "error": msg})


FLEET_API_KEY = fleet_key.resolve_fleet_key()
HOSTNAME_PREFIX = os.getenv("CASHPILOT_HOSTNAME_PREFIX", "cashpilot")
COLLECT_INTERVAL_MIN = int(os.getenv("CASHPILOT_COLLECT_INTERVAL", "60"))
STALE_WORKER_SECONDS = 180  # Mark worker offline after 3 missed heartbeats


async def _warm_session_epochs() -> None:
    """Restore the in-memory per-user session-epoch cache from durable state.

    Two sources are merged, taking the later timestamp per user:
      - ``users.password_changed_at`` — a password change invalidates older sessions.
      - ``session_revocations.revoked_before`` — a delete/demote invalidates older
        sessions and survives the users row being deleted.

    This runs at startup so those invalidations survive a UI restart. Without the
    revocation half, a delete/demote (which only bumps the in-memory epoch) would be
    forgotten on the next restart and the account's still-valid cookie would be
    honored again with its old role — the bug this fixes.
    """
    epochs: dict[int, float] = {}
    for _u in await database.list_users_with_pwd_epoch():
        changed = _u.get("password_changed_at") or 0.0
        if changed:
            epochs[_u["id"]] = changed
    for _r in await database.list_session_revocations():
        uid = _r["user_id"]
        epochs[uid] = max(epochs.get(uid, 0.0), _r["revoked_before"] or 0.0)
    for uid, ts in epochs.items():
        auth.set_user_pwd_epoch(uid, ts)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    # Before anything touches credentials: refuse to run when the encryption key
    # cannot survive a restart. Continuing would encrypt every credential entered
    # during this run under a key that dies with the process.
    database.verify_encryption_key_persisted()
    await database.init_db()
    await database.connect_shared()
    # Warm the per-user session-epoch cache (password changes + delete/demote
    # revocations) so invalidated sessions are rejected without a DB hit in the
    # request path — and, crucially, so those invalidations survive a restart.
    await _warm_session_epochs()
    # Restore the collector alerts persisted by earlier runs, so a restart doesn't
    # silently clear the notification bell while the underlying collector is still
    # broken (previously these lived only in memory).
    await _warm_collector_alerts()
    # Credentials saved before saving them began creating a tracking row are
    # otherwise inert forever, while Settings shows them as "Configured".
    await _track_fully_configured_services()
    # First-run setup token: while no users exist, require a one-time token
    # (printed below) for /register so a proxy-exposed instance cannot be seized
    # by the first public visitor. Persisted in config so it survives restarts;
    # cleared once the owner account is created.
    if not await database.has_any_users():
        _tok = await database.get_config("_setup_token")
        if not _tok:
            _tok = setup_token.generate()
            await database.set_config("_setup_token", _tok)
        setup_token.set_active(_tok)
        logger.warning(
            "FIRST-RUN SETUP: no account exists yet. Open /register and enter this "
            "one-time setup token to create the owner account: %s  (shown only here; "
            "not embedded in any URL so it stays out of proxy logs and browser history)",
            _tok,
        )
    if not notify.is_enabled():
        # The push path exists so problems reach someone when nobody is
        # watching the dashboard — and a default install has never armed it.
        # Say so once, loudly, in the same place the setup token announces
        # itself; anything quieter and this line is its own counterexample.
        logger.warning(
            "No notification channel configured — alerts will only appear in the UI bell, "
            "which somebody has to open. Set CASHPILOT_NTFY_URL, CASHPILOT_WEBHOOK_URL or "
            "the CASHPILOT_TELEGRAM_* variables to get collector failures, offline workers "
            "and payout prompts pushed out-of-band."
        )

    catalog.load_services()
    catalog.register_sighup()

    def _on_job_event(event):
        logger.error("Scheduler job %s failed or missed", event.job_id, exc_info=getattr(event, "exception", None))

    scheduler.add_listener(_on_job_event, EVENT_JOB_ERROR | EVENT_JOB_MISSED)
    scheduler.add_job(
        _run_collection,
        "interval",
        minutes=COLLECT_INTERVAL_MIN,
        id="collect",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _run_health_check,
        "interval",
        minutes=5,
        id="health_check",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _check_stale_workers,
        "interval",
        minutes=2,
        id="stale_workers",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _run_data_retention,
        "interval",
        hours=24,
        id="data_retention",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _run_vacuum,
        "interval",
        weeks=1,
        id="db_vacuum",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    # Once a day. A release is not urgent, and a self-hosted app polling a third
    # party more often than that is rude. Every failure mode inside refresh()
    # lands on UNKNOWN, so a firewalled install produces no noise at all.
    scheduler.add_job(
        update_check.refresh,
        "interval",
        hours=24,
        id="update_check",
        max_instances=1,
        coalesce=True,
        # 300 like every other job here rather than a carve-out. A missed daily
        # check simply happens tomorrow; that is not worth an exception to a
        # convention a test enforces uniformly.
        misfire_grace_time=300,
    )
    # The Android client's own release track, on the same daily cadence and with
    # the same failure contract. Separate job rather than folded into the one
    # above so a GitHub hiccup fetching one cannot suppress the other.
    scheduler.add_job(
        update_check.refresh_android,
        "interval",
        hours=24,
        id="update_check_android",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        exchange_rates.refresh,
        "interval",
        minutes=15,
        id="exchange_rates",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.start()
    await exchange_rates.refresh()
    # Kick both release checks NOW rather than waiting out the first 24-hour
    # interval. APScheduler's interval trigger does not fire on start, and this
    # container is recreated on every deploy -- so on an install that ships more
    # often than daily the check would never run at all, and the update banner
    # would sit permanently at known=false. Spawned, not awaited: a slow or
    # unreachable GitHub must not delay startup, and every failure inside these
    # already lands on UNKNOWN.
    _spawn(update_check.refresh())
    _spawn(update_check.refresh_android())
    _spawn(_run_collection())
    logger.info("CashPilot UI started (container ops via workers)")

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    await database.close_shared()
    from app.collectors import close_all_collectors

    await close_all_collectors()
    logger.info("CashPilot stopped")


app = FastAPI(
    title="CashPilot",
    version=version.current(),
    lifespan=lifespan,
    # Off by default. FastAPI serves these unauthenticated, and this app's
    # schema is a map of its own admin surface — every route, parameter and
    # body shape, including the worker and payout endpoints. Nothing here
    # needs them in a self-hosted deployment.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
metrics.setup(app)


# Whether a trusted reverse proxy sits in front (opt-in). Only then do we believe an
# X-Forwarded-Proto header for deciding HTTPS (matches app.deps._TRUST_PROXY semantics;
# read here directly to avoid importing deps into the middleware).
_HSTS_TRUST_PROXY = os.getenv("CASHPILOT_TRUSTED_PROXY", "").strip().lower() in ("1", "true", "yes", "on")


# Security headers middleware
class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # A fresh nonce per response. Templates read it via request.state so the
        # value in the header and the value in the markup can never disagree —
        # if they did, every inline script would be blocked and the UI would
        # simply stop working.
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # script-src no longer allows 'unsafe-inline' (bead guw). Inline event
        # handlers are gone — every control goes through one delegated listener —
        # and the few remaining inline <script> blocks carry a per-response
        # nonce. That matters because this UI renders provider-supplied strings:
        # with 'unsafe-inline', any markup an attacker gets into one of those
        # executes.
        #
        # style-src keeps 'unsafe-inline' for now: the templates carry inline
        # style= attributes, which a nonce cannot cover, and a style injection
        # cannot execute script. Narrower than script, and honest about staying.
        #
        # base-uri/object-src/form-action are additive hardening that costs
        # nothing: block <base> hijack of relative script URLs, disallow plugins,
        # and stop a form POSTing credentials off-origin if an XSS is ever found.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src 'self' https://cdn.jsdelivr.net 'nonce-{nonce}'; "
            "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self' https://cdn.jsdelivr.net; "
            "frame-ancestors 'none'; "
            "base-uri 'none'; "
            "object-src 'none'; "
            "form-action 'self'"
        )
        # HSTS only when the request is actually HTTPS, so plain-HTTP local dev is never
        # pinned to https (which would hard-break it). Behind a trusted proxy that
        # terminates TLS the app sees http, so honor X-Forwarded-Proto there.
        proto = request.headers.get("x-forwarded-proto") if _HSTS_TRUST_PROXY else request.url.scheme
        if proto == "https":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response


app.add_middleware(_SecurityHeadersMiddleware)


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's 422 body echoes the offending input, and some inputs cannot be
    encoded — so the rejection itself became a 500.

    JSON has no ``NaN`` or ``Infinity``. Python's parser accepts them anyway, so
    a client can put one in a float field; pydantic correctly rejects it, and
    then the default handler tries to serialise ``{"input": nan}`` and Starlette's
    encoder raises "Out of range float values are not JSON compliant". The client
    gets an opaque 500 for what is squarely a bad request, and the log fills with
    a traceback that names the encoder rather than the cause.

    Non-finite floats are therefore rendered as their names. That keeps the
    message diagnostic ("we saw NaN") instead of dropping the field, and it fixes
    the whole class rather than the one endpoint that happens to take a float
    today. Every other error is passed through byte-for-byte, so the response
    shape callers already parse is unchanged.
    """
    # jsonable_encoder FIRST, exactly as FastAPI's own handler does: a custom
    # validator's error carries the raised ValueError OBJECT in ctx, which is not
    # serialisable either. Encoding then sanitising fixes both without changing
    # the body for any error that was already fine.
    return JSONResponse(status_code=422, content={"detail": _json_safe(jsonable_encoder(exc.errors()))})


def _json_safe(value: Any) -> Any:
    """Recursively replace values the JSON encoder refuses — currently only
    non-finite floats.

    Deliberately narrow. ``bool`` needs no special case: it subclasses ``int``,
    not ``float``, so the check below never sees it. An earlier version guarded
    for it anyway, with a comment that was simply wrong; a negative control
    showed removing the guard changed nothing, so it went.
    (``test_booleans_survive_as_booleans`` still pins the guarantee.)
    """
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)  # "nan", "inf", "-inf"
    return value


# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")


# ---------------------------------------------------------------------------
# Auth helpers + templates (shared, defined in app.deps).
#
# Imported here so ``app.main._require_owner`` / ``app.main.templates`` keep
# resolving for tests and for the split router groups, which reference them
# through the ``app.main`` namespace (e.g. ``main._require_owner``).
# ---------------------------------------------------------------------------
from app.deps import (  # noqa: E402
    _login_redirect,  # noqa: F401  (re-exported for app.main.* test/router surface)
    _require_auth_api,
    _require_first_run_access,  # noqa: F401  (re-exported for app.main.* router surface)
    _require_owner,
    _require_private_network,  # noqa: F401  (re-exported for app.main.* router surface)
    _require_reader,
    _require_writer,
    client_ip,  # noqa: F401  (re-exported for app.main.* router surface)
    templates,  # noqa: F401  (re-exported for app.main.* router/test surface)
)

# ---------------------------------------------------------------------------
# API: Services
# ---------------------------------------------------------------------------


@app.get("/api/mode")
async def api_mode(request: Request) -> dict[str, Any]:
    """Return CashPilot operating mode and Docker availability."""
    _require_auth_api(request)
    return {"docker": False, "mode": "ui"}


@app.get("/api/services")
async def api_list_services(request: Request) -> list[dict[str, Any]]:
    _require_auth_api(request)
    return catalog.get_services()


def _collector_needs_setup(slug: str, config: dict[str, str]) -> bool:
    """True if `slug` has an earnings collector whose required config is unset.

    A service can be deployed and earning while CashPilot still can't read its
    balance because the (separate) collector credentials haven't been entered.
    This distinguishes that "not set up yet" state from a real collector error.
    """
    from app.collectors import _COLLECTOR_ARGS, COLLECTOR_MAP

    if slug not in COLLECTOR_MAP:
        return False
    for arg in _COLLECTOR_ARGS.get(slug, []):
        if arg.startswith("?"):  # optional arg — not required for setup
            continue
        if not config.get(f"{slug}_{arg}", ""):
            return True
    return False


# Catalog statuses a service must never be deployed with. Shared by the catalog
# listing (which hides them) and the deploy gate (which refuses them) so the two
# can't drift apart again — previously the listing hid all three but deploy only
# refused "dead", so a direct link or a stale page could still deploy a broken or
# dropped service and then silently earn nothing.
_UNDEPLOYABLE_STATUSES = frozenset({"broken", "dead", "dropped"})


def _split_image(ref: str) -> tuple[str, str, str]:
    """Split a Docker image reference into (repository, tag, digest)."""
    digest = ""
    if "@" in ref:
        ref, digest = ref.split("@", 1)
    repo, tag = ref, ""
    # A ':' is a tag only if it comes after the last '/', else it's a registry port.
    last_colon = ref.rfind(":")
    if last_colon > ref.rfind("/"):
        repo, tag = ref[:last_colon], ref[last_colon + 1 :]
    return repo, tag, digest


def _image_outdated(deployed: str, catalog_image: str) -> bool:
    """True when a running container's image no longer matches the catalog entry.

    Flags the case a provider changed its image path (the ProxyBase migration) or the
    catalog re-pinned to a new digest — so the dashboard can prompt a re-deploy instead
    of showing a healthy-looking container that is silently running a retired image.
    Deliberately conservative: unknown/empty images and a pure tag-vs-digest difference
    of the same repository are NOT flagged.
    """
    if not deployed or not catalog_image:
        return False
    d_repo, _, d_digest = _split_image(deployed)
    c_repo, _, c_digest = _split_image(catalog_image)
    if d_repo != c_repo:
        return True
    return bool(c_digest and d_digest and c_digest != d_digest)


def _apply_service_meta(entry: dict[str, Any], svc: dict[str, Any] | None) -> None:
    """Attach the catalog-derived cashout / referral / website fields to a deployed
    entry. Shared by the container-backed and external paths; a no-op when the catalog
    no longer lists the deployed slug."""
    if not svc:
        return
    cashout = svc.get("cashout", {})
    if cashout:
        entry["cashout"] = cashout
    referral = svc.get("referral", {})
    if referral:
        entry["referral_url"] = referral.get("signup_url", "")
    entry["website"] = svc.get("website", "")


@app.get("/api/services/deployed")
async def api_services_deployed(request: Request) -> list[dict[str, Any]]:
    """Return deployed services with container status, balance, CPU, memory.

    Multiple containers for the same slug (multi-node) are aggregated into a
    single row with summed CPU/memory, an instance count, and per-instance
    details for the expandable sub-row UI.
    """
    _require_reader(request)
    statuses: list[dict[str, Any]] = await _get_all_worker_containers()

    # Get latest earnings per platform for balance display
    earnings = await database.get_earnings_summary()
    balance_map = {e["platform"]: e["balance"] for e in earnings}
    currency_map = {e["platform"]: e["currency"] for e in earnings}

    # Get health scores
    health_scores = await database.get_health_scores(7)
    health_map = {h["slug"]: h for h in health_scores}

    # Build set of slugs with collector errors (disconnected)
    alert_slugs = {a["platform"] for a in _collector_alerts}

    # Config (decrypted) to detect collectors whose credentials aren't set yet.
    # A config-read failure must not blank the dashboard — degrade to "unknown".
    config: dict[str, str] = {}
    try:
        cfg = await database.get_config()
        if isinstance(cfg, dict):
            config = cfg
    except Exception as exc:
        logger.warning("Could not load config for collector-setup check: %s", exc)

    # Aggregate by slug: one row per service
    # "unknown" ranks LAST on purpose: best_status picks the lowest number, so a
    # service that is running on one worker and unknown on another reports
    # running -- a known fact beats a blind spot. It only wins when nothing else
    # is known, which is the honest answer at that point.
    # "stopped" is what _android_app_status emits; Docker's own word is "exited".
    # It MUST be listed: an unlisted status falls through to .get(cur, 9), and
    # with unknown ranked 5 a blind spot would have beaten a definite stopped --
    # the exact inverse of the rule below. (CodeRabbit, PR #252.)
    #
    # "unknown" ranks LAST on purpose: best_status picks the lowest number, so a
    # service running on one worker and unknown on another reports running -- a
    # known fact beats a blind spot. It only wins when nothing else is known.
    _STATUS_PRIORITY = {
        "running": 0,
        "restarting": 1,
        "exited": 2,
        "stopped": 2,
        "created": 3,
        "dead": 4,
        "unknown": 5,
    }
    slug_agg: dict[str, dict[str, Any]] = {}
    for s in statuses:
        slug = s["slug"]
        if slug not in slug_agg:
            slug_agg[slug] = {
                "instances": [],
                "total_cpu": 0.0,
                "total_mem": 0.0,
                "best_status": s.get("status", "unknown"),
                "image": s.get("image", ""),
            }
        agg = slug_agg[slug]
        agg["instances"].append(s)
        # Unknown instances are counted separately rather than summed as zero:
        # averaging a failed stats read into the total drags the figure toward
        # zero and makes a busy service look idle. `.get(key, 0)` does not help
        # here — the key EXISTS with value None, so the default never applies.
        cpu, mem = s.get("cpu_percent"), s.get("memory_mb")
        if cpu is None or mem is None:
            agg["unknown_stats"] = agg.get("unknown_stats", 0) + 1
        else:
            agg["total_cpu"] += float(cpu)
            agg["total_mem"] += float(mem)
            agg["measured"] = agg.get("measured", 0) + 1
        cur = s.get("status", "unknown")
        if _STATUS_PRIORITY.get(cur, 9) < _STATUS_PRIORITY.get(agg["best_status"], 9):
            agg["best_status"] = cur

    result = []
    for slug, agg in slug_agg.items():
        svc = catalog.get_service(slug)
        health = health_map.get(slug, {})

        # Build per-instance detail list (local first)
        instance_details = []
        for inst in agg["instances"]:
            detail = {
                "node": inst.get("_node", "unknown"),
                "worker_id": inst.get("_worker_id"),
                "status": inst.get("status", "unknown"),
                # None reaches the UI as null, which renders as an em dash. A
                # formatted "0.00" would be indistinguishable from a real idle
                # container.
                "cpu": None if inst.get("cpu_percent") is None else f"{float(inst['cpu_percent']):.2f}",
                "memory": None if inst.get("memory_mb") is None else f"{float(inst['memory_mb']):.1f} MB",
                "container_name": inst.get("name", ""),
                "has_docker": inst.get("_has_docker", False),
                "is_android": inst.get("_is_android", False),
                # Started outside CashPilot: it has no CashPilot label, so the
                # container commands cannot target it and the UI must not offer
                # them.
                "unmanaged": inst.get("deployed_by") == "external",
            }
            if inst.get("_is_android"):
                detail["net_tx_24h"] = inst.get("_net_tx_24h", 0)
                detail["net_rx_24h"] = inst.get("_net_rx_24h", 0)
            instance_details.append(detail)
        # Sort: local first, then alphabetically by node name
        instance_details.sort(key=lambda x: (0 if x["node"] == "local" else 1, x["node"]))

        entry = {
            "slug": slug,
            "name": svc["name"] if svc else slug,
            "container_status": agg["best_status"],
            # True only when EVERY instance was started outside CashPilot. With
            # a mix, the managed one can still be controlled, so the row keeps
            # its buttons and the per-instance flag marks the odd one out.
            "unmanaged": bool(agg["instances"]) and all(i.get("deployed_by") == "external" for i in agg["instances"]),
            # None, not 0.0, when CashPilot has never read this service.
            #
            # A missing earnings row means "no reading", and rendering it as
            # $0.00 told the user a service was running and earning nothing —
            # when the truth was that nothing had ever looked. Neither
            # suppressor fires in that state: collector_disconnected needs an
            # alert (none was raised, because no collector ran) and
            # collector_needs_setup only checks whether config keys are filled.
            # The flatline detector cannot catch it either: it skips rows whose
            # max balance is 0.
            #
            # This is the same defect filed three times by the audit
            # (CashPilot-vp6, -ikh, -7qk) from three different areas.
            "balance": balance_map.get(slug),
            "balance_known": slug in balance_map,
            "currency": currency_map.get(slug, "USD"),
            # None when NOTHING could be measured. A row whose every instance
            # failed its stats read must not show 0.00 — that is the same
            # fabricated idle as the per-instance case. When some instances were
            # readable the total is real, and stats_unknown says how many were
            # left out of it.
            "cpu": f"{agg['total_cpu']:.2f}" if agg.get("measured") else None,
            "memory": f"{agg['total_mem']:.1f} MB" if agg.get("measured") else None,
            "stats_unknown": agg.get("unknown_stats", 0),
            "image": agg["image"],
            "category": agg["instances"][0].get("category", ""),
            "health_score": health.get("score"),
            "uptime_pct": health.get("uptime_pct"),
            "restarts_7d": health.get("restarts", 0),
            "crashes_7d": health.get("crashes", 0),
            # "unstable" flags a service that has crashed repeatedly in the health window
            # so the dashboard can surface it at a glance (not just via the score number).
            "unstable": health.get("crashes", 0) >= 3,
            "instances": len(agg["instances"]),
            "instance_details": instance_details,
            "collector_disconnected": slug in alert_slugs,
            "collector_needs_setup": slug not in alert_slugs and _collector_needs_setup(slug, config),
            # True when the running container's image no longer matches the catalog
            # (provider migrated / re-pinned) — the dashboard prompts a re-deploy so a
            # retired image doesn't keep looking healthy while it silently stops earning.
            "image_outdated": False,
        }
        _apply_service_meta(entry, svc)
        if svc:
            entry["image_outdated"] = _image_outdated(agg["image"], (svc.get("docker") or {}).get("image", ""))
        result.append(entry)

    # Include external services (no Docker container, e.g. Grass, Bytelixir)
    seen_slugs = {r["slug"] for r in result}
    deployments = await database.get_deployments()
    for d in deployments:
        slug = d["slug"]
        if slug in seen_slugs:
            continue
        if d.get("status") != "external":
            continue
        svc = catalog.get_service(slug)
        health = health_map.get(slug, {})
        entry = {
            "slug": slug,
            "name": svc["name"] if svc else slug,
            "container_status": "external",
            # None, not 0.0, when CashPilot has never read this service.
            #
            # A missing earnings row means "no reading", and rendering it as
            # $0.00 told the user a service was running and earning nothing —
            # when the truth was that nothing had ever looked. Neither
            # suppressor fires in that state: collector_disconnected needs an
            # alert (none was raised, because no collector ran) and
            # collector_needs_setup only checks whether config keys are filled.
            # The flatline detector cannot catch it either: it skips rows whose
            # max balance is 0.
            #
            # This is the same defect filed three times by the audit
            # (CashPilot-vp6, -ikh, -7qk) from three different areas.
            "balance": balance_map.get(slug),
            "balance_known": slug in balance_map,
            "currency": currency_map.get(slug, "USD"),
            "cpu": "",
            "memory": "",
            "image": "",
            "category": svc.get("category", "") if svc else "",
            "health_score": None,
            "uptime_pct": None,
            "restarts_7d": 0,
            "crashes_7d": 0,
            "unstable": False,
            "instances": 0,
            "instance_details": [],
            "collector_disconnected": slug in alert_slugs,
            "collector_needs_setup": slug not in alert_slugs and _collector_needs_setup(slug, config),
        }
        _apply_service_meta(entry, svc)
        result.append(entry)

    return result


@app.get("/api/services/available")
async def api_services_available(request: Request) -> list[dict[str, Any]]:
    """Return available services from catalog, enriched with deployment status."""
    _require_auth_api(request)
    services = catalog.get_services()
    deployments = await database.get_deployments()
    deployed_slugs = {d["slug"] for d in deployments}
    # Imported here rather than at module scope: app.collectors pulls in every
    # collector module.
    from app.collectors import COLLECTOR_MAP as collector_map

    # Also check worker containers for deployed status (catches externally-deployed services)
    worker_containers = await _get_all_worker_containers()
    worker_slugs: set[str] = set()
    worker_node_counts: dict[str, set[str]] = {}
    for c in worker_containers:
        slug = c.get("slug", "")
        if slug:
            worker_slugs.add(slug)
            node = c.get("_node", "unknown")
            if slug not in worker_node_counts:
                worker_node_counts[slug] = set()
            worker_node_counts[slug].add(node)

    available = []
    for svc in services:
        if svc.get("status") in _UNDEPLOYABLE_STATUSES:
            continue  # Known non-functional — hide completely
        docker_conf = svc.get("docker", {})
        has_image = bool(docker_conf and docker_conf.get("image"))
        slug = svc.get("slug", "")
        svc["deployed"] = slug in deployed_slugs or slug in worker_slugs
        svc["manual_only"] = not has_image
        svc["node_count"] = len(worker_node_counts.get(slug, set()))
        # The setup wizard reads this endpoint, and it needs to know whether
        # earnings tracking takes a SECOND set of credentials — the service
        # detail view already says so, and the wizard is the screen a new user
        # actually sees (CashPilot-p6s).
        svc["has_collector"] = slug in collector_map
        available.append(svc)
    return available


@app.get("/api/services/{slug}")
async def api_get_service(request: Request, slug: str) -> dict[str, Any]:
    _require_auth_api(request)
    svc = catalog.get_service(slug)
    if not svc:
        raise HTTPException(status_code=404, detail=f"Service '{slug}' not found")

    # Enrich with deployment status (same logic as /api/services/available)
    deployments = await database.get_deployments()
    deployed_slugs = {d["slug"] for d in deployments}
    worker_containers = await _get_all_worker_containers()
    worker_slugs = {c["slug"] for c in worker_containers if c.get("slug")}
    worker_nodes: set[str] = set()
    for c in worker_containers:
        if c.get("slug") == slug:
            worker_nodes.add(c.get("_node", "unknown"))

    svc["deployed"] = slug in deployed_slugs or slug in worker_slugs
    svc["node_count"] = len(worker_nodes)

    # Flag whether earnings tracking uses separate credentials (entered in
    # Settings → Collectors), so the deploy UI can tell users the container
    # credentials alone won't populate the in-dashboard balance.
    from app.collectors import COLLECTOR_MAP

    svc["has_collector"] = slug in COLLECTOR_MAP
    return svc


# ---------------------------------------------------------------------------
# API: Container management
# ---------------------------------------------------------------------------


@app.get("/api/status")
async def api_status(request: Request) -> list[dict[str, Any]]:
    """Return container statuses from all workers."""
    _require_auth_api(request)
    return await _get_all_worker_containers()


class DeployRequest(BaseModel):
    env: dict[str, str] = {}
    hostname: str | None = None


@app.post("/api/deploy/{slug}")
async def api_deploy(
    request: Request,
    slug: str,
    body: DeployRequest,
    worker_id: int | None = None,
    _auth: dict[str, Any] = Depends(_require_owner),
) -> dict[str, Any]:
    # dict[str, Any], not dict[str, str]: kept_from_previous_deployment is a
    # list, and FastAPI validates the response against this annotation AFTER
    # the deploy has run and persisted — a stricter type turns the successful
    # deployments that had something to report into 500s.
    worker_id = await _resolve_worker_id(worker_id)
    svc = catalog.get_service(slug)
    if not svc:
        raise HTTPException(status_code=404, detail=f"Service '{slug}' not found")
    status = svc.get("status")
    if status in _UNDEPLOYABLE_STATUSES:
        # 410 for a service that is permanently gone, 409 for one that is merely
        # broken right now and may come back. Both are hidden from the catalog
        # listing, so reaching here means a direct link, a stale page or an API client.
        raise HTTPException(
            status_code=409 if status == "broken" else 410,
            detail=f"Service '{slug}' is no longer available for deployment ({status})",
        )

    docker_conf = svc.get("docker", {})
    image = docker_conf.get("image")
    if not image:
        raise HTTPException(status_code=400, detail=f"Service '{slug}' has no Docker image")

    # Build full env: YAML defaults + user overrides + {hostname} substitution.
    #
    # The substitution runs LAST, over the merged result, because it used to run
    # only over the defaults — and the setup wizard prefills each input with the
    # raw default, so the browser posts "cashpilot-{hostname}" back as a USER
    # value. A user value wins over the default, so the placeholder was never
    # substituted and the literal string shipped as the device name. Providers
    # count devices by that name, so every host deployed through the wizard
    # registered under one identical name.
    #
    # Applying it to overrides too is also the right reading of a value someone
    # typed by hand: nobody means the eight characters "{hostname}".
    hn = body.hostname or HOSTNAME_PREFIX
    env: dict[str, str] = {}
    for var in docker_conf.get("env", []):
        env[var["key"]] = str(var.get("default", ""))
    env.update(body.env or {})
    env = {k: v.replace("{hostname}", hn) if isinstance(v, str) else v for k, v in env.items()}

    # What this service was ACTUALLY deployed with, if anything. Loaded before
    # the required-field check because a redeploy must not demand values the
    # deployment already has: rejecting here would mean the operator has to
    # retype Storj's IDENTITY_DIR/STORAGE_DIR on every redeploy, which is
    # precisely what recording the spec exists to avoid.
    recorded = await database.get_deployment_spec(slug)
    recorded_env = (recorded or {}).get("env") or {}

    # Validate required env vars are not blank.
    missing = [
        var.get("label", var["key"])
        for var in docker_conf.get("env", [])
        if var.get("required")
        and not env.get(var["key"], "").strip()
        and not str(recorded_env.get(var["key"], "")).strip()
    ]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required fields: {', '.join(missing)}")

    # Ports — key is "container_port/protocol" per Docker SDK
    ports: dict[str, int] = {}
    for mapping in docker_conf.get("ports", []):
        raw = str(mapping)
        if ":" not in raw:
            continue
        parts = raw.split(":")
        host_port = int(parts[0])
        container_part = parts[1]  # e.g. "28967/tcp" or "28967"
        if "/" not in container_part:
            container_part += "/tcp"
        ports[container_part] = host_port

    # Volumes: resolve ${VAR} in host paths using env
    volumes: dict[str, dict[str, str]] = {}
    for mapping in docker_conf.get("volumes", []):
        if ":" in str(mapping):
            parts = str(mapping).split(":")
            host_path = re.sub(r"\$\{(\w+)\}", lambda m: env.get(m.group(1), m.group(0)), parts[0])
            container_path = parts[1]
            mode = parts[2] if len(parts) > 2 else "rw"
            volumes[host_path] = {"bind": container_path, "mode": mode}

    spec: dict[str, Any] = {
        "image": image,
        "env": env,
        "hostname": body.hostname,
        "ports": ports,
        "volumes": volumes,
        "network_mode": docker_conf.get("network_mode") or None,
        "cap_add": docker_conf.get("cap_add") or None,
        # Some services need a device, not just a capability: Mysterium cannot
        # carry wireguard traffic without /dev/net/tun, and without it the node
        # starts, registers and earns nothing.
        "devices": docker_conf.get("devices") or None,
        "privileged": docker_conf.get("privileged", False),
    }

    # Command: resolve ${VAR} placeholders
    raw_command = docker_conf.get("command") or None
    if raw_command:
        spec["command"] = re.sub(r"\$\{(\w+)\}", lambda m: env.get(m.group(1), m.group(0)), raw_command)

    # Durable resource limits (mem_limit / mem_reservation / oom_score_adj /
    # cpu_shares), declared in the service YAML. Only forwarded when present.
    resources = docker_conf.get("resources")
    if resources:
        spec["resources"] = resources

    # An existing deployment is rebuilt from what it actually ran, not from the
    # catalog - see _merge_recorded_spec. `recorded` was loaded above, before the
    # required-field check.
    divergence: list[str] = []
    if recorded:
        # Which env vars feed which mount, so a relocation applies only to the
        # mount it actually names.
        keys_by_target: dict[str, set[str]] = {}
        for mapping in docker_conf.get("volumes", []):
            raw = str(mapping)
            if ":" not in raw:
                continue
            host_part, target = raw.split(":")[0], raw.split(":")[1]
            keys_by_target.setdefault(target, set()).update(m.group(1) for m in re.finditer(r"\$\{(\w+)\}", host_part))
        spec, divergence = _merge_recorded_spec(spec, recorded, body.env or {}, keys_by_target)
        if divergence:
            logger.info("Redeploying %s from its recorded spec: %s", slug, "; ".join(divergence))

    result = await _proxy_worker_deploy(worker_id, slug, spec)
    container_id = result.get("container_id", "remote")
    await database.save_deployment(slug=slug, container_id=container_id, spec=spec)
    await database.record_health_event(slug, "start", f"deployed to worker {worker_id}")
    metrics.record_container_lifecycle("deploy", slug)
    _spawn(_run_collection())
    response: dict[str, Any] = {"status": "deployed", "container_id": container_id}
    if divergence:
        response["kept_from_previous_deployment"] = divergence
    return response


def _merge_recorded_spec(
    catalog_spec: dict[str, Any],
    recorded: dict[str, Any],
    user_env: dict[str, str],
    volume_env_keys_by_target: dict[str, set[str]] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Rebuild an EXISTING deployment from what it actually ran.

    The catalog describes what a NEW deployment looks like. It does not describe
    what this one looks like: the running container may sit on a bind mount
    where the catalog declares a named volume, or on a host path that only
    existed because of an env substitution. Rebuilding from the catalog silently
    produces a different container, and the worker destroys the old one before
    anything can compare them - which is how a node identity gets orphaned.

    So for an existing service the record wins, with two deliberate exceptions:
    the image always comes from the catalog (otherwise upgrades could never
    land), and anything the user explicitly typed on this deploy wins over the
    stored value (otherwise a credential could never be corrected).

    Returns the merged spec and a list of human-readable divergences, which are
    information for the operator rather than something to resolve silently.
    """
    merged = dict(catalog_spec)
    divergence: list[str] = []

    # Ports define the container's identity on the network. Reproduce them.
    stored_ports = recorded.get("ports")
    if stored_ports:
        if stored_ports != catalog_spec.get("ports"):
            divergence.append(
                "ports: keeping the ports this service was deployed with; the catalog now declares different ports"
            )
        merged["ports"] = stored_ports

    # Mounts are decided PER MOUNT, not for the volumes block as a whole.
    #
    # If the operator typed a value this deploy that the catalog substitutes into
    # a host path - Storj's ${IDENTITY_DIR}, say - they are moving that data on
    # purpose and the new path wins. Every OTHER mount is still reproduced from
    # the record: a service can have several independent path variables (Storj
    # has IDENTITY_DIR and STORAGE_DIR), and supplying one must not silently
    # reset the others.
    #
    # The trigger is the volume-substituting keys alone. Retyping a password must
    # never cost a service its mounts, which is the bug this function exists to
    # fix in the first place.
    stored_volumes = recorded.get("volumes")
    if stored_volumes:
        by_target = volume_env_keys_by_target or {}
        catalog_volumes = catalog_spec.get("volumes") or {}
        catalog_by_target = {spec.get("bind"): (host, spec) for host, spec in catalog_volumes.items()}
        recorded_targets = {spec.get("bind") for spec in stored_volumes.values()}

        merged_volumes: dict[str, Any] = {}
        moved: list[str] = []
        kept = False

        for host, spec in stored_volumes.items():
            target = spec.get("bind")
            if set(user_env) & by_target.get(target, set()):
                new_host, new_spec = catalog_by_target.get(target, (host, spec))
                merged_volumes[new_host] = new_spec
                moved.append(target)
            else:
                merged_volumes[host] = spec
                if catalog_by_target.get(target, (host, spec)) != (host, spec):
                    kept = True

        # Mounts the catalog has added since this service was deployed.
        for target, (host, spec) in catalog_by_target.items():
            if target not in recorded_targets:
                merged_volumes[host] = spec

        if moved:
            divergence.append(f"mounts: using the paths you supplied this deploy for {', '.join(sorted(moved))}")
        if kept:
            divergence.append(
                "mounts: keeping the mounts this service was deployed with; the catalog now declares different mounts"
            )
        merged["volumes"] = merged_volumes

    # Runtime shape that the catalog may since have changed underneath a
    # running service. hostname is included because several bandwidth services
    # key their device identity to the container hostname: on a redeploy where
    # the operator leaves the hostname field empty, catalog_spec["hostname"] is
    # None, and rebuilding from that would silently give the service a new
    # identity. As with env, a hostname the operator typed THIS deploy still
    # wins - a non-empty catalog_spec value is what they just asked for.
    for field in ("command", "network_mode", "cap_add"):
        if field in recorded and recorded.get(field) != catalog_spec.get(field):
            divergence.append(f"{field}: keeping the deployed value")
            merged[field] = recorded[field]

    # resources is merged per KEY, unlike the runtime-shape fields above, and
    # for the env reason: limits carry no deployment identity, and the catalog
    # is where NEW tuning keys land (a value change to a key the record
    # already set still keeps the recorded value, reported as a divergence).
    # Whole-dict recorded-wins made every catalog
    # resource change unreachable for a deployed service — the record predating
    # a new key (cpu_shares) beat the catalog forever, and the only escape was
    # remove-and-redeploy, which for storj is the identity-loss operation the
    # recorded spec exists to prevent. A key the record already set still wins:
    # that is the value this deployment verifiably ran with.
    stored_res = recorded.get("resources")
    if isinstance(stored_res, dict):
        catalog_res = catalog_spec.get("resources")
        merged_res = dict(catalog_res) if isinstance(catalog_res, dict) else {}
        merged_res.update(stored_res)
        if merged_res != (catalog_res or {}):
            divergence.append("resources: keeping the limits this service was deployed with")
        if merged_res:
            merged["resources"] = merged_res

    stored_hostname = recorded.get("hostname")
    if stored_hostname and not catalog_spec.get("hostname") and stored_hostname != catalog_spec.get("hostname"):
        divergence.append("hostname: keeping the hostname this service was deployed with")
        merged["hostname"] = stored_hostname

    # env: catalog defaults provide any newly added keys, the record provides
    # what this deployment actually used, and an explicit entry from the user
    # overrides both.
    stored_env = recorded.get("env")
    if isinstance(stored_env, dict):
        env = dict(catalog_spec.get("env") or {})
        for key, value in stored_env.items():
            if key not in user_env:
                env[key] = value
        merged["env"] = env

    return merged, divergence


# The stop/restart/remove lifecycle actions each have two public routes — the flat
# /api/{action}/{slug} and the service-scoped /api/services/{slug}/... — with identical
# behavior. Both sets of routes delegate to these helpers so the writer-guard, worker
# resolution, proxy, and bookkeeping live in exactly one place per action.
async def _svc_stop(request: Request, slug: str, worker_id: int | None) -> dict[str, str]:
    _require_writer(request)
    worker_id = await _resolve_worker_id(worker_id)
    result = await _proxy_worker_command(worker_id, "stop", slug)
    await database.record_health_event(slug, "stop")
    metrics.record_container_lifecycle("stop", slug)
    return result


async def _svc_restart(request: Request, slug: str, worker_id: int | None) -> dict[str, str]:
    _require_writer(request)
    worker_id = await _resolve_worker_id(worker_id)
    result = await _proxy_worker_command(worker_id, "restart", slug)
    await database.record_health_event(slug, "restart")
    metrics.record_container_lifecycle("restart", slug)
    return result


async def _svc_remove(
    request: Request,
    slug: str,
    worker_id: int | None,
    delete_volumes: bool,
    allow_delete_critical: bool = False,
) -> dict[str, Any]:
    _require_writer(request)
    if allow_delete_critical:
        # Overriding the critical-volume guard destroys state with no server-side
        # copy - a node identity, a generated wallet. Deploying already requires
        # owner; permanently destroying the money must not be the easier action.
        _require_owner(request)
    worker_id = await _resolve_worker_id(worker_id)
    params: dict[str, str] | None = None
    if delete_volumes:
        params = {"delete_volumes": "true"}
        if allow_delete_critical:
            params["allow_delete_critical"] = "true"
    result = await _proxy_worker_command(worker_id, "remove", slug, params=params)
    await database.remove_deployment(slug)
    await database.record_health_event(slug, "remove")
    metrics.record_container_lifecycle("remove", slug)
    return result


@app.post("/api/stop/{slug}")
async def api_stop(request: Request, slug: str, worker_id: int | None = None) -> dict[str, str]:
    return await _svc_stop(request, slug, worker_id)


@app.post("/api/restart/{slug}")
async def api_restart(request: Request, slug: str, worker_id: int | None = None) -> dict[str, str]:
    return await _svc_restart(request, slug, worker_id)


@app.delete("/api/remove/{slug}")
async def api_remove(
    request: Request,
    slug: str,
    worker_id: int | None = None,
    delete_volumes: bool = False,
    allow_delete_critical: bool = False,
) -> dict[str, Any]:
    return await _svc_remove(request, slug, worker_id, delete_volumes, allow_delete_critical)


# ---------------------------------------------------------------------------
# Helpers: proxy commands / logs to worker nodes
# ---------------------------------------------------------------------------


async def _get_verified_worker_url(worker: dict[str, Any]) -> tuple[str, dict[str, str]]:
    """Validate a worker record and return (url, headers).

    When the worker URL is a hostname, the returned URL is pinned to the IP that
    passed validation and a ``Host`` header preserves the original name — closing
    the DNS-rebinding TOCTOU between validation and the httpx request.
    """
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    if worker["status"] != "online":
        raise HTTPException(status_code=503, detail="Worker is offline")
    if not worker["url"]:
        raise HTTPException(status_code=503, detail="Worker URL not known")
    url, pinned_ip = await asyncio.to_thread(_validate_worker_url, worker["url"])
    host_header: str | None = None
    if pinned_ip:
        url, host_header = _pin_url_to_ip(url, pinned_ip)
    # Authenticate to the worker with ITS OWN key once enrolled; fall back to the
    # shared bootstrap key only for workers that have not enrolled yet. Post-cutover
    # an enrolled worker rejects the shared key, so the UI must present its own.
    cid = worker.get("client_id") or ""
    # Use the per-worker key only once the worker has CONFIRMED it.
    #
    # get_worker_key discards the confirmed flag, so the UI signed outbound
    # commands with a key the worker may never have received — reachable
    # whenever _save_worker_key failed on the worker ("staying on shared key").
    # The worker then read as online from its heartbeats while every deploy,
    # start, stop, restart and logs call failed 401, with nothing connecting
    # the two symptoms.
    key_state = await database.get_worker_key_state(cid) if cid else (None, False)
    stored_key, key_confirmed = key_state if isinstance(key_state, tuple) else (key_state, False)
    auth_key = stored_key if (stored_key and key_confirmed) else FLEET_API_KEY
    headers: dict[str, str] = {}
    if auth_key:
        headers["Authorization"] = f"Bearer {auth_key}"
    if host_header:
        headers["Host"] = host_header
    return url, headers


# Worker error bodies are not forwarded verbatim: they can carry internal paths
# and hostnames. Only errors the worker deliberately structures for the operator
# are passed through, and only the fields we expect.
_FORWARDABLE_WORKER_ERRORS = {"critical_volume"}


def _safe_worker_detail(resp: Any) -> dict[str, Any] | None:
    """Return a worker error detail that is safe to show, or None.

    A refusal to destroy irreplaceable data is useless to the operator without
    the reason - "409" alone does not say which volume, or what is in it - so
    that specific shape is forwarded. Everything else stays generic.
    """
    try:
        detail = (resp.json() or {}).get("detail")
    except (ValueError, AttributeError):
        return None
    error = detail.get("error") if isinstance(detail, dict) else None
    # error comes from a remote worker body; a list/dict would make the `not in`
    # test raise TypeError and turn a 409 into a 500. Require a string.
    if not isinstance(error, str) or error not in _FORWARDABLE_WORKER_ERRORS:
        return None
    blocked = detail.get("blocked")
    if not isinstance(blocked, list):
        return None
    return {
        "error": detail["error"],
        "message": str(detail.get("message") or ""),
        "hint": str(detail.get("hint") or ""),
        "blocked": [
            {
                "volume": str(b.get("volume", "")),
                "target": str(b.get("target", "")),
                "holds": str(b.get("holds", "")),
            }
            for b in blocked
            if isinstance(b, dict)
        ],
    }


async def _proxy_to_worker(
    worker_id: int,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    """Proxy one request to a worker's REST API and return its parsed JSON.

    Single home for the fetch-worker -> verified-URL+auth-header -> httpx call ->
    error-mapping sequence the deploy/command/logs paths all repeated. Dispatch uses
    the concrete httpx verbs (never client.request) so per-verb test mocks keep
    landing; the caller owns the timeout (deploy needs 60s, the rest 30s) and any
    query params (the logs line clamp, remove's delete_volumes).
    """
    worker = await database.get_worker(worker_id)
    url, headers = await _get_verified_worker_url(worker)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            verb = method.upper()
            if verb == "GET":
                resp = await client.get(f"{url}{path}", params=params, headers=headers)
            elif verb == "DELETE":
                resp = await client.delete(f"{url}{path}", params=params, headers=headers)
            else:
                resp = await client.post(f"{url}{path}", json=json, params=params, headers=headers)
            if resp.status_code >= 400:
                # NOT resp.text at warning level: withholding the raw body from the
                # caller (see _safe_worker_detail) is pointless if it goes straight
                # into the log instead. A deploy failure can echo env values, which
                # for several providers are live credentials.
                safe = _safe_worker_detail(resp)
                logger.warning("worker proxy error (%s): %s", resp.status_code, safe or "unstructured error body")
                logger.debug("worker proxy error body (%s): %s", resp.status_code, resp.text)
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=safe or "Worker request failed",
                )
            return resp.json()
    except httpx.HTTPError as exc:
        logger.warning("worker proxy error: %s", exc)
        raise HTTPException(status_code=503, detail="Worker communication failed")


async def _proxy_worker_command(
    worker_id: int, command: str, slug: str, *, params: dict[str, str] | None = None
) -> dict[str, Any]:
    """Forward a container command (restart/stop/start/remove) to a worker."""
    if command == "remove":
        return await _proxy_to_worker(worker_id, "DELETE", f"/api/containers/{slug}", params=params)
    return await _proxy_to_worker(worker_id, "POST", f"/api/containers/{slug}/{command}")


async def _proxy_worker_deploy(worker_id: int, slug: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Forward a deploy command with full spec to a worker."""
    return await _proxy_to_worker(worker_id, "POST", f"/api/containers/{slug}/deploy", json=spec, timeout=60)


async def _proxy_worker_logs(worker_id: int, slug: str, lines: int = 50) -> dict[str, str]:
    """Forward a logs request to a worker."""
    return await _proxy_to_worker(worker_id, "GET", f"/api/containers/{slug}/logs", params={"lines": min(lines, 1000)})


# ---------------------------------------------------------------------------
# API: Service management (new-style routes matching frontend)
# ---------------------------------------------------------------------------


@app.post("/api/services/{slug}/restart")
async def api_service_restart(request: Request, slug: str, worker_id: int | None = None) -> dict[str, str]:
    return await _svc_restart(request, slug, worker_id)


@app.post("/api/services/{slug}/stop")
async def api_service_stop(request: Request, slug: str, worker_id: int | None = None) -> dict[str, str]:
    return await _svc_stop(request, slug, worker_id)


@app.post("/api/services/{slug}/start")
async def api_service_start(request: Request, slug: str, worker_id: int | None = None) -> dict[str, str]:
    _require_writer(request)
    worker_id = await _resolve_worker_id(worker_id)
    result = await _proxy_worker_command(worker_id, "start", slug)
    await database.record_health_event(slug, "start")
    metrics.record_container_lifecycle("start", slug)
    return result


@app.get("/api/services/{slug}/logs")
async def api_service_logs(
    request: Request, slug: str, lines: int = 50, worker_id: int | None = None
) -> dict[str, str]:
    _require_writer(request)
    worker_id = await _resolve_worker_id(worker_id)
    return await _proxy_worker_logs(worker_id, slug, lines)


@app.delete("/api/services/{slug}")
async def api_service_remove(
    request: Request,
    slug: str,
    worker_id: int | None = None,
    delete_volumes: bool = False,
    allow_delete_critical: bool = False,
) -> dict[str, Any]:
    return await _svc_remove(request, slug, worker_id, delete_volumes, allow_delete_critical)


# ---------------------------------------------------------------------------
# API: Compose export
# ---------------------------------------------------------------------------


@app.get("/api/compose/{slug}", response_class=PlainTextResponse)
async def api_compose_single(request: Request, slug: str):
    """Export a docker-compose.yml for a single service."""
    _require_auth_api(request)
    svc = catalog.get_service(slug)
    if not svc:
        raise HTTPException(status_code=404, detail=f"Service '{slug}' not found")
    try:
        return compose_generator.generate_compose_single(slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class ComposeMultiRequest(BaseModel):
    slugs: list[str]


@app.post("/api/compose", response_class=PlainTextResponse)
async def api_compose_multi(
    request: Request,
    body: ComposeMultiRequest,
    _auth: dict[str, Any] = Depends(_require_auth_api),
):
    """Export a docker-compose.yml for multiple services."""
    try:
        return compose_generator.generate_compose_multi(body.slugs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/compose", response_class=PlainTextResponse)
async def api_compose_all(request: Request):
    """Export a docker-compose.yml for ALL services with Docker images."""
    _require_auth_api(request)
    try:
        return compose_generator.generate_compose_all()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# API: Earnings
# ---------------------------------------------------------------------------


@app.get("/api/earnings")
async def api_earnings(request: Request) -> list[dict[str, Any]]:
    _require_auth_api(request)
    return await database.get_earnings_summary()


@app.get("/api/earnings/summary")
async def api_earnings_summary(request: Request) -> dict[str, Any]:
    """Aggregated earnings stats for the dashboard."""
    _require_reader(request)
    summary = await database.get_earnings_dashboard_summary()

    # Load config for signup bonus offsets
    all_config = await database.get_config()
    if not isinstance(all_config, dict):
        all_config = {}

    # Include non-USD balances converted to USD in the total.
    # Compute total_adjusted as the sum of clamped per-service adjusted
    # balances (converted to USD) so it always matches the breakdown view.
    all_earnings = await database.get_earnings_summary()
    total_bonus_usd = 0.0
    total_adjusted = 0.0
    # CashPilot-oj4: the count was computed deep in database.py and only ever
    # logged. A total that silently omits holdings is indistinguishable from a
    # correct one, so the number of omissions has to reach the response.
    unpriced_platforms: list[str] = []
    for e in all_earnings:
        slug = e.get("platform", "")
        balance = float(e["balance"])
        currency = e["currency"]

        bonus = 0.0
        with contextlib.suppress(ValueError, TypeError):
            bonus = float(all_config.get(f"{slug}_signup_bonus", "0") or "0")
        adjusted = max(0.0, balance - bonus)

        if currency != "USD":
            # Fall back to the rate the reading was RECORDED at.
            #
            # to_usd consults only the live caches, so a crypto whose rate
            # lookup is merely stale was dropped from the headline total
            # entirely — silently, with nothing on screen saying the figure was
            # incomplete. upsert_earnings preserves fx_rate_usd on every row
            # precisely so a later reader is not left guessing.
            #
            # A stored rate is imperfect (it is the rate at collection time,
            # not now) but it is enormously better than omitting the holding,
            # and the count below says how many rows needed it.
            stored_rate = database._usd_rate(currency, e.get("fx_rate_usd"))
            usd_val = _to_usd_with_stored(balance, currency, stored_rate)
            if usd_val is not None:
                summary["total"] = round(summary["total"] + usd_val, 2)
            else:
                unpriced_platforms.append(slug)
            adj_usd = _to_usd_with_stored(adjusted, currency, stored_rate)
            if adj_usd is not None:
                total_adjusted += adj_usd
            bonus_usd = _to_usd_with_stored(bonus, currency, stored_rate) if bonus > 0 else 0.0
            if bonus_usd is not None:
                total_bonus_usd += bonus_usd
        else:
            total_adjusted += adjusted
            total_bonus_usd += bonus

    # Count active (running) services from worker data.
    #
    # None, not 0, when the count could not be taken. _get_all_worker_containers
    # opens SQLite, so a locked or busy database — or a JSON-decode failure on a
    # worker row — lands here while containers are in fact running, and "0"
    # reads as "nothing is running". Logged at WARNING rather than DEBUG: DEBUG
    # is off in production, so the only two places that could have said anything
    # both said nothing (CashPilot-45k).
    active: int | None = None
    try:
        worker_containers = await _get_all_worker_containers()
        active = sum(1 for s in worker_containers if s.get("status") == "running")
    except Exception as exc:
        logger.warning("Could not count active services, reporting it as unknown: %s", exc)
    summary["active_services"] = active
    # A total that silently omits holdings is indistinguishable from a correct
    # one. The count was already being computed in database.py and only logged;
    # it now reaches the caller so the card can say the figure is partial.
    # Whether anything has ever been read at all. Without this the payload is
    # identical on a fresh install and on an install whose collection has
    # silently stopped — an expired cookie, deleted credentials, a wedged
    # scheduler — and the dashboard states "$0.00" as a measurement in both.
    # A new user's very first view of CashPilot asserted three zero balances in
    # the same typeface those cards will later carry real money in.
    summary["has_readings"] = bool(all_earnings)
    summary["unpriced_platforms"] = sorted(set(unpriced_platforms))
    summary["total_bonus"] = round(total_bonus_usd, 2)
    summary["total_adjusted"] = round(total_adjusted, 2)
    return summary


@app.get("/api/earnings/daily")
async def api_earnings_daily(request: Request, days: int = 7) -> list[dict[str, Any]]:
    """Daily earnings for charting."""
    _require_auth_api(request)
    if days < 1 or days > 365:
        raise HTTPException(status_code=400, detail="days must be between 1 and 365")
    return await database.get_daily_earnings(days)


@app.get("/api/earnings/breakdown")
async def api_earnings_breakdown(request: Request) -> list[dict[str, Any]]:
    """Per-service earnings breakdown with cashout eligibility."""
    _require_reader(request)
    rows = await database.get_earnings_per_service()

    # Load config for per-service signup bonus offsets
    all_config = await database.get_config()
    if not isinstance(all_config, dict):
        all_config = {}

    result = []
    for row in rows:
        slug = row["platform"]
        svc = catalog.get_service(slug)
        cashout = (svc.get("cashout", {}) if svc else {}) or {}
        # Three-valued, matching payouts.min_payout: a positive number is a
        # real minimum, 0 is a documented "no minimum", and None means nobody
        # published one. float(..., 0) collapsed the last two, so 21 services
        # with no published minimum reported the user as eligible to cash out
        # any balance above zero.
        raw_min = cashout.get("min_amount")
        try:
            min_amount = float(raw_min) if raw_min is not None else None
        except (TypeError, ValueError):
            min_amount = None
        balance = float(row["balance"])
        # The minimum in the same unit as this balance. The catalog declares it
        # in whatever the provider cashes out in, which for Storj (USD balance,
        # STORJ minimum) and anyone-protocol is not what the collector reports —
        # so `balance >= min_amount` was comparing two different currencies at
        # 1:1, and told the user they were eligible when they were not.
        comparable_min = payouts.min_payout_in(svc, row.get("currency"))
        prev_balance = float(row.get("prev_balance", 0))
        delta = balance - prev_balance

        # Signup bonus offset (stored in config as {slug}_signup_bonus)
        signup_bonus = 0.0
        with contextlib.suppress(ValueError, TypeError):
            signup_bonus = float(all_config.get(f"{slug}_signup_bonus", "0") or "0")
        balance_adjusted = round(max(0.0, balance - signup_bonus), 4)

        entry = {
            "platform": slug,
            "name": svc["name"] if svc else slug,
            "balance": round(balance, 4),
            "balance_adjusted": balance_adjusted,
            "signup_bonus": round(signup_bonus, 4),
            "currency": row["currency"],
            "last_updated": row["date"],
            "delta": round(delta, 4),
            "cashout": {
                # None, not True, when the minimum is unknown. Claiming
                # eligibility we cannot establish sends the user to a withdrawal
                # page that will refuse them.
                # False and None mean different things here, and the existing
                # tests were right to insist on the distinction:
                #   no cashout section  -> False. There is no withdrawal route
                #                          at all; that is a real answer.
                #   route but no known  -> None. We cannot say, and claiming
                #   minimum                eligibility would send the user to a
                #                          page that refuses them.
                "eligible": (
                    False
                    if not cashout
                    else (None if comparable_min is None else (balance > 0 and balance >= comparable_min))
                ),
                "min_amount": min_amount,
                # The threshold in the same unit as the balance above, or None
                # when the two cannot be reconciled. Eligibility is decided on
                # this one; min_amount stays as the catalog declares it so the
                # provider's own wording is still available to the UI.
                "min_amount_comparable": comparable_min,
                "min_amount_currency": payouts.min_payout_currency(svc),
                "method": cashout.get("method", "redirect"),
                "dashboard_url": cashout.get("dashboard_url", ""),
                "notes": cashout.get("notes", ""),
            },
        }
        result.append(entry)
    return result


@app.get("/api/earnings/history")
async def api_earnings_history(request: Request, period: str = "week") -> list[dict[str, Any]]:
    _require_auth_api(request)
    if period not in ("week", "month", "year", "all"):
        raise HTTPException(status_code=400, detail="period must be week, month, year, or all")
    return await database.get_earnings_history(period)


@app.get("/api/health/scores")
async def api_health_scores(request: Request, days: int = 7) -> list[dict[str, Any]]:
    """Health scores for all services."""
    _require_reader(request)
    if days < 1 or days > 90:
        raise HTTPException(status_code=400, detail="days must be between 1 and 90")
    scores = await database.get_health_scores(days)
    # Enrich with service names
    for s in scores:
        svc = catalog.get_service(s["slug"])
        s["name"] = svc["name"] if svc else s["slug"]
    return scores


@app.post("/api/collect")
async def api_collect(request: Request) -> dict[str, str]:
    _require_writer(request)
    _spawn(_run_collection())
    return {"status": "collection_started"}


_MAX_ALERT_ERROR_LEN = 200


@app.get("/api/earnings/flatlines")
async def api_earnings_flatlines(request: Request) -> list[dict[str, Any]]:
    """Services that are running but whose balance has stopped moving."""
    _require_auth_api(request)
    return await database.get_flatlined_services()


@app.get("/api/credentials/health")
async def api_credential_health(request: Request) -> list[dict[str, Any]]:
    """Report how old each stored credential is and when it is expected to die.

    Never returns credential VALUES - only which key it is, how old, and what
    that means. The point is that "this will stop working tonight" is visible
    BEFORE it happens, rather than the user discovering it because earnings
    quietly stopped being recorded.
    """
    _require_auth_api(request)

    from app.collectors import _COLLECTOR_ARGS, credential_lifetime, durable_alternative

    updated = await database.get_config_updated_at()
    now = datetime.now(UTC)
    report: list[dict[str, Any]] = []

    for slug, args in _COLLECTOR_ARGS.items():
        missing_durable = [field for field in durable_alternative(slug) if f"{slug}_{field}" not in updated]
        for arg in args:
            field = arg.lstrip("?")
            key = f"{slug}_{field}"
            stamp = updated.get(key)
            if not stamp:
                continue  # not configured; nothing to report an age for

            meta = credential_lifetime(slug, field) or {}
            hours_total = meta.get("hours")
            try:
                age_hours = (now - datetime.fromisoformat(stamp).replace(tzinfo=UTC)).total_seconds() / 3600
            except ValueError:
                continue

            if hours_total is None:
                status = "no_known_expiry"
            elif age_hours >= hours_total:
                status = "likely_expired"
            elif age_hours >= hours_total * 0.75:
                status = "expiring_soon"
            else:
                status = "fresh"

            entry: dict[str, Any] = {
                "service": slug,
                "field": field,
                "age_hours": round(age_hours, 1),
                "expected_lifetime_hours": hours_total,
                "status": status,
            }
            if meta.get("why"):
                entry["why"] = meta["why"]
            # Only nag about a durable alternative when the short-lived credential
            # is the one actually at risk.
            if missing_durable and hours_total is not None and not meta.get("durable"):
                entry["durable_alternative_missing"] = missing_durable
            report.append(entry)

    return report


@app.get("/api/services/{slug}/preflight")
async def api_service_preflight(
    request: Request, slug: str, worker_id: int | None = None, planned: str | None = None
) -> dict[str, Any]:
    """What this service will realistically do for THIS user, before deploying.

    Never blocks a deploy: the goal is informed consent, not a nanny.
    """
    _require_auth_api(request)
    service = catalog.get_service(slug)
    if not service:
        raise HTTPException(status_code=404, detail=f"Unknown service '{slug}'")

    # What is already running on the SAME machine is what makes a per-IP limit
    # checkable at all, so scope to that worker when we know which one.
    if worker_id is None:
        deployed = await database.get_deployments()
        return preflight.assess(service, already_deployed_slugs={d["slug"] for d in deployed})

    # Only ONLINE workers count as peers. A worker that is merely switched off
    # keeps its row forever once enrolled (the purge spares enrolled rows), and
    # its last heartbeat still lists every container as running — so a retired
    # machine would fabricate a conflict against a live one. This module
    # promises the opposite failure direction: a missed conflict, never an
    # invented one. The worker being deployed to is looked up separately so a
    # freshly-restarted one can still be assessed.
    all_workers = [_decoded_worker(w) for w in await database.list_workers()]
    workers = [w for w in all_workers if w.get("status") == "online"]
    worker = next((w for w in all_workers if w.get("id") == worker_id), None)
    if worker is None:
        raise HTTPException(status_code=404, detail=f"Unknown worker {worker_id}")

    # The other workers receiving this service in the SAME wizard action. The
    # cross-machine check otherwise only sees what is already RUNNING, so
    # ticking two boxes behind one connection produced no warning: neither
    # worker had the service yet, so neither counted against the other. The
    # warning arrived on the next deploy, after the account was already at risk
    # (CashPilot-3tr).
    planned_ids: set[int] = set()
    for part in (planned or "").split(","):
        part = part.strip()
        if part.isdigit():
            planned_ids.add(int(part))
    planned_ids.discard(worker_id)

    return preflight.assess(
        service,
        already_deployed_slugs=egress.running_slugs(worker),
        system_info=worker.get("system_info") or {},
        # The cross-machine half: providers cap per IP, so a sibling worker
        # behind the same public address is the case a single-host tool cannot
        # see at all.
        worker=worker,
        fleet_workers=workers,
        also_deploying_to=planned_ids,
    )


@app.get("/api/fleet/egress-groups")
async def api_fleet_egress_groups(request: Request) -> dict[str, Any]:
    """The fleet grouped by the public address providers actually see.

    The normal fleet view is by machine, which is the wrong unit: two machines
    in one house are two rows here and one customer to every provider.
    """
    _require_auth_api(request)
    workers = [_decoded_worker(w) for w in await database.list_workers()]
    groups = egress.group_by_egress(workers)
    return {
        "groups": [
            {
                "egress_ip": g["egress_ip"],
                "known": g["known"],
                "network_type": g["network_type"],
                "shared": g["shared"],
                "worker_count": g["worker_count"],
                "workers": [
                    {"id": w.get("id"), "name": w.get("name"), "client_id": w.get("client_id")} for w in g["workers"]
                ],
            }
            for g in groups
        ],
        "shared_groups": sum(1 for g in groups if g["shared"]),
        # Reported separately and never folded into the groups above: these are
        # machines whose exit we could not determine, not machines we checked.
        "undetermined": sum(g["worker_count"] for g in groups if not g["known"]),
    }


@app.get("/api/earnings/net")
async def api_earnings_net(request: Request, days: int = 30) -> dict[str, Any]:
    """Gross, estimated electricity cost, and net per service.

    Reports net ALONGSIDE gross, never instead of it, and every cost carries
    whether it was estimated or measured. With no tariff configured it reports
    gross and says the cost is unknown, rather than charging zero and quietly
    presenting gross as if it were profit.
    """
    _require_auth_api(request)

    cfg = await database.get_config()
    try:
        price = _tariff_price(cfg)
    except (TypeError, ValueError):
        price = 0.0
    currency = str(cfg.get("power_currency") or "EUR")
    try:
        host_tdp = float(cfg.get("power_host_tdp_watts") or power.DEFAULT_HOST_TDP_WATTS)
    except (TypeError, ValueError):
        host_tdp = power.DEFAULT_HOST_TDP_WATTS

    # Whether the power side of this endpoint has any input at all. An empty
    # `statuses` from a FAILURE is not the same fact as an empty one from a
    # fleet with nothing running, and the difference decides whether a net
    # figure exists (CashPilot-c6u).
    watts_known = True
    try:
        statuses = await _get_all_worker_containers()
    except Exception as exc:
        # A worker status problem must not take out the earnings figures, which
        # come from the database and are still perfectly reportable.
        logger.warning("Worker status unavailable for the power estimate: %s", exc)
        statuses = []
        watts_known = False
    # Only RUNNING containers. A stopped one draws nothing, and counting it
    # inflates a worker's container count, which shrinks every running service's
    # share of that host's idle floor and understates the fleet's real cost.
    # egress.container_slug, NOT c["service"].
    #
    # _get_all_worker_containers emits "slug"; this filtered on "service" and so
    # matched NOTHING in production, every time. The consequence was not a
    # missing panel — it was that every service was charged 0 W, so cost came
    # out 0.00 and net was reported EQUAL TO GROSS with cost_known: true. The
    # endpoint's own docstring promises it never presents gross as profit, and
    # that is exactly what it did.
    #
    # This is the second time this key has bitten the project. container_slug()
    # exists because of the first time and accepts both spellings; its docstring
    # says code reading "service" matched nothing in production while its tests
    # passed, which is precisely what happened here again.
    running = [c for c in statuses if egress.container_slug(c) and str(c.get("status", "")).lower() == "running"]

    # Group by WORKER and keep it that way through the watt calculation. Each
    # host pays its own idle draw, so collapsing a multi-host fleet into one
    # count charges a single idle floor for the whole estate. Keeping the group
    # is also the only way power.is_metered can be applied: a VPS bill does not
    # move with CPU, and billing it like a home server invents a cost.
    by_worker: dict[Any, list[dict[str, Any]]] = {}
    for c in running:
        by_worker.setdefault(c.get("_worker_id"), []).append(c)

    worker_meta = {w.get("id"): w for w in await database.list_workers()}

    hours = max(1, int(days)) * 24.0
    # Earned OVER THE WINDOW, not the latest balance: subtracting a window's
    # electricity from a running total would be meaningless arithmetic.
    earned = await database.get_earned_by_platform(max(1, int(days)))

    watts_by_service: dict[str, float] = {}
    unmetered_services: set[str] = set()
    for wid, containers in by_worker.items():
        meta = worker_meta.get(wid) or {}
        info = _safe_json(meta.get("system_info", "{}"), {})
        metered = power.is_metered(info)
        try:
            tdp = float(info.get("host_tdp_watts") or host_tdp)
        except (TypeError, ValueError):
            tdp = host_tdp
        count = max(1, len(containers))
        for c in containers:
            svc = egress.container_slug(c)
            if not metered:
                # No marginal power cost to the user on this host, so charge
                # nothing rather than computing watts and multiplying by zero.
                unmetered_services.add(svc)
                continue
            # A container whose CPU could not be read contributes no estimate
            # rather than an estimate built from a fabricated 0%. `or 0.0` below
            # would silently turn "unmeasurable" into "idle", which is how a
            # busy service ends up costing nothing on the running-costs card.
            if c.get("cpu_percent") is None:
                continue
            watts_by_service[svc] = watts_by_service.get(svc, 0.0) + power.estimate_watts(
                float(c.get("cpu_percent") or 0.0), host_tdp_watts=tdp, container_count=count
            )

    rows = []
    for platform, gross in earned.items():
        watts = watts_by_service.get(platform, 0.0)
        rows.append(
            {
                "platform": platform,
                "gross": float(gross),
                "watts": watts,
                "hours": hours,
                "cost_quality": power.ESTIMATED,
                # Whether a PER-SERVICE cost means anything, as opposed to
                # whether the machine costs anything. A bandwidth container adds
                # roughly 1-3 W to a host that is already on, which is below
                # what a consumer smart plug can resolve, so the share-out is
                # arithmetic rather than measurement.
                #
                # The cost itself is still reported and still counted in the
                # fleet total — the machine really does draw that power, and
                # dropping it would understate what the fleet costs. What is
                # unreliable is which service to blame, so that is what gets
                # flagged. machine_economics has held this rule since it was
                # written and nothing had ever asked it.
                "cost_attributable": machine_economics.per_service_is_meaningful(watts),
            }
        )

    # Convert the TARIFF into USD, rather than the gross into the tariff currency.
    #
    # gross comes from get_earned_by_platform, which is USD by contract, while
    # the tariff is whatever power_currency says. Subtracting one from the other
    # produced a number in neither, labelled with the tariff currency — at
    # ~1.08 USD/EUR an 8% error, in the direction that flatters the result, on
    # the figure that decides whether a machine is worth running.
    #
    # Converting the PRICE keeps this endpoint canonical USD like every other
    # money figure in the API, and the frontend's display-currency layer renders
    # it in whatever the user reads in. Converting the gross the other way would
    # have made this one endpoint the exception.
    price_usd = price
    fx_ok = True
    if price and currency != "USD":
        converted = exchange_rates.to_usd(price, currency)
        if converted is None:
            fx_ok = False
        else:
            price_usd = converted

    # No rate means the tariff cannot be expressed in the same unit as the
    # earnings, so there is no honest net. Reporting gross alone is what this
    # module already does when no tariff is set at all: "a zero cost would
    # render gross as net and quietly overstate earnings."
    #
    # Unknown WATTS suppress the net for the same reason unknown FX does, and
    # through the same mechanism: a zero price makes summarise report cost and
    # net as None instead of as numbers. Without this, a failed worker lookup
    # charged every service 0 W, cost summed to 0.00, and the endpoint returned
    # total_net == total_gross with cost_known TRUE -- gross presented as profit,
    # which is the one thing this endpoint's docstring promises it never does.
    # cost_known came from `price_per_kwh > 0` alone and never asked whether any
    # watts had actually been measured (CashPilot-c6u).
    result = power.summarise(rows, price_per_kwh=(price_usd if (fx_ok and watts_known) else 0.0), currency="USD")
    if not watts_known:
        result["cost_known"] = False
        result["watts_unavailable"] = True
        result["cost_unavailable_reason"] = (
            "CashPilot could not reach its workers, so it does not know what any service "
            "is drawing right now. Earnings below are real; the running cost and the net "
            "figure are unknown for this window, not zero."
        )
    if not fx_ok:
        result["cost_known"] = False
        result["fx_unavailable"] = True
        result["tariff_currency"] = currency
        result["cost_unavailable_reason"] = (
            f"Your tariff is in {currency} and earnings are recorded in USD. No "
            f"{currency}-to-USD rate is available right now, so a net figure would be "
            "two different currencies subtracted from each other."
        )
    result["window_days"] = max(1, int(days))
    result["host_tdp_watts"] = host_tdp
    return result


#: Hostname shape a resolver should ever be asked about. advertised_address is
#: WORKER-SUPPLIED text: without this gate a rogue worker could drive the hub's
#: resolver with arbitrary strings (and an IDNA-invalid label does not even
#: raise the OSError family — see _resolve_advertised_host).
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


async def _advertised_address_mismatch(matches: list[dict[str, Any]], worker_id: int | None = None) -> str | None:
    """Is the network dialling an address this machine no longer has?

    Compares the advertised_address a worker reported (the ONE env var the
    service's catalog entry declares, see advertised_address_env in
    services/_schema.yml) against that worker's detected egress IP. This is
    the check that catches a stale advertised IP the day the ISP re-provisions
    it, instead of days later via the provider's offline emails.

    Every failure to gather either side returns None — no claim — because a
    wrong "your address is stale" sends the operator to fix DNS that is fine.
    Only a definitive NXDOMAIN counts as a resolution verdict; a timeout or a
    transient resolver error is indistinguishable from OUR network having a
    bad moment, which says nothing about the record.
    """
    # Judge only what is actually RUNNING, and only on the node the caller
    # asked about: an exited container elsewhere in the fleet carries the env
    # of its LAST run, and judging that produced a finding about a machine the
    # page was not even showing.
    candidates = [c for c in matches if str(c.get("status", "")).lower() == "running"]
    if worker_id is not None:
        candidates = [c for c in candidates if c.get("_worker_id") == worker_id]
    reported = next((c for c in candidates if c.get("advertised_address") and c.get("_worker_id") is not None), None)
    if reported is None:
        return None
    row = await database.get_worker(reported["_worker_id"])
    if row is None:
        return None
    egress_ip = egress.egress_of(_decoded_worker(row))

    host = egress.advertised_host(reported["advertised_address"])
    resolved: set[str] | None = None
    if host and egress_ip:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not _HOSTNAME_RE.fullmatch(host):
                return None
            resolved = await _resolve_advertised_host(host)
    reason = egress.advertised_address_verdict(reported["advertised_address"], egress_ip, resolved)
    # Name the node: on a fleet the bare reason says "this machine" with no
    # way to tell WHICH machine, which is a finding nobody can act on.
    if reason and (node := reported.get("_node")):
        return f"On {node}: {reason}"
    return reason


#: host -> (monotonic stamp, result). One entry per advertised hostname (one
#: service per fleet declares one today), so this stays tiny; the TTL exists so
#: a blackholed resolver costs one executor thread per window, not one per
#: request — wait_for abandons the await but the thread blocks on for the full
#: OS resolver timeout.
_RESOLVE_CACHE: dict[str, tuple[float, set[str] | None]] = {}
_RESOLVE_CACHE_TTL = 60.0
#: The keys are worker-supplied hostnames, so the table must be bounded: a
#: worker rotating its advertised address must not grow hub memory forever.
_RESOLVE_CACHE_MAX = 256


async def _resolve_advertised_host(host: str) -> set[str] | None:
    """Resolve a hostname the way the dialling network would.

    Three-valued by contract: a non-empty set of addresses, an EMPTY set only
    for a definitive does-not-exist answer (EAI_NONAME/EAI_NODATA), and None
    for everything transient — timeout, EAI_AGAIN, resolver trouble — because
    OUR resolver having a bad moment says nothing about the record.

    UnicodeError is in the transient clause because getaddrinfo raises it (a
    ValueError, NOT an OSError) for an IDNA-invalid label — uncaught, it
    escaped to the route's umbrella handler and silently disabled the log-
    signal scan that shares the same try block.
    """
    cached = _RESOLVE_CACHE.get(host)
    if cached and time.monotonic() - cached[0] < _RESOLVE_CACHE_TTL:
        return cached[1]
    try:
        infos = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM), 3.0)
        result: set[str] | None = {addr[4][0] for addr in infos}
    except socket.gaierror as exc:
        definitive = {socket.EAI_NONAME, getattr(socket, "EAI_NODATA", socket.EAI_NONAME)}
        result = set() if exc.errno in definitive else None
    except (TimeoutError, OSError, UnicodeError):
        result = None
    now = time.monotonic()
    # Purge expired entries on every write, then cap: without eviction each
    # distinct worker-supplied name would be a permanent key.
    for stale in [k for k, (stamp, _) in _RESOLVE_CACHE.items() if now - stamp >= _RESOLVE_CACHE_TTL]:
        del _RESOLVE_CACHE[stale]
    while len(_RESOLVE_CACHE) >= _RESOLVE_CACHE_MAX:
        del _RESOLVE_CACHE[min(_RESOLVE_CACHE, key=lambda k: _RESOLVE_CACHE[k][0])]
    _RESOLVE_CACHE[host] = (now, result)
    return result


@app.get("/api/services/{slug}/producer-state")
async def api_producer_state(request: Request, slug: str, worker_id: int | None = None) -> dict[str, Any]:
    """Is this service actually EARNING, as distinct from merely running?

    Container health is computed from restarts and crashes, so a service that
    has produced nothing for a month still scores full marks. This is a separate
    verdict, and it says "unknown" rather than guessing when the earnings cannot
    be seen at all.
    """
    _require_auth_api(request)
    service = catalog.get_service(slug)
    if not service:
        raise HTTPException(status_code=404, detail=f"Unknown service '{slug}'")

    from app.collectors import COLLECTOR_MAP

    has_collector = slug in COLLECTOR_MAP

    earned_recently: bool | None = None
    if has_collector:
        # A zero here has three possible causes and only one of them is "idle".
        #
        # get_earned_by_platform sums DELTAS, so a service with a single reading
        # contributes nothing — within an hour of a healthy first install this
        # reported "Recorded earnings have not moved recently" about a service
        # that had produced one perfectly good reading and had had no chance to
        # move. And the sum is in USD, so a platform whose readings cannot be
        # priced sums to zero forever: a MystNodes balance climbing 40 -> 55 ->
        # 70 MYST with no rate available was reported idle indefinitely.
        #
        # Both are "we cannot see", not "it is not earning" — and this module's
        # own docstring says reporting the second when the truth is the first is
        # exactly the false confidence it exists to remove.
        history = await database.get_balance_history(slug, days=7)
        if len(history) >= 2:
            priceable = all(
                str(row.get("currency") or "USD").upper() == "USD" or row.get("fx_rate_usd") for row in history
            )
            if priceable:
                earned = await database.get_earned_by_platform(days=7)
                earned_recently = float(earned.get(slug) or 0.0) > 0

    # None, not True. If the container lookup below throws, this value is what
    # survives, and claiming "running" on no evidence is exactly the assumption
    # this whole module exists to refuse: assess() would skip its unknown path
    # and, on a still-cached earnings figure, report the service as PRODUCING
    # at a moment when we cannot tell whether the container is even up.
    running: bool | None = None
    log_hits: list[dict[str, str]] = []
    traffic: str | None = None
    address_mismatch: str | None = None
    signals = producer_state.signals_for(service)
    try:
        containers = await _get_all_worker_containers()
        # Heartbeat entries key the service as "slug"; matching on "service"
        # here found nothing in production while the tests, which hand-fed
        # the wrong shape, passed.
        matches = [c for c in containers if egress.container_slug(c) == slug]
        running = any(str(c.get("status", "")).lower() == "running" for c in matches)
        traffic = _traffic_state(slug, matches)
        if running:
            # Own guard, not just the outer umbrella: an exception here would
            # otherwise abandon the whole try block and silently zero the
            # log-signal scan below — the address check disabling the very
            # detection (#318) that shares this block. No claim, ever, at the
            # cost of the rest of the verdict.
            with contextlib.suppress(Exception):
                address_mismatch = await _advertised_address_mismatch(matches, worker_id)
        if signals and running:
            wid = worker_id if worker_id is not None else (matches[0].get("_worker_id") if matches else None)
            if wid is not None:
                logs = (await _proxy_worker_logs(wid, slug, lines=200)).get("logs", "")
                log_hits = producer_state.match_log_signals(logs, signals)
    except Exception as exc:
        # Never let a log or worker problem turn "is it earning?" into a 500;
        # the earnings signal alone is still worth reporting.
        logger.warning("Producer-state signals unavailable for %s: %s", slug, exc)

    return producer_state.assess(
        slug=slug,
        has_collector=has_collector,
        earned_recently=earned_recently,
        log_hits=log_hits,
        traffic=traffic,
        container_running=running,
        address_mismatch=address_mismatch,
    )


@app.get("/api/services/{slug}/disclosure")
async def api_service_disclosure(request: Request, slug: str) -> dict[str, Any]:
    """What this service does with your machine, and what nobody has answered yet."""
    _require_auth_api(request)
    service = catalog.get_service(slug)
    if not service:
        raise HTTPException(status_code=404, detail=f"Unknown service '{slug}'")
    return disclosure.for_service(service)


@app.post("/api/services/{slug}/test-credentials")
async def api_test_credentials(request: Request, slug: str) -> dict[str, Any]:
    """Check the saved credentials for one service, right now.

    Without this a user waits up to a full collection interval — an hour — to
    find out a pasted token had a typo, and learns it from a notification bell.

    The response deliberately has no field that could carry a secret: outcomes
    are classified, and neither the credential nor the provider's raw body is
    returned. A failed provider login frequently echoes the submitted payload.
    """
    from app import collectors
    from app.collectors import COLLECTOR_MAP

    # Owner, not merely authenticated: this fires an authenticated login to a
    # third party using the OWNER's stored credentials and reads the balance
    # back. /api/collectors/meta already requires owner for the same material,
    # and POST /api/collect — which is strictly less privileged — requires
    # writer. A viewer must not be able to reach any of it.
    _require_owner(request)
    service = catalog.get_service(slug)
    if not service:
        raise HTTPException(status_code=404, detail=f"Unknown service '{slug}'")
    name = service.get("name") or slug

    if slug not in COLLECTOR_MAP:
        return credential_test.result(credential_test.UNSUPPORTED, name)

    remaining = credential_test.cooldown_remaining(slug)
    if remaining > 0:
        # Retrying a rejected login in a tight loop is how accounts get flagged,
        # and a button invites exactly that.
        return credential_test.result(credential_test.RATE_LIMITED, name, retry_after=round(remaining))

    config = await database.get_config() or {}
    collector, missing = collectors.build_one(slug, config)
    if collector is None:
        outcome = credential_test.NOT_CONFIGURED if missing else credential_test.UNSUPPORTED
        return credential_test.result(outcome, name)

    # Re-check immediately before claiming the slot. The first check above is
    # separated from this point by `await database.get_config()`, and an await
    # is where the event loop can run the other request: two clicks could both
    # pass the cooldown, both build a collector, and both reach the provider.
    # Hammering a provider with repeated logins is what gets accounts flagged,
    # which is the entire reason the cooldown exists. `build_one` is
    # synchronous, so re-check and claim are adjacent with no await between
    # them and the window is closed without needing a lock.
    remaining = credential_test.cooldown_remaining(slug)
    if remaining > 0:
        return credential_test.result(credential_test.RATE_LIMITED, name, retry_after=round(remaining))
    credential_test.note_attempt(slug)
    try:
        result = await collector.collect()
    except Exception as exc:
        logger.debug("Credential test for %s raised: %s", slug, exc)
        return credential_test.result(credential_test.classify(str(exc)), name)
    finally:
        with contextlib.suppress(Exception):
            await collector.close()

    outcome = credential_test.classify(result.error)
    if outcome == credential_test.OK:
        return credential_test.result(outcome, name, balance=result.balance, currency=result.currency)
    logger.debug("Credential test for %s failed: %s", slug, result.error)
    return credential_test.result(outcome, name)


@app.get("/api/earnings/payouts")
async def api_payouts(request: Request, platform: str | None = None) -> dict[str, Any]:
    """Payouts, split into confirmed income and drops still awaiting a human."""
    _require_auth_api(request)
    rows = await database.get_payouts(platform=platform)
    return {
        "confirmed": [r for r in rows if r.get("confirmed")],
        "probable": [r for r in rows if not r.get("confirmed")],
    }


async def _payout_platform(payout_id: int) -> str | None:
    """Which platform a payout row belongs to, before it is deleted."""
    try:
        rows = await database.get_payouts()
    except Exception as exc:  # noqa: BLE001 - answering the payout must not 500 on the lookup
        # Silent None here left the bell entry standing forever with no trace
        # of why; the operator "answered" the prompt and it never went away.
        logger.warning("Could not resolve payout %s to a platform; its bell entry stays: %s", payout_id, exc)
        return None
    for row in rows:
        if row.get("id") == payout_id:
            return row.get("platform")
    return None


async def _retire_payout_alert(payout_id: int, platform: str | None = None) -> None:
    """Drop the bell entry for a payout that has now been answered."""
    global _collector_alerts
    if platform is None:
        platform = await _payout_platform(payout_id)
    if not platform:
        return
    try:
        await database.clear_alerts("payout", platform)
    except Exception as exc:  # noqa: BLE001
        # Do NOT prune the in-memory bell when the durable delete failed: the
        # two stores would diverge on a financial record — the operator sees
        # the prompt disappear, believes it answered, and the surviving row
        # resurrects it after the next restart.
        logger.warning("Could not clear the stored payout alert for %s; keeping it in the bell: %s", platform, exc)
        return
    _collector_alerts = [
        a for a in _collector_alerts if not (a.get("kind") == "payout" and a.get("platform") == platform)
    ]


@app.post("/api/earnings/payouts/{payout_id}/confirm")
async def api_confirm_payout(request: Request, payout_id: int, method: str = "") -> dict[str, Any]:
    """Confirm a drop really was a payout. Only a human reaches this."""
    # Writer, not viewer: this mutates financial records, and rejection is a
    # hard DELETE. A read-only account must not be able to destroy them.
    _require_writer(request)
    # Forward `method`. The endpoint has always accepted it and the database
    # has always had a column for it, but it was never passed along, so every
    # confirmation recorded an empty method however the caller was paid.
    if not await database.confirm_payout(payout_id, method=method):
        raise HTTPException(status_code=404, detail="No unconfirmed payout with that id")
    # The question has been answered, so retire the prompt. Left behind, the
    # stored alert would be restored on the next restart and ask again about a
    # payout the user already confirmed.
    await _retire_payout_alert(payout_id)
    return {"ok": True, "id": payout_id, "confirmed": True}


@app.post("/api/earnings/payouts/{payout_id}/reject")
async def api_reject_payout(request: Request, payout_id: int) -> dict[str, Any]:
    """This drop was not a payout — forget it entirely."""
    # Writer, not viewer: this mutates financial records, and rejection is a
    # hard DELETE. A read-only account must not be able to destroy them.
    _require_writer(request)
    platform = await _payout_platform(payout_id)
    if not await database.reject_payout(payout_id):
        raise HTTPException(status_code=404, detail="No unconfirmed payout with that id")
    await _retire_payout_alert(payout_id, platform=platform)
    return {"ok": True, "id": payout_id, "removed": True}


@app.get("/api/services/{slug}/payout-progress")
async def api_payout_progress(request: Request, slug: str) -> dict[str, Any]:
    """Current balance, lifetime earned, and how far off the payout is.

    These are three different questions and were previously one number that went
    DOWN when the user got paid. The projection is the answer to the most
    demotivating unknown in this category — a 20 USD minimum can be months on
    one device, and not knowing that is what makes people give up.
    """
    _require_auth_api(request)
    service = catalog.get_service(slug)
    if not service:
        raise HTTPException(status_code=404, detail=f"Unknown service '{slug}'")

    balance = await database.get_latest_balance(slug)
    history = await database.get_balance_history(slug, days=30)
    # The unit the balance is recorded in, taken from the newest reading we
    # already fetched rather than a second query. None when nothing has ever
    # been collected, which min_payout_in reads as "cannot reconcile" and so
    # leaves the declared minimum alone.
    balance_currency = (history[-1].get("currency") if history else None) or None
    confirmed = await database.get_payouts(platform=slug, confirmed_only=True)

    known = balance is not None
    current = float(balance or 0.0)
    # The card renders every figure here in ONE unit and asks the user to compare
    # them against the provider's minimum. The balance is in whatever the
    # collector reports and the minimum in whatever the provider cashes out in;
    # for Storj and anyone-protocol those differ, so "3.50 STORJ" was really
    # $3.50 and "0.50 to go" counted down to a threshold in another unit.
    # Expressing the minimum in the BALANCE's unit keeps the comparison honest
    # and leaves the balance itself untouched.
    minimum = payouts.min_payout_in(service, balance_currency)
    declared_currency = payouts.min_payout_currency(service)
    comparable = minimum is not None or payouts.min_payout(service) is None
    return {
        "slug": slug,
        "current_balance": round(current, 6) if known else None,
        # What the numbers above are actually in, so nothing has to assume.
        "balance_currency": balance_currency,
        "min_amount": minimum,
        # Falls back to the DECLARED unit when nothing has been collected: with
        # no balance currency, min_payout_in returns the catalog figure at face
        # value, and labelling that with None leaves the consumer holding a
        # threshold it cannot attribute to any unit.
        "min_amount_currency": (balance_currency if (minimum is not None and balance_currency) else declared_currency),
        # False only when a real minimum exists and could not be brought into
        # the balance's unit. The card hides the comparison rather than drawing
        # a bar out of two different currencies.
        "comparable": comparable,
        # Lifetime counts CONFIRMED payouts only. A probable one folded in here
        # would let a single misread drop inflate earnings forever, invisibly.
        #
        # None when the balance is unknown AND nothing has been paid out:
        # `float(balance or 0.0)` folded "never read" into a real zero, so the
        # card stated a definite 0.00 lifetime for a service nothing had ever
        # looked at. Confirmed payouts are still a real lower bound, so they
        # keep a figure.
        "lifetime_earned": payouts.lifetime_earned(current, confirmed) if (known or confirmed) else None,
        "confirmed_payout_count": len(confirmed),
        "balance_known": known,
        # Projection stays. payouts.project already returns an explicit
        # NOT_ENOUGH_DATA state, which is a more useful answer than null — it
        # says WHY there is no estimate. Nulling it discarded that and pushed a
        # null-check onto every caller. The misleading part was never this
        # field; it was the card rendering a 0%-of-minimum bar from it, which
        # is fixed where the card is drawn.
        "projection": payouts.project(current, service, history, balance_currency),
    }


@app.get("/api/fleet/economics")
async def api_fleet_economics(request: Request) -> dict[str, Any]:
    """Is each machine worth keeping powered on for what it earns?

    Deliberately per-MACHINE. Adding a bandwidth container to a box that is
    already on costs 1-3 W — below what a consumer smart plug can measure — so a
    per-service net figure would be fabricated precision. The machine-level
    question is the one with an answer: a dedicated 65 W node at 0.20/kWh costs
    about 9.50 a month against a typical 3-6 gross.

    Nothing is ever stopped or throttled on the strength of this. The
    electricity is the operator's and so is the decision.
    """
    _require_auth_api(request)
    config = await database.get_config() or {}
    try:
        # Two features shipped in one release reading DIFFERENT keys for the
        # same tariff, so setting one left the other reporting "cost unknown"
        # forever — and both unknown-paths are deliberately quiet, which is
        # exactly what hid it. power_price_per_kwh is canonical (it shipped
        # first); the newer name is honoured so nobody's existing config breaks.
        price = _tariff_price(config)
    except (TypeError, ValueError):
        price = 0.0

    # The tariff is in the user's own currency; every gross here comes from
    # get_earned_by_platform, which is USD by contract. Subtracting one from the
    # other produced a "losing money — turning it off would save that" verdict
    # off by the whole FX spread, on a payload that carried no currency label at
    # all. Convert the TARIFF, so the endpoint stays canonical USD like the rest
    # of the API and the frontend's display-currency layer can render it.
    tariff_currency = str(config.get("power_currency") or "EUR")
    fx_ok = True
    if price and tariff_currency != "USD":
        converted = exchange_rates.to_usd(price, tariff_currency)
        if converted is None:
            fx_ok = False
        else:
            price = converted

    # Fetched once and reused: this used to query the worker table here and
    # then again inside _get_all_worker_containers, decoding every row twice
    # to build the same list in a single request.
    raw_workers = await database.list_workers()
    workers = [_decoded_worker(w) for w in raw_workers]
    earned = await database.get_earned_by_platform(days=30)
    containers = await _get_all_worker_containers(raw_workers)

    # Attribute each service's gross to the worker running it. A service on two
    # machines splits evenly: without per-node earnings there is no better
    # answer, and pretending otherwise would be invented precision again.
    per_worker_gross: dict[Any, float] = {}
    hosts: dict[str, list[Any]] = {}
    for container in containers:
        slug = egress.container_slug(container)
        if slug:
            hosts.setdefault(slug, []).append(container.get("_worker_id"))
    for slug, worker_ids in hosts.items():
        share = float(earned.get(slug) or 0.0) / max(1, len(worker_ids))
        for worker_id in worker_ids:
            per_worker_gross[worker_id] = per_worker_gross.get(worker_id, 0.0) + share

    assessed = []
    for worker in workers:
        info = worker.get("system_info") or {}
        # Keyed on client_id, not the autoincrement row id.
        #
        # delete_worker removes the row and nothing else, so a host that is
        # removed and re-enrols gets a fresh id — orphaning its watts and
        # dedicated settings silently, while the old keys linger forever. The
        # id is also read from the row-id fallback for volumes written before
        # this change.
        raw_watts = config.get(f"worker_{_worker_config_key(worker)}_watts") or config.get(
            f"worker_{worker.get('id')}_watts"
        )
        try:
            watts = float(raw_watts) if raw_watts else None
        except (TypeError, ValueError):
            watts = None
        assessed.append(
            machine_economics.assess_machine(
                name=worker.get("name") or f"worker {worker.get('id')}",
                # None, not 0.0, when this worker's containers were never
                # counted. per_worker_gross is built only from ONLINE workers
                # (_get_all_worker_containers skips the rest), so defaulting an
                # offline machine to zero earnings is what produced the
                # "turn it off" advice about a host we cannot see.
                monthly_gross=(
                    per_worker_gross.get(worker.get("id"), 0.0) if str(worker.get("status") or "") == "online" else None
                ),
                watts=watts,
                # No rate means the tariff cannot be expressed in the same unit
                # as the earnings, so there is no honest cost. None is already
                # this module's "unknown", and it reports that rather than
                # inventing a net.
                price_per_kwh=(price or None) if fx_ok else None,
                metered=power.is_metered(info),
                dedicated=_worker_flag(config, worker, "dedicated"),
            )
        )

    summary = machine_economics.fleet_summary(assessed)
    # Every figure in this payload is USD. It previously carried no currency at
    # all, so fleet.html printed bare numbers the user could not attribute to a
    # unit — and the numbers themselves mixed two.
    summary["currency"] = "USD"
    if not fx_ok:
        summary["fx_unavailable"] = True
        summary["tariff_currency"] = tariff_currency
        summary["cost_unavailable_reason"] = (
            f"Your electricity tariff is in {tariff_currency} and earnings are recorded in "
            f"USD. No {tariff_currency}-to-USD rate is available right now, so a running "
            "cost would be two different currencies subtracted from each other."
        )
    return summary


@app.get("/api/services/{slug}/deploy-risk")
async def api_deploy_risk(request: Request, slug: str) -> dict[str, Any]:
    """What the user should know BEFORE deploying this, in plain words.

    The documented risk of proxyware is not container escape — it is that
    someone else's traffic exits the user's address and is attributed to them.
    That belongs at the deploy step, not buried in an FAQ: a self-hosting
    audience is persuaded by a project that owns the downside.

    The notice is driven by the service's own disclosure entry, so it fires
    where strangers really do route through the user's IP and stays silent for a
    storage node, where it would be false and would train people to click past
    warnings that matter.
    """
    _require_auth_api(request)
    service = catalog.get_service(slug)
    if not service:
        raise HTTPException(status_code=404, detail=f"Unknown service '{slug}'")

    return {
        "slug": slug,
        "attribution": lan_isolation.attribution_notice(service),
        "isolation": lan_isolation.assess(service),
    }


@app.get("/api/fleet/isolation-guide")
async def api_isolation_guide(request: Request) -> dict[str, Any]:
    """Which services can be LAN-isolated, and what each one needs allowed.

    Returns the recipe rather than applying it. Creating bridges and firewall
    rules on someone's host is a change with real blast radius, and several
    services break in ways that cost money when the exceptions are missed.
    """
    _require_auth_api(request)
    assessed = [lan_isolation.assess(s) for s in catalog.get_services()]
    return {
        "network_name": lan_isolation.DEFAULT_NETWORK_NAME,
        "blocked_destinations": list(lan_isolation.RFC1918 + lan_isolation.LINK_LOCAL),
        "compose_snippet": lan_isolation.compose_snippet(),
        "isolatable": [a["slug"] for a in assessed if a["verdict"] == lan_isolation.ISOLATABLE],
        "needs_exceptions": [a for a in assessed if a["verdict"] == lan_isolation.NEEDS_EXCEPTIONS],
        "not_isolatable": [a for a in assessed if a["verdict"] == lan_isolation.NOT_ISOLATABLE],
    }


@app.get("/api/disclosure/coverage")
async def api_disclosure_coverage(request: Request) -> dict[str, Any]:
    """How much of the catalog is documented, and which services are not.

    Deliberately reports the gap: presenting the documented subset without
    saying what is missing would imply a completeness the catalog does not have.
    """
    _require_auth_api(request)
    return disclosure.coverage(catalog.get_services())


@app.get("/api/payout-registry")
async def api_payout_registry(request: Request) -> dict[str, Any]:
    """Where every service pays out (CashPilot-luj, tier 1).

    OWNER-ONLY, deliberately. The addresses themselves are public data, but this
    response maps one person to all of their wallets at once -- exactly the
    correlation an ordinary viewer has no business being handed.
    """
    _require_owner(request)
    return await payout_registry.registry()


@app.get("/api/payout-balances")
async def api_payout_balances(request: Request) -> dict[str, Any]:
    """What is actually AT each payout address (CashPilot-dv6, tier 2).

    OWNER-ONLY, same reasoning as the registry it builds on.

    A SEPARATE endpoint from /api/payout-registry on purpose. The registry is a
    local join and answers instantly; these are network reads against public
    RPCs that can take seconds or time out. Folding them together would make the
    whole payout table hostage to the slowest chain, so the page renders the
    table first and fills these in afterwards.

    Only addresses we actually hold are queried -- an `internal`, `minted` or
    `unknown` service has no address, and asking a public RPC about nothing is
    both pointless and rude.
    """
    _require_owner(request)
    registry = await payout_registry.registry()

    wanted = [
        row
        for row in registry["entries"]
        if row.get("model") == "external" and row.get("address") and row.get("chain") in onchain.CHAINS
    ]
    results = await onchain.balances([(row["chain"], row["address"]) for row in wanted])

    balances: dict[str, Any] = {}
    for row, result in zip(wanted, results, strict=True):
        # Decimal does not survive JSON. str() keeps every digit, which is the
        # whole reason the reader uses Decimal in the first place -- a float here
        # would undo it at the last step.
        amount = result.get("amount")
        balances[row["slug"]] = {**result, "amount": None if amount is None else str(amount)}

    return {
        "balances": balances,
        # Named so the UI can say "3 of 5 addresses could not be checked"
        # instead of quietly showing fewer rows than it did a moment ago.
        "checked": len(wanted),
        "unreadable": sum(1 for r in results if r.get("state") != onchain.KNOWN),
    }


@app.get("/api/update-status")
async def api_update_status(request: Request) -> dict[str, Any]:
    """Whether a newer CashPilot has been released (CashPilot-w0ss).

    Reads the cached result only -- it never fetches on the request path, so a
    slow or unreachable GitHub cannot make a page load slowly. The scheduler
    refreshes it once a day.

    ``known`` is the honest field. False means we do not know, which is NOT the
    same as up to date, and the UI must not render it as reassurance.
    """
    _require_auth_api(request)
    return update_check.state()


@app.get("/api/collector-alerts")
async def api_collector_alerts(request: Request) -> dict[str, Any]:
    """Collector errors from the last run, and whether a run has happened.

    The bell rendered an empty list as "All collectors healthy". On a fresh
    install — or after a restart, before the first hourly collection — nothing
    has been checked, so that affirmative is unearned: it is the same
    absent-equals-true shape this codebase rejects everywhere else. The bell's
    own FAILURE path is written correctly ("Alerts unavailable" rather than
    healthy), which makes the never-ran case the outlier (CashPilot-tb5).

    Returning an object rather than a bare list so "no alerts" and "nothing has
    run" can be told apart at all. The UI is the only consumer and ships with
    this.
    """
    _require_auth_api(request)
    sanitized: list[dict[str, str]] = []
    for alert in _collector_alerts:
        error_msg = alert.get("error", "")
        clean = error_msg[:_MAX_ALERT_ERROR_LEN]
        if len(error_msg) > _MAX_ALERT_ERROR_LEN:
            clean += "..."
        # `kind` is additive and defaults to "collector", so a frontend that
        # does not read it behaves exactly as before. `category` is the failure
        # TAXONOMY (auth/transient/shape) and is only present when a collector
        # actually classified it -- absent is unknown, never transient.
        entry = {"kind": alert.get("kind", "collector"), "platform": alert["platform"], "error": clean}
        if alert.get("category"):
            entry["category"] = alert["category"]
        sanitized.append(entry)
    return {"alerts": sanitized, "collected": _collection_has_run}


@app.get("/api/exchange-rates")
async def api_exchange_rates(request: Request) -> dict[str, Any]:
    """Return current exchange rates (fiat + crypto) for frontend conversion."""
    _require_auth_api(request)
    return exchange_rates.get_all()


@app.get("/api/services/{slug}/per-node-earnings")
async def api_per_node_earnings(request: Request, slug: str) -> list[dict[str, Any]]:
    """Return per-node earnings for services that support it (e.g. MystNodes)."""
    _require_auth_api(request)
    config = await database.get_config() or {}
    if not isinstance(config, dict):
        config = {}

    # Driven by the catalog, not by a slug comparison. This used to read
    # `if slug == "mysterium"` and import that collector class by name — two
    # pieces of service-specific knowledge in app/, where the repo's own rule
    # says neither belongs. Adding a second service that reports per-node
    # figures meant editing this function; now it means one line of YAML.
    service = catalog.get_service(slug)
    declares_per_node = bool((service.get("collector") or {}).get("per_node_earnings")) if service else False
    if not declares_per_node:
        return []

    # Imported here, matching api_test_credentials: app.collectors pulls in every
    # collector module, and importing it at module scope would drag that whole
    # tree into any process that imports app.main.
    from app import collectors

    collector, missing = collectors.build_one(slug, config)
    if collector is None or missing:
        return []
    try:
        # The capability is declared in YAML, so a service can claim it without
        # its collector implementing it yet. Refuse rather than 500.
        getter = getattr(collector, "get_per_node_earnings", None)
        if getter is None:
            logger.warning("%s declares per_node_earnings but its collector does not implement it", slug)
            return []
        try:
            return await getter()
        except Exception as exc:
            # This call reaches a THIRD-PARTY API: it times out, rate-limits,
            # and returns HTML instead of JSON on a bad day. None of that is a
            # fault in CashPilot, and none of it should reach the user as a raw
            # 500 — every other collector call in this file degrades instead.
            # An empty per-node breakdown alongside the account total is a
            # smaller loss than a broken page.
            logger.warning("Per-node earnings unavailable for %s: %s", slug, exc)
            return []
    finally:
        with contextlib.suppress(Exception):
            await collector.close()


def _config_flag(config: dict[str, Any], key: str) -> bool:
    """A stored config value read as a boolean.

    Config values are TEXT. `bool("false")` is True, so a user who set a flag
    to "false", "0" or "no" got the opposite of what they asked for. Uses the
    same truthy set as database.set_config so a value written by one half of
    the app means the same thing to the other.
    """
    from app.database import _TRUTHY

    return str(config.get(key, "") or "").strip().lower() in _TRUTHY


def _tariff_price(config: dict[str, Any]) -> float:
    """The electricity price per kWh, honouring the legacy key name.

    `electricity_price_per_kwh` was renamed to `power_price_per_kwh`. One
    endpoint accepted both and the other accepted only the new name, so an
    upgrading user who had set the old key saw running costs on the fleet page
    and "cost unknown" on the dashboard, from the same stored value. Both now
    resolve through here.
    """
    return float(config.get("power_price_per_kwh") or config.get("electricity_price_per_kwh") or 0.0)


def _to_usd_with_stored(amount: float, currency: str, stored_rate: float | None) -> float | None:
    """Convert to USD, falling back to the rate the reading was RECORDED at.

    ``exchange_rates.to_usd`` consults only the live caches, so a crypto whose
    rate lookup is merely stale was dropped from the dashboard total entirely —
    silently, with nothing on screen saying the headline figure was incomplete.

    This is not a new rule. ``get_earnings_dashboard_summary`` and
    ``get_earned_by_platform`` already price rows this way, and
    ``upsert_earnings`` stores ``fx_rate_usd`` on every row specifically so
    "the USD value of a historical non-USD reading cannot be reconstructed
    later" without it. The Total was the one figure applying a stricter rule
    than the cards beside it, which is why they disagreed.

    A stored rate is the rate at collection time rather than now — imperfect,
    and much better than omitting the holding. Callers count what still cannot
    be priced so the response can say so.

    Module-level rather than a closure: defined inside the loop it captured
    ``currency`` late, so every conversion would have used the LAST currency
    seen (ruff B023).
    """
    live = exchange_rates.to_usd(amount, currency)
    if live is not None:
        return live
    return amount * stored_rate if stored_rate is not None else None


def _worker_flag(config: dict[str, Any], worker: dict[str, Any], suffix: str) -> bool:
    """A per-worker boolean setting, read by client_id with a row-id fallback.

    Two problems in one place. Config values are TEXT, so ``bool("false")`` is
    True and a user who set a flag to "false" got the opposite of what they
    asked for; ``database._TRUTHY`` is the parser the rest of the app already
    uses. And the key was built from the AUTOINCREMENT row id, which changes
    when a host is removed and re-enrolled — silently orphaning the setting —
    so ``client_id`` is preferred, with the old id-based key still honoured for
    volumes written before this change.
    """
    for key in (f"worker_{_worker_config_key(worker)}_{suffix}", f"worker_{worker.get('id')}_{suffix}"):
        if str(config.get(key, "") or "").strip():
            return _config_flag(config, key)
    return False


def _worker_config_key(worker: dict[str, Any]) -> str:
    """The stable identifier for per-worker config keys.

    The row id is an AUTOINCREMENT primary key and ``delete_worker`` deletes the
    row without touching config, so a host removed and re-enrolled comes back
    under a new id — silently orphaning its watts and dedicated settings while
    the old keys linger. ``client_id`` is UNIQUE and survives re-enrolment,
    which is what these settings should have been keyed on.
    """
    return str(worker.get("client_id") or worker.get("id") or "")


# ---------------------------------------------------------------------------
# API: User Preferences (onboarding state)
# ---------------------------------------------------------------------------


@app.get("/api/preferences")
async def api_get_preferences(request: Request) -> dict[str, Any]:
    user = _require_auth_api(request)
    prefs = await database.get_user_preferences(user["uid"])
    if not prefs:
        return {"setup_mode": "fresh", "selected_categories": "[]", "timezone": "UTC", "setup_completed": False}
    return prefs


class PreferencesUpdate(BaseModel):
    setup_mode: str | None = None
    selected_categories: str | None = None
    timezone: str | None = None
    setup_completed: bool | None = None


@app.post("/api/preferences")
async def api_set_preferences(
    request: Request, body: PreferencesUpdate, user: dict[str, Any] = Depends(_require_auth_api)
) -> dict[str, str]:
    if body.setup_mode is not None and body.setup_mode not in ("fresh", "monitoring", "mixed"):
        raise HTTPException(status_code=400, detail="setup_mode must be fresh, monitoring, or mixed")

    # Merge with existing preferences so partial updates don't overwrite
    existing = await database.get_user_preferences(user["uid"]) or {}
    await database.save_user_preferences(
        user_id=user["uid"],
        setup_mode=body.setup_mode if body.setup_mode is not None else existing.get("setup_mode", "fresh"),
        selected_categories=body.selected_categories
        if body.selected_categories is not None
        else existing.get("selected_categories", "[]"),
        timezone=body.timezone if body.timezone is not None else existing.get("timezone", "UTC"),
        setup_completed=body.setup_completed
        if body.setup_completed is not None
        else existing.get("setup_completed", False),
    )
    # Saving the preference is a viewer-safe act; triggering a fleet-wide
    # collection is not. /api/collect gates the identical call behind
    # _require_writer, so this was the same side effect through a weaker door —
    # a viewer could hit every provider API on demand.
    #
    # The preference itself still saves for any authenticated user; only the
    # collection is gated, so a viewer completing setup is not blocked.
    if body.setup_completed and auth.require_role(user, "owner", "writer"):
        _spawn(_run_collection())
    return {"status": "saved"}


# ---------------------------------------------------------------------------
# API: Environment Info
# ---------------------------------------------------------------------------


@app.get("/api/env-info")
async def api_env_info(request: Request) -> list[dict[str, Any]]:
    _require_owner(request)
    # (key, label, secret, read_only, default, description)
    env_defs = [
        ("CASHPILOT_API_KEY", "Fleet API Key", True, False, "", "Bearer token for worker-to-UI authentication"),
        (
            "CASHPILOT_SECRET_KEY",
            "Session Secret Key",
            True,
            False,
            "changeme-generate-a-random-secret",
            "Secret for JWT session tokens — change from default for security",
        ),
        (
            "CASHPILOT_HOSTNAME_PREFIX",
            "Hostname Prefix",
            False,
            False,
            "cashpilot",
            "Containers named {prefix}-{service}",
        ),
        (
            "CASHPILOT_COLLECT_INTERVAL",
            "Collect Interval (min)",
            False,
            False,
            "60",
            "Minutes between automatic earnings collection",
        ),
        ("CASHPILOT_DATA_DIR", "Data Directory", False, True, "/data", "Directory containing the SQLite database"),
        ("TZ", "System Timezone", False, False, "", "Container timezone in IANA format (e.g. Europe/Madrid)"),
    ]
    result = []
    for key, label, secret, read_only, default, desc in env_defs:
        raw = os.getenv(key, "")
        entry: dict[str, Any] = {
            "key": key,
            "label": label,
            "secret": secret,
            "read_only": read_only,
            "description": desc,
            "set_via_env": bool(raw),
        }
        if key == "CASHPILOT_SECRET_KEY":
            # Auth always resolves a key at runtime (env, persisted, or generated),
            # so it is effectively always set; never expose its value and treat as
            # read-only in the UI.
            entry["is_set"] = True
            entry["read_only"] = True
        elif secret:
            # Drop the value for secrets — only report presence.
            entry["is_set"] = bool(raw)
        else:
            entry["value"] = raw or default
        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# API: Collectors Metadata
# ---------------------------------------------------------------------------


@app.get("/api/collectors/meta")
async def api_collectors_meta(request: Request) -> list[dict[str, Any]]:
    _require_owner(request)
    from app.collectors import _COLLECTOR_ARGS, COLLECTOR_MAP

    # Single-sourced from database.SECRET_CONFIG_KEYS so this endpoint can never
    # disagree with the encryption-at-rest / masking logic about which config
    # keys are secret (a hand-maintained duplicate here previously missed
    # `remember_web` and `xsrf_token`, unmasking them).
    secret_args = database.SECRET_CONFIG_KEYS
    # Credential hints live in the service YAML (collector.credential_hint),
    # not here. They are per-service prose about where to find a token in a
    # provider's UI, which is exactly the service-specific knowledge the
    # catalog exists to hold — 'never hardcode service-specific logic in
    # app/'. Kept in app/ they also drifted out of reach of anyone editing
    # the service they describe.
    meta = []
    for slug in sorted(COLLECTOR_MAP.keys()):
        args = _COLLECTOR_ARGS.get(slug, [])
        svc = catalog.get_service(slug)
        name = svc.get("name", slug) if svc else slug
        fields = []
        for arg in args:
            optional = arg.startswith("?")
            arg_name = arg.lstrip("?")
            config_key = f"{slug}_{arg_name}"
            fields.append(
                {
                    "key": config_key,
                    "label": arg_name.replace("_", " ").title(),
                    "secret": arg_name in secret_args,
                    "required": not optional,
                }
            )
        # Payment currency for bonus offset labeling
        payment = (svc.get("payment", {}) if svc else {}) or {}
        pay_currency = payment.get("currency", "USD")

        entry: dict[str, Any] = {"slug": slug, "name": name, "fields": fields, "currency": pay_currency}
        hint = (svc.get("collector") or {}).get("credential_hint") if svc else None
        if hint:
            entry["hint"] = hint
        meta.append(entry)
    return meta


# ---------------------------------------------------------------------------
# API: Config
# ---------------------------------------------------------------------------


@app.get("/api/config")
async def api_get_config(request: Request) -> dict[str, Any]:
    _require_owner(request)
    # Masked read path: non-secret values plus a {secret_key: is_set} map under
    # "_secrets". Stored credentials never cross the wire in plaintext.
    return await database.get_config_masked()


class ConfigUpdate(BaseModel):
    data: dict[str, str]


def _sanitize_credential(value: str) -> str:
    """Clean common copy-paste artifacts from credential values."""
    from urllib.parse import unquote

    v = value.strip()
    if v.startswith('"') and v.endswith('"'):
        v = v[1:-1]
    if v.startswith("'") and v.endswith("'"):
        v = v[1:-1]
    if "%3D" in v or "%3d" in v or "%2F" in v or "%2f" in v or "%2B" in v or "%2b" in v:
        v = unquote(v)
    return v


@app.post("/api/config")
async def api_set_config(
    request: Request, body: ConfigUpdate, _auth: dict[str, Any] = Depends(_require_owner)
) -> dict[str, str]:
    sanitized = {k: _sanitize_credential(v) for k, v in body.data.items()}
    await database.set_config_bulk(sanitized)

    # Auto-create "external" deployment records for manual-only services
    # whose collector credentials were just saved.  Without a deployment
    # row, _run_collection() will never instantiate the collector.
    from app.collectors import fully_configured_slugs

    # Completeness is judged against the MERGED config, not this request.
    #
    # set_config_bulk UPSERTS, so a credential set can legitimately arrive
    # across several requests — email now, password a moment later. Checking
    # only `sanitized` meant neither request ever saw a complete set, so both
    # values landed in the database and no deployment row was ever created:
    # credentials stored, collection still dead, and nothing to indicate why.
    #
    # Still scoped to the slugs this request touched, so saving one service's
    # credentials does not sweep the whole catalog.
    #
    # The completeness rule itself lives in collectors.fully_configured_slugs,
    # shared with the startup backfill so the two can never disagree about which
    # services are ready to collect.
    stored = await database.get_config() or {}
    for slug in fully_configured_slugs(stored):
        if not any(k.startswith(f"{slug}_") for k in sanitized):
            continue
        svc = catalog.get_service(slug)
        if not svc:
            continue
        # No has_image gate. Collection is driven by DEPLOYMENT ROWS
        # (make_collectors iterates deployments), so a service with no row is
        # never collected no matter how complete its credentials are. Skipping
        # image-backed services here meant that for 12 of the 15 collectors,
        # saving credentials did nothing at all — while Settings promised
        # "You don't need to deploy containers through CashPilot — just add
        # your credentials." The badge flipped to Configured and no earnings
        # ever arrived.
        #
        # Creating the row is safe for a user who later deploys through
        # CashPilot: api_deploy calls save_deployment with the real container
        # id and status, replacing this placeholder.
        existing = await database.get_deployment(slug)
        if not existing:
            await database.save_deployment(slug=slug, container_id="", status="external")
            logger.info("Tracking %s from stored credentials (no container deployed by CashPilot)", slug)

    return {"status": "saved"}


@app.delete("/api/config/{slug}")
async def api_clear_service_config(request: Request, slug: str) -> dict[str, str]:
    """Remove all stored credentials (and signup bonus) for a service."""
    _require_owner(request)
    from app.collectors import _COLLECTOR_ARGS

    arg_keys = _COLLECTOR_ARGS.get(slug)
    if not arg_keys:
        raise HTTPException(status_code=404, detail="Unknown service")

    config_keys = [f"{slug}_{a.lstrip('?')}" for a in arg_keys]
    config_keys.append(f"{slug}_signup_bonus")
    await database.delete_config_keys(config_keys)

    # Remove the row only if it is the placeholder we auto-created.
    #
    # Gated on status == "external", NOT on whether the service has an image.
    # Clearing credentials must never undeploy a container the user actually
    # deployed through CashPilot — that row has a real container id and a
    # status of its own, and removing it would orphan a running container from
    # the dashboard.
    existing = await database.get_deployment(slug)
    if existing and (existing.get("status") or "") == "external":
        await database.remove_deployment(slug)

    logger.info("Cleared credentials for %s", slug)
    return {"status": "cleared"}


# ---------------------------------------------------------------------------
# API: Users — change password (owner-reset + self-service).
#
# User list/role/delete routes live in app.routers.users. The password routes
# stay here to avoid the direct-import problem (no test imports them directly).
# ---------------------------------------------------------------------------


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class AdminPasswordSet(BaseModel):
    new_password: str


@app.post("/api/users/me/password")
async def api_change_own_password(
    request: Request, body: PasswordChange, user: dict[str, Any] = Depends(_require_auth_api)
) -> JSONResponse:
    """Change the authenticated user's own password (verifies current password)."""
    uid = user["uid"]
    if uid == 0:
        raise HTTPException(status_code=400, detail="API-key sessions cannot change a password")
    record = await database.get_user_by_id(uid)
    if not record:
        raise HTTPException(status_code=404, detail="User not found")
    if not await auth.verify_password_async(body.current_password, record["password"]):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    if len(body.new_password) < 10:
        raise HTTPException(status_code=400, detail="Password must be at least 10 characters")
    if body.new_password == body.current_password:
        raise HTTPException(status_code=400, detail="New password must differ from the current password")

    hashed = await auth.hash_password_async(body.new_password)
    await database.update_user_password(uid, hashed)
    changed = await database.get_user_by_id(uid)
    auth.set_user_pwd_epoch(uid, changed["password_changed_at"])
    # Re-mint the session cookie so the caller stays logged in after the epoch bump.
    token = auth.create_session_token(uid, user["u"], user["r"])
    return auth.set_session_cookie(JSONResponse({"status": "password_changed"}), token, request)


@app.post("/api/users/{user_id}/password")
async def api_admin_set_password(
    request: Request, user_id: int, body: AdminPasswordSet, _auth: dict[str, Any] = Depends(_require_owner)
) -> dict[str, str]:
    """Owner resets another user's password (no current-password check, no re-mint)."""
    target = await database.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if len(body.new_password) < 10:
        raise HTTPException(status_code=400, detail="Password must be at least 10 characters")
    hashed = await auth.hash_password_async(body.new_password)
    await database.update_user_password(user_id, hashed)
    changed = await database.get_user_by_id(user_id)
    auth.set_user_pwd_epoch(user_id, changed["password_changed_at"])
    return {"status": "password_set"}


# ---------------------------------------------------------------------------
# API: Fleet (Workers)
# ---------------------------------------------------------------------------


def _bearer_token(request: Request) -> str:
    """Extract the bearer token from an Authorization header (empty if absent)."""
    h = request.headers.get("Authorization", "")
    return h[7:] if h.startswith("Bearer ") else ""


WORKER_KEY_CONFIRM_WINDOW = timedelta(hours=24)


def _humanize_window() -> str:
    hours = WORKER_KEY_CONFIRM_WINDOW.total_seconds() / 3600
    return f"more than {hours:g} hours" if hours >= 1 else f"more than {WORKER_KEY_CONFIRM_WINDOW.total_seconds():g}s"


def enrollment_state(key_issued_at: str | None, confirmed: bool, now: datetime | None = None) -> str:
    """``"confirmed"``, ``"pending"`` (still inside the window) or ``"incomplete"``.

    Pure, so the heartbeat guard and the fleet page cannot disagree about which
    workers are still enrolling and which have stalled.

    An UNPARSEABLE or missing timestamp reads as ``"pending"``. That is the safe
    direction: reading unknown as expired would lock out a worker on the
    strength of a value nobody wrote.
    """
    if confirmed:
        return "confirmed"
    if not key_issued_at:
        return "pending"
    try:
        issued = datetime.fromisoformat(key_issued_at).replace(tzinfo=UTC)
    except (TypeError, ValueError):
        logger.warning(
            "Worker key issue time %r is unparseable; treating enrollment as still in progress", key_issued_at
        )
        return "pending"
    return "pending" if (now or datetime.now(UTC)) - issued <= WORKER_KEY_CONFIRM_WINDOW else "incomplete"


async def _enrollment_window_open(cid: str) -> bool:
    """Whether the shared key may still be honoured for this enrolled worker.

    A second read of the same row, rather than widening ``get_worker_key_state``.
    It is reached only on the rare branch — a worker that has a key, has never
    used it, and is presenting the shared key. Every steady-state heartbeat
    returns "ok" before this line, so this is not on the hot path.
    """
    return enrollment_state(await database.get_worker_key_issued_at(cid), confirmed=False) == "pending"


async def _authenticate_worker_heartbeat(request: Request, cid: str) -> str:
    """Authenticate a heartbeat and classify it. Returns one of:

    - ``"enroll"``  — worker has no key yet and presented the shared key: mint one.
    - ``"reissue"`` — worker has a key that is NOT yet confirmed and presented the
      shared key: it likely lost the enrollment response, so re-deliver the SAME
      key. Until confirmed, the shared key still works for this one worker — a
      window that closes on the worker's first own-key heartbeat OR after
      ``WORKER_KEY_CONFIRM_WINDOW`` from the key being minted, whichever comes
      first.

    That second bound is the whole point of this function. The window used to
    close only on confirmation, so a worker that CANNOT persist its key — a
    pre-1.0.0 image, a read-only /data, an ephemeral container — never closed it
    at all. The security cutover the per-worker keys exist for silently never
    completed: anyone holding CASHPILOT_API_KEY could impersonate that worker
    indefinitely, and the UI re-sent the key to them every 60 seconds while
    logging "not yet confirmed" once a minute forever.
    - ``"ok"``      — worker presented its own key: authenticated; confirm it so the
      shared key is refused from now on (the cutover finalizes).

    Raises 401 otherwise — notably, a confirmed worker presenting the shared key is
    rejected, which is what stops shared-key holders from impersonating a worker.
    """
    if not FLEET_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Fleet key not configured — set CASHPILOT_API_KEY or mount shared /fleet volume",
        )
    token = _bearer_token(request)
    key, confirmed = await database.get_worker_key_state(cid) if cid else (None, False)
    shared_ok = bool(token) and hmac.compare_digest(token.encode(), FLEET_API_KEY.encode())
    if key is None:
        if shared_ok:
            return "enroll"
        raise HTTPException(status_code=401, detail="Invalid API key")
    if token and hmac.compare_digest(token.encode(), key.encode()):
        return "ok"
    if not confirmed and shared_ok:
        if await _enrollment_window_open(cid):
            return "reissue"
        # Past the window. Refusing here is the cutover finally completing for a
        # worker that could never complete it itself. Said plainly, because the
        # operator's next question is why a worker that was working stopped.
        logger.warning(
            "Worker '%s' presented the SHARED key %s after enrolling and has never used its own key. "
            "The shared key is no longer accepted for it: a worker that cannot persist "
            "/data/.worker_key would otherwise keep the shared key valid for its identity forever. "
            "Upgrade that worker to 1.0.0+, give it a writable and PERSISTENT /data, then remove it "
            "in the fleet page so it can enroll again.",
            cid,
            _humanize_window(),
        )
        raise HTTPException(
            status_code=401,
            detail=(
                "Enrollment was never completed for this worker and the shared key is no longer "
                "accepted for it. Upgrade the worker to 1.0.0+ with a writable, persistent /data, "
                "then remove it in the fleet page so it can enroll again."
            ),
        )
    raise HTTPException(status_code=401, detail="Invalid or missing per-worker key")


class WorkerHeartbeat(BaseModel):
    name: str
    url: str = ""
    client_id: str = ""
    containers: list[dict[str, Any]] = []
    apps: list[dict[str, Any]] = []
    system_info: dict[str, Any] = {}


def _android_app_status(running: object) -> str:
    """How an Android app's three-valued ``running`` reads as a container status.

    ``None`` is UNKNOWN and must not become ``"stopped"``. The phone reports it
    when it cannot see -- notification-listener and usage access are what make
    detection possible at all, and without them every signal reads false. A
    worker on an older client that never sends null is unaffected.
    """
    if running is None:
        return "unknown"
    return "running" if running else "stopped"


async def _earnings_for_worker(body: WorkerHeartbeat, days: int = 30) -> dict[str, Any] | None:
    """What the platforms on THIS worker have earned, for the client to display.

    Returned in the heartbeat response rather than from a new endpoint, because
    the heartbeat is the ONE call a worker is already authenticated for. Every
    earnings route goes through ``_require_auth_api``, which needs a user
    session; a per-worker key cannot read any of them, and handing a phone an
    owner-level credential so it can show a number would be a bad trade.

    THE HONESTY CONSTRAINT, which shapes the whole payload:

    Earnings are collected per PLATFORM, from the provider's account. They are
    not, and cannot be, attributed to a device. If two machines both run Grass,
    the provider reports one balance and nothing can split it. So this never
    says "this device earned X" — it says "the platforms this device is running
    earned X on your account", and it flags each platform that is running on
    more than one worker so the client can say so too.

    Returns None when the figures cannot be produced at all. None means unknown;
    a caller must not render it as zero.
    """
    slugs = {
        str(entry.get("slug") or "").strip()
        for entry in (body.apps or []) + (body.containers or [])
        if str(entry.get("slug") or "").strip()
    }
    if not slugs:
        return None

    try:
        earned = await database.get_earned_by_platform(days)
        workers = await database.list_workers()
    except Exception as exc:  # noqa: BLE001 - a heartbeat must never fail on this
        logger.warning("Could not attach earnings to the heartbeat response: %s", exc)
        return None

    # Which platforms run on more than one worker. Counted across the fleet, not
    # just this device, because that is what makes a per-device claim false.
    running_on: dict[str, int] = {}
    for worker in workers:
        _parse_worker_json(worker)
        seen: set[str] = set()
        for entry in (worker.get("apps") or []) + (worker.get("containers") or []):
            slug = str(entry.get("slug") or "").strip()
            if slug and slug not in seen:
                seen.add(slug)
                running_on[slug] = running_on.get(slug, 0) + 1

    platforms = []
    for slug in sorted(slugs):
        # A platform with no reading is UNKNOWN, not zero. Absent from `earned`
        # means nothing has ever been collected for it -- most often no collector
        # exists, or its credentials were never entered.
        value = earned.get(slug)
        platforms.append(
            {
                "slug": slug,
                "usd": round(value, 4) if value is not None else None,
                "shared_with_other_workers": running_on.get(slug, 0) > 1,
            }
        )

    known = [p["usd"] for p in platforms if p["usd"] is not None]
    return {
        "window_days": max(1, int(days)),
        "currency": "USD",
        "platforms": platforms,
        # Only sums what is actually known. A total that silently treats unknown
        # as zero is the same lie in aggregate.
        "total_usd": round(sum(known), 4) if known else None,
        "platforms_without_readings": [p["slug"] for p in platforms if p["usd"] is None],
    }


#: The exact shape ``upsert_earnings`` writes and both delta readers ORDER BY.
#: A date in any other shape would sort into the wrong place in its own series,
#: so the readings either side of it difference against the wrong neighbour --
#: silently, and only for the client that sent it.
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class EarningsReading(BaseModel):
    """One historical balance reading from a paired client."""

    slug: str
    #: allow_inf_nan=False because JSON's `NaN` and `Infinity` -- which Python's
    #: parser accepts even though the spec does not -- are otherwise stored
    #: verbatim. One NaN balance poisons every delta taken from that series
    #: (NaN - x is NaN, and every comparison against it is False, so the clamp
    #: silently misbehaves), the account total becomes NaN, and serialising that
    #: back out emits a bare `NaN` that JSON.parse rejects. So a single bad
    #: reading from one client breaks the dashboard for everyone.
    balance: float = Field(allow_inf_nan=False)
    date: str
    currency: str = "USD"
    fx_rate_usd: float | None = Field(default=None, allow_inf_nan=False)

    @field_validator("date")
    @classmethod
    def _iso_date(cls, value: str) -> str:
        value = (value or "").strip()
        if not _ISO_DATE.match(value):
            raise ValueError("date must be YYYY-MM-DD")
        # Reject 2026-02-30 and friends: the pattern above only proves shape.
        try:
            datetime.strptime(value, "%Y-%m-%d")  # noqa: DTZ007 -- a calendar date, not an instant
        except ValueError as exc:
            raise ValueError("date must be a real calendar date") from exc
        return value


class EarningsImport(BaseModel):
    """A client pushing the history it collected before it was paired.

    Deliberately carries NO source field. The source is taken from the
    AUTHENTICATED worker, never from the body -- otherwise any enrolled client
    could write into the 'server' series, or into another machine's, and
    overwrite readings it never took.
    """

    client_id: str
    #: Bounded so one authenticated client cannot hand the server an
    #: arbitrarily large body to parse and then write row by row. 2000 is
    #: comfortably above a real import -- the server keeps 400 days, and a
    #: client chunks anything larger -- while staying a body the process can
    #: hold. An unbounded list here is a denial of service that needs only one
    #: compromised worker.
    readings: list[EarningsReading] = Field(default_factory=list, max_length=2000)


@app.post("/api/workers/earnings-import")
async def api_worker_earnings_import(request: Request, body: EarningsImport) -> dict[str, Any]:
    """Accept a paired client's historical earnings under its own source.

    This exists because the server and a Desktop can both have been reading the
    SAME provider account. Their readings must not be merged into one series:
    earnings are clamped deltas between consecutive readings, so interleaving two
    samplers makes every drop clamp to zero and the total comes out
    systematically understated. Each client's rows therefore land under its own
    ``source`` and are differenced separately.

    Idempotent by construction: the (platform, source, date) unique index means a
    re-pair or a retried import UPDATES a day rather than adding a second reading
    for it, which would difference against itself and read as zero.
    """
    cid = (body.client_id or "").strip()
    if not cid:
        raise HTTPException(status_code=400, detail="client_id required")

    state = await _authenticate_worker_heartbeat(request, cid)
    # Only a CONFIRMED worker may import. "enroll" and "reissue" both mean the
    # caller presented the SHARED key, which every worker holds -- accepting it
    # here would let anyone with that token write a history for any client_id
    # they cared to name. A heartbeat is idempotent status; this is durable
    # money data, so it gets the stricter bar.
    if state != "ok":
        raise HTTPException(
            status_code=403,
            detail=(
                "Importing earnings requires this worker's own key. Send a heartbeat first "
                "to complete enrollment, then retry."
            ),
        )

    known = {s["slug"] for s in catalog.get_services()}
    # DISTINCT slugs, not one entry per skipped reading. A client pushing 400
    # days of a platform this server does not know would otherwise get the same
    # name back 400 times -- a response that grows with the request, echoing
    # client-supplied strings, and tells the reader nothing the set does not.
    skipped: set[str] = set()
    rows: list[dict[str, Any]] = []
    for reading in body.readings:
        slug = (reading.slug or "").strip()
        # An unknown slug is dropped rather than stored: it would create a
        # platform the catalog cannot render, name or ever collect for again.
        if not slug or slug not in known:
            skipped.add(slug or "(blank)")
            continue
        rows.append(
            {
                "platform": slug,
                "balance": float(reading.balance),
                "currency": (reading.currency or "USD").upper(),
                "date": reading.date,
                "fx_rate_usd": reading.fx_rate_usd,
                "source": cid,
            }
        )

    # ONE transaction for the whole batch. Writing row by row committed once per
    # reading, and every commit is an fsync that takes SQLite's write lock -- so
    # a thousand-reading import serialised a thousand disk syncs against this
    # server's own collector, and latency tracked sync cost rather than row
    # count. It also makes the import all-or-nothing: a failure part-way leaves
    # the client's history exactly as it was rather than half-applied, and the
    # import is idempotent so retrying costs a round trip. (CodeRabbit, PR #256.)
    written = await database.upsert_earnings_many(rows)

    logger.info(
        "Imported %d earnings reading(s) from worker '%s' (%d unknown platform(s) skipped)",
        written,
        cid,
        len(skipped),
    )
    return {"status": "ok", "imported": written, "skipped": sorted(skipped), "source": cid}


@app.post("/api/workers/heartbeat")
async def api_worker_heartbeat(request: Request, body: WorkerHeartbeat) -> dict[str, Any]:
    """Receive a heartbeat from a worker. Registers or updates the worker."""
    # Use client_id for identity; fall back to name for backward compat
    cid = body.client_id or body.name
    if not cid:
        raise HTTPException(status_code=400, detail="Worker name or client_id required")
    state = await _authenticate_worker_heartbeat(request, cid)
    # Pre-upsert state: upsert_worker unconditionally writes 'online', so the
    # offline -> online recovery is only observable here, before it runs.
    # Best-effort on purpose: this read failing must never reject a heartbeat
    # (the upsert below is the loud path if the DB is really broken); the cost
    # is one missed immediate alert-clear, which the 24h cooldown self-heals.
    previous = None
    try:
        previous = await database.get_worker_status_and_name(cid)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not read pre-heartbeat worker state for %s: %s", cid, exc)
    worker_id = await database.upsert_worker(
        client_id=cid,
        name=body.name,
        url=body.url,
        containers=json.dumps(body.containers),
        apps=json.dumps(body.apps),
        system_info=json.dumps(body.system_info),
    )
    metrics.record_heartbeat(body.name)
    if previous is not None and previous[0] == "offline":
        # Recovered — drop the stored alert so the NEXT outage notifies again
        # instead of being deduped inside the cooldown window, and prune the
        # bell entry now rather than at the next hourly rebuild. Keyed by
        # client_id (the identity), never the cosmetic display name. Best
        # effort on purpose: a DB hiccup here must never fail a HEARTBEAT —
        # the stale-worker sweep reconciles any clear this misses.
        try:
            await database.clear_alerts("worker", cid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not clear the offline alert for recovered worker %s (sweep will): %s", cid, exc)
        else:
            global _collector_alerts
            _collector_alerts = [
                a for a in _collector_alerts if not (a.get("kind") == "worker" and a.get("client_id") == cid)
            ]
        logger.info("Worker '%s' is back online", previous[1])
    resp: dict[str, Any] = {"status": "ok", "worker_id": worker_id}
    if state == "enroll":
        # First contact: mint this worker's own key and hand it back once. Stored
        # unconfirmed until the worker proves receipt by using it (see "ok").
        new_key = secrets.token_urlsafe(32)
        await database.set_worker_key(cid, new_key)
        resp["worker_key"] = new_key
        logger.info("Worker '%s' enrolled — per-worker key issued (awaiting confirmation)", cid)
    elif state == "reissue":
        # The worker still holds the shared key, so it never received/persisted its
        # own key — re-deliver the same one so a dropped enrollment response can't
        # lock it out.
        existing = await database.get_worker_key(cid)
        if existing:
            resp["worker_key"] = existing
        logger.info("Worker '%s' re-issued its per-worker key (not yet confirmed)", cid)
    elif state == "ok":
        # The worker authenticated with its own key: finalize the cutover so the
        # shared key is refused from now on.
        await database.confirm_worker_key(cid)

    # What the platforms on this worker have earned, so a client can show money
    # without needing a second, broader credential. Absent when it cannot be
    # produced -- the key is omitted rather than sent as an empty object, so a
    # client can tell "unknown" from "nothing earned" (CashPilot-android-35t).
    earnings = await _earnings_for_worker(body)
    if earnings is not None:
        resp["earnings"] = earnings
    return resp


@app.get("/api/workers")
async def api_list_workers(request: Request) -> list[dict[str, Any]]:
    """List all registered workers."""
    _require_auth_api(request)
    workers = await database.list_workers()
    config = await database.get_config() or {}
    ui_version = version.current()
    for w in workers:
        _parse_worker_json(w)
        # Skew is judged here, where the UI's own version is known, rather than
        # in the browser: the fleet page would otherwise have to learn what the
        # UI is running and re-implement the comparison. Both sides must be
        # known releases for this to be True, so an older worker that predates
        # version reporting reads as unknown, not as a mismatch.
        w["ui_version"] = ui_version
        # An Android client ships on its OWN release track, so the UI's version
        # is the wrong yardstick: a phone on 0.3.0 against a UI on 1.24.1 is not
        # skew, it is two different products, and comparing them flagged EVERY
        # Android device permanently. Compare a phone against the newest
        # CashPilot-android release instead.
        #
        # reference_version is what the worker was actually judged against, so
        # the UI can say so rather than always claiming "UI vX".
        si = w.get("system_info") or {}
        is_android = str(si.get("os") or "").strip().lower() == "android"
        reference = update_check.android_latest() if is_android else ui_version
        w["reference_version"] = reference
        # Unknown reference -> no skew. version.skewed() already returns False
        # when either side is unknown, which is what keeps an offline install
        # (or a GitHub outage) from lighting a warning on every phone.
        w["version_skew"] = version.skewed(reference, si.get("version"))
        # The per-machine power settings the running-costs card needs, read the
        # SAME way api_fleet_economics reads them — client_id first, row id as
        # the fallback for values written before that changed. Returning them
        # here is what lets the fleet page show the current value in its input
        # rather than an empty box that silently overwrites what is stored.
        raw_watts = config.get(f"worker_{_worker_config_key(w)}_watts") or config.get(f"worker_{w.get('id')}_watts")
        w["watts"] = raw_watts or ""
        w["dedicated"] = _worker_flag(config, w, "dedicated")
        # Whether this worker ever finished the per-worker-key cutover. Without
        # it the only trace was a UI log line once a minute, which nobody reads,
        # so a worker still authenticating with the SHARED key looked identical
        # to a fully enrolled one on the fleet page.
        w["enrollment"] = enrollment_state(w.get("key_issued_at"), bool(w.get("key_confirmed")))
    return workers


def _parse_worker_json(w: dict[str, Any]) -> None:
    """Parse stored JSON columns and compute counts for a worker dict.

    Also drops the worker's encrypted fleet key, because ``list_workers`` is a
    ``SELECT *`` and every path that renders a worker to a client goes through
    here. The key is a credential: it is what a worker authenticates with, and
    it has no use in a dashboard. Encrypted at rest is not a reason to hand the
    ciphertext to every logged-in viewer — it makes the Fernet key the only
    thing standing between a read-only account and the whole fleet's
    credentials, when nothing needed to publish it at all.

    Stripped here rather than in ``list_workers`` on purpose: the stale-worker
    purge legitimately reads ``api_key_enc`` to tell an enrolled worker from one
    that never enrolled, and it does not go through this function.
    """
    w.pop("api_key_enc", None)
    w["containers"] = _safe_json(w.get("containers", "[]"))
    w["apps"] = _safe_json(w.get("apps", "[]"))
    w["system_info"] = _safe_json(w.get("system_info", "{}"), {})
    is_android = w["system_info"].get("device_type") == "android"
    if is_android:
        w["container_count"] = len(w["apps"])
        w["running_count"] = sum(1 for a in w["apps"] if a.get("running"))
    else:
        w["container_count"] = len(w["containers"])
        w["running_count"] = sum(1 for c in w["containers"] if c.get("status") == "running")


@app.get("/api/workers/{worker_id}")
async def api_get_worker(request: Request, worker_id: int) -> dict[str, Any]:
    """Get details for a specific worker."""
    _require_auth_api(request)
    worker = await database.get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    _parse_worker_json(worker)
    return worker


@app.delete("/api/workers/{worker_id}")
async def api_delete_worker(request: Request, worker_id: int) -> dict[str, str]:
    """Remove a registered worker."""
    _require_owner(request)
    worker = await database.get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    await database.delete_worker(worker_id)
    return {"status": "deleted"}


class WorkerCommand(BaseModel):
    command: str  # deploy, stop, restart, start, remove
    slug: str = ""
    spec: dict[str, Any] = {}


@app.post("/api/workers/{worker_id}/command")
async def api_worker_command(request: Request, worker_id: int, body: WorkerCommand) -> dict[str, Any]:
    """Send a command to a worker by proxying to its REST API."""
    # Deploy is owner-gated everywhere else (see /api/deploy/{slug}); a writer
    # must not be able to bypass that gate by sending command="deploy" here.
    if body.command == "deploy":
        _require_owner(request)
    else:
        _require_writer(request)

    if body.command == "deploy":
        # This is a THIRD deploy path. Without the same status gate, a broken or
        # dropped service could still be deployed here — and this route then runs the
        # full bookkeeping below, so it would look deployed while earning nothing.
        # An unknown slug is left alone: this raw route is not catalog-only.
        deploy_status = (catalog.get_service(body.slug) or {}).get("status")
        if deploy_status in _UNDEPLOYABLE_STATUSES:
            raise HTTPException(
                status_code=409 if deploy_status == "broken" else 410,
                detail=f"Service '{body.slug}' is no longer available for deployment ({deploy_status})",
            )
        result = await _proxy_to_worker(worker_id, "POST", f"/api/containers/{body.slug}/deploy", json=body.spec)
    elif body.command in ("stop", "restart", "start"):
        result = await _proxy_to_worker(worker_id, "POST", f"/api/containers/{body.slug}/{body.command}")
    elif body.command == "remove":
        result = await _proxy_to_worker(worker_id, "DELETE", f"/api/containers/{body.slug}")
    else:
        raise HTTPException(status_code=400, detail=f"Unknown command: {body.command}")

    # The primary lifecycle routes (/api/deploy, /api/stop, ...) all run bookkeeping
    # after a successful proxy. Without it a deploy through this raw command route never
    # creates a deployments row — so the service earns $0 forever — and a remove leaks
    # the row. Mirror the canonical routes exactly, keyed on the command, on success only.
    slug = body.slug
    if body.command == "deploy":
        container_id = result.get("container_id", "remote")
        # Record the spec this route actually deployed. It is supplied raw by the
        # caller rather than built from the catalog, so it is the only description
        # of this container that will ever exist.
        await database.save_deployment(
            slug=slug,
            container_id=container_id,
            spec=body.spec if isinstance(body.spec, dict) else None,
        )
        await database.record_health_event(slug, "start", f"deployed to worker {worker_id}")
        metrics.record_container_lifecycle("deploy", slug)
        _spawn(_run_collection())
    elif body.command == "stop":
        await database.record_health_event(slug, "stop")
        metrics.record_container_lifecycle("stop", slug)
    elif body.command == "restart":
        await database.record_health_event(slug, "restart")
        metrics.record_container_lifecycle("restart", slug)
    elif body.command == "start":
        await database.record_health_event(slug, "start")
        metrics.record_container_lifecycle("start", slug)
    elif body.command == "remove":
        await database.remove_deployment(slug)
        await database.record_health_event(slug, "remove")
        metrics.record_container_lifecycle("remove", slug)
    return result


@app.get("/api/fleet/summary")
async def api_fleet_summary(request: Request) -> dict[str, Any]:
    """Aggregate fleet stats across local + all workers."""
    _require_reader(request)

    workers = await database.list_workers()
    total_services = 0
    total_running = 0
    online_workers = 0

    # Containers on workers that are NOT online. They are still running and
    # still earning -- an unreachable worker is a reporting gap, not a stopped
    # one -- so the fleet page can say how much of the estate these cards leave
    # out instead of letting a reboot read as containers lost (CashPilot-wij).
    unreachable_containers = 0
    unreachable_workers = 0

    for w in workers:
        _parse_worker_json(w)
        if w["status"] != "online":
            if w["container_count"]:
                unreachable_workers += 1
                unreachable_containers += w["container_count"]
            continue
        online_workers += 1
        total_services += w["container_count"]
        total_running += w["running_count"]

    return {
        "total_workers": len(workers),
        "online_workers": online_workers,
        "total_containers": total_services,
        "running_containers": total_running,
        "unreachable_containers": unreachable_containers,
        "unreachable_workers": unreachable_workers,
    }


@app.get("/api/fleet/api-key")
async def api_fleet_api_key(request: Request) -> dict[str, Any]:
    """Report whether a fleet API key is configured (owner only).

    Never returns the key value — use POST /api/fleet/api-key/reveal for that.
    """
    _require_owner(request)
    source = "env" if os.getenv("CASHPILOT_API_KEY") else ("file" if FLEET_API_KEY else "none")
    return {"is_set": bool(FLEET_API_KEY), "source": source}


@app.post("/api/fleet/api-key/reveal")
async def api_fleet_api_key_reveal(request: Request) -> dict[str, str]:
    """Reveal the configured fleet API key (owner only, audit-logged)."""
    user = _require_owner(request)
    logger.warning("Fleet key revealed by uid=%s", user.get("uid"))
    return {"api_key": FLEET_API_KEY or ""}


# ---------------------------------------------------------------------------
# Router groups (auth / pages / users)
#
# Imported and included LAST, after ``app`` and every shared symbol above is
# defined, so the handlers (which reference state via ``app.main.*``) resolve
# correctly. Kept here to preserve the public ``app.main`` test surface while
# splitting the low-regression route groups into app.routers.
# ---------------------------------------------------------------------------
from app.routers import auth as auth_router  # noqa: E402
from app.routers import pages as pages_router  # noqa: E402
from app.routers import users as users_router  # noqa: E402

app.include_router(auth_router.router)
app.include_router(pages_router.router)
app.include_router(users_router.router)
