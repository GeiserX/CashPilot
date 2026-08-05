"""CashPilot-h3d: "Configured" for credentials that are never collected.

The bead's premise was that saving credentials in Settings → Collectors turned
the badge green while nothing ever collected them, because collection iterates
DEPLOYMENT ROWS (`make_collectors`) and saving credentials created none.

Half of that is now false: #187 made `POST /api/config` create an `external`
deployment row for any service whose required credentials are complete. The
badge and the tracking agree at save time.

The other half survived, and only on the path nobody tests by hand: a database
written BEFORE that fix. Those credentials are complete, so Settings shows
"Configured"; no row exists, so no collector is ever built; and nothing ever
re-runs the save path, because the user has no reason to re-save credentials the
UI says are fine. The fix that was supposed to end this state left every
existing install in it.

So: one predicate (`collectors.fully_configured_slugs`) shared by the save path
and a startup backfill, rather than a second inline copy that can drift from it.

The backfill is deliberately narrow. It never touches a slug that already has a
row — that row can carry a real container id and an encrypted spec, and
replacing it with an empty placeholder would lose the spec a later redeploy
needs.
"""

from __future__ import annotations

import pytest


class TestTheCompletenessPredicate:
    """One rule for "these credentials are complete", used by both callers."""

    def _slugs(self, config):
        from app.collectors import fully_configured_slugs

        return fully_configured_slugs(config)

    def _required_keys(self, slug):
        from app.collectors import _COLLECTOR_ARGS

        return [f"{slug}_{a}" for a in _COLLECTOR_ARGS.get(slug, []) if not a.startswith("?")]

    def test_a_service_with_every_required_key_is_configured(self):
        keys = self._required_keys("honeygain")
        assert keys, "honeygain has no required credentials — this test would prove nothing"
        assert "honeygain" in self._slugs({k: "value" for k in keys})

    def test_one_missing_required_key_is_not_configured(self):
        """The exact case the badge used to get wrong: email set, password not."""
        keys = self._required_keys("honeygain")
        assert len(keys) > 1, "needs a multi-field service to distinguish partial from complete"
        assert "honeygain" not in self._slugs({k: "value" for k in keys[:-1]})

    def test_an_empty_string_does_not_count_as_set(self):
        """Cleared credentials are stored as "", not deleted."""
        keys = self._required_keys("honeygain")
        config = {k: "value" for k in keys}
        config[keys[0]] = ""
        assert "honeygain" not in self._slugs(config)

    def test_optional_keys_are_not_demanded(self):
        """A collector works without them, so requiring them would refuse to track."""
        from app.collectors import _COLLECTOR_ARGS

        # Needs BOTH: an optional arg to ignore, and a required one to satisfy.
        # storj declares only `?api_url`, so it has no required credentials at
        # all and is deliberately never claimed — picking it proved the opposite
        # of what this test is about.
        slug = next(
            (
                s
                for s, args in _COLLECTOR_ARGS.items()
                if s in self._all()
                and any(a.startswith("?") for a in args)
                and any(not a.startswith("?") for a in args)
            ),
            None,
        )
        if slug is None:
            pytest.skip("no collector currently mixes required and optional arguments")
        assert slug in self._slugs({k: "value" for k in self._required_keys(slug)})

    def _all(self):
        from app.collectors import COLLECTOR_MAP

        return set(COLLECTOR_MAP)

    def test_nothing_is_configured_by_an_empty_config(self):
        assert self._slugs({}) == set()

    def test_a_slug_with_no_required_args_is_never_claimed(self):
        """There is no credential to be complete, so the user configured nothing."""
        from app.collectors import _COLLECTOR_ARGS, COLLECTOR_MAP

        bare = [s for s in COLLECTOR_MAP if not [a for a in _COLLECTOR_ARGS.get(s, []) if not a.startswith("?")]]
        for slug in bare:
            assert slug not in self._slugs({f"{slug}_anything": "value"})

    def test_it_only_reports_slugs_that_have_a_collector(self):
        """Tracking a slug with no collector class would create a row that collects nothing."""
        from app.collectors import _COLLECTOR_ARGS, COLLECTOR_MAP

        config = {f"{slug}_{a.lstrip('?')}": "value" for slug, args in _COLLECTOR_ARGS.items() for a in args}
        assert self._slugs(config) <= set(COLLECTOR_MAP)


class TestTheStartupBackfill:
    """The upgrade path: credentials stored before saving them began tracking."""

    @pytest.fixture
    def db(self, tmp_path, monkeypatch):
        import asyncio

        from app import database

        monkeypatch.setattr(database, "DB_DIR", tmp_path)
        monkeypatch.setattr(database, "DB_PATH", tmp_path / "h3d.db")
        monkeypatch.setattr(database, "_shared_db", None, raising=False)
        asyncio.run(database.init_db())
        return database

    def _honeygain_config(self):
        from app.collectors import _COLLECTOR_ARGS

        return {f"honeygain_{a}": "value" for a in _COLLECTOR_ARGS["honeygain"] if not a.startswith("?")}

    @pytest.mark.asyncio
    async def test_it_creates_a_row_for_stranded_credentials(self, db):
        """The whole bead: complete credentials, no row, nothing collecting."""
        from app import main

        await db.set_config_bulk(self._honeygain_config())
        assert not await db.get_deployments(), "fixture is wrong — a row already exists"

        created = await main._track_fully_configured_services()

        assert created == 1
        slugs = {d["slug"] for d in await db.get_deployments()}
        assert "honeygain" in slugs, "credentials stored before the fix are still never collected"

    @pytest.mark.asyncio
    async def test_the_row_it_creates_is_one_collection_will_use(self, db):
        """A row of the wrong shape would satisfy the test above and collect nothing.

        make_collectors reads `slug` off each deployment, so that is what has to
        be right — asserting the row merely exists proves nothing.
        """
        from app import collectors as collectors_mod
        from app import main
        from app.collectors import make_collectors

        await db.set_config_bulk(self._honeygain_config())
        await main._track_fully_configured_services()

        deployments = await db.get_deployments()
        config = await db.get_config()
        collectors = make_collectors(deployments, config)
        try:
            assert any(type(c).__name__.lower().startswith("honeygain") for c in collectors), (
                "the backfilled row does not produce a collector, so nothing is collected"
            )
        finally:
            # Evict BEFORE closing. make_collectors caches by slug and hands the
            # cached instance back whenever the resolved kwargs match, so
            # closing without evicting leaves a closed httpx client in the cache
            # for the next caller with the same credentials to be given.
            for slug in [d["slug"] for d in deployments]:
                collectors_mod._cached_collectors.pop(slug, None)
                collectors_mod._cached_kwargs.pop(slug, None)
            for collector in collectors:
                await collector.close()

    @pytest.mark.asyncio
    async def test_incomplete_credentials_are_left_alone(self, db):
        """Tracking a service that cannot collect would create a permanent failure."""
        from app import main

        partial = self._honeygain_config()
        partial.pop(sorted(partial)[-1])
        await db.set_config_bulk(partial)

        assert await main._track_fully_configured_services() == 0
        assert not await db.get_deployments()

    @pytest.mark.asyncio
    async def test_it_is_idempotent_across_restarts(self, db):
        """It runs on every start; the second start must be a no-op."""
        from app import main

        await db.set_config_bulk(self._honeygain_config())
        first = await main._track_fully_configured_services()
        second = await main._track_fully_configured_services()

        assert (first, second) == (1, 0)
        assert len([d for d in await db.get_deployments() if d["slug"] == "honeygain"]) == 1

    @pytest.mark.asyncio
    async def test_it_never_overwrites_a_real_deployment(self, db):
        """That row holds the container id and the encrypted spec a redeploy needs.

        Replacing it with an empty placeholder would lose the spec, and the next
        redeploy would silently rebuild the container from the catalog instead.
        """
        from app import main

        await db.set_config_bulk(self._honeygain_config())
        await db.save_deployment(
            slug="honeygain", container_id="abc123", spec={"image": "pinned:1.2.3"}, status="running"
        )

        assert await main._track_fully_configured_services() == 0

        row = await db.get_deployment("honeygain")
        assert row["container_id"] == "abc123"
        assert row["status"] == "running"
        assert (await db.get_deployment_spec("honeygain")) == {"image": "pinned:1.2.3"}

    @pytest.mark.asyncio
    async def test_a_stopped_deployment_is_also_left_alone(self, db):
        """Status is not the question — presence of a row is."""
        from app import main

        await db.set_config_bulk(self._honeygain_config())
        await db.save_deployment(slug="honeygain", container_id="dead", status="stopped")

        assert await main._track_fully_configured_services() == 0
        assert (await db.get_deployment("honeygain"))["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_a_database_failure_does_not_stop_startup(self, db, monkeypatch):
        """It runs inside lifespan; raising there takes the whole app down."""
        from app import main

        async def _boom():
            raise RuntimeError("database is unreadable")

        monkeypatch.setattr(db, "get_config", _boom)
        assert await main._track_fully_configured_services() == 0


class TestItActuallyRunsOnStartup:
    """A backfill nobody calls fixes nothing."""

    def test_lifespan_calls_it(self):
        import ast
        import inspect
        import textwrap

        from app import main

        tree = ast.parse(textwrap.dedent(inspect.getsource(main.lifespan.__wrapped__)))
        called = {
            node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "_track_fully_configured_services" in called, (
            "the backfill is defined but never runs, so no existing install is repaired"
        )

    def test_it_runs_before_collection_is_scheduled(self):
        """Otherwise the first collection after an upgrade still misses them."""
        import inspect

        from app import main

        source = inspect.getsource(main.lifespan.__wrapped__)
        assert source.index("_track_fully_configured_services") < source.index('id="collect"')


class TestTheSavePathStillTracks:
    """The half of the bead that #187 fixed must not regress while sharing code."""

    def test_it_uses_the_shared_predicate(self):
        import ast
        import inspect
        import textwrap

        from app import main

        tree = ast.parse(textwrap.dedent(inspect.getsource(main.api_set_config)))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
            alias.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for alias in n.names
        }
        assert "fully_configured_slugs" in names, "the save path has its own copy of the completeness rule again"

    def test_it_stays_scoped_to_the_slugs_the_request_touched(self):
        """Saving one service's credentials must not sweep the whole catalog.

        Without this the shared predicate — which looks at the merged config —
        would track every already-configured service on any unrelated save.
        """
        import ast
        import inspect
        import textwrap

        from app import main

        source = textwrap.dedent(inspect.getsource(main.api_set_config))
        tree = ast.parse(source)
        loops = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.For)
            and isinstance(node.iter, ast.Call)
            and getattr(node.iter.func, "id", "") == "fully_configured_slugs"
        ]
        assert len(loops) == 1, "expected exactly one loop over fully_configured_slugs"
        guard = ast.dump(ast.Module(body=loops[0].body, type_ignores=[]))
        assert "sanitized" in guard, "the loop no longer restricts itself to the slugs this request touched"
