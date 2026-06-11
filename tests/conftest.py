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
