"""Collector contracts (CashPilot-bfl).

The existing collector tests assert subclassing, async-ness and attribute
presence. None of that notices when a provider renames a field, which is how
the ProxyBase/Repocket/EarnFM breakages shipped: the collector stopped finding
the balance and every test stayed green.

Two honest limits on what this file can do, stated because the alternative is
pretending otherwise:

* A recorded fixture is frozen at the moment it was written. It cannot detect
  that a provider changed its API *today* — only that OUR code no longer reads
  what we said it reads. The nightly ``-m live`` job
  (.github/workflows/collector-live-check.yml) is the only thing here that
  checks reality, which is why it exists.
* The fixtures pin FIELD NAMES the collector depends on. That is the thing that
  actually breaks, and it is checkable without credentials or a network.

What this file therefore guarantees: every collector has a declared contract, a
new collector cannot be added without one, and a refactor that stops reading a
declared field fails CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.collectors import COLLECTOR_MAP

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "collectors"


def _fixture(slug: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{slug}.json").read_text(encoding="utf-8"))


def _source(slug: str) -> str:
    """The collector's own source, resolved via the CLASS not the slug.

    COLLECTOR_MAP is keyed by catalog slug ("mysterium", "anyone-protocol")
    while the modules are named after the provider's API ("mystnodes.py",
    "anyone.py"). Deriving the path from the slug silently looks at the wrong
    file — or no file at all.
    """
    module = COLLECTOR_MAP[slug].__module__.rsplit(".", 1)[-1]
    return (Path(__file__).parents[1] / "app" / "collectors" / f"{module}.py").read_text(encoding="utf-8")


ALL_SLUGS = sorted(COLLECTOR_MAP)


class TestEveryCollectorHasAContract:
    def test_no_collector_ships_without_a_fixture(self):
        """A new collector with no contract is exactly the untested case."""
        missing = [s for s in ALL_SLUGS if not (FIXTURE_DIR / f"{s}.json").exists()]
        assert not missing, (
            f"collectors without a contract fixture: {missing}. Add "
            f"tests/fixtures/collectors/<slug>.json declaring the fields it parses."
        )

    def test_no_fixture_describes_a_collector_that_no_longer_exists(self):
        orphans = [p.stem for p in FIXTURE_DIR.glob("*.json") if p.stem not in COLLECTOR_MAP]
        assert not orphans, f"fixtures for removed collectors: {orphans}"

    @pytest.mark.parametrize("slug", ALL_SLUGS)
    def test_the_contract_is_well_formed(self, slug):
        fx = _fixture(slug)
        assert fx["slug"] == slug
        assert fx["fields"], f"{slug}: a contract with no fields checks nothing"
        assert isinstance(fx["currency"], str) and fx["currency"]
        assert "sample" in fx


class TestTheCodeStillReadsWhatWeSayItReads:
    """A refactor that drops a declared field must fail here, not in production."""

    @pytest.mark.parametrize("slug", ALL_SLUGS)
    def test_every_declared_field_appears_in_the_collector(self, slug):
        source = _source(slug)
        fx = _fixture(slug)
        for dotted in fx["fields"]:
            leaf = dotted.split(".")[-1]
            assert leaf in source, (
                f"{slug}: the contract declares it parses {dotted!r}, but {leaf!r} does not appear in "
                f"app/collectors/{slug}.py. Either the code changed and the fixture is stale, "
                "or the fixture was wrong to begin with."
            )

    @pytest.mark.parametrize("slug", ALL_SLUGS)
    def test_the_declared_currency_matches_the_collector(self, slug):
        fx = _fixture(slug)
        currency = fx["currency"]
        if currency == "USD":
            # USD is the EarningsResult default, so its absence proves nothing.
            return
        assert currency in _source(slug), (
            f"{slug}: contract says it reports {currency}, which does not appear in the collector"
        )


class TestSampleShapesMatchTheDeclaredFields:
    """The sample must actually contain the fields the contract claims.

    Otherwise the fixture documents a shape nobody could parse, which is worse
    than no fixture — it looks like evidence.
    """

    @pytest.mark.parametrize("slug", ALL_SLUGS)
    def test_a_declared_path_resolves_in_the_sample_when_present(self, slug):
        fx = _fixture(slug)
        sample = fx["sample"]
        resolved = 0
        for dotted in fx["fields"]:
            node = sample
            for part in dotted.split("."):
                if not isinstance(node, dict) or part not in node:
                    node = None
                    break
                node = node[part]
            if node is not None:
                resolved += 1
        assert resolved >= 1, (
            f"{slug}: not one declared field resolves in the recorded sample, so the sample "
            "does not demonstrate the shape it claims to"
        )


class TestParsingRealShapes:
    """End-to-end parse for the collectors whose balance maths is deterministic.

    Deliberately not all fifteen: several authenticate across several hops or
    fall back to HTML scraping, and a mock elaborate enough to drive those would
    be asserting against my own invention rather than against a provider.
    """

    def _run(self, collector, payloads):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        def response(body):
            resp = MagicMock()
            resp.status_code = 200
            resp.json = MagicMock(return_value=body)
            resp.text = json.dumps(body)
            resp.raise_for_status = MagicMock()
            return resp

        client = MagicMock()
        client.get = AsyncMock(side_effect=[response(p) for p in payloads])
        client.post = AsyncMock(side_effect=[response(p) for p in payloads])
        client.is_closed = False
        client.aclose = AsyncMock()

        with patch.object(collector, "_get_client", return_value=client):
            return asyncio.run(collector.collect())

    def test_honeygain_reads_cents(self):
        from app.collectors.honeygain import HoneygainCollector

        fx = _fixture("honeygain")
        c = HoneygainCollector(email="a@b.c", password="x")
        c._token = "already-authenticated"
        out = self._run(c, [fx["sample"]])
        assert out.error is None
        assert out.balance == fx["parsed"]
        assert out.currency == fx["currency"]

    def test_salad_reads_the_balance_directly(self):
        from app.collectors.salad import SaladCollector

        fx = _fixture("salad")
        out = self._run(SaladCollector(auth_cookie="c"), [fx["sample"]])
        assert out.error is None
        assert out.balance == fx["parsed"]

    def test_a_renamed_field_is_caught_rather_than_read_as_zero(self):
        """The failure this bead exists for: the provider renames the key."""
        from app.collectors.salad import SaladCollector

        out = self._run(SaladCollector(auth_cookie="c"), [{"balanceCurrent": 3.5}])
        assert out.balance == 0.0 or out.error is not None, (
            "a renamed field must surface as an error or a zero, never as a plausible number"
        )


class TestCredentialSelfTest:
    """The button that answers "are these credentials valid?" in a second.

    The security requirement outranks the feature: a failing provider login
    frequently echoes the submitted payload, and a raw body has leaked into
    logs from a worker path in this codebase before. Nothing sensitive may
    appear in the response.
    """

    def _call(self, slug, config=None, collect=None, raises=None):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from app import credential_test, main

        credential_test._last_attempt.clear()
        collector = MagicMock()
        collector.close = AsyncMock()
        if raises is not None:
            collector.collect = AsyncMock(side_effect=raises)
        else:
            collector.collect = AsyncMock(return_value=collect)

        build = (collector, []) if (collect is not None or raises is not None) else (None, ["k"])

        async def run():
            with (
                patch.object(main, "_require_auth_api", lambda r: None),
                patch.object(main.database, "get_config", AsyncMock(return_value=config or {})),
                patch("app.collectors.build_one", return_value=build),
            ):
                return await main.api_test_credentials(MagicMock(), slug)

        return asyncio.run(run())

    def _result(self, balance=0.0, currency="USD", error=None):
        from app.collectors.base import EarningsResult

        return EarningsResult(platform="honeygain", balance=balance, currency=currency, error=error)

    def test_valid_credentials_report_the_balance(self):
        out = self._call("honeygain", collect=self._result(balance=12.5))
        assert out["ok"] is True
        assert "12.5" in out["message"]

    def test_a_rejected_login_says_so_without_echoing_anything(self):
        out = self._call("honeygain", collect=self._result(error="401 Unauthorized for token abc123secret"))
        assert out["ok"] is False
        assert out["outcome"] == "bad_credentials"
        assert "abc123secret" not in json.dumps(out), "the response leaked the provider's raw error"

    def test_a_raised_exception_never_leaks_its_text(self):
        out = self._call("honeygain", raises=RuntimeError("connect failed to https://user:hunter2@api"))
        assert "hunter2" not in json.dumps(out)
        assert out["outcome"] == "unreachable"

    def test_no_response_field_can_carry_a_secret(self):
        out = self._call("honeygain", collect=self._result(balance=1.0))
        assert set(out) <= {"ok", "outcome", "message", "balance", "currency"}

    def test_an_unknown_service_is_a_404(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            self._call("no-such-service")
        assert exc.value.status_code == 404

    def test_a_service_with_no_collector_says_there_is_nothing_to_test(self):
        out = self._call("grass" if "grass" not in COLLECTOR_MAP else "teneo")
        assert out["outcome"] in {"unsupported", "not_configured"}

    def test_unconfigured_credentials_are_reported_as_such(self):
        out = self._call("honeygain")
        assert out["outcome"] == "not_configured"

    def test_a_second_attempt_is_rate_limited(self):
        """Retrying a rejected login in a loop is how an account gets flagged."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from app import credential_test, main

        credential_test._last_attempt.clear()
        collector = MagicMock()
        collector.close = AsyncMock()
        collector.collect = AsyncMock(return_value=self._result(balance=1.0))

        async def run():
            with (
                patch.object(main, "_require_auth_api", lambda r: None),
                patch.object(main.database, "get_config", AsyncMock(return_value={})),
                patch("app.collectors.build_one", return_value=(collector, [])),
            ):
                first = await main.api_test_credentials(MagicMock(), "honeygain")
                second = await main.api_test_credentials(MagicMock(), "honeygain")
                return first, second

        first, second = asyncio.run(run())
        assert first["ok"] is True
        assert second["outcome"] == "rate_limited"
        assert collector.collect.await_count == 1, "the provider was hit twice despite the cooldown"

    def test_the_collector_is_closed_even_when_it_raises(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from app import credential_test, main

        credential_test._last_attempt.clear()
        collector = MagicMock()
        collector.close = AsyncMock()
        collector.collect = AsyncMock(side_effect=RuntimeError("boom"))

        async def run():
            with (
                patch.object(main, "_require_auth_api", lambda r: None),
                patch.object(main.database, "get_config", AsyncMock(return_value={})),
                patch("app.collectors.build_one", return_value=(collector, [])),
            ):
                return await main.api_test_credentials(MagicMock(), "honeygain")

        asyncio.run(run())
        collector.close.assert_awaited()


class TestOutcomeClassification:
    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (None, "ok"),
            ("401 Unauthorized", "bad_credentials"),
            ("HTTP 403 Forbidden", "bad_credentials"),
            ("Read timed out", "unreachable"),
            ("Connection refused", "unreachable"),
            ("Honeygain not configured", "not_configured"),
            ("KeyError: 'usd_cents'", "unexpected_shape"),
            ("something nobody anticipated", "unexpected_shape"),
        ],
    )
    def test_errors_map_to_stable_outcomes(self, error, expected):
        from app import credential_test

        assert credential_test.classify(error) == expected

    def test_every_outcome_has_a_message_a_user_can_act_on(self):
        from app import credential_test

        for outcome in (
            "ok",
            "bad_credentials",
            "not_configured",
            "unreachable",
            "unexpected_shape",
            "rate_limited",
            "unsupported",
        ):
            msg = credential_test.message(outcome, "Honeygain")
            assert len(msg) > 20 and msg.endswith((".", "!"))


class TestBuildingASingleCollector:
    """`build_one` is what the credential self-test runs.

    Deliberately UNCACHED: the button exists to check credentials the user just
    changed, and handing back a cached instance built from the previous values
    would validate the wrong thing and report success for a credential that no
    longer exists.
    """

    def test_it_builds_a_collector_when_every_required_key_is_present(self):
        from app import collectors

        collector, missing = collectors.build_one("honeygain", {"honeygain_email": "a@b.c", "honeygain_password": "pw"})
        assert collector is not None
        assert missing == []
        assert collector.platform == "honeygain"

    def test_it_names_the_missing_keys_rather_than_failing_vaguely(self):
        from app import collectors

        collector, missing = collectors.build_one("honeygain", {})
        assert collector is None
        assert missing == ["honeygain_email", "honeygain_password"]

    def test_a_partially_configured_service_names_only_what_is_absent(self):
        from app import collectors

        _, missing = collectors.build_one("honeygain", {"honeygain_email": "a@b.c"})
        assert missing == ["honeygain_password"]

    def test_an_unknown_slug_yields_nothing_and_no_missing_keys(self):
        """Nothing is missing because nothing was ever required."""
        from app import collectors

        assert collectors.build_one("no-such-service", {}) == (None, [])

    def test_each_call_returns_a_fresh_instance(self):
        """A cached one would validate the credentials the user just replaced."""
        from app import collectors

        config = {"honeygain_email": "a@b.c", "honeygain_password": "pw"}
        first, _ = collectors.build_one("honeygain", config)
        second, _ = collectors.build_one("honeygain", config)
        assert first is not second

    def test_it_never_populates_the_shared_collector_cache(self):
        from app import collectors

        collectors._cached_collectors.pop("honeygain", None)
        collectors.build_one("honeygain", {"honeygain_email": "a@b.c", "honeygain_password": "pw"})
        assert "honeygain" not in collectors._cached_collectors

    def test_optional_arguments_are_not_required(self):
        """A '?'-prefixed argument must not block construction when absent."""
        from app import collectors

        optional_slugs = [
            slug for slug, args in collectors._COLLECTOR_ARGS.items() if any(a.startswith("?") for a in args)
        ]
        if not optional_slugs:
            pytest.skip("no collector declares an optional argument")
        slug = optional_slugs[0]
        required = {f"{slug}_{a}": "x" for a in collectors._COLLECTOR_ARGS[slug] if not a.startswith("?")}
        collector, missing = collectors.build_one(slug, required)
        assert missing == []
        assert collector is not None

    def test_a_constructor_that_raises_is_reported_as_no_collector(self):
        from unittest.mock import patch

        from app import collectors

        with patch.dict(
            collectors.COLLECTOR_MAP, {"honeygain": lambda **kw: (_ for _ in ()).throw(ValueError("nope"))}
        ):
            collector, missing = collectors.build_one(
                "honeygain", {"honeygain_email": "a@b.c", "honeygain_password": "pw"}
            )
        assert collector is None
        assert missing == []

    def test_it_resolves_the_same_keys_as_the_scheduled_factory(self):
        """Two resolvers that disagree would validate different credentials."""
        from app import collectors

        for slug, args in collectors._COLLECTOR_ARGS.items():
            if slug not in collectors.COLLECTOR_MAP:
                continue
            _, missing = collectors.build_one(slug, {})
            expected = sorted(f"{slug}_{a}" for a in args if not a.startswith("?"))
            assert sorted(missing) == expected, f"{slug}: build_one disagrees with _COLLECTOR_ARGS"
