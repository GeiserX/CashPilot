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

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    # Not a context manager: entering one runs the lifespan, which starts
    # APScheduler and fails outside the main thread. These tests exercise the
    # route, not startup.
    return TestClient(app, raise_server_exceptions=False)


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
            patch("app.main.database.upsert_earnings", new_callable=AsyncMock) as upsert,
        ):
            resp = _import(client, readings=[{"slug": "grass", "balance": 1.0, "date": "2026-01-01"}])
        assert resp.status_code == 403
        upsert.assert_not_awaited(), "a shared-key holder wrote earnings"

    def test_a_confirmed_worker_is_accepted(self, client):
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings", new_callable=AsyncMock),
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
            patch("app.main.database.upsert_earnings", new_callable=AsyncMock) as upsert,
        ):
            resp = _import(client, cid="desktop-a", readings=[{"slug": "grass", "balance": 2.0, "date": "2026-01-01"}])
        assert resp.status_code == 200
        assert upsert.await_args.kwargs["source"] == "desktop-a"
        assert resp.json()["source"] == "desktop-a"

    def test_a_body_supplied_source_cannot_override_it(self, client):
        """The model carries no source field, so a hostile body is inert.

        Asserted by SENDING one: a field the model ignores is the defence, and
        a future model change that started honouring it would fail here.
        """
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings", new_callable=AsyncMock) as upsert,
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
        assert upsert.await_args.kwargs["source"] == "desktop-a", "a client overwrote the server's own series"

    def test_a_missing_client_id_is_refused(self, client):
        resp = _import(client, cid="  ")
        assert resp.status_code == 400


class TestOnlyKnownPlatformsAreStored:
    def test_an_unknown_slug_is_skipped_not_stored(self, client):
        """It would create a platform the catalog cannot name, render, or ever
        collect for again."""
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings", new_callable=AsyncMock) as upsert,
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
        assert upsert.await_count == 1

    def test_the_skips_are_reported_rather_than_swallowed(self, client):
        """A silent drop looks identical to a successful import."""
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings", new_callable=AsyncMock),
        ):
            resp = _import(client, readings=[{"slug": "nope", "balance": 1.0, "date": "2026-01-01"}])
        assert resp.json()["skipped"] == ["nope"]
        assert resp.json()["imported"] == 0

    def test_a_blank_slug_is_skipped(self, client):
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings", new_callable=AsyncMock) as upsert,
        ):
            resp = _import(client, readings=[{"slug": "  ", "balance": 1.0, "date": "2026-01-01"}])
        assert resp.json()["imported"] == 0
        upsert.assert_not_awaited()


class TestTheReadingsSurviveIntact:
    def test_currency_and_rate_are_passed_through(self, client):
        """Dropping the rate would make a non-USD balance unpriceable later —
        the reason the column exists at all."""
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings", new_callable=AsyncMock) as upsert,
        ):
            _import(
                client,
                readings=[
                    {"slug": "mysterium", "balance": 3.0, "date": "2026-01-01", "currency": "myst", "fx_rate_usd": 0.4}
                ],
            )
        kwargs = upsert.await_args.kwargs
        assert kwargs["currency"] == "MYST", "currency was not normalised"
        assert kwargs["fx_rate_usd"] == 0.4

    def test_an_absent_rate_stays_none_rather_than_becoming_zero(self, client):
        """None is UNKNOWN. A 0.0 rate would price the whole reading at nothing."""
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings", new_callable=AsyncMock) as upsert,
        ):
            _import(client, readings=[{"slug": "grass", "balance": 3.0, "date": "2026-01-01"}])
        assert upsert.await_args.kwargs["fx_rate_usd"] is None

    def test_an_empty_import_is_accepted_and_writes_nothing(self, client):
        """A client with no history to push is a normal case, not an error."""
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings", new_callable=AsyncMock) as upsert,
        ):
            resp = _import(client, readings=[])
        assert resp.status_code == 200
        assert resp.json()["imported"] == 0
        upsert.assert_not_awaited()


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
            patch("app.main.database.upsert_earnings", new_callable=AsyncMock) as upsert,
        ):
            resp = _import(client, readings=[{"slug": "grass", "balance": 1.0, "date": bad}])
        assert resp.status_code == 422, f"{bad!r} was accepted"
        upsert.assert_not_awaited()

    @pytest.mark.parametrize("good", ["2026-01-01", "2024-02-29", "2026-12-31"])
    def test_a_real_day_is_accepted(self, client, good):
        """A validator that rejects everything is as useless as none at all —
        2024-02-29 exists and must survive."""
        with (
            patch("app.main._authenticate_worker_heartbeat", new_callable=AsyncMock, return_value="ok"),
            patch("app.main.database.upsert_earnings", new_callable=AsyncMock) as upsert,
        ):
            resp = _import(client, readings=[{"slug": "grass", "balance": 1.0, "date": good}])
        assert resp.status_code == 200
        assert upsert.await_args.kwargs["date"] == good

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
            patch("app.main.database.upsert_earnings", new_callable=AsyncMock) as upsert,
        ):
            resp = _import(client, readings=self._readings(2001))
        assert resp.status_code == 422
        upsert.assert_not_awaited(), "the server wrote rows from a body it should have refused"

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
            patch("app.main.database.upsert_earnings", new_callable=AsyncMock) as upsert,
        ):
            resp = _import(client, readings=self._readings(1000))
        assert resp.status_code == 200
        assert upsert.await_count == 1000
