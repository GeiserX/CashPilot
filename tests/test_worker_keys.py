"""Worker-side per-worker fleet key: persistence, auth selection, enrollment."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

try:
    import httpx  # noqa: E402
    from fastapi import HTTPException  # noqa: E402

    import app.worker_api as w  # noqa: E402
except ImportError:
    pytest.skip(
        "Requires full app dependencies (fastapi, docker, etc.) — runs in CI",
        allow_module_level=True,
    )


class TestActiveKey:
    def test_prefers_own_key_when_enrolled(self):
        with patch.object(w, "_worker_key", "own"), patch.object(w, "API_KEY", "shared"):
            assert w._active_key() == "own"

    def test_falls_back_to_shared_before_enrollment(self):
        with patch.object(w, "_worker_key", None), patch.object(w, "API_KEY", "shared"):
            assert w._active_key() == "shared"


class TestKeyPersistence:
    def test_save_and_load_round_trip(self, tmp_path):
        f = tmp_path / ".worker_key"
        with patch.object(w, "_WORKER_KEY_FILE", f), patch.object(w, "_worker_key", None):
            w._save_worker_key("k1")
            assert f.read_text() == "k1"
            assert w._load_worker_key() == "k1"

    def test_load_missing_file_is_none(self, tmp_path):
        with patch.object(w, "_WORKER_KEY_FILE", tmp_path / "nope"):
            assert w._load_worker_key() is None


class TestInboundVerify:
    def _req(self, token):
        r = MagicMock()
        r.headers = {"Authorization": f"Bearer {token}"}
        return r

    def test_requires_own_key_once_enrolled(self):
        with patch.object(w, "_worker_key", "own"), patch.object(w, "API_KEY", "shared"):
            assert w._verify_api_key(self._req("own")) is None  # own key accepted
            with pytest.raises(HTTPException) as ei:
                w._verify_api_key(self._req("shared"))  # shared rejected post-cutover
            assert ei.value.status_code == 401

    def test_accepts_shared_before_enrollment(self):
        with patch.object(w, "_worker_key", None), patch.object(w, "API_KEY", "shared"):
            assert w._verify_api_key(self._req("shared")) is None

    def test_503_when_no_key_configured(self):
        with patch.object(w, "_worker_key", None), patch.object(w, "API_KEY", ""):
            with pytest.raises(HTTPException) as ei:
                w._verify_api_key(self._req("anything"))
            assert ei.value.status_code == 503


class TestHeartbeatEnrollment:
    def test_heartbeat_persists_issued_key(self, tmp_path):
        f = tmp_path / ".worker_key"
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"status": "ok", "worker_id": 1, "worker_key": "issued-key"})
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=resp)

        with (
            patch.object(w, "_WORKER_KEY_FILE", f),
            patch.object(w, "_worker_key", None),
            patch.object(w, "UI_URL", "http://ui:8080"),
            patch.object(w, "API_KEY", "shared"),
            patch("app.worker_api.orchestrator.get_status", return_value=[]),
            patch("app.worker_api.orchestrator.docker_available", return_value=True),
            patch("app.worker_api.httpx.AsyncClient", return_value=mock_client),
        ):
            asyncio.run(w._send_heartbeat())
            # The issued key was persisted and adopted.
            assert f.read_text() == "issued-key"
            assert w._worker_key == "issued-key"

    def test_heartbeat_does_not_adopt_key_when_persist_fails(self):
        # Regression: previously the worker adopted the issued key in memory
        # (_worker_key = key) BEFORE attempting to persist it, so a failed
        # write still left the new key active for the rest of this process's
        # life. On restart _load_worker_key() would find nothing on disk and
        # fall back to the shared key -- which the UI (having seen this worker
        # authenticate with its own key) may no longer accept: a lockout.
        fake_file = MagicMock()
        fake_file.parent.mkdir = MagicMock()
        fake_file.write_text = MagicMock(side_effect=OSError("read-only filesystem"))

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"status": "ok", "worker_id": 1, "worker_key": "issued-key"})
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=resp)

        with (
            patch.object(w, "_WORKER_KEY_FILE", fake_file),
            patch.object(w, "_worker_key", None),
            patch.object(w, "UI_URL", "http://ui:8080"),
            patch.object(w, "API_KEY", "shared"),
            patch("app.worker_api.orchestrator.get_status", return_value=[]),
            patch("app.worker_api.orchestrator.docker_available", return_value=True),
            patch("app.worker_api.httpx.AsyncClient", return_value=mock_client),
        ):
            asyncio.run(w._send_heartbeat())
            # NOT adopted -- still None, so _active_key() keeps using the shared key.
            assert w._worker_key is None
            assert w._active_key() == "shared"


class TestKeyPersistFailure:
    def test_persist_failure_returns_false_and_does_not_adopt(self):
        fake_file = MagicMock()
        fake_file.parent.mkdir = MagicMock()
        fake_file.write_text = MagicMock(side_effect=OSError("disk full"))
        with patch.object(w, "_WORKER_KEY_FILE", fake_file), patch.object(w, "_worker_key", None):
            result = w._save_worker_key("new-key")
            assert result is False
            assert w._worker_key is None

    def test_persist_success_returns_true_and_adopts(self, tmp_path):
        f = tmp_path / ".worker_key"
        with patch.object(w, "_WORKER_KEY_FILE", f), patch.object(w, "_worker_key", None):
            result = w._save_worker_key("new-key")
            assert result is True
            assert w._worker_key == "new-key"
            assert f.read_text() == "new-key"


class TestHeartbeatErrorClassification:
    """worker_api.py:163 nit: distinguish auth rejection (401/403) from network errors."""

    def _client_returning_status(self, status_code: int):
        request = httpx.Request("POST", "http://ui:8080/api/workers/heartbeat")
        response = httpx.Response(status_code, request=request)
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=response)
        return mock_client

    def _run_heartbeat_with(self, mock_client):
        with (
            patch.object(w, "_worker_key", "own"),
            patch.object(w, "UI_URL", "http://ui:8080"),
            patch("app.worker_api.orchestrator.get_status", return_value=[]),
            patch("app.worker_api.orchestrator.docker_available", return_value=True),
            patch("app.worker_api.httpx.AsyncClient", return_value=mock_client),
        ):
            asyncio.run(w._send_heartbeat())

    def test_401_sets_distinct_auth_rejected_message(self):
        self._run_heartbeat_with(self._client_returning_status(401))
        assert w._last_error == "authentication rejected (401)"
        assert w._ui_connected is False

    def test_403_sets_distinct_auth_rejected_message(self):
        self._run_heartbeat_with(self._client_returning_status(403))
        assert w._last_error == "authentication rejected (403)"

    def test_other_http_error_keeps_generic_message(self):
        self._run_heartbeat_with(self._client_returning_status(500))
        assert w._last_error == "connection failed"

    def test_network_error_keeps_generic_message(self):
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        self._run_heartbeat_with(mock_client)
        assert w._last_error == "connection failed"


class TestClientId:
    """CashPilot-ng1: stable worker identity (client_id) decoupled from the display name."""

    def test_returns_existing_id_file(self, tmp_path):
        f = tmp_path / ".worker_id"
        f.write_text("stable-123\n")
        with patch.object(w, "_WORKER_ID_FILE", f):
            assert w._load_or_create_client_id() == "stable-123"

    def test_mints_random_id_for_brand_new_worker(self, tmp_path):
        f = tmp_path / ".worker_id"
        with patch.object(w, "_WORKER_ID_FILE", f), patch.object(w, "_worker_key", None):
            cid = w._load_or_create_client_id()
            assert cid == f.read_text()  # persisted
            # A fresh random id, never the mutable display name.
            assert cid != w.WORKER_NAME
            assert len(cid) >= 16

    def test_preserves_name_identity_for_already_enrolled_worker(self, tmp_path):
        # Migration: an already-enrolled worker (has a key) with no id file yet keeps the
        # identity the UI knows it by (WORKER_NAME), so the upgrade never re-enrolls it.
        f = tmp_path / ".worker_id"
        with (
            patch.object(w, "_WORKER_ID_FILE", f),
            patch.object(w, "_worker_key", "already-enrolled-key"),
            patch.object(w, "WORKER_NAME", "my-host"),
        ):
            assert w._load_or_create_client_id() == "my-host"
            assert f.read_text() == "my-host"

    def test_id_is_stable_across_calls(self, tmp_path):
        f = tmp_path / ".worker_id"
        with patch.object(w, "_WORKER_ID_FILE", f), patch.object(w, "_worker_key", None):
            first = w._load_or_create_client_id()
            assert w._load_or_create_client_id() == first

    def test_persist_failure_falls_back_to_in_memory_id(self):
        fake = MagicMock()
        fake.parent.mkdir = MagicMock()
        fake.write_text = MagicMock(side_effect=OSError("read-only fs"))
        fake.read_text = MagicMock(side_effect=OSError("missing"))
        with patch.object(w, "_WORKER_ID_FILE", fake), patch.object(w, "_worker_key", None):
            cid = w._load_or_create_client_id()
            # A usable id is still returned even though it could not be persisted.
            assert len(cid) >= 16

    def test_heartbeat_payload_includes_client_id(self, tmp_path):
        captured: dict = {}
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"status": "ok", "worker_id": 1})
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        async def _post(_url, **kwargs):
            captured.update(kwargs.get("json", {}))
            return resp

        mock_client.post = AsyncMock(side_effect=_post)
        with (
            patch.object(w, "_WORKER_KEY_FILE", tmp_path / ".worker_key"),
            patch.object(w, "_worker_key", None),
            patch.object(w, "CLIENT_ID", "cid-abc"),
            patch.object(w, "UI_URL", "http://ui:8080"),
            patch.object(w, "API_KEY", "shared"),
            patch("app.worker_api.orchestrator.get_status", return_value=[]),
            patch("app.worker_api.orchestrator.docker_available", return_value=True),
            patch("app.worker_api.httpx.AsyncClient", return_value=mock_client),
        ):
            asyncio.run(w._send_heartbeat())
        # Identity travels as client_id; name remains present but display-only.
        assert captured.get("client_id") == "cid-abc"
        assert captured.get("name") == w.WORKER_NAME


class TestClientIdIsNotTheContainerHostname:
    """Regression: a worker's identity must survive a container recreate.

    Docker names a container after the first 12 hex chars of its ID, and that
    changes on every recreate — which is what an image bump does. Reusing it as
    the identity minted a new client_id each upgrade; the UI then refused the
    worker's still-valid per-worker key as coming from an unknown client, so
    every heartbeat 401'd while the service containers kept earning — a silent
    fleet outage. Hit in production upgrading 1.0.0 -> 1.4.1.
    """

    def test_container_id_name_is_rejected_as_identity(self, tmp_path):
        f = tmp_path / ".worker_id"
        with (
            patch.object(w, "_WORKER_ID_FILE", f),
            patch.object(w, "_worker_key", "already-enrolled-key"),
            patch.object(w, "WORKER_NAME", "515ccbc46cd9"),
            patch.object(w.Path, "exists", lambda self: True),
        ):
            cid = w._load_or_create_client_id()
        assert cid != "515ccbc46cd9", "must not adopt an ephemeral container ID"
        assert len(cid) == 32

    def test_real_hostname_still_migrates(self, tmp_path):
        # Bare metal / VM: gethostname() is stable, so the migration is correct
        # and must keep working — this is the row-preserving path.
        f = tmp_path / ".worker_id"
        with (
            patch.object(w, "_WORKER_ID_FILE", f),
            patch.object(w, "_worker_key", "already-enrolled-key"),
            patch.object(w, "WORKER_NAME", "watchtower"),
        ):
            assert w._load_or_create_client_id() == "watchtower"

    def test_container_id_shape_outside_docker_still_migrates(self, tmp_path):
        # A host legitimately named like a hex string is not a container.
        f = tmp_path / ".worker_id"
        with (
            patch.object(w, "_WORKER_ID_FILE", f),
            patch.object(w, "_worker_key", "already-enrolled-key"),
            patch.object(w, "WORKER_NAME", "515ccbc46cd9"),
            patch.object(w.Path, "exists", lambda self: False),
        ):
            assert w._load_or_create_client_id() == "515ccbc46cd9"

    def test_persisted_id_wins_over_everything(self, tmp_path):
        f = tmp_path / ".worker_id"
        f.write_text("159d39365879")
        with (
            patch.object(w, "_WORKER_ID_FILE", f),
            patch.object(w, "WORKER_NAME", "something-else"),
        ):
            assert w._load_or_create_client_id() == "159d39365879"

    def test_first_run_persists_id_so_next_recreate_reuses_it(self, tmp_path):
        f = tmp_path / ".worker_id"
        with (
            patch.object(w, "_WORKER_ID_FILE", f),
            patch.object(w, "_worker_key", None),
            patch.object(w, "WORKER_NAME", "aaaaaaaaaaaa"),
            patch.object(w.Path, "exists", lambda self: True),
        ):
            first = w._load_or_create_client_id()
            assert f.read_text() == first
            assert w._load_or_create_client_id() == first

    def test_ephemeral_detection(self):
        with patch.object(w.Path, "exists", lambda self: True):
            assert w._name_is_ephemeral("515ccbc46cd9")
            assert not w._name_is_ephemeral("watchtower")
            assert not w._name_is_ephemeral("515CCBC46CD9")
            assert not w._name_is_ephemeral("515ccbc46cd")


class TestAuthFailureAlarmCounter:
    """ "Consecutive" must mean consecutive, or the alarm fires on a flaky link."""

    def _run(self, statuses):
        """Drive _send_heartbeat once per status. None = network failure."""
        w._consecutive_auth_failures = 0
        for st in statuses:
            if st is None:
                client = MagicMock()
                client.__aenter__ = AsyncMock(return_value=client)
                client.__aexit__ = AsyncMock(return_value=False)
                client.post = AsyncMock(side_effect=httpx.ConnectError("boom"))
            else:
                request = httpx.Request("POST", "http://ui:8080/api/workers/heartbeat")
                response = httpx.Response(st, request=request, json={})
                client = MagicMock()
                client.__aenter__ = AsyncMock(return_value=client)
                client.__aexit__ = AsyncMock(return_value=False)
                client.post = AsyncMock(return_value=response)
            with (
                patch.object(w, "_worker_key", "own"),
                patch.object(w, "UI_URL", "http://ui:8080"),
                patch("app.worker_api.orchestrator.get_status", return_value=[]),
                patch("app.worker_api.orchestrator.docker_available", return_value=True),
                patch("app.worker_api.httpx.AsyncClient", return_value=client),
            ):
                asyncio.run(w._send_heartbeat())
        return w._consecutive_auth_failures

    def test_three_straight_401s_reach_the_alarm(self):
        assert self._run([401, 401, 401]) == w._AUTH_FAILURE_ALARM_AFTER

    def test_a_timeout_between_401s_breaks_the_run(self):
        # 401 -> timeout -> 401 -> 500 -> 401 is a flaky link, not an identity mismatch.
        assert self._run([401, None, 401, 500, 401]) == 1

    def test_a_non_401_status_breaks_the_run(self):
        assert self._run([401, 401, 503, 401]) == 1

    def test_success_resets(self):
        assert self._run([401, 401, 200]) == 0


class TestTheAlarmActuallyFires(TestAuthFailureAlarmCounter):
    """The counter reaching three is not the point — the operator being told is.

    The tests above assert only the counter, so the alarm block sat in the
    branch that had just zeroed the counter (`0 == 3`) and was unreachable dead
    code, while a test named for it passed. This is the failure it exists for:
    a worker recreated under a new container hostname gets a new client_id, the
    UI rejects its key forever, and the service containers keep earning — so
    nothing else surfaces it.
    """

    def _alarms(self, statuses, caplog):
        import logging

        with caplog.at_level(logging.ERROR, logger="app.worker_api"):
            caplog.clear()
            self._run(statuses)
        # Matched on "Rejected N times", which both lockout messages share.
        # It used to match "does not recognise client_id" — the wording of an
        # alarm that told the operator to edit /data/.worker_id, which is the
        # fix for neither lockout that actually happens (CashPilot-65s).
        return [r for r in caplog.records if "Rejected" in r.getMessage()]

    def test_three_straight_401s_tell_the_operator(self, caplog):
        assert len(self._alarms([401, 401, 401], caplog)) == 1

    def test_it_names_the_file_that_has_to_go(self, caplog):
        """The key, not the id.

        This worker holds a key that is being refused, so the recovery is to
        discard it — either by waiting for the automatic re-enrolment or by
        deleting the file. The id is fine in both real lockouts.
        """
        message = self._alarms([401, 401, 401], caplog)[0].getMessage()
        assert str(w._WORKER_KEY_FILE) in message, "the operator is not told which file to remove"
        assert "re-enrol" in message, "nothing says the worker will recover on its own"

    def test_it_stays_quiet_below_the_threshold(self, caplog):
        """Two 401s across a restart are ordinary, not an identity mismatch."""
        assert self._alarms([401, 401], caplog) == []

    def test_it_says_it_once_and_not_on_every_subsequent_failure(self, caplog):
        """`==`, not `>=`: an hourly heartbeat would otherwise log this forever."""
        assert len(self._alarms([401] * 8, caplog)) == 1

    def test_a_broken_run_never_raises_it(self, caplog):
        """A flaky link is not a lockout, and must not be reported as one."""
        assert self._alarms([401, None, 401, 500, 401], caplog) == []


class TestRemovingAWorkerDoesNotLockTheHostOut(TestAuthFailureAlarmCounter):
    """CashPilot-u10: "remove it and it re-enrols" was not true of any code.

    Removing a worker in the fleet dashboard deletes its row and its key on the
    UI side. The worker keeps sending the key it persisted at /data/.worker_key
    — _active_key() returns `_worker_key or API_KEY`, so once that file exists
    the shared key is never used again — and 401s forever, on a host whose
    service containers are still running and still earning. docs/upgrade-v1.md
    promised removal "clears its enrollment so the shared key is accepted
    again"; nothing cleared anything. The only real recovery was SSHing in to
    delete a file documented nowhere.
    """

    def _run_with_real_key_file(self, statuses, tmp_path):
        """Like _run, but with a key that can actually be discarded.

        The inherited harness patches _worker_key with patch.object, which
        restores the global when the block exits — so a discard inside the
        heartbeat would be silently undone and this whole class would pass
        against unmodified code.
        """
        key_file = tmp_path / ".worker_key"
        key_file.write_text("own")
        saved = w._worker_key
        w._worker_key = "own"
        w._consecutive_auth_failures = 0
        try:
            for st in statuses:
                request = httpx.Request("POST", "http://ui:8080/api/workers/heartbeat")
                response = httpx.Response(st, request=request, json={})
                client = MagicMock()
                client.__aenter__ = AsyncMock(return_value=client)
                client.__aexit__ = AsyncMock(return_value=False)
                client.post = AsyncMock(return_value=response)
                with (
                    patch.object(w, "_WORKER_KEY_FILE", key_file),
                    patch.object(w, "UI_URL", "http://ui:8080"),
                    patch("app.worker_api.orchestrator.get_status", return_value=[]),
                    patch("app.worker_api.orchestrator.docker_available", return_value=True),
                    patch("app.worker_api.httpx.AsyncClient", return_value=client),
                ):
                    asyncio.run(w._send_heartbeat())
            return {"key": w._worker_key, "file_exists": key_file.exists()}
        finally:
            w._worker_key = saved
            w._consecutive_auth_failures = 0

    def test_sustained_rejection_discards_the_stale_key(self, tmp_path):
        out = self._run_with_real_key_file([401] * w._AUTH_FAILURE_DISCARD_AFTER, tmp_path)
        assert out["key"] is None, "the worker is still sending the key the UI deleted"
        assert not out["file_exists"], "the stale key survives a restart"

    def test_it_then_re_enrols_with_the_shared_key(self, tmp_path):
        """Discarding is only useful if the next heartbeat can authenticate."""
        self._run_with_real_key_file([401] * w._AUTH_FAILURE_DISCARD_AFTER, tmp_path)
        with patch.object(w, "_worker_key", None), patch.object(w, "API_KEY", "shared"):
            assert w._active_key() == "shared"

    def test_a_few_401s_do_not_discard_anything(self, tmp_path):
        """The control that keeps this bounded.

        Discarding on the first failure would re-enrol on any blip and widen the
        window in which the shared key is accepted — the exact weakening that
        per-worker keys exist to close.
        """
        out = self._run_with_real_key_file([401] * (w._AUTH_FAILURE_DISCARD_AFTER - 1), tmp_path)
        assert out["key"] == "own"
        assert out["file_exists"]

    def test_the_discard_threshold_is_above_the_alarm(self):
        """The operator is told first, and only then does the key go."""
        assert w._AUTH_FAILURE_DISCARD_AFTER > w._AUTH_FAILURE_ALARM_AFTER

    def test_a_flaky_link_never_discards(self, tmp_path):
        """Non-consecutive failures are a network problem, not a deleted row."""
        statuses = [401, 500] * w._AUTH_FAILURE_DISCARD_AFTER
        out = self._run_with_real_key_file(statuses, tmp_path)
        assert out["key"] == "own"
        assert out["file_exists"]

    def test_a_success_before_the_threshold_saves_the_key(self, tmp_path):
        statuses = [401] * (w._AUTH_FAILURE_DISCARD_AFTER - 1) + [200, 401]
        out = self._run_with_real_key_file(statuses, tmp_path)
        assert out["key"] == "own"
        assert out["file_exists"]

    def test_it_says_why_in_the_log(self, tmp_path, caplog):
        """A key vanishing without explanation is its own support ticket."""
        import logging

        with caplog.at_level(logging.WARNING, logger="app.worker_api"):
            caplog.clear()
            self._run_with_real_key_file([401] * w._AUTH_FAILURE_DISCARD_AFTER, tmp_path)
        messages = [r.getMessage() for r in caplog.records]
        assert any("Discarded" in m and "Re-enrolling" in m for m in messages)

    def test_an_undeletable_key_keeps_the_key_rather_than_pretending(self, tmp_path, caplog):
        """A read-only /data must not leave us believing we re-enrolled.

        Zeroing _worker_key while the file survives would re-enrol now and then
        load the stale key back on the next restart, which is worse than not
        trying: the same lockout returns with no failures leading up to it.
        """
        import logging

        key_file = tmp_path / ".worker_key"
        key_file.write_text("own")
        saved = w._worker_key
        w._worker_key = "own"
        try:
            with (
                patch.object(w, "_WORKER_KEY_FILE", key_file),
                patch.object(w.Path, "unlink", side_effect=OSError("read-only file system")),
                caplog.at_level(logging.ERROR, logger="app.worker_api"),
            ):
                caplog.clear()
                w._discard_worker_key("test")
            assert w._worker_key == "own", "we claimed to re-enrol while the key is still on disk"
            assert key_file.exists()
            assert any("Delete it by hand" in r.getMessage() for r in caplog.records)
        finally:
            w._worker_key = saved


class TestTheRecoveryIsDocumentedWhereItIsNeeded:
    """The bead is as much about the two false promises as about the code."""

    def test_the_upgrade_doc_no_longer_promises_the_shared_key_is_accepted(self):
        from pathlib import Path

        text = Path(__file__).resolve().parents[1].joinpath("docs/upgrade-v1.md").read_text(encoding="utf-8")
        assert "so the shared key is accepted again" not in text
        assert "/data/.worker_key" in text, "the manual recovery must be written down somewhere"

    def test_the_confirm_dialog_says_the_worker_keeps_running(self):
        from pathlib import Path

        text = Path(__file__).resolve().parents[1].joinpath("app/templates/fleet.html").read_text(encoding="utf-8")
        assert "This will unregister it from the fleet." not in text
        assert "re-enrol on its own" in text
