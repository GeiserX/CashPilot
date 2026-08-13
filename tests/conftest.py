import asyncio
import contextlib
import os
import tempfile
from pathlib import Path

import pytest

# Point the suite at a writable data directory BEFORE any app module is imported:
# app.database resolves DB_PATH and the encryption-key path once, at import time.
# Without this the suite runs against the default /data, which on a developer Mac
# is a read-only filesystem and in CI is not creatable — so the encryption key
# could not be persisted and the app now (correctly) refuses to start.
os.environ.setdefault("CASHPILOT_DATA_DIR", tempfile.mkdtemp(prefix="cashpilot-tests-"))

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def services_dir():
    return PROJECT_ROOT / "services"


@pytest.fixture
def schema_path():
    return PROJECT_ROOT / "services" / "_schema.yml"


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
def _reset_shared_db():
    """Drain the per-loop shared SQLite connections after every test.

    ``database._get_db()`` caches one connection per event loop. Tests run via
    ``asyncio.run(...)`` create a fresh loop each time and patch ``DB_PATH`` at
    a tmp location, so a stale cached connection (pointing at a previous tmp DB
    or a closed loop) must never leak across tests. After each test we close
    any surviving connections and clear the cache so the next test binds fresh.
    """
    yield

    from app import database

    conns = list(database._shared_conns.values())
    database._shared_conns.clear()
    if not conns:
        return

    async def _drain():
        for conn in conns:
            with contextlib.suppress(Exception):
                await conn.close()

    # No usable loop (e.g. one is already running) — best-effort cleanup.
    with contextlib.suppress(RuntimeError):
        asyncio.run(_drain())


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
