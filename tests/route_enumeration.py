"""One way to enumerate the app's routes, for every test that needs to.

``app.routes`` is NOT a complete enumeration on every supported version.
FastAPI 0.141.1 drops routes from ``app.routes``. Measured by holding
Starlette at 1.3.1 and moving FastAPI alone: on 0.136.1 the app reports all 76
routes including /login; on 0.141.1 it reports 62 and /login is absent, with
``include_router`` leaving only a pathless placeholder behind. Routing itself is
unaffected — every one of those paths still serves.

It surfaced because requirements.txt pinned only ``fastapi>=0.136.1`` while the
lockfile pins 0.136.1, so CI resolved a version nobody developed against
(CashPilot-de1). CI now installs from the lock, which closes that gap — this
helper is what keeps a future FastAPI bump from silently shrinking a sweep
again.

Anything that ENUMERATES routes therefore sees a subset, and the failure is
silent in the worst possible direction:

* a sweep that asserts something about every route quietly stops covering the
  ones it cannot see, while still reporting a large number and passing;
* a NEGATIVE assertion — "no route serves /docs" — becomes trivially true the
  moment the enumeration is incomplete.

Three test modules independently walked ``app.routes``. The first was caught
because a PUBLIC-list staleness check failed on CI and nowhere else
(CashPilot-zfd); the other two would have shrunk in silence (CashPilot-33h).
Hence one helper rather than three copies of the workaround.
"""

from __future__ import annotations

from typing import Any


def all_routes() -> list[Any]:
    """Every route the app serves, on any supported Starlette version.

    The app's own routes, unioned with the routes of each ``APIRouter`` reached
    through ``app.main``. Deduplicated on (path, methods), so a version where
    ``include_router`` still populates ``app.routes`` yields the same list.
    """
    from fastapi import APIRouter

    from app import main

    # FastAPI 0.141.1 puts a pathless `_IncludedRouter` placeholder in
    # app.routes for each include_router call — the "+1 per include" measured
    # when this was diagnosed. It is not a route anyone can call, and leaving it
    # in makes every consumer filter it out again.
    routes = [r for r in main.app.routes if getattr(r, "path", "")]
    seen = {(getattr(r, "path", ""), frozenset(getattr(r, "methods", None) or ())) for r in routes}
    for value in vars(main).values():
        # main binds them as MODULES (`from app.routers import auth as
        # auth_router`), so the APIRouter is one attribute further in.
        candidate = value if isinstance(value, APIRouter) else getattr(value, "router", None)
        if isinstance(candidate, APIRouter):
            for route in candidate.routes:
                key = (getattr(route, "path", ""), frozenset(getattr(route, "methods", None) or ()))
                if key not in seen:
                    seen.add(key)
                    routes.append(route)
    return routes


def all_paths() -> set[str]:
    """Every path the app serves. For negative assertions, which need this most.

    "No route serves /docs" is only meaningful if the set being searched is
    complete: an incomplete one makes the claim true by omission.
    """
    return {getattr(r, "path", "") for r in all_routes()}
