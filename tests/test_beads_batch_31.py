"""CashPilot-33h: two more route sweeps were quietly shrinking.

``app.routes`` is not a complete enumeration on Starlette 1.3 — the version CI
installs, because requirements.txt pins only ``fastapi>=0.136.1``.
``include_router`` stops adding its routes there: re-including a 6-route
APIRouter grew ``app.routes`` by ONE, and ``/login`` never appeared at all.

Three test modules walked ``app.routes`` independently. The first was caught
only because a PUBLIC-list staleness check failed on CI and nowhere else. The
other two would have shrunk in silence, and one of them is the shape that breaks
worst: ``assert not paths & {"/docs", "/redoc", "/openapi.json"}`` is a NEGATIVE
assertion, true by omission the moment the set is incomplete.

One helper now, rather than a third copy of the same workaround.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"


class TestTheEnumerationSeesTheWholeApp:
    def test_it_finds_the_router_routes(self):
        from tests.route_enumeration import all_paths

        paths = all_paths()
        for path in ("/", "/login", "/logout", "/register", "/onboarding"):
            assert path in paths, f"{path} is served but not enumerated"

    def test_it_finds_the_directly_registered_routes(self):
        """The control: the union must not lose what app.routes already had."""
        from tests.route_enumeration import all_paths

        paths = all_paths()
        assert "/api/workers" in paths
        assert "/api/earnings/summary" in paths

    def test_it_does_not_duplicate(self):
        """Deduplicated on (path, methods), so a version where include_router
        still populates app.routes yields the same list rather than doubles."""
        from tests.route_enumeration import all_routes

        keys = [(getattr(r, "path", ""), frozenset(getattr(r, "methods", None) or ())) for r in all_routes()]
        assert len(keys) == len(set(keys)), "the union produced duplicate routes"

    def test_it_sees_more_than_app_routes_alone(self):
        """The premise. If this ever stops being true the helper is harmless,
        but the comment explaining it would be wrong, so it is asserted."""
        from app.main import app
        from tests.route_enumeration import all_routes

        real = [r for r in app.routes if getattr(r, "path", "")]
        assert len(all_routes()) > len(real), (
            "the union found nothing app.routes was missing — either Starlette changed back, "
            "or the helper stopped reaching the routers"
        )


class TestEverySweepUsesIt:
    """A fourth copy of the workaround is the thing to prevent."""

    SWEEPS = {
        "test_audit_guards.py": "the shadowing check",
        "test_beads_batch_1.py": "the docs-disabled check",
        "test_every_route_rejects_anonymous.py": "the anonymous sweep",
    }

    @pytest.mark.parametrize("filename", sorted(SWEEPS))
    def test_it_does_not_walk_app_routes_directly(self, filename):
        """Checked against the AST, not the text.

        Two earlier versions were wrong in opposite directions. Matching the
        literal "in app.routes" let a control reverting via
        `__import__("app.main").app.routes` sail straight past. Matching any
        mention then flagged the DOCSTRINGS that explain why the helper exists.

        An attribute access is the thing that actually matters, and it is what
        the parser can see: prose cannot trip it and no spelling can hide from
        it.
        """
        import ast

        tree = ast.parse((TESTS / filename).read_text(encoding="utf-8"))
        offenders = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr == "routes"
            and getattr(node.value, "id", getattr(node.value, "attr", None)) == "app"
        ]
        assert not offenders, (
            f"{filename} ({self.SWEEPS[filename]}) reaches for app.routes at line(s) {offenders}, "
            "which is incomplete on Starlette 1.3 — use tests/route_enumeration.py"
        )

    @pytest.mark.parametrize("filename", sorted(SWEEPS))
    def test_it_imports_the_helper(self, filename):
        source = (TESTS / filename).read_text(encoding="utf-8")
        assert "route_enumeration" in source, f"{filename} does not use the shared enumeration"


class TestTheNegativeAssertionCannotPassVacuously:
    """`assert not paths & {...}` is true when paths is empty.

    That is the failure mode an incomplete enumeration produces, so the test
    that makes the claim now also asserts it enumerated anything at all.
    """

    def test_the_docs_check_guards_against_an_empty_set(self):
        source = (TESTS / "test_beads_batch_1.py").read_text(encoding="utf-8")
        i = source.index("def test_no_route_serves_them")
        block = source[i : i + 900]
        assert "assert paths," in block, "an empty enumeration would satisfy this test"

    def test_the_docs_are_still_actually_disabled(self):
        """The control: the guard above must not be the only thing left."""
        from tests.route_enumeration import all_paths

        assert not all_paths() & {"/docs", "/redoc", "/openapi.json"}


def test_the_helper_explains_why_it_exists():
    """A workaround with no recorded reason gets 'simplified' back out."""
    source = (TESTS / "route_enumeration.py").read_text(encoding="utf-8")
    assert "Starlette 1.3" in source
    assert re.search(r"include_router", source)
