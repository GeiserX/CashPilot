"""The worker must be able to report that it cannot report.

A worker whose heartbeats stopped landing kept passing its container
healthcheck, because that check was a TCP connect to its own port -- true of a
process that is listening and completely disconnected. Two hosts ran like that
for 42 hours: `docker ps` said healthy, the fleet page said offline, and nothing
reconciled the two.

These tests pin the two behaviours that close that gap: /api/health degrades
after a sustained run of missed heartbeats, and a name-resolution failure is
explained once with the cause that actually produces it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import threading
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import httpx  # noqa: E402
import pytest  # noqa: E402

try:
    from fastapi.testclient import TestClient  # noqa: E402
except ImportError:  # pragma: no cover - exercised only without fastapi
    pytest.skip("fastapi not installed", allow_module_level=True)

from app import worker_api  # noqa: E402


@asynccontextmanager
async def _noop_lifespan(_app):
    yield


def _client():
    worker_api.app.router.lifespan_context = _noop_lifespan
    return TestClient(worker_api.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _reset_heartbeat_state():
    """Module-level counters leak between tests otherwise."""
    before = (
        worker_api._consecutive_heartbeat_failures,
        worker_api._link_hint_logged,
        worker_api._last_heartbeat,
        worker_api._last_error,
        worker_api._last_heartbeat_ok,
    )
    yield
    (
        worker_api._consecutive_heartbeat_failures,
        worker_api._link_hint_logged,
        worker_api._last_heartbeat,
        worker_api._last_error,
        worker_api._last_heartbeat_ok,
    ) = before


class TestHealthReflectsHeartbeat:
    def test_healthy_shape_is_unchanged(self):
        """The healthy response must stay byte-identical to the old one.

        Anything already parsing this endpoint keeps working; only the degraded
        path adds fields.
        """
        worker_api._consecutive_heartbeat_failures = 0
        resp = _client().get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "worker": worker_api.WORKER_NAME}

    def test_still_ok_below_the_threshold(self):
        """A UI restart or a blip must not flap the container to unhealthy."""
        worker_api._consecutive_heartbeat_failures = worker_api._HEARTBEAT_FAILURES_UNHEALTHY_AFTER - 1
        with patch.object(worker_api, "UI_URL", "http://cashpilot-ui:8080"):
            resp = _client().get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_degrades_after_sustained_failures(self):
        worker_api._consecutive_heartbeat_failures = worker_api._HEARTBEAT_FAILURES_UNHEALTHY_AFTER
        worker_api._last_heartbeat = "never"
        worker_api._last_error = "connection failed"
        with patch.object(worker_api, "UI_URL", "http://cashpilot-ui:8080"):
            resp = _client().get("/api/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["last_heartbeat"] == "never"
        assert body["error"] == "connection failed"
        assert body["consecutive_failures"] == str(worker_api._HEARTBEAT_FAILURES_UNHEALTHY_AFTER)

    def test_no_ui_configured_is_not_degraded(self):
        """A worker with nowhere to report is doing what it was told.

        Without this guard every standalone worker would report unhealthy
        forever, which trains operators to ignore the signal.
        """
        worker_api._consecutive_heartbeat_failures = 99
        worker_api._last_heartbeat_ok = 0.0  # maximally stale, still ok
        with patch.object(worker_api, "UI_URL", ""):
            resp = _client().get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_a_hung_cycle_degrades_via_staleness(self):
        """A cycle that never RETURNS must still become visible.

        A payload helper blocking forever (statvfs on a wedged /data mount, a
        wedged Docker socket) freezes the loop: no exception, no next cycle, so
        the failure counter stays at ZERO. The frozen last-success stamp is the
        only signal that survives a hang — this is the 42-hour false-healthy
        with a different mechanism.
        """
        worker_api._consecutive_heartbeat_failures = 0  # the hang's signature
        worker_api._last_heartbeat_ok = time.monotonic() - (worker_api._HEARTBEAT_STALE_AFTER + 1)
        with patch.object(worker_api, "UI_URL", "http://cashpilot-ui:8080"):
            resp = _client().get("/api/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["consecutive_failures"] == "0"
        assert body["last_success_age"].endswith("s")

    def test_a_fresh_success_stamp_is_healthy(self):
        # Negative control for staleness: fresh stamp + zero failures = ok,
        # which is also the boot state (the stamp starts at process start).
        worker_api._consecutive_heartbeat_failures = 0
        worker_api._last_heartbeat_ok = time.monotonic()
        with patch.object(worker_api, "UI_URL", "http://cashpilot-ui:8080"):
            resp = _client().get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "worker": worker_api.WORKER_NAME}


class TestLinkFailureHint:
    def test_explains_a_resolution_failure_once(self, caplog):
        worker_api._link_hint_logged = False
        wrapped = ConnectionError("connect failed")
        wrapped.__cause__ = socket.gaierror(-3, "Try again")

        with (
            patch.object(worker_api, "UI_URL", "http://cashpilot-ui:8080"),
            caplog.at_level(logging.ERROR, logger=worker_api.logger.name),
        ):
            worker_api._log_link_failure_hint(wrapped)
            first = len([r for r in caplog.records if "Cannot resolve" in r.getMessage()])
            # A second failure in the same outage must stay quiet: this used to
            # be logged every 60s for 42 hours, which is how it was ignored.
            worker_api._log_link_failure_hint(wrapped)
            second = len([r for r in caplog.records if "Cannot resolve" in r.getMessage()])

        assert first == 1
        assert second == 1
        msg = next(r.getMessage() for r in caplog.records if "Cannot resolve" in r.getMessage())
        assert "cashpilot-ui" in msg
        assert "NetworkSettings.Networks" in msg

    def test_silent_for_failures_that_are_not_resolution(self, caplog):
        """A refused connection or a timeout has a different cause and fix."""
        worker_api._link_hint_logged = False
        with (
            patch.object(worker_api, "UI_URL", "http://cashpilot-ui:8080"),
            caplog.at_level(logging.ERROR, logger=worker_api.logger.name),
        ):
            worker_api._log_link_failure_hint(TimeoutError("timed out"))

        assert not [r for r in caplog.records if "Cannot resolve" in r.getMessage()]
        assert worker_api._link_hint_logged is False

    def test_finds_the_gaierror_via_implicit_context(self, caplog):
        """An exception raised DURING gaierror handling chains via __context__,
        not __cause__ — the walk must follow both."""
        worker_api._link_hint_logged = False
        try:
            try:
                raise socket.gaierror(-3, "Try again")
            except socket.gaierror:
                raise ConnectionError("failed during resolution cleanup")  # noqa: B904 - implicit context IS the test
        except ConnectionError as e:
            exc = e

        with (
            patch.object(worker_api, "UI_URL", "http://cashpilot-ui:8080"),
            caplog.at_level(logging.ERROR, logger=worker_api.logger.name),
        ):
            worker_api._log_link_failure_hint(exc)

        assert [r for r in caplog.records if "Cannot resolve" in r.getMessage()]

    def test_a_suppressed_context_is_not_blamed_on_dns(self, caplog):
        """`raise X from None` disowns the context on purpose.

        Negative control for the implicit-context test above: same shape, but
        the author said this exception is NOT caused by the resolution failure
        it interrupted — blaming DNS would send the operator down the wrong
        runbook.
        """
        worker_api._link_hint_logged = False
        try:
            try:
                raise socket.gaierror(-3, "Try again")
            except socket.gaierror:
                raise ConnectionError("independent failure") from None
        except ConnectionError as e:
            exc = e

        with (
            patch.object(worker_api, "UI_URL", "http://cashpilot-ui:8080"),
            caplog.at_level(logging.ERROR, logger=worker_api.logger.name),
        ):
            worker_api._log_link_failure_hint(exc)

        assert not [r for r in caplog.records if "Cannot resolve" in r.getMessage()]
        assert worker_api._link_hint_logged is False

    def test_finds_the_gaierror_deep_in_the_chain(self, caplog):
        """httpx wraps the resolution error, so the surface type is not gaierror."""
        worker_api._link_hint_logged = False
        inner = socket.gaierror(-3, "Try again")
        middle = OSError("transport failed")
        middle.__cause__ = inner
        outer = ConnectionError("all connection attempts failed")
        outer.__cause__ = middle

        with (
            patch.object(worker_api, "UI_URL", "http://cashpilot-ui:8080"),
            caplog.at_level(logging.ERROR, logger=worker_api.logger.name),
        ):
            worker_api._log_link_failure_hint(outer)

        assert [r for r in caplog.records if "Cannot resolve" in r.getMessage()]

    def test_survives_a_self_referential_exception_chain(self):
        """A cycle in __cause__/__context__ must not hang the heartbeat loop.

        Run in a watched thread so that if the cycle guard is ever removed this
        test FAILS in five seconds instead of hanging the whole run — a test
        that can only hang is a check that cannot fail.
        """
        worker_api._link_hint_logged = False
        a = ConnectionError("a")
        b = ConnectionError("b")
        a.__cause__ = b
        b.__cause__ = a

        done = threading.Event()

        def _call():
            with patch.object(worker_api, "UI_URL", "http://cashpilot-ui:8080"):
                worker_api._log_link_failure_hint(a)
            done.set()

        t = threading.Thread(target=_call, daemon=True)
        t.start()
        t.join(5)

        assert done.is_set(), "the exception-chain walk did not terminate"
        assert worker_api._link_hint_logged is False


def _drive_heartbeat(outcome, json_body=None, extra_patches=()):
    """Run _send_heartbeat once through a mocked transport.

    outcome: int = HTTP status of the reply; BaseException = raised by post;
    None = generic network failure.
    """
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    if outcome is None:
        client.post = AsyncMock(side_effect=httpx.ConnectError("boom"))
    elif isinstance(outcome, BaseException):
        client.post = AsyncMock(side_effect=outcome)
    else:
        request = httpx.Request("POST", "http://ui:8080/api/workers/heartbeat")
        response = httpx.Response(outcome, request=request, json=json_body or {})
        client.post = AsyncMock(return_value=response)
    with (
        patch.object(worker_api, "_worker_key", "own"),
        patch.object(worker_api, "UI_URL", "http://ui:8080"),
        patch("app.worker_api.orchestrator.get_status", return_value=[]),
        patch("app.worker_api.orchestrator.docker_available", return_value=True),
        patch("app.worker_api.httpx.AsyncClient", return_value=client),
        contextlib.ExitStack() as stack,
    ):
        for p in extra_patches:
            stack.enter_context(p)
        asyncio.run(worker_api._send_heartbeat())
    return worker_api._consecutive_heartbeat_failures


class TestCounterWiring:
    """The counter must move on REAL heartbeat outcomes, not only when a test
    sets it by hand — deleting the increments must fail these tests."""

    def test_failures_count_and_a_success_resets(self):
        worker_api._consecutive_heartbeat_failures = 0
        assert _drive_heartbeat(None) == 1  # network failure path
        assert _drive_heartbeat(500) == 2  # HTTP status failure path
        worker_api._link_hint_logged = True  # as if an outage logged the hint
        assert _drive_heartbeat(200) == 0  # success resets the run...
        assert worker_api._link_hint_logged is False  # ...and re-arms the hint

    def test_a_success_advances_the_staleness_stamp(self):
        worker_api._last_heartbeat_ok = 1.0  # ancient
        _drive_heartbeat(200)
        assert time.monotonic() - worker_api._last_heartbeat_ok < 60

    def test_enrollment_explosion_does_not_count_a_landed_heartbeat(self, caplog):
        """The counter measures "did the UI hear from us", nothing else.

        A UI version skew handing back a malformed worker_key used to raise out
        of the success block into the generic handler, permanently degrading a
        worker whose every heartbeat LANDED — and calling it "connection
        failed" on top.
        """
        worker_api._consecutive_heartbeat_failures = 3
        with caplog.at_level(logging.ERROR, logger=worker_api.logger.name):
            count = _drive_heartbeat(
                200,
                json_body={"worker_key": 12345},
                extra_patches=(
                    patch.object(worker_api, "_save_worker_key", side_effect=TypeError("data must be str")),
                ),
            )
        assert count == 0  # the landed 200 reset the run
        assert worker_api._ui_connected is True
        assert any("Enrollment bookkeeping failed" in r.getMessage() for r in caplog.records)

    def test_the_hint_is_wired_to_the_failure_path(self, caplog):
        """A resolution failure must produce the hint through the REAL call
        site, not only when the helper is invoked directly."""
        worker_api._consecutive_heartbeat_failures = 0
        worker_api._link_hint_logged = False
        err = httpx.ConnectError("resolve failed")
        err.__cause__ = socket.gaierror(-3, "Try again")
        with caplog.at_level(logging.ERROR, logger=worker_api.logger.name):
            count = _drive_heartbeat(err)

        assert count == 1
        assert any("Cannot resolve" in r.getMessage() for r in caplog.records)

    def test_a_reply_rearms_the_hint_for_the_next_outage(self, caplog):
        """Any HTTP reply proves the name resolves, so the outage is over.

        Resetting the flag only on full success left it stuck True through a
        post-outage 401 spell — and the NEXT resolution outage then logged
        nothing, which is the original 42-hour blind spot all over again.
        """

        def _resolution_error():
            err = httpx.ConnectError("resolve failed")
            err.__cause__ = socket.gaierror(-3, "Try again")
            return err

        worker_api._link_hint_logged = False
        with caplog.at_level(logging.ERROR, logger=worker_api.logger.name):
            _drive_heartbeat(_resolution_error())  # outage 1 → hint
            _drive_heartbeat(401)  # name resolves again, auth broken
            assert worker_api._link_hint_logged is False  # re-armed by the reply
            _drive_heartbeat(_resolution_error())  # outage 2 → hint AGAIN

        hints = [r for r in caplog.records if "Cannot resolve" in r.getMessage()]
        assert len(hints) == 2


class TestThresholdContract:
    def test_unhealthy_fires_only_after_the_key_self_heal_could(self):
        """The unhealthy threshold must sit ABOVE the key-discard ladder.

        This repo documents an autoheal sidecar that restarts unhealthy
        containers. A restart resets the in-memory auth-failure ladder while
        the stale key file survives on disk — so if "unhealthy" fired before
        the discard-and-re-enrol step, a locked-out worker would be restart-
        looped at N failures forever and the self-heal could never run.
        """
        assert worker_api._HEARTBEAT_FAILURES_UNHEALTHY_AFTER > worker_api._AUTH_FAILURE_DISCARD_AFTER

    def test_a_real_outage_is_visible_within_a_quarter_hour(self):
        # The operational point of the endpoint: docker ps must tell the truth
        # the same quarter-hour, not eventually.
        assert worker_api._HEARTBEAT_FAILURES_UNHEALTHY_AFTER * worker_api.HEARTBEAT_INTERVAL <= 900
        # The hang path is the rare one and may take a little longer, but it
        # must still surface within 20 minutes.
        assert worker_api._HEARTBEAT_STALE_AFTER <= 1200

    def test_the_staleness_window_also_clears_the_ladder(self):
        """The wall-clock backstop must not pre-empt the cycle-counted ladder.

        The discard ladder is counted in CYCLES, each costing HEARTBEAT_INTERVAL
        plus payload time (stats stretch with fleet size; nvidia-smi may burn a
        10s timeout). If the staleness window were merely threshold x interval,
        ~15s of per-cycle overhead would flip the container unhealthy BEFORE
        failure #10 — restart-looping a locked-out worker through the exact
        hole the 12>10 ordering exists to close. 30s headroom per discard-cycle
        is the tolerance this pins.
        """
        ladder_wall_time = worker_api._AUTH_FAILURE_DISCARD_AFTER * (worker_api.HEARTBEAT_INTERVAL + 30)
        assert ladder_wall_time < worker_api._HEARTBEAT_STALE_AFTER


class TestLogsNeverCarryCredentials:
    """CASHPILOT_UI_URL can embed userinfo (a UI behind reverse-proxy basic
    auth is `https://user:pass@host`), and log lines must never repeat it."""

    def _resolution_failure(self):
        exc = ConnectionError("connect failed")
        exc.__cause__ = socket.gaierror(-3, "Try again")
        return exc

    def test_hint_logs_the_host_not_the_token(self, caplog):
        worker_api._link_hint_logged = False
        with (
            patch.object(worker_api, "UI_URL", "http://secret-token@cashpilot-ui:8080"),
            caplog.at_level(logging.ERROR, logger=worker_api.logger.name),
        ):
            worker_api._log_link_failure_hint(self._resolution_failure())

        msg = next(r.getMessage() for r in caplog.records if "Cannot resolve" in r.getMessage())
        assert "'cashpilot-ui'" in msg
        assert "secret-token" not in caplog.text

    def test_hint_logs_the_host_not_the_username(self, caplog):
        # user:pass form: the old string-split printed the USERNAME as the host.
        worker_api._link_hint_logged = False
        with (
            patch.object(worker_api, "UI_URL", "http://user:hunter2@ui.internal:8080"),
            caplog.at_level(logging.ERROR, logger=worker_api.logger.name),
        ):
            worker_api._log_link_failure_hint(self._resolution_failure())

        msg = next(r.getMessage() for r in caplog.records if "Cannot resolve" in r.getMessage())
        assert "'ui.internal'" in msg
        assert "hunter2" not in caplog.text
        assert "'user'" not in msg

    def test_ui_host_on_a_plain_url_is_unchanged(self):
        # Negative control: no userinfo, nothing to strip.
        with patch.object(worker_api, "UI_URL", "http://cashpilot-ui:8080"):
            assert worker_api._ui_host() == "cashpilot-ui"

    def test_redact_userinfo(self):
        assert worker_api._redact_userinfo("https://user:pass@host:8080/x") == "https://host:8080/x"
        assert worker_api._redact_userinfo("http://token@cashpilot-ui:8080") == "http://cashpilot-ui:8080"
        # Negative control: a URL without credentials passes through untouched.
        assert worker_api._redact_userinfo("http://cashpilot-ui:8080") == "http://cashpilot-ui:8080"

    def test_redact_userinfo_uppercase_scheme(self):
        # httpx accepts and normalizes 'HTTPS://', so this is a working config
        # — and the startup log redacts the RAW env value.
        assert worker_api._redact_userinfo("HTTPS://user:hunter2@ui.internal:8080") == "HTTPS://ui.internal:8080"

    def test_redact_userinfo_password_containing_at(self):
        # An unencoded '@' inside the password must not half-survive: the match
        # runs to the LAST '@' before the path.
        assert worker_api._redact_userinfo("https://user:p@ss@host/x") == "https://host/x"
        # Same property on the schemeless form (the startup-log input): this is
        # the second regex, which no scheme-carrying case can exercise.
        assert worker_api._redact_userinfo("user:p@ss@host:8080") == "host:8080"

    def test_redact_userinfo_inside_a_message(self):
        # httpx's HTTPStatusError message embeds str(request.url) UNREDACTED,
        # so the per-cycle warning must be scrubbed before logging.
        msg = "Client error '401 Unauthorized' for url 'https://user:hunter2@ui.internal/api/workers/heartbeat'"
        out = worker_api._redact_userinfo(msg)
        assert "hunter2" not in out
        assert "https://ui.internal/api/workers/heartbeat" in out
        # Negative control: a message whose URL has no userinfo is untouched.
        plain = "Client error '401 Unauthorized' for url 'https://ui.internal/x'"
        assert worker_api._redact_userinfo(plain) == plain

    def test_failed_heartbeat_warning_never_logs_the_password(self, caplog):
        import httpx

        req = httpx.Request("POST", "https://user:hunter2@ui.internal/api/workers/heartbeat")

        class _RaisingClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **k):
                httpx.Response(401, request=req).raise_for_status()

        async def _noop_status():
            return []

        with (
            patch.object(worker_api, "UI_URL", "https://user:hunter2@ui.internal"),
            patch.object(worker_api.httpx, "AsyncClient", _RaisingClient),
            patch.object(worker_api.orchestrator, "get_status", return_value=[]),
            caplog.at_level(logging.WARNING, logger=worker_api.logger.name),
        ):
            asyncio.run(worker_api._send_heartbeat())

        warning = next(r.getMessage() for r in caplog.records if "Heartbeat failed" in r.getMessage())
        assert "401" in warning
        assert "hunter2" not in caplog.text


class TestPayloadFailuresStillCount:
    def test_a_payload_construction_failure_still_degrades_health(self):
        """An exception BEFORE the POST is still a heartbeat that did not land.

        Payload construction runs outside _send_heartbeat's own try, so it
        escapes to the loop. Without loop-level accounting a worker whose
        egress probe (or any payload dependency) fails every cycle would keep
        answering 200 "ok" forever while never reporting in — the exact
        invisible state /api/health exists to expose.
        """
        worker_api._consecutive_heartbeat_failures = 0
        worker_api._last_error = ""

        async def _boom():
            raise RuntimeError("egress probe exploded")

        async def _run():
            task = asyncio.create_task(worker_api._heartbeat_loop())
            try:
                deadline = time.monotonic() + 10
                while (
                    worker_api._consecutive_heartbeat_failures < worker_api._HEARTBEAT_FAILURES_UNHEALTHY_AFTER
                    and time.monotonic() < deadline
                ):
                    await asyncio.sleep(0.01)
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        with (
            patch.object(worker_api, "UI_URL", "http://cashpilot-ui:8080"),
            patch.object(worker_api, "HEARTBEAT_INTERVAL", 0),
            patch.object(worker_api, "_detect_egress_ip", _boom),
            patch.object(worker_api.orchestrator, "get_status", return_value=[]),
            patch.object(worker_api.orchestrator, "docker_available", return_value=False),
        ):
            asyncio.run(_run())

        assert worker_api._consecutive_heartbeat_failures >= worker_api._HEARTBEAT_FAILURES_UNHEALTHY_AFTER
        assert worker_api._last_error == "internal error preparing the heartbeat"

        with patch.object(worker_api, "UI_URL", "http://cashpilot-ui:8080"):
            resp = _client().get("/api/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["error"] == "internal error preparing the heartbeat"
