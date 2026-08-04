"""CashPilot-zfd: prove the auth guard for every route, not for a hand-written list.

``tests/test_audit_guards.py`` checks 14 handler names typed out by hand, and
``test_main_routes.py`` adds one more. There are 75 routes. The other 60 could
lose their guard in a refactor with the whole suite still green — verified by
deleting ``_require_auth_api`` from ``api_exchange_rates``, ``_require_writer``
from ``api_collect`` and ``_require_auth_api`` from ``api_earnings_flatlines``:
2300 passed each time, and an anonymous GET to /api/exchange-rates then served
the full rate table. Every endpoint test patches the guard away before calling
the handler, so nothing anywhere notices when the real one is gone.

The fix is to stop maintaining a list. This drives the real ASGI app with no
session and no key and requires every route to refuse, so a new endpoint is
covered the moment it is registered — the author has to come here and say why
if it is public.

Why the app is driven rather than its source inspected: a first attempt walked
the AST of each handler looking for a guard call and reported 17 unguarded
routes, all of them false. ``api_stop`` delegates to ``_svc_stop``, which
guards; the page routes redirect to /login when ``get_current_user`` returns
None. Both are real protection that a local read of the handler cannot see.
"""

from __future__ import annotations

import typing

import pytest

# The routes that are meant to be reachable with no credentials, and why. A new
# entry here is a deliberate decision to expose something publicly.
PUBLIC = {
    ("GET", "/login"): "the login form itself",
    ("POST", "/login"): "authenticates; rejects bad credentials on its own",
    ("GET", "/logout"): "clears the session — safe to hit anonymously",
    ("GET", "/register"): "the registration form; gated by setup token / invite",
    ("POST", "/register"): "creates the account; enforces its own setup-token gate",
    ("GET", "/onboarding"): "first-boot owner creation; refuses once a user exists",
}

SUBSTITUTIONS = {
    "slug": "honeygain",
    "user_id": "1",
    "worker_id": "1",
    "payout_id": "1",
    "alert_id": "1",
    "id": "1",
}


def _dummy(annotation):
    """A value that satisfies a field's type, so validation cannot mask the guard.

    Without this, eleven POST routes answered 422 to an empty body — FastAPI
    validates before the handler runs, so the guard was never reached and the
    422 proved nothing about it. A 422 is not a rejection.
    """
    origin = typing.get_origin(annotation)
    if origin is typing.Union or str(origin) == "<class 'types.UnionType'>":
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        return _dummy(args[0]) if args else "x"
    if annotation is int:
        return 1
    if annotation is float:
        return 1.0
    if annotation is bool:
        return False
    if origin in (list, set, tuple):
        return []
    if origin is dict or annotation is dict:
        return {}
    fields = getattr(annotation, "model_fields", None)
    if fields is not None:
        return {n: _dummy(f.annotation) for n, f in fields.items() if f.is_required()}
    return "x"


def _body_for(route):
    body_field = getattr(route, "body_field", None)
    if body_field is None:
        return None
    return _dummy(body_field.field_info.annotation)


def _routes():
    """Every route the app serves, on any supported Starlette version.

    ``app.routes`` is NOT a complete enumeration. Under Starlette 1.3 (which CI
    installs, because requirements.txt pins only ``fastapi>=0.136.1``)
    ``include_router`` stops adding its routes there: re-including a 6-route
    router grew ``app.routes`` by one, and /login never appeared at all. Routing
    itself is unaffected — every one of those paths still serves — but anything
    that ENUMERATES routes silently sees 65 of 76.

    That is exactly the failure this file exists to prevent, reappearing as a
    quiet under-count, and it is why the page routes are unioned back in from
    the routers themselves. test_the_page_routes_are_enumerated below fails if
    this ever stops working, rather than letting the sweep shrink in silence.
    """
    from fastapi import APIRouter

    from app import main

    routes = list(main.app.routes)
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


def _requests():
    """Every (method, path, body) the app exposes, with path params filled in."""
    out = []
    for route in _routes():
        path = getattr(route, "path", "")
        if not path or path.startswith("/static") or getattr(route, "endpoint", None) is None:
            continue
        url = path
        for name, value in SUBSTITUTIONS.items():
            url = url.replace("{" + name + "}", value)
        if "{" in url:
            pytest.fail(f"{path} has a path parameter with no substitution — add one to SUBSTITUTIONS")
        for method in sorted((route.methods or set()) - {"HEAD", "OPTIONS"}):
            out.append((method, path, url, _body_for(route)))
    return out


ALL_REQUESTS = _requests()


@pytest.fixture(scope="module")
def anonymous_client(tmp_path_factory):
    """The real app on a real database, with no session and no API key.

    A database is required, not incidental: /api/workers/heartbeat authenticates
    through _authenticate_worker_heartbeat, which reads the workers table, so
    without one it answers 500 and the guard goes unproven.

    The client is built directly rather than entered as a context manager, which
    would run the app's lifespan — that calls catalog.register_sighup(), and
    signal handlers cannot be installed off the main thread. None of the startup
    work matters here; the guards are per-request.
    """
    import asyncio

    from fastapi.testclient import TestClient

    from app import database, main
    from app.main import app

    tmp = tmp_path_factory.mktemp("anon")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(database, "DB_DIR", tmp)
        mp.setattr(database, "DB_PATH", tmp / "anon.db")
        # Without a fleet key configured, /api/workers/heartbeat answers 503
        # ("Fleet key not configured") before reaching its authentication. That
        # is a fail-closed refusal, not a guard, and accepting it here would
        # leave the one route a stolen shared key targets effectively untested.
        mp.setattr(main, "FLEET_API_KEY", "a-configured-fleet-key")
        asyncio.run(database.init_db())
        yield TestClient(app, raise_server_exceptions=False, follow_redirects=False)


class TestEveryRegisteredRouteRefusesAnAnonymousCaller:
    def test_there_are_far_more_routes_than_the_old_list_covered(self):
        """The premise of the bead: 14 names checked, 75 routes registered."""
        assert len(ALL_REQUESTS) > 60, f"only {len(ALL_REQUESTS)} routes enumerated — the sweep is not seeing the app"

    @pytest.mark.parametrize("path", ["/", "/login", "/logout", "/register", "/onboarding", "/setup", "/fleet"])
    def test_the_page_routes_are_enumerated(self, path):
        """The under-count guard, and it has already fired once.

        On Starlette 1.3 — what CI installs, since requirements.txt pins only
        fastapi>=0.136.1 — include_router stops adding its routes to app.routes.
        The whole HTML surface silently dropped out of this sweep while it still
        reported 65 routes and passed. A sweep that quietly stops sweeping is
        worse than the hand-written list it replaced, because it still looks
        thorough.
        """
        assert path in {p for _m, p, _u, _b in ALL_REQUESTS}, (
            f"{path} is served but not enumerated — the sweep is missing a whole router"
        )

    @pytest.mark.parametrize(
        ("method", "path", "url", "body"),
        ALL_REQUESTS,
        ids=[f"{m} {p}" for m, p, _u, _b in ALL_REQUESTS],
    )
    def test_it_rejects_or_redirects_to_login(self, anonymous_client, method, path, url, body):
        if (method, path) in PUBLIC:
            pytest.skip(f"public by design: {PUBLIC[(method, path)]}")
        resp = (
            anonymous_client.request(method, url, json=body)
            if body is not None
            else anonymous_client.request(method, url)
        )
        location = resp.headers.get("location", "")
        redirected_to_login = resp.status_code in (302, 303, 307) and (
            "/login" in location or "/onboarding" in location
        )
        assert resp.status_code in (401, 403) or redirected_to_login, (
            f"{method} {path} answered {resp.status_code} to a caller with no session and no key"
            + (f" (Location: {location})" if location else "")
        )

    def test_a_422_is_never_accepted_as_a_rejection(self, anonymous_client):
        """Validation runs before the handler, so it says nothing about auth.

        This is what made the first version of this file worthless: eleven POST
        routes answered 422 to an empty body and looked protected.
        """
        bad = [
            (m, p)
            for m, p, u, b in ALL_REQUESTS
            if (m, p) not in PUBLIC
            and (
                anonymous_client.request(m, u, json=b) if b is not None else anonymous_client.request(m, u)
            ).status_code
            == 422
        ]
        assert not bad, f"these never reached their guard, so nothing here proves it exists: {bad}"

    def test_the_public_list_only_names_routes_that_exist(self):
        """A renamed route must not silently keep its exemption."""
        registered = {(m, p) for m, p, _u, _b in ALL_REQUESTS}
        stale = [entry for entry in PUBLIC if entry not in registered]
        assert not stale, f"PUBLIC exempts routes that are no longer registered: {stale}"

    @pytest.mark.parametrize(
        "path",
        ["/api/exchange-rates", "/api/earnings/flatlines"],
        ids=["exchange-rates", "flatlines"],
    )
    def test_the_three_endpoints_from_the_bead_are_covered(self, path):
        """Named explicitly: these were served anonymously under mutation.

        Without this, a future narrowing of the sweep could drop them and the
        file would still look thorough.
        """
        assert ("GET", path) in {(m, p) for m, p, _u, _b in ALL_REQUESTS}

    def test_the_collect_trigger_is_covered(self):
        assert ("POST", "/api/collect") in {(m, p) for m, p, _u, _b in ALL_REQUESTS}
