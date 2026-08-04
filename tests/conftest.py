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
