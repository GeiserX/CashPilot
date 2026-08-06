"""CashPilot-Desktop-xjr, server half: earnings readings need to know who took them.

The goal is the user's: pairing a Desktop uploads its history retroactively, the
Desktop then shows the complete picture, and on unlink it falls back to what that
machine earned alone.

The obvious implementation corrupts the data, and not visibly. The server does
not store *earnings* — it stores cumulative **balance readings**, and derives
earnings as clamped deltas between consecutive readings. Two samplers of the same
provider account, interleaved into one series, produce deltas between readings
that came from different samplers. The sequence oscillates, every downward step
clamps to zero, and the total comes out **systematically understated** while
looking entirely plausible.

That is worse than double counting, which at least overstates visibly.

So a reading records its ``source``, deltas are taken per ``(platform, source)``
and only then summed. That also makes ``(platform, source, date)`` the natural
idempotency key: re-pairing or a retried import overwrites a day instead of
appending a second reading for it.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app import database


# Mirrors the fixtures in test_database.py rather than importing them: they are
# module-local there, and pytest does not share fixtures across test modules
# without a conftest.
@pytest.fixture
def db_dir(tmp_path):
    db_path = tmp_path / "cashpilot.db"
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", db_path):
        yield tmp_path


@pytest.fixture
def db(db_dir):
    asyncio.run(database.init_db())
    return db_dir


class TestTheColumnExists:
    def test_readings_carry_a_source(self, db):
        async def run():
            conn = await database._get_db()
            try:
                cur = await conn.execute("PRAGMA table_info(earnings)")
                cols = {row["name"] for row in await cur.fetchall()}
            finally:
                await conn.close()
            assert "source" in cols

        asyncio.run(run())

    def test_it_defaults_to_this_server(self, db):
        """A row written by the existing collectors must not need updating."""

        async def run():
            conn = await database._get_db()
            try:
                await conn.execute(
                    "INSERT INTO earnings (platform, balance, currency, date) VALUES ('p', 1.0, 'USD', '2026-01-01')"
                )
                await conn.commit()
                cur = await conn.execute("SELECT source FROM earnings WHERE platform = 'p'")
                row = await cur.fetchone()
            finally:
                await conn.close()
            assert row["source"] == "server"

        asyncio.run(run())

    def test_one_day_per_source_is_unique(self, db):
        """The idempotency key: a retried import overwrites, never appends.

        Two readings for one (platform, source, date) would difference against
        each other and read as zero for that day.
        """

        async def run():
            import sqlite3

            conn = await database._get_db()
            try:
                await conn.execute(
                    "INSERT INTO earnings (platform, balance, currency, date, source) "
                    "VALUES ('p', 1.0, 'USD', '2026-01-01', 'desktop-a')"
                )
                await conn.commit()
                with pytest.raises(sqlite3.IntegrityError):
                    await conn.execute(
                        "INSERT INTO earnings (platform, balance, currency, date, source) "
                        "VALUES ('p', 9.0, 'USD', '2026-01-01', 'desktop-a')"
                    )
                    await conn.commit()
            finally:
                await conn.close()

        asyncio.run(run())

    def test_different_sources_may_share_a_day(self, db):
        """Two machines reporting the same day is the normal case, not a clash."""

        async def run():
            conn = await database._get_db()
            try:
                for src in ("server", "desktop-a"):
                    await conn.execute(
                        "INSERT INTO earnings (platform, balance, currency, date, source) "
                        "VALUES ('p', 1.0, 'USD', '2026-01-01', ?)",
                        (src,),
                    )
                await conn.commit()
                cur = await conn.execute("SELECT COUNT(*) AS n FROM earnings WHERE platform = 'p'")
                row = await cur.fetchone()
            finally:
                await conn.close()
            assert row["n"] == 2

        asyncio.run(run())


async def _insert(rows: list[tuple[str, float, str, str]]) -> None:
    """(platform, balance, date, source) — dates are relative days ago."""
    conn = await database._get_db()
    try:
        for platform, balance, day, source in rows:
            await conn.execute(
                "INSERT INTO earnings (platform, balance, currency, date, fx_rate_usd, source) "
                "VALUES (?, ?, 'USD', date('now', ?), 1.0, ?)",
                (platform, balance, day, source),
            )
        await conn.commit()
    finally:
        await conn.close()


class TestTwoSamplersNoLongerCorruptTheTotal:
    """The defect this whole change exists to prevent."""

    def test_interleaved_sources_are_differenced_separately(self, db):
        """Two machines watching one account, at DIFFERENT balance scales.

        The scales matter. With both sources reporting the same numbers, keying
        by platform alone still gives the right total -- the ORDER BY groups
        them and the one cross-source step clamps to zero. That made an earlier
        version of this test pass against a deliberately broken implementation,
        which is the whole reason the numbers below are far apart: the crossover
        from one source's series into the other's is POSITIVE and would be
        counted as earnings that never happened.

        desktop-a: 10 -> 12   (earned 2)
        server:    50 -> 52   (earned 2)
        correct total 4; as one series, 10,12,50,52 -> +2 +38 +2 = 42.
        """

        async def run():
            await _insert(
                [
                    ("grass", 10.0, "-4 days", "desktop-a"),
                    ("grass", 12.0, "-3 days", "desktop-a"),
                    ("grass", 50.0, "-4 days", "server"),
                    ("grass", 52.0, "-3 days", "server"),
                ]
            )
            earned = await database.get_earned_by_platform(days=30)
            assert earned["grass"] == pytest.approx(4.0)

        asyncio.run(run())

    def test_the_old_shape_would_have_understated_it(self, db):
        """Proves the defect was real, rather than asserting the fix in a vacuum.

        Differenced as ONE series ordered by date, the same readings give
        10,10,11,11,12,12 -> deltas 0,+1,0,+1,0 = 2.0 for the pair, when the two
        machines observed 2.0 EACH. The understatement is silent.
        """

        async def run():
            readings = [10.0, 10.0, 11.0, 11.0, 12.0, 12.0]
            interleaved = sum(max(0.0, b - a) for a, b in zip(readings, readings[1:], strict=False))
            per_source = 2 * sum(max(0.0, b - a) for a, b in zip([10.0, 11.0, 12.0], [11.0, 12.0], strict=False))
            assert interleaved == pytest.approx(2.0)
            assert per_source == pytest.approx(4.0)
            assert interleaved < per_source, "the old shape did not understate; the premise is wrong"

        asyncio.run(run())

    def test_a_payout_still_clamps_within_one_source(self, db):
        """The clamp must survive: a payout drops a balance and is not a loss."""

        async def run():
            await _insert(
                [
                    ("myst", 10.0, "-3 days", "server"),
                    ("myst", 2.0, "-2 days", "server"),  # paid out
                    ("myst", 5.0, "-1 days", "server"),
                ]
            )
            earned = await database.get_earned_by_platform(days=30)
            # 0 for the drop, +3 after it.
            assert earned["myst"] == pytest.approx(3.0)

        asyncio.run(run())

    def test_a_single_source_is_unchanged(self, db):
        """The common case must behave exactly as before."""

        async def run():
            await _insert([("earnapp", 1.0, "-2 days", "server"), ("earnapp", 4.0, "-1 days", "server")])
            earned = await database.get_earned_by_platform(days=30)
            assert earned["earnapp"] == pytest.approx(3.0)

        asyncio.run(run())

    def test_a_legacy_row_with_no_source_joins_the_server_series(self, db):
        """Rows written before the column existed were all this server's own.

        The column is OMITTED from the INSERT so the schema default applies --
        which is the shape a migrated legacy row actually has. An earlier version
        of this test set source='server' explicitly, so it exercised no fallback
        at all and merely duplicated the single-source case while its name
        claimed otherwise. (CodeRabbit, PR #255.)
        """

        async def run():
            conn = await database._get_db()
            try:
                await conn.execute(
                    "INSERT INTO earnings (platform, balance, currency, date, fx_rate_usd) "
                    "VALUES ('titan', 1.0, 'USD', date('now', '-2 days'), 1.0)"
                )
                await conn.execute(
                    "INSERT INTO earnings (platform, balance, currency, date, fx_rate_usd) "
                    "VALUES ('titan', 6.0, 'USD', date('now', '-1 days'), 1.0)"
                )
                await conn.commit()
            finally:
                await conn.close()
            earned = await database.get_earned_by_platform(days=30)
            assert earned["titan"] == pytest.approx(5.0)

        asyncio.run(run())

    def test_the_storage_api_can_write_a_source(self, db):
        """The schema is unusable if nothing can write a non-default source.

        upsert_earnings had no `source` parameter, so SQLite applied the default
        to every call and a paired client could never create its own series
        through the storage API. (CodeRabbit, PR #255.)
        """

        async def run():
            await database.upsert_earnings(
                platform="grass", balance=5.0, currency="USD", date="2026-01-01", fx_rate_usd=1.0, source="desktop-a"
            )
            conn = await database._get_db()
            try:
                cur = await conn.execute("SELECT source FROM earnings WHERE platform = 'grass'")
                row = await cur.fetchone()
            finally:
                await conn.close()
            assert row["source"] == "desktop-a"

        asyncio.run(run())

    def test_two_sources_upsert_independently(self, db):
        """Each machine's series is its own: writing one must not overwrite the
        other's reading for the same day."""

        async def run():
            for src, bal in (("server", 5.0), ("desktop-a", 50.0)):
                await database.upsert_earnings(
                    platform="grass", balance=bal, currency="USD", date="2026-01-01", fx_rate_usd=1.0, source=src
                )
            conn = await database._get_db()
            try:
                cur = await conn.execute(
                    "SELECT source, balance FROM earnings WHERE platform = 'grass' ORDER BY source"
                )
                rows = await cur.fetchall()
            finally:
                await conn.close()
            assert [(r["source"], r["balance"]) for r in rows] == [("desktop-a", 50.0), ("server", 5.0)]

        asyncio.run(run())

    def test_the_same_source_still_upserts(self, db):
        """The dedupe half of the key: one machine, one platform, one day."""

        async def run():
            for bal in (5.0, 9.0):
                await database.upsert_earnings(
                    platform="grass", balance=bal, currency="USD", date="2026-01-01", fx_rate_usd=1.0, source="server"
                )
            conn = await database._get_db()
            try:
                cur = await conn.execute(
                    "SELECT COUNT(*) AS n, MAX(balance) AS b FROM earnings WHERE platform = 'grass'"
                )
                row = await cur.fetchone()
            finally:
                await conn.close()
            assert row["n"] == 1
            assert row["b"] == 9.0

        asyncio.run(run())


class TestSourcesDoNotLeakAcrossPlatforms:
    def test_two_platforms_stay_separate(self, db):
        async def run():
            await _insert(
                [
                    ("a", 1.0, "-2 days", "server"),
                    ("a", 3.0, "-1 days", "server"),
                    ("b", 100.0, "-2 days", "server"),
                    ("b", 101.0, "-1 days", "server"),
                ]
            )
            earned = await database.get_earned_by_platform(days=30)
            assert earned["a"] == pytest.approx(2.0)
            assert earned["b"] == pytest.approx(1.0)

        asyncio.run(run())

    def test_the_result_is_keyed_by_platform_not_by_source(self, db):
        """Callers ask "what did Grass earn", never "what did this machine earn" —
        a provider reports one balance per account and it cannot be split."""

        async def run():
            await _insert(
                [
                    ("grass", 1.0, "-2 days", "server"),
                    ("grass", 2.0, "-1 days", "server"),
                    ("grass", 5.0, "-2 days", "desktop-a"),
                    ("grass", 7.0, "-1 days", "desktop-a"),
                ]
            )
            earned = await database.get_earned_by_platform(days=30)
            assert set(earned) == {"grass"}
            assert earned["grass"] == pytest.approx(3.0)

        asyncio.run(run())


class TestAnOldVolumeUpgradesCleanly:
    """The risky path: the column, the index and the dedupe all move together.

    `_SCHEMA` is replayed on EVERY startup, so anything declared there runs
    against whatever is already on disk. Declaring the new index there took
    init_db down with "no such column: source" on any upgraded volume -- twice,
    while writing this -- and the app does not start at all when that happens.
    """

    def test_a_pre_source_database_gains_the_column_and_index(self, db_dir):
        async def run():
            conn = await database._get_db()
            try:
                await conn.executescript("""
                    DROP TABLE IF EXISTS earnings;
                    CREATE TABLE earnings (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        platform   TEXT    NOT NULL,
                        balance    REAL    NOT NULL,
                        currency   TEXT    NOT NULL DEFAULT 'USD',
                        date       TEXT    NOT NULL,
                        created_at TEXT    NOT NULL DEFAULT (datetime('now'))
                    );
                    INSERT INTO earnings (platform, balance, currency, date)
                    VALUES ('legacy', 4.2, 'USD', '2026-01-01');
                """)
                await conn.commit()
            finally:
                await conn.close()

            await database.init_db()

            conn = await database._get_db()
            try:
                cur = await conn.execute("PRAGMA table_info(earnings)")
                cols = {row["name"] for row in await cur.fetchall()}
                cur = await conn.execute(
                    "SELECT 1 AS ok FROM sqlite_master "
                    "WHERE type = 'index' AND name = 'idx_earnings_platform_source_date'"
                )
                index_row = await cur.fetchone()
                cur = await conn.execute("SELECT source, balance FROM earnings WHERE platform = 'legacy'")
                row = await cur.fetchone()
            finally:
                await conn.close()

            assert "source" in cols
            assert index_row is not None, "the unique index was never created on an upgraded volume"
            # Backfilled truthfully: every pre-existing reading was this
            # server's own, because no other sampler could write then.
            assert row["source"] == "server"
            assert row["balance"] == 4.2

        asyncio.run(run())

    def test_duplicate_rows_predating_the_index_do_not_break_startup(self, db_dir):
        """The dedupe runs BEFORE the column exists, so its key must match the
        schema actually on disk. Referencing `source` unconditionally crashed
        init_db on precisely the volume the helper exists to rescue."""

        async def run():
            conn = await database._get_db()
            try:
                await conn.executescript("""
                    DROP TABLE IF EXISTS earnings;
                    CREATE TABLE earnings (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        platform   TEXT    NOT NULL,
                        balance    REAL    NOT NULL,
                        currency   TEXT    NOT NULL DEFAULT 'USD',
                        date       TEXT    NOT NULL,
                        created_at TEXT    NOT NULL DEFAULT (datetime('now'))
                    );
                    INSERT INTO earnings (platform, balance, currency, date)
                    VALUES ('dupe', 1.0, 'USD', '2026-01-01');
                    INSERT INTO earnings (platform, balance, currency, date)
                    VALUES ('dupe', 2.0, 'USD', '2026-01-01');
                """)
                await conn.commit()
            finally:
                await conn.close()

            await database.init_db()  # must not raise

            conn = await database._get_db()
            try:
                cur = await conn.execute("SELECT balance FROM earnings WHERE platform = 'dupe'")
                rows = await cur.fetchall()
            finally:
                await conn.close()
            # The highest id survives: the most recent write, which is what an
            # upsert would have left had the index existed all along.
            assert len(rows) == 1
            assert rows[0]["balance"] == 2.0

        asyncio.run(run())


class TestTheLegacyIndexIsRemovedOnUpgrade:
    """The bug my own upgrade test could not see.

    It built a legacy table with NO indexes, so it never noticed that a real
    upgraded volume keeps ``idx_earnings_platform_date`` -- which still forbids
    two sources for one (platform, date) and would silently defeat the entire
    change for every existing install. Creating the replacement is not enough;
    the old constraint has to be dropped. (CodeRabbit, PR #255.)
    """

    def _legacy_volume(self):
        async def build():
            conn = await database._get_db()
            try:
                await conn.executescript("""
                    DROP TABLE IF EXISTS earnings;
                    CREATE TABLE earnings (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        platform   TEXT    NOT NULL,
                        balance    REAL    NOT NULL,
                        currency   TEXT    NOT NULL DEFAULT 'USD',
                        date       TEXT    NOT NULL,
                        created_at TEXT    NOT NULL DEFAULT (datetime('now'))
                    );
                    CREATE UNIQUE INDEX idx_earnings_platform_date
                        ON earnings (platform, date);
                """)
                await conn.commit()
            finally:
                await conn.close()

        return build

    def test_the_old_index_is_gone_after_migration(self, db_dir):
        async def run():
            await self._legacy_volume()()
            await database.init_db()
            conn = await database._get_db()
            try:
                cur = await conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_earnings_platform%'"
                )
                names = {row["name"] for row in await cur.fetchall()}
            finally:
                await conn.close()
            assert "idx_earnings_platform_source_date" in names
            assert "idx_earnings_platform_date" not in names, (
                "the legacy index survived and still forbids two sources per day"
            )

        asyncio.run(run())

    def test_two_sources_can_write_one_day_after_upgrading(self, db_dir):
        """The behaviour the dropped index was blocking, end to end."""

        async def run():
            await self._legacy_volume()()
            await database.init_db()
            for src, bal in (("server", 1.0), ("desktop-a", 100.0)):
                await database.upsert_earnings(
                    platform="grass", balance=bal, currency="USD", date="2026-01-01", fx_rate_usd=1.0, source=src
                )
            conn = await database._get_db()
            try:
                cur = await conn.execute("SELECT COUNT(*) AS n FROM earnings WHERE platform = 'grass'")
                row = await cur.fetchone()
            finally:
                await conn.close()
            assert row["n"] == 2, "an upgraded volume still rejects a second source for the same day"

        asyncio.run(run())
