"""Guards for defects found in the v1.10.0 audit.

Each class here exists because a real defect got past the suite. The point is
not coverage — it is that the *shape* of each failure now turns the build red.

The auth class is the sharpest example: deleting `_require_auth_api` from five
endpoints was verified to leave all 2108 tests passing, because every endpoint
test patches the guard away before calling the handler.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]


def _unauthenticated():
    request = MagicMock()
    request.session = {}
    request.headers = {}
    request.cookies = {}
    return request


def _call(fn, *args):
    import asyncio

    return asyncio.run(fn(_unauthenticated(), *args))


class TestEveryEndpointRejectsAnAnonymousCaller:
    """Verified necessary: removing the guard left the whole suite green.

    Every other endpoint test patches `_require_auth_api` to a no-op before
    calling the handler, so nothing anywhere noticed the guard was gone.
    """

    @pytest.mark.parametrize(
        ("name", "args"),
        [
            ("api_fleet_egress_groups", ()),
            ("api_service_preflight", ("honeygain",)),
            ("api_producer_state", ("honeygain",)),
            ("api_payout_progress", ("honeygain",)),
            ("api_fleet_economics", ()),
            ("api_payouts", ()),
            ("api_deploy_risk", ("mysterium",)),
            ("api_isolation_guide", ()),
            ("api_service_disclosure", ("mysterium",)),
            ("api_disclosure_coverage", ()),
            ("api_earnings_net", ()),
        ],
        ids=lambda v: v if isinstance(v, str) else "",
    )
    def test_a_read_endpoint_requires_authentication(self, name, args):
        from app import main

        with pytest.raises(HTTPException) as exc:
            _call(getattr(main, name), *args)
        assert exc.value.status_code == 401, f"{name} served an unauthenticated caller"

    @pytest.mark.parametrize(
        ("name", "args"),
        [("api_test_credentials", ("honeygain",)), ("api_confirm_payout", (1,)), ("api_reject_payout", (1,))],
        ids=lambda v: v if isinstance(v, str) else "",
    )
    def test_a_mutating_endpoint_rejects_an_anonymous_caller(self, name, args):
        from app import main

        with pytest.raises(HTTPException) as exc:
            _call(getattr(main, name), *args)
        assert exc.value.status_code in (401, 403), f"{name} served an unauthenticated caller"


class TestMutatingEndpointsSitAboveViewer:
    """The repo's ladder: reads -> auth, actions -> writer, secrets -> owner.

    Three v1.10.0 endpoints deviated silently: a viewer could fire an
    authenticated login to a provider using the owner's credentials, and could
    permanently DELETE payout rows.
    """

    LADDER = {
        "api_test_credentials": "_require_owner",
        "api_confirm_payout": "_require_writer",
        "api_reject_payout": "_require_writer",
    }

    @pytest.mark.parametrize(("name", "expected"), sorted(LADDER.items()), ids=lambda v: v)
    def test_the_expected_guard_is_the_one_called(self, name, expected):
        import inspect
        import textwrap

        from app import main

        tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(main, name))))
        called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert expected in called, (
            f"{name} should call {expected}, called {sorted(called & {'_require_auth_api', '_require_writer', '_require_owner'})}"
        )


class TestTheWorkerImageShipsEveryModuleItImports:
    """A missing COPY line is a crash that ONLY happens in the real image.

    Local tests pass (the module is on disk), `docker build` succeeds (the
    listed files still copy), and the container then crash-loops on the user's
    machine after a pull. Nothing else in the pipeline can see it.
    """

    def _closure(self) -> set[str]:
        seen: set[str] = set()
        queue = ["worker_api"]
        while queue:
            mod = queue.pop()
            if mod in seen:
                continue
            path = ROOT / "app" / f"{mod}.py"
            if not path.exists():
                continue
            seen.add(mod)
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app"):
                    parts = (node.module or "").split(".")
                    if len(parts) > 1:
                        queue.append(parts[1])
                    queue.extend(a.name for a in node.names)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("app."):
                            queue.append(alias.name.split(".")[1])
        return seen

    def test_every_imported_module_is_copied_into_the_image(self):
        dockerfile = (ROOT / "Dockerfile.worker").read_text(encoding="utf-8")
        copied = set(re.findall(r"COPY[^\n]*\sapp/([a-z_]+)\.py\s", dockerfile))
        missing = {m for m in self._closure() if m != "__init__"} - copied - {"collectors"}
        assert not missing, (
            f"app/worker_api.py imports {sorted(missing)}, which Dockerfile.worker does not COPY. "
            "The image would build fine and then crash-loop on a user's machine."
        )

    def test_the_closure_is_not_trivially_empty(self):
        """A broken parser would make the test above vacuously pass."""
        closure = self._closure()
        assert {"worker_api", "orchestrator", "egress"} <= closure, closure


class TestNoConditionIsStaticallyImpossible:
    """Generalises the dead 401 alarm rather than just fixing it.

    That block compared a counter to 3 in the branch that had just set it to 0
    — `0 == 3`, never true, so the alarm was unreachable while a test named for
    it passed. A misplaced block is invisible to every check that asks whether
    code survived: a line moved into the wrong branch still survives.

    So this asks a different question — is any comparison decidable at parse
    time? A hand-written condition should not be.
    """

    def _impossible(self, path: Path) -> list[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # A name assigned a constant in the same branch, then compared against
        # a different constant, is the shape that hid the alarm.
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            for branch in (node.body, node.orelse):
                assigned: dict[str, object] = {}
                for stmt in branch:
                    if (
                        isinstance(stmt, ast.Assign)
                        and len(stmt.targets) == 1
                        and isinstance(stmt.targets[0], ast.Name)
                        and isinstance(stmt.value, ast.Constant)
                    ):
                        assigned[stmt.targets[0].id] = stmt.value.value
                    elif isinstance(stmt, ast.If):
                        test = stmt.test
                        if (
                            isinstance(test, ast.Compare)
                            and isinstance(test.left, ast.Name)
                            and test.left.id in assigned
                            and len(test.ops) == 1
                            and isinstance(test.ops[0], ast.Eq)
                            and isinstance(test.comparators[0], ast.Constant)
                            and assigned[test.left.id] != test.comparators[0].value
                        ):
                            found.append(f"{path.name}:{stmt.lineno} `{test.left.id}` is always != here")
        return found

    def test_no_module_contains_an_unreachable_branch(self):
        offenders = [f for p in sorted((ROOT / "app").rglob("*.py")) for f in self._impossible(p)]
        assert not offenders, "condition can never be true — the block is dead code: " + "; ".join(offenders)

    def test_the_detector_catches_the_defect_it_was_written_for(self):
        """A checker nobody proved is a checker that quietly passes forever.

        My first version of this scanned only `body` and missed the real bug,
        which lived in `orelse`.
        """
        import tempfile

        source = (
            "def f(s):\n"
            "    if s == 401:\n"
            "        n += 1\n"
            "    else:\n"
            "        n = 0\n"
            "        if n == 3:\n"
            "            alarm()\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "regression.py"
            path.write_text(source, encoding="utf-8")
            assert self._impossible(path), "the detector cannot see the bug it exists for"


class TestOneTariffKey:
    """Two features shipped reading different config keys for one tariff.

    Setting one left the other reporting "cost unknown" forever — and both
    unknown-paths are deliberately quiet, which is exactly what hid it.
    """

    def test_both_endpoints_read_the_same_canonical_key(self):
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        canonical = source.count("power_price_per_kwh")
        assert canonical >= 2, "the canonical tariff key should be read by both consumers"

    def test_the_newer_key_is_still_honoured_as_a_fallback(self):
        """Nobody's existing config should break because we picked a name."""
        source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert 'config.get("power_price_per_kwh") or config.get("electricity_price_per_kwh")' in source


class TestNoRouteIsShadowedByAnEarlierParameterisedOne:
    """FastAPI matches in declaration order.

    Every v1.10.0 endpoint was appended 800+ lines below `/api/services/{slug}`
    and escaped only because each carries a second path segment. A future
    `/api/services/summary` would 404 with no error anywhere.
    """

    def test_every_literal_path_resolves_to_its_own_handler(self):
        from fastapi.routing import APIRoute

        from app.main import app

        literals = [
            r for r in app.routes if isinstance(r, APIRoute) and "{" not in r.path and r.path.startswith("/api/")
        ]
        for route in literals:
            method = next(iter(route.methods - {"HEAD", "OPTIONS"}), "GET")
            scope = {
                "type": "http",
                "path": route.path,
                "method": method,
                "path_params": {},
                "headers": [],
                "query_string": b"",
                "root_path": "",
            }
            winner = next(
                (r for r in app.routes if isinstance(r, APIRoute) and r.matches(scope)[0].name == "FULL"),
                None,
            )
            assert winner is route, (
                f"{method} {route.path} is shadowed by {getattr(winner, 'path', None)} "
                "— it is declared after a parameterised route that swallows it"
            )
