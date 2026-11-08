"""A device the provider does not know yet is registered later, not dropped.

ProxyRack only knows a new UUID about five minutes after its client first
connects, and /device/add answers "Device not found ... try again in 5
minutes" until then. The deploy used to make one attempt at that moment,
report "not added" and never try again, so every new device stayed off the
account and earned for nobody. Now the refusal is stored, retried with
backoff, and handed to the user after a day.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import database, main, proxies

UUID = "AB" * 32
NOT_YET = (
    400,
    {
        "status": "error",
        "error": "Invalid request parameters",
        "details": {
            "device_id": "Device not found. If you recently installed a device it may take 5 minutes "
            "before it is found in our system. Please try again in 5 minutes."
        },
    },
)
UNKNOWN = (400, {"status": "error", "details": {"device_id": "The selected device id is invalid."}})
ADDED = (200, {"status": "success", "message": "Device added successfully", "data": {}})


def _api(answers):
    calls = []

    async def post(url, headers=None, json=None):
        path = url.rsplit("/api", 1)[1]
        calls.append(path)
        status, body = answers[path]
        resp = MagicMock()
        resp.status_code = status
        resp.json.return_value = body
        return resp

    client = AsyncMock()
    client.is_closed = False
    client.post.side_effect = post
    return client, calls


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "cashpilot.db")
    asyncio.run(database.init_db())


def _run(coro_fn):
    return asyncio.run(coro_fn())


def _with_api(answers, deployed=(UUID,), copies=()):
    api, calls = _api(answers)
    stack = [
        patch("app.collectors.proxyrack.httpx.AsyncClient", return_value=api),
        patch.object(main.database, "get_config", new_callable=AsyncMock, return_value={"proxyrack_api_key": "k"}),
        patch.object(main.database, "get_deployed_env_values", new_callable=AsyncMock, return_value=set(deployed)),
        patch.object(main.database, "list_proxied_copies", new_callable=AsyncMock, return_value=list(copies)),
        patch.object(main, "_spawn"),
    ]
    return stack, calls


def _enter(stack):
    for p in stack:
        p.start()


def _exit(stack):
    for p in reversed(stack):
        p.stop()


def test_a_device_the_provider_does_not_know_yet_is_stored_to_retry(db):
    stack, _ = _with_api({"/device/add": NOT_YET, "/device/status": UNKNOWN})
    _enter(stack)
    try:
        result = _run(lambda: main._register_device("proxyrack", UUID, {"DEVICE_NAME": "box"}))
        rows = _run(database.list_pending_device_links)
    finally:
        _exit(stack)
    assert result is None  # neither added nor a dead end
    assert [(r["slug"], r["device_id"], r["name"], r["gave_up"]) for r in rows] == [("proxyrack", UUID, "box", 0)]
    # The first retry waits out the provider's five minutes.
    first_retry = datetime.strptime(rows[0]["next_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    assert timedelta(minutes=5) < first_retry - datetime.now(UTC) <= main.DEVICE_LINK_FIRST_RETRY


def _due(device_id=UUID, attempts=0, first_at=None):
    async def go():
        await database.save_pending_device_link("proxyrack", device_id, "box", "2000-01-01 00:00:00")
        if first_at:
            conn = await database._get_db()
            try:
                await conn.execute("UPDATE pending_device_links SET first_at = ?, attempts = ?", (first_at, attempts))
                await conn.commit()
            finally:
                await conn.close()

    _run(go)


async def _health_events():
    conn = await database._get_db()
    try:
        cursor = await conn.execute("SELECT slug, event FROM health_events")
        return [(r["slug"], r["event"]) for r in await cursor.fetchall()]
    finally:
        await conn.close()


def test_a_retry_that_succeeds_marks_the_device_added(db):
    _due()
    stack, calls = _with_api({"/device/add": ADDED})
    _enter(stack)
    try:
        _run(main._retry_device_links)
        rows = _run(database.list_pending_device_links)
        events = _run(_health_events)
    finally:
        _exit(stack)
    assert calls == ["/device/add"]
    assert rows == []
    assert ("proxyrack", "device_linked") in events


def test_a_retry_the_provider_still_refuses_backs_off(db):
    _due()
    stack, _ = _with_api({"/device/add": NOT_YET, "/device/status": UNKNOWN})
    _enter(stack)
    try:
        _run(main._retry_device_links)
        (row,) = _run(database.list_pending_device_links)
    finally:
        _exit(stack)
    assert row["attempts"] == 1 and row["gave_up"] == 0
    wait = datetime.strptime(row["next_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC) - datetime.now(UTC)
    assert timedelta(minutes=11) < wait <= main.DEVICE_LINK_FIRST_RETRY * 2


def test_after_a_day_it_gives_up_and_tells_the_user(db):
    old = (datetime.now(UTC) - timedelta(hours=25)).strftime("%Y-%m-%d %H:%M:%S")
    _due(attempts=8, first_at=old)
    stack, _ = _with_api({"/device/add": NOT_YET, "/device/status": UNKNOWN})
    _enter(stack)
    try:
        _run(main._retry_device_links)
        (row,) = _run(database.list_pending_device_links)
        alerts = _run(database.list_alerts)
    finally:
        _exit(stack)
    assert row["gave_up"] == 1
    notice = [a for a in alerts if a.get("subject") == "proxyrack"]
    assert notice and UUID in notice[0]["message"] and "Add device" in notice[0]["message"]


def test_a_given_up_device_is_not_tried_again(db):
    old = (datetime.now(UTC) - timedelta(hours=25)).strftime("%Y-%m-%d %H:%M:%S")
    _due(attempts=8, first_at=old)
    stack, calls = _with_api({"/device/add": NOT_YET, "/device/status": UNKNOWN})
    _enter(stack)
    try:
        _run(main._retry_device_links)
        _run(main._retry_device_links)
    finally:
        _exit(stack)
    assert calls.count("/device/add") == 1


def test_a_device_that_no_longer_runs_is_dropped_without_asking(db):
    _due()
    stack, calls = _with_api({"/device/add": ADDED}, deployed=("CD" * 32,))
    _enter(stack)
    try:
        _run(main._retry_device_links)
        rows = _run(database.list_pending_device_links)
    finally:
        _exit(stack)
    assert calls == [] and rows == []


def test_a_proxied_copys_derived_id_counts_as_still_running(db):
    original = "CD" * 32
    copy_id = proxies.copy_device_id(original, 1)
    _due(device_id=copy_id)
    stack, calls = _with_api(
        {"/device/add": ADDED}, deployed=(original,), copies=[{"slug": "proxyrack", "proxy_id": 1}]
    )
    _enter(stack)
    try:
        _run(main._retry_device_links)
    finally:
        _exit(stack)
    assert calls == ["/device/add"]


def test_the_retry_runs_on_the_scheduler():
    source = Path(main.__file__).read_text()
    assert '_retry_device_links,\n        "interval",\n        minutes=3,\n        id="retry_device_links"' in source


def test_a_redeploy_after_giving_up_gets_a_new_day_of_retries(db):
    old = (datetime.now(UTC) - timedelta(hours=25)).strftime("%Y-%m-%d %H:%M:%S")
    _due(attempts=8, first_at=old)
    stack, calls = _with_api({"/device/add": NOT_YET, "/device/status": UNKNOWN})
    _enter(stack)
    try:
        _run(main._retry_device_links)  # gives up
        _run(lambda: main._register_device("proxyrack", UUID, {"DEVICE_NAME": "box"}))  # the redeploy
        (row,) = _run(database.list_pending_device_links)
        _run(main._retry_device_links)  # not due yet: the new window waits its first six minutes
    finally:
        _exit(stack)
    assert row["gave_up"] == 0 and row["attempts"] == 0 and row["first_at"] > old
    assert row["next_at"] > datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    assert calls.count("/device/add") == 2  # the give-up try and the redeploy, nothing more
