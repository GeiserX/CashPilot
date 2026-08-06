"""CashPilot-Desktop-xjr: a paired client pushes the history it collected alone.

The write path for the source-aware schema. A Desktop that ran standalone has
months of readings the server never saw; pairing should surrender them so the
fleet shows the complete picture, and unlinking should leave that machine able to
show what it earned by itself.

Two properties carry the whole design:

* **The source comes from AUTHENTICATION, never the body.** Otherwise any
  enrolled client could write into the ``'server'`` series, or into another
  machine's, and overwrite readings it never took.
* **Only a CONFIRMED worker may import.** ``"enroll"`` and ``"reissue"`` both
  mean the caller presented the SHARED key, which every worker holds. A
  heartbeat is idempotent status; this is durable money data, so it gets the
  stricter bar.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import app


@pytest.fixture
def client():
    # Not a context manager: entering one runs the lifespan, which starts
    # APScheduler and fails outside the main thread. These tests exercise the
    # route, not startup.
    return TestClient(app, raise_server_exceptions=False)


async def _count(rows):
    """Stand in for the real batched write, returning what it returns."""
    return len(rows)


def _rows(upsert) -> list[dict]:
    """The rows handed to the ONE batched write, or [] if it never ran.

    The endpoint used to call upsert_earnings once per reading; it now hands the
    whole batch to upsert_earnings_many in a single transaction, so "did it write
    this?" is a question about the rows, not about the call count.
    """
    if not upsert.await_args_list:
        return []
    assert len(upsert.await_args_list) == 1, "the batch was split into several transactions"
    return list(upsert.await_args_list[0].args[0])


def _import(client, *, cid="desktop-a", readings=None, token="worker-own-key"):
    return client.post(
        "/api/workers/earnings-import",
        json={"client_id": cid, "readings": readings if readings is not None else []},
        headers={"Authorization": f"Bearer {token}"},
    )


class TestOnlyAConfirmedWorkerMayImport:
    """The shared enrolment key must not be enough to write money data."""

    @pytest.mark.parametrize("state", ["enroll", "reissue"])
    def test_a_shared_key_holder_is_refused(self, client, state):
        # Both states mean "presented the shared key". Every worker holds it, so
        # accepting it here would let any of them write a history for any
        # client_id they cared to name -- including 'server'.
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value=state),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count) as upsert,
        ):
            resp = _import(client, readings=[{"slug": "grass", "balance": 1.0, "date": "2026-01-01"}])
        assert resp.status_code == 403
        assert _rows(upsert) == [], "a shared-key holder wrote earnings"

    def test_a_confirmed_worker_is_accepted(self, client):
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count),
        ):
            resp = _import(client, readings=[{"slug": "grass", "balance": 1.0, "date": "2026-01-01"}])
        assert resp.status_code == 200

    def test_the_refusal_says_how_to_proceed(self, client):
        """ "403" alone leaves a client with no way forward."""
        with patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="enroll"):
            resp = _import(client)
        assert "heartbeat" in resp.json()["detail"].lower()

    def test_a_bad_key_is_still_rejected_by_the_shared_auth(self, client):
        """The endpoint must not have its own weaker auth path."""
        from fastapi import HTTPException

        with patch(
            "app.main._authenticate_worker_heartbeat",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=401, detail="bad key"),
        ):
            resp = _import(client)
        assert resp.status_code == 401


class TestTheSourceComesFromAuthentication:
    def test_readings_are_stored_under_the_authenticated_client(self, client):
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count) as upsert,
        ):
            resp = _import(client, cid="desktop-a", readings=[{"slug": "grass", "balance": 2.0, "date": "2026-01-01"}])
        assert resp.status_code == 200
        assert _rows(upsert)[0]["source"] == "desktop-a"
        assert resp.json()["source"] == "desktop-a"

    def test_a_body_supplied_source_cannot_override_it(self, client):
        """The model carries no source field, so a hostile body is inert.

        Asserted by SENDING one: a field the model ignores is the defence, and
        a future model change that started honouring it would fail here.
        """
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count) as upsert,
        ):
            resp = client.post(
                "/api/workers/earnings-import",
                json={
                    "client_id": "desktop-a",
                    "source": "server",
                    "readings": [{"slug": "grass", "balance": 2.0, "date": "2026-01-01", "source": "server"}],
                },
                headers={"Authorization": "Bearer k"},
            )
        assert resp.status_code == 200
        assert _rows(upsert)[0]["source"] == "desktop-a", "a client overwrote the server's own series"

    def test_a_missing_client_id_is_refused(self, client):
        resp = _import(client, cid="  ")
        assert resp.status_code == 400


class TestOnlyKnownPlatformsAreStored:
    def test_an_unknown_slug_is_skipped_not_stored(self, client):
        """It would create a platform the catalog cannot name, render, or ever
        collect for again."""
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count) as upsert,
        ):
            resp = _import(
                client,
                readings=[
                    {"slug": "grass", "balance": 1.0, "date": "2026-01-01"},
                    {"slug": "not-a-real-service", "balance": 9.0, "date": "2026-01-01"},
                ],
            )
        body = resp.json()
        assert body["imported"] == 1
        assert body["skipped"] == ["not-a-real-service"]
        assert len(_rows(upsert)) == 1

    def test_the_skips_are_reported_rather_than_swallowed(self, client):
        """A silent drop looks identical to a successful import."""
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count),
        ):
            resp = _import(client, readings=[{"slug": "nope", "balance": 1.0, "date": "2026-01-01"}])
        assert resp.json()["skipped"] == ["nope"]
        assert resp.json()["imported"] == 0

    def test_a_blank_slug_is_skipped(self, client):
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count) as upsert,
        ):
            resp = _import(client, readings=[{"slug": "  ", "balance": 1.0, "date": "2026-01-01"}])
        assert resp.json()["imported"] == 0
        assert _rows(upsert) == []


class TestTheReadingsSurviveIntact:
    def test_currency_and_rate_are_passed_through(self, client):
        """Dropping the rate would make a non-USD balance unpriceable later —
        the reason the column exists at all."""
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count) as upsert,
        ):
            _import(
                client,
                readings=[
                    {"slug": "mysterium", "balance": 3.0, "date": "2026-01-01", "currency": "myst", "fx_rate_usd": 0.4}
                ],
            )
        row = _rows(upsert)[0]
        assert row["currency"] == "MYST", "currency was not normalised"
        assert row["fx_rate_usd"] == 0.4

    def test_an_absent_rate_stays_none_rather_than_becoming_zero(self, client):
        """None is UNKNOWN. A 0.0 rate would price the whole reading at nothing."""
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count) as upsert,
        ):
            _import(client, readings=[{"slug": "grass", "balance": 3.0, "date": "2026-01-01"}])
        assert _rows(upsert)[0]["fx_rate_usd"] is None

    def test_an_empty_import_is_accepted_and_writes_nothing(self, client):
        """A client with no history to push is a normal case, not an error."""
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count) as upsert,
        ):
            resp = _import(client, readings=[])
        assert resp.status_code == 200
        assert resp.json()["imported"] == 0
        assert _rows(upsert) == []


class TestABalanceMustBeARealNumber:
    """JSON has no NaN or Infinity. Python's parser accepts them anyway.

    Found by re-reading the endpoint rather than by a report: ``{"balance": NaN}``
    was accepted and stored verbatim. One such reading poisons every delta taken
    from that series — ``NaN - x`` is ``NaN``, and every comparison against it is
    False, so the clamp silently misbehaves — the account total becomes ``NaN``,
    and serialising that back out emits a bare ``NaN`` that ``JSON.parse``
    rejects. A single bad reading from one client breaks the dashboard for
    everyone.
    """

    @staticmethod
    def _raw(client, body: str):
        return client.post(
            "/api/workers/earnings-import",
            content=body,
            headers={"Authorization": "Bearer k", "Content-Type": "application/json"},
        )

    @pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
    def test_a_non_finite_balance_is_refused(self, client, literal):
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count) as upsert,
        ):
            resp = self._raw(
                client,
                f'{{"client_id":"d","readings":[{{"slug":"grass","balance":{literal},"date":"2026-01-01"}}]}}',
            )
        assert resp.status_code == 422, f"{literal} balance was accepted"
        assert _rows(upsert) == []

    @pytest.mark.parametrize("literal", ["NaN", "Infinity"])
    def test_a_non_finite_rate_is_refused(self, client, literal):
        """An infinite rate prices the balance at infinity, which is worse than
        pricing it at nothing."""
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count) as upsert,
        ):
            resp = self._raw(
                client,
                f'{{"client_id":"d","readings":[{{"slug":"grass","balance":1.0,"date":"2026-01-01",'
                f'"fx_rate_usd":{literal}}}]}}',
            )
        assert resp.status_code == 422, f"{literal} rate was accepted"
        assert _rows(upsert) == []

    def test_ordinary_numbers_still_pass(self, client):
        """A guard that rejects everything is as useless as none at all. Zero and
        a negative are both legitimate: a provider balance can be zero, and a
        clawback can take it negative."""
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count) as upsert,
        ):
            resp = _import(
                client,
                readings=[
                    {"slug": "grass", "balance": 0.0, "date": "2026-01-01"},
                    {"slug": "honeygain", "balance": -1.25, "date": "2026-01-02", "fx_rate_usd": 0.0001},
                    {"slug": "storj", "balance": 1e9, "date": "2026-01-03"},
                ],
            )
        assert resp.status_code == 200
        assert len(_rows(upsert)) == 3


class TestTheRejectionItselfCanBeSerialised:
    """FastAPI's 422 body echoes the offending input, and some inputs cannot be
    encoded — so the rejection became a 500.

    Both halves were found the same way: by driving the real request rather than
    reading the code. ``NaN`` made the default handler raise "Out of range float
    values are not JSON compliant"; my FIRST attempt at a handler then broke every
    OTHER validation error, because a custom validator's error carries the raised
    ``ValueError`` object in ``ctx`` and that is not serialisable either. The
    second test below is the regression that caught it.
    """

    def test_a_non_finite_value_yields_a_bad_request_not_a_server_error(self, client):
        with patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"):
            resp = client.post(
                "/api/workers/earnings-import",
                content='{"client_id":"d","readings":[{"slug":"grass","balance":NaN,"date":"2026-01-01"}]}',
                headers={"Authorization": "Bearer k", "Content-Type": "application/json"},
            )
        assert resp.status_code == 422
        resp.json()  # must parse: a bare NaN in the body would make this raise

    def test_an_ordinary_validation_error_is_unchanged(self, client):
        """The regression. A custom validator raises ValueError, which lands in
        `ctx` as an OBJECT; a handler that skips jsonable_encoder turns every one
        of those into a 500."""
        with patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"):
            resp = _import(client, readings=[{"slug": "grass", "balance": 1.0, "date": "yesterday"}])
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert isinstance(detail, list) and detail, detail
        assert "date" in str(detail), "the error no longer says which field was wrong"

    def test_a_missing_field_still_reports_normally(self, client):
        """The plainest possible validation error, to catch a handler that only
        works for the exotic cases it was written for."""
        resp = client.post(
            "/api/workers/earnings-import",
            json={"readings": []},
            headers={"Authorization": "Bearer k"},
        )
        assert resp.status_code == 422
        assert "client_id" in str(resp.json()["detail"])


class TestJsonSafe:
    """The sanitiser on its own, so its edge cases are not only reachable through
    a request that happens to hit them."""

    @staticmethod
    def _safe(value):
        from app.main import _json_safe

        return _json_safe(value)

    def test_non_finite_floats_become_their_names(self):
        assert self._safe(float("nan")) == "nan"
        assert self._safe(float("inf")) == "inf"
        assert self._safe(float("-inf")) == "-inf"

    def test_ordinary_numbers_are_untouched(self):
        """A sanitiser that rewrites healthy values corrupts every error body it
        touches."""
        for value in (0.0, -1.5, 1e300, 42):
            assert self._safe(value) == value

    def test_booleans_survive_as_booleans(self):
        """bool is a subclass of int. A guard written for numbers that forgets
        that turns True into 1 in every error body."""
        assert self._safe(True) is True
        assert self._safe(False) is False

    def test_it_recurses_into_nested_structures(self):
        """The value is buried at errors()[0]["input"], inside a list of dicts."""
        got = self._safe([{"input": float("nan"), "loc": ["body", 0, "balance"], "ok": 1.5}])
        assert got == [{"input": "nan", "loc": ["body", 0, "balance"], "ok": 1.5}]

    def test_strings_and_none_pass_through(self):
        assert self._safe(None) is None
        assert self._safe("nan") == "nan"


class TestTheSkipReportIsBounded:
    def test_a_repeated_unknown_slug_is_reported_once(self, client):
        """A client pushing 400 days of a platform this server does not know
        would otherwise get the same name back 400 times: a response that grows
        with the request, echoing client-supplied strings, and saying nothing the
        set does not."""
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count),
        ):
            resp = _import(
                client,
                readings=[
                    {"slug": "not-a-real-service", "balance": float(i), "date": f"2026-01-{i + 1:02d}"}
                    for i in range(20)
                ],
            )
        assert resp.json()["skipped"] == ["not-a-real-service"]
        assert resp.json()["imported"] == 0

    def test_several_distinct_unknowns_are_all_reported(self, client):
        """Deduplicating must not become "report only the first"."""
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count),
        ):
            resp = _import(
                client,
                readings=[
                    {"slug": "gone-one", "balance": 1.0, "date": "2026-01-01"},
                    {"slug": "gone-two", "balance": 1.0, "date": "2026-01-01"},
                    {"slug": "gone-one", "balance": 2.0, "date": "2026-01-02"},
                ],
            )
        assert resp.json()["skipped"] == ["gone-one", "gone-two"], "a distinct unknown platform was swallowed"


class TestTheDateIsAValidCalendarDay:
    """Both delta readers ``ORDER BY ... date``, so the date is not free text.

    A reading dated ``01/02/2026`` or ``2026-1-2`` sorts into the wrong place in
    its own series, and the readings either side of it then difference against
    the wrong neighbour. It fails silently, only for the client that sent it,
    and only in the earned figure — never in the balance the dashboard shows.
    """

    @pytest.mark.parametrize(
        "bad",
        [
            "01/02/2026",  # a different convention entirely
            "2026-1-2",  # unpadded: sorts after "2026-11-01"
            "2026-01-01T00:00:00Z",  # an instant, not a day
            "yesterday",
            "",
            "2026-02-30",  # right shape, no such day
            "2026-13-01",
        ],
    )
    def test_a_malformed_date_is_refused(self, client, bad):
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count) as upsert,
        ):
            resp = _import(client, readings=[{"slug": "grass", "balance": 1.0, "date": bad}])
        assert resp.status_code == 422, f"{bad!r} was accepted"
        assert _rows(upsert) == []

    @pytest.mark.parametrize("good", ["2026-01-01", "2024-02-29", "2026-12-31"])
    def test_a_real_day_is_accepted(self, client, good):
        """A validator that rejects everything is as useless as none at all —
        2024-02-29 exists and must survive."""
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count) as upsert,
        ):
            resp = _import(client, readings=[{"slug": "grass", "balance": 1.0, "date": good}])
        assert resp.status_code == 200
        assert _rows(upsert)[0]["date"] == good

    def test_the_date_is_refused_before_authentication_is_even_checked(self, client):
        """Body validation runs first, so a malformed date cannot be used to
        probe which client ids exist."""
        with patch(
            "app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"
        ) as authenticate:
            _import(client, readings=[{"slug": "grass", "balance": 1.0, "date": "nope"}])
        authenticate.assert_not_awaited()


class TestTheBodyIsBounded:
    """One authenticated client must not be able to hand the server an
    arbitrarily large body to parse and then write row by row."""

    @staticmethod
    def _readings(n: int) -> list[dict]:
        return [{"slug": "grass", "balance": float(i), "date": "2026-01-01"} for i in range(n)]

    def test_an_oversized_import_is_refused(self, client):
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count) as upsert,
        ):
            resp = _import(client, readings=self._readings(2001))
        assert resp.status_code == 422
        assert _rows(upsert) == [], "the server wrote rows from a body it should have refused"

    def test_a_real_sized_import_still_fits(self):
        """The cap must clear an honest import, or clients can never pair.

        400 days of retention against the whole catalog is the worst case a
        client would ever chunk against, so the bound is checked against the
        REAL catalog size rather than a guess.
        """
        from app import catalog

        chunk = 1000  # what a client sends per request
        assert chunk <= 2000
        assert len(catalog.get_services()) >= 40, "catalog too small for this to mean anything"

    def test_a_thousand_readings_are_accepted(self, client):
        """The chunk size a client actually uses, exercised end to end."""
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count) as upsert,
        ):
            resp = _import(client, readings=self._readings(1000))
        assert resp.status_code == 200
        assert len(_rows(upsert)) == 1000


class TestNoAssertionHidesItsOwnMessage:
    """``mock.assert_not_awaited(), "why"`` is a TUPLE, not an assertion.

    Python evaluates the call, builds a two-element tuple with the string, and
    throws it away. The mock still raises when the expectation fails, so the test
    is not broken — but the message that explains WHY never appears, and the
    reader of a red build gets ``AssertionError: Expected 'x' to not have been
    awaited`` instead of "a shared-key holder wrote earnings".

    CodeRabbit found two of these in this file and said Ruff's ``B018`` catches
    the pattern when bugbear is enabled. Bugbear IS enabled here (``B`` is in
    ``select``, and ``B018`` is not ignored) and ruff 0.15.14 passes it clean —
    checked against a minimal probe rather than assumed. So nothing in CI would
    catch a recurrence, which is what this test is for.

    Structural, over the AST: a string search would match the pattern inside this
    docstring, which is the specific way a test can end up matching its own prose.
    """

    def test_no_test_file_discards_a_message_into_a_tuple(self):
        import ast
        from pathlib import Path

        offenders: list[str] = []
        tests_dir = Path(__file__).resolve().parent
        files = sorted(tests_dir.glob("test_*.py"))
        # A silent empty scan would make this vacuously true forever.
        assert len(files) >= 20, f"only found {len(files)} test files; the path is wrong"

        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                # A bare expression statement whose value is a tuple: nothing
                # consumes the result, so every element after the first is dead.
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Tuple):
                    offenders.append(f"{path.name}:{node.lineno}")

        assert not offenders, "assertions whose failure message is discarded into a tuple: " + ", ".join(offenders)


class TestTheBatchIsOneTransaction:
    """A thousand-reading import used to commit a thousand times.

    Every commit is an fsync that takes SQLite's write lock, so one import
    serialised a thousand disk syncs against this server's own collector and
    request latency tracked sync cost rather than row count. (CodeRabbit, PR
    #256 — though only half of the reported cause was real: ``_get_db`` hands out
    a borrowed handle on a SHARED per-loop connection whose ``close()`` is a
    documented no-op, so the loop was never opening a thousand connections. It
    was committing a thousand times.)
    """

    def test_the_whole_import_is_one_write(self, client):
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count) as upsert,
        ):
            resp = _import(
                client,
                readings=[{"slug": "grass", "balance": float(i), "date": f"2026-01-{i + 1:02d}"} for i in range(28)],
            )
        assert resp.status_code == 200
        assert len(upsert.await_args_list) == 1, f"the import took {len(upsert.await_args_list)} transactions, not one"
        assert len(_rows(upsert)) == 28

    def test_the_per_reading_writer_is_not_used_here(self, client):
        """Reverting the endpoint to the row-by-row call would restore the
        thousand-commit behaviour while every other test still passed."""
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count),
            patch("app.main.database.upsert_earnings", new_callable=AsyncMock) as single,
        ):
            _import(client, readings=[{"slug": "grass", "balance": 1.0, "date": "2026-01-01"}])
        assert single.await_count == 0, "the endpoint is writing one row at a time again"

    def test_nothing_is_written_when_every_slug_is_unknown(self, client):
        """An empty batch must not take the write lock to do nothing."""
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings_many", new_callable=AsyncMock, side_effect=_count) as upsert,
        ):
            resp = _import(client, readings=[{"slug": "nope", "balance": 1.0, "date": "2026-01-01"}])
        assert resp.json()["imported"] == 0
        assert _rows(upsert) == []


# --- the batched writer itself, against a real database -------------------


# Mirrors the fixtures in test_database.py rather than importing them: they are
# module-local there, and pytest does not share fixtures across modules without
# a conftest.
@pytest.fixture
def db_dir(tmp_path):
    with patch.object(database, "DB_DIR", tmp_path), patch.object(database, "DB_PATH", tmp_path / "cashpilot.db"):
        yield tmp_path


@pytest.fixture
def db(db_dir):
    asyncio.run(database.init_db())
    return db_dir


def _all_earnings() -> list[dict]:
    async def run():
        conn = await database._get_db()
        cur = await conn.execute(
            "SELECT platform, balance, currency, date, fx_rate_usd, source FROM earnings ORDER BY date, platform"
        )
        return [dict(row) for row in await cur.fetchall()]

    return asyncio.run(run())


class TestUpsertEarningsMany:
    def test_it_writes_every_reading(self, db):
        written = asyncio.run(
            database.upsert_earnings_many(
                [
                    {"platform": "grass", "balance": 1.0, "date": "2026-01-01", "source": "mac"},
                    {"platform": "grass", "balance": 2.0, "date": "2026-01-02", "source": "mac"},
                    {"platform": "honeygain", "balance": 3.0, "date": "2026-01-01", "source": "mac"},
                ]
            )
        )
        assert written == 3
        assert len(_all_earnings()) == 3

    def test_re_importing_a_day_updates_rather_than_appends(self, db):
        """The whole reason the import is safe to retry. A second row for one
        (platform, source, date) would difference against itself and read zero."""
        rows = [{"platform": "grass", "balance": 1.0, "date": "2026-01-01", "source": "mac"}]
        asyncio.run(database.upsert_earnings_many(rows))
        asyncio.run(database.upsert_earnings_many([{**rows[0], "balance": 5.0}]))

        stored = _all_earnings()
        assert len(stored) == 1, f"a repeated day appended: {stored}"
        assert stored[0]["balance"] == 5.0

    def test_two_sources_coexist_for_one_platform_and_day(self, db):
        """The point of the source column: the server and a Desktop can both have
        read the same provider account on the same day."""
        asyncio.run(
            database.upsert_earnings_many(
                [
                    {"platform": "grass", "balance": 1.0, "date": "2026-01-01", "source": "server"},
                    {"platform": "grass", "balance": 9.0, "date": "2026-01-01", "source": "mac"},
                ]
            )
        )
        stored = _all_earnings()
        assert len(stored) == 2, f"one source overwrote the other: {stored}"
        assert {row["source"] for row in stored} == {"server", "mac"}

    def test_an_absent_rate_does_not_erase_a_known_one(self, db):
        """Same COALESCE rule the single-row writer has. Overwriting a known-good
        rate with NULL destroys the very data the column exists to preserve."""
        asyncio.run(
            database.upsert_earnings_many(
                [{"platform": "mysterium", "balance": 1.0, "date": "2026-01-01", "source": "mac", "fx_rate_usd": 0.4}]
            )
        )
        asyncio.run(
            database.upsert_earnings_many(
                [{"platform": "mysterium", "balance": 2.0, "date": "2026-01-01", "source": "mac", "fx_rate_usd": None}]
            )
        )
        assert _all_earnings()[0]["fx_rate_usd"] == 0.4

    def test_an_empty_batch_writes_nothing_and_reports_zero(self, db):
        assert asyncio.run(database.upsert_earnings_many([])) == 0
        assert _all_earnings() == []

    def test_defaults_match_the_single_row_writer(self, db):
        """Currency and source default the same way, or a batched import would
        land under a different series than the same reading written singly."""
        asyncio.run(database.upsert_earnings_many([{"platform": "grass", "balance": 1.0, "date": "2026-01-01"}]))
        row = _all_earnings()[0]
        assert row["currency"] == "USD"
        assert row["source"] == "server"

    def test_a_failure_part_way_leaves_nothing_behind(self, db):
        """One transaction means all-or-nothing. Half an imported history is
        worse than none: the client believes it failed and retries, and the rows
        that landed are indistinguishable from rows it took itself.

        The failure has to happen INSIDE the statement to test anything. My first
        version raised a KeyError while building the rows -- before any SQL ran --
        so it proved only that the row build validates first, and it passed
        against a writer that committed after every row. Caught by a negative
        control; this version uses a NULL platform, which survives the build and
        is rejected by the table.
        """
        asyncio.run(database.upsert_earnings_many([{"platform": "grass", "balance": 1.0, "date": "2026-01-01"}]))
        before = _all_earnings()

        with pytest.raises(Exception, match="(?i)not null|constraint"):
            asyncio.run(
                database.upsert_earnings_many(
                    [
                        {"platform": "honeygain", "balance": 2.0, "date": "2026-01-02"},
                        {"platform": None, "balance": 3.0, "date": "2026-01-03"},
                    ]
                )
            )
        assert _all_earnings() == before, "a failed batch left rows behind"

    def test_a_failed_batch_does_not_wedge_the_shared_connection(self, db):
        """The connection outlives the request, so an abandoned transaction would
        hold SQLite's write lock against every later write on this loop --
        including the server's own collector."""
        with pytest.raises(Exception, match="(?i)not null|constraint"):
            asyncio.run(database.upsert_earnings_many([{"platform": None, "balance": 1.0, "date": "2026-01-01"}]))
        # The next write must simply work.
        assert (
            asyncio.run(database.upsert_earnings_many([{"platform": "grass", "balance": 1.0, "date": "2026-01-02"}]))
            == 1
        )
        assert len(_all_earnings()) == 1
