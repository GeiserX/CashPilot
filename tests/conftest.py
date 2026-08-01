import asyncio
import contextlib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def services_dir():
    return PROJECT_ROOT / "services"


@pytest.fixture
def schema_path():
    return PROJECT_ROOT / "services" / "_schema.yml"


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
