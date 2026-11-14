"""Removing a proxied copy can never leave the dashboard out of step with the worker.

Seen on a real box: the worker removed the copy and its tunnel, but took longer
than the dashboard's 30 s, so the dashboard answered 504 and kept the copy's
record. That record then blocked deleting the proxy, and kept the copy's
ProxyRack device in the registration retries. Now the removal is recorded as
pending, every heartbeat from the worker asks again until it confirms, and the
copy's pending device link goes with its record.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app import database, main, proxies

UUID = "AB" * 32
COPY_UUID = proxies.copy_device_id(UUID, 1)
TIMEOUT = HTTPException(status_code=504, detail="The worker did not answer within 90 s.")
UNREACHABLE = HTTPException(status_code=503, detail="Worker communication failed")
REFUSED = HTTPException(status_code=409, detail="Docker did not remove cashpilot-proxyrack-p1")
REMOVED = {"status": "removed", "containers": ["cashpilot-proxyrack-p1", "cashpilot-tunnel-proxyrack-p1"]}


class _Req:
    def __init__(self, body):
        self._body = body
        self.url = MagicMock(path="/api/proxies")

    async def json(self):
        return self._body


@pytest.fixture
def db(tmp_path):
    with (
        patch.object(database, "DB_DIR", tmp_path),
        patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"),
    ):
        yield tmp_path


@pytest.fixture(autouse=True)
def _no_removals_in_flight():
    # A test that closes a spawned coroutine unrun skips its finally, which
    # would leave the copy marked as in flight for the next test.
    main._copy_removals_running.clear()
    yield
    main._copy_removals_running.clear()


def _run(fn):
    async def go():
        await database.init_db()
        try:
            return await fn()
        finally:
            await database.close_shared()

    return asyncio.run(go())


async def _proxy_with_copy(worker_id=7, slug="proxyrack"):
    created = await main.api_create_proxy(_Req({"name": "P", "kind": "socks5", "host": "h.example", "port": 1}), {})
    assert created["id"] == 1, "COPY_UUID is derived for proxy 1"
    await database.save_proxied_copy(created["id"], worker_id, slug)
    return created["id"]


def _worker(call, spawned=None):
    """Patches for a worker that exists and answers ``call``; spawned tasks are kept to await."""
    spawned = spawned if spawned is not None else []
    return (
        patch.object(main.database, "get_worker", new_callable=AsyncMock, return_value={"id": 7, "name": "box"}),
        patch.object(main, "_proxy_to_worker", call),
        patch.object(main.database, "get_deployed_env_values", new_callable=AsyncMock, return_value={UUID}),
        patch.object(main, "_spawn", side_effect=lambda coro: spawned.append(coro)),
    )


async def _copies():
    return [(c["worker_id"], c["slug"], bool(c.get("removing_since"))) for c in await database.list_proxied_copies()]


class TestTheWorkerConfirms:
    def test_a_confirmed_removal_drops_the_record(self, db):
        call = AsyncMock(return_value=REMOVED)

        async def go():
            pid = await _proxy_with_copy()
            a, b, c, d = _worker(call)
            with a, b, c, d:
                out = await main.api_remove_proxied_copy(pid, 7, "proxyrack", {})
                await main.api_delete_proxy(pid, {})
            return out, await _copies(), await database.list_proxies()

        out, copies, left = _run(go)
        assert out == REMOVED and copies == [] and left == []
        assert call.call_args.kwargs["timeout"] == main.COPY_REMOVE_TIMEOUT

    def test_a_refusal_from_the_worker_keeps_the_copy_listed_as_it_was(self, db):
        call = AsyncMock(side_effect=REFUSED)

        async def go():
            pid = await _proxy_with_copy()
            a, b, c, d = _worker(call)
            with a, b, c, d, pytest.raises(HTTPException) as err:
                await main.api_remove_proxied_copy(pid, 7, "proxyrack", {})
            return err.value.status_code, await _copies()

        status, copies = _run(go)
        # The worker said no: the copy still exists, so it is not shown as removing.
        assert status == 409 and copies == [(7, "proxyrack", False)]


class TestASlowWorker:
    @pytest.mark.parametrize("failure", [TIMEOUT, UNREACHABLE], ids=["timeout", "unreachable"])
    def test_the_removal_is_pending_not_an_error(self, db, failure):
        call = AsyncMock(side_effect=failure)

        async def go():
            pid = await _proxy_with_copy()
            a, b, c, d = _worker(call)
            with a, b, c, d:
                out = await main.api_remove_proxied_copy(pid, 7, "proxyrack", {})
            with patch.object(main.database, "list_workers", new_callable=AsyncMock, return_value=[]):
                view = (await main.api_list_proxies(MagicMock(), {}))["proxies"][0]
            return out, await _copies(), view

        out, copies, view = _run(go)
        assert isinstance(out, JSONResponse) and out.status_code == 202
        assert b'"status":"removing"' in out.body
        assert copies == [(7, "proxyrack", True)]
        assert view["copies"] == [{"worker_id": 7, "slug": "proxyrack", "stopped_by_cap": False, "removing": True}]

    def test_the_proxy_says_its_copies_are_still_being_removed(self, db):
        async def go():
            pid = await _proxy_with_copy()
            a, b, c, d = _worker(AsyncMock(side_effect=TIMEOUT))
            with a, b, c, d:
                await main.api_remove_proxied_copy(pid, 7, "proxyrack", {})
            with pytest.raises(HTTPException) as err:
                await main.api_delete_proxy(pid, {})
            return err.value

        err = _run(go)
        assert err.status_code == 409 and "still being removed" in err.detail

    def test_the_next_heartbeat_finishes_it_and_frees_the_proxy(self, db):
        spawned: list = []

        async def go():
            pid = await _proxy_with_copy()
            a, b, c, d = _worker(AsyncMock(side_effect=TIMEOUT), spawned)
            with a, b, c, d:
                await main.api_remove_proxied_copy(pid, 7, "proxyrack", {})
            confirm = AsyncMock(return_value={"status": "removed", "containers": []})
            a, b, c, d = _worker(confirm, spawned)
            with a, b, c, d:
                await main._queue_copy_removals(7)
                assert len(spawned) == 1
                await spawned.pop()
                await main.api_delete_proxy(pid, {})
            return confirm.call_args, await _copies(), await database.list_proxies(), main._copy_removals_running

        call, copies, left, running = _run(go)
        assert call.args[:3] == (7, "DELETE", "/api/proxied/proxyrack/1")
        assert copies == [] and left == [] and running == set()

    def test_another_worker_heartbeat_does_not_touch_it(self, db):
        spawned: list = []

        async def go():
            pid = await _proxy_with_copy()
            a, b, c, d = _worker(AsyncMock(side_effect=TIMEOUT), spawned)
            with a, b, c, d:
                await main.api_remove_proxied_copy(pid, 7, "proxyrack", {})
                await main._queue_copy_removals(8)
            return spawned, await _copies()

        spawned_, copies = _run(go)
        assert spawned_ == [] and copies == [(7, "proxyrack", True)]

    def test_a_still_slow_worker_keeps_it_pending_for_the_next_heartbeat(self, db):
        spawned: list = []

        async def go():
            pid = await _proxy_with_copy()
            a, b, c, d = _worker(AsyncMock(side_effect=TIMEOUT), spawned)
            with a, b, c, d:
                await main.api_remove_proxied_copy(pid, 7, "proxyrack", {})
                await main._queue_copy_removals(7)
                await spawned.pop()
                again = await _copies()
                await main._queue_copy_removals(7)
            for coro in spawned:
                coro.close()
            return again, len(spawned)

        again, queued = _run(go)
        assert again == [(7, "proxyrack", True)] and queued == 1

    def test_a_heartbeat_does_not_queue_a_second_request_while_one_runs(self, db):
        spawned: list = []

        async def go():
            pid = await _proxy_with_copy()
            a, b, c, d = _worker(AsyncMock(side_effect=TIMEOUT), spawned)
            with a, b, c, d:
                await main.api_remove_proxied_copy(pid, 7, "proxyrack", {})
                await main._queue_copy_removals(7)
                await main._queue_copy_removals(7)
            count = len(spawned)
            for coro in spawned:
                coro.close()
            return count

        assert _run(go) == 1

    def test_one_copys_failure_does_not_strand_the_next(self, db):
        spawned: list = []

        async def go():
            pid = await _proxy_with_copy()
            await database.save_proxied_copy(pid, 7, "honeygain")
            a, b, c, d = _worker(AsyncMock(side_effect=TIMEOUT), spawned)
            with a, b, c, d:
                await main.api_remove_proxied_copy(pid, 7, "honeygain", {})
                await main.api_remove_proxied_copy(pid, 7, "proxyrack", {})
            real = main._finish_copy_removal

            async def finish(proxy_id, worker_id, slug):
                if slug == "honeygain":
                    raise RuntimeError("database is locked")
                await real(proxy_id, worker_id, slug)

            a, b, c, d = _worker(AsyncMock(return_value=REMOVED), spawned)
            with a, b, c, d, patch.object(main, "_finish_copy_removal", finish):
                await main._queue_copy_removals(7)
                await spawned.pop()
            return await _copies(), set(main._copy_removals_running)

        copies, running = _run(go)
        # honeygain failed and waits for the next heartbeat; proxyrack still finished.
        assert copies == [(7, "honeygain", True)] and running == set()

    def test_a_refusal_on_the_retry_lists_the_copy_again(self, db):
        spawned: list = []

        async def go():
            pid = await _proxy_with_copy()
            a, b, c, d = _worker(AsyncMock(side_effect=TIMEOUT), spawned)
            with a, b, c, d:
                await main.api_remove_proxied_copy(pid, 7, "proxyrack", {})
            a, b, c, d = _worker(AsyncMock(side_effect=REFUSED), spawned)
            with a, b, c, d:
                await main._queue_copy_removals(7)
                await spawned.pop()
            return await _copies()

        assert _run(go) == [(7, "proxyrack", False)]

    def test_the_heartbeat_route_resumes_removals(self):
        # The heartbeat handler is what resumes them; a handler that stops calling it fails here.
        assert "_queue_copy_removals" in main.api_worker_heartbeat.__code__.co_names

    def test_a_copy_being_removed_is_not_restarted_by_the_cap(self, db):
        start = AsyncMock()

        async def go():
            pid = await _proxy_with_copy()
            await database.set_proxied_copy_capped(pid, 7, "proxyrack", True)
            await database.set_proxied_copy_removing(pid, 7, "proxyrack", True)
            proxy = await database.get_proxy(pid)
            with patch.object(main, "_start_proxied_copy", start):
                return await main._release_capped_copies(proxy)

        assert _run(go) == [] and start.await_count == 0

    def test_adding_the_copy_again_clears_the_pending_removal(self, db):
        async def go():
            pid = await _proxy_with_copy()
            await database.set_proxied_copy_removing(pid, 7, "proxyrack", True)
            await database.save_proxied_copy(pid, 7, "proxyrack")
            return await _copies()

        assert _run(go) == [(7, "proxyrack", False)]

    def test_a_copy_left_on_the_old_device_name_stays_marked_until_renamed_or_added_again(self, db):
        async def go():
            pid = await _proxy_with_copy()
            marks = []
            for step in (
                lambda: database.set_proxied_copy_rename_pending(pid, 7, "proxyrack", True),
                lambda: database.set_proxied_copy_rename_pending(pid, 7, "proxyrack", False),
                lambda: database.set_proxied_copy_rename_pending(pid, 7, "proxyrack", True),
                lambda: database.save_proxied_copy(pid, 7, "proxyrack"),
            ):
                await step()
                marks.append([c["rename_pending"] for c in await database.list_proxied_copies()])
            return marks

        assert _run(go) == [[1], [0], [1], [0]]


class TestPendingDeviceLinks:
    async def _links(self):
        return sorted((r["slug"], r["device_id"]) for r in await database.list_pending_device_links())

    async def _seed_links(self):
        await database.save_pending_device_link("proxyrack", COPY_UUID, "copy", "2000-01-01 00:00:00")
        await database.save_pending_device_link("proxyrack", UUID, "original", "2000-01-01 00:00:00")

    def test_removing_a_copy_drops_its_link_and_keeps_the_original(self, db):
        async def go():
            pid = await _proxy_with_copy()
            await self._seed_links()
            a, b, c, d = _worker(AsyncMock(return_value=REMOVED))
            with a, b, c, d:
                await main.api_remove_proxied_copy(pid, 7, "proxyrack", {})
            return await self._links()

        assert _run(go) == [("proxyrack", UUID)]

    def test_a_pending_removal_drops_the_link_only_when_the_worker_confirms(self, db):
        spawned: list = []

        async def go():
            pid = await _proxy_with_copy()
            await self._seed_links()
            a, b, c, d = _worker(AsyncMock(side_effect=TIMEOUT), spawned)
            with a, b, c, d:
                await main.api_remove_proxied_copy(pid, 7, "proxyrack", {})
            before = await self._links()
            a, b, c, d = _worker(AsyncMock(return_value=REMOVED), spawned)
            with a, b, c, d:
                await main._queue_copy_removals(7)
                await spawned.pop()
            return before, await self._links()

        before, after = _run(go)
        assert before == [("proxyrack", COPY_UUID), ("proxyrack", UUID)]
        assert after == [("proxyrack", UUID)]

    def test_a_copy_being_removed_is_not_a_device_to_register(self, db):
        async def go():
            pid = await _proxy_with_copy()
            with patch.object(main.database, "get_deployed_env_values", new_callable=AsyncMock, return_value={UUID}):
                running = await main._device_still_deployed("proxyrack", COPY_UUID)
                await database.set_proxied_copy_removing(pid, 7, "proxyrack", True)
                removing = await main._device_still_deployed("proxyrack", COPY_UUID)
                original = await main._device_still_deployed("proxyrack", UUID)
            return running, removing, original

        assert _run(go) == (True, False, True)

    def test_deleting_the_proxy_drops_its_copies_links(self, db):
        async def go():
            created = await main.api_create_proxy(_Req({"name": "P", "kind": "socks5", "host": "h", "port": 1}), {})
            await self._seed_links()
            with patch.object(main.database, "get_deployed_env_values", new_callable=AsyncMock, return_value={UUID}):
                await main.api_delete_proxy(created["id"], {})
            return await self._links()

        assert _run(go) == [("proxyrack", UUID)]

    def test_another_proxys_copy_keeps_its_link(self, db):
        other = proxies.copy_device_id(UUID, 2)

        async def go():
            pid = await _proxy_with_copy()
            await database.save_pending_device_link("proxyrack", other, "copy 2", "2000-01-01 00:00:00")
            a, b, c, d = _worker(AsyncMock(return_value=REMOVED))
            with a, b, c, d:
                await main.api_remove_proxied_copy(pid, 7, "proxyrack", {})
            return await self._links()

        assert _run(go) == [("proxyrack", other)]

    def test_a_copy_on_a_deleted_worker_drops_its_link_too(self, db):
        async def go():
            pid = await _proxy_with_copy(worker_id=99)
            await self._seed_links()
            with (
                patch.object(main.database, "get_worker", new_callable=AsyncMock, return_value=None),
                patch.object(main.database, "get_deployed_env_values", new_callable=AsyncMock, return_value={UUID}),
            ):
                await main.api_remove_proxied_copy(pid, 99, "proxyrack", {})
            return await self._links()

        assert _run(go) == [("proxyrack", UUID)]


def test_an_upgraded_database_gets_the_removal_column(db):
    async def go():
        import aiosqlite

        async with aiosqlite.connect(database.DB_PATH) as conn:
            await conn.execute(
                "CREATE TABLE proxied_copies (proxy_id INTEGER NOT NULL, worker_id INTEGER NOT NULL, "
                "slug TEXT NOT NULL, stopped_by_cap INTEGER NOT NULL DEFAULT 0, "
                "created_at TEXT NOT NULL DEFAULT (datetime('now')), PRIMARY KEY (proxy_id, worker_id, slug))"
            )
            await conn.execute("INSERT INTO proxied_copies (proxy_id, worker_id, slug) VALUES (1, 7, 'honeygain')")
            await conn.commit()
        await database.init_db()
        try:
            return await database.list_proxied_copies()
        finally:
            await database.close_shared()

    (row,) = asyncio.run(go())
    assert row["removing_since"] is None and row["slug"] == "honeygain"
    assert row["rename_pending"] == 0
