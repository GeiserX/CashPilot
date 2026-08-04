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

    The class name overstates what a hand-written list can do — it covered 14 of
    75 routes, and a guard deleted from any of the other 61 kept the suite green.
    tests/test_every_route_rejects_anonymous.py now sweeps every registered route
    instead. This is kept because it calls the handlers directly, which catches a
    guard that is present but unreachable behind an earlier return.
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


class TestWorkerCredentialsNeverReachAResponse:
    """`list_workers` is a `SELECT *`, so the fleet key rides along by default.

    Verified against the running handlers before the fix: GET /api/workers and
    GET /api/workers/{id} both returned `api_key_enc` to any authenticated
    caller, viewers included. Encryption at rest is not a reason to publish the
    ciphertext — doing so makes the Fernet key the only thing between a
    read-only account and every worker's credential.
    """

    def _worker_endpoints(self, tmp_path):
        import asyncio
        from unittest.mock import MagicMock, patch

        from app import database, main

        async def run():
            with (
                patch.object(database, "DB_DIR", tmp_path),
                patch.object(database, "DB_PATH", tmp_path / "w.db"),
            ):
                await database.init_db()
                await database.upsert_worker(client_id="w1", name="host", url="http://w:8081")
                await database.set_worker_key("w1", "a-real-fleet-key")
                rows = await database.list_workers()
                assert rows[0].get("api_key_enc"), "fixture must actually store a key"
                with patch.object(main, "_require_auth_api", lambda r: None):
                    one = await main.api_get_worker(MagicMock(), rows[0]["id"])
                    many = await main.api_list_workers(MagicMock())
                return one, many

        return asyncio.run(run())

    def test_the_single_worker_endpoint_omits_the_key(self, tmp_path):
        one, _ = self._worker_endpoints(tmp_path)
        assert "api_key_enc" not in one

    def test_the_list_endpoint_omits_the_key(self, tmp_path):
        _, many = self._worker_endpoints(tmp_path)
        assert all("api_key_enc" not in w for w in many)

    def test_no_response_field_carries_the_ciphertext_under_another_name(self, tmp_path):
        """Renaming the column must not quietly restore the leak."""
        one, _ = self._worker_endpoints(tmp_path)
        blob = repr(one)
        assert "gAAAAA" not in blob, "a Fernet token appears in the response"

    def test_the_worker_is_still_usable_without_it(self, tmp_path):
        """A stripping fix that empties the payload is not a fix."""
        one, _ = self._worker_endpoints(tmp_path)
        assert one["name"] == "host"
        assert "containers" in one and "system_info" in one


class TestADetectedPayoutActuallyReachesTheUser:
    """The prompt is the entire feature. Filing it silently is the same as not detecting it.

    `_detect_payout` ran in the collection SUCCESS branch and wrote to the
    database; the bell renders the in-memory list built by the FAILURE branch;
    and the startup restore dropped every alert whose kind was not "collector".
    So a detected payout was recorded and then shown to nobody, live or after a
    restart — the user was never asked the question the feature exists to ask.
    """

    def test_a_detected_payout_is_returned_so_the_bell_can_show_it(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from app import main

        result = MagicMock(platform="honeygain", balance=0.10, currency="USD")

        async def run():
            with (
                patch.object(main.database, "get_latest_balance", AsyncMock(return_value=25.0)),
                patch.object(main.database, "record_probable_payout", AsyncMock(return_value=7)),
                patch.object(main.database, "record_alert", AsyncMock()),
                patch.object(
                    main.catalog, "get_service", return_value={"slug": "honeygain", "cashout": {"min_amount": 20.0}}
                ),
            ):
                return await main._detect_payout(result)

        alert = asyncio.run(run())
        assert alert is not None, "detected and then dropped on the floor"
        assert alert["kind"] == "payout"
        assert alert["platform"] == "honeygain"

    def test_nothing_is_returned_when_there_is_no_payout(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from app import main

        result = MagicMock(platform="honeygain", balance=26.0, currency="USD")

        async def run():
            with (
                patch.object(main.database, "get_latest_balance", AsyncMock(return_value=25.0)),
                patch.object(
                    main.catalog, "get_service", return_value={"slug": "honeygain", "cashout": {"min_amount": 20.0}}
                ),
            ):
                return await main._detect_payout(result)

        assert asyncio.run(run()) is None

    def test_a_restart_does_not_lose_the_pending_question(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from app import main

        stored = [
            {"kind": "payout", "subject": "honeygain", "message": "Balance dropped by 25.00"},
            {"kind": "collector", "subject": "grass", "message": "login failed"},
        ]

        async def run():
            with patch.object(main.database, "list_alerts", AsyncMock(return_value=stored)):
                await main._warm_collector_alerts()

        asyncio.run(run())
        kinds = {a.get("kind") for a in main._collector_alerts}
        assert "payout" in kinds, "the payout prompt was dropped on restart"
        assert "collector" in kinds, "restoring payouts must not cost us collector alerts"

    def test_a_platform_can_have_both_a_broken_collector_and_a_payout(self):
        """Deduping by subject alone would silently hide one of them."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        from app import main

        stored = [
            {"kind": "payout", "subject": "honeygain", "message": "Balance dropped"},
            {"kind": "collector", "subject": "honeygain", "message": "login failed"},
        ]

        async def run():
            with patch.object(main.database, "list_alerts", AsyncMock(return_value=stored)):
                await main._warm_collector_alerts()

        asyncio.run(run())
        assert len(main._collector_alerts) == 2, main._collector_alerts

    def test_the_endpoint_tags_every_alert_so_the_bell_can_tell_them_apart(self):
        import asyncio
        from unittest.mock import MagicMock, patch

        from app import main

        with (
            patch.object(main, "_collector_alerts", [{"platform": "grass", "error": "boom"}]),
            patch.object(main, "_require_auth_api", lambda r: None),
        ):
            out = asyncio.run(main.api_collector_alerts(MagicMock()))
        assert out[0]["kind"] == "collector", "an untagged alert must default to collector, not vanish"


class TestTheCredentialCooldownCannotBeRaced:
    """Two clicks must not both reach the provider.

    Repeated logins are what get an account flagged, which is the only reason
    the cooldown exists. The check and the claim were separated by
    `await database.get_config()`, and an await is exactly where the event loop
    runs the other request.
    """

    def test_the_claim_is_not_separated_from_its_check_by_an_await(self):
        import ast
        import inspect
        import textwrap

        from app import main

        tree = ast.parse(textwrap.dedent(inspect.getsource(main.api_test_credentials)))
        body = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)).body

        def flatten(nodes):
            for node in nodes:
                yield node
                for field in ("body", "orelse", "finalbody"):
                    yield from flatten(getattr(node, field, []) or [])

        order = []
        for node in flatten(body):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Await):
                    order.append(("await", node.lineno))
                elif (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr in ("cooldown_remaining", "note_attempt")
                ):
                    order.append((sub.func.attr, node.lineno))
        sequence = [name for name, _ in sorted(set(order), key=lambda p: p[1])]
        claim = sequence.index("note_attempt")
        preceding = sequence[:claim]
        assert "cooldown_remaining" in preceding, "nothing checks the cooldown before claiming it"
        last_check = len(preceding) - 1 - preceding[::-1].index("cooldown_remaining")
        assert "await" not in sequence[last_check:claim], (
            "an await sits between the cooldown check and note_attempt, so two "
            "concurrent requests can both pass the check and both hit the provider"
        )


class TestAPayoutPromptSurvivesUntilItIsAnswered:
    """A prompt that vanishes on its own is worse than no prompt.

    `record_probable_payout` returns None while one is already pending, so
    `_detect_payout` reported a payout on the run that noticed it and None
    forever after. Rebuilding the bell from that alone made the question
    disappear on the very next collection — before the user could answer it.
    """

    PENDING = [
        {"id": 1, "platform": "honeygain", "amount": 25.0, "currency": "USD", "confirmed": 0},
        {"id": 2, "platform": "iproyal", "amount": 5.0, "currency": "USD", "confirmed": 1},
    ]

    def test_an_unanswered_payout_is_re_added_on_a_later_run(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from app import main

        with patch.object(main.database, "get_payouts", AsyncMock(return_value=self.PENDING)):
            alerts = asyncio.run(main._pending_payout_alerts())
        assert [a["platform"] for a in alerts] == ["honeygain"], "the pending question must persist"
        assert alerts[0]["kind"] == "payout"

    def test_an_already_confirmed_payout_is_not_asked_about_again(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from app import main

        with patch.object(main.database, "get_payouts", AsyncMock(return_value=self.PENDING)):
            alerts = asyncio.run(main._pending_payout_alerts())
        assert all(a["platform"] != "iproyal" for a in alerts)

    def test_it_does_not_duplicate_one_detected_in_this_run(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from app import main

        with patch.object(main.database, "get_payouts", AsyncMock(return_value=self.PENDING)):
            alerts = asyncio.run(main._pending_payout_alerts(seen={"honeygain"}))
        assert alerts == [], "the same payout would appear twice in the bell"

    def test_the_message_tells_the_user_what_to_do(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from app import main

        with patch.object(main.database, "get_payouts", AsyncMock(return_value=self.PENDING)):
            message = asyncio.run(main._pending_payout_alerts())[0]["error"]
        assert "Confirm or reject" in message

    def test_a_database_failure_does_not_break_the_collection_run(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from app import main

        with patch.object(main.database, "get_payouts", AsyncMock(side_effect=RuntimeError("db down"))):
            assert asyncio.run(main._pending_payout_alerts()) == []

    def test_answering_a_payout_retires_its_prompt(self):
        """Otherwise a restart restores it and asks again about a settled payout."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        from app import main

        with (
            patch.object(main.database, "get_payouts", AsyncMock(return_value=self.PENDING)),
            patch.object(main.database, "clear_alerts", AsyncMock()) as cleared,
            patch.object(main, "_collector_alerts", [{"kind": "payout", "platform": "honeygain", "error": "x"}]),
        ):
            asyncio.run(main._retire_payout_alert(1))
            cleared.assert_awaited_once_with("payout", "honeygain")
            # Inside the patch: _retire_payout_alert REBINDS the module global,
            # and patch.object restores it on exit, so asserting afterwards
            # would read the original list and pass for the wrong reason.
            assert main._collector_alerts == []
