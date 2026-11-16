import contextlib
import gc
import os
import sqlite3
import tempfile
import threading
import traceback
import warnings
from pathlib import Path

import pytest

# Point the suite at a writable data directory BEFORE any app module is imported:
# app.database resolves DB_PATH and the encryption-key path once, at import time.
# Without this the suite runs against the default /data, which on a developer Mac
# is a read-only filesystem and in CI is not creatable — so the encryption key
# could not be persisted and the app now (correctly) refuses to start.
os.environ.setdefault("CASHPILOT_DATA_DIR", tempfile.mkdtemp(prefix="cashpilot-tests-"))
# The suite's deploys run against mocked Docker clients that have no idea of
# networks. Isolation is a default the worker resolves through Docker
# (app/lan_fence.py), so every test starts with it off, which is the old
# default-bridge behaviour; tests/test_lan_fence.py sets each mode on purpose.
os.environ.setdefault("CASHPILOT_ISOLATION", "off")

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def services_dir():
    return PROJECT_ROOT / "services"


@pytest.fixture
def schema_path():
    return PROJECT_ROOT / "services" / "_schema.yml"


@pytest.fixture(autouse=True)
def _no_custom_images(request):
    """No worker runs a custom image, unless a test asks for the real lookup.

    The deployed-services and service-detail routes read every worker's
    recorded image choice from the database. Most route tests mock the database
    call by call and never create its tables, so without this each of them
    would fail on a lookup it does not care about. Tests marked
    ``real_custom_images`` get the real function.
    """
    if request.node.get_closest_marker("real_custom_images"):
        yield
        return
    from unittest.mock import AsyncMock, patch

    with patch("app.database.get_custom_images", new_callable=AsyncMock, return_value={}):
        yield


@pytest.fixture(autouse=True)
def _gated_services_run_in_any_mode(request):
    """A fence-gated service (Mysterium) deploys in the suite's ``off`` mode.

    The worker refuses one outside ``on`` and ``operator`` (lan_fence.mode_problem),
    and the suite runs with isolation off (above), where tests about volumes,
    mounts or capabilities deploy Mysterium as their example. Tests marked
    ``real_gated_mode`` get the real rule; tests/test_mysterium_fenced.py is.
    """
    if request.node.get_closest_marker("real_gated_mode"):
        yield
        return
    from unittest.mock import patch

    with patch("app.lan_fence.mode_problem", return_value=None):
        yield


@pytest.fixture(autouse=True)
def _no_state_backups(request):
    """No backup is confirmed, unless a test asks for the real table.

    The payout registry reads the confirmed backups. Its tests mock the
    database call by call, and a real read here would open a connection on a
    loop ``asyncio.run`` then closes, which hangs the suite at teardown on
    Linux. Tests marked ``real_state_backups`` get the real function.
    """
    if request.node.get_closest_marker("real_state_backups"):
        yield
        return
    from unittest.mock import AsyncMock, patch

    with patch("app.database.get_state_backups", new_callable=AsyncMock, return_value={}):
        yield


@pytest.fixture(autouse=True)
def _seed_fiat_rates():
    """Give every test the exchange rates a RUNNING CashPilot always has.

    ``exchange_rates.refresh()`` populates these at startup and every 15
    minutes, so in production a fiat rate is available essentially always. The
    test process never calls it, so ``_fiat_rates`` was empty everywhere.

    That mattered once ``/api/earnings/net`` started converting the tariff into
    USD before subtracting it from a USD gross: ten tests configure a EUR tariff
    and expect a cost, and with no rate the endpoint correctly refuses to
    produce a net — so they failed for a reason that had nothing to do with what
    they were testing.

    Seeded rather than mocked per-test, because "a rate exists" is the normal
    state of the system. Tests that need the no-rate path clear this themselves.
    """
    from app import exchange_rates

    saved = dict(exchange_rates._fiat_rates)
    exchange_rates._fiat_rates.update({"EUR": 0.92, "GBP": 0.79, "USD": 1.0})
    try:
        yield
    finally:
        exchange_rates._fiat_rates.clear()
        exchange_rates._fiat_rates.update(saved)


@pytest.fixture(autouse=True)
def _fresh_once_per_change_logs(monkeypatch):
    """The unpriced and blind-worker warnings remember what they last said.

    That memory is process-wide, so without this a test asserting the warning
    passes or fails depending on which test ran before it.
    """
    from app import database, main

    monkeypatch.setattr(database, "_unpriced_logged", {})
    monkeypatch.setattr(main, "_blind_workers_logged", None)


@pytest.fixture(autouse=True)
def _reset_shared_db():
    """Drain the per-loop shared SQLite connections after every test.

    ``database._get_db()`` caches one connection per event loop. Tests run via
    ``asyncio.run(...)`` create a fresh loop each time and patch ``DB_PATH`` at
    a tmp location, so a stale cached connection (pointing at a previous tmp DB
    or a closed loop) must never leak across tests. After each test we close
    any surviving connections and clear the cache so the next test binds fresh.

    Closed on their own threads, with no event loop: see ``close_shared_conns``.
    A worker thread can die at any moment of the test, the drain included, so
    the hook that frees its handle covers all of it.
    """
    pytest_hook = threading.excepthook
    threading.excepthook = hook_that_frees_dead_aiosqlite_handles(pytest_hook)
    try:
        yield

        from app import database

        database._forget_health_scores()
        conns = list(database._shared_conns.values())
        database._shared_conns.clear()
        close_shared_conns(conns)
    finally:
        threading.excepthook = pytest_hook


def hook_that_frees_dead_aiosqlite_handles(outer):
    """Report a dead aiosqlite worker as ``outer`` does, then clear its frames.

    pytest keeps each thread's exception until its test phase ends, and the
    traceback reaches the worker's frame, whose locals still hold the query it
    ran and the cursor it got. Both hold the sqlite handle, so a thread that
    dies in teardown, before or during the drain, keeps the handle and its
    lock past the drain. The report is already written when ``outer``
    returns; only the dead frames' locals go.
    """
    from aiosqlite.core import _connection_worker_thread

    def hook(args) -> None:
        try:
            outer(args)
        finally:
            if _died_in(args.exc_value, _connection_worker_thread.__code__):
                _clear_frames_of_chain(args.exc_value)

    hook.frees_dead_aiosqlite_handles = True
    return hook


def _chain(exc):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def _died_in(exc, code) -> bool:
    for e in _chain(exc):
        tb = e.__traceback__
        while tb is not None:
            if tb.tb_frame.f_code is code:
                return True
            tb = tb.tb_next
    return False


def _clear_frames_of_chain(exc) -> None:
    # The worker caught the first failure and failed again handing it over, so
    # the cursor also sits in the first exception's own frames.
    for e in _chain(exc):
        traceback.clear_frames(e.__traceback__)


def close_shared_conns(conns, wait: float = 5.0) -> None:
    """Close each aiosqlite connection on its own thread, and never wait forever.

    The trap this avoids hung CI for six hours a run (2026-11-14). A test that
    calls a route under ``asyncio.run`` leaves a fire-and-forget task behind
    (``_deploy`` spawns ``_run_collection``). ``asyncio.run`` cancels it while
    its query is still on the connection's thread, then closes the loop. The
    query finishes, aiosqlite hands the answer to that closed loop, gets
    "Event loop is closed", and its worker thread dies. The connection still
    looks open, so ``await conn.close()`` on a new loop queued work no thread
    would ever run and waited for it forever. A timeout around it does not
    help: aiosqlite's own cleanup awaits a second future from the same dead
    thread.

    ``stop()`` closes the sqlite connection on that thread and needs no loop,
    and ``join`` with a limit returns at once when the thread is already gone.

    A dead thread never runs that close, so the sqlite handle stays open, and a
    write cancelled before its commit keeps its lock: the next test to write
    that file gets "database is locked". Python refuses ``close()`` and
    ``rollback()`` from any thread but the one that opened the handle, and that
    one is gone. Its finaliser has no such check, and closing the handle rolls
    the open write back, so drop the last reference and collect it.

    sqlite3 connections take no weak reference, so the drain then looks for
    the handle among the live objects. One still alive keeps its lock, and the
    drain fails here rather than leave a later test "database is locked" with
    no clue why. That look walks every live object, which is fine: a thread
    dies this way rarely.
    """
    held = []
    for conn in conns:
        conn.stop()
        conn._thread.join(timeout=wait)
        if not conn._thread.is_alive() and conn._connection is not None:
            handle_id = id(conn._connection)
            conn._connection = None
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ResourceWarning)  # unclosed on purpose
                gc.collect()
            live = gc.get_objects()
            for obj in live:
                if id(obj) == handle_id and isinstance(obj, sqlite3.Connection):
                    holders = {type(r).__name__ for r in gc.get_referrers(obj) if r is not live}
                    held.append(f"{conn!r}, referred to by {sorted(holders)}")
            del live
    if held:
        raise AssertionError(
            "a dead aiosqlite thread's sqlite handle was not freed, so its lock stays; "
            "something still holds it: " + "; ".join(held)
        )


@pytest.fixture(autouse=True)
def _reset_login_attempts():
    """Clear the in-process login rate-limit bucket before every test.

    ``app.main._login_attempts`` is a module-level dict keyed by client host that
    persists for the whole test process, and TestClient's host is a constant
    ("testclient"), so failed-login attempts from one test would otherwise leak
    into later tests that hit /login — an order-dependent landmine (and the reason
    a real rate-limit test couldn't be added safely before). Start each test with
    an empty bucket.
    """
    with contextlib.suppress(Exception):
        from app import main

        main._login_attempts.clear()
    yield


@pytest.fixture(autouse=True)
def _reset_setup_token():
    """Clear the first-run setup-token module global before every test.

    ``app.setup_token._active`` persists for the whole process; a test that runs
    lifespan on a fresh DB (or exercises the token directly) would otherwise leak
    an active token into later tests, making unrelated /register tests 403.
    """
    with contextlib.suppress(Exception):
        from app import setup_token

        setup_token.clear()
    yield


@pytest.fixture(autouse=True)
def _reset_process_wide_caches():
    """Clear the remaining module-level state that outlives a single test.

    These are process-wide and were each being reset by hand at the top of the
    tests that happened to know about them — `_last_attempt` in three separate
    places in test_collector_contracts.py, `_net_baselines` in two more. That
    works only for as long as every future test author remembers the
    boilerplate, and the failure when someone forgets is an order-dependent
    flake in a DIFFERENT file, which is about the most expensive kind of test
    bug to track down.

    `_last_attempt` in particular is a live trap: it holds a real cooldown, so
    a test that triggers a credential test leaves the next one rate-limited.
    """
    for module_name, attr in (
        ("app.main", "_net_baselines"),
        ("app.main", "_worker_online_streak"),
        ("app.main", "_worker_last_offline_push"),
        ("app.credential_test", "_last_attempt"),
    ):
        with contextlib.suppress(Exception):
            import importlib

            getattr(importlib.import_module(module_name), attr).clear()
    with contextlib.suppress(Exception):
        from app import orchestrator

        orchestrator._status_cache = []
        orchestrator._status_cache_time = 0.0
    with contextlib.suppress(Exception):
        # test_worker_keys drives _send_heartbeat through 401/ConnectError paths
        # and leaves the heartbeat-failure counter nonzero; with CASHPILOT_UI_URL
        # exported (any dev pointed at a real fleet) that turns /api/health tests
        # in OTHER files into 503s.
        from app import worker_api

        worker_api._consecutive_heartbeat_failures = 0
        worker_api._link_hint_logged = False
        # A stale stamp reads as "not reporting in": without this reset, any
        # pytest process older than the staleness window would 503 every
        # /api/health test that patches UI_URL.
        worker_api._last_heartbeat_ok = worker_api.time.monotonic()
    yield


@pytest.fixture(autouse=True)
def _tunnel_replacement_in_place(request):
    """The heartbeat's tunnel replacement runs in place, not in its own thread.

    proxy_tunnel.status() starts it in the background, so a slow try never holds
    the heartbeat up. A thread a test leaves running would outlive the patches
    that test made (its fake Docker, its markers) and reach whatever the next
    test patched, or a real daemon. Tests marked ``real_background_replacement``
    get the real thread.
    """
    if request.node.get_closest_marker("real_background_replacement"):
        yield
        return
    try:
        from app import proxy_tunnel
    except Exception:  # noqa: BLE001 - a suite run without docker-py never reaches it
        yield
        return
    from unittest.mock import patch

    with patch.object(proxy_tunnel, "_in_background", lambda work: work()):
        yield


@pytest.fixture(scope="session")
def _real_catalog_slugs():
    from app import catalog

    return {s["slug"] for s in catalog.load_services()}


@pytest.fixture(autouse=True)
def _unpollute_catalog(_real_catalog_slugs):
    """Drop the catalog cache when a test leaves a fixture catalog behind.

    Several tests point ``catalog.SERVICES_DIR`` at a tmp directory and then
    call ``load_services()`` / ``get_service()``, which replaces the
    module-level caches for the rest of the session. Anything that later looks
    up a real slug then silently finds nothing - so a guard keyed on the catalog
    stops guarding without a single test failing.

    Clearing is O(1) and only happens when the cache genuinely does not match
    services/, so the common case pays nothing and the next real lookup
    lazy-loads from disk.
    """
    yield

    from app import catalog

    if catalog._by_slug and set(catalog._by_slug) != _real_catalog_slugs:
        catalog._services = []
        catalog._by_slug = {}


# ---------------------------------------------------------------------------
# CashPilot-ixjx: refuse to run against a contaminated working tree.
#
# The repos on this machine are two-way rsynced against a hub that keeps files
# the local side deleted (no --delete, by design). A branch checkout removes a
# file; the next sync copies it straight back as an UNTRACKED stray. The tree
# then holds a mixture of two branches.
#
# THE FAILING CASE IS THE LUCKY ONE. On 2026-08-06 four files from two feature
# branches reappeared on a third, and five tests failed loudly. But an EARLIER
# run on that same branch had reported 4096 PASSED while silently including
# another branch's tests -- a green suite measuring the wrong tree, which
# nothing announces and nobody double-checks.
#
# So: a stray is any untracked file that HAS COMMIT HISTORY somewhere. A file
# nobody ever committed is ordinary new work and is ignored.
# ---------------------------------------------------------------------------

#: Only these affect what the suite measures. An untracked note or scratch file
#: is nobody's business.
_RESULT_BEARING = ("app/", "tests/", "scripts/", "services/")


def _git(*args: str) -> str | None:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), *args],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def find_stray_files() -> list[str]:
    """Untracked, result-bearing files that were committed somewhere else.

    Returns [] when git is unavailable or this is not a repository — the guard
    must never be the reason a suite cannot run, only a reason it refuses to
    lie about what it measured.
    """
    status = _git("status", "--porcelain")
    if status is None:
        return []

    strays = []
    for line in status.splitlines():
        if not line.startswith("?? "):
            continue
        path = line[3:].strip().strip('"')
        if not path.startswith(_RESULT_BEARING):
            continue
        # Commit history anywhere means this file belongs to some branch, so its
        # presence here as untracked is resurrection rather than new work.
        history = _git("rev-list", "--all", "--max-count=1", "--", path)
        if history and history.strip():
            strays.append(path)
    return strays


def pytest_sessionstart(session):  # noqa: ARG001 - pytest hook signature
    if os.environ.get("CASHPILOT_ALLOW_STRAY_FILES"):
        return
    strays = find_stray_files()
    if not strays:
        return
    listing = "\n".join(f"  {p}" for p in strays)
    raise pytest.UsageError(
        "Refusing to run: the working tree holds untracked files that are committed on\n"
        "another branch. The suite would measure a mixture of two branches, and the\n"
        "dangerous outcome is not a failure but a PASS that means nothing.\n\n"
        f"{listing}\n\n"
        "These are almost certainly cmux-sync resurrecting files a branch checkout\n"
        "removed (CashPilot-ixjx). Verify each is identical to its committed version\n"
        "before removing it:\n"
        "  git show <branch>:<path> | diff - <path>\n\n"
        "Set CASHPILOT_ALLOW_STRAY_FILES=1 to run anyway."
    )
