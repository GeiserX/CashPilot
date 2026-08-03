"""Login rate limiting, extracted from main (CashPilot-sux).

The point of the move is structural: this was the last thing the routers
genuinely needed from ``app.main``, so extracting it is what actually removes
the ``main -> routers -> main`` import cycle. Everything else they reached for
through ``app.main`` — templates, client_ip, the auth guards — was already a
re-export of something in ``app.deps``.

The tests that matter are the ones about the seams. A refactor that quietly
rebinds a module-level dict leaves test fixtures clearing an object nothing
reads, and every test after it stops being isolated — a failure that shows up
much later as flakiness nobody can place.
"""

from __future__ import annotations

import ast
from time import monotonic

import pytest
from fastapi import HTTPException

from app import login_rate_limit as rl
from app import main


@pytest.fixture(autouse=True)
def _clean():
    rl._login_attempts.clear()
    yield
    rl._login_attempts.clear()


def imports_main(node) -> bool:
    """Does this AST node import ``app.main``, written any of the usual ways?

    The original version of this check tested only ``node.module.endswith("main")``,
    which misses ``from app import main`` entirely — that node's *module* is
    "app" and "main" is an alias NAME. Proven with a negative control: planting
    `from app import main` in a router left the guard green, and that is the
    idiomatic form everywhere else in this codebase (`from app import database,
    deps`). The guard that certifies the cycle is gone was blind to the most
    likely way of bringing it back.
    """
    if isinstance(node, ast.Import):
        # import app.main / import main
        return any(alias.name == "main" or alias.name.endswith(".main") for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        # from app.main import X / from .main import X
        if module == "main" or module.endswith(".main"):
            return True
        # from app import main / from . import main
        return any(alias.name == "main" for alias in node.names)
    return False


class TestTheCycleIsGone:
    def test_no_router_imports_main(self):
        """This is the whole reason the module exists."""
        import ast
        import pathlib

        offenders = sorted(
            path.name
            for path in (pathlib.Path(main.__file__).parent / "routers").glob("*.py")
            if any(imports_main(node) for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))))
        )
        assert not offenders, f"routers still import main: {offenders}"

    def test_no_module_anywhere_under_app_imports_main(self):
        """The guard above globs ONLY ``routers/*.py``.

        A new top-level module — ``app/fleet_state.py``, ``app/jobs.py``, the
        next extraction someone reaches for — falls entirely outside that glob
        and would reintroduce the cycle completely unguarded. Widening it costs
        nothing and is what makes the next extraction cheap, whether or not one
        ever happens.

        ``app.main`` itself is excluded for the obvious reason, and so are the
        routers, which the test above reports with a clearer message.
        """
        import ast
        import pathlib

        app_dir = pathlib.Path(main.__file__).parent
        offenders = sorted(
            str(path.relative_to(app_dir))
            for path in app_dir.rglob("*.py")
            if path.name != "main.py"
            and any(imports_main(node) for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))))
        )
        assert not offenders, f"these import app.main and would recreate the cycle: {offenders}"

    def test_that_guard_actually_looks_beyond_the_routers(self):
        """A checker that silently scans nothing passes forever.

        The first version of the widened guard could have kept the old glob by
        accident and still gone green, so this asserts it reaches modules the
        routers glob never covered.
        """
        import pathlib

        app_dir = pathlib.Path(main.__file__).parent
        scanned = {str(p.relative_to(app_dir)) for p in app_dir.rglob("*.py") if p.name != "main.py"}
        assert {"database.py", "orchestrator.py", "worker_api.py"} <= scanned, scanned

    def test_the_rate_limiter_imports_nothing_from_the_app(self):
        """Otherwise it could be pulled back into a cycle later."""
        import ast
        import pathlib

        tree = ast.parse(pathlib.Path(rl.__file__).read_text(encoding="utf-8"))
        app_imports = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app")
        ]
        assert not app_imports, f"login_rate_limit imports {app_imports}"


class TestTheTestSeamsStillPointAtTheSameObjects:
    def test_main_reexports_the_same_dict_not_a_copy(self):
        """conftest clears app.main._login_attempts between tests.

        A copy here would leave the fixture clearing something nothing reads,
        and every later test would silently inherit the previous one's state.
        """
        assert main._login_attempts is rl._login_attempts

    def test_clearing_through_main_clears_the_real_state(self):
        rl.record_failed_login("10.0.0.1")
        assert rl._login_attempts
        main._login_attempts.clear()
        assert not rl._login_attempts

    def test_main_reexports_the_same_functions(self):
        assert main._check_login_rate is rl.check_login_rate
        assert main._record_failed_login is rl.record_failed_login

    def test_the_published_limits_are_unchanged(self):
        assert main._LOGIN_MAX_ATTEMPTS == rl.MAX_ATTEMPTS == 5
        assert main._LOGIN_WINDOW_SECONDS == rl.WINDOW_SECONDS == 300


class TestTheBehaviourIsUnchanged:
    def test_it_allows_attempts_below_the_limit(self):
        for _ in range(rl.MAX_ATTEMPTS - 1):
            rl.record_failed_login("1.2.3.4")
        rl.check_login_rate("1.2.3.4")

    def test_it_blocks_at_the_limit(self):
        for _ in range(rl.MAX_ATTEMPTS):
            rl.record_failed_login("1.2.3.4")
        with pytest.raises(HTTPException) as exc:
            rl.check_login_rate("1.2.3.4")
        assert exc.value.status_code == 429

    def test_attempts_outside_the_window_do_not_count(self):
        rl._login_attempts["1.2.3.4"] = [monotonic() - (rl.WINDOW_SECONDS + 10)] * rl.MAX_ATTEMPTS
        rl.check_login_rate("1.2.3.4")

    def test_addresses_are_counted_separately(self):
        for _ in range(rl.MAX_ATTEMPTS):
            rl.record_failed_login("1.1.1.1")
        rl.check_login_rate("2.2.2.2")

    def test_a_successful_login_forgets_the_failures(self):
        rl.record_failed_login("1.2.3.4")
        rl.clear("1.2.3.4")
        assert "1.2.3.4" not in rl._login_attempts

    def test_clearing_an_address_that_never_failed_is_harmless(self):
        rl.clear("9.9.9.9")


class TestItDoesNotLeakBuckets:
    def test_an_aged_out_bucket_is_removed_rather_than_left_empty(self):
        """A plain dict, not a defaultdict, precisely so this can happen.

        Every distinct address that ever hits /login would otherwise leave a
        permanent key behind once its attempts expired — a slow leak that only
        shows on a host exposed long enough to see a lot of addresses.
        """
        rl._login_attempts["1.2.3.4"] = [monotonic() - (rl.WINDOW_SECONDS + 1)]
        rl.check_login_rate("1.2.3.4")
        assert "1.2.3.4" not in rl._login_attempts

    def test_checking_an_unseen_address_creates_no_entry(self):
        rl.check_login_rate("5.5.5.5")
        assert rl._login_attempts == {}
