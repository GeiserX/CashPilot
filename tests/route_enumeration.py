"""One way to enumerate the app's routes, for every test that needs to.

``app.routes`` is NOT a complete enumeration. Under Starlette 1.3 — which CI
installs, because requirements.txt pins only ``fastapi>=0.136.1`` —
``include_router`` stops adding its routes there. Measured: re-including a
6-route ``APIRouter`` grew ``app.routes`` by ONE, and ``/login`` never appeared
at all. Routing itself is unaffected; every one of those paths still serves.

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

    # Starlette 1.3 puts a pathless `_IncludedRouter` placeholder in app.routes
    # for each include_router call — that is the "+1 per include" measured when
    # this was diagnosed. It is not a route anyone can call, and leaving it in
    # makes every consumer filter it out again.
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
